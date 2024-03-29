[Replaced by galaxyproject/tiaas2](https://github.com/galaxyproject/tiaas2)

![](./images/logo.png)

# TIaaS / Galaxy Group Join Service

This is a simple service which allows users visiting a specific URL like:

```
https://usegalaxy.eu/join-training/denbi-summer-school
```

to be automatically added to a group named `training-denbi-summer-school` (and
a role automatically created.) It works on the basis of running underneath the
path prefix of Galaxy and so having access to the Galaxy session cookie. This
is decoded into a user id + the part after `/join-training/` decoded into a
group name, and this change is made.

## Status Page

For teachers giving trainings, we now offer a "status" page where they can see
the training queue of their class.

![](images/queue-status.png)

## Configuration

```
---
DEBUG: false

# database URL
db: 'postgresql://postgres:postgres@localhost/postgres?sslmode=disable'

# Where to send them once they've successfully joined the training
redirect_location: 'http://localhost'

# Galaxy information
galaxy:
    cookiename: galaxysession
    idsecret: 'some very secret key'

# List of valid training identifiers
trainings:
    - denbi-summer-school
```

## Deploying

- [Ansible Role](https://github.com/usegalaxy-eu/ansible-tiaas-group-join/)

## License

AGPL-3.0
