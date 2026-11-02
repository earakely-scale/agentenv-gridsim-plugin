"""The run film: one benchmark episode replayed on the desk viewer's 3D site and filmed as a GIF, with the desk beside
it: the agent's tool calls in order (the current one lit) with the results the run recorded, the node's price and the
battery's charge below as they post, then the settled grade beside the real operator's. The clock stands still while the
agent works and runs between its turns; the replay is driven frame by frame, so every film is the same.

    .venv/bin/python scripts/hub_space.py --only bench       # the viewer Space, built once into build/hub/space
    .venv/bin/python scripts/hub_desk_film.py --out build/article/media/gridsim-run.gif
    .venv/bin/python scripts/hub_desk_film.py --out build/article/stills --stills 4,20.5,31   # PNG stills instead
"""

import argparse
import base64
import gzip
import importlib.util
import io
import json
import re
import subprocess
import tempfile
import time
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import unescape
from pathlib import Path

from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "hub" / "desk-film"
BENCH = ROOT / "results" / "desk-v4-bench"
ACTS = ("submit_dam_offers", "submit_rt_offers", "update_cop")
PACE = {"lead": 0.4, "event": 0.45, "read": 0.19, "act": 0.48, "quote": 2.5, "tail": 0.25}
LAG = {"read": 0.1, "act": 0.3}
READS_MAX = 1.8
PLAY_S, PLAY_MIN, END_S, SPLIT_H = 8.5, 1.0, 4.6, 18
DAY_BEFORE = 0.45
DUSK = ("ramp", "establish")
WOKE = {"notice": "ERCOT notice", "nws": "weather alert", "checkpoint": "shift checkpoint", "reminder": "its reminder",
        "dam_results": "DAM results", "outage": "outage", "deployment": "deployment", "adjustment_open": "RT opens"}
HEADS = {"start": "The day-ahead market is open", "dam_results": "Day-ahead results are in",
         "adjustment_open": "Real-time offers open", "checkpoint": "Shift checkpoint", "reminder": "A reminder it set",
         "notice": "An ERCOT notice", "nws": "A weather alert", "outage": "An outage", "deployment": "A deployment",
         "dam_morning": "Day-ahead morning"}
WARMUP = 320


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--space", type=Path, default=ROOT / "build" / "hub" / "space",
                    help="The built viewer Space (scripts/hub_space.py --only bench).")
    ap.add_argument("--results", type=Path, default=BENCH)
    ap.add_argument("--model", help="The run's model key; the benchmark's lead run (summary.json's hero) by default.")
    ap.add_argument("--task", help="The run's window; the benchmark's lead run by default.")
    ap.add_argument("--hold", help="Comma-separated turn numbers to hold, overriding the automatic choice.")
    ap.add_argument("--shots", help="Comma-separated shot per beat (establish, high, push, ramp, line, city, sub), "
                                    "overriding the automatic choice.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--css-size", default="960x540", help="The page's CSS size; the GIF is this times --scale.")
    ap.add_argument("--scale", type=float, default=1.25)
    ap.add_argument("--fps", type=int, default=15, help="Frames a second while the agent works and at the end.")
    ap.add_argument("--play-fps", type=int, default=12, help="Frames a second while the clock runs.")
    ap.add_argument("--step", type=int, default=4, help="While the clock runs, the site moves every this many frames.")
    ap.add_argument("--frames", type=Path, help="Keep the PNG frames in this folder.")
    ap.add_argument("--stills", help="Comma-separated film seconds: write those frames as PNGs into --out, no GIF.")
    args = ap.parse_args()
    s, grades = bench(args.results)
    model, task = args.model or s["hero"]["model"], args.task or s["hero"]["task_id"]
    g = next(x for x in grades if x["model"] == model and x["task_id"] == task and x["status"] == "scored")
    hdh = module("hub_desk_hero", "scripts/hub_desk_hero.py")
    path = args.results / g["episode"]
    ep = hdh.regraded(hdh.read(path), path, args.results / "grades.jsonl.gz")
    holds = [int(x) for x in args.hold.split(",")] if args.hold else hdh.pick(ep)[:3]
    data = card(ep, s, g, holds, hdh)
    beats = plan(ep, data, holds, args.shots.split(",") if args.shots else None)
    frames = timeline(beats, args.fps, args.play_fps, args.step)
    hk = module("hub_desk", "scripts/hub_desk.py")
    hk.anonymous({"film.json": json.dumps(data, ensure_ascii=False).encode()}, hk.names(ROOT))
    cw, ch = (int(v) for v in args.css_size.split("x"))
    w, h = round(cw * args.scale), round(ch * args.scale)
    print(f"{task} {model}: holds turns {holds}, {len(beats)} beats, {len(frames)} frames, "
          f"{frames[-1]['s'] + 1 / args.fps:.1f} s")
    url = f"index.html?v=bench&m={model}&task={task}&play=0"
    if args.stills:
        want = [float(x) for x in args.stills.split(",")]
        keep = {min(range(len(frames)), key=lambda i, x=x: abs(frames[i]["s"] - x)) for x in want}
        args.out.mkdir(parents=True, exist_ok=True)
        film(args.space, url, data, frames, args.out, (cw, ch), args.scale, keep)
        return
    hh = module("hub_hero", "scripts/hub_hero.py")
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        shots = args.frames or Path(tmp)
        shots.mkdir(parents=True, exist_ok=True)
        film(args.space, url, data, frames, shots, (cw, ch), args.scale)
        parts = []
        for k, sg in enumerate(segments(frames)):
            parts.append(Path(tmp) / f"s{k:04d}.gif")
            segment(shots, sg, parts[-1], args.play_fps if sg["mode"] == "play" else args.fps, w, h)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        n = hh.join(parts, args.out, w, h)
    print(f"{args.out}: {w}x{h}, {n} frames, {frames[-1]['s']:.1f} s, {args.out.stat().st_size / 1e6:.2f} MB, "
          f"rendered in {time.monotonic() - t0:.0f} s")


