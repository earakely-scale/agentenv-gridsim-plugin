import * as THREE from "three";
import { glowTexture, inst, insulator, mat4, struts, V } from "./kit.js";

const SPAN = 330, ARM = 27.5, PH = [-7.5, 0, 7.5];

function towerGeometry() {
  const P = [];
  const leg = (y) => {
    const u = y / ARM;
    return 4.2 * (1 - u) + 1.0 * u;
  };
  const corners = (y) => {
    const w = leg(y);
    return [V(-w, y, -w), V(w, y, -w), V(w, y, w), V(-w, y, w)];
  };
  const levels = [0, 4, 8, 12, 16, 20, 23.5, ARM];
  for (let i = 0; i < levels.length - 1; i++) {
    const a = corners(levels[i]), b = corners(levels[i + 1]);
    for (let k = 0; k < 4; k++) {
      P.push([a[k], b[k]]);
      P.push([a[k], b[(k + 1) % 4]], [a[(k + 1) % 4], b[k]]);
      P.push([b[k], b[(k + 1) % 4]]);
    }
  }
  const top = corners(ARM);
  const w = 1.0;
  for (const s of [-1, 1]) {
    const tip = V(0, ARM + 0.6, s * 9.2);
    for (const c of [V(-w, ARM, s * w), V(w, ARM, s * w)]) P.push([c, tip]);
    for (const c of [V(-w, ARM - 2.6, s * w), V(w, ARM - 2.6, s * w)]) P.push([c, V(0, ARM, s * 9.2)]);
    P.push([V(0, ARM + 0.6, s * 4.8), V(0, ARM - 1.4, s * 4.8)]);
  }
  for (const c of top) P.push([c, V(0, ARM + 6, 0)]);
  P.push([V(0, ARM + 6, 0), V(0, ARM + 6.4, -3.5)], [V(0, ARM + 6, 0), V(0, ARM + 6.4, 3.5)]);
  return struts(P, 0.2);
}

function catenary(a, b, sag, n = 18) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const p = new THREE.Vector3().lerpVectors(a, b, u);
    p.y -= sag * 4 * u * (1 - u);
    pts.push(p);
  }
  return pts;
}

function pulseMaterial() {
  return new THREE.ShaderMaterial({
    transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, toneMapped: false,
    uniforms: { uColor: { value: new THREE.Color("#2fd3ff") }, uMap: { value: glowTexture() }, uScale: { value: 600 }, uSize: { value: 2.6 }, uI: { value: 1 }, uFog: { value: 1e-4 } },
    vertexShader: /* glsl */ `
      attribute float aA;
      uniform float uScale, uSize, uFog;
      varying float vA;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float d = -mv.z;
        vA = aA * exp(-d * uFog * 1.2);
        gl_PointSize = clamp(uSize * uScale / d, 3.5, 72.0);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform sampler2D uMap;
      uniform float uI;
      varying float vA;
      void main() {
        vec4 t = texture2D(uMap, gl_PointCoord);
        float core = smoothstep(0.55, 0.95, t.a);
        gl_FragColor = vec4((uColor * 1.6 + vec3(core) * 0.9) * t.a * vA * uI, 1.0);
      }`,
  });
}

/** The gen-tie: lattice towers from the substation's dead-end toward the city, its conductors and the power pulses
 * that run along them (cyan into the yard while charging, amber out while discharging). */
