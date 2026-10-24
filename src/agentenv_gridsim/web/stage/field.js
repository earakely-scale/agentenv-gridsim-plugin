/** The other seats out in the field, display-only: gas-G's simple-cycle peaker plant (aeroderivative units in two rows,
 * each with its inlet filter house, enclosure, SCR and stack), renew-R's single-axis tracker block, and the floating
 * name tags the director shows over each asset. Site-local metres like the yard; update() drives what runs. */
import * as THREE from "three";
import { box, canvasTexture, cyl, glowTexture, inst, mat4, merge, V } from "./kit.js";
import { trackerAngle } from "./plant.js";
import { gravelMaterial } from "./terrain.js";

const UNIT = { pitch: 26, row: 21 };
const ROW = { len: 104, w: 2.38, pitch: 6.8, hub: 1.7 };

function louvre(base, lines = "rgba(0,0,0,0.07)") {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = base;
    g.fillRect(0, 0, w, h);
    g.fillStyle = lines;
    for (let x = 0; x < w; x += 16) g.fillRect(x, 0, 2, h);
    g.fillStyle = "rgba(255,255,255,0.05)";
    for (let x = 8; x < w; x += 16) g.fillRect(x, 0, 1, h);
  });
}

function filterFace() {
  return canvasTexture(256, 256, (g, w, h) => {
    g.fillStyle = "#c7c9c4";
    g.fillRect(0, 0, w, h);
    for (let y = 8; y < h; y += 32) {
      g.fillStyle = "#8d918f";
      g.fillRect(6, y, w - 12, 22);
      g.fillStyle = "rgba(0,0,0,0.25)";
      g.fillRect(6, y + 18, w - 12, 4);
    }
  });
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
        g.fillStyle = (i + j) % 2 ? "#141d29" : "#16202d";
        g.fillRect(4 + i * cw + 0.6, 5 + j * ch + (j >= 12 ? 2 : 0) + 0.5, cw - 1.2, ch - 1);
      }
  }, { aniso: 12 });
}

/** gas-G: n units of about 45 MW in two rows along x, a control building, a demineralised-water tank, the fuel-gas
 * metering skid, step-up transformers and a fenced pad. */
