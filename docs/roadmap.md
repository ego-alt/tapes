# Tapes roadmap

Living plan for making tapes feel like a polished music product. MP3-only by
choice. Updated 2026-06-15.

## Shipped

- **Sort toggle** in All Tracks / Singles — By artist / Recently added /
  Recently played / Most played (server-side, per-user).
- **Shuffle + repeat** (off / all / one), persisted, as icon toggles beside the
  list title.
- **Queue ops** — "Play next" and "Add to queue" in the `+` menu.
- **Up Next bottom bar** — replaces the old right-side queue panel. Only
  appears when something's queued; collapsed it's a slim bar previewing the next
  track + count, and it expands upward into the full queue (jump / drag-reorder /
  remove). Stays in sync with playback, shuffle, and queue edits.
- **Drag-to-reorder** — pointer-based (mouse + touch) reordering of user-tape
  track lists (persists to playlist order) and the Up Next queue.
- **Album & Artist browsing** — sidebar Albums/Artists → browse list (album
  covers / track counts) → track lists, with back-stack + browse search. Built
  on existing `artist`/`album`; no schema change.
- **Shelf separator** — hairline between the auto shelves and user tapes.
- **Deterministic metadata cleanup** — `cleaning.py` (`clean_title`/`clean_meta`):
  strips YouTube cruft, splits "Artist - Song" titles, distrusts label/uploader
  artists, preserves Chinese tags. Wired into the download worker; `flask retag`
  command (dry-run default, `--write` applies + rescans). Applied: 20/33 cleaned.

## Open loops (hygiene — do before more building)

1. **Browser-verify the browse UI.** Album/Artist browsing is API-verified but
   never clicked through in a real browser at desktop + mobile widths.
2. **Clear the mispointed favorites.** The earlier DB incident left 8 favorites
   + 1 playlist's contents pointing at the wrong songs (SQLite id reuse). The
   original mapping is unrecoverable; clearing them is the honest fix.

## Next features (prioritised)

### Tier 1 — completes what's started, high daily value
- **Quick player features.** Sleep timer (stop after N min / end of track),
  volume slider + mute (persisted), autoplay when the queue ends. *effort: M*

### Tier 2 — product feel
- **Replace native dialogs + add feedback.** Kill `confirm()` (delete-tape) and
  silent `.catch()` failures; add toasts ("Added to <tape>", errors) and a
  styled confirm. Biggest perceived-quality jump. *effort: M*
- **Polish details.** Loading skeletons, crafted empty states, view-switch /
  label-reskin transitions, draggable scrub bar with buffered + hover time.
  *effort: M*
- **Audio-error handling.** On a stream error, toast + auto-skip instead of a
  silent stall. *effort: S*

### Tier 3 — bigger bets
- **Installable PWA.** manifest + icons + service worker: home-screen install,
  standalone chrome, themed splash, offline shell. Strong "real product" signal
  on mobile. *effort: M–L*
- **Offline downloads.** Cache tracks via the service worker for no-connection
  playback. Defining feature for a phone streamer. *effort: L*
- **Global server-side search** across the whole library (today's search is
  client-side over the current list only), focusable with `/`, plus a `?`
  shortcuts overlay. *effort: M*

## Backlog / robustness

- **Adopt Flask-Migrate** (like the calendar/library siblings) to replace the
  raw `ALTER TABLE` hack in `app.py` — needed before the next schema change.
- **Downloader filename collisions** — `-o "%(title)s.%(ext)s"` can clobber; the
  "newest mp3" fallback is fragile under concurrency. Dedupe + safer naming.
- **`--prune-covers`** housekeeping for orphaned cover thumbnails.
- **Tests** — there are none; the cleanup/sort/browse logic is worth covering.
- **beets (shelved)** — optional future *interactive* enrichment tool only; not
  automated. See `beets-plan.md` for the Phase 0 findings.
- **Hash-based track identity** — only if we ever let something reorganize files
  (switch identity from `file_path` to `file_hash`, which already exists).

## Recommendation for the next session

Close the two open loops (cheap), then build the **Up Next queue panel** — it
finishes a feature that's currently half-visible and is used every listen.
