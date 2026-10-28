"""Build the desk packs (docs/CONTRACT-desk.md section 1; docs/desk-data.md): data/desk/<pack>/manifest.json,
tasks.jsonl.gz and series/<task_id>.json.gz, from the ERCOT public API (desk_data_api, cached raw in $DESK_RAW), the
price history (desk_data_history), the v4 forecast store, the notices and NWS VTEC archives, the site registry
(data/desk/sites.parquet), the calibration (data/desk/calibration.json) and the desk price forecast
(data/desk/forecast/)."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DESK = ROOT / "data" / "desk"
HIST = A.RAW / "history"
STORE = Path("/Users/edgar.arakelyan/agentenv-gridsim-plugin/cache/forecast/store")
CPT = ZoneInfo("America/Chicago")
UTC = dt.UTC
RTCB = dt.date(2025, 12, 5)
PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")
AS_NAME = {"REGUP": "regup", "REGDN": "regdn", "RRS": "rrs", "ECRS": "ecrs", "NSPIN": "nspin", "NON-SPIN": "nspin",
           "NSPN": "nspin", "ECRSS": "ecrs", "RRSPFR": "rrs"}

SITES = {
    "S01": {"resource": "CROSSETT_ESR1", "load_zone": "LZ_WEST", "hub": "HB_WEST", "region": "west",
            "card_region": "Far West"},
    "S02": {"resource": "CLO_ESR1", "load_zone": "LZ_HOUSTON", "hub": "HB_HOUSTON", "region": "houston",
            "card_region": "Houston"},
    "S03": {"resource": "WIG_ESS_ESR1", "load_zone": "LZ_NORTH", "hub": "HB_NORTH", "region": "north",
            "card_region": "North"},
    "S04": {"resource": "WFTANK_ESR1", "load_zone": "LZ_SOUTH", "hub": "HB_SOUTH", "region": "south",
            "card_region": "South"},
}
PACKS = {
    "desk-v2-pilot": {"split": "pilot", "layer": "v2",
                      "tasks": [("2026-04-27", "S01"), ("2026-08-17", "S03")]},
    "desk-v2-eval": {"split": "eval", "layer": "v2",
                     "tasks": [(d, s) for d in ("2026-01-25", "2026-02-24", "2026-03-23", "2026-04-24", "2026-05-03",
                                                "2026-06-24", "2026-07-22", "2026-08-23") for s in SITES]},
    "desk-v2-tune": {"split": "train", "layer": "v2",
                     "tasks": [("2026-01-08", "S01"), ("2026-04-15", "S01"), ("2026-07-09", "S01"),
                               ("2026-02-11", "S02"), ("2026-05-20", "S02"), ("2026-08-05", "S02"),
                               ("2026-01-14", "S03"), ("2026-04-02", "S03"), ("2026-06-17", "S03"),
                               ("2026-03-04", "S04"), ("2026-05-27", "S04"), ("2026-08-12", "S04")]},
    "desk-v2-pre": {"split": "train", "layer": "v2",
                    "tasks": [("2025-05-16", "S02"), ("2025-08-20", "S03")]},
}


# ---------------------------------------------------------------- time

def d_(s) -> dt.date:
    return s if isinstance(s, dt.date) else dt.date.fromisoformat(str(s)[:10])


def offset(day: dt.date) -> str:
    o = dt.datetime(day.year, day.month, day.day, 12, tzinfo=CPT).utcoffset()
    h = int(o.total_seconds() // 3600)
    return f"{h:+03d}:00"


def iso(day: dt.date, minute: int) -> str:
    t = dt.datetime(day.year, day.month, day.day) + dt.timedelta(minutes=minute)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + offset(day)


def local_iso(ts: dt.datetime) -> str:
    t = ts.astimezone(CPT)
    return t.strftime("%Y-%m-%dT%H:%M:%S") + t.strftime("%z")[:3] + ":" + t.strftime("%z")[3:]


def parse_local(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s[:19]).replace(tzinfo=CPT)


def dst_free(days: list[dt.date]) -> bool:
    return len({offset(d) for d in days} | {offset(days[0] - dt.timedelta(days=1))}) == 1


def grid5(stamps: list[str], values: list, day: dt.date) -> tuple[list, int]:
    out: list = [None] * 288
    for s, v in sorted(zip(stamps, values, strict=False), key=lambda x: x[0]):
        t = dt.datetime.fromisoformat(s[:19])
        if t.date() != day:
            continue
        out[(t.hour * 60 + t.minute) // 5] = v
    fill = 0
    for k in range(288):
        if out[k] is None:
            if k and out[k - 1] is not None:
                out[k] = out[k - 1]
                fill += 1
    return out, fill


def r2(x):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 3)


# ---------------------------------------------------------------- prices

_hist: dict[str, pd.DataFrame] = {}


def hist(kind: str, point: str) -> pd.DataFrame:
    k = f"{kind}_{point}"
    if k not in _hist:
        p = HIST / f"{k}.parquet"
        if not p.exists():
            import desk_data_history as H
            (H.dam if kind == "dam" else H.rt)(point, "2024-01-01", "2026-08-31").to_parquet(p, index=False)
        _hist[k] = pd.read_parquet(p)
    return _hist[k]


def dam_day(point: str, day: dt.date) -> list:
    h = hist("dam", point)
    x = h[(h["date"] == day.isoformat()) & (~h["dst"])].set_index("he")["price"]
    return [r2(x.get(i)) for i in range(1, 25)]


def rt_day(point: str, day: dt.date) -> list:
    h = hist("rt", point)
    x = h[(h["date"] == day.isoformat()) & (~h["dst"])]
    v = {(int(a) - 1) * 4 + int(b) - 1: p for a, b, p in zip(x["hour"], x["interval"], x["price"], strict=False)}
    return [r2(v.get(i)) for i in range(96)]


def lmp_day(point: str, day: dt.date) -> tuple[list, int]:
    f, r = A.query("np6-788-cd/lmp_node_zone_hub", {"settlementPoint": point, "SCEDTimestampFrom": f"{day}T00:00:00",
                                                    "SCEDTimestampTo": f"{day}T23:59:59"})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["repeatHourFlag"].astype(bool)]
    g, fill = grid5(list(df["SCEDTimestamp"]), [r2(v) for v in df["LMP"]], day)
    return g, fill


def dam_posted(day: dt.date) -> str:
    """The real posting minute of the DAM SPP file for `day` (NP4-190-CD archive postDatetime on D-1), else 13:30."""
    prev = day - dt.timedelta(days=1)
    docs = A.archive_list("np4-190-cd", f"{prev}T00:00:00", f"{prev}T23:59:59")
    if not docs:
        return iso(prev, 13 * 60 + 30)
    return local_iso(parse_local(min(d["postDatetime"] for d in docs)))


def dam_mcpc_day(day: dt.date) -> dict:
    h = pd.read_parquet(HIST / "dam_mcpc.parquet")
    x = h[(h["date"] == day.isoformat()) & (~h["dst"])]
    out = {}
    for prod in PRODUCTS:
        y = x[x["product"].map(lambda s: AS_NAME.get(str(s).upper().replace(" ", ""), "")) == prod] \
            .groupby("he")["mcpc"].first()
        out[prod] = [r2(y.get(i)) for i in range(1, 25)]
    return out


def rt_mcpc_day(day: dt.date) -> tuple[dict, dict]:
    f, r = A.query("np6-332-cd/rt_clear_price_cap_sced", {"SCEDTimestampFrom": f"{day}T00:00:00",
                                                          "SCEDTimestampTo": f"{day}T23:59:59"})
    df = pd.DataFrame(r, columns=f)
    sced = {}
    for prod in PRODUCTS:
        y = df[df["ASType"].map(lambda s: AS_NAME.get(str(s).upper(), "")) == prod]
        sced[prod] = grid5(list(y["SCEDTimestamp"]), [r2(v) for v in y["cappedMCPC"]], day)[0]
    f, r = A.query("np6-331-cd/rt_clear_price_cap", {"deliveryDateFrom": str(day), "deliveryDateTo": str(day)})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["repeatHourFlag"].astype(bool)]
    q = {}
    for prod in PRODUCTS:
        y = df[df["ASType"].map(lambda s: AS_NAME.get(str(s).upper(), "")) == prod]
        v = {(int(a) - 1) * 4 + int(b) - 1: p
             for a, b, p in zip(y["deliveryHour"], y["deliveryInt"], y["MCPC"], strict=False)}
        q[prod] = [r2(v.get(i)) for i in range(96)]
    return sced, q


def asdc_day(day: dt.date) -> tuple[dict, str | None]:
    """DAM/SCED ASDCs for `day` from the NP4-212-CD archive: the latest posting at or before D-1 06:00 (else the first
    posting for the day)."""
    prev = day - dt.timedelta(days=1)
    docs = A.archive_list("np4-212-cd", f"{prev - dt.timedelta(days=1)}T00:00:00", f"{day}T23:59:59")
    paths = A.archive_fetch("np4-212-cd", docs)
    cutoff = f"{prev}T06:00:00"
    found = []
    for doc in sorted(docs, key=lambda d: d["postDatetime"]):
        df = A.read_zip_csv(paths[doc["docId"]])
        df.columns = [re.sub(r"[^a-z]", "", c.lower()) for c in df.columns]
        dd = pd.to_datetime(df["deliverydate"], format="mixed").dt.date
        df = df[dd == day]
        if not df.empty:
            found.append((doc["postDatetime"][:19], df))
    if not found:
        return {}, None
    pick, df = max([f for f in found if f[0] <= cutoff], default=found[0], key=lambda f: f[0])
    if "dstflag" in df:
        df = df[df["dstflag"].astype(str).str.upper().isin(["N", "FALSE", "0"])]
    he = df["hourending"].astype(str).str.split(":").str[0].astype(int)
    out = {}
    for prod in PRODUCTS:
        y = df[df["astype"].map(lambda v: AS_NAME.get(str(v).upper().replace(" ", ""), "")) == prod]
        yh = he[y.index]
        hours = []
        for h in range(1, 25):
            z = y[yh == h].sort_values("demandcurvepoint")
            hours.append(simplify(list(zip(z["quantity"].astype(float), z["price"].astype(float), strict=False))))
        out[prod] = hours
    return out, local_iso(parse_local(pick))


def simplify(pts: list, tol_abs: float = 0.5, tol_rel: float = 0.01) -> list:
    """Vertical-error Douglas-Peucker on a (MW, $) demand curve: max price error max(tol_abs, tol_rel * price)."""
    if len(pts) <= 2:
        return [[r2(a), r2(b)] for a, b in pts]
    x = np.array([p[0] for p in pts], float)
    y = np.array([p[1] for p in pts], float)
    tol = np.maximum(tol_abs, tol_rel * np.abs(y))
    keep = {0, len(pts) - 1}
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        xs, ys = x[i + 1:j], y[i + 1:j]
        yi = np.full_like(xs, y[i]) if x[j] == x[i] else y[i] + (y[j] - y[i]) * (xs - x[i]) / (x[j] - x[i])
        e = np.abs(ys - yi) - tol[i + 1:j]
        k = int(np.argmax(e))
        if e[k] > 0:
            keep.add(i + 1 + k)
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return [[r2(x[k]), r2(y[k])] for k in sorted(keep)]


# ---------------------------------------------------------------- system

def system_day(day: dt.date) -> tuple[dict, dict]:
    f, r = A.query("np6-323-cd/rt_price_adder_sced", {"SCEDTimestampFrom": f"{day}T00:00:00",
                                                      "SCEDTimestampTo": f"{day}T23:59:59"})
    adders = pd.DataFrame(r, columns=f)
    adders = adders[~adders["repeatHourFlag"].astype(bool)]
    st = list(adders["SCEDTimestamp"])
    lam, fill = grid5(st, [r2(v) for v in adders["systemLambda"]], day)
    olhsl = grid5(st, [r2(v) for v in adders["RTOLHSL"]], day)[0]
    f, r = A.query("np6-328-cd/tot_as_res_cap", {"SCEDTimestampFrom": f"{day}T00:00:00",
                                                 "SCEDTimestampTo": f"{day}T23:59:59"})
    cap = pd.DataFrame(r, columns=f)
    cap = cap[~cap["repeatHourFlag"].astype(bool)]
    caps = {c: grid5(list(cap["SCEDTimestamp"]), [r2(v) for v in cap[c]], day)[0]
            for c in ("capREGUP", "capRRS", "capECRS", "capNSPIN", "capREGUPRRS", "capREGUPRRSECRS")}
    load = demand_day(day)
    wind = renew_day("np4-733-cd/wpp_actual_5min_avg_values", day)
    solar = renew_day("np4-738-cd/spp_actual_5min_avg_values", day)
    inputs = {"rtolhsl_mw": olhsl, **{k: v for k, v in caps.items()}}
    prc = prc_proxy(day, inputs, load)
    return {"prc_mw": prc, "prc_kind": "proxy", "lambda": lam, "load_mw": load, "wind_mw": wind,
            "solar_mw": solar}, {"sced_fill_lambda": fill, "prc_inputs": inputs}


def demand_day(day: dt.date) -> list:
    f, r = A.query("np6-345-cd/act_sys_load_by_wzn", {"operatingDayFrom": str(day), "operatingDayTo": str(day)})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["DSTFlag"].astype(bool)]
    v = {int(he.split(":")[0]) - 1: r2(t) for he, t in zip(df["hourEnding"], df["total"], strict=False)}
    return [v.get(k // 12) for k in range(288)]


def renew_day(path: str, day: dt.date) -> list:
    nxt = day + dt.timedelta(days=1)
    f, r = A.query(path, {"intervalEndingFrom": f"{day}T00:05:00", "intervalEndingTo": f"{nxt}T00:00:00"})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["DSTFlag"].astype(bool)].sort_values("postedDatetime").drop_duplicates("intervalEnding", keep="last")
    out: list = [None] * 288
    for ie, g in zip(df["intervalEnding"], df["genSystemWide"], strict=False):
        t = dt.datetime.fromisoformat(ie[:19]) - dt.timedelta(minutes=5)
        if t.date() == day:
            out[(t.hour * 60 + t.minute) // 5] = r2(g)
    return out


_prc_fit: dict | None = None


def prc_proxy(day: dt.date, inputs: dict, load: list) -> list:
    global _prc_fit
    if _prc_fit is None:
        p = DESK / "prc_proxy.json"
        _prc_fit = json.loads(p.read_text())
    f = _prc_fit
    return [None if h is None or ld is None else round(f["a"] + f["b"] * (f["s"] * (h - ld) + f["c"]), 1)
            for h, ld in zip(inputs["rtolhsl_mw"], load, strict=False)]


# ---------------------------------------------------------------- forecasts, outages

_store: pd.DataFrame | None = None
STORE_KIND = {"load": ("ercot_load", "mw", "ERCOT STLF (NP3-565-CD, in-use model)"),
              "wind": ("ercot_wind", "stwpf_mw", "ERCOT STWPF (NP4-742-CD system)"),
              "solar": ("ercot_solar", "stppf_mw", "ERCOT STPPF (NP4-745-CD system)")}


def store_vintages(first: dt.datetime, last: dt.datetime) -> pd.DataFrame:
    global _store
    if _store is None:
        parts = []
        for y in (2025, 2026):
            parts.append(pd.read_parquet(STORE / "vintages" / f"{y}.parquet",
                                         filters=[("kind", "in", ["ercot_load", "ercot_wind", "ercot_solar"]),
                                                  ("key", "=", "system")]))
        _store = pd.concat(parts, ignore_index=True)
        _store["issued"] = pd.to_datetime(_store["issued_at_utc"], utc=True)
    a, b = pd.Timestamp(first), pd.Timestamp(last)
    return _store[(_store["issued"] >= a) & (_store["issued"] <= b)]


def forecasts(days: list[dt.date]) -> list[dict]:
    d0, dl = days[0], days[-1]
    first = dt.datetime(d0.year, d0.month, d0.day, tzinfo=CPT) - dt.timedelta(days=1)
    last = dt.datetime(dl.year, dl.month, dl.day, 23, 59, tzinfo=CPT)
    horizon_end = dt.datetime(dl.year, dl.month, dl.day, tzinfo=CPT) + dt.timedelta(days=2)
    v = store_vintages(first, last)
    out = []
    for kind, (k, field, model) in STORE_KIND.items():
        x = v[(v["kind"] == k) & (v["field"] == field)].sort_values("issued")
        for _, row in x.iterrows():
            start = pd.Timestamp(row["start_utc"]).to_pydatetime()
            n = int(min(len(row["values"]), (horizon_end - start).total_seconds() // 3600))
            out.append({"kind": kind, "issued_at": local_iso(row["issued"].to_pydatetime()),
                        "start": local_iso(start), "step_min": 60,
                        "values": [round(float(z), 1) for z in row["values"][:n]], "model": model, "zone": "system"})
    return out


def outage_capacity(days: list[dt.date]) -> list[dict]:
    d0, dl = days[0], days[-1]
    f, r = A.query("np3-233-cd/hourly_res_outage_cap", {"postedDatetimeFrom": f"{d0 - dt.timedelta(days=1)}T00:00:00",
                                                        "postedDatetimeTo": f"{dl}T23:59:59"})
    df = pd.DataFrame(r, columns=f)
    cols = [c for c in df.columns if c.startswith("totalResourceMWZone") or c.startswith("totalIRRMWZone")]
    df["total"] = df[cols].sum(axis=1)
    out = []
    for posted, g in df.groupby("postedDatetime"):
        g = g.sort_values(["operatingDate", "hourEnding"])
        od, he = g["operatingDate"].iloc[0], int(g["hourEnding"].iloc[0])
        out.append({"issued_at": local_iso(parse_local(posted)), "start": iso(d_(od), (he - 1) * 60),
                    "step_min": 60, "values": [int(v) for v in g["total"]]})
    return sorted(out, key=lambda x: x["issued_at"])


def unit_events(site: dict, days: list[dt.date]) -> list[dict]:
    names = {site["resource"], (site.get("resource_pre") or {}).get("gen")}
    first = days[0] - dt.timedelta(days=1)
    docs = A.archive_list("np1-346-er", f"{first + dt.timedelta(days=2)}T00:00:00",
                          f"{days[-1] + dt.timedelta(days=6)}T00:00:00")
    paths = A.archive_fetch("np1-346-er", docs)
    ev = {}
    for doc in docs:
        z = zipfile.ZipFile(paths[doc["docId"]])
        x = pd.read_excel(io.BytesIO(z.read(z.namelist()[0])), sheet_name="Unplanned Resource Outages", header=4)
        x = x[x["Resource Unit Code"].isin(names)]
        for _, row in x.iterrows():
            start = pd.Timestamp(row["Actual Outage Start"]).to_pydatetime().replace(tzinfo=CPT)
            end = row["Actual End Date"] if pd.notna(row["Actual End Date"]) else row["Planned End Date"]
            end = pd.Timestamp(end).to_pydatetime().replace(tzinfo=CPT)
            lo = dt.datetime(days[0].year, days[0].month, days[0].day, tzinfo=CPT)
            hi = lo + dt.timedelta(days=len(days))
            if end <= lo or start >= hi:
                continue
            avail = float(row["Available MW During Outage"])
            key = (row["Resource Unit Code"], start.isoformat())
            ev[key] = {"kind": "forced_outage" if avail <= 0 else "derate", "start": local_iso(start),
                       "end": local_iso(end), "hsl_mw": avail, "lsl_mw": -avail, "source": "NP1-346-ER",
                       "outage_type": str(row["Outage Type"]), "nature": str(row.get("Nature Of Work", ""))}
    return sorted(ev.values(), key=lambda e: e["start"])


# ---------------------------------------------------------------- notices, NWS

_notices: list | None = None
_nws: list | None = None


def notices(days: list[dt.date]) -> list[dict]:
    global _notices
    if _notices is None:
        _notices = [json.loads(x) for x in gzip.open(ROOT / "data" / "notices" / "notices.jsonl.gz", "rt")]
    lo = dt.datetime.combine(days[0] - dt.timedelta(days=2), dt.time(), CPT)
    hi = dt.datetime.combine(days[-1] + dt.timedelta(days=1), dt.time(), CPT)
    out = []
    for n in _notices:
        if not n.get("issued_at") or n.get("timestamp_quality") != "minute":
            continue
        t = dt.datetime.fromisoformat(n["issued_at"])
        if lo <= t < hi and (n.get("operator_relevant") or n.get("grid_condition")):
            out.append({"event_id": n["notice_id"], "source": n["source"], "kind": n["type"],
                        "level": n.get("level"), "issued_at": local_iso(t), "title": n["title"],
                        "text": (n.get("text") or "")[:1500], "action": n.get("action") or "issue",
                        "channel": n.get("channel")})
    return sorted(out, key=lambda x: x["issued_at"])


def nws(region: str, days: list[dt.date]) -> list[dict]:
    global _nws
    if _nws is None:
        _nws = [json.loads(x) for x in gzip.open(ROOT / "data" / "notices" / "nws_vtec.jsonl.gz", "rt")]
    lo = dt.datetime.combine(days[0] - dt.timedelta(days=2), dt.time(), CPT)
    hi = dt.datetime.combine(days[-1] + dt.timedelta(days=1), dt.time(), CPT)
    out = []
    sev = {"W": "Warning", "A": "Watch", "Y": "Advisory", "S": "Statement"}
    for n in _nws:
        if n["region"] != region:
            continue
        t = dt.datetime.fromisoformat(n["issued_at_utc"].replace("Z", "+00:00"))
        exp = dt.datetime.fromisoformat(n["expires_at_utc"].replace("Z", "+00:00")) if n.get("expires_at_utc") else t
        if t < hi and exp >= lo:
            out.append({"event_id": n["notice_id"], "event": n["name"], "severity": sev.get(n["significance"], ""),
                        "issued_at": local_iso(t), "effective": local_iso(dt.datetime.fromisoformat(
                            n["effective_from_utc"].replace("Z", "+00:00"))) if n.get("effective_from_utc") else None,
                        "expires": local_iso(exp), "area": ", ".join(n.get("counties", [])[:12]),
                        "headline": f"{n['name']} ({n['wfo']}) for {len(n.get('counties', []))} counties"})
    return sorted(out, key=lambda x: x["issued_at"])


# ---------------------------------------------------------------- operator

def curve(row, prefix_mw: str, prefix_p: str, n: int):
    pts = []
    for i in range(1, n + 1):
        m, p = row.get(f"{prefix_mw}{i}"), row.get(f"{prefix_p}{i}")
        if m is None or p is None or (isinstance(m, float) and np.isnan(m)):
            break
        pts.append([r2(m), r2(p)])
    return pts or None


def sced_esr(resource: str, day: dt.date) -> pd.DataFrame:
    f, r = A.query("np3-965-er/60d_sced_esr_data", {"resourceName": resource, "SCEDTimestampFrom": f"{day}T00:00:00",
                                                    "SCEDTimestampTo": f"{day}T23:59:59"})
    df = pd.DataFrame(r, columns=f)
    return df[~df["repeatHourFlag"].astype(bool)].sort_values("SCEDTimestamp") if not df.empty else df


def operator_post(site: dict, day: dt.date) -> tuple[dict, dict, dict]:
    res = site["resource"]
    f, r = A.query("np3-966-er/60d_dam_esr_data", {"resourceName": res, "deliveryDateFrom": str(day),
                                                   "deliveryDateTo": str(day)})
    dam = pd.DataFrame(r, columns=f)
    dam = {int(row["hourEnding"]): row for row in dam.to_dict("records")}
    dam_out = {"curves": [curve(dam[h], "qseSubmittedCurveMW", "qseSubmittedCurvePrice", 10) if h in dam else None
                          for h in range(1, 25)],
               "award_mw": [r2(dam[h]["awardedQuantity"]) if h in dam else None for h in range(1, 25)],
               "spp": [r2(dam[h]["energySettlementPointPrice"]) if h in dam else None for h in range(1, 25)],
               "status": [dam[h]["resourceStatus"] if h in dam else None for h in range(1, 25)],
               "as_award_mw": {p: [r2(dam[h].get(c)) if h in dam else None for h in range(1, 25)] for p, c in
                               (("regup", "REGUPAwarded"), ("regdn", "REGDNAwarded"), ("rrs_pfr", "RRSPFRAwarded"),
                                ("rrs_ffr", "RRSFFRAwarded"), ("ecrs", "ECRSSDAwarded"), ("nspin", "NSPINAwarded"))}}
    sc = sced_esr(res, day)
    sced_out, info = sced_block(sc, day, "SCED1CurveMW", "SCED1CurvePrice", 35)
    cop_out = cop(res, day)
    return {"dam": dam_out, "sced": sced_out, "cop": cop_out}, info, {}


def sced_block(sc: pd.DataFrame, day: dt.date, pm: str, pp: str, n: int) -> tuple[dict, dict]:
    if sc.empty:
        return None, {"sced_rows": 0}
    st = list(sc["SCEDTimestamp"])
    curves, last = [], None
    for row in sc.to_dict("records"):
        c = curve(row, pm, pp, n)
        if c != last:
            curves.append({"t": local_iso(parse_local(row["SCEDTimestamp"])), "points": c})
            last = c
    g = {}
    fills = {}
    for key, col in (("base_point_mw", "basePoint"), ("telemetry_mw", "telemeteredNetOutput"), ("soc_mwh", "SOC"),
                     ("hsl_mw", "HSL"), ("lsl_mw", "LSL"), ("min_soc_mwh", "minSOC"), ("max_soc_mwh", "maxSOC")):
        if col in sc:
            g[key], fills[key] = grid5(st, [r2(v) for v in sc[col]], day)
    g["status"] = grid5(st, list(sc["telemeteredResourceStatus"]), day)[0]
    as_awards = {}
    for p, col in (("regup", "ASAwardsREGUP"), ("regdn", "ASAwardsREGDN"), ("rrs_pfr", "ASAwardsRRSPFR"),
                   ("rrs_ffr", "ASAwardsRRSFFR"), ("ecrs", "ASAwardsECRS"), ("nspin", "ASAwardsNSPIN")):
        if col in sc:
            as_awards[p] = grid5(st, [r2(v) for v in sc[col]], day)[0]
    g["as_award_mw"] = as_awards
    g["curves"] = curves
    return g, {"sced_rows": len(sc), "sced_fill": max(fills.values()) if fills else 0,
               "soc_null": sum(v is None for v in g.get("soc_mwh", [None]))}


def cop(res: str, day: dt.date) -> dict | None:
    try:
        f, r = A.query("np3-991-ex/60_cop_all_updates", {"resourceName": res, "deliveryDateFrom": str(day),
                                                         "deliveryDateTo": str(day)})
    except Exception as e:
        print(f"[build] COP {res} {day}: {type(e).__name__}", flush=True)
        return None
    df = pd.DataFrame(r, columns=f)
    if df.empty:
        return None
    df = df[~df["cancelFlag"].astype(bool)]
    df["he"] = df["hourEnding"].str.split(":").str[0].astype(int)
    out = {k: [] for k in ("hbsoc_mwh", "min_soc_mwh", "max_soc_mwh", "hsl_mw", "lsl_mw", "status", "submitted_at")}
    for he in range(1, 25):
        frz = f"{day}T{he - 2:02d}:00:00" if he >= 2 else f"{day - dt.timedelta(days=1)}T23:00:00"
        x = df[(df["he"] == he) & (df["submitTime"] <= frz)].sort_values("submitTime")
        if x.empty:
            x = df[df["he"] == he].sort_values("submitTime")
        row = x.iloc[-1] if not x.empty else None
        for k, c in (("hbsoc_mwh", "hourBeginningPlannedSOC"), ("min_soc_mwh", "minSOC"), ("max_soc_mwh", "maxSOC"),
                     ("hsl_mw", "highSustainedLimit"), ("lsl_mw", "lowSustainedLimit")):
            out[k].append(None if row is None else r2(row[c]))
        out["status"].append(None if row is None else row["status"])
        out["submitted_at"].append(None if row is None else row["submitTime"])
    return out


def operator_pre(site: dict, day: dt.date) -> tuple[dict, dict]:
    pre = site["resource_pre"]
    f, r = A.query("np3-966-er/60_dam_gen_res_data", {"resourceName": pre["gen"], "deliveryDateFrom": str(day),
                                                      "deliveryDateTo": str(day)})
    gen = {int(x["hourEnding"]): x for x in pd.DataFrame(r, columns=f).to_dict("records")}
    f, r = A.query("np3-966-er/60_dam_energy_bids", {"settlementPointName": site["settlement_point"],
                                                     "deliveryDateFrom": str(day), "deliveryDateTo": str(day)})
    bids = pd.DataFrame(r, columns=f)
    qse = site.get("qse_pre")
    if not bids.empty and "qseName" in bids:
        bids = bids[bids["qseName"] == qse]
    f, r = A.query("np3-966-er/60_dam_energy_bid_awards", {"settlementPointName": site["settlement_point"],
                                                           "deliveryDateFrom": str(day), "deliveryDateTo": str(day)})
    bid_aw = pd.DataFrame(r, columns=f)
    if not bid_aw.empty and "qseName" in bid_aw:
        bid_aw = bid_aw[bid_aw["qseName"] == qse]
    he_col = next((c for c in bids.columns if c.lower().startswith("hourending")), "hourEnding")
    bid_rows = {}
    for x in bids.to_dict("records"):
        bid_rows.setdefault(int(str(x[he_col]).split(":")[0]), []).append(x)
    aw_col = next((c for c in bid_aw.columns if "award" in c.lower() and "mw" in c.lower()), None) \
        or next((c for c in bid_aw.columns if "award" in c.lower()), None)
    he_aw = next((c for c in bid_aw.columns if c.lower().startswith("hourending")), "hourEnding")
    aw = bid_aw.groupby(bid_aw[he_aw].astype(str).str.split(":").str[0].astype(int))[aw_col].sum() \
        if aw_col and not bid_aw.empty else pd.Series(dtype=float)

    def one_bid(row):
        pts = []
        for i in range(1, 11):
            m, p = row.get(f"energyOnlyBidMW{i}"), row.get(f"energyOnlyBidPrice{i}")
            if m is None or p is None or np.isnan(float(m)) or np.isnan(float(p)):
                break
            pts.append((float(m), float(p)))
        return pts

    def bid_curve(rows):
        """The QSE's DAM energy bids at the node for one hour, aggregated: MW wanted at each price (price falling)."""
        bids = [b for b in (one_bid(r) for r in rows or []) if b]
        if not bids:
            return None
        prices = sorted({p for b in bids for _, p in b}, reverse=True)
        out = []
        for p in prices:
            q = sum(max((m for m, bp in b if bp >= p), default=0.0) for b in bids)
            out.append([r2(q), r2(p)])
        return out[:10]

    dam = {"curves": [None] * 24, "award_mw": [None] * 24,
           "spp": [r2(gen[h]["energySettlementPointPrice"]) if h in gen else None for h in range(1, 25)],
           "pre": {"offer": [curve(gen[h], "qseSubmittedCurveMW", "qseSubmittedCurvePrice", 10) if h in gen else None
                             for h in range(1, 25)],
                   "bid": [bid_curve(bid_rows.get(h)) for h in range(1, 25)],
                   "offer_award_mw": [r2(gen[h]["awardedQuantity"]) if h in gen else None for h in range(1, 25)],
                   "bid_award_mw": [r2(abs(aw.get(h, 0.0))) for h in range(1, 25)]}}
    dam["award_mw"] = [None if a is None else round(a - (b or 0.0), 3)
                       for a, b in zip(dam["pre"]["offer_award_mw"], dam["pre"]["bid_award_mw"], strict=False)]
    f, r = A.query("np3-965-er/60_sced_gen_res_data", {"resourceName": pre["gen"],
                                                        "SCEDTimestampFrom": f"{day}T00:00:00",
                                                        "SCEDTimestampTo": f"{day}T23:59:59"})
    g = pd.DataFrame(r, columns=f)
    g = g[~g["repeatHourFlag"].astype(bool)].sort_values("SCEDTimestamp")
    f, r = A.query("np3-965-er/60_load_res_data_in_sced", {"resourceName": pre["load"],
                                                           "SCEDTimestampFrom": f"{day}T00:00:00",
                                                           "SCEDTimestampTo": f"{day}T23:59:59"})
    ld = pd.DataFrame(r, columns=f)
    ld = ld[~ld["repeatHourFlag"].astype(bool)].sort_values("SCEDTimestamp")
    sced, info = sced_block(g, day, "SCED1CurveMW", "SCED1CurvePrice", 35)
    if sced is not None:
        lmap = {row["SCEDTimestamp"]: row for row in ld.to_dict("records")}
        last = None
        bid_curves = []
        for row in ld.to_dict("records"):
            c = curve(row, "SCEDBidCurveMW", "SCEDBidCurvePrice", 10)
            if c != last:
                bid_curves.append({"t": local_iso(parse_local(row["SCEDTimestamp"])), "bid_points": c})
                last = c
        sced["bid_curves"] = bid_curves
        st = list(ld["SCEDTimestamp"])
        lbp = grid5(st, [r2(v) for v in ld["basePoint"]], day)[0]
        ltel = grid5(st, [r2(v) for v in ld["realPowerConsumption"]], day)[0]
        sced["load_base_point_mw"] = lbp
        sced["load_telemetry_mw"] = ltel
        sced["base_point_mw"] = [None if a is None else round(a - (b or 0.0), 3)
                                 for a, b in zip(sced["base_point_mw"], lbp, strict=False)]
        sced["telemetry_mw"] = [None if a is None else round(a - (b or 0.0), 3)
                                for a, b in zip(sced["telemetry_mw"], ltel, strict=False)]
        sced["soc_mwh"] = [None] * 288
        info["load_rows"] = len(lmap)
    return {"dam": dam, "sced": sced, "cop": None}, info


