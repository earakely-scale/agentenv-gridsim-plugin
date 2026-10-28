import copy
import json

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridsim_core.desk import TOOL_SPECS, TOOLS, Session, clock, fixtures, policies, refs, system_prompt, text
from gridsim_core.desk.curves import check_eboc, check_side, clear, clear_pre, reduce
from gridsim_core.desk.data import build
from gridsim_core.desk.engine import Engine, site_of

POST, PRE = "2026-02-14", "2025-08-14"


@pytest.fixture(scope="module")
def post():
    return fixtures.make(POST, seed=1, outage=True)


@pytest.fixture(scope="module")
def pre():
    return fixtures.make(PRE, seed=1)


@pytest.fixture(scope="module")
def post_refs(post):
    return refs.build_refs(*post)


def test_clock_parsing():
    d0 = POST
    assert clock.parse_time("D-1 10:00", d0) == clock.DAM_CLOSE
    assert clock.parse_time("14:35", d0, 0) == 875
    assert clock.parse_time("HE07", d0, 1) == 1440 + 360
    assert clock.parse_time("2026-02-13T13:30:00-06:00", d0) == clock.DAM_RESULTS
    assert clock.parse_hours("HE07-HE10") == [7, 8, 9, 10]
    assert clock.parse_hours([3, "HE05"]) == [3, 5]
    assert clock.parse_hours("all") == list(range(1, 25))
    assert clock.hours_label([1, 2, 3, 7, 9, 10]) == "HE01-HE03,HE07,HE09-HE10"
    with pytest.raises(clock.TimeError):
        clock.parse_hours("HE25")
    assert clock.label(clock.START, d0) == "Fri 02-13 06:00"


def test_eboc_codes():
    ok = [[-100, 10], [0, 20], [0, 40], [100, 60]]
    assert check_eboc(ok, 2000, -100, 100) == ([], [])
    codes = lambda pts, cap=2000: {e["code"] for e in check_eboc(pts, cap, -100, 100)[0]}  # noqa: E731
    assert codes([[0, 10]]) == {"EBOC-01"}
    assert "EBOC-02" in codes([[0, 30], [50, 20]])
    assert "EBOC-03" in codes([[0, 10], [10, 10], [20, 10]])
    assert "EBOC-04" in codes([[0, 10], [10, 2500]])
    assert "EBOC-04" not in codes([[0, 10], [10, 2500]], cap=5000)
    assert "EBOC-05" in codes([[-150, 10], [0, 20]])
    assert {e["code"] for e in check_side([[0, 30], [50, 20]], 5000, 100, "offer")} == {"GOC-03"}
    assert check_side([[0, 30], [50, 20]], 5000, 100, "bid") == []


def test_clear_examples():
    c = [[-100, 10], [0, 20], [0, 40], [100, 60]]
    assert clear(c, 5) == -100
    assert clear(c, 15) == pytest.approx(-50)
    assert clear(c, 30) == 0
    assert clear(c, 50) == pytest.approx(50)
    assert clear(c, 70) == 100
    assert clear([[20, 30], [50, 40]], 10) == 0
    assert clear([[-50, 10], [-20, 20]], 25) == 0
    assert clear_pre({"offer": [[0, 40], [100, 60]], "bid": [[0, 20], [100, 10]]}, 5) == -100
    assert clear_pre({"offer": [[0, 40], [100, 60]], "bid": [[0, 20], [100, 10]]}, 60) == 100


curve_st = st.lists(st.tuples(st.floats(-100, 100), st.floats(-250, 2000)), min_size=2, max_size=6).map(
    lambda pts: reduce(sorted((q, p) for q, p in zip(sorted(q for q, _ in pts), sorted(p for _, p in pts),
                                                        strict=True))))


