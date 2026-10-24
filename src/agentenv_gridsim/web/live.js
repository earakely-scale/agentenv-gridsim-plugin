/** A live day (gridsim.episode/v2) turned into what the scene and the cards show by the quarter hour: the DA position
 * committed the day before, the 15-minute schedule as re-planned at each watch, RT prices as intervals settle, the
 * bulletins and the references' cash on the same two-settlement rules. */
import { absolute, placeOf, REGIONS } from "./places.js";

export const LIVE_SCHEMA = "gridsim.episode/v2";
const P_FLOOR = 50;

/** Minutes from D 00:00 of a "YYYY-MM-DD HH:MM" label (D-1 and D+1 included). */
export function minutesOf(label, date) {
  const [d, hm] = label.split(" ");
  const [h, m] = hm.split(":").map(Number);
  return (d === date ? 0 : d < date ? -1440 : 1440) + h * 60 + m;
}

/** Replay hours: the day runs 0..24; the ten hours from watch 0 (D-1 14:00) to midnight play in the intro's -2..0. */
export const replayT = (min) => (min >= 0 ? min / 60 : Math.max(-2, -2 + ((min + 600) / 600) * 2));
export const clockMin = (t) => (t >= 0 ? t * 60 : -600 + ((t + 2) / 2) * 600);

export function parseInts(a) {
  const xs = typeof a === "string" ? a.trim().replace(/^\[|\]$/g, "").split(/[\s,]+/) : Array.isArray(a) ? a : null;
  const out = xs?.map(Number);
  return out && out.every(Number.isInteger) ? out : null;
}

export const expand = (hourly) => hourly.flatMap((a) => [a, a, a, a]);

const LEVELS = {
  EEA3: ["EEA 3", "eea3"], EEA2: ["EEA 2", "eea2"], EEA1: ["EEA 1", "eea1"], EEA_exit: ["Normal ops", "ok"],
  Emergency: ["Emergency", "eea2"], conservation: ["Conservation", "cons"], Watch: ["Watch", "watch"],
  Advisory: ["Advisory", "adv"], OCN: ["OCN", "ocn"], Warning: ["Warning", "warn"], derate: ["Derate", "warn"],
};

/** The badge (text, class) for a notice: its level, NWS products by name, cancellations greyed. */
export function badge(n) {
  const cancel = /cancel/i.test(n.title || "");
  if (n.source === "NWS") return [n.title?.replace(/^NWS\s+/, "") || n.level || "NWS", cancel ? "off" : n.level === "Warning" ? "warn" : "nws"];
  const [text, cls] = LEVELS[n.level] || LEVELS[n.kind] || [n.level || n.kind || "Notice", "ocn"];
  return [cancel ? (n.level === "EEA_exit" ? "Retracted" : `${text} ended`) : text, cancel ? "off" : cls];
}

const cashOf = (b, a) => {
  const mwh = a > 0 ? b.unit_mwh * a : (b.unit_mwh * a) / b.eta;
  return { mwh, deg: b.c_deg * b.unit_mwh * Math.max(a, 0) };
};

/** Per-interval two-settlement cash of a DA position (24, live-grid units) and a physical schedule (96). */
export function settle(b, da, rt, pos, phys) {
  const m = pos.map((d) => 4 * cashOf(b, d).mwh);
  return phys.map((a, t) => {
    const h = t >> 2, c = cashOf(b, a);
    return da[h] * (m[h] / 4) + rt[t] * (c.mwh - m[h] / 4) - c.deg;
  });
}

const cum = (xs) => xs.reduce((acc, x) => (acc.push((acc.at(-1) ?? 0) + x), acc), []);

