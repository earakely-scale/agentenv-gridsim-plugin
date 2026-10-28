"""What training bought, in dollars: the results page on the Space, its figures on the dataset card, and the result
folders under the dataset's results/. Every number comes from a committed summary, or from committed per-task records
re-graded with gridsim_core and bootstrapped with report_blind's day-block resampler, and is checked against the
summary that reports it.

    .venv/bin/python scripts/hub_results.py              # results/overview/ and build/hub/results/, nothing uploaded
    .venv/bin/python scripts/hub_results.py --publish    # then upload to the dataset and the Space

Beam's records are read from results/beam-agent/beam/ (or --beam DIR); each effort joins the frontier once all its
tasks are there. The figures are the page's own charts, captured in headless Chrome at twice their pixel size.
"""

import argparse
import base64
import gzip
import hashlib
import importlib.util
import json
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
from agentenv_hf.scan import known_values, scan
from huggingface_hub import CommitOperationAdd, HfApi, hf_hub_download

from gridsim_core.grade import reward_value

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "results" / "overview"
BUILD = ROOT / "build" / "hub" / "results"
WEB = ROOT / "src" / "agentenv_gridsim" / "web"
HF = "earakely-scale/GridSimEnv-AgentEnv"
DATASET = f"https://huggingface.co/datasets/{HF}"
APP = "https://earakely-scale-gridsimenv-agentenv.static.hf.space"
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
TB, T3, CM, EC = "results/train/4b-blind", "results/train/4b-dpa", "results/cost-matched", "results/economics"
EFFORTS = ("low", "medium", "high", "max")
READ: dict[str, str] = {}


def load(rel: str) -> dict:
    READ.setdefault(rel, hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12])
    return json.loads((ROOT / rel).read_text())


def text(rel: str) -> str:
    READ.setdefault(rel, hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12])
    return (ROOT / rel).read_text()


def records(path: Path) -> dict:
    rel = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else path.as_posix()
    READ.setdefault(rel, hashlib.sha256(path.read_bytes()).hexdigest()[:12])
    with gzip.open(path, "rt") if path.suffix == ".gz" else open(path) as f:
        return {r["task_id"]: r for r in map(json.loads, filter(str.strip, f))}


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RB = module("report_blind", f"{TB}/scripts/report_blind.py")


def same(got: float, want: float, what: str, tol: float = 5e-5) -> None:
    if abs(got - want) > tol:
        raise SystemExit(f"{what}: computed {got:.6f}, the committed summary says {want:.6f}")


def r4(x: float) -> float:
    return round(float(x), 4)


