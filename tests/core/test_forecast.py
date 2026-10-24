import copy
import json

import pytest

from gridsim_core import forecast as F
from gridsim_core import forecast_inputs as FI
from gridsim_core import forecast_prompt as P
from gridsim_core.task import load_pack

FIX = load_pack("fixtures-forecast")
BY_ID = {t["task_id"]: t for t in FIX}
T0 = FIX[0]


def scripted(s: F.Session):
    """Reads, asks for forecasts, bids each gate from the P50 guide, re-plans energy, advances."""
    s.call("get_situation")
    k = s.gate_day()
    if s.tier != "blind":
        s.call("get_forecast", {"kind": "price", "hours": 24})
        s.call("get_forecast", {"kind": "load"})
    if k is not None:
        plan = {"energy": [{"from": 1, "to": 5, "mw": -40}, {"from": 18, "to": 21, "mw": 60}]}
        if s.tier != "front-lite":
            plan["regdn"] = [{"from": 1, "to": 5, "mw": 20}]
        s.call("submit_dam", {"operating_day": s.day_date(k), "plan": plan, "pv_da_share": 0.8})
    elif 0 < s.first_open < s.H:
        fo = s.first_open
        s.call("check_schedule", {"plan": {"energy": [0] * (s.H - fo)}, "from_hour": fo})


def run(task, tier, policy):
    s = F.Session(task, tier)
    while not s.done:
        policy(s)
        s.call("advance")
        s.deliver_watch_notices()
    return s


def test_clock_constants():
    assert F.fixed_watches(3) == (-840, -600, -360, 0, 360, 600, 840, 1080, 1440, 1800, 2040, 2280, 2520, 2880, 3240,
                                  3960)
    assert F.fixed_watches(2) == (-840, -600, -360, 0, 360, 600, 840, 1080, 1440, 1800, 2520)
    assert [F.gate_minute(k) for k in range(3)] == [-840, 600, 2040]
    assert [F.results_minute(k) for k in range(3)] == [-630, 810, 2250]
    assert F.freeze_line(600) == 660 and F.freeze_line(600, "freeze-6h") == 960 and F.freeze_line(601) == 720
    assert F.to_minute("2025-02-18 24:00", "2025-02-18") == 1440 and F.to_minute("2025-02-17 10:00", "2025-02-18") == -840
    assert F.MAX_TURNS == {"front-lite": 72, "front": 122, "blind": 122, "freeze-6h": 122}


def test_inputs_points_and_reveal():
    assert len(FI.points()) == 18 and len(FI.zones()) == 8
    assert FI.site_point("HB_NORTH") == "DFW" and FI.zone_code("NORTH_C") == "NCEN"
    items = FI.reveal_doc()["items"]
    assert items["hrrr_run"]["minutes_after_cycle"] == FI.HRRR_ISSUE_MIN == 120
    assert {"eia_df", "da_spp", "notice", "ercot_posting"} <= set(items)


def test_synthetic_slice_is_deterministic_and_hashed():
    a, b = FI.synthetic_slice(T0), FI.synthetic_slice(T0)
    assert FI.vintages_sha(a["series"]) == FI.vintages_sha(b["series"]) == T0["vintages_sha"]
    for v in a["series"][:50]:
        assert v["sha"] == FI.vintage_sha(v["fields"])
    runs = {r["run_id"]: r for r in a["runs"]}
    for r in runs.values():
        assert (FI.parse_utc(r["issued_at"]) - FI.parse_utc(r["cycle"])).total_seconds() == 120 * 60