export function loadLive(ep, weather = null) {
  const task = ep.task, g = ep.grid, date = task.date;
  const b = { ...task.battery, ...g };
  const da = task.prices, rt = task.rt;
  const place = placeOf(task.settlement_point);
  const region = absolute(REGIONS[task.region] || REGIONS.central);
  const watches = ep.watches.map((w) => {
    const min = minutesOf(w.time, date), fz = minutesOf(w.freeze_line, date);
    return { ...w, min, t: replayT(min), freezeMin: fz, freezeT: replayT(fz), freezeI: Math.max(0, Math.min(96, fz / 15)), calls: [] };
  });
  const notices = (ep.notices || []).map((n) => {
    const w = n.watch != null ? watches[n.watch] : null;
    const rev = minutesOf(n.reveal_at, date);
    const issued = new Date(n.issued_at);
    return { ...n, badge: badge(n), revealMin: rev, revealT: replayT(rev), deliverT: w ? w.t : null, issued };
  });
  let sched = Array(96).fill(0), daPos = null;
  const snaps = [], daAt = [];
  for (const w of watches) {
    for (const s of ep.steps.filter((x) => x.watch === w.index)) {
      const out = s.output || {};
      if (s.tool === "commit_da" && out.accepted) {
        daPos = parseInts(s.args?.position);
        if (out.schedule_follows_da && daPos) sched = expand(daPos);
      } else if (s.tool === "commit_schedule" && out.accepted) {
        const acts = parseInts(s.args?.actions);
        const step = s.args?.step || "15m";
        const [hh, mm] = String(s.args?.start || "00:00").split(":").map(Number);
        const start = (hh * 60 + mm) / 15;
        const full = step === "1h" ? expand(acts) : acts;
        sched = sched.slice(0, start).concat(full).slice(0, 96);
      }
      if (["commit_da", "check_schedule", "commit_schedule"].includes(s.tool)) w.calls.push(s);
    }
    snaps.push(sched.slice());
    daAt.push(daPos);
  }
  if (JSON.stringify(snaps.at(-1)) !== JSON.stringify(ep.schedule)) {
    console.warn("live: the replayed schedule differs from the episode's; showing the episode's at the last watch");
    snaps[snaps.length - 1] = ep.schedule.slice();
  }
  const daPosition = ep.da_position || daPos || Array(24).fill(0);
  const ivs = ep.intervals || [];
  const agentCash = ivs.map((x) => x.da_usd + x.rt_usd - x.deg_usd);
  const agentCum = cum(agentCash);
  const R = ep.references || {};
  const lanes = [];
  const mk = (k, label, pos, phys, final) => {
    if (!pos || !phys) return;
    const c = cum(settle(b, da, rt, pos, phys));
    lanes.push({ k, label, cum: c, final: final ?? c.at(-1), sched: phys, pos });
  };
  const self = ep.model?.startsWith("reference/") ? ep.model.slice(10) : null;
  if (self !== "naive") mk("naive", "Naive (v1's plan, held)", R.naive?.da, R.naive?.da && expand(R.naive.da), R.p_naive);
  if (self !== "rolling-anchor") mk("anchor", "Rolling anchor", R.roll?.da, R.roll?.executed, R.p_roll);
  mk("hind", "Hindsight", R.hind?.da, R.hind?.schedule, R.p_hind);
  const pen = Math.max(0, b.s_end_min - (ep.soc_path?.at(-1) ?? b.s_end_min)) * (b.unit_mwh / b.eta) * Math.max(Math.max(...da), P_FLOOR);
  const hourly = Array.from({ length: 24 }, (_, h) => {
    const a = ep.executed.slice(4 * h, 4 * h + 4).reduce((x, y) => x + y, 0) / 4;
    const p = rt.slice(4 * h, 4 * h + 4).reduce((x, y) => x + y, 0) / 4;
    return { h, action: Math.round(a), neg: p < 0, mode: a > 0 ? "discharge" : a < 0 ? "charge" : "idle", price: p };
  });
  const rtH = hourly.map((x) => x.price);
  const peakH = rtH.indexOf(Math.max(...rtH));
  const sorted = [...rtH].sort((x, y) => x - y);
  const spikeI = rt.indexOf(Math.max(...rt));
  const d = {
    live: true, ep, task, b, prices: da, rt, place, region, weather, watches, notices, snaps, daAt, daPosition,
    executed: ep.executed, soc: ep.soc_path, intervals: ivs, agentCash, agentCum, lanes, penalty: pen,
    hours: hourly, peakH, median: sorted[12], firstNeg: hourly.findIndex((x) => x.neg && x.action < 0), trunc: null,
    spikeI, reward: ep.reward, capture: ep.capture_vs_hindsight,
    dateLabel: new Date(`${date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
    message: (ep.messages || []).filter((m) => m.role === "assistant").map((m) => m.content).join("\n\n"),
  };
  d.at = (t) => at(d, t);
  d.watchAt = (t) => watchAt(d, t);
  return d;
}

/** The latest watch at or before t (watch 0 from the start of the intro). */
export function watchAt(d, t) {
  let k = 0;
  for (const w of d.watches) if (w.t <= t + 1e-9) k = w.index;
  return d.watches[k];
}

/** What the scene shows at t: the executed quarter hour, its MW, SoC and price. */
export function at(d, t) {
  const tt = Math.max(0, Math.min(23.999, t));
  const i = Math.floor(tt * 4), u = tt * 4 - i, h = i >> 2;
  const a = d.executed[i];
  const soc = d.soc[i] + (d.soc[i + 1] - d.soc[i]) * u;
  return { h, i, u, t, action: a, mw: a * d.b.unit_mwh * 4, soc, neg: d.rt[i] < 0, price: d.prices[h], mode: a > 0 ? "discharge" : a < 0 ? "charge" : "idle" };
}
