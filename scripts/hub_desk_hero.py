"""The desk hero GIF: one desk episode filmed as the desk's own screen, node prices as they post, the battery's charge
and dispatch and the shadow statement as intervals settle, beside the agent's tool calls at each wake-up with the
results the run recorded, then the settled grade. The clock stands still while the agent works; nothing shows early.

    .venv/bin/python scripts/hub_desk_hero.py --episode EPISODE.json[.gz] --out build/hub/hero/gridsim-desk-hero.gif
    .venv/bin/python scripts/hub_desk_hero.py --results results/desk-v2 --out ...   # the best-looking Sol episode
"""

import argparse
import base64
import gzip
import importlib.util
import json
import re
import subprocess
import tempfile
import time
from datetime import date, timedelta
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "hub/desk-hero"
READS = {"get_prices": "prices", "get_forecasts": "forecasts", "get_grid_conditions": "grid",
         "get_asset_status": "asset", "get_position": "position"}
ACTS = {"submit_dam_offers": "DAM offers", "submit_rt_offers": "RT offers", "update_cop": "COP"}
TICKED = (*ACTS, "set_reminder", "check_submission")
REASONS = {"start": "start", "dam_results": "DAM results", "adjustment_open": "adjustment period opens",
           "checkpoint": "shift checkpoint", "reminder": "its reminder", "notice": "ERCOT notice", "nws": "NWS alert",
           "outage": "outage", "deployment": "deployment", "dam_morning": "DAM morning"}
MARKETS = {"dam": "DAM SPP", "rt": "RT SPP, 15-min", "sced": "SCED LMP, 5-min", "as_dam": "DAM MCPCs",
           "as_rt": "RT MCPCs", "asdc": "AS demand curves"}
KINDS = {"load": "ERCOT load forecast", "wind": "ERCOT wind forecast", "solar": "ERCOT solar forecast",
         "net_load": "ERCOT net-load forecast", "outages": "ERCOT outage capacity", "pv": "PV forecast (modelled)",
         "as_price": "AS price view (modelled)"}
MODELLED = {"end_soc_shortfall": "the end-of-day SoC charge", "warranty_overage": "warranty overage",
            "capacity_short": "capacity-short charges", "pv_energy": "PV energy"}
PACE = {"read": 0.3, "act": 0.72, "event": 0.4}
LAG = {"read": 0.13, "act": 0.32, "event": 0.0}
READS_MAX, PLAY_S_PER_H, PLAY_MIN, PLAY_MAX, QUOTE_S, END_S, LONGEST = 1.8, 0.3, 0.8, 6.5, 2.7, 4.6, 39.0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--episode", type=Path, help="A gridsim.desk.episode/v1 JSON, plain or gzipped.")
    ap.add_argument("--results", type=Path, help="A results/desk-v<N> folder: rank its Sol episodes and film the best.")
    ap.add_argument("--series", type=Path, help="The task's series JSON (for the operator's disclosed SoC at the end).")
    ap.add_argument("--grades", type=Path, help="The version's grades.jsonl.gz (desk_report.py): the end card shows "
                                                "its regraded P, references and capture; --results reads its own.")
    ap.add_argument("--hold", help="Comma-separated turn numbers to hold, overriding the automatic choice.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--css-size", default="960x540", help="The page's CSS size; the GIF is this times --scale.")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--hold-levels", type=int, default=3, help="Pixels moving less than this keep the last value.")
    ap.add_argument("--frames", type=Path, help="Keep the PNG frames in this folder.")
    ap.add_argument("--stills", help="Comma-separated GIF seconds: write those frames as PNGs beside --out, no GIF.")
    args = ap.parse_args()
    path = args.episode or best(args.results)
    ep = regraded(read(path), path, args.grades or (args.results / "grades.jsonl.gz" if args.results else None))
    series = read(args.series) if args.series else None
    holds = [int(x) for x in args.hold.split(",")] if args.hold else None
    cw, ch = (int(v) for v in args.css_size.split("x"))
    w, h = round(cw * args.scale), round(ch * args.scale)
    hero, frames, beats = storyboard(ep, series, holds, args.fps)
    print(f"{path.name}: holds turns {hero['held']}, {len(frames)} frames, {len(frames) / args.fps:.1f} s, settled P&L "
          f"{'recomputed and checked' if hero['pnl']['computed'] else 'as the env showed it'}")
    if args.stills:
        want = [float(x) for x in args.stills.split(",")]
        pick_ = [min(frames, key=lambda f, s=s: abs(f["s"] - s)) for s in want]
        args.out.mkdir(parents=True, exist_ok=True)
        film(hero, frames[:frames.index(pick_[-1]) + 1], args.out, (cw, ch), args.scale, keep={f["s"] for f in pick_})
        return
    hh = module("hub_hero", "scripts/hub_hero.py")
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory() as tmp:
        shots = args.frames or Path(tmp)
        shots.mkdir(parents=True, exist_ok=True)
        film(hero, frames, shots, (cw, ch), args.scale)
        parts, start = [], 0
        for k, n in enumerate(beats):
            parts.append(Path(tmp) / f"beat{k}.gif")
            hh.segment(hh.held(shots, start, n, w, h, args.hold_levels), parts[-1], w, h, args.fps)
            start += n
        args.out.parent.mkdir(parents=True, exist_ok=True)
        n = hh.join(parts, args.out, w, h)
    print(f"{args.out}: {w}x{h}, {n} frames at {args.fps} fps, {n / args.fps:.1f} s, "
          f"{args.out.stat().st_size / 1e6:.2f} MB, rendered in {time.monotonic() - t0:.0f} s")


