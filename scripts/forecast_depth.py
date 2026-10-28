"""The v4 depth report: coverage of every forecast kind by issue time, staleness at the 10:00 CPT watch, missing
vintages, the archive-vs-API spot check, sizes and the leakage spot checks on sample windows. Reads cache/forecast/
(raw pulls and the store built by scripts/build_forecast_store.py); writes data/forecast/coverage.json and
docs/v4-depth.md."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import forecast_inputs as FI  # noqa: E402

CPT = ZoneInfo("America/Chicago")
API_START = dt.date(2023, 12, 11)
FIXED_WATCH_HOURS = (0, 6, 10, 14, 18)
ERCOT_KINDS = ("ercot_load", "ercot_wind", "ercot_solar")
SAMPLE_WINDOWS = (("fern-0124", "2026-01-24"), ("heather-0114", "2024-01-14"), ("uri-0213", "2021-02-13"),
                  ("spring-0328", "2024-03-28"))
SPOT_KEYS = (("weather", "DFW"), ("load", "system"), ("load", "NCEN"), ("wind", "system"), ("solar", "system"),
             ("price", "HB_NORTH"), ("mcpc", "regup"), ("load_official", "system"), ("ercot_load", "system"),
             ("ercot_wind", "system"), ("ercot_solar", "system"))


def utc(local: dt.datetime) -> pd.Timestamp:
    return pd.Timestamp(local.replace(tzinfo=CPT)).tz_convert("UTC")


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def staleness(issued: pd.Series, days: list[dt.date], hour: int = 10) -> dict:
    """Age in hours of the latest issued_at at or before each day's HH:00 CPT."""
    s = np.sort(issued.values.astype("datetime64[s]"))
    w = np.array([utc(dt.datetime(d.year, d.month, d.day, hour)).to_datetime64() for d in days], "datetime64[s]")
    i = np.searchsorted(s, w, side="right") - 1
    age = np.where(i >= 0, (w - s[np.clip(i, 0, None)]).astype(float) / 3600, np.nan)
    if np.isnan(age).all():
        return {}
    return {"p50_h": round(float(np.nanmedian(age)), 2), "p95_h": round(float(np.nanpercentile(age, 95)), 2),
            "max_h": round(float(np.nanmax(age)), 2), "days_over_6h": int(np.sum(age > 6)),
            "days_over_24h": int(np.sum(age > 24))}


def hrrr_coverage(cache: Path, start: str, end: str) -> dict:
    runs = pd.read_parquet(cache / "hrrr" / "runs.parquet")
    runs = runs[(runs.run_id >= start) & (runs.run_id <= end + "T18Z")]
    exp = pd.date_range(start, end + " 18:00", freq="6h", tz="UTC")
    have = set(runs.run_id)
    missing = [f"{t:%Y-%m-%dT%H}Z" for t in exp if f"{t:%Y-%m-%dT%H}Z" not in have]
    runs = runs.assign(year=runs.run_id.str[:4], cycle=pd.to_datetime(runs.cycle_utc),
                       lm=pd.to_datetime(runs.s3_last_modified_utc))
    full = np.where(runs.hrrr == "v4", 49, 37)
    out = {"expected_runs": len(exp), "runs": len(runs), "missing_runs": missing, "by_year": {}}
    for y, g in runs.groupby("year"):
        f = full[runs.year.values == y]
        lag = ((g.lm - g.cycle).dt.total_seconds() / 60)[~g.backfilled]
        e = sum(1 for t in exp if t.year == int(y))
        out["by_year"][y] = {
            "runs": len(g), "expected": e, "coverage": round(len(g) / e, 4),
            "complete_fh": int((g.n_fh.values == f).sum()),
            "partial_fh": int(((g.n_fh.values < f) & (g.n_fh > 0)).sum()),
            "empty": int((g.n_fh == 0).sum()), "fh_max": sorted(int(x) for x in g.fh_max.dropna().unique()),
            "backfilled": int(g.backfilled.sum()),
            "lastmodified_lag_min": {"p50": round(float(lag.median()), 1), "p90": round(float(lag.quantile(0.9)), 1),
                                     "max": round(float(lag.max()), 1)} if len(lag) else None,
            "gb_read": round(float(g.bytes.sum()) / 1e9, 1)}
    d = [dt.date.fromisoformat(start) + dt.timedelta(days=i)
         for i in range((dt.date.fromisoformat(end) - dt.date.fromisoformat(start)).days + 1)]
    out["staleness_10cpt"] = staleness(pd.to_datetime(runs.issued_at_utc), d)
    out["missing_fh_runs"] = [r for r, m in zip(runs.run_id, runs.missing_fh, strict=True)
                              if m is not None and len(m)][:50]
    return out


