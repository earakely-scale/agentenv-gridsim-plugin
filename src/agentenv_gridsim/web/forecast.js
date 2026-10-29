/** A Weather Front window (gridsim.episode/v4) turned into what the scene and the cards show: v3's plant over two or
 * three operating days, each day's DAM gate and results, the book as re-planned at each watch, the forecast vintages
 * as issued (and what the agent read at each watch), the weather observed at the site's airport with the cold front's
 * passage and the frost it leaves, and the references' cash over the window. Time t is hours from d1 00:00 CPT; the
 * clock opens at t = -14 (10:00 the day before). */
import { badge } from "./live.js";
import { PROD, PRODUCTS, UP, DURATION } from "./hybrid.js";
import { absolute, placeOf, REGIONS } from "./places.js";
import { sunAt, tzOffsetMinutes } from "./stage/astro.js";
import { frostSeries, frontOf, sample, snowSeries, weatherSeries } from "./stage/wx.js";

export const FORECAST_SCHEMA = "gridsim.episode/v4";
export const OPEN = -14;
const SOLAR_GAP = 0.5;
const DAY_MS = 86400000;

const sum = (xs) => xs.reduce((a, x) => a + x, 0);
const cum = (xs) => xs.reduce((acc, x) => (acc.push((acc.at(-1) ?? 0) + x), acc), []);
const ease = (u) => u * u * (3 - 2 * u);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

/** Minutes from d1 00:00 of a CPT time, "YYYY-MM-DDTHH:MM-06:00" (rules 4.1) or "YYYY-MM-DD HH:MM" (4.0). */
export function minuteOf(label, d1) {
  const [, d, h, m] = /^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})/.exec(label);
  return Math.round((Date.parse(`${d}T00:00:00Z`) - Date.parse(`${d1}T00:00:00Z`)) / 60000) + Number(h) * 60 + Number(m);
}