@given(curve_st, st.floats(-300, 2500), st.floats(-300, 2500))
@settings(max_examples=200, deadline=None)
def test_clear_monotone(curve, p1, p2):
    if len(curve) < 2:
        return
    lo, hi = sorted((p1, p2))
    assert clear(curve, lo) <= clear(curve, hi) + 1e-9
    qs = [q for q, _ in curve] + [0.0]
    assert min(qs) - 1e-9 <= clear(curve, lo) <= max(qs) + 1e-9


@given(st.lists(curve_st, min_size=24, max_size=24), st.integers(0, 5))
@settings(max_examples=25, deadline=None)
def test_engine_soc_bounds(curves, seed):
    task, series = fixtures.make(POST, seed=seed, notices=False, operator=False, desk_forecast=False,
                                 outage=seed % 2 == 0)
    ser, site = build(task, series), site_of(task)
    e = Engine(site, ser, True)
    for h, c in enumerate(curves):
        e.dam_curve[h] = c if len(c) >= 2 else None
    e.advance(ser.end)
    for k in range(e.K):
        assert site.e_min - 1e-6 <= e.soc[k + 1] <= site.e_max + 1e-6
        assert site.lsl - 1e-9 <= e.bp[k] <= site.hsl + 1e-9
        if k:
            assert abs(e.bp[k] - e.bp[k - 1]) <= 5 * site.ramp + 1e-6 or e.event_limits(5 * k)[2] is not None \
                or e.event_limits(5 * k - 5)[2] is not None


def test_idle_anchor_hindsight(post, post_refs):
    r = post_refs
    assert r["p_idle"] == 0.0
    assert r["p_hind"] >= r["p_hind_phys"] - 1e-6
    assert r["p_hind"] >= r["p_anchor"]
    assert r["p_anchor"] > 0
    g_idle = refs.grade(policies.run(*post, "idle"), r)
    assert g_idle["valid"] and g_idle["reward"] == pytest.approx(0.2)
    g_anchor = refs.grade(policies.run(*post, "anchor"), r)
    assert g_anchor["reward"] == pytest.approx(1.0) and g_anchor["p"] == pytest.approx(r["p_anchor"])
    s = Session(*post)
    w = s.start()
    while w:
        w = s.end_turn()
    assert refs.grade(s, r)["reward"] == 0.0


def test_operator_rows_match(post):
    rep, act = refs.operator_replay(*post), refs.operator_actual(*post)
    assert rep["p"] == pytest.approx(act["p"], abs=0.05)


def test_pre_era(pre):
    task, series = pre
    assert task["era"] == "pre"
    r = refs.build_refs(task, series)
    assert refs.grade(policies.run(task, series, "idle"), r)["reward"] == pytest.approx(0.2)
    s = Session(task, series)
    s.start()
    out = s.call("submit_dam_offers", {"curves": [{"hours": "all", "points": [[0, 10], [50, 20]]}]})
    assert out["rejected"][0]["code"] == "GOC-00"
    out = s.call("submit_dam_offers", {"curves": [{"hours": "HE18-HE20", "offer": [[0, 40], [100, 60]]},
                                                  {"hours": "HE02-HE04", "bid": [[0, 30], [100, 20]]}]})
    assert out["accepted_hours"] == "HE02-HE04,HE18-HE20"
    s.advance_to(-60)
    out = s.call("submit_rt_offers", {"curves": [{"hours": "HE01", "offer": [[0, 40], [100, 60]],
                                                  "bid": [[0, 30], [100, 20]]}]})
    assert out["accepted_hours"] == "HE01" and out["rejected"][0]["code"] == "LRB-05"


