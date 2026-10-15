# Tapes — pre-launch product audit

Audited 2026-10-15 against `main` @ `bd95af8`.

**How I tested it:**
- I read all of the app code and ran it locally against a throwaway library, not your `music/` folder or database.
- The library held the five demo tracks, five deliberately awkward ones (a 150-character title, a file with no tags, a missing artist, Chinese characters, emoji) and, for the size tests, 3,000 extra catalogue rows.
- I drove it in Chrome through Playwright, at 1280×800 and as a 375×667 touch phone.
- Measurements quoted below come from those runs. Findings marked **[code]** come from reading the code, not from a test.

**Not exercised:**
- Real rips: `yt-dlp` isn't installed on this machine, so only the error path ran.
- Real podcast feeds: I didn't add any, to avoid downloading.
- iOS keyboard behaviour, which can't be emulated.

The cassette deck, the paper label, the Gruvbox palette and the orange accent are treated as intentional throughout. Nothing below asks to make Tapes look like Spotify. The goal is that it behaves like an app you'd trust with your music.

Each finding uses the same layout:

> **What** — the problem · **Where** — the file or screen · **Why** — why it matters · **Fix** — the suggested fix

---

## 1. Core purpose

Tapes' job is to **collect songs and podcasts I own, keep their metadata clean, and play them anywhere, cassette-style**. Most of the app serves that. These parts get in its way.

