"""The exact text, situation JSON and tool schemas the agent sees; path A (plugin) and path B (training) share them."""

from __future__ import annotations

import json

from gridsim_core.contract import P_FLOOR
from gridsim_core.forecast import FORECAST_NOTE

BATTERY_KEYS = ("p_dis_mw", "p_ch_mw", "energy_mwh", "unit_mwh", "k_dis", "k_ch", "soc_levels", "eta", "c_deg",
                "cycle_cap_units", "s0", "s_end_min")

_INTRO = """You operate a grid battery in the ERCOT day-ahead market (DAM) for one operating day: 24 hours, HE01..HE24 \
(hour ending, Central Prevailing Time). You are a price taker: what you sell or buy in an hour settles at that hour's \
DAM price in $/MWh."""

_SEE = {
    "foresight": "The situation JSON gives the battery and today's 24 prices (prices_usd_per_mwh).",
    "blind": """You do not see today's prices. The situation JSON gives the battery and the DAM prices at this point \
for the previous day (dam_prev_day_usd_per_mwh) and the previous 7 days (dam_prev_7d_usd_per_mwh, oldest first). \
Your schedule settles at today's actual prices.""",
}

_RULES = f"""Units and sign
- Energy moves in whole units of unit_mwh MWh. State of charge (SoC) is counted in units from 0 to soc_levels and \
starts at s0.
- Each hour you choose one integer a. a > 0 discharges a units: you sell a*unit_mwh MWh. a < 0 charges -a units: \
you buy -a*unit_mwh/eta MWh (losses are on the buy side). a = 0 is idle.
- SoC after the hour = SoC before - a.
- Hourly cash = price * MWh sold (MWh bought count as negative) - c_deg * unit_mwh * a when a > 0. A negative price \
pays you to buy.

Rules
1. -k_ch <= a <= k_dis.
2. 0 <= SoC <= soc_levels after every hour.
3. Discharged units summed over the day <= cycle_cap_units.
4. At the first hour that breaks rule 1, 2 or 3, that hour and every later hour execute as 0.
5. End obligation: SoC after HE24 must be at least s_end_min. Each missing unit is bought back: unit_mwh/eta MWh \
at max(the day's highest price, ${P_FLOOR:.0f}/MWh).

Profit = the sum of hourly cash - the end penalty. Make it as large as you can."""

_ACTIONS = "actions is a list of exactly 24 integers, HE01 first, for example [0, -2, -2, 0, ..., 3, 3, 0]."


def system_prompt(task: dict, tier: str = "foresight", checks: int = 3, forecast: bool = False) -> str:
    """The system prompt for a tier and a check budget (the text does not depend on the task's numbers); forecast
    adds the blind tier's forecast-first paragraph (forecast-then-plan)."""
    if forecast and tier != "blind":
        raise ValueError("the forecast-first paragraph is for the blind tier")
    tools = ["Tools"]
    if checks:
        what = "feasibility, the SoC path, any end shortfall" + (" and the profit" if tier == "foresight" else
                                                                     " (not the profit: today's prices stay hidden)")
        tools.append(f"- check_schedule(actions): simulates a schedule without submitting it and returns {what}. "
                     f"You have {checks} check{'s' if checks != 1 else ''}.")
    tools.append("- submit_schedule(actions): submits your final schedule and ends the episode. You submit once.")
    tools.append(_ACTIONS)
    tools.append("Finish by calling submit_schedule.")
    return "\n\n".join([_INTRO + " " + _SEE[tier], _RULES, "\n".join(tools)] + ([FORECAST_NOTE] if forecast else []))


def situation(task: dict, tier: str = "foresight", checks: int = 3) -> dict:
    """The situation JSON: identity, battery, and today's prices (foresight) or the lagged prices (blind)."""
    out = {"task_id": task["task_id"], "tier": tier, "market": "ERCOT DAM", "date": task["date"],
           "settlement_point": task["settlement_point"], "point_kind": task["point_kind"],
           "hours": "HE01..HE24 CPT", "battery": {k: task["battery"][k] for k in BATTERY_KEYS},
           "shortfall_price_floor_usd_per_mwh": P_FLOOR, "checks": checks}
    if tier == "blind":
        out["dam_prev_day_usd_per_mwh"] = _round(task["blind"]["dam_prev_day"])
        out["dam_prev_7d_usd_per_mwh"] = [_round(d) for d in task["blind"]["dam_prev_7d"]]
    else:
        out["prices_usd_per_mwh"] = _round(task["prices"])
    return out


def situation_text(task: dict, tier: str = "foresight", checks: int = 3) -> str:
    """The situation as the exact string the agent reads (get_situation output and the path-B user turn)."""
    return json.dumps(situation(task, tier, checks), separators=(", ", ": "))


def messages(task: dict, tier: str = "foresight", checks: int = 0, forecast: bool = False) -> list[dict]:
    """[system, user] chat messages for a one-shot episode (path B and the oneshot bundle)."""
    return [{"role": "system", "content": system_prompt(task, tier, checks, forecast)},
            {"role": "user", "content": situation_text(task, tier, checks)}]


def tool_schemas(tier: str = "foresight", checks: int = 3, get_situation: bool = False) -> list[dict]:
    """OpenAI-style function schemas for the tools offered in this configuration."""
    actions = {"type": "object", "required": ["actions"], "properties": {"actions": {
        "type": "array", "items": {"type": "integer"}, "minItems": 24, "maxItems": 24,
        "description": "24 integers for HE01..HE24: a > 0 discharges (sells) a units, a < 0 charges (buys) -a units."}}}
    out = []
    if get_situation:
        out.append(_fn("get_situation", "Return the situation JSON: the battery and the prices you may see.",
                       {"type": "object", "properties": {}}))
    if checks:
        out.append(_fn("check_schedule", "Simulate a schedule without submitting it. Uses one check.", actions))
    out.append(_fn("submit_schedule", "Submit the final 24-hour schedule. This ends the episode.", actions))
    return out


def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


def _round(xs) -> list[float]:
    return [round(float(x), 2) for x in xs]
