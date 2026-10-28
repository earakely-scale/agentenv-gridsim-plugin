/** The desk viewer: one recorded desk episode replayed on the battery site in 3D beside the desk. The clock runs on its
 * own between the agent's turns and stops at each turn while its tool calls play; ?v=v4&m=sol&task=desk-v4-... opens
 * an episode, &t=MINUTES a moment (minutes from the first operating day's midnight). */
import * as THREE from "three";
import { GridStage } from "gridsim/stage/stage.js";
import { describe } from "gridsim/stage/weather.js";
import { buildSheet } from "./browser.js";
import { REASONS, esc, mw as mwText, span, when } from "./fmt.js";
import { modelOf } from "./model.js";
import { buildPanel } from "./panel.js";
import { sceneOf } from "./scene.js";
import { buildTimeline } from "./timeline.js";

const RATE = { pre: 90, op: 30 };
const SPEEDS = [0.5, 1, 2, 4, 8];
const MODELS = { sol: "GPT-6.1 Sol", luna: "GPT-6 Luna", qwen: "Qwen3-4B" };
const SHORT = { sol: "Sol", luna: "Luna", qwen: "Qwen3-4B" };
const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = { t: 0, playing: false, speed: 1, hold: null, holdTurns: true, wall: 0 };
let C, M, D, stage, panel, timeline, sheet, tags, current, loading = 0;

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

function keyOf(v, m, task) {
  const ok = (k) => k && C.episodes[k];
  if (task && !v) v = task.split("-")[1];
  if (task) return ok(`${task}.${m || "sol"}`) ? `${task}.${m || "sol"}` : ok(`${task}.sol`) ? `${task}.sol` : null;
  const f = C.featured.find((x) => !v || x.key.startsWith(`desk-${v}-`));
  const k = f ? (m ? f.key.replace(/\.\w+$/, `.${m}`) : f.key) : null;
  return ok(k) ? k : f?.key ?? C.featured[0].key;
}

async function main() {
  C = await json("./data/catalog.json");
  const key = keyOf(Q.get("v"), Q.get("m"), Q.get("task")) || C.featured[0].key;
  sheet = buildSheet(C, { onPick: (k) => open(k, { push: true }) });
  $("open-sheet").addEventListener("click", () => sheet.show(current));
  controls();
  await open(key, { t: Q.has("t") ? +Q.get("t") : null, play: Q.get("play") !== "0" && !Q.has("t") });
  requestAnimationFrame(loop);
}

async function open(key, { t = null, play = true, push = false } = {}) {
  const n = ++loading;
  const e = C.episodes[key];
  $("boot").classList.remove("gone");
  $("boot").querySelector("span").textContent = `Loading ${C.tasks[e.task].name}, ${C.tasks[e.task].region}`;
  const [T, E] = await Promise.all([json(`./data/task/${e.task}.json`), json(`./data/ep/${key}.json`)]);
  if (n !== loading) return;
  current = key;
  stage?.dispose();
  stage = null;
  M = modelOf(C, T, E);
  D = sceneOf(T, E);
  const model = MODELS[E.model] || E.name;
  plate(T, E, model);
  panel = buildPanel(M, { model });
  timeline = buildTimeline(M, $("scrub"), { onSeek: seek });
  S.t = t ?? M.t0 - 0.01;
  S.hold = null;
  S.playing = play;
  const u = new URL(location.href);
  for (const [k, v] of [["v", T.version], ["m", E.model], ["task", T.task]]) u.searchParams.set(k, v);
  u.searchParams.delete("t");
  history[push ? "pushState" : "replaceState"](null, "", u);
  document.title = `${T.site.name}, ${span(T.dates)}, ${model} · GridSimEnv Desk`;
  try {
    stage = new GridStage($("stage"), D, { reduced, pixelRatio: Math.min(devicePixelRatio || 1, innerWidth < 700 ? 2 : 1.5) });
    stage.renderer.domElement.setAttribute("aria-hidden", "true");
    stage.onDirect = (on) => $("cam").setAttribute("aria-pressed", on);
    tags = anchors();
  } catch (err) {
    console.error(err);
    $("boot").querySelector("span").textContent = "This browser could not start WebGL; the desk on the right still replays.";
    return;
  }
  draw(0);
  requestAnimationFrame(() => $("boot").classList.add("gone"));
  window.gridsim.key = key;
  window.gridsim.resolveReady?.();
}