def segments(frames: list[dict]) -> list[dict]:
    """The GIF's parts, each with its own 256 colours: a turn or the grade whole, and each step of the site while the
    clock runs."""
    out = []
    for i, f in enumerate(frames):
        if not out or f["beat"] != frames[i - 1]["beat"] or (f["mode"] == "play" and f["site"]):
            out.append({"start": i, "n": 0, "mode": f["mode"]})
        out[-1]["n"] += 1
    return out


def segment(shots: Path, sg: dict, out: Path, fps: int, w: int, h: int) -> None:
    """Error-diffused, so the sky at dusk has no bands; between the site's steps only the desk changes, and the
    rectangle mode re-quantises only that. Frames go in as raw RGB: read as PNGs, every frame is encoded whole."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-start_number", str(sg["start"]), "-i", str(shots / "f%05d.png"),
                          "-frames:v", str(sg["n"]), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r",
                    str(fps), "-i", "-", "-filter_complex", f"split[a][b];[a]palettegen=stats_mode=full[p];[b][p]{USE}",
                    str(out)], input=raw, check=True)


def bench(folder: Path) -> tuple[dict, list[dict]]:
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        return json.loads((folder / "summary.json").read_text()), [json.loads(x) for x in f if x.strip()]


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


TAG = re.compile(r"<[^>]+>")
USE = "paletteuse=dither=sierra2_4a:diff_mode=rectangle"


def plain(html: str) -> str:
    return re.sub(r"\s+", " ", unescape(TAG.sub(" ", html or ""))).strip()


def card(ep: dict, s: dict, g: dict, holds: list[int], hdh) -> dict:
    """What the frame shows, from the episode alone: the run, its price, charge and settlement as they post, each held
    turn's events and calls with the results the run recorded, each other turn as a line, and the grade."""
    m, dates = s["models"][g["model"]], ep["dates"]
    d0, nd = date.fromisoformat(dates[0]), len(dates)
    front = next(f for f in s["fronts"] if f["front"] == g["front"])
    cat = lambda key, sub: [x for d in dates for x in ep[key][d][sub]]  # noqa: E731
    soc = [x for d in dates for x in ep["rt"][d]["soc_mwh"][:-1]] + [ep["rt"][dates[-1]]["soc_mwh"][-1]]
    rt = cat("rt", "spp")
    days = [d0 - timedelta(1) + timedelta(j) for j in range(nd + 1)]
    turns = {str(n): turn(ep, n, d0, hdh) for n in holds}
    gd, c = ep["grade"], ep["site"]["card"]
    rows = [{"label": m["name"], "p": gd["p"], "color": "var(--fm-agent)", "me": True}]
    if gd.get("p_operator_actual") is not None:
        rows.append({"label": "The real operator, as it ran", "p": gd["p_operator_actual"], "color": "var(--fm-op)"})
    if gd.get("p_operator_replay") is not None:
        rows.append({"label": "Its own bids, replayed", "p": gd["p_operator_replay"], "color": "var(--fm-op-2)"})
    rows.append({"label": "Hindsight optimum", "p": gd["p_hind"], "color": "var(--fm-hind)"})
    return {
        "tag": m.get("tag") or m["name"].split()[-1], "kicker": "a recorded benchmark run",
        "headline": f"{m['name']} trades {c['name']}, {c['region']}",
        "sub": f"{c['size']} · {front['kind']}, {span(d0, days[-1])} · {m['harness']}",
        "foot": f"{sum(len(t['calls']) for t in ep['turns'])} tool calls over {len(ep['turns'])} wake-ups. The agent "
                "sends ERCOT's own objects: offer curves and the operating plan.",
        "site": {"emax": ep["site"]["e_max_mwh"]}, "nd": nd, "t0": min(w["t"] for w in ep["wakes"]),
        "t1": 1440 * nd, "k": DAY_BEFORE,
        "dayNames": [f"{d:%a} {d.day} {d:%b}" for d in days],
        "dayLabels": [f"{days[0]:%a} {days[0].day}"] + [f"{d:%a} {d.day} {d:%b}" for d in days[1:]],
        "rt": rt, "pmax": nice(max(rt)), "soc": soc,
        "pnl": hdh.pnl(ep, d0), "nturns": len(ep["turns"]), "turns": turns,
        "wakes": [{"t": t["t"], "held": i in holds, "time": hdh.label_time(t, d0), "chips": chips(t, ep, hdh)}
                  for i, t in enumerate(ep["turns"])],
        "grade": {"p": gd["p"], "C": f"{pc(gd['capture'])}%", "R": f"{gd['reward']:.2f}", "rows": rows,
                  "note": "Profit over the three operating days, on ERCOT's real prices; the operator's is settled "
                          "the same way. Degradation and the end-of-window charge are modelled."},
    }