def eia_coverage(cache: Path) -> dict:
    b = pd.read_parquet(cache / "eia930" / "erco.parquet")
    s = pd.read_parquet(cache / "eia930" / "erco_sub.parquet")
    b["hour_end_utc"] = pd.to_datetime(b.hour_end_utc, utc=True)
    s["hour_end_utc"] = pd.to_datetime(s.hour_end_utc, utc=True)
    b = b.assign(year=b.hour_end_utc.dt.year)
    out = {"span": [str(b.hour_end_utc.min()), str(b.hour_end_utc.max())], "by_year": {}}
    lo, hi = b.hour_end_utc.min(), b.hour_end_utc.max()
    for y, g in b.groupby("year"):
        y0, y1 = pd.Timestamp(f"{y}-01-01T01:00Z"), pd.Timestamp(f"{y + 1}-01-01T00:00Z")
        exp = int((min(hi, y1) - max(lo, y0)).total_seconds() // 3600) + 1
        out["by_year"][str(y)] = {"hours": len(g), "expected": exp,
                                  **{f"{c}_non_null": round(float(g[c].notna().sum() / exp), 4)
                                                      for c in ("df_mw", "demand_mw", "wind_mw", "solar_mw")},
                                  "demand_imputed_h": int(g.demand_imputed.sum())}
    s = s.assign(year=s.hour_end_utc.dt.year)
    out["subregion_non_null_by_year"] = {str(y): round(float(g.demand_mw.notna().mean()), 4)
                                         for y, g in s.groupby("year")}
    df = b.dropna(subset=["df_mw"])
    days = df.hour_end_utc.dt.tz_convert(CPT).dt.date.nunique()
    out["df_days"] = int(days)
    return out


def ercot_coverage(cache: Path, store: Path, end: dt.date) -> dict:
    posts = pd.read_parquet(store / "ercot_postings.parquet")
    posts["posted"] = pd.to_datetime(posts.posted_utc_s, unit="s", utc=True)
    out = {"reports": {}}
    days = [API_START + dt.timedelta(days=i) for i in range((end - API_START).days + 1)]
    for rep, g in posts.groupby("report"):
        g = g.sort_values("posted")
        loc = g.posted.dt.tz_convert(CPT)
        gaps = g.posted.diff().dt.total_seconds() / 3600
        big = g[gaps > 1.5]
        per_day = loc.dt.date.value_counts()
        listing = []
        for f in (cache / "ercot" / "raw" / rep.lower() / "listing").glob("done-*.json"):
            listing += json.loads(f.read_text())
        listed = len({x["docId"] for x in listing if x["friendlyName"].lower().endswith("csv")})
        out["reports"][rep] = {
            "postings": len(g), "listed_csv_docs": listed, "first": str(loc.min()), "last": str(loc.max()),
            "posting_minute_mode": int(loc.dt.minute.mode().iloc[0]),
            "days_with_lt_23_postings": int((per_day < 23).sum()),
            "days_with_gt_25_postings": int((per_day > 25).sum()),
            "gaps_over_1_5h": len(big), "largest_gaps": [{"after": str(g.posted.iloc[i - 1]), "hours": round(float(
                gaps.iloc[i]), 2)} for i in np.argsort(-gaps.fillna(0).values)[:5] if gaps.iloc[i] > 1.5],
            "dst_postings": int(g.dst.sum()), "dst_ambiguous": int(g.ambiguous.sum()),
            "fallback_hour_postings": [str(x) for x in g.posted_local[g.posted_local.str.contains(
                r"-11-0[1-7]T01:")].tolist()][:12],
            "by_year": {str(y): int(n) for y, n in loc.dt.year.value_counts().sort_index().items()},
            "staleness_10cpt": staleness(g.posted, days)}
        if "system_total_max_abs_diff" in g and g.system_total_max_abs_diff.notna().any():
            diff = float(g.system_total_max_abs_diff.max())
            out["reports"][rep]["zones_sum_vs_system_total_max_abs_mw"] = round(diff, 3)
        for c in ("system_wide_max_abs_diff_stppf_mw", "system_wide_max_abs_diff_pvgrpp_mw"):
            if c in g and g[c].notna().any():
                out["reports"][rep][c.replace("system_wide_max_abs_diff_", "regions_sum_vs_system_wide_max_abs_")] = \
                    round(float(g[c].max()), 3)
        if rep == "NP3-565-CD":
            models = pd.Series([m for ms in g.models for m in ms if m is not None])
            out["reports"][rep]["in_use_model_hours"] = {k: int(v) for k, v in models.value_counts().items()}
    return out


def watch_cover(idx: pd.DataFrame, end: dt.date) -> dict:
    """V4-P17's source rule per day: each ercot kind has a posting within 2 h before every fixed watch."""
    days = [API_START + dt.timedelta(days=i) for i in range((end - API_START).days + 1)]
    res, fail = {}, {}
    for kind in ERCOT_KINDS:
        s = np.sort(idx[(idx.kind == kind) & (idx.key == "system")].issued_at_utc.values.astype("datetime64[s]"))
        ok = []
        for d in days:
            good = True
            for h in FIXED_WATCH_HOURS:
                w = utc(dt.datetime(d.year, d.month, d.day, h)).to_datetime64().astype("datetime64[s]")
                i = np.searchsorted(s, w, side="right") - 1
                if i < 0 or (w - s[i]) > np.timedelta64(2, "h"):
                    good = False
                    break
            ok.append(good)
        res[kind] = round(float(np.mean(ok)), 4)
        fail[kind] = [str(d) for d, g in zip(days, ok, strict=True) if not g]
    allk = [all(d not in set(fail[k]) for k in ERCOT_KINDS) for d in map(str, days)]
    return {"days": len(days), "share_of_days_all_watches_covered": res,
            "days_all_three_covered": round(float(np.mean(allk)), 4),
            "failing_days": {k: v[:40] for k, v in fail.items()}}


def store_coverage(idx: pd.DataFrame) -> dict:
    idx = idx.assign(year=idx.issued_at_utc.dt.year)
    out = {}
    for kind, g in idx.groupby("kind"):
        out[kind] = {"keys": int(g.key.nunique()), "by_year": {str(y): int(n) for y, n in
                                                               g.groupby("year").run_id.nunique().items()},
                     "vintages": len(g), "n_hours": [int(g.n_hours.min()), int(g.n_hours.max())]}
    return out


def window_minutes(d1: dt.date, n: int = 3) -> list[pd.Timestamp]:
    d0 = d1 - dt.timedelta(days=1)
    out = [utc(dt.datetime(d0.year, d0.month, d0.day, h)) for h in (10, 14, 18)]
    for k in range(n):
        d = d1 + dt.timedelta(days=k)
        hrs = (0, 6, 18) if k == n - 1 else (0, 6, 10, 14, 18)
        out += [utc(dt.datetime(d.year, d.month, d.day, h)) for h in hrs]
    return out


def leakage_spots(store: Path, idx: pd.DataFrame, extra_windows: int, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    first = idx[idx.kind == "price"].issued_at_utc.min()
    last = idx[idx.kind == "price"].issued_at_utc.max()
    wins = [(n, dt.date.fromisoformat(d)) for n, d in SAMPLE_WINDOWS]
    span = (last.date() - first.date()).days - 6
    wins += [(f"random-{i}", first.date() + dt.timedelta(days=3 + int(x)))
             for i, x in enumerate(rng.integers(0, max(1, span), extra_windows))]
    vint = {}
    rows = []
    for name, d1 in wins:
        watches = window_minutes(d1)
        for kind, key in SPOT_KEYS:
            g = idx[(idx.kind == kind) & (idx.key == key)].sort_values("reveal_at_utc")
            if g.empty:
                continue
            served = []
            for w in watches:
                h = g[g.reveal_at_utc <= w]
                if h.empty:
                    continue
                r = h.iloc[-1]
                served.append((w, r))
                rows.append({"window": name, "kind": kind, "key": key, "watch": str(w),
                             "issued_ok": bool(r.issued_at_utc <= w), "reveal_ok": bool(r.reveal_at_utc <= w)})
            seq = [(r.issued_at_utc, r.sha, r.run_id) for _, r in served]
            changes = [(a, b) for a, b in zip(seq, seq[1:], strict=False) if a[0] != b[0]]
            same_sha = [(a[2], b[2]) for a, b in changes if a[1] == b[1]]
            vint[f"{name}|{kind}|{key}"] = {"watches": len(served), "new_vintages": len(changes),
                                            "identical_sha_after_new_vintage": same_sha}
    df = pd.DataFrame(rows)
    ok_issue = bool(df.issued_ok.all() and df.reveal_ok.all()) if len(df) else None
    shas = check_shas(store, idx, wins)
    return {"windows": [[n, str(d)] for n, d in wins], "served_checks": len(df), "all_issued_at_le_watch": ok_issue,
            "vintage_changes": vint, "sha_recomputed": shas,
            "identical_after_change": sum(len(v["identical_sha_after_new_vintage"]) for v in vint.values()),
            "changes": sum(v["new_vintages"] for v in vint.values())}


def check_shas(store: Path, idx: pd.DataFrame, wins) -> dict:
    """Recompute each sample window vintage's sha from its rows, as forecast_inputs.slice_for reads them."""
    n = bad = 0
    for _, d1 in wins:
        lo = FI.iso_utc(utc(dt.datetime(d1.year, d1.month, d1.day)) - pd.Timedelta(days=2))
        hi = FI.iso_utc(utc(dt.datetime(d1.year, d1.month, d1.day)) + pd.Timedelta(days=3))
        p = store / "vintages" / f"{d1.year}.parquet"
        if not p.exists():
            continue
        t = pq.read_table(p, filters=[("issued_at_utc", ">=", lo), ("issued_at_utc", "<", hi)]).to_pandas()
        t = t[t.kind.isin([k for k, _ in SPOT_KEYS])]
        for _, g in t.groupby(["kind", "key", "run_id", "sha"]):
            fields = {f: [round(float(x), 2) for x in v] for f, v in zip(g.field, g["values"], strict=True)}
            n += 1
            bad += FI.vintage_sha(fields) != g.sha.iloc[0]
    return {"checked": n, "mismatch": bad}


def spot_check_api_vs_mis(cache: Path, store: Path, mis_zip: Path | None) -> dict | None:
    """Compare a NP4-745 posting cached from MIS (lane D3) with the same posting fetched through the API."""
    if mis_zip is None or not mis_zip.exists():
        return None
    z = zipfile.ZipFile(mis_zip)
    inner = z.read(z.namelist()[0])
    if inner[:2] == b"PK":
        iz = zipfile.ZipFile(io.BytesIO(inner))
        inner = iz.read(iz.namelist()[0])
    mis = pd.read_csv(io.BytesIO(inner))
    api_dir = cache / "ercot" / "spot"
    api = sorted(api_dir.glob("*.csv"))
    if not api:
        return {"mis_file": mis_zip.name, "api": "not fetched"}
    a = pd.read_csv(api[0])
    cols = [c for c in mis.columns if c in a.columns and c.startswith(("STPPF", "PVGRPP", "GEN", "COP"))]
    m = mis.merge(a, on=[mis.columns[0], mis.columns[1]], suffixes=("_mis", "_api"))
    diffs = {c: float(np.nanmax(np.abs(m[f"{c}_mis"] - m[f"{c}_api"]))) for c in cols}
    return {"mis_file": mis_zip.name, "api_file": api[0].name, "rows_mis": len(mis), "rows_api": len(a),
            "rows_matched": len(m), "max_abs_diff_by_column": diffs,
            "identical": bool(len(m) == len(mis) == len(a) and max(diffs.values(), default=0) == 0)}


def sizes(cache: Path) -> dict:
    out = {k: round(dir_size(cache / k) / 1e9, 3) for k in ("hrrr", "eia930", "ercot", "store")}
    out["hrrr_points_gb"] = round(dir_size(cache / "hrrr" / "points") / 1e9, 3)
    out["ercot_raw_gb"] = round(dir_size(cache / "ercot" / "raw") / 1e9, 3)
    out["store_vintages_gb"] = round(dir_size(cache / "store" / "vintages") / 1e9, 3)
    return out


def table(head: list[str], rows: list[list]) -> list[str]:
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)] + ["| " + " | ".join(map(str, r)) + " |"
                                                                       for r in rows]


