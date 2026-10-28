/** The dataset card's desk charts from desk.json (scripts/hub_desk.py): hindsight capture across the ladder's versions
 * (a check such as v5 is not a step on it), and each one's capture day by day (front by front in v4), each at the card's
 * width and in a phone layout. Bare SVG on a transparent page in the theme on <html>; hub_desk.py captures every
 * [data-figure] at 2x and takes chartsSvg(), each chart as a standalone SVG with its styles and font inlined, in light
 * and dark. */
const NS = "http://www.w3.org/2000/svg";
const ORDER = ["sol", "luna", "qwen"];
const COL = { sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)" };
const OP = { key: "operator_replay", label: "Real operator (bids replayed)", short: "Real operator" };
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
const pts = (x, sign = false) => {
  const k = Math.round(parseFloat(num(x, 3).replace("−", "-")) * 1000), a = Math.abs(k);
  return `${k < 0 ? "−" : sign && k > 0 ? "+" : ""}${Math.floor(a / 10)}.${a % 10}`;
};
const pct = (x) => `${pts(x)}%`;
const f1 = (v) => Math.round(v * 10) / 10;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const T = (x, y, s, cls, a = "start") => `<text x="${f1(x)}" y="${f1(y)}" class="${cls}"${a === "start" ? "" : ` text-anchor="${a}"`}>${esc(s)}</text>`;
const L_ = (x1, y1, x2, y2, cls) => `<line x1="${f1(x1)}" y1="${f1(y1)}" x2="${f1(x2)}" y2="${f1(y2)}" class="${cls}"/>`;
const path = (p) => p.map(([x, y], i) => `${i ? "L" : "M"}${f1(x)},${f1(y)}`).join("");

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
const fmtDay = (iso, o) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
const plusDays = (iso, n) => { const d = new Date(`${iso}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const span = (v, iso, year) => {
  const o = { day: "numeric", month: "short", ...(year ? { year: "numeric" } : {}) };
  if (v.days_per_task === 1) return fmtDay(iso, o);
  const b = plusDays(iso, v.days_per_task - 1);
  return `${fmtDay(iso, { day: "numeric", ...(iso.slice(5, 7) === b.slice(5, 7) ? {} : { month: "short" }) })}–${fmtDay(b, o)}`;
};
const cap = (s) => s[0].toUpperCase() + s.slice(1);

function header(head, sub, W, y0 = 17) {
  const hx = measure(head, "t-head") + 8;
  if (hx + measure(sub, "t-head-s") <= W) return [T(0, y0, head, "t-head") + T(hx, y0, sub, "t-head-s"), y0];
  return [T(0, y0, head, "t-head") + T(0, y0 + 19, sub, "t-head-s"), y0 + 19];
}

function dodge(items, lo, hi, gap) {
  const cl = [...items].sort((a, b) => a.y - b.y).map((it) => ({ items: [it], top: it.y - it.h / 2, h: it.h }));
  const fit = (c) => {
    const mid = c.items.reduce((s, x) => s + x.y, 0) / c.items.length;
    c.top = Math.min(Math.max(mid - c.h / 2, lo), hi - c.h);
  };
  for (let i = 1; i < cl.length;) {
    if (cl[i].top < cl[i - 1].top + cl[i - 1].h + gap) {
      const items = [...cl[i - 1].items, ...cl[i].items];
      const c = { items, h: items.reduce((s, x) => s + x.h, 0) + gap * (items.length - 1) };
      fit(c);
      cl.splice(i - 1, 2, c);
      i = Math.max(1, i - 1);
    } else i++;
  }
  return cl.flatMap((c) => {
    let y = c.top;
    return c.items.map((it) => { const ly = y + it.h / 2; y += it.h + gap; return { ...it, ly }; });
  });
}

function sample(lines) {
  const out = [];
  for (const p of lines) {
    for (let i = 1; i < p.length; i++) {
      const [x0, y0] = p[i - 1], [x1, y1] = p[i], n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 2);
      for (let k = 0; k <= n; k++) out.push([x0 + ((x1 - x0) * k) / n, y0 + ((y1 - y0) * k) / n]);
    }
  }
  return out;
}

function place(labels, obstacles, bounds) {
  const boxes = [...obstacles.boxes], dots = obstacles.dots, done = [];
  const hit = (b) => dots.filter(([x, y]) => x > b[0] - 2 && x < b[2] + 2 && y > b[1] - 2 && y < b[3] + 2).length
    + 6 * boxes.reduce((s, o) => s + Math.max(0, Math.min(b[2], o[2]) - Math.max(b[0], o[0])) * Math.max(0, Math.min(b[3], o[3]) - Math.max(b[1], o[1])) / 40, 0)
    + (b[0] < bounds[0] || b[2] > bounds[2] || b[1] < bounds[1] || b[3] > bounds[3] ? 400 : 0);
  for (const l of labels) {
    const w = measure(l.text, l.cls), h = l.size, g = l.r + 4;
    const cands = [["middle", 0, -g], ["middle", 0, g + h], ["start", g + 1, h / 2 - 1], ["end", -g - 1, h / 2 - 1], ["start", g - 3, -g + 2], ["end", -g + 3, -g + 2], ["start", g - 3, g + h - 2], ["end", -g + 3, g + h - 2]]
      .map(([a, dx, dy], i) => {
        const x = l.x + dx, y = l.y + dy, x0 = a === "middle" ? x - w / 2 : a === "start" ? x : x - w;
        const b = [x0, y - h * 0.78, x0 + w, y + h * 0.22], cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
        const own = Math.hypot(cx - l.x, cy - l.y), near = Math.min(1e9, ...(l.others || []).map(([ox, oy]) => Math.hypot(cx - ox, cy - oy)));
        return { a, x, y, b, score: hit(b) + (near < own - 2 ? 4 + (own - near) / 3 : 0) + (l.prefer === i ? 0 : i === 0 ? 0.6 : i === 1 ? 0.9 : 1.5 + i * 0.2) };
      });
    const best = cands.reduce((m, c) => (c.score < m.score ? c : m));
    boxes.push(best.b);
    done.push({ ...l, ...best });
  }
  return done;
}

function key(items, W, y0) {
  let s = "", x = 0, y = y0;
  for (const it of items) {
    const w = 22 + 7 + measure(it.label, it.cls);
    if (x > 0 && x + w > W) (x = 0), (y += 21);
    s += it.op ? `<path class="op" d="M${f1(x)},${f1(y - 4.5)}H${f1(x + 22)}"/>`
      : `<path class="ln-s" d="M${f1(x)},${f1(y - 4.5)}H${f1(x + 22)}" stroke="${it.color}"/><circle cx="${f1(x + 11)}" cy="${f1(y - 4.5)}" r="4" fill="${it.color}" class="mk-s"/>`;
    s += T(x + 29, y, it.label, it.cls);
    x += w + 16;
  }
  return [s, y];
}

function ticks(lo, hi, step, cls) {
  const out = [];
  for (let t = Math.ceil(lo / step - 1e-9) * step; t <= hi + 1e-9; t += step) {
    const tt = +t.toFixed(6);
    out.push({ t: tt, label: `${minus(String(Math.round(tt * 100)))}%` });
  }
  return out.map((k) => ({ ...k, w: measure(k.label, cls) }));
}

const ladder = (D) => D.versions.filter((v) => v.role === "ladder");

function across(D, W, narrow) {
  W = narrow ? W : D.charts.lead;
  const V = ladder(D), n = V.length, keys = ORDER.filter((k) => V.some((v) => model(v, k)));
  const names = Object.fromEntries(V.flatMap((v) => v.models.map((m) => [m.key, m.name])));
  let [s, y] = header("Hindsight capture C", "% of the hindsight optimum's profit over idle", W);
  if (narrow) {
    const [k, ky] = key([...keys.map((k) => ({ color: COL[k], label: names[k], cls: k === "sol" ? "t-key b" : "t-key" })), { op: true, label: OP.label, cls: "t-key op-t" }], W, y + 26);
    s += k;
    y = ky;
  }
  const y0head = y;
  const last = V[n - 1], split = (t) => { const i = t.indexOf(" ("); return i < 0 ? [t, ""] : [t.slice(0, i), t.slice(i + 1)]; };
  const ends = narrow ? [] : [...keys.map((k) => ({ key: k, c: model(last, k).C.mean, val: pct(model(last, k).C.mean), bold: k === "sol", name: split(names[k]) })),
    ...(ref(last, OP.key) ? [{ key: OP.key, c: ref(last, OP.key).C.mean, val: pct(ref(last, OP.key).C.mean), op: true, name: split(OP.label) }] : [])];
  const vw = Math.max(0, ...ends.map((e) => (e.val ? measure(e.val, "t-end-v") : 0))) + 7;
  const ew = ends.length ? vw + Math.max(...ends.map((e) => Math.max(measure(e.name[0], e.bold ? "t-end b" : "t-end"), measure(e.name[1], "t-end-q")))) : 0;
  const vals = V.flatMap((v) => [...v.models.map((m) => m.C.mean), ref(v, OP.key)?.C.mean ?? 0]);
  const lo = Math.min(-0.05, Math.floor((Math.min(...vals) - 0.02) * 50) / 50), hi = Math.ceil((Math.max(...vals) + 0.12) * 10) / 10;
  const tk = ticks(0, hi, hi > 0.5 ? 0.2 : 0.1, "t-tick"), L = Math.max(...tk.map((k) => k.w)) + 14;
  const R = W - (ends.length ? ew + 30 : 10), pad = narrow ? 30 : 40, xs = V.map((_, i) => L + pad + ((R - L - 2 * pad) * i) / (n - 1));
  const top = y + (narrow ? 22 : 24), PH = narrow ? 260 : 272, bottom = top + PH, yv = lin(lo, hi, bottom, top);
  const tickBoxes = [];
  for (const k of tk) {
    s += L_(L, yv(k.t), R + 6, yv(k.t), k.t ? "grid" : "zero") + T(L - 8, yv(k.t) + 4.5, k.label, "t-tick", "end");
    tickBoxes.push([L - 8 - k.w, yv(k.t) - 6, L - 6, yv(k.t) + 6]);
  }
  let lines = "", marks = "", labels = "";
  const series = keys.map((k) => ({ key: k, m: V.map((v) => model(v, k)) })).map((sr) => ({ ...sr, pts: sr.m.map((m, i) => [xs[i], yv(m.C.mean)]) }));
  const opPts = V.map((v, i) => (ref(v, OP.key) ? [xs[i], yv(ref(v, OP.key).C.mean)] : null)).filter(Boolean);
  lines += `<path class="op" d="${path(opPts)}"/>` + opPts.map(([x, y]) => `<circle class="op-dot" cx="${f1(x)}" cy="${f1(y)}" r="3"/>`).join("");
  for (const sr of [...series].reverse()) {
    lines += `<path class="ln${sr.key === "sol" ? " ln-b" : ""}" d="${path(sr.pts)}" stroke="${COL[sr.key]}"/>`;
    marks += sr.pts.map(([x, y]) => `<circle cx="${f1(x)}" cy="${f1(y)}" r="${sr.key === "sol" ? 6 : 5}" fill="${COL[sr.key]}" class="mk"/>`).join("");
  }
  const dots = sample([...series.map((sr) => sr.pts), opPts, [[L, yv(0)], [R + 6, yv(0)]]]);
  const obstacles = { boxes: [...tickBoxes, ...series.flatMap((sr) => sr.pts.map(([x, y]) => [x - 7, y - 7, x + 7, y + 7]))], dots };
  const want = series.flatMap((sr) => sr.pts.slice(0, narrow ? n : n - 1).map(([x, y], i) => {
    const pv = sr.pts[i - 1]?.[1], nx = sr.pts[i + 1]?.[1], valley = (pv ?? -1e9) < y && (nx ?? -1e9) < y, peak = (pv ?? 1e9) > y && (nx ?? 1e9) > y;
    return { key: sr.key, i, x, y, r: sr.key === "sol" ? 6 : 5, text: pct(sr.m[i].C.mean), cls: sr.key === "sol" ? "t-val b" : "t-val", size: sr.key === "sol" ? 14 : 13,
      prefer: i === 0 ? 3 : i === n - 1 ? 2 : peak ? 0 : valley ? 1 : undefined, others: [...series.filter((o) => o.key !== sr.key).map((o) => o.pts[i]), ...(opPts[i] ? [opPts[i]] : [])] };
  }));
  const placed = place(want, obstacles, [0, top - 24, W - 2, bottom + 20]);
  for (const p of placed) labels += T(p.x, p.y, p.text, p.cls, p.a);
  const gi = V.findIndex((v) => { const g = pair(v, "sol", "luna"); return g && (g.ci[0] > 0 || g.ci[1] < 0); });
  if (gi >= 0) {
    const g = pair(V[gi], "sol", "luna"), sp = placed.find((p) => p.key === "sol" && p.i === gi);
    const t1 = `Sol − Luna ${pts(g.mean, true)} pts`, t2 = `95% CI [${pts(g.ci[0])}, ${pts(g.ci[1])}]`, cw = Math.max(measure(t1, "t-call b"), measure(t2, "t-call"));
    const base = sp ? sp.b[1] : series[0].pts[gi][1] - 12;
    const grid = tk.map((k) => yv(k.t));
    const cands = [0, 8, 16, 24, 32].flatMap((up) => [[xs[gi], base - 24 - up, "middle"], [xs[gi] + 10, base - 24 - up, "start"], [xs[gi] - 10, base - 24 - up, "end"]].map(([x, y, a]) => {
      const x0 = a === "start" ? x : a === "end" ? x - cw : x - cw / 2, b = [x0, y - 12, x0 + cw, y + 20];
      const over = dots.filter(([px, py]) => px > b[0] - 3 && px < b[2] + 3 && py > b[1] - 3 && py < b[3] + 3).length + (x0 < 0 || x0 + cw > W - 2 ? 500 : 0)
        + (grid.some((g) => g > b[1] - 3 && g < b[3] + 2) ? 20 : 0) + (b[1] < y0head + 8 ? 500 : 0) + up / 8 + (a === "middle" ? 0 : 1);
      return { x, y, a, over };
    }));
    const c = cands.reduce((m, k) => (k.over < m.over ? k : m));
    labels += T(c.x, c.y, t1, "t-call b", c.a) + T(c.x, c.y + 16, t2, "t-call", c.a);
  }
  const ex = xs[n - 1] + 26;
  for (const e of dodge(ends.map((e) => ({ ...e, y: yv(e.c) + (e.name[1] ? 7 : 0), h: e.name[1] ? 31 : 16 })), top - 10, bottom + 30, 3)) {
    const y0 = e.ly - (e.name[1] ? 7 : 0), at = yv(e.c);
    labels += `<path class="lead" d="M${f1(xs[n - 1] + 9)},${f1(at)}L${f1(ex - 5)},${f1(y0 - 4.5)}"/>`;
    labels += (e.val ? T(ex + vw - 7, y0, e.val, e.op ? "t-end-v op-t" : "t-end-v", "end") : "") + T(ex + vw, y0, e.name[0], e.op ? "t-end op-t" : e.bold ? "t-end b" : "t-end");
    if (e.name[1]) labels += T(ex + vw, y0 + 15, e.name[1], "t-end-q");
  }
  let maxY = bottom, xl = "";
  const cw = (R - L - 2 * pad) / (n - 1);
  V.forEach((v, i) => {
    let ly = bottom + 26;
    xl += T(xs[i], ly, v.version, "t-ver", "middle");
    if (!narrow) {
      for (const line of wrap(v.name, "t-name", cw - 8)) xl += T(xs[i], (ly += 17), line, "t-name", "middle");
      ly += 2;
      xl += T(xs[i], (ly += 16), unitLines(v)[0], "t-unit", "middle");
    }
    maxY = Math.max(maxY, ly);
  });
  if (narrow) {
    maxY += 12;
    const vx = Math.max(...V.map((v) => measure(v.version, "t-kv"))) + 8;
    for (const v of V) {
      wrap(`${v.name} · ${unitLines(v).join(" ")}`, "t-kd", W - vx).forEach((line, i) => {
        maxY += i ? 17 : 21;
        xl += (i ? "" : T(0, maxY, v.version, "t-kv")) + T(vx, maxY, line, "t-kd");
      });
    }
  }
  const multi = V.filter((v) => v.block !== "day").map((v) => `${v.version} by ${v.block}`);
  maxY += 10;
  for (const line of wrap(`95% CIs (day-block bootstrap${multi.length ? `; ${multi.join(", ")}` : ""}) are in the table below.`, "t-foot", W)) xl += T(0, (maxY += 17), line, "t-foot");
  s += lines + marks + labels + xl;
  return svg(W, maxY + 6, s, "Hindsight capture by model and version");
}

function daily(v, D, W, narrow, scale) {
  const days = v.days, n = days.length, multi = v.days_per_task > 1, keys = ORDER.filter((k) => model(v, k));
  let [s, y] = header(multi ? "Hindsight capture C, front by front" : "Hindsight capture C, day by day", `mean of the ${days[0].n} sites, %`, W);
  if (narrow) {
    const [k, ky] = key([...keys.map((k) => ({ color: COL[k], label: model(v, k).name, cls: k === "sol" ? "t-key b" : "t-key" })), { op: true, label: OP.short, cls: "t-key op-t" }], W, y + 24);
    s += k;
    y = ky;
  }
  const ends = narrow ? [] : [...keys.map((k) => ({ key: k, c: days[n - 1].C[k], text: model(v, k).name, bold: k === "sol" })), { key: OP.key, c: days[n - 1].C[OP.key], text: OP.short, op: true }]
    .filter((e) => e.c != null).map((e) => ({ ...e, lines: [e.text] }));
  const ew = ends.length ? Math.max(...ends.map((e) => measure(e.text, e.bold ? "t-end b" : "t-end"))) : 0;
  const [lo, hi] = scale, tk = ticks(lo, hi, 0.2, "t-tick"), L = Math.max(...tk.map((k) => k.w)) + 14;
  const R = W - (ends.length ? ew + 30 : 10), pad = narrow ? 24 : n > 5 ? 24 : 36;
  const xs = days.map((_, i) => L + pad + ((R - L - 2 * pad) * i) / Math.max(1, n - 1));
  const top = y + 36, PH = narrow ? 240 : 240, bottom = top + PH, yv = lin(lo, hi, bottom, top);
  const fern = days.findIndex((d) => d.named), half = Math.min(xs[1] - xs[0], narrow ? 44 : 64) / 2;
  let back = "", bandRight = 0;
  if (fern >= 0) {
    const x0 = Math.max(L + 1, xs[fern] - half), x1 = (bandRight = Math.min(R + 6, xs[fern] + half));
    back += `<rect class="fern" x="${f1(x0)}" y="${f1(top - 8)}" width="${f1(x1 - x0)}" height="${f1(bottom - top + 8)}" rx="4"/>`;
    const t = cap(days[fern].named), tw = measure(t, "t-fern"), cx = Math.min(Math.max((x0 + x1) / 2, tw / 2), W - tw / 2);
    back += T(cx, top - 14, t, "t-fern", "middle");
  }
  for (const k of tk) back += L_(L, yv(k.t), R + 6, yv(k.t), k.t ? "grid" : "zero") + T(L - 8, yv(k.t) + 4.5, k.label, "t-tick", "end");
  let lines = "", marks = "", labels = "";
  const opPts = days.map((d, i) => (d.C[OP.key] != null ? [xs[i], yv(d.C[OP.key])] : null)).filter(Boolean);
  lines += `<path class="op" d="${path(opPts)}"/>` + opPts.map(([x, y]) => `<circle class="op-dot" cx="${f1(x)}" cy="${f1(y)}" r="2.6"/>`).join("");
  for (const k of [...keys].reverse()) {
    const p = days.map((d, i) => [xs[i], yv(d.C[k])]);
    lines += `<path class="ln-s${k === "sol" ? " ln-b" : ""}" d="${path(p)}" stroke="${COL[k]}"/>`;
    marks += p.map(([x, y]) => `<circle cx="${f1(x)}" cy="${f1(y)}" r="${k === "sol" ? 4.2 : 3.6}" fill="${COL[k]}" class="mk-s"/>`).join("");
  }
  if (fern >= 0) {
    const k = keys.reduce((a, b) => (days[fern].C[b] > days[fern].C[a] ? b : a));
    labels += T(Math.max(xs[fern] + 9, bandRight + 6), yv(days[fern].C[k]) + 4.5, pct(days[fern].C[k]), "t-val b");
  }
  const ex = xs[n - 1] + 24;
  for (const e of dodge(ends.map((e) => ({ ...e, y: yv(e.c), h: 15 })), top - 6, bottom + 12, 2)) {
    labels += `<path class="lead" d="M${f1(xs[n - 1] + 7)},${f1(yv(e.c))}L${f1(ex - 5)},${f1(e.ly)}"/>`;
    labels += T(ex, e.ly + 4.5, e.text, e.op ? "t-end op-t" : e.bold ? "t-end b" : "t-end");
  }
  let xl = "";
  const every = narrow && n > 6 ? 2 : 1;
  days.forEach((d, i) => {
    if (i % every && i !== fern) return;
    const t = span(v, d.block, false), w = measure(t, "t-date"), x = Math.min(Math.max(xs[i], w / 2), W - w / 2);
    xl += T(x, bottom + 22, t, i === fern ? "t-date b" : "t-date", "middle");
  });
  const year = [...new Set(days.map((d) => d.block.slice(0, 4)))].join("–");
  const foot = `${year} · each point: the mean of ${days[0].n} ${multi ? "three-day windows" : "battery-days"}, one per site`;
  let fy = bottom + 26;
  for (const line of wrap(foot, "t-foot", W)) xl += T(0, (fy += 18), line, "t-foot");
  s += back + lines + marks + labels + xl;
  return svg(W, fy + 8, s, `Hindsight capture by ${multi ? "front" : "day"}, ${v.version}`);
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
  const scale = D.charts.days_scale, sizes = [["", D.charts.width, false], ["-phone", D.charts.phone.width, true]];
  const figs = sizes.flatMap(([sfx, W, narrow]) => [[`desk-across${sfx}`, across(D, W, narrow)], ...ladder(D).map((v) => [`desk-${v.version}-days${sfx}`, daily(v, D, W, narrow, scale)])]);
  document.getElementById("figs").innerHTML = figs.map(([id, body]) => `<section class="fig" data-figure="${id}">${body}</section>`).join("");
  const font = await woff2();
  window.chartsSvg = () => Object.fromEntries([...document.querySelectorAll("[data-figure]")].map((e) => [e.dataset.figure, standalone(e.querySelector("svg"), font)]));
  window.chartsReady = true;
}

main();
