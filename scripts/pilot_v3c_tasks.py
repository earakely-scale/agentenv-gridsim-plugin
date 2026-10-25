"""The v3 re-pilot's tasks under rules 3.2 (docs/prereg/v3-pilot-c.md): the 3.1 pilot's days (docs/prereg/
v3-pilot-b-tasks.json) that survive the rules-3.2 refill of ercot-hybrid-v3-eval, topped up by the 3.1 pilot's own
rule and seeds (scripts/pilot_v3b_tasks.py). Reserves column: the survivors, then every deployment day not among them,
then round-robin over the AS strata until each stratum holds 10, on dates neither column uses. Energy column: the
survivors, then round-robin over the PV/POI classes until each holds 5, on dates the reserves column does not use. The
display and smoke days are the 3.1 pilot's, all still in their packs."""

import argparse
import json
from pathlib import Path

import pilot_v3b_tasks as b

from agentenv_gridsim import hybrid_tasks

PRIOR = Path("docs/prereg/v3-pilot-b-tasks.json")


def prior() -> dict[str, list[str]]:
    return {c: [t["task_id"] for t in ts] for c, ts in json.loads(PRIOR.read_text())["columns"].items()}


def picks() -> tuple[list[dict], list[dict]]:
    rows = hybrid_tasks.eligible(hybrid_tasks.eligible(hybrid_tasks.pack_rows(b.PACK), "reserves"), "energy")
    by, old = {r["task_id"]: r for r in rows}, prior()
    keep = {c: [by[t] for t in old[c] if t in by] for c in ("main", "energy")}
    kept = {r["task_id"] for r in keep["main"]}
    fixed = keep["main"] + sorted((r for r in rows if r["tags"]["deploy_day"] and r["task_id"] not in kept),
                                  key=lambda r: r["task_id"])
    main = b.draw([r for r in rows if not r["tags"]["deploy_day"]], dict.fromkeys(b.STRATA, b.PER_STRATUM),
                  lambda r: r["tags"]["as_stratum"], fixed, {r["date"] for r in keep["energy"]}, b.SEED)
    energy = b.draw([r for r in rows if b.ratio_class(r)], dict.fromkeys(b.RATIOS, b.PER_RATIO), b.ratio_class,
                    keep["energy"], {r["date"] for r in main}, b.SEED + 1)
    return main, energy


def column(name: str) -> list[dict]:
    old = prior()
    if name in ("main", "energy"):
        main, energy = picks()
        days = main if name == "main" else energy
    else:
        pack = b.TRAIN if name.startswith("smoke") else b.SHOWCASE_PACK
        rows = {r["task_id"]: r for r in hybrid_tasks.pack_rows(pack)}
        days = [rows[t] for t in old[name]]
    return [b.row(r, b.COLUMNS[name]) | {"in_3_1": r["task_id"] in old[name]} for r in days]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=list(b.COLUMNS), default="main")
    ap.add_argument("--json", type=Path, help="Write every column's days with their references here.")
    args = ap.parse_args()
    if args.json:
        args.json.write_text(json.dumps({"pack": b.PACK, "seed": b.SEED, "prior": str(PRIOR),
                                         "showcase_pack": b.SHOWCASE_PACK, "smoke_pack": b.TRAIN,
                                         "columns": {c: column(c) for c in b.COLUMNS}}, indent=1) + "\n")
    print(",".join(t["task_id"] for t in column(args.column)))


if __name__ == "__main__":
    main()
