"""GridSim desk: gridsim_core.desk.Session served behind the gateway, one env per layer and era: gridsim-desk-v2..v5
for post-RTC+B tasks and gridsim-desk-v2-pre..v5-pre for pre-RTC+B ones, since the gateway lists each env's tool
schemas once, before a task is loaded.

urn:gridsim:desk-load/v1 loads one task and starts its Session. The agent's tools reach the Session with the arguments
as sent and answer with its exact output text. Four tools are hidden by default and shown to the hook role only:
next_wakeup and advance_to, which the GridSim post-turn hook uses to run the market between turns on the gateway's
frozen clock, and episode and grade, which the verifier reads. Once the clock is synced, advance_to refuses to run the
market to a minute the gateway clock is not at."""

import os

import httpx
from agentenv_protocol import AgentEnvEnvironment, DataPart, environment_card, extension, get_data, reset_data, tool
from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from gridsim_core.desk import Session, grade, load_series, load_task, text, tool_specs
from gridsim_core.desk.clock import to_utc

LAYERS = ("v2", "v3", "v4", "v5")
DESK_ENVS = {f"gridsim-desk-{layer}{suffix}": (layer, rtcb) for layer in LAYERS
             for suffix, rtcb in (("", True), ("-pre", False))}
LOAD_URI = "urn:gridsim:desk-load/v1"
CLOCK_URI = "urn:agentenv:clock/v1"
HOOK_ROLE = "hook"
HIDDEN = ("next_wakeup", "advance_to", "episode", "grade")
DEFAULT_PACK = "fixtures"


def env_name(layer: str, era: str) -> str:
    return f"gridsim-desk-{layer}{'' if era == 'rtcb' else '-pre'}"


def specs(layer: str, rtcb: bool) -> dict[str, dict]:
    return {s["function"]["name"]: s["function"] for s in tool_specs(layer, rtcb)}


