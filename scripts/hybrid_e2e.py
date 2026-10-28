"""Play a hybrid site-day through `agent-env run` with no model spend: the task deploys gridsim-hybrid on the gateway
and gridsim-llm on local Docker, and tests/plugin/fake_litellm.py, on this machine, answers the agent with a scripted
policy's turns, one turn per watch: gridsim_core.hybrid's rolling MILP anchor (the default), the solar sponge or the
AS hog, its calls worked out in process watch by watch. It fails unless each watch's trigger fired once, at the
watch's time, delivering the watch's notices in order, each deployment's with its payload, which the env logged as
the scheduled one; each deployment dispatched frac x award in the hours of its real window, whatever watch revealed
it; the agent was never offered grid_notice; every tool output the agent got is the one the same calls get from
gridsim_core's hybrid Session in process, so each watch's bulletins came with the first tool result after its advance
and no other; get_time read the watch's time and held still between watches while real time passed; data/get holds
the day as played in process; the day scored the policy's stored reward and profit exactly (1.0 and P_anchor for the
anchor); and the agent's record replays byte for byte into Episode JSON v3 (the `episodes` path), its audit passing
with the agent's get_time reads.

Run it from the checkout after `agent-env gridsim setup --agent`, with the dev extra installed:

    python scripts/hybrid_e2e.py [--task ID] [--pack PACK] [--tier energy|reserves] [--policy anchor|sponge|as_hog]
        [--model ID] [--out day.json] [--episode episode.json]

The default plays the gridsim-hybrid bundle's `day` task; another day or tier is written as a one-task bundle in a
temporary folder.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests" / "hybrid"), str(ROOT / "scripts")]

from hybrid_days import in_process, scripted  # noqa: E402
from live_e2e import CLOCK, MODEL, PausingFake, fake_turns  # noqa: E402

from agentenv_gridsim import hybrid_tasks  # noqa: E402
from agentenv_gridsim.episodes import ReplayError, live_replay  # noqa: E402
from agentenv_gridsim.hybrid import HYBRID_PACK_NAMES  # noqa: E402
from agentenv_gridsim.server import TaskIndex, pack_dirs  # noqa: E402
from agentenv_gridsim.sweep import context, trajectory  # noqa: E402
from gridsim_core.hybrid import (  # noqa: E402
    EPISODE_SCHEMA,
    EVENT_PRODUCTS,
    HYBRID_ENV,
    NOTICE_TOOL,
    TOL,
    Session,
    anchor_policy,
    as_hog_policy,
    deploy_hours,
    sponge_policy,
)

POLICIES = {"anchor": anchor_policy(), "sponge": sponge_policy, "as_hog": as_hog_policy}


def bundle_day() -> str:
    steps = json.loads(files("agentenv_gridsim.bundles").joinpath("gridsim-hybrid/tasks/day.json").read_text())
    return next(s for s in steps if s["id"] == "load-task")["directives"][0]["args"]["task_id"]


def stored(task: dict, tier: str, policy: str) -> dict:
    """What the task row stores for the policy at the tier: its profit and reward."""
    refs = task["refs"][tier]
    return {"profit": refs["p_anchor"], "reward": 1.0} if policy == "anchor" else refs["baselines"][policy]


def with_clock(turns: list[list[tuple[str, dict]]]) -> list[list[tuple[str, dict]]]:
    """Each turn reads the clock first and, once a later watch is open, again after its get_situation."""
    return [[(CLOCK, {}), *calls] + ([(CLOCK, {})] if k < len(turns) - 1 else []) for k, calls in enumerate(turns)]


def episode_of(task: dict, tier: str, record: dict, model: str, instance: str) -> dict:
    """The run's Episode JSON v3 as `agent-env gridsim episodes` writes it: the record replayed through a hybrid
    Session, byte for byte, and audited with the agent's get_time reads."""
    s, reads = live_replay(task, tier, record, Session)
    return s.episode(bundle="live", path="A", model=model, trained="base", usage=record["usage"],
                     episode_id=instance.rsplit("/", 1)[-1]) | {"audit": s.audit(reads)}


