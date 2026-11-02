/** Try it: play one GridSimEnv Desk window by hand, exactly as an agent plays it. The window opens over this page's own
 * OpenEnv WebSocket session (/ws): reset, then the desk's eleven tools under the same per-turn call budget, and end_turn,
 * which runs the market to the next wake-up. Prices and forecasts show only what your calls returned; the battery site
 * in 3D, its charge and the settled statement come from the market's run so far (/api/episodes/{id}), never past now. */
import { buildChart } from "./charts.js";
import { AS, EVENTFUL, REASONS, argLine, at, dateDay, dateLabel, day, esc, isoDay, minuteOf, mw, num, pct, render, short, usd } from "./format.js";
import { EnvSession, answer, unwrap } from "./session.js";
import { CAMS, Site } from "./site3d.js";

const $ = (id) => document.getElementById(id);
const Q = new URLSearchParams(location.search);
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
const ANCHOR = { risk: 1.5, dam_position: "spread" };
const TOOLBAR = [["get_prices", "Prices"], ["get_forecasts", "Forecasts"], ["get_grid_conditions", "Grid"], ["get_asset_status", "Asset status"], ["get_position", "Position"], "|", ["optimize", "Optimize"], "|", ["submit_dam_offers", "DA offers"], ["submit_rt_offers", "RT offers"], ["update_cop", "COP"], ["check_submission", "Check"], ["set_reminder", "Reminder"], "|", ["*", "All tools"], "grow", ["end_turn", "End turn"]];
const VIEWER = "https://earakely-scale-gridsimenv-agentenv.static.hf.space/index.html";
const CODE = "https://github.com/earakely-scale/agentenv-gridsim-plugin/tree/main/hub/openenv";
const FIT_MIN = 540;
const FIT_GAP = 16;
const IDLE_MS = 20 * 60 * 1000;

const S = {
  cards: [], models: {}, card: null, session: null, token: null, tools: {}, brief: "", desk: {}, wake: null, wakes: [],
  log: [], unseen: 0, market: { dam: {}, series: {}, fc: {} }, proposal: null, plan: {}, view: null, grade: null,
  phase: "boot", busy: false, auto: false, quick: {}, moves: [], t: -1080, anim: null, playing: false, site: null,
  chart: null, tab: "market", wall: 0, lastInput: 0, seen: 0, ended: false,
};
const site = () => S.card.site;
const d0 = () => S.card.dates[0];
const T1 = () => 1440 * S.card.dates.length;

/* ---------------- boot ---------------- */

async function main() {
  toolbar();
  cams();
  tabs();
  dialogs();
  transport();
  const r = await fetch("/api/windows");
  const w = await r.json();
  S.cards = w.windows;
  S.models = w.models;
  const pick = S.cards.find((c) => c.task_id === Q.get("task")) || S.cards[+Q.get("index")] || S.cards.find((c) => c.task_id === w.default) || S.cards[0];
  S.session = session();
  await open(pick);
  requestAnimationFrame(loop);
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) addEventListener(ev, () => (S.seen = performance.now()), { capture: true, passive: true });
  S.seen = performance.now();
  setInterval(idleCheck, 30000);
}

/** The server holds a WebSocket's session for as long as the socket is open, so a window left without a move for
 * IDLE_MS gives its seat back; its moves are kept, and replaying them restores the same moment. */
function idleCheck() {
  if (S.ended || S.desk.done || S.phase !== "turn" || S.busy || S.auto || performance.now() - S.seen < IDLE_MS) return;
  S.session.close();
  dropped(`This session was closed after ${IDLE_MS / 60000} minutes without a move, so the Space can seat other visitors.`);
}

function session() {
  return new EnvSession((status) => {
    if (status === "dropped" && !S.ended && S.phase !== "boot") dropped("The connection to the env closed, and the server ended this episode with it.");
    renderState();
  });
}

/** Starts a window: reset, the tools' schemas, the scene; with `moves`, replays them first (a resumed episode). */
async function open(card, { moves = [] } = {}) {
  S.phase = "boot";
  S.card = card;
  S.ended = false;
  hideDrop();
  $("boot").classList.remove("gone");
  $("boot").querySelector("span").textContent = `Opening ${card.site.name}, ${card.site.region}`;
  $("end").hidden = true;
  Object.assign(S, { desk: {}, wake: null, wakes: [], log: [], unseen: 0, market: { dam: {}, series: {}, fc: {} }, proposal: null, plan: {}, view: null, grade: null, auto: false, quick: {}, moves: [], anim: null, playing: false });
  renderAll();
  let r;
  try {
    r = unwrap(await S.session.reset({ task_id: card.task_id }));
    if (r.error) throw Object.assign(new Error(r.error), { code: r.code });
    const tl = unwrap(await S.session.listTools());
    S.tools = Object.fromEntries((tl.obs?.tools || []).map((t) => [t.name, t]));
  } catch (e) {
    return dropped(e.code === "CAPACITY_REACHED" ? "Every session on this Space is in use. Try again in a minute." : `The env did not start an episode: ${e.message}`, { capacity: e.code === "CAPACITY_REACHED" });
  }
  S.token = r.meta.episode;
  S.brief = r.meta.system_prompt;
  S.desk = r.meta.desk;
  S.wake = JSON.parse(r.meta.prompt);
  S.wakes = [{ ...S.wake, minute: S.desk.minute }];
  S.t = S.desk.minute;
  history.replaceState(null, "", `${location.pathname}?${new URLSearchParams({ ...Object.fromEntries(Q), task: card.task_id, index: card.index })}`);
  S.site?.dispose();
  S.site = new Site($("stage"), card, { reduced });
  S.site.onDirect = (on) => !on && camPressed("fly");
  S.chart = buildChart($("p-market-chart") || marketShell(), { d0: card.dates[0], t0: -1080, t1: T1(), site: card.site });
  for (const m of moves) {
    $("boot").querySelector("span").textContent = `Replaying your moves: ${S.moves.length + 1} of ${moves.length}`;
    const ok = m.end ? await endTurn(m.response, { quiet: true }) : await call(m.name, m.args, { quiet: true });
    if (ok === false) break;
  }
  await refresh({ animate: false });
  S.phase = S.desk.done ? "over" : "turn";
  try {
    S.site.update(S.view);
  } catch (e) {
    console.error(e);
    $("boot").querySelector("span").textContent = "This browser could not start WebGL; the desk on the right still plays.";
    renderAll();
    return;
  }
  requestAnimationFrame(() => $("boot").classList.add("gone"));
  renderAll();
  if (S.desk.done) finish();
  window.gridsim = { ready: true, task: card.task_id };
}

/* ---------------- the desk's tools ---------------- */

/** One tool call over the session; returns the parsed answer, or false when the episode can't go on. */
async function call(name, args = {}, { quiet = false } = {}) {
  if (S.busy && !quiet) return null;
  S.busy = true;
  renderState();
  let r;
  try {
    r = unwrap(await S.session.call(name, args));
  } catch (e) {
    S.busy = false;
    return false;
  }
  S.busy = false;
  if (r.error) {
    dropped(`The env refused the call: ${r.error}`);
    return false;
  }
  const a = answer(r.obs);
  if (/^session_closed/.test(a.error || "")) {
    dropped("This session was closed after being idle.");
    return false;
  }
  S.moves.push({ name, args });
  if (r.meta.desk) S.desk = r.meta.desk;
  const res = a.json ?? (a.error ? { error: a.error } : { text: a.text });
  log({ kind: "call", tool: name, args, res, text: a.text ?? a.error, minute: S.desk.minute, turn: S.desk.turn });
  ingest(name, args, res);
  if (!quiet) {
    renderAll();
    if (name !== "optimize" && !S.auto) flash(name);
  }
  return res;
}

/** Ends the turn: the market runs to the next wake-up, which the scene then plays; the last turn grades the window. */
async function endTurn(response = "", { quiet = false } = {}) {
  if (S.busy && !quiet) return null;
  S.busy = true;
  S.phase = "run";
  renderState();
  const from = S.desk.minute;
  let r;
  try {
    r = unwrap(await S.session.call("end_turn", { response }));
  } catch (e) {
    S.busy = false;
    return false;
  }
  S.busy = false;
  if (r.error) {
    dropped(`The env refused end_turn: ${r.error}`);
    return false;
  }
  S.moves.push({ end: true, response });
  if (r.meta.desk) S.desk = r.meta.desk;
  if (r.done) {
    S.grade = r.meta.grade;
    log({ kind: "end", minute: S.desk.minute, res: r.meta.grade, text: r.obs.result?.data });
  } else {
    S.wake = JSON.parse(r.obs.result.prompt);
    S.wakes.push({ ...S.wake, minute: S.desk.minute });
    log({ kind: "wake", wake: S.wake, minute: S.desk.minute, turn: S.desk.turn, text: r.obs.result.prompt });
    S.quick = {};
  }
  if (quiet) return true;
  await refresh({ animate: true, from });
  return true;
}

