/** The weather observed at the site's airport turned into quarter-hour series the scene reads: temperature, wind,
 * cover and codes, the cold front's passage, lying snow and frost on the panels. */
const sum = (xs) => xs.reduce((a, x) => a + x, 0);
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

/** A series sampled every dt hours from t0, read at t with linear interpolation. */
export function sample(s, t) {
  const x = (t - s.t0) / s.dt, i = clamp(Math.floor(x), 0, s.v.length - 2), u = clamp(x - i, 0, 1);
  return s.v[i] + (s.v[i + 1] - s.v[i]) * u;
}

/** The observed weather at the airport, every quarter hour (temperature in °C, wind, cover, codes). */
export function weatherSeries(side, t0 = -16) {
  const obs = (side?.obs || []).filter((o) => o.temp_c != null);
  if (obs.length < 4) return null;
  const dt = 0.25, N = Math.round((obs.at(-1).t - t0) / dt) + 2;
  const temp = [], wdir = [], wkt = [], cover = [], wx = [];
  let j = 0;
  for (let i = 0; i < N; i++) {
    const t = t0 + i * dt;
    while (j + 1 < obs.length && obs[j + 1].t <= t) j++;
    const a = obs[j], c = obs[Math.min(obs.length - 1, j + 1)];
    const u = c === a || t <= a.t ? 0 : clamp((t - a.t) / Math.max(0.05, c.t - a.t), 0, 1);
    temp.push(a.temp_c + (c.temp_c - a.temp_c) * u);
    wdir.push(u < 0.5 ? a.wind_dir : c.wind_dir);
    wkt.push((a.wind_kt || 0) + ((c.wind_kt || 0) - (a.wind_kt || 0)) * u);
    cover.push((a.cover || 0) + ((c.cover || 0) - (a.cover || 0)) * u);
    wx.push((u < 0.5 ? a : c).wx || []);
  }
  return { t0, dt, temp, wdir, wkt, cover, wx, obs };
}

/** The cold front: the steepest three-hour fall in temperature (at least 5 °C) after which the wind blows from the
 * northwest to northeast at 10 kt or more, having come from another quarter; its passage time, the bearing it comes
 * from and the fall. Evening cooling under light winds and storm outflow from the south do not count. */
export function frontOf(wx) {
  if (!wx) return null;
  const k = Math.round(3 / wx.dt);
  const north = (b) => b != null && b > 0 && (b >= 285 || b <= 60);
  let best = null;
  for (let i = k; i + 3 * k < wx.temp.length; i++) {
    const drop = wx.temp[i] - wx.temp[i + k];
    if (drop < 5 || (best && drop <= best.drop)) continue;
    const after = wx.wdir.slice(i + k, i + 3 * k), before = wx.wdir.slice(i - k, i);
    const nAfter = after.filter(north).length / after.length, nBefore = before.filter(north).length / before.length;
    const spd = sum(wx.wkt.slice(i + k, i + 3 * k)) / (2 * k);
    if (nAfter >= 0.6 && nBefore <= 0.5 && spd >= 10) best = { i, drop };
  }
  if (!best) return null;
  let steep = best.i, worst = 0;
  for (let i = best.i; i < best.i + k; i++) {
    const f = wx.temp[i] - wx.temp[i + 1];
    if (f > worst) (worst = f), (steep = i);
  }
  const after = wx.wdir.slice(best.i + k, best.i + 3 * k).filter((x) => x != null && x > 0);
  const bearing = after.length ? circMean(after) : 340;
  const t = wx.t0 + (steep + 0.5) * wx.dt;
  return { t, bearing, drop: best.drop, from: wx.temp[best.i], to: Math.min(...wx.temp.slice(best.i, best.i + 4 * k)), gustKt: Math.max(...wx.wkt.slice(steep, steep + k)) };
}

function circMean(xs) {
  const s = sum(xs.map((x) => Math.sin((x * Math.PI) / 180))), c = sum(xs.map((x) => Math.cos((x * Math.PI) / 180)));
  return ((Math.atan2(s, c) * 180) / Math.PI + 360) % 360;
}

/** Lying snow, 0..1: it builds while snow falls (light, moderate, heavy) and melts above freezing or in the sun. */
export function snowSeries(wx, elAt) {
  if (!wx) return { t0: -16, dt: 0.25, v: [0, 0] };
  const v = [0];
  for (let i = 1; i < wx.temp.length; i++) {
    const t = wx.t0 + i * wx.dt, T = wx.temp[i], el = elAt(t);
    const sn = wx.wx[i].filter((c) => /SN|PL|GS/.test(c) && !c.startsWith("VC"));
    const rate = sn.length ? Math.max(...sn.map((c) => (c.startsWith("+") ? 0.4 : c.startsWith("-") ? 0.07 : 0.2))) : 0;
    let s = v[i - 1] + wx.dt * rate * (T < 1.5 ? 1 : 0.3);
    if (T > 1) s -= wx.dt * 0.12 * (T - 1);
    if (el > 15 && T > -2) s -= wx.dt * 0.06 * Math.min(1, (el - 15) / 20) * (1 - wx.cover[i] * 0.7);
    v.push(clamp(s, 0, 1));
  }
  return { t0: wx.t0, dt: wx.dt, v };
}

/** Frost (or glaze) on the panels, 0..1: it builds through freezing nights and in freezing drizzle or snow, and melts
 * once the sun is up and the air is near or above freezing. */
export function frostSeries(wx, elAt) {
  if (!wx) return { t0: -16, dt: 0.25, v: [0, 0] };
  const v = [0];
  for (let i = 1; i < wx.temp.length; i++) {
    const t = wx.t0 + i * wx.dt, T = wx.temp[i], el = elAt(t);
    const codes = wx.wx[i].join(" ");
    const glaze = /FZ|SN|PL/.test(codes) && T <= 0.5;
    let f = v[i - 1];
    if (T <= 0.5 && (el < 10 || T < -4)) f += wx.dt * (glaze ? 0.7 : T < -3 ? 0.45 : 0.3) * (wx.cover[i] > 0.9 && !glaze ? 0.5 : 1);
    if (el > 8 && T > -3) f -= wx.dt * 0.55 * (1 + Math.max(0, T) / 3) * Math.min(1, (el - 8) / 20);
    if (T > 2.5) f -= wx.dt * (0.6 + 0.2 * T);
    v.push(clamp(f, 0, 1));
  }
  return { t0: wx.t0, dt: wx.dt, v };
}