@pytest.mark.parametrize("task", FIX, ids=[t["task_id"][9:30] for t in FIX])
def test_anchor_reproduces_stored_reference(task):
    """The reference-solver test: the anchor replayed through a fresh, graded Session scores 1.0 (or the degenerate
    rule) and settles at the stored P_anchor to the cent, with a clean audit."""
    for tier in ("front", "front-lite"):
        a = F.play(task, tier, F.anchor_policy())
        tr = task["refs"][tier]
        assert round(a.profit(), 2) == round(tr["p_roll"], 2) == round(tr["p_anchor"], 2)
        s = F.Session(task, tier)
        for st in a.transcript:
            args = dict(st["args"]) | ({"_via": "trigger"} if st["tool"] == F.NOTICE_TOOL else {})
            s.call(st["tool"], args)
        g = s.grade()
        assert round(g["profit_usd"], 2) == round(tr["p_anchor"], 2)
        assert g["reward"] == (1.0 if tr["p_anchor"] - tr["p_idle"] > 1e-9 or g["profit_usd"] >= tr["p_anchor"] - 1e-6
                               else 0.0)
        assert not g["beats_anchor"]
        assert s.audit()["ok"], s.audit()["problems"]


def test_references_order_and_bounds():
    for t in FIX:
        for tier in F.TIERS:
            r = t["refs"][tier]
            assert r["p_hind"] >= r["p_roll"] - 1e-3 and r["p_hind"] >= r["p_idle"] - 1e-3
            assert r["p_lp"] >= r["p_hind"] - 1e-3
            assert set(r) >= {"p_idle", "p_anchor", "p_roll", "p_roll3", "p_blind", "p_naive", "p_hind", "p_lp"}
        assert t["refs"]["blind"]["p_anchor"] == t["refs"]["blind"]["p_blind"]
        assert t["refs"]["blind"]["p_roll"] == t["refs"]["front"]["p_roll"]


def test_no_action_scores_zero_and_zero_commit_scores_floor():
    s = run(T0, "front", lambda s: None)
    assert s.grade()["reward"] == 0.0 and s.grade()["dam_missed"] == 3
    assert round(s.profit(), 2) == round(T0["refs"]["front"]["p_idle"], 2)

    def zeros(s):
        if s.watch == 0:
            s.call("commit_schedule", {"plan": {"energy": [0] * s.H}, "from_hour": 0})

    z = run(T0, "front", zeros)
    assert z.grade()["submitted"] and z.grade()["reward"] == 0.2


def test_forecasts_are_served_as_issued():
    s = F.Session(T0, "front")
    out = json.loads(s.call("get_forecast", {"kind": "price", "hours": 6}))
    assert F.to_minute(out["issued_at"], s.d1) <= s.minute
    latest = max(r.minute for r in s.vint.all("price", T0["settlement_point"], s.minute))
    assert F.to_minute(out["issued_at"], s.d1) == latest
    late = json.loads(s.call("get_forecast", {"kind": "weather", "issued_at": "2025-02-17 11:00"}))
    assert "after now" in late["error"]
    old = json.loads(s.call("get_forecast", {"kind": "load", "issued_at": "2025-02-17 03:00"}))
    assert F.to_minute(old["issued_at"], s.d1) <= F.to_minute("2025-02-17 03:00", s.d1)
    assert out["da"]["known"][0] and out["da"]["p50"][0] == round(T0["history"]["dam"][-1][10], 2)
    for _ in range(5):
        s.call("get_forecast", {"kind": "wind"})
    assert "no forecast calls left" in json.loads(s.call("get_forecast", {"kind": "wind"}))["error"]
    assert s.audit()["ok"]


def test_audit_catches_a_tampered_vintage():
    t = copy.deepcopy(T0)
    s = F.Session(t, "front")
    s.call("get_forecast", {"kind": "price", "hours": 6})
    v = next(v for v in t["vintages"]["series"] if v["kind"] == "price" and v["issued_at"] == s.forecast_log[0][
        "issued_at"])
    v["fields"]["da_p50"][0] += 100
    assert any("does not match its sha" in p for p in s.audit()["problems"])


def test_da_prices_wait_for_dam_results():
    s = F.Session(T0, "front")
    sit = json.loads(s.call("get_situation"))
    assert sit["phase"] == "dam_gate" and all(d["da_usd"] is None for d in sit["days"])
    out = json.loads(s.call("advance"))
    s.deliver_watch_notices()
    assert out["time"].endswith("14:00") and out["dam_results"]["operating_day"] == T0["d1"]
    sit = json.loads(s.call("get_situation"))
    assert sit["days"][0]["da_usd"] is not None and sit["days"][1]["da_usd"] is None
    assert s.audit()["ok"]


