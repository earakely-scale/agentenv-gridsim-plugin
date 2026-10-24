import * as THREE from "three";
import { box, canvasTexture, cyl, glowTexture, insulator, inst, mat4, merge, struts, V } from "./kit.js";
import { gravelMaterial } from "./terrain.js";

export const COLORS = { charge: "#2fd3ff", discharge: "#ffa62b", idle: "#eef2f0", violation: "#ff4b3e", grey: "#5d6266" };
const ENC = { L: 6.06, W: 2.44, H: 2.9, F: 0.3 };
const BLOCK = 20.5, GAPX = 3.5, PITCH = 9.2;

/** Where everything stands for a battery of E MWh and P MW, in the site frame (+x toward the line). */
export function layout(b) {
  const n = Math.max(4, Math.min(140, Math.round(b.energy_mwh / 4.6)));
  const blocks = Math.ceil(n / 2);
  const cols = Math.max(2, Math.ceil(Math.sqrt(blocks / 1.4)));
  const rows = Math.ceil(blocks / cols);
  const W = cols * BLOCK + (cols - 1) * GAPX, D = rows * PITCH;
  const cx = -W / 2 - 22;
  const enc = [], skids = [];
  let k = 0;
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++) {
      if (k >= n) break;
      const x0 = cx - W / 2 + c * (BLOCK + GAPX), z = -D / 2 + PITCH * (r + 0.5);
      skids.push({ x: x0 + BLOCK / 2, z });
      enc.push({ x: x0 + ENC.L / 2, z, end: -1 });
      k++;
      if (k < n) enc.push({ x: x0 + BLOCK - ENC.L / 2, z, end: 1 }), k++;
    }
  const sx = cx + W / 2 + 34;
  const pad = { x0: cx - W / 2 - 16, x1: sx + 32, z0: -Math.max(D / 2, 24) - 14, z1: Math.max(D / 2, 24) + 22 };
  return { n, blocks, cols, rows, W, D, cx, enc, skids, sx, pad: { ...pad, lineZ: 0, roadX: pad.x0 + 22 }, mwPerSkid: b.p_dis_mw / skids.length };
}

function doorTexture() {
  return canvasTexture(1024, 512, (g, w, h) => {
    g.fillStyle = "#f1f2ef";
    g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 22) {
      g.fillStyle = "rgba(0,0,0,0.035)";
      g.fillRect(x, 0, 9, h);
    }
    g.fillStyle = "#d5d8d6";
    g.fillRect(0, h - 26, w, 26);
    g.fillRect(0, 0, w, 14);
    const doors = [[60, 300], [380, 300], [700, 300]];
    for (const [x, dw] of doors) {
      g.strokeStyle = "rgba(60,64,66,0.55)";
      g.lineWidth = 3;
      g.strokeRect(x, 40, dw - 30, h - 80);
      g.beginPath();
      g.moveTo(x + (dw - 30) / 2, 40);
      g.lineTo(x + (dw - 30) / 2, h - 40);
      g.stroke();
      g.fillStyle = "#7b8084";
      g.fillRect(x + (dw - 30) / 2 - 22, h / 2 - 34, 8, 68);
      g.fillRect(x + (dw - 30) / 2 + 14, h / 2 - 34, 8, 68);
      g.fillStyle = "rgba(70,74,78,0.5)";
      for (let i = 0; i < 6; i++) g.fillRect(x + 22, 80 + i * 13, 70, 5);
    }
    g.fillStyle = "#f2c230";
    g.beginPath();
    g.moveTo(330, 150);
    g.lineTo(350, 116);
    g.lineTo(370, 150);
    g.closePath();
    g.fill();
    g.fillStyle = "#222";
    g.fillRect(348, 128, 4, 12);
    g.fillRect(348, 143, 4, 4);
  });
}

function plainTexture(tone = "#eceeeb") {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = tone;
    g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 16) {
      g.fillStyle = "rgba(0,0,0,0.04)";
      g.fillRect(x, 0, 6, h);
    }
  });
}

function louvreTexture(base) {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    for (let y = 30; y < h - 30; y += 9) {
      g.fillStyle = "rgba(30,34,38,0.55)";
      g.fillRect(24, y, w - 48, 4);
    }
    g.strokeStyle = "rgba(40,44,48,0.5)";
    g.lineWidth = 3;
    g.strokeRect(10, 10, w - 20, h - 20);
  });
}

