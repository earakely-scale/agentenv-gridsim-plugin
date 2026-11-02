/** The desk's chart on the window's time axis. Prices and forecasts are only what your own calls returned (the DAM by
 * hour, real-time and SCED prices, the desk forecast's P10-P90 and P50, the optimizer's planned dispatch); the battery's
 * metered output, its charge and the settled statement are the market's run so far. Nothing right of now is real. */
import { day, esc, hm, mw as mwText, price, weekday } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
const LEFT = 42, RIGHT = 8, GAP = 12, AXIS = 16;
const STRIPS = [["p", 120], ["b", 56], ["s", 34], ["d", 42]];
const LABELS = { p: "Price at your node, $/MWh", b: "Battery, MW", s: "Charge, MWh", d: "Settled, $" };
const TICKS = [-250, -100, -25, 0, 25, 50, 100, 250, 500, 1000, 2500, 5000];
const f = (p) => Math.sign(p) * Math.log1p(Math.abs(p) / 25);
const kusd = (v) => {
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  return a >= 1e6 ? `${s}$${+(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${s}$${+(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k` : `${s}$${Math.round(a)}`;
};
const nice = (x) => {
  const p = 10 ** Math.floor(Math.log10(Math.max(1, x))), m = x / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 2.5 ? 2.5 : m <= 5 ? 5 : 10) * p;
};

