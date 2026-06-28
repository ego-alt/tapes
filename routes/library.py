import json
import logging
import pathlib
import threading
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from models import Episode, Play, PlaybackSession, Playlist, PlaylistTrack, Show, Track, db

library_blueprint = Blueprint("library", __name__)
log = logging.getLogger("tapes.library")


def _write_artist_tags(music_dir, paths, new):
    """Rewrite the ID3 artist tag across many files. Runs off the request thread
    (file I/O only, no DB) so a multi-hundred-track rename doesn't block the HTTP
    response — the DB row is already updated and authoritative."""
    from mutagen.easyid3 import EasyID3
    base = pathlib.Path(music_dir)
    ok = 0
    for rel in paths:
        try:
            audio = EasyID3(str(base / rel))
            audio["artist"] = new
            audio.save()
            ok += 1
        except Exception as e:  # noqa: BLE001 — DB stays the source of truth
            log.warning("artist retag failed for %s: %s", rel, e)
    log.info("artist rename: wrote tag to %d/%d files", ok, len(paths))


def _uid():
    return current_user.id


def _serialize(tracks):
    return [t.to_dict() for t in tracks]


def _tracks_by_ids(ids):
    """Serialize the given track ids, preserving order and dropping any that no
    longer exist. One query — lets the client hydrate a list of ids without us
    shipping the whole catalog."""
    if not ids:
        return []
    by_id = {t.id: t for t in Track.query.filter(Track.id.in_(ids)).all()}
    return _serialize([by_id[i] for i in ids if i in by_id])


def _is_single():
    """The 'single' rule (no album) in one place, so the shelf count and the
    Singles track list can't drift apart."""
    return or_(Track.album.is_(None), Track.album == "")


# ---- shelf ----

@library_blueprint.route("/api/playlists")
@login_required
def playlists():
    uid = _uid()
    singles_q = Track.query.filter(_is_single())
    shelf = [
        {"key": "all", "name": "All Tracks", "kind": "builtin", "count": Track.query.count()},
        {"key": "singles", "name": "Singles", "kind": "builtin", "count": singles_q.count()},
    ]
    album_count = (db.session.query(db.func.count(db.func.distinct(Track.album)))
                   .filter(Track.album.isnot(None), Track.album != "").scalar()) or 0
    artist_count = (db.session.query(db.func.count(db.func.distinct(Track.artist)))
                    .filter(Track.artist.isnot(None), Track.artist != "").scalar()) or 0
    shelf += [
        {"key": "albums", "name": "Albums", "kind": "browse", "count": album_count},
        {"key": "artists", "name": "Artists", "kind": "browse", "count": artist_count},
    ]
    for p in Playlist.query.filter_by(user_id=uid).order_by(Playlist.created_at).all():
        shelf.append({
            "key": str(p.id), "name": p.name, "kind": "user",
            "count": PlaylistTrack.query.filter_by(playlist_id=p.id).count(),
        })
    return jsonify(shelf)


@library_blueprint.route("/api/playlists", methods=["POST"])
@login_required
def create_playlist():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        abort(400, "name required")
    p = Playlist(user_id=_uid(), name=name)
    db.session.add(p)
    db.session.commit()
    return jsonify({"key": str(p.id), "name": p.name, "kind": "user", "count": 0})


@library_blueprint.route("/api/playlists/<int:pid>", methods=["PATCH"])
@login_required
def rename_playlist(pid):
    p = Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    name = (request.json or {}).get("name", "").strip()
    if not name:
        abort(400, "name required")
    p.name = name
    db.session.commit()
    return jsonify({"key": str(p.id), "name": p.name})


@library_blueprint.route("/api/playlists/<int:pid>", methods=["DELETE"])
@login_required
def delete_playlist(pid):
    p = Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    PlaylistTrack.query.filter_by(playlist_id=p.id).delete()
    db.session.delete(p)
    db.session.commit()
    return "", 204


# Sort orders offered for the All Tracks / Singles views. The play-based ones
# are per-user (they read this caller's listening history).
SORTS = {"default", "added", "played", "most"}


