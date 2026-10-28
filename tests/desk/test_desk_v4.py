import pytest

from gridsim_core.desk import Session, clock, fixtures, policies, refs
from gridsim_core.desk import forecast as fcm


@pytest.fixture(scope="module")
def front():
    return fixtures.make("2026-02-14", seed=2, layer="v4", days=3, outage=True)


def test_three_day_clock(front):
    s = policies.run(*front, "anchor")
    reasons = {(w["t"], tuple(w["reasons"])) for w in s.wakes}
    assert (clock.DAY + clock.START, ("checkpoint", "dam_morning")) in reasons
    assert (2 * clock.DAY + clock.START, ("checkpoint", "dam_morning")) in reasons
    assert len(s.result["days"]) == 3 and s.budget["max_turns"] == 100
    assert all(s.engine.dam_award[H] is not None for H in range(72))


def test_dam_windows_per_day(front):
    s = Session(*front)
    s.start()
    c = [{"hours": "all", "points": [[0, -250], [0, 2000]]}]
    assert s.call("submit_dam_offers", {"day": "D2", "curves": c})["accepted_hours"] == "HE01-HE24"
    s.advance_to(clock.DAY + clock.DAM_CLOSE - 5)
    assert s.call("submit_dam_offers", {"day": "D1", "curves": c})["accepted_hours"] == "HE01-HE24"
    assert s.call("submit_dam_offers", {"day": "D0", "curves": c})["rejected"][0]["code"] == "EBOC-06"
    s.advance_to(clock.DAY + clock.DAM_CLOSE)
    assert s.call("submit_dam_offers", {"day": "D1", "curves": c})["rejected"][0]["code"] == "EBOC-06"
    assert "values" in s.call("get_prices", {"market": "dam", "day": "D0"})
    assert "not_posted" in s.call("get_prices", {"market": "dam", "day": "D1"})["error"]


def test_dam_vintages_overlay(front):
    task, series = front
    s = Session(task, series)
    v = fcm.views(s.ser, s.fc, clock.START)
    later = fcm.views(s.ser, s.fc, clock.DAY + clock.START)
    d1 = [x for x in series["desk_forecast"] if x["market"] == "dam"][1]
    assert later["dam"].p50[24:48] == pytest.approx(d1["p50"][:24])
    assert v["dam"].p50[24:48] != pytest.approx(d1["p50"][:24])


def test_v4_grades(front):
    r = refs.build_refs(*front)
    assert r["p_hind"] >= r["p_anchor"] > r["p_idle"]
    assert refs.grade(policies.run(*front, "idle"), r)["reward"] == pytest.approx(0.2)
    assert refs.grade(policies.run(*front, "anchor"), r)["reward"] == pytest.approx(1.0)


def test_outage_before_the_window_is_in_the_initial_cop():
    task, series = fixtures.make("2026-02-14", seed=3, layer="v4", days=3, notices=False)
    d0 = task["dates"][0]
    series["unit_events"] = [{"kind": "forced_outage", "start": clock.to_iso(-5000, d0), "end": clock.to_iso(5000, d0),
                              "end_planned": clock.to_iso(1500, d0), "hsl_mw": 0.0, "lsl_mw": 0.0, "source": "t"}]
    s = Session(task, series)
    s.start()
    c = [{"hours": "all", "points": [[-100, -250], [100, -250]]}]
    for day in ("D0", "D1"):
        s.call("submit_dam_offers", {"day": day, "curves": c})
    s.finish()
    assert all(s.engine.dam_award[H] == 0 for H in range(24))
    assert s.engine.dam_award[30] == pytest.approx(100)
