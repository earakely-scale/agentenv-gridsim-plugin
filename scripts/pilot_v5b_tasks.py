"""The rules-5.1 v5 pilot's floors (docs/prereg/v5-pilot-b.md), one seeded draw over gridsim-market-eval. The floor-day
column takes every peak floor of the pack's floor-day subset and base floor-day floors until it holds DAY; the
floor-sprint column takes every peak floor, the floor-day column's base floors (so every floor-day floor is also played
at floor-sprint) and base floors until it holds SPRINT. Each draw takes the candidate on a date the column does not
hold yet whose month it holds least, ties broken by a seeded shuffle. The showcase floors are aug24-0820 and the fern
floor whose floor-day anchor earns the most over idle; the smoke floors are gridsim-market-train floors whose days,
back to D-62, are all in git (the env image holds no overflow month).
Each floor carries what is known before any run: its stored references and the baselines played in process at the
column's tier, on hindsight capture C against BR_rt (docs/REWARD-SCALES.md), R and both compliant scores."""

import argparse
import json
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from build_market_days import SHIP_FROM
from pilot_v5_tasks import peak

from agentenv_gridsim import market_tasks
from gridsim_core.market import baseline_plays

SEED = 5324
PACK = "gridsim-market-eval"
SHOWCASE_PACK = "gridsim-market-showcase"
SMOKE_PACK = "gridsim-market-train"
SPRINT, DAY, SMOKE = 30, 10, 2
AUG24 = "mkt-v5-2024-08-20-A800x2-e1"
COLUMNS = ("sprint", "day", "showcase", "smoke-sprint", "smoke-day")
TIERS = {"sprint": "floor-sprint", "smoke-sprint": "floor-sprint"}
V50 = Path("results/pilot-v5.json")


def capture(p: float, refs: dict, tier: str) -> float | None:
    """Hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, with v5's P_hind the tier's BR_rt."""
    d = refs[tier]["p_br_rt"] - refs["p_idle"]
    return (p - refs["p_idle"]) / d if d > 1e-6 else None


def compliant(c: float | None, welfare_ratio: float | None) -> float | None:
    """The public compliant score with C as its profit half: 0.5 clip(C, 0, 1) + 0.5 clip(W/W*, 0, 1)."""
    if c is None or welfare_ratio is None:
        return None
    return 0.5 * min(1.0, max(0.0, c)) + 0.5 * min(1.0, max(0.0, welfare_ratio))


def draw(pool: list[dict], n: int, held: list[dict], rng: random.Random) -> list[dict]:
    order = sorted(pool, key=lambda r: r["task_id"])
    rng.shuffle(order)
    rank = {r["task_id"]: i for i, r in enumerate(order)}
    months, dates, out = Counter(r["date"][:7] for r in held), {r["date"] for r in held}, []
    for _ in range(min(n, len(order))):
        r = min((r for r in order if r not in out),
                key=lambda r: (r["date"] in dates, months[r["date"][:7]], rank[r["task_id"]]))
        out.append(r)
        months[r["date"][:7]] += 1
        dates.add(r["date"])
    return out


def picks() -> dict[str, list[dict]]:
    rng = random.Random(SEED)
    rows = market_tasks.eligible(market_tasks.pack_rows(PACK), "floor-sprint")
    day_ok = {r["task_id"] for r in market_tasks.eligible(rows, "floor-day")}
    peaks = [r for r in rows if peak(r)]
    day = [r for r in peaks if r["task_id"] in day_ok]
    day += draw([r for r in rows if not peak(r) and r["task_id"] in day_ok], DAY - len(day), peaks, rng)
    sprint = peaks + [r for r in day if not peak(r)]
    sprint += draw([r for r in rows if not peak(r) and r not in sprint], SPRINT - len(sprint), sprint, rng)
    train = market_tasks.eligible(market_tasks.pack_rows(SMOKE_PACK), "floor-day")
    smoke = draw([r for r in train if (date.fromisoformat(r["date"]) - timedelta(days=62)).isoformat() >= SHIP_FROM],
                 2 * SMOKE, [], rng)
    show = market_tasks.eligible(market_tasks.pack_rows(SHOWCASE_PACK), "floor-day")
    gain = {r["task_id"]: r["refs"]["floor-day"]["p_anchor"] - r["refs"]["p_idle"] for r in show}
    fern = max((r for r in show if r["date"].startswith("2026-01") and gain[r["task_id"]] > 0),
               key=lambda r: gain[r["task_id"]])
    return {"sprint": sorted(sprint, key=lambda r: r["date"]), "day": sorted(day, key=lambda r: r["date"]),
            "showcase": [r for r in show if r["task_id"] == AUG24] + [fern], "smoke-sprint": smoke[:SMOKE],
            "smoke-day": smoke[SMOKE:]}


def v50_floors() -> dict[str, set[str]]:
    """The rules-5.0 pilot's floors by tier (floor-sprint amended, floor-day)."""
    cols = json.loads(V50.read_text())["columns"]
    return {"floor-sprint": {f["task_id"] for f in cols["floor-sprint"]["amended"]["floors"]},
            "floor-day": {f["task_id"] for f in cols["floor-day"]["primary"]["floors"]}}


def row(r: dict, tier: str, v50: set[str]) -> dict:
    refs, t, a = r["refs"], r["refs"][tier], r["seats"]["A"]
    return {"task_id": r["task_id"], "tier": tier, "date": r["date"], "stratum": r["tags"].get("stratum"),
            "p_mw": a["p_mw"], "hours": round(a["e_mwh"] / a["p_mw"], 2), "eta": a["eta"], "c_deg": a["c_deg"],
            "impact_hours": refs.get("impact_hours"), "impact_hours_2usd": r["tags"].get("impact_hours_2usd"),
            "within_ns": r["fidelity"]["within_ns"], "notice_day": r["tags"].get("notice_day"),
            "season": r["tags"].get("season"), "neg_hours": r["tags"].get("neg_hours"),
            "anchor_minus_idle_usd": round(t["p_anchor"] - refs["p_idle"], 2),
            "hindsight_minus_idle_usd": round(t["p_br_rt"] - refs["p_idle"], 2),
            "anchor_capture": capture(t["p_anchor"], refs, tier), "in_v50_pilot": r["task_id"] in v50,
            "baselines": {k: {"profit": v["profit"], "capture": capture(v["profit"], refs, tier), "reward": v["reward"],
                              "compliant": compliant(capture(v["profit"], refs, tier), v["welfare_ratio"]),
                              "compliant_r": v["compliant"], "welfare_ratio": v["welfare_ratio"]}
                          for k, v in baseline_plays(r, tier).items()}}


def column(name: str, rows: list[dict]) -> list[dict]:
    tier = TIERS.get(name, "floor-day")
    return [row(r, tier, v50_floors()[tier]) for r in rows]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=COLUMNS, default="sprint")
    ap.add_argument("--json", type=Path, help="Write every column's floors with what is known about them here.")
    args = ap.parse_args()
    p = picks()
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "seed": SEED, "showcase_pack": SHOWCASE_PACK,
                                         "smoke_pack": SMOKE_PACK, "hindsight": "p_br_rt",
                                         "columns": {c: column(c, p[c]) for c in COLUMNS}}, indent=1) + "\n")
    print(",".join(r["task_id"] for r in p[args.column]))


if __name__ == "__main__":
    main()
