"""The GridSim desk's post-turn hook: after each agent turn, run the desk to its next wake-up on the env's frozen clock
and wake the agent with the desk's wake message (desk contract 2.3-2.4).

It reads the desk's own next wake-up through the hidden next_wakeup tool (as the hook role), takes the earlier of it and
the gateway triggers' next_event_at, advances the gateway clock there, lets any trigger that came due settle, and has
the desk run the market to that minute through the hidden advance_to tool. A minute that wakes nobody is passed over;
the first that wakes the agent returns its message. When the desk has no wake-up left the episode is over and the
conversation ends. After the conversation's last turn it still runs the market to the end, so the episode is graded
whole. Based on the framework's next-env-event example.

Params, all optional: env_id (the desk env, when the task deploys more than one), role (the role its hidden tools are
shown to, "hook" by default), settle_timeout_seconds (300)."""

import asyncio
import json
import logging
import math
import time
from datetime import UTC, datetime, timedelta

CLOCK = "urn:agentenv:clock/v1"
TRIGGERS = "urn:agentenv:triggers/v1"
IN_FLIGHT = ("firing", "queued")
PARAMS = ("env_id", "role", "settle_timeout_seconds")
POLL_SECONDS = 0.5

logger = logging.getLogger(__name__)


async def post_turn(turn, params):
    env_id, role, timeout = _params(params)
    env = _desk(turn, env_id)
    reply, passed = {"reply": turn.agent_reply}, []
    while True:
        nxt = await _tool(env, "next_wakeup", role)
        if nxt["at"] is None:
            if not nxt["done"]:
                await _advance(env, _utc(nxt["end_utc"]))
                await _tool(env, "advance_to", role, {"minute": nxt["end"], **reply})
            turn.record({"end": "episode_over", "passed": passed})
            return None if turn.last else {"end": "episode_over"}
        desk_at = _utc(nxt["at_utc"])
        gateway_at = await _gateway_next(env)
        target = min(desk_at, gateway_at) if gateway_at is not None else desk_at
        minute = nxt["at"] - round((desk_at - target).total_seconds() / 60)
        await _advance(env, target)
        settled = await _settle(turn, env, timeout)
        out = await _tool(env, "advance_to", role, {"minute": minute, **reply})
        reply = {}
        entry = {"at": _iso(target), "minute": minute, "desk_next": nxt["reasons"],
                 "gateway_next_event_at": None if gateway_at is None else _iso(gateway_at), "settled": settled}
        if out["wake"] is None or turn.last:
            passed.append(entry | {"reasons": None if out["wake"] is None else out["wake"]["reasons"]})
            continue
        turn.record(entry | {"reasons": out["wake"]["reasons"], "passed": passed,
                             "turns_left": out["wake"]["budget"]["turns_left"]})
        return {"message": out["message"]}


async def _advance(env, target):
    clock = await env.invoke(CLOCK, "state")
    if _utc(clock["virtual_time"]) < target:
        await env.invoke(CLOCK, "advance", {"virtual_time": _iso(target)})


def _params(params):
    unknown = sorted(set(params) - set(PARAMS))
    if unknown:
        raise ValueError(f"gridsim-desk-hook takes {list(PARAMS)}, not {unknown}")
    timeout = params.get("settle_timeout_seconds", 300)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise ValueError(f"settle_timeout_seconds must be a positive number, got {timeout!r}")
    role = params.get("role", "hook")
    if not isinstance(role, str) or not role:
        raise ValueError(f"role must be a non-empty string, got {role!r}")
    return params.get("env_id"), role, timeout


def _desk(turn, env_id):
    envs = [env for env in turn.envs if env_id in (None, env.env_id) and env.supports(CLOCK, "advance")]
    if len(envs) != 1:
        raise RuntimeError(f"gridsim-desk-hook needs one desk env with clock advance; found "
                           f"{[e.env_id for e in envs]} (set env_id)")
    return envs[0]


async def _tool(env, name, role, args=None):
    """A hidden desk tool's JSON output, called as ``role`` through the gateway's /step."""
    result = await env.call_tool(name, args or {}, role)
    content = result.get("content") or []
    body = "".join(c.get("text", "") for c in content if c.get("type") == "text")
    if result.get("isError") or result.get("error"):
        raise RuntimeError(f"{env.env_id}: {name} failed: {result.get('error') or body}")
    return json.loads(body)


async def _gateway_next(env):
    """The gateway triggers' next_event_at rounded up to the minute, or None."""
    if not env.supports(TRIGGERS, "state"):
        return None
    at = (await env.invoke(TRIGGERS, "state")).get("next_event_at")
    if at is None:
        return None
    t = _utc(at)
    return t.replace(second=0, microsecond=0) + timedelta(minutes=math.ceil((t.second + t.microsecond / 1e6) / 60))


async def _settle(turn, env, timeout):
    """Wait until no gateway trigger still fires, bar one waiting for later; whether it settled in time."""
    if not env.supports(TRIGGERS, "state"):
        return True
    deadline = time.monotonic() + timeout
    while True:
        clock, state = await env.invoke(CLOCK, "state"), await env.invoke(TRIGGERS, "state")
        now = _utc(clock["virtual_time"])
        if state.get("next_event_at") is not None and _utc(state["next_event_at"]) <= now:
            await env.invoke(CLOCK, "advance", {"virtual_time": _iso(now)})
        elif not any(_busy(row, now) for row in state.get("triggers", [])):
            return True
        if time.monotonic() >= deadline:
            logger.warning(f"env {env.env_id} still had triggers firing {timeout}s on; running the desk anyway")
            return False
        turn.heartbeat()
        await asyncio.sleep(POLL_SECONDS)


def _busy(row, now):
    if row.get("evaluating"):
        return True
    if row["status"] not in IN_FLIGHT and not row.get("pending"):
        return False
    return not (row.get("waiting") and row.get("resumes_at") and _utc(row["resumes_at"]) > now)


def _utc(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def _iso(value):
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
