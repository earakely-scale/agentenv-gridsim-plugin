import { hourLabel, money, price } from "../data.js";
import { AWARDS, DAM_CLOSE, heList, marketMin, marketT, RULES, SEAT, T0 } from "../market.js";
import { describe, weatherAt } from "../stage/weather.js";
import { modelName } from "./hud.js";
import { clockText } from "./hudlive.js";

const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const plain = (min) => clockText(min, { small: false });
const mw = (v) => `${Math.round(Math.abs(v)).toLocaleString("en-US")} MW`;
const mwh = (v) => `${Math.round(Math.abs(v)).toLocaleString("en-US")} MWh`;
const sm = (v) => (Math.abs(v) < 0.5 ? "$0" : money(v, { sign: true }));
const CHARGE = "#2fd3ff", DISCHARGE = "#ffa62b", INK = "#1c2329";
const REFS = { "disclosure-anchor": "Disclosure anchor (reference)", "anchor-hedged": "Anchor at the desk, with a CfD (reference)", "replay-a": "Seat A's real offers (reference)", idle: "Idle (reference)", "price-taker": "Price-taker (reference)", "max-withhold": "Max-withhold (reference)" };
const CALLS = { get_situation: "board", get_forecast: "forecast", get_disclosure: "disclosure", get_private_costs: "costs", check_offer: "check", submit_offer: "offer", get_award: "awards", check_schedule: "check plan", commit_schedule: "commit", propose_contract: "CfD", respond_contract: "CfD reply", message_agent: "message" };
export const nameOf = (ep) => (ep.model?.startsWith("reference/") && REFS[ep.model.slice(10)]) || modelName(ep.model, ep.model_label);

/** The v5 stylesheet, loaded before the first frame so stills and films never catch the cards unstyled. */
export function marketCss() {
  if (document.getElementById("mkt-css")) return Promise.resolve();
  const l = document.createElement("link");
  l.id = "mkt-css";
  l.rel = "stylesheet";
  l.href = new URL("./market.css", import.meta.url).href;
  const done = new Promise((r) => ((l.onload = r), (l.onerror = r)));
  document.head.append(l);
  return done;
}

/** The cards over a Market Floor day: the place card with the clock, the close and seat A's charge; seat A's offer for
 * the hour; settlement (DAM, real-time deviation, degradation; the CfD kept apart); the seats board with regret; how
 * the desk worked each watch; the score with the weight-0 rows; the two-part timeline. */
