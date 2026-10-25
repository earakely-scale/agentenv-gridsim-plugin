import gzip
import json
import random
from pathlib import Path

import numpy as np
import pytest

from gridsim_core import market
from gridsim_core.market_auction import Book, battery_of, book, clear_hour, clear_mitigated, parse_offer, self_schedule
from gridsim_core.market_refs import (
    baseline_offers,
    battery_dp,
    forecast_books,
    physical_lp,
    profile_results,
    welfare,
    welfare_lp,
)
from gridsim_core.market_stack import DayStore, Floor, hour_curves

FIX = Path(__file__).resolve().parents[2] / "data" / "fixtures-market"
STORE = DayStore(FIX / "days.jsonl.gz")
TASKS = [json.loads(line) for line in gzip.open(FIX / "tasks.jsonl.gz")]


def random_offer(rng, grid):
    hours = []
    for he in range(1, 25):
        if rng.random() < 0.2:
            continue
        sp = rng.uniform(-50, 900)
        bp = sp - rng.uniform(1, 100)
        ks, kb = rng.randint(0, 20), rng.randint(0, 20)
        hours.append({"he": he, "sell": [[grid * ks, round(sp, 2)]] if ks else [],
                      "buy": [[grid * kb, round(bp, 2)]] if kb else []})
    return {"hours": hours}


def test_fixtures_are_real_and_anonymised():
    assert len(TASKS) >= 10 and {t["date"] for t in TASKS} == {"2024-08-20", "2026-07-21"}
    blob = (FIX / "days.jsonl.gz").read_bytes()
    days = [json.loads(line) for line in gzip.decompress(blob).decode().splitlines()]
    for d in days:
        assert "QSE" not in json.dumps(d) and "Resource Name" not in json.dumps(d)
        for side in ("supply", "demand"):
            assert all(len(c) <= 64 for c in (d.get("background") or {}).get(side, []))


@pytest.mark.parametrize("date", ["2024-08-20", "2026-07-21", "2024-06-19", "2026-05-21"])
def test_shipped_curves_rebuild_the_replay(date):
    day = STORE.get(date)
    for h in range(24):
        sup, dem = hour_curves(day, h)
        lam = clear_mitigated(lambda m, s=sup, d=dem: book(-250.0, 5000.0, s, d), [], {}, {}).lam
        assert abs(lam - day["replay"]["lambda_usd"][h]) < 0.01


@pytest.mark.parametrize("task", TASKS[:: 3], ids=lambda t: t["task_id"])
def test_replay_clears_at_the_real_hub_price(task):
    F = Floor(task, STORE)
    prof = {s: "replay" for s in task["seats"]}
    for h in range(24):
        assert abs(F.clear(h, prof).lam - F.hub_real[h]) < 0.01


@pytest.mark.parametrize("task", TASKS[::2], ids=lambda t: t["task_id"])
def test_br_dominates_sampled_offers_and_references(task):
    rng = random.Random(task["task_id"])
    r = task["refs"]
    br = r["floor-sprint"]["p_br_rt"]
    assert r["floor-sprint"]["p_br"] >= max(r["floor-sprint"]["p_anchor"], r["p_idle"]) - 1e-6
    assert br >= r["floor-sprint"]["p_br"] - 1e-6
    for _ in range(12):
        g = market.grade_offer(task, random_offer(rng, task["seats"]["A"]["grid_mw"]), STORE)
        assert g["profit_usd"] <= br + 1e-6


@pytest.mark.parametrize("task", TASKS[:2], ids=lambda t: t["task_id"])
def test_withhold_then_deviate_never_beats_br(task):
    s = market.Session(task, "floor-day", store=STORE)
    s.call("advance", {})
    b = s.b
    withhold = {"hours": [{"he": h, "sell": [[b.p, 5000]]} for h in range(1, 25)]}
    assert json.loads(s.call("submit_offer", {"offer": withhold}))["accepted"]
    s.call("advance", {})
    hub = np.repeat(np.asarray(s.F.rt, float)[:, None], 41, 1)
    v, ks, _ = battery_dp(b, hub, None, 0.0, feasible_only=True, s_start=b.s0, hard_end=True)
    out = json.loads(s.call("commit_schedule", {"plan": [k * b.grid for k in ks], "from_hour": 0}))
    assert out["accepted"], out
    while not s.done:
        s.call("advance", {})
    assert s.profit() <= task["refs"]["floor-day"]["p_br_rt"] + 1e-6
    assert physical_lp(b, s.F.rt) >= v - 1e-6


