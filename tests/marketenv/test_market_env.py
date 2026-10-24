"""The gridsim-market env in process through the MCP client and its middleware: its tools are gridsim_core's for the
loaded tier, every call reaches the market Session as sent and answers with its exact output, advance moves the gateway
clock to each watch it opens, no output shows another seat's private data, and the harness extensions load, play seat
A's calls, end and report one floor."""

import copy
import json

import httpx
import numpy as np
import pytest
from live_days import FakeClock, live_server
from market_floors import DAY, IDLE, ROWS, SPRINT, WIRING, anchor_offer, in_process, policies, scripted, stored

from agentenv_gridsim.market import CALLS_URI, EMPTY
from gridsim_core.live import NOTICE_TOOL
from gridsim_core.market import END_URI, LOAD_URI, MARKET_ENV, SPRINT_TOOLS, TOOLS, Session, grade_offer, reward_fn
from gridsim_core.market_prompt import tool_schemas

pytestmark = pytest.mark.anyio
PRIVATE = ("fuel_usd_mmbtu", "tariff_usd", "risk_lambda", "ptc_usd", "ptc_share", "dr_usd", "load_mw", "actual_mw",
           "pool_id", "units", "fair_usd")
NOTICES = [{"event_id": "OPS-d1", "source": "ERCOT", "kind": "OCN", "level": "OCN", "name": "ERCOT",
            "issued_at": "2026-07-20T09:10:00+00:00", "title": "ERCOT OCN", "action": "issue",
            "text": "ERCOT issued an OCN (hot weather)."},
           {"event_id": "OPS-d2", "source": "ERCOT", "kind": "OCN", "level": "OCN", "name": "ERCOT",
            "issued_at": "2026-07-21T13:10:00+00:00", "title": "ERCOT OCN", "action": "issue",
            "text": "ERCOT issued an OCN (a unit trip)."}]


async def text(client, name: str, args: dict) -> str:
    result = await client.call_tool_mcp(name, args)
    assert not result.isError, result.content[0].text
    return result.content[0].text


async def play(env, client, task: dict, tier: str, calls: list, **load) -> tuple[list[str], list[dict]]:
    """The calls through the client, the triggers' grid_notice calls after each advance that opens a watch; the
    outputs and the clock's sets."""
    env.market_load(task["task_id"], tier, **load)
    outs = []
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for name, args in (c for watch in calls for c in watch):
            outs.append(await text(client, name, args))
            if name == "advance" and "watch" in json.loads(outs[-1]):
                for n in env.session.watches[env.session.watch].notices:
                    await text(client, NOTICE_TOOL, n.args())
    return outs, clock.sets


@pytest.mark.parametrize("tier", ["floor-sprint", "floor-day"])
async def test_the_tools_are_gridsim_cores_for_the_tier_in_its_order(env, client, tier):
    assert [t.name for t in await client.list_tools()] == [*TOOLS, NOTICE_TOOL]
    env.market_load(SPRINT["task_id"], tier)
    tools = await client.list_tools()
    assert [t.name for t in tools] == [*(SPRINT_TOOLS if tier == "floor-sprint" else TOOLS), NOTICE_TOOL]
    want = {s["function"]["name"]: s["function"] for s in tool_schemas(tier)}
    for t in tools[:-1]:
        assert (t.description, t.inputSchema) == (want[t.name]["description"], want[t.name]["parameters"])


@pytest.mark.parametrize(("tier", "policy"), [("floor-sprint", "anchor"), ("floor-sprint", "replay"),
                                              ("floor-day", "anchor"), ("floor-day", "idle")])
async def test_a_floor_through_the_env_is_the_sessions_byte_for_byte(env, client, tier, policy):
    calls = scripted(DAY, tier, policies(DAY)[policy])
    outs, sets = await play(env, client, DAY, tier, calls)
    played, want = in_process(DAY, tier, calls)
    assert outs == want
    assert env.session.transcript == played.transcript and env.session.data() == played.data()
    assert sets == [{"virtual_time": w.time_utc, "virtual_seconds_per_real_second": 0} for w in played.watches[1:]]
    assert env.session.done and env.session.audit()["ok"]
    g, ref = env.session.grade(), stored(DAY, tier, policy)
    if ref:
        assert g["reward"] == ref["reward"] and abs(g["profit_usd"] - ref["profit"]) < 0.005


@pytest.mark.parametrize("task", ROWS, ids=[r["task_id"] for r in ROWS])
@pytest.mark.parametrize("tier", ["floor-sprint", "floor-day"])
async def test_every_fixture_floor_scores_its_stored_anchor_through_the_env(env, client, task, tier):
    calls = scripted(task, tier, policies(task)["anchor"])
    outs, _ = await play(env, client, task, tier, calls)
    played, want = in_process(task, tier, calls)
    assert outs == want and env.session.audit()["ok"]
    g = env.session.grade()
    assert (g["reward"], g["submitted"]) == (1.0, True)
    assert abs(g["profit_usd"] - task["refs"][tier]["p_anchor"]) < 1e-6