export function buildChart(host, ctx) {
  const { d0, t0, t1, site } = ctx;
  host.innerHTML = `<div class="legend"><span><i class="dam"></i>DAM</span><span><i class="rt"></i>Real time</span><span><i class="fc"></i>Desk forecast, P10–P90</span><span><i class="plan"></i>Optimizer's plan</span><span><i class="box dis"></i>Discharge</span><span><i class="box chg"></i>Charge</span></div><div class="charts"><svg role="img" aria-label="Prices from your calls, the battery's output and charge, and the settled statement, on the window's time axis"></svg><div class="ctip" hidden></div></div>`;
  const svg = host.querySelector("svg"), tip = host.querySelector(".ctip"), box = host.querySelector(".charts");
  const H = STRIPS.reduce((a, [, h]) => a + h, 0) + GAP * (STRIPS.length - 1) + AXIS;
  const st = { W: 0, top: {}, h: {}, data: null, hover: null };
  const el = (tag, attrs = {}, parent = svg) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent.append(e);
    return e;
  };
  const x = (t) => LEFT + ((t - t0) / (t1 - t0)) * (st.W - LEFT - RIGHT);
  const tOf = (px) => t0 + ((px - LEFT) / (st.W - LEFT - RIGHT)) * (t1 - t0);

  function draw() {
    const W = Math.max(260, Math.round(box.clientWidth));
    st.W = W;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("height", H);
    svg.replaceChildren();
    let y = 0;
    for (const [k, h] of STRIPS) (st.top[k] = y), (st.h[k] = h), (y += h + GAP);
    const D = st.data;
    if (!D) return;
    const now = D.now;
    const n = Math.round(t1 / 1440);
    for (const [k, h] of STRIPS) el("rect", { x: LEFT, y: st.top[k], width: W - LEFT - RIGHT, height: h, class: "band" });
    for (let j = 0; j <= n; j++) if (1440 * j > t0 && 1440 * j < t1) el("line", { x1: x(1440 * j), x2: x(1440 * j), y1: 0, y2: H - AXIS + 2, class: "mid" });
    for (let j = -1; j < n; j++) {
      const a = Math.max(t0, 1440 * j), b = Math.min(t1, 1440 * j + 1440);
      if (b - a < 200) continue;
      const wide = ((b - a) * (W - LEFT - RIGHT)) / (t1 - t0) > 64;
      el("text", { x: (x(a) + x(b)) / 2, y: H - 4, class: "tk day", "text-anchor": "middle" }).textContent = wide ? day(d0, a) : weekday(d0, a);
    }
    el("rect", { x: x(Math.max(t0, now)), y: 0, width: Math.max(0, x(t1) - x(Math.max(t0, now))), height: H - AXIS + 2, class: "future" });
    for (const [k] of STRIPS) el("text", { x: LEFT + 5, y: st.top[k] + 11, class: "lab" }).textContent = LABELS[k];

    const prices = [...Object.values(D.dam).flatMap((v) => v), ...D.series.flatMap((s) => s.values), ...D.fc.flatMap((v) => [...v.lo, ...v.hi])].filter((v) => v != null);
    const hi = Math.max(30, ...prices), lo = Math.min(0, ...prices);
    const ptop = TICKS.find((v) => v >= hi * 1.05) ?? 5000, pbot = Math.min(0, [...TICKS].reverse().find((v) => v <= lo) ?? -250);
    const yP = (p) => st.top.p + st.h.p - ((f(Math.max(pbot, Math.min(ptop, p))) - f(pbot)) / (f(ptop) - f(pbot))) * st.h.p;
    const ticks = TICKS.filter((v) => v >= pbot && v <= ptop);
    for (const v of ticks.length > 5 ? ticks.filter((v, i) => v === 0 || i % 2 === ticks.length % 2) : ticks) {
      el("line", { x1: LEFT, x2: W - RIGHT, y1: yP(v), y2: yP(v), class: v ? "grid" : "zero" });
      el("text", { x: LEFT - 5, y: yP(v) + 3.5, class: "tk", "text-anchor": "end" }).textContent = v === 0 ? "$0" : `${v < 0 ? "−" : ""}$${Math.abs(v) >= 1000 ? `${Math.abs(v) / 1000}k` : Math.abs(v)}`;
    }
    const steps = (vals, x0, dt, yf) => vals.map((v, i) => (v == null ? "" : `${i && vals[i - 1] != null ? "L" : "M"}${x(x0 + i * dt).toFixed(1)},${yf(v).toFixed(1)}H${x(x0 + (i + 1) * dt).toFixed(1)}`)).join("");
    const line = (vals, x0, dt, yf, off = 0.5) => vals.map((v, i) => (v == null ? "" : `${i && vals[i - 1] != null ? "L" : "M"}${x(x0 + (i + off) * dt).toFixed(1)},${yf(v).toFixed(1)}`)).join("");
    for (const v of D.fc) {
      const top = v.hi.map((p, i) => `${i ? "L" : "M"}${x(v.x0 + i * v.dt).toFixed(1)},${yP(p).toFixed(1)}H${x(v.x0 + (i + 1) * v.dt).toFixed(1)}`).join("");
      const bot = [...v.lo].reverse().map((p, k) => {
        const i = v.lo.length - 1 - k;
        return `L${x(v.x0 + (i + 1) * v.dt).toFixed(1)},${yP(p).toFixed(1)}H${x(v.x0 + i * v.dt).toFixed(1)}`;
      }).join("");
      el("path", { d: `${top}${bot}Z`, class: "fcband" });
      el("path", { d: steps(v.mid, v.x0, v.dt, yP), class: "fc" });
    }
    for (const s of D.series) el("path", { d: line(s.values, s.x0, s.dt, yP), class: "rt" });
    for (const [date, vals] of Object.entries(D.dam)) el("path", { d: steps(vals, 1440 * D.dayOf(date), 60, yP), class: "dam" });

    const P = Math.max(site.hsl, -site.lsl);
    const yB = (v) => st.top.b + st.h.b / 2 - (v / P) * (st.h.b / 2 - 2);
    for (const v of [site.hsl, 0, site.lsl]) {
      el("line", { x1: LEFT, x2: W - RIGHT, y1: yB(v), y2: yB(v), class: v ? "grid" : "zero" });
      el("text", { x: LEFT - 5, y: yB(v) + 3.5, class: "tk", "text-anchor": "end" }).textContent = v ? `${v > 0 ? "+" : "−"}${Math.round(Math.abs(v))}` : "0";
    }
    const area = (xs, cls) => {
      if (!xs.length) return;
      const d = `M${x(0)},${yB(0)}` + xs.map((v, i) => `L${x(5 * i).toFixed(1)},${yB(v).toFixed(1)}L${x(5 * i + 5).toFixed(1)},${yB(v).toFixed(1)}`).join("") + `L${x(5 * xs.length)},${yB(0)}Z`;
      el("path", { d, class: cls });
    };
    area(D.m.map((v) => Math.max(0, v)), "dis");
    area(D.m.map((v) => Math.min(0, v)), "chg");
    if (D.plan) el("path", { d: steps(D.plan.mw, D.plan.x0, 60, yB), class: "plan" });

    const yS = (v) => st.top.s + st.h.s - (v / site.emax) * (st.h.s - 2) - 1;
    for (const v of [site.emax, 0]) el("line", { x1: LEFT, x2: W - RIGHT, y1: yS(v), y2: yS(v), class: v ? "grid" : "zero" });
    el("text", { x: LEFT - 5, y: yS(site.emax) + 8, class: "tk", "text-anchor": "end" }).textContent = `${Math.round(site.emax)}`;
    const socs = D.now <= 0 ? [D.soc0, D.soc0] : D.soc;
    const sx0 = D.now <= 0 ? t0 : 0, sdt = D.now <= 0 ? Math.max(1, now - t0) : 5;
    const sd = socs.map((v, i) => `${i ? "L" : "M"}${x(sx0 + i * sdt).toFixed(1)},${yS(v).toFixed(1)}`).join("");
    el("path", { d: `${sd}L${x(sx0 + (socs.length - 1) * sdt)},${yS(0)}L${x(sx0)},${yS(0)}Z`, class: "socarea" });
    el("path", { d: sd, class: "socline" });

    const pn = [0, ...D.pnl, D.settled.total];
    const dlo = Math.min(0, ...pn), dhi = Math.max(1000, ...pn), step = nice((dhi - dlo) / 3);
    const dmin = Math.min(0, Math.floor(dlo / step) * step), dmax = Math.max(step, Math.ceil(dhi / step) * step);
    const yD = (v) => st.top.d + st.h.d - ((v - dmin) / (dmax - dmin)) * st.h.d;
    for (let v = dmin; v <= dmax + 1e-6; v += step) {
      el("line", { x1: LEFT, x2: W - RIGHT, y1: yD(v), y2: yD(v), class: v ? "grid" : "zero" });
      if (v === 0 || v === dmax || (v === dmin && dmax - step > 0)) el("text", { x: LEFT - 5, y: yD(v) + 3.5, class: "tk", "text-anchor": "end" }).textContent = kusd(v);
    }
    if (D.settled.upto > 0) {
      const pts = [[0, 0], ...D.pnl.map((v, i) => [60 * (i + 1), v]), [15 * D.settled.upto, D.settled.total]];
      el("path", { d: pts.map(([t, v], i) => `${i ? "L" : "M"}${x(t).toFixed(1)},${yD(v).toFixed(1)}`).join(""), class: "dol" });
    }
    const g = el("g", { class: "now" });
    el("line", { x1: x(now), x2: x(now), y1: 0, y2: H - AXIS + 2 }, g);
    const lab = el("text", { x: x(now) + (x(now) > W - 60 ? -4 : 4), y: st.top.b - 3, "text-anchor": x(now) > W - 60 ? "end" : "start" }, g);
    lab.textContent = `now ${hm(now)}`;
    st.hoverLine = el("line", { y1: 0, y2: H - AXIS + 2, class: "hoverline", visibility: "hidden" });
    if (st.hover != null) hoverAt(st.hover);
  }

  function hoverAt(px) {
    const D = st.data, t = tOf(px);
    if (!D || t < t0 || t > t1) return hide();
    const rows = [];
    const j = Math.floor(t / 1440), h = Math.floor(t / 60) - 24 * j;
    const date = D.dateOf(j);
    if (D.dam[date]) rows.push(["DAM", price(D.dam[date][h])]);
    for (const s of D.series) {
      const i = Math.floor((t - s.x0) / s.dt);
      if (i >= 0 && i < s.values.length) {
        rows.push([s.label, price(s.values[i])]);
        break;
      }
    }
    for (const v of D.fc) {
      const i = Math.floor((t - v.x0) / v.dt);
      if (i >= 0 && i < v.mid.length) {
        rows.push(["Desk forecast", `${price(v.mid[i])} (${price(v.lo[i])}–${price(v.hi[i])})`]);
        break;
      }
    }
    if (t <= D.now && t >= 0) {
      const k = Math.floor(t / 5), mwv = D.m[k] ?? 0;
      rows.push(["Battery", mwv > 1.5 ? `discharging ${mwText(mwv)}` : mwv < -1.5 ? `charging ${mwText(mwv)}` : "idle"]);
      rows.push(["Charge", `${Math.round(D.soc[k] ?? D.soc0)} MWh`]);
    } else if (t > D.now) rows.push(["", "not run yet"]);
    if (D.plan) {
      const i = Math.floor((t - D.plan.x0) / 60);
      if (i >= 0 && i < D.plan.mw.length) rows.push(["Optimizer's plan", `${D.plan.mw[i] > 0 ? "+" : ""}${Math.round(D.plan.mw[i])} MW`]);
    }
    tip.innerHTML = `<b>${esc(weekday(d0, t))} ${hm(t)}</b>${rows.map(([a, b]) => `<div><span>${esc(a)}</span><span>${esc(b)}</span></div>`).join("")}`;
    tip.hidden = false;
    const scale = box.clientWidth / st.W, left = px * scale;
    tip.style.left = `${Math.min(box.clientWidth - tip.offsetWidth - 2, Math.max(2, left + 12))}px`;
    st.hoverLine?.setAttribute("x1", px);
    st.hoverLine?.setAttribute("x2", px);
    st.hoverLine?.setAttribute("visibility", "visible");
  }

  function hide() {
    tip.hidden = true;
    st.hoverLine?.setAttribute("visibility", "hidden");
  }

  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    st.hover = ((e.clientX - r.left) / r.width) * st.W;
    hoverAt(st.hover);
  });
  svg.addEventListener("pointerleave", () => ((st.hover = null), hide()));
  new ResizeObserver(() => st.data && Math.round(box.clientWidth) !== st.W && draw()).observe(box);
  return {
    update(data) {
      st.data = data;
      draw();
    },
  };
}
