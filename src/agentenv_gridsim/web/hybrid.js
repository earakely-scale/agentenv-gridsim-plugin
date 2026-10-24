/** A solar-plus-storage day (gridsim.episode/v3) turned into what the scene and the cards show: the PV the panels can
 * deliver and what reaches the meter, the battery's move, the reserve book per product and hour, deployments, drift,
 * governor clips, failures to provide and excuses, and the references' cash on the same day. */
import { absolute, placeOf, REGIONS } from "./places.js";
import { badge, clockMin, minutesOf, replayT } from "./live.js";

export { clockMin };
export const HYBRID_SCHEMA = "gridsim.episode/v3";
export const PRODUCTS = ["regup", "regdn", "rrs", "ecrs", "nspin"];
export const UP = ["regup", "rrs", "ecrs", "nspin"];
/** Products are told apart by a letter and a hatch, never a hue: cyan is charge and amber discharge everywhere. */
export const PROD = {
  regup: { name: "RegUp", glyph: "U", hatch: "fwd" },
  regdn: { name: "RegDn", glyph: "D", hatch: "dots" },
  rrs: { name: "RRS", glyph: "R", hatch: "back" },
  ecrs: { name: "ECRS", glyph: "E", hatch: "cross" },
  nspin: { name: "Non-Spin", glyph: "N", hatch: "rows" },
};
/** gridsim_core.contract.AS_DURATION_H: hours of SoC each MW of an award must hold, by era. */
export const DURATION = {
  A: { regup: 1, regdn: 1, rrs: 1, nspin: 4 },
  B: { regup: 1, regdn: 1, rrs: 1, ecrs: 2, nspin: 4 },
  C: { regup: 0.5, regdn: 0.5, rrs: 0.5, ecrs: 1, nspin: 4 },
};
export const ERA = { A: ["PRE-ECRS", "pre-ECRS rules (no ECRS yet)"], B: ["ECRS", "ECRS era"], C: ["RTC+B as T2", "RTC+B day played with day-ahead reserves only"] };
export const RULES = {
  frozen: "inside the freeze", power: "over the power rating", headroom_up: "no power headroom for up-reserves",
  headroom_dn: "no power headroom for RegDn", meter_up: "past the meter with up-reserves", meter_dn: "past the import limit",
  soc_empty: "sells more than it holds", soc_full: "charges past full", cycle_cap: "past the cycle cap",
  reserve_up: "too little charge to back the up-reserves", reserve_dn: "too little room to back RegDn",
  not_offered: "product not offered", not_qualified: "site not qualified", as_fixed: "reserves are fixed after 2 pm", parse: "not a plan",
};
const SOLAR_GAP = 0.5;

const sum = (xs) => xs.reduce((a, x) => a + x, 0);
const cum = (xs) => xs.reduce((acc, x) => (acc.push((acc.at(-1) ?? 0) + x), acc), []);
const ease = (u) => u * u * (3 - 2 * u);

/** Fraction-hours an event product deploys in each hour (gridsim_core.hybrid.deploy_hours) and its minute window. */
function deployWindows(notices, dur) {
  return notices.filter((n) => n.deploy && dur[n.deploy.product] != null).map((n) => {
    const d = n.deploy;
    const a = Math.max(0, d.start_min), b = Math.min(1440, d.end_min, d.start_min + Math.round(dur[d.product] * 60));
    return { ...d, a, b, n };
  });
}

