"""The desk on the Hub: results/overview/desk.json (read by the Space's desk page, the card's desk section and the
article's desk chapter), the dataset's desk_leaderboard and desk_runs configs and its results/desk-v<N>/ folders, from
the result folders scripts/desk_report.py writes on the desk branch. Each version's grades are checked against its
summary.json before anything is written, and links to its files on GitHub pin the version's results tag.

    .venv/bin/python scripts/hub_desk.py --desk ~/gridsim-desk/results --ref v2=desk-v2-results
    .venv/bin/python scripts/hub_desk.py --desk ~/gridsim-desk/results --ref v2=desk-v2-results --publish
"""

import argparse
import gzip
import importlib.util
import io
import json
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
MODELS = {"sol": ("GPT-6.1 Sol", "API"), "luna": ("GPT-6 Luna", "API"), "qwen": ("Qwen3-4B", "open")}
REFS = (("anchor", "Anchor", "Anchor: the desk's optimiser at every wake, same information"),
        ("operator_replay", "The operator's bids, replayed", "The real operator's disclosed bids, replayed"),
        ("operator_actual", "The operator, as settled", "The real operator's awards and metered output, settled"),
        ("hind_phys", "Hindsight, DAM tied to dispatch", "Hindsight optimum, DAM position tied to dispatch"),
        ("hind", "Hindsight optimum", "Hindsight optimum"), ("idle", "Idle", "Idle"))
LINES = ("dam_energy", "rt_energy_imbalance", "deviation", "load_allocated", "degradation", "warranty_overage",
         "end_soc_shortfall")
F64, I64, STR, BOOL = pa.float64(), pa.int64(), pa.string(), pa.bool_()
LEADERBOARD = pa.schema([
    ("version", STR), ("pack", STR), ("type", STR), ("key", STR), ("name", STR), ("model_id", STR), ("effort", STR),
    ("weights", STR), ("battery_days", I64), ("operating_days", I64), ("valid", F64),
    *((f"{m}{s}", F64) for m in ("capture", "reward", "p_usd", "p_minus_anchor_usd", "p_minus_operator_replay_usd",
                                  "p_minus_operator_actual_usd") for s in ("", "_ci_low", "_ci_high")),
    ("capture_phys", F64), ("beats_anchor", F64), ("usd_per_episode", F64), ("turns", F64), ("calls", F64),
    ("submissions_accepted", F64), ("submissions_rejected", F64), ("reminders", F64), ("cycles", F64),
    ("source", STR),
])
RUNS = pa.schema([
    ("version", STR), ("pack", STR), ("model", STR), ("name", STR), ("model_id", STR), ("effort", STR),
    ("task_id", STR), ("date", STR), ("site", STR), ("region", STR), ("battery", STR), ("era", STR), ("status", STR),
    ("valid", BOOL), ("capture", F64), ("capture_phys", F64), ("reward", F64), ("stretch", F64), ("floored", BOOL),
    ("beats_anchor", BOOL), ("p_usd", F64), ("p_idle", F64), ("p_anchor", F64), ("p_hind", F64), ("p_hind_phys", F64),
    ("p_operator_replay", F64), ("p_operator_actual", F64), *((f"{x}_usd", F64) for x in LINES), ("lines", STR),
    ("turns", I64), ("calls", I64), ("submissions", I64), ("rejected", I64), ("input_tokens", I64),
    ("output_tokens", I64), ("cached_tokens", I64), ("usd", F64), ("wall_seconds", F64), ("episode", STR),
])


