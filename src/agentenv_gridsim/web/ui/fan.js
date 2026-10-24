import { price } from "../data.js";
import { minuteOf, resultsMin, whenText } from "../forecast.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const W = 340, HT = 132, L = 38, R = 6, T = 8, B = 16;
const FC = "#3a4f66", ERCOT = "#2e7d5b", INK = "#1c2329";
const mwK = (v) => (Math.abs(v) >= 1000 ? `${(v / 1000).toFixed(Math.abs(v) >= 10000 ? 0 : 1)} GW` : `${Math.round(v)} MW`);

/** What each tab draws: the forecast kind and key, its P50 (and P10/P90) fields, ERCOT's own kind where the window
 * has it, and the realized series (only up to now). */
function kinds(d) {
  const pt = d.task.settlement_point, a = d.task.actuals || null;
  const eia = (field) => (a?.[field] ? { start: d.tOf(a.start), v: a[field] } : null);
  const out = [{ k: "price", label: "Price", kind: "price", key: pt, p50: "rt_p50", p10: "rt_p10", p90: "rt_p90", da: "da_p50", unit: "$/MWh", fmt: price, log: true }];
  if (d.vint.all("load", "system").length || d.vint.all("ercot_load", "system").length)
    out.push({ k: "load", label: "Load", kind: "load", key: "system", p50: "mw", ercot: ["ercot_load", "system", "mw"], official: true, real: eia("load_mw"), unit: "MW", fmt: mwK });
  if (!d.lite && (d.vint.all("solar", "site").length || d.vint.all("ercot_solar", "site").length))
    out.push({ k: "solar", label: "Site PV", kind: "solar", key: "site", p50: "mw", ercot: ["ercot_solar", "site", "mw"], pv: true, unit: "MW", fmt: mwK });
  if (d.vint.all("wind", "system").length || d.vint.all("ercot_wind", "system").length)
    out.push({ k: "wind", label: "Wind", kind: "wind", key: "system", p50: "mw", ercot: ["ercot_wind", "system", "stwpf_mw"], real: eia("wind_mw"), unit: "MW", fmt: mwK });
  if (d.vint.all("weather", d.task.weather_point).length && d.vint.source !== "synthetic")
    out.push({ k: "weather", label: "Temp", kind: "weather", key: d.task.weather_point, p50: "t2m_f", obs: true, unit: "°F", fmt: (v) => `${Math.round(v)}°` });
  return out;
}

/** The forecasts-as-issued card: per kind the latest vintage (P10–P90 for the price guide, the spread of runs for the
 * rest), older vintages fading, the realized line to now, ERCOT's own forecast beside the desk's where both exist, and a
 * scrubber over the watches that pins the card to what was on the desk, and what the agent read, at that watch. */
export function buildFan(d) {
  const ks = kinds(d);
  const root = document.createElement("section");
  root.className = "card fan";
  const ercotAny = ks.some((x) => x.ercot && d.vint.all(...x.ercot.slice(0, 2)).length);
  root.innerHTML = `<h5>Forecasts as issued <small>${d.vint.source === "synthetic" ? "synthetic CI vintages" : ercotAny ? "ERCOT's own and the desk's" : "desk models on NOAA HRRR"}</small></h5>
    <div class="tabs">${ks.map((x) => `<button data-k="${x.k}">${x.label}</button>`).join("")}</div>
    <svg class="fanchart" viewBox="0 0 ${W} ${HT}"></svg><div class="cap"></div>
    <div class="scrub"><input type="range" min="0" max="0" step="1" value="0" aria-label="Watch"><button class="live on" title="Follow the replay">Live</button></div><div class="sw"></div>`;
  const svg = root.querySelector("svg"), cap = root.querySelector(".cap"), sw = root.querySelector(".sw");
  const range = root.querySelector("input"), live = root.querySelector(".live");
  const q = new URLSearchParams(location.search);
  const S = { k: ks.find((x) => x.k === q.get("fan"))?.k || ks[0].k, pin: q.has("fanw") ? +q.get("fanw") : null, key: "" };
  root.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => {
    S.k = b.dataset.k;
    root.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x === b));
    S.key = "";
  }));
  range.addEventListener("input", () => ((S.pin = +range.value), (S.key = "")));
  root.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("on", x.dataset.k === S.k));
  live.addEventListener("click", () => ((S.pin = null), (S.key = "")));
  return {
    root,
    update(t, w) {
      const cur = t >= d.H ? d.watches.length - 1 : w.index;
      const vw = S.pin != null ? Math.min(S.pin, cur) : cur;
      const tv = S.pin != null ? d.watches[vw].t : t;
      const key = `${S.k}|${vw}|${S.pin != null}|${Math.floor(tv * 4)}|${cur}`;
      if (key === S.key) return;
      S.key = key;
      range.max = String(cur);
      range.value = String(vw);
      live.classList.toggle("on", S.pin == null);
      root.classList.toggle("pinned", S.pin != null);
      const spec = ks.find((x) => x.k === S.k);
      const r = draw(d, spec, tv, d.watches[vw]);
      svg.innerHTML = r.svg;
      cap.innerHTML = r.cap;
      const ww = d.watches[vw];
      const reads = ww.reads.map((s) => (s.tool === "get_forecast_drift" ? "drift" : s.args?.kind)).filter(Boolean);
      sw.innerHTML = `<b>${S.pin != null ? "Pinned to" : "At"} the ${esc(whenText(d, ww.min))} watch</b>${ww.gate != null ? " · DAM gate" : ww.kind === "event" ? " · event watch" : ""} · ${reads.length ? `it read ${esc([...new Set(reads)].join(", "))}` : d.ep.model?.startsWith("reference/") ? "the reference plans on these vintages directly" : "it read no forecasts"}`;
    },
  };
}

