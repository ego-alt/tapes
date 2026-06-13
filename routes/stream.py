import pathlib
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, send_file
from flask_login import login_required

from models import Track

stream_blueprint = Blueprint("stream", __name__)


@stream_blueprint.route("/stream/<int:track_id>")
@login_required
def stream(track_id):
    track = Track.query.get_or_404(track_id)
    path = pathlib.Path(current_app.config["MUSIC_DIR"]) / track.file_path
    if not path.exists():
        abort(404)

    if current_app.config.get("USE_X_ACCEL"):
        # Hand the byte transfer to nginx (Stage 2). The /_audio/ location is an
        # internal alias onto MUSIC_DIR; quote the relpath for spaces/unicode.
        resp = Response()
        resp.headers["X-Accel-Redirect"] = "/_audio/" + quote(track.file_path)
        resp.headers["Content-Type"] = "audio/mpeg"
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    # Standalone (Stage 1): Flask serves the bytes with range/seek support.
    return send_file(path, conditional=True, mimetype="audio/mpeg")


@stream_blueprint.route("/cover/<int:track_id>")
@login_required
def cover(track_id):
    track = Track.query.get_or_404(track_id)
    if track.has_cover and track.file_hash:
        p = pathlib.Path(current_app.config["COVER_DIR"]) / f"{track.file_hash}.jpg"
        if p.exists():
            return send_file(p, mimetype="image/jpeg")
    abort(404)
