"""The distillation's eval report (docs/prereg/desk-distill.md): per held-out window each side's C, the anchor's C,
the largest prompt and the compaction events from the meter, and the env's refusals per submit tool; then the primary
result, C(student) − C(base) over the windows graded for both, with a 95% window-block bootstrap.

    python scripts/desk_distill_eval.py --pack data/desk/desk-v4-win --side base=<bench dir> --side student=<bench dir>
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

import numpy as np

from gridsim_core.desk import load_tasks

SUBMITS = ("submit_dam_offers", "submit_rt_offers", "update_cop")
FULL_TOOLS = 29


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def meter(b: Path) -> dict[str, dict]:
    """Per window (MM-DD-Sxx): calls, largest prompt, generated tokens, output-cap stops, compactions (a drop in the
    conversation's length between two of its calls) and calls OpenCode sent without the MCP tools (fewer than 29)."""
    out: dict[str, dict] = {}
    rows = sorted(_jsonl(b / "meter.jsonl"), key=lambda r: r["t"])
    last: dict[str, int] = {}
    for r in rows:
        w = r.get("window")
        if not w:
            continue
        u = r.get("usage") or {}
        m = out.setdefault(w, {"calls": 0, "max_prompt": 0, "generated": 0, "length_stops": 0, "compactions": 0,
                               "tools_dropped": 0})
        m["calls"] += 1
        m["tools_dropped"] += r.get("tools", 0) < FULL_TOOLS
        m["max_prompt"] = max(m["max_prompt"], u.get("prompt_tokens") or 0)
        m["generated"] += u.get("completion_tokens") or 0
        m["length_stops"] += r.get("finish") == "length"
        if w in last and r["messages"] < last[w] // 2:
            m["compactions"] += 1
        last[w] = r["messages"]
    return out


def refusals(ep: dict) -> dict[str, list[int]]:
    out = {t: [0, 0] for t in SUBMITS}
    for t in ep.get("turns", []):
        for c in t.get("calls", []):
            if c["tool"] in out:
                r = c.get("result") or {}
                out[c["tool"]][0] += 1
                out[c["tool"]][1] += bool(r.get("error") or r.get("rejected") or r.get("as_rejected"))
    return out


def side(b: Path) -> dict[str, dict]:
    res = {r["task_id"]: r for r in _jsonl(b / "results.jsonl")}
    att = _jsonl(b / "attempts.jsonl")
    met = meter(b)
    out = {}
    for tid in {a["task_id"] for a in att} | set(res):
        r = res.get(tid)
        ep = {}
        if r:
            p = next(iter((b / "episodes").glob(f"{tid}.*.json")), None)
            ep = json.loads(p.read_text()) if p else {}
        out[tid] = {"graded": r is not None, "C": r["grade"]["capture"] if r else None,
                    "attempts": sum(a["task_id"] == tid for a in att),
                    "classes": [a["class"] for a in att if a["task_id"] == tid],
                    "wall_s": r.get("wall_s") if r else None, "box": r.get("instance") if r else None,
                    **met.get(tid[-9:], {}), "refusals": refusals(ep)}
    return out


def boot(diffs: dict[str, list[float]], n: int = 10000, seed: int = 0) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    blocks = list(diffs.values())
    means = []
    for _ in range(n):
        pick = rng.integers(0, len(blocks), len(blocks))
        vals = [x for i in pick for x in blocks[i]]
        means.append(statistics.fmean(vals))
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def report(a: argparse.Namespace) -> dict:
    tasks = {t["task_id"]: t for t in load_tasks(a.pack) if t["split"] == "eval"}
    anchor = {k: (t["refs"]["p_anchor"] - t["refs"]["p_idle"]) / (t["refs"]["p_hind"] - t["refs"]["p_idle"])
              for k, t in tasks.items()}
    sides = {name: side(Path(path)) for name, path in (s.split("=", 1) for s in a.side)}
    out: dict = {"windows": len(tasks), "sides": {}}
    for name, s in sides.items():
        graded = {k: v["C"] for k, v in s.items() if v["graded"] and k in tasks}
        by = {}
        for k, c in graded.items():
            by.setdefault(tasks[k]["dates"][0], []).append(c)
        ref = {t: [sum(v["refusals"][t][0] for v in s.values()), sum(v["refusals"][t][1] for v in s.values())]
               for t in SUBMITS}
        out["sides"][name] = {
            "graded": len(graded), "missing": sorted(set(tasks) - set(graded)),
            "C_mean": round(statistics.fmean(graded.values()), 4) if graded else None,
            "C_ci": [round(x, 4) for x in boot(by)] if by else None,
            "anchor_C_same_windows": round(statistics.fmean(anchor[k] for k in graded), 4) if graded else None,
            "max_prompt": max((v.get("max_prompt", 0) for v in s.values()), default=0),
            "windows_compacted": sum(v.get("compactions", 0) > 0 for v in s.values()),
            "compactions": sum(v.get("compactions", 0) for v in s.values()),
            "length_stops": sum(v.get("length_stops", 0) for v in s.values()),
            "calls_without_mcp_tools": sum(v.get("tools_dropped", 0) for v in s.values()),
            "refusals": {t: {"calls": c, "refused": r, "share": round(r / c, 4) if c else None}
                         for t, (c, r) in ref.items()}}
    if len(sides) == 2:
        (na, sa), (nb, sb) = sides.items()
        both = [k for k in tasks if sa.get(k, {}).get("graded") and sb.get(k, {}).get("graded")]
        diffs = {}
        for k in both:
            diffs.setdefault(tasks[k]["dates"][0], []).append(sb[k]["C"] - sa[k]["C"])
        d = [x for v in diffs.values() for x in v]
        lo, hi = boot(diffs) if d else (None, None)
        out["primary"] = {"diff": f"C({nb}) - C({na})", "windows": len(both), "blocks": len(diffs),
                          "mean": round(statistics.fmean(d), 4) if d else None,
                          "ci95": [round(lo, 4), round(hi, 4)] if d else None,
                          "better": sum(x > 1e-9 for x in d), "worse": sum(x < -1e-9 for x in d),
                          "student_beats_base": bool(d) and lo > 0}
    out["per_window"] = {k: {"anchor_C": round(anchor[k], 4),
                             **{n: {f: s.get(k, {}).get(f) for f in ("C", "attempts", "classes", "max_prompt",
                                                                       "compactions", "length_stops", "calls",
                                                                       "tools_dropped")}
                                for n, s in sides.items()}} for k in sorted(tasks)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--side", action="append", required=True, help="name=bench dir (results, attempts, meter)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    r = report(a)
    text = json.dumps(r, indent=1)
    if a.out:
        a.out.write_text(text + "\n")
    print(json.dumps({k: v for k, v in r.items() if k != "per_window"}, indent=1))


if __name__ == "__main__":
    main()