async function refresh({ animate = false, from = null } = {}) {
  try {
    const r = await fetch(`/api/episodes/${S.token}`, { cache: "no-store" });
    if (!r.ok) throw new Error(`${r.status}`);
    S.view = await r.json();
  } catch (e) {
    return dropped("The env no longer holds this episode.");
  }
  if (S.view.grade) S.grade = S.view.grade;
  if (S.site?.stage) S.site.update(S.view);
  const to = S.desk.done ? T1() : S.desk.minute;
  if (animate && !reduced && from != null && to > from) {
    const hours = (to - from) / 60;
    S.anim = { a: from, b: to, start: performance.now(), dur: S.auto ? Math.min(1600, 500 + 90 * hours) : Math.min(5200, 1100 + 260 * hours) };
    S.phase = "run";
  } else {
    S.t = to;
    S.anim = null;
    S.phase = S.desk.done ? "over" : "turn";
    if (S.desk.done) finish();
  }
  renderAll();
}

function ingest(name, args, res) {
  if (!res || res.error) return;
  const m = S.market;
  if (name === "get_prices" && res.values?.length) {
    if (res.market === "dam") {
      if ((res.point || "node") === "node") m.dam[res.date] = res.values;
    } else if (res.point === "node" || !res.point) {
      const dt = { "5m": 5, "15m": 15, "60m": 60, "1h": 60, "30m": 30, "120m": 120 }[res.step] || 15;
      const x0 = res.start && /\d{2}-\d{2}/.test(res.start) ? minuteOf(res.start, d0()) : 1440 * dateDay(d0(), res.date) + (/^\d{2}:\d{2}$/.test(res.start || "") ? 60 * +res.start.slice(0, 2) : 0);
      m.series[`${res.market}|${x0}|${dt}`] = { x0, dt, values: res.values, label: res.market === "sced" ? "SCED, 5-min" : "Real time" };
    }
  }
  if (name === "get_forecasts" && res.kind === "price" && res.p50) {
    const dt = res.step === "15m" ? 15 : 60;
    m.fc[`${res.market}|${res.date}`] = { x0: 1440 * dateDay(d0(), res.date), dt, mid: res.p50, lo: res.p10, hi: res.p90, issued: res.issued_at, market: res.market };
  }
  if (name === "optimize" && !res.error) S.proposal = { ...res, minute: S.desk.minute };
  if (["submit_dam_offers", "submit_rt_offers", "update_cop"].includes(name)) {
    const day = res.date ? `D${dateDay(d0(), res.date)}` : args.day || "D0";
    const key = { submit_dam_offers: "dam", submit_rt_offers: "rt", update_cop: "cop" }[name];
    const p = (S.plan[day] ||= {});
    if (res.accepted_hours && res.accepted_hours !== "none" && res.accepted_hours !== "") (p[key] ||= []).push({ hours: res.accepted_hours, minute: S.desk.minute, rejected: (res.rejected || []).length });
    if (res.as_accepted && Object.keys(res.as_accepted).length) (p[`${key}_as`] ||= []).push({ as: res.as_accepted, minute: S.desk.minute });
  }
}

/* ---------------- quick play and the autopilot ---------------- */

const OPT_ARGS = () => ({ price_view: "desk", risk: ANCHOR.risk, constraints: { dam_position: ANCHOR.dam_position } });

async function quickOptimize() {
  const r = await call("optimize", OPT_ARGS());
  if (r && !r.error && !S.auto) setTab("plan");
  renderQuick();
  return r;
}

/** The optimizer's proposal sent as the anchor sends it: DAM curves and reserves per open day, real-time curves and
 * reserves for days whose adjustment period has opened, and the COP rows. */
async function quickSubmit() {
  const p = S.proposal;
  if (!p || p.minute !== S.desk.minute) return null;
  const sends = [];
  const group = (tool, curves, asOffers) => {
    const by = {};
    for (const g of curves || []) (by[g.day] ||= {}).curves = [...(by[g.day]?.curves || []), { hours: g.hours, points: g.points }];
    for (const a of asOffers || []) (by[a.day] ||= {}).as_offers = [...(by[a.day]?.as_offers || []), { hours: a.hours, product: a.product, mw: a.mw, price: a.price }];
    for (const [dayKey, args] of Object.entries(by)) sends.push([tool, { day: dayKey, ...args }]);
  };
  group("submit_dam_offers", p.dam_curves, p.dam_as_offers);
  group("submit_rt_offers", (p.rt_curves || []).filter((g) => S.desk.minute >= 1440 * +g.day.slice(1) - 360), p.rt_as_offers);
  for (const row of p.cop || []) sends.push(["update_cop", { day: row.day, rows: [{ hours: row.hours, hbsoc_mwh: row.hbsoc_mwh }] }]);
  S.quick.sending = true;
  renderQuick();
  let n = 0;
  for (const [tool, args] of sends) {
    if (S.desk.calls_left <= 0) break;
    const r = await call(tool, args, { quiet: true });
    if (r === false) return false;
    n++;
  }
  S.quick.sending = false;
  S.quick.sent = n || "none";
  renderAll();
  return n;
}

async function quickEnd() {
  return endTurn(S.auto ? "autopilot: optimize, submit, wait" : "");
}

async function autopilot() {
  if (S.auto) {
    S.auto = false;
    renderQuick();
    return;
  }
  S.auto = true;
  renderQuick();
  while (S.auto && !S.desk.done && !S.ended) {
    if (!(S.wake.reasons.length === 1 && S.wake.reasons[0] === "reminder")) {
      const r = await quickOptimize();
      if (r === false || !S.auto) break;
      if (r && !r.error && (await quickSubmit()) === false) break;
    }
    if (!S.auto) break;
    if ((await quickEnd()) === false) break;
    while (S.anim) await new Promise((r) => setTimeout(r, 60));
  }
  S.auto = false;
  renderQuick();
}

/* ---------------- rendering ---------------- */

function renderAll() {
  if (!S.card) return;
  renderBar();
  renderState();
  renderWake();
  renderQuick();
  renderMarket();
  renderPlan();
  renderCalls();
  renderBrief();
  renderPlate();
  drawScrub();
}

function renderBar() {
  const c = S.card;
  $("w-name").textContent = `${c.site.name}, ${c.site.region}`;
  $("w-meta").textContent = `${c.site.size} · window #${c.index}`;
  const f = c.front;
  $("w-front").innerHTML = `<i class="cut ${esc(c.cutoff)}" title="${c.cutoff === "pre_cutoff" ? "Before" : "After"} the models' training cutoffs"></i>${esc(dateSpan(c.dates))} · ${esc(cap(f.kind))}${f.name ? `, ${esc(f.name)}` : ""}`;
  const k = S.desk;
  $("c-now").textContent = k.minute != null ? at(d0(), k.minute) : "–";
  $("c-turn").textContent = k.turn ? (k.done ? "The window is over" : `Turn ${k.turn} of ${k.max_turns}`) : "";
  const left = k.calls_left ?? 0, per = k.calls_per_turn || 14;
  $("k-calls").textContent = k.done || k.minute == null ? "–" : `${left} of ${per}`;
  if ($("k-pips").childElementCount !== per) $("k-pips").innerHTML = "<i></i>".repeat(per);
  $("k-pips").style.gridTemplateColumns = `repeat(${per}, 1fr)`;
  [...$("k-pips").children].forEach((p, i) => p.classList.toggle("used", k.done || i >= left));
  const tot = S.view?.settled?.total ?? 0;
  $("k-pnl").textContent = usd(tot);
  $("k-pnl").classList.toggle("neg", tot < 0);
}

function renderState() {
  const el = $("state"), p = S.phase;
  const [cls, text] = S.ended ? ["bad", "Disconnected"] : p === "boot" ? ["", "Opening"] : p === "over" ? ["over", "Window over"] : p === "run" ? ["run", "The market runs"] : S.busy ? ["turn", "Calling the desk"] : S.auto ? ["run", "Autopilot"] : ["turn", "Your turn"];
  el.className = `state ${cls}`;
  el.querySelector("span").textContent = text;
  renderBarButtons();
}

function renderBarButtons() {
  const left = S.desk.calls_left ?? 0, off = S.ended || S.phase !== "turn" || S.busy;
  for (const b of document.querySelectorAll("#toolbar [data-tool]")) {
    const end = b.dataset.tool === "end_turn";
    b.disabled = off || S.auto || (!end && b.dataset.tool !== "*" && left <= 0);
  }
  for (const b of document.querySelectorAll("[data-q]")) b.disabled = (off && !(S.auto && b.dataset.q === "auto")) || (S.auto && b.dataset.q !== "auto");
}