def h(x: float, nd: int = 3, sign: bool = False) -> str:
    """Half-up, as the READMEs print the stored four-decimal values; a true minus sign."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP)
    return (f"{q:+}" if sign else f"{q}").replace("-", "−")


def ci(c: list[float], nd: int = 3, sign: bool = False) -> str:
    return f"[{h(c[0], nd, sign)}, {h(c[1], nd, sign)}]"


def gap(g: dict) -> dict:
    return {"mean": r4(g["mean"]), "ci": [r4(v) for v in (g.get("ci") or g["ci95"])],
            **{k: g[k] for k in ("ahead", "level", "days_ahead", "win_rate", "tie_rate") if k in g}}


def level(v: dict, **extra) -> dict:
    return {"mean": r4(v.get("mean", v.get("reward_mean"))), "ci": [r4(x) for x in (v.get("ci") or v["ci95"])]} | extra


def run_of(file: str, pack: str, decoding: str = "sampled") -> tuple[dict, float]:
    run = next(r for r in load(f"{TB}/{file}")["runs"] if r["pack"] == pack and r["decoding"] == decoding)
    return {t["task_id"]: t for t in run["per_task"]}, run["wall_s"]


def readme_number(rel: str, pattern: str) -> float:
    m = re.search(pattern, text(rel))
    if not m:
        raise SystemExit(f"{rel}: no match for {pattern!r}")
    return float(m[1].replace(",", ""))


def frontier(beam_dir: Path) -> dict:
    """Blind fresh days: every model's capture re-graded from its records, its cost per battery-day, the paired gap
    of the trained 4B to it, and the frontier: each point that no cheaper point matches."""
    cm = load(f"{CM}/summary.json")
    l40s = cm["gpu_usd_per_h"]["L40S (g6e.8xlarge, us-west-2)"]
    tasks = RB.tasks_of("fresh")
    days = np.array([t["date"] for t in tasks])
    n = len(tasks)
    pts = []
    for key, file, label in (("base", "eval_step0_base.json", "Qwen3-4B, untrained"),
                             ("final", "eval_final.json", "Qwen3-4B, trained (run 4)")):
        recs, wall = run_of(file, "fresh")
        pts.append({"key": key, "label": label, "family": "qwen", "effort": None, "open": True, "recs": recs,
                    "usd": wall * l40s / 3600 / n,
                    "tokens": float(np.mean([recs[t["task_id"]]["len"] for t in tasks]))})
    api = [("sol", ROOT / TB / "sol/sol-ercot-dam-v1-fresh-2026-10-blind.jsonl.gz", "GPT-6.1 Sol", "sol", "high",
            False)]
    api += [(f"luna-{e}", ROOT / CM / f"luna/luna-blind-fresh-{e}.jsonl.gz", "GPT-6 Luna", "luna", e, False)
            for e in ("low", "medium", "high")]
    beam = {}
    for e in EFFORTS:
        p = next((p for p in (beam_dir / f"beam-blind-fresh-{e}.jsonl.gz", beam_dir / f"beam-blind-fresh-{e}.jsonl")
                  if p.is_file()), None)
        got = records(p) if p else {}
        beam[e] = "included" if all(t["task_id"] in got for t in tasks) else f"{len(got)} of {n}" if got else "not run"
        if beam[e] == "included":
            api.append((f"beam-{e}", p, "Beam-1.0", "beam", e, True))
    for key, path, label, family, effort, open_ in api:
        recs = records(path)
        pts.append({"key": key, "label": label, "family": family, "effort": effort, "open": open_, "recs": recs,
                    "usd": float(np.mean([recs[t["task_id"]]["usd"] for t in tasks])),
                    "tokens": float(np.mean([recs[t["task_id"]]["usage"]["output"] for t in tasks]))})
    for p in pts:
        p["c"] = RB.model_rows(tasks, p.pop("recs"))["c"]
        p |= RB.boot(p["c"], days)
    by = {p["key"]: p for p in pts}
    ms, s4 = cm["packs"]["blind-fresh"]["models"], load(f"{TB}/summary.json")["packs"]["fresh"]["models"]
    for key, ref in (("final", "4b-sampled"), ("sol", "sol"), ("luna-high", "luna-high"), ("luna-low", "luna-low")):
        same(by[key]["mean"], ms[ref]["score"]["mean"], f"{key} C")
        same(by[key]["usd"], ms[ref]["usd_task"], f"{key} $ per task", 5e-8)
    same(by["base"]["mean"], s4["base-sampled"]["c"]["mean"], "untrained C")
    beam_table = re.findall(r"\| Beam, effort (\w+) \| \**([0-9.]+)\** \| \**\[([0-9.]+), ([0-9.]+)\]\** \| "
                            r"\**\$([0-9.]+)\**", text("results/beam-agent/README.md"))
    for e, c, lo, _, usd in beam_table:
        if f"beam-{e}" in by:
            b = by[f"beam-{e}"]
            same(b["mean"], float(c), f"Beam {e} C", 5e-4)
            same(b["ci"][0], float(lo), f"Beam {e} CI", 5e-4)
            same(b["usd"], float(usd), f"Beam {e} $ per task", 5e-5 if float(usd) < 0.01 else 5e-4)
    best = -1.0
    for p in sorted(pts, key=lambda p: (p["usd"], -p["mean"])):
        p["frontier"] = bool(p["mean"] > best)
        best = max(best, p["mean"])
    f = by["final"]
    for p in pts:
        if p is not f:
            p["final_minus"] = gap(RB.paired(f["c"], p["c"], days))
    refs = load("results/blind-ceiling/summary.json")["registered"]["packs"]["fresh"]["methods"]["persist_point"]["c"]
    teacher = s4["teacher"]["c"]
    return {"pack": RB.PACKS["fresh"], "n_tasks": n, "n_days": int(len(np.unique(days))),
            "dates": [str(min(days)), str(max(days))], "l40s_usd_per_h": l40s, "beam": beam,
            "points": [{k: (round(v, 8) if k == "usd" else round(v, 1) if k == "tokens" else v)
                        for k, v in p.items() if k not in ("c", "n", "days")} for p in pts],
            "refs": {"persistence_dp": level(refs), "teacher_dp": level(teacher)},
            "ratios": {k: r4(by[a]["usd"] / f["usd"]) for k, a in (("luna_high", "luna-high"), ("sol", "sol"),
                                                                    ("luna_low", "luna-low"))}}


def scores() -> list[dict]:
    """Before and after on the identical prompt and harness: the untrained Qwen3-4B, the trained one, GPT-6 Luna at
    high effort and GPT-6.1 Sol, with the simple baseline a desk would run, on each pack that has all four."""
    cm, s4 = load(f"{CM}/summary.json")["packs"], load(f"{TB}/summary.json")["packs"]
    ceil = load("results/blind-ceiling/summary.json")["registered"]["packs"]
    out = []
    for pack, key, name, when in (("fresh", "blind-fresh", "Blind, newest days", "18–27 Oct 2026"),
                                  ("eval2025", "blind-eval2025", "Blind, held-out 2025", "6 Jan–30 Nov 2025")):
        m, p = cm[key]["models"], s4[pack]["models"]
        out.append({"key": key, "tier": "blind", "label": name, "when": when, "n_tasks": cm[key]["n_tasks"],
                    "n_days": cm[key]["n_days"], "untrained": level(p["base-sampled"]["c"]),
                    "trained": level(m["4b-sampled"]["score"], run="run 4"), "luna": level(m["luna-high"]["score"]),
                    "sol": level(m["sol"]["score"]),
                    "baseline": level(ceil[pack]["methods"]["persist_point"]["c"], label="persistence-DP"),
                    "gaps": {"trained_minus_untrained": gap(s4[pack]["paired"]["final-sampled - base-sampled"]),
                             "trained_minus_luna": gap(cm[key]["gaps"]["4b-sampled - luna-high"]),
                             "trained_minus_sol": gap(cm[key]["gaps"]["4b-sampled - sol"])}})
        same(out[-1]["trained"]["mean"], p["final-sampled"]["c"]["mean"], f"run 4 {pack} C")
    m, g = cm["foresight-eval2025"]["models"], cm["foresight-eval2025"]["gaps"]
    base = next(r for r in load("results/train/4b/summary.json")["rows"]
                if r["model"] == "Qwen3-4B base (zero-shot)" and r["decoding"] == "sampled")
    dpa = load(f"{T3}/summary.json")
    out.append({"key": "foresight-eval2025", "tier": "foresight", "label": "Foresight, held-out 2025",
                "when": "6 Jan–26 Nov 2025", "n_tasks": cm["foresight-eval2025"]["n_tasks"],
                "n_days": cm["foresight-eval2025"]["n_days"], "untrained": level(base, ci_kind="task"),
                "trained": level(m["4b-sampled"]["score"], run="run 3"), "luna": level(m["luna-high"]["score"]),
                "sol": level(m["sol"]["score"]),
                "baseline": level(dpa["greedy_rule"], label="greedy rule", ci_kind="task"),
                "gaps": {"trained_minus_luna": gap(g["4b-sampled - luna-high"]),
                         "trained_minus_sol": gap(g["4b-sampled - sol"])}})
    same(out[-1]["trained"]["mean"], dpa["secondary"]["2_final_vs_greedy_rule"]["reward_mean"], "run 3 R")
    m, g = cm["foresight-fresh"]["models"], cm["foresight-fresh"]["gaps"]
    fr = load("results/fresh/2026-10/summary.json")["models"]
    rule = max(("greedy", "threshold"), key=lambda r: fr[r]["mean"])
    out.append({"key": "foresight-fresh", "tier": "foresight", "label": "Foresight, newest days",
                "when": "18–27 Oct 2026", "n_tasks": cm["foresight-fresh"]["n_tasks"],
                "n_days": cm["foresight-fresh"]["n_days"], "untrained": None,
                "trained": level(m["4b-sampled"]["score"], run="run 3"), "luna": level(m["luna-high"]["score"]),
                "sol": level(m["sol"]["score"]),
                "baseline": level({"mean": fr[rule]["mean"], "ci": fr[rule]["ci_day"]}, label=f"{rule} rule"),
                "gaps": {"trained_minus_luna": gap(g["4b-sampled - luna-high"]),
                         "trained_minus_sol": gap(g["4b-sampled - sol"])}})
    same(out[-1]["trained"]["mean"], fr["run3-sampled"]["mean"], "run 3 fresh R")
    return out


RC = module("report_cost", f"{CM}/scripts/report_cost.py")
PACK_NAMES = {"blind-fresh": ("Blind, newest days", "18–27 Oct 2026"),
              "blind-eval2025": ("Blind, held-out 2025", "6 Jan–30 Nov 2025"),
              "foresight-eval2025": ("Foresight, held-out 2025", "6 Jan–26 Nov 2025"),
              "foresight-fresh": ("Foresight, newest days", "18–27 Oct 2026")}
CONTEST_ROWS = {"4b-sampled": ("final", "qwen", None, True), "sol": ("sol", "sol", "high", False),
                "luna-high": ("luna-high", "luna", "high", False), "luna-low": ("luna-low", "luna", "low", False)}
# The leaderboard's rows beyond the cost-matched contest's own. To add a model, commit its per-task records (one JSON
# line per task: task_id, actions, c or reward, usd, usage) under the one-call harness, add a line, and rerun.
UNTRAINED = ("Qwen3-4B, untrained", "qwen", None, True)
BOARD_ROWS = [
    ("blind-fresh", "base", *UNTRAINED, (f"{TB}/eval_step0_base.json", "fresh")),
    ("blind-eval2025", "base", *UNTRAINED, (f"{TB}/eval_step0_base.json", "eval2025")),
    ("foresight-eval2025", "base", *UNTRAINED, ("results/train/4b/eval_base.json", None)),
    ("blind-fresh", "luna-medium", "GPT-6 Luna", "luna", "medium", False,
     f"{CM}/luna/luna-blind-fresh-medium.jsonl.gz"),
    *[("blind-fresh", f"beam-{e}", "Beam-1.0", "beam", e, True, f"beam-blind-fresh-{e}.jsonl.gz") for e in EFFORTS],
]
INVALID = ("malformed", "truncated", "error")


def board_row(key: str, label: str, family: str, effort: str | None, open_: bool, m: dict, days, usd, tokens,
              src: str) -> dict:
    kinds = {str(k): int(v) for k, v in zip(*np.unique(m["kind"][m["ran"]], return_counts=True), strict=True)}
    n = int(m["ran"].sum())
    return {"key": key, "label": label, "family": family, "effort": effort, "open": open_,
            **RB.boot(m["score"], days), "valid": r4(sum(v for k, v in kinds.items() if k not in INVALID) / n),
            "feasible": r4(m["feasible"].mean()),
            "kinds": kinds, "usd": None if usd is None else round(float(usd), 8),
            "tokens": None if tokens is None else round(float(tokens), 1), "src": src}


def leaderboard(beam_dir: Path, front: dict) -> dict:
    """Every model and effort run under the one-call harness, re-graded on each pack from its records, with the error
    kind of every schedule, beside the baselines: the cost-matched contest's rows, then BOARD_ROWS."""
    cm, s4 = load(f"{CM}/summary.json")["packs"], load(f"{TB}/summary.json")["packs"]
    ceil = load("results/blind-ceiling/summary.json")["registered"]["packs"]
    packs = []
    for key, p in RC.PACKS.items():
        tasks, tier = RC.tasks_of(key), p["tier"]
        days = np.array([t["date"] for t in tasks])
        sk = "c" if tier == "blind" else "reward"
        run = "run 4" if tier == "blind" else "run 3"
        rows = []
        for rel in (p["fourb"][0], p.get("sol"), *(f"{CM}/luna/luna-{key}-{e}.jsonl.gz" for e in ("high", "low"))):
            if rel and (ROOT / rel).is_file():
                READ.setdefault(rel, hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()[:12])
        for name, m in RC.models_for(key, tasks).items():
            if name in CONTEST_ROWS:
                rk, family, effort, open_ = CONTEST_ROWS[name]
                label = {"qwen": f"Qwen3-4B, trained ({run})", "sol": "GPT-6.1 Sol", "luna": "GPT-6 Luna"}[family]
                rows.append(board_row(rk, label, family, effort, open_, m, days, m["usd_task"], m["out_tokens"], CM))
                same(rows[-1]["mean"], cm[key]["models"][name]["score"]["mean"], f"{key} {name}")
        for pk, rk, label, family, effort, open_, src in BOARD_ROWS:
            if pk != key:
                continue
            if isinstance(src, tuple):
                ev = load(src[0])
                r = next(r for r in ev["runs"]
                         if r["decoding"] == "sampled" and (src[1] is None or r["pack"] == src[1]))
                recs, rel = {t["task_id"]: t for t in r["per_task"]}, src[0]
                usd = r["wall_s"] * p["rate"] / 3600 / len(tasks) if tier == "blind" else None
                tokens = float(np.mean([t["len"] for t in r["per_task"]]))
            else:
                path = beam_dir / src if src.startswith("beam-") else ROOT / src
                if not path.is_file():
                    continue
                recs, rel = records(path), path.relative_to(ROOT).as_posix()
                if not all(t["task_id"] in recs for t in tasks):
                    continue
                usd = float(np.mean([recs[t["task_id"]]["usd"] for t in tasks]))
                tokens = float(np.mean([recs[t["task_id"]]["usage"]["output"] for t in tasks]))
            m = RC.regrade(tasks, tier, recs, sk)
            rows.append(board_row(rk, label, family, effort, open_, m, days, usd, tokens, rel))
        if tier == "blind":
            pk = "fresh" if key == "blind-fresh" else "eval2025"
            refs = []
            for rk, label, field in (
                    ("persistence-dp", "persistence-DP, the exact DP on yesterday's prices", "p_persist"),
                    ("ridge-dp", "ridge-DP, the exact DP on a ridge forecast", "p_ridge"),
                    ("anchor", "blind anchor, the better of the two picked in hindsight", "p_anchor")):
                x = [reward_value(t["refs"]["blind"][field], t["refs"]["foresight"]["p_idle"],
                                  t["refs"]["foresight"]["p_opt"]) for t in tasks]
                refs.append({"key": rk, "label": label, **RB.boot(x, days)})
            same(refs[0]["mean"], ceil[pk]["methods"]["persist_point"]["c"]["mean"], f"{key} persistence-DP")
            refs.append({"key": "teacher-dp", "label": "a tuned forecaster with the exact DP (run 4's teacher)",
                         **level(s4[pk]["models"]["teacher"]["c"])})
        else:
            refs = [{"key": k, "label": f"{k} rule", **RB.boot([t["refs"]["foresight"]["baselines"][k]["reward"]
                                                              for t in tasks], days)}
                    for k in ("greedy", "threshold", "clock")]
        refs.append({"key": "idle", "label": "idle, the battery does nothing", "mean": 0.2, "ci": [0.2, 0.2]})
        by = {r["key"]: r for r in rows}
        if key == "blind-fresh":
            fp = {q["key"]: q for q in front["points"]}
            for r in rows:
                same(r["mean"], fp[r["key"]]["mean"], f"{key} {r['key']}")
                same(r["usd"], fp[r["key"]]["usd"], f"{key} {r['key']} $ per task", 5e-8)
        if "base" in by and tier == "blind":
            same(by["base"]["mean"], s4["fresh" if key == "blind-fresh" else "eval2025"]["models"]["base-sampled"]["c"]
                 ["mean"], f"{key} untrained")
        packs.append({"key": key, "tier": tier, "label": PACK_NAMES[key][0], "when": PACK_NAMES[key][1],
                      "n_tasks": len(tasks), "n_days": int(len(np.unique(days))),
                      "metric": "r_opt" if tier == "blind" else "R", "rows": rows, "baselines": refs})
    return {"harness": "the one-call path-B prompt, identical for every model (blind: with the forecast paragraph)",
            "ci": "day-block bootstrap, 10,000 resamples of days", "packs": packs}


