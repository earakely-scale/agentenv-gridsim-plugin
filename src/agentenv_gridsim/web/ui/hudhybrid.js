import { hourLabel, money, price } from "../data.js";
import { clockMin, ERA, hourSpan, laneAt, PROD, RULES, UP } from "../hybrid.js";
import { describe, weatherAt } from "../stage/weather.js";
import { ATTRIBUTION, modelName } from "./hud.js";
import { clockText } from "./hudlive.js";

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
const plain = (min) => clockText(min, { small: false });
const mwTxt = (v) => (Math.abs(v) < 10 ? Math.abs(v).toFixed(1) : String(Math.round(Math.abs(v))));
const mwh = (v) => `${Math.round(v)} MWh`;
const sgn = (v) => (v > 0.005 ? "+" : v < -0.005 ? "−" : "");
const CHARGE = "#2fd3ff", DISCHARGE = "#ffa62b", SOLAR = "#efe0a8", SOLAR_EDGE = "#b8973c";
const INK = "rgba(28,35,41,0.62)";
const reward = (p, idle, anchor) => (anchor - idle > 1e-6 ? Math.max(0, Math.min(1, 0.2 + (0.8 * (p - idle)) / (anchor - idle))) : null);

/** Hatches for the reserve products (ink on transparent), shared by every SVG on the page. */
export function hatchDefs() {
  const line = (id, rot, w = 1.6, gap = 4.5) => `<pattern id="hp-${id}" width="${gap}" height="${gap}" patternUnits="userSpaceOnUse" patternTransform="rotate(${rot})"><rect width="${w}" height="${gap}" fill="${INK}"/></pattern>`;
  return `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>${line("fwd", 45)}${line("back", -45)}${line("rows", 90, 1.4, 4)}
    <pattern id="hp-cross" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.3" height="5" fill="${INK}"/><rect width="5" height="1.3" fill="${INK}"/></pattern>
    <pattern id="hp-dots" width="4.5" height="4.5" patternUnits="userSpaceOnUse"><circle cx="2.2" cy="2.2" r="1.05" fill="${INK}"/></pattern>
    <pattern id="hp-curt" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="1.8" height="5" fill="${SOLAR_EDGE}"/></pattern>
    <pattern id="hp-fz" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="rgba(28,35,41,0.22)"/></pattern></defs></svg>`;
}

/** The cards over a solar-plus-storage day: the place card with the SoC and its reserve bands, the panels and the
 * meter; settlement; bulletins; the race; the reserve book; how it planned; the score; the 24-hour timeline. */
export function buildHybridHud(root, d, { onSeek, onToggle }) {
  const ep = d.ep;
  root.insertAdjacentHTML("beforeend", hatchDefs());
  const left = el("div", "left-col");
  const place = el("section", "card place hyb");
  const pnl = el("section", "card pnl");
  const bulls = el("div", "bulletins");
  left.append(place, pnl, bulls);
  const news = el("div", "news off");
  const right = el("aside", "right");
  const race = el("section", "card race");
  const book = el("section", "card asbook");
  const think = el("section", "card think planlog");
  right.append(race, ...(d.offered.length ? [book] : []), think);
  const timeline = el("section", "card timeline live hyb");
  const attrib = el("div", "attrib", ATTRIBUTION.replace("ERCOT DAM settlement point prices", "ERCOT DAM and real-time settlement point prices, DAM AS clearing prices") + " Solar: ERCOT system-wide availability (proxy). Bulletins: paraphrased ERCOT and NWS notices.");
  const back = el("a", "back-link", "← All runs");
  back.href = "./index.html";
  const intro = el("section", "card intro live-intro hyb");
  root.append(left, news, right, timeline, attrib, back, intro);

  const name = modelName(ep.model, ep.model_label);
  const lanes = [{ k: "agent", label: name, cum: d.agentCum, final: ep.profit_usd }, ...d.lanes];
  const lo = Math.min(0, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const hi = Math.max(1, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const zx = (v) => ((v - lo) / (hi - lo)) * 100;
  const cls = { agent: "agent", anchor: "opt", hind: "hind", energy: "base", as_hog: "base" };
  race.innerHTML = `<h5>Race against the references <span class="v2tag">v3 preview</span></h5>` + lanes.map((l) => `<div class="lane ${cls[l.k] || "base"} ${l.k}" data-k="${l.k}"><div class="who">${l.k === "agent" ? `<b>${esc(l.label)}</b>` : esc(l.label)}</div><div class="track"><i class="z" style="left:${zx(0)}%"></i><span></span></div><div class="v num"></div></div>`).join("") +
    `<svg class="spark" viewBox="0 0 240 70" preserveAspectRatio="none"></svg><div class="score live hyb" hidden></div>`;
  intro.innerHTML = introHtml(d, name);
  const anchorLane = d.lanes.find((l) => l.k === "anchor");
  const ab = d.offered.length ? bookStrip(d) : null;
  if (ab) {
    book.innerHTML = `<h5>Reserve book <small>MW by hour · ${ep.tier === "reserves" ? "sold day-ahead, fixed after 2 pm" : "re-optimisable"}</small></h5>`;
    book.append(ab.root);
  }

  const tl = buildTimeline(d);
  timeline.innerHTML = `<div class="ctl"><div class="row"><button class="play" data-a="play">▶ Play</button><button data-a="director" class="on" title="Automatic camera (D)">Director</button></div>
    <div class="row speeds">${[0.5, 1, 2, 4].map((s, i) => `<button data-s="${s}" title="${i + 1}">${s === 0.5 ? "½" : s}×</button>`).join("")}</div>
    <div class="row"><button data-a="charts" title="C">Charts</button><button data-a="settings">Settings</button><button data-a="link" title="Copy a link to this hour">Link</button></div></div>`;
  timeline.append(tl.root);
  const seekAt = (e) => {
    const r = tl.svg.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(24, ((e.clientX - r.left) / r.width) * 24)));
  };
  let drag = false;
  tl.root.addEventListener("pointerdown", (e) => ((drag = true), tl.root.setPointerCapture(e.pointerId), seekAt(e)));
  tl.root.addEventListener("pointermove", (e) => drag && seekAt(e));
  tl.root.addEventListener("pointerup", () => (drag = false));
  timeline.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => onToggle(btn.dataset.a || "speed", btn.dataset.s ? +btn.dataset.s : null)));

  const events = newsEvents(d);
  let lastKey = "", lastPlan = -1, lastEv = null, lastBook = "";
  function update(t, { playing, speed, directing }) {
    const min = clockMin(t);
    const pre = t < 0, ended = t >= 24;
    const x = pre ? d.pre(t) : d.at(Math.min(23.999, t));
    const w = d.watchAt(t);
    const settled = Math.max(0, Math.min(24, Math.floor(t + 1e-9)));
    const key = [Math.floor(t * 30), w.index, playing, speed, directing].join("|");
    if (key !== lastKey) {
      lastKey = key;
      const wx = weatherAt(d.weather, Math.max(0, Math.min(24, t)));
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
        const v = laneAt(l.cum, t, l.final);
        const row = race.querySelector(`.lane[data-k="${l.k}"]`);
        const s = row.querySelector("span");
        const a = zx(Math.min(0, v)), c = zx(Math.max(0, v));
        s.style.left = `${a}%`;
        s.style.width = `${Math.max(0.5, c - a)}%`;
        row.querySelector(".v").textContent = money(v);
      }
      race.querySelector(".spark").innerHTML = spark(lanes, Math.min(24, Math.max(0, t)), lo, hi);
      const score = race.querySelector(".score");
      score.hidden = !ended;
      if (ended) score.innerHTML = scoreHtml(d, lanes);
      if (w.index !== lastPlan || ended) {
        lastPlan = w.index;
        think.innerHTML = planHtml(d, t);
        const cur = think.querySelector(".wrow.now");
        if (ended) think.scrollTop = think.scrollHeight;
        else if (cur) think.scrollTop = Math.max(0, cur.offsetTop - think.clientHeight + cur.offsetHeight + 8);
      }
      const bk = `${pre ? -1 : Math.min(23, Math.floor(t))}|${w.index}|${ended}`;
      if (ab && bk !== lastBook) (lastBook = bk), ab.update(t, w, settled);
      timeline.querySelector(".play").textContent = playing ? "❚❚ Pause" : "▶ Play";
      timeline.querySelectorAll("[data-s]").forEach((s) => s.classList.toggle("on", +s.dataset.s === speed));
      timeline.querySelector('[data-a="director"]').classList.toggle("on", directing);
      intro.hidden = t >= -0.15;
    }
    const ramp = (a, b) => Math.max(0, Math.min(1, (t - a) / (b - a)));
    news.style.opacity = lastEv ? Math.min(ramp(lastEv.t, lastEv.t + 0.08), 1 - ramp(lastEv.until - 0.08, lastEv.until)) : 0;
    intro.style.opacity = 1 - ramp(-0.45, -0.15);
    intro.style.setProperty("--pos", 0.25 + 0.75 * ramp(-1.45, -1.2));
    tl.update(t, settled, w);
  }
  return { update, place, timeline };
}