async def test_iso_notices_reach_the_agent_with_its_next_call_after_the_watch_opens(env, client):
    task = copy.deepcopy(DAY) | {"notices": NOTICES}
    env.tasks.rows[task["task_id"]] = task
    calls = scripted(task, "floor-day", policies(task)["anchor"])
    calls[0] = [("get_situation", {}), *calls[0]]
    outs, _ = await play(env, client, task, "floor-day", calls)
    s = env.session
    [opening] = [w for w in s.watches if w.notices and w.index == 0]
    [later] = [w for w in s.watches if w.notices and w.index > 0]
    assert [n["event_id"] for n in json.loads(outs[0])["notices"]] == [opening.notices[0].event_id]
    got = [(k, [m["event_id"] for m in json.loads(o)["messages"]]) for k, o in enumerate(outs)
           if json.loads(o).get("messages")]
    k = next(i for i, (n, _) in enumerate(c for w in calls for c in w) if n == "advance"
             and json.loads(outs[i]).get("watch") == later.index)
    assert got == [(k + 1, ["OPS-d2"])]
    assert s.audit()["ok"] and outs == in_process(task, "floor-day", calls)[1]


async def test_a_malformed_call_gets_the_sessions_answer_and_uses_a_planning_call(env, client):
    env.market_load(DAY["task_id"], "floor-sprint")
    s = Session(DAY, "floor-sprint")
    for name, args in [("check_offer", {"offer": {"hours": [{"he": 25, "sell": [[1, 2]]}]}}),
                       ("check_offer", {"offer": "{", "x": 1}), ("submit_offer", {}),
                       ("get_situation", {"x": 1}), ("advance", {})]:
        assert await text(client, name, args) == s.call(name, args)
    assert env.session.planning_calls == [3] and env.session.calls == 5 and not env.session.done


async def test_advance_needs_the_synced_clock_and_moves_nothing_without_it(env, client):
    env.market_load(DAY["task_id"], "floor-day")
    result = await client.call_tool_mcp("advance", {})
    assert result.isError and "the gateway clock is not synced" in result.content[0].text
    assert (env.session.watch, env.session.calls, env.session.transcript) == (0, 0, [])
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        assert json.loads(await text(client, "advance", {}))["watch"] == 1
        assert clock.sets == [{"virtual_time": env.session.watch_time_utc(1), "virtual_seconds_per_real_second": 0}]


async def test_no_output_shows_another_seats_private_data_or_a_reference(env, client):
    task = copy.deepcopy(DAY) | {"notices": NOTICES}
    env.tasks.rows[task["task_id"]] = task
    calls = scripted(task, "floor-day", policies(task)["anchor"])
    calls[0] = [("get_situation", {}), ("get_private_costs", {}), ("get_forecast", {"kind": "load"}),
                ("get_disclosure", {"op_date": "2026-05-21", "hour": 18}),
                ("propose_contract", {"hours": [18, 19], "mw": 50, "strike_usd": 400.0}),
                ("message_agent", {"agent_name": "retail-L", "text": "hello"}), *calls[0]]
    outs, _ = await play(env, client, task, "floor-day", calls)
    for out in outs:
        assert not any(f'"{key}"' in out for key in PRIVATE), out[:300]
        assert '"p_br"' not in out and '"p_anchor"' not in out and '"refs"' not in out
    assert json.loads(outs[0])["public"]["peers"] == [task["seats"][s]["name"] for s in ("B", "G", "R", "L")]


async def test_the_dam_closes_at_ten_and_the_disclosure_is_sixty_days_old(env, client):
    for name, (task, tier, calls) in WIRING.items():
        env.loaded = False
        env.market_load(task["task_id"], tier)
        with FakeClock(env.session.watch_time_utc(0)) as clock:
            await env.sync_time(clock.url)
            outs = [json.loads(o) for o in (await env.market_calls([{"tool": t, "args": a} for t, a in calls]))
                    ["outputs"]]
        if name == "wiring-late":
            assert outs[1]["accepted"] is True and outs[3]["accepted"] is False
            assert outs[3]["issues"] == [{"he": None, "rule": "closed", "detail": "the DAM closed at 10:00"}]
            assert env.get()[0].data["offer"] == {"hours": anchor_offer(task)["hours"]}
        else:
            assert "not disclosed yet" in outs[0]["error"] and "outside the disclosure window" in outs[1]["error"]
            assert outs[2]["op_date"] == "2024-06-20" and len(outs[2]["curve"]) <= 64 and outs[3]["done"] is True
        end = env.end_floor()
        played, _ = in_process(task, tier, [calls])
        played.end_floor()
        assert (end["reward"], end["audit"]["ok"]) == (played.grade()["reward"], True)


