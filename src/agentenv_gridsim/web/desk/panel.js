/** The desk beside the scene: the clock and the market's phase, the node's prices as posted, the battery and the
 * settled statement, the day's awards, every wake-up with its tool calls as the replay reaches it, and ERCOT's
 * statement at the end. */
import { buildCharts } from "./charts.js";
import { AS_NAMES, EVENTFUL, REASONS, clock, dayLong, dayShort, esc, mw as mwText, num, price, usd, weekday, when } from "./fmt.js";

const ACT = new Set(["submit_dam_offers", "submit_rt_offers", "update_cop", "optimize"]);
const MID = new Set(["check_submission", "set_reminder"]);
const LINES = { dam_energy: "DAM energy", rt_energy_imbalance: "RT imbalance", deviation: "Set-point deviation", load_allocated: "Load-allocated", dam_as_capacity: "DAM ancillary capacity", rt_as_imbalance: "RT ancillary imbalance", capacity_short: "Capacity short", failure_to_provide: "Failure to provide", pv_energy: "Solar energy", degradation: "Degradation", warranty_overage: "Warranty overage", end_soc_shortfall: "End-of-window energy" };
const REFS = [["p_anchor", "Anchor", "anchor"], ["p_operator_replay", "Operator's bids, replayed", "op"], ["p_operator_actual", "Operator, as settled", "op"], ["p_hind_phys", "Hindsight, DAM tied to dispatch", "hind"], ["p_hind", "Hindsight optimum", "hind"]];
const $ = (id) => document.getElementById(id);

/** Seconds each part of a turn holds at 1×: busy turns (an act or an event) slower than reading turns. */
export function plan(turn) {
  const busy = turn.calls.some((c) => ACT.has(c.n)) || turn.why.some((r) => EVENTFUL.has(r)) || turn.why.includes("dam_results");
  const steps = [];
  let s = busy ? 0.7 : 0.35;
  turn.calls.forEach((c, i) => {
    steps.push(s);
    s += ACT.has(c.n) ? (busy ? 0.85 : 0.55) : MID.has(c.n) ? 0.4 : busy ? 0.26 : 0.15;
  });
  const quote = turn.q ? s : null;
  if (turn.q) s += Math.min(busy ? 2.4 : 1.0, 0.6 + turn.q.length / 260);
  return { steps, quote, total: s + 0.2, busy };
}

