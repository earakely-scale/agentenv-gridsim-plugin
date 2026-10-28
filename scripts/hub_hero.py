"""The dataset card's hero GIF: a v3 replay filmed in the viewer beside the agent's own episode: each watch's notices
and tool calls with the results the run recorded, its words at each commit, its book, each hour as it plays, the grade.

The clock stands still while the agent works and runs between watches, so a frame changes only where something
happens; pixels that move less than --hold levels keep the previous frame's value, and each beat gets its own 256
colours. --space is a built viewer Space with the v3 replay: the previews branch's build/hub/space, or a download of the
Space earakely-scale/GridSimEnv-AgentEnv.

    .venv/bin/python scripts/hub_hero.py --space SPACE_DIR --out build/hub/hero/gridsim-hero.gif
"""

import argparse
import base64
import importlib.util
import json
import re
import subprocess
import tempfile
from datetime import date, timedelta
from html import escape
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EPISODE = "runs/hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150-0xqk8eef.json"
BEATS = (("hold", -2.0, -2.0, 6.2, "establish", 14.0), ("play", 7.9, 8.9, 2.0, "push", 8.4),
         ("play", 13.55, 15.45, 2.0, "line", 14.5), ("hold", 15.5, 15.5, 6.4, "high", 15.5),
         ("play", 15.55, 18.0, 2.0, "city", 16.8), ("hold", 18.0, 18.0, 8.6, "establish", 18.0),
         ("play", 19.0, 19.4, 1.6, "push", 19.2), ("play", 20.1, 20.6, 1.7, "city", 20.35),
         ("end", 24.0, 24.3, 4.4, "establish", 24.15))
QUOTES = (("charge at low DA prices, keep the battery full through the scarcity hours", "and discharge at hour 21."),
          ("about 22.71 MWh short of the SoC needed to back its fixed 100 MW ECRS award at hour 19.",
           "I’ll schedule replenishment before then."),
          ("I’m canceling the hour-21 discharge and scheduling a small recharge at hour 20 to preserve the 100 MWh "
           "needed",))
PRODUCT = {"regup": "RegUp", "regdn": "RegDn", "rrs": "RRS", "ecrs": "ECRS", "nspin": "Non-Spin"}
PACE = {"get_situation": 0.9, "check_schedule": 1.1, "commit_schedule": 0.55}
WAIT = {"get_situation": 0.3, "check_schedule": 0.5, "commit_schedule": 0.3}
SUN = ("(() => { const s = gridsim.stage.sky, u = s.update, a = s.sunAt; "
       "s.update = (t, w, x) => u(window.sunT ?? t, w, x); s.sunAt = (t) => a(window.sunT ?? t); return true; })()")


def money(x: float, sign: bool = False) -> str:
    return ("+" if x >= 0 else "−") * sign + ("−" if x < 0 and not sign else "") + f"${abs(x):,.0f}"


def mw(x: float) -> str:
    x = abs(x)
    return f"{x:.0f}" if abs(x - round(x)) < 0.005 else f"{x:.1f}" if abs(x * 10 - round(x * 10)) < 0.05 else f"{x:.2f}"


def approx(x: float) -> str:
    return f"{abs(x):.0f}" if abs(x) >= 10 else f"{abs(x):.1f}"


def hhmm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def hours(hs: list[int]) -> str:
    runs = []
    for h in hs:
        if runs and h == runs[-1][1] + 1:
            runs[-1][1] = h
        else:
            runs.append([h, h])
    return ("hour " if len(hs) == 1 else "hours ") + ", ".join(f"{a}" if a == b else f"{a}–{b}" for a, b in runs)


def blocks(field) -> list[tuple[int, int, float]]:
    return [(b["from"], b["to"], b["mw"]) for b in field] if isinstance(field, list) else []


