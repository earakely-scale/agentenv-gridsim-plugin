import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { fbm2, rng } from "./rng.js";

const DEG = Math.PI / 180;
const smooth = (a, b, x) => {
  const u = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return u * u * (3 - 2 * u);
};
export const NOISE_GLSL = /* glsl */ `
  float gHash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float gNoise(vec2 p) {
    vec2 i = floor(p), f = fract(p);
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(gHash(i), gHash(i + vec2(1, 0)), u.x), mix(gHash(i + vec2(0, 1)), gHash(i + vec2(1, 1)), u.x), u.y);
  }
  float gFbm(vec2 p) {
    float v = 0.0, a = 0.5;
    for (int k = 0; k < 5; k++) { v += a * gNoise(p); p = p * 2.03 + vec2(13.0, 7.0); a *= 0.5; }
    return v;
  }`;

/** Ground height (m) at world x, z for a region: flat at the yard, low swales (dunes in the west) in the middle
 * distance, hills or a caprock farther out. `flat(x, z)` is 1 where the land may move and 0 on the pad and road. */
export function heightFn(region, flat = () => 1) {
  const cap = region.turbines?.caprock;
  return (x, z) => {
    const r = Math.hypot(x, z);
    let h = (fbm2(x * 0.0011 + 3, z * 0.0011 + 9, 3) - 0.5) * 6 * smooth(350, 1500, r);
    const m = r < 2600 ? flat(x, z) * (1 - smooth(1800, 2600, r)) : 0;
    if (m > 0) {
      h += m * (fbm2(x * 0.0095 + 5, z * 0.0095 + 2, 3) - 0.5) * 3.6;
      if (region.dunes) {
        const w = fbm2(x * 0.0021 + 1, z * 0.0021 + 4, 2);
        const ridge = 1 - Math.abs(Math.sin((x * 0.83 + z * 0.56) * 0.034 + w * 6));
        h += m * smooth(0.45, 0.7, w) * ridge * ridge * 2.8;
      }
    }
    if (region.hills) {
      const b = Math.atan2(x, -z) / DEG;
      const off = Math.abs(((b - region.city.bearing + 540) % 360) - 180);
      h += Math.max(0, fbm2(x * 0.00042 + 11, z * 0.00042 + 5, 4) - 0.32) * 210 * region.hills * smooth(500, 3800, r) * (0.15 + 0.85 * smooth(6, 20, off));
    }
    if (cap) {
      const b = ((Math.atan2(x, -z) / DEG) + 360) % 360;
      const [a0, a1] = cap.span;
      const inSpan = a0 <= a1 ? b >= a0 && b <= a1 : b >= a0 || b <= a1;
      const edge = cap.km * 1000 + (fbm2(x * 0.0009, z * 0.0009, 3) - 0.5) * 1400;
      if (inSpan) h += cap.height * smooth(edge - 250, edge + 350, r);
      else {
        const da = Math.min(Math.abs(((b - a0 + 540) % 360) - 180), Math.abs(((b - a1 + 540) % 360) - 180));
        h += cap.height * smooth(edge - 250, edge + 350, r) * Math.max(0, 1 - da / 18);
      }
    }
    return h;
  };
}

