"""The v2 pilot's pre-registered analysis (docs/prereg/v2-pilot.md) from the sweeps' replay-verified Episode JSON v2
and results.jsonl: R on the anchor scale, hindsight capture against naive's and the anchor's on the same days, the
beats-naive and beats-anchor rates, the re-plan rate, refusals, audit failures, cost and turns, overall and on notice
and quiet days, with paired 95% bootstrap CIs over days; the hero day apart, never counted."""

import argparse
import json
import random
import statistics
from pathlib import Path

from agentenv_gridsim import live_tasks
from agentenv_gridsim.sweep import slug

RUNS = Path("results/runs")
EPS = 1e-9
BOOT = 2000


def _mean(xs: list[float]) -> float | None:
    return statistics.mean(xs) if xs else None


def ci(xs: list[float], seed: int = 0) -> list[float] | None:
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(xs, k=len(xs))) for _ in range(BOOT))
    return [means[int(0.025 * BOOT)], means[int(0.975 * BOOT)]]


def day(e: dict, row: dict, task: dict) -> dict:
    """One scored day's pilot fields from its Episode JSON, its results row and its pack row."""
    r = e["references"]
    head = r["p_hind"] - r["p_idle"]
    p = e["profit_usd"]
    later = [w["index"] for w in e["watches"][1:]]
    replans = {c["watch"] for c in e["commits"] if c["tool"] == "commit_schedule" and c["accepted"] and c["watch"] >= 1}
    agent_watches = {s["watch"] for s in e["steps"]}
    return {"task_id": e["task_id"], "kind": task["tags"]["day_kind"], "point": task["settlement_point"],
            "notice_watches": task["tags"]["notice_watches"], "reward": e["reward"], "naive_reward": e["naive_reward"],
            "capture": (p - r["p_idle"]) / head, "naive_capture": (r["p_naive"] - r["p_idle"]) / head,
            "anchor_capture": (r["p_roll"] - r["p_idle"]) / head,
            "beats_naive": p > r["p_naive"] + EPS, "beats_anchor": p > r["p_roll"] + EPS,
            "ties_naive": abs(p - r["p_naive"]) <= EPS, "anchor_equals_naive": abs(r["p_roll"] - r["p_naive"]) <= EPS,
            "later_watches": len(later), "replan_watches": len(replans & set(later)),
            "reached": max(agent_watches) if agent_watches else 0,
            "anchor_replans": max(r["roll"]["commits"] - 1, 0),
            "refused_commits": sum(not c["accepted"] for c in e["commits"]),
            "commits": sum(c["accepted"] for c in e["commits"]), "planning_calls": row.get("checks"),
            "finished": row.get("end_reason") == "done", "audit_ok": e["audit"]["ok"],
            "cost_usd": row.get("priced_cost_usd") if row.get("priced_cost_usd") is not None else row.get("cost_usd"),
            "turns": row.get("turns"), "profit_usd": p, "p_naive": r["p_naive"], "p_roll": r["p_roll"],
            "p_hind": r["p_hind"]}


def summary(days: list[dict]) -> dict:
    if not days:
        return {"n": 0}
    d_naive = [d["capture"] - d["naive_capture"] for d in days]
    d_anchor = [d["capture"] - d["anchor_capture"] for d in days]
    later = sum(d["later_watches"] for d in days)
    out = {"n": len(days),
           "reward": _mean([d["reward"] for d in days]), "reward_ci": ci([d["reward"] for d in days]),
           "naive_reward": _mean([d["naive_reward"] for d in days]),
           "reward_minus_naive": _mean([d["reward"] - d["naive_reward"] for d in days]),
           "reward_minus_naive_ci": ci([d["reward"] - d["naive_reward"] for d in days]),
           "reward_at_1": _mean([float(d["reward"] >= 1 - EPS) for d in days]),
           "capture": _mean([d["capture"] for d in days]), "capture_ci": ci([d["capture"] for d in days]),
           "naive_capture": _mean([d["naive_capture"] for d in days]),
           "anchor_capture": _mean([d["anchor_capture"] for d in days]),
           "capture_minus_naive": _mean(d_naive), "capture_minus_naive_ci": ci(d_naive),
           "capture_minus_anchor": _mean(d_anchor), "capture_minus_anchor_ci": ci(d_anchor),
           "beats_naive": _mean([float(d["beats_naive"]) for d in days]),
           "ties_naive": _mean([float(d["ties_naive"]) for d in days]),
           "beats_anchor": _mean([float(d["beats_anchor"]) for d in days]),
           "replan_rate": sum(d["replan_watches"] for d in days) / later if later else None,
           "replanned_days": _mean([float(d["replan_watches"] > 0) for d in days]),
           "anchor_replan_rate": sum(min(d["anchor_replans"], d["later_watches"]) for d in days) / later if later
           else None,
           "refused_commits": sum(d["refused_commits"] for d in days),
           "days_with_refusal": sum(d["refused_commits"] > 0 for d in days),
           "finished": _mean([float(d["finished"]) for d in days]),
           "audit_failures": sum(not d["audit_ok"] for d in days),
           "usd_per_episode": _mean([d["cost_usd"] for d in days if d["cost_usd"] is not None]),
           "turns": _mean([d["turns"] for d in days if d["turns"] is not None])}
    return out