def md(c: dict, args) -> str:
    h, e, er, w, st, lk = c["hrrr"], c["eia930"], c["ercot"], c["watch_cover"], c["store"], c["leakage"]
    posts = ", ".join(f"{r} {v['postings']:,} postings" for r, v in er["reports"].items())
    deep = w["days_all_three_covered"] >= 0.95
    hs = h["staleness_10cpt"]
    shas = lk["sha_recomputed"]
    L = ["# GridSimEnv v4: forecast store depth report", "",
         f"Built {c['built_utc']} by `scripts/forecast_depth.py` from `cache/forecast/` (store "
         f"`{c['store_sha'][:16]}`). Machine-readable: `data/forecast/coverage.json`. Times are CPT unless marked UTC.",
         "", "## Answer", "",
         f"- **API era (2023-12-11 on)**: {posts}. On {w['days_all_three_covered']:.1%} of {w['days']} days all three "
         "ERCOT kinds have a posting within 2 h before every fixed watch (00, 06, 10, 14, 18), so ERCOT's own "
         + ("vintages are deep enough to serve V4-P17's `ercot` windows." if deep else
            "vintages have gaps: the days below fall back to `desk` under V4-P17's rule."),
         f"- **HRRR**: {h['runs']:,} of {h['expected_runs']:,} 00/06/12/18Z runs {args.hrrr_start}..{args.hrrr_end} "
         f"({h['runs'] / h['expected_runs']:.2%}); {len(h['missing_runs'])} missing; age of the latest run at 10:00 "
         f"p50 {hs.get('p50_h')} h, max {hs.get('max_h')} h.",
         f"- **EIA-930 ERCO**: {e['span'][0][:10]}..{e['span'][1][:10]}, DF on {e['df_days']:,} operating days.",
         f"- **Leakage spot checks**: {lk['served_checks']:,} served (watch, kind, key) lookups in "
         f"{len(lk['windows'])} windows, issued_at <= watch in all: {lk['all_issued_at_le_watch']}; "
         f"{lk['changes']:,} vintage changes, {lk['identical_after_change']} with an identical sha; sha recomputed "
         f"for {shas['checked']:,} vintages, {shas['mismatch']} mismatches.",
         "", "## HRRR (NOAA, as issued; issued_at = cycle + 120 min)", ""]
    rows = []
    for y, r in h["by_year"].items():
        lag = r["lastmodified_lag_min"]
        rows.append([y, r["runs"], r["expected"], f"{r['coverage']:.2%}", r["complete_fh"], r["partial_fh"],
                     r["fh_max"], r["backfilled"], "/".join(str(lag[k]) for k in ("p50", "p90", "max")) if lag else "-",
                     r["gb_read"]])
    L += table(["Year", "Runs", "Expected", "Coverage", "Complete f00..fN", "Partial", "fh max", "Backfilled",
                "LastModified lag p50/p90/max (min)", "GB read"], rows)
    miss = h["missing_runs"]
    L += ["", f"Missing runs: {', '.join(miss[:30]) or 'none'}{' …' if len(miss) > 30 else ''}. Runs with missing "
              f"forecast hours: {', '.join(h['missing_fh_runs'][:20]) or 'none'}.", "",
          "Backfilled runs (S3 LastModified > cycle + 180 min) are kept; the store times every run at cycle + 120 min "
          "(V4-P3) and keeps LastModified and the flag for the audit.", "",
          "## EIA-930 ERCO (reveal: DF 06:00 on its day, demand hour end + 60 min, fuel D+1 06:00)", ""]
    L += table(["Year", "Hours/expected", "DF", "Demand", "Wind", "Solar", "Demand imputed (h)", "Subregions"],
               [[y, f"{r['hours']}/{r['expected']}", f"{r['df_mw_non_null']:.2%}", f"{r['demand_mw_non_null']:.2%}",
                 f"{r['wind_mw_non_null']:.2%}", f"{r['solar_mw_non_null']:.2%}", r["demand_imputed_h"],
                 f"{e['subregion_non_null_by_year'].get(y, 0):.2%}"] for y, r in e["by_year"].items()])
    L += ["", "## ERCOT public API vintages (2023-12-11 on; issued_at = the API's postDatetime, CPT to UTC)", ""]
    rows = []
    for rep, r in er["reports"].items():
        s = r["staleness_10cpt"]
        rows.append([rep, f"{r['postings']:,}", f"{r['listed_csv_docs']:,}", r["first"][:16], r["last"][:16],
                     f":{r['posting_minute_mode']:02d}", r["days_with_lt_23_postings"], r["gaps_over_1_5h"],
                     f"{s.get('p50_h')}/{s.get('p95_h')}/{s.get('max_h')}", f"{r['dst_postings']:,}",
                     r["dst_ambiguous"]])
    L += table(["Report", "Postings", "Listed", "First", "Last", "Minute", "Days < 23", "Gaps > 1.5 h",
                "Age at 10:00 p50/p95/max (h)", "DST postings", "Ambiguous"], rows)
    L.append("")
    for rep, r in er["reports"].items():
        if r["largest_gaps"]:
            L.append(f"- {rep} largest gaps: " + "; ".join(f"{g['hours']} h after {g['after'][:16]} UTC"
                                                          for g in r["largest_gaps"]))
        if "in_use_model_hours" in r:
            L.append(f"- {rep} in-use model by hour: "
                     + ", ".join(f"{k} {v:,}" for k, v in r["in_use_model_hours"].items()))
        for k in ("zones_sum_vs_system_total_max_abs_mw", "regions_sum_vs_system_wide_max_abs_stppf_mw",
                  "regions_sum_vs_system_wide_max_abs_pvgrpp_mw"):
            if k in r:
                L.append(f"- {rep} {k.replace('_', ' ')}: {r[k]}")
        if r["fallback_hour_postings"]:
            L.append(f"- {rep} fall-back hour postings (local, as the API reports them): "
                     f"{', '.join(r['fallback_hour_postings'])}")
    share = ", ".join(f"{k} {v:.2%}" for k, v in w["share_of_days_all_watches_covered"].items())
    L += ["", f"Watch cover (V4-P17's `source` rule): share of days whose five fixed watches each have a posting "
              f"within 2 h before: {share}; all three {w['days_all_three_covered']:.2%}.", ""]
    for k, v in w["failing_days"].items():
        if v:
            L.append(f"- {k} failing days: {', '.join(v[:25])}{' …' if len(v) > 25 else ''}")
    sc = c.get("api_vs_mis")
    L += ["", "## Archive vs API spot check", ""]
    if sc and "rows_matched" in sc:
        diffs = ", ".join(f"{k} {v:g}" for k, v in sc["max_abs_diff_by_column"].items())
        L.append(f"NP4-745 posting `{sc['mis_file']}` cached from MIS by lane D3 vs the same posting through the API "
                 f"(`{sc['api_file']}`): {sc['rows_matched']} of {sc['rows_mis']} rows matched, identical: "
                 f"{sc['identical']}; max abs diff by column: {diffs}.")
    else:
        L.append("Not run (no MIS-cached posting overlaps the API pull).")
    L += ["", "## Store", ""]
    L += table(["Kind", "Keys", "Vintages", "Hours", "Runs or postings by year"],
               [[k, r["keys"], f"{r['vintages']:,}", f"{r['n_hours'][0]}-{r['n_hours'][1]}",
                 ", ".join(f"{y}: {n:,}" for y, n in r["by_year"].items())] for k, r in st.items()])
    z = c["sizes"]
    wins = ", ".join(f"{n} (d1 {d})" for n, d in lk["windows"])
    keys = ", ".join(f"`{k}/{key}`" for k, key in SPOT_KEYS)
    L += ["", f"Sizes (GB): HRRR points {z['hrrr_points_gb']}, EIA-930 {z['eia930']}, ERCOT raw {z['ercot_raw_gb']}, "
              f"store {z['store']} (vintages {z['store_vintages_gb']}).", "", "## Leakage spot checks", "",
          f"Windows: {wins}. For each fixed watch of a `front` window and each of {keys}, the served vintage (the "
          f"latest with reveal_at <= the watch) has issued_at <= the watch in all {lk['served_checks']:,} lookups "
          f"({lk['all_issued_at_le_watch']}); across a window's watches {lk['changes']:,} served vintages changed, "
          f"{lk['identical_after_change']} of them to a vintage with the same sha.", ""]
    L += builder_section(Path(args.cache) / "store" / "manifest.json", Path(args.data) / "forecast" / "guide-card.json")
    return "\n".join(L) + "\n"


