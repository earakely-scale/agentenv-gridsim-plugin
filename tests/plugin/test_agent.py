"""gridsim-llm on scripted turns from the fake LiteLLM against the running env: its card, its routes and effort, its
stop rules, its cost and caps, and the record episodes.py replays. No model is called."""

import json

import gridsim_llm
import pytest
from agent_env.a2a_agent.a2a_agent import A2AAgent
from agentenv_protocol.a2a_agent import TaskOutcome, TaskRequest, TextPart
from conftest import OPT, TASK
from fake_litellm import FakeLiteLLM
from starlette.testclient import TestClient

from gridsim_core.prompt import messages

pytestmark = pytest.mark.anyio

KEY = "sk-fake-agent-key"
SOL, SONNET, GLM = "openai/gpt-6.1-sol", "anthropic/claude-sonnet-5-5", "fireworks_ai/glm-5p3-flash"
FORWARDED = {"model", "system_prompt", "effort", "max_turns", "timeout_seconds", "model_params"}


def call(name: str, arguments: dict | str, i: int = 0) -> dict:
    return {"id": f"call_{name}_{i}", "name": name,
            "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments)}


def turn(*calls: dict, stop: str = "completed", content: str = "", reasoning: str = "", **usage) -> dict:
    return {"content": content, "reasoning": reasoning, "stop": stop, "tool_calls": list(calls), "usage": usage}


SUBMIT = turn(call("submit_schedule", {"actions": OPT}))


def summary(result) -> dict:
    return result.parts[1].data["structured_output"]


@pytest.fixture(autouse=True)
def environ(monkeypatch):
    for var in ["LITELLM_BASE_URL", "LITELLM_API_KEY", "GRIDSIM_MAX_COST_USD"]:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def play(harness, monkeypatch):
    """Runs gridsim-llm on a fresh episode of TASK against the fake: the result and the fake."""

    async def play(turns: list[dict], model: str = SOL, *, cap: str | None = None, **config):
        await harness.load_task(TASK)
        system, user = messages(TASK, "foresight", 3)
        with FakeLiteLLM(turns) as fake:
            monkeypatch.setenv("LITELLM_BASE_URL", fake.url)
            monkeypatch.setenv("LITELLM_API_KEY", KEY)
            if cap is not None:
                monkeypatch.setenv("GRIDSIM_MAX_COST_USD", cap)
            result = await gridsim_llm.GridSimLLM().run(TaskRequest(
                task_id="t", context_id="c", parts=(TextPart(text=user["content"]),),
                config=gridsim_llm.GridSimConfig(model=model, system_prompt=system["content"], **config),
                mcp_servers={"gridsim": {"url": f"{harness.base_url}/mcp", "headers": {"x-env": "1"}}}))
        return result, fake

    return play


def test_the_card_takes_every_field_prompt_agent_forwards():
    with TestClient(gridsim_llm.GridSimLLM().create_app()) as client:
        card = client.get("/.well-known/agent-card.json").json()
    desired = {"model": SOL, "system_prompt": "s", "effort": "high", "harness": "h", "max_turns": 4,
               "max_thinking_tokens": 1, "output_format": {}, "timeout_seconds": 1800, "task_id": "t",
               "agentenv_tools": [], "model_params": {"max_tokens": 4096}}
    assert card["name"] == "gridsim-llm"
    assert A2AAgent.negotiate_agent_config(card, desired).fields.keys() == FORWARDED


def test_every_model_on_the_board_is_priced():
    assert gridsim_llm.PRICES[SOL] == (2.00, 10.00, 0.10)


@pytest.mark.parametrize(("model", "path", "effort"), [
    (SOL, "/v1/responses", {"reasoning": {"effort": "high", "summary": "auto"}}),
    (SONNET, "/v1/messages", {"output_config": {"effort": "high"}}),
    (GLM, "/v1/chat/completions", {"reasoning_effort": "high"}),
])
async def test_each_route_carries_the_effort_where_its_api_takes_it(play, model, path, effort):
    result, fake = await play([SUBMIT if model == SOL else dict(SUBMIT, stop="stop")], model, effort="high")
    [(sent, _, body)] = fake.requests
    assert result.outcome is TaskOutcome.SUCCEEDED, result
    assert (sent, body["model"]) == (path, model)
    assert {k: body[k] for k in effort} == effort
    assert summary(result)["effort"] == "high"


async def test_without_an_effort_responses_runs_at_medium(play):
    result, fake = await play([SUBMIT])
    assert fake.requests[0][2]["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert summary(result)["effort"] == "medium"


async def test_a_submit_ends_the_episode_and_later_calls_are_not_sent(play, harness):
    result, fake = await play([turn(call("get_situation", {}), call("check_schedule", {"actions": OPT}, 1)),
                               turn(call("submit_schedule", {"actions": OPT}),
                                    call("check_schedule", {"actions": OPT}, 2)),
                               SUBMIT])
    record, data = result.native_trajectory.payload, await harness.data()
    assert len(fake.requests) == 2
    assert (record["end_reason"], summary(result)["submitted"], summary(result)["checks"]) == ("submitted", True, 1)
    assert record["final"] == {"submitted": True, "schedule": OPT}
    assert [(s["t"], s["tool"]) for s in record["steps"]] == [(0, "get_situation"), (1, "check_schedule"),
                                                              (2, "submit_schedule")]
    assert record["steps"][2]["output"]["submitted"] is True and "reward" not in record["steps"][2]["output"]
    assert record["messages"][-1]["content"] == '{"error": "the episode is over"}'
    assert (data["calls_used"], data["reward"]) == (3, 1.0)


async def test_an_unparseable_submit_does_not_end_the_episode(play, harness):
    result, _ = await play([turn(call("submit_schedule", {"actions": "1 2 3"})), SUBMIT])
    record = result.native_trajectory.payload
    assert record["steps"][0]["output"] == {"submitted": False, "error": "expected exactly 24 integers, got 3"}
    assert (record["end_reason"], (await harness.data())["reward"]) == ("submitted", 1.0)


async def test_the_last_turn_asks_for_the_submit(play):
    result, fake = await play([turn(call("get_situation", {}))] * 3 + [SUBMIT])
    assert summary(result)["turns"] == 4 and summary(result)["end_reason"] == "submitted"
    assert gridsim_llm.LAST_TURN in json.dumps(fake.requests[3][2]["input"][-1])


async def test_no_submit_in_four_turns_is_a_turn_limit(play, harness):
    result, _ = await play([turn(call("get_situation", {}))] * 4)
    assert summary(result)["end_reason"] == "turn_limit" and not summary(result)["submitted"]
    assert (await harness.data())["done"] is False


async def test_the_24th_call_ends_the_episode(play, harness):
    result, _ = await play([turn(*[call("get_situation", {}, i) for i in range(30)])])
    record = result.native_trajectory.payload
    assert (record["end_reason"], len(record["steps"]), summary(result)["tool_calls"]) == ("tool_call_limit", 24, 24)
    data = await harness.data()
    assert (data["calls_used"], data["done"], data["end_reason"], data["reward"]) == (24, True, "tool_call_limit", 0.0)


async def test_cost_is_usage_times_the_price(play):
    result, _ = await play([turn(call("submit_schedule", {"actions": OPT}), input=10000, output=2000, cached=4000)])
    assert summary(result)["cost_usd"] == pytest.approx((6000 * 2.0 + 4000 * 0.1 + 2000 * 10.0) / 1e6)


async def test_an_episode_stops_before_a_request_that_could_pass_its_cap(play):
    result, fake = await play([SUBMIT], cap="0.001")
    assert fake.requests == [] and result.outcome is TaskOutcome.FAILED
    assert summary(result)["end_reason"] == "cost_cap"


async def test_an_unpriced_model_never_calls(play):
    result, fake = await play([SUBMIT], "openai/unknown-model")
    assert fake.requests == [] and summary(result)["end_reason"] == "unpriced_model"
