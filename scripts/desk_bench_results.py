"""Desk bench results: every attempt the bench launcher recorded (one folder per `agent-env run`, meta.json beside
scripts/desk_bench_report.py's report.json with the Episode JSON) into results/desk-v4-bench/: summary.json,
grades.jsonl.gz (one row per model and window), each scored Episode JSON, the figures and a README.

    PYTHONPATH=src .venv/bin/python scripts/desk_bench_results.py --runs RUNS --out results/desk-v4-bench

A model's scored attempt on a window is its first that reached the grade; earlier attempts are retries, later ones
extra and never scored, and a window no attempt reached is missing, never imputed. Every grade is replayed from its
Episode JSON against the pack's frozen refs (scripts/desk_report.py's regrade). CIs are the earlier desk reports'
block bootstrap with the pack's eight weather fronts as blocks (10,000 resamples, seed 0, task-weighted), over all
windows and within each split. Cost is the trajectories' tokens at public list prices; Qwen3-4B's is its endpoint's
GPU time at Modal's list price, shared across its attempts by run time.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import importlib.util
import itertools
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import desk_bench_report as DBR  # noqa: E402
from desk_bench import HARNESSES  # noqa: E402
from desk_report import money_s, regrade, statement_lines  # noqa: E402

from gridsim_core.desk.data import load_tasks, pack_dir  # noqa: E402

B, SEED = 10_000, 0
SPLITS = ("pre_cutoff", "post_cutoff")
SCOPES = ("all", *SPLITS)
ORDER = ("opus", "sol", "luna", "argon", "qwen")
MODELS = {
    "claude-opus-5-5": {"key": "opus", "name": "Claude Opus 5.5", "tag": "Opus 5.5", "provider": "Anthropic",
                        "harness": "Claude Code", "setting": "effort high", "weights": "API", "cutoff": "2026-06"},
    "gpt-6.1-sol": {"key": "sol", "name": "GPT-6.1 Sol", "tag": "Sol", "provider": "OpenAI", "harness": "Codex CLI",
                    "setting": "effort high", "weights": "API", "cutoff": "2026-04-30",
                    "harness_note": "with OpenAI's catalog entries for the GPT-6 models"},
    "gpt-6-luna": {"key": "luna", "name": "GPT-6 Luna", "tag": "Luna", "provider": "OpenAI", "harness": "Codex CLI",
                   "setting": "effort high", "weights": "API", "cutoff": "2026-05-18",
                   "harness_note": "with OpenAI's catalog entries for the GPT-6 models"},
    "gemini-4-argon": {"key": "argon", "name": "Gemini 4 Argon", "tag": "Argon", "provider": "Google",
                       "harness": "Gemini CLI", "setting": "thinking high", "weights": "API", "cutoff": "2026-03"},
    "qwen3-4b": {"key": "qwen", "name": "Qwen3-4B", "tag": "Qwen3-4B", "variant": "untrained", "provider": "Qwen",
                 "harness": "OpenCode", "setting": "thinking on", "weights": "open", "server": "vLLM 0.29.0",
                 "cutoff": "2024"},
}
HARNESS_VERSIONS = {"Claude Code": "2.1.280", "Codex CLI": "0.147.0", "Gemini CLI": "0.38.2", "OpenCode": "1.17.18"}
GPU_USD_PER_S = {"T4": 0.000164, "L4": 0.000222, "A10": 0.000306, "L40S": 0.000542, "A100-40GB": 0.000583,
                 "A100-80GB": 0.000694, "H100": 0.001097, "H200": 0.001261, "B200": 0.001736}
GPU_PRICE_SOURCE = "Modal's list price, modal.com/pricing, read 2026-10-29"
SCALEDOWN_S = 300
EC2_USD_PER_H = {"g5.xlarge": 1.006, "g5.2xlarge": 1.212}
EC2_PRICE_SOURCE = "EC2 on-demand, us-west-2"
CLASS_KIND = {"infra": "infrastructure", "agent": "agent-side failure, final, no grade possible",
              "capped": "episode spend cap, final", "stopped": "model spend cap, final"}
SHELL = {"Bash", "command_execution", "run_shell_command", "bash", "shell", "local_shell"}
REFS = (("idle", "p_idle", "Idle"), ("anchor", "p_anchor", "Anchor (the desk's optimiser, same information)"),
        ("hind", "p_hind", "Hindsight optimum"), ("hind_phys", "p_hind_phys", "Hindsight, DAM tied to dispatch"),
        ("operator_replay", "p_operator_replay", "Real operator's bids, replayed"),
        ("operator_actual", "p_operator_actual", "Real operator, as settled"))
CHECKED = ("reward", "capture", "capture_phys", "p")
URL = re.compile(r"\b(?:https?|wss?)://\S+")
HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|ai|dev|run|app|cloud|internal)\b", re.I)


def boot(x, blocks) -> dict:
    """desk_report.boot's statistic: blocks drawn with replacement, the task-weighted mean of what they hold."""
    x, blocks = np.asarray(x, float), np.asarray(blocks)
    if not len(x):
        return {"mean": None, "ci": [None, None], "n": 0, "fronts": 0}
    u, inv = np.unique(blocks, return_inverse=True)
    idx = np.random.default_rng(SEED).integers(0, len(u), (B, len(u)))
    s, c = np.bincount(inv, x), np.bincount(inv)
    m = s[idx].sum(1) / c[idx].sum(1)
    return {"mean": round(float(x.mean()), 4), "ci": [round(float(v), 4) for v in np.percentile(m, [2.5, 97.5])],
            "n": int(len(x)), "fronts": int(len(u))}


def paired(a, b, blocks) -> dict:
    d = np.asarray(a, float) - np.asarray(b, float)
    out = boot(d, blocks)
    if len(d):
        blocks = np.asarray(blocks)
        out |= {"ahead": round(float((d > 1e-9).mean()), 4), "level": round(float((abs(d) <= 1e-9).mean()), 4),
                "fronts_ahead": int(sum(d[blocks == x].mean() > 0 for x in np.unique(blocks)))}
    return out


def split_gap(x, blocks, splits) -> dict:
    """Post-cutoff minus pre-cutoff mean, each split's fronts drawn with replacement apart (a stratified block
    bootstrap): the halves hold different windows, so nothing pairs them."""
    x, blocks, splits = np.asarray(x, float), np.asarray(blocks), np.asarray(splits)
    halves = [(x[splits == s], blocks[splits == s]) for s in SPLITS]
    if any(not len(v) for v, _ in halves):
        return {"mean": None, "ci": [None, None]}
    rng, means = np.random.default_rng(SEED), []
    for v, bl in halves:
        u, inv = np.unique(bl, return_inverse=True)
        idx = rng.integers(0, len(u), (B, len(u)))
        s, c = np.bincount(inv, v), np.bincount(inv)
        means.append(s[idx].sum(1) / c[idx].sum(1))
    return {"mean": round(float(halves[1][0].mean() - halves[0][0].mean()), 4),
            "ci": [round(float(v), 4) for v in np.percentile(means[1] - means[0], [2.5, 97.5])]}


def clean(text: str | None, limit: int = 240) -> str | None:
    return HOST.sub("<host>", URL.sub("<url>", str(text)))[:limit] if text else None


def failure_kind(text: str | None) -> str:
    t = (text or "").lower()
    for kind, words in (("cancelled", ("sigterm", "cancelled")),
                        ("sandbox or tunnel", ("sandbox", "stopped answering", "tunnel", "remoteprotocolerror")),
                        ("provider error", ("apierror", "api error", "error_code=4", "error_code=5", "rate limit",
                                            "overloaded", "invalid_argument")),
                        ("agent error", ("agent_error",))):
        if any(w in t for w in words):
            return kind
    return "other" if t else "no report"


