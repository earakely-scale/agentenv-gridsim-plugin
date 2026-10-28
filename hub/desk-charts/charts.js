/** The dataset card's desk charts from desk.json (scripts/hub_desk.py): hindsight capture across versions, and each
 * version's capture task by task, each at the card's width and in a phone layout. Bare SVG on a transparent page in
 * the theme on <html>; hub_desk.py captures every [data-figure] at 2x and takes chartsSvg(), each chart as a
 * standalone SVG with its styles and font inlined, in light and dark. */
const NS = "http://www.w3.org/2000/svg";
const ORDER = ["sol", "luna", "qwen"];
const COL = { sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)" };
const REFS = [
  { key: "anchor", color: "var(--c-anchor)", dash: "6 4", w: 1.5, cap: "butt", label: "Anchor", short: "Anchor" },
  { key: "operator_replay", color: "var(--c-op)", dash: "0.1 4.4", w: 2.4, cap: "round", label: "The operator's bids, replayed", short: "Operator's bids" },
];
const WORD = { 2: "two", 3: "three", 4: "four", 5: "five" };

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const minus = (s) => s.replace(/-/g, "−");
const num = (x, n = 3) => {
  const [i, f = ""] = Math.abs(x).toString().split(".");
  if (/e/.test(i)) return minus(x.toFixed(n));
  const v = BigInt(i + f.slice(0, n).padEnd(n, "0")) + (f[n] >= "5" ? 1n : 0n);
  const s = v.toString().padStart(n + 1, "0");
  return minus(`${x < 0 && v ? "-" : ""}${s.slice(0, s.length - n)}${n ? `.${s.slice(-n)}` : ""}`);
};
const sgn = (x, n = 3) => (x > 0 ? `+${num(x, n)}` : num(x, n));
const f1 = (v) => Math.round(v * 10) / 10;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const T = (x, y, s, cls, a = "start") => `<text x="${f1(x)}" y="${f1(y)}" class="${cls}"${a === "start" ? "" : ` text-anchor="${a}"`}>${esc(s)}</text>`;
const L_ = (x1, y1, x2, y2, cls) => `<line x1="${f1(x1)}" y1="${f1(y1)}" x2="${f1(x2)}" y2="${f1(y2)}" class="${cls}"/>`;
const refLine = (r, x1, x2, y) => `<line class="ref" x1="${f1(x1)}" y1="${f1(y)}" x2="${f1(x2)}" y2="${f1(y)}" stroke="${r.color}" stroke-width="${r.w}" stroke-dasharray="${r.dash}" stroke-linecap="${r.cap}"/>`;
const steps = (lo, hi, step) => { const out = []; for (let v = Math.ceil(lo / step - 1e-9) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6)); return out; };

const ruler = document.getElementById("ruler");
const measure = (s, cls) => {
  const t = document.createElementNS(NS, "text");
  t.setAttribute("class", cls);
  t.textContent = s;
  ruler.append(t);
  const w = t.getComputedTextLength();
  t.remove();
  return w;
};
const wrap = (s, cls, w) => s.split(" ").reduce((ls, word) => {
  const t = ls.length ? `${ls.at(-1)} ${word}` : word;
  if (ls.length && measure(t, cls) <= w) ls[ls.length - 1] = t;
  else ls.push(word);
  return ls;
}, []);
const svg = (w, h, body, label) => `<svg class="chart" viewBox="0 0 ${w} ${Math.ceil(h)}" width="${w}" height="${Math.ceil(h)}" role="img" aria-label="${esc(label)}">${body}</svg>`;
const ref = (v, key) => v.references.find((r) => r.key === key);
const model = (v, key) => v.models.find((m) => m.key === key);
const pair = (v, a, b) => {
  const p = v.paired.find((x) => x.a === a && x.b === b && x.C);
  if (p) return p.C;
  const q = v.paired.find((x) => x.a === b && x.b === a && x.C);
  return q && { mean: -q.C.mean, ci: [-q.C.ci[1], -q.C.ci[0]] };
};
const unitLines = (v) => (v.days_per_task > 1 ? [`${v.n_tasks} ${WORD[v.days_per_task] || v.days_per_task}-day windows`, `over ${v.n_days} ${v.block}s`] : [`${v.n_tasks} battery-days`]);

