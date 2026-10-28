import itertools
import json
import time

import numpy as np
import pytest
from conftest import battery_dict
from hypothesis import given, settings
from hypothesis import strategies as st

from gridsim_core import live
from gridsim_core.physics import simulate
from gridsim_core.task import battery_of, make_task


def live_task(prices, rt, battery, date="2024-07-18", notices=None, blind=None):
    t = make_task(prices, battery, date=date, point="HB_WEST", blind=blind)
    return t | {"task_id": f"live-v2-{date}-HB_WEST-t", "rt": [float(x) for x in rt], "notices": notices or []}


@st.composite
def live_tasks(draw, max_n=6, k_max=4):
    n = draw(st.integers(1, max_n))
    k_dis, k_ch = draw(st.integers(1, k_max)), draw(st.integers(1, k_max))
    b = battery_dict(n, k_dis, k_ch, draw(st.sampled_from([0.8, 0.85, 0.9])), draw(st.sampled_from([0.0, 4.0, 8.0])),
                     draw(st.integers(0, 2 * n)), draw(st.integers(0, n)), draw(st.integers(0, n)),
                     q=draw(st.sampled_from([2.5, 10.0, 25.0])))
    seed = draw(st.integers(0, 2**31))
    rng = np.random.default_rng(seed)
    da = np.round(30 + 25 * np.sin(np.arange(24) / 24 * 2 * np.pi - 2) + rng.normal(0, 8, 24), 2)
    rt = np.repeat(da, 4) + rng.normal(0, draw(st.sampled_from([2.0, 15.0, 60.0])), 96)
    if draw(st.booleans()):
        k = rng.integers(0, 90)
        rt[k:k + rng.integers(1, 6)] += rng.choice([-200.0, 900.0, 3000.0])
    return live_task(da.tolist(), np.round(rt, 2).tolist(), b)


def simple_task(**kw):
    da = [20.0] * 6 + [35.0] * 6 + [25.0] * 5 + [90.0, 120.0, 150.0, 110.0, 60.0, 40.0, 30.0]
    rt = [p + (8 if t % 3 else -6) for t, p in enumerate(live.expand(da))]
    rt[74] = 900.0
    b = battery_dict(4, 4, 4, 0.85, 4.0, 6, 2, 2, q=25.0)
    return live_task(da, rt, b, **kw)


def notice(eid, iso, text="Conservation appeal.", **kw):
    return {"event_id": eid, "source": "ERCOT", "kind": "conservation", "level": "Advisory", "issued_at": iso,
            "name": "ERCOT", "title": text, "text": text} | kw


def run(s: live.Session, policy) -> live.Session:
    """Drive a session through call() the way the env does: policy calls, advance, then the watch's triggers."""
    while not s.done:
        policy(s)
        out = json.loads(s.call("advance"))
        if "watch" in out:
            s.deliver_watch_notices()
    return s


@settings(max_examples=60, deadline=None)
@given(live_tasks())
def test_hourly_expansion_is_exact(task):
    hb = battery_of(task)
    plan = live.hourly_plan(hb, task["prices"])
    v1 = simulate(task, plan)["profit_usd"]
    assert live.settle_plan(task, plan, live.expand(plan)) == pytest.approx(v1, abs=1e-6)
    flat = dict(task, rt=[p for p in task["prices"] for _ in range(4)])
    assert live.settle_plan(flat, [0] * 24, live.expand(plan)) == pytest.approx(v1, abs=1e-6)
    a = live.Session(task)
    b = live.Session(task)
    oa = json.loads(a.call("commit_schedule", {"actions": plan, "start": "00:00", "step": "1h"}))
    ob = json.loads(b.call("commit_schedule", {"actions": live.expand(plan), "start": "00:00"}))
    assert oa == ob and a.sched == live.expand(plan)


