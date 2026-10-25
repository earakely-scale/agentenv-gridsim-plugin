import json
import time

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from gridsim_core import hybrid as H
from gridsim_core import hybrid_prompt as HP

DATE_B, DATE_A, DATE_C = "2023-09-06", "2022-07-20", "2026-01-26"


def synth(date=DATE_B, site="arch-ac150", seed=1, neg=False, deploy=True, notices=True, **site_kw):
    rng = np.random.default_rng(seed)
    h = np.arange(24)
    da = 30 + 20 * np.sin((h - 8) / 24 * 2 * np.pi) + np.where((h >= 17) & (h <= 21), 120, 0) + rng.normal(0, 5, 24)
    if neg:
        da[10:15] = -15 - rng.uniform(0, 30, 5)
    rt = da + rng.normal(0, 15, 24)
    rt[19] += 600
    cf = np.clip(np.sin((h - 6.5) / 13 * np.pi), 0, None) * rng.uniform(0.8, 1.0)
    cf[(h < 7) | (h > 19)] = 0
    m = {"regup": 8 + rng.uniform(0, 6, 24), "regdn": 5 + rng.uniform(0, 5, 24),
         "rrs": 10 + rng.uniform(0, 8, 24) + np.where((h >= 17) & (h <= 21), 40, 0),
         "ecrs": 6 + rng.uniform(0, 6, 24) + np.where((h >= 17) & (h <= 21), 60, 0),
         "nspin": 3 + rng.uniform(0, 3, 24)}
    if H.as_era(date) == "A":
        m.pop("ecrs")
    deps = [{"event_id": "dep-rrs", "issued_at": f"{date}T19:25:00-05:00", "product": "rrs", "frac": 1.0,
             "start": f"{date}T19:25:00-05:00", "end": f"{date}T20:37:00-05:00", "level": "EEA2"},
            {"event_id": "dep-nspin", "issued_at": f"{date}T15:06:00-05:00", "product": "nspin", "frac": 1.0,
             "start": f"{date}T15:06:00-05:00", "end": f"{date}T21:04:00-05:00"}] if deploy else []
    ns = [{"event_id": "n-cons", "source": "ERCOT", "kind": "conservation", "level": "conservation",
           "issued_at": f"{date}T16:30:00-05:00", "name": "ERCOT", "title": "Conservation appeal",
           "text": "Conserve."}] if notices else []
    return H.make_task(date, "HB_WEST", H.make_site(site, **site_kw), np.round(da, 2), np.round(rt, 2), cf,
                       {k: np.round(v, 2) for k, v in m.items()}, notices=ns, deployments=deps)


@pytest.fixture(scope="module")
def day():
    t = synth()
    return t | {"refs": H.references(t)}


def agent(s: H.Session):
    """A scripted agent through call(): reads, checks, commits a block plan at watch 0, re-plans energy later."""
    s.call("get_situation")
    if s.watch == 0:
        plan = {"energy": [{"from": 0, "to": 6, "mw": -25}, {"from": 18, "to": 22, "mw": 50}],
                "regdn": [{"from": 0, "to": 6, "mw": 50}], "ecrs": {"from": 17, "to": 21, "mw": 25},
                "rrs": [{"from": 8, "to": 12, "mw": 25}]}
        s.call("check_schedule", {"plan": plan, "from_hour": 0})
        s.call("commit_schedule", {"plan": plan, "from_hour": 0})
    elif s.first_open < 24:
        fo = s.first_open
        s.call("commit_schedule", {"plan": {"energy": [0] * (24 - fo)}, "from_hour": fo})


def run(s: H.Session, policy) -> H.Session:
    while not s.done:
        policy(s)
        out = json.loads(s.call("advance"))
        if "watch" in out:
            s.deliver_watch_notices()
    return s


