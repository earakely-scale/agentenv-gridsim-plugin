import * as THREE from "three";

const KT = 0.514444;

function decode(o) {
  const out = { rain: 0, ts: 0, mist: 0, snow: 0, dust: 0 };
  for (const c of o?.wx || []) {
    const k = c.startsWith("+") ? 1.5 : c.startsWith("-") ? 0.5 : 1;
    if (c.startsWith("VC")) {
      if (/TS/.test(c)) out.ts = Math.max(out.ts, 0.4);
      continue;
    }
    if (/TS/.test(c)) out.ts = 1;
    if (/RA|DZ|SH/.test(c)) out.rain = Math.max(out.rain, /DZ/.test(c) ? k * 0.4 : k);
    if (/SN|PL|GS/.test(c)) out.snow = Math.max(out.snow, k);
    if (/FG/.test(c)) out.mist = Math.max(out.mist, 1);
    else if (/BR|HZ/.test(c)) out.mist = Math.max(out.mist, 0.55);
    if (/DU|SA|BLDU/.test(c)) out.dust = Math.max(out.dust, 1);
  }
  return out;
}

/** The weather at hour t from the sidecar's observations, eased between reports; a plain clear day without one. */
export function weatherAt(sidecar, t) {
  const obs = sidecar?.obs || [];
  if (!obs.length) return { snow: 0, cover: 0.1, overcast: 0, visKm: 99, rain: 0, ts: 0, mist: 0, dust: 0, windKt: 8, windDir: 180, temp: null, baseFt: 6000, plain: null };
  let i = 0;
  while (i + 1 < obs.length && obs[i + 1].t <= t) i++;
  const a = obs[i], b = obs[Math.min(obs.length - 1, i + 1)];
  const u = b === a || t <= a.t ? 0 : Math.min(1, (t - a.t) / Math.max(0.05, b.t - a.t));
  const da = decode(a), db = decode(b);
  const mix = (x, y) => (x ?? y ?? 0) + ((y ?? x ?? 0) - (x ?? y ?? 0)) * u;
  const vis = (o) => (o.vis_sm == null || o.vis_sm >= 10 ? 99 : Math.max(0.15, o.vis_sm * 1.609));
  const overc = (o) => ((o.clouds || []).some(([c, ft]) => (c === "OVC" || c === "VV") && (ft ?? 0) < 20000) ? 1 : 0);
  let wd = a.wind_dir ?? b.wind_dir ?? 180;
  if (b.wind_dir != null && a.wind_dir != null) wd = a.wind_dir + ((((b.wind_dir - a.wind_dir) % 360) + 540) % 360 - 180) * u;
  const near = u < 0.5 ? a : b;
  return {
    cover: mix(a.cover, b.cover), overcast: mix(overc(a), overc(b)), visKm: Math.exp(mix(Math.log(vis(a)), Math.log(vis(b)))),
    snow: mix(da.snow, db.snow), rain: mix(da.rain, db.rain), ts: Math.max(da.ts * (1 - u), db.ts * u), mist: mix(da.mist, db.mist), dust: mix(da.dust, db.dust),
    windKt: mix(a.wind_kt, b.wind_kt), windDir: (wd + 360) % 360, gustKt: near.gust_kt, temp: mix(a.temp_c, b.temp_c),
    baseFt: near.cloud_base_ft ?? 6000, wx: near.wx || [], plain: near, windMs: mix(a.wind_kt, b.wind_kt) * KT,
  };
}

const SKY = { 0: "Clear", 0.2: "Mostly clear", 0.45: "Partly cloudy", 0.78: "Mostly cloudy", 1: "Overcast" };
const COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

/** "Partly cloudy, 31 °C, wind S 14 mph" for the card. */
export function describe(w) {
  if (!w.plain) return "";
  const k = Object.keys(SKY).map(Number).reduce((best, x) => (Math.abs(x - w.cover) < Math.abs(best - w.cover) ? x : best), 0);
  const wx = w.ts > 0.6 ? "Thunderstorm" : (w.snow || 0) > 0.3 ? "Snow" : w.rain > 1.2 ? "Heavy rain" : w.rain > 0.3 ? "Rain" : w.mist > 0.8 ? "Fog" : w.dust > 0.3 ? "Blowing dust" : w.mist > 0.3 ? "Haze" : SKY[k];
  const temp = w.temp == null ? "" : `, ${Math.round(w.temp * 9 / 5 + 32)} °F`;
  const wind = w.windKt < 3 ? ", calm" : `, wind ${COMPASS[Math.round(w.windDir / 45) % 8]} ${Math.round(w.windKt * 1.15078)} mph`;
  return `${wx}${temp}${wind}`;
}

/** Lying snow 0..1 at hour t: it builds over two hours from the first snow report (or lies from the start when the
 * night before reported it) and stays while the temperature holds below 2 °C. */
export function snowCover(sidecar, t) {
  const obs = sidecar?.obs || [];
  let cover = 0, last = -99;
  for (const o of obs) {
    if (o.t > t) break;
    const snowing = (o.wx || []).some((c) => /SN|PL|GS/.test(c) && !c.startsWith("VC"));
    if (snowing) last = o.t;
    if ((o.temp_c ?? 5) > 2) last = -99;
  }
  if (last > -99) cover = Math.min(1, 0.35 + (t - Math.max(-3, last)) / 2);
  const early = obs.filter((o) => o.t < 1).some((o) => (o.wx || []).some((c) => /SN|PL/.test(c)));
  const cold = obs.length && Math.max(...obs.filter((o) => o.t <= Math.max(t, 0.5)).map((o) => o.temp_c ?? 5)) < 1;
  return Math.max(cover, early && cold ? 1 : 0);
}

