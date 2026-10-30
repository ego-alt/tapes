# Polish pass

A refinement pass on branch `polish`: the structure, layouts and features are unchanged; what changed is whatever made the app look or feel unfinished. Everything outside the cassette is now flat near-black with engineered details (seams, recessed wells, engraved lines), things open out of a seam and close back into it, and hover is light rather than paint.

Screenshots of every state, at 1440×900 and 390×844, come from `scripts/shoot_states.py` (run against a scratch instance with `scripts/generate_samples.py`; it also captures slowed frames of openings and closings). Before/after pairs of the most visible changes are in `docs/polish/`.

## What changed

### Old floating and modal styles

- **Confirmation** (`docs/polish/confirm.png`): was a card over a dimmed screen. It's now a slot: inside the form it's about (in place of the form's buttons, a slot within the form's well), or under the list's bar like a menu (delete an episode, unfollow or delete a show, merge an artist). The scrim, card and modal styles are gone; the forms' `modal-` class names are now `form-`.
- **Up Next** (`docs/polish/up-next.png`): was a blurred pill with a drop shadow that opened a floating rounded card (a raised sheet on phones). It's now a flat bar at the deck's foot; the queue slides up out of a seam along its top edge as a well one step darker than the deck, on the shared spring, and shuts like every other drawer. The "UP NEXT" heading (repeating the bar) and the pill-shaped count went; rows are square and edge to edge.
- **Toasts** (`docs/polish/toast.png`): were floating rounded cards with a shadow, centred on the whole window (off-centre from the deck with the library open), and on phones they covered the mini-player. They're now a flat strip that rises out of the bottom edge (a seam along its top), cut at its resting edge so it emerges rather than floats; on desktop it's centred under the deck, and on phones it rises from the mini-player's top edge.

### Forms and menus

- **Duplicate names** (`docs/polish/duplicate-name.png`): adding a tape or show with a name that exists closed the slot, lost the text and showed a toast far away. The slot now stays open with the text, and the reason appears in the well under the field; typing clears it. Rip and Follow report a rejected link the same way.
- **Destructive items** (`docs/polish/row-menu.png`): "Delete from library", "Delete episode", "Delete tape", "Delete show" and "Unfollow" are red, so they no longer look like "Edit…".
- **Forms in wells** (`docs/polish/edit-form.png`): the song and album forms had bordered boxes and a filled orange Save. Their fields are now bare, with an engraved line that lights up in the accent while in use, like the slot's field; Save is an accent text action, "Choose image…" a quiet one. Two new variants in `controls.css` (`.input.bare`, `.btn-act`) keep one definition of each control.
- **Rows** (`docs/polish/row-menu.png`): every row highlight (hover, playing, the row whose menu is open) is now square and runs edge to edge, so an open menu's row reads as the drawer's lid rather than a rounded card above a square well.
- **Sort menu**: the chosen order is in the accent with a tick at the right, instead of a "✓" typed after the label.
- **Album form**: the hint "Leave blank to keep each song's artist" was cut off; it's now "Each song's own" under the label "Artist for every song".

### Bars and controls

- **Bar buttons**: search and + (open or hovered) sat in a filled grey block; now they just brighten.
- **Deck toggle**: the ☰ / ⌄ button on phones was a bordered box; now it's a plain icon (still 44px to tap).
- **Episode filters** (`docs/polish/show-filters.png`): All / Unplayed / Downloaded were rounded outlined pills, the only ones in the app; they now read like the library's tabs (words, the chosen one underlined in the accent).
- **Text actions** get square focus rings, matching the slots.

### Motion

- Closing + no longer flashes "Search your library" while it shuts (the field showed whenever the slot was empty).

### Details and states

- Empty states are all plain text now: the dashed first-run boxes ("No shows yet.", an empty library) became a line and a quieter line under it, like an empty tape; the library's first-run buttons became text actions.

- The playing song's ▸ marker was invisible inside albums (hiding its number shrank the marker too); it shows again.
- Download errors wrap to two lines instead of being cut off mid-sentence.
- An empty show said "Use Refresh", which doesn't exist; it now names the menu item ("Use ⋯ → Check for new episodes").
- The play buttons' icon colour and the mini-player's blank cover were raw colours; they're tokens now (`--color-on-accent`, `--color-label-paper`).
- The library's contents were 1px wider than the sidebar inside its border (since the slide fix on main), clipping right-aligned numbers by a pixel; fixed.
- The library's divider is engraved like a menu's.

All tests pass, including the style-token test, and the slot, navigation and menu checks from the earlier work still pass (navigation still ends pixel-identical to the real view).

## Left as it is

- **The confirmation focuses its action** (Discard, Delete), as the old dialog did, so Enter confirms (kept, by your decision).

- **The cassette, its label inks and the transport buttons** (round, raised): the cassette is the one physical object, and the deck's controls belong to it. Their raw colours in `player.css` are the printed label's inks.
- **Cover art corners**: album art keeps its small rounded corners, as covers do; the blank-cover placeholders match them.
- **Raw pixel sizes**: about 45 icon, touch-target and layout sizes are still written in px rather than tokens. The style test only covers font sizes, and moving them is mechanical with no visible change, so it's better as its own pass.
- **The deck's play button** stays a filled orange circle: it's the one main action on the deck, not a control in a well.
