"""Audit 4.1, 4.2, 4.4: edits keep the track number, tracks come off a tape
without leaving the library, and the playhead can be saved by a beacon."""
from mutagen.easyid3 import EasyID3

from models import PlaybackSession, PlaylistTrack, Track, db


def test_track_dict_includes_track_no(client, add_track):
    t = add_track(title="Warm Static", album="Analog Hearts", track_no=1)
    rows = client.get("/api/playlists/all/tracks").get_json()
    assert rows[0]["track_no"] == 1
    assert rows[0]["id"] == t.id


def test_editing_title_only_keeps_track_number(app, client, add_track):
    t = add_track(title="Warm Static", album="Analog Hearts", track_no=1)
    r = client.patch(f"/api/tracks/{t.id}", json={"title": "Warm Static (edit)"})
    assert r.status_code == 200
    assert r.get_json()["track_no"] == 1
    assert db.session.get(Track, t.id).track_no == 1
    tags = EasyID3(f"{app.config['MUSIC_DIR']}/{t.file_path}")
    assert tags["title"] == ["Warm Static (edit)"]
    assert tags["tracknumber"] == ["1"]


def test_clearing_track_number_explicitly_still_works(client, add_track):
    t = add_track(track_no=4)
    client.patch(f"/api/tracks/{t.id}", json={"track_no": ""})
    assert db.session.get(Track, t.id).track_no is None


def test_remove_from_tape_keeps_track_in_library(app, client, add_track):
    t = add_track()
    pid = client.post("/api/playlists", json={"name": "Road trip"}).get_json()["key"]
    client.post(f"/api/playlists/{pid}/tracks", json={"track_id": t.id})
    assert client.delete(f"/api/playlists/{pid}/tracks/{t.id}").status_code == 204
    assert PlaylistTrack.query.count() == 0
    assert db.session.get(Track, t.id) is not None


def test_playstate_accepts_beacon_post(client, add_track):
    t = add_track()
    r = client.post("/api/playstate", json={
        "context": "music", "queue": [t.id], "index": 0, "position": 42.5})
    assert r.status_code == 204
    s = PlaybackSession.query.one()
    assert s.position_s == 42.5
    assert client.get("/api/playstate").get_json()["position"] == 42.5


def test_add_to_tape_reports_duplicates(client, add_track):
    t = add_track()
    pid = client.post("/api/playlists", json={"name": "Road trip"}).get_json()["key"]
    assert client.post(f"/api/playlists/{pid}/tracks", json={"track_id": t.id}).get_json() == {"added": True, "tape": "Road trip"}
    assert client.post(f"/api/playlists/{pid}/tracks", json={"track_id": t.id}).get_json() == {"added": False, "tape": "Road trip"}
