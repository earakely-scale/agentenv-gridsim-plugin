/** Times, money and the desk's answers as the page prints them. Minutes count from the first operating day's midnight,
 * Central time; the desk labels a minute "Mon 08-17 06:00". */
import { esc, mw, price, usd } from "gridsim/desk/fmt.js";

export { esc, mw, price, usd };

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
export const AS = { regup: "RegUp", regdn: "RegDn", rrs: "RRS", rrspfr: "RRS-PFR", rrsffr: "RRS-FFR", ecrs: "ECRS", nspin: "Non-Spin" };
export const REASONS = {
  start: "the desk opens", dam_results: "DAM results", adjustment_open: "adjustment period opens", checkpoint: "shift checkpoint",
  dam_morning: "morning postings", notice: "ERCOT notice", nws: "weather alert", outage: "outage", deployment: "reserve deployment",
  reminder: "your reminder", gateway: "wake-up",
};
export const EVENTFUL = new Set(["notice", "nws", "outage", "deployment"]);

const dayOf = (d0, min) => new Date(Date.parse(`${d0}T12:00:00Z`) + Math.floor(min / 1440) * 86400000);
export const hm = (min) => {
  const r = ((Math.floor(min) % 1440) + 1440) % 1440;
  return `${String(Math.floor(r / 60)).padStart(2, "0")}:${String(r % 60).padStart(2, "0")}`;
};
export const day = (d0, min) => {
  const x = dayOf(d0, min);
  return `${DAYS[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`;
};
export const weekday = (d0, min) => DAYS[dayOf(d0, min).getUTCDay()];
export const at = (d0, min) => `${day(d0, min)} ${hm(min)}`;
export const short = (d0, min) => `${weekday(d0, min)} ${hm(min)}`;
export const isoDay = (d0, j) => dayOf(d0, 1440 * j).toISOString().slice(0, 10);
export const dateDay = (d0, iso) => Math.round((Date.parse(`${iso}T12:00:00Z`) - Date.parse(`${d0}T12:00:00Z`)) / 86400000);
export const dateLabel = (iso) => {
  const x = new Date(`${iso}T12:00:00Z`);
  return `${DAYS[x.getUTCDay()]} ${x.getUTCDate()} ${MONTHS[x.getUTCMonth()]}`;
};

/** The minute of a desk label ("Mon 08-17 06:00" or "08-17 06:00"), in the window that starts on d0. */
export function minuteOf(label, d0) {
  const m = /(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})/.exec(label || "");
  if (!m) return null;
  const year = +d0.slice(0, 4);
  const days = Math.round((Date.UTC(year, +m[1] - 1, +m[2], 12) - Date.parse(`${d0}T12:00:00Z`)) / 86400000);
  return days * 1440 + +m[3] * 60 + +m[4];
}

export const pct = (x, n = 1) => (x == null ? "–" : `${(100 * x).toFixed(n).replace("-", "−")}%`);
export const num = (x, n = 1) => (x == null ? "–" : (+x).toFixed(n).replace("-", "−"));

