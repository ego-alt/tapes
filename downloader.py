import json
import pathlib
import queue
import re
import subprocess
import sys
import threading
from urllib.parse import urlparse

from cleaning import clean_meta, clean_title
from models import DownloadJob, PlaylistTrack, Track, db
from scan import scan_library

_job_queue: "queue.Queue[int]" = queue.Queue()
_started = False


def expand_playlist(url: str):
    """Return (video_url_list, playlist_title) or ([url], None) for non-playlist URLs."""
    try:
        if urlparse(url).path.rstrip("/") != "/playlist":
            return [url], None
    except Exception:
        return [url], None

    result = subprocess.run(
        [sys.executable, "-m", "yt_dlp",
         "--flat-playlist", "--dump-single-json", "--no-warnings",
         "--playlist-end", "500", url],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return [url], None
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return [url], None

    if data.get("_type") != "playlist":
        return [url], None

    title = data.get("title") or "Playlist"
    urls = [
        f"https://www.youtube.com/watch?v={e['id']}"
        for e in (data.get("entries") or [])
        if e and e.get("id")
    ]
    return (urls or [url]), title


def enqueue(job_id: int):
    _job_queue.put(job_id)


def start_worker(app):
    global _started
    if _started:
        return
    _started = True
    with app.app_context():
        # Requeue anything left mid-flight by a previous run.
        for j in DownloadJob.query.filter(DownloadJob.status.in_(["queued", "running"])).all():
            j.status = "queued"
            _job_queue.put(j.id)
        db.session.commit()
    threading.Thread(target=_loop, args=(app,), daemon=True).start()


def _loop(app):
    while True:
        job_id = _job_queue.get()
        with app.app_context():
            try:
                _process(app, job_id)
            except Exception as e:  # noqa: BLE001
                job = db.session.get(DownloadJob, job_id)
                if job:
                    job.status = "error"
                    job.message = str(e)[:300]
                    db.session.commit()
        _job_queue.task_done()


def _process(app, job_id: int):
    job = db.session.get(DownloadJob, job_id)
    if not job or job.status == "done":
        return
    job.status = "running"
    job.progress = 0
    job.message = ""
    db.session.commit()

    music_dir = pathlib.Path(app.config["MUSIC_DIR"])
    music_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-thumbnail", "--embed-metadata", "--write-info-json",
        "--no-playlist", "--newline",
        "-o", str(music_dir / "%(title)s.%(ext)s"), job.url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    final_mp3 = None
    title = None
    last_pct = -1
    for line in proc.stdout:
        line = line.strip()
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            pct = float(m.group(1))
            if int(pct) != last_pct:
                last_pct = int(pct)
                job.progress = pct
                if not title:
                    job.message = "downloading"
                db.session.commit()
        d = re.search(r"\[(?:ExtractAudio|download)\] Destination: (.+)", line)
        if d:
            path = d.group(1).strip()
            if path.endswith(".mp3"):
                final_mp3 = path
            if not title:
                title = clean_title(pathlib.Path(path).stem)
                job.message = title
                db.session.commit()

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("yt-dlp failed (see server log)")

    if not final_mp3:
        mp3s = sorted(music_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        if not mp3s:
            raise RuntimeError("no mp3 produced")
        final_mp3 = str(mp3s[-1])

    source = _read_source_meta(final_mp3, job.url)
    llm_ok = _clean_tag(final_mp3, source=source, use_llm=app.config.get("LLM_CLEANING", True))
    if app.config.get("ART_LOOKUP", True):
        _fetch_art(final_mp3)
    scan_library(music_dir, app.config["COVER_DIR"], full=False)

    rel = str(pathlib.Path(final_mp3).relative_to(music_dir))
    track = Track.query.filter_by(file_path=rel).first()
    if track:
        track.source_url = source.get("url") or job.url
        if llm_ok is not None:
            track.needs_llm = not llm_ok  # flag misses for `retag --llm --pending`
    job.track_id = track.id if track else None
    job.progress = 100
    job.status = "done"
    job.message = (track.title if track else "done")
    if job.playlist_id and track:
        exists = PlaylistTrack.query.filter_by(
            playlist_id=job.playlist_id, track_id=track.id
        ).first()
        if not exists:
            pos = PlaylistTrack.query.filter_by(playlist_id=job.playlist_id).count()
            db.session.add(PlaylistTrack(
                playlist_id=job.playlist_id, track_id=track.id, position=pos
            ))
    db.session.commit()


def _read_source_meta(mp3_path: str, fallback_url: str) -> dict:
    """Pull a few high-signal fields from yt-dlp's `.info.json` (written alongside
    the mp3), then delete it. The video description is deliberately ignored."""
    src = {"url": fallback_url}
    try:
        info_path = pathlib.Path(mp3_path).with_suffix(".info.json")
        if not info_path.exists():
            cands = list(info_path.parent.glob(pathlib.Path(mp3_path).stem + "*.info.json"))
            info_path = cands[0] if cands else None
        if info_path and info_path.exists():
            data = json.loads(info_path.read_text())
            src.update({
                "url": data.get("webpage_url") or fallback_url,
                "channel": data.get("channel") or data.get("uploader"),
                "yt_track": data.get("track"),
                "yt_artist": data.get("artist"),
                "yt_album": data.get("album"),
                "year": data.get("release_year"),
                "playlist": data.get("playlist_title") or data.get("playlist"),
            })
            try:
                info_path.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001 — source signals are best-effort
        pass
    return {k: v for k, v in src.items() if v}


def _fetch_art(path: str):
    """Replace the embedded video thumbnail with real cover art when we can find a
    confident MusicBrainz match for the (cleaned) artist + album. No-op otherwise."""
    try:
        from mutagen.easyid3 import EasyID3
        audio = EasyID3(path)
        artist = (audio.get("artist") or [None])[0]
        album = (audio.get("album") or [None])[0]
        if not (artist and album):
            return
        from art import embed_cover, fetch_cover
        img = fetch_cover(artist, album)
        if img:
            embed_cover(path, img)
    except Exception:  # noqa: BLE001 — art is best-effort; keep the thumbnail on failure
        pass


def _clean_tag(path: str, *, source: dict | None = None, use_llm: bool = True):
    """Returns True/False when the LLM pass was attempted (succeeded/failed), or
    None when it wasn't — so the caller can flag the track for a later retry."""
    llm_ok = None
    try:
        from mutagen.easyid3 import EasyID3
        audio = EasyID3(path)
        title = (audio.get("title") or [None])[0]
        artist = (audio.get("artist") or [None])[0]
        album = (audio.get("album") or [None])[0]

        # 1. Deterministic pass — offline, can't mistag; also the LLM fallback.
        new_title, new_artist = clean_meta(title, artist)

        # 2. LLM correction + enrichment. Falls back to the deterministic result
        #    when unavailable or low-confidence; enrichment only fills blanks.
        enrich = {}
        if use_llm:
            from llm_cleaning import correct_track
            meta = {
                "filename": pathlib.Path(path).stem,
                "title": new_title or title,
                "artist": new_artist or artist,
                "album": album,
            }
            if source:
                for k in ("url", "channel", "yt_track", "yt_artist", "yt_album", "year", "playlist"):
                    if source.get(k):
                        meta[k] = source[k]
            result = correct_track(meta)
            llm_ok = result is not None
            if result and result["confidence"] in ("high", "medium"):
                new_title = result["title"] or new_title
                new_artist = result["artist"] or new_artist
                enrich = result

        changed = False
        if new_title and new_title != title:
            audio["title"] = new_title
            changed = True
        if new_artist and new_artist != artist:
            audio["artist"] = new_artist
            changed = True
        # Enrichment fills a blank album only — never overwrite source metadata.
        if enrich.get("album") and not (audio.get("album") or [None])[0]:
            audio["album"] = enrich["album"]
            changed = True
        if changed:
            audio.save()
    except Exception:  # noqa: BLE001
        pass
    return llm_ok
