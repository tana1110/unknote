const fs = require("fs");

const CHARCOAL = "#222222";
const IVORY = "#EAE9DE";

// deterministic pseudo-random, so the "hand-drawn" wobble is reproducible
const lcg = (seed) => () => (seed = (seed * 1664525 + 1013904223) % 4294967296) / 4294967296;

/* Catmull-Rom through the sampled points -> one smooth cubic path.
   The whole mark is a single unbroken stroke: a pen that never lifts. */
function smooth(pts) {
  let d = `M ${pts[0][0].toFixed(2)} ${pts[0][1].toFixed(2)}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i], p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(2)} ${c1[1].toFixed(2)}, ${c2[0].toFixed(2)} ${c2[1].toFixed(2)}, ${p2[0].toFixed(2)} ${p2[1].toFixed(2)}`;
  }
  return d;
}

/* THE TANGLE — a stack of overlapping ellipses, each with its own centre,
   size and tilt. The pen never lifts, so the hops between loops become the
   crossing strokes that make it read as a real scribble rather than a
   symmetrical spirograph. */
function scribble({ cx, cy, R, loops, rnd, steps = 46, rMin = 0.5, drift = 0.55 }) {
  const pts = [];
  for (let i = 0; i < loops; i++) {
    // rMin near 1 keeps every loop large and open (legible when small);
    // a low rMin mixes big and tiny loops into a denser, inkier knot
    const rx = R * (rMin + (1 - rMin) * rnd());
    const ry = R * (rMin + (1 - rMin) * rnd());
    const th = rnd() * Math.PI * 2;              // tilt
    const ox = cx + (rnd() - .5) * R * drift;    // drift
    const oy = cy + (rnd() - .5) * R * drift;
    const start = rnd() * Math.PI * 2;
    const dir = rnd() > .5 ? 1 : -1;             // some loops wind the other way
    for (let j = 0; j <= steps; j++) {
      const a = start + dir * (j / steps) * Math.PI * 2;
      const x = rx * Math.cos(a), y = ry * Math.sin(a);
      pts.push([
        ox + x * Math.cos(th) - y * Math.sin(th),
        oy + x * Math.sin(th) + y * Math.cos(th),
      ]);
    }
  }
  return pts;
}

/* THE RELEASE — the line finds its way out to the right and settles into one
   calm wave. Agitated as it leaves the knot, still by the time it arrives. */
function wave(from, to, amp, steps) {
  const pts = [];
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    // x runs steadily; y holds level and only drops late, so the line travels
    // straight out of the knot and sweeps underneath the circle at the end
    // instead of sagging the whole way across
    const x = from[0] + (to[0] - from[0]) * (t * t * (3 - 2 * t));
    const y = from[1] + (to[1] - from[1]) * t ** 1.7
            + Math.sin(t * Math.PI * 2.4) * amp * (1 - t) ** 0.9;
    pts.push([x, y]);
  }
  return pts;
}

/* THE CLARITY — one clean, quiet circle. Deliberately NOT sketchy: the knot
   is hand-drawn chaos, and this is what calm looks like by contrast.
   The wave arrives at the bottom travelling right, exactly along the circle's
   tangent, so the join disappears and it reads as one continuous stroke. */
function circle({ cx, cy, r, a0, sweep, steps }) {
  const pts = [];
  for (let i = 1; i <= steps; i++) {
    const a = a0 + (i / steps) * sweep;
    pts.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]);
  }
  return pts;
}

function buildLockup() {
  const rnd = lcg(11);
  const TX = 98, TY = 100, TR = 46;

  const T = scribble({ cx: TX, cy: TY, R: TR, loops: 13, rnd });
  // pull the pen out to the right edge of the knot before it escapes
  T.push([TX + TR * 0.95, TY + 6]);

  const CX = 402, CY = 100, R = 62;
  const a0 = Math.PI * 0.72;                     // the circle's lower-left shoulder
  const entry = [CX + R * Math.cos(a0), CY + R * Math.sin(a0)];

  const W = wave(T[T.length - 1], entry, 19, 110);
  // sweep backwards: at the entry the tangent points right, matching the wave
  const C = circle({ cx: CX, cy: CY, r: R, a0, sweep: -Math.PI * 2.04, steps: 240 });

  return smooth([...T, ...W, ...C]);
}