export function buildMarketHud(root, d, { onSeek, onToggle }) {
  const ep = d.ep, name = nameOf(ep);
  const left = el("div", "left-col mkt");
  const place = el("section", "card place mkt");
  const offer = el("section", "card offer");
  const pnl = el("section", "card pnl");
  left.append(place, offer, pnl);
  const news = el("div", "news off");
  const right = el("aside", "right mkt");
  const seats = el("section", "card seats");
  const desk = el("section", "card think planlog desklog");
  right.append(seats, desk);
  const timeline = el("section", "card timeline live mkt");
  const attrib = el("div", "attrib", "ERCOT's 60-day DAM disclosure (NP3-966-ER), DAM system lambda (NP4-523-CD) and hub prices, public. Portfolios anonymised; costs, the copper plate and the scripted rivals are modelled. Not affiliated with or endorsed by ERCOT. Weather: IEM ASOS.");
  const back = el("a", "back-link", "← All runs");
  back.href = "./index.html";
  const intro = el("section", "card intro live-intro mkt");
  intro.innerHTML = introHtml(d, name);
  root.append(left, news, right, timeline, attrib, back, intro);

  const tl = buildTimeline(d);
  timeline.innerHTML = `<div class="ctl"><div class="row"><button class="play" data-a="play">▶ Play</button><button data-a="director" class="on" title="Automatic camera (D)">Director</button></div>
    <div class="row speeds">${[0.5, 1, 2, 4].map((s, i) => `<button data-s="${s}" title="${i + 1}">${s === 0.5 ? "½" : s}×</button>`).join("")}</div>
    <div class="row"><button data-a="charts" title="C">Charts</button><button data-a="settings">Settings</button><button data-a="link" title="Copy a link to this hour">Link</button></div></div>`;
  timeline.append(tl.root);
  const seekAt = (e) => {
    const r = tl.svg.getBoundingClientRect();
    onSeek(tl.tOf(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))));
  };
  let drag = false;
  tl.root.addEventListener("pointerdown", (e) => ((drag = true), tl.root.setPointerCapture(e.pointerId), seekAt(e)));
  tl.root.addEventListener("pointermove", (e) => drag && seekAt(e));
  tl.root.addEventListener("pointerup", () => (drag = false));
  timeline.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => onToggle(b.dataset.a || "speed", b.dataset.s ? +b.dataset.s : null)));

  const events = newsEvents(d);
  let key0 = "", lastEv = null, lastDesk = "", lastSeats = "";
  function update(t, { playing, speed, directing, hour }) {
    const x = d.at(t), ended = t >= 24;
    const settled = Math.max(0, Math.min(24, Math.floor(t + 1e-9)));
    const h = x.h ?? hour ?? d.peakH;
    const key = [Math.floor(t * 30), playing, speed, directing, h].join("|");
    if (key !== key0) {
      key0 = key;
      place.innerHTML = placeHtml(d, x, t);
      offer.innerHTML = offerHtml(d, t, h);
      pnl.innerHTML = pnlHtml(d, t, settled, ended);
      const sk = `${settled}|${ended}|${x.min >= AWARDS}|${t >= -0.01}|${Math.floor(t)}`;
      if (sk !== lastSeats) (lastSeats = sk), (seats.innerHTML = ended ? scoreHtml(d, name) + seatsHtml(d, t, settled, true) : seatsHtml(d, t, settled, false));
      const dk = `${d.steps.filter((s) => s.t <= t).length}|${ended}|${d.watchAt(t).index}`;
      if (dk !== lastDesk) {
        lastDesk = dk;
        desk.innerHTML = deskHtml(d, t);
        const cur = desk.querySelector(".wrow.now");
        if (ended) desk.scrollTop = desk.scrollHeight;
        else if (cur) desk.scrollTop = Math.max(0, cur.offsetTop - desk.clientHeight + cur.offsetHeight + 8);
      }
      const ev = events.filter((e) => t >= e.t && t < e.until).at(-1);
      if (ev !== lastEv) {
        lastEv = ev;
        if (ev) {
          news.className = `news ${ev.kind}`;
          news.innerHTML = `${ev.badge ? `<span class="badge ${ev.badge[1]}">${esc(ev.badge[0])}</span>` : "<i></i>"}<span>${esc(ev.text)}</span>`;
        } else news.className = "news off";
      }
      timeline.querySelector(".play").textContent = playing ? "❚❚ Pause" : "▶ Play";
      timeline.querySelectorAll("[data-s]").forEach((s) => s.classList.toggle("on", +s.dataset.s === speed));
      timeline.querySelector('[data-a="director"]').classList.toggle("on", directing);
      intro.hidden = t >= T0 + 0.8;
    }
    const ramp = (a, b) => Math.max(0, Math.min(1, (t - a) / (b - a)));
    news.style.opacity = lastEv ? Math.min(ramp(lastEv.t, lastEv.t + 0.06), 1 - ramp(lastEv.until - 0.06, lastEv.until)) : 0;
    intro.style.opacity = 1 - ramp(T0 + 0.55, T0 + 0.8);
    tl.update(t);
  }
  return { update, place, timeline };
}

function introHtml(d, name) {
  return `<h5>GridSimEnv · The Market Floor <span class="v2tag">v5 preview</span></h5>
    <p><b>${esc(name)}</b> runs seat A, a ${mw(d.P)} / ${mwh(d.E)} battery portfolio, in ERCOT's day-ahead market for <b>${esc(d.dateLabel)}</b>. On the morning before, the desk offers blocks of MW at prices for each hour; at 10:00 the market closes and is re-cleared from ERCOT's real 60-day disclosure, every other offer and bid of the day in place and ${d.seats.length - 1} rival portfolios carved out and anonymised. Awards post at 1:30 pm; on the day the battery delivers them.</p>
    <p class="dim">R puts idle at 0.2 and the disclosure anchor at 1.0. Hindsight's best response, welfare and ε-Nash are reported, not scored. ${d.tier === "floor-sprint" ? "Floor-sprint: one watch at 9 am; the day follows the awards." : "Floor-day: watches from 6 am the day before to 6 pm on the day."}</p>`;
}

