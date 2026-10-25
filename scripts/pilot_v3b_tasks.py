"""The v3 re-pilot's tasks under rules 3.1 (docs/prereg/v3-pilot-b.md), one seeded draw over ercot-hybrid-v3-eval.
Reserves column: every deployment day, then non-deployment days round-robin over the AS strata until each stratum
holds 10. Energy column: 10 days on oversized sites with PV AC / POI >= 1.25 (5 at 1.25, 5 at 1.4), on dates the
reserves column does not use. Each pick takes the candidate on a date not drawn yet whose settlement point and then
month its class has drawn least, then the point and month the column has drawn least, ties broken by a seeded
shuffle. The display days are fixed. The smoke plays three era-B days with ERCOT-measured drift from
ercot-hybrid-v3-train: a deployment day and a quiet day at the reserves tier, an oversized day at the energy tier."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from agentenv_gridsim import hybrid_tasks

SEED = 4325
PACK = "ercot-hybrid-v3-eval"
STRATA = ("low", "mid", "high")
PER_STRATUM = 10
RATIOS = ("1.25", "1.4")
PER_RATIO = 5
SHOWCASE_PACK = "ercot-hybrid-v3-showcase"
SHOWCASE = ("hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150", "hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150")
TRAIN = "ercot-hybrid-v3-train"
COLUMNS = {"main": "reserves", "energy": "energy", "showcase": "reserves", "smoke-reserves": "reserves",
           "smoke-energy": "energy"}


def ratio(r: dict) -> float:
    return round(r["site"]["pv_mwac"] / r["site"]["poi_mw"], 2)


def ratio_class(r: dict) -> str | None:
    x = ratio(r)
    return None if x < 1.245 else "1.25" if x < 1.3 else "1.4"


def draw(rows: list[dict], quota: dict[str, int], cls, fixed: list[dict], avoid: set[str], seed: int) -> list[dict]:
    """Round-robin over the classes with quota left; fixed rows are counted first and kept."""
    rng = random.Random(seed)
    order = sorted(rows, key=lambda r: r["task_id"])
    rng.shuffle(order)
    rank = {r["task_id"]: i for i, r in enumerate(order)}
    points, months, out = Counter(), Counter(), list(fixed)
    dates = set(avoid) | {r["date"] for r in fixed}
    by = {c: (Counter(), Counter()) for c in quota}
    left = dict(quota)

    def count(r):
        for c, k in ((points, r["settlement_point"]), (months, r["date"][:7])):
            c[k] += 1
        if cls(r) in by:
            by[cls(r)][0][r["settlement_point"]] += 1
            by[cls(r)][1][r["date"][:7]] += 1

    for r in fixed:
        count(r)
        if cls(r) in left:
            left[cls(r)] -= 1
    i = 0
    while any(v > 0 for v in left.values()):
        c = list(quota)[i % len(quota)]
        i += 1
        if left[c] <= 0:
            continue
        sp, sm = by[c]
        taken = {r["task_id"] for r in out}
        pool = [r for r in order if cls(r) == c and r["task_id"] not in taken and r["date"] not in dates]
        r = min(pool, key=lambda r: (sp[r["settlement_point"]], sm[r["date"][:7]], points[r["settlement_point"]],
                                     months[r["date"][:7]], rank[r["task_id"]]))
        out.append(r)
        dates.add(r["date"])
        count(r)
        left[c] -= 1
    return out


def capture(p: float, p_idle: float, p_hind: float) -> float | None:
    return round((p - p_idle) / (p_hind - p_idle), 6) if p_hind - p_idle > 1e-9 else None


def reward(p: float, p_idle: float, p_anchor: float) -> float:
    return round(min(1.0, max(0.0, 0.2 + 0.8 * (p - p_idle) / (p_anchor - p_idle))), 6)


def row(r: dict, tier: str) -> dict:
    """A picked day with the references the pre-registration states before any run."""
    refs, t = r["refs"], r["refs"][tier]
    b, a, i, h = t["baselines"], t["anchor"], refs["p_idle"], t["p_hind"]
    out = {"task_id": r["task_id"], "tier": tier, "stratum": r["tags"]["as_stratum"], "point": r["settlement_point"],
           "date": r["date"], "site": r["site"]["site_id"], "pv_poi": ratio(r), "watches": r["tags"]["watches"],
           "notice_day": r["tags"]["notice_day"], "deploy_day": r["tags"]["deploy_day"],
           "neg_hours": r["tags"]["neg_hours"], "clip_mwh": r["tags"]["clip_mwh"],
           "as_value_usd": r["tags"]["as_value_usd"], "reg_source": r["reg"].get("source"),
           "p_idle": round(i, 2), "p_anchor": round(t["p_anchor"], 2), "p_hind": round(h, 2),
           "anchor_minus_idle_usd": round(t["p_anchor"] - i, 2), "anchor_capture": capture(t["p_anchor"], i, h),
           "anchor_commits": a["commits"], "anchor_as_usd": round(a["as_usd"], 2),
           "anchor_ftp_usd": round(a["ftp_usd"], 2), "anchor_governor_hours": a["governor_hours"]}
    for k in ("v2_energy", "sponge") + (("as_hog",) if tier == "reserves" else ()):
        out[k] = b[k]["reward"]
        out[k + "_capture"] = capture(b[k]["profit"], i, h)
    if tier == "reserves":
        out["energy_only"] = reward(t["p_energy_only"], i, t["p_anchor"])
        out["energy_only_capture"] = capture(t["p_energy_only"], i, h)
    return out


def picks() -> tuple[list[dict], list[dict]]:
    rows = hybrid_tasks.eligible(hybrid_tasks.eligible(hybrid_tasks.pack_rows(PACK), "reserves"), "energy")
    deploy = sorted((r for r in rows if r["tags"]["deploy_day"]), key=lambda r: r["task_id"])
    main = draw([r for r in rows if not r["tags"]["deploy_day"]], dict.fromkeys(STRATA, PER_STRATUM),
                lambda r: r["tags"]["as_stratum"], deploy, set(), SEED)
    energy = draw([r for r in rows if ratio_class(r)], dict.fromkeys(RATIOS, PER_RATIO), ratio_class, [],
                  {r["date"] for r in main}, SEED + 1)
    return main, energy


def smoke() -> tuple[list[dict], list[dict]]:
    rows = [r for r in hybrid_tasks.pack_rows(TRAIN) if r["era"] == "B" and r["reg"].get("source") == "ercot"]
    order = sorted(rows, key=lambda r: r["task_id"])
    random.Random(SEED + 2).shuffle(order)
    dep = next(r for r in order if r["tags"]["deploy_day"])
    quiet = next(r for r in order if not r["tags"]["deploy_day"] and not ratio_class(r) and r["date"] != dep["date"])
    over = next(r for r in order if ratio_class(r) and r["date"] not in (dep["date"], quiet["date"]))
    return [dep, quiet], [over]


def column(name: str) -> list[dict]:
    if name.startswith("smoke"):
        res, en = smoke()
        return [row(r, COLUMNS[name]) for r in (res if name == "smoke-reserves" else en)]
    if name == "showcase":
        rows = {r["task_id"]: r for r in hybrid_tasks.pack_rows(SHOWCASE_PACK)}
        return [row(rows[t], "reserves") for t in SHOWCASE]
    main, energy = picks()
    return [row(r, COLUMNS[name]) for r in (main if name == "main" else energy)]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=list(COLUMNS), default="main")
    ap.add_argument("--json", type=Path, help="Write every column's days with their references here.")
    args = ap.parse_args()
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "seed": SEED, "showcase_pack": SHOWCASE_PACK,
                                         "smoke_pack": TRAIN, "columns": {c: column(c) for c in COLUMNS}},
                                        indent=1) + "\n")
    print(",".join(t["task_id"] for t in column(args.column)))


if __name__ == "__main__":
    main()
