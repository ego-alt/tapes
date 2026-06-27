import pathlib

from flask import Blueprint, abort, current_app
from flask_login import login_required

from models import Track

from .serving import accel_audio, cached_jpeg

stream_blueprint = Blueprint("stream", __name__)


@stream_blueprint.route("/stream/<int:track_id>")
@login_required
def stream(track_id):
    track = Track.query.get_or_404(track_id)
    path = pathlib.Path(current_app.config["MUSIC_DIR"]) / track.file_path
    if not path.exists():
        abort(404)
    return accel_audio(track.file_path, "audio/mpeg")


@stream_blueprint.route("/cover/<int:track_id>")
@login_required
def cover(track_id):
    track = Track.query.get_or_404(track_id)
    if track.has_cover and track.file_hash:
        p = pathlib.Path(current_app.config["COVER_DIR"]) / f"{track.file_hash}.jpg"
        if p.exists():
            return cached_jpeg(p)
    abort(404)