def test_plan_parsing():
    fh, f = H.parse_plan({"energy": "0 25, -50", "regup": [{"from": 21, "to": 24, "mw": 10}]}, "21:00")
    assert fh == 21 and f == {"energy": [0.0, 25.0, -50.0], "regup": [10.0, 10.0, 10.0]}
    assert H.parse_plan(json.dumps({"energy": [0] * 24}), 22)[1]["energy"] == [0.0, 0.0]
    assert H.parse_plan({"energy": {"from": 5, "to": 7, "mw": 30}}, 4)[1]["energy"][:4] == [0.0, 30.0, 30.0, 0.0]
    for bad, fh in [({"energy": [0] * 5}, 0), ({"regup": []}, 0), ({"energy": [0] * 24, "foo": 1}, 0),
                    ({"energy": [{"from": 2, "to": 5, "mw": 1}, {"from": 4, "to": 6, "mw": 1}]}, 0),
                    ({"energy": [{"from": 1, "to": 3, "mw": 1}]}, 2), ({"energy": [True] * 24}, 0),
                    ({"energy": [0] * 24}, 24), ("nope", 0)]:
        with pytest.raises(H.PlanError):
            H.parse_plan(bad, fh)


def test_keep_and_null_keep_an_as_field_and_the_parse_error_says_how(day):
    assert H.parse_plan({"energy": [0], "regdn": "keep"}, 23, keep=True)[1] == {"energy": [0.0]}
    with pytest.raises(H.PlanError):
        H.parse_plan({"energy": [0], "regdn": "keep"}, 23)
    s = H.Session(day, "reserves")
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regdn": {"from": 0, "to": 6, "mw": 10}}, "from_hour": 0})
    out = json.loads(s.call("check_schedule", {"plan": {"energy": [0] * 24, "regdn": " Keep "}, "from_hour": 0}))
    assert out["feasible"] and out["projected"]["as_usd"] > 0
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regdn": None, "rrs": "keep"},
                                                "from_hour": 0}))
    assert len(out["committed"]) == 24 and out["book"]["regdn"][:7] == [10] * 6 + [0]
    s = H.Session(day, "reserves")
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regdn": [0] * 25}, "from_hour": 0}))
    assert out["committed"] == [] and out["refused"][0]["rule"] == "parse"
    assert 'leave regdn out (or send "keep")' in out["refused"][0]["detail"]
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": "keep"}, "from_hour": 0}))
    assert "send its booked MW" in out["refused"][0]["detail"]
    assert 'send "keep" or null' in HP.system_prompt("reserves", "B")


def test_a_deployment_uses_up_its_duration():
    dur = {"regup": 1.0, "regdn": 1.0, "rrs": 1.0, "ecrs": 2.0, "nspin": 4.0}
    dep = [dict.fromkeys(H.EVENT_PRODUCTS, 0.0) for _ in range(24)]
    for h, f in ((17, 2 / 3), (18, 1.0), (19, 1 / 3)):
        dep[h]["ecrs"] = f
    du = H.deployed_durations(dur, dep)
    assert [du[h]["ecrs"] for h in (16, 17, 18, 19, 20)] == pytest.approx([2.0, 2.0, 4 / 3, 1 / 3, 2.0])
    assert all(d["rrs"] == 1.0 and d["nspin"] == 4.0 for d in du)
    t = synth(deploy=False) | {"deployments": [
        {"event_id": "dep-ecrs", "issued_at": f"{DATE_B}T15:40:00-05:00", "product": "ecrs", "frac": 1.0,
         "start": f"{DATE_B}T16:00:00-05:00", "end": f"{DATE_B}T18:00:00-05:00"}]}
    s = H.Session(t, "reserves")
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "ecrs": {"from": 16, "to": 18, "mw": 50}},
                               "from_hour": 0})
    run(s, lambda s: None)
    assert s.cash["ftp"] == 0 and s.cash["deployment_energy"] > 0


