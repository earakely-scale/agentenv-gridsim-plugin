import { money, price } from "../data.js";
import { gateMin, laneAt, minuteOf, paraphrase, resultsMin, whenText } from "../forecast.js";
import { ERA, PROD, RULES, UP } from "../hybrid.js";
import { describe, weatherAt } from "../stage/weather.js";
import { ATTRIBUTION, modelName } from "./hud.js";
import { barSvg, hatchDefs, socSvg } from "./hudhybrid.js";
import { clockText } from "./hudlive.js";
import { buildFan } from "./fan.js";

const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const NS = "http://www.w3.org/2000/svg";
const svgEl = (tag, attrs) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
};
const mwTxt = (v) => (Math.abs(v) < 10 ? Math.abs(v).toFixed(1) : String(Math.round(Math.abs(v))));
const mvTxt = (v) => (Math.abs(v) < 0.05 ? "idle" : `${v > 0 ? "discharging" : "charging"} ${mwTxt(v)} MW`);
const CHARGE = "#2fd3ff", DISCHARGE = "#ffa62b", SOLAR = "#efe0a8", SOLAR_EDGE = "#b8973c", COLD = "#3d6fb6";
const reward = (p, idle, anchor) => (anchor - idle > 1e-6 ? Math.max(0, Math.min(1, 0.2 + (0.8 * (p - idle)) / (anchor - idle))) : null);
const fF = (c) => Math.round((c * 9) / 5 + 32);
const span = (m) => (m >= 60 ? `${Math.floor(m / 60)} h${m % 60 >= 5 ? ` ${Math.round(m % 60)} min` : ""}` : `${Math.max(1, Math.round(m))} min`);
export const TIER = { front: "FRONT", "front-lite": "FRONT-LITE", blind: "BLIND", "freeze-6h": "FREEZE 6 H" };

/** The cards over a Weather Front window: the place card with the clock, the DAM-gate countdown, the plant and the
 * weather; settlement so far; bulletins; the race against the rolling anchor, the blind re-planner and hindsight;
 * the forecasts as issued with the vintage scrubber; how it planned at each watch; the score; the multi-day timeline. */
export function buildForecastHud(root, d, { onSeek, onToggle }) {
  const ep = d.ep, H = d.H;
  root.insertAdjacentHTML("beforeend", hatchDefs());
  const left = el("div", "left-col");
  const place = el("section", "card place hyb fc");
  const pnl = el("section", "card pnl");
  const bulls = el("div", "bulletins");
  left.append(place, pnl, bulls);
  const news = el("div", "news off");
  const right = el("aside", "right fc");
  const race = el("section", "card race");
  const fan = buildFan(d);
  const think = el("section", "card think planlog");
  right.append(race, fan.root, think);
  const timeline = el("section", "card timeline live hyb fc");
  const attrib = el("div", "attrib", `${ATTRIBUTION.replace("ERCOT DAM settlement point prices", "ERCOT DAM and real-time settlement point prices, DAM AS clearing prices")} Forecasts: ${d.vint.source === "synthetic" ? "synthetic CI vintages" : d.ep.source === "ercot" ? "ERCOT's (public API) and desk models on NOAA HRRR, as issued" : "desk models on NOAA HRRR as issued"}; load: EIA-930. Bulletins: paraphrased ERCOT and NWS notices.`);
  const back = el("a", "back-link", "← All runs");
  back.href = "./index.html";
  const intro = el("section", "card intro live-intro hyb fc");
  root.append(left, news, right, timeline, attrib, back, intro);

  const name = modelName(ep.model, ep.model_label);
  const lanes = [{ k: "agent", label: name, cum: d.agentCum, final: ep.profit_usd }, ...d.lanes];
  const lo = Math.min(0, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const hi = Math.max(1, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const zx = (v) => ((v - lo) / (hi - lo)) * 100;
  const cls = { agent: "agent", roll: "opt", hind: "hind", blind: "blind", naive: "base" };
  race.innerHTML = `<h5>Race over the window <span class="v2tag v4">v4 preview</span></h5>` + lanes.map((l) => `<div class="lane ${cls[l.k] || "base"} ${l.k}" data-k="${l.k}"><div class="who">${l.k === "agent" ? `<b>${esc(l.label)}</b>` : esc(l.label)}</div><div class="track"><i class="z" style="left:${zx(0)}%"></i><span></span></div><div class="v num"></div></div>`).join("") +
    `<svg class="spark" viewBox="0 0 240 70" preserveAspectRatio="none"></svg><div class="score live hyb fc" hidden></div>`;
  intro.innerHTML = introHtml(d, name);
  const anchorLane = d.lanes.find((l) => l.k === "roll");

  const tl = buildTimeline(d);
  timeline.innerHTML = `<div class="ctl"><div class="row"><button class="play" data-a="play">▶ Play</button><button data-a="director" class="on" title="Automatic camera (D)">Director</button></div>
    <div class="row speeds">${[0.5, 1, 2, 4].map((s, i) => `<button data-s="${s}" title="${i + 1}">${s === 0.5 ? "½" : s}×</button>`).join("")}</div>
    <div class="row"><button data-a="charts" title="C">Charts</button><button data-a="settings">Settings</button><button data-a="link" title="Copy a link to this hour">Link</button></div></div>`;
  timeline.append(tl.root);
  const seekAt = (e) => {
    const r = tl.svg.getBoundingClientRect();
    onSeek(tl.tOfX(((e.clientX - r.left) / r.width) * tl.W));
  };
  let drag = false;
  tl.root.addEventListener("pointerdown", (e) => ((drag = true), tl.root.setPointerCapture(e.pointerId), seekAt(e)));
  tl.root.addEventListener("pointermove", (e) => drag && seekAt(e));
  tl.root.addEventListener("pointerup", () => (drag = false));
  timeline.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => onToggle(btn.dataset.a || "speed", btn.dataset.s ? +btn.dataset.s : null)));

  const events = newsEvents(d);
  let lastKey = "", lastPlan = -1, lastEv = null;
  function update(t, { playing, speed, directing }) {
    const min = t * 60;
    const pre = t < 0, ended = t >= H;
    const x = pre ? d.pre(t) : d.at(Math.min(H - 0.001, t));
    const w = d.watchAt(t);
    const settled = Math.max(0, Math.min(H, Math.floor(t + 1e-9)));
    const key = [Math.floor(t * 30), w.index, playing, speed, directing].join("|");
    if (key !== lastKey) {
      lastKey = key;
      const wx = weatherAt(d.weather, Math.max(d.t0, Math.min(H, t)));
      const lastRt = settled > 0 ? d.rt[settled - 1] : null;
      const hot = lastRt != null && lastRt > Math.max(150, 2 * d.prices[settled - 1]);
      place.innerHTML = placeHtml(d, x, t, min, settled, lastRt, hot, wx, anchorLane);
      pnl.innerHTML = pnlHtml(d, t, settled, ended);
      bulls.innerHTML = bulletinsHtml(d, t);
      const ev = events.filter((e) => t >= e.t && t < e.until).at(-1);
      if (ev !== lastEv) {
        lastEv = ev;
        if (ev) {
          news.className = `news ${ev.kind}`;
          news.innerHTML = `${ev.badge ? `<span class="badge ${ev.badge[1]}">${esc(ev.badge[0])}</span>` : "<i></i>"}<span>${esc(ev.text)}</span>`;
        } else news.className = "news off";
      }
      for (const l of lanes) {
        const v = laneAt(l.cum, t, l.final, H);
        const row = race.querySelector(`.lane[data-k="${l.k}"]`);
        const s = row.querySelector("span");
        const a = zx(Math.min(0, v)), c = zx(Math.max(0, v));
        s.style.left = `${a}%`;
        s.style.width = `${Math.max(0.5, c - a)}%`;
        row.querySelector(".v").textContent = money(v);
      }
      race.querySelector(".spark").innerHTML = spark(lanes, Math.min(H, Math.max(0, t)), lo, hi, H);
      const score = race.querySelector(".score");
      score.hidden = !ended;
      if (ended) score.innerHTML = scoreHtml(d, lanes);
      race.classList.toggle("ended", ended);
      right.classList.toggle("ended", ended);
      if (w.index !== lastPlan || ended) {
        lastPlan = w.index;
        think.innerHTML = planHtml(d, t);
        const cur = think.querySelector(".wrow.now");
        if (ended) think.scrollTop = think.scrollHeight;
        else if (cur) think.scrollTop = Math.max(0, cur.offsetTop - think.clientHeight + cur.offsetHeight + 8);
      }
      timeline.querySelector(".play").textContent = playing ? "❚❚ Pause" : "▶ Play";
      timeline.querySelectorAll("[data-s]").forEach((s) => s.classList.toggle("on", +s.dataset.s === speed));
      timeline.querySelector('[data-a="director"]').classList.toggle("on", directing);
      intro.hidden = t >= d.t0 + 1.6;
    }
    fan.update(t, w);
    const ramp = (a, b) => Math.max(0, Math.min(1, (t - a) / (b - a)));
    news.style.opacity = lastEv ? Math.min(ramp(lastEv.t, lastEv.t + 0.08), 1 - ramp(lastEv.until - 0.08, lastEv.until)) : 0;
    intro.style.opacity = 1 - ramp(d.t0 + 1.2, d.t0 + 1.6);
    tl.update(t, settled, w);
  }
  return { update, place, timeline };
}

