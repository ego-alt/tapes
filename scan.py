"""Library scan: walk MUSIC_DIR, read tags with mutagen, cache cover
thumbnails, upsert into `tracks`. Incremental by (path, mtime, size).

`scan_library()` is the reusable core (also called by the downloader worker);
`register_cli()` exposes it as `flask scan`."""

import hashlib
import os
import pathlib
from io import BytesIO

import click

from models import Track, db

AUDIO_EXTS = {".mp3"}
COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png")


def partial_hash(path: str, size: int) -> str:
    """Cheap stable identity: size + head/tail 64 KB. Survives renames/moves."""
    h = hashlib.sha1()
    h.update(str(size).encode())
    with open(path, "rb") as f:
        h.update(f.read(65536))
        if size > 131072:
            f.seek(-65536, os.SEEK_END)
            h.update(f.read(65536))
    return h.hexdigest()


def _read_tags(path: str) -> dict:
    from mutagen import File as MutagenFile

    out = {
        "title": None, "artist": None, "album": None,
        "track_no": None, "duration_s": None, "bitrate": None, "cover": None,
    }
    try:
        audio = MutagenFile(path)
    except Exception:
        return out
    if audio is None:
        return out
    if audio.info is not None:
        out["duration_s"] = getattr(audio.info, "length", None)
        out["bitrate"] = getattr(audio.info, "bitrate", None)

    tags = audio.tags
    if not tags:
        return out

    def first(key):
        v = tags.get(key)
        if v is None:
            return None
        try:
            return str(v.text[0]) if hasattr(v, "text") else str(v[0])
        except Exception:
            return None

    out["title"] = first("TIT2")
    out["artist"] = first("TPE1")
    out["album"] = first("TALB")
    trck = first("TRCK")
    if trck:
        try:
            out["track_no"] = int(trck.split("/")[0])
        except (ValueError, IndexError):
            pass
    for key in tags.keys():
        if key.startswith("APIC"):
            try:
                out["cover"] = tags[key].data
            except Exception:
                pass
            break
    return out


def _write_cover(raw, abspath: pathlib.Path, cover_dir: pathlib.Path, fhash: str) -> bool:
    from PIL import Image

    if not raw:
        for cand in COVER_NAMES:
            p = abspath.parent / cand
            if p.exists():
                raw = p.read_bytes()
                break
    if not raw:
        return False
    try:
        img = Image.open(BytesIO(raw)).convert("RGB")
        img.thumbnail((500, 500))
        img.save(cover_dir / f"{fhash}.jpg", "JPEG", quality=85)
        return True
    except Exception:
        return False


def scan_library(music_dir, cover_dir, *, full=False, prune=False) -> dict:
    """Walk music_dir, upsert tracks, cache covers. Returns a counts dict.
    Must run inside an app context (uses db.session)."""
    music_dir = pathlib.Path(music_dir)
    cover_dir = pathlib.Path(cover_dir)
    cover_dir.mkdir(parents=True, exist_ok=True)
    if not music_dir.is_dir():
        return {"error": f"MUSIC_DIR not found: {music_dir}"}

    existing = {t.file_path: t for t in Track.query.all()}
    seen_rel = set()
    added = updated = skipped = pruned = 0

    for root, _, files in os.walk(music_dir):
        for name in files:
            if pathlib.Path(name).suffix.lower() not in AUDIO_EXTS:
                continue
            abspath = pathlib.Path(root) / name
            rel = str(abspath.relative_to(music_dir))
            seen_rel.add(rel)
            st = abspath.stat()

            track = existing.get(rel)
            if track and not full and track.mtime == st.st_mtime \
                    and track.size_bytes == st.st_size:
                skipped += 1
                continue

            tags = _read_tags(str(abspath))
            fhash = partial_hash(str(abspath), st.st_size)
            has_cover = _write_cover(tags["cover"], abspath, cover_dir, fhash)

            if track is None:
                track = Track(file_path=rel)
                db.session.add(track)
                added += 1
            else:
                updated += 1

            track.file_hash = fhash
            track.title = tags["title"] or pathlib.Path(name).stem
            track.artist = tags["artist"]
            track.album = tags["album"]
            track.track_no = tags["track_no"]
            track.duration_s = tags["duration_s"]
            track.bitrate = tags["bitrate"]
            track.size_bytes = st.st_size
            track.mtime = st.st_mtime
            track.has_cover = has_cover

    if prune:
        for rel, track in existing.items():
            if rel not in seen_rel:
                db.session.delete(track)
                pruned += 1

    db.session.commit()
    return {"added": added, "updated": updated, "skipped": skipped, "pruned": pruned}


def register_cli(app):
    @app.cli.command("scan")
    @click.option("--full", is_flag=True, help="Re-read every file, ignore the mtime cache.")
    @click.option("--prune", is_flag=True, help="Drop DB rows whose files are gone.")
    def scan(full, prune):
        """Index MUSIC_DIR into the catalog."""
        r = scan_library(app.config["MUSIC_DIR"], app.config["COVER_DIR"], full=full, prune=prune)
        if "error" in r:
            click.echo(r["error"])
            return
        click.echo(
            f"scan: +{r['added']} added, ~{r['updated']} updated, "
            f"{r['skipped']} unchanged" + (f", -{r['pruned']} pruned" if prune else "")
        )
