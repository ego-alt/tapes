"""Audit 4.3: deleting from the library is undoable (trash), admin-gated when
admins are configured; 4.5: artist rename previews merges and can be undone."""
import pathlib
from datetime import datetime, timedelta

from models import Play, PlaylistTrack, Track, db
from trash import purge_trash


def _file(app, t):
    return pathlib.Path(app.config["MUSIC_DIR"]) / t.file_path


def test_delete_moves_to_trash_and_hides_everywhere(app, client, add_track):
    t = add_track(title="Gone", artist="Ghost", album="Haunt")
    keep = add_track(title="Kept", artist="Other")
    pid = client.post("/api/playlists", json={"name": "Mix"}).get_json()["key"]
    client.post(f"/api/playlists/{pid}/tracks", json={"track_id": t.id})
    client.post("/api/plays", json={"track_id": t.id})

    assert client.delete(f"/api/tracks/{t.id}").status_code == 204
    assert not _file(app, t).exists()
    trashed = pathlib.Path(app.config["MUSIC_DIR"]) / ".trash" / f"{t.id}.mp3"
    assert trashed.exists()

    titles = [x["title"] for x in client.get("/api/playlists/all/tracks").get_json()]
    assert titles == ["Kept"]
    shelf = {s["key"]: s["count"] for s in client.get("/api/playlists").get_json()}
    assert shelf["all"] == 1 and shelf["albums"] == 0 and shelf[pid] == 0
    assert [a["name"] for a in client.get("/api/artists").get_json()] == ["Other"]
    assert client.get(f"/api/playlists/{pid}/tracks").get_json() == []
    assert client.get(f"/stream/{t.id}").status_code == 404
    assert client.post("/api/tracks/by-ids", json={"ids": [t.id, keep.id]}).get_json()[0]["title"] == "Kept"


def test_restore_brings_back_file_tapes_and_plays(app, client, add_track):
    t = add_track(title="Back")
    pid = client.post("/api/playlists", json={"name": "Mix"}).get_json()["key"]
    client.post(f"/api/playlists/{pid}/tracks", json={"track_id": t.id})
    client.post("/api/plays", json={"track_id": t.id})
    client.delete(f"/api/tracks/{t.id}")

    r = client.post(f"/api/tracks/{t.id}/restore")
    assert r.status_code == 200 and r.get_json()["title"] == "Back"
    assert _file(app, t).exists()
    assert [x["title"] for x in client.get(f"/api/playlists/{pid}/tracks").get_json()] == ["Back"]
    assert Play.query.count() == 1


def test_purge_removes_only_old_trash(app, client, add_track):
    old, recent = add_track(title="Old"), add_track(title="Recent")
    client.delete(f"/api/tracks/{old.id}")
    client.delete(f"/api/tracks/{recent.id}")
    row = db.session.get(Track, old.id, execution_options={"include_deleted": True})
    row.deleted_at = datetime.now() - timedelta(days=31)
    db.session.commit()
    assert purge_trash(app) == 1
    assert db.session.get(Track, old.id, execution_options={"include_deleted": True}) is None
    assert db.session.get(Track, recent.id, execution_options={"include_deleted": True}) is not None
    assert PlaylistTrack.query.count() == 0


def test_scan_skips_the_trash(app, client, add_track):
    from scan import scan_library
    t = add_track(title="Trashed")
    client.delete(f"/api/tracks/{t.id}")
    r = scan_library(app.config["MUSIC_DIR"], app.config["COVER_DIR"], prune=True)
    assert r["added"] == 0 and r["pruned"] == 0
    assert client.post(f"/api/tracks/{t.id}/restore").status_code == 200


def test_admins_only_when_configured(app, client, add_track):
    t = add_track()
    app.config["ADMIN_USERS"] = {"someone-else"}
    r = client.delete(f"/api/tracks/{t.id}")
    assert r.status_code == 403
    assert r.get_json()["error"] == "Only an admin can delete songs from the library."
    r = client.patch("/api/artists", json={"old": "Artist", "new": "X"})
    assert r.status_code == 403
    app.config["ADMIN_USERS"] = {"local"}
    assert client.delete(f"/api/tracks/{t.id}").status_code == 204


def test_artist_rename_preview_merge_and_undo(app, client, add_track):
    a1 = add_track(title="One", artist="The Reels")
    a2 = add_track(title="Two", artist="The Reels")
    b1 = add_track(title="Three", artist="the reels.")
    p = client.get("/api/artists/rename-preview", query_string={"old": "the reels.", "new": "The Reels"}).get_json()
    assert p == {"name": "The Reels", "tracks": 1, "merges_into": 2}
    r = client.patch("/api/artists", json={"old": "the reels.", "new": "The Reels"}).get_json()
    assert r["name"] == "The Reels" and r["track_ids"] == [b1.id] and r["tag_failures"] == 0
    assert {t.artist for t in Track.query.all()} == {"The Reels"}
    # Undo puts exactly the moved tracks back, even though the names merged.
    u = client.patch("/api/tracks/artist", json={"track_ids": r["track_ids"], "artist": "the reels."})
    assert u.status_code == 200
    assert db.session.get(Track, b1.id).artist == "the reels."
    assert db.session.get(Track, a1.id).artist == db.session.get(Track, a2.id).artist == "The Reels"
