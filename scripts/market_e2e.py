"""Play a market floor through `agent-env run` with no model spend: the task deploys gridsim-market on the gateway and
gridsim-llm on local Docker, and tests/plugin/fake_litellm.py, on this machine, answers the agent with a scripted
policy's turns, one turn per watch: gridsim_core.market's disclosure best-responder (the default), seat A's real
offers of the day (replay) or idle, its calls worked out in process watch by watch. It fails unless each watch's
trigger fired once, at the watch's time, delivering the watch's notices in order; the agent was never offered
grid_notice (nor, in floor-sprint, a floor-day tool); every tool output the agent got is the one the same calls get
from gridsim_core's market Session in process, so each watch's bulletins came with the first tool result after its
advance and no other; get_time read the watch's time and held still between watches while real time passed; data/get
holds the floor as played in process; the floor scored the policy's stored reward and profit to the cent (1.0 and
P_anchor for the anchor) with a clean audit; the day's replay profile (every seat on its real offers) clears at the
real hub price within the day's stored simplification error; and the agent's record replays byte for byte into
Episode JSON v5 (the `episodes` path), its audit passing with the agent's get_time reads; and on a floor-sprint, path
B (gridsim_core.market.grade_offer of the submitted offer) grades it as path A did, to 1e-6.

With --wiring it plays the gridsim-market bundle's wiring tasks instead, which need no agent: each must score what
the same harness calls score in process, with the audit passing, a late offer refused and the 09:00 offer standing,
and get_disclosure refusing days newer than 60 days and older than the window.

Run it from the checkout after `agent-env gridsim setup --agent`, with the dev extra installed:

    python scripts/market_e2e.py [--task ID] [--tier floor-sprint|floor-day] [--policy anchor|replay|idle]
        [--compliant] [--model ID] [--out floor.json] [--episode episode.json]
    python scripts/market_e2e.py --wiring
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests" / "marketenv"), str(ROOT / "scripts")]

from live_e2e import CLOCK, MODEL, PausingFake, fake_turns  # noqa: E402
from market_floors import BUNDLE, DAY, SPRINT, WIRING, in_process, policies, scripted, stored  # noqa: E402

from agentenv_gridsim import market_tasks  # noqa: E402
from agentenv_gridsim.episodes import ReplayError, market_replay  # noqa: E402
from agentenv_gridsim.market import CALLS_URI, MARKET_PACK_NAMES  # noqa: E402
from agentenv_gridsim.server import TaskIndex, pack_dirs  # noqa: E402
from agentenv_gridsim.sweep import context, trajectory  # noqa: E402
from gridsim_core.live import NOTICE_TOOL  # noqa: E402
from gridsim_core.market import EPISODE_SCHEMA, MARKET_ENV, SPRINT_TOOLS, TOOLS, Session, grade_offer  # noqa: E402

DAY_ONLY = set(TOOLS) - set(SPRINT_TOOLS)


def with_clock(turns: list[list[tuple[str, dict]]]) -> list[list[tuple[str, dict]]]:
    """Each turn reads the clock first and, once a later watch is open, again after its get_situation."""
    return [[(CLOCK, {}), *calls] + ([(CLOCK, {})] if k < len(turns) - 1 else []) for k, calls in enumerate(turns)]


def agent_env_run(bundle: str, task: str, env: dict | None = None, model: str | None = None) -> tuple[str, dict]:
    """`agent-env run` of one task: its output and the instance's context."""
    run = subprocess.run([sys.executable, "-m", "agent_env.cli", "run", bundle, "--task", task,
                          *(["--model", model] if model else [])], capture_output=True, text=True,
                         env={**os.environ, **(env or {})})
    out = run.stdout + run.stderr
    print(out)
    instance = re.findall(r"instance (\S+)", run.stdout)
    if not instance:
        sys.exit("the run stored no instance")
    return instance[-1], context(instance[-1])


def replay_fidelity(task: dict) -> dict:
    """The replay profile's clear (stored in the row) against the real hub DAM price, hour by hour."""
    s = Session(task, "floor-sprint")
    err = [abs(a - b) for a, b in zip(task["refs"]["replay_lambda_usd"], s.F.hub_real, strict=True)]
    return {"max_abs_usd": round(max(err), 2), "hours_off_by_a_cent": int(sum(e > 0.01 for e in err)),
            "simplify_err_usd": task["fidelity"]["simplify_err_usd"]}


