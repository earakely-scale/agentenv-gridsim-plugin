"""The gridsim bundle: installed, checked as `agent-env run` checks it, and its wiring tasks' schedules graded."""

import json
from importlib.resources import files

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.cli import cli
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner

from agentenv_gridsim import tasks
from agentenv_gridsim.server import LOAD_URI, SUBMIT_URI
from gridsim_core.grade import grade
from gridsim_core.task import index_pack

TASK_ID = "dam-v1-2022-11-14-LZ_WEST-2h-m"
TASK = index_pack("fixtures")[TASK_ID]
INFEASIBLE_REWARD = 0.050083
NAMES = ["full", "oneshot", "smoke", "wiring-infeasible", "wiring-nosubmit"]


def steps(task: str) -> list[dict]:
    return json.loads(files("agentenv_gridsim.bundles").joinpath(f"gridsim/tasks/{task}.json").read_text())


def submitted(task: str) -> list[list[int]]:
    return [d["args"]["actions"] for s in steps(task) if s["type"] == "apply_server_config"
            for d in s["directives"] if d["uri"] == SUBMIT_URI]


def test_plugin_check_passes(local_stores):
    result = CliRunner().invoke(cli, ["plugin", "check"])
    assert result.exit_code == 0, result.output


def test_the_bundle_installs_its_tasks_and_the_verifier(local_stores):
    bundle = checked(find_bundle("gridsim"))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert bundle.description.startswith("GridSim: run one battery at an ERCOT hub or load zone")
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == NAMES
    assert entries[BundleKind.ARTIFACT, "gridsim-verifier"].type == "file"


@pytest.mark.parametrize("task", NAMES)
def test_each_task_loads_the_fixture_day_into_gridsim_and_grades_it(local_stores, task):
    registry = get_task_step_registry()
    built = [registry[s["type"]].from_dict(s) for s in steps(task)]
    assert {getattr(s, "env_id", "gridsim") for s in built} == {"gridsim"}
    assert [s.type for s in built[:2]] == ["deploy_env", "apply_server_config"]
    checks = 0 if task == "oneshot" else 3
    assert steps(task)[1]["directives"] == [
        {"service": "gridsim", "uri": LOAD_URI, "args": {"task_id": TASK_ID, "tier": "foresight", "checks": checks}}]
    grade_step = built[-1]
    assert (grade_step.type, grade_step.file_artifact_id, grade_step.score_aggregator.value) == (
        "env_outcome_verifier", "gridsim-verifier", "weighted_average")


@pytest.mark.parametrize("bundle", ["full", "oneshot"])
def test_the_played_tasks_are_tasks_steps(bundle):
    assert steps(bundle) == tasks.steps(TASK, "foresight", bundle)


def test_smoke_submits_the_dp_optimum():
    [actions] = submitted("smoke")
    assert actions == TASK["refs"]["foresight"]["opt"]
    assert grade(TASK, actions)["reward"] == 1.0


def test_wiring_infeasible_breaks_a_rule_and_scores_its_known_value():
    [actions] = submitted("wiring-infeasible")
    g = grade(TASK, actions)
    assert (g["feasible"], g["violation"], g["truncated_at"], g["reward"]) == (False, "rate", 7, INFEASIBLE_REWARD)
    assert g["end_shortfall_units"] > 0
    assert f"scores\n  exactly {INFEASIBLE_REWARD}" in files("agentenv_gridsim.bundles").joinpath(
        "gridsim/README.md").read_text()


def test_wiring_nosubmit_submits_nothing():
    assert submitted("wiring-nosubmit") == []
    assert [s["id"] for s in steps("wiring-nosubmit")] == ["deploy", "load-task", "grade"]
