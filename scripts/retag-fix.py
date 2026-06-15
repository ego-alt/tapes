#!/usr/bin/env python3
"""Clean the library's tags AND apply manual corrections for the handful of
files the deterministic cleaner can't get right (reversed "Title - Artist"
names, messy soundtrack titles, etc.), then rescan.

Files listed in FIXES get their exact tags; everything else goes through the
normal `clean_meta`. Dry-run by default.

Run inside the music container (WORKDIR is /app):
    docker compose exec music uv run python scripts/retag-fix.py            # preview
    docker compose exec music uv run python scripts/retag-fix.py --write    # apply + rescan

⚠️  Tag edits are in place and irreversible. The DB is backed up automatically
    on --write; back up MUSIC_DIR yourself if you want a net.
"""
import os
import pathlib
import shutil
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # repo root

from mutagen.easyid3 import EasyID3

from cleaning import clean_meta

# Basename (exactly as on disk) -> (artist, title). Edit/extend freely.
FIXES = {
    # reversed "Title - Artist" — cleaner overwrote the correct artist
    "Sweet - Cigarettes After Sex.mp3": ("Cigarettes After Sex", "Sweet"),
    "Apocalypse - Cigarettes After Sex (lyrics).mp3": ("Cigarettes After Sex", "Apocalypse"),
    "Like Real People Do - Hozier.mp3": ("Hozier", "Like Real People Do"),
    "[Official Video] Run to You - Pentatonix.mp3": ("Pentatonix", "Run to You"),
    "In All My Dreams I Drown - The Devil's Carnival.mp3": ("The Devil's Carnival", "In All My Dreams I Drown"),
    # best guesses for messy names — double-check these before applying
    "Sade - Smooth Operator - Official - 1984.mp3": ("Sade", "Smooth Operator"),
    "Bojack Horseman ｜ Mr. Blue - Catherine Feeny- Lyrics.mp3": ("Catherine Feeny", "Mr. Blue"),
    "Woman in Love - Barbra Streisand Subtitulado.mp3": ("Barbra Streisand", "Woman in Love"),
    "Nobody Movie Soundtrack 2021 ⧸⧸ Serye Glaza - NATASHA KOROLYOVA.mp3": ("Natasha Korolyova", "Serye Glaza"),
    "구룡 (North Korea) — 백두의 소환 — 2025 demo.mp3": ("구룡 (North Korea)", "백두의 소환"),
    "鄭融 Stephanie Cheng ⧸ 周柏豪 Pakho Chau - 一事無成 [鄭．融精選] - 官方完整版MV.mp3": (
        "鄭融 Stephanie Cheng / 周柏豪 Pakho Chau", "一事無成"),
}

WRITE = "--write" in sys.argv
music_dir = pathlib.Path(os.environ.get("MUSIC_DIR", "music"))

changed = 0
for p in sorted(music_dir.rglob("*.mp3")):
    try:
        audio = EasyID3(str(p))
    except Exception:
        continue
    title = (audio.get("title") or [None])[0]
    artist = (audio.get("artist") or [None])[0]

    if p.name in FIXES:
        new_artist, new_title = FIXES[p.name]
    else:
        new_title, new_artist = clean_meta(title, artist)

    diffs = []
    if new_title and new_title != title:
        diffs.append(("title", title, new_title))
    if new_artist and new_artist != artist:
        diffs.append(("artist", artist, new_artist))
    if not diffs:
        continue

    changed += 1
    print(p.name)
    for field, old, new in diffs:
        print(f"    {field}: {old!r} -> {new!r}")
    if WRITE:
        if new_title:
            audio["title"] = new_title
        if new_artist:
            audio["artist"] = new_artist
        audio.save()

print(f"\n{changed} file(s) " + ("updated" if WRITE else "would change — pass --write to apply"))

if WRITE and changed:
    from app import create_app
    from scan import scan_library

    app = create_app()
    with app.app_context():
        db_path = pathlib.Path(app.instance_path) / "music.db"
        if db_path.exists():
            shutil.copy(db_path, db_path.with_suffix(f".pre-fix-{time.strftime('%Y%m%d-%H%M%S')}.bak"))
        r = scan_library(app.config["MUSIC_DIR"], app.config["COVER_DIR"], full=True)
        print(f"rescan: +{r.get('added', 0)} added, ~{r.get('updated', 0)} updated")