function socSvg(d, x, ghost) {
  const W = 368, H = 30, y0 = 6, bh = 16, sx = (v) => (Math.max(0, Math.min(d.E, v)) / d.E) * W;
  const fill = sx(x.soc);
  let s = `<rect x="0" y="${y0}" width="${W}" height="${bh}" rx="5" fill="#e1e5e2"/><rect x="0" y="${y0}" width="${fill}" height="${bh}" rx="5" fill="url(#socfill)"/>`;
  let a = 0;
  const short = x.floor > x.soc + 0.5;
  for (const b of x.bands) {
    const w = sx(b.mwh);
    if (w < 0.6) continue;
    const p = PROD[b.k];
    s += `<rect x="${a}" y="${y0}" width="${w}" height="${bh}" fill="url(#hp-${p.hatch})" stroke="${short ? "#cf3e33" : "rgba(28,35,41,0.55)"}" stroke-width="${short ? 1.6 : 1}" class="${b.live ? "live" : ""}"/>`;
    if (w > 13) s += `<text x="${a + w / 2}" y="${y0 + bh / 2 + 3.6}" class="gl">${p.glyph}</text>`;
    a += w;
  }
  if (x.head > 0.3) {
    const w = sx(x.head);
    s += `<rect x="${W - w}" y="${y0}" width="${w}" height="${bh}" fill="url(#hp-dots)" stroke="rgba(28,35,41,0.55)"/>`;
    if (w > 13) s += `<text x="${W - w / 2}" y="${y0 + bh / 2 + 3.6}" class="gl">D</text>`;
  }
  const end = sx(d.site.bess.s_end_min_mwh);
  if (end > 0) s += `<line x1="${end}" x2="${end}" y1="2" y2="${y0 + bh + 3}" stroke="#d08a00" stroke-width="2"/>`;
  if (ghost != null) s += `<line x1="${sx(ghost)}" x2="${sx(ghost)}" y1="1" y2="${y0 + bh + 5}" stroke="#1c2329" stroke-width="1.4" stroke-dasharray="2 2"/><path d="M${sx(ghost) - 3.5},0 L${sx(ghost) + 3.5},0 L${sx(ghost)},4.5 Z" fill="#1c2329" opacity="0.55"/>`;
  return `<svg class="socsvg" viewBox="0 0 ${W} ${H}"><defs><linearGradient id="socfill"><stop offset="0" stop-color="#2bc271"/><stop offset="1" stop-color="#5fd893"/></linearGradient></defs>${s}</svg>`;
}

function barSvg(segs, W = 160, H = 12) {
  return `<svg class="mini" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><rect width="${W}" height="${H}" rx="3" fill="#e3e6e3"/>${segs.map(([a, b, fill, stroke]) => (b - a > 0.2 ? `<rect x="${a * W}" y="0" width="${(b - a) * W}" height="${H}" fill="${fill}" ${stroke ? `stroke="${stroke}" stroke-width="0.8"` : ""}/>` : "")).join("")}</svg>`;
}