function groundMaterial(region, U) {
  const m = new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.96, metalness: 0 });
  const [c0, c1, c2, c3] = region.ground.map((c) => new THREE.Color(c));
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, { uC0: { value: c0 }, uC1: { value: c1 }, uC2: { value: c2 }, uC3: { value: c3 }, uWet: U.uWet });
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWPos;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>\nvarying vec3 vWPos;\nuniform vec3 uC0, uC1, uC2, uC3;\nuniform float uWet;\n${NOISE_GLSL}`)
      .replace("#include <color_fragment>", `#include <color_fragment>
        vec2 wp = vWPos.xz;
        float px = length(fwidth(wp));
        float n1 = gFbm(wp * 0.0032);
        float n2 = gFbm(wp * 0.027 + 4.0);
        float n4 = gFbm(wp * 0.011 + 7.0);
        vec3 gc = mix(uC0, uC1, smoothstep(0.32, 0.68, n1));
        gc = mix(gc, uC2, smoothstep(0.48, 0.74, n2) * 0.75);
        gc = mix(gc, uC3, smoothstep(0.66, 0.86, n4) * 0.55);
        float fine = gNoise(wp * 0.55) * 0.6 + gNoise(wp * 2.3) * 0.4;
        gc *= mix(1.0, 0.8 + 0.4 * fine, 1.0 - smoothstep(0.2, 1.6, px));
        gc *= mix(1.0, 0.86 + 0.28 * gNoise(wp * 0.09), 1.0 - smoothstep(4.0, 30.0, px));
        float near = 1.0 - smoothstep(60.0, 400.0, px);
        gc = mix(gc, uC3, 0.3 * smoothstep(0.25, 1.3, vWPos.y) * near);
        gc *= 1.0 - 0.13 * smoothstep(0.2, -0.9, vWPos.y) * near;
        float puddle = smoothstep(0.62, 0.7, gFbm(wp * 0.06 + 2.0)) * uWet;
        gc *= 1.0 - 0.32 * uWet - 0.18 * puddle;
        diffuseColor.rgb *= gc;`)
      .replace("#include <roughnessmap_fragment>", `#include <roughnessmap_fragment>
        roughnessFactor = mix(roughnessFactor, 0.45, uWet * 0.6);
        roughnessFactor = mix(roughnessFactor, 0.08, smoothstep(0.62, 0.7, gFbm(vWPos.xz * 0.06 + 2.0)) * uWet);`);
  };
  return m;
}

function polarGround(heightAt, R = 70000, rings = 250, segs = 288) {
  const pos = [], idx = [];
  const radius = (i) => (i === 0 ? 0 : 1.6 * Math.pow(R / 1.6, (i - 1) / (rings - 2)));
  for (let i = 0; i < rings; i++) {
    const r = radius(i);
    for (let j = 0; j < segs; j++) {
      const a = (j / segs) * Math.PI * 2;
      const x = Math.cos(a) * r, z = Math.sin(a) * r;
      pos.push(x, heightAt(x, z) - (r > 30000 ? (r - 30000) * 0.004 : 0), z);
    }
  }
  for (let i = 0; i < rings - 1; i++)
    for (let j = 0; j < segs; j++) {
      const a = i * segs + j, b = i * segs + ((j + 1) % segs), c = (i + 1) * segs + j, d = (i + 1) * segs + ((j + 1) % segs);
      idx.push(a, b, c, b, d, c);
    }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  g.computeVertexNormals();
  return g;
}

function shrubGeometry(kind, r) {
  const parts = [];
  if (kind === "mesquite") {
    for (let i = 0; i < 7; i++) {
      const s = new THREE.IcosahedronGeometry(0.35 + r() * 0.3, 0);
      s.scale(1.1 + r() * 0.5, 0.7 + r() * 0.4, 1.1 + r() * 0.5);
      const a = r() * Math.PI * 2, rr = 0.3 + r() * 0.6;
      s.translate(Math.cos(a) * rr, 0.5 + r() * 0.9, Math.sin(a) * rr);
      parts.push(s);
    }
    for (let i = 0; i < 3; i++) {
      const t = new THREE.CylinderGeometry(0.03, 0.06, 1.1, 4);
      t.rotateZ((r() - 0.5) * 0.9);
      t.translate((r() - 0.5) * 0.4, 0.45, (r() - 0.5) * 0.4);
      parts.push(t);
    }
  } else if (kind === "creosote") {
    for (let i = 0; i < 5; i++) {
      const s = new THREE.IcosahedronGeometry(0.22 + r() * 0.18, 0);
      s.scale(1, 1.3 + r() * 0.5, 1);
      const a = r() * Math.PI * 2, rr = 0.15 + r() * 0.3;
      s.translate(Math.cos(a) * rr, 0.35 + r() * 0.4, Math.sin(a) * rr);
      parts.push(s);
    }
  } else if (kind === "juniper") {
    const s = new THREE.IcosahedronGeometry(0.8, 0);
    s.scale(1, 1.35, 1);
    s.translate(0, 1.0, 0);
    parts.push(s);
  } else {
    for (let i = 0; i < 9; i++) {
      const b = new THREE.ConeGeometry(0.05 + r() * 0.04, 0.5 + r() * 0.5, 3);
      b.translate(0, 0.3, 0);
      b.rotateZ((r() - 0.5) * 0.7);
      b.rotateX((r() - 0.5) * 0.7);
      const a = r() * Math.PI * 2, rr = r() * 0.3;
      b.translate(Math.cos(a) * rr, 0, Math.sin(a) * rr);
      parts.push(b);
    }
  }
  return mergeGeometries(parts.map((p) => p.toNonIndexed()));
}

function treeGeometry(kind) {
  const parts = [];
  if (kind === "pine") {
    const t = new THREE.CylinderGeometry(0.18, 0.3, 14, 5);
    t.translate(0, 7, 0);
    parts.push(t);
    for (let i = 0; i < 3; i++) {
      const c = new THREE.ConeGeometry(2.6 - i * 0.6, 4.2, 7);
      c.translate(0, 10 + i * 2.6, 0);
      parts.push(c);
    }
  } else {
    const t = new THREE.CylinderGeometry(0.22, 0.38, 3.2, 5);
    t.translate(0, 1.6, 0);
    parts.push(t);
    for (const [x, y, z, s] of [[0, 4.6, 0, 3.2], [1.6, 4.1, 0.6, 2.3], [-1.4, 4.2, -0.7, 2.4], [0.3, 5.4, -1.2, 2.0]]) {
      const c = new THREE.IcosahedronGeometry(s, 1);
      c.scale(1, 0.72, 1);
      c.translate(x, y, z);
      parts.push(c);
    }
  }
  return mergeGeometries(parts.map((p) => p.toNonIndexed()));
}

function scatter(group, { n, kind, r: [r0, r1] }, heightAt, avoid, seed, geomOf, palette, cams = []) {
  const r = rng(seed);
  const geom = geomOf(kind, r);
  const mat = new THREE.MeshStandardMaterial({ color: "#fff", roughness: 0.9, flatShading: true });
  const mesh = new THREE.InstancedMesh(geom, mat, n);
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), s = new THREE.Vector3(), p = new THREE.Vector3(), c = new THREE.Color();
  let k = 0;
  for (let tries = 0; k < n && tries < n * 6; tries++) {
    const rad = r0 + (r1 - r0) * Math.pow(r(), 1.7);
    const a = r() * Math.PI * 2;
    const x = Math.cos(a) * rad, z = Math.sin(a) * rad;
    if (avoid(x, z)) continue;
    if (fbm2(x * 0.004 + seed.length, z * 0.004, 3) < 0.33 + r() * 0.22) continue;
    if (cams.some(([cx, cz, cr]) => Math.hypot(x - cx, z - cz) < cr)) continue;
    const sc = kind === "oak" ? 1.5 + r() * 1.4 : kind === "pine" ? 0.55 + r() * 0.7 : kind === "mesquite" ? 0.7 + Math.pow(r(), 1.5) * 1.8 : 0.6 + r() * 0.9;
    p.set(x, heightAt(x, z) - 0.1, z);
    q.setFromAxisAngle(new THREE.Vector3(0, 1, 0), r() * Math.PI * 2);
    s.set(sc * (0.85 + r() * 0.3), sc * (0.8 + r() * 0.4), sc * (0.85 + r() * 0.3));
    mesh.setMatrixAt(k, m.compose(p, q, s));
    mesh.setColorAt(k, c.set(palette[Math.floor(r() * palette.length)]).multiplyScalar(0.85 + r() * 0.3));
    k++;
  }
  mesh.count = k;
  mesh.castShadow = true;
  mesh.receiveShadow = true;
  group.add(mesh);
  return mesh;
}

const SHRUB = { creosote: ["#6f7444", "#7a7a4a", "#65693e", "#858353"], mesquite: ["#4a4f31", "#545a37", "#5d5b3a", "#46482f", "#6a6544"], grass: ["#8e8c55", "#a09a62", "#7d8249", "#b0a66e"], juniper: ["#3c4a2e", "#36452c", "#465538"] };
const TREE = { oak: ["#4e6233", "#56693a", "#46592f"], pine: ["#3a4f2c", "#344828", "#40562f"] };

/** The land: the ground out to the horizon, the gravel pad, the access road, shrubs and trees. */
export function buildTerrain(region, { pad, yaw, seed, cams = [], level = null, keepOut = null }) {
  const group = new THREE.Group();
  const U = { uWet: { value: 0 } };
  const toLocal = (x, z) => [x * Math.cos(yaw) - z * Math.sin(yaw), x * Math.sin(yaw) + z * Math.cos(yaw)];
  const natural = heightFn(region, (x, z) => {
    const [lx, lz] = toLocal(x, z);
    let d = Math.hypot(Math.max(pad.x0 - lx, 0, lx - pad.x1), Math.max(pad.z0 - lz, 0, lz - pad.z1));
    if (lz > pad.z1) d = Math.min(d, Math.abs(lx - pad.roadX) - 4);
    return smooth(18, 110, d);
  });
  const heightAt = level ? (x, z) => natural(x, z) * (1 - level(x, z)) : natural;
  const ground = new THREE.Mesh(polarGround(heightAt), groundMaterial(region, U));
  ground.receiveShadow = true;
  group.add(ground);

  const avoid = (x, z) => {
    const [lx, lz] = toLocal(x, z);
    if (lx > pad.x0 - 30 && lx < pad.x1 + 30 && lz > pad.z0 - 30 && lz < pad.z1 + 30) return true;
    if (lx > pad.x1 && Math.abs(lz - pad.lineZ) < 45) return true;
    if (lz > pad.z1 && Math.abs(lx - pad.roadX) < 9) return true;
    return keepOut ? keepOut(x, z) : false;
  };
  const bigCams = cams.map(([x, z, r]) => [x, z, r * 2.2]);
  if (region.shrubs) scatter(group, region.shrubs, heightAt, avoid, `${seed}-shrub`, (k, r) => shrubGeometry(k, r), SHRUB[region.shrubs.kind] || SHRUB.grass, cams);
  if (region.shrubs2) scatter(group, region.shrubs2, heightAt, avoid, `${seed}-shrub2`, (k, r) => shrubGeometry(k, r), SHRUB[region.shrubs2.kind] || SHRUB.grass, cams);
  if (region.trees) scatter(group, region.trees, heightAt, avoid, `${seed}-tree`, (k) => treeGeometry(k), TREE[region.trees.kind] || TREE.oak, bigCams);
  return { group, heightAt, U, avoid };
}

/** Gravel with its own fine grain, darker and glossier when wet. */
export function gravelMaterial(color, U, { scale = 1.6, road = false } = {}) {
  const m = new THREE.MeshStandardMaterial({ color, roughness: 0.93 });
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uWet = U.uWet;
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWPos;")
      .replace("#include <begin_vertex>", "#include <begin_vertex>\nvWPos = (modelMatrix * vec4(transformed, 1.0)).xyz;");
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>\nvarying vec3 vWPos;\nuniform float uWet;\n${NOISE_GLSL}`)
      .replace("#include <color_fragment>", `#include <color_fragment>
        vec2 wp = vWPos.xz;
        float px = length(fwidth(wp));
        float g = gNoise(wp * ${(scale * 4).toFixed(2)}) * 0.5 + gNoise(wp * ${(scale * 11).toFixed(2)}) * 0.5;
        float big = gFbm(wp * 0.05);
        float gp = gFbm(wp * 0.013 + 3.0);
        diffuseColor.rgb *= mix(1.0, 0.82 + 0.36 * g, 1.0 - smoothstep(0.05, 0.6, px)) * (0.9 + 0.2 * big);
        diffuseColor.rgb *= mix(vec3(1.0), vec3(1.05, 1.02, 0.96), smoothstep(0.55, 0.75, gp)) * (1.0 - 0.07 * smoothstep(0.5, 0.3, gp));
        ${road ? "diffuseColor.rgb *= 0.92 + 0.12 * gNoise(wp * vec2(0.4, 3.0));" : ""}
        float puddle = smoothstep(0.6, 0.68, gFbm(wp * 0.11 + 9.0)) * uWet;
        diffuseColor.rgb *= 1.0 - 0.38 * uWet - 0.2 * puddle;`)
      .replace("#include <roughnessmap_fragment>", `#include <roughnessmap_fragment>
        float pd = smoothstep(0.6, 0.68, gFbm(vWPos.xz * 0.11 + 9.0)) * uWet;
        roughnessFactor = mix(roughnessFactor, 0.35, uWet * 0.7);
        roughnessFactor = mix(roughnessFactor, 0.04, pd);`);
  };
  return m;
}
