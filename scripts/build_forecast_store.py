"""Build the v4 forecast store (docs/CONTRACT-v4.md, "Forecast store") from the raw pulls in cache/forecast/:
hrrr/ (scripts/fetch_hrrr_points.py), eia930/ (scripts/fetch_eia930.py), ercot/raw/ (scripts/fetch_ercot_vintages.py),
v1's parsed DAM and RT SPPs (cache/parsed/), lane D3's DA MCPC and solar cf (data/hybrid/) and EIA-860M.

Writes the store through gridsim_core.forecast_inputs.write_store (store/vintages/YYYY.parquet, index.parquet,
manifest.json), plus store/ercot_postings.parquet, data/forecast/guide-card.json and data/forecast/store-index-sha.txt.
Desk load/wind/solar models and the price guide are refitted per calendar year Y on rows whose features and targets
were revealed before Y-01-01 00:00 CPT and serve the HRRR runs issued in Y; the guide's 2021 training rows (2019-07..
2020-12) read desk forecasts cross-fitted by half-year inside that span. Every feature is read at the vintage's
issued_at through the reveal table and asserted.
--canary CUTOFF runs leakage test 1 on a reduced build instead."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import multiprocessing as mp
import os
import re
import sys
import time
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pandas.tseries.holiday import USFederalHolidayCalendar
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import forecast_inputs as FI  # noqa: E402

BUILDER_VERSION = "1.0"
CPT = ZoneInfo("America/Chicago")
T0 = np.datetime64("2018-07-01T00", "h")
T_END = np.datetime64("2026-10-27T00", "h")
N = int((T_END - T0).astype(int))
EPOCH_H = int((T0 - np.datetime64("1970-01-01T00", "h")).astype(int))
D0 = dt.date(2018, 6, 30)
H = 72
HRRR_START = "2019-07-01"
STORE_FROM = 2021
ISSUE_MIN = 120
POINTS13 = ("HB_HOUSTON", "HB_NORTH", "HB_PAN", "HB_SOUTH", "HB_WEST", "LZ_AEN", "LZ_CPS", "LZ_HOUSTON", "LZ_LCRA",
            "LZ_NORTH", "LZ_RAYBN", "LZ_SOUTH", "LZ_WEST")
HUB = "HB_HUBAVG"
PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")
ECRS_FROM = dt.date(2023, 6, 10)
ERAS = ((dt.date(2014, 1, 1), 9000.0, 0, 0), (dt.date(2022, 1, 1), 5000.0, 0, 0), (ECRS_FROM, 5000.0, 1, 0),
        (dt.date(2025, 12, 5), 5000.0, 1, 1))
QS = (0.1, 0.5, 0.9)
MONTHLY_ORIGIN = {("mcpc", 2021)}
WIND_CAP_MS = 12.5
SOLAR_LATLON = (31.5, -100.5)
ERCOT_SOLAR_CALIB = 1.2991
DESK = ("load", "wind", "solar")
LOAD_KEYS = ("system", "COAS", "EAST", "FWES", "NCEN", "NRTH", "SCEN", "SOUT", "WEST")
OOF_BLOCKS = (("2019-07-01", "2020-01-01"), ("2020-01-01", "2020-07-01"), ("2020-07-01", "2021-01-01"))
DESK_GBR = dict(max_iter=200, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=100, early_stopping=False,
                random_state=0)
GUIDE_GBR = dict(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, min_samples_leaf=200, early_stopping=False,
                 random_state=0)
NP3_565_ZONES = {"Coast": "COAS", "East": "EAST", "FarWest": "FWES", "North": "NRTH", "NorthCentral": "NCEN",
                 "SouthCentral": "SCEN", "Southern": "SOUT", "West": "WEST"}
ERCOT_KIND = {"np3-565-cd": "ercot_load", "np4-732-cd": "ercot_wind", "np4-742-cd": "ercot_wind",
              "np4-745-cd": "ercot_solar"}
ERCOT_FIELDS = {"STWPF": "stwpf_mw", "WGRPP": "wgrpp_mw", "STPPF": "stppf_mw", "PVGRPP": "pvgrpp_mw"}
G: dict = {}


def log(msg: str):
    print(f"[build_forecast_store {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---- time ----

def hidx(ts) -> np.ndarray:
    return (np.asarray(ts, dtype="datetime64[h]") - T0).astype(np.int64)


def iso(i) -> str:
    return str(T0 + np.timedelta64(int(i), "h")) + ":00:00Z"


def year_start(y: int) -> int:
    return int(hidx(np.datetime64(pd.Timestamp(dt.datetime(y, 1, 1), tz=CPT).tz_convert("UTC").tz_localize(None),
                                  "h")))


def calendar() -> dict:
    t = pd.date_range(pd.Timestamp(str(T0)), periods=N, freq="h", tz="UTC").tz_convert(CPT)
    d = np.array([(x - D0).days for x in t.date], dtype=np.int64)
    nd = int(d.max()) + 2
    first = np.full(nd + 1, -1, dtype=np.int64)
    for i in range(N - 1, -1, -1):
        first[d[i]] = i
    dates = [D0 + dt.timedelta(days=int(k)) for k in range(nd + 1)]
    hol = {(x.date() - D0).days for x in USFederalHolidayCalendar().holidays("2018-01-01", "2027-12-31")}

    def at(k: int, hh: int, mm: int) -> int:
        x = dates[k]
        return int((pd.Timestamp(dt.datetime(x.year, x.month, x.day, hh, mm), tz=CPT).tz_convert("UTC")
                    .tz_localize(None) - pd.Timestamp(str(T0))).total_seconds() // 60)

    return {"hour": t.hour.values.astype(np.int64), "wd": t.dayofweek.values.astype(np.int64),
            "month": t.month.values.astype(np.int64), "day": d, "doy": t.day_of_year.values.astype(np.int64),
            "hol": np.isin(d, list(hol)).astype(np.int8), "first": first, "dates": dates,
            "min_0600": np.array([at(k, 6, 0) for k in range(nd + 1)]),
            "min_1330": np.array([at(k, 13, 30) for k in range(nd + 1)]),
            "min_0000": np.array([at(k, 0, 0) for k in range(nd + 1)])}


def day_rows(cal: dict, vals: dict[dt.date, list[float]]) -> np.ndarray:
    """{local date: 24 values} -> [day, 24] (DST days and other lengths stay NaN)."""
    out = np.full((len(cal["dates"]), 24), np.nan, dtype=np.float64)
    for d, v in vals.items():
        k = (d - D0).days
        if 0 <= k < len(out) and v is not None and len(v) == 24:
            out[k] = v
    return out


def hourly_from_days(cal: dict, table: np.ndarray) -> np.ndarray:
    out = np.full(N, np.nan)
    ok = cal["first"][cal["day"]] >= 0
    pos = np.arange(N) - cal["first"][cal["day"]]
    sel = ok & (pos < 24)
    out[sel] = table[cal["day"][sel], cal["hour"][sel]]
    n24 = np.bincount(cal["day"], minlength=len(table))
    out[n24[cal["day"]] != 24] = np.nan
    return out


# ---- inputs ----

def load_eia(cache: Path) -> dict:
    b = pd.read_parquet(cache / "eia930" / "erco.parquet")
    s = pd.read_parquet(cache / "eia930" / "erco_sub.parquet")
    out = {}
    i = hidx(pd.to_datetime(b["hour_end_utc"], utc=True).dt.tz_localize(None).values.astype("datetime64[h]")) - 1
    ok = (i >= 0) & (i < N)
    for c in ("df_mw", "demand_mw", "wind_mw", "solar_mw"):
        a = np.full(N, np.nan)
        a[i[ok]] = b[c].values[ok]
        out[c.removesuffix("_mw")] = a
    zones = json.loads((ROOT / "data" / "forecast" / "points.json").read_text())["zones"]
    j = hidx(pd.to_datetime(s["hour_end_utc"], utc=True).dt.tz_localize(None).values.astype("datetime64[h]")) - 1
    for code in zones:
        a = np.full(N, np.nan)
        m = (s["subregion"].values == code) & (j >= 0) & (j < N)
        a[j[m]] = s["demand_mw"].values[m]
        out[f"sub_{code}"] = a
    out["demand"][out["demand"] <= 0] = np.nan
    return out


def load_prices(parsed: Path, cal: dict) -> dict:
    dam_f = sorted(parsed.glob("dam-*.json.gz"))[-1]
    rt_f = sorted(parsed.glob("rt-*.json.gz"))[-1]
    dam, rt = json.load(gzip.open(dam_f))["dam"], json.load(gzip.open(rt_f))["rt"]
    out = {"files": [dam_f.name, rt_f.name]}
    for p in (*POINTS13, HUB):
        dd = {dt.date.fromisoformat(k[:10]): v for k, v in dam.items() if k.endswith("|" + p)}
        rr = {dt.date.fromisoformat(k[:10]): [float(np.mean(v[4 * h:4 * h + 4])) for h in range(24)]
              for k, v in rt.items() if k.endswith("|" + p) and v is not None and len(v) == 96}
        out[f"da_{p}"] = day_rows(cal, dd)
        out[f"rt_{p}"] = day_rows(cal, rr)
    return out


def load_hybrid(data: Path, cal: dict) -> dict:
    out = {}
    with gzip.open(data / "hybrid" / "as_dam_mcpc.jsonl.gz", "rt") as f:
        rows = [json.loads(x) for x in f]
    for p in PRODUCTS:
        out[f"mcpc_{p}"] = day_rows(cal, {dt.date.fromisoformat(r["date"]): r.get(p) for r in rows
                                          if r.get("n_hours", 24) == 24})
    with gzip.open(data / "hybrid" / "solar_cf.jsonl.gz", "rt") as f:
        rows = [json.loads(x) for x in f]
    out["cf_d3"] = hourly_from_days(cal, day_rows(cal, {dt.date.fromisoformat(r["date"]): r["cf"] for r in rows}))
    inst = {dt.date.fromisoformat(r["date"]): r["installed_mw"] for r in rows}
    out["installed_d3"] = inst
    return out


def eia860m_solar(path: Path) -> dict[str, float]:
    """{YYYY-MM: operable ERCO PV nameplate MWac at month end} (lane D3's construction, from 2019-01)."""
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    gens = []
    for sheet in ("Operating", "Retired"):
        rows = list(wb[sheet].iter_rows(values_only=True))
        hi = next(i for i, r in enumerate(rows) if r and "Balancing Authority Code" in r)
        head = rows[hi]
        ix = {k: head.index(k) for k in ("Balancing Authority Code", "Technology", "Nameplate Capacity (MW)",
                                          "Operating Month", "Operating Year")}
        ret = (head.index("Retirement Month"), head.index("Retirement Year")) if sheet == "Retired" else None
        for r in rows[hi + 1:]:
            if r[ix["Balancing Authority Code"]] != "ERCO" or r[ix["Technology"]] != "Solar Photovoltaic":
                continue
            on = (int(r[ix["Operating Year"]]), int(r[ix["Operating Month"]]))
            off = (int(r[ret[1]]), int(r[ret[0]])) if ret else None
            gens.append((on, off, float(r[ix["Nameplate Capacity (MW)"]])))
    out, y, m = {}, 2019, 1
    while (y, m) <= (2026, 12):
        out[f"{y}-{m:02d}"] = sum(mw for on, off, mw in gens if on <= (y, m) and (off is None or off > (y, m)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def solar_target(cal: dict, eia: dict, hyb: dict, e860: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """cf target per hour (lane D3's cf; before 2021 EIA-930 solar / (EIA-860M x D3's ERCOT/EIA ratio), flagged),
    installed MW per hour (D3's of the day; before 2021 the same EIA-860M figure; after D3's last day its last)."""
    inst_day = np.full(len(cal["dates"]), np.nan)
    d3 = hyb["installed_d3"]
    last = max(d3)
    for k, d in enumerate(cal["dates"]):
        if d in d3:
            inst_day[k] = d3[d]
        elif d > last:
            inst_day[k] = d3[last]
        elif f"{d:%Y-%m}" in e860:
            inst_day[k] = e860[f"{d:%Y-%m}"] * ERCOT_SOLAR_CALIB
    inst = inst_day[cal["day"]]
    proxy = np.clip(eia["solar"] / inst, 0, 1)
    cf = np.where(np.isnan(hyb["cf_d3"]), np.where(cal["day"] < (dt.date(2021, 1, 1) - D0).days, proxy, np.nan),
                  hyb["cf_d3"])
    return cf, inst, (np.isnan(hyb["cf_d3"]) & ~np.isnan(cf))


def load_hrrr(cache: Path, points: list[str]) -> tuple[pd.DataFrame, np.ndarray]:
    d = cache / "hrrr"
    if (d / "runs.parquet").exists():
        runs = pd.read_parquet(d / "runs.parquet")
        tables = [pq.read_table(f) for f in sorted((d / "points").glob("*.parquet"))]
    else:
        files = sorted((d / "runs").glob("*.parquet"))
        runs = pd.DataFrame([json.loads(pq.read_metadata(f).metadata[b"run"]) for f in files])
        tables = [pq.read_table(f) for f in files]
    runs = runs[runs["run_id"] >= HRRR_START].sort_values("run_id").reset_index(drop=True)
    pts = pa.concat_tables(tables).to_pandas()
    ri = {r: i for i, r in enumerate(runs["run_id"])}
    pi = {p: i for i, p in enumerate(points)}
    W = np.full((len(runs), len(points), 49, 5), np.nan, dtype=np.float32)
    pts = pts[pts["run_id"].isin(ri)]
    r = pts["run_id"].map(ri).values
    p = pts["point"].map(pi).values
    f = pts["fh"].values.astype(np.int64)
    for j, c in enumerate(("t2m_k", "u80_ms", "v80_ms", "dswrf_wm2", "tcdc_pct")):
        W[r, p, f, j] = pts[c].values
    runs["a"] = hidx(pd.to_datetime(runs["issued_at_utc"]).dt.tz_localize(None).values.astype("datetime64[h]"))
    return runs, W


# ---- features ----

def hourly_weather(W: np.ndarray) -> dict[str, np.ndarray]:
    """[run, point, q] means of the instants at fh q and q + 1, q = 0..47: hour [c + q, c + q + 1)."""
    t = (W[..., 0] - 273.15) * 9 / 5 + 32
    ws = np.sqrt(W[..., 1] ** 2 + W[..., 2] ** 2)
    out = {}
    for name, x in (("t2m_f", t), ("wind80_ms", ws), ("dswrf_wm2", W[..., 3]), ("cloud_pct", W[..., 4])):
        out[name] = (x[..., :-1] + x[..., 1:]) / 2
    return out


def at_q(x: np.ndarray, q: np.ndarray) -> np.ndarray:
    """x [run, point, 48] at q [run, 72] (q outside 0..47 -> NaN) -> [run, point, 72]."""
    ok = (q >= 0) & (q < x.shape[-1])
    v = np.take_along_axis(x, np.clip(q, 0, x.shape[-1] - 1)[:, None, :].repeat(x.shape[1], 1), axis=2)
    return np.where(ok[:, None, :], v, np.nan)


def solar_elevation(i: np.ndarray) -> np.ndarray:
    ts = pd.DatetimeIndex((T0 + i.astype("timedelta64[h]")).ravel()) + pd.Timedelta(minutes=30)
    lat, lon = np.radians(SOLAR_LATLON[0]), SOLAR_LATLON[1]
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + ts.day_of_year.values) / 365)
    ha = np.radians(15 * (ts.hour.values + ts.minute.values / 60 + lon / 15 - 12))
    el = np.degrees(np.arcsin(np.sin(lat) * np.sin(decl) + np.cos(lat) * np.cos(decl) * np.cos(ha)))
    return el.reshape(i.shape)


def ffill(x: np.ndarray) -> np.ndarray:
    idx = np.where(~np.isnan(x), np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    out = x[idx]
    out[:np.argmax(~np.isnan(x))] = np.nan
    return out


def window_mean(x: np.ndarray, end: np.ndarray, n: int) -> np.ndarray:
    """mean of x over [end - n, end) ignoring NaN (end exclusive, clipped)."""
    v = np.nan_to_num(x)
    cs, cn = np.concatenate([[0], np.cumsum(v)]), np.concatenate([[0], np.cumsum(~np.isnan(x))])
    e = np.clip(end, 0, len(x))
    s = np.clip(end - n, 0, len(x))
    cnt = cn[e] - cn[s]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(cnt > 0, (cs[e] - cs[s]) / np.maximum(cnt, 1), np.nan)


def rolling_max(x: np.ndarray, n: int) -> np.ndarray:
    return pd.Series(x).rolling(n, min_periods=24).max().values


class Reveal:
    """Collects, per feature family, the latest reveal minute used minus the vintage's issued_at minute."""

    def __init__(self):
        self.worst: dict[str, float] = {}

    def check(self, name: str, reveal_min: np.ndarray, issued_min: np.ndarray):
        d = np.asarray(reveal_min, dtype=np.float64) - np.asarray(issued_min, dtype=np.float64)
        d = d[~np.isnan(d)]
        if d.size:
            self.worst[name] = max(self.worst.get(name, -np.inf), float(d.max()))
            if d.max() > 0:
                raise AssertionError(f"leakage: feature {name} revealed {d.max():.0f} min after issued_at")


def base_context(args) -> dict:
    cal = calendar()
    cache, data = Path(args.cache), Path(args.data)
    pts = json.loads((data / "forecast" / "points.json").read_text())
    names = [p["id"] for p in pts["points"]]
    log("loading EIA-930, prices, D3 inputs")
    eia = load_eia(cache)
    prices = load_prices(Path(args.parsed), cal)
    hyb = load_hybrid(data, cal)
    e860 = eia860m_solar(Path(args.eia860m))
    cf, inst, cf_proxy = solar_target(cal, eia, hyb, e860)
    log("loading HRRR points")
    runs, W = load_hrrr(cache, names)
    if args.until:
        keep = runs["run_id"] < args.until
        runs, W = runs[keep].reset_index(drop=True), W[keep.values]
    log(f"{len(runs)} runs {runs.run_id.iloc[0]}..{runs.run_id.iloc[-1]}")
    zone_pt = {code: z["point"] for code, z in pts["zones"].items()}
    sp_pt = {}
    for p in pts["points"]:
        for code in re.findall(r"(HB_[A-Z]+|LZ_[A-Z]+)", p["label"]):
            sp_pt.setdefault(code, p["id"])
    return {"cal": cal, "eia": eia, "prices": prices, "hyb": hyb, "cf": cf, "inst": inst, "cf_proxy": cf_proxy,
            "runs": runs, "W": W, "names": names, "zone_pt": zone_pt, "sp_pt": sp_pt, "e860": e860, "points": pts}


def noise(ctx: dict, cutoff_min: int, seed: int = 7):
    """Leakage test 1: every price, actual and HRRR run revealed after the cutoff becomes noise."""
    rng = np.random.default_rng(seed)
    cal = ctx["cal"]
    hour_min = np.arange(N) * 60

    def hourly(x, reveal_min):
        m = (reveal_min > cutoff_min) & ~np.isnan(x)
        x[m] = rng.normal(np.nanmean(x), np.nanstd(x) + 1, m.sum())

    e = ctx["eia"]
    hourly(e["demand"], hour_min + 120)
    hourly(e["df"], cal["min_0600"][cal["day"]].astype(float))
    fuel = cal["min_0600"][np.minimum(cal["day"] + 1, len(cal["min_0600"]) - 1)].astype(float)
    hourly(e["wind"], fuel)
    hourly(e["solar"], fuel)
    for k in e:
        if k.startswith("sub_"):
            hourly(e[k], hour_min + 60 + 31 * 1440)
    hourly(ctx["cf"], hour_min + 60)
    day_reveal = cal["min_1330"][np.maximum(np.arange(len(cal["dates"])) - 1, 0)]
    hour_reveal = (cal["first"][:, None] + np.arange(24)[None, :] + 1) * 60
    for k, v in ctx["prices"].items():
        if k.startswith("da_"):
            m = (day_reveal > cutoff_min)[:, None] & ~np.isnan(v)
            v[m] = rng.normal(np.nanmean(v), np.nanstd(v) + 1, m.sum())
        elif k.startswith("rt_"):
            m = (hour_reveal > cutoff_min) & ~np.isnan(v)
            v[m] = rng.normal(np.nanmean(v), np.nanstd(v) + 1, m.sum())
    for k, v in ctx["hyb"].items():
        if k.startswith("mcpc_"):
            m = (day_reveal > cutoff_min)[:, None] & ~np.isnan(v)
            v[m] = rng.normal(np.nanmean(v), np.nanstd(v) + 1, m.sum())
    late = (ctx["runs"]["a"].values * 60 > cutoff_min)
    ctx["W"][late] = rng.normal(280, 5, ctx["W"][late].shape).astype(np.float32)


def run_grid(ctx: dict) -> dict:
    """Per-run vintage hours t = a + 1 + j, horizon k = j + 1, the HRRR q index of each hour, and calendar."""
    runs, cal = ctx["runs"], ctx["cal"]
    a = runs["a"].values
    j = np.arange(H)
    t = a[:, None] + 1 + j[None, :]
    tc = np.clip(t, 0, N - 1)
    return {"a": a, "t": t, "tc": tc, "k": np.broadcast_to(j + 1, t.shape), "q": j[None, :] + 3 + 0 * a[:, None],
            "q3": j[None, :] + 0 * a[:, None], "amin": a * 60, "hour": cal["hour"][tc], "wd": cal["wd"][tc],
            "month": cal["month"][tc], "hol": cal["hol"][tc], "day": cal["day"][tc],
            "fh_max": runs["fh_max"].fillna(-1).values.astype(np.int64)}


def weather_at(ctx: dict, grid: dict) -> dict:
    hw = hourly_weather(ctx["W"])
    lim = grid["fh_max"][:, None] - 1
    out = {}
    for name, x in hw.items():
        q = np.where(grid["q"] <= lim, grid["q"], -1)
        out[name] = at_q(x, q)
        out[name + "_m3"] = at_q(x, np.where(grid["q3"] <= lim, grid["q3"], -1))
    return out


def desk_frames(ctx: dict, grid: dict, wx: dict, rv: Reveal) -> dict[str, dict]:
    """{series: {"X", "names", "y", "y_reveal", "scale"}} over [run * 72] rows."""
    cal, eia = ctx["cal"], ctx["eia"]
    a, t, tc, amin = grid["a"], grid["t"], grid["tc"], grid["amin"]
    R = len(a)
    pi = {p: i for i, p in enumerate(ctx["names"])}
    cal_cols = [grid["hour"], grid["wd"], grid["month"], grid["hol"], grid["k"]]
    cal_names = ["hour", "weekday", "month", "holiday", "horizon"]
    hour_min = t * 60
    am = np.broadcast_to(amin[:, None], t.shape)

    dem = ffill(eia["demand"])
    last = a - 2
    rv.check("eia_demand_last", (last + 1) * 60 + 60, amin)
    dem_last = np.broadcast_to(dem[np.clip(last, 0, N - 1)][:, None], t.shape)
    back = np.ceil((t - last[:, None]) / 24).astype(np.int64) * 24
    src = np.clip(t - back, 0, N - 1)
    rv.check("eia_demand_same_hour", (src + 1) * 60 + 60, am)
    dem_sh = dem[src]
    zones = LOAD_KEYS[1:]
    tot = np.sum([eia[f"sub_{z}"] for z in zones], axis=0)
    full = ~np.isnan(tot)
    ct = np.concatenate([[0], np.cumsum(np.where(full, tot, 0))])
    e = np.clip(a - 1 - 31 * 24, 0, N)
    s = np.clip(e - 365 * 24, 0, N)
    rv.check("eia_subregion_share", np.where(e > 0, (e - 1 + 1) * 60 + 60 + 31 * 1440, np.nan), amin)
    shares = {}
    for z in zones:
        cz = np.concatenate([[0], np.cumsum(np.where(full, eia[f"sub_{z}"], 0))])
        with np.errstate(invalid="ignore", divide="ignore"):
            shares[z] = np.where(ct[e] - ct[s] > 0, (cz[e] - cz[s]) / (ct[e] - ct[s]), np.nan)

    temps = {z: wx["t2m_f"][:, pi[ctx["zone_pt"][z]], :] for z in zones}
    temps3 = {z: wx["t2m_f_m3"][:, pi[ctx["zone_pt"][z]], :] for z in zones}
    rv.check("hrrr_run", np.broadcast_to((a - 2)[:, None] * 60 + ISSUE_MIN, t.shape), am)
    out = {}
    tmean = np.mean([temps[z] for z in zones], axis=0)
    cols = cal_cols + [temps[z] for z in zones] + [np.maximum(65 - tmean, 0), np.maximum(tmean - 65, 0),
                                                   np.mean([temps3[z] for z in zones], axis=0), dem_last, dem_sh]
    names = cal_names + [f"t2m_{z}" for z in zones] + ["hdd", "cdd", "t2m_m3", "demand_last", "demand_same_hour"]
    out["load|system"] = {"X": cols, "names": names, "y": eia["demand"][tc], "y_reveal": hour_min + 120}
    for z in zones:
        sh = shares[z][:, None]
        cols = cal_cols + [temps[z], np.maximum(65 - temps[z], 0), np.maximum(temps[z] - 65, 0), temps3[z],
                           dem_last * sh, dem_sh * sh]
        names = cal_names + ["t2m", "hdd", "cdd", "t2m_m3", "demand_last_x_share", "demand_same_hour_x_share"]
        out[f"load|{z}"] = {"X": cols, "names": names, "y": eia[f"sub_{z}"][tc],
                            "y_reveal": hour_min + 60 + 31 * 1440}

    hour_a = cal["hour"][np.clip(a, 0, N - 1)]
    dloc = cal["day"][np.clip(a, 0, N - 1)]
    last_fuel_day = dloc - np.where(hour_a >= 6, 1, 2)
    fuel_end = cal["first"][np.clip(last_fuel_day + 1, 0, len(cal["first"]) - 1)]
    rv.check("eia_fuel_generation", cal["min_0600"][np.clip(last_fuel_day + 1, 0, len(cal["min_0600"]) - 1)], amin)
    wmax = rolling_max(eia["wind"], 30 * 24)
    fleet = wmax[np.clip(fuel_end - 1, 0, N - 1)]
    wp = [pi[p] for p in ("wind_pan", "wind_west", "wind_coast", "wind_south")]
    ws = [wx["wind80_ms"][:, i, :] for i in wp]
    cols = [grid["hour"], grid["month"], grid["k"]] + ws + [np.minimum(w, WIND_CAP_MS) ** 3 / 1000 for w in ws] + \
        [np.mean(ws, axis=0), np.broadcast_to(fleet[:, None], t.shape)]
    names = ["hour", "month", "horizon"] + [f"ws80_{i}" for i in range(4)] + [f"ws80_cube_{i}" for i in range(4)] + \
        ["ws80_mean", "fleet_30d_max"]
    fuel_rev = cal["min_0600"][np.clip(cal["day"][tc] + 1, 0, len(cal["min_0600"]) - 1)]
    with np.errstate(invalid="ignore", divide="ignore"):
        out["wind|system"] = {"X": cols, "names": names, "y": eia["wind"][tc] / fleet[:, None], "y_reveal": fuel_rev,
                              "scale": np.broadcast_to(fleet[:, None], t.shape)}

    sp = [pi[p] for p in ("solar_farwest", "solar_centerwest", "solar_north")]
    cols = [grid["hour"], grid["month"], grid["k"], solar_elevation(tc)] + \
        [wx["dswrf_wm2"][:, i, :] for i in sp] + [wx["cloud_pct"][:, i, :] for i in sp]
    names = ["hour", "month", "horizon", "solar_elevation"] + [f"dswrf_{i}" for i in range(3)] + \
        [f"cloud_{i}" for i in range(3)]
    cf_rev = np.where(ctx["cf_proxy"][tc], fuel_rev, hour_min + 60)
    out["solar|system"] = {"X": cols, "names": names, "y": ctx["cf"][tc], "y_reveal": cf_rev,
                           "scale": ctx["inst"][tc]}
    for v in out.values():
        v["X"] = np.stack([np.broadcast_to(c, t.shape).reshape(-1).astype(np.float32) for c in v["X"]], axis=1)
        v["y"] = np.asarray(v["y"], dtype=np.float64).reshape(-1)
        v["y_reveal"] = np.broadcast_to(v["y_reveal"], t.shape).reshape(-1)
        if "scale" in v:
            v["scale"] = np.asarray(v["scale"], dtype=np.float64).reshape(-1)
    out["_R"] = R
    return out


def subsample(n_rows: int, frac: float, salt: int) -> np.ndarray:
    h = (np.arange(n_rows, dtype=np.uint64) * np.uint64(2654435761) + np.uint64(salt * 97)) % np.uint64(2 ** 32)
    return h.astype(np.float64) / 2 ** 32 < frac


def fit_predict(task: tuple) -> tuple:
    """task = (frame key, spec, train mask key, predict mask key, loss, quantile) over the forked globals."""
    key, kind, train_sel, pred_sel, quantile = task
    fr = G["frames"][key]
    tr, pr = G["masks"][train_sel], G["masks"][pred_sel]
    X, y = fr["X"], fr["y"]
    ok = tr & ~np.isnan(y)
    if ok.sum() < 500 or not pr.any():
        return task, None, int(ok.sum())
    params = dict(DESK_GBR if kind == "desk" else GUIDE_GBR)
    if quantile is not None:
        params.update(loss="quantile", quantile=quantile)
    cat = fr.get("categorical")
    with threadpool_limits(G["threads"]):
        m = HistGradientBoostingRegressor(categorical_features=cat, **params).fit(X[ok], y[ok])
        return task, m.predict(X[pr]).astype(np.float64), int(ok.sum())


def run_pool(tasks: list[tuple], workers: int) -> list[tuple]:
    if workers <= 1:
        return [fit_predict(t) for t in tasks]
    with mp.get_context("fork").Pool(workers) as pool:
        return list(pool.imap(fit_predict, tasks))


def year_masks(grid: dict, years: list[int], frac: float, salt: int) -> dict:
    """Training masks (issued and target revealed before Y-01-01 CPT, subsampled) and prediction masks per year."""
    a = grid["a"]
    out = {}
    for y in years:
        y0, y1 = year_start(y), year_start(y + 1)
        out[f"pred_{y}"] = np.repeat((a >= y0) & (a < y1), H)
        out[f"issued_before_{y}"] = np.repeat(a < y0, H)
        out[f"y0_{y}"] = y0
    out["sub"] = subsample(len(a) * H, frac, salt)
    return out


def desk_models(frames: dict, grid: dict, years: list[int], args, rv: Reveal) -> dict[str, np.ndarray]:
    """{series: predictions [R*72]} in target units: rolling-origin for Y >= 2021, cross-fitted before."""
    a = grid["a"]
    rows = len(a) * H
    base = year_masks(grid, years, args.desk_frac, 1)
    masks = {}
    tasks = []
    keys = [k for k in frames if not k.startswith("_")]
    for key in keys:
        fr = frames[key]
        for y in years:
            y0m = base[f"y0_{y}"] * 60
            masks[f"{key}|tr{y}"] = base["sub"] & base[f"issued_before_{y}"] & (fr["y_reveal"] <= y0m)
            masks[f"{key}|pr{y}"] = base[f"pred_{y}"]
            tasks.append((key, "desk", f"{key}|tr{y}", f"{key}|pr{y}", None))
        y0m = year_start(2021) * 60
        for b, (lo, hi) in enumerate(OOF_BLOCKS):
            blk = np.repeat((a >= year_start_iso(lo)) & (a < year_start_iso(hi)), H)
            pre = np.repeat(a < year_start(2021), H)
            masks[f"{key}|oof_tr{b}"] = base["sub"] & pre & ~blk & (fr["y_reveal"] <= y0m)
            masks[f"{key}|oof_pr{b}"] = blk
            tasks.append((key, "desk", f"{key}|oof_tr{b}", f"{key}|oof_pr{b}", None))
    G.update(frames=frames, masks=masks, threads=args.threads)
    log(f"desk: {len(tasks)} fits on {args.workers} workers")
    preds = {k: np.full(rows, np.nan) for k in keys}
    ntrain = {}
    for (key, _, tr, pr, _), p, n in run_pool(tasks, args.workers):
        ntrain[tr] = n
        if p is not None:
            v = p * frames[key]["scale"][masks[pr]] if "scale" in frames[key] else p
            preds[key][masks[pr]] = np.maximum(v, 0)
    G["desk_ntrain"] = ntrain
    return preds


def year_start_iso(s: str) -> int:
    d = dt.date.fromisoformat(s)
    return int(hidx(np.datetime64(pd.Timestamp(dt.datetime(d.year, d.month, d.day), tz=CPT).tz_convert("UTC")
                                  .tz_localize(None), "h")))


def guide_frames(ctx: dict, grid: dict, wx: dict, desk: dict, rv: Reveal) -> dict:
    cal, prices, hyb = ctx["cal"], ctx["prices"], ctx["hyb"]
    a, t, amin = grid["a"], grid["t"], grid["amin"]
    R = len(a)
    am = np.broadcast_to(amin[:, None], t.shape)
    pi = {p: i for i, p in enumerate(ctx["names"])}
    ac = np.clip(a, 0, N - 1)
    dloc, hour_a = cal["day"][ac], cal["hour"][ac]
    nd = len(cal["dates"])
    d_last = np.clip(dloc + np.where(hour_a * 60 >= 13 * 60 + 30, 1, 0), 0, nd - 1)
    rv.check("da_last_day", cal["min_1330"][np.clip(d_last - 1, 0, nd - 1)], amin)
    e_day = np.clip(dloc - 1, 0, nd - 1)
    rv.check("rt_last_full_day", cal["min_0000"][np.clip(e_day + 1, 0, nd - 1)], amin)
    rv.check("rt_last_24h", a * 60, amin)
    td = grid["day"]
    known = td <= d_last[:, None]
    rv.check("da_known_at_t", np.where(known, cal["min_1330"][np.clip(td - 1, 0, nd - 1)], np.nan), am)
    load = desk["load|system"].reshape(R, H)
    wind = desk["wind|system"].reshape(R, H)
    solar = desk["solar|system"].reshape(R, H)
    era = np.zeros((nd, 3))
    for k, d in enumerate(cal["dates"]):
        for start, hcap, ecrs, rtcb in ERAS:
            if d >= start:
                era[k] = (hcap, ecrs, rtcb)
    common = [grid["hour"], grid["wd"], grid["month"], grid["hol"], grid["k"], load, wind, solar,
              load - wind - solar, era[td, 0], era[td, 1], era[td, 2]]
    cnames = ["hour", "weekday", "month", "holiday", "horizon", "desk_load", "desk_wind", "desk_solar",
              "desk_net_load", "hcap", "ecrs", "rtcb"]
    hour_t = grid["hour"]

    def price_cols(p: str) -> tuple[list, list, np.ndarray, np.ndarray, np.ndarray]:
        da, rt = prices[f"da_{p}"], prices[f"rt_{p}"]
        rt_h = hourly_from_days(cal, rt)
        with np.errstate(invalid="ignore"):
            da_sh = da[d_last[:, None], hour_t]
            da_mean = _nanmean(da[d_last])
            da_max = _nanmax(da[d_last])
            rt24 = window_mean(rt_h, a, 24)
            rtda = _nanmean(rt[e_day] - da[e_day])
        da_t = np.where(known, da[td, hour_t], np.nan)
        cols = [da_sh, da_mean[:, None], da_max[:, None], rt24[:, None], rtda[:, None]]
        names = ["da_last_same_hour", "da_last_mean", "da_last_max", "rt_mean_24h", "rt_minus_da_last_day"]
        return cols, names, da[td, hour_t], rt[td, hour_t], da_t

    out = {}
    blocks = {"da": [], "rt": []}
    for ci, p in enumerate(POINTS13):
        temp = wx["t2m_f"][:, pi[ctx["sp_pt"][p]], :]
        pc, pn, y_da, y_rt, da_t = price_cols(p)
        X = [np.broadcast_to(c, t.shape) for c in common + [temp] + pc] + [np.full(t.shape, ci)]
        names = cnames + ["t2m_point"] + pn + ["point"]
        anchor = fill(pc[0], np.broadcast_to(pc[1], t.shape))
        blocks["da"].append((X, y_da, known, anchor))
        blocks["rt"].append((X + [da_t], y_rt, np.zeros(t.shape, bool), np.where(np.isfinite(da_t), da_t, anchor)))
        G.setdefault("persist", {})[p] = (pc[0], window_persist(hourly_from_days(cal, prices[f"rt_{p}"]), t, a))
    for target in ("da", "rt"):
        Xs = [np.stack([c.reshape(-1).astype(np.float32) for c in X], axis=1) for X, _, _, _ in blocks[target]]
        y = np.concatenate([y.reshape(-1) for _, y, _, _ in blocks[target]])
        anchor = np.concatenate([an.reshape(-1) for _, _, _, an in blocks[target]])
        out[f"price_{target}"] = {
            "X": np.concatenate(Xs), "y": y - anchor, "y_abs": y, "anchor": anchor,
            "known": np.concatenate([k.reshape(-1) for _, _, k, _ in blocks[target]]),
            "names": names + (["da_known_t"] if target == "rt" else []),
            "reveal": np.concatenate([np.broadcast_to(
                cal["min_1330"][np.clip(td - 1, 0, nd - 1)] if target == "da" else (t + 1) * 60, t.shape).reshape(-1)
                for _ in POINTS13]), "n_groups": len(POINTS13)}
    hub_cols, hub_names, _, _, _ = price_cols(HUB)
    tmean = np.mean([wx["t2m_f"][:, pi[ctx["zone_pt"][z]], :] for z in LOAD_KEYS[1:]], axis=0)
    Xs, ys, anchors = [], [], []
    for ci, prod in enumerate(PRODUCTS):
        m = hyb[f"mcpc_{prod}"]
        with np.errstate(invalid="ignore"):
            msh = m[d_last[:, None], hour_t]
            mmean = _nanmean(m[d_last])
        X = [np.broadcast_to(c, t.shape) for c in common + [tmean] + hub_cols + [msh, mmean[:, None]]] + \
            [np.full(t.shape, ci)]
        Xs.append(np.stack([c.reshape(-1).astype(np.float32) for c in X], axis=1))
        ys.append(m[td, hour_t].reshape(-1))
        anchors.append(fill(msh, np.broadcast_to(mmean[:, None], t.shape)).reshape(-1))
        G.setdefault("persist", {})[f"mcpc_{prod}"] = (msh, None)
    y, anchor = np.concatenate(ys), np.concatenate(anchors)
    out["mcpc"] = {"X": np.concatenate(Xs), "y": y - anchor, "y_abs": y, "anchor": anchor,
                   "known": np.zeros(len(ys) * R * H, bool),
                   "names": cnames + ["t2m_mean"] + [f"hub_{n}" for n in hub_names] +
                   ["mcpc_last_same_hour", "mcpc_last_mean", "product"],
                   "reveal": np.concatenate([np.broadcast_to(cal["min_1330"][np.clip(td - 1, 0, nd - 1)],
                                                             t.shape).reshape(-1)] * len(PRODUCTS)),
                   "n_groups": len(PRODUCTS)}
    for v in out.values():
        v["categorical"] = [len(v["names"]) - (2 if v["names"][-1] == "da_known_t" else 1)]
    return out


def fill(x: np.ndarray, fallback: np.ndarray) -> np.ndarray:
    """The persistence anchor the guide predicts around: x, else the fallback, else 0."""
    return np.where(np.isfinite(x), x, np.where(np.isfinite(fallback), fallback, 0.0))


def window_persist(rt_h: np.ndarray, t: np.ndarray, a: np.ndarray) -> np.ndarray:
    last = (a - 1)[:, None]
    back = np.ceil((t - last) / 24).astype(np.int64) * 24
    return rt_h[np.clip(t - back, 0, N - 1)]


def _nanmean(x: np.ndarray) -> np.ndarray:
    n = np.sum(~np.isnan(x), axis=-1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, np.nansum(x, axis=-1) / np.maximum(n, 1), np.nan)


def _nanmax(x: np.ndarray) -> np.ndarray:
    return np.where(np.all(np.isnan(x), axis=-1), np.nan, np.nanmax(np.where(np.isnan(x), -np.inf, x), axis=-1))


def guide_models(frames: dict, grid: dict, years: list[int], args) -> dict[str, np.ndarray]:
    a = grid["a"]
    masks, tasks = {}, []
    for key, fr in frames.items():
        g = fr["n_groups"]
        sub = subsample(len(a) * H * g, args.guide_frac, 2 + len(key))
        for y in years:
            origins = [(f"{y}", year_start(y), year_start(y + 1))]
            if (key, y) in MONTHLY_ORIGIN:
                origins = [(f"{y}-{m:02d}", year_start_iso(f"{y}-{m:02d}-01"),
                            year_start_iso(f"{y + (m == 12)}-{m % 12 + 1:02d}-01")) for m in range(1, 13)]
            for name, o0, o1 in origins:
                iss = np.tile(np.repeat(a < o0, H), g)
                use = np.ones_like(sub) if len(origins) > 1 else sub
                masks[f"{key}|tr{name}"] = use & iss & (fr["reveal"] <= o0 * 60) & ~fr["known"]
                masks[f"{key}|pr{name}"] = np.tile(np.repeat((a >= o0) & (a < o1), H), g)
                for q in QS:
                    tasks.append((key, "guide", f"{key}|tr{name}", f"{key}|pr{name}", q))
    G.update(frames=frames, masks=masks, threads=args.threads)
    log(f"guide: {len(tasks)} fits on {args.workers} workers")
    preds = {(k, q): np.full(len(fr["y"]), np.nan) for k, fr in frames.items() for q in QS}
    ntrain = {}
    for (key, _, tr, pr, q), p, n in run_pool(tasks, args.workers):
        ntrain[f"{tr}|q{q}"] = n
        if p is not None:
            preds[(key, q)][masks[pr]] = p + frames[key]["anchor"][masks[pr]]
    G["guide_ntrain"] = ntrain
    for key in frames:
        s = np.sort(np.stack([preds[(key, q)] for q in QS]), axis=0)
        for i, q in enumerate(QS):
            preds[(key, q)] = s[i]
    return preds


# ---- vintages ----

def iso_s(unix_s: int) -> str:
    return dt.datetime.fromtimestamp(int(unix_s), dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def vintage(kind: str, key: str, issued_s: int, run_id: str, start: int, fields: dict[str, np.ndarray],
            source: str = "desk") -> dict | None:
    """FI.vintage over the leading hours where every field is finite (no vintage when there are none); issued_s in
    Unix seconds (reveal_at = issued_at), start an hour index from T0."""
    arr = {f: np.asarray(v, dtype=np.float64) for f, v in fields.items()}
    n = min(len(v) for v in arr.values())
    bad = np.where(~np.all([np.isfinite(v[:n]) for v in arr.values()], axis=0))[0]
    n = int(bad[0]) if bad.size else n
    if n == 0:
        return None
    return FI.vintage(kind, key, iso_s(issued_s), run_id, source, iso_s((start + EPOCH_H) * 3600),
                      {f: v[:n] for f, v in arr.items()})


def desk_vintages(ctx: dict, grid: dict, wx: dict, desk: dict, guide: dict, years: list[int]) -> list[dict]:
    runs, names = ctx["runs"], ctx["names"]
    a = grid["a"]
    R = len(a)
    y0 = year_start(min(years))
    out = []
    pr = {kq: v.reshape(-1, R, H) for kq, v in guide.items()}
    lim = grid["fh_max"] - 4
    for r in range(R):
        if a[r] < y0:
            continue
        run_id, start, iss = runs["run_id"].iloc[r], int(a[r]) + 1, (int(a[r]) + EPOCH_H) * 3600
        nw = int(np.clip(lim[r] + 1, 0, H))
        for pi_, p in enumerate(names):
            f = {n: wx[n][r, pi_, :nw] for n in ("t2m_f", "wind80_ms", "dswrf_wm2", "cloud_pct")}
            bad = np.where(np.any([np.isnan(v) for v in f.values()], axis=0))[0]
            n_ok = int(bad[0]) if bad.size else nw
            if n_ok:
                out.append(vintage("weather", p, iss, run_id, start, {n: v[:n_ok] for n, v in f.items()}))
        for key in LOAD_KEYS:
            out.append(vintage("load", key, iss, run_id, start, {"mw": desk[f"load|{key}"].reshape(R, H)[r]}))
        out.append(vintage("wind", "system", iss, run_id, start, {"mw": desk["wind|system"].reshape(R, H)[r]}))
        s = desk["solar|system"].reshape(R, H)[r]
        out.append(vintage("solar", "system", iss, run_id, start, {"mw": s}))
        for gi, p in enumerate(POINTS13):
            f = {}
            for tgt in ("da", "rt"):
                for q, qn in zip(QS, ("p10", "p50", "p90"), strict=True):
                    f[f"{tgt}_{qn}"] = pr[(f"price_{tgt}", q)][gi, r]
            out.append(vintage("price", p, iss, run_id, start, f))
        last_day = ctx["cal"]["dates"][ctx["cal"]["day"][grid["tc"][r, -1]]]
        for gi, prod in enumerate(PRODUCTS):
            if prod == "ecrs" and last_day < ECRS_FROM:
                continue
            f = {qn: pr[("mcpc", q)][gi, r] for q, qn in zip(QS, ("p10", "p50", "p90"), strict=True)}
            out.append(vintage("mcpc", prod, iss, run_id, start, f))
    return out


def official_vintages(ctx: dict) -> list[dict]:
    cal, df = ctx["cal"], ctx["eia"]["df"]
    out = []
    first = (dt.date.fromisoformat(HRRR_START) - D0).days
    for k in range(first, len(cal["dates"]) - 1):
        lo, hi = cal["first"][k], cal["first"][k + 1]
        if lo < 0 or hi < 0:
            continue
        v = df[lo:hi]
        if np.isnan(v).any():
            continue
        rev = int(cal["min_0600"][k]) * 60 + EPOCH_H * 3600
        out.append(vintage("load_official", "system", rev, f"eia930-df@{cal['dates'][k]}", int(lo), {"mw": v}))
    return out


# ---- ERCOT ----

def region_key(s: str) -> str:
    s = s.replace("SYSTEM_WIDE", "system").replace("SystemWide", "system")
    if s == "system":
        return s
    return re.sub(r"(?<=[a-z])(?=[A-Z])", "_", s).upper()


def posted_utc(posts: list[dict]) -> dict[int, dict]:
    """docId -> {posted_local, posted_utc_s, dst, ambiguous}; a repeated fall-back local time goes to CST for the
    later document."""
    seen: dict[str, list[int]] = {}
    for p in sorted(posts, key=lambda x: x["docId"]):
        seen.setdefault(p["postDatetime"][:13], []).append(p["docId"])
    out = {}
    for p in posts:
        loc = dt.datetime.fromisoformat(p["postDatetime"])
        lo = loc.replace(tzinfo=CPT, fold=0)
        hi = loc.replace(tzinfo=CPT, fold=1)
        amb = lo.utcoffset() != hi.utcoffset()
        fold = 0
        if amb:
            same = seen[p["postDatetime"][:13]]
            fold = 1 if len(same) > 1 and p["docId"] == same[-1] else 0
        x = loc.replace(tzinfo=CPT, fold=fold)
        out[p["docId"]] = {"posted_local": p["postDatetime"], "posted_utc_s": int(x.timestamp()),
                           "dst": bool(x.dst()), "ambiguous": bool(amb and len(seen[p["postDatetime"][:13]]) < 2)}
    return out


def ercot_hours(df: pd.DataFrame) -> np.ndarray:
    """Hour index (from T0) of each row's delivery hour: local DeliveryDate + HourEnding - 1 h, the repeated fall-back
    hour (DSTFlag Y) in CST."""
    dcol = next(c for c in df.columns if "DATE" in c.upper())
    hcol = next(c for c in df.columns if "HOUR" in c.upper())
    dst = df["DSTFlag"].astype(str).str.upper().eq("Y") if "DSTFlag" in df else pd.Series(False, index=df.index)
    key = df[dcol].astype(str) + "|" + df[hcol].astype(str).str.split(":").str[0] + "|" + dst.astype(int).astype(str)
    uniq, inv = np.unique(key.values.astype(str), return_inverse=True)
    vals = np.empty(len(uniq), dtype=np.int64)
    for i, k in enumerate(uniq):
        d, h, f = k.split("|")
        loc = dt.datetime.strptime(d, "%m/%d/%Y") + dt.timedelta(hours=int(h) - 1)
        vals[i] = int(loc.replace(tzinfo=CPT, fold=int(f)).timestamp()) // 3600 - EPOCH_H
    return vals[inv]


def parse_bulk(task: tuple) -> tuple[list[dict], list[dict]]:
    report, path, posts = task
    kind = ERCOT_KIND[report]
    vins, meta = [], []
    z = zipfile.ZipFile(path)
    for name in sorted(z.namelist()):
        doc = int(name.split(".")[0])
        p = posts.get(doc)
        if p is None:
            continue
        inner = zipfile.ZipFile(io.BytesIO(z.read(name)))
        csv_name = inner.namelist()[0]
        df = pd.read_csv(io.BytesIO(inner.read(csv_name)))
        hrs = ercot_hours(df)
        start = p["posted_utc_s"] // 3600 - EPOCH_H
        sel = (hrs >= start) & (hrs < start + H)
        pos = hrs - start
        run_id = f"{report.upper()}@{dt.datetime.fromtimestamp(p['posted_utc_s'], dt.UTC):%Y-%m-%dT%H:%M:%SZ}"
        m = {"report": report.upper(), "doc_id": doc, "file": csv_name, **p, "run_id": run_id, "rows": len(df)}
        if report == "np3-565-cd":
            use = df["InUseFlag"].astype(str).str.upper().eq("Y").values & sel
            models = [None] * H
            for i in np.where(use)[0]:
                models[pos[i]] = str(df["Model"].iloc[i])
            m["models"] = models
            series = {}
            for col, key in NP3_565_ZONES.items():
                v = np.full(H, np.nan)
                v[pos[use]] = df[col].values[use]
                series[key] = v
            series = {"system": np.sum([series[k] for k in NP3_565_ZONES.values()], axis=0), **series}
            sys_total = np.full(H, np.nan)
            sys_total[pos[use]] = df["SystemTotal"].values[use]
            m["system_total_max_abs_diff"] = float(np.nanmax(np.abs(series["system"] - sys_total))) \
                if np.isfinite(sys_total).any() else None
            for key, v in series.items():
                vins.append(vintage(kind, key, p["posted_utc_s"], run_id, start, {"mw": v}, "ercot"))
        else:
            groups: dict[str, dict] = {}
            for col in df.columns:
                mm = re.match(r"^(STWPF|WGRPP|STPPF|PVGRPP)_(.+)$", col)
                if not mm:
                    continue
                key = region_key(mm.group(2))
                if report == "np4-742-cd" and key == "system":
                    continue
                if report == "np4-732-cd" and key != "system":
                    continue
                v = np.full(H, np.nan)
                v[pos[sel]] = pd.to_numeric(df[col], errors="coerce").values[sel]
                groups.setdefault(key, {})[ERCOT_FIELDS[mm.group(1)]] = v
            if report == "np4-745-cd":
                regions = [k for k in groups if k != "system"]
                if "system" in groups:
                    for f in ("stppf_mw", "pvgrpp_mw"):
                        s = np.sum([groups[k][f] for k in regions], axis=0)
                        m[f"system_wide_max_abs_diff_{f}"] = float(np.nanmax(np.abs(s - groups["system"][f]))) \
                            if np.isfinite(groups["system"][f]).any() and np.isfinite(s).any() else None
                        groups["system"][f] = s
            m["keys"] = sorted(groups)
            for key, f in groups.items():
                vins.append(vintage(kind, key, p["posted_utc_s"], run_id, start, f, "ercot"))
        m["start_utc_s"] = (start + EPOCH_H) * 3600
        meta.append(m)
    return vins, meta


def ercot_vintages(raw: Path, workers: int) -> tuple[list[dict], pd.DataFrame]:
    tasks = []
    for report in ERCOT_KIND:
        d = raw / report
        if not d.exists():
            continue
        posts = []
        for f in sorted((d / "listing").glob("done-*.json")):
            posts += json.loads(f.read_text())
        posts = list({p["docId"]: p for p in posts if p["friendlyName"].lower().endswith("csv")}.values())
        pu = posted_utc(posts)
        for z in sorted((d / "bulk").glob("*.zip")):
            ids = {int(n.split(".")[0]) for n in zipfile.ZipFile(z).namelist()}
            tasks.append((report, z, {k: v for k, v in pu.items() if k in ids}))
    log(f"ercot: {len(tasks)} bulk zips")
    vins, meta = [], []
    with mp.get_context("fork").Pool(workers) as pool:
        for v, m in pool.imap(parse_bulk, tasks):
            vins += v
            meta += m
    return vins, pd.DataFrame(meta)


# ---- write ----

def write_store(out: Path, vins: list[dict], extra: dict) -> dict:
    """The store through FI.write_store (the one writer the reader trusts), the manifest extended with this build's
    spans, inputs and leakage results."""
    out.mkdir(parents=True, exist_ok=True)
    for f in (out / "vintages").glob("*.parquet"):
        f.unlink()
    df = pd.DataFrame({"kind": [v["kind"] for v in vins], "key": [v["key"] for v in vins],
                       "issued_at": [v["issued_at"] for v in vins], "source": [v["source"] for v in vins]})
    spans = {k: {"first": g.issued_at.min(), "last": g.issued_at.max(), "vintages": len(g),
                 "keys": sorted(g.key.unique()), "source": sorted(g.source.unique())} for k, g in df.groupby("kind")}
    meta = {"schema": "gridsim.forecast-store/v1", "builder_version": BUILDER_VERSION,
            "built_utc": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "spans": spans, **extra}
    sha = FI.write_store(vins, out, meta)
    return json.loads((out / "manifest.json").read_text()) | {"store_sha": sha}


# ---- guide card ----

def pinball(y, q, tau):
    d = y - q
    return np.nanmean(np.maximum(tau * d, (tau - 1) * d))


def guide_card(grid: dict, frames: dict, preds: dict, desk_frames_: dict, desk: dict, years: list[int]) -> dict:
    a = grid["a"]
    k = np.tile(grid["k"].reshape(-1), 1)
    buckets = {"0-14h": (0, 14), "14-38h": (14, 38), "38-72h": (38, 72)}
    card = {"guide": {}, "desk": {}}
    for key, fr in frames.items():
        g = fr["n_groups"]
        kk = np.tile(k, g)
        persist = fr["X"][:, fr["names"].index("da_last_same_hour" if key != "mcpc" else "mcpc_last_same_hour")]
        if key == "price_rt":
            persist = np.concatenate([G["persist"][p][1].reshape(-1) for p in POINTS13])
        for y in years:
            pr = np.tile(np.repeat((a >= year_start(y)) & (a < year_start(y + 1)), H), g) & ~np.isnan(fr["y_abs"])
            if key == "price_da":
                pr &= ~fr["known"]
            row = {}
            for b, (lo, hi) in buckets.items():
                m = pr & (kk > lo) & (kk <= hi)
                if not m.any():
                    continue
                yy = fr["y_abs"][m]
                p10, p50, p90 = (preds[(key, q)][m] for q in QS)
                pm = persist[m]
                row[b] = {"n": int(m.sum()), "pinball_p10": round(float(pinball(yy, p10, 0.1)), 3),
                          "pinball_p50": round(float(pinball(yy, p50, 0.5)), 3),
                          "pinball_p90": round(float(pinball(yy, p90, 0.9)), 3),
                          "coverage_80": round(float(np.mean((yy >= p10) & (yy <= p90))), 4),
                          "mae_p50": round(float(np.nanmean(np.abs(yy - p50))), 3),
                          "mae_persistence": round(float(np.nanmean(np.abs(yy - pm))), 3)}
            card["guide"].setdefault(str(y), {})[key.replace("price_", "")] = row
    for key, fr in desk_frames_.items():
        if key.startswith("_"):
            continue
        y_true = fr["y"] * fr["scale"] if "scale" in fr else fr["y"]
        for y in years:
            m = np.repeat((a >= year_start(y)) & (a < year_start(y + 1)), H) & ~np.isnan(y_true) & \
                ~np.isnan(desk[key])
            if not m.any():
                continue
            err = desk[key][m] - y_true[m]
            row = {"n": int(m.sum()), "mae_mw": round(float(np.mean(np.abs(err))), 1),
                   "nmae": round(float(np.mean(np.abs(err)) / np.mean(np.abs(y_true[m]))), 4),
                   "bias_mw": round(float(np.mean(err)), 1)}
            if not key.startswith("solar"):
                row["mape"] = round(float(np.mean(np.abs(err) / np.maximum(np.abs(y_true[m]), 1))), 4)
            card["desk"].setdefault(str(y), {})[key] = row
    return card


# ---- main ----

def build(args, ctx: dict | None = None, write: bool = True) -> dict:
    t0 = time.time()
    ctx = ctx or base_context(args)
    years = list(range(STORE_FROM, int(args.last_year) + 1))
    rv = Reveal()
    grid = run_grid(ctx)
    wx = weather_at(ctx, grid)
    log("desk features")
    dframes = desk_frames(ctx, grid, wx, rv)
    desk = desk_models(dframes, grid, years, args, rv)
    log(f"desk done at {time.time() - t0:.0f}s; guide features")
    gframes = guide_frames(ctx, grid, wx, desk, rv)
    guide = guide_models(gframes, grid, years, args)
    log(f"guide done at {time.time() - t0:.0f}s; vintages")
    for key in gframes:
        s = np.stack([guide[(key, q)] for q in QS])
        ok = ~np.isnan(s).any(axis=0)
        assert np.all(np.diff(s[:, ok], axis=0) >= 0), f"leakage test 3: {key} quantiles not sorted"
    vins = [v for v in desk_vintages(ctx, grid, wx, desk, guide, years) if v]
    result = {"vintages": vins, "reveal": rv.worst, "grid": grid, "gframes": gframes, "guide": guide,
              "dframes": dframes, "desk": desk, "years": years}
    if not write:
        return result
    vins += [v for v in official_vintages(ctx) if v]
    log(f"{len(vins)} desk/guide/weather/official vintages; ERCOT")
    ev, posts = ercot_vintages(Path(args.cache) / "ercot" / "raw", args.workers)
    vins += [v for v in ev if v]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    if len(posts):
        posts.to_parquet(out / "ercot_postings.parquet", index=False, compression="zstd")
    card = guide_card(grid, gframes, guide, dframes, desk, years)
    runs = ctx["runs"]
    extra = {"inputs": {"hrrr_runs": len(runs), "hrrr_span": [runs.run_id.iloc[0], runs.run_id.iloc[-1]],
                        "hrrr_backfilled": int(runs["backfilled"].sum()),
                        "prices": ctx["prices"]["files"], "eia860m_solar_mw": ctx["e860"],
                        "ercot_postings": len(posts)},
             "guide_years": {str(y): {"fit_on_issued_before": str(pd.Timestamp(dt.datetime(y, 1, 1), tz=CPT)),
                                      "serves": f"HRRR runs issued in {y} (CPT)"} for y in years},
             "guide_target": "residual around the persistence anchor (DA: the last revealed DA day's same hour; RT: "
                             "the revealed DA price of the hour, else that anchor; MCPC: the last revealed day's same "
                             "hour), quantile loss; vintages add the anchor back",
             "monthly_origin": {f"{k}|{y}": "no history before the year (DA MCPC from 2021-01-01): refitted at each "
                                            "month start on rows revealed before it; January has no vintages"
                                for k, y in sorted(MONTHLY_ORIGIN)},
             "train_rows": {"desk": G.get("desk_ntrain"), "guide": G.get("guide_ntrain")},
             "features": {"desk": {k: v["names"] for k, v in dframes.items() if not k.startswith("_")},
                          "guide": {k: v["names"] for k, v in gframes.items()}},
             "leakage": {"reveal_assertion": {"worst_minutes_after_issued_at": rv.worst, "ok": True},
                         "quantiles_sorted": True,
                         "canary": json.loads(Path(args.canary_result).read_text())
                         if args.canary_result and Path(args.canary_result).exists() else None},
             "conventions": {
                 "start": "desk, guide and weather vintages start at the hour after issued_at (cycle + 3 h); "
                          "ERCOT vintages at the posting hour (floor of the posting time)",
                 "weather": "hour [t, t+1) = mean of the run's instants at t and t+1; 45 h (v4) or 33 h (v3 36 h runs)",
                 "solar": "solar/system carries mw and cf (= mw / installed MW of the day) for the site's PV",
                 "load_official": "issued_at = reveal_at = operating day 06:00 CPT; start = its local midnight",
                 "ercot_model": "NP3-565's in-use model per hour is in ercot_postings.parquet (models)"},
             "wall_s": round(time.time() - t0)}
    manifest = write_store(out, vins, extra)
    data = Path(args.data) / "forecast"
    (data / "guide-card.json").write_text(json.dumps(card, indent=1))
    (data / "store-index-sha.txt").write_text(manifest["store_sha"] + "\n")
    log(f"store {manifest['store_sha'][:12]}: {manifest['vintages']} vintages, wall {time.time() - t0:.0f}s")
    return result


def canary(args):
    """Leakage test 1: a reduced build (runs before UNTIL) twice, the second with everything revealed after CUTOFF
    replaced by noise; every vintage issued before CUTOFF must be identical."""
    cut = dt.datetime.fromisoformat(args.canary).replace(tzinfo=dt.UTC)
    cut_min = int((cut.replace(tzinfo=None) - dt.datetime(2018, 7, 1)).total_seconds() // 60)
    a = build(args, write=False)["vintages"]
    ctx = base_context(args)
    noise(ctx, cut_min)
    b = build(args, ctx=ctx, write=False)["vintages"]
    cut_iso = cut.strftime("%Y-%m-%dT%H:%M:%SZ")

    def sel(vs, before=True):
        return {(v["kind"], v["key"], v["run_id"]): v["sha"] for v in vs if (v["issued_at"] < cut_iso) == before}

    sa, sb = sel(a), sel(b)
    diff = [k for k in sa if sa[k] != sb.get(k)]
    late_a, late_b = sel(a, False), sel(b, False)
    changed_after = sum(late_a[k] != late_b.get(k) for k in late_a)
    res = {"cutoff_utc": args.canary, "until": args.until, "years": list(range(STORE_FROM, int(args.last_year) + 1)),
           "vintages_before_cutoff": len(sa), "identical_before_cutoff": len(sa) - len(diff), "differ": diff[:20],
           "vintages_after_cutoff": len(late_a), "changed_after_cutoff": changed_after, "ok": not diff and
           changed_after > 0}
    Path(args.canary_result).write_text(json.dumps(res, indent=1))
    log(f"canary: {res}")
    if not res["ok"]:
        raise SystemExit("leakage test 1 failed")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cache", default=str(ROOT / "cache" / "forecast"))
    ap.add_argument("--out", default=None, help="default CACHE/store")
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--parsed", default=str(ROOT / "cache" / "parsed"))
    ap.add_argument("--eia860m", default=str(ROOT / "cache" / "raw" / "hybrid" / "eia860m" /
                                             "september_generator2026.xlsx"))
    ap.add_argument("--last-year", default="2026")
    ap.add_argument("--until", default=None, help="only HRRR runs before this run id (a reduced build)")
    ap.add_argument("--desk-frac", type=float, default=0.5)
    ap.add_argument("--guide-frac", type=float, default=0.15)
    ap.add_argument("--workers", type=int, default=max(1, min(12, mp.cpu_count() // 4)))
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--canary", default=None, help="run leakage test 1 with this UTC cutoff instead of a build")
    ap.add_argument("--canary-result", default=None)
    args = ap.parse_args()
    args.out = args.out or str(Path(args.cache) / "store")
    args.canary_result = args.canary_result or str(Path(args.cache) / "canary.json")
    os.environ.setdefault("OMP_NUM_THREADS", str(args.threads))
    if args.canary:
        canary(args)
    else:
        build(args)


if __name__ == "__main__":
    main()
