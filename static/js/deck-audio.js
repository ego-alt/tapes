/* The deck's audio: one object that behaves like an <audio> element for
 * player.js, with two things a plain element can't do.
 *
 * Gapless. Music plays as one continuous MediaSource stream. Each MP3 is
 * appended with its encoder delay and padding trimmed (the server reads both
 * from the LAME/Info tag), so the next song starts on the exact sample the
 * last one ended. Chrome's MSE path already accounts for the decoder delay and
 * the Info frame; only the encoder's own delay and padding need trimming
 * (measured: a sample-exact join, against 17 ms of silence for back-to-back
 * <audio> loads). When player.js loads the song that was appended next, the
 * stream simply carries on.
 *
 * Volume levelling. Music runs through a Web Audio gain set from the song's
 * EBU R128 loudness (measured on the server): album gain when an album is
 * playing in order, track gain otherwise, never letting a true peak above
 * -1 dBTP. The gain changes on the boundary sample, not when the UI notices.
 *
 * Times and durations are per song, so player.js keeps reading currentTime
 * and duration as before. Anything this can't do (no MSE, no gapless info, an
 * error) falls back to a plain element load for that song. Podcasts play on
 * their own plain element: their streams can come from another site, which a
 * Web Audio graph would silence. */
(function () {
  const TARGET_LUFS = -14;        // Spotify's "normal"; a bit below most rips
  const MAX_PEAK_DB = -1;         // true-peak ceiling after gain
  const GAIN_RANGE = [-20, 12];   // dB
  const BACK_BUFFER_S = 15;       // kept behind the playhead when memory runs short
  // Long tracks (mixes, live sets) play the plain way: gapless doesn't matter
  // there, and a plain element can jump straight to any point of a long file.
  const MAX_GAPLESS_S = 15 * 60;
  const MSE_TYPE = "audio/mpeg";
  const FORWARDED = ["play", "pause", "playing", "waiting", "loadedmetadata", "durationchange",
    "timeupdate", "seeking", "seeked", "emptied", "ended", "error", "canplay", "ratechange", "volumechange"];

  const mseSupported = () => !!(window.MediaSource && MediaSource.isTypeSupported(MSE_TYPE));
  const gaplessOk = (t) => !!(t && t.kind !== "episode" && t.gapless
    && t.gapless.samples / t.gapless.rate <= MAX_GAPLESS_S);
  const once = (el, ev) => new Promise((r) => el.addEventListener(ev, r, { once: true }));
  const isQuotaError = (e) => e && (e.name === "QuotaExceededError" || e.code === 22);
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  class DeckAudio extends EventTarget {
    constructor(musicEl, episodeEl) {
      super();
      this.music = musicEl;
      this.episode = episodeEl;
      this.mode = "idle";          // "mse" | "plain" | "episode" | "idle"
      this.seg = null;             // the song playing: { track, url, t0, t1, ... }
      this.next = null;            // the song appended after it (mse only)
      this.levelling = true;
      this.gen = 0;                // bumped on every reset; stale work checks it
      this.ctx = null;
      this.gainNode = null;
      this.analyser = null;        // taps the levelled sound for the VU needle (deck-fx.js)
      this.boundaryTimer = null;
      for (const el of [musicEl, episodeEl]) {
        for (const ev of FORWARDED) el.addEventListener(ev, (e) => this._forward(el, ev, e));
      }
    }

    // ---------- element-like surface used by player.js ----------
    get el() { return this.mode === "episode" ? this.episode : this.music; }
    get paused() { return this.el.paused; }
    get readyState() { return this.el.readyState; }
    get src() { return this.seg ? this.seg.url : ""; }
    get currentSrc() { return this.src; }
    getAttribute(name) { return name === "src" ? (this.seg ? this.seg.url : null) : null; }
    removeAttribute(name) { if (name === "src") this._stop(); }

    get currentTime() {
      if (this.mode !== "mse" || !this.seg) return this.el.currentTime;
      return Math.min(Math.max(0, this.music.currentTime - this.seg.t0), this.seg.t1 - this.seg.t0);
    }
    set currentTime(v) {
      if (this.mode !== "mse" || !this.seg) { this.el.currentTime = v; return; }
      const len = this.seg.t1 - this.seg.t0;
      const target = this.seg.t0 + Math.min(Math.max(0, v), Math.max(0, len - 0.05));
      // A stream only takes audio in order: a jump past what's loaded, in a song
      // that's hit the memory limit (or well ahead), plays the plain way from there.
      if (!this._buffered(target) && (this.seg.memoryFull || target > this._bufferedEnd() + 30)) {
        this._toPlain(v);
        return;
      }
      this.music.currentTime = target;
      this._scheduleBoundary();
    }
    get duration() {
      if (this.mode !== "mse" || !this.seg) return this.el.duration;
      return this.seg.t1 - this.seg.t0;
    }

    get volume() { return this.music.volume; }
    set volume(v) { this.music.volume = v; this.episode.volume = v; }
    get muted() { return this.music.muted; }
    set muted(v) { this.music.muted = v; this.episode.muted = v; }
    get playbackRate() { return this.el.playbackRate; }
    set playbackRate(v) { this.el.playbackRate = v; }

    play() {
      if (this.mode !== "episode") this._ensureGraph();
      if (this.ctx && this.ctx.state === "suspended") this.ctx.resume().catch(() => {});
      return this.el.play();
    }
    pause() { this.el.pause(); }
    load() {   // reload the current song from the top (player.js seeks after loadedmetadata)
      if (this.seg) this._open(this.seg.track, this.seg.url, this.seg.opts, { fresh: true });
      else this.el.load();
    }

    // ---------- deck API ----------
    /** Load a track. opts.album: an album is playing in order (album gain). */
    open(track, url, opts = {}) {
      if (track.kind === "episode") { this._openEpisode(track, url); return; }
      // The song already streaming in after this one: carry on, no reload.
      if (this.mode === "mse" && this.next && this.next.url === url) { this._adopt(opts); return; }
      this._open(track, url, opts, {});
    }

    /** The song that follows (or null). Appended to the stream for a gapless join. */
    setNext(track, url, opts = {}) {
      const usable = gaplessOk(track) && this.mode === "mse";
      if (this.next && (!usable || this.next.url !== url)) this._dropNext();
      if (!usable || (this.next && this.next.url === url)) return;
      const t0 = this.seg.t1;
      this.next = this._segment(track, url, opts, t0);
      this._appendWhenReady(this.next, this.gen);
    }

    /** Volume levelling on/off (on by default). */
    setLevelling(on) {
      this.levelling = !!on;
      // The audio graph starts on a play press (browsers require a gesture);
      // switching on mid-song builds it now.
      if (on && !this.music.paused) this._ensureGraph();
      this._applyGain(this.seg, 0);
    }

    // ---------- internals ----------
    _forward(el, ev, e) {
      if (el !== this.el) return;                      // the idle element
      if (this.mode === "mse") {
        if (ev === "ended") { this._crossBoundary(true); return; }
        if (ev === "timeupdate") this._checkBoundary();
        if (ev === "error") { this._mseFailed(); return; }
        if (ev === "durationchange") return;           // the stream's, not the song's
      }
      this.dispatchEvent(new Event(ev));
    }

    _segment(track, url, opts, t0) {
      const g = track.gapless;
      const len = g.samples / g.rate;
      return { track, url, opts, t0, t1: t0 + len, delay: g.delay / g.rate, abort: new AbortController(),
               appended: false, memoryFull: false };
    }

    _open(track, url, opts, { startAt = 0, autoplay = false, fresh = false } = {}) {
      this._reset();
      if (!mseSupported() || !gaplessOk(track)) { this._openPlain(track, url, opts); return; }
      const gen = this.gen;
      this.mode = "mse";
      const seg = this.seg = this._segment(track, url, opts, 0);
      const ms = this.ms = new MediaSource();
      this.music.src = URL.createObjectURL(ms);
      ms.addEventListener("sourceopen", () => {
        if (gen !== this.gen) return;
        try {
          this.sb = ms.addSourceBuffer(MSE_TYPE);
        } catch (_) { this._openPlain(track, url, opts); return; }
        this._applyGain(seg, 0);
        this._append(seg, gen).then(() => {
          if (gen !== this.gen) return;
          if (startAt) this.currentTime = startAt;
          if (autoplay) this.play().catch(() => {});
        });
      }, { once: true });
      this.music.addEventListener("loadedmetadata", () => {
        if (gen === this.gen && startAt) this.currentTime = startAt;
      }, { once: true });
      if (fresh) this.dispatchEvent(new Event("emptied"));
    }

    _openPlain(track, url, opts) {
      this._reset();
      this.mode = "plain";
      this.seg = { track, url, opts, t0: 0, t1: 0 };
      this._applyGain(this.seg, 0);
      this.music.src = url;
    }

    _openEpisode(track, url) {
      this._reset();
      this.mode = "episode";
      this.seg = { track, url, opts: {}, t0: 0, t1: 0 };
      this.episode.src = url;
    }

    _reset() {
      this.gen++;
      clearTimeout(this.boundaryTimer);
      for (const s of [this.seg, this.next]) if (s && s.abort) s.abort.abort();
      this.seg = this.next = null;
      this.sb = null;
      if (this.ms) { const u = this.music.src; this.ms = null; this.music.removeAttribute("src"); this.music.load(); URL.revokeObjectURL(u); }
      if (!this.music.paused) this.music.pause();
      if (!this.episode.paused) this.episode.pause();
    }

    _stop() { this._reset(); this.mode = "idle"; this.music.removeAttribute("src"); this.episode.removeAttribute("src"); }

    /** Serialize SourceBuffer work: one operation at a time. */
    async _sbDo(fn, gen) {
      while (this.sb && this.sb.updating) await once(this.sb, "updateend");
      if (gen !== this.gen || !this.sb) throw new Error("stale");
      fn(this.sb);
      if (this.sb.updating) await once(this.sb, "updateend");
    }

    /** Stream a song into the buffer: windowed so only its real samples land. */
    async _append(seg, gen) {
      try {
        await this._sbDo((sb) => {
          sb.appendWindowStart = 0;
          sb.appendWindowEnd = Infinity;
          sb.timestampOffset = seg.t0 - seg.delay;
          sb.appendWindowStart = seg.t0;
          sb.appendWindowEnd = seg.t1;
        }, gen);
        const res = await fetch(seg.url, { signal: seg.abort.signal });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);
        const reader = res.body.getReader();
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          await this._appendChunk(value, seg, gen);
        }
        seg.appended = true;
        if (gen === this.gen && this.ms && this.ms.readyState === "open" && !this.next) this._endStream(gen);
        if (seg === this.seg) this._scheduleBoundary();
      } catch (e) {
        if (gen !== this.gen || e.name === "AbortError" || e.message === "stale") return;
        if (seg === this.seg) this._mseFailed();
        else if (seg === this.next) this._dropNext();   // the next song plays the normal way
      }
    }

    async _appendChunk(chunk, seg, gen) {
      for (;;) {
        try {
          await this._sbDo((sb) => sb.appendBuffer(chunk), gen);
          return;
        } catch (e) {
          if (!isQuotaError(e)) throw e;
          seg.memoryFull = true;
          // Out of room: drop what's well behind the playhead, or wait for playback to catch up.
          const behind = this.music.currentTime - BACK_BUFFER_S;
          const start = this.sb && this.sb.buffered.length ? this.sb.buffered.start(0) : 0;
          if (behind > start + 1) {
            await this._sbDo((sb) => sb.remove(start, behind), gen);
          } else {
            await sleep(1000);
            if (gen !== this.gen) throw new Error("stale");
          }
        }
      }
    }

    _endStream(gen) {
      this._sbDo(() => {}, gen).then(() => {
        if (gen === this.gen && this.ms && this.ms.readyState === "open" && !this.next) {
          try { this.ms.endOfStream(); } catch (_) { /* already ended */ }
        }
      }).catch(() => {});
    }

    async _appendWhenReady(next, gen) {
      while (gen === this.gen && this.seg && !this.seg.appended) await sleep(250);
      if (gen !== this.gen || this.next !== next) return;
      this._append(next, gen);
      this._scheduleBoundary();
    }

    _dropNext() {
      const next = this.next;
      this.next = null;
      if (!next) return;
      next.abort.abort();
      const gen = this.gen;
      if (this.sb) {
        this._sbDo((sb) => { sb.abort(); sb.remove(next.t0, Infinity); }, gen)
          .then(() => this._endStream(gen)).catch(() => {});
      }
      this._applyGain(this.seg, 0);
    }

    _bufferedEnd() {
      const b = this.music.buffered;
      return b.length ? b.end(b.length - 1) : 0;
    }

    _buffered(t) {
      const b = this.music.buffered;
      for (let i = 0; i < b.length; i++) if (t >= b.start(i) && t < b.end(i)) return true;
      return false;
    }

    /** Fire the per-song "ended" right on the boundary (timeupdate is ~4 Hz). */
    _scheduleBoundary() {
      clearTimeout(this.boundaryTimer);
      if (this.mode !== "mse" || !this.seg || !this.next) return;
      const left = (this.seg.t1 - this.music.currentTime) / (this.music.playbackRate || 1);
      this._scheduleGain(left);
      if (left > 0) this.boundaryTimer = setTimeout(() => this._checkBoundary(), left * 1000 + 5);
    }

    _checkBoundary() {
      if (this.mode === "mse" && this.seg && this.next && this.music.currentTime >= this.seg.t1 - 0.005) {
        this._crossBoundary(false);
      }
    }

    /** The playing song has finished. Tell player.js; it loads the next one
     *  (and _adopt carries on without a gap), or it stops. */
    _crossBoundary(streamEnded) {
      clearTimeout(this.boundaryTimer);
      const before = this.seg;
      this.dispatchEvent(new Event("ended"));
      if (this.seg !== before || streamEnded) return;     // adopted, or stopped at the very end
      // Not continued (end of queue, repeat-one): stay at the end of this song.
      this._dropNext();
      this.music.pause();
      this.music.currentTime = Math.max(before.t0, before.t1 - 0.01);
    }

    _adopt(opts) {
      const prev = this.seg, seg = this.next;
      seg.opts = opts;
      this.seg = seg;
      this.next = null;
      if (this.music.currentTime < seg.t0) this.music.currentTime = seg.t0;   // skipped ahead early
      this._applyGain(seg, 0);
      const gen = this.gen;
      if (this.sb && prev) this._sbDo((sb) => sb.remove(0, Math.max(0, seg.t0 - 1)), gen).catch(() => {});
      // player.js queues the song after this one right after loading it; only
      // end the stream if it didn't.
      setTimeout(() => { if (gen === this.gen && seg.appended && !this.next) this._endStream(gen); }, 0);
      for (const ev of ["emptied", "loadedmetadata", "durationchange", "timeupdate"]) this.dispatchEvent(new Event(ev));
      if (!this.music.paused) this.dispatchEvent(new Event("play"));   // a new song started
    }

    _mseFailed() { this._toPlain(this.currentTime); }

    /** Carry on with this song the plain way, from `at` seconds. */
    _toPlain(at) {
      if (!this.seg || !this.seg.track) return;
      const { track, url, opts } = this.seg;
      const playing = !this.music.paused;
      this._openPlain(track, url, opts);
      this.music.addEventListener("loadedmetadata", () => {
        this.music.currentTime = at;
        if (playing) this.play().catch(() => {});
      }, { once: true });
    }

    // ---------- levelling ----------
    _ensureGraph() {
      if (this.ctx || !this.levelling) return;
      try {
        const Ctx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new Ctx();
        const src = this.ctx.createMediaElementSource(this.music);
        this.gainNode = this.ctx.createGain();
        src.connect(this.gainNode).connect(this.ctx.destination);
        this.analyser = this.ctx.createAnalyser();
        this.analyser.fftSize = 1024;
        this.gainNode.connect(this.analyser);
        this._levelBuf = new Float32Array(this.analyser.fftSize);
        this._applyGain(this.seg, 0);
      } catch (e) {
        console.warn("Volume levelling unavailable:", e);
        this.ctx = this.gainNode = this.analyser = null;
      }
    }

    /** The music's RMS level now (0..1), or null when there's nothing to read
     *  (a podcast, or levelling off so no graph). */
    level() {
      if (!this.analyser || this.mode === "episode") return null;
      this.analyser.getFloatTimeDomainData(this._levelBuf);
      let sum = 0;
      for (const x of this._levelBuf) sum += x * x;
      return Math.sqrt(sum / this._levelBuf.length);
    }

    /** The gain for a song, in linear terms. */
    gainFor(seg) {
      if (!this.levelling || !seg || !seg.track || seg.track.kind === "episode") return 1;
      const t = seg.track, album = seg.opts && seg.opts.album && t.album_lufs != null;
      const lufs = album ? t.album_lufs : t.lufs;
      if (lufs == null) return 1;
      const peak = (album ? t.album_peak : t.peak) ?? 0;
      let db = TARGET_LUFS - lufs;
      db = Math.min(db, MAX_PEAK_DB - peak);              // never push a peak past the ceiling
      db = Math.min(GAIN_RANGE[1], Math.max(GAIN_RANGE[0], db));
      return 10 ** (db / 20);
    }

    _applyGain(seg, inSeconds) {
      if (!this.gainNode) return;
      const g = this.gainNode.gain, at = this.ctx.currentTime + Math.max(0, inSeconds);
      g.cancelScheduledValues(this.ctx.currentTime);
      g.setValueAtTime(this.gainFor(seg), at);
    }

    _scheduleGain(inSeconds) {   // the next song's gain, on its first sample
      if (!this.gainNode || !this.next) return;
      const g = this.gainNode.gain, now = this.ctx.currentTime;
      g.cancelScheduledValues(now);
      g.setValueAtTime(this.gainFor(this.seg), now);
      g.setValueAtTime(this.gainFor(this.next), now + Math.max(0, inSeconds));
    }
  }

  window.DeckAudio = DeckAudio;
})();