def test_watches_reveal_and_deploy_triggers():
    t = synth()
    ws = H.schedule(t)
    times = [w.time[-5:] for w in ws]
    assert times[:4] == ["14:00", "00:00", "06:00", "12:00"] and "18:00" in times
    w = next(w for w in ws if any(n.event_id == "dep-rrs" for n in w.notices))
    assert w.minute == 19 * 60 + 30
    trig = H.triggers(ws)
    args = [a["args"] for tr in trig for a in tr["actions"] if a["args"]["event_id"] == "dep-rrs"][0]
    assert args["deploy"] == {"product": "rrs", "frac": 1.0, "start_min": 1165, "end_min": 1237}
    assert all("deploy" not in a["args"] for tr in trig for a in tr["actions"] if a["args"]["event_id"] == "n-cons")


def test_reserve_rules_refuse_and_name_the_rule():
    s = H.Session(synth())
    plan = {"energy": [-50, -50] + [0] * 22, "nspin": {"from": 0, "to": 24, "mw": 40}}
    out = json.loads(s.call("commit_schedule", {"plan": plan, "from_hour": 0}))
    assert [(r["hour"], r["field"], r["rule"]) for r in out["refused"]] == [(0, "nspin", "reserve_up"),
                                                                           (1, "nspin", "reserve_up")]
    assert "Non-Spin 4h need 160.00 MWh at 00:00, SoC 100.00" in out["refused"][0]["detail"]
    assert out["committed"] == list(range(24)) and out["book"]["energy"][:2] == [-50, -50]
    assert out["book"]["nspin"][:3] == [0, 0, 40]
    e = H.Session(synth(), "energy")
    out = json.loads(e.call("commit_schedule", {"plan": {"energy": [0] * 24, "regup": {"from": 3, "to": 4, "mw": 10}},
                                                "from_hour": 0}))
    assert [r["rule"] for r in out["refused"]] == ["not_offered"] and 3 not in out["committed"]
    a = H.Session(synth(DATE_A))
    out = json.loads(a.call("commit_schedule", {"plan": {"energy": [0] * 24, "ecrs": {"from": 3, "to": 4, "mw": 10}},
                                                "from_hour": 0}))
    assert out["refused"][0]["rule"] == "not_offered"
    big = json.loads(H.Session(synth()).call("check_schedule", {"plan": {"energy": [120] + [0] * 23}, "from_hour": 0}))
    assert not big["feasible"] and big["issues"][0]["rule"] == "power" and big["refused"] == [0]


def test_freeze_and_as_fixed():
    s = H.Session(synth())
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regup": {"from": 10, "to": 14, "mw": 20}}, "from_hour": 0})
    s.call("advance")
    s.deliver_watch_notices()
    s.call("advance")
    s.deliver_watch_notices()
    assert s.watches[s.watch].time.endswith("06:00") and s.first_open == 7
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [25] * 19}, "from_hour": 5}))
    assert {r["hour"] for r in out["refused"] if r["rule"] == "frozen"} == {5, 6}
    assert 7 in out["committed"]
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * 17, "regup": [0] * 17}, "from_hour": 7}))
    assert {r["hour"] for r in out["refused"] if r["rule"] == "as_fixed"} == {10, 11, 12, 13}
    same = json.loads(s.call("check_schedule", {"plan": {"energy": [0] * 17, "regup": [20.004] * 17}, "from_hour": 7}))
    assert {i["hour"] for i in same["issues"]} == {h for h in range(7, 24) if h not in range(10, 14)}
    assert json.loads(s.call("advance"))["watch"] == 3


def test_calls_budget_and_errors():
    s = H.Session(synth())
    for _ in range(3):
        s.call("check_schedule", {"plan": {"energy": [0] * 24}})
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * 24}}))
    assert "no planning calls left" in out["error"] and not s.commits
    s2 = H.Session(synth())
    out = json.loads(s2.call("commit_schedule", {"energy": [0] * 24}))
    assert out["error"].startswith("commit_schedule: unexpected argument") and out["calls_left"] == 2


