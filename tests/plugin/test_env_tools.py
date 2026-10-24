"""The gridsim env's tools, caps and harness surfaces, called in process through the MCP client and the middleware."""

import json

import pytest
from conftest import BLIND, OPT, TASK

from agentenv_gridsim.server import OVER
from gridsim_core.episode import check_result, submit_result
from gridsim_core.grade import grade
from gridsim_core.prompt import situation_text

pytestmark = pytest.mark.anyio
IDLE = [0] * 24


async def test_tools_are_listed_in_gridsim_cores_order(tools):
    assert [t.name for t in await tools.client.list_tools()] == ["get_situation", "check_schedule", "submit_schedule"]


async def test_get_situation_is_gridsim_cores_text_and_free(env, tools):
    result = await tools.client.call_tool_mcp("get_situation", {})
    assert result.content[0].text == situation_text(TASK, "foresight", 3)
    assert (env.checks_used, env.calls_used) == (0, 1)


async def test_check_schedule_is_gridsim_cores_check_without_grading(env, tools):
    assert await tools("check_schedule", actions=OPT) == json.loads(json.dumps(check_result(TASK, OPT, 2)))
    assert (env.done, env.reward, env.grade, env.checks_used) == (False, None, None, 1)


async def test_a_check_is_used_before_the_schedule_is_read(env, tools):
    assert await tools("check_schedule", actions="1 2 3") == {"error": "expected exactly 24 integers, got 3",
                                                             "checks_left": 2}


async def test_the_fourth_check_is_refused(env, tools):
    for left in (2, 1, 0):
        assert (await tools("check_schedule", actions=IDLE))["checks_left"] == left
    assert await tools("check_schedule", actions=IDLE) == {
        "error": "no checks left (you had 3); submit_schedule when ready"}
    assert (env.checks_used, env.calls_used, env.done) == (3, 4, False)


async def test_a_load_with_no_checks_refuses_every_check(env, tools):
    env.load_task(TASK["task_id"], "foresight", 0)
    assert (await tools("check_schedule", actions=IDLE))["error"].startswith("no checks left (you had 0)")


async def test_failed_calls_count_toward_the_limit_but_use_no_check(env, tools):
    assert (await tools.error("check_schedule")).startswith("1 validation error for call[check_schedule]")
    assert await tools.error("no_such_tool") == "Unknown tool: 'no_such_tool'"
    assert (env.checks_used, env.calls_used) == (0, 2)


async def test_the_24th_call_ends_the_episode_with_reward_0(env, tools):
    for _ in range(23):
        await tools.error("no_such_tool")
    assert not env.done
    await tools("get_situation")
    assert (env.done, env.end_reason, env.reward, env.grade, env.schedule) == (True, "tool_call_limit", 0.0, None, None)
    assert await tools.error("submit_schedule", actions=OPT) == f"Error calling tool 'submit_schedule': {OVER}"
    assert await tools.error("check_schedule", actions=OPT) == f"Error calling tool 'check_schedule': {OVER}"
    assert (env.reward, env.calls_used) == (0.0, 26)


async def test_submit_settles_once_and_the_grade_is_gridsim_cores(env, tools):
    assert await tools("submit_schedule", actions=OPT) == json.loads(json.dumps(submit_result(TASK, OPT)))
    assert (env.done, env.end_reason, env.schedule, env.reward) == (True, "submitted", OPT, 1.0)
    assert env.grade == grade(TASK, OPT, "foresight")
    assert await tools.error("submit_schedule", actions=IDLE) == f"Error calling tool 'submit_schedule': {OVER}"
    assert (env.reward, env.calls_used) == (1.0, 2)


@pytest.mark.parametrize("actions", ["not a schedule", [1.5] * 24, OPT[:23], [True] * 24, {"a": 1}])
async def test_an_unparseable_submit_uses_a_call_and_ends_nothing(env, tools, actions):
    out = await tools("submit_schedule", actions=actions)
    assert out["submitted"] is False and out["error"] == submit_result(TASK, actions)["error"]
    assert (env.done, env.reward, env.calls_used) == (False, None, 1)
    assert (await tools("submit_schedule", actions=" ".join(map(str, OPT))))["submitted"] is True
    assert env.reward == 1.0


async def test_an_out_of_range_submit_is_a_submission_that_truncates(env, tools):
    actions = [9] + OPT[1:]
    out = await tools("submit_schedule", actions=actions)
    assert (out["submitted"], out["feasible"], out["truncated_at"], out["violation"]) == (True, False, 0, "rate")
    assert env.reward == grade(TASK, actions)["reward"]


async def test_blind_checks_show_no_profit(env, tools):
    task = BLIND[0]
    env.load_task(task["task_id"], "blind")
    out = await tools("check_schedule", actions=task["refs"]["blind"]["persist"])
    assert out["profit_usd"] is None and out == json.loads(json.dumps(check_result(
        task, task["refs"]["blind"]["persist"], 2, "blind")))
    assert (await tools.client.call_tool_mcp("get_situation", {})).content[0].text == situation_text(task, "blind", 3)


async def test_hidden_tools_are_unlisted_and_unknown(env, tools):
    assert env.disable("default", ["get_situation", "check_schedule"]) == {
        "disabled": ["check_schedule", "get_situation"], "allowed": ["submit_schedule"]}
    assert [t.name for t in await tools.client.list_tools()] == ["submit_schedule"]
    assert await tools.error("check_schedule", actions=OPT) == "Unknown tool: 'check_schedule'"
    assert (env.checks_used, env.calls_used) == (0, 1)
    assert env.enable("default", ["get_situation"])["allowed"] == ["get_situation", "submit_schedule"]


async def test_no_tool_answers_before_a_task_is_loaded(env, tools):
    env.reset()
    assert await tools.error("get_situation") == "Error calling tool 'get_situation': no episode: load a task first"


@pytest.mark.parametrize(("args", "error"), [
    ({"task_id": "dam-v1-1999-01-01-HB_WEST-2h-c"}, "unknown task id 'dam-v1-1999-01-01-HB_WEST-2h-c'"),
    ({"task_id": TASK["task_id"], "tier": "psychic"}, "unknown tier 'psychic': one of foresight, blind"),
    ({"task_id": TASK["task_id"], "checks": 4}, "checks must be an integer from 0 to 3, got 4"),
    ({"task_id": TASK["task_id"], "checks": True}, "checks must be an integer from 0 to 3, got True"),
    ({"task_id": "other", "task": TASK}, f"the task row's id {TASK['task_id']!r} is not 'other'"),
])
def test_load_task_fails_loudly(env, args, error):
    with pytest.raises(ValueError) as e:
        env.load_task(**args)
    assert str(e.value) == error


def test_a_task_without_blind_inputs_has_no_blind_tier(env):
    row = dict(TASK, blind=None)
    with pytest.raises(ValueError, match="has no blind tier"):
        env.load_task(row["task_id"], "blind", task=row)


def test_an_explicit_task_row_loads_without_the_packs(env):
    row = dict(TASK, task_id="dam-v1-2030-01-01-HB_WEST-2h-c")
    assert env.load_task(row["task_id"], "foresight", 3, task=row) == {"task_id": row["task_id"], "tier": "foresight",
                                                                       "checks": 3}
    assert env.task is row
