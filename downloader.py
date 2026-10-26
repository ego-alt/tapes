import json
import logging
import os
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

import youtube
from cleaning import clean_meta, clean_title, reconcile_artist
from models import DownloadJob, Episode, Playlist, PlaylistTrack, Track, db
from scan import scan_library

log = logging.getLogger("tapes.downloader")

_job_queue: "queue.Queue[int]" = queue.Queue()
_started = False


def expand_playlist(url: str):
    """Return (video_url_list, playlist_title, source) for a playlist, or
    ([url], None, None) otherwise. `source` is {"id", "title", "owner"}, kept
    with each job so the rip can tell whether the playlist is an album."""
    try:
        path = urlparse(url).path.rstrip("/")
        if path != "/playlist" and not path.startswith("/browse/MPREb"):   # MPREb: a YouTube Music album
            return [url], None, None
    except Exception:
        return [url], None, None

    data = youtube.flat_playlist_json(url, end=500, timeout=60)
    if data is None or data.get("_type") != "playlist":
        return [url], None, None

    title = data.get("title") or "Playlist"
    urls = [
        f"https://www.youtube.com/watch?v={e['id']}"
        for e in (data.get("entries") or [])
        if e and e.get("id")
    ]
    if not urls:
        return [url], title, None
    source = {"id": data.get("id") or "", "title": data.get("title") or "",
              "owner": data.get("uploader") or data.get("channel") or ""}
    return urls, title, source


def enqueue(job_id: int):
    _job_queue.put(job_id)


def recover_interrupted_jobs():
    """Put jobs a restart cut off ("running" with no one running them) back in
    the queue. Under gunicorn this runs once in the master, before any worker
    starts; in a worker it could reset a job its sibling is busy with."""
    n = DownloadJob.query.filter_by(status="running").update({"status": "queued"})
    db.session.commit()
    return n


def start_worker(app):
    global _started
    if _started:
        return
    _started = True
    with app.app_context():
        if not os.environ.get("TAPES_JOBS_RECOVERED"):   # set by gunicorn's on_starting
            recover_interrupted_jobs()
        # Each worker process has its own queue; a job is run by whichever
        # worker claims it first (see _claim), so listing it in both is safe.
        for (job_id,) in db.session.query(DownloadJob.id).filter_by(status="queued").all():
            _job_queue.put(job_id)
    threading.Thread(target=_loop, args=(app,), daemon=True).start()
    if app.config.get("AUDIO_ANALYSIS", True):
        # Measure loudness + gapless info for the rest of the library, slowly.
        import audio_analysis
        threading.Thread(target=audio_analysis.backfill, args=(app,), daemon=True).start()


class RipError(RuntimeError):
    """A rip failure whose message is already fit to show the user."""


# yt-dlp error text -> what to tell the user. First match wins.
_RIP_ERRORS = [
    (("private video",), "This video is private."),
    (("sign in to confirm your age", "age-restricted", "inappropriate for some users"),
     "This video is age-restricted, so it can't be ripped."),
    (("available in your country", "geo restrict", "geo-restrict"),
     "This video isn't available in this region."),
    (("unsupported url",), "That site or link isn't supported."),
    (("video unavailable", "video is unavailable", "has been removed", "no longer available", "does not exist"),
     "This video is no longer available."),
    # The site answered, so before the connection rule ("unable to download
    # webpage" covers both).
    (("http error 404", "http error 410"), "That page doesn't exist. Check the link."),
    (("http error 401", "http error 403"), "That site wouldn't let the page be read."),
    (("unable to download webpage", "name or service not known", "timed out",
      "temporary failure in name resolution", "connection"),
     "Couldn't reach that site. Check the connection and try again."),
]
_RIP_GENERIC = "Couldn't rip that link. It may be private, region-locked or not a video."


