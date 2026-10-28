"""The v3 hybrid day's system prompt (the rules card plus the era's AS duration table), opening message, per-watch note,
tool schemas and the path B oneshot prompt and reward; the gridsim-hybrid env and training share them, so the agent
reads the same text on every path."""

from __future__ import annotations

import json
import re

from gridsim_core.contract import AS_DURATION_H, P_FLOOR, as_era
from gridsim_core.hybrid import HOURS, NAMES, PLANNING_CALLS, PRODUCTS, Session, oneshot_grade
from gridsim_core.trl import _THINK, _TOOL_CALL, _flatten, _name_args, _task

_JOB = """You run a solar farm and a battery that share one meter (the point of interconnection) at an ERCOT node, for \
one operating day (D), live, on a virtual clock. Times are Central Prevailing Time (CPT); hour h (0..23) is h:00 to \
h+1:00. You are a price taker. You decide only the battery and, when reserves are on, the battery's ancillary-service \
(AS) awards; the plant's controller runs the solar panels."""

_DAY = f"""How the day runs
- Watch 0 is D-1 14:00, after the day-ahead market (DAM) posts: you see D's 24 hourly PV availability, DA energy \
prices and DA AS prices. Whatever book you hold when watch 0 ends becomes your DA position.
- Then the day plays in watches: D 00:00, 06:00, 12:00, 18:00, plus a watch when ERCOT issues a notice or deploys \
reserves.
- At every watch: read the situation, re-plan if it helps with up to {PLANNING_CALLS} planning calls (check_schedule \
and commit_schedule share them; unused ones do not carry over), then call advance, which runs your book to the next \
watch. The day goes on until advance returns "done": true, so never stop early.
- An hour's real-time (RT) price is shown only after the hour ends. Nothing moves while you think.
- The freeze: at each watch, hours that start before the next full hour plus 1 hour are frozen at what you committed \
(frozen_until_hour is the first hour you can change). At watch 0 every hour is open."""

_PLANT = """The plant
- pv_mw[h] is the PV the panels can deliver in hour h. meter_mw caps export, meter_import_mw caps import.
- The controller curtails PV in hours whose price is negative, and whenever PV plus your battery output plus your \
up-reserve awards would exceed meter_mw. So discharging, or holding up reserves, while PV fills the meter costs you \
that PV.
- energy[h] is the battery's MW in hour h: + discharges (sells), - charges (buys or soaks up PV). |energy| <= p_mw. \
Charging c MWh stores eta*c; discharging d MWh removes d. SoC stays within 0..e_mwh. Discharge over the day <= \
cycle_cap_mwh. Plan values are MW, any value (one hour at x MW is x MWh)."""

_RESERVES = """Reserves (AS)
- Products: RegUp, RegDn (regulation), RRS, ECRS, Non-Spin. RegUp, RRS, ECRS and Non-Spin are up reserves: \
discharge on call. RegDn is a down reserve: charge on call. An award pays its hour's MCPC per MW.
- Power: energy + up awards <= p_mw and energy - RegDn >= -p_mw; energy + up awards <= meter_mw.
- State of charge (SoC) must back every award at both ends of the hour (before deployments): SoC >= sum over up \
products of duration_h x MW, and SoC <= e_mwh - eta x RegDn duration_h x RegDn MW. The durations for this day are \
below.
- Regulation drifts SoC every hour: RegUp drains about reg_drift_mean.regup x its MW, RegDn adds eta x \
reg_drift_mean.regdn x its MW. The actual draw follows the grid and is learned after the hour: RegUp deploys more \
when the system runs short (RT above DA), RegDn when it runs long. RRS, ECRS and Non-Spin deploy when ERCOT calls them \
(a notice says when): the battery discharges the award for up to the product's duration, and the hours it has \
delivered count toward that duration.
- An award the battery cannot back is a failure to provide: its MW are charged at the hour's MCPC (the larger of DA \
and RT where RT exists), whatever left the battery short (the book, drift or a deployment). Up awards also need power \
headroom: when the battery cannot charge enough to make room for them, the MW beyond it are short too.
{fixed}"""

_SETTLE = f"""Settlement
- Your DA position x_da[h] is the meter export your watch-0 book projects (PV after curtailment at DA prices, plus \
the energy the battery can run as booked on that projection). It settles at the hour's DA price; the hour's actual \
export minus x_da settles at the RT price.
{{deployed}}- Profit = DA energy + RT deviations + AS awards x MCPC - c_deg per MWh discharged - failures to provide - the end \
shortfall: each MWh of SoC short of s_end_min_mwh at 24:00 is bought back at max(the day's highest DA price, \
${P_FLOOR:.0f}/MWh) / eta. Prices can be negative or spike to the cap. Make profit as large as you can."""

