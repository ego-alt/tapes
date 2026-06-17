(() => {
  const M = window.MUSIC;
  const $ = (id) => document.getElementById(id);
  const audio = $("audio"), cassette = $("cassette");
  const labelArt = $("labelArt"), labelTitle = $("labelTitle"), labelArtist = $("labelArtist");
  const playBtn = $("playBtn"), favBtn = $("favBtn");
  const scrub = $("scrub"), scrubFill = $("scrubFill"), curTime = $("curTime"), durTime = $("durTime");
  const app = $("app");

  const streamUrl = (id) => M.streamBase + id;
  const coverUrl = (id) => M.coverBase + id;
  const fmt = (s) => (!s || !isFinite(s)) ? "0:00"
    : Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0");

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => t.classList.add("show"));
    setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); }, 3200);
  }
  // Both throw on a non-2xx or network failure so callers (and the global
  // unhandledrejection handler) can surface it instead of silently dying.
  async function jget(u) {
    const r = await fetch(u);
    if (!r.ok) throw new Error(`GET ${u} → ${r.status}`);
    return r.json();
  }
  async function jsend(u, m, b) {
    const r = await fetch(u, {
      method: m, headers: { "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : null,
    });
    if (!r.ok) throw new Error(`${m} ${u} → ${r.status}`);
    return r;
  }

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
    heart: svgIcon('<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>'),
    heartFill: svgIcon('<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.29 1.51 4.04 3 5.5l7 7Z"/>', true),
    plus: svgIcon('<path d="M12 5v14M5 12h14"/>'),
    shuffle: svgIcon('<path d="M2 18h1.4c1.3 0 2.5-.6 3.3-1.7l6.1-8.6c.7-1.1 2-1.7 3.3-1.7H22"/><path d="m18 2 4 4-4 4"/><path d="M2 6h1.9c1.5 0 2.9.9 3.6 2.2"/><path d="M22 18h-5.9c-1.3 0-2.6-.7-3.3-1.8l-.5-.8"/><path d="m18 14 4 4-4 4"/>'),
    repeat: svgIcon('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>'),
    repeatOne: svgIcon('<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/><path d="M11 10h1v4"/>'),
    list: svgIcon('<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>'),
    chevronUp: svgIcon('<path d="m6 15 6-6 6 6"/>'),
    moon: svgIcon('<path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/>', true),
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

  // ---------- shelf ----------
  async function loadShelf() {
    shelf = await jget("api/playlists");
    const list = $("shelfList");
    list.innerHTML = "";
    const icon = { all: "▤", singles: "♪", favorites: "♥", albums: "◉", artists: "♫" };
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
      li.className = "shelf-row";
      li.innerHTML = `<span class="shelf-ico">${icon[s.key] || "▰"}</span>
        <span class="shelf-name"></span><span class="shelf-count">${s.count}</span>`;
      li.querySelector(".shelf-name").textContent = s.name;
      li.addEventListener("click", () =>
        s.kind === "browse" ? openBrowse(s.key) : openTape(s.key, s.name, s.kind));
      list.appendChild(li);
    });
  }

  async function openTape(key, name, kind) {
    const tok = ++navToken;
    const sortable = key === "all" || key === "singles";
    currentSort = "default";
    const data = await jget(`api/playlists/${key}/tracks?sort=${currentSort}`);
    if (tok !== navToken) return;   // a newer view opened while we waited
    currentTape = { key, name, kind };
    view = data;
    $("sortSelect").value = "default";
    $("sortBar").hidden = !sortable;
    const titleEl = $("tapeTitle");
    titleEl.textContent = name;
    titleEl.contentEditable = "false";
    titleEl.classList.toggle("editable", kind === "user");
    titleEl.onclick = kind === "user" ? () => startTitleEdit((name) =>
      jsend(`api/playlists/${key}`, "PATCH", { name }).then(() => {
        if (currentTape) currentTape.name = name;
        loadShelf();
        return name;
      })) : null;
    $("tapeDelBtn").hidden = kind !== "user";
    $("search").value = "";
    $("backBtn").textContent = "‹ Tapes";
    trackParent = "shelf";
    renderTracks(view);
    showView("tracks");
  }

  // ---------- view switching ----------
  function showView(name) {
    $("shelfView").hidden = name !== "shelf";
    $("browseView").hidden = name !== "browse";
    $("tracksView").hidden = name !== "tracks";
  }

  // ---------- album / artist browse ----------
  async function openBrowse(kind) {
    const tok = ++navToken;
    const rows = await jget(kind === "albums" ? "api/albums" : "api/artists");
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
    if (!rows.length) { el.innerHTML = `<div class="empty-note">Nothing here yet.</div>`; return; }
    rows.forEach((r) => {
      const li = document.createElement("li");
      li.className = "browse-row";
      if (currentBrowse === "albums") {
        const art = r.cover_id
          ? `<img class="browse-cover" src="${coverUrl(r.cover_id)}" alt="" loading="lazy" decoding="async">`
          : `<span class="browse-cover browse-cover--blank">♪</span>`;
        li.innerHTML = `${art}<span class="browse-meta">
          <span class="browse-name"></span><span class="browse-sub"></span></span>
          <span class="shelf-count">${r.count}</span>`;
        li.querySelector(".browse-sub").textContent = r.artist;
        li.addEventListener("click", () => openAlbumTracks(r.name));
      } else {
        li.innerHTML = `<span class="shelf-ico">♫</span><span class="browse-meta">
          <span class="browse-name"></span></span><span class="shelf-count">${r.count}</span>`;
        li.addEventListener("click", () => openArtistTracks(r.name));
      }
      li.querySelector(".browse-name").textContent = r.name;
      el.appendChild(li);
    });
  }
  function applyBrowseSearch() {
    const q = $("browseSearch").value.toLowerCase().trim();
    renderBrowse(q ? browseRows.filter((r) =>
      (r.name + " " + (r.artist || "")).toLowerCase().includes(q)) : browseRows);
  }
  async function openAlbumTracks(album) {
    const tok = ++navToken;
    const data = await jget(`api/albums/tracks?album=${encodeURIComponent(album)}`);
    if (tok !== navToken) return;
    view = data;
    openTrackList(album, "albums", "‹ Albums");
  }
  async function openArtistTracks(artist) {
    const tok = ++navToken;
    const data = await jget(`api/artists/tracks?artist=${encodeURIComponent(artist)}`);
    if (tok !== navToken) return;
    view = data;
    openTrackList(artist, "artists", "‹ Artists");
  }
  function openTrackList(title, parent, backLabel) {
    currentTape = null;
    trackParent = parent;
    const titleEl = $("tapeTitle");
    titleEl.textContent = title;
    titleEl.contentEditable = "false";
    const renamable = parent === "artists";
    titleEl.classList.toggle("editable", renamable);
    titleEl.onclick = renamable ? () => startTitleEdit((name, orig) =>
      jsend("api/artists", "PATCH", { old: orig, new: name })
        .then((r) => { if (!r.ok) throw new Error("rename failed"); return r.json(); })
        .then(async (r) => {
          // Refresh the (now-hidden) Artists list so going back reflects the
          // rename/merge, then reload this artist's tracks under the final name.
          browseRows = await jget("api/artists");
          renderBrowse(browseRows);
          openArtistTracks(r.name);
          return r.name;
        })) : null;
    $("tapeDelBtn").hidden = true;
    $("sortBar").hidden = true;
    $("backBtn").textContent = backLabel;
    $("search").value = "";
    renderTracks(view);
    showView("tracks");
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
    document.execCommand("selectAll", false, null);

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

    el.onblur = () => commit(true);
    el.onkeydown = (e) => {
      if (e.key === "Enter") { e.preventDefault(); commit(true); }
      if (e.key === "Escape") commit(false);
    };
  }

  function renderTracks(list) {
    const el = $("trackList");
    el.innerHTML = "";
    if (!list.length) { el.innerHTML = `<div class="empty-note">Empty.</div>`; return; }
    // Drag-reorder only makes sense (and persists) for a user tape, and only
    // when the list isn't filtered by a search.
    const reorderable = !!(currentTape && currentTape.kind === "user") && !$("search").value.trim();
    list.forEach((t, i) => {
      const li = document.createElement("li");
      li.dataset.id = t.id;
      const handle = reorderable ? `<span class="tl-drag drag-handle" title="Drag to reorder" aria-hidden="true">⠿</span>` : "";
      li.innerHTML = `${handle}<span class="tl-num">${i + 1}</span>
        <span class="tl-meta"><div class="tl-title"></div><div class="tl-sub"></div></span>
        <button class="tl-fav" title="Favorite">${t.fav ? ICONS.heartFill : ICONS.heart}</button>
        <button class="tl-add" title="Add to tape">${ICONS.plus}</button>`;
      li.querySelector(".tl-title").textContent = t.title;
      li.querySelector(".tl-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
      li.querySelector(".tl-fav").addEventListener("click", (e) => { e.stopPropagation(); toggleFav(t); });
      li.querySelector(".tl-add").addEventListener("click", (e) => {
        e.stopPropagation();
        if (!menu.hidden && menu.dataset.for === String(t.id)) closeMenu();
        else openMenu(e, t);
      });
      const h = li.querySelector(".tl-drag");
      if (h) h.addEventListener("click", (e) => e.stopPropagation());
      li.addEventListener("click", () => playFromList(list, i));
      el.appendChild(li);
    });
    markActive();
  }

  function applySearch() {
    const q = $("search").value.toLowerCase().trim();
    renderTracks(q ? view.filter((t) =>
      (t.title + " " + t.artist + " " + t.album).toLowerCase().includes(q)) : view);
  }

  // ---------- mobile drawer ----------
  const isMobile = () => window.matchMedia("(max-width: 640px)").matches;
  const closeNav = () => app.classList.add("nav-collapsed");

  // ---------- playback ----------
  function shuffleArray(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  function playFromList(list, i) {
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
    if (isMobile()) closeNav();   // reveal the deck once a track is picked
  }
  function loadCurrent(autoplay) {
    const t = queue[qi];
    if (!t) return;
    audio.src = streamUrl(t.id);
    if (autoplay) audio.play().catch(() => {});
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = [t.artist, t.album].filter(Boolean).join(" — ");
    if (t.has_cover) labelArt.src = coverUrl(t.id); else labelArt.removeAttribute("src");
    favBtn.innerHTML = t.fav ? ICONS.heartFill : ICONS.heart;
    favBtn.classList.toggle("on", !!t.fav);
    document.title = t.title + (t.artist ? " · " + t.artist : "");
    setMediaSession(t);
    markActive();
    savePlaystate();
    prefetchNext();
    updateUpNext();
  }
  // Warm the browser/nginx cache for the next track so skips start instantly.
  let prefetchEl = null, prefetchId = null;
  function prefetchNext() {
    const next = queue[qi + 1];
    if (!next || next.id === prefetchId) return;
    if (prefetchEl) prefetchEl.src = "";  // abort the previous prefetch
    prefetchId = next.id;
    prefetchEl = new Audio();
    prefetchEl.preload = "auto";
    prefetchEl.src = streamUrl(next.id);
  }
  const currentTrack = () => queue[qi] || null;
  function markActive() {
    const cur = currentTrack();
    [...$("trackList").children].forEach((li) =>
      li.classList?.toggle("active", !!cur && Number(li.dataset.id) === cur.id));
  }
  function togglePlay() {
    if (qi < 0) { if (view.length) playFromList(view, 0); return; }
    audio.paused ? audio.play() : audio.pause();
  }
  function setMediaSession(t) {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title, artist: t.artist || "", album: t.album || "",
      artwork: t.has_cover ? [{ src: coverUrl(t.id), sizes: "500x500", type: "image/jpeg" }] : [],
    });
    navigator.mediaSession.setActionHandler("previoustrack", () => prev());
    navigator.mediaSession.setActionHandler("nexttrack", () => next(true));
  }
  function go(i, autoplay) { qi = i; loadCurrent(autoplay); }
  // `manual` = user pressed next (vs. a track ending). Repeat-one only loops on
  // natural end, so pressing next still advances.
  function next(manual) {
    if (!manual && repeatMode === "one") { audio.currentTime = 0; audio.play().catch(() => {}); return; }
    if (qi + 1 < queue.length) go(qi + 1, true);
    else if (repeatMode === "all") go(0, true);
    // else: end of queue — stop.
  }
  function prev() {
    if (qi >= 0 && audio.currentTime > 3) { audio.currentTime = 0; return; }  // restart current first
    if (qi > 0) go(qi - 1, true);
    else if (repeatMode === "all") go(queue.length - 1, true);
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
  function playNext(t) {
    if (qi < 0) { playFromList([t], 0); return; }
    queue.splice(qi + 1, 0, t);
    baseQueue = queue.slice();   // manual edits define the new source order
    prefetchNext();
    savePlaystate();
    updateUpNext();
  }
  function addToQueue(t) {
    if (qi < 0) { playFromList([t], 0); return; }
    queue.push(t);
    baseQueue = queue.slice();
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
  function renderQueue() {
    const el = $("queueList");
    el.innerHTML = "";
    if (!queue.length) { el.innerHTML = `<div class="queue-empty">Queue is empty.</div>`; return; }
    queue.forEach((t, i) => {
      const li = document.createElement("li");
      li.dataset.id = t.id;
      li.className = "q-row" + (i === qi ? " active" : "");
      li.innerHTML = `<span class="q-drag drag-handle" title="Drag to reorder" aria-hidden="true">⠿</span>
        <span class="q-meta"><div class="q-title"></div><div class="q-sub"></div></span>
        <button class="q-btn q-rm" title="Remove">✕</button>`;
      li.querySelector(".q-title").textContent = t.title;
      li.querySelector(".q-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
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
      updateUpNext(); markActive(); savePlaystate(); return;
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

  // ---------- favorites ----------
  async function toggleFav(t) {
    let fav;
    try {
      ({ fav } = await jsend(`api/favorites/${t.id}`, "POST").then((r) => r.json()));
    } catch (e) {
      console.error(e); toast("Couldn't update favorite."); return;
    }
    [...view, ...queue].forEach((x) => { if (x && x.id === t.id) x.fav = fav; });
    applySearch();
    const cur = currentTrack();
    if (cur && cur.id === t.id) { favBtn.innerHTML = fav ? ICONS.heartFill : ICONS.heart; favBtn.classList.toggle("on", fav); }
    loadShelf();
  }

  // ---------- popover menus (add-to-tape, sleep timer) ----------
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

  // ---------- add-to-tape menu ----------
  const menu = $("plMenu");
  function openMenu(e, t) {
    menu.dataset.for = t.id;
    menu.innerHTML = "";
    menu.appendChild(menuItem("Play next", () => playNext(t), closeMenu));
    menu.appendChild(menuItem("Add to queue", () => addToQueue(t), closeMenu));
    const sep = document.createElement("div");
    sep.className = "menu-sep";
    menu.appendChild(sep);

    const tapes = shelf.filter((s) => s.kind === "user");
    if (!tapes.length) {
      const empty = document.createElement("div");
      empty.className = "menu-empty";
      empty.textContent = "No tapes yet";
      menu.appendChild(empty);
    }
    tapes.forEach((s) => menu.appendChild(menuItem(s.name, async () => {
      await jsend(`api/playlists/${s.key}/tracks`, "POST", { track_id: t.id });
      loadShelf();
    }, closeMenu)));

    menu.hidden = false;   // show first so we can measure it, then place it
    const pad = 8, mh = menu.offsetHeight;
    const flipUp = e.clientY + mh > window.innerHeight - pad;
    const flipLeft = e.clientX + menu.offsetWidth > window.innerWidth - pad;
    // Grow from the corner pinned to the click (accounting for any flip).
    placeMenu(menu, flipUp ? e.clientY - mh : e.clientY, e.clientX,
      `${flipUp ? "bottom" : "top"} ${flipLeft ? "right" : "left"}`);
  }
  const closeMenu = () => { menu.hidden = true; delete menu.dataset.for; };
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });

  // ---------- sleep timer ----------
  // Client-only: arm a duration (or "end of track"), fade out and pause when it
  // fires, restore volume so the next manual play is normal. In-memory only — a
  // timer surviving a page reload would be surprising, not helpful.
  const sleepBtn = $("sleepBtn"), sleepMenu = $("sleepMenu");
  let sleepTimeoutId = null, sleepTickId = null, sleepDeadline = 0, sleepEndOfTrack = false;

  function renderSleepBtn() {
    const active = sleepTimeoutId !== null || sleepEndOfTrack;
    sleepBtn.classList.toggle("active", active);
    sleepBtn.setAttribute("aria-pressed", String(active));
    if (sleepTimeoutId !== null) {
      const left = Math.max(0, Math.round((sleepDeadline - Date.now()) / 1000));
      sleepBtn.innerHTML = `<span class="sleep-count">${Math.floor(left / 60)}:${String(left % 60).padStart(2, "0")}</span>`;
      sleepBtn.title = "Sleep timer running — tap to change";
    } else {
      sleepBtn.innerHTML = ICONS.moon;
      sleepBtn.title = sleepEndOfTrack ? "Sleep: stop at end of track" : "Sleep timer";
    }
  }

  function clearSleep() {
    if (sleepTimeoutId !== null) clearTimeout(sleepTimeoutId);
    if (sleepTickId !== null) clearInterval(sleepTickId);
    sleepTimeoutId = sleepTickId = null;
    sleepEndOfTrack = false;
    renderSleepBtn();
  }

  function sleepFire() {
    clearSleep();
    const startVol = audio.volume, steps = 40, span = 8000;
    let i = 0;
    const fade = setInterval(() => {
      audio.volume = Math.max(0, startVol * (1 - ++i / steps));
      if (i >= steps) { clearInterval(fade); audio.pause(); audio.volume = startVol; }
    }, span / steps);
  }

  function setSleep(val) {
    clearSleep();
    if (val === "track") {
      sleepEndOfTrack = true;
    } else if (val) {
      sleepDeadline = Date.now() + val * 60000;
      sleepTimeoutId = setTimeout(sleepFire, val * 60000);
      sleepTickId = setInterval(renderSleepBtn, 1000);
    }
    renderSleepBtn();
  }

  const closeSleep = () => { sleepMenu.hidden = true; };
  function openSleepMenu() {
    sleepMenu.innerHTML = "";
    [["15 min", 15], ["30 min", 30], ["45 min", 45], ["1 hour", 60], ["End of track", "track"]]
      .forEach(([label, val]) => sleepMenu.appendChild(menuItem(label, () => setSleep(val), closeSleep)));
    if (sleepTimeoutId !== null || sleepEndOfTrack) {
      const sep = document.createElement("div"); sep.className = "menu-sep"; sleepMenu.appendChild(sep);
      sleepMenu.appendChild(menuItem("Turn off", clearSleep, closeSleep));
    }
    sleepMenu.hidden = false;   // show first so we can measure, then place above the button
    const r = sleepBtn.getBoundingClientRect(), mh = sleepMenu.offsetHeight;
    let top = r.top - mh - 6, below = false;
    if (top < 8) { top = r.bottom + 6; below = true; }   // flip below if no room above
    placeMenu(sleepMenu, top, r.left + r.width / 2 - sleepMenu.offsetWidth / 2,
      (below ? "top" : "bottom") + " center");           // grow toward the button
  }

  sleepBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    sleepMenu.hidden ? openSleepMenu() : closeSleep();
  });
  document.addEventListener("click", (e) => {
    if (!sleepMenu.hidden && !sleepMenu.contains(e.target)) closeSleep();
  });

  // ---------- downloads ----------
  let dlEvt = null, dlPrev = {};
  $("dlToggle").addEventListener("click", () => {
    const showing = $("dlPanel").hidden;
    $("dlPanel").hidden = !showing;
    if (showing) openDlStream(); else closeDlStream();
  });
  $("dlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("dlUrl").value.trim();
    if (!url) return;
    await jsend("api/downloads", "POST", { url });
    $("dlUrl").value = "";
    openDlStream();
  });
  function openDlStream() {
    if (dlEvt) return;  // already streaming
    dlEvt = new EventSource("api/downloads/stream");
    dlEvt.onmessage = (e) => handleJobs(JSON.parse(e.data));
    dlEvt.addEventListener("done", closeDlStream);
    // transient drops auto-reconnect; nothing to do on error
  }
  function closeDlStream() {
    if (dlEvt) { dlEvt.close(); dlEvt = null; }
  }
  function handleJobs(jobs) {
    const activeIds = new Set(jobs.map((j) => j.id));
    // A job we were tracking has disappeared from the active list → it finished.
    let anyCompleted = false;
    for (const id of Object.keys(dlPrev)) {
      if (!activeIds.has(Number(id))) { anyCompleted = true; break; }
    }
    dlPrev = {};
    jobs.forEach((j) => { dlPrev[j.id] = j.status; });
    if (anyCompleted) onDownloadDone();

    const el = $("dlList");
    el.innerHTML = "";
    jobs.forEach((j) => {
      const li = document.createElement("li");
      li.className = "dl-job " + j.status;
      li.innerHTML = `<div class="dl-msg"></div>
        <div class="dl-bar"><div class="dl-bar-fill" style="width:${j.progress}%"></div></div>`;
      li.querySelector(".dl-msg").textContent =
        j.status === "error" ? "⚠ " + j.message
        : j.message ? j.message + ` · ${j.progress}%`
        : j.url;
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
  let saveTimer = null;
  function savePlaystate() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => jsend("api/playstate", "PUT",
      { queue: queue.map((t) => t.id), index: qi, position: audio.currentTime || 0 }), 400);
  }
  async function restorePlaystate() {
    const ps = await jget("api/playstate");
    if (!ps.queue || !ps.queue.length) return;
    queue = ps.queue;   // already hydrated server-side
    baseQueue = queue.slice();
    qi = Math.min(ps.index || 0, queue.length - 1);
    if (qi < 0 || !queue[qi]) return;
    loadCurrent(false);
    audio.addEventListener("loadedmetadata", function once() {
      audio.currentTime = ps.position || 0;
      audio.removeEventListener("loadedmetadata", once);
    });
  }

  // ---------- events ----------
  playBtn.addEventListener("click", togglePlay);
  $("prevBtn").addEventListener("click", () => prev());
  $("nextBtn").addEventListener("click", () => next(true));
  $("shuffleBtn").addEventListener("click", () => setShuffle(!shuffleOn));
  $("repeatBtn").addEventListener("click", cycleRepeat);
  $("sortSelect").addEventListener("change", async () => {
    if (!currentTape) return;
    currentSort = $("sortSelect").value;
    view = await jget(`api/playlists/${currentTape.key}/tracks?sort=${currentSort}`);
    applySearch();   // re-render, honouring any active search text
  });
  favBtn.addEventListener("click", () => { const t = currentTrack(); if (t) toggleFav(t); });
  $("backBtn").addEventListener("click", () =>
    showView(trackParent === "albums" || trackParent === "artists" ? "browse" : "shelf"));
  $("browseBack").addEventListener("click", () => showView("shelf"));
  $("browseSearch").addEventListener("input", applyBrowseSearch);
  $("upnextBar").addEventListener("click", toggleUpNext);
  $("tapeDelBtn").addEventListener("click", async () => {
    if (!currentTape || !confirm(`Delete tape "${currentTape.name}"?`)) return;
    await jsend(`api/playlists/${currentTape.key}`, "DELETE");
    currentTape = null;
    $("tracksView").hidden = true;
    $("shelfView").hidden = false;
    loadShelf();
  });
  $("navToggle").addEventListener("click", () => app.classList.toggle("nav-collapsed"));
  $("scrim").addEventListener("click", closeNav);
  $("search").addEventListener("input", applySearch);
  $("newTapeForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("newTapeName").value.trim();
    if (!name) return;
    await jsend("api/playlists", "POST", { name });
    $("newTapeName").value = ""; loadShelf();
  });

  audio.addEventListener("play", () => {
    cassette.classList.add("playing"); playBtn.innerHTML = ICONS.pause;
    const t = currentTrack();
    if (t && t.id !== lastPlayed) { lastPlayed = t.id; jsend("api/plays", "POST", { track_id: t.id }); }
  });
  audio.addEventListener("pause", () => { cassette.classList.remove("playing"); playBtn.innerHTML = ICONS.play; savePlaystate(); });
  audio.addEventListener("ended", () => {
    if (sleepEndOfTrack) { clearSleep(); audio.pause(); return; }  // sleep: stop, don't advance
    next(false);
  });
  audio.addEventListener("loadedmetadata", () => { durTime.textContent = fmt(audio.duration); });
  audio.addEventListener("timeupdate", () => {
    curTime.textContent = fmt(audio.currentTime);
    if (audio.duration) scrubFill.style.width = (audio.currentTime / audio.duration) * 100 + "%";
  });
  scrub.addEventListener("click", (e) => {
    if (!audio.duration) return;
    const r = scrub.getBoundingClientRect();
    audio.currentTime = ((e.clientX - r.left) / r.width) * audio.duration;
    savePlaystate();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { upnext.classList.remove("expanded"); closeMenu(); closeSleep(); }
    if (e.target.tagName === "INPUT" || e.target.isContentEditable) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.key === "ArrowRight" && e.shiftKey) next(true);
    if (e.key === "ArrowLeft" && e.shiftKey) prev();
  });
  window.addEventListener("beforeunload", savePlaystate);

  // ---------- init ----------
  $("prevBtn").innerHTML = ICONS.prev;
  playBtn.innerHTML = ICONS.play;
  $("nextBtn").innerHTML = ICONS.next;
  favBtn.innerHTML = ICONS.heart;
  renderSleepBtn();
  $("shuffleBtn").innerHTML = ICONS.shuffle;
  $("newTapeBtn").innerHTML = ICONS.plus;
  $("upnextIco").innerHTML = ICONS.list;
  $("upnextCaret").innerHTML = ICONS.chevronUp;
  $("shuffleBtn").classList.toggle("active", shuffleOn);
  $("shuffleBtn").setAttribute("aria-pressed", String(shuffleOn));
  updateRepeatBtn();
  enableReorder($("trackList"), onTrackReorder);
  enableReorder($("queueList"), onQueueReorder);
  window.addEventListener("unhandledrejection", (e) => {
    console.error(e.reason);
    toast("Something went wrong — please try again.");
  });
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
