"""Exact per-hour advantages from the DP: A_t = Q*(t, s_t, d_t, a_t) - V*(t, s_t, d_t) under grade's rules (a
rule-breaking hour truncates the day, which then settles idle with the end penalty), in $ and in reward units."""

from __future__ import annotations

import numpy as np

from gridsim_core.dp import TIE_TOL, action_order
from gridsim_core.grade import foresight_refs
from gridsim_core.parse import parse_actions
from gridsim_core.physics import cash, penalty_per_unit
from gridsim_core.task import Battery, battery_of


def value_table(b: Battery, prices) -> np.ndarray:
    """V*[h, s, d] for h in 0..len(prices): the best value-to-go from SoC s with d discharge units used."""
    n, cap, hours = b.n, b.cap, len(prices)
    v = np.empty((hours + 1, n + 1, cap + 1))
    v[hours] = (-np.maximum(0, b.s_end_min - np.arange(n + 1)) * penalty_per_unit(b, prices))[:, None]
    for h in range(hours - 1, -1, -1):
        best = np.full((n + 1, cap + 1), -np.inf)
        for a in action_order(b):
            lo, hi, da = max(0, a), min(n, n + a), max(a, 0)
            if lo <= hi and da <= cap:
                q = cash(b, prices[h], a)[1] + v[h + 1, lo - a:hi - a + 1, da:]
                np.maximum(best[lo:hi + 1, :cap + 1 - da], q, out=best[lo:hi + 1, :cap + 1 - da])
        v[h] = best
    return v


def q_value(b: Battery, prices, v: np.ndarray, h: int, s: int, d: int, a: int) -> float:
    """Q*(h, s, d, a); an action that breaks a rule truncates: this and every later hour idle, then the end penalty."""
    if a > b.k_dis or a < -b.k_ch or not 0 <= s - a <= b.n or d + max(a, 0) > b.cap:
        return -max(0, b.s_end_min - s) * penalty_per_unit(b, prices)
    return cash(b, prices[h], a)[1] + float(v[h + 1, s - a, d + max(a, 0)])


def sign_q(b: Battery, prices, v: np.ndarray, h: int, s: int, d: int, negative: bool) -> float:
    """max Q* over the actions that share a's sign class (a < 0, or a >= 0): the value of writing the sign token."""
    acts = range(-b.k_ch, 0) if negative else range(0, b.k_dis + 1)
    return max(q_value(b, prices, v, h, s, d, a) for a in acts)


def best_action(b: Battery, prices, v: np.ndarray, h: int, s: int, d: int) -> int:
    """The DP's action at (h, s, d), with dp_schedule's tie order."""
    qs = [(q_value(b, prices, v, h, s, d, a), a) for a in action_order(b)]
    top = max(q for q, _ in qs)
    return next(a for q, a in qs if q >= top - TIE_TOL)


def hour_advantages(task: dict, actions, prices=None) -> dict:
    """Per-hour exact advantages of a submitted schedule along its own SoC path, plus the sign/digit split of each
    hour (sign = Q*(sign class) - V*, digit = Q*(a) - Q*(sign class)) and the DP action a*_t at each visited state.
    Hours after a truncation have advantage 0 (nothing they say executes). scale = 0.8 / (P_opt - P_idle), so
    sum(adv) = R_unclipped - 1."""
    b, p = battery_of(task), task["prices"] if prices is None else prices
    acts, v = parse_actions(actions), value_table(b, p)
    f = foresight_refs(task)
    scale = 0.8 / (f["p_opt"] - f["p_idle"])
    s, d, cut = b.s0, 0, None
    adv, sign, digit, opt = [], [], [], []
    for h, a in enumerate(acts):
        if cut is not None:
            adv.append(0.0), sign.append(0.0), digit.append(0.0), opt.append(None)
            continue
        base = float(v[h, s, d])
        qa, qs = q_value(b, p, v, h, s, d, a), sign_q(b, p, v, h, s, d, a < 0)
        adv.append(qa - base), sign.append(qs - base), digit.append(qa - qs)
        opt.append(best_action(b, p, v, h, s, d))
        if a > b.k_dis or a < -b.k_ch or not 0 <= s - a <= b.n or d + max(a, 0) > b.cap:
            cut = h
        else:
            s, d = s - a, d + max(a, 0)
    return {"adv_usd": adv, "adv": [x * scale for x in adv], "sign": [x * scale for x in sign],
            "digit": [x * scale for x in digit], "opt": opt, "truncated_at": cut, "v0": float(v[0, b.s0, 0]),
            "scale": scale}