def fronts(pack: str, tasks: dict[str, dict], alias: dict[str, str]) -> tuple[dict[str, dict], dict[str, str]]:
    """The pack's fronts by first day, and each window's front: its own first day, a --block-alias, or the front
    whose note says a site runs other days ("S04 runs 04-03..05")."""
    man = json.loads((pack_dir(pack) / "manifest.json").read_text())
    out, of = {}, {}
    for f in man["fronts"]:
        start = f["dates"][:10]
        out[start] = {"front": start, "dates": f["dates"], "split": f["split"], "kind": f["kind"], "why": f["why"]}
        for _, md in re.findall(r"\b(S\d+) runs (\d\d-\d\d)\.\.", f["why"]):
            alias.setdefault(f"{start[:4]}-{md}", start)
    for tid, t in tasks.items():
        first = t["dates"][0]
        block = first if first in out else alias.get(first)
        if block is None:
            raise SystemExit(f"{tid} starts {first}, no front's first day: pass --block-alias {first}=FRONT")
        if out[block]["split"] != t["tags"]["split"]:
            raise SystemExit(f"{tid}: split {t['tags']['split']}, its front {block} is {out[block]['split']}")
        of[tid] = block
    return out, of


def labels_of(specs: list[str]) -> dict:
    """--model MODEL_ID=KEY:NAME[:FAMILY]: a model the table lacks, its provider, harness and setting its family's."""
    out = {}
    for spec in specs:
        model_id, _, rest = spec.partition("=")
        key, name, *fam = rest.split(":")
        base = next((m for m in MODELS.values() if m["key"] == (fam[0] if fam else key)), {})
        out[model_id] = {**base, "key": key, "name": name, "tag": name, "family": fam[0] if fam else key,
                         "variant": None}
    return out


def label_of(model_id: str, labels: dict) -> dict:
    lab = labels.get(model_id) or MODELS.get(model_id)
    if lab is None:
        raise SystemExit(f"model {model_id!r} has no label: pass --model {model_id}=KEY:NAME[:FAMILY]")
    return {"family": lab["key"], **lab}


def play_model(run: Path, task: str) -> str | None:
    p = run / "bundle" / "tasks" / f"{task}.json"
    if not p.is_file():
        return None
    return next((s.get("model") for s in json.loads(p.read_text()) if s.get("type") == "prompt_agent"), None)


