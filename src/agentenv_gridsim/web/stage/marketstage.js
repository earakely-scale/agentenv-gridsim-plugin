/** The Market Floor in 3D: the QSE's trading room (floor.js) for the day before, and out in the field the assets the
 * five seats run, in the place's real light and weather: seat A's battery yard at the hub, the rival's yard, gas-G's
 * peakers, renew-R's trackers and wind farm, and the city retail-L serves. The director cuts between room and field
 * at the moments that matter (the 10:00 close, the awards, the operating day's peaks, a mitigation, a CfD). */
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { marketMin, marketT, SEAT } from "../market.js";
import { buildBackdrop } from "./backdrop.js";
import { buildDirector } from "./director.js";
import { buildPeakers, buildSolarBlock, tag } from "./field.js";
import { buildFloor } from "./floor.js";
import { buildLine } from "./line.js";
import { buildSky } from "./sky.js";
import { buildTerrain } from "./terrain.js";
import { buildRain, describe, lightningAt, weatherAt } from "./weather.js";
import { buildYard, COLORS } from "./yard.js";

const DEG = Math.PI / 180;
const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));
const smooth = (a, b, x) => ease((x - a) / (b - a));
/** Where the other seats stand, site-local (x toward the hub and the city along seat A's gen-tie). */
const SPOT = { B: [-140, -640], G: [760, -340], R: [-760, 560] };
const ROOM_SHOTS = new Set(["room", "desk", "wall", "merit", "clock", "prices", "deal", "window"]);
const PRIORITY = { mitigated: 7, deal: 6.5, gas: 5, city: 5, ramp: 4.6, push: 4, solar: 3.5, byard: 3.2, desk: 3, wind: 2.5, establish: 1, high: 1, line: 1.5 };

export class MarketStage {
  constructor(container, d, { manual = false, reduced = false, pixelRatio = Math.min(globalThis.devicePixelRatio || 1, 2) } = {}) {
    this.d = d;
    this.container = container;
    this.manual = manual;
    this.reduced = reduced;
    this.directing = true;
    this.frameMs = [];
    const r = (this.renderer = new THREE.WebGLRenderer({ antialias: true, reverseDepthBuffer: true, preserveDrawingBuffer: manual, powerPreference: "high-performance" }));
    r.setPixelRatio(pixelRatio);
    r.shadowMap.enabled = true;
    r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.info.autoReset = false;
    r.domElement.className = "stage-canvas";
    container.appendChild(r.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.3, 120000);
    this.roomCam = new THREE.PerspectiveCamera(50, 1, 0.05, 120000);
    this.#build();
    this.resize();
    addEventListener("resize", () => this.resize());
  }

