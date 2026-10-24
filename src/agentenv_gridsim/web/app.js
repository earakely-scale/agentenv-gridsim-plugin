import { load } from "./data.js";
import { HYBRID_SCHEMA, loadHybrid } from "./hybrid.js";
import { LIVE_SCHEMA, loadLive } from "./live.js";
import { GridStage } from "./stage/stage.js";
import { buildCharts } from "./ui/charts.js";
import { buildHybridCharts } from "./ui/chartshybrid.js";
import { buildLiveCharts } from "./ui/chartslive.js";
import { buildHud } from "./ui/hud.js";
import { buildHybridHud } from "./ui/hudhybrid.js";
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
  if (q.has("levelup") || q.has("race")) {
    const { trainView } = await import("./ui/train.js");
    return trainView(app, q);
  }
  const epUrl = q.get("episode");
  if (!epUrl) {
    const { picker } = await import("./ui/picker.js");
    await picker(app, q);
    window.gridsim = { ready: Promise.resolve({ list: true, shots: [] }) };
    return;
  }
  const ep = await json(epUrl);
  const v4 = ep.schema === "gridsim.episode/v4";
  const wxUrl = q.get("weather") || `${q.get("wxbase") || "weather"}/${v4 ? `${ep.task.d1}_${ep.task.settlement_point}_${ep.task.days}d` : `${ep.task.date}_${ep.task.settlement_point}`}.json`;
  const weather = await json(wxUrl).catch(() => null);
  const F = v4 ? await Promise.all([import("./forecast.js"), import("./ui/hudforecast.js"), import("./ui/chartsforecast.js")]) : null;
  const hybrid = ep.schema === HYBRID_SCHEMA || v4;
  const live = ep.schema === LIVE_SCHEMA || hybrid;
  const d = v4 ? F[0].buildForecast(ep, weather) : hybrid ? loadHybrid(ep, weather) : live ? loadLive(ep, weather) : load(ep, weather);
  const END = d.end ?? 24, START = v4 ? d.t0 : INTRO;
  const manual = q.has("record");
  const reduced = q.has("reduced") ? q.get("reduced") !== "0" : matchMedia("(prefers-reduced-motion: reduce)").matches;
  app.innerHTML = "";
  const root = document.createElement("div");
  root.className = "ep";
  const host = document.createElement("div");
  host.className = "stage-host";
  root.append(host);
  app.append(root);
  document.title = v4 ? `${ep.task.settlement_point} ${ep.task.d1} weather front · GridSimEnv` : `${ep.task.settlement_point} ${ep.task.date}${hybrid ? " solar + storage" : live ? " live" : ""} · GridSimEnv`;
  root.classList.toggle("is-live", live);
  root.classList.toggle("is-hybrid", hybrid);
  root.classList.toggle("is-forecast", v4);
  const stage = new GridStage(host, d, { manual, reduced });
  stage.force = q.get("shot");
  const P = { t: q.has("hour") ? +q.get("hour") - 0.5 : q.has("t") ? +q.get("t") : START, playing: !manual && !q.has("t") && !q.has("hour"), speed: 1, wall: 0 };
  if (q.has("ui") && q.get("ui") === "0") root.classList.add("bare");
  const charts = (v4 ? F[2].buildForecastCharts : hybrid ? buildHybridCharts : live ? buildLiveCharts : buildCharts)(root, d);
  const intro = live ? { update() {} } : buildIntro(root, d);
  const sound = buildSound();
  const settings = document.createElement("section");
  settings.className = "card settings";
  settings.hidden = true;
  settings.innerHTML = `<h5>Settings</h5><label><input type="checkbox" name="reduced" ${reduced ? "checked" : ""}> Reduced motion</label><label><input type="checkbox" name="sound"> Sound (transformer hum)</label><label><input type="checkbox" name="ghosts" checked> ${v4 ? "The naive DAM bidder" : hybrid ? "Energy-only and AS-hog" : "Greedy and threshold"} ghosts in the race</label><p class="dim" style="font-size:12px;margin:6px 0 0">Keys: space play/pause · ←/→ hour${live ? " · [/] watch" : ""} · 1-4 speed · D camera · C charts</p>`;
  root.append(settings);
  root.classList.toggle("reduced", reduced);
  settings.querySelector('[name="reduced"]').addEventListener("change", (e) => ((stage.reduced = e.target.checked), root.classList.toggle("reduced", e.target.checked)));
  settings.querySelector('[name="sound"]').addEventListener("change", (e) => sound.set(e.target.checked));
  settings.querySelector('[name="ghosts"]').addEventListener("change", (e) => root.classList.toggle("no-ghosts", !e.target.checked));
  const hud = (v4 ? F[1].buildForecastHud : hybrid ? buildHybridHud : live ? buildLiveHud : buildHud)(root, d, {
    onSeek: (t) => ((P.t = t), stage.direct(stage.directing)),
    onToggle: (a, s) => {
      if (a === "play") P.playing = !P.playing, P.t >= END && P.playing && (P.t = START);
      else if (a === "speed") P.speed = s;
      else if (a === "director") stage.direct(!stage.directing);
      else if (a === "charts") charts.toggle();
      else if (a === "settings") settings.hidden = !settings.hidden;
      else if (a === "link") {
        const u = new URL(location.href);
        u.searchParams.delete("t");
        u.searchParams.set("hour", String(Math.min(END, Math.max(1, Math.floor(P.t) + 1))));
        history.replaceState(null, "", u);
        navigator.clipboard?.writeText(u.href).catch(() => {});
      }
    },
  });
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea")) return;
    if (e.code === "Space") (P.playing = !P.playing), e.preventDefault();
    else if (e.key === "ArrowRight") P.t = Math.min(END, Math.floor(P.t) + 1 + 0.02);
    else if (e.key === "ArrowLeft") P.t = Math.max(v4 ? START : 0, Math.floor(P.t - 0.02) - 1 + 0.02);
    else if (["1", "2", "3", "4"].includes(e.key)) P.speed = [0.5, 1, 2, 4][+e.key - 1];
    else if (live && (e.key === "]" || e.key === "[")) {
      const ts = d.watches.map((w) => (v4 ? w.t : Math.max(0, w.t)));
      P.t = e.key === "]" ? ts.find((x) => x > P.t + 0.01) ?? P.t : [...ts].reverse().find((x) => x < P.t - 0.01) ?? 0;
      stage.direct(stage.directing);
    } else if (e.key === "d" || e.key === "D") stage.direct(!stage.directing);
    else if (e.key === "c" || e.key === "C") charts.toggle();
  });
  if (q.get("charts") === "1") charts.toggle(true);
  const blindHidden = !live && d.ep.tier === "blind";
  const draw = (dt) => {
    const f = stage.frame({ t: live ? P.t : Math.max(0, P.t), dt, wall: P.wall });
    hud.update(P.t, { playing: P.playing, speed: P.speed, directing: stage.directing });
    charts.update(P.t);
    intro.update(P.t);
    root.classList.toggle("blind-hidden", blindHidden && P.t < 0);
    sound.level(f.mode === "charge" || f.mode === "discharge" ? Math.abs(f.x.mw) / d.b.p_dis_mw : 0);
  };
  window.gridsim = {
    ready: Promise.resolve({ point: ep.task.settlement_point, date: ep.task.date ?? ep.task.d1, shots: stage.director.shots, ...(v4 ? { start: START, end: END, front: d.front } : {}) }),
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
        P.t += v4 ? dt * P.speed * (P.t < 0 ? 1.6 : 0.85) : (dt * P.speed) / SECONDS_PER_HOUR;
        if (P.t >= END + 1.5) P.playing = false;
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
