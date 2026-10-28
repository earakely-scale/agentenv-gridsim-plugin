"""Build data/desk/sites.parquet, the ERCOT ESR site registry (docs/desk-data.md, "Site registry").

Post-RTC+B: 60-Day DAM ESR Data (NP3-966-ER, HE1 of every day from 2025-12-05) gives resource, QSE, DME, settlement
point, HSL/LSL and status; 60-Day ESR Data in SCED (NP3-965-ER, one SCED snapshot per month at 12:00) gives MinSOC
and MaxSOC. Pre-RTC+B: 60-Day DAM Generation Resource Data (type PWRSTR, API from 2023-12-11) through ERCOT's
combo-to-single-model crosswalk. CDR Dec 2025 "Unit Details" adds county, CDR zone, in-service date and installed MW;
its "Wind-Solar Region Mapping" adds the CDR wind/solar regions."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "desk"
WEB = A.RAW / "web"
RTCB = dt.date(2025, 12, 5)
LAST_DISCLOSED = dt.date(2026, 8, 28)


def frame(fields, rows):
    return pd.DataFrame(rows, columns=fields)


def dam_esr() -> pd.DataFrame:
    return frame(*A.query("np3-966-er/60d_dam_esr_data", {"hourEndingFrom": 1, "hourEndingTo": 1}))


def dam_pwrstr() -> pd.DataFrame:
    return frame(*A.query("np3-966-er/60_dam_gen_res_data",
                          {"resourceType": "PWRSTR", "hourEndingFrom": 1, "hourEndingTo": 1}))


def sced_snapshots() -> pd.DataFrame:
    out = []
    d = dt.date(2025, 12, 15)
    while d <= LAST_DISCLOSED:
        for hh in ("03", "12", "19"):
            f, r = A.query("np3-965-er/60d_sced_esr_data", {
                "SCEDTimestampFrom": f"{d}T{hh}:00:00", "SCEDTimestampTo": f"{d}T{hh}:04:59"})
            out.append(frame(f, r))
        d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=15)
    df = pd.concat(out, ignore_index=True)
    return df[["SCEDTimestamp", "resourceName", "qseName", "HSL", "LSL", "SOC", "minSOC", "maxSOC",
               "telemeteredResourceStatus"]]


def crosswalk() -> pd.DataFrame:
    x = pd.read_excel(WEB / "single-model-esr-names.xlsx", "Combo & Single Model ESR Names", header=None, skiprows=2)
    x = x.iloc[:, 1:7]
    x.columns = ["substation", "gen_unit", "pre_load_resource", "esr_unit", "resource_name", "updated"]
    x = x.dropna(subset=["resource_name"])
    x["pre_gen_resource"] = x["substation"].astype(str) + "_" + x["gen_unit"].astype(str)
    return x[["resource_name", "pre_gen_resource", "pre_load_resource"]]


def cdr() -> tuple[pd.DataFrame, dict, dict]:
    d = pd.read_excel(WEB / "CDR_Dec2025.xlsx", "Unit Details", header=2)
    d = d[d["FUEL"] == "STORAGE"].rename(columns={
        "UNIT NAME": "cdr_name", "UNIT CODE": "cdr_unit_code", "COUNTY": "county", "ZONE": "cdr_zone",
        "IN-SERVICE\nDATE": "in_service_date", "INSTALLED CAPACITY\n(MW)": "installed_mw", "CDR STATUS": "cdr_status"})
    d = d[["cdr_name", "cdr_unit_code", "county", "cdr_zone", "in_service_date", "installed_mw", "cdr_status"]]
    d = d.drop_duplicates("cdr_unit_code")
    m = pd.read_excel(WEB / "CDR_Dec2025.xlsx", "Wind-Solar Region Mapping", header=3)
    wind = dict(zip(m.iloc[:, 0].astype(str).str.upper(), m.iloc[:, 1], strict=False))
    solar = dict(zip(m.iloc[:, 3].astype(str).str.upper(), m.iloc[:, 4], strict=False))
    return d, wind, solar


def build() -> pd.DataFrame:
    post = dam_esr()
    post["deliveryDate"] = pd.to_datetime(post["deliveryDate"]).dt.date
    post = post.sort_values("deliveryDate")
    last = post.groupby("resourceName").tail(1).set_index("resourceName")
    g = post.groupby("resourceName")
    reg = pd.DataFrame({
        "resource_name": last.index,
        "settlement_point": last["settlementPointName"].values,
        "qse": last["qseName"].values,
        "dme": last["dmeName"].values,
        "first_seen_post": g["deliveryDate"].min().reindex(last.index).values,
        "last_seen_post": g["deliveryDate"].max().reindex(last.index).values,
        "days_post": g["deliveryDate"].nunique().reindex(last.index).values,
        "days_on_post": post[post["resourceStatus"] == "ON"].groupby("resourceName")["deliveryDate"].nunique()
        .reindex(last.index).fillna(0).astype(int).values,
        "hsl_mw": g["HSL"].max().reindex(last.index).values,
        "lsl_mw": g["LSL"].min().reindex(last.index).values,
        "n_qse": g["qseName"].nunique().reindex(last.index).values,
        "n_settlement_points": g["settlementPointName"].nunique().reindex(last.index).values,
    })
    sc = sced_snapshots()
    sg = sc.groupby("resourceName")
    soc = pd.DataFrame({"max_soc_mwh": sg["maxSOC"].max(), "min_soc_mwh": sg["minSOC"].min(),
                        "max_soc_median_mwh": sg["maxSOC"].median(), "sced_hsl_mw": sg["HSL"].max(),
                        "sced_lsl_mw": sg["LSL"].min(), "sced_snapshots": sg.size(),
                        "soc_reported_share": sg["SOC"].apply(lambda s: float(s.notna().mean()))})
    reg = reg.merge(soc, left_on="resource_name", right_index=True, how="left")
    reg["power_mw"] = reg[["hsl_mw", "sced_hsl_mw"]].max(axis=1)
    reg["duration_h"] = (reg["max_soc_mwh"] - reg["min_soc_mwh"].fillna(0)) / reg["power_mw"].replace(0, np.nan)
    reg = reg.merge(crosswalk(), on="resource_name", how="left")
    pre = dam_pwrstr()
    pre["deliveryDate"] = pd.to_datetime(pre["deliveryDate"]).dt.date
    pre = pre[pre["deliveryDate"] < RTCB]
    pg = pre.groupby("resourceName")
    pre_info = pd.DataFrame({"first_seen_pre": pg["deliveryDate"].min(), "last_seen_pre": pg["deliveryDate"].max(),
                             "pre_settlement_point": pg["settlementPointName"].last(), "pre_qse": pg["qseName"].last(),
                             "pre_hsl_mw": pg["HSL"].max()})
    reg = reg.merge(pre_info, left_on="pre_gen_resource", right_index=True, how="left")
    c, wind, solar = cdr()
    reg = reg.merge(c, left_on="pre_gen_resource", right_on="cdr_unit_code", how="left")
    reg["cdr_wind_region"] = reg["county"].astype(str).str.upper().map(wind)
    reg["cdr_solar_region"] = reg["county"].astype(str).str.upper().map(solar)
    reg["in_service_date"] = pd.to_datetime(reg["in_service_date"], errors="coerce").dt.date
    seen = reg[["first_seen_pre", "first_seen_post"]].min(axis=1)
    api_floor = dt.date(2024, 1, 19)
    use_cdr = reg["in_service_date"].notna() & ((seen <= api_floor) | (reg["in_service_date"] < seen))
    reg["first_operating_date"] = np.where(use_cdr, reg["in_service_date"], seen)
    reg["first_operating_date_source"] = np.where(
        use_cdr, "cdr_in_service_date", np.where(reg["first_seen_pre"].notna(), "first_dam_pwrstr_row",
                                                 "first_dam_esr_row"))
    for col in ("first_seen_post", "last_seen_post", "first_seen_pre", "last_seen_pre", "first_operating_date",
                "in_service_date"):
        reg[col] = reg[col].astype(str).replace({"NaT": None, "nan": None, "None": None})
    return reg.sort_values("resource_name").reset_index(drop=True)


def main():
    reg = build()
    OUT.mkdir(parents=True, exist_ok=True)
    reg.to_parquet(OUT / "sites.parquet", index=False)
    print(f"[sites] {len(reg)} ESRs; with MaxSOC {reg['max_soc_mwh'].notna().sum()}; with pre-RTC+B mapping "
          f"{reg['first_seen_pre'].notna().sum()}; with CDR county {reg['county'].notna().sum()}")


if __name__ == "__main__":
    main()
