"""The gridsim-desk bundle: installed and checked as `agent-env run` checks it; its tasks are what desk-tasks writes
for the fixtures-env pack, each step a registered step and the post-turn hook its own artifact."""

import json
from importlib.resources import files

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.task_step.registry import get_task_step_registry
from desk_util import local_stores  # noqa: F401

from agentenv_gridsim import desk_tasks
from gridsim_core.desk import load_series, load_tasks

PACKS = {"fixtures-env": ["outage", "quiet", "pre", "reserves"], "desk-v2-pilot": ["pilot-0427", "pilot-0817"]}
NAMES = {"pilot-0427": "desk-v2-2026-04-27-S01", "pilot-0817": "desk-v2-2026-08-17-S03",
         "outage": "desk-v2-2026-02-14-S00-f3", "quiet": "desk-v2-2026-02-14-S00-f1",
         "pre": "desk-v2-2025-08-14-S00-f2", "reserves": "desk-v3-2026-02-14-S00-f4-pv"}


def steps(name: str) -> list[dict]:
    return json.loads(files("agentenv_gridsim.bundles").joinpath(f"gridsim-desk/tasks/{name}.json").read_text())


@pytest.mark.usefixtures("local_stores")
def test_the_bundle_installs_its_tasks_hook_and_verifier():
    bundle = checked(find_bundle("gridsim-desk"))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == sorted(NAMES)
    assert entries[BundleKind.ARTIFACT, desk_tasks.HOOK].type == "file"
    assert entries[BundleKind.ARTIFACT, desk_tasks.VERIFIER].type == "file"


@pytest.mark.parametrize("name", NAMES)
def test_each_task_is_what_desk_tasks_writes(name):
    pack = next(p for p, names in PACKS.items() if name in names)
    task = {r["task_id"]: r for r in load_tasks(pack)}[NAMES[name]]
    assert steps(name) == desk_tasks.steps(task, load_series(pack, task), pack)
    registry = get_task_step_registry()
    built = [registry[s["type"]].from_dict(s) for s in steps(name)]
    assert [s.type for s in built] == ["deploy_env", "apply_server_config", "modify_env_tool_access",
                                       "modify_env_tool_access", "deploy_agent", "sync_env_clock", "prompt_agent",
                                       "env_outcome_verifier"]
    play = built[6]
    assert play.post_turn_hooks == [{"file_artifact_id": desk_tasks.HOOK, "params": {"env_id": built[0].env_id}}]
