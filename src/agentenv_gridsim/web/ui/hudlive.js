import { hourLabel, money, price } from "../data.js";
import { clockMin } from "../live.js";
import { describe, weatherAt } from "../stage/weather.js";
import { ATTRIBUTION, modelName } from "./hud.js";

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
/** "7:30 pm" for minutes from D 00:00; the day before gets its weekday. */
export function clockText(min, { small = true, day = null } = {}) {
  const m = Math.round(min), mm = ((m % 1440) + 1440) % 1440;
  const h = Math.floor(mm / 60), r = mm % 60, h12 = h % 12 || 12, ap = h < 12 ? "am" : "pm";
  return `${h12}:${String(r).padStart(2, "0")}${small ? `<small>${ap}</small>` : ` ${ap}`}${m < 0 && day ? `<small> ${day}</small>` : ""}`;
}
const plain = (min) => clockText(min, { small: false });
const fmtMw = (mw) => (mw < 10 ? mw.toFixed(1) : Math.round(mw));
const CHARGE = "#2fd3ff", DISCHARGE = "#ffa62b";
const CALL = { commit_da: "DA position", check_schedule: "check", commit_schedule: "commit" };
const REASON = { frozen: "inside the freeze", rate: "over the power limit", soc_below_0: "sells more than it holds", soc_above_max: "charges past full", cycle_cap: "past the cycle cap", end_target: "ends below the end target", parse: "not a schedule" };

/** The cards over a live day: place card, P&L, bulletins, the race against the references, how it planned at each
 * watch, the score, and the 96-interval timeline. */