def dollars() -> dict:
    """$k per MW of battery per year (economics/summary.json): the before and after, the ladder of every policy, the
    paired gaps, inference against value, the price-shape quartiles and the fresh days one by one."""
    e = load(f"{EC}/summary.json")
    cm = load(f"{CM}/summary.json")
    out = {"status": e["status"], "invalid": e["invalid"], "packs": {}}
    ladder = ("optimum", "sol", "persistence-dp", "luna-high", "luna-medium", "4b-sampled", "sft", "ridge-dp",
              "greedy-d1", "luna-low", "threshold-d1", "idle", "base")
    for pack, name, when in (("eval2025", "Blind, held-out 2025", "6 Jan–30 Nov 2025"),
                             ("fresh", "Blind, newest days", "18–27 Oct 2026")):
        p = e["packs"][pack]
        rows, g = p["rows"], p["gaps"]
        lad = [{"key": k, "label": rows[k]["label"], "kind": rows[k]["kind"],
                "day": level(rows[k]["usd_per_mw_day"]), "yr": level(rows[k]["k_usd_per_mw_yr"]),
                "per_100mw_yr": rows[k]["k_usd_per_100mw_yr"]["mean"],
                "inference": rows[k].get("usd_inference_per_battery_day"), "valid": rows[k].get("valid")}
               for k in ladder if k in rows]
        q = p["concentration"]
        out["packs"][pack] = {
            "label": name, "when": when, "n_tasks": p["n_tasks"], "n_days": p["n_days"], "mw": p["mw"],
            "battery_hours": p["battery_hours"],
            "degradation_days": sum(v for k, v in p["c_deg_usd_per_mwh"].items() if float(k) > 0),
            "ladder": lad,
            "gaps": {k: {"label": v["label"], "day": level(v["usd_per_mw_day"]), "yr": level(v["k_usd_per_mw_yr"]),
                         "per_100mw_yr": r4(v["k_usd_per_100mw_yr"]["mean"]), "ahead": v["ahead"],
                         "level": v["level"], "days_ahead": v["days_ahead"]} for k, v in g.items()},
            "closed": p["share_of_persistence_to_optimum_gap_closed"],
            "top_days": {"k": q["top_days"], "share": q["optimum_share_in_top_days"],
                         "sol_share_from_top": q["vs_persistence"]["sol"]["net_gain_share_from_top_days"],
                         "sol_days": {k: q["vs_persistence"]["sol"][k] for k in ("days_ahead", "days_level",
                                                                                "days_behind")}},
            "inference": e["inference"]["packs"][pack]}
        if "by_shape_change_quartile" in q:
            out["packs"][pack]["quartiles"] = [
                {"q": r["quartile"], "days": r["n_days"], "tasks": r["n_tasks"], "range": r["shape_change"],
                 "optimum": level(r["optimum"]), "shortfall": level(r["persistence_shortfall"]),
                 **{m: gap(r[f"{m} - persistence-dp"]) for m in ("sol", "luna-high", "4b-sampled")}}
                for r in q["by_shape_change_quartile"]]
        else:
            out["packs"][pack]["by_day"] = q["by_day"]
    payback = {}
    for run, pack, rel in (("run 3", "foresight-eval2025", "results/train/4b-dpa"),
                           ("run 4", "blind-eval2025", TB)):
        ms = cm["packs"][pack]["models"]
        save = ms["luna-high"]["usd_task"] - ms["4b-sampled"]["usd_task"]
        payback[run] = {"gpu_usd": cm["training_gpu_usd"][run], "saving_per_battery_day": round(save, 8),
                        "battery_days": round(cm["training_gpu_usd"][run] / save), "pack": pack, "src": rel}
    out["payback"] = payback
    return out


