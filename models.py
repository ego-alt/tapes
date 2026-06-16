from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.sql import func

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, unique=True, nullable=False)
    password_hash = db.Column(db.String)
    created_at = db.Column(db.DateTime, server_default=func.now())


class Track(db.Model):
    __tablename__ = "tracks"

    id = db.Column(db.Integer, primary_key=True)
    # Relative to MUSIC_DIR — also used as the X-Accel-Redirect suffix.
    file_path = db.Column(db.String, unique=True, nullable=False)
    file_hash = db.Column(db.String, index=True)
    title = db.Column(db.String, nullable=False)
    artist = db.Column(db.String)
    album = db.Column(db.String)
    # Original source (e.g. the YouTube URL the track was ripped from); NULL for
    # files added outside the ripper.
    source_url = db.Column(db.String)
    # Set when the automatic LLM cleanup didn't run on rip (no key / API failure),
    # so `retag --llm --pending` can sweep up all the misses later.
    needs_llm = db.Column(db.Boolean, default=False)
    # Chromaprint acoustic fingerprint (raw sub-fingerprints) for local content
    # dedup — same recording from any URL. NULL until fingerprinted.
    fingerprint = db.Column(db.Text)
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
            "source_url": self.source_url or "",
            "fav": fav,
        }


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
    __tablename__ = "playstate"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    queue_json = db.Column(db.Text)
    index = db.Column(db.Integer, default=0)
    position_s = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())


class DownloadJob(db.Model):
    __tablename__ = "download_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    url = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default="queued")  # queued|running|done|error
    progress = db.Column(db.Float, default=0)
    message = db.Column(db.String)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    playlist_id = db.Column(db.Integer, db.ForeignKey("playlists.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status,
            "progress": round(self.progress or 0, 1),
            "message": self.message or "",
            "track_id": self.track_id,
            "playlist_id": self.playlist_id,
        }
