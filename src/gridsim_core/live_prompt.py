"""The v2 live day's system prompt, opening message, per-watch note and tool schemas; the gridsim-live env and path B'
training share them, so the agent reads the same text on both paths."""

from __future__ import annotations

import json

from gridsim_core.contract import P_FLOOR
from gridsim_core.live import FREEZE_MIN, INTERVALS, PLANNING_CALLS, Session, hhmm

_JOB = """You run one grid battery at an ERCOT settlement point for one operating day (D), live, on a virtual clock. \
Times are Central Prevailing Time (CPT). ERCOT settles you twice: a day-ahead (DA) position at DA prices, and every \
deviation from it at 15-minute real-time (RT) prices. You are a price taker."""

_WHEN = {
    "foresight": "Watch 0 is D-1 14:00, after the day-ahead market (DAM) results post: you see D's 24 hourly DA prices.",
    "blind": """Watch 0 is D-1 14:00, but you choose the DA position before seeing D's DA prices: the situation gives \
the DAM prices at this point for D-1 and D-7..D-1. D's DA prices appear at the 00:00 watch.""",
}

_PLAY = f"""How the day runs
- At watch 0 you commit a DA position once (commit_da) and a physical schedule for D's 96 fifteen-minute intervals \
(00:00..23:45).
- Then the day plays in watches: D 00:00, 06:00, 12:00, 18:00, plus a watch when ERCOT or the weather service issues \
a notice.
- At every watch: read the situation (settled RT prices, notices, SoC), re-plan if it helps with up to \
{PLANNING_CALLS} planning calls, then call advance, which runs your schedule to the next watch. The day goes on until \
advance returns "done": true, so never stop early: keep going watch by watch.
- An RT price is revealed only after its interval ends (advance returns the settled intervals). Nothing moves while \
you think.
- Notices arrive in "messages" of your next tool result after advance. ERCOT notices change no physics; a derate \
lowers the battery's limits for a window (see "limits").
- After the last watch, advance runs the rest of the day and ends it."""

_UNITS = """Units and sign (per 15-minute interval)
- Energy moves in whole units of unit_mwh MWh. SoC is counted in units from 0 to soc_levels and starts at s0.
- Each interval you choose an integer a. a > 0 discharges a units: you sell a*unit_mwh MWh. a < 0 charges -a units: \
you buy -a*unit_mwh/eta MWh (losses are on the buy side). a = 0 is idle. SoC after the interval = SoC before - a.
- Rules: -k_ch <= a <= k_dis (lower inside a derate's window); 0 <= SoC <= soc_levels; discharged units over the \
day <= cycle_cap_units; SoC at 24:00 >= s_end_min. A commit that breaks a rule is refused whole."""

_SETTLE = f"""DA position and settlement
- The DA position is 24 integers, one per hour (HE01..HE24); hour h's value d counts as d in each of its four \
intervals, and it must itself keep every rule from s0. Its DA MWh (4 intervals' worth, losses on the buy side) settle \
at the hour's DA price. With no DA position you are all real time. Until your first commit_schedule, the battery \
follows your DA position.
- Each interval's physical MWh minus a quarter of its hour's DA MWh settles at the interval's RT price: selling more \
than your position earns RT, selling less buys it back at RT. The DA position is financial only; SoC follows the \
physical schedule.
- Degradation costs c_deg * unit_mwh per discharged unit. Each unit short of s_end_min at 24:00 is bought back: \
unit_mwh/eta MWh at max(the day's highest DA price, ${P_FLOOR:.0f}/MWh).
- Profit = DA settlement + RT deviation settlement - degradation - shortfall. Prices can be negative (charging then \
earns money) or spike to the cap. Make profit as large as you can."""


def _freeze(tier: str) -> str:
    h = FREEZE_MIN[tier] // 60
    return f"""The freeze and planning calls
- At each watch the freeze line is the next full hour plus {h} hour{'s' if h != 1 else ''}. Intervals that start \
before it are frozen at what you committed; you can change only intervals at or after it. Ended intervals are history.
- commit_da, check_schedule and commit_schedule share {PLANNING_CALLS} planning calls per watch (unused ones do not \
carry over); get_situation and advance are free."""