def training() -> dict:
    """What each run changed and what it taught, the held-out curves of the GRPO runs and of the DP-advantage run,
    the blind run's split into forecasting and planning, and the GPU bill."""
    s1, s2, s3 = (load(f"results/train/{d}/summary.json") for d in ("4b", "4b-v2", "4b-dpa"))
    s4, cf, dg = load(f"{TB}/summary.json"), load("results/train/confirm-sft10k/summary.json"), \
        load("results/train/diag-reasoning-size/summary.json")
    a1, a2, a2c = (load(f"results/train/{d}summary.json") for d in ("", "arm2/", "arm2c/"))

    def row(s, model, decoding="sampled"):
        return next(r for r in s["rows"] if r["model"] == model and r.get("decoding") == decoding)

    r1 = {k: row(s1, m) for k, m in (("base", "Qwen3-4B base (zero-shot)"), ("sft", "4B SFT-1500 (step 0)"),
                                     ("final", "4B SFT + GRPO (final)"))}
    r2 = {k: row(s2, m) for k, m in (("sft", "run 2: 4B SFT-10k (step 0)"),
                                     ("final", "run 2: 4B SFT-10k + GRPO (final)"))}
    curve = [{"step": c["step"], "sampled": level(c["sampled"]), "greedy": r4(c["greedy"]["reward_mean"]),
              "feasible": c["sampled"]["feasible_rate"]} for c in s3["curve"]]
    cm_f = load(f"{CM}/summary.json")["packs"]["foresight-eval2025"]["models"]
    iid = next(r for r in cf["packs"]["eval_iid"]["rows"] if r["model"] == "run 2: 4B SFT-10k (step 0)"
               and r["decoding"] == "sampled")
    iid_greedy = next(r for r in cf["packs"]["eval_iid"]["rows"] if r["model"] == "rule:greedy")
    dr = dg["rows"]
    usd = {"arms": readme_number("results/train/arm2c/README.md",
                                 r"2b and 2c is about [0-9.]+ h ≈ \*\*\$([0-9.]+)\*\*"),
           "run 1": readme_number("results/train/4b/README.md", r"about \*\*\$([0-9.]+)\*\*"),
           "run 2": readme_number("results/train/4b-v2/README.md", r"or about \*\*\$([0-9.]+)\*\*"),
           "confirm": readme_number("results/train/confirm-sft10k/README.md", r"about \$([0-9.]+)\. No API"),
           "run 3": readme_number(f"{T3}/README.md", r"\*\*about \$([0-9.]+)\*\*"),
           "run 4": readme_number(f"{TB}/README.md", r"≈ \*\*\$([0-9.]+)\*\*")}
    for run in ("run 3", "run 4"):
        same(usd[run], load(f"{CM}/summary.json")["training_gpu_usd"][run], f"{run} GPU $", 0.5)
    ev, fr = s4["packs"]["eval2025"], s4["packs"]["fresh"]
    fe = ev["forecast_err"]
    pl = {pack: {"untrained": level(p["models"]["base-sampled"]["c"]), "sft": level(p["models"]["sft-sampled"]["c"]),
                 "final": level(p["models"]["final-sampled"]["c"]),
                 "dp_own": level(p["models"]["final-dp-own"]["c"]), "sol": level(p["models"]["sol"]["c"]),
                 "teacher": level(p["models"]["teacher"]["c"]),
                 "gaps": {"dp_own_minus_sol": gap(p["paired"]["final-dp-own - sol"]),
                          "final_minus_sol": gap(p["paired"]["final-sampled - sol"]),
                          "final_minus_sft": gap(p["paired"]["final-sampled - sft-sampled"]),
                          "final_minus_dp_own": gap(p["models"]["final-sampled"]["planning"]["own_minus_dp_own"])},
                 "exact_dp_share": p["models"]["final-sampled"]["planning"]["share_dp_plan_on_own_forecast"]}
          for pack, p in (("eval2025", ev), ("fresh", fr))}
    pl["mae"] = {"final": fe["models"]["final-sampled"]["all"], "teacher": fe["references"]["teacher"]["all"],
                 "persistence": fe["references"]["persistence"]["all"], "unit": "$/MWh, all hours, eval-2025"}
    runs = [
        {"key": "arms", "model": "Qwen3-1.7B", "registered": False, "label": "Arms 1–2c",
         "status": "exploratory", "result": f"{h(0)} → {h(a2c['rows'][4]['reward_mean'])}",
         "change": "GRPO from the base model, then warm starts on DP-optimal schedules (SFT-200, then SoC-aware "
                   "SFT-1,500), then up to 330 GRPO steps",
         "lesson": "GRPO from the base never produced a valid schedule, so it had no reward to learn from. A warm "
                   f"start was needed, and one that spells out the state of charge took the model from "
                   f"{h(a1['rows'][2]['reward_mean'])} "
                   f"to {h(a2['rows'][6]['reward_mean'])} with no RL, and GRPO then reached "
                   f"{h(a2c['rows'][4]['reward_mean'])}.", "usd": usd["arms"], "src": "results/train/arm2c"},
        {"key": "run1", "model": "Qwen3-4B", "registered": True, "label": "Run 1", "status": "registered",
         "result": f"{h(r1['sft']['reward_mean'])} → {h(r1['final']['reward_mean'])}",
         "change": "SoC-aware SFT on 1,500 solver schedules, then 330 steps of GRPO (TRL GRPOTrainer, vLLM)",
         "lesson": f"GRPO added {h(s1['paired']['trained_sampled_minus_sft']['mean'], sign=True)} "
                   f"{ci(s1['paired']['trained_sampled_minus_sft']['ci95'], sign=True)} on held-out days, its gains "
                   "in the first ~100 steps; then the policy's entropy collapsed and up to 45% of GRPO groups had "
                   "no reward spread.", "usd": usd["run 1"], "src": "results/train/4b"},
        {"key": "run2", "model": "Qwen3-4B", "registered": True, "label": "Run 2", "status": "registered",
         "result": f"{h(r2['sft']['reward_mean'])} → {h(r2['final']['reward_mean'])}",
         "change": "SFT on 10,000 solver schedules whose rationale states the DP's rule (SFT-10k), then 310 GRPO "
                   "steps with adaptive and dynamic sampling",
         "lesson": f"Solver labels did the work: SFT-10k alone scored {h(r2['sft']['reward_mean'])}, "
                   f"{h(s2['comparisons']['sampled']['run2_sft_minus_run1_sft']['mean'], sign=True)} over run 1's "
                   "warm start. GRPO on top stalled at "
                   f"{h(s2['comparisons']['sampled']['run2_final_minus_run2_sft']['mean'], sign=True)} "
                   f"{ci(s2['comparisons']['sampled']['run2_final_minus_run2_sft']['ci95'], sign=True)}: the policy "
                   "was near-deterministic, so about half the days gave eight identical rollouts and no gradient.",
         "usd": usd["run 2"], "src": "results/train/4b-v2"},
        {"key": "confirm", "model": "Qwen3-4B", "registered": True, "label": "Confirmation", "status": "registered",
         "result": f"{h(iid['reward_mean'])} vs {h(iid_greedy['reward_mean'])}",
         "change": "No training: SFT-10k re-tested on 500 unseen days of 2014–2024 (eval-iid)",
         "lesson": f"Confirmed: {h(iid['reward_mean'])} {ci(iid['ci95'])} against the greedy rule's "
                   f"{h(iid_greedy['reward_mean'])} {ci(iid_greedy['ci95'])}, intervals apart.",
         "usd": usd["confirm"], "src": "results/train/confirm-sft10k"},
        {"key": "diag", "model": "Qwen3-4B, 8B, 14B", "registered": True, "label": "Diagnostic", "status": "registered",
         "result": f"{h(dr['q4b-on4096']['reward_mean'])} at 4,096 thinking tokens",
         "change": "No training: thinking mode on, and bigger untrained models (8B, 14B-AWQ)",
         "lesson": "Neither helped. With thinking on, no base model finished reasoning within 4,096 tokens (0 of 800 "
                   f"completions); untrained 8B answered all-idle ({h(dr['q8b-off512']['reward_mean'])}) and 14B-AWQ "
                   f"scored {h(dr['q14awq-off512']['reward_mean'])}; SFT-10k with thinking on fell to "
                   f"{h(dr['sft-on2048']['reward_mean'])}.", "usd": None, "src": "results/train/diag-reasoning-size"},
        {"key": "run3", "model": "Qwen3-4B", "registered": True, "label": "Run 3", "status": "registered",
         "result": f"{h(s3['curve'][0]['sampled']['reward_mean'])} → {h(s3['curve'][-1]['sampled']['reward_mean'])}",
         "change": "From SFT-10k, 300 steps of policy gradient with the DP's exact per-hour advantage "
                   "A_t = Q*(s_t, a_t) − V*(s_t) in place of GRPO's group baseline",
         "lesson": f"Held-out reward rose {h(s3['primary']['a_final_minus_step0_sampled']['mean'], sign=True)} "
                   f"{ci(s3['primary']['a_final_minus_step0_sampled']['ci95'], sign=True)} (primary met) and "
                   f"{h(s3['eval_iid']['sampled']['final_minus_step0']['mean'], sign=True)} on eval-iid, through "
                   "fewer broken schedules: every suboptimal hour carries a signal, even when all rollouts agree.",
         "usd": usd["run 3"], "src": T3},
        {"key": "run4", "model": "Qwen3-4B", "registered": True, "label": "Run 4 (blind)", "status": "registered",
         "result": f"{h(ev['models']['base-sampled']['c']['mean'])} → {h(ev['models']['final-sampled']['c']['mean'])}",
         "change": "From run 3, forecast-then-plan on the blind tier: SFT on a teacher forecaster's written forecast "
                   "and the DP plan on it (12,500 rows), then the same exact-advantage RL on the plan",
         "lesson": f"Its written forecasts are close to the teacher's (MAE {h(pl['mae']['final'], 2)} against "
                   f"{h(pl['mae']['teacher'], 2)} $/MWh), and the DP on them would score "
                   f"{h(pl['eval2025']['dp_own']['mean'])}, level with Sol's {h(pl['eval2025']['sol']['mean'])}. Its "
                   f"own schedules score {h(pl['eval2025']['final']['mean'])}: the 4B loses its score in planning.",
         "usd": usd["run 4"], "src": TB}]
    return {"runs": runs, "gpu_usd_total": round(sum(usd[k] for k in ("arms", "run 1", "run 2", "run 3", "run 4")), 2),
            "curve": {"run3": curve, "run3_gain": gap(s3["primary"]["a_final_minus_step0_sampled"]),
                      "run3_slope": {"per_100": s3["primary"]["b_slope_sampled"]["per_100_steps"],
                                     "ci": s3["primary"]["b_slope_sampled"]["ci95_per_100_steps"]},
                      "run2": {"start": level(r2["sft"]), "end": level(r2["final"], step=310),
                               "gain": gap(s2["comparisons"]["sampled"]["run2_final_minus_run2_sft"])},
                      "run1": {"start": level(r1["sft"]), "end": level(r1["final"], step=330),
                               "gain": gap(s1["paired"]["trained_sampled_minus_sft"])},
                      "base": level(r1["base"]), "greedy_rule": level(s3["greedy_rule"]),
                      "luna_high": level(cm_f["luna-high"]["score"]), "sol": level(cm_f["sol"]["score"])},
            "planning": pl}