  #build() {
    const { d, scene, renderer } = this;
    const region = d.region, seed = `market-${d.task.date}`;
    this.yaw = Math.PI / 2 - region.line * DEG;
    this.sky = buildSky(renderer, scene, { date: d.task.date, lat: d.place.lat, lon: d.place.lon, region });
    const U = (this.U = { uWet: { value: 0 }, uSnow: { value: 0 } });
    this.site = new THREE.Group();
    this.site.rotation.y = this.yaw;
    this.yard = buildYard(d.b, U, { gravel: region.gravel, road: region.road, seed });
    const L = this.yard.layout;
    const toWorld = (this.toWorld = (lx, lz) => new THREE.Vector3(lx, 0, lz).applyAxisAngle(new THREE.Vector3(0, 1, 0), this.yaw));
    const toLocal = (x, z) => new THREE.Vector3(x, 0, z).applyAxisAngle(new THREE.Vector3(0, 1, 0), -this.yaw);
    const bb = { energy_mwh: d.bat.e, p_dis_mw: d.bat.p, p_ch_mw: d.bat.p, soc_levels: 8, s0: (d.bat.s0 / d.bat.e) * 8, s_end_min: 0 };
    this.yardB = buildYard(bb, U, { gravel: region.gravel, road: region.road, seed: `${seed}-B` });
    const LB = this.yardB.layout;
    const nUnits = d.gUnits || Math.max(4, Math.round(d.gMw / 45));
    const solarRows = 64;
    const pads = [
      { c: SPOT.B, x0: LB.pad.x0 - 30, x1: LB.pad.x1 + 40, z0: LB.pad.z0 - 30, z1: LB.pad.z1 + 30 },
      { c: SPOT.G, x0: -((Math.ceil(nUnits / 2) * 26 + 70) / 2) - 40, x1: (Math.ceil(nUnits / 2) * 26 + 70) / 2 + 40, z0: -110, z1: 110 },
      { c: SPOT.R, x0: -solarRows * 3.4 - 50, x1: solarRows * 3.4 + 50, z0: -150, z1: 150, world: true },
    ];
    const inPad = (lx, lz, m) => pads.find((p) => {
      let x = lx - p.c[0], z = lz - p.c[1];
      if (p.world) {
        const cw = toWorld(...p.c), w = toWorld(lx, lz);
        x = w.x - cw.x;
        z = w.z - cw.z;
      }
      return x > p.x0 - m && x < p.x1 + m && z > p.z0 - m && z < p.z1 + m;
    });
    const level = (x, z) => {
      const l = toLocal(x, z);
      if (inPad(l.x, l.z, 30)) return 1;
      for (const [m, v] of [[60, 0.85], [100, 0.6], [150, 0.35], [210, 0.15]]) if (inPad(l.x, l.z, m)) return v;
      return 0;
    };
    const keepOut = (x, z) => {
      const l = toLocal(x, z);
      return !!inPad(l.x, l.z, 20) || (Math.abs(l.z - SPOT.B[1]) < 40 && l.x > SPOT.B[0]);
    };
    this.director = buildDirector(d, L, { night: (t) => 1 - Math.min(1, Math.max(0, (this.sky.sunAt(t).el + 6) / 8)) });
    const cams = this.director.spots.map(([x, z, r]) => {
      const v = toWorld(x, z);
      return [v.x, v.z, r];
    });
    this.terrain = buildTerrain(region, { pad: L.pad, yaw: this.yaw, seed, cams, level, keepOut });
    this.terrain.U.uWet = U.uWet;
    scene.add(this.terrain.group);
    const heightLocal = (lx, lz) => {
      const w = toWorld(lx, lz);
      return this.terrain.heightAt(w.x, w.z);
    };
    this.line = buildLine({ deadEnd: this.yard.sub.deadEnd, heightLocal, km: 9, seed });
    this.site.add(this.yard.group, this.line.group);
    const bGroup = new THREE.Group();
    bGroup.position.set(SPOT.B[0], 0, SPOT.B[1]);
    this.lineB = buildLine({ deadEnd: this.yardB.sub.deadEnd, heightLocal: (x, z) => heightLocal(x + SPOT.B[0], z + SPOT.B[1]), km: 5, seed: `${seed}-B` });
    bGroup.add(this.yardB.group, this.lineB.group);
    this.site.add(bGroup);
    this.gas = buildPeakers(nUnits, U, { at: SPOT.G });
    this.site.add(this.gas.group);
    const rw = toWorld(...SPOT.R);
    this.solar = buildSolarBlock(U, { at: [rw.x, rw.z], rows: solarRows });
    scene.add(this.solar.group);
    scene.add(this.site);
    this.backdrop = buildBackdrop(region, this.terrain.heightAt, this.terrain.avoid, seed, { near: [] });
    scene.add(this.backdrop.group);
    this.rain = buildRain();
    scene.add(this.rain.mesh);
    const cityB = region.city.bearing * DEG, cityM = region.city.km * 1000;
    this.tags = {
      A: [tag("A", SEAT.A.color), toWorld(L.cx, 0).setY(12)],
      B: [tag("B", SEAT.B.color), toWorld(SPOT.B[0] + LB.cx, SPOT.B[1]).setY(12)],
      G: [tag("G", SEAT.G.color), toWorld(...SPOT.G).setY(34)],
      R: [tag("R", SEAT.R.color), new THREE.Vector3(rw.x, 14, rw.z)],
      L: [tag("L", SEAT.L.color), new THREE.Vector3(Math.sin(cityB) * cityM, 320, -Math.cos(cityB) * cityM)],
    };
    for (const [sp, p] of Object.values(this.tags)) {
      sp.position.copy(p);
      sp.visible = false;
      scene.add(sp);
    }
    this.nUnits = nUnits;
    this.room = buildFloor(d, { sky: this.sky, fog: scene.fog, background: scene.background });
    this.shots = shotList(d, (t) => 1 - Math.min(1, Math.max(0, (this.sky.sunAt(marketMin(t) / 60).el + 6) / 8)));
    this.#post();
    if (!this.manual) {
      this.controls = new OrbitControls(this.camera, renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.maxPolarAngle = 1.52;
      this.controls.minDistance = 4;
      this.controls.maxDistance = 6000;
      this.controls.addEventListener("start", () => this.direct(false));
    }
    this.L = L;
    this.LB = LB;
  }

