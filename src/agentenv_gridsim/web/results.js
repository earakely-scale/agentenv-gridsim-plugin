/** What training bought: reads results.json (written by scripts/hub_results.py) and draws the before and after, the
 * score-against-cost frontier, the training runs, the dollars and the live board's status. ?export=1 draws only the
 * figures, 800 px wide on white, which the build captures as the dataset card's images. */
const Q = new URLSearchParams(location.search);
const EXPORT = Q.has("export");
const DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv";
const REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin";
const LIVE = Q.get("board") || `${DATASET}/resolve/main/live/board.json`;
const C = { sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)", beam: "var(--c-beam)", base: "var(--c-base)", rule: "var(--c-rule)", ref: "var(--c-ref)" };
const FILL = { low: 0.22, medium: 0.5, high: 1, max: 1, beam: { low: 0.18, medium: 0.42, high: 0.7, max: 1 } };
const NAME = { sol: "GPT-6.1 Sol", luna: "GPT-6 Luna", qwen: "Qwen3-4B", beam: "Beam-1.0" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const minus = (s) => s.replace(/-/g, "−");
const num = (x, n = 3) => {
  const [i, f = ""] = Math.abs(x).toString().split(".");
  if (/e/.test(i)) return minus(x.toFixed(n));
  const v = BigInt(i + f.slice(0, n).padEnd(n, "0")) + (f[n] >= "5" ? 1n : 0n);
  const s = v.toString().padStart(n + 1, "0");
  return minus(`${x < 0 && v ? "-" : ""}${s.slice(0, s.length - n)}${n ? `.${s.slice(-n)}` : ""}`);
};
const sg = (x, n = 3) => { const v = num(x, n); return v.startsWith("−") ? v : `+${v}`; };
const ci = (c, n = 3, s = false) => `[${(s ? sg : num)(c[0], n)}, ${(s ? sg : num)(c[1], n)}]`;
const usd = (x) => (x < 0.001 ? `$${x.toFixed(5)}` : `$${x.toFixed(4)}`);
const k = (x, s = false) => `${x < 0 ? "−" : s ? "+" : ""}$${num(Math.abs(x), 1)}k`;
const ds = (rel) => `${DATASET}/blob/main/${rel}`;
const dt = (rel) => `${DATASET}/tree/main/${rel}`;
const gh = (rel) => `${REPO}/blob/main/${rel}`;
const link = (href, t) => `<a href="${href}" target="_blank" rel="noopener">${t}</a>`;

const TIPS = [];
const tip = (html) => `data-tip="${TIPS.push(html) - 1}" tabindex="0"`;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const logs = (d0, d1, r0, r1) => (v) => r0 + ((Math.log10(v) - Math.log10(d0)) / (Math.log10(d1) - Math.log10(d0))) * (r1 - r0);
const ticks = (d0, d1, step) => { const out = []; for (let v = Math.ceil(d0 / step) * step; v <= d1 + 1e-9; v += step) out.push(+v.toFixed(6)); return out; };
const svg = (w, h, body, label) => `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;
const txt = (x, y, s, cls, anchor = "start", extra = "") => `<text x="${x}" y="${y}" class="${cls}" text-anchor="${anchor}" ${extra}>${s}</text>`;
const line = (x1, y1, x2, y2, stroke, w = 1, dash = "", extra = "") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}"${dash ? ` stroke-dasharray="${dash}"` : ""} ${extra}/>`;
const dot = (x, y, r, color, fill = 1, t = "") => `<circle cx="${x}" cy="${y}" r="${r}" fill="${color}" fill-opacity="${fill}" stroke="${color}" stroke-width="2" ${t}/>`;
const dia = (x, y, r, color, fill = 1, t = "") => `<path d="M${x},${y - r * 1.25}L${x + r * 1.25},${y}L${x},${y + r * 1.25}L${x - r * 1.25},${y}Z" fill="${color}" fill-opacity="${fill}" stroke="${color}" stroke-width="2" stroke-linejoin="round" ${t}/>`;
const tick = (x, y, h, color, t = "") => `<rect x="${x - 1.5}" y="${y - h / 2}" width="3" height="${h}" rx="1" fill="${color}" ${t}/>`;
const hit = (x, y, r, t) => `<circle class="hit" cx="${x}" cy="${y}" r="${r}" ${t}/>`;
const mark = (shape, color, fill = 1) => `<i class="mk${shape === "dia" ? " dia" : shape === "bar" ? " bar" : ""}" style="border-color:${color};background:${shape === "bar" ? color : fill === 1 ? color : "transparent"}"></i>`;
const legend = (items) => `<div class="legend">${items.map(([m, l]) => `<span>${m}${l}</span>`).join("")}</div>`;
const tipRows = (title, rows) => `<h6>${title}</h6>${rows.map(([a, b]) => `<div class="r"><span>${a}</span><span>${b}</span></div>`).join("")}`;

function pointTip(p, R) {
  const f = p.final_minus;
  return tipRows(`${NAME[p.family] || p.label}${p.effort ? `, effort ${p.effort}` : p.key === "base" ? ", untrained" : p.key === "final" ? ", trained (run 4)" : ""}`, [
    ["capture", `${num(p.mean)} ${ci(p.ci)}`],
    ["cost per battery-day", usd(p.usd)],
    ["output tokens per task", Math.round(p.tokens).toLocaleString("en-US")],
    ["weights", p.open ? "open" : "API only"],
    ["on the frontier", p.frontier ? "yes" : "no"],
    ...(f ? [["trained 4B minus this", `${sg(f.mean)} ${ci(f.ci, 3, true)}`]] : []),
  ]);
}

const lines = (items, width, px = 6.1) => {
  const out = [];
  for (const it of items) {
    const last = out[out.length - 1];
    if (last && (last.length + it.length + 3) * px <= width) out[out.length - 1] = `${last} · ${it}`;
    else out.push(it);
  }
  return out;
};
const arrow = (xa, xb, y, color) => `<line x1="${xa + 8}" y1="${y}" x2="${xb - 11}" y2="${y}" stroke="${color}" stroke-width="2.2" marker-end="url(#ah)"/>`;
const AH = `<defs><marker id="ah" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,1L9,5L0,9z" fill="var(--c-qwen)"/></marker></defs>`;

function beforeAfter(R, W) {
  const wide = W >= 600;
  const rows = R.scores.filter((r) => r.untrained);
  const L = wide ? 184 : 0, RC = wide ? 150 : 0, x0 = L + 12, x1 = W - RC - 14;
  const glyph = (shape, color) => (shape === "dia" ? dia(4, -4, 4, color) : shape === "bar" ? tick(4, -4, 10, color) : line(0, -4, 9, -4, color, 1.5, "2 2"));
  let y = 0, g = "";
  const head = (t) => { g += txt(0, y + 14, t, "t-lab b"); y += 28; };
  const label = (name, n, when) => (wide
    ? txt(0, y + 21, name, "t-lab b") + txt(0, y + 37, `${n} battery-days`, "t-sub") + txt(0, y + 51, when, "t-sub")
    : txt(0, y + 13, `${name} · ${n} battery-days`, "t-lab b") + txt(0, y + 28, when, "t-sub"));
  const refs = (items, ly) => (wide
    ? items.map(([shape, color, s], i) => `<g transform="translate(${W - RC + 6},${ly - 18 + i * 15})">${glyph(shape, color)}${txt(15, 0, s, "t-ann")}</g>`).join("")
    : lines(items.map(([, , s]) => s), W - 8).map((s, i) => txt(0, y + 43 + i * 15, s, "t-sub")).join(""));
  const drop = (items) => (wide ? 18 : 64 + 15 * (lines(items.map(([, , s]) => s), W - 8).length - 1));
  const lane = (sx, u, t, ly, nu, nt, gapLabel, tipU, tipT) => {
    let s = line(x0, ly, x1, ly, "var(--hair)") + line(x0, ly + 20, x1, ly + 20, "var(--hair)", 1, "2 3");
    s += line(sx(u.ci[0]), ly, sx(u.ci[1]), ly, C.qwen, 1.5, "", 'stroke-opacity="0.45"') + line(sx(t.ci[0]), ly, sx(t.ci[1]), ly, C.qwen, 1.5);
    s += arrow(sx(u.mean), sx(t.mean), ly, C.qwen) + dot(sx(u.mean), ly, 5.5, C.qwen, 0.22, tipU) + dot(sx(t.mean), ly, 6.5, C.qwen, 1, tipT);
    s += txt(sx(u.mean), ly - 10, num(u.mean, nu), "t-val", "middle") + txt(Math.max(sx(t.mean) + 11, sx(t.ci[1]) + 4), ly + 4, num(t.mean, nt), "t-val b");
    if (gapLabel && wide) s += txt((sx(u.mean) + sx(t.mean)) / 2, ly - 8, gapLabel, "t-ann", "middle");
    return s;
  };
  const refMark = (sx, v, color, ly, t) => line(sx(v.ci[0]), ly, sx(v.ci[1]), ly, color, 1.5) + dia(sx(v.mean), ly, 4.6, color, 1, t);
  head(wide ? "Score: the share of the hindsight optimum captured" : "Score: share of hindsight captured");
  const sx = lin(0, 1, x0, x1), topA = y;
  for (const r of rows) {
    const items = [["dia", C.luna, `Luna ${num(r.luna.mean)}`], ["bar", C.base, `${r.baseline.label} ${num(r.baseline.mean)}`], ["dia", C.sol, `Sol ${num(r.sol.mean)}`]];
    const ly = y + drop(items), ry = ly + 20, u = r.untrained, t = r.trained, gu = r.gaps.trained_minus_untrained;
    g += label(r.label, r.n_tasks, r.when);
    const tU = tip(tipRows(`Qwen3-4B, untrained · ${r.label}`, [["capture", `${num(u.mean)} ${ci(u.ci)}`]]));
    const tT = tip(tipRows(`Qwen3-4B, trained (${t.run}) · ${r.label}`, [["capture", `${num(t.mean)} ${ci(t.ci)}`], ...(gu ? [["minus untrained", `${sg(gu.mean)} ${ci(gu.ci, 3, true)}`]] : []), ["minus Luna (high)", `${sg(r.gaps.trained_minus_luna.mean)} ${ci(r.gaps.trained_minus_luna.ci, 3, true)}`], ["minus Sol", `${sg(r.gaps.trained_minus_sol.mean)} ${ci(r.gaps.trained_minus_sol.ci, 3, true)}`]]));
    g += lane(sx, u, t, ly, u.mean < 0.1 ? 2 : 3, 3, gu ? `${sg(gu.mean)} ${ci(gu.ci, 3, true)}` : "", tU, tT);
    g += tick(sx(r.baseline.mean), ry, 13, C.base, tip(tipRows(`${r.baseline.label} · ${r.label}`, [["capture", num(r.baseline.mean)], ["model", "none: rules on the same inputs"]])));
    g += refMark(sx, r.luna, C.luna, ry, tip(tipRows(`GPT-6 Luna, effort high · ${r.label}`, [["capture", `${num(r.luna.mean)} ${ci(r.luna.ci)}`]])));
    g += refMark(sx, r.sol, C.sol, ry, tip(tipRows(`GPT-6.1 Sol, effort high · ${r.label}`, [["capture", `${num(r.sol.mean)} ${ci(r.sol.ci)}`]])));
    g += refs(items, ry);
    y = ry + (wide ? 26 : 30);
  }
  const ta = [0, 0.2, 0.4, 0.6, 0.8, 1];
  g = `<g class="grid">${ta.map((v) => line(sx(v), topA, sx(v), y - 8, v === 0.2 ? "var(--axis)" : "var(--hair)", 1, v === 0.2 ? "3 3" : "")).join("")}</g>` + g;
  g += ta.map((v) => txt(sx(v), y + 6, v === 0.2 ? "0.2 idle" : num(v, 1), "t-ax", "middle")).join("");
  y += 36;
  head(wide ? "Dollars: $k per MW of battery power per year, day-ahead arbitrage" : "Dollars: $k per MW-year");
  const sd = lin(-20, 40, x0, x1), topB = y;
  for (const p of ["eval2025", "fresh"]) {
    const d = R.dollars.packs[p], lad = Object.fromEntries(d.ladder.map((r) => [r.key, r]));
    const up = d.gaps["4b-sampled - base"], vb = d.gaps["4b-sampled - persistence-dp"];
    const pd = lad["persistence-dp"], op = lad.optimum, id = lad.idle;
    const items = [["dia", C.luna, `Luna ${num(lad["luna-high"].yr.mean, 1)}`], ["bar", C.base, `persistence-DP ${num(pd.yr.mean, 1)}`], ["dia", C.sol, `Sol ${num(lad.sol.yr.mean, 1)}`], ["opt", "var(--text-secondary)", `optimum ${num(op.yr.mean, 1)}`]];
    const ly = y + drop(items), ry = ly + 20, u = lad.base.yr, t = lad["4b-sampled"].yr;
    g += label(d.label, d.n_tasks, d.when);
    const tU = tip(tipRows(`Qwen3-4B, untrained · ${d.label}`, [["$k per MW-year", `${num(u.mean, 1)} ${ci(u.ci, 1)}`], ["$ per MW-day", `${num(lad.base.day.mean, 1)} ${ci(lad.base.day.ci, 1)}`]]));
    const tT = tip(tipRows(`Qwen3-4B, trained (run 4) · ${d.label}`, [["$k per MW-year", `${num(t.mean, 1)} ${ci(t.ci, 1)}`], ["minus untrained", `${sg(up.yr.mean, 1)} ${ci(up.yr.ci, 1, true)}`], ["minus persistence-DP", `${sg(vb.yr.mean, 1)} ${ci(vb.yr.ci, 1, true)}`]]));
    g += lane(sd, u, t, ly, 1, 1, `${sg(up.yr.mean, 1)}k ${ci(up.yr.ci, 1, true)}`, tU, tT);
    g += tick(sd(id.yr.mean), ry, 9, C.ref, tip(tipRows(`idle · ${d.label}`, [["$k per MW-year", num(id.yr.mean, 1)], ["below 0", "some batteries must end the day fuller than they start"]]))) + txt(sd(id.yr.mean) - 6, ry + 4, "idle", "t-sub", "end");
    g += tick(sd(pd.yr.mean), ry, 13, C.base, tip(tipRows(`persistence-DP · ${d.label}`, [["$k per MW-year", `${num(pd.yr.mean, 1)} ${ci(pd.yr.ci, 1)}`], ["model", "none: the exact DP on yesterday's prices"]])));
    g += line(sd(op.yr.mean), ry - 8, sd(op.yr.mean), ry + 8, "var(--text-secondary)", 1.5, "2 2", tip(tipRows(`hindsight optimum · ${d.label}`, [["$k per MW-year", num(op.yr.mean, 1)]])));
    g += refMark(sd, lad["luna-high"].yr, C.luna, ry, tip(tipRows(`GPT-6 Luna, effort high · ${d.label}`, [["$k per MW-year", `${num(lad["luna-high"].yr.mean, 1)} ${ci(lad["luna-high"].yr.ci, 1)}`]])));
    g += refMark(sd, lad.sol.yr, C.sol, ry, tip(tipRows(`GPT-6.1 Sol, effort high · ${d.label}`, [["$k per MW-year", `${num(lad.sol.yr.mean, 1)} ${ci(lad.sol.yr.ci, 1)}`]])));
    g += refs(items, ry);
    y = ry + (wide ? 32 : 30);
  }
  const tb = [-20, -10, 0, 10, 20, 30, 40];
  g = `<g class="grid">${tb.map((v) => line(sd(v), topB, sd(v), y - 8, v === 0 ? "var(--axis)" : "var(--hair)")).join("")}</g>` + g;
  g += tb.map((v) => txt(sd(v), y + 6, v > 0 ? `+${v}` : minus(String(v)), "t-ax", "middle")).join("");
  return svg(W, y + 14, AH + g, "Before and after training: Qwen3-4B against GPT-6 Luna and GPT-6.1 Sol, in capture and in dollars");
}

function frontier(R, W) {
  const F = R.frontier, P = Object.fromEntries(F.points.map((p) => [p.key, p]));
  const wide = W >= 600;
  const x0 = 44, x1 = W - (wide ? 16 : 8);
  const H1 = wide ? Math.round(Math.min(380, Math.max(320, W * 0.44))) : 400, H2 = 50, gap = 16, yt = 8;
  const yb1 = yt + H1, yt2 = yb1 + gap, yb2 = yt2 + H2;
  const sx = logs(0.0002, 0.05, x0, x1), sy = lin(0.655, 0.95, yb1, yt), sy2 = lin(0.1, 0.24, yb2, yt2);
  const yOf = (v) => (v < 0.4 ? sy2(v) : sy(v));
  const xt = wide ? [0.0002, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02, 0.05] : [0.0002, 0.001, 0.005, 0.02];
  const yt1 = ticks(0.7, 0.95, 0.05);
  let g = `<g class="grid">${xt.map((v) => line(sx(v), yt, sx(v), yb1, "var(--hair)") + line(sx(v), yt2, sx(v), yb2, "var(--hair)")).join("")}${yt1.map((v) => line(x0, sy(v), x1, sy(v), "var(--hair)")).join("")}${[0.15, 0.2].map((v) => line(x0, sy2(v), x1, sy2(v), "var(--hair)")).join("")}</g>`;
  g += yt1.map((v) => txt(x0 - 7, sy(v) + 4, num(v, 2), "t-ax", "end")).join("") + [0.15, 0.2].map((v) => txt(x0 - 7, sy2(v) + 4, num(v, 2), "t-ax", "end")).join("");
  g += xt.map((v) => txt(sx(v), yb2 + 17, `$${v < 0.001 ? v.toFixed(4) : v < 0.01 ? v.toFixed(3) : v.toFixed(2)}`, "t-ax", "middle")).join("");
  g += txt((x0 + x1) / 2, yb2 + 34, "cost per battery-day, US$ (log scale)", "t-ax", "middle");
  g += `<path d="M${x0 - 5},${yb1 + 6}l10,-5M${x0 - 5},${yt2 + 2}l10,-5" stroke="var(--text-muted)" stroke-width="1.2" fill="none"/>`;
  for (const [key, col, dash, long, short] of [["persistence_dp", C.base, "1.5 3.5", "persistence-DP, no model", "persistence-DP"], ["teacher_dp", C.rule, "5 4", "forecaster + exact DP, no LLM", "forecaster + DP"]]) {
    const r = F.refs[key], t = tip(tipRows(long, [["capture", `${num(r.mean)} ${ci(r.ci)}`], ["cost", "≈ $0: CPU only"]]));
    g += line(x0, sy(r.mean), x1, sy(r.mean), col, 1.4, dash) + line(x0, sy(r.mean), x1, sy(r.mean), "transparent", 9, "", t);
    g += txt(sx(0.0042), sy(r.mean) - 5, `${wide ? long : short} ${num(r.mean)}`, "t-ann", "middle");
  }
  const fr = F.points.filter((p) => p.frontier).sort((a, b) => a.usd - b.usd);
  let main = "", low = "";
  fr.forEach((p, i) => {
    const nx = i + 1 < fr.length ? sx(fr[i + 1].usd) : x1;
    if (p.mean < 0.4) low += `M${sx(p.usd)},${sy2(p.mean)}H${nx}V${yt2}`;
    else main += `${main ? "" : `M${sx(p.usd)},${yb1}`}V${sy(p.mean)}H${nx}`;
  });
  g += `<path d="${main}${low}" fill="none" stroke="var(--text-secondary)" stroke-width="1.4" stroke-dasharray="5 4"/>`;
  for (const fam of ["luna", "beam"]) {
    const ps = F.points.filter((p) => p.family === fam).sort((a, b) => a.usd - b.usd);
    if (ps.length > 1) g += `<polyline points="${ps.map((p) => `${sx(p.usd)},${sy(p.mean)}`).join(" ")}" fill="none" stroke="${C[fam]}" stroke-width="1.6" stroke-opacity="0.5"/>`;
  }
  for (const p of F.points) {
    const ys = p.mean < 0.4 ? sy2 : sy;
    g += line(sx(p.usd), ys(p.ci[0]), sx(p.usd), ys(p.ci[1]), C[p.family], 1.5, "", 'stroke-opacity="0.7"');
  }
  for (const p of F.points) {
    const x = sx(p.usd), y = yOf(p.mean), col = C[p.family];
    const fill = p.family === "beam" ? FILL.beam[p.effort] : p.family === "luna" ? FILL[p.effort] : p.key === "base" ? 0.22 : 1;
    const r = p.key === "final" ? 7 : 5.2, t = tip(pointTip(p, R));
    g += (p.open ? dot(x, y, r, col, fill, t) : dia(x, y, r - 0.6, col, fill, t)) + hit(x, y, 13, t);
  }
  const at = (p, dx, dy, s, cls = "t-ann", anchor = "start") => txt(sx(p.usd) + dx, yOf(p.mean) + dy, s, cls, anchor);
  const lh = P["luna-high"], bm = F.points.filter((p) => p.family === "beam").sort((a, b) => a.usd - b.usd);
  if (wide) {
    g += at(P.final, 11, -24, "Qwen3-4B, trained", "t-lab b") + at(P.final, 11, -10, `${num(P.final.mean)} · ${usd(P.final.usd)}`, "t-val");
    g += at(P.base, 10, -7, `Qwen3-4B, untrained ${num(P.base.mean)}`, "t-lab");
    g += at(lh, 10, 5, "GPT-6 Luna, high", "t-lab b") + at(lh, 10, 19, `${num(lh.mean)} · ${num(F.ratios.luna_high, 1)}× the cost`, "t-val");
    for (const p of F.points.filter((q) => q.family === "luna" && q.effort !== "high")) g += at(p, 9, 4, p.effort);
    g += at(P.sol, -11, 5, "GPT-6.1 Sol", "t-lab b", "end") + at(P.sol, -11, 19, `${num(P.sol.mean)} · ${num(F.ratios.sol, 0)}× the cost`, "t-val", "end");
    for (const p of bm) g += at(p, 9, p.effort === "max" ? -9 : 15, p.effort);
    if (bm.length) g += at(bm[0], 9, 31, "Beam-1.0, open weights", "t-lab b");
  } else {
    g += at(P.final, 10, -11, `4B, trained ${num(P.final.mean)}`, "t-lab b") + at(P.base, 10, -7, `4B, untrained ${num(P.base.mean)}`, "t-lab");
    g += at(lh, 9, 17, "Luna", "t-lab b") + at(P.sol, -9, 4, "Sol", "t-lab b", "end");
    if (bm.length) g += at(bm[0], 8, 17, "Beam", "t-lab b");
  }
  return svg(W, yb2 + 42, g, "Capture against cost per battery-day on the blind newest days, with the frontier");
}

function training(R, W) {
  const T = R.training.curve, wide = W >= 600;
  const x0 = 44, x1 = W - (wide ? 200 : 10), yt = 10, yb = wide ? 330 : 300;
  const sx = lin(0, 335, x0, x1), sy = lin(0.62, 1.0, yb, yt);
  let g = `<g class="grid">${ticks(0.65, 1.0, 0.05).map((v) => line(x0, sy(v), x1, sy(v), "var(--hair)")).join("")}${ticks(0, 300, 50).map((v) => line(sx(v), yt, sx(v), yb, "var(--hair)")).join("")}</g>`;
  g += ticks(0.65, 1.0, 0.05).map((v) => txt(x0 - 7, sy(v) + 4, num(v, 2), "t-ax", "end")).join("");
  g += ticks(0, 300, 50).map((v) => txt(sx(v), yb + 17, v, "t-ax", "middle")).join("") + txt((x0 + x1) / 2, yb + 34, "training step after SFT", "t-ax", "middle");
  for (const [v, col, lab] of [[T.sol.mean, C.sol, `GPT-6.1 Sol ${num(T.sol.mean)}`], [T.luna_high.mean, C.luna, `GPT-6 Luna, high ${num(T.luna_high.mean)}`], [T.greedy_rule.mean, C.base, `greedy rule ${num(T.greedy_rule.mean)}`]]) {
    g += line(x0, sy(v), x1, sy(v), col, 1.3, "1.5 3.5") + txt(x0 + 6, sy(v) - 5, lab, "t-ann");
  }
  const c3 = T.run3;
  g += `<path d="M${c3.map((c) => `${sx(c.step)},${sy(c.sampled.ci[1])}`).join("L")}L${[...c3].reverse().map((c) => `${sx(c.step)},${sy(c.sampled.ci[0])}`).join("L")}Z" fill="var(--band)"/>`;
  for (const [run, col, name] of [[T.run1, C.rule, "Run 1: GRPO from SFT-1,500"], [T.run2, C.base, "Run 2: GRPO from SFT-10k"]]) {
    g += line(sx(0), sy(run.start.mean), sx(run.end.step), sy(run.end.mean), col, 1.8, "6 4");
    for (const [st, v] of [[0, run.start], [run.end.step, run.end]]) {
      const t = tip(tipRows(name, [["step", st], ["held-out R", `${num(v.mean)} ${ci(v.ci)}`], ["end minus start", `${sg(run.gain.mean)} ${ci(run.gain.ci, 3, true)}`]]));
      g += dot(sx(st), sy(v.mean), 4.2, col, 1, t) + hit(sx(st), sy(v.mean), 11, t);
    }
  }
  g += `<polyline points="${c3.map((c) => `${sx(c.step)},${sy(c.sampled.mean)}`).join(" ")}" fill="none" stroke="${C.qwen}" stroke-width="2.4" stroke-linejoin="round"/>`;
  for (const c of c3) {
    const t = tip(tipRows(`Run 3, step ${c.step}`, [["held-out R, sampled", `${num(c.sampled.mean)} ${ci(c.sampled.ci)}`], ["greedy decoding", num(c.greedy)], ["feasible schedules", `${(100 * c.feasible).toFixed(1)}%`]]));
    g += dot(sx(c.step), sy(c.sampled.mean), 3.6, C.qwen, 1, t) + hit(sx(c.step), sy(c.sampled.mean), 11, t);
  }
  const last = c3[c3.length - 1];
  const lab = (x, y, a, b, bold, anchor = "start") => txt(x, y, a, `t-lab${bold ? " b" : ""}`, anchor) + txt(x, y + 14, b, "t-ann", anchor);
  if (wide) {
    g += lab(x1 + 10, sy(last.sampled.mean) + 4, "Run 3: exact DP advantages", `${sg(T.run3_gain.mean)} ${ci(T.run3_gain.ci, 3, true)}`, true);
    g += lab(x1 + 10, sy(T.run2.end.mean) + 2, "Run 2: GRPO from SFT-10k", `${sg(T.run2.gain.mean)} ${ci(T.run2.gain.ci, 3, true)}`, false);
    g += lab(x1 + 10, sy(T.run1.end.mean) + 20, "Run 1: GRPO from SFT-1,500", `${sg(T.run1.gain.mean)} ${ci(T.run1.gain.ci, 3, true)}`, false);
  } else {
    g += txt(sx(last.step), sy(last.sampled.mean) - 11, `run 3 ${sg(T.run3_gain.mean)}`, "t-lab b", "end");
    g += txt(sx(T.run2.end.step) - 4, sy(T.run2.end.mean) + 17, `run 2 ${sg(T.run2.gain.mean)}`, "t-lab", "end");
    g += txt(sx(120), sy(T.run1.start.mean + (T.run1.end.mean - T.run1.start.mean) * 120 / T.run1.end.step) - 9, `run 1 ${sg(T.run1.gain.mean)}`, "t-lab", "middle");
  }
  return svg(W, yb + 42, g, "Held-out reward against training step: GRPO runs 1 and 2 and the DP-advantage run 3");
}

function planning(R, W) {
  const P = R.training.planning, wide = W >= 600;
  const packs = [["eval2025", "Held-out 2025 · 300 battery-days"], ["fresh", "Newest days · 331 battery-days"]];
  const rows = [["sft", "After SFT on the teacher", C.qwen, "dot", 0.45], ["final", "After RL: its own schedules", C.qwen, "dot", 1], ["dp_own", "The exact DP on its own forecast", C.qwen, "ring", 1], ["teacher", "The teacher's forecast + the DP", C.base, "bar", 1], ["sol", "GPT-6.1 Sol, same prompt", C.sol, "dia", 1]];
  const L = wide ? 222 : 0, rh = wide ? 28 : 36, colW = wide ? (W - L - 16) / 2 : W - 6;
  const one = (pack, title, ox, oy) => {
    const d = P[pack], sx = lin(0.78, 0.94, ox + 10, ox + colW - 34);
    let s = txt(ox + 10, oy - 14, title, "t-lab b");
    const yb = oy + rows.length * rh - 6;
    s += `<g class="grid">${ticks(0.8, 0.92, 0.04).map((v) => line(sx(v), oy - 6, sx(v), yb, "var(--hair)")).join("")}</g>`;
    s += ticks(0.8, 0.92, 0.04).map((v) => txt(sx(v), yb + 15, num(v, 2), "t-ax", "middle")).join("");
    rows.forEach(([key, lab, col, shape, fill], i) => {
      const v = d[key], y = oy + i * rh + (wide ? 8 : 16);
      if (!wide) s += txt(ox + 10, y - 10, lab, "t-sub");
      const t = tip(tipRows(`${lab} · ${title}`, [["capture", `${num(v.mean)} ${ci(v.ci)}`]]));
      s += line(sx(v.ci[0]), y, sx(v.ci[1]), y, col, 1.5, "", 'stroke-opacity="0.55"');
      s += shape === "dia" ? dia(sx(v.mean), y, 4.6, col, 1, t) : shape === "bar" ? tick(sx(v.mean), y, 13, col, t)
        : shape === "ring" ? `<circle cx="${sx(v.mean)}" cy="${y}" r="5.5" fill="var(--surface-1)" stroke="${col}" stroke-width="2.2" stroke-dasharray="2.4 1.8" ${t}/>` : dot(sx(v.mean), y, 5.5, col, fill, t);
      s += hit(sx(v.mean), y, 11, t) + txt(Math.max(sx(v.mean), sx(v.ci[1])) + 7, y + 4, num(v.mean), key === "final" || key === "dp_own" ? "t-val b" : "t-val");
    });
    const yf = oy + rh + (wide ? 8 : 16), yd = oy + 2 * rh + (wide ? 8 : 16), xf = sx(d.final.mean), gl = d.gaps.final_minus_dp_own;
    const xd = sx(d.dp_own.mean);
    if (wide) {
      s += `<path d="M${xf},${yf + 8}V${yd + 6}H${xd - 9}" stroke="var(--text-secondary)" stroke-width="1" fill="none" stroke-dasharray="2 2"/>`;
      s += txt((xf + xd) / 2, yd + 19, `planning loss ${sg(gl.mean)}`, "t-ann", "middle");
    }
    return s;
  };
  let g = "";
  if (wide) {
    rows.forEach(([, lab], i) => (g += txt(0, 34 + i * rh + 12, lab, "t-lab")));
    packs.forEach(([p, t], j) => (g += one(p, t, L + j * (colW + 16), 34)));
    return svg(W, 34 + rows.length * rh + 22, g, "Run 4 on the blind tier: its schedules against the exact DP on its own forecasts, the teacher and Sol");
  }
  const h1 = rows.length * rh + 58;
  packs.forEach(([p, t], j) => (g += one(p, t, 0, 24 + j * h1)));
  return svg(W, 24 + 2 * h1 - 20, g, "Run 4 on the blind tier: its schedules against the exact DP on its own forecasts, the teacher and Sol");
}

const LADDER = { optimum: ["hindsight optimum", null], sol: ["GPT-6.1 Sol", "sol"], "persistence-dp": ["persistence-DP (no model)", "base"], "luna-high": ["GPT-6 Luna, high", "luna"], "luna-medium": ["GPT-6 Luna, medium", "luna"], "4b-sampled": ["Qwen3-4B, trained", "qwen"], sft: ["Qwen3-4B, SFT only", "qwen"], "ridge-dp": ["ridge-DP (no LLM)", "rule"], "greedy-d1": ["greedy rule, yesterday's prices", "rule"], "luna-low": ["GPT-6 Luna, low", "luna"], "threshold-d1": ["threshold rule, yesterday's prices", "rule"], idle: ["idle", "ref"], base: ["Qwen3-4B, untrained", "qwen"] };

function ladder(R, W, pack = "eval2025") {
  const D = R.dollars.packs[pack], wide = W >= 600;
  const rows = D.ladder.filter((r) => r.key !== "optimum" && r.key !== "sft").sort((a, b) => b.yr.mean - a.yr.mean);
  const op = D.ladder.find((r) => r.key === "optimum");
  const L = wide ? 214 : 0, x0 = L + 10, x1 = W - (wide ? 132 : 30), rh = wide ? 26 : 36, yt = 28;
  const sx = lin(-20, 40, x0, x1), yb = yt + rows.length * rh;
  let g = `<g class="grid">${ticks(-20, 40, 10).map((v) => line(sx(v), yt - 6, sx(v), yb, v === 0 ? "var(--axis)" : "var(--hair)")).join("")}</g>`;
  g += ticks(-20, 40, 10).map((v) => txt(sx(v), yb + 16, v > 0 ? `+${v}` : minus(String(v)), "t-ax", "middle")).join("");
  g += txt((x0 + x1) / 2, yb + 33, wide ? "$k per MW of battery power per year (battery-day mean × 365)" : "$k per MW-year", "t-ax", "middle");
  const yOf = (i) => yt + i * rh + (wide ? rh / 2 : rh - 11);
  rows.forEach((r, i) => {
    const [name, fam] = LADDER[r.key], y = yOf(i), col = C[fam];
    const fill = fam === "luna" ? FILL[r.key.split("-")[1]] : r.key === "base" ? 0.22 : 1;
    const t = tip(tipRows(name, [["$k per MW-year", `${num(r.yr.mean, 1)} ${ci(r.yr.ci, 1)}`], ["$ per MW-day", `${num(r.day.mean, 1)} ${ci(r.day.ci, 1)}`], ["per 100 MW a year", `${r.per_100mw_yr < 0 ? "−" : ""}$${num(Math.abs(r.per_100mw_yr) / 1000, 2)}M`], ...(r.inference != null ? [["inference per battery-day", usd(r.inference)]] : [])]));
    const xa = sx(Math.min(0, r.yr.mean)), xb = sx(Math.max(0, r.yr.mean)), me = r.key === "4b-sampled" || r.key === "base";
    g += wide ? txt(L, y + 4, name, `t-lab${me ? " b" : ""}`, "end") : txt(x0, y - 12, name, `t-sub${me ? " b" : ""}`);
    g += `<rect x="${xa}" y="${y - 7.5}" width="${Math.max(1, xb - xa)}" height="15" rx="2" fill="${col}" fill-opacity="${fill}" stroke="${fill < 1 ? col : "none"}" stroke-width="${fill < 1 ? 1.5 : 0}" ${t}/>`;
    g += line(sx(r.yr.ci[0]), y, sx(r.yr.ci[1]), y, "var(--text-primary)", 1, "", 'stroke-opacity="0.5"');
    g += r.yr.mean >= 0 ? txt(Math.max(sx(r.yr.ci[1]), xb) + 6, y + 4, num(r.yr.mean, 1), `t-val${me ? " b" : ""}`) : txt(sx(0) + 6, y + 4, num(r.yr.mean, 1), `t-val${me ? " b" : ""}`);
  });
  g += line(sx(op.yr.mean), yt - 12, sx(op.yr.mean), yb, "var(--text-secondary)", 1.3, "4 3") + txt(sx(op.yr.mean) + (wide ? 0 : 4), yt - 16, `hindsight optimum ${num(op.yr.mean, 1)}`, "t-ann", wide ? "middle" : "end");
  const iT = rows.findIndex((r) => r.key === "4b-sampled"), iB = rows.findIndex((r) => r.key === "base");
  if (wide && iT >= 0 && iB >= 0) {
    const up = D.gaps["4b-sampled - base"], xr = x1 + 22, yA = yOf(iB), yB = yOf(iT);
    g += `<path d="M${xr - 7},${yA}H${xr}V${yB + 9}" fill="none" stroke="${C.qwen}" stroke-width="2"/><path d="M${xr - 5},${yB + 10}L${xr},${yB + 1}L${xr + 5},${yB + 10}Z" fill="${C.qwen}"/><path d="M${xr - 7},${yB}H${xr - 3}" stroke="${C.qwen}" stroke-width="2"/>`;
    g += txt(xr + 9, (yA + yB) / 2 - 8, `${sg(up.yr.mean, 1)}k`, "t-val b") + txt(xr + 9, (yA + yB) / 2 + 7, "from training", "t-ann") + txt(xr + 9, (yA + yB) / 2 + 21, ci(up.yr.ci, 1, true), "t-ann");
  }
  return svg(W, yb + 42, g, "Dollars per MW of battery power per year for every policy, blind tier");
}

function regimes(R, W) {
  const Qs = R.dollars.packs.eval2025.quartiles, wide = W >= 600;
  const x0 = 50, x1 = W - 8, yt = 16, yb = wide ? 300 : 280;
  const sy = lin(-42, 46, yb, yt), bw = (x1 - x0) / 4;
  const ms = [["sol", C.sol, "dia", "GPT-6.1 Sol"], ["luna-high", C.luna, "dia", "GPT-6 Luna, high"], ["4b-sampled", C.qwen, "dot", "Qwen3-4B, trained"]];
  let g = `<g class="grid">${ticks(-40, 40, 10).map((v) => line(x0, sy(v), x1, sy(v), v === 0 ? "var(--axis)" : "var(--hair)")).join("")}</g>`;
  g += ticks(-40, 40, 10).map((v) => txt(x0 - 7, sy(v) + 4, v > 0 ? `+${v}` : minus(String(v)), "t-ax", "end")).join("");
  g += `<text transform="translate(11,${(yt + yb) / 2}) rotate(-90)" class="t-ax" text-anchor="middle">$ per MW-day minus persistence-DP</text>`;
  Qs.forEach((q, i) => {
    const cx = x0 + bw * (i + 0.5), rng = `${num(q.range[0])}–${num(q.range[1])}`;
    const t = tip(tipRows(`Q${q.q}: 1 − r ${rng}`, [["days", q.days], ["persistence-DP below the optimum", `$${num(q.shortfall.mean, 1)} ${ci(q.shortfall.ci, 1)}`], ["hindsight optimum", `$${num(q.optimum.mean, 1)} per MW-day`]]));
    g += `<rect x="${cx - bw * 0.38}" y="${sy(q.shortfall.mean)}" width="${bw * 0.76}" height="${sy(0) - sy(q.shortfall.mean)}" rx="3" fill="var(--surface-2)" stroke="var(--hair)" ${t}/>`;
    g += txt(cx, sy(q.shortfall.mean) - 6, wide ? `room $${num(q.shortfall.mean, 1)}` : `$${num(q.shortfall.mean, 1)}`, "t-ann", "middle");
    ms.forEach(([key, col, shape, nm], j) => {
      const v = q[key], x = cx + (j - 1) * Math.min(26, bw * 0.24);
      const tt = tip(tipRows(`${nm} − persistence-DP · Q${q.q}`, [["$ per MW-day", `${sg(v.mean, 1)} ${ci(v.ci, 1, true)}`], ["days ahead", `${v.days_ahead} of ${q.days}`]]));
      g += line(x, sy(v.ci[0]), x, sy(v.ci[1]), col, 1.6, "", 'stroke-opacity="0.8"') + (shape === "dia" ? dia(x, sy(v.mean), 4.8, col, 1, tt) : dot(x, sy(v.mean), 5.2, col, 1, tt)) + hit(x, sy(v.mean), 11, tt);
      if (key === "sol" && q.q === 4) g += txt(x - 9, sy(v.mean) + 4, sg(v.mean, 1), "t-val b", "end");
    });
    g += txt(cx, yb + 17, wide ? `Q${q.q}${q.q === 1 ? " · shape repeats" : q.q === 4 ? " · shape changes" : ""}` : `Q${q.q}`, "t-lab b", "middle");
    g += txt(cx, yb + 32, wide ? `1 − r ${rng} · ${q.days} days` : rng, "t-sub", "middle");
  });
  return svg(W, yb + 44, g, "Gain over persistence-DP by price-shape change quartile, blind 2025");
}

const FIGS = {
  "before-after": {
    kicker: "Before and after",
    title: () => "Training took Qwen3-4B from below idle to level with GPT-6 Luna",
    sub: () => "The same one-call prompt for every model. Top: the share of the hindsight optimum each schedule captures (idle 0.2, perfect hindsight 1.0). Bottom: what the schedules earn at ERCOT's day-ahead prices. GPT-6.1 Sol stays ahead on every row. Lines: 95% CIs.",
    draw: beforeAfter,
    legend: () => legend([[mark("dot", C.qwen, 0.2), "Qwen3-4B, untrained"], [mark("dot", C.qwen), "Qwen3-4B, trained"], [mark("dia", C.luna), "GPT-6 Luna, high effort"], [mark("dia", C.sol), "GPT-6.1 Sol, high effort"], [mark("bar", C.base), "best simple rule, no model"]]),
    notes: (R) => {
      const f = R.scores.find((r) => r.key === "foresight-fresh");
      return [`The trained 4B is registered run 4's model on the blind rows and run 3's on foresight; the simple rule is persistence-DP (the exact DP on yesterday's prices) on blind and the greedy rule on foresight. CIs resample whole days, except the untrained foresight row and the greedy rule, which resample tasks as their runs registered them.`, f ? `Not drawn: foresight on the newest days, where the untrained 4B was not run. There GPT-6 Luna is ahead of the trained 4B, ${num(f.luna.mean)} against ${num(f.trained.mean)}, paired ${sg(f.gaps.trained_minus_luna.mean)} ${ci(f.gaps.trained_minus_luna.ci, 3, true)}.` : ""];
    },
    src: "results/train/4b-blind, results/train/4b-dpa, results/cost-matched and results/economics",
  },
  frontier: {
    kicker: "Score against cost",
    title: () => "The trained 4B is on the frontier: GPT-6 Luna's score at a quarter of its cost",
    sub: (R) => `Bidding blind on the ${R.frontier.n_tasks} newest battery-days, 18–27 October 2026. Each point is one model at one reasoning effort; lines are day-block 95% CIs. Dashed: the frontier, the best capture any model reaches at that cost or less.`,
    draw: frontier,
    legend: () => legend([[mark("dot", C.qwen), "Qwen3-4B, open weights, one L40S"], [mark("dot", C.beam), "Beam-1.0, open weights, via the HF router"], [mark("dia", C.luna), "GPT-6 Luna, API, effort low → high"], [mark("dia", C.sol), "GPT-6.1 Sol, API"], [`<i class="key dash" style="border-top-color:var(--text-secondary)"></i>`, "frontier"]]),
    notes: (R) => {
      const P = Object.fromEntries(R.frontier.points.map((p) => [p.key, p]));
      const bm = R.frontier.points.filter((p) => p.family === "beam").sort((a, b) => b.mean - a.mean)[0];
      return [`Trained 4B minus Luna at high effort: ${sg(P["luna-high"].final_minus.mean)} ${ci(P["luna-high"].final_minus.ci, 3, true)}. Minus Luna at low effort, the matched cost (${num(R.frontier.ratios.luna_low, 1)}× the 4B's): ${sg(P["luna-low"].final_minus.mean)} ${ci(P["luna-low"].final_minus.ci, 3, true)}. Minus Sol, at ${num(R.frontier.ratios.sol, 0)}× its cost: ${sg(P.sol.final_minus.mean)} ${ci(P.sol.final_minus.ci, 3, true)}.${bm ? ` Beam at its best effort (${bm.effort}) scores ${num(bm.mean)} for ${usd(bm.usd)}; Sol scores more for less, so Beam is off the frontier at every effort.` : ""}`, `Cost per battery-day: API models at their recorded token usage × list price, Beam at Baseten's price on the Hugging Face router; the 4Bs at the logged batched-generation time on one L40S, $${num(R.frontier.l40s_usd_per_h, 2)} an hour, engine start and idle time not charged. The two horizontal lines use no LLM: persistence-DP plans exactly on yesterday's prices, and the forecaster is run 4's teacher (ridge + LightGBM + MLP).`];
    },
    src: "results/cost-matched, results/beam-agent and results/train/4b-blind",
  },
  training: {
    kicker: "Training",
    title: () => "GRPO stalled on a strong warm start; exact DP advantages kept improving it",
    sub: () => "Foresight tier: held-out reward R on the same 200 battery-days of 2025, sampled at temperature 0.7. Run 3's band is the 95% CI at each checkpoint; runs 1 and 2 were scored on all 200 days at their start and end only. Labels: the registered paired change, end minus start.",
    draw: training,
    legend: () => legend([[`<i class="key" style="border-top-color:var(--c-qwen);border-top-width:3px"></i>`, "run 3: exact per-hour DP advantages (PPO-clipped loop, PEFT, vLLM)"], [`<i class="key dash" style="border-top-color:var(--c-base)"></i>`, "run 2: GRPO in TRL"], [`<i class="key dash" style="border-top-color:var(--c-rule)"></i>`, "run 1: GRPO in TRL"]]),
    notes: (R) => {
      const T = R.training.curve, c = T.run3;
      return [`GRPO lifted run 1's weaker warm start (SFT on 1,500 schedules); from SFT-10k it found almost no reward spread to learn from. Run 3's registered primary needed a paired gain over step 0 above 0 and a held-out slope above 0, ${sg(T.run3_slope.per_100, 4)} per 100 steps ${ci(T.run3_slope.ci, 4, true)}: both held. The gain is fewer broken schedules (feasible ${(100 * c[0].feasible).toFixed(1)}% → ${(100 * c[c.length - 1].feasible).toFixed(1)}%), not more exact optima.`];
    },
    src: "results/train/4b, results/train/4b-v2 and results/train/4b-dpa; CIs over tasks",
  },
  planning: {
    kicker: "Blind: forecasting against planning",
    title: () => "Bidding blind, the 4B forecasts like its teacher and loses its score in planning",
    sub: () => "Run 4 writes a 24-hour price forecast, then its schedule. Planned by the exact DP, its own forecasts would capture as much as GPT-6.1 Sol; its own schedules capture less. Dots: capture; lines: day-block 95% CIs.",
    draw: planning,
    legend: () => legend([[mark("dot", C.qwen), "Qwen3-4B, run 4"], [`<i class="mk" style="border-color:var(--c-qwen);border-style:dashed"></i>`, "the exact DP on the 4B's own forecast"], [mark("bar", C.base), "teacher forecaster + exact DP"], [mark("dia", C.sol), "GPT-6.1 Sol"]]),
    notes: (R) => {
      const e = R.training.planning.eval2025, m = R.training.planning.mae;
      return [`Held-out 2025: the DP on the 4B's own forecasts minus Sol ${sg(e.gaps.dp_own_minus_sol.mean)} ${ci(e.gaps.dp_own_minus_sol.ci, 3, true)}, reported, not registered; the 4B's own schedules minus Sol ${sg(e.gaps.final_minus_sol.mean)} ${ci(e.gaps.final_minus_sol.ci, 3, true)}, the registered primary, not met. Forecast error over all hours: the 4B ${num(m.final, 2)} $/MWh, its teacher ${num(m.teacher, 2)}, yesterday's prices ${num(m.persistence, 2)}. ${Math.round(100 * e.exact_dp_share)}% of its schedules are the DP plan on the forecast it wrote just above them.`];
    },
    src: "results/train/4b-blind",
  },
  ladder: {
    kicker: "What it's worth",
    title: (R) => `Training bought ${k(R.dollars.packs.eval2025.gaps["4b-sampled - base"].yr.mean)} per MW-year; the 4B still trails a free heuristic by ${k(-R.dollars.packs.eval2025.gaps["4b-sampled - persistence-dp"].yr.mean)}`,
    sub: () => "Every recorded blind schedule of 2025 settled again at ERCOT's day-ahead prices (300 battery-days on 191 days), its profit per MW of battery power × 365. Lines: day-block 95% CIs. Day-ahead energy arbitrage only.",
    draw: (R, W) => ladder(R, W, "eval2025"),
    legend: () => legend([[mark("bar", C.qwen), "Qwen3-4B"], [mark("bar", C.luna), "GPT-6 Luna"], [mark("bar", C.sol), "GPT-6.1 Sol"], [mark("bar", C.base), "persistence-DP"], [mark("bar", C.rule), "other rules on yesterday's prices"]]),
    notes: (R) => {
      const D = R.dollars.packs.eval2025, G = D.gaps, I = D.inference;
      return [`GPT-6.1 Sol minus persistence-DP: ${sg(G["sol - persistence-dp"].yr.mean, 1)}k ${ci(G["sol - persistence-dp"].yr.ci, 1, true)} per MW-year, about $${Math.round(G["sol - persistence-dp"].per_100mw_yr)}k a year for a 100 MW battery, for $${num(I.sol_over_persistence.inference_usd_per_battery_yr, 2)} of inference a battery-year. The trained 4B minus persistence-DP: ${sg(G["4b-sampled - persistence-dp"].yr.mean, 1)}k ${ci(G["4b-sampled - persistence-dp"].yr.ci, 1, true)}.`, "Idle is below zero because some batteries must end the day fuller than they started. The untrained 4B is below idle: it sells before it charges and breaks the battery's rules."];
    },
    src: "results/economics, a descriptive re-analysis",
  },
  regimes: {
    kicker: "When reasoning pays",
    title: () => "Sol's edge over the heuristic is on the days when the price shape changes",
    sub: () => "Blind, 2025: the 191 days split into quartiles by how far the day's 24 hourly prices move from the day before's shape (1 − Pearson r). Grey: what persistence-DP left below the hindsight optimum. Points: each model minus persistence-DP in $ per MW of battery power per day, with day-block 95% CIs.",
    draw: regimes,
    legend: () => legend([[mark("dia", C.sol), "GPT-6.1 Sol"], [mark("dia", C.luna), "GPT-6 Luna, high"], [mark("dot", C.qwen), "Qwen3-4B, trained"], [`<i class="mk bar" style="background:var(--surface-2);border:1px solid var(--hair);width:11px"></i>`, "room: persistence-DP's shortfall"]]),
    notes: (R) => {
      const D = R.dollars.packs.eval2025, q4 = D.quartiles[3];
      return [`When the day repeats yesterday (Q1, Q2), persistence-DP is within a few dollars of the optimum: Sol stays level with it, while Luna and the 4B lose money by moving off it. In Q4 Sol recovers ${num(q4.sol.mean, 1)} of the ${num(q4.shortfall.mean, 1)} $/MW-day persistence-DP leaves behind; Luna and the 4B only draw level. ${Math.round(100 * D.top_days.sol_share_from_top)}% of Sol's net gain over persistence-DP comes from its best ${D.top_days.k} days. A descriptive re-analysis, not pre-registered.`];
    },
    src: "results/economics, a descriptive re-analysis",
  },
};

function figure(id, R, W) {
  const f = FIGS[id];
  return `<section class="panel fig" id="fig-${id}" data-figure="${id}"><div class="panel-head"><span class="kicker">${f.kicker}</span><h2>${esc(f.title(R))}</h2><p class="sub">${esc(f.sub(R))}</p></div><div class="chart">${f.draw(R, W)}</div>${f.legend(R)}${f.notes(R).filter(Boolean).map((n) => `<p class="note">${esc(n)}</p>`).join("")}<p class="src">Sources: ${esc(f.src)} in the GridSimEnv-AgentEnv dataset.</p></section>`;
}

function kpis(R) {
  return R.glance.map((g, i) => `<div class="kpi${i === 0 ? " hero" : ""}"><span class="v">${esc(g.value)}</span><span class="l">${esc(g.label)}</span><span class="t">${esc(g.text)}</span><span class="src">Evidence: ${g.src.map((s) => link(dt(s), s.replace("results/", ""))).join(" · ")}</span></div>`).join("");
}

const td = (label, html, cls = "") => `<td class="${cls}"${label ? ` data-l="${esc(label)}"` : ""}>${html}</td>`;
const table = (cls, heads, rows) => `<div class="table-scroll"><table class="grid stack ${cls}"><thead><tr>${heads.map(([h, c = ""]) => `<th class="${c}">${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;

function scoreTable(R) {
  const v = (x, b = false) => (x ? `${b ? `<b>${num(x.mean)}</b>` : num(x.mean)}<span class="sub">${ci(x.ci)}</span>` : `<span class="na">not run</span>`);
  const gp = (g) => `${sg(g.mean)}<span class="sub">${ci(g.ci, 3, true)}</span>`;
  return table("scores", [["Pack", "l"], ["Untrained 4B"], ["Trained 4B"], ["Luna, high"], ["Sol, high"], ["Simple rule"], ["Trained − Luna"], ["Trained − Sol"]], R.scores.map((r) => `<tr>${td("", `<b>${esc(r.label)}</b><span class="sub">${r.n_tasks} battery-days · ${r.trained.run}</span>`, "l")}${td("Untrained 4B", v(r.untrained))}${td("Trained 4B", v(r.trained, true))}${td("Luna, high", v(r.luna))}${td("Sol, high", v(r.sol))}${td("Simple rule", `${num(r.baseline.mean)}<span class="sub">${esc(r.baseline.label)}</span>`)}${td("Trained − Luna", gp(r.gaps.trained_minus_luna))}${td("Trained − Sol", gp(r.gaps.trained_minus_sol))}</tr>`));
}

function frontierTable(R) {
  const sw = (p) => `<i style="background:${C[p.family]};opacity:${p.family === "beam" ? FILL.beam[p.effort] : p.family === "luna" ? FILL[p.effort] : p.key === "base" ? 0.3 : 1}"></i>`;
  return table("points", [["Model", "l"], ["Capture"], ["95% CI"], ["$ per battery-day"], ["Output tokens"], ["Weights"], ["Frontier"], ["Trained 4B − this"]], [...R.frontier.points].sort((a, b) => a.usd - b.usd).map((p) => `<tr class="${p.key === "final" ? "me" : ""}">${td("", `<span class="who">${sw(p)}${esc(NAME[p.family])}${p.effort ? `, ${p.effort}` : p.key === "base" ? ", untrained" : ", trained (run 4)"}</span>`, "l")}${td("Capture", num(p.mean))}${td("95% CI", ci(p.ci), "ci")}${td("$ per battery-day", usd(p.usd))}${td("Output tokens", Math.round(p.tokens).toLocaleString("en-US"))}${td("Weights", p.open ? "open" : "API")}${td("Frontier", p.frontier ? "yes" : "–")}${td("Trained 4B − this", p.final_minus ? `${sg(p.final_minus.mean)} <span class="ci">${ci(p.final_minus.ci, 3, true)}</span>` : "–")}</tr>`));
}

function runsTable(R) {
  return table("runs", [["Run", "l"], ["What changed", "l"], ["Held-out"], ["What it taught", "l"], ["GPU"]], R.training.runs.map((r) => `<tr>${td("", `<b>${esc(r.label)}</b><span class="sub">${esc(r.model)}</span><span class="tag${r.registered ? " reg" : ""}">${r.registered ? "pre-registered" : "exploratory"}</span>`, "l")}${td("What changed", esc(r.change), "l what full")}${td("Held-out", esc(r.result))}${td("What it taught", `${esc(r.lesson)} ${link(dt(r.src), "Evidence")}`, "l why full")}${td("GPU", r.usd == null ? "–" : `$${r.usd % 1 ? r.usd.toFixed(2) : r.usd}`)}</tr>`));
}

const ORDER = ["optimum", "sol", "persistence-dp", "luna-high", "luna-medium", "4b-sampled", "sft", "ridge-dp", "greedy-d1", "luna-low", "threshold-d1", "idle", "base"];

function economicsTable(R) {
  const P = R.dollars.packs, get = (p, key) => P[p].ladder.find((r) => r.key === key);
  const cell = (r) => (r ? `${num(r.yr.mean, 1)}<span class="sub">${ci(r.yr.ci, 1)}</span>` : `<span class="na">–</span>`);
  return table("usd", [["Policy", "l"], ["2025, $k per MW-yr"], ["2025, per 100 MW-yr"], ["Newest days, $k per MW-yr"], ["Inference per battery-day"]], ORDER.filter((key) => get("eval2025", key) || get("fresh", key)).map((key) => {
    const a = get("eval2025", key), b = get("fresh", key), r = a || b;
    return `<tr class="${key === "4b-sampled" ? "me" : ""}">${td("", esc(r.label), "l")}${td("2025, $k per MW-yr", cell(a))}${td("2025, per 100 MW-yr", a ? `${a.per_100mw_yr < 0 ? "−" : ""}$${num(Math.abs(a.per_100mw_yr) / 1000, 2)}M` : "–")}${td("Newest days, $k per MW-yr", cell(b))}${td("Inference per battery-day", r.inference != null ? usd(r.inference) : "–")}</tr>`;
  }));
}

function render(R) {
  TIPS.length = 0;
  const D = R.dollars.packs.eval2025, T = R.training;
  if (EXPORT) {
    document.body.classList.add("export");
    document.documentElement.dataset.theme = "light";
    $("main").innerHTML = Object.keys(FIGS).map((id) => figure(id, R, 748)).join("");
    return;
  }
  const W = Math.max(280, Math.min(1080, $("main").clientWidth) - (innerWidth < 720 ? 26 : 42));
  $("lede").innerHTML = `A 4-billion-parameter open model, <b>Qwen3-4B</b>, trained on GridSimEnv's exact grader, went from losing money on a Texas grid battery to <b>bidding as well as GPT-6 Luna at a quarter of its cost</b>. It still trails GPT-6.1 Sol, and a free heuristic, by thousands of dollars per MW of battery a year. Every number here comes from a pre-registered run or a committed re-analysis, with its evidence a click away.`;
  $("kpis").innerHTML = kpis(R);
  const block = (h, sub, inner, id = "") => `<section class="panel"${id ? ` id="${id}"` : ""}><div class="panel-head"><h2>${h}</h2>${sub ? `<p class="sub">${sub}</p>` : ""}</div>${inner}</section>`;
  $("main").innerHTML = [
    figure("before-after", R, W),
    block("Before and after, pack by pack", "Every comparison of the trained 4B with GPT-6 Luna and GPT-6.1 Sol under one harness, as the cost-matched contest registered them. Capture is r_opt: the hindsight optimum's share on the reward's scale, idle 0.2. On foresight it equals the reward R.", scoreTable(R)),
    figure("frontier", R, W),
    block("Every point on the frontier", "Blind, the 331 newest battery-days. The 4B, Luna at high and low effort and Sol are the cost-matched contest's registered rows; Luna at medium effort and Beam-1.0 are descriptive runs under the same harness.", frontierTable(R)),
    block("How it was trained", `Qwen3-4B with LoRA adapters on one GPU at a time. ${link(gh("results/train"), "Every script, log and pip freeze is committed")}; the adapters are not published.`, `<ol class="steps">
      <li><b>One prompt, one completion, an exact reward.</b>The env's own one-shot prompt (the battery and the day's prices, or at the blind tier the week before), a completion that ends in a <code>submit_schedule</code> call, and <code>gridsim_core.trl.reward_fn</code>, the env's own grader: the schedule against the dynamic program's optimum, in under a millisecond.</li>
      <li><b>SFT on solver labels.</b>The DP gives every training day's optimal schedule for free. Ten thousand of them, each with a rationale that tracks the state of charge and states the DP's buy-and-sell rule, took the 4B from 0.06 to 0.84 with no RL (run 2).</li>
      <li><b>GRPO in TRL stalls on a confident policy.</b>TRL's GRPOTrainer with colocated vLLM lifted run 1's weaker warm start. On SFT-10k about half the days gave eight identical rollouts and no gradient (run 2).</li>
      <li><b>Exact advantages instead of a group baseline.</b>Run 3 credits each hour with A_t = Q*(s_t, a_t) − V*(s_t) from the DP's value table, on the tokens of that hour's integer, in a PPO-clipped loop with a KL anchor to SFT-10k (PyTorch and PEFT, rollouts in vLLM). Held-out reward rose where GRPO's had not.</li>
      <li><b>Blind: forecast, then plan.</b>Run 4 starts from run 3, learns to write a teacher forecaster's 24-hour price forecast and the DP plan on it, then takes the same exact-advantage RL on the plan, credited against its own forecast.</li>
      <li><b>Pre-registered and out of sample.</b>Each run's plan and bars were committed before its first step. Held-out days of 2025 and ERCOT's ten newest days (18–27 October 2026) were never trained on, and every CI resamples whole days or tasks.</li></ol>`),
    block("What each run changed and what it taught", `Held-out: reward R on 200 foresight days of 2025 (runs 1 to 3), 500 unseen days of 2014–2024 (the confirmation), or blind capture on 300 days of 2025 (run 4). GPU: the box's on-demand cost; training called no API. About $${Math.round(T.gpu_usd_total)} of GPU in all, from the first 1.7B arm to run 4.`, runsTable(R)),
    figure("training", R, W),
    figure("planning", R, W),
    figure("ladder", R, W),
    block("Every policy in dollars", "Blind schedules settled at ERCOT's day-ahead prices, per MW of battery power, × 365, with day-block 95% CIs. A reply with no valid schedule settles as idle. Descriptive: computed after the results, not pre-registered.", economicsTable(R)),
    figure("regimes", R, W),
    block("Inference cost against what the decisions earn", "", `<div class="cols"><p class="note" style="margin:0">One model call per battery-day, whatever the battery's size, so the bill does not grow with MW; the value does. GPT-6.1 Sol over the trained 4B: <b>$${num(D.inference.sol_over_4b.extra_inference_usd_per_battery_yr, 2)}</b> more inference a battery-year buys about <b>$${Math.round(D.inference.sol_over_4b.decision_gap_k_usd_per_100mw_yr)}k</b> a year of better decisions per 100 MW. At grid scale, inference cost does not decide which model to run; decision quality does.</p><p class="note" style="margin:0">Training pays for itself against renting the same score: run 4's GPU bill ($${R.dollars.payback["run 4"].gpu_usd}) is repaid by its inference savings over GPT-6 Luna at high effort after about ${(Math.round(R.dollars.payback["run 4"].battery_days / 1000) * 1000).toLocaleString("en-US")} battery-days, run 3's ($${R.dollars.payback["run 3"].gpu_usd}) after about ${(Math.round(R.dollars.payback["run 3"].battery_days / 1000) * 1000).toLocaleString("en-US")}.</p></div>`),
    block("What these dollars are and aren't", "", `<ul class="caveats"><li><b>Day-ahead energy arbitrage only.</b> Hourly buys and sells settled at ERCOT's day-ahead prices at 7 hubs and 8 load zones. No real-time market and no ancillary services, where real ERCOT batteries earn much of their revenue: this is the value of the day-ahead decisions, not a battery's revenue.</li><li><b>A price-taker with perfect execution.</b> Every MWh clears at the published price, and the schedule moves no price.</li><li><b>Archetype batteries.</b> 7.5 to 225 MW, 1, 2 or 4 hours, sized from the ERCOT fleet in EIA-860. A flat degradation cost of $4 or $8 per MWh discharged on ${D.degradation_days} of the ${D.n_tasks} battery-days of 2025 and $0 on the rest; no capacity fade, O&amp;M or capital cost.</li><li><b>× 365 is a unit, not a forecast.</b> 2025's 191 days run from January to November; the newest pack is 10 days of October 2026.</li><li><b>Descriptive.</b> The dollars were computed after the results, from recorded schedules. The registered verdicts are on capture, in the training runs and the cost-matched contest.</li></ul>`),
    block("The live board", "", `<div class="live" id="live">Loading the live board…</div><p class="note">Each pass seals a 24-hour schedule for 45 batteries from GPT-6.1 Sol, GPT-6 Luna, the trained 4B and three rules, about 20 hours before ERCOT's day-ahead market closes, as a timestamped public commit. When ERCOT posts the day's prices, every schedule is settled at them. Passes run on demand. A descriptive track record, not a test.</p><p style="margin:10px 0 0"><a class="btn" href="./board.html">Open the live board →</a></p>`, "live-board"),
    block("Evidence", "", `<div class="links-grid"><div><h3>Results on the dataset</h3><ul>${[["results/train/4b-blind", "Run 4, blind"], ["results/train/4b-dpa", "Run 3, exact DP advantages"], ["results/train/4b-v2", "Run 2, SFT-10k and GRPO"], ["results/train/4b", "Run 1, GRPO"], ["results/cost-matched", "The cost-matched contest"], ["results/economics", "The economics"], ["results/beam-agent", "Beam-1.0"], ["results/overview", "This page's numbers"]].map(([p, t]) => `<li>${link(dt(p), t)}</li>`).join("")}</ul></div><div><h3>Pre-registrations</h3><ul>${[["v1-train-4b-blind", "Run 4"], ["v1-train-4b-dpa", "Run 3"], ["v1-train-4b-v2", "Run 2"], ["v1-train-4b", "Run 1"], ["v1-cost-matched", "The cost-matched contest"], ["v1-beam-agent", "Beam-1.0"], ["v1-live-board", "The live board"]].map(([p, t]) => `<li>${link(gh(`docs/prereg/${p}.md`), t)}</li>`).join("")}</ul></div><div><h3>Code and data</h3><ul><li>${link(REPO, "agentenv-gridsim-plugin")}</li><li>${link(gh("results/economics/scripts/econ.py"), "econ.py")} · ${link(gh("scripts/hub_results.py"), "hub_results.py")}</li><li>${link(DATASET, "The dataset: tasks, references, episodes")}</li><li><a href="./index.html">Replays of every run</a></li></ul></div></div>`),
  ].join("");
}

async function live() {
  try {
    const r = await fetch(`${LIVE}${LIVE.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    const b = r.ok ? await r.json() : { graded_days: [], timeline: [] };
    const sealed = (b.timeline || []).filter((t) => t.seal_commit).map((t) => t.delivery_day).sort();
    $("live").innerHTML = `<span><b>${sealed.length}</b> day${sealed.length === 1 ? "" : "s"} sealed${sealed.length ? `, the first for ${sealed[0]}` : ""}</span><span><b>${b.graded_days.length}</b> graded</span>${b.updated_utc ? `<span>updated ${b.updated_utc.slice(0, 16).replace("T", " ")} UTC</span>` : ""}`;
  } catch (e) {
    $("live").textContent = `The live board could not be loaded (${e.message}).`;
  }
}

function tips() {
  const box = $("tip");
  let pinned = null;
  const show = (el, x, y) => {
    box.innerHTML = TIPS[+el.dataset.tip];
    box.hidden = false;
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, x + 14))}px`;
    box.style.top = `${y + h + 22 > innerHeight ? Math.max(8, y - h - 14) : y + 16}px`;
  };
  addEventListener("pointermove", (e) => {
    if (pinned || e.pointerType === "touch") return;
    const el = e.target.closest?.("[data-tip]");
    if (el) show(el, e.clientX, e.clientY);
    else box.hidden = true;
  });
  addEventListener("click", (e) => {
    const el = e.target.closest?.("[data-tip]");
    pinned = el && el !== pinned ? el : null;
    if (pinned) show(el, e.clientX, e.clientY);
    else box.hidden = true;
  });
  addEventListener("keydown", (e) => e.key === "Escape" && ((pinned = null), (box.hidden = true)));
  addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (!el) return;
    const r = el.getBoundingClientRect();
    show(el, r.right, r.top);
  });
  addEventListener("scroll", () => !pinned && (box.hidden = true), { passive: true });
}

async function main() {
  let R;
  try {
    R = await (await fetch("./results.json", { cache: "no-store" })).json();
  } catch (e) {
    $("lede").textContent = `The results could not be loaded (${e.message}).`;
    return;
  }
  render(R);
  if (!EXPORT) {
    tips();
    let w = innerWidth;
    addEventListener("resize", () => {
      if (Math.abs(innerWidth - w) < 8) return;
      w = innerWidth;
      clearTimeout(main.t);
      main.t = setTimeout(() => (render(R), live()), 120);
    });
    await Promise.race([live(), new Promise((r) => setTimeout(r, 5000))]);
  }
  window.resultsReady = true;
}

main();
