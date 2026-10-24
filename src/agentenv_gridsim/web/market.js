/** A Market Floor day (gridsim.episode/v5) turned into what the room, the field and the cards show: the desk's calls by
 * watch, the offer as it stood, the day-ahead clear with every seat's award and the merit order of each hour, the
 * operating day of seat A's battery hour by hour, and what each other seat did with its real offers. */
import { minutesOf } from "./live.js";
import { absolute, placeOf, REGIONS } from "./places.js";

export const MARKET_SCHEMA = "gridsim.episode/v5";
export const DAM_CLOSE = -840, AWARDS = -630;
export const T0 = -6;
/** Replay hours: the operating day runs 0..24; the day before plays in -6..0, slower where the desk works. */
const KNOTS = [[-1080, -6], [-900, -5], [-840, -3.5], [-630, -2], [-480, -0.6], [0, 0]];
export const SEATS = ["A", "B", "G", "R", "L"];
export const SEAT = {
  A: { name: "bess-A", kind: "battery", what: "Battery portfolio", color: "#2c3440" },
  B: { name: "bess-B", kind: "battery", what: "Rival battery", color: "#5b7392" },
  G: { name: "gas-G", kind: "gas", what: "Gas peakers", color: "#a4573c" },
  R: { name: "renew-R", kind: "renewable", what: "Wind and solar", color: "#3f8656" },
  L: { name: "retail-L", kind: "retailer", what: "Retailer (city load)", color: "#8b6d9c" },
};
export const RULES = {
  grid: "MW off the seat's grid", power: "over the power rating", blocks: "too many blocks", price_range: "price outside the cap and floor",
  crossed: "a bid priced at or above an offer", parse: "not an offer", closed: "after the 10:00 close", frozen: "inside the freeze",
  soc_empty: "sells more than it holds", soc_full: "charges past full", end_target: "ends below the end target", cycle_cap: "past the cycle cap",
};

/** [1, 20, 21] as "HE1, 20–21". */
export function heList(hs) {
  const runs = [];
  for (const h of [...(hs || [])].sort((a, b) => a - b)) {
    const r = runs.at(-1);
    if (r && h === r[1] + 1) r[1] = h;
    else runs.push([h, h]);
  }
  return `HE${runs.map(([a, b]) => (a === b ? `${a}` : `${a}–${b}`)).join(", ")}`;
}
export function marketT(min) {
  if (min >= 0) return min / 60;
  if (min <= KNOTS[0][0]) return KNOTS[0][1];
  for (let i = 1; i < KNOTS.length; i++) {
    const [m0, t0] = KNOTS[i - 1], [m1, t1] = KNOTS[i];
    if (min <= m1) return t0 + ((min - m0) / (m1 - m0)) * (t1 - t0);
  }
  return 0;
}

export function marketMin(t) {
  if (t >= 0) return t * 60;
  if (t <= KNOTS[0][1]) return KNOTS[0][0];
  for (let i = 1; i < KNOTS.length; i++) {
    const [m0, t0] = KNOTS[i - 1], [m1, t1] = KNOTS[i];
    if (t <= t1) return m0 + ((t - t0) / (t1 - t0)) * (m1 - m0);
  }
  return 0;
}

const sum = (xs) => xs.reduce((a, x) => a + x, 0);
const cum = (xs) => xs.reduce((acc, x) => (acc.push((acc.at(-1) ?? 0) + x), acc), []);
const parse = (o) => (typeof o === "string" ? (() => { try { return JSON.parse(o); } catch { return null; } })() : o);

/** Per hour 1..24, sell and buy blocks [[mw, price]] of an offer JSON; omitted hours offer nothing. */
export function offerHours(offer) {
  const out = Array.from({ length: 24 }, () => ({ sell: [], buy: [] }));
  const o = parse(offer);
  const hours = Array.isArray(o) ? o : o?.hours;
  for (const x of hours || []) if (x?.he >= 1 && x.he <= 24) out[x.he - 1] = { sell: x.sell || [], buy: x.buy || [] };
  return out;
}

