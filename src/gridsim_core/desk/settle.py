"""The settlement statement (contract section 7): + is paid to the QSE. One function settles the agent, every reference
and the operator rows from DAM awards, base points and metered MW."""

from __future__ import annotations

from gridsim_core.desk.ancillary import DEPLOY_FACTOR, DURATION_POST, PRICE_KEY, UP
from gridsim_core.desk.data import Series
from gridsim_core.desk.engine import PER_H, Site

ENERGY_LINES = ("dam_energy", "rt_energy_imbalance", "deviation", "load_allocated", "degradation",
                "warranty_overage", "end_soc_shortfall")
AS_LINES = ("dam_as_capacity", "rt_as_imbalance", "failure_to_provide", "capacity_short", "pv_energy")
MODELLED = ("degradation", "warranty_overage", "end_soc_shortfall", "capacity_short", "pv_energy")
SPD_FLOOR = 20.0


def tolerances(aasp: float, rtcb: bool) -> tuple[float, float]:
    """(over, under) tolerance MW: post-RTC+B Set Point Deviation 3% / 3 MW (P§6.6.5); pre 5% / 5 MW [simplified]."""
    pct, mw = (0.03, 3.0) if rtcb else (0.05, 5.0)
    return max(pct * abs(aasp), mw), min(pct * abs(aasp), mw)


def deviation(aasp: float, actual: float, price: float, rtcb: bool) -> float:
    over_tol, under_tol = tolerances(aasp, rtcb)
    over = max(actual - aasp - over_tol, 0.0) / 4
    under = max(aasp - actual - under_tol, 0.0) / 4
    return -max(SPD_FLOOR, price) * over + min(-SPD_FLOOR, price) * under


