import pytest
from conftest import load_fixtures, tasks
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gridsim_core import baselines
from gridsim_core.dp import solve_dp
from gridsim_core.grade import grade, reward_value
from gridsim_core.physics import simulate
from gridsim_core.task import battery_of

FIX = load_fixtures()


@settings(max_examples=300, deadline=None)
@given(tasks(), st.data())
def test_reward_anchors_and_range(task, data):
    p_opt, opt = solve_dp(task)
    p_idle = simulate(task, [0] * 24)["profit_usd"]
    assume(p_opt - p_idle > 1e-6)
    assert grade(task, [0] * 24)["reward"] == 0.2
    assert grade(task, opt)["reward"] == 1.0
    b = battery_of(task)
    acts = data.draw(st.lists(st.integers(-b.k_ch - 1, b.k_dis + 1), min_size=24, max_size=24))
    g = grade(task, acts)
    assert 0.0 <= g["reward"] <= 1.0 and g["reward"] == round(g["reward"], 6)
    assert g == grade(task, " ".join(map(str, acts)))


@pytest.mark.parametrize("task", FIX, ids=[t["task_id"] for t in FIX])
def test_fixture_grades(task):
    f = task["refs"]["foresight"]
    assert grade(task, [0] * 24)["reward"] == 0.2
    assert grade(task, f["opt"])["reward"] == 1.0
    for name, b in f["baselines"].items():
        assert grade(task, b["schedule"])["reward"] == b["reward"], name
    if task["refs"].get("blind"):
        bl = task["refs"]["blind"]
        best = bl["persist"] if bl["p_persist"] >= bl["p_ridge"] else bl["ridge"]
        g = grade(task, best, "blind")
        assert g["reward"] == 1.0 and g["r_opt"] == bl["r_opt_anchor"] and g["beats_anchor"] is False


def test_not_a_submission():
    task = {"prices": [10.0] * 24, "battery": {"unit_mwh": 1, "k_dis": 2, "k_ch": 2, "soc_levels": 4, "eta": 0.9,
                                               "c_deg": 0, "cycle_cap_units": 4, "s0": 2, "s_end_min": 2}}
    for bad in ([0] * 23, "1 2 3", [0.5] * 24, [], [[0] * 24], None, {"actions": [0] * 24}):
        g = grade(task, bad)
        assert g["submitted"] is False and g["reward"] == 0.0 and g["error"]


def test_reward_value():
    assert reward_value(50, 0, 100) == 0.6
    assert reward_value(-1e9, 0, 100) == 0.0 and reward_value(1e9, 0, 100) == 1.0
    assert reward_value(0, 0, 0) == 1.0 and reward_value(-1, 0, 0) == 0.0


def test_idle_with_shortfall_is_still_0_2():
    prices = [20.0] * 12 + [80.0] * 12
    task = {"task_id": "x", "prices": prices, "battery": {"unit_mwh": 10, "k_dis": 2, "k_ch": 2, "soc_levels": 4,
                                                          "eta": 0.85, "c_deg": 0, "cycle_cap_units": 4, "s0": 0,
                                                          "s_end_min": 2}}
    g = grade(task, [0] * 24)
    assert g["profit"] < 0 and g["end_shortfall_units"] == 2 and g["reward"] == 0.2
    assert grade(task, baselines.greedy(task))["reward"] > 0.2
