"""Play a live battery-day through `agent-env run` with no model spend: the task deploys gridsim-live on the gateway and
gridsim-llm on local Docker, and tests/plugin/fake_litellm.py, on this machine, answers the agent with the naive
policy's turns, one turn per watch: v1's foresight DP plan committed as the DA position at watch 0, then advance at
every watch. It fails unless each watch's trigger fired once, at the watch's time, delivering the watch's notices in
order; the agent was never offered grid_notice; every tool output the agent got is the one the same calls get from
gridsim_core's Session in process, so each watch's bulletins came with the first tool result after its advance and
no other; get_time read the watch's time and held still between watches while real time passed; data/get holds the
day as played in process; and the day scored what it scores in process, which on a day without a derate is the naive
reward the task row stores.

Run it from the checkout after `agent-env gridsim setup --agent`, with the dev extra installed:

    python scripts/live_e2e.py [--task ID] [--pack PACK] [--tier foresight|blind] [--model ID] [--out day.json]

The default plays the gridsim-live bundle's `day` task; another day is written as a one-task bundle in a temporary
folder.
"""

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "plugin"))

from fake_litellm import FakeLiteLLM  # noqa: E402

from agentenv_gridsim import live_tasks  # noqa: E402
from agentenv_gridsim.live import LIVE_PACK_NAMES  # noqa: E402
from agentenv_gridsim.server import TaskIndex, pack_dirs  # noqa: E402
from agentenv_gridsim.sweep import context, trajectory  # noqa: E402
from gridsim_core.live import LIVE_ENV, NOTICE_TOOL, Session  # noqa: E402

MODEL = "openai/gpt-6.1-sol"
PAUSE = 2.0
CLOCK = "get_time"


class PausingFake(FakeLiteLLM):
    """Answers each request PAUSE seconds late, so real time passes between turns while the clock should not."""

    def _route(self, build):
        endpoint = super()._route(build)

        async def paused(request):
            await asyncio.sleep(PAUSE)
            return await endpoint(request)
        return paused


def bundle_day() -> str:
    steps = json.loads(files("agentenv_gridsim.bundles").joinpath("gridsim-live/tasks/day.json").read_text())
    return next(s for s in steps if s["id"] == "load-task")["directives"][0]["args"]["task_id"]


def script(task: dict, watches: int) -> list[list[tuple[str, dict]]]:
    """The naive policy's calls, one turn per watch: read the clock, commit the naive DA position at watch 0, advance,
    then read the new watch's situation and the clock again."""
    turns = []
    for k in range(watches):
        calls = [(CLOCK, {})] + ([("commit_da", {"position": task["refs"]["naive"]["da"]})] if k == 0 else [])
        calls.append(("advance", {}))
        if k < watches - 1:
            calls += [("get_situation", {}), (CLOCK, {})]
        turns.append(calls)
    return turns


def in_process(task: dict, tier: str, turns: list) -> tuple[Session, list[tuple[str, str]]]:
    """The same calls on a Session, the triggers' grid_notice calls after each advance that opens a watch: the outputs
    path B' gets."""
    s, outs = Session(task, tier), []
    for name, args in (c for calls in turns for c in calls if c[0] != CLOCK):
        out = s.call(name, args)
        outs.append((name, out))
        if name == "advance" and "watch" in json.loads(out):
            s.deliver_watch_notices()
    return s, outs


def fake_turns(turns: list) -> list[dict]:
    return [{"stop": "completed", "tool_calls": [{"id": f"call_{t}_{i}", "name": n, "arguments": json.dumps(a)}
                                                 for i, (n, a) in enumerate(calls)]}
            for t, calls in enumerate(turns)]