class GridSimDeskEnv(AgentEnvEnvironment):
    LAYER: str
    RTCB: bool

    def __init__(self):
        self.specs = specs(self.LAYER, self.RTCB)
        self.time_url: str | None = None
        self.loaded = False
        self.reset()

    def create_app(self) -> FastMCP:
        app = self.mount(FastMCP(env_name(self.LAYER, "rtcb" if self.RTCB else "pre"), middleware=[DeskTools(self)]))
        for name, spec in self.specs.items():
            app.tool(_stub, name=name, description=spec["description"])
        return app

    @extension(LOAD_URI, description="Load a desk task by id from a pack and start its episode at D-1 06:00; an env "
                                     "plays one episode.")
    def load(self, task_id: str, pack: str = DEFAULT_PACK) -> dict:
        if self.loaded:
            raise ValueError("an episode was already loaded in this env: each episode needs a new deploy")
        task = load_task(pack, task_id)
        session = Session(task, load_series(pack, task), layer=self.LAYER)
        if (session.layer, session.rtcb) != (self.LAYER, self.RTCB):
            raise ValueError(f"task {task_id!r} is {session.layer} {session.era}; this env serves "
                             f"{env_name(self.LAYER, 'rtcb' if self.RTCB else 'pre')}")
        self.session, self.task, self.start = session, task, session.start()
        self.loaded = True
        return {"task_id": task_id, "layer": self.LAYER, "era": session.era, "start": self.start}

    @extension(CLOCK_URI, description="Follow the gateway's virtual clock: advance_to checks it is at the minute it "
                                      "runs the market to.")
    async def sync_time(self, env_get_time_url: str) -> dict:
        self.time_url = env_get_time_url
        return {"env_get_time_url": env_get_time_url, "virtual_time": await self.gateway_time()}

    @tool(hidden_by_default=True, description="The desk's own next wake-up (milestones, events, reminders) as "
                                              "{at, at_utc, reasons}, at null once nothing more wakes the agent, "
                                              "with the episode's end and whether it is done. Hook role only.")
    def next_wakeup(self) -> str:
        s = self._session()
        return text(s.call("next_wakeup", {}, role=HOOK_ROLE) | {"end": s.end, "end_utc": to_utc(s.end, s.d0),
                                                                  "done": s.done})

    @tool(hidden_by_default=True, description="Close the agent's turn with its reply text, run the market forward to "
                                              "this minute from D0 00:00 CPT and return {wake, message, done}: the "
                                              "wake due then (null at the end or with no turns left) and the user "
                                              "message that delivers it. Hook role only.")
    async def advance_to(self, minute: int, reply: str | None = None) -> str:
        s = self._session()
        if self.time_url is not None and (now := await self.gateway_time()) != (at := to_utc(minute, s.d0)):
            raise ValueError(f"the gateway clock reads {now}, not minute {minute} ({at}): advance it first")
        s.close_turn(reply)
        wake = s.advance_to(minute)
        return text({"wake": wake, "message": None if wake is None else text(wake), "done": s.done})

    @tool(hidden_by_default=True, description="The episode's Episode JSON (contract section 11). Hook role only.")
    def episode(self) -> str:
        return text(self._session().episode())

    @tool(hidden_by_default=True, description="The episode's grade (contract section 9.1) once it is over. Hook role "
                                              "only.")
    def grade(self) -> str:
        s = self._session()
        if not s.done:
            raise ValueError("the episode is not over: run it to its end with advance_to first")
        return text(grade(s))

    async def gateway_time(self) -> str:
        async with httpx.AsyncClient() as http:
            response = await http.get(self.time_url, timeout=10)
            response.raise_for_status()
        return response.json()["virtual_time"]

    @reset_data
    def reset(self) -> None:
        self.session = None
        self.task = None
        self.start = None

    @get_data
    def get(self) -> list[DataPart]:
        s = self.session
        return [DataPart(data={"task_id": self.task["task_id"] if self.task else None, "layer": self.LAYER,
                               "era": s.era if s else None, "done": bool(s and s.done), "start": self.start})]

    def call(self, name: str, args: dict) -> str:
        if self.session is None:
            return text({"error": f"no_episode: load a task with {LOAD_URI} first"})
        return text(self.session.call(name, args))

    def _session(self) -> Session:
        if self.session is None:
            raise ValueError(f"no episode loaded: load a task with {LOAD_URI} first")
        return self.session


def _stub() -> str:
    raise RuntimeError("the desk's tools are answered by its middleware")


class DeskTools(Middleware):
    """Hands every agent-tool call to the Session with the arguments as sent, so a malformed call gets the Session's
    own answer rather than a schema error; lists the agent tools in core's order with core's descriptions and input
    schemas, then the hidden ones."""

    def __init__(self, env: GridSimDeskEnv):
        self.env = env

    async def on_call_tool(self, context, call_next):
        name = context.message.name
        if name not in self.env.specs:
            return await call_next(context)
        out = self.env.call(name, dict(context.message.arguments or {}))
        return ToolResult(content=[TextContent(type="text", text=out)], structured_content={"result": out})

    async def on_list_tools(self, context, call_next):
        tools = {t.name: t for t in await call_next(context)}
        listed = [tools[n].model_copy(update={"description": s["description"], "parameters": s["parameters"]})
                  for n, s in self.env.specs.items() if n in tools]
        return listed + [tools[n] for n in HIDDEN if n in tools]


def desk_env(name: str) -> GridSimDeskEnv:
    layer, rtcb = DESK_ENVS[name]
    cls = type(f"GridSimDesk{layer.upper()}{'' if rtcb else 'Pre'}Env", (GridSimDeskEnv,),
               {"LAYER": layer, "RTCB": rtcb})
    return environment_card(name=name)(cls)()


def main() -> None:
    desk_env(os.environ.get("ENVIRONMENT_NAME", "gridsim-desk-v2")).create_app().run(
        transport="http", host=os.environ.get("MCP_HOST", "0.0.0.0"), port=int(os.environ.get("MCP_PORT", "18765")),
        show_banner=False)
