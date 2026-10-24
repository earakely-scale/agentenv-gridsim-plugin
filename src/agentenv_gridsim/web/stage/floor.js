/** The QSE's trading floor, display-only, modelled on real power-trading rooms: a downtown office floor with a glass
 * east wall, rows of trading benches with two tiers of monitors and a turret at every seat, a tiled video wall with
 * the market clock, the merit order and the day's prices, and seat A's desk in the front row. Real sun and sky come
 * through the windows (the field's sky material is shared, its sun copied each frame). Metres, y up, x east, -z north:
 * the video wall is on the north wall and faces south. */
import * as THREE from "three";
import { RectAreaLightUniformsLib } from "three/addons/lights/RectAreaLightUniformsLib.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import { AWARDS, DAM_CLOSE, heList, SEAT } from "../market.js";
import { drawBlotter, drawCard, drawClock, drawLadder, drawMerit, drawPrices, genericScreens } from "./floorscreens.js";
import { canvasTexture, glowTexture } from "./kit.js";
import { rng } from "./rng.js";

const CARD_SHOTS = new Set(["desk", "deal", "room"]);
export const ROOM = { w: 24, d: 17, h: 3.6 };
const WALL = { cols: 6, rows: 2, pw: 1.66, ph: 0.935, y0: 1.22, z: -ROOM.d / 2 + 0.06 };
const ROWS = [-3.2, -0.2, 2.8];
const SEATS_X = [-7.2, -5.4, -3.6, -1.8, 0, 1.8, 3.6, 5.4, 7.2];
const MON = { w: 0.62, h: 0.37 };
const A_DESK = { x: 0, z: ROWS[0] };

function paint(geo, hex) {
  const c = new THREE.Color(hex), n = geo.attributes.position.count, a = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) c.toArray(a, i * 3);
  geo.setAttribute("color", new THREE.BufferAttribute(a, 3));
  return geo.index ? geo.toNonIndexed() : geo;
}
const box = (w, h, d, [x, y, z], hex, { rx = 0, ry = 0 } = {}) => paint(new THREE.BoxGeometry(w, h, d).rotateX(rx).rotateY(ry).translate(x, y, z), hex);
const ball = (r, [x, y, z], hex, [sx, sy, sz] = [1, 1, 1]) => paint(new THREE.SphereGeometry(r, 12, 9).scale(sx, sy, sz).translate(x, y, z), hex);
function limb(a, b, r, hex) {
  const A = new THREE.Vector3(...a), B = new THREE.Vector3(...b);
  const g = new THREE.CapsuleGeometry(r, A.distanceTo(B), 3, 8);
  g.applyQuaternion(new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), B.clone().sub(A).normalize()));
  return paint(g.translate((A.x + B.x) / 2, (A.y + B.y) / 2, (A.z + B.z) / 2), hex);
}

/** A seated trader facing -z on a chair at the origin; `phone` raises the right hand to the ear. */
function person({ shirt, trousers = 0x23272d, skin, hair, style = "short", phone = false }) {
  const p = [
    paint(new THREE.CapsuleGeometry(0.105, 0.14, 3, 10).rotateZ(Math.PI / 2).scale(1, 1, 0.85).translate(0, 0.57, 0.13), trousers),
    paint(new THREE.CapsuleGeometry(0.12, 0.12, 3, 12).scale(1.12, 1, 0.78).translate(0, 0.73, 0.14), shirt),
    paint(new THREE.CapsuleGeometry(0.135, 0.13, 3, 12).scale(1.38, 1, 0.74).rotateX(-0.08).translate(0, 0.93, 0.13), shirt),
    paint(new THREE.CylinderGeometry(0.04, 0.046, 0.11, 10).translate(0, 1.11, 0.115), skin),
    ball(0.09, [0, 1.25, 0.1], skin, [0.88, 1.1, 0.98]),
    ball(0.02, [-0.079, 1.246, 0.106], skin, [0.5, 1, 0.8]),
    ball(0.02, [0.079, 1.246, 0.106], skin, [0.5, 1, 0.8]),
    paint(new THREE.SphereGeometry(0.097, 18, 10, 0, Math.PI * 2, 0, Math.PI * 0.55).scale(0.93, 1.06, 1.02).rotateX(0.45).translate(0, 1.262, 0.112), hair),
  ];
  if (style === "long") p.push(paint(new THREE.CapsuleGeometry(0.068, 0.07, 4, 12).scale(1.2, 1, 0.55).rotateX(0.15).translate(0, 1.185, 0.16), hair));
  if (style === "bun") p.push(ball(0.042, [0, 1.305, 0.2], hair));
  for (const x of [-1, 1]) {
    p.push(limb([x * 0.095, 0.56, 0.12], [x * 0.105, 0.56, -0.3], 0.068, trousers));
    p.push(limb([x * 0.105, 0.53, -0.32], [x * 0.105, 0.1, -0.36], 0.05, trousers));
    p.push(box(0.09, 0.06, 0.23, [x * 0.105, 0.03, -0.41], 0x16181b));
    p.push(ball(0.06, [x * 0.185, 1.03, 0.13], shirt));
    if (phone && x > 0) {
      p.push(limb([0.2, 1.02, 0.13], [0.22, 0.95, -0.02], 0.046, shirt));
      p.push(limb([0.22, 0.95, -0.02], [0.11, 1.22, 0.06], 0.039, shirt));
      p.push(ball(0.04, [0.1, 1.24, 0.07], skin, [0.95, 1.2, 0.8]));
      p.push(box(0.035, 0.2, 0.05, [0.105, 1.24, 0.03], 0x15171a, { rx: 0.2 }));
      continue;
    }
    p.push(limb([x * 0.2, 1.02, 0.13], [x * 0.235, 0.8, 0.07], 0.046, shirt));
    p.push(limb([x * 0.235, 0.8, 0.07], [x * 0.15, 0.785, -0.23], 0.039, shirt));
    p.push(ball(0.04, [x * 0.14, 0.78, -0.28], skin, [0.95, 0.55, 1.35]));
  }
  return mergeGeometries(p);
}