def check(task: dict, tier: str, fake: FakeLiteLLM, ctx: dict, played: Session, expected: list) -> dict:
    watches = played.watches
    m = ctx["metadata"]
    v = m["verifications"]["gridsim"]
    day = v["results"][0]["episode"]
    response = next(p for p in ctx["prompt_responses"] if p.get("step_id") == "play")
    play = response["structured_output"]
    entry = m["env_trigger_state"][LIVE_ENV]
    capture = json.loads(trajectory(entry["object_url"]))
    problems = []

    fired, actions = {}, {}
    for e in capture["state"]["events"]:
        if e["kind"] == "fired":
            fired.setdefault(e["trigger_id"], []).append(e["virtual_time"])
        elif e["kind"] == "action_ok":
            actions.setdefault(e["trigger_id"], []).append(e["detail"]["args"]["event_id"])
    states = {t["id"]: t for t in entry["triggers"]} if isinstance(entry["triggers"], list) else entry["triggers"]
    for w in watches[1:]:
        tid = f"watch-{w.index}"
        t = states[tid]
        if (t["status"], t["fire_count"], fired.get(tid)) != ("fired", 1, [w.time_utc]):
            problems.append(f"{tid}: {t}, fired at {fired.get(tid)}, not once at {w.time_utc}")
        if actions.get(tid, []) != [n.event_id for n in w.notices]:
            problems.append(f"{tid} delivered {actions.get(tid)}, not {[n.event_id for n in w.notices]}")

    offered = sorted({tuple(t["name"] for t in body["tools"]) for _, _, body in fake.requests})
    if any(NOTICE_TOOL in names for names in offered):
        problems.append(f"the agent was offered {NOTICE_TOOL}: {offered}")

    record = json.loads(trajectory(response["agent_trajectory_object_url"]))
    got = [(msg["name"], msg["content"]) for msg in record["messages"] if msg["role"] == "tool"]
    session_calls = [(n, out) for n, out in got if n != CLOCK]
    if session_calls != expected:
        first = next((i for i, (a, b) in enumerate(zip(session_calls, expected, strict=False)) if a != b), None)
        problems.append(f"{len(session_calls)} outputs, {len(expected)} in process; the first that differs: {first}")
    watch, reads, bulletins = 0, {}, []
    for name, out in got:
        result = json.loads(out)
        if name == CLOCK:
            reads.setdefault(watch, []).append(result["current_time"])
            continue
        if result.get("messages"):
            bulletins.append({"watch": watch, "tool": name, "event_ids": [x["event_id"] for x in result["messages"]]})
        if name == "advance" and "watch" in result:
            watch = result["watch"]
    want = [{"watch": w.index, "tool": "get_situation", "event_ids": [n.event_id for n in w.notices]}
            for w in watches[1:] if w.notices]
    if bulletins != want:
        problems.append(f"bulletins {bulletins}, not {want}")
    for k, read in reads.items():
        if set(read) != {watches[k].time_utc} or len(read) != (1 if k == 0 else 2):
            problems.append(f"get_time in watch {k} read {read}, not {watches[k].time_utc}")
    if sorted(reads) != list(range(len(watches))):
        problems.append(f"get_time was read in watches {sorted(reads)}")
    clock = capture["clock"]
    if clock.get("virtual_seconds_per_real_second") != 0 or clock.get("t0") != watches[-1].time_utc:
        problems.append(f"the clock at the end: {clock}")

    if day != json.loads(json.dumps(played.data())):
        problems.append("data/get differs from the day played in process")
    naive, want = task["refs"]["roll"][tier]["naive_reward"], played.grade()
    g = day["grade"]
    if (v["score"], g["reward"], play["reward"]) != (want["reward"],) * 3:
        problems.append(f"scored {v['score']} (grade {g['reward']}, agent {play['reward']}), {want['reward']} in "
                        "process")
    if not played.limits and (want["reward"] != naive or abs(want["profit_usd"] - task["refs"]["p_naive"]) > 1e-6):
        problems.append(f"naive scored {want['reward']} (profit {want['profit_usd']}); the row stores {naive} "
                        f"(profit {task['refs']['p_naive']})")
    if not day["audit"]["ok"] or day["end_reason"] != "done" or play["end_reason"] != "done":
        problems.append(f"audit {day['audit']}, env {day['end_reason']}, agent {play['end_reason']}")
    if len(fake.requests) != play["turns"] or play["turns"] != len(watches):
        problems.append(f"{len(fake.requests)} requests for {play['turns']} turns over {len(watches)} watches")
    return {"problems": problems, "task_id": task["task_id"], "tier": tier, "score": v["score"],
            "naive_reward": naive, "watches": [w.time for w in watches], "fired": fired, "actions": actions,
            "tools": offered, "bulletins": bulletins, "get_time": reads, "clock": clock, "turns": play["turns"],
            "tool_calls": play["tool_calls"], "calls_used": day["calls_used"],
            "planning_calls": day["planning_calls"], "notices": [(n["event_id"], n["watch"], n["via"], n["call"])
                                                                  for n in day["notices"]],
            "data_get_sha256": hashlib.sha256(json.dumps(day, sort_keys=True).encode()).hexdigest()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--task", help="the day to play; default: the gridsim-live bundle's day")
    parser.add_argument("--pack", choices=LIVE_PACK_NAMES, default="fixtures-live", help="the live pack holding it")
    parser.add_argument("--tier", choices=["foresight", "blind"], default="foresight")
    parser.add_argument("--model", default=MODEL, help="the model id the run passes (the fake answers any)")
    parser.add_argument("--out", type=Path, help="write the day's data/get here")
    args = parser.parse_args()
    default = bundle_day()
    task_id = args.task or default
    task = TaskIndex(pack_dirs(LIVE_PACK_NAMES)).get(task_id)
    if task is None:
        sys.exit(f"no live task {task_id!r}")
    turns = script(task, len(Session(task, args.tier).watches))
    played, expected = in_process(task, args.tier, turns)
    with tempfile.TemporaryDirectory() as tmp:
        bundle, name = LIVE_ENV, "day"
        if task_id != default or args.tier != "foresight":
            live_tasks.generate(args.pack, Path(tmp), tier=args.tier, task_ids=[task_id])
            bundle, name = tmp, task_id
        with PausingFake(fake_turns(turns), host="0.0.0.0") as fake:
            port = fake.url.rpartition(":")[2]
            run = subprocess.run([sys.executable, "-m", "agent_env.cli", "run", bundle, "--task", name,
                                  "--model", args.model], capture_output=True, text=True,
                                 env={**os.environ, "LITELLM_BASE_URL": f"http://host.docker.internal:{port}",
                                      "LITELLM_API_KEY": "sk-fake-live"})
    print(run.stdout + run.stderr)
    instance = re.findall(r"instance (\S+)", run.stdout)
    if not instance:
        sys.exit("the run stored no instance")
    ctx = context(instance[-1])
    report = check(task, args.tier, fake, ctx, played, expected)
    if args.out:
        args.out.write_text(json.dumps(ctx["metadata"]["verifications"]["gridsim"]["results"][0]["episode"],
                                       indent=2, sort_keys=True) + "\n")
    print(json.dumps({"instance": instance[-1], **report}, indent=1, default=str))
    if report["problems"]:
        sys.exit(f"{len(report['problems'])} problems")


if __name__ == "__main__":
    main()
