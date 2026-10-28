"""The gridsim-desk-hook post-turn hook against the desk env's server and a frozen clock: it wakes the agent with the
messages end_turn gives in process, at their times, ends the conversation with episode_over once the desk has nothing
left, and on the conversation's last turn runs the market to the end without waking anyone."""

import importlib.util
import json
from importlib.resources import files

import pytest
from desk_util import anyio_backend, pack  # noqa: F401
from fastmcp import Client

from agentenv_gridsim.desk import desk_env, env_name
from gridsim_core.desk import Session, fixtures, text
from gridsim_core.desk.clock import START, to_utc

pytestmark = pytest.mark.anyio

CLOCK = "urn:agentenv:clock/v1"
TRIGGERS = "urn:agentenv:triggers/v1"
HOOK = files("agentenv_gridsim.bundles") / "gridsim-desk/artifacts/gridsim-desk-hook/hook.py"


def hook_module():
    spec = importlib.util.spec_from_file_location("gridsim_desk_hook", str(HOOK))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Env:
    env_id = "gridsim-desk-v2"

    def __init__(self, client, t0, trigger_at=None):
        self.client, self.time, self.roles, self.trigger_at = client, t0, [], trigger_at

    def supports(self, extension, method):
        return extension == CLOCK or extension == TRIGGERS and self.trigger_at is not None

    async def invoke(self, extension, method, params=None):
        if extension == TRIGGERS:
            due = self.trigger_at if self.trigger_at > self.time else None
            return {"next_event_at": due, "triggers": [{"status": "fired" if due is None else "armed"}]}
        if method == "advance":
            assert params["virtual_time"] >= self.time
            self.time = params["virtual_time"]
        return {"armed": True, "virtual_time": self.time}

    async def call_tool(self, tool, args, role):
        self.roles.append(role)
        result = await self.client.call_tool(tool, args, raise_on_error=False)
        return {"content": [{"type": "text", "text": result.content[0].text}], "isError": result.is_error}


class Turn:
    def __init__(self, env, number, last, reply):
        self.envs, self.number, self.last, self.agent_reply, self.records = [env], number, last, reply, []

    def record(self, entry):
        self.records.append(entry)

    def heartbeat(self):
        pass


@pytest.mark.parametrize("cut", [None, 5])
async def test_hook_wakes_as_end_turn(tmp_path, cut):
    hook = hook_module()
    task, series = fixtures.make(seed=1)
    shadow = Session(task, series)
    wakes = [text(shadow.start())]
    env = desk_env(env_name("v2", task["era"]))
    env.load(task["task_id"], pack(tmp_path, task, series))
    async with Client(env.create_app()) as client:
        gateway = Env(client, to_utc(START, task["dates"][0]))
        k = 0
        while True:
            reply = f"turn {k}"
            turn = Turn(gateway, k, k == cut, reply)
            answer = await hook.post_turn(turn, {"env_id": gateway.env_id})
            wake = shadow.end_turn(reply) if k != cut else None
            if k == cut:
                assert answer is None and env.session.done
                assert [r["end"] for r in turn.records] == ["episode_over"] and turn.records[0]["passed"]
                break
            if wake is None:
                assert answer == {"end": "episode_over"} and env.session.done
                break
            assert answer == {"message": text(wake)}
            assert turn.records[-1]["at"] == gateway.time == to_utc(shadow.now, task["dates"][0])
            wakes.append(answer["message"])
            k += 1
        assert set(gateway.roles) == {"hook"}
        if cut is None:
            episode = json.loads((await client.call_tool("episode", {})).content[0].text)
            assert episode == json.loads(text(shadow.episode()))


async def test_an_earlier_gateway_trigger_wakes_the_agent_at_its_minute(tmp_path):
    hook = hook_module()
    task, series = fixtures.make(seed=1)
    d0 = task["dates"][0]
    shadow = Session(task, series)
    shadow.start()
    env = desk_env(env_name("v2", task["era"]))
    env.load(task["task_id"], pack(tmp_path, task, series))
    async with Client(env.create_app()) as client:
        gateway = Env(client, to_utc(START, d0), trigger_at=to_utc(-1000, d0).replace(":00Z", ":30Z"))
        turn = Turn(gateway, 1, False, "first")
        answer = await hook.post_turn(turn, {})
    shadow.close_turn("first")
    assert answer == {"message": text(shadow.advance_to(-999))}
    assert (turn.records[-1]["minute"], turn.records[-1]["reasons"]) == (-999, ["gateway"])
    assert gateway.time == to_utc(-999, d0)
