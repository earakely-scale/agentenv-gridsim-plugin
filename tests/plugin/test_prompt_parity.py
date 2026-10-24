"""Prompt parity: what gridsim-llm sends the model in a bundle (system prompt, opening message and tool schemas, as
the running env lists the tools) is byte-identical to gridsim_core.prompt's path-B messages and tool schemas."""

import json

import gridsim_llm
import pytest
from conftest import BLIND, FIXTURES

from agentenv_gridsim import tasks
from agentenv_gridsim.server import DISABLE_URI
from gridsim_core.prompt import messages, tool_schemas

pytestmark = pytest.mark.anyio
CASES = [(t, tier, bundle) for bundle in tasks.BUNDLES for t, tier in [(FIXTURES[0], "foresight"), (BLIND[0], "blind")]]
IDS = [f"{bundle}-{tier}" for _, tier, bundle in CASES]


def wire(tools: list[gridsim_llm.Tool]) -> str:
    """The tools as gridsim-llm's chat-completions adapter sends them."""
    return json.dumps(gridsim_llm.ChatAgent("m", tools, "s", 1, "http://x/v1", "k").tools)


@pytest.mark.parametrize(("task", "tier", "bundle"), CASES, ids=IDS)
def test_the_bundles_prompts_are_path_bs_messages(task, tier, bundle):
    play = next(s for s in tasks.steps(task, tier, bundle) if s["type"] == "prompt_agent")
    system, user = messages(task, tier, tasks.BUNDLES[bundle])
    assert play["system_prompt"] == system["content"]
    assert play["prompt"] == user["content"]


@pytest.mark.parametrize(("task", "tier", "bundle"), CASES, ids=IDS)
async def test_the_tools_the_agent_sends_are_path_bs_schemas(harness, task, tier, bundle):
    checks = tasks.BUNDLES[bundle]
    await harness.load_task(task, tier, checks)
    for step in tasks.steps(task, tier, bundle):
        if step["type"] == "modify_env_tool_access":
            await harness.invoke(DISABLE_URI, {"role": step["role"], "tools": step["tools"]}, method="disable")
    try:
        async with harness.session() as session:
            listed = await gridsim_llm.EnvSession(session).tools()
    finally:
        await harness.invoke("urn:agentenv:enable-tool/v1", {"role": "default", "tools": tasks.HIDDEN_IN_ONESHOT},
                             method="enable")
    assert wire(listed) == json.dumps(tool_schemas(tier, checks, get_situation=bundle == "full"))


def test_the_oneshot_bundle_hides_every_tool_but_submit_schedule():
    steps = tasks.steps(FIXTURES[0], "foresight", "oneshot")
    assert [s for s in steps if s["type"] == "modify_env_tool_access"] == [
        {"id": "submit-only", "type": "modify_env_tool_access", "env_id": "gridsim", "action": "disable",
         "role": "default", "tools": ["get_situation", "check_schedule"]}]
    assert steps[1]["directives"][0]["args"]["checks"] == 0