**1.1 The docs still advertise favorites**
- **What:** Favorites were removed on purpose (they weren't useful), but the README still lists them in three places. The roadmap's open loop about "mispointed favorites" now refers to a feature that no longer exists.
- **Where:** `README.md` (features, browse list, home-stack note); `docs/roadmap.md` open loop 2
- **Why:** Small, but the README is the app's front page. Promising a feature that's gone makes the rest of it harder to trust.
- **Fix:** Remove favorites from the README, and close or delete that roadmap item. If the data still has old favorite rows or tables, drop them in the same change.

**1.2 Podcasts borrow the music vocabulary**
- **What:** In Podcasts mode, the create form says "New tape…", the show screen says "Delete tape", and filing an episode says "Add to tape…" with a "New tape name:" prompt. The API and code call these *shows*.
- **Where:** `templates/index.html` `#newShowForm`, `#showDelBtn`; `player.js` `openAssignMenu`
- **Why:** A tape is a mixtape you curate. A show is something you follow. Using one word for both blurs the two halves of the app.
- **Fix:** Use *show* throughout Podcasts: "New show…", "Unfollow show", "Move to show…". Keep *tape* for music.

**1.3 One hidden "⬇" panel does two different jobs**
- **What:** The ⬇ glyph (tooltip "Add") opens a URL field that rips a song in Music mode and follows a feed in Podcasts mode. Nothing on screen says which.
- **Where:** `#dlToggle`, `#dlPanel`
- **Why:** Adding music is the main way the library grows. It's behind an unlabeled download arrow that reads as "download this". The podcast empty state even says "paste … above", pointing at a field that isn't visible.
- **Fix:** Use a labelled **+ Add** button in each mode's header, opening a field titled for the mode: *Rip a song or playlist* / *Follow a podcast*. Keep the job list beneath it.

**1.4 "Singles" means "tracks with no album tag"**
- **What:** The Singles shelf is defined as `album IS NULL OR album = ''`. Real singles and badly tagged rips land in it together.
- **Where:** `routes/library.py` `_is_single`
- **Why:** As the library grows, Singles becomes a junk drawer with a friendly name.
- **Fix:** Keep Singles for tracks marked as singles. Route the untagged ones into a "Needs tidying" shelf (see 1.5).

**1.5 Metadata work is invisible**
- **What:** Several cleanup steps run silently on every rip: the deterministic cleanup, the Claude pass, the MusicBrainz art lookup and the fingerprint dedup. You never see what they changed. Tracks the Claude pass missed (`needs_llm`) and tracks with no cover, album or artist aren't surfaced anywhere. Editing is one track at a time. Renaming an artist is hidden behind clicking the list title.
- **Where:** `downloader.py`, `scan.py`, `player.js` `openTrackList`
- **Why:** "Mature metadata handling" is half the brief. Today it's mature on the server and opaque to you.
- **Fix:**
  - When a rip finishes, show a short review card: *"Saved as **Title** — Artist · Album, cover from MusicBrainz. Edit"*.
  - Add a **Needs tidying** shelf for missing artist, album or cover and for `needs_llm` tracks, with a "Tidy with AI" action.
  - Add album-level editing (rename, cover, artist across the album).
  - Give artist rename a visible pencil.

---

## 2. Missing states

**2.1 First run gives no guidance**
- **What:** With an empty library, the deck reads "insert a tape" and the shelf shows four zeros. On a phone the drawer starts closed, so you see only an empty cassette.
- **Where:** first launch, `player.js` init
- **Why:** The very first moment gives no next step.
- **Fix:** When the library is empty, put a card under the deck: *"Your shelf is empty. Rip a song from a link, or follow a podcast."* with the two Add actions from 1.3.

**2.2 Failed rips vanish without a word** (bug, confirmed)
- **What:** The job stream only lists *queued* and *running* jobs, so a job that errors drops out within a second. I submitted a non-video link: it appeared as its URL, then disappeared. No toast, no message. The stored error ("yt-dlp failed (see server log)") is never shown.
- **Where:** `routes/downloads.py` `_active_jobs`; `player.js` `handleJobs`
- **Why:** You can't tell a failed rip from one still in progress, and you won't know to try another link.
- **Fix:** Keep finished and failed jobs in the list for the session, with a clear outcome per row (see 6), dismissible. Show a toast for failures.

**2.3 Successful rips and dedups aren't confirmed either** (confirmed)
- **What:** A finished rip also drops out of the list. The only sign is a shelf count changing. The dedup results ("already in library: X", "duplicate of: X") are written to the job and never displayed.
- **Where:** same as 2.2
- **Why:** You paste a link and nothing tells you whether you now have the song, or already did.
- **Fix:** Show *"Added **Title** — Play · Show"* (or *"You already have **Title**"*), and highlight the new row.

**2.4 Unplayable tracks fail silently** (confirmed)
- **What:** I played a track whose file is missing. The label showed its title, the audio failed, and nothing else happened: no toast, no skip. The `error` handler only reports podcast episodes.
- **Where:** `player.js` `audio` `error` listener
- **Why:** On a phone in a pocket, playback just stops.
- **Fix:** Show a toast (*"Couldn't play **Title** — skipping"*) and move to the next track. Mark the row as unavailable.

**2.5 Errors arrive as HTML pages**
- **What:** Every `abort(400, "…")` returns Flask's HTML error page, for example `couldn't read that feed: not a readable RSS feed`. `jsend` throws a generic error, so the user sees "Couldn't add that — check the URL." or "Something went wrong — please try again."
- **Some actions have no error handling at all:** adding to a tape, creating a tape, deleting a tape, submitting a rip. Their failures fall through to the global "Something went wrong".
- **Where:** all `routes/*.py`; `player.js` `jsend`
- **Fix:** Return JSON errors (one `errorhandler`) with human messages (see 6), and show the server's message in the toast.

**2.6 No offline story**
- **What:** There's no service worker or manifest (and no favicon; the only 404s in the logs were `/favicon.ico`). When the connection drops mid-song, the deck stalls with no message.
- **Why:** This is meant to replace a streaming app on a phone.
- **Fix:** Covered in the roadmap's PWA and offline items. At minimum, show *"Offline — reconnecting"* on stall, and keep downloaded podcast episodes playable.

**2.7 Long titles can't be read anywhere** (confirmed)
- **What:** Titles are cut with "…" in lists, on the deck label and in Up Next. A 150-character test title showed as "The Extraordinarily L…" in the list and "The Extraordinarily Long and Windin…" on the label. Nothing shows the full text: no `title` attribute, no marquee.
- **Also:** on narrow screens the "INDEX" stamp overlaps the first line of the label.
- **Where:** `.tl-title`, `#labelTitle`, `.q-title`
- **Fix:**
  - Lists: add a `title` attribute and allow two lines.
  - Deck label: a slow, label-appropriate scroll on hover or tap, or wrap to two lines in a smaller hand-lettered size.
  - Move "INDEX" out of the title's line.

**2.8 Untagged tracks fall through the cracks** (confirmed)
- **What:** A file with no tags shows its filename as the title and an empty second line. No "Unknown artist", and no artist, album or year at all. It doesn't appear under Artists or Albums, so it can only be found by scrolling All Tracks or searching.
- **Where:** `scan.py` defaults; `routes/library.py` `artists`/`albums`
- **Fix:** Show "Unknown artist" in muted italics, and list such tracks in the Needs tidying shelf (1.5).

**2.9 Huge collections render everything at once** (measured)
- **What:** With 3,010 tracks, opening All Tracks builds all 3,010 rows: 1.1–1.2 s on a fast Mac, so likely several times that on a phone. Search re-renders the whole list on every keystroke (0.14 s here). It only searches the list you have open; there's no library-wide search.
- **Where:** `player.js` `renderTracks`, `applySearch`
- **Fix:** Render the visible window only (virtual list, or chunks of ~100 on scroll), and debounce search. Add a global search (see 8.4).

**2.10 No loading states**
- **What:** Opening a list, an album or a show shows nothing until the data arrives.
- **Fix:** Fade in a few skeleton rows after about 150 ms, and keep the previous list dimmed rather than blank.

**2.11 Things that should be hidden show anyway** (bug, confirmed)
- **What:** The app hides elements with the `hidden` attribute, but nothing forces `[hidden]` to `display: none`. Any element styled as a `.btn` or flex box stays visible. Confirmed cases:
  - "Up Next" shows with an empty queue, on desktop and phone;
  - "Delete tape" shows on All Tracks. Tapping it asks to delete "All Tracks" and then fails.
- **Same root cause, from the code [code]:** "Refresh" on shows that can't refresh, and "Delete tape" on Loose episodes.
- **Where:** `static/css/index.css` (only some views have `[hidden]` overrides), `player.css` `.upnext`
- **Fix:** One global rule, `[hidden] { display: none !important; }`.

---

## 3. Inconsistency within the app

**3.1 Two icon systems**
- **What:** Transport, shuffle, repeat, sleep and row buttons use a clean inline-SVG set. The shelf, mode toggle and other controls use Unicode glyphs (▤ ♪ ◉ ♫ ▰ ◎ ⬇ ☰ ✓ ○ ✕ ⠿ ‹), which render at different sizes and weights on each platform.
- **Where:** `player.js` `loadShelf`, `renderEpisodes`, `renderQueue`; `index.html`
- **Fix:** Draw the remaining glyphs in the existing `ICONS` set.

**3.2 Five empty-state voices**
- **What:** "Empty.", "Nothing here yet.", "No episodes.", "Queue is empty." and one helpful one ("No podcasts yet. Paste an RSS or YouTube URL above.").
- **Fix:** One voice, each saying what to do next (see 6).

**3.3 Two kinds of dialog**
- **What:** Edit uses a styled in-app modal. Delete track, delete tape, delete show and delete episode use the browser's `confirm()`, and naming a show uses `prompt()`.
- **Fix:** Replace confirms with Undo (see 4.3). Use the in-app modal style for naming.

**3.4 Feedback depends on which half of the app you're in**
- **What:** Podcast actions confirm themselves ("Added to …", "Download removed", "No new episodes"). Music actions don't: adding to a tape, queueing, creating or renaming a tape, deleting a track and renaming an artist are all silent. Adding a song that's already on the tape is silently ignored.
- **Fix:** Toast every outcome in the same style: *"Added to Road trip"*, *"Already on Road trip"*, *"Queued — plays after this"*.

**3.5 Words for the same things**
- **What:** The rip button is "Get" while the podcast one is "Add". There are three delete phrasings: "Delete from library", "Delete episode", "Delete tape". Subtitles use "·" in lists but "—" on the deck label.
- **Fix:** One verb per action, and one separator.

**3.6 Track rows show no duration**
- **What:** Episode rows show date and length. Track rows show neither, though the data has a duration.
- **Fix:** Add the duration, right-aligned in the mono face the timer uses.

---

## 4. Fragility

**4.1 Editing any field erases the track number** (bug, confirmed: data loss)
- **What:** The edit dialog fills its Track # field from `t.track_no`, but `Track.to_dict()` never sends `track_no`, so the field always opens blank. Saving sends an empty value, and the server stores `None` in both the database and the MP3 tag. In the test, "Warm Static" was track 1. After I changed only its title, its track number was gone.
- **Where:** `models.py` `Track.to_dict`; `player.js` `openEdit`/`saveEdit`; `routes/library.py` `update_track`
- **Fix:** Include `track_no` in `to_dict`. Only send fields the user actually changed.

**4.2 The only way to take a song off a tape deletes it from the library** (confirmed)
- **What:** Inside a tape, a row's "⋯" menu offers *Edit details…* and *Delete from library*. There's no *Remove from tape*. The API route exists (`DELETE /api/playlists/<id>/tracks/<track>`), but nothing in the UI calls it.
- **Why:** Tidying a mixtape means permanently deleting the file for everyone in the household.
- **Fix:** On a tape, put **Remove from tape** first and move *Delete from library* below a divider.

**4.3 Deleting from the library is permanent, and anyone can do it**
- **What:** *Delete from library* unlinks the MP3 and wipes its tape links and play history after a browser `confirm()`. There's no undo or trash. The catalogue is shared, so any household member can delete (or edit, or rename the artist of) anyone's music.
- **Where:** `routes/library.py` `delete_track`, `update_track`, `rename_artist`
- **Fix:**
  - Move deleted files to `MUSIC_DIR/.trash/` with an Undo toast, and purge after 30 days.
  - Consider limiting library-wide delete and artist rename to an admin.

**4.4 Closing the tab loses your place** (bug, confirmed)
- **What:** `beforeunload` calls `savePlaystate()`, which only *schedules* a save 400 ms later. The page is gone before it fires. In the test: playing at 14.5 s, close the tab, saved position `0.0`. Music position is otherwise saved only on pause, seek and track change.
- **Where:** `player.js` `savePlaystate`, `beforeunload`
- **Fix:** On `pagehide`/`visibilitychange`, send the position immediately with `navigator.sendBeacon`. Also save every ~10 s while playing.

**4.5 Artist rename can silently merge into someone else**
- **What:** Renaming an artist snaps the new name onto any existing spelling it resembles (`reconcile_artist`) without saying so. The tag rewrite runs in a background thread whose failures only reach the server log. There's no undo. The rename itself is reached by clicking the list title, which looks like a heading.
- **Fix:**
  - Show what will happen: *"Merge 12 tracks into **The Reels** (already 30 tracks)?"*
  - Confirm when the tag writes finish, and offer Undo.
  - Give the rename a visible pencil.

**4.6 Tape names save on blur**
- **What:** Tape titles are edited in place (`contentEditable`) and commit when focus leaves. A stray tap renames the tape, with no confirmation.
- **Fix:** Save only on Enter or a ✓ button; Esc or tapping away cancels. Toast *"Renamed to …"*.

**4.7 Rips can collide on filename** **[code]**
- **What:** Every rip is saved flat as `MUSIC_DIR/<raw YouTube title>.mp3`, so two different videos with the same title collide. The fallback that picks "the newest MP3 in the folder" breaks if two rips finish together. In a collision, the cleanup can re-tag the *existing* file with the new song's metadata. The roadmap already lists this.
- **Where:** `downloader.py` `_process`
- **Fix:** Rip into a temp dir named by job id, then move to `Artist/Album/NN Title.mp3` after tagging, adding a suffix on collision.

**4.8 Podcast deletes behave unexpectedly**
- **What:** Deleting a show deletes every downloaded episode (the confirm does say so). Deleting an episode from a followed show brings it back as new on the next refresh, which the code notes but the UI doesn't explain.
- **Fix:** Offer *Mark as played* or *Hide* instead of delete for followed shows, and keep delete for loose episodes.

**4.9 Edits can be lost by tapping outside**
- **What:** Tapping the backdrop closes the edit dialog and discards any changes.
- **Fix:** Ask *"Discard changes?"* when fields changed.

**4.10 Schema changes fail silently** **[code]**
- **What:** New columns are added by "best-effort" `ALTER TABLE` statements that swallow every error, as the roadmap notes.
- **Fix:** Adopt Flask-Migrate like library and calendar, so a failed schema change stops startup instead of drifting.

---

## 5. Friction

### Most common task: play something specific on your phone

| # | Step | Friction |
|---|---|---|
| 1 | Open Tapes | Good: the deck restores your last track. But if you closed the tab mid-song, it starts from 0:00 (4.4). |
| 2 | Tap ☰ | The library is a drawer over the deck. There's no "what's playing" or play/pause while browsing. |
| 3 | Tap All Tracks | Opens sorted *By artist* every time, even if you last chose *Recently added*. 3,000 tracks build in one go (2.9). |
| 4 | Find the song | Search covers only this list. There's no library-wide search and no "Recently played" shortcut. |
| 5 | Tap it | The drawer closes and it plays. Good. |
| 6 | Add it to a tape | **Impossible on a phone:** the + and ⋯ menus open behind the drawer (7.1). |
| 7 | Skip ahead in it | The scrub bar is 6 px tall and click-only, with no drag (7.3). |

**Fixes:**
- Make the phone layout library-first, with a **mini-player bar** (art, title, play/pause) that's always visible and opens the full deck (7.6).
- Remember the sort per shelf, and add *Recently played* and *Recently added* rows at the top of Music.
- Fix the menus (7.1).

### Second task: rip a song and play it

1. Tap the unlabeled ⬇.
2. Paste the link and tap "Get". The job shows as the raw URL until yt-dlp names it.
3. When it finishes, it **disappears**: no confirmation, no "Play" (2.3). If it failed, it also just disappears (2.2).
4. To find it, open All Tracks, change the sort to *Recently added*, and tap it.
5. If the metadata is wrong, ⋯ → Edit (desktop only, given 7.1), which also erases the track number (4.1).

**Fix:** After a rip, show the 1.5 review card with **Play now**, **Add to tape** and **Edit**. Ripping into a tape should go straight there.

### Third task: listen to a new podcast episode **[code]**

- An RSS episode must download completely before it plays: *"Downloading episode…"*, then it auto-plays when done. Streaming the enclosure URL directly while it downloads would make it play instantly.
- Once playing, there's no **skip back 15 s / forward 30 s**, no **playback speed**, and the lock screen only has previous/next (8.1).

---

## 6. Copy

| Where | Now | Suggested |
|---|---|---|
| Add button | ⬇ with tooltip "Add" | **+ Add** (label visible) |
| Rip field / button | "Paste a URL to rip…" / "Get" | "Paste a song or playlist link…" / **Rip** |
| Rip failed (`downloader.py`) | "yt-dlp failed (see server log)", "no mp3 produced" | "Couldn't rip that link — it may be private, region-locked or not a video." |
| Rip skipped (exact) | "already in library: X" | "You already have “X”" (+ "added to *Tape*" when ripping into one) |
| Rip skipped (fingerprint) | "duplicate of: X" | "Same recording as “X” — kept the one you have" |
| Bad URL (server) | "valid url required" | "Paste a full link starting with https://" |
| Bad feed (server) | "couldn't read that feed: not a readable RSS feed" | "That link isn't a podcast feed. Try the show's RSS link or a YouTube channel." |
| Refresh failed | "refresh failed: {exception}" | "Couldn't check for new episodes. Try again later." |
| Generic error | "Something went wrong — please try again." | The specific action: "Couldn't add to Road trip" / "Couldn't create the tape" |
| Empty tape | "Empty." | "This tape is empty. Tap + on any song to add it here." |
| Empty browse | "Nothing here yet." | "No albums yet — they appear as you add tagged songs." |
| Empty show | "No episodes." | "No episodes yet. Pull to check for new ones." / filtered: "No unplayed episodes." |
| Empty queue | "Queue is empty." | "Nothing up next. Use + → Queue on any song." |
| Podcast empty state | "…Paste an RSS or YouTube URL above." (field hidden) | "Follow a show: tap **+ Add** and paste its RSS or YouTube link." |
| Podcasts create field | "New tape…" | "New show…" |
| Episode menu | "Add to tape…" / prompt "New tape name:" | "Move to show…" / in-app field "Show name" |
| Show screen | "Delete tape" | "Unfollow show" |
| Loose episodes | "Loose episodes" | "Unsorted episodes" |
| Episode subtitle | "not downloaded" | "Not downloaded yet" |
| Refresh in progress | "…" | "Checking…" |
| Delete track confirm | `Delete "X" from the library? This removes the file.` | Undo toast: "Deleted “X” · Undo" (4.3) |
| Nav toggle tooltip | "Toggle navigator" | "Library" |
| Unlabeled controls | ⬇, shelf glyphs, ⠿ handles, ✕ in queue | `aria-label`s: "Add", "Reorder", "Remove from queue" |
| Deck, empty | "insert a tape" | Keep. It's the right voice, and the empty-state card (2.1) can carry the instructions. |

---

## 7. Mobile (375px, touch)

**7.1 Track and episode menus open behind the drawer** (bug, confirmed: critical)
- **What:** Popover menus are `z-index: 20`; the phone drawer is `z-index: 30`. Tapping **+** or **⋯** on a row opens the menu underneath the list, and the tap lands on the row behind it. On a phone you can't add to a tape, queue, edit, delete, or use any episode menu.
- **Where:** `static/css/index.css` `.menu` vs the 640px drawer rule
- **Fix:** Raise menus above the drawer (`z-index: 40`). Better still, show them as bottom action sheets on phones (7.6).

**7.2 Small tap targets** (measured; goal is 44×44)

| Control | Size |
|---|---|
| Row **+** and **⋯** | 24×24 |
| Queue drag handle / remove | 16×21 / 22×23 |
| Shuffle / repeat | 30×30 |
| Menu items | 33 tall |
| ⬇ Add | 34×42 |
| Music / Podcasts tabs | 36 tall |
| Shelf rows | 36–40 tall |
| Up Next bar | 35 tall |
| Scrub bar | **6 tall** |

**Fix:** At ≤640px, make row buttons, menu items and handles at least 44px. Give the scrub bar a 44px invisible hit area around its 6px line.

**7.3 The scrub bar only accepts clicks**
- **What:** You can tap a position but not drag. There's no handle, no hover time and no buffered indicator (the roadmap lists this).
- **Fix:** Pointer-drag with a visible thumb while dragging, and show the time under your finger.

**7.4 The keyboard covers inputs [code]**
- **What:**
  - The edit dialog is centred (measured y 134–534 on a 667px screen), so an iPhone keyboard covers its Save button.
  - The "New tape…" field sits pinned to the bottom of the drawer, where the keyboard will cover it.
- **Fix:** On phones, make the edit dialog a top-anchored or full-height sheet with Save in its header. Move "New tape" to a + in the shelf header.

**7.5 Notch, home bar and zoom [code]**
- **What:**
  - The drawer's bottom "New tape" form has no `safe-area-inset-bottom` padding, so it sits under the home indicator on iPhones.
  - The viewport sets `maximum-scale=1`, which blocks pinch-zoom for anyone who needs it.
- **Fix:** Pad the drawer's bottom with `env(safe-area-inset-bottom)`, and drop `maximum-scale=1`.

**7.6 The phone layout should change structure, not just shrink**
- **What:** On a phone the library is a drawer over the deck. While browsing you can't see or control what's playing. Up Next is a small floating card over the deck. Menus are tiny popovers.
- **Fix:**
  - Make the library the main phone screen, with a **mini-player bar** at the bottom (label art, title, play/pause; tap to open the deck).
  - Make the deck a full-screen "now playing" view with the cassette.
  - Make Up Next a bottom sheet, and row menus bottom action sheets.

**7.7 Desktop keyboard can't reach row actions**
- **What:**
  - Rows aren't focusable (`tabIndex -1`), so you can't Tab through the list.
  - The row **+** and **⋯** buttons are hover-only (`opacity: 0`); measured opacity when focused by keyboard: 0.
- **Fix:** Make rows focusable (Enter plays), and show row buttons on `:focus-within`.

---

## 8. Speed and feel

**8.1 Podcast and lock-screen controls are thin**
- **What:**
  - The Media Session only handles previous and next. There's no seek, skip-back or skip-forward, so lock-screen scrubbing doesn't work.
  - There's no ±15/30 s skip in the app, no playback speed, and no volume or mute (the roadmap lists volume).
- **Fix:**
  - Add `seekto`, `seekbackward` and `seekforward` handlers.
  - Add ↺15 / 30↻ buttons and a speed toggle (1×, 1.25×, 1.5×, 2×), shown only for episodes, styled as deck buttons.

**8.2 Missing instant feedback**
- **What:** Several actions give no sign they worked:
  - adding to a tape, queueing, creating or renaming a tape, and artist rename (3.4);
  - a rip until yt-dlp's first output line;
  - finished rips (2.3).
- **Fix:** Toast every outcome immediately. Add the rip job row with its link the instant you submit, marked *"Starting…"*.

**8.3 Lists are slow to open at scale and show no loading state**
- **What:** See 2.9 and 2.10.
- **Fix:** Render only the visible rows, and show skeleton rows while loading.

**8.4 Keyboard shortcuts are minimal**
- **What:** Only Space and Shift+←/→ exist. In testing, plain → didn't seek, and `/` didn't focus search.
- **Fix:** ←/→ seek 5 s (10 s for episodes), ↑/↓ volume, `M` mute, `/` library-wide search, `Q` toggle Up Next, `S` shuffle, `R` repeat, `?` shortcut sheet.

**8.5 Sort resets every time you open a shelf**
- **What:** `openTape` resets the sort to *By artist*.
- **Fix:** Remember the last sort per shelf.

---

## Top 10, ranked by how much better the app will feel

| Rank | Fix | Section | Size |
|---|---|---|---|
| 1 | **Make phones work:** menus above the drawer, plus one global `[hidden]` rule (fixes ghost "Delete tape", "Refresh" and "Up Next") | 7.1, 2.11 | **Small** |
| 2 | **Stop losing data:** keep track numbers on edit, add *Remove from tape*, save position on close (`sendBeacon`) | 4.1, 4.2, 4.4 | **Small** |
| 3 | **Tell me what happened to my rip:** keep finished and failed jobs, show dedups, review card with Play / Edit, human error copy, JSON errors | 2.2, 2.3, 2.5, 1.5, 6 | **Medium** |
| 4 | **Phone layout:** library as the main screen with a mini-player, full-screen deck, bottom sheets for Up Next and menus, 44px targets, draggable scrub | 7.6, 7.2, 7.3, 7.4 | **Large** |
| 5 | **Undoable delete and a trash**, with destructive library actions limited to an admin | 4.3, 4.5 | **Medium** |
| 6 | **Podcast listening basics:** ±15/30 s, speed, lock-screen seek, stream RSS episodes while they download | 8.1, 5 | **Medium** |
| 7 | **Visible metadata care:** Needs-tidying shelf, album-level edit, visible artist rename with a merge preview | 1.5, 1.4, 2.8 | **Large** |
| 8 | **Reassuring first run and failures:** a first-run card on the deck, skip unplayable tracks with a message, remove the stale favorites docs | 2.1, 2.4, 1.1 | **Small** |
| 9 | **One voice:** shows vs tapes, SVG icons everywhere, toasts for every action, empty states that say what to do | 1.2, 3.1–3.5, 6 | **Medium** |
| 10 | **Speed and keys:** windowed lists, loading states, remembered sort, library-wide search, shortcut set | 2.9, 2.10, 8.4, 8.5 | **Medium** |

Close runners-up:
- **Collision-safe rip filenames in `Artist/Album/` folders** (4.7, medium).
- **Installable and offline** (2.6, large; already on the roadmap).
