"""GridSim market ("The Market Floor"): seat A's battery portfolio offers into ERCOT's day-ahead market re-cleared from
the real 60-day disclosure, gridsim_core.market.Session served as the gridsim-market env.

It is gridsim-live's env (WatchEnv) around the market Session: urn:gridsim:market-load/v1 starts a floor at a tier
(floor-sprint: one decision at D-1 09:00; floor-day: the clocked day), each advance re-arms the clock at the next watch,
and the gateway's triggers deliver the watch's ISO notices through the hidden grid_notice tool. Every call reaches the
Session with the arguments the caller sent and answers with its exact output string, so an agent here gets what path B
and B' train on. The other seats are scripted in process on their real offers; none of their costs or offers reach
seat A. data/get never reports a reference before the floor ends."""

import json
from typing import Annotated, Any

from agentenv_protocol import DataPart, environment_card, extension, get_data, tool
from pydantic import Field

from gridsim_core.live import NOTICE_TOOL
from gridsim_core.market import END_URI, LOAD_URI, MARKET_ENV, TIERS, TOOLS, Session
from gridsim_core.market_prompt import tool_schemas

from .live import NOTICE_SCHEMA, WatchEnv

MARKET_PACK_NAMES = ("fixtures-market", "gridsim-market-eval", "gridsim-market-rtcb", "gridsim-market-showcase",
                     "gridsim-market-train")
CALLS_URI = "urn:gridsim:market-calls/v1"
LISTED = "floor-day"
"""The tier whose tools the env lists before a floor loads: every tool, as the gateway reads them at deploy."""
ISO = ("replay", "off")
EMPTY = {"task_id": None, "tier": None, "compliant": False, "watches": None, "watch": None, "time": None,
         "done": False, "end_reason": None, "calls_used": 0, "planning_calls": [], "data_calls": [], "offer": None,
         "submitted": False, "schedule": None, "executed": [], "notices": [], "frozen": [], "refusals": [],
         "commits": [], "contracts": [], "messages": [], "audit": None, "grade": None, "reward": None}

Offer = Annotated[Any, Field(description='{"hours": [{"he": 1..24, "sell": [[mw, price], ...], "buy": [...]}]}')]
Plan = Annotated[Any, Field(description="MW per hour from from_hour (+ discharge, - charge)")]


def schemas(tier: str) -> dict[str, dict]:
    """Each tool the tier offers, with its listed description and input schema: the agent's are gridsim_core's, as
    path B offers them."""
    return {s["function"]["name"]: {"description": s["function"]["description"],
                                    "parameters": s["function"]["parameters"]} for s in tool_schemas(tier)} | {
        NOTICE_TOOL: NOTICE_SCHEMA}


ALL = schemas("floor-day")


