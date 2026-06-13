from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required
from sqlalchemy import or_

from models import Track

index_blueprint = Blueprint("index_routes", __name__)


@index_blueprint.route("/")
@login_required
def index():
    return render_template("index.html")


@index_blueprint.route("/api/tracks")
@login_required
def api_tracks():
    q = (request.args.get("q") or "").strip()
    query = Track.query
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(Track.title.ilike(like), Track.artist.ilike(like), Track.album.ilike(like))
        )
    tracks = query.order_by(
        Track.artist.is_(None),  # named artists first
        Track.artist,
        Track.album,
        Track.track_no,
        Track.title,
    ).all()
    return jsonify([t.to_dict() for t in tracks])