class Mismatch(Exception):
    pass


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--desk", type=Path, default=ROOT / "results", help="The folder holding desk-v<N>/ results.")
    ap.add_argument("--ref", action="append", default=[], metavar="vN=TAG",
                    help="The git tag of a version's results commit on the desk branch; its GitHub links pin it.")
    ap.add_argument("--results", type=Path, default=ROOT / "results",
                    help="Where overview/desk.json goes, beside overview/results.json; the card is built from both.")
    ap.add_argument("--gif", type=Path, help="The newest version's desk hero GIF (scripts/hub_desk_hero.py).")
    ap.add_argument("--gif-task", help="The task id of the episode the GIF films.")
    ap.add_argument("--gif-model", default="sol", help="The model whose episode the GIF films.")
    ap.add_argument("--lead", action="store_true", help="The desk GIF leads the card; else it opens the desk section.")
    ap.add_argument("--publish", action="store_true", help="Upload to the dataset and the Space.")
    args = ap.parse_args()
    refs = dict(x.split("=", 1) for x in args.ref)
    desk, files = build(args.desk, refs)
    if args.gif:
        v = desk["versions"][-1]
        desk["gif"] = gif_info(v, args.desk / f"desk-{v['version']}", args.gif_model, args.gif_task, args.lead)
        files[GIF] = args.gif.read_bytes()
    out = args.results / "overview" / "desk.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(desk, indent=1, ensure_ascii=False) + "\n")
    hr = module("hub_results", "scripts/hub_results.py")
    hd = module("hub_dataset", "scripts/hub_dataset.py")
    sp = space_files(desk)
    space = BUILD / "space"
    shutil.rmtree(space, ignore_errors=True)
    for k, v in (sp | {n: (WEB / n).read_bytes() for n in ("board.css", "results.css")}).items():
        (space / k).parent.mkdir(parents=True, exist_ok=True)
        (space / k).write_bytes(v)
    figs = figures(space, [v["version"] for v in desk["versions"]], hr)
    card = hd.card_only(args.results)
    ds = files | figs | {"README.md": card.encode(), "results/overview/desk.json": out.read_bytes()}
    hr.leaks({k: v for k, v in ds.items() if k != GIF} | {f"space/{k}": v for k, v in sp.items()})
    dataset = BUILD / "dataset"
    shutil.rmtree(dataset, ignore_errors=True)
    for k, v in ds.items():
        (dataset / k).parent.mkdir(parents=True, exist_ok=True)
        (dataset / k).write_bytes(v)
    for name, fs, where in (("dataset", ds, dataset), ("space", sp, space)):
        print(f"{name}: {len(fs)} files, {sum(map(len, fs.values())) / 1e6:.2f} MB in {where}")
    for v in desk["versions"]:
        print(f"{v['version']} {v['pack']}: " + ", ".join(f"{m['name']} C {m['C']['mean']}" for m in v["models"]))
    if args.publish:
        done = ", ".join(v["version"] for v in desk["versions"])
        print("dataset:", hr.publish("dataset", ds, f"The desk: {done} results, desk_leaderboard and desk_runs"))
        print("space:", hr.publish("space", sp, f"The desk page: {done} results"))


def build(desk_dir: Path, refs: dict[str, str]) -> tuple[dict, dict[str, bytes]]:
    versions, files = [], {}
    for key, name, adds, does in LADDER:
        folder = desk_dir / f"desk-{key}"
        if not (folder / "summary.json").is_file():
            continue
        if key not in refs:
            raise SystemExit(f"--ref {key}=TAG: the results tag that {folder} was committed under")
        v, fs = version(key, name, adds, does, folder, refs[key])
        versions.append(v)
        files |= fs
    ladder = [{"version": k, "name": n, "adds": a, "does": d, "status": "results" if any(
        v["version"] == k for v in versions) else "next"} for k, n, a, d in LADDER]
    return {"schema": "gridsim.desk.hub/v1", "ladder": ladder, "versions": versions}, files


