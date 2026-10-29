"""The CPU check of the training bundle, no model: operating days played through AgentEnv's TRL integration the way
GRPOTrainer plays them. AgentEnv.local serves the bundle with the training reward, `dataset_for(split)` gives the rows,
`factory` the environment class; per row an instance is reset, a core policy (the anchor by default) makes its calls
through the instance's tool methods, `end_turn` ends each wake and answers with the next, and `get_reward` scores it;
each thread resets its instance again for its next row, as TRL reuses its pool. A shadow gridsim_core Session plays the
same calls in process: every tool output and wake must match it byte for byte, and the reward must be its hindsight
capture floored at -1.

    python replay.py --bundle bundles/desk-v4-train --pack-dir data/desk/desk-v4-train --split train --limit 8 \\
        --out replay.json
"""

import argparse
import json
import logging
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_env.training.trl import ENDED, AgentEnv

from gridsim_core.desk import Session, grade, load_series, load_task, policies, system_prompt, text, tool_specs

FLOOR = -1.0


def capture(scores: dict[str, float]) -> float:
    return 2 * scores["capture"] - 1


class Shadow:
    """The policy's Session: state read from the shadow, every call sent through the environment's tool method, as TRL
    calls it, and played on the shadow, outputs compared."""

    def __init__(self, session: Session, env, calls: list, problems: list):
        self.__dict__.update(_s=session, _env=env, _calls=calls, _problems=problems)

    def __getattr__(self, name):
        return getattr(self._s, name)

    def call(self, name, args=None, role="default"):
        args = args or {}
        got = getattr(self._env, name)(**args)
        want = text(self._s.call(name, args))
        self._calls.append(name)
        if got != want:
            self._problems.append(f"{name}: factory {got[:200]!r} != session {want[:200]!r}")
        return json.loads(want)


def play(env, row: dict, pack_dir: str, policy: str) -> dict:
    task = load_task(pack_dir, row["task_id"].rsplit("/", 1)[-1])
    s = Session(task, load_series(pack_dir, task))
    problems: list[str] = []
    calls: list[str] = []
    t0 = time.monotonic()
    env.reset(**{k: row[k] for k in ("split", "index", "task_id")})
    if row["prompt"][0]["content"] != system_prompt(s):
        problems.append("the row's system prompt is not core's")
    wake = s.start()
    if row["prompt"][-1]["content"] != text(wake):
        problems.append("the row's prompt is not the start wake")
    wakes = 0
    while wake is not None:
        policies.POLICIES[policy](Shadow(s, env, calls, problems), wake)
        reply = f"wake {wakes} done"
        answer = env.end_turn(response=reply)
        wake = s.end_turn(reply)
        wakes += 1
        if answer != (ENDED if wake is None else text(wake)):
            problems.append(f"end_turn after wake {wakes} answered {answer[:200]!r}")
    reward = env.get_reward()
    g = grade(s)
    want = None if g["capture"] is None else max(g["capture"], FLOOR)
    if reward is None or want is None or abs(reward - want) > 1e-9:
        problems.append(f"get_reward {reward} != the shadow's capture floored at -1 {want}")
    return {"task_id": task["task_id"], "reward": reward, "capture": g["capture"], "r": g["reward"],
            "anchor_capture": g["anchor_capture"], "wakes": wakes, "calls": len(calls),
            "wall_s": round(time.monotonic() - t0, 2), "problems": problems}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bundle", type=Path, required=True)
    ap.add_argument("--pack-dir", required=True, help="the pack the split's tasks come from, for the shadow")
    ap.add_argument("--split", default="train")
    ap.add_argument("--task", action="append", help="these task ids of the split (default: the first --limit)")
    ap.add_argument("--limit", type=int, default=4)
    ap.add_argument("--policy", default="anchor", choices=sorted(policies.POLICIES))
    ap.add_argument("--parallel", type=int, default=4, help="rollouts played at once, as a GRPO group is")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    for noisy in ("httpx", "httpcore", "websockets", "agentenv_protocol"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    t0 = time.monotonic()
    env = AgentEnv.local(a.bundle, split=a.split, reward=capture, max_concurrent_envs=a.parallel + 2,
                         tool_timeout=300, reset_timeout=1800)
    report: dict = {"server_start_s": round(time.monotonic() - t0, 2)}
    try:
        rows = list(env.dataset)
        rows = [r for r in rows if r["task_id"].rsplit("/", 1)[-1] in a.task] if a.task else rows[:a.limit]
        t1 = time.monotonic()
        Environment = env.factory
        tools = sorted(t["name"] for t in Environment._tools)
        want = sorted([sp["function"]["name"] for sp in tool_specs("v4", True)] + ["end_turn"])
        report |= {"factory_s": round(time.monotonic() - t1, 2), "tools_are_desk_and_end_turn": tools == want,
                   "split_rows": len(env.dataset), "factory": {"tools": [dict(t) for t in Environment._tools]}}
        t2 = time.monotonic()
        pooled = threading.local()

        def rollout(row: dict) -> dict:
            if not hasattr(pooled, "env"):
                pooled.env = Environment()
            return play(pooled.env, row, a.pack_dir, a.policy)

        with ThreadPoolExecutor(a.parallel) as pool:
            report["tasks"] = list(pool.map(rollout, rows))
        report["rollouts_wall_s"] = round(time.monotonic() - t2, 2)
    finally:
        env.close()
        report["total_s"] = round(time.monotonic() - t0, 2)
    done = report.get("tasks", [])
    report["summary"] = {"rollouts": len(done), "problems": sum(len(t["problems"]) for t in done),
                         "reward_mean": round(statistics.fmean(t["reward"] for t in done), 4) if done else None,
                         "wall_s_median": statistics.median(t["wall_s"] for t in done) if done else None}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(report, indent=1) + "\n")
    keys = ("task_id", "reward", "capture", "r", "wakes", "calls", "wall_s")
    print(json.dumps({k: v for k, v in report.items() if k not in ("tasks", "factory")} | {"tasks": [
        {k: t[k] for k in keys} | {"problems": t["problems"][:3]} for t in done]}, indent=1))


if __name__ == "__main__":
    main()
