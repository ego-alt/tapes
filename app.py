import gzip
import os
import pathlib
import secrets

from flask import Flask, jsonify, request
from flask_login import LoginManager
from flask_migrate import Migrate
from sqlalchemy import event
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from downloader import start_worker
from models import User, db
from proxy_auth import load_user_for_request
from routes import (
    auth_blueprint,
    downloads_blueprint,
    index_blueprint,
    library_blueprint,
    podcasts_blueprint,
    pwa_blueprint,
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
    # Podcast episodes live in a reserved subdir INSIDE MUSIC_DIR so the existing
    # nginx /_audio/ X-Accel alias serves them too; scan_library skips this dir.
    app.config["PODCAST_REL"] = "_podcasts"
    app.config["PODCAST_DIR"] = os.environ.get("PODCAST_DIR") or str(
        pathlib.Path(music_dir) / "_podcasts")

    app.config["USE_X_ACCEL"] = os.environ.get("USE_X_ACCEL", "").lower() in ("1", "true", "yes")
    # LLM tag correction on rip (needs ANTHROPIC_API_KEY; falls back to deterministic without it).
    app.config["LLM_CLEANING"] = os.environ.get("LLM_CLEANING", "1").lower() in ("1", "true", "yes")
    # Fetch real cover art from MusicBrainz on rip (replaces the yt-dlp video thumbnail).
    app.config["ART_LOOKUP"] = os.environ.get("ART_LOOKUP", "1").lower() in ("1", "true", "yes")
    # Acoustic-fingerprint dedup on rip (needs the fpcalc binary).
    app.config["FINGERPRINT_DEDUP"] = os.environ.get("FINGERPRINT_DEDUP", "1").lower() in ("1", "true", "yes")
    app.config["AUTH_PROXY_HEADER"] = os.environ.get("AUTH_PROXY_HEADER") or None
    app.config["LOCAL_USER"] = os.environ.get("MUSIC_LOCAL_USER", "local")
    # Usernames allowed to delete songs from the shared library or rename an
    # artist everywhere. Unset = everyone (a single-user install).
    _admins = {u.strip() for u in os.environ.get("TAPES_ADMINS", "").split(",") if u.strip()}
    app.config["ADMIN_USERS"] = _admins or None

    _root = os.environ.get("APPLICATION_ROOT", "").strip()
    app.config["APPLICATION_ROOT"] = _root if _root else "/"

    if config:
        app.config.update(config)

    pathlib.Path(app.config["COVER_DIR"]).mkdir(parents=True, exist_ok=True)
    pathlib.Path(app.config["PODCAST_DIR"]).mkdir(parents=True, exist_ok=True)

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
    app.register_blueprint(podcasts_blueprint)
    app.register_blueprint(pwa_blueprint)

    @app.errorhandler(HTTPException)
    def _json_errors(e):
        # The page reads errors as JSON and shows the message; keep Flask's HTML
        # error page only for plain browser navigation.
        if request.path.startswith("/api/") or request.accept_mimetypes.best == "application/json":
            return jsonify({"error": e.description}), e.code
        return e

    @app.get("/healthz")
    def healthz():
        return "", 200

    @app.after_request
    def _gzip(resp):
        # Compress JSON/text payloads (e.g. the All Tracks list) when the client
        # accepts it. Skips streamed responses (SSE) and the X-Accel audio path.
        if resp.direct_passthrough or resp.status_code != 200:
            return resp
        ctype = resp.content_type or ""
        if "event-stream" in ctype or not (
            "application/json" in ctype or ctype.startswith("text/") or "javascript" in ctype
        ):
            return resp
        if "gzip" not in request.headers.get("Accept-Encoding", ""):
            return resp
        data = resp.get_data()
        if len(data) < 1024:
            return resp
        resp.set_data(gzip.compress(data, 6))
        resp.headers["Content-Encoding"] = "gzip"
        resp.headers["Vary"] = "Accept-Encoding"
        return resp

    with app.app_context():
        # SQLite tuning: WAL lets the rip worker / SSE poller write while readers
        # browse — the default rollback journal serializes them ("database is
        # locked"). synchronous=NORMAL is safe under WAL; busy_timeout retries.
        @event.listens_for(db.engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.close()

    # The schema lives in migrations/ and is applied by `flask db upgrade`
    # (gunicorn runs it before starting workers; see gunicorn.conf.py).
    Migrate(app, db, render_as_batch=True)

    register_cli(app)

    # The rip worker starts with the first request, so CLI commands
    # (db upgrade, scan, purge-trash) never pick up queued rips.
    @app.before_request
    def _start_worker():
        start_worker(app)

    return app


if __name__ == "__main__":
    from flask_migrate import upgrade

    dev = create_app()
    with dev.app_context():
        upgrade()
    dev.run(debug=True, host="0.0.0.0", port=5003)
