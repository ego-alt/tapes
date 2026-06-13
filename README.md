# Tapes — cassette-deck music streamer

## Overview

Personal music streamer for the Pi home stack. The home page is a cassette deck:
the reels spin while a track plays, the orange band carries the transport, and
the paper label re-skins to the current song — title, artist, and cover art slotted
into the index card.

![Tapes](images/tapes.png)

## Features

- **Cassette deck player**
  - Animated reels that spin while playing and pause when you do.
  - Procedurally textured shell (matte grain, ribbing, diagonal hatching, surface scratches) — no image assets.
  - The label re-skins to the playing track: title, artist, and embedded cover art.
  - Scrub bar, play/pause, previous/next, and a favorite toggle.
  - Keyboard shortcuts: `Space` play/pause, `Shift + ←/→` previous/next track.
  - Lock-screen / media-key controls via the browser Media Session API.
  - Resumes your queue and playback position across sessions and devices.
- **Tapes (playlists)**
  - Built-in shelves: All Tracks, Singles, and Favorites.
  - Create your own tapes, rename them inline by clicking the title, and delete from inside the tape.
  - Add any track to a tape from its `+` menu.
  - Search within a tape.
- **Ripping**
  - Paste any URL to rip it to MP3 with embedded cover art and metadata (via `yt-dlp` + `ffmpeg`).
  - Live progress bar labelled with the song title.
  - Paste a YouTube **playlist** URL and it expands into one job per video, collecting them into a new tape named after the playlist as each track lands.
- **Indexing**
  - `flask scan` reads ID3 tags with `mutagen` and generates cover thumbnails with Pillow.
  - Incremental by default (mtime/size cache); `--full` re-reads everything, `--prune` drops rows for deleted files.
- **Favorites & history**
  - Favorite tracks for the Favorites shelf; play counts recorded per user.

## Installation

1. **Clone the repository**:
   ```bash
   git clone git@github.com:ego-alt/tapes.git
   cd tapes
   ```

2. **Install dependencies** with [`uv`](https://docs.astral.sh/uv/):
   ```bash
   uv sync
   ```

3. **Point at your music** (optional — defaults to `./music`):
   ```bash
   export MUSIC_DIR=/path/to/your/mp3s
   ```
   Or generate tagged demo tracks into `./music`:
   ```bash
   uv run python scripts/generate_samples.py
   ```

4. **Index the library and run**:
   ```bash
   uv run flask --app app:create_app scan
   uv run flask --app app:create_app run --port 5003
   # open http://127.0.0.1:5003
   ```

   `ffmpeg` must be on your `PATH` for ripping to work.

In standalone mode there is no login — a single local user is auto-attached.

## Home stack (with dashboard)

Served at `/music/` behind the [dashboard](../dashboard) nginx proxy, gated by the
dashboard's `auth_request` and streaming audio via nginx `X-Accel-Redirect`. The
`music` service, the `/music/` location, and the internal `/_audio/` alias are wired
into `../dashboard/docker-compose.yml` and `../dashboard/nginx/conf.d/home.conf`.

```bash
cd ../dashboard
MUSIC_HOST_DIR=/mnt/backup/music docker compose up -d --build music
```

Config (set by compose):

```bash
APPLICATION_ROOT=/music
AUTH_PROXY_HEADER=X-Forwarded-User
MUSIC_DIR=/data/music
USE_X_ACCEL=1
SECRET_KEY=...   # python -c "import secrets; print(secrets.token_hex(32))"
```

Dashboard handles login; this app trusts the `X-Forwarded-User` header and keeps
its own `users` rows for favorites, tapes, and playback state. Omit `APPLICATION_ROOT`
and `AUTH_PROXY_HEADER` for standalone dev (implicit local user on port 5003).

After adding a user in dashboard, sync shadow accounts:

```bash
cd ../dashboard && uv run python scripts/sync_household_users.py
```

> **Note:** code is baked into the image at build time (not bind-mounted). After
> pulling changes on the Pi, rebuild and recreate the container —
> `docker compose build music && docker compose up -d music`. A bare `up -d`
> reuses the old image.

## Usage

- **Play**: Open a shelf or tape, click a track. The reels spin and the label
  re-skins to the song. `Space` toggles play; `Shift + ←/→` skip tracks.
- **Make a tape**: Type a name in the "New tape…" box. Click into a tape and click
  its title to rename inline (Enter saves, Esc cancels); the "Delete tape" button
  lives at the top of the tape view.
- **Add tracks**: Hover a track and hit `+` to drop it onto any tape.
- **Rip music**: Click the ⬇ button in the sidebar header, paste a URL, and Get.
  Watch progress in the panel. Paste a YouTube playlist URL to rip the whole list
  into a new tape.
- **Favorite**: Use the ♡ on the deck or in a track row; favorites collect in the
  Favorites shelf.

## Commands

- **Scan the library** — index `MUSIC_DIR` into the catalog:
  ```bash
  uv run flask --app app:create_app scan [--full] [--prune]
  ```
  `--full` re-reads every file (ignores the mtime cache); `--prune` drops DB rows
  whose files are gone.

## Layout

```
app.py            create_app: db, login (proxy + standalone), blueprints, /healthz
proxy_auth.py     X-Forwarded-User in proxy mode; local user standalone
models.py         User · Track · Playlist · PlaylistTrack · Favorite · Play · PlayState · DownloadJob
scan.py           `flask scan` — mutagen tags + Pillow cover thumbnails
downloader.py     yt-dlp worker thread, playlist expansion, title cleanup
routes/           index · stream (/stream, /cover) · library (shelves, tapes, favorites) · downloads · auth
static/css/       tokens · primitives · index · player (the cassette)
static/js/        player.js — audio + cassette + queue + downloads
templates/        index.html
scripts/          generate_samples.py
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -m 'Add some new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request
