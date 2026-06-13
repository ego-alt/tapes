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

  const jget = (u) => fetch(u).then((r) => r.json());
  const jsend = (u, m, b) => fetch(u, {
    method: m, headers: { "Content-Type": "application/json" }, body: b ? JSON.stringify(b) : null,
  });

  let allMap = {};        // id -> track
  let shelf = [];         // tapes
  let view = [];          // tracks currently shown (browsing)
  let queue = [];         // tracks being played
  let qi = -1;            // index into queue
  let lastPlayed = null;  // for play-count dedupe

  // ---------- shelf ----------
  async function loadShelf() {
    shelf = await jget("/api/playlists");
    const list = $("shelfList");
    list.innerHTML = "";
    const icon = { all: "▤", singles: "♪", favorites: "♥" };
    shelf.forEach((s) => {
      const li = document.createElement("li");
      li.className = "shelf-row";
      li.innerHTML = `<span class="shelf-ico">${icon[s.key] || "▰"}</span>
        <span class="shelf-name"></span><span class="shelf-count">${s.count}</span>`;
      li.querySelector(".shelf-name").textContent = s.name;
      li.addEventListener("click", () => openTape(s.key, s.name));
      if (s.kind === "user") {
        const del = document.createElement("button");
        del.className = "shelf-del"; del.textContent = "×"; del.title = "Delete tape";
        del.addEventListener("click", async (e) => {
          e.stopPropagation();
          if (confirm(`Delete tape "${s.name}"?`)) { await jsend(`/api/playlists/${s.key}`, "DELETE"); loadShelf(); }
        });
        li.appendChild(del);
      }
      list.appendChild(li);
    });
  }

  async function openTape(key, name) {
    view = await jget(`/api/playlists/${key}/tracks`);
    $("tapeTitle").textContent = name;
    $("search").value = "";
    renderTracks(view);
    $("shelfView").hidden = true;
    $("tracksView").hidden = false;
  }

  function renderTracks(list) {
    const el = $("trackList");
    el.innerHTML = "";
    if (!list.length) { el.innerHTML = `<div class="empty-note">Empty.</div>`; return; }
    list.forEach((t, i) => {
      const li = document.createElement("li");
      li.dataset.id = t.id;
      li.innerHTML = `<span class="tl-num">${i + 1}</span>
        <span class="tl-meta"><div class="tl-title"></div><div class="tl-sub"></div></span>
        <button class="tl-fav" title="Favorite">${t.fav ? "♥" : "♡"}</button>
        <button class="tl-add" title="Add to tape">+</button>`;
      li.querySelector(".tl-title").textContent = t.title;
      li.querySelector(".tl-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
      li.querySelector(".tl-fav").addEventListener("click", (e) => { e.stopPropagation(); toggleFav(t); });
      li.querySelector(".tl-add").addEventListener("click", (e) => { e.stopPropagation(); openMenu(e, t); });
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

  // ---------- playback ----------
  function playFromList(list, i) { queue = list.slice(); qi = i; loadCurrent(true); }
  function loadCurrent(autoplay) {
    const t = queue[qi];
    if (!t) return;
    audio.src = streamUrl(t.id);
    if (autoplay) audio.play().catch(() => {});
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = [t.artist, t.album].filter(Boolean).join(" — ");
    if (t.has_cover) labelArt.src = coverUrl(t.id); else labelArt.removeAttribute("src");
    favBtn.textContent = t.fav ? "♥" : "♡";
    favBtn.classList.toggle("on", !!t.fav);
    document.title = t.title + (t.artist ? " · " + t.artist : "");
    setMediaSession(t);
    markActive();
    savePlaystate();
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
    navigator.mediaSession.setActionHandler("previoustrack", () => step(-1));
    navigator.mediaSession.setActionHandler("nexttrack", () => step(1));
  }
  function step(d) { if (qi + d >= 0 && qi + d < queue.length) { qi += d; loadCurrent(true); } }

  // ---------- favorites ----------
  async function toggleFav(t) {
    const { fav } = await jsend(`/api/favorites/${t.id}`, "POST").then((r) => r.json());
    [allMap[t.id], ...view, ...queue].forEach((x) => { if (x && x.id === t.id) x.fav = fav; });
    applySearch();
    const cur = currentTrack();
    if (cur && cur.id === t.id) { favBtn.textContent = fav ? "♥" : "♡"; favBtn.classList.toggle("on", fav); }
  }

  // ---------- add-to-tape menu ----------
  const menu = $("plMenu");
  function openMenu(e, t) {
    const tapes = shelf.filter((s) => s.kind === "user");
    menu.innerHTML = tapes.length ? "" : `<div class="menu-empty">No tapes yet</div>`;
    tapes.forEach((s) => {
      const item = document.createElement("div");
      item.className = "menu-item"; item.textContent = s.name;
      item.addEventListener("click", async () => {
        await jsend(`/api/playlists/${s.key}/tracks`, "POST", { track_id: t.id });
        closeMenu(); loadShelf();
      });
      menu.appendChild(item);
    });
    menu.style.left = Math.min(e.clientX, window.innerWidth - 180) + "px";
    menu.style.top = e.clientY + "px";
    menu.hidden = false;
  }
  const closeMenu = () => { menu.hidden = true; };
  document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) closeMenu(); });

  // ---------- downloads ----------
  let dlTimer = null, dlPrev = {};
  $("dlToggle").addEventListener("click", () => {
    $("dlPanel").hidden = !$("dlPanel").hidden;
    if (!$("dlPanel").hidden) pollDownloads();
  });
  $("dlForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const url = $("dlUrl").value.trim();
    if (!url) return;
    await jsend("/api/downloads", "POST", { url });
    $("dlUrl").value = "";
    pollDownloads();
  });
  async function pollDownloads() {
    const jobs = await jget("/api/downloads");
    const el = $("dlList");
    el.innerHTML = "";
    let active = false;
    jobs.forEach((j) => {
      if (j.status === "queued" || j.status === "running") active = true;
      if (dlPrev[j.id] && dlPrev[j.id] !== "done" && j.status === "done") onDownloadDone();
      dlPrev[j.id] = j.status;
      const li = document.createElement("li");
      li.className = "dl-job " + j.status;
      li.innerHTML = `<div class="dl-msg"></div>
        <div class="dl-bar"><div class="dl-bar-fill" style="width:${j.progress}%"></div></div>`;
      li.querySelector(".dl-msg").textContent =
        j.status === "error" ? "⚠ " + j.message : (j.message || j.status) + ` · ${j.progress}%`;
      el.appendChild(li);
    });
    clearTimeout(dlTimer);
    if (active && !$("dlPanel").hidden) dlTimer = setTimeout(pollDownloads, 1500);
  }
  async function onDownloadDone() {
    const allArr = await jget("/api/playlists/all/tracks");
    allArr.forEach((t) => (allMap[t.id] = t));
    await loadShelf();
    if (!$("tracksView").hidden) {
      const s = shelf.find((x) => x.name === $("tapeTitle").textContent);
      if (s && (s.key === "all" || s.key === "singles")) openTape(s.key, s.name);
    }
  }

  // ---------- playstate persistence ----------
  let saveTimer = null;
  function savePlaystate() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => jsend("/api/playstate", "PUT",
      { queue: queue.map((t) => t.id), index: qi, position: audio.currentTime || 0 }), 400);
  }
  async function restorePlaystate() {
    const ps = await jget("/api/playstate");
    if (!ps.queue || !ps.queue.length) return;
    queue = ps.queue.map((id) => allMap[id]).filter(Boolean);
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
  $("prevBtn").addEventListener("click", () => step(-1));
  $("nextBtn").addEventListener("click", () => step(1));
  favBtn.addEventListener("click", () => { const t = currentTrack(); if (t) toggleFav(t); });
  $("backBtn").addEventListener("click", () => { $("tracksView").hidden = true; $("shelfView").hidden = false; });
  $("navToggle").addEventListener("click", () => app.classList.toggle("nav-collapsed"));
  $("search").addEventListener("input", applySearch);
  $("newTapeForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("newTapeName").value.trim();
    if (!name) return;
    await jsend("/api/playlists", "POST", { name });
    $("newTapeName").value = ""; loadShelf();
  });

  audio.addEventListener("play", () => {
    cassette.classList.add("playing"); playBtn.textContent = "❚❚";
    const t = currentTrack();
    if (t && t.id !== lastPlayed) { lastPlayed = t.id; jsend("/api/plays", "POST", { track_id: t.id }); }
  });
  audio.addEventListener("pause", () => { cassette.classList.remove("playing"); playBtn.textContent = "▶"; savePlaystate(); });
  audio.addEventListener("ended", () => step(1));
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
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.key === "ArrowRight" && e.shiftKey) step(1);
    if (e.key === "ArrowLeft" && e.shiftKey) step(-1);
  });
  window.addEventListener("beforeunload", savePlaystate);

  // ---------- init ----------
  (async () => {
    const all = await jget("/api/playlists/all/tracks");
    all.forEach((t) => (allMap[t.id] = t));
    await loadShelf();
    await restorePlaystate();
  })();
})();