def friendly_rip_error(text: str) -> str:
    """Map yt-dlp's error output (or an exception) to a short, human message."""
    low = (text or "").lower()
    if "no module named yt_dlp" in low or "no module named 'yt_dlp'" in low:
        return "Ripping isn't set up on this server (yt-dlp is missing)."
    for needles, message in _RIP_ERRORS:
        if any(n in low for n in needles):
            return message
    return _RIP_GENERIC


def _finish(job, outcome: str, message: str):
    job.status = "error" if outcome == "error" else "done"
    job.outcome = outcome
    job.message = message[:300]
    job.finished_at = datetime.now()
    if outcome != "error":
        job.progress = 100


def _loop(app):
    while True:
        job_id = _job_queue.get()
        with app.app_context():
            try:
                _process(app, job_id)
            except Exception as e:  # noqa: BLE001
                log.warning("job %s failed: %s", job_id, e)
                db.session.rollback()
                job = db.session.get(DownloadJob, job_id)
                if job:
                    msg = str(e) if isinstance(e, RipError) else friendly_rip_error(str(e))
                    _finish(job, "error", msg)
                    # A failed episode download goes back to "not downloaded" so
                    # tapping it retries, instead of showing "downloading…" forever.
                    ep = db.session.get(Episode, job.episode_id) if job.episode_id else None
                    if ep is not None and ep.status == "downloading":
                        ep.status = "new"
                    db.session.commit()
        _job_queue.task_done()


def _norm_url(url: str) -> str:
    """Reduce a URL to a stable key — the YouTube video id when present — so that
    youtu.be / watch?v= / extra query params all dedupe to the same track."""
    return youtube.video_id(url) or url


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


# Characters that don't belong in a file or folder name on any common system.
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _safe_part(text: str, limit: int = 100) -> str:
    """One path component from a tag value: unsafe characters out, no leading
    dots (hidden files) or trailing dots/spaces (Windows/SMB), bounded length."""
    part = _UNSAFE.sub("_", text or "").strip().lstrip(".").rstrip(". ")
    return part[:limit].rstrip(". ") or "_"


def _library_path(music_dir: pathlib.Path, mp3: str) -> pathlib.Path:
    """Where a finished rip lives: Artist/Album/NN Title.mp3 (or Artist/Title.mp3
    without an album), from its cleaned tags."""
    title = artist = album = None
    track_no = None
    try:
        from mutagen.easyid3 import EasyID3
        tags = EasyID3(mp3)
        title = (tags.get("title") or [None])[0]
        artist = (tags.get("artist") or [None])[0]
        album = (tags.get("album") or [None])[0]
        m = re.match(r"\d+", (tags.get("tracknumber") or [""])[0])
        track_no = int(m.group()) if m else None
    except Exception:  # noqa: BLE001 — untagged: fall back to the file name
        pass
    name = _safe_part(title or pathlib.Path(mp3).stem)
    if album and track_no:
        name = f"{track_no:02d} {name}"
    folder = music_dir / _safe_part(artist or "Unknown artist")
    if album:
        folder = folder / _safe_part(album)
    return folder / f"{name}.mp3"


