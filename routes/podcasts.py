import pathlib
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

import podcasts
from downloader import enqueue
from models import DownloadJob, Episode, Show, db

podcasts_blueprint = Blueprint("podcasts", __name__)

_CTYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/mp4",
    ".ogg": "audio/ogg", ".opus": "audio/ogg", ".wav": "audio/wav",
}


def _uid():
    return current_user.id


def _episode_or_404(eid):
    return Episode.query.filter_by(id=eid, user_id=_uid()).first_or_404()


def _show_dict(s):
    total = Episode.query.filter_by(user_id=_uid(), show_id=s.id).count()
    unplayed = Episode.query.filter_by(user_id=_uid(), show_id=s.id, played=False).count()
    return {
        "id": s.id, "title": s.title, "source_type": s.source_type,
        "has_image": bool(s.has_image), "count": total, "unplayed": unplayed,
    }


# ---------- add / refresh / list ----------

@podcasts_blueprint.route("/api/podcast/add", methods=["POST"])
@login_required
def add():
    url = (request.json or {}).get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        abort(400, "valid url required")
    stype = podcasts.detect_source(url)
    try:
        show_meta, eps = podcasts.parse_feed(url, stype)
    except Exception as e:  # noqa: BLE001 — surface a clean message to the client
        abort(400, f"couldn't read that feed: {e}")

    # Single YouTube video → a loose episode (no show).
    if show_meta is None:
        if not eps:
            abort(400, "nothing to add")
        for m in eps:
            m["source_url"] = podcasts.normalize_video_url(m["source_url"])
        added = podcasts.upsert_episodes(_uid(), None, eps)
        db.session.commit()
        return jsonify({"loose": True, "added": added}), 201

    show = Show.query.filter_by(user_id=_uid(), source_url=url).first()
    created = False
    if show is None:
        show = Show(user_id=_uid(), title=show_meta["title"], source_type=stype,
                    source_url=url, description=show_meta.get("description") or "")
        db.session.add(show)
        db.session.flush()
        created = True
        if show_meta.get("image_url"):
            show.has_image = podcasts.download_show_image(
                show_meta["image_url"], current_app.config["COVER_DIR"], show.id)
    added = podcasts.upsert_episodes(_uid(), show.id, eps)
    show.last_refreshed_at = datetime.now()
    db.session.commit()
    return jsonify({**_show_dict(show), "added": added, "created": created}), 201


@podcasts_blueprint.route("/api/podcast/shows")
@login_required
def shows():
    rows = Show.query.filter_by(user_id=_uid()).order_by(Show.title).all()
    loose_total = Episode.query.filter_by(user_id=_uid(), show_id=None).count()
    loose_unplayed = Episode.query.filter_by(user_id=_uid(), show_id=None, played=False).count()
    return jsonify({
        "shows": [_show_dict(s) for s in rows],
        "loose_count": loose_total,
        "loose_unplayed": loose_unplayed,
    })


def _episodes_query(show_id):
    q = Episode.query.filter_by(user_id=_uid())
    q = q.filter_by(show_id=show_id) if show_id is not None else q.filter(Episode.show_id.is_(None))
    # Newest first; episodes without a date (YouTube) fall back to insert order.
    return q.order_by(Episode.published_at.is_(None), Episode.published_at.desc(),
                      Episode.id.desc()).all()


@podcasts_blueprint.route("/api/podcast/shows/<int:sid>/episodes")
@login_required
def show_episodes(sid):
    show = Show.query.filter_by(id=sid, user_id=_uid()).first_or_404()
    eps = [{**e.to_dict(), "show": show.title} for e in _episodes_query(sid)]
    return jsonify({"show": _show_dict(show), "episodes": eps})


@podcasts_blueprint.route("/api/podcast/episodes/loose")
@login_required
def loose_episodes():
    eps = [{**e.to_dict(), "show": ""} for e in _episodes_query(None)]
    return jsonify({"episodes": eps})


@podcasts_blueprint.route("/api/podcast/shows/<int:sid>/refresh", methods=["POST"])
@login_required
def refresh(sid):
    show = Show.query.filter_by(id=sid, user_id=_uid()).first_or_404()
    try:
        _meta, eps = podcasts.parse_feed(show.source_url, show.source_type)
    except Exception as e:  # noqa: BLE001
        abort(400, f"refresh failed: {e}")
    added = podcasts.upsert_episodes(_uid(), show.id, eps)
    show.last_refreshed_at = datetime.now()
    db.session.commit()
    return jsonify({"added": added})


