"""Test fixtures: an app on a temp DB + temp MUSIC_DIR, in standalone mode
(a local user is attached automatically), plus helpers to add tracks."""
import pathlib

import pytest
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK

from app import create_app
from models import Track, db


@pytest.fixture
def app(tmp_path, monkeypatch):
    for flag in ("LLM_CLEANING", "ART_LOOKUP", "FINGERPRINT_DEDUP"):
        monkeypatch.setenv(flag, "0")
    monkeypatch.delenv("AUTH_PROXY_HEADER", raising=False)
    music = tmp_path / "music"
    music.mkdir()
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
        "MUSIC_DIR": str(music),
        "COVER_DIR": str(tmp_path / "covers"),
        "PODCAST_DIR": str(music / "_podcasts"),
    })
    with app.app_context():
        yield app
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def add_track(app):
    """Create a Track row backed by a small file carrying a real ID3 tag, so
    tag-writing code paths work without needing ffmpeg."""
    counter = {"n": 0}

    def _add(title="Song", artist="Artist", album=None, track_no=None, **extra):
        counter["n"] += 1
        rel = f"{counter['n']:03d}.mp3"
        path = pathlib.Path(app.config["MUSIC_DIR"]) / rel
        path.write_bytes(b"")
        tags = ID3()
        tags.add(TIT2(encoding=3, text=title))
        if artist:
            tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.add(TALB(encoding=3, text=album))
        if track_no:
            tags.add(TRCK(encoding=3, text=str(track_no)))
        tags.save(path)
        t = Track(file_path=rel, title=title, artist=artist, album=album,
                  track_no=track_no, duration_s=extra.pop("duration_s", 180.0), **extra)
        db.session.add(t)
        db.session.commit()
        return t

    return _add
