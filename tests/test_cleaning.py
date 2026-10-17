"""Title/artist cleanup on real YouTube titles.

`fixtures/yt_titles.json` holds ~300 titles from YouTube searches for 80 songs
across languages and genres, each checked against the known song and artist.
The table below covers the shapes that once went wrong.
"""
import json
import pathlib

import pytest

from cleaning import clean_meta

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
REAL = json.loads((FIXTURES / "yt_titles.json").read_text())


@pytest.mark.parametrize("case", REAL, ids=[c["title"][:50] for c in REAL])
def test_real_titles(case):
    assert list(clean_meta(case["title"], case["channel"], case["known"])) == case["want"]


CASES = [
    # (title, channel, known artists) → (title, artist)
    # The artist's own uploads, quoted song
    ('Dominic Fike "3 Nights" (Official Audio)', "Dominic Fike", (), ("3 Nights", "Dominic Fike")),
    ('Dominic Fike "King Of Everything" (Official Audio)', "Dominic Fike", (), ("King Of Everything", "Dominic Fike")),
    ("Babydoll (Official Audio)", "Dominic Fike", (), ("Babydoll", "Dominic Fike")),
    ("King of Everything", "Dominic Fike - Topic", (), ("King of Everything", "Dominic Fike")),
    # Plain "Artist - Song" with cruft
    ("The 1975 - Somebody Else (Official Video)", "The 1975", (), ("Somebody Else", "The 1975")),
    ("Kate Bush - Running Up That Hill (A Deal With God) - Official Music Video", "KateBushMusic", (), ("Running Up That Hill (A Deal With God)", "Kate Bush")),
    ("Daft Punk - Digital Love video oficial HD", "Some Uploader", (), ("Digital Love", "Daft Punk")),
    ("the beatles- here comes the sun original video", "Some Uploader", (), ("here comes the sun", "the beatles")),
    ("Radiohead - Reckoner (By Clement Picon)", "Radiohead", (), ("Reckoner", "Radiohead")),
    ("Blue Swede - Hooked on a Feeling", "Some Uploader", (), ("Hooked on a Feeling", "Blue Swede")),
    # Pipes: keep the part shaped like a song, drop shows, channels and albums
    ("Mitski - Nobody (Lyrics) | Nobody nobody nobody", "Some Uploader", (), ("Nobody", "Mitski")),
    ("Bad Bunny - Tití Me Preguntó | Un Verano Sin Ti", "Bad Bunny", (), ("Tití Me Preguntó", "Bad Bunny")),
    ("한글 자막 MV | Dominic Fike - Phone Numbers", "Sony Music Korea", (), ("Phone Numbers", "Dominic Fike")),
    ("Ditto - NewJeans [Music Bank] | KBS WORLD TV 230127", "KBS WORLD TV", ("NewJeans",), ("Ditto", "NewJeans")),
    # Translation and lyric notes
    ("(한글 번역) Dominic Fike - Vampire 🧛‍♂️", "Some Uploader", (), ("Vampire", "Dominic Fike")),
    ("[라이브] 그냥 미친 알앤비 원탑 노래 ㄷㄷ SZA - Good Days [가사해석/한글자막]", "Some Uploader", ("SZA",), ("Good Days", "SZA")),
    ("「coffee - beabadoobee (lyrics)☕️」", "Some Uploader", ("Beabadoobee",), ("coffee", "beabadoobee")),
    ('Portishead - Glory Box (Lyrics) "I\'m a Woman Written By a Man"', "Some Uploader", (), ("Glory Box", "Portishead")),
    # "Song - Artist" told apart by a known artist
    ("nobody - mitski (speed up)", "Some Uploader", ("Mitski",), ("nobody", "mitski")),
    ("Coffee (death bed) by Beabadoobee | 10HourBGM", "10 HOUR BGM", ("Beabadoobee",), ("Coffee (death bed)", "Beabadoobee")),
    # Duets stay whole
    ("Dua Lipa & Arctic Monkeys - Do I Wanna Know", "Some Uploader", ("Arctic Monkeys",), ("Do I Wanna Know", "Dua Lipa & Arctic Monkeys")),
    # Names in two scripts keep the Latin one
    ("[MV] IU(아이유) _ Blueming(블루밍)", "1theK (원더케이)", ("IU",), ("Blueming(블루밍)", "IU")),
    # Short known names don't split ordinary titles
    ("Love Story", "Taylor Swift", ("Love",), ("Love Story", "Taylor Swift")),
    ("Love, Actually", "Some Uploader", ("Love",), ("Love, Actually", "Some Uploader")),
    ("Burial, Archangel", "Some Uploader", ("Burial",), ("Archangel", "Burial")),
    ("Mac Miller-Good News", "Some Uploader", ("Mac Miller",), ("Good News", "Mac Miller")),
]


@pytest.mark.parametrize("title,channel,known,want", CASES, ids=[c[0][:50] for c in CASES])
def test_tricky_titles(title, channel, known, want):
    assert clean_meta(title, channel, known) == want


def test_never_returns_an_empty_title():
    for title in ["(Official Video)", "[MV]", "Lyrics", "🧛"]:
        t, _ = clean_meta(title, "Someone")
        assert t.strip()
