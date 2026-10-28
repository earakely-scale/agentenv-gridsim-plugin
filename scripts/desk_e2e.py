"""Play one GridSim desk episode end to end on AgentEnv (path A): the task deploys the layer's gridsim-desk env on the
gateway (local Docker), arms its clock frozen at D-1 06:00 CPT and prompts the agent from the start wake; the
gridsim-desk-hook post-turn hook wakes it between turns; gridsim-desk-verifier grades it through the hidden grade tool.
The agent is played through the framework's Episode API (an in-process ProxyAgent), so its tool calls reach the env
through the gateway as an agent's do, by:

- a core policy (anchor, scripted or idle), $0: gridsim_core.desk.policies, its calls sent through the turn's tools;
- llm: a model through scripts/desk_run.py's ModelAgent (path B''s model loop: preset, route, prompts, transcript and
  spend cap), its credentials read in process as desk_run.py reads them (--gateway-env, --ssm-param).

The first turn also sets a reminder (--reminder), which must wake the agent with the reason reminder. A shadow
Session (path B') plays the same calls in process in lockstep. It fails unless every tool output and every
wake message matches the shadow's byte for byte, the agent is offered exactly the desk's tools (no hidden tool, no
get_time), each wake came at the shadow's time with its reasons, the hook ended the conversation with episode_over
after the market ran to the end, and the verifier's reward equals the shadow's Session grade.

Run it from the checkout after `agent-env gridsim setup`, with the dev extra installed:

    python scripts/desk_e2e.py --pack PACK --task ID [--policy anchor|scripted|idle] [--out report.json]
    python scripts/desk_e2e.py --pack PACK --task ID --policy llm --preset luna --gateway-env FILE --ssm-param NAME
        [--max-usd 1]
"""

import argparse
import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import desk_run  # noqa: E402
from agent_env.bundle.run import prepare_bundle
from agent_env.store.routing import namespace_routing
from agent_env.task import EpisodeSpec

from agentenv_gridsim import desk_tasks
from agentenv_gridsim.sweep import context
from gridsim_core.desk import Session, grade, load_series, load_task, policies, system_prompt, text, tool_specs
from gridsim_core.desk.clock import parse_time

TURN_SECONDS = 1800


class Shadow:
    """The policy's view of the desk: the shadow Session's state, every call sent through the turn's tools and played
    on the shadow too, the two outputs compared."""

    def __init__(self, session: Session, loop, report: dict):
        self.__dict__.update(_s=session, _loop=loop, _report=report, _tools=None)

    def __getattr__(self, name):
        return getattr(self._s, name)

    def call(self, name, args=None, role="default"):
        got = asyncio.run_coroutine_threadsafe(self.call_async(name, args or {}), self._loop).result()
        return json.loads(got)

    async def call_async(self, name, args):
        result = await self._tools.call(name, args)
        got = "".join(c["text"] if isinstance(c, dict) else c.text for c in result.content)
        want = text(self._s.call(name, args))
        self._report["calls"] += 1
        if got != want:
            self._report["problems"].append(f"{name}({json.dumps(args)[:200]}): gateway {got[:300]!r} != "
                                            f"session {want[:300]!r}")
        return got


async def play_policy(policy, shadow: Shadow, wake: dict) -> str:
    await asyncio.to_thread(policy, shadow, wake)
    return f"done at {wake['now']}"


class Model:
    """The B' runner's model agent (scripts/desk_run.py ModelAgent: the same routes, prompts and transcript), its
    tool calls sent through the turn's tools instead of to a Session; past its spend cap it ends every turn at once."""

    def __init__(self, a, system: str, specs: list[dict]):
        self.agent = desk_run.ModelAgent(a, desk_run.MODELS[a.preset], 0.0, system, specs)
        self.capped: str | None = None

    async def turn(self, shadow: Shadow, prompt: str, calls_per_turn: int) -> str | None:
        if self.capped:
            return None
        self.agent.user(prompt)
        reply = None
        try:
            for _ in range(calls_per_turn + 3):
                reply, calls = await asyncio.to_thread(self.agent.step, lambda row: None)
                if not calls:
                    break
                for call_id, name, raw in calls:
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        out = text({"error": "args: arguments are not valid JSON"})
                    else:
                        out = await shadow.call_async(name, args)
                    self.agent.result(call_id, out)
        except desk_run.SpendCap as e:
            self.capped = str(e)
        return reply


