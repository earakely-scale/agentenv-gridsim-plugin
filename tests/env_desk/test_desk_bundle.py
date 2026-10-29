"""The gridsim-desk bundle: installed and checked as `agent-env run` checks it; its tasks are what desk-tasks writes
for the fixtures-env pack, each step a registered step and the post-turn hook its own artifact."""

import asyncio
import json
import sys
import tomllib
from importlib.resources import files
from pathlib import Path

import httpx
import pytest
from agent_env.bundle.installed import checked, find_bundle
from agent_env.bundle.parse import BundleKind, parse_bundle
from agent_env.bundle.plan import check_bundle
from agent_env.bundle.resolve import resolve_bundle
from agent_env.task import EpisodeSpec, Task
from agent_env.task_step.registry import get_task_step_registry
from desk_util import local_stores  # noqa: F401

from agentenv_gridsim import desk_tasks
from gridsim_core.desk import load_series, load_tasks

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import desk_bench  # noqa: E402
import desk_train  # noqa: E402

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


TRAIN_PACK = ROOT / "data/desk/desk-v4-train"
needs_train_pack = pytest.mark.skipif(not (TRAIN_PACK / "tasks.jsonl.gz").exists(), reason="no desk-v4-train pack")


def training_bundle(out: Path) -> dict[str, list[str]]:
    return desk_train._write(out, {desk_train.BENCH: str(ROOT / "data/desk/desk-v4-bench"),
                                   desk_train.PACK: str(TRAIN_PACK)}, False)


@needs_train_pack
def test_the_training_bundle_holds_operating_days_scored_by_r_and_by_capture(tmp_path):
    ids = training_bundle(tmp_path)
    rows = {r["task_id"]: r for r in load_tasks(str(TRAIN_PACK))}
    for split in desk_train.SPLITS:
        assert tomllib.loads((tmp_path / f"evals/{split}.toml").read_text())["tasks"] == ids[split]
    assert len(ids["bench"]) == 32 and not set(ids["train"]) & set(ids["val"])
    assert {rows[t]["split"] for t in ids["val"]} == {"val"} and all(rows[t]["operator_ok"] for t in ids["train"])
    row = rows[ids["train"][0]]
    want = desk_tasks.steps(row, load_series(str(TRAIN_PACK), row), "desk-v4-train")
    want[6]["post_turn_hooks"] = [{"file_artifact_id": desk_tasks.HOOK, "params": {}}]
    got = json.loads((tmp_path / f"tasks/{row['task_id']}.json").read_text())
    assert got[:-1] == want and got[-1] | {"env_id": None} == {
        "id": "capture", "type": "env_outcome_verifier", "env_id": None, "file_artifact_id": desk_train.CAPTURE,
        "verifier_id": "gridsim-desk-capture", "score_aggregator": "weighted_average"}
    dockerfile = (tmp_path / "envs/gridsim-desk-v4/Dockerfile").read_text()
    assert f"tar.gz/{desk_bench.FREEZE}" in dockerfile and "desk-v4-bench /app" in dockerfile
    assert "desk-v4-train /app" in dockerfile
    assert (tmp_path / f"artifacts/{desk_train.CAPTURE}/verify.py").read_text() == desk_train.CAPTURE_VERIFY.read_text()


@needs_train_pack
@pytest.mark.usefixtures("local_stores")
def test_every_training_task_passes_the_checks_run_makes_and_plays_one_agent_from_outside(tmp_path):
    training_bundle(tmp_path)
    parsed = parse_bundle(tmp_path)
    check_bundle(resolve_bundle(parsed))
    for path in sorted((tmp_path / "tasks").glob("*.json"))[::40]:
        spec = EpisodeSpec.from_task(Task.from_dict({"id": path.stem, "steps": json.loads(path.read_text())}))
        assert spec.trainer_agents == ("default-agent",)


def test_the_capture_verifier_scores_c_floored_at_minus_1_shifted_into_0_1(monkeypatch):
    namespace: dict = {}
    exec((files("agentenv_gridsim") / "training-pack-desk-verify.py").read_text(), namespace)
    grades = iter([{"capture": 0.3, "reward": 0.9}, {"capture": -2.5, "reward": 0.0}, {"capture": None},
                   {"capture": 1.0, "reward": 1.0}])

    async def post(self, url, **kwargs):
        assert url == "http://env/step" and kwargs["headers"] == {"AgentEnv-Role": "hook"}
        return httpx.Response(200, json={"content": [{"type": "text", "text": json.dumps(next(grades))}]})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    rows = [asyncio.run(namespace["verify"]("http://env/mcp"))[0] for _ in range(4)]

    assert [row["score"] for row in rows] == [0.65, 0.0, 0.5, 1.0]
    assert [2 * row["score"] - 1 for row in rows] == pytest.approx([0.3, -1.0, 0.0, 1.0])
    assert [row["metadata"]["reward"] for row in rows] == [0.3, -1.0, 0.0, 1.0]
