"""Build data/market/days/<YYYY-MM>.jsonl.gz, data/market/manifest.json and data/market/stats.md (CONTRACT-v5 "Data
layout") from what scripts/fetch_disclosure.py keeps under cache/disclosure/ (NP3-966-ER zips, NP4-523-CD λ), the cached
HB_HUBAVG DAM and RT prices and EIA-930 ERCO hourly data, through core's `market_stack.build_day`.

Every non-DST op day with a disclosure and every public series becomes a full row; a day whose disclosure is missing or
fails to parse becomes a light row (public series only) so the tasks around it can still read it, and is never imputed.
DST days and days missing a public series drop. Only derived, anonymised aggregates are written."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
import time
import traceback
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core.contract import era  # noqa: E402
from gridsim_core.market_stack import build_day  # noqa: E402

CPT = ZoneInfo("America/Chicago")
LIGHT_BEFORE = 3
ERCOT_TERMS = ("ERCOT public reports (NP3-966-ER 60-Day DAM Disclosure, NP4-523-CD DAM System Lambda, NP4-180-ER "
               "DAM and NP6-785-ER RT settlement point prices) retrieved through the ERCOT Public API; ERCOT does not "
               "endorse this work. Only derived, aggregated, anonymised curves are published: no raw disclosure file "
               "and no resource or QSE name.")


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def days(first: str, last: str):
    d, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def is_dst(date: str) -> bool:
    d = dt.date.fromisoformat(date)
    a = dt.datetime(d.year, d.month, d.day, tzinfo=CPT).utcoffset()
    n = d + dt.timedelta(days=1)
    return a != dt.datetime(n.year, n.month, n.day, tzinfo=CPT).utcoffset()


def load_lambda(path: Path) -> dict[str, list[float]]:
    by: dict[str, dict[int, float]] = defaultdict(dict)
    dst = set()
    for line in path.open():
        r = json.loads(line)
        if r["dst"]:
            dst.add(r["date"])
        by[r["date"]][r["he"]] = r["lambda"]
    return {d: [v[h] for h in range(1, 25)] for d, v in by.items() if d not in dst and sorted(v) == list(range(1, 25))}


def load_eia930(path: Path) -> dict[str, dict[str, list[float]]]:
    """EIA-930 ERCO hourly by CPT op day and hour ending: df, load, wind, solar; a day with any gap is left out."""
    t = pq.read_table(path, columns=["hour_end_utc", "df_mw", "demand_mw", "wind_mw", "solar_mw"]).to_pylist()
    by: dict[str, dict[int, tuple]] = defaultdict(dict)
    for r in t:
        end = dt.datetime.fromisoformat(r["hour_end_utc"].replace("Z", "+00:00")).astimezone(CPT)
        start = end - dt.timedelta(hours=1)
        by[start.date().isoformat()][start.hour + 1] = (r["df_mw"], r["demand_mw"], r["wind_mw"], r["solar_mw"])
    out = {}
    for d, hours in by.items():
        if sorted(hours) != list(range(1, 25)):
            continue
        v = np.array([hours[h] for h in range(1, 25)], dtype=float)
        if not np.isfinite(v).all():
            continue
        out[d] = {"df": v[:, 0].tolist(), "load": v[:, 1].tolist(), "wind": v[:, 2].tolist(), "solar": v[:, 3].tolist()}
    return out


def public(d: str, lam: dict, dam: dict, rt: dict, eia: dict) -> dict | None:
    key = f"{d}|HB_HUBAVG"
    if is_dst(d) or d not in lam or key not in dam or key not in rt or d not in eia:
        return None
    e = eia[d]
    return {"lam": lam[d], "hub": dam[key], "rt": rt[key], "df": e["df"],
            "actuals": {"load_mw": e["load"], "wind_mw": e["wind"], "solar_mw": e["solar"]}}


def light_row(d: str, p: dict) -> dict:
    return {"date": d, "parser": "light", "lambda_usd": [round(x, 4) for x in p["lam"]],
            "hub_dam_usd": [round(x, 2) for x in p["hub"]], "hub_rt_usd": [round(x, 2) for x in p["rt"]],
            "df_mw": [round(x, 1) for x in p["df"]],
            "actuals": {k: [round(x, 1) for x in v] for k, v in p["actuals"].items()}}


def _build(d: str, zip_path: str, p: dict) -> tuple[str, dict | None, str | None, float]:
    t0 = time.time()
    try:
        row = build_day(zip_path, d, p["lam"], p["hub"], p["rt"], p["actuals"], p["df"])
        row["era"] = era(d)["name"]
        return d, row, None, time.time() - t0
    except Exception as e:  # noqa: BLE001
        where = traceback.format_exc(limit=-2).splitlines()[-3:]
        return d, None, f"{type(e).__name__}: {e} | {where}", time.time() - t0


def fidelity_table(rows: list[dict]) -> list[str]:
    def line(label: str, rs: list[dict]) -> str:
        f = [r["fidelity"] for r in rs]
        w = np.array([x["within_ns"] for x in f if x["within_ns"] is not None])
        mae = np.array([x["mae_ns_usd"] for x in f if x["mae_ns_usd"] is not None])
        simp = np.array([x["simplify_err_usd"] for x in f])
        surv = int((w >= 0.5).sum())
        return (f"| {label} | {len(rs)} | {surv} ({surv / max(1, len(rs)):.0%}) | {int((w >= 0.75).sum())} | "
                f"{int((w >= 0.9).sum())} | {np.median(w):.2f} | {np.median(mae):.2f} | "
                f"{np.percentile(simp, 95):.2f} | {simp.max():.2f} |")

    out = ["| Days | Full rows | raw within_ns ≥ 0.5 (V5-P2) | ≥ 0.75 | ≥ 0.9 (plan) | median within_ns | "
           "median MAE_ns $ | simplify err p95 $ | max $ |", "|---|---|---|---|---|---|---|---|---|"]
    groups = [("all", rows)]
    for y in sorted({r["date"][:4] for r in rows}):
        groups.append((y, [r for r in rows if r["date"][:4] == y]))
    groups += [("pre-RTC+B", [r for r in rows if r["date"] < "2025-12-05"]),
               ("RTC+B (2025-12-05+)", [r for r in rows if r["date"] >= "2025-12-05"])]
    return out + [line(label, rs) for label, rs in groups if rs]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--disclosure", type=Path, default=ROOT / "cache" / "disclosure")
    ap.add_argument("--parsed", type=Path, default=ROOT / "cache" / "parsed", help="dam-*.json.gz and rt-*.json.gz")
    ap.add_argument("--eia930", type=Path, default=ROOT / "cache" / "forecast" / "eia930" / "erco.parquet")
    ap.add_argument("--first", default="2023-12-11")
    ap.add_argument("--last", default=None, help="last op day (default: the latest disclosure)")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "market")
    args = ap.parse_args()
    raw = args.disclosure / "raw" / "np3-966-er"
    zips = {p.stem: p for p in raw.glob("20*.zip")}
    last = args.last or max(zips)
    lam = load_lambda(args.disclosure / "np4-523.jsonl")
    dam = json.load(gzip.open(max(args.parsed.glob("dam-*.json.gz"), key=lambda p: p.stat().st_mtime)))["dam"]
    rt = json.load(gzip.open(max(args.parsed.glob("rt-*.json.gz"), key=lambda p: p.stat().st_mtime)))["rt"]
    eia = load_eia930(args.eia930)
    log(f"inputs: {len(zips)} zips, λ {len(lam)} days, EIA-930 {len(eia)} days; op days {args.first}..{last}")
    rows: dict[str, dict] = {}
    dropped: dict[str, str] = {}
    errors: dict[str, str] = {}
    pub = {}
    for d in days((dt.date.fromisoformat(args.first) - dt.timedelta(days=LIGHT_BEFORE)).isoformat(), last):
        p = public(d, lam, dam, rt, eia)
        if p is None:
            dropped[d] = "dst" if is_dst(d) else "public series missing"
        else:
            pub[d] = p
    todo = [d for d in pub if d >= args.first and d in zips]
    t0, secs = time.time(), []
    with ProcessPoolExecutor(args.workers) as ex:
        futs = [ex.submit(_build, d, str(zips[d]), pub[d]) for d in todo]
        for i, f in enumerate(as_completed(futs), 1):
            d, row, err, s = f.result()
            secs.append(s)
            if row is not None:
                rows[d] = row
            else:
                errors[d] = err
                log(f"{d} parse error: {err[:300]}")
            if i % 50 == 0 or i == len(futs):
                log(f"{i}/{len(futs)} days built ({time.time() - t0:.0f}s, median {np.median(secs):.1f}s/day)")
    for d, p in pub.items():
        if d not in rows:
            rows[d] = light_row(d, p)
            if d >= args.first and d not in zips:
                dropped[d] = "no disclosure (light row)"
            elif d in errors:
                dropped[d] = "parse error (light row)"
    out = args.out
    (out / "days").mkdir(parents=True, exist_ok=True)
    by_month = defaultdict(list)
    for d in sorted(rows):
        by_month[d[:7]].append(rows[d])
    for m, rs in by_month.items():
        with gzip.open(out / "days" / f"{m}.jsonl.gz", "wt", compresslevel=9) as f:
            f.writelines(json.dumps(r, separators=(",", ":")) + "\n" for r in rs)
    full = [rows[d] for d in sorted(rows) if rows[d].get("parser") != "light"]
    index = {}
    for line in (raw / "index.jsonl").open():
        r = json.loads(line)
        index[r["op_date"]] = r
    manifest = {
        "schema": "gridsim.market-days/v5", "first": args.first, "last": last,
        "full_days": len(full), "light_days": len(rows) - len(full),
        "parsers": sorted({r["parser"] for r in full}),
        "sources": {
            "np3-966-er": {"endpoint": "GET https://api.ercot.com/api/public-reports/archive/np3-966-er (listing), "
                                       "POST .../archive/np3-966-er/download (bulk, 25 docIds)",
                           "documents": {d: {k: index[d][k] for k in ("docId", "postDatetime", "bytes", "sha256")}
                                         for d in sorted(index) if d in rows and rows[d].get("parser") != "light"}},
            "np4-523-cd": {"endpoint": "archive/np4-523-cd (bulk CSV documents)", "days": len(lam)},
            "hub": "HB_HUBAVG DAM (NP4-180-ER DAMLZHBSPP) and 15-min RT (NP6-785-ER RTMLZHBSPP), cached",
            "eia930": "EIA-930 ERCO hourly (BALANCE files): demand forecast, demand, wind and solar net generation"},
        "fidelity": {"within_ns_ge_0.5": sum((r["fidelity"]["within_ns"] or 0.0) >= 0.5 for r in full),
                     "median_within_ns": float(np.median([r["fidelity"]["within_ns"] for r in full
                                                          if r["fidelity"]["within_ns"] is not None]))},
        "dropped": dropped, "parse_errors": {d: e[:500] for d, e in errors.items()},
        "terms": ERCOT_TERMS}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    stats = ["# v5 market days: fidelity", "",
             f"Op days {args.first}..{last}: {len(full)} full rows, {len(rows) - len(full)} light rows; dropped "
             f"{sum(v == 'dst' for v in dropped.values())} DST days, "
             f"{sum(v == 'public series missing' for v in dropped.values())} without a public series, "
             f"{len(errors)} parse errors, {sum(v.startswith('no disclosure') for v in dropped.values())} without a "
             "disclosure. Fidelity is the copper-plate re-clear of every real offer against NP4-523-CD λ in "
             "non-scarcity hours (λ < $100), within $5 or 10%; the simplification error is the shipped (≤ 64-point) "
             "replay against the full re-clear.", "", *fidelity_table(full), ""]
    (out / "stats.md").write_text("\n".join(stats) + "\n")
    log(f"done: {len(full)} full, {len(rows) - len(full)} light, {len(errors)} errors, "
        f"survival {manifest['fidelity']['within_ns_ge_0.5']}/{len(full)}")


if __name__ == "__main__":
    main()
