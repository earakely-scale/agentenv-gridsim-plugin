"""The eleven desk tools as JSON schemas (OpenAI function format), per layer (contract section 3)."""

from __future__ import annotations

import copy

_TIME = {"type": "string", "description": 'a time: "D0 14:35", "D-1 10:00", "14:35" (on the day) or ISO'}
_DAY = {"type": "string", "description": '"D0", "D1", "D-1" (history) or an ISO date; default the day in progress'}
_HOURS = {"description": 'operating hours: "HE07-HE10", "HE07", "all", or a list like [7, 8]',
          "anyOf": [{"type": "string"}, {"type": "array", "items": {"type": "integer"}}]}
_POINTS = {"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
           "description": "[[mw, price], ...] from max charge (negative MW) to max discharge; MW and price "
                          "non-decreasing; 2-10 points"}
_PRE_SIDES = {
    "offer": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
              "description": "pre-RTC+B Gen Resource offer [[mw >= 0, price], ...], MW increasing, price non-decreasing"},
    "bid": {"type": "array", "items": {"type": "array", "items": {"type": "number"}},
            "description": "pre-RTC+B charging bid [[mw consumed >= 0, price], ...], MW increasing, price non-increasing"},
}


def _curves(rtcb: bool) -> dict:
    props = {"hours": _HOURS}
    if rtcb:
        props["points"] = _POINTS
    else:
        props.update(_PRE_SIDES)
    return {"type": "array", "items": {"type": "object", "properties": props, "required": ["hours"]}}


def _fn(name: str, desc: str, props: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props,
                                                            "required": required or []}}}


def tool_specs(layer: str = "v2", rtcb: bool = True) -> list[dict]:
    curve_desc = ("one ESR Energy Bid/Offer Curve per hour" if rtcb else
                  "per hour a Gen Resource offer ('offer') and/or a charging bid ('bid')")
    specs = [
        _fn("get_prices", "Posted prices only (ERCOT public reports): DAM SPP hourly, RT SPP 15-min, SCED LMP 5-min, "
            "at your node or your hub.",
            {"market": {"type": "string", "enum": ["dam", "rt", "sced"] + (["as_dam", "as_rt"] if layer != "v2" else [])},
             "point": {"type": "string", "enum": ["node", "hub"]}, "day": _DAY, "start": _TIME, "end": _TIME,
             "step": {"type": "string", "enum": ["5m", "15m", "1h"]}}),
        _fn("get_forecasts", "As-issued forecasts: the desk price forecast (P10/P50/P90, modelled), ERCOT load, wind, "
            "solar and net load, outage capacity, NWS alerts.",
            {"kind": {"type": "string", "enum": ["price", "load", "wind", "solar", "net_load", "outages", "weather"]},
             "market": {"type": "string", "enum": ["dam", "rt"]}, "day": _DAY,
             "vintage": {"type": "string", "description": '"latest" or a past time to read an earlier issue'},
             "step": {"type": "string", "enum": ["15m", "1h"]}}),
        _fn("get_grid_conditions", "System conditions on the 5-minute grid: PRC (or its labelled proxy), system lambda, "
            "load, wind, solar, EEA level and recent ERCOT notices.", {"start": _TIME, "end": _TIME}),
        _fn("get_asset_status", "Plant telemetry: status, SoC, limits, last base points, outages, cycles, parameters.",
            {}),
        _fn("get_position", "Your book: DAM awards, RT dispatch, curves in force, COP and the shadow statement.",
            {"day": _DAY, "detail": {"type": "string", "enum": ["summary", "hourly"]}}),
        _fn("submit_dam_offers", f"Submit DAM offers for an operating day ({curve_desc}); before 10:00 the day "
            "before. Accepted hours replace earlier curves for those hours.",
            {"day": _DAY, "curves": _curves(rtcb)}, ["curves"]),
        _fn("submit_rt_offers", f"Submit real-time offers ({curve_desc}); from 18:00 the day before until the hour "
            "ends; used from the next SCED run." + ("" if rtcb else " Charging bids freeze 60 minutes before the hour."),
            {"day": _DAY, "curves": _curves(rtcb)}, ["curves"]),
        _fn("update_cop", "Update your Current Operating Plan per hour (status, HSL/LSL, HBSOC, MinSOC/MaxSOC); an "
            "hour freezes 60 minutes before it starts.",
            {"day": _DAY, "rows": {"type": "array", "items": {"type": "object", "properties": {
                "hours": _HOURS, "status": {"type": "string"}, "hsl_mw": {"type": "number"},
                "lsl_mw": {"type": "number"},
                "hbsoc_mwh": {"anyOf": [{"type": "number"}, {"type": "array", "items": {"type": "number"}}]},
                "min_soc_mwh": {"type": "number"}, "max_soc_mwh": {"type": "number"}}, "required": ["hours"]}}},
            ["rows"]),
        _fn("check_submission", "Validate a DAM, RT or COP submission without sending it (ERCOT-style codes).",
            {"kind": {"type": "string", "enum": ["dam", "rt", "cop"]},
             "payload": {"type": "object", "description": "the arguments you would pass to the submit tool"}},
            ["kind", "payload"]),
        _fn("optimize", "Co-optimise DAM and RT on YOUR price view (\"desk\" = the latest desk forecast, or your own "
            "paths); returns proposed curves, COP and projected P&L. Proposals only; it never sees unposted prices.",
            {"price_view": {"anyOf": [{"type": "string", "enum": ["desk"]}, {"type": "object", "properties": {
                "dam": {"type": "array", "items": {"type": "number"}, "description": "24 hourly $/MWh per day"},
                "rt": {"type": "array", "items": {"type": "number"}, "description": "24 hourly or 96 15-min per day"},
                "scenarios": {"type": "array", "items": {"type": "object"}}}}]},
             "risk": {"type": "number", "description": "0 = act on the median only, 1 = widen curves to the scenario range"},
             "constraints": {"type": "object", "properties": {
                 "end_soc_mwh": {"type": "number"}, "max_cycles": {"type": "number"}, "hours": _HOURS, "day": _DAY}}}),
        _fn("set_reminder", "Wake yourself at a time (5-minute grid). Ending your turn waits until the next event.",
            {"at": _TIME, "note": {"type": "string"}}, ["at"]),
    ]
    return copy.deepcopy(specs)


TOOL_SPECS = tool_specs()
HOOK_SPEC = _fn("next_wakeup", "Hidden hook-role tool: the env's next wake-up.", {})
