import pathlib
from io import BytesIO

from PIL import Image


def _png(size=(660, 412)):
    out = BytesIO()
    Image.new("RGB", size, (30, 30, 30)).save(out, "PNG")
    return out.getvalue()


def test_the_page_stores_the_cassette_and_the_lock_screen_reads_it(app, client, add_track):
    t = add_track(title="Warm Static")
    assert client.get(f"/cassette/{t.id}/abc123").status_code == 404   # not drawn yet: the cover stands in
    assert client.put(f"/cassette/{t.id}/abc123", data=_png()).status_code == 204
    r = client.get(f"/cassette/{t.id}/abc123")
    assert r.status_code == 200 and r.mimetype == "image/jpeg"
    assert Image.open(BytesIO(r.data)).size == (512, 512)


def test_a_new_label_replaces_the_old_drawing(app, client, add_track):
    t = add_track()
    client.put(f"/cassette/{t.id}/old1", data=_png())
    client.put(f"/cassette/{t.id}/new2", data=_png())
    names = [p.name for p in (pathlib.Path(app.config["COVER_DIR"]) / "cassettes").glob("*.jpg")]
    assert names == [f"{t.id}-new2.jpg"]


def test_only_images_and_plain_keys_are_kept(client, add_track):
    t = add_track()
    assert client.put(f"/cassette/{t.id}/abc", data=b"<script>").status_code == 400
    assert client.put(f"/cassette/{t.id}/..%2Fx", data=_png()).status_code in (400, 404)
    assert client.put("/cassette/999/abc", data=_png()).status_code == 404
