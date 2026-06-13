from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()


class User(UserMixin, db.Model):
    """Shadow user. password_hash is NULL in proxy mode (dashboard owns auth);
    in standalone dev a single local user is auto-attached (see proxy_auth)."""

    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String)
    created_at = db.Column(db.DateTime, server_default=func.now())


class Track(db.Model):
    """Flat, denormalized catalog. Album/artist are plain strings and nullable —
    a YouTube single needs neither."""

    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    # Path RELATIVE to MUSIC_DIR — this is also the X-Accel-Redirect suffix.
    file_path = db.Column(db.String, unique=True, nullable=False)
    file_hash = db.Column(db.String, index=True)
    title = db.Column(db.String, nullable=False)
    artist = db.Column(db.String)
    album = db.Column(db.String)
    track_no = db.Column(db.Integer)
    duration_s = db.Column(db.Float)
    bitrate = db.Column(db.Integer)
    size_bytes = db.Column(db.Integer)
    has_cover = db.Column(db.Boolean, default=False)
    mtime = db.Column(db.Float)
    added_at = db.Column(db.DateTime, server_default=func.now())

    def to_dict(self, fav=False):
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist or "",
            "album": self.album or "",
            "duration": self.duration_s or 0,
            "has_cover": bool(self.has_cover),
            "fav": fav,
        }


# ---- Stage 3: per-user organization (catalog stays shared) ----

class Playlist(db.Model):
    __tablename__ = "playlists"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    name = db.Column(db.String, nullable=False)
    created_at = db.Column(db.DateTime, server_default=func.now())


class PlaylistTrack(db.Model):
    __tablename__ = "playlist_tracks"

    id = db.Column(db.Integer, primary_key=True)
    playlist_id = db.Column(db.Integer, db.ForeignKey("playlists.id"), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    position = db.Column(db.Integer, nullable=False, default=0)


class Favorite(db.Model):
    __tablename__ = "favorites"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), primary_key=True)
    created_at = db.Column(db.DateTime, server_default=func.now())


class Play(db.Model):
    __tablename__ = "plays"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    played_at = db.Column(db.DateTime, server_default=func.now(), index=True)


class PlayState(db.Model):
    """One row per user: the persisted queue + position, so playback follows
    you across devices."""

    __tablename__ = "playstate"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    queue_json = db.Column(db.Text)        # JSON list of track ids
    index = db.Column(db.Integer, default=0)
    position_s = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())


# ---- Stage 4: downloader ----

class DownloadJob(db.Model):
    __tablename__ = "download_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    url = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default="queued")  # queued|running|done|error
    progress = db.Column(db.Float, default=0)
    message = db.Column(db.String)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    created_at = db.Column(db.DateTime, server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status,
            "progress": round(self.progress or 0, 1),
            "message": self.message or "",
            "track_id": self.track_id,
        }