def glance(res: dict) -> list[dict]:
    """The headline numbers, each with the folders that hold its evidence."""
    fr = {p["key"]: p for p in res["frontier"]["points"]}
    bf, be = res["scores"][0], res["scores"][1]
    usd = res["dollars"]["packs"]["eval2025"]
    up, vb = usd["gaps"]["4b-sampled - base"], usd["gaps"]["4b-sampled - persistence-dp"]
    lad = {r["key"]: r for r in usd["ladder"]}
    t = res["training"]["curve"]
    lh, sol = fr["luna-high"], fr["sol"]
    return [
        {"key": "capture", "value": f"{h(bf['untrained']['mean'], 2)} → {h(bf['trained']['mean'], 2)}",
         "label": "of the hindsight optimum captured, before → after training",
         "text": f"Qwen3-4B bidding blind on {bf['n_tasks']} battery-days it never saw ({bf['when']}); "
                 f"{h(be['untrained']['mean'], 2)} → {h(be['trained']['mean'], 2)} on {be['n_tasks']} held-out "
                 "days of 2025. Doing nothing scores 0.2.", "src": [TB]},
        {"key": "cost", "value": "¼ the cost", "label": "of GPT-6 Luna at high effort, for the same score",
         "text": f"{h(fr['final']['mean'])} against {h(lh['mean'])}, paired {h(lh['final_minus']['mean'], sign=True)} "
                 f"{ci(lh['final_minus']['ci'], sign=True)}, for ${fr['final']['usd']:.5f} against ${lh['usd']:.4f} a "
                 f"battery-day. GPT-6.1 Sol scores {h(-sol['final_minus']['mean'])} more for "
                 f"{h(res['frontier']['ratios']['sol'], 0)}× the cost.", "src": [CM]},
        {"key": "usd", "value": f"+${h(up['yr']['mean'], 1)}k",
         "label": "per MW of battery power a year, bought by training",
         "text": f"From −${h(-lad['base']['yr']['mean'], 1)}k, worse than idle, to "
                 f"${h(lad['4b-sampled']['yr']['mean'], 1)}k "
                 f"on ERCOT's day-ahead prices of 2025: about ${h(up['per_100mw_yr'] / 1000, 1)}M a year for a 100 MW "
                 f"battery. Still ${h(-vb['yr']['mean'], 1)}k below persistence-DP, a free heuristic.", "src": [EC]},
        {"key": "dpa", "value": h(t["run3_gain"]["mean"], sign=True),
         "label": "held-out reward from exact DP advantages, where GRPO stalled",
         "text": f"Registered run 3: {h(t['run3_gain']['mean'], sign=True)} {ci(t['run3_gain']['ci'], sign=True)} "
                 f"over its warm start, to {h(t['run3'][-1]['sampled']['mean'])}. GRPO from the same start: "
                 f"{h(t['run2']['gain']['mean'], sign=True)} {ci(t['run2']['gain']['ci'], sign=True)}.",
         "src": [T3, "results/train/4b-v2"]}]


