"""Extract HRRR point forecasts as issued for the v4 forecast store (docs/CONTRACT-v4.md, data lane).

Reads NOAA's public bucket noaa-hrrr-bdp-pds over unsigned HTTPS: for each 00/06/12/18Z run, the S3 listing (for
LastModified and the forecast hours present), then per forecast hour the GRIB2 .idx and one byte range per field
(TMP 2 m, UGRD/VGRD 80 m, DSWRF surface, TCDC entire atmosphere), decoded with eccodes at the grid cells in
data/forecast/points.json. One parquet per run under OUT/runs/, so a stopped job resumes; --merge writes
OUT/runs.parquet and OUT/points/YYYY.parquet. Run it in us-east-1 (the bucket's region): ~260-300 MB and ~3 CPU-s per
run. Needs: pip install eccodes numpy pyarrow."""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import multiprocessing as mp
import re
import time
import urllib.request
from pathlib import Path

import eccodes
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
CYCLES = (0, 6, 12, 18)
FIELDS = {"t2m_k": ("TMP", "2 m above ground"), "u80_ms": ("UGRD", "80 m above ground"),
          "v80_ms": ("VGRD", "80 m above ground"), "dswrf_wm2": ("DSWRF", "surface"),
          "tcdc_pct": ("TCDC", "entire atmosphere")}
ISSUE_MIN = 120
BACKFILL_MIN = 180
V4_START = dt.datetime(2020, 12, 2, 12, tzinfo=dt.UTC)
_KEY = re.compile(r"<Key>([^<]+)</Key>.*?<LastModified>([^<]+)</LastModified>", re.S)


def points() -> tuple[list[str], np.ndarray, dict]:
    d = json.loads((ROOT / "data" / "forecast" / "points.json").read_text())
    return [p["id"] for p in d["points"]], np.array([p["grid_index"] for p in d["points"]]), d


def get(url: str, rng: tuple[int, int | None] | None = None) -> bytes:
    hdr = {"Range": f"bytes={rng[0]}-{'' if rng[1] is None else rng[1]}"} if rng else {}
    for attempt in range(6):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=120) as r:
                return r.read()
        except Exception:
            if attempt == 5:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError(url)


def listing(day: dt.date, cyc: int) -> dict[int, str]:
    """{forecast hour: LastModified of its .idx}."""
    prefix = f"hrrr.{day:%Y%m%d}/conus/hrrr.t{cyc:02d}z.wrfsfcf"
    xml = get(f"{BASE}/?list-type=2&prefix={prefix}").decode()
    out = {}
    for key, lm in _KEY.findall(xml):
        if key.endswith(".grib2.idx"):
            out[int(key.split("wrfsfcf")[1].split(".")[0])] = lm
    return out


def ranges(idx: str) -> dict[str, tuple[int, int | None]]:
    rows = [line.split(":") for line in idx.strip().splitlines()]
    out = {}
    for i, r in enumerate(rows):
        for name, (var, level) in FIELDS.items():
            if name not in out and r[3] == var and r[4] == level:
                out[name] = (int(r[1]), int(rows[i + 1][1]) - 1 if i + 1 < len(rows) else None)
    return out


def one_hour(day: dt.date, cyc: int, fh: int, index: np.ndarray) -> tuple[dict[str, np.ndarray], int]:
    key = f"{BASE}/hrrr.{day:%Y%m%d}/conus/hrrr.t{cyc:02d}z.wrfsfcf{fh:02d}.grib2"
    idx = get(key + ".idx")
    nbytes, vals = len(idx), {}
    for name, rng in ranges(idx.decode()).items():
        msg = get(key, rng)
        nbytes += len(msg)
        gid = eccodes.codes_new_from_message(msg)
        try:
            vals[name] = eccodes.codes_get_values(gid)[index].astype(np.float32)
        finally:
            eccodes.codes_release(gid)
    return vals, nbytes