_TOOLS = """Tools
- get_situation(): the full state as JSON: time, freeze line, battery, SoC, DA prices and position, settled RT prices, \
your schedule (status E executed, F frozen, O open), P&L so far and every notice.
- commit_da(position): 24 integers, HE01 first. Watch 0 only, accepted once.
- check_schedule(actions, start, step): a dry run of your schedule from start ("HH:MM") to 24:00: feasibility, \
refusals, the SoC path and the day's P&L with unsettled intervals at DA prices. Commits nothing.
- commit_schedule(actions, start, step): replaces your schedule from start to 24:00, all or nothing.
- advance(): ends this watch.
- get_time(), if offered, reads the same virtual clock in UTC; the GridSim tools take and show CPT "HH:MM".
actions: step "15m" sends one integer per interval from start to 24:00 (96 from 00:00); step "1h" sends one per \
hour from start (on the hour), each applied to the hour's four intervals. Intervals before the freeze line must keep \
their committed values."""


def system_prompt(tier: str = "foresight") -> str:
    """The system prompt for a tier (the text does not depend on the day's numbers or notices)."""
    when = _WHEN["blind" if tier == "blind" else "foresight"]
    return "\n\n".join([_JOB + " " + when, _PLAY, _UNITS, _SETTLE, _freeze(tier), _TOOLS])


def situation_text(s: Session) -> str:
    """The situation exactly as get_situation serialises it, without the messages queue."""
    return json.dumps(s.situation(), ensure_ascii=False, separators=(",", ":"))


def opening(s: Session) -> str:
    """The first user message: the task and the watch-0 situation."""
    t = s.task
    return (f"Operating day {t['date']} at {t['settlement_point']}. It is {s.watches[0].time} CPT, watch 0. Commit "
            f"your DA position and schedule, then advance. The situation:\n{situation_text(s)}")


def watch_text(s: Session) -> str:
    """A one-paragraph note for the current watch (path B' may send it after each advance)."""
    if s.done:
        g = s.grade()
        return f"The day is over: profit ${g['profit_usd']:,.2f}."
    fo = s.first_open
    open_from = "nothing is open" if fo >= INTERVALS else f"intervals from {hhmm(15 * fo)} are open"
    rt = s.rt[:s.settled]
    last = f" Last settled RT ${rt[-1]:,.2f}/MWh at {hhmm(15 * (s.settled - 1))}." if len(rt) else ""
    return (f"Watch {s.watch} at {s.watches[s.watch].time}: {open_from}, {s.calls_left} planning calls, SoC "
            f"{s.soc} of {s.grid.n} units, P&L so far ${s.profit():,.2f}.{last}")


def messages(s: Session) -> list[dict]:
    return [{"role": "system", "content": system_prompt(s.tier)}, {"role": "user", "content": opening(s)}]


def tool_schemas(tier: str = "foresight") -> list[dict]:
    """OpenAI-style function schemas for the agent's five tools."""
    ints = {"anyOf": [{"type": "array", "items": {"type": "integer"}}, {"type": "string"}]}
    sched = {"type": "object", "required": ["actions", "start"], "properties": {
        "actions": ints | {"description": "integers from start to 24:00: a > 0 discharges (sells) a units, a < 0 "
                                          "charges (buys) -a units; a list or a comma/space-separated string"},
        "start": {"type": "string", "description": 'first interval, "HH:MM" on the operating day (e.g. "07:00")'},
        "step": {"type": "string", "enum": ["15m", "1h"], "default": "15m",
                 "description": '"15m": one integer per interval; "1h": one per hour, applied to its 4 intervals'}}}
    return [
        _fn("get_situation", "The full state of the day as JSON. Free.", {"type": "object", "properties": {}}),
        _fn("commit_da", "Commit the DA position: 24 integers for HE01..HE24. Watch 0 only, accepted once. Uses a "
                         "planning call.",
            {"type": "object", "required": ["position"], "properties": {"position": ints | {
                "description": "24 integers: a > 0 sells, a < 0 buys, per interval of the hour"}}}),
        _fn("check_schedule", "Dry-run a schedule from start to 24:00 without committing it. Uses a planning call.",
            sched),
        _fn("commit_schedule", "Replace the schedule from start to 24:00, all or nothing. Uses a planning call.", sched),
        _fn("advance", "End this watch: the schedule runs to the next watch and the ended intervals settle at RT. "
                       "Free.", {"type": "object", "properties": {}}),
    ]


def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