/** The DAM gate (10:00 the day before) and the results (13:30, read at the 14:00 watch) of day k, in minutes. */
export const gateMin = (k) => 1440 * k - 840;
export const resultsMin = (k) => 1440 * k - 630;

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function buildForecast(ep, weather = null) {
  const task = ep.task, d1 = task.d1, n = ep.hours.length / 24, H = 24 * n, E = H;
  const lite = ep.tier === "front-lite";
  const site = task.site, bess = site.bess, era = task.era || "B", dur = DURATION[era];
  const offered = lite ? [] : Object.keys(task.mcpc_da || {}).filter((k) => dur[k] != null);
  const P = bess.p_mw, Ebat = bess.e_mwh, eta = bess.eta;
  const L = lite ? site.poi_mw : site.coupling === "dc" && site.inverter_mw ? Math.min(site.poi_mw, site.inverter_mw) : site.poi_mw;
  const Limp = site.poi_import_mw ?? site.poi_mw;
  const b = { p_dis_mw: P, p_ch_mw: P, energy_mwh: Ebat, soc_levels: 8, s0: (bess.s0_mwh / Ebat) * 8, s_end_min: (bess.s_end_min_mwh / Ebat) * 8, eta, c_deg: bess.c_deg, unit_mwh: Ebat / 8 };
  const place = placeOf(task.settlement_point);
  const region = absolute(REGIONS[task.region] || REGIONS.central);
  const tz = tzOffsetMinutes(d1);
  const d1ms = Date.parse(`${d1}T00:00:00Z`) - tz * 60000;
  const tOf = (iso) => (Date.parse(iso) - d1ms) / 3600000;
  const dayName = (k) => {
    const x = new Date(Date.parse(`${d1}T12:00:00Z`) + k * DAY_MS);
    return `${DAY_NAMES[x.getUTCDay()]} ${MONTHS[x.getUTCMonth()]} ${x.getUTCDate()}`;
  };

  const watches = ep.watches.map((w) => {
    const min = minuteOf(w.time, d1), fz = minuteOf(w.freeze_line, d1);
    return { ...w, min, t: min / 60, freezeMin: fz, freezeH: clamp(Math.ceil(fz / 60), 0, H), calls: [], reads: [], refused: [], dam: [], gate: null };
  });
  const notices = (ep.notices || []).map((x) => {
    const w = x.watch != null ? watches[x.watch] : null;
    const rev = minuteOf(x.reveal_at, d1);
    return { ...x, badge: x.deploy ? [`${PROD[x.deploy.product]?.name || x.deploy.product} deployed`, "dep"] : badge(x), revealMin: rev, revealT: rev / 60, deliverT: w ? w.t : null, issued: new Date(x.issued_at) };
  });
  for (let k = 0; k < n; k++) {
    const g = watches.find((w) => w.min === gateMin(k));
    if (g) g.gate = k;
  }

  const realized = {};
  let book = { energy: Array(H).fill(0) };
  let xda = Array(H).fill(null), eda = Array(H).fill(null), awards = Object.fromEntries(offered.map((k) => [k, Array(H).fill(0)]));
  const snaps = [];
  for (const w of watches) {
    for (const s of ep.steps.filter((x) => x.watch === w.index)) {
      const out = s.output || {};
      if (s.tool === "commit_schedule" && out.book) book = out.book;
      if (s.tool === "submit_dam" && Array.isArray(out.x_da_mw)) {
        const k = Math.round(minuteOf(`${out.operating_day} 00:00`, d1) / 1440);
        xda = xda.slice(), eda = eda.slice();
        awards = Object.fromEntries(Object.entries(awards).map(([p, v]) => [p, v.slice()]));
        for (const h of out.accepted || []) {
          const i = h % 24, hh = 24 * k + i;
          xda[hh] = out.x_da_mw[i];
          eda[hh] = out.x_da_mw[i] - (out.pv_da_mw?.[i] ?? 0);
          for (const p of offered) awards[p][hh] = +(out.awards?.[p]?.[i] ?? 0);
        }
        w.dam.push(s);
      }
      if (s.tool === "advance") for (const r of out.realized || []) realized[r.h] = r;
      if (s.tool === "check_schedule" || s.tool === "commit_schedule") {
        w.calls.push(s);
        if (s.tool === "commit_schedule") for (const r of out.refused || []) w.refused.push(r);
      }
      if ((s.tool === "get_forecast" || s.tool === "get_forecast_drift") && !out.error) w.reads.push(s);
    }
    snaps.push({ book, xda, eda, awards });
  }

  const wins = notices.filter((x) => x.deploy && dur[x.deploy.product] != null).map((x) => {
    const dd = x.deploy;
    const a = Math.max(0, dd.start_min), bb = Math.min(60 * H, dd.end_min, dd.start_min + Math.round(dur[dd.product] * 60));
    return { ...dd, a, b: bb, n: x };
  });
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
    const dep = (x.deployed_up_mwh - x.deployed_dn_mwh) * x.rt;
    const cash = x.energy_da_usd + x.energy_rt_usd + x.as_da_usd - x.deg_usd - x.ftp_usd;
    return {
      h, day: Math.floor(h / 24), da: x.da, rt: x.rt, price: x.rt, neg: x.rt < 0, pvAvail: x.pv_mw, pvUsed, curtailed: x.curtailed_mw, export: x.export_mw, xDa: x.x_da_mw,
      pvGate: x.pv_p50_gate, e: x.b_mw, b: x.b_mw, batt, up: x.deployed_up_mwh, dn: x.deployed_dn_mwh, depEvt, regUp, regDn: x.reg_dn_frac * a.regdn, events,
      awards: a, rUp, rDn, governor: x.governor, socBefore: ep.soc_path[h], socAfter: ep.soc_path[h + 1],
      cash, cashParts: { energy_da: x.energy_da_usd, energy_rt: x.energy_rt_usd - dep, as: x.as_da_usd, dep, deg: x.deg_usd, ftp: x.ftp_usd },
      ftpUsd: x.ftp_usd, excusedUsd: x.excused_usd, ftpMw: r.ftp_mw ?? 0, excusedMw: r.excused_mw ?? 0,
      mode: batt > 0.5 ? "discharge" : batt < -0.5 ? "charge" : "idle", action: Math.sign(Math.round(batt)),
    };
  });
  hours.at(-1).cash -= ep.cash?.end_penalty || 0;
  const agentCum = cum(hours.map((x) => x.cash));
  const rt = task.rt.slice(0, H), da = task.prices.slice(0, H);
  const peakH = rt.indexOf(Math.max(...rt));
  const sorted = [...rt].sort((p, q) => p - q);

  const vint = vintagesOf(ep, tOf);
  const wx = weatherSeries(weather);
  const front = frontOf(wx);
  const elAt = (t) => sunAt(d1ms + t * 3600000, place.lat, place.lon).el;
  const frost = frostSeries(wx, elAt), snow = snowSeries(wx, elAt);
  const hub = hubWind(vint, task.weather_point, ep.vintages?.source);

  const d = {
    hybrid: true, live: true, forecast: true, lite, ep, task: { ...task, date: d1 }, site, b, E: Ebat, P, eta, L, Limp, era, dur, offered,
    prices: da, rt, place, region, weather, watches, notices, snaps, hours, agentCum, wins, peakH, median: sorted[Math.floor(H / 2)],
    firstNeg: hours.findIndex((x) => x.neg && x.pvAvail > 1), trunc: null, reward: ep.reward, capture: ep.r_hind, n, H, end: E, t0: OPEN,
    pvPeak: Math.max(...hours.map((x) => x.pvAvail)), pvMwac: lite ? 0 : site.pv_mwac, d1, dayName, tOf, vint, wx, front,
    lanes: (ep.race || []).map((l) => ({ ...l })),
    dateLabel: dayName(0),
    message: (ep.messages || []).filter((m) => m.role === "assistant").map((m) => m.content).join("\n\n"),
  };
  d.s0 = bess.s0_mwh;
  d.at = (t) => at(d, t);
  d.pre = (t) => preAt(d, t);
  d.watchAt = (t) => {
    let k = 0;
    for (const w of watches) if (w.t <= t + 1e-9) k = w.index;
    return watches[k];
  };
  d.dayOf = (t) => clamp(Math.floor(t / 24), 0, n - 1);
  d.frostAt = (t) => sample(frost, t);
  d.snowAt = (t) => sample(snow, t);
  d.cold = !!wx && Math.min(...wx.temp) < 1.5;
  d.hubAt = (t) => (hub ? sample(hub, t) : null);
  return d;
}

