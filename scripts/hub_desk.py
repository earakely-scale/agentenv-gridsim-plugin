"""The desk on the Hub: results/overview/desk.json (read by the dataset card, the article and the viewer Space), the
dataset's desk_leaderboard, desk_runs and desk_tasks configs, its results/desk-v<N>/ folders and the card's charts,
exported from the desk page staged locally. Each version's grades are checked against its summary.json and its tasks'
references against the grades before anything is written, and links to its files on GitHub pin its results tag. The
viewer Space builds and publishes itself.

    .venv/bin/python scripts/hub_desk.py --desk results --ref v2=desk-v2-results ... --gif v4 TASK GIF --lead v4
    .venv/bin/python scripts/hub_desk.py --desk results --ref v2=desk-v2-results ... --lead v4 --publish
"""

import argparse
import gzip
import importlib.util
import io
import json
import math
import posixpath
import re
import shutil
from collections import Counter
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "hub" / "desk"
WEB = ROOT / "src" / "agentenv_gridsim" / "web"
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv"
APP = "https://earakely-scale-gridsimenv-agentenv.static.hf.space"
GIF = "assets/gridsim-desk-hero.gif"
PAGE = {"desk.html": "desk/results.html", "results.js": "desk/results.js", "results.css": "desk/results.css",
        "base.css": "desk/base.css",
        **{f"fonts/{f}": f"desk/fonts/{f}" for f in ("plex-sans.woff2", "plex-mono-500.woff2", "plex-mono-600.woff2")}}
CHARTS = ROOT / "hub" / "desk-charts"
CARD_CHARTS = {"width": 600, "lead": 660, "phone": {"width": 350, "media": "(max-width: 480px)"}}
LADDER = (
    ("v2", "The Live Grid", "energy only: the DAM and real time at a real battery's own node, with ERCOT notices, NWS "
     "alerts and the battery's outages at their real minutes",
     "bids the DAM, offers real-time curves and files its COP, waking at milestones, notices and its own reminders"),
    ("v3", "Sun, Storage and Reserves", "ERCOT's five ancillary services in the DAM and real time, with "
     "state-of-charge duration rules, deployments and capacity-short charges; a co-located solar option (modelled)",
     "co-optimises energy and reserves and keeps the charge to back them"),
    ("v4", "Weather Front", "three operating days across a weather front, on ERCOT's forecasts as each was issued",
     "bids three day-ahead markets as the forecasts move"),
    ("v5", "The Market Floor", "price impact: its DAM offers re-clear the day-ahead market against the day's real "
     "offers, disclosed 60 days later", "offers into a market its own bids move"),
)
CHECKS = {"v5": {"check_of": "v3", "label": "v5 · price-impact check"}}
WHY = {"v2": "when the node's day-ahead price ran far above real time"}
NAMED = {"v2": {"2026-01-25": "winter storm Fern"}, "v4": {"2026-01-23": "winter storm Fern"}}
IDLE = {v: "Idle, the battery offering nothing, still earns: through ERCOT's proxy AS offers and the co-located solar "
           "(modelled)." for v in ("v3", "v5")}
MODELS = {"sol": ("GPT-6.1 Sol", "API", {"api": "Responses API"}),
          "luna": ("GPT-6 Luna", "API", {"api": "Responses API"}),
          "qwen": ("Qwen3-4B (untrained)", "open", {"checkpoint": "Qwen/Qwen3-4B", "server": "vLLM 0.29",
                                                     "dtype": "bf16", "tool_parser": "hermes"})}
REFS = (("anchor", "Anchor", "Anchor: the desk's optimiser at every wake, same information"),
        ("operator_replay", "The operator's bids, replayed", "The real operator's disclosed bids, replayed"),
        ("operator_actual", "The operator, as settled", "The real operator's awards and metered output, settled"),
        ("hind_phys", "Hindsight, DAM tied to dispatch", "Hindsight optimum, DAM position tied to dispatch"),
        ("hind", "Hindsight optimum", "Hindsight optimum"), ("idle", "Idle", "Idle"))
LINES = ("dam_energy", "rt_energy_imbalance", "deviation", "load_allocated", "dam_as_capacity", "rt_as_imbalance",
         "capacity_short", "failure_to_provide", "pv_energy", "degradation", "warranty_overage", "end_soc_shortfall")
F64, I64, STR, BOOL = pa.float64(), pa.int64(), pa.string(), pa.bool_()
LEADERBOARD = pa.schema([
    ("version", STR), ("pack", STR), ("type", STR), ("key", STR), ("name", STR), ("model_id", STR), ("effort", STR),
    ("reasoning_effort", STR), ("thinking", BOOL), ("weights", STR), ("tasks", I64), ("days_per_task", I64),
    ("operating_days", I64), ("valid", F64),
    *((f"{m}{s}", F64) for m in ("capture", "reward", "p_usd", "p_minus_anchor_usd", "p_minus_operator_replay_usd",
                                  "p_minus_operator_actual_usd") for s in ("", "_ci_low", "_ci_high")),
    ("capture_phys", F64), ("beats_anchor", F64), ("usd_per_episode", F64), ("turns", F64), ("calls", F64),
    ("submissions_accepted", F64), ("submissions_rejected", F64), ("reminders", F64), ("cycles", F64),
    ("source", STR),
])
RUNS = pa.schema([
    ("version", STR), ("pack", STR), ("model", STR), ("name", STR), ("model_id", STR), ("effort", STR),
    ("reasoning_effort", STR), ("thinking", BOOL), ("task_id", STR), ("date", STR), ("site", STR), ("region", STR),
    ("battery", STR), ("era", STR), ("status", STR),
    ("valid", BOOL), ("capture", F64), ("capture_phys", F64), ("reward", F64), ("stretch", F64), ("floored", BOOL),
    ("beats_anchor", BOOL), ("p_usd", F64), ("p_idle", F64), ("p_anchor", F64), ("p_hind", F64), ("p_hind_phys", F64),
    ("p_operator_replay", F64), ("p_operator_actual", F64), *((f"{x}_usd", F64) for x in LINES), ("lines", STR),
    ("turns", I64), ("calls", I64), ("submissions", I64), ("rejected", I64), ("input_tokens", I64),
    ("output_tokens", I64), ("cached_tokens", I64), ("usd", F64), ("wall_seconds", F64), ("episode", STR),
])