function legend(groups, width) {
  let s = "", y = 14;
  for (const items of groups) {
    let x = 0;
    for (const it of items) {
      const cls = `t-leg${it.bold ? " b" : ""}`, sw = it.dot ? 11 : 26, w = sw + 7 + measure(it.label, cls);
      if (x > 0 && x + w > width) (x = 0), (y += 22);
      s += it.dot ? `<circle cx="${x + 5.5}" cy="${y - 4.6}" r="5.5" fill="${it.color}"/>` : refLine(it, x, x + sw, y - 4.6);
      s += T(x + sw + 7, y, it.label, cls);
      x += w + 20;
    }
    y += 22;
  }
  return [s, y - 22];
}

function across(D, W, narrow) {
  const V = D.versions, L = narrow ? 32 : 38, R = W - 2, cw = (R - L) / V.length, off = cw * (narrow ? 0.22 : 0.2);
  const names = Object.fromEntries(V.flatMap((v) => v.models.map((m) => [m.key, m.name])));
  const keys = ORDER.filter((k) => names[k]);
  let [s, y] = legend([keys.map((k) => ({ dot: true, color: COL[k], label: names[k], bold: true })), REFS], W);
  y += 30;
  const head = "Hindsight capture C", sub = "mean and 95% CI · idle is 0, the hindsight optimum 1", hx = measure(head, "t-axis") + 8;
  s += T(0, y, head, "t-axis");
  if (hx + measure(sub, "t-axis-s") <= W) s += T(hx, y, sub, "t-axis-s");
  else s += T(0, (y += 18), sub, "t-axis-s");
  const top = y + 18, PH = narrow ? 260 : 236;
  const vals = V.flatMap((v) => [...v.models.flatMap((m) => m.C.ci), ...REFS.map((r) => ref(v, r.key)?.C.mean).filter((x) => x != null)]);
  const lo = Math.min(-0.1, Math.floor((Math.min(...vals) - 0.03) * 10) / 10), hi = Math.max(0.6, Math.ceil((Math.max(...vals) + 0.035) * 20) / 20);
  const yv = lin(lo, hi, top + PH, top), bottom = top + PH;
  for (const t of steps(lo, hi, 0.2)) {
    s += L_(L, yv(t), R, yv(t), t ? "grid" : "zero") + T(L - 8, yv(t) + 4.3, t ? num(t, 1) : "0", "t-tick", "end");
  }
  let labels = "", ann = "", marks = "", maxY = bottom;
  V.forEach((v, i) => {
    const cx = L + cw * (i + 0.5), xs = Object.fromEntries(keys.map((k, j) => [k, cx + (j - (keys.length - 1) / 2) * off]));
    for (const r of REFS) {
      const x = ref(v, r.key);
      if (x) s += refLine(r, cx - cw * 0.39, cx + cw * 0.39, yv(x.C.mean));
    }
    for (const k of keys) {
      const m = model(v, k);
      if (!m) continue;
      marks += `<line x1="${f1(xs[k])}" x2="${f1(xs[k])}" y1="${f1(yv(m.C.ci[0]))}" y2="${f1(yv(m.C.ci[1]))}" stroke="${COL[k]}" stroke-width="2.6" stroke-linecap="round"/>`;
      marks += `<circle cx="${f1(xs[k])}" cy="${f1(yv(m.C.mean))}" r="5.6" fill="${COL[k]}" stroke="var(--halo)" stroke-width="2"/>`;
    }
    let ly = bottom + 24;
    labels += T(cx, ly, v.version, "t-ver", "middle");
    if (!narrow) {
      for (const line of wrap(v.name, "t-name", cw - 10)) labels += T(cx, (ly += 17), line, "t-name", "middle");
      ly += 2;
      for (const line of unitLines(v).flatMap((x) => wrap(x, "t-unit", cw + 10))) labels += T(cx, (ly += 16), line, "t-unit", "middle");
    }
    maxY = Math.max(maxY, ly);
    const p = pair(v, "sol", "luna"), a = model(v, "sol"), b = model(v, "luna");
    if (p && a && b && (p.ci[0] > 0 || p.ci[1] < 0)) {
      const t1 = `Sol − Luna ${sgn(p.mean, 2)}`, t2 = `95% CI [${num(p.ci[0], 2)}, ${num(p.ci[1], 2)}]`;
      const tw = Math.max(measure(t1, "t-ann"), measure(t2, "t-ann-s")), ya = yv(a.C.mean), yb = yv(b.C.mean), up = Math.min(ya, yb);
      const bx = narrow ? cx + cw * 0.42 : Math.min(cx + cw * 0.44, W - 9 - tw);
      ann += `<path class="lead" stroke-dasharray="2 2.5" d="M${f1(xs.sol + 8)},${f1(ya)}H${f1(bx - 1)}M${f1(xs.luna + 8)},${f1(yb)}H${f1(bx - 1)}"/>`;
      ann += `<path class="brk" d="M${f1(bx - 4)},${f1(ya)}H${f1(bx)}V${f1(yb)}H${f1(bx - 4)}"/>`;
      ann += narrow ? T(R, up - 27, t1, "t-ann", "end") + T(R, up - 10, t2, "t-ann-s", "end")
        : T(bx + 7, up + 4, t1, "t-ann") + T(bx + 7, up + 21, t2, "t-ann-s");
    }
  });
  if (narrow) {
    maxY += 12;
    const vx = Math.max(...V.map((v) => measure(v.version, "t-kv"))) + 8;
    for (const v of V) {
      wrap(`${v.name} · ${unitLines(v).join(" ")}`, "t-kd", W - vx).forEach((line, i) => {
        maxY += i ? 17 : 21;
        labels += (i ? "" : T(0, maxY, v.version, "t-kv")) + T(vx, maxY, line, "t-kd");
      });
    }
  }
  s += marks + ann + labels;
  return svg(W, maxY + 8, s, "Hindsight capture by model and version");
}

