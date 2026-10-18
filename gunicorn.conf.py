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
    back). Jobs a restart cut off go back in the queue here too, once, before
    any worker can be running one. The rip worker itself isn't started by
    this: it starts with a worker's first request.
    """
    import os

    from flask_migrate import upgrade

    from app import create_app
    from downloader import recover_interrupted_jobs

    app = create_app()
    with app.app_context():
        upgrade()
        recover_interrupted_jobs()
    os.environ["TAPES_JOBS_RECOVERED"] = "1"   # workers inherit it and skip their own recovery
