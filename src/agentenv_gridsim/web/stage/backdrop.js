import * as THREE from "three";
import { box, cyl, glowTexture, inst, mat4, merge, V } from "./kit.js";
import { rng } from "./rng.js";

const DEG = Math.PI / 180;
const at = (bearing, m) => [Math.sin(bearing * DEG) * m, -Math.cos(bearing * DEG) * m];

function windowMaterial({ base, glass, lit }) {
  const U = { uNight: { value: 0 }, uLit: { value: lit } };
  const m = new THREE.MeshStandardMaterial({ color: base, roughness: 0.35, metalness: 0.55 });
  m.onBeforeCompile = (sh) => {
    Object.assign(sh.uniforms, U);
    sh.vertexShader = sh.vertexShader
      .replace("#include <common>", "#include <common>\nvarying vec3 vWP; varying vec3 vWN;")
      .replace("#include <begin_vertex>", `#include <begin_vertex>
        vec4 wq = modelMatrix * vec4(transformed, 1.0);
        #ifdef USE_INSTANCING
          wq = modelMatrix * instanceMatrix * vec4(transformed, 1.0);
          vWN = normalize(mat3(modelMatrix * instanceMatrix) * objectNormal);
        #else
          vWN = normalize(mat3(modelMatrix) * objectNormal);
        #endif
        vWP = wq.xyz;`);
    sh.fragmentShader = sh.fragmentShader
      .replace("#include <common>", `#include <common>\nvarying vec3 vWP; varying vec3 vWN;\nuniform float uNight, uLit;
        float wHash(vec3 p) { return fract(sin(dot(p, vec3(12.9898, 78.233, 37.719))) * 43758.5453); }`)
      .replace("#include <emissivemap_fragment>", `#include <emissivemap_fragment>
        {
          vec3 an = abs(vWN);
          float side = step(an.y, 0.6);
          float h = (an.x > an.z ? vWP.z : vWP.x);
          vec2 cell = vec2(floor(h / 3.2), floor(vWP.y / 3.6));
          vec2 f = vec2(fract(h / 3.2), fract(vWP.y / 3.6));
          float win = step(0.18, f.x) * step(f.x, 0.82) * step(0.25, f.y) * step(f.y, 0.85);
          float r = wHash(vec3(cell, floor(vWP.x * 0.01) + floor(vWP.z * 0.01) * 7.0));
          float on = step(1.0 - uLit, r) * win * side * step(4.0, vWP.y);
          vec3 warm = mix(vec3(1.0, 0.78, 0.48), vec3(0.85, 0.9, 1.0), step(0.7, wHash(vec3(cell.yx, 3.0))));
          totalEmissiveRadiance += warm * on * uNight * (1.6 + 1.2 * r);
          diffuseColor.rgb *= mix(1.0, 0.72 + 0.4 * win, side * (1.0 - uNight));
        }`);
  };
  return { m, U };
}

