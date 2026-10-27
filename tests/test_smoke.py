def test_index_renders(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"<span class=\"sr-only\">Tapes</span>" in r.data and b"lib-bar" in r.data


def test_shelf_lists_builtins(client, add_track):
    add_track()
    keys = [s["key"] for s in client.get("/api/playlists").get_json()]
    assert keys[:4] == ["all", "singles", "albums", "artists"]