async def test_load_once_end_floor_and_data(env, client):
    assert env.get()[0].data == EMPTY
    for args, why in [({"floor_id": "nope"}, "unknown floor id 'nope'"),
                      ({"floor_id": DAY["task_id"], "tier": "foresight"}, "unknown tier 'foresight'"),
                      ({"floor_id": DAY["task_id"], "bidders": "a2a"}, "scripted bidders"),
                      ({"floor_id": DAY["task_id"], "script": "cost"}, "scripted bidders"),
                      ({"floor_id": DAY["task_id"], "iso": "live"}, "iso is one of replay, off")]:
        with pytest.raises(ValueError, match=why):
            env.market_load(**args)
    assert env.market_load(DAY["task_id"], "floor-day", compliant=True) == {
        "floor_id": DAY["task_id"], "tier": "floor-day", "watches": len(Session(DAY, "floor-day").watches)}
    assert env.get()[0].data["grade"] is None
    with pytest.raises(ValueError, match="each floor needs a new deploy"):
        env.market_load(DAY["task_id"])
    end = env.end_floor()
    assert (end["end_reason"], end["reward"], end["audit"]["ok"]) == ("end-floor", 0.0, True)
    data = env.get()[0].data
    assert data["done"] and set(data) == set(EMPTY) and data["compliant"] is True
    assert data["grade"]["compliant_reward"] == end["compliant_reward"]
    env.reset()
    assert env.get()[0].data == EMPTY
    result = await client.call_tool_mcp("get_situation", {})
    assert result.isError and "no day loaded" in result.content[0].text


async def test_iso_off_drops_the_notices(env):
    task = copy.deepcopy(DAY) | {"notices": NOTICES}
    env.tasks.rows[task["task_id"]] = task
    assert env.market_load(task["task_id"], "floor-day", iso="off")["watches"] == 7
    assert not any(w.notices for w in env.session.watches)


async def test_an_idle_offer_is_valid_and_scores_idle(env, client):
    outs, _ = await play(env, client, SPRINT, "floor-sprint", [[("submit_offer", {"offer": IDLE})]])
    assert json.loads(outs[0])["done"] is True and env.session.grade()["reward"] == 0.2


async def test_the_image_entry_point_serves_gridsim_market_when_named():
    with live_server(MARKET_ENV) as base:
        card = httpx.get(f"{base}/.well-known/agent-env.json").json()
        assert card["name"] == MARKET_ENV
        assert {e["uri"] for e in card["capabilities"]["extensions"]} >= {
            LOAD_URI, END_URI, CALLS_URI, "urn:agentenv:clock/v1"}
        assert {t["name"] for t in card["capabilities"]["tools"]} == {*TOOLS, NOTICE_TOOL}


async def test_a_floor_day_ended_early_delivers_the_unreached_notices_and_audits_clean(env):
    task = copy.deepcopy(DAY) | {"notices": NOTICES}
    env.tasks.rows[task["task_id"]] = task
    env.market_load(task["task_id"], "floor-day")
    end = env.end_floor()
    assert (end["reward"], end["audit"]) == (0.0, {"ok": True, "problems": []})
    assert [(e["event_id"], e["via"]) for e in env.session.log] == [("OPS-d1", "load"), ("OPS-d2", "env")]


def random_offer(task: dict, rng: np.random.Generator) -> dict:
    """A valid offer: up to three sell and three buy blocks an hour on seat A's grid, every buy below every sell."""
    a = task["seats"]["A"]
    grid, units = a["grid_mw"], int(round(a["p_mw"] / a["grid_mw"]))
    hours = []
    for he in range(1, 25):
        if rng.random() < 0.3:
            continue
        cut = float(rng.uniform(-50, 300))
        sides = {}
        for side, lo, hi in (("sell", cut + 1, 5000.0), ("buy", -250.0, cut)):
            left, blocks = units, []
            for _ in range(int(rng.integers(0, 4))):
                k = int(rng.integers(0, left + 1))
                if k:
                    blocks.append([k * grid, round(float(rng.uniform(lo, min(hi, cut + 400 if side == "sell"
                                                                                 else hi))), 2)])
                    left -= k
            sides[side] = blocks
        hours.append({"he": he, **sides})
    return {"hours": hours}


@pytest.mark.parametrize("task", [SPRINT, DAY], ids=["sprint", "day"])
async def test_path_a_and_path_b_grade_every_offer_alike(env, client, task):
    rng = np.random.default_rng(5)
    offers = [anchor_offer(task), IDLE, *(random_offer(task, rng) for _ in range(4))]
    for offer in offers:
        env.loaded = False
        outs, _ = await play(env, client, task, "floor-sprint", [[("submit_offer", {"offer": offer})]])
        a, b = env.session.grade(), grade_offer(task, offer, rows=True)
        assert json.loads(outs[0])["done"] is True
        for key in ("reward", "compliant_reward", "profit_usd", "welfare_ratio", "regret_usd"):
            assert abs(a[key] - b[key]) <= 1e-6, key
        call = json.dumps({"name": "submit_offer", "arguments": {"offer": offer}})
        assert abs(reward_fn(None, [f"<tool_call>{call}</tool_call>"], task=task)[0] - a["reward"]) <= 1e-6