async def run(bundle: Path, name: str, task: dict, series: dict, policy: str, model, reminder: str | None) -> dict:
    report = {"problems": [], "calls": 0, "wakes": []}
    shadow_session = Session(task, series)
    shadow = Shadow(shadow_session, asyncio.get_running_loop(), report)
    want_tools = [s["function"]["name"] for s in tool_specs(shadow_session.layer, shadow_session.rtcb)]
    started = time.monotonic()
    with namespace_routing():
        [(_, agentenv_task)] = prepare_bundle(bundle, tasks=[name], played=True).tasks
        episode = await EpisodeSpec.from_task(agentenv_task, turn_timeout=TURN_SECONDS).start()
        try:
            wake, llm, k = shadow_session.start(), None, 0
            while True:
                turn = await episode.next_turn()
                if wake is None:
                    if turn is not None:
                        report["problems"].append(f"a turn after the episode ended: {turn.prompt[:200]!r}")
                    break
                if turn is None:
                    report["problems"].append(f"the conversation ended before the wake at {wake['now']}")
                    break
                report["wakes"].append({"turn": k, "minute": shadow_session.now, "now": wake["now"],
                                        "reasons": wake["reasons"], "turns_left": wake["budget"]["turns_left"]})
                if turn.prompt != text(wake):
                    report["problems"].append(f"turn {k}: the prompt {turn.prompt[:300]!r} is not the shadow's wake "
                                              f"{text(wake)[:300]!r}")
                async with turn.tools() as tools:
                    offered = [t.name for t in tools.list()]
                    if offered != want_tools:
                        report["problems"].append(f"turn {k}: offered {offered}, not {want_tools}")
                    shadow.__dict__["_tools"] = tools
                    if k == 0 and reminder:
                        await shadow.call_async("set_reminder", {"at": reminder, "note": "desk_e2e reminder"})
                    if model is not None:
                        if turn.system_prompt != system_prompt(shadow_session):
                            report["problems"].append(f"turn {k}: the system prompt is not core's")
                        llm = llm or Model(model, system_prompt(shadow_session),
                                           tool_specs(shadow_session.layer, shadow_session.rtcb))
                        reply = await llm.turn(shadow, turn.prompt, shadow_session.budget["calls_per_turn"])
                    else:
                        reply = await play_policy(policies.POLICIES[policy], shadow, wake)
                await turn.end(reply)
                wake = shadow_session.end_turn(reply)
                k += 1
            scores = await episode.result()
        except BaseException:
            await episode.abandon("desk_e2e failed")
            raise
    ctx = context(episode.id)
    m = ctx["metadata"]
    hooks = [e for entries in (m.get("post_turn_hooks") or {}).values() for e in entries]
    woke = [(e["turn"], e["minute"], e["reasons"]) for e in hooks if "reasons" in e]
    want = [(w["turn"], w["minute"], w["reasons"]) for w in report["wakes"][1:]]
    if woke != want:
        report["problems"].append(f"the hook woke {woke}, the shadow {want}")
    if reminder:
        at = parse_time(reminder, shadow_session.d0)
        if not any(w["minute"] == at and "reminder" in w["reasons"] for w in report["wakes"]):
            report["problems"].append(f"no reminder wake at {reminder} (minute {at}): "
                                      f"{[w for w in report['wakes'] if w['minute'] == at]}")
    ends = [e for e in hooks if "end" in e]
    if len(ends) != 1 or ends[0]["end"] != "episode_over":
        report["problems"].append(f"the hook's ends: {ends}")
    v = m["verifications"]["gridsim-desk"]
    g = grade(shadow_session)
    got = v["results"][0]["metadata"]["grade"]
    if got != json.loads(text(g)) or v["results"][0]["score"] != g["reward"]:
        report["problems"].append(f"the verifier's grade {got} != the shadow's {g}")
    episode_json = v["results"][0]["episode"]
    if episode_json != json.loads(text(shadow_session.episode())):
        report["problems"].append("the env's Episode JSON differs from the shadow's")
    report.update({"instance": episode.id, "scores": scores, "reward": g["reward"], "grade": g,
                   "hook": hooks, "seconds": round(time.monotonic() - started, 1),
                   "usage": llm and {"model": llm.agent.model, **llm.agent.usage, "capped": llm.capped}})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--pack", required=True, help="the desk pack (a name under data/desk/ or a folder)")
    parser.add_argument("--task", required=True, help="the task id")
    parser.add_argument("--policy", choices=[*policies.POLICIES, "llm"], default="anchor")
    parser.add_argument("--preset", default="luna", help="llm: a scripts/desk_run.py model preset")
    parser.add_argument("--gateway-env", help="llm: a file with a LITELLM_BASE_URL= line (as desk_run.py)")
    parser.add_argument("--ssm-param", help="llm: the AWS SSM parameter holding the API key (as desk_run.py)")
    parser.add_argument("--max-usd", type=float, default=1.0, help="llm: the episode's spend cap")
    parser.add_argument("--reminder", default="D0 14:35", help="a reminder the first turn sets ('' for none)")
    parser.add_argument("--image-pack", help="the pack's name inside the env image, when --pack is a folder")
    parser.add_argument("--out", type=Path, help="write the report here")
    args = parser.parse_args()
    model = None
    if args.policy == "llm":
        model = argparse.Namespace(preset=args.preset, base_url=None, gateway_env=args.gateway_env,
                                   ssm_param=args.ssm_param, aws_profile=None, aws_region=None, model=None, price=None,
                                   effort=None, max_usd=args.max_usd, lane_cap_usd=None, max_tokens=None,
                                   timeout=600.0)
    task = load_task(args.pack, args.task)
    series = load_series(args.pack, task)
    with tempfile.TemporaryDirectory() as tmp:
        desk_tasks.generate(args.pack, Path(tmp), task_ids=[args.task], image_pack=args.image_pack)
        report = asyncio.run(run(Path(tmp), args.task, task, series, args.policy, model,
                                 args.reminder or None))
    if args.out:
        args.out.write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(json.dumps({k: report[k] for k in ("instance", "reward", "scores", "calls", "seconds", "usage", "problems")},
                     indent=1, default=str))
    for w in report["wakes"]:
        print(f"  turn {w['turn']:>2}  {w['now']}  {','.join(w['reasons'])}  turns_left {w['turns_left']}")
    if report["problems"]:
        sys.exit(f"{len(report['problems'])} problems")


if __name__ == "__main__":
    main()