/** The forecast vintages per (kind, key), oldest first, each with its reveal hour and first valid window hour. */
function vintagesOf(ep, tOf) {
  const by = {};
  for (const v of ep.vintages?.series || []) {
    const k = `${v.kind}|${v.key}`;
    const rec = { ...v, rev: tOf(v.issued_at), h0: Math.round(tOf(v.start)) };
    (by[k] ||= []).push(rec);
  }
  for (const xs of Object.values(by)) xs.sort((a, b) => a.rev - b.rev);
  return {
    by, runs: ep.vintages?.runs || [], source: ep.vintages?.source || null,
    all: (kind, key) => by[`${kind}|${key}`] || [],
    latest(kind, key, t) {
      const xs = by[`${kind}|${key}`] || [];
      let best = null;
      for (const v of xs) if (v.rev <= t + 1e-9) best = v;
      return best;
    },
    upto(kind, key, t) {
      return (by[`${kind}|${key}`] || []).filter((v) => v.rev <= t + 1e-9);
    },
  };
}

/** Hub-height (80 m) wind at the weather point from HRRR as issued, the shortest lead per hour; none for synthetic
 * fixture slices, where the scene scales the airport's 10 m wind instead. */
function hubWind(vint, point, source) {
  if (!point || source === "synthetic") return null;
  const xs = vint.all("weather", point);
  if (!xs.length) return null;
  const v = [];
  for (let h = -16; h <= 76; h += 1) {
    let best = null;
    for (const r of xs) {
      const i = h - r.h0;
      if (r.rev <= h && i >= 0 && i < (r.fields.wind80_ms?.length ?? 0)) best = r.fields.wind80_ms[i];
    }
    v.push(best ?? (v.at(-1) ?? 0));
  }
  return { t0: -16, dt: 1, v };
}

/** Deployment MW at minute m of hour x. */
function depAt(x, m) {
  return sum(x.events.filter((w) => m >= w.from && m < w.to).map((w) => w.mw));
}

