"""Install + offline support: the web app manifest, the service worker and
the favicon.

Served from the app root (not /static/) so behind the dashboard proxy they
live at /music/manifest.webmanifest and /music/sw.js, and the worker's scope
covers the whole /music/ mount.
"""

from flask import Blueprint, current_app, jsonify, request, send_from_directory, url_for

pwa_blueprint = Blueprint("pwa", __name__)


@pwa_blueprint.route("/manifest.webmanifest")
def manifest():
    root = request.script_root + "/"
    icon = lambda name: url_for("static", filename=f"icons/{name}")  # noqa: E731
    response = jsonify({
        "name": "Tapes",
        "short_name": "Tapes",
        "description": "Your music and podcasts on a cassette deck.",
        "start_url": root,
        "scope": root,
        "display": "standalone",
        "background_color": "#282828",
        "theme_color": "#282828",
        "icons": [
            {"src": icon("icon-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": icon("icon-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": icon("icon-maskable-512.png"), "sizes": "512x512", "type": "image/png",
             "purpose": "maskable"},
        ],
    })
    response.mimetype = "application/manifest+json"
    return response


@pwa_blueprint.route("/sw.js")
def service_worker():
    response = send_from_directory(current_app.static_folder + "/js", "sw.js",
                                   mimetype="application/javascript")
    # Browsers must always re-check the worker so updates roll out promptly.
    response.headers["Cache-Control"] = "no-cache"
    return response


@pwa_blueprint.route("/favicon.ico")
def favicon():
    return send_from_directory(current_app.static_folder, "favicon.ico",
                               mimetype="image/vnd.microsoft.icon", max_age=86400)
