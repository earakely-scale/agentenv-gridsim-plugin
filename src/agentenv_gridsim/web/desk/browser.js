/** The episode browser: each version's eval pack as a grid of days (or three-day windows) by battery, every cell one
 * model's replay with its hindsight capture and settled dollars; a few picks first. */
import { esc, num, shortSpan, usd } from "./fmt.js";

const MODELS = [["sol", "GPT-6.1 Sol"], ["luna", "GPT-6 Luna"], ["qwen", "Qwen3-4B"]];
const WX = { "freezing rain": "Freezing rain", "snow and sleet": "Snow and sleet", thunderstorms: "Thunderstorms", "hard freeze": "Hard freeze", "extreme heat": "Extreme heat", rain: "Rain" };
const $ = (id) => document.getElementById(id);

export function buildSheet(C, { onPick }) {
  const box = $("sheet");
  const st = { v: null, m: "sol", key: null, opener: null };
  const n = Object.keys(C.episodes).length;
  $("sheet-sub").textContent = `Every model on every task of each version's eval pack: ${Object.keys(C.tasks).length} tasks, ${n} recorded episodes. Each opens on the battery site in 3D beside its desk.`;

  function render() {
    const V = C.versions.find((x) => x.version === st.v) || C.versions[0];
    $("vtabs").innerHTML = C.versions.map((x) => `<button type="button" role="tab" aria-selected="${x === V}" data-v="${x.version}"><b>${x.version} ${esc(x.name)}</b><span>${x.tasks.length} ${x.days_per_task > 1 ? `${x.days_per_task}-day windows` : "battery-days"}</span></button>`).join("");
    $("adds").innerHTML = `${esc(V.adds[0].toUpperCase() + V.adds.slice(1))}.`;
    const picks = C.featured.filter((f) => C.episodes[f.key]);
    $("ctl").innerHTML = `<div class="seg" role="group" aria-label="Model">${MODELS.filter(([k]) => V.models.includes(k)).map(([k, l]) => `<button type="button" data-m="${k}" aria-pressed="${k === st.m}">${l}</button>`).join("")}</div>
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
      return `<td class="cell"><button type="button" data-k="${key}" aria-current="${key === st.key}" aria-label="${esc(`${t.name}, ${t.region}, ${label(t.dates[0])}: C ${c}, P ${usd(e.P)}`)}"><span class="cv"><b>${c}</b><span>${usd(e.P, { compact: true })}</span></span><span class="heat ${st.m}"><i style="width:${(100 * w).toFixed(0)}%"></i></span>${marks ? `<span class="marks">${marks}</span>` : ""}</button></td>`;
    };
    $("grid").innerHTML = `<div class="picks">${picks.map((f) => {
      const e = C.episodes[f.key], t = C.tasks[e.task];
      return `<button type="button" class="pick" data-k="${f.key}" aria-current="${f.key === st.key}"><span class="pv">${e.version}</span><b>${esc(f.why)}</b><span>${esc(t.name)}, ${esc(t.region)}, ${label2(t)}; ${esc(MODELS.find(([k]) => k === e.model)[1])}</span></button>`;
    }).join("")}</div>
      <table class="eps"><thead><tr><th></th>${sites.map((s) => `<th scope="col">${esc(s.name)}<small>${esc(s.region)}, ${esc(s.size)}</small></th>`).join("")}</tr></thead><tbody>${days.map(row).join("")}</tbody></table>`;
  }
  const label2 = (t) => shortSpan(t.dates);

  box.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) return hide();
    const v = e.target.closest("[data-v]"), m = e.target.closest("[data-m]"), k = e.target.closest("[data-k]");
    if (v) (st.v = v.dataset.v), render();
    else if (m) (st.m = m.dataset.m), render();
    else if (k) {
      hide();
      onPick(k.dataset.k);
    }
  });
  box.addEventListener("keydown", (e) => {
    if (e.key === "Escape") hide();
    if (e.key === "Tab") {
      const f = [...box.querySelectorAll("button, a[href]")].filter((x) => x.offsetParent);
      if (e.shiftKey && document.activeElement === f[0]) (e.preventDefault(), f.at(-1).focus());
      else if (!e.shiftKey && document.activeElement === f.at(-1)) (e.preventDefault(), f[0].focus());
    }
  });

  function show(key) {
    const e = C.episodes[key];
    st.key = key;
    st.v = e.version;
    st.m = e.model;
    st.opener = document.activeElement;
    render();
    box.hidden = false;
    requestAnimationFrame(() => box.classList.add("on"));
    (box.querySelector(`[data-k="${key}"]`) || box.querySelector("[data-close]")).focus({ preventScroll: true });
  }
  function hide() {
    box.classList.remove("on");
    box.hidden = true;
    st.opener?.focus?.();
  }
  return { show, hide };
}
