/** Settlement points in plain English, the representative airport and the regional scene each one gets. */
export const POINTS = {
  HB_WEST: { name: "West Texas hub", airport: "MAF", lat: 31.94, lon: -102.2 },
  LZ_WEST: { name: "West Texas load zone", airport: "MAF", lat: 31.94, lon: -102.2 },
  HB_PAN: { name: "Panhandle hub", airport: "AMA", lat: 35.22, lon: -101.71 },
  HB_NORTH: { name: "North Texas hub", airport: "DFW", lat: 32.9, lon: -97.04 },
  LZ_NORTH: { name: "North Texas load zone", airport: "DFW", lat: 32.9, lon: -97.04 },
  LZ_RAYBN: { name: "East Texas (Rayburn) load zone", airport: "TYR", lat: 32.35, lon: -95.4 },
  HB_HOUSTON: { name: "Houston hub", airport: "IAH", lat: 29.98, lon: -95.34 },
  LZ_HOUSTON: { name: "Houston load zone", airport: "IAH", lat: 29.98, lon: -95.34 },
  HB_SOUTH: { name: "South Texas hub", airport: "SAT", lat: 29.53, lon: -98.47 },
  LZ_SOUTH: { name: "South Texas load zone", airport: "CRP", lat: 27.77, lon: -97.5 },
  LZ_CPS: { name: "San Antonio load zone", airport: "SAT", lat: 29.53, lon: -98.47 },
  LZ_AEN: { name: "Austin load zone", airport: "AUS", lat: 30.19, lon: -97.67 },
  LZ_LCRA: { name: "Lower Colorado load zone", airport: "AUS", lat: 30.19, lon: -97.67 },
  HB_BUSAVG: { name: "Texas bus-average hub", airport: "AUS", lat: 30.19, lon: -97.67 },
  HB_HUBAVG: { name: "Texas hub average", airport: "AUS", lat: 30.19, lon: -97.67 },
};

/** Per region: ground tones, the clear-day visual range (km) and turbidity, the city the gen-tie runs toward and what
 * stands on the land around the yard. `line` is the gen-tie's bearing (degrees clockwise from north); every other
 * bearing here is relative to it, so the director's shots down the line find the city, turbines and stacks. */
