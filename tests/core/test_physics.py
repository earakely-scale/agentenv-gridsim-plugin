from conftest import tasks
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gridsim_core import baselines
from gridsim_core.contract import P_FLOOR
from gridsim_core.physics import simulate
from gridsim_core.task import battery_of


@settings(max_examples=300, deadline=None)
@given(tasks(), st.data())
def test_truncation(task, data):
    b = battery_of(task)
    acts = data.draw(st.lists(st.integers(-b.k_ch - 2, b.k_dis + 2), min_size=24, max_size=24))
    sim = simulate(task, acts)
    cut = sim["truncated_at"]
    if cut is None:
        assert sim["executed"] == acts and sim["feasible"]
        return
    assert not sim["feasible"] and sim["violation"] in {"rate", "soc_below_0", "soc_above_N", "cycle_cap"}
    assert sim["executed"][:cut] == acts[:cut] and sim["executed"][cut:] == [0] * (24 - cut)
    prefix = simulate(task, acts[:cut] + [0] * (24 - cut))
    assert prefix["cashflow"] == sim["cashflow"] and prefix["feasible"]
    assert sim["soc_path"][cut:] == [sim["soc_path"][cut]] * (25 - cut)


def test_violation_kinds():
    t = {"prices": [10.0] * 24, "battery": {"unit_mwh": 1, "k_dis": 2, "k_ch": 2, "soc_levels": 4, "eta": 0.9,
                                            "c_deg": 0, "cycle_cap_units": 3, "s0": 2, "s_end_min": 0}}
    assert simulate(t, [3] + [0] * 23)["violation"] == "rate"
    assert simulate(t, [-3] + [0] * 23)["violation"] == "rate"
    assert simulate(t, [2, 1] + [0] * 22)["violation"] == "soc_below_0"
    assert simulate(t, [-2, -1] + [0] * 22)["violation"] == "soc_above_N"
    sim = simulate(t, [2, -2, 2] + [0] * 21)
    assert sim["violation"] == "cycle_cap" and sim["truncated_at"] == 2 and sim["soc_path"][-1] == 2


@settings(max_examples=300, deadline=None)
@given(tasks(), st.data())
def test_shortfall_repair_pays(task, data):
    b = battery_of(task)
    assume(b.s_end_min > 0)
    sched = baselines.random_feasible(task, data.draw(st.integers(0, 10**6)))
    short = list(sched)
    for h in range(23, -1, -1):
        while short[h] < b.k_dis and simulate(task, short)["soc_path"][-1] >= b.s_end_min:
            trial = short[:h] + [short[h] + 1] + short[h + 1:]
            if not simulate(task, trial)["feasible"]:
                break
            short = trial
    s_short = simulate(task, short)
    assume(s_short["end_shortfall_units"] > 0 and s_short["feasible"])
    fixed = list(short)
    for h in range(23, -1, -1):
        while simulate(task, fixed)["end_shortfall_units"] and fixed[h] > -b.k_ch:
            trial = fixed[:h] + [fixed[h] - 1] + fixed[h + 1:]
            if not simulate(task, trial)["feasible"]:
                break
            fixed = trial
    s_fixed = simulate(task, fixed)
    assume(s_fixed["end_shortfall_units"] < s_short["end_shortfall_units"])
    assert s_fixed["profit_usd"] >= s_short["profit_usd"] - 1e-9
    pen_price = max(max(task["prices"]), P_FLOOR)
    if all(task["prices"][h] < pen_price for h in range(24) if fixed[h] != short[h]) and b.eta < 1:
        assert s_fixed["profit_usd"] > s_short["profit_usd"]


def test_nonpositive_day_penalty_uses_floor():
    t = {"prices": [-5.0] * 24, "battery": {"unit_mwh": 5, "k_dis": 2, "k_ch": 2, "soc_levels": 4, "eta": 0.9,
                                            "c_deg": 0, "cycle_cap_units": 4, "s0": 0, "s_end_min": 2}}
    sim = simulate(t, [0] * 24)
    assert sim["end_shortfall_units"] == 2 and abs(sim["penalty_usd"] - 2 * 5 / 0.9 * P_FLOOR) < 1e-9
    assert sim["profit_usd"] < 0


def test_cash_conventions():
    t = {"prices": [100.0] + [-20.0] + [0.0] * 22,
         "battery": {"unit_mwh": 25, "k_dis": 4, "k_ch": 4, "soc_levels": 8, "eta": 0.8, "c_deg": 4,
                     "cycle_cap_units": 8, "s0": 4, "s_end_min": 0}}
    sim = simulate(t, [2, -2] + [0] * 22)
    assert sim["mwh"][:2] == [50.0, -62.5]
    assert sim["cashflow"][:2] == [100 * 50 - 4 * 50, -20 * -62.5]
    assert sim["degradation_usd"] == 200 and sim["soc_path"][:3] == [4, 2, 4]
