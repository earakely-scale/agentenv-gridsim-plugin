"""Calibrate each desk site's round-trip efficiency and standby loss from its disclosed SCED SoC against telemetered
output (NP3-965-ER 60d_ESR_Data_in_SCED), docs/desk-data.md "Calibration". Writes data/desk/calibration.json and
data/desk/calibration.md (the fit report).

Per hour block b with the battery ON and SCED gaps under 10 min: dSoC_b = a*C_b - k*D_b - l*Sbar_b*T_b, where C_b and
D_b are charged and discharged AC MWh (telemetered net output, left Riemann over SCED runs), Sbar_b the mean SoC and T_b
the block length in hours. eta_c = a, eta_d = 1/k, RTE = a/k, standby = 100*l %/h. Huber-weighted least squares; 90% CIs
from a day-block bootstrap."""

from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402
from desk_data_build import SITES  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "data" / "desk"
WINDOWS = [("2026-02-03", "2026-03-02"), ("2026-06-01", "2026-06-28")]
COLS = ["SCEDTimestamp", "repeatHourFlag", "telemeteredResourceStatus", "telemeteredNetOutput", "SOC", "minSOC",
        "maxSOC", "HSL", "LSL", "rampRateUp", "rampRateDown"]


def pull(resource: str) -> pd.DataFrame:
    out = []
    for a, b in WINDOWS:
        s = dt.date.fromisoformat(a)
        e = dt.date.fromisoformat(b)
        while s <= e:
            t = min(s + dt.timedelta(days=6), e)
            f, r = A.query("np3-965-er/60d_sced_esr_data", {"resourceName": resource,
                                                            "SCEDTimestampFrom": f"{s}T00:00:00",
                                                            "SCEDTimestampTo": f"{t}T23:59:59"})
            out.append(pd.DataFrame(r, columns=f)[COLS])
            s = t + dt.timedelta(days=1)
    df = pd.concat(out, ignore_index=True)
    df["t"] = pd.to_datetime(df["SCEDTimestamp"])
    return df.sort_values(["t", "repeatHourFlag"]).drop_duplicates("SCEDTimestamp").reset_index(drop=True)


def blocks(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["SOC", "telemeteredNetOutput"]).copy()
    df["dt_h"] = (df["t"].shift(-1) - df["t"]).dt.total_seconds() / 3600
    df["dsoc"] = df["SOC"].shift(-1) - df["SOC"]
    df["on"] = df["telemeteredResourceStatus"].isin(["ON", "ONTEST", "ONEMR", "ONREG", "ONOS"])
    df = df.iloc[:-1]
    df = df[(df["dt_h"] > 0) & (df["dt_h"] <= 10 / 60)]
    p = df["telemeteredNetOutput"]
    df["c"] = (-p).clip(lower=0) * df["dt_h"]
    df["d"] = p.clip(lower=0) * df["dt_h"]
    df["s_dt"] = df["SOC"] * df["dt_h"]
    df["hour"] = df["t"].dt.floor("h")
    g = df.groupby("hour")
    b = pd.DataFrame({"dsoc": g["dsoc"].sum(), "c": g["c"].sum(), "d": g["d"].sum(), "s_dt": g["s_dt"].sum(),
                      "T": g["dt_h"].sum(), "on": g["on"].all(), "n": g.size()})
    b = b[(b["on"]) & (b["T"] >= 0.75)]
    b["day"] = b.index.date
    return b


def fit(b: pd.DataFrame) -> np.ndarray:
    X = np.column_stack([b["c"], -b["d"], -b["s_dt"]])
    y = b["dsoc"].to_numpy()
    w = np.ones(len(y))
    for _ in range(20):
        sw = np.sqrt(w)
        beta, *_ = np.linalg.lstsq(X * sw[:, None], y * sw, rcond=None)
        r = y - X @ beta
        s = 1.4826 * np.median(np.abs(r - np.median(r))) or 1e-6
        k = 1.345 * s
        w = np.where(np.abs(r) <= k, 1.0, k / np.abs(r))
    return beta