export const REGIONS = {
  west: {
    label: "the Permian Basin, West Texas",
    ground: ["#8d5a3b", "#9b6b47", "#6f6440", "#b28f6c"], gravel: "#a59a8c",
    visKm: 95, turbidity: 2.4, humid: 0.1,
    city: { name: "Midland", bearing: 8, km: 21, towers: 10, spread: 1.1, tallest: 105, lights: 0.55 },
    shrubs: { n: 3400, kind: "mesquite", r: [55, 2600] }, shrubs2: { n: 4200, kind: "creosote", r: [45, 1800] }, trees: null,
    pumpjacks: 18, turbines: { n: 34, km: [5.4, 8.5], bearing: [-58, -12], caprock: { km: 4.8, height: 60, span: [-72, -2] } },
    hills: 0, dunes: true, grain: false, refinery: null, suburbs: 0, line: 78, road: "#cbb995",
  },
  panhandle: {
    label: "the High Plains of the Texas Panhandle",
    ground: ["#9a8456", "#a99668", "#7e7a48", "#b9a57c"], gravel: "#a8a196",
    visKm: 85, turbidity: 2.2, humid: 0.12,
    city: { name: "Amarillo", bearing: 0, km: 24, towers: 8, spread: 1.0, tallest: 95, lights: 0.5 },
    shrubs: { n: 1800, kind: "grass", r: [50, 1500] }, trees: null,
    pumpjacks: 3, turbines: { n: 80, km: [2.4, 10], bearing: [-80, 80], caprock: null },
    hills: 0, grain: { bearing: -38, km: 2.2 }, refinery: null, suburbs: 0, line: 20, road: "#c2b08c",
  },
  north: {
    label: "the North Texas prairie outside Dallas–Fort Worth",
    ground: ["#7b8549", "#8c9257", "#6c7440", "#a39a68"], gravel: "#a3a19b",
    visKm: 42, turbidity: 3.6, humid: 0.35,
    city: { name: "Dallas–Fort Worth", bearing: 0, km: 13, towers: 52, spread: 1.8, tallest: 280, lights: 1 },
    shrubs: { n: 1400, kind: "grass", r: [50, 1200] }, trees: { n: 1700, kind: "oak", r: [300, 4200] },
    pumpjacks: 0, turbines: null, hills: 0.25, grain: false, refinery: null, suburbs: 1, line: 62, road: "#b9b2a3",
  },
  houston: {
    label: "the Gulf Coast plain east of Houston",
    ground: ["#66734a", "#737f50", "#58653f", "#8a8762"], gravel: "#9d9c98",
    visKm: 24, turbidity: 7.5, humid: 0.85,
    city: { name: "Houston", bearing: 0, km: 11, towers: 60, spread: 1.6, tallest: 300, lights: 1 },
    shrubs: { n: 1200, kind: "grass", r: [50, 900] }, trees: { n: 2400, kind: "pine", r: [320, 4200] },
    pumpjacks: 0, turbines: null, hills: 0, grain: false, line: 262, suburbs: 0.3, road: "#b5b0a4",
    refinery: { bearing: -16, km: 3.0 },
  },
  south: {
    label: "the South Texas brush country",
    ground: ["#7f7647", "#8e8356", "#69673d", "#a8946a"], gravel: "#a39d92",
    visKm: 48, turbidity: 4.2, humid: 0.45,
    city: { name: "San Antonio", bearing: 0, km: 16, towers: 28, spread: 1.6, tallest: 190, lights: 0.85, needle: true },
    shrubs: { n: 4200, kind: "mesquite", r: [55, 2600] }, shrubs2: { n: 2400, kind: "creosote", r: [45, 1500] }, trees: { n: 300, kind: "oak", r: [320, 3000] },
    pumpjacks: 4, turbines: null, hills: 0.15, grain: false, refinery: null, suburbs: 0.3, line: 335, road: "#c4b597",
  },
  central: {
    label: "the Texas Hill Country west of Austin",
    ground: ["#6e7a44", "#7f8650", "#5d6a3a", "#a59b78"], gravel: "#a7a39b",
    visKm: 45, turbidity: 3.8, humid: 0.4,
    city: { name: "Austin", bearing: 0, km: 15, towers: 36, spread: 1.4, tallest: 210, lights: 0.95 },
    shrubs: { n: 1600, kind: "juniper", r: [70, 2600] }, trees: { n: 2600, kind: "oak", r: [300, 4500] },
    pumpjacks: 0, turbines: null, hills: 1, grain: false, refinery: null, suburbs: 0.4, line: 95, road: "#c9c1ad",
  },
};

export const placeOf = (point) => POINTS[point] || { name: point, airport: "AUS", lat: 30.19, lon: -97.67 };

const wrap = (b) => ((b % 360) + 360) % 360;

/** A region with its relative bearings turned absolute. */
export function absolute(r) {
  const L = r.line;
  const out = { ...r, city: { ...r.city, bearing: wrap(L + r.city.bearing) } };
  if (r.turbines) {
    out.turbines = { ...r.turbines, bearing: r.turbines.bearing.map((b) => wrap(L + b)) };
    if (r.turbines.caprock) out.turbines.caprock = { ...r.turbines.caprock, span: r.turbines.caprock.span.map((b) => wrap(L + b)) };
  }
  if (r.refinery) out.refinery = { ...r.refinery, bearing: wrap(L + r.refinery.bearing) };
  if (r.grain) out.grain = { ...r.grain, bearing: wrap(L + r.grain.bearing) };
  return out;
}
