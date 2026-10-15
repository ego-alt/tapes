"""GET /api/tracks?q= — word-wise search across title, artist and album."""


def test_search_matches_every_word_across_fields(client, add_track):
    client.get("/")  # attaches the local user
    add_track(title="Pink Moon", artist="Nick Drake", album="Pink Moon")
    add_track(title="River Man", artist="Nick Drake", album="Five Leaves Left")
    add_track(title="Moon River", artist="Frank Ocean")

    def titles(q):
        return [t["title"] for t in client.get("/api/tracks", query_string={"q": q}).get_json()]

    assert titles("drake") == ["River Man", "Pink Moon"]  # album order
    assert titles("moon river") == ["Moon River"]
    assert titles("drake moon") == ["Pink Moon"]
    assert titles("nothing") == []


def test_search_limit_and_validation(client, add_track):
    client.get("/")
    for i in range(5):
        add_track(title=f"Song {i}", artist="Same")
    assert len(client.get("/api/tracks?q=same&limit=2").get_json()) == 2
    r = client.get("/api/tracks?q=")
    assert r.status_code == 400 and r.is_json


def test_playlist_tracks_limit(client, add_track):
    client.get("/")
    for i in range(4):
        add_track(title=f"Song {i}", artist="Same")
    assert len(client.get("/api/playlists/all/tracks?limit=2").get_json()) == 2
    assert len(client.get("/api/playlists/all/tracks?limit=2&sort=most").get_json()) == 2
    assert len(client.get("/api/playlists/all/tracks").get_json()) == 4
    pid = client.post("/api/playlists", json={"name": "Mix"}).get_json()["key"]
    for tid in (1, 2, 3):
        client.post(f"/api/playlists/{pid}/tracks", json={"track_id": tid})
    first_two = client.get(f"/api/playlists/{pid}/tracks?limit=2").get_json()
    assert [t["id"] for t in first_two] == [1, 2]