def run_one(args: tuple[str, int, str, int]) -> dict:
    day_s, cyc, out_s, threads = args
    day, out = dt.date.fromisoformat(day_s), Path(out_s)
    run_id = f"{day_s}T{cyc:02d}Z"
    path = out / "runs" / f"{day:%Y%m%d}_{cyc:02d}z.parquet"
    if path.exists():
        return json.loads(pq.read_metadata(path).metadata[b"run"])
    ids, index, _ = points()
    t0 = time.time()
    lm = listing(day, cyc)
    cycle = dt.datetime(day.year, day.month, day.day, cyc, tzinfo=dt.UTC)
    rows = {k: [] for k in ("point", "fh", "valid_utc", *FIELDS)}
    total = 0
    with cf.ThreadPoolExecutor(threads) as ex:
        for fh, (vals, nb) in zip(sorted(lm), ex.map(lambda f: one_hour(day, cyc, f, index), sorted(lm)), strict=True):
            total += nb
            valid = (cycle + dt.timedelta(hours=fh)).strftime("%Y-%m-%dT%H:%M:%SZ")
            for i, p in enumerate(ids):
                rows["point"].append(p)
                rows["fh"].append(fh)
                rows["valid_utc"].append(valid)
                for name in FIELDS:
                    rows[name].append(float(vals[name][i]) if name in vals else float("nan"))
    last = max((dt.datetime.fromisoformat(v.replace("Z", "+00:00")) for v in lm.values()), default=None)
    meta = {"run_id": run_id, "cycle_utc": cycle.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "issued_at_utc": (cycle + dt.timedelta(minutes=ISSUE_MIN)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "s3_last_modified_utc": last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None,
            "fh_max": max(lm) if lm else None, "n_fh": len(lm), "hrrr": "v4" if cycle >= V4_START else "v3",
            "backfilled": bool(last and (last - cycle).total_seconds() / 60 > BACKFILL_MIN),
            "bytes": total, "seconds": round(time.time() - t0, 1)}
    table = pa.table({"run_id": [run_id] * len(rows["point"]), **rows})
    table = table.replace_schema_metadata({"run": json.dumps(meta)})
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd")
    tmp.rename(path)
    return meta


def merge(out: Path):
    files = sorted((out / "runs").glob("*.parquet"))
    metas = [json.loads(pq.read_metadata(f).metadata[b"run"]) for f in files]
    pq.write_table(pa.Table.from_pylist(metas), out / "runs.parquet", compression="zstd")
    by_year: dict[str, list[Path]] = {}
    for f in files:
        by_year.setdefault(f.name[:4], []).append(f)
    (out / "points").mkdir(exist_ok=True)
    for year, fs in sorted(by_year.items()):
        pq.write_table(pa.concat_tables(pq.read_table(f) for f in fs), out / "points" / f"{year}.parquet",
                       compression="zstd")
        print(f"[fetch_hrrr_points] {year}: {len(fs)} runs", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2019-07-01")
    ap.add_argument("--end", default="2026-10-17")
    ap.add_argument("--out", default=str(ROOT / "cache" / "forecast" / "hrrr"))
    ap.add_argument("--procs", type=int, default=max(1, mp.cpu_count()))
    ap.add_argument("--threads", type=int, default=16, help="concurrent range GETs per run")
    ap.add_argument("--merge", action="store_true", help="only merge the per-run files")
    args = ap.parse_args()
    out = Path(args.out)
    if args.merge:
        merge(out)
        return
    d, end, jobs = dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end), []
    while d <= end:
        jobs += [(d.isoformat(), c, str(out), args.threads) for c in CYCLES]
        d += dt.timedelta(days=1)
    t0, done, nbytes = time.time(), 0, 0
    with mp.Pool(args.procs) as pool:
        for meta in pool.imap_unordered(run_one, jobs):
            done += 1
            nbytes += meta.get("bytes", 0)
            if done % 50 == 0 or done == len(jobs):
                rate = nbytes / max(1e-9, time.time() - t0) / 1e6
                print(f"[fetch_hrrr_points] {done}/{len(jobs)} runs, {nbytes / 1e9:.1f} GB, {rate:.0f} MB/s",
                      flush=True)
    merge(out)


if __name__ == "__main__":
    main()