/** The SoC-feasible delivery of hourly awards from s0 (core's market_auction.project), for a battery seen from outside. */
function project(b, awards) {
  let s = b.s0;
  const soc = [s], ex = [];
  for (const a of awards) {
    const x = a > 0 ? Math.min(a, s, b.p) : a < 0 ? -Math.min(-a, (b.e - s) / b.eta, b.p) : 0;
    s = Math.min(b.e, Math.max(0, x > 0 ? s - x : s - b.eta * x));
    ex.push(x);
    soc.push(s);
  }
  return { ex, soc };
}

/** Piecewise-linear MW of a cumulative curve [[mw, price]] at price p (supply: MW offered at or below p). */
export function curveMw(pts, p, side) {
  if (!pts?.length) return 0;
  if (side === "supply") {
    if (p < pts[0][1]) return 0;
    for (let i = 1; i < pts.length; i++) if (p <= pts[i][1]) return pts[i - 1][0] + ((pts[i][0] - pts[i - 1][0]) * (p - pts[i - 1][1])) / Math.max(1e-9, pts[i][1] - pts[i - 1][1]);
    return pts.at(-1)[0];
  }
  if (p > pts[0][1]) return 0;
  for (let i = 1; i < pts.length; i++) if (p >= pts[i][1]) return pts[i - 1][0] + ((pts[i][0] - pts[i - 1][0]) * (pts[i - 1][1] - p)) / Math.max(1e-9, pts[i - 1][1] - pts[i][1]);
  return pts.at(-1)[0];
}

/** The merit order of hour h as the wall shows it: supply and demand MW at each price with and without seat A, A's
 * own blocks, the cleared price and ERCOT's real day-ahead price. */
export function meritOrder(d, h) {
  const st = d.ep.stack?.[h];
  if (!st) return null;
  const seats = st.seats || {};
  const repl = Object.entries(seats).filter(([s]) => s !== "A");
  const mit = d.clear.mitigated.some((m) => m.seat === "A" && m.he === h + 1), ref = d.task.seat_A.reference_usd[h];
  const a0 = seats.A || { sell: [], buy: [] };
  const a = { buy: a0.buy, sell: mit ? a0.sell.map(([m, p]) => [m, p > ref + Math.max(10, 0.5 * Math.abs(ref)) ? ref : p]) : a0.sell };
  const supply = (p, withA = true) => curveMw(st.background.supply, p, "supply") + sum(repl.map(([, c]) => curveMw(c.sell, p, "supply"))) + (withA ? sum(a.sell.filter(([, q]) => q <= p).map(([m]) => m)) : 0);
  const demand = (p, withA = true) => curveMw(st.background.demand, p, "demand") + sum(repl.map(([, c]) => curveMw(c.buy, p, "demand"))) + (withA ? sum(a.buy.filter(([, q]) => q >= p).map(([m]) => m)) : 0);
  const prices = [...new Set([...st.background.supply.map((x) => x[1]), ...st.background.demand.map((x) => x[1]), ...a.sell.map((x) => x[1]), ...a.buy.map((x) => x[1]), ...repl.flatMap(([, c]) => [...c.sell, ...c.buy].map((x) => x[1]))])].sort((x, y) => x - y);
  const lam = d.clear.lambda[h];
  const qAt = (p) => supply(p);
  let lo = -250, hi = 5000;
  for (let i = 0; i < 60; i++) {
    const m = (lo + hi) / 2;
    if (supply(m, false) - demand(m, false) >= 0) hi = m;
    else lo = m;
  }
  return { h, supply, demand, prices, lam, lamNoA: hi, lamReal: d.hubReal[h], q: qAt(lam), aSell: a.sell, aBuy: a.buy, mitigated: d.clear.mitigated.filter((m) => m.he === h + 1) };
}

