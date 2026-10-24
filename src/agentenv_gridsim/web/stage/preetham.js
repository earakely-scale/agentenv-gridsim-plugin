/** The Sky shader's colour for a direction, on the CPU: the fog and the light take the sky's own horizon. */
const TR = [5.804542996261093e-6, 1.3562911419845635e-5, 3.0265902468824876e-5];
const MIE = [1.8399918514433978e14, 2.7798023919660528e14, 4.0790479543861094e14];
const CUTOFF = 1.6110731556870734, STEEP = 1.5, EE = 1000;

export function skyColor(d, sun, { turbidity, rayleigh, mieCoefficient, mieDirectionalG }) {
  const zc = Math.max(-1, Math.min(1, sun.y));
  const sunE = EE * Math.max(0, 1 - Math.exp(-((CUTOFF - Math.acos(zc)) / STEEP)));
  const sunfade = 1 - Math.min(1, Math.max(0, 1 - Math.exp(sun.y / 450000)));
  const rc = rayleigh - (1 - sunfade);
  const bR = TR.map((x) => x * rc);
  const c = 0.2 * turbidity * 10e-18;
  const bM = MIE.map((x) => 0.434 * c * x * mieCoefficient);
  const zen = Math.acos(Math.max(0, d.y));
  const inv = 1 / (Math.cos(zen) + 0.15 * Math.pow(93.885 - (zen * 180) / Math.PI, -1.253));
  const sR = 8.4e3 * inv, sM = 1.25e3 * inv;
  const cosT = d.x * sun.x + d.y * sun.y + d.z * sun.z;
  const rPhase = 0.05968310365946075 * (1 + Math.pow(cosT * 0.5 + 0.5, 2));
  const g = mieDirectionalG, g2 = g * g;
  const mPhase = 0.07957747154594767 * ((1 - g2) / Math.pow(1 - 2 * g * cosT + g2, 1.5));
  const k = Math.min(1, Math.max(0, Math.pow(1 - sun.y, 5)));
  return [0, 1, 2].map((i) => {
    const Fex = Math.exp(-(bR[i] * sR + bM[i] * sM));
    const ratio = (bR[i] * rPhase + bM[i] * mPhase) / (bR[i] + bM[i]);
    let Lin = Math.pow(sunE * ratio * (1 - Fex), 1.5);
    Lin *= 1 + (Math.pow(sunE * ratio * Fex, 0.5) - 1) * k;
    const tex = (Lin + 0.1 * Fex) * 0.04 + [0, 0.0003, 0.00075][i];
    return Math.pow(tex, 1 / (1.2 + 1.2 * sunfade));
  });
}

/** The mean horizon colour (a little above it) over all azimuths, and toward and away from the sun. */
export function horizonColors(sun, params, h = 0.035) {
  const acc = [0, 0, 0];
  const n = 12;
  for (let i = 0; i < n; i++) {
    const a = (i / n) * Math.PI * 2;
    const c = Math.sqrt(1 - h * h);
    const col = skyColor({ x: Math.cos(a) * c, y: h, z: Math.sin(a) * c }, sun, params);
    for (let k = 0; k < 3; k++) acc[k] += col[k] / n;
  }
  const zen = skyColor({ x: 0, y: 1, z: 0 }, sun, params);
  return { mean: acc, zenith: zen };
}