# ---------------------------------------------------------------- site record

def site_record(sid: str, day: dt.date, reg: pd.DataFrame, cal: dict) -> dict:
    s = SITES[sid]
    r = reg.set_index("resource_name").loc[s["resource"]]
    c = cal.get(s["resource"], {})
    hsl, lsl = float(r["power_mw"]), float(min(r["lsl_mw"], r["sced_lsl_mw"]))
    e_max, e_min = round(float(r["max_soc_mwh"]), 2), round(float(r["min_soc_mwh"] or 0.0), 2)
    rec = {"site_id": sid, "resource": s["resource"],
           "resource_pre": {"gen": r["pre_gen_resource"], "load": r["pre_load_resource"]},
           "settlement_point": r["settlement_point"], "load_zone": s["load_zone"], "hub": s["hub"],
           "region": s["region"], "hsl_mw": round(hsl, 2), "lsl_mw": round(lsl, 2), "e_max_mwh": e_max,
           "e_min_mwh": e_min,
           "ramp_mw_per_min": round(min(c["ramp_mw_per_min"], hsl), 2) if c.get("ramp_mw_per_min")
           else round(hsl / 5, 2),
           "rte": c.get("rte", 0.85), "standby_loss_pct_per_h": c.get("standby_loss_pct_per_h", 0.05),
           "calibration": c.get("calibration", {"method": "default (no calibration)"}),
           "deg_usd_per_mwh": 10.0, "warranty_cycles_per_day": 1.5, "soc0_mwh": None, "soc0_source": "default",
           "card": {"name": f"Battery {sid}", "region": s["card_region"],
                    "size": f"{hsl:.0f} MW / {e_max:.0f} MWh"},
           "pv": None, "qse": r["qse"], "qse_pre": r["pre_qse"], "county": r["county"]}
    return rec


