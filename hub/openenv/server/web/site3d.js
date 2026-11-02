/** The battery site in 3D for a live episode: the viewer's stage (GridStage) on a scene built from what the episode has
 * run so far, the battery's metered output and charge and the weather observed at the airport, never past the desk's
 * minute. The scene is rebuilt after each wake-up; the stage itself only when the weather adds a front or a freeze. */
import * as THREE from "three";
import { sceneOf } from "gridsim/desk/scene.js";
import { buildDirector } from "gridsim/stage/director.js";
import { GridStage } from "gridsim/stage/stage.js";
import { describe } from "gridsim/stage/weather.js";

export const CAMS = [["", "Director"], ["establish", "Site"], ["high", "Overhead"], ["push", "Close"], ["line", "Line"]];

export class Site {
  constructor(host, card, { reduced = false } = {}) {
    this.host = host;
    this.card = card;
    this.reduced = reduced;
    this.stage = null;
    this.sig = "";
    this.force = "";
    this.n = card.dates.length;
  }

  /** The scene for the episode as far as `view` goes. */
  scene(view) {
    const c = this.card, n = this.n, K = 288 * n;
    const T = {
      task: c.task_id, dates: c.dates, t0: -1080, t1: 1440 * n, pv: null, place: { lat: c.place.lat, lon: c.place.lon },
      site: { ...c.site, pv: c.site.pv || null }, prices: { lmp: new Array(K).fill(0) }, alerts: [],
      weather: { source: "IEM ASOS", obs: view.weather },
    };
    const m = view.m.concat(new Array(Math.max(0, K - view.m.length)).fill(0));
    const last = view.soc.at(-1) ?? c.site.soc0;
    const soc = view.soc.concat(new Array(Math.max(0, K + 1 - view.soc.length)).fill(last));
    const E = { m, soc, as: view.as, wakes: view.wakes.map(([t, why]) => [t, why]) };
    return sceneOf(T, E);
  }

  update(view) {
    const D = this.scene(view);
    const sig = `${D.front ? 1 : 0}${D.cold ? 1 : 0}`;
    if (!this.stage || sig !== this.sig) return this.rebuild(D, sig);
    const s = this.stage;
    s.d = D;
    s.director = buildDirector(D, s.yard.layout, { night: (t) => night(s, t), plant: s.plantL, yaw: s.yaw });
    return false;
  }

  rebuild(D, sig) {
    const cam = this.stage ? { p: this.stage.camera.position.clone(), q: this.stage.camera.quaternion.clone(), directing: this.stage.directing } : null;
    this.stage?.dispose();
    this.stage = new GridStage(this.host, D, { reduced: this.reduced, pixelRatio: Math.min(devicePixelRatio || 1, innerWidth < 700 ? 2 : 1.5) });
    this.stage.renderer.domElement.setAttribute("aria-hidden", "true");
    this.stage.force = this.force || null;
    this.stage.onDirect = (on) => this.onDirect?.(on);
    if (cam && !cam.directing) {
      this.stage.direct(false);
      this.stage.camera.position.copy(cam.p);
      this.stage.camera.quaternion.copy(cam.q);
    }
    this.sig = sig;
    this.anchor = null;
    return true;
  }

  camera(kind) {
    this.force = kind;
    if (!this.stage) return;
    this.stage.force = kind || null;
    this.stage.direct(true);
  }

  /** Renders minute t; returns what the frame showed (the sun, the weather, the battery). */
  frame(t, dt, wall) {
    if (!this.stage) return null;
    this.stage.drift = this.force ? 0.5 + 0.5 * Math.sin(wall * 0.06) : null;
    return this.stage.frame({ t: t / 60, dt, wall });
  }

  /** The yard's place on screen, for the battery's tag. */
  yard() {
    const s = this.stage;
    if (!s) return null;
    this.anchor ||= s.toWorld(s.yard.layout.cx, 0).setY(8.5);
    const r = s.renderer.domElement.getBoundingClientRect();
    _v.copy(this.anchor).project(s.camera);
    const vis = _v.z < 1 && _v.z > -1 && Math.abs(_v.x) < 1.05 && Math.abs(_v.y) < 1.05;
    return { x: ((_v.x + 1) / 2) * r.width, y: ((1 - _v.y) / 2) * r.height, vis };
  }

  sky(f) {
    return f?.w?.plain ? describe(f.w) : "";
  }

  dispose() {
    this.stage?.dispose();
    this.stage = null;
  }
}

const _v = new THREE.Vector3();
const night = (s, t) => 1 - Math.min(1, Math.max(0, (s.sky.sunAt(t).el + 6) / 8));
