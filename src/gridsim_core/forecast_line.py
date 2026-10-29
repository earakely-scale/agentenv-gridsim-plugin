"""Forecast-then-plan on the blind tier: the prompt paragraph that lets the agent write its forecast first, the one-line
forecast format and its parser. The grader never reads the forecast; it is a diagnostic and the plan's input."""

from __future__ import annotations

import re

from gridsim_core.contract import HOURS

FORECAST_NOTE = ("You may write your forecast first. Before calling submit_schedule you may write one line "
                 "\"Forecast: p1, p2, ..., p24\" with your forecast of today's 24 hourly DAM prices in $/MWh (HE01 "
                 "first), then a brief plan. Only the submitted schedule is graded. Keep the reply brief.")

_LINE = re.compile(r"^[ \t>*_`#-]*forecast[*_`]*[ \t]*(?:\([^)\n]*\))?[ \t]*[:=][ \t]*(.*)$", re.I | re.M)
_THOUSANDS = re.compile(r"(?<=\d),(?=\d{3}(?!\d))")
_NUM = re.compile(r"(-?)\$?(-?)(\d+(?:\.\d+)?)")
_THINK = re.compile(r"<think>.*?(?:</think>|$)", re.S)


def forecast_line(prices) -> str:
    """'Forecast: 23, 21, ..., 25': whole dollars per MWh, HE01 first."""
    return "Forecast: " + ", ".join(str(round(float(p))) for p in prices)


def written(prices) -> list[float]:
    """The prices a forecast line states (whole dollars), i.e. what the plan is made on."""
    return [float(round(float(p))) for p in prices]


def forecast_span(text: str) -> tuple[int, int] | None:
    """Character span of the first forecast line in the raw text (where its tokens sit in a completion)."""
    m = _LINE.search(text or "")
    return (m.start(), m.end()) if m else None


def parse_forecast(text: str, hours: int = HOURS) -> list[float] | None:
    """The first 'Forecast:' line's numbers if there are exactly `hours` of them, else None."""
    m = _LINE.search(_THINK.sub("", text or ""))
    if not m:
        return None
    nums = [float(f"-{v}" if (a or b) else v) for a, b, v in _NUM.findall(_THOUSANDS.sub("", m.group(1)))]
    return nums if len(nums) == hours else None