def test_windows_and_budgets(post):
    s = Session(*post)
    w = s.start()
    assert w["reasons"] == ["start"] and w["budget"]["turns_left"] == 39
    board = [e for e in w["events"] if e["kind"] == "notice"]
    assert len(board) == 1 and board[0]["board"]
    assert "not_posted" in s.call("get_prices", {"market": "dam"})["error"]
    assert s.call("get_prices", {"market": "dam", "day": "D-1"})["values"]
    rt = s.call("submit_rt_offers", {"curves": [{"hours": "HE10", "points": [[0, 10], [10, 20]]}]})
    assert rt["rejected"][0]["code"] == "EBOC-06"
    for _ in range(s.budget["calls_per_turn"] - 3):
        s.call("get_asset_status")
    assert "budget" in s.call("get_asset_status")["error"]
    w = s.end_turn()
    assert w["reasons"] == ["dam_results"]
    late = s.call("submit_dam_offers", {"curves": [{"hours": "all", "points": [[0, 10], [10, 20]]}]})
    assert late["rejected"][0]["code"] == "EBOC-06"
    assert s.call("get_prices", {"market": "dam"})["values"]
    assert s.call("set_reminder", {"at": "D0 03:02", "note": "check"})["at"] == "Sat 02-14 03:05"
    nxt = s.next_wakeup()
    assert nxt["reasons"] == ["druc"] or nxt["at"] <= clock.ADJ_OPEN
    labels = []
    while w:
        labels.append((w["now"], tuple(w["reasons"])))
        w = s.end_turn()
    assert ("Sat 02-14 03:05", ("reminder",)) in labels
    assert ("Sat 02-14 14:02", ("outage",)) in labels


def test_no_lookahead(post):
    """Tool outputs at time t never change when prices after t change."""
    task, series = post
    s1 = Session(task, series)
    s1.start()
    s1.advance_to(600)
    future = copy.deepcopy(series)
    d = task["dates"][0]
    future["rt_lmp"][d] = future["rt_lmp"][d][:120] + [x + 500 for x in future["rt_lmp"][d][120:]]
    future["rt_spp"][d] = future["rt_spp"][d][:40] + [x + 500 for x in future["rt_spp"][d][40:]]
    future["system"][d]["prc_mw"] = future["system"][d]["prc_mw"][:120] + [0.0] * 168
    s2 = Session(task, future)
    s2.start()
    s2.advance_to(600)
    for name, args in [("get_prices", {"market": "rt"}), ("get_prices", {"market": "sced"}),
                       ("get_grid_conditions", {}), ("get_asset_status", {}), ("get_position", {"detail": "hourly"}),
                       ("get_forecasts", {"kind": "price", "market": "rt"}), ("optimize", {"price_view": "desk"})]:
        assert s1.call(name, args) == s2.call(name, args), name


def test_optimize_proposals_validate(post):
    s = Session(*post)
    s.start()
    out = s.call("optimize", {"price_view": "desk", "risk": 0.5})
    assert out["dam_curves"] and out["cop"] and "error" not in out
    for g in out["dam_curves"]:
        assert check_eboc(g["points"], 5000, -100, 100)[0] == []
    chk = s.call("check_submission", {"kind": "dam", "payload": {"curves": [
        {"hours": g["hours"], "points": g["points"]} for g in out["dam_curves"]]}})
    assert chk["ok"] and chk["would_clear_at_desk_p50"]
    custom = s.call("optimize", {"price_view": {"dam": [30.0] * 24, "rt": [30.0] * 24}})
    assert "error" not in custom
    assert "error" in s.call("optimize", {"price_view": {"dam": [1, 2, 3]}})


def test_cop_rules(post):
    s = Session(*post)
    s.start()
    ok = s.call("update_cop", {"rows": [{"hours": "HE01-HE03", "hbsoc_mwh": [80, 150, 100]}]})
    assert ok["accepted_hours"] == "HE01-HE03"
    bad = s.call("update_cop", {"rows": [{"hours": "HE05", "hbsoc_mwh": 250}]})
    assert bad["rejected"][0]["code"] == "COP-02"
    ramp = s.call("update_cop", {"rows": [{"hours": "HE06-HE07", "hbsoc_mwh": [20, 190]}]})
    assert ramp["rejected"][0]["code"] == "COP-03"
    st_ = s.call("update_cop", {"rows": [{"hours": "HE10", "status": "OFF"}]})
    assert st_["rejected"][0]["code"] == "COP-01"