def test_path_b_equals_the_session_and_replays_byte_for_byte():
    task = TASKS[0]
    offer = random_offer(random.Random(4), task["seats"]["A"]["grid_mw"])
    g = market.grade_offer(task, offer, STORE)
    s = market.Session(task, "floor-sprint", store=STORE)
    s.call("get_situation", {})
    s.call("check_offer", {"offer": offer})
    s.call("submit_offer", {"offer": offer})
    sg = s.grade(rows=False)
    assert abs(sg["reward"] - g["reward"]) < 1e-6 and abs(sg["profit_usd"] - g["profit_usd"]) < 1e-6
    assert market.replay(task, "floor-sprint", None, s.transcript, STORE)["ok"]
    assert s.audit()["ok"]


def test_idle_scores_the_floor_and_no_submit_scores_zero():
    task = TASKS[1]
    assert market.grade_offer(task, {"hours": []}, STORE)["reward"] == pytest.approx(0.2)
    s = market.Session(task, "floor-sprint", store=STORE)
    s.end_floor()
    g = s.grade()
    assert g["reward"] == 0.0 and g["compliant_reward"] == 0.0 and not g["beats_anchor"]
    bad = market.grade_offer(task, {"hours": [{"he": 1, "sell": [[7.0, 30]]}]}, STORE)
    assert bad["reward"] == 0.0 and bad["submitted"] is False


def test_self_schedules_are_never_mitigated_and_mitigation_lowers_the_price():
    P = np.array([-250.0, 0.0, 50.0, 100.0, 5000.0])
    N = np.array([-3000.0, -1000.0, 0.0, 500.0, 600.0])
    bk = Book(-250.0, 5000.0, P, N, 1e9, [], {})
    grids = {"A": 50.0}
    blocks = [("A", 1, 500.0, 4000.0, 40.0), ("A", -1, 0.0, 0.0, None)]
    plain = clear_hour(bk, [b for b in blocks if b[2] > 0], grids)
    mit = clear_mitigated(lambda m: bk, blocks, grids, {})
    assert mit.mitigated == ["A"] and mit.lam <= plain.lam
    ss = clear_mitigated(lambda m: bk, self_schedule("A", 500.0, -250.0, 5000.0, 40.0), grids, {})
    assert ss.mitigated == [] and ss.awards["A"] == 500.0


def test_welfare_lp_bounds_every_dispatch():
    task = TASKS[0]
    F = Floor(task, STORE)
    prof = {s: "replay" for s in task["seats"] if s != "A"} | {"A": [[] for _ in range(24)]}
    ws = welfare_lp(F, prof)
    rng = random.Random(9)
    for _ in range(3):
        offer = random_offer(rng, task["seats"]["A"]["grid_mw"])
        s = market.Session(task, "floor-sprint", store=STORE)
        s.call("submit_offer", {"offer": offer})
        res = profile_results(F, s.profile)
        assert res["A"]["awards"] == s.cleared["awards"]
        assert welfare(F, prof, {"A": s.executed, "B": [0.0] * 24}) <= ws + 1.0


def test_disclosure_follows_the_60_day_rule():
    task = TASKS[0]
    s = market.Session(task, "floor-day", store=STORE)
    ok = json.loads(s.call("get_disclosure", {"op_date": "2024-06-20", "side": "supply", "hour": 18}))
    assert len(ok["curve"]) <= 64
    late = json.loads(s.call("get_disclosure", {"op_date": "2024-06-21", "side": "supply"}))
    assert "not disclosed" in late["error"]
    light = market.Session(task, "floor-day", store=DayStore(FIX / "days.jsonl.gz", [
        {"date": "2024-06-19", "parser": "light"}]))
    assert "not in the store" in json.loads(light.call("get_disclosure", {"op_date": "2024-06-19"}))["error"]


