import random

import pytest
from conftest import load_fixtures, tasks
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from gridsim_core.advantage import hour_advantages
from gridsim_core.dp import dp_schedule
from gridsim_core.forecast_line import FORECAST_NOTE, forecast_line, parse_forecast, written
from gridsim_core.grade import foresight_refs
from gridsim_core.physics import settle
from gridsim_core.prompt import messages, system_prompt
from gridsim_core.task import battery_of

FIX = load_fixtures()
price = st.floats(-250, 5000, allow_nan=False)
forecasts = st.lists(price, min_size=24, max_size=24)


@settings(max_examples=300, deadline=None)
@given(forecasts)
def test_a_written_forecast_parses_back_to_the_prices_it_states(f):
    line = forecast_line(f)
    assert parse_forecast(line) == written(f)
    plan = 'Plan: buy HE03 (2 units, $19) -> 2/8.\n<tool_call>\n{"name": "submit_schedule", "arguments": ' \
           '{"actions": [0, -2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 0, 0, 0, 0, 0, 0]}}\n</tool_call>'
    assert parse_forecast(f"{line}\nStarts at 0/8.\n{plan}") == written(f)
    assert parse_forecast(f"Some thought 1, 2, 3.\n{line}\n{forecast_line([1] * 24)}") == written(f)


@settings(max_examples=100, deadline=None)
@given(st.lists(price, min_size=0, max_size=40))
def test_a_forecast_line_needs_exactly_24_numbers(f):
    assume(len(f) != 24)
    assert parse_forecast(forecast_line(f)) is None


@pytest.mark.parametrize(("text", "want"), [
    ("**Forecast:** $23, -$5, $1,200.5, " + ", ".join(["30"] * 21), [23, -5, 1200.5] + [30] * 21),
    ("Forecast ($/MWh, HE01-HE24): " + " ".join(str(h) for h in range(24)), list(range(24))),
    ("forecast = " + ", ".join(["-12.25"] * 24), [-12.25] * 24),
    ("<think>Forecast: 1, 2</think>\nForecast: " + ", ".join(["7"] * 24), [7] * 24),
    ("No forecast here: " + ", ".join(["7"] * 24), None),
    ("Forecast: " + ", ".join(["7"] * 23), None),
    ("", None),
])
def test_forecast_line_forms(text, want):
    got = parse_forecast(text)
    assert got == (None if want is None else [float(x) for x in want])


@settings(max_examples=200, deadline=None)
@given(tasks(), forecasts, st.integers(0, 10**6))
def test_advantages_on_the_written_forecast_vanish_on_its_dp_plan(task, f, seed):
    ref = foresight_refs(task)
    assume(ref["p_opt"] - ref["p_idle"] > 1e-6)
    w, b = written(f), battery_of(task)
    plan = dp_schedule(b, w)
    a = hour_advantages(task, plan, prices=w)
    assert all(abs(x) <= 1e-6 * max(1.0, abs(a["v0"])) for x in a["adv_usd"])
    assert a["opt"] == plan
    rng = random.Random(seed)
    other = list(plan)
    other[rng.randrange(24)] += rng.choice([-2, -1, 1, 2])
    o = hour_advantages(task, other, prices=w)
    tol = 1e-6 * max(1.0, abs(a["v0"]))
    assert all(x <= tol for x in o["adv_usd"])
    assert abs(sum(o["adv_usd"]) - (settle(b, w, other)["profit_usd"] - settle(b, w, plan)["profit_usd"])) <= 24 * tol


def test_fixture_dp_plans_on_their_written_forecasts():
    for t in [t for t in FIX if t.get("blind")]:
        w = written(t["blind"]["dam_prev_day"])
        plan = dp_schedule(battery_of(t), w)
        assert max(abs(x) for x in hour_advantages(t, plan, prices=w)["adv"]) <= 1e-6


def test_the_forecast_prompt_is_the_blind_prompt_plus_one_paragraph():
    t = next(t for t in FIX if t.get("blind"))
    assert system_prompt(t, "blind", 0, forecast=True) == system_prompt(t, "blind", 0) + "\n\n" + FORECAST_NOTE
    assert messages(t, "blind", 0, forecast=True)[1] == messages(t, "blind", 0)[1]
    with pytest.raises(ValueError):
        system_prompt(t, "foresight", 0, forecast=True)