TASKS = pa.schema([
    ("version", STR), ("pack", STR), ("role", STR), ("task_id", STR), ("era", STR), ("dates", pa.list_(STR)),
    ("days", I64), ("site", STR), ("region", STR), ("battery", STR), ("hsl_mw", F64), ("e_max_mwh", F64),
    ("round_trip_efficiency", F64), ("standby_loss_pct_per_h", F64), ("degradation_usd_per_mwh", F64),
    ("warranty_cycles_per_day", F64), ("soc0_mwh", F64), ("pv_mw_ac", F64), ("operator_disclosed", BOOL),
    ("season", STR), ("day_kind", STR), ("notices", I64), ("deployments", I64), ("max_rt_lmp", F64),
    ("min_rt_lmp", F64), ("negative_lmp_intervals", I64), ("dam_spread", F64), ("max_dam_mcpc", F64),
    ("max_rt_mcpc", F64), ("p_idle", F64), ("p_anchor", F64), ("p_hind", F64), ("p_hind_phys", F64),
    ("p_operator_replay", F64), ("p_operator_actual", F64), ("floored", BOOL), ("anchor_risk", F64),
    ("anchor_dam_position", STR), ("core_version", STR),
])
ROLES = ("pilot", "eval", "tune")
GRADED = ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual")