def builder_section(manifest: Path, card: Path) -> list[str]:
    m, g = json.loads(manifest.read_text()), json.loads(card.read_text())
    lk, can = m.get("leakage", {}), (m.get("leakage", {}).get("canary") or {})
    worst = lk.get("reveal_assertion", {}).get("worst_minutes_after_issued_at", {})
    n_before, n_after = can.get("vintages_before_cutoff", 0), can.get("vintages_after_cutoff", 0)
    L = ["## Builder leakage tests and the guide card", "",
         "- Reveal assertion: every feature family's latest reveal minus the vintage's issued_at is <= 0 ("
         + ", ".join(f"{k} {v:g} min" for k, v in worst.items()) + ").",
         f"- Canary (cutoff {can.get('cutoff_utc')}, reduced build to {can.get('until')}): "
         f"{can.get('identical_before_cutoff', 0):,} of {n_before:,} vintages issued before the cutoff identical, "
         f"{can.get('changed_after_cutoff', 0):,} of {n_after:,} after it changed: {can.get('ok')}.",
         f"- Quantiles sorted per hour: {lk.get('quantiles_sorted')}.", "",
         "Guide P50 MAE vs persistence at the DAM horizon (14-38 h), $/MWh, and 80% coverage:", ""]
    rows = []
    for y, v in g["guide"].items():
        r = [y]
        for t in ("da", "rt", "mcpc"):
            b = v.get(t, {}).get("14-38h", {})
            r.append(f"{b.get('mae_p50')} / {b.get('mae_persistence')} / {b.get('coverage_80')}")
        d = g["desk"].get(y, {})
        r += [d.get("load|system", {}).get("mape"), d.get("wind|system", {}).get("nmae"),
              d.get("solar|system", {}).get("nmae")]
        rows.append(r)
    L += table(["Year", "DA", "RT", "MCPC", "Desk load MAPE", "Desk wind nMAE", "Desk solar nMAE"], rows)
    L += ["", "The store, its raw pulls (HRRR points, EIA-930 CSVs, ERCOT API zips) and this report's inputs are in "
              "Scale-internal object storage under `gridsim/v4/` (`store/store-<sha>.tar.zst`, `raw/`).", ""]
    return L


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default=str(ROOT / "cache" / "forecast"))
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--docs", default=str(ROOT / "docs"))
    ap.add_argument("--hrrr-start", default="2019-07-01")
    ap.add_argument("--hrrr-end", default="2026-10-17")
    ap.add_argument("--ercot-end", default="2026-10-23")
    ap.add_argument("--mis-zip", default=str(ROOT / "cache" / "raw" / "hybrid" / "np4_745" / "PVGR_20261024_0655.zip"))
    ap.add_argument("--windows", type=int, default=12)
    ap.add_argument("--render", action="store_true", help="only re-render the report from DATA/forecast/coverage.json")
    args = ap.parse_args()
    if args.render:
        c = json.loads((Path(args.data) / "forecast" / "coverage.json").read_text())
        (Path(args.docs) / "v4-depth.md").write_text(md(c, args))
        return
    cache = Path(args.cache)
    store = cache / "store"
    man = json.loads((store / "manifest.json").read_text())
    idx = pd.read_parquet(store / "index.parquet")
    for c in ("issued_at_utc", "reveal_at_utc", "start_utc"):
        idx[c] = pd.to_datetime(idx[c], utc=True)
    c = {"built_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "store_sha": man["store_sha"],
         "hrrr": hrrr_coverage(cache, args.hrrr_start, args.hrrr_end), "eia930": eia_coverage(cache),
         "ercot": ercot_coverage(cache, store, dt.date.fromisoformat(args.ercot_end)),
         "watch_cover": watch_cover(idx, dt.date.fromisoformat(args.ercot_end)), "store": store_coverage(idx),
         "api_vs_mis": spot_check_api_vs_mis(cache, store, Path(args.mis_zip)), "sizes": sizes(cache),
         "leakage": leakage_spots(store, idx, args.windows)}
    (Path(args.data) / "forecast" / "coverage.json").write_text(json.dumps(c, indent=1, default=str))
    (Path(args.docs) / "v4-depth.md").write_text(md(c, args))
    print(json.dumps({k: c[k] for k in ("watch_cover", "sizes")}, default=str)[:2000])
    print({k: v for k, v in c["leakage"].items() if k != "vintage_changes"})


if __name__ == "__main__":
    main()