def plan_lines(plan: dict, book: list[float], start: int) -> list[str]:
    """A plan as what it does to the book from its first hour: the moves it adds, drops and keeps, and the reserves."""
    new = [0.0] * 24
    for a, b, v in blocks(plan["energy"]):
        new[a:b] = [v] * (b - a)
    out = []
    for verb, sign in (("charge", -1), ("discharge", 1)):
        xs = [h for h in range(start, 24) if abs(book[h] - new[h]) >= 0.05 and new[h] * sign >= 0.05]
        if xs:
            out.append(f"{verb} " + ", ".join(f"{mw(new[h])} MW in hour {h}" for h in xs))
    for h in range(start, 24):
        move = "discharge" if (book[h] if abs(new[h]) < 0.05 else new[h]) > 0 else "charge"
        if abs(book[h] - new[h]) >= 0.05 and abs(new[h]) < 0.05:
            out.append(f"drop the {mw(book[h])} MW {move} in hour {h}")
        elif abs(book[h] - new[h]) < 0.05 and abs(new[h]) >= 0.05:
            out.append(f"keep the {move} in hour {h}")
    if all(plan.get(k) in ("keep", None) for k in PRODUCT):
        return out + ["reserves: keep"]
    for k, name in PRODUCT.items():
        bs = blocks(plan.get(k))
        hs = [h for a, b, v in bs for h in range(a, b) if abs(v) > 0.05]
        if hs:
            vals = sorted({v for _, _, v in bs if abs(v) > 0.05})
            out.append(f"{name} {mw(vals[0])}{'' if len(vals) == 1 else '–' + mw(vals[-1])} MW, {hours(hs)}")
    return out


def quote(name: str, frags: tuple[str, ...], said: str) -> str:
    """The agent's words cut to fragments, each found verbatim, with an ellipsis wherever words were left out."""
    text, pos, out = said.strip(), 0, ""
    for k, frag in enumerate(frags):
        at = text.index(frag, pos)
        out += ("…" if at and not re.search(r"[.!?]\s*$", text[:at]) else "") if k == 0 else \
            (" " if not text[pos:at].strip() else " … ")
        out, pos = out + frag, at + len(frag)
    return f"<b>{escape(name)}:</b> “{escape(out + ('' if pos == len(text) or frags[-1].endswith('.') else '…'))}”"


def watch_items(ep: dict, short: str) -> tuple[dict[int, list[dict]], dict[int, str]]:
    """Each watch's entries in order: the env's notices and the agent's calls with the results the run recorded."""
    watches = ep["watches"]
    said = [m["content"] for m in ep.get("messages") or [] if m["role"] == "assistant" and m.get("content")]
    e_mwh, eta = ep["task"]["site"]["bess"]["e_mwh"], ep["task"]["site"]["bess"]["eta"]
    book, booked, commits, out = [0.0] * 24, {}, 0, {}
    for s in ep["steps"]:
        o, a, w, tool = s["output"] or {}, s["args"] or {}, s["watch"], s["tool"]
        its = out.setdefault(w, [])
        if tool == "grid_notice":
            its.append({"kind": "notice", "html": notice(a, ep), "chip": chip(a)})
            continue
        it = {"kind": "call", "tool": tool, "lines": [], "cls": "ok", "chip": f"<i>{tool}</i>"}
        if tool in ("check_schedule", "commit_schedule"):
            start, p = a.get("from_hour", 0), o.get("projected") or {}
            it["head"], it["lines"] = f"from hour {start}", plan_lines(a["plan"], book, start)
            if tool == "check_schedule" and o.get("feasible"):
                it["result"] = f"✓ feasible · projects {money(p['total_usd'])}"
                it["chip"] = f'<i class="ok">{tool} ✓</i>'
            elif tool == "check_schedule":
                iss = o["issues"][0]
                it["cls"], it["chip"] = "no", f'<i class="no">{tool} ✗</i>'
                it["result"] = f'✗ hour {iss["hour"]} refused: <span class="m">{escape(iss["detail"])}</span>'
                tie = re.search(r"need ([\d.]+) MWh.*SoC ([\d.]+)$", iss["detail"])
                if tie and tie[1] == tie[2]:
                    h = iss["hour"]
                    charge = sum(-v for x, y, v in blocks(a["plan"]["energy"]) if x <= h < y and v < 0)
                    exact = ep["soc_path"][h] + eta * charge
                    it["result"] += f' <span class="dim">({exact:.4f} before rounding)</span>'
            else:
                it["result"] = f"✓ booked {hours(o['committed'])} · projects {money(p['total_usd'])}"
                it["chip"], it["keep"] = f'<i class="ok">{tool} ✓</i>', True
                old, book = book, [float(x) for x in o["book"]["energy"]]
                changed = [h for h in range(24) if abs(old[h] - book[h]) > 0.05]
                at = watches[w]["time"].split(" ")[1]
                booked |= {h: f"at {at}" if w else "the day before" for h in changed}
                reserve = [round(sum(o["book"][k][h] for k in PRODUCT), 2) for h in range(24)]
                it["book"] = {"energy": book, "reserve": reserve, "changed": changed if commits else [],
                              "label": f"as of {at}"}
                if commits < min(len(said), len(QUOTES)):
                    it["quote"] = quote(short, QUOTES[commits], said[commits])
                commits += 1
        elif tool == "get_situation":
            p = o["projected"]
            gap = [(h, -m) for h, m in enumerate(p["reserve_margin_mwh"]) if m < -0.005]
            it["result"] = f"SoC {o['soc_mwh']:.0f} of {e_mwh:.0f} MWh · projects {money(p['total_usd'])}"
            if gap:
                it["cls"] = "no"
                each = ", ".join(mw(m) for _, m in gap)
                it["result"] = (f"reserve short {mw(gap[0][1])} MWh in hour {gap[0][0]}" if len(gap) == 1 else
                                f"reserve short in {hours([h for h, _ in gap])} ({each} MWh)")
        else:
            nxt = watches[w + 1]["time"].split(" ")[1] if w + 1 < len(watches) else None
            it["cls"] = "adv"
            it["result"] = (f"→ waits until {nxt} (the next watch)" if nxt else
                            "→ no watch left: the day plays out to 24:00")
        small = f"<small>{it['head']}</small>" if it.get("head") else ""
        lines = "".join(f'<div class="a">{escape(x)}</div>' for x in it["lines"])
        it["html"] = f'<div class="tool">{tool}{small}</div>{lines}<div class="r"></div>'
        its.append(it)
        if it.get("quote"):
            its.append({"kind": "quote", "html": it["quote"]})
    return out, booked