def pc(x: float) -> str:
    """C in percent as the dataset card prints it: one decimal, half-up on the stored value."""
    q = (Decimal(str(x)) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return f"{'−' if q < 0 else ''}{abs(q)}"


def span(a: date, b: date) -> str:
    same = (a.year, a.month) == (b.year, b.month)
    return f"{a.day}–{b.day} {b:%B %Y}" if same else f"{a.day} {a:%B} – {b.day} {b:%B %Y}"


def nice(x: float) -> float:
    for step in (10, 25, 50, 100, 250, 500, 1000):
        if x <= step * 8:
            return float(step * -(-x // step))
    return float(x)


def turn(ep: dict, n: int, d0: date, hdh) -> dict:
    """A held turn: the events that woke the agent, then each call with what it asked and what came back, paced: reads
    quickly, submissions slower, the agent's own words at the end."""
    t = ep["turns"][n]
    w = t.get("wake") or {}
    rs = hdh.reasons(ep, t)
    reason = HEADS.get(rs[0], hdh.REASONS.get(rs[0], rs[0])) if rs else "A wake-up"
    p, events, calls = PACE["lead"], [], []
    for ev in w.get("events") or []:
        if ev.get("kind") in ("druc", "dam_close"):
            continue
        it = hdh.event(ev)
        if not it:
            continue
        cls = {"rem": "own", "ck": "ck"}.get(it.get("cls"), "")
        text = re.sub(r"^\d\d:\d\d\s+(its own reminder:\s+)?", "", plain(it["html"]).lstrip("⚑⏰ ").strip())
        events.append({"text": text, "cls": cls, "at": round(p, 3)})
        p += PACE["event"]
    reads = sum(1 for c in t["calls"] if c["tool"] not in ACTS)
    per = min(PACE["read"], READS_MAX / max(1, reads))
    for c in t["calls"]:
        tool, a, r = c["tool"], c.get("args") or {}, c.get("result") or {}
        small, lines, res, cls = hdh.describe(tool, a, r, ep)
        err = r.get("error") if isinstance(r, dict) else None
        act = tool in ACTS
        row = {"tool": tool, "act": act, "cls": "no" if err or cls == "no" else cls, "at": round(p, 3)}
        if err:
            row |= {"d": plain(small), "r": f"✗ {plain(hdh.cut(str(err), 90))}", "mark": "✗"}
        elif act:
            row |= {"d": plain(lines[0]) + (" …" if len(lines) > 1 else "") if lines else plain(small),
                    "mark": plain(res).split(" · ")[0].replace("accepted ", "") or "✗"}
        elif tool == "set_reminder":
            row |= {"d": plain(lines[0]) if lines else plain(small), "mark": plain(res).split(",")[0]}
        elif tool == "check_submission":
            row |= {"d": plain(small), "r": plain(res).lstrip("✓✗ "), "mark": "✓" if cls == "ok" else "✗"}
        else:
            row |= {"d": plain(small), "r": plain(res) or None}
        row["res"] = round(p + LAG["act" if act else "read"], 3)
        calls.append(row)
        p += PACE["act"] if act or tool in ("optimize", "set_reminder") else per
    text = hdh.clean(t.get("text") or "")
    quote = hdh.excerpt(text, 175) if text else None
    out = {"index": n, "time": hdh.label_time(t, d0), "reason": reason, "events": events,
           "calls": calls, "quote": quote}
    if quote:
        out["quoteAt"] = round(p + 0.15, 3)
        p += 0.15 + PACE["quote"]
    out["dur"] = round(p + PACE["tail"], 3)
    return out


def chips(t: dict, ep: dict, hdh) -> list[dict]:
    """A turn as one line: how many reads, then each plan it asked for and each submission, in order; a turn with no
    calls by what woke it."""
    if not t["calls"]:
        rs = hdh.reasons(ep, t)
        return [{"text": f"{WOKE.get(rs[0], rs[0]) if rs else 'woke'}, no calls"}]
    reads = sum(1 for c in t["calls"] if c["tool"] not in (*ACTS, "set_reminder", "check_submission", "optimize"))
    out = [{"text": f"{reads} {'read' if reads == 1 else 'reads'}"}] if reads else []
    for c in t["calls"]:
        tool, a, r = c["tool"], c.get("args") or {}, c.get("result") or {}
        if tool in (*ACTS, "optimize"):
            out.append({"text": hdh.chip_of(tool, a, r), "ok": bool(r.get("accepted_hours"))} if tool in ACTS
                       else {"text": "optimize"})
    return out or [{"text": "checks only"}]


def plan(ep: dict, data: dict, holds: list[int], shots: list[str] | None) -> list[dict]:
    """The beats: each held turn with the clock stopped, the clock running between them (faster where the battery
    rests and on the day before, slower where it moves), then the grade; each with a camera shot and its drift."""
    turns, t0, t1 = ep["turns"], data["t0"], data["t1"]
    mw = [x for d in ep["dates"] for x in ep["rt"][d]["metered_mw"]]
    beats, at = [], t0
    for n in holds:
        if turns[n]["t"] > at:
            beats.append({"mode": "play", "a": at, "b": turns[n]["t"]})
        beats.append({"mode": "hold", "turn": n, "a": turns[n]["t"], "b": turns[n]["t"],
                      "dur": data["turns"][str(n)]["dur"]})
        at = turns[n]["t"]
    beats.append({"mode": "play", "a": at, "b": t1})
    beats.append({"mode": "end", "a": t1, "b": t1, "dur": END_S})
    beats = [x for b in beats for x in split(b)]

    def weight(t: float) -> float:
        if t < 0:
            return DAY_BEFORE
        k = int(t // 5)
        return 3.0 if k < len(mw) and abs(mw[k]) > 2 else 1.0 if 360 <= t % 1440 < 1260 else 0.55

    plays = [b for b in beats if b["mode"] == "play"]
    for b in plays:
        b["w"] = [weight(t) for t in range(int(b["a"]), int(b["b"]), 5)]
    total = sum(sum(b["w"]) for b in plays)
    for b in plays:
        b["dur"] = max(PLAY_MIN, PLAY_S * sum(b["w"]) / total)
    dusk = iter(DUSK * len(beats))
    for i, b in enumerate(beats):
        b["shot"] = shots[i] if shots and i < len(shots) and shots[i] else shot(b, mw)
        b["shot"] = next(dusk) if b["shot"] == "ramp" and b["mode"] == "play" else b["shot"]
        b["u"] = 0.5 if b["mode"] == "play" else 0.4
    return beats


def split(b: dict) -> list[dict]:
    """A run of the clock longer than SPLIT_H hours, cut at each 06:00 inside it, so the camera can change shot."""
    if b["mode"] != "play" or b["b"] - b["a"] <= 60 * SPLIT_H:
        return [b]
    cuts = [t for t in range(int(b["a"]) // 1440 * 1440 - 1440, int(b["b"]) + 1440, 1440)
            if b["a"] + 360 < t + 360 < b["b"] - 360]
    edges = [b["a"], *(t + 360 for t in cuts), b["b"]]
    return [{"mode": "play", "a": a, "b": z} for a, z in zip(edges, edges[1:], strict=False)]


def shot(b: dict, mw: list[float]) -> str:
    """Night holds and the end on the establishing orbit, daytime holds from high, evening holds on the ramp; a run of
    the clock on the ramp when the battery discharges into an evening in it, from high by day, else establishing."""
    if b["mode"] != "play":
        m = b["a"] % 1440
        return "establish" if b["mode"] == "end" or m < 390 or m >= 1260 else "ramp" if m >= 960 else "high"
    dusk = [t for t in range(max(0, int(b["a"])), int(b["b"]), 5) if 1020 <= t % 1440 < 1260]
    if any(mw[t // 5] > 2 for t in dusk if t // 5 < len(mw)):
        return "ramp"
    mid = ((b["a"] + b["b"]) / 2) % 1440
    return "high" if 420 <= mid < 1140 else "establish"


def timeline(beats: list[dict], fps: int, play_fps: int, step: int) -> list[dict]:
    """Every frame: film second s, replay minute t, the beat, the camera's drift, and what the desk shows. While the
    clock runs the site moves on every step-th frame, a time-lapse, and the desk and the days below on every frame; in a
    turn and at the end the site holds still."""
    frames, s0 = [], 0.0
    for k, b in enumerate(beats):
        rate = play_fps if b["mode"] == "play" else fps
        n = max(2, round(b["dur"] * rate))
        if b["mode"] == "play":
            cum = [0.0]
            for x in b["w"]:
                cum.append(cum[-1] + x)
        for j in range(n):
            q = j / (n - 1)
            f = {"s": round(s0 + j / rate, 4), "beat": k, "mode": b["mode"], "shot": b["shot"], "u": b["u"],
                 "dt": step / rate if b["mode"] == "play" else 0.0,
                 "site": j % step == 0 if b["mode"] == "play" else j == 0}
            if b["mode"] == "play":
                goal, i = q * cum[-1], 0
                while i < len(b["w"]) - 1 and cum[i + 1] < goal:
                    i += 1
                f["t"] = round(b["a"] + 5 * (i + (goal - cum[i]) / b["w"][i]), 3)
                f["t3"] = f["t"] if f["site"] else frames[-1]["t3"]
            elif b["mode"] == "hold":
                f |= {"t": b["a"], "t3": b["a"], "turn": str(b["turn"]), "p": round(j / rate, 3)}
            else:
                f |= {"t": b["a"], "t3": b["a"], "e": round(j / rate, 3)}
            frames.append(f)
        s0 += n / rate
    return frames


DESK, BAND = 304, 84


def shot_png(page) -> bytes:
    return base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"])


def blank(png: bytes, box: tuple[int, int, int, int]) -> bool:
    """The site's canvas came back empty: headless Chrome now and then presents a WebGL frame before it is drawn."""
    return ImageStat.Stat(Image.open(io.BytesIO(png)).convert("L").crop(box).resize((96, 54))).stddev[0] < 2.5


NO_HAZE = ("(() => { Object.defineProperty(gridsim.stage.shimmer.uniforms.uAmt, 'value', "
           "{ get: () => 0, set: () => {} }); return true; })()")
NO_NAN = """(() => {
  const m = gridsim.stage.shimmer.material;
  const bad = "(any(isnan(c)) || any(isinf(c)))";
  m.fragmentShader = m.fragmentShader.replace("void main() {", `vec4 clean(vec2 uv) {
    vec4 c = texture2D(tDiffuse, uv);
    if (!${bad}) return c;
    vec2 px = 1.0 / vec2(textureSize(tDiffuse, 0));
    for (int i = 1; i <= 8; i++) {
      c = texture2D(tDiffuse, uv + vec2(0.0, float(i) * px.y));
      if (!${bad}) return c;
      c = texture2D(tDiffuse, uv - vec2(0.0, float(i) * px.y));
      if (!${bad}) return c;
    }
    return vec4(0.0, 0.0, 0.0, 1.0);
  }
  void main() {`).replaceAll("grade(texture2D(tDiffuse, uv))", "grade(clean(uv))");
  m.needsUpdate = true;
  return true;
})()"""

RAF = """(() => {
  const q = []; let now = performance.now();
  window.requestAnimationFrame = (cb) => (q.push(cb), q.length);
  window.__raf = (ms) => { now += ms; const cbs = q.splice(0); cbs.forEach((cb) => cb(now)); return true; };
  return true;
})()"""


def film(space: Path, url: str, data: dict, frames: list[dict], out: Path, size: tuple[int, int], scale: float,
         keep: set[int] | None = None) -> None:
    """Drive the viewer frame by frame: the replay's own animation loop runs only when a frame steps it, so the wall
    clock that moves fans and the line's pulses advances by the film's frame time and stands still in a turn. The odd
    pixel at the horizon that renders as not-a-number takes its neighbour's colour instead of black, and the heat haze,
    which would smear such pixels into streaks, is off."""
    rec = module("record", "scripts/record.py")
    w, h = size
    with rec.serve(space) as port, tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(None), Path(profile), w, h), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale,
                          mobile=False)
                page.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": "dark"}])
                page.call("Runtime.enable")
                page.call("Page.navigate", url=f"http://127.0.0.1:{port}/{url}")
                page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.gridsim ? r() : "
                        "Date.now() - s > 60000 ? j('timeout') : setTimeout(f, 50); f(); })")
                page.js("gridsim.ready.then(() => document.fonts.ready).then(() => true)")
                css = (PAGE / "film.css").read_text()
                page.js(f"(() => {{ const s = document.createElement('style'); s.textContent = {json.dumps(css)}; "
                        "document.head.append(s); return true; })()")
                page.js((PAGE / "film.js").read_text() + "; true")
                page.js(f"film.init({json.dumps(data, ensure_ascii=False)}); true")
                page.js("new Promise((r) => setTimeout(() => { gridsim.stage.resize(); r(true); }, 300))")
                page.js(NO_HAZE)
                page.js(NO_NAN)
                page.js(RAF)
                page.js(f"(() => {{ for (let i = 0; i < {WARMUP}; i++) __raf(16); return true; }})()")
                box, again = (0, 0, round((w - DESK) * scale), round((h - BAND) * scale)), 0
                for i, f in enumerate(frames):
                    if keep is not None and i not in keep:
                        continue
                    site = (f"gridsim.stage.force = {json.dumps(f['shot'])}; gridsim.stage.drift = {f['u']}; "
                            f"gridsim.seek({f['t3']}); __raf({1000 * f['dt']}); ") if f["site"] or keep else ""
                    page.js(f"{site}film.render({json.dumps(f)}); true")
                    png = shot_png(page)
                    while blank(png, box):
                        again += 1
                        if again > 20:
                            raise SystemExit(f"frame {i}: the site keeps rendering blank")
                        page.js(f"gridsim.seek({f['t3']}); __raf(0); true")
                        png = shot_png(page)
                    (out / (f"f{i:05d}.png" if keep is None else f"s{f['s']:06.2f}.png")).write_bytes(png)
                if again:
                    print(f"re-rendered {again} blank frames of the site")
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    main()