class Mismatch(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--desk", type=Path, default=ROOT / "results", help="The folder holding desk-v<N>/ results.")
    ap.add_argument("--ref", action="append", default=[], metavar="vN=TAG",
                    help="The git tag of a version's results commit on the desk branch; its GitHub links pin it.")
    ap.add_argument("--results", type=Path, default=ROOT / "results",
                    help="Where overview/desk.json goes, beside overview/results.json; the card is built from both.")
    ap.add_argument("--gif", nargs=3, action="append", default=[], metavar=("VERSION", "TASK", "PATH"),
                    help="A desk GIF (scripts/hub_desk_hero.py) of the model's episode on TASK; one per version.")
    ap.add_argument("--gif-model", default="sol", help="The model whose episodes the GIFs film.")
    ap.add_argument("--lead", metavar="VERSION", help="The version whose GIF leads the card; else the first GIF opens "
                                                     "the desk section. Every GIF links its episode's replay.")
    ap.add_argument("--publish", action="store_true", help="Upload to the dataset; the viewer Space publishes itself.")
    ap.add_argument("--only", nargs="+", metavar="vN", help="Publish these versions, though --desk holds more.")
    args = ap.parse_args()
    refs = dict(x.split("=", 1) for x in args.ref)
    desk, files = build(args.desk, refs, args.only)
    lead = args.lead or (args.gif[0][0] if args.gif else None)
    desk["gifs"] = {}
    for key, task, path in args.gif:
        v = next(x for x in desk["versions"] if x["version"] == key)
        info, ep = gif_info(v, args.desk / f"desk-{key}", desk["models"][args.gif_model]["label"], args.gif_model,
                            task, key == lead and bool(args.lead))
        info["path"] = GIF if key == lead else f"assets/gridsim-desk-{key}.gif"
        desk["gifs"][key] = info
        card = ep["site"]["card"]
        v["story"] = story(ep, {"model": args.gif_model, "label": f"{card['name']} ({card['region']}, {card['size']}), "
                                                                   f"{date_label(ep['dates'])}"})
        files[info["path"]] = Path(path).read_bytes()
    if lead:
        desk["gif"] = desk["gifs"][lead]
        one = [k for k in [lead, *desk["gifs"]] if next(v for v in desk["versions"] if v["version"] == k)[
            "days_per_task"] == 1]
        desk["story_version"] = one[0] if one else lead
    hd = module("hub_dataset", "scripts/hub_dataset.py")
    desk["across"], desk["models_lines"] = hd.across_text(desk), hd.models_lines(desk)
    out = args.results / "overview" / "desk.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(desk, indent=1, ensure_ascii=False) + "\n")
    hr = module("hub_results", "scripts/hub_results.py")
    space = BUILD / "space"
    shutil.rmtree(space, ignore_errors=True)
    space.mkdir(parents=True)
    for n, src in PAGE.items():
        (space / n).parent.mkdir(parents=True, exist_ok=True)
        (space / n).write_bytes((WEB / src).read_bytes())
    for src in CHARTS.iterdir():
        (space / src.name).write_bytes(src.read_bytes())
    (space / "desk.json").write_text(json.dumps(desk, ensure_ascii=False, separators=(",", ":")))
    figs = figures(space, [v["version"] for v in desk["versions"]], hr)
    card = hd.card_only(args.results)
    ds = files | figs | {"README.md": card.encode(), "results/overview/desk.json": out.read_bytes()}
    text = {k: re.sub(rb"base64,[\w+/=]+", b"base64,", v) if k.endswith(".svg") else v for k, v in ds.items()
            if not k.endswith(".gif")}
    hr.leaks(text)
    anonymous(text, names(args.desk.parent))
    dataset = BUILD / "dataset"
    shutil.rmtree(dataset, ignore_errors=True)
    for k, v in ds.items():
        (dataset / k).parent.mkdir(parents=True, exist_ok=True)
        (dataset / k).write_bytes(v)
    print(f"dataset: {len(ds)} files, {sum(map(len, ds.values())) / 1e6:.2f} MB in {dataset}")
    for v in desk["versions"]:
        print(f"{v['version']} {v['pack']}: " + ", ".join(f"{m['name']} C {m['C']['mean']}" for m in v["models"]))
    if args.publish:
        done = ", ".join(v["version"] for v in desk["versions"])
        print("dataset:", hr.publish("dataset", ds, f"The desk: {done} results and tables"))


def build(desk_dir: Path, refs: dict[str, str], only: list[str] | None) -> tuple[dict, dict[str, bytes]]:
    versions, files, ms = [], {}, settings()
    for key, name, adds, does in LADDER:
        folder = desk_dir / f"desk-{key}"
        if not (folder / "summary.json").is_file() or only and key not in only:
            continue
        if key not in refs:
            raise SystemExit(f"--ref {key}=TAG: the results tag that {folder} was committed under")
        v, fs = version(key, name, adds, does, folder, refs[key], ms)
        versions.append(v)
        files |= fs
    ladder = [{"version": k, "name": n, "adds": a, "does": d, "status": "results" if any(
        v["version"] == k for v in versions) else "next"} for k, n, a, d in LADDER if k not in CHECKS]
    c = [x for v in versions if v["role"] == "ladder" for d in v["days"] for x in d["C"].values()]
    scale = [round(math.floor((min(c) - 0.02) / 0.2) * 0.2, 6), round(math.ceil((max(c) + 0.04) / 0.2) * 0.2, 6)]
    return {"schema": "gridsim.desk.hub/v1", "models": ms, "ladder": ladder, "versions": versions,
            "charts": CARD_CHARTS | {"days_scale": scale}}, files


def settings() -> dict:
    """Each model's settings as scripts/desk_run.py's presets ran it in every frozen version (no run passed an
    override), how it was served and its label: desk.json's `models`, which every surface names the models from."""
    run = module("desk_run", "scripts/desk_run.py").MODELS
    out = {}
    for k, (name, weights, served) in MODELS.items():
        p = run[k]
        setting = f"effort {p['effort']}" if p["effort"] else f"thinking {'on' if p['thinking'] else 'off'}"
        chat = {"temperature": p["sampling"]["temperature"], "top_p": p["sampling"]["top_p"],
                "context_tokens": p["context"], "prompt_tokens": p["prompt_target"],
                "max_output_tokens": p["max_out"]} if "sampling" in p else {}
        out[k] = {"name": name, "setting": setting, "label": f"{name} · {setting}", "model_id": p["model"],
                  "weights": weights, "reasoning_effort": p["effort"], "thinking": p.get("thinking"), **chat, **served}
    return out


def version(key: str, name: str, adds: str, does: str, folder: Path, tag: str,
            ms: dict) -> tuple[dict, dict[str, bytes]]:
    s = json.loads((folder / "summary.json").read_text())
    if s["layer"] != key:
        raise Mismatch(f"{folder}: layer {s['layer']}, expected {key}")
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        grades = [json.loads(x) for x in f if x.strip()]
    episodes = {g["episode"]: json.loads(gzip.decompress((folder / g["episode"]).read_bytes())) for g in grades}
    check(s, grades)
    rel = f"results/desk-{key}"
    models = [model_row(k, m, ms[k]) for k, m in s["models"].items()]
    models.sort(key=lambda m: -m["C"]["mean"])
    refs = [{"key": k, "short": short, "name": label, **{x: s["references"][k][x] for x in ("P", "C", "C_phys")}}
            for k, short, label in REFS if s["references"].get(k, {}).get("P", {}).get("mean") is not None]
    paired = [{"a": b["a"], "b": b["b"], **{x: b[x] for x in ("P", "R", "C") if x in b}} for b in s["paired"].values()]
    sites = sorted({(e["site"]["card"]["name"], e["site"]["card"]["region"], e["site"]["card"]["size"])
                    for e in episodes.values()})
    dates = sorted({e["dates"][0] for e in episodes.values()})
    v = {"version": key, "name": name, "role": "check" if key in CHECKS else "ladder", **CHECKS.get(key, {}),
         "adds": adds, "does": does, "ref": tag, "folder": rel, "pack": s["pack"],
         "n_tasks": s["n_tasks"], "n_days": s["n_days"], "dates": [dates[0], dates[-1]],
         "days_per_task": max(len(e["dates"]) for e in episodes.values()),
         "sites": [{"name": n, "region": r, "size": z} for n, r, z in sites], "eras": s["method"]["eras"],
         "budget": s["method"]["budget"], "core": s["method"]["core_versions"], "ci": s["ci"], "models": models,
         "references": refs, "paired": paired, "hero": s.get("hero"), "defects": defects(key, s),
         "deviations": deviations(key, s), "versus": s.get("versus"), "price_impact": s.get("price_impact"),
         "idle": IDLE.get(key),
         "sensitivity": sensitivity(key, s, grades, folder.parent.parent, models[0]["key"]),
         "block": s.get("block_name") or "day",
         "tasks": (tasks := captures(grades, episodes, NAMED.get(key, {}), s.get("block_alias") or {})),
         "days": days(tasks),
         "figures": {k: f"{rel}/figures/{f}" for k, f in (("bars", "p-bars.png"), ("bars_dark", "p-bars-dark.png"),
                                                         ("hero", "hero.png"), ("hero_dark", "hero-dark.png"))
                     if (folder / "figures" / f).is_file()},
         "github": f"{REPO}/tree/{tag}/{rel}"}
    hero = s.get("hero")
    if hero:
        g = next(g for g in grades if g["model"] == hero["model"] and g["task_id"] == hero["task_id"])
        v["story"] = story(episodes[g["episode"]], hero)
    rows = [run_row(key, s, g, episodes[g["episode"]], ms[g["model"]]) for g in grades]
    board = [board_row(key, s, m, v["days_per_task"], ms[m["key"]]) for m in models] + [
        ref_row(key, s, r, v["days_per_task"]) for r in refs]
    tasks = task_rows(key, folder.parent.parent, grades)
    files = {f"desk_leaderboard/{key}.parquet": parquet(board, LEADERBOARD),
             f"desk_runs/{key}.parquet": parquet(rows, RUNS), f"desk_tasks/{key}.parquet": parquet(tasks, TASKS)}
    v["rows"] = {"leaderboard": len(board), "runs": len(rows), "tasks": len(tasks)}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = f"{rel}/{path.relative_to(folder).as_posix()}"
        files[name] = relink(path.read_text(), rel, tag, folder).encode() if path.suffix == ".md" else path.read_bytes()
    return v, files


def captures(grades: list[dict], episodes: dict[str, dict], named: dict[str, str], alias: dict[str, str]) -> list[dict]:
    """Each task's hindsight capture C by model, as the grades give it, and of the real operator's replayed bids,
    (P_ref - P_idle) / (P_hind - P_idle), with its first operating day, the block its bootstrap draws it in (its day,
    or in v4 its front) and the named event (NAMED) that block is."""
    out = {}
    for g in sorted(grades, key=lambda g: (g["date"], g["site"])):
        first = episodes[g["episode"]]["dates"][0]
        block = alias.get(first, g["date"])
        t = out.setdefault(g["task_id"], {"task_id": g["task_id"], "date": first, "block": block, "site": g["site"],
                                          "C": {}})
        t["C"][g["model"]] = g["capture"]
        if g["p_operator_replay"] is not None:
            t["C"]["operator_replay"] = round((g["p_operator_replay"] - g["p_idle"]) / (g["p_hind"] - g["p_idle"]), 6)
        if name := named.get(block):
            t["named"] = name
    return list(out.values())


def days(tasks: list[dict]) -> list[dict]:
    """Each block's mean C over its tasks (the card's day-by-day charts), by model and for the operator's bids."""
    out = {}
    for t in tasks:
        b = out.setdefault(t["block"], {"block": t["block"], "n": 0, "C": {}} | (
            {"named": t["named"]} if t.get("named") else {}))
        b["n"] += 1
        for k, c in t["C"].items():
            b["C"].setdefault(k, []).append(c)
    return [b | {"C": {k: round(sum(cs) / len(cs), 6) for k, cs in b["C"].items()}}
            for b in sorted(out.values(), key=lambda b: b["block"])]


SUBMIT = {"submit_dam_offers": "DAM offers", "submit_rt_offers": "RT curves", "update_cop": "COP"}
READS = ("get_prices", "get_forecasts", "get_grid_conditions", "get_asset_status", "get_position", "check_submission")


def gif_info(v: dict, folder: Path, name: str, model: str, task: str, lead: bool) -> tuple[dict, dict]:
    """The desk hero GIF's link, alt text and caption, every number from the episode's grade in grades.jsonl.gz, and
    the episode it films."""
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        g = next(x for x in map(json.loads, f) if x["model"] == model and x["task_id"] == task)
    ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
    card = ep["site"]["card"]
    subs = [x for x in ep.get("submissions", []) if x["accepted"]]
    dam = [x for x in subs if x["tool"] == "submit_dam_offers"]
    rt = [x for x in subs if x["tool"] == "submit_rt_offers"]
    acted = [w for w in ep["wakes"] if w.get("turn") is not None]
    events = sum(any(r in ("notice", "nws", "outage", "deployment") for r in w["reasons"]) for w in acted)
    reasons = Counter("reminder" for w in acted if "reminder" in w["reasons"])
    calls = sum(len(t["calls"]) for t in ep["turns"])
    day, nd = date_label(ep["dates"]), len(ep["dates"])
    bid = len({x.get("day") for x in dam})
    acts = ([f"bids the day-ahead market at {clock_label(dam[0]['t'])} the day before" if nd == 1 else
             f"bids {COUNT.get(bid, bid)} day-ahead markets, the first at {clock_label(dam[0]['t'])} the day before"]
            if dam else [])
    acts += [f"sends {len(rt)} sets of real-time curves"] if rt else []
    why = [f"{events} for ERCOT notices, NWS alerts or outages"] if events else []
    why += [f"{reasons['reminder']} for its own reminders"] if reasons["reminder"] else []
    acts += [f"wakes {len(ep['turns'])} times" + (f", {' and '.join(why)}" if why else "")]
    op = g.get("p_operator_replay")
    link = replay(v["version"], model, task)
    caption = (f"GridSimEnv Desk, {v['version']}, {v['name']}: {name} trades {card['name']} ({card['region']}, "
               f"{card['size']}), a real ERCOT battery, {'on' if nd == 1 else 'over'} {day}, beside its {calls} tool "
               "calls. It "
               + ", ".join(acts[:-1]) + (" and " if len(acts) > 1 else "") + acts[-1]
               + f". The battery settles at {usd(g['p'])}, hindsight capture C "
               f"{g['capture']:.3f}" + (f"; the real operator's own bids, replayed, earn {usd(op)}" if op is not None
                                         else "") + f". [Replay it in the viewer]({link}). "
               "Data: ERCOT and NWS, public; not affiliated with or endorsed by ERCOT.")
    alt = (f"{name} at the desk of {card['name']} ({card['region']}, {card['size']}) {'on' if nd == 1 else 'over'} "
           f"{day}: the node's prices as "
           "they post, the battery's state of charge and dispatch, and each wake-up's tool calls with their results, "
           "then the settled grade")
    return {"version": v["version"], "model": model, "task_id": task, "lead": lead, "path": GIF,
            "link": link, "alt": alt, "caption": caption}, ep


def replay(version: str, model: str, task: str) -> str:
    return f"{APP}/index.html?v={version}&m={model}&task={task}"


def usd(x: float) -> str:
    v = f"{abs(x):,.0f}"
    return f"{'−' if x < 0 and v != '0' else ''}\u2060${v}"


COUNT = {1: "one", 2: "two", 3: "three", 4: "four"}


def date_label(dates: list[str]) -> str:
    a, b = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    return f"{a:%-d %B %Y}" if a == b else f"{a:%-d} to {b:%-d %B %Y}"


def clock_label(minute: int) -> str:
    return f"{(minute % 1440) // 60:02d}:{minute % 60:02d}"


def story(ep: dict, hero: dict) -> dict:
    """The hero episode's wake-ups for the article's desk-day chart: when the desk woke, why, and what it did."""
    turns = {t["turn"]: t for t in ep["turns"]}
    wakes = []
    for w in ep["wakes"]:
        t = turns.get(w.get("turn"))
        if t is None:
            continue
        subs = [x for x in ep.get("submissions", []) if x["t"] == t["t"]]
        wakes.append({"t": w["t"], "label": w["label"], "reasons": w["reasons"], "calls": len(t["calls"]),
                      "submitted": any(x["accepted"] for x in subs), "did": did(t, subs)})
    posted = [e["t_min"] for e in ep["events"] if e.get("kind") == "dam_results" and "t_min" in e]
    return {"model": hero["model"], "task_id": ep["task_id"], "label": hero["label"], "dates": ep["dates"],
            "start": min(w["t"] for w in ep["wakes"]), "end": 1440 * len(ep["dates"]), "dam_results": posted,
            "wakes": wakes}


def did(turn: dict, subs: list[dict]) -> str:
    acts = []
    for tool, what in SUBMIT.items():
        mine = [x for x in subs if x["tool"] == tool]
        if not mine:
            continue
        hrs = sorted({h for x in mine if x["accepted"] for h in x.get("hours") or []})
        rej = sum(not x["accepted"] for x in mine)
        acts.append(what + (f" HE{hrs[0]}–{hrs[-1]}" if hrs and tool != "update_cop" else "")
                    + (f", {rej} rejected" if rej else ""))
    n = Counter(c["tool"] for c in turn["calls"])
    acts = (["optimize"] if n["optimize"] else []) + acts + (["a reminder"] if n["set_reminder"] else [])
    reads = [k.removeprefix("get_").replace("_", " ") for k in READS if n[k]]
    return "; ".join(acts) or ("read " + ", ".join(reads) if reads else "no calls")


def check(s: dict, grades: list[dict]) -> None:
    """Each model's grades reproduce its summary row: the count, mean R, mean C over the rows that have one, mean P."""
    for k, m in s["models"].items():
        rows = [g for g in grades if g["model"] == k]
        caps = [g["capture"] for g in rows if g["capture"] is not None]
        got = {"n": len(rows), "R": sum(g["reward"] for g in rows) / len(rows), "C": sum(caps) / len(caps),
               "P": sum(g["p"] for g in rows) / len(rows)}
        want = {"n": m["n"], "R": m["R"]["mean"], "C": m["C"]["mean"], "P": m["P"]["mean"]}
        if got["n"] != want["n"] or any(abs(round(got[x], 4) - want[x]) > 1e-9 for x in ("R", "C", "P")):
            raise Mismatch(f"{s['layer']} {k}: grades give {got}, summary.json {want}")


def sensitivity(key: str, s: dict, grades: list[dict], repo: Path, top: str) -> dict | None:
    """The report's post-hoc check, with the desks that made more than half their total P in the block it leaves out
    (the report's own, else the block that made most of the top model's P, when that is more than half of it) and, of
    those, the ones whose statements show day-ahead sales bought back in real time there (the anchor's from the frozen
    refs the grades were replayed against). Means without that block, when the report gives none, are task means
    from the grades, without CIs."""
    sv = s.get("sensitivity")
    if not sv:
        return sv
    alias, first = s.get("block_alias") or {}, next(iter(s["models"]))
    p = {k: [(alias.get(g["date"], g["date"]), g["p"]) for g in grades if g["model"] == k] for k in s["models"]} | {
        k: [(alias.get(g["date"], g["date"]), g[f"p_{k}"]) for g in grades
            if g["model"] == first and g[f"p_{k}"] is not None]
        for k in ("anchor", "operator_replay", "operator_actual")}
    out = sv | {"block": s.get("block_name") or "day", "names": NAMED.get(key, {})}
    if sv.get("without"):
        days = set(sv["without"]["days"])
    else:
        tot = sum(x for _, x in p[top])
        best = max(sorted({d for d, _ in p[top]}), key=lambda b: sum(x for d, x in p[top] if d == b))
        if tot <= 0 or sum(x for d, x in p[top] if d == best) <= tot / 2:
            return out
        days, rest = {best}, {k: [x for d, x in xs if d != best] for k, xs in p.items()}
        out["derived"] = {"days": [best], "n_tasks": len(rest[top]), "means": {
            g: {k: {"P": {"mean": round(sum(rest[k]) / len(rest[k]), 4)}} for k in rest
                if (k in s["models"]) == (g == "models") and rest[k]} for g in ("models", "references")}}
    carried = [k for k, xs in p.items() if xs and (t := sum(x for _, x in xs)) > 0
               and sum(x for d, x in xs if d in days) > t / 2]
    lines = {k: [g["lines"] for g in grades if g["model"] == k and alias.get(g["date"], g["date"]) in days]
             for k in s["models"]}
    refs = repo / ((s.get("regraded") or {}).get("refs") or "-")
    if refs.is_file():
        with open(refs) as f:
            lines["anchor"] = [day["lines"] for r in map(json.loads, filter(str.strip, f))
                               for d, day in r["refs"]["anchor"]["statement"]["days"].items() if d in days]
    sold = {k: (sum(x.get("dam_energy", 0.0) for x in xs), sum(x.get("rt_energy_imbalance", 0.0) for x in xs))
            for k, xs in lines.items()}
    return out | {"carried": carried, "bought_back": [k for k in carried if k in sold and sold[k][0] > 0
                                                     and sold[k][1] < -0.1 * sold[k][0]]} | (
        {"why_short": WHY[key]} if key in WHY else {})


KNOWN = (("empty `as_offers` list", "an empty `as_offers` list drew a spurious ASO-02 note while the energy curves in "
                                    "the same call were accepted, so the reserve figures leave those calls out of the "
                                    "refused offers"),)


LOGGED = (("Qwen3-4B sharding",
           "the Qwen3-4B task lists were set wrong, so its four winter storm Fern windows ran late as a fill-in on the "
           "same frozen code and four other windows ran twice; the runs on the planned host are scored, under a rule "
           "set before any duplicate was read"),
          ("began before the v5 pilot was checked",
           "the Qwen3-4B runs began before the v5 pilot was checked (the pilot passed)"),
          ("The same task-list error as v4",
           "as in v4, six Qwen3-4B tasks ran late as a fill-in on the same frozen code and six ran on two hosts; the "
           "runs on the planned host are scored, under a rule set before any duplicate was read"))


def deviations(key: str, s: dict) -> str | None:
    """The report's logged deviations from the pre-registration, in the words every surface uses."""
    out = []
    for d in s.get("deviations") or []:
        said = [t for k, t in LOGGED if k in d]
        if not said:
            raise Mismatch(f"desk-{key} logs a deviation the hub does not describe yet: {d}")
        out += said
    if not out:
        return None
    return f"Logged deviation{'s' if len(out) > 1 else ''} from the pre-registration: {'; '.join(out)}."


def defects(key: str, s: dict) -> str | None:
    """The report's known env defects, in the words every surface uses; one this script has no words for stops it."""
    out = []
    for d in s.get("defects") or []:
        said = [t for k, t in KNOWN if k in d]
        if not said:
            raise Mismatch(f"desk-{key} lists an env defect the hub does not describe yet: {d}")
        out += said
    return f"Known env defect, frozen for {key} and fixed after it: {'; '.join(out)}." if out else None


def model_row(k: str, m: dict, preset: dict) -> dict:
    pol = m["policy"]
    if (pol.get("model"), pol.get("effort")) != (preset["model_id"], preset["reasoning_effort"]):
        raise Mismatch(f"{k}: the runs recorded {pol.get('model')} at effort {pol.get('effort')}, the runner's "
                       f"preset is {preset['model_id']} at {preset['reasoning_effort']}")
    return {"key": k, "name": preset["name"], "model_id": pol.get("model"), "effort": pol.get("effort"),
            "weights": preset["weights"], "n": m["n"], "days": m["days"], "valid": m["valid_share"], "C": m["C"],
            "C_phys": m["C_phys"], "R": m["R"], "P": m["P"], "P_minus_anchor": m["P_minus_anchor"],
            "beats_anchor": m["beats_anchor_share"], "P_minus_operator_replay": m["P_minus_operator_replay"],
            "P_minus_operator_actual": m["P_minus_operator_actual"], "lines": m["lines"],
            "usd_per_episode": m["cost_usd"]["per_episode"], "usd_total": m["cost_usd"]["total_all_attempts"],
            "turns": m["turns"], "wakes": m["wakes"], "calls": m["calls"], "calls_by_tool": m["calls_by_tool"],
            "ancillary": m.get("ancillary"), "submissions_by_day": m.get("submissions_by_day"),
            "accepted": m["submissions"]["accepted"], "rejected": m["submissions"]["rejected"],
            "rejected_codes": m["submissions"]["rejected_codes_total"], "reminders": m["reminders"],
            "cycles": m["cycles"], "tokens": m["tokens"]}


def task_rows(key: str, repo: Path, grades: list[dict]) -> list[dict]:
    """Every task of the version's pilot, eval and tune packs, by its anonymous site card, with the references it was
    graded against: the frozen refs file where the report replayed against one, else the pack's own rows. The eval
    rows must carry exactly the references in the grades."""
    out = []
    for role in ROLES:
        pack = f"desk-{key}-{role}"
        if not (repo / "data/desk" / pack / "tasks.jsonl.gz").is_file():
            continue
        with gzip.open(repo / "data/desk" / pack / "tasks.jsonl.gz", "rt") as f:
            tasks = [json.loads(x) for x in f if x.strip()]
        frozen = repo / "results/desk-refs" / pack / "refs.jsonl"
        refs = ({r["task_id"]: r["refs"] for r in map(json.loads, filter(str.strip, frozen.read_text().splitlines()))}
                if frozen.is_file() else {t["task_id"]: t["refs"] for t in tasks})
        for t in tasks:
            site, tags, r = t["site"], t["tags"], refs[t["task_id"]]
            out.append({
                "version": key, "pack": pack, "role": role, "task_id": t["task_id"], "era": t["era"],
                "dates": t["dates"], "days": len(t["dates"]), "site": site["card"]["name"],
                "region": site["card"]["region"], "battery": site["card"]["size"], "hsl_mw": site["hsl_mw"],
                "e_max_mwh": site["e_max_mwh"], "round_trip_efficiency": site["rte"],
                "standby_loss_pct_per_h": site["standby_loss_pct_per_h"],
                "degradation_usd_per_mwh": site["deg_usd_per_mwh"],
                "warranty_cycles_per_day": site["warranty_cycles_per_day"], "soc0_mwh": site["soc0_mwh"],
                "pv_mw_ac": (site.get("pv") or {}).get("mw_ac"), "operator_disclosed": t["operator_ok"],
                "season": tags["season"], "day_kind": tags["day_kind"], "notices": tags["notices"],
                "deployments": tags.get("deployments"), "max_rt_lmp": tags["max_rt_lmp"],
                "min_rt_lmp": tags["min_rt_lmp"], "negative_lmp_intervals": tags["neg_lmp_intervals"],
                "dam_spread": tags["dam_spread"], "max_dam_mcpc": tags.get("max_dam_mcpc"),
                "max_rt_mcpc": tags.get("max_rt_mcpc"), **{x: r[x] for x in GRADED}, "floored": r["floored"],
                "anchor_risk": r["anchor_setting"]["risk"], "anchor_dam_position": r["anchor_setting"]["dam_position"],
                "core_version": r.get("core_version")})
    first = next(iter({g["model"] for g in grades}))
    by_id = {x["task_id"]: x for x in out if x["role"] == "eval"}
    for g in (g for g in grades if g["model"] == first):
        row = by_id.get(g["task_id"])
        if row is None or any(abs((g[x] or 0.0) - (row[x] or 0.0)) > 0.005 or (g[x] is None) != (row[x] is None)
                              for x in GRADED):
            raise Mismatch(f"desk-{key}: {g['task_id']}'s grade references differ from desk_tasks")
    return out


def board_row(key: str, s: dict, m: dict, dpt: int, preset: dict) -> dict:
    return common(key, s, dpt) | {
        "type": "model", "key": m["key"], "name": m["name"], "model_id": m["model_id"], "effort": m["effort"],
        "reasoning_effort": preset["reasoning_effort"], "thinking": preset["thinking"], "weights": m["weights"],
        "valid": m["valid"], **band("capture", m["C"]), **band("reward", m["R"]),
        **band("p_usd", m["P"]), **band("p_minus_anchor_usd", m["P_minus_anchor"]),
        **band("p_minus_operator_replay_usd", m["P_minus_operator_replay"]),
        **band("p_minus_operator_actual_usd", m["P_minus_operator_actual"]), "capture_phys": m["C_phys"]["mean"],
        "beats_anchor": m["beats_anchor"], "usd_per_episode": m["usd_per_episode"], "turns": m["turns"],
        "calls": m["calls"], "submissions_accepted": m["accepted"], "submissions_rejected": m["rejected"],
        "reminders": m["reminders"], "cycles": m["cycles"]}


def ref_row(key: str, s: dict, r: dict, dpt: int) -> dict:
    return common(key, s, dpt) | {"type": "reference", "key": r["key"], "name": r["name"], **band("capture", r["C"]),
                             **band("p_usd", r["P"]), "capture_phys": r["C_phys"]["mean"]}


def common(key: str, s: dict, dpt: int) -> dict:
    return {"version": key, "pack": s["pack"], "tasks": s["n_tasks"], "days_per_task": dpt,
            "operating_days": s["n_days"], "source": f"results/desk-{key}"}


def band(name: str, b: dict) -> dict:
    return {name: b["mean"], f"{name}_ci_low": b["ci"][0], f"{name}_ci_high": b["ci"][1]}


def run_row(key: str, s: dict, g: dict, ep: dict, preset: dict) -> dict:
    pol, u, card = ep["policy"], g["usage"], ep["site"]["card"]
    return {"version": key, "pack": s["pack"], "model": g["model"], "name": preset["name"],
            "model_id": pol.get("model"), "effort": pol.get("effort"), "reasoning_effort": preset["reasoning_effort"],
            "thinking": preset["thinking"], "task_id": g["task_id"], "date": g["date"], "site": g["site"],
            "region": card["region"], "battery": card["size"], "era": ep["era"], "status": g["status"],
            "valid": g["valid"], "capture": g["capture"], "capture_phys": g["capture_phys"], "reward": g["reward"],
            "stretch": g["stretch"], "floored": g.get("floored"), "beats_anchor": g["beats_anchor"], "p_usd": g["p"],
            **{x: g[x] for x in ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay",
                                 "p_operator_actual")},
            **{f"{x}_usd": g["lines"].get(x) for x in LINES}, "lines": json.dumps(g["lines"]),
            "turns": u.get("turns"), "calls": u.get("calls"), "submissions": g["submissions"],
            "rejected": g["rejected"], **{x: u.get(x) for x in ("input_tokens", "output_tokens", "cached_tokens")},
            "usd": u.get("cost_usd"), "wall_seconds": u.get("wall_s"), "episode": f"results/desk-{key}/{g['episode']}"}


