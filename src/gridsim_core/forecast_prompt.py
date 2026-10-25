"""The v4 forecast window's system prompt (the desk card plus the era's AS durations), opening message, per-watch note
and tool schemas; the gridsim-forecast env and path B' share them, so the agent reads the same text on every path."""

from __future__ import annotations

import json

from gridsim_core.contract import P_FLOOR
from gridsim_core.forecast import DAM_SUBMITS, DAYS, FORECAST_CALLS, KEEP, KINDS, Session
from gridsim_core.hybrid import NAMES, PLANNING_CALLS, PRODUCTS
from gridsim_core.hybrid_prompt import duration_table

EXAMPLE = "2025-01-28T10:00-06:00"
_JOB = """You run the desk of a {plant} at an ERCOT settlement point for {days} operating days, live, on a virtual clock. \
Times are Central Prevailing Time (CPT), shown as ISO 8601 with the UTC offset (e.g. {example}). Window hour h counts \
from 00:00 of the first operating day (hour 0) to the last hour of the last day ({last}); tools also accept a time: \
without an offset it is read as CPT, with one (or Z) it is converted. You are a price taker."""

_CLOCK = f"""How the window runs
- The clock opens at 10:00 the day before the first operating day. Watches: 10:00, 14:00 and 18:00 that day; then \
00:00, 06:00, 10:00, 14:00 and 18:00 each operating day (the last day ends with 00:00, 06:00 and 18:00); plus a watch \
when ERCOT or the National Weather Service issues a notice{{deploys}}, or a new weather run moves the price outlook.
- The day-ahead market (DAM) gate for each operating day is the 10:00 watch the day before: submit_dam is open only \
there, and you may resubmit until you advance (up to {DAM_SUBMITS} submits). Miss a gate and that day has no DA \
position{{no_as}}: everything settles in real time (RT).
- DAM results (that day's DA prices{{as_prices}}) arrive at 13:30 and show at the 14:00 watch.
- At every watch: read, plan, then call advance, which runs your book to the next watch. The window goes on until \
advance returns "done": true, so never stop early. Nothing moves while you think.
- The freeze: hours that start before the next full hour plus {{freeze}} are frozen at what you committed \
(frozen_until_hour is the first window hour you can change).
- An hour's RT price{{solar_actual}} shown only after the hour ends."""

_PLANT = """The plant
- energy[h] is the battery's MW in hour h: + discharges (sells), - charges (buys{pv_soak}). |energy| <= p_mw. Charging \
c MWh stores eta*c; discharging d MWh removes d. SoC stays within 0..e_mwh. Discharge over the window <= cycle_cap_mwh. \
Plan values are MW, any value (one hour at x MW is x MWh).{pv}"""

_PV = """
- PV: the panels deliver what the sun gives; you see only the forecast until the hour ends. The controller curtails \
PV in hours whose price is negative and whenever PV plus the battery plus up-reserve awards would exceed meter_mw."""

_RESERVES = """Reserves (AS), set only at the DAM gate
- Products: RegUp, RegDn (regulation), RRS, ECRS, Non-Spin. Up reserves (RegUp, RRS, ECRS, Non-Spin) discharge on \
call; RegDn charges on call. An award pays the hour's DA MCPC per MW. Awards are part of submit_dam and fixed after \
the gate.
- Power: energy + up awards <= p_mw, energy - RegDn >= -p_mw, energy + up awards <= meter_mw.
- SoC must back every award: SoC >= sum over up products of duration_h x MW, and SoC <= e_mwh - eta x RegDn \
duration_h x RegDn MW. Regulation drifts SoC every hour (reg_drift_mean); RRS, ECRS and Non-Spin deploy when ERCOT \
calls them. An award the battery cannot back is a failure to provide, charged at the hour's MCPC; a shortfall caused \
by drift or a deployment that arrived after the hour froze is excused."""

_SETTLE = f"""Settlement (two settlements)
- Your DA position for an hour is your DAM battery move{{pv_da}}. It settles at the DA price; actual export minus the \
DA position settles at the hour's RT price (the mean of its four 15-minute prices).
- Profit = DA energy + RT deviations{{as_cash}} - c_deg per MWh discharged{{ftp}} - the end shortfall: each MWh of SoC short of s_end_min_mwh at the end of the window is bought back at max(the window's highest DA \
price, ${P_FLOOR:.0f}/MWh) / eta. Prices can be negative or spike to the cap. Make profit as large as you can."""

