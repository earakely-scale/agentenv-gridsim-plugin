"""`agent-env gridsim tasks training-pack`: the self-contained GridSim v1 training bundle. Its eval split is the 200
eval-2025 days the registered training runs were scored on, its env builds from the plugin's code and the v1 packs with
the repo image's pins, its verifier scores from the env's own report with nothing but the framework, and every task
passes the checks `agent-env run` makes before a store and runs as an episode with one agent played from outside."""

import asyncio
import json
import re
import tomllib
from pathlib import Path
from types import SimpleNamespace

from agent_env.bundle.parse import BundleKind, parse_bundle
from agent_env.bundle.plan import check_bundle
from agent_env.bundle.resolve import resolve_bundle
from agent_env.task import EpisodeSpec, Task
from agentenv_protocol import client
from click.testing import CliRunner

from agentenv_gridsim import tasks
from agentenv_gridsim.cli import gridsim

ROOT = Path(__file__).resolve().parents[2]


def statement(dockerfile: Path, instruction: str) -> str:
    """The first ``instruction`` of ``dockerfile``, with its continuation lines joined."""
    lines = re.sub(r"\s*\\\n\s*", " ", dockerfile.read_text()).splitlines()
    return next(line for line in lines if line.startswith(instruction))


def test_the_eval_split_is_the_200_days_the_registered_training_runs_were_scored_on():
    splits = tasks.training_rows()

    assert [r["task_id"] for r in splits["eval"]] == json.loads((ROOT / "results/train/4b/eval_base.json").read_text())[
        "task_ids"]
    assert len(splits["train"]) == 2000
    assert not {r["task_id"] for r in splits["train"]} & {r["task_id"] for r in splits["eval"]}


def test_the_bundle_holds_the_env_the_verifier_and_a_one_shot_task_per_day(tmp_path):
    names = tasks.training_pack(tmp_path, n_train=40, n_eval=10)
    env = tmp_path / "envs/gridsim"

    assert len(names) == 50 == len(list((tmp_path / "tasks").iterdir()))
    assert {split: len(tomllib.loads((tmp_path / f"evals/{split}.toml").read_text())["tasks"])
            for split in ("train", "eval")} == {"train": 40, "eval": 10}
    assert tomllib.loads((env / "env.toml").read_text()) == {"environment_name": "gridsim",
                                                             "env_provider_type": "server"}
    assert sorted(p.name for p in env.iterdir()) == ["Dockerfile", "LICENSE", "NOTICE", "agentenv_gridsim", "env.toml",
                                                     "gridsim_core", "packs"]
    assert sorted(p.name for p in (env / "packs").iterdir()) == ["ercot-dam-v1-eval", "ercot-dam-v1-train"]
    assert not (env / "agentenv_gridsim/web").exists() and not (env / "agentenv_gridsim/bundles").exists()
    assert "gridsim_core" not in (tmp_path / "artifacts/gridsim-verifier/verify.py").read_text()
    play = json.loads((tmp_path / "tasks" / f"{names[0]}.json").read_text())
    assert [s["type"] for s in play] == ["deploy_env", "apply_server_config", "modify_env_tool_access", "deploy_agent",
                                         "prompt_agent", "env_outcome_verifier"]


def test_its_env_installs_the_repo_images_pins_and_serves_the_copied_packs():
    env, repo = Path(str(tasks.TRAINING_DOCKERFILE)), ROOT / "Dockerfile"

    assert statement(env, "RUN pip install") == statement(repo, "RUN pip install")
    for instruction in ("FROM ", "RUN useradd ", "USER ", "EXPOSE ", "CMD "):
        assert statement(env, instruction) == statement(repo, instruction)
    assert "GRIDSIM_TASKS_DIR=/app/packs/ercot-dam-v1-train:/app/packs/ercot-dam-v1-eval" in statement(env, "ENV ")


def test_every_task_passes_the_checks_run_makes_and_is_an_episode_with_one_agent_played_from_outside(
        tmp_path, local_stores):
    tasks.training_pack(tmp_path, n_train=20, n_eval=10)
    parsed = parse_bundle(tmp_path)
    check_bundle(resolve_bundle(parsed))

    assert sum(entry.kind is BundleKind.TASK for entry in parsed.entries) == 30
    for path in (tmp_path / "tasks").glob("*.json"):
        spec = EpisodeSpec.from_task(Task.from_dict({"id": path.stem, "steps": json.loads(path.read_text())}))
        assert spec.trainer_agents == ("default-agent",)


def test_the_verifier_scores_the_envs_own_grade_and_nothing_submitted_as_0(tmp_path, monkeypatch):
    tasks.training_pack(tmp_path, n_train=1, n_eval=1)
    namespace: dict = {}
    exec((tmp_path / "artifacts/gridsim-verifier/verify.py").read_text(), namespace)
    episodes = iter([
        {"task_id": "d", "done": True, "schedule": [0] * 24, "reward": 0.73, "task": {"task_id": "d"},
         "grade": {"reward": 0.73, "r_opt": 0.61}},
        {"task_id": "d", "done": True, "schedule": None, "reward": None, "task": {"task_id": "d"}, "grade": None},
    ])

    async def get_data(url):
        return SimpleNamespace(parts=[SimpleNamespace(data=next(episodes))])

    monkeypatch.setattr(client, "get_data", get_data)
    scored = [asyncio.run(namespace["verify"]("http://env/mcp")) for _ in range(2)]

    assert [[row["score"] for row in rows] for rows in scored] == [[0.73, 0.61], [0.0, 0.0]]


def test_training_pack_writes_into_packs_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(gridsim, ["tasks", "training-pack", "--train", "5"])

    assert result.exit_code == 0, result.output
    assert result.output.startswith("Wrote 205 tasks into packs/gridsim-v1; train on it with: AgentEnv.local(")
    assert len(list((tmp_path / "packs/gridsim-v1/tasks").iterdir())) == 205
