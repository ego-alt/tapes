"""Small YouTube helpers shared by the ripper (downloader.py) and the podcast
feed layer (podcasts.py): URL classification/parsing and the flat-playlist
metadata fetch. Stdlib only — no Flask, no DB."""
import json
import subprocess
import sys
from urllib.parse import parse_qs, urlparse

HOSTS = ("youtube.com", "youtu.be", "music.youtube.com")


def is_youtube(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return False
    host = host[4:] if host.startswith("www.") else host
    return any(host == h or host.endswith("." + h) for h in HOSTS)


def video_id(url: str) -> str | None:
    """The YouTube video id for a watch / youtu.be URL, or None."""
    try:
        u = urlparse(url)
        if "youtu.be" in (u.netloc or ""):
            return u.path.lstrip("/") or None
        return (parse_qs(u.query).get("v") or [None])[0]
    except Exception:  # noqa: BLE001
        return None


def canonical_watch_url(url: str) -> str:
    """Reduce a single-video URL to a canonical watch URL (drops list=, etc.)."""
    vid = video_id(url)
    return f"https://www.youtube.com/watch?v={vid}" if vid else url


def flat_playlist_json(url: str, *, end: int, timeout: int):
    """yt-dlp's flat-playlist single-JSON dump → parsed dict, or None on failure."""
    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         "--flat-playlist", "--dump-single-json", "--no-warnings",
         "--playlist-end", str(end), url],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
