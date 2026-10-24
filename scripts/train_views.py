"""The training views from path-B episodes (gridsim.episode/v1 with `trained`): LEVEL UP, one held-out day replayed at
successive checkpoints, and the race, up to four models on that day. Copies the episodes they use into --out with
levelup.json and race.json, which the Space build and the viewer read.

The day is picked by rule: the largest base-to-trained gain in reward among the days where the trained model scores
at least DOES_WELL; when no day reaches it, the largest gain, and the manifest says so.

usage: python scripts/train_views.py --episodes ~/agentenv-gridsim-plugin/results/train/episodes
       [--out results/runs/train] [--day TASK_ID]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOL = ("v1-board-sol-oneshot", "v1-board-sol-oneshot-amend", "v1-board-sol-full", "v1-board-sol-full-amend")
DOES_WELL = 0.85
RULE = (f"the largest base-to-trained gain in reward among held-out days where the trained model scores at least "
        f"{DOES_WELL}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--episodes", type=Path, required=True)
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "train")
    p.add_argument("--day", help="Override the rule with this task id (the manifest records the override).")
    args = p.parse_args(argv)
    eps = [e for f in sorted(args.episodes.rglob("*.json")) if (e := read(f))]
    days: dict[str, dict] = {}
    for e in eps:
        d = days.setdefault(e["task_id"], {"base": [], "sft": [], "grpo": []})
        d.setdefault(e["trained"], []).append(e)
    rows = []
    for tid, d in days.items():
        base, final = pick(d["base"]), final_of(d["grpo"])
        if base and final:
            rows.append((tid, r(final) - r(base), r(final), len({e["checkpoint_step"] for e in d["grpo"]})))
    if not rows:
        raise SystemExit(f"no day in {args.episodes} has both a base and a trained episode")
    good = [x for x in rows if x[2] >= DOES_WELL]
    if args.day:
        tid, note = args.day, f"day chosen by hand ({args.day}), not by the rule"
    else:
        tid = max(good or rows, key=lambda x: (x[1], x[3], x[2], x[0]))[0]
        note = None if good else (f"no held-out day reaches {DOES_WELL} for the trained model; this is the day "
                                  "with the largest gain")
    d = days[tid]
    frames = [e for e in (pick(d["base"]), pick(d["sft"])) if e]
    by_step: dict[int, list[dict]] = {}
    for e in d["grpo"]:
        by_step.setdefault(e["checkpoint_step"] if e["checkpoint_step"] is not None else 10**9, []).append(e)
    frames += [pick(by_step[s]) for s in sorted(by_step)]
    final = final_of(d["grpo"])
    lanes = [x for x in (pick(d["base"]), pick(d["sft"]), final) if x]
    if sol := sol_run(tid):
        lanes.append(sol)
    args.out.mkdir(parents=True, exist_ok=True)
    for e in {e["episode_id"]: e for e in frames + lanes}.values():
        (args.out / f"{e['episode_id']}.json").write_text(json.dumps(e, separators=(",", ":")))
    steps = [e["checkpoint_step"] for e in d["grpo"] if e["checkpoint_step"] is not None]
    model = final.get("model") or "trained model"
    levelup = {"schema": "gridsim.levelup/v1", "task_id": tid, "model": model, "rule": RULE, "note": note,
               "total_steps": max(steps, default=None), "gain": round(r(final) - r(frames[0]), 6),
               "frames": [{"episode_id": e["episode_id"], "trained": e["trained"], "step": e["checkpoint_step"],
                           "reward": e.get("reward")} for e in frames]}
    race = {"schema": "gridsim.race/v1", "task_id": tid,
            "lanes": [{"episode_id": e["episode_id"], "label": label(e)} for e in lanes[-4:]]}
    (args.out / "levelup.json").write_text(json.dumps(levelup, indent=1))
    (args.out / "race.json").write_text(json.dumps(race, indent=1))
    print(f"day {tid}: {len(frames)} frames, rewards {[round(r(e), 3) for e in frames]}; race {race['lanes']}"
          + (f"; NOTE {note}" if note else ""))
    return 0


def read(f: Path) -> dict | None:
    try:
        e = json.loads(f.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not (isinstance(e, dict) and e.get("schema") == "gridsim.episode/v1" and e.get("trained")):
        return None
    return e | {"trained": str(e["trained"]).lower()}


def r(e: dict) -> float:
    return e.get("reward") or 0.0


def pick(eps: list[dict]) -> dict | None:
    """The greedy (unseeded) episode when there is one, else the lowest seed."""
    return min(eps, key=lambda e: (e.get("seed") is not None, e.get("seed") or 0, e["episode_id"]), default=None)


def final_of(grpo: list[dict]) -> dict | None:
    """The final trained model: the unnumbered final eval when present, else the last checkpoint."""
    if not grpo:
        return None
    last = max(10**9 if e["checkpoint_step"] is None else e["checkpoint_step"] for e in grpo)
    return pick([e for e in grpo if (10**9 if e["checkpoint_step"] is None else e["checkpoint_step"]) == last])


def sol_run(tid: str) -> dict | None:
    for sweep in SOL:
        for f in sorted((ROOT / "results" / "runs" / sweep).glob(f"{tid}-*.json")):
            return json.loads(f.read_text()) | {"model_label": "GPT-6.1 Sol"}
    return None


def label(e: dict) -> str:
    if e.get("model_label"):
        return e["model_label"]
    name = (e.get("model") or "model").split("/")[-1]
    return {"base": f"{name} base", "sft": f"{name} SFT"}.get(e["trained"], f"{name} GRPO")


if __name__ == "__main__":
    sys.exit(main())
