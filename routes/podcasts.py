import pathlib
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, request
from flask_login import current_user, login_required

import podcasts
from downloader import enqueue
from models import DownloadJob, Episode, Show, db

from .serving import accel_audio, cached_jpeg

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
        # Manual shows (built from loose episodes) have no feed URL → can't refresh.
        "refreshable": bool(s.source_url),
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

    # Single YouTube video → a loose episode, unless its channel is already linked
    # to a show (opt-in auto-routing), in which case it files into that show.
    if show_meta is None:
        if not eps:
            abort(400, "nothing to add")
        for m in eps:
            m["source_url"] = podcasts.normalize_video_url(m["source_url"])
        ch = eps[0].get("channel_id")
        target = Show.query.filter_by(user_id=_uid(), channel_id=ch).first() if ch else None
        added = podcasts.upsert_episodes(_uid(), target.id if target else None, eps)
        db.session.commit()
        if target:
            return jsonify({"assigned": _show_dict(target), "added": added}), 201
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


@podcasts_blueprint.route("/api/podcast/episodes/<int:eid>/assign", methods=["POST"])
@login_required
def assign_episode(eid):
    """File a loose episode into a show — an existing one (show_id) or a new one
    (new_show_name). For a YouTube episode this links the show to the video's
    channel, so future videos from it auto-route here (opt-in)."""
    ep = _episode_or_404(eid)
    data = request.json or {}
    sid = data.get("show_id")
    name = (data.get("new_show_name") or "").strip()

    if sid is not None:
        show = Show.query.filter_by(id=sid, user_id=_uid()).first_or_404()
    elif name:
        # A manual show; if we can link a channel, give it that channel's URL so it
        # also becomes refreshable like a real subscription.
        src = f"https://www.youtube.com/channel/{ep.channel_id}" if ep.channel_id else ""
        show = Show(user_id=_uid(), title=name, source_type="youtube", source_url=src)
        db.session.add(show)
        db.session.flush()
    else:
        abort(400, "show_id or new_show_name required")

    ep.show_id = show.id
    if ep.channel_id and not show.channel_id:
        show.channel_id = ep.channel_id
        if not show.source_url:
            show.source_url = f"https://www.youtube.com/channel/{ep.channel_id}"
    db.session.commit()
    return jsonify({"show": _show_dict(show)})


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
    return accel_audio(ep.file_path, ctype)


def _serve_show_cover(show_id):
    p = pathlib.Path(current_app.config["COVER_DIR"]) / "shows" / f"{show_id}.jpg"
    if not p.exists():
        abort(404)
    return cached_jpeg(p)


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