function placeHtml(d, x0, t, min, settled, lastRt, hot, wx, anchor) {
  const ended = t >= 24, pre = t < 0, ep = d.ep;
  const x = ended ? { ...x0, bands: [], head: 0, floor: 0 } : x0;
  const mw = Math.abs(x.net);
  const dep = x.dep > 0.1 ? x.events.filter((e) => min >= e.from && min < e.to).map((e) => PROD[e.product].name) : [];
  const upMw = UP.reduce((a, k) => a + x.awards[k], 0);
  const act = pre ? (t < -1.2 ? "The day before: planning" : "Day-ahead book committed") : ended ? "Day over" :
    dep.length ? `Discharging ${mwTxt(mw)} MW · ${dep.join(" and ")} deployed` :
    x.mode === "charge" ? `Charging ${mwTxt(mw)} MW${x.fromPv > mw - 0.5 ? " from the panels" : x.fromPv > 0.5 ? `, ${mwTxt(x.fromPv)} from the panels` : x.price < 0 ? `, paid ${price(-x.price)}/MWh to take it` : " from the grid"}` :
    x.mode === "discharge" ? `Discharging ${mwTxt(mw)} MW` :
    upMw + x.awards.regdn > 0.5 ? `Holding ${[upMw > 0.5 && `${mwTxt(upMw)} MW up`, x.awards.regdn > 0.5 && `${mwTxt(x.awards.regdn)} MW RegDn`].filter(Boolean).join(" and ")} in reserve` : "Idle";
  const era = ERA[d.era];
  const ghost = anchor && !pre && !ended ? anchor.soc[x.h] + (anchor.soc[x.h + 1] - anchor.soc[x.h]) * x.u : null;
  const held = x.bands.filter((b) => b.mwh > 0.5).map((b) => `<span class="gl">${PROD[b.k].glyph}</span>${PROD[b.k].name} ${mwh(b.mwh)}`).join(" · ");
  const room = x.head > 0.5 ? `<span class="gl">D</span>RegDn room ${mwh(x.head)}` : "";
  const bandLine = ended ? `ends at ${Math.round(x.soc)} MWh; the obligation is ${Math.round(d.site.bess.s_end_min_mwh)}` : pre ? "" : [held && `held for ${held}`, room].filter(Boolean).join(" · ");
  const pvA = x.pvAvail, pvU = x.pvUsed;
  const L = d.L, toBat = Math.max(0, Math.min(x.exp, x.net)), pvOut = Math.max(0, x.exp - toBat);
  const panels = pvA < 0.5 ? "no sun" : x.stow && !pre ? `stowed: price ${price(x.price)}/MWh` : `${mwTxt(pvU)} MW${x.curtailed > 0.5 && !pre ? ` · ${mwTxt(x.curtailed)} curtailed` : ""}`;
  const meter = x.exp < -0.5 ? `importing ${mwTxt(x.exp)} MW` : `${mwTxt(x.exp)} of ${Math.round(L)} MW`;
  return `<div class="where">${d.dateLabel} · <b>${esc(d.task.settlement_point)}</b> · ${esc(d.place.name)}<span class="tier hyb">V3 · ${esc(ep.tier.toUpperCase())}</span><span class="era e${d.era}" title="${esc(era[1])}">${esc(era[0])}</span></div>
    <div class="big"><span class="clock num">${ended ? "End of day" : clockText(min)}</span>${pre ? "" : lastRt == null ? `<span class="price num dim-price">${price(d.prices[x.h])}<small>/MWh DA</small></span>` : `<span class="price num ${lastRt < 0 ? "neg" : hot ? "hot" : ""}">${price(lastRt)}<small>/MWh RT</small></span>`}</div>
    <div class="where" style="margin-top:-2px">${pre ? "the day before · the day-ahead book is due at 2 pm" : lastRt == null ? "day-ahead price; the first real-time price settles at 1 am" : `real time, ${hourSpan(settled - 1)} settled · day-ahead ${price(d.prices[settled - 1])}`}</div>
    <div class="act ${ended ? "" : dep.length ? "discharge" : x.mode}"><i></i><span>${act}</span></div>
    <div class="soc hyb"><div class="row"><span>State of charge</span><span><b class="num">${Math.round((x.soc / d.E) * 100)}%</b> · ${Math.round(x.soc)} of ${Math.round(d.E)} MWh</span></div>
      ${socSvg(d, x, ghost)}<div class="bands">${bandLine || (pre ? "reserves are booked at 2 pm" : "no reserves this hour")}${ghost != null ? '<span class="gh">┆ anchor</span>' : ""}</div></div>
    <div class="plantrow"><div><span>Panels</span><b class="num">${panels}</b>${barSvg([[0, Math.min(1, pvU / d.pvMwac), SOLAR, SOLAR_EDGE], [pvU / d.pvMwac, Math.min(1, pvA / d.pvMwac), "url(#hp-curt)"]])}</div>
      <div><span>Meter</span><b class="num">${meter}</b>${barSvg(x.exp < 0 ? [[0, Math.min(1, -x.exp / d.Limp), CHARGE]] : [[0, pvOut / L, SOLAR, SOLAR_EDGE], [pvOut / L, Math.min(1, (pvOut + toBat) / L), DISCHARGE], [Math.max(0, 1 - upMw / L), 1, "url(#hp-fwd)"]])}</div></div>
    <div class="meta">PV ${d.site.pv_mwac} MWac / ${d.site.pv_mwdc} MWdc · battery ${d.P} MW / ${d.E} MWh · meter ${Math.round(L)} MW · ${describe(wx) || "weather n/a"}</div>`;
}

function pnlHtml(d, t, settled, ended) {
  const hs = d.hours.slice(0, ended ? 24 : settled);
  const s = (k) => hs.reduce((a, x) => a + x.cashParts[k], 0);
  const c = ended ? d.ep.cash : null;
  const pen = ended ? c.end_penalty || 0 : null;
  const exc = hs.reduce((a, x) => a + x.excusedUsd, 0);
  const total = hs.reduce((a, x) => a + x.cash, 0) + (ended ? 0 : 0);
  const row = (k, v, cl = "") => `<div class="r ${cl}"><span>${k}</span><b class="num">${v}</b></div>`;
  const sm = (v) => (Math.abs(v) < 0.5 ? "$0" : money(v, { sign: true }));
  const dep = s("dep"), ftp = s("ftp");
  return `<h5>Settlement so far <small>${ended ? "24 of 24 hours" : `${settled} of 24 hours`}</small></h5>
    ${row("Energy, day-ahead", sm(s("energy_da")))}
    ${row("Energy, real-time deviation", sm(s("energy_rt")), s("energy_rt") < -0.5 ? "bad" : s("energy_rt") > 0.5 ? "good" : "")}
    ${d.offered.length ? row("Reserves (AS), day-ahead", sm(s("as"))) : ""}
    ${d.offered.length ? row("Deployment energy", sm(dep)) : ""}
    ${row("Degradation", s("deg") < 0.5 ? "$0" : money(-s("deg")))}
    ${d.offered.length ? row("Failure to provide", ftp > 0.5 ? money(-ftp) : "$0", ftp > 0.5 ? "bad" : "") : ""}
    ${row("End-of-day shortfall", pen == null ? "at midnight" : pen ? money(-pen) : "$0", pen ? "bad" : "")}
    ${exc > 0.5 ? row("Excused (not charged)", money(exc), "dim") : ""}
    ${row("Total", money(ended ? d.ep.profit_usd : total), "total")}`;
}

function bulletinsHtml(d, t) {
  const got = d.notices.map((n) => ({ n, at: n.deploy ? Math.max(0, n.deploy.start_min) / 60 : n.deliverT })).filter((z) => z.at != null && z.at <= t + 1e-9 && (z.n.deploy || z.n.deliverT != null));
  if (!got.length) return "";
  const lastAt = got.at(-1).at;
  const recent = got.filter((z) => t - z.at < 2 || z.at === lastAt).sort((a, b) => a.at - b.at);
  const shown = recent.slice(-2).reverse();
  return shown.map(({ n, at }, i) => {
    const fresh = i === 0 && t - at < 0.75;
    const issued = n.issued.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }).toLowerCase();
    let text = n.text, when = `issued ${issued}${n.watch === 0 ? " · on the board" : n.watch != null ? ` · read at ${plain(d.watches[n.watch].min)}` : ""}`;
    if (n.deploy) {
      const h = Math.min(23, Math.floor(n.deploy.start_min / 60)), aw = d.hours[h].awards[n.deploy.product] || 0, k = PROD[n.deploy.product];
      const win = d.wins.find((z) => z.n.event_id === n.event_id);
      const hrs = win ? (win.b - win.a) / 60 : 0;
      text = aw > 0.05 ? `${k.name} deployed ${plain(n.deploy.start_min)} · ${mwTxt(aw * n.deploy.frac)} MW for ${hrs >= 0.95 ? `${+hrs.toFixed(1)} h` : `${Math.round(hrs * 60)} min`}: the reserved band drains to the line.` : `ERCOT deploys ${k.name} at ${plain(n.deploy.start_min)}; this plant holds none then.`;
      when = `the agent learns of it ${n.watch != null ? `at the ${plain(d.watches[n.watch].min)} watch` : "after the day"}`;
    }
    return `<div class="card bul ${fresh ? "fresh" : ""} ${n.deploy ? "dep" : ""}"><div class="bh"><span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span><span class="src">${esc(n.name || n.source)}</span><span class="when">${esc(when)}</span></div><p>${esc(text)}</p></div>`;
  }).join("") + (got.length > shown.length ? `<div class="more-b">${got.length - shown.length} earlier bulletin${got.length - shown.length > 1 ? "s" : ""} in the timeline</div>` : "");
}

