/* The printed design on the cassette's paper label: one of a dozen bold
 * geometric designs, the kind 70s and 80s tapes were printed with.
 *
 * The design is chosen (and varied: angle, count, spacing) from a seed, the
 * album or tape name, so an album always prints the same way and every song
 * on it shares the label. Drawn in the cassette's 330×206 view-box units
 * into the print area under the writing lines; the solid band below it
 * (where "C60" is printed) is tan.
 *
 * Every tape is printed in one retro palette, red, orange, mustard and
 * brown on cream with a tan band; the seed also picks the order the inks go
 * in. Inks are named a, c, d, e (and b, the tan) so a design can say "the
 * first band, the second…" without naming colours. Printed as overprinting
 * ink (multiply, set on the group in the SVG), as on real labels. */
(function () {
  const X0 = 15.5, X1 = 314.5, Y0 = 60, Y1 = 114.5, W = X1 - X0, H = Y1 - Y0;
  const CX = (X0 + X1) / 2, CY = (Y0 + Y1) / 2;
  const f = (n) => +n.toFixed(2);

  // A small seeded generator (mulberry32), so a seed always draws the same.
  function rng(seed) {
    let h = 1779033703 ^ seed.length;
    for (let i = 0; i < seed.length; i++) { h = Math.imul(h ^ seed.charCodeAt(i), 3432918353); h = (h << 13) | (h >>> 19); }
    let a = h >>> 0;
    return () => {
      a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const pick = (r, list) => list[Math.floor(r() * list.length)];
  const between = (r, lo, hi) => lo + r() * (hi - lo);
  const rect = (x, y, w, h, ink) => `<rect class="ink-${ink}" x="${f(x)}" y="${f(y)}" width="${f(w)}" height="${f(h)}"/>`;
  const poly = (pts, ink) => `<polygon class="ink-${ink}" points="${pts.map(([x, y]) => `${f(x)},${f(y)}`).join(" ")}"/>`;
  const path = (d, ink, stroke) => stroke
    ? `<path class="ink-${ink}" d="${d}" fill="none" stroke-width="${f(stroke)}"/>`
    : `<path class="ink-${ink}" d="${d}"/>`;

  // Broad retro designs: a few big shapes in a family of inks.
  const RAINBOW = ["c", "a", "e", "d"];
  const circle = (cx, cy, rad, ink) => `<circle class="ink-${ink}" cx="${f(cx)}" cy="${f(cy)}" r="${f(rad)}"/>`;
  const side = (r) => (r() > 0.5 ? 1 : -1);                       // which end of the label a shape favours
  const atSide = (s, inset) => (s > 0 ? X1 - inset : X0 + inset);
  const DESIGNS = {
    // Thick rainbow bands straight across: the 70s classic.
    rainbow(r) {
      const n = pick(r, [3, 4]), gap = between(r, 1.2, 2.4), h = (H - 6 - gap * (n - 1)) / n;
      return RAINBOW.slice(0, n).map((ink, i) => rect(X0, Y0 + 6 + i * (h + gap), W, h, ink)).join("");
    },
    // Bands that run flat, then sweep up at one end, like a racing stripe.
    swoosh(r) {
      const s = side(r), n = pick(r, [3, 4]), band = H / (n + 1.2), turn = s > 0 ? X1 - between(r, 40, 70) : X0 + between(r, 40, 70);
      return RAINBOW.slice(0, n).map((ink, i) => {
        const y = Y0 + band * (i + 1.1), rise = 70 + i * band;
        const end = s > 0 ? X1 + 40 : X0 - 40;
        return path(`M${s > 0 ? X0 - 5 : X1 + 5} ${f(y)} H${f(turn)} Q${f(turn + s * 26)} ${f(y)} ${f(end)} ${f(y - rise)}`, ink, band * 0.82);
      }).join("");
    },
    // A rainbow arch rising from the bottom edge beside the window.
    arch(r) {
      const s = side(r), cx = atSide(s, between(r, 24, 30)), w = between(r, 8.5, 10.5);
      return RAINBOW.map((ink, i) => `<circle class="ink-${ink}" cx="${f(cx)}" cy="${Y1}" r="${f(w * (4.5 - i))}" fill="none" stroke-width="${f(w)}"/>`).join("");
    },
    // A sun setting at one end, its lower half cut into widening gaps, with
    // bands across the sky.
    sunset(r) {
      const s = side(r), cx = atSide(s, between(r, 26, 34)), rad = between(r, 22, 26), cy = Y1 - 2;
      const slices = [];
      for (let y = cy - rad, k = 0; y < Y1; k++) {
        const h = y < cy - rad * 0.4 ? rad * 0.6 : Math.max(1.2, 4.5 - k * 0.7);
        slices.push(rect(cx - rad, y, rad * 2, h, "a"));
        y += h + (y < cy - rad * 0.4 ? 1.2 : 1 + k * 0.5);
      }
      return rect(X0, Y0 + 6, W, 6, "c") + rect(X0, Y0 + 15, W, 4, "e")
        + `<clipPath id="lp-sun"><circle cx="${f(cx)}" cy="${f(cy)}" r="${f(rad)}"/></clipPath><g clip-path="url(#lp-sun)">${slices.join("")}</g>`;
    },
    // The label split into a few broad slanting fields of colour.
    fields(r) {
      const slope = between(r, 18, 34) * side(r), widths = [between(r, 30, 60), between(r, 18, 30), between(r, 10, 18), between(r, 6, 10)];
      let x = between(r, X0 + 20, X0 + 60);
      return RAINBOW.map((ink, i) => {
        const w = widths[i], pts = [[x, Y1], [x + w, Y1], [x + w + slope, Y0], [x + slope, Y0]];
        x += w + 6 + between(r, 30, 70);
        return poly(pts, ink);
      }).join("") + poly([[X1 - 50, Y1], [X1 + 10, Y1], [X1 + 10 + slope, Y0], [X1 - 50 + slope, Y0]], "a");
    },
    // Two or three huge chevrons.
    chevrons(r) {
      const n = pick(r, [2, 3]), w = between(r, 9, 13), depth = between(r, 18, 26), out = [];
      for (let i = 0; i < n; i++) {
        const y = Y0 + 10 + i * (w + 4);
        out.push(path(`M${X0 - 10} ${f(y)} L${CX} ${f(y + depth)} L${X1 + 10} ${f(y)}`, RAINBOW[i], w));
      }
      return out.join("");
    },
    // Overlapping mountain peaks along the bottom.
    peaks(r) {
      const out = [];
      for (const [k, ink] of [["far", "c"], ["mid", "e"], ["near", "a"]]) {
        const h = { far: H * 0.95, mid: H * 0.75, near: H * 0.5 }[k], w = h * between(r, 1.3, 1.9);
        for (let x = X0 - w / 2 + between(r, 0, w / 2); x < X1; x += w * between(r, 0.8, 1.2)) {
          out.push(poly([[x, Y1], [x + w / 2, Y1 - h], [x + w, Y1]], ink));
        }
      }
      return out.join("");
    },
    // Memphis: a big disc at one end; a triangle and a ring overlapping at the other.
    memphis(r) {
      const s = side(r);
      return circle(atSide(s, 30), Y0 + 26, 20, "c")
        + poly([[atSide(-s, 8), Y1], [atSide(-s, 52), Y1], [atSide(-s, 30), Y0 + 8]], "a")
        + `<circle class="ink-e" cx="${f(atSide(-s, 42))}" cy="${Y0 + 20}" r="12" fill="none" stroke-width="4"/>`
        + rect(X0, Y1 - 6, W, 6, "d");
    },
    // Bauhaus tiles: big squares, each with a quarter circle.
    bauhaus(r) {
      const sz = H / 2, out = [];
      for (let x = X0, i = 0; x < X1; x += sz, i++) {
        for (let j = 0; j < 2; j++) {
          const y = Y0 + j * sz, ink = RAINBOW[(i + j * 2) % 4], corner = Math.floor(r() * 4);
          const [cx, cy] = [[x, y], [x + sz, y], [x + sz, y + sz], [x, y + sz]][corner];
          out.push(rect(x, y, sz, sz, (i + j) % 2 ? "b" : "d"));
          out.push(`<path class="ink-${ink}" d="M${f(cx)} ${f(cy)} m${corner === 1 || corner === 2 ? -sz : sz} 0 A${f(sz)} ${f(sz)} 0 0 ${corner % 2} ${f(cx)} ${f(cy + (corner < 2 ? sz : -sz))} L${f(cx)} ${f(cy)} Z"/>`);
        }
      }
      return out.join("");
    },
    // Big checks in two rows.
    checks(r) {
      const sz = H / 2, out = [], offset = between(r, 0, sz);
      for (let x = X0 - offset, i = 0; x < X1; x += sz, i++) {
        for (let j = 0; j < 2; j++) if ((i + j) % 2) out.push(rect(x, Y0 + j * sz, sz, sz, RAINBOW[i % 4]));
      }
      return out.join("");
    },
    // Two or three thick, slow waves.
    waves(r) {
      const n = pick(r, [2, 3]), len = between(r, 90, 140), amp = between(r, 6, 10), band = H / (n + 0.3);
      return RAINBOW.slice(0, n).map((ink, i) => {
        const y = Y0 + band * (i + 0.65);
        let d = `M${X0 - len} ${f(y)}`;
        for (let x = X0 - len; x < X1 + len; x += len) d += ` q${f(len / 4)} ${-amp} ${f(len / 2)} 0 t${f(len / 2)} 0`;
        return path(d, ink, band * 0.75);
      }).join("");
    },
    // A block of wide vertical stripes at one end, the rest left as paper.
    block(r) {
      const s = side(r), w = between(r, 9, 12), out = [rect(X0, Y0 + 8, W, 5, "d")];
      RAINBOW.forEach((ink, i) => out.push(rect(s > 0 ? X1 - (4 - i) * w : X0 + i * w, Y0, w, H, ink)));
      return out.join("");
    },
  };
  const NAMES = Object.keys(DESIGNS);

  /** The design's name and markup for a seed (an album or tape name). */
  const RETRO = { red: "#c43c2e", orange: "#e0702a", mustard: "#e6b23a", brown: "#6d3e24", tan: "#b08d68" };
  // The inks in rainbow order (c, a, e, d): a few classic runs to choose from.
  const RUNS = [["mustard", "orange", "red", "brown"], ["orange", "red", "brown", "mustard"],
                ["red", "orange", "mustard", "brown"], ["mustard", "red", "orange", "brown"]];

  /** The design for a seed (an album or tape name): its name, markup and inks. */
  function design(seed) {
    const r = rng(String(seed || ""));
    const name = NAMES[Math.floor(r() * NAMES.length)];
    const [c, a, e, d] = pick(r, RUNS).map((k) => RETRO[k]);
    return { name, markup: DESIGNS[name](r), inks: { a, c, d, e, b: RETRO.tan } };
  }

  // Each ink printed from its own plate, a hair out of register.
  const PLATE = { c: "translate(0.35 0.22)", e: "translate(-0.25 0.3)", d: "translate(0.15 -0.2)" };

  /** Draw a seed's design into the label's print group. Fills are attributes,
   *  so a copy of the SVG (the lock-screen drawing) keeps them. */
  function draw(group, seed) {
    const { name, markup, inks } = design(seed);
    group.innerHTML = markup;
    for (const ink of ["a", "b", "c", "d", "e"]) {
      group.querySelectorAll(`.ink-${ink}`).forEach((el) => {
        el.setAttribute(el.getAttribute("fill") === "none" ? "stroke" : "fill", inks[ink]);
        if (PLATE[ink]) el.setAttribute("transform", PLATE[ink]);
      });
    }
    return name;
  }

  /** How the title was written on this tape: a slight tilt and where the pen started. */
  function hand(seed) {
    const r = rng(`hand:${seed}`);
    return { tilt: between(r, -1.3, 0.5), shift: between(r, -0.6, 2.4) };
  }
  window.LabelPrint = { draw, design, hand, NAMES };
})();
