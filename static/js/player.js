(() => {
  const M = window.MUSIC;
  const audio = document.getElementById("audio");
  const cassette = document.getElementById("cassette");
  const listEl = document.getElementById("trackList");
  const searchEl = document.getElementById("search");
  const labelArt = document.getElementById("labelArt");
  const labelTitle = document.getElementById("labelTitle");
  const labelArtist = document.getElementById("labelArtist");
  const playBtn = document.getElementById("playBtn");
  const scrub = document.getElementById("scrub");
  const scrubFill = document.getElementById("scrubFill");
  const curTime = document.getElementById("curTime");
  const durTime = document.getElementById("durTime");

  let allTracks = [];   // full catalog
  let view = [];        // current filtered list = the queue
  let index = -1;       // position in `view`

  const streamUrl = (id) => M.streamBase + id;
  const coverUrl = (id) => M.coverBase + id;

  const fmt = (s) => {
    if (!s || !isFinite(s)) return "0:00";
    s = Math.floor(s);
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  };

  async function loadTracks() {
    const r = await fetch(M.tracksUrl);
    allTracks = await r.json();
    render(searchEl.value);
  }

  function render(q) {
    q = (q || "").toLowerCase().trim();
    view = q
      ? allTracks.filter((t) =>
          (t.title + " " + t.artist + " " + t.album).toLowerCase().includes(q))
      : allTracks.slice();

    listEl.innerHTML = "";
    if (!view.length) {
      const note = document.createElement("div");
      note.className = "empty-note";
      note.textContent = allTracks.length ? "No matches." : "No tracks yet — run `flask scan`.";
      listEl.appendChild(note);
      return;
    }
    view.forEach((t, i) => {
      const li = document.createElement("li");
      li.dataset.i = i;
      if (currentId() === t.id) li.classList.add("active");
      li.innerHTML =
        `<span class="tl-num">${i + 1}</span>` +
        `<span class="tl-meta"><div class="tl-title"></div><div class="tl-sub"></div></span>`;
      li.querySelector(".tl-title").textContent = t.title;
      li.querySelector(".tl-sub").textContent = [t.artist, t.album].filter(Boolean).join(" · ");
      li.addEventListener("click", () => playAt(i));
      listEl.appendChild(li);
    });
  }

  const currentId = () => (index >= 0 && view[index] ? view[index].id : null);

  function markActive() {
    [...listEl.children].forEach((li) =>
      li.classList.toggle("active", Number(li.dataset.i) === index));
  }

  function playAt(i) {
    if (i < 0 || i >= view.length) return;
    index = i;
    const t = view[i];
    audio.src = streamUrl(t.id);
    audio.play().catch(() => {});
    cassette.classList.add("loaded");
    labelTitle.textContent = t.title;
    labelArtist.textContent = [t.artist, t.album].filter(Boolean).join(" — ");
    if (t.has_cover) { labelArt.src = coverUrl(t.id); }
    else { labelArt.removeAttribute("src"); }
    document.title = t.title + (t.artist ? " · " + t.artist : "");
    markActive();
    setMediaSession(t);
  }

  function setMediaSession(t) {
    if (!("mediaSession" in navigator)) return;
    navigator.mediaSession.metadata = new MediaMetadata({
      title: t.title,
      artist: t.artist || "",
      album: t.album || "",
      artwork: t.has_cover ? [{ src: coverUrl(t.id), sizes: "500x500", type: "image/jpeg" }] : [],
    });
    navigator.mediaSession.setActionHandler("previoustrack", () => playAt(index - 1));
    navigator.mediaSession.setActionHandler("nexttrack", () => playAt(index + 1));
    navigator.mediaSession.setActionHandler("play", () => audio.play());
    navigator.mediaSession.setActionHandler("pause", () => audio.pause());
  }

  function togglePlay() {
    if (index < 0) { playAt(0); return; }
    if (audio.paused) audio.play(); else audio.pause();
  }

  // ---- events ----
  playBtn.addEventListener("click", togglePlay);
  document.getElementById("prevBtn").addEventListener("click", () => playAt(index - 1));
  document.getElementById("nextBtn").addEventListener("click", () => playAt(index + 1));

  audio.addEventListener("play", () => { cassette.classList.add("playing"); playBtn.textContent = "❚❚"; });
  audio.addEventListener("pause", () => { cassette.classList.remove("playing"); playBtn.textContent = "▶"; });
  audio.addEventListener("ended", () => playAt(index + 1));
  audio.addEventListener("loadedmetadata", () => { durTime.textContent = fmt(audio.duration); });
  audio.addEventListener("timeupdate", () => {
    curTime.textContent = fmt(audio.currentTime);
    if (audio.duration) scrubFill.style.width = (audio.currentTime / audio.duration) * 100 + "%";
  });

  scrub.addEventListener("click", (e) => {
    if (!audio.duration) return;
    const rect = scrub.getBoundingClientRect();
    audio.currentTime = ((e.clientX - rect.left) / rect.width) * audio.duration;
  });

  let searchTimer;
  searchEl.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => render(searchEl.value), 120);
  });

  const app = document.getElementById("app");
  document.getElementById("navToggle").addEventListener("click", () =>
    app.classList.toggle("nav-collapsed"));

  document.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); togglePlay(); }
    if (e.key === "ArrowRight" && e.shiftKey) playAt(index + 1);
    if (e.key === "ArrowLeft" && e.shiftKey) playAt(index - 1);
  });

  loadTracks();
})();
