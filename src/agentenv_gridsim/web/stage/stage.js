import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { at } from "../data.js";
import { buildBackdrop } from "./backdrop.js";
import { buildDirector } from "./director.js";
import { buildLine } from "./line.js";
import { buildSky } from "./sky.js";
import { buildTerrain } from "./terrain.js";
import { buildRain, lightningAt, weatherAt } from "./weather.js";
import { buildYard, COLORS } from "./yard.js";

const DEG = Math.PI / 180;

/** The battery yard in its region, light and weather for a whole episode: frame({t, dt, wall}) renders hour t. */
export class GridStage {
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
    r.domElement.className = "stage-canvas";
    container.appendChild(r.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.3, 120000);
    this.#build();
    this.resize();
    addEventListener("resize", () => this.resize());
  }

  #build() {
    const { d, scene, renderer } = this;
    const region = d.region;
    const seed = `${d.task.settlement_point}-${d.task.date}`;
    this.yaw = Math.PI / 2 - region.line * DEG;
    this.sky = buildSky(renderer, scene, { date: d.task.date, lat: d.place.lat, lon: d.place.lon, region });
    this.site = new THREE.Group();
    this.site.rotation.y = this.yaw;
    const U = { uWet: { value: 0 } };
    this.yard = buildYard(d.b, U, { gravel: region.gravel, road: region.road, seed });
    const L = this.yard.layout;
    this.director = buildDirector(d, L, { night: (t) => 1 - Math.min(1, Math.max(0, (this.sky.sunAt(t).el + 6) / 8)) });
    const cams = this.director.spots.map(([x, z, r]) => {
      const v = new THREE.Vector3(x, 0, z).applyAxisAngle(new THREE.Vector3(0, 1, 0), this.yaw);
      return [v.x, v.z, r];
    });
    this.terrain = buildTerrain(region, { pad: L.pad, yaw: this.yaw, seed, cams });
    this.terrain.U.uWet = U.uWet;
    this.U = U;
    scene.add(this.terrain.group);
    const toWorld = (lx, lz) => new THREE.Vector3(lx, 0, lz).applyAxisAngle(new THREE.Vector3(0, 1, 0), this.yaw);
    const heightLocal = (lx, lz) => {
      const w = toWorld(lx, lz);
      return this.terrain.heightAt(w.x, w.z);
    };
    this.line = buildLine({ deadEnd: this.yard.sub.deadEnd, heightLocal, km: 9, seed });
    this.site.add(this.yard.group, this.line.group);
    scene.add(this.site);
    this.backdrop = buildBackdrop(region, this.terrain.heightAt, this.terrain.avoid, seed);
    scene.add(this.backdrop.group);
    this.rain = buildRain();
    scene.add(this.rain.mesh);
    this.#post();
    if (!this.manual) {
      this.controls = new OrbitControls(this.camera, renderer.domElement);
      this.controls.enableDamping = true;
      this.controls.maxPolarAngle = 1.52;
      this.controls.minDistance = 4;
      this.controls.maxDistance = 6000;
      this.controls.addEventListener("start", () => this.direct(false));
    }
    this.toWorld = toWorld;
  }

  #post() {
    const r = this.renderer;
    const size = r.getDrawingBufferSize(new THREE.Vector2());
    const rt = new THREE.WebGLRenderTarget(size.x || 1, size.y || 1, { type: THREE.HalfFloatType, samples: 4 });
    this.composer = new EffectComposer(r, rt);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
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
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.composer?.setSize(w, h);
  }

  /** Render hour t; dt and wall are presentation seconds (fans, rotors, rain, pulses move on these). */
  frame({ t, dt = 1 / 60, wall = 0 }) {
    const t0 = performance.now();
    const { d } = this;
    const tt = Math.max(0, Math.min(24, t));
    const w = weatherAt(d.weather, tt);
    this.w = w;
    const s = this.sky.update(tt, wall, w);
    const x = at(d, Math.min(23.999, tt));
    const mode = t >= 24 ? (d.trunc != null ? "grey" : "idle") : x.mode;
    const mw = mode === "charge" || mode === "discharge" ? Math.abs(x.mw) : 0;
    const pmax = mode === "charge" ? d.b.p_ch_mw : d.b.p_dis_mw;
    const wet = Math.min(1, w.rain * 0.9 + w.ts * 0.3 + (w.mist > 0.8 ? 0.2 : 0));
    this.U.uWet.value += (wet - this.U.uWet.value) * Math.min(1, dt * 0.6);
    if (this.manual && dt === 0) this.U.uWet.value = wet;
    const windYaw = -((w.windDir ?? 180) + 90) * DEG - this.yaw;
    this.yard.update({ mode, mw, pmax, soc: x.soc, night: s.night, lights: 1 - Math.min(1, Math.max(0, (s.el + 3) / 5)), dt, wall, reduced: this.reduced, temp: w.temp ?? 25, wind: { kt: w.windKt, yawLocal: windYaw + Math.PI } });
    this.line.update({ dir: mode === "discharge" ? 1 : mode === "charge" ? -1 : 0, load: mw / Math.max(1, pmax), color: x.neg && mode === "charge" ? "#7ff0ff" : COLORS[mode] || COLORS.idle, dt, fog: this.scene.fog.density, height: this.renderer.domElement.height / (2 * Math.tan((this.camera.fov * DEG) / 2)), day: s.day, reduced: this.reduced });
    this.backdrop.update({ night: s.night, wall, dt, windMs: w.windMs, windDir: w.windDir, reduced: this.reduced });
    const fl = lightningAt(wall, w.ts, this.reduced);
    this.sky.flash(fl ? fl.f * 0.9 : 0, fl?.dir);
    this.sky.hemi.intensity += fl ? fl.f * 1.5 : 0;
    if (this.directing || !this.controls) {
      const p = this.director.pose(t, this.force);
      const wp = this.toWorld(p.pos.x, p.pos.z).setY(p.pos.y + this.terrain.heightAt(...this.#xz(p.pos)));
      const wl = this.toWorld(p.look.x, p.look.z).setY(p.look.y);
      this.camera.position.copy(wp);
      this.camera.fov = p.fov;
      this.camera.updateProjectionMatrix();
      this.camera.lookAt(wl);
      if (this.controls) this.controls.target.copy(wl);
      this.shot = p.shot;
    } else this.controls.update();
    this.rain.update({ wall, camera: this.camera, w, day: s.day });
    this.sky.focus(this.camera, this.controls?.target || this.camera.position.clone().add(this.camera.getWorldDirection(new THREE.Vector3()).multiplyScalar(60)));
    this.bloom.threshold = 1.1 + 1.5 * s.day;
    this.bloom.strength = 0.38 + 0.32 * s.night;
    this.bloom.radius = 0.5;
    this.composer.render();
    this.frameMs.push(performance.now() - t0);
    if (this.frameMs.length > 240) this.frameMs.shift();
    return { s, w, x, mode };
  }

  #xz(p) {
    const v = this.toWorld(p.x, p.z);
    return [v.x, v.z];
  }

  state() {
    const ms = [...this.frameMs].sort((a, b) => a - b);
    return { shot: this.shot?.kind, el: this.sky.state?.el, frameMsP50: ms[ms.length >> 1], frameMsP95: ms[Math.floor(ms.length * 0.95)], calls: this.renderer.info.render.calls, tris: this.renderer.info.render.triangles, geometries: this.renderer.info.memory.geometries, textures: this.renderer.info.memory.textures };
  }
}
