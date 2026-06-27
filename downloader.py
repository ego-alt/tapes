import json
import pathlib
import queue
import re
import subprocess
import sys
import threading
import urllib.request
from urllib.parse import parse_qs, urlparse

from cleaning import clean_meta, clean_title, reconcile_artist
from models import DownloadJob, Episode, Playlist, PlaylistTrack, Track, db
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


def _norm_url(url: str) -> str:
    """Reduce a URL to a stable key — the YouTube video id when present — so that
    youtu.be / watch?v= / extra query params all dedupe to the same track."""
    try:
        u = urlparse(url)
        if "youtu.be" in u.netloc:
            return u.path.lstrip("/") or url
        vid = parse_qs(u.query).get("v")
        if vid:
            return vid[0]
    except Exception:  # noqa: BLE001
        pass
    return url


def _find_existing(url: str):
    """Return a Track already ripped from this URL, or None. Only matches tracks
    that carry a source_url (i.e. ripped since that was recorded)."""
    track = Track.query.filter_by(source_url=url).first()  # fast exact-match path
    if track:
        return track
    norm = _norm_url(url)
    if norm == url:
        return None
    for t in Track.query.filter(Track.source_url.isnot(None)):
        if _norm_url(t.source_url) == norm:
            return t
    return None


def _discard(path: str):
    """Remove a just-downloaded file we won't keep (and its sidecar .info.json)."""
    for p in (pathlib.Path(path), pathlib.Path(path).with_suffix(".info.json")):
        try:
            p.unlink()
        except OSError:
            pass


def _link_playlist(job, track):
    """Add `track` to the job's target playlist (tape), if any, avoiding dupes."""
    if not (job.playlist_id and track):
        return
    if PlaylistTrack.query.filter_by(playlist_id=job.playlist_id, track_id=track.id).first():
        return
    pos = PlaylistTrack.query.filter_by(playlist_id=job.playlist_id).count()
    db.session.add(PlaylistTrack(playlist_id=job.playlist_id, track_id=track.id, position=pos))


def _find_dup(duration: int, fp: list):
    """A library track whose stored fingerprint matches `fp`, or None. Pre-filtered
    by duration so we only fuzzy-compare similar-length tracks."""
    import fingerprint as fpr
    q = Track.query.filter(Track.fingerprint.isnot(None))
    if duration:
        q = q.filter(Track.duration_s.between(duration - 15, duration + 15))
    for t in q:
        other = fpr.decode(t.fingerprint)
        if other and fpr.similarity(fp, other) >= fpr.DUP_THRESHOLD:
            return t
    return None


def _process(app, job_id: int):
    job = db.session.get(DownloadJob, job_id)
    if not job or job.status == "done":
        return

    if job.kind == "podcast":
        _process_podcast(app, job)
        return

    # Already have this source? Skip the download + LLM + art entirely; just link
    # it (and add it to the target tape if one was requested).
    existing = _find_existing(job.url)
    if existing is not None:
        _link_playlist(job, existing)
        job.track_id = existing.id
        job.progress = 100
        job.status = "done"
        job.message = f"already in library: {existing.title}"
        db.session.commit()
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

    # Content dedup: a different URL but the same recording? Fingerprint the audio
    # and, if we already have it, discard this copy instead of re-tagging it.
    fp = None
    if app.config.get("FINGERPRINT_DEDUP", True):
        import fingerprint as fpr
        computed = fpr.compute(final_mp3)
        if computed:
            duration, fp = computed
            dup = _find_dup(duration, fp)
            if dup:
                _discard(final_mp3)
                _link_playlist(job, dup)
                job.track_id = dup.id
                job.progress = 100
                job.status = "done"
                job.message = f"duplicate of: {dup.title}"
                db.session.commit()
                return

    source = _read_source_meta(final_mp3, job.url)
    # A playlist rip downloads each video with --no-playlist, so the per-video
    # info.json carries no playlist context. Supply the tape name we captured at
    # submit time as the playlist signal so the LLM can enrich the album from it.
    if job.playlist_id and not source.get("playlist"):
        pl = db.session.get(Playlist, job.playlist_id)
        if pl and pl.name:
            source["playlist"] = pl.name
    llm_ok = _clean_tag(final_mp3, source=source, use_llm=app.config.get("LLM_CLEANING", True))
    if app.config.get("ART_LOOKUP", True):
        _fetch_art(final_mp3)
    scan_library(music_dir, app.config["COVER_DIR"], full=False)

    rel = str(pathlib.Path(final_mp3).relative_to(music_dir))
    track = Track.query.filter_by(file_path=rel).first()
    if track:
        track.source_url = source.get("url") or job.url
        if fp:
            import fingerprint as fpr
            track.fingerprint = fpr.encode(fp)
        if llm_ok is not None:
            track.needs_llm = not llm_ok  # flag misses for `retag --llm --pending`
    job.track_id = track.id if track else None
    job.progress = 100
    job.status = "done"
    job.message = (track.title if track else "done")
    _link_playlist(job, track)
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

        # Snap the artist onto an existing library spelling (a casing/punctuation
        # variant) so the same act doesn't split into two shelves. This new rip
        # isn't in the DB yet, so the candidates are every *other* track's artist.
        if new_artist:
            from models import distinct_artists
            new_artist = reconcile_artist(new_artist, distinct_artists())

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


