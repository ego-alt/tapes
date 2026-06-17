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
        resp = Response()
        resp.headers["X-Accel-Redirect"] = "/_audio/" + quote(track.file_path)
        resp.headers["Content-Type"] = "audio/mpeg"
        resp.headers["Accept-Ranges"] = "bytes"
        return resp

    return send_file(path, conditional=True, mimetype="audio/mpeg")


@stream_blueprint.route("/cover/<int:track_id>")
@login_required
def cover(track_id):
    track = Track.query.get_or_404(track_id)
    if track.has_cover and track.file_hash:
        p = pathlib.Path(current_app.config["COVER_DIR"]) / f"{track.file_hash}.jpg"
        if p.exists():
            resp = send_file(p, mimetype="image/jpeg")
            # Thumbnails are stable per file; cache for a week. The ETag send_file
            # sets still lets the browser revalidate cheaply if it does change.
            resp.headers["Cache-Control"] = "public, max-age=604800"
            return resp
    abort(404)