function chair() {
  const c = 0x1d2024, parts = [
    box(0.5, 0.07, 0.48, [0, 0.465, 0.08], c), box(0.46, 0.62, 0.06, [0, 0.86, 0.35], 0x24282e, { rx: 0.1 }),
    box(0.06, 0.32, 0.04, [0, 0.55, 0.36], 0x2b2f34), paint(new THREE.CylinderGeometry(0.028, 0.028, 0.36, 8).translate(0, 0.25, 0.1), 0x3a3e44),
  ];
  for (const x of [-0.26, 0.26]) parts.push(box(0.05, 0.03, 0.26, [x, 0.67, 0.1], c), box(0.03, 0.18, 0.03, [x, 0.58, 0.14], c));
  for (let k = 0; k < 5; k++) parts.push(box(0.3, 0.03, 0.045, [0, 0, 0], c).translate(0.15, 0, 0).rotateY((k / 5) * Math.PI * 2).translate(0, 0.06, 0.1));
  return mergeGeometries(parts);
}

/** One position of a trading bench, its user's edge on the origin: desktop, modesty panel, keyboard, mouse, a turret
 * sloped toward the user, a handset, a mug, and the monitor arm's post. */
function bench(w = 1.8) {
  const top = 0xd9d6cf, edge = 0x8b8780, dark = 0x15171a;
  return mergeGeometries([
    box(w - 0.02, 0.035, 0.85, [0, 0.74, -0.425], top), box(w - 0.02, 0.02, 0.03, [0, 0.755, -0.015], edge),
    box(w - 0.02, 0.6, 0.025, [0, 0.42, -0.83], 0x3c4046), box(0.04, 0.72, 0.84, [w / 2 - 0.02, 0.36, -0.42], 0x3c4046),
    box(0.46, 0.02, 0.15, [0.05, 0.768, -0.24], dark), box(0.06, 0.02, 0.1, [0.4, 0.768, -0.24], dark),
    box(0.34, 0.07, 0.24, [-0.56, 0.79, -0.34], 0x23262b, { rx: -0.35 }), box(0.32, 0.01, 0.2, [-0.56, 0.826, -0.33], 0x30353b, { rx: -0.35 }),
    box(0.05, 0.05, 0.2, [-0.78, 0.79, -0.3], 0x111316),
    paint(new THREE.CylinderGeometry(0.04, 0.035, 0.1, 12).translate(0.62, 0.81, -0.36), 0xe9e6e0),
    paint(new THREE.CylinderGeometry(0.025, 0.025, 0.9, 8).translate(0, 1.2, -0.72), 0x2a2d31),
    box(0.26, 0.012, 0.2, [0, 0.763, -0.72], 0x2a2d31), box(1.95, 0.05, 0.05, [0, 1.62, -0.72], 0x2a2d31),
  ]);
}

/** Six monitors in two tiers of three, curved around the seat; their matrices relative to the position's origin. */
function monitorMatrices() {
  const out = [];
  for (const tier of [0, 1])
    for (const i of [-1, 0, 1]) {
      const yaw = -i * 0.3, m = new THREE.Matrix4().makeRotationY(yaw);
      m.setPosition(i * (MON.w + 0.02) * Math.cos(yaw * 0.5), 1.04 + tier * (MON.h + 0.03), -0.66 + Math.abs(i) * 0.1);
      if (tier) m.multiply(new THREE.Matrix4().makeRotationX(0.12));
      out.push(m);
    }
  return out;
}

const tex = (draw, w, h, repeat) => canvasTexture(w, h, draw, repeat ? { repeat } : {});

function carpet() {
  const r = rng("carpet-v5");
  return tex((g, w, h) => {
    g.fillStyle = "#5c6168";
    g.fillRect(0, 0, w, h);
    for (let i = 0; i < 12000; i++) {
      const v = 76 + r() * 30;
      g.fillStyle = `rgba(${v},${v + 3},${v + 9},0.5)`;
      g.fillRect(r() * w, r() * h, 1.6, 1.6);
    }
    g.strokeStyle = "rgba(0,0,0,0.25)";
    for (const [x, y] of [[0, 0], [128, 0], [0, 128], [128, 128]]) g.strokeRect(x + 0.5, y + 0.5, 127, 127);
  }, 256, 256, [ROOM.w / 1, ROOM.d / 1]);
}

