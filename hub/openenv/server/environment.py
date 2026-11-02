"""GridSimEnv Desk as an OpenEnv environment. Each session trades one benchmark window on gridsim_core.desk's Session,
the desk state machine the benchmark's gridsim-desk env serves: its eleven tools reach the Session with the arguments as
sent and answer with its exact output, under the same per-turn call budget, and end_turn closes the turn with the reply
and runs the market to the next wake-up, as the benchmark's post-turn hook does; the end_turn that ends the window
grades it. Prompts, end_turn and the Task API follow AgentEnv's OpenEnv adapter (agent_env.openenv)."""

import asyncio
import secrets
import threading
import weakref
from contextlib import asynccontextmanager
from functools import cache
from typing import Any

from fastmcp import FastMCP
from openenv.core.env_server.mcp_environment import MCPEnvironment
from openenv.core.env_server.mcp_types import (
    CallToolAction,
    CallToolObservation,
    ListToolsAction,
    ListToolsObservation,
    Tool,
    ToolError,
    ToolErrorType,
)
from openenv.core.env_server.types import Observation, State
from openenv.core.rubrics import Rubric

from gridsim_core.desk import Session, clock, grade, system_prompt, text, tool_specs
from gridsim_core.desk.settle import partial

from .windows import windows

ENV_NAME = "gridsim_desk"
END_TURN = Tool(name="end_turn", description="End your turn with your reply. The episode goes on to your next turn, or "
                                             "ends and is scored.",
                input_schema={"type": "object", "properties": {"response": {"type": "string",
                                                                             "description": "Your reply."}}})
NOT_RESET = "no episode has started; call reset before stepping"
TOOLSET = {"envs": ["gridsim-desk-v4"], "versions": {}, "role": None,
           "access": [{"env": "gridsim-desk-v4", "action": "disable", "tools": ["get_time"]}], "bash": False}
REFS = ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual")
LIVE: "weakref.WeakValueDictionary[str, GridSimDeskEnvironment]" = weakref.WeakValueDictionary()


def tools(layer: str = "v4", rtcb: bool = True) -> list[Tool]:
    return [Tool(name=s["function"]["name"], description=s["function"]["description"],
                 input_schema=s["function"]["parameters"]) for s in tool_specs(layer, rtcb)] + [END_TURN]


@cache
def opening(task_id: str) -> tuple[str, str]:
    """The window's first prompt (the start wake-up) and system prompt (the desk brief), as the benchmark's agents had
    them."""
    s = Session(windows().tasks[task_id], windows().series(task_id))
    return text(s.start()), system_prompt(s)


def describe(split: str, index: int) -> dict:
    w = windows()
    task_id = w.at(split, index)
    prompt, system = opening(task_id)
    return {"id": task_id, "name": task_id, "index": index, "prompt": prompt, "system_prompt": system,
            "agent": "agent", "toolset": TOOLSET, "turns": 1, "window": w.cards[task_id]}


class DeskState(State):
    task_id: str | None = None
    split: str | None = None
    index: int | None = None
    now: str | None = None
    turn: int = 0
    turns_left: int | None = None
    calls_left: int | None = None
    done: bool = False
    reward: float | None = None


class _Graded(Rubric):
    def __init__(self, key: str):
        super().__init__()
        object.__setattr__(self, "key", key)

    def forward(self, action, observation) -> float:
        g = (observation.metadata or {}).get("grade") if observation.done else None
        return float(g.get(self.key) or 0.0) if g else 0.0


class DeskRubric(_Graded):
    """The desk's reward R (contract 9.1) on the end_turn that ends the window and 0.0 on every other step; its
    children report the hindsight capture C and whether a submission was accepted."""

    def __init__(self):
        super().__init__("reward")
        self.capture = _Graded("capture")
        self.valid = _Graded("valid")

    def forward(self, action, observation) -> float:
        self.capture(action, observation)
        self.valid(action, observation)
        return super().forward(action, observation)


