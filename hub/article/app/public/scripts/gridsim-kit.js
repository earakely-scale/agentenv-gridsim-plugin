/* Shared helpers for the GridSimEnv embeds: data loading, mounting, tooltips, formats and the model registry.
   Loaded once by the page, before any embed runs. */
(() => {
  const cache = new Map();
  const data = (name) => {
    if (!cache.has(name)) {
      cache.set(name, (async () => {
        for (const u of [`/data/${name}`, `./assets/data/${name}`, `../assets/data/${name}`]) {
          try {
            const r = await fetch(u, { cache: "no-cache" });
            if (r.ok) return await r.json();
          } catch (e) { /* try the next path */ }
        }
        throw new Error(`${name} not found`);
      })());
    }
    return cache.get(name);
  };

  /* The embed's root: the element before the running script, else the last unmounted one of its class. */
  const mount = (cls) => {
    let root = document.currentScript ? document.currentScript.previousElementSibling : null;
    while (root && !(root.classList && root.classList.contains(cls))) root = root.previousElementSibling;
    if (!root) root = [...document.querySelectorAll(`.${cls}`)].filter((e) => e.dataset.mounted !== "true")[0];
    if (!root || root.dataset.mounted === "true") return null;
    root.dataset.mounted = "true";
    return root;
  };

  const config = (root) => {
    try { return JSON.parse(root.closest("[data-config]")?.dataset.config || "{}"); } catch (e) { return {}; }
  };

  const whenD3 = (cb) => {
    if (window.d3 && window.d3.select) return cb();
    const t = setInterval(() => { if (window.d3 && window.d3.select) { clearInterval(t); cb(); } }, 30);
  };

  /* Re-render on resize (width changes only) and on theme switches. */
  const watch = (root, render) => {
    let w = root.clientWidth;
    const go = () => { const nw = root.clientWidth; if (nw && nw !== w) { w = nw; render(); } };
    if (window.ResizeObserver) new ResizeObserver(go).observe(root); else window.addEventListener("resize", go);
    new MutationObserver(() => render()).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  };

  const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  const dark = () => document.documentElement.getAttribute("data-theme") === "dark";

  /* One tooltip per embed; content is built from text nodes and simple rows, never from data as HTML. */
  const tip = (root) => {
    root.style.position = root.style.position || "relative";
    const el = document.createElement("div");
    el.className = "gs-tip";
    el.setAttribute("role", "tooltip");
    root.appendChild(el);
    const place = (x, y) => {
      const r = root.getBoundingClientRect();
      const w = el.offsetWidth, h = el.offsetHeight;
      let left = x + 14, top = y + 12;
      if (left + w > r.width - 4) left = Math.max(4, x - w - 14);
      if (top + h > r.height + 40) top = Math.max(-40, y - h - 12);
      el.style.transform = `translate(${left}px, ${top}px)`;
    };
    return {
      show(build, ev) {
        el.replaceChildren();
        build(el);
        el.style.opacity = "1";
        const r = root.getBoundingClientRect();
        const p = ev && ev.touches ? ev.touches[0] : ev;
        if (p && p.clientX != null) place(p.clientX - r.left, p.clientY - r.top);
        else if (ev && ev.target && ev.target.getBoundingClientRect) {
          const b = ev.target.getBoundingClientRect();
          place(b.left - r.left + b.width / 2, b.top - r.top + b.height / 2);
        }
      },
      hide() { el.style.opacity = "0"; el.style.transform = "translate(-9999px, -9999px)"; },
    };
  };

  /* Tooltip content helpers: a title, rows of [label, value], an optional color key. */
  const t = {
    title(el, text, color) {
      const d = document.createElement("div");
      d.className = "t";
      if (color) { const k = document.createElement("i"); k.className = "key"; k.style.background = color; d.appendChild(k); }
      d.appendChild(document.createTextNode(text));
      el.appendChild(d);
    },
    row(el, label, value) {
      const d = document.createElement("div");
      d.className = "row";
      const a = document.createElement("span"); a.textContent = label;
      const b = document.createElement("span"); b.textContent = value;
      d.append(a, b);
      el.appendChild(d);
    },
    note(el, text) {
      const d = document.createElement("div");
      d.style.cssText = "margin-top:4px;color:var(--muted-color)";
      d.textContent = text;
      el.appendChild(d);
    },
  };

  const minus = (s) => String(s).replace(/-/g, "−");
  const fmt = {
    n: (x, d = 3) => (x == null || Number.isNaN(x) ? "–" : minus(Number(x).toFixed(d))),
    s: (x, d = 3) => (x == null ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "±") + Math.abs(x).toFixed(d)),
    ci: (c, d = 3, sign = false) => (c ? `[${sign ? fmt.s(c[0], d) : fmt.n(c[0], d)}, ${sign ? fmt.s(c[1], d) : fmt.n(c[1], d)}]` : ""),
    usd: (x, d) => {
      if (x == null) return "–";
      const a = Math.abs(x);
      const dd = d != null ? d : a >= 100 ? 0 : a >= 1 ? 2 : a >= 0.01 ? 4 : 5;
      return (x < 0 ? "−$" : "$") + a.toLocaleString("en-US", { minimumFractionDigits: dd, maximumFractionDigits: dd });
    },
    k: (x, d = 1) => (x == null ? "–" : (x < 0 ? "−$" : "$") + Math.abs(x).toFixed(d) + "k"),
    pct: (x, d = 0) => (x == null ? "–" : (100 * x).toFixed(d) + "%"),
    int: (x) => (x == null ? "–" : Math.round(x).toLocaleString("en-US")),
    he: (h) => `HE${String(h + 1).padStart(2, "0")}`,
    hour: (h) => { const x = h % 24; return x === 0 ? "midnight" : x === 12 ? "noon" : x < 12 ? `${x} am` : `${x - 12} pm`; },
  };

  /* The models, with one colour each, as on the Space's results page; open weights are dots, API models diamonds. */
  const FAMILY = {
    qwen: { color: "var(--c-qwen)", shape: "dot" }, base: { color: "var(--c-base)", shape: "dot" },
    sol: { color: "var(--c-sol)", shape: "dia" }, luna: { color: "var(--c-luna)", shape: "dia" },
    beam: { color: "var(--c-beam)", shape: "dot" }, rule: { color: "var(--c-rule)", shape: "bar" },
  };
  const family = (row) => (row.family === "qwen" && row.key === "base" ? "base" : row.family || "rule");
  const colorOf = (row) => (FAMILY[family(row)] || FAMILY.rule).color;
  const shapeOf = (row) => (FAMILY[family(row)] || FAMILY.rule).shape;
  const labelOf = (row) => row.label + (row.effort ? `, ${row.effort}` : "");

  const symbol = (sel, shape, x, y, r, color, fill = 1) => {
    if (shape === "dia") {
      const s = r * 1.3;
      return sel.append("path").attr("d", `M${x},${y - s}L${x + s},${y}L${x},${y + s}L${x - s},${y}Z`)
        .style("fill", color).style("fill-opacity", fill).style("stroke", color).style("stroke-width", 1.6)
        .style("stroke-linejoin", "round");
    }
    return sel.append("circle").attr("cx", x).attr("cy", y).attr("r", r).style("fill", color)
      .style("fill-opacity", fill).style("stroke", color).style("stroke-width", 1.6);
  };

  window.GridsimKit = { data, mount, config, whenD3, watch, css, dark, tip, t, fmt, colorOf, shapeOf, labelOf, family, symbol, FAMILY };
})();
