"""Loudness + gapless info: parsing, album maths, tags, claiming, and what the
player receives."""
import pathlib
import shutil

import pytest
from mutagen.id3 import ID3, TIT2

import audio_analysis as aa
from models import Track, db

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")


def test_reads_encoder_delay_and_padding():
    g = aa.read_gapless(str(FIXTURES / "tone-1s.mp3"))
    assert g.sample_rate == 44100
    assert g.samples == 44100          # exactly the one second that was encoded
    assert g.delay == 576 and g.padding > 0


def test_reads_gapless_info_behind_an_id3_tag(tmp_path):
    f = tmp_path / "tagged.mp3"
    shutil.copy(FIXTURES / "tone-1s.mp3", f)
    t = ID3()
    t.add(TIT2(encoding=3, text=["x" * 3000]))   # a large tag pushes the audio along
    t.save(f)
    assert aa.read_gapless(str(f)).samples == 44100


def test_no_info_tag_means_no_gapless_info():
    assert aa.read_gapless(str(FIXTURES / "tone-1s-noxing.mp3")) is None


def test_album_loudness_is_the_energy_mean():
    agg = aa.album_loudness([(-10.0, -1.0, 100), (-20.0, -5.0, 100), (None, None, 50)])
    assert agg.lufs == pytest.approx(-12.596, abs=0.01)
    assert agg.peak_db == -1.0
    assert aa.album_loudness([(None, None, 10)]) is None


def test_replaygain_tags_leave_the_audio_alone(tmp_path):
    f = tmp_path / "t.mp3"
    shutil.copy(FIXTURES / "tone-1s.mp3", f)
    assert aa.write_replaygain_tags(str(f), aa.Loudness(-12.0, -0.5), aa.Loudness(-14.0, -0.2))
    tags = {fr.desc: fr.text[0] for fr in ID3(f).getall("TXXX")}
    assert tags["REPLAYGAIN_TRACK_GAIN"] == "-6.00 dB"      # -18 reference − (−12)
    assert tags["REPLAYGAIN_ALBUM_GAIN"] == "-4.00 dB"
    assert float(tags["REPLAYGAIN_TRACK_PEAK"]) == pytest.approx(0.944, abs=0.001)
    assert aa.read_gapless(str(f)).samples == 44100


@needs_ffmpeg
def test_measures_loudness(tmp_path):
    loud = aa.measure_loudness(str(FIXTURES / "tone-1s.mp3"))
    assert -30 < loud.lufs < -15 and loud.peak_db < 0


def _stub_measure(monkeypatch, lufs=-10.0, peak=-0.5):
    monkeypatch.setattr(aa, "measure_loudness", lambda path, **kw: aa.Loudness(lufs, peak))


def test_new_track_gets_figures_and_album_is_refreshed(app, add_track, monkeypatch):
    a = add_track(title="One", album="LP", duration_s=100)
    shutil.copy(FIXTURES / "tone-1s.mp3", pathlib.Path(app.config["MUSIC_DIR"]) / a.file_path)
    _stub_measure(monkeypatch, -10.0)
    aa.analyze_new_track(a, app.config["MUSIC_DIR"])
    b = add_track(title="Two", album="LP", duration_s=100)
    _stub_measure(monkeypatch, -20.0, -5.0)
    aa.analyze_new_track(b, app.config["MUSIC_DIR"])
    db.session.commit()
    assert a.loudness_lufs == -10.0 and a.audio_samples == 44100 and a.enc_delay == 576
    assert b.audio_samples is None                       # its file has no LAME tag
    for t in (a, b):
        assert t.album_loudness_lufs == pytest.approx(-12.596, abs=0.01)
        assert t.album_peak_db == -0.5


def test_claiming_hands_out_each_track_once(app, add_track):
    add_track(title="A")
    add_track(title="B")
    first = aa.claim_next(db.session)
    second = aa.claim_next(db.session)
    assert {first.title, second.title} == {"A", "B"}
    assert aa.claim_next(db.session) is None


def test_player_receives_levelling_and_gapless_fields(client, add_track):
    client.get("/")
    t = add_track(title="Song", album="LP")
    t.loudness_lufs, t.true_peak_db = -9.5, -0.3
    t.album_loudness_lufs, t.album_peak_db = -11.0, -0.1
    t.sample_rate, t.enc_delay, t.enc_padding, t.audio_samples = 44100, 576, 700, 441000
    db.session.commit()
    row = client.get("/api/playlists/all/tracks").get_json()[0]
    levels = (row["lufs"], row["peak"], row["album_lufs"], row["album_peak"])
    assert levels == (-9.5, -0.3, -11.0, -0.1)
    assert row["gapless"] == {"rate": 44100, "delay": 576, "padding": 700, "samples": 441000}


def test_moving_a_song_to_another_album_refreshes_both(client, add_track):
    client.get("/")
    a = add_track(title="A", album="Old", duration_s=100)
    b = add_track(title="B", album="Old", duration_s=100)
    a.loudness_lufs, a.true_peak_db = -10.0, -1.0
    b.loudness_lufs, b.true_peak_db = -20.0, -2.0
    aa.refresh_album("Old")
    db.session.commit()
    client.patch(f"/api/tracks/{b.id}", json={"album": "New"})
    a, b = db.session.get(Track, a.id), db.session.get(Track, b.id)
    assert a.album_loudness_lufs == pytest.approx(-10.0)
    assert b.album_loudness_lufs == pytest.approx(-20.0)
