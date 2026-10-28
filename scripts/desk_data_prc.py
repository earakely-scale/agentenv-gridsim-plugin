"""Fit the post-RTC+B PRC proxy (design D12; docs/desk-data.md "PRC proxy") on real pre-RTC+B PRC, and validate it.

Pre-RTC+B, NP6-792-ER (RTM_ORDC_REL_DPLY_PRC_ADDR_RSRV_2025) posts PRC with RTOLHSL per SCED. Post-RTC+B, NP6-323-CD
still posts RTOLHSL but not PRC or RTBP. The proxy reads only fields public in both eras:
    headroom = RTOLHSL - actual system load (NP6-345-CD, hourly, aligned to the SCED run's hour)
    PRC_proxy = a + b * headroom, with b fitted on 2025-01-01..2025-08-31, validated on 2025-09-01..2025-12-04.
Writes data/desk/prc_proxy.json (coefficients, validation metrics, era check) and the parsed pre-RTC+B PRC per year at
$DESK_RAW/history/prc_2025.parquet for pre-RTC+B tasks (prc_kind "real")."""

from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "data" / "desk"
HIST = A.RAW / "history"


def sheets(path: Path) -> pd.DataFrame:
    z = zipfile.ZipFile(path)
    x = pd.read_excel(io.BytesIO(z.read(z.namelist()[0])), sheet_name=None, header=None)
    frames = []
    for v in x.values():
        m = v.apply(lambda r: r.astype(str).str.contains("SCED Time").any(), axis=1)
        if not m.any():
            continue
        hdr = m[m].index[0]
        df = v.iloc[hdr + 1:].copy()
        df.columns = [str(c).strip() for c in v.iloc[hdr]]
        df = df.loc[:, [c != "nan" for c in df.columns]]
        df = df.loc[:, ~df.columns.duplicated()]
        frames.append(df.dropna(subset=["SCED Timestamp"]))
    df = pd.concat(frames, ignore_index=True)
    df["ts"] = pd.to_datetime(df["SCED Timestamp"], errors="coerce", format="mixed")
    df = df.dropna(subset=["ts"])
    return df


def pre_prc() -> pd.DataFrame:
    docs = A.archive_list("np6-792-er", "2025-01-01T00:00:00", "2026-10-01T00:00:00")
    doc = max((d for d in docs if d["friendlyName"] == "RTM_ORDC_REL_DPLY_PRC_ADDR_RSRV_2025"),
              key=lambda d: d["postDatetime"])
    df = sheets(A.archive_fetch("np6-792-er", [doc])[doc["docId"]])
    df = df[df["Repeated Hour Flag"].astype(str).str.upper() != "Y"]
    out = pd.DataFrame({"ts": df["ts"], "prc": pd.to_numeric(df["PRC"]), "lambda": pd.to_numeric(df["System Lamda"]),
                        "rtolhsl": pd.to_numeric(df["RTOLHSL"]), "rtbp": pd.to_numeric(df["RTBP"]),
                        "rtolcap": pd.to_numeric(df["RTOLCAP"])})
    out["date"] = out["ts"].dt.date.astype(str)
    return out.sort_values("ts").reset_index(drop=True)


def post_adders() -> pd.DataFrame:
    docs = A.archive_list("np6-792-er", "2025-01-01T00:00:00", "2026-10-01T00:00:00")
    frames = []
    for name in ("HIST_RT_SCED_PRC_ADDR_2025", "HIST_RT_SCED_PRC_ADDR_2026"):
        doc = max((d for d in docs if d["friendlyName"] == name), key=lambda d: d["postDatetime"])
        df = sheets(A.archive_fetch("np6-792-er", [doc])[doc["docId"]])
        df = df[df["Repeated Hour Flag"].astype(str).str.upper() != "Y"]
        frames.append(pd.DataFrame({"ts": df["ts"], "rtolhsl": pd.to_numeric(df["RTOLHSL"]),
                                    "lambda": pd.to_numeric(df["System Lamda"])}))
    return pd.concat(frames, ignore_index=True).sort_values("ts").reset_index(drop=True)