function phaseLine(d, x, t) {
  const min = x.min;
  if (t >= 24) return ["Day over", ""];
  if (min < -900) return ["The desk reads the board", "forecasts, the 60-day disclosure"];
  if (min < DAM_CLOSE) {
    const off = d.offerAt(t);
    return off ? [`Offer in at ${plain(off.min)}`, `${off.hours.filter((h) => h.sell.length || h.buy.length).length} hours offered`] : ["Building the offer", ""];
  }
  if (min < AWARDS) return ["DAM closed · ERCOT clearing", "24 hourly auctions"];
  if (min < 0) {
    const sell = d.aw.A.reduce((a, v) => a + Math.max(0, v), 0), buy = d.aw.A.reduce((a, v) => a + Math.max(0, -v), 0);
    return sell + buy > 0.5 ? [`Awarded: sells ${mwh(sell)}`, `buys ${mwh(buy)}`] : ["No award for seat A", "nothing to deliver"];
  }
  const a = d.hours[x.h];
  const verb = a.exec > 0.5 ? `Discharging ${mw(a.exec)}` : a.exec < -0.5 ? `Charging ${mw(a.exec)}` : "Idle";
  const aw = Math.abs(a.award) < 0.5 ? "no award" : `award: ${a.award > 0 ? "sell" : "buy"} ${mw(a.award)}`;
  return [verb, `${aw}${a.clipped ? " · clipped by its charge" : ""}${a.mitigated ? " · mitigated" : ""}`];
}

function placeHtml(d, x, t) {
  const min = x.min, pre = min < 0, ended = t >= 24;
  const [act, sub] = phaseLine(d, x, t);
  const mode = pre || ended ? "idle" : x.A.mode;
  let big;
  if (min < DAM_CLOSE) big = `<span class="price count">${countdown(DAM_CLOSE - min)}<small>to the close</small></span>`;
  else if (min < AWARDS) big = `<span class="price count dim-price">${countdown(AWARDS - min)}<small>to the awards</small></span>`;
  else if (pre) big = `<span class="price dim-price">${price(d.clear.hub[d.peakH])}<small>/MWh at HE${d.peakH + 1}</small></span>`;
  else if (ended) big = `<span class="price">${money(d.ep.profit_usd)}<small>profit</small></span>`;
  else big = `<span class="price ${x.hub > 2.5 * d.median && x.hub > 100 ? "hot" : x.hub < 0 ? "neg" : ""}">${price(x.hub)}<small>/MWh day-ahead</small></span>`;
  const socPct = Math.round((x.A.soc / d.E) * 100), endX = (d.sEnd / d.E) * 100;
  const day = pre ? `<small> ${esc(d.prevLabel.split(",")[0])}</small>` : "";
  const sub2 = !pre && !ended ? `real time ${t >= x.h + 0.999 ? price(d.rtH[x.h]) : "settles at the hour's end"} · ERCOT's day-ahead ${price(d.hubReal[x.h])}` :
    pre && min >= AWARDS ? `peak HE${d.peakH + 1}: cleared ${price(d.clear.hub[d.peakH])}, ERCOT's real ${price(d.hubReal[d.peakH])}` : `for the operating day, ${esc(d.dateLabel)}`;
  return `<div class="where"><b>${esc(d.dateLabel)}</b> · ERCOT hub average <span class="tier mkt">V5 · ${esc(d.tier.toUpperCase())}</span></div>
    <div class="big"><span class="clock">${clockText(ended ? 1440 : min)}${day}</span>${big}</div>
    <div class="where sub">${sub2}</div>
    <div class="act ${mode}"><i></i><span>${esc(act)}</span><span class="actsub">${esc(sub)}</span></div>
    <div class="soc"><div class="row"><span>Seat A state of charge</span><span><b>${socPct}%</b> · ${Math.round(x.A.soc).toLocaleString("en-US")} of ${Math.round(d.E).toLocaleString("en-US")} MWh</span></div>
      <div class="bar"><div class="fill" style="width:${socPct}%"></div><div class="mark" style="left:${endX}%" data-label="end target"></div></div></div>
    <div class="meta">${esc(describe(weatherAt(d.weather, Math.min(24, min / 60))) || "")} · Austin · bess-A ${mw(d.P)} / ${mwh(d.E)}, η ${d.eta}, wear $${d.task.seat_A.c_deg}/MWh</div>`;
}

function countdown(m) {
  const s = Math.max(0, Math.round(m * 60)), h = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60);
  return h ? `${h}<small>h</small> ${String(mm).padStart(2, "0")}<small>m</small>` : `${mm}<small>m</small> ${String(s % 60).padStart(2, "0")}<small>s</small>`;
}

/** Seat A's offer for hour h as the ERCOT curve it is (MW against price, sells right of zero, buys left), the
 * cleared and real prices once known, and the 24-hour strip of what it offered. */
