"""Desk time: minutes from D0 00:00 CPT, operating hours HE01..HE24, and the labels the agent reads and writes."""

from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

CPT = ZoneInfo("America/Chicago")
START = -1080
DAM_CLOSE = -840
DAM_RESULTS = -630
DRUC = -570
ADJ_OPEN = -360
CHECKPOINTS = (0, 360, 720, 1080)
DAY = 1440
SCED = 5

_REL = re.compile(r"^D(-?\d+)\s+(\d{1,2}):(\d{2})$")
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_HE = re.compile(r"^HE\s*(\d{1,2})$", re.I)
_LABEL = re.compile(r"^(?:(Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+)?(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})$", re.I)
_HE_RANGE = re.compile(r"^HE\s*(\d{1,2})\s*-\s*(?:HE)?\s*(\d{1,2})$", re.I)


class TimeError(ValueError):
    pass


def d0_midnight(d0: str) -> dt.datetime:
    return dt.datetime.combine(dt.date.fromisoformat(d0), dt.time(0), CPT)


def to_minutes(iso: str, d0: str) -> float:
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=CPT)
    return (t - d0_midnight(d0)).total_seconds() / 60.0


def to_iso(minute: float, d0: str) -> str:
    return (d0_midnight(d0) + dt.timedelta(minutes=minute)).isoformat()


def to_utc(minute: float, d0: str) -> str:
    return (d0_midnight(d0) + dt.timedelta(minutes=minute)).astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def label(minute: float, d0: str) -> str:
    t = d0_midnight(d0) + dt.timedelta(minutes=minute)
    return t.strftime("%a %m-%d %H:%M")


def day_label(day: int, d0: str) -> str:
    return (dt.date.fromisoformat(d0) + dt.timedelta(days=day)).strftime("%a %m-%d")


def date_of(day: int, d0: str) -> str:
    return (dt.date.fromisoformat(d0) + dt.timedelta(days=day)).isoformat()


def parse_time(value, d0: str, day: int = 0) -> int:
    """A minute from D0 00:00 for "Sun 04-26 09:00" or "04-26 09:00" (as shown), "D-1 10:00", "14:35" (on `day`), an
    ISO timestamp, "HE07" (its start) or a number."""
    if isinstance(value, int | float) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str) or not value.strip():
        raise TimeError(f"time {value!r} not understood")
    v = value.strip()
    if m := _REL.match(v):
        return int(m[1]) * DAY + int(m[2]) * 60 + int(m[3])
    if m := _HHMM.match(v):
        return day * DAY + int(m[1]) * 60 + int(m[2])
    if m := _LABEL.match(v):
        return _from_label(m, d0)
    if m := _HE.match(v):
        h = int(m[1])
        if not 1 <= h <= 24:
            raise TimeError(f"hour {v!r} not in HE01..HE24")
        return day * DAY + (h - 1) * 60
    try:
        return int(round(to_minutes(v, d0)))
    except ValueError as e:
        raise TimeError(f"time {value!r} not understood") from e


def _from_label(m: re.Match, d0: str) -> int:
    """A minute for "Sun 04-26 09:00" or "04-26 09:00", the form the desk shows: the year nearest D0; a weekday that
    does not match the date is an error."""
    base = dt.date.fromisoformat(d0)
    try:
        cands = [dt.date(y, int(m[2]), int(m[3])) for y in (base.year - 1, base.year, base.year + 1)]
    except ValueError as e:
        raise TimeError(f"date {m[2]}-{m[3]} not understood") from e
    day = min(cands, key=lambda d: abs((d - base).days))
    if m[1] and day.strftime("%a").lower() != m[1].lower():
        raise TimeError(f"{m[2]}-{m[3]} is a {day.strftime('%a')}, not a {m[1]}")
    hh, mm = int(m[4]), int(m[5])
    if hh > 24 or mm > 59:
        raise TimeError(f"time {hh}:{mm:02d} not understood")
    return (day - base).days * DAY + hh * 60 + mm


def parse_day(value, d0: str, days: int, default: int) -> int:
    """Operating-day index for "D0", "D1", "D-1", an ISO date or an int."""
    if value is None:
        return default
    if isinstance(value, int) and not isinstance(value, bool):
        j = value
    elif isinstance(value, str) and re.fullmatch(r"D-?\d+", value.strip()):
        j = int(value.strip()[1:])
    else:
        try:
            j = (dt.date.fromisoformat(str(value)) - dt.date.fromisoformat(d0)).days
        except ValueError as e:
            raise TimeError(f"day {value!r} not understood") from e
    if not 0 <= j < days:
        raise TimeError(f"day {value!r} is not an operating day of this episode (D0..D{days - 1})")
    return j


def parse_hours(value) -> list[int]:
    """HE numbers 1..24 from "all", "HE07", "HE07-HE10", "7-10", a list of ints or HE strings."""
    if value is None or value == "all":
        return list(range(1, 25))
    if isinstance(value, int) and not isinstance(value, bool):
        out = [value]
    elif isinstance(value, str):
        v = value.strip()
        if m := _HE_RANGE.match(v) or re.fullmatch(r"(\d{1,2})\s*-\s*(\d{1,2})", v):
            a, b = int(m[1]), int(m[2])
            if a > b:
                raise TimeError(f"hours {value!r}: start after end")
            out = list(range(a, b + 1))
        elif m := _HE.match(v) or re.fullmatch(r"(\d{1,2})", v):
            out = [int(m[1])]
        else:
            raise TimeError(f"hours {value!r} not understood (use 'HE07-HE10', 'HE07', 'all' or [7, 8])")
    elif isinstance(value, list) and value:
        out = []
        for x in value:
            out += parse_hours(x)
    else:
        raise TimeError(f"hours {value!r} not understood")
    bad = [h for h in out if not 1 <= h <= 24]
    if bad:
        raise TimeError(f"hours {bad} not in HE01..HE24")
    return sorted(set(out))


def he(h: int) -> str:
    return f"HE{h:02d}"


def hours_label(hours: list[int]) -> str:
    if not hours:
        return ""
    runs, a = [], hours[0]
    for p, q in zip(hours, hours[1:] + [None], strict=True):
        if q != p + 1:
            runs.append(he(a) if a == p else f"{he(a)}-{he(p)}")
            a = q
    return ",".join(runs)
