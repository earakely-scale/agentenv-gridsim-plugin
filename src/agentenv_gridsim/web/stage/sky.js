import * as THREE from "three";
import { Sky } from "three/addons/objects/Sky.js";
import { dirOf, moonAt, sunAt, tzOffsetMinutes } from "./astro.js";

const smooth = (a, b, x) => {
  const u = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return u * u * (3 - 2 * u);
};
const KEYS = [-18, -10, -5, -1, 3, 10, 25, 60];
/** Horizon haze by sun elevation, clear and overcast: the colour far land fades into. */
const HAZE = [
  ["#06080d", "#0d1220", "#2a2c3c", "#7a6261", "#c9a487", "#c7c3bb", "#b9c6d1", "#b4c5d4"],
  ["#07080a", "#101216", "#25282e", "#4d5058", "#7c7f86", "#9a9ea4", "#aeb2b7", "#b8bcc0"],
];
const NIGHT = { zenith: new THREE.Color("#03060f"), horizon: new THREE.Color("#121a2b") };
const _a = new THREE.Color();
const _b = new THREE.Color();

function hazeAt(el, row, out) {
  let k = 0;
  while (k < KEYS.length - 2 && el > KEYS[k + 1]) k++;
  const u = Math.min(1, Math.max(0, (el - KEYS[k]) / (KEYS[k + 1] - KEYS[k])));
  return out.copy(_a.set(HAZE[row][k])).lerp(_b.set(HAZE[row][k + 1]), u);
}