export function loadHybrid(ep, weather = null) {
  const task = ep.task, date = task.date, site = task.site, bess = site.bess;
  const era = task.era || "B";
  const dur = DURATION[era];
  const offered = Object.keys(ep.book || {}).filter((k) => k !== "energy");
  const E = bess.e_mwh, P = bess.p_mw, eta = bess.eta;
  const L = site.coupling === "dc" && site.inverter_mw ? Math.min(site.poi_mw, site.inverter_mw) : site.poi_mw;
  const Limp = site.poi_import_mw ?? site.poi_mw;
  const b = { p_dis_mw: P, p_ch_mw: P, energy_mwh: E, soc_levels: 8, s0: (bess.s0_mwh / E) * 8, s_end_min: (bess.s_end_min_mwh / E) * 8, eta, c_deg: bess.c_deg, unit_mwh: E / 8 };
  const place = placeOf(task.settlement_point);
  const region = absolute(REGIONS[task.region] || REGIONS.central);
  const watches = ep.watches.map((w) => {
    const min = minutesOf(w.time, date), fz = minutesOf(w.freeze_line, date);
    return { ...w, min, t: replayT(min), freezeMin: fz, freezeT: replayT(fz), freezeH: Math.max(0, Math.min(24, Math.ceil(fz / 60))), calls: [], refused: [] };
  });
  const notices = (ep.notices || []).map((n) => {
    const w = n.watch != null ? watches[n.watch] : null;
    const rev = minutesOf(n.reveal_at, date);
    return { ...n, badge: n.deploy ? [`${PROD[n.deploy.product].name} deployed`, "dep"] : badge(n), revealMin: rev, revealT: replayT(rev), deliverT: w ? w.t : null, issued: new Date(n.issued_at) };
  });
  const realized = {};
  let book = Object.fromEntries(["energy", ...offered].map((k) => [k, Array(24).fill(0)]));
  const snaps = [];
  for (const w of watches) {
    for (const s of ep.steps.filter((x) => x.watch === w.index)) {
      const out = s.output || {};
      if (s.tool === "commit_schedule" && out.book) book = out.book;
      if (s.tool === "advance") for (const r of out.realized || []) realized[r.h] = r;
      if (s.tool === "check_schedule" || s.tool === "commit_schedule") {
        w.calls.push(s);
        const bad = s.tool === "commit_schedule" ? out.refused || [] : [];
        for (const r of bad) w.refused.push(r);
      }
    }
    snaps.push(book);
  }
  const da = ep.da;
  const wins = deployWindows(notices, dur);
  const hours = ep.hours.map((x, h) => {
    const a = Object.fromEntries(PRODUCTS.map((k) => [k, +(x.awards?.[k] ?? 0)]));
    const rUp = sum(UP.map((k) => (dur[k] ?? 0) * a[k]));
    const rDn = eta * (dur.regdn ?? 0) * a.regdn;
    const pvUsed = Math.max(0, x.pv_mw - x.curtailed_mw);
    const regUp = x.reg_up_frac * a.regup;
    const events = wins.filter((w) => w.b > 60 * h && w.a < 60 * h + 60 && a[w.product] > 0).map((w) => ({ ...w, mw: w.frac * a[w.product], from: Math.max(w.a, 60 * h), to: Math.min(w.b, 60 * h + 60) }));
    const depEvt = Math.max(0, x.deployed_up_mwh - regUp);
    const batt = x.b_mw + x.deployed_up_mwh - x.deployed_dn_mwh;
    const r = realized[h] || {};
    const cash = x.energy_da_usd + x.energy_rt_usd + x.as_da_usd + x.as_rt_usd - x.deg_usd - x.ftp_usd;
    return {
      h, da: x.da, rt: x.rt, price: x.rt, neg: x.rt < 0, pvAvail: x.pv_mw, pvUsed, curtailed: x.curtailed_mw, export: x.export_mw, xDa: x.x_da_mw,
      e: x.e_mw, b: x.b_mw, batt, up: x.deployed_up_mwh, dn: x.deployed_dn_mwh, depEvt, regUp, regDn: x.reg_dn_frac * a.regdn, events,
      awards: a, rUp, rDn, governor: x.governor, socBefore: ep.soc_path[h], socAfter: ep.soc_path[h + 1],
      cash, cashParts: { energy_da: x.energy_da_usd, energy_rt: x.energy_rt_usd - (x.deployed_up_mwh - x.deployed_dn_mwh) * x.rt, as: x.as_da_usd + x.as_rt_usd, dep: (x.deployed_up_mwh - x.deployed_dn_mwh) * x.rt, deg: x.deg_usd, ftp: x.ftp_usd },
      ftpUsd: x.ftp_usd, excusedUsd: x.excused_usd, ftpMw: r.ftp_mw ?? 0, excusedMw: r.excused_mw ?? 0,
      mode: batt > 0.5 ? "discharge" : batt < -0.5 ? "charge" : "idle", action: Math.sign(Math.round(batt)),
    };
  });
  hours.at(-1).cash -= ep.cash?.end_penalty || 0;
  const agentCum = cum(hours.map((x) => x.cash));
  const lanes = (ep.race || []).map((l) => ({ ...l }));
  const rt = task.rt, prices = task.prices;
  const sorted = [...rt].sort((p, q) => p - q);
  const peakH = rt.indexOf(Math.max(...rt));
  const g = ep.grade || null;
  const d = {
    hybrid: true, live: true, ep, task, site, b, E, P, eta, L, Limp, era, dur, offered, prices, rt, place, region, weather, watches, notices, snaps, da,
    hours, agentCum, lanes, wins, peakH, median: sorted[12], firstNeg: hours.findIndex((x) => x.neg && x.pvAvail > 1), trunc: null,
    reward: ep.reward, capture: ep.capture_vs_hindsight, grade: g,
    pvPeak: Math.max(...hours.map((x) => x.pvAvail)), pvMwac: site.pv_mwac,
    dateLabel: new Date(`${date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
    message: (ep.messages || []).filter((m) => m.role === "assistant").map((m) => m.content).join("\n\n"),
  };
  d.weight0 = weight0(d);
  d.s0 = bess.s0_mwh;
  d.at = (t) => at(d, t);
  d.pre = (t) => preAt(d, t);
  d.watchAt = (t) => {
    let k = 0;
    for (const w of watches) if (w.t <= t + 1e-9) k = w.index;
    return watches[k];
  };
  return d;
}

/** The weight-0 rows the score card shows beside R, from the episode and its hours. */
function weight0(d) {
  const ep = d.ep, c = ep.cash || {}, hs = d.hours;
  const asRev = (c.as_da || 0) + (c.as_rt || 0);
  const en = Math.max(0, (c.energy_da || 0) + (c.energy_rt || 0) - (ep.references?.p_idle || 0));
  const clippable = sum(hs.map((x) => Math.max(0, x.pvAvail - d.L)));
  return {
    capture: ep.capture_vs_hindsight,
    asShare: asRev + en > 1e-6 ? asRev / (asRev + en) : null,
    clipPct: clippable > 1e-4 ? (100 * sum(hs.map((x) => Math.max(0, x.pvUsed - d.L)))) / clippable : null,
    curtailed: sum(hs.map((x) => x.curtailed)),
    ftpMwh: sum(hs.map((x) => x.ftpMw)), excusedMwh: sum(hs.map((x) => x.excusedMw)),
    governor: hs.filter((x) => x.governor).length,
  };
}

/** Deployment MW at minute m of hour x (its events, frac x award, within each window). */
export function depAt(x, m) {
  return sum(x.events.filter((w) => m >= w.from && m < w.to).map((w) => w.mw));
}

/** What the scene shows at t: SoC with regulation jiggle and deployment draw inside the hour, the battery's MW, the
 * PV and the meter, and the reserve bands as they stand. */
export function at(d, t) {
  const tt = Math.max(0, Math.min(23.999, t));
  const h = Math.floor(tt), u = tt - h, x = d.hours[h], m = tt * 60;
  const depMins = sum(x.events.map((w) => (w.to - w.from) * w.mw));
  const done = depMins > 0 ? sum(x.events.map((w) => Math.max(0, Math.min(m, w.to) - w.from) * w.mw)) / depMins : 0;
  const depPart = -Math.min(x.depEvt, x.socBefore);
  const lin = x.socAfter - x.socBefore - depPart;
  const jig = (x.regUp + x.regDn) * 0.22 * Math.sin(Math.PI * u) * (Math.sin(tt * 37.1) * 0.6 + Math.sin(tt * 91.7 + 1.3) * 0.4);
  const soc = Math.max(0, Math.min(d.E, x.socBefore + lin * u + depPart * done + jig));
  const dep = depAt(x, m);
  const net = depMins ? x.batt - x.depEvt + dep : x.batt;
  const exp = x.export + (net - x.batt);
  const bands = UP.filter((k) => d.dur[k] && x.awards[k] > 0).map((k) => {
    const full = d.dur[k] * x.awards[k];
    const drawn = x.events.filter((w) => w.product === k).reduce((a, w) => a + (Math.max(0, Math.min(m, w.to) - w.from) / 60) * w.mw, 0);
    return { k, mwh: Math.max(0, full - drawn), full, live: x.events.some((w) => w.product === k && m >= w.from && m < w.to) };
  });
  const mode = net > 0.5 ? "discharge" : net < -0.5 ? "charge" : "idle";
  const prev = h > 0 ? d.hours[h - 1] : x;
  const off = offOf(prev) + (offOf(x) - offOf(prev)) * ease(Math.min(1, u / 0.12));
  return {
    ...x, t, u, soc, socLevels: (soc / d.E) * 8, net, mw: net, exp, dep, mode, bands, floor: sum(bands.map((z) => z.mwh)), head: x.rDn,
    upMw: sum(UP.map((k) => x.awards[k])), off, pvShare: 1 - offOf(x), stow: offOf(x) > 0.98, fromPv: net < 0 ? Math.min(x.pvUsed, -net) : 0,
  };
}

const offOf = (y) => (y.pvAvail > SOLAR_GAP ? Math.max(0, Math.min(1, y.curtailed / y.pvAvail)) : 0);

/** The afternoon before (the intro): the plant runs on the day's PV profile at the same clock hour, the battery
 * idle at its starting charge. */
export function preAt(d, t) {
  const h = ((Math.floor(clockMin(t) / 60) % 24) + 24) % 24, x = d.hours[h];
  return { ...x, t, u: 0, soc: d.s0, socLevels: d.b.s0, net: 0, mw: 0, exp: x.pvAvail, dep: 0, mode: "idle", bands: [], floor: 0, head: 0, upMw: 0, off: 0, pvUsed: x.pvAvail, pvShare: 1, stow: false, fromPv: 0, curtailed: 0 };
}

/** Each lane's cash at t, interpolated inside the hour. */
export function laneAt(cumv, t, final) {
  if (t >= 24) return final;
  if (t <= 0) return 0;
  const h = Math.min(23, Math.floor(t)), u = t - h;
  const before = h > 0 ? cumv[h - 1] : 0;
  return before + (cumv[h] - before) * u;
}

export function hourSpan(h) {
  const f = (k) => (k % 24 === 0 ? "midnight" : k === 12 ? "noon" : k < 12 ? `${k} am` : `${k - 12} pm`);
  return `${f(h)}–${f(h + 1)}`;
}
