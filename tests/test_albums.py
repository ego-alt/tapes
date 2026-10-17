"""Albums from the playlist a track was ripped from.

`fixtures/yt_album_playlists.json` holds ~350 real playlists found by searching
YouTube for 47 albums: artists' own playlists, fans' "Full Album" uploads, and
look-alikes that aren't the album (slowed edits, moods, other albums).
"""
import json
import pathlib
import shutil

import pytest
from mutagen.easyid3 import EasyID3

import downloader
import llm_cleaning
from albums import album_from_playlist, parse_playlist_title, reconcile_album
from models import DownloadJob

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REAL = json.loads((FIXTURES / "yt_album_playlists.json").read_text())


@pytest.mark.parametrize("case", REAL, ids=[f'{c["artist"]}: {c["playlist"]["title"][:40]}' for c in REAL])
def test_real_playlists(case):
    assert album_from_playlist(case["playlist"], case["artist"]) == case["want"]


FIKE = "Dominic Fike"
CASES = [
    # (playlist title, owner, playlist id, track artist) → album
    ("Don't Forget About Me, Demos", FIKE, "PL8W7wLaHW9iaUdMsCajvCvP_YDyzUG4m7", FIKE, "Don't Forget About Me, Demos"),
    ("dominic fike - don’t forget about me, demos", "a fan", "PL1", FIKE, "don’t forget about me, demos"),
    ("Don’t Forget About Me, Demos - Dominic Fike (Full Album) (Lyrics)", "a fan", "PL2", FIKE, "Don’t Forget About Me, Demos"),
    ("Don’t Forget About Me, Demos - Dominic Fike ( slowed + reverb )", "a fan", "PL3", FIKE, None),
    ("Dominic Fike 'What Could Possibly Go Wrong?' Album", FIKE, "PL4", FIKE, "What Could Possibly Go Wrong?"),
    ("Dominic Fike, Sunburn", "a fan", "PL5", FIKE, "Sunburn"),
    ("Sunburn", FIKE, "PL6", FIKE, "Sunburn"),
    ("Sunburn", "a fan", "PL7", FIKE, None),                       # bare title, no evidence: not without a check
    ("Album - Sunburn", "Dominic Fike - Topic", "OLAK5uy_abc", FIKE, "Sunburn"),
    ("Uploads from Dominic Fike", FIKE, "UU1", FIKE, None),
    ("Dominic Fike - Babydoll", "a fan", "RDnb8CnIo_-_A", FIKE, None),
    ("Music Videos", FIKE, "PL8", FIKE, None),
    ("Dominic Fike Mix", "a fan", "RD1", FIKE, None),
    ("chill vibes", "a fan", "PL9", FIKE, None),
    ("Dominic Fike", "a fan", "PL10", FIKE, None),
    ("Kendrick Lamar - good kid, m.A.A.d city (Full Album)", "a fan", "PL11", "Kendrick Lamar", "good kid, m.A.A.d city"),
    ("Tyler, The Creator's IGOR - Full Album", "a fan", "PL12", "Tyler, The Creator", "IGOR"),
    ("米津玄師 4th Album「BOOTLEG」", "a fan", "PL13", "Kenshi Yonezu", "BOOTLEG"),
    ("ROSALÍA - MOTOMAMI (Album Completo)", "a fan", "PL14", "Rosalía", "MOTOMAMI"),
]


@pytest.mark.parametrize("title,owner,pid,artist,want", CASES, ids=[c[0][:50] for c in CASES])
def test_playlist_albums(title, owner, pid, artist, want):
    assert album_from_playlist({"id": pid, "title": title, "owner": owner}, artist) == want


def test_a_check_settles_a_bare_title():
    ctx = {"id": "PL7", "title": "good kid mAAd city", "owner": "a fan"}
    assert album_from_playlist(ctx, "Kendrick Lamar") is None
    assert album_from_playlist(ctx, "Kendrick Lamar", verify=lambda a, b: "good kid, m.A.A.d city") == "good kid, m.A.A.d city"
    assert album_from_playlist(ctx, "Kendrick Lamar", verify=lambda a, b: None) is None
    assert album_from_playlist(ctx, "Kendrick Lamar", verify=lambda a, b: "Something Else") is None


def test_named_artist_flag():
    assert parse_playlist_title("Dominic Fike - Sunburn (Full Album)", FIKE) == ("Sunburn", True, True)
    assert parse_playlist_title("Sunburn", FIKE) == ("Sunburn", False, False)


def test_reconcile_album_takes_the_library_spelling():
    assert reconcile_album("don’t forget about me, demos", ["Sunburn", "Don't Forget About Me, Demos"]) == "Don't Forget About Me, Demos"
    assert reconcile_album("New One", ["Sunburn"]) == "New One"


# ---------- the rip pipeline ----------

def _rip_file(tmp_path, title, artist, album=None):
    path = tmp_path / "rip.mp3"
    shutil.copy(FIXTURES / "tone-1s.mp3", path)
    tags = EasyID3()
    tags["title"], tags["artist"] = title, artist
    if album:
        tags["album"] = album
    tags.save(path)
    return str(path)


def _tags(path):
    t = EasyID3(path)
    return {k: t[k][0] for k in ("title", "artist", "album", "tracknumber", "date") if k in t}


