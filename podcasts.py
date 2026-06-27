"""Podcast feed layer — RSS + YouTube, no Flask.

Two source types feed the same Show/Episode model:
  - rss:     a podcast RSS feed; episodes are <enclosure> audio URLs.
  - youtube: a channel/playlist (a show) or a single video (a loose episode).

Adding/refreshing only catalogues *metadata* (cheap). The audio is fetched on
demand the first time an episode is played — see downloader._process_podcast.
"""
import datetime as _dt
import pathlib
import re
import time
import urllib.request
from urllib.parse import urlparse

import youtube
from models import Episode, db

_UA = "tapes-podcast/1.0 (+https://github.com/ego-alt/tapes)"


def detect_source(url: str) -> str:
    """Classify a pasted URL. YouTube hosts → 'youtube'; everything else is
    treated as an RSS feed (parse_rss validates and raises if it isn't one)."""
    return "youtube" if youtube.is_youtube(url) else "rss"


def _struct_to_dt(st) -> _dt.datetime | None:
    if not st:
        return None
    try:
        return _dt.datetime.fromtimestamp(time.mktime(st))
    except Exception:  # noqa: BLE001
        return None


def _parse_duration(val) -> float | None:
    """itunes:duration is either seconds ('3600') or 'HH:MM:SS' / 'MM:SS'."""
    if val is None:
        return None
    s = str(val).strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return None
        secs = 0.0
        for n in nums:
            secs = secs * 60 + n
        return secs
    try:
        return float(s)
    except ValueError:
        return None


# ---------- parsing ----------

def parse_rss(url: str):
    """Return (show_meta, [episode_meta]). Raises ValueError if it isn't a usable feed."""
    import feedparser

    feed = feedparser.parse(url, agent=_UA)
    chan = feed.get("feed") or {}
    entries = feed.get("entries") or []
    if not chan.get("title") and not entries:
        raise ValueError("not a readable RSS feed")

    image = ""
    if chan.get("image") and chan["image"].get("href"):
        image = chan["image"]["href"]
    elif chan.get("itunes_image", {}).get("href"):
        image = chan["itunes_image"]["href"]

    show = {
        "title": chan.get("title") or url,
        "source_type": "rss",
        "source_url": url,
        "description": chan.get("subtitle") or chan.get("summary") or "",
        "image_url": image,
    }

    episodes = []
    for e in entries:
        enclosure = ""
        for link in (e.get("links") or []):
            if link.get("rel") == "enclosure" and (link.get("type") or "").startswith("audio"):
                enclosure = link.get("href") or ""
                break
        if not enclosure:  # some feeds only set <enclosure> without type
            for link in (e.get("links") or []):
                if link.get("rel") == "enclosure":
                    enclosure = link.get("href") or ""
                    break
        if not enclosure:
            continue
        episodes.append({
            "guid": e.get("id") or enclosure,
            "title": e.get("title") or "(untitled)",
            "source_url": enclosure,
            "source_type": "rss",
            "duration_s": _parse_duration(e.get("itunes_duration")),
            "description": e.get("summary") or "",
            "published_at": _struct_to_dt(e.get("published_parsed")),
        })
    return show, episodes


def _yt_json(url: str):
    data = youtube.flat_playlist_json(url, end=300, timeout=90)
    if data is None:
        raise ValueError("yt-dlp could not read that URL")
    return data


