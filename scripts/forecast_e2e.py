"""Play a forecast window through `agent-env run` with no model spend: the task deploys gridsim-forecast on the gateway
and gridsim-llm on local Docker, and tests/plugin/fake_litellm.py, on this machine, answers the agent with a scripted
policy's turns, one turn per watch: gridsim_core.forecast's rolling MILP anchor (the default; on persistence at the
blind tier) or the naive bidder, its calls worked out in process watch by watch. It fails unless each watch's trigger
fired once, at the watch's time, delivering the watch's notices in order, each deployment's with its payload, which the
env logged as the scheduled one; each deployment dispatched frac x award in the hours of its real window; the agent was
never offered grid_notice (nor, blind, the forecast tools); every tool output the agent got is the one the same calls
get from gridsim_core's forecast Session in process, so each watch's bulletins came with the first tool result after
its advance and no other; get_time read the watch's time and held still between watches while real time passed;
data/get holds the window as played in process; the window scored the policy's stored reward and profit exactly (1.0
and P_anchor to the cent for the anchor); and the agent's record replays byte for byte into Episode JSON v4 (the
`episodes` path), its audit passing with the agent's get_time reads.

With --lookahead it plays the bundle's wiring-lookahead task instead: the agent asks for a price forecast issued at
the next watch, which must be refused with nothing served, then only advances (the harness holds back the first
advance at each DAM gate once); the window scores 0 with every gate missed and the audit passing.

Run it from the checkout after `agent-env gridsim setup --agent`, with the dev extra installed:

    python scripts/forecast_e2e.py [--tier front|front-lite|blind|freeze-6h] [--task ID] [--pack PACK]
        [--policy anchor|naive] [--lookahead] [--model ID] [--out window.json] [--episode episode.json]

The default plays the gridsim-forecast bundle's task for the tier; another window is written as a one-task bundle in
a temporary folder.
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
sys.path[:0] = [str(ROOT / "tests" / d) for d in ("forecast", "plugin")] + [str(ROOT / "scripts")]

import gridsim_llm  # noqa: E402
from forecast_days import anchor, scripted  # noqa: E402
from live_e2e import CLOCK, MODEL, PausingFake, fake_turns  # noqa: E402

from agentenv_gridsim import forecast_tasks  # noqa: E402
from agentenv_gridsim.episodes import ReplayError, live_replay  # noqa: E402
from agentenv_gridsim.forecast import FORECAST_PACK_NAMES  # noqa: E402
from agentenv_gridsim.server import TaskIndex, pack_dirs  # noqa: E402
from agentenv_gridsim.sweep import context, trajectory  # noqa: E402
from gridsim_core.forecast import (  # noqa: E402
    EPISODE_SCHEMA,
    EVENT_PRODUCTS,
    FORECAST_ENV,
    FORECAST_TOOLS,
    NOTICE_TOOL,
    TIERS,
    TOL,
    Session,
    deploy_hours,
    gate_minute,
    naive_policy,
)

HELD = json.dumps({"error": gridsim_llm.GATE_OPEN})


def bundle_window(name: str) -> str:
    steps = json.loads(forecast_tasks.BUNDLE.joinpath(f"tasks/{name}.json").read_text())
    return next(s for s in steps if s["id"] == "load-task")["directives"][0]["args"]["task_id"]


def stored(task: dict, tier: str, policy: str) -> dict:
    """What the task row stores for the policy at the tier: its profit and reward."""
    refs = task["refs"][tier]
    return {"profit": refs["p_anchor"], "reward": 1.0} if policy == "anchor" else refs["baselines"][policy]


def with_clock(turns: list[list[tuple[str, dict]]]) -> list[list[tuple[str, dict]]]:
    """Each turn reads the clock first and, once a later watch is open, again after its get_situation."""
    return [[(CLOCK, {}), *calls] + ([(CLOCK, {})] if k < len(turns) - 1 else []) for k, calls in enumerate(turns)]


def lookahead_turns(task: dict, tier: str) -> tuple[list[list[tuple[str, dict]]], set[tuple[int, int]]]:
    """The wiring-lookahead task as its prompt asks: a price forecast issued at the next watch, then advances only, the
    first at each DAM gate held back by the harness; the turns and the (turn, call) the harness answers itself."""
    s = Session(task, tier)
    gates = {gate_minute(k) for k in range(s.n)}
    turns, held = [[(CLOCK, {}), ("get_forecast", {"kind": "price", "issued_at": s.watches[1].time})]], set()
    for w in s.watches:
        if w.minute in gates:
            turns[-1].append(("advance", {}))
            held.add((len(turns) - 1, len(turns[-1]) - 1))
            turns.append([])
        last = w.index == len(s.watches) - 1
        turns[-1] += [("advance", {})] + ([] if last else [("get_situation", {}), (CLOCK, {})])
        if not last:
            turns.append([(CLOCK, {})])
    return turns, held


def in_process(task: dict, tier: str, turns: list, held: set) -> tuple[Session, list[tuple[str, str]]]:
    """The same calls on a Session, the triggers' grid_notice calls after each advance that opens a watch, the held
    advances answered by the harness: the outputs the agent should get."""
    s, outs = Session(task, tier), []
    for t, calls in enumerate(turns):
        for i, (name, args) in enumerate(calls):
            if name == CLOCK:
                continue
            if (t, i) in held:
                outs.append((name, HELD))
                continue
            out = s.call(name, args)
            outs.append((name, out))
            if name == "advance" and "watch" in json.loads(out):
                s.deliver_watch_notices()
    return s, outs


def episode_of(task: dict, tier: str, record: dict, model: str, instance: str) -> dict:
    """The run's Episode JSON v4 as `agent-env gridsim episodes` writes it: the record replayed through a forecast
    Session, byte for byte, and audited with the agent's get_time reads."""
    s, reads = live_replay(task, tier, record, Session)
    return s.episode(bundle="live", path="A", model=model, trained="base", usage=record["usage"],
                     episode_id=instance.rsplit("/", 1)[-1]) | {"audit": s.audit(reads)}


