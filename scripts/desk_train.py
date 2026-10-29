"""Desk training: the desk-v4-train bundle, GridSim desk operating days for fine-tuning a model with TRL through
AgentEnv, as `agent-env gridsim tasks training-pack` writes GridSim v1's.

Each task is one operating day of desk-v4-train under the v4 layer and env, as desk-tasks writes it: the plain default
agent with no harness config, woken by gridsim-desk-hook and graded by gridsim-desk-verifier (R), plus a `capture`
step whose verifier scores the hindsight capture C floored at -1, as (max(C, -1) + 1) / 2 since a verifier step's
score is clamped to [0, 1]. The hook finds the task's one desk env itself, since a bundle's env is deployed under its
bundle-qualified id. Splits: `train` and `val` (the pack's operating days that pass its operator_ok check and have C
defined), and `bench` (desk-v4-bench's 32 three-day windows). The env builds where it deploys from the plugin's tree at
desk-v4-freeze with both packs added from their commits.

    python scripts/desk_train.py bundle --out bundles/desk-v4-train
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib.resources import files
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_bench  # noqa: E402

from agentenv_gridsim import desk_tasks  # noqa: E402
from gridsim_core.desk import load_series, load_tasks  # noqa: E402

PACK = "desk-v4-train"
BENCH = "desk-v4-bench"
PACKS = {BENCH: desk_bench.PACKS[BENCH], PACK: "28816a6fd2bb116b91a67d59ae29cd539738ae70"}
SPLITS = ("train", "val", "bench")
CAPTURE = "gridsim-desk-capture-verifier"
CAPTURE_STEP = "capture"
CAPTURE_VERIFY = files("agentenv_gridsim") / "training-pack-desk-verify.py"
REWARD = "lambda scores: 2 * scores['capture'] - 1"


def steps(task: dict, series: dict, pack: str) -> list[dict]:
    out = desk_tasks.steps(task, series, pack)
    for step in out:
        if step["type"] == "prompt_agent":
            step["post_turn_hooks"] = [hook | {"params": {k: v for k, v in hook["params"].items() if k != "env_id"}}
                                       for hook in step["post_turn_hooks"]]
    return out + [{"id": CAPTURE_STEP, "type": "env_outcome_verifier", "env_id": out[0]["env_id"],
                   "file_artifact_id": CAPTURE, "verifier_id": "gridsim-desk-capture",
                   "score_aggregator": "weighted_average"}]


def rows(train: str, bench: str, operator_gaps: bool = False) -> dict[str, list[dict]]:
    """The splits' task rows: the train pack's days by their split that pass the pack builder's operator_ok check
    (all of them with ``operator_gaps``) and whose C is defined, and every bench window."""
    days = [r for r in load_tasks(train) if not r["refs"]["c_undefined"] and (r["operator_ok"] or operator_gaps)]
    return {"train": [r for r in days if r["split"] == "train"], "val": [r for r in days if r["split"] == "val"],
            "bench": load_tasks(bench)}


def write(out: Path, *, operator_gaps: bool = False, train_dir: str | None = None) -> dict[str, list[str]]:
    with tempfile.TemporaryDirectory() as tmp:
        sources = {BENCH: _source(BENCH, Path(tmp)), PACK: train_dir or _source(PACK, Path(tmp))}
        return _write(out, sources, operator_gaps)


def _write(out: Path, sources: dict[str, str], operator_gaps: bool) -> dict[str, list[str]]:
    splits = rows(sources[PACK], sources[BENCH], operator_gaps)
    envs = set()
    for split in SPLITS:
        pack = BENCH if split == "bench" else PACK
        for row in splits[split]:
            task_steps = steps(row, load_series(sources[pack], row), pack)
            envs.add(task_steps[0]["env_id"])
            _put(out / "tasks" / f"{row['task_id']}.json", json.dumps(task_steps, indent=2, ensure_ascii=False) + "\n")
        if splits[split]:
            _put(out / "evals" / f"{split}.toml",
                 "tasks = [\n" + "".join(f'  "{r["task_id"]}",\n' for r in splits[split]) + "]\n")
    for artifact, name in ((desk_tasks.HOOK, "hook.py"), (desk_tasks.VERIFIER, "verify.py")):
        _put(out / "artifacts" / artifact / name, (desk_tasks.ARTIFACTS / artifact / name).read_text())
    _put(out / "artifacts" / CAPTURE / "verify.py", CAPTURE_VERIFY.read_text())
    layers = "".join(desk_bench.PACK_LAYER.format(commit=PACKS[p], pack=p) for p in (BENCH, PACK))
    for env in sorted(envs):
        _put(out / "envs" / env / "Dockerfile", desk_bench.ENV_DOCKERFILE.replace("{pack}", layers))
        shutil.copy(desk_bench.CONSTRAINTS, out / "envs" / env / "constraints.txt")
        _put(out / "envs" / env / "env.toml", desk_bench.ENV_TOML.format(name=env))
    n = {split: len(splits[split]) for split in SPLITS}
    _put(out / "README.md", README.format(**n, env=", ".join(sorted(envs)), freeze=desk_bench.FREEZE[:7],
                                          repo=desk_bench.REPO, bench_commit=PACKS[BENCH][:7],
                                          train_commit=PACKS[PACK][:7], hook=desk_tasks.HOOK,
                                          verifier=desk_tasks.VERIFIER, capture=CAPTURE, reward=REWARD,
                                          licence=desk_tasks.LICENCE))
    return {split: [r["task_id"] for r in splits[split]] for split in SPLITS}


def _source(pack: str, tmp: Path) -> str:
    """A pack read from the commit the env image adds it from."""
    tar = subprocess.run(["git", "-C", str(desk_bench.ROOT), "archive", PACKS[pack], f"data/desk/{pack}"], check=True,
                         capture_output=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    return str(tmp / "data" / "desk" / pack)


def _put(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


README = """GridSim desk for training: trade one real ERCOT battery as a QSE's battery desk for one operating day, \
from the day-ahead market the day before through real time, on a frozen virtual clock that moves only between turns. \
{train} train and {val} val operating days of the desk-v4-train pack under the v4 layer, and the {bench} three-day \
windows of desk-v4-bench in a `bench` split; the same eleven desk tools in every task.

