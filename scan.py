import hashlib
import os
import pathlib
from io import BytesIO

import click

from models import Track, db

AUDIO_EXTS = {".mp3"}
COVER_NAMES = ("cover.jpg", "cover.png", "folder.jpg", "folder.png")


def partial_hash(path: str, size: int) -> str:
    # Size + head/tail 64 KB: cheap identity that survives renames.
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

    @app.cli.command("retag")
    @click.option("--write", is_flag=True, help="Apply changes (default: dry run / preview).")
    @click.option("--llm", is_flag=True,
                  help="Use Claude (Batches API) to correct + enrich tags, not just deterministic cleanup.")
    def retag(write, llm):
        """Clean title/artist tags in place (and, with --llm, fill a blank album), then rescan."""
        from mutagen.easyid3 import EasyID3

        from cleaning import clean_meta

        music_dir = pathlib.Path(app.config["MUSIC_DIR"])
        paths = sorted(music_dir.rglob("*.mp3"))

        # Read tags + run the deterministic pass for every file up front.
        # entries: path -> {audio, title, artist, album, dt_title, dt_artist}
        entries = []
        for p in paths:
            try:
                audio = EasyID3(str(p))
            except Exception:
                continue
            title = (audio.get("title") or [None])[0]
            artist = (audio.get("artist") or [None])[0]
            album = (audio.get("album") or [None])[0]
            dt_title, dt_artist = clean_meta(title, artist)
            entries.append({
                "path": p, "audio": audio, "title": title, "artist": artist,
                "album": album, "dt_title": dt_title, "dt_artist": dt_artist,
            })

        # With --llm, send the (deterministically-cleaned) tags through Claude in one batch.
        corrections = {}
        if llm:
            from llm_cleaning import correct_tracks_batch
            items = [
                (str(i), {
                    "filename": e["path"].stem,
                    "title": e["dt_title"] or e["title"],
                    "artist": e["dt_artist"] or e["artist"],
                    "album": e["album"],
                })
                for i, e in enumerate(entries)
            ]
            click.echo(f"submitting {len(items)} track(s) to Claude (Batches API)…")
            corrections = correct_tracks_batch(
                items,
                on_status=lambda b: click.echo(f"  batch {b.processing_status}…"),
            )
            if not corrections:
                click.echo("! no LLM results (is ANTHROPIC_API_KEY set?) — falling back to deterministic")

        changed = 0
        for i, e in enumerate(entries):
            res = corrections.get(str(i))
            confident = bool(res) and res["confidence"] in ("high", "medium")
            new_title = (res["title"] if confident else None) or e["dt_title"]
            new_artist = (res["artist"] if confident else None) or e["dt_artist"]

            diffs, writes = [], []
            if new_title and new_title != e["title"]:
                diffs.append(("title", e["title"], new_title))
                writes.append(("title", new_title))
            if new_artist and new_artist != e["artist"]:
                diffs.append(("artist", e["artist"], new_artist))
                writes.append(("artist", new_artist))
            # Enrichment fills a blank album only — never overwrite an existing tag.
            if confident and res.get("album") and not (e["audio"].get("album") or [None])[0]:
                diffs.append(("album", None, res["album"]))
                writes.append(("album", res["album"]))
            if not diffs:
                continue

            changed += 1
            click.echo(e["path"].name)
            for field, old, new in diffs:
                click.echo(f"    {field}: {old!r} -> {new!r}")
            if write:
                for tag, val in writes:
                    e["audio"][tag] = val
                try:
                    e["audio"].save()
                except Exception as ex:  # noqa: BLE001
                    click.echo(f"    ! save failed: {ex}")

        click.echo(
            f"\n{changed} file(s) "
            + ("updated" if write else "would change — re-run with --write to apply")
        )
        if write and changed:
            r = scan_library(app.config["MUSIC_DIR"], app.config["COVER_DIR"], full=True)
            click.echo(f"rescan: +{r.get('added', 0)} added, ~{r.get('updated', 0)} updated")

    @app.cli.command("art")
    @click.option("--write", is_flag=True, help="Embed the fetched art (default: dry run / preview).")
    @click.option("--all", "do_all", is_flag=True,
                  help="Also re-fetch tracks that already have a cover (upgrade thumbnails).")
    def art(write, do_all):
        """Fetch real cover art from MusicBrainz for tracks with a known artist + album.

        Throttled to ~1 lookup/sec (MusicBrainz etiquette), so a large library
        takes roughly one second per track. Without --all, only covers tracks
        that currently have no art.
        """
        from art import embed_cover, fetch_cover

        music_dir = pathlib.Path(app.config["MUSIC_DIR"])
        tracks = Track.query.order_by(Track.artist, Track.album).all()
        found = 0
        for t in tracks:
            if not (t.artist and t.album):
                continue
            if t.has_cover and not do_all:
                continue
            img = fetch_cover(t.artist, t.album)
            click.echo(f"[{'FOUND' if img else '  -  '}] {t.artist} — {t.album} :: {t.title}")
            if not img:
                continue
            found += 1
            if write:
                try:
                    embed_cover(str(music_dir / t.file_path), img)
                except Exception as e:  # noqa: BLE001
                    click.echo(f"    ! embed failed: {e}")
        click.echo(
            f"\n{found} cover(s) "
            + ("embedded" if write else "found — re-run with --write to apply")
        )
        if write and found:
            r = scan_library(app.config["MUSIC_DIR"], app.config["COVER_DIR"], full=True)
            click.echo(f"rescan: ~{r.get('updated', 0)} updated")