@settings(max_examples=150, deadline=None)
@given(S=st.floats(0, 200), e=st.floats(-100, 100), ru=st.floats(0, 60), rd=st.floats(0, 60), rrs=st.floats(0, 60),
       ecrs=st.floats(0, 50), ns=st.floats(0, 30), era=st.sampled_from(["A", "B", "C"]), cyc=st.floats(0, 300),
       pv=st.floats(0, 200), price=st.floats(-50, 300))
def test_reservation_guarantees_deliverability_under_worst_deployment(S, e, ru, rd, rrs, ecrs, ns, era, cyc, pv, price):
    date = {"A": DATE_A, "B": DATE_B, "C": DATE_C}[era]
    s = H.Session(synth(date), "reserves")
    a = {"regup": ru, "regdn": rd, "rrs": rrs, "ecrs": ecrs if era != "A" else 0.0, "nspin": ns}
    if s.rules(5, S, cyc, e, a):
        return
    dur = s.day.dur
    U = sum(min(1.0, dur.get(k, 0)) * a[k] for k in H.UP)
    D = min(1.0, dur["regdn"]) * rd
    r = H.step(s.site, dur, S, cyc, e, a, pv, price, U, D)
    tol = 1e-3
    assert abs(r["b"] - e) <= tol and sum(r["short"].values()) <= tol
    assert r["up_mwh"] == pytest.approx(U, abs=tol) and r["dn_mwh"] == pytest.approx(D, abs=tol)
    assert -tol <= r["S"] <= s.site.e + tol
    assert r["x"] <= s.site.meter + tol and r["x"] >= -s.site.meter_imp - tol
    lo = H.step(s.site, dur, S, cyc, e, a, pv, price, 0.0, D)
    assert -tol <= lo["S"] <= s.site.e + tol and lo["dn_mwh"] == pytest.approx(D, abs=tol)


@pytest.mark.parametrize("seed,neg,site", [(1, False, "arch-ac150"), (2, True, "arch-ac150"), (3, False, "arch-dc150"),
                                           (4, True, "arch-ac125")])
def test_milp_beats_every_baseline_and_lp_bounds_milp(seed, neg, site):
    t = synth(seed=seed, neg=neg, site=site)
    for tier in ("energy", "reserves"):
        ref = H.oneshot_ref(t, tier)
        assert ref["p_milp"] >= ref["p_idle"] - 1e-6
        for pol in (H.sponge_policy, H.as_hog_policy, H.anchor_policy(energy_only=True, pv_blind=True)):
            s = H.Session(t, tier, [], [], reference=True)
            pol(s)
            assert s._project()["total"] <= ref["p_milp"] + 1e-3
        rng = np.random.default_rng(seed)
        for _ in range(5):
            plan = {"energy": [float(x) for x in rng.choice([-50, -25, 0, 25, 50], 24)]}
            if tier == "reserves":
                plan |= {k: [float(x) for x in rng.choice([0, 10, 25], 24)] for k in ("regup", "regdn", "rrs")}
            g = H.oneshot_grade(t | {"refs": {tier: {"oneshot": ref}}}, plan, tier)
            assert not g["submitted"] or g["profit_usd"] <= ref["p_milp"] + 1e-3
        hind, lp = H.hindsight(t, tier), H.hindsight(t, tier, integer=False)
        assert lp >= hind - 1e-6
        S0 = H.site_of(t).s0
        day = H.day_of(t, tier)
        prods = day.offered
        assert (H.solve_day(H.site_of(t), day, 0, S0, 0.0, products=prods, integer=False)["objective"]
                >= H.solve_day(H.site_of(t), day, 0, S0, 0.0, products=prods)["objective"] - 1e-6)


