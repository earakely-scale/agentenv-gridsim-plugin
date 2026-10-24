"""Reference live days for the viewer, played through gridsim_core.live: the naive plan (v1's foresight DP as the DA
position and the schedule, never re-planned) and the rolling anchor (re-planned at every watch), as gridsim.episode/v2
JSON.

usage: python scripts/live_reference_episodes.py [--out results/runs/live-reference] [--tasks ID ...]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core.live import hourly_plan, naive_policy, play, roll_policy  # noqa: E402
from gridsim_core.task import battery_of, load_pack  # noqa: E402

PACKS = ("gridsim-live-showcase", "gridsim-live-eval", "fixtures-live")
TASKS = {
    "live-v2-2023-09-06-HB_NORTH-2h-l": ("roll", "naive"),
    "live-v2-2023-09-06-LZ_HOUSTON-2h-l": ("roll",),
    "live-v2-2021-02-15-HB_HOUSTON-2h-i": ("roll",),
    "live-v2-2024-01-02-LZ_CPS-1h-y-derate": ("roll",),
}
MODELS = {"roll": "reference/rolling-anchor", "naive": "reference/naive"}
SAY = {
    "roll": "The rolling anchor: the naive DA position at 2 pm the day before, then at every watch the exact plan "
            "over the open intervals on DA prices plus the latest real-time basis, decaying over two hours. It reads "
            "no bulletin.",
    "naive": "Naive: the exact plan on the day-ahead prices, committed as the DA position and the schedule at 2 pm "
             "the day before and never changed.",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "live-reference")
    p.add_argument("--tasks", nargs="*")
    args = p.parse_args(argv)
    rows = {r["task_id"]: r for pack in PACKS for r in load_pack(pack)}
    args.out.mkdir(parents=True, exist_ok=True)
    for tid in args.tasks or TASKS:
        task = rows[tid]
        for kind in TASKS.get(tid, ("roll", "naive")):
            policy = roll_policy() if kind == "roll" else naive_policy(hourly_plan(battery_of(task), task["prices"]))
            s = play(task, "foresight", None, policy, reference=False)
            ep = s.episode(bundle="reference", path="ref", model=MODELS[kind],
                           messages=[{"role": "assistant", "content": SAY[kind]}])
            out = args.out / f"{tid}-foresight-{kind}.json"
            out.write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
            print(f"{out.name}: profit {ep['profit_usd']:,.0f} reward {ep['reward']:.3f} capture "
                  f"{ep['capture_vs_hindsight']:.3f} commits {sum(c['accepted'] for c in ep['commits'])} "
                  f"notices {len(ep['notices'])} audit {ep['audit']['ok']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