function placeHtml(d, x0, t, min, settled, lastRt, hot, wx, anchor) {
  const H = d.H, ended = t >= H, pre = t < 0, ep = d.ep;
  const x = ended ? { ...x0, bands: [], head: 0, floor: 0 } : x0;
  const mw = Math.abs(x.net);
  const dep = x.dep > 0.1 ? x.events.filter((e) => min >= e.from && min < e.to).map((e) => PROD[e.product].name) : [];
  const upMw = UP.reduce((a, k) => a + x.awards[k], 0);
  const gw = d.watches.find((w) => w.gate != null && Math.abs(w.t - t) < 0.75 && t >= w.t);
  const act = pre ? (gw ? `Bidding ${d.dayName(gw.gate).split(" ")[0]}'s day-ahead book` : "Before the handover: idle") : ended ? `Handed back at ${Math.round((x.soc / d.E) * 100)}% charge` :
    dep.length ? `${dep.join(" and ")} deployed · ${mwTxt(x.dep)} MW called${x.net > 0.5 ? `, discharging ${mwTxt(x.net)}` : ""}` :
    x.mode === "charge" ? `Charging ${mwTxt(mw)} MW${x.fromPv > mw - 0.5 ? " from the panels" : x.fromPv > 0.5 ? `, ${mwTxt(x.fromPv)} from the panels` : x.price < 0 ? " from the grid, paid to take it" : " from the grid"}` :
    x.mode === "discharge" ? `Discharging ${mwTxt(mw)} MW` :
    upMw + x.awards.regdn > 0.5 ? `Holding ${[upMw > 0.5 && `${mwTxt(upMw)} MW up`, x.awards.regdn > 0.5 && `${mwTxt(x.awards.regdn)} MW RegDn`].filter(Boolean).join(" and ")} in reserve` : "Idle";
  const era = ERA[d.era];
  const ghost = anchor && !pre && !ended ? anchor.soc[x.h] + (anchor.soc[x.h + 1] - anchor.soc[x.h]) * x.u : null;
  const held = x.bands.filter((b) => b.mwh > 0.5).map((b) => `<span class="gl">${PROD[b.k].glyph}</span>${PROD[b.k].name} ${Math.round(b.mwh)} MWh`).join(" · ");
  const room = x.head > 0.5 ? `<span class="gl">D</span>RegDn room ${Math.round(x.head)} MWh` : "";
  const bandLine = ended ? `ends at ${Math.round(x.soc)} MWh; the obligation is ${Math.round(d.site.bess.s_end_min_mwh)}` : pre ? "handed over at midnight" : [held && `held for ${held}`, room].filter(Boolean).join(" · ");
  const L = d.L, toBat = Math.max(0, Math.min(x.exp, x.net)), pvOut = Math.max(0, x.exp - toBat);
  const panels = d.lite ? "battery-only site" : x.pvAvail < 0.5 ? "no sun" : x.stow && !pre ? (x.price < 0 ? "stowed: negative price" : "stowed") : `${mwTxt(x.pvUsed)} MW${x.curtailed > 0.5 && !pre ? ` · ${mwTxt(x.curtailed)} curtailed` : ""}`;
  const meter = x.exp < -0.5 ? `importing ${mwTxt(x.exp)} MW` : `${mwTxt(x.exp)} of ${Math.round(L)} MW`;
  const k = d.dayOf(t), dayTxt = pre ? "the day before" : ended ? `${d.n} operating days` : `day ${k + 1} of ${d.n}`;
  const priceTxt = pre || ended ? "" : lastRt == null ? `<span class="price num dim-price">${price(d.prices[x.h])}<small>/MWh DA</small></span>` : `<span class="price num ${lastRt < 0 ? "neg" : hot ? "hot" : ""}">${price(lastRt)}<small>/MWh RT</small></span>`;
  return `<div class="where">${esc(ended ? d.dayName(d.n - 1) : d.dayName(Math.floor(t / 24)))} · ${dayTxt} · <b>${esc(d.task.settlement_point)}</b> · ${esc(d.place.name)}<span class="tags"><span class="tier fc">V4 · ${esc(TIER[ep.tier] || ep.tier.toUpperCase())}</span><span class="era e${d.era}" title="${esc(era[1])}">${esc(era[0])}</span></span></div>
    <div class="big"><span class="clock num">${ended ? "Window over" : clockText(min)}</span>${priceTxt}</div>
    <div class="gate">${gateLine(d, min)}</div>
    <div class="act ${ended ? "" : dep.length ? "discharge" : x.mode}"><i></i><span>${act}</span></div>
    <div class="soc hyb"><div class="row"><span>State of charge</span><span><b class="num">${Math.round((x.soc / d.E) * 100)}%</b> · ${Math.round(x.soc)} of ${Math.round(d.E)} MWh</span></div>
      ${socSvg(d, x, ghost)}<div class="bands">${bandLine || "no reserves this hour"}${ghost != null ? '<span class="gh">┆ anchor</span>' : ""}</div></div>
    <div class="plantrow"><div><span>Panels</span><b class="num">${panels}</b>${barSvg(d.lite ? [] : [[0, Math.min(1, x.pvUsed / d.pvMwac), SOLAR, SOLAR_EDGE], [x.pvUsed / d.pvMwac, Math.min(1, x.pvAvail / d.pvMwac), "url(#hp-curt)"]])}</div>
      <div><span>Meter</span><b class="num">${meter}</b>${barSvg(x.exp < 0 ? [[0, Math.min(1, -x.exp / d.Limp), CHARGE]] : [[0, pvOut / L, SOLAR, SOLAR_EDGE], [pvOut / L, Math.min(1, (pvOut + toBat) / L), DISCHARGE], [Math.max(0, 1 - upMw / L), 1, "url(#hp-fwd)"]])}</div></div>
    <div class="wxrow">${weatherLine(d, t, wx)}</div>`;
}

