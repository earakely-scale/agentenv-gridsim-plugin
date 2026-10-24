import * as THREE from "three";
import { box, canvasTexture, cyl, glowTexture, inst, insulator, mat4, merge, V } from "./kit.js";
import { pulseMaterial } from "./line.js";
import { rng } from "./rng.js";
import { gravelMaterial } from "./terrain.js";

/** A 1P single-axis tracker row: 90 modules of 1.13 m in portrait across a 2.38 m wide table, about 52 kWdc. */
const ROW = { len: 104, w: 2.38, kw: 52, pitch: 6.8, hub: 1.7, posts: 12 };
const BLOCK = { rows: 40, gap: 14, road: 10 };
const BX = BLOCK.rows * ROW.pitch + BLOCK.road;
const BZ = 2 * ROW.len + BLOCK.gap + BLOCK.road;
const GCR = ROW.w / ROW.pitch;
const MAX_TILT = 60;
const DEG = Math.PI / 180;
export const SOLAR = "#fff1bf";
export const CHARGE = "#2fd3ff";
export const DISCHARGE = "#ffa62b";

const smooth = (a, b, x) => {
  const u = Math.max(0, Math.min(1, (x - a) / (b - a)));
  return u * u * (3 - 2 * u);
};

/** Where the array stands for a site: tracker rows on a world-aligned block grid (axes north-south), grown outward
 * from the battery yard until the site's MWdc is placed, kept off the pad, the access road, the gen-tie corridor and
 * the collector feeder's road. Everything the terrain, the vegetation and the director need comes from here. */