def check(task: dict, tier: str, policy: str, compliant: bool, fake, ctx: dict, played: Session,
          expected: list) -> dict:
    watches = played.watches
    m = ctx["metadata"]
    v = m["verifications"]["gridsim"]
    floor = v["results"][0]["episode"]
    response = next(p for p in ctx["prompt_responses"] if p.get("step_id") == "play")
    play = response["structured_output"]
    problems = []

    fired, actions = {}, {}
    if tier == "floor-day":
        entry = m["env_trigger_state"][MARKET_ENV]
        capture = json.loads(trajectory(entry["object_url"]))
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
        clock = capture["clock"]
        if clock.get("virtual_seconds_per_real_second") != 0 or clock.get("t0") != watches[-1].time_utc:
            problems.append(f"the clock at the end: {clock}")

    offered = sorted({tuple(t["name"] for t in body["tools"]) for _, _, body in fake.requests})
    if any(NOTICE_TOOL in names for names in offered):
        problems.append(f"the agent was offered {NOTICE_TOOL}: {offered}")
    if tier == "floor-sprint" and any(DAY_ONLY & set(names) for names in offered):
        problems.append(f"the sprint agent was offered floor-day tools: {offered}")

    record = json.loads(trajectory(response["agent_trajectory_object_url"]))
    try:
        s, reads = market_replay(task, tier, record, compliant)
        episode = s.episode(bundle="compliant" if compliant else "live", path="A", model=play["model"],
                            trained="base", usage=record["usage"], episode_id=ctx["instance_id"].rsplit("/", 1)[-1])
        episode["audit"] = s.audit(reads)
        score = episode["compliant_reward" if compliant else "reward"]
        if episode["schema"] != EPISODE_SCHEMA or not episode["audit"]["ok"] or score != v["score"]:
            problems.append(f"the episode's schema {episode['schema']}, audit {episode['audit']}, score {score}")
        if episode["clear"]["lambda_replay"] != task["refs"]["replay_lambda_usd"]:
            problems.append("the episode's replay clear is not the row's")
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

    if floor != json.loads(json.dumps(played.data() | {"compliant": compliant})):
        problems.append("data/get differs from the floor played in process")
    g = played.grade()
    want_score = g["compliant_reward"] if compliant else g["reward"]
    if (v["score"], floor["grade"]["compliant_reward" if compliant else "reward"]) != (want_score, want_score):
        problems.append(f"scored {v['score']}, {want_score} in process")
    ref = stored(task, tier, policy)
    if ref and (g["reward"] != ref["reward"] or abs(g["profit_usd"] - ref["profit"]) >= 0.005):
        problems.append(f"{policy} scored {g['reward']} (profit {g['profit_usd']}); the row stores {ref['reward']} "
                        f"(profit {ref['profit']})")
    parity = None
    if tier == "floor-sprint":
        b = grade_offer(task, floor["offer"], rows=True)
        parity = {k: round(abs(b[k] - floor["grade"][k]), 9) for k in ("reward", "compliant_reward", "profit_usd")}
        if max(parity.values()) > 1e-6:
            problems.append(f"path B grades the offer {b['reward']} (compliant {b['compliant_reward']}), path A "
                            f"{floor['grade']['reward']} ({floor['grade']['compliant_reward']})")
    end = "done" if tier == "floor-day" else "submitted"
    if not floor["audit"]["ok"] or floor["end_reason"] != end or play["end_reason"] != end:
        problems.append(f"audit {floor['audit']}, env {floor['end_reason']}, agent {play['end_reason']}")
    if len(fake.requests) != play["turns"] or play["turns"] != len(watches):
        problems.append(f"{len(fake.requests)} requests for {play['turns']} turns over {len(watches)} watches")
    fid = replay_fidelity(task)
    if fid["max_abs_usd"] > fid["simplify_err_usd"] + 0.01:
        problems.append(f"the replay profile misses the real hub price by ${fid['max_abs_usd']}")
    return {"problems": problems, "task_id": task["task_id"], "tier": tier, "policy": policy, "compliant": compliant,
            "score": v["score"], "reward": g["reward"], "compliant_reward": g["compliant_reward"],
            "profit": round(g["profit_usd"], 2), "stored": ref, "watches": [w.time for w in watches], "fired": fired,
            "tools": offered, "bulletins": bulletins, "get_time": reads, "turns": play["turns"],
            "tool_calls": play["tool_calls"], "calls_used": floor["calls_used"], "replay_fidelity": fid,
            "path_b_gap": parity,
            "rows": {r["criterion"]: r.get("value") for r in v["results"][1:]},
            "data_get_sha256": hashlib.sha256(json.dumps(floor, sort_keys=True).encode()).hexdigest(),
            "episode": episode}