const CALL = { check_schedule: "check", commit_schedule: "commit" };

function planHtml(d, t) {
  const cur = d.watchAt(t);
  const rows = d.watches.filter((w) => w.t <= t + 1e-9 || t >= 24).map((w) => {
    const ns = d.notices.filter((n) => n.watch === w.index && !/cancel/i.test(n.title || ""));
    const pills = w.calls.map((s) => {
      const o = s.output || {};
      if (o.error) return `<span class="pill no">${CALL[s.tool]} ✗ · ${esc(o.error.slice(0, 40))}</span>`;
      if (s.tool === "check_schedule") return `<span class="pill ${o.feasible ? "ok" : "no"}">check ${o.feasible ? "✓" : `✗ ${(o.issues || []).length} issue${(o.issues || []).length === 1 ? "" : "s"}`}</span>`;
      const got = o.committed || [], bad = o.refused || [];
      const span = got.length ? ` ${hourLabel(got[0])}–${hourLabel(got.at(-1) + 1)}` : "";
      const why = bad.length ? ` · refused ${[...new Set(bad.map((r) => r.hour))].length}h: ${[...new Set(bad.map((r) => r.rule))].map((r) => esc(r)).join(", ")}` : "";
      return `<span class="pill ${got.length ? (bad.length ? "part" : "ok") : "no"}" title="${esc(bad.slice(0, 4).map((r) => `${r.hour}: ${r.detail}`).join("\n"))}">commit ${got.length ? "✓" : "✗"}${span}${why}</span>`;
    }).join("");
    return `<div class="wrow ${w.index === cur.index && t < 24 ? "now" : ""}"><span class="wt">${w.index === 0 ? "2 pm, day before" : plain(w.min)}</span><span class="wc">${ns.slice(0, 2).map((n) => `<span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span>`).join("")}${pills || '<span class="pill idle">held the book</span>'}</span></div>`;
  }).join("");
  const n = d.watches.reduce((a, w) => a + w.calls.length, 0);
  const rules = {};
  for (const w of d.watches) if (w.t <= t + 1e-9 || t >= 24) for (const r of w.refused) rules[r.rule] = (rules[r.rule] || 0) + 1;
  const ruleLine = Object.keys(rules).length ? `<div class="rules">Refused hours by rule: ${Object.entries(rules).sort((a, b) => b[1] - a[1]).map(([r, k]) => `<b>${esc(r)}</b> ${k} <span class="dim">(${esc(RULES[r] || r)})</span>`).join(" · ")}</div>` : "";
  const said = (d.ep.messages || []).filter((m) => m.role === "assistant" && m.content).map((m) => m.content);
  const msg = (t < 0 ? said.slice(0, 1) : said.slice(-2)).map((m) => `<blockquote>“${esc(m.slice(0, 240))}${m.length > 240 ? "…" : ""}”</blockquote>`).join("");
  return `<h5>How it planned <small>${d.watches.length} watches · ${n} planning call${n === 1 ? "" : "s"}</small></h5><div class="wlist">${rows}</div>${ruleLine}${t >= 24 || t < 0 ? msg : ""}`;
}

function scoreHtml(d, lanes) {
  const ep = d.ep, R = ep.reward ?? 0, ref = ep.references || {}, w0 = d.weight0;
  const pi = ref.p_idle, pa = ref.p_anchor;
  const pos = (r) => `${Math.max(0, Math.min(1, r)) * 100}%`;
  const ticks = [["energy", "energy-only"], ["as_hog", "AS-hog"]].map(([k, lab]) => {
    const l = lanes.find((x) => x.k === k);
    const r = l ? reward(l.final, pi, pa) : null;
    return r == null ? "" : `<i class="tick n" style="left:${pos(r)}" title="${lab} ${r.toFixed(2)}"></i>`;
  }).join("");
  const cap = (k) => {
    const l = lanes.find((x) => x.k === k);
    const r = l ? reward(l.final, pi, pa) : null;
    return r == null ? "" : `${k === "energy" ? "energy-only" : "AS-hog"} ${r.toFixed(2)} · `;
  };
  const self = ep.model === "reference/rolling-anchor" ? "This is the rolling anchor: R is 1 by definition." : ep.beats_anchor ? "Beats the rolling anchor." : "Does not beat the rolling anchor.";
  const vs = lanes.find((l) => l.k === "anchor");
  const rel = vs ? ` vs the anchor <b class="${ep.profit_usd - vs.final >= 0 ? "good" : "bad"}">${money(ep.profit_usd - vs.final, { sign: true })}</b>` : "";
  const pct = (v) => (v == null ? "—" : `${Math.round(v * 100)}%`);
  const cells = [
    ["Hindsight", pct(w0.capture), `of ${money((ref.p_hind ?? 0) - (pi ?? 0))} over idle`],
    ["AS share", d.offered.length ? pct(w0.asShare) : "—", "of revenue over idle"],
    ["Clip saved", w0.clipPct == null ? "n/a" : `${Math.round(w0.clipPct)}%`, w0.clipPct == null ? "meter ≥ PV AC" : "of PV over the meter"],
    ["Curtailed", `${Math.round(w0.curtailed)} MWh`, "PV held back"],
    ["Short (FTP)", `${w0.ftpMwh.toFixed(1)} MWh`, `charged · ${w0.excusedMwh.toFixed(1)} excused`],
    ["Governor", `${w0.governor} h`, "moves clipped"],
  ];
  return `<div class="pair"><div><div class="lbl">R · anchor scale</div><div class="r num">${R.toFixed(3)}</div>
      <div class="rscale"><span class="fill" style="width:${pos(R)}"></span><i class="tick" style="left:20%" title="idle"></i>${ticks}<i class="tick a" style="left:100%" title="anchor"></i></div>
      <div class="cap">idle 0.2 · ${cap("energy")}${cap("as_hog")}anchor 1.0</div></div>
    <div class="second"><div class="lbl">Profit</div><div class="r num">${money(ep.profit_usd)}</div><div class="cap">anchor ${money(pa ?? 0)} · hindsight ${money(ref.p_hind ?? 0)}</div></div></div>
    <div class="w0">${cells.map(([k, v, c]) => `<div><span>${k}</span><b class="num">${v}</b><em>${c}</em></div>`).join("")}</div>
    <div class="line">${self}${rel}</div>
    <div class="line dim">v3 preview · weight-0 rows are reported, not scored. PV is a system-wide proxy; regulation drift is a seeded draw.</div>`;
}