export function plantLayout(site, L, yaw, seed) {
  const cos = Math.cos(yaw), sin = Math.sin(yaw);
  const toW = (lx, lz) => [lx * cos + lz * sin, -lx * sin + lz * cos];
  const toL = (x, z) => [x * cos - z * sin, x * sin + z * cos];
  const p = L.pad;
  const fx = L.sx - 15, feedLen = 560;
  const out = (lx, lz, m = 0) =>
    (lx > p.x0 - 16 - m && lx < p.x1 + 16 + m && lz > p.z0 - 16 - m && lz < p.z1 + 16 + m) ||
    (lz > p.z0 - 20 && Math.abs(lx - p.roadX) < 12 + m) ||
    (lx > p.x1 - 20 && Math.abs(lz) < 42 + m) ||
    (lz < p.z0 && lz > -feedLen - 30 && Math.abs(lx - fx) < 8 + m);
  const need = Math.round(((site.pv_mwdc || site.pv_mwac * 1.3) * 1000) / ROW.kw);
  let placed = 0;
  const [ox, oz] = toW(L.cx, 0);
  const r = rng(`${seed}-pv`);
  const K = Math.ceil(Math.sqrt(need / (2 * BLOCK.rows))) + 4;
  const cand = [];
  for (let i = -K; i <= K; i++)
    for (let j = -K; j <= K; j++) {
      const bx = ox + i * BX - BX / 2, bz = oz + j * BZ - BZ / 2;
      const [lx, lz] = toL(bx + BX / 2, bz + BZ / 2);
      cand.push({ bx, bz, s: Math.hypot(lx - L.cx, lz * 1.08) * (lx > p.x1 ? 1.9 : 1) * (0.92 + 0.16 * r()) });
    }
  cand.sort((a, b) => a.s - b.s);
  const rows = [], skids = [], blocks = [], roads = [];
  for (const c of cand) {
    if (placed >= need) break;
    let n = 0;
    const got = [];
    for (let half = 0; half < 2; half++) {
      const zc = c.bz + ROW.len / 2 + half * (ROW.len + BLOCK.gap);
      for (let k = 0; k < BLOCK.rows; k++) {
        if (placed + n >= need) break;
        const x = c.bx + ROW.pitch * (k + 0.5);
        const clear = (z0, z1) => [0, 0.25, 0.5, 0.75, 1].every((u) => [-1.3, 1.3].every((dx) => !out(...toL(x + dx, z0 + (z1 - z0) * u))));
        if (clear(zc - ROW.len / 2, zc + ROW.len / 2)) got.push({ x, z: zc, len: ROW.len }), n++;
        else for (const sgn of [-1, 1]) if (clear(zc + (sgn < 0 ? -ROW.len / 2 : 0), zc + (sgn < 0 ? 0 : ROW.len / 2))) got.push({ x, z: zc + (sgn * ROW.len) / 4, len: ROW.len / 2 }), (n += 0.5);
      }
    }
    if (n < 2) continue;
    const id = blocks.length;
    const rank = r();
    placed += n;
    for (const g of got) rows.push({ ...g, rank, block: id });
    blocks.push({ x0: c.bx, z0: c.bz, x1: c.bx + BX - BLOCK.road, z1: c.bz + BZ - BLOCK.road, rank, n });
    const sx = c.bx + BX / 2 - 6, sz = c.bz + ROW.len + BLOCK.gap / 2;
    if (n >= 24 && !out(...toL(sx, sz), 2)) skids.push({ x: sx, z: sz, block: id });
    roads.push({ x: c.bx + (BX - BLOCK.road) / 2, z: sz, w: BX - BLOCK.road, d: 7 });
  }
  const order = [...blocks.keys()].sort((a, b) => blocks[a].rank - blocks[b].rank);
  order.forEach((b, i) => (blocks[b].rank = (i + 0.5) / blocks.length));
  for (const row of rows) row.rank = blocks[row.block].rank;
  let ax0 = Infinity, ax1 = -Infinity, az0 = Infinity, az1 = -Infinity;
  for (const b of blocks) (ax0 = Math.min(ax0, b.x0)), (ax1 = Math.max(ax1, b.x1)), (az0 = Math.min(az0, b.z0)), (az1 = Math.max(az1, b.z1));
  const dist = (x, z) => {
    let best = Infinity;
    for (const b of blocks) {
      const dx = Math.max(b.x0 - x, 0, x - b.x1), dz = Math.max(b.z0 - z, 0, z - b.z1);
      best = Math.min(best, Math.hypot(dx, dz));
      if (best === 0) break;
    }
    return best;
  };
  const level = (x, z) => (x < ax0 - 80 || x > ax1 + 80 || z < az0 - 80 || z > az1 + 80 ? 0 : 1 - smooth(10, 75, dist(x, z)));
  const keepOut = (x, z) => !(x < ax0 - 8 || x > ax1 + 8 || z < az0 - 8 || z > az1 + 8) && dist(x, z) < 6;
  const near = rows.map((w) => ({ w, l: toL(w.x, w.z) })).filter(({ l }) => l[0] < L.cx - 30 && l[1] < p.z0 - 30).sort((a, b) => Math.hypot(a.l[0] - L.cx, a.l[1]) - Math.hypot(b.l[0] - L.cx, b.l[1]))[0];
  const aisle = near ? toL(near.w.x + ROW.pitch / 2, near.w.z) : [L.cx - 120, p.z0 - 80];
  const along = toL(0, 1);
  return { rows, skids, blocks, roads, need, placed, level, keepOut, toW, toL, fx, feedLen, aisle, along, out, mwdc: (placed * ROW.kw) / 1000 };
}

function moduleTexture() {
  return canvasTexture(128, 256, (g, w, h) => {
    g.fillStyle = "#b9c0c4";
    g.fillRect(0, 0, w, h);
    g.fillStyle = "#2a3646";
    g.fillRect(3, 3, w - 6, h - 6);
    const cw = (w - 8) / 6, ch = (h - 10) / 24;
    for (let i = 0; i < 6; i++)
      for (let j = 0; j < 24; j++) {
        const x = 4 + i * cw, y = 5 + j * ch + (j >= 12 ? 2 : 0);
        g.fillStyle = (i + j) % 2 ? "#141d29" : "#16202d";
        g.fillRect(x + 0.6, y + 0.5, cw - 1.2, ch - 1);
        g.fillStyle = "rgba(150,165,180,0.12)";
        g.fillRect(x + cw * 0.32, y + 0.5, 0.8, ch - 1);
        g.fillRect(x + cw * 0.66, y + 0.5, 0.8, ch - 1);
      }
  }, { aniso: 12 });
}