function gaugeMaterial(levels) {
  return new THREE.ShaderMaterial({
    uniforms: { uSoc: { value: 0.5 }, uEnd: { value: 0.5 }, uLevels: { value: levels }, uGrey: { value: 0 }, uGlow: { value: 1 } },
    vertexShader: /* glsl */ `
      varying vec2 vUv;
      void main() {
        vUv = uv;
        gl_Position = projectionMatrix * modelViewMatrix * instanceMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: /* glsl */ `
      uniform float uSoc, uEnd, uLevels, uGrey, uGlow;
      varying vec2 vUv;
      void main() {
        vec2 p = vUv;
        vec3 frame = vec3(0.09, 0.1, 0.11);
        float inner = step(0.12, p.x) * step(p.x, 0.88) * step(0.04, p.y) * step(p.y, 0.96);
        float y = (p.y - 0.04) / 0.92;
        float seg = floor(y * uLevels);
        float within = fract(y * uLevels);
        float gap = step(0.1, within) * step(within, 0.92);
        float filled = step(seg + 1.0, uSoc + 0.001) + step(seg, uSoc) * (1.0 - step(seg + 1.0, uSoc + 0.001)) * step(within, fract(uSoc));
        vec3 on = mix(vec3(0.2, 0.95, 0.5), vec3(0.62, 0.66, 0.66), uGrey) * (1.2 + 0.6 * uGlow);
        vec3 off = vec3(0.16, 0.19, 0.2);
        vec3 c = mix(off, on, filled) * gap;
        float mark = 1.0 - smoothstep(0.0, 0.012, abs(y - uEnd / uLevels));
        c = mix(c, vec3(1.0, 0.85, 0.35) * 1.6, mark);
        gl_FragColor = vec4(mix(frame, c, inner), 1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  });
}

/** The battery yard, its substation, fence, lights and O&M building. update(state) drives lights, fans and gauges. */
export function buildYard(battery, U, { gravel = "#a7a39b", seed = "yard" } = {}) {
  const L = layout(battery);
  const group = new THREE.Group();
  const white = [
    new THREE.MeshStandardMaterial({ map: plainTexture(), roughness: 0.5, metalness: 0.15 }),
    new THREE.MeshStandardMaterial({ map: plainTexture(), roughness: 0.5, metalness: 0.15 }),
    new THREE.MeshStandardMaterial({ map: plainTexture("#e4e6e3"), roughness: 0.55, metalness: 0.1 }),
    new THREE.MeshStandardMaterial({ color: "#555", roughness: 0.9 }),
    new THREE.MeshStandardMaterial({ map: doorTexture(), roughness: 0.48, metalness: 0.15 }),
    new THREE.MeshStandardMaterial({ map: plainTexture(), roughness: 0.5, metalness: 0.15 }),
  ];
  const steel = new THREE.MeshStandardMaterial({ color: "#b9bfc2", roughness: 0.5, metalness: 0.45 });
  const dark = new THREE.MeshStandardMaterial({ color: "#26292c", roughness: 0.7, metalness: 0.3 });
  const concrete = new THREE.MeshStandardMaterial({ color: "#bdb9b0", roughness: 0.92 });
  const xfmr = new THREE.MeshStandardMaterial({ color: "#7d878a", roughness: 0.5, metalness: 0.45 });
  const padmount = new THREE.MeshStandardMaterial({ color: "#73806f", roughness: 0.55, metalness: 0.35 });
  const porcelain = new THREE.MeshStandardMaterial({ color: "#6b4d3c", roughness: 0.3, metalness: 0.05 });
  const polymer = new THREE.MeshStandardMaterial({ color: "#8d9396", roughness: 0.45 });
  const cabinet = new THREE.MeshStandardMaterial({ map: louvreTexture("#dde0de"), roughness: 0.5, metalness: 0.2 });
  const hvacMat = new THREE.MeshStandardMaterial({ map: louvreTexture("#e7e9e6"), roughness: 0.5, metalness: 0.2 });

  const pad = new THREE.Mesh(new THREE.PlaneGeometry(L.pad.x1 - L.pad.x0, L.pad.z1 - L.pad.z0), gravelMaterial(gravel, U));
  pad.rotation.x = -Math.PI / 2;
  pad.position.set((L.pad.x0 + L.pad.x1) / 2, 0.04, (L.pad.z0 + L.pad.z1) / 2);
  pad.receiveShadow = true;
  group.add(pad);
  const roadMat = gravelMaterial("#b6a98f", U, { scale: 1.1, road: true });
  const road = new THREE.Mesh(new THREE.PlaneGeometry(7, 1600), roadMat);
  road.rotation.x = -Math.PI / 2;
  road.position.set(L.pad.roadX, 0.05, L.pad.z1 + 800 - 1);
  road.receiveShadow = true;
  group.add(road);
  const aisle = new THREE.Mesh(new THREE.PlaneGeometry(L.pad.x1 - L.pad.x0 - 12, 6), roadMat);
  aisle.rotation.x = -Math.PI / 2;
  aisle.position.set((L.pad.x0 + L.pad.x1) / 2, 0.06, L.pad.z1 - 9);
  aisle.receiveShadow = true;
  group.add(aisle);

  const encM = [], slabM = [], hvacM = [], fanM = [], grilleM = [], barM = [], gaugeM = [];
  const fans = [];
  for (const e of L.enc) {
    encM.push(mat4(V(e.x, ENC.F + ENC.H / 2, e.z)));
    slabM.push(mat4(V(e.x, ENC.F / 2, e.z)));
    const hx = e.x + e.end * (ENC.L / 2 + 0.45);
    hvacM.push(mat4(V(hx, ENC.F + 1.25, e.z), 0));
    for (const dz of [-0.55, 0.55]) {
      const p = V(hx + e.end * 0.455, ENC.F + 1.55, e.z + dz);
      grilleM.push(mat4(p, e.end > 0 ? Math.PI / 2 : -Math.PI / 2));
      fans.push({ p: V(hx + e.end * 0.47, ENC.F + 1.55, e.z + dz), yaw: e.end > 0 ? Math.PI / 2 : -Math.PI / 2 });
    }
    barM.push(mat4(V(e.x, ENC.F + ENC.H - 0.16, e.z + ENC.W / 2 + 0.03)));
    gaugeM.push(mat4(V(e.x - e.end * (ENC.L / 2 - 0.45), ENC.F + 1.5, e.z + ENC.W / 2 + 0.025)));
  }
  group.add(inst(new THREE.BoxGeometry(ENC.L, ENC.H, ENC.W), white, encM));
  group.add(inst(new THREE.BoxGeometry(ENC.L + 0.4, ENC.F, ENC.W + 0.4), concrete, slabM));
  group.add(inst(new THREE.BoxGeometry(0.9, 2.1, 2.2), hvacMat, hvacM));
  group.add(inst(new THREE.CircleGeometry(0.42, 24), dark, grilleM, { shadow: false }));
  const ringG = new THREE.RingGeometry(0.4, 0.45, 28);
  group.add(inst(ringG, new THREE.MeshStandardMaterial({ color: "#b9bec0", roughness: 0.4, metalness: 0.6, side: THREE.DoubleSide }), grilleM.map((m) => m.clone().multiply(new THREE.Matrix4().makeTranslation(0, 0, 0.03))), { shadow: false }));
  const blade = new THREE.CircleGeometry(0.37, 10, -0.28, 0.56);
  const fanGeom = merge([0, 1, 2, 3, 4].map((k) => blade.clone().rotateZ((k * 2 * Math.PI) / 5)).concat([new THREE.CircleGeometry(0.07, 12)]));
  const fanMesh = inst(fanGeom, new THREE.MeshStandardMaterial({ color: "#8f979b", roughness: 0.5, metalness: 0.5, side: THREE.DoubleSide }), fans.map((f) => mat4(f.p, f.yaw)), { shadow: false });
  group.add(fanMesh);
  const barMat = new THREE.MeshStandardMaterial({ color: "#111", emissive: new THREE.Color(COLORS.idle), emissiveIntensity: 1.2, roughness: 0.4 });
  group.add(inst(new THREE.BoxGeometry(ENC.L - 0.7, 0.13, 0.06), barMat, barM, { shadow: false }));
  const gauge = gaugeMaterial(battery.soc_levels);
  gauge.uniforms.uEnd.value = battery.s_end_min;
  group.add(inst(new THREE.PlaneGeometry(0.36, 1.55), gauge, gaugeM, { shadow: false }));

  const skidPad = [], cab = [], tank = [], fin = [], bush = [], led = [];
  for (const s of L.skids) {
    skidPad.push(mat4(V(s.x, 0.15, s.z), 0, V(7.2, 0.3, 3.2)));
    cab.push(mat4(V(s.x - 1.5, 0.3 + 1.15, s.z)));
    tank.push(mat4(V(s.x + 1.9, 0.3 + 1.0, s.z)));
    for (let i = 0; i < 7; i++) for (const side of [-1, 1]) fin.push(mat4(V(s.x + 1.2 + i * 0.22, 0.3 + 0.95, s.z + side * 1.08)));
    for (let i = 0; i < 3; i++) bush.push(mat4(V(s.x + 1.4 + i * 0.5, 2.3, s.z - 0.5)));
    led.push(mat4(V(s.x - 1.5, 2.2, s.z + 1.22)));
  }
  group.add(inst(new THREE.BoxGeometry(1, 1, 1), concrete, skidPad));
  group.add(inst(new THREE.BoxGeometry(3.4, 2.3, 2.4), cabinet, cab));
  group.add(inst(new THREE.BoxGeometry(2.1, 2.0, 2.0), padmount, tank));
  group.add(inst(new THREE.BoxGeometry(0.05, 1.6, 0.35), padmount, fin));
  group.add(inst(insulator(0.55, 0.07, 4), polymer, bush));
  const ledMat = new THREE.MeshStandardMaterial({ color: "#111", emissive: new THREE.Color("#7dffa8"), emissiveIntensity: 2 });
  group.add(inst(new THREE.BoxGeometry(0.5, 0.06, 0.04), ledMat, led, { shadow: false }));

  const sub = buildSubstation(L, { steel, xfmr, porcelain, polymer, concrete, dark });
  group.add(sub.group);

  const fence = buildFence(L.pad, steel);
  group.add(fence);

  const om = buildOM(L, concrete, seed);
  group.add(om.group);

  const lights = buildLights(L, steel, dark);
  group.add(lights.group);

  const flag = buildFlag(L);
  group.add(flag.group);

  const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), one = V(1, 1, 1);
  let fanAngle = 0, fanSpeed = 2;
  const col = new THREE.Color();
  function update({ mode, mw, pmax, soc, night, dt, temp = 25, wind }) {
    const load = Math.abs(mw) / Math.max(1, pmax);
    const target = mode === "grey" ? 3 : 4 + 22 * load + Math.max(0, temp - 20) * 0.35;
    fanSpeed += (target - fanSpeed) * Math.min(1, dt * 1.5);
    fanAngle = (fanAngle + fanSpeed * dt) % (Math.PI * 2);
    fans.forEach((f, i) => {
      _q.setFromEuler(_e.set(0, f.yaw, fanAngle + i * 0.7));
      fanMesh.setMatrixAt(i, _m.compose(f.p, _q, one));
    });
    fanMesh.instanceMatrix.needsUpdate = true;
    col.set(COLORS[mode] || COLORS.idle);
    barMat.emissive.copy(col);
    barMat.emissiveIntensity = (mode === "idle" ? 0.9 : mode === "grey" ? 0.25 : 2.4) * (0.7 + 0.5 * night) + (mode === "charge" || mode === "discharge" ? load * 1.2 : 0);
    gauge.uniforms.uSoc.value = soc;
    gauge.uniforms.uGrey.value = mode === "grey" ? 1 : 0;
    gauge.uniforms.uGlow.value = night;
    ledMat.emissive.set(mode === "grey" || mode === "violation" ? "#ff5a4a" : "#7dffa8");
    lights.update(night, dt);
    flag.update(wind, dt);
  }
  return { group, layout: L, update, lights, sub };
}

function buildSubstation(L, M) {
  const g = new THREE.Group();
  const sx = L.sx;
  const slab = new THREE.Mesh(new THREE.BoxGeometry(9, 0.5, 7), M.concrete);
  slab.position.set(sx - 8, 0.25, 0);
  slab.receiveShadow = slab.castShadow = true;
  g.add(slab);
  const tank = new THREE.Mesh(merge([box(6.5, 4.2, 4.2, 0, 2.6, 0), cyl(0.7, 0.7, 4.6, 0.5, 5.6, -1.6, 14, "x"), box(0.3, 1.0, 0.3, 0.5, 5.0, -1.6)]), M.xfmr);
  tank.position.set(sx - 8, 0.5, 0);
  tank.castShadow = tank.receiveShadow = true;
  g.add(tank);
  const finM = [];
  for (let i = 0; i < 12; i++) for (const s of [-1, 1]) finM.push(mat4(V(sx - 10.6 + i * 0.45, 2.9, s * 2.75)));
  g.add(inst(new THREE.BoxGeometry(0.08, 3.4, 1.1), M.xfmr, finM));
  const bush = [];
  for (let i = 0; i < 3; i++) bush.push(mat4(V(sx - 9.5 + i * 1.5, 4.8, 0.9)));
  g.add(inst(insulator(2.6, 0.22, 11), M.porcelain, bush));
  const lv = [];
  for (let i = 0; i < 3; i++) lv.push(mat4(V(sx - 9.5 + i * 1.5, 4.8, -0.6)));
  g.add(inst(insulator(1.1, 0.16, 5), M.porcelain, lv));

  const pairs = [];
  const frame = (x, h, w) => {
    for (const z of [-w / 2, w / 2]) {
      pairs.push([V(x, 0, z), V(x, h, z)]);
      for (let y = 0; y < h - 0.5; y += 1.5) pairs.push([V(x, y, z), V(x, y + 1.5, z)]);
    }
    pairs.push([V(x, h, -w / 2), V(x, h, w / 2)], [V(x, h - 1, -w / 2), V(x, h - 1, w / 2)]);
  };
  frame(sx, 9, 9);
  frame(sx + 9, 9, 9);
  for (const z of [-3, 0, 3]) pairs.push([V(sx, 9, z), V(sx + 9, 9, z)]);
  g.add(Object.assign(new THREE.Mesh(struts(pairs, 0.28), M.steel), { castShadow: true }));
  const busM = [], postM = [], brk = [], brkB = [];
  for (const z of [-3, 0, 3]) {
    busM.push(mat4(V(sx + 4.5, 7.6, z), 0, V(1, 1, 1)));
    busM.push(mat4(V(sx - 3.5, 6.6, z * 0.5), 0, V(1, 1, 1)));
    for (const x of [sx + 2, sx + 7]) postM.push(mat4(V(x, 4.2, z)));
    brk.push(mat4(V(sx + 4.5, 2.9, z)));
    brkB.push(mat4(V(sx + 3.6, 3.4, z)), mat4(V(sx + 5.4, 3.4, z)));
  }
  g.add(inst(cyl(0.09, 0.09, 9, 0, 0, 0, 8, "x"), M.steel, busM));
  g.add(inst(insulator(2.4, 0.15, 9), M.polymer, postM));
  const supports = [];
  for (const z of [-3, 0, 3]) for (const x of [sx + 2, sx + 7]) supports.push([V(x, 0, z), V(x, 4.2, z)]);
  g.add(Object.assign(new THREE.Mesh(struts(supports, 0.32), M.steel), { castShadow: true }));
  g.add(inst(merge([cyl(0.55, 0.55, 2.2, 0, 0, 0, 14, "x"), box(0.25, 2.9, 0.25, -0.8, -1.45, 0), box(0.25, 2.9, 0.25, 0.8, -1.45, 0)]), M.xfmr, brk));
  g.add(inst(insulator(1.6, 0.13, 7), M.porcelain, brkB));
  for (const [x, z] of [[sx - 16, -8], [sx + 14, 9]]) {
    const mast = new THREE.Mesh(cyl(0.12, 0.35, 24, 0, 12, 0, 8), M.steel);
    mast.position.set(x, 0, z);
    mast.castShadow = true;
    g.add(mast);
  }
  const de = [];
  const deX = sx + 20;
  for (const z of [-5.5, 5.5]) {
    const w = 1.4;
    for (const dx of [-w / 2, w / 2]) for (const dz of [-w / 2, w / 2]) de.push([V(deX + dx * 1.6, 0, z + dz * 1.6), V(deX + dx * 0.6, 17, z + dz * 0.6)]);
    for (let y = 0; y < 16; y += 2) {
      const a = 0.8 - (0.5 * y) / 17, b = 0.8 - (0.5 * (y + 2)) / 17;
      de.push([V(deX - a, y, z - a), V(deX + b, y + 2, z + b)], [V(deX + a, y, z - a), V(deX - b, y + 2, z + b)]);
      de.push([V(deX - a, y, z + a), V(deX + b, y + 2, z - b)], [V(deX + a, y, z + a), V(deX - b, y + 2, z - b)]);
    }
  }
  de.push([V(deX, 16, -6.5), V(deX, 16, 6.5)], [V(deX, 15, -6.5), V(deX, 15, 6.5)], [V(deX, 17, -5.5), V(deX, 17, 5.5)]);
  g.add(Object.assign(new THREE.Mesh(struts(de, 0.2), M.steel), { castShadow: true }));
  const strings = [];
  for (const z of [-4, 0, 4]) strings.push(mat4(V(deX + 0.3, 13.2, z), 0, 1));
  g.add(inst(insulator(2.6, 0.13, 12), M.polymer, strings));
  const house = new THREE.Mesh(box(8, 3.4, 5, sx - 20, 1.7, 9), new THREE.MeshStandardMaterial({ color: "#cfc6b4", roughness: 0.8 }));
  house.castShadow = house.receiveShadow = true;
  g.add(house);
  const subFence = new THREE.Mesh(new THREE.BoxGeometry(46, 2.4, 30), new THREE.MeshBasicMaterial({ visible: false }));
  subFence.position.set(sx, 1.2, 0);
  return { group: g, deadEnd: { x: deX, y: 16, z: [-4, 0, 4] } };
}

function fenceTexture() {
  return canvasTexture(64, 64, (g, w, h) => {
    g.clearRect(0, 0, w, h);
    g.strokeStyle = "rgba(170,178,182,0.85)";
    g.lineWidth = 2;
    for (let i = -w; i < w * 2; i += 16) {
      g.beginPath();
      g.moveTo(i, 0);
      g.lineTo(i + h, h);
      g.moveTo(i + h, 0);
      g.lineTo(i, h);
      g.stroke();
    }
  });
}

function buildFence(pad, steel) {
  const g = new THREE.Group();
  const H = 2.4;
  const tex = fenceTexture();
  tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
  const mesh = new THREE.MeshStandardMaterial({ map: tex, transparent: true, alphaTest: 0.25, side: THREE.DoubleSide, roughness: 0.5, metalness: 0.6, depthWrite: true });
  const sides = [
    [pad.x0, pad.z0, pad.x1, pad.z0], [pad.x1, pad.z0, pad.x1, pad.z1], [pad.x1, pad.z1, pad.x0, pad.z1], [pad.x0, pad.z1, pad.x0, pad.z0],
  ];
  const posts = [];
  for (const [x0, z0, x1, z1] of sides) {
    const len = Math.hypot(x1 - x0, z1 - z0);
    const t = mesh.clone();
    t.map = tex.clone();
    t.map.repeat.set(len / 0.9, H / 0.9);
    t.map.needsUpdate = true;
    const m = new THREE.Mesh(new THREE.PlaneGeometry(len, H), t);
    m.position.set((x0 + x1) / 2, H / 2, (z0 + z1) / 2);
    m.rotation.y = -Math.atan2(z1 - z0, x1 - x0);
    g.add(m);
    const n = Math.ceil(len / 3);
    for (let i = 0; i <= n; i++) posts.push(mat4(V(x0 + ((x1 - x0) * i) / n, H / 2 + 0.15, z0 + ((z1 - z0) * i) / n)));
  }
  g.add(inst(cyl(0.04, 0.04, H + 0.3, 0, 0, 0, 6), steel, posts));
  return g;
}

function buildOM(L, concrete, seed) {
  const g = new THREE.Group();
  const x = L.pad.roadX + 18, z = L.pad.z1 - 5;
  const wall = new THREE.MeshStandardMaterial({ map: canvasTexture(256, 128, (c, w, h) => {
    c.fillStyle = "#d8cfbd";
    c.fillRect(0, 0, w, h);
    for (let i = 0; i < w; i += 8) {
      c.fillStyle = "rgba(0,0,0,0.05)";
      c.fillRect(i, 0, 3, h);
    }
  }), roughness: 0.75 });
  const b = new THREE.Mesh(box(14, 4.2, 8, x, 2.1, z - 4), wall);
  b.castShadow = b.receiveShadow = true;
  const roof = new THREE.Mesh(box(14.6, 0.35, 8.6, x, 4.35, z - 4), new THREE.MeshStandardMaterial({ color: "#7c8a92", roughness: 0.5, metalness: 0.5 }));
  roof.castShadow = true;
  const winMat = new THREE.MeshStandardMaterial({ color: "#20282e", emissive: new THREE.Color("#ffd9a0"), emissiveIntensity: 0, roughness: 0.15, metalness: 0.4 });
  const wins = [];
  for (const dx of [-4.5, -1.5, 3.5]) wins.push(mat4(V(x + dx, 2.3, z + 0.03)));
  const w = inst(new THREE.PlaneGeometry(1.6, 1.1), winMat, wins, { shadow: false });
  const door = new THREE.Mesh(new THREE.PlaneGeometry(1.0, 2.2), new THREE.MeshStandardMaterial({ color: "#5d6a72", roughness: 0.6 }));
  door.position.set(x + 1, 1.1, z + 0.02);
  const truck = new THREE.Mesh(merge([box(5.4, 0.9, 2.0, 0, 0.85, 0), box(2.5, 0.85, 1.9, -0.6, 1.7, 0)]), new THREE.MeshStandardMaterial({ color: "#e9ebea", roughness: 0.35, metalness: 0.5 }));
  truck.position.set(x - 2, 0, z + 5);
  truck.rotation.y = 0.08;
  truck.castShadow = true;
  const wheels = inst(cyl(0.42, 0.42, 0.3, 0, 0, 0, 12, "z"), new THREE.MeshStandardMaterial({ color: "#1b1c1e", roughness: 0.9 }),
    [[-1.7, -0.95], [-1.7, 0.95], [1.7, -0.95], [1.7, 0.95]].map(([dx, dz]) => mat4(V(x - 2 + dx, 0.42, z + 5 + dz))));
  g.add(b, roof, w, door, truck, wheels);
  return { group: g, windows: winMat };
}

function buildLights(L, steel, dark) {
  const g = new THREE.Group();
  const spots = [];
  const { x0, x1, z0, z1 } = L.pad;
  const poles = [];
  const step = 34;
  for (let x = x0 + 8; x <= x1 - 8; x += step) poles.push([x, z0 + 3, 1], [x, z1 - 3, -1]);
  for (let z = z0 + 3 + step; z <= z1 - 3 - step / 2; z += step) poles.push([x0 + 3, z, 0]);
  const poleM = [], headM = [], glowPos = [];
  for (const [x, z, f] of poles) {
    poleM.push(mat4(V(x, 6, z)));
    headM.push(mat4(V(x, 11.8, z + f * 0.5), 0, 1, f * 0.35));
    glowPos.push(V(x, 11.6, z + f * 0.6));
  }
  g.add(inst(cyl(0.09, 0.16, 12, 0, 0, 0, 8), steel, poleM));
  g.add(inst(box(0.7, 0.18, 0.5), dark, headM));
  const lampMat = new THREE.MeshBasicMaterial({ color: "#fff2d8" });
  const lampM = headM.map((m) => m.clone().multiply(new THREE.Matrix4().makeTranslation(0, -0.1, 0)));
  const lamps = inst(box(0.55, 0.04, 0.38), lampMat, lampM, { shadow: false });
  g.add(lamps);
  const glowMat = new THREE.SpriteMaterial({ map: glowTexture(), color: "#ffe4b8", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 });
  const glows = glowPos.map((p) => {
    const s = new THREE.Sprite(glowMat);
    s.position.copy(p);
    s.scale.setScalar(5);
    g.add(s);
    return s;
  });
  const poolMat = new THREE.MeshBasicMaterial({ map: glowTexture(), color: "#ffdcae", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 });
  for (const [x, z, f] of poles) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(30, 30), poolMat);
    p.rotation.x = -Math.PI / 2;
    p.position.set(x, 0.09, z + f * 9);
    g.add(p);
  }
  const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2;
  const pick = [0, 2, poles.length - 2, Math.floor(poles.length / 2), 1, poles.length - 1].filter((i, k, a) => i >= 0 && i < poles.length && a.indexOf(i) === k);
  for (const i of pick.slice(0, 6)) {
    const [x, z, f] = poles[i];
    const s = new THREE.SpotLight("#ffe2bb", 0, 140, 1.05, 0.65, 1.4);
    s.position.set(x, 11.5, z);
    s.target.position.set(x + (cx - x) * 0.3, 0, z + (f || 0) * 26 + (f ? 0 : (cz - z) * 0.2));
    g.add(s, s.target);
    spots.push(s);
  }
  return {
    group: g, poles,
    update(night) {
      const on = Math.min(1, Math.max(0, (night - 0.15) / 0.35));
      lampMat.color.set("#fff2d8").multiplyScalar(0.25 + 2.5 * on);
      glowMat.opacity = 0.85 * on;
      poolMat.opacity = 0.16 * on;
      for (const s of spots) s.intensity = 110 * on;
      glows.forEach((s) => (s.visible = on > 0.01));
    },
  };
}

