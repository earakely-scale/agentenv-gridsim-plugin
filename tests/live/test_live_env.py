"""The gridsim-live env in process through the MCP client and its middleware: its tools are gridsim_core's, every call
reaches the Session as sent and answers with its exact output, advance moves the gateway clock to each watch it
opens, and the harness extensions load, end and report one day."""

import json

import httpx
import pytest
from live_days import DERATE_DAY, NOTICE_DAY, QUIET_DAY, FakeClock, in_process, live_server, naive_calls

from agentenv_gridsim.live import EMPTY, NOTICE_SCHEMA
from gridsim_core.live import LIVE_ENV, NOTICE_TOOL, TOOLS, Session
from gridsim_core.live_prompt import tool_schemas

pytestmark = pytest.mark.anyio


async def text(client, name: str, args: dict) -> str:
    result = await client.call_tool_mcp(name, args)
    assert not result.isError, result.content[0].text
    return result.content[0].text


async def play(env, client, task: dict, tier: str = "foresight") -> tuple[list[str], list[dict]]:
    """The naive calls through the client, the triggers' grid_notice calls after each advance that opens a watch; the
    outputs and the clock's sets."""
    env.live_load(task["task_id"], tier)
    outs = []
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for name, args in (c for watch in naive_calls(task, tier) for c in watch):
            outs.append(await text(client, name, args))
            if name == "advance" and "watch" in json.loads(outs[-1]):
                for n in env.session.watches[env.session.watch].notices:
                    await text(client, NOTICE_TOOL, n.args())
    return outs, clock.sets


async def test_the_tools_are_gridsim_cores_in_its_order(client):
    tools = await client.list_tools()
    assert [t.name for t in tools] == [*TOOLS, NOTICE_TOOL]
    want = {s["function"]["name"]: s["function"] for s in tool_schemas("foresight")}
    for t in tools[:-1]:
        assert (t.description, t.inputSchema) == (want[t.name]["description"], want[t.name]["parameters"])
    assert (tools[-1].description, tools[-1].inputSchema) == (NOTICE_SCHEMA["description"],
                                                              NOTICE_SCHEMA["parameters"])


@pytest.mark.parametrize(("task", "tier"), [(NOTICE_DAY, "foresight"), (NOTICE_DAY, "blind"),
                                             (DERATE_DAY, "foresight"), (QUIET_DAY, "short")])
async def test_a_day_through_the_env_is_the_sessions_byte_for_byte(env, client, task, tier):
    outs, sets = await play(env, client, task, tier)
    played, want = in_process(task, tier, naive_calls(task, tier))
    assert outs == want
    assert env.session.transcript == played.transcript and env.session.data() == played.data()
    assert sets == [{"virtual_time": w.time_utc, "virtual_seconds_per_real_second": 0} for w in played.watches[1:]]
    assert env.session.done and env.session.audit()["ok"]
    if not played.limits:
        assert env.session.grade()["reward"] == task["refs"]["roll"][tier]["naive_reward"]


async def test_a_malformed_call_gets_the_sessions_answer_and_uses_a_planning_call(env, client):
    env.live_load(NOTICE_DAY["task_id"])
    s = Session(NOTICE_DAY)
    for name, args in [("commit_da", {"position": [0] * 24, "hour": 3}), ("check_schedule", {"actions": [0] * 96}),
                       ("commit_schedule", {"actions": "1 2", "start": "25:00"}), ("get_situation", {"x": 1})]:
        assert await text(client, name, args) == s.call(name, args)
    assert env.session.planning_calls == [3] and env.session.calls == 4


async def test_advance_needs_the_synced_clock_and_moves_nothing_without_it(env, client):
    env.live_load(NOTICE_DAY["task_id"])
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


async def test_the_last_advance_ends_the_day_without_moving_the_clock(env, client):
    env.live_load(QUIET_DAY["task_id"])
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for _ in env.session.watches:
            out = json.loads(await text(client, "advance", {}))
        assert out["done"] is True and out["reward"] == 0.0
        assert len(clock.sets) == len(env.session.watches) - 1
        assert json.loads(await text(client, "advance", {}))["error"] == "the day is over"
        assert json.loads(await text(client, "get_situation", {}))["day_over"] is True


async def test_load_once_end_day_and_data(env, client):
    assert env.get()[0].data == EMPTY
    for args, why in [({"task_id": "nope"}, "unknown task id 'nope'"),
                      ({"task_id": NOTICE_DAY["task_id"], "tier": "bid10"}, "unknown tier 'bid10'")]:
        with pytest.raises(ValueError, match=why):
            env.live_load(**args)
    assert env.live_load(NOTICE_DAY["task_id"], "blind") == {"task_id": NOTICE_DAY["task_id"], "tier": "blind",
                                                            "watches": len(Session(NOTICE_DAY, "blind").watches)}
    with pytest.raises(ValueError, match="each live day needs a new deploy"):
        env.live_load(NOTICE_DAY["task_id"])
    end = env.end_day()
    assert (end["end_reason"], end["reward"], end["audit"]["ok"]) == ("end_day", 0.0, True)
    data = env.get()[0].data
    assert data["done"] and [n["via"] for n in data["notices"]] == ["load", "env"]
    env.reset()
    assert env.get()[0].data == EMPTY
    result = await client.call_tool_mcp("get_situation", {})
    assert result.isError and "no day loaded" in result.content[0].text


async def test_the_image_entry_point_serves_gridsim_live_when_named():
    with live_server() as base:
        card = httpx.get(f"{base}/.well-known/agent-env.json").json()
        assert card["name"] == LIVE_ENV
        assert {e["uri"] for e in card["capabilities"]["extensions"]} >= {
            "urn:gridsim:live-load/v1", "urn:gridsim:end-day/v1", "urn:agentenv:clock/v1"}