def test_forecast_issued_at_is_a_time():
    s = market.Session(TASKS[0], "floor-sprint", store=STORE)
    assert json.loads(s.call("get_forecast", {"kind": "load", "issued_at": "2024-08-19T11:00:00Z"}))["kind"] == "load"
    assert json.loads(s.call("get_forecast", {"kind": "load", "issued_at": "2024-08-19 08:59"}))["kind"] == "load"
    assert "after now" in json.loads(s.call("get_forecast", {"kind": "wind", "issued_at": "2024-08-19T15:00:00Z"}))[
        "error"]
    assert "not a time" in json.loads(s.call("get_forecast", {"kind": "wind", "issued_at": "this morning"}))["error"]


def test_a_side_left_out_null_or_keep_stays_as_the_last_accepted_offer():
    task = TASKS[0]
    b = battery_of(task["seats"]["A"])
    g, s = b.grid, market.Session(task, "floor-day", store=STORE)
    first = {"hours": [{"he": 18, "sell": [[2 * g, 100]], "buy": []}, {"he": 3, "sell": [], "buy": [[g, 10]]}]}
    assert json.loads(s.call("submit_offer", {"offer": first}))["accepted"]
    again = {"hours": [{"he": 18, "buy": [[g, 20]]}, {"he": 3, "sell": "keep", "buy": None}], "as_awards": "keep"}
    assert json.loads(s.call("submit_offer", {"offer": again}))["replaces_previous"]
    assert s.situation()["offer"]["hours"] == [{"he": 3, "sell": [], "buy": [[g, 10.0]]},
                                               {"he": 18, "sell": [[2 * g, 100.0]], "buy": [[g, 20.0]]}]
    bad = json.loads(s.call("check_offer", {"offer": {"hours": [{"he": 18, "sell": "same"}]}}))
    assert not bad["valid"] and "leave sell out" in bad["issues"][0]["detail"]
    assert parse_offer({"hours": [{"he": 5}]}, b.p, g, -250, 5000) == ({5: {"sell": [], "buy": []}}, [])
    while s.cleared is None or s.minute < market.AWARDS:
        s.call("advance", {})
    fo, cur = s.first_open, list(s.plan)
    kept, full = ({k: v for k, v in json.loads(s.call("check_schedule", {"plan": plan, "from_hour": fo})).items()
                   if k != "calls_left"} for plan in ([None, "keep"] + cur[fo + 2:], cur[fo:]))
    assert kept == full and "issues" in kept
    refused = json.loads(s.call("check_schedule", {"plan": {"energy": cur, "regup": [g] * 24}, "from_hour": 0}))
    assert refused["issues"][0]["rule"] == "not_offered" and "leave regup out" in refused["issues"][0]["detail"]


def test_floor_day_contracts_and_audit():
    task = TASKS[0]
    s = market.Session(task, "floor-day", store=STORE)
    fair = s.fc["forecast_hub_usd"][18]
    acc = json.loads(s.call("propose_contract", {"counterparty": "retail-L", "kind": "cfd", "hours": [19], "mw": 50,
                                                 "strike_usd": round(fair, 2), "op_dates": [task["date"]]}))
    assert acc["status"] == "accepted"
    hi = json.loads(s.call("propose_contract", {"hours": [19], "mw": 50, "strike_usd": fair + 5000}))
    assert hi["status"] == "countered"
    json.loads(s.call("respond_contract", {"contract_id": hi["contract_id"], "action": "accept"}))
    for tool, args in market.anchor_policy(s):
        s.call(tool, args)
    while not s.done:
        s.call("advance", {})
        for tool, args in market.anchor_policy(s):
            s.call(tool, args)
    g = s.grade(rows=False)
    assert g["contract"]["contracts"] and len(g["contract"]["contracts"]) == 2
    assert g["reward"] == pytest.approx(1.0, abs=1e-6)
    assert s.audit()["ok"]


