"""`agent-env gridsim tasks generate`: the eval bundles at each tier and harness, their tasks' exact steps, and the
bundle checks `agent-env run` makes before it reads a store."""

import json
from importlib.resources import files
from pathlib import Path

import pytest
from agent_env.bundle.parse import BundleKind, parse_bundle
from agent_env.bundle.plan import check_bundle
from agent_env.bundle.resolve import resolve_bundle
from agent_env.task_step.registry import get_task_step_registry
from click.testing import CliRunner
from conftest import BLIND

from agentenv_gridsim import tasks
from agentenv_gridsim.cli import gridsim
from gridsim_core.prompt import messages

VERIFY = files("agentenv_gridsim.bundles").joinpath("gridsim/artifacts/gridsim-verifier/verify.py").read_bytes()
EVAL = "ercot-dam-v1-eval"


def snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.mark.parametrize(("tier", "bundle", "n"), [("foresight", "full", 500), ("blind", "oneshot", 300)])
def test_the_eval_bundles_hold_the_readme_the_verifier_and_a_task_per_day(tmp_path, tier, bundle, n):
    names = tasks.generate(EVAL, tmp_path / "a", tier=tier, bundle=bundle)
    found = snapshot(tmp_path / "a")
    assert len(names) == n == len(set(names))
    assert sorted(found) == sorted(["README.md", "artifacts/gridsim-verifier/verify.py",
                                    *(f"tasks/{t}.json" for t in names)])
    assert found["artifacts/gridsim-verifier/verify.py"] == VERIFY
    assert found["README.md"].decode().startswith(f"GridSim {EVAL}, {tier} tier, {bundle} harness")
    assert tasks.generate(EVAL, tmp_path / "b", tier=tier, bundle=bundle) == names
    assert snapshot(tmp_path / "b") == found


def test_blind_plays_exactly_the_packs_blind_eval_days():
    rows = tasks.pack_rows(EVAL)
    manifest = json.loads((Path(tasks.data_root()) / EVAL / "manifest.json").read_text())
    assert [r["task_id"] for r in tasks.eligible(rows, "blind")] == [
        r["task_id"] for r in rows if r["task_id"] in set(manifest["blind_task_ids"])]


@pytest.mark.parametrize("bundle", ["full", "oneshot"])
def test_a_task_deploys_loads_plays_on_gridsim_cores_prompt_and_grades(tmp_path, bundle):
    task = BLIND[0]
    checks = tasks.BUNDLES[bundle]
    tasks.generate("fixtures", tmp_path, tier="blind", bundle=bundle, task_ids=[task["task_id"]])
    text = (tmp_path / f"tasks/{task['task_id']}.json").read_text()
    assert text == json.dumps(json.loads(text), indent=2, ensure_ascii=False) + "\n"
    system, user = messages(task, "blind", checks)
    hide = [{"id": "submit-only", "type": "modify_env_tool_access", "env_id": "gridsim", "action": "disable",
             "role": "default", "tools": ["get_situation", "check_schedule"]}] if bundle == "oneshot" else []
    assert json.loads(text) == [
        {"id": "deploy", "type": "deploy_env", "env_id": "gridsim"},
        {"id": "load-task", "type": "apply_server_config", "env_id": "gridsim",
         "directives": [{"service": "gridsim", "uri": "urn:gridsim:load-task/v1",
                         "args": {"task_id": task["task_id"], "tier": "blind", "checks": checks}}]},
        *hide,
        {"id": "deploy-agent", "type": "deploy_agent", "a2a_agent_id": "gridsim-llm", "env_ids": ["gridsim"]},
        {"id": "play", "type": "prompt_agent", "prompt_id": task["task_id"], "system_prompt": system["content"],
         "prompt": user["content"], "max_turns": 4, "model_params": {"max_tokens": 4096}, "effort": "high",
         "timeout_seconds": 1800},
        {"id": "grade", "type": "env_outcome_verifier", "env_id": "gridsim", "file_artifact_id": "gridsim-verifier",
         "verifier_id": "gridsim", "score_aggregator": "weighted_average"},
    ]


def test_every_task_builds_and_the_folder_passes_the_checks_run_makes_before_a_store(tmp_path, local_stores):
    tasks.generate("fixtures", tmp_path, tier="foresight", bundle="oneshot")
    registry = get_task_step_registry()
    for path in sorted((tmp_path / "tasks").glob("*.json")):
        built = [registry[s["type"]].from_dict(s) for s in json.loads(path.read_text())]
        assert [s.type for s in built] == ["deploy_env", "apply_server_config", "modify_env_tool_access",
                                           "deploy_agent", "prompt_agent", "env_outcome_verifier"]
    parsed = parse_bundle(tmp_path)
    check_bundle(resolve_bundle(parsed))
    kinds = [(e.kind, e.name) for e in parsed.entries]
    assert (BundleKind.ARTIFACT, "gridsim-verifier") in kinds
    assert sum(kind is BundleKind.TASK for kind, _ in kinds) == 20


@pytest.mark.parametrize(("cap", "env_vars"), [(None, None), (1.0, {"GRIDSIM_MAX_COST_USD": "1"}),
                                               (0.25, {"GRIDSIM_MAX_COST_USD": "0.25"})])
def test_the_episode_cap_reaches_the_agent_only_when_one_is_given(tmp_path, cap, env_vars):
    task_id = BLIND[0]["task_id"]
    tasks.generate("fixtures", tmp_path, task_ids=[task_id], episode_cap_usd=cap)
    deploy_agent = next(s for s in json.loads((tmp_path / f"tasks/{task_id}.json").read_text())
                        if s["type"] == "deploy_agent")
    assert deploy_agent.get("env_vars") == env_vars


def test_zone_keeps_one_settlement_points_days(tmp_path):
    names = tasks.generate(EVAL, tmp_path, zone="HB_WEST")
    assert names and all("-HB_WEST-" in n for n in names)


@pytest.mark.parametrize(("args", "out"), [
    (["--tier", "blind", "--bundle", "oneshot"], "results/bundles/ercot-dam-v1-eval-blind-oneshot"),
    (["--out", "elsewhere"], "elsewhere")])
def test_generate_writes_to_out_or_results_bundles(tmp_path, monkeypatch, args, out):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", EVAL, *args])
    assert result.exit_code == 0, result.output
    n = 300 if "blind" in args else 500
    assert result.output.startswith(f"Wrote {n} tasks into {out}; play one with: agent-env run {out} --task ")
    assert len(list((tmp_path / out / "tasks").iterdir())) == n


def test_a_zone_with_no_days_is_refused(tmp_path):
    result = CliRunner().invoke(gridsim, ["tasks", "generate", "--pack", "fixtures", "--zone", "LZ_NOWHERE",
                                          "--out", str(tmp_path)])
    assert result.exit_code == 2 and "fixtures has no foresight tasks at LZ_NOWHERE" in result.output