def calibrate(resource: str) -> dict:
    raw = pull(resource)
    b = blocks(raw)
    beta = fit(b)
    days = np.array(sorted(set(b["day"])))
    rng = np.random.default_rng(7)
    boots = []
    for _ in range(300):
        pick = rng.choice(days, len(days))
        bb = pd.concat([b[b["day"] == d] for d in pick])
        boots.append(fit(bb))
    boots = np.array(boots)
    a, k, l_ = beta
    rte = a / k
    rte_b = boots[:, 0] / boots[:, 1]
    resid = b["dsoc"].to_numpy() - np.column_stack([b["c"], -b["d"], -b["s_dt"]]) @ beta
    ramp = pd.to_numeric(raw["rampRateUp"], errors="coerce").dropna()
    rte_c = float(np.clip(rte, 0.70, 0.98))
    stby = float(np.clip(100 * l_, 0.0, 1.0))
    return {
        "rte": round(rte_c, 4), "standby_loss_pct_per_h": round(stby, 4),
        "ramp_mw_per_min": round(float(ramp.median()), 2) if len(ramp) else None,
        "calibration": {
            "source": "NP3-965-ER 60d_ESR_Data_in_SCED", "window": [WINDOWS[0][0], WINDOWS[-1][1]],
            "windows": WINDOWS, "n_intervals": int(b["n"].sum()), "n_hours": int(len(b)), "n_days": int(len(days)),
            "eta_c": round(float(a), 4), "eta_d": round(float(1 / k), 4), "rte_raw": round(float(rte), 4),
            "standby_raw_pct_per_h": round(float(100 * l_), 4),
            "rte_ci": [round(float(np.percentile(rte_b, 5)), 4), round(float(np.percentile(rte_b, 95)), 4)],
            "standby_ci": [round(float(np.percentile(100 * boots[:, 2], 5)), 4),
                           round(float(np.percentile(100 * boots[:, 2], 95)), 4)],
            "resid_mwh_mad": round(float(np.median(np.abs(resid))), 3),
            "r2": round(float(1 - np.var(resid) / np.var(b["dsoc"])), 4),
            "throughput_mwh": {"charged": round(float(b["c"].sum()), 1), "discharged": round(float(b["d"].sum()), 1)},
            "clipped": bool(rte_c != rte or stby != 100 * l_),
            "method": "hourly SoC balance, Huber LS, day-block bootstrap (300), RTE clipped to [0.70, 0.98], "
                      "standby to [0, 1] %/h"}}


def main():
    out = {}
    lines = ["# Desk site calibration (generated by scripts/desk_data_calibrate.py)", "",
             "| site | resource | RTE | 90% CI | eta_c | eta_d | standby %/h | 90% CI | R^2 | hours | ramp MW/min |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for sid, s in SITES.items():
        c = calibrate(s["resource"])
        out[s["resource"]] = c
        k = c["calibration"]
        lines.append(f"| {sid} | {s['resource']} | {c['rte']:.3f} | {k['rte_ci'][0]:.3f}–{k['rte_ci'][1]:.3f} | "
                     f"{k['eta_c']:.3f} | {k['eta_d']:.3f} | {c['standby_loss_pct_per_h']:.3f} | "
                     f"{k['standby_ci'][0]:.3f}–{k['standby_ci'][1]:.3f} | {k['r2']:.3f} | {k['n_hours']} | "
                     f"{c['ramp_mw_per_min']} |")
        print(lines[-1], flush=True)
    DESK.mkdir(parents=True, exist_ok=True)
    (DESK / "calibration.json").write_text(json.dumps({"schema": "gridsim.desk.calibration/v1", "sites": out},
                                                      indent=1))
    (DESK / "calibration.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