function spark(lanes, t, lo, hi) {
  const W = 240, H = 70;
  const y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  let s = `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.15)"/>`;
  const n = Math.min(24, Math.ceil(t));
  for (const l of lanes) {
    const pts = [[0, 0], ...l.cum.slice(0, n).map((v, i) => [Math.min(t, i + 1), i + 1 > t ? laneAt(l.cum, t, l.final) : v])];
    const col = l.k === "agent" ? "#2c3440" : l.k === "anchor" ? "rgba(28,35,41,0.45)" : l.k === "hind" ? "rgba(29,154,87,0.45)" : "rgba(28,35,41,0.2)";
    s += `<polyline fill="none" stroke="${col}" stroke-width="${l.k === "agent" ? 2.2 : 1.5}" ${l.k === "anchor" || l.k === "hind" ? 'stroke-dasharray="4 3"' : ""} points="${pts.map(([i, v]) => `${(i / 24) * W},${y(v)}`).join(" ")}"/>`;
  }
  return s;
}

/** The reserve book per product and hour: ink density by MW, deployments, failures to provide and excuses marked. */
function bookStrip(d) {
  const ks = d.offered, W = 336, lab = 52, cw = (W - lab) / 24, rh = 13, H = ks.length * rh + 14;
  const root = el("div", "bookstrip");
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}` });
  const cells = {};
  ks.forEach((k, r) => {
    const t = svgEl("text", { x: 2, y: r * rh + 10, class: "gl2" });
    t.textContent = PROD[k].glyph;
    svg.appendChild(t);
    const nm = svgEl("text", { x: 11, y: r * rh + 10, class: "nm" });
    nm.textContent = PROD[k].name;
    svg.appendChild(nm);
    cells[k] = Array.from({ length: 24 }, (_, h) => {
      const c = svgEl("rect", { x: lab + h * cw + 0.5, y: r * rh + 1, width: cw - 1, height: rh - 2, rx: 1.5, fill: "rgba(28,35,41,0.05)" });
      svg.appendChild(c);
      return c;
    });
  });
  for (const x of d.hours) {
    if (x.ftpMw > 0.05) svg.appendChild(svgEl("rect", { x: lab + x.h * cw + 0.5, y: 0.5, width: cw - 1, height: ks.length * rh, fill: "none", stroke: "#cf3e33", "stroke-width": 1.2, rx: 2, class: "ftp", opacity: 0 }));
    else if (x.excusedMw > 0.05) svg.appendChild(svgEl("rect", { x: lab + x.h * cw + 0.5, y: 0.5, width: cw - 1, height: ks.length * rh, fill: "none", stroke: "#7a868e", "stroke-width": 1, "stroke-dasharray": "2 1.5", rx: 2, class: "exc", opacity: 0 }));
    for (const e of x.events) {
      const r = ks.indexOf(e.product);
      if (r < 0) continue;
      svg.appendChild(svgEl("path", { d: `M${lab + x.h * cw + cw / 2 - 3},${r * rh + 3} L${lab + x.h * cw + cw / 2 + 3},${r * rh + 3} L${lab + x.h * cw + cw / 2},${r * rh + 9} Z`, fill: DISCHARGE, class: "depm", opacity: 0, "data-h": x.h }));
    }
  }
  const now = svgEl("rect", { y: 0, height: ks.length * rh, width: cw, fill: "none", stroke: "#1c2329", "stroke-width": 1.4, rx: 2 });
  svg.appendChild(now);
  [0, 6, 12, 18].forEach((h) => {
    const t = svgEl("text", { x: lab + h * cw, y: H - 2, class: "hr" });
    t.textContent = hourLabel(h);
    svg.appendChild(t);
  });
  root.append(svg);
  const foot = el("div", "bookfoot");
  root.append(foot);
  return {
    root,
    update(t, w, settled) {
      const book = t < -1.2 ? null : t >= 24 || !d.snaps[w.index] ? null : d.snaps[w.index];
      for (const k of ks)
        for (let h = 0; h < 24; h++) {
          const v = book ? +(book[k]?.[h] ?? 0) : t >= 24 || h < settled ? d.hours[h].awards[k] : 0;
          const a = v > 0.01 ? 0.14 + 0.72 * Math.min(1, v / d.P) : 0.05;
          cells[k][h].setAttribute("fill", `rgba(28,35,41,${a.toFixed(3)})`);
          cells[k][h].setAttribute("opacity", h < settled || t >= 24 ? 1 : 0.8);
        }
      const h = Math.max(0, Math.min(23, Math.floor(t)));
      now.setAttribute("x", lab + h * cw);
      now.setAttribute("opacity", t >= 0 && t < 24 ? 1 : 0);
      svg.querySelectorAll(".ftp, .exc").forEach((r) => r.setAttribute("opacity", +((+r.getAttribute("x") - lab) / cw) < settled || t >= 24 ? 1 : 0));
      svg.querySelectorAll(".depm").forEach((p) => p.setAttribute("opacity", +p.dataset.h <= t || t >= 24 ? 1 : 0));
      const x = d.hours[h];
      const tot = d.offered.reduce((a, k) => a + x.awards[k] * (d.dur[k] ?? 0), 0);
      foot.innerHTML = t < 0 ? (t < -1.2 ? "Sold at 2 pm with the day-ahead position." : "Day-ahead book sold.") : t >= 24 ? `${money(d.ep.cash.as_da + d.ep.cash.as_rt)} of reserve revenue` : `${hourSpan(h)}: ${d.offered.filter((k) => x.awards[k] > 0.05).map((k) => `<span class="gl">${PROD[k].glyph}</span>${mwTxt(x.awards[k])}`).join(" ") || "nothing sold"}${tot > 0.5 ? ` · ${mwh(tot)} of charge or room reserved` : ""}`;
    },
  };
}

function introHtml(d, name) {
  const w0 = d.watches[0], ep = d.ep;
  const board = d.notices.filter((n) => n.watch === 0 && !n.deploy);
  const strip = (vals, col, H = 36) => {
    const lo = Math.min(0, ...vals), hi = Math.max(1e-6, ...vals);
    const y = (v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6);
    const pts = vals.map((v, h) => `${(h / 23) * 560},${y(v)}`).join(" ");
    return `<svg viewBox="0 0 560 ${H + 4}" preserveAspectRatio="none">${lo < 0 ? `<line x1="0" x2="560" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.2)"/>` : ""}<polygon fill="${col}" opacity="0.16" points="0,${H + 4} ${pts} 560,${H + 4}"/><polyline fill="none" stroke="${col}" stroke-width="2" points="${pts}"/></svg>`;
  };
  const da = d.snaps[0];
  const P = d.P;
  const chips = (da?.energy || Array(24).fill(0)).map((a, h) => `<rect x="${(h / 24) * 560 + 1}" y="${a > 0 ? 9 - (a / P) * 8 : 9}" width="${560 / 24 - 2}" height="${Math.max(1, (Math.abs(a) / P) * 8)}" rx="1.5" fill="${a > 0 ? DISCHARGE : a < 0 ? CHARGE : "#cfd5d8"}"/>`).join("");
  const asTot = Array.from({ length: 24 }, (_, h) => d.offered.reduce((s, k) => s + +(da?.[k]?.[h] ?? 0), 0));
  const asChips = asTot.map((v, h) => `<rect x="${(h / 24) * 560 + 1}" y="${18 - Math.min(16, (v / P) * 16)}" width="${560 / 24 - 2}" height="${Math.max(1, Math.min(16, (v / P) * 16))}" rx="1.5" fill="url(#hp-fwd)" stroke="rgba(28,35,41,0.5)" stroke-width="0.6"/>`).join("");
  const durs = d.offered.map((k) => `${PROD[k].name} ${d.dur[k]} h`).join(", ");
  const mcpc = Array.from({ length: 24 }, (_, h) => Math.max(0, ...d.offered.map((k) => ep.task.mcpc_da?.[k]?.[h] ?? 0)));
  return `<h5>The day before · ${plain(w0.min)} · ${esc(d.task.settlement_point)} <span class="era e${d.era}">${esc(ERA[d.era][0])}</span></h5>
    <p><b>${esc(name)}</b> runs a ${d.site.pv_mwac} MWac solar farm and a ${d.P} MW / ${d.E} MWh battery behind one ${Math.round(d.L)} MW meter tomorrow, ${d.dateLabel}. At 2 pm today it sells a <b>day-ahead book</b>: the battery's MW for each hour${d.offered.length ? ` and its <b>reserve awards</b>, each backed by charge for its duration (${durs})` : " (energy tier: no reserves)"}. Tomorrow it re-plans at ${d.watches.length - 1} watches, never inside the <b>1 h lock</b>${ep.tier === "reserves" ? "; the reserves stay as sold" : ""}, while real-time prices settle and ERCOT may deploy what it bought.</p>
    <div class="strip"><span>DA prices</span>${strip(d.prices, "#3a4651")}<em>peak ${price(Math.max(...d.prices))}</em></div>
    <div class="strip"><span>PV available</span>${strip(d.hours.map((x) => x.pvAvail), SOLAR_EDGE)}<em>peak ${Math.round(d.pvPeak)} MW</em></div>
    ${d.offered.length ? `<div class="strip"><span>AS prices</span>${strip(mcpc, "#7a868e")}<em>top ${price(Math.max(...mcpc))}/MW</em></div>` : ""}
    <div class="strip pos"><span>DA battery</span><svg viewBox="0 0 560 18" preserveAspectRatio="none"><line x1="0" x2="560" y1="9" y2="9" stroke="rgba(0,0,0,0.12)"/>${chips}</svg><em>${da?.energy?.some((a) => a) ? "sold" : "none"}</em></div>
    ${d.offered.length ? `<div class="strip pos"><span>DA reserves</span><svg viewBox="0 0 560 18" preserveAspectRatio="none">${asChips}</svg><em>${asTot.some((v) => v > 0.05) ? "sold" : "none"}</em></div>` : ""}
    <p class="dim">${board.length ? `${board.length} bulletin${board.length > 1 ? "s" : ""} on the board: ${board.map((n) => esc(n.badge[0])).join(", ")}.` : "No bulletins on the board."} ${d.notices.some((n) => n.watch > 0) ? "More arrive during the day." : ""}</p>`;
}