export function buildLiveHud(root, d, { onSeek, onToggle }) {
  const b = d.b;
  const left = el("div", "left-col");
  const place = el("section", "card place");
  const pnl = el("section", "card pnl");
  const bulls = el("div", "bulletins");
  left.append(place, pnl, bulls);
  const news = el("div", "news off");
  const right = el("aside", "right");
  const race = el("section", "card race");
  const think = el("section", "card think planlog");
  right.append(race, think);
  const timeline = el("section", "card timeline live");
  const attrib = el("div", "attrib", ATTRIBUTION.replace("ERCOT DAM settlement point prices", "ERCOT DAM and real-time settlement point prices") + " Bulletins: paraphrased ERCOT and NWS notices.");
  const back = el("a", "back-link", "← All runs");
  back.href = "./index.html";
  const intro = el("section", "card intro live-intro");
  root.append(left, news, right, timeline, attrib, back, intro);

  const name = modelName(d.ep.model, d.ep.model_label);
  const lanes = [{ k: "agent", label: name, cum: d.agentCum, final: d.ep.profit_usd }, ...d.lanes];
  const lo = Math.min(0, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const hi = Math.max(1, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const zx = (v) => ((v - lo) / (hi - lo)) * 100;
  race.innerHTML = `<h5>Race against the references <span class="v2tag">v2 preview</span></h5>` + lanes.map((l) => `<div class="lane ${l.k === "agent" ? "agent" : l.k === "anchor" ? "opt" : "base"} ${l.k}" data-k="${l.k}"><div class="who">${l.k === "agent" ? `<b>${esc(l.label)}</b>` : esc(l.label)}</div><div class="track"><i class="z" style="left:${zx(0)}%"></i><span></span></div><div class="v num"></div></div>`).join("") +
    `<svg class="spark" viewBox="0 0 240 70" preserveAspectRatio="none"></svg><div class="score live" hidden></div>`;
  const tierNote = d.ep.tier === "foresight" ? "" : ` · ${d.ep.tier}`;
  intro.innerHTML = introHtml(d, name);

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
  let lastKey = "", lastPlan = -1, lastEv = null;
  function update(t, { playing, speed, directing }) {
    const min = clockMin(t);
    const x = d.at(Math.min(23.999, Math.max(0, t)));
    const w = d.watchAt(t);
    const settled = Math.max(0, Math.min(96, Math.floor(t * 4 + 1e-9)));
    const ended = t >= 24;
    const key = [Math.floor(t * 12), settled, w.index, playing, speed, directing].join("|");
    if (key !== lastKey) {
      lastKey = key;
      const wx = weatherAt(d.weather, Math.max(0, Math.min(24, t)));
      const lastRt = settled > 0 ? d.rt[settled - 1] : null;
      const hot = lastRt != null && lastRt > Math.max(150, 2 * d.prices[(settled - 1) >> 2]);
      const plan = t < 0 ? null : d.snaps[w.index][x.i];
      const mode = t < 0 ? "idle" : x.mode;
      const mw = Math.abs(x.mw);
      const act = t < 0 ? (t < -1.2 ? "The day before: planning" : "Day-ahead position committed") : ended ? "Day over" :
        mode === "charge" ? `Charging ${fmtMw(mw)} MW` : mode === "discharge" ? `Discharging ${fmtMw(mw)} MW` : "Idle";
      const follows = t >= 0 && !ended && plan != null && plan !== x.action ? " (derated)" : "";
      const socPct = (x.soc / b.soc_levels) * 100;
      const soc = t < 0 ? b.s0 : x.soc;
      place.innerHTML = `<div class="where">${d.dateLabel} · <b>${esc(d.task.settlement_point)}</b> · ${esc(d.place.name)}<span class="tier live">LIVE${tierNote.toUpperCase()}</span></div>
        <div class="big"><span class="clock num">${ended ? "End of day" : clockText(min)}</span>${t < 0 ? "" : lastRt == null ? `<span class="price num dim-price">${price(d.prices[x.h])}<small>/MWh DA</small></span>` : `<span class="price num ${lastRt < 0 ? "neg" : hot ? "hot" : ""}">${price(lastRt)}<small>/MWh RT</small></span>`}</div>
        <div class="where" style="margin-top:-2px">${t < 0 ? "the day before · the day-ahead position is due at 2 pm" : lastRt == null ? "day-ahead price; the first real-time price settles at 12:15 am" : `real time, ${plain((settled - 1) * 15)}–${plain(settled * 15)} settled · day-ahead ${price(d.prices[(settled - 1) >> 2])}`}</div>
        <div class="act ${ended ? "" : mode}"><i></i><span>${act}${follows}</span></div>
        <div class="soc"><div class="row"><span>State of charge</span><span><b class="num">${Math.round(t < 0 ? (b.s0 / b.soc_levels) * 100 : socPct)}%</b> · ${Math.round(soc * b.unit_mwh)} of ${b.energy_mwh} MWh</span></div>
          <div class="bar"><div class="fill" style="width:${t < 0 ? (b.s0 / b.soc_levels) * 100 : socPct}%"></div>${b.s_end_min > 0 ? `<div class="mark" style="left:${(b.s_end_min / b.soc_levels) * 100}%" data-label="end ≥ ${Math.round((b.s_end_min / b.soc_levels) * 100)}%"></div>` : ""}</div></div>
        <div class="meta">${b.p_dis_mw} MW / ${b.energy_mwh} MWh battery · ${Math.round(b.energy_mwh / Math.max(1, b.p_dis_mw))}-hour · ${describe(wx) || "weather n/a"}</div>`;
      pnl.innerHTML = pnlHtml(d, settled, ended);
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
        const v = ended ? l.final : t <= 0 ? 0 : (x.i > 0 ? l.cum[x.i - 1] : 0) + (l.cum[x.i] - (x.i > 0 ? l.cum[x.i - 1] : 0)) * x.u;
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
      if (ended) score.innerHTML = scoreHtml(d);
      if (w.index !== lastPlan || ended) {
        lastPlan = w.index;
        think.innerHTML = planHtml(d, t);
        const cur = think.querySelector(".wrow.now");
        if (cur) think.scrollTop = Math.max(0, cur.offsetTop - think.clientHeight + cur.offsetHeight + 8);
      }
      timeline.querySelector(".play").textContent = playing ? "❚❚ Pause" : "▶ Play";
      timeline.querySelectorAll("[data-s]").forEach((s) => s.classList.toggle("on", +s.dataset.s === speed));
      timeline.querySelector('[data-a="director"]').classList.toggle("on", directing);
      intro.hidden = t >= -0.15;
    }
    const ramp = (a, b) => Math.max(0, Math.min(1, (t - a) / (b - a)));
    news.style.opacity = lastEv ? Math.min(ramp(lastEv.t, lastEv.t + 0.12), 1 - ramp(lastEv.until - 0.12, lastEv.until)) : 0;
    intro.style.opacity = 1 - ramp(-0.45, -0.15);
    intro.style.setProperty("--pos", 0.25 + 0.75 * ramp(-1.45, -1.2));
    tl.update(t, settled, w);
  }
  return { update, place, timeline };
}

function introHtml(d, name) {
  const b = d.b, w0 = d.watches[0];
  const board = d.notices.filter((n) => n.watch === 0);
  const lo = Math.min(0, ...d.prices), hi = Math.max(...d.prices);
  const y = (v) => 36 - ((v - lo) / (hi - lo || 1)) * 32;
  const pts = d.prices.map((v, h) => `${(h / 23) * 560},${y(v)}`).join(" ");
  const k = Math.max(b.k_dis, b.k_ch);
  const pos = d.daAt[0] || d.daPosition;
  const chips = pos.map((a, h) => `<rect x="${(h / 24) * 560 + 1}" y="${a > 0 ? 9 - (a / k) * 8 : 9}" width="${560 / 24 - 2}" height="${Math.max(1, (Math.abs(a) / k) * 8)}" rx="1.5" fill="${a > 0 ? DISCHARGE : a < 0 ? CHARGE : "#cfd5d8"}"/>`).join("");
  return `<h5>The day before · ${plain(w0.min)} · ${esc(d.task.settlement_point)}</h5>
    <p><b>${esc(name)}</b> runs a ${b.p_dis_mw} MW / ${b.energy_mwh} MWh battery tomorrow, ${d.dateLabel}. At 2 pm today it commits a <b>day-ahead position</b> for each hour from the published day-ahead prices. Tomorrow it can re-plan its <b>15-minute schedule</b> at ${d.watches.length - 1} watches, but never inside the <b>freeze line</b>, an hour ahead. Every deviation from the position settles at the <b>real-time</b> price.</p>
    <div class="strip"><span>DA prices</span><svg viewBox="0 0 560 40" preserveAspectRatio="none">${lo < 0 ? `<line x1="0" x2="560" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.2)"/>` : ""}<polygon fill="#3a4651" opacity="0.12" points="0,40 ${pts} 560,40"/><polyline fill="none" stroke="#3a4651" stroke-width="2" points="${pts}"/></svg><em>peak ${price(hi)}</em></div>
    <div class="strip pos"><span>DA position</span><svg viewBox="0 0 560 18" preserveAspectRatio="none"><line x1="0" x2="560" y1="9" y2="9" stroke="rgba(0,0,0,0.12)"/>${chips}</svg><em>${pos.some((a) => a) ? "committed" : "none"}</em></div>
    <p class="dim">${board.length ? `${board.length} bulletin${board.length > 1 ? "s" : ""} on the board already: ${board.map((n) => esc(n.badge[0])).join(", ")}.` : "No bulletins on the board."} ${d.notices.filter((n) => n.watch > 0).length ? "More arrive during the day." : ""}</p>`;
}

function pnlHtml(d, settled, ended) {
  const p = ended ? d.ep.pnl : d.intervals.slice(0, settled).reduce((a, x) => ({ da_usd: a.da_usd + x.da_usd, rt_deviation_usd: a.rt_deviation_usd + x.rt_usd, degradation_usd: a.degradation_usd + x.deg_usd }), { da_usd: 0, rt_deviation_usd: 0, degradation_usd: 0 });
  const total = ended ? d.ep.pnl.total_usd : p.da_usd + p.rt_deviation_usd - p.degradation_usd;
  const pen = ended ? (d.ep.pnl.shortfall_usd || 0) : null;
  const exc = ended ? d.ep.pnl.excused_usd || 0 : 0;
  const row = (k, v, cls = "") => `<div class="r ${cls}"><span>${k}</span><b class="num">${v}</b></div>`;
  return `<h5>Settlement so far <small>${ended ? "96 of 96 intervals" : `${settled} of 96 intervals`}</small></h5>
    ${row("Day-ahead revenue", money(p.da_usd, { sign: true }))}
    ${row("Real-time deviation", money(p.rt_deviation_usd, { sign: true }), p.rt_deviation_usd < -0.5 ? "bad" : p.rt_deviation_usd > 0.5 ? "good" : "")}
    ${row("Degradation", money(-p.degradation_usd))}
    ${row("End-of-day penalty", pen == null ? "at midnight" : pen ? money(-pen) : "$0", pen ? "bad" : "")}
    ${exc ? row("Excused (derate)", money(exc, { sign: true })) : ""}
    ${row("Total", money(total), "total")}`;
}

function bulletinsHtml(d, t) {
  const got = d.notices.filter((n) => n.deliverT != null && n.deliverT <= t + 1e-9);
  if (!got.length) return "";
  const recent = got.filter((n) => t - n.deliverT < 2 || n.deliverT === got.at(-1).deliverT);
  const shown = recent.slice(-2).reverse();
  return shown.map((n, i) => {
    const fresh = i === 0 && t - n.deliverT < 0.75;
    const issued = n.issued.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", timeZone: "America/Chicago" }).toLowerCase();
    return `<div class="card bul ${fresh ? "fresh" : ""}"><div class="bh"><span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span><span class="src">${esc(n.name || n.source)}</span><span class="when">issued ${issued}${n.watch === 0 ? " · on the board" : ` · read at ${plain(d.watches[n.watch].min)}`}</span></div><p>${esc(n.text)}</p></div>`;
  }).join("") + (got.length > shown.length ? `<div class="more-b">${got.length - shown.length} earlier bulletin${got.length - shown.length > 1 ? "s" : ""} in the timeline</div>` : "");
}

function planHtml(d, t) {
  const cur = d.watchAt(t);
  const rows = d.watches.filter((w) => w.t <= t + 1e-9 || t >= 24).map((w) => {
    const ns = d.notices.filter((n) => n.watch === w.index && !/cancel/i.test(n.title || ""));
    const pills = w.calls.map((s) => {
      const o = s.output || {};
      const ok = s.tool === "check_schedule" ? o.feasible : o.accepted;
      const ref = (o.refusals || [])[0];
      const got = String(ref?.reason || "").match(/^parse:.*got (\d+)/);
      const why = !ref ? "" : got ? ` · malformed: ${got[1]} values` : ` · ${REASON[String(ref.reason).split(":")[0]] || esc(ref.reason)}${ref.time ? ` ${ref.time}` : ref.hour ? ` ${ref.hour}` : ""}`;
      const from = s.tool === "commit_schedule" && ok ? ` from ${plain((s.args?.start || "00:00").split(":").reduce((h, m) => +h * 60 + +m))}` : "";
      return `<span class="pill ${ok ? "ok" : "no"}">${CALL[s.tool]} ${ok ? "✓" : "✗"}${from}${ok ? "" : why}</span>`;
    }).join("");
    return `<div class="wrow ${w.index === cur.index && t < 24 ? "now" : ""}"><span class="wt">${w.index === 0 ? "2 pm, day before" : plain(w.min)}</span><span class="wc">${ns.slice(0, 2).map((n) => `<span class="badge ${n.badge[1]}">${esc(n.badge[0])}</span>`).join("")}${pills || '<span class="pill idle">held the plan</span>'}</span></div>`;
  }).join("");
  const n = d.watches.reduce((a, w) => a + w.calls.length, 0);
  const said = (d.ep.messages || []).filter((m) => m.role === "assistant" && m.content).map((m) => m.content);
  const msg = (t < 0 ? said.slice(0, 1) : said.slice(-2)).map((m) => `<blockquote>“${esc(m.slice(0, 220))}${m.length > 220 ? "…" : ""}”</blockquote>`).join("");
  return `<h5>How it planned <small>${d.watches.length} watches · ${n} planning call${n === 1 ? "" : "s"}</small></h5><div class="wlist">${rows}</div>${t >= 24 || t < 0 ? msg : ""}`;
}

function scoreHtml(d) {
  const ep = d.ep, R = ep.reward ?? 0, cap = ep.capture_vs_hindsight ?? 0, ref = ep.references || {};
  const naiveR = ep.naive_reward;
  const pos = (r) => `${Math.max(0, Math.min(1, r)) * 100}%`;
  const vs = (k) => {
    const l = d.lanes.find((x) => x.k === k);
    return l ? ep.profit_usd - l.final : null;
  };
  const fmt = (v) => `<b class="${v >= 0 ? "good" : "bad"}">${money(v, { sign: true })}</b>`;
  const rel = [["naive", vs("naive")], ["the anchor", vs("anchor")]].filter(([, v]) => v != null).map(([k, v]) => `vs ${k} ${fmt(v)}`).join(" · ");
  const self = ep.model === "reference/rolling-anchor" ? "This is the rolling anchor: R is 1 by definition." : ep.model === "reference/naive" ? "This is the naive reference." : ep.beats_anchor ? "Beats the rolling anchor." : "Does not beat the rolling anchor.";
  return `<div class="pair"><div><div class="lbl">Hindsight capture</div><div class="r num">${Math.round(cap * 100)}<small>%</small></div>
      <div class="rscale hind"><span class="fill" style="width:${pos(cap)}"></span></div>
      <div class="cap">of the ${money((ref.p_hind ?? 0) - (ref.p_idle ?? 0))} perfect foresight could make</div></div>
    <div class="second"><div class="lbl">R · provisional anchor</div><div class="r num">${R.toFixed(3)}</div>
      <div class="rscale"><span class="fill" style="width:${pos(R)}"></span><i class="tick" style="left:20%" title="idle"></i>${naiveR != null ? `<i class="tick n" style="left:${pos(naiveR)}" title="naive"></i>` : ""}<i class="tick a" style="left:100%" title="anchor"></i></div>
      <div class="cap">idle 0.2 · ${naiveR != null ? `naive ${naiveR.toFixed(2)} · ` : ""}anchor 1.0</div></div></div>
    <div class="line">${self} ${rel}</div>
    <div class="line dim">v2 preview (provisional anchor): the anchor sits near naive on many days, so hindsight capture leads.</div>`;
}

function spark(lanes, t, lo, hi) {
  const W = 240, H = 70;
  const y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  const n = Math.min(96, Math.ceil(t * 4));
  let s = `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.15)"/>`;
  for (const l of lanes) {
    const pts = [[0, 0], ...l.cum.slice(0, n).map((v, i) => [i + 1, v])];
    const col = l.k === "agent" ? "#2c3440" : l.k === "anchor" ? "rgba(28,35,41,0.45)" : l.k === "hind" ? "rgba(29,154,87,0.45)" : "rgba(28,35,41,0.2)";
    s += `<polyline fill="none" stroke="${col}" stroke-width="${l.k === "agent" ? 2.2 : 1.5}" ${l.k === "anchor" || l.k === "hind" ? 'stroke-dasharray="4 3"' : ""} points="${pts.map(([i, v]) => `${(i / 96) * W},${y(v)}`).join(" ")}"/>`;
  }
  return s;
}

