from flask import Flask
import codecs
from functools import wraps
from flask import render_template
from flask import request
from flask_sqlalchemy import SQLAlchemy
from Crypto.Cipher import Blowfish
import os
import yaml

app = Flask(__name__)

default_path = os.path.join(app.root_path, 'config.yaml')
with open(os.environ.get('CONFIG_PATH', default_path), 'r') as f:
    c = yaml.safe_load(f)
    for key in c.keys():
        app.config[key] = c[key]

# Make things safe for whatever they enter
app.config['trainings'] = [x.lower()  for x in app.config['trainings']]
app.config['SQLALCHEMY_DATABASE_URI'] = app.config['db']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
cipher = Blowfish.new(app.config['galaxy']['idsecret'])

LOGIN_FAILURE = """Please log in to Galaxy first: <a href="{url}/login">{url}/login</a>""".format(url=app.config['redirect_location'])

TRAINING_QUEUE_HEADERS = ['state', 'job_runner_external_id', 'tool_id', 'user_id', 'create_time']
TRAINING_QUEUE_QUERY = """
SELECT
        job.state,
        job.job_runner_external_id AS extid,
        job.tool_id,
        substring(md5(COALESCE(galaxy_user.username, 'Anonymous') || now()::date), 0, 12),
        date_trunc('second', job.create_time) AS created
FROM
        job, galaxy_user
WHERE
        job.user_id = galaxy_user.id
        AND job.create_time > (now() AT TIME ZONE 'UTC' - '6 hours'::interval)
        AND galaxy_user.id
                IN (
                                SELECT
                                        galaxy_user.id
                                FROM
                                        galaxy_user, user_group_association, galaxy_group
                                WHERE
                                        galaxy_group.name = 'training-%s'
                                        AND galaxy_group.id = user_group_association.group_id
                                        AND user_group_association.user_id = galaxy_user.id
                        )
ORDER BY
        job.create_time DESC
LIMIT 300
"""


def unauthorized(message="Unauthorized"):
    return template('error.html', message=message), 401


def known_training(query):
    return query in app.config['trainings']


def authenticate():
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if app.config['galaxy']['cookiename'] not in request.cookies:
                return unauthorized(LOGIN_FAILURE)
            galaxy_encoded_session_id = codecs.decode(request.cookies[app.config['galaxy']['cookiename']], 'hex')
            galaxy_session_id = cipher.decrypt(galaxy_encoded_session_id).decode('utf-8').lstrip('!')
            results = db.engine.execute("select user_id, username from galaxy_session join galaxy_user on galaxy_session.user_id = galaxy_user.id  where session_key = '%s'" % galaxy_session_id)
            users = list(results)
            if len(users) == 0:
                return unauthorized(LOGIN_FAILURE)
            user = users[0]
            # fetch user_id attr
            user_id = user[0]

            if user_id is None:
                return unauthorized(LOGIN_FAILURE)
            user_name = user[1]

            # Now, encode it.
            kwargs['user_id'] = user_id
            kwargs['user_name'] = user_name.decode('utf-8')

            return f(*args, **kwargs)
        return wrapped
    return wrapper


def template(name, **context):
    return render_template(name, config=app.config, **context)


def get_roles():
    roles = db.engine.execute("select id, name from role where type in ('admin', 'system') and name like 'training-%%'")
    for role in roles:
        yield {'id': role[0], 'name': role[1]}

def create_role(training_id):
    db.engine.execute("insert into role (name, description, type, create_time, update_time, deleted) values ('%s', 'Autogenerated role', 'system', now(), now(), false)" % training_id)
    # get the role back
    role = db.engine.execute("select id from role where name = '%s'"  % training_id)
    for r in role:
        return r[0]
    return -1


def get_jobs(training_id):
    jobs = db.engine.execute(TRAINING_QUEUE_QUERY  % training_id)
    print(TRAINING_QUEUE_QUERY % training_id)
    for job in jobs:
        yield dict(zip(TRAINING_QUEUE_HEADERS, job))

def get_groups():
    groups = db.engine.execute("select id, name from galaxy_group where name like 'training-%%'")
    for group in groups:
        yield {'id': group[0], 'name': group[1]}

def create_group(training_id, role_id):
    db.engine.execute("insert into galaxy_group (name, create_time, update_time, deleted) values ('%s', now(), now(), false)" % training_id)
    # get the role back
    groups = db.engine.execute("select id from galaxy_group where name = '%s'"  % training_id)
    group_id = -1
    for group in groups:
        group_id = group[0]
    db.engine.execute("insert into group_role_association (group_id, role_id, create_time, update_time) values (%s, %s, now(), now())" % (group_id, role_id))
    return group_id

def add_group_user(group_id, user_id):
    db.engine.execute("insert into user_group_association (user_id, group_id, create_time, update_time) values (%s, %s, now(), now())" % (user_id, group_id))


@app.route('/join-training/<training_id>', methods=['GET'])
@authenticate()
def join_training(training_id, user_id=None, user_name=None):
    if not user_id:
        return unauthorized()

    # Try and catch common mistakes
    training_id = training_id.lower()

    # If we don't know this training, reject
    if not known_training(training_id):
        return template('error.html', message='Unknown training. Please check the URL'), 404

    training_role_name = 'training-%s' % training_id
    # Otherwise, training is OK + they are a valid user.
    # We need to add them to the role

    ################
    # BEGIN UNSAFE #
    ################
    # Create role if need to.
    current_roles = list(get_roles())
    role_exists = any([training_role_name == x['name'] for x in current_roles])

    if not role_exists:
        role_id = create_role(training_role_name)
    else:
        role_id = [x for x in current_roles if training_role_name == x['name']][0]['id']

    # Create group if need to.
    current_groups = list(get_groups())
    group_exists = any([training_role_name == x['name'] for x in current_groups])
    if not group_exists:
        group_id = create_group(training_role_name, role_id)
    else:
        group_id = [x for x in current_groups if training_role_name == x['name']][0]['id']

    ################
    #  END UNSAFE  #
    ################

    add_group_user(group_id, user_id)

    return template('me.html', user_id=user_id, user_name=user_name, welcome_to=training_id)


@app.route('/join-training/<training_id>/status', methods=['GET'])
@authenticate()
#@require_admin
def training_status(training_id, user_id=None, user_name=None):
    jobs = list(get_jobs(training_id))
    jobs_overview = {}
    state_summary = {}
    for job in jobs:
        tool_id = job['tool_id']
        if tool_id not in jobs_overview:
            jobs_overview[tool_id] = {
                'ok': 0,
                'new': 0,
                'error': 0,
                'queued': 0,
            }

        if job['state'] in ('ok', 'new', 'error', 'queued'):
            jobs_overview[tool_id][job['state']] += 1

        if job['state'] not in state_summary:
            state_summary[job['state']] = 0
        state_summary[job['state']] += 1

    return template('status.html', jobs=jobs, job_summary=jobs_overview, state_summary=state_summary)
