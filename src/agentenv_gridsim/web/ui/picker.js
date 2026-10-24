import { grade, money } from "../data.js";
import { POINTS } from "../places.js";
import { ATTRIBUTION, modelName } from "./hud.js";

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const REGION = { west: "West Texas", panhandle: "Panhandle", north: "North Texas", houston: "Houston", south: "South Texas", central: "Central Texas" };

/** The run list: a featured day, filters, sort and a link per episode into the replay. */
export async function picker(app, q) {
  const url = q.get("index") || "runs/index.json";
  let index;
  try {
    index = await (await fetch(url)).json();
  } catch (e) {
    app.innerHTML = `<div class="error"><p>No run index at ${esc(url)}.</p></div>`;
    return;
  }
  const base = url.replace(/[^/]*$/, "");
  const runs = index.episodes.map((e) => ({ ...e, href: `index.html?episode=${encodeURIComponent(base + e.url)}` }));
  document.body.classList.add("list-page");
  const state = { model: q.get("model") || "", tier: q.get("tier") || "", bundle: q.get("bundle") || "", region: q.get("region") || "", text: q.get("q") || "", sort: q.get("sort") || "reward" };
  const opts = (k) => [...new Set(runs.map((r) => r[k]).filter(Boolean))].sort();
  const hero = runs.find((r) => r.hero) || runs[0];
  app.innerHTML = `<div class="list">
    <header><div><h1>GridSimEnv <span>· The Battery Desk</span></h1>
      <p>A model runs one grid battery in Texas for one day: it reads the day's 24 hourly ERCOT day-ahead prices, commits 24 charge and discharge actions, and is graded against the exact optimum. Every replay below is a recorded episode, shown in the place's real light and weather.</p></div></header>
    ${hero ? featured(hero) : ""}
    <section class="filters card">
      ${sel("model", "Model", opts("model"), (m) => modelName(m))}
      ${sel("tier", "Tier", opts("tier"))}
      ${sel("bundle", "Bundle", opts("bundle"))}
      ${sel("region", "Region", opts("region"), (r) => REGION[r] || r)}
      <label>Search<input name="text" placeholder="date, point, task" value="${esc(state.text)}"></label>
      <label>Sort<select name="sort">${[["reward", "Reward (high first)"], ["low", "Reward (low first)"], ["date", "Date"], ["profit", "Profit"]].map(([v, l]) => `<option value="${v}" ${state.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <span class="count"></span>
    </section>
    <section class="rows card"><table><thead><tr><th>Day</th><th>Settlement point</th><th>Battery</th><th>Model</th><th>Tier</th><th>Bundle</th><th class="r">Profit</th><th class="r">Reward</th></tr></thead><tbody></tbody></table></section>
    <footer>${ATTRIBUTION} Replays only: nothing here runs a model. Scene and art are procedural (CC0); three.js is MIT.</footer></div>`;
  const tbody = app.querySelector("tbody");
  const count = app.querySelector(".count");
  const render = () => {
    const t = state.text.toLowerCase();
    let rows = runs.filter((r) => (!state.model || r.model === state.model) && (!state.tier || r.tier === state.tier) && (!state.bundle || r.bundle === state.bundle) && (!state.region || r.region === state.region) && (!t || `${r.date} ${r.point} ${r.task_id} ${r.model}`.toLowerCase().includes(t)));
    const by = { reward: (a, b) => (b.reward ?? -1) - (a.reward ?? -1), low: (a, b) => (a.reward ?? 2) - (b.reward ?? 2), date: (a, b) => (a.date < b.date ? 1 : -1), profit: (a, b) => (b.profit ?? 0) - (a.profit ?? 0) }[state.sort];
    rows = rows.sort(by);
    count.textContent = `${rows.length} of ${runs.length} episodes`;
    tbody.innerHTML = rows.slice(0, 600).map((r) => `<tr onclick="location.href='${r.href}'"><td><a href="${r.href}">${esc(r.date)}</a></td><td><b>${esc(r.point)}</b> <span class="dim">${esc(POINTS[r.point]?.name || "")}</span></td><td class="dim">${esc(r.battery)}</td><td>${esc(modelName(r.model))}</td><td><span class="tier ${esc(r.tier)}">${esc(r.tier)}</span></td><td class="dim">${esc(r.bundle)}</td><td class="r num">${r.profit == null ? "—" : money(r.profit)}</td><td class="r num"><span class="g ${r.reward == null ? "" : grade(r.reward)}">${r.reward == null ? "" : grade(r.reward)}</span> ${r.reward == null ? "—" : r.reward.toFixed(3)}</td></tr>`).join("");
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) if (v && !(k === "sort" && v === "reward")) p.set(k === "text" ? "q" : k, v);
    history.replaceState(null, "", `${location.pathname}${p.toString() ? "?" + p : ""}`);
  };
  app.querySelectorAll("select, input").forEach((el) => el.addEventListener("input", () => {
    state[el.name] = el.value;
    render();
  }));
  render();
  function sel(name, label, values, show = (v) => v) {
    return `<label>${label}<select name="${name}"><option value="">All</option>${values.map((v) => `<option value="${esc(v)}" ${state[name] === v ? "selected" : ""}>${esc(show(v))}</option>`).join("")}</select></label>`;
  }
}

function featured(r) {
  const thumb = r.thumb ? `<img src="${esc(r.thumb)}" alt="${esc(r.point)} on ${esc(r.date)}: the battery yard at ${esc(r.hero_moment || "the day's key hour")}">` : "";
  return `<a class="hero card" href="${r.href}">${thumb}<div class="txt"><h5>Featured day</h5><h2>${esc(r.date)} · ${esc(r.point)} <span>${esc(POINTS[r.point]?.name || "")}</span></h2>
    <p>${esc(r.blurb || "")}</p><p class="dim">${esc(modelName(r.model))} · ${esc(r.tier)} · reward ${r.reward == null ? "—" : r.reward.toFixed(3)}</p><span class="go">Watch the replay →</span></div></a>`;
}
