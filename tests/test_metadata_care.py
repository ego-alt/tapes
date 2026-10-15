"""Audit 1.4, 1.5, 2.8: a Needs-tidying shelf, a real Singles shelf, album
editing, and a tidy action that reuses the rip cleanup."""
import io
import pathlib

from mutagen.easyid3 import EasyID3
from PIL import Image

from models import Track, db


def _shelf(client):
    return {s["key"]: s for s in client.get("/api/playlists").get_json()}


def test_needs_tidying_shelf_lists_reasons(client, add_track):
    add_track(title="Fine", artist="A", album="X", has_cover=True)
    add_track(title="No artist", artist=None, album="X", has_cover=True)
    add_track(title="No cover", artist="A", album="X", has_cover=False)
    add_track(title="AI missed", artist="A", album="X", has_cover=True, needs_llm=True)
    shelf = _shelf(client)
    assert shelf["tidy"]["count"] == 3 and shelf["tidy"]["name"] == "Needs tidying"
    rows = {r["title"]: r["issues"] for r in client.get("/api/playlists/tidy/tracks").get_json()}
    assert rows == {"No artist": ["no artist"], "No cover": ["no cover"], "AI missed": ["AI pass missed"]}


def test_tidy_shelf_hidden_when_nothing_to_tidy(client, add_track):
    add_track(title="Fine", artist="A", album="X", has_cover=True)
    assert "tidy" not in _shelf(client)


def test_singles_need_an_artist(client, add_track):
    add_track(title="Real single", artist="A", album=None, has_cover=True)
    add_track(title="Mystery file", artist=None, album=None, has_cover=True)
    titles = [r["title"] for r in client.get("/api/playlists/singles/tracks").get_json()]
    assert titles == ["Real single"]
    assert _shelf(client)["singles"]["count"] == 1


def test_album_rename_and_artist(app, client, add_track):
    a = add_track(title="One", artist="A", album="Old Name", track_no=1)
    b = add_track(title="Two", artist="B", album="Old Name", track_no=2)
    r = client.patch("/api/albums", json={"album": "Old Name", "name": "New Name", "artist": "The Band"})
    assert r.status_code == 200 and r.get_json() == {"album": "New Name", "updated": 2}
    for t in (a, b):
        row = db.session.get(Track, t.id)
        assert (row.album, row.artist) == ("New Name", "The Band")
        tags = EasyID3(str(pathlib.Path(app.config["MUSIC_DIR"]) / t.file_path))
        assert tags["album"] == ["New Name"] and tags["artist"] == ["The Band"]
        assert row.track_no in (1, 2)


def test_album_cover_upload(app, client, add_track):
    t = add_track(title="One", artist="A", album="Covered")
    buf = io.BytesIO()
    Image.new("RGB", (600, 600), (200, 80, 20)).save(buf, "PNG")
    r = client.post("/api/albums/cover", data={"album": "Covered", "cover": (io.BytesIO(buf.getvalue()), "c.png")},
                    content_type="multipart/form-data")
    assert r.status_code == 200, r.get_json()
    assert db.session.get(Track, t.id).has_cover is True
    assert client.get(f"/cover/{t.id}").status_code == 200


def test_tidy_runs_deterministic_cleanup_without_a_key(app, client, add_track, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    t = add_track(title="The Reels - Warm Static (Official Video)", artist=None)
    r = client.post("/api/tracks/tidy", json={"track_ids": [t.id]}).get_json()
    assert r["tidied"] == 1 and r["ai"] is False
    row = db.session.get(Track, t.id)
    assert (row.title, row.artist) == ("Warm Static", "The Reels")