OFFICIAL = {"id": "PL8W7wLaHW9iaUdMsCajvCvP_YDyzUG4m7", "title": "Don't Forget About Me, Demos", "owner": FIKE}


def test_official_playlist_without_llm(app, tmp_path):
    path = _rip_file(tmp_path, 'Dominic Fike "King Of Everything" (Official Audio)', FIKE)
    downloader._clean_tag(path, source={"source_playlist": OFFICIAL, "playlist_index": 6}, use_llm=False)
    assert _tags(path) == {"title": "King Of Everything", "artist": FIKE, "album": "Don't Forget About Me, Demos", "tracknumber": "6"}
    assert downloader._library_path(tmp_path, path) == tmp_path / FIKE / "Don't Forget About Me, Demos" / "06 King Of Everything.mp3"


def test_youtube_album_wins_and_year_is_kept(app, tmp_path):
    path = _rip_file(tmp_path, "Babydoll", "Dominic Fike", album="Don't Forget About Me, Demos")
    fan = {"id": "PL1", "title": "my summer", "owner": "a fan"}
    downloader._clean_tag(path, source={"source_playlist": fan, "playlist_index": 3, "year": 2018}, use_llm=False)
    assert _tags(path) == {"title": "Babydoll", "artist": FIKE, "album": "Don't Forget About Me, Demos", "date": "2018"}


def test_not_an_album_playlist_adds_nothing(app, tmp_path):
    path = _rip_file(tmp_path, "Dominic Fike - Babydoll (slowed + reverb)", "a fan")
    mood = {"id": "PL2", "title": "Dominic Fike but slowed", "owner": "a fan"}
    downloader._clean_tag(path, source={"source_playlist": mood, "playlist_index": 1}, use_llm=False)
    assert "album" not in _tags(path) and "tracknumber" not in _tags(path)


def _fake_llm(monkeypatch, reply):
    seen = {}

    def correct_track(meta):
        seen.update(meta)
        return reply

    monkeypatch.setattr(llm_cleaning, "correct_track", correct_track)
    return seen


def test_llm_sees_the_playlist_and_decides_the_album(app, tmp_path, monkeypatch):
    seen = _fake_llm(monkeypatch, {"title": "3 Nights", "artist": FIKE, "confidence": "high", "album": "Don't Forget About Me, Demos", "track_no": 1})
    fan = {"id": "PL3", "title": "dominic fike - don’t forget about me, demos", "owner": "a fan"}
    path = _rip_file(tmp_path, "3 Nights", "Dominic Fike - Topic")
    downloader._clean_tag(path, source={"source_playlist": fan, "playlist_index": 1, "playlist": fan["title"]}, use_llm=True)
    assert seen["playlist_owner"] == "a fan" and seen["playlist_index"] == 1 and seen["playlist_album"] == "don’t forget about me, demos"
    assert _tags(path) == {"title": "3 Nights", "artist": FIKE, "album": "Don't Forget About Me, Demos", "tracknumber": "1"}


def test_llm_saying_no_album_overrides_the_parser(app, tmp_path, monkeypatch):
    _fake_llm(monkeypatch, {"title": "Sunburn", "artist": FIKE, "confidence": "high", "album": None, "track_no": None})
    path = _rip_file(tmp_path, "Sunburn", FIKE)
    ctx = {"id": "PL4", "title": "Dominic Fike - Sunburn (Full Album)", "owner": "a fan"}
    downloader._clean_tag(path, source={"source_playlist": ctx, "playlist_index": 2}, use_llm=True)
    assert "album" not in _tags(path)


def test_llm_failure_falls_back_to_the_parser(app, tmp_path, monkeypatch):
    _fake_llm(monkeypatch, None)
    path = _rip_file(tmp_path, 'Dominic Fike "Babydoll" (Official Audio)', FIKE)
    assert downloader._clean_tag(path, source={"source_playlist": OFFICIAL, "playlist_index": 3}, use_llm=True) is False
    assert _tags(path)["album"] == "Don't Forget About Me, Demos" and _tags(path)["tracknumber"] == "3"


def test_llm_album_only_counts_when_flagged():
    raw = {"title": "T", "artist": "A", "album": "Guess", "track_no": 4, "confidence": "high", "enriched": []}
    assert llm_cleaning._normalize(raw)["album"] is None and llm_cleaning._normalize(raw)["track_no"] is None
    raw["enriched"] = ["album"]
    assert llm_cleaning._normalize(raw)["album"] == "Guess" and llm_cleaning._normalize(raw)["track_no"] == 4


def test_submit_keeps_the_playlist_on_each_job(app, client, monkeypatch):
    urls = [f"https://www.youtube.com/watch?v={i}" for i in "abc"]
    monkeypatch.setattr("routes.downloads.expand_playlist", lambda url: (urls, OFFICIAL["title"], OFFICIAL))
    monkeypatch.setattr("routes.downloads.enqueue", lambda job_id: None)
    r = client.post("/api/downloads", json={"url": "https://www.youtube.com/playlist?list=" + OFFICIAL["id"]})
    assert r.status_code == 201
    jobs = DownloadJob.query.order_by(DownloadJob.id).all()
    assert [j.playlist_index for j in jobs] == [1, 2, 3]
    assert all(json.loads(j.source_playlist) == OFFICIAL for j in jobs)
