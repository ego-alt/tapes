/* The printed design on the cassette's paper label: the classic four broad
 * bands, or one of seven bold, full-bleed geometric designs of the kind 70s
 * and 80s tapes were printed with (the window simply sits on top).
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
  const X0 = 15.5, X1 = 314.5, Y0 = 58, Y1 = 136, W = X1 - X0, H = Y1 - Y0;
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

  const RAINBOW = ["c", "a", "e", "d"];
  const inkAt = (i) => RAINBOW[((i % 4) + 4) % 4];
  const circle = (cx, cy, rad, k) => `<circle class="ink-${k}" cx="${f(cx)}" cy="${f(cy)}" r="${f(rad)}"/>`;
  const DESIGNS = {
    // The classic: four broad bands with a hairline of cream between them,
    // always red, orange, mustard, brown (see CLASSIC_RUN).
    classic() {
      const gap = 1.2, h = (H - gap * 3) / 4;
      return RAINBOW.map((k, i) => rect(X0, Y0 + i * (h + gap), W, h, k)).join("");
    },
    // Wide diagonal stripes straight across, all four inks.
    diagonal(r) {
      const w = between(r, 14, 22), gap = r() > 0.5 ? 0 : between(r, 3, 6), lean = (r() > 0.5 ? 1 : -1) * H * between(r, 0.7, 1.1), out = [];
      for (let x = X0 - Math.abs(lean) - w, i = 0; x < X1 + Math.abs(lean); x += w + gap, i++) {
        out.push(poly([[x, Y1], [x + w, Y1], [x + w + lean, Y0], [x + lean, Y0]], inkAt(i)));
      }
      return out.join("");
    },
    // Eight narrower rainbow bands, edge to edge.
    rainbow() {
      const h = H / 8;
      return Array.from({ length: 8 }, (_, i) => rect(X0, Y0 + i * h, W, h + 0.2, inkAt(i))).join("");
    },
    // Rays from the middle of the bottom edge, filling the label.
    sunburst(r) {
      const rays = pick(r, [16, 20, 24]), oy = Y1 + between(r, 0, 20), R = 420, out = [rect(X0, Y0, W, H, "c")];
      for (let i = 0; i < rays; i++) {
        const a0 = Math.PI + Math.PI * i / rays, a1 = Math.PI + Math.PI * (i + 1) / rays;
        if (i % 2) out.push(poly([[CX, oy], [CX + R * Math.cos(a0), oy + R * Math.sin(a0)], [CX + R * Math.cos(a1), oy + R * Math.sin(a1)]], inkAt(1 + ((i - 1) / 2) % 3)));
      }
      return out.join("");
    },
    // Fat waves, band on band.
    waves(r) {
      const n = pick(r, [4, 5]), len = between(r, 70, 110), amp = between(r, 5, 9), band = H / (n - 0.5), out = [rect(X0, Y0, W, H, "d")];
      for (let i = 0; i < n; i++) {
        const y = Y0 + band * i;
        let d = `M${X0 - len} ${f(y)}`;
        for (let x = X0 - len; x < X1 + len; x += len) d += ` q${f(len / 4)} ${-amp} ${f(len / 2)} 0 t${f(len / 2)} 0`;
        out.push(path(`${d} V${Y1 + 20} H${X0 - len} Z`, inkAt(i)));
      }
      return out.join("");
    },
    // The label split into big diagonal fields of colour.
    split(r) {
      const lean = H * between(r, 0.5, 1) * (r() > 0.5 ? 1 : -1), cuts = [X0 + W * between(r, 0.15, 0.3), CX + W * between(r, -0.08, 0.08), X1 - W * between(r, 0.15, 0.3)];
      const xs = [X0 - 200, ...cuts, X1 + 200];
      return xs.slice(0, -1).map((x, i) => poly([[x, Y1], [xs[i + 1], Y1], [xs[i + 1] + lean, Y0], [x + lean, Y0]], inkAt(i))).join("");
    },
    // Bauhaus: big squares, each with a quarter circle in one corner.
    bauhaus(r) {
      const rows = 2, sz = H / rows, out = [];
      for (let x = X0, i = 0; x < X1; x += sz, i++) {
        for (let j = 0; j < rows; j++) {
          const y = Y0 + j * sz, corner = Math.floor(r() * 4), [cx, cy] = [[x, y], [x + sz, y], [x + sz, y + sz], [x, y + sz]][corner];
          out.push(rect(x, y, sz + 0.2, sz + 0.2, inkAt(i + j)));
          out.push(`<clipPath id="lp-q${i}-${j}"><rect x="${f(x)}" y="${f(y)}" width="${f(sz)}" height="${f(sz)}"/></clipPath>`);
          out.push(`<g clip-path="url(#lp-q${i}-${j})">${circle(cx, cy, sz, inkAt(i + j + 2))}</g>`);
        }
      }
      return out.join("");
    },
    // A racing swoosh: fat bands that run flat, then sweep up at the end.
    swoosh(r) {
      const n = 4, band = H / (n + 0.5), turn = X1 - between(r, 70, 100), out = [rect(X0, Y0, W, H, "b")];
      for (let i = 0; i < n; i++) {
        const y = Y0 + band * (i + 0.75), rise = 120 + i * band;
        out.push(path(`M${X0 - 5} ${f(y)} H${f(turn)} Q${f(turn + 30)} ${f(y)} ${X1 + 60} ${f(y - rise)}`, inkAt(i), band));
      }
      return out.join("");
    },
  };
  const NAMES = Object.keys(DESIGNS);

  // The palette every tape is printed in.
  const RETRO = { red: "#c43c2e", orange: "#e0702a", mustard: "#e6b23a", brown: "#6d3e24", tan: "#b08d68" };
  // The inks in rainbow order (c, a, e, d): a few classic runs to choose from.
  const CLASSIC_RUN = ["red", "orange", "mustard", "brown"];
  const RUNS = [["mustard", "orange", "red", "brown"], ["orange", "red", "brown", "mustard"],
                CLASSIC_RUN, ["mustard", "red", "orange", "brown"]];

  /** The design for a seed (an album or tape name): its name, markup and inks. */
  function design(seed) {
    const r = rng(String(seed || ""));
    const name = NAMES[Math.floor(r() * NAMES.length)];
    const run = pick(r, RUNS);
    const [c, a, e, d] = (name === "classic" ? CLASSIC_RUN : run).map((k) => RETRO[k]);
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