const svg = (w, h, body, bg) =>
  `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img">
${bg ? `  <rect width="${w}" height="${h}" fill="${bg}"/>\n` : ""}${body}
</svg>`;

/* pathLength="1" normalises the stroke's length to 1, so the mark can be drawn
   on with a stroke-dashoffset from 1 -> 0 without anyone measuring the path.
   It has no effect on how the static mark renders. */
const stroke = (d, w, color = CHARCOAL) =>
  `  <path d="${d}" pathLength="1" fill="none" stroke="${color}" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"/>`;

/* THE ICON — a compact retelling of the wide mark, not a different idea.
   One MESSY scribble on the left, one CALM circle on the right, one line
   between. A single smooth loop said nothing; the whole meaning lives in the
   contrast between chaos and clarity, so the icon has to carry it too.
   The knot uses few enough loops to stay legible at favicon size. */
function buildIcon({ tx, ty, tr, loops, cx, cy, R, seed }) {
  const rnd = lcg(seed);
  // few, large, open loops — a dense knot just fills in to a black dot at 20px
  // few, large, OPEN loops. Dense settings that look great at hero size flood
  // into a solid dot at 20px; equal-sized loops stack up and read as glasses.
  const T = scribble({ cx: tx, cy: ty, R: tr, loops, rnd, steps: 40, rMin: 0.35, drift: 0.6 });
  T.push([tx + tr * 0.9, ty + tr * 0.2]);          // pull the pen out to the right

  const a0 = Math.PI * 0.72;                       // the circle's lower-left shoulder
  const entry = [cx + R * Math.cos(a0), cy + R * Math.sin(a0)];
  const W = wave(T[T.length - 1], entry, 2.2, 26);
  const C = circle({ cx, cy, r: R, a0, sweep: -Math.PI * 2.02, steps: 160 });
  return smooth([...T, ...W, ...C]);
}

const OUT = process.argv[2] || ".";
const d = buildLockup();
const m = buildIcon({ tx: 16, ty: 33, tr: 12, loops: 5, cx: 45, cy: 31, R: 13, seed: 5 });

const files = {
  // the wide mark: chaos -> one calm circle. For the landing hero.
  "logo-wide.svg":        svg(560, 200, stroke(d, 2.4), null),
  "logo-wide-ivory.svg":  svg(560, 200, stroke(d, 2.4, IVORY), null),
  // the icon: for the app icon, nav, buttons and empty states.
  "logo-mark.svg":        svg(64, 64, stroke(m, 1.8), null),
  "logo-mark-ivory.svg":  svg(64, 64, stroke(m, 1.8, IVORY), null),

  /* THE FAVICON — a different problem to the in-app mark. A transparent
     charcoal mark vanishes against a browser's dark tab bar, and at 16px a
     hairline stroke disappears anyway. So it gets its own ivory tile (the
     other colour from the palette) and a heavy stroke: it then reads on a
     dark tab bar and a light one, which no transparent version can do. */
  "favicon.svg": svg(64, 64,
    `  <rect width="64" height="64" rx="14" fill="${IVORY}"/>\n` +
    `  <g transform="translate(32 32) scale(0.82) translate(-31 -30.5)">\n` +
    `  ${stroke(m, 4.2)}\n  </g>`, null),
  // preview-only, with the ivory ground painted in
  "logo-preview.svg":     svg(560, 200, stroke(d, 2.4), IVORY),
};
for (const [name, body] of Object.entries(files)) {
  fs.writeFileSync(`${OUT}/${name}`, body);
  console.log("wrote " + name);
}
