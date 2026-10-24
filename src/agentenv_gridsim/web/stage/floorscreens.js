/** What the trading room's screens show, drawn on canvases: the video wall's market clock, the merit order of an hour
 * and the day's prices; seat A's desk monitors with its offer ladder and the hour's curve; generic desk screens. */
import { AWARDS, DAM_CLOSE, SEAT } from "../market.js";

const FONT = "Inter, 'Helvetica Neue', Arial, sans-serif";
const MONO = "'SF Mono', Menlo, Consolas, monospace";
export const SCREEN = { bg: "#0a1017", panel: "#0f1822", grid: "#1b2836", ink: "#dfe7ee", dim: "#7f93a6", faint: "#4c5f71", charge: "#2fd3ff", discharge: "#ffa62b", good: "#5fd08f", bad: "#ff6a5c", gold: "#f2c14e", ghost: "#9fb3c8" };
const C = SCREEN;

const hh = (min) => {
  const m = ((Math.floor(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
};
const hms = (s) => {
  const v = Math.max(0, Math.floor(s));
  return `${String(Math.floor(v / 3600)).padStart(2, "0")}:${String(Math.floor((v % 3600) / 60)).padStart(2, "0")}:${String(v % 60).padStart(2, "0")}`;
};
export const usd = (p) => `${p < 0 ? "−" : ""}$${Math.abs(p) >= 1000 ? Math.round(Math.abs(p)).toLocaleString("en-US") : Math.abs(p).toFixed(2)}`;
const mwTxt = (v) => `${Math.round(Math.abs(v)).toLocaleString("en-US")} MW`;
const heSpan = (h) => {
  const f = (k) => (k % 24 === 0 ? "12 am" : k === 12 ? "12 pm" : k < 12 ? `${k} am` : `${k - 12} pm`);
  return `${f(h)}–${f(h + 1)}`;
};

function header(g, w, title, right, accent = C.dim) {
  g.fillStyle = "#101b27";
  g.fillRect(0, 0, w, 54);
  g.fillStyle = accent;
  g.fillRect(0, 52, w, 2);
  g.fillStyle = C.ink;
  g.font = `700 26px ${FONT}`;
  g.textBaseline = "middle";
  g.textAlign = "left";
  g.fillText(title, 22, 28);
  g.fillStyle = C.dim;
  g.font = `500 21px ${FONT}`;
  g.textAlign = "right";
  g.fillText(right, w - 22, 28);
  g.textAlign = "left";
}

function chip(g, x, y, text, fill, ink = "#0a1017", size = 24) {
  g.font = `750 ${size}px ${FONT}`;
  const w = g.measureText(text).width + size * 1.1;
  g.fillStyle = fill;
  roundRect(g, x, y, w, size * 1.6, size * 0.4);
  g.fill();
  g.fillStyle = ink;
  g.textBaseline = "middle";
  g.fillText(text, x + size * 0.55, y + size * 0.82);
  return w;
}

function roundRect(g, x, y, w, h, r) {
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

/** The market clock (left of the wall): the CPT time, the market's state and the countdown to the next step. */
export function drawClock(g, w, h, d, s) {
  g.fillStyle = C.bg;
  g.fillRect(0, 0, w, h);
  const min = s.min;
  header(g, w, "ERCOT DAY-AHEAD MARKET", `Operating day ${d.dateLabel}`);
  const sec = (min - Math.floor(min)) * 60;
  g.fillStyle = C.ink;
  g.font = `300 140px ${FONT}`;
  g.textBaseline = "alphabetic";
  g.fillText(hh(min), 40, 250);
  const tw = g.measureText(hh(min)).width;
  g.font = `300 64px ${FONT}`;
  g.fillStyle = C.dim;
  g.fillText(`:${String(Math.floor(sec)).padStart(2, "0")}`, 48 + tw, 250);
  g.font = `600 28px ${FONT}`;
  g.fillText(`CPT · ${min < 0 ? d.prevLabel : d.dateLabel.replace(/, \d{4}$/, "")}`, 44, 296);
  let state, fill, line, count;
  if (min < DAM_CLOSE) [state, fill, line, count] = ["OPEN", C.good, "Offers due at 10:00", (DAM_CLOSE - min) * 60];
  else if (min < AWARDS) [state, fill, line, count] = ["CLOSED · CLEARING", C.gold, "Awards post at 13:30", (AWARDS - min) * 60];
  else if (min < 0) [state, fill, line, count] = ["AWARDS POSTED", "#7fb0ff", "Operating day starts at midnight", -min * 60];
  else if (min < 1440) [state, fill, line, count] = ["OPERATING DAY", C.ink, `Hour ending ${Math.floor(min / 60) + 1} · ${heSpan(Math.floor(min / 60))}`, null];
  else [state, fill, line, count] = ["DAY SETTLED", C.dim, "The operating day is over", null];
  chip(g, 40, 336, state, fill, "#0a1017", 30);
  g.fillStyle = C.ink;
  g.font = `500 30px ${FONT}`;
  g.fillText(line, 44, 448);
  if (count != null) {
    g.font = `700 92px ${MONO}`;
    g.fillStyle = min < DAM_CLOSE && count < 15 * 60 ? C.gold : C.ink;
    g.fillText(hms(count), 40, 560);
    g.font = `500 22px ${FONT}`;
    g.fillStyle = C.dim;
    g.fillText(min < DAM_CLOSE ? "until the DAM closes" : min < AWARDS ? "until the awards" : "until the operating day", 44, 596);
  } else if (s.h != null) {
    const p = d.clear.hub[s.h], rt = s.h < Math.floor(min / 60) ? d.rtH[s.h] : null;
    g.font = `700 80px ${FONT}`;
    g.fillStyle = p > 2 * d.median && p > 100 ? C.discharge : C.ink;
    g.fillText(`${usd(p)}`, 40, 560);
    g.font = `500 22px ${FONT}`;
    g.fillStyle = C.dim;
    g.fillText(`day-ahead hub price this hour${rt != null ? ` · real time ${usd(rt)}` : ""}`, 44, 596);
  }
  const steps = [[-1080, "6:00", "The desk opens: forecasts, the 60-day disclosure"], [-900, "9:00", "Seat A's offer, checks, contracts"], [DAM_CLOSE, "10:00", "DAM closes; offers frozen"], [AWARDS, "13:30", "Awards post; ERCOT's clear"], [0, "0:00", "Operating day: deliver the awards"], [1440, "24:00", "Settlement"]];
  const x0 = w * 0.56;
  g.fillStyle = C.grid;
  g.fillRect(x0 - 30, 80, 2, 530);
  g.font = `650 22px ${FONT}`;
  g.fillStyle = C.faint;
  g.fillText("THE MARKET DAY", x0, 104);
  steps.forEach(([m, hhmm, txt], i) => {
    const y = 160 + i * 82, done = min >= m, now = done && (i === steps.length - 1 || min < steps[i + 1][0]);
    g.fillStyle = now ? C.gold : done ? C.good : C.faint;
    g.beginPath();
    g.arc(x0 + 10, y - 8, 10, 0, Math.PI * 2);
    done ? g.fill() : (g.strokeStyle = C.faint, g.lineWidth = 2, g.stroke());
    g.font = `700 30px ${MONO}`;
    g.fillStyle = now ? C.ink : done ? C.dim : C.faint;
    g.fillText(hhmm, x0 + 34, y);
    g.font = `500 22px ${FONT}`;
    g.fillText(txt, x0 + 34, y + 30);
  });
  const wx = s.weather;
  g.fillStyle = C.faint;
  g.fillRect(40, 632, w - 80, 1.5);
  g.fillStyle = C.dim;
  g.font = `500 22px ${FONT}`;
  g.fillText(wx ? `Austin · ${wx}` : "Austin", 44, 672);
  g.textAlign = "right";
  g.fillText(`Seat A · ${d.P.toLocaleString("en-US")} MW / ${Math.round(d.E).toLocaleString("en-US")} MWh`, w - 40, 672);
  g.textAlign = "left";
}

/** The merit order of hour h around the clear: supply and demand (with A and, dashed, without it), A's blocks, the
 * cleared price, ERCOT's real day-ahead price and, if the monitor mitigated A, the stamp. */
export function drawMerit(g, w, h, d, s, hour, { reveal = 1 } = {}) {
  g.fillStyle = C.bg;
  g.fillRect(0, 0, w, h);
  const m = d.meritAt(hour);
  const cleared = s.min >= AWARDS;
  header(g, w, `MERIT ORDER · HE${hour + 1} · ${heSpan(hour)}`, cleared ? "re-cleared from the 60-day disclosure · hub $/MWh" : "the clear runs at 10:00 · results at 13:30", cleared ? C.gold : C.dim);
  if (!m) return;
  const lam = m.lam, q = m.q;
  const span = Math.max(4000, 4 * d.P);
  const x0 = q - span * 0.55, x1 = q + span * 0.45;
  const seen = [lam, m.lamReal, m.lamNoA, ...[...m.aSell, ...m.aBuy].map((x) => x[1]).filter((p) => p > -250 && p < 5000)];
  for (let i = 0; i <= 400; i++) {
    const p = -250 + 5250 * Math.pow(i / 400, 2.2);
    for (const f of [m.supply, m.demand]) if (f(p) > x0 && f(p) < x1) seen.push(p);
  }
  const pmin = Math.min(...seen), pmax = Math.max(...seen), pad = Math.max(8, (pmax - pmin) * 0.12);
  const top = Math.min(5000, pmax + pad), lo = Math.max(-250, Math.min(pmin - pad, lam - 20));
  const L = 96, R = w - 30, T = 92, B = h - 92;
  const X = (mw) => L + ((mw - x0) / (x1 - x0)) * (R - L), Y = (p) => B - ((Math.max(lo, Math.min(top, p)) - lo) / (top - lo)) * (B - T);
  g.strokeStyle = C.grid;
  g.lineWidth = 1;
  g.font = `500 18px ${FONT}`;
  g.fillStyle = C.faint;
  const rng = top - lo, step = rng > 2000 ? 500 : rng > 800 ? 200 : rng > 300 ? 50 : rng > 120 ? 25 : rng > 50 ? 10 : 5;
  for (let p = Math.ceil(lo / step) * step; p <= top; p += step) {
    g.beginPath();
    g.moveTo(L, Y(p));
    g.lineTo(R, Y(p));
    g.stroke();
    g.textAlign = "right";
    g.fillText(`$${p}`, L - 10, Y(p) + 6);
  }
  g.textAlign = "center";
  const gw = span > 6000 ? 2000 : 1000;
  for (let x = Math.ceil(x0 / gw) * gw; x <= x1; x += gw) g.fillText(`${(x / 1000).toFixed(0)} GW`, X(x), B + 28);
  g.textAlign = "left";
  const curve = (f, withA, color, width, dash = []) => {
    g.strokeStyle = color;
    g.lineWidth = width;
    g.setLineDash(dash);
    g.beginPath();
    let first = true;
    for (let i = 0; i <= 480 * reveal; i++) {
      const p = lo + ((top - lo) * i) / 480;
      const x = X(f(p, withA)), y = Y(p);
      if (x < L - 40 || x > R + 40) {
        first = true;
        continue;
      }
      first ? g.moveTo(x, y) : g.lineTo(x, y);
      first = false;
    }
    g.stroke();
    g.setLineDash([]);
  };
  const hasA = m.aSell.length || m.aBuy.length;
  if (hasA && cleared) {
    curve(m.supply, false, "rgba(159,179,200,0.45)", 2.5, [10, 8]);
    curve(m.demand, false, "rgba(159,179,200,0.45)", 2.5, [10, 8]);
  }
  curve(m.supply, true, "#c9d6e2", 4);
  curve(m.demand, true, "#8da2b7", 4);
  g.font = `600 20px ${FONT}`;
  const endLabel = (f, side, color, text) => {
    const xs = side > 0 ? x1 : x0;
    let pe = lo;
    for (let i = 0; i <= 480; i++) {
      const p = lo + ((top - lo) * i) / 480;
      if (side > 0 ? f(p) <= xs : f(p) >= xs) pe = p;
    }
    g.fillStyle = color;
    g.textAlign = side > 0 ? "right" : "left";
    g.fillText(text, side > 0 ? R - 8 : L + 8, Math.max(T + 22, Math.min(B - 30, Y(pe) + (side > 0 ? 30 : -14))));
    g.textAlign = "left";
  };
  endLabel(m.supply, 1, "#c9d6e2", "supply");
  endLabel(m.demand, -1, "#8da2b7", "demand");
  const own = (blocks, side) => {
    for (const [mw, p] of blocks) {
      const y = Y(p), xq = X(side > 0 ? m.supply(p) : m.demand(p));
      g.fillStyle = side > 0 ? C.discharge : C.charge;
      g.globalAlpha = 0.9;
      g.fillRect(side > 0 ? xq - (X(mw) - X(0)) : xq, y - 5, X(mw) - X(0), 10);
      g.globalAlpha = 1;
    }
  };
  own(m.aSell.filter(([, p]) => p > lo && p < top), 1);
  own(m.aBuy.filter(([, p]) => p > lo && p < top), -1);
  const ss = m.aSell.filter(([, p]) => p <= lo).reduce((a, x) => a + x[0], 0) - m.aBuy.filter(([, p]) => p >= top).reduce((a, x) => a + x[0], 0);
  if (Math.abs(ss) > 0.5) {
    g.fillStyle = ss > 0 ? C.discharge : C.charge;
    g.globalAlpha = 0.85;
    g.fillRect(X(q) - Math.abs(X(ss) - X(0)), B - 14, Math.abs(X(ss) - X(0)), 14);
    g.globalAlpha = 1;
    g.font = `600 18px ${FONT}`;
    g.fillText(`seat A ${ss > 0 ? "sells" : "buys"} ${mwTxt(ss)} at any price`, Math.max(L + 4, X(q) - Math.abs(X(ss) - X(0))), B - 22);
  }
  if (cleared && reveal >= 1) {
    g.strokeStyle = C.gold;
    g.lineWidth = 3;
    g.beginPath();
    g.moveTo(L, Y(lam));
    g.lineTo(R, Y(lam));
    g.stroke();
    g.fillStyle = C.gold;
    g.beginPath();
    g.arc(X(q), Y(lam), 9, 0, Math.PI * 2);
    g.fill();
    g.strokeStyle = "rgba(255,255,255,0.55)";
    g.setLineDash([6, 6]);
    g.lineWidth = 2;
    g.beginPath();
    g.moveTo(L, Y(m.lamReal));
    g.lineTo(R, Y(m.lamReal));
    g.stroke();
    g.setLineDash([]);
    g.font = `700 30px ${FONT}`;
    g.fillStyle = C.gold;
    const lx = Math.min(R - 260, X(q) + 24);
    g.fillText(`clears ${usd(lam)}`, lx, Y(lam) + (Y(lam) > T + 60 ? -18 : 40));
    const legend = [["rgba(255,255,255,0.8)", [7, 6], `ERCOT's real day-ahead ${usd(m.lamReal)}`]];
    if (hasA) legend.push([C.ghost, [10, 8], `without seat A ${usd(m.lamNoA)}`]);
    g.fillStyle = "rgba(10,16,23,0.82)";
    g.fillRect(L + 8, T + 4, 360, 18 + legend.length * 30);
    legend.forEach(([c, dash, txt], i) => {
      g.strokeStyle = c;
      g.setLineDash(dash);
      g.lineWidth = 2.5;
      g.beginPath();
      g.moveTo(L + 20, T + 26 + i * 30);
      g.lineTo(L + 62, T + 26 + i * 30);
      g.stroke();
      g.setLineDash([]);
      g.fillStyle = c;
      g.font = `500 20px ${FONT}`;
      g.fillText(txt, L + 72, T + 33 + i * 30);
    });
  }
  const aw = d.aw.A[hour];
  g.font = `600 22px ${FONT}`;
  g.fillStyle = C.ink;
  const lab = !hasA ? "Seat A offers nothing this hour" : !cleared ? `Seat A offers ${m.aSell.length ? `${mwTxt(m.aSell.reduce((a, x) => a + x[0], 0))} to sell` : ""}${m.aSell.length && m.aBuy.length ? " and " : ""}${m.aBuy.length ? `${mwTxt(m.aBuy.reduce((a, x) => a + x[0], 0))} to buy` : ""}` :
    Math.abs(aw) < 0.5 ? "Seat A: no award this hour" : `Seat A awarded ${aw > 0 ? "a sale of" : "a purchase of"} ${mwTxt(aw)}`;
  g.fillText(lab, L, h - 34);
  g.fillStyle = C.dim;
  g.font = `500 18px ${FONT}`;
  g.textAlign = "right";
  g.fillText("anonymised portfolios · copper plate", R, h - 34);
  g.textAlign = "left";
  if (cleared && m.mitigated.some((x) => x.seat === "A")) stamp(g, w * 0.7, h * 0.36, "MITIGATED", `seat A re-priced to its $${Math.round(d.task.seat_A.reference_usd[hour])} reference`);
}

function stamp(g, x, y, big, small) {
  g.save();
  g.translate(x, y);
  g.rotate(-0.12);
  g.strokeStyle = C.bad;
  g.fillStyle = "rgba(255,106,92,0.12)";
  g.lineWidth = 6;
  roundRect(g, -190, -58, 380, 116, 14);
  g.fill();
  g.stroke();
  g.fillStyle = C.bad;
  g.font = `800 52px ${FONT}`;
  g.textAlign = "center";
  g.fillText(big, 0, 8);
  g.font = `600 18px ${FONT}`;
  g.fillText(small, 0, 42);
  g.restore();
}

/** The day's prices: cleared hub price by hour against ERCOT's real day-ahead (dashed), seat A's awards below the axis
 * and, on the operating day, real time for the settled hours. Before the awards, seat A's offer by hour. */
export function drawPrices(g, w, h, d, s) {
  g.fillStyle = C.bg;
  g.fillRect(0, 0, w, h);
  const cleared = s.min >= AWARDS;
  const off = d.offerAt(s.t);
  header(g, w, cleared ? "DAY-AHEAD PRICES AND AWARDS" : "SEAT A · OFFER BY HOUR", cleared ? "hub $/MWh · seat A MW" : off ? `submitted ${hh(off.min)}` : "not submitted yet");
  const L = 70, R = w - 24, T = 84, B = h - 70, mid = cleared ? T + (B - T) * 0.62 : (T + B) / 2;
  const bw = (R - L) / 24;
  g.font = `500 17px ${FONT}`;
  g.fillStyle = C.faint;
  g.textAlign = "center";
  for (let k = 0; k < 24; k += 3) g.fillText(k === 0 ? "12a" : k === 12 ? "12p" : k < 12 ? `${k}a` : `${k - 12}p`, L + k * bw + bw / 2, h - 34);
  g.textAlign = "left";
  const now = s.h;
  if (!cleared) {
    const mx = Math.max(1, d.P);
    g.strokeStyle = C.grid;
    g.beginPath();
    g.moveTo(L, mid);
    g.lineTo(R, mid);
    g.stroke();
    if (!off) {
      g.fillStyle = C.dim;
      g.font = `500 30px ${FONT}`;
      g.textAlign = "center";
      g.fillText("The desk is building its offer", (L + R) / 2, mid - 20);
      g.font = `500 22px ${FONT}`;
      g.fillText("sells above the line, buys below, by hour", (L + R) / 2, mid + 24);
      g.textAlign = "left";
      return;
    }
    off.hours.forEach((x, k) => {
      const sell = x.sell.reduce((a, b) => a + b[0], 0), buy = x.buy.reduce((a, b) => a + b[0], 0);
      const ys = ((B - T) / 2 - 8) / mx;
      g.fillStyle = C.discharge;
      if (sell) g.fillRect(L + k * bw + 4, mid - sell * ys, bw - 8, sell * ys);
      g.fillStyle = C.charge;
      if (buy) g.fillRect(L + k * bw + 4, mid, bw - 8, buy * ys);
    });
    g.fillStyle = C.dim;
    g.font = `500 18px ${FONT}`;
    g.fillText(`sell ↑  ${mwTxt(d.P)}`, L + 6, T + 22);
    g.fillText(`buy ↓  ${mwTxt(d.P)}`, L + 6, B - 8);
    return;
  }
  const top = Math.max(50, ...d.clear.hub, ...d.hubReal) * 1.08;
  const lo = Math.min(0, ...d.clear.hub, ...d.hubReal);
  const Y = (p) => mid - 12 - ((p - lo) / (top - lo)) * (mid - 12 - T);
  g.strokeStyle = C.grid;
  for (const p of [0, top / 2, top * 0.92]) {
    g.beginPath();
    g.moveTo(L, Y(p));
    g.lineTo(R, Y(p));
    g.stroke();
    g.fillStyle = C.faint;
    g.textAlign = "right";
    g.fillText(`$${Math.round(p)}`, L - 8, Y(p) + 6);
    g.textAlign = "left";
  }
  d.clear.hub.forEach((p, k) => {
    g.fillStyle = k === now ? C.gold : "#5d7287";
    g.fillRect(L + k * bw + 5, Y(Math.max(0, p)), bw - 10, Y(Math.min(0, p)) - Y(Math.max(0, p)) + 1);
  });
  g.strokeStyle = "rgba(255,255,255,0.8)";
  g.setLineDash([7, 6]);
  g.lineWidth = 2.5;
  g.beginPath();
  d.hubReal.forEach((p, k) => (k ? g.lineTo(L + k * bw + bw / 2, Y(p)) : g.moveTo(L + k * bw + bw / 2, Y(p))));
  g.stroke();
  g.setLineDash([]);
  if (now != null) {
    for (let k = 0; k < Math.min(24, Math.floor(s.min / 60)); k++) {
      g.fillStyle = C.ink;
      g.beginPath();
      g.arc(L + k * bw + bw / 2, Y(Math.max(lo, Math.min(top, d.rtH[k]))), 5, 0, Math.PI * 2);
      g.fill();
    }
  }
  const mx = Math.max(1, d.P), ys = (B - mid - 14) / mx;
  g.strokeStyle = C.grid;
  g.beginPath();
  g.moveTo(L, mid + 6);
  g.lineTo(R, mid + 6);
  g.stroke();
  d.aw.A.forEach((a, k) => {
    if (Math.abs(a) < 0.5) return;
    g.fillStyle = a > 0 ? C.discharge : C.charge;
    const hgt = Math.abs(a) * ys;
    g.fillRect(L + k * bw + 5, mid + 8, bw - 10, hgt);
  });
  for (const x of d.clear.mitigated.filter((x) => x.seat === "A")) {
    g.strokeStyle = C.bad;
    g.lineWidth = 3;
    g.strokeRect(L + (x.he - 1) * bw + 2, T, bw - 4, B - T);
  }
  g.font = `500 18px ${FONT}`;
  g.fillStyle = C.dim;
  g.fillText("cleared hub price", L + 6, T + 20);
  g.fillStyle = "rgba(255,255,255,0.8)";
  g.fillText("- - ERCOT's real day-ahead", L + 190, T + 20);
  g.fillStyle = C.dim;
  g.fillText("seat A's awards: sells amber, buys cyan", L + 6, B + 2);
}

/** Seat A's left monitor: the offer ladder by hour (blocks to sell and to buy, MW at price). */
export function drawLadder(g, w, h, d, s) {
  g.fillStyle = "#0b121a";
  g.fillRect(0, 0, w, h);
  const off = d.offerAt(s.t);
  g.fillStyle = "#13263a";
  g.fillRect(0, 0, w, 34);
  g.fillStyle = C.ink;
  g.font = `700 18px ${FONT}`;
  g.fillText(`SEAT A · ESR OFFER · OD ${d.task.date}`, 12, 23);
  g.fillStyle = off ? C.good : C.gold;
  g.textAlign = "right";
  g.fillText(off ? `SUBMITTED ${hh(off.min)}` : "DRAFT", w - 12, 23);
  g.textAlign = "left";
  const hours = off ? off.hours : null;
  const rowH = (h - 70) / 24;
  g.font = `500 ${Math.min(15, rowH * 0.8)}px ${MONO}`;
  g.fillStyle = C.faint;
  g.fillText("HE   SELL MW@$            BUY MW@$", 12, 54);
  for (let k = 0; k < 24; k++) {
    const y = 66 + k * rowH;
    if (k === s.h) {
      g.fillStyle = "rgba(242,193,78,0.16)";
      g.fillRect(0, y - rowH + 4, w, rowH);
    }
    g.fillStyle = C.dim;
    g.fillText(String(k + 1).padStart(2, " "), 12, y);
    if (!hours) continue;
    const x = hours[k];
    g.fillStyle = C.discharge;
    g.fillText(x.sell.slice(0, 2).map(([m, p]) => `${Math.round(m)}@${Math.round(p)}`).join(" ") || "·", 60, y);
    g.fillStyle = C.charge;
    g.fillText(x.buy.slice(0, 2).map(([m, p]) => `${Math.round(m)}@${Math.round(p)}`).join(" ") || "·", w * 0.56, y);
  }
}

/** Seat A's right monitor: the settlement so far by hour, or before the day the hour's offer curve. */
export function drawBlotter(g, w, h, d, s) {
  g.fillStyle = "#0b121a";
  g.fillRect(0, 0, w, h);
  g.fillStyle = "#13263a";
  g.fillRect(0, 0, w, 34);
  g.fillStyle = C.ink;
  g.font = `700 18px ${FONT}`;
  g.fillText(s.min < 0 ? "CHECKS AND CONFIRMS" : "SETTLEMENT · SEAT A", 12, 23);
  g.font = `500 15px ${MONO}`;
  if (s.min < 0) {
    const lines = d.steps.filter((x) => x.t <= s.t).slice(-12).map((x) => {
      const o = x.out || {};
      const ok = o.error ? "✕" : o.valid === false || o.accepted === false ? "✕" : "✓";
      return [`${hh(d.watches[x.watch].min)} ${x.tool.replace(/_/g, " ")}`, ok, o.error || (o.issues?.length ? `${o.issues.length} issues` : o.status || "")];
    });
    lines.forEach(([a, ok, b], i) => {
      g.fillStyle = ok === "✓" ? C.good : C.bad;
      g.fillText(ok, 12, 58 + i * 22);
      g.fillStyle = C.ink;
      g.fillText(a, 34, 58 + i * 22);
      g.fillStyle = C.dim;
      g.fillText(String(b).slice(0, 26), w * 0.62, 58 + i * 22);
    });
    return;
  }
  const n = Math.min(24, Math.floor(s.min / 60));
  let tot = 0;
  for (let k = 0; k < 24; k++) {
    const y = 58 + k * ((h - 90) / 24);
    const x = d.hours[k];
    g.fillStyle = k < n ? C.ink : C.faint;
    g.fillText(String(k + 1).padStart(2, " "), 12, y);
    if (k < n) {
      tot += x.cash;
      g.fillStyle = x.exec > 0.5 ? C.discharge : x.exec < -0.5 ? C.charge : C.dim;
      g.fillText(`${Math.round(x.exec)}`.padStart(6, " "), 48, y);
      g.fillStyle = x.cash >= 0 ? C.good : C.bad;
      g.fillText(usd(x.cash).padStart(12, " "), w * 0.42, y);
    }
  }
  g.fillStyle = C.ink;
  g.font = `700 18px ${FONT}`;
  g.fillText(`so far ${usd(tot)}`, 12, h - 14);
}

/** Background desk screens: quotes, a price chart, a chat, a map of the grid, a load chart, a blotter. */
export function genericScreens(r) {
  const W = 512, H = 300, out = [];
  const frame = (g, title, acc = "#1c3550") => {
    g.fillStyle = "#0b1118";
    g.fillRect(0, 0, W, H);
    g.fillStyle = acc;
    g.fillRect(0, 0, W, 22);
    g.fillStyle = "#9db4c9";
    g.font = `700 13px ${FONT}`;
    g.fillText(title, 8, 16);
  };
  const can = (draw) => {
    const c = document.createElement("canvas");
    c.width = W;
    c.height = H;
    draw(c.getContext("2d"));
    return c;
  };
  out.push(can((g) => {
    frame(g, "HUB QUOTES");
    for (let y = 34; y < H - 6; y += 16) {
      g.fillStyle = y % 32 ? "#101922" : "#0d151d";
      g.fillRect(4, y - 11, W - 8, 15);
      g.fillStyle = "#8aa0b4";
      g.font = `500 12px ${MONO}`;
      g.fillText(["HB_NORTH", "HB_HOUSTON", "HB_WEST", "HB_SOUTH", "HB_PAN", "LZ_AEN", "LZ_CPS"][Math.floor(r() * 7)], 10, y);
      g.fillStyle = r() < 0.5 ? "#5fd08f" : "#ff6a5c";
      g.fillText((20 + r() * 80).toFixed(2), 150, y);
      g.fillStyle = "#c9d6e2";
      g.fillText((20 + r() * 80).toFixed(2), 260, y);
      g.fillText((r() * 400).toFixed(0), 380, y);
    }
  }));
  out.push(can((g) => {
    frame(g, "RT LMP · 5 MIN", "#2a2f4a");
    g.strokeStyle = "#7fb0ff";
    g.lineWidth = 2;
    g.beginPath();
    let y = H * 0.6;
    for (let x = 6; x < W - 6; x += 6) {
      y = Math.max(40, Math.min(H - 20, y + (r() - 0.52) * 22));
      x === 6 ? g.moveTo(x, y) : g.lineTo(x, y);
    }
    g.stroke();
    g.strokeStyle = "#1b2836";
    for (let k = 1; k < 5; k++) {
      g.beginPath();
      g.moveTo(0, 22 + (k * (H - 22)) / 5);
      g.lineTo(W, 22 + (k * (H - 22)) / 5);
      g.stroke();
    }
  }));
  out.push(can((g) => {
    frame(g, "CHAT", "#24343f");
    for (let y = 40; y < H - 8; y += 22) {
      g.fillStyle = "#4f6578";
      g.fillRect(8, y - 10, 46, 9);
      g.fillStyle = "#8a9caf";
      g.fillRect(62, y - 10, 60 + r() * 360, 9);
    }
  }));
  out.push(can((g) => {
    frame(g, "ERCOT SYSTEM", "#1f3b33");
    g.fillStyle = "#12201b";
    g.fillRect(6, 28, W - 12, H - 34);
    g.strokeStyle = "#5fd08f";
    g.lineWidth = 2;
    g.beginPath();
    for (let x = 0; x < W - 20; x += 8) g.lineTo(10 + x, H - 40 - Math.sin(x / 70) * 60 - x * 0.18 - r() * 4);
    g.stroke();
    g.strokeStyle = "#f2c14e";
    g.beginPath();
    for (let x = 0; x < W - 20; x += 8) g.lineTo(10 + x, H - 60 - Math.max(0, Math.sin((x - 80) / 110)) * 120);
    g.stroke();
  }));
  out.push(can((g) => {
    frame(g, "POSITIONS");
    g.font = `500 12px ${MONO}`;
    for (let y = 40; y < H - 6; y += 15) {
      g.fillStyle = "#7d8a95";
      g.fillText(`${["DA", "RT", "OTC", "CFD"][Math.floor(r() * 4)]}  HE${String(1 + Math.floor(r() * 24)).padStart(2, "0")}`, 10, y);
      g.fillStyle = r() < 0.5 ? "#ffa62b" : "#2fd3ff";
      g.fillText(`${Math.round(r() * 300)} MW`, 150, y);
      g.fillStyle = "#c9d6e2";
      g.fillText(`$${(20 + r() * 60).toFixed(2)}`, 260, y);
    }
  }));
  out.push(can((g) => {
    frame(g, "WEATHER · TX", "#33402a");
    g.fillStyle = "#132233";
    g.fillRect(6, 28, W - 12, H - 34);
    for (let k = 0; k < 50; k++) {
      const x = 40 + r() * (W - 80), y = 50 + r() * (H - 80), s = 4 + r() * 20;
      g.fillStyle = r() < 0.2 ? "rgba(230,190,60,0.6)" : "rgba(60,170,90,0.5)";
      g.beginPath();
      g.ellipse(x, y, s, s * 0.6, r() * 3, 0, Math.PI * 2);
      g.fill();
    }
  }));
  return out;
}

/** A floating card's face: a title and a line, with a stripe in the seat's or the event's colour. */
export function drawCard(g, w, h, { title, line, color = SEAT.A.color, stamp: st = false }) {
  g.clearRect(0, 0, w, h);
  g.fillStyle = st ? "rgba(255,240,236,0.97)" : "rgba(250,249,245,0.97)";
  roundRect(g, 4, 4, w - 8, h - 8, 18);
  g.fill();
  g.fillStyle = color;
  roundRect(g, 4, 4, 16, h - 8, 8);
  g.fill();
  g.fillStyle = "#1c2329";
  g.font = `700 40px ${FONT}`;
  g.textBaseline = "alphabetic";
  g.fillText(title, 40, h * 0.46);
  g.fillStyle = "#46525b";
  g.font = `500 28px ${FONT}`;
  g.fillText(line, 40, h * 0.8);
}