def _apply_sort(base, sort, uid):
    if sort == "added":
        # Recently added == recently downloaded (rips get a fresh added_at).
        return base.order_by(Track.added_at.desc(), Track.id.desc()).all()
    if sort == "played":
        last = (db.session.query(Play.track_id, db.func.max(Play.played_at).label("lp"))
                .filter(Play.user_id == uid).group_by(Play.track_id).subquery())
        # SQLite sorts NULLs last on DESC, so never-played tracks fall to the end.
        return (base.outerjoin(last, last.c.track_id == Track.id)
                .order_by(last.c.lp.desc(), Track.title).all())
    if sort == "most":
        cnt = (db.session.query(Play.track_id, db.func.count().label("c"))
               .filter(Play.user_id == uid).group_by(Play.track_id).subquery())
        return (base.outerjoin(cnt, cnt.c.track_id == Track.id)
                .order_by(db.func.coalesce(cnt.c.c, 0).desc(), Track.added_at.desc()).all())
    order = (Track.artist.is_(None), Track.artist, Track.album, Track.track_no, Track.title)
    return base.order_by(*order).all()


@library_blueprint.route("/api/playlists/<key>/tracks")
@login_required
def playlist_tracks(key):
    sort = request.args.get("sort", "default")
    if sort not in SORTS:
        sort = "default"
    if key == "all":
        tracks = _apply_sort(Track.query, sort, _uid())
    elif key == "singles":
        base = Track.query.filter(_is_single())
        tracks = _apply_sort(base, sort, _uid())
    else:
        p = Playlist.query.filter_by(id=int(key), user_id=_uid()).first_or_404()
        rows = (db.session.query(Track).join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .filter(PlaylistTrack.playlist_id == p.id)
                .order_by(PlaylistTrack.position).all())
        tracks = rows
    return jsonify(_serialize(tracks))


@library_blueprint.route("/api/playlists/<int:pid>/tracks", methods=["POST"])
@login_required
def add_to_playlist(pid):
    p = Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    track_id = (request.json or {}).get("track_id")
    if not Track.query.get(track_id):
        abort(404)
    if PlaylistTrack.query.filter_by(playlist_id=p.id, track_id=track_id).first():
        return "", 204  # already present
    nxt = (db.session.query(db.func.max(PlaylistTrack.position))
           .filter_by(playlist_id=p.id).scalar() or 0) + 1
    db.session.add(PlaylistTrack(playlist_id=p.id, track_id=track_id, position=nxt))
    db.session.commit()
    return "", 204


@library_blueprint.route("/api/playlists/<int:pid>/tracks/<int:track_id>", methods=["DELETE"])
@login_required
def remove_from_playlist(pid, track_id):
    Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    PlaylistTrack.query.filter_by(playlist_id=pid, track_id=track_id).delete()
    db.session.commit()
    return "", 204


@library_blueprint.route("/api/playlists/<int:pid>/order", methods=["PUT"])
@login_required
def reorder_playlist(pid):
    Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    ids = (request.json or {}).get("track_ids", [])
    rows = {pt.track_id: pt for pt in PlaylistTrack.query.filter_by(playlist_id=pid).all()}
    for pos, tid in enumerate(ids):
        pt = rows.get(tid)
        if pt:
            pt.position = pos
    db.session.commit()
    return "", 204


# ---- album / artist browsing ----

@library_blueprint.route("/api/albums")
@login_required
def albums():
    rows = (db.session.query(
                Track.album,
                db.func.count(Track.id),
                db.func.count(db.func.distinct(Track.artist)),
                db.func.min(Track.artist),
            )
            .filter(Track.album.isnot(None), Track.album != "")
            .group_by(Track.album).order_by(Track.album).all())
    # One extra query maps each album to a cover-bearing track id (for the thumb).
    covers = dict(
        db.session.query(Track.album, db.func.min(Track.id))
        .filter(Track.has_cover.is_(True), Track.album.isnot(None), Track.album != "")
        .group_by(Track.album).all()
    )
    out = []
    for album, count, n_artists, rep_artist in rows:
        artist = "Various Artists" if n_artists > 1 else (rep_artist or "")
        out.append({
            "name": album, "artist": artist,
            "count": count, "cover_id": covers.get(album),
        })
    return jsonify(out)


