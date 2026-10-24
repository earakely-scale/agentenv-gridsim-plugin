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

/** Per region: ground tones, the clear-day visual range (km) and turbidity, the city the line runs toward and what
 * stands on the land around the yard. Bearings are degrees clockwise from north. */
export const REGIONS = {
  west: {
    label: "the Permian Basin, West Texas",
    ground: ["#8d5a3b", "#9b6b47", "#6f6440", "#b28f6c"], gravel: "#a59a8c",
    visKm: 95, turbidity: 2.4, humid: 0.1,
    city: { name: "Midland", bearing: 78, km: 22, towers: 9, spread: 1.1, tallest: 105, lights: 0.55 },
    shrubs: { n: 2600, kind: "mesquite", r: [60, 2400] }, trees: null,
    pumpjacks: 16, turbines: { n: 34, km: [8.5, 13], bearing: [300, 20], caprock: { km: 7.2, height: 70, span: [270, 40] } },
    hills: 0, grain: false, refinery: null, suburbs: 0, line: 78,
  },
  panhandle: {
    label: "the High Plains of the Texas Panhandle",
    ground: ["#9a8456", "#a99668", "#7e7a48", "#b9a57c"], gravel: "#a8a196",
    visKm: 85, turbidity: 2.2, humid: 0.12,
    city: { name: "Amarillo", bearing: 200, km: 24, towers: 7, spread: 1.0, tallest: 95, lights: 0.5 },
    shrubs: { n: 700, kind: "grass", r: [60, 1500] }, trees: null,
    pumpjacks: 0, turbines: { n: 70, km: [2.6, 9], bearing: [250, 110], caprock: null },
    hills: 0, grain: true, refinery: null, suburbs: 0, line: 200,
  },
  north: {
    label: "the North Texas prairie outside Dallas–Fort Worth",
    ground: ["#7b8549", "#8c9257", "#6c7440", "#a39a68"], gravel: "#a3a19b",
    visKm: 42, turbidity: 3.6, humid: 0.35,
    city: { name: "Dallas–Fort Worth", bearing: 62, km: 17, towers: 46, spread: 2.2, tallest: 280, lights: 1 },
    shrubs: { n: 500, kind: "grass", r: [60, 1200] }, trees: { n: 1500, kind: "oak", r: [140, 4200] },
    pumpjacks: 0, turbines: null, hills: 0.25, grain: false, refinery: null, suburbs: 1, line: 62,
  },
  houston: {
    label: "the Gulf Coast plain east of Houston",
    ground: ["#5f7a3c", "#6e8746", "#4f6833", "#8a8a5a"], gravel: "#9d9c98",
    visKm: 24, turbidity: 7.5, humid: 0.85,
    city: { name: "Houston", bearing: 262, km: 15, towers: 52, spread: 2.0, tallest: 300, lights: 1 },
    shrubs: { n: 400, kind: "grass", r: [60, 900] }, trees: { n: 2400, kind: "pine", r: [150, 4200] },
    pumpjacks: 0, turbines: null, hills: 0, grain: false, line: 262, suburbs: 0.3,
    refinery: { bearing: 118, km: 3.4 },
  },
  south: {
    label: "the South Texas brush country",
    ground: ["#7f7647", "#8e8356", "#69673d", "#a8946a"], gravel: "#a39d92",
    visKm: 48, turbidity: 4.2, humid: 0.45,
    city: { name: "San Antonio", bearing: 335, km: 17, towers: 26, spread: 1.6, tallest: 190, lights: 0.85, needle: true },
    shrubs: { n: 3600, kind: "mesquite", r: [60, 2600] }, trees: { n: 300, kind: "oak", r: [300, 3000] },
    pumpjacks: 4, turbines: null, hills: 0.15, grain: false, refinery: null, suburbs: 0.3, line: 335,
  },
  central: {
    label: "the Texas Hill Country west of Austin",
    ground: ["#6e7a44", "#7f8650", "#5d6a3a", "#a59b78"], gravel: "#a7a39b",
    visKm: 45, turbidity: 3.8, humid: 0.4,
    city: { name: "Austin", bearing: 95, km: 15, towers: 34, spread: 1.4, tallest: 210, lights: 0.95 },
    shrubs: { n: 900, kind: "juniper", r: [80, 2600] }, trees: { n: 2600, kind: "oak", r: [120, 4500] },
    pumpjacks: 0, turbines: null, hills: 1, grain: false, refinery: null, suburbs: 0.4, line: 95,
  },
};

export const placeOf = (point) => POINTS[point] || { name: point, airport: "AUS", lat: 30.19, lon: -97.67 };