def demand(first: str, last: str) -> pd.DataFrame:
    f, r = A.query("np6-345-cd/act_sys_load_by_wzn", {"operatingDayFrom": first, "operatingDayTo": last})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["DSTFlag"].astype(bool)]
    he = df["hourEnding"].str.split(":").str[0].astype(int)
    df["start"] = pd.to_datetime(df["operatingDay"]) + pd.to_timedelta(he - 1, unit="h")
    return df.rename(columns={"total": "demand"})[["start", "demand"]].sort_values("start")


def align(x: pd.DataFrame, d: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    x["start"] = x["ts"].dt.floor("h")
    return x.merge(d, on="start", how="inner")


def main():
    pre = pre_prc()
    HIST.mkdir(parents=True, exist_ok=True)
    pre[["date", "ts", "prc", "lambda"]].assign(ts=pre["ts"].dt.strftime("%Y-%m-%dT%H:%M:%S")) \
        .to_parquet(HIST / "prc_2025.parquet", index=False)
    d = demand("2025-01-01", "2026-08-31")
    p = align(pre, d)
    p["head"] = p["rtolhsl"] - p["demand"]
    train = p[p["ts"] < "2025-09-01"]
    test = p[(p["ts"] >= "2025-09-01") & (p["ts"] < "2025-12-05")]
    b, a = np.polyfit(train["head"], train["prc"], 1)
    pred = a + b * test["head"]
    err = pred - test["prc"]
    post = align(post_adders(), d)
    post["head"] = post["rtolhsl"] - post["demand"]
    last_pre = p[p["ts"] >= "2025-11-20"]["head"]
    first_post = post[(post["ts"] >= "2025-12-05") & (post["ts"] < "2025-12-20")]["head"]
    ratio = float(first_post.median() / last_pre.median())
    scale = 1.0
    if abs(ratio - 1) > 0.15:
        pre_q = np.nanquantile(p[p["ts"] >= "2025-10-01"]["head"], [0.1, 0.5, 0.9])
        post_q = np.nanquantile(post[post["ts"] < "2026-02-01"]["head"], [0.1, 0.5, 0.9])
        scale = float((pre_q[2] - pre_q[0]) / (post_q[2] - post_q[0]))
        shift = float(pre_q[1] - scale * post_q[1])
    else:
        shift = 0.0
    fit = {"schema": "gridsim.desk.prc-proxy/v1", "label": "modelled",
           "formula": "prc_proxy = a + b * (s * (RTOLHSL - demand) + c)",
           "feature": "headroom", "a": round(float(a), 3), "b": round(float(b), 5), "s": round(scale, 5),
           "c": round(shift, 2),
           "inputs": {"RTOLHSL": "NP6-323-CD (post) / NP6-792-ER (pre)", "demand": "NP6-345-CD hourly total"},
           "train": ["2025-01-01", "2025-08-31"], "test": ["2025-09-01", "2025-12-04"],
           "test_metrics": {"n": int(len(test)), "mae_mw": round(float(err.abs().mean()), 1),
                            "rmse_mw": round(float(np.sqrt((err ** 2).mean())), 1),
                            "bias_mw": round(float(err.mean()), 1),
                            "corr": round(float(np.corrcoef(pred, test["prc"])[0, 1]), 4),
                            "mae_prc_below_7000_mw": round(float(err[test["prc"] < 7000].abs().mean()), 1),
                            "prc_test_range": [round(float(test["prc"].min()), 0), round(float(test["prc"].max()), 0)]},
           "era_check": {"headroom_median_pre_2025-11-20_12-04": round(float(last_pre.median()), 1),
                         "headroom_median_post_2025-12-05_12-19": round(float(first_post.median()), 1),
                         "ratio": round(ratio, 4),
                         "note": "median headroom doubles across RTC+B go-live (RTOLHSL definition changed with "
                                 "the single ESR model; ERCOT does not document the change); when "
                                 "the median ratio is off by > 15%, post headroom is rescaled by quantile matching "
                                 "(s, c) to the last pre-RTC+B quarter"}}
    (DESK / "prc_proxy.json").write_text(json.dumps(fit, indent=1))
    print(json.dumps(fit, indent=1))


if __name__ == "__main__":
    main()