def parse_youtube(url: str):
    """Return (show_meta | None, [episode_meta]). show_meta is None for a single
    video (→ a loose episode); a channel/playlist yields a show + its videos."""
    data = _yt_json(url)

    def _episode(entry):
        vid = entry.get("id")
        if not vid:
            return None
        return {
            "guid": vid,
            "title": entry.get("title") or "(untitled)",
            "source_url": f"https://www.youtube.com/watch?v={vid}",
            "source_type": "youtube",
            "duration_s": entry.get("duration"),
            "description": entry.get("description") or "",
            "published_at": None,
            "channel_id": entry.get("channel_id"),
        }

    if data.get("_type") == "playlist":
        eps = []
        for entry in (data.get("entries") or []):
            if not entry:
                continue
            # A channel can nest tabs as sub-playlists; flatten one level.
            if entry.get("_type") == "playlist":
                for sub in (entry.get("entries") or []):
                    ep = sub and _episode(sub)
                    if ep:
                        eps.append(ep)
            else:
                ep = _episode(entry)
                if ep:
                    eps.append(ep)
        thumbs = data.get("thumbnails") or []
        show = {
            "title": data.get("title") or "YouTube",
            "source_type": "youtube",
            "source_url": url,
            "description": data.get("description") or "",
            "image_url": thumbs[-1].get("url", "") if thumbs else "",
        }
        return show, eps

    # Single video.
    ep = _episode(data)
    return None, ([ep] if ep else [])


def parse_feed(url: str, source_type: str):
    return parse_youtube(url) if source_type == "youtube" else parse_rss(url)


# ---------- cataloguing (DB; caller commits) ----------

def upsert_episodes(user_id: int, show_id, ep_metas) -> int:
    """Add Episode rows that don't already exist for this (show, guid). Returns the
    count of newly-added episodes. Does not commit — the caller does."""
    existing = set()
    q = Episode.query.filter_by(user_id=user_id)
    q = q.filter_by(show_id=show_id) if show_id is not None else q.filter(Episode.show_id.is_(None))
    for guid, in db.session.query(Episode.guid).filter(
            Episode.user_id == user_id,
            (Episode.show_id == show_id) if show_id is not None else Episode.show_id.is_(None)):
        existing.add(guid)

    added = 0
    for m in ep_metas:
        if m["guid"] in existing:
            continue
        existing.add(m["guid"])
        db.session.add(Episode(
            user_id=user_id, show_id=show_id, guid=m["guid"], title=m["title"],
            source_url=m["source_url"], source_type=m["source_type"],
            channel_id=m.get("channel_id"),
            duration_s=m.get("duration_s"), description=m.get("description") or "",
            published_at=m.get("published_at"), status="new",
        ))
        added += 1
    return added


def download_show_image(image_url: str, cover_dir, show_id: int) -> bool:
    """Cache a show's cover to <cover_dir>/shows/<id>.jpg (a 500px JPEG). Best-effort."""
    if not image_url:
        return False
    try:
        from io import BytesIO

        from PIL import Image
        req = urllib.request.Request(image_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=20) as r:  # noqa: S310 — user-supplied feed
            raw = r.read()
        out_dir = pathlib.Path(cover_dir) / "shows"
        out_dir.mkdir(parents=True, exist_ok=True)
        img = Image.open(BytesIO(raw)).convert("RGB")
        img.thumbnail((500, 500))
        img.save(out_dir / f"{show_id}.jpg", "JPEG", quality=85)
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------- file paths for download-on-play ----------

def _slug(text: str, limit: int = 60) -> str:
    s = re.sub(r"[^\w\- ]+", "", text, flags=re.UNICODE).strip().replace(" ", "_")
    return (s[:limit] or "episode")


def _ext_for(ep) -> str:
    if ep.source_type == "youtube":
        return "mp3"  # we always extract to mp3
    # RSS: derive from the enclosure URL path, default mp3.
    path = urlparse(ep.source_url).path
    ext = pathlib.Path(path).suffix.lower().lstrip(".")
    return ext if ext in ("mp3", "m4a", "aac", "ogg", "opus", "wav") else "mp3"


def episode_target(podcast_dir, ep) -> pathlib.Path:
    """Absolute target path for an episode's audio. Keyed by episode id so it's
    always unique even across re-titles."""
    sub = str(ep.show_id) if ep.show_id is not None else "loose"
    folder = pathlib.Path(podcast_dir) / sub
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{ep.id}-{_slug(ep.title)}.{_ext_for(ep)}"


def normalize_video_url(url: str) -> str:
    """For a single YouTube video, reduce to a canonical watch URL (drops list= etc.)."""
    return youtube.canonical_watch_url(url)
