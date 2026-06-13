from flask import Blueprint, redirect, url_for
from flask_login import logout_user

from proxy_auth import is_proxy_mode

auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")


@auth_blueprint.route("/logout")
def logout():
    if is_proxy_mode():
        return redirect("/logout", code=302)
    logout_user()
    return redirect(url_for("index_routes.index"))