function ceilingTiles() {
  const r = rng("ceiling-v5");
  return tex((g, w, h) => {
    g.fillStyle = "#e4e3df";
    g.fillRect(0, 0, w, h);
    for (let i = 0; i < 4000; i++) {
      const v = 200 + r() * 40;
      g.fillStyle = `rgba(${v},${v},${v - 4},0.5)`;
      g.fillRect(r() * w, r() * h, 1, 1);
    }
    g.fillStyle = "#bdbbb5";
    g.fillRect(0, 0, w, 3);
    g.fillRect(0, 0, 3, h);
  }, 256, 256, [ROOM.w / 0.6, ROOM.d / 0.6]);
}

function slats() {
  return tex((g, w, h) => {
    g.fillStyle = "#2a221c";
    g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 32) {
      const grad = g.createLinearGradient(x, 0, x + 24, 0);
      grad.addColorStop(0, "#7a5a3e");
      grad.addColorStop(0.5, "#916c4a");
      grad.addColorStop(1, "#6a4d35");
      g.fillStyle = grad;
      g.fillRect(x + 4, 0, 24, h);
    }
  }, 256, 256, [ROOM.d / 1.2, 1]);
}

/** A curtain-wall tower face, 32 m wide and 64 m (18 floors) tall per repeat: glass bands, spandrels and mullions;
 * `lit` is its night emissive map with a random share of offices on. */
function facade(seed, lit) {
  const r = rng(seed);
  return tex((g, w, h) => {
    const fh = h / 18, mw = w / 21;
    g.fillStyle = lit ? "#000" : "#8c99a4";
    g.fillRect(0, 0, w, h);
    for (let f = 0; f < 18; f++) {
      const y = f * fh;
      if (lit) {
        for (let k = 0; k < 21; k++) {
          if (r() < 0.3) {
            const v = 150 + r() * 100;
            g.fillStyle = `rgb(${v},${v * 0.9},${v * 0.7})`;
            g.fillRect(k * mw + 1, y + fh * 0.22, mw - 1, fh * 0.66);
          }
        }
        continue;
      }
      const grad = g.createLinearGradient(0, y, 0, y + fh);
      const b = 70 + r() * 30;
      grad.addColorStop(0, `rgb(${b * 0.75},${b * 0.88},${b})`);
      grad.addColorStop(1, `rgb(${b * 0.95},${b * 1.05},${b * 1.15})`);
      g.fillStyle = grad;
      g.fillRect(0, y + fh * 0.22, w, fh * 0.7);
      g.fillStyle = "rgba(205,212,216,0.9)";
      g.fillRect(0, y, w, fh * 0.2);
      g.fillStyle = "rgba(60,66,72,0.55)";
      for (let k = 0; k <= 21; k++) g.fillRect(k * mw - 0.5, y + fh * 0.2, 1.2, fh * 0.72);
    }
  }, 256, 512);
}

function screenMaterial(map, k = 1) {
  return new THREE.MeshBasicMaterial({ map, color: new THREE.Color(k, k, k), toneMapped: true });
}

