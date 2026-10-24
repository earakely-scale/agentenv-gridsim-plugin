"""Hybrid bundles: FD-4322's episode flow as task steps agent-env accepts, the gridsim-hybrid bundle built from them,
and `tasks generate` on the hybrid packs."""

import json
from importlib.resources import files

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner
from hybrid_days import DAY, ROWS

from agentenv_gridsim import hybrid_tasks
from agentenv_gridsim.cli import gridsim
from gridsim_core.hybrid import (
    END_DAY_URI,
    HYBRID_ENV,
    LIVE_LOAD_URI,
    MAX_TURNS,
    NOTICE_TOOL,
    Session,
    schedule,
    triggers,
)
from gridsim_core.hybrid_prompt import opening, system_prompt

FLOW = ["deploy_env", "apply_server_config", "modify_env_tool_access", "register_env_triggers", "deploy_agent",
        "sync_env_clock", "prompt_agent", "apply_server_config", "env_outcome_verifier"]
BUNDLE = files("agentenv_gridsim.bundles").joinpath("gridsim-hybrid")


def bundle_task(name: str) -> list[dict]:
    return json.loads(BUNDLE.joinpath(f"tasks/{name}.json").read_text())


@pytest.mark.parametrize("tier", ["energy", "reserves"])
def test_the_steps_are_the_episode_flow(local_stores, tier):
    steps = hybrid_tasks.steps(DAY, tier, episode_cap_usd=0.5)
    registry = get_task_step_registry()
    assert [registry[s["type"]].from_dict(s).type for s in steps] == FLOW
    by_id = {s["id"]: s for s in steps}
    assert by_id["load-task"]["directives"] == [{"service": HYBRID_ENV, "uri": LIVE_LOAD_URI,
                                                 "args": {"task_id": DAY["task_id"], "tier": tier}}]
    assert (by_id["hide-grid-notice"]["role"], by_id["hide-grid-notice"]["tools"]) == ("default", [NOTICE_TOOL])
    watches = schedule(DAY, tier)
    assert by_id["watches"]["triggers"] == triggers(watches) and len(triggers(watches)) == len(watches) - 1
    payloads = [a["args"]["deploy"] for t in by_id["watches"]["triggers"] for a in t["actions"]
                if "deploy" in a["args"]]
    assert payloads and len(payloads) == len(DAY["deployments"])
    assert (by_id["clock"]["virtual_time"], by_id["clock"]["virtual_seconds_per_real_second"],
            by_id["clock"]["tolerate_missing_sync_time"]) == (watches[0].time_utc, 0, False)
    s = Session(DAY, tier)
    play = by_id["play"]
    assert (play["system_prompt"], play["prompt"], play["max_turns"]) == (system_prompt(tier, s.day.era), opening(s),
                                                                          MAX_TURNS)
    assert by_id["deploy-agent"]["env_vars"] == {"GRIDSIM_MAX_COST_USD": "0.5"}
    assert by_id["end-day"]["directives"][0]["uri"] == END_DAY_URI
    assert (by_id["grade"]["file_artifact_id"], by_id["grade"]["score_aggregator"]) == (
        "gridsim-hybrid-verifier", "weighted_average")


def test_the_bundle_plays_the_fixture_deployment_day_and_its_wiring_task_has_no_agent(local_stores):
    """When data/fixtures-hybrid or the hybrid prompt changes, write tasks/day.json and wiring-noplay.json again from
    hybrid_tasks.steps of hybrid_days.DAY (play=False for the wiring task), indent 2."""
    assert bundle_task("day") == json.loads(json.dumps(hybrid_tasks.steps(DAY)))
    assert bundle_task("wiring-noplay") == json.loads(json.dumps(hybrid_tasks.steps(DAY, play=False)))
    assert [s["type"] for s in bundle_task("wiring-noplay")] == [t for t in FLOW
                                                                 if t not in ("deploy_agent", "prompt_agent")]
    bundle = checked(find_bundle("gridsim-hybrid"))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == ["day", "wiring-noplay"]
    assert entries[BundleKind.ARTIFACT, "gridsim-hybrid-verifier"].type == "file"
    assert BUNDLE.joinpath("artifacts/gridsim-hybrid-verifier/verify.py").read_bytes() == \
        hybrid_tasks.VERIFY.read_bytes()


@pytest.mark.parametrize("tier", ["energy", "reserves"])
def test_tasks_generate_writes_a_hybrid_pack_at_a_tier(tmp_path, tier):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-hybrid", "--tier", tier,
                                          "--out", str(tmp_path / "b")])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in (tmp_path / "b/tasks").iterdir())
    assert names == sorted(f"{r['task_id']}.json" for r in hybrid_tasks.eligible(ROWS, tier))
    assert (tmp_path / "b/README.md").read_text().startswith(f"GridSim hybrid fixtures-hybrid, {tier} tier")
    assert json.loads((tmp_path / "b/tasks" / f"{DAY['task_id']}.json").read_text()) == json.loads(
        json.dumps(hybrid_tasks.steps(DAY, tier)))


def test_tasks_generate_defaults_a_hybrid_pack_to_reserves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-hybrid"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "results/bundles/fixtures-hybrid-reserves/tasks" / f"{DAY['task_id']}.json").is_file()


@pytest.mark.parametrize(("args", "error"), [
    (["--pack", "fixtures-hybrid", "--tier", "foresight"], "fixtures-hybrid doesn't take foresight"),
    (["--pack", "fixtures-live", "--tier", "reserves"], "reserves is a hybrid tier"),
    (["--pack", "fixtures-hybrid", "--bundle", "oneshot"], "a live day has one harness")])
def test_tasks_generate_keeps_hybrid_tiers_to_hybrid_packs(tmp_path, args, error):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", *args, "--out", str(tmp_path / "b")])
    assert result.exit_code == 2 and error in result.output, result.output


def test_a_hybrid_pack_is_not_written_as_a_live_one(tmp_path):
    with pytest.raises(Exception, match="not a hybrid pack"):
        hybrid_tasks.generate("fixtures-live", tmp_path)
