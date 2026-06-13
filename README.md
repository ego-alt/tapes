# Music — cassette-deck streamer

Personal music streamer for the Pi home stack. Home page is a cassette deck; the
reels turn while a track plays and the label re-skins to the current song. See
[`PLAN.md`](PLAN.md) for the full design and staged roadmap.

## Stage 1 — standalone (current)

```sh
uv sync
uv run python scripts/generate_samples.py     # optional: tagged demo tracks → ./music
uv run flask --app app:create_app scan          # index MUSIC_DIR (default ./music)
uv run flask --app app:create_app run --port 5003
# open http://127.0.0.1:5003
```

No login in standalone — a single local user is auto-attached. Point at a real
library with `MUSIC_DIR=/path/to/mp3s` (then re-run `scan`).

### CLI

```sh
uv run flask --app app:create_app scan [--full] [--prune]
```

## Stage 2 — behind the dashboard

Runs as a downstream app at `/music/`, gated by the dashboard's nginx
`auth_request` (trusts `X-Forwarded-User`), streaming via nginx `X-Accel-Redirect`.
The `music` service + `/music/` location + internal `/_audio/` alias are wired
into `../dashboard/docker-compose.yml` and `../dashboard/nginx/conf.d/home.conf`.

```sh
cd ../dashboard
MUSIC_HOST_DIR=/mnt/backup/music docker compose up -d --build
```

Config (set by compose): `APPLICATION_ROOT=/music`,
`AUTH_PROXY_HEADER=X-Forwarded-User`, `MUSIC_DIR=/data/music`, `USE_X_ACCEL=1`.

## Layout

```
app.py            create_app: db, login (proxy + standalone), blueprints, /healthz
proxy_auth.py     X-Forwarded-User in proxy mode; local user standalone
models.py         User + Track (flat Stage-1 catalog)
scan.py           `flask scan` — mutagen tags + cover thumbnails
routes/           index (page + /api/tracks), stream (/stream, /cover), auth
static/css/       tokens · primitives · index · player (the cassette)
static/js/        player.js — audio + cassette + queue
templates/        index.html
scripts/          generate_samples.py
```
