"""The grader-parity gate: for every fixture task and tier and a set of action vectors, the reward gridsim-verifier
scores through the running env server equals gridsim_core.grade's, to 1e-6, and so does its hindsight row."""

import importlib.util
import random
from importlib.resources import as_file, files

import pytest
from agent_env.task_step.task_steps.verifiers.scoring import ScoreAggregator, aggregate_score
from conftest import FIXTURES

from gridsim_core.baselines import greedy, idle, random_feasible
from gridsim_core.grade import grade

pytestmark = pytest.mark.anyio
TOLERANCE = 1e-6


def load_verifier():
    path = files("agentenv_gridsim.bundles").joinpath("gridsim/artifacts/gridsim-verifier/verify.py")
    with as_file(path) as p:
        spec = importlib.util.spec_from_file_location("gridsim_verifier", p)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


verifier = load_verifier()


def vectors(task: dict) -> list[list[int]]:
    """The optimum, idle, greedy, a random feasible schedule and random ones that break rules."""
    b, rng = task["battery"], random.Random(task["task_id"])
    out = [task["refs"]["foresight"]["opt"], idle(task), greedy(task), random_feasible(task, 3)]
    out += [[rng.randint(-b["k_ch"], b["k_dis"]) for _ in range(24)] for _ in range(3)]
    out += [[rng.randint(-b["k_ch"] - 2, b["k_dis"] + 2) for _ in range(24)]]
    return out


CASES = [(t, tier, i) for t in FIXTURES for tier in ("foresight", "blind")
         if tier == "foresight" or (t.get("blind") and (t.get("refs") or {}).get("blind")) for i in range(8)]


@pytest.mark.parametrize(("task", "tier", "i"), CASES, ids=[f"{t['task_id']}-{tier}-{i}" for t, tier, i in CASES])
async def test_the_verifier_through_the_server_scores_gridsim_cores_reward(harness, task, tier, i):
    actions = vectors(task)[i]
    await harness.load_task(task, tier)
    async with harness.session() as session:
        out = await harness.call(session, "submit_schedule", {"actions": actions})
    assert '"submitted":true' in out
    rows = await verifier.verify(f"{harness.base_url}/mcp")
    expected = grade(task, actions, tier)
    assert abs(aggregate_score(rows, ScoreAggregator.WEIGHTED_AVERAGE) - expected["reward"]) <= TOLERANCE
    assert [(r["criterion"], r["weight"]) for r in rows] == [("gridsim", 1.0), ("hindsight_capture", 0.0)]
    assert abs(rows[0]["score"] - expected["reward"]) <= TOLERANCE
    assert abs(rows[1]["score"] - expected["r_opt"]) <= TOLERANCE


async def test_an_explicit_task_row_grades_the_same(harness):
    task = dict(FIXTURES[-1], task_id="dam-v1-2030-01-01-HB_WEST-2h-c")
    actions = vectors(task)[2]
    await harness.load_task(task, explicit=True)
    async with harness.session() as session:
        await harness.call(session, "submit_schedule", {"actions": actions})
    rows = await verifier.verify(f"{harness.base_url}/mcp")
    assert abs(rows[0]["score"] - grade(task, actions)["reward"]) <= TOLERANCE
