import itertools
import time
from functools import cache

import numpy as np
import pytest
from conftest import battery_dict, load_fixtures, tasks
from hypothesis import given, settings
from hypothesis import strategies as st

from gridsim_core import baselines
from gridsim_core.dp import dp_schedule, solve_dp
from gridsim_core.lp import lp_bound
from gridsim_core.physics import penalty_per_unit, settle, simulate
from gridsim_core.task import battery_of

FIX = load_fixtures()


def _baseline_profits(task):
    out = [simulate(task, f(task))["profit_usd"] for f in (baselines.idle, baselines.clock, baselines.threshold,
                                                          baselines.greedy)]
    out += [simulate(task, baselines.random_feasible(task, s))["profit_usd"] for s in range(3)]
    if task.get("blind"):
        out.append(simulate(task, baselines.persistence_dp(task))["profit_usd"])
    return out


@settings(max_examples=300, deadline=None)
@given(tasks())
def test_dp_beats_baselines_feasible_and_settles(task):
    p_opt, sched = solve_dp(task)
    sim = simulate(task, sched)
    assert sim["feasible"] and sim["profit_usd"] == p_opt
    assert all(p <= p_opt + 1e-6 for p in _baseline_profits(task))


@settings(max_examples=200, deadline=None)
@given(tasks())
def test_lp_bounds_dp(task):
    assert lp_bound(task) >= solve_dp(task)[0] - 1e-6 * max(1.0, abs(solve_dp(task)[0]))


@pytest.mark.parametrize("task", FIX, ids=[t["task_id"] for t in FIX])
def test_fixture_refs(task):
    p_opt, sched = solve_dp(task)
    f = task["refs"]["foresight"]
    assert sched == f["opt"] and round(p_opt, 6) == f["p_opt"]
    assert all(p <= p_opt + 1e-6 for p in _baseline_profits(task))
    assert f["p_lp"] is None or f["p_lp"] >= p_opt - 1e-4
    for b in f["baselines"].values():
        assert simulate(task, b["schedule"])["feasible"]


@settings(max_examples=150, deadline=None)
@given(st.data())
def test_brute_force_short_horizon(data):
    hours = data.draw(st.integers(1, 5))
    n = data.draw(st.integers(1, 3))
    b = battery_of(battery_dict(n, data.draw(st.integers(1, 2)), data.draw(st.integers(1, 2)),
                                data.draw(st.sampled_from([0.8, 0.9])), data.draw(st.sampled_from([0.0, 8.0])),
                                data.draw(st.integers(0, 2 * n)), data.draw(st.integers(0, n)),
                                data.draw(st.integers(0, n))))
    prices = data.draw(st.lists(st.floats(-100, 300, allow_nan=False).map(lambda x: round(x, 2)),
                                min_size=hours, max_size=hours))
    best = max(r["profit_usd"] for a in itertools.product(range(-b.k_ch, b.k_dis + 1), repeat=hours)
               if (r := settle(b, prices, a))["feasible"])
    sched = dp_schedule(b, prices)
    got = settle(b, prices, sched)
    assert got["feasible"] and abs(got["profit_usd"] - best) < 1e-6


@settings(max_examples=60, deadline=None)
@given(tasks(max_n=3, k_max=3))
def test_matches_reference_recursion_24h(task):
    b, p = battery_of(task), task["prices"]
    pen = penalty_per_unit(b, p)

    @cache
    def v(h, s, d):
        if h == 24:
            return -max(0, b.s_end_min - s) * pen
        best = -np.inf
        for a in range(-b.k_ch, b.k_dis + 1):
            if 0 <= s - a <= b.n and d + max(a, 0) <= b.cap:
                g = b.q * a if a > 0 else b.q * a / b.eta
                best = max(best, p[h] * g - b.c_deg * b.q * max(a, 0) + v(h + 1, s - a, d + max(a, 0)))
        return best

    assert abs(solve_dp(task)[0] - v(0, b.s0, 0)) < 1e-6


@settings(max_examples=50, deadline=None)
@given(tasks())
def test_deterministic(task):
    assert solve_dp(task) == solve_dp(dict(task)) and lp_bound(task) == lp_bound(task)
    assert baselines.random_feasible(task, 7) == baselines.random_feasible(task, 7)


def test_dp_speed():
    rng = np.random.default_rng(1)
    t = {"prices": list(rng.normal(40, 30, 24)), "battery": battery_dict(16, 4, 4, 0.85, 4.0, 32, 8, 8)}
    solve_dp(t)
    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        solve_dp(t)
        times.append(time.perf_counter() - t0)
    assert np.percentile(times, 95) < 0.005