function place(ys, d) {
  const idx = ys.map((_, i) => i).sort((a, b) => ys[a] - ys[b]), xs = new Array(ys.length), done = [];
  const free = (x, y) => done.every((j) => (xs[j] - x) ** 2 + (ys[j] - y) ** 2 >= d * d - 1e-6);
  for (const i of idx) {
    const y = ys[i], c = [0];
    for (const j of done) {
      const dy = Math.abs(ys[j] - y);
      if (dy < d) {
        const dx = Math.sqrt(d * d - dy * dy) + 1e-6;
        c.push(xs[j] + dx, xs[j] - dx);
      }
    }
    c.sort((a, b) => Math.abs(a) - Math.abs(b) || b - a);
    let x = c.find((x) => free(x, y));
    for (let k = 1; x === undefined; k++) x = [k * 0.5, -k * 0.5].find((x) => free(x, y));
    xs[i] = x;
    done.push(i);
  }
  return xs;
}

function swarm(ys, r, maxHalf) {
  let d = 2 * r + 0.9, xs = place(ys, d);
  for (let k = 0; k < 8; k++) {
    const half = Math.max(0, ...xs.map(Math.abs)) + r;
    if (half <= maxHalf) break;
    d *= Math.max(0.5, (maxHalf - r) / (half - r));
    xs = place(ys, d);
  }
  return xs;
}

function dodge(items, lo, hi) {
  const out = [...items].sort((a, b) => a.y - b.y).map((x) => ({ ...x, ly: x.y }));
  const gap = (a, b) => (a.h + b.h) / 2 + 2;
  for (let i = 1; i < out.length; i++) out[i].ly = Math.max(out[i].ly, out[i - 1].ly + gap(out[i - 1], out[i]));
  for (let i = out.length - 1; i >= 0; i--) {
    if (i === out.length - 1) out[i].ly = Math.min(out[i].ly, hi);
    else out[i].ly = Math.min(out[i].ly, out[i + 1].ly - gap(out[i], out[i + 1]));
    out[i].ly = Math.max(out[i].ly, lo);
  }
  return out;
}

function key(v, r, W, narrow) {
  const head = "Hindsight capture C", each = v.days_per_task > 1 ? `one ${WORD[v.days_per_task] || v.days_per_task}-day window` : "one battery-day";
  let s = T(0, 17, head, "t-axis"), x = measure(head, "t-axis") + 18, y = 17;
  if (narrow) (s += T(x - 10, 17, "· idle is 0, the hindsight optimum 1", "t-axis-s")), (x = 0), (y = 40);
  s += `<circle cx="${f1(x + r)}" cy="${f1(y - 4.6)}" r="${r}" class="key"/>` + T(x + 2 * r + 7, y, each, "t-axis-s");
  x += 2 * r + 7 + measure(each, "t-axis-s") + 18;
  s += `<line x1="${f1(x + 6)}" x2="${f1(x + 6)}" y1="${f1(y - 15)}" y2="${f1(y + 6)}" class="key-ci"/><circle cx="${f1(x + 6)}" cy="${f1(y - 4.6)}" r="6" class="key key-mean"/>`;
  s += T(x + 19, y, "mean, 95% CI", "t-axis-s");
  if (!narrow) return [s, y];
  x = 0;
  y += 23;
  for (const it of REFS) {
    s += refLine(it, x, x + 26, y - 4.6) + T(x + 33, y, it.short, "t-axis-s");
    x += 33 + measure(it.short, "t-axis-s") + 20;
  }
  return [s, y];
}