def deployments(played: Session) -> tuple[list[dict], list[str]]:
    """Each hour a deployment dispatched awards in, from its payload's real window: the energy the plant delivered for
    it beyond regulation, against frac x award; problems where they differ, unless SoC limited the hour."""
    told = {e["event_id"]: e["watch"] for e in played.log if e["first"]}
    payloads = [n for w in played.watches for n in w.notices if n.deploy]
    frac = deploy_hours([n.deploy for n in payloads], played.day.dur)
    rows, problems = [], []
    for r in played.rows:
        h, a = r["h"], r["a"]
        want = sum(frac[h][k] * a[k] for k in EVENT_PRODUCTS)
        got = r["up_mwh"] - played.day.reg_up[h] * a["regup"]
        if want <= TOL and abs(got) <= TOL:
            continue
        limited = r["up_mwh"] + TOL < played.day.reg_up[h] * a["regup"] + want
        rows.append({"h": h, "want_mwh": round(want, 6), "event_mwh": round(got, 6), "soc_limited": limited,
                     "events": [n.event_id for n in payloads if frac_of(n, played)[h]],
                     "told_in_watch": sorted({told[n.event_id] for n in payloads if frac_of(n, played)[h]})})
        if abs(got - want) > TOL and not limited:
            problems.append(f"hour {h}: deployments delivered {got:.6f} MWh, their payloads dispatch {want:.6f}")
    return rows, problems


def frac_of(n, played: Session) -> list[float]:
    return [sum(f.values()) for f in deploy_hours([n.deploy], played.day.dur)]