def test_two_settlement_by_hand():
    task = simple_task()
    g = live.live_grid(task)
    assert (g.q, g.k_dis, g.n, g.cap, g.s0, g.s_end_min) == (6.25, 4, 16, 24, 8, 8)
    da_pos = [0] * 24
    da_pos[1], da_pos[18] = -1, 1
    phys = [0] * 96
    phys[4], phys[74] = -2, 2
    rt = task["rt"]
    m_buy, m_sell = -4 * 6.25 / 0.85, 4 * 6.25
    da_usd = 20.0 * m_buy + 120.0 * m_sell
    dev = sum(rt[t] * (0 - m_buy / 4) for t in range(4, 8)) + rt[4] * (-2 * 6.25 / 0.85)
    dev += sum(rt[t] * (0 - m_sell / 4) for t in range(72, 76)) + rt[74] * (2 * 6.25)
    assert live.settle_plan(task, da_pos, phys) == pytest.approx(da_usd + dev - 4.0 * 6.25 * 2, abs=1e-9)
    s = live.Session(task)
    s.call("commit_da", {"position": da_pos})
    s.call("commit_schedule", {"actions": phys, "start": "00:00"})
    run(s, lambda s: None)
    assert s.profit() == pytest.approx(da_usd + dev - 4.0 * 6.25 * 2, abs=1e-9)
    assert s.pnl()["da_usd"] == round(da_usd, 2)


@settings(max_examples=40, deadline=None)
@given(live_tasks())
def test_hindsight_bounds_every_reference(task):
    r = live.references(task, ("foresight", "freeze6h"))
    assert r["p_hind"] >= r["roll"]["foresight"]["p_roll"] - 1e-6
    assert r["p_hind"] >= r["roll"]["freeze6h"]["p_roll"] - 1e-6
    assert r["p_hind"] >= r["p_naive"] - 1e-6 and r["p_hind"] >= r["p_idle"] - 1e-6
    assert r["p_hind"] == pytest.approx(live.settle_plan(task, r["hind"]["da"], r["hind"]["schedule"]), abs=1e-5)
    if r["p_lp"] is not None:
        assert r["p_hind"] <= r["p_lp"] + 1e-5


def _brute(b, prices):
    best = -np.inf
    for acts in itertools.product(range(-b.k_ch, b.k_dis + 1), repeat=len(prices)):
        s, d, v, ok = b.s0, 0, 0.0, True
        for p, a in zip(prices, acts, strict=True):
            if live._violation(a, s, d, b.k_dis, b.k_ch, b):
                ok = False
                break
            mwh = b.q * a if a > 0 else b.q * a / b.eta
            v += p * mwh - b.c_deg * b.q * max(a, 0)
            s, d = s - a, d + max(a, 0)
        if ok and s >= b.s_end_min:
            best = max(best, v)
    return best


def _feasible(b, acts):
    s, d = b.s0, 0
    for a in acts:
        if live._violation(a, s, d, b.k_dis, b.k_ch, b):
            return False
        s, d = s - a, d + max(a, 0)
    return s >= b.s_end_min


