(() => {
  const D = window.HERO;
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const hp = el("aside", "", `<div class="hd"><div><b>${D.model}</b> <span>· its tool calls</span></div><div class="n"></div></div>`);
  hp.id = "hp";
  const book = el("div", "book", `<div class="cap"><span>Book: <i class="c">charge</i> · <i class="d">discharge</i> · <i class="r">reserve</i></span><span class="bk"></span></div><svg viewBox="0 0 336 58" preserveAspectRatio="none"></svg><div class="ticks"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>`);
  const log = el("div", "log", "");
  const inner = el("div", "in", "");
  log.append(inner);
  hp.append(book, log);
  const sb = el("section", "", `<div class="top"><span class="clk"></span><span class="day"></span><span class="st"></span></div><div class="ln"></div><div class="soc"><span>SoC</span><div class="bar"><i class="f"></i></div><b></b></div>`);
  sb.id = "sb";
  const gc = el("section", "", D.grade);
  gc.id = "gc";
  document.body.append(hp, sb, gc);

  const groups = D.groups.map((g) => {
    const node = el("div", "wg", `<div class="gh"><span class="tm">${g.time}</span><span class="lb">${g.label}</span><span class="chips">${g.chips}</span></div>`);
    const items = g.items.map((it) => {
      const n = el("div", `it ${it.kind}`, it.html);
      node.append(n);
      return { ...it, node: n };
    });
    inner.append(node);
    return { ...g, node, items };
  });

  const svg = book.querySelector("svg");
  const W = 336, cw = W / 24, mid = 22, amp = 19;
  const axis = `<line x1="0" x2="${W}" y1="${mid}" y2="${mid}" stroke="rgba(255,255,255,0.25)" stroke-width="1"/>`;
  function bookSvg(b, glow, cur) {
    let s = cur == null ? "" : `<rect x="${cur * cw}" y="0" width="${cw}" height="58" fill="rgba(255,255,255,0.13)"/>`;
    s += axis;
    for (let h = 0; h < 24; h++) {
      const e = b.energy[h], r = b.reserve[h], x = h * cw + 1.3, w = cw - 2.6;
      if (Math.abs(e) > 0.05) {
        const hgt = Math.max(2.5, (Math.abs(e) / 100) * amp);
        s += `<rect x="${x}" y="${e > 0 ? mid - hgt : mid}" width="${w}" height="${hgt}" rx="1.5" fill="${e > 0 ? "#ffa62b" : "#2fd3ff"}"/>`;
      }
      if (r > 0.05) {
        const rh = Math.max(2, (r / 100) * 11);
        s += `<rect x="${x}" y="${58 - rh}" width="${w}" height="${rh}" rx="1" fill="#a7c4b8"/>`;
      }
      if (glow > 0 && b.changed.includes(h)) s += `<rect x="${h * cw + 0.5}" y="0.5" width="${cw - 1}" height="57" fill="none" stroke="#fff" stroke-opacity="${glow}" stroke-width="1.8" rx="2.5"/>`;
    }
    return s;
  }
  const two = (n) => String(n).padStart(2, "0");
  const clock = (m) => `${two(Math.floor(((m + 1440) % 1440) / 60))}:${two(((m % 60) + 60) % 60)}`;

  function render(s, t, mode) {
    let calls = 0;
    for (const g of groups) {
      const open = s >= g.open, closed = g.close != null && s >= g.close;
      g.node.style.display = open ? "" : "none";
      g.node.classList.toggle("closed", closed);
      if (!open) continue;
      const shown = g.items.filter((it) => s >= it.at);
      const last = shown.filter((it) => it.kind === "call").at(-1);
      for (const it of g.items) {
        if (it.kind === "call" && s >= it.at) calls++;
        const vis = !closed && s >= it.at;
        it.node.style.display = vis ? "" : "none";
        if (!vis) continue;
        const later = shown.some((o) => o.at > it.at + 1e-6 && o.kind !== "quote");
        it.node.classList.toggle("short", it.kind === "call" && later && it !== last && !it.keep);
        it.node.classList.toggle("on", it === last);
        const r = it.node.querySelector(".r");
        if (r) {
          const done = s >= it.res;
          r.className = `r ${done ? it.cls : "wait"}`;
          r.innerHTML = done ? it.result : "…";
        }
      }
    }
    hp.querySelector(".n").textContent = `${calls} of ${D.total} calls`;
    inner.style.top = "0px";
    const over = inner.offsetHeight - log.clientHeight;
    if (over > 0) inner.style.top = `${-over}px`;
    log.classList.toggle("top", over <= 0);
    const b = D.books.filter((x) => s >= x.at).at(-1);
    svg.innerHTML = b ? bookSvg(b, Math.max(0, 1 - (s - b.at) / 2.2), t >= 0 && t < 24 ? Math.floor(t) : null) : axis;
    book.querySelector(".bk").textContent = b ? b.label : "empty";
    gc.classList.toggle("show", s >= D.gradeAt);
    document.body.classList.toggle("fin", s >= D.gradeAt);
    const m = t < 0 ? Math.round(-600 + ((t + 2) / 2) * 600) : Math.min(1440, Math.round(t * 60));
    sb.querySelector(".clk").textContent = t >= 24 ? "24:00" : clock(m);
    sb.querySelector(".day").textContent = t < 0 ? D.dayBefore : D.day;
    const st = sb.querySelector(".st"), next = D.watchT.findIndex((x) => x > t + 1e-6);
    st.className = `st ${mode}`;
    st.textContent = mode === "hold" ? "clock paused · the agent’s turn" : mode === "end" ? "day over" : next >= 0 ? `clock running to the ${D.watchTime[next]} watch` : "clock running to midnight";
    sb.querySelector(".ln").innerHTML = t < 0 ? D.preLine : t >= 24 ? D.endLine : D.hours.filter((c) => c.min <= m).at(-1).html;
    const d = gridsim.stage.d, soc = t >= 24 ? D.endSoc : t < 0 ? d.s0 : d.at(Math.min(23.999, t)).soc;
    sb.querySelector(".soc .f").style.width = `${(soc / d.E) * 100}%`;
    sb.querySelector(".soc b").textContent = `${soc.toFixed(0)} of ${d.E.toFixed(0)} MWh`;
  }
  window.hero = { render };
  return true;
})();