export function loadMarket(ep, weather = null) {
  const task = ep.task, date = task.date, sa = task.seat_A;
  const P = sa.p_mw, E = sa.e_mwh, eta = sa.eta;
  const b = { p_dis_mw: P, p_ch_mw: P, energy_mwh: E, soc_levels: 8, s0: (sa.s0_mwh / E) * 8, s_end_min: (sa.s_end_min_mwh / E) * 8, eta, c_deg: sa.c_deg, unit_mwh: E / 8 };
  const place = placeOf(task.point);
  const region = absolute({ ...REGIONS[task.region] || REGIONS.central, turbines: { n: 46, km: [6.5, 11], bearing: [-122, -58], caprock: null } });
  const view = ep.seats_view || {};
  const watches = ep.watches.map((w) => {
    const min = minutesOf(w.time, date);
    return { ...w, min, t: marketT(min), steps: [] };
  });
  const steps = ep.steps.map((s) => ({ ...s, out: s.output || {} }));
  for (const s of steps) watches[Math.min(watches.length - 1, s.watch)]?.steps.push(s);
  for (const w of watches) {
    const span = Math.min(w.index + 1 < watches.length ? watches[w.index + 1].t - w.t : 0.8, w.min < DAM_CLOSE ? 0.9 : 0.6);
    w.steps.forEach((s, i) => (s.t = w.t + (span * (i + 0.6)) / (w.steps.length + 0.6)));
  }
  const offers = steps.filter((s) => s.tool === "submit_offer" && (s.out.accepted || s.out.submitted)).map((s) => ({ t: s.t, min: watches[s.watch].min, hours: offerHours(s.args?.offer) }));
  const refused = steps.filter((s) => s.tool === "submit_offer" && !s.out.accepted && !s.out.submitted);
  const contracts = [];
  for (const s of steps) {
    if ((s.tool === "propose_contract" || s.tool === "respond_contract") && s.out.contract_id) {
      const c = contracts.find((x) => x.id === s.out.contract_id) || contracts[contracts.push({ id: s.out.contract_id, t: s.t, min: watches[s.watch].min }) - 1];
      Object.assign(c, { status: s.out.status, hours: s.out.hours, mw: s.out.mw, strike: s.out.strike_usd, counter: s.out.counter_strike_usd, who: s.out.counterparty, t: s.t });
    }
  }
  const signed = (ep.rows?.contract?.contracts || []).reduce((m, r) => ((m[r.contract_id] = r), m), {});
  for (const c of contracts) c.row = signed[c.id] || null;
  const c = ep.clear;
  const clear = { lambda: c.lambda_usd, hub: c.hub_usd, real: c.lambda_real, replay: c.lambda_replay, mitigated: c.mitigated || [], curtailed: c.curtailed_mw };
  const hubReal = task.hub_dam_real;
  const rtH = Array.from({ length: 24 }, (_, h) => sum(task.hub_rt_real.slice(4 * h, 4 * h + 4)) / 4);
  const aw = ep.awards;
  const hours = ep.hours.map((x, h) => {
    const cash = x.dam_usd + x.rt_usd - x.deg_usd;
    const mode = x.exec_mw > 0.5 ? "discharge" : x.exec_mw < -0.5 ? "charge" : "idle";
    return { h, hub: x.hub, price: x.hub, neg: x.hub < 0, rt: x.rt, award: x.award_mw, exec: x.exec_mw, dev: x.dev_mw, socAfter: x.soc_mwh, dam: x.dam_usd, rtUsd: x.rt_usd, deg: x.deg_usd, mitigated: x.mitigated, clipped: x.clipped, cash, mode, action: Math.sign(Math.round(x.exec_mw)) };
  });
  hours.forEach((x, h) => (x.socBefore = h ? hours[h - 1].socAfter : sa.s0_mwh));
  const short = ep.pnl?.shortfall_usd || 0;
  if (short) hours[23].cash -= short;
  const agentCum = cum(hours.map((x) => x.cash));
  const bView = view.B || {};
  const bP = bView.p_mw || Math.max(1, ...aw.B.map(Math.abs)), bE = bView.e_mwh || bP * 2;
  const bat = { p: bP, e: bE, eta: bView.eta || 0.88, s0: bView.s0_mwh ?? bE / 2 };
  const bProj = aw.B ? project(bat, aw.B) : null;
  const gUnits = view.G?.units || null;
  const gMw = view.G?.mw || Math.max(1, ...aw.G.map(Math.abs));
  const rMw = view.R?.mw || Math.max(1, ...aw.R.map(Math.abs));
  const lMw = view.L?.mw || Math.max(1, ...aw.L.map(Math.abs));
  const seats = SEATS.filter((s) => s === "A" || ep.task.seats_public?.[s]).map((s) => {
    const r = s === "A" ? { profit_usd: ep.profit_usd, br_usd: ep.references?.p_br } : ep.seat_results?.[s] || {};
    const size = s === "A" ? P : s === "B" ? bP : s === "G" ? gMw : s === "R" ? rMw : lMw;
    return { s, ...SEAT[s], name: ep.task.seats_public?.[s]?.name || SEAT[s].name, size, profit: r.profit_usd, br: r.br_usd, regret: r.br_usd != null && r.profit_usd != null ? r.br_usd - r.profit_usd : null, perMw: r.profit_usd != null ? r.profit_usd / Math.max(1, size) : null, eps: r.eps };
  });
  const peakH = clear.hub.indexOf(Math.max(...clear.hub));
  const sorted = [...clear.hub].sort((x, y) => x - y);
  const g = ep;
  const d = {
    market: true, live: true, ep, task, b, P, E, eta, place, region, weather, watches, steps, offers, refused, contracts, clear, hubReal, rtH, hours, agentCum, aw, bat, bProj,
    gUnits, gMw, rMw, lMw, seats, peakH, median: sorted[12], s0: sa.s0_mwh, sEnd: sa.s_end_min_mwh, tier: ep.tier,
    reward: g.reward, compliant: g.compliant_reward, rows: g.rows || {}, refs: g.references || {}, pnl: g.pnl || {},
    trunc: null, firstNeg: clear.hub.findIndex((p) => p < 0), closeT: marketT(DAM_CLOSE), awardsT: marketT(AWARDS),
    dateLabel: new Date(`${date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
    message: (ep.messages || []).filter((m) => m.role === "assistant").map((m) => m.content).join("\n\n"),
  };
  const prev = new Date(`${date}T12:00:00`);
  prev.setDate(prev.getDate() - 1);
  d.prevLabel = prev.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short" });
  d.offerAt = (t) => offers.filter((o) => o.t <= t + 1e-9).at(-1) || null;
  d.finalOffer = offerHours(ep.offers?.A);
  d.watchAt = (t) => watches.filter((w) => w.t <= t + 1e-9).at(-1) || watches[0];
  d.at = (t) => at(d, t);
  d.merit = Array.from({ length: 24 }, (_, h) => null);
  d.meritAt = (h) => (d.merit[h] ??= meritOrder(d, h));
  return d;
}

const ease = (u) => u * u * (3 - 2 * u);

/** What the field shows at t: seat A's battery, the rival's, the peakers running, the wind and solar output, the
 * city's load, and the hour's prices; before the day every asset rests at its starting state. */
export function at(d, t) {
  const min = marketMin(t);
  const phase = min < DAM_CLOSE ? "pre_close" : min < AWARDS ? "clearing" : min < 0 ? "awards" : t < 24 ? "op_day" : "done";
  if (t < 0) {
    return { t, min, phase, h: null, u: 0, A: { mw: 0, soc: d.s0, mode: "idle" }, B: { mw: 0, soc: d.bat.s0, mode: "idle" }, G: { mw: 0, units: 0 }, R: { mw: 0 }, L: { mw: d.lMw * 0.6 }, hub: null, rt: null };
  }
  const tt = Math.min(23.999, t), h = Math.floor(tt), u = tt - h, x = d.hours[h];
  const soc = x.socBefore + (x.socAfter - x.socBefore) * Math.min(1, u / 0.98);
  const bx = d.bProj ? d.bProj.ex[h] : d.aw.B[h];
  const bSoc = d.bProj ? d.bProj.soc[h] + (d.bProj.soc[h + 1] - d.bProj.soc[h]) * u : d.bat.s0;
  const prevG = h ? d.aw.G[h - 1] : 0, g = prevG + (d.aw.G[h] - prevG) * ease(Math.min(1, u / 0.15));
  const unitMw = d.gUnits ? d.gMw / d.gUnits : 45;
  return {
    t, min, phase, h, u, hub: d.clear.hub[h], rt: d.rtH[h],
    A: { mw: x.exec, soc, mode: t >= 24 ? "idle" : x.mode, award: x.award },
    B: { mw: bx, soc: bSoc, mode: bx > 0.5 ? "discharge" : bx < -0.5 ? "charge" : "idle" },
    G: { mw: Math.max(0, g), units: Math.ceil(Math.max(0, d.aw.G[h]) / unitMw - 0.05) },
    R: { mw: Math.max(0, d.aw.R[h]) },
    L: { mw: Math.abs(d.aw.L[h]) },
  };
}
