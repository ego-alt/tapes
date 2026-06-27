"""Shared file-serving helpers for the music and podcast stream/cover routes."""
import pathlib
from urllib.parse import quote

from flask import Response, current_app, send_file


def accel_audio(rel_path: str, ctype: str):
    """Serve an audio file under MUSIC_DIR: via nginx X-Accel-Redirect when enabled
    (lets nginx handle range/seek), else Flask send_file with range support."""
    if current_app.config.get("USE_X_ACCEL"):
        resp = Response()
        resp.headers["X-Accel-Redirect"] = "/_audio/" + quote(rel_path)
        resp.headers["Content-Type"] = ctype
        resp.headers["Accept-Ranges"] = "bytes"
        return resp
    return send_file(pathlib.Path(current_app.config["MUSIC_DIR"]) / rel_path,
                     conditional=True, mimetype=ctype)


def cached_jpeg(path):
    """Send a JPEG cover with a week-long cache (covers are stable per file hash;
    send_file's ETag still lets the browser revalidate cheaply)."""
    resp = send_file(path, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp
