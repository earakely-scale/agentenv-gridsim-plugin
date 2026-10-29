/** The live board: reads live/board.json from the dataset (written by scripts/live/live.py) and draws the cumulative
 * P&L, the daily table and the sealed-then-graded timeline. */
const DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv";
const SOURCE = new URLSearchParams(location.search).get("board") || `${DATASET}/resolve/main/live/board.json`;
const REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin";

const STYLE = {
  "gpt-6.1-sol": { color: "var(--series-1)", w: 2.5 },
  "gpt-6-luna": { color: "var(--series-2)", w: 2.5 },
  "qwen3-4b-gridsim-run4": { color: "var(--series-3)", w: 2.5 },
  ridge_dp: { color: "var(--rule)", w: 1.6 },
  persistence_dp: { color: "var(--rule)", w: 1.6, dash: "6 4" },
  greedy_d1: { color: "var(--rule)", w: 1.6, dash: "1.5 3.5" },
  blind_anchor: { color: "var(--ref)", w: 1.6, dash: "6 4" },
  hindsight_dp: { color: "var(--ref)", w: 1.6, dash: "1.5 3.5" },
};
const ORDER = Object.keys(STYLE);
const REFS = new Set(["blind_anchor", "hindsight_dp"]);
const CT = "America/Chicago";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const usd = (v, sign = false) =>
  v == null ? "–" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const fix = (v, n = 3) => (v == null ? "–" : v.toFixed(n));
const fmt = (iso, opts) => new Intl.DateTimeFormat("en-US", { timeZone: CT, ...opts }).format(new Date(iso));
const when = (iso) => (iso ? `${fmt(iso, { weekday: "short", month: "short", day: "numeric" })}, ${fmt(iso, { hour: "2-digit", minute: "2-digit", hour12: false })} CT` : "–");
const dayName = (d) => new Intl.DateTimeFormat("en-US", { timeZone: "UTC", weekday: "short", month: "short", day: "numeric" }).format(new Date(`${d}T12:00:00Z`));
const lead = (a, b) => {
  const m = Math.round((new Date(b) - new Date(a)) / 60000);
  const closed = new Date(b) < new Date() ? "closed" : "closes";
  return m > 0 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, "0")} m before the DAM ${closed}` : "after the DAM closed";
};
const keyStyle = (n) => {
  const s = STYLE[n];
  return `border-top-color:${s.color};border-top-style:${s.dash ? (s.dash.startsWith("1.5") ? "dotted" : "dashed") : "solid"}`;
};

async function main() {
  let b;
  try {
    const r = await fetch(`${SOURCE}${SOURCE.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
    if (r.status === 404) b = { graded_days: [], agents: {}, timeline: [], updated_utc: null };
    else if (!r.ok) throw new Error(`HTTP ${r.status}`);
    else b = await r.json();
  } catch (e) {
    $("status").textContent = `The board could not be loaded (${e.message}).`;
    return;
  }
  status(b);
  chart(b);
  standings(b);
  daily(b);
  timeline(b);
  $("links").innerHTML = [
    [`${DATASET}/tree/main/live`, "Sealed and graded files"],
    [`${DATASET}/commits/main`, "Commit history"],
    [`${REPO}/blob/main/docs/prereg/v1-live-board.md`, "Pre-registration"],
    [`${REPO}/blob/main/scripts/live/live.py`, "The job"],
  ].map(([h, t]) => `<a href="${h}" target="_blank" rel="noopener">${t}</a>`).join("");
}