/** The room scene: build(sky) once; update(...) each frame; cams[name](u) gives a camera pose. */
export function buildFloor(d, { sky, fog, background }) {
  RectAreaLightUniformsLib.init();
  const scene = new THREE.Scene();
  scene.fog = fog;
  scene.background = background;
  const skyMesh = new THREE.Mesh(sky.sky.geometry, sky.sky.material);
  skyMesh.scale.copy(sky.sky.scale);
  skyMesh.renderOrder = sky.sky.renderOrder;
  skyMesh.frustumCulled = false;
  const dome = new THREE.Mesh(sky.dome.geometry, sky.dome.material);
  dome.renderOrder = sky.dome.renderOrder;
  dome.frustumCulled = false;
  scene.add(skyMesh, dome);
  const group = new THREE.Group();
  scene.add(group);
  const { w: W, d: D, h: H } = ROOM;
  const r = rng(`floor-${d.task.date}`);

  const floor = new THREE.Mesh(new THREE.PlaneGeometry(W, D).rotateX(-Math.PI / 2), new THREE.MeshStandardMaterial({ map: carpet(), roughness: 0.95 }));
  floor.receiveShadow = true;
  const ceilTex = ceilingTiles();
  const ceilMat = new THREE.MeshStandardMaterial({ map: ceilTex, roughness: 1, emissive: new THREE.Color("#8f8d88"), emissiveMap: ceilTex, emissiveIntensity: 0.35 });
  const ceil = new THREE.Mesh(new THREE.BoxGeometry(W, 0.1, D).translate(0, H + 0.05, 0), ceilMat);
  ceil.castShadow = true;
  ceil.receiveShadow = true;
  group.add(floor, ceil);
  const wallMat = new THREE.MeshStandardMaterial({ color: "#d6d3cc", roughness: 0.9 });
  const slab = new THREE.MeshStandardMaterial({ color: "#3a3d42", roughness: 0.8 });
  const north = new THREE.Mesh(new THREE.BoxGeometry(W, H, 0.2).translate(0, H / 2, -D / 2 - 0.1), new THREE.MeshStandardMaterial({ color: "#5b5f66", roughness: 0.85 }));
  const south = new THREE.Mesh(new THREE.BoxGeometry(W, H, 0.2).translate(0, H / 2, D / 2 + 0.1), wallMat);
  const west = new THREE.Mesh(new THREE.BoxGeometry(0.2, H, D).translate(-W / 2 - 0.1, H / 2, 0), new THREE.MeshStandardMaterial({ map: slats(), roughness: 0.75 }));
  for (const m of [north, south, west]) (m.castShadow = true), (m.receiveShadow = true), group.add(m);
  const bays = Math.round(D / 1.5);
  const bw = D / bays;
  const frame = new THREE.MeshStandardMaterial({ color: "#8e959b", roughness: 0.35, metalness: 0.7 });
  const parts = [];
  for (let i = 0; i <= bays; i++) parts.push(new THREE.BoxGeometry(0.08, H, 0.08).translate(W / 2, H / 2, -D / 2 + i * bw));
  parts.push(new THREE.BoxGeometry(0.12, 0.32, D).translate(W / 2, 0.16, 0), new THREE.BoxGeometry(0.12, 0.42, D).translate(W / 2, H - 0.21, 0));
  const mullions = new THREE.Mesh(mergeGeometries(parts), frame);
  mullions.castShadow = true;
  group.add(mullions);
  const glass = new THREE.Mesh(new THREE.PlaneGeometry(D, H - 0.74).rotateY(-Math.PI / 2).translate(W / 2 + 0.02, 0.32 + (H - 0.74) / 2, 0),
    new THREE.MeshStandardMaterial({ color: "#9fb7c4", transparent: true, opacity: 0.1, roughness: 0.05, metalness: 0.2, depthWrite: false }));
  group.add(glass);
  const shadeMat = new THREE.MeshStandardMaterial({ color: "#c9c5bb", roughness: 0.9, transparent: true, opacity: 0.86, side: THREE.DoubleSide });
  const shadeParts = [];
  for (let i = 0; i < bays; i++) {
    const drop = [0.2, 0.9, 0.45, 0.2, 1.2, 0.2, 0.6, 0.3, 1.0, 0.25, 0.7][i % 11];
    shadeParts.push(new THREE.PlaneGeometry(bw - 0.1, drop).rotateY(-Math.PI / 2).translate(W / 2 - 0.08, H - 0.42 - drop / 2, -D / 2 + (i + 0.5) * bw));
    shadeParts.push(new THREE.BoxGeometry(0.06, 0.05, bw - 0.1).translate(W / 2 - 0.08, H - 0.42 - drop, -D / 2 + (i + 0.5) * bw));
  }
  const shades = new THREE.Mesh(mergeGeometries(shadeParts.map((g) => (g.index ? g.toNonIndexed() : g))), shadeMat);
  shades.castShadow = true;
  group.add(shades);

  const lightMat = new THREE.MeshStandardMaterial({ color: "#fff", emissive: new THREE.Color("#fff6e8"), emissiveIntensity: 1 });
  const strips = [], housings = [];
  for (const x of [-7.5, -2.5, 2.5, 7.5])
    for (const z of [-6, -2, 2, 6]) {
      strips.push(new THREE.BoxGeometry(0.12, 0.02, 3.0).translate(x, H - 0.035, z));
      housings.push(new THREE.BoxGeometry(0.2, 0.05, 3.1).translate(x, H - 0.02, z));
    }
  group.add(new THREE.Mesh(mergeGeometries(housings), new THREE.MeshStandardMaterial({ color: "#c9c8c4", roughness: 0.4, metalness: 0.6 })));
  group.add(new THREE.Mesh(mergeGeometries(strips), lightMat));

  const benchG = bench(), chairG = chair(), vc = new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.6, metalness: 0.1 });
  const benches = [], chairs = [], mons = [], screens = [];
  const mm = monitorMatrices();
  const deskPos = [];
  ROWS.forEach((z, ri) => SEATS_X.forEach((x) => deskPos.push({ x, z, row: ri, a: ri === 0 && x === A_DESK.x })));
  for (const p of deskPos) {
    const base = new THREE.Matrix4().makeTranslation(p.x, 0, p.z);
    benches.push(base);
    chairs.push(new THREE.Matrix4().makeTranslation(p.x + (r() - 0.5) * 0.1, 0, p.z + 0.35 + r() * 0.12).multiply(new THREE.Matrix4().makeRotationY((r() - 0.5) * 0.4)));
    mm.forEach((m, k) => {
      const w = base.clone().multiply(m);
      mons.push(w);
      screens.push({ m: w.clone().multiply(new THREE.Matrix4().makeTranslation(0, 0, 0.021)), a: p.a, k });
    });
  }
  const instM = (geo, mat, list, shadow = true) => {
    const m = new THREE.InstancedMesh(geo, mat, list.length);
    list.forEach((x, i) => m.setMatrixAt(i, x));
    m.castShadow = shadow;
    m.receiveShadow = true;
    group.add(m);
    return m;
  };
  instM(benchG, vc, benches);
  instM(chairG, vc, chairs);
  instM(paint(new THREE.BoxGeometry(MON.w, MON.h, 0.03), 0x15171a), vc, mons);
  const gens = genericScreens(r).map((c) => {
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return screenMaterial(t, 0.85);
  });
  const plane = new THREE.PlaneGeometry(MON.w - 0.02, MON.h - 0.02);
  const byMat = new Map();
  for (const s of screens) {
    if (s.a && (s.k === 0 || s.k === 1 || s.k === 2)) continue;
    const mat = gens[Math.floor(r() * gens.length)];
    if (!byMat.has(mat)) byMat.set(mat, []);
    byMat.get(mat).push(s.m);
  }
  for (const [mat, list] of byMat) instM(plane, mat, list, false);
  const aCanvas = (w, h) => {
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.anisotropy = 8;
    return { c, g: c.getContext("2d"), t };
  };
  const ladder = aCanvas(768, 460), blotter = aCanvas(768, 460), merit3 = aCanvas(768, 460);
  const aScreens = screens.filter((s) => s.a && s.k < 3);
  [ladder, merit3, blotter].forEach((cv, i) => {
    const m = new THREE.Mesh(plane, screenMaterial(cv.t, 1));
    m.applyMatrix4(aScreens[i].m);
    group.add(m);
  });

  const FOLK = [
    { shirt: 0x55606c, skin: 0xc69a7c, hair: 0x2a211c }, { shirt: 0xdfe3e8, skin: 0x8d5f43, hair: 0x15100c },
    { shirt: 0x6b6460, skin: 0xd8b294, hair: 0x6a4a30, style: "long" }, { shirt: 0x2f3a46, skin: 0xb27c5c, hair: 0x1d1612, style: "bun" },
    { shirt: 0x9db3c8, skin: 0xe0bc9c, hair: 0x8a8a8a }, { shirt: 0x46533f, skin: 0xa8724f, hair: 0x241a12 },
    { shirt: 0xf2efe8, skin: 0xc58c6a, hair: 0x3a2a1e, style: "long" },
  ];
  const seated = deskPos.filter((p, i) => p.a || (p.x !== A_DESK.x + 1.8 && r() < 0.45 + (p.row === 0 ? 0.2 : 0)));
  const people = new THREE.Group();
  const phoneGuy = new THREE.Mesh(person({ ...FOLK[1], phone: true }), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.75 }));
  const aGuy = new THREE.Mesh(person(FOLK[1]), phoneGuy.material);
  for (const [i, p] of seated.entries()) {
    const m = p.a ? aGuy : new THREE.Mesh(person(FOLK[(i * 3 + 1) % FOLK.length]), phoneGuy.material);
    m.position.set(p.x, 0, p.z + 0.42);
    m.rotation.y = p.a ? 0 : (r() - 0.5) * 0.3;
    m.castShadow = true;
    people.add(m);
  }
  phoneGuy.position.copy(aGuy.position);
  phoneGuy.visible = false;
  people.add(phoneGuy);
  group.add(people);

  const plants = [];
  for (const [x, z] of [[-11.2, 7.6], [11, 7.6], [-11.2, -7.6], [11.1, -7.4], [-11.2, 1.2]]) {
    plants.push(paint(new THREE.CylinderGeometry(0.26, 0.2, 0.5, 14).translate(x, 0.25, z), 0x3b3e42));
    for (let k = 0; k < 9; k++) plants.push(ball(0.22 + r() * 0.12, [x + (r() - 0.5) * 0.4, 0.75 + r() * 0.9, z + (r() - 0.5) * 0.4], 0x3f6a3a + Math.floor(r() * 3) * 0x020302, [1, 1.4, 1]));
  }
  const pm = new THREE.Mesh(mergeGeometries(plants), new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.85 }));
  pm.castShadow = true;
  group.add(pm);

  const wallW = WALL.cols * WALL.pw, wallH = WALL.rows * WALL.ph;
  const bezel = new THREE.Mesh(new THREE.BoxGeometry(wallW + 0.08, wallH + 0.08, 0.08).translate(0, WALL.y0 + wallH / 2, WALL.z - 0.04), new THREE.MeshStandardMaterial({ color: "#0c0d0f", roughness: 0.5 }));
  group.add(bezel);
  const big = (w, h) => aCanvas(w, h);
  const vClock = big(1280, 720), vMerit = big(1280, 720), vPrices = big(1280, 720);
  const panels = [vClock, vMerit, vPrices];
  panels.forEach((cv, i) => {
    const m = new THREE.Mesh(new THREE.PlaneGeometry(2 * WALL.pw - 0.01, wallH - 0.01), screenMaterial(cv.t, 1.05));
    m.position.set((i - 1) * 2 * WALL.pw, WALL.y0 + wallH / 2, WALL.z + 0.005);
    group.add(m);
  });
  const seams = [];
  for (let c = 1; c < WALL.cols; c++) seams.push(new THREE.BoxGeometry(0.008, wallH, 0.01).translate(-wallW / 2 + c * WALL.pw, WALL.y0 + wallH / 2, WALL.z + 0.012));
  seams.push(new THREE.BoxGeometry(wallW, 0.008, 0.01).translate(0, WALL.y0 + WALL.ph, WALL.z + 0.012));
  group.add(new THREE.Mesh(mergeGeometries(seams), new THREE.MeshBasicMaterial({ color: "#050607" })));
  const ticker = aCanvas(2048, 64);
  const tick = new THREE.Mesh(new THREE.PlaneGeometry(wallW, 0.22), screenMaterial(ticker.t, 1));
  tick.position.set(0, WALL.y0 + wallH + 0.2, WALL.z + 0.01);
  group.add(tick);

  const outside = new THREE.Group();
  scene.add(outside);
  const street = new THREE.Mesh(new THREE.CircleGeometry(9000, 48).rotateX(-Math.PI / 2).translate(0, -95, 0), new THREE.MeshStandardMaterial({ color: "#5d625f", roughness: 1 }));
  outside.add(street);
  const towerDay = facade("tw-day", false), towerLit = facade("tw-lit", true);
  towerDay.wrapS = towerDay.wrapT = towerLit.wrapS = towerLit.wrapT = THREE.RepeatWrapping;
  const towerMat = new THREE.MeshStandardMaterial({ map: towerDay, emissiveMap: towerLit, emissive: new THREE.Color("#ffe2b0"), emissiveIntensity: 0, roughness: 0.35, metalness: 0.35 });
  const stoneMat = new THREE.MeshStandardMaterial({ color: "#b9b1a3", roughness: 0.85 });
  const tw = [], st = [];
  for (let i = 0; i < 70; i++) {
    const a = -1.3 + r() * 2.6 + (i % 5 === 0 ? Math.PI : 0), dist = 130 + Math.pow(r(), 1.3) * 900;
    const x = W / 2 + Math.cos(a) * dist, z = Math.sin(a) * dist;
    const hgt = 30 + Math.pow(r(), 1.6) * 210, wd = 22 + r() * 30, dp = 22 + r() * 30;
    const g = new THREE.BoxGeometry(wd, hgt, dp).translate(x, -95 + hgt / 2, z);
    const uv = g.attributes.uv;
    for (let k = 0; k < uv.count; k++) uv.setXY(k, uv.getX(k) * wd / 32, uv.getY(k) * hgt / 64);
    (r() < 0.75 ? tw : st).push(g);
  }
  const towers = new THREE.Mesh(mergeGeometries(tw), towerMat);
  const stones = new THREE.Mesh(mergeGeometries(st), stoneMat);
  towers.castShadow = stones.castShadow = false;
  outside.add(towers, stones);

  const hemi = new THREE.HemisphereLight("#cfd8e2", "#4a4640", 0.3);
  const sun = new THREE.DirectionalLight("#fff", 0);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  Object.assign(sun.shadow.camera, { left: -16, right: 16, top: 16, bottom: -16, near: 1, far: 140 });
  sun.shadow.camera.updateProjectionMatrix();
  sun.shadow.bias = -0.0004;
  sun.shadow.normalBias = 0.03;
  scene.add(hemi, sun, sun.target);
  const spots = [];
  for (const x of [-6, 0, 6])
    for (const z of [-4.5, 0.5, 5.5]) {
      const s = new THREE.SpotLight("#ffe9d2", 20, 9, 0.95, 0.85, 1.6);
      s.position.set(x, H - 0.05, z);
      s.target.position.set(x, 0, z + 0.2);
      scene.add(s, s.target);
      spots.push(s);
    }
  const wallGlow = new THREE.RectAreaLight("#9cb8de", 3, wallW, wallH);
  wallGlow.position.set(0, WALL.y0 + wallH / 2, WALL.z + 0.05);
  wallGlow.lookAt(0, WALL.y0 + wallH / 2, 5);
  scene.add(wallGlow);

  const env = new THREE.Scene();
  env.add(new THREE.Mesh(new THREE.BoxGeometry(20, 6, 20), new THREE.MeshBasicMaterial({ color: "#3a3d42", side: THREE.BackSide })));
  for (const [x, z, c, s] of [[0, -9.5, "#8fb4e0", 4], [9.5, 0, "#f1efe6", 7], [-5, 0, "#fff3e0", 3], [5, 0, "#fff3e0", 3]]) {
    const p = new THREE.Mesh(new THREE.PlaneGeometry(s * 2, 2.5), new THREE.MeshBasicMaterial({ color: new THREE.Color(c).multiplyScalar(4) }));
    p.position.set(x, 2, z);
    p.lookAt(0, 2, 0);
    env.add(p);
  }
  let pmrem = null;

  const cardTex = new Map();
  const cardMat = (ev) => {
    if (!cardTex.has(ev.key)) {
      const t = canvasTexture(900, 220, (g, w, h) => drawCard(g, w, h, ev));
      cardTex.set(ev.key, new THREE.SpriteMaterial({ map: t, transparent: true, depthWrite: false, depthTest: false, fog: false }));
    }
    return cardTex.get(ev.key);
  };
  const cards = [0, 1].map(() => {
    const s = new THREE.Sprite();
    s.scale.set(0.82, 0.2, 1);
    s.renderOrder = 10;
    s.visible = false;
    group.add(s);
    return s;
  });
  const glow = new THREE.Sprite(new THREE.SpriteMaterial({ map: glowTexture(), color: "#ffcf6a", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0 }));
  glow.position.set(0, WALL.y0 + wallH / 2, WALL.z + 0.3);
  glow.scale.set(wallW * 0.6, wallH * 1.4, 1);
  group.add(glow);

  const events = roomEvents(d);
  const keys = { clock: "", merit: "", prices: "", ladder: "", blotter: "", m3: "", ticker: "" };
  const redraw = (k, key, cv, draw) => {
    if (keys[k] === key) return;
    keys[k] = key;
    draw(cv.g, cv.c.width, cv.c.height);
    cv.t.needsUpdate = true;
  };

  function wallHour(s) {
    if (s.h != null) return s.h;
    const awarded = d.aw.A.map((a, h) => [Math.abs(a), h]).filter(([a]) => a > 0.5);
    const key = awarded.length ? awarded.map(([, h]) => h) : [d.peakH];
    if (s.min < AWARDS || s.t < d.awardsT + 0.95) return d.peakH;
    const order = [d.peakH, ...key.filter((h) => h !== d.peakH)];
    return order[Math.floor((s.t - d.awardsT - 0.95) / 0.3) % order.length];
  }

  function update({ t, s, sky: st, sunLight, hemiLight, dt, wall, weather, renderer, reduced, shot }) {
    if (!pmrem) {
      const gen = new THREE.PMREMGenerator(renderer);
      pmrem = gen.fromScene(env, 0.04);
      scene.environment = pmrem.texture;
      renderer.setRenderTarget(null);
    }
    scene.environmentIntensity = 0.32;
    sun.color.copy(sunLight.color);
    sun.intensity = sunLight.intensity * 1.15;
    sun.target.position.set(0, 0, 0);
    sun.position.copy(st.sunDir).multiplyScalar(60);
    sun.castShadow = st.el > 0.5 && sunLight.intensity > 0.1;
    hemi.color.set("#f3efe8").lerp(hemiLight.color, 0.25);
    hemi.groundColor.set("#5a5650");
    hemi.intensity = 0.55 + 0.75 * st.day;
    const lightsOn = 0.55 + 0.45 * (1 - st.day);
    ceilMat.emissiveIntensity = 0.22 + 0.18 * lightsOn;
    for (const x of spots) x.intensity = 26 * lightsOn;
    lightMat.emissiveIntensity = 0.9 + 0.5 * lightsOn;
    towerMat.emissiveIntensity = 1.6 * st.night;
    const hour = wallHour(s);
    const minKey = Math.floor(s.min * (s.min < AWARDS ? 6 : 1));
    redraw("clock", `${minKey}|${weather}`, vClock, (g, w, h) => drawClock(g, w, h, d, { ...s, weather }));
    const reveal = s.min >= AWARDS ? Math.min(1, (s.t - d.awardsT) / 0.35 + 0.001) : 1;
    redraw("merit", `${hour}|${s.min >= AWARDS}|${Math.round(reveal * 40)}|${s.min >= DAM_CLOSE}|${d.offerAt(t)?.t}`, vMerit, (g, w, h) => drawMerit(g, w, h, d, s, hour, { reveal }));
    redraw("prices", `${s.min >= AWARDS}|${s.h}|${Math.floor(Math.max(0, s.min) / 60)}|${d.offerAt(t)?.t}`, vPrices, (g, w, h) => drawPrices(g, w, h, d, s));
    redraw("ladder", `${d.offerAt(t)?.t}|${s.h}`, ladder, (g, w, h) => drawLadder(g, w, h, d, s));
    redraw("blotter", `${s.min < 0 ? d.steps.filter((x) => x.t <= t).length : Math.floor(s.min / 60)}`, blotter, (g, w, h) => drawBlotter(g, w, h, d, s));
    redraw("m3", `${hour}|${s.min >= AWARDS}|${d.offerAt(t)?.t}`, merit3, (g, w, h) => drawMerit(g, w, h, d, s, hour));
    redraw("ticker", `${Math.floor(Math.max(-1, s.min) / 60)}|${s.min >= AWARDS}`, ticker, (g, w, h) => drawTicker(g, w, h, d, s));
    const flash = d.awardsT != null && t >= d.awardsT && t < d.awardsT + 0.35 && !reduced ? 1 - (t - d.awardsT) / 0.35 : 0;
    glow.material.opacity = 0.35 * flash;
    const deal = d.contracts.find((c) => c.status === "accepted" && t >= c.t - 0.05 && t < c.t + 0.55);
    phoneGuy.visible = !!deal;
    aGuy.visible = !deal;
    const live = CARD_SHOTS.has(shot) ? events.filter((e) => t >= e.t && t < e.t + e.dur).slice(-2) : [];
    cards.forEach((c, i) => {
      const e = live[live.length - 1 - i];
      c.visible = !!e;
      if (!e) return;
      c.material = cardMat(e);
      const u = (t - e.t) / e.dur;
      const rise = reduced ? 0.5 : u;
      c.position.set(A_DESK.x + 0.95, 1.98 + rise * 0.22 + i * 0.24, A_DESK.z - 0.55);
      c.material.opacity = Math.min(1, u * 8, (1 - u) * 6);
    });
    return { hour };
  }

  const cams = {
    room: (u, n) => n % 2 ? { pos: [10.2 - 1.2 * u, 2.4, 7.4], look: [-2, 1.4, -8], fov: 52 } : { pos: [-10.4 + 1.4 * u, 2.45, 7.3], look: [2.6, 1.3, -7.5], fov: 54 },
    desk: (u) => ({ pos: [0.78 - 0.12 * u, 1.66, A_DESK.z + 1.5 - 0.2 * u], look: [-0.12, 1.25, A_DESK.z - 0.7], fov: 42 }),
    wall: (u) => ({ pos: [0.7 - 1.4 * u, 1.95, -1.25], look: [0, 2.05, WALL.z], fov: 54 }),
    merit: (u) => ({ pos: [0, 2.15, -4.3 + 0.35 * u], look: [0, 2.15, WALL.z], fov: 34 }),
    clock: (u) => ({ pos: [-2 * WALL.pw + 0.3 - 0.3 * u, 2.15, -4.7 + 0.3 * u], look: [-2 * WALL.pw, 2.15, WALL.z], fov: 32 }),
    prices: (u) => ({ pos: [2 * WALL.pw - 0.3 + 0.3 * u, 2.15, -4.7 + 0.3 * u], look: [2 * WALL.pw, 2.15, WALL.z], fov: 32 }),
    deal: (u) => ({ pos: [-1.7 + 0.2 * u, 1.38, A_DESK.z + 0.25], look: [0.15, 1.12, A_DESK.z + 0.1], fov: 44 }),
    window: (u) => ({ pos: [10.4, 1.65, 7.2 - 0.6 * u], look: [7.5, 1.0, -6], fov: 52 }),
  };
  return { scene, update, cams, wall: WALL, aDesk: A_DESK, sun, hemi };
}