def version(key: str, name: str, adds: str, does: str, folder: Path, tag: str) -> tuple[dict, dict[str, bytes]]:
    s = json.loads((folder / "summary.json").read_text())
    if s["layer"] != key:
        raise Mismatch(f"{folder}: layer {s['layer']}, expected {key}")
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        grades = [json.loads(x) for x in f if x.strip()]
    episodes = {g["episode"]: json.loads(gzip.decompress((folder / g["episode"]).read_bytes())) for g in grades}
    check(s, grades)
    rel = f"results/desk-{key}"
    models = [model_row(k, m) for k, m in s["models"].items()]
    models.sort(key=lambda m: -m["C"]["mean"])
    refs = [{"key": k, "short": short, "name": label, **{x: s["references"][k][x] for x in ("P", "C", "C_phys")}}
            for k, short, label in REFS if s["references"].get(k, {}).get("P", {}).get("mean") is not None]
    paired = [{"a": b["a"], "b": b["b"], **{x: b[x] for x in ("P", "R", "C") if x in b}} for b in s["paired"].values()]
    sites = sorted({(e["site"]["card"]["name"], e["site"]["card"]["region"], e["site"]["card"]["size"])
                    for e in episodes.values()})
    dates = sorted({e["dates"][0] for e in episodes.values()})
    v = {"version": key, "name": name, "adds": adds, "does": does, "ref": tag, "folder": rel, "pack": s["pack"],
         "n_tasks": s["n_tasks"], "n_days": s["n_days"], "dates": [dates[0], dates[-1]],
         "sites": [{"name": n, "region": r, "size": z} for n, r, z in sites], "eras": s["method"]["eras"],
         "budget": s["method"]["budget"], "core": s["method"]["core_versions"], "ci": s["ci"], "models": models,
         "references": refs, "paired": paired, "hero": s.get("hero"),
         "figures": {k: f"{rel}/figures/{f}" for k, f in (("bars", "p-bars.png"), ("bars_dark", "p-bars-dark.png"),
                                                         ("hero", "hero.png"), ("hero_dark", "hero-dark.png"))
                     if (folder / "figures" / f).is_file()},
         "github": f"{REPO}/tree/{tag}/{rel}"}
    hero = s.get("hero")
    if hero:
        g = next(g for g in grades if g["model"] == hero["model"] and g["task_id"] == hero["task_id"])
        v["story"] = story(episodes[g["episode"]], hero)
    rows = [run_row(key, s, g, episodes[g["episode"]]) for g in grades]
    board = [board_row(key, s, m) for m in models] + [ref_row(key, s, r) for r in refs]
    files = {f"desk_leaderboard/{key}.parquet": parquet(board, LEADERBOARD),
             f"desk_runs/{key}.parquet": parquet(rows, RUNS)}
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        name = f"{rel}/{path.relative_to(folder).as_posix()}"
        files[name] = relink(path.read_text(), rel, tag, folder).encode() if path.suffix == ".md" else path.read_bytes()
    return v, files


SUBMIT = {"submit_dam_offers": "DAM offers", "submit_rt_offers": "RT curves", "update_cop": "COP"}
READS = ("get_prices", "get_forecasts", "get_grid_conditions", "get_asset_status", "get_position", "check_submission")


def gif_info(v: dict, folder: Path, model: str, task: str, lead: bool) -> dict:
    """The desk hero GIF's link, alt text and caption, every number from the episode's grade in grades.jsonl.gz."""
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        g = next(x for x in map(json.loads, f) if x["model"] == model and x["task_id"] == task)
    ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
    card, name = ep["site"]["card"], MODELS.get(model, (model, None))[0]
    subs = [x for x in ep.get("submissions", []) if x["accepted"]]
    dam = [x for x in subs if x["tool"] == "submit_dam_offers"]
    rt = [x for x in subs if x["tool"] == "submit_rt_offers"]
    acted = [w for w in ep["wakes"] if w.get("turn") is not None]
    events = sum(any(r in ("notice", "nws", "outage", "deployment") for r in w["reasons"]) for w in acted)
    reasons = Counter("reminder" for w in acted if "reminder" in w["reasons"])
    calls = sum(len(t["calls"]) for t in ep["turns"])
    day = date_label(ep["dates"])
    acts = ([f"bids the day-ahead market at {clock_label(dam[0]['t'])} the day before"] if dam else [])
    acts += [f"sends {len(rt)} sets of real-time curves"] if rt else []
    why = [f"{events} for ERCOT notices, NWS alerts or outages"] if events else []
    why += [f"{reasons['reminder']} for its own reminders"] if reasons["reminder"] else []
    acts += [f"wakes {len(ep['turns'])} times" + (f", {' and '.join(why)}" if why else "")]
    op = g.get("p_operator_replay")
    caption = (f"GridSimEnv Desk, {v['version']}, {v['name']}: {name} trades {card['name']} ({card['region']}, "
               f"{card['size']}), a real ERCOT battery, on {day}, beside its {calls} tool calls. It "
               + ", ".join(acts[:-1]) + (" and " if len(acts) > 1 else "") + acts[-1]
               + f". The battery settles at {usd(g['p'])}, hindsight capture C "
               f"{g['capture']:.3f}" + (f"; the real operator's own bids, replayed, earn {usd(op)}" if op is not None
                                         else "") + f". [Open the desk page]({APP}/desk.html?v={v['version']}). "
               "Data: ERCOT and NWS, public; not affiliated with or endorsed by ERCOT.")
    alt = (f"{name} at the desk of {card['name']} ({card['region']}, {card['size']}) on {day}: the node's prices as "
           "they post, the battery's state of charge and dispatch, and each wake-up's tool calls with their results, "
           "then the settled grade")
    return {"version": v["version"], "model": model, "task_id": task, "lead": lead, "path": GIF,
            "link": f"{APP}/desk.html?v={v['version']}", "alt": alt, "caption": caption}