function overlayDome(radius) {
  const mat = new THREE.ShaderMaterial({
    side: THREE.BackSide, transparent: true, depthWrite: false, fog: false,
    uniforms: {
      uHaze: { value: new THREE.Color() }, uHazeK: { value: 0.5 }, uNight: { value: 0 }, uStars: { value: 0 },
      uZen: { value: NIGHT.zenith.clone() }, uHor: { value: NIGHT.horizon.clone() },
      uSun: { value: new THREE.Vector3(0, 1, 0) }, uSunCol: { value: new THREE.Color() }, uDay: { value: 1 },
      uMoon: { value: new THREE.Vector3(0, -1, 0) }, uMoonLit: { value: 0.5 }, uMoonWax: { value: 1 },
      uCover: { value: 0 }, uOvercast: { value: 0 }, uCloudBase: { value: 0.5 }, uTime: { value: 0 },
      uWind: { value: new THREE.Vector2() }, uGlowDir: { value: new THREE.Vector2(1, 0) }, uGlow: { value: 0 },
      uFlash: { value: 0 }, uFlashDir: { value: new THREE.Vector3(0, 0.3, 1) }, uRain: { value: 0 },
    },
    vertexShader: /* glsl */ `
      varying vec3 vDir;
      void main() {
        vDir = normalize(position);
        vec4 p = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        gl_Position = p.xyww;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uHaze, uZen, uHor, uSun, uSunCol, uMoon, uFlashDir;
      uniform float uHazeK, uNight, uStars, uDay, uMoonLit, uMoonWax, uCover, uOvercast, uCloudBase, uTime, uGlow, uFlash, uRain;
      uniform vec2 uWind, uGlowDir;
      varying vec3 vDir;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float hash3(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i = floor(p), f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1, 0)), u.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), u.x), u.y);
      }
      float fbm(vec2 p) {
        float v = 0.0, a = 0.5;
        for (int k = 0; k < 6; k++) { v += a * noise(p); p = p * 2.02 + vec2(17.0, 9.0); a *= 0.5; }
        return v;
      }
      void main() {
        vec3 d = normalize(vDir);
        float h = d.y;
        vec3 col = vec3(0.0);
        float a = 0.0;
        // night sky
        vec3 night = mix(uHor, uZen, smoothstep(0.0, 0.55, h));
        vec2 hz = normalize(d.xz + 1e-5);
        float glow = pow(max(dot(hz, uGlowDir), 0.0), 6.0) * (1.0 - smoothstep(0.0, 0.16, h)) * uGlow;
        night += vec3(0.42, 0.27, 0.16) * glow * 0.32 + vec3(0.2, 0.14, 0.1) * uGlow * 0.05 * (1.0 - smoothstep(0.0, 0.35, h));
        if (uStars > 0.0 && h > 0.0) {
          vec3 cell = floor(d * 420.0);
          float r = hash3(cell);
          vec3 c3 = normalize((cell + 0.5) / 420.0);
          float star = step(0.9972, r) * exp(-dot(d - c3, d - c3) * 2.4e6) * (0.25 + 0.75 * pow(hash3(cell + 7.0), 2.0));
          float milky = fbm(vec2(atan(d.z, d.x) * 3.0, d.y * 6.0)) * smoothstep(0.1, 0.6, h) * 0.06;
          night += vec3(0.9, 0.93, 1.0) * (star * 1.8 + milky * 0.4) * uStars * smoothstep(0.03, 0.25, h);
        }
        // moon
        vec3 sd0 = normalize(uSun);
        vec3 md = normalize(uMoon);
        float mc = dot(d, md);
        float disc = smoothstep(0.99996, 0.999975, mc);
        vec3 off = (d - md * mc) / 0.0078;
        vec3 sp = normalize(sd0 - md * dot(sd0, md) + vec3(1e-4, 0.0, 0.0));
        vec3 sq = cross(md, sp);
        float px = dot(off, sp), py = dot(off, sq);
        float litSide = smoothstep(-0.06, 0.06, px + (2.0 * uMoonLit - 1.0) * sqrt(max(0.0, 1.0 - py * py)));
        float moonA = disc * step(0.0, md.y + 0.02);
        vec3 moonCol = vec3(0.92, 0.9, 0.84) * (0.12 + 0.88 * litSide) * 2.4;
        night = mix(night, moonCol, moonA * (1.0 - uOvercast * 0.95));
        night += vec3(0.6, 0.65, 0.75) * pow(max(mc, 0.0), 400.0) * 0.18 * uMoonLit * (1.0 - uOvercast);
        col = night; a = uNight;
        // horizon haze band
        float band = 1.0 - smoothstep(0.0, 0.015 + 0.1 * uHazeK, max(h, 0.0));
        band *= band;
        if (h < 0.0) band = 1.0;
        vec3 sd = normalize(uSun);
        vec2 sz = normalize(sd.xz + 1e-5);
        float toward = pow(max(dot(hz, sz), 0.0), 3.0);
        vec3 haze = uHaze * (1.0 + toward * 0.25 * uDay) + uSunCol * toward * 0.14 * (1.0 - uDay) * step(-0.12, sd.y);
        col = mix(col, haze, band * (0.6 + 0.4 * uHazeK));
        a = max(a, band * (0.6 + 0.4 * uHazeK));
        // overcast deck and clouds
        if (h > -0.02) {
          vec2 cp = d.xz / (max(h, 0.0) + 0.09) * (0.9 + 0.7 * uCloudBase);
          float c = fbm(cp * 0.9 + uWind * uTime);
          float c2 = fbm(cp * 2.3 - uWind * uTime * 1.4 + 3.0);
          float th = 0.78 - 0.5 * uCover;
          float cl = smoothstep(th, th + 0.18, c * 0.8 + c2 * 0.3) * smoothstep(-0.02, 0.06, h);
          cl = max(cl, uOvercast * smoothstep(-0.02, 0.05, h));
          float lit = smoothstep(0.35, 0.9, fbm(cp * 1.4 - sd.xz * 0.5 + 5.0));
          vec3 base = mix(vec3(0.5, 0.52, 0.56), vec3(0.95, 0.95, 0.94), uDay) * (0.55 + 0.45 * uDay);
          base = mix(base, vec3(0.32, 0.34, 0.38) * (0.25 + 0.75 * uDay), uRain);
          vec3 cloud = base * (0.82 + 0.3 * lit) + uSunCol * pow(max(dot(d, sd), 0.0), 4.0) * 0.5 * (1.0 - uOvercast) * step(-0.05, sd.y);
          cloud = mix(cloud, vec3(0.05, 0.055, 0.07) + vec3(0.36, 0.24, 0.15) * glow * 0.5 + vec3(0.1, 0.07, 0.05) * uGlow * 0.12, uNight);
          cloud *= mix(1.0, 0.82 + 0.3 * c2, uOvercast);
          col = mix(col, cloud, cl * 0.95);
          a = max(a, cl * 0.95);
          col = mix(col, haze, band * (0.5 + 0.5 * uHazeK) * cl);
        }
        float fl = uFlash * (0.25 + 0.75 * pow(max(dot(d, normalize(uFlashDir)), 0.0), 3.0));
        col += vec3(0.62, 0.66, 0.86) * fl;
        a = max(a, min(1.0, fl));
        gl_FragColor = vec4(col, a);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(radius, 64, 32), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = -9;
  return mesh;
}

/** The sky, sun, moon, haze and their lights for hour t of the day; update(t, wall, weather) returns the state. */
export function buildSky(renderer, scene, { date, lat, lon, region }) {
  const offset = tzOffsetMinutes(date);
  const [Y, M, D] = date.split("-").map(Number);
  const utc = (t) => Date.UTC(Y, M - 1, D) + (t * 60 - offset) * 60000;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  const R = 60000;
  const sky = new Sky();
  sky.scale.setScalar(R * 1.2);
  sky.renderOrder = -10;
  sky.frustumCulled = false;
  const dome = overlayDome(R);
  scene.add(sky, dome);
  scene.background = new THREE.Color("#000");
  scene.fog = new THREE.FogExp2(0x8899aa, 0.0001);

  const hemi = new THREE.HemisphereLight("#bcd0e6", "#5a4a3a", 0.6);
  const sun = new THREE.DirectionalLight("#fff", 0);
  sun.castShadow = true;
  sun.shadow.mapSize.set(4096, 4096);
  sun.shadow.bias = -0.00025;
  sun.shadow.normalBias = 0.25;
  const moon = new THREE.DirectionalLight("#9fb3d9", 0);
  scene.add(hemi, sun, sun.target, moon, moon.target);

  const pm = new THREE.PMREMGenerator(renderer);
  const envScene = new THREE.Scene();
  const envSky = new Sky();
  envSky.scale.setScalar(900);
  const envDome = overlayDome(800);
  const envGround = new THREE.Mesh(new THREE.CircleGeometry(700, 32), new THREE.MeshBasicMaterial({ color: "#555" }));
  envGround.rotation.x = -Math.PI / 2;
  envGround.position.y = -40;
  envScene.add(envSky, envDome, envGround);
  let envTarget = null;
  let envKey = "";

  const sunDir = new THREE.Vector3(), moonDir = new THREE.Vector3();
  const haze = new THREE.Color(), hazeO = new THREE.Color(), sunCol = new THREE.Color();
  const groundTint = new THREE.Color(region.ground[0]);
  const cityB = (region.city.bearing * Math.PI) / 180;
  let last = null;

  function stateAt(t, w) {
    const ms = utc(t);
    const s = sunAt(ms, lat, lon), m = moonAt(ms, lat, lon);
    return { t, ms, sun: s, moon: m, w };
  }

  function update(t, wall, w) {
    const st = stateAt(t, w);
    const el = st.sun.el;
    dirOf(el, st.sun.az, sunDir);
    dirOf(st.moon.el, st.moon.az, moonDir);
    const cover = w.cover, overcast = w.overcast;
    const day = smooth(-6, 8, el);
    const night = 1 - smooth(-14, -2, el);
    const twilight = smooth(-10, -1, el) * (1 - smooth(3, 14, el));
    const visKm = Math.min(region.visKm, w.visKm);
    const hazeK = Math.min(1, 0.18 + region.humid * 0.55 + 22 / Math.max(4, visKm) * 0.3 + w.mist * 0.5);

    const u = sky.material.uniforms;
    u.sunPosition.value.copy(sunDir);
    u.turbidity.value = region.turbidity + w.mist * 4 + overcast * 3;
    u.rayleigh.value = 1.2 + region.humid * 0.8 + twilight * 1.2;
    u.mieCoefficient.value = 0.004 + region.humid * 0.005 + w.mist * 0.01;
    u.mieDirectionalG.value = 0.82;
    for (const k of ["sunPosition", "turbidity", "rayleigh", "mieCoefficient", "mieDirectionalG"]) {
      const v = u[k].value;
      if (v?.copy) envSky.material.uniforms[k].value.copy(v);
      else envSky.material.uniforms[k].value = v;
    }

    hazeAt(el, 0, haze);
    hazeAt(el, 1, hazeO);
    haze.lerp(hazeO, Math.min(1, overcast * 0.9 + w.rain * 0.3));
    if (region.humid > 0.5) haze.lerp(_a.set("#d8d2bf").multiplyScalar(0.25 + 0.75 * day), 0.12 * region.humid * day);
    if (w.dust) haze.lerp(_a.set("#c49a6c").multiplyScalar(0.3 + 0.7 * day), Math.min(0.5, w.dust * 0.5));
    sunCol.setHSL(0.07 + 0.065 * smooth(0, 25, el), 0.9 - 0.55 * smooth(2, 35, el), 0.58 + 0.3 * smooth(0, 30, el));

    const o = dome.material.uniforms;
    o.uHaze.value.copy(haze);
    o.uHazeK.value = hazeK;
    o.uNight.value = night;
    o.uStars.value = smooth(-8, -16, el) * (1 - 0.95 * overcast) * (1 - 0.6 * w.mist) * (1 - 0.65 * region.humid) * (1 - 0.4 * region.city.lights * region.city.km / 30);
    o.uSun.value.copy(sunDir);
    o.uSunCol.value.copy(sunCol);
    o.uDay.value = day;
    o.uMoon.value.copy(moonDir);
    o.uMoonLit.value = st.moon.lit;
    o.uMoonWax.value = st.moon.waxing ? 1 : 0;
    o.uCover.value = cover;
    o.uOvercast.value = overcast;
    o.uCloudBase.value = Math.min(1, (w.baseFt ?? 6000) / 12000);
    o.uTime.value = wall;
    const wd = ((w.windDir ?? 180) + 180) * (Math.PI / 180);
    o.uWind.value.set(Math.sin(wd), -Math.cos(wd)).multiplyScalar(0.0025 * (w.windKt || 0) + 0.002);
    o.uGlowDir.value.set(Math.sin(cityB), -Math.cos(cityB));
    o.uGlow.value = region.city.lights * (night * 0.9 + 0.1) * (1 + overcast * 1.4) * (1 - day);
    o.uRain.value = Math.min(1, w.rain);
    for (const k of Object.keys(o)) {
      const v = o[k].value;
      if (v?.copy) envDome.material.uniforms[k].value.copy(v);
      else envDome.material.uniforms[k].value = v;
    }
    envDome.material.uniforms.uStars.value = 0;

    scene.fog.color.copy(haze);
    scene.background.copy(haze);
    scene.fog.density = 3.6 / (visKm * 1000);

    const cloudDim = 1 - 0.82 * Math.pow(cover, 1.6) - 0.08 * w.rain;
    sun.color.copy(sunCol);
    sun.intensity = 4.2 * smooth(-1.5, 8, el) * Math.max(0.06, cloudDim);
    moon.color.set("#a7b8d8");
    moon.intensity = 0.2 * st.moon.lit * smooth(-2, 10, st.moon.el) * night * (1 - 0.85 * overcast);
    hemi.color.copy(_a.set("#c3d4ea").lerp(haze, 0.35)).multiplyScalar(0.25 + 0.75 * day);
    hemi.color.lerp(_b.set("#2a3550"), night * 0.85);
    hemi.groundColor.copy(groundTint).multiplyScalar(0.25 + 0.5 * day);
    hemi.intensity = 0.06 + 0.7 * day * (0.7 + 0.8 * overcast) + 0.22 * twilight;
    renderer.toneMappingExposure = 0.55 + 0.4 * night + 0.15 * overcast * day;
    envGround.material.color.copy(groundTint).multiplyScalar(0.06 + 0.5 * day);

    const key = [Math.round(el / 1.5), Math.round(cover * 10), Math.round(night * 10), Math.round(hazeK * 10), Math.round(w.rain * 4)].join("|");
    if (key !== envKey) {
      envKey = key;
      envTarget?.dispose();
      envTarget = pm.fromScene(envScene, 0.035);
      scene.environment = envTarget.texture;
    }
    scene.environmentIntensity = 0.18 + 0.42 * day;
    last = { ...st, el, day, night, twilight, sunDir, moonDir, haze, hazeK, visKm, cover, overcast, sunI: sun.intensity };
    return last;
  }

  const _t = new THREE.Vector3();
  function focus(camera, target) {
    const on = last && last.sunI > 0.25 && last.el > 1.5;
    sun.castShadow = !!on;
    if (!on) return;
    const r = Math.min(900, Math.max(60, camera.position.distanceTo(target) * 0.9));
    _t.copy(target).setY(0);
    sun.target.position.copy(_t);
    sun.position.copy(_t).addScaledVector(sunDir, 3000);
    const c = sun.shadow.camera;
    if (c.right !== r) {
      Object.assign(c, { left: -r, right: r, top: r, bottom: -r, near: 1500, far: 4500 });
      c.updateProjectionMatrix();
    }
    sun.target.updateMatrixWorld();
    moon.position.copy(_t).addScaledVector(moonDir, 3000);
    moon.target.position.copy(_t);
    moon.target.updateMatrixWorld();
  }

  function flash(f, dir) {
    dome.material.uniforms.uFlash.value = f;
    if (dir) dome.material.uniforms.uFlashDir.value.copy(dir);
  }

  return { update, focus, flash, sunAt: (t) => sunAt(utc(t), lat, lon), get state() { return last; }, sun, moon, hemi, sky, dome };
}
