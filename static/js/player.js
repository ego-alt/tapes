(() => {
  const M = window.MUSIC;
  const $ = (id) => document.getElementById(id);
  // Music plays gapless and levelled; podcasts on their own element (deck-audio.js).
  const audio = new DeckAudio($("audio"), $("episodeAudio")), cassette = $("cassette");
  const labelArt = $("labelArt"), labelTitle = $("labelTitle"), labelArtist = $("labelArtist");
  const playBtn = $("playBtn");
  const scrub = $("scrub"), scrubFill = $("scrubFill"), curTime = $("curTime"), durTime = $("durTime");
  const app = $("app");
  const sidebar = document.querySelector(".sidebar");

  const streamUrl = (id) => M.streamBase + id;
  const coverUrl = (id) => M.coverBase + id;
  // Polymorphic source/art: a track plays from the music endpoints, an episode
  // (kind === "episode") from the podcast ones. Everything else in the player
  // works on these two helpers so the queue/deck can hold either.
  // An RSS episode that isn't downloaded yet streams straight from the feed's
  // audio URL while the download runs in the background.
  const canStreamRemote = (t) => t.kind === "episode" && t.status !== "ready"
    && t.source_type === "rss" && /^https?:/.test(t.source_url || "");
  const srcUrl = (t) => t.kind === "episode"
    ? (canStreamRemote(t) ? t.source_url : M.epStreamBase + t.id)
    : streamUrl(t.id);
  const artUrl = (t) => t.kind === "episode"
    ? (t.show_id ? M.epEpisodeCoverBase + t.id : null)
    : (t.has_cover ? coverUrl(t.id) : null);
  // The line under a song's title: the show for an episode, else artist · album.
  const subLine = (t) => t.kind === "episode" ? (t.show || "Podcast")
    : [t.artist || "Unknown artist", t.album].filter(Boolean).join(" · ");
  const fmt = (s) => {
    if (!s || !isFinite(s)) return "0:00";
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const pad = (n) => String(n).padStart(2, "0");
    // Hours only when needed, so 3-min songs stay "3:14" and long episodes read "4:14:13".
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  };

  // toast("Saved") or toast("Deleted …", { action: "Undo", onAction }) — a
  // toast with an action stays up longer so there's time to use it.
  function toast(msg, { action, onAction } = {}) {
    const t = document.createElement("div");
    t.className = "toast";
    t.setAttribute("role", "status");
    const text = document.createElement("span");
    text.textContent = msg;
    t.appendChild(text);
    const dismiss = () => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); };
    if (action) {
      const b = document.createElement("button");
      b.className = "toast-action";
      b.textContent = action;
      b.addEventListener("click", (e) => { e.stopPropagation(); dismiss(); onAction(); });
      t.appendChild(b);
    }
    document.body.appendChild(t);
    requestAnimationFrame(() => t.classList.add("show"));
    setTimeout(dismiss, action ? 8000 : 3200);
  }

  // ---------- the back gesture ----------
  // Android's back (and the browser's) closes what's open, top layer first,
  // instead of leaving the app. History keeps one entry per open layer, put
  // back in line after every tap or key and whenever something opens.
  // (Live once the page has set up: the layers below are defined further on.)
  const layers = () => [   // topmost first: [is it open?, close it]
    [() => !$("confirmModal").hidden, () => $("confirmCancel").click()],
    [() => !$("nameModal").hidden, () => $("nameCancel").click()],
    [() => !$("albumModal").hidden, () => $("alCancel").click()],
    [() => !$("editModal").hidden, () => dismissEdit()],
    [() => !menu.hidden, closeMenu],
    [() => !deckMenu.hidden, closeDeckMenu],
    [() => upnext.classList.contains("expanded"), () => upnext.classList.remove("expanded")],
    [() => app.classList.contains("immersive"), () => DeckFX.setImmersive(false)],
    [() => isMobile() && app.classList.contains("deck-open"), closeDeck],
    [() => !$("dlPanel").hidden, () => $("dlToggle").click()],
    [() => !$("tracksView").hidden, () => $("backBtn").click()],
    [() => !$("browseView").hidden, () => $("browseBack").click()],
    [() => !$("episodesView").hidden, () => $("epBack").click()],
  ];
  let historyLive = false, historyDepth = 0, ignoredPops = 0;
  function syncHistory() {
    if (!historyLive) return;
    const open = layers().filter(([isOpen]) => isOpen()).length;
    while (historyDepth < open) history.pushState({ tapesLayer: ++historyDepth }, "");
    if (historyDepth > open) { ignoredPops++; history.go(open - historyDepth); historyDepth = open; }
  }
  window.addEventListener("popstate", () => {
    if (ignoredPops) { ignoredPops--; return; }
    historyDepth = Math.max(0, historyDepth - 1);
    layers().find(([isOpen]) => isOpen())?.[1]();
    setTimeout(syncHistory, 0);
  });
  ["click", "keydown", "touchend"].forEach((ev) => document.addEventListener(ev, () => setTimeout(syncHistory, 0), true));

  // In-app name field: resolves the trimmed name, or null if cancelled.
  function askName(title, { label = "Name", ok = "Create", value = "" } = {}) {
    return new Promise((resolve) => {
      $("nameTitle").textContent = title;
      $("nameLabel").textContent = label;
      $("nameOk").textContent = ok;
      $("nameInput").value = value;
      $("nameModal").hidden = false;
      $("nameInput").focus();
      syncHistory();
      const done = (v) => {
        $("nameModal").hidden = true;
        $("nameForm").onsubmit = $("nameCancel").onclick = $("nameModal").onclick = null;
        resolve(v);
      };
      $("nameForm").onsubmit = (e) => { e.preventDefault(); const v = $("nameInput").value.trim(); if (v) done(v); };
      $("nameCancel").onclick = () => done(null);
      $("nameModal").onclick = (e) => { if (e.target === $("nameModal")) done(null); };
    });
  }

  // In-app confirm: resolves true/false. `danger` styles the OK button red.
  function askConfirm(text, { detail = "", ok = "OK", danger = false } = {}) {
    return new Promise((resolve) => {
      $("confirmText").textContent = text;
      $("confirmDetail").textContent = detail;
      $("confirmOk").textContent = ok;
      $("confirmOk").classList.toggle("danger", danger);
      $("confirmModal").hidden = false;
      $("confirmOk").focus();
      syncHistory();
      const done = (v) => {
        $("confirmModal").hidden = true;
        $("confirmOk").onclick = $("confirmCancel").onclick = $("confirmModal").onclick = null;
        document.removeEventListener("keydown", onKey, true);
        resolve(v);
      };
      const onKey = (e) => {
        if (e.key === "Escape") { e.stopPropagation(); done(false); }
        if (e.key === "Enter") { e.preventDefault(); done(true); }
      };
      $("confirmOk").onclick = () => done(true);
      $("confirmCancel").onclick = () => done(false);
      $("confirmModal").onclick = (e) => { if (e.target === $("confirmModal")) done(false); };
      document.addEventListener("keydown", onKey, true);
    });
  }
  // Both throw on a non-2xx or network failure so callers (and the global
  // unhandledrejection handler) can surface it instead of silently dying. The
  // error carries the server's plain-language message as .userMessage.
  async function failure(r, what) {
    const err = new Error(`${what} → ${r.status}`);
    try { err.userMessage = (await r.json()).error; } catch (_) { /* not JSON */ }
    return err;
  }
  async function jget(u) {
    const r = await fetch(u);
    if (!r.ok) throw await failure(r, `GET ${u}`);
    return r.json();
  }
  async function jsend(u, m, b) {
    const r = await fetch(u, {
      method: m, headers: { "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : null,
    });
    if (!r.ok) throw await failure(r, `${m} ${u}`);
    return r;
  }
  const errText = (e, fallback) => (e && e.userMessage) || fallback;

  // ---------- icons (inline SVG, currentColor) ----------
  // Replaces the mismatched unicode glyphs. Stroke icons by default; `filled`
  // for solid media glyphs. Sized via CSS (.icn) per container, centred by flex.
  const svgIcon = (inner, filled) =>
    `<svg class="icn" viewBox="0 0 24 24" ${filled
      ? 'fill="currentColor" stroke="none"'
      : 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'} aria-hidden="true">${inner}</svg>`;
  const ICONS = {
    play: svgIcon('<path d="M7 4.4a1 1 0 0 1 1.5-.87l12.5 7.6a1 1 0 0 1 0 1.74L8.5 20.47A1 1 0 0 1 7 19.6z"/>', true),
    pause: svgIcon('<rect x="6.5" y="5" width="3.8" height="14" rx="1.3"/><rect x="13.7" y="5" width="3.8" height="14" rx="1.3"/>', true),
    prev: svgIcon('<rect x="5.5" y="5" width="2.6" height="14" rx="1"/><path d="M20 5.7a.7.7 0 0 0-1.08-.59L9.8 11.4a.7.7 0 0 0 0 1.2l9.12 6.3A.7.7 0 0 0 20 18.3z"/>', true),
    next: svgIcon('<path d="M4 5.7a.7.7 0 0 1 1.08-.59l9.12 6.29a.7.7 0 0 1 0 1.2l-9.12 6.3A.7.7 0 0 1 4 18.3z"/><rect x="15.9" y="5" width="2.6" height="14" rx="1"/>', true),
    plus: svgIcon('<path d="M12 5v14M5 12h14"/>'),
    more: svgIcon('<circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/>', true),
    shuffle: svgIcon('<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>'),
    repeat: svgIcon('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'),
    repeatOne: svgIcon('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4"/>'),
    list: svgIcon('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
    chevronUp: svgIcon('<path d="m6 15 6-6 6 6"/>'),
    back15: svgIcon('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><text x="12" y="15.5" font-size="7.5" font-family="Inter, sans-serif" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none">15</text>'),
    fwd30: svgIcon('<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/><text x="12" y="15.5" font-size="7.5" font-family="Inter, sans-serif" font-weight="700" text-anchor="middle" fill="currentColor" stroke="none">30</text>'),
    note: svgIcon('<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'),
    disc: svgIcon('<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>'),
    artist: svgIcon('<path d="M12 2a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3z"/><path d="M19 10v1a7 7 0 0 1-14 0v-1"/><path d="M12 18v4"/>'),
    tape: svgIcon('<rect x="2" y="5" width="20" height="14" rx="2"/><circle cx="8" cy="11" r="2"/><circle cx="16" cy="11" r="2"/><path d="M10 11h4M6 19l2-4h8l2 4"/>'),
    sparkle: svgIcon('<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>'),
    podcast: svgIcon('<circle cx="12" cy="11" r="2"/><path d="M8.5 15.5a5 5 0 1 1 7 0"/><path d="M5.6 18.4a9 9 0 1 1 12.8 0"/><path d="M12 13v8"/>'),
    check: svgIcon('<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>'),
    circleO: svgIcon('<circle cx="12" cy="12" r="9"/>'),
    x: svgIcon('<path d="M18 6 6 18M6 6l12 12"/>'),
    grip: svgIcon('<circle cx="9" cy="6" r="1.4"/><circle cx="15" cy="6" r="1.4"/><circle cx="9" cy="12" r="1.4"/><circle cx="15" cy="12" r="1.4"/><circle cx="9" cy="18" r="1.4"/><circle cx="15" cy="18" r="1.4"/>', true),
    chevronLeft: svgIcon('<path d="m15 18-6-6 6-6"/>'),
    chevronDown: svgIcon('<path d="m6 9 6 6 6-6"/>'),
    library: svgIcon('<path d="M4 6h16M4 12h16M4 18h16"/>'),
  };

  let shelf = [];         // tapes
  let view = [];          // tracks currently shown (browsing)
  let queue = [];         // tracks being played (play order)
  let baseQueue = [];     // queue in source order, before shuffle
  let qi = -1;            // index into queue
  let lastPlayed = null;  // for play-count dedupe
  let currentTape = null; // { key, name, kind }
  let currentSort = "default";
  let shuffleOn = localStorage.getItem("tapes-shuffle") === "1";
  let repeatMode = localStorage.getItem("tapes-repeat") || "off"; // off | all | one
  let trackParent = "shelf";  // where tracks-view "back" returns: shelf | albums | artists
  let browseRows = [];        // current album/artist browse list
  let currentBrowse = null;   // "albums" | "artists" | null
  let navToken = 0;           // bumped per view-open; a slow load bails if superseded
  let showsData = null;       // last /api/podcast/shows payload
  let currentShow = null;     // show whose episodes are open (null = loose)
  let episodes = [];          // episodes currently shown
  const pendingPlays = {};    // episode_id -> {list, i} awaiting download-then-play

  // ---------- shelf ----------
  async function loadShelf() {
    shelf = await jget("api/playlists");
    const all = shelf.find((x) => x.key === "all");
    $("firstRun").hidden = !(all && all.count === 0 && !shelf.some((x) => x.kind === "user"));
    const list = $("shelfList");
    list.innerHTML = "";
    const icon = { all: ICONS.list, singles: ICONS.note, albums: ICONS.disc, artists: ICONS.artist, tidy: ICONS.sparkle };
    let sepDone = false;
    shelf.forEach((s) => {
      // Subtle divider between the auto shelves and the user's own tapes.
      if (!sepDone && s.kind === "user") {
        const sep = document.createElement("li");
        sep.className = "shelf-sep";
        sep.setAttribute("aria-hidden", "true");
        list.appendChild(sep);
        sepDone = true;
      }
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.className = "shelf-row";
      li.innerHTML = `<span class="shelf-ico">${icon[s.key] || ICONS.tape}</span>
        <span class="shelf-name"></span><span class="shelf-count">${s.count}</span>`;
      li.querySelector(".shelf-name").textContent = s.name;
      li.addEventListener("click", () =>
        s.kind === "browse" ? openBrowse(s.key) : openTape(s.key, s.name, s.kind));
      list.appendChild(li);
    });
  }

  // ---------- top-level Music / Podcasts mode ----------
  let mode = "music";
  function setMode(m) {
    mode = m;
    $("modeMusic").classList.toggle("active", m === "music");
    $("modePods").classList.toggle("active", m === "podcasts");
    $("modeMusic").setAttribute("aria-selected", String(m === "music"));
    $("modePods").setAttribute("aria-selected", String(m === "podcasts"));
    // The one add input re-skins to the mode; the submit handler routes on it.
    $("dlUrl").placeholder = m === "music" ? "Paste a song or playlist link…" : "Paste an RSS or YouTube link…";
    $("dlSubmit").textContent = m === "music" ? "Rip" : "Follow";
    if (m === "music") showView("shelf");
    else openPodcasts();
  }

  // The last sort picked on each shelf, remembered on this device.
  function savedSort(key) {
    let v = null;
    try { v = localStorage.getItem(`tapes-sort-${key}`); } catch (_) { /* private mode */ }
    return v && [...$("sortSelect").options].some((o) => o.value === v) ? v : "default";
  }

  async function openTape(key, name, kind) {
    const tok = ++navToken;
    const sortable = key === "all" || key === "singles";
    currentSort = sortable ? savedSort(key) : "default";
    const data = await navGet(`api/playlists/${key}/tracks?sort=${currentSort}`);
    if (tok !== navToken) return;   // a newer view opened while we waited
    currentTape = { key, name, kind };
    view = data;
    $("sortSelect").value = currentSort;
    $("sortBar").hidden = !sortable;
    const titleEl = $("tapeTitle");
    titleEl.textContent = name;
    titleEl.contentEditable = "false";
    titleEl.classList.toggle("editable", kind === "user");
    titleEl.onclick = kind === "user" ? () => startTitleEdit((name) =>
      jsend(`api/playlists/${key}`, "PATCH", { name }).then(() => {
        if (currentTape) currentTape.name = name;
        loadShelf();
        toast(`Renamed to “${name}”`);
        return name;
      }).catch((e) => { toast(errText(e, "Couldn't rename the tape.")); throw e; })) : null;
    $("tapeDelBtn").hidden = kind !== "user";
    $("tidyBtn").hidden = key !== "tidy";
    $("albumEditBtn").hidden = true;
    $("search").value = "";
    $("backBtn").querySelector(".back-label").textContent = "Tapes";
    trackParent = "shelf";
    renderTracks(view);
    showView("tracks");
  }

  // ---------- loading + long lists ----------
  // A view that takes more than a moment to load dims the library and shows a
  // thin bar, instead of looking like the tap did nothing.
  let loadingCount = 0, loadingTimer = null;
  function whileLoading(p) {
    loadingCount++;
    if (!loadingTimer) loadingTimer = setTimeout(() => sidebar.classList.add("loading"), 150);
    return p.finally(() => {
      if (--loadingCount) return;
      clearTimeout(loadingTimer); loadingTimer = null;
      sidebar.classList.remove("loading");
    });
  }
  const navGet = (url) => whileLoading(jget(url));

  // Build a long list a chunk at a time: the first rows straight away, the
  // rest as the end of the list scrolls into view.
  const CHUNK = 150;
  function renderInChunks(el, items, makeRow, after) {
    let n = 0;
    const more = () => {
      const frag = document.createDocumentFragment();
      const end = Math.min(items.length, n + CHUNK);
      for (; n < end; n++) frag.appendChild(makeRow(items[n], n));
      el.appendChild(frag);
      if (after) after();
      if (n < items.length) watch();
    };
    const watch = () => {
      const sentinel = document.createElement("li");
      sentinel.className = "list-more"; sentinel.setAttribute("aria-hidden", "true");
      el.appendChild(sentinel);
      const io = new IntersectionObserver((entries) => {
        if (!entries.some((x) => x.isIntersecting)) return;
        io.disconnect(); sentinel.remove(); more();
      }, { rootMargin: "600px 0px" });
      io.observe(sentinel);
    };
    more();
  }
  function debounce(fn, ms) {
    let t = null;
    return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  }

  // ---------- view switching ----------
  function showView(name) {
    $("shelfView").hidden = name !== "shelf";
    $("browseView").hidden = name !== "browse";
    $("tracksView").hidden = name !== "tracks";
    $("podcastsView").hidden = name !== "podcasts";
    $("episodesView").hidden = name !== "episodes";
    syncHistory();
  }

  // ---------- album / artist browse ----------
  async function openBrowse(kind) {
    const tok = ++navToken;
    const rows = await navGet(kind === "albums" ? "api/albums" : "api/artists");
    if (tok !== navToken) return;
    currentBrowse = kind;
    browseRows = rows;
    $("browseTitle").textContent = kind === "albums" ? "Albums" : "Artists";
    $("browseSearch").value = "";
    renderBrowse(browseRows);
    showView("browse");
  }
  function renderBrowse(rows) {
    const el = $("browseList");
    el.innerHTML = "";
    if (!rows.length) {
      const q = $("browseSearch").value.trim();
      el.innerHTML = `<div class="empty-note"></div>`;
      el.firstChild.textContent = q ? `Nothing matches “${q}”.`
        : currentBrowse === "albums" ? "No albums yet — they appear as you add songs with album tags."
        : "No artists yet — they appear as you add songs.";
      return;
    }
    renderInChunks(el, rows, (r) => {
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.className = "browse-row";
      if (currentBrowse === "albums") {
        const art = r.cover_id
          ? `<img class="browse-cover" src="${coverUrl(r.cover_id)}" alt="" loading="lazy" decoding="async">`
          : `<span class="browse-cover browse-cover--blank">${ICONS.disc}</span>`;
        li.innerHTML = `${art}<span class="browse-meta">
          <span class="browse-name"></span><span class="browse-sub"></span></span>
          <span class="shelf-count">${r.count}</span>`;
        li.querySelector(".browse-sub").textContent = r.artist;
        li.addEventListener("click", () => openAlbumTracks(r.name));
      } else {
        li.innerHTML = `<span class="shelf-ico">${ICONS.artist}</span><span class="browse-meta">
          <span class="browse-name"></span></span><span class="shelf-count">${r.count}</span>`;
        li.addEventListener("click", () => openArtistTracks(r.name));
      }
      li.querySelector(".browse-name").textContent = r.name;
      return li;
    });
  }
  function applyBrowseSearch() {
    const q = $("browseSearch").value.toLowerCase().trim();
    renderBrowse(q ? browseRows.filter((r) =>
      (r.name + " " + (r.artist || "")).toLowerCase().includes(q)) : browseRows);
  }
  async function openAlbumTracks(album) {
    const tok = ++navToken;
    const data = await navGet(`api/albums/tracks?album=${encodeURIComponent(album)}`);
    if (tok !== navToken) return;
    view = data;
    openTrackList(album, "albums", "Albums");
  }
  async function openArtistTracks(artist) {
    const tok = ++navToken;
    const data = await navGet(`api/artists/tracks?artist=${encodeURIComponent(artist)}`);
    if (tok !== navToken) return;
    view = data;
    openTrackList(artist, "artists", "Artists");
  }
  function openTrackList(title, parent, backLabel) {
    currentTape = null;
    trackParent = parent;
    const titleEl = $("tapeTitle");
    titleEl.textContent = title;
    titleEl.contentEditable = "false";
    const renamable = parent === "artists" || parent === "albums";
    titleEl.classList.toggle("editable", renamable);
    titleEl.onclick = !renamable ? null : parent === "artists"
      ? () => startTitleEdit((name, orig) => renameArtist(orig, name))
      : () => startTitleEdit((name, orig) => saveAlbum(orig, { name }).then((r) => r.album));
    $("tidyBtn").hidden = true;
    $("albumEditBtn").hidden = parent !== "albums";
    $("tapeDelBtn").hidden = true;
    $("sortBar").hidden = true;
    $("backBtn").querySelector(".back-label").textContent = backLabel;
    $("search").value = "";
    renderTracks(view);
    showView("tracks");
  }

  // Rename an artist everywhere. If the new name matches an existing artist the
  // tracks merge, so ask first; either way the toast offers Undo.
  async function renameArtist(orig, name) {
    const p = await jget(`api/artists/rename-preview?old=${encodeURIComponent(orig)}&new=${encodeURIComponent(name)}`);
    const n = (k) => `${k} song${k === 1 ? "" : "s"}`;
    if (p.merges_into && p.name !== orig) {
      const ok = await askConfirm(`Merge into “${p.name}”?`, {
        detail: `${n(p.tracks)} by “${orig}” will join ${n(p.merges_into)} already under “${p.name}”.`,
        ok: "Merge",
      });
      if (!ok) throw new Error("cancelled");
    }
    const r = await jsend("api/artists", "PATCH", { old: orig, new: name }).then((x) => x.json());
    browseRows = await jget("api/artists");
    renderBrowse(browseRows);
    openArtistTracks(r.name);
    const note = r.tag_failures ? ` (${r.tag_failures} file tag${r.tag_failures === 1 ? "" : "s"} couldn't be updated)` : "";
    toast(`Renamed to “${r.name}”${note}`, {
      action: "Undo",
      onAction: async () => {
        try {
          await jsend("api/tracks/artist", "PATCH", { track_ids: r.track_ids, artist: orig });
          browseRows = await jget("api/artists");
          renderBrowse(browseRows);
          openArtistTracks(orig);
          toast(`Changed back to “${orig}”`);
        } catch (e) { console.error(e); toast(errText(e, "Couldn't undo the rename.")); }
      },
    });
    return r.name;
  }

  // ---------- podcasts ----------
  async function openPodcasts() {
    const tok = ++navToken;
    let data;
    try { data = await navGet("api/podcast/shows"); }
    catch (e) { console.error(e); toast("Couldn't load podcasts."); return; }
    if (tok !== navToken) return;
    showsData = data;
    renderShows(data);
    showView("podcasts");
  }
  function renderShows(data) {
    const el = $("showList");
    el.innerHTML = "";
    if (!data.shows.length && !data.loose_count) {
      el.innerHTML = `<div class="empty-note">Follow a show: tap <b>+ Add</b> and paste its RSS or YouTube link.</div>`;
      return;
    }
    data.shows.forEach((s) => {
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.className = "browse-row";
      const art = s.has_image
        ? `<img class="browse-cover" src="${M.epShowCoverBase + s.id}" alt="" loading="lazy" decoding="async">`
        : `<span class="browse-cover browse-cover--blank">${ICONS.podcast}</span>`;
      li.innerHTML = `${art}<span class="browse-meta">
        <span class="browse-name"></span><span class="browse-sub"></span></span>
        <span class="shelf-count">${s.unplayed ? s.unplayed + " new" : s.count}</span>`;
      li.querySelector(".browse-name").textContent = s.title;
      li.querySelector(".browse-sub").textContent = s.source_type === "youtube" ? "YouTube" : "RSS";
      li.addEventListener("click", () => openShow(s));
      el.appendChild(li);
    });
    if (data.loose_count) {
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.className = "browse-row";
      li.innerHTML = `<span class="browse-cover browse-cover--blank">${ICONS.podcast}</span>
        <span class="browse-meta"><span class="browse-name">Unsorted episodes</span></span>
        <span class="shelf-count">${data.loose_count}</span>`;
      li.addEventListener("click", openLoose);
      el.appendChild(li);
    }
  }
  async function openShow(s) {
    const tok = ++navToken;
    const data = await navGet(`api/podcast/shows/${s.id}/episodes`);
    if (tok !== navToken) return;
    currentShow = data.show;
    // manual tapes can't refresh; only real shows can be deleted from here
    enterEpisodes(data.show.title, data.episodes, { refreshable: data.show.refreshable, deletable: true });
  }
  async function openLoose() {
    const tok = ++navToken;
    const data = await navGet("api/podcast/episodes/loose");
    if (tok !== navToken) return;
    currentShow = null;
    enterEpisodes("Unsorted episodes", data.episodes, { refreshable: false, deletable: false });
  }
  // Shared tail for the two episode views (a show's episodes, or Unsorted episodes).
  function enterEpisodes(title, eps, { refreshable, deletable }) {
    episodes = eps;
    $("showTitle").textContent = title;
    $("showRefreshBtn").hidden = !refreshable;
    $("showDelBtn").hidden = !deletable;
    $("epSearch").value = "";
    renderEpisodes(episodes);
    showView("episodes");
  }
  function formatEpDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  }
  function renderEpisodes(list) {
    const el = $("episodeList");
    el.innerHTML = "";
    if (!list.length) {
      const q = $("epSearch").value.trim();
      el.innerHTML = `<div class="empty-note"></div>`;
      el.firstChild.textContent = q ? `Nothing matches “${q}”.`
        : epFilter === "unplayed" ? "No unplayed episodes."
        : epFilter === "downloaded" ? "No downloaded episodes."
        : "No episodes yet. Use Refresh to check for new ones.";
      return;
    }
    renderInChunks(el, list, (e, i) => {
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.dataset.id = e.id;
      li.className = e.played ? "played" : "";   // layout comes from .track-list li
      const pct = (!e.played && e.duration && e.position)
        ? Math.min(100, (e.position / e.duration) * 100) : 0;
      const sub = [
        formatEpDate(e.published_at),
        e.duration ? fmt(e.duration) : (e.status === "new" ? "Not downloaded yet" : ""),
        e.status === "downloading" ? "Downloading…" : "",
      ].filter(Boolean).join(" · ");
      li.innerHTML = `<span class="tl-meta">
          <div class="tl-title"></div><div class="tl-sub"></div>
          <div class="ep-prog"${pct ? "" : " hidden"}><div class="ep-prog-fill" style="width:${pct}%"></div></div>
        </span>
        <button class="tl-add ep-played" title="${e.played ? "Mark as unplayed" : "Mark as played"}" aria-label="${e.played ? "Mark as unplayed" : "Mark as played"}">${e.played ? ICONS.check : ICONS.circleO}</button>
        <button class="tl-add ep-menu" title="More" aria-label="More">${ICONS.more}</button>`;
      li.querySelector(".tl-title").textContent = e.title;
      li.querySelector(".tl-title").title = e.title;
      li.querySelector(".tl-sub").textContent = sub;
      li.querySelector(".ep-played").addEventListener("click", (ev) => { ev.stopPropagation(); togglePlayed(e); });
      li.querySelector(".ep-menu").addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (!menu.hidden && menu.dataset.for === "ep" + e.id) closeMenu();
        else openEpisodeMenu(ev, e);
      });
      li.addEventListener("click", () => playEpisode(list, i));
      return li;
    }, markActive);
  }
  let epFilter = localStorage.getItem("tapes-ep-filter") || "all";  // all | unplayed | downloaded
  function applyEpisodeSearch() {
    const q = $("epSearch").value.toLowerCase().trim();
    let list = episodes;
    if (epFilter === "unplayed") list = list.filter((e) => !e.played);
    else if (epFilter === "downloaded") list = list.filter((e) => e.status === "ready");
    if (q) list = list.filter((e) => e.title.toLowerCase().includes(q));
    renderEpisodes(list);
  }
  function updateEpFilterBtns() {
    [...document.querySelectorAll(".ep-filter-btn")].forEach((b) =>
      b.classList.toggle("active", b.dataset.f === epFilter));
  }
  // ---- per-episode menu (assign to show / remove download / delete) ----
  function placeAtClick(e) {
    const pad = 8, mh = menu.offsetHeight;
    const flipUp = e.clientY + mh > window.innerHeight - pad;
    const flipLeft = e.clientX + menu.offsetWidth > window.innerWidth - pad;
    placeMenu(menu, flipUp ? e.clientY - mh : e.clientY, e.clientX,
      `${flipUp ? "bottom" : "top"} ${flipLeft ? "right" : "left"}`);
  }
  function openEpisodeMenu(e, ep) {
    menu.dataset.for = "ep" + ep.id;
    menu.innerHTML = "";
    menu.appendChild(menuHead(ep.title));
    // Unsorted episodes can be moved into a show (in-place picker — see submenuItem).
    if (ep.show_id == null)
      menu.appendChild(submenuItem("Move to show…", () => openAssignMenu(e, ep)));
    if (ep.status === "ready")
      menu.appendChild(menuItem("Remove download", () => removeDownload(ep), closeMenu));
    // A followed show's feed would bring a deleted episode back on the next
    // refresh, so there it's hidden instead; delete is for everything else.
    if (ep.show_id != null && currentShow && currentShow.refreshable)
      menu.appendChild(menuItem("Hide episode", () => hideEpisode(ep), closeMenu));
    else
      menu.appendChild(menuItem("Delete episode", () => deleteEpisode(ep), closeMenu));
    showMenuAt(e);
  }
  async function openAssignMenu(e, ep) {
    if (!showsData) { try { showsData = await jget("api/podcast/shows"); } catch (_) { /* ignore */ } }
    menu.innerHTML = "";
    menu.appendChild(menuHead(`Move “${ep.title}” to…`));
    (showsData?.shows || []).forEach((s) =>
      menu.appendChild(menuItem(s.title, () => assignEpisode(ep, { show_id: s.id }), closeMenu)));
    menu.appendChild(menuSep());
    menu.appendChild(menuItem("New show…", async () => {
      const name = await askName("New show", { label: "Show name", ok: "Create" });
      if (name) assignEpisode(ep, { new_show_name: name });
    }, closeMenu));
    showMenuAt(e);
  }
  async function assignEpisode(ep, body) {
    let res;
    try { res = await jsend(`api/podcast/episodes/${ep.id}/assign`, "POST", body).then((r) => r.json()); }
    catch (err) { console.error(err); toast(errText(err, "Couldn't move the episode.")); return; }
    episodes = episodes.filter((x) => x.id !== ep.id);   // it left Unsorted episodes
    applyEpisodeSearch();
    showsData = null;   // counts/new show changed — refetch on next open
    toast(`Moved to “${res.show.title}”`);
  }
  async function removeDownload(ep) {
    try { await jsend(`api/podcast/episodes/${ep.id}/remove-download`, "POST"); }
    catch (err) { console.error(err); toast("Couldn't remove the download."); return; }
    ep.status = "new"; ep.file_path = null;
    applyEpisodeSearch();
    toast("Download removed");
  }
  async function deleteEpisode(ep) {
    if (!await askConfirm(`Delete “${ep.title}”?`, { detail: "Its download is removed too.", ok: "Delete", danger: true })) return;
    try { await jsend(`api/podcast/episodes/${ep.id}`, "DELETE"); }
    catch (err) { console.error(err); toast("Couldn't delete."); return; }
    episodes = episodes.filter((x) => x.id !== ep.id);
    applyEpisodeSearch();
  }
  async function hideEpisode(ep) {
    try { await jsend(`api/podcast/episodes/${ep.id}/hide`, "POST"); }
    catch (err) { console.error(err); toast(errText(err, "Couldn't hide that episode.")); return; }
    const at = episodes.findIndex((x) => x.id === ep.id);
    episodes = episodes.filter((x) => x.id !== ep.id);
    showsData = null;   // counts changed
    applyEpisodeSearch();
    toast(`Hid “${ep.title}”`, {
      action: "Undo",
      onAction: async () => {
        try {
          const back = await jsend(`api/podcast/episodes/${ep.id}/unhide`, "POST").then((r) => r.json());
          episodes.splice(Math.max(0, at), 0, back);
          showsData = null;
          applyEpisodeSearch();
        } catch (err) { console.error(err); toast(errText(err, "Couldn't bring it back.")); }
      },
    });
  }
  // Start the download without the "wait for it" UI (used while streaming).
  function fetchEpisodeQuietly(t) {
    jsend(`api/podcast/episodes/${t.id}/play`, "POST").catch(() => { /* streaming still works */ });
  }
  async function playEpisode(list, i) {
    const e = list[i];
    if (e.status === "ready" || canStreamRemote(e)) { startEpisodePlayback(list, i); return; }
    let res;
    try { res = await jsend(`api/podcast/episodes/${e.id}/play`, "POST").then((r) => r.json()); }
    catch (err) { console.error(err); toast("Couldn't start the episode."); return; }
    if (res.ready) { e.status = "ready"; startEpisodePlayback(list, i); return; }
    // Downloading — reveal the progress panel and auto-play when its job finishes.
    pendingPlays[e.id] = { list, i };
    e.status = "downloading";
    applyEpisodeSearch();
    $("dlPanel").hidden = false;
    openDlStream();
    toast("Downloading episode…");
  }
  function startEpisodePlayback(list, i) {
    newTape(list);
    baseQueue = list.slice();
    queue = list.slice();
    qi = i;
    loadCurrent(true);
  }
  // Show a "downloading…" deck state and fetch an episode that was reached before
  // it was downloaded; onPodcastJobDone plays it once the job completes.
  function loadPendingEpisode(t) {
    cassette.closest(".deck").classList.add("is-episode");
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = subLine(t) + " · downloading…";
    labelArt.removeAttribute("src");
    markActive();
    updateUpNext();
    updateMini();
    pendingPlays[t.id] = { list: queue, i: qi };
    jsend(`api/podcast/episodes/${t.id}/play`, "POST").then((r) => r.json()).then((res) => {
      if (res.ready) { t.status = "ready"; loadCurrent(true); }
      else { $("dlPanel").hidden = false; openDlStream(); }
    }).catch((e) => { console.error(e); toast("Couldn't load episode."); });
  }
  // A podcast download job finished (or errored — it just drops off the stream).
  // Re-sync the open view's statuses, then play if this episode was awaited.
  async function onPodcastJobDone(epId) {
    const pend = pendingPlays[epId];
    delete pendingPlays[epId];
    if (!$("episodesView").hidden) {
      try {
        const data = currentShow
          ? await jget(`api/podcast/shows/${currentShow.id}/episodes`)
          : await jget("api/podcast/episodes/loose");
        episodes = data.episodes;
        applyEpisodeSearch();
      } catch (e) { console.error(e); }
    }
    if (!pend) return;
    const e = episodes.find((x) => x.id === epId);
    if (e && e.status === "ready") startEpisodePlayback(episodes, episodes.indexOf(e));
    else toast("Episode download failed.");
  }
  async function togglePlayed(e) {
    const played = !e.played;
    try { await jsend(`api/podcast/episodes/${e.id}/played`, "POST", { played }); }
    catch (err) { console.error(err); toast("Couldn't update."); return; }
    e.played = played;
    if (played) e.position = 0;
    applyEpisodeSearch();
  }
  function markEpisodePlayed(t) {
    t.played = true; t.position = 0;
    jsend(`api/podcast/episodes/${t.id}/progress`, "PUT", { position: 0, played: true }).catch(() => {});
    const e = episodes.find((x) => x.id === t.id);
    if (e) { e.played = true; e.position = 0; }
    if (!$("episodesView").hidden) applyEpisodeSearch();
  }
  async function refreshCurrentShow() {
    if (!currentShow) return;
    const btn = $("showRefreshBtn"), orig = btn.textContent;
    btn.disabled = true; btn.textContent = "Checking…";
    try {
      const r = await jsend(`api/podcast/shows/${currentShow.id}/refresh`, "POST").then((x) => x.json());
      toast(r.added ? `${r.added} new episode${r.added > 1 ? "s" : ""}` : "No new episodes");
      if (r.added) await openShow(currentShow);
    } catch (e) { console.error(e); toast(errText(e, "Couldn't check for new episodes.")); }
    finally { btn.disabled = false; btn.textContent = orig; }
  }
  async function deleteCurrentShow() {
    if (!currentShow) return;
    const followed = currentShow.refreshable;
    if (!await askConfirm(followed ? `Unfollow “${currentShow.title}”?` : `Delete the show “${currentShow.title}”?`, {
      detail: "Its episodes and any downloads are removed from Tapes.",
      ok: followed ? "Unfollow" : "Delete", danger: true })) return;
    try { await jsend(`api/podcast/shows/${currentShow.id}`, "DELETE"); }
    catch (e) { console.error(e); toast(errText(e, "Couldn't delete the show.")); return; }
    toast(`${followed ? "Unfollowed" : "Deleted"} “${currentShow.title}”`);
    currentShow = null;
    openPodcasts();
  }

  // Inline-edit the track-list header. `save(name, orig)` does the persistence and
  // resolves to the final name to display (which may differ from what was typed —
  // an artist rename can merge onto an existing spelling). On reject we revert.
  function startTitleEdit(save) {
    const el = $("tapeTitle");
    if (el.contentEditable === "true") return;
    const orig = el.textContent;
    el.contentEditable = "true";
    el.focus();
    // Select all of the title (execCommand is deprecated).
    const range = document.createRange();
    range.selectNodeContents(el);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    function commit(doSave) {
      el.onblur = null;
      el.onkeydown = null;
      const name = doSave ? el.innerText.trim() : orig;
      el.contentEditable = "false";
      el.textContent = name || orig;
      if (doSave && name && name !== orig) {
        Promise.resolve(save(name, orig))
          .then((finalName) => { el.textContent = finalName || name; })
          .catch(() => { el.textContent = orig; });
      }
    }

    // Only Enter saves; tapping/clicking away cancels, so a stray tap can't rename.
    el.onblur = () => commit(false);
    el.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(true); }
      if (e.key === "Escape") commit(false);
    };
  }

  function renderTracks(list) {
    const el = $("trackList");
    el.innerHTML = "";
    if (!list.length) {
      const q = $("search").value.trim();
      el.innerHTML = `<div class="empty-note"></div>`;
      el.firstChild.textContent = q ? `Nothing matches “${q}”.`
        : currentTape && currentTape.kind === "user" ? "This tape is empty. Tap + on any song to add it here."
        : currentTape && currentTape.key === "tidy" ? "Nothing needs tidying."
        : "No songs yet. Tap + Add to rip one from a link.";
      return;
    }
    // Drag-reorder only makes sense (and persists) for a user tape, and only
    // when the list isn't filtered by a search.
    const reorderable = !!(currentTape && currentTape.kind === "user") && !$("search").value.trim();
    const makeRow = (t, i) => {
      const li = document.createElement("li");
      li.tabIndex = 0;   // reachable by Tab; Enter opens or plays it
      li.dataset.id = t.id;
      const handle = reorderable ? `<span class="tl-drag drag-handle" title="Drag to reorder" aria-hidden="true">${ICONS.grip}</span>` : "";
      li.innerHTML = `${handle}<span class="tl-num">${i + 1}</span>
        <span class="tl-meta"><div class="tl-title"></div><div class="tl-sub"></div></span>
        <span class="tl-dur">${t.duration ? fmt(t.duration) : ""}</span>
        <button class="tl-add tl-addto" title="Add to…" aria-label="Add to tape or queue">${ICONS.plus}</button>
        <button class="tl-add tl-more" title="More" aria-label="More">${ICONS.more}</button>`;
      li.querySelector(".tl-title").textContent = t.title;
      li.querySelector(".tl-title").title = t.title;   // full text on hover
      const sub = li.querySelector(".tl-sub");
      if (t.artist) sub.textContent = [t.artist, t.album].filter(Boolean).join(" · ");
      else {
        const u = document.createElement("span");
        u.className = "unknown"; u.textContent = "Unknown artist";
        sub.append(u, t.album ? ` · ${t.album}` : "");
      }
      if (t.issues && t.issues.length) {
        const chips = document.createElement("div");
        chips.className = "tl-issues";
        t.issues.forEach((x) => { const c = document.createElement("span"); c.className = "tl-issue"; c.textContent = x; chips.appendChild(c); });
        li.querySelector(".tl-meta").appendChild(chips);
      }
      li.querySelector(".tl-addto").addEventListener("click", (e) => { e.stopPropagation(); openAddMenu(e, t); });
      li.querySelector(".tl-more").addEventListener("click", (e) => {
        e.stopPropagation();
        if (!menu.hidden && menu.dataset.for === String(t.id)) closeMenu();
        else openMenu(e, t);
      });
      const h = li.querySelector(".tl-drag");
      if (h) h.addEventListener("click", (e) => e.stopPropagation());
      li.addEventListener("click", () => playFromList(list, i));
      return li;
    };
    if (reorderable) { list.forEach((t, i) => el.appendChild(makeRow(t, i))); markActive(); }
    else renderInChunks(el, list, makeRow, markActive);
  }

  function applySearch() {
    const q = $("search").value.toLowerCase().trim();
    renderTracks(q ? view.filter((t) =>
      (t.title + " " + t.artist + " " + t.album).toLowerCase().includes(q)) : view);
  }

  // ---------- phone layout: library first, deck slides up ----------
  const phoneQuery = window.matchMedia("(max-width: 640px)");
  const isMobile = () => phoneQuery.matches;
  const openDeck = () => app.classList.add("deck-open");
  const closeDeck = () => app.classList.remove("deck-open");
  function updateNavToggle() {
    const b = $("navToggle");
    b.innerHTML = isMobile() ? ICONS.chevronDown : ICONS.library;
    const label = isMobile() ? "Back to library" : "Show or hide the library";
    b.title = label;
    b.setAttribute("aria-label", label);
  }
  phoneQuery.addEventListener("change", updateNavToggle);

  // The phone mini-player mirrors the deck: art, title, play/pause.
  function updateMini() {
    const t = currentTrack();
    $("mini").hidden = !t;
    if (!t) { closeDeck(); return; }
    $("miniTitle").textContent = t.title;
    $("miniSub").textContent = subLine(t);
    const art = artUrl(t);
    if (art) $("miniArt").src = art; else $("miniArt").removeAttribute("src");
    const playing = !audio.paused;
    $("miniPlay").innerHTML = playing ? ICONS.pause : ICONS.play;
    $("miniPlay").setAttribute("aria-label", playing ? "Pause" : "Play");
  }

  // ---------- playback ----------
  function shuffleArray(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  // Starting a different list puts a new tape in: the old one ejects and the
  // new one starts on side A (Keep playing turns it over to side B).
  const listKey = (list) => `${list.length}:${list[0]?.id}:${list[list.length - 1]?.id}`;
  // A tape of yours prints one label design for all its songs; anything else
  // prints each album's own (label-print.js).
  let tapeChanging = false, side = "A", tapeSeed = null;
  function newTape(list) {
    tapeChanging = cassette.classList.contains("loaded") && listKey(list) !== listKey(baseQueue);
    side = "A";
    tapeSeed = currentTape && currentTape.kind === "user" ? `tape:${currentTape.key}` : null;
  }
  const labelSeed = (t) => tapeSeed || (t.kind === "episode" ? `show:${t.show}` : t.album || `${t.artist}|${t.title}`);
  function playFromList(list, i) {
    newTape(list);
    baseQueue = list.slice();
    if (shuffleOn) {
      const chosen = baseQueue[i];
      queue = [chosen, ...shuffleArray(baseQueue.filter((_, idx) => idx !== i))];
      qi = 0;
    } else {
      queue = baseQueue.slice();
      qi = i;
    }
    loadCurrent(true);
  }
  function loadCurrent(autoplay) {
    const t = queue[qi];
    if (!t) return;
    const isEp = t.kind === "episode";
    // Reached an episode that isn't downloaded yet (e.g. auto-advance / queue jump):
    // kick off the fetch and let onPodcastJobDone resume playback when it's ready.
    if (isEp && t.status !== "ready" && !canStreamRemote(t)) { loadPendingEpisode(t); return; }
    if (isEp && t.status !== "ready") fetchEpisodeQuietly(t);   // stream now, keep a copy
    audio.open(t, srcUrl(t), { album: inAlbumRun(qi) });
    $("cassette").closest(".deck").classList.toggle("is-episode", isEp);
    audio.playbackRate = isEp ? episodeSpeed : 1;
    // Resume an episode where you left off (music resume rides the playstate path).
    if (isEp) resumeEpisodeTo(t.position);
    if (autoplay) audio.play().catch(() => {});
    if (tapeChanging) { tapeChanging = false; DeckFX.changeTape(() => paintLabel(t)); } else paintLabel(t);
    if (t.radio && side === "A") { side = "B"; DeckFX.flip(side); }
    markActive();
    // Persist the deck snapshot. For episodes, only the session (queue+cursor) —
    // the position rides on the episode and mustn't be saved as 0 before the seek.
    if (isEp) savePodcastSession(); else savePlaystate();
    prefetchNext();
    updateUpNext();
    updateMini();
    keepPlayingIfEnding();
  }
  // The label, the page title and the lock screen for what's in the deck.
  function paintLabel(t) {
    cassette.classList.add("loaded");
    $("sideLetter").textContent = side;
    labelTitle.textContent = t.title;
    labelArtist.textContent = subLine(t);
    fitLabel();
    const art = artUrl(t);
    if (art) labelArt.src = art; else labelArt.removeAttribute("src");
    document.title = `${t.title} · ${subLine(t)}`;
    setMediaSession(t);
    const seed = labelSeed(t);
    DeckFX.setLabel(seed, art).then((glow) => {
      if (t.kind === "episode" || currentTrack() !== t) return;
      DeckFX.lockArt(M.cassetteBase, t, { title: t.title, sub: subLine(t), artUrl: art, glow, seed },
        (url) => { if (currentTrack() === t) setMediaSession(t, url); });
    });
  }
  // ---------- reels ----------
  // The tape winds from the left pack to the right one as the song plays.
  // Each pack's radius follows the amount of tape on it (area, not length,
  // so it changes faster near the empty hub), and the hubs turn at the
  // speed constant tape speed implies: a small pack spins faster.
  const reels = (() => {
    // View-box geometry: hub centres, empty core and full pack radii. On a
    // real C-cassette the full pack is a little over twice the core.
    const CORE = 36, FULL = 80, CX = { L: 95.75, R: 234.25 }, CY = 92.25;
    const TAPE_SPEED = 55;   // view-box units per second at the tape surface
    const el = (id) => document.getElementById(id);
    const packL = el("packL"), packR = el("packR"), reelL = el("reelL"), reelR = el("reelR");
    // A few winding layers just inside each pack's edge, each a slightly
    // different shade, like the edge of a real pack of tape.
    const LAYERS = [[1.6, 0.18, "#7a6a5c"], [3.1, 0.12, "#000"], [4.4, 0.14, "#6b5b4e"],
                    [6.5, 0.1, "#000"], [8.8, 0.12, "#5e5045"], [12, 0.08, "#000"]];
    const makeLayers = (g, cx) => LAYERS.map(([, w, color]) => {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", cx); c.setAttribute("cy", CY);
      c.setAttribute("fill", "none"); c.setAttribute("stroke", color);
      c.setAttribute("stroke-width", 0.5); c.setAttribute("stroke-opacity", w * 3);
      g.appendChild(c);
      return c;
    });
    const ringsL = makeLayers(el("layersL"), CX.L), ringsR = makeLayers(el("layersR"), CX.R);
    const placeLayers = (rings, r) => rings.forEach((c, i) => {
      const rr = r - LAYERS[i][0];
      c.setAttribute("r", Math.max(0, rr));
      c.setAttribute("visibility", rr > CORE ? "visible" : "hidden");
    });
    const still = window.matchMedia("(prefers-reduced-motion: reduce)");
    // A skip or seek spins the reels fast for a moment, like fast-forward or
    // rewind, even while paused; `playing` is whether the tape itself runs.
    const WHIR_MS = 450, WHIR_SPEED = 14;
    let angL = 0, angR = 0, last = 0, raf = 0, playing = false, whirDir = 0, whirEnd = 0;
    const radius = (share) => Math.sqrt(CORE * CORE + share * (FULL * FULL - CORE * CORE));
    function setPacks() {
      const p = audio.duration ? Math.min(1, Math.max(0, audio.currentTime / audio.duration)) : 0;
      const rL = radius(1 - p), rR = radius(p);
      packL.setAttribute("r", rL);
      packR.setAttribute("r", rR);
      placeLayers(ringsL, rL);
      placeLayers(ringsR, rR);
      return [rL, rR];
    }
    function frame(t) {
      const dt = last ? Math.min(0.1, (t - last) / 1000) : 0;
      last = t;
      const [rL, rR] = setPacks();
      const whir = Math.max(0, (whirEnd - t) / WHIR_MS);   // 1 → 0 as the whir dies away
      if (!still.matches) {
        const rate = (playing ? audio.playbackRate || 1 : 0) + whirDir * WHIR_SPEED * whir * whir;
        const speed = TAPE_SPEED * rate * dt;
        angL = (angL + (speed / rL) * 180 / Math.PI) % 360;
        angR = (angR + (speed / rR) * 180 / Math.PI) % 360;
        reelL.setAttribute("transform", `rotate(${angL} ${CX.L} ${CY})`);
        reelR.setAttribute("transform", `rotate(${angR} ${CX.R} ${CY})`);
      }
      raf = playing || whir > 0 ? requestAnimationFrame(frame) : 0;
    }
    const run = () => { if (!raf) { last = 0; raf = requestAnimationFrame(frame); } };
    return {
      start() { playing = true; run(); },
      stop() { playing = false; setPacks(); },
      /** dir: 1 forward (next, seek ahead), -1 back. */
      whir(dir) { if (still.matches || !dir) return; whirDir = Math.sign(dir); whirEnd = performance.now() + WHIR_MS; run(); },
      sync: setPacks,
    };
  })();
  ["loadedmetadata", "seeked", "emptied"].forEach((ev) => audio.addEventListener(ev, reels.sync));
  reels.sync();

  // Long titles on the paper label drift slowly sideways (and back) so the
  // whole name can be read; the full text is also the tooltip.
  function fitLabel() {
    [labelTitle, labelArtist].forEach((el) => {
      el.title = el.textContent;
      el.classList.remove("drift");
      el.style.removeProperty("--drift");
      const inner = el.scrollWidth - el.clientWidth;
      if (inner > 4) { el.style.setProperty("--drift", `-${inner}px`); el.classList.add("drift"); }
    });
  }
  window.addEventListener("resize", () => { if (currentTrack()) fitLabel(); });

  // The song after this one streams in behind it, for a gapless join (and an
  // instant skip). Repeat-one replays instead, so nothing follows.
  function upcomingIndex() {
    if (activeIsEpisode() || repeatMode === "one") return -1;
    if (qi + 1 < queue.length) return qi + 1;
    return repeatMode === "all" && queue.length > 1 ? 0 : -1;
  }
  function prefetchNext() {
    const i = upcomingIndex(), next = i >= 0 ? queue[i] : null;
    audio.setNext(next, next ? srcUrl(next) : null, { album: next ? inAlbumRun(i) : false });
  }
  // An album playing in order gets album gain (its quiet and loud songs keep
  // their balance): true when a neighbour in the queue is from the same album.
  function inAlbumRun(i) {
    const t = queue[i];
    if (!t || !t.album) return false;
    return [queue[i - 1], queue[i + 1]].some((n) => n && n.album === t.album);
  }
  const currentTrack = () => queue[qi] || null;
  // The active deck queue is kind-pure: when an episode is playing, music's
  // shuffle/repeat don't apply and music "add to queue" starts a fresh music
  // queue rather than mixing songs into the podcast queue.
  const activeIsEpisode = () => { const c = currentTrack(); return !!c && c.kind === "episode"; };
  function markActive() {
    const cur = currentTrack();
    const isEp = !!cur && cur.kind === "episode";
    [...$("trackList").children].forEach((li) =>
      li.classList?.toggle("active", !isEp && !!cur && Number(li.dataset.id) === cur.id));
    [...$("episodeList").children].forEach((li) =>
      li.classList?.toggle("active", isEp && !!cur && Number(li.dataset.id) === cur.id));
  }
  function togglePlay() {
    if (qi < 0) { if (view.length) playFromList(view, 0); return; }
    audio.paused ? audio.play() : audio.pause();
  }
  // `lockArt`: the cassette drawn with this label (deck-fx.js), once it's stored;
  // until then the cover.
  function setMediaSession(t, lockArt) {
    if (!("mediaSession" in navigator)) return;
    const isEp = t.kind === "episode";
    const art = artUrl(t);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title,
      artist: isEp ? (t.show || "Podcast") : (t.artist || ""),
      album: isEp ? "" : (t.album || ""),
      artwork: lockArt ? [{ src: lockArt, sizes: "512x512", type: "image/jpeg" }]
        : art ? [{ src: art, sizes: "500x500", type: "image/jpeg" }] : [],
    });
    const handle = (action, fn) => { try { navigator.mediaSession.setActionHandler(action, fn); } catch (_) { /* unsupported */ } };
    handle("previoustrack", () => prev());
    handle("nexttrack", () => next(true));
    // Lock-screen scrubbing and skips (±15/30 s for episodes, ±10 s for songs).
    handle("seekto", (d) => { if (d.seekTime != null) seekTo(d.seekTime); });
    handle("seekbackward", (d) => skipBy(-(d.seekOffset || (isEp ? 15 : 10))));
    handle("seekforward", (d) => skipBy(d.seekOffset || (isEp ? 30 : 10)));
  }
  function go(i, autoplay) { qi = i; loadCurrent(autoplay); }
  // `manual` = user pressed next (vs. a track ending). Repeat-one only loops on
  // natural end, so pressing next still advances.
  function next(manual) {
    if (manual) reels.whir(1);
    const ep = activeIsEpisode();
    // Episodes are listed newest-first, so "forward" means newer (toward index 0)
    // — finishing one plays the next-newer episode and stops at the newest.
    if (ep) { if (qi - 1 >= 0) go(qi - 1, true); return; }
    if (!manual && repeatMode === "one") { audio.currentTime = 0; audio.play().catch(() => {}); return; }
    if (qi + 1 < queue.length) go(qi + 1, true);
    else if (repeatMode === "all") go(0, true);
    // else: end of queue — stop.
  }
  function prev() {
    reels.whir(-1);
    if (qi >= 0 && audio.currentTime > 3) { audio.currentTime = 0; return; }  // restart current first
    if (activeIsEpisode()) { if (qi + 1 < queue.length) go(qi + 1, true); return; }  // back = older
    if (qi > 0) go(qi - 1, true);
    else if (repeatMode === "all") go(queue.length - 1, true);
  }

  // ---------- podcast controls: skip and speed ----------
  const SPEEDS = [1, 1.25, 1.5, 1.75, 2];
  let episodeSpeed = Number(localStorage.getItem("tapes-ep-speed")) || 1;
  function renderSpeed() {
    const label = `${episodeSpeed}×`;
    $("speedBtn").textContent = label;
    $("speedBtn").setAttribute("aria-label", `Playback speed ${label}`);
  }
  function cycleSpeed() {
    episodeSpeed = SPEEDS[(SPEEDS.indexOf(episodeSpeed) + 1) % SPEEDS.length];
    localStorage.setItem("tapes-ep-speed", String(episodeSpeed));
    if (activeIsEpisode()) audio.playbackRate = episodeSpeed;
    renderSpeed();
  }
  function skipBy(sec) {
    if (audio.duration) seekTo(Math.min(audio.duration - 0.5, audio.currentTime + sec));
  }
  // Every seek (scrub, skip, lock screen) winds the reels the way it went.
  function seekTo(at) {
    const to = Math.max(0, at);
    reels.whir(to - audio.currentTime);
    audio.currentTime = to;
    savePlaystate();
  }

  // ---------- Keep playing ----------
  // When the queue is about to run out, related songs follow (radio.py), so
  // the music doesn't stop; the tape turns over to side B as they start.
  let keepPlaying = localStorage.getItem("tapes-keep-playing") !== "off", extending = false;
  async function keepPlayingIfEnding() {
    if (!keepPlaying || extending || activeIsEpisode() || repeatMode !== "off" || qi < queue.length - 2) return;
    extending = true;
    const q = queue;
    try {
      const more = await jsend("api/keep-playing", "POST", {
        seed: queue.slice(Math.max(0, qi - 4), qi + 1).map((t) => t.id), exclude: queue.map((t) => t.id),
      }).then((r) => r.json());
      if (queue !== q || !keepPlaying) return;   // a new tape went in meanwhile
      const items = more.map((t) => ({ ...t, radio: true }));
      queue.push(...items);
      if (baseQueue !== queue) baseQueue.push(...items);
      prefetchNext();
      savePlaystate();
      updateUpNext();
    } catch (e) { console.warn("Keep playing:", e); }
    finally { extending = false; }
  }
  function setKeepPlaying(on) {
    keepPlaying = on;
    localStorage.setItem("tapes-keep-playing", on ? "on" : "off");
    toast(on ? "Keep playing on" : "Keep playing off");
    if (on) keepPlayingIfEnding();
    else {   // take back the songs it added that haven't played yet
      const kept = (t, i) => i <= qi || !t.radio;
      queue = queue.filter(kept);
      baseQueue = baseQueue.filter((t) => !t.radio || queue.includes(t));
      prefetchNext();
      savePlaystate();
      updateUpNext();
    }
  }

  // ---------- shuffle / repeat ----------
  function setShuffle(on) {
    shuffleOn = on;
    localStorage.setItem("tapes-shuffle", on ? "1" : "0");
    $("shuffleBtn").classList.toggle("active", on);
    $("shuffleBtn").setAttribute("aria-pressed", String(on));
    const cur = currentTrack();
    if (!cur) return;
    if (on) {
      queue = [cur, ...shuffleArray(baseQueue.filter((t) => t.id !== cur.id))];
      qi = 0;
    } else {
      queue = baseQueue.slice();
      qi = Math.max(0, queue.findIndex((t) => t.id === cur.id));
    }
    prefetchNext();
    savePlaystate();
    updateUpNext();
  }
  function cycleRepeat() {
    repeatMode = repeatMode === "off" ? "all" : repeatMode === "all" ? "one" : "off";
    localStorage.setItem("tapes-repeat", repeatMode);
    updateRepeatBtn();
    prefetchNext();   // what follows depends on the repeat mode
    keepPlayingIfEnding();
  }
  function updateRepeatBtn() {
    const b = $("repeatBtn");
    b.classList.toggle("active", repeatMode !== "off");
    b.setAttribute("aria-pressed", String(repeatMode !== "off"));
    b.innerHTML = repeatMode === "one" ? ICONS.repeatOne : ICONS.repeat;
    b.title = repeatMode === "one" ? "Repeat one"
      : repeatMode === "all" ? "Repeat all" : "Repeat";
  }

  // ---------- queue editing ----------
  // A queued song plays next: after the current one and anything queued before
  // it, not at the end of the album or list that's playing.
  function insertQueued(list, from, item) {
    let at = from + 1;
    while (at < list.length && list[at].queued) at++;
    list.splice(at, 0, item);
  }
  function addToQueue(t) {
    if (qi < 0 || activeIsEpisode()) { playFromList([t], 0); toast(`Playing “${t.title}”`); return; }
    toast(`Queued “${t.title}”`);
    const item = { ...t, queued: true };
    insertQueued(queue, qi, item);
    // Shuffled, the unshuffled order keeps it too, for when shuffle goes off.
    if (shuffleOn) insertQueued(baseQueue, baseQueue.findIndex((x) => x.id === currentTrack().id), item);
    else baseQueue = queue.slice();
    prefetchNext();
    savePlaystate();
    updateUpNext();
  }

  // ---------- Up Next (bottom bar) ----------
  // Only present when something is queued; collapsed it's a slim bar previewing
  // the next track, expanding upward into the full queue.
  const upnext = $("upnext");
  function updateUpNext() {
    if (qi < 0 || !queue.length) {
      upnext.hidden = true;
      upnext.classList.remove("expanded");
      return;
    }
    upnext.hidden = false;
    const remaining = queue.length - qi - 1;
    $("upnextCount").textContent = remaining > 0 ? String(remaining) : "";
    if (upnext.classList.contains("expanded")) renderQueue();
  }
  function toggleUpNext() {
    upnext.classList.toggle("expanded");
    if (upnext.classList.contains("expanded")) renderQueue();
  }
  // Tapping outside the open queue closes it (it's a sheet on phones).
  document.addEventListener("click", (e) => {
    if (upnext.classList.contains("expanded") && !upnext.contains(e.target)) upnext.classList.remove("expanded");
  });
  function renderQueue() {
    const el = $("queueList");
    el.innerHTML = "";
    if (!queue.length) { el.innerHTML = `<div class="queue-empty">Nothing up next. Use + → Queue on any song.</div>`; return; }
    queue.forEach((t, i) => {
      const li = document.createElement("li");
      li.dataset.id = t.id;
      li.className = "q-row" + (i === qi ? " active" : "")
        + (t.radio && !queue[i - 1]?.radio ? " side-b" : "");   // where Keep playing takes over
      li.innerHTML = `<span class="q-drag drag-handle" title="Drag to reorder" aria-hidden="true">${ICONS.grip}</span>
        <span class="q-meta"><div class="q-title"></div><div class="q-sub"></div></span>
        <button class="q-btn q-rm" title="Remove from queue" aria-label="Remove from queue">${ICONS.x}</button>`;
      li.querySelector(".q-title").textContent = t.title;
      li.querySelector(".q-title").title = t.title;
      li.querySelector(".q-sub").textContent = subLine(t);
      li.querySelector(".q-meta").addEventListener("click", () => queueJump(i));
      li.querySelector(".q-drag").addEventListener("click", (e) => e.stopPropagation());
      li.querySelector(".q-rm").addEventListener("click", (e) => { e.stopPropagation(); queueRemove(i); });
      el.appendChild(li);
    });
  }
  function queueJump(i) { qi = i; loadCurrent(true); }
  function queueRemove(i) {
    const wasCurrent = i === qi;
    const cur = queue[qi];
    queue.splice(i, 1);
    baseQueue = queue.slice();
    if (!queue.length) {
      qi = -1; audio.pause(); audio.removeAttribute("src");
      updateUpNext(); markActive(); updateMini(); savePlaystate(); return;
    }
    if (wasCurrent) {
      qi = Math.min(i, queue.length - 1);
      loadCurrent(!audio.paused);     // updateUpNext() runs inside loadCurrent
    } else {
      qi = queue.indexOf(cur);
      updateUpNext(); markActive(); prefetchNext(); savePlaystate();
    }
  }

  // ---------- drag-to-reorder (mouse + touch) ----------
  function enableReorder(el, onDrop) {
    let dragLi = null, moved = false, offset = 0;
    el.addEventListener("pointerdown", (e) => {
      const handle = e.target.closest(".drag-handle");
      if (!handle) return;
      dragLi = handle.closest("li");
      if (!dragLi) return;
      moved = false;
      offset = 0;
      e.preventDefault();
      try { dragLi.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
      dragLi.classList.add("dragging");   // lift immediately so the grab registers
    });
    el.addEventListener("pointermove", (e) => {
      if (!dragLi) return;
      moved = true;
      // Reorder: drop the row before whichever sibling the pointer is over.
      const sibs = [...el.querySelectorAll("li:not(.dragging)")];
      const after = sibs.find((r) => {
        const rc = r.getBoundingClientRect();
        return e.clientY < rc.top + rc.height / 2;
      });
      if (after) el.insertBefore(dragLi, after);
      else el.appendChild(dragLi);
      // Keep the lifted row centred under the pointer even though reflow moved
      // its slot — recompute the translate from its post-reflow layout position.
      const rect = dragLi.getBoundingClientRect();
      const layoutCenter = rect.top + rect.height / 2 - offset;
      offset = e.clientY - layoutCenter;
      dragLi.style.transform = `translateY(${offset}px)`;
    });
    function end() {
      if (!dragLi) return;
      dragLi.classList.remove("dragging");
      dragLi.style.transform = "";
      dragLi = null;
      offset = 0;
      if (moved) onDrop([...el.querySelectorAll("li")].map((li) => Number(li.dataset.id)));
    }
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
  }
  function onTrackReorder(ids) {
    view = ids.map((id) => view.find((t) => t.id === id)).filter(Boolean);
    renderTracks(view);
    if (currentTape && currentTape.kind === "user")
      jsend(`api/playlists/${currentTape.key}/order`, "PUT", { track_ids: ids });
  }
  function onQueueReorder(ids) {
    const cur = queue[qi];
    queue = ids.map((id) => queue.find((t) => t.id === id)).filter(Boolean);
    qi = queue.indexOf(cur);
    baseQueue = queue.slice();
    updateUpNext(); markActive(); prefetchNext(); savePlaystate();
  }

  // ---------- track edit / delete ----------
  let editing = null;
  function openEdit(t) {
    editing = t;
    $("edTitle").value = t.title || "";
    $("edArtist").value = t.artist || "";
    $("edAlbum").value = t.album || "";
    $("edTrackNo").value = t.track_no == null ? "" : t.track_no;
    $("editModal").hidden = false;
    $("edTitle").focus();
  }
  function closeEdit() { $("editModal").hidden = true; editing = null; }
  // Tapping outside or Escape with unsaved changes asks first; Cancel doesn't.
  async function dismissEdit() {
    if (editing && Object.keys(editChanges()).length
        && !(await askConfirm("Discard your changes?", { ok: "Discard", danger: true }))) {
      $("edTitle").focus();   // keep editing
      return;
    }
    closeEdit();
  }
  // Only what changed, so a field the form couldn't show (or the user didn't
  // touch) is never overwritten with a blank.
  function editChanges() {
    const before = {
      title: editing.title || "", artist: editing.artist || "",
      album: editing.album || "", track_no: editing.track_no == null ? "" : String(editing.track_no),
    };
    const after = {
      title: $("edTitle").value, artist: $("edArtist").value,
      album: $("edAlbum").value, track_no: $("edTrackNo").value,
    };
    return Object.fromEntries(Object.entries(after).filter(([k, v]) => v.trim() !== before[k].trim()));
  }
  async function saveEdit() {
    if (!editing) return;
    const id = editing.id;
    const changes = editChanges();
    if (!Object.keys(changes).length) { closeEdit(); return; }
    let updated;
    try {
      updated = await jsend(`api/tracks/${id}`, "PATCH", changes).then((r) => r.json());
    } catch (e) { console.error(e); toast(errText(e, "Couldn't save changes.")); return; }
    // Patch every in-memory copy of this track (view, queue, source order).
    [...view, ...queue, ...baseQueue].forEach((x) => {
      if (x && x.id === id) {
        x.title = updated.title; x.artist = updated.artist;
        x.album = updated.album; x.track_no = updated.track_no;
      }
    });
    closeEdit();
    applySearch();
    const cur = currentTrack();
    if (cur && cur.id === id) { paintLabel(cur); updateMini(); }   // the label, without reloading audio
    loadShelf();   // album/artist counts may have shifted
  }
  // Delete goes to the trash; the toast's Undo brings it back (file, tapes and
  // play history included).
  async function deleteTrack(t) {
    try { await jsend(`api/tracks/${t.id}`, "DELETE"); }
    catch (e) { console.error(e); toast(errText(e, "Couldn't delete that song.")); return; }
    const idx = queue.findIndex((x) => x.id === t.id);
    if (idx >= 0) queueRemove(idx);   // handles current-track/qi/Up Next cleanup
    view = view.filter((x) => x.id !== t.id);
    applySearch();
    loadShelf();
    toast(`Deleted “${t.title}”`, { action: "Undo", onAction: () => restoreTrack(t) });
  }
  async function restoreTrack(t) {
    try { await jsend(`api/tracks/${t.id}/restore`, "POST"); }
    catch (e) { console.error(e); toast(errText(e, "Couldn't restore that song.")); return; }
    await loadShelf();
    await reloadCurrentList();
    toast(`Restored “${t.title}”`);
  }
  // Re-fetch whichever track list is open (after an undo changes it).
  async function reloadCurrentList() {
    if ($("tracksView").hidden) return;
    if (currentTape) {
      view = await jget(`api/playlists/${currentTape.key}/tracks?sort=${currentSort}`);
    } else if (trackParent === "albums" || trackParent === "artists") {
      const name = $("tapeTitle").textContent;
      view = await jget(trackParent === "albums"
        ? `api/albums/tracks?album=${encodeURIComponent(name)}`
        : `api/artists/tracks?artist=${encodeURIComponent(name)}`);
    }
    applySearch();
  }

  // ---------- first run ----------
  function openAdd(m) {
    setMode(m);
    $("dlPanel").hidden = false;
    openDlStream();
    $("dlUrl").focus();
  }
  $("firstRip").addEventListener("click", () => openAdd("music"));
  $("firstFollow").addEventListener("click", () => openAdd("podcasts"));

  // ---------- tidying + album edits ----------
  async function tidy(ids) {
    let changed = 0, ai = true;
    for (let i = 0; i < ids.length; i += 25) {
      const chunk = ids.slice(i, i + 25);
      if (ids.length > 25) toast(`Tidying ${i + 1}–${i + chunk.length} of ${ids.length}…`);
      const r = await jsend("api/tracks/tidy", "POST", { track_ids: chunk }).then((x) => x.json());
      changed += r.changed.length; ai = r.ai;
    }
    await loadShelf();
    await reloadCurrentList();
    const n = (k) => `${k} song${k === 1 ? "" : "s"}`;
    toast(`Tidied ${n(ids.length)} — ${changed ? `${changed} changed` : "nothing needed changing"}`
      + (ai ? "" : ". AI tidying isn't set up (add ANTHROPIC_API_KEY)"));
  }
  $("tidyBtn").addEventListener("click", async () => {
    const btn = $("tidyBtn"); btn.disabled = true; btn.textContent = "Tidying…";
    try { await tidy(view.map((t) => t.id)); }
    catch (e) { console.error(e); toast(errText(e, "Couldn't tidy those songs.")); }
    finally { btn.disabled = false; btn.textContent = "Tidy all"; }
  });

  async function saveAlbum(album, { name, artist } = {}) {
    const r = await jsend("api/albums", "PATCH", { album, name, artist }).then((x) => x.json());
    await loadShelf();
    if (name && name !== album) toast(`Renamed album to “${r.album}”`);
    return r;
  }
  let albumCoverFile = null;
  $("albumEditBtn").addEventListener("click", () => {
    const album = $("tapeTitle").textContent;
    $("alName").value = album;
    $("alArtist").value = "";
    albumCoverFile = null;
    const withCover = view.find((t) => t.has_cover);
    if (withCover) $("alCoverPreview").src = coverUrl(withCover.id); else $("alCoverPreview").removeAttribute("src");
    $("albumModal").hidden = false;
    $("alName").focus();
  });
  $("alCover").addEventListener("change", () => {
    albumCoverFile = $("alCover").files[0] || null;
    if (albumCoverFile) $("alCoverPreview").src = URL.createObjectURL(albumCoverFile);
  });
  const closeAlbum = () => { $("albumModal").hidden = true; $("alCover").value = ""; };
  $("alCancel").addEventListener("click", closeAlbum);
  $("albumModal").addEventListener("click", async (e) => {
    if (e.target !== $("albumModal")) return;
    const dirty = $("alName").value.trim() !== $("tapeTitle").textContent.trim()
      || $("alArtist").value.trim() || albumCoverFile;
    if (dirty && !(await askConfirm("Discard your changes?", { ok: "Discard", danger: true }))) return;
    closeAlbum();
  });
  $("alSave").addEventListener("click", async () => {
    const album = $("tapeTitle").textContent;
    const name = $("alName").value.trim();
    const artist = $("alArtist").value.trim();
    try {
      if (albumCoverFile) {
        const fd = new FormData();
        fd.append("album", album); fd.append("cover", albumCoverFile);
        const r = await fetch("api/albums/cover", { method: "POST", body: fd });
        if (!r.ok) throw await failure(r, "POST api/albums/cover");
      }
      let final = album;
      if ((name && name !== album) || artist) final = (await saveAlbum(album, { name, artist })).album;
      closeAlbum();
      await openAlbumTracks(final);
      if (final === album) toast("Album saved");   // a rename has said so already
    } catch (e) { console.error(e); toast(errText(e, "Couldn't save the album.")); }
  });

  // ---------- popover menus (add-to-tape, deck settings) ----------
  // Measure-then-clamp into the viewport; the caller picks the tentative top/left
  // and the grow-from corner. Shared by both menus.
  function placeMenu(el, top, left, origin) {
    const pad = 8, mw = el.offsetWidth;
    el.style.top = Math.max(pad, top) + "px";
    el.style.left = Math.min(Math.max(pad, left), window.innerWidth - mw - pad) + "px";
    el.style.transformOrigin = origin;
  }
  function menuItem(label, fn, close) {
    const item = document.createElement("div");
    item.className = "menu-item";
    item.setAttribute("role", "menuitem");
    item.tabIndex = -1;
    item.textContent = label;
    item.addEventListener("click", () => { fn(); close(); });
    return item;
  }
  // A menu item that swaps the menu in place for a sub-picker. Its click must NOT
  // bubble to the close-on-outside handler (the rebuild detaches this element,
  // which would otherwise read as an outside click and close the menu).
  function submenuItem(label, opener) {
    const item = document.createElement("div");
    item.className = "menu-item";
    item.setAttribute("role", "menuitem");
    item.tabIndex = -1;
    item.textContent = label;
    item.addEventListener("click", (ev) => { ev.stopPropagation(); opener(); });
    return item;
  }
  // Shown as the bottom sheet's title on phones (which song this menu is for).
  function menuHead(text) {
    const h = document.createElement("div");
    h.className = "menu-head";
    h.textContent = text;
    return h;
  }
  function menuSep() {
    const s = document.createElement("div");
    s.className = "menu-sep";
    return s;
  }
  // Reveal the popover then place it at the click (placement measures it visible).
  function showMenuAt(e) { menu.hidden = false; placeAtClick(e); }

  // ---------- add-to-tape menu ----------
  const menu = $("plMenu");
  function openMenu(e, t) {
    menu.dataset.for = t.id;
    menu.innerHTML = "";
    menu.appendChild(menuHead(t.title));
    // On a tape, taking a song off the tape comes first; deleting it from the
    // whole library is the rare, separate action below the divider.
    if (currentTape && currentTape.kind === "user") {
      menu.appendChild(menuItem("Remove from tape", () => removeFromTape(t), closeMenu));
    }
    menu.appendChild(menuItem("Edit details…", () => openEdit(t), closeMenu));
    menu.appendChild(menuItem("Tidy up", () => tidy([t.id]).catch((e) => toast(errText(e, "Couldn't tidy that song."))), closeMenu));
    menu.appendChild(menuSep());
    menu.appendChild(menuItem("Delete from library", () => deleteTrack(t), closeMenu));
    showMenuAt(e);
  }
  async function removeFromTape(t) {
    const tape = currentTape;
    try { await jsend(`api/playlists/${tape.key}/tracks/${t.id}`, "DELETE"); }
    catch (err) { console.error(err); toast(`Couldn't remove it from ${tape.name}.`); return; }
    view = view.filter((x) => x.id !== t.id);
    applySearch();
    loadShelf();
    toast(`Removed from ${tape.name}`);
  }
  // "Add to…" picker (the + button): the queue, or any tape. Distinct dataset key
  // so it doesn't clash with the ⋯ more-menu's open/close toggle on the same row.
  function openAddMenu(e, t) {
    menu.dataset.for = "add" + t.id;
    menu.innerHTML = "";
    menu.appendChild(menuHead(`Add “${t.title}” to…`));
    menu.appendChild(menuItem("Queue", () => addToQueue(t), closeMenu));
    const tapes = shelf.filter((s) => s.kind === "user");
    if (tapes.length) {
      menu.appendChild(menuSep());
      tapes.forEach((s) => menu.appendChild(menuItem(s.name, async () => {
        try {
          const r = await jsend(`api/playlists/${s.key}/tracks`, "POST", { track_id: t.id }).then((x) => x.json());
          toast(r.added ? `Added to ${r.tape}` : `Already on ${r.tape}`);
          loadShelf();
        } catch (e) { console.error(e); toast(errText(e, `Couldn't add it to ${s.name}.`)); }
      }, closeMenu)));
    }
    showMenuAt(e);
  }
  const closeMenu = () => { menu.hidden = true; delete menu.dataset.for; };
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });

  // ---------- the deck's ⋯ menu: settings ----------
  const deckBtn = $("deckMenuBtn"), deckMenu = $("deckMenu");
  const closeDeckMenu = () => { deckMenu.hidden = true; };
  // Under the ⋯ on a laptop; a bottom sheet on a phone (CSS).
  function openDeckMenu() {
    deckMenu.innerHTML = "";
    deckMenu.appendChild(menuHead("Deck"));
    if (!activeIsEpisode()) {   // levelling is for music only
      deckMenu.appendChild(menuItem(`Volume levelling: ${levelling ? "on" : "off"}`, toggleLevelling, closeDeckMenu));
    }
    deckMenu.appendChild(menuItem(`Keep playing: ${keepPlaying ? "on" : "off"}`, () => setKeepPlaying(!keepPlaying), closeDeckMenu));
    deckMenu.hidden = false;
    const r = deckBtn.getBoundingClientRect();
    placeMenu(deckMenu, r.bottom + 6, r.right - deckMenu.offsetWidth, "top right");
    syncHistory();
  }
  deckBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    deckMenu.hidden ? openDeckMenu() : closeDeckMenu();
  });
  document.addEventListener("click", (e) => {
    if (!deckMenu.hidden && !deckMenu.contains(e.target)) closeDeckMenu();
  });

  // ---------- downloads ----------
  let dlEvt = null, dlPrev = {};
  $("dlToggle").addEventListener("click", () => {
    const showing = $("dlPanel").hidden;
    $("dlPanel").hidden = !showing;
    $("dlToggle").setAttribute("aria-expanded", String(showing));
    if (showing) $("dlUrl").focus();
    if (showing) openDlStream(); else closeDlStream();
  });
  $("dlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("dlUrl").value.trim();
    if (!url) return;
    if (mode === "podcasts") { await addPodcast(url); return; }
    const btn = $("dlSubmit");
    btn.disabled = true;
    try {
      const r = await jsend("api/downloads", "POST", { url }).then((x) => x.json());
      $("dlUrl").value = "";
      toast(r.playlist ? `Ripping ${r.queued} songs into a new tape, “${r.playlist}”` : "Ripping…");
      // Count these as in flight, so even an instant result (already in the
      // library) gets announced.
      (r.job_ids || []).forEach((id) => { dlPrev[id] = { finished: false }; });
      handleJobs(await jget("api/downloads"));   // show the job right away
      openDlStream();
    } catch (err) {
      console.error(err); toast(errText(err, "Couldn't start that rip."));
    } finally { btn.disabled = false; }
  });
  async function addPodcast(url) {
    const btn = $("dlSubmit");
    btn.disabled = true;
    try {
      const r = await jsend("api/podcast/add", "POST", { url }).then((x) => x.json());
      $("dlUrl").value = "";
      const msg = r.assigned ? `Added to “${r.assigned.title}”`
        : r.loose ? "Added to Unsorted episodes"
        : r.created === false ? `${r.added} new episode${r.added === 1 ? "" : "s"}`
        : `Following “${r.title}”`;
      toast(msg);
      openPodcasts();
    } catch (err) {
      console.error(err); toast(errText(err, "Couldn't add that — check the link."));
    } finally { btn.disabled = false; }
  }
  function openDlStream() {
    if (dlEvt) return;  // already streaming
    jget("api/downloads").then(handleJobs).catch(() => {});   // recent results too
    dlEvt = new EventSource("api/downloads/stream");
    dlEvt.onmessage = (e) => handleJobs(JSON.parse(e.data));
    dlEvt.addEventListener("done", closeDlStream);
    // transient drops auto-reconnect; nothing to do on error
  }
  function closeDlStream() {
    if (dlEvt) { dlEvt.close(); dlEvt = null; }
  }
  // What a finished job means, in words. `t` is the track (or episode title).
  function jobOutcomeText(j) {
    const name = j.track ? j.track.title : j.message;
    if (j.status === "error") return j.message || "Couldn't rip that link.";
    if (j.kind === "podcast") return `Downloaded “${name}”`;
    if (j.outcome === "exists") return `You already have “${name}”`;
    if (j.outcome === "duplicate") return `Same recording as “${name}” — kept the one you have`;
    return `Added “${name}”`;
  }
  function handleJobs(jobs) {
    // A job we saw queued/running is now finished → announce it once and route
    // the follow-up (shelf refresh for music, play-when-ready for podcasts).
    let musicCompleted = false;
    for (const j of jobs) {
      const prev = dlPrev[j.id];
      const finished = j.status === "done" || j.status === "error";
      if (prev && !prev.finished && finished) {
        if (j.kind === "podcast") onPodcastJobDone(j.episode_id);
        else { musicCompleted = true; toast(jobOutcomeText(j)); }
      }
    }
    dlPrev = {};
    jobs.forEach((j) => { dlPrev[j.id] = { finished: j.status === "done" || j.status === "error" }; });
    if (musicCompleted) onDownloadDone();

    const el = $("dlList");
    el.innerHTML = "";
    jobs.forEach((j) => {
      const li = document.createElement("li");
      li.className = "dl-job " + j.status;
      if (j.status === "queued" || j.status === "running") {
        li.innerHTML = `<div class="dl-msg"></div>
          <div class="dl-bar"><div class="dl-bar-fill" style="width:${j.progress}%"></div></div>`;
        li.querySelector(".dl-msg").textContent = j.status === "queued" ? `Waiting… ${j.url}`
          : j.message && j.message !== "downloading" ? `${j.message} · ${Math.round(j.progress)}%`
          : `Starting… ${j.url}`;
      } else {
        // Finished: what happened, what it was saved as, and what to do next.
        li.innerHTML = `<div class="dl-row"><div class="dl-meta"><div class="dl-msg"></div><div class="dl-sub"></div></div>
          <div class="dl-actions"></div>
          <button class="dl-dismiss" title="Dismiss" aria-label="Dismiss">${ICONS.x}</button></div>`;
        li.querySelector(".dl-msg").textContent = jobOutcomeText(j);
        const sub = j.status === "error" ? j.url
          : j.track ? [j.track.artist, j.track.album].filter(Boolean).join(" · ") || "No artist or album yet" : "";
        li.querySelector(".dl-sub").textContent = sub;
        const actions = li.querySelector(".dl-actions");
        if (j.track && j.status === "done") {
          const play = document.createElement("button");
          play.className = "btn btn-ghost dl-act"; play.textContent = "Play";
          play.addEventListener("click", () => playFromList([j.track], 0));
          actions.appendChild(play);
          const add = document.createElement("button");
          add.className = "btn btn-ghost dl-act"; add.textContent = "Add to…";
          add.addEventListener("click", (e) => { e.stopPropagation(); openAddMenu(e, j.track); });
          actions.appendChild(add);
          if (j.outcome === "added") {
            const edit = document.createElement("button");
            edit.className = "btn btn-ghost dl-act"; edit.textContent = "Edit";
            edit.addEventListener("click", () => openEdit(j.track));
            actions.appendChild(edit);
          }
        }
        li.querySelector(".dl-dismiss").addEventListener("click", async () => {
          li.remove();
          try { await jsend(`api/downloads/${j.id}`, "DELETE"); } catch (_) { /* best effort */ }
        });
      }
      el.appendChild(li);
    });
  }
  async function onDownloadDone() {
    await loadShelf();
    if (!$("tracksView").hidden) {
      const s = shelf.find((x) => x.name === $("tapeTitle").textContent);
      if (s && (s.key === "all" || s.key === "singles")) openTape(s.key, s.name, s.kind);
    }
  }

  // ---------- playstate persistence ----------
  let saveTimer = null, sessTimer = null, lastMusicSave = 0;
  function savePlaystate() {
    const cur = currentTrack();
    if (cur && cur.kind === "episode") {
      // Per-episode position is the source of truth; the session snapshot (queue +
      // cursor) just lets a reload restore the podcast deck. Separate 'podcast'
      // context → never clobbers the music session.
      saveEpisodeProgress(cur);
      savePodcastSession();
      return;
    }
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => jsend("api/playstate", "PUT",
      { context: "music", queue: queue.map((t) => t.id), index: qi, position: audio.currentTime || 0 }), 400);
  }
  // Save just the podcast deck snapshot (no position — that rides on the episode).
  // Safe to call on load, unlike saveEpisodeProgress which would store currentTime 0.
  function savePodcastSession() {
    clearTimeout(sessTimer);
    sessTimer = setTimeout(() => jsend("api/playstate", "PUT",
      { context: "podcast", queue: queue.map((t) => t.id), index: qi }), 400);
  }
  // Per-episode resume — debounced; the resume point lives on the episode.
  let epSaveTimer = null, lastEpSave = 0, resumeTarget = 0;
  // Seek the loaded episode to its saved position. Handles the case where metadata
  // is already available (re-tapping a loaded episode → loadedmetadata won't fire
  // again). resumeTarget gates saving until we've actually reached the point, so an
  // early timeupdate at ~0 can't clobber the saved position back to the start.
  function resumeEpisodeTo(pos) {
    resumeTarget = pos || 0;
    if (!resumeTarget) return;
    const seek = () => { try { audio.currentTime = resumeTarget; } catch (_) { /* not seekable yet */ } };
    if (audio.readyState >= 1) seek();
    else audio.addEventListener("loadedmetadata", seek, { once: true });
  }
  function saveEpisodeProgress(t) {
    const pos = audio.currentTime || 0;
    t.position = pos;
    clearTimeout(epSaveTimer);
    epSaveTimer = setTimeout(() =>
      jsend(`api/podcast/episodes/${t.id}/progress`, "PUT", { position: pos }).catch(() => {}), 800);
  }
  function maybeSaveEpisodeTick(t) {
    // Hold off until playback reaches the resume point, so the first tick (at ~0,
    // before the seek lands) can't overwrite a saved position with the start.
    if (resumeTarget) {
      if (audio.currentTime < resumeTarget - 2) return;
      resumeTarget = 0;
    }
    const now = Date.now();
    if (now - lastEpSave < 5000) return;   // throttle the timeupdate firehose
    lastEpSave = now;
    saveEpisodeProgress(t);
  }
  async function restorePlaystate() {
    // Restores whichever context (music or podcast) was last active — the server
    // returns the most-recently-updated session, hydrated.
    const ps = await jget("api/playstate");
    if (!ps.queue || !ps.queue.length) return;
    const idx = Math.min(ps.index || 0, ps.queue.length - 1);
    const cur = ps.queue[idx];
    if (!cur) return;
    // Don't auto-fetch an undownloaded episode on a passive reload — you can only
    // resume what you already have; tapping it will download as usual.
    if (cur.kind === "episode" && cur.status !== "ready" && !canStreamRemote(cur)) return;
    queue = ps.queue;   // already hydrated server-side
    baseQueue = queue.slice();
    qi = idx;
    loadCurrent(false);   // episode resume is handled inside loadCurrent
    if (cur.kind !== "episode") {
      audio.addEventListener("loadedmetadata", function once() {
        audio.currentTime = ps.position || 0;
        audio.removeEventListener("loadedmetadata", once);
      });
    }
  }

  // ---------- events ----------
  // The transport keys give a short buzz under the thumb, like a deck's keys.
  const key = (fn) => () => { navigator.vibrate?.(12); fn(); };
  playBtn.addEventListener("click", key(togglePlay));
  $("prevBtn").addEventListener("click", key(() => prev()));
  $("nextBtn").addEventListener("click", key(() => next(true)));
  $("miniPlay").addEventListener("click", key(togglePlay));
  $("miniNext").addEventListener("click", key(() => next(true)));
  // Tap the tape: full screen, just the cassette (its gestures are below).
  const immersive = () => app.classList.contains("immersive");
  let swiped = false;   // a swipe on the tape isn't also a tap
  cassette.addEventListener("click", (e) => {
    if (swiped) { swiped = false; return; }
    if (immersive()) return;   // the full-screen gestures handle it
    e.stopPropagation();
    DeckFX.setImmersive(true);
  });

  // ---------- swipes ----------
  // On the deck: down closes it (phones), and left or right on the tape skips
  // to the next or previous song. On the mini player: up opens the deck.
  const main = document.querySelector(".main");
  const SWIPE = 60, CLOSE = 110;
  let touch = null;
  main.addEventListener("touchstart", (e) => {
    swiped = false;   // a new gesture: whatever the last swipe was, it's over
    if (e.touches.length !== 1 || e.target.closest(".controls, .upnext, .nav-toggle, .deck-menu-btn, .menu")) { touch = null; return; }
    const p = e.touches[0];
    touch = { x: p.clientX, y: p.clientY, t: performance.now(), axis: null, onTape: !!e.target.closest("#cassette") };
  }, { passive: true });
  main.addEventListener("touchmove", (e) => {
    if (!touch) return;
    const p = e.touches[0], dx = p.clientX - touch.x, dy = p.clientY - touch.y;
    if (!touch.axis && Math.hypot(dx, dy) > 10) touch.axis = Math.abs(dx) > Math.abs(dy) ? "x" : "y";
    if (touch.axis === "y" && dy > 0 && isMobile() && app.classList.contains("deck-open") && !immersive()) {
      main.classList.add("dragging");
      main.style.transform = `translateY(${dy}px)`;   // the deck follows the finger down
    }
  }, { passive: true });
  main.addEventListener("touchend", (e) => {
    if (!touch) return;
    const p = e.changedTouches[0], dx = p.clientX - touch.x, dy = p.clientY - touch.y;
    const fast = Math.abs(dy) / (performance.now() - touch.t) > 0.6;
    if (main.classList.contains("dragging")) {
      main.classList.remove("dragging");
      main.style.transform = "";
      if (dy > CLOSE || (dy > 40 && fast)) closeDeck();
    } else if (touch.axis === "y" && dy > SWIPE && immersive()) {
      swiped = true;
      DeckFX.setImmersive(false);   // swipe down: the controls come back
    } else if (touch.axis === "x" && touch.onTape && Math.abs(dx) > SWIPE) {
      swiped = true;
      navigator.vibrate?.(12);
      if (dx < 0) next(true); else prev();
    }
    touch = null;
  }, { passive: true });
  // ---------- full-screen tape: the tape is the control ----------
  // With just the tape on screen (a phone on its side, or after tapping the
  // tape) there are no buttons:
  //   tap the left / right side   previous / next song
  //   tap the middle              play / pause
  //   double-tap a side           back / forward 10 seconds
  //   press and hold a side       rewind / fast-forward while held
  //   swipe down                  the controls come back (above)
  //   shake the phone             shuffle (below; works whenever it's playing)
  // A small icon flashes over the tape to say what happened (the words are
  // for screen readers; full screen is about the tape, not labels).
  const hint = $("gestureHint");
  let hintTimer = 0;
  function showHint(icon, text) {
    hint.innerHTML = icon || `<span>${text}</span>`;
    hint.setAttribute("aria-label", text);
    hint.classList.add("show");
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => hint.classList.remove("show"), 800);
    navigator.vibrate?.(12);
  }
  const DOUBLE_MS = 280, HOLD_MS = 450, WIND_STEP_S = 2.5, WIND_EVERY_MS = 120;
  const zoneAt = (x) => (x < innerWidth / 3 ? -1 : x > innerWidth * 2 / 3 ? 1 : 0);   // left, middle, right
  let lastTap = null, pendingTap = 0, hold = null, winding = false;
  main.addEventListener("pointerdown", (e) => {
    if (!immersive() || e.target.closest(".controls, .nav-toggle, .deck-menu-btn")) return;
    const zone = zoneAt(e.clientX);
    if (!zone) return;
    hold = { x: e.clientX, y: e.clientY, timer: setTimeout(() => {   // held: wind the tape
      winding = true;
      showHint(zone > 0 ? ICONS.next : ICONS.prev, zone > 0 ? "Fast-forward" : "Rewind");
      hold.wind = setInterval(() => skipBy(zone * WIND_STEP_S), WIND_EVERY_MS);
    }, HOLD_MS) };
  });
  main.addEventListener("pointermove", (e) => {
    if (hold && !winding && Math.hypot(e.clientX - hold.x, e.clientY - hold.y) > 12) { clearTimeout(hold.timer); hold = null; }   // a swipe
  });
  const endHold = () => { if (hold) { clearTimeout(hold.timer); clearInterval(hold.wind); hold = null; } };
  main.addEventListener("pointerup", endHold);
  main.addEventListener("pointercancel", () => { endHold(); winding = false; });
  main.addEventListener("contextmenu", (e) => { if (immersive()) e.preventDefault(); });   // a long press winds, no menu
  main.addEventListener("click", (e) => {
    if (!immersive() || e.target.closest(".controls, .nav-toggle, .deck-menu-btn")) return;
    if (winding) { winding = false; return; }
    if (swiped) { swiped = false; return; }
    const zone = zoneAt(e.clientX), now = performance.now();
    if (!zone) {
      togglePlay();
      showHint(audio.paused ? ICONS.pause : ICONS.play, audio.paused ? "Paused" : "Playing");
      return;
    }
    if (lastTap && lastTap.zone === zone && now - lastTap.t < DOUBLE_MS) {   // double tap: ±10 s
      clearTimeout(pendingTap);
      lastTap = null;
      skipBy(zone * 10);
      showHint(null, zone > 0 ? "+10" : "−10");
      return;
    }
    lastTap = { zone, t: now };
    pendingTap = setTimeout(() => {   // a single tap, once it's clearly not a double
      lastTap = null;
      if (zone > 0) { next(true); showHint(ICONS.next, "Next"); } else { prev(); showHint(ICONS.prev, "Previous"); }
    }, DOUBLE_MS);
  });

  // Shake to shuffle: two hard jolts within a second while tapes is on
  // screen and music is playing (walking with it doesn't come close).
  const JOLT = 18;   // m/s², gravity excluded
  let jolts = [], lastShuffle = 0;
  window.addEventListener("devicemotion", (e) => {
    const a = e.acceleration;
    if (!a || a.x == null || document.hidden || qi < 0 || activeIsEpisode()) return;
    const now = performance.now();
    if (Math.hypot(a.x, a.y, a.z) < JOLT || now - lastShuffle < 2000) return;
    if (jolts.length && now - jolts[jolts.length - 1] < 150) return;   // the same jolt, still settling
    jolts = jolts.filter((t) => now - t < 1000).concat(now);
    if (jolts.length < 2) return;
    jolts = [];
    lastShuffle = now;
    setShuffle(true);
    showHint(ICONS.shuffle, "Shuffled");
  });

  let miniY = null;
  $("mini").addEventListener("touchstart", (e) => { miniY = e.touches[0].clientY; }, { passive: true });
  $("mini").addEventListener("touchend", (e) => {
    if (miniY !== null && miniY - e.changedTouches[0].clientY > 40) openDeck();
    miniY = null;
  }, { passive: true });
  // A phone turned on its side is for listening: the tape fills the screen
  // (a tap brings the controls back); upright again, the deck returns.
  const sideways = window.matchMedia("(max-height: 480px) and (orientation: landscape)");
  const onSideways = () => {
    if (sideways.matches) app.classList.add("nav-collapsed");
    DeckFX.setImmersive(sideways.matches);
    syncHistory();
  };
  sideways.addEventListener("change", onSideways);
  onSideways();
  DeckFX.meter.attach(audio);
  $("shuffleBtn").addEventListener("click", () => setShuffle(!shuffleOn));
  $("repeatBtn").addEventListener("click", cycleRepeat);
  $("sortSelect").addEventListener("change", async () => {
    if (!currentTape) return;
    currentSort = $("sortSelect").value;
    try { localStorage.setItem(`tapes-sort-${currentTape.key}`, currentSort); } catch (_) { /* private mode */ }
    view = await navGet(`api/playlists/${currentTape.key}/tracks?sort=${currentSort}`);
    applySearch();   // re-render, honouring any active search text
  });
  // Back to Albums or Artists fetches the list again: an edit, rename or delete
  // in the list just left may have changed its names and counts.
  $("backBtn").addEventListener("click", async () => {
    if (trackParent !== "albums" && trackParent !== "artists") { showView("shelf"); return; }
    showView("browse");
    try { browseRows = await jget(currentBrowse === "albums" ? "api/albums" : "api/artists"); applyBrowseSearch(); } catch (_) { /* keep the old list */ }
  });
  $("browseBack").addEventListener("click", () => showView("shelf"));
  $("browseSearch").addEventListener("input", debounce(applyBrowseSearch, 120));
  // Library-wide search from the shelf: typing jumps into All Tracks with the
  // query, keeping the cursor in the search field.
  // Keys typed while All Tracks loads stay in this field, then move across.
  let libJumping = false;
  $("libSearch").addEventListener("input", async () => {
    if (libJumping || !$("libSearch").value.trim()) return;
    libJumping = true;
    try { await openTape("all", "All Tracks", "smart"); } finally { libJumping = false; }
    $("search").value = $("libSearch").value;
    $("libSearch").value = "";
    applySearch();
    $("search").focus();
  });
  $("modeMusic").addEventListener("click", () => setMode("music"));
  $("modePods").addEventListener("click", () => setMode("podcasts"));
  $("edCancel").addEventListener("click", closeEdit);
  $("edSave").addEventListener("click", saveEdit);
  $("editModal").addEventListener("click", (e) => { if (e.target === $("editModal")) dismissEdit(); });
  $("editModal").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveEdit(); }
  });
  $("epBack").addEventListener("click", () => showView("podcasts"));
  [...document.querySelectorAll(".ep-filter-btn")].forEach((b) =>
    b.addEventListener("click", () => {
      epFilter = b.dataset.f;
      localStorage.setItem("tapes-ep-filter", epFilter);
      updateEpFilterBtns();
      applyEpisodeSearch();
    }));
  $("epSearch").addEventListener("input", debounce(applyEpisodeSearch, 120));
  $("showRefreshBtn").addEventListener("click", refreshCurrentShow);
  $("showDelBtn").addEventListener("click", deleteCurrentShow);
  // A song that can't play (missing or damaged file): say so and move on, but
  // stop after three failures in a row rather than racing through the queue.
  let playErrors = 0;
  audio.addEventListener("error", async () => {
    const t = currentTrack();
    if (!t || !audio.getAttribute("src")) return;
    // A dropped connection isn't a bad file (browsers often report it as an
    // unsupported source): if the server can't be reached, hold the place and
    // resume once it's back instead of skipping.
    if (held || !(await serverReachable())) {
      holdForReconnect();
      return;
    }
    if (t.kind === "episode") { toast("Couldn't play this episode."); return; }
    t.unavailable = true;
    [...$("trackList").children].forEach((li) => {
      if (Number(li.dataset.id) === t.id) li.classList.add("unavailable");
    });
    playErrors += 1;
    if (playErrors >= 3 || qi + 1 >= queue.length) {
      toast(`Couldn't play “${t.title}”.` + (playErrors >= 3 ? " Several songs in a row failed, so playback stopped." : ""));
      playErrors = 0;
      return;
    }
    toast(`Couldn't play “${t.title}” — skipping`);
    next(true);
  });
  audio.addEventListener("playing", () => { playErrors = 0; });

  // ---------- offline ----------
  // The service worker keeps the app and its lists available offline (see
  // static/js/sw.js); audio still needs the server. When the connection drops
  // mid-song, say so, keep the place, and pick up there once it's back.
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("sw.js", { scope: "./" })
        .catch((err) => console.warn("Service worker registration failed:", err));
    });
  }
  let held = null;          // { time, playing } while waiting to reconnect
  let reconnectTimer = null;
  async function serverReachable() {
    if (!navigator.onLine) return false;
    try { return (await fetch("healthz", { cache: "no-store" })).ok; }
    catch (_) { return false; }
  }
  function holdForReconnect() {
    const spot = { src: audio.currentSrc || audio.src, time: audio.currentTime || 0, playing: !audio.paused };
    if (held) {
      // Another failed load while waiting means a song was picked (or picked
      // again) offline: follow it, and play it once we're back.
      held = { ...spot, time: spot.src === held.src ? held.time : 0, playing: true };
      return;
    }
    held = spot;
    toast("Offline — reconnecting…");
    // navigator.onLine misses a dead Wi-Fi or a server restart, so also poll.
    reconnectTimer = setInterval(async () => {
      if (await serverReachable()) resumeAfterReconnect();
    }, 5000);
  }
  function resumeAfterReconnect() {
    if (!held) return;
    // A different song picked while offline starts from the top and plays.
    const same = (audio.currentSrc || audio.src) === held.src;
    const time = same ? held.time : 0, playing = same ? held.playing : true;
    held = null;
    clearInterval(reconnectTimer);
    toast("Back online");
    audio.addEventListener("loadedmetadata", function once() {
      audio.removeEventListener("loadedmetadata", once);
      audio.currentTime = time;
      if (playing) audio.play().catch(() => { /* needs a tap */ });
    });
    audio.load();
  }
  window.addEventListener("offline", () => {
    if (!audio.paused) toast("You're offline. This song plays on as far as it has loaded.");
  });
  window.addEventListener("online", () => { if (held) resumeAfterReconnect(); });
  audio.addEventListener("waiting", () => { if (!navigator.onLine) holdForReconnect(); });
  $("upnextBar").addEventListener("click", toggleUpNext);
  // Like songs, a deleted tape goes to the trash; the toast's Undo brings it
  // back with its track list. The songs themselves never leave the library.
  $("tapeDelBtn").addEventListener("click", async () => {
    if (!currentTape) return;
    const tape = currentTape;
    try { await jsend(`api/playlists/${tape.key}`, "DELETE"); }
    catch (e) { console.error(e); toast(errText(e, "Couldn't delete the tape.")); return; }
    currentTape = null;
    $("tracksView").hidden = true;
    $("shelfView").hidden = false;
    loadShelf();
    toast(`Deleted the tape “${tape.name}”`, { action: "Undo", onAction: async () => {
      try { await jsend(`api/playlists/${tape.key}/restore`, "POST"); }
      catch (e) { console.error(e); toast(errText(e, "Couldn't bring the tape back.")); return; }
      await loadShelf();
      toast(`Restored “${tape.name}”`);
    } });
  });
  $("navToggle").addEventListener("click", () =>
    isMobile() ? closeDeck() : app.classList.toggle("nav-collapsed"));
  // Desktop: a click outside the library collapses it, except on the deck's
  // controls (play, skip, scrubber…), menus and dialogs, so playing a song
  // doesn't also hide the list.
  document.addEventListener("click", (e) => {
    if (isMobile() || app.classList.contains("nav-collapsed") || !e.target.isConnected) return;
    const t = e.target;
    if (t.closest(".sidebar, button, a, input, select, textarea, [role='slider'], [role='menu'], .menu, .modal-scrim, .toast, .upnext, #navToggle")) return;
    app.classList.add("nav-collapsed");
  });
  $("miniOpen").addEventListener("click", openDeck);
  $("search").addEventListener("input", debounce(applySearch, 120));
  // Both "New tape" forms (music + podcast) share the create boilerplate.
  function wireCreateForm(formId, inputId, onSubmit) {
    $(formId).addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $(inputId).value.trim();
      if (!name) return;
      try { await onSubmit(name); } catch (err) { toast(errText(err, "Couldn't create that. Try again.")); return; }
      $(inputId).value = "";
    });
  }
  wireCreateForm("newTapeForm", "newTapeName", async (name) => {
    await jsend("api/playlists", "POST", { name }); loadShelf(); toast(`Created the tape “${name}”`);
  });
  wireCreateForm("newShowForm", "newShowName", async (name) => {
    await jsend("api/podcast/shows", "POST", { name }); showsData = null; openPodcasts(); toast(`Created the show “${name}”`);
  });

  audio.addEventListener("play", () => {
    cassette.classList.add("playing"); playBtn.innerHTML = ICONS.pause; updateMini(); reels.start(); DeckFX.meter.wake();
    const t = currentTrack();
    // Play counts are a music-catalog thing (no Play row for episodes).
    if (t && t.kind !== "episode" && t.id !== lastPlayed) {
      lastPlayed = t.id; jsend("api/plays", "POST", { track_id: t.id });
    }
  });
  audio.addEventListener("pause", () => {
    cassette.classList.remove("playing"); playBtn.innerHTML = ICONS.play; updateMini(); savePlaystate(); reels.stop();
  });
  audio.addEventListener("ended", () => {
    const t = currentTrack();
    if (t && t.kind === "episode") markEpisodePlayed(t);
    next(false);
  });
  audio.addEventListener("loadedmetadata", () => { durTime.textContent = fmt(audio.duration); });
  audio.addEventListener("timeupdate", () => {
    if (!scrubbing) {   // don't fight the user's drag
      curTime.textContent = fmt(audio.currentTime);
      if (audio.duration) paintScrub(audio.currentTime / audio.duration);
    }
    const t = currentTrack();
    updatePositionState();
    if (t && t.kind === "episode") maybeSaveEpisodeTick(t);
    else if (t && !audio.paused && Date.now() - lastMusicSave > 15000) {
      lastMusicSave = Date.now();   // keep the saved playhead fresh while playing
      savePlaystate();
    }
  });
  // Scrub: press, drag and release (mouse or finger). While dragging the fill,
  // thumb and time follow the pointer; the seek happens on release.
  let scrubbing = false;
  const scrubFrac = (e) => {
    const r = scrub.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  };
  function paintScrub(frac) {
    scrubFill.style.width = frac * 100 + "%";
    $("scrubThumb").style.left = frac * 100 + "%";
    scrub.setAttribute("aria-valuenow", String(Math.round(frac * 100)));
    $("miniFill").style.width = frac * 100 + "%";
  }
  scrub.addEventListener("pointerdown", (e) => {
    if (!audio.duration) return;
    scrubbing = true;
    scrub.classList.add("dragging");
    try { scrub.setPointerCapture(e.pointerId); } catch (_) { /* ignore */ }
    const f = scrubFrac(e);
    paintScrub(f);
    curTime.textContent = fmt(f * audio.duration);
  });
  scrub.addEventListener("pointermove", (e) => {
    if (!scrubbing) return;
    const f = scrubFrac(e);
    paintScrub(f);
    curTime.textContent = fmt(f * audio.duration);
  });
  function endScrub(e) {
    if (!scrubbing) return;
    scrubbing = false;
    scrub.classList.remove("dragging");
    seekTo(scrubFrac(e) * audio.duration);
  }
  scrub.addEventListener("pointerup", endScrub);
  scrub.addEventListener("pointercancel", () => { scrubbing = false; scrub.classList.remove("dragging"); });
  // Keyboard on the focused scrub: ←/→ 5 s.
  scrub.addEventListener("keydown", (e) => {
    if (!audio.duration || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    e.preventDefault();
    e.stopPropagation();
    seekTo(Math.min(audio.duration, audio.currentTime + (e.key === "ArrowRight" ? 5 : -5)));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !$("editModal").hidden && $("confirmModal").hidden) { dismissEdit(); return; }
    if (e.key === "Escape" && app.classList.contains("immersive")) { DeckFX.setImmersive(false); return; }
    if (e.key === "Escape") {
      const anyOpen = upnext.classList.contains("expanded") || !menu.hidden || !deckMenu.hidden;
      upnext.classList.remove("expanded"); closeMenu(); closeDeckMenu();
      if (!anyOpen && isMobile()) closeDeck();
    }
    if (["INPUT", "TEXTAREA", "SELECT"].includes(e.target.tagName) || e.target.isContentEditable) return;
    if (e.metaKey || e.ctrlKey || e.altKey) return;   // leave browser shortcuts alone
    if (document.querySelector(".modal-scrim:not([hidden])")) return;
    // A focused list row: Enter opens/plays it, ↑/↓ move between rows.
    if (e.target.matches && e.target.matches("li[tabindex]")) {
      if (e.key === "Enter") { e.preventDefault(); e.target.click(); return; }
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        let n = e.target;
        do { n = e.key === "ArrowDown" ? n.nextElementSibling : n.previousElementSibling; }
        while (n && !n.matches("li[tabindex]"));
        if (n) n.focus();
        return;
      }
    }
  });
  // Volume levelling: every song (or album) at the same loudness. On by default.
  let levelling = localStorage.getItem("tapes-levelling") !== "off";
  audio.setLevelling(levelling);
  function toggleLevelling() {
    levelling = !levelling;
    try { localStorage.setItem("tapes-levelling", levelling ? "on" : "off"); } catch (_) { /* private mode */ }
    audio.setLevelling(levelling);
    toast(levelling ? "Volume levelling on" : "Volume levelling off");
  }
  // Closing or backgrounding the page: send the playhead right away with a
  // beacon (a normal fetch would be cancelled, and savePlaystate debounces).
  function beaconPlaystate() {
    const cur = currentTrack();
    if (!cur || !navigator.sendBeacon) return;
    const send = (url, body) => navigator.sendBeacon(url,
      new Blob([JSON.stringify(body)], { type: "application/json" }));
    if (cur.kind === "episode") {
      send(`api/podcast/episodes/${cur.id}/progress`, { position: audio.currentTime || 0 });
      send("api/playstate", { context: "podcast", queue: queue.map((t) => t.id), index: qi });
    } else {
      send("api/playstate", {
        context: "music", queue: queue.map((t) => t.id), index: qi, position: audio.currentTime || 0,
      });
    }
  }
  window.addEventListener("pagehide", beaconPlaystate);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") beaconPlaystate();
  });

  // Keep the lock screen's position bar in sync (throttled).
  let lastPosState = 0;
  function updatePositionState() {
    if (!("mediaSession" in navigator) || !navigator.mediaSession.setPositionState || !audio.duration) return;
    const now = Date.now();
    if (now - lastPosState < 1000) return;
    lastPosState = now;
    try {
      navigator.mediaSession.setPositionState({
        duration: audio.duration, playbackRate: audio.playbackRate || 1,
        position: Math.min(audio.currentTime, audio.duration),
      });
    } catch (_) { /* ignore */ }
  }
  $("back15Btn").addEventListener("click", () => skipBy(-15));
  $("fwd30Btn").addEventListener("click", () => skipBy(30));
  $("speedBtn").addEventListener("click", cycleSpeed);

  // ---------- init ----------
  document.querySelectorAll(".ico[data-icon]").forEach((el) => { el.innerHTML = ICONS[el.dataset.icon] || ""; });
  $("back15Btn").innerHTML = ICONS.back15;
  $("fwd30Btn").innerHTML = ICONS.fwd30;
  renderSpeed();
  updateNavToggle();
  $("prevBtn").innerHTML = ICONS.prev;
  playBtn.innerHTML = ICONS.play;
  $("nextBtn").innerHTML = ICONS.next;
  deckBtn.innerHTML = ICONS.more;
  $("miniNext").innerHTML = ICONS.next;
  $("shuffleBtn").innerHTML = ICONS.shuffle;
  $("newTapeBtn").innerHTML = ICONS.plus;
  $("newShowBtn").innerHTML = ICONS.plus;
  $("upnextIco").innerHTML = ICONS.list;
  $("upnextCaret").innerHTML = ICONS.chevronUp;
  $("shuffleBtn").classList.toggle("active", shuffleOn);
  $("shuffleBtn").setAttribute("aria-pressed", String(shuffleOn));
  updateRepeatBtn();
  updateEpFilterBtns();
  enableReorder($("trackList"), onTrackReorder);
  enableReorder($("queueList"), onQueueReorder);
  let lastNetToast = 0;
  window.addEventListener("unhandledrejection", (e) => {
    console.error(e.reason);
    // A request that never reached the server (offline, server restarting):
    // one calm note, not a toast per background save.
    if (e.reason instanceof TypeError && !e.reason.userMessage) {
      if (held || Date.now() - lastNetToast < 15000) return;
      lastNetToast = Date.now();
      toast("Can't reach Tapes right now. It'll catch up when the connection's back.");
      return;
    }
    toast(errText(e.reason, "Something went wrong — please try again."));
  });
  historyLive = true;
  (async () => {
    try {
      await loadShelf();
      await restorePlaystate();
      updateUpNext();
    } catch (e) {
      console.error(e);
      toast("Couldn't load your library.");
    }
  })();
})();
