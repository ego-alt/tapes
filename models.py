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
    """Stage 1 schema: a flat, denormalized catalog. Album/artist are plain
    strings and nullable — a YouTube single needs neither. Normalize into
    artists/albums + playlists in Stage 3."""

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

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist or "",
            "album": self.album or "",
            "duration": self.duration_s or 0,
            "has_cover": bool(self.has_cover),
        }