def notice(a: dict, ep: dict) -> str:
    dep = a.get("deploy")
    if not dep:
        return f"<b>⚑ {escape(a['name'])}</b> {escape(a['text'].split(': ', 1)[-1].split(' until ')[0])}"
    held = any(h["awards"].get(dep["product"], 0) > 0.05 for h in ep["hours"])
    return (f"<b>⚑ {escape(a['name'])}</b> deploys {PRODUCT[dep['product']]} {hhmm(dep['start_min'])}–"
            f"{hhmm(dep['end_min'])}" + ("" if held else " <em>(it holds none)</em>"))


def chip(a: dict) -> str:
    dep = a.get("deploy")
    what = PRODUCT[dep["product"]] + " deployed" if dep else a["text"].split(": ", 1)[-1].split(" for ")[0]
    return f'<i class="nt">⚑ {escape(what)}</i>'


def captions(ep: dict, booked: dict[int, str]) -> list[dict]:
    """Each hour as it played, with only what was known at that minute: the hour's DA price, posted the day before,
    and the RT price of the last hour settled, never the hour's own; each reserve call from the minute it starts or
    ends; a reserve shortfall from the hour's start, its charge only in the grade."""
    realized = {r["h"]: r for s in ep["steps"] if s["tool"] == "advance" for r in s["output"].get("realized", [])}
    dur = next(s["output"]["as_rules"]["duration_h"] for s in ep["steps"] if s["tool"] == "get_situation")
    spans: dict[str, list[list[int]]] = {}
    for n in ep["notices"]:
        if dep := n.get("deploy"):
            a, b = dep["start_min"], min(dep["end_min"], dep["start_min"] + round(60 * dur.get(dep["product"], 1)))
            xs = spans.setdefault(dep["product"], [])
            if xs and a <= xs[-1][1]:
                xs[-1][1] = max(xs[-1][1], b)
            else:
                xs.append([a, b])
    e_mwh, out = ep["task"]["site"]["bess"]["e_mwh"], []
    hot = lambda p: " hot" if p > 200 else ""  # noqa: E731
    for x in ep["hours"]:
        h, m0 = x["h"], x["h"] * 60
        last = ep["hours"][h - 1]["rt"] if h else None
        head = [f'<span class="w">{h:02d}:00–{h + 1:02d}:00</span> '
                f'<span class="p{hot(x["da"])}">DA ${x["da"]:,.0f}</span>',
                *([f'<span class="p{hot(last)}">RT ${last:,.0f} last hour</span>'] if h else [])]
        aw = {k: v for k, v in x["awards"].items() if v > 0.05}
        tail = [f'<span class="bad">{approx(realized[h]["ftp_mw"])} MW of reserve short</span>'] \
            if x["ftp_usd"] > 0.5 else []
        batt = ""
        if abs(x["b_mw"]) > 0.05:
            batt = (f'<span class="{"c" if x["b_mw"] < 0 else "d"}">{"charging" if x["b_mw"] < 0 else "discharging"} '
                    f'{mw(x["b_mw"])} MW</span>' + (f" (booked {booked[h]})" if h in booked else ""))
        marks = [(m0, None)]
        for p, xs in spans.items():
            for a, b in xs:
                if p in aw and b > m0 and a < m0 + 60:
                    marks[0:1] = [(m0, (p, "on"))] if a <= m0 else [marks[0]]
                    marks += ([(a, (p, "on"))] if a > m0 else []) + ([(b, (p, "off"))] if b < m0 + 60 else [])
        for m, ev in sorted(marks, key=lambda z: z[0]):
            if ev and ev[1] == "on":
                body = [f'<span class="d">ERCOT calls its {PRODUCT[ev[0]]}: {mw(aw[ev[0]])} MW</span>'
                        + (f" from {hhmm(m)}" if m > m0 else "")]
                if batt:
                    body += [batt, f"net discharging {approx(aw[ev[0]] + x['b_mw'])} MW"]
            elif ev:
                body = [f"the {PRODUCT[ev[0]]} call ends at {hhmm(m)}", f"holding {PRODUCT[ev[0]]} {mw(aw[ev[0]])} MW"]
            elif batt:
                pv = min(-x["b_mw"], max(0.0, x["pv_mw"] - x["curtailed_mw"])) if x["b_mw"] < 0 else 0
                body = [batt.replace("</span>", f"</span>, {approx(pv)} from the panels", 1) if pv > 0.5 else batt]
            elif x["soc_mwh"] >= e_mwh - 0.5 and not aw:
                body = [f"battery full at {x['soc_mwh']:.0f} MWh", f"the panels export {approx(x['export_mw'])} MW"]
            elif aw:
                body = ["holding " + " + ".join(f"{PRODUCT[k]} {mw(v)} MW" for k, v in aw.items()) + " in reserve"]
            else:
                body = ["idle"]
            segs = head + body + tail
            out.append({"min": m, "html": " ".join(f'<span class="hs">{seg}{" ·" if i < len(segs) - 1 else ""}</span>'
                                                   for i, seg in enumerate(segs))})
    return out


