import { hourLabel, money, price } from "../data.js";

const W = 560, H = 150, L = 46, R = 8, T = 10, B = 22;
const x = (h) => L + ((W - L - R) * h) / 24;

function axes(lo, hi, fmt) {
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
  let s = "";
  for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(0,0,0,0.07)"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#7a868e">${fmt(v)}</text>`;
  if (lo < 0 && hi > 0) s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.3)"/>`;
  for (const h of [0, 6, 12, 18, 24]) s += `<text x="${x(h)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#7a868e">${hourLabel(h)}</text>`;
  return { s, y };
}

const step = (vals, y) => vals.map((v, h) => `${x(h)},${y(v)} ${x(h + 1)},${y(v)}`).join(" ");
const svg = (inner) => `<svg viewBox="0 0 ${W} ${H}">${inner}<line class="ph" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#1c2329" stroke-width="1.5"/></svg>`;

/** The expert view behind the Charts button: price, schedule against the optimum, SoC and cumulative cash. */
export function buildCharts(root, d) {
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("aria-label", "Charts");
  const p = d.prices;
  const pa = axes(Math.min(0, ...p), Math.max(...p) * 1.05, (v) => price(v));
  const priceSvg = svg(pa.s + `<polyline fill="none" stroke="#3a4651" stroke-width="2" points="${step(p, pa.y)}"/>` +
    p.map((v, h) => (v < 0 ? `<rect x="${x(h)}" y="${pa.y(0)}" width="${x(1) - x(0)}" height="${pa.y(v) - pa.y(0)}" fill="#9a7fd0" opacity="0.5"/>` : "")).join(""));
  const k = Math.max(d.b.k_ch, d.b.k_dis) * d.b.unit_mwh;
  const sa = axes(-k, k, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const bar = (vals, dx, col, op) => vals.map((a, h) => {
    if (!a) return "";
    const v = a * d.b.unit_mwh, y0 = sa.y(0), y1 = sa.y(v);
    return `<rect x="${x(h) + dx}" y="${Math.min(y0, y1)}" width="${(x(1) - x(0)) / 2 - 1}" height="${Math.abs(y1 - y0)}" fill="${col}" opacity="${op}"/>`;
  }).join("");
  const opt = d.ghosts.opt?.executed;
  const schedSvg = svg(sa.s + bar(d.actions.map((a, h) => (d.hours[h].mode === "grey" || d.hours[h].mode === "violation" ? d.hours[h].intended : a)), 0, "#2c3440", 0.85) + (opt ? bar(opt, (x(1) - x(0)) / 2, "#9aa3a9", 0.7) : "") +
    d.actions.map((a, h) => (a < 0 ? `<rect x="${x(h)}" y="${H - B - 3}" width="${(x(1) - x(0)) / 2 - 1}" height="3" fill="#2fd3ff"/>` : a > 0 ? `<rect x="${x(h)}" y="${H - B - 3}" width="${(x(1) - x(0)) / 2 - 1}" height="3" fill="#ffa62b"/>` : "")).join(""));
  const N = d.b.soc_levels;
  const ca = axes(0, N * d.b.unit_mwh, (v) => `${Math.round(v)}`);
  const socLine = (soc, col, dash) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${soc.map((s, h) => `${x(h)},${ca.y(s * d.b.unit_mwh)}`).join(" ")}"/>`;
  const socSvg = svg(ca.s + `<line x1="${L}" x2="${W - R}" y1="${ca.y(d.b.s_end_min * d.b.unit_mwh)}" y2="${ca.y(d.b.s_end_min * d.b.unit_mwh)}" stroke="#d08a00" stroke-dasharray="3 3"/>` + (d.ghosts.opt ? socLine(d.ghosts.opt.soc, "#9aa3a9", true) : "") + socLine(d.soc, "#22b866"));
  const series = [["agent", d.agentCum, "#2c3440", false], ["opt", d.ghosts.opt?.cum, "#9aa3a9", true], ["greedy", d.ghosts.greedy?.cum, "#c9a24d", true], ["threshold", d.ghosts.threshold?.cum, "#7db1c4", true]].filter((s) => s[1]);
  const all = series.flatMap((s) => s[1]).concat([0, d.ep.profit_usd ?? 0]);
  const ma = axes(Math.min(...all), Math.max(...all) * 1.05 || 1, (v) => money(v));
  const cashSvg = svg(ma.s + series.map(([, c, col, dash]) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${[0, ...c].map((v, h) => `${x(h)},${ma.y(v)}`).join(" ")}"/>`).join(""));
  el.innerHTML = `<button class="x" aria-label="Close charts">×</button><h3>Charts</h3><div class="sub">${d.task.settlement_point} · ${d.task.date} · ${d.b.p_dis_mw} MW / ${d.b.energy_mwh} MWh · η ${d.b.eta} · degradation $${d.b.c_deg}/MWh · cycle cap ${d.b.cycle_cap_units} units</div>
    <figure><figcaption>Day-ahead price, $/MWh (purple: negative)</figcaption>${priceSvg}</figure>
    <figure><figcaption>Schedule, MW: the agent (dark) against the DP optimum (grey); + discharges, − charges</figcaption>${schedSvg}</figure>
    <figure><figcaption>State of charge, MWh: the agent (green) and the optimum (dashed); the orange line is the end-of-day obligation</figcaption>${socSvg}</figure>
    <figure><figcaption>Cumulative cash, $: agent (solid), optimum, greedy and threshold (dashed)</figcaption>${cashSvg}</figure>`;
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
      const px = x(Math.max(0, Math.min(24, t)));
      for (const l of phs) l.setAttribute("x1", px), l.setAttribute("x2", px);
    },
  };
}
