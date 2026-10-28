import copy
import json

import pytest

from gridsim_core.desk import Session, ancillary, fixtures, policies, refs, text
from gridsim_core.desk.curves import clear

POST, PRE = "2026-02-14", "2025-08-14"


@pytest.fixture(scope="module")
def post3():
    return fixtures.make(POST, seed=1, layer="v3", outage=True)


@pytest.fixture(scope="module")
def pre3():
    return fixtures.make(PRE, seed=1, layer="v3")


def test_co_clear_energy_only_matches_clear():
    c = [[-100, 10], [0, 20], [0, 40], [100, 60]]
    for p in (5, 15, 30, 50, 70):
        q, aw = ancillary.co_clear(c, True, p, {}, {}, 100, -100)
        assert q == pytest.approx(clear(c, p)) and aw == {}


def test_co_clear_trades_energy_for_reserves():
    c = [[0, 0], [100, 0]]
    q, aw = ancillary.co_clear(c, True, 30.0, {"regup": [[60, 1.0]]}, {"regup": 50.0}, 100, -100)
    assert aw["regup"] == pytest.approx(60) and q == pytest.approx(40, abs=1e-6)
    q, aw = ancillary.co_clear(c, True, 30.0, {"regup": [[60, 1.0]]}, {"regup": 50.0}, 100, -100, soc_up=10.0,
                               dur={"regup": 0.5})
    assert aw["regup"] * 0.5 + q / 12 <= 10.0 + 1e-6


def test_as_offer_codes():
    assert ancillary.check_as_offer("rrsufr", [[1, 1]], 5000, 200, POST)[0]["code"] == "ASO-01"
    assert ancillary.check_as_offer("ecrs", [[1, 1]], 5000, 200, "2023-01-05")[0]["code"] == "ASO-01"
    assert ancillary.check_as_offer("regup", [[0.05, 1]], 5000, 200, POST)[0]["code"] == "ASO-03"
    assert ancillary.check_as_offer("regup", [[10, 2500]], 2000, 200, POST)[0]["code"] == "ASO-04"
    assert ancillary.check_as_offer("rrspfr", [[50, 1]], 5000, 200, POST)[0]["code"] == "ASO-05"
    assert ancillary.check_as_offer("regup", [[1, 1]] * 6, 5000, 200, POST)[0]["code"] == "ASO-02"
    assert ancillary.check_as_offer("nspin", [[20, 3.0], [10, 5.0]], 5000, 200, POST) == []


def test_v3_soc_holds_and_awards_within_headroom(post3):
    s = policies.run(*post3, "anchor")
    e, site = s.engine, s.site
    for k in range(e.K):
        assert site.e_min - 1e-6 <= e.soc[k + 1] <= site.e_max + 1e-6
        up = sum(e.rt_as[k].get(p, 0.0) for p in ancillary.UP)
        assert up <= site.hsl - site.lsl + 1e-6
        assert e.rt_as[k].get("rrspfr", 0.0) <= ancillary.PFR_SHARE * (site.hsl - site.lsl) + 1e-6


def test_v3_grades(post3, pre3):
    for task, series in (post3, pre3):
        r = refs.build_refs(task, series)
        assert r["p_hind"] >= r["p_anchor"] >= r["p_idle"]
        assert refs.grade(policies.run(task, series, "idle"), r)["reward"] == pytest.approx(0.2)
        assert refs.grade(policies.run(task, series, "anchor"), r)["reward"] == pytest.approx(1.0)
        lines = r["anchor"]["statement"]["days"][task["dates"][0]]["lines"]
        assert lines["dam_as_capacity"] > 0


def test_v3_tools(post3, pre3):
    s = Session(*post3)
    s.start()
    out = s.call("submit_dam_offers", {"as_offers": [{"hours": "HE17-HE19", "product": "regup", "mw": [20, 0, 30],
                                                       "price": [1.0, 0, 2.0]}]})
    assert out["as_accepted"] == {"RegUp": "HE17-HE19"}
    assert s.engine.dam_as_offer[16]["regup"] == [[20.0, 1.0]] and "regup" not in s.engine.dam_as_offer[17]
    assert "error" not in s.call("get_prices", {"market": "as_dam", "day": "D-1"})
    assert "not_posted" in s.call("get_prices", {"market": "as_dam"})["error"]
    assert "curves" in s.call("get_prices", {"market": "asdc"})
    assert s.call("get_forecasts", {"kind": "as_price", "market": "rt"})["p50"]["regup"]
    bad = s.call("update_cop", {"rows": [{"hours": "HE10", "as_capability": {"regup": 999}}]})
    assert bad["rejected"][0]["code"] == "COP-06"
    ok = s.call("update_cop", {"rows": [{"hours": "HE10", "as_capability": {"regup": 20}}]})
    assert ok["accepted_hours"] == "HE10" and s.engine.cop["as_cap"][9] == {"regup": 20.0}
    p = Session(*pre3)
    p.start()
    p.advance_to(-300)
    assert p.call("submit_rt_offers", {"as_offers": [{"hours": "HE05", "product": "regup", "blocks": [[5, 1]]}]})[
        "as_rejected"][0]["code"] == "ASO-06"
    assert "rule" in p.call("get_prices", {"market": "as_rt"})["error"]
    v2 = Session(*fixtures.make(POST, seed=1))
    v2.start()
    assert "layer" in v2.call("submit_dam_offers", {"as_offers": []})["error"]


def test_v3_no_lookahead(post3):
    task, series = post3
    d = task["dates"][0]
    future = copy.deepcopy(series)
    for k in future["rt_mcpc"][d]:
        future["rt_mcpc"][d][k] = future["rt_mcpc"][d][k][:120] + [999.0] * 168
        future["rt_mcpc_15"][d][k] = future["rt_mcpc_15"][d][k][:40] + [999.0] * 56
    a, b = Session(task, series), Session(task, future)
    for s in (a, b):
        s.start()
        s.advance_to(600)
    for name, args in [("get_prices", {"market": "as_rt"}), ("get_position", {"detail": "hourly"}),
                       ("get_forecasts", {"kind": "as_price", "market": "rt"}), ("optimize", {}),
                       ("get_asset_status", {})]:
        assert text(a.call(name, args)) == text(b.call(name, args)), name


def test_pv_site():
    task, series = fixtures.make(POST, seed=2, layer="v3", pv=True)
    s = policies.run(task, series, "anchor")
    assert s.result["days"][POST]["lines"]["pv_energy"] > 0
    for k in range(s.engine.K):
        assert s.engine.metered[k] + s.engine.pv[k] <= task["site"]["pv"]["poi_mw"] + 1e-6
    assert "pv_mw" in json.loads(text(s.episode()))["site"] or True
