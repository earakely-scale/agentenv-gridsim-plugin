"""The market fixture floors, scripted policies' calls watch by watch, the Session they play on, and the gridsim-market
bundle's tasks: which floor and tier each plays, and the wiring tasks' harness calls."""

import json

from agentenv_gridsim import market_tasks
from gridsim_core.market import Session, anchor_policy
from gridsim_core.market_refs import replay_a

ROWS = market_tasks.pack_rows("fixtures-market")
assert ROWS, "no market fixture floors in data/fixtures-market"
BY_ID = {r["task_id"]: r for r in ROWS}
SPRINT = BY_ID["mkt-v5-2024-08-20-A580x2-e1"]
DAY = BY_ID["mkt-v5-2026-07-21-A1160x2-e1"]
SHOWCASE = {(f"fern-{r['date'][5:7]}{r['date'][8:]}" if r["tags"]["showcase"] == "fern-0123"
             else r["tags"]["showcase"]): r for r in market_tasks.pack_rows("gridsim-market-showcase")}
"""The contract's showcase floors by bundle task: aug24-0820, and fern-0123 to fern-0127 for each day of fern-0123."""
IDLE = {"hours": []}


def anchor_offer(task: dict) -> dict:
    """The disclosure best-responder's self-schedule, as it submits it at D-1 09:00."""
    s = Session(task, "floor-sprint")
    [(_, args)] = anchor_policy(s)
    return json.loads(json.dumps(args["offer"]))


def replay_offer(task: dict) -> dict:
    """Seat A's real offers of the day snapped to its grid (the replay_A baseline) as an offer."""
    blocks = replay_a(Session(task, "floor-sprint").F)
    return {"hours": [{"he": h + 1, "sell": [[mw, p] for _, side, mw, p, _ in b if side > 0],
                       "buy": [[mw, p] for _, side, mw, p, _ in b if side < 0]} for h, b in enumerate(blocks) if b]}


def submit_at_nine(offer: dict):
    return lambda s: [("submit_offer", {"offer": offer})] if s.minute == -900 else []


def policies(task: dict) -> dict:
    return {"anchor": anchor_policy, "replay": submit_at_nine(replay_offer(task)), "idle": submit_at_nine(IDLE)}


def scripted(task: dict, tier: str, policy) -> list[list[tuple[str, dict]]]:
    """One list of calls per watch: what ``policy`` (session -> calls, as gridsim_core.market.play takes) calls at the
    watch, then advance unless the floor ended, then get_situation after each advance that opens a watch."""
    s, turns = Session(task, tier), []
    while not s.done:
        calls = [(t, json.loads(json.dumps(a))) for t, a in policy(s)]
        for t, a in calls:
            s.call(t, a)
        if not s.done:
            calls.append(("advance", {}))
            s.call("advance", {})
            s.deliver_watch_notices()
            if not s.done:
                s.call("get_situation", {})
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


def stored(task: dict, tier: str, policy: str) -> dict | None:
    """What the task row stores for the policy at the tier: its profit and reward (None where it stores nothing)."""
    refs = task["refs"]
    if policy == "anchor":
        return {"profit": refs[tier]["p_anchor"], "reward": 1.0}
    if policy == "idle":
        return {"profit": refs["p_idle"], "reward": 0.2}
    return refs["floor-sprint"]["baselines"]["replay_A"] if tier == "floor-sprint" else None


WIRING = {
    "wiring-late": (DAY, "floor-day", [("advance", {}), ("submit_offer", {"offer": anchor_offer(DAY)}),
                                       ("advance", {}), ("submit_offer", {"offer": IDLE})]),
    "wiring-disclosure": (SPRINT, "floor-sprint", [
        ("get_disclosure", {"op_date": "2024-06-21"}), ("get_disclosure", {"op_date": "2024-05-01"}),
        ("get_disclosure", {"op_date": "2024-06-20", "side": "demand", "hour": 18}),
        ("submit_offer", {"offer": IDLE})]),
}
BUNDLE = {
    "sprint": {"task": SPRINT, "tier": "floor-sprint"},
    "sprint-compliant": {"task": SPRINT, "tier": "floor-sprint", "compliant": True},
    "day": {"task": DAY, "tier": "floor-day"},
    **{name: {"task": task, "tier": "floor-day", "compliant": True} for name, task in sorted(SHOWCASE.items())},
    "wiring-noplay": {"task": DAY, "tier": "floor-day", "play": False},
    **{name: {"task": task, "tier": tier, "play": False, "calls": calls}
       for name, (task, tier, calls) in WIRING.items()},
}


def bundle_steps(name: str) -> list[dict]:
    """The bundle task ``name``'s steps as market_tasks writes them."""
    spec = dict(BUNDLE[name])
    task = spec.pop("task")
    return json.loads(json.dumps(market_tasks.steps(task, **spec)))
