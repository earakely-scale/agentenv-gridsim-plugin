"""Play one GridSim desk episode end to end on AgentEnv (path A): the task deploys the layer's gridsim-desk env on the
gateway (local Docker), arms its clock frozen at D-1 06:00 CPT and prompts the agent from the start wake; the
gridsim-desk-hook post-turn hook wakes it between turns; gridsim-desk-verifier grades it through the hidden grade tool.
The agent is played through the framework's Episode API (an in-process ProxyAgent), so its tool calls reach the env
through the gateway as an agent's do, by:

- a core policy (anchor, scripted or idle), $0: gridsim_core.desk.policies, its calls sent through the turn's tools;
- llm: a model on LiteLLM's OpenAI-compatible endpoint (LITELLM_BASE_URL, LITELLM_API_KEY), its history kept across
  turns, stopped at --max-cost.

The first turn also sets a reminder (--reminder), which must wake the agent with the reason reminder. A shadow
Session (path B') plays the same calls in process in lockstep. It fails unless every tool output and every
wake message matches the shadow's byte for byte, the agent is offered exactly the desk's tools (no hidden tool, no
get_time), each wake came at the shadow's time with its reasons, the hook ended the conversation with episode_over
after the market ran to the end, and the verifier's reward equals the shadow's Session grade.

Run it from the checkout after `agent-env gridsim setup`, with the dev extra installed:

    python scripts/desk_e2e.py --pack PACK --task ID [--policy anchor|scripted|idle|llm] [--model ID]
        [--out report.json]
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from agent_env.bundle.run import prepare_bundle
from agent_env.store.routing import namespace_routing
from agent_env.task import EpisodeSpec

from agentenv_gridsim import desk_tasks
from agentenv_gridsim.sweep import context
from gridsim_core.desk import Session, grade, load_series, load_task, policies, system_prompt, text, tool_specs
from gridsim_core.desk.clock import parse_time

LUNA = "openai/gpt-6-luna"
PRICE = {LUNA: (0.10, 0.50)}
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


class LLM:
    def __init__(self, model: str, system: str, tools: list, max_cost: float):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(base_url=os.environ["LITELLM_BASE_URL"], api_key=os.environ["LITELLM_API_KEY"],
                                  timeout=900)
        self.model, self.max_cost, self.cost, self.usage = model, max_cost, 0.0, {"input": 0, "output": 0}
        self.messages = [{"role": "system", "content": system}]
        self.tools = [{"type": "function", "function": {"name": t.name, "description": t.description,
                                                        "parameters": t.inputSchema}} for t in tools]

    async def turn(self, shadow: Shadow, prompt: str, calls_per_turn: int) -> str:
        self.messages.append({"role": "user", "content": prompt})
        for _ in range(calls_per_turn + 2):
            if self.cost > self.max_cost:
                raise RuntimeError(f"cost cap: ${self.cost:.4f} spent")
            r = await self.client.chat.completions.create(model=self.model, messages=self.messages, tools=self.tools,
                                                          reasoning_effort="high", max_completion_tokens=8192)
            u = r.usage
            self.usage["input"] += u.prompt_tokens
            self.usage["output"] += u.completion_tokens
            p_in, p_out = PRICE.get(self.model, (2.0, 10.0))
            self.cost += (u.prompt_tokens * p_in + u.completion_tokens * p_out) / 1e6
            msg = r.choices[0].message
            self.messages.append(msg.model_dump(exclude_none=True))
            if not msg.tool_calls:
                return msg.content or ""
            for c in msg.tool_calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    out = await shadow.call_async(c.function.name, args) if isinstance(args, dict) else \
                        text({"error": "args: arguments must be an object"})
                except json.JSONDecodeError as e:
                    out = text({"error": f"args: not JSON: {e}"})
                self.messages.append({"role": "tool", "tool_call_id": c.id, "content": out})
        return "(tool rounds exhausted)"


async def run(bundle: Path, name: str, task: dict, series: dict, policy: str, model: str, max_cost: float,
              reminder: str | None) -> dict:
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
                    if policy == "llm":
                        system = turn.system_prompt or system_prompt(shadow_session)
                        llm = llm or LLM(model, system, tools.list(), max_cost)
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
                   "usage": llm and {"model": model, **llm.usage, "cost_usd": round(llm.cost, 4)}})
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    parser.add_argument("--pack", required=True, help="the desk pack (a name under data/desk/ or a folder)")
    parser.add_argument("--task", required=True, help="the task id")
    parser.add_argument("--policy", choices=[*policies.POLICIES, "llm"], default="anchor")
    parser.add_argument("--model", default=LUNA, help="llm: the LiteLLM model id")
    parser.add_argument("--max-cost", type=float, default=1.0, help="llm: stop past this many USD")
    parser.add_argument("--reminder", default="D0 14:35", help="a reminder the first turn sets ('' for none)")
    parser.add_argument("--image-pack", help="the pack's name inside the env image, when --pack is a folder")
    parser.add_argument("--out", type=Path, help="write the report here")
    args = parser.parse_args()
    task = load_task(args.pack, args.task)
    series = load_series(args.pack, task)
    with tempfile.TemporaryDirectory() as tmp:
        desk_tasks.generate(args.pack, Path(tmp), task_ids=[args.task], image_pack=args.image_pack)
        report = asyncio.run(run(Path(tmp), args.task, task, series, args.policy, args.model, args.max_cost,
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
