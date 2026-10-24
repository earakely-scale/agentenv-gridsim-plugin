import { at, hourLabel, money, price } from "../data.js";
import { describe, weatherAt } from "../stage/weather.js";

export const ATTRIBUTION = "Prices: ERCOT DAM settlement point prices (public). Not affiliated with or endorsed by ERCOT. Weather: IEM ASOS.";
const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const NS = "http://www.w3.org/2000/svg";
const svg = (w, h, inner) => `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${inner}</svg>`;
const clock = (t) => {
  const m = Math.round(t * 60);
  const h = Math.floor(m / 60) % 24, mm = m % 60;
  const h12 = h % 12 || 12;
  return `${h12}:${String(mm).padStart(2, "0")}<small>${h < 12 ? "am" : "pm"}</small>`;
};
const span = (h) => `${hourLabel(h)}–${hourLabel(h + 1)}`;

/** The cards over the scene: place card, news strip, race and score, the agent's reasoning, the timeline. */
export function buildHud(root, d, { onSeek, onToggle }) {
  const b = d.b;
  const place = el("section", "card place");
  const news = el("div", "news off");
  const right = el("aside", "right");
  const race = el("section", "card race");
  const think = el("section", "card think");
  right.append(race, think);
  const timeline = el("section", "card timeline");
  const attrib = el("div", "attrib", ATTRIBUTION);
  root.append(place, news, right, timeline, attrib);

  const ghosts = d.ghosts;
  const same = (g) => g && JSON.stringify(g.sched) === JSON.stringify(d.ep.final_schedule);
  const lanes = [
    { k: "agent", label: modelName(d.ep.model), cls: "agent", cum: d.agentCum, final: d.ep.profit_usd },
    ghosts.opt && !same(ghosts.opt) && { k: "opt", label: "DP optimum", cls: "opt", cum: ghosts.opt.cum, final: ghosts.opt.profit },
    ghosts.greedy && !same(ghosts.greedy) && { k: "greedy", label: "Greedy", cls: "base", cum: ghosts.greedy.cum, final: ghosts.greedy.profit },
    ghosts.threshold && !same(ghosts.threshold) && { k: "threshold", label: "Threshold", cls: "base", cum: ghosts.threshold.cum, final: ghosts.threshold.profit },
  ].filter(Boolean);
  const extent = Math.max(1, ...lanes.flatMap((l) => [Math.abs(l.final), ...l.cum.map(Math.abs)]));
  const lo = Math.min(0, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  const hi = Math.max(1, ...lanes.flatMap((l) => [l.final, ...l.cum]));
  race.innerHTML = `<h5>Race against the optimum</h5>` + lanes.map((l) => `<div class="lane ${l.cls}" data-k="${l.k}"><div class="who">${l.k === "agent" ? `<b>${l.label}</b>` : l.label}</div><div class="track"><i class="z"></i><span></span></div><div class="v num"></div></div>`).join("") +
    `<svg class="spark" viewBox="0 0 240 70" preserveAspectRatio="none"></svg><div class="score" hidden></div>`;
  void extent;
  const zx = (v) => ((v - lo) / (hi - lo)) * 100;
  race.querySelectorAll(".lane .z").forEach((z) => (z.style.left = `${zx(0)}%`));

  think.innerHTML = reasoning(d);
  timeline.innerHTML = `<div class="ctl"><div class="row"><button class="play" data-a="play">▶ Play</button><button data-a="director" class="on" title="Automatic camera (D)">Director</button></div>
    <div class="row speeds">${[0.5, 1, 2, 4].map((s, i) => `<button data-s="${s}" title="${i + 1}">${s === 0.5 ? "½" : s}×</button>`).join("")}</div>
    <div class="row"><button data-a="charts" title="C">Charts</button><button data-a="settings">Settings</button><a class="back" href="./index.html">All runs</a></div></div>
    <div class="tl"><div class="hours">${[0, 3, 6, 9, 12, 15, 18, 21].map((h) => `<span style="left:${(h / 24) * 100}%">${hourLabel(h)}</span>`).join("")}</div><div class="legend"><span><i style="background:var(--charge-l)"></i>charge</span><span><i style="background:var(--discharge-l)"></i>discharge</span><span><i style="background:var(--ghost)"></i>optimum (ghost)</span><span><i style="border:1.5px dashed #1c2329"></i>differs</span></div>${tlSvg(d)}<div class="ph"></div></div>`;
  const tl = timeline.querySelector(".tl");
  const ph = tl.querySelector(".ph");
  const seekAt = (e) => {
    const r = tl.getBoundingClientRect();
    onSeek(Math.max(0, Math.min(24, ((e.clientX - r.left) / r.width) * 24)));
  };
  let drag = false;
  tl.addEventListener("pointerdown", (e) => ((drag = true), tl.setPointerCapture(e.pointerId), seekAt(e)));
  tl.addEventListener("pointermove", (e) => drag && seekAt(e));
  tl.addEventListener("pointerup", () => (drag = false));
  timeline.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => onToggle(btn.dataset.a || "speed", btn.dataset.s ? +btn.dataset.s : null)));

  let lastKey = "";
  function update(t, { playing, speed, directing }) {
    const x = at(d, Math.min(23.999, Math.max(0, t)));
    const w = weatherAt(d.weather, Math.max(0, Math.min(24, t)));
    const h = x.h;
    const p = x.price;
    const hot = p >= [...d.prices].sort((a, c) => a - c)[21];
    const mw = Math.abs(x.mw);
    const actText = t < 0 ? "Before the day: planning" : t >= 24 ? (d.trunc != null ? "Day over · the plan was cut short" : "Day over") :
      x.mode === "violation" ? `Breaks a rule here: ${d.ep.violation === "soc_below_0" ? "selling more than it holds" : d.ep.violation === "soc_above_N" ? "charging past full" : d.ep.violation === "cycle_cap" ? "past the cycle limit" : "over the power limit"}` :
      x.mode === "grey" ? `Cancelled · the plan broke a rule at ${hourLabel(d.trunc)}` :
      x.mode === "charge" ? (p < 0 ? `Charging ${mw} MW, paid ${price(-p)}/MWh to take it` : `Charging ${mw} MW at ${price(p)}/MWh`) :
      x.mode === "discharge" ? `Discharging ${mw} MW at ${price(p)}/MWh` : `Idle${p < 0 ? " through a negative price" : ""}`;
    const socPct = (x.soc / b.soc_levels) * 100;
    const hidden = d.ep.tier === "blind" && t < 0;
    const gap = x.optCash != null ? x.cash - x.optCash : null;
    const key = [Math.floor(t * 12), playing, speed, directing].join("|");
    if (key !== lastKey) {
      lastKey = key;
      place.innerHTML = `<div class="where">${d.dateLabel} · <b>${d.task.settlement_point}</b> · ${d.place.name}<span class="tier ${d.ep.tier}">${d.ep.tier.toUpperCase()}</span></div>
        <div class="big"><span class="clock num">${t >= 24 ? "End of day" : clock(Math.max(0, t))}</span>${hidden ? `<span class="price num" style="color:var(--faint)">$ ?<small>/MWh</small></span>` : `<span class="price num ${p < 0 ? "neg" : hot ? "hot" : ""}">${price(p)}<small>/MWh</small></span>`}</div>
        <div class="where" style="margin-top:-2px">${hidden ? "today's prices are hidden until it submits" : t >= 24 ? `last hour: ${span(23)}` : `day-ahead price for ${span(h)}`}</div>
        <div class="act ${t >= 24 ? "" : x.mode}"><i></i><span>${actText}</span></div>
        <div class="soc"><div class="row"><span>State of charge</span><span><b class="num">${Math.round(socPct)}%</b> · ${Math.round(x.soc * b.unit_mwh)} of ${b.energy_mwh} MWh</span></div>
          <div class="bar"><div class="fill" style="width:${socPct}%"></div>${b.s_end_min > 0 ? `<div class="mark" style="left:${(b.s_end_min / b.soc_levels) * 100}%" data-label="end ≥ ${Math.round((b.s_end_min / b.soc_levels) * 100)}%"></div>` : ""}</div></div>
        <div class="cash"><div>Cash so far<b class="num">${money(x.cash)}</b></div><div>Optimum so far<b class="num">${x.optCash == null ? "—" : money(x.optCash)}</b></div><div class="gap">Gap<b class="num ${gap == null ? "" : gap >= -0.5 ? "good" : "bad"}">${gap == null ? "—" : money(gap, { sign: true })}</b></div></div>
        ${t >= 24 && d.ep.end_shortfall_units > 0 ? `<div class="bill">Penalty bill: <b>${money(-d.penalty)}</b><br>Ended ${d.ep.end_shortfall_units} unit${d.ep.end_shortfall_units > 1 ? "s" : ""} (${d.ep.end_shortfall_units * b.unit_mwh} MWh) below the required charge, bought back at ${price(Math.max(d.maxP, 50))}/MWh after losses.</div>` : ""}
        <div class="meta">${b.p_dis_mw} MW / ${b.energy_mwh} MWh battery · ${Math.round(b.energy_mwh / Math.max(1, b.p_dis_mw))}-hour · ${describe(w) || "weather n/a"}</div>`;
      const n = x.news && t < 24.5 ? x.news : t >= 24 && d.news.find((q) => q.kind === "penalty") ? d.news.find((q) => q.kind === "penalty") : null;
      if (n) {
        news.className = `news ${n.kind}`;
        news.innerHTML = `<i></i><span>${n.text}</span>`;
      } else news.className = "news off";
      for (const l of lanes) {
        const v = t >= 24 ? l.final : x.h > 0 || x.u > 0 ? l.cum[h - 1] ?? 0 : 0;
        const vv = t >= 24 ? l.final : (h > 0 ? l.cum[h - 1] : 0) + ((l.cum[h] - (h > 0 ? l.cum[h - 1] : 0)) * x.u);
        void v;
        const row = race.querySelector(`.lane[data-k="${l.k}"]`);
        const s = row.querySelector("span");
        const a = zx(Math.min(0, vv)), c = zx(Math.max(0, vv));
        s.style.left = `${a}%`;
        s.style.width = `${Math.max(0.5, c - a)}%`;
        row.querySelector(".v").textContent = money(vv);
      }
      race.querySelector(".spark").innerHTML = spark(lanes, Math.min(24, t), lo, hi);
      const score = race.querySelector(".score");
      score.hidden = t < 24;
      if (t >= 24) score.innerHTML = scoreBox(d);
      timeline.querySelector(".play").textContent = playing ? "❚❚ Pause" : "▶ Play";
      timeline.querySelectorAll("[data-s]").forEach((s) => s.classList.toggle("on", +s.dataset.s === speed));
      timeline.querySelector('[data-a="director"]').classList.toggle("on", directing);
      tl.querySelectorAll(".col").forEach((c) => c.classList.toggle("now", +c.dataset.h === h && t < 24));
    }
    ph.style.left = `${(Math.min(24, Math.max(0, t)) / 24) * 100}%`;
  }
  return { update, place, timeline };
}