/** Panel materials that turn about the torque tube by uTilt, or toward uStow for blocks whose rank is under uOff. */
function tracking(m, U, depth = false) {
  m.onBeforeCompile = (sh) => {
    sh.uniforms.uTilt = U.uTilt;
    sh.uniforms.uStow = U.uStow;
    sh.uniforms.uOff = U.uOff;
    sh.vertexShader = sh.vertexShader.replace("#include <common>", `#include <common>
      attribute float aRank;
      uniform float uTilt, uStow, uOff;
      mat2 trk() { float o = smoothstep(aRank - 0.03, aRank + 0.03, uOff); float a = mix(uTilt, uStow, o); float c = cos(a), s = sin(a); return mat2(c, s, -s, c); }`)
      .replace("#include <begin_vertex>", "#include <begin_vertex>\ntransformed.xy = trk() * transformed.xy;");
    if (!depth) sh.vertexShader = sh.vertexShader.replace("#include <beginnormal_vertex>", "#include <beginnormal_vertex>\nobjectNormal.xy = trk() * objectNormal.xy;");
  };
  m.customProgramCacheKey = () => (depth ? "trk-depth" : "trk");
  return m;
}

function gaugeMaterial() {
  return new THREE.ShaderMaterial({
    uniforms: { uPv: { value: 0 }, uBat: { value: 0 }, uImp: { value: 0 }, uHead: { value: 0 }, uGlow: { value: 1 } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }",
    fragmentShader: /* glsl */ `
      uniform float uPv, uBat, uImp, uHead, uGlow;
      varying vec2 vUv;
      void main() {
        vec2 p = vUv;
        vec3 frame = vec3(0.08, 0.09, 0.1);
        float inner = step(0.36, p.x) * step(p.x, 0.86) * step(0.03, p.y) * step(p.y, 0.97);
        float z = 0.2;
        float y = (p.y - 0.03) / 0.94;
        float tu = (y - z) / (1.0 - z);
        float f = abs(fract(tu * 10.0 + 0.5) - 0.5);
        float tick = step(-0.01, tu) * step(tu, 1.01) * (1.0 - step(0.07, f)) * step(0.14, p.x) * step(p.x, 0.3);
        vec3 ink = vec3(0.75) * (1.0 + 0.5 * uGlow);
        float up = (y - z) / (1.0 - z), dn = (z - y) / z;
        vec3 off = vec3(0.15, 0.17, 0.18);
        vec3 c = off;
        float k = 1.1 + 0.7 * uGlow;
        if (up >= 0.0) {
          if (up < uPv) c = vec3(1.0, 0.93, 0.72) * k;
          else if (up < uPv + uBat) c = vec3(1.0, 0.62, 0.15) * k;
          float hb = step(1.0 - uHead, up) * step(0.002, uHead);
          float hatch = step(0.5, fract((p.x + p.y * 0.6) * 22.0));
          c = mix(c, mix(c, vec3(0.92) * k * 0.7, 0.55), hb * hatch);
        } else if (dn < uImp) c = vec3(0.18, 0.83, 1.0) * k;
        float zl = 1.0 - smoothstep(0.0, 0.01, abs(y - z));
        float top = 1.0 - smoothstep(0.0, 0.012, abs(y - 0.985));
        c = mix(c, vec3(0.9), zl * 0.8);
        c = mix(c, vec3(1.0, 0.35, 0.25) * 1.6, top);
        vec3 col = mix(frame, c, inner);
        col = mix(col, ink, tick * (1.0 - inner));
        gl_FragColor = vec4(col, 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

function plateTexture(text) {
  return canvasTexture(256, 96, (g, w, h) => {
    g.fillStyle = "#f2f2ee";
    g.fillRect(0, 0, w, h);
    g.strokeStyle = "#1c2329";
    g.lineWidth = 5;
    g.strokeRect(6, 6, w - 12, h - 12);
    g.fillStyle = "#1c2329";
    g.font = "700 34px Helvetica, Arial, sans-serif";
    g.textAlign = "center";
    g.fillText(text, w / 2, 58);
  });
}

function louvre(base) {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    for (let y = 34; y < h - 34; y += 10) {
      g.fillStyle = "rgba(30,34,38,0.5)";
      g.fillRect(28, y, w - 56, 4);
    }
    g.strokeStyle = "rgba(40,44,48,0.45)";
    g.lineWidth = 3;
    g.strokeRect(12, 12, w - 24, h - 24);
  });
}

function catenary(a, b, sag, n = 14) {
  const pts = [];
  for (let i = 0; i <= n; i++) {
    const u = i / n;
    const q = new THREE.Vector3().lerpVectors(a, b, u);
    q.y -= sag * 4 * u * (1 - u);
    pts.push(q);
  }
  return pts;
}

/** Comet pulses along polylines, as on the gen-tie: dir +1 runs from the first point to the last. */
function pulses(paths, per = 18) {
  const TAIL = 7, n = paths.length * per;
  const ps = paths.map((pts) => {
    const c = [0];
    for (let i = 1; i < pts.length; i++) c.push(c[i - 1] + pts[i].distanceTo(pts[i - 1]));
    return { pts, cum: c, len: c.at(-1) };
  });
  const pos = new Float32Array(n * TAIL * 3), alpha = new Float32Array(n * TAIL);
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  g.setAttribute("aA", new THREE.BufferAttribute(alpha, 1));
  const mat = pulseMaterial();
  const points = new THREE.Points(g, mat);
  points.frustumCulled = false;
  const hash = (i) => {
    const s = Math.sin(i * 57.31 + 3.7) * 43758.5453;
    return s - Math.floor(s);
  };
  const seeds = Array.from({ length: n }, (_, i) => hash(i)), jit = Array.from({ length: n }, (_, i) => 0.85 + 0.3 * hash(i + 300));
  const _p = new THREE.Vector3();
  const at = (path, s) => {
    let lo = 0, hi = path.cum.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (path.cum[mid] < s) lo = mid;
      else hi = mid;
    }
    return _p.lerpVectors(path.pts[lo], path.pts[hi], (s - path.cum[lo]) / Math.max(1e-6, path.cum[hi] - path.cum[lo]));
  };
  let travel = 0;
  return {
    points,
    update({ dir, load, color, dt, height, fog, day, reduced, speed = 40 }) {
      travel += dir * (speed + speed * 3 * load) * (reduced ? 0.5 : 1) * dt;
      const on = Math.round(per * Math.min(1, 0.2 + 0.8 * load) * (dir && load > 0.004 ? 1 : 0));
      let k = 0;
      ps.forEach((path, pi) => {
        for (let i = 0; i < per; i++) {
          const id = pi * per + i;
          const head = ((((seeds[id] + (travel * jit[id]) / path.len) % 1) + 1) % 1) * path.len;
          const fade = Math.min(1, head / 6) * Math.min(1, (path.len - head) / 6);
          for (let j = 0; j < TAIL; j++, k++) {
            if (i >= on) {
              alpha[k] = 0;
              continue;
            }
            const q = at(path, Math.max(0, Math.min(path.len, head - dir * j * 1.4)));
            pos[k * 3] = q.x;
            pos[k * 3 + 1] = q.y - 0.08;
            pos[k * 3 + 2] = q.z;
            alpha[k] = fade * Math.pow(1 - j / TAIL, 1.6) * (j === 0 ? 1.2 : 0.8);
          }
        }
      });
      g.attributes.position.needsUpdate = true;
      g.attributes.aA.needsUpdate = true;
      mat.uniforms.uColor.value.set(color);
      mat.uniforms.uScale.value = height;
      mat.uniforms.uFog.value = fog;
      mat.uniforms.uSize.value = 1.5 + 0.9 * day;
      mat.uniforms.uI.value = 0.6 + 0.6 * day;
      points.visible = on > 0;
    },
  };
}

/** Single-axis tracking with backtracking (flat ground): the rotation (degrees, + toward east) for a sun at el, az. */
export function trackerAngle(el, az) {
  if (el <= 0.5) return 0;
  const e = el * DEG, a = az * DEG;
  const sx = Math.sin(a) * Math.cos(e), sy = Math.sin(e);
  const ideal = Math.atan2(sx, sy);
  const t = Math.cos(ideal) / GCR;
  const th = t < 1 ? ideal - Math.sign(ideal) * Math.acos(t) : ideal;
  return Math.max(-MAX_TILT, Math.min(MAX_TILT, th / DEG));
}

/** The solar farm and the plant's power path, built from plantLayout: tracker tables that follow the sun, posts and
 * torque tubes, block roads, inverter and MV transformer skids, the 34.5 kV collector feeders into the substation, the
 * link from the substation to the battery yard and the POI meter cabinet. world holds what stands on the world grid,
 * local what sits in the site frame. */
export function buildPlant(P, L, { site, U: wetU, heightAt, sub }) {
  const world = new THREE.Group(), local = new THREE.Group();
  const U = { uTilt: { value: 0 }, uStow: { value: 0 }, uOff: { value: 0 } };
  const tex = moduleTexture();
  tex.wrapS = THREE.RepeatWrapping;
  tex.repeat.set(90, 1);
  const glass = tracking(new THREE.MeshStandardMaterial({ map: tex, roughness: 0.2, metalness: 0.0, envMapIntensity: 0.5 }), U);
  const back = tracking(new THREE.MeshStandardMaterial({ color: "#5d666c", roughness: 0.6, metalness: 0.2 }), U);
  const rim = tracking(new THREE.MeshStandardMaterial({ color: "#c4cacd", roughness: 0.35, metalness: 0.7 }), U);
  const depth = tracking(new THREE.MeshDepthMaterial({ depthPacking: THREE.RGBADepthPacking }), U, true);
  const steel = new THREE.MeshStandardMaterial({ color: "#9ea6aa", roughness: 0.45, metalness: 0.6 });
  const panels = [];
  for (const len of [ROW.len, ROW.len / 2]) {
    const rs = P.rows.filter((w) => w.len === len);
    if (!rs.length) continue;
    const table = new THREE.BoxGeometry(len, 0.045, ROW.w);
    table.translate(0, 0.16, 0);
    table.rotateY(Math.PI / 2);
    const g = len === ROW.len ? glass : glass.clone();
    if (g !== glass) (g.map = tex.clone()), g.map.repeat.set(45, 1), (g.onBeforeCompile = glass.onBeforeCompile), (g.customProgramCacheKey = glass.customProgramCacheKey);
    const ms = rs.map((w) => mat4(V(w.x, heightAt(w.x, w.z) + ROW.hub, w.z)));
    const mesh = inst(table, [rim, rim, g, back, rim, rim], ms);
    mesh.geometry.setAttribute("aRank", new THREE.InstancedBufferAttribute(new Float32Array(rs.map((w) => w.rank)), 1));
    mesh.customDepthMaterial = depth;
    world.add(mesh, inst(cyl(0.065, 0.065, len, 0, 0, 0, 7, "z"), steel, ms, { shadow: false }));
    panels.push(mesh);
  }
  const [cx, cz] = P.toW(L.cx, 0);
  const postM = [], motorM = [];
  for (const w of P.rows) {
    if (Math.hypot(w.x - cx, w.z - cz) > 900) continue;
    const y0 = heightAt(w.x, w.z);
    const np = w.len === ROW.len ? ROW.posts : ROW.posts / 2;
    for (let i = 0; i < np; i++) postM.push(mat4(V(w.x, y0 + ROW.hub / 2, w.z - w.len / 2 + 3 + (i * (w.len - 6)) / (np - 1))));
    motorM.push(mat4(V(w.x + 0.18, y0 + ROW.hub - 0.15, w.z)));
  }
  world.add(inst(box(0.16, ROW.hub, 0.12), steel, postM, { shadow: false }));
  world.add(inst(box(0.32, 0.36, 0.5), new THREE.MeshStandardMaterial({ color: "#5c6368", roughness: 0.6, metalness: 0.4 }), motorM, { shadow: false }));
  const roadMat = gravelMaterial("#b9ad97", wetU, { scale: 1.2, road: true });
  const roadM = P.roads.map((r) => mat4(V(r.x, heightAt(r.x, r.z) + 0.06, r.z), 0, V(r.w, 1, r.d)));
  const road = inst(new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2), roadMat, roadM, { shadow: false });
  world.add(road);

  const concrete = new THREE.MeshStandardMaterial({ color: "#bcb8af", roughness: 0.92 });
  const cabinet = new THREE.MeshStandardMaterial({ map: louvre("#e3e5e2"), roughness: 0.5, metalness: 0.2 });
  const padmount = new THREE.MeshStandardMaterial({ color: "#6f7d6b", roughness: 0.55, metalness: 0.35 });
  const sp = [], sc = [], st = [], sf = [], sl = [];
  for (const s of P.skids) {
    const y = heightAt(s.x, s.z);
    sp.push(mat4(V(s.x, y + 0.15, s.z), 0, V(3.4, 0.3, 8.2)));
    sc.push(mat4(V(s.x, y + 0.3 + 1.2, s.z - 1.9)));
    st.push(mat4(V(s.x, y + 0.3 + 1.05, s.z + 1.9)));
    for (let i = 0; i < 6; i++) for (const side of [-1, 1]) sf.push(mat4(V(s.x + side * 1.12, y + 1.3, s.z + 1.2 + i * 0.26)));
    sl.push(mat4(V(s.x + 1.23, y + 2.35, s.z - 1.9)));
  }
  world.add(inst(new THREE.BoxGeometry(1, 1, 1), concrete, sp));
  world.add(inst(new THREE.BoxGeometry(2.4, 2.4, 3.6), cabinet, sc));
  world.add(inst(new THREE.BoxGeometry(2.1, 2.1, 2.2), padmount, st));
  world.add(inst(new THREE.BoxGeometry(0.35, 1.6, 0.05), padmount, sf));
  const led = new THREE.MeshStandardMaterial({ color: "#111", emissive: new THREE.Color("#7dffa8"), emissiveIntensity: 1.6 });
  world.add(inst(new THREE.BoxGeometry(0.04, 0.06, 0.5), led, sl, { shadow: false }));

  const wood = new THREE.MeshStandardMaterial({ color: "#6e5d4b", roughness: 0.85 });
  const arm = new THREE.MeshStandardMaterial({ color: "#7a6a58", roughness: 0.8 });
  const polymer = new THREE.MeshStandardMaterial({ color: "#8d9396", roughness: 0.45 });
  const wire = new THREE.LineBasicMaterial({ color: "#3a4045", transparent: true, opacity: 0.7 });
  const poles = [];
  for (let z = -18; z >= -P.feedLen; z -= 52) poles.push(V(P.fx, 0, z));
  const poleM = [], armM = [], insM = [];
  const tipsOf = (q) => [-1.5, 0, 1.5].flatMap((dx) => [V(q.x + dx, q.y + 12.6, q.z), V(q.x + dx, q.y + 11.2, q.z)]);
  for (const q of poles) {
    q.y = heightAt(...P.toW(q.x, q.z));
    poleM.push(mat4(V(q.x, q.y + 6.5, q.z)));
    for (const y of [12.45, 11.05]) armM.push(mat4(V(q.x, q.y + y, q.z)));
    for (const t of tipsOf(q)) insM.push(mat4(t.clone().setY(t.y - 0.25)));
  }
  local.add(inst(cyl(0.14, 0.2, 13, 0, 0, 0, 8), wood, poleM));
  local.add(inst(box(3.6, 0.14, 0.14), arm, armM));
  local.add(inst(insulator(0.32, 0.07, 3), polymer, insM, { shadow: false }));
  const land = V(sub.lowX, 6.8, -2.6);
  const feeders = [];
  for (const c of [0, 2, 4]) {
    const pts = [V(land.x + [-1.5, -1.5, 0, 0, 1.5, 1.5][c], land.y - (c % 2) * 0.6, land.z)];
    let prev = pts[0];
    for (const q of poles) {
      const a = tipsOf(q)[c];
      pts.push(...catenary(prev, a, Math.min(1.6, 0.012 * prev.distanceTo(a))).slice(1));
      prev = a;
    }
    local.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wire));
    feeders.push(pts.slice().reverse());
  }
  const feed = pulses(feeders, 22);
  local.add(feed.points);

  const yx = L.cx + L.W / 2 + 5;
  const riser = V(yx, 0, 6);
  const linkPoles = [V(yx, 0, 6), V((yx + sub.lowX) / 2, 0, 9)];
  const lp = [], la = [];
  for (const q of linkPoles) {
    lp.push(mat4(V(q.x, 5.5, q.z), 0, V(1, 11 / 13, 1)));
    la.push(mat4(V(q.x, 10.6, q.z), Math.PI / 2, V(0.8, 1, 1)));
  }
  local.add(inst(cyl(0.14, 0.2, 13, 0, 0, 0, 8), wood, lp));
  local.add(inst(box(3.6, 0.14, 0.14), arm, la));
  const links = [-1.2, 0, 1.2].map((dz) => {
    const pts = [V(sub.lowX, 6.8, 2.6 + dz * 0.6)];
    let prev = pts[0];
    for (const q of [...linkPoles].reverse()) {
      const a = V(q.x, 10.75, q.z + dz);
      pts.push(...catenary(prev, a, 0.4).slice(1));
      prev = a;
    }
    pts.push(V(riser.x, 1.0, riser.z + dz * 0.4));
    local.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), wire));
    return pts;
  });
  const link = pulses(links, 10);
  local.add(link.points);

  const mx = sub.deX - 5, mz = 11.5;
  const cab = new THREE.Mesh(box(1.5, 2.2, 0.9, mx, 1.1 + 0.3, mz), new THREE.MeshStandardMaterial({ color: "#d9dcd8", roughness: 0.5, metalness: 0.25 }));
  cab.castShadow = true;
  const base = new THREE.Mesh(box(2.0, 0.3, 1.4, mx, 0.15, mz), concrete);
  const gauge = gaugeMaterial();
  const face = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 1.55), gauge);
  face.position.set(mx - 0.25, 1.45, mz + 0.46);
  const plate = new THREE.Mesh(new THREE.PlaneGeometry(0.62, 0.23), new THREE.MeshStandardMaterial({ map: plateTexture(`POI ${Math.round(site.poi_mw)} MW`), roughness: 0.6 }));
  plate.position.set(mx + 0.42, 2.05, mz + 0.46);
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: SOLAR, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
  glow.position.set(mx - 0.25, 1.45, mz + 0.9);
  glow.scale.set(2.2, 3.2, 1);
  local.add(cab, base, face, plate, glow);

  let tilt = 0;
  /** state: tilt (deg), off (0..1 of blocks off sun), stow (deg), pv (MW reaching the bus), net (+ discharge MW),
   * exp (meter MW), head (MW of up-award headroom at the meter). */
  function update({ tilt: deg, off, pv, net, exp, head, night, dt, height, fog, day, reduced }) {
    tilt = deg;
    U.uTilt.value = -tilt * DEG;
    U.uStow.value = 0;
    U.uOff.value = off;
    const Lm = Math.max(1, site.poi_mw);
    feed.update({ dir: 1, load: Math.max(0, pv) / Math.max(1, site.pv_mwac), color: SOLAR, dt, height, fog, day, reduced, speed: 26 });
    link.update({ dir: net > 0 ? -1 : 1, load: Math.abs(net) > 0.5 ? Math.abs(net) / site.bess.p_mw : 0, color: net > 0 ? DISCHARGE : CHARGE, dt, height, fog, day, reduced, speed: 14 });
    const g = gauge.uniforms;
    const toBat = Math.max(0, Math.min(exp, net));
    g.uPv.value = Math.max(0, exp - toBat) / Lm;
    g.uBat.value = Math.max(0, toBat) / Lm;
    g.uImp.value = Math.max(0, -exp) / Math.max(1, site.poi_import_mw || Lm);
    g.uHead.value = Math.min(1, Math.max(0, head) / Lm);
    g.uGlow.value = night;
    glow.material.opacity = (0.15 + 0.5 * night) * Math.min(1, Math.abs(exp) / Lm);
    glow.material.color.set(exp < 0 ? CHARGE : net > 0.5 ? DISCHARGE : SOLAR);
  }
  return { world, local, update, U, panels, meter: V(mx, 1.4, mz), riser, poles };
}