def usd(x: float) -> str:
    return f"{'−' if x < 0 else ''}\u2060${abs(x):,.0f}"


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
            "wakes": wakes, "grade": {k: ep["grade"].get(k) for k in ("p", "capture", "p_anchor", "p_hind")}}


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


def model_row(k: str, m: dict) -> dict:
    name, weights = MODELS.get(k, (k, None))
    pol = m["policy"]
    return {"key": k, "name": name, "model_id": pol.get("model"), "effort": pol.get("effort"), "weights": weights,
            "n": m["n"], "days": m["days"], "valid": m["valid_share"], "C": m["C"], "C_phys": m["C_phys"],
            "R": m["R"], "P": m["P"], "P_minus_anchor": m["P_minus_anchor"], "beats_anchor": m["beats_anchor_share"],
            "P_minus_operator_replay": m["P_minus_operator_replay"],
            "P_minus_operator_actual": m["P_minus_operator_actual"], "lines": m["lines"],
            "usd_per_episode": m["cost_usd"]["per_episode"], "usd_total": m["cost_usd"]["total_all_attempts"],
            "turns": m["turns"], "wakes": m["wakes"], "calls": m["calls"], "calls_by_tool": m["calls_by_tool"],
            "accepted": m["submissions"]["accepted"], "rejected": m["submissions"]["rejected"],
            "rejected_codes": m["submissions"]["rejected_codes_total"], "reminders": m["reminders"],
            "cycles": m["cycles"], "tokens": m["tokens"]}


def board_row(key: str, s: dict, m: dict) -> dict:
    return common(key, s) | {
        "type": "model", "key": m["key"], "name": m["name"], "model_id": m["model_id"], "effort": m["effort"],
        "weights": m["weights"], "valid": m["valid"], **band("capture", m["C"]), **band("reward", m["R"]),
        **band("p_usd", m["P"]), **band("p_minus_anchor_usd", m["P_minus_anchor"]),
        **band("p_minus_operator_replay_usd", m["P_minus_operator_replay"]),
        **band("p_minus_operator_actual_usd", m["P_minus_operator_actual"]), "capture_phys": m["C_phys"]["mean"],
        "beats_anchor": m["beats_anchor"], "usd_per_episode": m["usd_per_episode"], "turns": m["turns"],
        "calls": m["calls"], "submissions_accepted": m["accepted"], "submissions_rejected": m["rejected"],
        "reminders": m["reminders"], "cycles": m["cycles"]}


def ref_row(key: str, s: dict, r: dict) -> dict:
    return common(key, s) | {"type": "reference", "key": r["key"], "name": r["name"], **band("capture", r["C"]),
                             **band("p_usd", r["P"]), "capture_phys": r["C_phys"]["mean"]}


def common(key: str, s: dict) -> dict:
    return {"version": key, "pack": s["pack"], "battery_days": s["n_tasks"], "operating_days": s["n_days"],
            "source": f"results/desk-{key}"}


def band(name: str, b: dict) -> dict:
    return {name: b["mean"], f"{name}_ci_low": b["ci"][0], f"{name}_ci_high": b["ci"][1]}


def run_row(key: str, s: dict, g: dict, ep: dict) -> dict:
    name, _ = MODELS.get(g["model"], (g["model"], None))
    pol, u, card = ep["policy"], g["usage"], ep["site"]["card"]
    return {"version": key, "pack": s["pack"], "model": g["model"], "name": name, "model_id": pol.get("model"),
            "effort": pol.get("effort"), "task_id": g["task_id"], "date": g["date"], "site": g["site"],
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


def space_files(desk: dict) -> dict[str, bytes]:
    names = ("desk.html", "desk.js", "desk.css", "results.html", "board.html", "index.html")
    return {n: (WEB / n).read_bytes() for n in names} | {"desk.json": json.dumps(
        desk, ensure_ascii=False, separators=(",", ":")).encode()}


def figures(space: Path, versions: list[str], hr) -> dict[str, bytes]:
    """Each version's capture and dollars charts as the desk page draws them, 640 px wide at twice that, bare on a
    transparent background in the page's light and dark themes, each theme's text halo the Hub page's colour."""
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
    return out


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == "__main__":
    main()
