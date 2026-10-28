"""Forecast bundles: the episode flow as task steps agent-env accepts, the gridsim-forecast bundle built from them, and
`tasks generate` on the forecast packs."""

import json

import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner
from forecast_days import ROWS, WINDOW

from agentenv_gridsim import forecast_tasks
from agentenv_gridsim.cli import gridsim
from gridsim_core.forecast import (
    END_WINDOW_URI,
    FORECAST_ENV,
    FORECAST_LOAD_URI,
    FORECAST_TOOLS,
    MAX_TURNS,
    NOTICE_TOOL,
    TIERS,
    Session,
    triggers,
)
from gridsim_core.forecast_prompt import opening, system_prompt

FLOW = ["deploy_env", "apply_server_config", "modify_env_tool_access", "register_env_triggers", "deploy_agent",
        "sync_env_clock", "prompt_agent", "apply_server_config", "env_outcome_verifier"]
BLIND_FLOW = FLOW[:3] + ["modify_env_tool_access"] + FLOW[3:]


def bundle_task(name: str) -> list[dict]:
    return json.loads(forecast_tasks.BUNDLE.joinpath(f"tasks/{name}.json").read_text())


@pytest.mark.parametrize("tier", TIERS)
def test_the_steps_are_the_episode_flow(local_stores, tier):
    steps = forecast_tasks.steps(WINDOW, tier, episode_cap_usd=5.0)
    registry = get_task_step_registry()
    assert [registry[s["type"]].from_dict(s).type for s in steps] == (BLIND_FLOW if tier == "blind" else FLOW)
    by_id = {s["id"]: s for s in steps}
    assert by_id["load-task"]["directives"] == [{"service": FORECAST_ENV, "uri": FORECAST_LOAD_URI,
                                                 "args": {"task_id": WINDOW["task_id"], "tier": tier}}]
    assert (by_id["hide-grid-notice"]["role"], by_id["hide-grid-notice"]["tools"]) == ("default", [NOTICE_TOOL])
    if tier == "blind":
        assert (by_id["hide-tier-tools"]["role"], by_id["hide-tier-tools"]["tools"]) == ("default",
                                                                                         list(FORECAST_TOOLS))
    s = Session(WINDOW, tier)
    assert by_id["watches"]["triggers"] == triggers(s.watches) and len(triggers(s.watches)) == len(s.watches) - 1
    payloads = [a["args"]["deploy"] for t in by_id["watches"]["triggers"] for a in t["actions"]
                if "deploy" in a["args"]]
    assert payloads and len(payloads) == len(WINDOW["deployments"])
    assert (by_id["clock"]["virtual_time"], by_id["clock"]["virtual_seconds_per_real_second"],
            by_id["clock"]["tolerate_missing_sync_time"]) == (s.watches[0].time_utc, 0, False)
    play = by_id["play"]
    assert (play["system_prompt"], play["prompt"], play["max_turns"], play["model_params"], play["effort"],
            play["timeout_seconds"]) == (system_prompt(tier, s.win.era, s.source), opening(s), MAX_TURNS[tier],
                                         {"max_tokens": 16384}, "high", forecast_tasks.PLAY_SECONDS)
    assert by_id["deploy-agent"]["env_vars"] == {"GRIDSIM_MAX_COST_USD": "5"}
    assert by_id["end-window"]["directives"] == [{"service": FORECAST_ENV, "uri": END_WINDOW_URI, "args": {}}]
    assert (by_id["grade"]["file_artifact_id"], by_id["grade"]["score_aggregator"]) == (
        "gridsim-forecast-verifier", "weighted_average")


