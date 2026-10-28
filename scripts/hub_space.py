"""Build the desk viewer Space: the 3D desk replay (index.html) and the results (results.html, alias desk.html) from
web/desk, each desk v2-v5 episode as a compact view, each task's posted prices, desk forecasts, alerts, observed
weather, references and reference paths, and the Space card. Every text file is scanned for the real site and operator
names (design decision D9) and for leaks before anything goes to the Hub.

usage: python scripts/hub_space.py [--out build/hub/space] [--only v4] [--publish]
"""

import argparse
import copy
import gzip
import importlib.util
import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import weather as wx  # noqa: E402

from gridsim_core.desk import clock, policies  # noqa: E402
from gridsim_core.desk.ancillary import PRICE_KEY  # noqa: E402
from gridsim_core.desk.data import build as build_series  # noqa: E402
from gridsim_core.desk.data import load_series, load_tasks  # noqa: E402
from gridsim_core.desk.engine import PER_H, site_of  # noqa: E402
from gridsim_core.desk.settle import deviation, partial  # noqa: E402

WEB = ROOT / "src" / "agentenv_gridsim" / "web"
DESK = WEB / "desk"
SPACE = "earakely-scale/GridSimEnv-AgentEnv"
APP = "https://earakely-scale-gridsimenv-agentenv.static.hf.space"
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv"
ARTICLE = "https://huggingface.co/spaces/earakely-scale/GridSimEnv"
ARCHIVE = "cd4a17ed32275a93328ef286ad4f88cc3c3f7216"
VERSIONS = ("v2", "v3", "v4", "v5")
SCENES = {"LZ_WEST": "west", "LZ_HOUSTON": "houston", "LZ_NORTH": "north", "LZ_SOUTH": "south"}
THREE = WEB / "vendor" / "three-0.180.0"
LIVE = ("board.html", "board.css", "board.js")
FEATURED = (("desk-v4-2026-05-08-S04.sol", "Three days of spring thunderstorms in South Texas"),
            ("desk-v2-2026-08-23-S02.sol", "A Houston scarcity day with 13 ERCOT notices"),
            ("desk-v2-2026-01-25-S03.sol", "Winter storm Fern in North Texas"),
            ("desk-v3-2026-07-21-S02.sol", "Reserves and 60 MW of solar through a Houston heat wave"),
            ("desk-v4-2026-01-23-S01.sol", "Fern over three days in the Far West"),
            ("desk-v5-2026-07-21-S02.sol", "The price-impact check: that heat-wave day, its DAM re-cleared"))
D9 = re.compile(r"CROSSETT|CLO_ESR|WIG_ESS|WFTANK|\bJupiter\b|\bMEA\b|\bHabitat\b|\bTenaska\b|\b[A-Z0-9]+_RN\b|"
                r"\b[A-Z0-9]+_ESR\w*\b|\b[A-Z0-9]+_ESS\w*\b")
PRODUCTS = ("regup", "regdn", "rrspfr", "rrsffr", "ecrs", "nspin")
NOTICE_LEVELS = {"Watch", "Emergency", "Advisory", "OCN", "EEA", "EEA1", "EEA2", "EEA3"}
CACHE = ROOT / "cache" / "viewer-desk"
WEATHER = ROOT / "cache" / "weather" / "iem-desk"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "hub" / "space")
    ap.add_argument("--only", nargs="+", choices=VERSIONS, help="Build these versions only (a dev build).")
    ap.add_argument("--publish", action="store_true", help="Replace the Space's files with the build.")
    args = ap.parse_args()
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    data = out / "data"
    (data / "task").mkdir(parents=True)
    (data / "ep").mkdir(parents=True)
    desk = json.loads((ROOT / "results" / "overview" / "desk.json").read_text())
    cat = {"schema": "gridsim.desk.catalog/v1", "archive": ARCHIVE, "models": desk["models"], "versions": [],
           "tasks": {}, "episodes": {}}
    for key in VERSIONS:
        if not args.only or key in args.only:
            cat["versions"].append(version(key, desk, data, cat))
    cat["featured"] = featured(cat)
    (data / "catalog.json").write_text(dumps(cat))
    (out / "desk.json").write_text(dumps(desk))
    site(out)
    (out / "README.md").write_text(readme(cat, desk))
    scan(out)
    files = [p for p in out.rglob("*") if p.is_file()]
    print(f"{len(files)} files, {sum(p.stat().st_size for p in files) / 1e6:.1f} MB, {len(cat['episodes'])} "
          f"episodes, {len(cat['tasks'])} tasks -> {out}")
    if args.publish:
        print(publish(out))
    return 0


def dumps(x) -> str:
    return json.dumps(x, ensure_ascii=False, separators=(",", ":"))


def version(key: str, desk: dict, data: Path, cat: dict) -> dict:
    folder = ROOT / "results" / f"desk-{key}"
    summary = json.loads((folder / "summary.json").read_text())
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        grades = [json.loads(x) for x in f if x.strip()]
    pack = summary["pack"]
    rows = {t["task_id"]: t for t in load_tasks(pack)}
    frozen = frozen_refs(pack)
    v = next(x for x in desk["versions"] if x["version"] == key)
    tasks = sorted({g["task_id"] for g in grades})
    for task_id in tasks:
        task = rows[task_id] if rows[task_id].get("refs") else {**rows[task_id], "refs": frozen[task_id]}
        raw = load_series(pack, task)
        ser = build_series(task, raw)
        tv, meta = task_view(key, task, raw, ser)
        (data / "task" / f"{task_id}.json").write_text(dumps(tv))
        cat["tasks"][task_id] = meta
        for g in (x for x in grades if x["task_id"] == task_id):
            ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
            ev, row = episode_view(key, task, ser, ep, g, desk["models"][g["model"]]["name"])
            name = f"{task_id}.{g['model']}"
            (data / "ep" / f"{name}.json").write_text(dumps(ev))
            cat["episodes"][name] = row
        print(f"{key} {task_id}")
    return {"version": key, "name": v["name"], "role": v["role"], **{k: v[k] for k in ("label", "check_of") if k in v},
            "adds": v["adds"], "does": v["does"], "pack": pack,
            "days_per_task": v["days_per_task"], "block": v.get("block", "day"), "budget": v["budget"],
            "models": [m["key"] for m in v["models"]], "sites": v["sites"], "tasks": tasks,
            "names": (v.get("sensitivity") or {}).get("names") or {}}