/** The headlines: each watch's most urgent bulletin, the day's real-time spike when it settles, each re-plan, and a
 * short end. */
function newsEvents(d) {
  const ev = [];
  const rank = { eea3: 7, eea2: 6, eea1: 5, cons: 4, watch: 3, warn: 3, adv: 2, ocn: 1, nws: 1, ok: 2, off: 0 };
  for (const w of d.watches) {
    const ns = d.notices.filter((n) => n.watch === w.index && w.index > 0);
    if (!ns.length) continue;
    const top = ns.reduce((a, n) => ((rank[n.badge[1]] ?? 0) > (rank[a.badge[1]] ?? 0) ? n : a));
    ev.push({ t: w.t, until: w.t + 1.4, kind: "bulletin", badge: top.badge, text: top.text + (ns.length > 1 ? ` (+${ns.length - 1} more)` : "") });
  }
  const s = d.spikeI;
  if (d.rt[s] > Math.max(200, 2.5 * d.prices[s >> 2])) ev.push({ t: (s + 1) / 4, until: (s + 1) / 4 + 1.2, kind: "peak", text: `Real-time price hits ${price(d.rt[s])}/MWh at ${plain(s * 15)}; the day-ahead price for that hour was ${price(d.prices[s >> 2])}` });
  for (const w of d.watches.slice(1)) {
    const c = w.calls.filter((x) => x.tool === "commit_schedule" && x.output?.accepted).at(-1);
    if (c) ev.push({ t: w.t + 0.05, until: w.t + 1.1, kind: "replan", text: `At ${plain(w.min)} it re-plans everything from ${plain(String(c.args?.start || "00:00").split(":").reduce((h, m) => +h * 60 + +m))}, after the freeze line` });
  }
  if (d.ep.pnl?.shortfall_usd > 0) ev.push({ t: 23.6, until: 25, kind: "penalty", text: `The day ends below the required charge: a ${money(d.ep.pnl.shortfall_usd)} penalty` });
  return ev.sort((a, b) => a.t - b.t);
}