/** The cards that rise from seat A's desk: each accepted offer, the contracts, the close, the awards, the operating
 * day's commits and any mitigation. */
function roomEvents(d) {
  const out = [];
  for (const s of d.steps) {
    const o = s.out || {};
    if (s.tool === "submit_offer") {
      const hrs = offerHoursCount(s.args?.offer);
      out.push(o.accepted || o.submitted ? { t: s.t, title: "Offer submitted", line: `${hrs} hours · seat A · before the 10:00 close`, color: SEAT.A.color } : { t: s.t, title: "Offer refused", line: (o.issues || []).slice(0, 1).map((x) => x.rule).join(", ") || o.error || "", color: "#cf3e33", stamp: true });
    } else if (s.tool === "check_offer") out.push({ t: s.t, title: o.valid ? "Offer checked" : "Check: issues", line: o.valid ? `estimate $${Math.round(o.estimate?.dam_usd ?? 0).toLocaleString("en-US")} on the disclosure forecast` : `${(o.issues || []).length} issues`, color: o.valid ? "#3f8656" : "#cf3e33" });
    else if (s.tool === "propose_contract" || s.tool === "respond_contract") {
      if (o.status) out.push({ t: s.t, title: o.status === "accepted" ? "CfD confirmed with retail-L" : `CfD ${o.status}`, line: `${Math.round(Math.abs(o.mw || 0))} MW · ${heList(o.hours)} · strike $${(o.strike_usd ?? 0).toFixed(2)}`, color: SEAT.L.color });
    } else if (s.tool === "commit_schedule" && o.accepted && d.watches[s.watch].min >= 0) out.push({ t: s.t, title: "Schedule committed", line: `from HE${(s.args?.from_hour ?? 0) + 1} · on the awards' prices`, color: SEAT.A.color });
  }
  out.push({ t: d.closeT, title: "DAM closed", line: "offers frozen at 10:00 · ERCOT clears 24 hours", color: "#c58a12" });
  out.push({ t: d.awardsT, title: "Awards posted", line: awardsLine(d), color: "#2a78d6" });
  for (const m of d.clear.mitigated.filter((x) => x.seat === "A")) out.push({ t: m.he - 1 + 0.05, title: `Mitigated HE${m.he}`, line: "conduct and impact: re-priced to the reference", color: "#cf3e33", stamp: true });
  return out.filter((e) => e.t != null).map((e, i) => ({ ...e, key: `${i}-${e.title}`, dur: e.t < 0 ? 0.55 : 0.9 }));
}