def test_episode_json(post):
    s = policies.run(*post, "anchor")
    ep = s.episode(policy={"kind": "anchor"}, grade=refs.grade(s))
    txt = json.dumps(ep)
    assert ep["schema"] == "gridsim.desk.episode/v1" and len(ep["rt"][POST]["soc_mwh"]) == 289
    assert "FIXTURE_RN" not in txt and "FIXTURE_ESR1" not in txt


def test_tool_specs_and_output_sizes(post):
    assert [t["function"]["name"] for t in TOOL_SPECS] == list(TOOLS)
    s = policies.run(*post, "anchor")
    for t in s.turns:
        for c in t["calls"]:
            if c["tool"] != "optimize":
                assert len(json.dumps(c["result"])) < 4000, c["tool"]


def test_gateway_path_matches_turn_path(post):
    a = policies.run(*post, "anchor")
    s = Session(*post)
    w = s.start()
    while w is not None:
        policies.anchor(s, w)
        s.close_turn(None)
        nxt = s.call("next_wakeup", {}, role="hook")
        w = s.advance_to(nxt["at"]) if nxt["at"] is not None else None
    s.finish()
    assert s.result == a.result
    assert [x["reasons"] for x in s.wakes] == [x["reasons"] for x in a.wakes]


def test_replay_is_deterministic(post):
    a = policies.run(*post, "scripted")
    b = Session(*post)
    b.start()
    for t in a.turns:
        for c in t["calls"]:
            b.call(c["tool"], c["args"])
        b.end_turn(t["text"])
    assert b.done and b.result == a.result


def test_prompt_and_text(post, pre):
    p = system_prompt(post[0], "v2")
    assert "RTC+B" in p and "FIXTURE" not in p and p == system_prompt(Session(*post))
    assert "combo model" in system_prompt(pre[0])
    assert text({"a": "é", "b": [1, 2]}) == '{"a":"é","b":[1,2]}'


def test_no_lookahead_into_the_day_before(post):
    task, series = post
    dm1 = clock.date_of(-1, task["dates"][0])
    future = copy.deepcopy(series)
    future["rt_spp"][dm1] = future["rt_spp"][dm1][:24] + [x + 900 for x in future["rt_spp"][dm1][24:]]
    future["rt_lmp"][dm1] = future["rt_lmp"][dm1][:72] + [x + 900 for x in future["rt_lmp"][dm1][72:]]
    a, b = Session(task, series), Session(task, future)
    for s in (a, b):
        s.start()
    for args in ({"market": "rt", "day": "D-1", "step": "15m"}, {"market": "sced", "day": "D-1", "step": "5m"}):
        ra, rb = a.call("get_prices", args), b.call("get_prices", args)
        assert ra == rb and len(ra["values"]) < (96 if args["market"] == "rt" else 288)
    assert a.call("optimize", {}) == b.call("optimize", {})


def test_unit_event_hidden_until_it_starts():
    task, series = fixtures.make(POST, seed=4, notices=False)
    d0 = task["dates"][0]
    series["unit_events"] = [{"kind": "forced_outage", "start": clock.to_iso(-240, d0), "end": clock.to_iso(600, d0),
                              "hsl_mw": 0.0, "lsl_mw": 0.0, "source": "t"}]
    clean = fixtures.make(POST, seed=4, notices=False)[1]
    a, b = Session(task, series), Session(task, clean)
    for s in (a, b):
        s.start()
    assert a.call("get_asset_status") == b.call("get_asset_status")
    assert a.call("optimize", {}) == b.call("optimize", {})


