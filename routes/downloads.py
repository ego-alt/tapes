import json
import time

from flask import Blueprint, Response, abort, jsonify, request, stream_with_context
from flask_login import current_user, login_required

from downloader import enqueue, expand_playlist
from models import DownloadJob, Playlist, db

downloads_blueprint = Blueprint("downloads", __name__)


def _active_jobs(user_id):
    return (DownloadJob.query.filter_by(user_id=user_id)
            .filter(DownloadJob.status.in_(["queued", "running"]))
            .order_by(DownloadJob.created_at.desc()).all())


@downloads_blueprint.route("/api/downloads", methods=["GET"])
@login_required
def list_jobs():
    return jsonify([j.to_dict() for j in _active_jobs(current_user.id)])


@downloads_blueprint.route("/api/downloads/stream")
@login_required
def stream_jobs():
    """Server-Sent Events of active jobs. Job state lives in the DB (shared
    across workers), so we poll it here and push only on change. Ends shortly
    after the queue drains; the client reopens the stream on the next submit."""
    uid = current_user.id

    @stream_with_context
    def gen():
        last = None
        idle = ticks = 0
        while True:
            jobs = _active_jobs(uid)
            payload = json.dumps([j.to_dict() for j in jobs])
            if payload != last:
                last = payload
                yield f"data: {payload}\n\n"
            elif ticks % 15 == 0:
                yield ": ping\n\n"  # keep proxies from closing an idle stream
            if jobs:
                idle = 0
            else:
                idle += 1
                if idle >= 3:
                    yield "event: done\ndata: {}\n\n"
                    break
            db.session.remove()  # fresh read next loop; don't hold a txn open
            ticks += 1
            time.sleep(1)

    return Response(gen(), mimetype="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",  # tell nginx not to buffer the stream
    })


@downloads_blueprint.route("/api/downloads", methods=["POST"])
@login_required
def create_job():
    url = (request.json or {}).get("url", "").strip()
    if not url.startswith(("http://", "https://")):
        abort(400, "valid url required")

    video_urls, playlist_title = expand_playlist(url)

    playlist_id = None
    if playlist_title:
        pl = Playlist(user_id=current_user.id, name=playlist_title)
        db.session.add(pl)
        db.session.flush()
        playlist_id = pl.id

    jobs = []
    for u in video_urls:
        job = DownloadJob(user_id=current_user.id, url=u, status="queued", playlist_id=playlist_id)
        db.session.add(job)
        jobs.append(job)
    db.session.commit()
    for job in jobs:
        enqueue(job.id)

    return jsonify({"queued": len(jobs), "playlist": playlist_title}), 201
