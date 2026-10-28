"""Pull price history for the desk sites (docs/desk-data.md): node and hub DAM SPP (NP4-190-CD) and RT SPP (NP6-905-CD)
from 2024-01-01, and DAM MCPC (NP4-188-CD), through the API query endpoints (cached in $DESK_RAW/query). Writes the
compact per-point parquet files to $DESK_RAW/history/ for the series builder and the desk price forecaster."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402

HIST = A.RAW / "history"


def chunks(first: str, last: str, months: int):
    s = pd.Timestamp(first)
    end = pd.Timestamp(last)
    while s <= end:
        e = min(s + pd.DateOffset(months=months) - pd.Timedelta(days=1), end)
        yield s.date().isoformat(), e.date().isoformat()
        s = e + pd.Timedelta(days=1)


def dam(point: str, first: str, last: str) -> pd.DataFrame:
    out = []
    for a, b in chunks(first, last, 12):
        f, r = A.query("np4-190-cd/dam_stlmnt_pnt_prices",
                       {"settlementPoint": point, "deliveryDateFrom": a, "deliveryDateTo": b})
        out.append(pd.DataFrame(r, columns=f))
    df = pd.concat(out, ignore_index=True)
    df["he"] = df["hourEnding"].str.slice(0, 2).astype(int)
    return df.rename(columns={"deliveryDate": "date", "settlementPointPrice": "price", "DSTFlag": "dst"})[
        ["date", "he", "dst", "price"]].sort_values(["date", "he", "dst"]).reset_index(drop=True)


def rt(point: str, first: str, last: str) -> pd.DataFrame:
    out = []
    for a, b in chunks(first, last, 3):
        f, r = A.query("np6-905-cd/spp_node_zone_hub",
                       {"settlementPoint": point, "deliveryDateFrom": a, "deliveryDateTo": b})
        out.append(pd.DataFrame(r, columns=f))
    df = pd.concat(out, ignore_index=True)
    return df.rename(columns={"deliveryDate": "date", "deliveryHour": "hour", "deliveryInterval": "interval",
                              "settlementPointPrice": "price", "DSTFlag": "dst"})[
        ["date", "hour", "interval", "dst", "price"]].sort_values(["date", "hour", "dst", "interval"]) \
        .reset_index(drop=True)


def mcpc(first: str, last: str) -> pd.DataFrame:
    out = []
    for a, b in chunks(first, last, 12):
        f, r = A.query("np4-188-cd/dam_clear_price_for_cap", {"deliveryDateFrom": a, "deliveryDateTo": b})
        out.append(pd.DataFrame(r, columns=f))
    df = pd.concat(out, ignore_index=True)
    df["he"] = df["hourEnding"].str.slice(0, 2).astype(int)
    return df.rename(columns={"deliveryDate": "date", "ancillaryType": "product", "MCPC": "mcpc", "DSTFlag": "dst"})[
        ["date", "he", "dst", "product", "mcpc"]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("points", nargs="+")
    ap.add_argument("--first", default="2024-01-01")
    ap.add_argument("--last", default="2026-08-31")
    ap.add_argument("--rt", action="store_true")
    ap.add_argument("--mcpc", action="store_true")
    a = ap.parse_args()
    HIST.mkdir(parents=True, exist_ok=True)
    if a.mcpc:
        mcpc(a.first, a.last).to_parquet(HIST / "dam_mcpc.parquet", index=False)
        print("[history] dam_mcpc", flush=True)
    for p in a.points:
        if not (HIST / f"dam_{p}.parquet").exists():
            dam(p, a.first, a.last).to_parquet(HIST / f"dam_{p}.parquet", index=False)
            print(f"[history] dam {p}", flush=True)
        if a.rt and not (HIST / f"rt_{p}.parquet").exists():
            rt(p, a.first, a.last).to_parquet(HIST / f"rt_{p}.parquet", index=False)
            print(f"[history] rt {p}", flush=True)


if __name__ == "__main__":
    main()
