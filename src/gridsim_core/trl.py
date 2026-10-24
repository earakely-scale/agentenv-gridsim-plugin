"""TRL reward entry: parse the submit_schedule call from a completion and grade it."""

from __future__ import annotations

import json
import re
from functools import lru_cache

from gridsim_core.grade import grade
from gridsim_core.parse import ParseError, parse_actions
from gridsim_core.task import data_root, load_pack

_TOOL_CALL = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.DOTALL)
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.DOTALL)
_LIST = re.compile(r"\[[^\[\]]*\]")


def reward_fn(prompts, completions, task=None, tier=None, task_id=None, **kw) -> list[float]:
    """TRL reward_funcs entry: one reward per completion; task is a dataset column of dicts, JSON or task ids."""
    tasks = task if task is not None else task_id
    out = []
    for i, completion in enumerate(completions):
        t = _task(tasks[i] if isinstance(tasks, (list, tuple)) else tasks)
        tr = (tier[i] if isinstance(tier, (list, tuple)) else tier) or "foresight"
        acts = extract_actions(completion)
        out.append(0.0 if acts is None else grade(t, acts, tr)["reward"])
    return out


def extract_actions(completion):
    """Actions of the first parseable submit_schedule call; a bare 24-int list only when there is no tool call."""
    text, calls = _flatten(completion)
    text = _THINK.sub("", text)
    for m in _TOOL_CALL.finditer(text):
        try:
            calls.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            calls.append(None)
    found = False
    for c in calls:
        name, args = _name_args(c)
        if name != "submit_schedule":
            continue
        found = True
        acts = args.get("actions") if isinstance(args, dict) else args
        if _ok(acts):
            return acts
    if found or calls:
        return None
    for m in reversed(list(_LIST.finditer(text))):
        try:
            acts = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        if _ok(acts):
            return acts
    return None


def _flatten(completion) -> tuple[str, list]:
    """(assistant text, structured tool calls) from a string, a message or a list of messages."""
    if isinstance(completion, str):
        return completion, []
    msgs = [completion] if isinstance(completion, dict) else list(completion)
    texts, calls = [], []
    for m in msgs:
        if m.get("role", "assistant") != "assistant":
            continue
        c = m.get("content") or ""
        texts.append(c if isinstance(c, str) else "".join(p.get("text", "") for p in c if isinstance(p, dict)))
        calls.extend(m.get("tool_calls") or [])
    return "\n".join(texts), calls


def _name_args(call) -> tuple[str | None, object]:
    if not isinstance(call, dict):
        return None, None
    fn = call.get("function", call)
    args = fn.get("arguments", fn.get("parameters"))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            pass
    return fn.get("name"), args


def _ok(acts) -> bool:
    try:
        parse_actions(acts)
        return True
    except ParseError:
        return False


def _task(t) -> dict:
    if isinstance(t, dict):
        return t
    if isinstance(t, str) and t.lstrip().startswith("{"):
        return json.loads(t)
    return _all_tasks()[t]


@lru_cache(maxsize=1)
def _all_tasks() -> dict[str, dict]:
    out = {}
    for p in sorted(data_root().glob("*/tasks.jsonl.gz")):
        out.update({t["task_id"]: t for t in load_pack(p)})
    return out
