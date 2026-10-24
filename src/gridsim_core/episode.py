"""Tool outputs and the gridsim.episode/v1 record shared by the plugin (path A) and training (path B)."""

from __future__ import annotations

import hashlib
import json

from gridsim_core.grade import foresight_refs, grade
from gridsim_core.parse import ParseError, parse_actions
from gridsim_core.physics import simulate
from gridsim_core.prompt import situation

SCHEMA = "gridsim.episode/v1"


def check_result(task: dict, actions, checks_left: int, tier: str = "foresight") -> dict:
    """check_schedule output; the blind tier never shows profit (it would leak today's prices)."""
    try:
        sim = simulate(task, actions)
    except ParseError as e:
        return {"error": str(e), "checks_left": checks_left}
    return {"feasible": sim["feasible"], "truncated_at": sim["truncated_at"], "violation": sim["violation"],
            "soc_path": sim["soc_path"], "end_shortfall_units": sim["end_shortfall_units"],
            "profit_usd": round(sim["profit_usd"], 2) if tier == "foresight" else None, "checks_left": checks_left}


def submit_result(task: dict, actions) -> dict:
    """submit_schedule output: profit and feasibility only, never the reward or a reference."""
    try:
        sim = simulate(task, actions)
    except ParseError as e:
        return {"submitted": False, "error": str(e)}
    return {"submitted": True, "feasible": sim["feasible"], "truncated_at": sim["truncated_at"],
            "violation": sim["violation"], "soc_path": sim["soc_path"], "profit_usd": round(sim["profit_usd"], 2)}


def to_episode_json(task: dict, actions, tier: str = "foresight", checks: int = 0, *, steps: list | None = None,
                    bundle: str = "train", path: str = "B", model: str | None = None, trained: str | None = None,
                    checkpoint_step: int | None = None, seed: int | None = None, messages: list | None = None,
                    usage: dict | None = None, wall_seconds: float | None = None,
                    episode_id: str | None = None) -> dict:
    """A gridsim.episode/v1 dict; without steps it synthesizes the single submit_schedule call."""
    g = grade(task, actions, tier)
    try:
        acts = parse_actions(actions)
    except ParseError:
        acts = None
    if steps is None:
        steps = [{"t": 0, "tool": "submit_schedule", "args": {"actions": actions}, "output": submit_result(task, actions)}]
    sim = simulate(task, acts) if acts is not None else None
    f, refs = foresight_refs(task), task.get("refs") or {}
    fb = f.get("baselines", {})
    eid = episode_id or hashlib.sha256(json.dumps(
        [task["task_id"], tier, bundle, path, model, trained, checkpoint_step, seed, acts]).encode()).hexdigest()[:16]
    hourly = None
    if sim:
        hourly = [{"he": h + 1, "price": task["prices"][h], "action": sim["executed"][h], "mwh": round(sim["mwh"][h], 6),
                   "cash": round(sim["cashflow"][h], 6),
                   "degradation": round(task["battery"]["c_deg"] * task["battery"]["unit_mwh"]
                                        * max(sim["executed"][h], 0), 6),
                   "soc": sim["soc_path"][h + 1]} for h in range(len(acts))]
    return {"schema": SCHEMA, "episode_id": eid, "env": "gridsim", "version": "v1", "task_id": task["task_id"],
            "tier": tier, "bundle": bundle, "path": path, "model": model, "trained": trained,
            "checkpoint_step": checkpoint_step, "seed": seed, "situation": situation(task, tier, checks),
            "task": {k: task.get(k) for k in ("date", "settlement_point", "point_kind", "region", "battery", "prices",
                                              "blind")},
            "steps": steps, "final_schedule": acts, "soc_path": sim["soc_path"] if sim else None, "hourly": hourly,
            "truncated_at": g.get("truncated_at"), "violation": g.get("violation"),
            "end_shortfall_units": g.get("end_shortfall_units"),
            "profit_usd": round(g["profit"], 6) if g["submitted"] else None, "reward": g["reward"],
            "r_opt": g.get("r_opt", 0.0),
            "references": {"p_opt": f["p_opt"], "p_idle": f["p_idle"], "p_lp": f.get("p_lp"), "opt": f["opt"],
                           "greedy": fb.get("greedy"), "threshold": fb.get("threshold"), "clock": fb.get("clock"),
                           "blind": refs.get("blind")},
            "messages": messages or [], "usage": usage, "wall_seconds": wall_seconds}
