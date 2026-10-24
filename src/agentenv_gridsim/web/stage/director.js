import * as THREE from "three";

const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : u * u * (3 - 2 * u));
const lerp = (a, b, u) => a + (b - a) * u;
const PRIORITY = { violation: 6, neg: 5, ramp: 4, push: 3, establish: 1, sub: 1, high: 1, line: 2, city: 1 };

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
  if ((d.live ? d.hours.map((x) => x.price) : d.prices)[d.peakH] > d.median * 1.6) claim(d.peakH - 1.25, d.peakH + 1.5, "ramp");
  for (const w of d.watches || []) if (w.index > 0 && w.notices.length) claim(w.t - 0.05, w.t + 1.2, "line");
  const negH = d.hours.find((x) => x.neg && x.action < 0)?.h ?? d.firstNeg;
  if (negH >= 0) claim(negH - 0.1, negH + 1.9, "neg");
  if (d.trunc != null) claim(d.trunc - 0.1, d.trunc + 2.2, "violation");
  const fill = d.region.city.lights >= 0.85 ? ["sub", "establish", "city", "line", "high"] : ["sub", "establish", "line", "high"];
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

  const front = [...L.enc].filter((e) => e.z === Math.max(...L.enc.map((x) => x.z)));
  front.sort((a, b) => b.x - a.x);
  const hero = front[0];
  const x0 = L.cx - L.W / 2, x1 = L.cx + L.W / 2, zf = Math.max(...L.enc.map((e) => e.z)) + 1.3;
  const xa = x0 - 2, xb = L.sx + 14, mid = (xa + xb) / 2, diag = Math.hypot(xb - xa, L.D * 1.3);
  /** A camera at `look` plus the direction (dx, dy, dz) turned by `turn` about the vertical, k yard diagonals away:
   * the yard fills about two thirds of the frame width whatever its size. */
  const orbit = (look, [dx, dy, dz], k, turn = 0) => {
    const n = Math.hypot(dx, dy, dz), c = Math.cos(turn), si = Math.sin(turn);
    const rx = dx * c - dz * si, rz = dx * si + dz * c;
    return [look[0] + (rx / n) * k * diag, look[1] + (dy / n) * k * diag, look[2] + (rz / n) * k * diag];
  };
  const poses = {
    establish(u, s) {
      if (s.n % 2) {
        const look = [mid - 0.08 * diag, 0, 0.25 * L.D];
        return { pos: orbit(look, [-134, 46, -87], 1.04 * (1 - 0.07 * u), 0.1 - 0.16 * u), look, fov: 36 };
      }
      const look = [mid - 0.06 * diag, 0, -0.25 * L.D];
      return { pos: orbit(look, [-140, 45, 94], 1.08 * (1 - 0.07 * u), -0.1 + 0.16 * u), look, fov: 36 };
    },
    high(u, s) {
      const a = 2.3 + (s.n % 3) * 0.5 + 0.25 * u;
      return { pos: [L.cx + Math.cos(a) * 190, 95, Math.sin(a) * -190], look: [L.cx + 40, 0, 0], fov: 46 };
    },
    push(u) {
      return { pos: [hero.x + 30 - 12 * u, 6 - 1.4 * u, hero.z + 12 - 2 * u], look: [hero.x - 22, 1.6, hero.z - 2], fov: 44 };
    },
    neg(u) {
      return { pos: [x1 + 9 - 3 * u, 4.2, zf + 6.5], look: [L.cx - L.W * 0.35, 1.4, zf - 3.5], fov: 46 };
    },
    violation(u) {
      return { pos: [x1 + 12 - 4 * u, 5.5, zf + 9], look: [L.cx - L.W * 0.3, 1.2, zf - 5], fov: 44 };
    },
    ramp(u) {
      return { pos: [x0 - 100 + 25 * u, 23 - 3 * u, zf + 50], look: [L.cx + L.W * 0.75, -3, -6], fov: 46 };
    },
    line(u) {
      return { pos: [L.sx + 26 + 30 * u, 7, 34], look: [L.sx + 1600, 22, -40], fov: 42 };
    },
    city(u) {
      const b = ((d.region.city.bearing - d.region.line + 540) % 360) - 180;
      const a = (b * Math.PI) / 180;
      return { pos: [L.sx + 40 + 10 * u, 32, 70], look: [L.sx + 40 + Math.cos(a) * 4000, 60, 70 + Math.sin(a) * 4000], fov: 13 };
    },
    sub(u) {
      return { pos: [L.sx - 34 + 12 * u, 11, 36], look: [L.sx + 4, 5, -2], fov: 48 };
    },
  };
  const out = { pos: new THREE.Vector3(), look: new THREE.Vector3(), fov: 45, shot: null };
  function pose(t, force = null, reduced = false, drift = null) {
    const tt = Math.max(0, Math.min(23.999, t));
    let s = t >= 24 ? { kind: "high", t0: 24, t1: 30, n: 99 } : shots.find((x) => tt >= x.t0 && tt < x.t1) || shots[0];
    if (force && poses[force]) s = { kind: force, t0: Math.floor(tt), t1: Math.floor(tt) + 2, n: 0 };
    const u = reduced ? 0.5 : drift ?? ease((t - s.t0) / (s.t1 - s.t0));
    const p = poses[s.kind](u, s);
    out.pos.set(...p.pos);
    out.look.set(...p.look);
    out.fov = p.fov;
    out.shot = s;
    return out;
  }
  /** Site-local (x, z, radius) the cameras pass through, for keeping vegetation out of shot. */
  const at = (kind, u, n) => poses[kind](u, { n }).pos;
  const spots = [at("establish", 0, 0), at("establish", 1, 0), at("establish", 0, 1), at("establish", 1, 1)].map(([x, , z]) => [x, z, 40])
    .concat([[x0 - 85, zf + 46, 45], [L.sx + 40, 34, 40], [L.sx - 30, 36, 30], [L.cx, 0, 210], [L.sx + 50, 70, 40]]);
  return { shots, pose, hero, spots };
}
