"""Build the v4 forecast windows (docs/CONTRACT-v4.md): data/fixtures-forecast now, the ercot-front-v4-* packs once
the data lane's forecast store exists. A window row gathers v1's DAM and v2's RT caches, lane D3's MCPC, solar cf and
deployments, lane N's notices and the window's vintage slice, then gridsim_core.forecast references on HiGHS.
Before the store lands the slice is the deterministic synthetic one (flagged source "synthetic")."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_hybrid_pack as v3  # noqa: E402
import build_live_pack as v2  # noqa: E402

from gridsim_core import forecast as F  # noqa: E402
from gridsim_core import forecast_inputs as FI  # noqa: E402
from gridsim_core import hybrid as H  # noqa: E402
from gridsim_core import hybrid_inputs as HI  # noqa: E402
from gridsim_core.contract import as_era  # noqa: E402

FIXTURES = [("2025-02-18", "HB_NORTH", "default"), ("2023-08-24", "HB_HOUSTON", "default"),
            ("2022-12-22", "HB_NORTH", "default"), ("2021-06-14", "HB_WEST", "default"),
            ("2026-02-10", "LZ_CPS", "default"), ("2025-07-15", "HB_WEST", "draw"),
            ("2024-05-08", "HB_HOUSTON", "draw"), ("2023-09-05", "HB_WEST", "default"),
            ("2025-10-12", "LZ_SOUTH", "draw"), ("2022-03-29", "HB_PAN", "default"),
            ("2026-04-20", "HB_SOUTH", "draw"), ("2024-07-30", "LZ_LCRA", "draw")]


def log(msg: str):
    print(f"[build_forecast_pack] {msg}", flush=True)


def dates(d1: str, a: int, b: int) -> list[str]:
    d = dt.date.fromisoformat(d1)
    return [(d + dt.timedelta(days=k)).isoformat() for k in range(a, b)]


def caches(cache: Path) -> tuple[dict, dict]:
    dam = json.load(gzip.open(next(cache.glob("dam-*.json.gz")), "rt"))["dam"]
    rt = json.load(gzip.open(next(cache.glob("rt-*.json.gz")), "rt"))["rt"]
    return dam, rt


def hourly(rt96) -> list[float]:
    return [round(float(x), 4) for x in np.asarray(rt96, dtype=float).reshape(24, 4).mean(axis=1)]


def window(d1: str, point: str, site: dict, dam: dict, rt: dict, days: int = 3) -> dict | None:
    """One window row (no slice, no refs), or None when an input day is missing or a DST day or era change falls in
    d1-1..d(n) (V4-P9)."""
    span = dates(d1, -1, days)
    if any(d in v2.v1.dst_dates(int(d[:4])) for d in span) or len({as_era(d) for d in span}) > 1:
        return None
    win = dates(d1, 0, days)
    try:
        da = [x for d in win for x in dam[f"{d}|{point}"]]
        rth = [x for d in win for x in hourly(rt[f"{d}|{point}"])]
        hist_dam = [dam[f"{d}|{point}"] for d in dates(d1, -7, 0)]
        hist_rt = [hourly(rt[f"{d}|{point}"]) for d in dates(d1, -8, -1)]
    except KeyError:
        return None
    asp = [HI.as_prices(d) for d in dates(d1, -2, days)]
    rows = [HI.solar_row(d) for d in dates(d1, -2, days)]
    if any(a is None or a["n_hours"] != 24 for a in asp) or any(r is None for r in rows):
        return None
    mcpc = {k: [x for a in asp[2:] for x in a[k]] for k in H.PRODUCTS if all(a.get(k) is not None for a in asp)}
    cf = [c for r in rows[2:] for c in r["cf"]]
    hist_pv = [H.pv_at_bus(site, r["cf"]) for r in rows[:2]]
    notices, seen = [], set()
    for d in win:
        for n in v2.day_notices(d, point):
            if n["event_id"] not in seen:
                seen.add(n["event_id"])
                notices.append(n)
    deps, dseen = [], set()
    for d in win:
        for x in v3.deployments(d):
            if x["event_id"] not in dseen:
                dseen.add(x["event_id"])
                deps.append(x)
    return F.make_task(d1, point, site, da, rth, cf, mcpc, era=as_era(d1),
                       history={"dam": hist_dam, "rt": hist_rt, "rt_d0": hourly(rt[f"{dates(d1, -1, 0)[0]}|{point}"]),
                                "pv_mw": hist_pv,
                                "mcpc_da": {k: [a[k] for a in asp[:2]] for k in mcpc}},
                       notices=notices, deployments=deps, solar_installed_mw=rows[2].get("installed_mw"), days=days)


def site_for(kind: str, d1: str, point: str, arch: dict) -> dict:
    if kind == "default":
        return H.site_from_archetype(arch["default"], c_deg=4.0)
    return v3.pick_site(d1, point, "forecast-fixtures", arch)


def build_one(args: tuple) -> dict:
    t, tiers = args
    t0 = time.perf_counter()
    sl = FI.synthetic_slice(t)
    out = F.attach(t, sl, tiers=tiers)
    out["_ms"] = round(1000 * (time.perf_counter() - t0))
    return out


def write(out: Path, name: str, tasks: list, meta: dict):
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "tasks.jsonl.gz", "wt") as f:
        for t in tasks:
            f.write(json.dumps({k: v for k, v in t.items() if not k.startswith("_")}, separators=(",", ":")) + "\n")
    (d / "manifest.json").write_text(json.dumps({
        "pack": name, "forecast_version": F.FORECAST_VERSION, "tasks": len(tasks),
        "dates": [min(t["d1"] for t in tasks), max(t["d1"] for t in tasks)] if tasks else None,
        "tiers": list(F.TIERS), "sources": sorted({t["source"] for t in tasks}),
        "flags": {"vintages": "synthetic until the forecast store lands (V4-P12)", "site": "archetype",
                  "pv_availability": "proxy, system-wide cf", "reg_drift": "seeded", "rt_as": "not modelled (V4-P6)"},
        "licence": "ERCOT data with attribution and no endorsement; NOAA and IEM with attribution; EIA public domain"}
        | meta, indent=1) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", action="store_true", help="build data/fixtures-forecast (synthetic slices)")
    ap.add_argument("--cache", default=str(ROOT / "cache" / "parsed"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 2))
    args = ap.parse_args()
    if not args.fixtures:
        ap.error("the ercot-front-v4-* packs need the forecast store; only --fixtures builds tonight")
    dam, rt = caches(Path(args.cache))
    arch = HI.archetypes()
    rows = []
    for i, (d1, point, kind) in enumerate(FIXTURES):
        t = window(d1, point, site_for(kind, d1, point, arch), dam, rt, days=3)
        if t is None:
            log(f"skip {d1} {point}: missing input or DST/era")
            continue
        t["pack"], t["split"] = "fixtures-forecast", "fixtures"
        t["tags"] = {"fixture": i, "showcase": None}
        rows.append(t)
    t0 = time.time()
    with mp.Pool(min(args.workers, len(rows))) as pool:
        built = pool.map(build_one, [(t, F.TIERS) for t in rows])
    for t in built:
        tr = t["refs"]
        log(f"{t['task_id']}: {t['_ms']} ms, front roll {tr['front']['p_roll']:.0f} idle {tr['front']['p_idle']:.0f} "
            f"hind {tr['front']['p_hind']:.0f}; lite roll {tr['front-lite']['p_roll']:.0f}")
    write(Path(args.out), "fixtures-forecast", built, {"build_seconds": round(time.time() - t0, 1),
                                                       "build_command": "python scripts/build_forecast_pack.py "
                                                                        "--fixtures"})
    log(f"wrote {len(built)} fixtures in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
