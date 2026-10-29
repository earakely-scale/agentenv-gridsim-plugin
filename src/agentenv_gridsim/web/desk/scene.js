/** A desk episode turned into what the battery site's scene shows: the battery's metered MW and state of charge every
 * five minutes, its reserve awards and deployments, the co-located PV by the sun (modelled), the weather observed at
 * the region's airport and the front or ice it brings. Scene time is hours from the first operating day's midnight;
 * the episode opens at D-1 06:00 (t = -18), when the battery waits at its starting charge. */
import { absolute, REGIONS } from "gridsim/places.js";
import { sunAt, tzOffsetMinutes } from "gridsim/stage/astro.js";
import { frostSeries, frontOf, sample, snowSeries, weatherSeries } from "gridsim/stage/wx.js";

export const DURATION = { regup: 0.5, regdn: 0.5, rrspfr: 0.5, rrsffr: 0.25, ecrs: 1, nspin: 4 };
export const UP = ["regup", "rrspfr", "rrsffr", "ecrs", "nspin"];
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
const sum = (xs) => xs.reduce((a, x) => a + x, 0);
const mean = (xs) => (xs.length ? sum(xs) / xs.length : 0);

export function sceneOf(T, E) {
  const n = T.dates.length, H = 24 * n, s = T.site, Emax = s.emax, P = s.hsl, eta = Math.sqrt(s.rte);
  const pv = T.pv, lmp = T.prices.lmp, as = E.as || null;
  const award = (src, p, h) => as?.[src]?.[p]?.[h] ?? 0;
  const awardsAt = (h) => {
    const src = as?.rt && Object.keys(as.rt).length ? "rt" : "dam";
    const a = Object.fromEntries([...UP, "regdn"].map((p) => [p, Math.max(award(src, p, h), award("dam", p, h))]));
    a.rrs = a.rrspfr + a.rrsffr;
    return a;
  };
  const pvAt = (k) => (pv ? Math.max(0, pv[clamp(k, 0, pv.length - 1)]) : 0);
  const hours = Array.from({ length: H }, (_, h) => {
    const k0 = 12 * h, mw = mean(E.m.slice(k0, k0 + 12)), price = mean(lmp.slice(k0, k0 + 12));
    const avail = pv ? mean(pv.slice(k0, k0 + 12)) : 0, used = pv ? mean(pv.slice(k0, k0 + 12).map((x, i) => (lmp[k0 + i] < 0 ? 0 : x))) : 0;
    return {
      h, day: Math.floor(h / 24), batt: mw, mw, price, rt: price, neg: price < 0, action: Math.sign(Math.round(mw)),
      mode: mw > 1.5 ? "discharge" : mw < -1.5 ? "charge" : "idle", pvAvail: avail, pvUsed: used, curtailed: avail - used,
      export: mw + used, awards: awardsAt(h), socBefore: E.soc[k0], socAfter: E.soc[k0 + 12],
    };
  });
  const wins = T.alerts.filter((a) => a.kind === "deploy").map((a) => ({ product: a.sev, a: a.t, b: a.until }));
  const tz = tzOffsetMinutes(T.dates[0]);
  const d0ms = Date.parse(`${T.dates[0]}T00:00:00Z`) - tz * 60000;
  const elAt = (t) => sunAt(d0ms + t * 3600000, T.place.lat, T.place.lon).el;
  const wx = weatherSeries(T.weather, -20);
  const frost = frostSeries(wx, elAt), snow = snowSeries(wx, elAt);
  const sorted = hours.map((x) => x.price).sort((a, b) => a - b);
  const peakH = hours.reduce((a, x) => (x.price > hours[a].price ? x.h : a), 0);
  const L = pv ? s.pv.poi_mw : P;
  const d = {
    hybrid: true, live: true, forecast: true, lite: !pv, bands: !!as, fill: true,
    task: { settlement_point: s.id, date: T.dates[0] }, place: T.place, region: absolute(REGIONS[s.scene] || REGIONS.central),
    weather: T.weather, b: { p_dis_mw: P, p_ch_mw: -s.lsl, energy_mwh: Emax, soc_levels: 8, s0: (s.soc0 / Emax) * 8, s_end_min: (s.soc0 / Emax) * 8, eta, c_deg: 0, unit_mwh: Emax / 8 },
    site: pv ? { pv_mwac: s.pv.mw_ac, pv_mwdc: s.pv.mw_ac * 1.3, poi_mw: s.pv.poi_mw, poi_import_mw: s.pv.poi_mw, coupling: "ac", bess: { p_mw: P, e_mwh: Emax } } : null,
    E: Emax, P, L, Limp: L, n, H, end: H, t0: T.t0 / 60, hours, wins, peakH, median: sorted[Math.floor(H / 2)], trunc: null,
    firstNeg: hours.findIndex((x) => x.neg && x.pvAvail > 1), prices: hours.map((x) => x.price),
    watches: E.wakes.map(([t, why], index) => ({ index, t: t / 60, notices: why.filter((r) => ["notice", "nws", "outage", "deployment"].includes(r)) })),
    wx, front: frontOf(wx), cold: !!wx && Math.min(...wx.temp) < 1.5, frostAt: (t) => sample(frost, t), snowAt: (t) => sample(snow, t), hubAt: () => null,
    shotFill: (plant) => (plant ? ["establish", "solar", "high", "array", "establish", "high"] : ["establish", "high", "establish", "high", "line"]),
    shotNight: ["high", "establish", "high", "line"], eventShot: "high",
  };
  d.at = (t) => {
    const tt = clamp(t, 0, H - 1e-6), k = Math.floor(tt * 12), u = tt * 12 - k, h = Math.floor(tt);
    const mw = E.m[k], soc = E.soc[k] + (E.soc[k + 1] - E.soc[k]) * u;
    const avail = pvAt(k), neg = lmp[k] < 0, used = neg ? 0 : avail, a = hours[h].awards;
    const live = wins.filter((w) => tt * 60 >= w.a && tt * 60 < w.b && (a[w.product] || 0) > 0);
    const floor = sum(UP.map((p) => DURATION[p] * a[p])) / eta, head = DURATION.regdn * a.regdn * eta;
    const off = pv && avail > 0.5 ? (neg ? 1 : 0) : 0;
    return {
      t, h, k, mw, net: mw, soc, socLevels: (soc / Emax) * 8, mode: mw > 1.5 ? "discharge" : mw < -1.5 ? "charge" : "idle",
      exp: mw + used, pvAvail: avail, pvUsed: used, curtailed: avail - used, off, stow: off > 0.98, neg, price: lmp[k],
      awards: a, upMw: sum(UP.map((p) => a[p])), floor: Math.min(floor, Emax), head: Math.min(head, Emax),
      bands: live.map((w) => ({ k: w.product, live: true })), fromPv: mw < 0 ? Math.min(used, -mw) : 0,
    };
  };
  d.pre = (t) => {
    const k = clamp(Math.floor((((t % 24) + 24) % 24) * 12), 0, 287), avail = pvAt(k), used = lmp[k] < 0 ? 0 : avail;
    return {
      t, h: -1, k: -1, mw: 0, net: 0, soc: s.soc0, socLevels: (s.soc0 / Emax) * 8, mode: "idle", exp: used, pvAvail: avail, pvUsed: used,
      curtailed: avail - used, off: 0, stow: false, neg: false, awards: {}, upMw: 0, floor: 0, head: 0, bands: [], fromPv: 0,
    };
  };
  return d;
}
