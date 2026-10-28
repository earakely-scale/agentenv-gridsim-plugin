import { money, price } from "../data.js";
import { whenText } from "../forecast.js";
import { PROD, UP } from "../hybrid.js";

const W = 560, H = 150, L = 54, R = 8, T = 10, B = 22;

/** The expert view of a Weather Front window, on linear scales over its 48 or 72 hours: real-time against
 * day-ahead prices with the guide's P50 at each gate; how the guide's forecast for the window's dearest hour moved
 * run by run; load and temperature, every run against what happened; the battery against its DAM position over the
 * PV; SoC inside its reserve bands; reserve awards; and the cash race. */
export function buildForecastCharts(root, d) {
  const N = d.H, x = (h) => L + ((W - L - R) * h) / N;
  const axes = (lo, hi, fmt) => {
    const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
    let s = "";
    for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(0,0,0,0.07)"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#7a868e">${fmt(v)}</text>`;
    if (lo < 0 && hi > 0) s += `<line x1="${L}" x2="${W - R}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.3)"/>`;
    for (let k = 0; k < d.n; k++) s += `<line x1="${x(24 * k)}" x2="${x(24 * k)}" y1="${T}" y2="${H - B}" stroke="rgba(0,0,0,0.12)"/><text x="${x(24 * k) + 3}" y="${H - 6}" font-size="10" fill="#7a868e">${d.dayName(k)}</text>`;
    return { s, y };
  };
  const step = (vals, y, col, { dash = false, w = 2, op = 1 } = {}) => `<polyline fill="none" stroke="${col}" stroke-opacity="${op}" stroke-width="${w}" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${vals.map((v, i) => (v == null ? "" : `${x(i)},${y(v)} ${x(i + 1)},${y(v)}`)).join(" ")}"/>`;
  const svg = (inner) => `<svg viewBox="0 0 ${W} ${H}">${inner}<line class="ph" x1="0" x2="0" y1="${T}" y2="${H - B}" stroke="#1c2329" stroke-width="1.5"/></svg>`;
  const el = document.createElement("aside");
  el.className = "drawer";
  el.setAttribute("aria-label", "Charts");
  const da = d.prices, rt = d.rt, hs = d.hours, pt = d.task.settlement_point;
  const ser = (v, f) => Array.from({ length: N }, (_, h) => v?.fields[f]?.[h - v.h0] ?? null);

  const cap = Math.max(...da) * 3 + 50;
  const top = Math.min(Math.max(...rt, ...da), cap);
  const pa = axes(Math.min(0, ...rt, ...da), top * 1.05, (v) => price(v));
  const gates = d.watches.filter((w) => w.gate != null).map((w) => ser(d.vint.latest("price", pt, w.t), "da_p50").map((v, h) => (Math.floor(h / 24) === w.gate ? v : null)));
  const gp = Array.from({ length: N }, (_, h) => gates.map((g) => g[h]).find((v) => v != null) ?? null);
  const pk = rt.indexOf(Math.max(...rt));
  const over = rt[pk] > top * 1.05 ? `<text x="${Math.min(x(pk + 0.5), W - R - 60)}" y="${T + 9}" font-size="10" text-anchor="middle" fill="#cf3e33">peak ${price(rt[pk])} (off scale)</text>` : "";
  const clip = (v) => (v == null ? null : Math.min(v, top * 1.05));
  const priceSvg = svg(pa.s + rt.map((v, h) => `<rect x="${x(h) + 0.5}" y="${Math.min(pa.y(clip(v)), pa.y(0))}" width="${x(1) - x(0) - 1}" height="${Math.abs(pa.y(clip(v)) - pa.y(0))}" fill="${v < 0 ? "#9a7fd0" : "#9fb0bc"}"/>`).join("") + step(da, pa.y, "#2c3440", { dash: true, w: 1.6 }) + step(gp.map(clip), pa.y, "#3a4f66", { w: 1.4, op: 0.8 }) + over);

  const dh = da.indexOf(Math.max(...da));
  const runs = d.vint.all("price", pt).map((v) => ({ t: v.rev, p: v.fields.rt_p50?.[dh - v.h0], q: v.fields.da_p50?.[dh - v.h0], lo: v.fields.da_p10?.[dh - v.h0], hi: v.fields.da_p90?.[dh - v.h0] })).filter((r) => r.q != null);
  let driftSvg = "";
  if (runs.length > 1) {
    const t0 = Math.min(d.t0, runs[0].t), t1 = Math.max(dh + 1, runs.at(-1).t);
    const xr = (t) => L + ((W - L - R) * (t - t0)) / (t1 - t0 || 1);
    const vals = runs.flatMap((r) => [r.lo, r.hi, r.q]).concat([da[dh]]).filter((v) => v != null);
    const lo = Math.min(0, ...vals), hi = Math.max(...vals) * 1.08;
    const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo || 1));
    let s = "";
    for (const v of [lo, (lo + hi) / 2, hi]) s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="rgba(0,0,0,0.07)"/><text x="${L - 6}" y="${y(v) + 4}" font-size="10" text-anchor="end" fill="#7a868e">${price(v)}</text>`;
    for (let k = 0; k <= d.n; k++) if (24 * k - 14 >= t0 && 24 * k - 14 <= t1) s += `<line x1="${xr(24 * k - 14)}" x2="${xr(24 * k - 14)}" y1="${T}" y2="${H - B}" stroke="rgba(176,105,14,0.4)" stroke-dasharray="2 3"/><text x="${xr(24 * k - 14) + 3}" y="${T + 9}" font-size="9.5" fill="#8a5200">DAM gate</text>`;
    s += `<polygon fill="rgba(58,79,102,0.14)" points="${runs.map((r) => `${xr(r.t)},${y(r.hi ?? r.q)}`).join(" ")} ${[...runs].reverse().map((r) => `${xr(r.t)},${y(r.lo ?? r.q)}`).join(" ")}"/>`;
    s += `<polyline fill="none" stroke="#3a4f66" stroke-width="2" points="${runs.map((r) => `${xr(r.t)},${y(r.q)}`).join(" ")}"/>`;
    s += runs.map((r) => `<circle cx="${xr(r.t)}" cy="${y(r.q)}" r="2.4" fill="#3a4f66"/>`).join("");
    s += `<line x1="${L}" x2="${W - R}" y1="${y(da[dh])}" y2="${y(da[dh])}" stroke="#1c2329" stroke-dasharray="5 3"/><text x="${W - R - 4}" y="${y(da[dh]) - 4}" font-size="10" text-anchor="end" fill="#1c2329">cleared ${price(da[dh])}</text>`;
    s += `<text x="${L + 4}" y="${H - 6}" font-size="10" fill="#7a868e">issued ${whenText(d, t0 * 60)}</text><text x="${W - R}" y="${H - 6}" font-size="10" text-anchor="end" fill="#7a868e">${whenText(d, t1 * 60)}</text>`;
    driftSvg = `<svg viewBox="0 0 ${W} ${H}">${s}</svg>`;
  }

  const ld = d.vint.all("load", "system");
  let loadSvg = "";
  if (ld.length) {
    const act = d.task.actuals?.load_mw ? Array.from({ length: N }, (_, h) => d.task.actuals.load_mw[Math.round(h - d.tOf(d.task.actuals.start))] ?? null) : null;
    const off = Array(N).fill(null);
    for (const v of d.vint.all("load_official", "system")) v.fields.mw.forEach((m, i) => v.h0 + i >= 0 && v.h0 + i < N && (off[v.h0 + i] = m));
    const vals = ld.flatMap((v) => ser(v, "mw")).concat(act || [], off).filter((v) => v != null);
    const la = axes(Math.min(...vals) * 0.96, Math.max(...vals) * 1.03, (v) => `${(v / 1000).toFixed(0)} GW`);
    loadSvg = svg(la.s + ld.map((v, i) => step(ser(v, "mw"), la.y, "#3a4f66", { w: 1, op: 0.15 + (0.6 * (i + 1)) / ld.length })).join("") + step(off, la.y, "#b5487a", { dash: true, w: 1.5 }) + (act ? step(act, la.y, "#1c2329", { w: 2 }) : ""));
  }

  let tempSvg = "";
  const wv = d.vint.source === "synthetic" ? [] : d.vint.all("weather", d.task.weather_point);
  if (wv.length || d.wx) {
    const obs = d.wx ? Array.from({ length: N }, (_, h) => {
      const i = Math.round((h + 0.5 - d.wx.t0) / d.wx.dt);
      return d.wx.temp[i] != null ? (d.wx.temp[i] * 9) / 5 + 32 : null;
    }) : [];
    const vals = wv.flatMap((v) => ser(v, "t2m_f")).concat(obs).filter((v) => v != null);
    const ta = axes(Math.min(...vals) - 2, Math.max(...vals) + 2, (v) => `${Math.round(v)} °F`);
    const fr = d.front ? `<line x1="${x(d.front.t)}" x2="${x(d.front.t)}" y1="${T}" y2="${H - B}" stroke="#3d6fb6" stroke-width="1.5"/><text x="${x(d.front.t) + 4}" y="${T + 10}" font-size="10" fill="#3d6fb6">cold front</text>` : "";
    tempSvg = svg(ta.s + wv.map((v, i) => step(ser(v, "t2m_f"), ta.y, "#3a4f66", { w: 1, op: 0.12 + (0.5 * (i + 1)) / wv.length })).join("") + step(obs, ta.y, "#1c2329", { w: 2 }) + fr);
  }

  const P = d.P, pvm = Math.max(P, d.pvMwac);
  const ba = axes(-P, pvm, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const eda = d.snaps.at(-1).eda;
  const pvArea = d.lite ? "" : `<polygon fill="#efe0a8" opacity="0.7" points="${x(0)},${ba.y(0)} ${hs.map((z, h) => `${x(h)},${ba.y(z.pvAvail)} ${x(h + 1)},${ba.y(z.pvAvail)}`).join(" ")} ${x(N)},${ba.y(0)}"/>`;
  const battSvg = svg(ba.s + pvArea + hs.map((z, h) => (Math.abs(z.batt) > 0.05 ? `<rect x="${x(h) + 0.5}" y="${Math.min(ba.y(0), ba.y(z.batt))}" width="${x(1) - x(0) - 1}" height="${Math.abs(ba.y(z.batt) - ba.y(0))}" fill="${z.batt > 0 ? "#ffa62b" : "#2fd3ff"}" opacity="0.9"/>` : "")).join("") + step(eda, ba.y, "#1c2329", { w: 1.3 }));

  const sa = axes(0, d.E, (v) => `${Math.round(v)}`);
  const floor = hs.map((z) => Math.min(d.E, z.rUp)), head = hs.map((z) => d.E - Math.min(d.E, z.rDn));
  const bands = `<polygon fill="url(#hp-fwd)" points="${x(0)},${sa.y(0)} ${floor.map((v, h) => `${x(h)},${sa.y(v)} ${x(h + 1)},${sa.y(v)}`).join(" ")} ${x(N)},${sa.y(0)}"/><polygon fill="url(#hp-dots)" points="${x(0)},${sa.y(d.E)} ${head.map((v, h) => `${x(h)},${sa.y(v)} ${x(h + 1)},${sa.y(v)}`).join(" ")} ${x(N)},${sa.y(d.E)}"/>`;
  const an = d.lanes.find((l) => l.k === "roll");
  const socSvg = svg(sa.s + bands + `<line x1="${L}" x2="${W - R}" y1="${sa.y(d.site.bess.s_end_min_mwh)}" y2="${sa.y(d.site.bess.s_end_min_mwh)}" stroke="#d08a00" stroke-dasharray="3 3"/>` + (an ? `<polyline fill="none" stroke="rgba(28,35,41,0.45)" stroke-width="1.5" stroke-dasharray="4 3" points="${an.soc.map((s, i) => `${x(i)},${sa.y(s)}`).join(" ")}"/>` : "") + `<polyline fill="none" stroke="#22b866" stroke-width="2" points="${d.ep.soc_path.map((s, i) => `${x(i)},${sa.y(s)}`).join(" ")}"/>`);

  const aa = axes(-P, P, (v) => `${v > 0 ? "+" : ""}${Math.round(v)}`);
  const asSvg = svg(aa.s + hs.map((z, h) => {
    let up = 0, s = "";
    for (const k of UP.filter((kk) => d.offered.includes(kk))) {
      const v = z.awards[k];
      if (v > 0.05) s += `<rect x="${x(h) + 0.5}" y="${aa.y(up + v)}" width="${x(1) - x(0) - 1}" height="${aa.y(up) - aa.y(up + v)}" fill="url(#hp-${PROD[k].hatch})" stroke="rgba(28,35,41,0.5)" stroke-width="0.5"/>`;
      up += v;
    }
    const rd = z.awards.regdn;
    if (rd > 0.05 && d.offered.includes("regdn")) s += `<rect x="${x(h) + 0.5}" y="${aa.y(0)}" width="${x(1) - x(0) - 1}" height="${aa.y(-rd) - aa.y(0)}" fill="url(#hp-dots)" stroke="rgba(28,35,41,0.5)" stroke-width="0.5"/>`;
    return s;
  }).join(""));

  const series = [["agent", d.agentCum, "#2c3440", false], ...d.lanes.map((l) => [l.k, l.cum, l.k === "hind" ? "#1d9a57" : l.k === "roll" ? "#7a868e" : l.k === "blind" ? "#3d6fb6" : "#c9a24d", true])];
  const all = series.flatMap((s) => s[1]).concat([0]);
  const ma = axes(Math.min(...all), Math.max(...all) * 1.05 || 1, (v) => money(v));
  const cashSvg = svg(ma.s + series.map(([, c, col, dash]) => `<polyline fill="none" stroke="${col}" stroke-width="2" ${dash ? 'stroke-dasharray="5 4"' : ""} points="${[0, ...c].map((v, i) => `${x(i)},${ma.y(v)}`).join(" ")}"/>`).join(""));

  el.innerHTML = `<button class="x" aria-label="Close charts">×</button><h3>Charts</h3><div class="sub">${pt} · ${d.dayName(0)} to ${d.dayName(d.n - 1)} · ${d.lite ? "battery only" : `PV ${d.site.pv_mwac} MWac`} · ${d.P} MW / ${d.E} MWh · η ${d.eta} · meter ${Math.round(d.L)} MW · ${d.watches.length} watches · ${d.vint.runs.length} weather runs · v4 preview</div>
    <figure><figcaption>Real-time price by the hour (bars), the day-ahead price (dashed) and the guide's day-ahead P50 at each day's gate (blue), $/MWh</figcaption>${priceSvg}</figure>
    ${driftSvg ? `<figure><figcaption>How the forecast for the dearest hour (${whenText(d, dh * 60)}) moved: the guide's day-ahead P50 run by run (P10–P90 shaded) against what cleared</figcaption>${driftSvg}</figure>` : ""}
    ${tempSvg ? `<figure><figcaption>Temperature at ${d.task.weather_point || "the site"}: ${wv.length ? "every HRRR run (fading) against " : ""}what the airport observed (black)</figcaption>${tempSvg}</figure>` : ""}
    ${loadSvg ? `<figure><figcaption>ERCOT system load: every desk run (fading)${d.vint.all("load_official", "system").length ? ", ERCOT's day-ahead forecast via EIA-930 (dashed)" : ""}${d.task.actuals?.load_mw ? " and EIA-930 actual (black)" : ""}</figcaption>${loadSvg}</figure>` : ""}
    <figure><figcaption>Battery MW as executed (bars; + discharges)${d.lite ? "" : " over the PV available (cream)"}, against its DAM position (black line)</figcaption>${battSvg}</figure>
    <figure><figcaption>State of charge, MWh (green), the anchor's (dashed), inside the reserve bands; orange is the end obligation</figcaption>${socSvg}</figure>
    ${d.offered.length ? `<figure><figcaption>Reserve awards, MW: up products stacked above, RegDn below</figcaption>${asSvg}</figure>` : ""}
    <figure><figcaption>Cumulative cash, $: the agent (solid), the rolling anchor (grey), the blind re-planner (blue), the naive DAM bidder (gold), hindsight (green)</figcaption>${cashSvg}</figure>`;
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
      const px = x(Math.max(0, Math.min(N, t)));
      for (const l of phs) l.setAttribute("x1", px), l.setAttribute("x2", px);
    },
  };
}
