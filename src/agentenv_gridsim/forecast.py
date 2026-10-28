"""GridSim forecast ("Weather Front"): a solar-plus-storage site run for two or three operating days on forecasts served
as issued, each day's DAM position bid at its 10:00 gate the day before, gridsim_core.forecast.Session served as the
gridsim-forecast env.

It is gridsim-hybrid's env (WatchEnv) around the forecast Session: urn:gridsim:forecast-load/v1 starts a window at a
tier, each advance re-arms the clock at the next watch, and the gateway's triggers deliver the watch's notices, a
deployment's with its payload, through the hidden grid_notice tool. Every call reaches the Session with the arguments
the caller sent and answers with its exact output string, so an agent here gets what path B' trains on. data/get never
reports a reference before the window ends."""

from typing import Annotated, Any

from agentenv_protocol import environment_card, extension, tool
from pydantic import Field

from gridsim_core.forecast import END_WINDOW_URI, FORECAST_ENV, FORECAST_LOAD_URI, NOTICE_TOOL, TIERS, TOOLS, Session
from gridsim_core.forecast_prompt import tool_schemas

from .hybrid import HYBRID_NOTICE_SCHEMA
from .live import WatchEnv

FORECAST_PACK_NAMES = ("fixtures-forecast", "ercot-front-v4-eval", "ercot-front-v4-rtcb", "ercot-front-v4-showcase",
                       "ercot-front-v4-train")
TIER = "front"
EMPTY = {"task_id": None, "tier": None, "source": None, "watches": None, "watch": None, "time": None, "done": False,
         "end_reason": None, "calls_used": 0, "planning_calls": [], "forecast_calls": [], "dam": [], "book": None,
         "executed": [], "status": None, "notices": [], "forecast_log": [], "frozen": [], "refusals": [],
         "governor": [], "excused": None, "settled": 0, "audit": None, "grade": None, "reward": None}

Plan = Annotated[Any, Field(description="battery MW (and, in submit_dam, AS award MW): lists or {from, to, mw} blocks")]
Hour = Annotated[Any, Field(description="a window hour, or a time (ISO 8601; CPT without an offset)")]


def schemas(tier: str) -> dict[str, dict]:
    """Each tool the tier offers, with its listed description and input schema: the agent's are gridsim_core's, as
    path B' offers them (blind has no forecast tools)."""
    return {s["function"]["name"]: {"description": s["function"]["description"],
                                    "parameters": s["function"]["parameters"]} for s in tool_schemas(tier)} | {
        NOTICE_TOOL: HYBRID_NOTICE_SCHEMA}


@environment_card(name=FORECAST_ENV)
class GridSimForecastEnv(WatchEnv):
    NAME, SESSION, TIERS, TIER, TOOLS, EMPTY, LOAD_URI = (FORECAST_ENV, Session, TIERS, TIER, TOOLS, EMPTY,
                                                          FORECAST_LOAD_URI)
    schemas = staticmethod(schemas)

    @tool(description=schemas(TIER)["get_situation"]["description"])
    async def get_situation(self) -> str:
        return await self.call("get_situation", {})

    @tool(description=schemas(TIER)["get_forecast"]["description"])
    async def get_forecast(self, kind: str, zone: str | None = None, hours: int = 48,
                           issued_at: str | None = None) -> str:
        return await self.call("get_forecast", {"kind": kind, "zone": zone, "hours": hours, "issued_at": issued_at})

    @tool(description=schemas(TIER)["get_forecast_drift"]["description"])
    async def get_forecast_drift(self, kind: str, target_hour: Hour, zone: str | None = None) -> str:
        return await self.call("get_forecast_drift", {"kind": kind, "target_hour": target_hour, "zone": zone})

    @tool(description=schemas(TIER)["check_schedule"]["description"])
    async def check_schedule(self, plan: Plan, from_hour: Hour = None) -> str:
        return await self.call("check_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=schemas(TIER)["commit_schedule"]["description"])
    async def commit_schedule(self, plan: Plan, from_hour: Hour = None) -> str:
        return await self.call("commit_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=schemas(TIER)["submit_dam"]["description"])
    async def submit_dam(self, operating_day: str, plan: Plan, pv_da_share: float = 1.0) -> str:
        return await self.call("submit_dam", {"operating_day": operating_day, "plan": plan,
                                              "pv_da_share": pv_da_share})

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

    @extension(FORECAST_LOAD_URI, description="Start a forecast window on the task with this id at a tier (front-lite, "
                                               "front, blind or freeze-6h), on its own forecast source or, for the "
                                               "desk ablation, source desk; an env plays one window.")
    def forecast_load(self, task_id: str, tier: str = TIER, source: str | None = None) -> dict:
        if source not in (None, "desk"):
            raise ValueError(f"source overrides a window's forecasts with the desk's only, not {source!r}")
        return self.load(task_id, tier, **({"source": source} if source else {})) | {
            "days": self.session.n, "source": self.session.source}

    @extension(END_WINDOW_URI, description="Play the unreached watches on the submitted DAM entries and the committed "
                                           "book, then grade and audit the window.")
    def end_window(self) -> dict:
        return self._session().end_window()
