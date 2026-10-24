/** An Episode JSON (gridsim.episode/v1) turned into what the scene and the cards show hour by hour. */
import { placeOf, REGIONS } from "./places.js";

export const P_FLOOR = 50;

/** The contract's physics, for the references' schedules (the agent's own path comes from the episode). */
export function simulate(task, actions) {
  const b = task.battery, p = task.prices;
  const q = b.unit_mwh, eta = b.eta, n = b.soc_levels;
  let s = b.s0, used = 0, trunc = null, viol = null;
  const executed = [], soc = [s], cash = [], mwh = [];
  actions.forEach((a0, h) => {
    let a = a0;
    if (trunc === null) {
      const v = !(a >= -b.k_ch && a <= b.k_dis) ? "rate" : s - a < 0 ? "soc_below_0" : s - a > n ? "soc_above_N" : used + Math.max(a, 0) > b.cycle_cap_units ? "cycle_cap" : null;
      if (v) (trunc = h), (viol = v);
    }
    if (trunc !== null) a = 0;
    s -= a;
    used += Math.max(a, 0);
    const g = a > 0 ? q * a : (q * a) / eta;
    executed.push(a);
    soc.push(s);
    mwh.push(g);
    cash.push(p[h] * g - b.c_deg * q * Math.max(a, 0));
  });
  const short = Math.max(0, b.s_end_min - s);
  const penalty = (short * q / eta) * Math.max(Math.max(...p), P_FLOOR);
  return { executed, soc, cash, mwh, truncated_at: trunc, violation: viol, end_shortfall_units: short, penalty, profit: cash.reduce((x, y) => x + y, 0) - penalty };
}

const cum = (xs) => xs.reduce((a, x) => (a.push((a.at(-1) ?? 0) + x), a), []);

export function grade(r) {
  return r >= 0.95 ? "S" : r >= 0.85 ? "A" : r >= 0.7 ? "B" : r >= 0.5 ? "C" : "D";
}

export function hourLabel(h) {
  const k = ((h % 24) + 24) % 24;
  return k === 0 ? "midnight" : k === 12 ? "noon" : k < 12 ? `${k} am` : `${k - 12} pm`;
}

export const money = (v, { sign = false, cents = false } = {}) => {
  const a = Math.abs(v);
  const s = a >= 1e6 ? `$${(a / 1e6).toFixed(2)}M` : a >= 1e4 ? `$${Math.round(a).toLocaleString("en-US")}` : `$${a.toLocaleString("en-US", { maximumFractionDigits: cents ? 2 : 0, minimumFractionDigits: cents ? 2 : 0 })}`;
  return (v < 0 ? "−" : sign ? "+" : "") + s;
};

export const price = (p) => `${p < 0 ? "−" : ""}$${Math.abs(p) >= 100 ? Math.round(Math.abs(p)).toLocaleString("en-US") : Math.abs(p).toFixed(2)}`;

const VIOLATIONS = {
  soc_below_0: "it would sell more than the battery holds",
  soc_above_N: "it would charge past full",
  rate: "it asks for more power than the inverters can carry",
  cycle_cap: "it would pass the day's cycle limit",
};

