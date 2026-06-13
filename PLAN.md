# Music — personal streaming app for the home stack

A fourth downstream app in the Pi home stack: a folder of MP3s, a library
scanner, an HTTP audio streamer, a web player, and a yt-dlp downloader page.
Cloned from `calendar/` so it inherits the proven shape — Flask + uv + gunicorn
+ SQLAlchemy + SQLite, mounted under `/music/` behind the dashboard's nginx,
trusting `X-Forwarded-User`. No new auth, no new login, no new design language.

This is a plan, not a spec — settled decisions are flagged **[fixed]**; the
choices that must be made before coding are in **§0**; deferred ones in §13.

**Status (2026-06-13)** — **Stage 1 done; Stage 2 code-complete (not yet
deployed).** Full-DIY Flask (not Navidrome): the two hard requirements —
*aesthetic parity with calendar/library* and *dashboard gating* — are things our
own stack already solves. Built so far: the scan, `send_file`/X-Accel streaming,
and the realistic cassette-deck player. Stage-4 yt-dlp→mp3 pipeline has been
exercised by hand (one track pulled) but the in-app downloader isn't built yet.
Stage progress tracked in §12.

---

## 0. Decisions — locked (2026-06-13)

All four scaffold-gating choices are decided; the rest (§13) can wait.

- **D1 — Streaming transport → X-Accel-Redirect.** Flask authenticates +
  resolves the track; nginx serves the file with range/206/seek in C, zero
  Python in the byte path. Requires the music dir mounted into the *nginx*
  container too (§6). **[fixed]**
- **D2 — File layout → index-in-place.** Existing folders are the library,
  indexed as-is and **never moved**; the main music mount is **read-only**.
  yt-dlp/beets writes only into a dedicated, writable `…/music/_downloads/`
  subtree that is also scanned. Protects the curated collection. **[fixed]**
- **D3 — Sharing → shared catalog, per-user state.** One track/artist/album
  catalog visible to every household user; playlists, favorites, play history,
  and resume are per-user (the §3 schema reflects this). **[fixed]**
- **D4 — Downloader → fast-follow (build step 6).** Streaming + player ship
  first (steps 1–5); the yt-dlp/beets downloader — and the ffmpeg + MusicBrainz
  + background-worker dependencies it brings to the Pi — lands afterward. **[fixed]**

---

## 1. Goal

- Stream a drive of MP3s to any device's browser, gated behind one dashboard
  login, with per-user playlists / favorites / play history / resume.
- A downloader page: paste a URL → yt-dlp extracts MP3 → beets autotags →
  appears in the library.
- Aesthetically a sibling of calendar/library (shared design-token contract),
  appearing as a dashboard tile via `homehub.*` labels.
- Independently runnable in dev (local login) exactly like calendar/library —
  auth mode is a config flag, never a code fork.
- A path to a future mobile client that reuses the dashboard's API-token
  (Bearer) mechanism — no new auth surface.

---

## 2. Architecture overview

```
                  ┌──────────────┐
   browser  ───>  │    nginx     │  ──>  dashboard  (auth + /auth/verify)
                  │  (TLS, only  │  ──>  library    (Flask, X-Forwarded-User)
                  │   entrypoint)│  ──>  calendar   (Flask, X-Forwarded-User)
                  └──────────────┘  ──>  music      (Flask, X-Forwarded-User)  ← new
                          │
                          └── internal location /_audio/  (X-Accel-Redirect target)
```

- Identical downstream contract to calendar: nginx runs `auth_request` →
  `/auth/verify`, injects `X-Forwarded-User`; the app trusts it via a verbatim
  copy of `calendar/proxy_auth.py`. **[fixed]**
- Bytes do **not** flow through Python (D1). The Flask stream endpoint
  authenticates + resolves the track, then returns an `X-Accel-Redirect` to an
  `internal` nginx location mapped to the music volume; nginx serves the file
  with full range/206 support and zero Python in the byte path (see §6).
- Music lives on the USB HDD, bind-mounted **read-only** into the container
  (D2 index-in-place), with a separate writable `_downloads/` mount for the
  downloader; the SQLite index lives in `instance/` (bind-mounted), never on
  the SD card.

---

## 3. Schema

`flask_sqlalchemy` + `flask-migrate`, matching calendar/library exactly. The
`users` table is the same shadow pattern — `password_hash` NULL in proxy mode,
auto-created on first `X-Forwarded-User` sight.