/** The next DAM event: the gate's countdown, the results' countdown, or the gate now. */
function gateLine(d, min) {
  for (let k = 0; k < d.n; k++) {
    const g = gateMin(k), r = resultsMin(k) + 30;
    if (min < g - 0.5) return `<span class="gl2">DAM</span> gate for ${esc(d.dayName(k))} in <b class="num">${span(g - min)}</b>`;
    if (min < g + 45) return `<span class="gl2 on">DAM</span> gate now: ${esc(d.dayName(k))}'s book is due`;
    if (min < r) return `<span class="gl2">DAM</span> ${esc(d.dayName(k))}'s results at 2 pm, in <b class="num">${span(r - min)}</b>`;
  }
  return `<span class="gl2 off">DAM</span> no gates left · the window ends ${esc(d.dayName(d.n - 1))} at midnight`;
}

function weatherLine(d, t, wx) {
  const parts = [describe(wx) || "weather n/a"];
  const fr = d.frostAt(Math.max(d.t0, Math.min(d.H, t)));
  if (fr > 0.3 && !d.lite) parts.push((wx.wx || []).some((c) => /FZ/.test(c)) ? "ice on the panels" : "frost on the panels");
  const f = d.front;
  if (f && t >= f.t && t < f.t + 10) parts.push(`<b class="cold">cold front through ${esc(whenText(d, f.t * 60, { day: false }))}: ${fF(f.from)} to ${fF(f.to)} °F</b>`);
  return parts.join(" · ");
}

function pnlHtml(d, t, settled, ended) {
  const H = d.H, hs = d.hours.slice(0, ended ? H : settled);
  const s = (k) => hs.reduce((a, x) => a + x.cashParts[k], 0);
  const pen = ended ? d.ep.cash.end_penalty || 0 : null;
  const exc = hs.reduce((a, x) => a + x.excusedUsd, 0);
  const total = hs.reduce((a, x) => a + x.cash, 0);
  const row = (k, v, cl = "") => `<div class="r ${cl}"><span>${k}</span><b class="num">${v}</b></div>`;
  const sm = (v) => (Math.abs(v) < 0.5 ? "$0" : money(v, { sign: true }));
  const dep = s("dep"), ftp = s("ftp");
  return `<h5>Settlement so far <small>${ended ? `${H} of ${H} hours` : `${settled} of ${H} hours`}</small></h5>
    ${row("DAM energy (day-ahead)", sm(s("energy_da")))}
    ${row("Real-time deviation", sm(s("energy_rt")), s("energy_rt") < -0.5 ? "bad" : s("energy_rt") > 0.5 ? "good" : "")}
    ${d.offered.length ? row("Reserves (AS), day-ahead", sm(s("as"))) : ""}
    ${d.offered.length ? row("Deployment energy", sm(dep)) : ""}
    ${row("Degradation", s("deg") < 0.5 ? "$0" : money(-s("deg")))}
    ${d.offered.length ? row("Failure to provide", ftp > 0.5 ? money(-ftp) : "$0", ftp > 0.5 ? "bad" : "") : ""}
    ${row("Terminal shortfall", pen == null ? "at the end" : pen ? money(-pen) : "$0", pen ? "bad" : "")}
    ${exc > 0.5 ? row("Excused (not charged)", money(exc), "dim") : ""}
    ${row("Total", money(ended ? d.ep.profit_usd : total), "total")}`;
}

function bulletinsHtml(d, t) {
  const got = d.notices.map((n) => ({ n, at: n.deploy ? Math.max(0, n.deploy.start_min) / 60 : n.deliverT })).filter((z) => z.at != null && z.at <= t + 1e-9 && (z.n.deploy || z.n.deliverT != null));
  if (!got.length) return "";
  const lastAt = got.at(-1).at;
  const recent = got.filter((z) => t - z.at < 3 || z.at === lastAt).sort((a, b) => a.at - b.at);
  const shown = recent.slice(-2).reverse();
  return shown.map(({ n, at }, i) => {
    const fresh = i === 0 && t - at < 0.75;
    const issued = n.issued.toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }).replace(/ (AM|PM)$/, (m) => m.toLowerCase());
    let text = paraphrase(n), when = `issued ${issued}${n.watch === 0 ? " · on the board" : n.watch != null ? ` · read at ${whenText(d, d.watches[n.watch].min)}` : ""}`;
    if (n.deploy) {
      const h = Math.min(d.H - 1, Math.floor(n.deploy.start_min / 60)), aw = d.hours[h].awards[n.deploy.product] || 0, k = PROD[n.deploy.product];
      const win = d.wins.find((z) => z.n.event_id === n.event_id);
      const hrs = win ? (win.b - win.a) / 60 : 0;
      text = aw > 0.05 ? `${k.name} deployed ${whenText(d, n.deploy.start_min)} · ${mwTxt(aw * n.deploy.frac)} MW for ${hrs >= 0.95 ? `${+hrs.toFixed(1)} h` : `${Math.round(hrs * 60)} min`}: the reserved band drains to the line.` : `ERCOT deploys ${k.name} at ${whenText(d, n.deploy.start_min)}; this plant holds none then.`;
      when = `the agent learns of it ${n.watch != null ? `at the ${whenText(d, d.watches[n.watch].min)} watch` : "after the window"}`;
    }
    return `<div class="card bul ${fresh ? "fresh" : ""} ${n.deploy ? "dep" : ""}"><div class="bh"><span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span><span class="src">${esc(n.name || n.source)}</span><span class="when">${esc(when)}</span></div><p>${esc(text)}</p></div>`;
  }).join("") + (got.length > shown.length ? `<div class="more-b">${got.length - shown.length} earlier bulletin${got.length - shown.length > 1 ? "s" : ""} in the timeline</div>` : "");
}

const READ = { price: "price", load: "load", solar: "solar", wind: "wind", weather: "weather", alerts: "alerts" };

