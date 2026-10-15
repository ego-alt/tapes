"""Library-side metadata fixes the page can trigger: re-run the rip cleanup on
existing songs ("tidy"), and edit a whole album (name, artist, cover). Each one
writes the file tags and keeps the DB row (and cover thumbnail) in step."""
import os
import pathlib

from models import Track, db
from scan import _write_cover, partial_hash


def _path(app, track) -> pathlib.Path:
    return pathlib.Path(app.config["MUSIC_DIR"]) / track.file_path


def refresh_from_tags(app, track):
    """Copy title/artist/album from the file's tags back onto the row."""
    from mutagen.easyid3 import EasyID3
    try:
        tags = EasyID3(str(_path(app, track)))
    except Exception:  # noqa: BLE001 — leave the row as it was
        return
    first = lambda k: (tags.get(k) or [None])[0]  # noqa: E731
    track.title = first("title") or track.title
    track.artist = first("artist")
    track.album = first("album")


def set_cover(app, track, jpg_bytes: bytes) -> bool:
    """Embed a cover in the file and refresh the row's thumbnail. The file's
    content hash changes with its tags, so the thumbnail is re-keyed."""
    from art import embed_cover
    path = _path(app, track)
    embed_cover(str(path), jpg_bytes)
    st = path.stat()
    track.file_hash = partial_hash(str(path), st.st_size)
    track.size_bytes, track.mtime = st.st_size, st.st_mtime
    track.has_cover = _write_cover(jpg_bytes, path, pathlib.Path(app.config["COVER_DIR"]), track.file_hash)
    return track.has_cover


def ai_available(app) -> bool:
    return bool(app.config.get("LLM_CLEANING", True) and os.environ.get("ANTHROPIC_API_KEY"))


def tidy_tracks(app, tracks) -> dict:
    """Run the same cleanup a rip gets: deterministic title/artist cleanup, the
    Claude pass when a key is set, and a MusicBrainz cover when one is missing."""
    from downloader import _clean_tag
    use_llm = ai_available(app)
    changed = []
    for t in tracks:
        before = (t.title, t.artist, t.album, bool(t.has_cover))
        source = {"url": t.source_url} if t.source_url else None
        ok = _clean_tag(str(_path(app, t)), source=source, use_llm=use_llm)
        refresh_from_tags(app, t)
        if use_llm and ok is not None:
            t.needs_llm = not ok
        if app.config.get("ART_LOOKUP", True) and not t.has_cover and t.artist and t.album:
            try:
                from art import fetch_cover
                img = fetch_cover(t.artist, t.album)
                if img:
                    set_cover(app, t, img)
            except Exception:  # noqa: BLE001 — art is best-effort
                pass
        if (t.title, t.artist, t.album, bool(t.has_cover)) != before:
            changed.append(t.id)
    db.session.commit()
    return {"tidied": len(tracks), "changed": changed, "ai": use_llm}


def edit_album(app, album: str, *, name: str | None, artist: str | None) -> list:
    from mutagen.easyid3 import EasyID3
    tracks = Track.query.filter(Track.album == album).all()
    for t in tracks:
        if name:
            t.album = name
        if artist:
            t.artist = artist
        try:
            tags = EasyID3(str(_path(app, t)))
            if name:
                tags["album"] = name
            if artist:
                tags["artist"] = artist
            tags.save()
        except Exception:  # noqa: BLE001 — DB stays authoritative
            pass
    db.session.commit()
    return tracks
