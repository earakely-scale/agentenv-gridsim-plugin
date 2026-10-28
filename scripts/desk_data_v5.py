"""v5 "The Market Floor" series field for the desk packs (docs/CONTRACT-desk.md 10.3, docs/desk-data.md section 11):
`market`, one previews-shape days row per operating day built from that day's NP3-966-ER 60-Day DAM Disclosure with the
site's own resource carved out, and the replay check (the operator's real curve put back reproduces the real price)."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import desk_data_api as A  # noqa: E402

from gridsim_core import market_stack as M  # noqa: E402
from gridsim_core.contract import era as era_of  # noqa: E402
from gridsim_core.market_auction import limits  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
V5_DAYS = ("2026-04-11", "2026-04-24", "2026-05-26", "2026-06-06", "2026-07-21", "2026-08-22")
V5_PV = {("2026-04-24", "S01"), ("2026-05-26", "S02"), ("2026-05-26", "S04"), ("2026-04-11", "S01"),
         ("2026-06-06", "S03"), ("2026-07-21", "S02"), ("2026-07-21", "S04"), ("2026-08-22", "S03")}
PACKS = {
    "desk-v5-pilot": {"split": "pilot", "layer": "v5", "tasks": [("2026-04-20", "S01"), ("2026-08-14", "S03")],
                      "pv": {("2026-04-20", "S01")}},
    "desk-v5-eval": {"split": "eval", "layer": "v5",
                     "tasks": [(d, s) for d in V5_DAYS for s in ("S01", "S02", "S03", "S04")], "pv": V5_PV},
}
_store: M.DayStore | None = None


def disclosure_zip(day: dt.date) -> Path:
    post = day + dt.timedelta(days=60)
    docs = [d for d in A.archive_list("np3-966-er", f"{post}T00:00:00", f"{post}T23:59:59")
            if d.get("friendlyName") == "60_Day_DAM_Disclosure"]
    if not docs:
        raise ValueError(f"no NP3-966-ER disclosure posted {post} for {day}")
    doc = max(docs, key=lambda d: d["postDatetime"])
    return A.archive_fetch("np3-966-er", [doc])[doc["docId"]]


def market_day(resource: str, day: dt.date) -> dict:
    """The days row of `day` rebuilt from its disclosure with every curve of `resource` removed; the public series
    (NP4-523-CD λ, HB_HUBAVG DAM/RT, EIA-930) come from the packaged days store."""
    global _store
    if _store is None:
        _store = M.DayStore(ROOT / "data" / "market" / "days")
    pub = _store.get(str(day))
    orig = M.parse_disclosure
    carved = {"supply": 0, "demand": 0}

    def parse(path, date):
        hours = orig(path, date)
        for hr in hours:
            for side in ("supply", "demand"):
                keep = [(o, c) for o, c in hr[side] if o.get("name") != resource]
                carved[side] += len(hr[side]) - len(keep)
                hr[side] = keep
        return hours

    M.parse_disclosure = parse
    try:
        row = M.build_day(disclosure_zip(day), str(day), pub["lambda_usd"], pub["hub_dam_usd"], pub["hub_rt_usd"],
                          pub["actuals"], pub["df_mw"])
    finally:
        M.parse_disclosure = orig
    row["era"] = era_of(str(day))["name"]
    row["carved"] = {"resource": resource, "supply_hours": carved["supply"], "demand_hours": carved["demand"]}
    return row


def extend(ser: dict, site: dict, days: list[dt.date], info) -> None:
    ser["market"] = {}
    for d in days:
        row = market_day(site["resource"], d)
        ser["market"][str(d)] = row
        info["market_carved_hours"] += row["carved"]["supply_hours"] + row["carved"]["demand_hours"]


def replay_check(pack: str) -> dict:
    """Per task and hour: the re-clear with no battery curve (must post the real node DAM price), and with the
    operator's real EB/OC put back (the carved book plus the operator; its error vs the real price is the replay
    error), and the copper-plate replay λ vs NP4-523-CD λ."""
    from gridsim_core.desk.impact import Stack
    tasks = [json.loads(x) for x in gzip.open(ROOT / "data" / "desk" / pack / "tasks.jsonl.gz", "rt")]
    rows, err_none, err_op, err_lam, aw = [], [], [], [], []
    for t in tasks:
        ser = json.loads(gzip.open(ROOT / "data" / "desk" / pack / t["series"], "rt").read())
        for d in t["dates"]:
            day = ser["market"][d]
            node = ser["dam_spp"][d]
            floor, cap = limits(d)
            st = Stack(day, node, floor, cap)
            op = ser["operator"]["dam"][d]
            e_none, e_op = [], []
            for h in range(24):
                p0, _ = st.clear(h, None, True)
                e_none.append(p0 - node[h])
                c = op["curves"][h]
                if c:
                    p1, mw = st.clear(h, c, True)
                    e_op.append(p1 - node[h])
                    aw.append(mw - (op["award_mw"][h] or 0.0))
            lam = np.asarray(day["lambda_usd"], float)
            el = np.asarray(day["replay"]["lambda_usd"], float) - lam
            err_none += e_none
            err_op += e_op
            err_lam += list(el)
            rows.append({"task_id": t["task_id"], "date": d, "max_abs_err_no_battery": round(max(map(abs, e_none)), 4),
                         "operator_hours": len(e_op),
                         "mae_with_operator": round(float(np.mean(np.abs(e_op))), 4) if e_op else None,
                         "max_abs_err_with_operator": round(float(np.max(np.abs(e_op))), 4) if e_op else None,
                         "fidelity": day.get("fidelity"), "carved": day.get("carved")})

    def dist(x):
        a = np.abs(np.asarray(x, float))
        return {"n": int(a.size), "mean": round(float(a.mean()), 4), "p50": round(float(np.percentile(a, 50)), 4),
                "p90": round(float(np.percentile(a, 90)), 4), "p99": round(float(np.percentile(a, 99)), 4),
                "max": round(float(a.max()), 4)} if a.size else None

    return {"pack": pack, "no_battery_err_usd": dist(err_none), "with_operator_err_usd": dist(err_op),
            "operator_award_err_mw": dist(aw), "replay_lambda_vs_np4523_usd": dist(err_lam), "tasks": rows}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="+")
    a = ap.parse_args()
    for p in a.packs:
        rep = replay_check(p)
        (ROOT / "data" / "desk" / p / "replay_check.json").write_text(json.dumps(rep, indent=1))
        print(json.dumps({k: v for k, v in rep.items() if k != "tasks"}, indent=1))


if __name__ == "__main__":
    main()