const spark = (vals, cls = "") => {
  const v = vals.filter((x) => x != null);
  if (v.length < 2) return "";
  const lo = Math.min(...v), hi = Math.max(...v), W = 300, H = 34, n = vals.length;
  const y = (p) => (H - 3 - ((p - lo) / (hi - lo || 1)) * (H - 6)).toFixed(1);
  const d = vals.map((p, i) => (p == null ? "" : `${i && vals[i - 1] != null ? "L" : "M"}${((i / (n - 1)) * W).toFixed(1)},${y(p)}`)).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path class="${cls}" d="${d}" vector-effect="non-scaling-stroke"/></svg>`;
};
const band = (lo, mid, hi) => {
  const all = [...lo, ...hi].filter((x) => x != null);
  if (all.length < 2) return "";
  const a = Math.min(...all), b = Math.max(...all), W = 300, H = 34, n = mid.length;
  const x = (i) => ((i / (n - 1)) * W).toFixed(1), y = (p) => (H - 3 - ((p - a) / (b - a || 1)) * (H - 6)).toFixed(1);
  const top = hi.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p)}`).join(""), bot = [...lo].reverse().map((p, k) => `L${x(n - 1 - k)},${y(p)}`).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path class="band" d="${top}${bot}Z"/><path class="dam" d="${mid.map((p, i) => `${i ? "L" : "M"}${x(i)},${y(p)}`).join("")}" vector-effect="non-scaling-stroke"/></svg>`;
};
const stats = (s) => (s && s.min != null ? `min ${price(s.min)} · mean ${price(s.mean)} · max ${price(s.max)}` : "");
const where = (point) => (point === "hub" ? "your hub" : "your node");
const dayName = (r) => (r.date ? dateLabel(r.date) : "");
const kv = (rows) => `<dl class="kv">${rows.filter(([, v]) => v != null && v !== "").map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("")}</dl>`;
const rejects = (r) => {
  const rows = [...(r.rejected || []), ...(r.as_rejected || [])];
  return rows.length ? `<ul>${rows.slice(0, 6).map((x) => `<li class="bad">${esc(x.hours ?? "")} ${esc(x.product ? AS[x.product] || x.product : "")} <b>${esc(x.code)}</b> ${esc(x.text)}</li>`).join("")}</ul>` : "";
};
const warns = (r) => ((r.warnings || []).length ? `<ul>${r.warnings.slice(0, 4).map((x) => `<li>${esc(x.hours ?? "")} <b>${esc(x.code)}</b> ${esc(x.text)}</li>`).join("")}</ul>` : "");

/** A readable rendering of one tool answer; the exact text stays one click away. */
export function render(tool, args, res) {
  if (res == null) return "";
  if (res.error) return `<p class="bad">${esc(res.error)}</p>`;
  const r = res;
  switch (tool) {
    case "get_prices": {
      if (r.mcpc) {
        const rows = Object.entries(r.mcpc).map(([p, v]) => {
          const x = v.filter((y) => y != null);
          return [AS[p] || p, x.length ? `${price(Math.min(...x))}–${price(Math.max(...x))} /MW/h` : "–"];
        });
        return `<b>${r.market === "as_dam" ? "DAM" : "Real-time"} AS clearing prices · ${dayName(r)}</b>${kv(rows)}`;
      }
      if (r.curves) return `<b>AS demand curves · ${dayName(r)} ${esc(r.hour)}</b>${kv(Object.entries(r.curves).map(([p, c]) => [AS[p] || p, `${c.length} points, ${price(c[0][1])} at 0 MW`]))}`;
      const what = r.market === "dam" ? "DAM SPP, hourly" : r.market === "rt" ? `RT SPP, ${r.step || "15m"}` : `SCED LMP, ${r.step || "5m"}`;
      if (!r.values?.length) return `<b>${what} · ${where(r.point)} · ${dayName(r)}</b><p class="muted">${esc(r.note || "nothing posted yet")}</p>`;
      return `<b>${what} · ${where(r.point)} · ${dayName(r)}</b><div class="muted">${esc(r.start || "")}${r.end ? ` → ${esc(r.end)}` : ""} · ${r.values.length} values · ${stats(r.stats)}</div>${spark(r.values, r.market === "dam" ? "dam" : "")}`;
    }
    case "get_forecasts": {
      if (r.kind === "price") return `<b>Desk ${r.market === "rt" ? "real-time" : "DAM"} price forecast · ${dayName(r)}</b><div class="muted">${esc(r.label || r.model || "")}${r.issued_at ? `, issued ${esc(r.issued_at)}` : ""} · P50 ${price(Math.min(...r.p50))}–${price(Math.max(...r.p50))}${r.posted_slots ? ` · ${r.posted_slots} slots already posted` : ""}</div>${band(r.p10, r.p50, r.p90)}`;
      if (r.kind === "as_price") return `<b>Desk AS price forecast · ${dayName(r)}</b><div class="muted">${esc(r.label || "")}</div>${kv(Object.entries(r.p50).map(([p, v]) => [AS[p] || p, `P50 ${price(Math.min(...v))}–${price(Math.max(...v))} /MW/h`]))}`;
      if (r.kind === "weather") return `<b>NWS alerts in force</b>${r.alerts.length ? `<ul>${r.alerts.map((a) => `<li><b>${esc(a.event)}</b> ${esc(a.severity || "")}, issued ${esc(a.issued)}${a.expires ? `, until ${esc(a.expires)}` : ""}</li>`).join("")}</ul>` : '<p class="muted">none</p>'}`;
      if (r.values) {
        const v = r.values.filter((x) => x != null), name = { load: "ERCOT load", wind: "ERCOT wind", solar: "ERCOT solar", net_load: "Net load", outages: "Outage capacity", pv: "PV (modelled)" }[r.kind] || r.kind;
        return `<b>${name} forecast · ${dayName(r)}</b><div class="muted">${r.issued_at ? `issued ${esc(r.issued_at)} · ` : ""}${v.length ? `${Math.round(Math.min(...v)).toLocaleString("en-US")}–${Math.round(Math.max(...v)).toLocaleString("en-US")} MW` : "–"}</div>${spark(r.values)}`;
      }
      return "";
    }
    case "get_grid_conditions": {
      const f = (o, u = "MW") => (o ? `${Math.round(o.last).toLocaleString("en-US")} ${u} <span class="muted">(${Math.round(o.min).toLocaleString("en-US")}–${Math.round(o.max).toLocaleString("en-US")})</span>` : null);
      return `<b>Grid conditions${r.window ? ` · ${esc(r.window)}` : ""}</b>${kv([["Reserves (PRC)", f(r.prc_mw) && `${f(r.prc_mw)}${r.prc_mw.kind ? ` <span class="muted">${esc(r.prc_mw.kind)}</span>` : ""}`], ["System lambda", r.lambda ? price(r.lambda.last) : null], ["Load", f(r.load_mw)], ["Wind", f(r.wind_mw)], ["Solar", f(r.solar_mw)], ["EEA", r.eea_level ? esc(r.eea_level) : "none"]])}${(r.notices_recent || []).length ? `<ul>${r.notices_recent.map((n) => `<li><small>${esc(n.t)}</small> ${esc(n.title || n.level)}</li>`).join("")}</ul>` : ""}`;
    }
    case "get_asset_status": {
      const bp = (r.last_base_points || []).map((x) => x.bp_mw);
      return `<b>Battery: ${num(r.soc_mwh)} of ${num(r.nameplate?.e_max_mwh)} MWh, ${esc(r.status)}</b>${kv([["Limits now", `${num(r.lsl_mw)} … ${num(r.hsl_mw)} MW`], ["Metered", `${num(r.metered_mw)} MW`], ["Last base points", bp.length ? bp.map((x) => num(x)).join(", ") : "–"], ["Curve in force", esc(r.curve_in_force)], ["Cycles today", num(r.cycles_today, 2)], ["Outage", r.outage ? `${esc(r.outage.kind)} until ${esc(r.outage.until)}` : "none"], ["Reserves awarded", r.as_awards_mw && Object.keys(r.as_awards_mw).length ? Object.entries(r.as_awards_mw).map(([k, v]) => `${esc(k)} ${num(v)} MW`).join(", ") : null]])}`;
    }
    case "get_position": {
      const d = r.dam || {}, rt = r.rt || {}, ss = r.shadow_statement;
      return `<b>Position · ${dayName(r)}</b>${kv([["DAM", d.status ? `${esc(d.status)}, curves for ${d.curves_submitted_hours} hours` : `sold ${num(d.sold_mwh)} MWh, bought ${num(d.bought_mwh)} MWh, value ${usd(d.value_usd || 0)}`], ["Real time", rt.intervals_run ? `discharged ${num(rt.discharged_mwh)} MWh, charged ${num(rt.charged_mwh)} MWh` : "not started"], ["Curves in force", (r.curves || []).map(esc).join(", ")], ["Reserves", r.as?.dam_awards_mwh && Object.keys(r.as.dam_awards_mwh).length ? Object.entries(r.as.dam_awards_mwh).map(([k, v]) => `${esc(k)} ${num(v)} MWh`).join(", ") : null], ["Shadow statement", ss ? usd(ss.total) : null]])}`;
    }
    case "optimize": {
      const p = r.projected || {}, sc = p.pnl_by_scenario || {};
      const hrs = (r.schedule?.hourly_mw || []).map((x) => x.split(":")).map(([h, v]) => [h, +v]);
      const ch = hrs.filter(([, v]) => v < 0).length, dis = hrs.filter(([, v]) => v > 0).length;
      return `<b>Proposal: expected ${usd(p.expected ?? 0)}</b><div class="muted">${Object.entries(sc).map(([k, v]) => `${k.toUpperCase()} ${usd(v)}`).join(" · ")}</div>${kv([["DAM curves", groups(r.dam_curves)], ["RT curves", groups(r.rt_curves)], ["COP", (r.cop || []).map((c) => `${c.day} ${esc(c.hours)}`).join(", ") || "none"], ["Reserves", (r.dam_as_offers || []).length ? [...new Set(r.dam_as_offers.map((a) => AS[a.product] || a.product))].join(", ") : "none"], ["Next 24 h", hrs.length ? `charge ${ch} h, discharge ${dis} h` : "idle"]])}<p class="muted">${esc(r.basis || "")}</p>`;
    }
    case "submit_dam_offers":
    case "submit_rt_offers":
    case "update_cop":
    case "check_submission": {
      const ok = r.accepted_hours && r.accepted_hours !== "none";
      const as = r.as_accepted && Object.keys(r.as_accepted).length ? Object.entries(r.as_accepted).map(([k, v]) => `${esc(k)} ${esc(v)}`).join(", ") : "";
      const head = tool === "check_submission" ? (r.ok ? '<b class="ok">Valid: nothing would be refused</b>' : "<b>Some of it would be refused</b>") : ok ? `<b class="ok">Accepted ${esc(r.accepted_hours)}</b>` : "<b>Nothing accepted</b>";
      return `${head}${r.date ? `<div class="muted">${dateLabel(r.date)}${r.effective ? ` · ${esc(r.effective)}` : ""}</div>` : ""}${as ? `<div class="muted">Reserves: ${as}</div>` : ""}${rejects(r)}${warns(r)}${(r.would_clear_at_desk_p50 || []).length ? `<div class="muted">Would clear at the desk P50: ${r.would_clear_at_desk_p50.slice(0, 8).map(esc).join(", ")}${r.would_clear_at_desk_p50.length > 8 ? "…" : ""}</div>` : ""}`;
    }
    case "set_reminder":
      return `<b class="ok">Reminder set for ${esc(r.at)}</b><div class="muted">${r.pending} pending</div>`;
    default:
      return "";
  }
}

const groups = (gs) => {
  if (!gs?.length) return "none";
  const by = {};
  for (const g of gs) (by[g.day] ||= []).push(g.hours);
  return Object.entries(by).map(([d, hs]) => `${d}: ${hs.length} block${hs.length > 1 ? "s" : ""}`).join(", ");
};

/** The arguments as a short line for the log. */
export function argLine(args) {
  const s = JSON.stringify(args || {});
  return s === "{}" ? "" : s.length > 180 ? `${s.slice(0, 177)}…` : s;
}
