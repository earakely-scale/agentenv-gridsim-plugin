import pytest

from gridsim_core.desk import Session, fixtures, policies, refs
from gridsim_core.desk.data import build
from gridsim_core.desk.engine import Engine, site_of

D = "2026-02-14"


@pytest.fixture(scope="module")
def floor():
    return fixtures.make(D, seed=1, layer="v5")


def test_stack_reproduces_real_price_without_the_battery(floor):
    task, series = floor
    ser = build(task, series)
    e = Engine(site_of(task), ser, True, ancillary=True, impact=True)
    for h in range(24):
        assert e.stacks[0].clear(h, None, True)[0] == pytest.approx(ser.dam_spp[h], abs=0.02)
    assert e.ser is not ser and e.ser.dam_spp == ser.dam_spp


def test_selling_lowers_and_buying_raises_the_price(floor):
    task, series = floor
    e = Engine(site_of(task), build(task, series), True, ancillary=True, impact=True)
    st = e.stacks[0]
    for h in (3, 19):
        base = st.clear(h, None, True)[0]
        assert st.self_schedule(h, 100) < base < st.self_schedule(h, -100)
    price, mw = st.clear(19, [[-100, 0], [0, 0], [0, 40], [100, 40]], True)
    assert mw == pytest.approx(100) and price < e.ser.dam_spp[19]


def test_session_posts_the_recleared_price(floor):
    task, series = floor
    s = Session(task, series)
    s.start()
    s.call("submit_dam_offers", {"curves": [{"hours": "HE20", "points": [[0, -250], [100, -250]]}]})
    s.advance_to(-600)
    posted = s.call("get_prices", {"market": "dam"})["values"][19]
    assert posted < series["dam_spp"][D][19] - 0.5
    assert build(task, series).dam_spp[19] == series["dam_spp"][D][19]


def test_v5_grades(floor):
    r = refs.build_refs(*floor)
    assert r["p_hind"] >= r["p_anchor"]
    assert refs.grade(policies.run(*floor, "idle"), r)["reward"] == pytest.approx(0.2)
    assert refs.grade(policies.run(*floor, "anchor"), r)["reward"] == pytest.approx(1.0)
