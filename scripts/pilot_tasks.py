"""The v2 pilot's tasks (docs/prereg/v2-pilot.md): 20 notice and 20 quiet foresight days of gridsim-live-eval, drawn
with a fixed seed, round-robin over the settlement points in a shuffled order, one battery per point-day, a date not
yet drawn of that kind first (2024-07-12 alone holds 45 of the 136 quiet tasks)."""

import argparse
import json
import random
from pathlib import Path

from agentenv_gridsim import live_tasks

SEED = 4321
PACK = "gridsim-live-eval"
TIER = "foresight"
PER_KIND = 20
HERO = "live-v2-2023-09-06-HB_NORTH-2h-l"


def pick(rows: list[dict], kind: str, n: int, rng: random.Random) -> list[dict]:
    pool = sorted((r for r in rows if r["tags"]["day_kind"] == kind), key=lambda r: r["task_id"])
    points = sorted({r["settlement_point"] for r in pool})
    rng.shuffle(points)
    left = {p: [r for r in pool if r["settlement_point"] == p] for p in points}
    for p in points:
        rng.shuffle(left[p])
    out, dates = [], set()
    while len(out) < n:
        before = len(out)
        for p in points:
            fresh = [r for r in left[p] if r["date"] not in dates] or left[p]
            if len(out) < n and fresh:
                r = fresh[0]
                left[p] = [x for x in left[p] if x["date"] != r["date"]]
                dates.add(r["date"])
                out.append(r)
        if len(out) == before:
            raise SystemExit(f"only {len(out)} {kind} point-days in {PACK}")
    return out


def row(r: dict) -> dict:
    f = r["refs"]["roll"][TIER]
    head = r["refs"]["p_hind"] - r["refs"]["p_idle"]
    return {"task_id": r["task_id"], "kind": r["tags"]["day_kind"], "point": r["settlement_point"], "date": r["date"],
            "watches": r["tags"]["watches"], "notice_watches": r["tags"]["notice_watches"],
            "naive_reward": f["naive_reward"],
            "naive_capture": round((r["refs"]["p_naive"] - r["refs"]["p_idle"]) / head, 6),
            "anchor_capture": round((f["p_roll"] - r["refs"]["p_idle"]) / head, 6)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", type=Path, help="Also write the picked tasks with their kind, point and references.")
    args = ap.parse_args()
    rows = live_tasks.eligible(live_tasks.pack_rows(PACK), TIER)
    rng = random.Random(SEED)
    picked = [row(r) for kind in ("notice", "quiet") for r in pick(rows, kind, PER_KIND, rng)]
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "tier": TIER, "seed": SEED, "hero": HERO, "tasks": picked},
                                        indent=1) + "\n")
    print(",".join(t["task_id"] for t in picked))


if __name__ == "__main__":
    main()