function offerHoursCount(offer) {
  const o = typeof offer === "string" ? (() => { try { return JSON.parse(offer); } catch { return null; } })() : offer;
  return (o?.hours || o || []).filter?.((x) => (x.sell?.length || x.buy?.length)).length ?? 0;
}

export function awardsLine(d) {
  const sell = d.aw.A.reduce((a, x) => a + Math.max(0, x), 0), buy = d.aw.A.reduce((a, x) => a + Math.max(0, -x), 0);
  if (sell + buy < 0.5) return "seat A: no award";
  return `seat A sells ${Math.round(sell).toLocaleString("en-US")} MWh · buys ${Math.round(buy).toLocaleString("en-US")} MWh`;
}

function drawTicker(g, w, h, d, s) {
  g.fillStyle = "#06090d";
  g.fillRect(0, 0, w, h);
  g.font = "600 30px 'SF Mono', Menlo, monospace";
  g.textBaseline = "middle";
  let x = 20;
  const items = s.min >= AWARDS ? d.clear.hub.map((p, k) => [`HE${k + 1}`, p, d.hubReal[k]])
    : [["ERCOT DAM · OFFERS DUE 10:00 CPT", null], [`OPERATING DAY ${d.dateLabel.toUpperCase()}`, null], [`SEAT A ${d.P} MW / ${Math.round(d.E)} MWh`, null], ["60-DAY DISCLOSURE · AGGREGATED", null], ["COPPER PLATE · HUB PRICES", null]];
  for (const [a, p, real] of items) {
    g.fillStyle = "#7f93a6";
    g.fillText(a, x, h / 2);
    x += g.measureText(a).width + 10;
    if (p != null) {
      g.fillStyle = p >= real ? "#5fd08f" : "#ff6a5c";
      const txt = `$${p.toFixed(2)}`;
      g.fillText(txt, x, h / 2);
      x += g.measureText(txt).width + 34;
    } else x += 30;
    if (x > w) break;
  }
}
