"""Minimal auth surface. Stage 1 standalone needs no login (a local user is
auto-attached); behind the dashboard, nginx + X-Forwarded-User gate access.
Kept for parity and a working logout."""

from flask import Blueprint, redirect, url_for
from flask_login import logout_user

from proxy_auth import is_proxy_mode

auth_blueprint = Blueprint("auth", __name__, url_prefix="/auth")


@auth_blueprint.route("/logout")
def logout():
    if is_proxy_mode():
        # The dashboard owns the session; send the browser to its logout.
        return redirect("/logout", code=302)
    logout_user()
    return redirect(url_for("index_routes.index"))
