# Tapes

A personal cassette-deck music streamer for the home stack. The home page is a
cassette deck — the reels spin while a track plays and the paper label re-skins
to the current song.

![Tapes](images/tapes.png)

## Features

- **Cassette-deck player** — animated reels, scrubber, shuffle / repeat,
  favorites, keyboard shortcuts (`Space`, `Shift + ←/→`), lock-screen controls,
  and it resumes your queue across sessions and devices.
- **Browse** — All Tracks (sortable: by artist / recently added / recently
  played / most played), Singles, Favorites, Albums, Artists, and your own tapes.
- **Up Next** queue with drag-to-reorder; *Play next* / *Add to queue* per track.
- **Rip** any URL to MP3 with cover art via `yt-dlp` + `ffmpeg`, with live
  progress over SSE; paste a YouTube playlist to rip it into a new tape.
- **Tidy metadata** — ripped tags are cleaned automatically (YouTube cruft
  stripped, `Artist - Title` split); `flask retag` cleans an existing library.

## Run it — standalone

```sh
uv sync
export MUSIC_DIR=/path/to/mp3s            # optional; defaults to ./music
uv run flask --app app:create_app scan    # index the library
uv run flask --app app:create_app run --port 5003
# open http://127.0.0.1:5003
```

`ffmpeg` must be on your `PATH` for ripping. There's no login in standalone mode
— a single local user is attached automatically. To try it without your own
music, `uv run python scripts/generate_samples.py` writes tagged demo tracks
into `./music`.

## Run it — home stack

Served at `/music/` behind the [dashboard](../dashboard) nginx proxy: gated by
its `auth_request` and streaming audio via `X-Accel-Redirect`. The service is
wired into `../dashboard/docker-compose.yml`.

```sh
cd ../dashboard
MUSIC_HOST_DIR=/mnt/backup/music docker compose up -d --build music
```

Dashboard handles login; tapes trusts the `X-Forwarded-User` header and keeps
its own `users` rows for favorites, tapes, and playback state.

> Code is baked into the image at build time. After pulling changes, rebuild:
> `docker compose build music && docker compose up -d music`. A bare `up -d`
> reuses the old image.

## Commands

```sh
uv run flask --app app:create_app scan [--full] [--prune]   # index MUSIC_DIR
uv run flask --app app:create_app retag [--write]           # clean title/artist tags
```

`scan` is incremental (mtime/size cache); `--full` re-reads every file, `--prune`
drops rows for deleted files. `retag` previews by default; `--write` applies the
cleanup in place and rescans.

## Layout

```
app.py          create_app: db, login, blueprints, static cache-busting
cleaning.py     deterministic title/artist cleanup for rips
scan.py         flask scan / flask retag — mutagen tags + Pillow thumbnails
downloader.py   yt-dlp worker, playlist expansion, tag cleanup
routes/         index · stream · library (shelves/tapes/albums/artists) · downloads · auth
static/         css (tokens · primitives · index · player) + player.js
templates/      index.html
```
