/** Sun and moon positions (low-precision almanac formulas) for a UTC instant at a latitude and longitude. */
const RAD = Math.PI / 180;
const E = RAD * 23.4397;

const days = (ms) => ms / 86400000 - 10957.5;
const ra = (l, b) => Math.atan2(Math.sin(l) * Math.cos(E) - Math.tan(b) * Math.sin(E), Math.cos(l));
const dec = (l, b) => Math.asin(Math.sin(b) * Math.cos(E) + Math.cos(b) * Math.sin(E) * Math.sin(l));
const sidereal = (d, lw) => RAD * (280.16 + 360.9856235 * d) - lw;

function horizontal(H, phi, de) {
  const el = Math.asin(Math.sin(phi) * Math.sin(de) + Math.cos(phi) * Math.cos(de) * Math.cos(H));
  const az = Math.atan2(Math.sin(H), Math.cos(H) * Math.sin(phi) - Math.tan(de) * Math.cos(phi));
  return { el, az: az + Math.PI };
}

function refract(el) {
  const h = Math.max(el, 0);
  return el + 0.0002967 / Math.tan(h + 0.00312536 / (h + 0.08901179));
}

function sunCoords(d) {
  const M = RAD * (357.5291 + 0.98560028 * d);
  const C = RAD * (1.9148 * Math.sin(M) + 0.02 * Math.sin(2 * M) + 0.0003 * Math.sin(3 * M));
  const L = M + C + RAD * 102.9372 + Math.PI;
  return { ra: ra(L, 0), dec: dec(L, 0), L };
}

function moonCoords(d) {
  const L = RAD * (218.316 + 13.176396 * d);
  const M = RAD * (134.963 + 13.064993 * d);
  const F = RAD * (93.272 + 13.22935 * d);
  const l = L + RAD * 6.289 * Math.sin(M);
  const b = RAD * 5.128 * Math.sin(F);
  return { ra: ra(l, b), dec: dec(l, b), dist: 385001 - 20905 * Math.cos(M) };
}

/** {el, az} in degrees, azimuth clockwise from north. */
export function sunAt(ms, lat, lon) {
  const d = days(ms), lw = -lon * RAD, phi = lat * RAD;
  const c = sunCoords(d);
  const p = horizontal(sidereal(d, lw) - c.ra, phi, c.dec);
  return { el: refract(p.el) / RAD, az: (p.az / RAD + 360) % 360 };
}

/** {el, az, lit}: lit is the illuminated fraction of the disc, waxing true before full. */
export function moonAt(ms, lat, lon) {
  const d = days(ms), lw = -lon * RAD, phi = lat * RAD;
  const m = moonCoords(d), s = sunCoords(d);
  const p = horizontal(sidereal(d, lw) - m.ra, phi, m.dec);
  const sdist = 149598000;
  const phiA = Math.acos(Math.sin(s.dec) * Math.sin(m.dec) + Math.cos(s.dec) * Math.cos(m.dec) * Math.cos(s.ra - m.ra));
  const inc = Math.atan2(sdist * Math.sin(phiA), m.dist - sdist * Math.cos(phiA));
  const angle = Math.atan2(Math.cos(s.dec) * Math.sin(s.ra - m.ra), Math.sin(s.dec) * Math.cos(m.dec) - Math.cos(s.dec) * Math.sin(m.dec) * Math.cos(s.ra - m.ra));
  return { el: refract(p.el) / RAD, az: (p.az / RAD + 360) % 360, lit: (1 + Math.cos(inc)) / 2, waxing: angle < 0 };
}

/** Minutes east of UTC for an IANA zone on a date (Central: -300 in summer, -360 in winter). */
export function tzOffsetMinutes(date, tz = "America/Chicago") {
  const part = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "shortOffset" })
    .formatToParts(new Date(`${date}T12:00:00Z`)).find((p) => p.type === "timeZoneName")?.value || "GMT";
  const m = part.match(/GMT([+-])(\d+)(?::(\d+))?/);
  return m ? (m[1] === "-" ? -1 : 1) * (+m[2] * 60 + +(m[3] || 0)) : 0;
}

/** World direction (x east, y up, z south) for an elevation and azimuth in degrees. */
export function dirOf(el, az, out) {
  const e = el * RAD, a = az * RAD;
  return out.set(Math.sin(a) * Math.cos(e), Math.sin(e), -Math.cos(a) * Math.cos(e));
}
