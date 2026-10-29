/** The desk's results. The landing, ?v=bench, is the v4 benchmark from bench.json (scripts/hub_space.py): the dataset
 * card's own words for it; its headline, capture either side of the training cutoffs, drawn by the card's chart module
 * (card-charts.js) at the page's width, with each model's post − pre gap; the board with every CI, paired gaps, every
 * run as a replay, and the links to the pre-registration, its deviations and the results folder. Then the development
 * ladder from desk.json (scripts/hub_desk.py): the findings, capture up the ladder (v2 to v4) beside the v5
 * price-impact check, then each version's board, its capture and dollars against the anchor, the hindsight optimum and
 * the real operator, where the money came from, how each model traded and every run as a replay; the check's board
 * leads with the price impact and v5 against v3. ?v=v4 opens a version; ?export=1 draws the capture and dollars figures
 * alone for the dataset card. */
const Q = new URLSearchParams(location.search);
const EXPORT = Q.has("export");
const DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv";
const REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin";
const ARTICLE = "https://huggingface.co/spaces/earakely-scale/GridSimEnv";
const SPACE = "https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv";
const ORDER = ["sol", "luna", "qwen"];
const COL = { sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)" };
const NICK = { sol: "Sol", luna: "Luna", qwen: "Qwen" };
const OPNAME = "Real operator (bids replayed)";
const REFC = { anchor: "var(--c-anchor)", operator_replay: "var(--c-op)", operator_actual: "var(--c-op)", hind_phys: "var(--c-hind)", idle: "var(--c-hind)" };
const AS = { regup: "RegUp", regdn: "RegDn", rrsffr: "RRS-FFR", rrspfr: "RRS-PFR", ecrs: "ECRS", nspin: "Non-Spin" };
const ASO = { "ASO-01": "a product the battery may not offer", "ASO-02": "the shape check", "ASO-06": "after the market window closed" };
const BUYBACK = "day-ahead sales bought back in real time: positions the DAM allows because it ignores state of charge, and which ERCOT's DAM credit screening, not modelled here, would limit";
const INLINE = { anchor: "the anchor", operator_replay: "the operator's bids", operator_actual: "the operator as settled" };
const SHORT = { anchor: "Anchor", operator_replay: "Operator's bids, replayed", operator_actual: "Operator, as settled", hind_phys: "Hindsight, DAM tied to dispatch", hind: "Hindsight optimum", idle: "Idle" };
const LINE = { dam_energy: "DAM energy", rt_energy_imbalance: "RT imbalance", deviation: "Set-point deviation", load_allocated: "Load-allocated charges", dam_as_capacity: "DAM ancillary capacity", rt_as_imbalance: "RT ancillary imbalance", as_only_buyback: "Ancillary buy-back", capacity_short: "Capacity short", failure_to_provide: "Failure to provide", pv_energy: "Solar energy", degradation: "Degradation", warranty_overage: "Warranty overage", end_soc_shortfall: "End-of-window energy" };
const MODELLED = new Set(["degradation", "warranty_overage", "end_soc_shortfall", "capacity_short", "pv_energy"]);

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const md = (s) => esc(s).replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
const minus = (s) => s.replace(/-/g, "−");
const num = (x, n = 3) => {
  const [i, f = ""] = Math.abs(x).toString().split(".");
  if (/e/.test(i)) return minus(x.toFixed(n));
  const v = BigInt(i + f.slice(0, n).padEnd(n, "0")) + (f[n] >= "5" ? 1n : 0n);
  const s = v.toString().padStart(n + 1, "0");
  return minus(`${x < 0 && v ? "-" : ""}${s.slice(0, s.length - n)}${n ? `.${s.slice(-n)}` : ""}`);
};
const sgn = (x, n = 3) => (x > 0 ? `+${num(x, n)}` : num(x, n));
const ci = (c, n = 3) => `[${num(c[0], n)}, ${num(c[1], n)}]`;
const sci = (c, n = 3) => `[${sgn(c[0], n)}, ${sgn(c[1], n)}]`;
const whole = (a) => { const f = Math.floor(a), d = a - f; return d > 0.5 || (d === 0.5 && f % 2 === 1) ? f + 1 : f; };
const usd = (x, s = false) => { const w = whole(Math.abs(x)); return `${!w ? "" : x < 0 ? "−⁠" : s ? "+⁠" : ""}$${w.toLocaleString("en-US")}`; };
const usdci = (c, s = false) => `[${usd(c[0], s)}, ${usd(c[1], s)}]`;
const pct = (x) => `${whole(100 * x)}%`;
const pts = (x, s = false) => { const k = Math.round(parseFloat(num(x, 3).replace("−", "-")) * 1000), a = Math.abs(k); return `${k < 0 ? "−" : s && k > 0 ? "+" : ""}${Math.floor(a / 10)}.${a % 10}`; };
const cp = (x) => `${pts(x)}%`;
const ptsci = (c) => `[${pts(c[0])}, ${pts(c[1])}]`;
const cents = (x) => `${x < 0 ? "−" : x > 0 ? "+" : ""}${(Math.abs(x) * 100).toFixed(1)}¢`;
const unit = (V) => (V.days_per_task > 1 ? `${V.days_per_task}-day window` : "battery-day");
const isCheck = (V) => V.role === "check";
const title = (V) => (isCheck(V) ? esc(V.label) : `${V.version} ${esc(V.name)}`);
const noise = (V) => Object.values(V.versus.models).every((b) => ["P", "C", "R"].every((k) => b[k].ci[0] <= 0 && b[k].ci[1] >= 0));
const blocks = (V) => (V.block === "day" ? `${V.n_days} operating days` : `${V.n_days} ${V.block}s`);
const and = (xs) => (xs.length < 2 ? xs.join("") : `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}`);
const lastDay = (V) => { const d = new Date(`${V.dates[1]}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + V.days_per_task - 1); return d.toISOString().slice(0, 10); };
const link = (href, t) => `<a href="${href}" target="_blank" rel="noopener">${t}</a>`;
const day = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const day_ = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const shortDay = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });
const blockLabel = (V, d) => {
  if (V.days_per_task === 1) return day_(d);
  const a = new Date(`${d}T12:00:00Z`), b = new Date(a), f = (x, o) => x.toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
  b.setUTCDate(b.getUTCDate() + V.days_per_task - 1);
  const name = ((V.sensitivity || {}).names || {})[d];
  return `the front of ${f(a, { day: "numeric", ...(a.getUTCMonth() === b.getUTCMonth() ? {} : { month: "long" }) })} to ${f(b, { day: "numeric", month: "long", year: "numeric" })}${name ? ` (${name})` : ""}`;
};

const TIPS = [];
const tip = (html) => `data-tip="${TIPS.push(html) - 1}" tabindex="0"`;
const tipRows = (title, rows) => `<h6>${title}</h6>${rows.map(([a, b]) => `<div class="r"><span>${a}</span><span>${b}</span></div>`).join("")}`;
const lin = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
const svg = (w, h, body, label) => `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" role="img" aria-label="${esc(label)}">${body}</svg>`;
const txt = (x, y, s, cls, anchor = "start") => `<text x="${x}" y="${y}" class="${cls}" text-anchor="${anchor}">${s}</text>`;
const line = (x1, y1, x2, y2, stroke, w = 1, dash = "") => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${stroke}" stroke-width="${w}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
const block = (h, sub, inner, fig = "", id = "") => `<section class="panel${fig ? " fig" : ""}"${fig ? ` data-figure="${fig}"` : ""}${id ? ` id="${id}"` : ""}>${h ? `<div class="panel-head"><h2>${h}</h2>${sub ? `<p class="sub">${sub}</p>` : ""}</div>` : ""}${inner}</section>`;
const who = (color, label, sub = "") => `<span class="who"><i style="background:${color}"></i><span>${label}${sub ? `<span class="sub">${sub}</span>` : ""}</span></span>`;
let MS = {};
const labelOf = (k) => (MS[k] ? MS[k].label : k);
const whoM = (k, color = COL[k] || "var(--c-hind)", extra = "") => who(color, `<b>${esc(MS[k].name)}</b>`, esc([MS[k].setting, extra].filter(Boolean).join(" · ")));
const keyM = (k) => `<span><i class="sw" style="background:${COL[k]}"></i><span class="lab">${esc(MS[k].name)}<small> · ${esc(MS[k].setting)}</small></span></span>`;
let RULER = null;
const measure = (s, cls) => {
  if (!RULER) {
    document.body.insertAdjacentHTML("beforeend", '<div class="chart" aria-hidden="true" style="position:absolute;left:-9999px;top:0;visibility:hidden"><svg width="10" height="10"></svg></div>');
    RULER = document.body.lastElementChild.firstElementChild;
  }
  const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
  t.setAttribute("class", cls);
  t.textContent = s;
  RULER.append(t);
  const w = t.getComputedTextLength();
  t.remove();
  return w;
};
const wrapText = (s, cls, w) => s.split(" ").reduce((ls, word) => {
  const t = ls.length ? `${ls.at(-1)} ${word}` : word;
  if (ls.length && measure(t, cls) <= w) ls[ls.length - 1] = t;
  else ls.push(word);
  return ls;
}, []);

function ticks(d0, d1, n) {
  const raw = (d1 - d0) / n, p = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw);
  const out = [];
  for (let v = Math.ceil(d0 / step) * step; v <= d1 + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function rows(V) {
  const refs = V.references.filter((r) => r.key !== "hind" && (r.key !== "idle" || Math.abs(r.P.mean) >= 0.5));
  return [...V.models.map((m) => ({ ...m, setting: MS[m.key].setting, label: MS[m.key].label, kind: "model", color: COL[m.key] || "var(--c-hind)" })),
    ...refs.map((r) => ({ ...r, kind: "ref", color: REFC[r.key] || "var(--c-hind)" }))];
}

function render(D, C) {
  TIPS.length = 0;
  const want = Q.get("v") || location.hash.slice(1);
  const L = D.versions.filter((v) => v.role === "ladder"), X = D.versions.find(isCheck);
  const V = D.versions.find((v) => v.version === want) || L.at(-1);
  if (EXPORT) {
    document.body.classList.add("export");
    document.documentElement.dataset.theme = "light";
    $("main").innerHTML = capFig(V, 588) + usdFig(V, 588);
    return;
  }
  const B = isCheck(V) && D.versions.find((v) => v.version === V.check_of);
  const W = Math.max(280, Math.min(1080, $("main").clientWidth) - (innerWidth < 720 ? 24 : 44));
  pagetabs(false);
  $("title").textContent = "How three models traded a real ERCOT battery, v2 to v4";
  document.title = `${V.version} results, the development ladder · GridSimEnv Desk`;
  const n = D.versions.reduce((a, v) => a + v.n_tasks * v.models.length, 0);
  $("lede").innerHTML = `A desk agent trades one real ERCOT battery the way a QSE's battery desk does: <b>day-ahead bids before the 10:00 close, real-time offers and its operating plan through the operating day</b>, on ERCOT's real prices, forecasts and notices as each was posted, settled by ERCOT's rules. The ladder adds one kind of realism a version: v2 trades energy at the battery's own node, v3 adds reserves and co-located solar, v4 three-day weather fronts.${X ? ` Apart from the ladder, the ${esc(X.label)} plays ${X.check_of}'s days again with the day-ahead market re-cleared against the desk's own offers.` : ""} ${n} recorded runs: GPT-6.1 Sol and GPT-6 Luna at high reasoning effort and an untrained Qwen3-4B with thinking off, each against the anchor, the hindsight optimum and the battery's real operator.`;
  $("findings").innerHTML = findings(D).map((x, i) => `<li${i ? "" : ' class="lead"'}>${x}</li>`).join("");
  const tab = (x) => `<a href="?v=${x.version}#tabs" data-v="${x.version}" class="${[x === V ? "on" : "", isCheck(x) ? "check" : ""].join(" ").trim()}"${x === V ? ' aria-current="true"' : ""}><b>${title(x)}</b><small>${isCheck(x) ? `${x.check_of}'s ${x.n_tasks} ${unit(x)}s, re-cleared` : `${x.n_tasks} real ${unit(x)}s`}</small></a>`;
  const where = `${V.sites.length} real batteries (${esc(V.sites.map((s) => s.region).join(", "))}) ${V.days_per_task > 1 ? `across ${blocks(V)}` : `on ${V.n_days} days`} from ${day(V.dates[0])} to ${day(lastDay(V))}`;
  const intro = B ? `Not a step on the ladder: ${B.version}'s ${V.n_tasks} ${unit(V)}s again, ${where}, with the same tools, grading and models, and each day-ahead market re-cleared after the desk's own curves join ERCOT's offer stack for that day, disclosed 60 days later. It checks the price-taker assumption the ladder makes. Pre-registered as ${V.version}, ${esc(V.name)}.`
    : `${esc(cap(V.adds))}. The desk ${esc(V.does)}. ${V.n_tasks} ${unit(V)}s: ${where}.`;
  const boardBlock = block("The board", `Each model played each ${unit(V)} once under pre-registered settings. C is the share of the hindsight optimum's profit over idle; P the battery's settled ERCOT statement a ${unit(V)}; R, second to C, the environment's reward (idle 0.2, the anchor 1.0). Brackets: ${V.block}-block bootstrap 95% CIs over ${blocks(V)}.`, board(V));
  const rest = [
    block("Where the money came from", `Each line of the settled statement, mean $ a ${unit(V)}. DAM energy settles at the node's day-ahead price, RT imbalance at its 15-minute real-time price; modelled lines are marked.`, linesTable(V)),
    reserves(V),
    block("How each desk traded", `Means per ${unit(V)}: turns are wake-ups the model acted on, calls its tool calls, submissions the DAM curves, RT curves and COP updates it filed (rejections carry ERCOT-style codes).`, behaviour(V)),
    replays(V, C),
    settingsBlock(D),
    how(),
    sources(V),
  ];
  $("main").innerHTML = [
    acrossBlock(D, W),
    `<nav class="vtabs" id="tabs" aria-label="Versions">${L.map(tab).join("")}${X ? tab(X) : ""}</nav>`,
    `<div class="version${B ? " check" : ""}"><div class="vhead"><h2>${title(V)}</h2><p>${intro}</p></div><div class="kpis">${B ? checkKpis(V, B) : kpis(V)}</div></div>`,
    ...(B ? [impact(V, W), versus(V, B), boardBlock, capFig(V, W), usdFig(V, W), sensitivity(V)] : [boardBlock, capFig(V, W), usdFig(V, W), sensitivity(V)]),
    ...rest,
  ].join("");
}

const cap = (s) => s[0].toUpperCase() + s.slice(1);

function pagetabs(bench) {
  const a = (href, on, b, s) => `<a href="${href}"${on ? ' aria-current="page"' : ""}><b>${b}</b><small>${s}</small></a>`;
  $("pagetabs").innerHTML = a("?v=bench", bench, "The v4 benchmark", "models in native agent harnesses") + a("?v=v4", !bench, "The development ladder", "v2 to v4 and the v5 price-impact check");
}

const BCOL = { opus: "var(--c-opus)", sol: "var(--c-sol)", luna: "var(--c-luna)", qwen: "var(--c-qwen)" };
const busd = (x) => (x < 100 ? `$${x.toFixed(2)}` : `$${whole(x).toLocaleString("en-US")}`);
const isoPlus = (iso, n) => new Date(Date.parse(`${iso}T12:00:00Z`) + n * 864e5).toISOString().slice(0, 10);
const spanOf = (a, b) => {
  const f = (iso, o) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-GB", { ...o, timeZone: "UTC" });
  return a.slice(5, 7) === b.slice(5, 7) ? `${f(a, { day: "numeric" })} to ${f(b, { day: "numeric", month: "long", year: "numeric" })}` : `${f(a, { day: "numeric", month: "long" })} to ${f(b, { day: "numeric", month: "long", year: "numeric" })}`;
};

async function cardCharts() {
  if (!document.querySelector('link[href="./card-charts.css"]')) {
    const l = Object.assign(document.createElement("link"), { rel: "stylesheet", href: "./card-charts.css" });
    const done = new Promise((r) => (l.onload = l.onerror = r));
    document.head.append(l);
    await done;
  }
  if (!$("ruler")) document.body.insertAdjacentHTML("beforeend", '<svg id="ruler" class="chart" aria-hidden="true" style="position:absolute;left:0;top:0;width:0;height:0;overflow:hidden;visibility:hidden"></svg>');
  return import("./card-charts.js");
}

async function benchPage(D, C) {
  const [B, F, K] = await Promise.all([fetch("./bench.json").then((r) => r.json()), import("./fmt.js"), cardCharts()]);
  await document.fonts.ready;
  return () => renderBench(B, C, D, F.pc, K);
}

function renderBench(B, C, D, pc, K) {
  TIPS.length = 0;
  pagetabs(true);
  const W = Math.max(280, Math.min(1080, $("main").clientWidth) - (innerWidth < 720 ? 24 : 44)), narrow = W < 560;
  const ms = B.order_by_C.map((k) => B.models[k]), refs = B.references, card = B.card, L = B.links, sides = card.sides;
  const n = (x) => pc(x).slice(0, -1);
  const sp = (x) => (x > 0 && n(x) !== "0.0" ? `+${n(x)}` : n(x));
  const cci = (b) => `[${n(b.ci[0])}, ${n(b.ci[1])}]`;
  const h = B.hero, e = C?.episodes[`bench/${h.task_id}.${h.model}`], t = C?.tasks[h.task_id], hm = B.models[h.model];
  const front = (f) => B.fronts.find((x) => x.front === f);
  $("title").textContent = "The v4 benchmark: models in native agent harnesses";
  document.title = "The v4 benchmark · GridSimEnv Desk";
  $("lede").innerHTML = `${md(card.pitch.replace(/\*\*/g, ""))}${e ? ` <a href="./index.html?v=bench&m=${h.model}&task=${h.task_id}"><b>Replay the lead run</b></a>: ${esc(hm.name)} in ${esc(hm.harness)} trades ${esc(t.name)} (${esc(t.region)}, ${esc(t.size)}) over ${spanOf(t.dates[0], t.dates.at(-1))}, through a ${esc(front(e.front).kind)}, ${e.split === "post_cutoff" ? "after every model's training cutoff" : "a window that may be in the models' training data"}, and settles at ${usd(e.P)}, C ${pc(e.C)}.` : ""}`;
  $("findings").innerHTML = card.bullets.map((x, i) => `<li${i ? "" : ' class="lead"'}>${md(x)}</li>`).join("");
  const fig = (svg, label) => `<div class="cardfig" role="figure" aria-label="${esc(label)}">${svg}</div>`;
  const who_ = (m) => who(BCOL[m.key] || "var(--c-hind)", `<b>${esc(m.name)}</b>`, `${esc(m.harness)} · ${esc(m.setting)}<br>${busd(m.cost.usd_per_window)} a window${m.cost.basis === "gpu_time" ? ", GPU time" : ""} · ${busd(m.cost.usd_all_attempts)} in all${m.n === B.n_windows ? "" : ` · ${m.n} of ${B.n_windows} windows`}`);
  const cell = (l, b, bold = false) => `<td data-l="${esc(l)}">${b.mean == null ? "–" : `${bold ? `<b>${pc(b.mean)}</b>` : pc(b.mean)}<span class="sub">${cci(b)}</span>`}</td>`;
  const cols = [[`C, all ${B.n_windows} windows`, "all"], ...["pre_cutoff", "post_cutoff"].map((k) => [`${sides[k].label}`, k])];
  const board = `<div class="table-scroll"><table class="grid stack wrapcells bboard"><thead><tr><th class="l">Model</th>${cols.map(([l, k]) => `<th>${esc(l)}${k === "all" ? "" : `<span class="sub">${esc(sides[k].note)}</span>`}</th>`).join("")}<th>R</th><th>P a window</th></tr></thead><tbody>
    ${ms.map((m) => `<tr><td>${who_(m)}</td>${cols.map(([l, k]) => cell(k === "all" ? l : `${l}, ${sides[k].note}`, m[k].C, k === "all")).join("")}<td data-l="R">${num(m.all.R.mean, 2)}<span class="sub">${ci(m.all.R.ci, 2)}</span></td><td data-l="P a window">${usd(m.all.P.mean)}<span class="sub">${usdci(m.all.P.ci)}</span></td></tr>`).join("")}
    ${Object.entries(card.refs).map(([k, label]) => `<tr class="ref"><td>${who(REFC[k], esc(label))}</td>${cols.map(([l, s]) => cell(s === "all" ? l : `${l}, ${sides[s].note}`, refs[k][s].C)).join("")}<td class="na" data-l="R">–</td><td data-l="P a window">${usd(refs[k].all.P.mean)}<span class="sub">${usdci(refs[k].all.P.ci)}</span></td></tr>`).join("")}</tbody></table></div>
    <p class="note">${md(card.captions.table)}</p>${(B.deferred || []).map((x) => `<p class="note">${md(x)}</p>`).join("")}
    <p class="note">The hindsight optimum earns ${usd(refs.hind.all.P.mean)} a window ${usdci(refs.hind.all.P.ci)}, the best the rules allow with every price known in advance; idle earns ${usd(refs.idle.all.P.mean)}. R is the contract's reward: the anchor 1.0, idle 0.2.</p>`;
  const gapRow = (b, l) => `<td data-l="${l}">${b ? `${sp(b.mean)}<span class="sub">[${sp(b.ci[0])}, ${sp(b.ci[1])}]</span>` : "–"}</td>`;
  const name = (k) => (B.models[k] ? B.models[k].name : card.refs[k]);
  const pairs = Object.entries(B.paired).map(([k, p]) => ({ k, a: p.a || k.split("-")[0], b: p.b || k.split("-")[1], ...p.all }));
  const paired = `<div class="table-scroll"><table class="grid stack wrapcells bpairs"><thead><tr><th class="l">Paired gap, a − b</th><th>Δ C, pts</th><th>Δ R</th><th>Δ P a window</th><th>a ahead</th><th>Fronts a leads</th></tr></thead><tbody>${pairs.map((p) => `<tr${B.models[p.b] ? "" : ' class="ref"'}><td><b>${esc(name(p.a))}</b> − ${esc(name(p.b))}</td>${gapRow(p.C, "Δ C, pts")}<td data-l="Δ R">${p.R ? `${sgn(p.R.mean, 2)}<span class="sub">${sci(p.R.ci, 2)}</span>` : "–"}</td><td data-l="Δ P a window">${usd(p.P.mean, true)}<span class="sub">${usdci(p.P.ci, true)}</span></td><td data-l="a ahead">${pct(p.C.ahead)}</td><td data-l="Fronts a leads">${p.C.fronts_ahead} of ${p.C.fronts}</td></tr>`).join("")}</tbody></table></div>`;
  const gaps = `<div class="table-scroll"><table class="grid stack wrapcells bgaps"><thead><tr><th class="l">Model</th><th>Δ C, pts</th><th>Δ R</th><th>Δ P a window</th></tr></thead><tbody>${ms.map((m) => `<tr><td>${who(BCOL[m.key], `<b>${esc(m.name)}</b>`, esc(m.harness))}</td>${gapRow(m.split_gap.C, "Δ C, pts")}<td data-l="Δ R">${sgn(m.split_gap.R.mean, 2)}<span class="sub">${sci(m.split_gap.R.ci, 2)}</span></td><td data-l="Δ P a window">${usd(m.split_gap.P.mean, true)}<span class="sub">${usdci(m.split_gap.P.ci, true)}</span></td></tr>`).join("")}</tbody></table></div>`;
  const runs = C ? Object.entries(C.episodes).filter(([, x]) => x.version === "bench") : [], named = C?.versions.find((x) => x.role === "bench")?.names || {};
  const sites = [...new Set(B.sites)].sort();
  const cellR = (f, s) => {
    const here = runs.filter(([, x]) => x.front === f.front && C.tasks[x.task].site === s).sort(([, a], [, b]) => B.order_by_C.indexOf(a.model) - B.order_by_C.indexOf(b.model));
    if (!here.length) return "<td></td>";
    const tk = C.tasks[here[0][1].task], own = tk.dates[0] !== f.front ? `<small>${esc(spanOf(tk.dates[0], tk.dates.at(-1)).replace(/ \d{4}$/, ""))}</small>` : "";
    return `<td class="rp" data-l="${esc(`${tk.name}, ${tk.region}`)}">${own}<div class="chips">${here.map(([k, x]) => `<a href="./index.html?v=bench&m=${x.model}&task=${x.task}" title="${esc(`${B.models[x.model].name} on ${tk.name}, ${spanOf(tk.dates[0], tk.dates.at(-1))}: C ${pc(x.C)}, P ${usd(x.P)}${x.valid ? "" : ", no valid submission"}`)}"${k === C.lead ? ' class="lead"' : ""}><i style="background:${BCOL[x.model]}"></i>${pc(x.C)}</a>`).join("")}</div></td>`;
  };
  const replaysB = !runs.length ? "" : block("Every run, replayed", `Each link opens that model's run on the battery site in 3D beside its desk, with its hindsight capture C. Rows are the ${B.n_fronts} weather fronts, ${esc(sides.pre_cutoff.label)} first.`,
    `<div class="legend">${ms.map((m) => `<span><i class="sw" style="background:${BCOL[m.key]}"></i><span class="lab">${esc(m.name)}<small> · ${esc(m.harness)}</small></span></span>`).join("")}</div><div class="table-scroll"><table class="grid replays breplays"><thead><tr><th></th>${sites.map((s) => { const tk = Object.values(C.tasks).find((x) => x.site === s); return `<th>${esc(tk.name)}<small>${esc(tk.region)}, ${esc(tk.size)}</small></th>`; }).join("")}</tr></thead><tbody>${B.fronts.map((f) => `<tr><th scope="row"><i class="side ${f.split}"></i>${esc(spanOf(f.front, isoPlus(f.front, 2)).replace(/ \d{4}$/, ""))}<small>${esc(f.kind)}${named[f.front] ? `, ${esc(named[f.front])}` : ""}</small></th>${sites.map((s) => cellR(f, s)).join("")}</tr>`).join("")}</tbody></table></div>`, "", "replays");
  const ladder = D.versions.filter((v) => v.role === "ladder"), checkV = D.versions.find(isCheck);
  $("main").innerHTML = [
    block("", "", `${fig(K.splitsChart(B, Math.min(W, narrow ? W : 760), narrow), "Hindsight capture before and after the training cutoffs")}<p class="note">${md(card.captions.splits)}</p><p class="note">${md(B.text.rule)}</p><h3 class="minor">Post-cutoff minus pre-cutoff, each model</h3><p class="note">The halves hold different windows, so each half's fronts are drawn apart (a stratified block bootstrap).</p>${gaps}`, "", "halves"),
    block("The board", `Each model ran each of the ${B.n_windows} windows once, in its native agent harness. C is the share of the hindsight optimum's profit over idle, the headline; R the contract's reward; P the settled ERCOT statement a window. Brackets: 95% CIs, a block bootstrap over the ${B.n_fronts} weather fronts (each half's 4 within it).`, board, "", "board"),
    block("Paired by window", `Each gap a − b over the ${B.n_windows} windows both played, with front-block 95% CIs; <i>a ahead</i> is the share of windows where a's C is higher, and <i>fronts a leads</i> counts the fronts on which a's mean C is higher.`, paired, "", "paired"),
    replaysB,
    block("How it runs", "", `<ul class="models">${card.how.map((x) => `<li>${md(x)}</li>`).join("")}</ul>`),
    block("Known limitations of the benchmark", "", `<ul class="models">${card.limits.map((x) => `<li>${md(x)}</li>`).join("")}</ul>`),
    block("Deviations from the pre-registration", `Logged after the runs and appended to the pre-registration at the tag <code>${esc(L.tag)}</code>: ${link(L.deviations, "its Deviations section")}.`, `<ul class="models">${B.deviations.map((x) => `<li>${md(x)}</li>`).join("")}</ul>`, "", "deviations"),
    block("Every number's source", "", `<div class="links-grid">
      <div><h3>On GitHub</h3><ul><li>${link(L.prereg, "The pre-registration")}, <code>docs/prereg/v4-bench.md</code> at <code>${esc(L.run_tag)}</code></li><li>${link(L.deviations, "Its deviations")} at <code>${esc(L.tag)}</code></li><li>${link(L.folder, "The results folder")}, <code>results/desk-v4-bench</code> at <code>${esc(L.tag)}</code></li></ul></div>
      <div><h3>On the dataset</h3><ul><li>${link(L.dataset, "<code>results/desk-v4-bench</code>")}: its README, <code>summary.json</code>, <code>grades.jsonl.gz</code> and every scored Episode JSON</li><li>config <code>desk_v4_bench</code>, splits <code>pre_cutoff</code> and <code>post_cutoff</code></li></ul></div>
      <div><h3>Settings</h3><ul><li>max_turns ${B.run.budget.max_turns}, calls_per_turn ${B.run.budget.calls_per_turn}, max_reminders ${B.run.budget.max_reminders}</li><li>core ${esc(B.run.core_versions.join(", "))}, bundle <code>${esc(B.run.bundle)}</code></li><li>${esc(B.ci.method)}, ${B.ci.resamples.toLocaleString("en-US")} resamples, seed ${B.ci.seed}</li></ul></div></div>`),
    block("The development ladder", `Before the benchmark, the desk's own runner played GPT-6.1 Sol and GPT-6 Luna at high reasoning effort and an untrained Qwen3-4B with thinking off up a ladder of versions, each adding one kind of realism, and through a price-impact check. ${D.across ? esc(D.across) : ""}`,
      `<nav class="vtabs ladder" aria-label="Development versions">${ladder.map((v) => `<a href="?v=${v.version}"><b>${v.version} ${esc(v.name)}</b><small>${v.n_tasks} real ${unit(v)}s</small></a>`).join("")}${checkV ? `<a href="?v=${checkV.version}" class="check"><b>${esc(checkV.label)}</b><small>${checkV.check_of}'s ${checkV.n_tasks} ${unit(checkV)}s, re-cleared</small></a>` : ""}</nav>`, "", "ladder"),
  ].join("");
}

function findings(D) {
  const L = D.versions.filter((v) => v.role === "ladder"), X = D.versions.find(isCheck), out = [];
  const nm = (k) => (D.versions.flatMap((v) => v.models).find((m) => m.key === k) || {}).name || k;
  if (D.across) out.push(`<b>Up the ladder.</b> ${esc(D.across)}`);
  if (X) {
    const B = D.versions.find((v) => v.version === X.check_of), pi = X.price_impact, m = (k) => X.models.find((q) => q.key === k);
    const lead = pi.sol ? "sol" : Object.keys(pi)[0], top = Object.keys(pi).reduce((a, k) => (pi[k].max_abs_usd_per_mwh > pi[a].max_abs_usd_per_mwh ? k : a));
    const tie = X.paired.find((p) => p.a === "sol" && p.b === "luna" && p.C)?.C;
    out.push(`<b>The ${esc(X.label)} reproduces ${B.version}.</b> Re-cleared against ERCOT's offer stack, ${esc(nm(lead))}'s own day-ahead offers moved the price ${cents(pi[lead].sales_mwh_weighted_usd_per_mwh)}/MWh on its sales, at most $${pi[top].max_abs_usd_per_mwh.toFixed(2)}/MWh in any hour, about ${usd(pi[lead].revenue_effect_usd_per_episode, true)} a battery-day.${noise(X) ? ` Every paired ${X.version} − ${B.version} gap is within noise` : ""}${tie && tie.ci[0] <= 0 && tie.ci[1] >= 0 ? `${noise(X) ? ", and" : ""} ${esc(nm("luna"))}'s ${cp(m("luna").C.mean)} against ${esc(nm("sol"))}'s ${cp(m("sol").C.mean)} is a statistical tie` : ""}. A fleet desk, a QSE trading a portfolio of batteries, is where price impact would matter.`);
  }
  const op = (v, k) => v.models.find((q) => q.key === k)?.P_minus_operator_replay;
  const ahead = L.filter((v) => ["sol", "luna"].every((k) => op(v, k)?.ci?.[0] > 0)), behind = L.filter((v) => op(v, "qwen")?.ci?.[1] < 0);
  if (ahead.length || behind.length) out.push(`<b>Against the battery's real operator</b>, its own disclosed bids replayed through the same clearing and settlement: ${ahead.length ? `${esc(nm("sol"))} and ${esc(nm("luna"))} are ahead with a CI above zero only in ${and(ahead.map((v) => v.version))}` : "no model is ahead with a CI above zero"}${behind.length ? `; ${esc(nm("qwen"))} is behind with a CI below zero in ${and(behind.map((v) => v.version))}` : ""}.`);
  return out;
}

function acrossBlock(D, W) {
  const L = D.versions.filter((v) => v.role === "ladder"), X = D.versions.find(isCheck), B = X && D.versions.find((v) => v.version === X.check_of);
  if (L.length < 2) return "";
  const OP = "operator_replay", narrow = W < 620;
  const keys = ORDER.filter((k) => L.some((v) => v.models.some((m) => m.key === k)));
  const get = (v, k) => v.models.find((m) => m.key === k) || v.references.find((r) => r.key === k);
  const f1 = (v) => Math.round(v * 10) / 10;
  const T = (x, y, s, cls, a = "start") => `<text x="${f1(x)}" y="${f1(y)}" class="${cls}"${a === "start" ? "" : ` text-anchor="${a}"`}>${s}</text>`;
  const path = (p) => p.map(([x, y], i) => `${i ? "L" : "M"}${f1(x)},${f1(y)}`).join("");
  const mk = (x, y, k) => `<circle cx="${f1(x)}" cy="${f1(y)}" r="${k === "sol" ? 6 : 5}" fill="${COL[k]}" class="mk"/>`;
  const hits = [];
  const hit = (x, y, head, rows) => hits.push(`<circle cx="${f1(x)}" cy="${f1(y)}" r="11" class="hit" ${tip(tipRows(head, rows))}/>`);
  const vals = [...L, ...(X ? [X] : [])].flatMap((v) => [...keys.map((k) => get(v, k)?.C.mean), get(v, OP)?.C.mean]).filter((x) => x != null);
  const lo = Math.min(-0.04, Math.floor((Math.min(...vals) - 0.015) * 50) / 50), hi = Math.ceil((Math.max(...vals) + 0.03) * 20) / 20;
  const top = 26, bottom = top + (narrow ? 230 : 280), y = lin(lo, hi, bottom, top);
  const tk = [];
  for (let t = Math.ceil(lo * 10 - 1e-9) / 10; t <= hi + 1e-9; t = Math.round((t + 0.1) * 10) / 10) tk.push(t);
  const tickW = Math.max(...tk.map((t) => measure(`${Math.round(t * 100)}%`, "t-ax"))), left = tickW + 12;
  const last = L.at(-1);
  const ends = narrow ? [] : [...keys.map((k) => ({ c: get(last, k).C.mean, name: [MS[k].name, MS[k].setting], b: k === "sol" })), ...(get(last, OP) ? [{ c: get(last, OP).C.mean, name: ["Real operator", "(bids replayed)"], op: true }] : [])];
  const endW = ends.length ? Math.max(...ends.map((e) => measure(cp(e.c), "t-end-v") + 7 + Math.max(measure(e.name[0], e.b ? "t-end b" : "t-end"), measure(e.name[1], "t-end-q")))) + 12 : 0;
  const checkW = X && !narrow ? Math.max(250, Math.min(300, W * 0.28)) : 0;
  const R = W - checkW - endW - (checkW ? 28 : 0) - 6, pad = narrow ? 44 : 54;
  const xs = L.map((_, i) => left + pad + ((R - left - 2 * pad) * i) / (L.length - 1));
  let s = tk.map((t) => `<line x1="${f1(left)}" x2="${f1(R + (narrow ? 0 : 10))}" y1="${f1(y(t))}" y2="${f1(y(t))}" class="${t ? "gl" : "zl"}"/>${T(left - 8, y(t) + 4, `${minus(String(Math.round(t * 100)))}%`, "t-ax", "end")}`).join("");
  const gap = Math.min(...xs.slice(1).map((x, i) => x - xs[i]));
  const xl = L.map((v) => (narrow ? wrapText(v.name, "t-ax", Math.min(gap - 8, 140)) : [v.name]));
  L.forEach((v, i) => {
    s += T(xs[i], bottom + 21, v.version, "t-xv", "middle") + xl[i].map((l, j) => T(xs[i], bottom + 37 + j * 14, esc(l), "t-ax", "middle")).join("");
    if (v.days_per_task > 1) s += T(xs[i], bottom + 37 + xl[i].length * 14, `${v.days_per_task}-day windows`, "t-ax", "middle");
  });
  const series = keys.map((k) => ({ k, m: L.map((v) => get(v, k)) })).map((sr) => ({ ...sr, p: sr.m.map((m, i) => [xs[i], y(m.C.mean)]) }));
  const opPts = L.map((v, i) => (get(v, OP) ? [xs[i], y(get(v, OP).C.mean)] : null)).filter(Boolean);
  s += `<path class="op" d="${path(opPts)}"/>${opPts.map(([x, yy]) => `<circle cx="${f1(x)}" cy="${f1(yy)}" r="3" class="op-dot"/>`).join("")}`;
  L.forEach((v, i) => { const r = get(v, OP); if (r) hit(xs[i], y(r.C.mean), `${v.version} ${esc(OPNAME)}`, [["C", cp(r.C.mean)], [`P a ${unit(v)}`, usd(r.P.mean)]]); });
  for (const sr of [...series].reverse()) {
    s += `<path class="ln${sr.k === "sol" ? " b" : ""}" d="${path(sr.p)}" stroke="${COL[sr.k]}"/>${sr.p.map(([x, yy]) => mk(x, yy, sr.k)).join("")}`;
    sr.m.forEach((m, i) => hit(xs[i], y(m.C.mean), `${L[i].version} ${esc(labelOf(sr.k))}`, [["C", `${cp(m.C.mean)} ${ptsci(m.C.ci)}`], [`P a ${unit(L[i])}`, `${usd(m.P.mean)} ${usdci(m.P.ci)}`]]));
  }
  const placed = [...tk.map((t) => [left - 8 - tickW, y(t) - 7, left - 4, y(t) + 5]), ...series.flatMap((sr) => sr.p.map(([x, yy]) => [x - 7, yy - 7, x + 7, yy + 7])), ...opPts.map(([x, yy]) => [x - 4, yy - 4, x + 4, yy + 4])];
  const samples = [];
  for (const p of [...series.map((sr) => sr.p), opPts]) for (let i = 1; i < p.length; i++) {
    const [ax, ay] = p[i - 1], [bx, by] = p[i], k = Math.ceil(Math.hypot(bx - ax, by - ay) / 3);
    for (let j = 0; j <= k; j++) samples.push([ax + ((bx - ax) * j) / k, ay + ((by - ay) * j) / k]);
  }
  const cost = (b) => samples.filter(([px, py]) => px > b[0] - 2 && px < b[2] + 2 && py > b[1] - 2 && py < b[3] + 2).length
    + placed.reduce((a, o) => { const ov = Math.max(0, Math.min(b[2], o[2]) - Math.max(b[0], o[0])) * Math.max(0, Math.min(b[3], o[3]) - Math.max(b[1], o[1])); return a + (ov ? 40 + ov : 0); }, 0)
    + (b[0] < 0 || b[2] > (narrow ? W : R + 8) || b[1] < top - 22 || b[3] > bottom + 6 ? 500 : 0);
  for (const sr of series) sr.p.forEach(([x, yy], i) => {
    if (!narrow && i === L.length - 1) return;
    const text = cp(sr.m[i].C.mean), cls = sr.k === "sol" ? "t-val b" : "t-val", w = measure(text, cls), h = 13, g = (sr.k === "sol" ? 6 : 5) + 4;
    const nb = [sr.p[i - 1]?.[1], sr.p[i + 1]?.[1]].filter((q) => q != null);
    const pref = nb.every((q) => q > yy) ? 0 : nb.every((q) => q < yy) ? 1 : -1;
    const best = [["middle", 0, -g], ["middle", 0, g + h - 2], ["start", g + 2, h / 2 - 2], ["end", -g - 2, h / 2 - 2], ["start", g - 2, -g + 1], ["end", -g + 2, -g + 1], ["start", g - 2, g + h - 3], ["end", -g + 2, g + h - 3]].map(([a, dx, dy], j) => {
      const tx = x + dx, ty = yy + dy, bx = a === "middle" ? tx - w / 2 : a === "start" ? tx : tx - w;
      const b = [bx, ty - h * 0.8, bx + w, ty + h * 0.2];
      return { a, tx, ty, b, sc: cost(b) + (j === pref ? 0 : j < 2 ? 0.7 : 1.4 + j * 0.15) };
    }).reduce((a, c) => (c.sc < a.sc ? c : a));
    placed.push(best.b);
    s += T(best.tx, best.ty, text, cls, best.a);
  });
  if (ends.length) {
    const ex = R + 18, items = ends.map((e) => ({ ...e, y: y(e.c) + 4 })).sort((a, b) => a.y - b.y);
    for (let i = 1; i < items.length; i++) if (items[i].y - items[i - 1].y < 30) items[i].y = items[i - 1].y + 30;
    const over = items.at(-1).y - (bottom + 8);
    if (over > 0) items.forEach((it) => (it.y -= over));
    for (const it of items) {
      const vw = measure(cp(it.c), "t-end-v");
      s += T(ex, it.y, cp(it.c), `t-end-v${it.op ? " t-op" : ""}`) + T(ex + vw + 7, it.y, esc(it.name[0]), `t-end${it.b ? " b" : ""}${it.op ? " t-op" : ""}`);
      if (it.name[1]) s += T(ex + vw + 7, it.y + 14, esc(it.name[1]), "t-end-q");
    }
  }
  let H = bottom + 37 + 14 * Math.max(...L.map((v, i) => xl[i].length + (v.days_per_task > 1 ? 1 : 0)));
  if (X) {
    const x0 = narrow ? 0 : W - checkW, x1 = W;
    if (!narrow) s += `<line x1="${f1(x0 - 14)}" x2="${f1(x0 - 14)}" y1="${f1(top - 14)}" y2="${f1(bottom + 46)}" class="sep"/>`;
    const ttop = narrow ? H + 40 : top - 2;
    const subl = wrapText(`${B.version}'s ${X.n_tasks} ${unit(X)}s again, each day-ahead market re-cleared with the desk's own offers`, "t-ck-s", x1 - x0 - 4);
    s += T(x0, ttop, esc(X.label), "t-ck") + subl.map((l, j) => T(x0, ttop + 17 + j * 15, esc(l), "t-ck-s")).join("");
    const ptop = ttop + 17 + subl.length * 15 + 20, pbot = narrow ? ptop + 150 : bottom;
    const cv = [B, X].flatMap((v) => [...keys.map((k) => get(v, k).C.mean), get(v, OP)?.C.mean ?? 0]);
    const yc = narrow ? lin(Math.min(0, ...cv) - 0.01, Math.max(...cv) + 0.01, pbot, ptop) : y;
    const lw = Math.max(...keys.map((k) => measure(cp(get(B, k).C.mean), "t-val b"))) + 14;
    const rw = Math.max(...keys.map((k) => measure(`${cp(get(X, k).C.mean)} ${NICK[k]}`, "t-val b"))) + 16;
    const xa = x0 + lw, xb = Math.min(x1 - rw, xa + (narrow ? 170 : 130));
    if (narrow) s += `<line x1="${f1(x0)}" x2="${f1(x1)}" y1="${f1(yc(0))}" y2="${f1(yc(0))}" class="zl"/>${T(x0, yc(0) - 5, "0%", "t-ax")}`;
    const ob = get(B, OP), ox = get(X, OP);
    if (ob && ox) {
      s += `<path class="op" d="M${f1(xa)},${f1(yc(ob.C.mean))}L${f1(xb)},${f1(yc(ox.C.mean))}"/><circle cx="${f1(xa)}" cy="${f1(yc(ob.C.mean))}" r="3" class="op-dot"/><circle cx="${f1(xb)}" cy="${f1(yc(ox.C.mean))}" r="3" class="op-dot"/>`;
      hit(xa, yc(ob.C.mean), `${B.version} ${esc(OPNAME)}`, [["C", cp(ob.C.mean)], [`P a ${unit(B)}`, usd(ob.P.mean)]]);
      hit(xb, yc(ox.C.mean), `${esc(X.label)}: ${esc(OPNAME)}`, [["C", cp(ox.C.mean)], [`P a ${unit(X)}`, usd(ox.P.mean)]]);
    }
    for (const k of [...keys].reverse()) {
      const a = get(B, k), b = get(X, k), d = X.versus.models[k];
      s += `<path class="ln${k === "sol" ? " b" : ""}" d="M${f1(xa)},${f1(yc(a.C.mean))}L${f1(xb)},${f1(yc(b.C.mean))}" stroke="${COL[k]}"/>${mk(xa, yc(a.C.mean), k)}${mk(xb, yc(b.C.mean), k)}`;
      hit(xa, yc(a.C.mean), `${B.version} ${esc(labelOf(k))}`, [["C", `${cp(a.C.mean)} ${ptsci(a.C.ci)}`], [`P a ${unit(B)}`, usd(a.P.mean)]]);
      hit(xb, yc(b.C.mean), `${esc(X.label)}: ${esc(labelOf(k))}`, [["C", `${cp(b.C.mean)} ${ptsci(b.C.ci)}`], [`P a ${unit(X)}`, usd(b.P.mean)], ...(d ? [[`${X.version} − ${B.version}, paired`, `${pts(d.C.mean, true)} pts ${ptsci(d.C.ci)}`]] : [])]);
    }
    const dodge = (its) => { its.sort((p, q) => p.y - q.y); for (let i = 1; i < its.length; i++) if (its[i].y - its[i - 1].y < 15) its[i].y = its[i - 1].y + 15; return its; };
    for (const it of dodge(keys.map((k) => ({ k, y: yc(get(B, k).C.mean) + 4 })))) s += T(xa - 11, it.y, cp(get(B, it.k).C.mean), it.k === "sol" ? "t-val b" : "t-val", "end");
    for (const it of dodge(keys.map((k) => ({ k, y: yc(get(X, k).C.mean) + 4 })))) s += `<text x="${f1(xb + 11)}" y="${f1(it.y)}" class="${it.k === "sol" ? "t-val b" : "t-val"}">${cp(get(X, it.k).C.mean)}<tspan class="t-ck-s" dx="5">${NICK[it.k]}</tspan></text>`;
    s += T(xa, pbot + 21, B.version, "t-xv", "middle") + T(xb, pbot + 21, X.version, "t-xv", "middle") + T(xa, pbot + 37, "as run", "t-ax", "middle") + T(xb, pbot + 37, "re-cleared", "t-ax", "middle");
    if (narrow) H = pbot + 44;
  }
  H = Math.ceil(H + 6);
  const legend = narrow ? `<div class="legend">${keys.map(keyM).join("")}<span><i class="ln op"></i>${esc(OPNAME)}</span></div>` : "";
  const cols = [...L, ...(X ? [X] : [])];
  const cell = (v, k) => { const m = get(v, k); return `<td data-l="${title(v)}"${isCheck(v) ? ' class="ck"' : ""}>${m ? `${cp(m.C.mean)}${m.C.ci && m.kind !== "ref" && v.models.includes(m) ? `<span class="sub">${ptsci(m.C.ci)}</span>` : ""}` : "–"}</td>`; };
  const tr = [...keys.map((k) => `<tr><td>${whoM(k)}</td>${cols.map((v) => cell(v, k)).join("")}</tr>`),
    `<tr class="ref"><td>${who("var(--c-op)", esc(OPNAME))}</td>${cols.map((v) => cell(v, OP)).join("")}</tr>`].join("");
  return block("Up the ladder: hindsight capture, v2 to v4", `C, the share of the hindsight optimum's profit over idle, for each model in each version of the ladder; the battery's real operator, its own disclosed bids replayed through the same clearing and settlement, is dashed.${X ? ` Apart from the ladder, the ${esc(X.label)} plays ${B.version}'s ${unit(X)}s again with the day-ahead market re-cleared, drawn beside ${B.version}'s values.` : ""} Hover a point for its 95% CI; the table has them all.`,
    `${legend}<div class="chart">${svg(W, H, s + hits.join(""), "Hindsight capture by model up the ladder, and the price-impact check beside it")}</div><div class="table-scroll"><table class="grid stack across"><thead><tr><th class="l">Desk</th>${cols.map((v) => `<th${isCheck(v) ? ' class="ck"' : ""}>${title(v)}</th>`).join("")}</tr></thead><tbody>${tr}</tbody></table></div><p class="note">C in % with its 95% ${L[0].block}-block bootstrap CI in brackets (fronts in v4).${X ? ` The ${esc(X.label)} is ${B.version}'s days re-cleared, not a fourth step; its paired gaps to ${B.version} are on its board.` : ""}</p>`, "", "across");
}

function kpis(V) {
  const m = V.models.find((x) => x.key === "sol") || V.models[0], refs = Object.fromEntries(V.references.map((r) => [r.key, r]));
  const g = m.P_minus_anchor, o = m.P_minus_operator_replay, a = refs.anchor;
  const tile = (v, cls, l, t) => `<div class="kpi"><div class="v ${cls}">${v}</div><div class="l">${l}</div><div class="t">${t}</div></div>`;
  const sign = (b) => (b.ci[0] > 0 ? "pos" : b.ci[1] < 0 ? "neg" : "");
  return [
    tile(num(m.C.mean), "", `of the hindsight optimum, <span class="nw">${esc(labelOf(m.key))}</span>`, `C ${ci(m.C.ci)}; ${usd(m.P.mean)} a ${unit(V)}. The anchor captures ${num(a.C.mean)}.`),
    o.mean == null ? tile("–", "", "against the real operator", "No operator disclosure for these days.") :
      tile(usd(o.mean, true), sign(o), `a ${unit(V)} against the real operator's bids`, `${usdci(o.ci, true)}${o.ci[0] <= 0 && o.ci[1] >= 0 ? ", a CI that includes zero" : ""}. Its bids, disclosed by ERCOT 60 days later and replayed through the same clearing and settlement, earn ${usd(refs.operator_replay.P.mean)} a ${unit(V)}.`),
    tile(usd(g.mean, true), sign(g), `a ${unit(V)} against the anchor`, `${usdci(g.ci, true)}; ahead on ${pct(m.beats_anchor)} of ${unit(V)}s. The anchor is the desk's own optimiser on the same information${((V.sensitivity || {}).bought_back || []).includes("anchor") ? "; its DAM/RT spread positions pay off on scarcity days" : ", free to take DAM/RT spread positions"}.`),
    tile(String(V.n_tasks), "", `real ${unit(V)}s`, `${V.sites.map((s) => `${esc(s.region)} ${esc(s.size)}`).join("; ")}. ${blocks(V)}, each old enough for ERCOT to have disclosed the operators' bids.`),
  ].join("");
}

function checkKpis(V, B) {
  const pi = V.price_impact, keys = Object.keys(pi), lead = pi.sol ? "sol" : keys[0], r = pi[lead];
  const top = keys.reduce((a, k) => (pi[k].max_abs_usd_per_mwh > pi[a].max_abs_usd_per_mwh ? k : a));
  const nm = (k) => (V.models.find((m) => m.key === k) || {}).name || SHORT[k] || k, m = V.models.find((q) => q.key === lead);
  const tie = V.paired.find((p) => p.a === "sol" && p.b === "luna" && p.C)?.C;
  const tile = (v, l, t) => `<div class="kpi"><div class="v">${v}</div><div class="l">${l}</div><div class="t">${t}</div></div>`;
  return [
    tile(`${cents(r.sales_mwh_weighted_usd_per_mwh)}<small>/MWh</small>`, `${esc(nm(lead))}'s own offers moved the price on its sales`, `The re-cleared minus the real node price, weighted by the ${Math.round(r.sales_mwh_per_episode)} MWh it sold a ${unit(V)}; ${cents(r.purchases_mwh_weighted_usd_per_mwh)} on the ${Math.round(r.purchases_mwh_per_episode)} MWh it bought.`),
    tile(`$${pi[top].max_abs_usd_per_mwh.toFixed(2)}<small>/MWh</small>`, "the largest move in any hour", `${esc(nm(top))}'s; ${pi[top].hours_moved_over_1c} of its ${pi[top].awarded_hours} awarded hours moved by more than 1¢.`),
    tile(usd(r.revenue_effect_usd_per_episode, true), `a ${unit(V)}: what the moves did to ${esc(nm(lead))}`, `The change in its day-ahead revenue at the re-cleared prices, against ${usd(m.P.mean)} of P a ${unit(V)}. One 100–150 MW battery is a price taker.`),
    tile(noise(V) ? "Within noise" : "Mixed", `every paired ${V.version} − ${B.version} gap`, `In P, C and R, for all ${Object.keys(V.versus.models).length} models.${tie ? ` ${esc(nm("sol"))} − ${esc(nm("luna"))} in C is ${sgn(tie.mean)} ${sci(tie.ci)}${tie.ci[0] <= 0 && tie.ci[1] >= 0 ? ", a statistical tie" : ""}.` : ""}`),
  ].join("");
}

function board(V) {
  const pa = `P a ${unit(V)}`, head = ["Desk", "C", pa, "P − operator's bids", "P − anchor", "R", "Beats anchor", "$ a run"];
  const cell = (l, v, sub = "") => `<td data-l="${l}">${v}${sub ? `<span class="sub">${sub}</span>` : ""}</td>`;
  const na = (l) => `<td class="na" data-l="${l}">–</td>`;
  const name = (r) => (r.kind === "model" ? whoM(r.key, r.color, r.weights === "open" ? "open weights" : "") : who(r.color, esc(r.name)));
  const op = (r) => (r.P_minus_operator_replay.mean == null ? cell("P − operator's bids", "–") : cell("P − operator's bids", usd(r.P_minus_operator_replay.mean, true), usdci(r.P_minus_operator_replay.ci, true)));
  const body = rows(V).map((r) => r.kind === "model"
    ? `<tr><td>${name(r)}</td>${cell("C", `<b>${num(r.C.mean)}</b>`, ci(r.C.ci))}${cell(pa, usd(r.P.mean), usdci(r.P.ci))}${op(r)}${cell("P − anchor", usd(r.P_minus_anchor.mean, true), usdci(r.P_minus_anchor.ci, true))}${cell("R", num(r.R.mean, 2), ci(r.R.ci, 2))}${cell("Beats anchor", pct(r.beats_anchor))}${cell("$ a run", r.weights === "open" || r.usd_per_episode == null ? "–" : `$${r.usd_per_episode.toFixed(2)}`)}</tr>`
    : `<tr class="ref"><td>${name(r)}</td>${cell("C", num(r.C.mean), ci(r.C.ci))}${cell(pa, usd(r.P.mean), usdci(r.P.ci))}${["P − operator's bids", "P − anchor", "R", "Beats anchor", "$ a run"].map(na).join("")}</tr>`).join("");
  const hind = V.references.find((r) => r.key === "hind");
  return `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr>${head.map((h, i) => `<th class="${i ? "" : "l"}">${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>
    <p class="note">The hindsight optimum earns ${usd(hind.P.mean)} a ${unit(V)} ${usdci(hind.P.ci)}: the best the rules allow with every price known in advance, DAM/RT spread positions included. The operator rows are the real operator's own disclosed bids and awards on each ${unit(V)}, settled by the same code.${V.idle ? ` ${esc(V.idle)}` : ""}</p>`;
}

function frame(R, W) {
  const narrow = W < 560, rh = narrow ? 46 : 38, top = 30, H = top + R.length * rh + 34;
  const left = narrow ? 10 : 218, y = (i) => top + i * rh + (narrow ? 30 : rh / 2);
  const label = (r, i) => (r.kind !== "model" ? txt(narrow ? 10 : left - 8, narrow ? y(i) - 14 : y(i) + 4, esc(r.short || SHORT[r.key] || r.name), "t-lab", narrow ? "start" : "end")
    : narrow ? `<text x="10" y="${y(i) - 14}" class="t-lab b">${esc(r.name)}<tspan class="t-set"> · ${esc(r.setting)}</tspan></text>`
    : txt(left - 8, y(i) - 1, esc(r.name), "t-lab b", "end") + txt(left - 8, y(i) + 13, esc(r.setting), "t-set", "end"));
  return { narrow, top, H, left, y, label };
}

function sensitivity(V) {
  const sv = V.sensitivity, w = sv && (sv.without || sv.derived);
  if (!w) return "";
  const ms = Object.fromEntries(V.models.map((m) => [m.key, m])), name = (k) => (ms[k] ? ms[k].name : SHORT[k] || k);
  const said = (k) => (ms[k] ? ms[k].name : INLINE[k] || k);
  const one = w.days.length === 1, blk = sv.block || "day", dd = and(w.days.map((d) => blockLabel(V, d)));
  const all = Object.fromEntries([...V.models.map((m) => [m.key, m.P]), ...V.references.map((r) => [r.key, r.P])]);
  const keys = [...Object.keys(w.means.models), ...Object.keys(w.means.references)];
  const wo = { ...w.means.models, ...w.means.references }, med = { ...sv.median_P, ...sv.median_P_references };
  const per = w.days.map((d) => ({ ...sv.per_day_mean_P[d].models, ...sv.per_day_mean_P[d].references }));
  const cci = (b) => (b.ci ? `<span class="sub">${usdci(b.ci)}</span>` : "");
  const col = (d) => (V.days_per_task === 1 ? `On ${day_(d)}` : `On the ${day_(d).replace(/ \d{4}$/, "")} ${blk}`);
  const tr = keys.map((k) => `<tr class="${ms[k] ? "" : "ref"}"><td>${ms[k] ? `<b>${esc(name(k))}</b><span class="sub">${esc(MS[k].setting)}</span>` : esc(name(k))}</td><td data-l="All ${V.n_tasks}">${usd(all[k].mean)}${cci(all[k])}</td>${per.map((on, i) => `<td data-l="${col(w.days[i])}">${on[k] == null ? "–" : usd(on[k])}</td>`).join("")}<td data-l="Without ${one ? "it" : "them"}">${usd(wo[k].P.mean)}${cci(wo[k].P)}</td><td data-l="Median, all">${med[k] == null ? "–" : usd(med[k])}</td></tr>`).join("");
  const loss = Object.entries(sv.losses).map(([k, x]) => `${esc(name(k))} ${x.tasks_p_below_0} of ${V.n_tasks}${x.tasks_p_below_0 ? ` (worst ${usd(x.worst_p)})` : ""}`).join("; ");
  const whom = (sv.carried || []).map(said), bb = (sv.bought_back || []).map(said);
  const from = !bb.length ? "" : bb.length === whom.length ? `, from ${BUYBACK}` : `; ${and(bb)} from ${BUYBACK}`;
  const lead = whom.length ? `On ${dd}${sv.why_short ? `, ${esc(sv.why_short)}` : ""}, ${esc(and(whom))} made more than half of ${whom.length > 1 ? "their" : "its"} total P${esc(from)}. ` : "";
  const title = whom.length ? `${one ? `One ${blk} carries` : `A few ${blk}s carry`} the means` : `Without ${dd}`;
  return block(title, `${lead}Mean P a ${unit(V)} with and without ${one ? `that ${blk}` : `those ${blk}s`}${sv.derived ? " (means from the grades, without CIs)" : ""}, and the median over every ${unit(V)}. P below zero: ${loss}. A post-hoc check, not pre-registered.`,
    `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>All ${V.n_tasks}</th>${w.days.map((d) => `<th>${col(d)}</th>`).join("")}<th>Without ${one ? "it" : "them"} (${w.n_tasks})</th><th>Median, all</th></tr></thead><tbody>${tr}</tbody></table></div>`);
}

function capFig(V, W) {
  const R = rows(V).filter((r) => r.key !== "idle"), lo = Math.min(0, ...R.map((r) => r.C.ci[0])), hi = Math.max(1, ...R.map((r) => r.C.ci[1]));
  const F = frame(R, W), x = lin(lo - 0.02, hi + 0.02, F.left, W - 56);
  let s = ticks(lo, hi, F.narrow ? 4 : 8).map((t) => `<g class="grid">${line(x(t), F.top - 6, x(t), F.H - 26, "", 1)}</g>${txt(x(t), F.H - 10, num(t, 1), "t-ax", "middle")}`).join("");
  s += line(x(0), F.top - 10, x(0), F.H - 26, "var(--text-muted)", 1) + txt(x(0) + 4, F.top - 14, "idle", "t-ann");
  s += line(x(1), F.top - 10, x(1), F.H - 26, "var(--text-muted)", 1, "4 3") + txt(x(1) - 4, F.top - 14, "hindsight optimum", "t-ann", "end");
  R.forEach((r, i) => {
    const y = F.y(i), t = tip(tipRows(esc(r.label || r.name), [["C", `${num(r.C.mean)} ${ci(r.C.ci)}`], [`P a ${unit(V)}`, `${usd(r.P.mean)} ${usdci(r.P.ci)}`], ...(r.kind === "model" ? [["P − anchor", `${usd(r.P_minus_anchor.mean, true)} ${usdci(r.P_minus_anchor.ci, true)}`]] : [])]));
    s += F.label(r, i) + line(x(r.C.ci[0]), y, x(r.C.ci[1]), y, r.color, 2);
    s += `<circle cx="${x(r.C.mean)}" cy="${y}" r="${r.kind === "model" ? 6 : 5}" fill="${r.kind === "model" ? r.color : "var(--surface-1)"}" stroke="${r.color}" stroke-width="2" ${t}/>`;
    s += txt(Math.max(x(r.C.ci[1]), x(r.C.mean) + 6) + 8, y + 4, num(r.C.mean), `t-val${r.kind === "model" ? " b" : ""}`);
  });
  return block("Capture: how much of the hindsight optimum each desk earned", "C for each model and reference, with its 95% CI. Idle is 0 and the hindsight optimum 1 by definition; the anchor and the real operator are drawn as references.", `<div class="chart">${svg(W, F.H, s, "Hindsight capture by desk")}</div>`, "capture");
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
    const t = tip(tipRows(esc(r.label || r.name), [[`P a ${unit(V)}`, `${usd(r.P.mean)} ${usdci(r.P.ci)}`], ["C", num(r.C.mean)]]));
    s += F.label(r, i);
    s += `<rect x="${x0}" y="${y - 8}" width="${Math.max(1, w)}" height="16" rx="3" fill="${r.color}" fill-opacity="${r.kind === "model" ? 0.9 : 0.35}" ${t}/>`;
    s += line(x(r.P.ci[0]), y, x(r.P.ci[1]), y, "var(--text-primary)", 1.2);
    s += txt(Math.max(x(r.P.ci[1]), x(r.P.mean)) + 8, y + 4, usd(r.P.mean), `t-val${r.kind === "model" ? " b" : ""}`);
  });
  return block(`Dollars: the settled statement a ${unit(V)}`, "Mean P with 95% CIs, models in colour and references in grey and bronze. The dashed line is the hindsight optimum.", `<div class="chart">${svg(W, F.H, s, `Mean settled P per ${unit(V)}`)}</div>`, "dollars");
}

function linesTable(V) {
  const keys = [...new Set(V.models.flatMap((m) => Object.keys(m.lines)))].filter((k) => V.models.some((m) => Math.abs(m.lines[k] || 0) >= 0.5));
  const order = Object.keys(LINE);
  keys.sort((a, b) => (order.indexOf(a) < 0 ? 99 : order.indexOf(a)) - (order.indexOf(b) < 0 ? 99 : order.indexOf(b)));
  const head = `<tr><th class="l">Line</th>${V.models.map((m) => `<th>${esc(MS[m.key].name)}<span class="sub">${esc(MS[m.key].setting)}</span></th>`).join("")}</tr>`;
  const body = keys.map((k) => `<tr><td>${esc(LINE[k] || k)}${MODELLED.has(k) ? ' <span class="mod">modelled</span>' : ""}</td>${V.models.map((m) => `<td data-l="${esc(labelOf(m.key))}">${usd(m.lines[k] || 0, true)}</td>`).join("")}</tr>`).join("");
  const total = `<tr class="tot"><td><b>P</b></td>${V.models.map((m) => `<td data-l="${esc(labelOf(m.key))}"><b>${usd(m.P.mean, true)}</b></td>`).join("")}</tr>`;
  return `<div class="table-scroll"><table class="grid stack lines"><thead>${head}</thead><tbody>${body}${total}</tbody></table></div>`;
}

function impact(V, W) {
  const pi = V.price_impact;
  if (!pi) return "";
  const keys = [...V.models.map((m) => m.key), "anchor"].filter((k) => pi[k]);
  const nm = (k) => (V.models.find((m) => m.key === k) || {}).name || SHORT[k] || k;
  const color = (k) => COL[k] || REFC[k] || "var(--c-hind)";
  const narrow = W < 560, left = narrow ? 10 : 218, rh = narrow ? 58 : 46, top = 26, H = top + keys.length * rh + 30;
  const vals = keys.flatMap((k) => [pi[k].sales_mwh_weighted_usd_per_mwh, pi[k].purchases_mwh_weighted_usd_per_mwh]);
  const m = Math.max(0.05, ...vals.map(Math.abs)) * (narrow ? 1.15 : 1.6), x = lin(-m, m, narrow ? 10 : left, W - 20);
  let s = ticks(-m, m, narrow ? 3 : 5).map((t) => `<g class="grid">${line(x(t), top - 6, x(t), H - 26, "", 1)}</g>${txt(x(t), H - 10, cents(t), "t-ax", "middle")}`).join("");
  s += line(x(0), top - 10, x(0), H - 26, "var(--text-muted)", 1) + txt(x(0) - 6, top - 14, "price lower", "t-ann", "end") + txt(x(0) + 6, top - 14, "price higher", "t-ann");
  keys.forEach((k, i) => {
    const y = top + i * rh + (narrow ? 22 : 8), r = pi[k];
    s += !MS[k] ? txt(narrow ? 10 : left - 8, narrow ? y - 6 : y + 14, esc(nm(k)), "t-lab", narrow ? "start" : "end")
      : narrow ? `<text x="10" y="${y - 6}" class="t-lab b">${esc(MS[k].name)}<tspan class="t-set"> · ${esc(MS[k].setting)}</tspan></text>`
      : txt(left - 8, y + 9, esc(MS[k].name), "t-lab b", "end") + txt(left - 8, y + 24, esc(MS[k].setting), "t-set", "end");
    [[r.sales_mwh_weighted_usd_per_mwh, "on sales", 0], [r.purchases_mwh_weighted_usd_per_mwh, "on purchases", 1]].forEach(([v, lab, j]) => {
      const yy = y + j * 16, x0 = x(Math.min(0, v)), w = Math.max(1, Math.abs(x(v) - x(0)));
      const t = tip(tipRows(esc(MS[k] ? labelOf(k) : nm(k)), [["Sales, MWh-weighted", `${cents(r.sales_mwh_weighted_usd_per_mwh)}/MWh on ${Math.round(r.sales_mwh_per_episode)} MWh`], ["Purchases, MWh-weighted", `${cents(r.purchases_mwh_weighted_usd_per_mwh)}/MWh on ${Math.round(r.purchases_mwh_per_episode)} MWh`], ["Revenue effect", `${usd(r.revenue_effect_usd_per_episode, true)} a ${unit(V)}`]]));
      s += `<rect x="${x0}" y="${yy}" width="${w}" height="11" rx="2" fill="${color(k)}" fill-opacity="${j ? 0.45 : 0.9}" ${t}/>`;
      if (!narrow) s += txt(v < 0 ? x0 - 6 : x0 + w + 6, yy + 9, `${cents(v)} ${lab}`, "t-val", v < 0 ? "end" : "start");
    });
  });
  const tr = keys.map((k) => { const r = pi[k]; return `<tr><td>${MS[k] ? whoM(k, color(k)) : who(color(k), esc(nm(k)))}</td><td data-l="On its sales">${cents(r.sales_mwh_weighted_usd_per_mwh)}<span class="sub">${Math.round(r.sales_mwh_per_episode)} MWh</span></td><td data-l="On its purchases">${cents(r.purchases_mwh_weighted_usd_per_mwh)}<span class="sub">${Math.round(r.purchases_mwh_per_episode)} MWh</span></td><td data-l="Revenue effect">${usd(r.revenue_effect_usd_per_episode, true)}</td><td data-l="Largest move">$${r.max_abs_usd_per_mwh.toFixed(2)}/MWh</td><td data-l="Hours moved over 1¢">${r.hours_moved_over_1c} of ${r.awarded_hours}</td></tr>`; }).join("");
  return block("Price impact: what the desk's own DAM offers did to the price", `The day-ahead market re-cleared against the day's real offers with each desk's own: the re-cleared minus the real node price over awarded hours, MWh-weighted, per ${unit(V)}. A single 100–150 MW battery is a price taker here, as pre-registered; a fleet desk, a QSE trading a portfolio of batteries, is the next step for price impact to matter.`,
    `<div class="chart">${svg(W, H, s, "DAM price impact by desk")}</div><div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>On its sales</th><th>On its purchases</th><th>Revenue effect, $ a ${unit(V)}</th><th>Largest move</th><th>Hours moved over 1¢</th></tr></thead><tbody>${tr}</tbody></table></div>`);
}

function versus(V, B) {
  const vs = V.versus;
  const nm = (k) => (V.models.find((m) => m.key === k) || {}).name || k;
  const g = (b, n = 3) => `${sgn(b.mean, n)}<span class="sub">${sci(b.ci, n)}</span>`;
  const c = (v, k) => { const m = v.models.find((q) => q.key === k); return `${num(m.C.mean)}<span class="sub">${ci(m.C.ci)}</span>`; };
  const tr = ORDER.filter((k) => vs.models[k]).map((k) => { const b = vs.models[k]; return `<tr><td>${whoM(k)}</td><td data-l="C in ${B.version}">${c(B, k)}</td><td data-l="C in ${V.version}">${c(V, k)}</td><td data-l="${V.version} − ${B.version}, C">${g(b.C)}</td><td data-l="${V.version} − ${B.version}, P">${usd(b.P.mean, true)}<span class="sub">${usdci(b.P.ci, true)}</span></td><td data-l="${V.version} − ${B.version}, R">${g(b.R, 2)}</td></tr>`; }).join("");
  return block(`${V.version} against ${B.version}, paired on the same ${unit(V)}s`, `Each model's ${V.version} run minus its ${B.version} run on the same ${V.n_tasks} ${unit(V)}s, with day-block 95% CIs.${noise(V) ? " Every gap's CI includes zero: two runs of the same model differ this much, while the price moved by cents." : ""}`,
    `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>C in ${B.version}</th><th>C in ${V.version}</th><th>${V.version} − ${B.version}, C</th><th>${V.version} − ${B.version}, P a ${unit(V)}</th><th>${V.version} − ${B.version}, R</th></tr></thead><tbody>${tr}</tbody></table></div>`);
}

function reserves(V) {
  const ms = V.models.filter((m) => m.ancillary);
  if (!ms.length) return "";
  const mwh = (o) => Object.values(o).reduce((a, b) => a + b, 0), f = (v) => (!v ? "0" : v >= 9.95 ? Math.round(v).toLocaleString("en-US") : v.toFixed(1));
  const parts = (o) => Object.entries(o).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${AS[k] || k} ${f(v)}`).join(", ");
  const body = ms.map((m) => {
    const a = m.ancillary, rc = Object.entries(a.rejected_codes_total), got = (m.lines.dam_as_capacity || 0) + (m.lines.rt_as_imbalance || 0);
    const refused = rc.length ? `${rc.reduce((x, [, k]) => x + k, 0)}<span class="sub">${rc.map(([c, k]) => `${esc(c)} ×${k}${ASO[c] ? `, ${ASO[c]}` : ""}`).join("; ")}</span>` : "–";
    return `<tr><td>${whoM(m.key)}</td><td data-l="AS awards">${a.episodes_with_awards} of ${m.n}</td><td data-l="From the AS lines">${usd(got, true)}</td><td data-l="DAM award MWh">${f(mwh(a.dam_award_mwh))}<span class="sub">${parts(a.dam_award_mwh)}</span></td><td data-l="RT award MWh">${f(mwh(a.rt_award_mwh))}<span class="sub">${parts(a.rt_award_mwh)}</span></td><td class="full" data-l="AS offers refused">${refused}</td></tr>`;
  }).join("");
  return block("Reserves: what each desk's AS offers won", `Means per ${unit(V)}. AS awards counts the ${unit(V)}s with any ancillary-service award; the AS lines are DAM capacity and RT imbalance; award MWh by product, DAM and real time.`,
    `<div class="table-scroll"><table class="grid stack wrapcells"><thead><tr><th class="l">Desk</th><th>AS awards</th><th>From the AS lines</th><th>DAM award MWh</th><th>RT award MWh</th><th>AS offers refused</th></tr></thead><tbody>${body}</tbody></table></div>${V.defects ? `<p class="note">${md(V.defects)}</p>` : ""}`);
}

function behaviour(V) {
  const head = ["Desk", "Turns", "Wakes", "Calls", "Most-used tools", "Submissions accepted / rejected", "Rejection codes", "Reminders", "Cycles"];
  const body = V.models.map((m) => {
    const tools = Object.entries(m.calls_by_tool).slice(0, 4).map(([t, n]) => `<span class="nw"><code>${esc(t)}</code> ${num(n, 1)}</span>`).join(", ");
    const codes = Object.entries(m.rejected_codes).slice(0, 3).map(([c, n]) => `${esc(c)} ×${n}`).join(", ") || "–";
    return `<tr><td>${whoM(m.key)}</td><td data-l="Turns">${num(m.turns, 1)}</td><td data-l="Wakes">${num(m.wakes, 1)}</td><td data-l="Calls">${num(m.calls, 1)}</td><td class="l full" data-l="Most-used tools">${tools}</td><td data-l="Accepted / rejected">${num(m.accepted, 1)} / ${num(m.rejected, 1)}</td><td class="l full codes" data-l="Rejection codes">${codes}</td><td data-l="Reminders">${num(m.reminders, 1)}</td><td data-l="Cycles">${num(m.cycles, 2)}</td></tr>`;
  }).join("");
  return `<div class="table-scroll"><table class="grid stack wrapcells beh"><thead><tr>${head.map((h, i) => `<th class="${i === 0 || i === 4 || i === 6 ? "l" : ""}">${h}</th>`).join("")}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function replays(V, C) {
  if (!C) return "";
  const cv = C.versions.find((x) => x.version === V.version);
  if (!cv) return "";
  const tasks = cv.tasks.map((k) => [k, C.tasks[k]]);
  const sites = [...new Map(tasks.map(([, t]) => [t.site, t])).values()].sort((a, b) => a.site.localeCompare(b.site));
  const days = [...new Set(tasks.map(([, t]) => t.dates[0]))].sort();
  const label = (t) => (t.dates.length > 1 ? `${+t.dates[0].slice(8)} to ${shortDay(t.dates.at(-1))}` : shortDay(t.dates[0]));
  const models = V.models.map((m) => m.key), solar = new Set(tasks.filter(([, t]) => t.pv).map(([, t]) => t.site));
  const cell = (kt) => {
    if (!kt) return "<td></td>";
    const [k, t] = kt;
    return `<td class="rp">${models.map((m) => { const e = C.episodes[`${k}.${m}`]; return e ? `<a href="./index.html?v=${V.version}&m=${m}&task=${k}" title="${esc(`${t.name}, ${label(t)}: ${labelOf(m)}, P ${usd(e.P)}`)}"><i style="background:${COL[m]}"></i>${e.C == null ? "–" : num(e.C, 2)}</a>` : ""; }).join("")}</td>`;
  };
  const tr = days.map((d) => { const t0 = tasks.find(([, t]) => t.dates[0] === d)[1]; return `<tr><th scope="row">${label(t0)}${t0.wx ? `<small>${esc(t0.wx)}</small>` : ""}</th>${sites.map((s) => cell(tasks.find(([, t]) => t.dates[0] === d && t.site === s.site))).join("")}</tr>`; }).join("");
  return block("Every run, replayed", `Each cell opens that ${unit(V)} on the battery site in 3D beside the desk, one link per model with its hindsight capture C.`,
    `<div class="legend">${models.map(keyM).join("")}</div><div class="table-scroll"><table class="grid replays"><thead><tr><th></th>${sites.map((s) => `<th>${esc(s.name)}<small>${esc(s.region)}, ${esc(s.size)}${solar.has(s.site) ? ", solar on some days" : ""}</small></th>`).join("")}</tr></thead><tbody>${tr}</tbody></table></div>`);
}

function settingsBlock(D) {
  const [lead, ...each] = D.models_lines;
  return block("Models and settings", md(lead), `<ul class="models">${each.map((x) => `<li>${md(x)}</li>`).join("")}</ul>`);
}

function how() {
  const g = [["ERCOT's public reports", "<code>get_prices</code> (DAM, 15-minute RT and 5-minute SCED at the node; DAM and RT at its hub), <code>get_forecasts</code> (ERCOT's load, wind, solar and outage forecasts as issued, NWS alerts, the desk's price forecast, modelled), <code>get_grid_conditions</code>"],
    ["Plant telemetry and the book", "<code>get_asset_status</code> (state of charge, limits, base points, outages), <code>get_position</code> (awards, RT position, COP, the statement so far)"],
    ["ERCOT's market submission system", "<code>submit_dam_offers</code>, <code>submit_rt_offers</code>, <code>update_cop</code>, and <code>check_submission</code>, a dry run with ERCOT's validation codes"],
    ["The desk's analytics", "<code>optimize</code>, a co-optimiser on the agent's own price view that proposes curves and a COP and never submits; <code>set_reminder</code>"]];
  return block("How the desk works", `The agent never moves a megawatt: ERCOT's clearing turns its curves into dispatch every 5 minutes, and the day settles on ERCOT's statement. The clock stands still while it works and runs between turns; it wakes at the market's milestones, at each notice, outage and deployment at its real minute, and at reminders it sets. ${link(`${ARTICLE}`, "The article")} explains why and how.`,
    `<div class="tools">${g.map(([h, t]) => `<div><h3>${h}</h3>${t}</div>`).join("")}</div>`);
}

function sources(V) {
  const t = (rel) => `${DATASET}/tree/main/${rel}`, b = (rel) => `${DATASET}/blob/main/${rel}`;
  return block("Every number's source", "", `<div class="links-grid">
    <div><h3>On the dataset</h3><ul><li>${link(t(V.folder), `<code>${V.folder}</code>`)}</li><li>${link(b(`${V.folder}/README.md`), "README")}, ${link(b(`${V.folder}/summary.json`), "summary.json")}, ${link(b(`${V.folder}/grades.jsonl.gz`), "grades")}</li><li>configs <code>desk_leaderboard</code>, <code>desk_runs</code> and <code>desk_tasks</code>, split <code>${V.version}</code></li></ul></div>
    <div><h3>On GitHub, tag <code>${esc(V.ref)}</code></h3><ul><li>${link(V.github, "the result folder")}</li><li>${link(`${REPO}/blob/${V.ref}/docs/prereg/${V.version}-desk.md`, "the pre-registration")}</li><li>${link(`${REPO}/blob/${V.ref}/docs/CONTRACT-desk.md`, "the desk contract")}</li></ul></div>
    <div><h3>Settings</h3><ul><li>${esc(V.budget)}</li><li>core ${esc(V.core)}, ${esc(V.eras.join(", "))} rules</li><li>${esc(V.ci.method)}, ${V.ci.resamples.toLocaleString("en-US")} resamples</li></ul></div></div>
    ${V.defects ? `<p class="note">${md(V.defects)}</p>` : ""}${V.deviations ? `<p class="note">${md(V.deviations)}</p>` : ""}`);
}

function footer(C) {
  return `<p>Prices, awards, notices and disclosures: ERCOT's public reports. Alerts: the National Weather Service. Not affiliated with or endorsed by ERCOT. The batteries are anonymised as S01 to S04 by region; the co-located solar, the desk's price forecast and degradation are modelled.</p>
    <p>${link(DATASET, "The dataset")}, ${link(ARTICLE, "the article")} and ${link(REPO, "the code")}. The earlier viewer, v1 and the previews, is archived at ${link(`${SPACE}/tree/${C?.archive || ""}`, `this Space's revision ${(C?.archive || "").slice(0, 7)}`)}.</p>`;
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
  addEventListener("focusin", (e) => {
    const el = e.target.closest?.("[data-tip]");
    if (!el) return;
    const r = el.getBoundingClientRect();
    show(el, r.right, r.top);
  });
  addEventListener("keydown", (e) => e.key === "Escape" && ((pinned = null), (box.hidden = true)));
  addEventListener("scroll", () => !pinned && (box.hidden = true), { passive: true });
}

async function main() {
  let D, C = null;
  try {
    D = await (await fetch("./desk.json")).json();
  } catch (e) {
    $("lede").textContent = `The desk's results could not be loaded (${e.message}).`;
    return;
  }
  for (const v of D.versions) v.models.sort((a, b) => ORDER.indexOf(a.key) - ORDER.indexOf(b.key));
  MS = D.models;
  if (!EXPORT) C = await fetch("./data/catalog.json").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  await document.fonts.ready;
  const hash = location.hash.slice(1), want = Q.get("v") || (D.versions.some((v) => v.version === hash) ? hash : "bench");
  const draw = !EXPORT && want === "bench" ? await benchPage(D, C) : () => render(D, C);
  draw();
  if (EXPORT) {
    window.deskReady = true;
    return;
  }
  $("foot").innerHTML = footer(C);
  tips();
  $("main").addEventListener("click", (e) => {
    const a = e.target.closest("a[data-v]");
    if (!a) return;
    e.preventDefault();
    Q.set("v", a.dataset.v);
    history.replaceState(null, "", `?${Q}#tabs`);
    const y = $("tabs").getBoundingClientRect().top + scrollY;
    render(D, C);
    scrollTo({ top: y - 12 });
  });
  let w = innerWidth;
  addEventListener("resize", () => {
    if (Math.abs(innerWidth - w) < 8) return;
    w = innerWidth;
    clearTimeout(main.t);
    main.t = setTimeout(draw, 120);
  });
  const id = location.hash.slice(1), to = { cost: "halves" }[id] || id;
  if (to && $(to)) {
    if (to !== id) history.replaceState(null, "", `#${to}`);
    $(to).scrollIntoView();
  }
  window.deskReady = true;
  window.resultsReady = true;
}

main();