/** The headlines: bulletins, deployments at their real time, negative-price stows, a full meter, failures to provide
 * and excuses, governor clips, refused commits naming the rule, re-plans, the real-time spike and the end. */
function newsEvents(d) {
  const ev = [];
  const rank = { eea3: 7, eea2: 6, eea1: 5, cons: 4, watch: 3, warn: 3, adv: 2, ocn: 1, nws: 1, ok: 2, off: 0 };
  for (const w of d.watches) {
    const ns = d.notices.filter((n) => n.watch === w.index && w.index > 0 && !n.deploy);
    if (!ns.length) continue;
    const top = ns.reduce((a, n) => ((rank[n.badge[1]] ?? 0) > (rank[a.badge[1]] ?? 0) ? n : a));
    ev.push({ t: w.t, until: w.t + 1.2, kind: "bulletin", badge: top.badge, text: top.text + (ns.length > 1 ? ` (+${ns.length - 1} more)` : "") });
  }
  for (const z of d.wins) {
    const h = Math.min(23, Math.floor(z.a / 60)), aw = d.hours[h].awards[z.product] || 0, k = PROD[z.product];
    const hrs = (z.b - z.a) / 60;
    ev.push({ t: z.a / 60, until: z.a / 60 + 1.3, kind: "deploy", badge: [`${k.name} deployed`, "dep"], text: aw > 0.05 ? `${k.name} deployed ${plain(z.a)} · ${mwTxt(aw * z.frac)} MW for ${hrs >= 0.95 ? `${+hrs.toFixed(1)} h` : `${Math.round(hrs * 60)} min`}` : `ERCOT deploys ${k.name} at ${plain(z.a)}; this plant holds none then` });
  }
  const st = d.hours.find((x) => x.neg && x.pvAvail > 5 && x.curtailed > 0.9 * x.pvAvail);
  if (st) ev.push({ t: st.h + 0.05, until: st.h + 1.4, kind: "neg", text: `Real-time ${price(st.rt)}/MWh ${hourSpan(st.h)}: the controller stows the panels${st.mode === "charge" ? " and the battery charges at a negative price" : ""}` });
  const full = d.hours.find((x) => !x.neg && x.curtailed > 1 && x.pvAvail > 5);
  if (full) {
    const up = UP.reduce((a, k) => a + full.awards[k], 0);
    ev.push({ t: full.h + 0.05, until: full.h + 1.2, kind: "meter", text: `The meter is full at ${Math.round(d.L)} MW ${hourSpan(full.h)}: ${mwTxt(full.curtailed)} MW of PV curtailed${up > 0.5 ? ` to keep headroom for ${mwTxt(up)} MW of up-reserves` : full.b > 0.5 ? ` while the battery discharges ${mwTxt(full.b)} MW` : ""}` });
  }
  for (const x of d.hours) {
    if (x.ftpMw > 0.05) ev.push({ t: x.h + 0.6, until: x.h + 1.5, kind: "ftp", text: `Short ${mwTxt(x.ftpMw)} MW of reserves ${hourSpan(x.h)}: ${money(x.ftpUsd)} failure to provide` });
    else if (x.excusedMw > 0.05) ev.push({ t: x.h + 0.6, until: x.h + 1.4, kind: "excused", badge: ["Excused", "off"], text: `${mwTxt(x.excusedMw)} MW short ${hourSpan(x.h)}, excused: the drift or deployment came after the hour froze` });
    if (x.governor) ev.push({ t: x.h + 0.08, until: x.h + 0.9, kind: "governor", text: `Governor ${hourSpan(x.h)}: the battery's ${sgn(x.e)}${mwTxt(x.e)} MW is moved to ${sgn(x.b)}${mwTxt(x.b)} MW to keep its awards backed` });
  }
  for (const w of d.watches) {
    const bad = w.refused;
    if (bad.length) {
      const hrs = [...new Set(bad.map((r) => r.hour).filter((h) => h != null))];
      const r0 = bad[0];
      ev.push({ t: Math.max(-1.6, w.t) + 0.04, until: Math.max(-1.6, w.t) + 1.1, kind: "refused", text: `${w.index === 0 ? "2 pm" : plain(w.min)} commit: ${hrs.length ? `hour${hrs.length > 1 ? "s" : ""} ${hrs.slice(0, 4).join(", ")}${hrs.length > 4 ? "…" : ""} refused` : "refused"} · ${r0.rule}: ${r0.detail}` });
    } else if (w.index > 0) {
      const c = w.calls.filter((s) => s.tool === "commit_schedule" && (s.output?.committed || []).length).at(-1);
      if (c) ev.push({ t: w.t + 0.04, until: w.t + 0.9, kind: "replan", text: `At ${plain(w.min)} it re-plans from ${hourLabel(c.output.committed[0])}, past the 1 h lock` });
    }
  }
  const s = d.peakH;
  if (d.rt[s] > Math.max(200, 2.5 * d.prices[s])) ev.push({ t: s + 1, until: s + 2, kind: "peak", text: `Real-time ${price(d.rt[s])}/MWh ${hourSpan(s)}; day-ahead was ${price(d.prices[s])}` });
  if ((d.ep.cash?.end_penalty || 0) > 0.5) ev.push({ t: 23.6, until: 25, kind: "penalty", text: `The day ends below the required charge: a ${money(d.ep.cash.end_penalty)} shortfall` });
  return ev.sort((a, b) => a.t - b.t);
}