function plate(T, E, model) {
  const v = C.versions.find((x) => x.version === T.version);
  $("p-ver").textContent = v?.label || `${T.version} ${v?.name || ""}`;
  $("p-site").innerHTML = `${esc(T.site.name)}, ${esc(T.site.region)}<small>${esc(T.site.size)}</small>`;
  $("p-who").innerHTML = `<b>${esc(model)}</b> trades it ${T.dates.length > 1 ? "over" : "on"} ${esc(span(T.dates))}${T.site.pv ? `, beside ${Math.round(T.site.pv.mw_ac)} MW of solar <span class="mod">modelled</span>` : ""}`;
}

function seek(t) {
  S.t = Math.max(M.t0 - 0.01, Math.min(M.t1 + 1, t));
  S.hold = null;
}

function step(dt) {
  if (!S.playing || !M) return;
  if (S.hold) {
    S.hold.p += dt * S.speed;
    if (S.hold.p >= S.hold.turn.plan.total) S.hold = null;
    return;
  }
  const rate = (S.t < 0 ? RATE.pre : RATE.op) * S.speed;
  let t = S.t + dt * rate;
  const next = S.holdTurns ? M.turns.find((x) => x.t > S.t && x.t <= t) : null;
  if (next) {
    t = next.t;
    S.hold = { turn: next, p: 0 };
  }
  if (t >= M.t1 + 30) {
    t = M.t1 + 30;
    S.playing = false;
  }
  S.t = t;
}

let last = performance.now();
const fps = { n: 0, s: 0 };
function loop(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  S.wall += dt;
  step(dt);
  draw(dt);
  adapt(dt);
  requestAnimationFrame(loop);
}

/** One step down on a slow machine: after four seconds under 40 frames a second, render at a pixel ratio of 1. */
function adapt(dt) {
  if (!stage || document.hidden || fps.done || !$("boot").classList.contains("gone")) return;
  fps.n++;
  fps.s += dt;
  if (fps.s < 4) return;
  fps.done = true;
  if (fps.n / fps.s < 40 && stage.renderer.getPixelRatio() > 1) {
    stage.renderer.setPixelRatio(1);
    stage.composer.setPixelRatio(1);
    stage.resize();
  }
}

function draw(dt) {
  if (!M) return;
  panel.update(S);
  timeline.update(S);
  playIcon();
  holdPill();
  if (!stage) return;
  const th = Math.max(M.t0, Math.min(M.t1, S.t)) / 60;
  const f = stage.frame({ t: th, dt: S.hold ? dt * 0.35 : dt, wall: S.wall });
  place(f);
  weather(f);
}

function holdPill() {
  const h = $("hold"), model = SHORT[M.E.model] || M.E.name;
  let text = "";
  if (S.hold) {
    const p = S.hold.p, pl = S.hold.turn.plan, k = pl.steps.filter((s) => s <= p).length;
    text = pl.quote != null && p >= pl.quote ? `${model} ends its turn; the clock runs on` : k ? `${model} is working: call ${k} of ${pl.steps.length}` : `${model} wakes: ${S.hold.turn.why.map((r) => REASONS[r] || r).join(", ")}`;
  } else if (!S.playing && S.t < M.t1) text = "Paused";
  if (h.dataset.text !== text) {
    h.dataset.text = text;
    $("hold-text").textContent = text;
    h.classList.toggle("on", !!text);
    h.classList.toggle("paused", !S.hold);
  }
}

function playIcon() {
  const on = S.playing ? "1" : "0";
  if ($("play").dataset.on === on) return;
  $("play").dataset.on = on;
  $("play-icon").setAttribute("d", S.playing ? "M4 2.5h3v11H4zM9 2.5h3v11H9z" : "M4 2.5v11l9.5-5.5z");
  $("play").setAttribute("aria-label", S.playing ? "Pause" : "Play");
}