function planHtml(d, t) {
  const H = d.H, cur = d.watchAt(t);
  const rows = d.watches.filter((w) => w.t <= t + 1e-9 || t >= H).map((w) => {
    const ns = d.notices.filter((n) => n.watch === w.index && !/cancel/i.test(n.title || "") && !n.deploy);
    const pills = [];
    if (w.reads.length) {
      const kinds = [...new Set(w.reads.map((s) => (s.tool === "get_forecast_drift" ? "drift" : READ[s.args?.kind] || s.args?.kind)))];
      pills.push(`<span class="pill read" title="${esc(kinds.join(", "))}">read ${w.reads.length}</span>`);
    }
    for (const s of w.dam) {
      const o = s.output || {}, k = Math.round(minuteOf(`${o.operating_day} 00:00`, d.d1) / 1440);
      const got = (o.accepted || []).length;
      pills.push(`<span class="pill dam ${got === 24 ? "ok" : got ? "part" : "no"}">DAM ${esc(d.dayName(k).split(" ")[0])} ${got ? "✓" : "✗"} ${got}/24 h${o.refused?.length ? ` · refused: ${[...new Set(o.refused.map((r) => r.rule))].map(esc).join(", ")}` : ""}</span>`);
    }
    for (const s of w.calls) {
      const o = s.output || {};
      if (o.error) {
        pills.push(`<span class="pill no">${s.tool === "check_schedule" ? "check" : "commit"} ✗ · ${esc(o.error.slice(0, 40))}</span>`);
        continue;
      }
      if (s.tool === "check_schedule") {
        pills.push(`<span class="pill ${o.feasible ? "ok" : "no"}">check ${o.feasible ? "✓" : `✗ ${(o.issues || []).length}`}</span>`);
        continue;
      }
      const got = o.committed || [], bad = o.refused || [];
      const sp = got.length ? ` ${whenText(d, got[0] * 60)}–${got.at(-1) + 1 >= H ? "the end" : whenText(d, (got.at(-1) + 1) * 60)}` : "";
      const why = bad.length ? ` · refused ${[...new Set(bad.map((r) => r.hour))].length} h: ${[...new Set(bad.map((r) => r.rule))].map(esc).join(", ")}` : "";
      pills.push(`<span class="pill ${got.length ? (bad.length ? "part" : "ok") : "no"}" title="${esc(bad.slice(0, 4).map((r) => `${r.hour}: ${r.detail}`).join("\n"))}">commit ${got.length ? "✓" : "✗"}${sp}${why}</span>`);
    }
    const tag = w.gate != null ? '<span class="chip gate">gate</span>' : w.kind === "event" && !ns.length ? '<span class="chip run">HRRR</span>' : "";
    return `<div class="wrow ${w.index === cur.index && t < H ? "now" : ""}"><span class="wt">${esc(whenText(d, w.min))}</span><span class="wc">${tag}${ns.slice(0, 2).map((n) => `<span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span>`).join("")}${pills.join("") || '<span class="pill idle">held the book</span>'}</span></div>`;
  }).join("");
  const n = d.watches.reduce((a, w) => a + w.calls.length + w.dam.length, 0);
  const reads = d.watches.reduce((a, w) => a + w.reads.length, 0);
  const rules = {};
  for (const w of d.watches) if (w.t <= t + 1e-9 || t >= H) for (const r of w.refused) rules[r.rule] = (rules[r.rule] || 0) + 1;
  const ruleLine = Object.keys(rules).length ? `<div class="rules">Refused hours by rule: ${Object.entries(rules).sort((a, b) => b[1] - a[1]).map(([r, k]) => `<b>${esc(r)}</b> ${k} <span class="dim">(${esc(RULES[r] || r)})</span>`).join(" · ")}</div>` : "";
  const said = (d.ep.messages || []).filter((m) => m.role === "assistant" && m.content).map((m) => m.content);
  const msg = (t < 0 ? said.slice(0, 1) : said.slice(-2)).map((m) => `<blockquote>“${esc(m.slice(0, 240))}${m.length > 240 ? "…" : ""}”</blockquote>`).join("");
  return `<h5>How it planned <small>${d.watches.length} watches · ${n} planning calls · ${reads} forecast reads</small></h5><div class="wlist">${rows}</div>${ruleLine}${t >= H || t < 0 ? msg : ""}`;
}

function scoreHtml(d, lanes) {
  const ep = d.ep, R = ep.reward ?? 0, ref = ep.references || {};
  const pi = ref.p_idle, pa = ref.p_anchor;
  const pos = (r) => `${Math.max(0, Math.min(1, r)) * 100}%`;
  const rr = (p) => reward(p, pi, pa);
  const capt = (p) => (p == null || pi == null || ref.p_hind == null || ref.p_hind - pi <= 1e-9 ? null : (p - pi) / (ref.p_hind - pi));
  const c = capt(ep.profit_usd), ca = capt(pa), f3 = (x) => (x == null ? "—" : x.toFixed(3));
  const dl = c == null || ca == null ? "" : ` · Δ ${c - ca >= 0 ? "+" : "−"}${Math.abs(c - ca).toFixed(3)}`;
  const ticks = [["blind", ref.p_blind], ["naive", ref.p_naive]].map(([k, p]) => {
    const x = capt(p);
    return x == null ? "" : `<i class="tick ${k === "naive" ? "n" : "b"}" style="left:${pos(x)}" title="${k} ${x.toFixed(2)}"></i>`;
  }).join("");
  const self = ep.model === "reference/rolling-p50" && ep.tier !== "blind" ? "This is the rolling anchor: R is 1 by definition." : ep.beats_anchor ? "Beats the rolling anchor." : "Does not beat the rolling anchor.";
  const missed = (ep.dam || []).filter((x) => x.missed).length;
  const reads = d.watches.reduce((a, w) => a + w.reads.length, 0);
  const rows = [["Rolling anchor (guide P50)", ref.p_roll], ["Three-scenario anchor", ref.p_roll3], ["Blind re-planner", ref.p_blind], ["Naive DAM bidder", ref.p_naive], ["Hindsight", ref.p_hind]]
    .filter(([, p]) => p != null).map(([k, p]) => `<div class="cr"><span>${k}</span><b class="num">${money(p)}</b><em class="num">${k === "Hindsight" ? "C 1, the bound" : `C ${f3(capt(p))} · R ${(rr(p) ?? 0).toFixed(2)}`}</em></div>`).join("");
  return `<div class="pair"><div><div class="lbl">Hindsight capture C</div><div class="r num">${f3(c)}</div>
      <div class="rscale"><span class="fill" style="width:${pos(c ?? 0)}"></span>${ticks}${ca == null ? "" : `<i class="tick a" style="left:${pos(ca)}" title="anchor ${ca.toFixed(2)}"></i>`}</div>
      <div class="cap">idle 0 · the anchor's ${f3(ca)}${dl} · hindsight 1</div></div>
    <div class="second"><div class="lbl">Profit, ${d.n} days</div><div class="r num">${money(ep.profit_usd)}</div><div class="cap">vs the anchor <b class="${ep.profit_usd - (pa ?? 0) >= 0 ? "good" : "bad"}">${money(ep.profit_usd - (pa ?? 0), { sign: true })}</b> · R ${R.toFixed(3)} on the anchor scale</div></div></div>
    <div class="cmp">${rows}</div>
    <div class="line">${self} DAM gates ${d.n - missed} of ${d.n}${missed ? ` (${missed} missed)` : ""} · ${reads} forecast reads.</div>
    <div class="line dim">v4 preview · C heads, R on the anchor scale (idle 0.2, anchor 1.0) comes second. ${d.vint.source === "synthetic" ? "This CI window's forecast vintages are synthetic." : ep.source === "ercot" ? "Load, wind and solar forecasts are ERCOT's own as posted; the price guide is the desk's." : "Forecasts are the desk's, modelled from NOAA HRRR as issued."}</div>`;
}

function spark(lanes, t, lo, hi, H) {
  const W = 240, Hh = 70;
  const y = (v) => Hh - 4 - ((v - lo) / (hi - lo || 1)) * (Hh - 8);
  let s = `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.15)"/>`;
  for (let k = 24; k < H; k += 24) s += `<line x1="${(k / H) * W}" x2="${(k / H) * W}" y1="0" y2="${Hh}" stroke="rgba(0,0,0,0.08)"/>`;
  const n = Math.min(H, Math.ceil(t));
  for (const l of lanes) {
    const pts = [[0, 0], ...l.cum.slice(0, n).map((v, i) => [Math.min(t, i + 1), i + 1 > t ? laneAt(l.cum, t, l.final, H) : v])];
    const col = l.k === "agent" ? "#2c3440" : l.k === "roll" ? "rgba(28,35,41,0.45)" : l.k === "hind" ? "rgba(29,154,87,0.45)" : l.k === "blind" ? "rgba(61,111,182,0.5)" : "rgba(28,35,41,0.2)";
    s += `<polyline fill="none" stroke="${col}" stroke-width="${l.k === "agent" ? 2.2 : 1.5}" ${l.k === "roll" || l.k === "hind" ? 'stroke-dasharray="4 3"' : ""} points="${pts.map(([i, v]) => `${(i / H) * W},${y(v)}`).join(" ")}"/>`;
  }
  return s;
}

