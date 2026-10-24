"""The gridsim env: one battery-day per episode on three MCP tools, their text, schemas and outputs gridsim_core's, so
an agent here sees what path B trains on.

urn:gridsim:load-task/v1 starts an episode; data/get reports it, with the grade, the reward and the task row only once
it is done. The task packs come from GRIDSIM_TASKS_DIR (colon-separated pack folders), else gridsim_core's data/."""

import gzip
import json
import os
from pathlib import Path
from typing import Annotated, Any

from agentenv_protocol import AgentEnvEnvironment, DataPart, environment_card, extension, get_data, reset_data, tool
from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError
from fastmcp.server.middleware import Middleware
from pydantic import Field

from gridsim_core.episode import check_result, submit_result
from gridsim_core.grade import grade
from gridsim_core.parse import parse_actions
from gridsim_core.prompt import situation_text, tool_schemas
from gridsim_core.task import TIERS, data_root

PACK_NAMES = ("fixtures", "ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "ercot-dam-v1-train")
MAX_CHECKS = 3
MAX_TOOL_CALLS = 24
LOAD_URI = "urn:gridsim:load-task/v1"
SUBMIT_URI = "urn:gridsim:submit-schedule/v1"
DISABLE_URI = "urn:agentenv:disable-tool/v1"
ENABLE_URI = "urn:agentenv:enable-tool/v1"
OVER = "the episode is over: the schedule was already submitted"
SCHEMAS = {s["function"]["name"]: s["function"] for s in tool_schemas("foresight", MAX_CHECKS, get_situation=True)}
TOOL_ORDER = list(SCHEMAS)

Actions = Annotated[Any, Field(description=SCHEMAS["submit_schedule"]["parameters"]["properties"]["actions"]
                               ["description"])]


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def pack_dirs() -> list[Path]:
    if spec := os.environ.get("GRIDSIM_TASKS_DIR"):
        return [Path(p) for p in spec.split(":") if p]
    return [data_root() / name for name in PACK_NAMES]


def read_pack(folder: Path) -> list[dict]:
    """A pack's task rows, or none when the pack isn't built."""
    if not (folder / "tasks.jsonl.gz").is_file():
        return []
    with gzip.open(folder / "tasks.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


class TaskIndex:
    """The packs' task rows by id, each pack read on the first lookup it could answer, in order: the train pack's
    rows are only read for a task the others don't hold."""

    def __init__(self, dirs: list[Path]):
        self.dirs, self.read, self.rows = list(dirs), 0, {}

    def get(self, task_id: str) -> dict | None:
        while task_id not in self.rows and self.read < len(self.dirs):
            for row in read_pack(self.dirs[self.read]):
                self.rows.setdefault(row["task_id"], row)
            self.read += 1
        return self.rows.get(task_id)


@environment_card(name="gridsim")
class GridSimEnv(AgentEnvEnvironment):
    def __init__(self):
        self.tasks = TaskIndex(pack_dirs())
        self.disabled: set[str] = set()
        self.reset()

    def create_app(self) -> FastMCP:
        return self.mount(FastMCP("gridsim", middleware=[Episode(self)]))

    @tool(description=SCHEMAS["get_situation"]["description"])
    def get_situation(self) -> str:
        return situation_text(self._require(), self.tier, self.checks)

    @tool(description=SCHEMAS["check_schedule"]["description"])
    def check_schedule(self, actions: Actions) -> str:
        task = self._require(open_only=True)
        if self.checks_used >= self.checks:
            return _json({"error": f"no checks left (you had {self.checks}); submit_schedule when ready"})
        self.checks_used += 1
        return _json(check_result(task, actions, self.checks - self.checks_used, self.tier))

    @tool(description=SCHEMAS["submit_schedule"]["description"])
    def submit_schedule(self, actions: Actions) -> str:
        return _json(self._submit(actions))

    @extension(LOAD_URI, description="Start an episode on a task: its id in the packs, or an explicit task row.")
    def load_task(self, task_id: str, tier: str = "foresight", checks: int = MAX_CHECKS,
                  task: dict | None = None) -> dict:
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}: one of {', '.join(TIERS)}")
        if isinstance(checks, bool) or not isinstance(checks, int) or not 0 <= checks <= MAX_CHECKS:
            raise ValueError(f"checks must be an integer from 0 to {MAX_CHECKS}, got {checks!r}")
        if task is not None:
            if task.get("task_id") != task_id:
                raise ValueError(f"the task row's id {task.get('task_id')!r} is not {task_id!r}")
            row = task
        elif (row := self.tasks.get(task_id)) is None:
            raise ValueError(f"unknown task id {task_id!r}")
        if tier == "blind" and not (row.get("blind") and (row.get("refs") or {}).get("blind")):
            raise ValueError(f"task {task_id!r} has no blind tier")
        self.reset()
        self.task, self.tier, self.checks = row, tier, checks
        return {"task_id": task_id, "tier": tier, "checks": checks}

    @extension(SUBMIT_URI, description="Submit a schedule as the submit_schedule tool does, outside the agent's "
                                       "tool calls.")
    def submit(self, actions: Any) -> dict:
        return self._submit(actions)

    @extension(DISABLE_URI, description="Hide tools from the agent.")
    def disable(self, role: str, tools: list[str]) -> dict:
        self.disabled |= set(tools)
        return self._access()

    @extension(ENABLE_URI, description="Show hidden tools to the agent again.")
    def enable(self, role: str, tools: list[str]) -> dict:
        self.disabled -= set(tools)
        return self._access()

    @reset_data
    def reset(self) -> None:
        self.task: dict | None = None
        self.tier = "foresight"
        self.checks = MAX_CHECKS
        self.checks_used = 0
        self.calls_used = 0
        self.done = False
        self.end_reason: str | None = None
        self.schedule: list[int] | None = None
        self.grade: dict | None = None
        self.reward: float | None = None

    @get_data
    def get(self) -> list[DataPart]:
        return [DataPart(data={"task_id": self.task["task_id"] if self.task else None, "tier": self.tier,
                               "checks": self.checks, "checks_used": self.checks_used, "calls_used": self.calls_used,
                               "done": self.done, "end_reason": self.end_reason, "schedule": self.schedule,
                               "grade": self.grade, "reward": self.reward,
                               "task": self.task if self.done else None})]

    def count_call(self) -> None:
        self.calls_used += 1
        if self.calls_used >= MAX_TOOL_CALLS and not self.done:
            self.done, self.end_reason, self.reward = True, "tool_call_limit", 0.0

    def _access(self) -> dict:
        return {"disabled": sorted(self.disabled), "allowed": [t for t in TOOL_ORDER if t not in self.disabled]}

    def _require(self, open_only: bool = False) -> dict:
        if self.task is None:
            raise ValueError("no episode: load a task first")
        if open_only and self.done:
            raise ValueError(OVER)
        return self.task

    def _submit(self, actions) -> dict:
        task = self._require(open_only=True)
        out = submit_result(task, actions)
        if out["submitted"]:
            self.grade = grade(task, actions, self.tier)
            self.done, self.end_reason, self.schedule = True, "submitted", parse_actions(actions)
            self.reward = float(self.grade["reward"])
        return out


class Episode(Middleware):
    """Counts every tools/call, including those that fail validation, name no tool or name a hidden one; lists the
    tools in gridsim_core's order, with its descriptions and input schemas, without the hidden ones."""

    def __init__(self, env: GridSimEnv):
        self.env = env

    async def on_call_tool(self, context, call_next):
        try:
            if context.message.name in self.env.disabled:
                raise NotFoundError(f"Unknown tool: {context.message.name!r}")
            return await call_next(context)
        finally:
            self.env.count_call()

    async def on_list_tools(self, context, call_next):
        tools = {t.name: t for t in await call_next(context) if t.name not in self.env.disabled}
        return [tools[name].model_copy(update={"description": SCHEMAS[name]["description"],
                                               "parameters": SCHEMAS[name]["parameters"]})
                for name in TOOL_ORDER if name in tools]


def main() -> None:
    GridSimEnv().create_app().run(transport="http", host=os.environ.get("MCP_HOST", "0.0.0.0"),
                                  port=int(os.environ.get("MCP_PORT", "18765")), show_banner=False)


if __name__ == "__main__":
    main()