def watch_hours(watches: list[dict]) -> list[float]:
    """Each watch on the replay clock: the day runs 0..24 and the ten hours before it -2..0, as the viewer plays
    them."""
    day = watches[-1]["time"][:10]
    out = []
    for w in watches:
        m = int(w["time"][11:13]) * 60 + int(w["time"][14:16]) - (0 if w["time"][:10] == day else 1440)
        out.append(m / 60 if m >= 0 else -2 + (m + 600) / 300)
    return out


def storyboard(ep: dict, fps: int) -> tuple[dict, list[dict]]:
    """What the overlay shows and when: a watch the replay holds opens with its calls paced one by one and stays open
    until the next one opens; the watches the replay runs through land as one line each when the clock passes them."""
    base = ep["model"].split("/")[-1]
    g = re.match(r"gpt-([\d.]+)-?(.*)$", base)
    name = f"GPT-{g[1]}" + (" " + g[2].replace("-", " ").title() if g[2] else "") if g else base
    items, booked = watch_items(ep, name.split(" ")[-1])
    wt = watch_hours(ep["watches"])
    held = {next(i for i, x in enumerate(wt) if abs(x - b[1]) < 1e-6) for b in BEATS if b[0] == "hold"}
    groups, beats, s0 = [], [], 0.0
    for kind, t0, t1, dur, shot, sun in BEATS:
        if kind == "hold":
            w = next(i for i, x in enumerate(wt) if abs(x - t0) < 1e-6)
            s = s0 + 0.2
            for it in items[w]:
                if it.get("tool") == "advance":
                    it["at"] = max(s0 + dur - 0.9, s + 0.45)
                    it["res"] = it["at"] + 0.35
                    continue
                it["at"] = s
                it["res"] = s + WAIT.get(it.get("tool"), 0)
                if it["kind"] == "notice":
                    s += 0.35
                elif it["kind"] == "call":
                    s += PACE[it["tool"]] + (0.16 * len(it["lines"]) if it["tool"] == "check_schedule" else 0)
                    s += (0.9 if it["tool"] == "check_schedule" else 0.5) if it["cls"] == "no" else 0
            for x in groups:
                x["close"] = s0 if x["close"] is None else x["close"]
            groups.append({"watch": w, "open": s0 + 0.05, "close": None, "items": items[w]})
        else:
            if kind == "end":
                for x in groups:
                    x["close"] = s0 if x["close"] is None else x["close"]
            due = [w for w, x in enumerate(wt) if x < t1 and w not in held and all(g["watch"] != w for g in groups)]
            for k, w in enumerate(due):
                at = max(s0 + 0.15 + max(0.0, (wt[w] - t0) / (t1 - t0)) * dur, s0 + 0.15 + 0.3 * k)
                for it in items[w]:
                    it["at"] = it["res"] = at
                groups.append({"watch": w, "open": at, "close": at, "items": items[w]})
        beats.append((kind, t0, t1, dur, shot, sun, s0))
        s0 += dur
    rows, books = [], []
    for g in sorted(groups, key=lambda g: g["open"]):
        books += [{**it["book"], "at": it["res"]} for it in g["items"] if "book" in it]
        rows.append({"time": ep["watches"][g["watch"]]["time"].split(" ")[1], "open": g["open"], "close": g["close"],
                     "label": "" if g["watch"] else "the day before",
                     "chips": " ".join(it["chip"] for it in g["items"] if it.get("chip")),
                     "items": [{k: it[k] for k in ("kind", "html", "at", "res", "result", "cls", "keep") if k in it}
                               for it in g["items"]]})
    d, bess = date.fromisoformat(ep["task"]["date"]), ep["task"]["site"]["bess"]
    day = lambda x: f"{x:%a} {x.day} {x:%b %Y}"  # noqa: E731
    times = [w["time"].split(" ")[1] for w in ep["watches"]]
    end = ep["soc_path"][-1]
    hero = {"model": escape(name), "total": sum(1 for s in ep["steps"] if s["tool"] != "grid_notice"), "groups": rows,
            "books": books, "hours": captions(ep, booked), "watchT": wt, "watchTime": times, "day": day(d),
            "dayBefore": day(d - timedelta(1)),
            "preLine": f"The day-ahead book for {d:%a} {d.day} {d:%b} is due at {times[0]}",
            "endLine": f"day over · {end:.0f} MWh at midnight, the {bess['s_end_min_mwh']:.0f} MWh it must end on",
            "endSoc": end, "grade": grade(ep, name), "gradeAt": beats[-1][6] + 0.25}
    frames = []
    for kind, t0, t1, dur, shot, sun, s0 in beats:
        n = round(dur * fps)
        frames += [{"s": round(s0 + k / fps, 4), "t": round(t0 if kind == "hold" else t0 + (t1 - t0) * k / (n - 1), 5),
                    "mode": kind, "shot": shot, "sun": sun, "dt": 0 if kind == "hold" else 1 / fps, "cut": k == 0}
                   for k in range(n)]
    return hero, frames