def test_oneshot_reward_of_the_optimum_is_one():
    t = synth(seed=7)
    ref = H.oneshot_ref(t, "reserves")
    plan = ref["plan"]
    g = H.oneshot_grade(t | {"refs": {"reserves": {"oneshot": ref}}}, plan, "reserves")
    assert g["submitted"] and g["reward"] == pytest.approx(1.0, abs=1e-6)
    assert H.oneshot_grade(t, "not json", "reserves")["reward"] == 0.0
    idle = H.oneshot_grade(t | {"refs": {"reserves": {"oneshot": ref}}}, {"energy": [0] * 24}, "reserves")
    assert idle["reward"] == pytest.approx(0.2, abs=1e-6)


def test_milp_solve_time():
    t = synth(seed=5)
    st_, day = H.site_of(t), H.day_of(t, "reserves")
    times = []
    for h0 in (0, 7, 13, 19):
        t0 = time.perf_counter()
        assert H.solve_day(st_, day, h0, st_.s0, 0.0, products=day.offered) is not None
        times.append(time.perf_counter() - t0)
    assert max(times) < 1.0


def test_determinism_and_replay(day):
    a, b = H.Session(day), H.Session(day)
    run(a, agent)
    run(b, agent)
    assert [x["output"] for x in a.transcript] == [x["output"] for x in b.transcript]
    assert a.grade() == b.grade() and a.grade()["submitted"]
    rep = H.replay(day, "reserves", None, None, a.transcript)
    assert rep["ok"], rep["problems"]
    assert a.audit()["ok"], a.audit()["problems"]
    assert H.references(day) == day["refs"]


def test_audit_catches_tampering_and_early_reveal(day):
    s = run(H.Session(day), agent)
    bad = [dict(x) for x in s.transcript]
    i = next(i for i, x in enumerate(bad) if x["tool"] == "advance")
    bad[i]["output"] = bad[i]["output"].replace('"watch":1', '"watch":2')
    assert not H.replay(day, "reserves", None, None, bad)["ok"]
    early = H.Session(day)
    with pytest.raises(ValueError):
        early.notice("nope", "x", "y")
    early.call("grid_notice", {"event_id": "dep-rrs", "name": "ERCOT", "text": "early",
                               "deploy": {"product": "rrs", "frac": 1.0, "start_min": 1165, "end_min": 1237}})
    probs = early._audit_watches()
    assert any("before its reveal time" in p for p in probs) and any("differs from the schedule" in p for p in probs)


def test_no_rt_before_the_hour_ends(day):
    s = H.Session(day)
    while not s.done:
        sit = json.loads(s.call("get_situation"))
        assert len(sit["hours"]["rt_usd"]) * 60 <= max(0, s.minute)
        out = json.loads(s.call("advance"))
        if "watch" in out:
            assert max([r["h"] for r in out["realized"]], default=-1) < s.minute / 60
            s.deliver_watch_notices()
    assert not [p for p in s.audit()["problems"] if "RT prices" in p]


def test_deployment_acts_at_its_real_time_and_is_revealed_once(day):
    s = H.Session(day)
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "rrs": {"from": 19, "to": 21, "mw": 40}}, "from_hour": 0})
    msgs = []
    while not s.done:
        out = json.loads(s.call("advance"))
        msgs += out["messages"]
        if "watch" in out:
            s.deliver_watch_notices()
    msgs += json.loads(s.call("get_situation"))["messages"]
    dep = [m for m in msgs if m["event_id"] == "dep-rrs"]
    assert len(dep) == 1 and dep[0]["deploy"]["product"] == "rrs" and dep[0]["time"].endswith("19:30")
    up = {r["h"]: r["up_mwh"] for r in s.rows}
    assert up[19] == pytest.approx(40 * 35 / 60, abs=1e-6) and up[20] == pytest.approx(40 * 25 / 60, abs=1e-6)
    assert s.audit()["ok"]


