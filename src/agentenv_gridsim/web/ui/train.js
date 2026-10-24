import { grade, hourLabel, load, money, price } from "../data.js";
import { GridStage } from "../stage/stage.js";
import { ATTRIBUTION, modelName } from "./hud.js";

const el = (tag, cls, html) => {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html != null) e.innerHTML = html;
  return e;
};
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const json = async (url) => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
};
const clock = (t) => {
  const m = Math.round(clamp(t, 0, 24) * 60), h = Math.floor(m / 60) % 24, mm = m % 60;
  return `${h % 12 || 12}:${String(mm).padStart(2, "0")}<small>${h < 12 ? "am" : "pm"}</small>`;
};
const STAGE = { base: "Base", sft: "SFT", grpo: "GRPO" };
const hourName = (h) => (h === 0 ? "midnight" : h === 12 ? "noon" : `${h % 12} ${h < 12 ? "am" : "pm"}`);
/** The run over every held-out day, from the manifest's context: stage means, the rules, how the plans open. */
function overall(c, man) {
  if (!c || c.trained == null) return "";
  const n = c.tasks ? `${c.tasks} held-out days` : "the held-out days";
  const rules = c.greedy != null ? ` The greedy rule scores ${c.greedy.toFixed(2)}${c.threshold != null ? `, the threshold rule ${c.threshold.toFixed(2)}` : ""}.` : "";
  const open = c.opening ? ` ${c.opening.share[0]} of ${c.opening.share[1]} trained plans open by ${c.opening.charge ? "charging" : "trading"} at ${hourName(c.opening.hour)}, whatever the battery already holds.` : "";
  const days = man?.days ? ` This day is one of ${man.days.doing_well} in ${man.days.candidates} checkpointed days where it reaches 0.85.` : "";
  return `Across all ${n} the model goes from ${c.base.toFixed(2)} (base) to ${c.sft.toFixed(2)} (SFT) to ${c.trained.toFixed(2)} (GRPO).${rules}${days}${open}`;
}
const frameName = (f) => (f.trained === "grpo" ? (f.step != null ? `Step ${f.step}` : "Trained") : STAGE[f.trained] || f.trained);

/** The training views: LEVEL UP (one held-out day at successive checkpoints, the plan converging on the DP ghost)
 * and the race (up to four models on the same day on one clock). Both drive the same yard. */
export async function trainView(app, q) {
  const mode = q.has("levelup") ? "levelup" : "race";
  const url = q.get(mode);
  const base = url.replace(/[^/]*$/, "");
  const man = await json(url);
  const items = mode === "levelup" ? man.frames : man.lanes;
  const eps = await Promise.all(items.map((x) => json(`${base}${x.episode_id}.json`)));
  const e0 = eps[0];
  const wxUrl = q.get("weather") || `${q.get("wxbase") || "weather"}/${e0.task.date}_${e0.task.settlement_point}.json`;
  const weather = await json(wxUrl).catch(() => null);
  const ds = eps.map((e) => load(e, weather));
  const manual = q.has("record");
  const reduced = q.has("reduced") ? q.get("reduced") !== "0" : matchMedia("(prefers-reduced-motion: reduce)").matches;
  app.innerHTML = "";
  const root = el("div", `ep train t-${mode}`);
  const host = el("div", "stage-host");
  root.append(host);
  app.append(root);
  root.classList.toggle("reduced", reduced);
  if (q.get("ui") === "0") root.classList.add("bare");
  const focus0 = mode === "race" ? Math.max(0, items.findIndex((x, i) => eps[i].trained === "grpo")) : ds.length - 1;
  const stage = new GridStage(host, ds[focus0], { manual, reduced });
  const view = mode === "levelup" ? levelUp(root, man, ds, stage, q) : race(root, man, ds, stage, focus0);
  document.title = `${mode === "levelup" ? "LEVEL UP" : "Race"} · ${e0.task.settlement_point} ${e0.task.date} · GridSimEnv`;
  root.append(el("div", "attrib", ATTRIBUTION), Object.assign(el("a", "back-link", "← All runs"), { href: "./index.html" }));
  const P = { T: q.has("t") ? +q.get("t") : 0, playing: !manual, speed: 1, wall: 0 };
  const draw = (dt) => {
    const s = view.at(P.T);
    stage.d = s.d;
    stage.drift = s.drift;
    stage.force = s.shot;
    stage.frame({ t: s.t, dt, wall: P.wall });
    view.update(P.T, s);
  };
  addEventListener("keydown", (e) => {
    if (e.code === "Space") (P.playing = !P.playing), e.preventDefault();
    else if (["1", "2", "3", "4"].includes(e.key) && view.focus) view.focus(+e.key - 1);
    else if (e.key === "ArrowRight") P.T = Math.min(view.duration, P.T + 3);
    else if (e.key === "ArrowLeft") P.T = Math.max(0, P.T - 3);
  });
  root.addEventListener("click", (e) => {
    const b = e.target.closest("[data-play]");
    if (b) P.playing = !P.playing, P.T >= view.duration && (P.T = 0);
  });
  window.gridsim = {
    ready: Promise.resolve({ mode, duration: view.duration, shots: [] }),
    async time(T, { dt = 1 / 30 } = {}) {
      P.T = +T;
      P.wall += dt;
      draw(dt);
      await new Promise((r) => requestAnimationFrame(() => r()));
      return P.T;
    },
    state: () => ({ T: P.T, ...stage.state() }),
    stage,
  };
  if (manual) return draw(0);
  let last = performance.now();
  const loop = (now) => {
    const dt = Math.min(0.1, (now - last) / 1000);
    last = now;
    P.wall += dt;
    if (P.playing) P.T = Math.min(view.duration, P.T + dt * P.speed);
    if (P.T >= view.duration) P.playing = false;
    draw(dt);
    requestAnimationFrame(loop);
  };
  requestAnimationFrame(loop);
}

