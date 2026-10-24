"""Play one battery-day end to end with no model spend, and turn it into Episode JSON: `agent-env gridsim sweep run`
plays the `full` harness through `agent-env run` (the gridsim env and gridsim-llm on local Docker), and
tests/plugin/fake_litellm.py, on this machine, answers the agent with scripted turns: get_situation and a check of
greedy, then a check of the DP optimum, then its submit. It fails unless the sweep scores 1.0 with two checks and four
calls, `agent-env gridsim episodes` replays every recorded call into a gridsim.episode/v1 file that gridsim_core
agrees with, and `sweep report` writes the card and the board. Then the installed bundle's `oneshot` task plays the
fixture day with a scripted submit of the optimum: it must pass, and the request the agent sends must carry
gridsim_core's oneshot system prompt, situation and submit_schedule schema byte for byte.

Run it from the checkout after `agent-env gridsim setup --agent`, with the dev extra installed:

    PYTHONPATH=tests/plugin python scripts/scripted_e2e.py [--task ID] [--out DIR]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fake_litellm import FakeLiteLLM

from agentenv_gridsim.server import read_pack
from gridsim_core.grade import grade
from gridsim_core.prompt import messages, tool_schemas
from gridsim_core.task import data_root, index_pack

MODEL = "openai/gpt-6.1-sol"
CONFIG = Path(__file__).resolve().parents[1] / ".agentenv" / "config.toml"
ONESHOT_TASK = "dam-v1-2022-11-14-LZ_WEST-2h-m"


def call(name: str, arguments: dict, i: int) -> dict:
    return {"id": f"call_{i}", "name": name, "arguments": json.dumps(arguments)}


def turns(task: dict) -> list[dict]:
    f = task["refs"]["foresight"]
    usage = {"input": 4000, "output": 600, "cached": 0, "cache_write": 0}
    return [{"content": "Looking at the day.", "reasoning": "Charge low, sell high.", "stop": "completed",
             "tool_calls": [call("get_situation", {}, 0),
                            call("check_schedule", {"actions": f["baselines"]["greedy"]["schedule"]}, 1)],
             "usage": usage},
            {"content": "", "reasoning": "Try the better one.", "stop": "completed",
             "tool_calls": [call("check_schedule", {"actions": f["opt"]}, 2)], "usage": usage},
            {"content": "Submitting.", "reasoning": "", "stop": "completed",
             "tool_calls": [call("submit_schedule", {"actions": f["opt"]}, 3)], "usage": usage}]


def gridsim(*args: str, env: dict, cwd: Path) -> str:
    out = subprocess.run([sys.executable, "-m", "agent_env.cli", "gridsim", *args], env=env, cwd=cwd,
                         capture_output=True, text=True)
    print(out.stdout + out.stderr)
    if out.returncode:
        raise SystemExit(f"agent-env gridsim {' '.join(args)} exited {out.returncode}")
    return out.stdout


def endpoint(port: str) -> dict:
    return {**os.environ, "LITELLM_BASE_URL": f"http://host.docker.internal:{port}", "LITELLM_API_KEY": "sk-fake"} | (
        {"AGENT_ENV_CONFIG": str(CONFIG)} if CONFIG.is_file() else {})


def oneshot() -> None:
    """The bundle's oneshot task on a scripted submit: it passes, and the agent's request is path B's, byte for byte."""
    task = index_pack("fixtures")[ONESHOT_TASK]
    submit = {"content": "", "reasoning": "", "stop": "completed", "usage": {"input": 3000, "output": 500},
              "tool_calls": [call("submit_schedule", {"actions": task["refs"]["foresight"]["opt"]}, 0)]}
    with FakeLiteLLM([submit], host="0.0.0.0") as fake:
        out = subprocess.run([sys.executable, "-m", "agent_env.cli", "run", "gridsim", "--task", "oneshot", "--model",
                              MODEL], env=endpoint(fake.url.rsplit(":", 1)[1]), capture_output=True, text=True)
        print(out.stdout + out.stderr)
        assert "tasks/oneshot.json v" in out.stdout and ": passed (grade: 1)" in out.stdout, "oneshot did not pass"
        [(_, _, body)] = fake.requests
    system, user = messages(task, "foresight", 0)
    tools = [{"type": "function", "function": {k: t[k] for k in ("name", "description", "parameters")}}
             for t in body["tools"]]
    assert json.dumps(tools) == json.dumps(tool_schemas("foresight", 0)), body["tools"]
    assert body["instructions"] == system["content"] and body["input"][0]["content"][0]["text"] == user["content"]
    assert (body["reasoning"]["effort"], body["max_output_tokens"]) == ("high", 4096)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--task", help="A fixture task id (default: the first fixture).")
    parser.add_argument("--out", type=Path, help="The folder to run in (default: a temporary one).")
    args = parser.parse_args()
    fixtures = read_pack(data_root() / "fixtures")
    task = next(t for t in fixtures if t["task_id"] == args.task) if args.task else fixtures[0]
    cwd = args.out or Path(tempfile.mkdtemp(prefix="gridsim-e2e-"))
    cwd.mkdir(parents=True, exist_ok=True)
    with FakeLiteLLM(turns(task), host="0.0.0.0") as fake:
        port = fake.url.rsplit(":", 1)[1]
        env = endpoint(port)
        gridsim("sweep", "run", "--name", "scripted-e2e", "--models", MODEL, "--pack", "fixtures", "--tasks",
                task["task_id"], "--cap-usd", "1", "--episode-cap-usd", "0.5", "--parallel", "1", env=env, cwd=cwd)
        assert len(fake.requests) == 3, f"the agent sent {len(fake.requests)} requests, not 3"
    raw = cwd / "results/runs/scripted-e2e/raw"
    [row] = [json.loads(line) for line in (raw / "results.jsonl").read_text().splitlines()]
    expected = grade(task, task["refs"]["foresight"]["opt"])
    assert (row["outcome"], row["reward"], row["r_opt"], row["checks"], row["calls"], row["end_reason"]) == (
        "scored", expected["reward"], expected["r_opt"], 2, 4, "submitted"), row
    gridsim("episodes", "scripted-e2e", env=env, cwd=cwd)
    [path] = sorted((cwd / "results/runs/scripted-e2e").glob("*.json"))
    episode = json.loads(path.read_text())
    assert (episode["schema"], episode["path"], episode["bundle"], episode["reward"], episode["r_opt"]) == (
        "gridsim.episode/v1", "A", "full", expected["reward"], expected["r_opt"])
    assert [s["tool"] for s in episode["steps"]] == ["get_situation", "check_schedule", "check_schedule",
                                                     "submit_schedule"]
    assert episode["final_schedule"] == task["refs"]["foresight"]["opt"]
    gridsim("sweep", "report", "scripted-e2e", env=env, cwd=cwd)
    card = json.loads((cwd / "results/eval-v1.json").read_text())
    assert card["models"][0]["mean"] == expected["reward"] and card["baselines"]["idle"] == 0.2
    oneshot()
    print(f"scripted e2e passed: reward {row['reward']}, episode {path}, card {cwd / 'results/eval-v1.json'}; "
          "oneshot passed on path B's prompt and schema")


if __name__ == "__main__":
    main()
