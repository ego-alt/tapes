import json
import logging
import pathlib
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from models import Episode, Play, PlaybackSession, Playlist, PlaylistTrack, Show, Track, db

library_blueprint = Blueprint("library", __name__)
log = logging.getLogger("tapes.library")


def _uid():
    return current_user.id


def _require_admin(message):
    """Library-wide destructive actions are limited to TAPES_ADMINS when set."""
    admins = current_app.config.get("ADMIN_USERS")
    if admins and current_user.username not in admins:
        abort(403, message)


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
    """The 'single' rule in one place, so the shelf count and the Singles list
    can't drift apart: no album, but a known artist. Songs with neither are
    'Needs tidying', not singles."""
    return db.and_(or_(Track.album.is_(None), Track.album == ""),
                   Track.artist.isnot(None), Track.artist != "")


def _needs_tidying():
    return or_(Track.artist.is_(None), Track.artist == "",
               Track.has_cover.isnot(True), Track.needs_llm.is_(True))


def _issues(t):
    out = []
    if not t.artist:
        out.append("no artist")
    if not t.has_cover:
        out.append("no cover")
    if t.needs_llm:
        out.append("AI pass missed")
    return out


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
    tidy_count = Track.query.filter(_needs_tidying()).count()
    if tidy_count:
        shelf.append({"key": "tidy", "name": "Needs tidying", "kind": "builtin", "count": tidy_count})
    for p in Playlist.query.filter_by(user_id=uid).order_by(Playlist.created_at).all():
        shelf.append({
            "key": str(p.id), "name": p.name, "kind": "user",
            # Joined to Track so songs in the trash don't count.
            "count": (db.session.query(PlaylistTrack).join(Track, Track.id == PlaylistTrack.track_id)
                      .filter(PlaylistTrack.playlist_id == p.id).count()),
        })
    return jsonify(shelf)


@library_blueprint.route("/api/playlists", methods=["POST"])
@login_required
def create_playlist():
    name = (request.json or {}).get("name", "").strip()
    if not name:
        abort(400, "Give the tape a name.")
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
        abort(400, "Give the tape a name.")
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


def _take(query, limit):
    return query.limit(limit).all() if limit else query.all()


def _apply_sort(base, sort, uid, limit=None):
    if sort == "added":
        # Recently added == recently downloaded (rips get a fresh added_at).
        return _take(base.order_by(Track.added_at.desc(), Track.id.desc()), limit)
    if sort == "played":
        last = (db.session.query(Play.track_id, db.func.max(Play.played_at).label("lp"))
                .filter(Play.user_id == uid).group_by(Play.track_id).subquery())
        # SQLite sorts NULLs last on DESC, so never-played tracks fall to the end.
        return _take(base.outerjoin(last, last.c.track_id == Track.id)
                     .order_by(last.c.lp.desc(), Track.title), limit)
    if sort == "most":
        cnt = (db.session.query(Play.track_id, db.func.count().label("c"))
               .filter(Play.user_id == uid).group_by(Play.track_id).subquery())
        return _take(base.outerjoin(cnt, cnt.c.track_id == Track.id)
                     .order_by(db.func.coalesce(cnt.c.c, 0).desc(), Track.added_at.desc()), limit)
    order = (Track.artist.is_(None), Track.artist, Track.album, Track.track_no, Track.title)
    return _take(base.order_by(*order), limit)


@library_blueprint.route("/api/playlists/<key>/tracks")
@login_required
def playlist_tracks(key):
    sort = request.args.get("sort", "default")
    if sort not in SORTS:
        sort = "default"
    # Optional cap for programmatic clients (the MCP server); the deck loads all.
    limit = request.args.get("limit", type=int)
    limit = max(limit, 1) if limit else None
    if key == "all":
        tracks = _apply_sort(Track.query, sort, _uid(), limit)
    elif key == "singles":
        base = Track.query.filter(_is_single())
        tracks = _apply_sort(base, sort, _uid(), limit)
    elif key == "tidy":
        tracks = _apply_sort(Track.query.filter(_needs_tidying()), sort, _uid(), limit)
        return jsonify([{**t.to_dict(), "issues": _issues(t)} for t in tracks])
    else:
        p = Playlist.query.filter_by(id=int(key), user_id=_uid()).first_or_404()
        rows = (db.session.query(Track).join(PlaylistTrack, PlaylistTrack.track_id == Track.id)
                .filter(PlaylistTrack.playlist_id == p.id)
                .order_by(PlaylistTrack.position))
        tracks = _take(rows, limit)
    return jsonify(_serialize(tracks))


