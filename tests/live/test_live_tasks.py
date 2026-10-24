"""Live bundles: FD-4321's episode flow as task steps agent-env accepts, the gridsim-live bundle built from them, and
`tasks generate` on the live packs."""

import json
from importlib.resources import files

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner
from live_days import NOTICE_DAY, ROWS

from agentenv_gridsim import live_tasks
from agentenv_gridsim.cli import gridsim
from gridsim_core.live import END_DAY_URI, LIVE_LOAD_URI, MAX_TURNS, NOTICE_TOOL, Session, schedule, triggers
from gridsim_core.live_prompt import messages

FLOW = ["deploy_env", "apply_server_config", "modify_env_tool_access", "register_env_triggers", "deploy_agent",
        "sync_env_clock", "prompt_agent", "apply_server_config", "env_outcome_verifier"]
BUNDLE = files("agentenv_gridsim.bundles").joinpath("gridsim-live")


def bundle_task(name: str) -> list[dict]:
    return json.loads(BUNDLE.joinpath(f"tasks/{name}.json").read_text())


@pytest.mark.parametrize("tier", ["foresight", "blind", "short", "freeze6h"])
def test_the_steps_are_the_episode_flow(local_stores, tier):
    steps = live_tasks.steps(NOTICE_DAY, tier, episode_cap_usd=0.5)
    registry = get_task_step_registry()
    assert [registry[s["type"]].from_dict(s).type for s in steps] == FLOW
    by_id = {s["id"]: s for s in steps}
    assert by_id["load-task"]["directives"] == [{"service": "gridsim-live", "uri": LIVE_LOAD_URI,
                                                 "args": {"task_id": NOTICE_DAY["task_id"], "tier": tier}}]
    assert (by_id["hide-grid-notice"]["role"], by_id["hide-grid-notice"]["tools"]) == ("default", [NOTICE_TOOL])
    watches = schedule(NOTICE_DAY, tier)
    assert by_id["watches"]["triggers"] == triggers(watches) and len(triggers(watches)) == len(watches) - 1
    assert (by_id["clock"]["virtual_time"], by_id["clock"]["virtual_seconds_per_real_second"],
            by_id["clock"]["tolerate_missing_sync_time"]) == (watches[0].time_utc, 0, False)
    system, user = messages(Session(NOTICE_DAY, tier))
    play = by_id["play"]
    assert (play["system_prompt"], play["prompt"], play["max_turns"]) == (system["content"], user["content"],
                                                                          MAX_TURNS)
    assert by_id["deploy-agent"]["env_vars"] == {"GRIDSIM_MAX_COST_USD": "0.5"}
    assert by_id["end-day"]["directives"][0]["uri"] == END_DAY_URI
    assert (by_id["grade"]["file_artifact_id"], by_id["grade"]["score_aggregator"]) == (
        "gridsim-live-verifier", "weighted_average")


def test_the_bundle_plays_the_fixture_notice_day_and_its_wiring_task_has_no_agent(local_stores):
    """When data/fixtures-live changes, write tasks/day.json and wiring-noplay.json again from live_tasks.steps of the
    fixture notice day (play=False for the wiring task), indent 2."""
    assert bundle_task("day") == json.loads(json.dumps(live_tasks.steps(NOTICE_DAY)))
    assert bundle_task("wiring-noplay") == json.loads(json.dumps(live_tasks.steps(NOTICE_DAY, play=False)))
    assert [s["type"] for s in bundle_task("wiring-noplay")] == [t for t in FLOW
                                                                 if t not in ("deploy_agent", "prompt_agent")]
    bundle = checked(find_bundle("gridsim-live"))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == ["day", "wiring-noplay"]
    assert entries[BundleKind.ARTIFACT, "gridsim-live-verifier"].type == "file"
    assert BUNDLE.joinpath("artifacts/gridsim-live-verifier/verify.py").read_bytes() == live_tasks.VERIFY.read_bytes()


def test_tasks_generate_writes_a_live_pack_at_a_tier(tmp_path):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-live", "--tier", "blind",
                                          "--out", str(tmp_path / "b")])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in (tmp_path / "b/tasks").iterdir())
    assert names == sorted(f"{r['task_id']}.json" for r in live_tasks.eligible(ROWS, "blind"))
    assert (tmp_path / "b/README.md").read_text().startswith("GridSim live fixtures-live, blind tier")
    assert json.loads((tmp_path / "b/tasks" / f"{NOTICE_DAY['task_id']}.json").read_text()) == json.loads(
        json.dumps(live_tasks.steps(NOTICE_DAY, "blind")))


@pytest.mark.parametrize(("args", "error"), [
    (["--pack", "fixtures-live", "--bundle", "oneshot"], "a live day has one harness"),
    (["--pack", "fixtures", "--tier", "short"], "the v1 packs have the tiers foresight, blind, not short")])
def test_tasks_generate_keeps_live_and_v1_options_apart(tmp_path, args, error):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", *args, "--out", str(tmp_path / "b")])
    assert result.exit_code == 2 and error in result.output