def grade(ep: dict, name: str) -> str:
    ref, p = ep["references"], ep["profit_usd"]
    pi, pa, ph, ftp = ref["p_idle"], ref["p_anchor"], ref["p_hind"], ep["cash"]["ftp"]
    rows = ((name + (f", after {money(ftp)} failure to provide" if ftp > 0.5 else ""), p, "#0b9fc6"),
            ("Rolling anchor (MILP, same information)", pa, "#7a868e"),
            ("Hindsight optimum", ph, "#b9c0c5"), ("Solar alone, battery idle", pi, "#d9dddf"))
    bars = "".join(f'<div class="gr"><span>{escape(label)}</span><b>{money(v)}</b></div><div class="bar">'
                   f'<i style="width:{v / ph * 100:.1f}%;background:{col}"></i></div>' for label, v, col in rows)
    return (f'<div class="t"><b>Day over · graded</b><span><small>reward</small>{ep["reward"]:.2f}</span></div>'
            f'<div class="sub"><b class="good">{money(p - pa, sign=True)}</b> against the rolling anchor · hindsight '
            f'capture C {(p - pi) / (ph - pi):.3f} (the anchor’s {(pa - pi) / (ph - pi):.3f})</div>{bars}')


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def film(space: Path, episode: str, hero: dict, frames: list[dict], out: Path, size: tuple[int, int],
         scale: float) -> None:
    rec = module("record", "scripts/record.py")
    w, h = size
    css, js = (ROOT / "hub/hero/overlay.css").read_text(), (ROOT / "hub/hero/overlay.js").read_text()
    with rec.serve(space) as port, tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(None), Path(profile), w, h), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale,
                          mobile=False)
                page.call("Runtime.enable")
                page.call("Page.navigate", url=f"http://127.0.0.1:{port}/index.html?record=1&t=0&reduced=1&episode={episode}")
                page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.gridsim ? r() : "
                        "Date.now() - s > 90000 ? j('timeout') : setTimeout(f, 50); f(); })")
                page.js("gridsim.ready.then(() => document.fonts.ready).then(() => true)")
                page.js(f"document.head.insertAdjacentHTML('beforeend', {json.dumps(f'<style>{css}</style>')})")
                page.js(f"window.HERO = {json.dumps(hero)}; true")
                page.js(js)
                page.js(SUN)
                page.js("gridsim.stage.resize(); true")
                last = None
                for i, f in enumerate(frames):
                    page.js(f"gridsim.stage.force = {json.dumps(f['shot'])}; window.sunT = {f['sun']}; "
                            f"hero.render({f['s']}, {f['t']}, {json.dumps(f['mode'])}); true")
                    key = (f["shot"], f["sun"], f["mode"] == "hold" and f["t"])
                    if f["cut"] or key != last:
                        for _ in range(3):
                            page.js(f"gridsim.time({f['t']}, {{dt: 0}})")
                        last = key
                    page.js(f"gridsim.time({f['t']}, {{dt: {f['dt']}}})")
                    png = page.call("Page.captureScreenshot", format="png")["data"]
                    (out / f"f{i:05d}.png").write_bytes(base64.b64decode(png))
        finally:
            proc.terminate()
            proc.wait()