function introHtml(d, name) {
  const ep = d.ep, w0 = d.watches[0];
  const board = d.notices.filter((n) => n.watch === 0 && !n.deploy);
  const at = w0.t;
  const strip = (vals, col, band = null, Hh = 34) => {
    const xs = vals.map((v, i) => [i, v]).filter(([, v]) => v != null);
    if (!xs.length) return '<svg viewBox="0 0 560 38"></svg>';
    const all = xs.map(([, v]) => v).concat(band ? band.flat().filter((v) => v != null) : []);
    const lo = Math.min(0, ...all), hi = Math.max(1e-6, ...all);
    const y = (v) => Hh - 3 - ((v - lo) / (hi - lo || 1)) * (Hh - 6);
    const X = (i) => (i / (vals.length - 1)) * 560;
    const pts = xs.map(([i, v]) => `${X(i)},${y(v)}`).join(" ");
    const bd = band ? `<polygon fill="${col}" opacity="0.14" points="${band[1].map((v, i) => `${X(i)},${y(v ?? 0)}`).join(" ")} ${band[0].map((v, i) => [X(i), y(v ?? 0)]).reverse().map((p) => p.join(",")).join(" ")}"/>` : "";
    const days = [24, 48].filter((k) => k < vals.length).map((k) => `<line x1="${X(k)}" x2="${X(k)}" y1="0" y2="${Hh}" stroke="rgba(0,0,0,0.12)"/>`).join("");
    return `<svg viewBox="0 0 560 ${Hh + 4}" preserveAspectRatio="none">${days}${bd}<polyline fill="none" stroke="${col}" stroke-width="2" points="${pts}"/></svg>`;
  };
  const ser = (kind, key, field) => {
    const v = d.vint.latest(kind, key, at);
    if (!v) return null;
    return Array.from({ length: d.H }, (_, h) => v.fields[field]?.[h - v.h0] ?? null);
  };
  const pt = d.task.settlement_point;
  const rt = ser("price", pt, "rt_p50"), band = [ser("price", pt, "rt_p10"), ser("price", pt, "rt_p90")];
  const pv = d.lite ? null : ser(ep.source === "ercot" ? "ercot_solar" : "solar", "site", "mw");
  const tmp = d.vint.source === "synthetic" ? null : ser("weather", d.task.weather_point, "t2m_f");
  const v0 = d.vint.latest("price", pt, at);
  const issued = v0 ? whenText(d, v0.rev * 60) : null;
  const durs = d.offered.map((k) => `${PROD[k].name} ${d.dur[k]} h`).join(", ");
  return `<h5>The window opens · ${esc(whenText(d, w0.min))} · ${esc(pt)} <span class="era e${d.era}">${esc(ERA[d.era][0])}</span></h5>
    <p><b>${esc(name)}</b> runs ${d.lite ? `a ${d.P} MW / ${d.E} MWh battery` : `a ${d.site.pv_mwac} MWac solar farm and a ${d.P} MW / ${d.E} MWh battery behind one ${Math.round(d.L)} MW meter`} for ${d.n} operating days, ${esc(d.dayName(0))} to ${esc(d.dayName(d.n - 1))}. Each day's <b>day-ahead book</b>${d.offered.length ? ` (battery MW and reserve awards: ${esc(durs)})` : ""} is due at the <b>10 am DAM gate</b> the day before; results arrive at 2 pm. Between gates it re-plans at ${d.watches.length - 1} more watches, never inside the <b>${ep.tier === "freeze-6h" ? "6 h" : "1 h"} lock</b>, as weather runs, bulletins and prices arrive.</p>
    <div class="strip"><span>Price guide</span>${strip(rt || [], "#3a4651", rt && band[0] ? band : null)}<em>${rt ? `RT P50 peak ${price(Math.max(...rt.filter((v) => v != null)))}` : "none yet"}</em></div>
    ${pv ? `<div class="strip"><span>Site PV</span>${strip(pv, SOLAR_EDGE)}<em>P50 peak ${Math.round(Math.max(...pv.filter((v) => v != null)))} MW</em></div>` : ""}
    ${tmp ? `<div class="strip"><span>Temperature</span>${strip(tmp, COLD)}<em>HRRR ${Math.round(Math.min(...tmp.filter((v) => v != null)))}–${Math.round(Math.max(...tmp.filter((v) => v != null)))} °F</em></div>` : ""}
    <p class="dim">${issued ? `What the desk holds now: the guide issued ${esc(issued)}, ${d.vint.upto("price", pt, at).length} runs so far. ` : ""}${board.length ? `${board.length} bulletin${board.length > 1 ? "s" : ""} on the board: ${board.map((n) => esc(n.badge[0])).join(", ")}.` : "No bulletins on the board."}${d.vint.source === "synthetic" ? " This CI window's forecast vintages are synthetic; prices, PV and the weather are real." : ""}</p>`;
}

/** The headlines over the window: bulletins, HRRR runs that move the guide, gates and DAM results, the cold front, the
 * first frost, deployments, stows, failures to provide, refused commits, the real-time spike and the end. */
