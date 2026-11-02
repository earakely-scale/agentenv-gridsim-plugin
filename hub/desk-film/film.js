/* The run film's frame over the desk viewer: film.init(data) once, then film.render(frame) for every frame the script
   films. frame = {t, mode: "hold" | "play" | "end", turn, p, e}: t in minutes from the first operating day's midnight;
   in a hold, p is seconds into the agent's turn; at the end, e is seconds into the grade. Text goes in as textContent. */
(() => {
  const NS = "http://www.w3.org/2000/svg";
  const W = 656, GUT = 58, PAD = 12, X1 = W - PAD, P0 = 22, P1 = 50, C0 = 56, C1 = 78;
  let D, els = {}, last = {};

  const h = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  };
  const s = (tag, attrs) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
    return e;
  };
  const money = (x) => `${x < 0 ? "−" : ""}$${Math.round(Math.abs(x)).toLocaleString("en-US")}`;
  const hhmm = (t) => {
    const m = ((Math.round(t) % 1440) + 1440) % 1440;
    return `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  };
  const ease = (u) => (u <= 0 ? 0 : u >= 1 ? 1 : 1 - (1 - u) ** 3);

  function init(data) {
    D = data;
    document.body.classList.add("filming");
    const root = h("div");
    root.id = "film";
    const title = h("div", "fm-title"), kick = h("div", "fm-kick");
    kick.append(h("b", null, "GridSimEnv"), document.createTextNode(` · ${D.kicker}`));
    title.append(kick, h("h1", null, D.headline), h("p", "fm-sub", D.sub));
    const desk = h("div", "fm-desk"), clock = h("div", "fm-clock");
    els.hm = h("b", "fm-hm");
    els.day = h("span", "fm-day");
    clock.append(els.hm, els.day);
    els.state = h("div", "fm-state");
    els.body = h("div", "fm-body");
    desk.append(clock, els.state, h("div", "fm-rule"), els.body, h("div", "fm-foot", D.foot));
    const band = h("div", "fm-band");
    els.svg = s("svg", { viewBox: `0 0 ${W} 84` });
    band.append(els.svg);
    root.append(h("div", "fm-scrim"), title, desk, band);
    document.body.append(root);
    frame();
  }

  const x = (t) => {
    const k = D.k, u = (t < 0 ? (t - D.t0) * k : -D.t0 * k + t) / (-D.t0 * k + D.t1);
    return GUT + Math.max(0, Math.min(1, u)) * (X1 - GUT);
  };
  const yp = (v) => P1 - (Math.max(0, Math.min(D.pmax, v)) / D.pmax) * (P1 - P0);
  const yc = (v) => C1 - (Math.max(0, v) / D.site.emax) * (C1 - C0);

  /* The band's fixed parts: the days, the rows, the legend; what has happened draws in band(). */
  function frame() {
    const g = els.svg;
    for (const t of [0, 1440, 2880]) g.append(s("line", { class: "fm-sep", x1: x(t), x2: x(t), y1: 3, y2: C1 + 3 }));
    g.append(s("line", { class: "fm-base", x1: GUT, x2: X1, y1: P1, y2: P1 }), s("line", { class: "fm-base", x1: GUT, x2: X1, y1: C1, y2: C1 }));
    D.dayLabels.forEach((l, j) => {
      const a = j === 0 ? D.t0 : 1440 * (j - 1), b = j === 0 ? 0 : 1440 * j;
      const t = s("text", { class: j ? "fm-dl" : "", x: (x(a) + x(b)) / 2, y: 12, "text-anchor": "middle" });
      t.textContent = l;
      g.append(t);
    });
    for (const [label, y] of [["Price", (P0 + P1) / 2 + 3.5], ["Charge", (C0 + C1) / 2 + 3.5]]) {
      const t = s("text", { class: "fm-k", x: 12, y });
      t.textContent = label;
      g.append(t);
    }
    els.rt = s("path", { class: "fm-rt" });
    els.soc = s("path", { class: "fm-soc" });
    els.wk = s("g");
    els.head = s("line", { class: "fm-head", y1: P0 - 5, y2: C1 + 3 });
    g.append(els.soc, els.rt, els.wk, els.head);
  }

  function band(t) {
    const tt = Math.max(D.t0, Math.min(D.t1, t));
    let rt = "";
    for (let i = 0; i < D.rt.length && 15 * (i + 1) + 2 <= tt; i++)
      rt += `${rt ? "L" : "M"}${x(15 * i).toFixed(1)},${yp(D.rt[i]).toFixed(1)}H${x(15 * (i + 1)).toFixed(1)}`;
    els.rt.setAttribute("d", rt);
    const n = Math.max(0, Math.min(D.soc.length - 1, Math.floor(tt / 5)));
    let soc;
    if (tt > 0) {
      soc = `M${x(0).toFixed(1)},${C1}`;
      for (let i = 0; i <= n; i += 2) soc += `L${x(5 * i).toFixed(1)},${yc(D.soc[i]).toFixed(1)}`;
      soc += `L${x(tt).toFixed(1)},${yc(D.soc[n]).toFixed(1)}L${x(tt).toFixed(1)},${C1}Z`;
    } else soc = `M${x(D.t0).toFixed(1)},${yc(D.soc[0]).toFixed(1)}H${x(tt).toFixed(1)}V${C1}H${x(D.t0).toFixed(1)}Z`;
    els.soc.setAttribute("d", soc);
    const ticks = D.wakes.filter((w) => w.t <= tt);
    if (last.ticks !== ticks.length) {
      last.ticks = ticks.length;
      els.wk.replaceChildren(...ticks.map((w) => s("line", { class: `fm-wk${w.held ? " fm-held" : ""}`, x1: x(w.t), x2: x(w.t), y1: P0 - 7, y2: P0 - (w.held ? 0 : 2) })));
    }
    els.head.setAttribute("x1", x(tt));
    els.head.setAttribute("x2", x(tt));
  }

  function clock(t, mode) {
    const tt = Math.max(D.t0, Math.min(D.t1, t));
    const j = tt < 0 ? -1 : Math.min(D.nd - 1, Math.floor(tt / 1440 - (tt >= D.t1 ? 1e-9 : 0)));
    els.hm.textContent = tt >= D.t1 ? "24:00" : hhmm(tt);
    els.day.replaceChildren(document.createTextNode(D.dayNames[j + 1]), h("small", null, j < 0 ? "the day before" : `operating day ${j + 1} of ${D.nd}`));
    els.state.replaceChildren(h("i"), h("span", null, mode === "hold" ? `${D.tag}'s turn: the clock waits` : mode === "end" ? "Window over, settled" : "The clock runs"));
    els.state.className = `fm-state${mode === "hold" ? " fm-turn" : ""}`;
    const v = tt >= 0 && mode !== "end" ? pnlAt(tt) : null;
    if (v != null) {
      const p = h("span", "fm-pnl", "settled ");
      p.append(h("b", null, money(v)));
      els.state.append(p);
    }
  }

  function pnlAt(t) {
    if (D.pnl.steps) {
      const i = Math.floor((t - 2) / 15) - 1;
      return i >= 0 ? D.pnl.steps[Math.min(i, D.pnl.steps.length - 1)] : 0;
    }
    const seen = D.pnl.shown.filter(([at]) => at <= t);
    return seen.length ? seen[seen.length - 1][1] : null;
  }

  function hold(n, p) {
    const T = D.turns[n], body = els.body;
    body.replaceChildren();
    const wake = h("div", "fm-wake");
    wake.append(h("small", null, `Wake-up ${T.index + 1} of ${D.nturns} · ${T.time}`), h("h2", null, T.reason));
    for (const ev of T.events) if (p >= ev.at) wake.append(h("p", ev.cls ? `fm-${ev.cls}` : "", ev.text));
    const shown = T.calls.filter((c) => c.at <= p);
    const done = T.quote != null && p >= T.quoteAt;
    const list = h("ol", "fm-calls");
    shown.forEach((c, i) => {
      const on = i === shown.length - 1 && !done, landed = p >= c.res;
      const li = h("li", on ? "fm-on" : "fm-past");
      const t = h("div", "fm-t", c.tool);
      if (landed && c.mark) t.append(h("em", c.cls === "no" ? "fm-no" : "", c.mark));
      li.append(t);
      const d = landed && c.r ? c.r : c.d;
      if (d) li.append(h("div", `fm-d${landed && c.r ? " fm-r" : ""}`, d));
      list.append(li);
    });
    body.append(wake, list);
    if (done) {
      const q = h("div", "fm-quote");
      q.append(h("b", null, `${D.tag}: `), h("span", null, `“${T.quote}”`));
      body.append(q);
    }
    fit(list, (k) => `${k} earlier ${k === 1 ? "call" : "calls"}`);
  }

  /* Drop the oldest rows until the list fits the desk, so the newest, lit row always shows; say counts them. */
  function fit(list, say) {
    let k = 0, more = null;
    const rows = () => [...list.children].filter((x) => x !== more);
    while (list.scrollHeight > list.clientHeight + 1 && rows().length > 1) {
      rows()[0].remove();
      k++;
      if (!say) continue;
      if (!more) list.prepend((more = h("li", "fm-more")));
      more.textContent = say(k);
    }
  }

  function between(t) {
    const body = els.body, past = D.wakes.filter((w) => w.t <= t);
    body.replaceChildren();
    const wake = h("div", "fm-wake");
    wake.append(h("small", null, `${past.length} of ${D.nturns} wake-ups so far`), h("h2", null, "Between turns, the clock runs"));
    const list = h("ol", "fm-log");
    past.slice(-8).forEach((w, i, arr) => {
      const li = h("li", i < arr.length - 3 ? "fm-old" : ""), span = h("span");
      w.chips.forEach((c, k) => {
        if (k) span.append(document.createTextNode(" · "));
        span.append(document.createTextNode(c.ok != null ? `${c.text} ` : c.text));
        if (c.ok != null) span.append(h("i", c.ok ? "" : "fm-no", c.ok ? "✓" : "✗"));
      });
      li.append(h("b", null, w.time), span);
      list.append(li);
    });
    body.append(wake, list);
    fit(list, null);
  }

  function end(e) {
    const G = D.grade, body = els.body, box = h("div", "fm-end");
    body.replaceChildren();
    const cap = h("div", "fm-cap", "hindsight capture ");
    cap.append(h("b", null, `C ${G.C}`), document.createTextNode(` · reward R ${G.R}`));
    box.append(h("small", null, `${D.nd} operating days, settled`), h("div", "fm-big", money(G.p)), cap);
    const ul = h("ul"), top = Math.max(...G.rows.map((r) => r.p), 1);
    G.rows.forEach((r, i) => {
      const li = h("li", r.me ? "fm-me" : ""), row = h("div", "fm-row"), bar = h("div", "fm-bar"), b = h("b");
      row.append(h("span", null, r.label), h("b", null, money(r.p)));
      b.style.width = `${((100 * Math.max(0, r.p)) / top) * ease((e - 0.12 * i) / 0.8)}%`;
      b.style.background = r.color;
      bar.append(b);
      li.append(row, bar);
      ul.append(li);
    });
    box.append(ul, h("div", "fm-note", G.note));
    body.append(box);
  }

  function render(f) {
    clock(f.t, f.mode);
    band(f.t);
    if (f.mode === "hold") hold(f.turn, f.p);
    else if (f.mode === "end") end(f.e);
    else between(f.t);
  }

  window.film = { init, render };
})();