export function buildPanel(M, { model }) {
  const T = M.T, E = M.E;
  const charts = buildCharts(M, $("charts"));
  const cache = {};
  const set = (id, html) => {
    if (cache[id] !== html) (cache[id] = html), ($(id).innerHTML = html);
  };
  const cls = (id, c) => {
    if (cache[`c-${id}`] !== c) (cache[`c-${id}`] = c), ($(id).className = c);
  };
  const feed = $("feed");
  feed.replaceChildren();
  const heads = [];
  const items = M.turns.map((x) => {
    const j = Math.floor(x.t / 1440);
    if (heads.at(-1)?.j !== j) {
      const h = document.createElement("h4");
      h.className = "dayhead later";
      h.innerHTML = `${esc(dayLong(M.d0, x.t))}<small>${j < 0 ? "the day before: bidding" : M.n > 1 ? `operating day ${j + 1} of ${M.n}` : "the operating day"}</small>`;
      feed.append(h);
      heads.push({ h, j, first: x.t });
    }
    const a = document.createElement("article");
    a.className = "turn later";
    a.dataset.i = x.i;
    const p = plan(x);
    x.plan = p;
    const sum = summary(x);
    a.innerHTML = `<button class="th" type="button" aria-expanded="false"><time>${clock(x.t)}</time><span class="why">${esc(x.why.map((r) => REASONS[r] || r).join(", "))}</span><span class="sum">${sum}</span></button>
      <div class="tb">${x.ev.length ? `<ul class="inbox">${x.ev.map((e) => `<li class="ev ${esc(e.k)}"><b>${esc(e.at)}</b> ${esc(e.x)}</li>`).join("")}</ul>` : ""}
      <ol class="calls">${x.calls.map((c, i) => call(c, i)).join("")}</ol>${x.q ? `<blockquote class="q">${esc(x.q)}</blockquote>` : ""}</div>`;
    a.querySelector(".th").addEventListener("click", () => {
      const open = !a.classList.contains("open");
      a.classList.toggle("open", open);
      a.querySelector(".th").setAttribute("aria-expanded", open);
      a.dataset.user = "1";
    });
    feed.append(a);
    return { a, calls: [...a.querySelectorAll(".call")], q: a.querySelector(".q"), x };
  });
  const endcard = document.createElement("section");
  endcard.className = "endcard later";
  endcard.innerHTML = statement(M, model);
  feed.append(endcard);
  let userScroll = 0;
  feed.addEventListener("wheel", () => (userScroll = performance.now()), { passive: true });
  feed.addEventListener("touchmove", () => (userScroll = performance.now()), { passive: true });
  $("foot").innerHTML = footer(M);
  const cmp = $("charts").querySelector(".legend");
  if (T.ghost?.anchor || T.ghost?.actual) {
    const lab = document.createElement("label");
    lab.className = "toggle small";
    lab.title = `Overlay the anchor's state of charge and settled dollars${T.ghost.actual ? ", and the real operator's metered state of charge" : ""}, up to the replay's minute`;
    lab.innerHTML = `<input type="checkbox"> Compare`;
    lab.querySelector("input").addEventListener("change", (e) => charts.setCompare(e.target.checked));
    cmp.append(lab);
  }

  let live = -1;
  function update(S) {
    const t = Math.max(M.t0, Math.min(M.t1, S.t)), hold = S.hold;
    head(t, S);
    charts.update(t);
    positions(t);
    let cur = -1;
    for (const it of items) {
      const x = it.x, held = hold && hold.turn.i === x.i;
      const done = !held && x.t <= S.t;
      const state = held ? "turn live" : done ? "turn past" : "turn later";
      if (it.state !== state) {
        it.state = state;
        it.a.classList.remove("live", "past", "later");
        it.a.classList.add(...state.split(" ").slice(1));
        if (!it.a.dataset.user) it.a.classList.toggle("open", held);
      }
      if (held) {
        cur = x.i;
        const p = hold.p, steps = x.plan.steps;
        it.calls.forEach((c, i) => {
          const on = p >= steps[i];
          c.classList.toggle("wait", !on);
          c.classList.toggle("cur", on && (i === steps.length - 1 ? x.plan.quote == null || p < x.plan.quote : p < steps[i + 1]));
        });
        it.q?.classList.toggle("wait", x.plan.quote == null || p < x.plan.quote);
      } else if (it.wasHeld) {
        it.calls.forEach((c) => c.classList.remove("wait", "cur"));
        it.q?.classList.remove("wait");
      }
      it.wasHeld = held;
      if (done || held) cur = Math.max(cur, x.i);
    }
    endcard.classList.toggle("later", S.t < M.t1);
    for (const hd of heads) hd.h.classList.toggle("later", S.t < hd.first);
    const n = items.filter((it) => it.state !== "turn later").length;
    set("feed-count", `${n} of ${items.length} turns, ${items.slice(0, n).reduce((a, it) => a + it.x.calls.length, 0)} calls`);
    if (cur !== live) {
      live = cur;
      const it = items[cur];
      if (it && performance.now() - userScroll > 5000) it.a.scrollIntoView({ block: hold ? "start" : "nearest", behavior: S.playing ? "smooth" : "auto" });
    }
    if (S.t >= M.t1 && endcard.dataset.shown !== "1" && performance.now() - userScroll > 5000) {
      endcard.dataset.shown = "1";
      endcard.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
    if (S.t < M.t1) endcard.dataset.shown = "";
  }

  function head(t, S) {
    set("clock", clock(t).replace(":", '<span class="colon">:</span>'));
    cls("clock", `clock${S.playing && !S.hold ? "" : " stopped"}`);
    const j = Math.floor(t / 1440);
    set("day", `${dayShort(M.d0, t)}<small>${t < 0 ? "the day before" : t >= M.t1 ? "settled" : M.n > 1 ? `operating day ${j + 1} of ${M.n}` : "operating day"}</small>`);
    const ph = phase(t);
    set("state", S.hold ? `${esc(model)} at work` : ph);
    cls("state", `state${S.hold ? " working" : t >= M.t1 ? " end" : ""}`);
    const dm = M.damNow(t);
    set("n-dam", !dm ? "–" : dm.pending != null ? `<span class="pend">posts ${esc(when(M.d0, dm.pending, t))}</span>` : `${price(dm.p)}<small>HE${String(dm.h + 1).padStart(2, "0")}${M.v5 && dm.real != null && Math.abs(dm.p - dm.real) >= 0.005 ? `, ${dm.p > dm.real ? "+" : "−"}${Math.abs(100 * (dm.p - dm.real)).toFixed(1)}¢ its offers` : ""}</small>`);
    const sc = M.lastSced(t);
    set("n-sced", sc ? `${price(sc.p)}<small>${clock(sc.at - 5)}</small>` : "–");
    const fc = M.forecastNow(t);
    set("n-fc", fc ? `${price(fc.p)}<small>issued ${clock(fc.at)}</small>` : "–");
    const b = M.battery(t), pct = Math.max(0, Math.min(1, b.soc / T.site.emax));
    const mode = b.pre ? "Waiting for the operating day" : b.end ? "Window over" : b.mw > 1.5 ? `Discharging ${mwText(b.mw)}` : b.mw < -1.5 ? `Charging ${mwText(b.mw)}` : "Idle";
    set("b-mode", `<i class="dot ${b.mw > 1.5 ? "dis" : b.mw < -1.5 ? "chg" : ""}"></i>${mode}`);
    const pv = M.pvAt(t);
    set("b-pv", pv == null ? "" : `<i class="dot pv"></i>Solar ${pv < 0.5 ? (M.pvRaw(t) > 0.5 ? "curtailed, price below zero" : "0 MW") : mwText(pv)} <span class="mod">modelled</span>`);
    set("b-soc", `${Math.round(b.soc)} of ${Math.round(T.site.emax)} MWh <small>${Math.round(100 * pct)}%</small>`);
    const bar = $("b-bar"), w = `${(100 * pct).toFixed(1)}%`;
    if (bar.style.width !== w) bar.style.width = w;
    const done = t >= M.t1, v = done ? E.grade.p : M.pnlAt(t);
    set("b-pnl", `<span class="${v < -0.5 ? "neg" : ""}">${usd(v)}</span>`);
    set("b-pnl-l", done ? "ERCOT's statement" : "Settled so far");
  }

  function phase(t) {
    if (t >= M.t1) return "Settled";
    if (t >= 0) return "Real time";
    if (t < -840) return "DAM open";
    if (t < M.posted[0]) return "DAM clearing";
    return t < -360 ? "Awards in" : "Offers for real time";
  }

  function positions(t) {
    const j = Math.max(0, Math.min(M.n - 1, Math.floor(t / 1440))), out = [];
    for (let k = j; k < M.n && out.length < 2; k++) {
      if (k > j && t < 1440 * (k - 1) - 1080) break;
      const day = weekday(M.d0, 1440 * k), aw = M.awardsFor(k, t);
      if (aw) {
        const sold = aw.hs.filter((x) => x > 0.05), bought = aw.hs.filter((x) => x < -0.05);
        const tot = (xs) => Math.round(xs.reduce((a, x) => a + Math.abs(x), 0));
        const energy = [sold.length ? `sold ${tot(sold)} MWh in ${sold.length} h` : "", bought.length ? `bought ${tot(bought)} MWh in ${bought.length} h` : ""].filter(Boolean).join(", ") || "no energy awards";
        const as = Object.entries(aw.as).map(([p, v]) => `${AS_NAMES[p] || p} ${Math.round(Math.max(...v))}`).join(", ");
        out.push(`<div><b>DAM ${day}</b> ${energy}${as ? `<span class="as">; reserves up to ${as} MW</span>` : ""}</div>`);
      } else {
        const close = 1440 * k - 840, subs = M.E.subs.filter((x) => x[0] <= t && x[1] === "submit_dam_offers" && x[4] && dayIndex(x[2], x[0]) === k).length;
        out.push(`<div><b>DAM ${day}</b> ${t < close ? `open to ${when(M.d0, close, t)}, ${subs ? `${subs} offer${subs > 1 ? "s" : ""} in` : "no offers yet"}` : `cleared, results ${when(M.d0, M.posted[k], t)}`}</div>`);
      }
    }
    set("pos", out.join(""));
  }

  function dayIndex(label, at) {
    if (/^D(-?\d+)$/.test(label || "")) return +label.slice(1);
    if (/^\d{4}-\d{2}-\d{2}$/.test(label || "")) return M.T.dates.indexOf(label);
    return Math.max(0, Math.floor(at / 1440) + 1);
  }

  return { update, charts };
}

function call(c, i) {
  const lines = (c.l || []).map((l) => `<span class="ln">${esc(l)}</span>`).join("");
  return `<li class="call ${esc(c.c)}" data-k="${i}"><span class="tool">${esc(c.n)}</span>${c.s ? `<span class="s">${esc(c.s)}</span>` : ""}${lines}${c.r ? `<span class="r">${esc(c.r)}</span>` : ""}</li>`;
}

function summary(x) {
  const acts = x.calls.filter((c) => ACT.has(c.n) || c.n === "set_reminder" || c.n === "check_submission");
  const reads = x.calls.length - acts.length;
  const chips = acts.map((c) => `<i class="${c.c === "no" ? "no" : c.n.startsWith("submit") || c.n === "update_cop" ? "ok" : ""}">${esc(c.h)}</i>`);
  if (reads) chips.push(`<i>${reads} read${reads > 1 ? "s" : ""}</i>`);
  return chips.join("") || "<i>no calls</i>";
}

function statement(M, model) {
  const g = M.E.grade, st = M.E.statement, refs = M.T.refs;
  const rows = [[model, g.p, "me"], ...REFS.filter(([k]) => refs[k] != null).map(([k, l, c]) => [l, refs[k], c])];
  const lo = Math.min(0, ...rows.map((r) => r[1])), hi = Math.max(...rows.map((r) => r[1]), 1);
  const x = (v) => (100 * (v - lo)) / (hi - lo);
  const bars = rows.map(([l, v, c]) => `<span class="${c === "me" ? "me" : ""}">${esc(l)}</span><span class="v">${usd(v)}</span><span class="bar"><i class="${c}" style="left:${Math.min(x(0), x(v)).toFixed(1)}%;width:${Math.max(0.6, Math.abs(x(v) - x(0))).toFixed(1)}%"></i><b style="left:${x(0).toFixed(1)}%"></b></span>`).join("");
  const lines = Object.entries(st.lines).filter(([, v]) => Math.abs(v) >= 0.5).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
    .map(([k, v]) => `<span>${esc(LINES[k] || k)}${st.modelled.includes(k) ? ' <small>modelled</small>' : ""}</span><span class="v">${usd(v, { sign: true })}</span>`).join("");
  return `<h3>ERCOT's statement</h3>
    <div class="big"><span>${usd(g.p)}</span><small>settled over the ${M.n > 1 ? `${M.n} operating days` : "operating day"}</small></div>
    <p class="cr">${g.capture == null ? "Hindsight capture undefined on this task" : `<b>C ${num(g.capture)}</b> of the hindsight optimum's profit over idle`}, <b>R ${num(g.reward, 2)}</b>${g.beats_anchor ? ", ahead of the anchor" : ""}.</p>
    <div class="refs">${bars}</div>
    <details><summary>Statement lines</summary><div class="lines">${lines}</div></details>`;
}

function footer(M) {
  const C = M.C;
  return `<p>ERCOT and NWS public data, IEM weather; PV, the desk forecast and degradation modelled. Not affiliated with ERCOT.</p>
    <p>The earlier viewer (v1 and the previews) is archived at <a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv/tree/${esc(C.archive)}" target="_blank" rel="noopener">revision ${esc(C.archive.slice(0, 7))}</a>.</p>`;
}
