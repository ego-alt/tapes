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
    artist = db.Column(db.String, index=True)
    album = db.Column(db.String, index=True)
    # Original source (e.g. the YouTube URL the track was ripped from); NULL for
    # files added outside the ripper. Indexed for the re-rip exact-match dedup.
    source_url = db.Column(db.String, index=True)
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

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist or "",
            "album": self.album or "",
            "duration": self.duration_s or 0,
            "has_cover": bool(self.has_cover),
            "source_url": self.source_url or "",
        }


def distinct_artists():
    """Distinct non-empty artist spellings, earliest-seen first — the candidate
    list for canonical-artist snapping (see cleaning.reconcile_artist). Ordering
    by first appearance makes first-seen the canonical spelling."""
    rows = (db.session.query(Track.artist, func.min(Track.id).label("seen"))
            .filter(Track.artist.isnot(None), Track.artist != "")
            .group_by(Track.artist).order_by("seen").all())
    return [r[0] for r in rows]


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


class Play(db.Model):
    __tablename__ = "plays"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"), nullable=False)
    played_at = db.Column(db.DateTime, server_default=func.now(), index=True)


class PlaybackSession(db.Model):
    """The deck's 'now playing' snapshot, one row per (user, context). Keying by
    context — 'music' | 'podcast' — keeps the two from clobbering each other; the
    most-recently-updated row is the one to restore on reload (no separate pointer).

    queue_json holds ids (track ids for music, episode ids for podcast); the items
    are hydrated on read. position_s is the music playhead — podcast resume is read
    from Episode.position_s (the per-item source of truth), not duplicated here."""
    __tablename__ = "playback_sessions"

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), primary_key=True)
    context = db.Column(db.String, primary_key=True)  # music | podcast
    queue_json = db.Column(db.Text)
    cursor = db.Column(db.Integer, default=0)
    position_s = db.Column(db.Float, default=0)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())


class Show(db.Model):
    """A podcast subscription — an RSS feed or a YouTube channel/playlist. Per-user
    (mirrors Playlist), so each household member curates their own shows."""
    __tablename__ = "shows"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String, nullable=False)
    source_type = db.Column(db.String, nullable=False)  # rss | youtube
    source_url = db.Column(db.String, nullable=False)  # feed/channel/playlist URL ("" = manual)
    # Linked YouTube channel: when set, future single videos from this channel
    # auto-file into this show instead of landing in Loose episodes.
    channel_id = db.Column(db.String, index=True)
    description = db.Column(db.Text)
    has_image = db.Column(db.Boolean, default=False)     # cover cached at shows/<id>.jpg
    created_at = db.Column(db.DateTime, server_default=func.now())
    last_refreshed_at = db.Column(db.DateTime)


class Episode(db.Model):
    """One podcast episode. Catalogued from the feed as metadata first (status
    'new'); the audio is fetched on demand the first time it's played
    (download-on-play). Per-user, so resume position / played live right here."""
    __tablename__ = "episodes"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    # Null = a "loose" episode (a one-off video, not part of a subscribed show).
    show_id = db.Column(db.Integer, db.ForeignKey("shows.id"), nullable=True, index=True)
    # Stable per-show key for refresh dedup: RSS guid, or the YouTube video id.
    guid = db.Column(db.String, index=True)
    title = db.Column(db.String, nullable=False)
    # Enclosure URL (rss) or watch URL (youtube) — what we download from.
    source_url = db.Column(db.String, nullable=False)
    source_type = db.Column(db.String, nullable=False)  # rss | youtube
    # YouTube channel of this video, captured at add time so a loose episode can be
    # assigned to a show and that channel linked for future auto-routing.
    channel_id = db.Column(db.String)
    # Relative to MUSIC_DIR (under the reserved _podcasts/ subdir); null until fetched.
    file_path = db.Column(db.String)
    status = db.Column(db.String, nullable=False, default="new")  # new|downloading|ready|error
    duration_s = db.Column(db.Float)
    description = db.Column(db.Text)
    published_at = db.Column(db.DateTime, index=True)
    added_at = db.Column(db.DateTime, server_default=func.now())
    # Per-user playback state (episodes are already per-user — no separate table).
    position_s = db.Column(db.Float, default=0)
    played = db.Column(db.Boolean, default=False, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "kind": "episode",
            "show_id": self.show_id,
            "title": self.title,
            "status": self.status,
            "duration": self.duration_s or 0,
            "position": self.position_s or 0,
            "played": bool(self.played),
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "source_url": self.source_url or "",
            "has_cover": True,  # cover endpoint falls back to the show image
        }


class DownloadJob(db.Model):
    __tablename__ = "download_jobs"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    url = db.Column(db.String, nullable=False)
    status = db.Column(db.String, nullable=False, default="queued")  # queued|running|done|error
    progress = db.Column(db.Float, default=0)
    message = db.Column(db.String)
    kind = db.Column(db.String, nullable=False, default="music")  # music | podcast
    track_id = db.Column(db.Integer, db.ForeignKey("tracks.id"))
    playlist_id = db.Column(db.Integer, db.ForeignKey("playlists.id"), nullable=True)
    episode_id = db.Column(db.Integer, db.ForeignKey("episodes.id"), nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now(), index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "status": self.status,
            "progress": round(self.progress or 0, 1),
            "message": self.message or "",
            "kind": self.kind,
            "track_id": self.track_id,
            "playlist_id": self.playlist_id,
            "episode_id": self.episode_id,
        }
