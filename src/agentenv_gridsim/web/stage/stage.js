import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { at } from "../data.js";
import { buildBackdrop } from "./backdrop.js";
import { buildDirector } from "./director.js";
import { buildFront, coverOn, frostOn } from "./front.js";
import { buildLine } from "./line.js";
import { buildPlant, plantLayout, SOLAR, trackerAngle } from "./plant.js";
import { buildSky } from "./sky.js";
import { buildTerrain } from "./terrain.js";
import { buildRain, lightningAt, snowCover, snowOn, weatherAt } from "./weather.js";
import { buildYard, COLORS } from "./yard.js";

const DEG = Math.PI / 180;
THREE.ShaderChunk.fog_fragment = /* glsl */ `
#ifdef USE_FOG
  #ifdef FOG_EXP2
    float fogFactor = 1.0 - exp( - fogDensity * vFogDepth );
  #else
    float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
  #endif
  gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif`;

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
    r.info.autoReset = false;
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
    const hyb = !!d.hybrid && !d.lite;
    this.yard = buildYard(d.b, U, { gravel: region.gravel, road: region.road, seed, ...(hyb ? { bands: true } : {}) });
    const L = this.yard.layout;
    this.plantL = hyb ? plantLayout(d.site, L, this.yaw, seed) : null;
    this.director = buildDirector(d, L, { night: (t) => 1 - Math.min(1, Math.max(0, (this.sky.sunAt(t).el + 6) / 8)), plant: this.plantL, yaw: this.yaw });
    const cams = this.director.spots.map(([x, z, r]) => {
      const v = new THREE.Vector3(x, 0, z).applyAxisAngle(new THREE.Vector3(0, 1, 0), this.yaw);
      return [v.x, v.z, r];
    });
    this.terrain = buildTerrain(region, { pad: L.pad, yaw: this.yaw, seed, cams, ...(hyb ? { level: this.plantL.level, keepOut: this.plantL.keepOut } : {}) });
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
    if (hyb) {
      this.plant = buildPlant(this.plantL, L, { site: d.site, U, heightAt: this.terrain.heightAt, sub: { lowX: L.sx - 13, deX: this.yard.sub.deadEnd.x } });
      scene.add(this.plant.world);
      this.site.add(this.plant.local);
    }
    scene.add(this.site);
    const nearPj = [[L.cx + 30, -L.D / 2 - 190], [L.cx - L.W / 2 - 160, L.D / 2 + 260]].map(([x, z]) => {
      const v = toWorld(x, z);
      return [v.x, v.z];
    }).filter(([x, z]) => !hyb || this.plantL.level(x, z) === 0);
    this.backdrop = buildBackdrop(region, this.terrain.heightAt, this.terrain.avoid, seed, { near: nearPj });
    scene.add(this.backdrop.group);
    this.rain = buildRain();
    scene.add(this.rain.mesh);
    U.uSnow = { value: 0 };
    const snowy = (d.weather?.obs || []).some((o) => (o.wx || []).some((c) => /SN|PL/.test(c))) || (d.weather?.obs || []).some((o) => (o.temp_c ?? 9) < -2);
    if (snowy && !d.forecast) this.scene.traverse((o) => {
      const ms = Array.isArray(o.material) ? o.material : [o.material];
      for (const m of ms) if (m?.isMeshStandardMaterial) snowOn(m, U);
    });
    if (d.forecast) {
      U.uFrost = { value: 0 };
      U.uSnowD = { value: 0 };
      U.uRime = { value: 0 };
      if (hyb) for (const mesh of this.plant.panels) frostOn(mesh.material[2], U);
      if (d.cold) this.scene.traverse((o) => {
        const ms = Array.isArray(o.material) ? o.material : [o.material];
        for (const m of ms) if (m?.isMeshStandardMaterial) coverOn(m, U, !m.userData.frost);
      });
      if (d.front) {
        this.front = buildFront();
        scene.add(this.front.mesh);
      }
    }
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
    this.shimmer = new ShaderPass({
      uniforms: { tDiffuse: { value: null }, uAmt: { value: 0 }, uH: { value: 0.5 }, uT: { value: 0 }, uNight: { value: 0 } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
      fragmentShader: /* glsl */ `
        uniform sampler2D tDiffuse;
        uniform float uAmt, uH, uT, uNight;
        varying vec2 vUv;
        vec4 grade(vec4 c) {
          if (any(isnan(c)) || any(isinf(c))) return vec4(0.0, 0.0, 0.0, 1.0);
          float l = dot(c.rgb, vec3(0.2126, 0.7152, 0.0722));
          c.rgb = mix(c.rgb, l * vec3(0.9, 0.97, 1.12), uNight * 0.32 * (1.0 - smoothstep(0.4, 3.0, l)));
          return min(c, vec4(80.0));
        }
        void main() {
          vec2 uv = vUv;
          if (uAmt <= 0.0) {
            gl_FragColor = grade(texture2D(tDiffuse, uv));
            return;
          }
          float dy = (uv.y - uH) / 0.035;
          float band = exp(-dy * dy) * step(uv.y, uH + 0.01);
          float n = sin(uv.y * 1100.0 + uT * 7.0) * 0.6 + sin(uv.y * 1900.0 - uT * 11.0 + uv.x * 35.0) * 0.4;
          uv.x += n * uAmt * band * 0.0011;
          uv.y += n * uAmt * band * 0.0005;
          gl_FragColor = grade(texture2D(tDiffuse, uv));
        }`,
    });
    this.composer.addPass(this.shimmer);
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
    this.renderer.info.reset();
    const { d } = this;
    const E = d.end ?? 24, v4 = !!d.forecast;
    const tt = Math.max(0, Math.min(E, t));
    const wt = v4 ? Math.max(d.t0, Math.min(E, t)) : tt;
    const w = weatherAt(d.weather, wt);
    if (v4) w.hubMs = d.hubAt(wt) ?? (w.windMs || 0) * 1.35;
    this.w = w;
    const pre = d.live && t < 0;
    const clock = v4 ? wt : pre ? (-600 + ((t + 2) / 2) * 600) / 60 : tt;
    const s = this.sky.update(clock, wall, w);
    if (this.front) {
      const f = d.front, lead = 4.5;
      const shade = this.front.update({ p: (wt - (f.t - lead)) / lead, bearing: f.bearing, s, wall, reduced: this.reduced });
      if (shade > 0) this.sky.sun.intensity *= 1 - 0.7 * shade;
    }
    const x = d.hybrid ? (pre ? d.pre(t) : d.at(tt)) : pre ? { ...at(d, 0), mode: "idle", mw: 0, soc: d.b.s0 } : at(d, Math.min(23.999, tt));
    const mode = t >= E ? (d.trunc != null ? "grey" : "idle") : x.mode;
    const mw = mode === "charge" || mode === "discharge" ? Math.abs(x.mw) : 0;
    const pmax = mode === "charge" ? d.b.p_ch_mw : d.b.p_dis_mw;
    const wet = Math.min(1, w.rain * 0.9 + w.ts * 0.3 + (w.mist > 0.8 ? 0.2 : 0));
    this.U.uWet.value += (wet - this.U.uWet.value) * Math.min(1, dt * 0.6);
    if (this.manual && dt === 0) this.U.uWet.value = wet;
    this.U.uSnow.value = snowCover(d.weather, wt);
    if (v4) {
      this.U.uFrost.value = d.frostAt(wt);
      this.U.uSnowD.value = d.snowAt(wt);
      this.U.uRime.value = d.frostAt(wt);
    }
    const windYaw = -((w.windDir ?? 180) + 90) * DEG - this.yaw;
    const lights = 1 - Math.min(1, Math.max(0, (s.el + 3) / 5)), wind = { kt: w.windKt, yawLocal: windYaw + Math.PI };
    const height = this.renderer.domElement.height / (2 * Math.tan((this.camera.fov * DEG) / 2));
    if (d.hybrid) {
      this.yard.update({ mode, mw, pmax, soc: x.socLevels, night: s.night, lights, dt, wall, reduced: this.reduced, temp: w.temp ?? 25, wind, floor: t >= E ? 0 : x.floor / d.E, head: t >= E ? 0 : x.head / d.E, draw: x.bands.some((z) => z.live) ? 1 : 0 });
      const e = x.exp;
      this.line.update({ dir: e > 1 ? 1 : e < -1 ? -1 : 0, load: Math.abs(e) / Math.max(1, d.L), color: e < 0 ? COLORS.charge : x.net > 0.5 ? COLORS.discharge : SOLAR, dt, fog: this.scene.fog.density, height, day: s.day, reduced: this.reduced });
      const sun = this.sky.sunAt(clock);
      this.plant?.update({ tilt: trackerAngle(sun.el, sun.az), off: x.off, pv: x.pvUsed, net: x.net, exp: e, head: x.upMw, night: s.night, dt, height, fog: this.scene.fog.density, day: s.day, reduced: this.reduced });
    } else {
      this.yard.update({ mode, mw, pmax, soc: x.soc, night: s.night, lights, dt, wall, reduced: this.reduced, temp: w.temp ?? 25, wind });
      this.line.update({ dir: mode === "discharge" ? 1 : mode === "charge" ? -1 : 0, load: mw / Math.max(1, pmax), color: x.neg && mode === "charge" ? "#7ff0ff" : COLORS[mode] || COLORS.idle, dt, fog: this.scene.fog.density, height, day: s.day, reduced: this.reduced });
    }
    this.backdrop.update({ night: s.night, wall, dt, windMs: v4 ? w.hubMs : w.windMs, windDir: w.windDir, reduced: this.reduced });
    const fl = lightningAt(wall, w.ts, this.reduced);
    this.sky.flash(fl ? fl.f * 0.9 : 0, fl?.dir);
    this.sky.hemi.intensity += fl ? fl.f * 1.5 : 0;
    if (this.directing || !this.controls) {
      const p = this.director.pose(t, this.force, this.reduced, this.drift);
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
    const heat = this.reduced ? 0 : Math.min(1, Math.max(0, ((w.temp ?? 20) - 31) / 6)) * Math.min(1, Math.max(0, (s.el - 20) / 20)) * (1 - w.cover * 0.8) * (1 - w.rain);
    this.shimmer.uniforms.uAmt.value = 0;
    this.shimmer.uniforms.uNight.value = s.night;
    if (heat > 0.02) {
      const f = this.camera.getWorldDirection(new THREE.Vector3()).setY(0).normalize().multiplyScalar(20000).add(this.camera.position);
      f.y = this.camera.position.y * 0.98;
      const ndc = f.project(this.camera);
      this.shimmer.uniforms.uH.value = (ndc.y + 1) / 2;
      this.shimmer.uniforms.uAmt.value = heat;
      this.shimmer.uniforms.uT.value = wall;
    }
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