@environment_card(name=MARKET_ENV)
class GridSimMarketEnv(WatchEnv):
    NAME, SESSION, TIERS, TIER, TOOLS, EMPTY, LOAD_URI = MARKET_ENV, Session, TIERS, LISTED, TOOLS, EMPTY, LOAD_URI
    schemas = staticmethod(schemas)

    def __init__(self, tasks):
        self.compliant = False
        super().__init__(tasks)

    @tool(description=ALL["get_situation"]["description"])
    async def get_situation(self) -> str:
        return await self.call("get_situation", {})

    @tool(description=ALL["get_forecast"]["description"])
    async def get_forecast(self, kind: str, issued_at: str | None = None) -> str:
        return await self.call("get_forecast", {"kind": kind, "issued_at": issued_at})

    @tool(description=ALL["get_disclosure"]["description"])
    async def get_disclosure(self, op_date: str, side: str = "supply", hour: int | None = None) -> str:
        return await self.call("get_disclosure", {"op_date": op_date, "side": side, "hour": hour})

    @tool(description=ALL["get_private_costs"]["description"])
    async def get_private_costs(self) -> str:
        return await self.call("get_private_costs", {})

    @tool(description=ALL["check_offer"]["description"])
    async def check_offer(self, offer: Offer) -> str:
        return await self.call("check_offer", {"offer": offer})

    @tool(description=ALL["submit_offer"]["description"])
    async def submit_offer(self, offer: Offer) -> str:
        return await self.call("submit_offer", {"offer": offer})

    @tool(description=ALL["get_award"]["description"])
    async def get_award(self, op_date: str | None = None) -> str:
        return await self.call("get_award", {"op_date": op_date})

    @tool(description=ALL["check_schedule"]["description"])
    async def check_schedule(self, plan: Plan, from_hour: int | None = None) -> str:
        return await self.call("check_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=ALL["commit_schedule"]["description"])
    async def commit_schedule(self, plan: Plan, from_hour: int | None = None) -> str:
        return await self.call("commit_schedule", {"plan": plan, "from_hour": from_hour})

    @tool(description=ALL["advance"]["description"])
    async def advance(self) -> str:
        return await self.call("advance", {})

    @tool(description=ALL["propose_contract"]["description"])
    async def propose_contract(self, hours: list[int], mw: float, strike_usd: float, counterparty: str = "retail-L",
                               kind: str = "cfd", op_dates: list[str] | None = None) -> str:
        return await self.call("propose_contract", {"counterparty": counterparty, "kind": kind, "hours": hours,
                                                    "mw": mw, "strike_usd": strike_usd, "op_dates": op_dates})

    @tool(description=ALL["respond_contract"]["description"])
    async def respond_contract(self, contract_id: str, action: str, strike_usd: float | None = None) -> str:
        return await self.call("respond_contract", {"contract_id": contract_id, "action": action,
                                                    "strike_usd": strike_usd})

    @tool(description=ALL["message_agent"]["description"])
    async def message_agent(self, agent_name: str, text: str) -> str:
        return await self.call("message_agent", {"agent_name": agent_name, "text": text})

    @tool(description=NOTICE_SCHEMA["description"])
    async def grid_notice(self, event_id: str, name: str, text: str, level: str | None = None,
                          derate_mw: float | None = None,
                          start: Annotated[str | None, Field(alias="from")] = None, until: str | None = None) -> str:
        return await self.call(NOTICE_TOOL, {"event_id": event_id, "name": name, "text": text, "level": level,
                                             "derate_mw": derate_mw, "from": start, "until": until})

    @extension(LOAD_URI, description="Start a floor on the task with this id at a tier (floor-sprint or floor-day), "
                                      "the other seats scripted on their real offers, the ISO's notices replayed or "
                                      "off; compliant scores it 0.5 R + 0.5 welfare ratio. An env plays one floor.")
    def market_load(self, floor_id: str, tier: str = "floor-sprint", bidders: str = "scripted", script: str = "real",
                    iso: str = "replay", compliant: bool = False) -> dict:
        if bidders != "scripted" or script != "real":
            raise ValueError("the preview plays scripted bidders on their real offers (bidders scripted, script real)")
        if iso not in ISO:
            raise ValueError(f"iso is one of {', '.join(ISO)}, not {iso!r}")
        if self.loaded:
            raise ValueError("a floor was already loaded in this env: each floor needs a new deploy")
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}: one of {', '.join(TIERS)}")
        if (row := self.tasks.get(floor_id)) is None:
            raise ValueError(f"unknown floor id {floor_id!r}")
        self.reset()
        self.session = Session(row, tier, [] if iso == "off" else None, compliant=bool(compliant))
        self.compliant, self.loaded = bool(compliant), True
        return {"floor_id": floor_id, "tier": tier, "watches": len(self.session.watches)}

    @extension(END_URI, description="Close the floor: clear the market if it hasn't, run the day on the awards or the "
                                     "committed schedule, then grade and audit it.")
    def end_floor(self) -> dict:
        return self._session().end_floor()

    @extension(CALLS_URI, description="Play tool calls as seat A outside the agent's turns, in order, each answered as "
                                       "the agent's would be; an advance that opens a watch moves the clock and "
                                       "delivers the watch's notices.")
    async def market_calls(self, calls: list[dict]) -> dict:
        s, outs = self._session(), []
        for c in calls:
            out = await self.call(c["tool"], dict(c.get("args") or {}))
            outs.append(out)
            if c["tool"] == "advance" and "watch" in json.loads(out) and not s.done:
                s.deliver_watch_notices(via="harness")
        return {"outputs": outs}

    @get_data
    def get(self) -> list[DataPart]:
        return [DataPart(data=self.session.data() | {"compliant": self.compliant} if self.session else self.EMPTY)]
