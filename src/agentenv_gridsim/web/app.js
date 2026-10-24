import { load } from "./data.js";
import { LIVE_SCHEMA, loadLive } from "./live.js";
import { GridStage } from "./stage/stage.js";
import { buildCharts } from "./ui/charts.js";
import { buildLiveCharts } from "./ui/chartslive.js";
import { buildHud } from "./ui/hud.js";
import { buildLiveHud } from "./ui/hudlive.js";
import { buildIntro } from "./ui/intro.js";
import { buildSound } from "./ui/sound.js";

const SECONDS_PER_HOUR = 3;
const INTRO = -2;
const FPS = { n: 0, t0: performance.now() };
const q = new URLSearchParams(location.search);
const app = document.getElementById("app");

async function json(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function main() {
  const epUrl = q.get("episode");
  if (!epUrl) {
    const { picker } = await import("./ui/picker.js");
    await picker(app, q);
    window.gridsim = { ready: Promise.resolve({ list: true, shots: [] }) };
    return;
  }
  const ep = await json(epUrl);
  const wxUrl = q.get("weather") || `${q.get("wxbase") || "weather"}/${ep.task.date}_${ep.task.settlement_point}.json`;
  const weather = await json(wxUrl).catch(() => null);
  const live = ep.schema === LIVE_SCHEMA;
  const d = live ? loadLive(ep, weather) : load(ep, weather);
  const manual = q.has("record");
  const reduced = q.has("reduced") ? q.get("reduced") !== "0" : matchMedia("(prefers-reduced-motion: reduce)").matches;
  app.innerHTML = "";
  const root = document.createElement("div");
  root.className = "ep";
  const host = document.createElement("div");
  host.className = "stage-host";
  root.append(host);
  app.append(root);
  document.title = `${ep.task.settlement_point} ${ep.task.date}${live ? " live" : ""} · GridSimEnv`;
  root.classList.toggle("is-live", live);
  const stage = new GridStage(host, d, { manual, reduced });
  stage.force = q.get("shot");
  const P = { t: q.has("hour") ? +q.get("hour") - 0.5 : q.has("t") ? +q.get("t") : INTRO, playing: !manual && !q.has("t") && !q.has("hour"), speed: 1, wall: 0 };
  if (q.has("ui") && q.get("ui") === "0") root.classList.add("bare");
  const charts = (live ? buildLiveCharts : buildCharts)(root, d);
  const intro = live ? { update() {} } : buildIntro(root, d);
  const sound = buildSound();
  const settings = document.createElement("section");
  settings.className = "card settings";
  settings.hidden = true;
  settings.innerHTML = `<h5>Settings</h5><label><input type="checkbox" name="reduced" ${reduced ? "checked" : ""}> Reduced motion</label><label><input type="checkbox" name="sound"> Sound (transformer hum)</label><label><input type="checkbox" name="ghosts" checked> Greedy and threshold ghosts in the race</label><p class="dim" style="font-size:12px;margin:6px 0 0">Keys: space play/pause · ←/→ hour · 1-4 speed · D camera · C charts</p>`;
  root.append(settings);
  settings.querySelector('[name="reduced"]').addEventListener("change", (e) => (stage.reduced = e.target.checked));
  settings.querySelector('[name="sound"]').addEventListener("change", (e) => sound.set(e.target.checked));
  settings.querySelector('[name="ghosts"]').addEventListener("change", (e) => root.classList.toggle("no-ghosts", !e.target.checked));
  const hud = (live ? buildLiveHud : buildHud)(root, d, {
    onSeek: (t) => ((P.t = t), stage.direct(stage.directing)),
    onToggle: (a, s) => {
      if (a === "play") P.playing = !P.playing, P.t >= 24 && P.playing && (P.t = INTRO);
      else if (a === "speed") P.speed = s;
      else if (a === "director") stage.direct(!stage.directing);
      else if (a === "charts") charts.toggle();
      else if (a === "settings") settings.hidden = !settings.hidden;
      else if (a === "link") {
        const u = new URL(location.href);
        u.searchParams.delete("t");
        u.searchParams.set("hour", String(Math.min(24, Math.max(1, Math.floor(P.t) + 1))));
        history.replaceState(null, "", u);
        navigator.clipboard?.writeText(u.href).catch(() => {});
      }
    },
  });
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea")) return;
    if (e.code === "Space") (P.playing = !P.playing), e.preventDefault();
    else if (e.key === "ArrowRight") P.t = Math.min(24, Math.floor(P.t) + 1 + 0.02);
    else if (e.key === "ArrowLeft") P.t = Math.max(0, Math.floor(P.t - 0.02) - 1 + 0.02);
    else if (["1", "2", "3", "4"].includes(e.key)) P.speed = [0.5, 1, 2, 4][+e.key - 1];
    else if (e.key === "d" || e.key === "D") stage.direct(!stage.directing);
    else if (e.key === "c" || e.key === "C") charts.toggle();
  });
  if (q.get("charts") === "1") charts.toggle(true);
  const blindHidden = !live && d.ep.tier === "blind";
  const draw = (dt) => {
    const f = stage.frame({ t: Math.max(0, P.t), dt, wall: P.wall });
    hud.update(P.t, { playing: P.playing, speed: P.speed, directing: stage.directing });
    charts.update(P.t);
    intro.update(P.t);
    root.classList.toggle("blind-hidden", blindHidden && P.t < 0);
    sound.level(f.mode === "charge" || f.mode === "discharge" ? Math.abs(f.x.mw) / d.b.p_dis_mw : 0);
  };
  window.gridsim = {
    ready: Promise.resolve({ point: ep.task.settlement_point, date: ep.task.date, shots: stage.director.shots }),
    async time(t, { dt = 1 / 30 } = {}) {
      P.t = +t;
      P.wall += dt;
      draw(dt);
      await new Promise((r) => requestAnimationFrame(() => r()));
      return P.t;
    },
    state: () => ({ t: P.t, ...stage.state() }),
    fps: () => FPS.n / Math.max(1e-3, (performance.now() - FPS.t0) / 1000),
    play: (speed = 1) => ((P.playing = true), (P.speed = speed), (FPS.n = 0), (FPS.t0 = performance.now())),
    stage,
  };
  if (!manual) {
    let last = performance.now();
    const loop = (now) => {
      FPS.n++;
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      P.wall += dt;
      if (P.playing) {
        P.t += (dt * P.speed) / SECONDS_PER_HOUR;
        if (P.t >= 25.5) P.playing = false;
      }
      draw(dt);
      requestAnimationFrame(loop);
    };
    requestAnimationFrame(loop);
  } else draw(0);
}

main().catch((e) => {
  console.error(e);
  app.innerHTML = `<div class="error"><p>Could not load this replay.</p><pre>${String(e.stack || e)}</pre></div>`;
});
