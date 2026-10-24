"""GridSim live: one battery-day played in watches on the gateway's virtual clock, gridsim_core.live.Session served as
the gridsim-live env.

urn:gridsim:live-load/v1 starts a day; each advance re-arms the clock at the next watch, and the gateway's triggers
deliver the watch's notices through the hidden grid_notice tool. Every call reaches the Session with the arguments the
caller sent and answers with its exact output string, so an agent here gets what path B' trains on. data/get never
reports a reference plan or value before the day ends."""

from typing import Annotated, Any

import httpx
from agentenv_protocol import AgentEnvEnvironment, DataPart, environment_card, extension, get_data, reset_data, tool
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.types import TextContent
from pydantic import Field

from gridsim_core.live import CLOCK_URI, END_DAY_URI, LIVE_ENV, LIVE_LOAD_URI, NOTICE_TOOL, TIERS, TOOLS, Session
from gridsim_core.live_prompt import tool_schemas

LIVE_PACK_NAMES = ("fixtures-live", "gridsim-live-eval", "gridsim-live-test-2025", "gridsim-live-rtcb",
                   "gridsim-live-showcase", "gridsim-live-train")
NOTICE_SCHEMA = {
    "description": "Deliver one notice for this watch: the battery applies a derate and the message is queued for the "
                   "agent's next tool result. Called by the env's triggers.",
    "parameters": {"type": "object", "required": ["event_id", "name", "text"], "properties": {
        "event_id": {"type": "string"}, "name": {"type": "string"}, "text": {"type": "string"},
        "level": {"type": ["string", "null"]}, "derate_mw": {"type": ["number", "null"]},
        "from": {"type": ["string", "null"]}, "until": {"type": ["string", "null"]}}}}
EMPTY = {"task_id": None, "tier": None, "watches": None, "watch": None, "time": None, "done": False,
         "end_reason": None, "calls_used": 0, "planning_calls": [], "da_position": None, "schedule": None,
         "executed": [], "schedule_status": None, "notices": [], "frozen": [], "refusals": [], "excused": None,
         "settled": 0, "audit": None, "grade": None, "reward": None}

Ints = Annotated[Any, Field(description="integers, a list or a comma/space-separated string")]


def schemas(tier: str) -> dict[str, dict]:
    """Each tool's listed description and input schema: the agent's are gridsim_core's, as path B' offers them."""
    return {s["function"]["name"]: {"description": s["function"]["description"],
                                    "parameters": s["function"]["parameters"]} for s in tool_schemas(tier)} | {
        NOTICE_TOOL: NOTICE_SCHEMA}


class WatchEnv(AgentEnvEnvironment):
    """A day in watches behind the gateway, the part gridsim-live and gridsim-hybrid share: one Session per deploy that
    every agent-tool and grid_notice call reaches as sent, advance re-arming the gateway's clock at the watch it opens,
    end-day, the clock sync and data/get. A subclass declares its tools and live_load and sets NAME, SESSION, TIERS,
    TIER, TOOLS, EMPTY and schemas."""

    NAME: str
    SESSION: type
    TIERS: tuple[str, ...]
    TIER: str
    TOOLS: tuple[str, ...]
    EMPTY: dict

    def __init__(self, tasks):
        self.tasks = tasks
        self.set_time_url: str | None = None
        self.loaded = False
        self.reset()

    def create_app(self) -> FastMCP:
        return self.mount(FastMCP(self.NAME, middleware=[LiveDay(self)]))

    @staticmethod
    def schemas(tier: str) -> dict[str, dict]:
        raise NotImplementedError

    async def call(self, name: str, args: dict) -> str:
        """The Session's output for one call; an advance that opens a watch first moves the gateway's clock to it."""
        s = self._session()
        if name == "advance" and not args and not s.done and not s.last:
            await self.set_clock(s.watch_time_utc(s.watch + 1))
        return s.call(name, args)

    async def set_clock(self, virtual_time: str) -> None:
        if self.set_time_url is None:
            raise ValueError(f"the gateway clock is not synced: call {CLOCK_URI} sync_time first")
        async with httpx.AsyncClient() as http:
            response = await http.put(self.set_time_url, timeout=10, json={
                "virtual_time": virtual_time, "virtual_seconds_per_real_second": 0})
            response.raise_for_status()

    def load(self, task_id: str, tier: str) -> dict:
        """Loading again would replay the day with its notices and prices already seen, unseen by the audit."""
        if self.loaded:
            raise ValueError("a day was already loaded in this env: each live day needs a new deploy")
        if tier not in self.TIERS:
            raise ValueError(f"unknown tier {tier!r}: one of {', '.join(self.TIERS)}")
        if (row := self.tasks.get(task_id)) is None:
            raise ValueError(f"unknown task id {task_id!r}")
        self.reset()
        self.session = self.SESSION(row, tier)
        self.loaded = True
        return {"task_id": task_id, "tier": tier, "watches": len(self.session.watches)}

    @extension(END_DAY_URI, description="Play the unreached watches on the committed schedule, then grade and audit "
                                        "the day.")
    def end_day(self) -> dict:
        return self._session().end_day()

    @extension(CLOCK_URI, description="Follow the gateway's virtual clock; advance re-arms it at each watch.")
    async def sync_time(self, env_get_time_url: str) -> dict:
        self.set_time_url = env_get_time_url.removesuffix("/clock/time") + "/clock/set-time"
        async with httpx.AsyncClient() as http:
            response = await http.get(env_get_time_url, timeout=10)
            response.raise_for_status()
        return {"env_get_time_url": env_get_time_url, "virtual_time": response.json()["virtual_time"]}

    @reset_data
    def reset(self) -> None:
        self.session = None

    @get_data
    def get(self) -> list[DataPart]:
        return [DataPart(data=self.session.data() if self.session else self.EMPTY)]

    def _session(self):
        if self.session is None:
            raise ValueError(f"no day loaded: load one with {LIVE_LOAD_URI}")
        return self.session