def build(beam_dir: Path) -> dict:
    READ.clear()
    res = {"schema": "gridsim.results/v1", "title": "What training bought, in dollars",
           "frontier": frontier(beam_dir), "scores": scores(), "dollars": dollars(), "training": training()}
    res["leaderboard"] = leaderboard(beam_dir, res["frontier"])
    res["glance"] = glance(res)
    res["live"] = {"prereg": "docs/prereg/v1-live-board.md", "first_seal": "2026-10-29", "page": f"{APP}/board.html",
                   "on_demand": True}
    res["sources"] = dict(sorted(READ.items()))
    return res


SPACE_FILES = ("results.html", "results.js", "results.css", "board.css", "board.html", "board.js", "index.html")


def stage(res: dict) -> Path:
    """The Space's files this build owns, beside the page's data, ready to serve."""
    space = BUILD / "space"
    shutil.rmtree(space, ignore_errors=True)
    space.mkdir(parents=True)
    for name in SPACE_FILES:
        shutil.copy(WEB / name, space / name)
    (space / "results.json").write_text(json.dumps(res, ensure_ascii=False, separators=(",", ":")))
    return space


@contextmanager
def browser(root: Path, chrome: str | None):
    rec = module("record", "scripts/record.py")
    with rec.serve(root) as port, tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(chrome), Path(profile), 1440, 900),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Page.enable")
                page.call("Runtime.enable")
                yield page, f"http://127.0.0.1:{port}"
        finally:
            proc.terminate()
            proc.wait()


def open_page(page, url: str, width: int, height: int, scale: float, mobile: bool = False) -> None:
    page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=scale,
              mobile=mobile)
    page.call("Page.navigate", url=url)
    page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.resultsReady ? r() : "
            "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
    page.js("document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 400)))")