@library_blueprint.route("/api/playlists/<int:pid>/tracks", methods=["POST"])
@login_required
def add_to_playlist(pid):
    p = Playlist.query.filter_by(id=pid, user_id=_uid()).first_or_404()
    track_id = (request.json or {}).get("track_id")
    if not Track.query.get(track_id):
        abort(404, "That song isn't in the library any more.")
    if PlaylistTrack.query.filter_by(playlist_id=p.id, track_id=track_id).first():
        return jsonify({"added": False, "tape": p.name})   # already on it
    nxt = (db.session.query(db.func.max(PlaylistTrack.position))
           .filter_by(playlist_id=p.id).scalar() or 0) + 1
    db.session.add(PlaylistTrack(playlist_id=p.id, track_id=track_id, position=nxt))
    db.session.commit()
    return jsonify({"added": True, "tape": p.name})


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


def _resolve_artist_name(old, new):
    """The name a rename will actually use: snapped onto an existing spelling it
    normalizes to (the canonical-override behaviour), excluding the old name."""
    from cleaning import reconcile_artist
    from models import distinct_artists
    return reconcile_artist(new, [a for a in distinct_artists() if a != old])


def _set_artist(tracks, name):
    """Set the artist in the DB and the files. Returns how many tag writes failed
    (the DB is authoritative either way)."""
    from mutagen.easyid3 import EasyID3
    base = pathlib.Path(current_app.config["MUSIC_DIR"])
    failures = 0
    for t in tracks:
        t.artist = name
        try:
            audio = EasyID3(str(base / t.file_path))
            audio["artist"] = name
            audio.save()
        except Exception as e:  # noqa: BLE001 — DB stays the source of truth
            failures += 1
            log.warning("artist tag write failed for %s: %s", t.file_path, e)
    db.session.commit()
    return failures


@library_blueprint.route("/api/artists/rename-preview")
@login_required
def rename_artist_preview():
    """What a rename would do, so the page can ask before merging two artists."""
    old = (request.args.get("old") or "").strip()
    new = (request.args.get("new") or "").strip()
    if not old or not new:
        abort(400, "Type the artist's new name.")
    name = _resolve_artist_name(old, new)
    return jsonify({
        "name": name,
        "tracks": Track.query.filter(Track.artist == old).count(),
        "merges_into": Track.query.filter(Track.artist == name).count() if name != old else 0,
    })


@library_blueprint.route("/api/artists", methods=["PATCH"])
@login_required
def rename_artist():
    """Rename one artist across the whole library, in both the DB and the file
    tags. If the new name normalizes to an artist that already exists, the tracks
    merge onto that spelling. Returns the moved track ids so it can be undone."""
    _require_admin("Only an admin can rename an artist across the library.")
    body = request.json or {}
    old = (body.get("old") or "").strip()
    new = (body.get("new") or "").strip()
    if not old or not new:
        abort(400, "Type the artist's new name.")
    tracks = Track.query.filter(Track.artist == old).all()
    if not tracks:
        abort(404, "That artist isn't in the library any more.")
    new = _resolve_artist_name(old, new)
    if new == old:
        return jsonify({"name": old, "updated": 0, "track_ids": [], "tag_failures": 0})
    failures = _set_artist(tracks, new)
    return jsonify({"name": new, "updated": len(tracks),
                    "track_ids": [t.id for t in tracks], "tag_failures": failures})


@library_blueprint.route("/api/tracks/artist", methods=["PATCH"])
@login_required
def set_tracks_artist():
    """Set the artist on exactly these tracks (used to undo a rename/merge)."""
    _require_admin("Only an admin can rename an artist across the library.")
    body = request.json or {}
    ids = [i for i in body.get("track_ids", []) if isinstance(i, int)]
    name = (body.get("artist") or "").strip()
    if not ids or not name:
        abort(400, "Nothing to change.")
    tracks = Track.query.filter(Track.id.in_(ids)).all()
    failures = _set_artist(tracks, name)
    return jsonify({"updated": len(tracks), "tag_failures": failures})


