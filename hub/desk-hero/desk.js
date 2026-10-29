(() => {
  const PLANNED = { reminder: "its reminder", checkpoint: "shift checkpoint", adjustment_open: "RT opens", dam_morning: "DAM morning", start: "start" };
  const X0 = 52, X1 = 574, PR = [30, 166], SO = [194, 258], DI = [288, 378], TOP = 18;
  const two = (n) => String(n).padStart(2, "0");
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
  const whole = (a) => { const f = Math.floor(a), d = a - f; return d > 0.5 || (d === 0.5 && f % 2 === 1) ? f + 1 : f; };
  const money = (x) => { const w = whole(Math.abs(x)); return `${x < 0 && w ? "−" : ""}$${w.toLocaleString("en-US")}`; };
  const price = (x) => { const v = Math.abs(x), s = v >= 99.95 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 }) : v >= 10 ? String(Math.round(v * 10) / 10) : v.toFixed(2); return `${x < 0 ? "−" : ""}$${s}`; };
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const $ = (s) => document.querySelector(s);
  let D, groups, hi = null, lo = null;

  const C = (t) => (t < 0 ? t * D.k : t);
  const X = (t) => X0 + ((C(t) - C(D.t0)) / (C(D.t1) - C(D.t0))) * (X1 - X0);
  const hhmm = (t) => { const m = ((Math.round(t) % 1440) + 1440) % 1440; return `${two(Math.floor(m / 60))}:${two(m % 60)}`; };

  function init(data) {
    D = data;
    $("#hp .nm").textContent = D.model;
    $("#hd .site").textContent = D.site;
    const inner = $("#hp .in");
    const who = D.model.split(" ").at(-1);
    groups = D.groups.map((g) => {
      const node = el("div", "wg", `<div class="gh"><span class="tm">${g.time}</span><span class="lb">${esc(g.reasons)}</span><span class="chips">${g.chips}</span></div>`);
      const items = g.items.map((it) => { const n = el("div", `it ${it.kind}${it.cls && it.kind === "event" ? " " + it.cls : ""}`, it.html); node.append(n); return { ...it, node: n }; });
      let qnode = null;
      if (g.quote) { qnode = el("div", "it quote", `<b>${esc(who)}:</b> “${esc(g.quote)}”`); node.append(qnode); }
      inner.append(node);
      return { ...g, node, items, qnode };
    });
    $("#gc").innerHTML = grade();
    return true;
  }

  function render(s, t, mode) {
    header(t, mode);
    $("#ch").innerHTML = chart(t, mode);
    panel(s, t);
    const fin = s >= D.gradeAt;
    $("#gc").classList.toggle("show", fin);
    document.body.classList.toggle("fin", fin);
  }

  function header(t, mode) {
    const end = t >= D.t1;
    const day = end ? D.nd - 1 : Math.floor(t / 1440);
    $("#hd .clk").textContent = end ? "24:00" : hhmm(t);
    $("#hd .day").textContent = t < 0 ? D.dayBefore : D.days[Math.min(day, D.nd - 1)];
    const st = $("#hd .st"), next = D.wakes.find((w) => w.t > t + 1e-6 && w.reasons.some((r) => r in PLANNED));
    st.className = `st ${mode}`;
    st.textContent = mode === "hold" ? "clock paused · the agent’s turn" : mode === "end" ? (D.nd > 1 ? "window over" : "day over") : next ? `clock running to ${hhmm(next.t)} · ${PLANNED[next.reasons.find((r) => r in PLANNED)]}` : "clock running";
    $("#hd .ln").innerHTML = caption(t, mode).map((x, i, a) => `<span class="hs">${x}${i < a.length - 1 ? " ·" : ""}</span>`).join(" ");
    const soc = socAt(t);
    $("#hd .soc").innerHTML = `SoC <b>${soc.toFixed(0)}</b> of ${D.eMax.toFixed(0)} MWh`;
    const p = mode === "end" || t >= D.t1 ? D.grade.p : settled(t);
    $("#hd .pnl").innerHTML = `${mode === "end" || t >= D.t1 ? "statement" : "settled so far"} <b class="${p < 0 ? "neg" : ""}">${money(p ?? 0)}</b>`;
  }

  function caption(t, mode) {
    if (mode === "end" || t >= D.t1) return [`<span class="w">${D.nd > 1 ? "window over" : "day over"}</span>`, "every interval settled", `${D.turns} wake-ups, ${D.total} tool calls`];
    if (t < 0) {
      const d = D.days[0].split(" ").slice(0, 3).join(" ");
      if (t < -840) return [`<span class="w">DAM for ${d}</span> open until 10:00`];
      if (t < D.posted[0]) return [`<span class="w">DAM for ${d}</span> closed at 10:00`, `<span class="dim">results pending</span>`];
      if (t < -360) return [`<span class="w">DAM results ${hhmm(D.posted[0])}:</span> ${awards(0)}`, `node DAM <span class="p">${price(Math.min(...D.dam.slice(0, 24)))}–${price(Math.max(...D.dam.slice(0, 24)))}</span>`];
      return [`<span class="w">RT offers and COP open</span> for ${d}`, `<span class="dim">DAM: ${awards(0)}</span>`];
    }
    const h = Math.floor(t / 60), out = [`<span class="w">HE${two((h % 24) + 1)}</span> <span class="dim">${hhmm(h * 60)}–${hhmm(h * 60 + 60).replace("00:00", "24:00")}</span>`];
    const dp = D.dam[h];
    out.push(`DAM <span class="p${dp > 200 ? " hot" : ""}">${price(dp)}</span>`);
    const n = Math.min(D.lmp.length, Math.max(0, Math.floor((t - 1) / 5)));
    if (n > 0) out.push(`SCED <span class="p rt">${price(D.lmp[n - 1])}</span> <span class="dim">(${hhmm(5 * (n - 1))})</span>`);
    const bp = D.bp[Math.min(D.bp.length - 1, Math.floor(t / 5))] ?? 0;
    out.push(Math.abs(bp) < 0.5 ? `<span class="dim">idle</span>` : bp > 0 ? `<span class="d">discharging ${bp.toFixed(0)} MW</span>` : `<span class="c">charging ${(-bp).toFixed(0)} MW</span>`);
    return out;
  }

  function awards(j) {
    const a = D.award.slice(24 * j, 24 * j + 24), sold = a.filter((x) => x > 0.05), bought = a.filter((x) => x < -0.05);
    if (!sold.length && !bought.length) return "no awards";
    const parts = [];
    if (sold.length) parts.push(`sold ${sold.reduce((x, y) => x + y, 0).toFixed(0)} MWh in ${sold.length} h`);
    if (bought.length) parts.push(`bought ${(-bought.reduce((x, y) => x + y, 0)).toFixed(0)} MWh`);
    return parts.join(", ");
  }

  function socAt(t) {
    if (t <= 0) return D.soc[0];
    const x = Math.min(t, D.t1) / 5, i = Math.min(D.soc.length - 2, Math.floor(x)), f = Math.min(1, x - i);
    return D.soc[i] + (D.soc[i + 1] - D.soc[i]) * f;
  }

  function settled(t) {
    if (t < 0) return null;
    const P = D.pnl;
    if (P.computed) { const up = Math.min(P.steps.length, Math.floor((t - 2) / 15)); return up > 0 ? P.steps[up - 1] : 0; }
    const s = P.shown.filter((x) => x[0] <= t).at(-1);
    return s ? s[1] : null;
  }

  function chart(t, mode) {
    const end = mode === "end" || t >= D.t1;
    const nl = end ? D.lmp.length : Math.min(D.lmp.length, Math.max(0, Math.floor((t - 1) / 5)));
    const nm = end ? D.metered.length : Math.min(D.metered.length, Math.max(0, Math.floor(t / 5)));
    const days = [...Array(D.nd).keys()].filter((j) => D.posted[j] <= t);
    const fc = forecastLines(t);
    const known = [...D.lmp.slice(0, nl)].sort((a, b) => a - b);
    const p98 = known.length ? known[Math.min(known.length - 1, Math.floor(known.length * 0.985))] : 0;
    const vals = [p98, ...days.flatMap((j) => D.dam.slice(24 * j, 24 * j + 24)), ...fc.flatMap((f) => f.pts.map((p) => p[1]))];
    const tHi = Math.max(40, ...vals) * 1.16, tLo = Math.min(0, ...known.slice(0, 3), ...vals) * 1.1;
    hi = hi == null || tHi > hi ? (hi == null ? tHi : hi + (tHi - hi) * 0.6) : hi;
    lo = lo == null || tLo < lo ? (lo == null ? tLo : lo + (tLo - lo) * 0.6) : lo;
    const yP = (v) => PR[1] - ((v - lo) / (hi - lo)) * (PR[1] - PR[0]);
    const yS = (v) => SO[1] - (v / D.eMax) * (SO[1] - SO[0]);
    const span = Math.max(D.hsl, -D.lsl), mid = DI[0] + ((DI[1] - DI[0]) * D.hsl) / (D.hsl - D.lsl);
    const yD = (v) => mid - (v / (v >= 0 ? D.hsl : -D.lsl)) * (v >= 0 ? mid - DI[0] : DI[1] - mid);
    let s = `<defs><linearGradient id="gr" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#ffb000" stop-opacity="0.26"/><stop offset="1" stop-color="#ffb000" stop-opacity="0.02"/></linearGradient><linearGradient id="gs" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#45d793" stop-opacity="0.24"/><stop offset="1" stop-color="#45d793" stop-opacity="0.02"/></linearGradient><clipPath id="cp"><rect x="${X0}" y="${PR[0] - 2}" width="${X1 - X0}" height="${PR[1] - PR[0] + 4}"/></clipPath></defs>`;
    if (D.t0 < 0) s += `<rect x="${X(D.t0)}" y="${TOP}" width="${X(0) - X(D.t0)}" height="${DI[1] - TOP}" fill="rgba(255,255,255,0.028)"/>`;
    for (const [a, b] of [PR, SO, DI]) s += `<line x1="${X0}" x2="${X1}" y1="${b}" y2="${b}" stroke="rgba(255,255,255,0.13)"/>`;
    for (const [a, b] of [PR, SO, DI]) s += `<rect x="${X0 - 3}" y="${a - 3}" width="${X1 - X0 + 6}" height="${b - a + 6}" rx="5" fill="rgba(255,255,255,0.022)"/>`;
    for (const v of ticks(lo, hi)) s += `<line x1="${X0}" x2="${X1}" y1="${yP(v)}" y2="${yP(v)}" stroke="rgba(255,255,255,0.055)"/><text class="tk" x="${X0 - 6}" y="${yP(v) + 3.5}" text-anchor="end">${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US")}</text>`;
    if (D.t0 < 0) for (const [m, txt, dy] of [[-840, "DAM closes", 9], [-360, "RT opens", 20]]) if (m > D.t0) s += `<line x1="${X(m)}" x2="${X(m)}" y1="${PR[0]}" y2="${DI[1]}" stroke="rgba(255,255,255,0.16)" stroke-dasharray="2 3"/><text class="note" x="${X(m) + 3}" y="${PR[0] + dy}">${txt}</text>`;
    s += `<line x1="${X0}" x2="${X1}" y1="${yS(D.eMax)}" y2="${yS(D.eMax)}" stroke="rgba(255,255,255,0.22)" stroke-dasharray="3 3"/><text class="tk" x="${X0 - 6}" y="${yS(D.eMax) + 3.5}" text-anchor="end">${D.eMax.toFixed(0)}</text><text class="tk" x="${X0 - 6}" y="${yS(0) + 3.5}" text-anchor="end">0</text>`;
    s += `<line x1="${X0}" x2="${X1}" y1="${mid}" y2="${mid}" stroke="rgba(255,255,255,0.22)"/><text class="tk" x="${X0 - 6}" y="${DI[0] + 8}" text-anchor="end">+${D.hsl.toFixed(0)}</text><text class="tk" x="${X0 - 6}" y="${mid + 3.5}" text-anchor="end">0</text><text class="tk" x="${X0 - 6}" y="${DI[1]}" text-anchor="end">${D.lsl.toFixed(0).replace("-", "−")}</text>`;
    for (let j = 0; j <= D.nd; j++) {
      for (const h of j < D.nd ? [6, 12, 18] : []) s += `<line x1="${X(j * 1440 + h * 60)}" x2="${X(j * 1440 + h * 60)}" y1="${TOP + 6}" y2="${DI[1]}" stroke="rgba(255,255,255,0.05)"/>`;
      s += `<line x1="${X(j * 1440)}" x2="${X(j * 1440)}" y1="${TOP + 6}" y2="${DI[1]}" stroke="rgba(255,255,255,0.16)"/>`;
    }
    s += xLabels();
    s += `<g clip-path="url(#cp)">`;
    for (const f of fc) s += `<path d="${f.pts.map((p, i) => `${i ? "L" : "M"}${X(p[0]).toFixed(1)},${yP(p[1]).toFixed(1)}`).join("")}" fill="none" stroke="#9fb0bd" stroke-width="1.4" stroke-dasharray="4 3" opacity="0.9"/>`;
    for (const j of days) {
      let d = "";
      for (let h = 0; h < 24; h++) { const v = D.dam[24 * j + h], a = j * 1440 + h * 60; d += `${h ? "L" : "M"}${X(a).toFixed(1)},${yP(v).toFixed(1)}L${X(a + 60).toFixed(1)},${yP(v).toFixed(1)}`; }
      s += `<path d="${d}" fill="none" stroke="var(--dam)" stroke-width="1.9"/>`;
    }
    if (nl) {
      const line = D.lmp.slice(0, nl).map((v, i) => `${i ? "L" : "M"}${X(i * 5 + 2.5).toFixed(1)},${yP(Math.min(v, hi * 1.02)).toFixed(1)}`).join("");
      s += `<path d="${line}L${X((nl - 1) * 5 + 2.5).toFixed(1)},${yP(Math.max(lo, 0)).toFixed(1)}L${X(2.5).toFixed(1)},${yP(Math.max(lo, 0)).toFixed(1)}Z" fill="url(#gr)"/><path d="${line}" fill="none" stroke="var(--rt)" stroke-width="1.3" stroke-linejoin="round"/>`;
    }
    s += `</g>`;
    if (nl) {
      const i = D.lmp.slice(0, nl).reduce((b, v, j, a) => (v > a[b] ? j : b), 0);
      if (D.lmp[i] > Math.max(hi, tHi) * 1.04) s += `<text class="peak" x="${Math.min(X1 - 4, X(i * 5) + 4)}" y="${PR[0] + 9}" text-anchor="${X(i * 5) > X1 - 80 ? "end" : "start"}">▲ ${price(D.lmp[i])} at ${hhmm(i * 5)}</text>`;
    }
    for (const w of D.wakes) {
      if (w.t > t + 1e-6) break;
      const x = X(w.t);
      s += w.held ? `<circle cx="${x}" cy="${TOP + 3}" r="3.6" fill="var(--acc)"/>` : `<line x1="${x}" x2="${x}" y1="${TOP}" y2="${TOP + 7}" stroke="${w.acted ? "var(--acc)" : "rgba(255,255,255,0.45)"}" stroke-width="1.4"/>`;
    }
    if (D.opSoc && end) s += `<path d="${D.opSoc.map((v, i) => (v == null ? "" : `${i && D.opSoc[i - 1] != null ? "L" : "M"}${X(i * 5).toFixed(1)},${yS(v).toFixed(1)}`)).join("")}" fill="none" stroke="#c9d3da" stroke-width="1.3" stroke-dasharray="4 3"/>`;
    const tt = Math.min(Math.max(t, 0), D.t1), ns = Math.min(D.soc.length - 1, Math.floor(tt / 5));
    let sp = `M${X(t < 0 ? D.t0 : 0).toFixed(1)},${yS(D.soc[0]).toFixed(1)}`;
    if (t < 0) sp += `L${X(t).toFixed(1)},${yS(D.soc[0]).toFixed(1)}`;
    else { for (let i = 0; i <= ns; i++) sp += `L${X(i * 5).toFixed(1)},${yS(D.soc[i]).toFixed(1)}`; sp += `L${X(tt).toFixed(1)},${yS(socAt(tt)).toFixed(1)}`; }
    const sx = t < 0 ? X(t) : X(tt);
    s += `<path d="${sp}L${sx.toFixed(1)},${yS(0)}L${X(t < 0 ? D.t0 : 0).toFixed(1)},${yS(0)}Z" fill="url(#gs)"/><path d="${sp}" fill="none" stroke="var(--soc)" stroke-width="2" stroke-linejoin="round"/>`;
    if (nm) {
      let up = `M${X(0)},${mid}`, dn = `M${X(0)},${mid}`;
      for (let i = 0; i < nm; i++) { const v = D.metered[i], a = X(i * 5).toFixed(1), b = X(i * 5 + 5).toFixed(1); up += `L${a},${yD(Math.max(v, 0)).toFixed(1)}L${b},${yD(Math.max(v, 0)).toFixed(1)}`; dn += `L${a},${yD(Math.min(v, 0)).toFixed(1)}L${b},${yD(Math.min(v, 0)).toFixed(1)}`; }
      up += `L${X(nm * 5)},${mid}Z`; dn += `L${X(nm * 5)},${mid}Z`;
      s += `<path d="${up}" fill="var(--dis)" opacity="0.92"/><path d="${dn}" fill="var(--chg)" opacity="0.92"/>`;
    }
    for (const j of days) {
      if (!D.award.slice(24 * j, 24 * j + 24).some((x) => Math.abs(x) > 0.05)) continue;
      let d = "";
      for (let h = 0; h < 24; h++) { const v = D.award[24 * j + h], a = j * 1440 + h * 60; d += `${h ? "L" : "M"}${X(a).toFixed(1)},${yD(v).toFixed(1)}L${X(a + 60).toFixed(1)},${yD(v).toFixed(1)}`; }
      s += `<path d="${d}" fill="none" stroke="var(--dam)" stroke-width="1.4"/>`;
    }
    if (!end && t >= D.t0) s += `<line x1="${X(t)}" x2="${X(t)}" y1="${TOP - 2}" y2="${DI[1] + 3}" stroke="#fff" stroke-width="1.3" opacity="0.92"/>`;
    s += legends(fc.length > 0, days.some((j) => D.award.slice(24 * j, 24 * j + 24).some((x) => Math.abs(x) > 0.05)), D.opSoc && end);
    return s;
  }

  function forecastLines(t) {
    const out = [];
    for (let j = 0; j < D.nd; j++) {
      const posted = D.posted[j] <= t, mk = posted ? "rt" : "dam";
      const f = D.fc.filter((x) => x.t <= t && x.market === mk && x.start === j * 1440).at(-1);
      if (!f) continue;
      const pts = [];
      f.p50.forEach((v, i) => {
        if (v == null) return;
        let a = f.start + i * f.step, b = a + f.step;
        if (posted) { if (b <= t) return; a = Math.max(a, t); }
        pts.push([a, v], [b, v]);
      });
      if (pts.length) out.push({ pts });
    }
    return out;
  }

  function ticks(a, b) {
    const raw = (b - a) / 3.2, mag = 10 ** Math.floor(Math.log10(raw)), st = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((x) => x >= raw);
    const out = [];
    for (let v = Math.ceil(a / st) * st; v <= b; v += st) out.push(Math.round(v * 100) / 100);
    return out;
  }

  function xLabels() {
    const y = DI[1] + 16, want = [];
    if (D.t0 < 0) want.push([D.t0, D.dayBefore.split(" ").slice(0, 3).join(" "), "dim", "start"]);
    for (let j = 0; j < D.nd; j++) {
      want.push([j * 1440, D.days[j].split(" ").slice(0, 3).join(" "), "day", j ? "middle" : "start"]);
      for (const h of D.nd > 1 ? [12] : [6, 12, 18]) want.push([j * 1440 + h * 60, `${two(h)}:00`, "", "middle"]);
    }
    want.push([D.t1, "24:00", "", "end"]);
    const keep = [];
    const span = (w) => { const x = X(w[0]) + (w[3] === "start" ? 3 : 0), n = w[1].length * 5.6; return w[3] === "start" ? [x, x + n] : w[3] === "end" ? [x - n, x] : [x - n / 2, x + n / 2]; };
    for (const w of want.sort((a, b) => (b[2] === "day") - (a[2] === "day"))) { const [a, b] = span(w); if (keep.every((k) => { const [c, d] = span(k); return b + 8 < c || d + 8 < a; })) keep.push(w); }
    return keep.map((w) => `<text class="tk ${w[2]}" x="${X(w[0]) + (w[3] === "start" ? 3 : 0)}" y="${y}" text-anchor="${w[3]}">${w[1]}</text>`).join("");
  }

  function legends(fc, award, op) {
    const sw = (x, y, col, dash) => `<line x1="${x}" x2="${x + 14}" y1="${y - 4}" y2="${y - 4}" stroke="${col}" stroke-width="2.2" ${dash ? 'stroke-dasharray="3 2"' : ""}/>`;
    let s = "", x = X0;
    const item = (y, col, txt, dash, box) => { s += box ? `<rect x="${x}" y="${y - 9}" width="11" height="9" rx="1.5" fill="${col}"/>` : sw(x, y, col, dash); s += `<text class="lg" x="${x + (box ? 15 : 18)}" y="${y}">${txt}</text>`; x += 26 + txt.replace(/<[^>]+>/g, "").length * 6.05; };
    item(PR[0] - 16 + 2, "var(--dam)", "node DAM price, hourly");
    item(PR[0] - 16 + 2, "var(--rt)", "node SCED price, 5-min");
    if (fc) item(PR[0] - 16 + 2, "#9fb0bd", "desk forecast P50 <tspan class=\"m\">(modelled)</tspan>", true);
    x = X0; item(SO[0] - 10, "var(--soc)", "state of charge, MWh");
    if (op) item(SO[0] - 10, "#c9d3da", "the real operator <tspan class=\"m\">(disclosed 60 days later)</tspan>", true);
    x = X0; item(DI[0] - 10, "var(--dis)", "discharge", false, true); item(DI[0] - 10, "var(--chg)", "charge, MW", false, true);
    if (award) item(DI[0] - 10, "var(--dam)", "DAM award");
    return s;
  }

  function panel(s, t) {
    let calls = 0, wakes = 0;
    for (const g of groups) {
      const open = s >= g.open, closed = g.close != null && s >= g.close;
      g.node.style.display = open ? "" : "none";
      g.node.classList.toggle("closed", closed);
      if (!open) continue;
      wakes++;
      const shown = g.items.filter((it) => s >= it.at);
      const last = shown.filter((it) => it.kind === "call").at(-1);
      for (const it of g.items) {
        if (it.kind === "call" && s >= it.at) calls++;
        const vis = !closed && s >= it.at;
        it.node.style.display = vis ? "" : "none";
        if (!vis) continue;
        const later = shown.some((o) => o.at > it.at + 1e-6) || (g.quoteAt != null && s >= g.quoteAt);
        it.node.classList.toggle("short", it.kind === "call" && later && it !== last && !it.keep);
        it.node.classList.toggle("on", it === last && !(g.quoteAt != null && s >= g.quoteAt));
        const r = it.node.querySelector(".r");
        if (r) { const done = s >= it.res; r.className = `r ${done ? it.cls : "wait"}`; r.innerHTML = done ? it.result : "…"; }
      }
      if (g.qnode) g.qnode.style.display = !closed && g.quoteAt != null && s >= g.quoteAt ? "" : "none";
    }
    $("#hp .n").textContent = `${calls} of ${D.total} calls`;
    $("#hp .sub").textContent = `wake-up ${Math.max(1, wakes)} of ${D.turns} · the clock waits while it works`;
    const log = $("#hp .log"), inner = $("#hp .in");
    inner.style.top = "0px";
    const over = inner.offsetHeight - log.clientHeight;
    if (over > 0) inner.style.top = `${-over}px`;
    log.classList.toggle("top", over <= 0);
  }

  function grade() {
    const g = D.grade, rows = g.rows, ps = rows.map((r) => r.p), lo = Math.min(0, ...ps), hi = Math.max(...ps), w = (v) => ((v - lo) / (hi - lo)) * 100;
    const col = { model: "#0b9fc6", anchor: "#7a868e", op: "#a48a5a", opa: "#c8b48c", hind: "#b9c0c5" };
    const bars = rows.map((r) => `<div class="gr"><span class="${r.key === "model" ? "me" : ""}">${esc(r.label)}</span><b>${money(r.p)}</b></div><div class="bar"><i style="left:${Math.min(w(0), w(r.p)).toFixed(1)}%;width:${Math.abs(w(r.p) - w(0)).toFixed(1)}%;background:${col[r.key]}"></i>${lo < 0 ? `<span class="z" style="left:${w(0).toFixed(1)}%"></span>` : ""}</div>`).join("");
    const ref = rows.find((r) => r.key === "op") || { key: "anchor", p: g.anchor }, gap = g.p - ref.p;
    const vs = ref.key === "op" ? "against the real operator's own bids" : "against the anchor policy";
    const head = g.capture == null ? `<span class="${g.reward < 0.5 ? "low" : ""}"><small>reward</small>${g.reward.toFixed(2)}</span>` : `<span class="${g.capture < 0 ? "low" : ""}"><small>hindsight capture C</small>${g.capture.toFixed(2)}</span>`;
    const m = g.modelled, mod = m.length ? `; ${m.length > 1 ? `${m.slice(0, -1).join(", ")} and ${m.at(-1)} are` : `${m[0]} is`} modelled` : "";
    return `<div class="t"><b>${D.nd > 1 ? `${["", "", "Two", "Three", "Four"][D.nd] || D.nd} days` : "Day over"} · settled</b>${head}</div><div class="sub"><b class="${gap >= 0 ? "good" : "bad"}">${gap >= 0 ? "+" : "−"}$${whole(Math.abs(gap)).toLocaleString("en-US")}</b> ${vs}${g.capture == null ? "" : ` · reward R ${g.reward.toFixed(2)}`}</div>${bars}<div class="ft">Profit P for the ${D.nd > 1 ? `${["", "", "two", "three", "four"][D.nd] || D.nd} operating days` : "operating day"} from the desk's ERCOT statement, at ERCOT's real prices${mod}.</div>`;
  }

  window.desk = { init, render };
})();