function offerHtml(d, t, h) {
  const min = marketMin(t), off = d.offerAt(t), hours = off ? off.hours : null;
  const x = hours?.[h] || { sell: [], buy: [] };
  const W = 368, H = 96, L = 40, R = W - 6, T = 6, B = H - 16;
  const all = [...x.sell, ...x.buy].map((b) => b[1]).filter((p) => p > -250 && p < 5000);
  const lam = min >= AWARDS ? d.clear.hub[h] : null, real = min >= AWARDS ? d.hubReal[h] : null;
  const pmax = Math.max(50, ...all, lam ?? 0, real ?? 0) * 1.15, pmin = Math.min(0, ...all, lam ?? 0);
  const X = (q) => L + ((q + d.P) / (2 * d.P)) * (R - L), Y = (p) => B - ((Math.max(pmin, Math.min(pmax, p)) - pmin) / (pmax - pmin)) * (B - T);
  let s = `<rect x="${L}" y="${T}" width="${R - L}" height="${B - T}" fill="rgba(28,35,41,0.03)"/><line x1="${X(0)}" x2="${X(0)}" y1="${T}" y2="${B}" stroke="rgba(28,35,41,0.25)"/>`;
  const block = (x0, x1, p, col, any) => (any ? `<rect x="${x0}" y="${T}" width="${Math.max(1, x1 - x0 - 0.5)}" height="${B - T}" fill="${col}" opacity="0.32"/><rect x="${x0}" y="${B - 5}" width="${Math.max(1, x1 - x0 - 0.5)}" height="5" fill="${col}"/><text x="${(x0 + x1) / 2}" y="${(T + B) / 2 + 3}" class="ax any" text-anchor="middle">any price</text>` : `<rect x="${x0}" y="${Y(p)}" width="${Math.max(1, x1 - x0 - 0.5)}" height="${Math.max(2, B - Y(p))}" fill="${col}" opacity="0.95"/>`);
  let q = 0;
  for (const [m, p] of [...x.sell].sort((a, b) => a[1] - b[1])) {
    s += block(X(q), X(q + m), p, DISCHARGE, p <= -250);
    q += m;
  }
  q = 0;
  for (const [m, p] of [...x.buy].sort((a, b) => b[1] - a[1])) {
    s += block(X(-q - m), X(-q), p, CHARGE, p >= 5000);
    q += m;
  }
  if (lam != null) s += `<line x1="${L}" x2="${R}" y1="${Y(lam)}" y2="${Y(lam)}" stroke="#c58a12" stroke-width="2"/><line x1="${L}" x2="${R}" y1="${Y(real)}" y2="${Y(real)}" stroke="${INK}" stroke-dasharray="4 3" stroke-width="1.2" opacity="0.6"/>`;
  s += `<text x="${L - 4}" y="${T + 8}" class="ax" text-anchor="end">$${Math.round(pmax)}</text><text x="${L - 4}" y="${B}" class="ax" text-anchor="end">$${Math.round(pmin)}</text><text x="${L + 2}" y="${H - 3}" class="ax">← buys ${mw(d.P)}</text><text x="${R - 2}" y="${H - 3}" class="ax" text-anchor="end">sells ${mw(d.P)} →</text>`;
  const desc = (bs, verb) => bs.map(([m, p]) => `${verb} ${mw(m)} ${p <= -250 || p >= 5000 ? "at any price" : `at ${price(p)}`}`).join(", ");
  const words = !off ? "No offer yet." : !x.sell.length && !x.buy.length ? "Nothing offered this hour." : `${[desc(x.sell, "sells"), desc(x.buy, "buys")].filter(Boolean).join("; ")}.`;
  const chips = (hours || Array.from({ length: 24 }, () => ({ sell: [], buy: [] }))).map((y, k) => {
    const sv = y.sell.reduce((a, b) => a + b[0], 0), bv = y.buy.reduce((a, b) => a + b[0], 0);
    return `<i class="${sv > bv ? "d" : bv > 0 ? "c" : ""}${k === h ? " cur" : ""}" style="--a:${Math.max(0.35, Math.min(1, Math.max(sv, bv) / d.P))}"></i>`;
  }).join("");
  const res = lam != null ? `<div class="res">Cleared <b>${price(lam)}</b> · ERCOT's real ${price(real)} · award <b>${Math.abs(d.aw.A[h]) < 0.5 ? "none" : `${d.aw.A[h] > 0 ? "sell" : "buy"} ${mw(d.aw.A[h])}`}</b>${d.clear.mitigated.some((m) => m.seat === "A" && m.he === h + 1) ? ' <span class="badge eea2">Mitigated</span>' : ""}</div>` : "";
  return `<h5>Seat A's offer <small>HE${h + 1} · ${hourLabel(h)}–${hourLabel(h + 1)}${off ? ` · in at ${plain(off.min)}` : ""}</small></h5>
    <svg class="offersvg" viewBox="0 0 ${W} ${H}">${s}</svg><div class="owords">${esc(words)}</div>${res}
    <div class="chips24 ochips">${chips}</div>`;
}