def _move_into_library(src: str, dest: pathlib.Path) -> pathlib.Path:
    """Move a rip to `dest`, adding " (2)", " (3)"… if that name is taken. The
    name is claimed with an exclusive create, so two rips finishing together
    can't land on the same file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        cand = dest if n == 1 else dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
        try:
            os.close(os.open(cand, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            n += 1
            continue
        os.replace(src, cand)
        return cand


def _claim(job_id: int) -> bool:
    """Mark a queued job running, atomically: with more than one worker process
    each holding its own queue, only the one that wins this update runs it."""
    claimed = (DownloadJob.query.filter_by(id=job_id, status="queued")
               .update({"status": "running", "progress": 0, "message": ""}))
    db.session.commit()
    return claimed == 1


def _process(app, job_id: int):
    if not _claim(job_id):
        return                                       # done, or another worker has it
    job = db.session.get(DownloadJob, job_id)

    if job.kind == "podcast":
        _process_podcast(app, job)
        return

    # Already have this source? Skip the download + LLM + art entirely; just link
    # it (and add it to the target tape if one was requested).
    existing = _find_existing(job.url)
    if existing is not None:
        _link_playlist(job, existing)
        job.track_id = existing.id
        _finish(job, "exists", existing.title)
        db.session.commit()
        return

    music_dir = pathlib.Path(app.config["MUSIC_DIR"])
    # Each rip works in its own folder (a dot-dir, so scans skip it) and only
    # moves into the library once tagged.
    work = music_dir / ".incoming" / str(job.id)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        _rip(app, job, music_dir, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _rip(app, job, music_dir: pathlib.Path, work: pathlib.Path):
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-thumbnail", "--embed-metadata", "--write-info-json",
        "--no-playlist", "--newline",
        "-o", str(work / "%(title)s.%(ext)s"), job.url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    final_mp3 = None
    title = None
    last_pct = -1
    errors, tail = [], []
    for line in proc.stdout:
        line = line.strip()
        if line.startswith("ERROR"):
            errors.append(line)
        tail = (tail + [line])[-5:]   # for failures that never print ERROR
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
        detail = " | ".join(errors or tail) or "no output"
        log.warning("yt-dlp failed for %s: %s", job.url, detail)
        raise RipError(friendly_rip_error(detail))

    if not final_mp3:
        mp3s = list(work.glob("*.mp3"))   # only this job's folder
        if not mp3s:
            raise RipError(_RIP_GENERIC)
        final_mp3 = str(mp3s[0])

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
                _finish(job, "duplicate", dup.title)
                db.session.commit()
                return

    source = _read_source_meta(final_mp3, job.url)
    # A playlist rip downloads each video with --no-playlist, so the per-video
    # info.json carries no playlist context. Supply what we captured at submit
    # time: the playlist (title, owner) and this video's place in it.
    if job.source_playlist:
        try:
            source["source_playlist"] = json.loads(job.source_playlist)
        except ValueError:
            pass
        if job.playlist_index:
            source["playlist_index"] = job.playlist_index
    if job.playlist_id and not source.get("playlist"):
        pl = db.session.get(Playlist, job.playlist_id)
        if pl and pl.name:
            source["playlist"] = pl.name
    llm_ok = _clean_tag(final_mp3, source=source, use_llm=app.config.get("LLM_CLEANING", True),
                        verify_album=app.config.get("ART_LOOKUP", True))
    if app.config.get("ART_LOOKUP", True):
        _fetch_art(final_mp3)
    final_mp3 = str(_move_into_library(final_mp3, _library_path(music_dir, final_mp3)))
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
        if app.config.get("AUDIO_ANALYSIS", True):
            import audio_analysis
            audio_analysis.analyze_new_track(track, music_dir)   # loudness + gapless
    job.track_id = track.id if track else None
    _finish(job, "added", track.title if track else "Added")
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


def _clean_tag(path: str, *, source: dict | None = None, use_llm: bool = True, verify_album: bool = False):
    """Returns True/False when the LLM pass was attempted (succeeded/failed), or
    None when it wasn't — so the caller can flag the track for a later retry."""
    llm_ok = None
    source = source or {}
    try:
        from mutagen.easyid3 import EasyID3

        from albums import album_from_playlist
        from models import distinct_artists
        audio = EasyID3(path)
        title = (audio.get("title") or [None])[0]
        artist = (audio.get("artist") or [None])[0]
        album = (audio.get("album") or [None])[0]       # YouTube's own, for Topic uploads
        library_artists = distinct_artists()
        ctx = source.get("source_playlist")

        # 1. Deterministic pass — offline, can't mistag; the LLM's starting point
        #    and its fallback. Library artists tell "Song - Artist" from "Artist - Song".
        new_title, new_artist = clean_meta(title, artist, library_artists)
        playlist_album = None if album else album_from_playlist(ctx, new_artist or artist or "")

        # 2. LLM correction, and the album decision when the playlist could be one.
        #    Falls back to the deterministic result when unavailable or unsure.
        llm = None
        if use_llm:
            from llm_cleaning import correct_track
            meta = {"filename": pathlib.Path(path).stem, "title": new_title or title, "artist": new_artist or artist, "album": album}
            for k in ("url", "channel", "yt_track", "yt_artist", "yt_album", "year", "playlist", "playlist_index"):
                if source.get(k):
                    meta[k] = source[k]
            if ctx:
                meta.update(playlist_id=ctx.get("id"), playlist_owner=ctx.get("owner"), playlist_album=playlist_album)
            result = correct_track(meta)
            llm_ok = result is not None
            if result and result["confidence"] in ("high", "medium"):
                new_title = result["title"] or new_title
                new_artist = result["artist"] or new_artist
                llm = result

        # Snap the artist onto an existing library spelling (a casing/punctuation
        # variant) so the same act doesn't split into two shelves. This new rip
        # isn't in the DB yet, so the candidates are every *other* track's artist.
        if new_artist:
            new_artist = reconcile_artist(new_artist, library_artists)

        # 3. Album, track number, year.
        tags = _album_tags(album, new_artist or artist, source, llm, verify_album)

        changed = False
        for key, value in (("title", new_title), ("artist", new_artist), *tags.items()):
            if value and (audio.get(key) or [None])[0] != value:
                audio[key] = value
                changed = True
        if changed:
            audio.save()
    except Exception:  # noqa: BLE001
        pass
    return llm_ok