  #post() {
    const r = this.renderer;
    const size = r.getDrawingBufferSize(new THREE.Vector2());
    const rt = new THREE.WebGLRenderTarget(size.x || 1, size.y || 1, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(r, rt);
    this.pass = new RenderPass(this.scene, this.camera);
    this.composer.addPass(this.pass);
    this.grade = new ShaderPass({
      uniforms: { tDiffuse: { value: null }, uNight: { value: 0 } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: /* glsl */ `
        uniform sampler2D tDiffuse;
        uniform float uNight;
        varying vec2 vUv;
        void main() {
          vec4 c = texture2D(tDiffuse, vUv);
          if (any(isnan(c)) || any(isinf(c))) c = vec4(0.0, 0.0, 0.0, 1.0);
          float l = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
          c.rgb = mix(c.rgb, l * vec3(0.9, 0.97, 1.12), uNight * 0.32 * (1.0 - smoothstep(0.4, 3.0, l)));
          gl_FragColor = min(c, vec4(80.0));
        }`,
    });
    this.composer.addPass(this.grade);
    this.bloom = new UnrealBloomPass(new THREE.Vector2(size.x || 1, size.y || 1), 0.5, 0.55, 1.4);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
  }

  direct(on) {
    this.directing = on;
    this.onDirect?.(on);
  }

  resize() {
    const w = this.container.clientWidth || innerWidth, h = this.container.clientHeight || innerHeight;
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "100%";
    for (const c of [this.camera, this.roomCam]) {
      c.aspect = w / h;
      c.updateProjectionMatrix();
    }
    this.phone = w < 700;
    this.composer?.setSize(w, h);
  }

  shotAt(t) {
    if (this.force) return { kind: this.force, t0: Math.floor(t), t1: Math.floor(t) + 1, n: 0 };
    return this.shots.find((s) => t >= s.t0 && t < s.t1) || this.shots.at(-1);
  }

  frame({ t, dt = 1 / 60, wall = 0 }) {
    const t0 = performance.now();
    this.renderer.info.reset();
    const { d } = this;
    const x = d.at(t);
    const hr = Math.min(24, x.min / 60);
    const w = weatherAt(d.weather, hr);
    this.w = w;
    const st = this.sky.update(hr, wall, w);
    const wet = Math.min(1, w.rain * 0.9 + w.ts * 0.3 + (w.mist > 0.8 ? 0.2 : 0));
    this.U.uWet.value += (wet - this.U.uWet.value) * Math.min(1, dt * 0.6);
    if (this.manual && dt === 0) this.U.uWet.value = wet;
    const lights = 1 - Math.min(1, Math.max(0, (st.el + 3) / 5));
    const windYaw = -((w.windDir ?? 180) + 90) * DEG - this.yaw, wind = { kt: w.windKt, yawLocal: windYaw + Math.PI };
    const fieldH = this.renderer.domElement.height / (2 * Math.tan((this.camera.fov * DEG) / 2));
    const lvl = (s, e) => (s / e) * 8;
    const modeA = t >= 24 ? "idle" : x.A.mode;
    this.yard.update({ mode: modeA, mw: Math.abs(x.A.mw), pmax: d.P, soc: lvl(x.A.soc, d.E), night: st.night, lights, dt, wall, reduced: this.reduced, temp: w.temp ?? 25, wind });
    this.yardB.update({ mode: t >= 24 ? "idle" : x.B.mode, mw: Math.abs(x.B.mw), pmax: d.bat.p, soc: lvl(x.B.soc, d.bat.e), night: st.night, lights, dt, wall, reduced: this.reduced, temp: w.temp ?? 25, wind });
    const lineOf = (m, mw, p) => ({ dir: m === "discharge" ? 1 : m === "charge" ? -1 : 0, load: mw / Math.max(1, p), color: COLORS[m] || COLORS.idle });
    this.line.update({ ...lineOf(modeA, Math.abs(x.A.mw), d.P), dt, fog: this.scene.fog.density, height: fieldH, day: st.day, reduced: this.reduced });
    this.lineB.update({ ...lineOf(x.B.mode, Math.abs(x.B.mw), d.bat.p), dt, fog: this.scene.fog.density, height: fieldH, day: st.day, reduced: this.reduced });
    const wd = ((w.windDir ?? 180) + 180) * DEG;
    this.gas.update({ running: t >= 24 ? 0 : x.G.units, night: st.night, dt, wind: { x: Math.sin(wd) * 0.6, z: -Math.cos(wd) * 0.6 }, reduced: this.reduced });
    const sun = this.sky.sunAt(hr);
    this.solar.update({ el: sun.el, az: sun.az });
    this.backdrop.update({ night: st.night, wall, dt, windMs: w.windMs, windDir: w.windDir, reduced: this.reduced });
    const fl = lightningAt(wall, w.ts, this.reduced);
    this.sky.flash(fl ? fl.f * 0.9 : 0, fl?.dir);
    this.sky.hemi.intensity += fl ? fl.f * 1.5 : 0;
    const shot = this.shotAt(t);
    const inRoom = ROOM_SHOTS.has(shot.kind);
    this.shot = shot;
    const u = this.reduced ? 0.5 : this.drift ?? ease((t - shot.t0) / Math.max(1e-6, shot.t1 - shot.t0));
    const roomState = this.room.update({ t, s: x, sky: st, sunLight: this.sky.sun, hemiLight: this.sky.hemi, dt, wall, weather: describe(w), renderer: this.renderer, reduced: this.reduced, shot: shot.kind });
    this.wallHour = roomState.hour;
    let cam = this.camera;
    if (inRoom) {
      cam = this.roomCam;
      if (this.directing || !this.controls) {
        const p = this.room.cams[shot.kind](u, shot.n);
        cam.position.set(...p.pos);
        cam.fov = p.fov;
        cam.updateProjectionMatrix();
        cam.lookAt(...p.look);
      }
      this.pass.scene = this.room.scene;
      this.renderer.toneMappingExposure = Math.min(1.25, this.renderer.toneMappingExposure * 1.6);
    } else {
      if (this.directing || !this.controls) {
        const p = this.#fieldPose(shot, u, t);
        const wp = this.toWorld(p.pos[0], p.pos[2]);
        wp.y = p.pos[1] + this.terrain.heightAt(wp.x, wp.z);
        const wl = p.world ? new THREE.Vector3(...p.look) : this.toWorld(p.look[0], p.look[2]).setY(p.look[1]);
        if (p.world) wp.set(...p.pos).setY(p.pos[1] + this.terrain.heightAt(p.pos[0], p.pos[2]));
        this.camera.position.copy(wp);
        this.camera.fov = p.fov;
        this.camera.updateProjectionMatrix();
        this.camera.lookAt(wl);
        if (this.controls) this.controls.target.copy(wl);
      } else this.controls.update();
      this.pass.scene = this.scene;
      for (const [s, [sp]] of Object.entries(this.tags)) {
        sp.visible = !this.phone && shot.tags?.includes(s) && !this.bare;
        if (sp.visible) sp.userData.set(this.#tagText(s, x, t));
      }
    }
    this.pass.camera = cam;
    this.rain.update({ wall, camera: inRoom ? this.camera : this.camera, w, day: st.day });
    this.rain.mesh.visible = !inRoom;
    if (!inRoom) this.sky.focus(this.camera, this.controls?.target || this.camera.position.clone().add(this.camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(60)));
    this.grade.uniforms.uNight.value = inRoom ? 0 : st.night;
    this.bloom.threshold = inRoom ? 1.25 : 1.1 + 1.5 * st.day;
    this.bloom.strength = inRoom ? 0.32 : 0.38 + 0.32 * st.night;
    this.bloom.radius = 0.5;
    this.composer.render();
    this.frameMs.push(performance.now() - t0);
    if (this.frameMs.length > 240) this.frameMs.shift();
    return { s: st, w, x: { ...x, mw: x.A.mw }, mode: modeA, shot, inRoom };
  }

  #tagText(s, x, t) {
    const d = this.d, n = (v) => Math.round(Math.abs(v)).toLocaleString("en-US"), on = t >= 0 && t < 24;
    const mv = (m) => (m > 0.5 ? `discharging ${n(m)} MW` : m < -0.5 ? `charging ${n(m)} MW` : "idle");
    if (s === "A") return `${SEAT.A.name} · the model's ${n(d.P)} MW battery${on ? ` · ${mv(x.A.mw)}` : ""}`;
    if (s === "B") return `${SEAT.B.name} · rival battery${on ? ` · ${mv(x.B.mw)}` : ""}`;
    if (s === "G") return `${SEAT.G.name} · ${this.nUnits} gas peakers${on ? ` · ${x.G.units ? `${Math.min(this.nUnits, x.G.units)} running, ${n(x.G.mw)} MW` : "all off"}` : ""}`;
    if (s === "R") return `${SEAT.R.name} · wind and solar${on ? ` · ${n(x.R.mw)} MW` : ""}`;
    return `${SEAT.L.name} · the city's retailer${on ? ` · buys ${n(x.L.mw)} MW` : ""}`;
  }

  /** Field poses: seat A's yard from the shared director, the other seats from here (site-local unless `world`). */
  #fieldPose(shot, u, t) {
    const L = this.L, LB = this.LB, k = shot.kind;
    const yardKinds = { establish: 1, high: 1, push: 1, ramp: 1, line: 1, city: 1, sub: 1 };
    if (yardKinds[k]) {
      const p = this.director.pose(Math.max(0, Math.min(23.99, t)), k, this.reduced, u);
      return { pos: [p.pos.x, p.pos.y, p.pos.z], look: [p.look.x, p.look.y, p.look.z], fov: p.fov };
    }
    if (k === "byard") {
      const bx = SPOT.B[0] + LB.cx, bz = SPOT.B[1];
      return { pos: [bx + 150 - 40 * u, 42 - 6 * u, bz + 120], look: [bx - 10, 0, bz - 4], fov: 40 };
    }
    if (k === "gas") {
      const [gx, gz] = SPOT.G;
      return { pos: [gx - 150 + 60 * u, 30 - 4 * u, gz + 125 - 20 * u], look: [gx + 10, 10, gz], fov: 42 };
    }
    if (k === "solar") {
      const c = this.toWorld(...SPOT.R);
      return { world: true, pos: [c.x + 260 - 60 * u, 48, c.z + 210], look: [c.x - 20, 0, c.z], fov: 42 };
    }
    if (k === "wind") {
      const b = (this.d.region.line - 90) * DEG;
      const dir = new THREE.Vector3(Math.sin(b), 0, -Math.cos(b));
      return { world: true, pos: [dir.x * 1200 - dir.z * 60 * u, 30, dir.z * 1200 + dir.x * 60 * u], look: [dir.x * 8000, 120, dir.z * 8000], fov: 26 };
    }
    return { pos: [L.cx, 80, 160], look: [L.cx, 0, 0], fov: 45 };
  }