function draw(d, sp, tv, ww) {
  const H = d.H, X = (h) => L + ((W - L - R) * Math.max(0, Math.min(H, h))) / H;
  const vs = d.vint.upto(sp.kind, sp.key, tv);
  const last = vs.at(-1) || null;
  const ghosts = vs.slice(Math.max(0, vs.length - 7), -1);
  const ser = (v, field) => Array.from({ length: H }, (_, h) => v?.fields[field]?.[h - v.h0] ?? null);
  const p50 = ser(last, sp.p50);
  const band = sp.p10 ? [ser(last, sp.p10), ser(last, sp.p90)] : spread(vs, sp.p50, H);
  const er = sp.ercot ? d.vint.latest(sp.ercot[0], sp.ercot[1], tv) : null;
  const erS = er ? ser(er, sp.ercot[2]) : null;
  const now = Math.max(0, Math.min(H, Math.floor(tv + 1e-9)));
  let real = null;
  if (sp.k === "price") real = d.rt.map((v, h) => (h < now ? v : null));
  else if (sp.pv) real = d.hours.map((x, h) => (h < now ? x.pvAvail : null));
  else if (sp.obs && d.wx) real = Array.from({ length: H }, (_, h) => (h < now ? (sampleT(d.wx, h + 0.5) * 9) / 5 + 32 : null));
  else if (sp.real) real = Array.from({ length: H }, (_, h) => {
    const i = Math.round(h - sp.real.start);
    return h + 1 <= tv && i >= 0 && i < sp.real.v.length ? sp.real.v[i] : null;
  });
  const da = sp.da ? d.prices.map((v, h) => (tv >= resultsMin(Math.floor(h / 24)) / 60 + 0.5 ? v : null)) : null;
  const daF = sp.da ? ser(last, sp.da).map((v, h) => (da[h] == null ? v : null)) : null;
  const off = sp.official ? d.vint.upto("load_official", "system", tv) : [];
  const offS = Array(H).fill(null);
  for (const v of off) for (let i = 0; i < v.fields.mw.length; i++) if (v.h0 + i >= 0 && v.h0 + i < H) offS[v.h0 + i] = v.fields.mw[i];
  const reads = ww.reads.filter((s) => s.tool === "get_forecast" && (s.args?.kind || "") === sp.k && !s.output?.error);
  const drift = ww.reads.filter((s) => s.tool === "get_forecast_drift" && s.args?.kind === sp.k && s.output?.vintages);
  const readS = reads.map((s) => readSeries(d, sp, s.output)).filter(Boolean);
  const pool = [p50, band[0], band[1], erS, real, da, daF, offS, ...ghosts.map((g) => ser(g, sp.p50)), ...readS.map((x) => x.v)].flat().filter((v) => v != null && Number.isFinite(v));
  if (!pool.length) return { svg: `<text x="${W / 2}" y="${HT / 2}" text-anchor="middle" font-size="11" fill="#7a868e">No ${esc(sp.label.toLowerCase())} vintage yet</text>`, cap: "" };
  let lo = Math.min(...pool), hi = Math.max(...pool);
  if (sp.k !== "weather") lo = Math.min(0, lo);
  if (hi - lo < 1e-6) hi = lo + 1;
  const kk = 40, fl = (p) => (sp.log ? Math.sign(p) * Math.log1p(Math.abs(p) / kk) : p);
  const flo = fl(lo), fhi = fl(hi + (hi - lo) * 0.04);
  const Y = (v) => T + (HT - T - B) * (1 - (fl(v) - flo) / (fhi - flo || 1));
  const line = (vals, attrs) => {
    let s = "", seg = [];
    const flush = () => {
      if (seg.length > 1) s += `<polyline fill="none" ${attrs} points="${seg.join(" ")}"/>`;
      seg = [];
    };
    vals.forEach((v, h) => (v == null ? flush() : seg.push(`${X(h + 0.5).toFixed(1)},${Y(v).toFixed(1)}`)));
    flush();
    return s;
  };
  let s = "";
  for (let k = 24; k < H; k += 24) s += `<line x1="${X(k)}" x2="${X(k)}" y1="${T}" y2="${HT - B}" stroke="rgba(28,35,41,0.12)"/>`;
  const ticks = (sp.log ? [0, 50, 200, 1000, 5000].filter((v) => v >= lo && v <= hi) : [lo, (lo + hi) / 2, hi]).filter((v, i, xs) => !i || Math.abs(Y(v) - Y(xs[i - 1])) > 10);
  for (const v of ticks) s += `<line x1="${L}" x2="${W - R}" y1="${Y(v)}" y2="${Y(v)}" stroke="rgba(0,0,0,${v === 0 ? 0.22 : 0.06})"/><text x="${L - 4}" y="${Y(v) + 3.5}" class="ax" text-anchor="end">${esc(sp.fmt(v))}</text>`;
  for (let k = 0; k < d.n; k++) s += `<text x="${X(24 * k) + 3}" y="${HT - 4}" class="ax">${esc(d.dayName(k))}</text>`;
  const bp = [];
  for (let h = 0; h < H; h++) if (band[0][h] != null && band[1][h] != null) bp.push(h);
  if (bp.length) {
    const top = bp.map((h) => `${X(h + 0.5).toFixed(1)},${Y(band[1][h]).toFixed(1)}`), bot = bp.map((h) => `${X(h + 0.5).toFixed(1)},${Y(band[0][h]).toFixed(1)}`).reverse();
    s += `<polygon points="${top.concat(bot).join(" ")}" fill="rgba(58,79,102,0.15)"/>`;
  }
  ghosts.forEach((g, i) => (s += line(ser(g, sp.p50), `stroke="${FC}" stroke-opacity="${(0.1 + (0.4 * (i + 1)) / ghosts.length).toFixed(2)}" stroke-width="1"`)));
  if (daF) s += line(daF, `stroke="${FC}" stroke-width="1" stroke-dasharray="2 2"`);
  if (da) s += line(da, `stroke="${INK}" stroke-width="1.2" stroke-dasharray="4 2"`);
  if (offS.some((v) => v != null)) s += line(offS, `stroke="#b5487a" stroke-width="1.3" stroke-dasharray="5 2"`);
  if (erS) s += line(erS, `stroke="${ERCOT}" stroke-width="1.6"`);
  s += line(p50, `stroke="${FC}" stroke-width="1.8"`);
  for (const r of readS) {
    s += line(r.v, `stroke="${INK}" stroke-width="2.6" stroke-opacity="0.55" stroke-linecap="round"`);
    const h0 = r.v.findIndex((v) => v != null);
    if (h0 >= 0) s += `<circle cx="${X(h0 + 0.5)}" cy="${Y(r.v[h0])}" r="3" fill="#fff" stroke="${INK}" stroke-width="1.4"/>`;
  }
  if (real) s += line(real, `stroke="${INK}" stroke-width="1.7"`);
  for (const dr of drift) {
    const th = minuteOf(dr.output.target, d.d1) / 60;
    const vals = dr.output.vintages.map((v) => (sp.k === "price" ? v.value?.rt_p50 : v.value)).filter((v) => v != null);
    s += `<line x1="${X(th + 0.5)}" x2="${X(th + 0.5)}" y1="${T}" y2="${HT - B}" stroke="rgba(181,72,122,0.35)" stroke-dasharray="2 2"/>`;
    vals.forEach((v, i) => (s += `<circle cx="${X(th + 0.5)}" cy="${Y(v)}" r="2.3" fill="#b5487a" fill-opacity="${(0.25 + (0.75 * (i + 1)) / vals.length).toFixed(2)}"/>`));
  }
  const nx = X(tv < 0 ? 0 : tv);
  s += `<line x1="${nx}" x2="${nx}" y1="${T - 2}" y2="${HT - B}" stroke="${INK}" stroke-width="1.2"/>`;
  const capParts = [];
  if (last) capParts.push(`${esc(last.source && last.source !== "synthetic" ? srcName(sp, last) : sp.k === "price" ? "Desk price guide" : `Desk ${sp.label.toLowerCase()}`)}, issued ${esc(whenText(d, last.rev * 60))}${sp.p10 ? " · P10–P90 shaded" : vs.length > 1 ? " · spread of runs shaded" : ""}${ghosts.length ? ` · ${ghosts.length} older run${ghosts.length > 1 ? "s" : ""} fading` : ""}`);
  if (erS) capParts.push(`<span class="k er">ERCOT's own</span>, posted ${esc(whenText(d, er.rev * 60))}`);
  if (off.length) capParts.push(`<span class="k df">ERCOT day-ahead (EIA-930)</span>`);
  if (readS.length) capParts.push(`<span class="k rd">read</span> ${esc(readS.map((r) => `issued ${r.issued}`).join(", "))}`);
  if (drift.length) {
    const vals = drift[0].output.vintages.map((v) => (sp.k === "price" ? v.value?.rt_p50 : v.value)).filter((v) => v != null);
    if (vals.length) capParts.push(`<span class="k dr">drift</span> for ${esc(whenText(d, minuteOf(drift[0].output.target, d.d1)))}: ${esc(sp.fmt(vals[0]))} → ${esc(sp.fmt(vals.at(-1)))} over ${vals.length} runs`);
  }
  if (real && real.some((v) => v != null)) capParts.push(`<span class="k rl">${sp.k === "price" ? "real time" : sp.obs ? "observed" : "actual"}</span> to now`);
  else if (sp.real === null) capParts.push("no EIA actuals in this window");
  return { svg: s, cap: capParts.join(" · ") };
}