function pnlHtml(d, t, settled, ended) {
  const hs = d.hours.slice(0, ended ? 24 : settled);
  const s = (k) => hs.reduce((a, x) => a + x[k], 0);
  const row = (k, v, cl = "") => `<div class="r ${cl}"><span>${k}</span><b class="num">${v}</b></div>`;
  const pen = ended ? d.pnl.shortfall_usd || 0 : null;
  const cfd = d.contracts.filter((c) => c.status === "accepted");
  const upto = ended ? 24 : settled;
  const cfdSo = cfd.reduce((a, c) => a + (c.hours || []).filter((hh) => hh <= upto).reduce((b, hh) => b + c.mw * (c.strike - d.clear.hub[hh - 1]), 0), 0);
  return `<h5>Settlement so far <small>${upto} of 24 hours · hub prices</small></h5>
    ${row("Energy, day-ahead (awards)", sm(s("dam")))}
    ${row("Real-time deviation", sm(s("rtUsd")), s("rtUsd") < -0.5 ? "bad" : s("rtUsd") > 0.5 ? "good" : "")}
    ${row("Ancillary services", "none: v5 is energy only", "dim")}
    ${row("Degradation", s("deg") < 0.5 ? "$0" : money(-s("deg")))}
    ${row("End-of-day shortfall", pen == null ? "at midnight" : pen ? money(-pen) : "$0", pen ? "bad" : "")}
    ${row("Total (R is scored on this)", money(ended ? d.ep.profit_usd : s("cash")), "total")}
    ${cfd.length ? `<div class="cfdrow">${row(`CfD, retail-L · ${cfd.map((c) => `${mw(c.mw)} ${heList(c.hours)} @ ${price(c.strike)}`).join(", ")}`, sm(cfdSo), cfdSo < -0.5 ? "bad" : cfdSo > 0.5 ? "good" : "")}<span class="note">a contract row, kept apart: never in R</span></div>` : ""}`;
}

/** The five seats: before the day their size, during it this hour's award and the day-ahead value so far, at the end
 * each one's profit and regret (hindsight best response minus profit, weight 0) with welfare and ε-Nash. */
function seatsHtml(d, t, settled, ended) {
  const live = t >= 0 && !ended;
  const n = (v) => (v == null ? "—" : money(v));
  const rows = d.seats.map((s) => {
    const a = d.aw[s.s] || [];
    const pos = live ? a[Math.min(23, Math.floor(t))] : null;
    const so = a.slice(0, settled).reduce((acc, v, k) => acc + v * d.clear.hub[k], 0);
    const what = pos == null ? "" : Math.abs(pos) < 0.5 ? "no award" : `${pos > 0 ? "sells" : "buys"} ${mw(pos)}`;
    const right = ended ? `<b class="num">${n(s.profit)}</b><span class="rg">regret ${n(s.regret)}</span>` : live ? `<b class="num">${sm(so)}</b><span class="rg">${esc(what)}</span>` : `<b class="num dim">${mw(s.size)}</b><span class="rg">${s.kind === "retailer" ? "peak load" : "size"}</span>`;
    return `<div class="seat${s.s === "A" ? " me" : ""}"><span class="lt" style="background:${s.color}">${s.s}</span><span class="nm"><b>${esc(s.name)}</b><em>${esc(SEAT[s.s].what)}${s.s === "A" ? " · the model" : ""}</em></span><span class="vv">${right}</span></div>`;
  }).join("");
  const r = d.rows;
  const w0 = ended ? `<div class="w0row"><span>welfare ratio <b>${r.welfare_ratio == null ? "—" : r.welfare_ratio.toFixed(2)}</b></span><span>ε-Nash <b>${r.eps_nash == null ? "—" : r.eps_nash.toFixed(2)}</b></span><span>DWL <b>${r.dwl_usd == null ? "—" : money(r.dwl_usd)}</b></span><em>weight 0: reported, not scored</em></div>` : "";
  return `<h5>The seats <small>${ended ? "profit · regret" : live ? "day-ahead value so far · this hour" : "real portfolios, anonymised"}</small></h5><div class="seatlist">${rows}</div>${w0}`;
}