def soc0(site: dict, d0: dt.date) -> tuple[float | None, str]:
    if d0 < RTCB:
        return None, "default"
    sc = sced_esr(site["resource"], d0 - dt.timedelta(days=1))
    if sc.empty or sc["SOC"].dropna().empty:
        return None, "default"
    return round(float(sc["SOC"].dropna().iloc[-1]), 3), "disclosed"


# ---------------------------------------------------------------- desk forecast

def desk_forecast(site: dict, days: list[dt.date]) -> list[dict]:
    p = A.RAW / "forecast" / "vintages" / f"{site['settlement_point']}_{days[0]}.json.gz"
    if not p.exists():
        return []
    return json.loads(gzip.decompress(p.read_bytes()))


# ---------------------------------------------------------------- task

def build_task(pack: str, spec: dict, d0: str, sid: str, reg, cal) -> tuple[dict, dict, dict]:
    days = [d_(d0)]
    if not dst_free([days[0] - dt.timedelta(days=7)] + days):
        raise ValueError(f"{d0}: DST transition inside the window")
    era = "rtcb" if days[0] >= RTCB else "pre"
    site = site_record(sid, days[0], reg, cal)
    tid = f"desk-{spec['layer']}-{d0}-{sid}"
    hist_days = [days[0] - dt.timedelta(days=i) for i in range(7, 0, -1)]
    node, hub = site["settlement_point"], site["hub"]
    info = Counter()
    ser = {"schema": "gridsim.desk.series/v1", "task_id": tid, "tz": "America/Chicago", "d0": d0,
           "history_days": [str(d) for d in hist_days]}
    ser["dam_spp"] = {str(d): dam_day(node, d) for d in hist_days + days}
    ser["dam_spp_hub"] = {str(d): dam_day(hub, d) for d in hist_days + days}
    rt_days = [days[0] - dt.timedelta(days=1)] + days
    ser["rt_spp"] = {str(d): rt_day(node, d) for d in rt_days}
    ser["rt_spp_hub"] = {str(d): rt_day(hub, d) for d in rt_days}
    ser["rt_lmp"] = {}
    for d in rt_days:
        ser["rt_lmp"][str(d)], fill = lmp_day(node, d)
        info["sced_fill"] += fill
    ser["dam_mcpc"] = {str(d): dam_mcpc_day(d) for d in hist_days + days}
    posted = {"dam": {}, "asdc": {}}
    if era == "rtcb":
        ser["rt_mcpc"], ser["rt_mcpc_15"], ser["asdc"] = {}, {}, {}
        for d in rt_days:
            ser["rt_mcpc"][str(d)], ser["rt_mcpc_15"][str(d)] = rt_mcpc_day(d)
        for d in days:
            ser["asdc"][str(d)], posted["asdc"][str(d)] = asdc_day(d)
    for d in days:
        posted["dam"][str(d)] = dam_posted(d)
    ser["posted"] = posted
    ser["system"] = {}
    sys_info = {}
    for d in rt_days:
        if era == "rtcb":
            ser["system"][str(d)], sys_info[str(d)] = system_day(d)
        else:
            ser["system"][str(d)], sys_info[str(d)] = system_pre(d)
    ser["forecasts"] = forecasts(days)
    ser["outage_capacity"] = outage_capacity(days)
    ser["desk_forecast"] = desk_forecast(site, days)
    ser["unit_events"] = unit_events(site, days)
    ser["notices"] = notices(days)
    ser["nws"] = nws(site["region"], days)
    ser["deployments"] = []
    op = {"resource": site["resource"] if era == "rtcb" else site["resource_pre"], "qse": site["qse"] if era == "rtcb"
          else site["qse_pre"], "dam": {}, "sced": {}, "cop": {}}
    ok = True
    for d in days:
        if era == "rtcb":
            o, oi, _ = operator_post(site, d)
        else:
            o, oi = operator_pre(site, d)
        op["dam"][str(d)], op["sced"][str(d)], op["cop"][str(d)] = o["dam"], o["sced"], o["cop"]
        for k, v in oi.items():
            info[k] += v
        dam_ok = (era == "pre" and all(a is not None for a in o["dam"]["pre"]["offer_award_mw"])) or \
            (era == "rtcb" and all(st is not None for st in o["dam"]["status"]))
        sced_ok = o["sced"] is not None and oi.get("sced_rows", 0) >= (250 if era == "rtcb" else 90) and \
            (era == "pre" or oi.get("soc_null", 288) == 0)
        ok = ok and dam_ok and sced_ok
    ser["operator"] = op
    site["soc0_mwh"], site["soc0_source"] = soc0(site, days[0])
    if site["soc0_mwh"] is None:
        site["soc0_mwh"] = round((site["e_max_mwh"] + site["e_min_mwh"]) / 2, 2)
    else:
        site["soc0_mwh"] = min(max(site["soc0_mwh"], site["e_min_mwh"]), site["e_max_mwh"])
    for k in ("dam_spp", "rt_spp", "rt_lmp"):
        for d in days:
            if any(v is None for v in ser[k][str(d)]):
                raise ValueError(f"{tid}: null in {k} {d}")
    lmps = [v for d in days for v in ser["rt_lmp"][str(d)]]
    dams = [v for d in days for v in ser["dam_spp"][str(d)]]
    n_not = sum(1 for n in ser["notices"] if n["issued_at"][:10] in {str(d) for d in days}
                or n["issued_at"][:10] == str(days[0] - dt.timedelta(days=1)))
    kind = "outage" if ser["unit_events"] else "scarcity" if max(lmps) >= 500 else \
        "negative" if min(lmps) < 0 and sum(v < 0 for v in lmps) >= 12 else "notice" if n_not >= 3 else "quiet"
    season = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer",
              7: "summer", 8: "summer"}.get(days[0].month, "fall")
    site.pop("qse", None)
    site.pop("qse_pre", None)
    site.pop("county", None)
    s = json.dumps(ser, separators=(",", ":"), allow_nan=False)
    task = {"task_id": tid, "schema": "gridsim.desk.task/v1", "desk_version": "2.0", "pack": pack,
            "split": spec["split"], "layer": spec["layer"], "era": era, "dates": [d0], "site": site,
            "series": f"series/{tid}.json.gz", "series_sha": hashlib.sha256(s.encode()).hexdigest(),
            "operator_ok": bool(ok),
            "tags": {"season": season, "day_kind": kind, "notices": n_not, "max_rt_lmp": max(lmps),
                     "min_rt_lmp": min(lmps), "dam_spread": round(max(dams) - min(dams), 2),
                     "neg_lmp_intervals": sum(v < 0 for v in lmps)}}
    info["unit_events"] = len(ser["unit_events"])
    info["notices"] = len(ser["notices"])
    info["nws"] = len(ser["nws"])
    info["forecast_vintages"] = len(ser["forecasts"])
    info["desk_forecast_vintages"] = len(ser["desk_forecast"])
    return task, s, dict(info)


