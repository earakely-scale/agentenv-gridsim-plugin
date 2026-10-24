import * as THREE from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

export const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _s = new THREE.Vector3(), _e = new THREE.Euler();

export function mat4(p, rotY = 0, s = 1, rotX = 0, rotZ = 0) {
  _q.setFromEuler(_e.set(rotX, rotY, rotZ));
  if (typeof s === "number") _s.set(s, s, s);
  else _s.copy(s);
  return new THREE.Matrix4().compose(p, _q, _s);
}

/** One InstancedMesh for a geometry at a list of matrices. */
export function inst(geom, material, mats, { shadow = true, receive = true } = {}) {
  const m = new THREE.InstancedMesh(geom, material, Math.max(1, mats.length));
  mats.forEach((x, i) => m.setMatrixAt(i, x));
  m.count = mats.length;
  m.castShadow = shadow;
  m.receiveShadow = receive;
  return m;
}

export function box(w, h, d, x = 0, y = 0, z = 0) {
  const g = new THREE.BoxGeometry(w, h, d);
  g.translate(x, y, z);
  return g;
}

export function cyl(rt, rb, h, x = 0, y = 0, z = 0, seg = 10, axis = "y") {
  const g = new THREE.CylinderGeometry(rt, rb, h, seg);
  if (axis === "x") g.rotateZ(Math.PI / 2);
  if (axis === "z") g.rotateX(Math.PI / 2);
  g.translate(x, y, z);
  return g;
}

export const merge = (parts) => mergeGeometries(parts.map((p) => (p.index ? p.toNonIndexed() : p)));

/** A ribbed porcelain or polymer insulator of height h standing on the origin. */
export function insulator(h, r = 0.16, sheds = 8) {
  const pts = [new THREE.Vector2(0.001, 0), new THREE.Vector2(r * 0.6, 0)];
  for (let i = 0; i < sheds; i++) {
    const y = (h * (i + 0.5)) / sheds;
    pts.push(new THREE.Vector2(r * 0.55, y - h / sheds / 2.5), new THREE.Vector2(r * 1.25, y), new THREE.Vector2(r * 0.55, y + h / sheds / 3));
  }
  pts.push(new THREE.Vector2(r * 0.5, h), new THREE.Vector2(0.001, h));
  return new THREE.LatheGeometry(pts, 10);
}

export function canvasTexture(w, h, draw, { repeat = null, aniso = 8 } = {}) {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  draw(c.getContext("2d"), w, h);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = aniso;
  if (repeat) {
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(...repeat);
  }
  return t;
}

/** A soft round glow sprite texture. */
export function glowTexture(size = 128) {
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  const r = g.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  r.addColorStop(0, "rgba(255,255,255,1)");
  r.addColorStop(0.18, "rgba(255,255,255,0.55)");
  r.addColorStop(0.45, "rgba(255,255,255,0.12)");
  r.addColorStop(1, "rgba(255,255,255,0)");
  g.fillStyle = r;
  g.fillRect(0, 0, size, size);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

/** Galvanised lattice steel as thin boxes between pairs of points, merged into one geometry. */
export function struts(pairs, t = 0.12) {
  const parts = [];
  const up = new THREE.Vector3(0, 1, 0);
  for (const [a, b] of pairs) {
    const d = new THREE.Vector3().subVectors(b, a);
    const len = d.length();
    if (len < 1e-3) continue;
    const g = new THREE.BoxGeometry(t, len, t);
    const q = new THREE.Quaternion().setFromUnitVectors(up, d.clone().normalize());
    g.applyMatrix4(new THREE.Matrix4().compose(a.clone().add(b).multiplyScalar(0.5), q, new THREE.Vector3(1, 1, 1)));
    parts.push(g.toNonIndexed());
  }
  return mergeGeometries(parts);
}
