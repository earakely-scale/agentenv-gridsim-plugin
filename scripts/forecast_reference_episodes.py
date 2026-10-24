"""Reference v4 forecast windows for the viewer's race lanes, played through gridsim_core.forecast.Session: the rolling
re-planner on the guide's P50 (the anchor), its three-scenario mean, the persistence re-planner and the naive DAM
bidder, as gridsim.episode/v4 JSON, each audited (replayed call by call) before it is written.

usage: python scripts/forecast_reference_episodes.py [--packs ...] [--tasks ID ...] [--out DIR]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import forecast as F  # noqa: E402
from gridsim_core.task import data_root, load_pack  # noqa: E402

PACKS = ("ercot-front-v4-showcase", "ercot-front-v4-eval", "fixtures-forecast")
LANES = {"anchor": ("front", F.anchor_policy("p50")), "roll3": ("front", F.anchor_policy("mean3")),
         "blind": ("blind", F.anchor_policy("persist")), "naive": ("front", F.naive_policy),
         "lite-anchor": ("front-lite", F.anchor_policy("p50"))}
MODELS = {"anchor": "reference/rolling-p50", "roll3": "reference/rolling-mean3", "blind": "reference/persistence",
          "naive": "reference/naive-dam", "lite-anchor": "reference/rolling-p50"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "forecast-reference")
    p.add_argument("--packs", nargs="*", default=[x for x in PACKS if (data_root() / x).is_dir()])
    p.add_argument("--tasks", nargs="*")
    p.add_argument("--lanes", nargs="*", default=list(LANES))
    args = p.parse_args(argv)
    rows = {r["task_id"]: r for pack in args.packs for r in load_pack(pack)}
    args.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for tid in args.tasks or list(rows)[:6]:
        task = rows[tid]
        for lane in args.lanes:
            tier, policy = LANES[lane]
            s = F.play(task, tier, policy, reference=False)
            ep = s.episode(bundle="reference", path="ref", model=MODELS[lane])
            if not ep["audit"]["ok"]:
                bad += 1
                print(f"{tid} {lane}: audit failed {ep['audit']['problems'][:2]}", flush=True)
                continue
            (args.out / f"{tid}-{lane}.json").write_text(json.dumps(ep, separators=(",", ":")) + "\n")
            print(f"{tid} {lane}: reward {ep['reward']} profit ${ep['profit_usd']:,.0f}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
