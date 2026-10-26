"""Path B shared pieces: the oneshot prompt (system + situation + submit_schedule tool schema through the chat
template), the tool-call extraction, grading and the error taxonomy."""

import json
import os
import re
import statistics

from gridsim_core.grade import grade
from gridsim_core.parse import parse_actions
from gridsim_core.prompt import messages, tool_schemas
from gridsim_core.trl import extract_actions

TIER, CHECKS = os.environ.get("TIER", "foresight"), 0
CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
KINDS = ("ok", "all_idle", "overfill", "sell_before_charge", "rate", "cycle_cap", "end_short", "malformed",
         "truncated")


def prompt_text(tok, task: dict) -> str:
    return tok.apply_chat_template(messages(task, TIER, CHECKS), tools=tool_schemas(TIER, CHECKS), tokenize=False,
                                   add_generation_prompt=True, enable_thinking=False)


def tool_call(text: str) -> bool:
    """A well-formed <tool_call> to submit_schedule with an actions argument (what path A's tool parser needs)."""
    m = CALL.search(text)
    if not m:
        return False
    try:
        call = json.loads(m.group(1))
    except json.JSONDecodeError:
        return False
    if not isinstance(call, dict):
        return False
    args = call.get("arguments")
    return call.get("name") == "submit_schedule" and isinstance(args, dict) and "actions" in args


def score(task: dict, text: str, truncated: bool = False) -> dict:
    """Reward = gridsim_core.trl.reward_fn exactly (its extract_actions, then grade); no format credit."""
    sent = extract_actions(text)
    call = tool_call(text)
    if sent is None:
        return {"reward": 0.0, "valid": False, "tool_call": call, "kind": "truncated" if truncated else "malformed",
                "actions": None, "grade": None}
    g = grade(task, sent, TIER)
    acts = parse_actions(sent)
    return {"reward": float(g["reward"]), "valid": True, "tool_call": call, "kind": kind_of(g, acts),
            "actions": acts, "args": sent, "grade": g}


def kind_of(g: dict, acts: list[int]) -> str:
    if not any(acts):
        return "all_idle"
    if g["violation"]:
        return {"soc_above_N": "overfill", "soc_below_0": "sell_before_charge"}.get(g["violation"], g["violation"])
    return "end_short" if g["end_shortfall_units"] else "ok"


def summarize(records: list[dict]) -> dict:
    """Mean R, valid/feasible rates and the error taxonomy over scored records."""
    n = len(records)
    if not n:
        return {"n": 0}
    rs = [r["reward"] for r in records]
    out = {"n": n, "reward_mean": round(statistics.fmean(rs), 4), "reward_std": round(statistics.pstdev(rs), 4),
           "valid_rate": round(sum(r["valid"] for r in records) / n, 4),
           "tool_call_rate": round(sum(r["tool_call"] for r in records) / n, 4),
           "feasible_rate": round(sum(r["valid"] and r["grade"]["feasible"] for r in records) / n, 4)}
    for k in KINDS:
        out[f"rate_{k}"] = round(sum(r["kind"] == k for r in records) / n, 4)
    if any("len" in r for r in records):
        out["completion_len_mean"] = round(statistics.fmean(r.get("len", 0) for r in records), 1)
    return out