function skyline(city, heightAt, seed) {
  const g = new THREE.Group();
  const r = rng(seed);
  const [cx, cz] = at(city.bearing, city.km * 1000);
  const base = heightAt(cx, cz);
  const glass = windowMaterial({ base: "#7f909d", lit: 0.42 });
  const stone = windowMaterial({ base: "#b4ab9c", lit: 0.36 });
  const towersG = [], towersS = [], tops = [];
  for (let i = 0; i < city.towers; i++) {
    const rad = Math.pow(r(), 1.5) * city.spread * 650;
    const a = r() * Math.PI * 2;
    const x = cx + Math.cos(a) * rad, z = cz + Math.sin(a) * rad;
    const hgt = city.tallest * (0.25 + 0.75 * Math.pow(r(), 2.4)) * (1 - 0.4 * rad / (city.spread * 650));
    const w = 22 + r() * 30, d = 22 + r() * 30;
    const m = mat4(V(x, base + hgt / 2, z), r() * Math.PI, V(w, hgt, d));
    (r() < 0.62 ? towersG : towersS).push(m);
    if (hgt > 120) tops.push(V(x, base + hgt + 2, z));
    if (r() < 0.25 && hgt > 80) {
      const set = hgt * (0.12 + r() * 0.12);
      (r() < 0.5 ? towersG : towersS).push(mat4(V(x, base + hgt + set / 2, z), r() * Math.PI, V(w * 0.6, set, d * 0.6)));
    }
  }
  if (city.needle) {
    g.add(Object.assign(new THREE.Mesh(merge([cyl(5, 7, 190, 0, 95, 0, 12), cyl(15, 12, 16, 0, 192, 0, 16), cyl(2, 2, 26, 0, 213, 0, 6)]), stone.m), { position: V(cx + 400, base, cz - 300) }));
    tops.push(V(cx + 400, base + 228, cz - 300));
  }
  const unit = new THREE.BoxGeometry(1, 1, 1);
  g.add(inst(unit, glass.m, towersG, { shadow: false, receive: false }));
  g.add(inst(unit, stone.m, towersS, { shadow: false, receive: false }));
  const low = [];
  for (let i = 0; i < city.towers * 18; i++) {
    const rad = city.spread * 600 + Math.pow(r(), 0.8) * city.spread * 3200;
    const a = r() * Math.PI * 2;
    const x = cx + Math.cos(a) * rad, z = cz + Math.sin(a) * rad;
    const h = 8 + Math.pow(r(), 3) * 40;
    low.push(mat4(V(x, heightAt(x, z) + h / 2 - 1, z), r() * Math.PI, V(30 + r() * 60, h, 30 + r() * 60)));
  }
  const lowMat = windowMaterial({ base: "#a59f94", lit: 0.22 });
  g.add(inst(unit, lowMat.m, low, { shadow: false, receive: false }));
  const red = beacons(tops, "#ff3b2e", 22);
  g.add(red.group);
  return { group: g, mats: [glass, stone, lowMat], beacons: red };
}

function beacons(list, color, size) {
  const g = new THREE.Group();
  const mat = new THREE.SpriteMaterial({ map: glowTexture(), color, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, opacity: 0, fog: false });
  for (const p of list) {
    const s = new THREE.Sprite(mat);
    s.position.copy(p);
    s.scale.setScalar(size);
    g.add(s);
  }
  return { group: g, mat };
}

