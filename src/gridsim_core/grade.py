"""The one reward contract: R = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1), rounded to 6 decimals."""

from __future__ import annotations

from gridsim_core import baselines
from gridsim_core.contract import DEGENERATE_EPS
from gridsim_core.dp import solve_dp
from gridsim_core.lp import lp_bound
from gridsim_core.parse import ParseError, parse_actions
from gridsim_core.physics import simulate
from gridsim_core.task import stable_seed


def reward_value(p: float, p_idle: float, p_anchor: float) -> float:
    """The contract reward; a degenerate anchor (no headroom over idle) pays 1 for matching it, else 0."""
    den = p_anchor - p_idle
    if den <= DEGENERATE_EPS:
        return 1.0 if p >= p_anchor - 1e-6 else 0.0
    return round(min(1.0, max(0.0, 0.2 + 0.8 * (p - p_idle) / den)), 6)


def stretch_value(p: float, p_idle: float, p_anchor: float, p_hind: float | None) -> float:
    """The training reward S: R up to the anchor, then rising linearly to 1.2 at hindsight; S = R where the anchor is
    the hindsight (v1 foresight, v3 oneshot) or no hindsight is stored."""
    if p_hind is not None and p > p_anchor + DEGENERATE_EPS and p_hind - p_anchor > DEGENERATE_EPS:
        return round(min(1.2, 1 + 0.2 * (p - p_anchor) / (p_hind - p_anchor)), 6)
    return reward_value(p, p_idle, p_anchor)


def foresight_refs(task: dict) -> dict:
    """The task's stored foresight refs, or {p_idle, p_opt, opt} computed now."""
    f = (task.get("refs") or {}).get("foresight")
    if f:
        return f
    p_opt, opt = solve_dp(task)
    return {"p_idle": simulate(task, baselines.idle(task))["profit_usd"], "p_opt": p_opt, "opt": opt}


def grade(task: dict, actions, tier: str = "foresight") -> dict:
    """Grade a submission against the tier's anchor; unparseable input is not a submission."""
    try:
        acts = parse_actions(actions)
    except ParseError as e:
        return {"submitted": False, "tier": tier, "reward": 0.0, "error": str(e)}
    sim, f = simulate(task, acts), foresight_refs(task)
    p, p_idle, p_opt = sim["profit_usd"], f["p_idle"], f["p_opt"]
    if tier == "blind" and not (task.get("refs") or {}).get("blind"):
        raise ValueError(f"{task.get('task_id')} has no blind refs; it is not a blind-tier task")
    anchor = task["refs"]["blind"]["p_anchor"] if tier == "blind" else p_opt
    out = {"submitted": True, "tier": tier, "reward": reward_value(p, p_idle, anchor),
           "r_opt": reward_value(p, p_idle, p_opt), "profit": p, "profit_idle": p_idle, "profit_anchor": anchor,
           "profit_opt": p_opt, "feasible": sim["feasible"], "truncated_at": sim["truncated_at"],
           "violation": sim["violation"], "end_shortfall_units": sim["end_shortfall_units"]}
    if tier == "blind":
        out["beats_anchor"] = p > anchor + DEGENERATE_EPS
    return out


def references(task: dict, ridge: dict | None = None, seed: int | None = None, lp: bool = True) -> dict:
    """The refs block of a task row: foresight always, blind when the task has blind inputs and a ridge model."""
    p_opt, opt = solve_dp(task)
    p_opt, p_idle = _r(p_opt), _r(simulate(task, baselines.idle(task))["profit_usd"])
    seed = stable_seed(task["task_id"]) if seed is None else seed
    scheds = {"clock": baselines.clock(task), "threshold": baselines.threshold(task),
              "greedy": baselines.greedy(task), "random": baselines.random_feasible(task, seed)}
    out = {"foresight": {"p_idle": p_idle, "p_opt": p_opt, "opt": opt,
                         "p_lp": _r(lp_bound(task)) if lp else None,
                         "baselines": {k: _entry(task, s, p_idle, p_opt) for k, s in scheds.items()}},
           "blind": None}
    if task.get("blind") and ridge is not None:
        persist, ridge_s = baselines.persistence_dp(task), baselines.ridge_dp(task, ridge)
        p_persist, p_ridge = simulate(task, persist)["profit_usd"], simulate(task, ridge_s)["profit_usd"]
        anchor = _r(max(p_persist, p_ridge))
        out["blind"] = {"p_persist": _r(p_persist), "persist": persist, "p_ridge": _r(p_ridge), "ridge": ridge_s,
                        "p_anchor": anchor, "r_opt_anchor": reward_value(anchor, p_idle, p_opt)}
    return out


def _entry(task: dict, sched: list[int], p_idle: float, p_opt: float) -> dict:
    p = simulate(task, sched)["profit_usd"]
    return {"profit": _r(p), "reward": reward_value(p, p_idle, p_opt), "schedule": sched}


def _r(x: float | None) -> float | None:
    return None if x is None else round(x, 6)