function anchors() {
  const L = stage.yard.layout, out = [];
  out.push({ kind: "yard", p: stage.toWorld(L.cx, 0).setY(8.5) });
  if (stage.plantL?.blocks?.length) {
    const c = stage.toWorld(L.cx, 0), dist = (b) => Math.hypot((b.x0 + b.x1) / 2 - c.x, (b.z0 + b.z1) / 2 - c.z);
    const bs = [...stage.plantL.blocks].sort((a, b) => dist(a) - dist(b)), b = bs[Math.floor(bs.length / 2)];
    const x = (b.x0 + b.x1) / 2, z = (b.z0 + b.z1) / 2;
    out.push({ kind: "pv", p: new THREE.Vector3(x, stage.terrain.heightAt(x, z) + 4, z) });
  }
  const host = $("tags");
  host.replaceChildren();
  for (const a of out) {
    a.el = document.createElement("div");
    a.el.className = `tag ${a.kind}`;
    a.el.innerHTML = `<div class="card"><div class="what"><i></i><span></span></div>${a.kind === "yard" ? '<div class="soc"><span class="bar"><b></b></span><span class="v"></span></div>' : ""}</div><div class="stem"></div>`;
    host.append(a.el);
  }
  return out;
}

const _v = new THREE.Vector3();
function place(f) {
  const r = stage.renderer.domElement.getBoundingClientRect(), narrow = r.width < 600;
  const b = M.battery(Math.max(M.t0, Math.min(M.t1, S.t)));
  for (const a of tags || []) {
    _v.copy(a.p).project(stage.camera);
    const vis = _v.z < 1 && _v.z > -1 && Math.abs(_v.x) < 1.05 && Math.abs(_v.y) < 1.05;
    let text = "", cls = "";
    if (a.kind === "yard") {
      text = b.pre ? "Waiting at its starting charge" : b.end ? "Window over" : b.mw > 1.5 ? `Discharging ${mwText(b.mw)}` : b.mw < -1.5 ? `Charging ${mwText(b.mw)}` : "Idle";
      cls = b.mw > 1.5 ? "discharge" : b.mw < -1.5 ? "charge" : "";
      const pct = Math.max(0, Math.min(1, b.soc / M.T.site.emax));
      const key = `${text}|${Math.round(pct * 200)}`;
      if (a.key !== key) {
        a.key = key;
        a.el.querySelector(".bar b").style.width = `${(100 * pct).toFixed(1)}%`;
        a.el.querySelector(".v").textContent = `${Math.round(100 * pct)}%`;
      }
    } else {
      const pv = M.pvAt(Math.max(M.t0, Math.min(M.t1 - 1, S.t))) ?? 0;
      text = f.s.el < -2 ? "Solar, night" : pv < 0.5 && f.x?.pvAvail > 0.5 ? "Solar stowed, price below zero" : `Solar ${mwText(pv)}`;
      cls = "pv";
    }
    a.x = ((_v.x + 1) / 2) * r.width;
    a.y = ((1 - _v.y) / 2) * r.height;
    a.show = vis && $("boot").classList.contains("gone");
    if (a.text !== text) (a.text = text), (a.el.querySelector(".what span").textContent = text);
    const c = `tag ${a.kind} ${cls}${narrow ? " small" : ""}`;
    if (a.cls !== c) (a.cls = c), (a.el.className = c);
  }
  const [y, pv] = tags || [];
  if (y && pv && y.show && pv.show && Math.abs(y.x - pv.x) < 190 && Math.abs(y.y - pv.y) < 90) pv.show = false;
  for (const a of tags || []) {
    a.el.style.display = a.show ? "" : "none";
    if (a.show) a.el.style.transform = `translate(${a.x}px, ${a.y}px) translate(-50%, -100%)`;
  }
}

