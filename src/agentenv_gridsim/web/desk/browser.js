/** The episode browser. The v4 benchmark first: every model's run on every three-day window as a row with its C, R, P,
 * cost and whether it made a valid submission, filtered by model, side of the training cutoffs, front and battery and
 * sorted by any column. Then the development runs: each version's eval pack as a grid of days (or three-day windows)
 * by battery, every cell one model's replay, a few picks first. */
import { esc, num, pc, shortSpan, usd } from "./fmt.js";

const ORDER = ["sol", "luna", "qwen"];
const WX = { "freezing rain": "Freezing rain", "snow and sleet": "Snow and sleet", thunderstorms: "Thunderstorms", "hard freeze": "Hard freeze", "extreme heat": "Extreme heat", rain: "Rain" };
const SORTS = { window: 1, C: -1, R: -1, P: -1, usd: -1 };
const WORDS = ["none", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"];
const $ = (id) => document.getElementById(id);

export function buildSheet(C, { onPick }) {
  const box = $("sheet"), B = C.versions.find((x) => x.role === "bench"), dev = C.versions.filter((x) => x !== B);
  const st = { v: null, m: "sol", key: null, opener: null, f: { m: "", split: "", front: "", site: "" }, sort: "window", dir: 1 };
  const runs = Object.entries(C.episodes).filter(([, e]) => e.version === "bench");
  $("sheet-sub").textContent = `Every recorded run, each on the battery site in 3D beside its desk: the v4 benchmark's ${runs.length}, then ${Object.keys(C.episodes).length - runs.length} development runs on the desk's own runner.`;

  function render() {
    const V = C.versions.find((x) => x.version === st.v) || C.versions[0];
    const name = (x) => x.label || `${x.version} ${x.name}`;
    const size = (x) => (x.role === "check" ? `${x.check_of}'s ${x.tasks.length} battery-days, re-cleared` : `${x.tasks.length} ${x.days_per_task > 1 ? `${x.days_per_task}-day windows` : "battery-days"}`);
    const tab = (x) => (x === B ? `<button type="button" role="tab" aria-selected="${x === V}" data-v="${x.version}" class="bench"><b>${esc(name(x))}</b><span>${Object.keys(x.roster).length} models in native agent harnesses, ${x.tasks.length} three-day windows</span></button>`
      : `<button type="button" role="tab" aria-selected="${x === V}" data-v="${x.version}" class="dev ${x.role}" aria-label="${esc(`${name(x)}, ${size(x)}`)}">${esc(x.role === "check" ? `${x.version} check` : x.version)}</button>`);
    $("vtabs").innerHTML = `${B ? tab(B) : ""}<span class="vlab" role="presentation">Development runs</span>${dev.map(tab).join("")}`;
    if (V === B) return bench();
    $("adds").innerHTML = `<b>${esc(name(V))}</b>, ${esc(size(V))}, on the desk's own runner. ${V.role === "check" ? `A price-impact check, not a step on the ladder: ${V.check_of}'s battery-days again, each day-ahead market re-cleared with the desk's own offers in ERCOT's offer stack for the day.` : `${esc(V.adds[0].toUpperCase() + V.adds.slice(1))}.`}`;
    if (!V.models.includes(st.m)) st.m = V.models[0];
    const picks = C.featured.filter((f) => C.episodes[f.key]);
    $("ctl").innerHTML = `<div class="seg two" role="group" aria-label="Model">${ORDER.filter((k) => V.models.includes(k)).map((k) => `<button type="button" data-m="${k}" aria-pressed="${k === st.m}" aria-label="${esc(C.models[k].label)}"><b>${esc(C.models[k].name)}</b><small>${esc(C.models[k].setting)}</small></button>`).join("")}</div>
      <span class="hint">Cells: C, the share of the hindsight optimum's profit over idle, and P, the settled ERCOT statement.</span>`;
    const tasks = V.tasks.map((k) => [k, C.tasks[k]]);
    const sites = [...new Map(tasks.map(([, t]) => [t.site, t])).values()].sort((a, b) => a.site.localeCompare(b.site));
    const days = [...new Set(tasks.map(([, t]) => t.dates[0]))].sort();
    const label = (d) => shortSpan(tasks.find(([, x]) => x.dates[0] === d)[1].dates);
    const named = V.names || {};
    const row = (d) => `<tr><th scope="row" class="day">${label(d)}<small>${esc(named[d] || "")}</small></th>${sites.map((s) => cell(tasks.find(([, t]) => t.dates[0] === d && t.site === s.site))).join("")}</tr>`;
    const cell = (kt) => {
      if (!kt) return `<td class="cell empty"></td>`;
      const [k, t] = kt, key = `${k}.${st.m}`, e = C.episodes[key];
      if (!e) return `<td class="cell empty"></td>`;
      const marks = [t.pv ? '<i class="mk pv" title="Co-located solar, modelled">Solar</i>' : "", t.wx ? `<i class="mk cond">${esc(WX[t.wx] || t.wx)}</i>` : "", C.featured.some((f) => f.key === key) ? '<i class="mk pick">Pick</i>' : ""].join("");
      const c = e.C == null ? "–" : num(e.C, 2);
      const w = e.C == null ? 0 : Math.max(0, Math.min(1, e.C));
      return `<td class="cell"><button type="button" data-k="${key}" aria-current="${key === st.key}" aria-label="${esc(`${C.models[st.m].label} on ${t.name}, ${t.region}, ${label(t.dates[0])}: C ${c}, P ${usd(e.P)}`)}"><span class="cv"><b>${c}</b><span>${usd(e.P, { compact: true })}</span></span><span class="heat ${st.m}"><i style="width:${(100 * w).toFixed(0)}%"></i></span>${marks ? `<span class="marks">${marks}</span>` : ""}</button></td>`;
    };
    $("grid").innerHTML = `<div class="picks">${picks.map((f) => {
      const e = C.episodes[f.key], t = C.tasks[e.task];
      return `<button type="button" class="pick" data-k="${f.key}" aria-current="${f.key === st.key}"><span class="pv">${e.version}${C.versions.find((x) => x.version === e.version)?.role === "check" ? " check" : ""}</span><b>${esc(f.why)}</b><span>${esc(t.name)}, ${esc(t.region)}, ${shortSpan(t.dates)}; <span class="nw">${esc(C.models[e.model].label)}</span></span></button>`;
    }).join("")}</div>
      <table class="eps"><thead><tr><th></th>${sites.map((s) => `<th scope="col">${esc(s.name)}<small>${esc(s.region)}, ${esc(s.size)}</small></th>`).join("")}</tr></thead><tbody>${days.map(row).join("")}</tbody></table>`;
  }

  function bench() {
    const R = B.roster, f = st.f, fronts = Object.fromEntries(B.fronts.map((x) => [x.front, x]));
    const sites = [...new Map(B.tasks.map((k) => [C.tasks[k].site, C.tasks[k]])).values()].sort((a, b) => a.site.localeCompare(b.site));
    const span = (x) => shortSpan([x.front, new Date(Date.parse(`${x.front}T12:00:00Z`) + (B.days_per_task - 1) * 864e5).toISOString().slice(0, 10)]);
    const n = B.models.length, word = WORDS[n] || String(n);
    $("adds").innerHTML = `${word[0].toUpperCase()}${word.slice(1)} models, each in its native agent harness at high effort, trade a real battery for three days at a time: ${B.fronts.length} real Texas weather fronts × ${sites.length} batteries, one run per model per window. C is the share of the hindsight optimum's profit over idle, R the contract's reward and P the settled ERCOT statement; the cost is the graded run's list-price tokens${Object.values(R).some((m) => m.basis === "gpu_time") ? ", or the open model's GPU time" : ""}.`;
    const opt = (v, cur, label) => `<option value="${esc(v)}"${v === cur ? " selected" : ""}>${esc(label)}</option>`;
    $("ctl").innerHTML = `<div class="filters">
      <div class="seg two fm" role="group" aria-label="Model"><button type="button" data-fm="" aria-pressed="${!f.m}"><b><span class="full">All ${word}</span><span class="nick">All</span></b><small>${runs.length} runs</small></button>${B.models.map((k) => `<button type="button" data-fm="${k}" aria-pressed="${f.m === k}" aria-label="${esc(R[k].label)}"><b><i class="dot ${k}"></i><span class="full">${esc(R[k].name)}</span><span class="nick">${esc(R[k].tag)}</span></b><small>${esc(R[k].harness)}</small></button>`).join("")}</div>
      <div class="seg two fs" role="group" aria-label="Side of the training cutoffs"><button type="button" data-fs="" aria-pressed="${!f.split}"><b>Both halves</b><small>${B.tasks.length} windows</small></button>${Object.entries(B.splits).map(([k, s]) => `<button type="button" data-fs="${k}" aria-pressed="${f.split === k}"><b><i class="side ${k}"></i>${esc(s.label)}</b><small>${esc(s.note)}</small></button>`).join("")}</div>
      <select data-ff aria-label="Weather front">${opt("", f.front, `All ${B.fronts.length} fronts`)}${B.fronts.filter((x) => !f.split || x.split === f.split).map((x) => opt(x.front, f.front, `${span(x)}, ${x.kind}${B.names[x.front] ? `, ${B.names[x.front]}` : ""}`)).join("")}</select>
      <select data-fb aria-label="Battery">${opt("", f.site, `All ${sites.length} batteries`)}${sites.map((s) => opt(s.site, f.site, `${s.name}, ${s.region}`)).join("")}</select></div>`;
    const rank = Object.fromEntries(B.models.map((k, i) => [k, i]));
    const keep = ([, e]) => (!f.m || e.model === f.m) && (!f.split || e.split === f.split) && (!f.front || e.front === f.front) && (!f.site || C.tasks[e.task].site === f.site);
    const off = (B.unscored || []).map((x) => [null, x]).filter(keep);
    const rows = [...runs.filter(keep), ...off]
      .sort(([ka, a], [kb, b]) => {
        const w = a.front.localeCompare(b.front) || C.tasks[a.task].site.localeCompare(C.tasks[b.task].site) || rank[a.model] - rank[b.model];
        return st.sort === "window" ? st.dir * w : !ka || !kb ? !ka - !kb || w : st.dir * (a[st.sort] - b[st.sort]) || w;
      });
    const scored = rows.filter(([k]) => k);
    const mean = f.m && scored.length ? scored.reduce((s, [, e]) => s + e.C, 0) / scored.length : null, invalid = scored.filter(([, e]) => !e.valid).length;
    const head = (k, l, cls) => `<button type="button" class="sort ${cls}" data-sort="${k}" aria-pressed="${st.sort === k}"${st.sort === k ? ` data-dir="${st.dir > 0 ? "up" : "down"}"` : ""}>${l}</button>`;
    let prev = null;
    const row = ([k, e]) => {
      const t = C.tasks[e.task], m = R[e.model], w = `${e.front}|${t.site}`, first = st.sort !== "window" || w !== prev;
      prev = w;
      if (!k) return `<div class="brow off${first ? " first" : ""}" role="note" aria-label="${esc(`${m.label} on ${t.name}, ${t.region}, ${shortSpan(t.dates)}: stopped by the ${e.why.replace(/, final$/, "")} after $${e.usd.toFixed(2)}, unscored`)}">
        <span class="w"><b>${shortSpan(t.dates)}</b><small>${esc(fronts[e.front].kind)}${B.names[e.front] ? `, ${esc(B.names[e.front])}` : ""}</small></span>
        <span class="s"><b>${esc(t.site)}</b><small>${esc(t.region)}</small></span>
        <span class="m"><b><i class="dot ${e.model}"></i>${esc(m.name)}</b><small>${esc(m.harness)}</small></span>
        <span class="x"><b>Capped</b><small>stopped by the ${esc(e.why.replace(/, final$/, ""))} after $${e.usd.toFixed(2)}; final and unscored, never imputed</small></span></div>`;
      return `<button type="button" class="brow${first ? " first" : ""}${e.valid ? "" : " void"}" data-k="${k}" aria-current="${k === st.key}" aria-label="${esc(`${m.label} on ${t.name}, ${t.region}, ${shortSpan(t.dates)}: C ${pc(e.C)}, R ${num(e.R, 2)}, P ${usd(e.P)}, cost $${e.usd.toFixed(2)}${e.valid ? "" : ", no valid submission"}`)}">
        <span class="w"><b>${shortSpan(t.dates)}</b><small>${esc(fronts[e.front].kind)}${B.names[e.front] ? `, ${esc(B.names[e.front])}` : ""}</small></span>
        <span class="s"><b>${esc(t.site)}</b><small>${esc(t.region)}</small></span>
        <span class="m"><b><i class="dot ${e.model}"></i>${esc(m.name)}</b><small>${esc(m.harness)}${k === C.lead ? '<i class="lead">Lead run</i>' : ""}</small></span>
        <span class="c"><b>${pc(e.C)}</b><i class="heat ${e.model}"><i style="width:${(100 * Math.max(0, Math.min(1, e.C))).toFixed(0)}%"></i></i></span>
        <span class="r"><small class="k">R </small>${num(e.R, 2)}</span>
        <span class="p"><small class="k">P </small>${usd(e.P, { compact: true })}</span>
        <span class="u"><small class="k">Cost </small>$${e.usd.toFixed(2)}${m.basis === "gpu_time" ? "<small> GPU</small>" : ""}</span>
        <span class="v">${e.valid ? '<i class="ok" aria-hidden="true">✓</i><small>Valid</small>' : '<i class="no" aria-hidden="true">✕</i><small>No valid submission</small>'}</span></button>`;
    };
    $("grid").innerHTML = `<p class="bsum" aria-live="polite"><b>${scored.length} run${scored.length === 1 ? "" : "s"}</b>${mean == null ? "" : ` · mean C ${pc(mean)}`}${invalid ? ` · ${invalid} without a valid submission` : ""}${off.length ? ` · ${off.length} capped window${off.length === 1 ? "" : "s"}, unscored` : ""}${rows.length ? "" : " · no run matches these filters"}</p>
      <div class="blist"><div class="bhead">${head("window", "Window", "w")}<span class="s">Battery</span><span class="m">Model, harness</span>${head("C", "C", "c")}${head("R", "R", "r")}${head("P", "P", "p")}${head("usd", "Cost", "u")}<span class="v">Valid</span></div>${rows.map(row).join("")}</div>`;
  }

  box.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) return hide();
    const v = e.target.closest("[data-v]"), m = e.target.closest("[data-m]"), k = e.target.closest("[data-k]");
    const fm = e.target.closest("[data-fm]"), fs = e.target.closest("[data-fs]"), so = e.target.closest("[data-sort]");
    if (v) (st.v = v.dataset.v), render();
    else if (m) (st.m = m.dataset.m), render();
    else if (fm) (st.f.m = fm.dataset.fm), render();
    else if (fs) {
      st.f.split = fs.dataset.fs;
      if (st.f.split && B.fronts.find((x) => x.front === st.f.front)?.split !== st.f.split) st.f.front = "";
      render();
    } else if (so) {
      st.dir = st.sort === so.dataset.sort ? -st.dir : SORTS[so.dataset.sort];
      st.sort = so.dataset.sort;
      render();
    } else if (k) {
      hide();
      onPick(k.dataset.k);
    }
  });
  box.addEventListener("change", (e) => {
    if (e.target.matches("[data-ff]")) (st.f.front = e.target.value), render();
    else if (e.target.matches("[data-fb]")) (st.f.site = e.target.value), render();
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
    if (e.key === "Tab") {
      const f = [...box.querySelectorAll("button, a[href], select")].filter((x) => x.offsetParent);
      if (e.shiftKey && document.activeElement === f[0]) (e.preventDefault(), f.at(-1).focus());
      else if (!e.shiftKey && document.activeElement === f.at(-1)) (e.preventDefault(), f[0].focus());
    }
  });

  function show(key) {
    const e = C.episodes[key];
    st.key = key;
    st.v = e.version;
    if (e.version !== "bench") st.m = e.model;
    st.opener = document.activeElement;
    render();
    box.hidden = false;
    requestAnimationFrame(() => box.classList.add("on"));
    const cur = box.querySelector(`[data-k="${CSS.escape(key)}"]`);
    cur?.scrollIntoView({ block: "center" });
    (cur || box.querySelector("[data-close]")).focus({ preventScroll: true });
  }
  function hide() {
    box.classList.remove("on");
    box.hidden = true;
    st.opener?.focus?.();
  }
  return { show, hide };
}
