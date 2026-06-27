"""One-off: fix the Brazzaville "In Istanbul" tracks.

These were ripped before the ripper passed the tape name to the LLM as an album
signal, so their album came back blank and the "(In Istanbul)" album marker was
left stuck in the title. The tape is gone now, so we match on that title marker:
for every track whose title contains "(In Istanbul)" this sets album="In
Istanbul" (only when blank) and strips the marker out of the title.

Standalone — stdlib only, runs straight against the SQLite file. No docker, no
uv, no app deps:

    python3 scripts/fix_in_istanbul_album.py            # preview
    python3 scripts/fix_in_istanbul_album.py --write    # apply
    python3 scripts/fix_in_istanbul_album.py --write --db /path/to/music.db

DB defaults to ../instance/music.db relative to this script (the bind-mounted
host path, e.g. ~/Projects/tapes/instance/music.db on the Pi).

Note: this updates the DB only. A future `flask scan --full` re-reads tags from
the files and would revert these (incremental `scan` won't — it skips unchanged
files). If you run --full, re-run this, or write the tags via the app.
"""

import argparse
import pathlib
import re
import sqlite3

ALBUM = "In Istanbul"
# The marker in the title, anywhere, with surrounding space — collapsed away.
MARKER = re.compile(r"\s*\(\s*In Istanbul\s*\)", re.IGNORECASE)

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "instance" / "music.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply (default is preview)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to music.db")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, title, album FROM tracks WHERE title LIKE '%(In Istanbul)%'"
    ).fetchall()

    if not rows:
        print(f"No tracks with '(In Istanbul)' in the title found (db: {args.db}).")
        return

    changed = 0
    for r in rows:
        new_title = MARKER.sub("", r["title"]).strip()
        set_album = not (r["album"] or "").strip()

        title_note = f"{r['title']!r} -> {new_title!r}" if new_title != r["title"] else f"{r['title']!r} (title unchanged)"
        album_note = f"album -> {ALBUM!r}" if set_album else f"album kept {r['album']!r}"
        print(f"{'apply' if args.write else 'would'}: {title_note} | {album_note}")

        if args.write:
            if set_album:
                con.execute("UPDATE tracks SET album = ? WHERE id = ?", (ALBUM, r["id"]))
            if new_title != r["title"]:
                con.execute("UPDATE tracks SET title = ? WHERE id = ?", (new_title, r["id"]))
            changed += 1

    if args.write:
        con.commit()
        print(f"\nUpdated {changed} track(s).")
    else:
        print("\nDry run — re-run with --write to apply.")
    con.close()


if __name__ == "__main__":
    main()