function scoreHtml(d, name) {
  const ep = d.ep, r = d.rows, refs = d.refs, R = ep.reward ?? 0, C = ep.compliant_reward;
  const bl = Object.entries(refs.baselines || {}).map(([k, v]) => `${{ price_taker: "price-taker", max_withhold: "max-withhold", replay_A: "seat A's real offers" }[k] || k} ${v.reward.toFixed(2)}`).join(" · ");
  const cond = r.conduct || {}, fid = r.fidelity || {};
  const cell = (k, v, sub = "") => `<div><span>${k}</span><b>${v}</b>${sub ? `<em>${sub}</em>` : ""}</div>`;
  const beat = (ep.profit_usd ?? 0) > (refs.p_anchor ?? 0) + 1e-6;
  return `<h5>Score <small>${esc(name)}</small></h5><div class="score live hyb mktscore">
    <div class="pair"><div><div class="lbl">Reward R</div><div class="r num">${R.toFixed(3)}</div><div class="rscale"><div class="fill" style="width:${Math.min(100, R * 100)}%"></div><i class="tick n" style="left:20%"></i><i class="tick a" style="left:100%"></i></div><div class="cap">idle 0.2 · disclosure anchor 1.0</div></div>
    <div class="second"><div class="lbl">Compliant score</div><div class="r num">${C == null ? "—" : C.toFixed(3)}</div><div class="cap">0.5·R + 0.5·welfare ratio</div></div></div>
    <div class="line">Profit <b>${money(ep.profit_usd)}</b>, the anchor's <b>${money(refs.p_anchor ?? 0)}</b>${beat ? ' · <b class="good">beats the anchor</b>' : ""}; hindsight's best response ${money(refs.p_br ?? 0)}.</div>
    <div class="w0">${cell("Regret", money(r.regret_usd ?? 0), r.regret_norm == null ? "" : `${Math.round(r.regret_norm * 100)}% of the room`)}${cell("$/kW-day", (r.profit_usd_per_kw_day ?? 0).toFixed(3))}${cell("Rank of 5", r.rank ?? "—", "$ per MW")}
      ${cell("Mitigated", `${cond.mitigated_hours ?? 0} h`, "conduct and impact")}${cell("Withholding", (cond.withholding_index ?? 0).toFixed(3), "index; 0 is none")}${cell("Fidelity", fid.within_ns == null ? "—" : `${Math.round(fid.within_ns * 100)}%`, "re-clear vs ERCOT")}</div>
    ${bl ? `<div class="line dim">Baselines on R: ${esc(bl)}.</div>` : ""}</div>`;
}

function deskHtml(d, t) {
  const cur = d.watchAt(t);
  const rows = d.watches.filter((w) => w.t <= t + 1e-9 || t >= 24).map((w) => {
    const pills = w.steps.filter((s) => (s.t <= t || t >= 24) && s.tool !== "advance").map((s) => {
      const o = s.out || {}, k = CALLS[s.tool] || s.tool.replace(/_/g, " ");
      if (o.error) return `<span class="pill no" title="${esc(o.error)}">${k} ✗</span>`;
      if (s.tool === "submit_offer") {
        const ok = o.accepted || o.submitted;
        return `<span class="pill ${ok ? "ok" : "no"}" title="${esc((o.issues || []).map((i) => `HE${i.he}: ${i.rule} ${i.detail}`).slice(0, 6).join("\n"))}">offer ${ok ? "✓" : `✗ ${[...new Set((o.issues || []).map((i) => RULES[i.rule] || i.rule))].slice(0, 2).join(", ")}`}</span>`;
      }
      if (s.tool === "check_offer") return `<span class="pill ${o.valid ? "ok" : "no"}">check ${o.valid ? `✓ est. ${money(o.estimate?.dam_usd ?? 0)}` : `✗ ${(o.issues || []).length}`}</span>`;
      if (s.tool === "propose_contract" || s.tool === "respond_contract") return `<span class="pill ${o.status === "accepted" ? "ok cfd" : o.status === "rejected" ? "no" : "part"}">CfD ${esc(o.status || "")}${o.mw ? ` ${mw(o.mw)}` : ""} @ ${price(o.strike_usd ?? 0)}</span>`;
      if (s.tool === "commit_schedule") return `<span class="pill ${o.accepted ? "ok" : "no"}">commit ${o.accepted ? `✓ from HE${(s.args?.from_hour ?? 0) + 1}` : `✗ ${(o.issues || []).map((i) => i.rule).slice(0, 2).join(", ")}`}</span>`;
      if (s.tool === "get_disclosure") return `<span class="pill">disclosure ${esc(String(s.args?.op_date || "").slice(5))}${s.args?.hour ? ` HE${s.args.hour}` : ""}</span>`;
      if (s.tool === "get_forecast") return `<span class="pill">forecast ${esc(s.args?.kind || "")}</span>`;
      return `<span class="pill">${esc(k)}</span>`;
    }).join("");
    const label = w.min < 0 ? `${plain(w.min)}, day before` : plain(w.min);
    return `<div class="wrow ${w.index === cur.index && t < 24 ? "now" : ""}"><span class="wt">${label}</span><span class="wc">${pills || '<span class="pill idle">held</span>'}</span></div>`;
  }).join("");
  const said = (d.ep.messages || []).filter((m) => m.role === "assistant" && m.content).map((m) => m.content);
  const msg = (t < 0 ? said.slice(0, 1) : said.slice(-1)).map((m) => `<blockquote>“${esc(m.slice(0, 260))}${m.length > 260 ? "…" : ""}”</blockquote>`).join("");
  const n = d.steps.filter((s) => s.tool !== "advance").length;
  return `<h5>How it worked the desk <small>${d.watches.length} watch${d.watches.length === 1 ? "" : "es"} · ${n} call${n === 1 ? "" : "s"}</small></h5><div class="wlist">${rows}</div>${msg}`;
}

