"""gridsim-verifier against a stand-in env's data/get: what it scores, and when it refuses to."""

import asyncio
import socket
from contextlib import asynccontextmanager

import pytest
import uvicorn
from agentenv_protocol import AgentEnvEnvironment, DataPart, environment_card, get_data
from conftest import OPT, TASK
from test_grader_parity import verifier

from gridsim_core.grade import grade

pytestmark = pytest.mark.anyio


def episode(**fields) -> dict:
    return {"task_id": TASK["task_id"], "tier": "foresight", "checks": 3, "checks_used": 0, "calls_used": 0,
            "done": False, "end_reason": None, "schedule": None, "grade": None, "reward": None, "task": None} | fields


def submitted(actions: list[int], reward: float | None = None) -> dict:
    g = grade(TASK, actions)
    return episode(done=True, end_reason="submitted", schedule=actions, grade=g,
                   reward=g["reward"] if reward is None else reward, task=TASK, calls_used=1)


@environment_card(name="gridsim")
class Episode(AgentEnvEnvironment):
    def __init__(self, answer: dict | Exception):
        self.answer = answer

    @get_data
    async def get(self) -> list[DataPart]:
        if isinstance(self.answer, Exception):
            raise self.answer
        return [DataPart(data=self.answer)]


@asynccontextmanager
async def served(env: AgentEnvEnvironment):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(env.create_app().streamable_http_app(), host="127.0.0.1", port=port,
                                           log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    try:
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        server.should_exit = True
        await serving


@pytest.mark.parametrize("fields", [{}, {"done": True, "end_reason": "tool_call_limit", "reward": 0.0,
                                         "calls_used": 24}], ids=["no-submit", "tool-call-limit"])
async def test_no_submit_scores_0(fields):
    async with served(Episode(episode(**fields))) as url:
        rows = await verifier.verify(url)
    assert [(r["criterion"], r["score"], r["weight"]) for r in rows] == [("gridsim", 0.0, 1.0),
                                                                         ("hindsight_capture", 0.0, 0.0)]
    assert rows[0]["episode"] == {k: v for k, v in episode(**fields).items() if k != "task"}


async def test_a_submit_scores_gridsim_cores_reward_and_its_hindsight_capture():
    async with served(Episode(submitted(OPT))) as url:
        rows = await verifier.verify(url)
    assert [(r["score"], r["result"]) for r in rows] == [(1.0, True), (1.0, True)]
    assert "task" not in rows[0]["episode"]


async def test_no_task_loaded_fails_the_step():
    async with served(Episode(episode(task_id=None))) as url:
        with pytest.raises(RuntimeError, match="no task loaded"):
            await verifier.verify(url)


async def test_an_env_reward_that_gridsim_core_disagrees_with_fails_the_step():
    async with served(Episode(submitted(OPT, reward=0.5))) as url:
        with pytest.raises(RuntimeError, match="gridsim_core grades the schedule 1.0, the env reported 0.5"):
            await verifier.verify(url)


async def test_an_env_that_cannot_report_fails_the_step():
    async with served(Episode(RuntimeError("down"))) as url:
        with pytest.raises(RuntimeError, match="data/get failed"):
            await verifier.verify(url)
