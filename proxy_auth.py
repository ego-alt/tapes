"""Auth resolution for both modes.

Proxy mode (behind the dashboard nginx): trust ``X-Forwarded-User``, mirroring
calendar/library. Standalone dev: no login wall — auto-attach a single local
user so the cassette is immediately pokeable. Either way flask-login's
request_loader resolves the user per request.
"""

from flask import current_app, request

from models import User, db


def is_proxy_mode() -> bool:
    return bool(current_app.config.get("AUTH_PROXY_HEADER"))


def _get_or_create(username: str) -> User:
    user = User.query.filter_by(username=username).first()
    if user is None:
        user = User(username=username, password_hash=None)
        db.session.add(user)
        db.session.commit()
    return user


def load_user_for_request() -> User | None:
    if is_proxy_mode():
        username = request.headers.get(current_app.config["AUTH_PROXY_HEADER"])
        if not username:
            return None
        return _get_or_create(username)
    # Standalone dev: single implicit local user, no login required.
    return _get_or_create(current_app.config.get("LOCAL_USER", "local"))
