/** The v5 Market Floor replay page: the room and the field (stage/marketstage.js), the cards (ui/hudmarket.js) and the
 * charts drawer over one gridsim.episode/v5, played from 6 am the day before through the operating day. */
import { loadMarket, T0 } from "./market.js";
import { MarketStage } from "./stage/marketstage.js";
import { buildMarketCharts } from "./ui/chartsmarket.js";
import { buildMarketHud, marketCss } from "./ui/hudmarket.js";
import { buildSound } from "./ui/sound.js";

const SECONDS_PER_HOUR = 3;
const FPS = { n: 0, t0: performance.now() };

export async function marketApp(app, q, ep) {
  const wxUrl = q.get("weather") || `${q.get("wxbase") || "weather"}/${ep.task.date}_${ep.task.point}_d1.json`;
  const [weather] = await Promise.all([fetch(wxUrl).then((r) => (r.ok ? r.json() : null)).catch(() => null), marketCss()]);
  const d = loadMarket(ep, weather);
  const manual = q.has("record");
  const reduced = q.has("reduced") ? q.get("reduced") !== "0" : matchMedia("(prefers-reduced-motion: reduce)").matches;
  app.innerHTML = "";
  const root = document.createElement("div");
  root.className = "ep is-live is-market";
  const host = document.createElement("div");
  host.className = "stage-host";
  root.append(host);
  app.append(root);
  document.title = `${ep.task.date} The Market Floor · GridSimEnv`;
  const stage = new MarketStage(host, d, { manual, reduced });
  stage.force = q.get("shot");
  const start = q.has("hour") ? +q.get("hour") - 0.5 : q.has("t") ? +q.get("t") : T0;
  const P = { t: start, playing: !manual && !q.has("t") && !q.has("hour"), speed: 1, wall: 0 };
  if (q.get("ui") === "0") root.classList.add("bare"), (stage.bare = true);
  const charts = buildMarketCharts(root, d);
  const sound = buildSound();
  const settings = document.createElement("section");
  settings.className = "card settings";
  settings.hidden = true;
  settings.innerHTML = `<h5>Settings</h5><label><input type="checkbox" name="reduced" ${reduced ? "checked" : ""}> Reduced motion</label><label><input type="checkbox" name="sound"> Sound (transformer hum)</label><label><input type="checkbox" name="tags" checked> Seat tags in the field</label><p class="dim" style="font-size:12px;margin:6px 0 0">Keys: space play/pause · ←/→ hour · [/] watch · 1-4 speed · D camera · C charts</p>`;
  root.append(settings);
  root.classList.toggle("reduced", reduced);
  settings.querySelector('[name="reduced"]').addEventListener("change", (e) => ((stage.reduced = e.target.checked), root.classList.toggle("reduced", e.target.checked)));
  settings.querySelector('[name="sound"]').addEventListener("change", (e) => sound.set(e.target.checked));
  settings.querySelector('[name="tags"]').addEventListener("change", (e) => (stage.bare = !e.target.checked));
  const hud = buildMarketHud(root, d, {
    onSeek: (t) => ((P.t = t), stage.direct(stage.directing)),
    onToggle: (a, s) => {
      if (a === "play") P.playing = !P.playing, P.t >= 24 && P.playing && (P.t = T0);
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
    else if (e.key === "ArrowLeft") P.t = Math.max(T0, Math.floor(P.t - 0.02) - 1 + 0.02);
    else if (["1", "2", "3", "4"].includes(e.key)) P.speed = [0.5, 1, 2, 4][+e.key - 1];
    else if (e.key === "]" || e.key === "[") {
      const ts = [...d.watches.map((w) => w.t), d.closeT, d.awardsT].sort((a, b) => a - b);
      P.t = e.key === "]" ? ts.find((x) => x > P.t + 0.01) ?? P.t : [...ts].reverse().find((x) => x < P.t - 0.01) ?? T0;
      stage.direct(stage.directing);
    } else if (e.key === "d" || e.key === "D") stage.direct(!stage.directing);
    else if (e.key === "c" || e.key === "C") charts.toggle();
  });
  if (q.get("charts") === "1") charts.toggle(true);
  const draw = (dt) => {
    const f = stage.frame({ t: P.t, dt, wall: P.wall });
    hud.update(P.t, { playing: P.playing, speed: P.speed, directing: stage.directing, shot: f.shot, inRoom: f.inRoom, hour: stage.wallHour });
    charts.update(P.t);
    sound.level(f.mode === "charge" || f.mode === "discharge" ? Math.abs(f.x.mw) / d.P : 0);
  };
  window.gridsim = {
    ready: Promise.resolve({ point: ep.task.point, date: ep.task.date, shots: stage.shots, t0: T0 }),
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