Each task deploys {env}, loads its day through `urn:gridsim:desk-load/v1`, shows the hidden tools to the hook role \
and hides the gateway clock from the agent, gives the plain default agent the start wake with the desk brief as its \
system prompt, and wakes it after each turn through `{hook}`. Two steps score it: `grade` ({verifier}) records the \
reward R, and `capture` ({capture}) records the hindsight capture C = (P - P_idle) / (P_hind - P_idle) floored at -1 \
as (max(C, -1) + 1) / 2, since a verifier step's score is clamped to [0, 1]. Train on C with the reward function \
`{reward}`, on R with `reward="grade"`:

```python
from agent_env.training.trl import AgentEnv

env = AgentEnv.local("bundles/desk-v4-train", split="train", reward={reward})
```

A served task's agent is played from outside, by TRL through `agent_env.training.trl`, and its turns end through the \
`end_turn` tool, since TRL ends a rollout at a reply without a tool call.

The env image builds from `envs/`: the plugin ({repo}) at {freeze} (desk-v4-freeze) with the desk-v4-bench pack from \
{bench_commit} and the desk-v4-train pack from {train_commit}. `python scripts/desk_train.py bundle` writes this folder.

{licence}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bundle", help="write the desk-v4-train bundle")
    b.add_argument("--out", type=Path, default=Path("bundles") / PACK)
    b.add_argument("--operator-gaps", action="store_true", help="also the days whose operator disclosure is "
                   "incomplete (operator_ok false), which only the operator replay reference reads")
    b.add_argument("--train-dir", help="read desk-v4-train from this folder rather than its commit (the env image "
                   "still adds the commit's)")
    a = ap.parse_args()
    if a.out.exists():
        shutil.rmtree(a.out)
    ids = write(a.out, operator_gaps=a.operator_gaps, train_dir=a.train_dir)
    counts = ", ".join(f"{split} {len(v)}" for split, v in ids.items())
    print(f"Wrote {sum(map(len, ids.values()))} tasks into {a.out} ({counts}); serve it with "
          f"build_app({str(a.out)!r}, reward={REWARD})")


if __name__ == "__main__":
    main()