def _album_tags(album: str | None, artist: str | None, source: dict, llm: dict | None, verify: bool) -> dict:
    """Album, track number and year for a rip.

    The album comes from, in order: YouTube's own (Topic uploads); the LLM,
    which weighs the playlist's title, owner and position; and, when the LLM
    is unavailable, albums.album_from_playlist (optionally confirmed against
    MusicBrainz). An album spelled differently from one already in the library
    takes the library's spelling, so it doesn't split in two."""
    from albums import album_from_playlist, is_album_order, reconcile_album
    from models import Track

    ctx = source.get("source_playlist")
    track_no = None
    if not album and llm is not None:
        album, track_no = llm.get("album"), llm.get("track_no")
    elif not album:
        confirm = None
        if verify:
            from art import confirm_album as confirm
        album = album_from_playlist(ctx, artist or "", verify=confirm)
    tags = {}
    if album:
        existing = [r[0] for r in db.session.query(Track.album).filter(Track.artist == artist).distinct()]
        tags["album"] = reconcile_album(album, existing)
        if not track_no and source.get("playlist_index") and is_album_order(ctx, artist or "", album):
            track_no = source["playlist_index"]
        if track_no:
            tags["tracknumber"] = str(track_no)
    if source.get("year"):
        tags["date"] = str(source["year"])
    return tags


# ---------- podcasts (download-on-play) ----------

def _process_podcast(app, job):
    """Fetch one episode's audio on demand: RSS enclosure over HTTP, or a YouTube
    video via yt-dlp. Metadata-only passes (LLM/art/fingerprint/scan) are skipped —
    episodes live outside the music catalog."""
    import podcasts

    ep = db.session.get(Episode, job.episode_id)
    if ep is None:
        _finish(job, "error", "That episode is no longer in your library.")
        db.session.commit()
        return

    music_dir = pathlib.Path(app.config["MUSIC_DIR"])
    podcast_dir = pathlib.Path(app.config["PODCAST_DIR"])

    # Already downloaded (e.g. a second play queued it again)? Just finish.
    if ep.status == "ready" and ep.file_path and (music_dir / ep.file_path).exists():
        _finish(job, "added", ep.title)
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
    _finish(job, "added", ep.title)
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
        raise RuntimeError("yt-dlp failed")
    if not target.exists():  # paranoia: find the produced file by stem
        cands = sorted(target.parent.glob(target.stem + ".*"))
        if not cands:
            raise RipError("Couldn't download that episode.")
        return cands[-1]
    return target
