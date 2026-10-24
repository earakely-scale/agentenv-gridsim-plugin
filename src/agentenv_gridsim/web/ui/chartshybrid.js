import { hourLabel, money, price } from "../data.js";
import { PROD, UP } from "../hybrid.js";

const W = 560, H = 150, L = 50, R = 8, T = 10, B = 22;
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

/** The expert view of a solar-plus-storage day: RT against DA prices, the battery against the anchor's book over the
 * PV, SoC inside its reserve bands, the reserve book by product, and the cash race. Linear scales. */
export function buildHybridCharts(root, d) {
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("aria-label", "Charts");
  const da = d.prices, rt = d.rt, hs = d.hours;
  const cap = Math.max(...da) * 3 + 50;
  const top = Math.min(Math.max(...rt, ...da), cap);
  const pa = axes(Math.min(0, ...rt, ...da), top * 1.05, (v) => price(v));
  const pk = rt.indexOf(Math.max(...rt));
  const over = rt[pk] > top * 1.05 ? `<text x="${Math.min(x(pk + 0.5), W - R - 60)}" y="${T + 9}" font-size="10" text-anchor="middle" fill="#cf3e33">peak ${price(rt[pk])} (off scale)</text>` : "";
  const priceSvg = svg(pa.s + rt.map((v, h) => `<rect x="${x(h) + 1}" y="${Math.min(pa.y(Math.min(v, top * 1.05)), pa.y(0))}" width="${x(1) - x(0) - 2}" height="${Math.abs(pa.y(Math.min(v, top * 1.05)) - pa.y(0))}" fill="${v < 0 ? "#9a7fd0" : "#9fb0bc"}"/>`).join("") + step(da, pa.y, "#2c3440", { dash: true }) + over);
  const P = d.P, pvm = Math.max(P, d.pvMwac);
  const ba = axes(-P, pvm, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const anchor = d.ep.references?.anchor?.book?.energy;
  const pvArea = `<polygon fill="#efe0a8" opacity="0.7" points="${x(0)},${ba.y(0)} ${hs.map((z, h) => `${x(h)},${ba.y(z.pvAvail)} ${x(h + 1)},${ba.y(z.pvAvail)}`).join(" ")} ${x(24)},${ba.y(0)}"/>`;
  const battSvg = svg(ba.s + pvArea + hs.map((z, h) => (Math.abs(z.batt) > 0.05 ? `<rect x="${x(h) + 1.5}" y="${Math.min(ba.y(0), ba.y(z.batt))}" width="${x(1) - x(0) - 3}" height="${Math.abs(ba.y(z.batt) - ba.y(0))}" fill="${z.batt > 0 ? "#ffa62b" : "#2fd3ff"}" opacity="0.9"/>` : "")).join("") + (anchor ? step(anchor.map(Number), ba.y, "#2c3440", { dash: true, w: 1.5 }) : ""));
  const sa = axes(0, d.E, (v) => `${Math.round(v)}`);
  const floor = hs.map((z) => Math.min(d.E, z.rUp)), head = hs.map((z) => d.E - Math.min(d.E, z.rDn));
  const bands = `<polygon fill="url(#hp-fwd)" points="${x(0)},${sa.y(0)} ${floor.map((v, h) => `${x(h)},${sa.y(v)} ${x(h + 1)},${sa.y(v)}`).join(" ")} ${x(24)},${sa.y(0)}"/><polygon fill="url(#hp-dots)" points="${x(0)},${sa.y(d.E)} ${head.map((v, h) => `${x(h)},${sa.y(v)} ${x(h + 1)},${sa.y(v)}`).join(" ")} ${x(24)},${sa.y(d.E)}"/>`;
  const socPts = d.ep.soc_path.map((s, i) => `${x(i)},${sa.y(s)}`).join(" ");
  const an = d.lanes.find((l) => l.k === "anchor");
  const socSvg = svg(sa.s + bands + `<line x1="${L}" x2="${W - R}" y1="${sa.y(d.site.bess.s_end_min_mwh)}" y2="${sa.y(d.site.bess.s_end_min_mwh)}" stroke="#d08a00" stroke-dasharray="3 3"/>` + (an ? `<polyline fill="none" stroke="rgba(28,35,41,0.45)" stroke-width="1.5" stroke-dasharray="4 3" points="${an.soc.map((s, i) => `${x(i)},${sa.y(s)}`).join(" ")}"/>` : "") + `<polyline fill="none" stroke="#22b866" stroke-width="2" points="${socPts}"/>`);
  const aa = axes(-P, P, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const asSvg = svg(aa.s + hs.map((z, h) => {
    let up = 0, s = "";
    for (const k of UP.filter((kk) => d.offered.includes(kk))) {
      const v = z.awards[k];
      if (v > 0.05) s += `<rect x="${x(h) + 2}" y="${aa.y(up + v)}" width="${x(1) - x(0) - 4}" height="${aa.y(up) - aa.y(up + v)}" fill="url(#hp-${PROD[k].hatch})" stroke="rgba(28,35,41,0.5)" stroke-width="0.6"/>`;
      up += v;
    }
    const rd = z.awards.regdn;
    if (rd > 0.05 && d.offered.includes("regdn")) s += `<rect x="${x(h) + 2}" y="${aa.y(0)}" width="${x(1) - x(0) - 4}" height="${aa.y(-rd) - aa.y(0)}" fill="url(#hp-dots)" stroke="rgba(28,35,41,0.5)" stroke-width="0.6"/>`;
    return s;
  }).join(""));
  const series = [["agent", d.agentCum, "#2c3440", false], ...d.lanes.map((l) => [l.k, l.cum, l.k === "hind" ? "#1d9a57" : l.k === "anchor" ? "#7a868e" : "#c9a24d", true])];
  const all = series.flatMap((s) => s[1]).concat([0]);
  const ma = axes(Math.min(...all), Math.max(...all) * 1.05 || 1, (v) => money(v));
  const cashSvg = svg(ma.s + series.map(([, c, col, dash]) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${[0, ...c].map((v, i) => `${x(i)},${ma.y(v)}`).join(" ")}"/>`).join(""));
  const glyphs = d.offered.map((k) => `${PROD[k].glyph} ${PROD[k].name}`).join(", ");
  el.innerHTML = `<button class="x" aria-label="Close charts">×</button><h3>Charts</h3><div class="sub">${d.task.settlement_point} · ${d.task.date} · PV ${d.site.pv_mwac} MWac · ${d.P} MW / ${d.E} MWh · η ${d.eta} · degradation $${d.site.bess.c_deg}/MWh · meter ${Math.round(d.L)} MW · ${d.watches.length} watches · v3 preview</div>
    <figure><figcaption>Real-time price by the hour (bars) and the day-ahead price (dashed), $/MWh</figcaption>${priceSvg}</figure>
    <figure><figcaption>Battery MW as executed (bars; + discharges) over the PV available (cream), against the rolling anchor's book (dashed)</figcaption>${battSvg}</figure>
    <figure><figcaption>State of charge, MWh (green), the anchor's (dashed), inside the reserve bands: up-reserves need charge below (hatched), RegDn needs room above (dotted); orange is the end obligation</figcaption>${socSvg}</figure>
    ${d.offered.length ? `<figure><figcaption>Reserve awards, MW: up products stacked above, RegDn below (${glyphs})</figcaption>${asSvg}</figure>` : ""}
    <figure><figcaption>Cumulative cash, $: the agent (solid), the rolling anchor (grey), the energy-only anchor and AS-hog (gold), hindsight (green)</figcaption>${cashSvg}</figure>`;
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
