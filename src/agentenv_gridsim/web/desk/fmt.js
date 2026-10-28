/** Numbers, money, prices and times as the desk pages print them. Times are minutes from the first operating day's
 * midnight, Central Prevailing Time. */
const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
export const minus = (s) => String(s).replace(/-/g, "−");

export function usd(x, { sign = false, compact = false } = {}) {
  const a = Math.abs(x), w = Math.round(a);
  const body = compact && a >= 1e6 ? `${(a / 1e6).toFixed(a >= 1e7 ? 1 : 2)}M` : compact && a >= 1e4 ? `${(a / 1e3).toFixed(a >= 1e5 ? 0 : 1)}k` : w.toLocaleString("en-US");
  return `${w === 0 && !compact ? "" : x < 0 ? "−" : sign ? "+" : ""}$${body}`;
}

export function price(p) {
  if (p == null || Number.isNaN(p)) return "–";
  const a = Math.abs(p), s = p < 0 ? "−" : "";
  return a >= 1000 ? `${s}$${Math.round(a).toLocaleString("en-US")}` : a >= 100 ? `${s}$${a.toFixed(0)}` : `${s}$${a.toFixed(2)}`;
}

export const mw = (x) => `${Math.abs(x) >= 9.95 ? Math.round(Math.abs(x)) : Math.abs(x).toFixed(1)} MW`;
export const pct = (x) => `${Math.round(100 * x)}%`;
export const num = (x, n = 3) => minus((Math.round(x * 10 ** n) / 10 ** n).toFixed(n));

/** The calendar date of a minute (its operating day), as a UTC Date at noon. */
export function dateAt(d0, min) {
  return new Date(Date.parse(`${d0}T12:00:00Z`) + Math.floor(min / 1440) * 86400000);
}

export function clock(min) {
  const r = ((Math.floor(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(r / 60)).padStart(2, "0")}:${String(r % 60).padStart(2, "0")}`;
}

export const dayShort = (d0, min) => {
  const x = dateAt(d0, min);
  return `${DAYS[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`;
};

export const weekday = (d0, min) => DAYS[dateAt(d0, min).getUTCDay()];

const DAYS_LONG = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
export const dayLong = (d0, min) => {
  const x = dateAt(d0, min);
  return `${DAYS_LONG[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS_LONG[x.getUTCMonth()]}`;
};

/** "8 to 10 May 2026", "25 January 2026". */
export function span(dates) {
  const a = new Date(`${dates[0]}T12:00:00Z`), b = new Date(`${dates.at(-1)}T12:00:00Z`);
  const tail = `${MONTHS_LONG[b.getUTCMonth()]} ${b.getUTCFullYear()}`;
  if (dates.length === 1) return `${a.getUTCDate()} ${tail}`;
  return a.getUTCMonth() === b.getUTCMonth() ? `${a.getUTCDate()} to ${b.getUTCDate()} ${tail}` : `${a.getUTCDate()} ${MONTHS_LONG[a.getUTCMonth()]} to ${b.getUTCDate()} ${tail}`;
}

export const shortDate = (iso) => {
  const x = new Date(`${iso}T12:00:00Z`);
  return `${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`;
};

/** "25 Jan", "23 to 25 Jan", "30 Jan to 1 Feb". */
export const shortSpan = (dates) => (dates.length < 2 ? shortDate(dates[0]) : dates[0].slice(5, 7) === dates.at(-1).slice(5, 7) ? `${+dates[0].slice(8)} to ${shortDate(dates.at(-1))}` : `${shortDate(dates[0])} to ${shortDate(dates.at(-1))}`);

/** "Fri 13:30", or "13:30" on the same operating day as `ref`. */
export function when(d0, min, ref = null) {
  return ref != null && Math.floor(ref / 1440) === Math.floor(min / 1440) ? clock(min) : `${weekday(d0, min)} ${clock(min)}`;
}

export const REASONS = {
  start: "Desk opens", dam_morning: "DAM morning", dam_results: "DAM results", adjustment_open: "Adjustment period opens",
  checkpoint: "Shift checkpoint", reminder: "Its reminder", notice: "ERCOT notice", nws: "NWS alert", outage: "Outage",
  deployment: "Reserve deployment",
};
export const EVENTFUL = new Set(["notice", "nws", "outage", "deployment"]);
export const AS_NAMES = { regup: "RegUp", regdn: "RegDn", rrspfr: "RRS-PFR", rrsffr: "RRS-FFR", rrs: "RRS", ecrs: "ECRS", nspin: "Non-Spin" };