def frozen_refs(pack: str) -> dict:
    path = ROOT / "results" / "desk-refs" / pack / "refs.jsonl"
    if not path.is_file():
        return {}
    return {r["task_id"]: r["refs"] for r in map(json.loads, filter(str.strip, path.read_text().splitlines()))}


def r1(x) -> float:
    return round(float(x), 1) + 0.0


def r2(x) -> float:
    return round(float(x), 2) + 0.0


def task_view(key: str, task: dict, raw: dict, ser) -> tuple[dict, dict]:
    site, card, nd = task["site"], task["site"]["card"], len(task["dates"])
    station = wx.STATION[site["load_zone"]]
    _, lat, lon = wx.AIRPORTS[station]
    prev = (date.fromisoformat(task["dates"][0]) - timedelta(days=1)).isoformat()
    pre_lmp = (raw.get("rt_lmp") or {}).get(prev) or []
    pre_dam = (raw.get("dam_spp") or {}).get(prev) or []
    pv = [r1(p) for p in ser.pv] if site.get("pv") and ser.pv else None
    view = {
        "schema": "gridsim.desk.task-view/v1", "task": task["task_id"], "version": key, "dates": task["dates"],
        "era": task.get("era"), "t0": clock.START, "t1": clock.DAY * nd,
        "site": {"id": site["site_id"], "name": card["name"], "region": card["region"], "size": card["size"],
                 "scene": SCENES[site["load_zone"]], "hsl": r1(site["hsl_mw"]), "lsl": r1(site["lsl_mw"]),
                 "emax": r2(site["e_max_mwh"]), "emin": r2(site.get("e_min_mwh", 0.0)), "rte": r2(site["rte"]),
                 "soc0": r2(site["soc0_mwh"]),
                 "pv": {"mw_ac": site["pv"]["mw_ac"], "poi_mw": site["pv"]["poi_mw"]} if site.get("pv") else None},
        "place": {"lat": lat, "lon": lon},
        "tags": {k: task["tags"].get(k) for k in ("season", "day_kind", "notices", "max_rt_lmp", "min_rt_lmp",
                                                    "dam_spread", "neg_lmp_intervals", "deployments")},
        "prices": {"lmp": [r2(x) for x in ser.rt_lmp], "spp": [r2(x) for x in ser.rt_spp],
                   "dam": [r2(x) for x in ser.dam_spp], "dam_posted": [int(x) for x in ser.dam_posted],
                   "pre_lmp": [r2(x) for x in pre_lmp[72:]] if len(pre_lmp) == 288 else [],
                   "pre_dam": [r2(x) for x in pre_dam] if len(pre_dam) == 24 else []},
        "fc": forecasts(ser),
        "pv": pv,
        "alerts": alerts(ser),
        "weather": weather(station, task["dates"]),
        "refs": {k: r2(task["refs"][k]) if task["refs"].get(k) is not None else None
                 for k in ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual")},
        "ghost": ghosts(task, raw),
    }
    meta = {"version": key, "dates": task["dates"], "site": site["site_id"], "name": card["name"],
            "region": card["region"], "size": card["size"], "pv": bool(site.get("pv")), "tags": view["tags"],
            "alerts": sorted({a["title"] for a in view["alerts"] if a["kind"] == "nws"
                              and a["sev"] in ("Warning", "Watch")})[:4],
            "wx": weather_tag(view["weather"]), "refs": view["refs"]}
    return view, meta


def forecasts(ser) -> dict:
    dam, rt = [], []
    for v in ser.desk_forecast:
        if v.product:
            continue
        p50 = v.values.get("p50") or []
        if v.kind == "dam":
            dam.append([v.issued_at, v.start // clock.DAY, [r2(x) for x in v.values.get("p10") or []],
                        [r2(x) for x in p50], [r2(x) for x in v.values.get("p90") or []]])
        elif v.kind == "rt":
            n = max(1, 60 // v.step_min)
            vals = [sum(p50[i:i + n]) / len(p50[i:i + n]) for i in range(0, len(p50), n)]
            rt.append([v.issued_at, v.start - v.start % 60, [r2(x) for x in vals]])
    return {"dam": sorted(dam), "rt": sorted(rt)}


def alerts(ser) -> list[dict]:
    """NWS warnings and watches from issue to expiry, ERCOT notices from issue to their cancellation (else four hours),
    reserve deployments and the battery's outages over their spans; none that ended before the desk opened."""
    out = []
    for n in ser.nws:
        a = n.get("t_issued_at", 0)
        end = n.get("expires") or n.get("ends")
        until = max(a + 30, clock.to_minutes(end, ser.d0)) if end else a + 240
        out.append({"kind": "nws", "t": round(a), "until": round(until), "issued": round(a), "sev": n.get("severity"),
                    "title": n["event"]})
    ends = {n.get("event_id"): clock.to_minutes(n["issued_at"], ser.d0) for n in ser.notices
            if n.get("action") in ("cancel", "end") and n.get("event_id")}
    for n in ser.notices:
        if (n.get("level") or "") not in NOTICE_LEVELS or n.get("action") in ("cancel", "end"):
            continue
        t = clock.to_minutes(n["issued_at"], ser.d0)
        out.append({"kind": "notice", "t": round(t), "until": round(max(t + 30, ends.get(n.get("event_id"), t + 240))),
                    "issued": round(t), "sev": n["level"], "title": notice_title(n)})
    for d in ser.deployments:
        a = clock.to_minutes(d["start"], ser.d0)
        b = clock.to_minutes(d["end"], ser.d0) if d.get("end") else a + 60
        name = AS_NAMES.get(d.get("product"), str(d.get("product", "")).upper())
        out.append({"kind": "deploy", "t": round(a), "until": round(b), "issued": round(a), "sev": d.get("product"),
                    "title": f"ERCOT deploys {name}"})
    for u in ser.unit_events:
        a = clock.to_minutes(u["start"], ser.d0)
        b = clock.to_minutes(u["end"], ser.d0) if u.get("end") else a + 60
        what = "Forced outage" if u.get("kind") == "forced_outage" else f"Derate to {u.get('hsl_mw', 0):.0f} MW"
        out.append({"kind": "outage", "t": round(a), "until": round(b), "issued": round(a), "sev": u.get("kind"),
                    "title": what})
    return sorted((x for x in out if x["until"] > clock.START), key=lambda x: (x["issued"], x["kind"]))


def notice_title(n: dict) -> str:
    """An ERCOT notice in a line: its words after "ERCOT is issuing a", from the text when the title was cut."""
    s = n.get("title") or ""
    if s.endswith("...") or not s:
        s = n.get("text") or s
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^ERCOT (is issuing|has issued|issued) an? ", "", s)
    s = re.sub(r"\.{3}$|\s+INTENDED AUDIENCE.*$", "", s).rstrip(" .")
    if len(s) > 96:
        s = s[:96].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return s[:1].upper() + s[1:]


def weather(station: str, dates: list[str]) -> dict:
    WEATHER.mkdir(parents=True, exist_ok=True)
    raw = WEATHER / f"{station}_{dates[0]}_{len(dates)}d.csv"
    if not raw.is_file():
        start = (date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat()
        raw.write_text(wx.fetch(wx.url(station, start, len(dates) + 1)))
    point = next(p for p, s in wx.STATION.items() if s == station)
    side = wx.build(point, dates[0], raw.read_text(), (-21, 24 * len(dates) + 2))
    keep = ("t", "temp_c", "cover", "clouds", "cloud_base_ft", "ceiling_ft", "wx", "precip_in", "wind_kt", "wind_dir",
            "gust_kt", "vis_sm")
    return {"source": "IEM ASOS", "obs": [{k: o[k] for k in keep if o.get(k) not in (None, [], "")}
                                          for o in side["obs"]]}


def weather_tag(w: dict) -> str | None:
    codes = [c for o in w["obs"] if o["t"] >= 0 for c in o.get("wx", [])]
    temps = [o["temp_c"] for o in w["obs"] if o["t"] >= 0 and "temp_c" in o]
    if any(re.search(r"FZRA|FZDZ", c) for c in codes):
        return "freezing rain"
    if any(re.search(r"SN|PL", c) and not c.startswith("VC") for c in codes):
        return "snow and sleet"
    if any("TS" in c and not c.startswith("VC") for c in codes):
        return "thunderstorms"
    if temps and min(temps) <= -5:
        return "hard freeze"
    if temps and max(temps) >= 38:
        return "extreme heat"
    if any(re.search(r"RA|DZ", c) for c in codes):
        return "rain"
    return None


def ghosts(task: dict, raw: dict) -> dict:
    """The anchor's path (re-run through the core; its total is checked against the stored reference), the operator
    replay's total and the operator's own telemetered SoC."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"ghost-{task['task_id']}-{task.get('series_sha', '')[:12]}.json"
    if path.is_file():
        return json.loads(path.read_text())
    s = policies.run(task, raw, "anchor")
    e = s.engine
    want = task["refs"]["p_anchor"]
    if abs(s.result["total"] - want) > max(5.0, 0.002 * abs(want)):
        print(f"  note {task['task_id']}: anchor re-run {s.result['total']:.2f} vs stored {want:.2f}")
    out = {"anchor": {"p": r2(s.result["total"]), "soc": [r1(x) for x in e.soc], "m": [r1(x) for x in e.metered],
                      "pnl": shadow(site_of(task), e.ser, e.dam_award, e.bp, e.metered,
                                    {"dam_as": e.dam_as, "rt_as": e.rt_as} if e.ancillary else None, s.rtcb)}}
    op = (raw.get("operator") or {}).get("sced") or {}
    soc = [x for d in task["dates"] for x in ((op.get(d) or {}).get("soc_mwh") or [])]
    if len(soc) == 288 * len(task["dates"]) and all(x is not None for x in soc):
        out["actual"] = {"soc": [r1(x) for x in soc]}
    path.write_text(dumps(out))
    return out


def shadow(site, ser, award, bp, metered, anc, rtcb: bool) -> list[int]:
    """The shadow statement after each 15-minute interval: settle.partial's lines, accumulated interval by interval."""
    run, out = 0.0, []
    for i in range(96 * ser.days):
        k0, a = 3 * i, award[i // 4] or 0.0
        m = sum(metered[k0:k0 + 3]) / 3
        run += ser.dam_spp[i // 4] * a / 4 + ser.rt_spp[i] * (m - a) / 4
        run += deviation(sum(bp[k0:k0 + 3]) / 3, m, ser.rt_spp[i], rtcb)
        run -= site.deg * sum(max(x, 0.0) for x in metered[k0:k0 + 3]) / PER_H
        if anc is not None:
            aw = anc["dam_as"][i // 4] or {}
            run += sum(mcpc(ser.dam_mcpc, p, i // 4) * v for p, v in aw.items()) / 4
            rt_as = anc.get("rt_as")
            if rtcb and rt_as is not None:
                for p in set(aw) | {p for k in range(k0, k0 + 3) for p in (rt_as[k] or {})}:
                    pk = PRICE_KEY[p]
                    price_ = ser.rt_mcpc_15[pk][i] if pk in ser.rt_mcpc_15 else 0.0
                    r = sum((rt_as[k] or {}).get(p, 0.0) for k in range(k0, k0 + 3)) / 3
                    run += price_ * (r - aw.get(p, 0.0)) / 4
        out.append(round(run))
    return out


def mcpc(block: dict, product: str, h: int) -> float:
    v = block.get(PRICE_KEY[product])
    return float(v[h]) if v else 0.0


def episode_view(key: str, task: dict, ser, ep: dict, g: dict, name: str) -> tuple[dict, dict]:
    dates, nd = ep["dates"], len(ep["dates"])

    def cat(blk: str, k: str, n: int | None = None) -> list:
        return [x for d in dates for x in (ep[blk][d][k] or [])[:n]]

    award = [x or 0.0 for x in cat("dam", "award_mw")]
    m, bp = cat("rt", "metered_mw"), cat("rt", "base_point_mw")
    soc = cat("rt", "soc_mwh", -1) + [ep["rt"][dates[-1]]["soc_mwh"][-1]]
    anc = None
    if "as_award_mw" in ep["dam"][dates[0]]:
        rt_as = [x or {} for x in cat("rt", "as_award_mw")] if ep["rt"][dates[0]].get("as_award_mw") else None
        anc = {"dam_as": [x or {} for x in cat("dam", "as_award_mw")], "rt_as": rt_as}
    rtcb = ep.get("era") == "rtcb"
    site = site_of(task)
    ser_ep = ser
    if key == "v5":
        ser_ep = copy.copy(ser)
        ser_ep.dam_spp = list(cat("dam", "spp"))
    pnl = shadow(site, ser_ep, award, bp, m, anc, rtcb)
    check(ep, g, site, ser_ep, award, bp, m, anc, rtcb, pnl)
    view = {
        "schema": "gridsim.desk.view/v1", "version": key, "model": g["model"], "name": name,
        "task": ep["task_id"], "policy": {k: ep["policy"].get(k) for k in ("model", "effort")},
        "dam": [r2(x) for x in cat("dam", "spp")], "award": [r1(x) for x in award],
        "m": [r1(x) for x in m], "soc": [r1(x) for x in soc], "pnl": pnl,
        "wakes": [[w["t"], w["reasons"], w.get("turn")] for w in ep["wakes"]],
        "turns": [turn(t) for t in ep["turns"]],
        "subs": [[s["t"], s["tool"], s.get("day"), hours_label(s.get("hours") or []), s["accepted"]]
                 for s in ep.get("submissions", [])],
        "grade": {k: g.get(k) for k in ("valid", "reward", "capture", "capture_phys", "beats_anchor", "floored",
                                        "p", "p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay",
                                        "p_operator_actual")},
        "statement": {"total": g["p"], "lines": g["lines"],
                      "days": {d: v["total"] for d, v in ep["statement"]["days"].items()},
                      "modelled": ep["statement"].get("modelled", [])},
        "usage": {k: ep["usage"].get(k) for k in ("turns", "calls", "cost_usd", "input_tokens", "output_tokens",
                                                   "cached_tokens")},
        "budget": ep.get("budget"),
    }
    if any(abs(a - b) > 0.05 for a, b in zip(m, bp, strict=True)):
        view["bp"] = [r1(x) for x in bp]
    if anc:
        view["as"] = as_hourly(anc, nd)
    row = {"version": key, "task": ep["task_id"], "model": g["model"], "valid": g["valid"], "C": g["capture"],
           "R": g["reward"], "P": g["p"], "beats_anchor": g["beats_anchor"],
           "vs_op": None if g.get("p_operator_replay") is None else r2(g["p"] - g["p_operator_replay"]),
           "turns": len(ep["turns"]), "calls": sum(len(t["calls"]) for t in ep["turns"])}
    return view, row


def check(ep, g, site, ser, award, bp, m, anc, rtcb, pnl) -> None:
    """The running statement must end where settle.partial does, and the statement's total must be the graded P."""
    full = partial(site, ser, rtcb, award, bp, m, 96 * ser.days, anc)["total"]
    if abs(full - pnl[-1]) > 1.5:
        raise SystemExit(f"{ep['task_id']} {g['model']}: running statement {pnl[-1]} != settle.partial {full}")
    if abs(sum(g["lines"].values()) - g["p"]) > 1.0:
        raise SystemExit(f"{ep['task_id']} {g['model']}: statement lines do not add up to P {g['p']}")
    shown = [(t["t"], c["result"]["shadow_statement"]["total"]) for t in ep["turns"] for c in t["calls"]
             if c["tool"] == "get_position" and isinstance(c.get("result"), dict)
             and (c["result"].get("shadow_statement") or {}).get("total") is not None]
    bad = [(t, v) for t, v in shown if abs((pnl[(t - 2) // 15 - 1] if (t - 2) // 15 > 0 else 0) - v) > 1.5]
    if bad:
        print(f"  note {ep['task_id']} {g['model']}: {len(bad)} of {len(shown)} statements the agent read differ "
              f"from the running statement, first {bad[0]}")


def as_hourly(anc: dict, nd: int) -> dict:
    out = {"dam": {}, "rt": {}}
    for p in PRODUCTS:
        dam = [r1((anc["dam_as"][h] or {}).get(p, 0.0)) for h in range(24 * nd)]
        if any(dam):
            out["dam"][p] = dam
        if anc.get("rt_as"):
            rt = [r1(sum((anc["rt_as"][k] or {}).get(p, 0.0) for k in range(12 * h, 12 * h + 12)) / 12)
                  for h in range(24 * nd)]
            if any(rt):
                out["rt"][p] = rt
    return out


def hours_label(hours: list[int]) -> str:
    if not hours:
        return ""
    hs = sorted(set(hours))
    runs, a = [], hs[0]
    for x, y in zip(hs, hs[1:] + [None], strict=True):
        if y != x + 1:
            runs.append(f"HE{a:02d}" if a == x else f"HE{a:02d}–HE{x:02d}")
            a = y
    return ", ".join(runs) if len(runs) <= 2 else f"{runs[0]} … {runs[-1]}"


EVENT_SKIP = {"druc", "dam_close", "start"}
AS_NAMES = {"regup": "RegUp", "regdn": "RegDn", "rrs": "RRS", "rrspfr": "RRS-PFR", "rrsffr": "RRS-FFR", "ecrs": "ECRS",
            "nspin": "Non-Spin"}
MARKETS = {"dam": "DAM price", "rt": "RT price, 15-min", "sced": "SCED price, 5-min", "as_dam": "DAM AS prices",
           "as_rt": "RT AS prices", "asdc": "AS demand curves"}
KINDS = {"load": "ERCOT load forecast", "wind": "ERCOT wind forecast", "solar": "ERCOT solar forecast",
         "net_load": "ERCOT net-load forecast", "outages": "ERCOT outage capacity", "pv": "PV forecast (modelled)",
         "as_price": "AS price view (modelled)", "weather": "NWS alerts in force", "grid": "grid"}
ACTS = {"submit_dam_offers": "DAM offers", "submit_rt_offers": "RT offers", "update_cop": "COP"}


def turn(t: dict) -> dict:
    w = t.get("wake") or {}
    return {"t": t["t"], "why": w.get("reasons") or [], "ev": [x for x in map(event, w.get("events") or []) if x],
            "calls": [call(c) for c in t["calls"]], "q": re.sub(r"[ \t]+\n", "\n", (t.get("text") or "").strip())[:900]}


def stamp(label) -> str:
    return str(label or "")[-5:]


def event(e: dict) -> dict | None:
    k, text = e.get("kind"), re.sub(r"\s+", " ", e.get("text") or "").strip()
    if k in EVENT_SKIP:
        return None
    at = stamp(e.get("t"))
    if k == "dam_results":
        mm = re.search(r"for (\w{3} [\d-]+): awards in (\d+) of 24 hours, sold ([\d.,]+) MWh, bought ([\d.,]+) MWh, "
                       r"net value (\$?[−\-\d,]+); DAM SPP at your node ([−\-\d.]+)\.\.([−\-\d.]+)", text)
        if mm:
            won = "no awards" if mm[2] == "0" else (f"awarded {mm[2]} of 24 hours, sold {fnum(mm[3])} MWh, "
                                                    f"bought {fnum(mm[4])} MWh, {usd_text(mm[5])}")
            text = f"DAM results for {mm[1]}: {won}; node DAM {price(mm[6])} to {price(mm[7])}"
        return {"k": "dam", "at": at, "x": text}
    if k == "notice":
        mm = re.search(r"AS_TYPE: ([\w-]+), DEPLOY_MW: ([\d.]+)(,| DEPLOYED\.| STILL DEPLOYED\.) BEGIN_TIME: \S+ "
                       r"(\d\d:\d\d)\S*, END_TIME: \S+ (\d\d:\d\d)", text)
        if mm:
            mw = float(mm[2])
            x = (f"ERCOT recalls {mm[1]}" if mw < 0.05 else
                 f"ERCOT: {mw:,.0f} MW of {mm[1]} still deployed" if "STILL" in mm[3] else
                 f"ERCOT deploys {mw:,.0f} MW of {mm[1]}, {mm[4]} to {mm[5]}")
            return {"k": "notice", "at": at, "x": x}
        return {"k": "notice", "at": at, "x": "ERCOT: " + notice_title({"title": e.get("title"), "text": text})}
    if k == "weather":
        return {"k": "nws", "at": at, "x": f"NWS {e.get('event') or text}"
                + (f" until {stamp(e['expires'])}" if e.get("expires") else "")}
    if k == "checkpoint":
        mm = re.search(r"SoC ([\d.]+) MWh.*shadow P&L ([−\-\d,]+) \$", text)
        return {"k": "ck", "at": at,
                "x": f"Shift checkpoint: SoC {float(mm[1]):.0f} MWh, settled so far {usd_text(mm[2])}" if mm else text}
    if k == "reminder":
        return {"k": "rem", "at": at, "x": text}
    if k == "adjustment_open":
        return {"k": "ck", "at": at, "x": text.replace("Adjustment period open", "Real-time adjustment period open")}
    if k in ("deployment", "outage"):
        return {"k": k, "at": at, "x": text[:1].upper() + text[1:]}
    return {"k": "ck", "at": at, "x": text}


def fnum(s: str) -> str:
    v = float(s.replace(",", ""))
    return f"{v:,.0f}" if abs(v) >= 10 or v == 0 else f"{v:,.1f}"


def usd_text(s: str) -> str:
    return usd(float(s.replace("$", "").replace(",", "").replace("−", "-")))


def usd(v: float) -> str:
    return f"{'−' if v <= -0.5 else ''}${abs(v):,.0f}"


def price(v) -> str:
    x = float(str(v).replace("−", "-"))
    a = abs(x)
    return f"{'−' if x < 0 else ''}${a:,.0f}" if a >= 100 else f"{'−' if x < 0 else ''}${a:.1f}" if a >= 10 else \
        f"{'−' if x < 0 else ''}${a:.2f}"


def gw(mw: float) -> str:
    return f"{mw / 1000:.1f} GW"


def call(c: dict) -> dict:
    tool, a, r = c["tool"], c.get("args"), c.get("result")
    a, r = a if isinstance(a, dict) else {}, r if isinstance(r, dict) else {}
    try:
        sub, lines, res, cls = describe(tool, a, r)
    except (KeyError, TypeError, ValueError, IndexError, ZeroDivisionError, AttributeError):
        sub, lines, res, cls = "", [], "", "ok"
    if r.get("error"):
        res, cls = str(r["error"])[:160], "no"
    out = {"n": tool, "c": cls, "h": chip_of(tool, a, r)}
    out |= {"s": sub} if sub else {}
    out |= {"l": lines} if lines else {}
    out |= {"r": res} if res else {}
    return out


def chip_of(tool: str, a: dict, r: dict) -> str:
    simple = {"get_prices": "prices", "get_forecasts": "forecasts", "get_grid_conditions": "grid",
              "get_asset_status": "asset", "get_position": "position", "optimize": "optimize"}
    if tool in simple:
        return simple[tool]
    if tool == "check_submission":
        return f"check {str(a.get('kind', 'dam')).upper()}"
    if tool == "set_reminder":
        return f"reminder {stamp(r.get('at'))}".strip()
    acc = r.get("accepted_hours")
    return f"{ACTS.get(tool, tool)} {acc}" if acc and len(str(acc)) <= 13 else ACTS.get(tool, tool)


def describe(tool: str, a: dict, r: dict) -> tuple[str, list[str], str, str]:
    day = f", {a['day']}" if a.get("day") else ""
    if tool == "get_prices":
        mk = a.get("market", "rt")
        sub = f"{MARKETS.get(mk, mk)} at the {a.get('point', 'node')}{day}"
        if r.get("mcpc"):
            bits = [f"{AS_NAMES.get(p, p)} {price(min(xs))}–{price(max(xs))}" for p, vs in r["mcpc"].items()
                    if (xs := [v for v in vs or [] if v is not None])]
            return sub, [], ("; ".join(bits[:3]) + (" …" if len(bits) > 3 else "")) or "nothing posted yet", "ok"
        vals = [v for v in r.get("values") or [] if v is not None]
        if not vals:
            return sub, [], r.get("note") or "nothing posted yet", "dim"
        if mk == "dam":
            pk = max(range(len(vals)), key=lambda i: vals[i])
            return sub, [], f"{price(min(vals))} to {price(max(vals))}, peak HE{pk + 1:02d}", "ok"
        return sub, [], (f"{stamp(r.get('start'))}–{stamp(r.get('end'))}: {price(min(vals))} to {price(max(vals))}, "
                         f"last {price(vals[-1])}"), "ok"
    if tool == "get_forecasts":
        kind = a.get("kind", "price")
        if kind == "price":
            mk = r.get("market") or a.get("market", "dam")
            sub = f"{'DAM' if mk == 'dam' else 'RT'} price, desk forecast (modelled){day}"
            p50 = [v for v in r.get("p50") or [] if v is not None]
            if not p50:
                return sub, [], r.get("note") or "", "dim"
            i = max(range(len(p50)), key=lambda j: p50[j])
            slot = f"HE{i + 1:02d}" if r.get("step") == "1h" else f"{(i * 15) // 60:02d}:{(i * 15) % 60:02d}"
            iss = f"issued {stamp(r.get('issued_at'))}: " if r.get("issued_at") else "naive fallback: "
            band = f" (P10–P90 {price(r['p10'][i])}–{price(r['p90'][i])})" if r.get("p10") and r.get("p90") else ""
            return sub, [], f"{iss}P50 {price(min(p50))} to {price(max(p50))}, peak {slot}{band}", "ok"
        if kind == "weather":
            names = list(dict.fromkeys(x.get("event") or "" for x in r.get("alerts") or []))
            return KINDS["weather"], [], ", ".join(names[:3]) + (" …" if len(names) > 3 else "") or "none", "ok"
        if kind == "as_price":
            bits = [f"{AS_NAMES.get(p, p)} {price(max(v))}" for p, v in (r.get("p50") or {}).items() if v][:3]
            return KINDS["as_price"], [], ("peaks " + ", ".join(bits)) if bits else "", "ok"
        vals = [v for v in r.get("values") or [] if v is not None]
        if not vals:
            return KINDS.get(kind, kind), [], r.get("note") or "", "dim"
        return KINDS.get(kind, kind), [], f"peak {gw(max(vals))} at HE{vals.index(max(vals)) + 1:02d}", "ok"
    if tool == "get_grid_conditions":
        bits = []
        if p := r.get("prc_mw"):
            bits.append(f"reserves {gw(p['last'])}" + (" (modelled proxy)" if "proxy" in str(p.get("kind")) else ""))
        if lam := r.get("lambda"):
            bits.append(f"system λ {price(lam['last'])}")
        if ld := r.get("load_mw"):
            bits.append(f"load {gw(ld['last'])}")
        if r.get("eea_level"):
            bits.append(str(r["eea_level"]))
        return "", [], ", ".join(bits) or (r.get("note") or ""), "ok"
    if tool == "get_asset_status":
        e_max = (r.get("nameplate") or {}).get("e_max_mwh")
        bits = [f"SoC {r.get('soc_mwh', 0):.1f}" + (f" of {e_max:.0f}" if e_max else "") + " MWh",
                f"status {r.get('status', 'ON')}"]
        if r.get("outage"):
            bits.append("outage")
        if aw := r.get("as_awards_mw"):
            bits.append(", ".join(f"{k} {v:.0f} MW" for k, v in list(aw.items())[:2]))
        if r.get("pv_mw"):
            bits.append(f"PV {r['pv_mw']:.0f} MW (modelled)")
        return "", [], ", ".join(bits), "ok"
    if tool == "get_position":
        bits = []
        dam = r.get("dam") or {}
        if "sold_mwh" in dam:
            bits.append("DAM: no awards" if not dam["sold_mwh"] and not dam["bought_mwh"] else
                        f"DAM sold {dam['sold_mwh']:,.0f} MWh, bought {dam['bought_mwh']:,.0f} MWh, "
                        f"{usd(dam.get('value_usd', 0))}")
        elif dam.get("status"):
            bits.append(f"DAM {dam['status']}")
        rt = r.get("rt") or {}
        if rt.get("discharged_mwh") is not None:
            bits.append(f"RT {rt['discharged_mwh']:,.0f} MWh out, {rt['charged_mwh']:,.0f} in")
        if st := r.get("shadow_statement"):
            bits.append(f"settled {usd(st['total'])}")
        return a.get("day", ""), [], "; ".join(bits), "ok"
    if tool in ("submit_dam_offers", "submit_rt_offers"):
        cs = [c for c in a.get("curves") or [] if isinstance(c, dict)]
        lines = [f"{c.get('hours', '')}: {curve(c)}" for c in cs[:2]]
        lines += [f"+{len(cs) - 2} more curves"] if len(cs) > 2 else []
        lines += ["AS: " + as_offers(a["as_offers"])] if a.get("as_offers") else []
        ok = r.get("accepted_hours") or r.get("as_accepted")
        return f"for {a.get('day', 'D0')}", lines, accepted(r), "ok" if ok else "no"
    if tool == "update_cop":
        rows = [x for x in a.get("rows") or [] if isinstance(x, dict)]
        return (f"for {a.get('day', 'D0')}", [f"{x.get('hours', '')}: {cop_row(x)}" for x in rows[:2]], accepted(r),
                "ok" if r.get("accepted_hours") else "no")
    if tool == "check_submission":
        sub = f"dry run, {str(a.get('kind', 'dam')).upper()}"
        if r.get("ok"):
            wc = r.get("would_clear_at_desk_p50")
            n = sum(1 for x in wc or [] if not str(x).endswith(":0")) if wc else None
            return sub, [], "valid" + (f", would clear {n} of 24 hours at the desk P50" if wc else ""), "ok"
        errs = r.get("errors") or r.get("rejected") or []
        x = errs[0] if errs else {}
        return sub, [], f"{x.get('code', '')} {str(x.get('text', ''))[:100]}".strip(), "no"
    if tool == "optimize":
        cn = a.get("constraints") or {}
        bits = [f"risk {a.get('risk', 0.5)}"]
        bits += [f"end SoC {cn['end_soc_mwh']} MWh"] if "end_soc_mwh" in cn else []
        bits += [f"at most {cn['max_cycles']} cycles"] if "max_cycles" in cn else []
        view = "the desk forecast" if a.get("price_view", "desk") == "desk" else "its own price view"
        pr = r.get("projected") or {}
        exp = pr.get("pnl", pr.get("expected"))
        res = (f"proposes {len(r.get('dam_curves') or [])} DAM and {len(r.get('rt_curves') or [])} RT curves and a "
               "COP" + (f", projects {usd(exp)} (modelled)" if isinstance(exp, (int, float)) else ""))
        return f"on {view}, {', '.join(bits)}", [], res, "ok"
    if tool == "set_reminder":
        note = str(a.get("note") or "")
        pend = f", {r['pending']} pending" if r.get("pending") else ""
        return (f"for {stamp(r.get('at') or a.get('at'))}",
                [f"“{note[:110]}{'…' if len(note) > 110 else ''}”"] if note else [], f"set{pend}", "ok")
    return "", [], "", "ok"


def accepted(r: dict) -> str:
    bits = [f"accepted {r['accepted_hours']}"] if r.get("accepted_hours") else []
    if r.get("as_accepted"):
        bits.append("AS " + ", ".join(f"{k} {v}" for k, v in list(r["as_accepted"].items())[:2]))
    if rej := r.get("rejected"):
        bits.append(f"rejected {rej[0].get('code', '')}: {str(rej[0].get('text', ''))[:80]}")
    elif r.get("as_rejected") and not r.get("as_accepted"):
        bits.append(f"AS rejected {r['as_rejected'][0].get('code', '')}")
    return "; ".join(bits)


def curve(c: dict) -> str:
    pts = sorted((float(q), float(p)) for q, p in c.get("points") or [] if q is not None and p is not None)
    if not pts and (c.get("offer") or c.get("bid")):
        return "offer and bid curves"
    buy = [(p, -q) for q, p in pts if q < -0.05]
    sell = [(p, q) for q, p in pts if q > 0.05]
    out = [f"buys up to {max(q for _, q in buy):.0f} MW at ≤ {price(max(p for p, _ in buy))}"] if buy else []
    if sell:
        lv = sorted({p: max(q for pp, q in sell if pp == p) for p, _ in sell}.items())
        out.append("sells " + ", ".join(f"{q:.0f} MW at ≥ {price(p)}" for p, q in lv[:2])
                   + (" …" if len(lv) > 2 else ""))
    return "; ".join(out) or "0 MW"


def as_offers(xs: list) -> str:
    bits = []
    for x in (x for x in xs if isinstance(x, dict)):
        name = AS_NAMES.get(str(x.get("product", "")).lower().replace("-", ""), x.get("product"))
        b = x.get("blocks")
        mw = b[0][0] if b and isinstance(b[0], (list, tuple)) else first(x.get("mw"))
        pr = b[0][1] if b and isinstance(b[0], (list, tuple)) else first(x.get("price"))
        bits.append(f"{name} {mw:.0f} MW at {price(pr)}" if isinstance(mw, (int, float)) and
                    isinstance(pr, (int, float)) else str(name))
    seen = list(dict.fromkeys(bits))
    out = [f"{b} ×{bits.count(b)}" if bits.count(b) > 1 else b for b in seen]
    return ", ".join(out[:3]) + (f" and {len(out) - 3} more" if len(out) > 3 else "")


def first(v):
    return v[0] if isinstance(v, list) and v else v


def cop_row(x: dict) -> str:
    bits = [str(x["status"])] if x.get("status") else []
    hb = x.get("hbsoc_mwh")
    if isinstance(hb, list) and hb:
        bits.append(f"HBSOC {hb[0]:g} to {hb[-1]:g} MWh")
    elif hb is not None:
        bits.append(f"HBSOC {hb:g} MWh")
    lo, hi = x.get("min_soc_mwh"), x.get("max_soc_mwh")
    if lo is not None and hi is not None:
        bits.append(f"SoC {lo:g} to {hi:g} MWh")
    elif lo is not None or hi is not None:
        bits.append(f"MinSOC {lo:g} MWh" if lo is not None else f"MaxSOC {hi:g} MWh")
    if x.get("hsl_mw") is not None:
        bits.append(f"HSL {x['hsl_mw']:g} MW")
    return ", ".join(bits) or "unchanged"


def featured(cat: dict) -> list[dict]:
    return [{"key": k, "why": why} for k, why in FEATURED if k in cat["episodes"]]


def site(out: Path) -> None:
    """The pages, their stylesheets and fonts at the root, and every module they import, followed from each page's
    scripts: the desk's own, the stage's under stage/, three.js under vendor/. The v1 live board's page stays at its
    address, outside the desk's navigation."""
    for f in DESK.rglob("*"):
        if f.is_file() and f.name != ".DS_Store":
            dst = out / f.relative_to(DESK)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, dst)
    shutil.copy(out / "results.html", out / "desk.html")
    for name in LIVE:
        shutil.copy(WEB / name, out / name)
    todo, seen = [f for f in DESK.glob("*.js")], set()
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        for spec in re.findall(r"""(?:\bfrom\s+|\bimport\s*\(?\s*)["']([^"']+)["']""", f.read_text()):
            dep = resolve(spec, f)
            if dep is not None and dep not in seen:
                todo.append(dep)
    for f in seen:
        rel = f.relative_to(DESK) if f.is_relative_to(DESK) else f.relative_to(WEB)
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(f, out / rel)
    for rel in ("LICENSE", "build/three.core.min.js"):
        (out / "vendor/three-0.180.0" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(THREE / rel, out / "vendor/three-0.180.0" / rel)


def resolve(spec: str, f: Path) -> Path | None:
    if spec == "three":
        return THREE / "build" / "three.module.min.js"
    if spec.startswith("three/addons/"):
        return THREE / "examples" / "jsm" / spec.removeprefix("three/addons/")
    if spec.startswith("gridsim/"):
        return WEB / spec.removeprefix("gridsim/")
    if spec.startswith("."):
        return (f.parent / spec).resolve()
    raise SystemExit(f"{f}: cannot resolve import {spec!r}")


def readme(cat: dict, desk: dict) -> str:
    count = {v["version"]: sum(1 for e in cat["episodes"].values() if e["version"] == v["version"])
             for v in cat["versions"]}
    ladder = "\n".join(f"- **{v['version']}, {v['name']}:** {v['adds']} ({count[v['version']]} replays)."
                       for v in cat["versions"] if v["role"] == "ladder")
    checks = "\n\n".join(
        f"Apart from the ladder, **{v['label']}** plays {v['check_of']}'s battery-days again with each day-ahead "
        "market re-cleared against the desk's own offers in ERCOT's disclosed offer stack "
        f"([results]({APP}/results.html?v={v['version']}), {count[v['version']]} replays). For one 100–150 MW "
        f"battery the price moves by cents, and every paired {v['version']} − {v['check_of']} gap is within noise; a "
        "fleet desk, a QSE trading a portfolio of batteries, is where price impact would matter."
        for v in cat["versions"] if v["role"] == "check")
    lead = cat["featured"][0]["key"]
    task, model = lead.rsplit(".", 1)
    how, *each = desk["models_lines"]
    settings = "\n".join([how, "", *(f"- {x}" for x in each)])
    return f"""---
title: GridSimEnv Desk
emoji: 🔋
colorFrom: green
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: An agent trades a real ERCOT battery, replayed in 3D
---

# GridSimEnv Desk

An agent works as the battery trader at a QSE for one real ERCOT battery at its own node. It submits ERCOT's own
objects: day-ahead and real-time energy offer curves, ancillary-service offers and its current operating plan. The
clock moves on its own: the agent wakes at the market's milestones, at ERCOT notices, NWS alerts and outages, and at
reminders it sets. The day settles on ERCOT's rules.

**[Replays]({APP}/index.html).** Each recorded episode plays on the battery site in 3D, in the day's real light and
the weather observed at the region's airport. The containers' light strips fill with the state of charge, power runs
along the line as the battery charges or discharges, and the co-located solar tracks the sun on the days that have it.
Beside the scene, the desk shows prices only as they posted, and every tool call as the model made it. The clock
stops at each of the agent's turns.

**[Results]({APP}/results.html).** Hindsight capture, reward and settled dollars for GPT-6.1 Sol and GPT-6 Luna at
high reasoning effort and an untrained Qwen3-4B with thinking off, version by version. Each is set against the anchor,
the hindsight optimum and the battery's real operator.

The ladder adds one kind of realism a version:

{ladder}

{checks}

**The headline.** {desk['across']}

There are {len(cat['episodes'])} replays: every model on every task of each version's eval pack. Each replay is a
recorded episode (`gridsim.desk.episode/v1`) converted for the viewer, and nothing here calls a model. The running
statement is the desk's shadow settlement, recomputed from the episode and checked against the environment's own.

## Models and settings

{settings}

## Links

- One episode: `index.html?v=v4&m={model}&task={task}`. Add `&t=` for a moment, in minutes from the first operating
  day's midnight (CPT).
- One version's results: `results.html?v=v4`; the price-impact check's, `results.html?v=v5`. `desk.html` is the
  same page.
- The episodes, tasks and results are in the dataset [earakely-scale/GridSimEnv-AgentEnv]({DATASET}).
- The write-up is the article Space [earakely-scale/GridSimEnv]({ARTICLE}).
- The environment and this viewer are in [agentenv-gridsim-plugin]({REPO}).
- The earlier viewer (v1 and the previews) is archived at
  [this Space's revision {ARCHIVE[:7]}](https://huggingface.co/spaces/{SPACE}/tree/{ARCHIVE}).

## Data and attribution

- Prices, awards, notices and disclosures come from ERCOT's public reports. This Space is not affiliated with or
  endorsed by ERCOT.
- Alerts come from the National Weather Service. The scene's weather is IEM ASOS observations at the region's main
  airport, from the Iowa Environmental Mesonet, Iowa State University (public domain).
- These are modelled, and labelled so: the desk price forecast, the co-located PV, degradation, warranty, the
  end-of-window energy and capacity-short charges.
- The sites are anonymised as Battery S01 to S04, by region.

## Licences

- Viewer code: Apache-2.0. three.js 0.180.0 (`vendor/`): MIT. IBM Plex (`fonts/`): SIL Open Font License 1.1.
- Scene and art: procedural geometry and canvas-drawn textures, CC0. No ERCOT logo or trademark is used, and the
  battery enclosures carry no brand.
"""


def scan(out: Path) -> None:
    hd = module("hub_desk", "scripts/hub_desk.py")
    hr = module("hub_results", "scripts/hub_results.py")
    text = (".json", ".html", ".js", ".css", ".md", ".txt")
    files = {str(p.relative_to(out)): p.read_bytes() for p in out.rglob("*")
             if p.is_file() and p.suffix in text and "vendor" not in p.parts}
    hd.anonymous(files, hd.names(ROOT) + ["MEA"])
    hr.leaks(files)
    keys = re.compile(r'"(resource|resource_pre|settlement_point|qse|load_zone)"\s*:')
    for k, v in files.items():
        if keys.search(v.decode()):
            raise SystemExit(f"{k} carries a resource, node or QSE field; nothing was published")
        if hit := D9.search(v.decode()):
            raise SystemExit(f"{k} names {hit[0]!r}, a real resource, node or operator; nothing was published")
    print(f"scan: {len(files)} text files clean")


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def publish(out: Path) -> str:
    """One commit: the build's files, and every other file in the Space deleted except its .gitattributes."""
    api = HfApi()
    files = sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file())
    stale = sorted(set(api.list_repo_files(SPACE, repo_type="space")) - set(files) - {".gitattributes"})
    ops = [CommitOperationDelete(path_in_repo=f) for f in stale] + [
        CommitOperationAdd(path_in_repo=f, path_or_fileobj=str(out / f)) for f in files]
    info = api.create_commit(SPACE, repo_type="space", operations=ops, commit_message=(
        "The desk viewer: the ladder v2 to v4 and the v5 price-impact check, every episode in 3D beside the desk, and "
        "the results"))
    return f"{info.commit_url} ({len(files)} files, {len(stale)} removed)"


if __name__ == "__main__":
    sys.exit(main())