export function buildPeakers(n, U, { at: [ox, oz] }) {
  const g = new THREE.Group();
  g.position.set(ox, 0, oz);
  const per = Math.ceil(n / 2);
  const W = per * UNIT.pitch + 70, D = 2 * UNIT.row + 64;
  const x0 = -W / 2 + 22;
  const pad = new THREE.Mesh(new THREE.PlaneGeometry(W, D).rotateX(-Math.PI / 2), gravelMaterial("#a9a59c", U));
  pad.position.y = 0.04;
  pad.receiveShadow = true;
  g.add(pad);
  const beige = new THREE.MeshStandardMaterial({ map: louvre("#d9d4c6"), roughness: 0.55, metalness: 0.15 });
  const grey = new THREE.MeshStandardMaterial({ map: louvre("#a6abad", "rgba(0,0,0,0.1)"), roughness: 0.5, metalness: 0.35 });
  const steel = new THREE.MeshStandardMaterial({ color: "#8c9396", roughness: 0.45, metalness: 0.6 });
  const stackMat = new THREE.MeshStandardMaterial({ color: "#9aa0a2", roughness: 0.5, metalness: 0.5 });
  const filter = new THREE.MeshStandardMaterial({ map: filterFace(), roughness: 0.7 });
  const concrete = new THREE.MeshStandardMaterial({ color: "#bdb9b0", roughness: 0.92 });
  const xfmr = new THREE.MeshStandardMaterial({ color: "#77827f", roughness: 0.5, metalness: 0.45 });
  const yellow = new THREE.MeshStandardMaterial({ color: "#d6b23a", roughness: 0.5, metalness: 0.3 });
  const units = [];
  const M = { slab: [], enc: [], inlet: [], face: [], scr: [], duct: [], stack: [], ring: [], fin: [], gsu: [], fan: [] };
  for (let i = 0; i < n; i++) {
    const row = i < per ? -1 : 1, k = i % per;
    const x = x0 + k * UNIT.pitch, z = row * UNIT.row;
    const s = row;
    M.slab.push(mat4(V(x, 0.2, z), 0, V(13, 0.4, 30)));
    M.enc.push(mat4(V(x, 0.4 + 2.5, z - s * 1)));
    M.inlet.push(mat4(V(x, 7.6, z - s * 10.5)));
    M.face.push(mat4(V(x, 7.6, z - s * 13.53), s < 0 ? 0 : Math.PI));
    M.duct.push(mat4(V(x, 3.2, z + s * 9.5)));
    M.scr.push(mat4(V(x, 4.3, z + s * 13.2)));
    M.stack.push(mat4(V(x, 12.5, z + s * 16.4)));
    M.ring.push(mat4(V(x, 21.5, z + s * 16.4)));
    M.fin.push(mat4(V(x + 5, 1.6, z - s * 3)));
    M.gsu.push(mat4(V(x - 4.5, 2.1, z + s * 2.5)));
    units.push({ x, z: z + s * 16.4, top: 25.2, s });
  }
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), concrete, M.slab));
  g.add(inst(new THREE.BoxGeometry(4.6, 5, 18), beige, M.enc));
  g.add(inst(new THREE.BoxGeometry(6.2, 5.6, 6.2), grey, M.inlet));
  g.add(inst(new THREE.PlaneGeometry(6, 5.4), filter, M.face, { shadow: false }));
  g.add(inst(new THREE.BoxGeometry(3.4, 3.4, 3.4), grey, M.duct));
  g.add(inst(new THREE.BoxGeometry(5.4, 7.4, 6), grey, M.scr));
  g.add(inst(cyl(1.75, 1.95, 25, 0, 0, 0, 20), stackMat, M.stack));
  g.add(inst(cyl(2.4, 2.4, 0.25, 0, 0, 0, 20), steel, M.ring));
  g.add(inst(new THREE.BoxGeometry(3.2, 2.6, 4.2), grey, M.fin));
  g.add(inst(new THREE.BoxGeometry(3.4, 3.6, 4.4), xfmr, M.gsu));
  g.add(inst(new THREE.BoxGeometry(0.5, 23, 0.25), steel, units.map((u) => mat4(V(u.x + 1.95, 12.5, u.z)))));
  g.add(inst(new THREE.BoxGeometry(2.4, 2.6, 2.4), new THREE.MeshStandardMaterial({ color: "#e4e1d9", roughness: 0.7 }), units.map((u) => mat4(V(u.x - 3.2, 1.7, u.z)))));
  const sy = [], syX = W / 2 - 22, syZ = 0;
  for (const dz of [-14, 0, 14]) {
    for (const dx of [-6, 6]) sy.push(mat4(V(syX + dx, 7, syZ + dz), 0, V(0.5, 14, 0.5)));
    sy.push(mat4(V(syX, 13.6, syZ + dz), 0, V(12.5, 0.6, 0.6)));
  }
  for (let k = 0; k < 4; k++) sy.push(mat4(V(syX - 2 + k * 1.4, 1.6, syZ - 7), 0, V(0.8, 3.2, 0.8)));
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), steel, sy));
  const legs = [];
  for (const m of M.inlet) {
    const p = new THREE.Vector3().setFromMatrixPosition(m);
    for (const dx of [-2.8, 2.8]) for (const dz of [-2.8, 2.8]) legs.push(mat4(V(p.x + dx, 2.4, p.z + dz), 0, V(0.25, 4.8, 0.25)));
  }
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), steel, legs));
  const bx = W / 2 - 22;
  const build = new THREE.Mesh(box(16, 4.8, 9, bx, 2.4, -D / 2 + 9), new THREE.MeshStandardMaterial({ map: louvre("#e6e2d8", "rgba(0,0,0,0.05)"), roughness: 0.7 }));
  const tank = new THREE.Mesh(cyl(7, 7, 11, bx - 2, 5.5, D / 2 - 14, 36), new THREE.MeshStandardMaterial({ color: "#eceae4", roughness: 0.5, metalness: 0.2 }));
  const skid = new THREE.Mesh(merge([box(10, 0.4, 4, x0 - 16, 0.2, 0), cyl(0.35, 0.35, 10, x0 - 16, 1.2, -1, 10, "x"), cyl(0.35, 0.35, 10, x0 - 16, 1.2, 1, 10, "x"), cyl(0.5, 0.5, 2.4, x0 - 19, 1.6, 0, 12), cyl(0.5, 0.5, 2.4, x0 - 13, 1.6, 0, 12)]), yellow);
  const header = new THREE.Mesh(cyl(0.3, 0.3, per * UNIT.pitch, x0 + ((per - 1) * UNIT.pitch) / 2, 0.9, 0, 10, "x"), yellow);
  for (const m of [build, tank, skid, header]) (m.castShadow = m.receiveShadow = true), g.add(m);
  const fence = [];
  for (const [a, b, c, d2] of [[-W / 2, -D / 2, W / 2, -D / 2], [W / 2, -D / 2, W / 2, D / 2], [W / 2, D / 2, -W / 2, D / 2], [-W / 2, D / 2, -W / 2, -D / 2]]) {
    const len = Math.hypot(c - a, d2 - b);
    fence.push(box(len, 2.4, 0.04).rotateY(-Math.atan2(d2 - b, c - a)).translate((a + c) / 2, 1.2, (b + d2) / 2));
  }
  const fm = new THREE.Mesh(merge(fence), new THREE.MeshStandardMaterial({ color: "#b4babd", roughness: 0.6, metalness: 0.5, transparent: true, opacity: 0.45 }));
  g.add(fm);

  const plume = new THREE.SpriteMaterial({ map: glowTexture(), color: "#d9d6d0", transparent: true, depthWrite: false, opacity: 0 });
  const sprites = units.map((u) => {
    const list = [];
    for (let k = 0; k < 4; k++) {
      const sp = new THREE.Sprite(plume.clone());
      sp.position.set(u.x, u.top, u.z);
      g.add(sp);
      list.push(sp);
    }
    return list;
  });
  const beaconMat = new THREE.SpriteMaterial({ map: glowTexture(), color: "#ff3b2b", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 });
  for (const u of units) {
    const b = new THREE.Sprite(beaconMat);
    b.position.set(u.x, u.top + 0.4, u.z);
    b.scale.set(2.2, 2.2, 1);
    g.add(b);
  }
  const ledOn = new THREE.MeshStandardMaterial({ color: "#111", emissive: new THREE.Color("#7dffa8"), emissiveIntensity: 0 });
  const leds = inst(new THREE.BoxGeometry(0.06, 0.3, 0.3), ledOn, units.map((u) => mat4(V(u.x + 2.35, 4.4, u.z - u.s * 16))), { shadow: false });
  g.add(leds);
  const yard = new THREE.PointLight("#ffd9a0", 0, 160, 1.6);
  yard.position.set(0, 18, 0);
  g.add(yard);
  let clock = 0;
  return {
    group: g, units, W, D, center: [ox, oz],
    update({ running, night, dt, wind, reduced }) {
      clock += reduced ? 0 : dt;
      units.forEach((u, i) => {
        const on = i < running ? 1 : 0;
        sprites[i].forEach((sp, k) => {
          const ph = (clock * 0.35 + k / 6 + i * 0.13) % 1;
          sp.position.set(u.x + (wind?.x || 0) * ph * 14, u.top + 1 + ph * 22, u.z + (wind?.z || 0) * ph * 14);
          const sc = 5 + ph * 18;
          sp.scale.set(sc, sc, 1);
          sp.material.opacity = on * (1 - ph) * ph * 4 * (0.42 + 0.1 * night);
        });
      });
      beaconMat.opacity = night * 0.9;
      ledOn.emissiveIntensity = running ? 2.4 : 0;
      ledOn.emissive.set(running ? "#7dffa8" : "#ff9a5a");
      yard.intensity = night * 900;
    },
  };
}