function srcName(sp, v) {
  const s = v.source || "";
  return /desk|HRRR|guide/i.test(s) ? s.replace(/\(synthetic\)/, "").trim() : sp.k === "price" ? "Desk price guide" : `Desk ${sp.label.toLowerCase()}`;
}

/** Per hour the lowest and highest P50 among the runs so far (only where two or more cover it). */
function spread(vs, field, H) {
  const lo = Array(H).fill(null), hi = Array(H).fill(null), n = Array(H).fill(0);
  for (const v of vs) {
    const xs = v.fields[field] || [];
    for (let i = 0; i < xs.length; i++) {
      const h = v.h0 + i;
      if (h < 0 || h >= H || xs[i] == null) continue;
      lo[h] = lo[h] == null ? xs[i] : Math.min(lo[h], xs[i]);
      hi[h] = hi[h] == null ? xs[i] : Math.max(hi[h], xs[i]);
      n[h]++;
    }
  }
  return [lo.map((v, h) => (n[h] > 1 ? v : null)), hi.map((v, h) => (n[h] > 1 ? v : null))];
}

/** A recorded get_forecast output as a series over window hours. */
function readSeries(d, sp, o) {
  if (!o?.from) return null;
  const h0 = minuteOf(o.from, d.d1) / 60;
  const xs = sp.k === "price" ? o.rt?.p50 : sp.k === "weather" ? o.t2m_f : o.mw;
  if (!Array.isArray(xs)) return null;
  const v = Array(d.H).fill(null);
  xs.forEach((x, i) => {
    const h = Math.round(h0 + i);
    if (h >= 0 && h < d.H) v[h] = x;
  });
  return { v, issued: whenText(d, minuteOf(o.issued_at, d.d1)) };
}

function sampleT(wx, t) {
  const x = (t - wx.t0) / wx.dt, i = Math.max(0, Math.min(wx.temp.length - 2, Math.floor(x))), u = Math.max(0, Math.min(1, x - i));
  return wx.temp[i] + (wx.temp[i + 1] - wx.temp[i]) * u;
}