_FORECASTS = """Forecasts, served as they were issued
- get_forecast(kind, zone?, hours?, issued_at?) returns the latest vintage issued by now (issued_at left out, blank or \
null); issued_at asks for the one issued at or before it, and a time after now is refused. Kinds: load (system or a \
weather zone), wind, solar ({solar}), weather (NOAA HRRR at your site or a zone), price (the desk's P10/P50/P90 for DA \
and RT prices at your point{as_prices}), alerts (NWS products in force).
- {load_note}
- The price guide is the desk's model, not a market product: it is often wrong, most when the weather turns.
- get_forecast_drift(kind, target_hour) shows how every vintage so far forecast one hour.
- Forecast tools share {calls} calls per watch."""

_TOOLS = f"""Tools
- get_situation(): the full state as JSON: time, phase, frozen_until_hour, the site, each day's DAM state and results, \
recent RT prices, SoC, your book, a projection of the window on the P50 forecasts and every notice.
- check_schedule(plan, from_hour): a dry run of an energy plan; commit_schedule(plan, from_hour) replaces your book \
from from_hour, hour by hour (a refused hour keeps its old entry). They share {PLANNING_CALLS} planning calls per \
watch. plan = {{{{"energy": ...}}}}: MW values from from_hour to the last window hour (or all of them), or blocks \
[{{{{"from": 30, "to": 34, "mw": 50}}}}] in window hours (hours no block covers are 0).
- submit_dam(operating_day, plan{{share}}): at the gate, the next day's 24 hours: plan = {{{{"energy": ...{{as_fields}}}}}} \
in that day's hours 0..23 (lists or blocks). It sets the day's DA position{{as_note}} and your book for that day.{{keep_note}}
- advance(): ends this watch.
- get_time(), if offered, reads the same virtual clock in UTC."""


def system_prompt(tier: str = "front", era: str = "B", source: str = "desk") -> str:
    """The desk card for a tier, AS era and forecast source (it does not depend on the window's numbers)."""
    lite, blind = tier == "front-lite", tier == "blind"
    days = DAYS[tier]
    parts = [_JOB.format(plant="battery" if lite else "solar farm and battery behind one meter", days=days,
                         last=24 * days - 1, example=EXAMPLE),
             _CLOCK.format(freeze="6 hours" if tier == "freeze-6h" else "1 hour",
                           deploys="" if lite else ", ERCOT deploys reserves", no_as="" if lite else " and no reserves",
                           as_prices="" if lite else " and AS prices",
                           solar_actual=" is" if lite else " and its actual solar are"),
             _PLANT.format(pv_soak="" if lite else " or soaks up PV", pv="" if lite else _PV)]
    if not lite:
        parts += [_RESERVES, duration_table(era)]
    parts.append(_SETTLE.format(
        pv_da="" if lite else " plus pv_da_share x the desk's P50 solar forecast at the gate (none in hours whose DA "
                              "price outlook is negative)",
        as_cash="" if lite else " + AS awards x MCPC", ftp="" if lite else " - failures to provide"))
    if blind:
        parts.append("Forecasts are withheld in this tier: you see history only (past DA and RT prices, settled solar, "
                     "notices).")
    else:
        note = ("load, wind and solar are ERCOT's own forecasts as posted; the official day-ahead load forecast also "
                "comes via EIA-930 at 06:00 of its day" if source == "ercot" else
                "load, wind and solar are the desk's models run on each weather run; ERCOT's own day-ahead load "
                "forecast (via EIA-930) shows at 06:00 of its operating day")
        parts.append(_FORECASTS.format(load_note=note, calls=FORECAST_CALLS, solar="system" if lite else
                                       "system or your site", as_prices="" if lite else ", and AS prices"))
    parts.append(_TOOLS.format(as_fields="" if lite else ', "regup": ..., "regdn": ..., "rrs": ..., "ecrs": ..., '
                                                         '"nspin": ...',
                               as_note="" if lite else " and AS awards", share="" if lite else ", pv_da_share",
                               keep_note=" Energy only in this tier." if lite else
                               f' To keep an AS field as it is, leave it out of the plan or send "{KEEP}" (a field '
                               "never submitted is 0); a field that does not parse refuses the whole submit."))
    return "\n\n".join(parts)


def situation_text(s: Session) -> str:
    """The situation exactly as get_situation serialises it, without the messages queue."""
    return json.dumps(s.situation(), ensure_ascii=False, separators=(",", ":"))


def opening(s: Session) -> str:
    t, k = s.task, s.gate_day()
    gate = f" The DAM gate for {s.day_date(k)} is open now." if k is not None else ""
    return (f"Window {', '.join(s.dates)} at {t['settlement_point']} (site {t['site']['site_id']}). It is "
            f"{s.watches[0].time}, watch 0.{gate} The situation:\n{situation_text(s)}")