export function load(ep, weather = null) {
  const task = ep.task;
  const b = task.battery;
  const prices = task.prices;
  const place = placeOf(task.settlement_point);
  const region = REGIONS[task.region] || REGIONS.central;
  const hourly = ep.hourly?.length === 24 ? ep.hourly : null;
  const agentSim = simulate(task, ep.final_schedule || Array(24).fill(0));
  const actions = hourly ? hourly.map((x) => x.action) : agentSim.executed;
  const cash = hourly ? hourly.map((x) => x.cash) : agentSim.cash;
  const soc = ep.soc_path?.length === 25 ? ep.soc_path : agentSim.soc;
  const refs = ep.references || {};
  const ghosts = {};
  if (refs.opt) ghosts.opt = { label: "Optimum", sched: refs.opt, ...simulate(task, refs.opt) };
  for (const k of ["greedy", "threshold", "clock"]) if (refs[k]?.schedule) ghosts[k] = { label: k === "greedy" ? "Greedy" : k === "threshold" ? "Threshold" : "Clock", sched: refs[k].schedule, reward: refs[k].reward, ...simulate(task, refs[k].schedule) };
  for (const g of Object.values(ghosts)) g.cum = cum(g.cash);
  const agentCum = cum(cash);
  const pOpt = refs.p_opt ?? ghosts.opt?.profit ?? null;
  const pIdle = refs.p_idle ?? simulate(task, Array(24).fill(0)).profit;
  const trunc = ep.truncated_at ?? null;
  const penalty = ep.end_shortfall_units ? (ep.end_shortfall_units * b.unit_mwh / b.eta) * Math.max(Math.max(...prices), P_FLOOR) : 0;
  const reward = ep.reward ?? null;
  const spread = pOpt != null ? pOpt - pIdle : null;
  const captured = spread ? Math.max(0, (ep.profit_usd - pIdle) / spread) : null;
  const sorted = [...prices].sort((a, x) => a - x);
  const median = sorted[12];
  const peakH = prices.indexOf(Math.max(...prices));
  const hours = prices.map((p, h) => ({
    h, he: h + 1, price: p, action: actions[h], intended: ep.final_schedule?.[h] ?? actions[h], mw: actions[h] * b.unit_mwh,
    socBefore: soc[h], socAfter: soc[h + 1], cash: cash[h], cum: agentCum[h], opt: ghosts.opt?.executed[h] ?? null,
    optCum: ghosts.opt?.cum[h] ?? null, mismatch: ghosts.opt ? ghosts.opt.executed[h] !== actions[h] : false,
    neg: p < 0, mode: trunc !== null && h === trunc ? "violation" : trunc !== null && h > trunc ? "grey" : actions[h] > 0 ? "discharge" : actions[h] < 0 ? "charge" : "idle",
  }));
  const news = [];
  const firstNeg = prices.findIndex((p, h) => p < 0 && actions[h] < 0) >= 0 ? prices.findIndex((p, h) => p < 0 && actions[h] < 0) : prices.findIndex((p) => p < 0);
  if (firstNeg >= 0) {
    const negs = prices.filter((p) => p < 0).length;
    news.push({ t: firstNeg + 0.05, until: firstNeg + 2.5, kind: "neg", text: actions[firstNeg] < 0
      ? `Negative prices at ${hourLabel(firstNeg)}: the battery is paid ${price(-prices[firstNeg])}/MWh to charge`
      : `Prices go negative at ${hourLabel(firstNeg)} (${negs} hour${negs > 1 ? "s" : ""} today), and the plan ${actions[firstNeg] > 0 ? "sells into them" : "sits idle"}` });
  }
  if (prices[peakH] > Math.max(60, median * 1.8)) {
    news.push({ t: Math.max(0, peakH - 1.2), until: peakH + 1.5, kind: "peak", text: `${peakH >= 15 ? "Evening ramp" : peakH <= 9 ? "Morning ramp" : "Price spike"}: ${price(prices[peakH])}/MWh at ${hourLabel(peakH)}` + (actions[peakH] > 0 ? `, and the battery sells ${actions[peakH] * b.unit_mwh} MW into it` : actions[peakH] < 0 ? ", and the battery is buying" : ", and the battery holds back") });
  }
  if (trunc !== null) {
    news.push({ t: trunc + 0.05, until: trunc + 3, kind: "violation", text: `At ${hourLabel(trunc)} the plan breaks a rule (${VIOLATIONS[ep.violation] || ep.violation}): the rest of the day is cancelled` });
  }
  if (ep.end_shortfall_units > 0) news.push({ t: 23.2, until: 24.5, kind: "penalty", text: `The day ends ${ep.end_shortfall_units} unit${ep.end_shortfall_units > 1 ? "s" : ""} short of the required charge: a ${money(penalty)} penalty` });
  news.sort((a, x) => a.t - x.t);
  for (let i = 0; i + 1 < news.length; i++) news[i].until = Math.min(news[i].until, news[i + 1].t);
  const checks = (ep.steps || []).filter((s) => s.tool === "check_schedule").map((s) => ({ actions: s.args?.actions ?? s.args, out: s.output }));
  const date = new Date(`${task.date}T12:00:00`);
  return {
    ep, task, b, prices, place, region, weather, hours, ghosts, agentCum, soc, actions, pOpt, pIdle, reward, captured, trunc,
    penalty, news, checks, peakH, median, firstNeg, maxP: Math.max(...prices), minP: Math.min(...prices),
    grade: reward != null ? grade(reward) : null,
    dateLabel: date.toLocaleDateString("en-US", { weekday: "short", day: "numeric", month: "short", year: "numeric" }),
    message: (ep.messages || []).filter((m) => m.role === "assistant").map((m) => m.content).join("\n\n"),
  };
}

/** What the scene shows at t (hours since local midnight, 0..24). */
export function at(d, t) {
  const h = Math.max(0, Math.min(23, Math.floor(t)));
  const u = Math.max(0, Math.min(1, t - h));
  const x = d.hours[h];
  const ramp = u;
  const soc = x.socBefore + (x.socAfter - x.socBefore) * ramp;
  const before = h > 0 ? d.hours[h - 1].cum : 0;
  const cash = t >= 24 ? d.ep.profit_usd : before + x.cash * ramp;
  const optBefore = h > 0 ? d.hours[h - 1].optCum : 0;
  const optCash = d.ghosts.opt ? (t >= 24 ? d.pOpt : optBefore + d.ghosts.opt.cash[h] * ramp) : null;
  return { ...x, t, u, soc, cash, optCash, news: d.news.find((n) => t >= n.t && t < n.until) || null };
}