/** renew-R's solar block: rows of 1P single-axis trackers that follow the real sun and stow flat at night, four
 * inverter skids along the central road. */
export function buildSolarBlock(U, { at: [ox, oz], rows = 64 }) {
  const g = new THREE.Group();
  g.position.set(ox, 0, oz);
  const tex = moduleTexture();
  tex.wrapS = THREE.RepeatWrapping;
  tex.repeat.set(90, 1);
  const glass = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.2, metalness: 0, envMapIntensity: 0.5 });
  const back = new THREE.MeshStandardMaterial({ color: "#5d666c", roughness: 0.6, metalness: 0.2 });
  const rim = new THREE.MeshStandardMaterial({ color: "#c4cacd", roughness: 0.35, metalness: 0.7 });
  const steel = new THREE.MeshStandardMaterial({ color: "#9ea6aa", roughness: 0.45, metalness: 0.6 });
  const table = new THREE.BoxGeometry(ROW.len, 0.045, ROW.w).rotateY(Math.PI / 2);
  const list = [];
  for (const half of [-1, 1])
    for (let k = 0; k < rows; k++) list.push({ x: (k - (rows - 1) / 2) * ROW.pitch, z: half * (ROW.len / 2 + 7) });
  const mesh = inst(table, [rim, rim, glass, back, rim, rim], list.map(() => new THREE.Matrix4()));
  const tubes = inst(cyl(0.065, 0.065, ROW.len, 0, 0, 0, 7, "z"), steel, list.map((w) => mat4(V(w.x, ROW.hub, w.z))), { shadow: false });
  const posts = [];
  for (const w of list) for (let i = 0; i < 6; i++) posts.push(mat4(V(w.x, ROW.hub / 2, w.z - ROW.len / 2 + 4 + (i * (ROW.len - 8)) / 5), 0, V(0.16, ROW.hub, 0.12)));
  g.add(mesh, tubes, inst(new THREE.BoxGeometry(1, 1, 1), steel, posts, { shadow: false }));
  const skids = [];
  for (let i = 0; i < 4; i++) skids.push(mat4(V((i - 1.5) * ROW.pitch * rows * 0.25, 1.3, 0), 0, V(2.4, 2.4, 4.2)));
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial({ color: "#e3e5e2", roughness: 0.5, metalness: 0.2 }), skids));
  const road = new THREE.Mesh(new THREE.PlaneGeometry(rows * ROW.pitch + 20, 10).rotateX(-Math.PI / 2), gravelMaterial("#b9ad97", U, { scale: 1.2, road: true }));
  road.position.y = 0.06;
  road.receiveShadow = true;
  g.add(road);
  const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), one = V(1, 1, 1), _p = V();
  let last = null;
  return {
    group: g, W: rows * ROW.pitch, D: 2 * ROW.len + 14, center: [ox, oz],
    update({ el, az }) {
      const a = (trackerAngle(el, az) * Math.PI) / 180;
      if (last !== null && Math.abs(a - last) < 0.002) return;
      last = a;
      list.forEach((w, i) => {
        _q.setFromEuler(_e.set(0, 0, -a));
        mesh.setMatrixAt(i, _m.compose(_p.set(w.x, ROW.hub + 0.12, w.z), _q, one));
      });
      mesh.instanceMatrix.needsUpdate = true;
    },
  };
}