function wakeTitle(w) {
  const rs = (w.reasons || []).map((r) => REASONS[r] || r);
  return rs.length ? cap(rs.join(" · ")) : "Wake-up";
}

function eventLine(e) {
  const t = `<small>${esc(when(e.t))}</small> `;
  switch (e.kind) {
    case "notice": return `<li class="ev">${t}ERCOT ${esc(e.level || "")}: ${esc(e.title || e.text || "")}</li>`;
    case "weather": return `<li class="ev">${t}NWS ${esc(e.event || "")}${e.expires ? `, until ${esc(when(e.expires))}` : ""}</li>`;
    case "outage": return `<li class="ev">${t}${esc(e.text)}</li>`;
    case "deployment": return `<li class="ev">${t}${esc(AS[e.product] || e.product || "")} deployment ${esc(e.text || "")}</li>`;
    case "dam_results": return `<li class="dam">${t}${esc(e.text)}</li>`;
    case "reminder": return `<li>${t}Your reminder${e.text ? `: ${esc(e.text)}` : ""}</li>`;
    default: return `<li>${t}${esc(e.text || e.kind)}</li>`;
  }
}

function renderWake() {
  const w = S.wake;
  if (!w || S.desk.done) {
    $("wake").innerHTML = S.desk.done ? `<div class="hd"><b>The window is over</b><span>${esc(at(d0(), T1()))}</span></div><ul><li>Every interval is settled and the window is graded.</li></ul>${S.grade ? '<div class="chips" style="margin-top:8px"><button type="button" class="btn sm go" data-act="results">Your results</button></div>' : ""}` : "";
    return;
  }
  const evs = (w.events || []).filter((e) => !["dam_close", "druc"].includes(e.kind) || (w.events || []).length < 3);
  $("wake").innerHTML = `<div class="hd"><b>${esc(wakeTitle(w))}</b><span>${esc(at(d0(), S.desk.minute))}</span></div>
    ${evs.length ? `<ul>${evs.slice(0, 6).map(eventLine).join("")}${evs.length > 6 ? `<li>${evs.length - 6} more in Calls</li>` : ""}</ul>` : ""}
    <div class="dl">${(w.deadlines || []).slice(0, 3).map((d) => `<span>${esc(cap(d.what))} <b>${esc(when(d.at))}</b></span>`).join("")}</div>`;
}

function renderQuick() {
  const q = S.quick, p = S.proposal, fresh = p && p.minute === S.desk.minute;
  if (S.desk.done || !S.card || S.desk.minute == null) return void ($("quick").innerHTML = "");
  const left = S.desk.calls_left ?? 0;
  $("quick").innerHTML = `<div class="hd"><b>Quick play</b><span>the desk's optimizer, three clicks a wake-up</span></div>
    <ol>
      <li><button type="button" class="btn ${!fresh ? "go" : "done"}" data-q="opt"><b>Ask optimize</b><small>${fresh ? `expects ${usd(p.projected?.expected ?? 0)}` : "1 call · risk 1.5, DAM spread"}</small></button></li>
      <li><button type="button" class="btn ${fresh && !q.sent ? "go" : q.sent ? "done" : ""}" data-q="send"><b>Submit its proposal</b><small>${q.sending ? "sending…" : q.sent === "none" ? "nothing to send" : q.sent ? `${q.sent} call${q.sent === 1 ? "" : "s"} sent` : fresh ? `${proposalCalls(p)} calls` : "after optimize"}</small></button></li>
      <li><button type="button" class="btn ${q.sent ? "go" : ""}" data-q="end"><b>End turn</b><small>the market runs to your next wake-up</small></button></li>
    </ol>
    <div class="auto"><span>${S.auto ? `Autopilot: turn ${S.desk.turn}, ${esc(short(d0(), S.desk.minute))}` : "Or repeat all three at every wake-up to the end"}</span><button type="button" class="btn sm ${S.auto ? "solid" : ""}" data-q="auto">${S.auto ? "Stop" : "Autopilot"}</button></div>
    <p class="note">This is what the anchor reference does at each wake-up; it scores R = 1 on most windows. ${left < 14 ? `${left} calls left this turn.` : "Beat it by hand with the tools above."}</p>`;
  renderBarButtons();
}

function proposalCalls(p) {
  const days = (gs) => new Set((gs || []).map((g) => g.day)).size;
  const rt = (p.rt_curves || []).filter((g) => S.desk.minute >= 1440 * +g.day.slice(1) - 360);
  return days([...(p.dam_curves || []), ...(p.dam_as_offers || [])]) + days([...rt, ...(p.rt_as_offers || [])]) + (p.cop || []).length;
}

function marketShell() {
  $("p-market").innerHTML = `<div id="p-market-chart"></div><div id="p-market-more"></div>`;
  return $("p-market-chart");
}

function renderMarket() {
  if (!S.chart) return;
  const m = S.market, v = S.view;
  const fc = Object.values(m.fc).sort((a, b) => (a.market === "rt") - (b.market === "rt"));
  const plan = S.proposal?.schedule && !S.desk.done ? planOf(S.proposal) : null;
  S.chart.update({
    now: S.t, dam: m.dam, series: Object.values(m.series), fc, plan, dayOf: (iso) => dateDay(d0(), iso), dateOf: (j) => isoDay(d0(), j),
    m: v?.m || [], soc: v?.soc || [site().soc0], soc0: site().soc0, pnl: v?.pnl || [], settled: v?.settled || { upto: 0, total: 0 },
  });
  const got = [
    ...Object.keys(m.dam).map((d) => `DAM ${dateLabel(d)}`),
    ...Object.values(m.series).map((s) => `${s.label} from ${short(d0(), s.x0)}`),
    ...Object.entries(m.fc).map(([k, f]) => `Desk ${f.market === "rt" ? "RT" : "DAM"} forecast ${dateLabel(k.split("|")[1])}${f.issued ? `, issued ${when(f.issued)}` : ""}`),
  ];
  const dam = S.wakes.flatMap((w) => (w.events || []).filter((e) => e.kind === "dam_results"));
  const done = S.desk.done || S.phase !== "turn";
  $("p-market-more").innerHTML = `${got.length ? "" : '<p class="muted">Prices and forecasts appear here once you ask for them: each one is a call, as it is for an agent. The battery, its charge and the settled dollars come from the market\'s run.</p>'}
    ${done ? "" : `<div class="chips" style="margin-top:8px">${asks().map(([label, name, args]) => `<button type="button" class="btn sm" data-ask='${esc(JSON.stringify([name, args]))}'>${esc(label)} <span class="k">1 call</span></button>`).join("")}</div>`}
    ${got.length ? `<h3>From your calls</h3><div class="chips">${got.slice(-12).map((g) => `<span class="chip">${esc(g)}</span>`).join("")}</div>` : ""}
    ${dam.length ? `<h3>DAM results</h3>${dam.map((e) => `<p class="muted">${esc(e.text)}</p>`).join("")}` : ""}`;
}

/** One-click reads under the chart: the desk forecast for the next DAM still open, today's DAM prices, and
 * the latest SCED prices; each is an ordinary call. */
function asks() {
  const now = S.desk.minute ?? -1080, n = S.card.dates.length;
  const open = now < -840 ? 0 : Math.floor((now + 840) / 1440) + 1, today = now < 0 ? -1 : Math.floor(now / 1440);
  return [
    ...(open < n ? [[`Desk DAM forecast, D${open}`, "get_forecasts", { kind: "price", market: "dam", day: `D${open}` }]] : []),
    [`DAM prices, D${today}`, "get_prices", { market: "dam", day: `D${today}` }],
    ["Latest SCED prices", "get_prices", { market: "sced" }],
  ];
}

function planOf(p) {
  const hrs = (p.schedule.hourly_mw || []).map((s) => {
    const [h, v] = s.split(":");
    const mm = /HE(\d+)(?:@D(\d+))?/.exec(h);
    return [60 * (+mm[1] - 1) + 1440 * +(mm[2] || 0), +v];
  });
  const from = minuteOf(p.schedule.from, d0());
  const x0 = Math.floor(Math.max(0, from) / 60) * 60, n = 24;
  const mwv = Array.from({ length: n }, (_, i) => hrs.find(([t]) => t === x0 + 60 * i)?.[1] ?? 0);
  return { x0, mw: mwv };
}