def check(task: dict, tier: str, policy: str, fake, ctx: dict, played: Session, expected: list) -> dict:
    watches = played.watches
    m = ctx["metadata"]
    v = m["verifications"]["gridsim"]
    day = v["results"][0]["episode"]
    response = next(p for p in ctx["prompt_responses"] if p.get("step_id") == "play")
    play = response["structured_output"]
    entry = m["env_trigger_state"][HYBRID_ENV]
    capture = json.loads(trajectory(entry["object_url"]))
    problems = []

    fired, actions = {}, {}
    for e in capture["state"]["events"]:
        if e["kind"] == "fired":
            fired.setdefault(e["trigger_id"], []).append(e["virtual_time"])
        elif e["kind"] == "action_ok":
            actions.setdefault(e["trigger_id"], []).append(e["detail"]["args"])
    states = {t["id"]: t for t in entry["triggers"]} if isinstance(entry["triggers"], list) else entry["triggers"]
    for w in watches[1:]:
        tid = f"watch-{w.index}"
        t = states[tid]
        if (t["status"], t["fire_count"], fired.get(tid)) != ("fired", 1, [w.time_utc]):
            problems.append(f"{tid}: {t}, fired at {fired.get(tid)}, not once at {w.time_utc}")
        sent = [(a["event_id"], sorted(a), sorted(a.get("deploy") or {})) for a in actions.get(tid, [])]
        if sent != [(n.event_id, sorted(n.args()), sorted(n.deploy or {})) for n in w.notices]:
            problems.append(f"{tid} delivered {sent}, not {[n.args() for n in w.notices]}")
    delivered = {e["event_id"]: e for e in day["notices"]}
    for w in watches:
        for n in w.notices:
            e = delivered.get(n.event_id)
            if not e or (e["via"], e["matches"], e["first"]) != ("trigger" if w.index else "load", True, True):
                problems.append(f"{n.event_id}: the env logged {e}, not the scheduled notice and payload")

    offered = sorted({tuple(t["name"] for t in body["tools"]) for _, _, body in fake.requests})
    if any(NOTICE_TOOL in names for names in offered):
        problems.append(f"the agent was offered {NOTICE_TOOL}: {offered}")

    record = json.loads(trajectory(response["agent_trajectory_object_url"]))
    try:
        episode = episode_of(task, tier, record, play["model"], ctx["instance_id"])
        if episode["schema"] != EPISODE_SCHEMA or not episode["audit"]["ok"] or episode["reward"] != v["score"]:
            problems.append(f"the episode's schema {episode['schema']}, audit {episode['audit']}, reward "
                            f"{episode['reward']}")
    except ReplayError as e:
        episode = None
        problems.append(f"the record doesn't replay: {e}")
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
            bulletins.append({"watch": watch, "tool": name, "event_ids": [x["event_id"] for x in result["messages"]],
                              "deploys": [x["event_id"] for x in result["messages"] if "deploy" in x]})
        if name == "advance" and "watch" in result:
            watch = result["watch"]
    want = [{"watch": w.index, "tool": "get_situation", "event_ids": [n.event_id for n in w.notices],
             "deploys": [n.event_id for n in w.notices if n.deploy]} for w in watches[1:] if w.notices]
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
    energy, off = deployments(played)
    problems += off

    if day != json.loads(json.dumps(played.data())):
        problems.append("data/get differs from the day played in process")
    want_grade, ref = played.grade(), stored(task, tier, policy)
    g = day["grade"]
    if (v["score"], g["reward"], play["reward"]) != (want_grade["reward"],) * 3:
        problems.append(f"scored {v['score']} (grade {g['reward']}, agent {play['reward']}), {want_grade['reward']} "
                        "in process")
    if want_grade["reward"] != ref["reward"] or abs(want_grade["profit_usd"] - ref["profit"]) > 1e-6:
        problems.append(f"{policy} scored {want_grade['reward']} (profit {want_grade['profit_usd']}); the row stores "
                        f"{ref['reward']} (profit {ref['profit']})")
    if not day["audit"]["ok"] or day["end_reason"] != "done" or play["end_reason"] != "done":
        problems.append(f"audit {day['audit']}, env {day['end_reason']}, agent {play['end_reason']}")
    if len(fake.requests) != play["turns"] or play["turns"] != len(watches):
        problems.append(f"{len(fake.requests)} requests for {play['turns']} turns over {len(watches)} watches")
    return {"problems": problems, "task_id": task["task_id"], "tier": tier, "policy": policy, "score": v["score"],
            "stored": ref, "profit": want_grade["profit_usd"], "watches": [w.time for w in watches], "fired": fired,
            "deploy_payloads": {n.event_id: n.deploy for w in watches for n in w.notices if n.deploy},
            "deploy_energy": energy, "deploy_exercised": bool(energy), "tools": offered, "bulletins": bulletins,
            "get_time": reads, "clock": clock,
            "turns": play["turns"], "tool_calls": play["tool_calls"], "calls_used": day["calls_used"],
            "planning_calls": day["planning_calls"], "commits": g["commits"], "as_share": g["as_share"],
            "notices": [(n["event_id"], n["watch"], n["via"], n["call"]) for n in day["notices"]],
            "data_get_sha256": hashlib.sha256(json.dumps(day, sort_keys=True).encode()).hexdigest(),
            "episode": episode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--task", help="the day to play; default: the gridsim-hybrid bundle's day")
    parser.add_argument("--pack", choices=HYBRID_PACK_NAMES, default="fixtures-hybrid", help="the pack holding it")
    parser.add_argument("--tier", choices=["energy", "reserves"], default="reserves")
    parser.add_argument("--policy", choices=list(POLICIES), default="anchor")
    parser.add_argument("--model", default=MODEL, help="the model id the run passes (the fake answers any)")
    parser.add_argument("--out", type=Path, help="write the day's data/get here")
    parser.add_argument("--episode", type=Path, help="write the run's Episode JSON v3 here")
    args = parser.parse_args()
    default = bundle_day()
    task_id = args.task or default
    task = TaskIndex(pack_dirs(HYBRID_PACK_NAMES)).get(task_id)
    if task is None:
        sys.exit(f"no hybrid task {task_id!r}")
    turns = scripted(task, args.tier, POLICIES[args.policy])
    played, outs = in_process(task, args.tier, turns)
    expected = [(name, out) for (name, _), out in zip((c for calls in turns for c in calls), outs, strict=True)]
    with tempfile.TemporaryDirectory() as tmp:
        bundle, name = HYBRID_ENV, "day"
        if task_id != default or args.tier != "reserves":
            hybrid_tasks.generate(args.pack, Path(tmp), tier=args.tier, task_ids=[task_id])
            bundle, name = tmp, task_id
        with PausingFake(fake_turns(with_clock(turns)), host="0.0.0.0") as fake:
            port = fake.url.rpartition(":")[2]
            run = subprocess.run([sys.executable, "-m", "agent_env.cli", "run", bundle, "--task", name,
                                  "--model", args.model], capture_output=True, text=True,
                                 env={**os.environ, "LITELLM_BASE_URL": f"http://host.docker.internal:{port}",
                                      "LITELLM_API_KEY": "sk-fake-hybrid"})
    print(run.stdout + run.stderr)
    instance = re.findall(r"instance (\S+)", run.stdout)
    if not instance:
        sys.exit("the run stored no instance")
    ctx = context(instance[-1])
    report = check(task, args.tier, args.policy, fake, ctx, played, expected)
    if args.out:
        args.out.write_text(json.dumps(ctx["metadata"]["verifications"]["gridsim"]["results"][0]["episode"],
                                       indent=2, sort_keys=True) + "\n")
    episode = report.pop("episode")
    if args.episode and episode:
        args.episode.write_text(json.dumps(episode, indent=1) + "\n")
    report["episode_steps"] = len(episode["steps"]) if episode else None
    print(json.dumps({"instance": instance[-1], **report}, indent=1, default=str))
    if report["problems"]:
        sys.exit(f"{len(report['problems'])} problems")


if __name__ == "__main__":
    main()
