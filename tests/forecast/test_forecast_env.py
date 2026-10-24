"""The gridsim-forecast env in process through the MCP client and its middleware: its tools are gridsim_core's for the
loaded tier, every call reaches the forecast Session as sent and answers with its exact output, a deployment's payload
arrives through grid_notice, advance moves the gateway clock to each watch it opens, a forecast asked for after now is
refused with the audit intact, and the harness extensions load, end and report one window."""

import json

import httpx
import pytest
from forecast_days import ROWS, WINDOW, anchor, in_process, scripted
from live_days import FakeClock, live_server

from agentenv_gridsim.forecast import EMPTY
from agentenv_gridsim.hybrid import HYBRID_NOTICE_SCHEMA
from gridsim_core.forecast import (
    END_WINDOW_URI,
    FORECAST_ENV,
    FORECAST_LOAD_URI,
    FORECAST_TOOLS,
    NOTICE_TOOL,
    TIERS,
    TOOLS,
    Session,
)
from gridsim_core.forecast_prompt import tool_schemas

pytestmark = pytest.mark.anyio


async def text(client, name: str, args: dict) -> str:
    result = await client.call_tool_mcp(name, args)
    assert not result.isError, result.content[0].text
    return result.content[0].text


async def play(env, client, task: dict, tier: str, calls: list) -> tuple[list[str], list[dict]]:
    """The calls through the client, the triggers' grid_notice calls after each advance that opens a watch; the
    outputs and the clock's sets."""
    env.forecast_load(task["task_id"], tier)
    outs = []
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for name, args in (c for watch in calls for c in watch):
            outs.append(await text(client, name, args))
            if name == "advance" and "watch" in json.loads(outs[-1]):
                for n in env.session.watches[env.session.watch].notices:
                    await text(client, NOTICE_TOOL, n.args())
    return outs, clock.sets


@pytest.mark.parametrize("tier", TIERS)
async def test_the_tools_are_gridsim_cores_for_the_tier_in_its_order(env, client, tier):
    env.forecast_load(WINDOW["task_id"], tier)
    tools = await client.list_tools()
    offered = [t for t in TOOLS if tier != "blind" or t not in FORECAST_TOOLS]
    assert [t.name for t in tools] == [*offered, NOTICE_TOOL]
    want = {s["function"]["name"]: s["function"] for s in tool_schemas(tier)}
    for t in tools[:-1]:
        assert (t.description, t.inputSchema) == (want[t.name]["description"], want[t.name]["parameters"])
    assert (tools[-1].description, tools[-1].inputSchema) == (HYBRID_NOTICE_SCHEMA["description"],
                                                              HYBRID_NOTICE_SCHEMA["parameters"])


@pytest.mark.parametrize("tier", TIERS)
async def test_the_anchor_through_the_env_is_the_sessions_byte_for_byte(env, client, tier):
    """The stored P_anchor is the anchor's on the platform that built the pack (the MILP's ties break by platform), so
    the window is graded against the same calls in process here; scripts/forecast_e2e.py holds it to the cent."""
    calls = scripted(WINDOW, tier, anchor(tier))
    outs, sets = await play(env, client, WINDOW, tier, calls)
    played, want = in_process(WINDOW, tier, calls)
    assert outs == want
    assert env.session.transcript == played.transcript and env.session.data() == played.data()
    assert sets == [{"virtual_time": w.time_utc, "virtual_seconds_per_real_second": 0} for w in played.watches[1:]]
    g = env.session.grade()
    assert env.session.done and env.session.audit()["ok"] and g == played.grade()
    assert g["reward"] >= 0.99 and g["dam_missed"] == 0
    deploys = [n.event_id for w in played.watches for n in w.notices if n.deploy]
    assert deploys and {e["event_id"] for e in env.session.log if e["via"] == "trigger"} >= set(deploys)


@pytest.mark.parametrize("task", ROWS, ids=[r["task_id"] for r in ROWS])
async def test_every_fixture_window_scores_its_anchor_through_the_env(env, client, task):
    calls = scripted(task, "front", anchor("front"))
    outs, _ = await play(env, client, task, "front", calls)
    played, want = in_process(task, "front", calls)
    assert outs == want and env.session.data() == played.data() and env.session.audit()["ok"]
    assert env.session.grade() == played.grade()


