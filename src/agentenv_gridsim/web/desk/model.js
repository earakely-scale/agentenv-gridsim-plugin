/** One desk episode as the desk saw it at each minute: a 5-minute SCED price one minute after its interval, a
 * 15-minute RT price and that interval's settlement two minutes after, a day's DAM prices and awards once ERCOT
 * posts them, each desk-forecast vintage once issued. Nothing reads ahead of `t`. */
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export function modelOf(C, T, E) {
  const n = T.dates.length, t0 = T.t0, t1 = T.t1, P = T.prices;
  const pre = P.pre_lmp.length;
  const sced = [...P.pre_lmp, ...P.lmp], s0 = -5 * pre;
  const dam = E.dam, real = P.dam;
  const posted = P.dam_posted;
  const preDam = P.pre_dam.length === 24 ? P.pre_dam : null;
  const fcDam = T.fc.dam.map(([at, day, p10, p50, p90]) => ({ at, day, p10, p50, p90 }));
  const fcRt = T.fc.rt.map(([at, start, p50]) => ({ at, start, p50 }));
  const turns = E.turns.map((x, i) => ({ ...x, i }));
  const wakes = E.wakes.map(([t, why, turn], i) => ({ t, why, turn: turn == null ? null : turns[turn] ?? null, i }));
  const M = {
    C, T, E, n, t0, t1, d0: T.dates[0], sced, s0, dam, real, posted, preDam, turns, wakes, fcDam, fcRt,
    v5: T.version === "v5", pv: !!T.pv, as: !!E.as,
    scedCount: (t) => clamp(Math.floor((t - s0 - 1) / 5), 0, sced.length),
    sppCount: (t) => clamp(Math.floor((t - 2) / 15), 0, 96 * n),
    damPosted: (j, t) => j >= 0 && j < n && t >= posted[j],
    lastSced(t) {
      const c = M.scedCount(t);
      return c ? { p: sced[c - 1], at: s0 + 5 * c } : null;
    },
    damNow(t) {
      if (t < 0) return preDam ? { p: preDam[clamp(24 + Math.floor(t / 60), 0, 23)], h: 24 + Math.floor(t / 60), day: -1 } : null;
      const h = clamp(Math.floor(t / 60), 0, 24 * n - 1), j = Math.floor(h / 24);
      return M.damPosted(j, t) ? { p: dam[h], real: real[h], h: h % 24, day: j } : { pending: posted[j], day: j, h: h % 24 };
    },
    fcDamFor(j, t) {
      let best = null;
      for (const v of fcDam) if (v.day === j && v.at <= t) best = v;
      return best;
    },
    fcRtAt(t) {
      let best = null;
      for (const v of fcRt) if (v.at <= t) best = v;
      return best;
    },
    forecastNow(t) {
      if (t >= t1) return null;
      const v = M.fcRtAt(t), hm = Math.floor(Math.max(t, 0) / 60) * 60;
      if (v) {
        const i = Math.floor((hm - v.start) / 60);
        if (i >= 0 && i < v.p50.length) return { p: v.p50[i], at: v.at };
      }
      const j = clamp(Math.floor(Math.max(t, 0) / 1440), 0, n - 1), dv = M.fcDamFor(j, t);
      return dv ? { p: dv.p50[clamp(Math.floor(Math.max(t, 0) / 60) % 24, 0, 23)], at: dv.at } : null;
    },
    pnlAt(t) {
      const c = M.sppCount(t);
      return c ? E.pnl[c - 1] : 0;
    },
    battery(t) {
      if (t < 0) return { mw: 0, soc: T.site.soc0, pre: true };
      if (t >= t1) return { mw: 0, soc: E.soc.at(-1), end: true };
      const k = clamp(Math.floor(t / 5), 0, E.m.length - 1), u = (t - 5 * k) / 5;
      return { mw: E.m[k], soc: E.soc[k] + (E.soc[k + 1] - E.soc[k]) * u, k };
    },
    pvRaw(t) {
      if (!T.pv) return null;
      return T.pv[M.pvK(t)];
    },
    pvK: (t) => clamp(Math.floor((((t % 1440) + 1440) % 1440) / 5) + (t >= 0 ? 288 * clamp(Math.floor(t / 1440), 0, n - 1) : 0), 0, T.pv.length - 1),
    pvAt(t) {
      if (!T.pv) return null;
      const k = M.pvK(t);
      return P.lmp[k] < 0 ? 0 : T.pv[k];
    },
    awardsFor(j, t) {
      if (!M.damPosted(j, t)) return null;
      const hs = Array.from({ length: 24 }, (_, h) => E.award[24 * j + h] || 0);
      const as = E.as ? Object.fromEntries(Object.entries(E.as.dam).map(([p, v]) => [p, v.slice(24 * j, 24 * j + 24)]).filter(([, v]) => v.some((x) => x > 0))) : {};
      return { hs, as };
    },
    turnAt: (t) => turns.findLast((x) => x.t <= t) || null,
    alertsAt: (t) => T.alerts.filter((a) => a.issued <= t && t < a.until && a.kind !== "deploy" && a.kind !== "outage"),
    eventsAt: (t) => T.alerts.filter((a) => (a.kind === "deploy" || a.kind === "outage") && a.t <= t && t < a.until),
  };
  return M;
}
