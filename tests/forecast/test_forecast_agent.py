"""gridsim-llm on a forecast window: the env lists submit_dam, so the episode ends on advance's done, its nudges speak
of DAM gates, and the first advance that would leave an open gate with nothing accepted there is held back once. The
scripted turns come from the fake LiteLLM; the env is the image's entry point serving gridsim-forecast, its clock a
stand-in."""

import json

import gridsim_llm
import httpx
import pytest
from agentenv_protocol import client
from agentenv_protocol.a2a_agent import TaskOutcome, TaskRequest, TextPart
from fake_litellm import FakeLiteLLM
from forecast_days import ROWS, anchor, in_process, scripted
from live_days import FakeClock, live_server

from agentenv_gridsim import forecast_tasks
from gridsim_core.forecast import FORECAST_ENV, FORECAST_LOAD_URI, MAX_TURNS, Session
from gridsim_core.forecast_prompt import opening, system_prompt

pytestmark = pytest.mark.anyio
SOL = "openai/gpt-6.1-sol"
QUIET = next(r for r in ROWS if not r["notices"] and not r["deployments"])


def turn(calls: list[tuple[str, dict]], t: int = 0) -> dict:
    return {"stop": "completed", "tool_calls": [{"id": f"call_{t}_{i}", "name": n, "arguments": json.dumps(a)}
                                                for i, (n, a) in enumerate(calls)]}


@pytest.fixture
def play(monkeypatch):
    """gridsim-llm on a window at a tier in a fresh forecast env, its clock synced to a stand-in: the result, the fake
    and the env's data/get."""
    for var in ["LITELLM_BASE_URL", "LITELLM_API_KEY", "GRIDSIM_MAX_COST_USD"]:
        monkeypatch.delenv(var, raising=False)

    async def play(turns: list[dict], task: dict = QUIET, tier: str = "front", **config):
        s = Session(task, tier)
        with live_server(FORECAST_ENV) as base, FakeClock(s.watch_time_utc(0)) as clock, FakeLiteLLM(turns) as fake:
            card = httpx.get(f"{base}/.well-known/agent-env.json").json()
            await client.invoke_extension(base, card, FORECAST_LOAD_URI, {"task_id": task["task_id"], "tier": tier})
            await client.invoke_extension(base, card, "urn:agentenv:clock/v1", {"env_get_time_url": clock.url})
            monkeypatch.setenv("LITELLM_BASE_URL", fake.url)
            monkeypatch.setenv("LITELLM_API_KEY", "sk-fake")
            result = await gridsim_llm.GridSimLLM().run(TaskRequest(
                task_id="t", context_id="c", parts=(TextPart(text=opening(s)),),
                config=gridsim_llm.GridSimConfig(model=SOL, system_prompt=system_prompt(tier, s.win.era, s.source),
                                                 timeout_seconds=forecast_tasks.PLAY_SECONDS,
                                                 model_params=forecast_tasks.MODEL_PARAMS, **config),
                mcp_servers={FORECAST_ENV: {"url": f"{base}/mcp"}}))
            data = (await client.get_data(base)).parts[0].data
        return result, fake, data

    return play


def summary(result) -> dict:
    return result.parts[1].data["structured_output"]


def sent(fake) -> list[str]:
    return [json.dumps(body["input"]) for _, _, body in fake.requests]


@pytest.mark.parametrize("tier", ["front", "blind"])
async def test_the_window_ends_on_advances_done_with_the_anchors_reward(play, tier):
    calls = scripted(QUIET, tier, anchor(tier))
    result, fake, data = await play([turn(c, t) for t, c in enumerate(calls)], tier=tier, max_turns=MAX_TURNS[tier])
    record, s = result.native_trajectory.payload, summary(result)
    g = in_process(QUIET, tier, calls)[0].grade()
    assert result.outcome is TaskOutcome.SUCCEEDED
    assert (record["end_reason"], s["live"], s["reward"], data["reward"], s["gate_nudges"]) == (
        "done", True, g["reward"], g["reward"], 0)
    assert data["grade"]["profit_usd"] == g["profit_usd"] and data["audit"]["ok"]
    assert (len(fake.requests), s["tool_calls"], data["calls_used"]) == (len(calls), sum(map(len, calls)),
                                                                        s["tool_calls"])


