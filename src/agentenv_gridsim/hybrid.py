"""GridSim hybrid: one solar-plus-storage site-day behind one meter, co-optimised across energy and five ancillary
services in watches on the gateway's virtual clock, gridsim_core.hybrid.Session served as the gridsim-hybrid env.

It is gridsim-live's env (WatchEnv) around the hybrid Session: urn:gridsim:live-load/v1 starts a day at a tier, each
advance re-arms the clock at the next watch, and the gateway's triggers deliver the watch's notices, a deployment's
with its payload, through the hidden grid_notice tool. Every call reaches the Session with the arguments the caller
sent and answers with its exact output string, so an agent here gets what path B' trains on. data/get never reports a
reference before the day ends."""

from typing import Annotated, Any

from agentenv_protocol import environment_card, extension, tool
from pydantic import Field

from gridsim_core.hybrid import END_DAY_URI, HYBRID_ENV, LIVE_LOAD_URI, NOTICE_TOOL, TIERS, TOOLS, Session
from gridsim_core.hybrid_prompt import tool_schemas

from .live import NOTICE_SCHEMA, WatchEnv

HYBRID_PACK_NAMES = ("fixtures-hybrid", "ercot-hybrid-v3-eval", "ercot-hybrid-v3-rtcb", "ercot-hybrid-v3-showcase",
                     "ercot-hybrid-v3-train")
TIER = "reserves"
DEPLOY = {"type": ["object", "null"], "required": ["product", "frac", "start_min", "end_min"], "properties": {
    "product": {"type": "string"}, "frac": {"type": "number"}, "start_min": {"type": "integer"},
    "end_min": {"type": "integer"}}}
HYBRID_NOTICE_SCHEMA = {
    "description": "Deliver one notice for this watch: the message is queued for the agent's next tool result, and a "
                   "deployment's payload is revealed (it dispatches the awards at its real time either way). Called "
                   "by the env's triggers.",
    "parameters": {**NOTICE_SCHEMA["parameters"],
                   "properties": NOTICE_SCHEMA["parameters"]["properties"] | {"deploy": DEPLOY}}}
EMPTY = {"task_id": None, "tier": None, "watches": None, "watch": None, "time": None, "done": False,
         "end_reason": None, "calls_used": 0, "planning_calls": [], "book": None, "da": None, "executed": [],
         "status": None, "notices": [], "frozen": [], "refusals": [], "governor": [], "excused": None, "settled": 0,
         "audit": None, "grade": None, "reward": None}

Plan = Annotated[Any, Field(description="energy and AS levels in MW: lists or {from, to, mw} blocks")]
Hour = Annotated[Any, Field(description="the first hour the plan covers, 0..23")]


def schemas(tier: str) -> dict[str, dict]:
    """Each tool's listed description and input schema: the agent's are gridsim_core's, as path B' offers them."""
    return {s["function"]["name"]: {"description": s["function"]["description"],
                                    "parameters": s["function"]["parameters"]} for s in tool_schemas(tier)} | {
        NOTICE_TOOL: HYBRID_NOTICE_SCHEMA}


@environment_card(name=HYBRID_ENV)
class GridSimHybridEnv(WatchEnv):
    NAME, SESSION, TIERS, TIER, TOOLS, EMPTY = HYBRID_ENV, Session, TIERS, TIER, TOOLS, EMPTY
    schemas = staticmethod(schemas)

    @tool(description=schemas(TIER)["get_situation"]["description"])
    async def get_situation(self) -> str:
        return await self.call("get_situation", {})

    @tool(description=schemas(TIER)["check_schedule"]["description"])
    async def check_schedule(self, plan: Plan, from_hour: Hour = None) -> str:
        return await self.call("check_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=schemas(TIER)["commit_schedule"]["description"])
    async def commit_schedule(self, plan: Plan, from_hour: Hour = None) -> str:
        return await self.call("commit_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=schemas(TIER)["advance"]["description"])
    async def advance(self) -> str:
        return await self.call("advance", {})

    @tool(description=HYBRID_NOTICE_SCHEMA["description"])
    async def grid_notice(self, event_id: str, name: str, text: str, level: str | None = None,
                          derate_mw: float | None = None,
                          start: Annotated[str | None, Field(alias="from")] = None, until: str | None = None,
                          deploy: dict | None = None) -> str:
        return await self.call(NOTICE_TOOL, {"event_id": event_id, "name": name, "text": text, "level": level,
                                             "derate_mw": derate_mw, "from": start, "until": until, "deploy": deploy})

    @extension(LIVE_LOAD_URI, description="Start a live hybrid site-day on the task with this id at a tier (energy, "
                                           "reserves or rtcb); an env plays one day.")
    def live_load(self, task_id: str, tier: str = TIER) -> dict:
        return self.load(task_id, tier)

    @extension(END_DAY_URI, description="Play the unreached watches on the committed schedule, then grade and audit "
                                        "the day.")
    def end_day(self) -> dict:
        return self._session().end_day()