_DEPLOYED = """- Energy that regulation and reserve deployments move (RegUp, RRS, ECRS and Non-Spin discharging, RegDn \
charging) is part of the hour's actual export, so it settles at that hour's RT price, as ERCOT settles it.
"""

_TOOLS = """Tools
- get_situation(): the full state as JSON: time, frozen_until_hour, site, AS rules, the day's hourly inputs, SoC, your \
book, the DA position, a projection of the day (SoC path, reserve margin per hour, money) and every notice.
- check_schedule(plan, from_hour): a dry run: rule issues per hour, the projected day, clip recovered, curtailment and \
the reserve margin per hour. Commits nothing.
- commit_schedule(plan, from_hour): replaces your book from from_hour, hour by hour: an hour that breaks a rule is \
refused (named by its rule) and keeps its old entry; if its energy alone passes, the energy is kept and only its AS \
are refused. Hours before frozen_until_hour must keep their committed values.
- A planning call refused because its input is malformed (a list of the wrong length, a value of the wrong type, an \
unknown field) does not use a planning call, up to 3 such refusals per watch; its error names the field and the shape \
it needs. A plan that parses uses a call even when hours are refused.
- advance(): ends this watch.
- get_time(), if offered, reads the same virtual clock in UTC.
plan: {{"energy": ...{as_fields}}}. Each field is a list of MW values from from_hour to hour 23 (or all 24), or \
blocks [{{"from": 17, "to": 21, "mw": 50}}] meaning hours 17..20 at 50 MW (hours no block covers are 0). energy is \
required{omit}. Example: {example}"""


def duration_table(era: str) -> str:
    d = AS_DURATION_H[era]
    rows = ", ".join(f"{NAMES[k]} {d[k]:g} h" for k in PRODUCTS if k in d)
    note = {"A": "ECRS does not exist yet (it starts 2023-06-10).", "B": "",
            "C": "RTC+B rules (NPRR1282)."}[era]
    return f"AS durations for this day (era {era}): {rows}. {note}".strip()


def system_prompt(tier: str = "reserves", era: str = "B") -> str:
    """The rules card for a tier and AS era (the text does not depend on the day's numbers or notices)."""
    parts = [_JOB, _DAY, _PLANT]
    if tier != "energy":
        fixed = ("- Reserves tier: your DA AS awards are fixed after watch 0; later commits may change only energy."
                 if tier == "reserves" else "- AS changes on open hours after watch 0 settle at RT MCPC.")
        parts += [_RESERVES.format(fixed=fixed), duration_table(era)]
    else:
        parts.append("Reserves are off in this tier: plans carry energy only.")
    parts.append(_SETTLE.format(deployed="" if tier == "energy" else _DEPLOYED))
    if tier == "energy":
        parts.append(_TOOLS.format(as_fields="", omit="", example='{"energy": [{"from": 0, "to": 5, "mw": -50}, '
                                                                  '{"from": 18, "to": 21, "mw": 100}]}'))
    else:
        parts.append(_TOOLS.format(as_fields=', "regup": ..., "regdn": ..., "rrs": ..., "ecrs": ..., "nspin": ...',
                                   omit='; leave an AS field out (or send "keep" or null) to keep your book for it',
                                   example='{"energy": [{"from": 0, "to": 5, "mw": -50}, {"from": 18, "to": 21, '
                                           '"mw": 50}], "regdn": [{"from": 0, "to": 6, "mw": 25}], "ecrs": '
                                           '[{"from": 17, "to": 21, "mw": 25}]}'))
    return "\n\n".join(parts)


def situation_text(s: Session) -> str:
    """The situation exactly as get_situation serialises it, without the messages queue."""
    return json.dumps(s.situation(), ensure_ascii=False, separators=(",", ":"))


def opening(s: Session) -> str:
    """The first user message: the task and the watch-0 situation."""
    t = s.task
    return (f"Operating day {t['date']} at {t['settlement_point']} (site {t['site']['site_id']}). It is "
            f"{s.watches[0].time} CPT, watch 0. Commit your book for D, then advance. The situation:\n"
            f"{situation_text(s)}")


def watch_text(s: Session) -> str:
    """A one-paragraph note for the current watch (path B' may send it after each advance)."""
    if s.done:
        return f"The day is over: profit ${s.profit():,.2f}."
    fo = s.first_open
    open_from = "nothing is open" if fo >= HOURS else f"hours from {fo} are open"
    last = (f" Last settled RT ${s.day.rt[s.settled - 1]:,.2f}/MWh in hour {s.settled - 1}." if s.settled else "")
    return (f"Watch {s.watch} at {s.watches[s.watch].time}: {open_from}, {s.calls_left} planning calls, SoC "
            f"{s.S:.1f} of {s.site.e:g} MWh, P&L so far ${s.profit():,.2f}.{last}")


