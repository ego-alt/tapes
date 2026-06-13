from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from downloader import enqueue, expand_playlist
from models import DownloadJob, Playlist, db

downloads_blueprint = Blueprint("downloads", __name__)


@downloads_blueprint.route("/api/downloads", methods=["GET"])
@login_required
def list_jobs():
    jobs = (DownloadJob.query.filter_by(user_id=current_user.id)
            .filter(DownloadJob.status.in_(["queued", "running"]))
            .order_by(DownloadJob.created_at.desc()).all())
    return jsonify([j.to_dict() for j in jobs])


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
