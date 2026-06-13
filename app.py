import os
import pathlib
import secrets

from flask import Flask
from flask_login import LoginManager
from werkzeug.middleware.proxy_fix import ProxyFix

from downloader import start_worker
from models import User, db
from proxy_auth import load_user_for_request
from routes import (
    auth_blueprint,
    downloads_blueprint,
    index_blueprint,
    library_blueprint,
    stream_blueprint,
)
from scan import register_cli


def create_app(config=None):
    app = Flask(__name__)
    app.url_map.strict_slashes = False

    instance = pathlib.Path(app.instance_path)
    instance.mkdir(parents=True, exist_ok=True)

    db_path = instance / "music.db"
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY") or secrets.token_hex(32)

    music_dir = os.environ.get("MUSIC_DIR") or str(pathlib.Path(app.root_path) / "music")
    app.config["MUSIC_DIR"] = music_dir
    app.config["COVER_DIR"] = str(instance / "covers")

    app.config["USE_X_ACCEL"] = os.environ.get("USE_X_ACCEL", "").lower() in ("1", "true", "yes")
    app.config["AUTH_PROXY_HEADER"] = os.environ.get("AUTH_PROXY_HEADER") or None
    app.config["LOCAL_USER"] = os.environ.get("MUSIC_LOCAL_USER", "local")

    _root = os.environ.get("APPLICATION_ROOT", "").strip()
    app.config["APPLICATION_ROOT"] = _root if _root else "/"

    if config:
        app.config.update(config)

    pathlib.Path(app.config["COVER_DIR"]).mkdir(parents=True, exist_ok=True)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1, x_prefix=1)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @login_manager.request_loader
    def load_request_user(_request):
        return load_user_for_request()

    app.register_blueprint(auth_blueprint)
    app.register_blueprint(index_blueprint)
    app.register_blueprint(stream_blueprint)
    app.register_blueprint(library_blueprint)
    app.register_blueprint(downloads_blueprint)

    @app.get("/healthz")
    def healthz():
        return "", 200

    with app.app_context():
        db.create_all()

    register_cli(app)
    start_worker(app)
    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5003)