function newsEvents(d) {
  const ev = [], H = d.H;
  const rank = { eea3: 7, eea2: 6, eea1: 5, cons: 4, watch: 3, warn: 3, adv: 2, ocn: 1, nws: 1, ok: 2, off: 0 };
  for (const w of d.watches) {
    const ns = d.notices.filter((n) => n.watch === w.index && w.index > 0 && !n.deploy);
    if (ns.length) {
      const top = ns.reduce((a, n) => ((rank[n.badge[1]] ?? 0) > (rank[a.badge[1]] ?? 0) ? n : a));
      ev.push({ t: w.t, until: w.t + 2.2, kind: "bulletin", badge: top.badge, text: paraphrase(top) + (ns.length > 1 ? ` (+${ns.length - 1} more)` : "") });
    }
  }
  for (const s of d.ep.steps) {
    const o = s.output || {};
    if (s.tool !== "advance" || o.watch == null) continue;
    const w = d.watches[o.watch];
    const nv = (o.new_vintages || []).filter((v) => v.headline);
    if (w && w.kind === "event" && nv.length && !d.notices.some((n) => n.watch === w.index)) ev.push({ t: w.t, until: w.t + 1.8, kind: "run", badge: ["HRRR", "run"], text: nv.at(-1).headline });
    if (o.dam_results) {
      const r = o.dam_results, k = Math.round(minuteOf(`${r.operating_day} 00:00`, d.d1) / 1440);
      const pk = r.da_usd.indexOf(Math.max(...r.da_usd));
      ev.push({ t: w.t + 0.02, until: w.t + 2, kind: "dam", badge: ["DAM results", "dam"], text: `${d.dayName(k)} clears day-ahead: peak ${price(r.da_usd[pk])}/MWh at ${whenText(d, pk * 60, { day: false })}${r.value_usd ? `; the book earns ${money((r.value_usd.energy || 0) + (r.value_usd.as || 0))} at these prices${r.value_usd.as ? `, ${money(r.value_usd.as)} of it reserves` : ""}` : ""}` });
    }
  }
  for (const w of d.watches) {
    if (w.gate == null) continue;
    const s = w.dam.at(-1), got = (s?.output?.accepted || []).length;
    ev.push({ t: w.t + 0.01, until: w.t + 1.4, kind: "gate", badge: ["DAM gate", "gate"], text: s ? `${d.dayName(w.gate)}'s day-ahead book is in: ${got} of 24 hours accepted${s.args?.pv_da_share != null && !d.lite ? `, ${Math.round(s.args.pv_da_share * 100)}% of the PV P50 sold` : ""}` : `${d.dayName(w.gate)}'s DAM gate passes with no book: the day runs on real time alone` });
  }
  const f = d.front;
  if (f) ev.push({ t: f.t, until: f.t + 2.6, kind: "front", badge: ["Cold front", "front"], text: `A cold front reaches ${d.place.airport || "the site"}: ${fF(f.from)} °F to ${fF(f.to)} °F, the wind backs into the ${compass(f.bearing)} at up to ${Math.round(f.gustKt * 1.15)} mph` });
  for (let t = d.t0; t < H; t += 0.25) {
    if (d.frostAt(t) > 0.45 && d.frostAt(t - 0.25) <= 0.45 && !d.lite) {
      ev.push({ t, until: t + 1.5, kind: "frost", text: "Frost forms on the panels" });
      break;
    }
  }
  for (const z of d.wins) {
    const h = Math.min(H - 1, Math.floor(z.a / 60)), aw = d.hours[h].awards[z.product] || 0, k = PROD[z.product];
    ev.push({ t: z.a / 60, until: z.a / 60 + 1.3, kind: "deploy", badge: [`${k.name} deployed`, "dep"], text: aw > 0.05 ? `${k.name} deployed ${whenText(d, z.a)} · ${mwTxt(aw * z.frac)} MW` : `ERCOT deploys ${k.name} at ${whenText(d, z.a)}; this plant holds none then` });
  }
  const st = d.hours.find((x) => x.neg && x.pvAvail > 5 && x.curtailed > 0.9 * x.pvAvail);
  if (st) ev.push({ t: st.h + 0.05, until: st.h + 1.4, kind: "neg", text: `Negative real-time prices ${whenText(d, st.h * 60)}: the controller stows the panels` });
  let gov = 0;
  for (const x of d.hours) {
    if (x.ftpMw > 0.05) ev.push({ t: x.h + 1, until: x.h + 1.8, kind: "ftp", text: `Short ${mwTxt(x.ftpMw)} MW of reserves ${whenText(d, x.h * 60)}: ${money(x.ftpUsd)} failure to provide` });
    if (x.governor && gov++ < 3) ev.push({ t: x.h + 0.08, until: x.h + 0.9, kind: "governor", text: `Governor ${whenText(d, x.h * 60)}: the battery's move is clipped to ${mvTxt(x.b)} to keep its awards backed` });
  }
  for (const w of d.watches) {
    if (!w.refused.length) continue;
    const hrs = [...new Set(w.refused.map((r) => r.hour).filter((h) => h != null))];
    ev.push({ t: w.t + 0.04, until: w.t + 1.1, kind: "refused", text: `${whenText(d, w.min)} commit: ${hrs.length} hour${hrs.length > 1 ? "s" : ""} refused · ${w.refused[0].rule}: ${w.refused[0].detail}` });
  }
  const s = d.peakH;
  if (d.rt[s] > Math.max(200, 2.5 * d.prices[s])) ev.push({ t: s + 1, until: s + 2.2, kind: "peak", text: `Real-time ${price(d.rt[s])}/MWh ${whenText(d, s * 60)}; day-ahead was ${price(d.prices[s])}` });
  if ((d.ep.cash?.end_penalty || 0) > 0.5) ev.push({ t: H - 0.4, until: H + 1, kind: "penalty", text: `The window ends below the required charge: a ${money(d.ep.cash.end_penalty)} shortfall` });
  return ev.sort((a, b) => a.t - b.t);
}

const compass = (b) => ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][Math.round(b / 45) % 8];

/** The multi-day timeline: the weather at the site (temperature, the front, frost) on top; DA bars as each day's
 * results arrive and RT dots as hours settle, under the guide's DA P50 until then; the battery's DAM position
 * (outlined) against the real-time book (filled) over the PV; reserve awards by hatch; watch markers by kind, gates,
 * the frozen hours and the lock line. The day before the window runs compressed on the left. */
