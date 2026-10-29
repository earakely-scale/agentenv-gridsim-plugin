import random

from conftest import load_fixtures, tasks
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gridsim_core.advantage import hour_advantages, value_table
from gridsim_core.dp import solve_dp
from gridsim_core.grade import foresight_refs, grade
from gridsim_core.physics import simulate
from gridsim_core.task import battery_of

FIX = load_fixtures()


def _plans(task, seed):
    b, rng = task["battery"], random.Random(seed)
    lo, hi = -b["k_ch"] - 1, b["k_dis"] + 1
    yield solve_dp(task)[1]
    yield [0] * 24
    for _ in range(6):
        yield [rng.randint(lo, hi) for _ in range(24)]
    opt = solve_dp(task)[1]
    for _ in range(4):
        p = list(opt)
        p[rng.randrange(24)] += rng.choice([-2, -1, 1, 2])
        yield p


def _check(task, plan):
    f = foresight_refs(task)
    a = hour_advantages(task, plan)
    sim, g = simulate(task, plan), grade(task, plan)
    tol = 1e-6 * max(1.0, abs(f["p_opt"]), abs(sim["profit_usd"]))
    assert all(x <= tol for x in a["adv_usd"])
    assert abs(sum(a["adv_usd"]) - (sim["profit_usd"] - f["p_opt"])) <= 24 * tol
    if g["reward"] > 0:
        assert abs(sum(a["adv"]) - (g["reward"] - 1)) <= 2e-6 + 24 * tol * a["scale"]
    else:
        assert sum(a["adv"]) <= -1 + 2e-6
    assert all(abs(s + d - x) <= 1e-9 * max(1.0, abs(x)) for s, d, x in zip(a["sign"], a["digit"], a["adv"],
                                                                             strict=True))
    assert all(s <= 1e-9 and d <= 1e-9 for s, d in zip(a["sign"], a["digit"], strict=True))
    assert a["truncated_at"] == sim["truncated_at"]
    if a["truncated_at"] is not None:
        assert all(x == 0 for x in a["adv"][a["truncated_at"] + 1:])
    return a


@settings(max_examples=200, deadline=None)
@given(tasks(), st.integers(0, 10**6))
def test_advantages_sum_to_shortfall_and_vanish_on_the_optimum(task, seed):
    f = foresight_refs(task)
    assume(f["p_opt"] - f["p_idle"] > 1e-6)
    for i, plan in enumerate(_plans(task, seed)):
        a = _check(task, plan)
        if i == 0:
            assert all(abs(x) <= 1e-6 * max(1.0, abs(a["v0"])) for x in a["adv_usd"])
            assert a["opt"] == plan


@settings(max_examples=200, deadline=None)
@given(tasks())
def test_value_table_matches_dp(task):
    b = battery_of(task)
    p_opt, _ = solve_dp(task)
    assert abs(value_table(b, task["prices"])[0, b.s0, 0] - p_opt) <= 1e-6 * max(1.0, abs(p_opt))


def test_fixtures_and_stored_refs():
    for t in FIX:
        for plan in _plans(t, 0):
            _check(t, plan)
        opt = t["refs"]["foresight"]["opt"]
        assert max(abs(x) for x in hour_advantages(t, opt)["adv"]) <= 1e-6
