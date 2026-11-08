# Tapes roadmap

What's left to do. What's built is in the README; how it got there is in git history.

## Open loops

- **Check the one mispointed tape.** An old database incident (SQLite id reuse) left one tape's contents pointing at the wrong songs; the original mapping is unrecoverable, so clearing that tape is the honest fix.

## Next

- **Offline listening.** Keep chosen tracks and downloaded episodes on the phone for no-connection playback (the app shell already works offline; audio is never cached). The defining feature for a phone streamer. *Large.*
- **Recently played / Recently added rows** at the top of Music (the remembered sort covers it for now). *Small.*
- **Search podcasts from the shelf too.** The shelf searches the whole music library; episodes are only searchable inside a show. Move search to the server if libraries outgrow the browser. *Medium.*

## Backlog

- **`--prune-covers`**: housekeeping for orphaned cover thumbnails.
- **More tests** for the cleanup, sort and browse logic (the API's safety nets are covered).
- **Hash-based track identity**, only if something starts reorganising existing files: switch identity from `file_path` to `file_hash`, which already exists.
- **beets** (shelved): possibly a future interactive enrichment tool, never automated.