@library_blueprint.route("/api/artists")
@login_required
def artists():
    rows = (db.session.query(Track.artist, db.func.count(Track.id))
            .filter(Track.artist.isnot(None), Track.artist != "")
            .group_by(Track.artist).order_by(Track.artist).all())
    return jsonify([{"name": a, "count": c} for a, c in rows])


@library_blueprint.route("/api/artists", methods=["PATCH"])
@login_required
def rename_artist():
    """Rename one artist across the whole library: rewrite every matching track's
    file tag (so a later `scan --full` can't revert it) and DB row. If the new
    name normalizes to an artist that already exists, it merges onto that
    spelling — the manual canonical override for a bad first-seen name."""
    body = request.json or {}
    old = (body.get("old") or "").strip()
    new = (body.get("new") or "").strip()
    if not old or not new:
        abort(400, "old and new required")
    tracks = Track.query.filter(Track.artist == old).all()
    if not tracks:
        abort(404, "unknown artist")

    # Snap onto an existing spelling (excluding the one we're renaming away from).
    from cleaning import reconcile_artist
    from models import distinct_artists
    new = reconcile_artist(new, [a for a in distinct_artists() if a != old])
    if new == old:
        return jsonify({"name": old, "updated": 0})

    paths = [t.file_path for t in tracks]
    for t in tracks:
        t.artist = new
    db.session.commit()
    # Defer the (potentially hundreds of) file-tag writes so the request returns
    # promptly; the rescan reads tags, but the DB is already canonical here.
    threading.Thread(
        target=_write_artist_tags,
        args=(current_app.config["MUSIC_DIR"], paths, new),
        daemon=True,
    ).start()
    return jsonify({"name": new, "updated": len(paths)})


@library_blueprint.route("/api/albums/tracks")
@login_required
def album_tracks():
    album = request.args.get("album", "")
    tracks = (Track.query.filter(Track.album == album)
              .order_by(Track.track_no, Track.title).all())
    return jsonify(_serialize(tracks))


@library_blueprint.route("/api/artists/tracks")
@login_required
def artist_tracks():
    artist = request.args.get("artist", "")
    tracks = (Track.query.filter(Track.artist == artist)
              .order_by(Track.album, Track.track_no, Track.title).all())
    return jsonify(_serialize(tracks))


@library_blueprint.route("/api/tracks/by-ids", methods=["POST"])
@login_required
def tracks_by_ids():
    """Hydrate a list of track ids into full track objects (for playstate/queue
    restore) without fetching the entire library."""
    ids = (request.get_json(silent=True) or {}).get("ids") or []
    return jsonify(_tracks_by_ids([i for i in ids if isinstance(i, int)]))


# ---- per-track edit / delete ----

@library_blueprint.route("/api/tracks/<int:track_id>", methods=["PATCH"])
@login_required
def update_track(track_id):
    """Edit a single track's title/artist/album/track number in both the file tag
    (so a later `scan --full` keeps it) and the DB row. The DB is authoritative if
    the tag write fails. Unlike the global artist rename, this writes exactly what
    the user typed (no canonical-spelling reconcile) — they're in explicit control."""
    t = Track.query.get_or_404(track_id)
    data = request.json or {}

    def _clean(key):
        v = data.get(key)
        return v.strip() if isinstance(v, str) else None

    title = _clean("title")
    if "title" in data and not title:
        abort(400, "title can't be empty")
    artist = _clean("artist") if "artist" in data else None
    album = _clean("album") if "album" in data else None
    track_no = None
    if "track_no" in data:
        raw = data.get("track_no")
        try:
            track_no = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            abort(400, "track number must be a number")

    if title is not None:
        t.title = title
    if "artist" in data:
        t.artist = artist or None
    if "album" in data:
        t.album = album or None
    if "track_no" in data:
        t.track_no = track_no
    db.session.commit()

    # Mirror into the file tag (best-effort; DB stays the source of truth).
    try:
        from mutagen.easyid3 import EasyID3
        audio = EasyID3(str(pathlib.Path(current_app.config["MUSIC_DIR"]) / t.file_path))
        if title is not None:
            audio["title"] = title
        if "artist" in data:
            audio["artist"] = artist or ""
        if "album" in data:
            audio["album"] = album or ""
        if "track_no" in data:
            audio["tracknumber"] = str(track_no) if track_no else ""
        audio.save()
    except Exception as e:  # noqa: BLE001 — DB is authoritative
        log.warning("tag write failed for %s: %s", t.file_path, e)

    return jsonify(t.to_dict())


