"""One-off: set the album on the Brazzaville "In Istanbul" tracks.

These were ripped from the playlist before the ripper passed the tape name to
the LLM as an album signal, so their album came back blank. This stamps the
album onto every blank-album track in that tape.

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
import sqlite3

TAPE_NAME = "Brazzaville in Istanbul (2009)"
ALBUM = "In Istanbul"

DEFAULT_DB = pathlib.Path(__file__).resolve().parent.parent / "instance" / "music.db"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="apply (default is preview)")
    ap.add_argument("--db", default=str(DEFAULT_DB), help="path to music.db")
    args = ap.parse_args()

    con = sqlite3.connect(args.db)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT t.id, t.title, t.album
        FROM tracks t
        JOIN playlist_tracks pt ON pt.track_id = t.id
        JOIN playlists p        ON p.id = pt.playlist_id
        WHERE p.name = ?
        """,
        (TAPE_NAME,),
    ).fetchall()

    if not rows:
        print(f"No tracks found in a tape named {TAPE_NAME!r} (db: {args.db}).")
        return

    changed = 0
    for r in rows:
        if (r["album"] or "").strip():
            print(f"skip  (album={r['album']!r}): {r['title']}")
            continue
        print(f"{'set ' if args.write else 'would set'} album={ALBUM!r}: {r['title']}")
        if args.write:
            con.execute("UPDATE tracks SET album = ? WHERE id = ?", (ALBUM, r["id"]))
            changed += 1

    if args.write:
        con.commit()
        print(f"\nUpdated {changed} track(s).")
    else:
        print("\nDry run — re-run with --write to apply.")
    con.close()


if __name__ == "__main__":
    main()