/** The 96-interval timeline: watch markers and bulletins, DA prices as a ghost line, real-time bars that grow in as
 * intervals settle, the DA position by the hour and the 15-minute schedule, the frozen intervals and the freeze line. */
function buildTimeline(d) {
  const root = el("div", "tl live");
  const W = 1200, H = 112, cw = W / 96;
  const Y = { mk: 0, pTop: 16, pBot: 60, pos: 66, posH: 10, sch: 80, schH: 18, bot: 100 };
  const all = [...d.rt, ...d.prices];
  const mx = Math.max(1, ...all.map((p) => Math.abs(p)));
  const k = 40, f = (p) => Math.sign(p) * Math.log1p(Math.abs(p) / k) / Math.log1p(mx / k);
  const lo = Math.min(0, ...all.map(f));
  const zero = Y.pTop + (Y.pBot - Y.pTop) * (1 / (1 - lo));
  const py = (p) => zero - f(p) * (zero - Y.pTop);
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "none", "shape-rendering": "crispEdges" });
  const g = (cls) => svg.appendChild(svgEl("g", { class: cls }));
  const bg = g("bg");
  for (let h = 0; h <= 24; h += 3) bg.appendChild(svgEl("line", { x1: h * 4 * cw, x2: h * 4 * cw, y1: Y.pTop, y2: Y.bot, stroke: "rgba(28,35,41,0.06)" }));
  bg.appendChild(svgEl("line", { x1: 0, x2: W, y1: zero, y2: zero, stroke: "rgba(0,0,0,0.22)" }));
  const freeze = svgEl("rect", { y: Y.pTop - 2, height: Y.bot - Y.pTop + 4, fill: "rgba(28,35,41,0.07)", x: 0, width: 0 });
  svg.appendChild(freeze);
  const rts = g("rt");
  const bars = d.rt.map((p, i) => {
    const r = svgEl("rect", { x: i * cw + 0.8, width: cw - 1.6, y: zero, height: 0, rx: 1, fill: p < 0 ? "#9a7fd0" : p > Math.max(150, 2 * d.prices[i >> 2]) ? "#d9534a" : "#9fb0bc" });
    rts.appendChild(r);
    return r;
  });
  const ghost = d.prices.map((p, h) => `${h * 4 * cw},${py(p)} ${(h + 1) * 4 * cw},${py(p)}`).join(" ");
  svg.appendChild(svgEl("polyline", { points: ghost, fill: "none", stroke: "rgba(28,35,41,0.55)", "stroke-width": 1.4, "stroke-dasharray": "5 3" }));
  const kk = Math.max(d.b.k_dis, d.b.k_ch);
  const posG = g("pos");
  const posR = Array.from({ length: 24 }, (_, h) => posG.appendChild(svgEl("rect", { x: h * 4 * cw + 1.5, width: 4 * cw - 3, y: Y.pos, height: Y.posH, rx: 2, fill: "#e4e7e5" })));
  const schG = g("sch");
  const schR = Array.from({ length: 96 }, (_, i) => schG.appendChild(svgEl("rect", { x: i * cw + 0.6, width: cw - 1.2, y: Y.sch, height: Y.schH, rx: 1, fill: "#e4e7e5" })));
  const hatch = svgEl("rect", { y: Y.sch - 1, height: Y.schH + 2, fill: "url(#fz)", x: 0, width: 0 });
  const defs = svgEl("defs", {});
  defs.innerHTML = `<pattern id="fz" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="2" height="5" fill="rgba(28,35,41,0.28)"/></pattern>`;
  svg.prepend(defs);
  svg.appendChild(hatch);
  const fline = svgEl("line", { y1: Y.mk + 4, y2: Y.bot, stroke: "#1c2329", "stroke-width": 1.4, "stroke-dasharray": "3 2" });
  svg.appendChild(fline);
  const mk = g("mk");
  mk.setAttribute("shape-rendering", "geometricPrecision");
  const wm = d.watches.slice(1).map((w) => {
    const x = (w.min / 15) * cw;
    const m = svgEl("path", { d: `M${x - 4},${Y.mk + 2} L${x + 4},${Y.mk + 2} L${x},${Y.mk + 8} Z`, fill: "#1c2329" });
    mk.appendChild(m);
    return { w, m };
  });
  const COL = { eea3: "#8e1b14", eea2: "#cf3e33", eea1: "#e0632c", cons: "#d9820b", watch: "#d9a30b", warn: "#b5487a", adv: "#c9b23a", ocn: "#5b7c99", nws: "#7d8ea0", ok: "#1d9a57", off: "#b0b7bb" };
  const icons = d.notices.filter((n) => n.revealMin >= 0 && n.revealMin < 1440).map((n) => {
    const x = (n.revealMin / 15) * cw;
    const c = svgEl("rect", { x: x - 3.5, y: Y.mk + 4, width: 7, height: 7, transform: `rotate(45 ${x} ${Y.mk + 7.5})`, fill: COL[n.badge[1]] || "#7d8ea0", stroke: "#fff", "stroke-width": 1 });
    mk.appendChild(c);
    return { n, c };
  });
  root.innerHTML = `<div class="rows"><span style="top:${(Y.pTop + 8) / H * 100}%">price</span><span style="top:${Y.pos / H * 100}%">DA</span><span style="top:${(Y.sch + 2) / H * 100}%">plan</span></div>
    <div class="hours">${[0, 3, 6, 9, 12, 15, 18, 21].map((h) => `<span style="left:${(h / 24) * 100}%">${hourLabel(h)}</span>`).join("")}</div>
    <div class="legend"><span><i style="background:#9fb0bc"></i>real-time</span><span><i class="dash"></i>day-ahead</span><span><i style="background:${CHARGE}"></i>charge</span><span><i style="background:${DISCHARGE}"></i>discharge</span><span><i class="hz"></i>frozen</span><span><i class="dia"></i>bulletin</span><span class="dim">log price scale</span></div>`;
  const plot = el("div", "plot");
  plot.append(svg);
  const ph = el("div", "ph");
  plot.append(ph);
  root.append(plot);
  const colour = (a) => (a > 0 ? DISCHARGE : a < 0 ? CHARGE : "#e4e7e5");
  let lastS = -1, lastW = -1, lastPos = null;
  const barY = [], barH = [];
  return {
    root, svg,
    update(t, settled, w) {
      const tt = Math.max(0, Math.min(24, t));
      ph.style.left = `${(tt / 24) * 100}%`;
      const bar = (i) => {
        const age = t - (i + 1) / 4, grow = age < 0 ? 0 : Math.min(1, age / 0.12), y = py(d.rt[i]);
        const top = (Math.min(y, zero) + (1 - grow) * (y < zero ? zero - y : 0)).toFixed(2);
        const hh = Math.max(grow ? 1.2 : 0, Math.abs(y - zero) * grow).toFixed(2);
        if (barY[i] !== top) bars[i].setAttribute("y", (barY[i] = top));
        if (barH[i] !== hh) bars[i].setAttribute("height", (barH[i] = hh));
      };
      for (let i = Math.max(0, settled - 2); i < Math.min(96, settled + 1); i++) bar(i);
      if (settled !== lastS || w.index !== lastW) {
        if (Math.abs(settled - lastS) > 2 || lastS < 0) for (let i = 0; i < 96; i++) bar(i);
        lastS = settled;
        lastW = w.index;
        const plan = t < -1.2 ? Array(96).fill(0) : d.snaps[w.index];
        const pos = t < -1.2 ? Array(24).fill(0) : d.daAt[w.index] || Array(24).fill(0);
        if (pos !== lastPos) {
          lastPos = pos;
          pos.forEach((a, h) => {
            const hh = Math.max(2, (Math.abs(a) / kk) * Y.posH);
            posR[h].setAttribute("height", hh);
            posR[h].setAttribute("y", Y.pos + (Y.posH - hh) / 2);
            posR[h].setAttribute("fill", colour(a));
          });
        }
        const fz = t < 0 ? 0 : Math.max(settled, Math.min(96, w.freezeI));
        for (let i = 0; i < 96; i++) {
          const a = i < settled ? d.executed[i] : plan[i];
          const hh = Math.max(2, (Math.abs(a) / kk) * Y.schH);
          schR[i].setAttribute("height", hh);
          schR[i].setAttribute("y", Y.sch + (Y.schH - hh) / 2);
          schR[i].setAttribute("fill", colour(a));
          schR[i].setAttribute("opacity", i < settled ? 1 : i < fz ? 0.9 : 0.5);
        }
        const x0 = settled * cw, x1 = fz * cw;
        freeze.setAttribute("x", x0);
        freeze.setAttribute("width", Math.max(0, x1 - x0));
        hatch.setAttribute("x", x0);
        hatch.setAttribute("width", Math.max(0, x1 - x0));
        const showF = t >= 0 && t < 24 && w.freezeI > settled && w.freezeI <= 96;
        fline.setAttribute("x1", w.freezeI * cw);
        fline.setAttribute("x2", w.freezeI * cw);
        fline.setAttribute("opacity", showF ? 1 : 0);
        for (const { w: x, m } of wm) m.setAttribute("fill", x.t <= t + 1e-9 ? "#1c2329" : "rgba(28,35,41,0.28)");
        for (const { n, c } of icons) c.setAttribute("opacity", n.revealT <= t + 1e-9 ? 1 : 0.3);
      }
    },
  };
}