  state() {
    const ms = [...this.frameMs].sort((a, b) => a - b);
    return { shot: this.shot?.kind, el: this.sky.state?.el, frameMsP50: ms[ms.length >> 1], frameMsP95: ms[Math.floor(ms.length * 0.95)], calls: this.renderer.info.render.calls, tris: this.renderer.info.render.triangles, geometries: this.renderer.info.memory.geometries, textures: this.renderer.info.memory.textures };
  }
}

/** The cut: the day before in the room (the desk at 6, the offer at 9, the clock at the 10:00 close, the wall while
 * ERCOT clears, the merit order when the awards post), then the operating day in the field by quarter hour, with
 * cuts back to the room for a mitigation and the desk's re-plans. */
function shotList(d, night) {
  const pre = [];
  const deal = d.contracts.find((c) => c.status === "accepted" && c.t < d.closeT);
  const sub = d.offers[0]?.t ?? -4.6;
  pre.push({ kind: "room", t0: -6, t1: -5.1 });
  pre.push({ kind: "desk", t0: -5.1, t1: Math.max(-4.25, Math.min(-3.95, sub + 0.35)) });
  if (deal && deal.t < -3.85) pre.push({ kind: "deal", t0: pre.at(-1).t1, t1: Math.max(pre.at(-1).t1 + 0.45, -3.85) });
  else pre.push({ kind: "window", t0: pre.at(-1).t1, t1: -3.85 });
  pre.push({ kind: "clock", t0: pre.at(-1).t1, t1: -3.25 });
  pre.push({ kind: "wall", t0: -3.25, t1: -2.08 });
  pre.push({ kind: "merit", t0: -2.08, t1: -1.15 });
  pre.push({ kind: "prices", t0: -1.15, t1: -0.55 });
  pre.push({ kind: "high", t0: -0.55, t1: 0, tags: ["A", "B", "G", "R"] });
  const slots = Array.from({ length: 96 }, () => ({ kind: null, p: 0 }));
  const claim = (a, b, kind, extra = {}) => {
    for (let i = Math.max(0, Math.round(a * 4)); i < Math.min(96, Math.round(b * 4)); i++)
      if ((PRIORITY[kind] || 0) > slots[i].p) slots[i] = { kind, p: PRIORITY[kind], ...extra };
  };
  const H = d.hours;
  H.forEach((x, h) => h > 0 && x.mode !== H[h - 1].mode && x.mode !== "idle" && claim(h - 0.1, h + 1.3, "push"));
  const peak = d.peakH;
  if (d.clear.hub[peak] > d.median * 1.6) {
    claim(peak - 1.2, peak + 0.2, night(peak + 0.5) > 0.4 ? "city" : "ramp", { tags: ["L"] });
    claim(peak + 0.2, peak + 1.6, "ramp");
  }
  const gOn = d.aw.G.findIndex((g, h) => g > 1 && (h === 0 || d.aw.G[h - 1] <= 1));
  if (gOn >= 0) claim(gOn - 0.1, gOn + 1.2, "gas", { tags: ["G"] });
  const sunH = d.aw.R.reduce((a, v, h) => (v > d.aw.R[a] ? h : a), 0);
  if (d.aw.R[sunH] > 1) claim(sunH - 1.3, sunH - 0.1, "solar", { tags: ["R"] });
  const bOn = d.aw.B.findIndex((b) => Math.abs(b) > 1);
  if (bOn >= 0) claim(bOn - 0.1, bOn + 1.1, "byard", { tags: ["B"] });
  for (const w of d.watches) if (w.min >= 0 && w.min < 1440 && w.steps.some((s) => s.tool === "commit_schedule" && s.out.accepted)) claim(w.t, w.t + 0.6, "desk");
  for (const m of d.clear.mitigated.filter((x) => x.seat === "A")) claim(m.he - 1, m.he - 0.1, "mitigated");
  const fill = ["establish", "byard", "gas", "high", "solar", "wind", "line"];
  let f = 0;
  for (let i = 0; i < 96; i++) {
    if (slots[i].kind) continue;
    let j = i;
    while (j < 96 && !slots[j].kind) j++;
    for (let k = i; k < j; k += 10) {
      let kind = fill[f++ % fill.length];
      if (night(k / 4 + 1) > 0.6 && (kind === "solar" || kind === "wind")) kind = night(k / 4 + 1) > 0.9 ? "high" : "city";
      for (let m = k; m < Math.min(j, k + 10); m++) slots[m] = { kind, p: 0.5, ...(kind === "gas" ? { tags: ["G"] } : kind === "byard" ? { tags: ["B"] } : kind === "solar" ? { tags: ["R"] } : kind === "high" ? { tags: ["A", "B", "G", "R"] } : kind === "establish" ? { tags: ["A"] } : kind === "city" ? { tags: ["L"] } : kind === "wind" ? { tags: ["R"] } : {}) };
    }
    i = j - 1;
  }
  const shots = [...pre];
  for (let i = 0; i < 96; i++) {
    const s = slots[i], last = shots.at(-1);
    const kind = s.kind === "mitigated" ? "merit" : s.kind;
    if (last && last.t0 >= 0 && last.kind === kind) last.t1 = (i + 1) / 4;
    else shots.push({ kind, t0: i / 4, t1: (i + 1) / 4, tags: s.tags });
  }
  for (let i = pre.length + 1; i < shots.length; i++)
    if (shots[i].t1 - shots[i].t0 < 0.75 && shots[i].kind !== "merit") {
      shots[i - 1].t1 = shots[i].t1;
      shots.splice(i, 1);
      i--;
    }
  shots.push({ kind: "high", t0: 24, t1: 99, tags: ["A", "B", "G", "R"] });
  shots.forEach((s, i) => (s.n = i));
  return shots;
}

export { marketT };