@podcasts_blueprint.route("/api/podcast/shows/<int:sid>", methods=["DELETE"])
@login_required
def delete_show(sid):
    show = Show.query.filter_by(id=sid, user_id=_uid()).first_or_404()
    music_dir = pathlib.Path(current_app.config["MUSIC_DIR"])
    eps = Episode.query.filter_by(user_id=_uid(), show_id=sid).all()
    for ep in eps:
        _delete_episode_file(music_dir, ep)
        DownloadJob.query.filter_by(episode_id=ep.id).delete()
        db.session.delete(ep)
    # The show's episode folder + cached cover.
    _rmdir(pathlib.Path(current_app.config["PODCAST_DIR"]) / str(sid))
    cover = pathlib.Path(current_app.config["COVER_DIR"]) / "shows" / f"{sid}.jpg"
    cover.unlink(missing_ok=True)
    db.session.delete(show)
    db.session.commit()
    return "", 204


# ---------- playback (download-on-play, progress, played) ----------

@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>/play", methods=["POST"])
@login_required
def play(eid):
    ep = _episode_or_404(eid)
    music_dir = pathlib.Path(current_app.config["MUSIC_DIR"])
    if ep.status == "ready" and ep.file_path and (music_dir / ep.file_path).exists():
        return jsonify({"ready": True, "episode": ep.to_dict()})

    # Reuse an in-flight job for this episode rather than queueing a duplicate.
    job = (DownloadJob.query.filter_by(episode_id=ep.id)
           .filter(DownloadJob.status.in_(["queued", "running"])).first())
    if job is None:
        job = DownloadJob(user_id=_uid(), url=ep.source_url, kind="podcast",
                          episode_id=ep.id, status="queued")
        db.session.add(job)
        db.session.commit()
        enqueue(job.id)
    return jsonify({"ready": False, "job_id": job.id, "episode": ep.to_dict()})


@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>/progress", methods=["PUT"])
@login_required
def progress(eid):
    ep = _episode_or_404(eid)
    data = request.json or {}
    if "position" in data:
        ep.position_s = data.get("position") or 0
    if "played" in data:
        ep.played = bool(data["played"])
    db.session.commit()
    return "", 204


@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>/played", methods=["POST"])
@login_required
def set_played(eid):
    ep = _episode_or_404(eid)
    ep.played = bool((request.json or {}).get("played", True))
    db.session.commit()
    return jsonify({"played": ep.played})


@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>/remove-download", methods=["POST"])
@login_required
def remove_download(eid):
    """Drop the cached audio file but keep the episode (status back to 'new', so it
    can be re-downloaded). For reclaiming disk without losing the episode."""
    ep = _episode_or_404(eid)
    _delete_episode_file(pathlib.Path(current_app.config["MUSIC_DIR"]), ep)
    ep.file_path = None
    ep.status = "new"
    db.session.commit()
    return jsonify({"status": ep.status})


@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>", methods=["DELETE"])
@login_required
def delete_episode(eid):
    """Remove an episode entirely — its file, jobs, and row. Note: for a subscribed
    show, a later refresh re-catalogues it from the feed (as 'new')."""
    ep = _episode_or_404(eid)
    _delete_episode_file(pathlib.Path(current_app.config["MUSIC_DIR"]), ep)
    DownloadJob.query.filter_by(episode_id=ep.id).delete()
    db.session.delete(ep)
    db.session.commit()
    return "", 204


# ---------- audio + cover ----------

@podcasts_blueprint.route("/podcast/stream/<int:eid>")
@login_required
def stream(eid):
    ep = _episode_or_404(eid)
    if not ep.file_path:
        abort(404)
    path = pathlib.Path(current_app.config["MUSIC_DIR"]) / ep.file_path
    if not path.exists():
        abort(404)
    ctype = _CTYPES.get(path.suffix.lower(), "audio/mpeg")
    if current_app.config.get("USE_X_ACCEL"):
        resp = Response()
        resp.headers["X-Accel-Redirect"] = "/_audio/" + quote(ep.file_path)
        resp.headers["Content-Type"] = ctype
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    return send_file(path, conditional=True, mimetype=ctype)


def _serve_show_cover(show_id):
    p = pathlib.Path(current_app.config["COVER_DIR"]) / "shows" / f"{show_id}.jpg"
    if not p.exists():
        abort(404)
    resp = send_file(p, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


@podcasts_blueprint.route("/podcast/cover/show/<int:sid>")
@login_required
def show_cover(sid):
    Show.query.filter_by(id=sid, user_id=_uid()).first_or_404()
    return _serve_show_cover(sid)


@podcasts_blueprint.route("/podcast/cover/episode/<int:eid>")
@login_required
def episode_cover(eid):
    ep = _episode_or_404(eid)
    if ep.show_id is None:
        abort(404)  # loose episodes have no art in v1
    return _serve_show_cover(ep.show_id)


# ---------- helpers ----------

def _delete_episode_file(music_dir, ep):
    if ep.file_path:
        try:
            (music_dir / ep.file_path).unlink(missing_ok=True)
        except OSError:
            pass


def _rmdir(path: pathlib.Path):
    try:
        for child in path.glob("*"):
            child.unlink(missing_ok=True)
        path.rmdir()
    except OSError:
        pass