function weather(f) {
  const t = Math.max(M.t0, Math.min(M.t1, S.t));
  const chips = [];
  const sky = f.w?.plain ? describe(f.w) : "";
  if (sky) chips.push(`<span>${esc(sky)}</span>`);
  if (D.front && Math.abs(t / 60 - D.front.t) < 2) chips.push(`<span class="alert">Cold front: ${Math.round(D.front.drop * 1.8)} °F colder in 3 hours</span>`);
  if (M.pv && D.frostAt(t / 60) > 0.5) chips.push('<span class="alert">Ice on the panels</span>');
  const seen = new Set(), alerts = M.alertsAt(t).filter((a) => !seen.has(a.kind + a.title) && seen.add(a.kind + a.title));
  for (const a of alerts.slice(0, small() ? 2 : 4)) chips.push(`<span class="alert ${a.kind}" title="${a.kind === "nws" ? "NWS" : "ERCOT"}, issued ${esc(when(M.d0, a.issued, t))}">${a.kind === "nws" ? "NWS " : "ERCOT "}${esc(a.title)}</span>`);
  for (const a of M.eventsAt(t)) chips.push(`<span class="alert ${a.kind}">${esc(a.title)}</span>`);
  const html = chips.join("");
  if ($("wx").dataset.html !== html) ($("wx").dataset.html = html), ($("wx").innerHTML = html);
}

const small = () => innerWidth < 700;

function controls() {
  $("play").addEventListener("click", toggle);
  $("speed").innerHTML = SPEEDS.map((s) => `<button type="button" data-s="${s}" aria-pressed="${s === S.speed}">${s === 0.5 ? "½" : s}×</button>`).join("");
  $("speed").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-s]");
    if (b) setSpeed(+b.dataset.s);
  });
  $("holdturns").addEventListener("change", (e) => {
    S.holdTurns = e.target.checked;
    if (!S.holdTurns) S.hold = null;
  });
  $("cam").addEventListener("click", () => stage?.direct(!stage.directing));
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea,[role=dialog]") || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.code === "Space") (e.preventDefault(), toggle());
    else if (e.key === "ArrowRight") (e.preventDefault(), jump(1));
    else if (e.key === "ArrowLeft") (e.preventDefault(), jump(-1));
    else if (e.key === "]" || e.key === "[") setSpeed(SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, SPEEDS.indexOf(S.speed) + (e.key === "]" ? 1 : -1)))]);
    else if (e.key === "c" || e.key === "C") stage?.direct(!stage.directing);
    else if (e.key === "e" || e.key === "E") sheet.show(current);
  });
  addEventListener("popstate", () => {
    const p = new URLSearchParams(location.search), k = keyOf(p.get("v"), p.get("m"), p.get("task"));
    if (k && k !== current) open(k);
  });
}

function toggle() {
  if (!M) return;
  if (S.t >= M.t1 && !S.playing) seek(M.t0 - 0.01);
  S.playing = !S.playing;
}

function setSpeed(s) {
  S.speed = s;
  for (const b of $("speed").querySelectorAll("button")) b.setAttribute("aria-pressed", +b.dataset.s === s);
}

function jump(dir) {
  const ts = M.wakes.map((w) => w.t);
  const t = dir > 0 ? ts.find((x) => x > S.t + 0.5) : [...ts].reverse().find((x) => x < S.t - 0.5);
  if (t == null) return seek(dir > 0 ? M.t1 : M.t0 - 0.01);
  seek(t - 0.01);
}

let readyResolve;
window.gridsim = {
  ready: new Promise((r) => (readyResolve = r)),
  resolveReady: () => readyResolve?.({ key: current, t0: M.t0, t1: M.t1, wakes: M.wakes.map((w) => w.t) }),
  seek(t, { hold = null } = {}) {
    seek(+t);
    S.playing = false;
    if (hold != null) {
      const turn = M.turns.find((x) => x.t === +t);
      if (turn) S.hold = { turn, p: hold };
    }
    draw(1 / 30);
    return new Promise((r) => requestAnimationFrame(() => r(S.t)));
  },
  async settle(frames = 30) {
    for (let i = 0; i < frames; i++) {
      S.wall += 1 / 30;
      draw(1 / 30);
      await new Promise((r) => requestAnimationFrame(r));
    }
  },
  state: () => ({ t: S.t, playing: S.playing, hold: !!S.hold, ...(stage ? stage.state() : {}) }),
  get stage() {
    return stage;
  },
  play: (speed = 1) => (setSpeed(speed), (S.playing = true)),
  pause: () => (S.playing = false),
  open: (k) => open(k),
};

main().catch((e) => {
  console.error(e);
  $("boot").querySelector("span").textContent = `The replay could not load: ${e.message}`;
});
