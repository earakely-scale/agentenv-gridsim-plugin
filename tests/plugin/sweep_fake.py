"""A stand-in `agent-env run` for the sweep, and the instance contexts a GridSim run stores as `Task.run()` stores them
(`TaskStepContext.to_safe_dict()`): the verifier's rows and episode, and the play step's PromptResponse and failures."""

import json
import sys
import textwrap
from pathlib import Path

import pytest
from agent_env.task_step.context import PromptResponse, TaskStepContext

from agentenv_gridsim import sweep
from gridsim_core.grade import grade

FAKE = textwrap.dedent("""
    import fcntl, json, os, signal, sys, time, uuid
    from pathlib import Path

    here = Path(os.environ["FAKE_AGENT_ENV"])
    args = sys.argv[1:]
    stopped = []
    signal.signal(signal.SIGTERM, lambda *_: stopped.append(1))
    with open(here / "calls.jsonl", "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0)
        earlier = [c["argv"] for c in map(json.loads, f.read().splitlines()) if "start" in c]
        f.write(json.dumps({"argv": args, "pythonpath": os.environ.get("PYTHONPATH"), "pid": os.getpid(),
                            "start": time.time()}) + "\\n")
    if "--dry-run" in args:
        sys.exit(int(os.environ.get("FAKE_DRY_RUN_EXIT", "0")))
    task, model = args[args.index("--task") + 1], args[args.index("--model") + 1]
    script = json.loads((here / "script.json").read_text())
    plan = script.get(f"{model}|{task}") or script["*"]
    step = plan[min(earlier.count(args), len(plan) - 1)]
    while step.get("wait") and not stopped:
        time.sleep(0.02)
    time.sleep(step.get("sleep", 0))
    if step.get("context") is not None:
        instance = f"@local/fake/tasks/{task}-{uuid.uuid4().hex[:8]}"
        (here / "instances").mkdir(exist_ok=True)
        (here / "instances" / instance.replace("/", "_")).write_text(json.dumps(step["context"]))
        print(f"  tasks/{task}.json v1: {step.get('says', 'passed')}, 12.5s, instance {instance}")
    sys.exit(143 if stopped else step.get("exit", 0))
""")


class Fake:
    """The stand-in's folder: script.json says what each (model, task) run does on its first, second, ... call."""

    def __init__(self, root: Path):
        self.root = root

    def script(self, plans: dict[str, list[dict]]) -> None:
        (self.root / "script.json").write_text(json.dumps(plans))

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def runs(self) -> list[list[str]]:
        return [c["argv"] for c in self.calls() if "start" in c and "--dry-run" not in c["argv"]]


@pytest.fixture
def fake(tmp_path, monkeypatch) -> Fake:
    """The sweep in tmp_path, its attempts played by the stand-in, which leaves the contexts it is scripted with
    where the sweep's instance reader finds them, and each run's transcript as the record it names."""
    root = tmp_path / "fake"
    root.mkdir()
    script = root / "agent_env_run.py"
    script.write_text(FAKE)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FAKE_AGENT_ENV", str(root))
    monkeypatch.setattr(sweep, "AGENT_ENV", [sys.executable, str(script)])
    monkeypatch.setattr(sweep, "POLL_SECONDS", 0.02)
    monkeypatch.setattr(sweep, "context",
                        lambda instance: json.loads((root / "instances" / instance.replace("/", "_")).read_text()))
    monkeypatch.setattr(sweep, "trajectory", lambda uri: (root / "records" / Path(uri).name).read_bytes()
                        if (root / "records" / Path(uri).name).is_file() else b"{}")
    return Fake(root)


def summary(model: str, end_reason: str = "submitted", cost: float = 0.0123, **fields) -> dict:
    return {"agent": "gridsim-llm", "model": model, "route": "responses", "effort": "high", "end_reason": end_reason,
            "submitted": end_reason == "submitted", "turns": 2, "tool_calls": 3, "checks": 1, "input_tokens": 6000,
            "output_tokens": 1200, "cached_tokens": 0, "cache_write_tokens": 0, "cost_usd": cost, "max_cost_usd": 1.0,
            "priced_cost_usd": cost, "failed_requests": 0, "seconds": 20.5, "error": None} | fields


def episode(task: dict, actions: list[int] | None, tier: str = "foresight", checks_used: int = 1) -> dict:
    """data/get once done, as the verifier slims it (no task row)."""
    g = grade(task, actions, tier) if actions is not None else None
    return {"task_id": task["task_id"], "tier": tier, "checks": 3, "checks_used": checks_used,
            "calls_used": checks_used + 2, "done": actions is not None, "end_reason": "submitted" if g else None,
            "schedule": actions, "grade": g, "reward": g["reward"] if g else None}


def play(task: str, model: str, structured: dict | None, code: str | None = None, message: str | None = None,
         trajectory: str | None = "file:///state/agent-env/object_store/trajectories/play.json") -> PromptResponse:
    return PromptResponse(prompt_id=task, response=f"{code or 'submitted'}: ...",
                          agent_trajectory_object_url=trajectory, model=model,
                          error_type="infra_error" if code else None, error_code=code, error_message=message,
                          agent_session_id="a2a-1", agent_name="gridsim-llm", step_id="play",
                          structured_output=structured)


def failure(step_id: str, step_type: str, error: str, error_type: str = "RuntimeError") -> dict:
    return {"step_id": step_id, "step_type": step_type, "error": error, "error_type": error_type,
            "started_at_utc": "2026-10-24T08:00:00+00:00", "duration_seconds": 3.0, "is_fatal": True}


def stored(prompt: PromptResponse | None = None, **metadata) -> dict:
    context = TaskStepContext(prompt_responses=[prompt] if prompt else [], metadata=metadata,
                              instance_id="@local/fake/tasks/t-1")
    return context.to_safe_dict()


def scored(task: dict, model: str, actions: list[int] | None, tier: str = "foresight", cost: float = 0.0123,
           trajectory: str = "file:///state/agent-env/object_store/trajectories/play.json") -> dict:
    data = episode(task, actions, tier)
    g = data["grade"] or {}
    reward, r_opt = g.get("reward", 0.0), g.get("r_opt", 0.0)
    return stored(play(task["task_id"], model, summary(model, "submitted" if actions else "turn_limit", cost),
                       trajectory=trajectory),
                  verifications={"gridsim": {"results": [
                      {"criterion": "gridsim", "result": reward >= 1.0, "score": reward, "weight": 1.0,
                       "episode": data},
                      {"criterion": "hindsight_capture", "result": r_opt >= 1.0, "score": r_opt, "weight": 0.0}],
                      "score": reward}})


def agent_failed(task: str, model: str, code: str, cost: float = 0.05) -> dict:
    return stored(play(task, model, summary(model, end_reason=code, cost=cost, error=f"APIStatusError: {code}"),
                       code=code, message=f"{code}: the episode stopped"),
                  failed_steps=[failure("play", "prompt_agent",
                                        f"A2A task failed (error_type=infra_error, error_code={code}): {code}")])


def step_failed(step_id: str, step_type: str) -> dict:
    return stored(failed_steps=[failure(step_id, step_type, f"{step_id} failed: the sandbox did not start")])
