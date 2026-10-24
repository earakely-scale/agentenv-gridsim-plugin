"""Reference policies; each returns a feasible schedule of 24 ints (settle it with physics.simulate)."""

from __future__ import annotations

import datetime as dt
import math

import numpy as np

from gridsim_core.dp import dp_schedule
from gridsim_core.physics import settle
from gridsim_core.task import Battery, battery_of


def idle(task: dict) -> list[int]:
    return [0] * len(task["prices"])


def clock(task: dict) -> list[int]:
    """Charge at full rate HE02-05, discharge at full rate HE18-21."""
    b = battery_of(task)
    want = [-b.k_ch if 1 <= h <= 4 else b.k_dis if 17 <= h <= 20 else 0 for h in range(len(task["prices"]))]
    return _repair(b, task["prices"], _clip(b, want))


def threshold(task: dict) -> list[int]:
    """Charge at p <= p25 and discharge at p >= p75 while p*eta - p25 > c_deg."""
    b, p = battery_of(task), task["prices"]
    lo, hi = np.percentile(p, 25), np.percentile(p, 75)
    sell = [x >= hi and x * b.eta - lo > b.c_deg for x in p]
    want = [0] * len(p)
    if any(sell):
        want = [b.k_dis if sell[h] else -b.k_ch if x <= lo else 0 for h, x in enumerate(p)]
    return _repair(b, p, _clip(b, want))


def greedy(task: dict) -> list[int]:
    """Pair the m = ceil(E/P) cheapest hours with the dearest later ones at full rate while p_d*eta - p_c - c_deg*eta > 0."""
    b, p = battery_of(task), task["prices"]
    m = math.ceil(b.n / b.k_dis)
    order = sorted(range(len(p)), key=lambda h: (p[h], h))
    cheap, dear = order[:m], sorted(order[-m:], key=lambda h: (-p[h], h))
    want, used = [0] * len(p), set()
    for c in cheap:
        for d in dear:
            if d > c and d not in used and p[d] * b.eta - p[c] - b.c_deg * b.eta > 0:
                used.add(d)
                want[c], want[d] = -b.k_ch, b.k_dis
                break
    return _repair(b, p, _clip(b, want))


def random_feasible(task: dict, seed: int = 0) -> list[int]:
    """Uniform over actions that keep every rule and leave the end obligation reachable."""
    b, t = battery_of(task), len(task["prices"])
    rng = np.random.default_rng(seed)
    s, d, out = b.s0, 0, []
    for h in range(t):
        ok = [a for a in range(-b.k_ch, b.k_dis + 1)
              if 0 <= s - a <= b.n and d + max(a, 0) <= b.cap and s - a + b.k_ch * (t - 1 - h) >= b.s_end_min]
        a = int(rng.choice(ok)) if ok else -min(b.k_ch, b.n - s)
        out.append(a)
        s, d = s - a, d + max(a, 0)
    return out


def persistence_dp(task: dict) -> list[int]:
    """The DP schedule on D-1 prices (settle it on D)."""
    return dp_schedule(battery_of(task), task["blind"]["dam_prev_day"])


def ridge_dp(task: dict, model: dict) -> list[int]:
    """The DP schedule on ridge-predicted prices (settle it on D)."""
    return dp_schedule(battery_of(task), ridge_predict(task, model))


RIDGE_FEATURES = ["bias", "dam_prev_day", "dam_prev_7d_mean"] + [f"dow_{i}" for i in range(6)] + [
    f"month_{m}" for m in range(2, 13)]


def ridge_features(date: str, prev_day, prev_7d) -> np.ndarray:
    """[24, 20] design rows: bias, D-1 price, D-7..D-1 mean at the hour, weekday (Sun base) and month (Jan base)."""
    d = dt.date.fromisoformat(date)
    cal = np.zeros(17)
    if d.weekday() < 6:
        cal[d.weekday()] = 1.0
    if d.month > 1:
        cal[4 + d.month] = 1.0
    x = np.empty((24, 20))
    x[:, 0], x[:, 1], x[:, 2], x[:, 3:] = 1.0, prev_day, np.mean(prev_7d, axis=0), cal
    return x


def ridge_predict(task: dict, model: dict) -> list[float]:
    x = ridge_features(task["date"], task["blind"]["dam_prev_day"], task["blind"]["dam_prev_7d"])
    return [float(v) for v in np.einsum("hf,hf->h", x, np.asarray(model["coef"]))]


def ridge_fit(rows, lam: float = 10.0) -> dict:
    """Per-hour ridge on (date, prev_day, prev_7d, prices) rows; the bias is not penalised."""
    xs = np.stack([ridge_features(r[0], r[1], r[2]) for r in rows])
    ys = np.asarray([r[3] for r in rows], dtype=float)
    pen = lam * np.eye(xs.shape[2])
    pen[0, 0] = 0.0
    coef = [np.linalg.solve(xs[:, h].T @ xs[:, h] + pen, xs[:, h].T @ ys[:, h]) for h in range(24)]
    return {"version": "ridge-v1", "features": RIDGE_FEATURES, "lambda": lam, "n_rows": len(rows),
            "coef": [[round(float(c), 8) for c in row] for row in coef]}


def _clip(b: Battery, want) -> list[int]:
    """Clip each hour to rate, SoC and the cycle cap."""
    s, d, out = b.s0, 0, []
    for a in want:
        a = min(a, b.k_dis, s, b.cap - d) if a > 0 else -min(-a, b.k_ch, b.n - s) if a < 0 else 0
        out.append(a)
        s, d = s - a, d + max(a, 0)
    return out


def _repair(b: Battery, prices, sched: list[int]) -> list[int]:
    """Cover an end shortfall by charging one more unit in the cheapest hour that stays feasible and pays."""
    sched = list(sched)
    cur = settle(b, prices, sched)
    while cur["end_shortfall_units"]:
        for h in sorted(range(len(prices)), key=lambda h: (prices[h], h)):
            trial = sched[:h] + [sched[h] - 1] + sched[h + 1:]
            new = settle(b, prices, trial)
            if new["feasible"] and new["profit_usd"] > cur["profit_usd"]:
                sched, cur = trial, new
                break
        else:
            break
    return sched