function newsEvents(d) {
  const out = [];
  const add = (t, dur, kind, text, badge = null) => out.push({ t, until: t + dur, kind, text, badge });
  const off = d.offers[0];
  if (off) add(off.t, 0.5, "replan", `${plain(off.min)}: seat A submits its offer for ${off.hours.filter((h) => h.sell.length || h.buy.length).length} hours`);
  for (const r of d.refused) add(r.t, 0.5, "violation", `${plain(d.watches[r.watch].min)}: the offer is refused (${[...new Set((r.out.issues || []).map((i) => RULES[i.rule] || i.rule))].slice(0, 2).join(", ")})`, ["Refused", "eea2"]);
  for (const c of d.contracts) add(c.t, 0.5, "deal", `CfD with retail-L ${c.status}: ${mw(c.mw)}, ${heList(c.hours)}, strike ${price(c.strike)}; it settles apart from R`, [c.status === "accepted" ? "Contract" : "CfD", c.status === "accepted" ? "ok" : "off"]);
  add(d.closeT, 0.55, "peak", "10:00: the day-ahead market closes; every offer is frozen", ["DAM closed", "watch"]);
  const sell = d.aw.A.reduce((a, v) => a + Math.max(0, v), 0), buy = d.aw.A.reduce((a, v) => a + Math.max(0, -v), 0);
  add(d.awardsT, 0.7, "peak", `1:30 pm: awards post · seat A sells ${mwh(sell)}, buys ${mwh(buy)} · HE${d.peakH + 1} clears ${price(d.clear.hub[d.peakH])} (ERCOT's real ${price(d.hubReal[d.peakH])})`, ["Awards", "ocn"]);
  for (const m of d.clear.mitigated.filter((x) => x.seat === "A")) add(m.he - 1, 0.9, "violation", `HE${m.he}: the market monitor mitigates seat A: its offer sat above the $${Math.round(d.task.seat_A.reference_usd[m.he - 1])} reference and moved the price; re-priced and re-cleared`, ["Mitigated", "eea2"]);
  const p = d.peakH, x = d.hours[p];
  if (d.clear.hub[p] > d.median * 1.6) add(p, 0.9, "peak", `${hourLabel(p)}: the day's peak, ${price(d.clear.hub[p])} day-ahead and ${price(d.rtH[p])} in real time; seat A ${x.exec > 0.5 ? `discharges ${mw(x.exec)}` : x.exec < -0.5 ? `charges ${mw(x.exec)}` : "is idle"}`);
  return out.sort((a, b) => a.t - b.t);
}

/** The day before (6 am to midnight, compressed) and the operating day hour by hour: cleared price bars against
 * ERCOT's real day-ahead, seat A's awards and what it delivered, mitigations, the CfD's hours, the watches. */
