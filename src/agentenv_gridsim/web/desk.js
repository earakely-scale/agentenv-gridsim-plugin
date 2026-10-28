/** The desk: reads desk.json (written by scripts/hub_desk.py) and draws each desk version's board, its capture and
 * dollars against the anchor, the hindsight optimum and the real operator, where the money came from and how each
 * model traded. ?v=v3 opens a version. */
const Q = new URLSearchParams(location.search);
const EXPORT = Q.has("export");
const DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv";
const REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin";
const ARTICLE = "https://huggingface.co/spaces/earakely-scale/GridSimEnv";
const COL = { sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)" };
const REFC = { anchor: "var(--c-anchor)", operator_replay: "var(--c-op)", operator_actual: "var(--c-op)", hind_phys: "var(--c-rule)", idle: "var(--c-rule)" };
const AS = { regup: "RegUp", regdn: "RegDn", rrsffr: "RRS-FFR", rrspfr: "RRS-PFR", ecrs: "ECRS", nspin: "Non-Spin" };
const ASO = { "ASO-02": "the shape check", "ASO-06": "after the market window closed" };
const md = (s) => esc(s).replace(/`([^`]+)`/g, "<code>$1</code>");
const BUYBACK = "day-ahead sales bought back in real time: positions the DAM allows because it ignores state of charge, and which ERCOT's DAM credit screening, not modelled here, would limit";
const INLINE = { anchor: "the anchor", operator_replay: "the operator's bids", operator_actual: "the operator as settled" };
const SHORT = { anchor: "Anchor", operator_replay: "Operator's bids, replayed", operator_actual: "Operator, as settled", hind_phys: "Hindsight, DAM tied to dispatch", hind: "Hindsight optimum", idle: "Idle" };
const LINE = { dam_energy: "DAM energy", rt_energy_imbalance: "RT imbalance", deviation: "Set-point deviation", load_allocated: "Load-allocated charges", dam_as_capacity: "DAM ancillary capacity", rt_as_imbalance: "RT ancillary imbalance", as_only_buyback: "Ancillary buy-back", capacity_short: "Capacity short", failure_to_provide: "Failure to provide", pv_energy: "Solar energy", degradation: "Degradation", warranty_overage: "Warranty overage", end_soc_shortfall: "End-of-day energy" };
const MODELLED = new Set(["degradation", "warranty_overage", "end_soc_shortfall", "capacity_short", "pv_energy"]);

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const minus = (s) => s.replace(/-/g, "−");
const num = (x, n = 3) => {
  const [i, f = ""] = Math.abs(x).toString().split(".");
  if (/e/.test(i)) return minus(x.toFixed(n));
  const v = BigInt(i + f.slice(0, n).padEnd(n, "0")) + (f[n] >= "5" ? 1n : 0n);
  const s = v.toString().padStart(n + 1, "0");
  return minus(`${x < 0 && v ? "-" : ""}${s.slice(0, s.length - n)}${n ? `.${s.slice(-n)}` : ""}`);
};
const ci = (c, n = 3) => `[${num(c[0], n)}, ${num(c[1], n)}]`;
const whole = (a) => { const f = Math.floor(a), d = a - f; return d > 0.5 || (d === 0.5 && f % 2 === 1) ? f + 1 : f; };
const usd = (x, s = false) => { const w = whole(Math.abs(x)); return `${!w ? "" : x < 0 ? "−\u2060" : s ? "+\u2060" : ""}$${w.toLocaleString("en-US")}`; };
const usdci = (c, s = false) => `[${usd(c[0], s)}, ${usd(c[1], s)}]`;
const pct = (x) => `${whole(100 * x)}%`;
const unit = (V) => (V.days_per_task > 1 ? `${V.days_per_task}-day window` : "battery-day");
const link = (href, t) => `<a href="${href}" target="_blank" rel="noopener">${t}</a>`;
const day = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const day_ = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });

const TIPS = [];
const tip = (html) => `data-tip="${TIPS.push(html) - 1}" tabindex="0"`;
const tipRows = (title, rows) => `<h6>${title}</h6>${rows.map(([a, b]) => `<div class="r"><span>${a}</span><span>${b}</span></div>`).join("")}`;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const svg = (w, h, body, label) => `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;
const txt = (x, y, s, cls, anchor = "start") => `<text x="${x}" y="${y}" class="${cls}" text-anchor="${anchor}">${s}</text>`;
const line = (x1, y1, x2, y2, stroke, w = 1, dash = "") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
const block = (h, sub, inner, kicker = "", fig = "") => `<section class="panel${fig ? " fig" : ""}"${fig ? ` data-figure="${fig}"` : ""}><div class="panel-head">${kicker ? `<span class="kicker">${kicker}</span>` : ""}<h2>${h}</h2>${sub ? `<p class="sub">${sub}</p>` : ""}</div>${inner}</section>`;