def load(name: str) -> tuple[list[dict], list[dict]]:
    """A sweep's scored days (from its Episode JSON) and its runs that ended unscored."""
    out = RUNS / name
    spec = json.loads((out / "raw" / "sweep.json").read_text())
    rows = [json.loads(x) for x in (out / "raw" / "results.jsonl").read_text().splitlines() if x.strip()]
    tasks = {r["task_id"]: r for r in live_tasks.pack_rows(spec["pack"])}
    days, unscored = [], []
    for task_id in spec["tasks"]:
        mine = [r for r in rows if r["task_id"] == task_id]
        scored = next((r for r in mine if r["outcome"] == "scored"), None)
        path = out / f"{task_id}-{slug(scored['model'])}-r{scored['rep']}.json" if scored else None
        if scored and path.is_file():
            days.append(day(json.loads(path.read_text()), scored, tasks[task_id]))
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return days, unscored


def spend(name: str) -> float:
    rows = (RUNS / name / "raw" / "results.jsonl").read_text().splitlines()
    return sum(json.loads(x).get("cost_usd") or 0.0 for x in rows if x.strip())


def _f(x, fmt: str = ".3f") -> str:
    return "–" if x is None else format(x, fmt)


def _ci(m: dict, key: str) -> str:
    c = m.get(key + "_ci")
    return _f(m.get(key)) + (f" ({_f(c[0])} to {_f(c[1])})" if c else "")


def table(cells: list[tuple[str, dict]]) -> list[str]:
    """Two tables: the scores against naive, the anchor and hindsight; then how the model played."""
    scores = ["| Set | Days | R (95% CI) | Naive R | R − naive R (95% CI) | R = 1 | Capture (95% CI) | Naive capture "
              "| Anchor capture | Capture − naive (95% CI) | Capture − anchor (95% CI) | Beats naive | Ties naive "
              "| Beats anchor |", "|---|---:|---|---:|---|---:|---|---:|---:|---|---|---:|---:|---:|"]
    play = ["| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits "
            "| Audit failures | $/episode | Turns |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label, m in cells:
        if not m["n"]:
            scores.append(f"| {label} | 0 |" + " – |" * 12)
            play.append(f"| {label} | 0 |" + " – |" * 8)
            continue
        scores.append(" | ".join([
            f"| {label}", str(m["n"]), _ci(m, "reward"), _f(m["naive_reward"]), _ci(m, "reward_minus_naive"),
            _f(m["reward_at_1"]), _ci(m, "capture"), _f(m["naive_capture"]), _f(m["anchor_capture"]),
            _ci(m, "capture_minus_naive"), _ci(m, "capture_minus_anchor"), _f(m["beats_naive"]),
            _f(m["ties_naive"]), _f(m["beats_anchor"])]) + " |")
        play.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["replan_rate"]), _f(m["replanned_days"]), _f(m["anchor_replan_rate"]),
            _f(m["finished"]), f"{m['refused_commits']} on {m['days_with_refusal']} days", str(m["audit_failures"]),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}", _f(m["turns"], ".1f")]) + " |")
    return scores + [""] + play


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The pre-registered sweep (v2-pilot-sol).")
    ap.add_argument("--amend", help="The labelled amendment sweep: the main sweep's unscored runs at $1.20.")
    ap.add_argument("--hero", help="The hero day's sweep (display only, never counted).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    days, unscored = load(args.main)
    sets = {"primary": days}
    if args.amend:
        extra, still = load(args.amend)
        sets["amended"] = days + extra
        unscored = [u | {"amendment": next((s["why"] for s in still if s["task_id"] == u["task_id"]), "scored")}
                    for u in unscored]
    out = {"sets": {}, "unscored": unscored, "spend_usd": {n: round(spend(n), 4) for n in
                                                              [args.main, args.amend, args.hero] if n}}
    lines: list[str] = []
    for name, ds in sets.items():
        cells = [(f"{name}: all", summary(ds)), (f"{name}: notice", summary([d for d in ds if d["kind"] == "notice"])),
                 (f"{name}: quiet", summary([d for d in ds if d["kind"] == "quiet"])),
                 (f"{name}: anchor ≠ naive", summary([d for d in ds if not d["anchor_equals_naive"]])),
                 (f"{name}: a notice watch", summary([d for d in ds if d["notice_watches"] > 0]))]
        out["sets"][name] = {label: m for label, m in cells}
        lines += table(cells) + [""]
    if args.hero:
        hero, missing = load(args.hero)
        out["hero"] = {"days": hero, "unscored": missing}
        lines += ["Hero (display only): " + ("; ".join(
            f"{h['task_id']}: R {_f(h['reward'])} (naive {_f(h['naive_reward'])}), capture {_f(h['capture'])} "
            f"(naive {_f(h['naive_capture'])}, anchor {_f(h['anchor_capture'])}), profit ${h['profit_usd']:,.0f} "
            f"(naive ${h['p_naive']:,.0f}, anchor ${h['p_roll']:,.0f}, hindsight ${h['p_hind']:,.0f}), re-planned "
            f"{h['replan_watches']} of {h['later_watches']} later watches, ${h['cost_usd']:.4f}, {h['turns']} turns"
            for h in hero) or f"unscored: {missing}"), ""]
    lines += ["Unscored: " + ("; ".join(f"{u['task_id']} ({u['why']}, {u['attempts']} attempts"
                                        + (f", amendment: {u['amendment']}" if "amendment" in u else "") + ")"
                                        for u in unscored) or "none") + ".",
              "Spend: " + ", ".join(f"{n} ${v:.2f}" for n, v in out["spend_usd"].items()) + "."]
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