def held(frames: Path, start: int, n: int, w: int, h: int, hold: int) -> bytes:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-start_number", str(start), "-i", str(frames / "f%05d.png"),
                          "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    seq = np.frombuffer(raw, np.uint8).reshape(n, h, w, 3).copy()
    for k in range(1, n):
        move = np.abs(seq[k].astype(np.int16) - seq[k - 1]).max(axis=2) > hold
        seq[k][~move] = seq[k - 1][~move]
    return seq.tobytes()


def segment(raw: bytes, out: Path, w: int, h: int, fps: int) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r",
                    str(fps), "-i", "-", "-filter_complex",
                    "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=2:"
                    "diff_mode=rectangle", str(out)], input=raw, check=True)


def sub_blocks(b: bytes, i: int) -> int:
    while b[i]:
        i += b[i] + 1
    return i + 1


def frames_of(path: Path) -> list[bytes]:
    b = path.read_bytes()
    bits = b[10] & 7
    table = b[13:13 + 3 * 2 ** (bits + 1)]
    i, gce, out = 13 + len(table), b"", []
    while b[i] != 0x3B:
        if b[i] == 0x21:
            j = sub_blocks(b, i + 2)
            gce = b[i:j] if b[i + 1] == 0xF9 else gce
            i = j
        else:
            desc = bytearray(b[i:i + 10])
            assert not desc[9] & 0x80
            desc[9] |= 0x80 | bits
            j = sub_blocks(b, i + 11)
            out.append(gce + desc + table + b[i + 10:j])
            i, gce = j, b""
    return out


def join(parts: list[Path], out: Path, w: int, h: int) -> int:
    frames = [f for p in parts for f in frames_of(p)]
    head = b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + bytes([0x70, 0, 0])
    out.write_bytes(head + b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00" + b"".join(frames) + b"\x3b")
    return len(frames)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--space", type=Path, required=True, help="A built viewer Space with the v3 replay.")
    ap.add_argument("--episode", default=EPISODE)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--css-size", default="960x540", help="The viewer's CSS size; the GIF is this times --scale.")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--hold", type=int, default=3)
    ap.add_argument("--frames", type=Path, help="Keep the PNG frames in this folder.")
    args = ap.parse_args()
    cw, ch = (int(v) for v in args.css_size.split("x"))
    w, h = round(cw * args.scale), round(ch * args.scale)
    hero, frames = storyboard(json.loads((args.space / args.episode).read_text()), args.fps)
    with tempfile.TemporaryDirectory() as tmp:
        shots = args.frames or Path(tmp)
        shots.mkdir(parents=True, exist_ok=True)
        film(args.space, args.episode, hero, frames, shots, (cw, ch), args.scale)
        parts, start = [], 0
        for k, beat in enumerate(BEATS):
            n = round(beat[3] * args.fps)
            parts.append(Path(tmp) / f"beat{k}.gif")
            segment(held(shots, start, n, w, h, args.hold), parts[-1], w, h, args.fps)
            start += n
        args.out.parent.mkdir(parents=True, exist_ok=True)
        n = join(parts, args.out, w, h)
    print(f"{args.out}: {w}x{h}, {n} frames at {args.fps} fps, {n / args.fps:.1f} s, "
          f"{args.out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