function cells(d, { now = null, ghost = false } = {}) {
  const k = Math.max(d.b.k_ch, d.b.k_dis);
  return d.hours.map((x, h) => {
    const a = x.mode === "grey" || x.mode === "violation" ? x.intended : x.action;
    const cls = x.mode === "violation" ? "bad" : x.mode === "grey" ? "grey" : a > 0 ? "d" : a < 0 ? "c" : "";
    return `<i class="${cls}${now === h ? " now" : ""}${ghost ? " gh" : ""}" style="--a:${a ? 0.35 + 0.65 * Math.min(1, Math.abs(a) / k) : 1}"></i>`;
  }).join("");
}

function ghostCells(d) {
  const o = d.ghosts.opt;
  if (!o) return "";
  return o.executed.map((a) => `<i class="${a > 0 ? "d" : a < 0 ? "c" : ""} gh"></i>`).join("");
}

const matches = (d) => (d.ghosts.opt ? d.hours.filter((x, h) => x.action === d.ghosts.opt.executed[h] && x.mode !== "grey" && x.mode !== "violation").length : null);

/** LEVEL UP: an intro, then for each checkpoint the day at speed and a held moment for its reward, then a summary. */
function levelUp(root, man, ds, stage, q) {
  const SEG = +q.get("seg") || 6.5, HOLD = 1.1, INTRO = 5, OUTRO = 5.5;
  const DAY = SEG - HOLD, n = ds.length;
  const duration = INTRO + n * SEG + OUTRO;
  const d0 = ds[0], b = d0.b;
  const name = modelName(man.model).replace(/^Qwen\s/, "Qwen").replace(/Qwen3 1\.7B/, "Qwen3-1.7B");
  const rewards = man.frames.map((f, i) => ds[i].reward ?? 0);
  const peakEve = d0.prices.indexOf(Math.max(...d0.prices.slice(15, 22)));
  const head = el("section", "card lvl-head");
  const rew = el("section", "card lvl-reward");
  const stack = el("section", "card lvl-stack");
  const toast = el("div", "lvl-toast");
  const intro = el("section", "card lvl-intro");
  root.append(head, rew, stack, toast, intro);
  intro.innerHTML = `<h5>LEVEL UP · a held-out day</h5><h2>${esc(name)} learns to run one battery-day</h2>
    <p>${d0.dateLabel} at <b>${esc(d0.task.settlement_point)}</b> (${esc(d0.place.name)}): a ${b.p_dis_mw} MW / ${b.energy_mwh} MWh battery, the day's 24 ERCOT day-ahead prices from ${price(d0.minP)} to ${price(d0.maxP)}/MWh. The same day is replayed at each checkpoint of training, against the exact optimum (the grey ghost).</p>
    <p class="dim">Picked by rule: ${esc(man.rule)}.${man.note ? ` <b>${esc(man.note)}.</b>` : ""}</p>
    ${overall(man.context, man) ? `<p class="ctx">${esc(overall(man.context, man))}</p>` : ""}`;
  const W = 260, H = 64;
  const rx = (i) => 8 + ((W - 16) * i) / Math.max(1, n - 1), ry = (v) => H - 8 - clamp(v) * (H - 16);
  let lastKey = "";
  function at(T) {
    const k = Math.min(n - 1, Math.max(0, Math.floor((T - INTRO) / SEG)));
    const s = T - INTRO - k * SEG;
    const t = T < INTRO ? peakEve + 0.5 : T >= INTRO + n * SEG ? 24.2 : clamp(s / DAY, 0, 1) * 24;
    return { k: T < INTRO ? -1 : k, s, t, d: ds[T < INTRO ? 0 : k], drift: clamp(T / duration), shot: "establish", end: T >= INTRO + n * SEG, hold: T >= INTRO && s >= DAY };
  }
  function update(T, st) {
    const { k, t, end, hold } = st;
    const key = [k, Math.floor(t * 4), hold, end].join("|");
    const fade = (a, c) => clamp((T - a) / (c - a));
    intro.style.opacity = 1 - fade(INTRO - 0.5, INTRO);
    intro.hidden = T > INTRO;
    const ki = Math.max(0, k);
    const f = man.frames[ki], d = ds[ki];
    const shownR = end || hold ? rewards[ki] : null;
    const xp = man.total_steps ? (f.trained === "grpo" ? (f.step ?? man.total_steps) / man.total_steps : 0) : (ki + (hold || end ? 1 : 0)) / n;
    if (key !== lastKey) {
      lastKey = key;
      head.innerHTML = `<div class="eyebrow">LEVEL UP</div><div class="who">${esc(name)} <span class="tier ${f.trained}">${esc(STAGE[f.trained] || f.trained)}</span></div>
        <div class="lvl">${k < 0 ? "Before training" : f.trained === "grpo" ? `Step <b>${f.step ?? man.total_steps}</b>${man.total_steps ? ` <span>of ${man.total_steps}</span>` : ""}` : f.trained === "sft" ? "<b>SFT</b> warm start" : "<b>Base</b> model"}</div>
        <div class="xp"><span style="width:${(k < 0 ? 0 : xp) * 100}%"></span>${man.frames.map((x, i) => `<i style="left:${(man.total_steps && x.trained === "grpo" ? (x.step ?? man.total_steps) / man.total_steps : i / n) * 100}%" class="${i <= ki && k >= 0 ? "on" : ""}"></i>`).join("")}</div>
        <div class="meta">${d0.dateLabel} · ${esc(d0.task.settlement_point)} · ${b.p_dis_mw} MW / ${b.energy_mwh} MWh${k < 0 ? "" : ` · <span class="num">${clock(t)}</span>`}</div>`;
      const seen = rewards.slice(0, k < 0 ? 0 : hold || end ? ki + 1 : ki);
      rew.innerHTML = `<h5>Reward on this day</h5><div class="big num">${shownR == null ? (k < 0 ? "—" : `<span class="dim">…</span>`) : shownR.toFixed(3)}${shownR == null ? "" : `<span class="g ${grade(shownR)}">${grade(shownR)}</span>`}</div>
        <div class="sub">${k < 0 ? "1.0 is the exact optimum's plan" : shownR == null ? `cash so far ${money(cashAt(d, t))} · optimum ${money(optAt(d, t))}` : d.nosubmit ? "no valid plan: the battery sits idle" : `${money(d.ep.profit_usd)} of the optimum's ${money(d.pOpt)}`}</div>
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"><line x1="8" x2="${W - 8}" y1="${ry(1)}" y2="${ry(1)}" stroke="rgba(28,35,41,0.15)" stroke-dasharray="3 3"/><line x1="8" x2="${W - 8}" y1="${ry(0)}" y2="${ry(0)}" stroke="rgba(28,35,41,0.15)"/>
        <polyline fill="none" stroke="#2c3440" stroke-width="2" points="${seen.map((v, i) => `${rx(i)},${ry(v)}`).join(" ")}"/>${seen.map((v, i) => `<circle cx="${rx(i)}" cy="${ry(v)}" r="${i === seen.length - 1 ? 4 : 2.6}" fill="${i === seen.length - 1 ? "#1d9a57" : "#2c3440"}"/>`).join("")}</svg>`;
      const rows = man.frames.map((x, i) => i > ki || k < 0 ? "" : `<div class="srow ${i === ki ? "cur" : ""}"><span class="lab">${esc(frameName(x))}</span><span class="chips24">${cells(ds[i], { now: i === ki && !hold && !end ? Math.min(23, Math.floor(t)) : null })}</span><span class="m num">${ds[i].nosubmit ? "no plan" : i < ki || hold || end ? `${matches(ds[i])}/24 h · ${rewards[i].toFixed(2)}` : ""}</span></div>`).join("");
      stack.innerHTML = `<h5>The plan, checkpoint by checkpoint <small>against the exact optimum</small></h5><div class="srow ghost"><span class="lab">DP optimum</span><span class="chips24">${ghostCells(d0)}</span><span class="m">24/24 h · 1.00</span></div>${rows}
        <div class="hrs"><span></span><span>${[0, 6, 12, 18].map((h) => `<em style="left:${(h / 24) * 100}%">${hourLabel(h)}</em>`).join("")}</span><span></span></div>`;
    }
    const prev = ki > 0 ? rewards[ki - 1] : null;
    const show = hold && k >= 0 && !end;
    toast.style.opacity = show ? Math.min(fade(INTRO + ki * SEG + DAY, INTRO + ki * SEG + DAY + 0.2), 1 - fade(INTRO + (ki + 1) * SEG - 0.15, INTRO + (ki + 1) * SEG)) : end ? fade(INTRO + n * SEG, INTRO + n * SEG + 0.4) : 0;
    if (show) toast.innerHTML = `<div class="t">${prev == null ? "START" : rewards[ki] > prev + 1e-9 ? "LEVEL UP" : rewards[ki] < prev - 1e-9 ? "SETBACK" : "HOLDS"}</div><div class="v">${esc(frameName(f))} · reward ${prev == null ? "" : `${prev.toFixed(2)} → `}<b>${rewards[ki].toFixed(2)}</b></div>`;
    else if (end) {
      const c = man.context;
      toast.innerHTML = `<div class="t">TRAINED</div><div class="v">${esc(name)} on this day: reward <b>${rewards[0].toFixed(2)}</b> → <b>${rewards[n - 1].toFixed(2)}</b>${man.total_steps ? ` in ${man.total_steps} GRPO steps` : ""}</div>${man.note ? `<div class="note">${esc(man.note)}</div>` : ""}${c?.trained != null ? `<div class="all">Over all ${c.tasks || ""} held-out days: <b>${c.base.toFixed(2)} → ${c.sft.toFixed(2)} → ${c.trained.toFixed(2)}</b>${c.greedy != null ? `; the greedy rule scores ${c.greedy.toFixed(2)}` : ""}. Valid plans now, not yet the simple rules.</div>` : ""}`;
    }
  }
  return { duration, at, update };
}

const cashAt = (d, t) => {
  const h = Math.min(23, Math.floor(t)), u = clamp(t - h);
  return t >= 24 ? d.ep.profit_usd : (h > 0 ? d.hours[h - 1].cum : 0) + d.hours[h].cash * u;
};
const optAt = (d, t) => {
  if (!d.ghosts.opt) return 0;
  const h = Math.min(23, Math.floor(t)), u = clamp(t - h);
  return t >= 24 ? d.pOpt : (h > 0 ? d.ghosts.opt.cum[h - 1] : 0) + d.ghosts.opt.cash[h] * u;
};

/** The race: the lanes on one clock; the yard follows the focused lane (click a row, or keys 1-4). */
function race(root, man, ds, stage, focus0) {
  const INTRO = 2, DAYS = 72, OUTRO = 6;
  const duration = INTRO + DAYS + OUTRO;
  const d0 = ds[0], b = d0.b;
  let focus = focus0;
  const place = el("section", "card place race-place");
  const board = el("section", "card race-board");
  root.append(place, board);
  const all = ds.flatMap((d) => [d.ep.profit_usd, ...d.agentCum, d.pOpt ?? 0]);
  const lo = Math.min(0, ...all), hi = Math.max(1, ...all);
  const zx = (v) => ((v - lo) / (hi - lo)) * 100;
  const c = man.context;
  board.innerHTML = `<div class="rhead"><h5>Race · the same day, the same prices <small>the yard follows the highlighted lane · keys 1-${ds.length}</small></h5><button data-play class="play">❚❚ Pause</button></div>
    ${c?.trained != null ? `<div class="rctx">Over all ${c.tasks || ""} held-out days: base ${c.base.toFixed(2)} · SFT ${c.sft.toFixed(2)} · GRPO ${c.trained.toFixed(2)}${c.greedy != null ? ` · greedy rule ${c.greedy.toFixed(2)}` : ""}${c.threshold != null ? ` · threshold rule ${c.threshold.toFixed(2)}` : ""}</div>` : ""}
    <div class="rrow ghost"><span class="lab">DP optimum</span><span class="chips24">${ghostCells(d0)}</span><span class="rsoc"></span><span class="rcash"><span class="bar" style="left:${zx(0)}%;width:${zx(d0.pOpt ?? 0) - zx(0)}%"></span></span><span class="v num">${money(d0.pOpt ?? 0)}</span><span class="g0"></span></div>
    ${man.lanes.map((l, i) => `<div class="rrow lane" data-i="${i}"><span class="lab"><b>${i + 1}</b> ${esc(l.label)}</span><span class="chips24"></span><span class="rsoc"><span></span></span><span class="rcash"><i class="z" style="left:${zx(0)}%"></i><span class="bar"></span></span><span class="v num"></span><span class="g0"></span></div>`).join("")}
    <div class="hrs"><span></span><span>${[0, 6, 12, 18].map((h) => `<em style="left:${(h / 24) * 100}%">${hourLabel(h)}</em>`).join("")}</span><span></span></div>`;
  board.querySelectorAll(".rrow.lane").forEach((r) => r.addEventListener("click", () => setFocus(+r.dataset.i)));
  const setFocus = (i) => (focus = clamp(i, 0, ds.length - 1));
  const best = ds.reduce((a, d, i) => ((d.reward ?? -1) > (ds[a].reward ?? -1) ? i : a), 0);
  let lastKey = "";
  function at(T) {
    const t = T < INTRO ? 0 : Math.min(24.5, ((T - INTRO) / DAYS) * 24);
    return { t, d: ds[focus], drift: null, shot: null };
  }
  function update(T, { t }) {
    const h = Math.min(23, Math.floor(t)), end = t >= 24;
    const key = [Math.floor(t * 12), focus, end].join("|");
    if (key === lastKey) return;
    lastKey = key;
    const x = d0.hours[h];
    place.innerHTML = `<div class="where">${d0.dateLabel} · <b>${esc(d0.task.settlement_point)}</b> · ${esc(d0.place.name)}<span class="tier foresight">RACE</span></div>
      <div class="big"><span class="clock num">${end ? "End of day" : clock(t)}</span><span class="price num ${x.price < 0 ? "neg" : ""}">${price(x.price)}<small>/MWh</small></span></div>
      <div class="where">day-ahead price for ${hourLabel(h)}–${hourLabel(h + 1)} · ${b.p_dis_mw} MW / ${b.energy_mwh} MWh battery</div>
      <div class="where" style="margin-top:6px">In the yard: <b>${esc(man.lanes[focus].label)}</b></div>`;
    board.querySelectorAll(".rrow.lane").forEach((r, i) => {
      const d = ds[i];
      const v = end ? d.ep.profit_usd : cashAt(d, t);
      r.classList.toggle("focus", i === focus);
      r.querySelector(".chips24").innerHTML = cells(d, { now: end ? null : h });
      const soc = d.soc[Math.min(24, Math.floor(t))] / b.soc_levels;
      r.querySelector(".rsoc span").style.width = `${clamp(soc) * 100}%`;
      const a = zx(Math.min(0, v)), c = zx(Math.max(0, v));
      const bar = r.querySelector(".rcash .bar");
      bar.style.left = `${a}%`;
      bar.style.width = `${Math.max(0.4, c - a)}%`;
      r.querySelector(".v").textContent = money(v);
      r.querySelector(".g0").innerHTML = end ? (d.reward == null ? "" : `<span class="g ${grade(d.reward)}">${grade(d.reward)}</span> ${d.reward.toFixed(2)}${i === best ? " <b class='win'>best</b>" : ""}`) : "";
    });
  }
  return { duration, at, update, focus: setFocus };
}