@environment_card(name=LIVE_ENV)
class GridSimLiveEnv(WatchEnv):
    NAME, SESSION, TIERS, TIER, TOOLS, EMPTY = LIVE_ENV, Session, TIERS, "foresight", TOOLS, EMPTY
    schemas = staticmethod(schemas)

    @tool(description=schemas("foresight")["get_situation"]["description"])
    async def get_situation(self) -> str:
        return await self.call("get_situation", {})

    @tool(description=schemas("foresight")["commit_da"]["description"])
    async def commit_da(self, position: Ints) -> str:
        return await self.call("commit_da", {"position": position})

    @tool(description=schemas("foresight")["check_schedule"]["description"])
    async def check_schedule(self, actions: Ints, start: str, step: str = "15m") -> str:
        return await self.call("check_schedule", {"actions": actions, "start": start, "step": step})

    @tool(description=schemas("foresight")["commit_schedule"]["description"])
    async def commit_schedule(self, actions: Ints, start: str, step: str = "15m") -> str:
        return await self.call("commit_schedule", {"actions": actions, "start": start, "step": step})

    @tool(description=schemas("foresight")["advance"]["description"])
    async def advance(self) -> str:
        return await self.call("advance", {})

    @tool(description=NOTICE_SCHEMA["description"])
    async def grid_notice(self, event_id: str, name: str, text: str, level: str | None = None,
                          derate_mw: float | None = None,
                          start: Annotated[str | None, Field(alias="from")] = None, until: str | None = None) -> str:
        return await self.call(NOTICE_TOOL, {"event_id": event_id, "name": name, "text": text, "level": level,
                                             "derate_mw": derate_mw, "from": start, "until": until})

    @extension(LIVE_LOAD_URI, description="Start a live battery-day on the task with this id at a tier; an env plays "
                                           "one day.")
    def live_load(self, task_id: str, tier: str = "foresight") -> dict:
        return self.load(task_id, tier)


class LiveDay(Middleware):
    """Hands every agent-tool and grid_notice call to the Session with the arguments as sent, so a malformed call gets
    the Session's own answer (and uses a planning call) rather than a schema error, in the shape the tool's own str
    return takes; lists the tools in gridsim_core's order with its descriptions and input schemas."""

    def __init__(self, env: WatchEnv):
        self.env = env

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        if name not in (*self.env.TOOLS, NOTICE_TOOL):
            return await call_next(context)
        text = await self.env.call(name, dict(context.message.arguments or {}))
        return ToolResult(content=[TextContent(type="text", text=text)], structured_content={"result": text})

    async def on_list_tools(self, context, call_next):
        listed = self.env.schemas(self.env.session.tier if self.env.session else self.env.TIER)
        tools = {t.name: t for t in await call_next(context)}
        return [tools[n].model_copy(update=listed[n]) for n in (*self.env.TOOLS, NOTICE_TOOL) if n in tools]
