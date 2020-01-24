"""Configuration for the database and connections to it
"""
import os

# User to connect to database with. Can be None to connect as current user
user = os.environ.get('POSTGRES_USER')

# Password to connect with. Can be None if no password set or using identd or
# other passwordless authentication method
password = os.environ.get('POSTGRES_PASS')

# Server to connect to. If unset, will attempt to find database locally
server = os.environ.get('POSTGRES_SRVR') or 'localhost'

# Name of database to connect to
db_name = os.environ.get('POSTGRES_DATABASE') or 'dashboard'

SQLALCHEMY_DATABASE_URI = 'postgresql://{user}:{pwd}@{srvr}/{db}'.format(
    user=user,
    pwd=password,
    srvr=server,
    db=db_name)

# Timezone offset used for timezone aware timestamps. Default is Eastern time
# Used by psycopg2.tz.FixedOffsetTimezone in the models
TZ_OFFSET = os.environ.get('TIMEZONE') or -240

# Not needed and uses more memory. Just disable it.
SQLALCHEMY_TRACK_MODIFICATIONS = False
