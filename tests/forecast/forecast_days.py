"""The forecast fixture windows, a scripted policy's calls watch by watch, and the Session they play on."""

import json

from agentenv_gridsim import forecast_tasks
from gridsim_core.forecast import Session, anchor_policy

ROWS = forecast_tasks.pack_rows("fixtures-forecast")
assert ROWS, "no forecast fixture windows in data/fixtures-forecast"
WINDOW = next(r for r in ROWS if r["task_id"] == forecast_tasks.BUNDLE_WINDOW)


def anchor(tier: str):
    """The tier's anchor: the rolling MILP on the P50 guide, or on persistence at the blind tier."""
    return anchor_policy("persist" if tier == "blind" else "p50")


def scripted(task: dict, tier: str, policy) -> list[list[tuple[str, dict]]]:
    """One list of calls per watch: what ``policy`` (a gridsim_core.forecast policy) calls at the watch, then advance,
    then get_situation after each advance that opens a watch."""
    s, turns = Session(task, tier), []
    while not s.done:
        n = len(s.transcript)
        policy(s)
        calls = [(x["tool"], json.loads(json.dumps(x["args"]))) for x in s.transcript[n:]] + [("advance", {})]
        s.call("advance")
        s.deliver_watch_notices()
        if not s.done:
            s.call("get_situation")
            calls.append(("get_situation", {}))
        turns.append(calls)
    return turns


def in_process(task: dict, tier: str, calls: list) -> tuple[Session, list[str]]:
    """The calls on a Session, each watch's notices delivered after the advance that opens it, as the triggers do."""
    s, outs = Session(task, tier), []
    for name, args in (c for watch in calls for c in watch):
        outs.append(s.call(name, args))
        if name == "advance" and "watch" in json.loads(outs[-1]):
            s.deliver_watch_notices()
    return s, outs
