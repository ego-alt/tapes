import json

from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from models import Favorite, Play, Playlist, PlaylistTrack, PlayState, Track, db

library_blueprint = Blueprint("library", __name__)


def _uid():
    return current_user.id


def _fav_ids():
    return {f.track_id for f in Favorite.query.filter_by(user_id=_uid()).all()}


def _serialize(tracks):
    favs = _fav_ids()
    return [t.to_dict(fav=t.id in favs) for t in tracks]


# ---- shelf ----

@library_blueprint.route("/api/playlists")
@login_required
def playlists():
    uid = _uid()
    singles_q = Track.query.filter(or_(Track.album.is_(None), Track.album == ""))
    shelf = [
        {"key": "all", "name": "All Tracks", "kind": "builtin", "count": Track.query.count()},
        {"key": "singles", "name": "Singles", "kind": "builtin", "count": singles_q.count()},
        {"key": "favorites", "name": "Favorites", "kind": "builtin",
         "count": Favorite.query.filter_by(user_id=uid).count()},
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


@library_blueprint.route("/api/playlists/<key>/tracks")
@login_required
def playlist_tracks(key):
    order = (Track.artist.is_(None), Track.artist, Track.album, Track.track_no, Track.title)
    if key == "all":
        tracks = Track.query.order_by(*order).all()
    elif key == "singles":
        tracks = (Track.query.filter(or_(Track.album.is_(None), Track.album == ""))
                  .order_by(*order).all())
    elif key == "favorites":
        tracks = (Track.query.join(Favorite, Favorite.track_id == Track.id)
                  .filter(Favorite.user_id == _uid())
                  .order_by(Favorite.created_at.desc()).all())
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


# ---- favorites / plays / playstate ----

@library_blueprint.route("/api/favorites/<int:track_id>", methods=["POST"])
@login_required
def toggle_favorite(track_id):
    existing = Favorite.query.filter_by(user_id=_uid(), track_id=track_id).first()
    if existing:
        db.session.delete(existing)
        fav = False
    else:
        db.session.add(Favorite(user_id=_uid(), track_id=track_id))
        fav = True
    db.session.commit()
    return jsonify({"fav": fav})


@library_blueprint.route("/api/plays", methods=["POST"])
@login_required
def record_play():
    track_id = (request.json or {}).get("track_id")
    if track_id:
        db.session.add(Play(user_id=_uid(), track_id=track_id))
        db.session.commit()
    return "", 204


@library_blueprint.route("/api/playstate", methods=["GET", "PUT"])
@login_required
def playstate():
    ps = db.session.get(PlayState, _uid())
    if request.method == "GET":
        if not ps:
            return jsonify({"queue": [], "index": 0, "position": 0})
        return jsonify({
            "queue": json.loads(ps.queue_json or "[]"),
            "index": ps.index or 0,
            "position": ps.position_s or 0,
        })
    data = request.json or {}
    if not ps:
        ps = PlayState(user_id=_uid())
        db.session.add(ps)
    ps.queue_json = json.dumps(data.get("queue", []))
    ps.index = data.get("index", 0)
    ps.position_s = data.get("position", 0)
    db.session.commit()
    return "", 204
