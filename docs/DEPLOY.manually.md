Manual Server Deploy Instructions
==================================

Linux is currently the only supported development platform. Theoretically this codebase should work on other platforms, but this has not been tested. These instructions only cover the base ubersystem without any plugins, YMMV.

This method of installation uses postgres, which is what the actual production server uses, and so should be more supported (but is more complex to set up). A simpler alternate installation method, using sqlite, is at the bottom of this document.

Here's what you need installed before you can run this:
* Python >= 3.12 (with source headers) (ppa:deadsnakes/ppa)
* Postgresql 9.0 or later
* Rabbitmq-server (default configuration will work!)
* Redis (default configuration will work!)
* (Optional, but helpful) Nginx

Shopping list:
`postgresql python3.12 python3.12-venv rabbitmq-server redis`

Now let's continue by getting all of the Python dependencies installed.  We'll clone the repo, make a virtualenv, install distribute, and then install all of our Python dependencies and allowing execution of the uber-wrapper:

```bash
$ git clone https://github.com/magfest/ubersystem /app # or your fork. The contents of the repo should live inside /app in your root directory!
$ cd /app
$ python3.12 -m venv env
$ source ./env/bin/activate # verify it works with 'which python3'
$ python3 -m pip install --upgrade pip
$ pip install -r requirements.txt
$ sudo chmod 755 uber-wrapper.sh
```

Let's get rabbitmq set up with our celery user
```bash
$ sudo rabbitmqctl add_user celery celery
$ sudo rabbitmqctl add_vhost uber
$ sudo rabbitmqctl set_permissions -p uber celery ".*" ".*" ".*"
```

Now we need to create a Postgresql database.  The default username, password, and database name is "uber_db", so we'll go ahead and do that, e.g.

```bash
$ sudo -i
$ sudo -i -u postgres
$ createuser --superuser --pwprompt uber_db
$ createdb --owner=uber_db uber_db
```

Lastly, let's set up our ENV file, feel free to change items here such as the default port:

```ini
# UBER_CONFIG_FILES=/app/uber.ini -- For big uber configurations!
PYTHONSTARTUP=/app/.pythonstartup.py
DB_CONNECTION_STRING=postgresql://uber_db:uber_db@localhost:5432/uber_db
uber_cherrypy_server_socket_port=80
uber_cherrypy_server_socket_host=0.0.0.0
uber_cherrypy_server_socket_timeout=1
uber_cherrypy_tools_sessions_host=localhost
uber_cherrypy_tools_sessions_prefix=uber
uber_cherrypy_tools_sessions_storage_type=redis
uber_loggers_cherrypy_access=DEBUG
uber_redis_host=localhost
uber_secret_broker_url=amqp://celery:celery@localhost:5672/uber
uber_hostname=localhost
```

Now we can try it out and actually start the server:

```bash
$ ./uber-wrapper.sh uber
```

Now we can go to http://localhost/ and see the landing page if everyting works!

You can create the first test account at the url http://localhost/accounts/insert_test_admin and log in with the email address "magfest@example.com" and the password "magfest".

If you'd like to override any of the default configuration settings, you can create a "uber.ini" file in the top-level directory of the repo, and any values you put there will override the default values. Check out the `configspec.ini` for a good idea on what can be configured, or going even deeper you can check the configuration.md file.

If you'd like to insert about 10,000 attendees with realistic shifts and whatnot, you can run the following command (warning, this takes 5-10 minutes to insert everything):

```bash
$ python uber/tests/import_test_data.py
```

Alternatively, you could insert directly with the sql file in the same directory as that script (though you'll need to start with an empty database for this to work), e.g.

```bash
$ psql --host=localhost --username=uber_db --password uber_db < uber/tests/test_data.sql
```

## What about getting things on a service worker?

For this example we're using systemd. The existing `uber-wrapper.sh` file will be our go-to execution file for all the required system workers. Create the following files.

`sudo vi /etc/systemd/system/uber.service`
```ini
[Unit]
Description=Uber Application
After=network.target postgresql.service redis.service rabbitmq-server.service

[Service]
User=<user>
Group=<group>
WorkingDirectory=/app
EnvironmentFile=/app/.env
ExecStart=/app/uber-wrapper.sh uber
Restart=always

[Install]
WantedBy=multi-user.target
```
`sudo vi /etc/systemd/system/celery-beat.service`
```ini
[Unit]
Description=Celery Beat Service
After=network.target

[Service]
User=<user>
Group=<group>
WorkingDirectory=/app
EnvironmentFile=/app/.env
ExecStart=/app/uber-wrapper.sh celery-beat
Restart=always


[Install]
WantedBy=multi-user.target
```

`sudo vi /etc/systemd/system/celery-worker.service`
```ini
[Unit]
Description=Celery Worker Service
After=network.target

[Service]
User=<user>
Group=<group>
WorkingDirectory=/app
EnvironmentFile=/app/.env
ExecStart=/app/uber-wrapper.sh celery-worker
Restart=always

[Install]
WantedBy=multi-user.target
```

Now that those files are saved, you can enable and start the services.
```bash
$ sudo systemctl enable celery-beat
$ sudo systemctl start celery-beat
$ sudo systemctl enable celery-worker
$ sudo systemctl start celery-worker
$ sudo systemctl enable uber
$ sudo systemctl start uber
```

You can check the statuses using `systemctl status <name>`.

## I want Nginx!

Common gatcha, but make sure apache is disabled on your system.

This simple configuration will forward the traffic to localhost. Be sure you update the proxy pass port to whatever you set in your config **which you will need to specify**, as the default for uber is 80.

```
server {
    listen 80;
    server_name localhost;

    location / {
        proxy_pass http://localhost:6969;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

```