def shot(page, path: Path, clip: dict) -> None:
    data = page.call("Page.captureScreenshot", format="png", captureBeyondViewport=True, clip=clip | {"scale": 1})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(base64.b64decode(data["data"]))


def page_shots(page, stem: Path, segment: int = 3000) -> list[Path]:
    """The whole page in segments: Chrome wraps a single capture taller than its texture limit."""
    m = page.call("Page.getLayoutMetrics")["cssContentSize"]
    out = []
    for i, y in enumerate(range(0, int(m["height"]), segment)):
        out.append(stem.with_name(f"{stem.name}-{i:02d}.png"))
        shot(page, out[-1], {"x": 0, "y": y, "width": m["width"], "height": min(segment, m["height"] - y)})
    return out


def figures(space: Path, chrome: str | None, shots: Path | None) -> dict[str, bytes]:
    """Each figure of the page, 800 px wide on white, captured at 2x; with ``shots``, the whole page at 1440 and 390."""
    out = {}
    with browser(space, chrome) as (page, base):
        open_page(page, f"{base}/results.html?export=1", 800, 900, 2)
        boxes = page.js("[...document.querySelectorAll('[data-figure]')].map((e) => { const r = "
                        "e.getBoundingClientRect(); return {id: e.dataset.figure, x: r.x + scrollX, y: r.y + scrollY, "
                        "width: r.width, height: r.height}; })")
        for b in boxes:
            path = BUILD / "figures" / f"{b['id']}.png"
            shot(page, path, {k: b[k] for k in ("x", "y", "width", "height")})
            out[b["id"]] = path.read_bytes()
        if shots:
            for w, mobile in ((1440, False), (390, True)):
                open_page(page, f"{base}/results.html", w, 900, 1 if w > 1000 else 2, mobile)
                page_shots(page, shots / f"results-{w}", 2400 if w > 1000 else 1200)
    return out


SHIP = {
    "results/train/4b-blind": ("README.md", "summary.json", "curves.png", "eval_final.json", "eval_rl-0000.json",
                               "eval_step0_base.json", "sol/sol-ercot-dam-v1-eval.jsonl.gz",
                               "sol/sol-ercot-dam-v1-fresh-2026-10-blind.jsonl.gz"),
    "results/train/4b-dpa": ("README.md", "summary.json", "curves.png", "eval_step0.json", "eval_trained.json"),
    "results/train/4b-v2": ("README.md", "summary.json", "curves.png"),
    "results/train/4b": ("README.md", "summary.json", "curves.png"),
    "results/train/arm2c": ("README.md", "summary.json", "curves.png"),
    "results/train/confirm-sft10k": ("README.md", "summary.json"),
    "results/train/diag-reasoning-size": ("README.md", "summary.json", "r_by_model.png"),
    "results/cost-matched": ("README.md", "summary.json", "tables.md", "score_vs_cost.png",
                             *(f"luna/luna-{t}-{p}-{e}.jsonl.gz" for t, p, e in (
                                 ("foresight", "eval2025", "high"), ("foresight", "eval2025", "low"),
                                 ("foresight", "fresh", "high"), ("foresight", "fresh", "low"),
                                 ("blind", "eval2025", "high"), ("blind", "eval2025", "low"),
                                 ("blind", "fresh", "high"), ("blind", "fresh", "medium"), ("blind", "fresh", "low")))),
    "results/economics": ("README.md", "summary.json", "tables.md", "value_ladder.png"),
    "results/beam-agent": ("README.md",),
    "results/fresh/2026-10": ("README.md", "summary.json", "tables.md", "per_day.png"),
    "results/fresh/2026-10-blind": ("README.md", "summary.json", "tables.md", "per_day.png"),
    "results/blind-ceiling": ("README.md", "summary.json", "tables.md", "ceiling.png"),
}
LINK = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
LEAK = re.compile(r"s3://|amazonaws|airops-runs|scale\.com|\bFD-\d|\bsk-[A-Za-z0-9_-]{12,}|litellm\.[a-z]|ocp-apim|"
                  r"b2clogin|ercot-api|\bhf_[A-Za-z0-9]{30,}|\b(?:10|172|192)\.\d+\.\d+\.\d+\b", re.I)


def unticket(text: str) -> str:
    text = re.sub(r"\s*\(FD-\d+\)", "", text)
    text = re.sub(r"\bFD-\d+'s\b", "the plan's", text)
    text = re.sub(r",\s*FD-\d+", "", text)
    return re.sub(r"(?:\bthe )?\bFD-\d+\b", "the plan", text)


def relink(text: str, folder: str, shipped: set[str]) -> str:
    """A README as the dataset shows it: links to shipped files and folders point into the dataset, the rest to the
    plugin on GitHub, both absolute, since a dataset page resolves neither relative folders nor images."""
    def fix(m: re.Match) -> str:
        bang, label, target = m[1], m[2], m[3]
        if re.match(r"[a-z]+:|#", target):
            return m[0]
        path, _, frag = target.partition("#")
        rel = posixpath.normpath(posixpath.join(folder, path)) if path else folder
        frag = f"#{frag}" if frag else ""
        if rel in shipped:
            url = f"{DATASET}/{'resolve' if bang else 'blob'}/main/{rel}{frag}"
        elif any(x.startswith(rel + "/") for x in shipped):
            url = f"{DATASET}/tree/main/{rel}{frag}"
        else:
            url = f"{REPO}/{'tree' if (ROOT / rel).is_dir() else 'blob'}/main/{rel}{frag}"
        return f"{bang}[{label}]({url})"
    return LINK.sub(fix, text)


def dataset_files(card: str, figs: dict[str, bytes]) -> dict[str, bytes]:
    shipped = {f"{d}/{f}" for d, fs in SHIP.items() for f in fs}
    files = {"README.md": card.encode(), "results/overview/results.json": (OUT / "results.json").read_bytes(),
             **{f"assets/figures/{k}.png": v for k, v in figs.items()}}
    for rel in sorted(shipped):
        content = (ROOT / rel).read_bytes()
        if rel.endswith(".md"):
            content = relink(unticket(content.decode()), posixpath.dirname(rel), shipped).encode()
        files[rel] = content
    return files


