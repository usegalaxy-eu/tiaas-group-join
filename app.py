from flask import Flask
from bioblend import galaxy
import codecs
from functools import wraps
from flask import redirect, make_response
from flask import request, abort
from flask_sqlalchemy import SQLAlchemy
from Crypto.Cipher import Blowfish
import os
import yaml

app = Flask(__name__)

default_path = os.path.join(app.root_path, 'config.yaml')
with open(os.environ.get('CONFIG_PATH', default_path), 'r') as f:
    c = yaml.load(f)
    for key in c.keys():
        app.config[key] = c[key]

    app.config['gi'] = galaxy.GalaxyInstance(**app.config['galaxy']['api'])

app.config['SQLALCHEMY_DATABASE_URI'] = app.config['db']
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
cipher = Blowfish.new(app.config['galaxy']['idsecret'])
gi = app.config['gi']

LOGIN_FAILURE = """Please log in to Galaxy first: <a href='{url}/login'>{url}/login</a>""".format(url=app.config['galaxy']['api']['url'])


def unauthorized(message="Unauthorized", html=False):
    if html:
        message = '<html><head></head><body>' + message + '</body></html>'

    return abort(make_response(message, 401))


def authenticate():
    def wrapper(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if app.config['galaxy']['cookiename'] not in request.cookies:
                return unauthorized(LOGIN_FAILURE, html=True)
            galaxy_encoded_session_id = codecs.decode(request.cookies[app.config['galaxy']['cookiename']], 'hex')
            galaxy_session_id = cipher.decrypt(galaxy_encoded_session_id).decode('utf-8').lstrip('!')
            results = db.engine.execute("select user_id from galaxy_session where session_key = '%s'" % galaxy_session_id)
            users = list(results)
            if len(users) == 0:
                return unauthorized(LOGIN_FAILURE, html=True)
            user = users[0]
            # fetch user_id attr
            user_id = user[0]
            if user_id is None:
                return unauthorized(LOGIN_FAILURE, html=True)

            # Now, encode it.
            s = str.encode(str(user_id))
            s = (b"!" * (8 - len(s) % 8)) + s
            user_id = codecs.encode(cipher.encrypt(s), 'hex')
            # Wipe out / overwrite user_id
            kwargs['user_id'] = user_id.decode('utf-8')

            return f(*args, **kwargs)
        return wrapped
    return wrapper


@app.route('/join-training/<training_id>', methods=['GET'])
@authenticate()
def join_training(training_id, user_id=None):
    if not user_id:
        return unauthorized()

    # Try and catch common mistakes
    training_id = training_id.lower()

    # If we don't know this training, reject
    if training_id not in app.config['trainings']:
        return 'Unknown training. Please check the URL.'

    training_role_name = 'training-%s' % training_id
    # Otherwise, training is OK + they are a valid user.
    # We need to add them to the role

    ################
    # BEGIN UNSAFE #
    ################
    # Create role if need to.
    current_roles = gi.roles.get_roles()
    role_exists = any([training_role_name == x['name'] for x in current_roles])
    if not role_exists:
        role_id = gi.roles.create_role(training_role_name, description='Autogenerated role')[0]['id']
    else:
        role_id = [x for x in current_roles if training_role_name == x['name']][0]['id']

    # Create group if need to.
    current_groups = gi.groups.get_groups()
    group_exists = any([training_role_name == x['name'] for x in current_groups])
    if not group_exists:
        group_id = gi.groups.create_group(training_role_name)[0]['id']
    else:
        group_id = [x for x in current_groups if training_role_name == x['name']][0]['id']
    ################
    #  END UNSAFE  #
    ################

    # Ensure the role is attached to the group since that is what adds the user
    # to the training group
    gi.groups.add_group_role(group_id, role_id)

    # Lastly, add the user to the group
    # print('Adding %s to %s (%s)' % (user_id, group_id, training_role_name))
    gi.groups.add_group_user(group_id, user_id)

    return redirect(app.config['galaxy']['api']['url'], code=302)