function status(b) {
  const tl = b.timeline || [];
  const sealed = tl.filter((t) => t.seal_commit);
  const pending = sealed.filter((t) => !t.graded_utc);
  const bits = [`<span><b>${b.graded_days.length}</b> graded day${b.graded_days.length === 1 ? "" : "s"}</span>`,
    `<span><b>${sealed.length}</b> sealed</span>`];
  if (pending.length) {
    const p = pending[0];
    bits.unshift(`<span class="next"><i class="pulse"></i><span>Sealed for <b>${dayName(p.delivery_day)}</b>, awaiting ERCOT's prices (posted about 13:30 CT the day before)</span></span>`);
  }
  if (b.api_spend_usd != null) bits.push(`<span>API spend <b>${usd(b.api_spend_usd)}</b> of $25</span>`);
  if (b.updated_utc) bits.push(`<span>Updated ${when(b.updated_utc)}</span>`);
  else bits.unshift(`<span>Nothing is published yet: the first schedules are sealed for <b>${dayName("2026-10-29")}</b>.</span>`);
  $("status").innerHTML = bits.join("");
}

function series(b) {
  return ORDER.filter((n) => b.agents[n] && Object.keys(b.agents[n].cum_usd_per_mw || {}).length).map((n) => ({
    n, label: b.agents[n].label, ref: REFS.has(n),
    pts: b.graded_days.filter((d) => d in b.agents[n].cum_usd_per_mw).map((d) => ({ d, v: b.agents[n].cum_usd_per_mw[d], day: b.agents[n].days[d] })),
  }));
}