def system_pre(day: dt.date) -> tuple[dict, dict]:
    p = A.RAW / "history" / f"prc_{day.year}.parquet"
    df = pd.read_parquet(p) if p.exists() else None
    out = {"prc_mw": [None] * 288, "prc_kind": "real", "lambda": [None] * 288}
    if df is not None:
        x = df[df["date"] == str(day)]
        out["prc_mw"] = grid5(list(x["ts"]), [r2(v) for v in x["prc"]], day)[0]
        out["lambda"] = grid5(list(x["ts"]), [r2(v) for v in x["lambda"]], day)[0]
    out["load_mw"] = demand_day(day)
    out["wind_mw"] = renew_day("np4-733-cd/wpp_actual_5min_avg_values", day)
    out["solar_mw"] = renew_day("np4-738-cd/spp_actual_5min_avg_values", day)
    return out, {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("packs", nargs="*", default=list(PACKS))
    ap.add_argument("--only", help="task_id substring")
    a = ap.parse_args()
    reg = pd.read_parquet(DESK / "sites.parquet")
    cal_p = DESK / "calibration.json"
    cal = json.loads(cal_p.read_text())["sites"] if cal_p.exists() else {}
    for pack in a.packs:
        spec = PACKS[pack]
        out = DESK / pack
        (out / "series").mkdir(parents=True, exist_ok=True)
        tasks, infos = [], {}
        for d0, sid in spec["tasks"]:
            tid = f"desk-{spec['layer']}-{d0}-{sid}"
            if a.only and a.only not in tid:
                continue
            task, s, info = build_task(pack, spec, d0, sid, reg, cal)
            (out / "series" / f"{task['task_id']}.json.gz").write_bytes(gzip.compress(s.encode(), mtime=0))
            tasks.append(task)
            infos[task["task_id"]] = info
            print(f"[build] {task['task_id']}: operator_ok={task['operator_ok']} {task['tags']} {info}", flush=True)
        if a.only:
            continue
        with gzip.GzipFile(out / "tasks.jsonl.gz", "wb", mtime=0) as f:
            for t in tasks:
                f.write((json.dumps(t, separators=(",", ":")) + "\n").encode())
        manifest = {"pack": pack, "schema": "gridsim.desk.pack/v1", "split": spec["split"], "layer": spec["layer"],
                    "n_tasks": len(tasks), "sites": sorted({t["site"]["site_id"] for t in tasks}),
                    "dates": sorted({t["dates"][0] for t in tasks}),
                    "operator_ok": sum(t["operator_ok"] for t in tasks),
                    "sced_fill": {k: v.get("sced_fill", 0) for k, v in infos.items()},
                    "coverage": infos, "built_utc": dt.datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "builder": "scripts/desk_data_build.py", "sources": SOURCES}
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))


