"""The gridsim-hybrid env in process through the MCP client and its middleware: its tools are gridsim_core's, every
call reaches the hybrid Session as sent and answers with its exact output, a deployment's payload arrives through
grid_notice, advance moves the gateway clock to each watch it opens, and the harness extensions load, end and report
one day."""

import json

import httpx
import pytest
from hybrid_days import DAY, in_process, scripted
from live_days import FakeClock, live_server

from agentenv_gridsim.hybrid import EMPTY, HYBRID_NOTICE_SCHEMA
from gridsim_core.hybrid import HYBRID_ENV, NOTICE_TOOL, TOOLS, Session, as_hog_policy, idle_policy, sponge_policy
from gridsim_core.hybrid_prompt import tool_schemas

pytestmark = pytest.mark.anyio
POLICIES = {"idle": idle_policy, "sponge": sponge_policy, "as_hog": as_hog_policy}


async def text(client, name: str, args: dict) -> str:
    result = await client.call_tool_mcp(name, args)
    assert not result.isError, result.content[0].text
    return result.content[0].text


async def play(env, client, task: dict, tier: str, calls: list) -> tuple[list[str], list[dict]]:
    """The calls through the client, the triggers' grid_notice calls after each advance that opens a watch; the
    outputs and the clock's sets."""
    env.live_load(task["task_id"], tier)
    outs = []
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for name, args in (c for watch in calls for c in watch):
            outs.append(await text(client, name, args))
            if name == "advance" and "watch" in json.loads(outs[-1]):
                for n in env.session.watches[env.session.watch].notices:
                    await text(client, NOTICE_TOOL, n.args())
    return outs, clock.sets


@pytest.mark.parametrize("tier", ["energy", "reserves"])
async def test_the_tools_are_gridsim_cores_in_its_order(env, client, tier):
    env.live_load(DAY["task_id"], tier)
    tools = await client.list_tools()
    assert [t.name for t in tools] == [*TOOLS, NOTICE_TOOL]
    want = {s["function"]["name"]: s["function"] for s in tool_schemas(tier)}
    for t in tools[:-1]:
        assert (t.description, t.inputSchema) == (want[t.name]["description"], want[t.name]["parameters"])
    assert (tools[-1].description, tools[-1].inputSchema) == (HYBRID_NOTICE_SCHEMA["description"],
                                                              HYBRID_NOTICE_SCHEMA["parameters"])
    assert "deploy" in tools[-1].inputSchema["properties"]


@pytest.mark.parametrize(("policy", "tier"), [("as_hog", "reserves"), ("sponge", "energy"), ("idle", "reserves")])
async def test_a_day_through_the_env_is_the_sessions_byte_for_byte(env, client, policy, tier):
    calls = scripted(DAY, tier, POLICIES[policy])
    outs, sets = await play(env, client, DAY, tier, calls)
    played, want = in_process(DAY, tier, calls)
    assert outs == want
    assert env.session.transcript == played.transcript and env.session.data() == played.data()
    assert sets == [{"virtual_time": w.time_utc, "virtual_seconds_per_real_second": 0} for w in played.watches[1:]]
    assert env.session.done and env.session.audit()["ok"]
    deploys = [n.event_id for w in played.watches for n in w.notices if n.deploy]
    assert deploys and {e["event_id"] for e in env.session.log if e["via"] == "trigger"} >= set(deploys)
    refs = DAY["refs"]
    stored = 0.0 if policy == "idle" else refs[tier]["baselines"][policy]["reward"]
    assert env.session.grade()["reward"] == stored


async def test_a_notice_whose_payload_differs_from_the_schedule_fails_the_audit(env, client):
    env.live_load(DAY["task_id"], "reserves")
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
    end = env.end_day()
    assert not end["audit"]["ok"] and any("differs from the schedule" in p for p in end["audit"]["problems"])


async def test_a_malformed_call_gets_the_sessions_answer_and_uses_a_planning_call(env, client):
    env.live_load(DAY["task_id"], "reserves")
    s = Session(DAY, "reserves")
    for name, args in [("check_schedule", {"plan": {"regup": [{"from": 0, "to": 4, "mw": 25}]}, "from_hour": 0}),
                       ("commit_schedule", {"plan": {"energy": "1 2"}, "from_hour": 0, "start": "00:00"}),
                       ("commit_schedule", {"from_hour": 3}), ("get_situation", {"x": 1})]:
        assert await text(client, name, args) == s.call(name, args)
    assert env.session.planning_calls == [3] and env.session.calls == 4


async def test_advance_needs_the_synced_clock_and_moves_nothing_without_it(env, client):
    env.live_load(DAY["task_id"], "reserves")
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
    env.live_load(DAY["task_id"], "energy")
    with FakeClock(env.session.watch_time_utc(0)) as clock:
        await env.sync_time(clock.url)
        for _ in env.session.watches:
            out = json.loads(await text(client, "advance", {}))
        assert out["done"] is True and out["reward"] == 0.0 and "watch" not in out
        assert len(clock.sets) == len(env.session.watches) - 1
        assert json.loads(await text(client, "advance", {}))["error"] == "the day is over"
        assert json.loads(await text(client, "get_situation", {}))["day_over"] is True


async def test_load_once_end_day_and_data(env, client):
    assert env.get()[0].data == EMPTY
    for args, why in [({"task_id": "nope"}, "unknown task id 'nope'"),
                      ({"task_id": DAY["task_id"], "tier": "foresight"}, "unknown tier 'foresight'"),
                      ({"task_id": DAY["task_id"], "tier": "rtcb"}, "not an rtcb day")]:
        with pytest.raises(ValueError, match=why):
            env.live_load(**args)
    assert env.live_load(DAY["task_id"]) == {"task_id": DAY["task_id"], "tier": "reserves",
                                             "watches": len(Session(DAY, "reserves").watches)}
    with pytest.raises(ValueError, match="each live day needs a new deploy"):
        env.live_load(DAY["task_id"])
    end = env.end_day()
    assert (end["end_reason"], end["reward"], end["audit"]["ok"]) == ("end_day", 0.0, True)
    data = env.get()[0].data
    assert data["done"] and set(data) == set(EMPTY) and {n["via"] for n in data["notices"]} <= {"load", "env"}
    env.reset()
    assert env.get()[0].data == EMPTY
    result = await client.call_tool_mcp("get_situation", {})
    assert result.isError and "no day loaded" in result.content[0].text


async def test_the_image_entry_point_serves_gridsim_hybrid_when_named():
    with live_server(HYBRID_ENV) as base:
        card = httpx.get(f"{base}/.well-known/agent-env.json").json()
        assert card["name"] == HYBRID_ENV
        assert {e["uri"] for e in card["capabilities"]["extensions"]} >= {
            "urn:gridsim:live-load/v1", "urn:gridsim:end-day/v1", "urn:agentenv:clock/v1"}
        assert {t["name"] for t in card["capabilities"]["tools"]} == {*TOOLS, NOTICE_TOOL}