function flagTexture() {
  return canvasTexture(192, 128, (g, w, h) => {
    g.fillStyle = "#0a3a8c";
    g.fillRect(0, 0, w / 3, h);
    g.fillStyle = "#f4f4f2";
    g.fillRect(w / 3, 0, w, h / 2);
    g.fillStyle = "#c21f32";
    g.fillRect(w / 3, h / 2, w, h / 2);
    g.fillStyle = "#f4f4f2";
    g.beginPath();
    const cx = w / 6, cy = h / 2, R = 22, r = 9;
    for (let i = 0; i < 10; i++) {
      const a = -Math.PI / 2 + (i * Math.PI) / 5;
      const rr = i % 2 ? r : R;
      g.lineTo(cx + Math.cos(a) * rr, cy + Math.sin(a) * rr);
    }
    g.closePath();
    g.fill();
  });
}

/** The Texas flag on the O&M flagpole, flying downwind at a rate set by the wind. */
function buildFlag(L) {
  const g = new THREE.Group();
  const x = L.pad.roadX + 30, z = L.pad.z1 - 1.5;
  const pole = new THREE.Mesh(cyl(0.05, 0.08, 10, x, 5, z, 8), new THREE.MeshStandardMaterial({ color: "#d9dcdd", metalness: 0.7, roughness: 0.3 }));
  pole.castShadow = true;
  const U = { uT: { value: 0 }, uWind: { value: 0.5 } };
  const geom = new THREE.PlaneGeometry(2.4, 1.6, 24, 8);
  geom.translate(1.2, 0, 0);
  const mat = new THREE.MeshStandardMaterial({ map: flagTexture(), side: THREE.DoubleSide, roughness: 0.8 });
  mat.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, U);
    sh.vertexShader = sh.vertexShader.replace("#include <common>", "#include <common>\nuniform float uT, uWind;").replace("#include <begin_vertex>", `#include <begin_vertex>
      float u = position.x / 2.4;
      float droop = (1.0 - uWind);
      transformed.z += sin(position.x * 2.2 - uT * (3.0 + 7.0 * uWind)) * 0.16 * u * (0.3 + uWind);
      transformed.y -= u * u * droop * 1.3;
      transformed.x *= 1.0 - droop * 0.55 * u;`);
  };
  const flag = new THREE.Mesh(geom, mat);
  flag.position.set(x, 9.1, z);
  flag.castShadow = true;
  g.add(pole, flag);
  let t = 0;
  return {
    group: g,
    update(wind, dt) {
      const kt = wind?.kt ?? 8;
      U.uWind.value = Math.min(1, kt / 22);
      t += dt;
      U.uT.value = t;
      flag.rotation.y = wind?.yawLocal ?? 0;
    },
  };
}