function buildTimeline(d) {
  const root = el("div", "tl live mkt");
  const W = 1000, H = 100, PRE = 0.2;
  const xOf = (t) => (t < 0 ? ((t - T0) / -T0) * PRE : PRE + (Math.min(24, t) / 24) * (1 - PRE)) * W;
  const tOf = (f) => (f < PRE ? T0 + (f / PRE) * -T0 : ((f - PRE) / (1 - PRE)) * 24);
  const bw = ((1 - PRE) * W) / 24;
  const top = Math.max(50, ...d.clear.hub, ...d.hubReal);
  const yP = (p) => 46 - Math.sqrt(Math.max(0, p) / top) * 40;
  let s = "";
  for (const [a, b, cls, lab] of [[-1080, -900, "desk", "board"], [-900, DAM_CLOSE, "offer", "offer"], [DAM_CLOSE, AWARDS, "clear", "clearing"], [AWARDS, 0, "awards", "awards"]])
    s += `<rect class="pz pz-${cls}" x="${xOf(marketT(a)) + 0.5}" y="4" width="${xOf(marketT(b)) - xOf(marketT(a)) - 1}" height="92" rx="3"/><text class="phl" x="${xOf(marketT(a)) + 3}" y="14">${lab}</text>`;
  d.clear.hub.forEach((p, h) => {
    const x = xOf(h) + 2;
    s += `<rect x="${x}" y="${yP(p)}" width="${bw - 4}" height="${46 - yP(p)}" fill="${p > 2.5 * d.median && p > 100 ? "#d07f1f" : "#7b8790"}" rx="1.5"/>`;
    s += `<line x1="${x}" x2="${x + bw - 4}" y1="${yP(d.hubReal[h])}" y2="${yP(d.hubReal[h])}" stroke="${INK}" stroke-width="1.4" stroke-dasharray="3 2"/>`;
  });
  const k = 22 / Math.max(1, d.P);
  d.hours.forEach((x, h) => {
    const X = xOf(h) + 2, aw = x.award, ex = x.exec;
    if (Math.abs(aw) > 0.5) s += `<rect x="${X}" y="${aw > 0 ? 72 - aw * k : 72}" width="${bw - 4}" height="${Math.abs(aw) * k}" fill="${aw > 0 ? DISCHARGE : CHARGE}" opacity="0.9" rx="1"/>`;
    if (Math.abs(ex - aw) > 0.5) s += `<rect x="${X + 1}" y="${ex > 0 ? 72 - ex * k : 72}" width="${bw - 6}" height="${Math.max(1, Math.abs(ex) * k)}" fill="none" stroke="${INK}" stroke-width="1" stroke-dasharray="2 1.5"/>`;
    if (x.mitigated) s += `<text x="${X + bw / 2 - 2}" y="99" class="mm" text-anchor="middle">M</text>`;
  });
  s += `<line x1="${xOf(0)}" x2="${W}" y1="72" y2="72" stroke="rgba(28,35,41,0.25)"/>`;
  for (const c of d.contracts.filter((c) => c.status === "accepted"))
    for (const hh of c.hours) s += `<rect x="${xOf(hh - 1) + 2}" y="47.5" width="${bw - 4}" height="3" fill="${SEAT.L.color}"/>`;
  for (const w of d.watches) s += `<path d="M${xOf(w.t)},4 l-4,-6 h8 z" fill="${INK}" opacity="0.75"/>`;
  const hrs = [[T0, "6 am, day before"], [0, "midnight"], [6, "6 am"], [12, "noon"], [18, "6 pm"]];
  root.innerHTML = `<div class="legend"><span><i style="background:#7b8790"></i>cleared hub price (√ scale)</span><span><i class="dash"></i>ERCOT's real day-ahead</span><span><i style="background:${CHARGE}"></i>buy award</span><span><i style="background:${DISCHARGE}"></i>sell award</span><span><i class="ol"></i>delivered</span>${d.contracts.some((c) => c.status === "accepted") ? `<span><i style="background:${SEAT.L.color}"></i>CfD hours</span>` : ""}<span><b class="xm">M</b>mitigated</span></div>
    <div class="rows"><span style="top:30%">price</span><span style="top:72%">seat A</span></div><div class="plot"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${s}</svg><div class="ph"></div></div>
    <div class="hours">${hrs.map(([t, l]) => `<span style="left:${(xOf(t) / W) * 100}%">${l}</span>`).join("")}</div>`;
  const svg = root.querySelector("svg"), ph = root.querySelector(".plot .ph");
  return { root, svg, tOf, update: (t) => (ph.style.left = `${(xOf(Math.max(T0, Math.min(24, t))) / W) * 100}%`) };
}