/** Snow on the upward faces of a material (uSnow 0..1), chained onto any patch it already has. */
export function snowOn(mat, U) {
  if (mat.userData.snow) return mat;
  mat.userData.snow = true;
  const prev = mat.onBeforeCompile;
  const base = mat.customProgramCacheKey();
  mat.onBeforeCompile = (sh, r) => {
    prev?.call(mat, sh, r);
    sh.uniforms.uSnowLie = U.uSnow;
    sh.fragmentShader = "uniform float uSnowLie;\n" + sh.fragmentShader.replace("#include <normal_fragment_maps>", `#include <normal_fragment_maps>
      {
        float up = dot(normal, normalize((viewMatrix * vec4(0.0, 1.0, 0.0, 0.0)).xyz));
        float lie = uSnowLie * smoothstep(0.35, 0.8, up);
        diffuseColor.rgb = mix(diffuseColor.rgb, vec3(0.86, 0.88, 0.92), lie);
      }`);
  };
  mat.customProgramCacheKey = () => `${base}-snow`;
  return mat;
}

/** Rain streaks around the camera, wind-slanted, as dense as the report says. */
export function buildRain() {
  const N = 9000;
  const seeds = new Float32Array(N * 2 * 3), ends = new Float32Array(N * 2);
  for (let i = 0; i < N; i++) {
    const s = [(i * 0.7548776662) % 1, (i * 0.56984029) % 1, (i * 0.381966 + 0.13) % 1];
    for (let e = 0; e < 2; e++) {
      seeds.set(s, (i * 2 + e) * 3);
      ends[i * 2 + e] = e;
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(seeds, 3));
  g.setAttribute("aEnd", new THREE.BufferAttribute(ends, 1));
  const mat = new THREE.ShaderMaterial({
    transparent: true, depthWrite: false,
    uniforms: { uT: { value: 0 }, uCam: { value: new THREE.Vector3() }, uWind: { value: new THREE.Vector2() }, uN: { value: 0 }, uCol: { value: new THREE.Color("#c9d3dc") }, uA: { value: 0.35 }, uFall: { value: 9 }, uLen: { value: 0.06 } },
    vertexShader: /* glsl */ `
      attribute float aEnd;
      uniform float uT, uN, uFall, uLen;
      uniform vec3 uCam;
      uniform vec2 uWind;
      varying float vA;
      void main() {
        float id = float(gl_VertexID / 2) / 9000.0;
        vec3 box = vec3(90.0, 50.0, 90.0);
        vec3 p = position * box;
        float fall = uFall;
        p.y = mod(p.y - uT * fall, box.y);
        p.xz += uWind * (box.y - p.y) / fall + (uFall < 3.0 ? vec2(sin(uT * 1.3 + id * 40.0), cos(uT * 1.1 + id * 31.0)) * 0.6 : vec2(0.0));
        vec3 base = uCam - box * 0.5;
        p.x = mod(p.x - base.x, box.x) + base.x;
        p.z = mod(p.z - base.z, box.z) + base.z;
        p.y += uCam.y - box.y * 0.5;
        p.y = max(p.y, 0.0);
        vec3 v = vec3(uWind.x, -fall, uWind.y);
        p += v * aEnd * uLen;
        vA = step(id, uN) * (1.0 - smoothstep(25.0, 45.0, length(p - uCam)));
        gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uCol;
      uniform float uA;
      varying float vA;
      void main() {
        if (vA < 0.01) discard;
        gl_FragColor = vec4(uCol, uA * vA);
        #include <colorspace_fragment>
      }`,
  });
  const lines = new THREE.LineSegments(g, mat);
  lines.frustumCulled = false;
  return {
    mesh: lines,
    update({ wall, camera, w, day }) {
      const snow = (w.snow || 0) > 0.05;
      const n = Math.min(1, (snow ? w.snow : w.rain) / 1.5);
      lines.visible = n > 0.02;
      mat.uniforms.uFall.value = snow ? 1.4 : 9;
      mat.uniforms.uLen.value = snow ? 0.05 : 0.06;
      mat.uniforms.uN.value = n;
      mat.uniforms.uT.value = wall;
      mat.uniforms.uCam.value.copy(camera.position);
      const wd = ((w.windDir ?? 180) + 180) * (Math.PI / 180);
      const ms = (w.windMs || 0) * 0.6;
      mat.uniforms.uWind.value.set(Math.sin(wd) * ms, -Math.cos(wd) * ms);
      mat.uniforms.uA.value = snow ? 0.75 : 0.18 + 0.22 * day;
      mat.uniforms.uCol.value.set(snow ? "#f4f6fa" : day > 0.3 ? "#cdd6de" : "#8d98a6");
    },
  };
}

const h1 = (x) => {
  const s = Math.sin(x * 127.1 + 311.7) * 43758.5453;
  return s - Math.floor(s);
};

/** Lightning only when the codes say thunderstorm: at most one flash every 4 s, each a short double pulse. */
export function lightningAt(wall, ts, reduced) {
  if (reduced || ts < 0.3) return null;
  const slot = Math.floor(wall / 4);
  if (h1(slot) > 0.35 + 0.35 * ts) return null;
  const at = slot * 4 + 0.4 + h1(slot + 0.5) * 2.8;
  const dt = wall - at;
  if (dt < 0 || dt > 0.45) return null;
  const f = dt < 0.08 ? 1 : dt < 0.16 ? 0.25 : dt < 0.24 ? 0.7 : Math.max(0, 0.7 - (dt - 0.24) * 3.3);
  const az = h1(slot + 0.25) * Math.PI * 2;
  return { f, dir: new THREE.Vector3(Math.sin(az), 0.35, -Math.cos(az)) };
}