def space_readme(live: str) -> str:
    """The Space card as published, with the results page linked above the featured day and the live board's passes
    on demand."""
    live_par = re.search(r"\*\*\[The live board\]\((\S+?)/board\.html\):\*\*.*?\n\n", live, re.S)
    if not live_par or "**The featured day,**" not in live:
        raise SystemExit("the Space card changed shape; update space_readme")
    app = live_par[1]
    results = (f"**[What training bought, in dollars]({app}/results.html):** Qwen3-4B, trained on this environment's "
               "exact grader,\nwent from below idle to bidding as well as GPT-6 Luna at a quarter of its cost, with "
               "GPT-6.1 Sol still ahead: the\nbefore and after, the score-against-cost frontier, the training runs and "
               "what the decisions earn per MW of battery.\n\n")
    board = (f"**[The live board]({app}/board.html):** on each pass, GPT-6.1 Sol, GPT-6 Luna, the trained 4B and three "
             "rules seal a\nschedule for 45 batteries before ERCOT's day-ahead market closes; the first seal is for "
             "2026-10-29, and passes run on\ndemand. The schedules are settled at the prices ERCOT then posts, and the "
             "P&L adds up day by day.\n\n")
    text = live[:live_par.start()] + board + live[live_par.end():]
    text = re.sub(r"\*\*\[What training bought, in dollars\]\(.*?\n\n", "", text, flags=re.S)
    text = text.replace("**The featured day,**", results + "**The featured day,**", 1)
    new = "The viewer holds **replays only**: every replay plays back a recorded episode"
    text = text.replace("This Space holds **replays only**: every page plays back a recorded episode", new)
    if new not in text:
        raise SystemExit("the Space card's replays paragraph changed; update space_readme")
    return text


def space_files(space: Path, live_readme: str) -> dict[str, bytes]:
    names = ("results.html", "results.js", "results.css", "results.json", "index.html", "board.html")
    return {n: (space / n).read_bytes() for n in names} | {"README.md": space_readme(live_readme).encode()}


def front(text: str) -> str:
    return text[:text.index("\n---\n", 4) + 5]


def card_diff(new: str, live: str) -> list[str]:
    """What the new card drops from the live one, line by line; the front matter must be identical."""
    if front(new) != front(live):
        raise SystemExit("the new card's front matter differs from the live card's; the dataset viewer reads it")
    have = {x.strip() for x in new.splitlines()}
    return [x for x in live.splitlines() if x.strip() and x.strip() not in have]


def leaks(files: dict[str, bytes]) -> None:
    scan({k: v for k, v in files.items() if not k.endswith(".png")}, known_values())
    for path, content in files.items():
        if path.endswith(".png"):
            continue
        text = gzip.decompress(content).decode() if path.endswith(".gz") else content.decode()
        if hit := LEAK.search(text):
            raise SystemExit(f"{path} holds {hit[0]!r}; nothing was published")


def live_file(repo_type: str, name: str) -> str:
    with tempfile.TemporaryDirectory() as d:
        return Path(hf_hub_download(HF, name, repo_type=repo_type, local_dir=d)).read_text()


def publish(repo_type: str, files: dict[str, bytes], message: str) -> str:
    info = HfApi().create_commit(HF, repo_type=repo_type, commit_message=message, operations=[
        CommitOperationAdd(path_in_repo=k, path_or_fileobj=v) for k, v in sorted(files.items())])
    return info.commit_url


def live_shots(chrome: str | None, shots: Path) -> None:
    """After publishing: the dataset card and the Space's results page as the world sees them."""
    rec = module("record", "scripts/record.py")
    with tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(chrome), Path(profile), 1440, 900),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Page.enable")
                for url, stem, w, mobile in ((DATASET, "card-live-1440", 1440, False),
                                             (f"{APP}/results.html", "results-live-1440", 1440, False),
                                             (f"{APP}/results.html", "results-live-390", 390, True)):
                    page.call("Emulation.setDeviceMetricsOverride", width=w, height=900,
                              deviceScaleFactor=1 if w > 1000 else 2, mobile=mobile)
                    page.call("Page.navigate", url=f"{url}{'&' if '?' in url else '?'}t={int(time.time())}")
                    page.js("new Promise((r) => { const s = Date.now(); const f = () => (document.readyState === "
                            "'complete' && (window.resultsReady || !location.pathname.endsWith('results.html')) || "
                            "Date.now() - s > 30000) ? setTimeout(r, 2500) : setTimeout(f, 100); f(); })")
                    page_shots(page, shots / stem, 2400 if w > 1000 else 1200)
        finally:
            proc.terminate()
            proc.wait()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--beam", type=Path, default=ROOT / "results/beam-agent/beam")
    ap.add_argument("--chrome", help="Chrome to capture the figures with (default: found on the machine).")
    ap.add_argument("--shots", type=Path, help="Write full-page screenshots of the results page here (and, with "
                                                "--publish, of the published card and page).")
    ap.add_argument("--pareto", type=Path, default=Path.home() / "Downloads" / "gridsim-blind-fresh-pareto.png",
                    help="Also write the frontier figure here.")
    ap.add_argument("--publish", action="store_true", help="Upload to the dataset and the Space.")
    args = ap.parse_args()
    res = build(args.beam)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "results.json").write_text(json.dumps(res, indent=1, ensure_ascii=False) + "\n")
    for g in res["glance"]:
        print(f"{g['value']:>16}  {g['label']}")
    space = stage(res)
    figs = figures(space, args.chrome, args.shots)
    (OUT / "figures").mkdir(exist_ok=True)
    for name, png in figs.items():
        (OUT / "figures" / f"{name}.png").write_bytes(png)
    if args.pareto:
        args.pareto.parent.mkdir(parents=True, exist_ok=True)
        args.pareto.write_bytes(figs["frontier"])
    hub_dataset = module("hub_dataset", "scripts/hub_dataset.py")
    card = hub_dataset.card_only(ROOT / "results")
    live_card, live_readme = live_file("dataset", "README.md"), live_file("space", "README.md")
    dropped = card_diff(card, live_card)
    ds, sp = dataset_files(card, figs), space_files(space, live_readme)
    leaks(ds | {f"space/{k}": v for k, v in sp.items()})
    for name, files in (("dataset", ds), ("space", sp)):
        out = BUILD / name
        shutil.rmtree(out, ignore_errors=True)
        for k, v in files.items():
            (out / k).parent.mkdir(parents=True, exist_ok=True)
            (out / k).write_bytes(v)
        print(f"{name}: {len(files)} files, {sum(map(len, files.values())) / 1e6:.2f} MB in {out}")
    print(f"{len(figs)} figures in {OUT / 'figures'}; the frontier also at {args.pareto}")
    print(f"the card drops {len(dropped)} lines of the live card:", *(f"  - {x[:150]}" for x in dropped), sep="\n")
    if args.publish:
        print("dataset:", publish("dataset", ds, "Results: what training bought, in dollars (training, score against "
                                                  "cost, economics, live board), with the result folders"))
        print("space:", publish("space", sp, "Results page: what training bought, in dollars; linked from the viewer, "
                                              "the live board and the card"))
        if args.shots:
            live_shots(args.chrome, args.shots)


if __name__ == "__main__":
    main()
