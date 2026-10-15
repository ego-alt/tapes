(() => {
  const M = window.MUSIC;
  const $ = (id) => document.getElementById(id);
  const audio = $("audio"), cassette = $("cassette");
  const labelArt = $("labelArt"), labelTitle = $("labelTitle"), labelArtist = $("labelArtist");
  const playBtn = $("playBtn");
  const scrub = $("scrub"), scrubFill = $("scrubFill"), curTime = $("curTime"), durTime = $("durTime");
  const app = $("app");

  const streamUrl = (id) => M.streamBase + id;
  const coverUrl = (id) => M.coverBase + id;
  // Polymorphic source/art: a track plays from the music endpoints, an episode
  // (kind === "episode") from the podcast ones. Everything else in the player
  // works on these two helpers so the queue/deck can hold either.
  const srcUrl = (t) => t.kind === "episode" ? M.epStreamBase + t.id : streamUrl(t.id);
  const artUrl = (t) => t.kind === "episode"
    ? (t.show_id ? M.epEpisodeCoverBase + t.id : null)
    : (t.has_cover ? coverUrl(t.id) : null);
  const fmt = (s) => {
    if (!s || !isFinite(s)) return "0:00";
    s = Math.floor(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    const pad = (n) => String(n).padStart(2, "0");
    // Hours only when needed, so 3-min songs stay "3:14" and long episodes read "4:14:13".
    return h ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
  };

  function toast(msg) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = msg;
    document.body.appendChild(t);
    requestAnimationFrame(() => t.classList.add("show"));
    setTimeout(() => { t.classList.remove("show"); setTimeout(() => t.remove(), 300); }, 3200);
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
    chevronDown: svgIcon('<path d="m6 9 6 6 6-6"/>'),
    library: svgIcon('<path d="M4 6h16M4 12h16M4 18h16"/>'),
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
  let showsData = null;       // last /api/podcast/shows payload
  let currentShow = null;     // show whose episodes are open (null = loose)
  let episodes = [];          // episodes currently shown
  const pendingPlays = {};    // episode_id -> {list, i} awaiting download-then-play

  // ---------- shelf ----------
  async function loadShelf() {
    shelf = await jget("api/playlists");
    const list = $("shelfList");
    list.innerHTML = "";
    const icon = { all: "▤", singles: "♪", albums: "◉", artists: "♫" };
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
    $("podcastsView").hidden = name !== "podcasts";
    $("episodesView").hidden = name !== "episodes";
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

  // ---------- podcasts ----------
  async function openPodcasts() {
    const tok = ++navToken;
    let data;
    try { data = await jget("api/podcast/shows"); }
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
      el.innerHTML = `<div class="empty-note">No podcasts yet. Paste an RSS or YouTube URL above.</div>`;
      return;
    }
    data.shows.forEach((s) => {
      const li = document.createElement("li");
      li.className = "browse-row";
      const art = s.has_image
        ? `<img class="browse-cover" src="${M.epShowCoverBase + s.id}" alt="" loading="lazy" decoding="async">`
        : `<span class="browse-cover browse-cover--blank">◎</span>`;
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
      li.className = "browse-row";
      li.innerHTML = `<span class="browse-cover browse-cover--blank">◎</span>
        <span class="browse-meta"><span class="browse-name">Loose episodes</span></span>
        <span class="shelf-count">${data.loose_count}</span>`;
      li.addEventListener("click", openLoose);
      el.appendChild(li);
    }
  }
  async function openShow(s) {
    const tok = ++navToken;
    const data = await jget(`api/podcast/shows/${s.id}/episodes`);
    if (tok !== navToken) return;
    currentShow = data.show;
    // manual tapes can't refresh; only real shows can be deleted from here
    enterEpisodes(data.show.title, data.episodes, { refreshable: data.show.refreshable, deletable: true });
  }
  async function openLoose() {
    const tok = ++navToken;
    const data = await jget("api/podcast/episodes/loose");
    if (tok !== navToken) return;
    currentShow = null;
    enterEpisodes("Loose episodes", data.episodes, { refreshable: false, deletable: false });
  }
  // Shared tail for the two episode views (a tape's episodes, or Loose episodes).
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
    if (!list.length) { el.innerHTML = `<div class="empty-note">No episodes.</div>`; return; }
    list.forEach((e, i) => {
      const li = document.createElement("li");
      li.dataset.id = e.id;
      li.className = e.played ? "played" : "";   // layout comes from .track-list li
      const pct = (!e.played && e.duration && e.position)
        ? Math.min(100, (e.position / e.duration) * 100) : 0;
      const sub = [
        formatEpDate(e.published_at),
        e.duration ? fmt(e.duration) : (e.status === "new" ? "not downloaded" : ""),
        e.status === "downloading" ? "downloading…" : "",
      ].filter(Boolean).join(" · ");
      li.innerHTML = `<span class="tl-meta">
          <div class="tl-title"></div><div class="tl-sub"></div>
          <div class="ep-prog"${pct ? "" : " hidden"}><div class="ep-prog-fill" style="width:${pct}%"></div></div>
        </span>
        <button class="tl-add ep-played" title="Mark played / unplayed">${e.played ? "✓" : "○"}</button>
        <button class="tl-add ep-menu" title="More">${ICONS.more}</button>`;
      li.querySelector(".tl-title").textContent = e.title;
      li.querySelector(".tl-sub").textContent = sub;
      li.querySelector(".ep-played").addEventListener("click", (ev) => { ev.stopPropagation(); togglePlayed(e); });
      li.querySelector(".ep-menu").addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (!menu.hidden && menu.dataset.for === "ep" + e.id) closeMenu();
        else openEpisodeMenu(ev, e);
      });
      li.addEventListener("click", () => playEpisode(list, i));
      el.appendChild(li);
    });
    markActive();
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
    // Loose episodes can be filed into a tape (in-place picker — see submenuItem).
    if (ep.show_id == null)
      menu.appendChild(submenuItem("Add to tape…", () => openAssignMenu(e, ep)));
    if (ep.status === "ready")
      menu.appendChild(menuItem("Remove download", () => removeDownload(ep), closeMenu));
    menu.appendChild(menuItem("Delete episode", () => deleteEpisode(ep), closeMenu));
    showMenuAt(e);
  }
  async function openAssignMenu(e, ep) {
    if (!showsData) { try { showsData = await jget("api/podcast/shows"); } catch (_) { /* ignore */ } }
    menu.innerHTML = "";
    (showsData?.shows || []).forEach((s) =>
      menu.appendChild(menuItem(s.title, () => assignEpisode(ep, { show_id: s.id }), closeMenu)));
    menu.appendChild(menuSep());
    menu.appendChild(menuItem("New tape…", () => {
      const name = prompt("New tape name:");
      if (name && name.trim()) assignEpisode(ep, { new_show_name: name.trim() });
    }, closeMenu));
    showMenuAt(e);
  }
  async function assignEpisode(ep, body) {
    let res;
    try { res = await jsend(`api/podcast/episodes/${ep.id}/assign`, "POST", body).then((r) => r.json()); }
    catch (err) { console.error(err); toast("Couldn't add to tape."); return; }
    episodes = episodes.filter((x) => x.id !== ep.id);   // it left Loose episodes
    applyEpisodeSearch();
    showsData = null;   // counts/new show changed — refetch on next open
    toast(`Added to "${res.show.title}"`);
  }
  async function removeDownload(ep) {
    try { await jsend(`api/podcast/episodes/${ep.id}/remove-download`, "POST"); }
    catch (err) { console.error(err); toast("Couldn't remove the download."); return; }
    ep.status = "new"; ep.file_path = null;
    applyEpisodeSearch();
    toast("Download removed");
  }
  async function deleteEpisode(ep) {
    if (!confirm(`Delete "${ep.title}"?`)) return;
    try { await jsend(`api/podcast/episodes/${ep.id}`, "DELETE"); }
    catch (err) { console.error(err); toast("Couldn't delete."); return; }
    episodes = episodes.filter((x) => x.id !== ep.id);
    applyEpisodeSearch();
  }
  async function playEpisode(list, i) {
    const e = list[i];
    if (e.status === "ready") { startEpisodePlayback(list, i); return; }
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
    baseQueue = list.slice();
    queue = list.slice();
    qi = i;
    loadCurrent(true);
  }
  // Show a "downloading…" deck state and fetch an episode that was reached before
  // it was downloaded; onPodcastJobDone plays it once the job completes.
  function loadPendingEpisode(t) {
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = (t.show || "Podcast") + " · downloading…";
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
    btn.disabled = true; btn.textContent = "…";
    try {
      const r = await jsend(`api/podcast/shows/${currentShow.id}/refresh`, "POST").then((x) => x.json());
      toast(r.added ? `Added ${r.added} new episode${r.added > 1 ? "s" : ""}` : "No new episodes");
      if (r.added) await openShow(currentShow);
    } catch (e) { console.error(e); toast("Refresh failed."); }
    finally { btn.disabled = false; btn.textContent = orig; }
  }
  async function deleteCurrentShow() {
    if (!currentShow || !confirm(`Delete "${currentShow.title}" and its downloads?`)) return;
    await jsend(`api/podcast/shows/${currentShow.id}`, "DELETE");
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
        <button class="tl-add tl-addto" title="Add to…">${ICONS.plus}</button>
        <button class="tl-add tl-more" title="More">${ICONS.more}</button>`;
      li.querySelector(".tl-title").textContent = t.title;
      li.querySelector(".tl-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
      li.querySelector(".tl-addto").addEventListener("click", (e) => { e.stopPropagation(); openAddMenu(e, t); });
      li.querySelector(".tl-more").addEventListener("click", (e) => {
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
    $("miniSub").textContent = t.kind === "episode" ? (t.show || "Podcast")
      : [t.artist, t.album].filter(Boolean).join(" · ") || "Unknown artist";
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
  }
  function loadCurrent(autoplay) {
    const t = queue[qi];
    if (!t) return;
    const isEp = t.kind === "episode";
    // Reached an episode that isn't downloaded yet (e.g. auto-advance / queue jump):
    // kick off the fetch and let onPodcastJobDone resume playback when it's ready.
    if (isEp && t.status !== "ready") { loadPendingEpisode(t); return; }
    audio.src = srcUrl(t);
    // Resume an episode where you left off (music resume rides the playstate path).
    if (isEp) resumeEpisodeTo(t.position);
    if (autoplay) audio.play().catch(() => {});
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = isEp
      ? (t.show || "Podcast")
      : [t.artist, t.album].filter(Boolean).join(" — ");
    const art = artUrl(t);
    if (art) labelArt.src = art; else labelArt.removeAttribute("src");
    document.title = t.title + (isEp ? (t.show ? " · " + t.show : "") : (t.artist ? " · " + t.artist : ""));
    setMediaSession(t);
    markActive();
    // Persist the deck snapshot. For episodes, only the session (queue+cursor) —
    // the position rides on the episode and mustn't be saved as 0 before the seek.
    if (isEp) savePodcastSession(); else savePlaystate();
    prefetchNext();
    updateUpNext();
    updateMini();
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
    // Don't warm an undownloaded episode — its stream 404s until it's fetched.
    if (next.kind === "episode" && next.status !== "ready") { prefetchEl = null; prefetchId = null; return; }
    prefetchEl.src = srcUrl(next);
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
  function setMediaSession(t) {
    if (!("mediaSession" in navigator)) return;
    const isEp = t.kind === "episode";
    const art = artUrl(t);
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title,
      artist: isEp ? (t.show || "Podcast") : (t.artist || ""),
      album: isEp ? "" : (t.album || ""),
      artwork: art ? [{ src: art, sizes: "500x500", type: "image/jpeg" }] : [],
    });
    navigator.mediaSession.setActionHandler("previoustrack", () => prev());
    navigator.mediaSession.setActionHandler("nexttrack", () => next(true));
  }
  function go(i, autoplay) { qi = i; loadCurrent(autoplay); }
  // `manual` = user pressed next (vs. a track ending). Repeat-one only loops on
  // natural end, so pressing next still advances.
  function next(manual) {
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
    if (qi >= 0 && audio.currentTime > 3) { audio.currentTime = 0; return; }  // restart current first
    if (activeIsEpisode()) { if (qi + 1 < queue.length) go(qi + 1, true); return; }  // back = older
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
  function addToQueue(t) {
    if (qi < 0 || activeIsEpisode()) { playFromList([t], 0); return; }
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
  // Tapping outside the open queue closes it (it's a sheet on phones).
  document.addEventListener("click", (e) => {
    if (upnext.classList.contains("expanded") && !upnext.contains(e.target)) upnext.classList.remove("expanded");
  });
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
  async function saveEdit() {
    if (!editing) return;
    const id = editing.id;
    // Send only what changed, so a field the form couldn't show (or the user
    // didn't touch) is never overwritten with a blank.
    const before = {
      title: editing.title || "", artist: editing.artist || "",
      album: editing.album || "", track_no: editing.track_no == null ? "" : String(editing.track_no),
    };
    const after = {
      title: $("edTitle").value, artist: $("edArtist").value,
      album: $("edAlbum").value, track_no: $("edTrackNo").value,
    };
    const changes = Object.fromEntries(Object.entries(after).filter(([k, v]) => v.trim() !== before[k].trim()));
    if (!Object.keys(changes).length) { closeEdit(); return; }
    let updated;
    try {
      updated = await jsend(`api/tracks/${id}`, "PATCH", changes).then((r) => r.json());
    } catch (e) { console.error(e); toast("Couldn't save changes."); return; }
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
    if (cur && cur.id === id) {   // refresh the deck label without reloading audio
      labelTitle.textContent = cur.title;
      labelArtist.textContent = [cur.artist, cur.album].filter(Boolean).join(" — ");
      document.title = cur.title + (cur.artist ? " · " + cur.artist : "");
      updateMini();
    }
    loadShelf();   // album/artist counts may have shifted
  }
  async function deleteTrack(t) {
    if (!confirm(`Delete "${t.title}" from the library? This removes the file.`)) return;
    try { await jsend(`api/tracks/${t.id}`, "DELETE"); }
    catch (e) { console.error(e); toast("Couldn't delete."); return; }
    const idx = queue.findIndex((x) => x.id === t.id);
    if (idx >= 0) queueRemove(idx);   // handles current-track/qi/Up Next cleanup
    view = view.filter((x) => x.id !== t.id);
    applySearch();
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
        await jsend(`api/playlists/${s.key}/tracks`, "POST", { track_id: t.id });
        loadShelf();
      }, closeMenu)));
    }
    showMenuAt(e);
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
      const msg = r.assigned ? `Added to "${r.assigned.title}"`
        : r.loose ? "Added to Loose episodes"
        : r.created === false ? `Added ${r.added} new episode${r.added === 1 ? "" : "s"}`
        : `Added "${r.title}"`;
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
          <button class="dl-dismiss" title="Dismiss" aria-label="Dismiss">✕</button></div>`;
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
    if (cur.kind === "episode" && cur.status !== "ready") return;
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
  $("backBtn").addEventListener("click", () =>
    showView(trackParent === "albums" || trackParent === "artists" ? "browse" : "shelf"));
  $("browseBack").addEventListener("click", () => showView("shelf"));
  $("browseSearch").addEventListener("input", applyBrowseSearch);
  $("modeMusic").addEventListener("click", () => setMode("music"));
  $("modePods").addEventListener("click", () => setMode("podcasts"));
  $("edCancel").addEventListener("click", closeEdit);
  $("edSave").addEventListener("click", saveEdit);
  $("editModal").addEventListener("click", (e) => { if (e.target === $("editModal")) closeEdit(); });
  $("editModal").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveEdit(); }
    if (e.key === "Escape") closeEdit();
  });
  $("epBack").addEventListener("click", () => showView("podcasts"));
  [...document.querySelectorAll(".ep-filter-btn")].forEach((b) =>
    b.addEventListener("click", () => {
      epFilter = b.dataset.f;
      localStorage.setItem("tapes-ep-filter", epFilter);
      updateEpFilterBtns();
      applyEpisodeSearch();
    }));
  $("epSearch").addEventListener("input", applyEpisodeSearch);
  $("showRefreshBtn").addEventListener("click", refreshCurrentShow);
  $("showDelBtn").addEventListener("click", deleteCurrentShow);
  audio.addEventListener("error", () => {
    const t = currentTrack();
    if (t && t.kind === "episode") toast("Couldn't play this episode.");
  });
  $("upnextBar").addEventListener("click", toggleUpNext);
  $("tapeDelBtn").addEventListener("click", async () => {
    if (!currentTape || !confirm(`Delete tape "${currentTape.name}"?`)) return;
    await jsend(`api/playlists/${currentTape.key}`, "DELETE");
    currentTape = null;
    $("tracksView").hidden = true;
    $("shelfView").hidden = false;
    loadShelf();
  });
  $("navToggle").addEventListener("click", () =>
    isMobile() ? closeDeck() : app.classList.toggle("nav-collapsed"));
  $("miniOpen").addEventListener("click", openDeck);
  $("miniPlay").addEventListener("click", togglePlay);
  $("search").addEventListener("input", applySearch);
  // Both "New tape" forms (music + podcast) share the create boilerplate.
  function wireCreateForm(formId, inputId, onSubmit) {
    $(formId).addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $(inputId).value.trim();
      if (!name) return;
      await onSubmit(name);
      $(inputId).value = "";
    });
  }
  wireCreateForm("newTapeForm", "newTapeName", async (name) => {
    await jsend("api/playlists", "POST", { name }); loadShelf();
  });
  wireCreateForm("newShowForm", "newShowName", async (name) => {
    await jsend("api/podcast/shows", "POST", { name }); showsData = null; openPodcasts();
  });

  audio.addEventListener("play", () => {
    cassette.classList.add("playing"); playBtn.innerHTML = ICONS.pause; updateMini();
    const t = currentTrack();
    // Play counts are a music-catalog thing (no Play row for episodes).
    if (t && t.kind !== "episode" && t.id !== lastPlayed) {
      lastPlayed = t.id; jsend("api/plays", "POST", { track_id: t.id });
    }
  });
  audio.addEventListener("pause", () => {
    cassette.classList.remove("playing"); playBtn.innerHTML = ICONS.play; updateMini(); savePlaystate();
  });
  audio.addEventListener("ended", () => {
    if (sleepEndOfTrack) { clearSleep(); audio.pause(); return; }  // sleep: stop, don't advance
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
    audio.currentTime = scrubFrac(e) * audio.duration;
    savePlaystate();
  }
  scrub.addEventListener("pointerup", endScrub);
  scrub.addEventListener("pointercancel", () => { scrubbing = false; scrub.classList.remove("dragging"); });
  // Keyboard on the focused scrub: ←/→ 5 s.
  scrub.addEventListener("keydown", (e) => {
    if (!audio.duration || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
    e.preventDefault();
    e.stopPropagation();
    audio.currentTime = Math.max(0, Math.min(audio.duration, audio.currentTime + (e.key === "ArrowRight" ? 5 : -5)));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const anyOpen = upnext.classList.contains("expanded") || !menu.hidden || !sleepMenu.hidden;
      upnext.classList.remove("expanded"); closeMenu(); closeSleep();
      if (!anyOpen && isMobile()) closeDeck();
    }
    if (e.target.tagName === "INPUT" || e.target.isContentEditable) return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.key === "ArrowRight" && e.shiftKey) next(true);
    if (e.key === "ArrowLeft" && e.shiftKey) prev();
  });
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

  // ---------- init ----------
  updateNavToggle();
  $("prevBtn").innerHTML = ICONS.prev;
  playBtn.innerHTML = ICONS.play;
  $("nextBtn").innerHTML = ICONS.next;
  renderSleepBtn();
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
  window.addEventListener("unhandledrejection", (e) => {
    console.error(e.reason);
    toast(errText(e.reason, "Something went wrong — please try again."));
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
