"""The hybrid fixture days, a scripted policy's calls watch by watch, and the Session they play on."""

import json

from agentenv_gridsim import hybrid_tasks
from gridsim_core.hybrid import Session

ROWS = hybrid_tasks.pack_rows("fixtures-hybrid")
assert ROWS, "no hybrid fixture days in data/fixtures-hybrid"
DAY = next(r for r in ROWS if r.get("deployments") and not r["tags"].get("showcase")
           and hybrid_tasks.eligible([r], "reserves"))


def scripted(task: dict, tier: str, policy) -> list[list[tuple[str, dict]]]:
    """One list of calls per watch: what ``policy`` (a gridsim_core.hybrid policy) calls at the watch, then advance,
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