def wiring() -> list[str]:
    """The bundle's wiring tasks through `agent-env run`, each against the same harness calls in process."""
    problems = []
    for name in ("wiring-noplay", *WIRING):
        spec = BUNDLE[name]
        task, tier, calls = spec["task"], spec["tier"], spec.get("calls") or []
        s = Session(task, tier)
        outs = [s.call(t, a) for t, a in calls]
        s.end_floor()
        _, ctx = agent_env_run(MARKET_ENV, name)
        v = ctx["metadata"]["verifications"]["gridsim"]
        floor = v["results"][0]["episode"]
        applied = {c["uri"]: c["result"] for c in ctx["metadata"].get("server_config_changes") or []}
        got = (applied.get(CALLS_URI) or {}).get("outputs", [])
        if got != outs:
            problems.append(f"{name}: the harness calls answered {got}, {outs} in process")
        if (v["score"], floor["audit"]["ok"]) != (s.grade()["reward"], True):
            problems.append(f"{name}: scored {v['score']} with audit {floor['audit']}, {s.grade()['reward']} in "
                            "process")
        print(json.dumps({"task": name, "score": v["score"], "outputs": [json.loads(o) for o in got]})[:1500])
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--task", help="the floor to play; default: the gridsim-market bundle's sprint or day floor")
    parser.add_argument("--tier", choices=["floor-sprint", "floor-day"], default="floor-day")
    parser.add_argument("--policy", choices=["anchor", "replay", "idle"], default="anchor")
    parser.add_argument("--compliant", action="store_true", help="score it 0.5 R + 0.5 welfare ratio")
    parser.add_argument("--model", default=MODEL, help="the model id the run passes (the fake answers any)")
    parser.add_argument("--wiring", action="store_true", help="play the bundle's wiring tasks instead")
    parser.add_argument("--out", type=Path, help="write the floor's data/get here")
    parser.add_argument("--episode", type=Path, help="write the run's Episode JSON v5 here")
    args = parser.parse_args()
    if args.wiring:
        problems = wiring()
        print(json.dumps({"wiring": list(BUNDLE)[4:], "problems": problems}, indent=1))
        if problems:
            sys.exit(f"{len(problems)} problems")
        return
    task_id = args.task or (SPRINT if args.tier == "floor-sprint" else DAY)["task_id"]
    task = TaskIndex(pack_dirs(MARKET_PACK_NAMES)).get(task_id)
    if task is None:
        sys.exit(f"no market floor {task_id!r}")
    turns = scripted(task, args.tier, policies(task)[args.policy])
    played, outs = in_process(task, args.tier, turns)
    expected = [(name, out) for (name, _), out in zip((c for calls in turns for c in calls), outs, strict=True)]
    pack = next(p for p in MARKET_PACK_NAMES if TaskIndex(pack_dirs((p,))).get(task_id))
    with tempfile.TemporaryDirectory() as tmp:
        market_tasks.generate(pack, Path(tmp), tier=args.tier, compliant=args.compliant, task_ids=[task_id])
        with PausingFake(fake_turns(with_clock(turns)), host="0.0.0.0") as fake:
            port = fake.url.rpartition(":")[2]
            instance, ctx = agent_env_run(tmp, task_id, {"LITELLM_BASE_URL": f"http://host.docker.internal:{port}",
                                                          "LITELLM_API_KEY": "sk-fake-market"}, args.model)
    report = check(task, args.tier, args.policy, args.compliant, fake, ctx, played, expected)
    if args.out:
        args.out.write_text(json.dumps(ctx["metadata"]["verifications"]["gridsim"]["results"][0]["episode"],
                                       indent=2, sort_keys=True) + "\n")
    episode = report.pop("episode")
    if args.episode and episode:
        args.episode.write_text(json.dumps(episode, indent=1) + "\n")
    report["episode_steps"] = len(episode["steps"]) if episode else None
    print(json.dumps({"instance": instance, **report}, indent=1, default=str))
    if report["problems"]:
        sys.exit(f"{len(report['problems'])} problems")


if __name__ == "__main__":
    main()
