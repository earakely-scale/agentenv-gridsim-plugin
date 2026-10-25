"""gridsim-llm on a market floor: the env lists submit_offer, so a floor-sprint (no advance) ends on submit_offer's done
and a floor-day on advance's done, its nudges speaking of the DAM offer, its cost guard under a market tier's cap. The
scripted turns come from the fake LiteLLM; the env is the image's entry point serving gridsim-market, its clock a
stand-in."""

import json

import gridsim_llm
import httpx
import pytest
from agentenv_protocol import client
from agentenv_protocol.a2a_agent import TaskOutcome, TaskRequest, TextPart
from fake_litellm import FakeLiteLLM
from live_days import FakeClock, live_server
from market_floors import DAY, policies, scripted

from agentenv_gridsim import market_tasks
from gridsim_core.market import LOAD_URI, MARKET_ENV, MAX_TURNS, Session
from gridsim_core.market_prompt import opening, system_prompt

pytestmark = pytest.mark.anyio
SOL = "openai/gpt-6.1-sol"
PAD = "x" * 10_000


def turn(calls: list[tuple[str, dict]], t: int = 0, **extra) -> dict:
    return {"stop": "completed", "tool_calls": [{"id": f"call_{t}_{i}", "name": n, "arguments": json.dumps(a)}
                                                for i, (n, a) in enumerate(calls)], **extra}


@pytest.fixture
def play(monkeypatch):
    """gridsim-llm on DAY at a tier in a fresh market env, its clock synced to a stand-in: the result, the fake and the
    env's data/get."""
    for var in ["LITELLM_BASE_URL", "LITELLM_API_KEY", "GRIDSIM_MAX_COST_USD"]:
        monkeypatch.delenv(var, raising=False)

    async def play(turns: list[dict], tier: str, **config):
        s = Session(DAY, tier)
        with live_server(MARKET_ENV) as base, FakeClock(s.watch_time_utc(0)) as clock, FakeLiteLLM(turns) as fake:
            card = httpx.get(f"{base}/.well-known/agent-env.json").json()
            await client.invoke_extension(base, card, LOAD_URI, {"floor_id": DAY["task_id"], "tier": tier})
            await client.invoke_extension(base, card, "urn:agentenv:clock/v1", {"env_get_time_url": clock.url})
            monkeypatch.setenv("LITELLM_BASE_URL", fake.url)
            monkeypatch.setenv("LITELLM_API_KEY", "sk-fake")
            result = await gridsim_llm.GridSimLLM().run(TaskRequest(
                task_id="t", context_id="c", parts=(TextPart(text=opening(s)),),
                config=gridsim_llm.GridSimConfig(model=SOL, system_prompt=system_prompt(tier), timeout_seconds=3600,
                                                 **{"max_turns": MAX_TURNS[tier]} | config),
                mcp_servers={MARKET_ENV: {"url": f"{base}/mcp"}}))
            data = (await client.get_data(base)).parts[0].data
        return result, fake, data

    return play


def summary(result) -> dict:
    return result.parts[1].data["structured_output"]


async def test_a_sprint_ends_on_submit_offers_done(play):
    calls = scripted(DAY, "floor-sprint", policies(DAY)["anchor"])
    result, fake, data = await play([turn([("get_private_costs", {})], 0), turn(calls[0], 1)], "floor-sprint")
    record, s = result.native_trajectory.payload, summary(result)
    assert result.outcome is TaskOutcome.SUCCEEDED
    assert (record["end_reason"], s["submitted"], s.get("live"), data["reward"]) == ("submitted", True, None, 1.0)
    assert record["final"] == {"submitted": True, "offer": calls[0][0][1]["offer"]}
    assert (len(fake.requests), s["tool_calls"], data["calls_used"]) == (2, 2, 2)
    assert {t["name"] for t in fake.requests[0][2]["tools"]} >= {"submit_offer", "check_offer", "get_disclosure"}


async def test_a_refused_offer_does_not_end_the_sprint_and_the_nudges_speak_of_the_offer(play):
    bad = ("submit_offer", {"offer": {"hours": [{"he": 1, "sell": [[1.5, 20]]}]}})
    result, fake, data = await play([turn([bad], 0), {"stop": "completed", "tool_calls": []},
                                     turn([("get_situation", {})], 2)], "floor-sprint", max_turns=3)
    sent = [json.dumps(body["input"]) for _, _, body in fake.requests]
    assert gridsim_llm.SPRINT.no_call in sent[2] and gridsim_llm.SPRINT.last_turn in sent[2]
    assert "commit_schedule" not in sent[2]
    assert (summary(result)["end_reason"], data["done"], data["refusals"][0]["issues"][0]["rule"]) == (
        "turn_limit", False, "grid")


async def test_a_floor_day_ends_on_advances_done(play):
    calls = scripted(DAY, "floor-day", policies(DAY)["anchor"])
    result, fake, data = await play([turn(c, t) for t, c in enumerate(calls)], "floor-day")
    record, s = result.native_trajectory.payload, summary(result)
    assert (record["end_reason"], s["live"], s["reward"], data["reward"], data["done"]) == ("done", True, None, 1.0,
                                                                                            True)
    assert record["final"] == {"done": True, "reward": None} and len(fake.requests) == len(calls)
    sent = json.dumps(fake.requests[0][2]["tools"])
    assert "advance" in sent and "propose_contract" in sent


async def test_floor_day_nudges(play):
    result, fake, _ = await play([{"stop": "completed", "tool_calls": []}, turn([("get_situation", {})], 1)],
                                 "floor-day", max_turns=2)
    sent = [json.dumps(body["input"]) for _, _, body in fake.requests]
    assert gridsim_llm.FLOOR.no_call in sent[1] and gridsim_llm.FLOOR.last_turn in sent[1]


async def test_the_cost_guard_stops_a_sprint_before_the_tier_cap(play, monkeypatch):
    """A sprint whose turns each read 20,000 fresh input tokens and write 20,000: the guard books each turn's usage and
    stops before the request whose estimate (its input plus the most output a reply used) would pass the $1 sprint
    cap."""
    cap = market_tasks.EPISODE_CAP_USD["floor-sprint"]
    monkeypatch.setenv("GRIDSIM_MAX_COST_USD", format(cap, "g"))
    turns = [turn([("get_situation", {})], t, content=PAD, usage={"input": 20000, "output": 20000, "cached": 0})
             for t in range(MAX_TURNS["floor-sprint"])]
    result, fake, data = await play(turns, "floor-sprint", model_params=market_tasks.MODEL_PARAMS["floor-sprint"])
    s, per_turn = summary(result), (20000 * 2.00 + 20000 * 10.00) / 1e6
    n = len(fake.requests)
    assert (s["end_reason"], data["done"]) == ("cost_cap", False) and n == 4
    assert s["cost_usd"] == pytest.approx(n * per_turn) and s["cost_usd"] <= cap < s["cost_usd"] + per_turn
