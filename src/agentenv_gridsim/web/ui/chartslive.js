import { hourLabel, money, price } from "../data.js";

const W = 560, H = 150, L = 50, R = 8, T = 10, B = 22;
const x = (i) => L + ((W - L - R) * i) / 96;

function axes(lo, hi, fmt) {
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
  let s = "";
  for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(0,0,0,0.07)"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#7a868e">${fmt(v)}</text>`;
  if (lo < 0 && hi > 0) s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.3)"/>`;
  for (const h of [0, 6, 12, 18, 24]) s += `<text x="${x(h * 4)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#7a868e">${hourLabel(h)}</text>`;
  return { s, y };
}
const line = (vals, y, col, { dash = false, w = 2, step = 1 } = {}) => `<polyline fill="none" stroke="${col}" stroke-width="${w}" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${vals.map((v, i) => `${x(i * step)},${y(v)} ${x((i + 1) * step)},${y(v)}`).join(" ")}"/>`;
const svg = (inner) => `<svg viewBox="0 0 ${W} ${H}">${inner}<line class="ph" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#1c2329" stroke-width="1.5"/></svg>`;

/** The expert view of a live day: real-time against day-ahead prices, the schedule against the anchor's, SoC, and the
 * cash race against naive, the anchor and hindsight. Linear scales; a spike past the axis is labelled. */
export function buildLiveCharts(root, d) {
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("aria-label", "Charts");
  const da = d.prices, rt = d.rt;
  const cap = Math.max(...da) * 3 + 50;
  const top = Math.min(Math.max(...rt, ...da), cap);
  const pa = axes(Math.min(0, ...rt, ...da), top * 1.05, (v) => price(v));
  const clip = rt.map((v) => Math.min(v, top * 1.05));
  const over = rt.map((v, i) => (v > top * 1.05 ? `<text x="${x(i + 0.5)}" y="${T + 9}" font-size="9.5" text-anchor="middle" fill="#cf3e33">${price(v)}</text>` : "")).join("");
  const priceSvg = svg(pa.s + clip.map((v, i) => `<rect x="${x(i)}" y="${Math.min(pa.y(v), pa.y(0))}" width="${x(1) - x(0) - 0.6}" height="${Math.abs(pa.y(v) - pa.y(0))}" fill="${v < 0 ? "#9a7fd0" : "#9fb0bc"}"/>`).join("") + line(da, pa.y, "#2c3440", { dash: true, step: 4 }) + over);
  const k = Math.max(d.b.k_ch, d.b.k_dis) * d.b.unit_mwh * 4;
  const sa = axes(-k, k, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const anchor = d.lanes.find((l) => l.k === "anchor");
  const mw = (a) => a * d.b.unit_mwh * 4;
  const schedSvg = svg(sa.s + d.executed.map((a, i) => (a ? `<rect x="${x(i)}" y="${Math.min(sa.y(0), sa.y(mw(a)))}" width="${x(1) - x(0) - 0.6}" height="${Math.abs(sa.y(mw(a)) - sa.y(0))}" fill="${a > 0 ? "#ffa62b" : "#2fd3ff"}" opacity="0.9"/>` : "")).join("") + (anchor ? line(anchor.sched.map(mw), sa.y, "#2c3440", { dash: true, w: 1.5 }) : ""));
  const N = d.b.soc_levels, u = d.b.unit_mwh;
  const ca = axes(0, N * u, (v) => `${Math.round(v)}`);
  const socPts = (soc) => soc.map((s, i) => `${x(i)},${ca.y(s * u)}`).join(" ");
  const socSvg = svg(ca.s + `<line x1="${L}" x2="${W - R}" y1="${ca.y(d.b.s_end_min * u)}" y2="${ca.y(d.b.s_end_min * u)}" stroke="#d08a00" stroke-dasharray="3 3"/><polyline fill="none" stroke="#22b866" stroke-width="2" points="${socPts(d.soc)}"/>`);
  const series = [["agent", d.agentCum, "#2c3440", false], ...d.lanes.map((l) => [l.k, l.cum, l.k === "hind" ? "#1d9a57" : l.k === "anchor" ? "#7a868e" : "#c9a24d", true])];
  const all = series.flatMap((s) => s[1]).concat([0]);
  const ma = axes(Math.min(...all), Math.max(...all) * 1.05 || 1, (v) => money(v));
  const cashSvg = svg(ma.s + series.map(([, c, col, dash]) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${[0, ...c].map((v, i) => `${x(i)},${ma.y(v)}`).join(" ")}"/>`).join(""));
  el.innerHTML = `<button class="x" aria-label="Close charts">×</button><h3>Charts</h3><div class="sub">${d.task.settlement_point} · ${d.task.date} · ${d.b.p_dis_mw} MW / ${d.b.energy_mwh} MWh · η ${d.b.eta} · degradation $${d.b.c_deg}/MWh · ${d.watches.length} watches · v2 preview</div>
    <figure><figcaption>Real-time price by 15 minutes (bars) and the day-ahead price by the hour (dashed), $/MWh</figcaption>${priceSvg}</figure>
    <figure><figcaption>Executed schedule, MW (bars), against the rolling anchor's (dashed); + discharges, − charges</figcaption>${schedSvg}</figure>
    <figure><figcaption>State of charge, MWh; the orange line is the end-of-day obligation</figcaption>${socSvg}</figure>
    <figure><figcaption>Cumulative two-settlement cash, $: the agent (solid), naive (gold), the anchor (grey) and hindsight (green)</figcaption>${cashSvg}</figure>`;
  root.append(el);
  const phs = [...el.querySelectorAll(".ph")];
  el.querySelector(".x").addEventListener("click", () => toggle(false));
  function toggle(on = !el.classList.contains("open")) {
    el.classList.toggle("open", on);
    return on;
  }
  return {
    toggle,
    update(t) {
      if (!el.classList.contains("open")) return;
      const px = x(Math.max(0, Math.min(24, t)) * 4);
      for (const l of phs) l.setAttribute("x1", px), l.setAttribute("x2", px);
    },
  };
}
