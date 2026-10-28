"""Tool-surface parity: one scripted action list played on gridsim_core.desk's Session in process (path B') and through
the gridsim-desk env's MCP server, woken by its hidden next_wakeup / advance_to tools as the post-turn hook wakes it
(path A's server), gives byte-identical tool outputs and wake messages, the same Episode JSON and the same grade."""

import json

import pytest
from desk_util import anyio_backend, pack  # noqa: F401
from fastmcp import Client

from agentenv_gridsim.desk import DESK_ENVS, HIDDEN, desk_env, env_name
from gridsim_core.desk import Session, fixtures, grade, policies, text, tool_specs

pytestmark = pytest.mark.anyio

MALFORMED = [("submit_dam_offers", {"day": "D0", "curves": "all of them"}),
             ("get_prices", {"market": "nowhere"}),
             ("set_reminder", {"at": "D0 14:37", "note": "off the grid"}),
             ("set_reminder", {"at": "D0 14:35", "note": "check the evening ramp"}),
             ("check_submission", {"kind": "dam", "payload": {"curves": [{"hours": "HE07", "points": [[0, 1]]}]}}),
             ("get_asset_status", {"surprise": 1}),
             ("update_cop", {"rows": [{"hours": "HE30", "status": "ON"}]})]


class Recorder:
    """Path B': the Session, every call recorded with its output text."""

    def __init__(self, session):
        self.__dict__.update(_s=session, calls=[], outs=[])

    def __getattr__(self, name):
        return getattr(self._s, name)

    def call(self, name, args=None, role="default"):
        out = self._s.call(name, args, role)
        self.calls.append((name, args or {}))
        self.outs.append(text(out))
        return out


def script(task, series, policy):
    """The policy's calls per turn, recorded on path B', each turn's reply, and B''s outputs and wakes as text."""
    s = Session(task, series)
    rec, turns, wakes = Recorder(s), [], [text(wake := s.start())]
    while wake is not None:
        first = len(rec.calls)
        if not turns:
            for name, args in MALFORMED:
                rec.call(name, args)
        policy(rec, wake)
        reply = f"turn {len(turns)} done"
        turns.append((rec.calls[first:], reply))
        wake = s.end_turn(reply)
        wakes.append(None if wake is None else text(wake))
    return s, turns, rec.outs, wakes


async def hidden(client, name, args=None):
    return json.loads((await client.call_tool(name, args or {})).content[0].text)


@pytest.mark.parametrize("policy", ["anchor", "scripted"])
async def test_gateway_server_matches_session(tmp_path, policy):
    task, series = fixtures.make(seed=3, outage=True)
    b, turns, outs, wakes = script(task, series, policies.POLICIES[policy])
    env = desk_env(env_name("v2", task["era"]))
    started = env.load(task["task_id"], pack(tmp_path, task, series))
    got_outs, got_wakes = [], [text(started["start"])]
    async with Client(env.create_app()) as client:
        for calls, reply in turns:
            for name, args in calls:
                got_outs.append((await client.call_tool(name, args, raise_on_error=False)).content[0].text)
            nxt = await hidden(client, "next_wakeup")
            minute = nxt["at"] if nxt["at"] is not None else nxt["end"]
            out = await hidden(client, "advance_to", {"minute": minute, "reply": reply})
            got_wakes.append(out["message"])
        assert (await hidden(client, "next_wakeup"))["done"]
        assert await hidden(client, "episode") == json.loads(text(b.episode()))
        assert await hidden(client, "grade") == json.loads(text(grade(b)))
    assert got_outs == outs
    assert got_wakes == wakes
    assert len(turns) > 3 and any("reminder" in json.loads(w)["reasons"] for w in wakes[1:-1])


async def test_tools_listed_as_core_specs(tmp_path):
    for name, (layer, rtcb) in DESK_ENVS.items():
        async with Client(desk_env(name).create_app()) as client:
            listed = await client.list_tools()
        want = [s["function"] for s in tool_specs(layer, rtcb)]
        assert [(t.name, t.description, t.inputSchema) for t in listed[:len(want)]] == \
            [(w["name"], w["description"], w["parameters"]) for w in want]
        assert [t.name for t in listed[len(want):]] == list(HIDDEN)
        assert all(t.meta and t.meta.get("agentenv.io/hiddenByDefault") for t in listed[len(want):])
