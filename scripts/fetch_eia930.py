"""Fetch EIA-930's six-month BALANCE and SUBREGION CSVs (2018-H2 on) and keep ERCO's rows (docs/CONTRACT-v4.md, data
lane): cache/forecast/eia930/raw/*.csv as downloaded, erco.parquet (hour_end_utc as "YYYY-MM-DDTHH:MM:SSZ", df_mw,
demand_mw, wind_mw, solar_mw, battery_mw, imputed flags) and erco_sub.parquet (hour_end_utc, subregion, demand_mw).
From 2026 the wind and solar columns are split by integrated storage; they are summed. Values are the reported ones;
a missing reported value is filled from EIA's imputed column and flagged."""

from __future__ import annotations

import argparse
import datetime as dt
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.eia.gov/electricity/gridmonitor/sixMonthFiles"
UA = "gridsim-forecast-store/1.0 (research; contact via github.com/earakely-scale)"
BA = "ERCO"


def halves(start: str, end: str) -> list[str]:
    y, h = int(start[:4]), start[5:]
    out = []
    while (y, h) <= (int(end[:4]), end[5:]):
        out.append(f"{y}_{'Jan_Jun' if h == 'H1' else 'Jul_Dec'}")
        y, h = (y, "H2") if h == "H1" else (y + 1, "H1")
    return out


def fetch(name: str, raw: Path) -> Path | None:
    path = raw / name
    if path.exists():
        return path
    for attempt in range(5):
        try:
            req = urllib.request.Request(f"{BASE}/{name}", headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=300) as r:
                body = r.read()
            path.write_bytes(body)
            print(f"[eia930] {name}: {len(body) / 1e6:.1f} MB", flush=True)
            return path
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"[eia930] {name}: not published", flush=True)
                return None
        except OSError:
            pass
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(name)


def utc(s: pd.Series) -> pd.Series:
    return pd.to_datetime(s, format="%m/%d/%Y %I:%M:%S %p", utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def num(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df:
        return pd.Series(np.nan, index=df.index)
    return pd.to_numeric(df[col].astype(str).str.replace(",", "", regex=False), errors="coerce")


def sum_cols(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    have = [c for c in cols if c in df]
    if not have:
        return pd.Series(np.nan, index=df.index)
    vals = pd.concat([num(df, c) for c in have], axis=1)
    return vals.sum(axis=1, min_count=1)


def filled(df: pd.DataFrame, reported: list[str], imputed: list[str]) -> tuple[pd.Series, pd.Series]:
    r, i = sum_cols(df, reported), sum_cols(df, imputed)
    flag = r.isna() & i.notna()
    return r.where(~flag, i), flag


def balance(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = df[df["Balancing Authority"] == BA]
    wind = ["Net Generation (MW) from Wind", "Net Generation (MW) from Wind without Integrated Battery Storage",
            "Net Generation (MW) from Wind with Integrated Battery Storage"]
    solar = ["Net Generation (MW) from Solar", "Net Generation (MW) from Solar without Integrated Battery Storage",
             "Net Generation (MW) from Solar with Integrated Battery Storage"]
    out = pd.DataFrame({"hour_end_utc": utc(df["UTC Time at End of Hour"])})
    out["df_mw"] = num(df, "Demand Forecast (MW)")
    out["demand_mw"], out["demand_imputed"] = filled(df, ["Demand (MW)"], ["Demand (MW) (Imputed)"])
    out["wind_mw"], out["wind_imputed"] = filled(df, wind, [f"{c} (Imputed)" for c in wind])
    out["solar_mw"], out["solar_imputed"] = filled(df, solar, [f"{c} (Imputed)" for c in solar])
    out["battery_mw"] = num(df, "Net Generation (MW) from Battery Storage")
    out["source_file"] = path.name
    return out


def subregion(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = df[df["Balancing Authority"] == BA]
    return pd.DataFrame({"hour_end_utc": utc(df["UTC Time at End of Hour"]), "subregion": df["Sub-Region"].values,
                         "demand_mw": num(df, "Demand (MW)").values, "source_file": path.name})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--start", default="2018-H2")
    ap.add_argument("--end", default=f"{dt.date.today().year}-{'H1' if dt.date.today().month <= 6 else 'H2'}")
    ap.add_argument("--out", default=str(ROOT / "cache" / "forecast" / "eia930"))
    args = ap.parse_args()
    out = Path(args.out)
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    bal, sub = [], []
    for h in halves(args.start, args.end):
        if p := fetch(f"EIA930_BALANCE_{h}.csv", raw):
            bal.append(balance(p))
        if p := fetch(f"EIA930_SUBREGION_{h}.csv", raw):
            sub.append(subregion(p))
    b = pd.concat(bal).drop_duplicates("hour_end_utc", keep="last").sort_values("hour_end_utc")
    s = pd.concat(sub).drop_duplicates(["hour_end_utc", "subregion"], keep="last").sort_values(
        ["hour_end_utc", "subregion"])
    b.to_parquet(out / "erco.parquet", index=False)
    s.to_parquet(out / "erco_sub.parquet", index=False)
    print(f"[eia930] erco {len(b)} hours {b.hour_end_utc.min()}..{b.hour_end_utc.max()}; "
          f"sub {len(s)} rows, {sorted(s.subregion.unique())}", flush=True)
    for col in ("df_mw", "demand_mw", "wind_mw", "solar_mw", "battery_mw"):
        print(f"[eia930] {col} non-null {b[col].notna().mean():.4f}", flush=True)


if __name__ == "__main__":
    main()