def statement(site: Site, ser: Series, rtcb: bool, dam_award, bp, metered, soc_end: float, target: float,
              ancillary: dict | None = None) -> dict:
    """Per-day lines and totals for awards (24/day), base points and metered MW (288/day); `ancillary` (v3+) adds
    the AS and PV lines: {"dam_as": [H], "rt_as": [K] (post), "short": [K] (pre), "druc": [days], "pv": [K]}."""
    days, out, total = ser.days, {}, 0.0
    for j in range(days):
        hs, ks = range(24 * j, 24 * j + 24), range(288 * j, 288 * j + 288)
        dam = sum(ser.dam_spp[h] * (dam_award[h] or 0.0) for h in hs)
        rt = dev = 0.0
        for i in range(96 * j, 96 * j + 96):
            k0 = 3 * i
            m = sum(metered[k0:k0 + 3]) / 3
            a = sum(bp[k0:k0 + 3]) / 3
            rt += ser.rt_spp[i] * (m - (dam_award[i // 4] or 0.0)) / 4
            dev += deviation(a, m, ser.rt_spp[i], rtcb)
        dis = sum(max(metered[k], 0.0) for k in ks) / PER_H
        chg = sum(max(-metered[k], 0.0) for k in ks) / PER_H
        excess = max(dis - site.warranty * site.usable, 0.0)
        lines = {"dam_energy": dam, "rt_energy_imbalance": rt, "deviation": dev, "load_allocated": 0.0,
                 "degradation": -site.deg * dis, "warranty_overage": -2 * site.deg * excess, "end_soc_shortfall": 0.0}
        if j == days - 1:
            price = max(sum(ser.dam_spp[h] for h in hs) / 24, SPD_FLOOR) / site.eta
            lines["end_soc_shortfall"] = -max(target - soc_end, 0.0) * price
        if ancillary is not None:
            lines.update(as_lines(site, ser, rtcb, j, ancillary))
        lines = {k: round(float(v), 2) + 0.0 for k, v in lines.items()}
        day_total = round(sum(lines.values()), 2)
        out[ser.dates[j]] = {"lines": lines, "total": day_total, "discharged_mwh": round(float(dis), 3),
                             "charged_mwh": round(float(chg), 3), "cycles": round(float(dis) / site.usable, 3)}
        total += day_total
    return {"days": out, "total": round(float(total), 2), "modelled": list(MODELLED),
            "deviation_kind": "set_point_deviation" if rtcb else "base_point_deviation"}


def partial(site: Site, ser: Series, rtcb: bool, dam_award, bp, metered, upto_interval: int,
            ancillary: dict | None = None) -> dict:
    """Shadow settlement of the 15-minute intervals that ended before `upto_interval` (index on the 15-minute grid)."""
    lines = {"dam_energy": 0.0, "rt_energy_imbalance": 0.0, "deviation": 0.0, "degradation": 0.0}
    if ancillary is not None:
        lines.update({"dam_as_capacity": 0.0, "rt_as_imbalance": 0.0})
    for i in range(min(upto_interval, 96 * ser.days)):
        k0, a = 3 * i, dam_award[i // 4] or 0.0
        m = sum(metered[k0:k0 + 3]) / 3
        lines["dam_energy"] += ser.dam_spp[i // 4] * a / 4
        lines["rt_energy_imbalance"] += ser.rt_spp[i] * (m - a) / 4
        lines["deviation"] += deviation(sum(bp[k0:k0 + 3]) / 3, m, ser.rt_spp[i], rtcb)
        lines["degradation"] -= site.deg * sum(max(x, 0.0) for x in metered[k0:k0 + 3]) / PER_H
        if ancillary is not None:
            aw = ancillary["dam_as"][i // 4]
            lines["dam_as_capacity"] += sum(_mcpc(ser.dam_mcpc, PRICE_KEY[p], i // 4) * v for p, v in aw.items()) / 4
            rt_as = ancillary.get("rt_as")
            if rtcb and rt_as is not None:
                for p in set(aw) | {p for k in range(k0, k0 + 3) for p in rt_as[k]}:
                    pk = PRICE_KEY[p]
                    price = ser.rt_mcpc_15[pk][i] if pk in ser.rt_mcpc_15 else 0.0
                    r = sum(rt_as[k].get(p, 0.0) for k in range(k0, k0 + 3)) / 3
                    lines["rt_as_imbalance"] += price * (r - aw.get(p, 0.0)) / 4
    lines = {k: round(v, 2) + 0.0 for k, v in lines.items()}
    return {"lines": lines, "total": round(sum(lines.values()), 2)}


def as_lines(site: Site, ser: Series, rtcb: bool, j: int, a: dict) -> dict:
    """AS capacity (DAM MCPC), post-RTC+B RT imbalance at the RT MCPC (P§6.7.2.x), pre-RTC+B failure-to-provide at
    the DAM MCPC (pre-P§6.7.3, ORDC part omitted), the post-RTC+B capacity-short test on the DRUC COP HBSOC
    (P§5.7.4.1, simplified), and PV energy at the RT SPP."""
    dam_as, rt_as, short, pv = a.get("dam_as") or [], a.get("rt_as"), a.get("short"), a.get("pv")
    out = {k: 0.0 for k in AS_LINES}
    for h in range(24 * j, 24 * j + 24):
        aw = dam_as[h] if h < len(dam_as) else {}
        for p, mw in aw.items():
            out["dam_as_capacity"] += _mcpc(ser.dam_mcpc, PRICE_KEY[p], h) * mw
        if not rtcb and short:
            for p in aw:
                q = sum(short[k].get(p, 0.0) for k in range(PER_H * h, PER_H * h + PER_H)) / PER_H
                out["failure_to_provide"] -= _mcpc(ser.dam_mcpc, PRICE_KEY[p], h) * q
        if rtcb and aw:
            druc = (a.get("druc") or [None] * ser.days)[j]
            if druc:
                hh = h - 24 * j
                need = sum(aw.get(p, 0.0) * DURATION_POST[p] * DEPLOY_FACTOR for p in UP)
                avail = max(druc["hbsoc"][hh] - druc["min_soc"][hh], 0.0) * site.eta
                up = sum(aw.get(p, 0.0) for p in UP)
                if need > avail + 1e-9 and up > 0:
                    short_mw = (need - avail) / (need / up)
                    price = sum(_mcpc(ser.dam_mcpc, PRICE_KEY[p], h) * aw.get(p, 0.0) for p in UP) / up
                    out["capacity_short"] -= short_mw * price
    if rtcb and rt_as is not None:
        for i in range(96 * j, 96 * j + 96):
            h = i // 4
            aw = dam_as[h] if h < len(dam_as) else {}
            for p in set(aw) | {p for k in range(3 * i, 3 * i + 3) for p in rt_as[k]}:
                r = sum(rt_as[k].get(p, 0.0) for k in range(3 * i, 3 * i + 3)) / 3
                pk = PRICE_KEY[p]
                price = ser.rt_mcpc_15[pk][i] if pk in ser.rt_mcpc_15 else (
                    sum(ser.rt_mcpc[pk][3 * i:3 * i + 3]) / 3 if pk in ser.rt_mcpc else 0.0)
                out["rt_as_imbalance"] += price * (r - aw.get(p, 0.0)) / 4
    if pv:
        for i in range(96 * j, 96 * j + 96):
            out["pv_energy"] += ser.rt_spp[i] * sum(pv[3 * i:3 * i + 3]) / 3 / 4
    return out


def _mcpc(block: dict, key: str, h: int) -> float:
    v = block.get(key)
    return float(v[h]) if v else 0.0