/** The 24-hour timeline: watches, bulletins and deployments on top; DA price bars and RT dots as hours settle; the
 * battery's MW (book, then executed) over the PV available; the reserve awards stacked by product hatch; failures to
 * provide and excuses below; the frozen hours and the 1 h lock line. */
function buildTimeline(d) {
  const root = el("div", "tl live hyb");
  const W = 1200, H = 132, cw = W / 24;
  const Y = { mk: 0, pTop: 16, pBot: 48, eMid: 66, eH: 12, aBase: 104, aUp: 18, aDn: 7, marks: 118, bot: 124 };
  const all = [...d.rt, ...d.prices];
  const mx = Math.max(1, ...all.map((p) => Math.abs(p)));
  const k = 40, f = (p) => (Math.sign(p) * Math.log1p(Math.abs(p) / k)) / Math.log1p(mx / k);
  const lo = Math.min(0, ...all.map(f));
  const zero = Y.pTop + (Y.pBot - Y.pTop) * (1 / (1 - lo));
  const py = (p) => zero - f(p) * (zero - Y.pTop);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none" });
  const g = (cls) => svg.appendChild(svgEl("g", { class: cls }));
  const bg = g("bg");
  for (let h = 0; h <= 24; h += 3) bg.appendChild(svgEl("line", { x1: h * cw, x2: h * cw, y1: Y.pTop, y2: Y.bot, stroke: "rgba(28,35,41,0.06)" }));
  bg.appendChild(svgEl("line", { x1: 0, x2: W, y1: zero, y2: zero, stroke: "rgba(0,0,0,0.22)" }));
  bg.appendChild(svgEl("line", { x1: 0, x2: W, y1: Y.eMid, y2: Y.eMid, stroke: "rgba(0,0,0,0.14)" }));
  bg.appendChild(svgEl("line", { x1: 0, x2: W, y1: Y.aBase, y2: Y.aBase, stroke: "rgba(0,0,0,0.14)" }));
  const freeze = svgEl("rect", { y: Y.pTop - 2, height: Y.bot - Y.pTop + 4, fill: "rgba(28,35,41,0.06)", x: 0, width: 0 });
  svg.appendChild(freeze);
  const pvMax = Math.max(1, d.pvMwac);
  const pvPts = d.hours.map((x, h) => `${h * cw},${Y.eMid - (x.pvAvail / pvMax) * (Y.eH + 4)} ${(h + 1) * cw},${Y.eMid - (x.pvAvail / pvMax) * (Y.eH + 4)}`).join(" ");
  svg.appendChild(svgEl("polygon", { points: `0,${Y.eMid} ${pvPts} ${W},${Y.eMid}`, fill: SOLAR, opacity: 0.55 }));
  const pg = g("p");
  d.prices.forEach((p, h) => pg.appendChild(svgEl("rect", { x: h * cw + 3, width: cw - 6, y: Math.min(py(p), zero), height: Math.max(1, Math.abs(py(p) - zero)), rx: 1.5, fill: "none", stroke: "rgba(28,35,41,0.4)", "stroke-width": 1, "vector-effect": "non-scaling-stroke" })));
  const rtG = g("rt");
  rtG.setAttribute("shape-rendering", "geometricPrecision");
  const dots = d.rt.map((p, h) => {
    const c = svgEl("ellipse", { cx: (h + 0.5) * cw, cy: py(p), rx: 5.5, ry: 3.6, fill: p < 0 ? "#7c58b3" : p > Math.max(150, 2 * d.prices[h]) ? "#cf3e33" : "#2c3440", opacity: 0 });
    rtG.appendChild(c);
    return c;
  });
  const eG = g("e");
  const eR = Array.from({ length: 24 }, (_, h) => eG.appendChild(svgEl("rect", { x: h * cw + 4, width: cw - 8, y: Y.eMid, height: 0, rx: 2 })));
  const aG = g("as");
  const aR = {};
  for (const kk of d.offered) aR[kk] = Array.from({ length: 24 }, (_, h) => aG.appendChild(svgEl("rect", { x: h * cw + 6, width: cw - 12, y: Y.aBase, height: 0, fill: `url(#hp-${PROD[kk].hatch})`, stroke: "rgba(28,35,41,0.45)", "stroke-width": 0.8, "vector-effect": "non-scaling-stroke" })));
  const hatch = svgEl("rect", { y: Y.eMid - Y.eH - 6, height: Y.aBase + Y.aDn - (Y.eMid - Y.eH - 6) + 2, fill: "url(#hp-fz)", x: 0, width: 0 });
  svg.appendChild(hatch);
  const fline = svgEl("line", { y1: Y.mk + 4, y2: Y.bot, stroke: "#1c2329", "stroke-width": 1.4, "stroke-dasharray": "3 2", "vector-effect": "non-scaling-stroke" });
  svg.appendChild(fline);
  const mkG = g("mk");
  mkG.setAttribute("shape-rendering", "geometricPrecision");
  const marks = d.hours.flatMap((x) => {
    const out = [];
    if (x.ftpMw > 0.05) {
      const t = svgEl("text", { x: (x.h + 0.5) * cw, y: Y.marks + 5, class: "ftpm", "text-anchor": "middle" });
      t.textContent = "×";
      out.push({ h: x.h, e: t });
    } else if (x.excusedMw > 0.05) {
      const t = svgEl("text", { x: (x.h + 0.5) * cw, y: Y.marks + 5, class: "excm", "text-anchor": "middle" });
      t.textContent = "×";
      t.appendChild(svgEl("title", {})).textContent = `${mwTxt(x.excusedMw)} MW short, excused`;
      out.push({ h: x.h, e: t });
    }
    if (x.governor) {
      const t = svgEl("text", { x: (x.h + 0.5) * cw, y: Y.eMid + Y.eH + 9, class: "govm", "text-anchor": "middle" });
      t.textContent = "gov";
      out.push({ h: x.h, e: t });
    }
    for (const o of out) (o.e.style.opacity = 0), mkG.appendChild(o.e);
    return out;
  });
  const wm = d.watches.slice(1).map((w) => {
    const x = (w.min / 60) * cw;
    const m = svgEl("path", { d: `M${x - 4},${Y.mk + 2} L${x + 4},${Y.mk + 2} L${x},${Y.mk + 8} Z`, fill: "#1c2329" });
    m.appendChild(svgEl("title", {})).textContent = `Watch at ${plain(w.min)} · 1 h lock to ${plain(w.freezeMin)}`;
    mkG.appendChild(m);
    return { w, m };
  });
  const COL = { eea3: "#8e1b14", eea2: "#cf3e33", eea1: "#e0632c", cons: "#d9820b", watch: "#d9a30b", warn: "#b5487a", adv: "#c9b23a", ocn: "#5b7c99", nws: "#7d8ea0", ok: "#1d9a57", off: "#b0b7bb" };
  const icons = d.notices.filter((n) => !n.deploy && n.revealMin >= 0 && n.revealMin < 1440).map((n) => {
    const x = (n.revealMin / 60) * cw;
    const c = svgEl("rect", { x: x - 3.5, y: Y.mk + 4, width: 7, height: 7, transform: `rotate(45 ${x} ${Y.mk + 7.5})`, fill: COL[n.badge[1]] || "#7d8ea0", stroke: "#fff", "stroke-width": 1 });
    c.appendChild(svgEl("title", {})).textContent = `${n.badge[0]} · ${n.name || n.source} · public at ${plain(n.revealMin)}\n${n.text}`;
    mkG.appendChild(c);
    return { at: n.revealT, c };
  }).concat(d.wins.map((z) => {
    const x = (z.a / 60) * cw;
    const c = svgEl("path", { d: `M${x + 1},${Y.mk + 2} L${x - 3},${Y.mk + 8} L${x},${Y.mk + 8} L${x - 1.5},${Y.mk + 13} L${x + 3.5},${Y.mk + 6} L${x + 0.5},${Y.mk + 6} Z`, fill: DISCHARGE, stroke: "#8a5200", "stroke-width": 0.6 });
    c.appendChild(svgEl("title", {})).textContent = `${PROD[z.product].name} deployed ${plain(z.a)}–${plain(z.b)}`;
    mkG.appendChild(c);
    return { at: z.a / 60, c };
  }));
  root.innerHTML = `<div class="rows"><span style="top:${((Y.pTop + Y.pBot) / 2 / H) * 100}%">price</span><span style="top:${(Y.eMid / H) * 100}%">battery</span>${d.offered.length ? `<span style="top:${((Y.aBase - 6) / H) * 100}%">reserves</span>` : ""}</div>
    <div class="hours">${[0, 3, 6, 9, 12, 15, 18, 21].map((h) => `<span style="left:${(h / 24) * 100}%">${hourLabel(h)}</span>`).join("")}</div>
    <div class="legend"><span><i class="ol"></i>day-ahead</span><span><i class="dot"></i>real-time</span><span><i style="background:${SOLAR}"></i>PV</span><span><i style="background:${CHARGE}"></i>charge</span><span><i style="background:${DISCHARGE}"></i>discharge</span>${d.offered.length ? `<span>${d.offered.map((kk) => `<i class="hp ${PROD[kk].hatch}"></i>${PROD[kk].glyph}`).join(" ")}</span>` : ""}<span><i class="hz"></i>1 h lock</span><span><b class="xm">×</b>short<b class="xm ex">×</b>excused</span><span class="dim">log price scale</span></div>`;
  const plot = el("div", "plot");
  plot.append(svg);
  const ph = el("div", "ph");
  plot.append(ph);
  root.append(plot);
  const P = d.P;
  let lastS = -1, lastW = -1;
  return {
    root, svg,
    update(t, settled, w) {
      const tt = Math.max(0, Math.min(24, t));
      ph.style.left = `${(tt / 24) * 100}%`;
      if (settled === lastS && w.index === lastW) return;
      lastS = settled;
      lastW = w.index;
      dots.forEach((c, h) => c.setAttribute("opacity", h < settled ? 1 : 0));
      const book = t < -1.2 ? null : d.snaps[w.index];
      for (let h = 0; h < 24; h++) {
        const x = d.hours[h];
        const e = h < settled ? x.batt : book ? +book.energy[h] : 0;
        const hh = Math.min(Y.eH, (Math.abs(e) / P) * Y.eH);
        eR[h].setAttribute("y", e > 0 ? Y.eMid - hh : Y.eMid);
        eR[h].setAttribute("height", Math.abs(e) > 0.05 ? Math.max(1.2, hh) : 0);
        eR[h].setAttribute("fill", e > 0 ? DISCHARGE : CHARGE);
        eR[h].setAttribute("opacity", h < settled ? 1 : 0.55);
        let up = Y.aBase;
        for (const kk of d.offered) {
          const v = h < settled ? x.awards[kk] : book ? +(book[kk]?.[h] ?? 0) : 0;
          const r = aR[kk][h];
          if (kk === "regdn") {
            const hd = (v / P) * Y.aDn;
            r.setAttribute("y", Y.aBase);
            r.setAttribute("height", v > 0.05 ? Math.max(1, hd) : 0);
          } else {
            const hu = (v / P) * Y.aUp;
            up -= hu;
            r.setAttribute("y", up);
            r.setAttribute("height", v > 0.05 ? Math.max(1, hu) : 0);
          }
          r.setAttribute("opacity", h < settled ? 1 : 0.6);
        }
      }
      for (const m of marks) m.e.style.opacity = m.h < settled || t >= 24 ? 1 : 0;
      const fz = t < 0 ? 0 : Math.max(settled, Math.min(24, w.freezeH));
      freeze.setAttribute("x", settled * cw);
      freeze.setAttribute("width", Math.max(0, (fz - settled) * cw));
      hatch.setAttribute("x", settled * cw);
      hatch.setAttribute("width", Math.max(0, (fz - settled) * cw));
      const showF = t >= 0 && t < 24 && w.freezeH > settled && w.freezeH <= 24;
      fline.setAttribute("x1", w.freezeH * cw);
      fline.setAttribute("x2", w.freezeH * cw);
      fline.setAttribute("opacity", showF ? 1 : 0);
      for (const { w: x, m } of wm) m.setAttribute("fill", x.t <= t + 1e-9 ? "#1c2329" : "rgba(28,35,41,0.28)");
      for (const { at, c } of icons) c.setAttribute("opacity", at <= t + 1e-9 ? 1 : 0.3);
    },
  };
}