const REFS = { "dp-optimum": "DP optimum (reference)", greedy: "Greedy (reference)", threshold: "Threshold (reference)", "flawed-plan": "Flawed plan (demo)", "persistence-dp": "Persistence DP (reference)" };

export function modelName(m) {
  if (!m) return "Agent";
  if (m.startsWith("reference/")) return REFS[m.slice(10)] || m.slice(10);
  const base = m.split("/").pop();
  const g = base.match(/^gpt-([\d.]+)-?(.*)$/i);
  if (g) return `GPT-${g[1]}${g[2] ? " " + g[2].replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) : ""}`;
  return base.replace(/-/g, " ");
}

function tlSvg(d) {
  const W = 1200, H = 96, top = 14, barH = 44, chipY = top + barH + 5, chipH = 18, ghostY = chipY + chipH + 3, ghostH = 9;
  const cw = W / 24;
  const max = Math.max(1, ...d.prices.map((p) => Math.max(0, p)));
  const min = Math.min(0, ...d.prices);
  const zero = top + barH * (max / (max - min || 1));
  const sy = barH / (max - min || 1);
  let s = `<line x1="0" x2="${W}" y1="${zero}" y2="${zero}" stroke="rgba(0,0,0,0.25)" stroke-width="1"/>`;
  d.hours.forEach((x, h) => {
    const p = x.price;
    const y = p >= 0 ? zero - p * sy : zero;
    const hh = Math.max(1.5, Math.abs(p) * sy);
    const grey = x.mode === "grey";
    s += `<g class="col" data-h="${h}"><rect x="${h * cw + 3}" y="${y}" width="${cw - 6}" height="${hh}" rx="2" fill="${p < 0 ? "#9a7fd0" : "#9fb0bc"}" opacity="${grey ? 0.45 : 0.95}"/>`;
    const a = x.action, o = x.opt;
    const chip = (v, y0, hgt, ghost) => {
      if (!v) return `<circle cx="${h * cw + cw / 2}" cy="${y0 + hgt / 2}" r="2" fill="${ghost ? "rgba(0,0,0,0.18)" : "#aab3b8"}"/>`;
      const c = v < 0 ? "#2fd3ff" : "#ffa62b";
      const wv = (cw - 6) * (Math.abs(v) / Math.max(d.b.k_ch, d.b.k_dis));
      return `<rect x="${h * cw + cw / 2 - wv / 2}" y="${y0}" width="${wv}" height="${hgt}" rx="3" fill="${ghost ? "rgba(28,35,41,0.2)" : grey ? "#c4c9cc" : c}"/>` +
        (ghost ? "" : `<text x="${h * cw + cw / 2}" y="${y0 + hgt - 5}" text-anchor="middle" font-size="11" font-weight="650" fill="${grey ? "#7a868e" : "#1c2329"}">${v > 0 ? "+" : "−"}${Math.abs(v) * d.b.unit_mwh}</text>`);
    };
    const shown = x.mode === "grey" || x.mode === "violation" ? x.intended : a;
    s += chip(shown, chipY, chipH, false);
    if (x.mode === "violation") s += `<rect x="${h * cw + 2}" y="${chipY - 2}" width="${cw - 4}" height="${chipH + 4}" rx="4" fill="none" stroke="#cf3e33" stroke-width="2"/>`;
    else if (x.mismatch && x.mode !== "grey") s += `<rect x="${h * cw + 2}" y="${chipY - 2}" width="${cw - 4}" height="${chipH + 4}" rx="4" fill="none" stroke="#1c2329" stroke-width="1.2" stroke-dasharray="3 2"/>`;
    if (o != null) s += chip(o, ghostY, ghostH, true);
    s += `<rect class="hl" x="${h * cw}" y="0" width="${cw}" height="${ghostY + ghostH + 3}" fill="rgba(28,35,41,0.06)" rx="4"/></g>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><style>.col .hl{opacity:0}.col.now .hl{opacity:1}</style>${s}</svg>`;
}

function spark(lanes, t, lo, hi) {
  const W = 240, H = 70;
  const y = (v) => H - 4 - ((v - lo) / (hi - lo || 1)) * (H - 8);
  let s = `<line x1="0" x2="${W}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(0,0,0,0.15)"/>`;
  for (const l of lanes) {
    const pts = [[0, 0], ...l.cum.map((v, h) => [h + 1, v])].filter(([h]) => h <= Math.ceil(t));
    const col = l.k === "agent" ? "#2c3440" : l.k === "opt" ? "rgba(28,35,41,0.4)" : "rgba(28,35,41,0.18)";
    s += `<polyline fill="none" stroke="${col}" stroke-width="${l.k === "agent" ? 2.2 : 1.5}" ${l.k === "opt" ? 'stroke-dasharray="4 3"' : ""} points="${pts.map(([h, v]) => `${(h / 24) * W},${y(v)}`).join(" ")}"/>`;
  }
  return s;
}

function scoreBox(d) {
  const r = d.reward ?? 0;
  const g = d.ghosts;
  const vs = (k) => (g[k] ? d.ep.profit_usd - g[k].profit : null);
  const fmt = (v) => (v == null ? "—" : `<b class="${v >= 0 ? "good" : "bad"}">${money(v, { sign: true })}</b>`);
  return `<div class="grade ${d.grade}">${d.grade}</div><div class="r num">${r.toFixed(3)}<small>reward</small></div>
    <div class="rbar"><span style="width:${r * 100}%"></span></div>
    <div class="line">Captured <b>${d.captured == null ? "—" : Math.round(d.captured * 100) + "%"}</b> of the day's spread (${money(d.ep.profit_usd)} of ${money(d.pOpt)} the optimum made${d.pIdle ? `, idle ${money(d.pIdle)}` : ""}).</div>
    <div class="line">vs greedy ${fmt(vs("greedy"))} · vs threshold ${fmt(vs("threshold"))}${d.penalty ? ` · penalty <b class="bad">${money(-d.penalty)}</b>` : ""}</div>`;
}

function chips(actions) {
  return `<div class="chips">${actions.map((a) => `<i class="${a < 0 ? "c" : a > 0 ? "d" : ""}" style="opacity:${a ? 0.35 + 0.65 * Math.min(1, Math.abs(a) / 4) : 1}"></i>`).join("")}</div>`;
}

function reasoning(d) {
  const rows = d.checks.map((c, i) => `<div class="plan practice"><span>Practice ${i + 1}</span>${chips(c.actions || [])}<span class="note">${c.out?.feasible === false ? `infeasible at ${hourLabel(c.out.truncated_at ?? 0)}` : `profit ${money(c.out?.profit_usd ?? 0)}`}</span></div>`).join("");
  const final = `<div class="plan"><span><b>Final plan</b></span>${chips(d.ep.final_schedule || d.actions)}<span class="note">submitted · ${d.ep.truncated_at != null ? `cut short at ${hourLabel(d.ep.truncated_at)}` : `profit ${money(d.ep.profit_usd)}`}</span></div>`;
  const msg = d.message ? `<blockquote>“${escapeHtml(d.message.slice(0, 360))}${d.message.length > 360 ? "…" : ""}”</blockquote>` : "";
  return `<h5>How it decided <small style="text-transform:none;letter-spacing:0;font-weight:400">${d.checks.length} practice check${d.checks.length === 1 ? "" : "s"}</small></h5>${rows}${final}${msg}`;
}

const escapeHtml = (s) => s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
void NS;
void svg;
