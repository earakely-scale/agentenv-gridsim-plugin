import { load } from "./data.js";
import { GridStage } from "./stage/stage.js";
import { buildHud } from "./ui/hud.js";

const SECONDS_PER_HOUR = 3;
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
    return picker(app, q);
  }
  const ep = await json(epUrl);
  const wxUrl = q.get("weather") || `${q.get("wxbase") || "weather"}/${ep.task.date}_${ep.task.settlement_point}.json`;
  const weather = await json(wxUrl).catch(() => null);
  const d = load(ep, weather);
  const manual = q.has("record");
  const reduced = q.has("reduced") ? q.get("reduced") !== "0" : matchMedia("(prefers-reduced-motion: reduce)").matches;
  app.innerHTML = "";
  const root = document.createElement("div");
  root.className = "ep";
  const host = document.createElement("div");
  host.className = "stage-host";
  root.append(host);
  app.append(root);
  document.title = `${ep.task.settlement_point} ${ep.task.date} · GridSimEnv`;
  const stage = new GridStage(host, d, { manual, reduced });
  stage.force = q.get("shot");
  const P = { t: q.has("hour") ? +q.get("hour") - 0.5 : q.has("t") ? +q.get("t") : 0, playing: !manual && !q.has("t") && !q.has("hour"), speed: 1, wall: 0 };
  if (q.has("ui") && q.get("ui") === "0") root.classList.add("bare");
  const hud = buildHud(root, d, {
    onSeek: (t) => ((P.t = t), stage.direct(stage.directing)),
    onToggle: (a, s) => {
      if (a === "play") P.playing = !P.playing, P.t >= 24 && P.playing && (P.t = 0);
      else if (a === "speed") P.speed = s;
      else if (a === "director") stage.direct(!stage.directing);
    },
  });
  addEventListener("keydown", (e) => {
    if (e.target.closest?.("input,select,textarea")) return;
    if (e.code === "Space") (P.playing = !P.playing), e.preventDefault();
    else if (e.key === "ArrowRight") P.t = Math.min(24, Math.floor(P.t) + 1 + 0.02);
    else if (e.key === "ArrowLeft") P.t = Math.max(0, Math.floor(P.t - 0.02) - 1 + 0.02);
    else if (["1", "2", "3", "4"].includes(e.key)) P.speed = [0.5, 1, 2, 4][+e.key - 1];
    else if (e.key === "d" || e.key === "D") stage.direct(!stage.directing);
  });
  const draw = (dt) => {
    stage.frame({ t: P.t, dt, wall: P.wall });
    hud.update(P.t, { playing: P.playing, speed: P.speed, directing: stage.directing });
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
    stage,
  };
  if (!manual) {
    let last = performance.now();
    const loop = (now) => {
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
