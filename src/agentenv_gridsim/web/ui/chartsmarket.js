import { hourLabel, money, price } from "../data.js";
import { SEAT } from "../market.js";

const W = 560, H = 150, L = 54, R = 8, T = 10, B = 22;
const x = (h) => L + ((W - L - R) * h) / 24;

function axes(lo, hi, fmt) {
  const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
  let s = "";
  for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(0,0,0,0.07)"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#7a868e">${fmt(v)}</text>`;
  if (lo < 0 && hi > 0) s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.3)"/>`;
  for (const h of [0, 6, 12, 18, 24]) s += `<text x="${x(h)}" y="${H - 6}" font-size="10" text-anchor="middle" fill="#7a868e">${hourLabel(h)}</text>`;
  return { s, y };
}
const step = (vals, y, col, { dash = false, w = 2 } = {}) => `<polyline fill="none" stroke="${col}" stroke-width="${w}" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${vals.map((v, i) => `${x(i)},${y(v)} ${x(i + 1)},${y(v)}`).join(" ")}"/>`;
const svg = (inner) => `<svg viewBox="0 0 ${W} ${H}">${inner}<line class="ph" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#1c2329" stroke-width="1.5"/></svg>`;
const kmw = (v) => `${v > 0 ? "+" : ""}${Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v)}`;

/** The expert view of a Market Floor day: the cleared hub price against ERCOT's real day-ahead and the re-clear of
 * every real offer; seat A's awards and delivery against the anchor's; every seat's award; seat A's cash against the
 * anchor's. Linear scales. */
export function buildMarketCharts(root, d) {
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("aria-label", "Charts");
  const c = d.clear, top = Math.max(...c.hub, ...d.hubReal, ...(c.replay || [])) * 1.05;
  const pa = axes(Math.min(0, ...c.hub, ...d.hubReal), top, (v) => price(v));
  const priceSvg = svg(pa.s + c.hub.map((v, h) => `<rect x="${x(h) + 1}" y="${Math.min(pa.y(v), pa.y(0))}" width="${x(1) - x(0) - 2}" height="${Math.abs(pa.y(v) - pa.y(0))}" fill="#9fb0bc"/>`).join("") + step(d.hubReal, pa.y, "#2c3440", { dash: true }) + (c.replay ? step(c.replay, pa.y, "#c58a12", { w: 1.4 }) : "") + d.rtH.map((v, h) => `<circle cx="${x(h + 0.5)}" cy="${pa.y(Math.min(top, v))}" r="2.2" fill="#1c2329"/>`).join(""));
  const anc = d.refs.anchor?.q_mw;
  const ba = axes(-d.P, d.P, kmw);
  const battSvg = svg(ba.s + d.hours.map((z, h) => (Math.abs(z.award) > 0.5 ? `<rect x="${x(h) + 1.5}" y="${Math.min(ba.y(0), ba.y(z.award))}" width="${x(1) - x(0) - 3}" height="${Math.abs(ba.y(z.award) - ba.y(0))}" fill="${z.award > 0 ? "#ffa62b" : "#2fd3ff"}" opacity="0.9"/>` : "")).join("") + step(d.hours.map((z) => z.exec), ba.y, "#1c2329", { w: 1.4 }) + (anc ? step(anc, ba.y, "#7a868e", { dash: true, w: 1.5 }) : ""));
  const seats = Object.keys(d.aw);
  const lim = Math.max(1, ...seats.flatMap((s) => d.aw[s].map(Math.abs)));
  const sa = axes(-lim, lim, kmw);
  const seatSvg = svg(sa.s + seats.map((s) => step(d.aw[s], sa.y, SEAT[s].color, { w: s === "A" ? 2.4 : 1.6 })).join(""));
  const ancCash = anc ? cumAnchor(d, anc) : null;
  const all = [0, ...d.agentCum, ...(ancCash || [])];
  const ma = axes(Math.min(...all), Math.max(...all) * 1.05 || 1, (v) => money(v));
  const cashSvg = svg(ma.s + `<polyline fill="none" stroke="#2c3440" stroke-width="2" points="${[0, ...d.agentCum].map((v, i) => `${x(i)},${ma.y(v)}`).join(" ")}"/>` + (ancCash ? `<polyline fill="none" stroke="#7a868e" stroke-width="2" stroke-dasharray="5 4" points="${[0, ...ancCash].map((v, i) => `${x(i)},${ma.y(v)}`).join(" ")}"/>` : ""));
  const legend = seats.map((s) => `<span style="color:${SEAT[s].color}">■</span> ${s} ${SEAT[s].name}`).join(" · ");
  el.innerHTML = `<button class="x" aria-label="Close charts">×</button><h3>Charts</h3><div class="sub">${d.task.date} · ERCOT hub average · seat A ${d.P} MW / ${Math.round(d.E)} MWh · η ${d.eta} · wear $${d.task.seat_A.c_deg}/MWh · ${d.tier} · ${d.watches.length} watches · v5 preview</div>
    <figure><figcaption>Cleared hub price by hour (bars), ERCOT's real day-ahead hub price (dashed), the re-clear of every real offer (gold), real time (dots), $/MWh</figcaption>${priceSvg}</figure>
    <figure><figcaption>Seat A's day-ahead awards, MW (+ sells), what it delivered (line) and the disclosure anchor's self-schedule (dashed)</figcaption>${battSvg}</figure>
    <figure><figcaption>Every seat's award, MW (+ sells, − buys): ${legend}</figcaption>${seatSvg}</figure>
    <figure><figcaption>Seat A's cumulative cash, $ (solid), and the anchor's day-ahead cash on its own clear less wear (dashed)</figcaption>${cashSvg}</figure>`;
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

function cumAnchor(d, q) {
  const hub = d.refs.anchor?.hub_usd || d.clear.hub, c = d.task.seat_A.c_deg;
  let acc = 0;
  return q.map((v, h) => (acc += v * hub[h] - c * Math.max(0, v)));
}