def test_drift_after_freeze_is_excused_and_known_drift_is_charged():
    t = synth(deploy=False, notices=False)
    t["reg"] = t["reg"] | {"up": [1.0] * 24, "dn": [0.0] * 24}
    s = H.Session(t)
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regup": {"from": 0, "to": 24, "mw": 25}},
                                                "from_hour": 0}))
    assert out["committed"] == list(range(24)) and not out["refused"]
    run(s, lambda s: None)
    g = s.grade()
    excused = {r["hour"] for r in s.excused}
    charged = {r["h"] for r in s.rows if sum(r["charged"].values()) > 1e-9}
    assert min(excused) == 4 and not charged & {4, 5, 6} and min(charged) == 7
    rows = {r["h"]: r for r in s.rows}
    assert rows[10]["charged"]["regup"] < rows[10]["excused_mw"]["regup"]
    assert any(g["hour"] == 6 and g["excused"] for g in s.governor)
    assert g["ftp_mwh_excused"] > 0 and g["ftp_mwh_charged"] > 0 and s.cash["ftp"] > 0


def test_episode_json_and_data(day):
    s = run(H.Session(day), agent)
    ep = s.episode(bundle="test", path="B'", model="scripted")
    assert ep["schema"] == "gridsim.episode/v3" and ep["env"] == "gridsim-hybrid" and len(ep["hours"]) == 24
    assert ep["audit"]["ok"] and ep["references"]["p_anchor"] == day["refs"]["reserves"]["p_anchor"]
    json.dumps(ep)
    d = H.Session(day).data()
    assert d["grade"] is None and "p_anchor" not in json.dumps(d)


def test_end_day_plays_the_book_and_grades(day):
    s = H.Session(day)
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regdn": {"from": 0, "to": 6, "mw": 30}}, "from_hour": 0})
    out = s.end_day()
    assert out["end_reason"] == "end_day" and out["audit"]["ok"], out["audit"]
    assert s.done and len(s.rows) == 24 and 0 <= out["reward"] <= 1


def test_anchor_scores_one_and_idle_point_two(day):
    r = day["refs"]
    anc = H.play(day, "reserves", H.anchor_policy(), reference=False)
    assert anc.grade()["reward"] == pytest.approx(1.0) and anc.audit()["ok"] and not anc.grade()["beats_anchor"]
    assert anc.grade()["stretch_reward"] == anc.grade()["reward"]
    idle = H.play(day, "reserves", lambda s: s.call("commit_schedule", {"plan": {"energy": [0] * 24}, "from_hour": 0})
                  if s.watch == 0 else None, reference=False)
    assert idle.grade()["reward"] == pytest.approx(0.2) and idle.profit() == pytest.approx(r["p_idle"])
    assert idle.grade()["stretch_reward"] == idle.grade()["reward"]
    assert H.play(day, "reserves", H.idle_policy, reference=False).grade()["reward"] == 0.0


def test_negative_prices_curtail_pv_and_charge():
    t = synth(seed=3, neg=True, deploy=False)
    s = H.play(t, "energy", H.anchor_policy())
    for r in s.rows:
        if t["rt"][r["h"]] < 0:
            assert r["pv"] == 0.0
    assert any(r["b"] < 0 for r in s.rows if t["prices"][r["h"]] < 0)


def test_rtcb_refuses_without_rt_mcpc():
    with pytest.raises(ValueError, match="rtcb"):
        H.Session(synth(DATE_C), "rtcb")