function tasks(v, D, W, narrow) {
  const [lo, hi] = D.charts.tasks_axis, L = narrow ? 34 : 38, PH = narrow ? 300 : 292, r = narrow ? 3.2 : 3.5, lane = 18;
  const G = narrow ? 4 : Math.ceil(Math.max(...REFS.map((x) => measure(x.short, "t-ref")), measure("Idle", "t-ref"))) + 22, R = W - G;
  let [s, ky] = key(v, r, W, narrow), marks = "", notes = "";
  const top = ky + 29, ms = ORDER.map((k) => model(v, k)).filter(Boolean), cw = (R - L) / ms.length, yv = lin(lo, hi, top + PH, top), bottom = top + PH;
  const pts = (k) => v.tasks.map((t) => ({ c: t.C[k], named: t.named })).filter((p) => p.c != null);
  for (const t of steps(lo, hi, 0.2)) {
    s += L_(L, yv(t), R, yv(t), t === 0 ? "zero" : t === hi ? "top" : "grid") + T(L - 8, yv(t) + 4.5, t ? num(t, 1) : "0", "t-tick", "end");
  }
  const gut = [{ y: yv(hi), text: "Hindsight optimum" }, { y: yv(0), text: "Idle" }];
  for (const x of REFS) {
    const rf = ref(v, x.key);
    if (!rf) continue;
    s += refLine(x, L, narrow ? R : R + 4, yv(rf.C.mean));
    gut.push({ y: yv(rf.C.mean), text: x.short });
  }
  const lines = gut.map((g) => ({ ...g, lines: wrap(g.text, "t-ref", G - 14) })).map((g) => ({ ...g, h: g.lines.length * 15, y: g.y + (g.lines.length - 1) * 7.5 }));
  for (const g of narrow ? [] : dodge(lines, top, bottom + lane)) {
    const y0 = g.ly - (g.h - 15) / 2, at = g.y - (g.h - 15) / 2;
    if (Math.abs(y0 - at) > 0.5) s += `<path class="lead" d="M${f1(R + 4)},${f1(at)}L${f1(R + 9)},${f1(y0)}"/>`;
    g.lines.forEach((t, i) => (s += T(R + 12, y0 + 4.6 + i * 15, t, "t-ref")));
  }
  ms.forEach((m, j) => {
    const cx = L + cw * (j + 0.5), sx = cx - (narrow ? 8 : 10), edge = cx + cw / 2 - (narrow ? 9 : 12);
    const all = pts(m.key), inside = all.filter((p) => p.c >= lo && p.c <= hi), out = all.filter((p) => p.c < lo);
    const xs = swarm(inside.map((p) => yv(p.c)), r, edge - 14 - sx);
    const half = Math.max(0, ...xs.map(Math.abs)) + r, gx = Math.min(edge, sx + half + 13);
    inside.forEach((p, i) => {
      marks += p.named
        ? `<circle cx="${f1(sx + xs[i])}" cy="${f1(yv(p.c))}" r="${r + 0.4}" fill="${COL[m.key]}" stroke="var(--ink)" stroke-width="1.6"/>`
        : `<circle class="dot" cx="${f1(sx + xs[i])}" cy="${f1(yv(p.c))}" r="${r}" fill="${COL[m.key]}" stroke="var(--halo)" stroke-width="0.8"/>`;
    });
    out.sort((a, b) => a.c - b.c).forEach((p, i) => {
      const x = sx - 4 + i * 40, yy = bottom + 6;
      marks += `<path d="M${f1(x - 4.5)},${f1(yy)}H${f1(x + 4.5)}L${f1(x)},${f1(yy + 7)}Z" fill="${COL[m.key]}"/>`;
      notes += T(x + 8, yy + 7.5, num(p.c, 2), "t-out");
    });
    marks += `<line x1="${f1(gx)}" x2="${f1(gx)}" y1="${f1(yv(m.C.ci[0]))}" y2="${f1(yv(m.C.ci[1]))}" stroke="${COL[m.key]}" stroke-width="2.8" stroke-linecap="round"/>`;
    marks += `<circle cx="${f1(gx)}" cy="${f1(yv(m.C.mean))}" r="6" fill="${COL[m.key]}" stroke="var(--halo)" stroke-width="2"/>`;
    let ly = bottom + lane + 22;
    for (const line of wrap(m.name, "t-col", cw - 6)) (s += T(cx, ly, line, "t-col", "middle")), (ly += 17);
    const fp = inside.map((p, i) => ({ ...p, x: sx + xs[i], y: yv(p.c) })).filter((p) => p.named);
    if (j === 0 && fp.length) {
      const ytop = Math.min(...fp.map((p) => p.y)), xr = Math.max(...fp.map((p) => p.x)) + r + 8, t = fp[0].named;
      const day = v.tasks.find((x) => x.named).date, by = Math.max(ytop + 7, yv(hi) + 18);
      notes += T(xr + 2, by, cap(t), "t-ann") + T(xr + 2, by + 17, dayLabel(v, day), "t-ann-s");
    }
  });
  s += marks + notes;
  return svg(W, bottom + lane + 26 + 17 * 2, s, `Hindsight capture task by task, ${v.version}`);
}