/** A floating tag over an asset: the seat letter and what it is, white on ink, always facing the camera; set(text)
 * redraws it when the asset's state line changes. */
export function tag(letter, color) {
  const H = 160, font = "600 56px Inter, 'Helvetica Neue', Arial, sans-serif";
  const c = document.createElement("canvas");
  c.height = H;
  const map = new THREE.CanvasTexture(c);
  map.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map, transparent: true, depthWrite: false, depthTest: false, fog: false, sizeAttenuation: false }));
  s.center.set(0, 0);
  s.renderOrder = 20;
  let last = null;
  s.userData.set = (text) => {
    if (text === last) return;
    last = text;
    const g = c.getContext("2d");
    g.font = font;
    c.width = Math.ceil(g.measureText(text).width) + 176;
    g.clearRect(0, 0, c.width, H);
    g.fillStyle = "rgba(20,26,32,0.82)";
    g.beginPath();
    g.roundRect(4, 20, c.width - 8, 120, 26);
    g.fill();
    g.fillStyle = color;
    g.beginPath();
    g.roundRect(18, 34, 92, 92, 18);
    g.fill();
    g.fillStyle = "#fff";
    g.font = "800 64px Inter, 'Helvetica Neue', Arial, sans-serif";
    g.textAlign = "center";
    g.textBaseline = "middle";
    g.fillText(letter, 64, 82);
    g.textAlign = "left";
    g.font = font;
    g.fillText(text, 136, 82);
    map.dispose();
    map.image = c;
    map.needsUpdate = true;
    s.scale.set((0.03 * c.width) / H, 0.03, 1);
  };
  return s;
}