def test_dam_gate_rules():
    s = F.Session(T0, "front")
    bad = json.loads(s.call("submit_dam", {"operating_day": "2025-02-19", "plan": {"energy": [0] * 24}}))
    assert "this gate takes the DAM for 2025-02-18" in bad["error"]
    over = json.loads(s.call("submit_dam", {"operating_day": T0["d1"], "plan": {"energy": [10] * 24}}))
    assert {x["rule"] for x in over["refused"]} == {"soc_empty"} and len(over["accepted"]) == 10
    ok = json.loads(s.call("submit_dam", {"operating_day": T0["d1"], "plan": {"energy": {"from": 0, "to": 8, "mw": 10}},
                                          "pv_da_share": 0}))
    assert len(ok["accepted"]) == 24 and ok["pv_da_mw"] == [0.0] * 24 and ok["x_da_mw"][:9] == [10.0] * 8 + [0.0]
    assert "no DAM submits left" in json.loads(s.call("submit_dam", {"operating_day": T0["d1"], "plan": {
        "energy": [0] * 24}}))["error"]
    s.call("advance")
    late = json.loads(s.call("submit_dam", {"operating_day": "2025-02-19", "plan": {"energy": [0] * 24}}))
    assert "only at the 10:00 DAM watch" in late["error"]
    lite = F.Session(T0, "front-lite")
    r = json.loads(lite.call("submit_dam", {"operating_day": T0["d1"], "plan": {"energy": [0] * 24,
                                                                                 "regup": [{"from": 0, "to": 2,
                                                                                            "mw": 10}]}}))
    assert {x["rule"] for x in r["refused"]} == {"not_offered"}


def test_blind_tier_withholds_forecasts():
    s = F.Session(T0, "blind")
    assert "withheld" in json.loads(s.call("get_forecast", {"kind": "price"}))["error"]
    assert json.loads(s.call("get_situation"))["latest_vintages"] is None
    front = F.Session(T0, "front")
    hrrr = set(F.hrrr_moves(T0, "front", front.vint))
    assert not {w.minute for w in s.watches} - set(F.fixed_watches(3)) - {
        n.reveal for n in (F.parse_notice(x, T0["d1"], 60) for x in F.events_of(T0))}
    assert hrrr and P.tool_schemas("blind")[1]["function"]["name"] == "check_schedule"


def test_scripted_agent_replays_and_writes_episode_v4():
    for tier in ("front", "front-lite", "blind", "freeze-6h"):
        s = run(T0, tier, scripted)
        assert s.audit()["ok"], (tier, s.audit()["problems"])
        ep = s.episode(bundle="test", path="B'", model="scripted")
        assert ep["schema"] == F.EPISODE_SCHEMA and ep["env"] == F.FORECAST_ENV and len(ep["hours"]) == s.H
        assert ep["dam"][0]["accepted"] and ep["vintages"]["series"] and ep["forecasts_served"] or tier == "blind"
        assert 0.0 <= ep["reward"] <= 1.0
        assert len(ep["watches"]) <= F.MAX_WATCHES[tier]


def test_notices_never_arrive_before_their_hour():
    for t in FIX:
        s = F.Session(t, "front")
        for w in s.watches:
            for n in w.notices:
                assert n.reveal % 60 == 0 and n.reveal <= w.minute
                assert n.reveal > w.minute - 1440 * 4


def test_prompt_and_schemas():
    text = P.system_prompt("front", "C", "ercot")
    assert "ERCOT's own forecasts" in text and "RTC+B" in text
    assert "Reserves" not in P.system_prompt("front-lite", "B")
    names = [x["function"]["name"] for x in P.tool_schemas("front")]
    assert names == ["get_situation", "get_forecast", "get_forecast_drift", "check_schedule", "commit_schedule",
                     "submit_dam", "advance"]
    s = F.Session(T0, "front")
    assert json.loads(P.situation_text(s))["task_id"] == T0["task_id"]