def test_reward_fn_reads_the_tool_call():
    task = TASKS[2]
    q = task["refs"]["floor-sprint"]["anchor"]["q_mw"]
    hours = [{"he": h + 1, "sell": [[x, -250]] if x > 0 else [], "buy": [[-x, 5000]] if x < 0 else []}
             for h, x in enumerate(q) if x]
    call = json.dumps({"name": "submit_offer", "arguments": {"offer": {"hours": hours}}})
    r = market.reward_fn(None, [f"<tool_call>{call}</tool_call>", "no call"], task=[task, task])
    assert r[0] == pytest.approx(1.0, abs=1e-6) and r[1] == 0.0


def test_reward_fn_trains_on_s_against_br_rt_above_the_anchor():
    task = TASKS[2]
    fs = task["refs"]["floor-sprint"]
    hours = [{"he": h + 1, "sell": [[x, -250]] if x > 0 else [], "buy": [[-x, 5000]] if x < 0 else []}
             for h, x in enumerate(fs["br"]["q_mw"]) if x]
    call = json.dumps({"name": "submit_offer", "arguments": {"offer": {"hours": hours}}})
    g = market.grade_offer(task, {"hours": hours})
    s = 1 + 0.2 * (g["profit_usd"] - fs["p_anchor"]) / (fs["p_br_rt"] - fs["p_anchor"])
    assert g["reward"] == 1.0 and g["profit_usd"] > fs["p_anchor"] and g["stretch_reward"] == pytest.approx(s, abs=1e-6)
    assert market.reward_fn(None, [f"<tool_call>{call}</tool_call>"], task=[task]) == [g["stretch_reward"]]
    assert g["capture_vs_hindsight"] == pytest.approx(
        (g["profit_usd"] - task["refs"]["p_idle"]) / (fs["p_br_rt"] - task["refs"]["p_idle"]), abs=1e-6)


def test_battery_dp_is_the_price_taker_optimum_on_flat_prices():
    task = TASKS[0]
    b = battery_of(task["seats"]["A"])
    prices = np.asarray(STORE.get(task["date"])["hub_dam_usd"], float)
    v, ks, _ = battery_dp(b, np.repeat(prices[:, None], 41, 1), None, 50.0, feasible_only=True)
    assert v <= physical_lp(b, prices) + 1e-6
    assert all(-20 <= k <= 20 for k in ks)


@pytest.mark.parametrize("task", TASKS, ids=lambda t: t["task_id"])
def test_every_baseline_is_a_legal_offer(task):
    F = Floor(task, STORE)
    b = battery_of(task["seats"]["A"])
    for name, offer in baseline_offers(F, forecast_books(STORE, task)).items():
        assert parse_offer(offer, b.p, b.grid, F.floor, F.cap)[1] == [], name
    assert "baseline_issues" not in task["refs"]


def test_the_anchor_does_not_beat_itself_and_eps_is_a_share():
    task = TASKS[3]
    s = market.play(task, "floor-sprint", market.anchor_policy, store=STORE)
    g = s.grade()
    assert g["reward"] == pytest.approx(1.0) and not g["beats_anchor"]
    assert 0.0 <= g["eps_nash"] <= 1.0 and all(0.0 <= v["eps"] <= 1.0 for v in g["seat_results"].values())
    assert g["capture_vs_br"] <= 1.0 + 1e-9


def test_scored_tasks_have_headroom_in_both_tiers():
    for t in TASKS:
        h = t["refs"]["headroom_usd_per_mw"]
        if h["anchor"] >= 10 and h["anchor_day"] >= 10:
            assert t["refs"]["floor-sprint"]["p_anchor"] > t["refs"]["p_idle"]


@pytest.mark.parametrize("pack", ["gridsim-market-eval", "gridsim-market-rtcb", "gridsim-market-train"])
def test_packs_have_legal_baselines_and_per_tier_headroom(pack):
    for line in gzip.open(FIX.parent / pack / "tasks.jsonl.gz"):
        t = json.loads(line)
        r = t["refs"]
        assert "baseline_issues" not in r, t["task_id"]
        assert r["headroom_usd_per_mw"]["anchor"] >= 10 and r["headroom_usd_per_mw"]["br"] >= 25
        if t["tags"].get("floor_day"):
            assert t["tags"]["floor_day_ok"] and r["headroom_usd_per_mw"]["anchor_day"] >= 10