function buildTimeline(d) {
  const root = el("div", "tl live hyb fc");
  const H = d.H, W = 1200, Ht = 150, T0 = d.t0, FP = H > 48 ? 0.07 : 0.1;
  const x = (t) => (t < 0 ? (FP * W * (t - T0)) / -T0 : FP * W + ((1 - FP) * W * t) / H);
  const tOfX = (px) => (px < FP * W ? T0 + (px / (FP * W)) * -T0 : ((px - FP * W) / ((1 - FP) * W)) * H);
  const cw = ((1 - FP) * W) / H;
  const Y = { mk: 0, wTop: 15, wBot: 31, pTop: 36, pBot: 64, eMid: 84, eH: 13, aBase: 120, aUp: 14, aDn: 6, marks: 132, bot: 138 };
  const all = [...d.rt, ...d.prices];
  const mx = Math.max(1, ...all.map((p) => Math.abs(p)));
  const k = 40, f = (p) => (Math.sign(p) * Math.log1p(Math.abs(p) / k)) / Math.log1p(mx / k);
  const lo = Math.min(0, ...all.map(f));
  const zero = Y.pTop + (Y.pBot - Y.pTop) * (1 / (1 - lo));
  const py = (p) => zero - f(Math.max(-mx, Math.min(mx, p))) * (zero - Y.pTop);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${Ht}`, preserveAspectRatio: "none" });
  const g = (c) => svg.appendChild(svgEl("g", { class: c }));
  const bg = g("bg");
  bg.appendChild(svgEl("rect", { x: 0, y: Y.wTop - 2, width: x(0), height: Y.bot - Y.wTop + 2, fill: "rgba(28,35,41,0.035)" }));
  for (let h = 6; h < H; h += 6) bg.appendChild(svgEl("line", { x1: x(h), x2: x(h), y1: Y.wTop, y2: Y.bot, stroke: h % 24 ? "rgba(28,35,41,0.05)" : "rgba(28,35,41,0.22)", "vector-effect": "non-scaling-stroke" }));
  bg.appendChild(svgEl("line", { x1: x(0), x2: x(0), y1: Y.mk, y2: Y.bot, stroke: "rgba(28,35,41,0.35)", "vector-effect": "non-scaling-stroke" }));
  for (const yy of [zero, Y.eMid, Y.aBase]) bg.appendChild(svgEl("line", { x1: x(0), x2: W, y1: yy, y2: yy, stroke: "rgba(0,0,0,0.14)", "vector-effect": "non-scaling-stroke" }));
  const wx = d.wx;
  if (wx) {
    const ts = [], temps = [];
    for (let i = 0; i < wx.temp.length; i++) {
      const t = wx.t0 + i * wx.dt;
      if (t < T0 || t > H) continue;
      ts.push(t), temps.push(wx.temp[i]);
    }
    const tlo = Math.min(...temps), thi = Math.max(...temps, tlo + 6);
    const ty = (c) => Y.wBot - ((c - tlo) / (thi - tlo)) * (Y.wBot - Y.wTop);
    for (let i = 0; i < ts.length; i++) {
      const fr = d.lite ? 0 : d.frostAt(ts[i]);
      if (fr > 0.3) bg.appendChild(svgEl("rect", { x: x(ts[i]), width: x(ts[i] + wx.dt) - x(ts[i]) + 0.3, y: Y.wTop - 1, height: Y.wBot - Y.wTop + 2, fill: `rgba(120,160,210,${(0.12 + 0.2 * fr).toFixed(3)})` }));
    }
    if (tlo < 0 && thi > 0) bg.appendChild(svgEl("line", { x1: 0, x2: W, y1: ty(0), y2: ty(0), stroke: "rgba(61,111,182,0.35)", "stroke-dasharray": "3 3", "vector-effect": "non-scaling-stroke" }));
    bg.appendChild(svgEl("polyline", { points: ts.map((t, i) => `${x(t)},${ty(temps[i])}`).join(" "), fill: "none", stroke: "#5b6c7a", "stroke-width": 1.4, "vector-effect": "non-scaling-stroke" }));
    if (d.front) {
      const fx = x(d.front.t), path = [];
      for (let i = -2; i <= 2; i++) path.push(`M${fx + i * 9 - 4},${Y.wBot + 1} L${fx + i * 9 + 4},${Y.wBot + 1} L${fx + i * 9},${Y.wBot - 6} Z`);
      bg.appendChild(svgEl("line", { x1: fx - 22, x2: fx + 22, y1: Y.wBot + 1, y2: Y.wBot + 1, stroke: COLD, "stroke-width": 2, "vector-effect": "non-scaling-stroke" }));
      const tri = svgEl("path", { d: path.join(" "), fill: COLD });
      tri.appendChild(svgEl("title", {})).textContent = `Cold front ${whenText(d, d.front.t * 60)}: ${fF(d.front.from)} to ${fF(d.front.to)} °F`;
      bg.appendChild(tri);
    }
  }
  const freeze = svgEl("rect", { y: Y.pTop - 2, height: Y.bot - Y.pTop + 4, fill: "rgba(28,35,41,0.06)", x: 0, width: 0 });
  svg.appendChild(freeze);
  if (!d.lite) {
    const pvMax = Math.max(1, d.pvMwac);
    const pts = d.hours.map((z, h) => `${x(h)},${Y.eMid - (z.pvAvail / pvMax) * (Y.eH + 3)} ${x(h + 1)},${Y.eMid - (z.pvAvail / pvMax) * (Y.eH + 3)}`).join(" ");
    svg.appendChild(svgEl("polygon", { points: `${x(0)},${Y.eMid} ${pts} ${x(H)},${Y.eMid}`, fill: SOLAR, opacity: 0.55 }));
  }
  const guide = svgEl("polyline", { fill: "none", stroke: "rgba(28,35,41,0.5)", "stroke-width": 1.2, "stroke-dasharray": "2 2", "vector-effect": "non-scaling-stroke" });
  svg.appendChild(guide);
  const pg = g("p");
  const daR = d.prices.map((p, h) => pg.appendChild(svgEl("rect", { x: x(h) + 0.6, width: cw - 1.2, y: Math.min(py(p), zero), height: Math.max(1, Math.abs(py(p) - zero)), rx: 1, fill: "none", stroke: "rgba(28,35,41,0.42)", "stroke-width": 1, "vector-effect": "non-scaling-stroke", opacity: 0 })));
  const rtG = g("rt");
  rtG.setAttribute("shape-rendering", "geometricPrecision");
  const dots = d.rt.map((p, h) => rtG.appendChild(svgEl("ellipse", { cx: x(h + 0.5), cy: py(p), rx: Math.min(4.5, cw * 0.42), ry: 2.6, fill: p < 0 ? "#7c58b3" : p > Math.max(150, 2 * d.prices[h]) ? "#cf3e33" : "#2c3440", opacity: 0 })));
  const eG = g("e");
  const eR = d.hours.map((_, h) => eG.appendChild(svgEl("rect", { x: x(h) + 0.8, width: cw - 1.6, y: Y.eMid, height: 0, rx: 1 })));
  const daG = g("eda");
  const daE = d.hours.map((_, h) => daG.appendChild(svgEl("rect", { x: x(h) + 0.4, width: cw - 0.8, y: Y.eMid, height: 0, fill: "none", stroke: "#1c2329", "stroke-width": 1, "vector-effect": "non-scaling-stroke", opacity: 0.75 })));
  const aG = g("as");
  const aR = {};
  for (const kk of d.offered) aR[kk] = d.hours.map((_, h) => aG.appendChild(svgEl("rect", { x: x(h) + 1, width: cw - 2, y: Y.aBase, height: 0, fill: `url(#hp-${PROD[kk].hatch})`, stroke: "rgba(28,35,41,0.4)", "stroke-width": 0.6, "vector-effect": "non-scaling-stroke" })));
  const hatch = svgEl("rect", { y: Y.eMid - Y.eH - 5, height: Y.aBase + Y.aDn - (Y.eMid - Y.eH - 5) + 2, fill: "url(#hp-fz)", x: 0, width: 0 });
  svg.appendChild(hatch);
  const fline = svgEl("line", { y1: Y.mk + 4, y2: Y.bot, stroke: "#1c2329", "stroke-width": 1.4, "stroke-dasharray": "3 2", "vector-effect": "non-scaling-stroke" });
  svg.appendChild(fline);
  const mkG = g("mk");
  mkG.setAttribute("shape-rendering", "geometricPrecision");
  const marks = d.hours.flatMap((z) => {
    if (z.ftpMw <= 0.05 && z.excusedMw <= 0.05) return [];
    const r = svgEl("rect", { x: x(z.h + 0.5) - 1.5, y: Y.marks - 3, width: 3, height: 6, fill: z.ftpMw > 0.05 ? "#cf3e33" : "#9aa3a9", opacity: 0 });
    r.appendChild(svgEl("title", {})).textContent = z.ftpMw > 0.05 ? `${mwTxt(z.ftpMw)} MW short, charged` : `${mwTxt(z.excusedMw)} MW short, excused`;
    mkG.appendChild(r);
    return [{ h: z.h, e: r }];
  });
  const COL = { eea3: "#8e1b14", eea2: "#cf3e33", eea1: "#e0632c", cons: "#d9820b", watch: "#d9a30b", warn: "#b5487a", adv: "#c9b23a", ocn: "#5b7c99", nws: "#7d8ea0", ok: "#1d9a57", off: "#b0b7bb" };
  const wm = d.watches.map((w) => {
    const xx = x(w.t);
    const run = w.kind === "event" && !d.notices.some((n) => n.watch === w.index && !n.deploy);
    const m = svgEl("path", { d: `M${xx - 3.5},${Y.mk + 1} L${xx + 3.5},${Y.mk + 1} L${xx},${Y.mk + 7} Z`, fill: run ? "#fff" : "#1c2329", stroke: run ? "#5b7c99" : "none", "stroke-width": 1.2, "vector-effect": "non-scaling-stroke" });
    m.appendChild(svgEl("title", {})).textContent = `${w.gate != null ? `DAM gate for ${d.dayName(w.gate)} · ` : ""}${run ? "HRRR run moved the guide · " : ""}watch at ${whenText(d, w.min)} · lock to ${whenText(d, w.freezeMin)}`;
    mkG.appendChild(m);
    return { w, m, run };
  });
  const icons = d.notices.filter((n) => !n.deploy && n.revealMin >= T0 * 60 && n.revealMin < H * 60).map((n) => {
    const xx = x(n.revealT);
    const c = svgEl("rect", { x: xx - 3, y: Y.mk + 3.5, width: 6, height: 6, transform: `rotate(45 ${xx} ${Y.mk + 6.5})`, fill: COL[n.badge[1]] || "#7d8ea0", stroke: "#fff", "stroke-width": 1, "vector-effect": "non-scaling-stroke" });
    c.appendChild(svgEl("title", {})).textContent = `${n.badge[0]} · ${n.name || n.source} · public ${whenText(d, n.revealMin)}\n${paraphrase(n)}`;
    mkG.appendChild(c);
    return { at: n.revealT, c };
  }).concat(d.wins.map((z) => {
    const xx = x(z.a / 60);
    const c = svgEl("path", { d: `M${xx + 1},${Y.mk + 2} L${xx - 3},${Y.mk + 8} L${xx},${Y.mk + 8} L${xx - 1.5},${Y.mk + 13} L${xx + 3.5},${Y.mk + 6} L${xx + 0.5},${Y.mk + 6} Z`, fill: DISCHARGE, stroke: "#8a5200", "stroke-width": 0.6 });
    c.appendChild(svgEl("title", {})).textContent = `${PROD[z.product].name} deployed ${whenText(d, z.a)}–${whenText(d, z.b)}`;
    mkG.appendChild(c);
    return { at: z.a / 60, c };
  }));
  const pct = (t) => `${(x(t) / W) * 100}%`;
  const days = Array.from({ length: d.n }, (_, kk) => `<span class="day" style="left:${pct(24 * kk)}">${esc(d.dayName(kk))}</span>`).join("");
  const gates = Array.from({ length: d.n }, (_, kk) => `<span class="gt" style="left:${pct(gateMin(kk) / 60)}" title="DAM gate for ${esc(d.dayName(kk))}">DAM ${esc(d.dayName(kk).split(" ")[0])}</span>`).join("");
  root.innerHTML = `<div class="rows"><span style="top:${(((Y.wTop + Y.wBot) / 2) / Ht) * 100}%">°F</span><span style="top:${(((Y.pTop + Y.pBot) / 2) / Ht) * 100}%">price</span><span style="top:${(Y.eMid / Ht) * 100}%">battery</span>${d.offered.length ? `<span style="top:${((Y.aBase - 5) / Ht) * 100}%">reserves</span>` : ""}</div>
    <div class="hours fc">${days}${gates}</div>
    <div class="legend"><span><i class="ol"></i>day-ahead</span><span><i class="dash"></i>guide P50</span><span><i class="dot"></i>real-time</span><span><i class="olb"></i>DAM position</span><span><i style="background:${CHARGE}"></i>charge</span><span><i style="background:${DISCHARGE}"></i>discharge</span>${d.lite ? "" : `<span><i style="background:${SOLAR}"></i>PV</span>`}<span><i class="tri"></i>front</span><span><i class="hz"></i>lock</span><span><i class="wk"></i>watch</span><span><i class="wk run"></i>HRRR</span></div>`;
  const plot = el("div", "plot");
  plot.append(svg);
  const ph = el("div", "ph");
  plot.append(ph);
  root.append(plot);
  const P = d.P;
  let lastS = -1, lastW = -1, lastG = "";
  return {
    root, svg, W, tOfX,
    update(t, settled, w) {
      ph.style.left = pct(Math.max(T0, Math.min(H, t)));
      const gk = `${Math.floor(t * 4)}`;
      if (gk !== lastG) {
        lastG = gk;
        const pts = [];
        for (let h = 0; h < H; h++) {
          const kk = Math.floor(h / 24);
          if (t >= resultsMin(kk) / 60 + 0.5) continue;
          const v = d.vint.latest("price", d.task.settlement_point, t);
          const p = v?.fields.da_p50?.[h - v.h0];
          if (p != null) pts.push(`${x(h)},${py(p)} ${x(h + 1)},${py(p)}`);
        }
        guide.setAttribute("points", pts.join(" "));
      }
      if (settled === lastS && w.index === lastW) return;
      lastS = settled;
      lastW = w.index;
      dots.forEach((c, h) => c.setAttribute("opacity", h < settled ? 1 : 0));
      daR.forEach((r, h) => r.setAttribute("opacity", t >= resultsMin(Math.floor(h / 24)) / 60 + 0.5 ? 1 : 0));
      const snap = d.snaps[w.index];
      for (let h = 0; h < H; h++) {
        const z = d.hours[h];
        const e = h < settled ? z.batt : +snap.book.energy[h] || 0;
        const hh = Math.min(Y.eH, (Math.abs(e) / P) * Y.eH);
        eR[h].setAttribute("y", e > 0 ? Y.eMid - hh : Y.eMid);
        eR[h].setAttribute("height", Math.abs(e) > 0.05 ? Math.max(1, hh) : 0);
        eR[h].setAttribute("fill", e > 0 ? DISCHARGE : CHARGE);
        eR[h].setAttribute("opacity", h < settled ? 1 : 0.5);
        const ed = snap.eda[h];
        const hd = ed == null ? 0 : Math.min(Y.eH + 2, (Math.abs(ed) / P) * Y.eH);
        daE[h].setAttribute("y", ed > 0 ? Y.eMid - hd : Y.eMid);
        daE[h].setAttribute("height", ed != null && Math.abs(ed) > 0.05 ? Math.max(0.8, hd) : 0);
        let up = Y.aBase;
        for (const kk of d.offered) {
          const v = h < settled ? z.awards[kk] : +(snap.awards[kk]?.[h] ?? 0);
          const r = aR[kk][h];
          if (kk === "regdn") {
            r.setAttribute("y", Y.aBase);
            r.setAttribute("height", v > 0.05 ? Math.max(0.8, (v / P) * Y.aDn) : 0);
          } else {
            const hu = (v / P) * Y.aUp;
            up -= hu;
            r.setAttribute("y", up);
            r.setAttribute("height", v > 0.05 ? Math.max(0.8, hu) : 0);
          }
          r.setAttribute("opacity", h < settled ? 1 : 0.55);
        }
      }
      for (const m of marks) m.e.setAttribute("opacity", m.h < settled || t >= H ? 1 : 0);
      const fz = t < 0 ? 0 : Math.max(settled, Math.min(H, w.freezeH));
      freeze.setAttribute("x", x(settled));
      freeze.setAttribute("width", Math.max(0, x(fz) - x(settled)));
      hatch.setAttribute("x", x(settled));
      hatch.setAttribute("width", Math.max(0, x(fz) - x(settled)));
      const showF = t >= 0 && t < H && w.freezeH > settled && w.freezeH <= H;
      fline.setAttribute("x1", x(w.freezeH));
      fline.setAttribute("x2", x(w.freezeH));
      fline.setAttribute("opacity", showF ? 1 : 0);
      for (const { w: ww, m, run } of wm) m.setAttribute("opacity", ww.t <= t + 1e-9 ? 1 : run ? 0.35 : 0.3);
      for (const { at, c } of icons) c.setAttribute("opacity", at <= t + 1e-9 ? 1 : 0.3);
    },
  };
}
