/* The deck's looks: what makes the cassette feel like a tape in a deck.
 *
 * - The label: a printed retro design per album or tape (label-print.js),
 *   and behind the tape a soft glow of the cover's most vivid common colour.
 * - VU needle: a meter needle seen through a slot over the printed scale,
 *   driven by the music's level (the levelling graph in deck-audio.js); with
 *   no graph to read (podcasts, levelling off) it sways with the playing.
 * - Tape changes: a new tape ejects and the next slides in; Keep playing
 *   flips to side B.
 * - Sounds (off by default): the clunk of the keys and a breath of hiss as a
 *   tape goes in, made in Web Audio, no files.
 * - Lock screen: the cassette, label and all, drawn to an image once per
 *   label and stored (routes/stream.py), so the lock screen shows the tape.
 * - Full screen: tapping the cassette (or turning a phone on its side)
 *   leaves just the tape, and keeps the screen on where the browser allows.
 *
 * player.js calls these; nothing here changes what plays. */
(function () {
  const $ = (id) => document.getElementById(id);
  const still = window.matchMedia("(prefers-reduced-motion: reduce)");
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (_) { /* private mode */ } },
  };

  // ---------- the label, and the cover's glow behind the tape ----------
  const NO_GLOW = "transparent";
  const glows = new Map();   // art url -> css colour
  function rgbToHsl(r, g, b) {
    r /= 255; g /= 255; b /= 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
    if (max === min) return [0, 0, l];
    const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
    return [h / 6, s, l];
  }
  // The cover's most vivid common colour: hue buckets weighted by saturation
  // and by how near mid lightness a pixel is (near-black and white don't count).
  function vividGlow(img) {
    const c = document.createElement("canvas");
    c.width = c.height = 24;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0, 24, 24);
    const px = g.getImageData(0, 0, 24, 24).data, buckets = new Map();
    for (let i = 0; i < px.length; i += 4) {
      const [h, s, l] = rgbToHsl(px[i], px[i + 1], px[i + 2]);
      const w = s * Math.sqrt(Math.max(0, 1 - Math.abs(l - 0.5) * 2));
      if (w < 0.08) continue;
      const k = Math.floor(h * 24) % 24, acc = buckets.get(k) || [0, 0, 0, 0];
      acc[0] += w; acc[1] += px[i] * w; acc[2] += px[i + 1] * w; acc[3] += px[i + 2] * w;
      buckets.set(k, acc);
    }
    let best = null;
    for (const acc of buckets.values()) if (!best || acc[0] > best[0]) best = acc;
    if (!best || best[0] < 2) return NO_GLOW;   // a grey cover
    const [h, s] = rgbToHsl(best[1] / best[0], best[2] / best[0], best[3] / best[0]);
    return `hsl(${Math.round(h * 360)} ${Math.round(Math.min(0.7, Math.max(0.4, s)) * 100)}% 45%)`;
  }
  function loadImage(url) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = reject;
      img.src = url;
    });
  }
  async function glowFor(url) {
    if (!url) return NO_GLOW;
    if (!glows.has(url)) {
      try { glows.set(url, vividGlow(await loadImage(url))); } catch (_) { glows.set(url, NO_GLOW); }
    }
    return glows.get(url);
  }
  // The label for what's playing: the seed's design and handwriting (redrawn
  // only when the seed, the album or tape, changes), and the cover's glow.
  // Resolves to the glow.
  let labelSeed = null, labelToken = 0;
  async function setLabel(seed, artUrl) {
    if (seed !== labelSeed) {
      labelSeed = seed;
      LabelPrint.draw($("labelPrint"), seed);
      const { tilt, shift } = LabelPrint.hand(seed), write = $("label").querySelector(".label-write");
      write.style.setProperty("--hand-tilt", `${tilt.toFixed(2)}deg`);
      write.style.setProperty("--hand-shift", `${shift.toFixed(2)}%`);
    }
    const tok = ++labelToken, glow = await glowFor(artUrl);
    if (tok === labelToken) document.documentElement.style.setProperty("--art-glow", glow);
    return glow;
  }

  // ---------- VU needle ----------
  // Rest on 0 (right), full on 100 (left): the needle turns about a pivot
  // below the label and only its tip shows through the slot.
  const REST = 37, FULL = -37;
  const meter = (() => {
    let audio = null, v = 0, last = 0, raf = 0, phase = 0;
    const needle = () => $("vuNeedle");
    function target(dt) {
      if (!audio || audio.paused) return 0;
      const rms = audio.level ? audio.level() : null;
      if (rms == null) {   // nothing to read: sway as if playing
        phase += dt;
        return 0.55 + 0.12 * Math.sin(phase * 2.3) + 0.08 * Math.sin(phase * 5.9) + 0.05 * (Math.random() - 0.5);
      }
      const db = 20 * Math.log10(Math.max(rms, 1e-5));
      return Math.min(1.05, Math.max(0, (db + 38) / 32));   // -38 dBFS .. -6 dBFS
    }
    function frame(t) {
      const dt = last ? Math.min(0.1, (t - last) / 1000) : 0.016;
      last = t;
      const goal = target(dt);
      const tau = goal > v ? 0.07 : 0.32;   // quick up, slow fall, like a real VU
      v += (goal - v) * (1 - Math.exp(-dt / tau));
      const n = needle();
      if (n) n.setAttribute("transform", `rotate(${(REST + (FULL - REST) * Math.min(1, v)).toFixed(2)} 165 150)`);
      if ((audio && !audio.paused) || v > 0.004) raf = requestAnimationFrame(frame);
      else { raf = 0; v = 0; }
    }
    return {
      attach(a) { audio = a; },
      wake() { if (!raf && !still.matches) { last = 0; raf = requestAnimationFrame(frame); } },
    };
  })();

  // ---------- sounds (off by default) ----------
  const sounds = (() => {
    let ctx = null, noise = null;
    const on = () => store.get("tapes-deck-sounds") === "on";
    function context() {
      if (!ctx) {
        const C = window.AudioContext || window.webkitAudioContext;
        if (!C) return null;
        ctx = new C();
        const len = ctx.sampleRate;
        noise = ctx.createBuffer(1, len, ctx.sampleRate);
        const d = noise.getChannelData(0);
        let b = 0;
        for (let i = 0; i < len; i++) { b = 0.97 * b + 0.03 * (Math.random() * 2 - 1); d[i] = (Math.random() * 2 - 1) * 0.6 + b * 2; }
      }
      if (ctx.state === "suspended") ctx.resume().catch(() => {});
      return ctx;
    }
    function burst(c, { at, dur, freq, q, gain }) {
      const src = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
      src.buffer = noise; f.type = "bandpass"; f.frequency.value = freq; f.Q.value = q;
      g.gain.setValueAtTime(gain, at);
      g.gain.exponentialRampToValueAtTime(0.0001, at + dur);
      src.connect(f).connect(g).connect(c.destination);
      src.start(at, Math.random() * 0.5); src.stop(at + dur + 0.02);
    }
    return {
      enabled: on,
      toggle() { store.set("tapes-deck-sounds", on() ? "off" : "on"); if (on()) context(); return on(); },
      // The mechanical key: a click, then the thump of the transport engaging.
      clunk() {
        if (!on()) return;
        const c = context(); if (!c) return;
        const t = c.currentTime;
        burst(c, { at: t, dur: 0.025, freq: 3200, q: 1.2, gain: 0.35 });
        const o = c.createOscillator(), g = c.createGain();
        o.frequency.setValueAtTime(110, t + 0.012); o.frequency.exponentialRampToValueAtTime(45, t + 0.11);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.5, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.14);
        o.connect(g).connect(c.destination); o.start(t); o.stop(t + 0.16);
        burst(c, { at: t + 0.04, dur: 0.06, freq: 900, q: 0.8, gain: 0.12 });
      },
      // A tape going in: the clatter of the door, then a breath of hiss.
      insert() {
        if (!on()) return;
        const c = context(); if (!c) return;
        const t = c.currentTime;
        burst(c, { at: t, dur: 0.05, freq: 1800, q: 0.9, gain: 0.25 });
        burst(c, { at: t + 0.09, dur: 0.04, freq: 2600, q: 1.5, gain: 0.2 });
        const src = c.createBufferSource(), hp = c.createBiquadFilter(), g = c.createGain();
        src.buffer = noise; src.loop = true; hp.type = "highpass"; hp.frequency.value = 3500;
        g.gain.setValueAtTime(0.0001, t + 0.15); g.gain.linearRampToValueAtTime(0.025, t + 0.4); g.gain.linearRampToValueAtTime(0.0001, t + 1.5);
        src.connect(hp).connect(g).connect(c.destination); src.start(t + 0.15); src.stop(t + 1.6);
      },
    };
  })();

  // ---------- tape changes ----------
  // One movement of the cassette: animate out, `swap` what it shows, animate
  // back in. Queued, so a quick second change waits for the first.
  let busy = Promise.resolve();
  function move(out, back, swap) {
    const el = $("cassette");
    if (still.matches || !el || !el.animate) { swap(); return; }
    busy = busy.then(async () => {
      // Cancelled by reference: once the second replaces the first, the
      // browser stops listing the first, which would hold the tape hidden.
      const moves = [];
      let swapped = false;
      try {
        moves.push(el.animate(out.frames, { ...out.timing, fill: "forwards" }));
        await moves[0].finished;
        swap(); swapped = true;
        moves.push(el.animate(back.frames, { ...back.timing, fill: "forwards" }));
        await moves[1].finished;
      } catch (e) {
        console.warn("Tape animation:", e);
        if (!swapped) swap();
      } finally {
        moves.forEach((m) => m.cancel());   // never leave the tape faded out
      }
    });
  }
  // Out goes the old tape, in slides the new one (with its label written).
  function changeTape(swap) {
    move({ frames: [{ transform: "none", opacity: 1 }, { transform: "translateY(14%) scale(0.97)", opacity: 0 }],
           timing: { duration: 240, easing: "cubic-bezier(.5,0,.75,0)" } },
         { frames: [{ transform: "translateY(-10%) scale(0.98)", opacity: 0 }, { transform: "translateY(1.5%)", opacity: 1, offset: 0.75 }, { transform: "none", opacity: 1 }],
           timing: { duration: 420, easing: "cubic-bezier(.2,.8,.3,1)" } },
         () => { swap(); sounds.insert(); });
  }
  // Turn the tape over: side A to B (Keep playing) or back.
  function flip(side) {
    const turn = (from, to) => [{ transform: `perspective(1200px) rotateY(${from})` }, { transform: `perspective(1200px) rotateY(${to})` }];
    move({ frames: turn("0deg", "90deg"), timing: { duration: 230, easing: "ease-in" } },
         { frames: turn("-90deg", "0deg"), timing: { duration: 280, easing: "ease-out" } },
         () => { $("sideLetter").textContent = side; });
  }

  // ---------- the cassette as lock-screen artwork ----------
  const ART = 512;
  // Draws the deck's SVG, then the label's art and writing (read from the
  // label on screen: its positions, fonts and tilt), into a square image.
  async function drawCassette(glow) {
    const deck = $("cassette"), svg = deck.querySelector(".cassette-svg");
    const clone = svg.cloneNode(true);
    clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
    clone.setAttribute("width", 330 * 3); clone.setAttribute("height", 206 * 3);
    clone.querySelector("#vuNeedle")?.setAttribute("transform", `rotate(${REST} 165 150)`);
    const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)], { type: "image/svg+xml" }));
    try {
      const shell = await loadImage(url);
      const S = ART * 2, c = document.createElement("canvas");
      c.width = c.height = S;
      const g = c.getContext("2d");
      g.fillStyle = "#1a1817"; g.fillRect(0, 0, S, S);
      if (glow !== NO_GLOW) {
        const rg = g.createRadialGradient(S / 2, S * 0.52, 0, S / 2, S * 0.52, S * 0.55);
        rg.addColorStop(0, glow); rg.addColorStop(1, "rgba(0,0,0,0)");
        g.globalAlpha = 0.35; g.fillStyle = rg; g.fillRect(0, 0, S, S); g.globalAlpha = 1;
      }
      const w = S * 0.92, h = w * 206 / 330, x = (S - w) / 2, y = (S - h) / 2;
      g.save(); g.shadowColor = "rgba(0,0,0,0.6)"; g.shadowBlur = 40; g.shadowOffsetY = 24;
      g.drawImage(shell, x, y, w, h); g.restore();
      // Screen boxes → canvas boxes (the label sits over the SVG in the same frame).
      const frame = deck.getBoundingClientRect(), k = w / frame.width;
      const box = (el) => { const r = el.getBoundingClientRect(); return { x: x + (r.left - frame.left) * k, y: y + (r.top - frame.top) * k, w: r.width * k, h: r.height * k }; };
      const art = $("labelArt");
      if (art.getAttribute("src") && art.complete && art.naturalWidth) {   // cover-fit, the box's corner cut
        const b = box(art), cut = b.w * 0.17;
        g.save(); g.beginPath();
        g.moveTo(b.x + cut, b.y); g.lineTo(b.x + b.w, b.y); g.lineTo(b.x + b.w, b.y + b.h); g.lineTo(b.x, b.y + b.h); g.lineTo(b.x, b.y + b.h * 0.14); g.closePath(); g.clip();
        const s = Math.max(b.w / art.naturalWidth, b.h / art.naturalHeight);
        g.drawImage(art, b.x + (b.w - art.naturalWidth * s) / 2, b.y + (b.h - art.naturalHeight * s) / 2, art.naturalWidth * s, art.naturalHeight * s);
        g.restore();
      }
      // The writing keeps its tilt: turn about the writing area's bottom-left, as the CSS does.
      const write = deck.querySelector(".label-write"), tilt = parseFloat(getComputedStyle(write).getPropertyValue("--hand-tilt")) || -0.5;
      const wb = box(write);
      g.save();
      g.translate(wb.x, wb.y + wb.h); g.rotate(tilt * Math.PI / 180); g.translate(-wb.x, -(wb.y + wb.h));
      for (const el of [$("labelTitle"), $("labelArtist")]) {
        const cs = getComputedStyle(el), b = box(el), size = parseFloat(cs.fontSize) * k;
        g.font = `${cs.fontWeight} ${size}px ${cs.fontFamily}`;
        let t = el.textContent;
        if (g.measureText(t).width > b.w) { while (t && g.measureText(t + "…").width > b.w) t = t.slice(0, -1); t += "…"; }
        g.fillStyle = cs.color;
        g.textBaseline = "alphabetic";
        g.fillText(t, b.x + parseFloat(cs.paddingLeft) * k, b.y + b.h - parseFloat(cs.paddingBottom) * k - size * 0.22);
      }
      g.restore();
      const out = document.createElement("canvas");
      out.width = out.height = ART;
      out.getContext("2d").drawImage(c, 0, 0, ART, ART);
      return await new Promise((r) => out.toBlob(r, "image/jpeg", 0.88));
    } finally { URL.revokeObjectURL(url); }
  }
  const djb2 = (s) => { let h = 5381; for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0; return h.toString(36); };
  const LOCK_VERSION = 5;
  const ready = new Map();   // url -> true once it exists on the server
  /** The lock-screen URL for this label, once drawn and stored; draws it if needed.
   *  Calls onReady(url) when it becomes available. */
  async function lockArt(base, t, { title, sub, artUrl, glow, seed }, onReady) {
    const key = djb2([LOCK_VERSION, t.id, title, sub, artUrl || "", glow, seed].join("|"));
    const url = `${base}${t.id}/${key}`;
    if (ready.get(url)) return url;
    try {
      if ((await fetch(url, { method: "HEAD" })).ok) { ready.set(url, true); onReady(url); return url; }
      await busy;                       // a tape change still swapping the label
      await document.fonts.ready;
      await $("labelArt").decode?.().catch(() => {});
      if ($("labelTitle").textContent !== title) return null;   // moved on to another song
      const blob = await drawCassette(glow);
      if (!blob) return null;
      if ((await fetch(url, { method: "PUT", body: blob, headers: { "Content-Type": "image/jpeg" } })).ok) {
        ready.set(url, true); onReady(url); return url;
      }
    } catch (e) { console.warn("Lock-screen cassette not drawn:", e); }
    return null;
  }

  // ---------- full screen: just the tape ----------
  let wakeLock = null;
  async function holdScreen(on) {
    try {
      if (on && !wakeLock && navigator.wakeLock) {
        wakeLock = await navigator.wakeLock.request("screen");
        wakeLock.addEventListener("release", () => { wakeLock = null; });
      } else if (!on && wakeLock) { await wakeLock.release(); wakeLock = null; }
    } catch (_) { /* not allowed now */ }
  }
  function setImmersive(on) {
    $("app").classList.toggle("immersive", on);
    holdScreen(on);
    const root = document.documentElement;
    if (on && root.requestFullscreen && !document.fullscreenElement) root.requestFullscreen({ navigationUI: "hide" }).catch(() => {});
    if (!on && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }
  const immersive = () => $("app").classList.contains("immersive");
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible" && immersive()) holdScreen(true); });
  // Leaving the browser's full screen (the back gesture) leaves ours too.
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && immersive()) setImmersive(false); });

  window.DeckFX = { setLabel, meter, sounds, changeTape, flip, lockArt, setImmersive };
})();