def test_malformed_arguments_come_back_as_errors():
    task, series = fixtures.make(POST, seed=1, layer="v3")
    s = Session(task, series)
    s.start()
    bad = [("submit_dam_offers", {"curves": [{"hours": "HE01", "points": [[0, "x"], [10, 20]]}]}),
           ("submit_rt_offers", {"curves": [{"hours": "HE01", "points": [[0, 1, 2], [10, 20]]}]}),
           ("check_submission", {"kind": "dam", "payload": {"curves": [{"hours": "HE01", "points": [[0, "x"]]}]}}),
           ("optimize", {"constraints": {"max_cycles": "lots"}}),
           ("optimize", {"constraints": {"end_soc_mwh": [1]}}),
           ("optimize", {"price_view": {"scenarios": ["x"]}}),
           ("optimize", {"price_view": {"scenarios": [{"dam": [30] * 24, "weight": "w"}]}}),
           ("get_prices", {"market": "rt", "day": "D-1x"}),
           ("submit_dam_offers", {"as_offers": [{"hours": "HE01", "product": "regup", "mw": ["a"], "price": [1]}]}),
           ("update_cop", {"rows": [{"hours": "HE05", "as_capability": "x"}]}),
           ("set_reminder", {"at": {"x": 1}})]
    for name, args in bad:
        out = s.call(name, args)
        rejected = out.get("rejected") or out.get("as_rejected")
        assert "error" in out or rejected, (name, args, out)
    assert not s.done


def test_reward_floor():
    assert refs.desk_reward(0.0, 0.0, -5000.0, 50000.0) == (pytest.approx(0.2), True)
    r, floored = refs.desk_reward(2500.0, 0.0, -5000.0, 50000.0)
    assert floored and r == pytest.approx(0.6)
    assert refs.desk_reward(10000.0, 0.0, 10000.0, 50000.0) == (pytest.approx(1.0), False)
    assert refs.desk_reward(0.0, 0.0, 0.0, 0.0) == (1.0, False)


def _labels(obj, out):
    if isinstance(obj, dict):
        for v in obj.values():
            _labels(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _labels(v, out)
    elif isinstance(obj, str) and clock._LABEL.match(obj):
        out.append(obj)


def test_every_shown_time_is_accepted_back(post):
    s = policies.run(*post, "anchor")
    shown = []
    _labels(s.wakes, shown)
    for t in s.turns:
        _labels(t["wake"], shown)
        for c in t["calls"]:
            _labels(c["result"], shown)
    _labels(s.events, shown)
    assert len(shown) > 50
    d0 = post[0]["dates"][0]
    for v in set(shown):
        assert clock.label(clock.parse_time(v, d0), d0) == v
    with pytest.raises(clock.TimeError):
        clock.parse_time("Mon 02-14 09:00", d0)
    r = Session(*post)
    r.start()
    assert r.call("set_reminder", {"at": "Fri 02-13 09:30"})["at"] == "Fri 02-13 09:30"
    assert r.call("set_reminder", {"at": "02-14 07:00"})["at"] == "Sat 02-14 07:00"


@pytest.mark.parametrize("now,hour", [(270, "HE07"), (630, "HE13"), (1160, "HE22")])
def test_deadline_names_the_next_open_freeze(post, now, hour):
    s = Session(*post)
    s.start()
    s.advance_to(now)
    cop = next(d for d in s._deadlines() if d["what"].startswith("COP"))
    assert hour in cop["what"] and clock.parse_time(cop["at"], s.d0) > now


def test_hourly_load_posts_after_the_hour():
    task, series = fixtures.make(POST, seed=1, notices=False)
    d0 = task["dates"][0]
    hourly = [series["system"][d0]["load_mw"][12 * h] for h in range(24)]
    series["system"][d0]["load_mw"] = [hourly[k // 12] for k in range(288)]
    future = copy.deepcopy(series)
    future["system"][d0]["load_mw"] = [x if k < 12 * 11 else x + 9999 for k, x in enumerate(
        future["system"][d0]["load_mw"])]
    a, b = Session(task, series), Session(task, future)
    for s in (a, b):
        s.start()
        s.advance_to(11 * 60 + 30)
    ga, gb = a.call("get_grid_conditions"), b.call("get_grid_conditions")
    assert ga == gb and ga["load_mw"]["step"] == "1h" and ga["load_mw"]["last_hour"].startswith("HE11")
