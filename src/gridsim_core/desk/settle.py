"""The settlement statement (contract section 7): + is paid to the QSE. One function settles the agent, every reference
and the operator rows from DAM awards, base points and metered MW."""

from __future__ import annotations

from gridsim_core.desk.data import Series
from gridsim_core.desk.engine import PER_H, Site

ENERGY_LINES = ("dam_energy", "rt_energy_imbalance", "deviation", "load_allocated", "degradation",
                "warranty_overage", "end_soc_shortfall")
MODELLED = ("degradation", "warranty_overage", "end_soc_shortfall")
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


def statement(site: Site, ser: Series, rtcb: bool, dam_award, bp, metered, soc_end: float, target: float) -> dict:
    """Per-day lines and totals for awards (24/day), base points and metered MW (288/day)."""
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
        lines = {k: round(float(v), 2) + 0.0 for k, v in lines.items()}
        day_total = round(sum(lines.values()), 2)
        out[ser.dates[j]] = {"lines": lines, "total": day_total, "discharged_mwh": round(float(dis), 3),
                             "charged_mwh": round(float(chg), 3), "cycles": round(float(dis) / site.usable, 3)}
        total += day_total
    return {"days": out, "total": round(float(total), 2), "modelled": list(MODELLED),
            "deviation_kind": "set_point_deviation" if rtcb else "base_point_deviation"}


def partial(site: Site, ser: Series, rtcb: bool, dam_award, bp, metered, upto_interval: int) -> dict:
    """Shadow settlement of the 15-minute intervals that ended before `upto_interval` (index on the 15-minute grid)."""
    lines = {"dam_energy": 0.0, "rt_energy_imbalance": 0.0, "deviation": 0.0, "degradation": 0.0}
    for i in range(min(upto_interval, 96 * ser.days)):
        k0, a = 3 * i, dam_award[i // 4] or 0.0
        m = sum(metered[k0:k0 + 3]) / 3
        lines["dam_energy"] += ser.dam_spp[i // 4] * a / 4
        lines["rt_energy_imbalance"] += ser.rt_spp[i] * (m - a) / 4
        lines["deviation"] += deviation(sum(bp[k0:k0 + 3]) / 3, m, ser.rt_spp[i], rtcb)
        lines["degradation"] -= site.deg * sum(max(x, 0.0) for x in metered[k0:k0 + 3]) / PER_H
    lines = {k: round(v, 2) + 0.0 for k, v in lines.items()}
    return {"lines": lines, "total": round(sum(lines.values()), 2)}