@library_blueprint.route("/api/albums", methods=["PATCH"])
@login_required
def edit_album_route():
    """Rename an album and/or set one artist on all its songs (DB + file tags)."""
    _require_admin("Only an admin can edit an album across the library.")
    body = request.json or {}
    album = (body.get("album") or "").strip()
    name = (body.get("name") or "").strip() or None
    artist = (body.get("artist") or "").strip() or None
    if not album or not (name or artist):
        abort(400, "Nothing to change.")
    from metadata_ops import edit_album
    tracks = edit_album(current_app, album, name=name, artist=artist)
    if not tracks:
        abort(404, "That album isn't in the library any more.")
    return jsonify({"album": name or album, "updated": len(tracks)})


@library_blueprint.route("/api/albums/cover", methods=["POST"])
@login_required
def album_cover():
    """Set one cover image on every song of an album."""
    _require_admin("Only an admin can edit an album across the library.")
    album = (request.form.get("album") or "").strip()
    upload = request.files.get("cover")
    if not album or not upload:
        abort(400, "Choose an image for the cover.")
    from art import _to_jpeg
    from metadata_ops import set_cover
    jpg = _to_jpeg(upload.read())
    if not jpg:
        abort(400, "That file isn't an image tapes can read. Try a JPG or PNG.")
    tracks = Track.query.filter(Track.album == album).all()
    if not tracks:
        abort(404, "That album isn't in the library any more.")
    for t in tracks:
        set_cover(current_app, t, jpg)
    db.session.commit()
    return jsonify({"album": album, "updated": len(tracks), "cover_id": tracks[0].id})


@library_blueprint.route("/api/tracks/tidy", methods=["POST"])
@login_required
def tidy_route():
    """Re-run the rip cleanup on these songs (at most 25 per call)."""
    ids = [i for i in (request.json or {}).get("track_ids", []) if isinstance(i, int)][:25]
    if not ids:
        abort(400, "Nothing to tidy.")
    from metadata_ops import tidy_tracks
    tracks = Track.query.filter(Track.id.in_(ids)).all()
    return jsonify(tidy_tracks(current_app, tracks))


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


# Most results /api/tracks returns for one search.
MAX_SEARCH_RESULTS = 100


@library_blueprint.route("/api/tracks")
@login_required
def search_tracks():
    """Tracks whose title, artist or album contains every word of ``q`` (case-
    insensitive), best-known first. For programmatic clients (the MCP server);
    the deck filters its loaded list in the browser."""
    words = (request.args.get("q") or "").split()
    if not words:
        abort(400, "Say what to search for.")
    limit = min(max(request.args.get("limit", 25, type=int) or 25, 1), MAX_SEARCH_RESULTS)
    query = Track.query
    for word in words:
        like = f"%{word}%"
        query = query.filter(or_(Track.title.ilike(like), Track.artist.ilike(like),
                                 Track.album.ilike(like)))
    tracks = (query.order_by(Track.artist.is_(None), Track.artist, Track.album,
                             Track.track_no, Track.title)
              .limit(limit).all())
    return jsonify(_serialize(tracks))


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
        abort(400, "A song needs a title.")
    artist = _clean("artist") if "artist" in data else None
    album = _clean("album") if "album" in data else None
    track_no = None
    if "track_no" in data:
        raw = data.get("track_no")
        try:
            track_no = int(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            abort(400, "Track number must be a number.")

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
    """Move a track to the trash (undoable via /restore). Its tape links and
    play history are kept until the trash is purged."""
    _require_admin("Only an admin can delete songs from the library.")
    t = Track.query.get_or_404(track_id)
    from trash import purge_trash, trash_track
    trash_track(current_app, t)
    purge_trash(current_app)
    return "", 204


@library_blueprint.route("/api/tracks/<int:track_id>/restore", methods=["POST"])
@login_required
def restore_track_route(track_id):
    """Undo a delete."""
    _require_admin("Only an admin can delete songs from the library.")
    from trash import get_trashed, restore_track
    t = get_trashed(track_id)
    if t is None:
        abort(404, "That song isn't in the trash any more.")
    restore_track(current_app, t)
    return jsonify(t.to_dict())


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


# POST is for navigator.sendBeacon (which can only POST): the page saves its
# playhead that way as it closes, when an ordinary fetch would be cancelled.
@library_blueprint.route("/api/playstate", methods=["GET", "PUT", "POST"])
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

    data = request.get_json(force=True, silent=True) or {}
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