@library_blueprint.route("/api/tracks/<int:track_id>", methods=["DELETE"])
@login_required
def delete_track(track_id):
    """Remove a track from the library entirely — its file, tape links, and play
    history. (The cover thumbnail is left; it's keyed by file hash and may be
    shared.)"""
    t = Track.query.get_or_404(track_id)
    try:
        (pathlib.Path(current_app.config["MUSIC_DIR"]) / t.file_path).unlink(missing_ok=True)
    except OSError as e:
        log.warning("file delete failed for %s: %s", t.file_path, e)
    PlaylistTrack.query.filter_by(track_id=track_id).delete()
    Play.query.filter_by(track_id=track_id).delete()
    db.session.delete(t)
    db.session.commit()
    return "", 204


# ---- plays / playstate ----

@library_blueprint.route("/api/plays", methods=["POST"])
@login_required
def record_play():
    track_id = (request.json or {}).get("track_id")
    if track_id:
        db.session.add(Play(user_id=_uid(), track_id=track_id))
        db.session.commit()
    return "", 204


def _hydrate_episode_ids(ids):
    """Hydrate episode ids → deck dicts (kind, show title, resume position), in
    order, dropping any that no longer exist. Mirrors _tracks_by_ids for music."""
    if not ids:
        return []
    rows = Episode.query.filter(Episode.id.in_(ids), Episode.user_id == _uid()).all()
    by_id = {e.id: e for e in rows}
    show_titles = dict(db.session.query(Show.id, Show.title)
                       .filter(Show.user_id == _uid()).all())
    out = []
    for i in ids:
        e = by_id.get(i)
        if e:
            out.append({**e.to_dict(), "show": show_titles.get(e.show_id, "")})
    return out


@library_blueprint.route("/api/playstate", methods=["GET", "PUT"])
@login_required
def playstate():
    if request.method == "GET":
        # The most-recently-updated context is what the deck last held → restore it.
        s = (PlaybackSession.query.filter_by(user_id=_uid())
             .order_by(PlaybackSession.updated_at.desc()).first())
        if not s:
            return jsonify({"queue": [], "index": 0, "position": 0})
        ids = json.loads(s.queue_json or "[]")
        if s.context == "podcast":
            queue = _hydrate_episode_ids(ids)
            # Resume point is the current episode's own saved position.
            cur = queue[s.cursor] if 0 <= s.cursor < len(queue) else None
            position = cur["position"] if cur else 0
        else:
            queue = _tracks_by_ids(ids)
            position = s.position_s or 0
        return jsonify({"queue": queue, "index": s.cursor or 0, "position": position})

    data = request.json or {}
    context = "podcast" if data.get("context") == "podcast" else "music"
    s = db.session.get(PlaybackSession, (_uid(), context))
    if not s:
        s = PlaybackSession(user_id=_uid(), context=context)
        db.session.add(s)
    s.queue_json = json.dumps(data.get("queue", []))
    s.cursor = data.get("index", 0)
    s.position_s = data.get("position", 0)  # music playhead; podcast resume lives on Episode
    # Explicit microsecond stamp: SQLite's func.now() is second-resolution, so two
    # context saves in the same second would tie and the "last active" pick on GET
    # would be undefined.
    s.updated_at = datetime.now()
    db.session.commit()
    return "", 204
