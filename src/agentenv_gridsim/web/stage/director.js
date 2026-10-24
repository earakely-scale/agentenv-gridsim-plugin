import * as THREE from "three";

const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));
const lerp = (a, b, u) => a + (b - a) * u;
const PRIORITY = { violation: 6, neg: 5, ramp: 4, push: 3, establish: 1, sub: 1, high: 1, line: 2 };

/** The automatic camera: a shot list cut from the day (establishing orbit, a push in when the action changes, a wide
 * shot down the line on the evening ramp, a close shot on a negative-price hour), each a pose as a function of t. */
export function buildDirector(d, L, { night }) {
  const slots = Array.from({ length: 24 * 4 }, (_, i) => ({ kind: i < 8 ? "establish" : null, p: i < 8 ? 2 : 0 }));
  const claim = (t0, t1, kind) => {
    for (let i = Math.max(0, Math.round(t0 * 4)); i < Math.min(96, Math.round(t1 * 4)); i++)
      if ((PRIORITY[kind] || 0) > slots[i].p) slots[i] = { kind, p: PRIORITY[kind] };
  };
  d.hours.forEach((x, h) => {
    if (h > 1 && x.mode !== d.hours[h - 1].mode && x.mode !== "grey") claim(h - 0.1, h + 1.4, "push");
  });
  if (d.prices[d.peakH] > d.median * 1.6) claim(d.peakH - 1.25, d.peakH + 1.5, "ramp");
  const negH = d.hours.find((x) => x.neg && x.action < 0)?.h ?? d.firstNeg;
  if (negH >= 0) claim(negH - 0.1, negH + 1.9, "neg");
  if (d.trunc != null) claim(d.trunc - 0.1, d.trunc + 2.2, "violation");
  const fill = ["sub", "establish", "line", "high"];
  let f = 0;
  for (let i = 0; i < 96; i++) {
    if (slots[i].kind) continue;
    let j = i;
    while (j < 96 && !slots[j].kind) j++;
    for (let k = i; k < j; k += 10) {
      const kind = night(k / 4 + 1) > 0.6 && fill[f % fill.length] === "sub" ? "high" : fill[f % fill.length];
      f++;
      for (let m = k; m < Math.min(j, k + 10); m++) slots[m] = { kind, p: 0.5 };
    }
    i = j - 1;
  }
  const shots = [];
  for (let i = 0; i < 96; i++) {
    const last = shots.at(-1);
    if (last && last.kind === slots[i].kind) last.t1 = (i + 1) / 4;
    else shots.push({ kind: slots[i].kind, t0: i / 4, t1: (i + 1) / 4 });
  }
  for (let i = 1; i < shots.length; i++)
    if (shots[i].t1 - shots[i].t0 < 1 && shots[i].kind !== "neg" && shots[i].kind !== "violation") {
      shots[i - 1].t1 = shots[i].t1;
      shots.splice(i, 1);
      i--;
    }
  shots.forEach((s, i) => (s.n = i));

  const front = [...L.enc].sort((a, b) => b.z - a.z || Math.abs(a.x - L.cx) - Math.abs(b.x - L.cx));
  const hero = front.find((e) => e.end > 0) || front[0];
  const ctr = new THREE.Vector3(L.cx + 18, 0, 0);
  const R = Math.max(L.W, L.D) * 0.9 + 140;

  const poses = {
    establish(u, s) {
      const a = 0.35 + (s.n % 2 ? -1 : 1) * 0.55 * u + s.n * 0.9;
      return { pos: [ctr.x + Math.cos(a) * R, 62 - 12 * u, ctr.z + Math.sin(a) * R], look: [ctr.x, 2, ctr.z], fov: 42 };
    },
    high(u, s) {
      const a = 1.1 + s.n * 0.7 + 0.35 * u;
      return { pos: [ctr.x + Math.cos(a) * R * 1.3, 150, ctr.z + Math.sin(a) * R * 1.3], look: [ctr.x + 30, 0, ctr.z], fov: 40 };
    },
    push(u, s) {
      const side = s.n % 2 ? -1 : 1;
      return { pos: [hero.x + side * lerp(26, 9, u), lerp(9, 3.2, u), hero.z + lerp(46, 15, u)], look: [hero.x + side * 1.5, 1.9, hero.z], fov: 38 };
    },
    neg(u) {
      const e = hero;
      return { pos: [e.x + lerp(13, 10, u), lerp(2.6, 2.3, u), e.z + lerp(8.5, 6.5, u)], look: [e.x + 1.2, 1.9, e.z + 0.6], fov: 44 };
    },
    violation(u) {
      return { pos: [hero.x - 6 - 4 * u, 3.4, hero.z + 13 - 2 * u], look: [hero.x, 2.0, hero.z + 1], fov: 40 };
    },
    ramp(u) {
      return { pos: [L.pad.x0 - 70 + 30 * u, 13, L.pad.z1 + 34], look: [L.sx + 2600, -90, -260], fov: 30 };
    },
    line(u) {
      return { pos: [L.sx - 70 + 20 * u, 18, -70], look: [L.sx + 1800, 30, 30], fov: 30 };
    },
    sub(u) {
      return { pos: [L.sx - 36 + 16 * u, 9, 36], look: [L.sx + 12, 8, -2], fov: 44 };
    },
  };
  const out = { pos: new THREE.Vector3(), look: new THREE.Vector3(), fov: 45, shot: null };
  function pose(t) {
    const tt = Math.max(0, Math.min(23.999, t));
    const s = t >= 24 ? { kind: "high", t0: 24, t1: 30, n: 99 } : shots.find((x) => tt >= x.t0 && tt < x.t1) || shots[0];
    const u = ease((t - s.t0) / (s.t1 - s.t0));
    const p = poses[s.kind](u, s);
    out.pos.set(...p.pos);
    out.look.set(...p.look);
    out.fov = p.fov;
    out.shot = s;
    return out;
  }
  return { shots, pose, hero };
}
