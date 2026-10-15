"""Where finished rips are filed, and that same-named rips never collide."""
import pathlib

from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK

import downloader


def _tagged(path: pathlib.Path, **tags):
    path.write_bytes(b"")
    id3 = ID3()
    frames = {"title": TIT2, "artist": TPE1, "album": TALB, "track_no": TRCK}
    for key, value in tags.items():
        id3.add(frames[key](encoding=3, text=str(value)))
    id3.save(path)
    return str(path)


def test_library_path_from_tags(tmp_path):
    music = tmp_path / "music"
    full = _tagged(tmp_path / "a.mp3", title="Warm Static", artist="The Reels", album="Analog Hearts", track_no=3)
    assert downloader._library_path(music, full) == music / "The Reels" / "Analog Hearts" / "03 Warm Static.mp3"
    single = _tagged(tmp_path / "b.mp3", title="Midnight Rip", artist="DJ Orphan")
    assert downloader._library_path(music, single) == music / "DJ Orphan" / "Midnight Rip.mp3"
    bare = _tagged(tmp_path / "Some Video Title.mp3")
    assert downloader._library_path(music, bare) == music / "Unknown artist" / "Some Video Title.mp3"
    odd = _tagged(tmp_path / "c.mp3", title="What?/Why: <now>", artist="AC/DC", album="..Live.")
    assert downloader._library_path(music, odd) == music / "AC_DC" / "Live" / "What__Why_ _now_.mp3"


def test_same_name_rips_get_suffixes(tmp_path):
    dest = tmp_path / "Artist" / "Song.mp3"
    paths = []
    for i in range(3):
        src = tmp_path / f"rip{i}.mp3"
        src.write_bytes(bytes([i]))
        paths.append(downloader._move_into_library(str(src), dest))
    assert [p.name for p in paths] == ["Song.mp3", "Song (2).mp3", "Song (3).mp3"]
    assert [p.read_bytes() for p in paths] == [b"\x00", b"\x01", b"\x02"]   # nothing overwritten