def watch_text(s: Session) -> str:
    """A one-paragraph note for the current watch (path B' may send it after each advance)."""
    if s.done:
        return f"The window is over: profit ${s.profit():,.2f}."
    k, fo = s.gate_day(), s.first_open
    gate = f" The DAM gate for {s.day_date(k)} is open: submit_dam before you advance." if k is not None else ""
    open_from = "nothing is open" if fo >= s.H else f"hours from {fo} are open"
    return (f"Watch {s.watch} at {s.watches[s.watch].time}: {open_from}, {s.calls_left} planning calls, "
            f"{s.forecast_calls_left} forecast calls, SoC {s.S:.1f} of {s.site.e:g} MWh, P&L so far "
            f"${s.profit():,.2f}.{gate}")


def messages(s: Session) -> list[dict]:
    return [{"role": "system", "content": system_prompt(s.tier, s.win.era, s.source)},
            {"role": "user", "content": opening(s)}]


def tool_schemas(tier: str = "front") -> list[dict]:
    """OpenAI-style function schemas for the agent's tools (blind omits the forecast tools)."""
    block = {"type": "object", "required": ["from", "to", "mw"], "properties": {
        "from": {"type": "integer"}, "to": {"type": "integer", "description": "the hour after the last"},
        "mw": {"type": "number"}}}
    field = {"anyOf": [{"type": "array", "items": {"anyOf": [{"type": "number"}, block]}}, block, {"type": "string"}]}
    hour = {"anyOf": [{"type": "integer"}, {"type": "string"}],
            "description": f"a window hour, or a time like {EXAMPLE} (CPT without an offset)"}
    plan = {"type": "object", "required": ["plan"], "properties": {
        "plan": {"type": "object", "required": ["energy"], "properties": {
            "energy": field | {"description": "battery MW per window hour (+ discharges, - charges) from from_hour, "
                                              "or blocks"}}},
        "from_hour": hour | {"description": "first window hour the plan covers; defaults to frozen_until_hour"}}}
    lite = tier == "front-lite"
    dam_props = {"energy": field | {"description": "battery MW for the day's hours 0..23, or blocks"}}
    if not lite:
        dam_props |= {k: field | {"description": f'{NAMES[k]} award MW per hour (0..23) as blocks; leave it out or '
                                                 f'send "{KEEP}" to keep it as it is'} for k in PRODUCTS}
    dam = {"type": "object", "required": ["operating_day", "plan"], "properties": {
        "operating_day": {"type": "string", "description": "YYYY-MM-DD, the day after the gate"},
        "plan": {"type": "object", "required": ["energy"], "properties": dam_props}}}
    if not lite:
        dam["properties"]["pv_da_share"] = {"type": "number",
                                            "description": "share of the P50 solar forecast sold DA, 0..1 (default 1)"}
    out = [_fn("get_situation", "The full state of the window as JSON. Free.", {"type": "object", "properties": {}})]
    if tier != "blind":
        out += [
            _fn("get_forecast", "A forecast as issued (latest by now, or the one issued at or before issued_at). Uses a "
                                "forecast call.",
                {"type": "object", "required": ["kind"], "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "zone": {"type": "string", "description": "system, site, a weather zone (COAST, EAST, FAR_WEST, "
                                                              "NORTH, NORTH_C, SOUTHERN, SOUTH_C, WEST) or a point"},
                    "hours": {"type": "integer", "description": "1..72 from now (default 48)"},
                    "issued_at": {"type": "string", "description": f"a time like {EXAMPLE}, not after now; leave "
                                                                   "it out (or blank) for the latest"}}}),
            _fn("get_forecast_drift", "Every vintage so far for one target hour. Uses a forecast call.",
                {"type": "object", "required": ["kind", "target_hour"], "properties": {
                    "kind": {"type": "string", "enum": ["load", "wind", "solar", "weather", "price"]},
                    "target_hour": hour, "zone": {"type": "string"}}})]
    out += [
        _fn("check_schedule", "Dry-run an energy plan from from_hour. Uses a planning call.", plan),
        _fn("commit_schedule", "Replace the book from from_hour, hour by hour (refused hours keep their old entry). "
                               "Uses a planning call.", plan),
        _fn("submit_dam", "At the 10:00 DAM gate only: the next operating day's DA plan ("
                          + ("battery energy only" if lite else "battery and AS") + "). Resubmit until you advance.",
            dam),
        _fn("advance", "End this watch: the book runs to the next watch and ended hours settle. Free.",
            {"type": "object", "properties": {}})]
    return out


def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}
