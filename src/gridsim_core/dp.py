"""Exact DP optimum over SoC s in 0..N, discharge used d in 0..cap and integer actions."""

from __future__ import annotations

import numpy as np

from gridsim_core.physics import cash, penalty_per_unit, settle
from gridsim_core.task import Battery, battery_of

TIE_TOL = 1e-7


def action_order(b: Battery) -> list[int]:
    """Tie order: smaller |a| first, then charge before discharge."""
    return sorted(range(-b.k_ch, b.k_dis + 1), key=lambda a: (abs(a), a))


def dp_schedule(b: Battery, prices) -> list[int]:
    """Optimal schedule for any horizon; ties go to the earliest action in action_order at each hour."""
    n, cap, acts = b.n, b.cap, action_order(b)
    v = np.repeat((-np.maximum(0, b.s_end_min - np.arange(n + 1)) * penalty_per_unit(b, prices))[:, None], cap + 1, 1)
    policy = np.empty((len(prices), n + 1, cap + 1), dtype=np.int8)
    q = np.empty((len(acts), n + 1, cap + 1))
    for h in range(len(prices) - 1, -1, -1):
        q.fill(-np.inf)
        for i, a in enumerate(acts):
            lo, hi, da = max(0, a), min(n, n + a), max(a, 0)
            if lo <= hi and da <= cap:
                q[i, lo:hi + 1, :cap + 1 - da] = cash(b, prices[h], a)[1] + v[lo - a:hi - a + 1, da:]
        pick = np.argmax(q >= q.max(axis=0) - TIE_TOL, axis=0)
        policy[h] = pick
        v = np.take_along_axis(q, pick[None], 0)[0]
    s, d, out = b.s0, 0, []
    for h in range(len(prices)):
        a = acts[policy[h, s, d]]
        out.append(a)
        s, d = s - a, d + max(a, 0)
    return out


def solve_dp(task: dict, prices=None) -> tuple[float, list[int]]:
    """(profit at the decision prices, schedule[24]); profit is the settled value of the schedule."""
    b, p = battery_of(task), task["prices"] if prices is None else prices
    sched = dp_schedule(b, p)
    return settle(b, p, sched)["profit_usd"], sched
