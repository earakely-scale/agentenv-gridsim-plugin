/** The desk's charts on one time axis: the node's prices as they posted (DAM by hour, SCED every 5 minutes) with the
 * desk's forecast (modelled) where no price has posted, the battery's metered MW against its DAM award, its state of
 * charge and the settled statement. Every series is revealed only up to what had posted at the replay's minute, and
 * the price and dollar axes grow only with what has posted. */
import { clock, dayShort, esc, mw as mwText, price, usd, weekday } from "./fmt.js";

const NS = "http://www.w3.org/2000/svg";
const LEFT = 44, RIGHT = 10;
const STRIPS = [["p", 86], ["b", 44], ["s", 30], ["d", 36]];
const GAP = 8, AXIS = 17;
const TICKS = [-250, -100, -25, 0, 25, 50, 100, 250, 500, 1000, 2500, 5000];
const C = 25;
const f = (p) => Math.sign(p) * Math.log1p(Math.abs(p) / C);
const kusd = (v) => {
  const a = Math.abs(v), s = v < 0 ? "−" : "";
  return a >= 1e6 ? `${s}$${+(a / 1e6).toFixed(1)}M` : a >= 1e3 ? `${s}$${+(a / 1e3).toFixed(a >= 1e4 ? 0 : 1)}k` : `${s}$${Math.round(a)}`;
};
const nice = (x) => {
  const p = 10 ** Math.floor(Math.log10(Math.max(1, x))), m = x / p;
  return (m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10) * p;
};
const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export function buildCharts(M, host, { compare = false } = {}) {
  const T = M.T, E = M.E, n = M.n, t0 = M.t0, t1 = M.t1;
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", "The node's prices as posted, the battery's metered MW and DAM award, its state of charge and the settled statement, up to the replay's minute");
  host.replaceChildren(svg);
  const legend = document.createElement("div");
  legend.className = "legend";
  legend.innerHTML = `<span><i class="k dam"></i>Node DAM</span><span><i class="k sced"></i>SCED, 5-min</span><span><i class="k fc"></i>Desk forecast <small>modelled</small></span>${M.v5 ? '<span><i class="k real"></i>DAM without its offers</span>' : ""}`;
  host.prepend(legend);
  const tip = document.createElement("div");
  tip.className = "ctip";
  tip.hidden = true;
  host.append(tip);
  const st = { W: 0, x: null, y: {}, top: {}, pmax: null, pmin: null, dmax: null, dmin: null, fcKey: "", compare, hover: null };
  const H = STRIPS.reduce((a, [, h]) => a + h, 0) + GAP * (STRIPS.length - 1) + AXIS;
  const el = (tag, attrs = {}, parent = svg) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent.append(e);
    return e;
  };
  const sced = M.sced, s0 = M.s0;
  const smax = [], smin = [];
  sced.forEach((v, i) => (smax.push(Math.max(v, smax[i - 1] ?? -Infinity)), smin.push(Math.min(v, smin[i - 1] ?? Infinity))));
  const dmaxs = [], dmins = [];
  E.pnl.forEach((v, i) => (dmaxs.push(Math.max(v, dmaxs[i - 1] ?? 0)), dmins.push(Math.min(v, dmins[i - 1] ?? 0))));
  const ghost = T.ghost || {};
  const amax = [], amin = [];
  (ghost.anchor?.pnl || []).forEach((v, i) => (amax.push(Math.max(v, amax[i - 1] ?? 0)), amin.push(Math.min(v, amin[i - 1] ?? 0))));

  function layout() {
    const W = Math.max(240, Math.round(host.clientWidth));
    if (W === st.W) return false;
    st.W = W;
    svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
    svg.setAttribute("height", H);
    st.x = (t) => LEFT + ((t - t0) / (t1 - t0)) * (W - LEFT - RIGHT);
    let y = 0;
    for (const [k, h] of STRIPS) (st.top[k] = y), (st.y[k] = h), (y += h + GAP);
    return true;
  }

  function scaleP(t) {
    const c = M.scedCount(t);
    let hi = c ? smax[c - 1] : 30, lo = c ? smin[c - 1] : 0;
    for (let j = 0; j < n; j++) if (M.damPosted(j, t)) for (let h = 0; h < 24; h++) (hi = Math.max(hi, M.dam[24 * j + h])), (lo = Math.min(lo, M.dam[24 * j + h]));
    if (M.preDam) for (const v of M.preDam) (hi = Math.max(hi, v)), (lo = Math.min(lo, v));
    for (const v of fcShown(t)) for (const p of v.hi) hi = Math.max(hi, p);
    const top = TICKS.find((x) => x >= hi * 1.05) ?? 5000, bot = Math.min(0, [...TICKS].reverse().find((x) => x <= lo) ?? -250);
    return [bot, top];
  }

  function scaleD(t) {
    const c = M.sppCount(t);
    let hi = c ? dmaxs[c - 1] : 0, lo = c ? dmins[c - 1] : 0;
    if (st.compare && ghost.anchor && c) (hi = Math.max(hi, amax[c - 1])), (lo = Math.min(lo, amin[c - 1]));
    return [lo, Math.max(hi, lo + 1000)];
  }

  function fcShown(t) {
    const out = [];
    for (let j = 0; j < n; j++) {
      if (M.damPosted(j, t)) continue;
      const v = M.fcDamFor(j, t);
      if (v) out.push({ x0: 1440 * j, step: 60, mid: v.p50, lo: v.p10, hi: v.p90, at: v.at, key: `d${j}-${v.at}` });
    }
    const r = M.fcRtAt(t);
    if (r && t >= 0) {
      const from = Math.max(0, Math.ceil(t / 60) * 60);
      const i0 = Math.max(0, Math.round((from - r.start) / 60));
      const vals = r.p50.slice(i0);
      const posted = vals.length && M.damPosted(Math.floor(from / 1440), t);
      if (vals.length && posted) out.push({ x0: r.start + 60 * i0, step: 60, mid: vals, lo: null, hi: vals, at: r.at, key: `r${r.at}-${i0}` });
    }
    return out;
  }

  const yP = (p) => {
    const [a, b] = [f(st.pmin), f(st.pmax)], top = st.top.p, h = st.y.p;
    return top + h - ((clamp(f(p), a, b) - a) / (b - a)) * h;
  };
  const yB = (v) => st.top.b + st.y.b / 2 - (v / Math.max(T.site.hsl, -T.site.lsl)) * (st.y.b / 2 - 2);
  const yS = (v) => st.top.s + st.y.s - (v / T.site.emax) * (st.y.s - 2) - 1;
  const yD = (v) => st.top.d + st.y.d - ((v - st.dmin) / (st.dmax - st.dmin)) * st.y.d;

  const steps = (xs, x0, dt, y) => xs.map((v, i) => `${i ? "L" : "M"}${st.x(x0 + i * dt).toFixed(1)},${y(v).toFixed(1)}H${st.x(x0 + (i + 1) * dt).toFixed(1)}`).join("");
  const poly = (xs, x0, dt, y, off = 0) => xs.map((v, i) => `${i ? "L" : "M"}${st.x(x0 + (i + off) * dt).toFixed(1)},${y(v).toFixed(1)}`).join("");

  const g = {};
  function frame() {
    svg.replaceChildren();
    const defs = el("defs");
    for (const k of ["sced", "phys", "set"]) {
      const cp = el("clipPath", { id: `cl-${k}` }, defs);
      g[`clip-${k}`] = el("rect", { x: 0, y: 0, width: 0, height: H }, cp);
    }
    for (const [k] of STRIPS) {
      const cp = el("clipPath", { id: `band-${k}` }, defs);
      el("rect", { x: LEFT, y: st.top[k] - 1, width: st.W - LEFT - RIGHT + 1, height: st.y[k] + 2 }, cp);
    }
    const axis = el("g", { class: "ax" });
    for (let j = -1; j <= n; j++) {
      const m = 1440 * j;
      if (m > t0 && m < t1) el("line", { x1: st.x(m), x2: st.x(m), y1: 0, y2: H - AXIS + 2, class: "mid" }, axis);
      const a = Math.max(t0, m), b = Math.min(t1, m + 1440);
      if (b - a > 200) {
        const lab = el("text", { x: st.x((a + b) / 2), y: H - 6, class: "tk day", "text-anchor": "middle" }, axis);
        lab.textContent = j < 0 ? `${weekday(M.d0, m)}, day before` : (b - a) * (st.W - LEFT - RIGHT) / (t1 - t0) > 70 ? dayShort(M.d0, m) : weekday(M.d0, m);
      }
    }
    const labels = { p: "Price, $/MWh", b: "Battery, MW, and its DAM award (line)", s: "State of charge, MWh", d: "Settled statement, $" };
    g.labels = el("g", { class: "labs" });
    for (const [k, h] of STRIPS) {
      el("rect", { x: LEFT, y: st.top[k], width: st.W - LEFT - RIGHT, height: h, class: "band" }, axis);
      el("text", { x: LEFT + 5, y: st.top[k] + 11, class: "lab" }, g.labels).textContent = labels[k];
    }
    g.pAxis = el("g", { class: "ax" });
    g.bAxis = el("g", { class: "ax" });
    g.dAxis = el("g", { class: "ax" });
    for (const v of [T.site.hsl, 0, T.site.lsl]) {
      el("line", { x1: LEFT, x2: st.W - RIGHT, y1: yB(v), y2: yB(v), class: v ? "grid" : "zero" }, g.bAxis);
      el("text", { x: LEFT - 5, y: yB(v) + 3.5, class: "tk", "text-anchor": "end" }, g.bAxis).textContent = v ? `${v > 0 ? "+" : "−"}${Math.round(Math.abs(v))}` : "0";
    }
    for (const v of [T.site.emax, 0]) {
      el("line", { x1: LEFT, x2: st.W - RIGHT, y1: yS(v), y2: yS(v), class: v ? "grid" : "zero" }, g.bAxis);
      el("text", { x: LEFT - 5, y: yS(v) + 3.5, class: "tk", "text-anchor": "end" }, g.bAxis).textContent = `${Math.round(v)}`;
    }
    g.fc = el("g", { "clip-path": "url(#band-p)" });
    g.dam = el("g", { "clip-path": "url(#band-p)" });
    g.sced = el("g", { "clip-path": "url(#band-p)" });
    const physB = el("g", { "clip-path": "url(#band-b)" });
    g.mw = el("g", { "clip-path": "url(#cl-phys)" }, physB);
    g.award = el("g", {}, physB);
    const physS = el("g", { "clip-path": "url(#band-s)" });
    g.soc = el("g", { "clip-path": "url(#cl-phys)" }, physS);
    g.dol = el("g", { "clip-path": "url(#band-d)" });
    svg.append(g.labels);
    g.now = el("g", { class: "nowmark" });
    g.nowLine = el("line", { y1: 0, y2: H - AXIS + 2 }, g.now);
    g.hover = el("line", { y1: 0, y2: H - AXIS + 2, class: "hoverline", visibility: "hidden" });
    drawMw();
    drawSoc();
    st.pmax = st.pmin = st.dmax = st.dmin = null;
    st.fcKey = "";
    st.damKey = "";
  }

  function drawMw() {
    g.mw.replaceChildren();
    const up = E.m.map((v) => Math.max(0, v)), dn = E.m.map((v) => Math.min(0, v));
    const area = (xs, cls) => {
      const d = `M${st.x(0)},${yB(0)}` + xs.map((v, i) => `L${st.x(5 * i).toFixed(1)},${yB(v).toFixed(1)}L${st.x(5 * i + 5).toFixed(1)},${yB(v).toFixed(1)}`).join("") + `L${st.x(5 * xs.length)},${yB(0)}Z`;
      el("path", { d, class: cls }, g.mw);
    };
    area(up, "dis");
    area(dn, "chg");
  }

  function drawSoc() {
    g.soc.replaceChildren();
    if (st.compare && ghost.actual) el("path", { d: poly(ghost.actual.soc, 0, 5, yS, 1), class: "ghost op" }, g.soc);
    if (st.compare && ghost.anchor) el("path", { d: poly(ghost.anchor.soc, 0, 5, yS), class: "ghost anchor" }, g.soc);
    const d = poly(E.soc, 0, 5, yS);
    el("path", { d: `${d}L${st.x(5 * (E.soc.length - 1))},${yS(0)}L${st.x(0)},${yS(0)}Z`, class: "socarea" }, g.soc);
    el("path", { d, class: "socline" }, g.soc);
  }

  function drawPrices(t) {
    const [lo, hi] = scaleP(t);
    if (lo === st.pmin && hi === st.pmax) return false;
    st.pmin = lo;
    st.pmax = hi;
    g.pAxis.replaceChildren();
    const ticks = TICKS.filter((v) => v >= lo && v <= hi);
    const keep = ticks.length > 5 ? ticks.filter((v, i) => v === 0 || i % 2 === ticks.length % 2) : ticks;
    for (const v of keep) {
      el("line", { x1: LEFT, x2: st.W - RIGHT, y1: yP(v), y2: yP(v), class: v ? "grid" : "zero" }, g.pAxis);
      el("text", { x: LEFT - 5, y: yP(v) + 3.5, class: "tk", "text-anchor": "end" }, g.pAxis).textContent = v === 0 ? "$0" : `${v < 0 ? "−" : ""}$${Math.abs(v) >= 1000 ? `${Math.abs(v) / 1000}k` : Math.abs(v)}`;
    }
    g.sced.replaceChildren();
    el("path", { d: poly(sced, s0, 5, yP, 0.5), class: "sced", "clip-path": "url(#cl-sced)" }, g.sced);
    st.damKey = "";
    st.fcKey = "";
    return true;
  }

  function drawDam(t) {
    const key = Array.from({ length: n }, (_, j) => +M.damPosted(j, t)).join("") + st.pmax + st.pmin;
    if (key === st.damKey) return;
    st.damKey = key;
    g.dam.replaceChildren();
    if (M.preDam) el("path", { d: steps(M.preDam, -1440, 60, yP), class: "dam" }, g.dam);
    for (let j = 0; j < n; j++) {
      if (!M.damPosted(j, t)) continue;
      if (M.v5) el("path", { d: steps(M.real.slice(24 * j, 24 * j + 24), 1440 * j, 60, yP), class: "real" }, g.dam);
      el("path", { d: steps(M.dam.slice(24 * j, 24 * j + 24), 1440 * j, 60, yP), class: "dam" }, g.dam);
    }
    g.award.replaceChildren();
    for (let j = 0; j < n; j++) if (M.damPosted(j, t)) el("path", { d: steps(E.award.slice(24 * j, 24 * j + 24), 1440 * j, 60, yB), class: "award" }, g.award);
  }

  function drawFc(t) {
    const fs = fcShown(t), key = fs.map((v) => v.key).join("|") + st.pmax + st.pmin;
    if (key === st.fcKey) return;
    st.fcKey = key;
    g.fc.replaceChildren();
    for (const v of fs) {
      if (v.lo) {
        const top = v.hi.map((p, i) => `${i ? "L" : "M"}${st.x(v.x0 + i * v.step).toFixed(1)},${yP(p).toFixed(1)}H${st.x(v.x0 + (i + 1) * v.step).toFixed(1)}`).join("");
        const bot = [...v.lo].reverse().map((p, k) => {
          const i = v.lo.length - 1 - k;
          return `L${st.x(v.x0 + (i + 1) * v.step).toFixed(1)},${yP(p).toFixed(1)}H${st.x(v.x0 + i * v.step).toFixed(1)}`;
        }).join("");
        el("path", { d: `${top}${bot}Z`, class: "fcband" }, g.fc);
      }
      el("path", { d: steps(v.mid, v.x0, v.step, yP), class: "fc" }, g.fc);
    }
  }

  function drawDol(t) {
    const [lo, hi] = scaleD(t);
    if (st.dmax != null && lo >= st.dmin && hi <= st.dmax) return;
    const step = nice((hi - lo) / 2);
    st.dmin = Math.min(0, Math.floor(lo / step) * step);
    st.dmax = Math.max(step, Math.ceil(hi / step) * step);
    g.dAxis.replaceChildren();
    g.dol.replaceChildren();
    for (let v = st.dmin; v <= st.dmax + 1e-6; v += step) {
      el("line", { x1: LEFT, x2: st.W - RIGHT, y1: yD(v), y2: yD(v), class: v ? "grid" : "zero" }, g.dAxis);
      el("text", { x: LEFT - 5, y: yD(v) + 3.5, class: "tk", "text-anchor": "end" }, g.dAxis).textContent = kusd(v);
    }
    const set = el("g", { "clip-path": "url(#cl-set)" }, g.dol);
    if (st.compare && ghost.anchor) el("path", { d: `M${st.x(0)},${yD(0)}` + poly(ghost.anchor.pnl, 0, 15, yD, 1).replace(/^M/, "L"), class: "ghost anchor" }, set);
    el("path", { d: `M${st.x(0)},${yD(0)}` + poly(E.pnl, 0, 15, yD, 1).replace(/^M/, "L"), class: "dol" }, set);
  }

  function update(t) {
    const tt = clamp(t, t0, t1);
    if (layout()) frame();
    else if (tt === st.t) return false;
    const rescaled = drawPrices(tt);
    drawDam(tt);
    drawFc(tt);
    drawDol(tt);
    const c = M.scedCount(tt);
    g["clip-sced"].setAttribute("width", c ? st.x(s0 + 5 * c) : 0);
    g["clip-phys"].setAttribute("width", tt > 0 ? st.x(tt) : 0);
    const sc = M.sppCount(tt);
    g["clip-set"].setAttribute("width", sc ? st.x(15 * sc) + 0.5 : 0);
    g.nowLine.setAttribute("x1", st.x(tt));
    g.nowLine.setAttribute("x2", st.x(tt));
    st.t = tt;
    if (st.hover != null) hoverAt(st.hover);
    return rescaled;
  }

  function hoverAt(px) {
    const tt = t0 + ((px - LEFT) / (st.W - LEFT - RIGHT)) * (t1 - t0);
    if (tt < t0 || tt > t1) return hide();
    const now = st.t ?? t0;
    const rows = [];
    const h = Math.floor(tt / 60), j = Math.floor(tt / 1440);
    if (tt < 0 && M.preDam) rows.push(["Node DAM", price(M.preDam[24 + h])]);
    else if (tt >= 0 && M.damPosted(j, now)) rows.push(["Node DAM", `${price(M.dam[h])}${M.v5 ? `, without its offers ${price(M.real[h])}` : ""}`]);
    const k = Math.floor((tt - s0) / 5);
    if (k >= 0 && k < M.scedCount(now)) rows.push(["SCED, 5-min", price(sced[k])]);
    if (tt <= now && tt >= 0) {
      const b = M.battery(tt);
      rows.push(["Battery", b.mw > 1.5 ? `discharging ${mwText(b.mw)}` : b.mw < -1.5 ? `charging ${mwText(b.mw)}` : "idle"]);
      if (M.damPosted(j, now)) rows.push(["DAM award", `${E.award[h] > 0 ? "sold " : E.award[h] < 0 ? "bought " : ""}${mwText(E.award[h])}`]);
      rows.push(["State of charge", `${Math.round(b.soc)} MWh`]);
      const i = Math.floor(tt / 15);
      if (i < M.sppCount(now)) rows.push(["Settled", usd(E.pnl[i])]);
    } else if (tt > now) {
      const fcs = fcShown(now).filter((v) => tt >= v.x0 && tt < v.x0 + v.mid.length * v.step);
      if (fcs.length) rows.push(["Desk forecast", `${price(fcs[0].mid[Math.floor((tt - fcs[0].x0) / fcs[0].step)])}, modelled`]);
      else rows.push(["", "not posted yet"]);
    }
    tip.innerHTML = `<b>${esc(weekday(M.d0, tt))} ${clock(tt)}</b>${rows.map(([a, b]) => `<div><span>${esc(a)}</span><span>${esc(b)}</span></div>`).join("")}`;
    tip.hidden = false;
    const x = (px / st.W) * host.clientWidth;
    tip.style.left = `${Math.min(host.clientWidth - tip.offsetWidth - 4, Math.max(4, x + 12))}px`;
    g.hover.setAttribute("x1", px);
    g.hover.setAttribute("x2", px);
    g.hover.setAttribute("visibility", "visible");
  }

  function hide() {
    tip.hidden = true;
    g.hover?.setAttribute("visibility", "hidden");
  }

  svg.addEventListener("pointermove", (e) => {
    const r = svg.getBoundingClientRect();
    st.hover = ((e.clientX - r.left) / r.width) * st.W;
    hoverAt(st.hover);
  });
  svg.addEventListener("pointerleave", () => ((st.hover = null), hide()));
  return {
    update,
    setCompare(on) {
      st.compare = on;
      st.W = 0;
    },
  };
}
