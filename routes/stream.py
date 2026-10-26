import pathlib
from io import BytesIO

from flask import Blueprint, abort, current_app, request
from flask_login import login_required
from PIL import Image

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



# The lock screen shows the deck's cassette with the song on its label. The
# page draws it (the same SVG and label as on screen) and stores it here once
# per label, so the lock screen and the car get a plain image URL.
CASSETTE_SIZE = 512


def _cassette_path(track_id: int, key: str) -> pathlib.Path:
    if not key.isalnum() or len(key) > 40:
        abort(400, "Bad cassette key.")
    return pathlib.Path(current_app.config["COVER_DIR"]) / "cassettes" / f"{track_id}-{key}.jpg"


@stream_blueprint.route("/cassette/<int:track_id>/<key>")
@login_required
def cassette(track_id, key):
    path = _cassette_path(track_id, key)
    if not path.exists():
        abort(404)
    return cached_jpeg(path)


@stream_blueprint.route("/cassette/<int:track_id>/<key>", methods=["PUT"])
@login_required
def save_cassette(track_id, key):
    """Keep the page's drawing of the cassette, re-encoded as a square JPEG
    (anything that isn't an image is refused)."""
    Track.query.get_or_404(track_id)
    path = _cassette_path(track_id, key)
    try:
        img = Image.open(BytesIO(request.get_data(cache=False)[: 4 * 1024 * 1024]))
        img = img.convert("RGB").resize((CASSETTE_SIZE, CASSETTE_SIZE))
    except (OSError, ValueError):
        abort(400, "That isn't an image.")
    path.parent.mkdir(parents=True, exist_ok=True)
    for old in path.parent.glob(f"{track_id}-*.jpg"):   # an old label for this song
        old.unlink(missing_ok=True)
    tmp = path.with_suffix(".tmp")
    img.save(tmp, "JPEG", quality=88)
    tmp.replace(path)
    return "", 204