def test_prompts_schemas_and_oneshot_reward():
    from gridsim_core import hybrid_prompt as P

    t = synth(seed=9)
    sp = P.system_prompt("reserves", "B")
    assert "ECRS 2 h" in sp and "Non-Spin 4 h" in sp and "fixed after watch 0" in sp
    assert "ECRS does not exist yet" in P.system_prompt("reserves", "A")
    assert "RegUp" not in P.system_prompt("energy", "B")
    names = [x["function"]["name"] for x in P.tool_schemas("reserves")]
    assert names == list(H.TOOLS)
    assert "ecrs" not in json.dumps(P.tool_schemas("energy"))
    s = H.Session(t)
    assert json.loads(s.call("get_situation")) == json.loads(P.situation_text(s)) | {"messages": []}
    msgs = P.oneshot_messages(t, "reserves")
    assert msgs[0]["role"] == "system" and "one-shot" in msgs[0]["content"] and "watch 0" in msgs[1]["content"]
    ref = H.oneshot_ref(t, "reserves")
    t = t | {"refs": {"reserves": {"oneshot": ref}}}
    best = json.dumps(ref["plan"])
    comps = [f"<think>x</think>Here: {best}",
             [{"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "commit_schedule",
                                                                                   "arguments": json.dumps({"plan": ref["plan"], "from_hour": 0})}}]}],
             'I will idle: {"energy": [0, 0]}', "no plan"]
    r = P.oneshot_reward_fn(None, comps, task=[t] * 4, tier="reserves")
    assert r[0] == pytest.approx(1.0) and r[1] == pytest.approx(1.0) and r[2] == 0.0 and r[3] == 0.0


@pytest.mark.parametrize("site", ["arch-dc150", "arch-ac125"])
def test_clipping_is_exact_and_the_sponge_catches_it(site):
    t = synth(seed=11, site=site, deploy=False, notices=False)
    st_, day = H.site_of(t), H.day_of(t, "energy")
    clip = [max(0.0, float(x) - st_.meter) for x in day.pv]
    assert sum(clip) > 10
    s = H.play(t, "energy", H.sponge_policy)
    rows = {r["h"]: r for r in s.rows}
    for h, c in enumerate(clip):
        r = rows[h]
        assert r["clippable"] == pytest.approx(c, abs=1e-9)
        assert r["clip_rec"] == pytest.approx(min(c, max(0.0, -r["b"])), abs=1e-6)
        if c and r["b"] < 0:
            assert r["x"] == pytest.approx(st_.meter, abs=1e-6) or r["pv"] == pytest.approx(day.pv[h], abs=1e-6)
    caught = sum(r["clip_rec"] for r in s.rows)
    room = (st_.e - st_.s0) / st_.eta
    assert min(sum(clip), room) - 1e-3 <= caught <= sum(clip) + 1e-6
    ref = H.references(t, tiers=("energy",))
    assert ref["energy"]["baselines"]["sponge"]["reward"] > 0.2
    g = H.play(t | {"refs": ref}, "energy", H.sponge_policy, reference=False).grade()
    assert g["clip_recovered_pct"] == pytest.approx(100 * caught / sum(clip), abs=1e-4)


def test_issue_details_never_name_an_empty_product_list():
    s = H.Session(synth())
    out = json.loads(s.call("check_schedule", {"plan": {"energy": [100] * 24}, "from_hour": 0}))
    assert {i["rule"] for i in out["issues"]} == {"soc_empty"}
    assert all(" need " not in i["detail"] or i["detail"].split(" need ")[0].strip() for i in out["issues"])


def test_inherited_awards_accept_the_governors_move():
    t = synth(deploy=False, notices=False)
    t["reg"] = t["reg"] | {"up": [1.0] * 24, "dn": [0.0] * 24}
    s = H.Session(t)
    s.call("commit_schedule", {"plan": {"energy": [0] * 24, "regup": {"from": 0, "to": 24, "mw": 25}}, "from_hour": 0})
    for _ in range(3):
        s.call("advance")
        s.deliver_watch_notices()
    fo = s.first_open
    S, cyc = H.projected_state(s, fo)
    a = s.entry(fo)[1]
    assert S < H.r_up(s.day.dur, a)
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [0] * (24 - fo)}, "from_hour": fo}))
    assert any(r["hour"] == fo and r["rule"] == "reserve_up" for r in out["refused"])
    g = H.govern(0.0, *H.limits(s.site, s.day.dur, S, cyc, a))
    out = json.loads(s.call("commit_schedule", {"plan": {"energy": [g] + [0] * (23 - fo)}, "from_hour": fo}))
    assert fo in out["committed"] and not any(r["hour"] == fo for r in out["refused"])