# ---------- podcasts (download-on-play) ----------

def _process_podcast(app, job):
    """Fetch one episode's audio on demand: RSS enclosure over HTTP, or a YouTube
    video via yt-dlp. Metadata-only passes (LLM/art/fingerprint/scan) are skipped —
    episodes live outside the music catalog."""
    import podcasts

    ep = db.session.get(Episode, job.episode_id)
    if ep is None:
        job.status = "error"
        job.message = "episode gone"
        db.session.commit()
        return

    music_dir = pathlib.Path(app.config["MUSIC_DIR"])
    podcast_dir = pathlib.Path(app.config["PODCAST_DIR"])

    # Already downloaded (e.g. a second play queued it again)? Just finish.
    if ep.status == "ready" and ep.file_path and (music_dir / ep.file_path).exists():
        job.progress = 100
        job.status = "done"
        job.message = ep.title
        db.session.commit()
        return

    ep.status = "downloading"
    job.status = "running"
    job.progress = 0
    job.message = ep.title
    db.session.commit()

    target = podcasts.episode_target(podcast_dir, ep)
    if ep.source_type == "youtube":
        final = _download_youtube_audio(ep.source_url, target, job)
    else:
        final = _download_enclosure(ep.source_url, target, job)

    duration = None
    try:
        from mutagen import File as MutagenFile
        mf = MutagenFile(str(final))
        if mf is not None and mf.info is not None:
            duration = getattr(mf.info, "length", None)
    except Exception:  # noqa: BLE001
        pass

    ep.file_path = str(final.relative_to(music_dir))
    if duration:
        ep.duration_s = duration
    ep.status = "ready"
    job.progress = 100
    job.status = "done"
    job.message = ep.title
    db.session.commit()


def _download_enclosure(url: str, target: pathlib.Path, job) -> pathlib.Path:
    """Stream an RSS enclosure to disk, updating job.progress from Content-Length."""
    req = urllib.request.Request(url, headers={"User-Agent": "tapes-podcast/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310 — user-supplied feed
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        last = -1
        tmp = target.with_suffix(target.suffix + ".part")
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 // total
                    if pct != last:
                        last = pct
                        job.progress = pct
                        db.session.commit()
    tmp.replace(target)
    return target


def _download_youtube_audio(url: str, target: pathlib.Path, job) -> pathlib.Path:
    """Extract a YouTube video's audio to mp3 at `target` (no thumbnail/metadata
    passes — episodes don't get the music rip treatment)."""
    out_tmpl = str(target.with_suffix("")) + ".%(ext)s"
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--no-playlist", "--newline", "-o", out_tmpl, url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    last = -1
    for line in proc.stdout:
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            pct = int(float(m.group(1)))
            if pct != last:
                last = pct
                job.progress = pct
                db.session.commit()
    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("yt-dlp failed (see server log)")
    if not target.exists():  # paranoia: find the produced file by stem
        cands = sorted(target.parent.glob(target.stem + ".*"))
        if not cands:
            raise RuntimeError("no audio produced")
        return cands[-1]
    return target