function renderPlan() {
  const p = S.proposal, days = Object.keys(S.plan).sort();
  const fresh = p && p.minute === S.desk.minute;
  const prop = p ? `<div class="plan-sec"><h3>The optimizer's latest proposal</h3>
      <p class="muted">Asked ${esc(at(d0(), p.minute))}${fresh || S.desk.done ? "" : ", before your last wake-up: ask again for a fresh one"}.</p>
      <div class="entry"><div class="out">${render("optimize", {}, p)}</div></div>
      ${fresh && !S.desk.done ? `<div class="chips" style="margin-top:8px"><button type="button" class="btn sm go" data-q="send">Submit this proposal</button><button type="button" class="btn sm" data-fill="submit_dam_offers">Edit its DA offers</button><button type="button" class="btn sm" data-fill="submit_rt_offers">Edit its RT offers</button></div>` : ""}</div>` : `<div class="plan-sec"><h3>The optimizer</h3><p class="muted"><b>Optimize</b> co-optimises the DAM and real time on a price view (by default the desk's forecast) and proposes curves, reserve offers and a COP. It submits nothing.</p></div>`;
  const rows = days.map((dk) => {
    const p2 = S.plan[dk], last = (xs) => xs?.at(-1);
    const cell = (xs) => (xs?.length ? `${esc(last(xs).hours)}<br><span class="muted">${esc(short(d0(), last(xs).minute))}${xs.length > 1 ? ` · ${xs.length} sends` : ""}</span>` : '<span class="muted">none</span>');
    const as = (xs) => (xs?.length ? `+ ${Object.keys(last(xs).as).map(esc).join(", ")}` : "");
    return `<tr><td><b>${esc(dk)}</b><br><span class="muted">${esc(dateLabel(isoDay(d0(), +dk.slice(1))))}</span></td><td>${cell(p2.dam)}${as(p2.dam_as) ? `<br><span class="muted">${as(p2.dam_as)}</span>` : ""}</td><td>${cell(p2.rt)}${as(p2.rt_as) ? `<br><span class="muted">${as(p2.rt_as)}</span>` : ""}</td><td>${cell(p2.cop)}</td></tr>`;
  }).join("");
  $("p-plan").innerHTML = `${prop}<div class="plan-sec"><h3>What you submitted</h3>${days.length ? `<table class="t"><thead><tr><th>Day</th><th>DAM offers</th><th>RT curves</th><th>COP</th></tr></thead><tbody>${rows}</tbody></table><p class="muted">Accepted hours as the desk reported them. DAM curves stay in force in real time until RT curves replace them; with no curve ERCOT uses a proxy curve.</p>` : '<p class="muted">Nothing yet. Without offers the battery sits on ERCOT\'s proxy curve: it charges only at −$250 and discharges only at $2,000.</p>'}</div>`;
}

function renderCalls() {
  $("b-calls").textContent = S.unseen && S.tab !== "calls" ? String(S.unseen) : "";
  if (S.tab !== "calls" && $("p-calls").dataset.n === String(S.log.length)) return;
  $("p-calls").dataset.n = String(S.log.length);
  const items = [...S.log].reverse().map((e) => {
    if (e.kind === "wake") return `<article class="entry wk"><header><span class="n">T${e.turn}</span><code>${esc(wakeTitle(e.wake))}</code><span class="t">${esc(short(d0(), e.minute))}</span></header><div class="out"><ul>${(e.wake.events || []).map(eventLine).join("") || "<li>No new events</li>"}</ul></div><details><summary>Exact message</summary><pre>${esc(e.text)}</pre></details></article>`;
    if (e.kind === "end") return `<article class="entry wk"><header><span class="n">End</span><code>The window is graded</code><span class="t">${esc(short(d0(), e.minute))}</span></header><div class="out">P ${usd(e.res.p)} · C ${pct(e.res.capture)} · R ${num(e.res.reward, 3)}</div><details><summary>Exact answer</summary><pre>${esc(e.text)}</pre></details></article>`;
    const err = e.res?.error;
    return `<article class="entry${err ? " err" : ""}"><header><span class="n">${e.n}</span><code>${esc(e.tool)}</code><span class="t">T${e.turn} · ${esc(short(d0(), e.minute))}</span></header>${argLine(e.args) ? `<div class="args">${esc(argLine(e.args))}</div>` : ""}<div class="out">${render(e.tool, e.args, e.res)}</div><details><summary>Exact answer, as an agent reads it</summary><pre>${esc(e.text)}</pre></details></article>`;
  });
  $("p-calls").innerHTML = items.length ? `<div class="log">${items.join("")}</div>` : '<p class="muted">Every call you make and every wake-up you get, with the exact text an agent would read.</p>';
}

function renderBrief() {
  const key = `${S.card?.task_id}|${S.brief.length}|${S.desk.max_turns}`;
  if ($("p-brief").dataset.key === key) return;
  $("p-brief").dataset.key = key;
  $("p-brief").innerHTML = `<div class="brief"><p class="note"><b>The desk brief.</b> This is the system prompt every benchmark model got for this window, word for word. You play under the same rules: ${S.desk.max_turns || 100} turns, ${S.desk.calls_per_turn || 14} tool calls per turn, a clock that is frozen while you work, and the same grade.</p><pre>${esc(S.brief.split(/\n\s*\n/).map((p) => p.replace(/\n(?!- )\s*/g, " ")).join("\n\n"))}</pre><p class="muted" style="margin-top:12px">Code: <a href="${CODE}" target="_blank" rel="noopener">hub/openenv</a> on GitHub. Prices and system data: ERCOT public reports (ERCOT does not endorse this work). Weather: NWS alerts and IEM ASOS observations.</p></div>`;
}

function renderPlate() {
  const c = S.card;
  if (!c) return;
  const busy = S.phase === "run";
  $("plate").innerHTML = `<div class="k">${esc(c.site.region)} · ${esc(cap(c.front.kind))}</div><h2>${esc(c.site.name)}, ${esc(c.site.size)}</h2><p>${esc(dateSpan(c.dates))}${busy || !S.wake ? "" : S.desk.done ? " · settled" : ` · ${esc(wakeTitle(S.wake))}`}</p>`;
}

/* ---------------- the end card ---------------- */

