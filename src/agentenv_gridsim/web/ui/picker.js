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
  const wx = q.get("wxbase") ? `&wxbase=${encodeURIComponent(q.get("wxbase"))}` : "";
  const runs = index.episodes.map((e) => ({ ...e, version: e.version || "v1", href: `index.html?episode=${encodeURIComponent(base + e.url)}${wx}` }));
  document.body.classList.add("list-page");
  const state = { version: q.get("version") || "", model: q.get("model") || "", tier: q.get("tier") || "", bundle: q.get("bundle") || "", region: q.get("region") || "", text: q.get("q") || "", sort: q.get("sort") || "reward" };
  const opts = (k) => [...new Set(runs.map((r) => r[k]).filter(Boolean))].sort();
  const hero = runs.find((r) => r.hero) || runs[0];
  const also = runs.filter((r) => r.featured && !r.hero);
  const labels = Object.fromEntries(runs.map((r) => [r.model, r.model_label]));
  app.innerHTML = `<div class="list">
    <header><div><h1>GridSimEnv <span>· The Battery Desk</span></h1>
      <p>A model runs one grid battery in Texas for one day: it reads the day's 24 hourly ERCOT day-ahead prices, commits 24 charge and discharge actions, and is graded against the exact optimum. Every replay below is a recorded episode, shown in the place's real light and weather.${runs.some((r) => r.version === "v2") ? ` <b>v2 preview, The Live Grid:</b> a day-ahead position the day before, then a 15-minute schedule re-planned at watches as real-time prices settle and ERCOT bulletins arrive.` : ""}${runs.some((r) => r.version === "v3") ? ` <b>v3 preview, Sun, Storage and Reserves:</b> a solar farm and a battery behind one meter, energy and five reserve products sold the day before, played live as ERCOT deploys them.` : ""}${runs.some((r) => r.version === "v4") ? ` <b>v4 preview, Weather Front:</b> the same plant over three operating days, each day's book bid at the 10 am DAM gate the day before, re-planned as weather runs, bulletins and prices arrive, on forecasts as they were issued.` : ""}</p></div></header>
    ${hero ? featured(hero) : ""}
    ${also.length ? `<section class="also">${also.map(featured).join("")}</section>` : ""}
    ${index.training ? `<section class="also">${trainingCards(index.training, base)}</section>` : ""}
    <section class="filters card">
      ${opts("version").length > 1 ? sel("version", "Version", opts("version"), (v) => VERSION[v] || v) : ""}
      ${sel("model", "Model", opts("model"), (m) => modelName(m, labels[m]))}
      ${sel("tier", "Tier", opts("tier"))}
      ${sel("bundle", "Bundle", opts("bundle"))}
      ${sel("region", "Region", opts("region"), (r) => REGION[r] || r)}
      <label>Search<input name="text" placeholder="date, point, task" value="${esc(state.text)}"></label>
      <label>Sort<select name="sort">${[["reward", "Score (high first)"], ["low", "Score (low first)"], ["date", "Date"], ["profit", "Profit"]].map(([v, l]) => `<option value="${v}" ${state.sort === v ? "selected" : ""}>${l}</option>`).join("")}</select></label>
      <span class="count"></span>
    </section>
    <section class="rows card"><table><thead><tr><th>Day</th><th>Settlement point</th><th>Battery</th><th>Model</th><th>Tier</th><th>Bundle</th><th class="r">Profit</th><th class="r">Score</th></tr></thead><tbody></tbody></table><button class="more" hidden>Show more</button></section>
    <footer>${ATTRIBUTION} Replays only: nothing here runs a model. Scene and art are procedural (CC0); three.js is MIT.</footer></div>`;
  const tbody = app.querySelector("tbody");
  const count = app.querySelector(".count");
  const more = app.querySelector(".more");
  const PAGE = 200;
  let shown = PAGE;
  let timer = 0;
  more.addEventListener("click", () => ((shown += PAGE * 3), render()));
  const render = () => {
    const t = state.text.toLowerCase();
    let rows = runs.filter((r) => (!state.version || r.version === state.version) && (!state.model || r.model === state.model) && (!state.tier || r.tier === state.tier) && (!state.bundle || r.bundle === state.bundle) && (!state.region || r.region === state.region) && (!t || `${r.date} ${r.point} ${r.task_id} ${r.model}`.toLowerCase().includes(t)));
    const sc = (r) => (r.version === "v2" ? r.r_opt : r.reward);
    const by = { reward: (a, b) => (sc(b) ?? -1) - (sc(a) ?? -1), low: (a, b) => (sc(a) ?? 2) - (sc(b) ?? 2), date: (a, b) => (a.date < b.date ? 1 : -1), profit: (a, b) => (b.profit ?? 0) - (a.profit ?? 0) }[state.sort];
    rows = rows.sort(by);
    count.textContent = `${rows.length} of ${runs.length} episodes`;
    more.hidden = rows.length <= shown;
    more.textContent = `Show more (${Math.min(shown, rows.length)} of ${rows.length} shown)`;
    tbody.innerHTML = rows.slice(0, shown).map((r) => `<tr onclick="location.href='${r.href}'"><td><a href="${r.href}">${esc(r.date)}</a>${r.days > 1 ? ` <span class="dim small">+${r.days - 1} days</span>` : ""}</td><td><b>${esc(r.point)}</b> <span class="dim">${esc(POINTS[r.point]?.name || "")}</span></td><td class="dim">${esc(r.battery)}</td><td>${esc(modelName(r.model, r.model_label))}${r.path === "B" && r.trained ? ` <span class="dim">${esc(r.trained.toUpperCase() === "GRPO" ? "GRPO" : r.trained)}${r.checkpoint_step != null ? ` step ${r.checkpoint_step}` : ""}</span>` : ""}</td><td>${r.version === "v4" ? `<span class="tier fc">v4 · ${esc(r.tier)}</span>` : r.version === "v3" ? `<span class="tier hyb">v3 · ${esc(r.tier)}</span>` : r.version === "v2" ? `<span class="tier live">v2 · ${esc(r.tier)}</span>` : `<span class="tier ${esc(r.tier)}">${esc(r.tier)}</span>`}</td><td class="dim">${esc(r.bundle)}</td><td class="r num">${r.profit == null ? "—" : money(r.profit)}</td><td class="r num">${r.version === "v4" ? `R ${r.reward == null ? "—" : r.reward.toFixed(3)}<br><span class="dim small">r_hind ${r.r_opt == null ? "—" : r.r_opt.toFixed(2)}${r.synthetic ? " · CI window" : ""}</span>` : r.version === "v3" ? `R ${r.reward == null ? "—" : r.reward.toFixed(3)}<br><span class="dim small">${r.r_opt == null ? "—" : Math.round(r.r_opt * 100) + "%"} hindsight${r.as_share != null ? ` · AS ${Math.round(r.as_share * 100)}%` : ""}</span>` : r.version === "v2" ? `${r.r_opt == null ? "—" : Math.round(r.r_opt * 100) + "%"} <span class="dim">hindsight</span><br><span class="dim small">R ${r.reward == null ? "—" : r.reward.toFixed(3)}</span>` : `<span class="g ${r.reward == null ? "" : grade(r.reward)}">${r.reward == null ? "" : grade(r.reward)}</span> ${r.reward == null ? "—" : r.reward.toFixed(3)}`}</td></tr>`).join("");
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state)) if (v && !(k === "sort" && v === "reward")) p.set(k === "text" ? "q" : k, v);
    history.replaceState(null, "", `${location.pathname}${p.toString() ? "?" + p : ""}`);
  };
  app.querySelectorAll("select, input").forEach((el) => el.addEventListener("input", () => {
    state[el.name] = el.value;
    shown = PAGE;
    clearTimeout(timer);
    timer = setTimeout(render, el.tagName === "INPUT" ? 120 : 0);
  }));
  render();
  function sel(name, label, values, show = (v) => v) {
    return `<label>${label}<select name="${name}"><option value="">All</option>${values.map((v) => `<option value="${esc(v)}" ${state[name] === v ? "selected" : ""}>${esc(show(v))}</option>`).join("")}</select></label>`;
  }
}

const KIND = { beats: "Blind: beats the forecasters", trails: "Blind: trails the forecasters", live: "v2 preview · The Live Grid (provisional anchor)", hybrid: "v3 preview · Sun, Storage and Reserves", forecast: "v4 preview · Weather Front" };
const VERSION = { v1: "v1 · day-ahead", v2: "v2 preview (provisional anchor)", v3: "v3 preview · solar + storage + reserves", v4: "v4 preview · Weather Front" };

function trainingCards(t, base) {
  const card = (k, kind, title, text) => t[k] ? `<a class="hero card small" href="index.html?${k}=${encodeURIComponent(base + t[k].url.replace(/^runs\//, ""))}">${t[k].thumb ? `<img src="${esc(t[k].thumb)}" alt="${esc(title)}" loading="lazy">` : ""}<div class="txt"><h5>${kind}</h5><h2>${esc(title)}</h2><p>${text}</p><span class="go">Watch →</span></div></a>` : "";
  const lv = t.levelup, rc = t.race;
  return card("levelup", "Training · LEVEL UP", `${(lv?.model || "").split("/").pop()} learns one battery-day`, lv ? `One held-out day (${esc(lv.task_id)}) replayed at ${lv.frames} checkpoints, the plan converging on the exact optimum; reward gain ${lv.gain >= 0 ? "+" : ""}${lv.gain.toFixed(2)}.${lv.note ? ` <b>${esc(lv.note.charAt(0).toUpperCase() + lv.note.slice(1))}.</b>` : ""}${lv.overall ? ` Over all ${esc(lv.overall)}${lv.reading ? `; the final model is ${esc(lv.reading)}` : ""}.` : ""}` : "") +
    card("race", "Training · Race", "Base, SFT, GRPO and GPT-6.1 Sol on one clock", rc ? `${rc.lanes.map(esc).join(" · ")} on the same day and prices.` : "");
}

function featured(r) {
  const thumb = r.thumb ? `<img src="${esc(r.thumb)}" alt="${esc(r.point)} on ${esc(r.date)}: the battery yard at ${esc(r.hero_moment || "the day's key hour")}" loading="lazy">` : "";
  return `<a class="hero card${r.hero ? "" : " small"}" href="${r.href}">${thumb}<div class="txt"><h5>${KIND[r.featured] || "Featured day"}</h5><h2>${esc(r.date)}${r.days > 1 ? `–${esc(endDate(r.date, r.days))}` : ""} · ${esc(r.point)} <span>${esc(POINTS[r.point]?.name || "")}</span></h2>
    <p>${esc(r.blurb || "")}</p><p class="dim">${esc(modelName(r.model, r.model_label))} · ${esc(r.tier)} · ${r.version === "v4" ? `R ${r.reward == null ? "—" : r.reward.toFixed(3)} on the anchor scale · r_hind ${r.r_opt == null ? "—" : r.r_opt.toFixed(2)} · guide drift $${Math.round(r.drift ?? 0)}/MWh` : r.version === "v3" ? `R ${r.reward == null ? "—" : r.reward.toFixed(3)} on the anchor scale · hindsight capture ${r.r_opt == null ? "—" : Math.round(r.r_opt * 100) + "%"}` : r.version === "v2" ? `hindsight capture ${r.r_opt == null ? "—" : Math.round(r.r_opt * 100) + "%"} · R ${r.reward == null ? "—" : r.reward.toFixed(3)} (provisional anchor)` : `reward ${r.reward == null ? "—" : r.reward.toFixed(3)}`}</p><span class="go">Watch the replay →</span></div></a>`;
}

function endDate(d1, days) {
  const x = new Date(Date.parse(`${d1}T12:00:00Z`) + (days - 1) * 86400000);
  return x.toISOString().slice(5, 10);
}
