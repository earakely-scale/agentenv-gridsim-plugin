"""Settle a schedule under the exact v1 battery physics."""

from __future__ import annotations

from gridsim_core.contract import P_FLOOR
from gridsim_core.parse import parse_actions
from gridsim_core.task import Battery, battery_of


def penalty_per_unit(b: Battery, prices) -> float:
    """$ per unit of end-SoC shortfall: q/eta * max(max price, p_floor)."""
    return b.q / b.eta * max(max(prices), P_FLOOR)


def cash(b: Battery, price: float, a: int) -> tuple[float, float, float]:
    """(mwh, cash, degradation) of action a at price."""
    mwh = b.q * a if a > 0 else b.q * a / b.eta
    deg = b.c_deg * b.q * a if a > 0 else 0.0
    return mwh, price * mwh - deg, deg


def settle(b: Battery, prices, actions) -> dict:
    """Simulate any horizon; the first rule-breaking hour and all later hours execute as 0."""
    s, d, cut, why = b.s0, 0, None, None
    executed, soc, cashflow, mwh, degs = [], [s], [], [], []
    for h, a in enumerate(actions):
        if cut is None:
            why = ("rate" if a > b.k_dis or a < -b.k_ch else "soc_below_0" if s - a < 0
                   else "soc_above_N" if s - a > b.n else "cycle_cap" if d + max(a, 0) > b.cap else None)
            if why:
                cut = h
        a = 0 if cut is not None else a
        s, d = s - a, d + max(a, 0)
        m, c, g = cash(b, prices[h], a)
        executed.append(a)
        soc.append(s)
        mwh.append(m)
        cashflow.append(c)
        degs.append(g)
    short = max(0, b.s_end_min - s)
    penalty = short * penalty_per_unit(b, prices) if short else 0.0
    return {"feasible": cut is None, "truncated_at": cut, "violation": why if cut is not None else None,
            "executed": executed, "soc_path": soc, "cashflow": cashflow, "mwh": mwh, "degradation_usd": sum(degs),
            "end_shortfall_units": short, "penalty_usd": penalty, "profit_usd": sum(cashflow) - penalty}


def simulate(task: dict, actions, prices=None) -> dict:
    """Settle parsed actions for a task at its prices (or at the given prices)."""
    return settle(battery_of(task), task["prices"] if prices is None else prices, parse_actions(actions))


def profit(task: dict, actions, prices=None) -> float:
    return simulate(task, actions, prices)["profit_usd"]
