"""One-off: set the album on the Brazzaville "In Istanbul" tracks.

These were ripped from the playlist before the ripper passed the tape name to
the LLM as an album signal, so their album tag came back blank. This stamps the
album onto every blank-album track in that tape — in the mp3 tag (so a rescan
keeps it) and in the DB row.

    uv run python scripts/fix_in_istanbul_album.py            # preview
    uv run python scripts/fix_in_istanbul_album.py --write    # apply

Run it where the DB and music files live (on the Pi: `docker compose exec music
python scripts/fix_in_istanbul_album.py --write`).
"""

import pathlib
import sys

from mutagen.easyid3 import EasyID3

from app import create_app
from models import Playlist, PlaylistTrack, Track, db

TAPE_NAME = "Brazzaville in Istanbul (2009)"
ALBUM = "In Istanbul"


def main(write: bool):
    app = create_app()
    with app.app_context():
        music_dir = pathlib.Path(app.config["MUSIC_DIR"])
        playlists = Playlist.query.filter_by(name=TAPE_NAME).all()
        if not playlists:
            print(f"No tape named {TAPE_NAME!r} found.")
            return

        track_ids = {
            pt.track_id
            for pl in playlists
            for pt in PlaylistTrack.query.filter_by(playlist_id=pl.id)
        }
        tracks = Track.query.filter(Track.id.in_(track_ids)).all()

        changed = 0
        for t in tracks:
            if (t.album or "").strip():
                print(f"skip  (album={t.album!r}): {t.title}")
                continue
            print(f"{'set ' if write else 'would set'} album={ALBUM!r}: {t.title}")
            if write:
                path = music_dir / t.file_path
                audio = EasyID3(str(path))
                audio["album"] = ALBUM
                audio.save()
                t.album = ALBUM
                changed += 1

        if write:
            db.session.commit()
            print(f"\nUpdated {changed} track(s).")
        else:
            print("\nDry run — re-run with --write to apply.")


if __name__ == "__main__":
    main(write="--write" in sys.argv[1:])