function finish() {
  if (!S.grade || !S.view?.bench) return;
  S.session.close();
  const g = S.grade, b = S.view.bench, refs = b.refs, c = S.card;
  const cOf = (p) => (refs.p_hind - refs.p_idle > 1 ? (p - refs.p_idle) / (refs.p_hind - refs.p_idle) : null);
  const rows = [["hind", "Hindsight", "The best possible: every price known in advance", refs.p_hind], ["you", "You", "Your desk", g.p], ["anchor", "Anchor", "The desk's optimizer at every wake-up", refs.p_anchor], ["op", "Real operator", "The battery's operator, as it ran (ERCOT's 60-day disclosures)", refs.p_operator_actual], ["opr", "Operator, replayed", "The operator's own offers, replayed in this market", refs.p_operator_replay], ["idle", "Idle", "No offers at all", refs.p_idle]].filter((r) => r[3] != null);
  const lo = Math.min(0, ...rows.map((r) => r[3])), hi = Math.max(1, ...rows.map((r) => r[3]));
  const X = (v) => (100 * (v - lo)) / (hi - lo);
  const bars = rows.map(([k, name, title, v]) => `<div class="row ${k}"><span class="nm" title="${esc(title)}">${esc(name)}</span><span class="tr"><span class="z" style="left:${X(0)}%"></span><b style="left:${Math.min(X(0), X(v))}%;width:${Math.max(0.6, Math.abs(X(v) - X(0)))}%"></b></span><span class="v">${usd(v)}</span></div>`).join("");
  const ms = b.models.filter((r) => r[1] != null);
  const rank = 1 + ms.filter((r) => r[1] > (g.capture ?? -Infinity)).length;
  const best = ms[0];
  const viewer = `${VIEWER}?v=bench&m=${best ? best[0] : "sol"}&task=${encodeURIComponent(c.task_id)}`;
  $("end").innerHTML = `<div class="sheet" role="dialog" aria-labelledby="end-h">
    <button type="button" class="x" data-act="close" aria-label="Close, to watch your run on the site" title="Close, to watch your run on the site">×</button>
    <div class="l">
    <div class="eyebrow">Window over · ${esc(at(d0(), T1()))}</div>
    <h2 id="end-h">Your desk settled ${usd(g.p)}</h2>
    <p class="lede">${g.valid ? "" : "No submission was accepted, so the reward is 0. "}${g.capture != null ? `That is ${pct(g.capture)} of what perfect hindsight could have earned on this window` : "Hindsight could not earn more than idle on this window"}${refs.p_operator_actual != null ? `, against ${pct(cOf(refs.p_operator_actual))} for the battery's real operator` : ""}.</p>
    <div class="big"><div><span>Profit P</span><b>${usd(g.p)}</b><small>settled by ERCOT's rules</small></div><div><span>Capture C</span><b>${pct(g.capture)}</b><small>of hindsight, above idle</small></div><div><span>Reward R</span><b>${num(g.reward, 2)}</b><small>0.2 at idle, 1 at the anchor</small></div></div>
    <div class="acts"><button type="button" class="btn go" data-act="again">Play this window again</button><button type="button" class="btn" data-act="pick">Another window</button><a class="btn" href="${viewer}" target="_blank" rel="noopener">See how ${esc(best ? S.models[best[0]]?.tag || best[0] : "the models")} played it ↗</a></div>
    </div>
    <div class="r">
    <div class="bars"><h3>Settled on this window</h3>${bars}</div>
    <div class="strip"><h3>Against the 15 models on this window</h3><p>${ms.length ? `You would rank ${rank} of ${ms.length + 1}. Best: ${esc(S.models[best[0]]?.name || best[0])} at ${pct(best[1])}.` : ""}</p>
      <svg id="end-strip" aria-label="Hindsight capture of each model on this window, with yours"></svg></div>
    <p class="src">C = (P − P_idle) / (P_hindsight − P_idle). The operator's numbers come from ERCOT's 60-day disclosures; the models' from the v4 benchmark, each in its native harness.</p>
    </div>
  </div>`;
  showEnd();
  strip(ms, g.capture ?? 0, cOf(refs.p_anchor));
}

function showEnd() {
  $("end").hidden = false;
  if (matchMedia("(max-width: 760px)").matches) requestAnimationFrame(() => $("end").scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" }));
}

/** Each model's C on this window as a dot, yours larger, on an axis drawn at the card's own width. */
function strip(ms, mine, anchor) {
  const svg = $("end-strip"), W = Math.max(240, svg.clientWidth || 560), H = 64;
  const cs = [...ms.map((r) => r[1]), mine, anchor ?? 0];
  const cmin = Math.min(0, ...cs), cmax = Math.max(0.5, ...cs);
  const sx = (v) => 12 + ((v - cmin) / (cmax - cmin)) * (W - 24);
  const ticks = [-0.5, -0.25, 0, 0.25, 0.5, 0.75, 1, 1.25].filter((v) => v >= cmin - 1e-9 && v <= cmax + 1e-9);
  const dots = ms.map(([k, cv], i) => `<circle class="mdl" cx="${sx(cv).toFixed(1)}" cy="${30 + ((i % 3) - 1) * 6}" r="5" style="fill:var(--c-${k}, var(--ink-3))"><title>${esc(S.models[k]?.name || k)} ${pct(cv)}</title></circle>`).join("");
  const best = ms[0], bx = best ? sx(best[1]) : 0, yx = sx(mine);
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.innerHTML = `<line class="axis" x1="12" x2="${W - 12}" y1="47" y2="47"/>${ticks.map((v) => `<line class="axis" x1="${sx(v)}" x2="${sx(v)}" y1="45" y2="49"/><text class="tk" x="${sx(v)}" y="61" text-anchor="middle">${Math.round(v * 100)}%</text>`).join("")}${dots}${best && Math.abs(bx - yx) > 60 ? `<text class="tk" x="${bx}" y="13" text-anchor="${bx > W - 60 ? "end" : bx < 60 ? "start" : "middle"}">${esc(S.models[best[0]]?.tag || best[0])}</text>` : ""}<circle class="you" cx="${yx}" cy="30" r="7"/><text class="you-l" x="${yx}" y="13" text-anchor="${yx > W - 30 ? "end" : yx < 30 ? "start" : "middle"}">You</text>`;
}

/* ---------------- the stage, the transport and the loop ---------------- */

function loop(now) {
  const dt = Math.min(0.1, (now - (loop.last || now)) / 1000);
  loop.last = now;
  S.wall += dt;
  if (S.anim) {
    const u = Math.min(1, (now - S.anim.start) / S.anim.dur), e = u < 0.5 ? 2 * u * u : 1 - (-2 * u + 2) ** 2 / 2;
    S.t = S.anim.a + (S.anim.b - S.anim.a) * e;
    if (u >= 1) {
      S.anim = null;
      S.phase = S.desk.done ? "over" : "turn";
      if (S.desk.done) finish();
      renderAll();
    }
  } else if (S.playing) {
    const to = S.desk.done ? T1() : S.desk.minute;
    S.t = Math.min(to, S.t + dt * 60 * 3);
    if (S.t >= to) S.playing = false;
  }
  const active = S.anim || S.playing || now - S.lastInput < 2500 || S.wall < 3;
  if (S.site?.stage && !document.hidden && (active || now - (loop.drawn || 0) > 66)) {
    loop.drawn = now;
    const f = S.site.frame(S.t, dt, S.wall);
    tag(f);
    weather(f);
  }
  readout();
  scrubHandle();
  run();
  requestAnimationFrame(loop);
}

function battery(t) {
  const v = S.view;
  if (!v || t < 0 || !v.m.length) return { mw: 0, soc: v?.soc?.[0] ?? site().soc0, pre: t < 0 };
  const k = Math.max(0, Math.min(v.m.length - 1, Math.floor(t / 5))), u = Math.min(1, (t - 5 * k) / 5);
  return { mw: v.m[k], soc: v.soc[k] + ((v.soc[k + 1] ?? v.soc[k]) - v.soc[k]) * u };
}

function tag(f) {
  const y = S.site.yard();
  let el = $("tags").firstElementChild;
  if (!el) {
    $("tags").innerHTML = '<div class="tag"><div class="card glass"><div class="what"><i></i><span></span></div><div class="soc"><span class="bar"><b></b></span><span class="v"></span></div></div><div class="stem"></div></div>';
    el = $("tags").firstElementChild;
  }
  const b = battery(S.t), mwv = b.mw;
  const text = b.pre ? "Waiting at its starting charge" : S.t >= T1() ? "Window over" : mwv > 1.5 ? `Discharging ${mw(mwv)}` : mwv < -1.5 ? `Charging ${mw(mwv)}` : "Idle";
  const pctv = Math.max(0, Math.min(1, b.soc / site().emax));
  const key = `${text}|${Math.round(pctv * 200)}`;
  if (el.dataset.key !== key) {
    el.dataset.key = key;
    el.className = `tag ${mwv > 1.5 ? "discharge" : mwv < -1.5 ? "charge" : ""}`;
    el.querySelector(".what span").textContent = text;
    el.querySelector(".bar b").style.width = `${(100 * pctv).toFixed(1)}%`;
    el.querySelector(".v").textContent = `${Math.round(b.soc)} of ${Math.round(site().emax)} MWh`;
  }
  const show = y && y.vis && $("boot").classList.contains("gone") && $("end").hidden;
  el.style.display = show ? "" : "none";
  if (show) el.style.transform = `translate(${y.x}px, ${y.y}px) translate(-50%, -100%)`;
}

function weather(f) {
  const chips = [];
  const sky = S.site.sky(f);
  if (sky) chips.push(`<span class="glass">${esc(sky)}</span>`);
  const t = S.t, seen = new Set();
  for (const e of [...(S.view?.events || [])].reverse()) {
    if (e.t_min > t || chips.length > 3) continue;
    if (e.kind === "weather" && (e.severity === "Warning" || e.severity === "Watch" || /Warning|Watch/.test(e.event || ""))) {
      const end = minuteOf(e.expires, d0());
      if ((end == null || end > t) && !seen.has(e.event)) seen.add(e.event) && chips.push(`<span class="glass alert">NWS ${esc(e.event)}</span>`);
    } else if (e.kind === "notice" && t - e.t_min < 240 && /Watch|Emergency|Advisory|EEA|OCN/i.test(e.level || "") && !seen.has(e.title)) {
      seen.add(e.title) && chips.push(`<span class="glass alert notice">ERCOT ${esc(e.level)}</span>`);
    }
  }
  const html = chips.join("");
  if ($("wx").dataset.html !== html) ($("wx").dataset.html = html), ($("wx").innerHTML = html);
}

function run() {
  const on = S.phase === "run" && !!S.anim;
  const text = on ? `The market runs: ${short(d0(), Math.floor(S.t / 5) * 5)} → ${short(d0(), S.anim.b)}` : "";
  if ($("run").dataset.text !== text) {
    $("run").dataset.text = text;
    $("run").querySelector("span").textContent = text;
    $("run").classList.toggle("on", on);
  }
}

function readout() {
  if (S.desk.minute == null) {
    $("readout").innerHTML = $("readout").dataset.html = "";
    $("play").disabled = true;
    return;
  }
  const now = S.desk.done ? T1() : S.desk.minute;
  const back = S.t < (now ?? 0) - 1 && !S.anim;
  const html = S.card ? `<b>${esc(short(d0(), Math.floor(S.t)))}</b>${back ? `replay · now ${esc(short(d0(), now))}` : S.anim ? "market running" : S.desk.done ? "settled" : "now"}` : "";
  if ($("readout").dataset.html !== html) ($("readout").dataset.html = html), ($("readout").innerHTML = html);
  const icon = S.playing ? "M4 2.5h3v11H4zM9 2.5h3v11H9z" : "M4 2.5v11l9.5-5.5z";
  if ($("play-icon").getAttribute("d") !== icon) $("play-icon").setAttribute("d", icon);
  $("play").disabled = !back && !S.playing;
}

const NS = "http://www.w3.org/2000/svg";
function drawScrub() {
  const host = $("scrub");
  if (!S.card) return;
  const W = Math.max(200, host.clientWidth), H = host.clientHeight || 42, PAD = 8, TY = 15;
  const t0 = -1080, t1 = T1(), X = (t) => PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  const now = S.desk.done ? t1 : S.desk.minute ?? t0;
  const ticks = S.wakes.map((w) => {
    const why = w.reasons || [], cls = why.some((r) => EVENTFUL.has(r)) ? "ev" : why.length === 1 && why[0] === "reminder" ? "rem" : why.every((r) => r === "checkpoint") ? "ck" : "";
    return `<line class="wk ${cls}" x1="${X(w.minute)}" x2="${X(w.minute)}" y1="${TY - 6}" y2="${TY + 6}"/>`;
  }).join("");
  const days = [];
  for (let j = -1; j < S.card.dates.length; j++) {
    const a = Math.max(t0, 1440 * j), b = Math.min(t1, 1440 * j + 1440);
    if (j >= 0) days.push(`<line class="daymark" x1="${X(1440 * j)}" x2="${X(1440 * j)}" y1="${TY - 8}" y2="${TY + 8}"/>`);
    days.push(`<text class="tk day" x="${(X(a) + X(b)) / 2}" y="${TY + 21}" text-anchor="middle">${esc(W < 420 ? day(d0(), a).split(" ")[0] : day(d0(), a))}</text>`);
  }
  host.innerHTML = `<svg viewBox="0 0 ${W} ${H}"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line class="hatch" x1="0" y1="0" x2="0" y2="6"/></pattern></defs>
    <rect class="trk" x="${PAD}" y="${TY - 2}" width="${W - 2 * PAD}" height="4" rx="2"/><rect class="fut" x="${X(now)}" y="${TY - 5}" width="${Math.max(0, X(t1) - X(now))}" height="10"/>
    <rect class="known" x="${PAD}" y="${TY - 2}" width="${Math.max(0, X(now) - PAD)}" height="4" rx="2"/><rect class="played" id="sc-played" x="${PAD}" y="${TY - 2}" width="0" height="4" rx="2"/>
    ${days.join("")}${ticks}<line class="nowmark" x1="${X(now)}" x2="${X(now)}" y1="${TY - 9}" y2="${TY + 9}"/><circle class="handle" id="sc-h" cx="${X(S.t)}" cy="${TY}" r="6"/></svg>`;
  host.dataset.w = W;
}

function scrubHandle() {
  const host = $("scrub"), h = $("sc-h");
  if (!h || !S.card) return;
  const W = +host.dataset.w, PAD = 8, t0 = -1080, t1 = T1(), X = (t) => PAD + ((t - t0) / (t1 - t0)) * (W - 2 * PAD);
  const x = X(S.t).toFixed(1);
  if (h.getAttribute("cx") !== x) {
    h.setAttribute("cx", x);
    $("sc-played").setAttribute("width", Math.max(0, X(S.t) - PAD).toFixed(1));
    host.setAttribute("aria-valuenow", String(Math.round(S.t)));
  }
}

function transport() {
  const host = $("scrub");
  const seek = (e) => {
    if (!S.card || S.anim) return;
    const r = host.getBoundingClientRect(), PAD = 8, t0 = -1080, t1 = T1();
    const t = t0 + ((e.clientX - r.left - PAD) / (r.width - 2 * PAD)) * (t1 - t0);
    const now = S.desk.done ? t1 : S.desk.minute;
    S.t = Math.max(t0, Math.min(now, t));
    S.playing = false;
    S.lastInput = performance.now();
  };
  host.addEventListener("pointerdown", (e) => {
    host.setPointerCapture(e.pointerId);
    seek(e);
    host.onpointermove = seek;
  });
  host.addEventListener("pointerup", () => (host.onpointermove = null));
  host.addEventListener("keydown", (e) => {
    if (!["ArrowLeft", "ArrowRight", "End"].includes(e.key) || S.anim) return;
    e.preventDefault();
    const now = S.desk.done ? T1() : S.desk.minute;
    S.t = e.key === "End" ? now : Math.max(-1080, Math.min(now, S.t + (e.key === "ArrowRight" ? 60 : -60)));
    S.lastInput = performance.now();
  });
  $("play").addEventListener("click", () => {
    if (S.playing) return void (S.playing = false);
    const now = S.desk.done ? T1() : S.desk.minute;
    if (S.t >= now - 1) S.t = -1080;
    S.playing = true;
  });
  $("stage").addEventListener("pointerdown", () => (S.lastInput = performance.now()));
  $("stage").addEventListener("wheel", () => (S.lastInput = performance.now()), { passive: true });
  new ResizeObserver(() => drawScrub()).observe(host);
}

/* ---------------- toolbar, cameras, tabs ---------------- */

function toolbar() {
  $("toolbar").innerHTML = TOOLBAR.map((t) => (t === "|" ? '<span class="sep"></span>' : t === "grow" ? '<span class="grow"></span>' : `<button type="button" class="btn sm ${t[0] === "end_turn" ? "solid" : ""}" data-tool="${t[0]}" title="${t[0] === "*" ? "Any desk tool with your own JSON arguments" : t[0] === "end_turn" ? "End your turn: the market runs to your next wake-up" : t[0]}">${t[0] === "end_turn" ? `${t[1]} <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8h9M8.5 4.5L12 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>` : esc(t[1])}</button>`)).join("");
  $("toolbar").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tool]");
    if (!b || b.disabled) return;
    const t = b.dataset.tool;
    if (t === "end_turn") return endTurn("");
    if (t === "get_asset_status") return call("get_asset_status", {});
    dialog(t);
  });
  document.addEventListener("click", (e) => {
    const q = e.target.closest("[data-q]");
    if (q && !q.disabled) {
      if (q.dataset.q === "opt") quickOptimize();
      else if (q.dataset.q === "send") quickSubmit();
      else if (q.dataset.q === "end") quickEnd();
      else if (q.dataset.q === "auto") autopilot();
      return;
    }
    const ask = e.target.closest("[data-ask]");
    if (ask && S.phase === "turn" && !S.busy) {
      const [name, args] = JSON.parse(ask.dataset.ask);
      return call(name, args);
    }
    const fill = e.target.closest("[data-fill]");
    if (fill && S.phase === "turn") return dialog(fill.dataset.fill, { fill: true });
    const act = e.target.closest("[data-act]");
    if (act?.dataset.act === "close") return void ($("end").hidden = true);
    if (act?.dataset.act === "results") return showEnd();
    if (act?.dataset.act === "again") return S.card && restart(S.card);
    if (act?.dataset.act === "pick") return picker();
    if (act?.dataset.act === "resume") return resume();
    if (act?.dataset.act === "restart") return restart(S.card);
  });
  $("w-pick").addEventListener("click", picker);
}

function cams() {
  $("cams").classList.add("glass");
  $("cams").innerHTML = CAMS.map(([k, label]) => `<button type="button" data-cam="${k}" aria-pressed="${k === ""}">${label}</button>`).join("");
  $("cams").addEventListener("click", (e) => {
    const b = e.target.closest("[data-cam]");
    if (!b || !S.site) return;
    S.site.camera(b.dataset.cam);
    camPressed(b.dataset.cam);
    S.lastInput = performance.now();
  });
}

function camPressed(k) {
  for (const b of $("cams").querySelectorAll("button")) b.setAttribute("aria-pressed", String(b.dataset.cam === k));
}

function tabs() {
  document.querySelector(".tabs").addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) setTab(b.dataset.tab);
  });
}

function setTab(tab) {
  S.tab = tab;
  for (const b of document.querySelectorAll(".tabs [data-tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  for (const p of document.querySelectorAll(".panel")) p.hidden = p.dataset.panel !== tab;
  if (tab === "calls") S.unseen = 0;
  if (tab === "market") renderMarket();
  renderCalls();
}

function flash(name) {
  if (["get_prices", "get_forecasts"].includes(name)) setTab("market");
  else if (["submit_dam_offers", "submit_rt_offers", "update_cop"].includes(name)) setTab("plan");
  else setTab("calls");
}

function log(e) {
  if (e.kind === "call") e.n = S.log.filter((x) => x.kind === "call").length + 1;
  S.log.push(e);
  if (S.tab !== "calls") S.unseen++;
}

/* ---------------- dialogs ---------------- */

const DAYS = ["D-1", "D0", "D1", "D2"];
const SEGS = {
  market: ["dam", "rt", "sced", "as_dam", "as_rt", "asdc"], point: ["node", "hub"], step: ["", "5m", "15m", "1h"],
  kind: ["price", "as_price", "load", "wind", "solar", "net_load", "outages", "weather"], fmarket: ["dam", "rt"], detail: ["summary", "hourly"],
  ckind: ["dam", "rt", "cop"],
};
const FORMS = {
  get_prices: { title: "Prices", text: "Posted prices only: the DAM by hour, real-time settlement prices every 15 minutes, SCED prices every 5 minutes, at your node or your hub; and the AS prices and demand curves.", fields: [["market", "seg", "market", "dam"], ["point", "seg", "point", "node"], ["day", "seg", DAYS, "D0"], ["step", "seg", "step", ""], ["start", "text", "start (optional)", ""], ["end", "text", "end (optional)", ""]] },
  get_forecasts: { title: "Forecasts", text: "As-issued forecasts: the desk's price forecast (P10, P50, P90; modelled), ERCOT's load, wind, solar and net load, outage capacity and NWS alerts.", fields: [["kind", "seg", "kind", "price"], ["market", "seg", "fmarket", "dam"], ["day", "seg", DAYS.slice(1), "D0"], ["vintage", "text", "vintage", "latest"]] },
  get_grid_conditions: { title: "Grid conditions", text: "System conditions on the 5-minute grid: reserves (PRC), system lambda, load, wind, solar, the EEA level and recent ERCOT notices.", fields: [["start", "text", "start (optional)", ""], ["end", "text", "end (optional)", ""]] },
  get_position: { title: "Position", text: "Your book: DAM awards, real-time dispatch, the curves in force, your COP and the shadow statement.", fields: [["day", "seg", DAYS.slice(1), "D0"], ["detail", "seg", "detail", "summary"]] },
  optimize: { title: "Optimize", text: "Co-optimises the DAM and real time on your price view and proposes curves, reserve offers and a COP, with projected profit. It submits nothing and never sees prices that have not posted. The fields start at the anchor's settings; the tool's own defaults are risk 0.5 and a physical DAM position.", fields: [["price_view", "text", 'price view ("desk" or JSON)', "desk"], ["risk", "range", "risk: 0 acts on the median, up to 2 widens curves to the scenario range", 1.5], ["dam_position", "seg", ["spread", "physical"], "spread"], ["end_soc_mwh", "text", "end state of charge, MWh (optional)", ""], ["max_cycles", "text", "max cycles (optional)", ""]] },
  submit_dam_offers: { title: "DA offers", text: "DAM offers for an operating day: one Energy Bid/Offer Curve per hour, 2–10 [MW, $/MWh] points from max charge (negative MW) to max discharge, due before 10:00 the day before. Reserve offers ride in as_offers.", fields: [["day", "seg", DAYS.slice(1), "D0"], ["curves", "json", "curves", [{ hours: "HE18-HE21", points: [[0, -250], [0, 80], [100, 81], [100, 5000]] }]], ["as_offers", "json", "as_offers (optional)", null]] },
  submit_rt_offers: { title: "RT offers", text: "Real-time curves from 18:00 the day before until each hour ends; each change applies from the next 5-minute SCED run.", fields: [["day", "seg", DAYS.slice(1), "D0"], ["curves", "json", "curves", [{ hours: "HE18-HE21", points: [[0, -250], [0, 80], [100, 81], [100, 2000]] }]], ["as_offers", "json", "as_offers (optional)", null]] },
  update_cop: { title: "COP", text: "Your Current Operating Plan per hour: status, HSL/LSL, HBSOC and MinSOC/MaxSOC. An hour freezes 60 minutes before it starts.", fields: [["day", "seg", DAYS.slice(1), "D0"], ["rows", "json", "rows", [{ hours: "HE01-HE24", hbsoc_mwh: 50 }]]] },
  check_submission: { title: "Check", text: "Validate a DAM, RT or COP submission without sending it, with ERCOT-style codes; for DAM curves, where they would clear at the desk's P50.", fields: [["kind", "seg", "ckind", "dam"], ["payload", "json", "payload: the arguments of the matching submit tool", { day: "D0", curves: [{ hours: "HE18-HE21", points: [[0, -250], [0, 80], [100, 81], [100, 5000]] }] }]] },
  set_reminder: { title: "Reminder", text: "Wake yourself at a time on the 5-minute grid. Ending your turn waits until the next wake-up: a milestone, an event, or your reminder.", fields: [["at", "text", 'at ("D0 14:00", "18:30" or "Tue 08-18 09:00")', "D0 09:00"], ["note", "text", "note", ""]] },
};

function dialogs() {
  $("dialog").addEventListener("click", (e) => e.target.closest("[data-close]") && closeDialog());
  $("picker").addEventListener("click", (e) => e.target.closest("[data-close]") && ($("picker").hidden = true));
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") (closeDialog(), ($("picker").hidden = true));
  });
}

function closeDialog() {
  $("dialog").hidden = true;
}

function proposalArgs(tool) {
  const p = S.proposal;
  if (!p) return null;
  const key = { submit_dam_offers: ["dam_curves", "dam_as_offers"], submit_rt_offers: ["rt_curves", "rt_as_offers"] }[tool];
  if (key) {
    const curves = (p[key[0]] || []).filter((g) => tool === "submit_dam_offers" || S.desk.minute >= 1440 * +g.day.slice(1) - 360);
    const dayKey = curves[0]?.day || "D0";
    const as = (p[key[1]] || []).filter((a) => a.day === dayKey).map(({ day: _d, ...a }) => a);
    return { day: dayKey, curves: curves.filter((g) => g.day === dayKey).map((g) => ({ hours: g.hours, points: g.points })), as_offers: as.length ? as : null };
  }
  if (tool === "update_cop" && p.cop?.length) return { day: p.cop[0].day, rows: p.cop.filter((r) => r.day === p.cop[0].day).map((r) => ({ hours: r.hours, hbsoc_mwh: r.hbsoc_mwh })) };
  return null;
}

function dialog(tool, { fill = false } = {}) {
  const spec = FORMS[tool], form = $("form");
  const all = tool === "*";
  const pre = fill ? proposalArgs(tool) : null;
  const vals = {};
  const segHtml = (name, opts, cur) => `<div class="seg" data-seg="${name}">${opts.map((o) => `<button type="button" data-v="${esc(o)}" aria-pressed="${o === cur}">${esc(o === "" ? "default" : o)}</button>`).join("")}</div>`;
  let body;
  if (all) {
    const names = Object.keys(S.tools).filter((n) => n !== "end_turn");
    body = `<label class="fld"><span>tool</span><select id="f-tool">${names.map((n) => `<option>${esc(n)}</option>`).join("")}</select></label><p class="desc" id="f-desc"></p><label class="fld"><span>arguments <small>JSON, sent as written</small></span><textarea id="f-args" spellcheck="false">{}</textarea></label><details><summary class="muted">Input schema</summary><pre id="f-schema" class="muted" style="white-space:pre-wrap;font:500 11px/1.45 var(--mono)"></pre></details>`;
  } else {
    body = spec.fields.map(([name, kind, label, def]) => {
      const v = pre && name in pre ? pre[name] : def;
      vals[name] = v;
      if (kind === "seg") return `<div class="fld"><span>${esc(name)}</span>${segHtml(name, Array.isArray(label) ? label : SEGS[label], v)}</div>`;
      if (kind === "range") return `<label class="fld"><span>${esc(label)} <small id="f-${name}-v">${v}</small></span><input type="range" id="f-${name}" min="0" max="2" step="0.05" value="${v}"></label>`;
      if (kind === "json") return `<label class="fld"><span>${esc(label)} <small>JSON</small></span><textarea id="f-${name}" spellcheck="false">${v == null ? "" : esc(JSON.stringify(v, null, 1))}</textarea></label>`;
      return `<label class="fld"><span>${esc(label)}</span><input type="text" id="f-${name}" value="${esc(v ?? "")}" autocomplete="off"></label>`;
    }).join("");
  }
  const submitTool = ["submit_dam_offers", "submit_rt_offers", "update_cop"].includes(tool);
  const left = S.desk.calls_left ?? 0;
  form.innerHTML = `<h2 id="d-title">${esc(all ? "Any tool" : spec.title)} <code>${esc(all ? "" : tool)}</code></h2>${all ? "" : `<p class="desc">${esc(spec.text)}</p>`}${body}
    <div class="err" id="f-err"></div>
    <div class="foot">${submitTool && S.proposal ? '<button type="button" class="btn sm ghost" id="f-fill">Fill from the optimizer</button>' : ""}<span class="grow"></span><span class="cost">uses 1 of ${left} calls left</span>${submitTool ? '<button type="button" class="btn" id="f-check">Check</button>' : ""}<button type="submit" class="btn go">${submitTool ? "Submit" : "Call"}</button></div>`;
  place($("dialog"));
  $("dialog").hidden = false;
  if (all) {
    const pickTool = () => {
      const t = S.tools[$("f-tool").value];
      $("f-desc").textContent = t?.description || "";
      $("f-schema").textContent = JSON.stringify(t?.input_schema || {}, null, 1);
    };
    $("f-tool").addEventListener("change", pickTool);
    pickTool();
  }
  form.querySelectorAll("[data-seg]").forEach((g) => g.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (!b) return;
    for (const x of g.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x === b));
  }));
  form.querySelector("input[type=range]")?.addEventListener("input", (e) => ($(`f-${e.target.id.slice(2)}-v`).textContent = e.target.value));
  $("f-fill")?.addEventListener("click", () => {
    const p = proposalArgs(tool);
    if (!p) return;
    for (const [k, v] of Object.entries(p)) {
      const ta = $(`f-${k}`);
      if (ta) ta.value = v == null ? "" : JSON.stringify(v, null, 1);
      const seg = form.querySelector(`[data-seg="${k}"]`);
      if (seg) for (const x of seg.querySelectorAll("button")) x.setAttribute("aria-pressed", String(x.dataset.v === v));
    }
  });
  const collect = () => {
    if (all) return [$("f-tool").value, JSON.parse($("f-args").value || "{}")];
    const args = {};
    for (const [name, kind] of spec.fields) {
      if (kind === "seg") {
        const v = form.querySelector(`[data-seg="${name}"] [aria-pressed="true"]`)?.dataset.v;
        if (v) args[name] = v;
      } else if (kind === "range") args[name] = +$(`f-${name}`).value;
      else if (kind === "json") {
        const s = $(`f-${name}`).value.trim();
        if (s) args[name] = JSON.parse(s);
      } else {
        const s = $(`f-${name}`).value.trim();
        if (s) args[name] = name === "end_soc_mwh" || name === "max_cycles" ? +s : s;
      }
    }
    if (tool === "optimize") {
      const pv = args.price_view;
      const out = { price_view: pv && pv.startsWith("{") ? JSON.parse(pv) : pv || "desk", risk: args.risk, constraints: { dam_position: args.dam_position } };
      if (args.end_soc_mwh != null) out.constraints.end_soc_mwh = args.end_soc_mwh;
      if (args.max_cycles != null) out.constraints.max_cycles = args.max_cycles;
      return [tool, out];
    }
    if (tool === "get_forecasts" && args.kind !== "price" && args.kind !== "as_price") delete args.market;
    if (tool === "get_prices" && args.market.startsWith("as")) delete args.point;
    return [tool, args];
  };
  const send = async (asCheck) => {
    let name, args;
    try {
      [name, args] = collect();
    } catch (e) {
      $("f-err").textContent = `Arguments: ${e.message}`;
      return;
    }
    if (asCheck) [name, args] = ["check_submission", { kind: { submit_dam_offers: "dam", submit_rt_offers: "rt", update_cop: "cop" }[tool], payload: args }];
    closeDialog();
    await call(name, args);
    if (!asCheck && ["get_prices", "get_forecasts"].includes(name)) setTab("market");
  };
  form.onsubmit = (e) => (e.preventDefault(), send(false));
  $("f-check")?.addEventListener("click", () => send(true));
  form.querySelector("input, textarea, select, button")?.focus();
}

function picker() {
  const box = $("pk");
  const fronts = {};
  for (const c of S.cards) (fronts[c.front.date] ||= []).push(c);
  box.innerHTML = `<h2 id="pk-title">Choose a window</h2><p class="desc">The v4 benchmark's 32 windows: four real batteries across eight Texas weather fronts, three operating days each. Hollow dots are before the models' training cutoffs, filled after.</p>
    <div class="list">${Object.values(fronts).map((cs) => `<div class="grp"><i class="cut ${esc(cs[0].cutoff)}"></i>${esc(cap(cs[0].front.kind))}${cs[0].front.name ? `, ${esc(cs[0].front.name)}` : ""} <span>${esc(dateSpan(cs[0].dates))}</span></div>${cs.map((c) => `<button type="button" class="pick" data-i="${c.index}" aria-current="${c.task_id === S.card?.task_id}"><b>${esc(c.site.name)}, ${esc(c.site.region)}</b><span>${esc(c.site.size)}${c.dates[0] !== cs[0].dates[0] ? ` · ${esc(dateSpan(c.dates))}` : ""} · #${c.index}</span></button>`).join("")}`).join("")}</div>
    <div class="foot" style="display:flex;margin-top:14px"><span class="grow" style="flex:1"></span><button type="button" class="btn" data-close>Close</button></div>`;
  box.onclick = (e) => {
    const b = e.target.closest("[data-i]");
    if (!b) return;
    $("picker").hidden = true;
    restart(S.cards[+b.dataset.i]);
  };
  place($("picker"));
  $("picker").hidden = false;
}

/** A dialog covers the part of the frame the Space's window shows: on a phone the frame is as tall as the page. */
function place(el) {
  let f = null;
  try {
    f = window.frameElement;
  } catch {}
  if (!f) return;
  const r = f.getBoundingClientRect(), top = Math.max(0, -r.top), bottom = Math.min(r.height, parent.innerHeight - r.top);
  Object.assign(el.style, { top: `${top}px`, height: `${Math.max(240, bottom - top)}px` });
}

/* ---------------- dropped sessions ---------------- */

function dropped(text, { capacity = false } = {}) {
  if (S.ended && !capacity) return;
  S.ended = true;
  S.auto = false;
  S.anim = null;
  S.busy = false;
  const n = S.moves.length;
  $("drop").innerHTML = `<i></i><span>${esc(text)} ${capacity ? "" : n ? `Your ${n} move${n === 1 ? "" : "s"} are kept: the desk is deterministic, so replaying them restores this exact moment.` : ""}</span>${!capacity && n ? '<button type="button" class="btn sm go" data-act="resume">Reconnect and replay my moves</button>' : ""}<button type="button" class="btn sm" data-act="restart">${capacity ? "Try again" : "Restart this window"}</button>`;
  $("drop").hidden = false;
  $("boot").classList.add("gone");
  renderAll();
}

function hideDrop() {
  $("drop").hidden = true;
}

async function resume() {
  const moves = S.moves.slice();
  S.session.close();
  S.session = session();
  await open(S.card, { moves });
}

async function restart(card) {
  S.auto = false;
  S.session.close();
  S.session = session();
  await open(card);
}

/* ---------------- helpers ---------------- */

function dateSpan(dates) {
  const a = new Date(`${dates[0]}T12:00:00Z`), b = new Date(`${dates.at(-1)}T12:00:00Z`);
  const M = (x) => x.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  return a.getUTCMonth() === b.getUTCMonth() ? `${a.getUTCDate()}–${b.getUTCDate()} ${M(b)} ${b.getUTCFullYear()}` : `${a.getUTCDate()} ${M(a)}–${b.getUTCDate()} ${M(b)} ${b.getUTCFullYear()}`;
}

const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");
const when = (label) => {
  const m = minuteOf(label, d0());
  return m == null ? label : short(d0(), m);
};

/** The frame in the Try Environment tab fills the Space's window below the tab's controls, down to FIT_MIN, so a page or
 * an embed 820 px tall shows the whole desk without scrolling. On a phone the page is one tall column: the frame takes
 * the page's full height, so only the Space's page scrolls. */
function fitFrame() {
  let f = null;
  try {
    f = window.frameElement;
  } catch {}
  if (!f || !f.getClientRects().length) return;
  if (matchMedia("(max-width: 760px)").matches) return void (f.style.height = `${document.documentElement.scrollHeight}px`);
  const top = f.getBoundingClientRect().top + parent.scrollY;
  f.style.height = `${Math.max(FIT_MIN, Math.floor(parent.innerHeight - top - FIT_GAP))}px`;
}
new ResizeObserver(fitFrame).observe(document.body);
try {
  parent.addEventListener("resize", fitFrame);
} catch {}

main().catch((e) => {
  console.error(e);
  $("boot").querySelector("span").textContent = `The page could not start: ${e.message}`;
});
