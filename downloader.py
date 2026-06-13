import pathlib
import queue
import re
import subprocess
import sys
import threading

from models import DownloadJob, Track, db
from scan import scan_library

_job_queue: "queue.Queue[int]" = queue.Queue()
_started = False

# YouTube title cruft → stripped from the embedded title tag.
_CRUFT = re.compile(
    r"\s*[\(\[]\s*(?:official\s*)?(?:music\s*)?"
    r"(?:audio|video|lyric[s]?|lyric\s*video|visuali[sz]er|hd|hq|4k|mv|m/v|"
    r"full\s*album|official|explicit)\s*[\)\]]",
    re.I,
)


def clean_title(title: str) -> str:
    if not title:
        return title
    out = _CRUFT.sub("", title)
    out = re.sub(r"\s*-\s*topic$", "", out, flags=re.I)
    return re.sub(r"\s{2,}", " ", out).strip(" -–—")


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
    job.message = "starting"
    db.session.commit()

    music_dir = pathlib.Path(app.config["MUSIC_DIR"])
    music_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-x", "--audio-format", "mp3", "--audio-quality", "0",
        "--embed-thumbnail", "--embed-metadata", "--no-playlist", "--newline",
        "-o", str(music_dir / "%(title)s.%(ext)s"), job.url,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    final_mp3 = None
    last_pct = -1
    for line in proc.stdout:
        line = line.strip()
        m = re.search(r"\[download\]\s+([\d.]+)%", line)
        if m:
            pct = float(m.group(1))
            if int(pct) != last_pct:
                last_pct = int(pct)
                job.progress = pct
                job.message = "downloading"
                db.session.commit()
        d = re.search(r"\[(?:ExtractAudio|download)\] Destination: (.+\.mp3)", line)
        if d:
            final_mp3 = d.group(1)

    proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("yt-dlp failed (see server log)")

    if not final_mp3:
        mp3s = sorted(music_dir.glob("*.mp3"), key=lambda p: p.stat().st_mtime)
        if not mp3s:
            raise RuntimeError("no mp3 produced")
        final_mp3 = str(mp3s[-1])

    job.message = "tagging"
    db.session.commit()
    _clean_tag(final_mp3)

    job.message = "indexing"
    db.session.commit()
    scan_library(music_dir, app.config["COVER_DIR"], full=False)

    rel = str(pathlib.Path(final_mp3).relative_to(music_dir))
    track = Track.query.filter_by(file_path=rel).first()
    job.track_id = track.id if track else None
    job.progress = 100
    job.status = "done"
    job.message = (track.title if track else "done")
    db.session.commit()


def _clean_tag(path: str):
    try:
        from mutagen.easyid3 import EasyID3
        audio = EasyID3(path)
        title = (audio.get("title") or [None])[0]
        cleaned = clean_title(title) if title else None
        if cleaned and cleaned != title:
            audio["title"] = cleaned
            audio.save()
    except Exception:
        pass