@settings(max_examples=15, deadline=None)
@given(st.integers(1, 2), st.integers(0, 4), st.integers(0, 2), st.integers(0, 2), st.integers(0, 2**31))
def test_decomposition_is_exact_against_the_joint_brute_force(n, cap, s0, se, seed):
    """On a 2-hour toy, the max over every feasible (DA position, physical schedule) pair equals the two DPs."""
    rng = np.random.default_rng(seed)
    s0, se = min(s0, n), min(se, n)
    hb = battery_of({"battery": battery_dict(n, 1, 1, 0.85, 4.0, cap, s0, se, q=4.0)})
    g = hb._replace(q=1.0, n=4 * n, cap=4 * cap, s0=4 * s0, s_end_min=4 * se)
    da, rt = rng.normal(40, 30, 2).round(2), rng.normal(40, 60, 8).round(2)
    def gm(a):
        return (g.q * a if a > 0 else g.q * a / g.eta)
    das = [d for d in itertools.product((-1, 0, 1), repeat=2) if _feasible(hb, d)]
    phs = [a for a in itertools.product((-1, 0, 1), repeat=8) if _feasible(g, a)]
    joint = max((sum(da[h] * 4 * gm(d[h]) for h in range(2))
                 + sum(rt[t] * (gm(a[t]) - 4 * gm(d[t // 4]) / 4) - g.c_deg * g.q * max(a[t], 0) for t in range(8))
                 for d in das for a in phs), default=None)
    spread = da - rt.reshape(2, 4).mean(axis=1)
    dpa, phys = live.plan_dp(hb._replace(c_deg=0.0), spread, hb.s0), live.plan_dp(g, rt, g.s0)
    if joint is None:
        assert dpa is None or phys is None
        return
    val = sum(spread[h] * 4 * gm(dpa[h]) for h in range(2)) + sum(
        rt[t] * gm(a) - g.c_deg * g.q * max(a, 0) for t, a in enumerate(phys))
    assert val == pytest.approx(joint, abs=1e-6)


def test_frozen_intervals_are_immutable_and_execute_as_committed():
    task = simple_task()
    s = live.Session(task)
    plan = [0] * 96
    plan[8:12], plan[72:76] = [-2] * 4, [2] * 4
    assert json.loads(s.call("commit_schedule", {"actions": plan, "start": "00:00"}))["accepted"]
    s.call("advance")
    s.call("advance")
    assert s.minute == 360 and s.first_open == 28
    before = list(s.sched)
    bad = plan[:]
    bad[26] = -1
    out = json.loads(s.call("commit_schedule", {"actions": bad, "start": "00:00"}))
    assert not out["accepted"] and out["refusals"][0] == {"interval": 26, "time": "06:30", "reason": "frozen"}
    assert s.sched == before
    out = json.loads(s.call("commit_schedule", {"actions": bad[24:], "start": "06:00"}))
    assert not out["accepted"] and out["refusals"][0]["reason"] == "frozen"
    ok = plan[:]
    ok[72], ok[75] = 3, 1
    assert json.loads(s.call("commit_schedule", {"actions": ok[28:], "start": "07:00"}))["accepted"]
    run(s, lambda s: None)
    assert s.executed[:28] == plan[:28] and s.executed == ok


def test_no_rt_price_before_its_interval_ends():
    task = simple_task(notices=[notice("n1", "2024-07-18T15:05:00-05:00")])
    s = live.Session(task)
    seen = []

    def policy(s):
        sit = json.loads(s.call("get_situation"))
        seen.append((s.minute, len(sit["rt_prices_usd_per_mwh"])))
        assert sit["rt_prices_usd_per_mwh"] == [round(x, 2) for x in task["rt"][:max(0, s.minute) // 15]]

    run(s, policy)
    assert seen == [(-600, 0), (0, 0), (360, 24), (720, 48), (915, 61), (1080, 72)]
    for step in s.transcript:
        out = json.loads(step["output"])
        for row in out.get("settled") or []:
            assert row["rt_spp"] == round(task["rt"][row["interval"]], 2)
    assert s.audit()["ok"]
    s.rt_log.append({"call": 99, "minute": 360, "rt_shown": 25})
    assert any("RT prices" in p for p in s.audit()["problems"])


def test_watch_schedule_and_reveal_rule():
    d = "2023-09-06T"
    ns = [notice("board", "2023-09-05T09:00:00-05:00"), notice("eve", "2023-09-05T21:10:00-05:00"),
          notice("a", d + "05:10:00-05:00"), notice("eea2", d + "19:25:00-05:00"), notice("eea1", d + "20:27:00-05:00"),
          notice("normal", d + "20:37:00-05:00"), notice("late", d + "23:20:00-05:00"),
          notice("utc", "2023-09-06T15:01:00Z")]
    task = simple_task(date="2023-09-06", notices=ns)
    ws = live.schedule(task)
    assert [w.minute for w in ws] == [-600, 0, 360, 615, 720, 1080, 1170, 1245]
    assert {w.minute: [n.event_id for n in w.notices] for w in ws} == {
        -600: ["board"], 0: ["eve"], 360: ["a"], 615: ["utc"], 720: [], 1080: [], 1170: ["eea2"],
        1245: ["eea1", "normal"]}
    assert live.after_day(task) == ["late"]
    assert ws[0].time == "2023-09-05 14:00" and ws[0].time_utc == "2023-09-05T19:00:00Z"
    assert ws[6].freeze_line == 1260 and ws[7].freeze_line == 1320
    assert [w.minute for w in live.schedule(task, "short")] == [-600, 0, 315, 615, 720, 1170, 1245]
    many = [notice(f"n{h}", f"{d}{h:02d}:05:00-05:00") for h in range(1, 23)]
    assert len(live.schedule(simple_task(date="2023-09-06", notices=many))) == live.MAX_WATCHES
    many.append(notice("eea", f"{d}20:10:00-05:00", "EEA2.", level="EEA2"))
    many.append(notice("cx", f"{d}16:10:00-05:00", "Cancelled.", action="cancel", level="EEA2"))
    capped = live.schedule(simple_task(date="2023-09-06", notices=many))
    assert [w.minute for w in capped] == [-600, 0, 75, 135, 195, 255, 360, 720, 1080, 1215]
    assert [n.event_id for n in capped[-1].notices] == ["n18", "n19", "n20", "eea"]
    trig = live.triggers(ws)
    assert [t["id"] for t in trig] == [f"watch-{k}" for k in range(1, 8)]
    assert trig[6]["actions"][1]["args"]["event_id"] == "normal"
    s = run(live.Session(task), lambda s: None)
    assert s.audit()["ok"], s.audit()
    for e in s.log:
        assert e["minute"] >= s.scheduled[e["event_id"]][0].reveal
    s2 = live.Session(task)
    s2.call("advance")
    s2.call("grid_notice", ws[6].notices[0].args())
    assert any("before its reveal" in p for p in s2.audit()["problems"])


def test_planning_call_budget():
    s = live.Session(simple_task())
    pos = live.hourly_plan(battery_of(s.task), s.task["prices"])
    assert json.loads(s.call("check_schedule", {"actions": [0] * 24, "start": "00:00", "step": "1h"}))[
        "planning_calls_left"] == 2
    assert json.loads(s.call("commit_da", {"position": "1,2"}))["planning_calls_left"] == 1
    assert json.loads(s.call("commit_da", {"position": pos}))["accepted"]
    out = json.loads(s.call("commit_schedule", {"actions": [0] * 24, "start": "00:00", "step": "1h"}))
    assert out == {"error": "no planning calls left in this watch (3 used): call advance", "planning_calls_left": 0,
                   "messages": []}
    assert json.loads(s.call("get_situation"))["planning_calls_left"] == 0
    assert json.loads(s.call("advance"))["planning_calls_left"] == 3
    out = json.loads(s.call("commit_da", {"position": pos}))
    assert not out["accepted"] and "watch 0 only" in out["refusals"][0]["reason"]
    assert s.planning_calls == [3, 1]
    assert json.loads(s.call("check_schedule", {"actions": [0], "start": "00:00", "bogus": 1}))["error"]
    assert s.planning_calls == [3, 2]


def test_da_position_rules_and_follow():
    s = live.Session(simple_task())
    out = json.loads(s.call("commit_da", {"position": [-1] * 3 + [0] * 21}))
    assert not out["accepted"] and out["refusals"] == [{"hour": "HE03", "reason": "soc_above_max"}]
    out = json.loads(s.call("commit_da", {"position": [1, 1] + [0] * 22}))
    assert not out["accepted"] and out["refusals"] == [{"hour": "HE24", "reason": "end_target"}]
    out = json.loads(s.call("commit_da", {"position": [0, -1] + [0] * 16 + [1] + [0] * 5}))
    assert out["accepted"] and out["schedule_follows_da"] and s.sched == live.expand(s.da_pos)
    s2 = live.Session(simple_task())
    s2.call("commit_schedule", {"actions": [0] * 96, "start": "00:00"})
    out = json.loads(s2.call("commit_da", {"position": [0, -1] + [0] * 16 + [1] + [0] * 5}))
    assert out["accepted"] and not out["schedule_follows_da"] and s2.sched == [0] * 96


def test_replay_is_byte_identical_and_deterministic():
    task = simple_task(notices=[notice("n1", "2024-07-18T15:05:00-05:00"), notice("n0", "2024-07-17T10:00:00-05:00")])

    def agent(s):
        rng = np.random.default_rng(s.watch)
        s.call("get_situation")
        if s.watch == 0:
            s.call("commit_da", {"position": live.hourly_plan(battery_of(s.task), s.task["prices"])})
        fo = s.first_open
        if fo < 96:
            cand = s.display()
            cand[fo] = int(rng.integers(-1, 2))
            s.call("check_schedule", {"actions": cand[fo:], "start": live.hhmm(15 * fo)})
            s.call("commit_schedule", {"actions": " ".join(map(str, cand[fo:])), "start": live.hhmm(15 * fo)})

    a, b = run(live.Session(task), agent), run(live.Session(task), agent)
    assert [x["output"] for x in a.transcript] == [x["output"] for x in b.transcript]
    assert a.grade() == b.grade()
    assert live.replay(task, "foresight", None, a.transcript)["ok"]
    bad = [dict(x) for x in a.transcript]
    bad[3]["output"] = bad[3]["output"].replace("1", "2", 1)
    assert not live.replay(task, "foresight", None, bad)["ok"]
    assert a.audit()["ok"]
    ep = a.episode(model="scripted")
    assert ep["schema"] == "gridsim.episode/v2" and len(ep["intervals"]) == 96 and ep["audit"]["ok"]
    assert ep["steps"][0]["output"]["watch"] == 0 and ep["notices"][0]["watch"] in (0, 4)


def test_reward_contract():
    task = simple_task()
    r = live.references(task)
    s = run(live.Session(task), lambda s: None)
    assert s.grade()["reward"] == 0.0 and not s.grade()["submitted"]
    s = live.Session(task)
    s.call("commit_schedule", {"actions": [0] * 96, "start": "00:00"})
    s = run(s, lambda s: None)
    assert s.profit() == r["p_idle"] and s.grade()["reward"] == 0.2
    s = run(live.Session(task), lambda s: s.call("commit_da", {"position": r["naive"]["da"]}) if s.watch == 0 else None)
    assert s.grade()["profit_usd"] == pytest.approx(r["p_naive"], abs=1e-6)
    roll = live.roll_policy()
    s = live.Session(task)
    while not s.done:
        roll(s)
        s.call("advance")
        if not s.done:
            s.deliver_watch_notices()
    g = s.grade()
    assert g["profit_usd"] == pytest.approx(r["roll"]["foresight"]["p_roll"], abs=1e-6) and g["reward"] == 1.0
    assert g["capture_vs_hindsight"] <= 1.0 + 1e-9 and g["stretch_reward"] == 1.0
    assert s.executed == r["roll"]["foresight"]["executed"]


def test_derate_clips_frozen_intervals_and_is_excused():
    derate = notice("d1", "2024-07-18T17:50:00-05:00", "Unit derate.", kind="derate", source="asset",
                    derate_mw=50.0, **{"from": "2024-07-18T18:00:00-05:00", "until": "2024-07-18T20:00:00-05:00"})
    task = simple_task(notices=[derate])
    s = live.Session(task)
    plan = [0] * 96
    plan[8:12], plan[72:76] = [-2] * 4, [4, 4, 0, 0]
    plan[76:80] = [0, 0, 0, 0]
    s.call("commit_schedule", {"actions": plan, "start": "00:00"})
    run(s, lambda s: None)
    assert [w.minute for w in s.watches] == [-600, 0, 360, 720, 1080]
    assert s.executed[72:74] == [2, 2] and s.limits[0]["k_dis"] == 2
    frozen = [c for c in s.clips if c["frozen"]]
    assert [c["interval"] for c in frozen] == [72, 73]
    want = sum(task["rt"][t] * 2 * 6.25 - 4.0 * 6.25 * 2 for t in (72, 73))
    assert s.cash["excused_usd"] == pytest.approx(want)
    assert s.grade()["excused_usd"] == pytest.approx(want) and not s.grade()["feasible"]
    s2 = live.Session(task)
    plan2 = [0] * 96
    plan2[8:12], plan2[78:80] = [-2] * 4, [4, 4]
    s2.call("commit_schedule", {"actions": plan2, "start": "00:00"})
    run(s2, lambda s: None)
    assert s2.executed[78:80] == [2, 2] and s2.cash["excused_usd"] == 0.0
    sit = json.loads(s2.call("get_situation"))
    assert sit["limits"] == [{"from": "18:00", "until": "20:00", "k_dis": 2, "k_ch": 2, "event_id": "d1"}]


def test_blind_tier_hides_da_until_midnight():
    lag = [30.0] * 24
    task = simple_task(blind={"dam_prev_day": lag, "dam_prev_7d": [lag] * 7})
    s = live.Session(task, "blind")
    sit = json.loads(s.call("get_situation"))
    assert sit["da_prices_usd_per_mwh"] is None and sit["dam_prev_day_usd_per_mwh"] == lag
    out = json.loads(s.call("check_schedule", {"actions": [0] * 96, "start": "00:00"}))
    assert out["projected"]["pnl_at_da_prices_usd"] is None
    out = json.loads(s.call("commit_da", {"position": [0] * 24}))
    assert out["accepted"] and out["da_value_usd"] is None
    s.call("advance")
    assert json.loads(s.call("get_situation"))["da_prices_usd_per_mwh"] == task["prices"]
    r = live.references(task, "blind")
    assert r["roll"]["blind"]["via"] in ("persist", "ridge")
    with pytest.raises(ValueError):
        live.Session(simple_task(), "blind")


def test_freeze6h_and_short_tiers():
    s = live.Session(simple_task(), "freeze6h")
    s.call("advance")
    assert s.first_open == 24
    s.call("advance")
    assert s.first_open == 48
    assert len(live.Session(simple_task(), "short").watches) == 3


def test_parse_errors_use_a_planning_call():
    s = live.Session(simple_task())
    out = json.loads(s.call("commit_schedule", {"actions": [0] * 95, "start": "00:00"}))
    assert not out["accepted"] and out["refusals"][0]["reason"].startswith("parse: expected exactly 96")
    out = json.loads(s.call("check_schedule", {"actions": [0] * 24, "start": "00:30", "step": "1h"}))
    assert out["refusals"][0]["reason"].startswith("parse: start 00:30 is not a 1h boundary")
    out = json.loads(s.call("check_schedule", {"actions": [0] * 24, "start": "0:00", "step": "2h"}))
    assert out["refusals"][0]["reason"] == 'parse: step must be "15m" or "1h", got \'2h\''
    out = json.loads(s.call("commit_schedule", {"actions": [0] * 24, "start": "0:00", "step": "1h"}))
    assert out == {"error": "no planning calls left in this watch (3 used): call advance", "planning_calls_left": 0,
                   "messages": []}


def test_reference_speed():
    task = live_task(*(lambda r: (r[0], r[1]))((list(30 + 20 * np.sin(np.arange(24) / 4)),
                                                 list(np.repeat(30 + 20 * np.sin(np.arange(24) / 4), 4)
                                                      + np.random.default_rng(0).normal(0, 30, 96)))),
                     battery_dict(16, 4, 4, 0.85, 4.0, 32, 8, 8, q=25.0))
    t0 = time.perf_counter()
    live.references(task, lp=False)
    assert time.perf_counter() - t0 < 0.5