async def test_forecast_nudges_and_the_last_turn(play):
    result, fake, data = await play([{"stop": "completed", "tool_calls": []}, turn([("get_situation", {})], 1)],
                                    max_turns=2)
    text = sent(fake)[1]
    assert gridsim_llm.FORECAST.no_call in text and gridsim_llm.FORECAST.last_turn in text
    assert "commit_da" not in text and "submit_dam" in gridsim_llm.FORECAST.last_turn
    assert (summary(result)["end_reason"], summary(result)["reward"], data["done"]) == ("turn_limit", None, False)


async def test_an_advance_that_would_leave_an_open_gate_unbid_is_held_back_once(play):
    s = Session(QUIET, "front")
    gate = next(w.index for w in s.watches if w.minute == 600)
    k = 1
    bid = ("submit_dam", {"operating_day": s.day_date(k), "plan": {"energy": [0] * 24}})
    turns = [turn([("advance", {})], 0), turn([("advance", {})], 1)]
    turns += [turn([("advance", {})], t) for t in range(2, gate + 1)]
    turns += [turn([bid, ("advance", {})], gate + 1), turn([("get_situation", {})], gate + 2)]
    result, fake, data = await play(turns, max_turns=len(turns))
    record = result.native_trajectory.payload
    outs = [m["content"] for m in record["messages"] if m["role"] == "tool"]
    assert [i for i, o in enumerate(outs) if gridsim_llm.GATE_OPEN in o] == [0] and gridsim_llm.GATE_OPEN in sent(
        fake)[1]
    assert [st["tool"] for st in record["steps"]][:1] == ["advance"] and summary(result)["gate_nudges"] == 1
    assert data["watch"] == gate + 1 and data["dam"][k]["accepted"] == list(range(24))
    assert data["dam"][0]["accepted"] == [] and data["calls_used"] == len(turns)


async def test_a_gate_with_a_refused_bid_still_holds_the_advance_back(play):
    s = Session(QUIET, "front")
    bad = ("submit_dam", {"operating_day": s.day_date(0), "plan": {"energy": "keep"}})
    turns = [turn([bad, ("advance", {})], 0), turn([("advance", {})], 1), turn([("get_situation", {})], 2)]
    result, fake, data = await play(turns, max_turns=3)
    tool_out = [m["content"] for m in result.native_trajectory.payload["messages"] if m["role"] == "tool"]
    assert "leave" not in tool_out[0] and "energy is always sent" in tool_out[0]
    assert json.loads(tool_out[1]) == {"error": gridsim_llm.GATE_OPEN} and data["watch"] == 1


def sol_paced(growth: int) -> list[dict]:
    """The anchor's window one call a turn with a get_situation after each advance, at Sol's v3 pace: input from
    8,000 tokens growing by ``growth`` a turn, all but the newest turn's tokens read from the cache, 580 output
    tokens a turn."""
    calls = [[c] for watch in scripted(QUIET, "front", anchor("front")) for c in watch]
    return [dict(turn(c, t), usage={"input": 8000 + growth * t, "output": 580,
                                    "cached": 8000 + growth * (t - 1) if t else 0}) for t, c in enumerate(calls)]


@pytest.mark.parametrize("growth", [1800, 3600])
async def test_the_episode_cap_covers_a_front_window_at_sols_pace(play, monkeypatch, growth):
    monkeypatch.setenv("GRIDSIM_MAX_COST_USD", format(forecast_tasks.EPISODE_CAP_USD, "g"))
    turns = sol_paced(growth)
    result, fake, data = await play(turns, max_turns=MAX_TURNS["front"])
    s = summary(result)
    spent = sum(gridsim_llm.cost(dict(t["usage"], cache_write=0), gridsim_llm.PRICES[SOL]) for t in turns)
    assert (s["end_reason"], s["turns"], data["done"], data["audit"]["ok"]) == ("done", len(turns), True, True)
    assert s["cost_usd"] == pytest.approx(spent) and spent < forecast_tasks.EPISODE_CAP_USD / 2
