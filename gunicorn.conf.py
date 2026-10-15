bind = "0.0.0.0:5003"
worker_class = "gthread"
workers = 2
threads = 4
timeout = 120
keepalive = 2
accesslog = "-"
errorlog = "-"
loglevel = "info"
proc_name = "music"


def on_starting(server):
    """Bring the database schema up to date once, before any worker starts.

    A failed migration raises here and gunicorn exits, so the container never
    reports healthy on a half-upgraded schema (the deploy script then rolls
    back). The rip worker isn't started by this: it starts with a worker's
    first request.
    """
    from flask_migrate import upgrade

    from app import create_app

    app = create_app()
    with app.app_context():
        upgrade()