def parquet(rows: list[dict], schema: pa.Schema) -> bytes:
    sink = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([{f.name: r.get(f.name) for f in schema} for r in rows], schema=schema), sink,
                   compression="zstd")
    return sink.getvalue()


LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")


def relink(text: str, rel: str, tag: str, folder: Path) -> str:
    """A version's README as the dataset shows it: its own files point into the dataset, anything else to the plugin
    on GitHub at the version's results tag."""
    def fix(m: re.Match) -> str:
        bang, label, target = m[1], m[2], m[3]
        if re.match(r"[a-z]+:|#", target):
            return m[0]
        path = posixpath.normpath(posixpath.join(rel, target))
        local = folder / posixpath.relpath(path, rel)
        if path.startswith(rel + "/") and local.exists():
            url = f"{DATASET}/{'resolve' if bang else 'tree' if local.is_dir() else 'blob'}/main/{path}"
        else:
            url = f"{REPO}/blob/{tag}/{path}"
        return f"{bang}[{label}]({url})"
    return LINK.sub(fix, text)


def figures(space: Path, versions: list[str], hr) -> dict[str, bytes]:
    """Each version's capture and dollars charts as the desk page draws them, 640 px wide at twice that, and the card's
    own charts (hub/desk-charts: capture across versions and each version's day by day) as standalone SVG with the
    font embedded, which the card prints, at its width and in a phone layout, and the former also at twice its width
    as PNG; all bare on a transparent background in the light and dark themes, each theme's text halo the Hub page's
    colour."""
    out = {}
    with hr.browser(space, None) as (page, base):
        for v in versions:
            page.call("Emulation.setDeviceMetricsOverride", width=640, height=900, deviceScaleFactor=2, mobile=False)
            page.call("Page.navigate", url=f"{base}/desk.html?export=1&v={v}")
            page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.deskReady ? r() : "
                    "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
            page.js("document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 400)))")
            page.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            for suffix, theme, hub_bg in hr.THEMES:
                page.js(hr.BARE % (theme, hub_bg))
                for b in page.js(hr.BOXES):
                    path = BUILD / "figures" / f"desk-{v}-{b['id']}{suffix}.png"
                    hr.shot(page, path, {k: b[k] for k in ("x", "y", "width", "height")})
                    out[f"assets/figures/{path.name}"] = path.read_bytes()
            page.call("Emulation.setDefaultBackgroundColorOverride")
        page.call("Emulation.setDeviceMetricsOverride", width=640, height=900, deviceScaleFactor=2, mobile=False)
        page.call("Page.navigate", url=f"{base}/charts.html")
        page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.chartsReady ? r() : "
                "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
        page.js("document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 400)))")
        page.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
        for suffix, theme, hub_bg in hr.THEMES:
            page.js(f"document.documentElement.dataset.theme = '{theme}'; "
                    f"document.documentElement.style.setProperty('--halo', '{hub_bg}')")
            for b in page.js(hr.BOXES):
                if b["id"].endswith("-phone"):
                    continue
                path = BUILD / "figures" / f"{b['id']}{suffix}.png"
                hr.shot(page, path, {k: b[k] for k in ("x", "y", "width", "height")})
                out[f"assets/figures/{path.name}"] = path.read_bytes()
            for name, svg in page.js("chartsSvg()").items():
                out[f"assets/figures/{name}{suffix}.svg"] = svg.encode()
        page.call("Emulation.setDefaultBackgroundColorOverride")
    return out