def deployments(played: Session) -> tuple[list[dict], list[str]]:
    """Each hour a deployment dispatched awards in, from its payload's real window: the energy the plant delivered for
    it beyond regulation, against frac x award; problems where they differ, unless SoC limited the hour."""
    payloads = [n for w in played.watches for n in w.notices if n.deploy]
    frac = deploy_hours([n.deploy for n in payloads], played.win.dur, played.H)
    rows, problems = [], []
    for r in played.rows:
        h, a = r["h"], r["a"]
        want = sum(frac[h][k] * a[k] for k in EVENT_PRODUCTS)
        got = r["up_mwh"] - played.win.reg_up[h] * a["regup"]
        if want <= TOL and abs(got) <= TOL:
            continue
        limited = r["up_mwh"] + TOL < played.win.reg_up[h] * a["regup"] + want
        rows.append({"h": h, "want_mwh": round(want, 6), "event_mwh": round(got, 6), "soc_limited": limited})
        if abs(got - want) > TOL and not limited:
            problems.append(f"hour {h}: deployments delivered {got:.6f} MWh, their payloads dispatch {want:.6f}")
    return rows, problems


def check(task: dict, tier: str, policy: str, fake, ctx: dict, played: Session, expected: list, turns: list,
          lookahead: bool) -> dict:
    watches = played.watches
    m = ctx["metadata"]
    v = m["verifications"]["gridsim"]
    w = v["results"][0]["episode"]
    response = next(p for p in ctx["prompt_responses"] if p.get("step_id") == "play")
    play = response["structured_output"]
    entry = m["env_trigger_state"][FORECAST_ENV]
    capture = json.loads(trajectory(entry["object_url"]))
    problems = []

    fired, actions = {}, {}
    for e in capture["state"]["events"]:
        if e["kind"] == "fired":
            fired.setdefault(e["trigger_id"], []).append(e["virtual_time"])
        elif e["kind"] == "action_ok":
            actions.setdefault(e["trigger_id"], []).append(e["detail"]["args"])
    states = {t["id"]: t for t in entry["triggers"]} if isinstance(entry["triggers"], list) else entry["triggers"]
    for wa in watches[1:]:
        tid = f"watch-{wa.index}"
        t = states[tid]
        if (t["status"], t["fire_count"], fired.get(tid)) != ("fired", 1, [wa.time_utc]):
            problems.append(f"{tid}: {t}, fired at {fired.get(tid)}, not once at {wa.time_utc}")
        sent = [(a["event_id"], sorted(a), sorted(a.get("deploy") or {})) for a in actions.get(tid, [])]
        if sent != [(n.event_id, sorted(n.args()), sorted(n.deploy or {})) for n in wa.notices]:
            problems.append(f"{tid} delivered {sent}, not {[n.args() for n in wa.notices]}")
    delivered = {e["event_id"]: e for e in w["notices"]}
    for wa in watches:
        for n in wa.notices:
            e = delivered.get(n.event_id)
            if not e or (e["via"], e["matches"], e["first"]) != ("trigger" if wa.index else "load", True, True):
                problems.append(f"{n.event_id}: the env logged {e}, not the scheduled notice and payload")

    offered = sorted({tuple(t["name"] for t in body["tools"]) for _, _, body in fake.requests})
    hidden = [NOTICE_TOOL, *(FORECAST_TOOLS if tier == "blind" else ())]
    if any(name in names for names in offered for name in hidden):
        problems.append(f"the agent was offered one of {hidden}: {offered}")

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
    want = [{"watch": wa.index, "tool": "get_situation", "event_ids": [n.event_id for n in wa.notices],
             "deploys": [n.event_id for n in wa.notices if n.deploy]} for wa in watches[1:] if wa.notices]
    if bulletins != want:
        problems.append(f"bulletins {bulletins}, not {want}")
    for k, read in reads.items():
        if set(read) != {watches[k].time_utc}:
            problems.append(f"get_time in watch {k} read {read}, not {watches[k].time_utc}")
    if sorted(reads) != list(range(len(watches))):
        problems.append(f"get_time was read in watches {sorted(reads)}")
    clock = capture["clock"]
    if clock.get("virtual_seconds_per_real_second") != 0 or clock.get("t0") != watches[-1].time_utc:
        problems.append(f"the clock at the end: {clock}")
    energy, off = deployments(played)
    problems += off

    if w != json.loads(json.dumps(played.data())):
        problems.append("data/get differs from the window played in process")
    want_grade = played.grade()
    g = w["grade"]
    if (v["score"], g["reward"], play["reward"]) != (want_grade["reward"],) * 3:
        problems.append(f"scored {v['score']} (grade {g['reward']}, agent {play['reward']}), {want_grade['reward']} "
                        "in process")
    if lookahead:
        refusal = json.loads(expected[0][1])
        if not refusal.get("error", "").startswith("issued_at is after now") or w["forecast_log"]:
            problems.append(f"the lookahead got {refusal}; served {w['forecast_log']}")
        if (want_grade["reward"], g["dam_missed"], play["gate_nudges"]) != (0.0, played.n, played.n):
            problems.append(f"lookahead scored {want_grade['reward']}, {g['dam_missed']} gates missed, "
                            f"{play['gate_nudges']} gate nudges")
        ref = None
    else:
        ref = stored(task, tier, policy)
        if want_grade["reward"] != ref["reward"] or round(want_grade["profit_usd"], 2) != round(ref["profit"], 2):
            problems.append(f"{policy} scored {want_grade['reward']} (profit {want_grade['profit_usd']}); the row "
                            f"stores {ref['reward']} (profit {ref['profit']})")
        if play["gate_nudges"]:
            problems.append(f"{policy} was held back at {play['gate_nudges']} gates")
    if not w["audit"]["ok"] or w["end_reason"] != "done" or play["end_reason"] != "done":
        problems.append(f"audit {w['audit']}, env {w['end_reason']}, agent {play['end_reason']}")
    if len(fake.requests) != play["turns"] or play["turns"] != len(turns):
        problems.append(f"{len(fake.requests)} requests for {play['turns']} turns, {len(turns)} scripted")
    return {"problems": problems, "task_id": task["task_id"], "tier": tier,
            "policy": "lookahead" if lookahead else policy, "score": v["score"], "stored": ref,
            "profit": want_grade["profit_usd"], "watches": [wa.time for wa in watches], "fired": fired,
            "deploy_payloads": {n.event_id: n.deploy for wa in watches for n in wa.notices if n.deploy},
            "deploy_energy": energy, "deploy_exercised": bool(energy), "tools": offered, "bulletins": bulletins,
            "get_time": reads, "clock": clock, "turns": play["turns"], "tool_calls": play["tool_calls"],
            "gate_nudges": play["gate_nudges"], "calls_used": w["calls_used"], "planning_calls": w["planning_calls"],
            "forecast_calls": w["forecast_calls"], "commits": g["commits"], "dam_missed": g["dam_missed"],
            "dam": [(d["day"], len(d["accepted"]), d["missed"]) for d in w["dam"]],
            "notices": [(n["event_id"], n["watch"], n["via"], n["call"]) for n in w["notices"]],
            "data_get_sha256": hashlib.sha256(json.dumps(w, sort_keys=True).encode()).hexdigest(),
            "episode": episode}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--tier", choices=TIERS, default="front")
    parser.add_argument("--task", help="the window to play; default: the gridsim-forecast bundle's window")
    parser.add_argument("--pack", choices=FORECAST_PACK_NAMES, default="fixtures-forecast", help="the pack holding it")
    parser.add_argument("--policy", choices=["anchor", "naive"], default="anchor")
    parser.add_argument("--lookahead", action="store_true", help="play the bundle's wiring-lookahead task")
    parser.add_argument("--model", default=MODEL, help="the model id the run passes (the fake answers any)")
    parser.add_argument("--out", type=Path, help="write the window's data/get here")
    parser.add_argument("--episode", type=Path, help="write the run's Episode JSON v4 here")
    args = parser.parse_args()
    if args.lookahead and (args.task or args.tier != "front"):
        sys.exit("--lookahead plays the bundle's wiring-lookahead task, at front")
    name = "wiring-lookahead" if args.lookahead else args.tier
    default = bundle_window(name)
    task_id = args.task or default
    task = TaskIndex(pack_dirs(FORECAST_PACK_NAMES)).get(task_id)
    if task is None:
        sys.exit(f"no forecast window {task_id!r}")
    if args.lookahead:
        turns, held = lookahead_turns(task, args.tier)
    else:
        policy = anchor(args.tier) if args.policy == "anchor" else naive_policy
        turns, held = with_clock(scripted(task, args.tier, policy)), set()
    played, expected = in_process(task, args.tier, turns, held)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = FORECAST_ENV
        if task_id != default:
            forecast_tasks.generate(args.pack, Path(tmp), tier=args.tier, task_ids=[task_id])
            bundle, name = tmp, task_id
        with PausingFake(fake_turns(turns), host="0.0.0.0") as fake:
            port = fake.url.rpartition(":")[2]
            run = subprocess.run([sys.executable, "-m", "agent_env.cli", "run", bundle, "--task", name,
                                  "--model", args.model], capture_output=True, text=True,
                                 env={**os.environ, "LITELLM_BASE_URL": f"http://host.docker.internal:{port}",
                                      "LITELLM_API_KEY": "sk-fake-forecast"})
    print(run.stdout + run.stderr)
    instance = re.findall(r"instance (\S+)", run.stdout)
    if not instance:
        sys.exit("the run stored no instance")
    ctx = context(instance[-1])
    report = check(task, args.tier, args.policy, fake, ctx, played, expected, turns, args.lookahead)
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
