"""The library trash: deleting a song moves its file to MUSIC_DIR/.trash/ and
stamps the row, so the delete can be undone (restore). After TRASH_DAYS the
file, the row, its tape links and its play history are removed for good."""
import pathlib
import shutil
from datetime import datetime, timedelta

from models import Play, PlaylistTrack, Track, db

TRASH_DIRNAME = ".trash"
TRASH_DAYS = 30


def _trash_path(app, track) -> pathlib.Path:
    return pathlib.Path(app.config["MUSIC_DIR"]) / TRASH_DIRNAME / f"{track.id}{pathlib.Path(track.file_path).suffix}"


def trash_track(app, track):
    src = pathlib.Path(app.config["MUSIC_DIR"]) / track.file_path
    dst = _trash_path(app, track)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.exists():
        shutil.move(str(src), str(dst))
    track.deleted_at = datetime.now()
    db.session.commit()


def get_trashed(track_id):
    return (Track.query.execution_options(include_deleted=True)
            .filter(Track.id == track_id, Track.deleted_at.isnot(None)).first())


def restore_track(app, track):
    src = _trash_path(app, track)
    dst = pathlib.Path(app.config["MUSIC_DIR"]) / track.file_path
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    track.deleted_at = None
    db.session.commit()


def purge_trash(app, days=TRASH_DAYS) -> int:
    """Permanently remove tracks trashed more than `days` ago. Returns the count."""
    cutoff = datetime.now() - timedelta(days=days)
    old = (Track.query.execution_options(include_deleted=True)
           .filter(Track.deleted_at.isnot(None), Track.deleted_at < cutoff).all())
    for t in old:
        _trash_path(app, t).unlink(missing_ok=True)
        PlaylistTrack.query.filter_by(track_id=t.id).delete()
        Play.query.filter_by(track_id=t.id).delete()
        db.session.delete(t)
    db.session.commit()
    return len(old)