function chart(b) {
  const host = $("chart");
  const ss = series(b);
  $("legend").innerHTML = ORDER.filter((n) => b.agents[n]).map((n) => `<span><i class="key" style="${keyStyle(n)}"></i>${esc(b.agents[n].label)}</span>`).join("");
  if (!b.graded_days.length) {
    host.innerHTML = `<div class="empty">No day is graded yet. The first sealed day is graded when ERCOT posts its prices; the chart starts then.</div>`;
    return;
  }
  const days = b.graded_days;
  const W = 1000, H = 360, L = 58, R = 170, T = 14, B = 34;
  const vals = ss.flatMap((s) => s.pts.map((p) => p.v)).concat([0]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const step = nice((hi - lo) / 5 || 10);
  lo = Math.floor(lo / step) * step;
  hi = Math.ceil(hi / step) * step;
  const x = (i) => (days.length === 1 ? L + (W - L - R) / 2 : L + (i * (W - L - R)) / (days.length - 1));
  const y = (v) => T + ((hi - v) * (H - T - B)) / (hi - lo || 1);
  let g = `<g class="grid">`;
  for (let v = lo; v <= hi + 1e-9; v += step) g += `<line x1="${L}" x2="${W - R + 8}" y1="${y(v)}" y2="${y(v)}"/>`;
  g += `</g><g class="axis">`;
  for (let v = lo; v <= hi + 1e-9; v += step) g += `<text x="${L - 8}" y="${y(v) + 4}" text-anchor="end">${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US")}</text>`;
  days.forEach((d, i) => { g += `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">${dayName(d)}</text>`; });
  g += `</g>`;
  if (lo < 0) g += `<line class="zero" x1="${L}" x2="${W - R + 8}" y1="${y(0)}" y2="${y(0)}"/>`;
  let lines = "";
  for (const s of [...ss].sort((a, c) => (a.ref === c.ref ? 0 : a.ref ? -1 : 1))) {
    const st = STYLE[s.n];
    const pts = s.pts.map((p) => [x(days.indexOf(p.d)), y(p.v)]);
    if (pts.length > 1) lines += `<polyline points="${pts.map((p) => p.join(",")).join(" ")}" fill="none" stroke="${st.color}" stroke-width="${st.w}" stroke-linejoin="round" stroke-linecap="round"${st.dash ? ` stroke-dasharray="${st.dash}"` : ""}/>`;
    if (!s.ref) for (const [px, py] of pts) lines += `<circle cx="${px}" cy="${py}" r="4.5" fill="${st.color}" stroke="var(--surface-1)" stroke-width="2"/>`;
  }
  const ends = ss.map((s) => ({ s, v: s.pts[s.pts.length - 1].v })).sort((a, c) => c.v - a.v);
  let lastY = -Infinity;
  let labels = "";
  for (const e of ends) {
    const yy = Math.max(y(e.v) + 4, lastY + 15);
    lastY = yy;
    labels += `<text class="end" x="${W - R + 16}" y="${yy}">${esc(short(e.s.label))} ${usd(e.v)}</text>`;
  }
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Cumulative dollars per MW by graded day">${g}${lines}${labels}<line class="cross" x1="0" x2="0" y1="${T}" y2="${H - B}" visibility="hidden"/><rect x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}" fill="transparent"/></svg>`;
  const svg = host.querySelector("svg");
  const cross = svg.querySelector(".cross");
  const tip = $("tip");
  svg.querySelector("rect").addEventListener("pointermove", (ev) => {
    const r = svg.getBoundingClientRect();
    const sx = ((ev.clientX - r.left) * W) / r.width;
    let i = 0;
    days.forEach((_, k) => { if (Math.abs(x(k) - sx) < Math.abs(x(i) - sx)) i = k; });
    cross.setAttribute("x1", x(i));
    cross.setAttribute("x2", x(i));
    cross.setAttribute("visibility", "visible");
    const rows = ss.filter((s) => s.pts.some((p) => p.d === days[i])).map((s) => ({ s, p: s.pts.find((p) => p.d === days[i]) })).sort((a, c) => c.p.v - a.p.v);
    tip.innerHTML = `<h6>Through ${dayName(days[i])}</h6>${rows.map(({ s, p }) => `<div class="r"><span><i style="${keyStyle(s.n)}"></i>${esc(short(s.label))}</span><span>${usd(p.v)} <span class="na">(${usd(p.day.usd_per_mw, true)} · C ${fix(p.day.c_mean)})</span></span></div>`).join("")}`;
    tip.hidden = false;
    const tx = Math.min(ev.clientX + 16, innerWidth - tip.offsetWidth - 8);
    tip.style.left = `${tx}px`;
    tip.style.top = `${Math.max(8, ev.clientY - tip.offsetHeight - 12)}px`;
  });
  svg.querySelector("rect").addEventListener("pointerleave", () => {
    cross.setAttribute("visibility", "hidden");
    tip.hidden = true;
  });
}

function nice(x) {
  const p = 10 ** Math.floor(Math.log10(x));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((v) => v >= x);
}

const short = (label) => label.replace("Qwen3-4B trained (run 4)", "Trained 4B");

function who(b, n) {
  const st = STYLE[n];
  const mark = REFS.has(n) || b.agents[n].kind === "rule" ? `<i class="line" style="${keyStyle(n)}"></i>` : `<i style="background:${st.color}"></i>`;
  return `<span class="who">${mark}${esc(b.agents[n].label)}</span>`;
}

function standings(b) {
  if (!b.graded_days.length) {
    $("standings").innerHTML = "";
    return;
  }
  const rows = ORDER.filter((n) => b.agents[n] && !REFS.has(n)).sort((a, c) => (b.agents[c].total_usd_per_mw ?? -1e9) - (b.agents[a].total_usd_per_mw ?? -1e9));
  const gap = (g) => (g ? `${usd(g.usd_per_mw_per_day.mean, true)} <span class="ci">[${usd(g.usd_per_mw_per_day.ci[0], true)}, ${usd(g.usd_per_mw_per_day.ci[1], true)}]</span>` : `<span class="na">–</span>`);
  const row = (n, ref) => {
    const a = b.agents[n];
    const nd = Object.keys(a.days || {}).length;
    return `<tr class="${ref ? "ref" : ""}"><td>${who(b, n)}</td><td>${nd || "–"}</td><td><b>${usd(a.total_usd_per_mw)}</b></td><td>${fix(a.c_mean)}</td><td>${ref ? "" : gap(a.vs_persistence_dp)}</td></tr>`;
  };
  $("standings").innerHTML = `<thead><tr><th>Agent</th><th>Days</th><th>$ per MW</th><th>Mean C</th><th>vs persistence + DP, $/MW a day [95% CI]</th></tr></thead><tbody>${rows.map((n) => row(n, false)).join("")}<tr class="sep"><td colspan="5">References, computed after the prices post</td></tr>${["blind_anchor", "hindsight_dp"].filter((n) => b.agents[n]).map((n) => row(n, true)).join("")}</tbody>`;
}

function daily(b) {
  const days = b.graded_days;
  if (!days.length) {
    $("daily").innerHTML = `<tbody><tr><td class="na">No graded day yet.</td></tr></tbody>`;
    return;
  }
  const head = `<thead><tr><th>Agent</th>${days.map((d) => `<th>${dayName(d)}</th>`).join("")}</tr></thead>`;
  const body = ORDER.filter((n) => b.agents[n]).map((n) => {
    const a = b.agents[n];
    return `<tr class="${REFS.has(n) ? "ref" : ""}"><td>${who(b, n)}</td>${days.map((d) => {
      const v = a.days[d];
      return v ? `<td class="cell">${usd(v.usd_per_mw)}<small>C ${fix(v.c_mean)}</small></td>` : `<td class="na">not sealed</td>`;
    }).join("")}</tr>`;
  }).join("");
  $("daily").innerHTML = head + `<tbody>${body}</tbody>`;
}

function timeline(b) {
  const tl = [...(b.timeline || [])].sort((a, c) => (a.delivery_day < c.delivery_day ? 1 : -1));
  if (!tl.length) {
    $("timeline").innerHTML = `<li><span class="na">Nothing sealed yet.</span></li>`;
    return;
  }
  $("timeline").innerHTML = tl.map((t) => {
    const sc = t.seal_commit;
    let chip = `<span class="chip">Not sealed</span>`;
    if (t.graded_utc) chip = t.seal_valid ? `<span class="chip graded">Graded</span>` : `<span class="chip bad">Seal late</span>`;
    else if (sc) chip = `<span class="chip sealed">Sealed</span>`;
    else if (t.sealed_utc) chip = `<span class="chip">Publishing</span>`;
    const seal = sc
      ? `<span class="k">Sealed</span>${when(sc.created_utc)} · <a href="${esc(sc.url)}" target="_blank" rel="noopener">${esc(sc.oid.slice(0, 7))}</a><small><a href="${DATASET}/blob/main/live/sealed/${t.delivery_day}.json" target="_blank" rel="noopener">sealed file</a> · ${lead(sc.created_utc, t.dam_close_utc)}${t.missing_agents && t.missing_agents.length ? ` · missing: ${t.missing_agents.map((m) => esc(b.agents[m] ? short(b.agents[m].label) : m)).join(", ")}` : ""}</small>`
      : `<span class="k">Sealed</span>–`;
    const gc = t.grade_commit;
    const graded = t.graded_utc
      ? `<span class="k">Graded</span>${when(t.graded_utc)}${gc ? ` · <a href="${esc(gc.url)}" target="_blank" rel="noopener">${esc(gc.oid.slice(0, 7))}</a>` : ""}<small><a href="${DATASET}/blob/main/live/graded/${t.delivery_day}.json" target="_blank" rel="noopener">graded file</a></small>`
      : `<span class="k">Graded</span>–<small>prices post about 13:30 CT on ${dayName(prevDay(t.delivery_day))}</small>`;
    return `<li><div class="day">${dayName(t.delivery_day)}<small>DAM ${new Date(t.dam_close_utc) > new Date() ? "closes" : "closed"} ${when(t.dam_close_utc)}</small></div><div class="step">${seal}</div><div class="step">${graded}</div><div>${chip}</div></li>`;
  }).join("");
}

function prevDay(d) {
  const t = new Date(`${d}T12:00:00Z`);
  t.setUTCDate(t.getUTCDate() - 1);
  return t.toISOString().slice(0, 10);
}

main();