def test_the_bundle_plays_the_fixture_window_at_each_tier_and_its_wiring_tasks(local_stores):
    """When data/fixtures-forecast or the forecast prompt changes (or the showcase pack is built), write the tasks
    again with forecast_tasks.write_bundle_tasks(src/agentenv_gridsim/bundles/gridsim-forecast)."""
    want = forecast_tasks.bundle_tasks()
    for name, steps in want.items():
        assert bundle_task(name) == json.loads(json.dumps(steps)), name
    assert [s["type"] for s in bundle_task("wiring-nodam")] == [t for t in FLOW
                                                                 if t not in ("deploy_agent", "prompt_agent")]
    look = {s["id"]: s for s in bundle_task("wiring-lookahead")}["play"]
    s = Session(WINDOW, "front")
    assert look["prompt"].startswith(opening(s)) and f'issued_at "{s.watches[1].time}"' in look["prompt"]
    assert look["max_turns"] == len(s.watches) + 3 + 2
    bundle = checked(find_bundle("gridsim-forecast"))
    entries = {(e.kind, e.name): e for e in bundle.entries}
    assert sorted(name for kind, name in entries if kind is BundleKind.TASK) == sorted(want)
    assert {*TIERS, "wiring-nodam", "wiring-lookahead"} <= set(want)
    assert entries[BundleKind.ARTIFACT, "gridsim-forecast-verifier"].type == "file"


@pytest.mark.parametrize("tier", TIERS)
def test_tasks_generate_writes_a_forecast_pack_at_a_tier(tmp_path, tier):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-forecast", "--tier", tier,
                                          "--out", str(tmp_path / "b")])
    assert result.exit_code == 0, result.output
    names = sorted(p.name for p in (tmp_path / "b/tasks").iterdir())
    assert names == sorted(f"{r['task_id']}.json" for r in forecast_tasks.eligible(ROWS, tier))
    assert (tmp_path / "b/README.md").read_text().startswith(f"GridSim forecast fixtures-forecast, {tier} tier")
    assert json.loads((tmp_path / "b/tasks" / f"{WINDOW['task_id']}.json").read_text()) == json.loads(
        json.dumps(forecast_tasks.steps(WINDOW, tier)))
    assert (tmp_path / "b/artifacts/gridsim-forecast-verifier/verify.py").read_bytes() == \
        forecast_tasks.VERIFY.read_bytes()


def test_tasks_generate_defaults_a_forecast_pack_to_front(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-forecast", "--zone", "HB_NORTH"])
    assert result.exit_code == 0, result.output
    written = sorted(p.stem for p in (tmp_path / "results/bundles/fixtures-forecast-front/tasks").iterdir())
    assert WINDOW["task_id"] in written and all("HB_NORTH" in t for t in written)


def test_tasks_generate_writes_the_desk_ablation_with_the_source_in_the_load(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures-forecast", "--source", "desk"])
    assert result.exit_code == 0, result.output
    out = tmp_path / "results/bundles/fixtures-forecast-front-desk"
    steps = json.loads((out / "tasks" / f"{WINDOW['task_id']}.json").read_text())
    assert steps[1]["directives"][0]["args"] == {"task_id": WINDOW["task_id"], "tier": "front", "source": "desk"}
    assert steps == json.loads(json.dumps(forecast_tasks.steps(WINDOW, "front", source="desk")))
    assert "front tier on the desk's forecasts" in (out / "README.md").read_text()


@pytest.mark.parametrize(("args", "error"), [
    (["--pack", "fixtures-forecast", "--tier", "reserves"], "fixtures-forecast doesn't take reserves"),
    (["--pack", "fixtures-forecast", "--tier", "foresight"], "fixtures-forecast doesn't take foresight"),
    (["--pack", "fixtures-hybrid", "--tier", "front"], "front is a forecast tier"),
    (["--pack", "fixtures-forecast", "--bundle", "oneshot"], "a forecast window has one harness"),
    (["--pack", "fixtures-forecast", "--zone", "LZ_NOWHERE"], "fixtures-forecast has no front tasks at LZ_NOWHERE"),
    (["--pack", "fixtures-hybrid", "--source", "desk"], "--source is for forecast packs")])
def test_tasks_generate_keeps_forecast_tiers_to_forecast_packs(tmp_path, args, error):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", *args, "--out", str(tmp_path / "b")])
    assert result.exit_code == 2 and error in result.output, result.output


def test_a_forecast_pack_is_not_written_as_another(tmp_path):
    with pytest.raises(Exception, match="not a forecast pack"):
        forecast_tasks.generate("fixtures-hybrid", tmp_path)