def state_usage(run: Path, task: str, model: str) -> dict | None:
    folder = run / "state" / "agent-env" / "object_store" / "prompt_agent_trajectories" / f"prompt_id={task}"
    if not folder.is_dir():
        return None
    turns = [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"), key=lambda f: f.stat().st_mtime)]
    return DBR.usage_of([t if isinstance(t, list) else t.get("events", []) for t in turns], model)


def watched_usd(run: Path) -> float | None:
    p = run / "watch.jsonl"
    if not p.is_file():
        return None
    rows = map(json.loads, filter(str.strip, p.read_text().splitlines()))
    costs = [r["usd"] for r in rows if r.get("event") == "cost"]
    return costs[-1] if costs else None


def state_verdict(run: Path) -> tuple[dict, dict | None]:
    """The verifier's grade and Episode JSON as the run's own document store holds them, for a report written
    without --with-episode (or none at all)."""
    log = run / "run.log"
    if not (log.is_file() and (run / "state").is_dir()):
        return {}, None
    try:
        inst = DBR.instance(run / "state", log.read_text())
    except (SystemExit, OSError, ValueError):
        return {}, None
    rows = (((inst.get("context") or {}).get("metadata") or {}).get("verifications") or {}).get("gridsim-desk") or {}
    first = (rows.get("results") or [{}])[0]
    ep = first.get("episode")
    return (first.get("metadata") or {}).get("grade") or {}, ep if isinstance(ep, dict) and "statement" in ep else None


def attempt(run: Path, meta: dict, rep: dict, labels: dict) -> dict:
    task = meta["task"]
    pr = rep.get("prompt_response") or {}
    model_id = pr.get("model") or play_model(run, task) or HARNESSES[meta["harness"]]["model"]
    ep = rep.get("episode") if isinstance(rep.get("episode"), dict) and "statement" in rep["episode"] else None
    if ep is None and rep.get("grade") is not None:
        grade, ep = state_verdict(run)
        rep = rep | {"grade": rep.get("grade") or grade}
    if rep.get("grade") and "valid" not in rep["grade"]:
        raise SystemExit(f"{run}: the report's grade has no 'valid'; rerun scripts/desk_bench_report.py there")
    usage = rep.get("usage") or {}
    if not usage.get("tokens"):
        usage = state_usage(run, task, model_id) or usage
    usd = usage.get("cost_usd_list_price")
    if usd is None:
        usd = watched_usd(run)
    calls = rep.get("calls") if isinstance(rep.get("calls"), dict) else rep.get("harness")
    calls = calls if isinstance(calls, dict) else {}
    own = calls.get("builtin_by_tool") or {}
    error = rep.get("error") or pr.get("error_message") or (meta.get("report_err") if not rep else None)
    wakes = rep.get("wakes") or {}
    return {"run": run.name, "harness_key": meta["harness"], "model_id": model_id,
            "label": label_of(model_id, labels), "task_id": task, "started": dt.datetime.fromisoformat(meta["started"]),
            "wall_s": float(rep.get("wall_s") or meta.get("wall_s") or 0.0), "status": rep.get("status") or "no report",
            "graded": bool(rep.get("grade")) and ep is not None, "grade": rep.get("grade") or {}, "episode": ep,
            "error": clean(error), "kind": None if rep.get("grade") else failure_kind(error or rep.get("status")),
            "tokens": usage.get("tokens") or {}, "usd": usd, "fake": bool(meta.get("fake")),
            "turns": calls.get("turns"), "own_calls": calls.get("builtin_calls"),
            "own_by_tool": own, "shell_calls": sum(v for k, v in own.items() if k in SHELL),
            "compactions": calls.get("compaction_events"), "sessions": len(calls.get("session_ids") or []),
            "wakes": wakes.get("env_episode"), "reminders": wakes.get("agent_reminders_set")}


def route_c(bench: Path, row: dict, result: dict | None, labels: dict) -> dict:
    """One attempt of the route-C driver on an EC2 box (its row in attempts.jsonl, runs/<unit>/report.json, and for a
    graded window its results.jsonl row and episodes/<window>.<model>.json); its class says whether it reached the
    grade."""
    run = bench / "runs" / row["unit"]
    rep = json.loads((run / "report.json").read_text()) if (run / "report.json").is_file() else {}
    if not rep and result:
        u = result.get("usage") or {}
        rep = {"status": row.get("status"), "wall_s": row.get("wall_s"), "grade": result.get("grade"),
               "harness": {"turns": u.get("turns"), "builtin_calls": u.get("harness_builtin_calls")}}
    meta = {"harness": row["harness"], "task": row["task_id"], "started": row["t_start"], "wall_s": row["wall_s"]}
    a = attempt(run, meta, rep, labels)
    ok = row["class"] == "ok"
    if ok and a["episode"] is None and (p := bench / "episodes" / f"{row['task_id']}.{a['model_id']}.json").is_file():
        ep = json.loads(p.read_text())
        a |= {"episode": ep, "grade": a["grade"] or ep.get("grade") or {}}
    u = row.get("usage") or {}
    version = re.search(r"\d+\.\d+\.\d+", row.get("agent_version") or "")
    return a | {"graded": ok and a["episode"] is not None and bool(a["grade"]),
                "harness_version": version[0] if version else None,
                "kind": None if ok else CLASS_KIND.get(row["class"], row["class"]),
                "error": clean(row.get("why")) or a["error"], "box": row.get("box"),
                "instance_type": row.get("instance_type"), "ended": dt.datetime.fromisoformat(row["t_end"]),
                "tokens": a["tokens"] or u.get("tokens") or {},
                "usd": a["usd"] if a["usd"] is not None else u.get("cost_usd_list_price", row.get("proxy_cost_usd"))}


def load(roots: list[Path], pack: str, tasks: dict, labels: dict) -> tuple[list[dict], Counter]:
    """Every bench attempt under the roots, from the Modal launcher's run folders (meta.json, report.json) or the
    route-C driver's attempts.jsonl (a box's own over a merged copy above it), and what was passed over: other packs'
    and tasks' runs, checks that are not the pre-registered episode (a turn cap, Codex on its own model metadata) and
    a second copy of a run."""
    out, skipped, seen = [], Counter(), set()
    benches = sorted({p.parent for r in roots for p in r.rglob("attempts.jsonl")})
    for b in (b for b in benches if not any(o != b and o.is_relative_to(b) for o in benches)):
        assign = next((json.loads(q.read_text()) for q in (b / "assignment.json", b.parent / "assignment.json",
                                                            b.parent.parent / "assignment.json") if q.is_file()), {})
        res = b / "results.jsonl"
        results = {r["unit"]: r for r in map(json.loads, filter(str.strip, res.read_text().splitlines()))
                   } if res.is_file() else {}
        for row in map(json.loads, filter(str.strip, (b / "attempts.jsonl").read_text().splitlines())):
            why = ("another pack" if assign.get("pack", pack) != pack else "another task" if row.get("task_id") not in
                   tasks or row.get("harness") not in HARNESSES else None)
            if why or (key := (row["harness"], row["task_id"], row["t_start"])) in seen:
                skipped[why or "a copy of a run already read"] += 1
                continue
            seen.add(key)
            out.append(route_c(b, row, results.get(row["unit"]), labels))
    for meta_path in sorted(p for r in roots for p in r.rglob("meta.json")):
        meta = json.loads(meta_path.read_text())
        if not isinstance(meta, dict) or meta.get("harness") not in HARNESSES:
            continue
        why = ("another pack" if meta.get("pack", pack) != pack else "another task" if meta.get("task") not in tasks
               else "a turn cap" if meta.get("max_turns") else "Codex as installed" if meta.get(
                   "codex_as_installed") else None)
        if why:
            skipped[why] += 1
            continue
        if (key := (meta["harness"], meta["task"], meta.get("started"))) in seen:
            skipped["a copy of a run already read"] += 1
            continue
        seen.add(key)
        rep = meta_path.parent / "report.json"
        out.append(attempt(meta_path.parent, meta, json.loads(rep.read_text()) if rep.is_file() else {}, labels))
    return out, skipped


def gpu_share(atts: list[dict], gpu: str, hours: float | None) -> dict:
    """The endpoint's GPU time over these attempts, --qwen-gpu-hours as billed or else the union of their run
    intervals, each held open by the endpoint's 300 s scale-down window; priced once and shared by run time."""
    spans = sorted((a["started"].timestamp(), a["started"].timestamp() + a["wall_s"] + SCALEDOWN_S) for a in atts)
    union, lo, hi = 0.0, None, None
    for s, e in spans:
        if hi is None or s > hi:
            union += 0.0 if hi is None else hi - lo
            lo, hi = s, e
        else:
            hi = max(hi, e)
    union += 0.0 if hi is None else hi - lo
    seconds = hours * 3600 if hours is not None else union
    total, wall = seconds * GPU_USD_PER_S[gpu], sum(a["wall_s"] for a in atts)
    for a in atts:
        a["usd"] = total * a["wall_s"] / wall if wall else 0.0
    return {"basis": "modal", "gpu": gpu, "usd_per_gpu_second": GPU_USD_PER_S[gpu], "price_source": GPU_PRICE_SOURCE,
            "gpu_hours": round(seconds / 3600, 3), "measured": hours is not None,
            "union_hours": round(union / 3600, 3), "scaledown_s": SCALEDOWN_S, "usd_total": round(total, 4),
            "attempts": len(atts), "where": f"one {gpu} GPU on Modal",
            "note": f"GPU time: {seconds / 3600:.2f} GPU-hours on one {gpu} at {GPU_PRICE_SOURCE} "
                    f"(${GPU_USD_PER_S[gpu]} a GPU-second), shared across its runs by run time"}


def ec2_share(atts: list[dict]) -> dict:
    """Route C: each open-weight attempt's share of its GPU box's time, its interval divided among the attempts running
    on that box at the same time (the boxes run nothing else), at the box's on-demand price."""
    for box in sorted({a["box"] for a in atts}):
        xs = [a for a in atts if a["box"] == box]
        edges = sorted({a["started"].timestamp() for a in xs} | {a["ended"].timestamp() for a in xs})
        share = defaultdict(float)
        for lo, hi in itertools.pairwise(edges):
            live = [a for a in xs if a["started"].timestamp() <= lo and a["ended"].timestamp() >= hi]
            for a in live:
                share[a["run"]] += (hi - lo) / len(live)
        for a in xs:
            if a["instance_type"] not in EC2_USD_PER_H:
                raise SystemExit(f"{box}: no on-demand price for {a['instance_type']}: pass --ec2-price TYPE=USD")
            a["gpu_s"] = share[a["run"]]
            a["usd"] = share[a["run"]] / 3600 * EC2_USD_PER_H[a["instance_type"]]
    types = sorted({a["instance_type"] for a in atts})
    hours = sum(a["gpu_s"] for a in atts) / 3600
    return {"basis": "ec2", "price_source": EC2_PRICE_SOURCE, "usd_per_hour": {k: EC2_USD_PER_H[k] for k in types},
            "boxes": len({a["box"] for a in atts}), "gpu_hours": round(hours, 3),
            "usd_total": round(sum(a["usd"] for a in atts), 4), "attempts": len(atts),
            "where": f"EC2 GPU boxes ({', '.join(types)})",
            "note": f"GPU time: {hours:.2f} box-hours on EC2 GPU boxes ("
                    + ", ".join(f"{k} at ${v}/h" for k, v in EC2_USD_PER_H.items() if k in types)
                    + f", {EC2_PRICE_SOURCE}), each run's share of its box's time while it ran"}


def cap(p: float | None, r: dict) -> float | None:
    if p is None or r["p_hind"] - r["p_idle"] <= 1e-9:
        return None
    return round((p - r["p_idle"]) / (r["p_hind"] - r["p_idle"]), 6)


def windows(atts: list[dict], tasks: dict, front_of: dict) -> tuple[list[dict], list[dict]]:
    """One row per model and window of the pack, its scored attempt regraded or the window marked missing (with the
    last attempt's failure, or no attempt at all), and every attempt."""
    by = defaultdict(list)
    for a in atts:
        by[(a["label"]["key"], a["task_id"])].append(a)
    rank = {k: i for i, k in enumerate(ORDER)}
    rows, log = [], []
    for key in sorted({k for k, _ in by}, key=lambda k: (rank.get(k, 99), k)):
        some = next(xs[0] for (k, _), xs in by.items() if k == key)
        for tid in sorted(set(tasks) - {t for k, t in by if k == key}):
            t, card = tasks[tid], tasks[tid]["site"].get("card") or {}
            rows.append({"model": key, "name": some["label"]["name"], "family": some["label"]["family"],
                         "harness": some["label"]["harness"], "harness_key": some["harness_key"],
                         "model_id": some["model_id"], "task_id": tid, "split": t["tags"]["split"],
                         "front": front_of[tid], "site": t["site"]["site_id"], "region": card.get("region"),
                         "battery": card.get("size"), "dates": t["dates"], "status": "missing",
                         "missing_reason": "no attempt", "attempts": 0, "retries": 0, "extra_attempts": 0, "usd": None,
                         "usd_all_attempts": 0.0})
    for (key, tid), xs in sorted(by.items(), key=lambda kv: (rank.get(kv[0][0], 99), kv[0][0], kv[0][1])):
        xs.sort(key=lambda a: a["started"])
        i = next((j for j, a in enumerate(xs) if a["graded"]), None)
        for j, a in enumerate(xs):
            log.append({"model": key, "task_id": tid, "run": a["run"], "attempt": j + 1,
                        "role": "scored" if j == i else "extra" if i is not None and j > i else "failed",
                        "status": a["status"], "kind": a["kind"], "error": a["error"], "usd": round(a["usd"] or 0, 4),
                        "wall_s": round(a["wall_s"], 1), "started": a["started"].isoformat(timespec="seconds"),
                        **({"box": a["box"], "instance_type": a["instance_type"],
                            "harness_version": a["harness_version"]} if a.get("box") else {})})
        t, a = tasks[tid], xs[i if i is not None else -1]
        lab, card = a["label"], t["site"].get("card") or {}
        row = {"model": key, "name": lab["name"], "family": lab["family"], "harness": lab["harness"],
               "harness_key": a["harness_key"], "model_id": a["model_id"], "task_id": tid,
               "split": t["tags"]["split"], "front": front_of[tid], "site": t["site"]["site_id"],
               "region": card.get("region"), "battery": card.get("size"), "dates": t["dates"],
               "status": "scored" if i is not None else "missing", "attempts": len(xs),
               "retries": i if i is not None else len(xs), "extra_attempts": len(xs) - i - 1 if i is not None else 0,
               "usd": round(a["usd"] or 0.0, 4) if i is not None else None,
               "usd_all_attempts": round(sum(x["usd"] or 0.0 for x in xs), 4),
               **({} if i is not None else {"missing_reason": xs[-1]["kind"] or "not graded"})}
        if i is not None:
            ep, refs = a["episode"], t["refs"]
            g = regrade({"valid": bool(a["grade"].get("valid"))}, ep, refs)
            subs = ep.get("submissions") or []
            row |= {k: g.get(k) for k in ("valid", "reward", "capture", "capture_phys", "stretch", "beats_anchor",
                                          "floored", "p", "p_idle", "p_anchor", "p_hind", "p_hind_phys",
                                          "p_operator_replay", "p_operator_actual")}
            row |= {"c_operator_replay": cap(g["p_operator_replay"], g),
                    "verifier": {k: a["grade"].get(k) for k in CHECKED}, "lines": statement_lines(ep),
                    "turns": a["turns"] if a["turns"] is not None else len(ep.get("turns") or []),
                    "wakes": a["wakes"] if a["wakes"] is not None else len(ep.get("wakes") or []),
                    "desk_calls": sum(len(x.get("calls") or []) for x in ep.get("turns") or []),
                    "own_tool_calls": a["own_calls"], "shell_calls": a["shell_calls"], "own_tools": a["own_by_tool"],
                    "reminders": a["reminders"], "compactions": a["compactions"], "sessions": a["sessions"],
                    "submissions": len(subs), "rejected": sum(not s.get("accepted") for s in subs),
                    "tokens": a["tokens"], "wall_s": round(a["wall_s"], 1),
                    "episode": f"episodes/{key}/{tid}.{a['model_id']}.json.gz"}
        rows.append(row)
    rows.sort(key=lambda r: (rank.get(r["model"], 99), r["model"], r["task_id"]))
    return rows, log


def scope_rows(rows: list[dict], scope: str) -> list[dict]:
    return [r for r in rows if scope == "all" or r["split"] == scope]


def stat(rows: list[dict], fn) -> dict:
    pairs = [(v, r["front"]) for r in rows if (v := fn(r)) is not None]
    return boot([v for v, _ in pairs], [f for _, f in pairs])


def model_scope(rows: list[dict]) -> dict:
    return {"n": len(rows), "fronts": len({r["front"] for r in rows}),
            "C": stat(rows, lambda r: r["capture"]), "R": stat(rows, lambda r: r["reward"]),
            "P": stat(rows, lambda r: r["p"]), "C_phys": stat(rows, lambda r: r["capture_phys"]),
            "P_minus_anchor": stat(rows, lambda r: r["p"] - r["p_anchor"]),
            "P_minus_operator_replay": stat(rows, lambda r: None if r["p_operator_replay"] is None
                                            else r["p"] - r["p_operator_replay"]),
            "C_minus_operator_replay": stat(rows, lambda r: None if r["capture"] is None or r[
                "c_operator_replay"] is None else r["capture"] - r["c_operator_replay"]),
            "valid_share": round(float(np.mean([r["valid"] for r in rows])), 4) if rows else None,
            "beats_anchor_share": round(float(np.mean([r["beats_anchor"] for r in rows])), 4) if rows else None,
            "usd_per_window": round(float(np.mean([r["usd"] for r in rows])), 4) if rows else None}


def mean(rows: list[dict], key: str, nd: int = 2) -> float | None:
    v = [r[key] for r in rows if r.get(key) is not None]
    return round(float(np.mean(v)), nd) if v else None


def model_block(rows: list[dict], log: list[dict], lab: dict, gpu: dict | None) -> dict:
    key, done = rows[0]["model"], [r for r in rows if r["status"] == "scored"]
    tries = [x for x in log if x["model"] == key]
    versions = Counter(x["harness_version"] for x in tries if x.get("harness_version"))
    tok = Counter()
    for r in done:
        tok.update({k: v or 0 for k, v in (r["tokens"] or {}).items()})
    gaps = {}
    for k, f in (("C", "capture"), ("R", "reward"), ("P", "p")):
        xs = [(r[f], r["front"], r["split"]) for r in done if r[f] is not None]
        gaps[k] = split_gap(*zip(*xs, strict=True)) if xs else {"mean": None, "ci": [None, None]}
    return {"key": key, **{k: lab.get(k) for k in ("name", "tag", "provider", "harness", "setting", "weights",
                                                   "variant", "family", "harness_note", "server", "cutoff")},
            "model_id": rows[0]["model_id"], "harness_key": rows[0]["harness_key"],
            "harness_version": versions.most_common(1)[0][0] if versions else HARNESS_VERSIONS.get(lab.get("harness")),
            "harness_versions_recorded": dict(versions) or None, "n": len(done),
            "missing": sorted(r["task_id"] for r in rows if r["status"] == "missing"),
            **{s: model_scope(scope_rows(done, s)) for s in SCOPES}, "split_gap": gaps,
            "cost": {"basis": "gpu_time" if gpu else "list_price_tokens",
                     "usd_per_window": round(float(np.mean([r["usd"] for r in done])), 4) if done else None,
                     "usd_median": round(float(np.median([r["usd"] for r in done])), 4) if done else None,
                     "usd_scored_total": round(sum(r["usd"] for r in done), 4),
                     "usd_all_attempts": round(sum(x["usd"] for x in tries), 4), **({"gpu": gpu} if gpu else {})},
            "tokens_per_window": {k: round(v / len(done), 1) for k, v in tok.items()} if done else {},
            "behaviour": {k: mean(done, k) for k in ("turns", "wakes", "desk_calls", "own_tool_calls", "shell_calls",
                                                     "reminders", "submissions", "rejected", "compactions", "wall_s")},
            "own_tools": dict(sum((Counter(r["own_tools"] or {}) for r in done), Counter()).most_common()),
            "attempts": {"total": len(tries), "scored": sum(x["role"] == "scored" for x in tries),
                         "failed": sum(x["role"] == "failed" for x in tries),
                         "extra": sum(x["role"] == "extra" for x in tries),
                         "windows_retried": sum(1 for r in rows if r["retries"]),
                         "windows_missing": sum(r["status"] == "missing" for r in rows),
                         "missing_reasons": dict(Counter(r["missing_reason"] for r in rows
                                                         if r["status"] == "missing")),
                         "failure_kinds": dict(Counter(x["kind"] for x in tries if x["role"] == "failed"))}}


def ref_block(tasks: dict, front_of: dict) -> dict:
    """Every reference on every window of the pack, from its frozen refs, whichever models reached it."""
    rows = [{**t["refs"], "split": t["tags"]["split"], "front": front_of[tid]} for tid, t in tasks.items()]
    out = {}
    for key, field, label in REFS:
        out[key] = {"label": label}
        for s in SCOPES:
            rs = [r for r in scope_rows(rows, s) if r.get(field) is not None]
            out[key][s] = {"n": len(rs), "P": stat(rs, lambda r, f=field: r[f]),
                           "C": stat(rs, lambda r, f=field: cap(r[f], r)),
                           "C_phys": stat(rs, lambda r, f=field: None if r.get("p_hind_phys") is None or r[
                               "p_hind_phys"] - r["p_idle"] <= 1e-9 else (r[f] - r["p_idle"]) / (
                               r["p_hind_phys"] - r["p_idle"]))}
    return out


def pair_block(a: str, b: str, ra: dict, rb: dict) -> dict:
    out = {"a": a, "b": b}
    for s in SCOPES:
        common = sorted(t for t in set(ra) & set(rb) if s == "all" or ra[t]["split"] == s)
        fr = [ra[t]["front"] for t in common]
        cc = [t for t in common if ra[t]["capture"] is not None and rb[t]["capture"] is not None]
        out[s] = {"n": len(common), "C": paired([ra[t]["capture"] for t in cc], [rb[t]["capture"] for t in cc],
                                                [ra[t]["front"] for t in cc]),
                  "R": paired([ra[t]["reward"] for t in common], [rb[t]["reward"] for t in common], fr),
                  "P": paired([ra[t]["p"] for t in common], [rb[t]["p"] for t in common], fr)}
    return out


def operator_block(a: str, ra: dict) -> dict:
    out = {"a": a, "b": "operator_replay"}
    for s in SCOPES:
        ts = sorted(t for t in ra if (s == "all" or ra[t]["split"] == s) and ra[t]["p_operator_replay"] is not None)
        cc = [t for t in ts if ra[t]["capture"] is not None and ra[t]["c_operator_replay"] is not None]
        out[s] = {"n": len(ts), "P": paired([ra[t]["p"] for t in ts], [ra[t]["p_operator_replay"] for t in ts],
                                            [ra[t]["front"] for t in ts]),
                  "C": paired([ra[t]["capture"] for t in cc], [ra[t]["c_operator_replay"] for t in cc],
                              [ra[t]["front"] for t in cc])}
    return out


def plot_block(models: dict, refs: dict) -> dict:
    """The cost-versus-score chart's data: a point per model at its mean cost and C over the windows it has, and a
    series per family, so a fine-tuned checkpoint sits in its base's series."""
    pts = [{"key": k, "family": m["family"], "name": m["name"], "tag": m["tag"], "variant": m.get("variant"),
            "provider": m["provider"], "harness": m["harness"], "setting": m["setting"], "weights": m["weights"],
            "n": m["n"], "usd": m["cost"]["usd_per_window"], "basis": m["cost"]["basis"], "C": m["all"]["C"],
            **{s: m[s]["C"] for s in SPLITS}} for k, m in models.items() if m["n"]]
    return {"points": pts, "series": [{"family": f, "points": [p["key"] for p in pts if p["family"] == f]}
                                      for f in dict.fromkeys(p["family"] for p in pts)],
            "references": {k: {"label": refs[k]["label"], **{s: refs[k][s]["C"] for s in SCOPES}}
                           for k in ("operator_replay", "anchor")}}


def regrade_check(rows: list[dict]) -> dict:
    diffs = []
    for r in (r for r in rows if r["status"] == "scored"):
        d = {k: (r["verifier"].get(k), r[k]) for k in CHECKED
             if (r["verifier"].get(k) is None) != (r[k] is None) or (r[k] is not None and abs(
                 float(r["verifier"][k]) - float(r[k])) > (0.005 if k == "p" else 1e-3))}
        if d:
            diffs.append({"model": r["model"], "task_id": r["task_id"], "changed": d})
    return {"refs": "the pack's task rows, frozen at desk-v4-freeze", "diffs": diffs}


def join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


def lead_text(models: dict, exposed: list[str], differ: list[str]) -> str:
    """The pre-registration's lead-split rule as read before any API-model result, and what it gave: the rule guards
    against training-data contamination, so only a model whose training cutoff falls inside the pre-cutoff windows
    can trigger it."""
    unexposed = [m for k, m in models.items() if k not in exposed]
    rule = ("Which half leads, a reading set before any API-model result: the rule guards against training-data "
            "contamination, so the post-cutoff half leads only if a model whose reported training cutoff comes after "
            "the first pre-cutoff window, so that those windows may be in its training data ("
            + join([models[k]["name"] for k in exposed] or ["none here"]) + "), has a post − pre C interval that "
            "excludes zero")
    if unexposed:
        rule += ("; " + join([f"{m['name']}'s ({m.get('cutoff') or 'unknown'})" for m in unexposed])
                 + f" cutoff{'s precede' if len(unexposed) > 1 else ' precedes'} every window, so both halves are "
                 "unseen and the gap cannot be contamination")
    return rule + (f". {join([models[k]['name'] for k in differ])} meet{'s' if len(differ) == 1 else ''} it, so the "
                   "post-cutoff column leads." if differ else
                   ". None does, so all the windows lead, with both halves shown.")


def summarize(a, tasks: dict, fr: dict, front_of: dict, rows: list[dict], log: list[dict], labs: dict, gpus: dict,
              episodes: list[dict], fake: bool) -> dict:
    rank = {k: i for i, k in enumerate(ORDER)}
    keys = sorted({r["model"] for r in rows}, key=lambda k: (rank.get(k, 99), k))
    models = {k: model_block([r for r in rows if r["model"] == k], log, labs[k], gpus.get(k)) for k in keys}
    scored = {k: {r["task_id"]: r for r in rows if r["model"] == k and r["status"] == "scored"} for k in keys}
    pairs = {f"{x}-{y}": pair_block(x, y, scored[x], scored[y]) for x, y in itertools.combinations(keys, 2)}
    pairs |= {f"{x}-operator_replay": operator_block(x, scored[x]) for x in keys}
    refs = ref_block(tasks, front_of)
    man = json.loads((pack_dir(a.pack) / "manifest.json").read_text())
    route = "ec2" if any(r.get("box") for r in log) else "modal"
    first = min(t["dates"][0] for t in tasks.values() if t["tags"]["split"] == "pre_cutoff")
    exposed = [k for k in keys if (models[k].get("cutoff") or "") >= first]
    differ = [k for k in exposed if (g := models[k]["split_gap"]["C"])["mean"] is not None and (
        g["ci"][0] > 0 or g["ci"][1] < 0)]
    agent = {m["name"]: n for m in models.values()
             if (n := m["attempts"]["missing_reasons"].get(CLASS_KIND["agent"]))}
    return {
        "schema": "gridsim.desk.bench/v1", "fake": fake, "pack": a.pack, "layer": "v4", "unit": "3-day window",
        "generated": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "n_windows": len(tasks),
        "n_fronts": len(fr), "sites": sorted({t["site"]["site_id"] for t in tasks.values()}),
        "splits": {s: {"windows": sum(t["tags"]["split"] == s for t in tasks.values()),
                       "fronts": [f for f, x in fr.items() if x["split"] == s]} for s in SPLITS},
        "cutoff": man.get("cutoff"), "fronts": list(fr.values()),
        "block_alias": {tasks[t]["dates"][0]: b for t, b in front_of.items() if tasks[t]["dates"][0] != b},
        "ci": {"method": "block bootstrap, the pack's weather fronts as blocks, task-weighted means; a split's CI "
                         "draws its own fronts; post − pre draws each split's fronts apart",
               "resamples": B, "seed": SEED, "level": 0.95, "blocks": "front"},
        "models": models, "order_by_C": sorted((k for k in keys if models[k]["n"]),
                                               key=lambda k: -models[k]["all"]["C"]["mean"]),
        "lead_rule": {"exposed": exposed, "unexposed": [k for k in keys if k not in exposed], "first_window": first,
                      "set": "before any API-model result", "text": lead_text(models, exposed, differ)},
        "halves_differ": differ, "lead_split": "post_cutoff" if differ else "all", "references": refs,
        "paired": pairs, "plot": plot_block(models, refs), "attempts": log, "regraded": regrade_check(rows),
        "run": {"framework": a.framework, "bundle": a.bundle, "prereg": a.prereg, "route": route,
                "harness_versions": {m["harness"]: m["harness_version"] for m in models.values()},
                "budget": next((e.get("budget") for e in episodes if e.get("budget")), None),
                "core_versions": sorted({e.get("core_version", "?") for e in episodes}),
                "prices_per_mtok": {k: v for k, v in DBR.PRICES.items() if any(m["model_id"] == k
                                                                              for m in models.values())}},
        "deviations": [d.replace("{retries}", ", ".join(
            f"{m['name']} {sum(x['kind'] == CLASS_KIND['infra'] for x in log if x['model'] == k)}"
            for k, m in models.items())) for d in a.deviation] + ([
                f"Agent-side failures with no grade ({', '.join(f'{n} {k}' for n, k in agent.items())}): the harness "
                "failed during play, so the verifier never ran and these windows could not be scored as settled; they "
                "are reported missing and not imputed."] if agent else []) or None,
        "defects": a.defect or None, "notes": a.note or None,
        "deferred": a.deferred or None}


def episodes_out(atts: list[dict], rows: list[dict], out: Path, redact: list[str]) -> dict[str, int]:
    """Each scored Episode JSON beside the run's own grade, its policy naming the agent that played it (the hero GIF
    and the viewer name the model from it); each --redact term replaced and counted."""
    paths = {(r["model"], r["task_id"]): out / r["episode"] for r in rows if r["status"] == "scored"}
    shutil.rmtree(out / "episodes", ignore_errors=True)
    hits = Counter()
    for a in atts:
        p = paths.pop((a["label"]["key"], a["task_id"]), None) if a["graded"] else None
        if p is None:
            continue
        lab = a["label"]
        policy = (a["episode"].get("policy") or {"kind": "model", "model": a["model_id"]}) | {
            "name": lab["name"], "tag": lab["tag"], "harness_name": lab["harness"], "setting": lab["setting"]}
        text = json.dumps(dict(a["episode"], grade=a["grade"], policy=policy), ensure_ascii=False)
        for term in redact:
            hits[term] += text.count(term)
            text = text.replace(term, "<redacted>")
        p.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(p, "wb", compresslevel=9, mtime=0) as f:
            f.write(text.encode())
    return dict(hits)


def hero(s: dict, rows: list[dict], out: Path, pick: str | None) -> dict | None:
    """The lead GIF's episode (MODEL:TASK_ID with --hero): a run of an API model with visible trading (accepted
    day-ahead offers and at least two real-time re-offers), a window after every model's training cutoff when one
    qualifies, ranked by scripts/hub_desk_hero.py's score plus a bonus per day-ahead market bid and for reserves won."""
    hh, cands = module("hub_desk_hero", "scripts/hub_desk_hero.py"), []
    for r in rows:
        if r["status"] != "scored" or s["models"][r["model"]]["weights"] == "open" or (
                pick and pick != f"{r['model']}:{r['task_id']}"):
            continue
        path = out / r["episode"]
        ep = hh.regraded(hh.read(path), path, out / "grades.jsonl.gz")
        subs = [x for x in ep.get("submissions") or [] if x.get("accepted")]
        dam = {x.get("day") for x in subs if x["tool"] == "submit_dam_offers" and not x.get("as")}
        rt = sum(x["tool"] == "submit_rt_offers" and not x.get("as") for x in subs)
        reserves = any(x.get("as") for x in subs) or any(
            v for d in ep["dates"] for part in ("dam", "rt")
            for h in ((ep.get(part) or {}).get(d, {}).get("as_award_mw") or []) for v in (h or {}).values())
        if not pick and (not dam or rt < 2):
            continue
        score, why = hh.score(ep)
        cands.append({"model": r["model"], "task_id": r["task_id"], "episode": r["episode"], "split": r["split"],
                      "score": round(score + 0.25 * len(dam) + 0.8 * reserves, 3),
                      "why": f"{why}; day-ahead markets bid {len(dam)}, real-time re-offers {rt}, reserves "
                             f"{'won' if reserves else 'none'}, {r['split']}"
                             + ("; chosen with --hero" if pick else "")})
    if pick and not cands:
        raise SystemExit(f"--hero {pick}: no scored API-model run of that window")
    post = [c for c in cands if c["split"] == "post_cutoff"]
    return max(post or cands, key=lambda c: c["score"], default=None)


def leaks(out: Path, extra: list[str]) -> None:
    """The folder's text files scanned as the Hub's surfaces are: keys and token shapes (agentenv-hf), hosts and
    addresses (hub_results.LEAK), and the desk's real site and operator names (design decision D9)."""
    hr, hd = module("hub_results", "scripts/hub_results.py"), module("hub_desk", "scripts/hub_desk.py")
    files = {p.relative_to(out).as_posix(): p.read_bytes() for p in sorted(out.rglob("*"))
             if p.is_file() and p.suffix != ".png"}
    files = {k: re.sub(rb"base64,[\w+/=]+", b"base64,", v) if k.endswith(".svg") else v for k, v in files.items()}
    hr.leaks(files)
    hd.anonymous(files, hd.names(ROOT) + extra)


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def pc(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    return f"{'−' if x < -5e-4 else '+' if sign and x > 5e-4 else ''}{abs(100 * x):.1f}"


def pci(b: dict, sign: bool = False, unit: str = "%") -> str:
    if b.get("mean") is None:
        return "—"
    return f"{pc(b['mean'], sign)}{unit} [{pc(b['ci'][0], sign)}, {pc(b['ci'][1], sign)}]"


def r2(b: dict, sign: bool = False) -> str:
    if b.get("mean") is None:
        return "—"
    f = (lambda v: f"{v:+.2f}" if sign else f"{v:.2f}")  # noqa: E731
    return f"{f(b['mean'])} [{f(b['ci'][0])}, {f(b['ci'][1])}]".replace("-", "−")


def usd_ci(b: dict, sign: bool = False) -> str:
    if b.get("mean") is None:
        return "—"
    return f"{money_s(b['mean'], sign)} [{money_s(b['ci'][0], sign)}, {money_s(b['ci'][1], sign)}]"


def usd(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def table(head: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
                     + ["| " + " | ".join(r) + " |" for r in rows])


def picture(name: str, alt: str) -> str:
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="figures/{name}-dark.png">'
            f'<img src="figures/{name}.png" width="660" alt="{alt}"></picture>')


def readme(s: dict) -> str:
    ms, refs, sp = s["models"], s["references"], s["splits"]
    who = {k: m["name"] for k, m in ms.items()} | {"operator_replay": "the operator's bids, replayed"}
    t1 = table(["model", "harness", "n", "C", "C, pre_cutoff", "C, post_cutoff", "R", "P", "$ / window"],
               [[f"**{m['name']}**", f"{m['harness']} · {m['setting']}", str(m["n"]), pci(m["all"]["C"]),
                 pci(m["pre_cutoff"]["C"]), pci(m["post_cutoff"]["C"]), r2(m["all"]["R"]), usd_ci(m["all"]["P"]),
                 usd(m["cost"]["usd_per_window"])] for m in ms.values()])
    t2 = table(["paired gap", "n", "Δ C, pts", "Δ R", "Δ P", "ahead (windows)", "fronts ahead"],
               [[f"{who[b['a']]} − {who[b['b']]}", str(b["all"]["n"]), pci(b["all"]["C"], True, ""),
                 r2(b["all"]["R"], True) if "R" in b["all"] else "—", usd_ci(b["all"]["P"], True),
                 f"{100 * b['all']['P'].get('ahead', 0):.0f}%", f"{b['all']['P'].get('fronts_ahead', '—')}/"
                 f"{b['all']['P']['fronts']}"] for b in s["paired"].values() if b["b"] != "operator_replay"])
    t3 = table(["model", "n", "P − operator, all", "C − operator, all, pts", "C − operator, pre_cutoff",
                "C − operator, post_cutoff"],
               [[ms[b["a"]]["name"], str(b["all"]["n"]), usd_ci(b["all"]["P"], True), pci(b["all"]["C"], True, ""),
                 pci(b["pre_cutoff"]["C"], True, ""), pci(b["post_cutoff"]["C"], True, "")]
                for b in s["paired"].values() if b["b"] == "operator_replay"])
    t4 = table(["model", "Δ C, pts", "Δ R", "Δ P"],
               [[m["name"], pci(m["split_gap"]["C"], True, ""), r2(m["split_gap"]["R"], True),
                 usd_ci(m["split_gap"]["P"], True)] for m in ms.values()])
    t5 = table(["reference", "C", "C, pre_cutoff", "C, post_cutoff", "P"],
               [[r["label"], pci(r["all"]["C"]), pci(r["pre_cutoff"]["C"]), pci(r["post_cutoff"]["C"]),
                 usd_ci(r["all"]["P"])] for r in refs.values()])
    tok = ("input", "cached", "cache_write", "output", "reasoning")
    t6 = table(["model", "$ / window", "basis", *[f"{k.replace('_', ' ')} tok" for k in tok], "turns", "wakes",
                "desk calls", "own-tool calls", "shell", "reminders", "rejected"],
               [[m["name"], usd(m["cost"]["usd_per_window"]),
                 "GPU time" if m["cost"]["basis"] == "gpu_time" else "list price",
                 *[f"{m['tokens_per_window'].get(k, 0):,.0f}" for k in tok],
                 *[("—" if m["behaviour"][k] is None else f"{m['behaviour'][k]:g}") for k in (
                     "turns", "wakes", "desk_calls", "own_tool_calls", "shell_calls", "reminders", "rejected")]]
                for m in ms.values()])
    t7 = table(["model", "attempts", "scored", "failed", "extra", "windows retried", "windows missing", "failures",
                "spend, all attempts"],
               [[m["name"], str(m["attempts"]["total"]), str(m["attempts"]["scored"]), str(m["attempts"]["failed"]),
                 str(m["attempts"]["extra"]), str(m["attempts"]["windows_retried"]),
                 str(m["attempts"]["windows_missing"]),
                 ", ".join(f"{k} ×{v}" for k, v in m["attempts"]["failure_kinds"].items()) or "—",
                 usd(m["cost"]["usd_all_attempts"])] for m in ms.values()])
    off = [x for x in s["attempts"] if x["role"] != "scored"]
    t8 = table(["model", "window", "attempt", "role", "status", "kind", "error"],
               [[who[x["model"]], x["task_id"], str(x["attempt"]), x["role"], x["status"], x["kind"] or "—",
                 (x["error"] or "—").replace("|", "/")[:120]] for x in off]) if off else "None."
    fr = table(["front", "split", "kind", "what happened"],
               [[f["dates"], f["split"], f["kind"], f["why"]] for f in s["fronts"]])
    gpu = next((m["cost"]["gpu"] for m in ms.values() if m["cost"].get("gpu")), None)
    run = s["run"]
    prices = "; ".join(f"`{k}` {v['in']}/{v['cached']}/{v['write']}/{v['out']}" for k, v in run[
        "prices_per_mtok"].items() if v["in"])
    fake = ("> **FAKE DATA.** Synthesized from the pilot records to exercise this pipeline; no benchmark run is "
            "behind any number here.\n\n" if s["fake"] else "")
    deferred = "".join(f"\n\n{x}" for x in s.get("deferred") or [])
    lead = s["lead_rule"]["text"]
    diffs = s["regraded"]["diffs"]
    lines = [
        f"# GridSimEnv desk v4 benchmark: results on `{s['pack']}`", "", fake.rstrip(), "" if fake else None,
        f"{s['n_windows']} three-day windows ({s['n_fronts']} real ERCOT weather fronts × {len(s['sites'])} real "
        f"batteries), {len(ms)} models, each in its own vendor's agent harness at high effort. C, the headline, is "
        "hindsight capture (P − P_idle)/(P_hind − P_idle), the share of the hindsight optimum's profit over idle; R "
        "the contract reward (anchor 1.0, idle 0.2); P the settled ERCOT statement in $ per window. "
        f"`pre_cutoff`: {sp['pre_cutoff']['windows']} windows, January to May 2026; `post_cutoff`: "
        f"{sp['post_cutoff']['windows']} windows, July and August 2026, after every model's reported training "
        f"cutoff. Brackets: 95% CIs, a block bootstrap over the {s['n_fronts']} fronts (each split's "
        f"{len(sp['pre_cutoff']['fronts'])} within it).", "",
        picture("cost-vs-score", "Hindsight capture against cost per window, one point per model"), "",
        t1 + deferred, "", lead, "", picture("splits", "Hindsight capture before and after the training cutoffs"), "",
        "## Paired gaps (the windows both played)", "", t2, "",
        "## Against the real operator's bids, replayed through the same clearing and settlement", "", t3, "",
        "## Post-cutoff minus pre-cutoff, each model", "",
        "The halves hold different windows, so each split's fronts are drawn apart (a stratified block bootstrap).",
        "", t4, "", "## References (every window, from the frozen refs)", "", t5, "",
        "## Cost, tokens and behaviour (mean per scored window)", "", t6, "",
        "## Attempts, failures and retries", "", t7, "", t8, "", "## Method", "",
        f"- Pack `{s['pack']}`: {s['n_windows']} windows; references from the pack's task rows (anchor 1.5/spread, "
        "frozen at `desk-v4-freeze`).", "", fr, "",
        "- Every episode is a plain `agent-env run` of the bench bundle (`scripts/desk_bench.py`)"
        + (f" at `{run['bundle']}`" if run.get("bundle") else "")
        + (" on EC2 boxes with local Docker (route C)" if run.get("route") == "ec2" else "")
        + (f", agentenv-framework {run['framework']}" if run.get("framework") else "") + "; harnesses: "
        + ", ".join(f"{k} {v}" for k, v in run["harness_versions"].items()) + "; budget: "
        + ", ".join(f"{k} {v}" for k, v in (run.get("budget") or {}).items())
        + f"; core {', '.join(run['core_versions'])}.",
        "- A model's scored attempt on a window is its first that reached the grade; earlier attempts are retries "
        "(infrastructure failures), later ones extra and never scored; a window no attempt reached is missing and "
        "never imputed (each model's n says how many it has).",
        f"- Every grade replayed from its Episode JSON against the frozen refs; {len(diffs)} differ"
        f"{'s' if len(diffs) == 1 else ''} from the run's own verifier grade"
        + (": " + "; ".join(f"{who[d['model']]} {d['task_id']}" for d in diffs[:8]) if diffs else "") + ".",
        f"- CIs: {s['ci']['method']}; {s['ci']['resamples']:,} resamples, seed {s['ci']['seed']}.",
        "- Cost: tokens from the harness trajectories at public list prices, $ per million tokens "
        f"input/cached/cache write/output: {prices}." + (f" Open weights: {gpu['note']}." if gpu else ""),
        *(["- Passed over under the run folders: " + ", ".join(f"{k} ×{v}" for k, v in s["skipped"].items()) + "."]
          if s.get("skipped") else []),
        *([f"- Redacted from the Episode JSON: {sum(s['redactions'].values())} occurrences of "
           f"{len(s['redactions'])} term{'s' if len(s['redactions']) > 1 else ''} the leak scan refused."]
          if s.get("redactions") else []),
        *[f"- Deviation: {d}" for d in s.get("deviations") or []],
        *[f"- Known env defect: {d}" for d in s.get("defects") or []],
        *[f"- {n}" for n in s.get("notes") or []],
        "- Files: `summary.json`, `grades.jsonl.gz` (one row per model and window), `episodes/<model>/*.json.gz` "
        "(Episode JSON with the run's own grade), `figures/`.", ""]
    return "\n".join(x for x in lines if x is not None)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, action="append", required=True, help="a folder of run folders (recursive)")
    ap.add_argument("--pack", default="desk-v4-bench")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "desk-v4-bench")
    ap.add_argument("--qwen-gpu", default="L4", choices=sorted(GPU_USD_PER_S), help="the open model endpoint's GPU")
    ap.add_argument("--qwen-gpu-hours", type=float, help="the endpoint's GPU-hours as billed; default: the union of "
                                                          "its runs' intervals, each plus the scale-down window")
    ap.add_argument("--ec2-price", action="append", default=[], metavar="TYPE=USD_PER_HOUR",
                    help="route C: another GPU box type's on-demand price (g5.xlarge and g5.2xlarge are known)")
    ap.add_argument("--deferred", action="append", default=[], metavar="TEXT",
                    help="a pre-registered model that did not run, as the card and README state it")
    ap.add_argument("--block-alias", action="append", default=[], metavar="DATE=FRONT")
    ap.add_argument("--model", action="append", default=[], metavar="MODEL_ID=KEY:NAME[:FAMILY]",
                    help="label a model the table lacks, e.g. a fine-tuned Qwen3-4B in the qwen family")
    ap.add_argument("--framework", help="the agentenv-framework version the runs used")
    ap.add_argument("--bundle", help="the bench bundle's tag or commit the runs played")
    ap.add_argument("--prereg", help="the pre-registration's path in the repo, e.g. docs/prereg/v4-bench.md")
    ap.add_argument("--deviation", action="append", default=[], help="a deviation from the pre-registration; "
                    "{retries} becomes each model's count of infrastructure retries")
    ap.add_argument("--defect", action="append", default=[], help="a known env defect")
    ap.add_argument("--note", action="append", default=[], help="a line for the README's method")
    ap.add_argument("--scan", action="append", default=[], metavar="TERM",
                    help="another term the leak scan refuses, beside the desk's real site and operator names")
    ap.add_argument("--redact", action="append", default=[], metavar="TERM",
                    help="replace TERM in every Episode JSON with <redacted>, counted in summary.json (for a term the "
                         "leak scan stops on, such as a host an agent printed)")
    ap.add_argument("--hero", metavar="MODEL:TASK_ID", help="the lead GIF's episode, in place of the ranking's pick")
    ap.add_argument("--no-figures", action="store_true")
    a = ap.parse_args()
    tasks = {t["task_id"]: t for t in load_tasks(a.pack)}
    fr, front_of = fronts(a.pack, tasks, dict(x.split("=", 1) for x in a.block_alias))
    atts, skipped = load(a.runs, a.pack, tasks, labels_of(a.model))
    if not atts:
        raise SystemExit(f"no attempts on {a.pack} under {', '.join(map(str, a.runs))}")
    fake = {x["fake"] for x in atts}
    if len(fake) > 1:
        raise SystemExit("FAKE and real attempts are mixed under --runs")
    labs = {x["label"]["key"]: x["label"] for x in atts}
    EC2_USD_PER_H.update({k: float(v) for k, v in (x.split("=", 1) for x in a.ec2_price)})
    gpus = {}
    for k in (k for k, lab in labs.items() if lab["weights"] == "open"):
        xs = [x for x in atts if x["label"]["key"] == k]
        gpus[k] = ec2_share(xs) if all(x.get("box") for x in xs) else gpu_share(xs, a.qwen_gpu, a.qwen_gpu_hours)
    rows, log = windows(atts, tasks, front_of)
    s = summarize(a, tasks, fr, front_of, rows, log, labs, gpus, [x["episode"] for x in atts if x["episode"]],
                  fake.pop())
    out = a.out
    out.mkdir(parents=True, exist_ok=True)
    s["redactions"] = episodes_out(atts, rows, out, a.redact) or None
    s["skipped"] = dict(skipped) or None
    with gzip.GzipFile(out / "grades.jsonl.gz", "wb", mtime=0) as f:
        f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows).encode())
    s["hero"] = hero(s, rows, out, a.hero)
    (out / "summary.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n")
    if not a.no_figures:
        shutil.rmtree(out / "figures", ignore_errors=True)
        (out / "figures").mkdir()
        for name, data in module("hub_desk", "scripts/hub_desk.py").bench_figures(s).items():
            (out / "figures" / name).write_bytes(data)
    (out / "README.md").write_text(readme(s))
    leaks(out, a.scan)
    for k, m in s["models"].items():
        c = m["all"]["C"]
        print(f"{k:6} n {m['n']:2}  C {c['mean']} {c['ci']}  ${m['cost']['usd_per_window']}/window  "
              f"attempts {m['attempts']['total']} (failed {m['attempts']['failed']})")
    print(f"{'FAKE ' if s['fake'] else ''}results in {out}")


if __name__ == "__main__":
    main()
