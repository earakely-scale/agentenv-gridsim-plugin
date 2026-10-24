"""The v3 pilot's tasks (docs/prereg/v3-pilot.md): one seeded draw over ercot-hybrid-v3-eval, round-robin over the AS
strata (low, mid, high). Each pick takes the candidate of its stratum on a date not drawn yet, whose settlement point
and then month the stratum has drawn least, then the point and month the whole draw has drawn least, ties broken by a
seeded shuffle. Picks 1-30 (10 per stratum) are the reserves-tier main column, picks 31-40 the energy-tier secondary
column; the showcase day is fixed."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from agentenv_gridsim import hybrid_tasks

SEED = 4322
PACK = "ercot-hybrid-v3-eval"
STRATA = ("low", "mid", "high")
MAIN, SECONDARY = 30, 10
SHOWCASE_PACK = "ercot-hybrid-v3-showcase"
SHOWCASE = "hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150"
COLUMNS = {"main": ("reserves", PACK), "energy": ("energy", PACK), "showcase": (None, SHOWCASE_PACK)}


def draw(rows: list[dict], n: int, seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    order = sorted(rows, key=lambda r: r["task_id"])
    rng.shuffle(order)
    rank = {r["task_id"]: i for i, r in enumerate(order)}
    points, months, dates, out = Counter(), Counter(), set(), []
    by = {s: (Counter(), Counter()) for s in STRATA}
    for i in range(n):
        s = STRATA[i % len(STRATA)]
        sp, sm = by[s]
        taken = {r["task_id"] for r in out}
        pool = [r for r in order if r["tags"]["as_stratum"] == s and r["task_id"] not in taken]
        r = min(pool, key=lambda r: (r["date"] in dates, sp[r["settlement_point"]], sm[r["date"][:7]],
                                     points[r["settlement_point"]], months[r["date"][:7]], rank[r["task_id"]]))
        out.append(r)
        dates.add(r["date"])
        for c, k in ((sp, r["settlement_point"]), (sm, r["date"][:7]), (points, r["settlement_point"]),
                     (months, r["date"][:7])):
            c[k] += 1
    return out


def capture(p: float, p_idle: float, p_hind: float) -> float | None:
    return round((p - p_idle) / (p_hind - p_idle), 6) if p_hind - p_idle > 1e-9 else None


def reward(p: float, p_idle: float, p_anchor: float) -> float:
    return round(min(1.0, max(0.0, 0.2 + 0.8 * (p - p_idle) / (p_anchor - p_idle))), 6)


def row(r: dict, tier: str) -> dict:
    """A picked day with the references the pre-registration states before any run."""
    refs, t = r["refs"], r["refs"][tier]
    b = t["baselines"]
    a = t["anchor"]
    out = {"task_id": r["task_id"], "tier": tier, "stratum": r["tags"]["as_stratum"], "point": r["settlement_point"],
           "date": r["date"], "site": r["site"]["site_id"], "watches": r["tags"]["watches"],
           "notice_day": r["tags"]["notice_day"], "deploy_day": r["tags"]["deploy_day"],
           "neg_hours": r["tags"]["neg_hours"], "as_value_usd": r["tags"]["as_value_usd"],
           "anchor_minus_idle_usd": round(t["p_anchor"] - refs["p_idle"], 2),
           "anchor_capture": capture(t["p_anchor"], refs["p_idle"], t["p_hind"]),
           "anchor_commits": a["commits"], "anchor_as_usd": round(a["as_usd"], 2),
           "anchor_ftp_usd": round(a["ftp_usd"], 2), "anchor_governor_hours": a["governor_hours"],
           "v2_energy": b["v2_energy"]["reward"], "sponge": b["sponge"]["reward"]}
    if tier == "reserves":
        out |= {"as_hog": b["as_hog"]["reward"],
                "energy_only": reward(t["p_energy_only"], refs["p_idle"], t["p_anchor"])}
    return out


def column(name: str) -> list[dict]:
    tier, pack = COLUMNS[name]
    if name == "showcase":
        r = next(x for x in hybrid_tasks.pack_rows(pack) if x["task_id"] == SHOWCASE)
        return [row(r, t) for t in ("energy", "reserves")]
    rows = hybrid_tasks.eligible(hybrid_tasks.eligible(hybrid_tasks.pack_rows(PACK), "reserves"), "energy")
    picked = draw(rows, MAIN + SECONDARY)
    return [row(r, tier) for r in (picked[:MAIN] if name == "main" else picked[MAIN:])]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=list(COLUMNS), default="main")
    ap.add_argument("--json", type=Path, help="Write every column's days with their references here.")
    args = ap.parse_args()
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "seed": SEED, "showcase_pack": SHOWCASE_PACK,
                                         "columns": {c: column(c) for c in COLUMNS}}, indent=1) + "\n")
    print(",".join(dict.fromkeys(t["task_id"] for t in column(args.column))))


if __name__ == "__main__":
    main()