**Three-layer model** — only the bottom layer is mandatory, so nothing is ever
orphaned: every track lives in the **library** (`tracks`) unconditionally;
**album** (nullable FK) and **playlist** (M2M, zero-or-more) are optional
groupings layered on top. A YouTube single with no album and on no playlist is
still fully reachable via All Tracks / By Artist / Recently Added / Search.

> **Stage 1 ships a minimal subset** (§12): a denormalized `tracks` table only.
> The tables below are the Stage-3 target; albums/playlists/favorites/plays
> arrive then.

Tables:

- **users** — `id, username (unique), password_hash (nullable), created_at`.
  Copied from calendar verbatim.
- **artists** — `id, name (unique), sort_name`.
- **albums** — `id, title, artist_id→artists, year, cover_path`. Unique on
  `(artist_id, title)`.
- **tracks** — `id, file_path (unique), file_hash, title, artist_id (nullable),
  album_id (nullable), track_no, disc_no, duration_s, bitrate, size_bytes,
  mtime, added_at`. Album/artist nullable — singles need neither.
  - `file_hash` (cheap partial hash: size + first/last 64 KB) is the stable
    identity across moves/renames; `file_path` + `mtime` drive incremental
    rescans. **[fixed: hash, not path, is identity]**
  - Index `(artist_id, album_id, disc_no, track_no)` for album ordering.
- **playlists** — `id, user_id→users, name, created_at`.
- **playlist_tracks** — `playlist_id, track_id, position`. PK `(playlist_id,
  position)`.
- **favorites** — `user_id, track_id`. PK `(user_id, track_id)`.
- **plays** — `id, user_id, track_id, played_at`. Powers recently-played +
  play counts. (Mirrors how library-app tracks reading state.)
- **playstate** — `user_id (PK), track_id, position_s, queue_json,
  updated_at`. One row per user: resume point + persisted queue, synced across
  devices (the library-app "remembers where you read" feature, for audio).
- **download_jobs** — `id, user_id, url, status (queued|running|done|error),
  progress, message, track_id (nullable), created_at`. See §7.

---

## 4. Library scan

- **Scan, don't serve-from-scan** — walk the HDD once into `tracks`, serve
  every play from the DB. **[fixed]**
- Incremental: skip files whose `(path, mtime, size)` are unchanged; this makes
  re-scans cheap on a Pi even for a large library.
- Tag parsing via **`mutagen`** (artist/album/title/track/disc/duration/
  bitrate). Fallbacks for missing tags: filename heuristics, "Various Artists"
  detection for compilations (`albumartist` ≠ `artist`).
- **Cover art**: embedded (APIC frame) *or* folder `cover.jpg`/`folder.jpg`.
  Extract once, resize to a thumbnail, cache under `instance/covers/<hash>.jpg`.
  Never decode full-res art on browse — that's a real jank source.
- Triggers: a `flask scan` CLI command (cron-friendly, like library's
  `import-books` / `backup-db`), **and** auto-scan after each download job
  completes (§7). Optional `watchdog` filesystem watcher is a §13 nice-to-have.

---

## 5. Frontend & design tokens

Server-rendered Flask + Jinja + vanilla JS + static CSS — same as calendar
(*not* the React/Tailwind dashboard stack; content apps stay on Flask's home
turf, per `dashboard/PLAN.md §2`). **[fixed]**