def messages(s: Session) -> list[dict]:
    return [{"role": "system", "content": system_prompt(s.tier, s.day.era)}, {"role": "user", "content": opening(s)}]


def tool_schemas(tier: str = "reserves") -> list[dict]:
    """OpenAI-style function schemas for the agent's four tools."""
    block = {"type": "object", "required": ["from", "to", "mw"], "properties": {
        "from": {"type": "integer", "description": "first hour (0..23)"},
        "to": {"type": "integer", "description": "hour after the last (1..24)"},
        "mw": {"type": "number"}}}
    field = {"anyOf": [{"type": "array", "items": {"anyOf": [{"type": "number"}, block]}}, block, {"type": "string"}]}
    props = {"energy": field | {"description": "battery MW per hour (+ discharges, - charges): MW values from "
                                              "from_hour to 23, or blocks"}}
    if tier != "energy":
        props |= {k: {"anyOf": field["anyOf"] + [{"type": "null"}],
                      "description": f'{NAMES[k]} award MW per hour as blocks; left out, "keep" or null keeps the '
                                     'book'} for k in PRODUCTS}
    plan = {"type": "object", "required": ["plan"], "properties": {
        "plan": {"type": "object", "required": ["energy"], "properties": props},
        "from_hour": {"type": "integer", "description": "first hour the plan covers; defaults to frozen_until_hour"}}}
    return [
        _fn("get_situation", "The full state of the day as JSON. Free.", {"type": "object", "properties": {}}),
        _fn("check_schedule", "Dry-run a plan from from_hour without committing it. Uses a planning call.", plan),
        _fn("commit_schedule", "Replace the book from from_hour, hour by hour (refused hours keep their old entry). "
                               "Uses a planning call.", plan),
        _fn("advance", "End this watch: the book runs to the next watch and the ended hours settle. Free.",
            {"type": "object", "properties": {}}),
    ]


def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


# path B: one watch-0 plan, graded by gridsim_core.hybrid.oneshot_grade


_ONESHOT = """This is a one-shot version: there is one decision, at watch 0. Reply with your plan for all of D as one \
JSON object, {"energy": ..., "regup": ..., ...} with from_hour 0, either alone or as the plan argument of a \
commit_schedule tool call. The plan is graded on the day at DA prices with expected regulation drift."""


def oneshot_messages(task: dict, tier: str = "reserves") -> list[dict]:
    """The path B prompt: the rules card, the one-shot note and the watch-0 situation."""
    s = Session(task, tier, [], [], reference=True)
    return [{"role": "system", "content": system_prompt(tier, as_era(task["date"])) + "\n\n" + _ONESHOT},
            {"role": "user", "content": opening(s)}]


_OBJ = re.compile(r"\{")


def extract_plan(completion) -> dict | None:
    """The plan of the first commit_schedule call, else the last JSON object with an energy field in the text."""
    text, calls = _flatten(completion)
    text = _THINK.sub("", text)
    for m in _TOOL_CALL.finditer(text):
        try:
            calls.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            calls.append(None)
    for c in calls:
        name, args = _name_args(c)
        if name in ("commit_schedule", "check_schedule") and isinstance(args, dict) and isinstance(args.get("plan"),
                                                                                                  (dict, str)):
            return args["plan"] if isinstance(args["plan"], dict) else _loads(args["plan"])
    dec, found = json.JSONDecoder(), None
    for m in _OBJ.finditer(text):
        try:
            obj, _ = dec.raw_decode(text, m.start())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            plan = obj.get("plan") if isinstance(obj.get("plan"), dict) else obj
            if "energy" in plan:
                found = plan
    return found


def _loads(s: str) -> dict | None:
    try:
        v = json.loads(s)
    except json.JSONDecodeError:
        return None
    return v if isinstance(v, dict) else None


def oneshot_reward_fn(prompts, completions, task=None, tier=None, task_id=None, **kw) -> list[float]:
    """TRL reward_funcs entry for hybrid-oneshot: one reward per completion; no format credit."""
    tasks = task if task is not None else task_id
    out = []
    for i, completion in enumerate(completions):
        t = _task(tasks[i] if isinstance(tasks, (list, tuple)) else tasks)
        tr = (tier[i] if isinstance(tier, (list, tuple)) else tier) or "reserves"
        plan = extract_plan(completion)
        out.append(0.0 if plan is None else oneshot_grade(t, plan, tr)["reward"])
    return out