function cityLights(city, heightAt, seed, n = 2600) {
  const r = rng(seed + "-lights");
  const [cx, cz] = at(city.bearing, city.km * 1000);
  const pos = [];
  for (let i = 0; i < n; i++) {
    const rad = Math.pow(r(), 0.7) * city.spread * 3600;
    const a = r() * Math.PI * 2;
    const x = cx + Math.cos(a) * rad, z = cz + Math.sin(a) * rad;
    pos.push(x, heightAt(x, z) + 4 + r() * 6, z);
  }
  const geom = new THREE.BufferGeometry();
  geom.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({ color: "#ffc37a", size: 2.2, sizeAttenuation: false, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
  return { points: new THREE.Points(geom, mat), mat };
}

function turbineParts() {
  const tower = cyl(1.6, 2.6, 84, 0, 42, 0, 14);
  const nacelle = merge([box(11, 4, 4, -3, 0, 0), cyl(1.6, 1.4, 2.5, 3.2, 0, 0, 12, "x")]);
  const blade = new THREE.BufferGeometry();
  const L = 52;
  const shape = [[0, -1.6], [L * 0.25, -1.9], [L, -0.35], [L, 0.2], [L * 0.25, 1.2], [0, 1.2]];
  const v = [];
  for (let i = 1; i < shape.length - 1; i++) for (const k of [0, i, i + 1]) v.push(0, shape[k][0], shape[k][1] * 0.95);
  blade.setAttribute("position", new THREE.Float32BufferAttribute(v, 3));
  blade.computeVertexNormals();
  const parts = [];
  for (let k = 0; k < 3; k++) {
    const b = blade.clone();
    b.rotateX((k * 2 * Math.PI) / 3);
    parts.push(b);
  }
  const rotor = merge(parts);
  return { tower, nacelle, rotor };
}

function turbines(spec, heightAt, seed) {
  const r = rng(seed + "-wt");
  const pts = [];
  for (let i = 0; i < spec.n * 4 && pts.length < spec.n; i++) {
    const [b0, b1] = spec.bearing;
    const span = (b1 - b0 + 360) % 360;
    const b = b0 + r() * span;
    const km = spec.km[0] + r() * (spec.km[1] - spec.km[0]);
    const [x, z] = at(b, km * 1000);
    if (pts.some((p) => Math.hypot(p.x - x, p.z - z) < 420)) continue;
    pts.push(V(x, heightAt(x, z), z));
  }
  const parts = turbineParts();
  const white = new THREE.MeshStandardMaterial({ color: "#eef0f0", roughness: 0.45, metalness: 0.1 });
  const towerMesh = inst(parts.tower, white, pts.map((p) => mat4(p)), { shadow: false });
  const nac = inst(parts.nacelle, white, pts.map((p) => mat4(V(p.x, p.y + 85, p.z))), { shadow: false });
  const rot = inst(parts.rotor, white, pts.map((p) => mat4(V(p.x, p.y + 85, p.z))), { shadow: false });
  rot.side = THREE.DoubleSide;
  white.side = THREE.DoubleSide;
  const g = new THREE.Group();
  g.add(towerMesh, nac, rot);
  const red = beacons(pts.map((p) => V(p.x, p.y + 88, p.z)), "#ff2a1f", 16);
  g.add(red.group);
  const phase = pts.map(() => r() * Math.PI * 2);
  let spin = 0;
  const _m = new THREE.Matrix4(), _q = new THREE.Quaternion(), _e = new THREE.Euler(), one = V(1, 1, 1);
  return {
    group: g, beacons: red,
    update({ windMs, windDir, dt }) {
      const rpm = windMs < 3 ? 0 : Math.min(15, 4 + ((windMs - 3) / 9) * 11);
      spin += (rpm / 60) * 2 * Math.PI * dt;
      const yaw = -((windDir ?? 180) + 90) * DEG;
      pts.forEach((p, i) => {
        _q.setFromEuler(_e.set(0, yaw, 0, "YXZ"));
        nac.setMatrixAt(i, _m.compose(V(p.x, p.y + 85, p.z), _q, one));
        _q.setFromEuler(_e.set(spin + phase[i], yaw, 0, "YXZ"));
        const hub = V(5.2, 0, 0).applyAxisAngle(V(0, 1, 0), yaw).add(V(p.x, p.y + 85, p.z));
        rot.setMatrixAt(i, _m.compose(hub, _q, one));
      });
      nac.instanceMatrix.needsUpdate = rot.instanceMatrix.needsUpdate = true;
    },
  };
}

function pumpjack(color) {
  const g = new THREE.Group();
  const paint = new THREE.MeshStandardMaterial({ color, roughness: 0.55, metalness: 0.4 });
  const dark = new THREE.MeshStandardMaterial({ color: "#2c2e30", roughness: 0.7, metalness: 0.4 });
  const skid = new THREE.Mesh(box(9, 0.5, 2.2, 0, 0.25, 0), dark);
  const post = new THREE.Mesh(merge([box(0.3, 6, 0.3, 0.6, 3.2, 0.9), box(0.3, 6, 0.3, 0.6, 3.2, -0.9), box(0.3, 6.2, 0.3, -0.8, 3.2, 0)]), paint);
  const beam = new THREE.Group();
  beam.position.set(0.4, 6.2, 0);
  const bar = new THREE.Mesh(box(9.5, 0.55, 0.45, 0.6, 0, 0), paint);
  const head = new THREE.Mesh(merge([box(0.5, 2.4, 0.7, 5.4, -0.7, 0), box(0.9, 0.6, 0.7, 5.15, 0.4, 0)]), paint);
  beam.add(bar, head);
  const crank = new THREE.Group();
  crank.position.set(-3.6, 1.8, 0);
  const weights = new THREE.Mesh(merge([box(0.35, 2.6, 0.25, 0, -0.6, 1.0), box(0.35, 2.6, 0.25, 0, -0.6, -1.0), box(1.4, 1.1, 0.3, 0, -1.6, 1.05), box(1.4, 1.1, 0.3, 0, -1.6, -1.05)]), dark);
  crank.add(weights);
  const motor = new THREE.Mesh(box(1.4, 1.1, 1.0, -4.4, 1.0, 0), dark);
  const rod = new THREE.Mesh(cyl(0.05, 0.05, 6, 5.85, 3.0, 0, 5), dark);
  const well = new THREE.Mesh(cyl(0.3, 0.3, 1.2, 5.85, 0.6, 0, 8), dark);
  for (const m of [skid, post, bar, head, weights, motor, rod, well]) m.castShadow = true;
  g.add(skid, post, beam, crank, motor, rod, well);
  return { g, beam, crank, rod };
}

function pumpjacks(n, heightAt, avoid, seed) {
  const r = rng(seed + "-pj");
  const g = new THREE.Group();
  const list = [];
  const colors = ["#6d7a83", "#b23a2c", "#3d6b4f", "#c7a43a", "#4b5d74"];
  for (let i = 0; i < n * 5 && list.length < n; i++) {
    const rad = 180 + Math.pow(r(), 0.9) * 2600, a = r() * Math.PI * 2;
    const x = Math.cos(a) * rad, z = Math.sin(a) * rad;
    if (avoid(x, z) || list.some((p) => Math.hypot(p.x - x, p.z - z) < 260)) continue;
    const pj = pumpjack(colors[Math.floor(r() * colors.length)]);
    pj.g.position.set(x, heightAt(x, z), z);
    pj.g.rotation.y = r() * Math.PI * 2;
    const pad = new THREE.Mesh(new THREE.CircleGeometry(16, 20), new THREE.MeshStandardMaterial({ color: "#b49a7c", roughness: 1 }));
    pad.rotation.x = -Math.PI / 2;
    pad.position.set(x, pj.g.position.y + 0.05, z);
    pad.receiveShadow = true;
    g.add(pj.g, pad);
    list.push({ ...pj, x, z, phase: r() * Math.PI * 2, spm: 6 + r() * 5 });
  }
  let t = 0;
  return {
    group: g,
    update(dt) {
      t += dt;
      for (const p of list) {
        const a = (t * p.spm * 2 * Math.PI) / 60 + p.phase;
        p.crank.rotation.z = a;
        p.beam.rotation.z = Math.sin(a) * 0.32;
        p.rod.position.y = Math.sin(a) * 1.6;
      }
    },
  };
}

function refinery(spec, heightAt, seed) {
  const r = rng(seed + "-ref");
  const g = new THREE.Group();
  const [cx, cz] = at(spec.bearing, spec.km * 1000);
  const y0 = heightAt(cx, cz);
  const white = new THREE.MeshStandardMaterial({ color: "#e3e1db", roughness: 0.55, metalness: 0.3 });
  const steel = new THREE.MeshStandardMaterial({ color: "#8b9196", roughness: 0.5, metalness: 0.7 });
  const rust = new THREE.MeshStandardMaterial({ color: "#7d6656", roughness: 0.7, metalness: 0.4 });
  const tanks = [];
  for (let i = 0; i < 26; i++) {
    const x = cx - 700 + (i % 7) * 95 + r() * 10, z = cz + 260 + Math.floor(i / 7) * 95 + r() * 10;
    const d = 36 + r() * 30;
    tanks.push(mat4(V(x, y0 + 7, z), 0, V(d, 14 + r() * 6, d)));
  }
  g.add(inst(cyl(0.5, 0.5, 1, 0, 0, 0, 24), white, tanks, { shadow: false }));
  const cols = [], units = [], stacks = [];
  for (let i = 0; i < 22; i++) {
    const x = cx - 300 + r() * 650, z = cz - 250 + r() * 420;
    const h = 25 + r() * 55;
    cols.push(mat4(V(x, y0 + h / 2, z), 0, V(2 + r() * 4, h, 2 + r() * 4)));
  }
  for (let i = 0; i < 30; i++) {
    const x = cx - 350 + r() * 700, z = cz - 300 + r() * 500;
    const h = 10 + r() * 25;
    units.push(mat4(V(x, y0 + h / 2, z), r() * 0.3, V(20 + r() * 50, h, 15 + r() * 30)));
  }
  for (let i = 0; i < 5; i++) stacks.push(mat4(V(cx - 200 + i * 110 + r() * 30, y0 + 45, cz - 40 + r() * 80), 0, V(1, 90, 1)));
  g.add(inst(cyl(0.5, 0.5, 1, 0, 0, 0, 12), steel, cols, { shadow: false }));
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), rust, units, { shadow: false }));
  g.add(inst(cyl(2.2, 3.2, 1, 0, 0, 0, 12), new THREE.MeshStandardMaterial({ color: "#c9c3bb", roughness: 0.6 }), stacks, { shadow: false }));
  const flares = [V(cx + 380, y0, cz - 200), V(cx + 430, y0, cz - 120), V(cx - 420, y0, cz - 260)];
  const fl = flares.map((p) => {
    const pole = new THREE.Mesh(cyl(1.2, 1.8, 100, p.x, p.y + 50, p.z, 8), steel);
    g.add(pole);
    return V(p.x, p.y + 104, p.z);
  });
  const flameMat = new THREE.SpriteMaterial({ map: glowTexture(), color: "#ff9a3c", transparent: true, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
  const flames = fl.map((p) => {
    const s = new THREE.Sprite(flameMat.clone());
    s.position.copy(p);
    g.add(s);
    return s;
  });
  const pos = [];
  for (let i = 0; i < 3200; i++) {
    const x = cx - 380 + r() * 760, z = cz - 320 + r() * 560;
    pos.push(x, y0 + 3 + Math.pow(r(), 2) * 70, z);
  }
  const lg = new THREE.BufferGeometry();
  lg.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  const lmat = new THREE.PointsMaterial({ color: "#ffd38a", size: 2.0, sizeAttenuation: false, transparent: true, opacity: 0, depthWrite: false, blending: THREE.AdditiveBlending, fog: false });
  g.add(new THREE.Points(lg, lmat));
  const steamMat = new THREE.SpriteMaterial({ map: glowTexture(), color: "#f4f2ee", transparent: true, depthWrite: false, opacity: 0.35 });
  const steam = [];
  for (let i = 0; i < 5; i++) {
    for (let k = 0; k < 5; k++) {
      const s = new THREE.Sprite(steamMat);
      s.userData = { i, k, base: V(cx - 200 + i * 110, y0 + 92, cz - 40) };
      g.add(s);
      steam.push(s);
    }
  }
  return {
    group: g,
    update({ wall, night, windVec }) {
      flames.forEach((s, i) => {
        const f = 0.8 + 0.2 * Math.sin(wall * 7.3 + i * 2) * Math.sin(wall * 3.1 + i);
        s.scale.set(22 * f, 34 * f, 1);
        s.material.opacity = 0.75 + 0.25 * night;
      });
      lmat.opacity = Math.min(1, night * 1.3);
      for (const s of steam) {
        const { k, base } = s.userData;
        const u = ((wall * 0.08 + k / 5) % 1);
        s.position.set(base.x + windVec.x * u * 140, base.y + u * 60, base.z + windVec.y * u * 140);
        s.scale.setScalar(16 + u * 50);
        s.material.opacity = 0.32 * (1 - u) * (1 - night * 0.6);
      }
    },
  };
}

function grainElevator(heightAt, seed) {
  const r = rng(seed + "-ge");
  const g = new THREE.Group();
  const [cx, cz] = at(140, 2400);
  const y0 = heightAt(cx, cz);
  const conc = new THREE.MeshStandardMaterial({ color: "#d6d1c6", roughness: 0.85 });
  const silos = [];
  for (let i = 0; i < 12; i++) silos.push(mat4(V(cx + (i % 6) * 9.2, y0 + 19, cz + Math.floor(i / 6) * 9.2)));
  g.add(inst(cyl(4.6, 4.6, 38, 0, 0, 0, 20), conc, silos, { shadow: true }));
  const head = new THREE.Mesh(box(10, 58, 9, cx - 9, y0 + 29, cz + 4.6), conc);
  head.castShadow = true;
  g.add(head);
  const rail = new THREE.Mesh(new THREE.BoxGeometry(6000, 0.4, 3.2), new THREE.MeshStandardMaterial({ color: "#5b5650", roughness: 1 }));
  rail.position.set(cx, y0 + 0.2, cz + 22);
  g.add(rail);
  const cars = [];
  for (let i = 0; i < 18; i++) cars.push(mat4(V(cx - 260 + i * 17 + r() * 0.5, y0 + 2.6, cz + 22)));
  g.add(inst(box(16, 4.2, 3.1), new THREE.MeshStandardMaterial({ color: "#8e8a83", roughness: 0.7, metalness: 0.3 }), cars, { shadow: true }));
  return { group: g };
}

function suburbs(city, heightAt, seed, amount) {
  const r = rng(seed + "-sub");
  const g = new THREE.Group();
  const houses = [], roofs = [];
  const n = Math.round(1800 * amount);
  for (let i = 0; i < n; i++) {
    const b = city.bearing + (r() - 0.5) * 70;
    const km = 2.6 + Math.pow(r(), 0.7) * (city.km - 4);
    const [x, z] = at(b, km * 1000);
    const y = heightAt(x, z);
    const rot = Math.round(r() * 4) * (Math.PI / 2) + 0.05;
    houses.push(mat4(V(x, y + 1.6, z), rot, V(14, 3.2, 10)));
    roofs.push(mat4(V(x, y + 3.2, z), rot, V(15, 2.2, 11)));
  }
  const wall = windowMaterial({ base: "#c8bba6", lit: 0.5 });
  g.add(inst(new THREE.BoxGeometry(1, 1, 1), wall.m, houses, { shadow: false }));
  const roofG = new THREE.CylinderGeometry(0.5, 0.5, 1, 3, 1);
  roofG.rotateZ(Math.PI / 2);
  roofG.translate(0, 0.25, 0);
  g.add(inst(roofG, new THREE.MeshStandardMaterial({ color: "#5e5a57", roughness: 0.85, flatShading: true }), roofs, { shadow: false }));
  return { group: g, mats: [wall] };
}

/** What stands on the land around the site for a region: its city, wind farm, pumpjacks, refinery or grain elevator. */
export function buildBackdrop(region, heightAt, avoid, seed) {
  const group = new THREE.Group();
  const parts = {};
  parts.city = skyline(region.city, heightAt, seed);
  group.add(parts.city.group);
  parts.lights = cityLights(region.city, heightAt, seed, Math.round(2600 * region.city.lights));
  group.add(parts.lights.points);
  if (region.turbines) {
    parts.turbines = turbines(region.turbines, heightAt, seed);
    group.add(parts.turbines.group);
  }
  if (region.pumpjacks) {
    parts.pumpjacks = pumpjacks(region.pumpjacks, heightAt, avoid, seed);
    group.add(parts.pumpjacks.group);
  }
  if (region.refinery) {
    parts.refinery = refinery(region.refinery, heightAt, seed);
    group.add(parts.refinery.group);
  }
  if (region.grain) group.add(grainElevator(heightAt, seed).group);
  if (region.suburbs) {
    parts.suburbs = suburbs(region.city, heightAt, seed, region.suburbs);
    group.add(parts.suburbs.group);
  }
  const mats = [...parts.city.mats, ...(parts.suburbs?.mats || [])];
  return {
    group,
    update({ night, wall, dt, windMs, windDir, reduced }) {
      for (const m of mats) m.U.uNight.value = night;
      parts.lights.mat.opacity = Math.min(1, night * 1.2) * 0.9;
      const blink = reduced ? 1 : Math.sin(wall * Math.PI * 2 * 0.5) > 0 ? 1 : 0.08;
      parts.city.beacons.mat.opacity = night * 0.9 * blink;
      if (parts.turbines) {
        parts.turbines.update({ windMs, windDir, dt });
        parts.turbines.beacons.mat.opacity = night * blink;
      }
      parts.pumpjacks?.update(dt);
      const wd = ((windDir ?? 180) + 180) * DEG;
      parts.refinery?.update({ wall, night, windVec: new THREE.Vector2(Math.sin(wd), -Math.cos(wd)) });
    },
  };
}
