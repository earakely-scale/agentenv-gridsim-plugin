"""Build data/fixtures-market/ (the v5 CI days and tasks) from NP3-966-ER zips and the NP4-523-CD JSON pulled through
the ERCOT API (`<sample>/np3-966-er/<op_date>.zip`, `<sample>/np4-523-cd/*.json`), the cached HB_HUBAVG DAM and RT
prices, EIA-930 `Region_TEX.xlsx` and EIA-860/923 2025 (CT heat rates). Only derived, anonymised aggregates ship."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import sys
from pathlib import Path

import numpy as np
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from probe_market_stack import load_fleet  # noqa: E402

from gridsim_core.market import finalize_task  # noqa: E402
from gridsim_core.market_stack import DayStore, build_day, sample_seats, shift  # noqa: E402

OP_DAYS = ("2024-08-20", "2026-07-21")
DRAWS = (("e1", None, 2.0, 0.85, 4.0), ("e1", None, 1.0, 0.9, 0.0), ("e2", None, 2.0, 0.85, 8.0),
         ("e1", 1500.0, 4.0, 0.8, 4.0), ("e2", 400.0, 2.0, 0.9, 4.0))


def lambdas(sample: Path) -> dict[str, list[float]]:
    out: dict[str, dict[int, float]] = {}
    for f in sorted((sample / "np4-523-cd").glob("*.json")):
        for d, he, v, _dst in json.loads(f.read_text())["data"]:
            out.setdefault(d, {})[int(str(he).split(":")[0])] = float(v)
    return {d: [v[h] for h in range(1, 25)] for d, v in out.items() if sorted(v) == list(range(1, 25))}


def eia930(path: Path, dates: set[str]) -> dict[str, dict]:
    wb = openpyxl.load_workbook(io.BytesIO(path.read_bytes()), read_only=True, data_only=True)
    rows = wb["Published Hourly Data"].iter_rows(values_only=True)
    head = [str(h).strip() if h is not None else "" for h in next(rows)]
    ix = {k: head.index(k) for k in ("Local date", "Hour", "Demand forecast", "Demand", "NG: WND", "NG: SUN")}
    out: dict[str, dict] = {}
    for r in rows:
        d = r[ix["Local date"]]
        if not isinstance(d, dt.datetime) or d.date().isoformat() not in dates:
            continue
        h = int(r[ix["Hour"]]) - 1
        row = out.setdefault(d.date().isoformat(), {k: [0.0] * 24 for k in ("df", "load", "wind", "solar")})
        for k, c in (("df", "Demand forecast"), ("load", "Demand"), ("wind", "NG: WND"), ("solar", "NG: SUN")):
            row[k][h] = float(r[ix[c]] or 0.0)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=ROOT / "cache")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "fixtures-market")
    args = ap.parse_args()
    lam = lambdas(args.sample)
    full = {d for op in OP_DAYS for d in (op, shift(op, -61), shift(op, -62))}
    light = {shift(op, k) for op in OP_DAYS for k in (-1, -2, -3)}
    eia = eia930(args.cache / "raw" / "eia930" / "Region_TEX.xlsx", full | light)
    dam = json.load(gzip.open(next((args.cache / "parsed").glob("dam-*.json.gz"))))["dam"]
    rt = json.load(gzip.open(next((args.cache / "parsed").glob("rt-*.json.gz"))))["rt"]
    days = []
    for d in sorted(full | light):
        e = eia[d]
        actuals = {"load_mw": e["load"], "wind_mw": e["wind"], "solar_mw": e["solar"]}
        hub, hub_rt = dam[f"{d}|HB_HUBAVG"], rt[f"{d}|HB_HUBAVG"]
        if d in full:
            row = build_day(args.sample / "np3-966-er" / f"{d}.zip", d, lam[d], hub, hub_rt, actuals, e["df"])
        else:
            row = {"date": d, "parser": "light", "lambda_usd": [round(x, 4) for x in lam[d]],
                   "hub_dam_usd": [round(x, 2) for x in hub], "hub_rt_usd": [round(x, 2) for x in hub_rt],
                   "df_mw": [round(x, 1) for x in e["df"]],
                   "actuals": {k: [round(x, 1) for x in v] for k, v in actuals.items()}}
        days.append(row)
        print(d, row.get("fidelity"), flush=True)
    store = DayStore(days)
    cts = [u["hr"] for u in load_fleet(args.cache / "raw") if u["cls"] == "ct" and u["hr_source"] == "eia923"]
    rng = np.random.default_rng(5)
    tasks = []
    for op in OP_DAYS:
        day = store.get(op)
        for pool_id, size, dur, eta, c_deg in DRAWS:
            seats = sample_seats(day, rng, cts, size, dur, eta, c_deg, pool_id)
            p = int(seats["A"]["p_mw"])
            task = {"task_id": f"mkt-v5-{op}-A{p}x{int(dur)}-{pool_id}", "market_version": "5.0",
                    "contract_version": "1.0", "pack": "fixtures-market", "split": "fixtures", "date": op,
                    "era": "rtc+b" if op >= "2025-12-05" else "ecrs", "point": "HB_HUBAVG", "region": "central",
                    "seats": seats, "notices": [],
                    "flags": {"stack": "real", "copper_plate": True, "as": "truncated", "costs": "modelled",
                              "forecast": "eia930", "calibration": "hub_offset"}}
            tasks.append(finalize_task(task, store))
            r = task["refs"]
            print(task["task_id"], {"p_anchor": r["floor-sprint"]["p_anchor"], "p_br": r["floor-sprint"]["p_br"],
                                    "headroom": r["headroom_usd_per_mw"], "impact_hours": r["impact_hours"]},
                  flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out / "days.jsonl.gz", "wt") as f:
        for r in days:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    with gzip.open(args.out / "tasks.jsonl.gz", "wt") as f:
        for t in tasks:
            f.write(json.dumps(t, separators=(",", ":")) + "\n")
    manifest = {"pack": "fixtures-market", "tasks": len(tasks), "days": [r["date"] for r in days],
                "op_days": list(OP_DAYS), "sources": {"np3-966-er": "ERCOT public API archive (60-Day DAM Disclosure)",
                                                      "np4-523-cd": "ERCOT public API (DAM System Lambda)",
                                                      "hub": "NP4-180-ER / NP6-905 cached HB_HUBAVG",
                                                      "eia930": "EIA-930 Region_TEX.xlsx", "eia923": "f923_2025.zip"},
                "fidelity": {r["date"]: r.get("fidelity") for r in days if r.get("fidelity")},
                "note": "derived, anonymised aggregates only; ERCOT data, not endorsed by ERCOT"}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")


if __name__ == "__main__":
    main()
