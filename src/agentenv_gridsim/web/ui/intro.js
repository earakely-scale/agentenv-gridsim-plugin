import { hourLabel, money, price } from "../data.js";
import { modelName } from "./hud.js";

function strip(vals, { w = 560, h = 40, lo, hi, col = "#3a4651", fill = false } = {}) {
  const y = (v) => h - 3 - ((v - lo) / (hi - lo || 1)) * (h - 6);
  const pts = vals.map((v, i) => `${(i / (vals.length - 1)) * w},${y(v)}`).join(" ");
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${lo < 0 ? `<line x1="0" x2="${w}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.2)"/>` : ""}${fill ? `<polygon fill="${col}" opacity="0.15" points="0,${h} ${pts} ${w},${h}"/>` : ""}<polyline fill="none" stroke="${col}" stroke-width="2" points="${pts}"/></svg>`;
}

/** Before the day: what the agent saw (all 24 prices, or for the blind tier D-1 and the week before), its practice
 * checks and its submission; the real day is revealed when the replay starts. */
export function buildIntro(root, d) {
  const el = document.createElement("section");
  el.className = "card intro";
  const blind = d.ep.tier === "blind" && d.task.blind;
  const series = blind ? [d.task.blind.dam_prev_day, ...(d.task.blind.dam_prev_7d || [])] : [d.prices];
  const flat = series.flat().concat(d.prices);
  const lo = Math.min(0, ...flat), hi = Math.max(...flat);
  const checks = d.checks.length;
  const sub = d.ep.steps?.find((s) => s.tool === "submit_schedule");
  el.innerHTML = `<h5>Before the day · ${d.dateLabel} · ${d.task.settlement_point}</h5>
    <p><b>${modelName(d.ep.model)}</b> runs a ${d.b.p_dis_mw} MW / ${d.b.energy_mwh} MWh battery. It starts ${Math.round((d.b.s0 / d.b.soc_levels) * 100)}% full${d.b.s_end_min > 0 ? ` and must end at least ${Math.round((d.b.s_end_min / d.b.soc_levels) * 100)}% full, or buy the shortfall back at the day's top price` : " and has no end-of-day charge to keep"}.</p>
    ${blind ? `<p><b>Blind tier:</b> it does not see today's prices. It plans from yesterday's day-ahead prices and the week before; today's prices are revealed only after it submits.</p>
      <div class="strip"><span>Yesterday</span>${strip(d.task.blind.dam_prev_day, { lo: Math.min(0, ...d.task.blind.dam_prev_day), hi: Math.max(...d.task.blind.dam_prev_day), col: "#3a4651", fill: true })}<em>peak ${price(Math.max(...d.task.blind.dam_prev_day))}</em></div>
      ${(d.task.blind.dam_prev_7d || []).map((v, i, a) => `<div class="strip faint"><span>${a.length - i} days ago</span>${strip(v, { lo: Math.min(0, ...v), hi: Math.max(...v), h: 22, col: "#8f9aa2" })}<em>peak ${price(Math.max(...v))}</em></div>`).join("")}
      <div class="strip reveal"><span>Today</span><div class="hidden-day">revealed after it submits</div>${strip(d.prices, { lo: Math.min(0, ...d.prices), hi: Math.max(...d.prices), col: "#d9820b", fill: true })}<em>peak ${price(Math.max(...d.prices))}</em></div>
      <p class="dim" style="font-size:11.5px">Each strip is scaled to its own day.</p>`
    : `<p>It sees all 24 of the day's hourly prices, from ${price(Math.min(...d.prices))} to ${price(Math.max(...d.prices))}/MWh (peak at ${hourLabel(d.peakH)}).</p>
      <div class="strip"><span>Today</span>${strip(d.prices, { lo, hi, col: "#3a4651", fill: true })}<em>peak ${price(Math.max(...d.prices))}</em></div>`}
    <p class="dim">${checks ? `It tried ${checks} practice plan${checks > 1 ? "s" : ""} with check_schedule, then submitted.` : "It submitted its plan without a practice check."}${sub?.output?.profit_usd != null ? ` The submission settles at ${money(sub.output.profit_usd)}.` : ""}</p>`;
  root.append(el);
  return {
    update(t) {
      el.hidden = t >= 0;
      el.classList.toggle("revealed", t > -0.6);
    },
  };
}
