"""The v5 pilot's floors (docs/prereg/v5-pilot.md), one seeded draw over gridsim-market-eval. The floor-day column
takes DAY_PEAK peak floors (>= 2 impact hours) and the rest base floors, all from the pack's floor-day subset; the
floor-sprint column takes every peak floor, the floor-day column's base floors (so every floor-day floor is also played
at floor-sprint) and base floors drawn until it holds SPRINT floors. Each draw takes the candidate whose month has been
drawn least, ties broken by a seeded shuffle. The smoke floors come from gridsim-market-train's months in git (the env
image holds no overflow days), the showcase floors are the showcase pack's six. The baselines are core's
baseline_plays."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from build_market_days import SHIP_FROM

from agentenv_gridsim import market_tasks
from gridsim_core.market import baseline_plays

SEED = 5324
PACK = "gridsim-market-eval"
SHOWCASE_PACK = "gridsim-market-showcase"
SMOKE_PACK = "gridsim-market-train"
SPRINT, DAY, DAY_PEAK, SMOKE = 30, 10, 4, 2
COLUMNS = ("sprint", "day", "showcase", "smoke-sprint", "smoke-day")


def peak(r: dict) -> bool:
    return r["tags"]["stratum"] == "peak"


def draw(pool: list[dict], n: int, months: Counter, rng: random.Random) -> list[dict]:
    order = sorted(pool, key=lambda r: r["task_id"])
    rng.shuffle(order)
    rank = {r["task_id"]: i for i, r in enumerate(order)}
    out = []
    for _ in range(min(n, len(order))):
        r = min((r for r in order if r not in out), key=lambda r: (months[r["date"][:7]], rank[r["task_id"]]))
        out.append(r)
        months[r["date"][:7]] += 1
    return out


def picks() -> dict[str, list[dict]]:
    rng = random.Random(SEED)
    rows = market_tasks.eligible(market_tasks.pack_rows(PACK), "floor-sprint")
    day_ok = {r["task_id"] for r in market_tasks.eligible(rows, "floor-day")}
    peaks = [r for r in rows if peak(r)]
    months = Counter()
    day = draw([r for r in peaks if r["task_id"] in day_ok], DAY_PEAK, months, rng)
    day += draw([r for r in rows if not peak(r) and r["task_id"] in day_ok], DAY - len(day), months, rng)
    taken = {r["task_id"] for r in day} | {r["task_id"] for r in peaks}
    sprint = peaks + [r for r in day if not peak(r)]
    sprint += draw([r for r in rows if r["task_id"] not in taken], SPRINT - len(sprint), months, rng)
    train = [r for r in market_tasks.pack_rows(SMOKE_PACK) if r["date"][:7] >= SHIP_FROM]
    smoke = draw(train, 2 * SMOKE, Counter(), rng)
    return {"sprint": sorted(sprint, key=lambda r: r["date"]), "day": sorted(day, key=lambda r: r["date"]),
            "showcase": market_tasks.pack_rows(SHOWCASE_PACK), "smoke-sprint": smoke[:SMOKE],
            "smoke-day": smoke[SMOKE:]}


def row(r: dict, tier: str) -> dict:
    """A picked floor with what the pre-registration states about it before any run, its baselines played in process
    at the tier under both scorings."""
    refs, t, a = r["refs"], r["refs"][tier], r["seats"]["A"]
    hind = t["p_br"] - refs["p_idle"]
    return {"task_id": r["task_id"], "tier": tier, "date": r["date"], "stratum": r["tags"].get("stratum"),
            "p_mw": a["p_mw"], "hours": round(a["e_mwh"] / a["p_mw"], 2), "eta": a["eta"], "c_deg": a["c_deg"],
            "impact_hours": refs.get("impact_hours"), "impact_hours_2usd": r["tags"].get("impact_hours_2usd"),
            "within_ns": r["fidelity"]["within_ns"], "notice_day": r["tags"].get("notice_day"),
            "season": r["tags"].get("season"), "neg_hours": r["tags"].get("neg_hours"),
            "anchor_minus_idle_usd": round(t["p_anchor"] - refs["p_idle"], 2),
            "anchor_capture": round((t["p_anchor"] - refs["p_idle"]) / hind, 6) if hind > 1e-6 else None,
            "baselines": {k: {x: v[x] for x in ("reward", "compliant", "welfare_ratio", "profit")}
                          for k, v in baseline_plays(r, tier).items()}}


def column(name: str) -> list[dict]:
    tier = "floor-sprint" if name in ("sprint", "smoke-sprint") else "floor-day"
    return [row(r, tier) for r in picks()[name]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=COLUMNS, default="sprint")
    ap.add_argument("--json", type=Path, help="Write every column's floors with their references here.")
    args = ap.parse_args()
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "seed": SEED, "showcase_pack": SHOWCASE_PACK,
                                         "smoke_pack": SMOKE_PACK, "columns": {c: column(c) for c in COLUMNS}},
                                        indent=1) + "\n")
    print(",".join(r["task_id"] for r in picks()[args.column]))


if __name__ == "__main__":
    main()