function ticks(d0, d1, n) {
  const raw = (d1 - d0) / n, p = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(d0 / step) * step; v <= d1 + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function rows(V) {
  const refs = V.references.filter((r) => r.key !== "hind" && (r.key !== "idle" || Math.abs(r.P.mean) >= 0.5));
  return [...V.models.map((m) => ({ ...m, kind: "model", color: COL[m.key] || "var(--c-base)" })),
    ...refs.map((r) => ({ ...r, kind: "ref", color: REFC[r.key] || "var(--c-rule)" }))];
}

function render(D) {
  TIPS.length = 0;
  const want = Q.get("v") || location.hash.slice(1);
  const V = D.versions.find((v) => v.version === want) || D.versions.at(-1);
  $("tabs").innerHTML = D.ladder.map((x) => {
    const v = D.versions.find((y) => y.version === x.version);
    return v ? `<a href="?v=${x.version}" data-v="${x.version}" class="${v === V ? "on" : ""}"><b>${x.version} · ${esc(x.name)}</b><small>${v.n_tasks} real ${unit(v)}s</small></a>`
      : `<span><b>${x.version} · ${esc(x.name)}</b><small>next</small></span>`;
  }).join("");
  if (!V) {
    $("lede").textContent = "The desk's first results are still running.";
    return;
  }
  if (EXPORT) {
    document.body.classList.add("export");
    document.documentElement.dataset.theme = "light";
    $("main").innerHTML = capFig(V, 588) + usdFig(V, 588);
    return;
  }
  const W = Math.max(280, Math.min(1080, $("main").clientWidth) - (innerWidth < 720 ? 26 : 42));
  const regions = V.sites.map((s) => s.region).join(", ");
  $("lede").innerHTML = `One real ERCOT battery, traded the way a desk trades it: <b>day-ahead bids before the 10:00 close, real-time offers and the COP through the operating day</b>, on ERCOT's real prices, forecasts and notices as each was posted, with the clock moving on its own between turns. ${esc(V.version)}, <i>${esc(V.name)}</i>, adds ${esc(V.adds)}. ${V.n_tasks} ${unit(V)}s: ${V.sites.length} real batteries (${esc(regions)}) on ${V.n_days} days from ${day(V.dates[0])} to ${day(V.dates[1])}.`;
  $("kpis").innerHTML = kpis(V);
  $("main").innerHTML = [
    block("The board", `Each model played each ${unit(V)} once under pre-registered settings. C is the share of the hindsight optimum's profit over idle; P the battery's settled ERCOT statement a ${unit(V)}; R, second to C, the env's reward (idle 0.2, the anchor 1.0). Brackets: day-block bootstrap 95% CIs over ${V.n_days} operating days.`, board(V), `${V.version} · ${esc(V.name)}`),
    sensitivity(V),
    capFig(V, W),
    usdFig(V, W),
    block("Where the money came from", `Each line of the settled statement, mean $ a ${unit(V)}. DAM energy settles at the node's day-ahead price, RT imbalance at its 15-minute real-time price; modelled lines are marked.`, linesTable(V)),
    reserves(V),
    block("How each desk traded", `Means per ${unit(V)}: turns are wake-ups the model acted on, calls its tool calls, submissions the DAM curves, RT curves and COP updates it filed (rejections carry ERCOT-style codes).`, behaviour(V)),
    episode(V, D),
    how(),
    sources(V),
  ].join("");
}

function kpis(V) {
  const m = V.models[0], refs = Object.fromEntries(V.references.map((r) => [r.key, r]));
  const g = m.P_minus_anchor, o = m.P_minus_operator_replay, a = refs.anchor;
  const tile = (v, cls, l, t) => `<div class="kpi"><div class="v ${cls}">${v}</div><div class="l">${l}</div><div class="t">${t}</div></div>`;
  const sign = (b) => (b.ci[0] > 0 ? "pos" : b.ci[1] < 0 ? "neg" : "");
  return [
    tile(num(m.C.mean), "", `of the hindsight optimum captured: ${esc(m.name)}`, `C ${ci(m.C.ci)}; ${usd(m.P.mean)} a ${unit(V)}. The anchor captures ${num(a.C.mean)}, the hindsight optimum 1 by definition.`),
    o.mean == null ? tile("–", "", "against the real operator", "No operator disclosure for these days.") :
      tile(usd(o.mean, true), sign(o), `a ${unit(V)} against the real operator's bids`, `${usdci(o.ci, true)}${o.ci[0] <= 0 && o.ci[1] >= 0 ? ", a CI that includes zero" : ""}. Its bids, disclosed by ERCOT 60 days later and replayed through the same clearing and settlement, earn ${usd(refs.operator_replay.P.mean)} a ${unit(V)}.`),
    tile(usd(g.mean, true), sign(g), `a ${unit(V)} against the anchor`, `${usdci(g.ci, true)}; ahead on ${pct(m.beats_anchor)} of ${unit(V)}s. The anchor is the desk's own optimiser on the same information${((V.sensitivity || {}).bought_back || []).includes("anchor") ? "; its DAM/RT spread positions pay off on scarcity days" : ", free to take DAM/RT spread positions"}.`),
    tile(String(V.n_tasks), "", `real ${unit(V)}s`, `${V.sites.map((s) => `${esc(s.region)} ${esc(s.size)}`).join(" · ")}; ${V.n_days} operating days, every one old enough for ERCOT to have disclosed the operators' bids.`),
  ].join("");
}

function board(V) {
  const pa = `P a ${unit(V)}`, head = ["Desk", "C", pa, "P − operator's bids", "P − anchor", "R", "Beats anchor", "$ a run"];
  const cell = (l, v, sub = "") => `<td data-l="${l}">${v}${sub ? `<span class="sub">${sub}</span>` : ""}</td>`;
  const na = (l) => `<td class="na" data-l="${l}">–</td>`;
  const who = (r) => `<span class="who"><i style="background:${r.color}"></i><span>${r.kind === "model" ? `<b>${esc(r.name)}</b>` : esc(r.name)}${r.effort ? `<span class="sub">${esc(r.effort)} effort</span>` : r.weights === "open" ? `<span class="sub">open weights</span>` : ""}</span></span>`;
  const op = (r) => (r.P_minus_operator_replay.mean == null ? cell("P − operator's bids", "–") : cell("P − operator's bids", usd(r.P_minus_operator_replay.mean, true), usdci(r.P_minus_operator_replay.ci, true)));
  const body = rows(V).map((r) => r.kind === "model"
    ? `<tr><td>${who(r)}</td>${cell("C", `<b>${num(r.C.mean)}</b>`, ci(r.C.ci))}${cell(pa, usd(r.P.mean), usdci(r.P.ci))}${op(r)}${cell("P − anchor", usd(r.P_minus_anchor.mean, true), usdci(r.P_minus_anchor.ci, true))}${cell("R", num(r.R.mean, 2), ci(r.R.ci, 2))}${cell("Beats anchor", pct(r.beats_anchor))}${cell("$ a run", r.weights === "open" || r.usd_per_episode == null ? "–" : `$${r.usd_per_episode.toFixed(2)}`)}</tr>`
    : `<tr class="ref"><td>${who(r)}</td>${cell("C", num(r.C.mean), ci(r.C.ci))}${cell(pa, usd(r.P.mean), usdci(r.P.ci))}${["P − operator's bids", "P − anchor", "R", "Beats anchor", "$ a run"].map(na).join("")}</tr>`).join("");
  const hind = V.references.find((r) => r.key === "hind");
  return `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr>${head.map((h, i) => `<th class="${i ? "" : "l"}">${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="note">The hindsight optimum earns ${usd(hind.P.mean)} a ${unit(V)} ${usdci(hind.P.ci)}: the best the rules allow with every price known in advance, DAM/RT spread positions included. The operator rows use the real operator's own disclosed bids and awards on each ${unit(V)}, settled by the same code.${V.idle ? ` ${esc(V.idle)}` : ""}</p>`;
}

function frame(R, W) {
  const narrow = W < 560, rh = narrow ? 46 : 34, top = 30, H = top + R.length * rh + 34;
  const left = narrow ? 10 : 218, y = (i) => top + i * rh + (narrow ? 30 : rh / 2);
  const label = (r, i) => txt(narrow ? 10 : left - 8, narrow ? y(i) - 14 : y(i) + 4, esc(r.kind === "model" ? r.name : r.short || SHORT[r.key] || r.name), `t-lab${r.kind === "model" ? " b" : ""}`, narrow ? "start" : "end");
  return { narrow, top, H, left, y, label };
}

function sensitivity(V) {
  const sv = V.sensitivity, w = sv && sv.without;
  if (!w) return "";
  const ms = Object.fromEntries(V.models.map((m) => [m.key, m])), name = (k) => (ms[k] ? ms[k].name : SHORT[k] || k);
  const said = (k) => (ms[k] ? ms[k].name : INLINE[k] || k), and = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`);
  const one = w.days.length === 1, day = and(w.days.map(day_)), all = Object.fromEntries([...V.models.map((m) => [m.key, m.P]), ...V.references.map((r) => [r.key, r.P])]);
  const keys = [...Object.keys(w.means.models), ...Object.keys(w.means.references)];
  const wo = { ...w.means.models, ...w.means.references }, med = { ...sv.median_P, ...sv.median_P_references };
  const per = w.days.map((d) => ({ ...sv.per_day_mean_P[d].models, ...sv.per_day_mean_P[d].references }));
  const rows = keys.map((k) => `<tr class="${ms[k] ? "" : "ref"}"><td>${ms[k] ? `<b>${esc(name(k))}</b>` : esc(name(k))}</td><td data-l="All ${V.n_tasks}">${usd(all[k].mean)}<span class="sub">${usdci(all[k].ci)}</span></td>${per.map((on, i) => `<td data-l="On ${day_(w.days[i])}">${on[k] == null ? "–" : usd(on[k])}</td>`).join("")}<td data-l="Without ${one ? "it" : "them"}">${usd(wo[k].P.mean)}<span class="sub">${usdci(wo[k].P.ci)}</span></td><td data-l="Median, all">${med[k] == null ? "–" : usd(med[k])}</td></tr>`).join("");
  const loss = Object.entries(sv.losses).map(([k, x]) => `${esc(name(k))} on ${x.tasks_p_below_0} (worst ${usd(x.worst_p)})`).join("; ");
  const who = (sv.carried || []).map(said), bb = (sv.bought_back || []).map(said);
  const from = !bb.length ? "" : bb.length === who.length ? `, from ${BUYBACK}` : `; ${and(bb)} from ${BUYBACK}`;
  const lead = who.length ? `On ${day}${sv.why_short ? `, ${esc(sv.why_short)}` : ""}, ${esc(and(who))} made more than half of ${who.length > 1 ? "their" : "its"} total P${esc(from)}. ` : "";
  return block(who.length ? `${one ? "One day carries" : "A few days carry"} the means` : `Without ${day}`, `${lead}Mean P a ${unit(V)} with and without ${one ? "that day" : "those days"}, and the median over every ${unit(V)}. P below zero: ${loss}. A post-hoc check, not pre-registered.`,
    `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>All ${V.n_tasks}</th>${w.days.map((d) => `<th>On ${day_(d)}</th>`).join("")}<th>Without ${one ? "it" : "them"} (${w.n_tasks})</th><th>Median, all</th></tr></thead><tbody>${rows}</tbody></table></div>`, "Sensitivity");
}

function capFig(V, W) {
  const R = rows(V).filter((r) => r.key !== "idle"), lo = Math.min(0, ...R.map((r) => r.C.ci[0])), hi = Math.max(1, ...R.map((r) => r.C.ci[1]));
  const F = frame(R, W), x = lin(lo - 0.02, hi + 0.02, F.left, W - 56);
  let s = ticks(lo, hi, F.narrow ? 4 : 8).map((t) => `<g class="grid">${line(x(t), F.top - 6, x(t), F.H - 26, "", 1)}</g>${txt(x(t), F.H - 10, num(t, 1), "t-ax", "middle")}`).join("");
  s += line(x(0), F.top - 10, x(0), F.H - 26, "var(--text-muted)", 1) + txt(x(0) + 4, F.top - 14, "idle", "t-ann");
  s += line(x(1), F.top - 10, x(1), F.H - 26, "var(--text-muted)", 1, "4 3") + txt(x(1) - 4, F.top - 14, "hindsight optimum", "t-ann", "end");
  R.forEach((r, i) => {
    const y = F.y(i), t = tip(tipRows(esc(r.name), [["C", `${num(r.C.mean)} ${ci(r.C.ci)}`], [`P a ${unit(V)}`, `${usd(r.P.mean)} ${usdci(r.P.ci)}`], ...(r.kind === "model" ? [["P − anchor", `${usd(r.P_minus_anchor.mean, true)} ${usdci(r.P_minus_anchor.ci, true)}`]] : [])]));
    s += F.label(r, i) + line(x(r.C.ci[0]), y, x(r.C.ci[1]), y, r.color, 2);
    s += `<circle cx="${x(r.C.mean)}" cy="${y}" r="${r.kind === "model" ? 6 : 5}" fill="${r.kind === "model" ? r.color : "var(--surface-1)"}" stroke="${r.color}" stroke-width="2" ${t}/>`;
    s += txt(Math.max(x(r.C.ci[1]), x(r.C.mean) + 6) + 8, y + 4, num(r.C.mean), `t-val${r.kind === "model" ? " b" : ""}`);
  });
  return block("Capture: how much of the hindsight optimum each desk earned", "C for each model and reference, with its 95% CI. Idle is 0 and the hindsight optimum 1 by definition; the anchor and the real operator are drawn as references.", `<div class="chart fig">${svg(W, F.H, s, "Hindsight capture by desk")}</div>`, "Capture", "capture");
}

function usdFig(V, W) {
  const R = rows(V), hind = V.references.find((r) => r.key === "hind");
  const lo = Math.min(0, ...R.map((r) => r.P.ci[0])), hi = Math.max(hind.P.mean, ...R.map((r) => r.P.ci[1]));
  const F = frame(R, W), x = lin(lo - (hi - lo) * 0.02, hi * 1.04, F.left, W - 70);
  let s = ticks(lo, hi, F.narrow ? 3 : 6).map((t) => `<g class="grid">${line(x(t), F.top - 6, x(t), F.H - 26, "", 1)}</g>${txt(x(t), F.H - 10, usd(t), "t-ax", "middle")}`).join("");
  s += line(x(0), F.top - 10, x(0), F.H - 26, "var(--text-muted)", 1) + line(x(hind.P.mean), F.top - 10, x(hind.P.mean), F.H - 26, "var(--text-muted)", 1, "4 3");
  s += txt(x(hind.P.mean) - 4, F.top - 14, `hindsight optimum ${usd(hind.P.mean)}`, "t-ann", "end");
  R.forEach((r, i) => {
    const y = F.y(i), x0 = x(Math.min(0, r.P.mean)), w = Math.abs(x(r.P.mean) - x(0));
    const t = tip(tipRows(esc(r.name), [[`P a ${unit(V)}`, `${usd(r.P.mean)} ${usdci(r.P.ci)}`], ["C", num(r.C.mean)]]));
    s += F.label(r, i);
    s += `<rect x="${x0}" y="${y - 8}" width="${Math.max(1, w)}" height="16" rx="3" fill="${r.color}" fill-opacity="${r.kind === "model" ? 0.9 : 0.35}" ${t}/>`;
    s += line(x(r.P.ci[0]), y, x(r.P.ci[1]), y, "var(--text-primary)", 1.2);
    s += txt(Math.max(x(r.P.ci[1]), x(r.P.mean)) + 8, y + 4, usd(r.P.mean), `t-val${r.kind === "model" ? " b" : ""}`);
  });
  return block(`Dollars: the settled statement a ${unit(V)}`, "Mean P with 95% CIs, models in colour and references in grey and bronze. The dashed line is the hindsight optimum.", `<div class="chart fig">${svg(W, F.H, s, `Mean settled P per ${unit(V)}`)}</div>`, "Dollars", "dollars");
}

function linesTable(V) {
  const keys = [...new Set(V.models.flatMap((m) => Object.keys(m.lines)))].filter((k) => V.models.some((m) => Math.abs(m.lines[k] || 0) >= 0.5));
  const order = Object.keys(LINE);
  keys.sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  const head = `<tr><th class="l">Line</th>${V.models.map((m) => `<th>${esc(m.name)}</th>`).join("")}</tr>`;
  const body = keys.map((k) => `<tr><td>${esc(LINE[k] || k)}${MODELLED.has(k) ? ' <span class="mod">modelled</span>' : ""}</td>${V.models.map((m) => `<td data-l="${esc(m.name)}">${usd(m.lines[k] || 0, true)}</td>`).join("")}</tr>`).join("");
  const total = `<tr><td><b>P</b></td>${V.models.map((m) => `<td data-l="${esc(m.name)}"><b>${usd(m.P.mean, true)}</b></td>`).join("")}</tr>`;
  return `<div class="table-scroll"><table class="grid stack lines"><thead>${head}</thead><tbody>${body}${total}</tbody></table></div>`;
}

function reserves(V) {
  const ms = V.models.filter((m) => m.ancillary);
  if (!ms.length) return "";
  const mwh = (o) => Object.values(o).reduce((a, b) => a + b, 0), f = (v) => (!v ? "0" : v >= 9.95 ? Math.round(v).toLocaleString("en-US") : v.toFixed(1));
  const parts = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${AS[k] || k} ${f(v)}`).join(", ");
  const body = ms.map((m) => {
    const a = m.ancillary, rc = Object.entries(a.rejected_codes_total), got = (m.lines.dam_as_capacity || 0) + (m.lines.rt_as_imbalance || 0);
    const refused = rc.length ? `${rc.reduce((x, [, k]) => x + k, 0)}<span class="sub">${rc.map(([c, k]) => `${esc(c)} ×${k}${ASO[c] ? `, ${ASO[c]}` : ""}`).join("; ")}</span>` : "–";
    return `<tr><td><span class="who"><i style="background:${COL[m.key] || "var(--c-base)"}"></i><b>${esc(m.name)}</b></span></td><td data-l="AS awards">${a.episodes_with_awards} of ${m.n}</td><td data-l="From the AS lines">${usd(got, true)}</td><td data-l="DAM award MWh">${f(mwh(a.dam_award_mwh))}<span class="sub">${parts(a.dam_award_mwh)}</span></td><td data-l="RT award MWh">${f(mwh(a.rt_award_mwh))}<span class="sub">${parts(a.rt_award_mwh)}</span></td><td class="full" data-l="AS offers refused">${refused}</td></tr>`;
  }).join("");
  return block("Reserves: what each desk's AS offers won", `Means per ${unit(V)}. AS awards counts the ${unit(V)}s with any ancillary-service award; the AS lines are DAM capacity and RT imbalance; award MWh by product, DAM and real time.`,
    `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>AS awards</th><th>From the AS lines</th><th>DAM award MWh</th><th>RT award MWh</th><th>AS offers refused</th></tr></thead><tbody>${body}</tbody></table></div>${V.defects ? `<p class="note">${md(V.defects)}</p>` : ""}`, "Reserves");
}

function behaviour(V) {
  const head = ["Desk", "Turns", "Wakes", "Calls", "Most-used tools", "Submissions accepted / rejected", "Rejection codes", "Reminders", "Cycles"];
  const body = V.models.map((m) => {
    const tools = Object.entries(m.calls_by_tool).slice(0, 4).map(([t, n]) => `<span class="nw"><code>${esc(t)}</code> ${num(n, 1)}</span>`).join(", ");
    const codes = Object.entries(m.rejected_codes).slice(0, 3).map(([c, n]) => `${esc(c)} ×${n}`).join(", ") || "–";
    return `<tr><td><span class="who"><i style="background:${COL[m.key] || "var(--c-base)"}"></i><b>${esc(m.name)}</b></span></td><td data-l="Turns">${num(m.turns, 1)}</td><td data-l="Wakes">${num(m.wakes, 1)}</td><td data-l="Calls">${num(m.calls, 1)}</td><td class="l full" data-l="Most-used tools">${tools}</td><td data-l="Accepted / rejected">${num(m.accepted, 1)} / ${num(m.rejected, 1)}</td><td class="l full codes" data-l="Rejection codes">${codes}</td><td data-l="Reminders">${num(m.reminders, 1)}</td><td data-l="Cycles">${num(m.cycles, 2)}</td></tr>`;
  }).join("");
  return `<div class="table-scroll"><table class="grid stack wrapcells beh"><thead><tr>${head.map((h, i) => `<th class="${i === 0 || i === 4 || i === 6 ? "l" : ""}">${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function episode(V, D) {
  const res = (rel) => `${DATASET}/resolve/main/${rel}`;
  const h = V.hero;
  if (D.gif && D.gif.version === V.version) {
    return block(`One ${unit(V)}, as it happened`, `${esc(D.gif.alt)}.`, `<div class="desk-ep"><a href="${res(D.gif.path)}"><img src="${res(D.gif.path)}" alt="${esc(D.gif.alt)}" loading="lazy"></a></div>`, "A run");
  }
  if (!h || !V.figures.hero) return "";
  return block(`One ${unit(V)}: ${esc(h.label)}`, "The node's day-ahead and 5-minute real-time prices, the battery's state of charge (dashed: the real operator's, as disclosed) and its dispatch against the DAM award, with every wake-up and what the desk did at it.",
    `<div class="desk-ep"><picture><source srcset="${res(V.figures.hero_dark)}" media="(prefers-color-scheme: dark)"><img src="${res(V.figures.hero)}" alt="The desk's timeline for one ${unit(V)}" loading="lazy"></picture></div>`, "A run");
}

function how() {
  const g = [["ERCOT's public reports", "<code>get_prices</code> (DAM, 15-minute RT and 5-minute SCED at the node; DAM and RT at its hub), <code>get_forecasts</code> (ERCOT's load, wind, solar and outage forecasts as issued, NWS alerts, the desk's price forecast, modelled), <code>get_grid_conditions</code>"],
    ["Plant telemetry and the book", "<code>get_asset_status</code> (state of charge, limits, base points, outages), <code>get_position</code> (awards, RT position, COP, the statement so far)"],
    ["ERCOT's market submission system", "<code>submit_dam_offers</code>, <code>submit_rt_offers</code>, <code>update_cop</code>, and <code>check_submission</code>, a dry run with ERCOT's validation codes"],
    ["The desk's analytics", "<code>optimize</code>, a co-optimiser on the agent's own price view that proposes curves and a COP and never submits; <code>set_reminder</code>"]];
  return block("How the desk works", `The agent never moves a megawatt: ERCOT's clearing turns its curves into dispatch every 5 minutes, and the day settles on ERCOT's statement. The clock stands still while it works and runs between turns; it wakes at the market's milestones, at each notice, outage and deployment at its real minute, and at reminders it sets. ${link(`${ARTICLE}#the-desk`, "The article's chapter on the desk")} explains why and how.`,
    `<div class="tools">${g.map(([h, t]) => `<div><h3>${h}</h3>${t}</div>`).join("")}</div>`, "Eleven tools");
}

function sources(V) {
  const t = (rel) => `${DATASET}/tree/main/${rel}`, b = (rel) => `${DATASET}/blob/main/${rel}`;
  return block("Every number's source", "", `<div class="links-grid">
    <div><h3>On the dataset</h3><ul><li>${link(t(V.folder), `<code>${V.folder}</code>`)}</li><li>${link(b(`${V.folder}/README.md`), "README")} · ${link(b(`${V.folder}/summary.json`), "summary.json")} · ${link(b(`${V.folder}/grades.jsonl.gz`), "grades")}</li><li>configs <code>desk_leaderboard</code> and <code>desk_runs</code>, split <code>${V.version}</code></li></ul></div>
    <div><h3>On GitHub, tag <code>${esc(V.ref)}</code></h3><ul><li>${link(V.github, "the result folder")}</li><li>${link(`${REPO}/blob/${V.ref}/docs/prereg/${V.version}-desk.md`, "the pre-registration")}</li><li>${link(`${REPO}/blob/${V.ref}/docs/CONTRACT-desk.md`, "the desk contract")}</li></ul></div>
    <div><h3>Settings</h3><ul><li>${esc(V.budget)}</li><li>core ${esc(V.core)}, ${esc(V.eras.join(", "))} rules</li><li>${esc(V.ci.method)}, ${V.ci.resamples.toLocaleString("en-US")} resamples</li></ul></div></div>
    ${V.defects ? `<p class="note">${md(V.defects)}</p>` : ""}<p class="note">Prices, notices and disclosures: ERCOT's public reports; weather alerts: NWS. Not affiliated with or endorsed by ERCOT.</p>`);
}

function tips() {
  const box = $("tip");
  let pinned = null;
  const show = (el, x, y) => {
    box.innerHTML = TIPS[+el.dataset.tip];
    box.hidden = false;
    const w = box.offsetWidth, h = box.offsetHeight;
    box.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, x + 14))}px`;
    box.style.top = `${y + h + 22 > innerHeight ? Math.max(8, y - h - 14) : y + 16}px`;
  };
  addEventListener("pointermove", (e) => {
    if (pinned || e.pointerType === "touch") return;
    const el = e.target.closest?.("[data-tip]");
    if (el) show(el, e.clientX, e.clientY);
    else box.hidden = true;
  });
  addEventListener("click", (e) => {
    const el = e.target.closest?.("[data-tip]");
    pinned = el && el !== pinned ? el : null;
    if (pinned) show(el, e.clientX, e.clientY);
    else box.hidden = true;
  });
  addEventListener("keydown", (e) => e.key === "Escape" && ((pinned = null), (box.hidden = true)));
  addEventListener("scroll", () => !pinned && (box.hidden = true), { passive: true });
}

async function main() {
  let D;
  try {
    D = await (await fetch("./desk.json", { cache: "no-store" })).json();
  } catch (e) {
    $("lede").textContent = `The desk's results could not be loaded (${e.message}).`;
    return;
  }
  render(D);
  if (EXPORT) {
    window.deskReady = true;
    return;
  }
  tips();
  $("tabs").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-v]");
    if (!a) return;
    e.preventDefault();
    Q.set("v", a.dataset.v);
    history.replaceState(null, "", `?${Q}`);
    render(D);
  });
  let w = innerWidth;
  addEventListener("resize", () => {
    if (Math.abs(innerWidth - w) < 8) return;
    w = innerWidth;
    clearTimeout(main.t);
    main.t = setTimeout(() => render(D), 120);
  });
  window.deskReady = true;
}

main();