async def test_a_forecast_issued_after_now_is_refused_and_the_audit_holds(env, client):
    env.forecast_load(WINDOW["task_id"], "front")
    s = env.session
    with FakeClock(s.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        later = json.loads(await text(client, "get_forecast", {"kind": "price", "issued_at": s.watches[1].time}))
        assert later["error"].startswith(f"issued_at is after now ({s.watches[0].time})")
        assert later["forecast_calls_left"] == 5 and s.forecast_log == []
        now = json.loads(await text(client, "get_forecast", {"kind": "price", "issued_at": s.watches[0].time}))
        assert "error" not in now and all(f["reveal_minute"] <= f["minute"] for f in s.forecast_log)
    end = env.end_window()
    assert (end["end_reason"], end["reward"], end["audit"]) == ("end_window", 0.0, {"ok": True, "problems": []})


async def test_a_notice_whose_payload_differs_from_the_schedule_fails_the_audit(env, client):
    env.forecast_load(WINDOW["task_id"], "front")
    w = next(w for w in env.session.watches if any(n.deploy for n in w.notices))
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        while env.session.watch < w.index:
            await text(client, "advance", {})
        for n in w.notices:
            args = n.args()
            if n.deploy:
                args["deploy"] = args["deploy"] | {"frac": 0.5}
            await text(client, NOTICE_TOOL, args)
    end = env.end_window()
    assert not end["audit"]["ok"] and any("differs from the schedule" in p for p in end["audit"]["problems"])


async def test_a_malformed_call_gets_the_sessions_answer_and_uses_its_budget(env, client):
    env.forecast_load(WINDOW["task_id"], "front")
    s = Session(WINDOW, "front")
    for name, args in [("check_schedule", {"plan": {"regup": [{"from": 0, "to": 4, "mw": 25}]}, "from_hour": 0}),
                       ("commit_schedule", {"plan": {"energy": "keep"}, "from_hour": 0}),
                       ("submit_dam", {"operating_day": WINDOW["d1"], "plan": {"energy": [0] * 24, "regup": "keep"}}),
                       ("get_forecast", {"kind": "price", "when": "now"}), ("get_situation", {"x": 1})]:
        assert await text(client, name, args) == s.call(name, args)
    assert (env.session.planning_calls, env.session.forecast_calls, env.session.dam_submits) == ([2], [1], [1])
    refused = json.loads(s.transcript[2]["output"])["refused"][0]["detail"]
    assert "to keep RegUp as it is, leave regup out of the plan" in refused


async def test_advance_needs_the_synced_clock_and_moves_nothing_without_it(env, client):
    env.forecast_load(WINDOW["task_id"], "front")
    result = await client.call_tool_mcp("advance", {})
    assert result.isError and "the gateway clock is not synced" in result.content[0].text
    assert (env.session.watch, env.session.calls, env.session.transcript) == (0, 0, [])
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        assert await env.sync_time(clock.url) == {"env_get_time_url": clock.url,
                                                  "virtual_time": env.session.watch_time_utc(0)}
        assert json.loads(await text(client, "advance", {"now": True}))["error"] == "advance: unexpected argument 'now'"
        assert clock.sets == [] and env.session.watch == 0
        assert json.loads(await text(client, "advance", {}))["watch"] == 1
        assert clock.sets == [{"virtual_time": env.session.watch_time_utc(1), "virtual_seconds_per_real_second": 0}]


async def test_the_last_advance_ends_the_window_without_moving_the_clock(env, client):
    env.forecast_load(WINDOW["task_id"], "front-lite")
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for _ in env.session.watches:
            out = json.loads(await text(client, "advance", {}))
        assert out["done"] is True and out["reward"] == 0.0 and "watch" not in out
        assert len(clock.sets) == len(env.session.watches) - 1
        assert json.loads(await text(client, "advance", {}))["error"] == "the window is over"
        assert json.loads(await text(client, "get_situation", {}))["window_over"] is True
    assert env.session.grade()["dam_missed"] == 2


async def test_load_once_end_window_and_data(env, client):
    assert env.get()[0].data == EMPTY
    for args, why in [({"task_id": "nope"}, "unknown task id 'nope'"),
                      ({"task_id": WINDOW["task_id"], "tier": "reserves"}, "unknown tier 'reserves'")]:
        with pytest.raises(ValueError, match=why):
            env.forecast_load(**args)
    with pytest.raises(ValueError, match="with the desk's only, not 'ercot'"):
        env.forecast_load(WINDOW["task_id"], "front", "ercot")
    s = Session(WINDOW, "front")
    assert env.forecast_load(WINDOW["task_id"], source="desk") == {
        "task_id": WINDOW["task_id"], "tier": "front", "watches": len(s.watches), "days": 3, "source": "desk"}
    with pytest.raises(ValueError, match="needs a new deploy"):
        env.forecast_load(WINDOW["task_id"])
    end = env.end_window()
    assert (end["end_reason"], end["reward"], end["audit"]["ok"]) == ("end_window", 0.0, True)
    data = env.get()[0].data
    assert data["done"] and set(data) == set(EMPTY) and {n["via"] for n in data["notices"]} <= {"load", "env"}
    assert data["grade"]["dam_missed"] == 3 and data["grade"]["baselines"] == WINDOW["refs"]["front"]["baselines"]
    env.reset()
    assert env.get()[0].data == EMPTY
    result = await client.call_tool_mcp("get_situation", {})
    assert result.isError and f"no day loaded: load one with {FORECAST_LOAD_URI}" in result.content[0].text


async def test_the_image_entry_point_serves_gridsim_forecast_when_named():
    with live_server(FORECAST_ENV) as base:
        card = httpx.get(f"{base}/.well-known/agent-env.json").json()
        assert card["name"] == FORECAST_ENV
        uris = {e["uri"] for e in card["capabilities"]["extensions"]}
        assert uris >= {FORECAST_LOAD_URI, END_WINDOW_URI, "urn:agentenv:clock/v1"}
        assert "urn:gridsim:end-day/v1" not in uris and "urn:gridsim:live-load/v1" not in uris
        assert {t["name"] for t in card["capabilities"]["tools"]} == {*TOOLS, NOTICE_TOOL}