BRANDS = ("Jupiter", "Habitat", "Tenaska", "Callisto", "Wigeon", "Wolf Tank")


def names(repo: Path) -> list[str]:
    """The desk's real resources, nodes, QSEs and plants (design decision D9 keeps them off every public surface): from
    every desk pack's site records and the ESR registry's rows for those sites, with the operators' brand names."""
    sites = {}
    for f in (repo / "data/desk").glob("*/tasks.jsonl.gz"):
        with gzip.open(f, "rt") as g:
            for t in map(json.loads, filter(str.strip, g)):
                sites[t["site"]["resource"]] = t["site"]
    reg = {r["resource_name"]: r for r in pq.read_table(repo / "data/desk/sites.parquet").to_pylist()}
    out = set(BRANDS)
    for res, site in sites.items():
        if res.startswith("FIXTURE"):
            continue
        r = reg.get(res, {})
        out |= {res, site["settlement_point"], *(site.get("resource_pre") or {}).values(), res.split("_")[0]}
        out |= {r.get(k) for k in ("qse", "dme", "pre_qse", "cdr_name", "pre_gen_resource", "pre_load_resource")}
    return sorted(x for x in out if x)


def anonymous(files: dict[str, bytes], terms: list[str]) -> None:
    """Short upper-case codes (CLO, WIG) match as written, so a word cut short in a note ('clo…') is not a hit."""
    code = lambda t: len(t) <= 4 and t.isupper()  # noqa: E731
    any_case = "|".join(rf"\b{re.escape(t)}\b" for t in sorted(terms, key=len, reverse=True) if not code(t))
    pat = re.compile("|".join(filter(None, [rf"(?i:{any_case})" if any_case else "", *(
        rf"\b{re.escape(t)}\b" for t in terms if code(t))])))
    for path, content in files.items():
        if path.endswith(".png"):
            continue
        text = (json.dumps(pq.read_table(io.BytesIO(content)).to_pylist(), ensure_ascii=False, default=str)
                if path.endswith(".parquet") else gzip.decompress(content).decode() if path.endswith(".gz")
                else content.decode())
        if hit := pat.search(text):
            raise SystemExit(f"{path} names {hit[0]!r}, a real site or operator; nothing was published")
    print(f"anonymity: {len(files)} files clean of {len(terms)} real site and operator names")


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    main()