const offOf = (y) => (y.pvAvail > SOLAR_GAP ? clamp(y.curtailed / y.pvAvail, 0, 1) : 0);

/** What the scene shows at window hour t (0..H): as v3's day, hour by hour. */
export function at(d, t) {
  const tt = clamp(t, 0, d.H - 0.001);
  const h = Math.floor(tt), u = tt - h, x = d.hours[h], m = tt * 60;
  const depMins = sum(x.events.map((w) => (w.to - w.from) * w.mw));
  const done = depMins > 0 ? sum(x.events.map((w) => Math.max(0, Math.min(m, w.to) - w.from) * w.mw)) / depMins : 0;
  const depPart = -Math.min(x.depEvt, x.socBefore);
  const lin = x.socAfter - x.socBefore - depPart;
  const jig = (x.regUp + x.regDn) * 0.22 * Math.sin(Math.PI * u) * (Math.sin(tt * 37.1) * 0.6 + Math.sin(tt * 91.7 + 1.3) * 0.4);
  const soc = clamp(x.socBefore + lin * u + depPart * done + jig, 0, d.E);
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

/** Before the handover (t < 0): the plant idle at its starting charge, the panels on day 1's PV at the same clock hour. */
export function preAt(d, t) {
  const h = ((Math.floor(t) % 24) + 24) % 24, x = d.hours[h];
  return { ...x, t, u: 0, soc: d.s0, socLevels: d.b.s0, net: 0, mw: 0, exp: x.pvAvail, dep: 0, mode: "idle", bands: [], floor: 0, head: 0, upMw: 0, off: 0, pvUsed: x.pvAvail, pvShare: 1, stow: false, fromPv: 0, curtailed: 0 };
}

/** A lane's cash at t, interpolated inside the hour. */
export function laneAt(cumv, t, final, H) {
  if (t >= H) return final;
  if (t <= 0) return 0;
  const h = Math.min(H - 1, Math.floor(t)), u = t - h;
  const before = h > 0 ? cumv[h - 1] : 0;
  return before + (cumv[h] - before) * u;
}

/** "Sat 7 am", "Sun noon": a window hour or minute as the card says it. */
export function whenText(d, min, { day = true } = {}) {
  const mm = Math.round(min), k = Math.floor(mm / 1440), r = ((mm % 1440) + 1440) % 1440;
  const h = Math.floor(r / 60), m = r % 60;
  const hh = h === 0 && m === 0 ? "midnight" : h === 12 && m === 0 ? "noon" : `${h % 12 || 12}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h < 12 ? "am" : "pm"}`;
  if (!day) return hh;
  const x = new Date(Date.parse(`${d.d1}T12:00:00Z`) + k * DAY_MS);
  return `${DAY_NAMES[x.getUTCDay()]} ${hh}`;
}

/** An ERCOT bulletin in the viewer's own words: its level, what it is about (from keywords) and when it starts; NWS
 * products are already composed from structured fields (office, product, counties, until). */
export function paraphrase(x) {
  if (x.deploy || x.source !== "ERCOT") return x.text;
  const head = (x.text || "").split(" (")[0].replace(/\.$/, "");
  const body = ((x.text || "").match(/\((.*)\)/) || [])[1] || "";
  const themes = [
    [/cold|freez|winter|arctic/i, "extreme cold"], [/heat|hot\b|temperatures? (above|near) 10/i, "extreme heat"], [/demand|load/i, "high demand"],
    [/reserve|capacity|supply|tight/i, "tight reserves"], [/conserv/i, "a call to conserve"], [/transmission|outage/i, "transmission limits"],
    [/wind|solar|renewable/i, "low wind or solar"], [/emergency|EEA/i, "emergency operations"], [/gas|fuel|curtail/i, "fuel supply"],
  ].filter(([re]) => re.test(body)).map(([, w]) => w);
  const when = body.match(/(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)/);
  const tail = [themes.slice(0, 2).join(" and "), when ? `from ${when[1]}` : ""].filter(Boolean).join(", ");
  return tail ? `${head}: ${tail}.` : `${head}.`;
}