SOURCES = {"dam_spp": "NP4-190-CD", "rt_spp": "NP6-905-CD", "rt_lmp": "NP6-788-CD", "dam_mcpc": "NP4-188-CD",
           "rt_mcpc": "NP6-332-CD", "rt_mcpc_15": "NP6-331-CD", "asdc": "NP4-212-CD",
           "system.lambda": "NP6-323-CD",
           "system.prc_mw": "post: proxy (docs/desk-data.md) from NP6-323-CD and NP6-345-CD; pre: NP6-792-ER",
           "system.load_mw": "NP6-345-CD (hourly actual system load, repeated on the 5-min grid)",
           "system.wind_mw": "NP4-733-CD", "system.solar_mw": "NP4-738-CD",
           "forecasts": "v4 forecast store (NP3-565-CD, NP4-742-CD, NP4-745-CD system vintages)",
           "outage_capacity": "NP3-233-CD", "unit_events": "NP1-346-ER", "notices": "data/notices/notices.jsonl.gz",
           "nws": "data/notices/nws_vtec.jsonl.gz", "operator.dam": "NP3-966-ER", "operator.sced": "NP3-965-ER",
           "operator.cop": "NP3-991-EX", "desk_forecast": "data/desk/forecast (desk-qr-v1)"}

if __name__ == "__main__":
    main()
