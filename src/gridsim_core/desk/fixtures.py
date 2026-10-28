"""Synthetic desk fixtures in the pack shape (contract section 1), so tests and smoke runs never need a real pack.
Every number here is invented; nothing is ERCOT data."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from gridsim_core.desk import clock
from gridsim_core.desk.data import build, era_of, series_sha
from gridsim_core.desk.engine import Engine, site_of

SITE = {"site_id": "S00", "resource": "FIXTURE_ESR1", "resource_pre": {"gen": "FIXTURE_BES1", "load": "FIXTURE_LD1"},
        "settlement_point": "FIXTURE_RN", "load_zone": "LZ_SOUTH", "hub": "HB_SOUTH", "region": "south",
        "hsl_mw": 100.0, "lsl_mw": -100.0, "e_max_mwh": 200.0, "e_min_mwh": 10.0, "ramp_mw_per_min": 20.0,
        "rte": 0.86, "standby_loss_pct_per_h": 0.05,
        "calibration": {"source": "fixture", "method": "invented"},
        "deg_usd_per_mwh": 10.0, "warranty_cycles_per_day": 1.5, "soc0_mwh": 80.0, "soc0_source": "default",
        "card": {"name": "Battery S00", "region": "South", "size": "100 MW / 200 MWh"}, "pv": None}


def _iso(minute: float, d0: str) -> str:
    return clock.to_iso(minute, d0)


def _dam_shape(rng, scale: float = 1.0) -> list[float]:
    base = []
    for h in range(24):
        v = 22 + 6 * math.cos((h - 3) / 24 * 2 * math.pi) * -1 + 18 * math.exp(-((h - 7.5) ** 2) / 3)
        v += 70 * math.exp(-((h - 19) ** 2) / 4)
        base.append(round(max(v * scale + rng.normal(0, 3), -5.0), 2))
    return base


def make(date: str = "2026-02-14", seed: int = 0, days: int = 1, layer: str = "v2", outage: bool = False,
         notices: bool = True, desk_forecast: bool = True, operator: bool = True, spike: bool = True,
         site: dict | None = None, pv: bool = False) -> tuple[dict, dict]:
    rng = np.random.default_rng(seed)
    d0 = date
    dates = [(dt.date.fromisoformat(d0) + dt.timedelta(days=j)).isoformat() for j in range(days)]
    hist = [(dt.date.fromisoformat(d0) - dt.timedelta(days=i)).isoformat() for i in range(7, 0, -1)]
    dam, dam_hub, rt_spp, rt_hub, lmp, system = {}, {}, {}, {}, {}, {}
    for d in hist + dates:
        dam[d] = _dam_shape(rng, 0.8 + 0.4 * rng.random())
        dam_hub[d] = [round(x - 1.5 + rng.normal(0, 1), 2) for x in dam[d]]
        l5 = []
        for k in range(288):
            h = k // 12
            v = dam[d][h] + rng.normal(0, 6) + (-8 if 1 <= h <= 5 else 0)
            l5.append(round(v, 2))
        if spike and d in dates:
            k = 12 * 18 + 5
            l5[k] = 650.0
            l5[k + 1] = 320.0
        lmp[d] = l5
        rt_spp[d] = [round(sum(l5[3 * j:3 * j + 3]) / 3, 2) for j in range(96)]
        rt_hub[d] = [round(x - 1.0, 2) for x in rt_spp[d]]
        if d in dates:
            system[d] = {"prc_mw": [round(4500 - 1500 * math.exp(-((k / 12 - 19) ** 2) / 6) + rng.normal(0, 80), 0)
                                    for k in range(288)],
                         "prc_kind": "proxy" if dt.date.fromisoformat(d) >= dt.date(2025, 12, 5) else "real",
                         "lambda": [round(x - 0.5, 2) for x in l5],
                         "load_mw": [round(45000 + 9000 * math.sin((k / 288 - 0.3) * 2 * math.pi), 0) for k in range(288)],
                         "wind_mw": [round(12000 + 3000 * math.cos(k / 288 * 2 * math.pi), 0) for k in range(288)],
                         "solar_mw": [round(max(0.0, 9000 * math.sin((k / 288 - 0.29) / 0.46 * math.pi)), 0)
                                      if 0.29 <= k / 288 <= 0.75 else 0.0 for k in range(288)]}
    end = clock.DAY * days
    forecasts = []
    for t in range(-1440, end, 180):
        start = (t // 60) * 60
        n = (end + clock.DAY - start) // 60
        for kind, f in (("load", lambda h: 45000 + 9000 * math.sin((h % 24 / 24 - 0.3) * 2 * math.pi)),
                        ("wind", lambda h: 12000 + 3000 * math.cos(h % 24 / 24 * 2 * math.pi)),
                        ("solar", lambda h: max(0.0, 9000 * math.sin((h % 24 / 24 - 0.29) / 0.46 * math.pi))
                         if 0.29 <= h % 24 / 24 <= 0.75 else 0.0)):
            forecasts.append({"kind": kind, "issued_at": _iso(t + 30, d0), "start": _iso(start, d0), "step_min": 60,
                              "values": [round(f(start // 60 + i) + rng.normal(0, 300), 0) for i in range(n)],
                              "model": {"load": "fixture STLF", "wind": "fixture STWPF", "solar": "fixture STPPF"}[kind]})
    outage_cap = [{"issued_at": _iso(t, d0), "start": _iso(t, d0), "step_min": 60,
                   "values": [round(9000 + rng.normal(0, 200), 0) for _ in range((end - t) // 60)]}
                  for t in range(-1080, end, 360)]
    series = {"schema": "gridsim.desk.series/v1", "task_id": "", "tz": "America/Chicago", "d0": d0,
              "history_days": hist, "dam_spp": dam, "dam_spp_hub": dam_hub, "rt_spp": rt_spp, "rt_spp_hub": rt_hub,
              "rt_lmp": lmp, "system": system, "forecasts": forecasts, "outage_capacity": outage_cap,
              "unit_events": [], "notices": [], "nws": [], "deployments": [], "operator": {},
              "posted": {"dam": {d: _iso(j * clock.DAY - 646, d0) for j, d in enumerate(dates)}}}
    if desk_forecast:
        fcs = []
        truth = sum((dam[d] for d in dates), [])
        for j in range(days):
            dam_p50 = [round(x + rng.normal(0, 8 + 4 * j), 2) for x in truth[24 * j:]]
            fcs.append({"market": "dam", "issued_at": _iso(j * clock.DAY - 1110, d0), "start": _iso(j * clock.DAY, d0),
                        "step_min": 60, "p10": [round(x - 15, 2) for x in dam_p50], "p50": dam_p50,
                        "p90": [round(x + 20, 2) for x in dam_p50], "model": "fixture-qr"})
        rt_truth = sum((rt_spp[d] for d in dates), [])
        for t in range(-1080, end, 60):
            s0 = max(t, 0) // 60 * 60
            n = (end - s0) // 60
            p50 = []
            for i in range(n):
                H = s0 // 60 + i
                rt_h = sum(rt_truth[4 * H:4 * H + 4]) / 4
                p50.append(round(truth[H] + 0.5 * (rt_h - truth[H]) + rng.normal(0, 6), 2))
            fcs.append({"market": "rt", "issued_at": _iso(t, d0), "start": _iso(s0, d0), "step_min": 60,
                        "p10": [round(x - 12, 2) for x in p50], "p50": p50, "p90": [round(x + 18, 2) for x in p50],
                        "model": "fixture-qr"})
        series["desk_forecast"] = fcs
    if notices:
        series["notices"] = [
            {"event_id": "FIX-1", "source": "ERCOT", "kind": "OCN", "level": "OCN", "issued_at": _iso(-1200, d0),
             "title": "ERCOT OCN", "text": "ERCOT issued an OCN for cold weather (fixture).", "action": "issue"},
            {"event_id": "FIX-2", "source": "ERCOT", "kind": "Advisory", "level": "Advisory",
             "issued_at": _iso(1033, d0), "title": "ERCOT Advisory",
             "text": "ERCOT issued an Advisory: PRC below 3,000 MW expected (fixture).", "action": "issue"}]
        series["nws"] = [{"event_id": "NWS-1", "event": "Wind Advisory", "severity": "Moderate",
                          "issued_at": _iso(-300, d0), "expires": _iso(600, d0), "area": "South",
                          "headline": "Wind Advisory until 10 AM (fixture)"}]
    if outage:
        series["unit_events"] = [{"kind": "derate", "start": _iso(842, d0), "end": _iso(960, d0), "hsl_mw": 50.0,
                                  "lsl_mw": -50.0, "source": "fixture"}]
    if layer != "v2":
        _ancillary(series, hist, dates, d0, rng, pv)
    site = dict(site or SITE)
    if pv:
        site["pv"] = {"mw_ac": 50.0, "poi_mw": 100.0, "profile": "modelled", "source": "fixture"}
    task = {"task_id": f"desk-{layer}-{d0}-S00-f{seed}{'-pv' if pv else ''}", "schema": "gridsim.desk.task/v1", "desk_version": "2.0",
            "pack": "fixtures", "split": "fixture", "layer": layer, "era": era_of(dates), "dates": dates,
            "site": site, "series": "", "operator_ok": operator, "tags": {"fixture": True}}
    series["task_id"] = task["task_id"]
    task["series"] = f"series/{task['task_id']}.json.gz"
    if operator:
        series["operator"] = _operator(task, series)
    task["series_sha"] = series_sha(series)
    return task, series


AS_BASE = {"regup": 4.0, "regdn": 2.0, "rrs": 3.0, "ecrs": 3.5, "nspin": 4.0}
AS_PLAN = {"regup": 350.0, "regdn": 350.0, "rrs": 3000.0, "ecrs": 1500.0, "nspin": 2500.0}


def _ancillary(series: dict, hist: list[str], dates: list[str], d0: str, rng, pv: bool) -> None:
    keys = [k for k in AS_BASE if k != "ecrs" or dt.date.fromisoformat(d0) >= dt.date(2023, 6, 10)]
    rtcb = dt.date.fromisoformat(d0) >= dt.date(2025, 12, 5)
    series["dam_mcpc"], series["rt_mcpc"], series["rt_mcpc_15"], series["asdc"], series["as_plan"] = {}, {}, {}, {}, {}
    series["reg_deploy"] = {}
    for d in hist + dates:
        day = {}
        for k in keys:
            day[k] = [round(max(AS_BASE[k] * (1 + 2.5 * math.exp(-((h - 19) ** 2) / 5)) + rng.normal(0, 0.5), 0.1), 2)
                      for h in range(24)]
        series["dam_mcpc"][d] = day
        if rtcb or d in dates:
            rt5 = {}
            for k in keys:
                v = [round(max(day[k][i // 12] * 0.35 * (1 + rng.normal(0, 0.3)), 0.0), 2) for i in range(288)]
                if d in dates and k == "rrs":
                    v[12 * 18 + 5] = 180.0
                rt5[k] = v
            if rtcb:
                series["rt_mcpc"][d] = rt5
                series["rt_mcpc_15"][d] = {k: [round(sum(v[3 * i:3 * i + 3]) / 3, 2) for i in range(96)]
                                           for k, v in rt5.items()}
        if d in dates:
            series["asdc"][d] = {k: [[[0.0, 5000.0], [0.5 * AS_PLAN[k], 300.0], [AS_PLAN[k], 25.0],
                                      [1.5 * AS_PLAN[k], 0.0]]] * 24 for k in keys}
            series["as_plan"][d] = {k: [AS_PLAN[k]] * 24 for k in keys}
            series["reg_deploy"][d] = {"up": [round(0.1 + 0.1 * rng.random(), 3) for _ in range(24)],
                                       "dn": [round(0.12 + 0.1 * rng.random(), 3) for _ in range(24)],
                                       "source": "modelled"}
    series["deployments"] = [
        {"event_id": "FIX-DEP-1", "product": "rrs", "start": _iso(432, d0), "end": _iso(436, d0), "frac": None,
         "summary": "ERCOT deployed Responsive Reserve (fixture)."},
        {"event_id": "FIX-DEP-2", "product": "ecrs", "start": _iso(1120, d0), "end": _iso(1150, d0), "frac": 1.0,
         "summary": "ERCOT deployed ECRS (fixture)."}]
    if pv:
        series["pv"] = {d: [round(max(0.0, 50 * math.sin((k / 288 - 0.29) / 0.46 * math.pi)), 2)
                            if 0.29 <= k / 288 <= 0.75 else 0.0 for k in range(288)] for d in dates}
        end = clock.DAY * len(dates)
        series["forecasts"] += [{"kind": "pv", "issued_at": _iso(t + 55, d0), "start": _iso(t // 60 * 60, d0),
                                 "step_min": 60, "model": "fixture PV (modelled)",
                                 "values": [round(max(0.0, 50 * math.sin(((t // 60 + i) % 24 / 24 - 0.29) / 0.46
                                                                         * math.pi)) if 0.29 <= (t // 60 + i) % 24 / 24
                                                  <= 0.75 else 0.0, 1) for i in range((end - t // 60 * 60) // 60)]}
                                for t in range(-1440, end, 180)]


def _operator(task: dict, series: dict) -> dict:
    """An invented operator: threshold curves (charge below $22, discharge above $55) run through the engine."""
    ser = build(task, dict(series, operator={}))
    site = site_of(task)
    rtcb = task["era"] == "rtcb"
    eboc = [[site.lsl, 15.0], [0.0, 22.0], [0.0, 55.0], [site.hsl, 80.0]]
    pre = {"offer": [[0.0, 55.0], [site.hsl, 80.0]], "bid": [[0.0, 22.0], [-site.lsl, 15.0]]}
    anc = task["layer"] != "v2"
    e = Engine(site, ser, rtcb, ancillary=anc)
    offers = {"regup": [[20.0, 2.0]], "rrsffr": [[10.0, 1.0]]}
    for H in range(e.H):
        e.dam_curve[H] = eboc if rtcb else pre
        if anc:
            e.dam_as_offer[H] = dict(offers)
    e.advance(ser.end)
    out = {"resource": task["site"]["resource"], "qse": "QFIX00", "dam": {}, "sced": {}, "cop": {}}
    for j, d in enumerate(ser.dates):
        hs, ks = slice(24 * j, 24 * j + 24), slice(288 * j, 288 * j + 288)
        day = {"curves": [eboc] * 24 if rtcb else None, "award_mw": e.dam_award[hs], "spp": ser.dam_spp[hs]}
        if not rtcb:
            day["pre"] = {"offer": [pre["offer"]] * 24, "bid": [pre["bid"]] * 24}
        if anc:
            day["as_offers"] = {p: [offers[p]] * 24 for p in offers}
            day["as_awards"] = {p: [e.dam_as[H].get(p, 0.0) for H in range(24 * j, 24 * j + 24)]
                                for p in ("regup", "regdn", "rrspfr", "rrsffr", "ecrs", "nspin")}
        out["dam"][d] = day
        out["sced"][d] = {"curves": [], "base_point_mw": e.bp[ks], "telemetry_mw": e.metered[ks],
                          "soc_mwh": [round(x, 3) for x in e.soc[288 * j + 1:288 * j + 289]],
                          "hsl_mw": [site.hsl] * 288, "lsl_mw": [site.lsl] * 288, "status": ["ON"] * 288}
        if anc and rtcb:
            out["sced"][d]["as_awards"] = {p: [e.rt_as[k].get(p, 0.0) for k in range(288 * j, 288 * j + 288)]
                                           for p in ("regup", "regdn", "rrspfr", "rrsffr", "ecrs", "nspin")}
    return out
