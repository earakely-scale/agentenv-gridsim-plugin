"""gridsim-llm on a live day: the env lists advance, so the episode ends on advance's done with no tool-call cap, its
nudges speak of commits and watches, and Anthropic requests carry one rolling cache breakpoint. The scripted turns
come from the fake LiteLLM; the env is the image's entry point serving gridsim-live, its clock a stand-in."""

import json

import gridsim_llm
import httpx
import pytest
from agentenv_protocol import client
from agentenv_protocol.a2a_agent import TaskOutcome, TaskRequest, TextPart
from fake_litellm import FakeLiteLLM
from live_days import QUIET_DAY, FakeClock, live_server, naive_calls

from gridsim_core.live import LIVE_ENV, LIVE_LOAD_URI, MAX_TURNS, Session
from gridsim_core.live_prompt import messages

pytestmark = pytest.mark.anyio
SOL, SONNET = "openai/gpt-6.1-sol", "anthropic/claude-sonnet-5-5"


def turn(calls: list[tuple[str, dict]], t: int = 0, stop: str = "completed") -> dict:
    return {"stop": stop, "tool_calls": [{"id": f"call_{t}_{i}", "name": n, "arguments": json.dumps(a)}
                                         for i, (n, a) in enumerate(calls)]}


@pytest.fixture
def play(monkeypatch):
    """gridsim-llm on QUIET_DAY in a fresh live env, its clock synced to a stand-in: the result, the fake and the
    env's data/get."""
    for var in ["LITELLM_BASE_URL", "LITELLM_API_KEY", "GRIDSIM_MAX_COST_USD"]:
        monkeypatch.delenv(var, raising=False)

    async def play(turns: list[dict], model: str = SOL, **config):
        system, user = messages(Session(QUIET_DAY))
        with live_server() as base, FakeClock(Session(QUIET_DAY).watch_time_utc(0)) as clock, \
                FakeLiteLLM(turns) as fake:
            card = httpx.get(f"{base}/.well-known/agent-env.json").json()
            await client.invoke_extension(base, card, LIVE_LOAD_URI, {"task_id": QUIET_DAY["task_id"]})
            await client.invoke_extension(base, card, "urn:agentenv:clock/v1", {"env_get_time_url": clock.url})
            monkeypatch.setenv("LITELLM_BASE_URL", fake.url)
            monkeypatch.setenv("LITELLM_API_KEY", "sk-fake")
            result = await gridsim_llm.GridSimLLM().run(TaskRequest(
                task_id="t", context_id="c", parts=(TextPart(text=user["content"]),),
                config=gridsim_llm.GridSimConfig(model=model, system_prompt=system["content"], timeout_seconds=7200,
                                                 **config),
                mcp_servers={LIVE_ENV: {"url": f"{base}/mcp"}}))
            data = (await client.get_data(base)).parts[0].data
        return result, fake, data

    return play


def summary(result) -> dict:
    return result.parts[1].data["structured_output"]


async def test_the_day_ends_on_advances_done_past_24_tool_calls(play):
    calls = naive_calls(QUIET_DAY)
    calls[0] = [("get_situation", {})] * 25 + calls[0]
    result, fake, data = await play([turn(c, t) for t, c in enumerate(calls)], max_turns=MAX_TURNS)
    record, s = result.native_trajectory.payload, summary(result)
    assert result.outcome is TaskOutcome.SUCCEEDED
    reward = QUIET_DAY["refs"]["roll"]["foresight"]["naive_reward"]
    assert (record["end_reason"], s["live"], s["reward"], record["final"]) == (
        "done", True, reward, {"done": True, "reward": reward})
    assert s["tool_calls"] == len(record["steps"]) == sum(map(len, calls)) > gridsim_llm.MAX_TOOL_CALLS
    assert (len(fake.requests), data["done"], data["reward"], data["calls_used"]) == (
        len(calls), True, reward, s["tool_calls"])


async def test_live_nudges_and_the_last_turn(play):
    result, fake, data = await play([{"stop": "completed", "tool_calls": []}, turn([("get_situation", {})], 1)],
                                    max_turns=2)
    sent = [json.dumps(body["input"]) for _, _, body in fake.requests]
    assert gridsim_llm.LIVE.no_call in sent[1] and gridsim_llm.LIVE.last_turn in sent[1]
    assert (summary(result)["end_reason"], summary(result)["reward"], data["done"]) == ("turn_limit", None, False)


async def test_anthropic_requests_carry_one_rolling_cache_breakpoint(play):
    calls = naive_calls(QUIET_DAY)[:2]
    result, fake, _ = await play([dict(turn(c, t), stop="tool_use") for t, c in enumerate(calls)], SONNET,
                                 max_turns=2)
    assert [json.dumps(body).count('"cache_control"') for _, _, body in fake.requests] == [1, 1]
    newest = fake.requests[1][2]["messages"][-1]["content"][-1]
    assert newest["cache_control"] == {"type": "ephemeral"} and newest["type"] in ("tool_result", "text")