def regraded(ep: dict, path: Path, grades: Path | None) -> dict:
    """The episode with the grade its version's report settled on (frozen references, the reward floor), as every
    published table has it; the run's own grade only when no report is given."""
    if grades is None:
        return ep
    with gzip.open(grades, "rt") as f:
        row = next(g for g in map(json.loads, filter(str.strip, f))
                   if g["task_id"] == ep["task_id"] and Path(g["episode"]).name == path.name)
    keys = ("p", "p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual", "capture",
            "reward", "valid")
    return {**ep, "grade": {**ep["grade"], **{k: row[k] for k in keys}}}


def best(results: Path) -> Path:
    ranked = sorted(((score(regraded(read(p), p, results / "grades.jsonl.gz")), p)
                     for p in sorted((results / "episodes/sol").glob("*.json*"))),
                    key=lambda x: -x[0][0])
    for (s, why), p in ranked[:5]:
        print(f"{s:6.2f}  {p.name}  {why}")
    if not ranked:
        raise SystemExit(f"no Sol episodes under {results}/episodes/sol")
    return ranked[0][1]


def score(ep: dict) -> tuple[float, str]:
    g, turns = ep["grade"], ep["turns"]
    if not g.get("valid") or g["p"] <= 0:
        return -9.0, "invalid or loses money"
    subs = [s for s in ep.get("submissions", []) if s["accepted"]]
    dam = any(s["tool"] == "submit_dam_offers" for s in subs)
    rt = sum(s["tool"] == "submit_rt_offers" for s in subs)
    acted = {s["t"] for s in subs}
    woke = {"notice", "nws", "outage", "deployment"}
    events = sum(1 for t in turns if t["t"] in acted and set(reasons(ep, t)) & woke)
    lmp = max(x for d in ep["dates"] for x in ep["rt"][d]["lmp"])
    words = max((len(t.get("text") or "") for t in turns), default=0)
    parts = {"capture": 2 * max(-0.5, min(1.0, g.get("capture") or 0)), "beats anchor": float(g["p"] > g["p_anchor"]),
             "beats operator": float(g["p"] > (g.get("p_operator_replay") or 1e18)), "DAM bid": 0.6 * dam,
             "RT re-bids": min(1.0, rt / 4), "event re-plans": min(1.4, 0.7 * events), "spike": min(1.0, lmp / 1000),
             "quote": 0.3 * (words > 80)}
    return sum(parts.values()), ", ".join(f"{k} {v:.2f}" for k, v in parts.items() if v)


