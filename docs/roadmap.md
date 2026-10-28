# Tapes roadmap

Living plan for making tapes feel like a polished music product. MP3-only by
choice. Updated 2026-10-15, after the UX audit.

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
- **UX audit, all 44 findings** (2026-10-15; the audit itself is in git history):
  - phone layout library-first with a mini-player, bottom-sheet menus, 44px
    targets, draggable scrub bar;
  - in-app dialogs instead of `confirm()`/`prompt()`, a toast for every action,
    Undo for deletes (songs go to a 30-day trash), discard prompts on edits;
  - rip feedback: review cards with Play / Add to… / Edit, plain-language
    errors, duplicates explained; rips filed as `Artist/Album/NN Title.mp3`;
  - Needs-tidying shelf, album edit, artist rename with merge preview;
  - podcasts: ±15/30 s, speed, lock-screen seek, RSS streaming while it
    downloads, Hide (not delete) for followed shows;
  - chunked long lists, loading bar, remembered sort, library search,
    keyboard-reachable rows (the shortcut keys went on 2026-10-26: tapes is
    for phones);
  - installable PWA with an offline app shell; reconnects resume mid-song;
  - Flask-Migrate (migrations run on start), `tests/` + CI, Pi auto-deploy.
- **Gapless playback + volume levelling** (2026-10-16). Music plays on one
  MediaSource stream with each MP3's encoder delay and padding trimmed
  (sample-exact joins, measured), and through a Web Audio gain set from EBU
  R128 loudness: album gain for an album in order, track gain otherwise, true
  peak kept under -1 dBTP. Loudness and gapless info are measured on the
  server (on rip, plus a background pass) and written as ReplayGain tags.
  Tracks over 15 minutes, and far seeks in a song that hit the browser's
  memory limit, play the plain way. Podcasts keep a plain element (their
  streams can be cross-origin). Always on.

## Open loops

1. **Check the one mispointed tape.** An old DB incident (SQLite id reuse) left
   one tape's contents pointing at the wrong songs; the original mapping is
   unrecoverable, so clearing that tape is the honest fix.

## Next features (prioritised)

- **Recently played / Recently added rows** at the top of Music (the audit's
  one unbuilt suggestion; the remembered sort covers it for now). *effort: S*
- **Autoplay when the queue ends** (something similar, or the rest of the
  shelf). *effort: M*
- **Offline listening.** Cache chosen tracks and downloaded episodes in the
  service worker for no-connection playback (the app shell is already
  offline). Defining feature for a phone streamer. *effort: L*
- **Search podcasts from the shelf too.** `/` and the shelf field search the
  whole music library (client-side, over All Tracks); episodes are only
  searchable inside a show. Move search server-side if libraries outgrow it.
  *effort: M*

## Backlog / robustness

- **`--prune-covers`** housekeeping for orphaned cover thumbnails.
- **More tests** — `tests/` covers the API safety nets (edits, trash, rips,
  podcasts, metadata, migrations); the cleanup/sort/browse logic is still
  worth covering.
- **Hash-based track identity** — only if something starts reorganizing
  existing files (new rips are filed into folders, but nothing moves old
  ones): switch identity from `file_path` to `file_hash`, which already exists.
- **beets (shelved)** — possible future *interactive* enrichment tool only;
  not automated.
