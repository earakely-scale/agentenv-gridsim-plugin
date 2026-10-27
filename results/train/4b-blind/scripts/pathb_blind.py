"""Path B for registered run 4 (blind tier, forecast-then-plan): the one prompt every model gets (the blind path-B
prompt plus gridsim_core.forecast's paragraph, one call, no checks), scoring with gridsim_core.trl's extraction and
grade, and the plan diagnostics on the model's own written forecast."""

import json
import re
import statistics

from gridsim_core.dp import dp_schedule
from gridsim_core.forecast import parse_forecast
from gridsim_core.grade import grade, reward_value
from gridsim_core.parse import parse_actions
from gridsim_core.physics import settle
from gridsim_core.prompt import messages, tool_schemas
from gridsim_core.task import battery_of
from gridsim_core.trl import extract_actions

TIER, CHECKS = "blind", 0
CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
KINDS = ("ok", "all_idle", "overfill", "sell_before_charge", "rate", "cycle_cap", "end_short", "malformed",
         "truncated")


def prompt_text(tok, task: dict) -> str:
    return tok.apply_chat_template(messages(task, TIER, CHECKS, forecast=True), tools=tool_schemas(TIER, CHECKS),
                                   tokenize=False, add_generation_prompt=True, enable_thinking=False)


def tool_call(text: str) -> bool:
    m = CALL.search(text)
    if not m:
        return False
    try:
        call = json.loads(m.group(1))
    except json.JSONDecodeError:
        return False
    args = call.get("arguments") if isinstance(call, dict) else None
    return call.get("name") == "submit_schedule" and isinstance(args, dict) and "actions" in args


def plan_diag(task: dict, acts: list[int], fc: list[float]) -> dict:
    """c_dp_own: C (on the day) of the DP plan on the model's own forecast; c_f: the schedule's capture on that
    forecast, clip(0.2 + 0.8 (P_F - P_F,idle) / (P_F,opt - P_F,idle)), where 1 means it is the forecast's DP plan."""
    b = battery_of(task)
    dp = dp_schedule(b, fc)
    p = {k: settle(b, fc, s)["profit_usd"] for k, s in (("own", acts), ("idle", [0] * 24), ("opt", dp))}
    return {"c_dp_own": grade(task, dp)["r_opt"], "c_f": reward_value(p["own"], p["idle"], p["opt"]),
            "is_dp_own": acts == dp}


def score(task: dict, text: str, truncated: bool = False) -> dict:
    """C = r_opt of the submitted schedule and R on the blind anchor's scale (None for a train day without blind
    refs); both 0 for no valid submission (no format credit)."""
    return graded(task, extract_actions(text), parse_forecast(text), tool_call(text), truncated)


def graded(task: dict, sent, fc: list[float] | None, call: bool, truncated: bool = False) -> dict:
    base = {"forecast": fc, "tool_call": call}
    if sent is None:
        return base | {"reward": 0.0, "c": 0.0, "valid": False, "kind": "truncated" if truncated else "malformed",
                       "actions": None, "grade": None}
    blind = bool((task.get("refs") or {}).get("blind"))
    g = grade(task, sent, TIER if blind else "foresight")
    acts = parse_actions(sent)
    out = base | {"reward": float(g["reward"]) if blind else None, "c": float(g["r_opt"]), "valid": True,
                  "kind": kind_of(g, acts), "actions": acts, "args": sent, "grade": g}
    return out | (plan_diag(task, acts, fc) if fc is not None else {})


def kind_of(g: dict, acts: list[int]) -> str:
    if not any(acts):
        return "all_idle"
    if g["violation"]:
        return {"soc_above_N": "overfill", "soc_below_0": "sell_before_charge"}.get(g["violation"], g["violation"])
    return "end_short" if g["end_shortfall_units"] else "ok"


def summarize(records: list[dict]) -> dict:
    n = len(records)
    if not n:
        return {"n": 0}
    out = {"n": n, "c_mean": round(statistics.fmean(r["c"] for r in records), 4),
           "reward_mean": round(statistics.fmean(r["reward"] or 0.0 for r in records), 4),
           "valid_rate": round(sum(r["valid"] for r in records) / n, 4),
           "tool_call_rate": round(sum(r["tool_call"] for r in records) / n, 4),
           "forecast_rate": round(sum(r["forecast"] is not None for r in records) / n, 4),
           "feasible_rate": round(sum(r["valid"] and r["grade"]["feasible"] for r in records) / n, 4)}
    fc = [r for r in records if "c_f" in r]
    if fc:
        out |= {"c_f_mean": round(statistics.fmean(r["c_f"] for r in fc), 4),
                "c_dp_own_mean": round(statistics.fmean(r["c_dp_own"] for r in fc), 4),
                "is_dp_own_rate": round(sum(r["is_dp_own"] for r in fc) / n, 4)}
    for k in KINDS:
        out[f"rate_{k}"] = round(sum(r["kind"] == k for r in records) / n, 4)
    if any("len" in r for r in records):
        out["completion_len_mean"] = round(statistics.fmean(r.get("len", 0) for r in records), 1)
    return out