- **File structure mirrors library** (cleaner than calendar's monolith):
  `tokens.css` (palette + scale `:root`), `primitives.css` (`.btn` / `.input`),
  `index.css` (layout), `player.css` (player-specific tokens). **[fixed]**
- **Copy verbatim** from the shared contract: `primitives.css`, and the scale /
  font tokens (`--space-*`, `--radius-*`, `--text-*`, `--font-sans` Inter,
  `--font-mono`). Identical in calendar + library — they don't change per app.
- **Palette → Gruvbox dark + orange accent.** Reuse calendar's Gruvbox-dark
  neutrals (`--color-bg-base #282828`, `--color-text-primary #ebdbb2`, etc.);
  set `--color-accent #fe8019` / `--color-accent-hover #d65d0e`. Dark suits a
  listening app (immersive now-playing, art pops); orange distinguishes the
  tile from calendar (aqua) and library (blue). **[fixed]**
- **`player.css` — music-specific tokens, all derived from base** (the way
  library's `reader.css` extends, never hardcodes):
  ```css
  --cassette-body: var(--color-bg-elevated);  --reel-hub: var(--color-accent);
  --tape: #3a2f28;                             /* dark spool, on the dark deck */
  --scrubber-track: var(--color-border);       --scrubber-fill: var(--color-accent);
  --track-active: var(--color-accent);          --track-hover: var(--color-bg-inset);
  --label-bg: #ece3d0;                          /* cream Sharpie-label */
  --art-radius: var(--radius-md);               --art-shadow: var(--color-shadow);
  ```
  plus a label font token alongside the scale: `--font-label` (a marker /
  handwritten display face) for the cassette label; `--font-sans` (Inter) stays
  for all UI chrome.
  New components to style (rest inherits): the cassette deck, reels/scrubber,
  track rows (active/hover), the navigator list.

**Aesthetic — a retro cassette deck.** The home page *is* a cassette in a deck.

- **The deck = a queue visualizer.** Playback plays a *queue* (from a track, a
  search result, later an album or a saved mixtape); the cassette is the visual
  skin for whatever's in it. A playlist is just a *saved queue* — a mixtape.
- **Skin reacts to the current song**: the label shows the playing track's
  **cover art + title/artist** (long titles → marquee scroll, in a marker-style
  `--font-label`), optional tint from the art's dominant color.
- **Reels turn while playing**: `@keyframes rotate` gated by
  `animation-play-state` on play/pause (GPU-cheap). Stage 3 adds the
  *tape-pack transfer* (left reel shrinks / right fills as ambient progress, SVG
  radii on `timeupdate`). A thin scrub line under the cassette does precise
  seeking. Honor `prefers-reduced-motion` (freeze the reels).
- **Transport** as chunky deck buttons (▶ ‖ ◀◀ ▶▶ ■).
- **Navigator sidebar**: search + track list; collapses to leave just the
  cassette. Stage 3 turns it into the cassette **shelf** (mixtapes as tapes +
  virtual *All Tracks* / *Singles*).
- **Media Session API** — lock-screen / Bluetooth controls on mobile. Cheap,
  high-impact.
- Playback via HTML5 `<audio>` (MP3 plays natively → no transcode); prefetch the
  next track for snappy transitions.

---

## 6. Streaming

Bytes go via nginx, not Python (D1). Unlike library, which serves book bytes
through Flask, the music dir is mounted into the nginx container so it can serve
audio directly — justified by long-lived audio sessions where freeing the worker
and letting nginx handle range/seek matters.

- **Stream endpoint** `GET /stream/<track_id>`: auth (proxy header) →
  look up `tracks.file_path` → return a response carrying
  `X-Accel-Redirect: /_audio/<relative_path>` + correct `Content-Type`.
  nginx maps `/_audio/` (`internal;`) to the music volume and serves the file
  with `Accept-Ranges`/206/seek for free.
- **No on-the-fly transcoding in v1.** MP3-only → serve bytes directly. This
  avoids the one genuinely CPU-heavy, seek-breaking failure mode on a Pi.
  Bitrate-downscaling for cellular is a §13 item (would require HLS segmenting,
  not naive streaming).
- **Worker class**: use `gthread` (like library: `--worker-class gthread
  --threads 4`), *not* sync — even with X-Accel the app should not block a
  whole worker on slow downstream I/O. **[fixed]**
- **`X-Forwarded-Prefix` discipline**: every URL (`<audio src>`, art, API,
  X-Accel path) must be built with `url_for` so it respects the `/music`
  prefix. `ProxyFix(x_prefix=1)` + `APPLICATION_ROOT=/music` handle this
  exactly as in `calendar/app.py`. Getting this wrong = 404s on seek under the
  subpath. **[the #1 integration gotcha]**

---

## 7. Downloader (yt-dlp → beets → library)

The one feature no off-the-shelf server gives you; isolated as its own blueprint
+ background worker.

- **Page**: paste URL → `POST /downloads` creates a `download_jobs` row →
  returns immediately. Progress streamed to the browser via **SSE** (or poll
  the job row). Never run yt-dlp inside the request.
- **Worker**: v1 = a single background thread started at app boot, draining
  `download_jobs` FIFO. (A separate `flask download-worker` process / sidecar
  container is the cleaner §13 upgrade if downloads get heavy — keeps yt-dlp's
  ffmpeg CPU burst off the web workers.)
- **Pipeline** per job:
  1. `yt-dlp -x --audio-format mp3 --embed-thumbnail --embed-metadata
     --parse-metadata "%(artist)s - %(title)s"` into a staging dir.
  2. **`beets import`** (non-interactive, autotag via MusicBrainz) → fixes
     artist/album/track/art, writing into the writable `_downloads/` subtree
     (D2 index-in-place — never touches the read-only main library). This is the
     answer to the metadata pain point — far better than hand-rolled tag-fixing.
     **[fixed]**
  3. Trigger an incremental `scan` of the affected folder → track appears.
- **Pin + auto-update yt-dlp** — it breaks constantly as YouTube changes; a
  stale binary is the #1 cause of "downloads suddenly stopped." Plan a refresh
  (it's just a pip/binary bump). **[fixed: must keep current]**
- Keep it personal/private — ToS gray area at best.

---

## 8. Auth integration

Zero new auth code — reuse the established contract:

- Copy `calendar/proxy_auth.py` verbatim (`load_user_from_proxy_header`,
  `get_or_create_proxy_user`); wire the same `request_loader` in `create_app`.
- `AUTH_PROXY_HEADER=X-Forwarded-User` + `APPLICATION_ROOT=/music` env vars;
  omit both for standalone dev (local flask-login).
- Shadow users picked up via dashboard's
  `scripts/sync_household_users.py` (add `music` to its target list) **and**
  auto-created on first request.

---

## 9. Deployment

- **Port**: 5003 (library 5001, calendar 5002). **[fixed]**
- **compose service** in `dashboard/docker-compose.yml`, modeled on `calendar`:
  - `build: ../tapes`, `APPLICATION_ROOT=/music`,
    `AUTH_PROXY_HEADER=X-Forwarded-User`, `SECRET_KEY`.
  - volumes: `../tapes/instance:/app/instance` and the HDD music path,
    following library's convention (host path via env, fixed container path,
    app env points at the *container* target):
    `${MUSIC_HOST_DIR:-../tapes/music}:/data/music:ro` with `MUSIC_DIR=/data/music`
    (read-only, D2 index-in-place). On the Pi, `MUSIC_HOST_DIR=/mnt/backup/music`
    (alongside the existing `/mnt/backup/books`). The downloader needs a
    **separate writable mount** for its target, e.g.
    `${MUSIC_DOWNLOADS_DIR:-/mnt/backup/music/_downloads}:/data/music/_downloads`
    (no `:ro`) — beets writes there, the scanner picks it up, and the curated
    library stays untouchable.
  - **labels**: `homehub.enable=true`, `homehub.name=Music`,
    `homehub.route=/music/`, `homehub.icon=music`,
    `homehub.description="Streaming + yt-dlp downloads"` → dashboard tile, no
    registration code.
  - command: `flask db upgrade && gunicorn 'app:create_app()' --bind
    0.0.0.0:5003 --worker-class gthread --threads 4 --timeout 120`.
  - `/healthz` endpoint + healthcheck (copy calendar's).
- **nginx**: add a `/music/` block identical to `/calendar/`'s (auth_request +
  X-Forwarded-User + prefix headers) **plus** the `internal` `/_audio/`
  location for X-Accel:
  ```nginx
  location /_audio/ { internal; alias /data/music/; }
  ```
  This is the one piece library doesn't need: the music dir must **also** be
  bind-mounted into the **nginx** container (read-only) so nginx can read the
  files it serves — add `${MUSIC_HOST_DIR}:/data/music:ro` to the `nginx`
  service's volumes, not just the `music` service's.

---

## 10. Mobile path (later)

- **PWA first**: the web player, installable, with Media Session + offline
  shell. Reachable through the dashboard with the normal session cookie. Likely
  enough.
- **Native client**: authenticates with a **dashboard API token** (Bearer) —
  nginx already forwards `Authorization` to `/auth/verify`, which resolves it to
  `X-User`, so the token works through the proxy exactly like a session
  (`dashboard/README.md`, "API tokens for native apps"). No new auth surface.
- Tradeoff of DIY (vs Subsonic): existing third-party mobile clients won't
  work, since we don't speak Subsonic. Acceptable — we're building our own
  client. **Optional §13 escape hatch**: implement a minimal Subsonic-compatible
  API later to unlock the whole ecosystem of existing apps for free.

---

## 11. Pi / performance notes

- One user streaming 320 kbps MP3 over LAN is ~40 KB/s vs gigabit's ~100 MB/s —
  performance is a non-issue *if* bytes go via nginx (§6), not Python.
- The HDD: if it spins down, first-track-after-idle stalls on spin-up. Consider
  `hd-idle` tuning or keeping it awake. OS page cache makes repeats instant.
- The only CPU burst is the downloader's ffmpeg extraction — bursty, per
  download, off the playback path. Fine on a Pi.

---

## 12. Build stages

### Stage 1 — "the cassette plays" (standalone MVP) — ✅ DONE

The full pipe behind one screen: scan → pick a song → the cassette deck plays
it, reels turning, skin reflecting the track. Standalone (`flask run`, hot
reload — **no nginx / Docker / dashboard yet**), so the player can be iterated
fast.

> **As built:** realistic clear-shell cassette (orange band, sprocket reels,
> mechanism, INDEX label); Inter loaded via Google Fonts to match
> calendar/library. Two as-built simplifications vs the spec: `db.create_all()`
> instead of `flask-migrate` (add migrations when the schema first changes), and
> standalone auth auto-attaches a local user (no login form) rather than a local
> login.

- Scaffold from `calendar/` (`app.py`, `pyproject.toml`, `migrations/`,
  `/healthz`, the `tokens.css`/`primitives.css`/`index.css`/`player.css` split).
- **Minimal schema — `tracks` only**, denormalized to keep it simple: `id,
  file_path, file_hash, title, artist, album (nullable), duration_s, bitrate,
  cover_path, mtime, added_at`. (Normalize into `artists`/`albums` in Stage 3.)
- `flask scan`: walk the MP3 dir, mutagen tags + cover extraction → thumbnail
  cache (§4).
- **Streaming via `send_file(conditional=True)`** standalone — range/seek works
  without nginx. (Swaps to X-Accel in Stage 2; this is a build phase, not a
  permanent fallback.)
- **Cassette deck**: SVG/CSS cassette, reels spin gated on play/pause, label
  shows the current track's **cover art + title/artist** (the per-song "skin"),
  optional art-derived tint; transport (play/pause/next/prev), thin scrub line,
  HTML5 `<audio>`, Media Session.
- **Minimal navigator**: a searchable flat track list to choose songs + an
  ad-hoc queue. Collapses to leave just the cassette.
- Local auth; ad-hoc queue in memory (persist to `playstate` in Stage 3).

*Exit:* open standalone, search/pick a track, hit play, watch the cassette spin
and hear it stream.

### Stage 2 — into the home stack — 🟡 code-complete, not yet deployed/verified

- X-Accel path implemented (gated by `USE_X_ACCEL`); `proxy_auth.py` trusts
  `X-Forwarded-User`; `APPLICATION_ROOT`/`ProxyFix` prefix handling. **Wired into
  `../dashboard`:** `tapes` compose service, `/music/` + internal `/_audio/`
  nginx blocks, `homehub.*` labels, and a `music` entry in
  `sync_household_users.py`. ⏳ **Not yet run** — the stack only builds on the Pi
  (bare-name siblings collide with macOS `~/Library`/`~/Music`), so gated
  playback + prefix correctness await a Pi deploy. The dashboard edits are
  uncommitted in `../dashboard` pending review.

### Stage 3 — library structure + mixtapes — ⬜ next up

- Normalize `artists`/`albums`; add `playlists` (M2M) + `favorites` + `plays` +
  persisted `playstate` queue; the cassette **shelf** + virtual *All Tracks* /
  *Singles* tapes; richer browse.

### Stage 4 — downloader — ⬜ pending (pipeline proven by hand)

- The yt-dlp → mp3 + embedded-art flow works manually; still to build: the
  in-app downloader blueprint (`download_jobs`, SSE progress), the beets autotag
  step, `_downloads/` target + writable mount.

### Stage 5 — mobile — ⬜ later

- PWA polish; (later) native client on dashboard API tokens (§10).

---

## 13. Deferred (non-blocking) questions

The scaffold-gating decisions are in §0; these can be settled later without
reshaping the build.

- Watchdog auto-rescan vs cron `flask scan` — §4.
- Downloader worker: in-process thread (v1) vs sidecar process — §7.
- Cellular bitrate downscaling / HLS — out of v1, revisit if remote use grows.
- Subsonic-compatible API shim to unlock existing mobile clients — §10.
- beets config: how aggressive autotag/match-threshold should be before it
  asks vs accepts (non-interactive needs a sane default).
