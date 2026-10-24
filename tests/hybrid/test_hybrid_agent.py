"""gridsim-llm on a hybrid day: the env lists advance and no commit_da, so the episode ends on advance's done and its
nudges speak of commit_schedule and the AS book. The scripted turns come from the fake LiteLLM; the env is the image's
entry point serving gridsim-hybrid, its clock a stand-in."""

import json

import gridsim_llm
import httpx
import pytest
from agentenv_protocol import client
from agentenv_protocol.a2a_agent import TaskOutcome, TaskRequest, TextPart
from fake_litellm import FakeLiteLLM
from hybrid_days import DAY, scripted
from live_days import FakeClock, live_server

from gridsim_core.hybrid import HYBRID_ENV, LIVE_LOAD_URI, MAX_TURNS, Session, as_hog_policy
from gridsim_core.hybrid_prompt import opening, system_prompt

pytestmark = pytest.mark.anyio
SOL = "openai/gpt-6.1-sol"


def turn(calls: list[tuple[str, dict]], t: int = 0) -> dict:
    return {"stop": "completed", "tool_calls": [{"id": f"call_{t}_{i}", "name": n, "arguments": json.dumps(a)}
                                                for i, (n, a) in enumerate(calls)]}


@pytest.fixture
def play(monkeypatch):
    """gridsim-llm on DAY at reserves in a fresh hybrid env, its clock synced to a stand-in: the result, the fake and
    the env's data/get."""
    for var in ["LITELLM_BASE_URL", "LITELLM_API_KEY", "GRIDSIM_MAX_COST_USD"]:
        monkeypatch.delenv(var, raising=False)

    async def play(turns: list[dict], **config):
        s = Session(DAY, "reserves")
        with live_server(HYBRID_ENV) as base, FakeClock(s.watch_time_utc(0)) as clock, FakeLiteLLM(turns) as fake:
            card = httpx.get(f"{base}/.well-known/agent-env.json").json()
            await client.invoke_extension(base, card, LIVE_LOAD_URI, {"task_id": DAY["task_id"], "tier": "reserves"})
            await client.invoke_extension(base, card, "urn:agentenv:clock/v1", {"env_get_time_url": clock.url})
            monkeypatch.setenv("LITELLM_BASE_URL", fake.url)
            monkeypatch.setenv("LITELLM_API_KEY", "sk-fake")
            result = await gridsim_llm.GridSimLLM().run(TaskRequest(
                task_id="t", context_id="c", parts=(TextPart(text=opening(s)),),
                config=gridsim_llm.GridSimConfig(model=SOL, system_prompt=system_prompt("reserves", s.day.era),
                                                 timeout_seconds=7200, **config),
                mcp_servers={HYBRID_ENV: {"url": f"{base}/mcp"}}))
            data = (await client.get_data(base)).parts[0].data
        return result, fake, data

    return play


def summary(result) -> dict:
    return result.parts[1].data["structured_output"]


async def test_the_day_ends_on_advances_done_with_the_stored_reward(play):
    """No gateway delivers the notices here; the deployments act at their real times all the same."""
    calls = scripted(DAY, "reserves", as_hog_policy)
    result, fake, data = await play([turn(c, t) for t, c in enumerate(calls)], max_turns=MAX_TURNS)
    record, s = result.native_trajectory.payload, summary(result)
    reward = DAY["refs"]["reserves"]["baselines"]["as_hog"]["reward"]
    assert result.outcome is TaskOutcome.SUCCEEDED
    assert (record["end_reason"], s["live"], s["reward"], data["reward"]) == ("done", True, reward, reward)
    assert (len(fake.requests), s["tool_calls"], data["calls_used"]) == (len(calls), sum(map(len, calls)),
                                                                        s["tool_calls"])


async def test_hybrid_nudges_and_the_last_turn(play):
    result, fake, data = await play([{"stop": "completed", "tool_calls": []}, turn([("get_situation", {})], 1)],
                                    max_turns=2)
    sent = [json.dumps(body["input"]) for _, _, body in fake.requests]
    assert gridsim_llm.HYBRID.no_call in sent[1] and gridsim_llm.HYBRID.last_turn in sent[1]
    assert "commit_da" not in sent[1]
    assert (summary(result)["end_reason"], summary(result)["reward"], data["done"]) == ("turn_limit", None, False)
