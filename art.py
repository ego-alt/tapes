"""Album-art lookup via MusicBrainz + the Cover Art Archive (no API key).

Given a confident artist + album, find a matching release and return its front
cover image bytes — used to replace the weak video thumbnail yt-dlp embeds.

MusicBrainz etiquette is mandatory and enforced here: a descriptive User-Agent
and a >=1 request/second rate limit (they block clients that skip either). The
Cover Art Archive has no key and no hard limit, but we stay polite.

Everything returns None / no-ops on a miss so callers keep the existing art.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from io import BytesIO

_MB_SEARCH = "https://musicbrainz.org/ws/2/release/"
_CAA_FRONT = "https://coverartarchive.org/release/{mbid}/front-{size}"

# MusicBrainz requires a meaningful UA identifying the app + a contact.
_UA = os.environ.get("MUSICBRAINZ_UA") or (
    "tapes/0.1 ( "
    + (os.environ.get("MUSICBRAINZ_CONTACT") or "https://github.com/ego-alt/tapes")
    + " )"
)

_MIN_SCORE = 85  # MusicBrainz search score (0–100); below this is too loose to trust.
_lock = threading.Lock()
_last_call = 0.0


def _throttle():
    """Serialize MusicBrainz calls to <= 1/sec (across the worker + CLI threads)."""
    global _last_call
    with _lock:
        wait = 1.0 - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _get(url: str, accept: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": accept})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def _search_releases(artist: str, album: str, limit: int = 5):
    # Strip quotes so they can't break the Lucene query.
    q = f'artist:"{artist.replace(chr(34), "")}" AND release:"{album.replace(chr(34), "")}"'
    url = _MB_SEARCH + "?" + urllib.parse.urlencode({"query": q, "fmt": "json", "limit": limit})
    _throttle()
    data = json.loads(_get(url, "application/json"))
    releases = data.get("releases") or []
    return [r for r in releases if (r.get("score") or 0) >= _MIN_SCORE]


def fetch_cover(artist: str, album: str, *, size: int = 500) -> bytes | None:
    """Return JPEG front-cover bytes for `artist`/`album`, or None on any miss.

    Walks the best-scoring releases and returns the first that has front art in
    the Cover Art Archive. Normalizes to JPEG so callers can embed it directly.
    """
    if not (artist and album):
        return None
    try:
        candidates = _search_releases(artist, album)
    except Exception:  # noqa: BLE001 — network/parse failures are a miss, not an error
        return None

    for rel in candidates:
        mbid = rel.get("id")
        if not mbid:
            continue
        try:
            raw = _get(_CAA_FRONT.format(mbid=mbid, size=size), "image/*")
        except Exception:  # noqa: BLE001 — 404 = no art for this release; try the next
            continue
        if raw:
            return _to_jpeg(raw)
    return None


def _to_jpeg(raw: bytes) -> bytes | None:
    from PIL import Image
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:  # noqa: BLE001
        return None
    buf = BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue()


def embed_cover(path: str, jpg_bytes: bytes):
    """Replace the file's front-cover (APIC) frame with `jpg_bytes`."""
    from mutagen.id3 import APIC, ID3
    from mutagen.id3._util import ID3NoHeaderError
    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("APIC")
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=jpg_bytes))
    tags.save(path)
