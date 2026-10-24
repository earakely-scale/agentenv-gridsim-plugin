"""Market bundles: the floor flow as task steps agent-env accepts, the gridsim-market bundle built from them, and
`tasks generate` on the market packs."""

import json
from importlib.resources import files

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner
from market_floors import BUNDLE, DAY, ROWS, SPRINT, bundle_steps

from agentenv_gridsim import market_tasks
from agentenv_gridsim.cli import gridsim
from agentenv_gridsim.market import CALLS_URI
from gridsim_core.live import NOTICE_TOOL
from gridsim_core.market import END_URI, LOAD_URI, MARKET_ENV, MAX_TURNS, SPRINT_TOOLS, TOOLS, Session, triggers
from gridsim_core.market_prompt import opening, system_prompt

FLOW = {"floor-sprint": ["deploy_env", "apply_server_config", "modify_env_tool_access", "modify_env_tool_access",
                         "deploy_agent", "sync_env_clock", "prompt_agent", "apply_server_config",
                         "env_outcome_verifier"],
        "floor-day": ["deploy_env", "apply_server_config", "modify_env_tool_access", "register_env_triggers",
                      "deploy_agent", "sync_env_clock", "prompt_agent", "apply_server_config", "env_outcome_verifier"]}
BUNDLE_DIR = files("agentenv_gridsim.bundles").joinpath("gridsim-market")


@pytest.mark.parametrize("tier", ["floor-sprint", "floor-day"])
def test_the_steps_are_the_floor_flow(local_stores, tier):
    steps = market_tasks.steps(DAY, tier, episode_cap_usd=0.5)
    registry = get_task_step_registry()
    assert [registry[s["type"]].from_dict(s).type for s in steps] == FLOW[tier]
    by_id = {s["id"]: s for s in steps}
    assert by_id["load-task"]["directives"] == [{"service": MARKET_ENV, "uri": LOAD_URI,
                                                 "args": {"floor_id": DAY["task_id"], "tier": tier}}]
    assert (by_id["hide-grid-notice"]["role"], by_id["hide-grid-notice"]["tools"]) == ("default", [NOTICE_TOOL])
    s = Session(DAY, tier)
    if tier == "floor-sprint":
        assert by_id["hide-tier-tools"]["tools"] == [t for t in TOOLS if t not in SPRINT_TOOLS]
        assert "watches" not in by_id
    else:
        assert "hide-tier-tools" not in by_id
        assert by_id["watches"]["triggers"] == triggers(s.watches) and len(s.watches) == 7
        barrier = {"at": "provoking_call", "timeout_seconds": 60}
        assert all(t["barrier"] == barrier for t in by_id["watches"]["triggers"])
    assert (by_id["clock"]["virtual_time"], by_id["clock"]["virtual_seconds_per_real_second"]) == (
        s.watch_time_utc(0), 0)
    play = by_id["play"]
    assert (play["system_prompt"], play["prompt"], play["max_turns"], play["model_params"], play["effort"],
            play["timeout_seconds"]) == (system_prompt(tier), opening(s), MAX_TURNS[tier], {"max_tokens": 16384},
                                         "high", market_tasks.PLAY_SECONDS[tier])
    assert by_id["deploy-agent"]["env_vars"] == {"GRIDSIM_MAX_COST_USD": "0.5"}
    assert by_id["end-floor"]["directives"][0]["uri"] == END_URI
    assert (by_id["grade"]["file_artifact_id"], by_id["grade"]["score_aggregator"]) == (
        "gridsim-market-verifier", "weighted_average")


def test_compliant_and_harness_calls(local_stores):
    steps = market_tasks.steps(SPRINT, "floor-sprint", compliant=True, play=False,
                               calls=[("submit_offer", {"offer": {"hours": []}})])
    by_id = {s["id"]: s for s in steps}
    assert by_id["load-task"]["directives"][0]["args"] == {"floor_id": SPRINT["task_id"], "tier": "floor-sprint",
                                                           "compliant": True}
    assert [s["id"] for s in steps][-3:] == ["seat-calls", "end-floor", "grade"] and "play" not in by_id
    assert by_id["seat-calls"]["directives"] == [{"service": MARKET_ENV, "uri": CALLS_URI, "args": {
        "calls": [{"tool": "submit_offer", "args": {"offer": {"hours": []}}}]}}]
    registry = get_task_step_registry()
    assert all(registry[s["type"]].from_dict(s) for s in steps)


def test_the_bundle_holds_its_floors_and_wiring_tasks(local_stores):
    """When data/fixtures-market or the market prompt changes, write the bundle's tasks again from
    market_floors.bundle_steps, indent 2."""
    for name in BUNDLE:
        assert json.loads(BUNDLE_DIR.joinpath(f"tasks/{name}.json").read_text()) == bundle_steps(name), name
    bundle = checked(find_bundle(MARKET_ENV))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == sorted(BUNDLE)
    assert entries[BundleKind.ARTIFACT, "gridsim-market-verifier"].type == "file"
    assert BUNDLE_DIR.joinpath("artifacts/gridsim-market-verifier/verify.py").read_bytes() == \
        market_tasks.VERIFY.read_bytes()
    assert not any(s["type"] == "deploy_agent" for name in ("wiring-noplay", "wiring-late", "wiring-disclosure")
                   for s in bundle_steps(name))


@pytest.mark.parametrize(("tier", "compliant"), [("floor-sprint", False), ("floor-day", True)])
def test_tasks_generate_writes_a_market_pack_at_a_tier(tmp_path, tier, compliant):
    out = tmp_path / "b"
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-market", "--tier", tier,
                                          *(["--compliant"] if compliant else []), "--out", str(out)])
    assert result.exit_code == 0, result.output
    names = sorted(p.stem for p in (out / "tasks").glob("*.json"))
    assert names == sorted(r["task_id"] for r in ROWS)
    first = json.loads((out / "tasks" / f"{DAY['task_id']}.json").read_text())
    assert first == json.loads(json.dumps(market_tasks.steps(DAY, tier, compliant)))
    assert "deploy_agent" in {s["type"] for s in first} and "GRIDSIM_MAX_COST_USD" not in json.dumps(first)
    assert (out / "artifacts/gridsim-market-verifier/verify.py").is_file()


@pytest.mark.parametrize(("args", "error"), [
    (["--pack", "fixtures-market", "--tier", "foresight"], "fixtures-market does not take foresight"),
    (["--pack", "fixtures-live", "--tier", "floor-day"], "fixtures-live does not take floor-day"),
    (["--pack", "fixtures-live", "--compliant"], "fixtures-live does not take --compliant"),
    (["--pack", "fixtures-market", "--bundle", "oneshot"], "not for market packs")])
def test_tasks_generate_keeps_market_tiers_to_market_packs(tmp_path, args, error):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", *args, "--out", str(tmp_path / "b")])
    assert result.exit_code == 2 and error in result.output, result.output