export function buildLine({ deadEnd, heightLocal, km = 9, seed }) {
  const group = new THREE.Group();
  const steel = new THREE.MeshStandardMaterial({ color: "#9aa2a6", roughness: 0.5, metalness: 0.7 });
  const geom = towerGeometry();
  const towers = [];
  const n = Math.round((km * 1000) / SPAN);
  for (let i = 0; i < n; i++) {
    const x = deadEnd.x + 140 + i * SPAN;
    const z = Math.sin(i * 0.11) * 6;
    towers.push(V(x, heightLocal(x, z), z));
  }
  group.add(inst(geom, steel, towers.map((p) => mat4(p))));
  const insM = [];
  for (const p of towers) for (const z of PH) insM.push(mat4(V(p.x, p.y + ARM - 0.2, p.z + z), 0, 1, Math.PI));
  group.add(inst(insulator(3.4, 0.12, 14), new THREE.MeshStandardMaterial({ color: "#8f969a", roughness: 0.4 }), insM, { shadow: false }));

  const wire = new THREE.LineBasicMaterial({ color: "#3c4247", transparent: true, opacity: 0.9 });
  const phases = PH.map((z, k) => {
    const pts = [];
    let prev = V(deadEnd.x + 0.3, deadEnd.y - 3.2, deadEnd.z[k]);
    pts.push(prev);
    for (const t of towers) {
      const a = V(t.x, t.y + ARM - 3.6, t.z + z);
      pts.push(...catenary(prev, a, Math.min(9, 0.018 * prev.distanceTo(a))).slice(1));
      prev = a;
    }
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wire));
    return pts;
  });
  for (const z of [-9.2, 9.2]) {
    const pts = [];
    let prev = null;
    for (const t of towers) {
      const a = V(t.x, t.y + ARM + 0.6, t.z + z);
      if (prev) pts.push(...catenary(prev, a, 0.012 * prev.distanceTo(a)).slice(1));
      else pts.push(a);
      prev = a;
    }
    group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: "#555b60", transparent: true, opacity: 0.6 })));
  }

  const paths = phases.map((pts) => {
    const cum = [0];
    for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + pts[i].distanceTo(pts[i - 1]));
    return { pts, cum, len: cum[cum.length - 1] };
  });
  const MAX = 150, TAIL = 9;
  const pos = new Float32Array(MAX * TAIL * 3), alpha = new Float32Array(MAX * TAIL);
  const pg = new THREE.BufferGeometry();
  pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  pg.setAttribute("aA", new THREE.BufferAttribute(alpha, 1));
  const pmat = pulseMaterial();
  const points = new THREE.Points(pg, pmat);
  points.frustumCulled = false;
  group.add(points);
  const hash = (i) => {
    const s = Math.sin(i * 91.345 + 7.13) * 43758.5453;
    return s - Math.floor(s);
  };
  const seeds = Array.from({ length: MAX }, (_, i) => hash(i));
  const jit = Array.from({ length: MAX }, (_, i) => 0.85 + 0.3 * hash(i + 500));
  let travel = 0;
  const _p = new THREE.Vector3();
  const at = (path, s, out) => {
    let lo = 0, hi = path.cum.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (path.cum[mid] < s) lo = mid;
      else hi = mid;
    }
    const u = (s - path.cum[lo]) / Math.max(1e-6, path.cum[hi] - path.cum[lo]);
    return out.lerpVectors(path.pts[lo], path.pts[hi], u);
  };

  /** dir: +1 out of the yard (discharge), -1 into it (charge), 0 idle; load 0..1. */
  function update({ dir, load, color, dt, fog, height, day, reduced }) {
    const speed = (70 + 260 * load) * (reduced ? 0.5 : 1);
    travel += dir * speed * dt;
    const per = Math.round((MAX / 3) * Math.min(1, 0.25 + 0.75 * load) * (dir && load > 0 ? 1 : 0));
    const visLen = 1700;
    let k = 0;
    for (let ph = 0; ph < 3; ph++) {
      const path = paths[ph];
      const len = Math.min(path.len, visLen);
      for (let i = 0; i < MAX / 3; i++) {
        const id = ph * (MAX / 3) + i;
        const on = i < per;
        const head = ((((seeds[id] + (travel * jit[id]) / len) % 1) + 1) % 1) * len;
        const fade = Math.min(1, head / 40) * Math.min(1, (len - head) / 400);
        for (let j = 0; j < TAIL; j++, k++) {
          if (!on) {
            alpha[k] = 0;
            continue;
          }
          const s = Math.max(0, Math.min(len, head - dir * j * 2.2));
          at(path, s, _p);
          pos[k * 3] = _p.x;
          pos[k * 3 + 1] = _p.y - 0.1;
          pos[k * 3 + 2] = _p.z;
          alpha[k] = fade * Math.pow(1 - j / TAIL, 1.6) * (j === 0 ? 1.2 : 0.8);
        }
      }
    }
    pg.attributes.position.needsUpdate = true;
    pg.attributes.aA.needsUpdate = true;
    pmat.uniforms.uColor.value.set(color);
    pmat.uniforms.uScale.value = height;
    pmat.uniforms.uFog.value = fog;
    pmat.uniforms.uSize.value = 2.4 + 1.4 * day;
    pmat.uniforms.uI.value = 0.55 + 0.6 * day;
    points.visible = per > 0;
  }
  return { group, towers, update, phases };
}