def read(path: Path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def storyboard(ep: dict, series: dict | None, holds: list[int] | None, fps: int) -> tuple[dict, list[dict], list[int]]:
    """The page's data and every frame: the held turns' calls paced one by one with the clock stopped, the other turns
    landing as one line each when the clock passes them, then the grade; paced faster until it lasts at most LONGEST
    seconds."""
    for f in (1.0, 0.9, 0.8, 0.7, 0.6):
        hero, frames, beats = board(ep, series, holds, fps, f)
        if len(frames) / fps <= LONGEST:
            break
    return hero, frames, beats


def board(ep: dict, series: dict | None, holds: list[int] | None, fps: int, f: float):
    d0, nd = date.fromisoformat(ep["dates"][0]), len(ep["dates"])
    turns = ep["turns"]
    holds = sorted(holds if holds is not None else pick(ep))
    k = min(0.6, 0.4 * nd)
    t_start, t_end = min(w["t"] for w in ep["wakes"]), 1440 * nd
    comp = lambda t: t * k if t < 0 else t  # noqa: E731
    groups, beats, frames, s0 = [], [], [], 0.0
    plan = []
    for i, n in enumerate(holds):
        plan.append(("play", turns[holds[i - 1]]["t"] if i else t_start, turns[n]["t"]))
        plan.append(("hold", n))
    plan.append(("play", turns[holds[-1]]["t"], t_end))
    plan.append(("end",))
    plan = [p for p in plan if p[0] != "play" or p[2] > p[1]]
    items = {i: turn_items(ep, tr, d0) for i, tr in enumerate(turns)}
    held = set(holds)
    for step in plan:
        if step[0] == "hold":
            n = step[1]
            s, its = s0 + 0.25, items[n]
            reads = sum(1 for it in its["items"] if it["pace"] == "read")
            per = min(PACE["read"], READS_MAX / max(1, reads)) * f
            for it in its["items"]:
                it["at"], it["res"] = s, s + LAG[it["pace"]] * f
                s += (per if it["pace"] == "read" else PACE[it["pace"]] * f) + 0.35 * f * (it.get("cls") == "no")
            if its["quote"]:
                its["quote_at"] = s + 0.2
                s += QUOTE_S
            dur = max(3.0, s - s0 + 0.45)
            for g in groups:
                g["close"] = s0 if g["close"] is None else g["close"]
            groups.append({"turn": n, "open": s0 + 0.05, "close": None, **its})
            beats.append(("hold", turns[n]["t"], turns[n]["t"], dur, s0))
        elif step[0] == "play":
            a, b = step[1], step[2]
            dur = min(PLAY_MAX, max(PLAY_MIN, PLAY_S_PER_H * f * (comp(b) - comp(a)) / 60))
            for i, tr in enumerate(turns):
                if a <= tr["t"] < b and i not in held and not any(g["turn"] == i for g in groups):
                    at = s0 + dur * (comp(tr["t"]) - comp(a)) / (comp(b) - comp(a))
                    for it in items[i]["items"]:
                        it["at"] = it["res"] = at
                    groups.append({"turn": i, "open": at, "close": at, **items[i]})
            beats.append(("play", a, b, dur, s0))
        else:
            for g in groups:
                g["close"] = s0 if g["close"] is None else g["close"]
            dur = END_S + 1.4 * bool(series)
            beats.append(("end", t_end, t_end, dur, s0))
        s0 += dur
    hero = page_data(ep, series, d0, k, t_start, t_end, groups, holds)
    hero["gradeAt"] = beats[-1][4] + (1.75 if hero["opSoc"] else 0.35)
    counts = []
    for kind, a, b, dur, s in beats:
        n = round(dur * fps)
        counts.append(n)
        for j in range(n):
            if kind == "play":
                c = comp(a) + (comp(b) - comp(a)) * j / max(1, n - 1)
                t = c / k if c < 0 else c
            else:
                t = a
            frames.append({"s": round(s + j / fps, 4), "t": round(t, 3), "mode": kind, "cut": j == 0})
    return hero, frames, counts


def pick(ep: dict) -> list[int]:
    """At most four turns to hold: the turn that bids the DAM (else the first), the DAM results when they award
    anything, the adjustment period opening, and the operating-day turns that act on the most: submissions, an ERCOT
    or weather event, price spikes; two of them when there is room."""
    turns, subs = ep["turns"], [s for s in ep.get("submissions", []) if s["accepted"]]
    acted = {}
    for s in subs:
        acted[s["t"]] = acted.get(s["t"], 0) + 1
    first = lambda r: next((i for i, t in enumerate(turns) if r in reasons(ep, t)), None)  # noqa: E731
    dam_bid = next((i for i, t in enumerate(turns) if any(s["tool"] == "submit_dam_offers" and s["t"] == t["t"]
                                                          for s in subs)), 0)
    awarded = any(abs(x or 0) > 0.05 for d in ep["dates"] for x in ep["dam"][d]["award_mw"])
    early = list(dict.fromkeys(x for x in (dam_bid, first("dam_results") if awarded else None, first("adjustment_open"))
                               if x is not None))
    lmp = [x for d in ep["dates"] for x in ep["rt"][d]["lmp"]]
    cands = []
    for i, t in enumerate(turns):
        if t["t"] < 0:
            continue
        near = [lmp[j] for j in range(max(0, t["t"] // 5 - 12), min(len(lmp), t["t"] // 5))] or [0]
        ev = set(reasons(ep, t)) & {"notice", "nws", "outage", "deployment"}
        cands.append((2.0 * bool(acted.get(t["t"])) + 0.4 * min(3, acted.get(t["t"], 0)) + 1.5 * bool(ev)
                      + min(1.5, max(near) / 500) + 0.4 * (len(t.get("text") or "") > 80), i))
    late = []
    for _, i in sorted(cands, reverse=True):
        if len(late) < 2 and all(abs(turns[i]["t"] - turns[j]["t"]) >= 60 for j in late):
            late.append(i)
    return sorted(early[:4 - len(late)] + late)


def reasons(ep: dict, turn: dict) -> list[str]:
    w = turn.get("wake") or {}
    return w.get("reasons") or next((x["reasons"] for x in ep["wakes"] if x.get("turn") == turn["turn"]), [])


def turn_items(ep: dict, turn: dict, d0: date) -> dict:
    """A turn as the panel shows it: the events that woke the agent, each call with its arguments and recorded result,
    the chips a closed turn keeps, and the agent's words."""
    w = turn.get("wake") or {}
    rs = reasons(ep, turn)
    items = [event(ev) for ev in w.get("events") or [] if ev.get("kind") not in ("druc", "dam_close")]
    items = [x for x in items if x]
    for c in turn["calls"]:
        items.append(call(c, ep))
    chips = [f'<i class="nt">⚑ {escape(x["chip"])}</i>' for x in items if x["kind"] == "event" and x.get("chip")]
    chips += merged(x for x in items if x["kind"] == "call")
    text = clean(turn.get("text") or "")
    return {"time": label_time(turn, d0), "reasons": " · ".join(REASONS.get(r, r) for r in rs),
            "chips": " ".join(chips), "items": items, "quote": excerpt(text) if text else None}


def label_time(turn: dict, d0: date) -> str:
    t = turn["t"]
    return f"{(t % 1440) // 60:02d}:{t % 60:02d}"


def event(ev: dict) -> dict | None:
    kind, text = ev.get("kind"), ev.get("text") or ""
    at = (ev.get("t") or "")[-5:]
    if kind == "dam_results":
        m = re.search(r"awards in (\d+) of 24 hours, sold ([\d.,]+) MWh, bought ([\d.,]+) MWh, net value (\$?[−\-\d,]+)"
                      r"; DAM SPP at your node ([−\-\d.]+)\.\.([−\-\d.]+)", text)
        if m:
            won = "no awards" if m[1] == "0" else (f"awards in {m[1]} hours: sold {m[2]} MWh, bought {m[3]} MWh, "
                                                  f"{m[4].replace('-', '−')}")
            body = f"DAM results: {won} · node DAM {price(float(m[5]))}–{price(float(m[6]))}"
        else:
            body = text
        return {"kind": "event", "pace": "event", "html": f"<b>⚑ {at}</b> {escape(body)}", "chip": "DAM results"}
    if kind == "notice":
        return {"kind": "event", "pace": "event", "html": f"<b>⚑ ERCOT {at}</b> {escape(cut(text, 118))}",
                "chip": "ERCOT notice"}
    if kind in ("weather", "nws"):
        what = ev.get("event") or text
        return {"kind": "event", "pace": "event", "html": f"<b>⚑ NWS {at}</b> {escape(cut(text, 100))}",
                "chip": cut(what, 28)}
    if kind in ("outage", "deployment", "unit_event"):
        return {"kind": "event", "pace": "event", "html": f"<b>⚑ {at}</b> {escape(cut(text, 118))}", "chip": kind}
    if kind == "reminder":
        return {"kind": "event", "pace": "event", "cls": "rem",
                "html": f"<b>⏰ {at}</b> its own reminder: “{escape(cut(text, 96))}”"}
    if kind == "checkpoint":
        m = re.search(r"SoC ([\d.]+) MWh.*shadow P&L ([−\-\d,]+) \$", text)
        body = f"SoC {m[1]} MWh · settled so far {money(float(m[2].replace(',', '').replace('−', '-')))}" if m else text
        return {"kind": "event", "pace": "event", "cls": "ck", "html": f"<b>{at}</b> shift checkpoint · {escape(body)}"}
    if kind == "adjustment_open":
        return {"kind": "event", "pace": "event", "cls": "ck",
                "html": f"<b>{at}</b> adjustment period open: RT offers and COP updates accepted"}
    if kind in ("dam_morning", "start"):
        return None
    return {"kind": "event", "pace": "event", "cls": "ck", "html": f"<b>{at}</b> {escape(cut(text, 110))}"}


def call(c: dict, ep: dict) -> dict:
    tool, a, r = c["tool"], c.get("args") or {}, c.get("result") or {}
    err = r.get("error") if isinstance(r, dict) else None
    small, lines, res, cls = describe(tool, a, r, ep)
    if err:
        res, cls = f"✗ {escape(cut(err, 120))}", "no"
    pace = "read" if tool in READS else "act"
    tick = {"ok": " ✓", "no": " ✗"}.get(cls, "") if tool in TICKED else (" ✗" if cls == "no" else "")
    chip = (READS.get(tool) or chip_of(tool, a, r)) + tick
    head = f'<div class="tool">{tool}{f"<small>{small}</small>" if small else ""}</div>'
    body = "".join(f'<div class="a">{x}</div>' for x in lines)
    return {"kind": "call", "pace": pace, "tool": tool, "html": head + body + '<div class="r"></div>', "result": res,
            "cls": cls, "chip": chip, "keep": pace == "act"}


def describe(tool: str, a: dict, r: dict, ep: dict) -> tuple[str, list[str], str, str]:
    if tool == "get_prices":
        what = MARKETS.get(a.get("market", "rt"), a.get("market", ""))
        small = f"{what} · {a.get('point', 'node')}"
        vals = [v for v in r.get("values") or [] if v is not None]
        if not vals:
            return small, [], escape(r.get("note", "nothing posted yet")), "dim"
        if r.get("market") == "dam":
            peak = max(range(len(vals)), key=lambda i: vals[i])
            return small, [], f"HE01–HE24 {price(min(vals))} to {price(max(vals))}, peak HE{peak + 1:02d}", "ok"
        span = f"{(r.get('start') or '')[-5:]}–{(r.get('end') or '')[-5:]}"
        return small, [], f"{span}: {price(min(vals))} to {price(max(vals))}, last {price(vals[-1])}", "ok"
    if tool == "get_forecasts":
        kind = a.get("kind", "price")
        if kind == "price":
            small = f"{'DAM' if a.get('market', 'dam') == 'dam' else 'RT'} price · modelled desk forecast"
            p50 = [v for v in r.get("p50") or [] if v is not None]
            if not p50:
                return small, [], "", "ok"
            i = max(range(len(p50)), key=lambda j: p50[j])
            slot = f"HE{i + 1:02d}" if r.get("step") == "1h" else f"{(i * 15) // 60:02d}:{(i * 15) % 60:02d}"
            return small, [], (f"issued {(r.get('issued_at') or '')[-5:]}: P50 {price(min(p50))} to {price(max(p50))}, "
                               f"peak {slot} (P10–P90 {price(r['p10'][i])}–{price(r['p90'][i])})"), "ok"
        if kind == "weather":
            al = r.get("alerts") or []
            return "NWS alerts", [], ", ".join(escape(x.get("event") or "") for x in al[:3]) or "none in force", "ok"
        vals = [v for v in r.get("values") or [] if v is not None]
        small = KINDS.get(kind, kind)
        if not vals:
            return small, [], "", "ok"
        i = max(range(len(vals)), key=lambda j: vals[j] if vals[j] is not None else -1e18)
        return small, [], f"peak {gw(max(vals))} at HE{(r.get('values') or []).index(max(vals)) + 1:02d}", "ok"
    if tool == "get_grid_conditions":
        if r.get("note"):
            return "", [], escape(r["note"]), "dim"
        bits = []
        if p := r.get("prc_mw"):
            bits.append(f"PRC {gw(p['last'])}" + (" (modelled proxy)" if "proxy" in str(p.get("kind")) else ""))
        if lam := r.get("lambda"):
            bits.append(f"λ {price(lam['last'])}")
        if ld := r.get("load_mw"):
            bits.append(f"load {gw(ld['last'])}")
        if r.get("eea_level"):
            bits.append(f"<b>{escape(str(r['eea_level']))}</b>")
        return "", [], " · ".join(bits), "ok"
    if tool == "get_asset_status":
        e_max = (r.get("nameplate") or {}).get("e_max_mwh") or ep["site"]["e_max_mwh"]
        out = f" · outage until {r['outage'].get('until') or '?'}" if r.get("outage") else ""
        return "", [], f"SoC {r.get('soc_mwh', 0):.1f} of {e_max:.0f} MWh · {r.get('status', 'ON')}{out}", "ok"
    if tool == "get_position":
        bits = []
        dam = r.get("dam") or {}
        if "sold_mwh" in dam:
            bits.append("DAM: no awards" if not dam["sold_mwh"] and not dam["bought_mwh"] else
                        f"DAM sold {dam['sold_mwh']:,.0f} MWh, {money(dam.get('value_usd', 0))}")
        elif dam.get("status"):
            bits.append(f"DAM {dam['status']}")
        rt = r.get("rt") or {}
        if rt.get("discharged_mwh") is not None:
            bits.append(f"RT {rt['discharged_mwh']:,.1f} MWh out, {rt['charged_mwh']:,.1f} in")
        if st := r.get("shadow_statement"):
            bits.append(f"settled {money(st['total'])}")
        return "", [], " · ".join(bits), "ok"
    if tool in ("submit_dam_offers", "submit_rt_offers"):
        cs = a.get("curves") or []
        lines = [f"{escape(str(c.get('hours', '')))}: {curve(c, ep)}" for c in cs[:2] if isinstance(c, dict)]
        if len(cs) > 2:
            lines[-1] += f" <span class='m'>+{len(cs) - 2} more</span>"
        if a.get("as_offers"):
            lines.append(f"AS offers: {len(a['as_offers'])}")
        return f"day {escape(str(a.get('day', 'D0')))}", lines, accepted(r), "ok" if r.get("accepted_hours") else "no"
    if tool == "update_cop":
        rows = a.get("rows") or []
        lines = [f"{escape(str(x.get('hours', '')))}: {cop_row(x)}" for x in rows[:2] if isinstance(x, dict)]
        return "", lines, accepted(r), "ok" if r.get("accepted_hours") else "no"
    if tool == "check_submission":
        p = a.get("payload") or {}
        hrs = ", ".join(str(c.get("hours")) for c in (p.get("curves") or [])[:1] if isinstance(c, dict))
        small = f"dry run · {a.get('kind', 'dam').upper()}" + (f" {escape(hrs)}…" if hrs else "")
        if r.get("ok"):
            wc = r.get("would_clear_at_desk_p50")
            clears = sum(1 for x in wc or [] if not x.endswith(":0"))
            return small, [], "✓ valid" + (f" · would clear {clears} of 24 hours at the desk P50" if wc else ""), "ok"
        errs = r.get("errors") or r.get("rejected") or []
        first = errs[0] if errs else {}
        return small, [], f"✗ {escape(str(first.get('code', '')))} {escape(cut(str(first.get('text', '')), 90))}", "no"
    if tool == "optimize":
        cn = a.get("constraints") or {}
        bits = [f"risk {a.get('risk', 0.5)}"]
        bits += [f"end SoC {cn['end_soc_mwh']} MWh"] if "end_soc_mwh" in cn else []
        bits += [f"DAM {cn['dam_position']}"] if "dam_position" in cn else []
        view = "desk view" if a.get("price_view", "desk") == "desk" else "own price view"
        pr = r.get("projected") or {}
        exp = f" · expects {money(pr['expected'])} (modelled)" if pr.get("expected") is not None else ""
        n_dam, n_rt = len(r.get("dam_curves") or []), len(r.get("rt_curves") or [])
        return f"{view} · {' · '.join(bits)}", [], f"proposes {n_dam} DAM, {n_rt} RT curves + COP{exp}", "ok"
    if tool == "set_reminder":
        note = cut(str(a.get("note") or ""), 64)
        pend = f", {r['pending']} pending" if r.get("pending") else ""
        res = f"✓ set for {escape(str(r.get('at', ''))[-5:])}{pend}"
        return f"at {escape(str(a.get('at', '')))}", [f"“{escape(note)}”"] if note else [], res, "ok"
    return "", [], "", "ok"


def accepted(r: dict) -> str:
    acc, rej = r.get("accepted_hours"), r.get("rejected") or []
    out = f"✓ accepted {escape(str(acc))}" if acc else ""
    if rej:
        x = rej[0]
        hrs = str(x.get("hours", ""))
        hrs = hrs if len(hrs) < 16 else hrs.split(",")[0] + "…"
        why = f"{escape(str(x.get('code', '')))} {escape(cut(str(x.get('text', '')), 60))}"
        out += (" · " if out else "") + f'<span class="x">✗ {escape(hrs)} {why}</span>'
    return out


def curve(c: dict, ep: dict) -> str:
    """An ESR energy bid/offer curve in words: what it buys up to which price, what it sells from which price."""
    pts = sorted((float(q), float(p)) for q, p in c.get("points") or [] if q is not None and p is not None)
    if not pts and (c.get("offer") or c.get("bid")):
        return "offer and bid curves (pre-RTC+B)"
    buy = [(p, -q) for q, p in pts if q < -0.05]
    sell = [(p, q) for q, p in pts if q > 0.05]
    out = []
    if buy:
        hi = max(p for p, _ in buy)
        out.append(f"buys up to {max(q for _, q in buy):.0f} MW at ≤ {price(hi)}" if len({p for p, _ in buy}) == 1 else
                   f"buys {max(q for _, q in buy):.0f} MW below {price(min(p for p, _ in buy))}, less up to "
                   f"{price(hi)}")
    if sell:
        levels = sorted({p: max(q for pp, q in sell if pp == p) for p, _ in sell}.items())
        steps = [(p, q) for p, q in levels if q > 0.05]
        out.append("sells " + ", ".join(f"{q:.0f} MW ≥ {price(p)}" for p, q in steps[:2])
                   + (" …" if len(steps) > 2 else ""))
    return escape(" · ".join(out)) if out else "0 MW"


def cop_row(x: dict) -> str:
    bits = []
    if x.get("status"):
        bits.append(str(x["status"]))
    hb = x.get("hbsoc_mwh")
    if isinstance(hb, list) and hb:
        bits.append(f"HBSOC {hb[0]:g}→{hb[-1]:g} MWh")
    elif hb is not None:
        bits.append(f"HBSOC {hb:g} MWh")
    if x.get("min_soc_mwh") is not None or x.get("max_soc_mwh") is not None:
        bits.append(f"SoC {x.get('min_soc_mwh', '·')}–{x.get('max_soc_mwh', '·')} MWh")
    return escape(" · ".join(bits))


def chip_of(tool: str, a: dict, r: dict) -> str:
    if tool in ACTS:
        acc = r.get("accepted_hours") if isinstance(r, dict) else None
        return f"{ACTS[tool]} {acc}" if acc and len(str(acc)) <= 11 else ACTS[tool]
    if tool == "set_reminder":
        at = str((r or {}).get("at") or "")[-5:]
        return f"reminder {at}" if at else "reminder"
    if tool == "check_submission":
        return "check"
    return tool


def merged(items) -> list[str]:
    out, last, n = [], None, 0
    for it in items:
        key = (it["chip"], it["cls"] if it["tool"] in TICKED or it["cls"] == "no" else "")
        if key == last:
            n += 1
            continue
        if last:
            out.append(chip_html(*last, n))
        last, n = key, 1
    if last:
        out.append(chip_html(*last, n))
    return out


def chip_html(text: str, cls: str, n: int) -> str:
    return f'<i class="{cls}">{escape(text)}{f" ×{n}" if n > 1 else ""}</i>'


def page_data(ep: dict, series: dict | None, d0: date, k: float, t_start: int, t_end: int, groups: list[dict],
              holds: list[int]) -> dict:
    dates, nd = ep["dates"], len(ep["dates"])
    cat = lambda key, sub, n=None: [x for d in dates for x in ep[key][d][sub][:n]]  # noqa: E731
    soc = cat("rt", "soc_mwh", -1) + [ep["rt"][dates[-1]]["soc_mwh"][-1]]
    posted = []
    for j, d in enumerate(dates):
        md = date.fromisoformat(d).strftime("%m-%d")
        ev = next((e for e in ep["events"] if e.get("kind") == "dam_results" and md in e.get("text", "")), None)
        posted.append(stamp(ev["t"], d0) if ev else j * 1440 - 630)
    g = ep["grade"]
    card = (ep.get("site") or {}).get("card") or {}
    rows = [{"key": "model", "label": name(ep), "p": g["p"]}]
    if g.get("p_operator_replay") is not None:
        rows.append({"key": "op", "label": "The real operator's disclosed bids, through the same market",
                     "p": g["p_operator_replay"]})
    if g.get("p_operator_actual") is not None:
        rows.append({"key": "opa", "label": "The real operator, as it ran (disclosed awards and telemetry)",
                     "p": g["p_operator_actual"]})
    if (ep.get("policy") or {}).get("kind") != "anchor":
        rows.append({"key": "anchor", "label": "Anchor policy: the optimiser at every wake-up, same information",
                     "p": g["p_anchor"]})
    rows.append({"key": "hind", "label": "Hindsight optimum under the same rules", "p": g["p_hind"]})
    op_soc = None
    if series and series.get("operator"):
        try:
            op_soc = [x for d in dates for x in series["operator"]["sced"][d]["soc_mwh"]]
        except (KeyError, TypeError):
            op_soc = None
    statement = ep["statement"]
    modelled = [MODELLED.get(x, x.replace("_", " ")) for x in statement.get("modelled", [])
                if any(x in v["lines"] for v in statement["days"].values())]
    return {
        "model": name(ep), "site": " · ".join(x for x in (card.get("name"), card.get("region"), card.get("size")) if x),
        "d0": dates[0], "nd": nd, "k": k, "t0": t_start, "t1": t_end, "days": [day_label(d) for d in dates],
        "dayBefore": day_label((d0 - timedelta(1)).isoformat()), "eMax": ep["site"]["e_max_mwh"],
        "hsl": ep["site"]["hsl_mw"], "lsl": ep["site"]["lsl_mw"], "dam": cat("dam", "spp"),
        "award": cat("dam", "award_mw"), "posted": posted, "lmp": cat("rt", "lmp"), "bp": cat("rt", "base_point_mw"),
        "metered": cat("rt", "metered_mw"), "soc": soc, "opSoc": op_soc, "fc": forecasts(ep, d0),
        "pnl": pnl(ep, d0), "wakes": wakes(ep, holds),
        "total": sum(len(t["calls"]) for t in ep["turns"]), "turns": len(ep["turns"]), "held": holds,
        "groups": [{**{x: gp[x] for x in ("time", "reasons", "chips", "open", "close", "quote")},
                    "quoteAt": gp.get("quote_at"), "label": "" if gp["turn"] else "the day before",
                    "items": [{x: it[x] for x in ("kind", "html", "at", "res", "result", "cls", "keep") if x in it}
                              for it in gp["items"]]} for gp in groups],
        "grade": {"rows": rows, "reward": g["reward"], "capture": g.get("capture"),
                                                  "anchor": g["p_anchor"], "p": g["p"], "modelled": modelled},
    }


def wakes(ep: dict, holds: list[int]) -> list[dict]:
    done = {s["t"] for s in ep.get("submissions", []) if s["accepted"]}
    return [{"t": t["t"], "acted": t["t"] in done, "held": i in holds, "reasons": reasons(ep, t)}
            for i, t in enumerate(ep["turns"])]


def forecasts(ep: dict, d0: date) -> list[dict]:
    out = []
    for tr in ep["turns"]:
        for c in tr["calls"]:
            r = c.get("result") or {}
            if c["tool"] != "get_forecasts" or r.get("kind") != "price" or not r.get("p50"):
                continue
            j = (date.fromisoformat(r["date"]) - d0).days
            step = 60 if r.get("step") == "1h" else 15
            out.append({"t": tr["t"], "market": r["market"], "start": j * 1440, "step": step, "p50": r["p50"]})
    return out


def pnl(ep: dict, d0: date) -> dict:
    """The shadow statement as intervals settle (each 15-minute interval two minutes after it ends), from the
    episode's prices, awards and metered MW, checked against every statement the env showed the agent; when any check
    fails, only the env's own figures, each from the minute it was shown."""
    dates = ep["dates"]
    dam = [x for d in dates for x in ep["dam"][d]["spp"]]
    aw = [x or 0.0 for d in dates for x in ep["dam"][d]["award_mw"]]
    spp = [x for d in dates for x in ep["rt"][d]["spp"]]
    m5 = [x for d in dates for x in ep["rt"][d]["metered_mw"]]
    bp = [x for d in dates for x in ep["rt"][d]["base_point_mw"]]
    st = ep["statement"]["days"]
    dis = sum(v.get("discharged_mwh", 0.0) for v in st.values())
    deg = -sum(v["lines"].get("degradation", 0.0) for v in st.values()) / dis if dis > 1e-9 else 0.0
    rtcb = ep.get("era") == "rtcb"
    pct, mw = (0.03, 3.0) if rtcb else (0.05, 5.0)
    run, steps = 0.0, []
    for i in range(len(spp)):
        m, a = sum(m5[3 * i:3 * i + 3]) / 3, sum(bp[3 * i:3 * i + 3]) / 3
        over, under = max(pct * abs(a), mw), min(pct * abs(a), mw)
        dev = -max(20.0, spp[i]) * max(m - a - over, 0) / 4 + min(-20.0, spp[i]) * max(a - m - under, 0) / 4
        run += dam[i // 4] * aw[i // 4] / 4 + spp[i] * (m - aw[i // 4]) / 4 + dev
        run -= deg * sum(max(x, 0.0) for x in m5[3 * i:3 * i + 3]) / 12
        steps.append(round(run, 2))
    shown = []
    for tr in ep["turns"]:
        for c in tr["calls"]:
            s = (c.get("result") or {}).get("shadow_statement")
            if c["tool"] == "get_position" and s:
                shown.append((tr["t"], s["total"]))
    for ev in ep["events"]:
        if ev.get("kind") == "checkpoint" and (m := re.search(r"shadow P&L ([−\-\d,]+) \$", ev.get("text", ""))):
            shown.append((stamp(ev["t"], d0), float(m[1].replace(",", "").replace("−", "-"))))
    ok = all(abs((steps[int((t - 2) // 15) - 1] if int((t - 2) // 15) > 0 else 0.0) - v) <= 1.0 for t, v in shown)
    return {"computed": ok, "steps": steps if ok else None, "shown": sorted(shown)}


def stamp(label: str, d0: date) -> int:
    m = re.match(r"\w{3} (\d{2})-(\d{2}) (\d{2}):(\d{2})", label)
    days = []
    for y in (d0.year - 1, d0.year, d0.year + 1):
        try:
            days.append(date(y, int(m[1]), int(m[2])))
        except ValueError:
            continue
    d = min(days, key=lambda x: abs((x - d0).days))
    return (d - d0).days * 1440 + int(m[3]) * 60 + int(m[4])


def day_label(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x:%a} {x.day} {x:%b %Y}"


def name(ep: dict) -> str:
    pol = ep.get("policy") or {}
    if pol.get("kind") != "model":
        return f"{str(pol.get('kind', 'scripted')).capitalize()} policy"
    base = str(pol.get("model", "")).split("/")[-1]
    if g := re.match(r"gpt-([\d.]+)-?(.*)$", base):
        return f"GPT-{g[1]}" + (" " + g[2].replace("-", " ").title() if g[2] else "")
    if q := re.match(r"qwen([\d.]+)-(\d+)b", base, re.I):
        return f"Qwen{q[1]}-{q[2]}B"
    return base


def excerpt(text: str, limit: int = 200) -> str:
    """The agent's words cut to whole sentences from the start, verbatim; a cut sentence ends at a comma or a dash with
    an ellipsis."""
    sents = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for s in sents:
        if len(out) + len(s) + 1 <= limit:
            out = f"{out} {s}".strip()
            continue
        if not out:
            room = s[:limit]
            at = max(room.rfind(", "), room.rfind("; "), room.rfind(" — "), room.rfind(": "))
            out = (room[:at] if at > limit // 3 else room[:room.rfind(" ")]).rstrip(",;: —") + "…"
        else:
            out += " …"
        break
    return out


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\*\*|__|`", "", text)).strip()


def cut(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def money(x: float) -> str:
    return f"{'−' if x < 0 else ''}${abs(x):,.0f}"


def price(x: float) -> str:
    v = abs(x)
    s = f"${v:,.0f}" if v >= 99.95 else f"${round(v, 1):g}" if v >= 10 else f"${v:.2f}"
    return ("−" if x < 0 else "") + s


def gw(x: float) -> str:
    return f"{x / 1000:,.1f} GW" if abs(x) >= 1000 else f"{x:,.0f} MW"


def module(name_: str, rel: str):
    spec = importlib.util.spec_from_file_location(name_, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def film(hero: dict, frames: list[dict], out: Path, size: tuple[int, int], scale: float,
         keep: set[float] | None = None) -> None:
    rec = module("record", "scripts/record.py")
    w, h = size
    with rec.serve(PAGE) as port, tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(None), Path(profile), w, h), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale,
                          mobile=False)
                page.call("Runtime.enable")
                page.call("Page.navigate", url=f"http://127.0.0.1:{port}/page.html")
                page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.desk ? r() : "
                        "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
                page.js(f"desk.init({json.dumps(hero)}); document.fonts.ready.then(() => true)")
                for i, f in enumerate(frames):
                    page.js(f"desk.render({f['s']}, {f['t']}, {json.dumps(f['mode'])}); true")
                    if keep is None or f["s"] in keep:
                        png = page.call("Page.captureScreenshot", format="png")["data"]
                        name = f"f{i:05d}.png" if keep is None else f"s{f['s']:06.2f}.png"
                        (out / name).write_bytes(base64.b64decode(png))
        finally:
            proc.terminate()
            proc.wait()


if __name__ == "__main__":
    main()