const cap = (s) => s[0].toUpperCase() + s.slice(1);
const fmtDay = (iso, o) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
function dayLabel(v, iso) {
  if (v.days_per_task === 1) return fmtDay(iso, { day: "numeric", month: "short", year: "numeric" });
  const b = new Date(`${iso}T12:00:00Z`);
  b.setUTCDate(b.getUTCDate() + v.days_per_task - 1);
  return `${fmtDay(iso, { day: "numeric" })}–${fmtDay(b.toISOString().slice(0, 10), { day: "numeric", month: "short", year: "numeric" })}`;
}

const PAINT = { fill: "", "fill-opacity": "1", stroke: "none", "stroke-width": "", "stroke-opacity": "1", "stroke-dasharray": "none", "stroke-linecap": "butt", "stroke-linejoin": "miter", "paint-order": "normal", opacity: "1" };
const FONT = { "font-size": "", "font-weight": "400" };

async function woff2() {
  const u = new Uint8Array(await (await fetch("./fonts/plex-sans.woff2")).arrayBuffer());
  let s = "";
  for (let i = 0; i < u.length; i += 0x8000) s += String.fromCharCode(...u.subarray(i, i + 0x8000));
  return btoa(s);
}

function standalone(el, font) {
  const out = el.cloneNode(true), src = el.querySelectorAll("*"), dst = out.querySelectorAll("*");
  src.forEach((e, i) => {
    const cs = getComputedStyle(e), d = dst[i];
    for (const [p, initial] of Object.entries(e.tagName === "text" ? { ...PAINT, ...FONT } : PAINT)) {
      const v = cs.getPropertyValue(p);
      if (v && v !== initial) d.setAttribute(p, v);
      else d.removeAttribute(p);
    }
    d.removeAttribute("class");
  });
  out.removeAttribute("class");
  out.setAttribute("xmlns", NS);
  out.insertAdjacentHTML("afterbegin", `<style>@font-face{font-family:"IBM Plex Sans";font-weight:100 700;src:url(data:font/woff2;base64,${font}) format("woff2")}text{font-family:"IBM Plex Sans",sans-serif;font-variant-numeric:tabular-nums}</style>`);
  return new XMLSerializer().serializeToString(out);
}

async function main() {
  const D = await (await fetch("./desk.json")).json();
  await document.fonts.load('600 13px "IBM Plex Sans"');
  await document.fonts.ready;
  const sizes = [["", D.charts.width, false], ["-phone", D.charts.phone.width, true]];
  const figs = sizes.flatMap(([sfx, W, narrow]) => [[`desk-across${sfx}`, across(D, W, narrow)], ...D.versions.map((v) => [`desk-${v.version}-tasks${sfx}`, tasks(v, D, W, narrow)])]);
  document.getElementById("figs").innerHTML = figs.map(([id, body]) => `<section class="fig" data-figure="${id}">${body}</section>`).join("");
  const font = await woff2();
  window.chartsSvg = () => Object.fromEntries([...document.querySelectorAll("[data-figure]")].map((e) => [e.dataset.figure, standalone(e.querySelector("svg"), font)]));
  window.chartsReady = true;
}

main();
