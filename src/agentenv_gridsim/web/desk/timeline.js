/** The replay's scrubber: the episode from the desk's opening the day before to the end of the last operating day,
 * each operating day marked, a tick for every wake-up (market milestones in ink, ERCOT notices, NWS alerts and
 * outages in red, the agent's own reminders in blue), and the handle at the replay's minute. */
import { EVENTFUL, REASONS, clock, esc, weekday } from "./fmt.js";

const NS = "http://www.w3.org/2000/svg";
const PAD = 8, TY = 17;

export function buildTimeline(M, host, { onSeek }) {
  const svg = document.createElementNS(NS, "svg");
  host.replaceChildren(svg);
  const hover = document.createElement("div");
  hover.className = "stip";
  hover.hidden = true;
  host.append(hover);
  const el = (tag, attrs = {}, parent = svg) => {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    parent.append(e);
    return e;
  };
  const st = { W: 0 };
  const X = (t) => PAD + ((t - M.t0) / (M.t1 - M.t0)) * (st.W - 2 * PAD);
  const T = (x) => M.t0 + ((x - PAD) / (st.W - 2 * PAD)) * (M.t1 - M.t0);
  const kind = (why) => (why.some((r) => EVENTFUL.has(r)) ? "ev" : why.includes("reminder") && why.length === 1 ? "rem" : why.every((r) => r === "checkpoint") ? "ck" : "mk");

  function build() {
    st.W = Math.max(200, host.clientWidth);
    const H = host.clientHeight || 46;
    svg.setAttribute("viewBox", `0 0 ${st.W} ${H}`);
    svg.replaceChildren();
    el("rect", { x: PAD, y: TY - 2, width: st.W - 2 * PAD, height: 4, rx: 2, class: "trk" });
    st.played = el("rect", { x: PAD, y: TY - 2, width: 0, height: 4, rx: 2, class: "played" });
    for (let j = 0; j <= M.n; j++) {
      const x = X(1440 * j);
      el("line", { x1: x, x2: x, y1: TY - 9, y2: TY + 9, class: "daymark" });
    }
    for (let j = -1; j < M.n; j++) {
      const a = Math.max(M.t0, 1440 * j), b = Math.min(M.t1, 1440 * j + 1440);
      const lab = el("text", { x: (X(a) + X(b)) / 2, y: TY + 22, class: "tk day", "text-anchor": "middle" });
      lab.textContent = j < 0 ? `${weekday(M.d0, 1440 * j)}, day before` : weekday(M.d0, 1440 * j);
    }
    for (const w of M.wakes) {
      const x = X(w.t), k = kind(w.why), tall = w.turn ? 7 : 3;
      el("line", { x1: x, x2: x, y1: TY - 3 - tall, y2: TY - 3, class: `wk ${k}` });
    }
    for (let j = 0; j < M.n; j++) {
      const x = X(M.posted[j]);
      el("path", { d: `M${x - 3.5},${TY + 4.5}L${x + 3.5},${TY + 4.5}L${x},${TY + 9}Z`, class: "dammark" });
    }
    st.handle = el("circle", { cx: PAD, cy: TY, r: 6.5, class: "handle" });
  }

  let drag = false;
  const at = (e) => {
    const r = svg.getBoundingClientRect();
    return T(((e.clientX - r.left) / r.width) * st.W);
  };
  const snap = (t) => {
    const px = (M.t1 - M.t0) / (st.W - 2 * PAD);
    const w = M.wakes.find((x) => Math.abs(x.t - t) < 5 * px);
    return w ? w.t - 0.01 : t;
  };
  host.addEventListener("pointerdown", (e) => {
    drag = true;
    host.setPointerCapture(e.pointerId);
    onSeek(snap(at(e)));
  });
  host.addEventListener("pointermove", (e) => {
    const t = at(e);
    if (drag) onSeek(t);
    const w = M.wakes.find((x) => Math.abs(X(x.t) - X(t)) < 5);
    hover.innerHTML = `<b>${esc(weekday(M.d0, w ? w.t : t))} ${clock(w ? w.t : t)}</b>${w ? ` ${esc(w.why.map((r) => REASONS[r] || r).join(", "))}${w.turn ? `, ${w.turn.calls.length} calls` : ", no turn left"}` : ""}`;
    hover.hidden = false;
    const x = (X(w ? w.t : t) / st.W) * host.clientWidth;
    hover.style.left = `${Math.max(0, Math.min(host.clientWidth - hover.offsetWidth, x - hover.offsetWidth / 2))}px`;
  });
  host.addEventListener("pointerup", () => (drag = false));
  host.addEventListener("pointerleave", () => (hover.hidden = true));
  host.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 60 : 15;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") (e.preventDefault(), e.stopPropagation(), onSeek(st.t + (e.key === "ArrowRight" ? step : -step)));
    else if (e.key === "Home") onSeek(M.t0);
    else if (e.key === "End") onSeek(M.t1);
  });

  return {
    update(S) {
      if (Math.abs(host.clientWidth - st.W) > 1 || !st.handle) build();
      const t = Math.max(M.t0, Math.min(M.t1, S.t));
      if (st.t === t) return;
      st.t = t;
      const x = X(t);
      st.played.setAttribute("width", Math.max(0, x - PAD));
      st.handle.setAttribute("cx", x);
      host.setAttribute("aria-valuenow", Math.round(t));
      host.setAttribute("aria-valuetext", `${weekday(M.d0, t)} ${clock(t)}`);
      host.setAttribute("aria-valuemin", M.t0);
      host.setAttribute("aria-valuemax", M.t1);
    },
  };
}
