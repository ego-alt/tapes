from flask import Blueprint, render_template
from flask_login import login_required

index_blueprint = Blueprint("index_routes", __name__)


@index_blueprint.route("/")
@login_required
def index():
    return render_template("index.html")