class GridSimDeskEnvironment(MCPEnvironment):
    """Every OpenEnv route to the tools (the WebSocket's steps, its MCP messages, HTTP /mcp, the playground) reaches
    step(): the FastMCP server is left out, and each tool is marked a mode tool so /mcp tools/call answers with the
    tool's own result, as OpenEnv's MCP envs do."""

    SUPPORTS_CONCURRENT_SESSIONS = True

    def __init__(self):
        super().__init__(FastMCP(ENV_NAME))
        self.mcp_client = self.mcp_server = None
        self._mode_tools = {t.name: {"production": None} for t in tools()}
        self.rubric = DeskRubric()
        self.lock = threading.RLock()
        self.s: Session | None = None
        self.task_id = self.token = None
        self.split, self.index = windows().split, None
        self.closed = False
        self._pnl: list[float] = []
        self._state = DeskState()

    @asynccontextmanager
    async def mcp_session(self):
        yield None

    # The Task API

    def list_splits(self) -> list[dict]:
        w = windows()
        return [{"name": s, "type": "test", "num_tasks": len(w.ids(s))} for s in w.splits()]

    def num_tasks(self, split: str) -> int:
        return len(windows().ids(split))

    def get_task(self, split: str, index: int) -> dict:
        return describe(split, int(index))

    def get_task_range(self, split: str, start: int | None = None, stop: int | None = None) -> list[dict]:
        return [describe(split, i) for i in range(self.num_tasks(split))[start:stop]]

    def list_tasks(self, split: str) -> list[dict]:
        return self.get_task_range(split)

    # The episode

    def reset(self, seed: int | None = None, episode_id: str | None = None, split: str | None = None,
              index: int | None = None, task_id: str | None = None, **kwargs: Any) -> Observation:
        """Plays task_id, or window index of split, or with neither a window drawn by seed, or else the default one."""
        w = windows()
        with self.lock:
            if self.closed:
                raise RuntimeError("session_closed: this session was closed; open a new one")
            self._release()
            if task_id is None:
                split = split or w.split
                if index is not None:
                    task_id = w.at(split, int(index))
                elif seed is not None:
                    ids = w.ids(split)
                    task_id = ids[seed % len(ids)]
                else:
                    task_id = w.default
            if task_id not in w.tasks:
                raise ValueError(f"unknown window {task_id!r}")
            self.task_id, self.index = task_id, w.order.index(task_id)
            self.s = Session(w.tasks[task_id], w.series(task_id))
            self.token = secrets.token_hex(16)
            LIVE[self.token] = self
            self._pnl = []
            self._reset_rubric()
            wake = self.s.start()
            prompt, system = opening(task_id)
            self._state = DeskState(episode_id=episode_id or self.token[:12], task_id=task_id, split=w.split,
                                    index=self.index)
            self._sync()
            return Observation(done=False, reward=None, metadata={
                "prompt": text(wake), "system_prompt": system, "task": self._task(), "window": w.cards[task_id],
                "episode": self.token, "desk": self.status(), "tools": [t.name for t in tools()]})

    def step(self, action: Any, timeout_s: float | None = None, **kwargs: Any) -> Observation:
        with self.lock:
            if isinstance(action, ListToolsAction):
                s = self.s
                return ListToolsObservation(tools=tools(s.layer, s.rtcb) if s else tools())
            if self.closed:
                return CallToolObservation(tool_name=getattr(action, "tool_name", ""), done=True, error=ToolError(
                    error_type=ToolErrorType.EXECUTION_ERROR, message="session_closed: this session was closed; "
                                                                      "open a new one and reset"))
            if self.s is None:
                raise RuntimeError(NOT_RESET)
            if not isinstance(action, CallToolAction):
                raise TypeError(f"unsupported action {type(action).__name__}; use ListToolsAction or CallToolAction")
            self._state.step_count += 1
            name = action.tool_name
            if name == END_TURN.name:
                obs = self._end_turn(action.arguments.get("response"))
            elif name not in {t.name for t in tools(self.s.layer, self.s.rtcb)}:
                obs = CallToolObservation(tool_name=name, error=ToolError(
                    error_type=ToolErrorType.TOOL_NOT_FOUND, message=f"{name} is not a desk tool"))
            else:
                out = text(self.s.call(name, dict(action.arguments or {})))
                obs = CallToolObservation(tool_name=name, done=self.s.done, result=_result(out))
            obs.reward = self._apply_rubric(action, obs)
            if obs.done and obs.metadata.get("grade"):
                obs.metadata["rubric"] = {n: r.last_score for n, r in self.rubric.named_rubrics()}
                self._state.reward = obs.reward
            obs.metadata["desk"] = self.status()
            self._sync()
            return obs

    async def step_async(self, action: Any, timeout_s: float | None = None, **kwargs: Any) -> Observation:
        return await asyncio.to_thread(self.step, action, timeout_s)

    async def _async_handle_list_tools(self) -> ListToolsObservation:
        return await asyncio.to_thread(self.step, ListToolsAction())

    async def _async_handle_call_tool(self, action: CallToolAction, timeout_s: float | None = None) -> Observation:
        return await asyncio.to_thread(self.step, action, timeout_s)

    def _step_impl(self, action: Any, timeout_s: float | None = None, **kwargs: Any) -> Observation:
        raise TypeError("use the desk's tools: ListToolsAction or CallToolAction")

    def _end_turn(self, response: Any) -> CallToolObservation:
        s = self.s
        if s.done:
            return CallToolObservation(tool_name=END_TURN.name, done=True, result=_result(text(
                {"error": "over: the episode has ended"})))
        wake = s.end_turn(response if isinstance(response, str) else None)
        if wake is not None:
            prompt, system = text(wake), opening(self.task_id)[1]
            return CallToolObservation(tool_name=END_TURN.name, result={"prompt": prompt, "system_prompt": system,
                                                                         "data": prompt})
        s.finish()
        g = self.grade()
        return CallToolObservation(tool_name=END_TURN.name, done=True, result={"data": text(g)},
                                   metadata={"grade": g, "scores": {"grade": g["reward"]}, "task": self._task(),
                                             "statement": s.result})

    def grade(self) -> dict:
        t = windows().tasks[self.task_id]
        return grade(self.s, {k: t["refs"].get(k) for k in REFS})

    def status(self) -> dict:
        s = self.s
        if s is None:
            return {}
        per = s.budget["calls_per_turn"]
        return {"now": clock.label(s.now, s.d0), "minute": s.now, "turn": s.turn + 1,
                "max_turns": s.budget["max_turns"], "turns_left": s.turns_left, "calls_left": max(per - s.calls, 0),
                "calls_per_turn": per, "done": s.done}

    def view(self) -> dict:
        """What the page shows besides the tools' answers: the battery's metered output and charge up to now, the
        statement as it settles, the wake-ups so far, the weather observed up to now and, once the window is over,
        its grade against the references."""
        with self.lock:
            s, w = self.s, windows()
            e = s.engine
            upto = 96 * s.ser.days if s.done else max(int((s.now - 2) // 15), 0) if s.now > 0 else 0
            anc = s.ancillary_record()
            while 4 * (len(self._pnl) + 1) <= upto:
                self._pnl.append(partial(s.site, s.ser, s.rtcb, e.dam_award, e.bp, e.metered, 4 * (len(self._pnl) + 1),
                                         anc)["total"])
            settled = s.result["total"] if s.done else 0.0
            if upto and not s.done:
                settled = partial(s.site, s.ser, s.rtcb, e.dam_award, e.bp, e.metered, upto, anc)["total"]
            hour = s.now / 60
            out = {"task_id": self.task_id, "desk": self.status(), "t0": clock.START, "t1": s.end,
                   "m": [round(x, 1) for x in e.metered[:e.k]], "soc": [round(x, 2) for x in e.soc[:e.k + 1]],
                   "pnl": self._pnl, "settled": {"upto": upto, "total": settled},
                   "as": _as_hours(e, s.now) if e.ancillary else None,
                   "wakes": [[x["t"], x["reasons"], x["turn"]] for x in s.wakes],
                   "events": [{k: v for k, v in ev.items() if k != "t"} for ev in s.events],
                   "weather": [o for o in w.scenes[self.task_id]["weather"] if o["t"] <= hour]}
            if s.done:
                out.update(grade=self.grade(), statement=s.result, bench=w.bench[self.task_id])
            return out

    @property
    def state(self) -> DeskState:
        return self._state

    def close(self) -> None:
        with self.lock:
            self._release()
            self.closed = True
        super().close()

    def _release(self) -> None:
        if self.token:
            LIVE.pop(self.token, None)
        self.s = self.token = None

    def _sync(self) -> None:
        st = self.status()
        for k in ("now", "turn", "turns_left", "calls_left", "done"):
            setattr(self._state, k, st[k])

    def _task(self) -> dict:
        return {"id": self.task_id, "name": self.task_id, "split": self.split, "index": self.index}


def _result(out: str) -> dict:
    return {"content": [{"type": "text", "text": out}], "structured_content": None, "meta": None, "data": out,
            "is_error": False}


def _as_hours(e, now: int) -> dict:
    """Reserve awards per hour for the hours under way or done: the DAM's and SCED's largest in each hour."""
    h1 = min(max(now, 0) // 60 + 1, e.H) if now > 0 else 0
    dam = {p: [round(e.dam_as[H].get(p, 0.0), 1) for H in range(h1)] for p in e.products}
    rt = {p: [round(max((e.rt_as[k].get(p, 0.0) for k in range(12 * H, min(12 * H + 12, e.k))), default=0.0), 1)
              for H in range(h1)] for p in e.products} if e.rtcb else {}
    return {"dam": {p: v for p, v in dam.items() if any(v)}, "rt": {p: v for p, v in rt.items() if any(v)}}
