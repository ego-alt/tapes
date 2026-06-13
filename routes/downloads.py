from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from downloader import enqueue
from models import DownloadJob, db

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
    job = DownloadJob(user_id=current_user.id, url=url, status="queued")
    db.session.add(job)
    db.session.commit()
    enqueue(job.id)
    return jsonify(job.to_dict()), 201
