import pytest

from gridsim_core.dp import solve_dp
from gridsim_core.grade import grade
from gridsim_core.lp import lp_bound
from gridsim_core.physics import simulate
from gridsim_core.task import make_battery, make_task


def test_golden_proposal_day():
    """100 MW / 200 MWh, q=25, eta=0.85, $4 degradation, 12 cycle units, s0 = s_end_min = N/2."""
    b = make_battery(100, 200, 4, eta=0.85, c_deg=4.0, cycles=1.5)
    assert (b["unit_mwh"], b["soc_levels"], b["cycle_cap_units"], b["s0"], b["s_end_min"]) == (25, 8, 12, 4, 4)
    t = make_task([10.0] * 4 + [30.0] * 12 + [100.0] * 4 + [30.0] * 4, b)
    p, s = solve_dp(t)
    assert p == pytest.approx(-4 * 25 / 0.85 * 10 + 8 * 25 * 96 - 4 * 25 / 0.85 * 30, abs=1e-9)
    assert p == pytest.approx(14494.117647, abs=1e-6)
    assert s == [0, 0, 0, -4] + [0] * 12 + [0, 0, 4, 4] + [0, 0, 0, -4]
    assert lp_bound(t) == pytest.approx(p, abs=1e-4)
    assert grade(t, s)["reward"] == 1.0 and grade(t, [0] * 24)["reward"] == 0.2


def test_golden_negative_day_end_obligation():
    """All prices <= 0 and s_end_min > s0: idle pays the $50 floor; the optimum is paid to charge."""
    b = make_battery(10, 20, 2, eta=0.9, c_deg=0.0, cycles=1.0, s0=0, s_end_min=2)
    assert (b["unit_mwh"], b["soc_levels"], b["cycle_cap_units"]) == (5, 4, 4)
    t = make_task([-5.0] * 9 + [-20.0] * 2 + [-5.0] * 13, b)
    assert simulate(t, [0] * 24)["profit_usd"] == pytest.approx(-2 * 5 / 0.9 * 50)
    p, s = solve_dp(t)
    assert p == pytest.approx(4100 / 9, abs=1e-9)
    sim = simulate(t, s)
    assert sim["feasible"] and sim["soc_path"][-1] == 4 and sum(max(a, 0) for a in s) == 4
    assert sum(-a for a in s if a < 0) == 8 and s[9] == s[10] == -2


def test_golden_cycle_cap_asymmetric():
    """30 MW discharge / 20 MW charge, 40 MWh, eta 0.8, $8 degradation, 1 cycle, starts full."""
    b = make_battery(30, 40, 3, k_ch=2, eta=0.8, c_deg=8.0, cycles=1.0, s0=4, s_end_min=0)
    assert (b["unit_mwh"], b["soc_levels"], b["cycle_cap_units"], b["p_ch_mw"]) == (10, 4, 4, 20)
    prices = [20.0] * 24
    prices[7], prices[18] = 200.0, 150.0
    t = make_task(prices, b)
    p, s = solve_dp(t)
    assert p == pytest.approx(3 * 10 * 192 + 10 * 142)
    assert s == [0] * 7 + [3] + [0] * 10 + [1] + [0] * 5
    over = list(s)
    over[20] = -1
    over[21] = 1
    assert simulate(t, over)["violation"] == "cycle_cap"
