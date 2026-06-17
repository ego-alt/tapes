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
    # LLM tag correction on rip (needs ANTHROPIC_API_KEY; falls back to deterministic without it).
    app.config["LLM_CLEANING"] = os.environ.get("LLM_CLEANING", "1").lower() in ("1", "true", "yes")
    # Fetch real cover art from MusicBrainz on rip (replaces the yt-dlp video thumbnail).
    app.config["ART_LOOKUP"] = os.environ.get("ART_LOOKUP", "1").lower() in ("1", "true", "yes")
    # Acoustic-fingerprint dedup on rip (needs the fpcalc binary).
    app.config["FINGERPRINT_DEDUP"] = os.environ.get("FINGERPRINT_DEDUP", "1").lower() in ("1", "true", "yes")
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
        # Lightweight column adds for existing DBs (SQLite ignores IF NOT EXISTS
        # for columns, so each is best-effort and rolls back if already present).
        for stmt in (
            "ALTER TABLE download_jobs ADD COLUMN playlist_id INTEGER REFERENCES playlists(id)",
            "ALTER TABLE tracks ADD COLUMN source_url VARCHAR",
            "ALTER TABLE tracks ADD COLUMN needs_llm BOOLEAN DEFAULT 0",
            "ALTER TABLE tracks ADD COLUMN fingerprint TEXT",
            # Indexes for shelf grouping (artist/album) and the re-rip dedup
            # lookup — create_all() won't add these to a pre-existing table.
            "CREATE INDEX IF NOT EXISTS ix_tracks_artist ON tracks (artist)",
            "CREATE INDEX IF NOT EXISTS ix_tracks_album ON tracks (album)",
            "CREATE INDEX IF NOT EXISTS ix_tracks_source_url ON tracks (source_url)",
        ):
            try:
                db.session.execute(db.text(stmt))
                db.session.commit()
            except Exception:
                db.session.rollback()

    register_cli(app)
    start_worker(app)
    return app


if __name__ == "__main__":
    create_app().run(debug=True, host="0.0.0.0", port=5003)
