"""ERCOT notices and NWS alerts on the v2 live day: the reveal rule and the per-(date, point) lookups the pack builder
uses. Data: data/notices/notices.jsonl, nws_vtec.jsonl and ops_coverage.json from scripts/scrape_notices.py and
scripts/join_vtec.py."""

from __future__ import annotations

import datetime as dt
import json
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from gridsim_core.contract import ceil_to_interval
from gridsim_core.task import REGIONS, data_root

CPT = ZoneInfo("America/Chicago")
REVEAL_MINUTES = 15
WATCH0_HOUR = 14
BOARD_DAYS = 3
NWS_WARNING = "W"
# Load-moving NWS warnings; severe-thunderstorm and tornado warnings are short and local, so they do not make a notice day.
NWS_DAY_PHENOMENA = frozenset({"EH", "XH", "WS", "IS", "BZ", "WC", "EC", "HZ", "HU", "TR", "HW", "EW"})


def reveal_at(issued: dt.datetime, minutes: int = REVEAL_MINUTES) -> dt.datetime:
    """ceil(issued, 15 min), taken in UTC so the repeated fall-back hour cannot shift it; CPT boundaries are UTC ones."""
    return ceil_to_interval(issued.astimezone(dt.UTC), minutes).astimezone(CPT)


def watch0(date: str | dt.date) -> dt.datetime:
    d = dt.date.fromisoformat(str(date))
    return dt.datetime.combine(d - dt.timedelta(days=1), dt.time(WATCH0_HOUR), CPT)


def day_bounds(date: str | dt.date) -> tuple[dt.datetime, dt.datetime]:
    d = dt.date.fromisoformat(str(date))
    return dt.datetime.combine(d, dt.time(0), CPT), dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), CPT)


@lru_cache(maxsize=4)
def load(root: str | None = None) -> tuple[tuple[dict, ...], tuple[dict, ...], dict]:
    base = Path(root) if root else data_root() / "notices"

    def rows(name: str) -> tuple[dict, ...]:
        p = base / name
        return tuple(json.loads(line) for line in p.open()) if p.exists() else ()

    cov = base / "ops_coverage.json"
    return rows("notices.jsonl"), rows("nws_vtec.jsonl"), json.loads(cov.read_text())["days"] if cov.exists() else {}


def coverage(date: str | dt.date, root: str | None = None) -> float:
    """min over D-1 and D of the share of the CPT day the ops-message archive covers; below 1.0 a day without
    notices may only be a gap in the archive, so it is not a known-quiet day."""
    d = dt.date.fromisoformat(str(date))
    days = load(root)[2]
    return min(days.get((d - dt.timedelta(days=1)).isoformat(), 0.0), days.get(d.isoformat(), 0.0))


def _issued(n: dict) -> dt.datetime:
    return dt.datetime.fromisoformat(n["issued_at_utc"].replace("Z", "+00:00")).astimezone(CPT)


@lru_cache(maxsize=4)
def _by_day(root: str | None = None) -> tuple[dict, dict]:
    """ERCOT rows and NWS rows keyed by their CPT issue date, so a lookup reads a few days, not the archive."""
    ercot, vtec, _ = load(root)
    e: dict[dt.date, list[dict]] = {}
    v: dict[tuple[str, dt.date], list[dict]] = {}
    for n in ercot:
        day = _issued(n).date() if n["timestamp_quality"] == "minute" else dt.date.fromisoformat(n["issued_at"][:10])
        e.setdefault(day, []).append(n)
    for n in vtec:
        v.setdefault((n["region"], _issued(n).date()), []).append(n)
    return e, v


def notices_for(
    date: str | dt.date, point: str, *, grid_only: bool = True, nws: bool = True, root: str | None = None
) -> list[dict]:
    """Every notice the agent may see on the live day at `point`, each with `reveal_at` (CPT ISO) and `when`:
    "board" (issued in the BOARD_DAYS before watch 0; shown at watch 0), "midnight" (issued D-1 14:00..24:00; shown at
    the D 00:00 watch) or "intraday" (issued on D; shown at the first watch >= reveal_at). Minute-stamped rows only,
    except date-only ERCOT rows dated <= D-2, which join the board. NWS rows are the point's region's alerts still in
    effect at watch 0 or issued before D 24:00."""
    w0 = watch0(date)
    d0, d1 = day_bounds(date)
    board_from = w0 - dt.timedelta(days=BOARD_DAYS)
    region = REGIONS.get(point, "central")
    e_idx, v_idx = _by_day(root)
    span = [board_from.date() + dt.timedelta(days=k) for k in range((d1.date() - board_from.date()).days + 1)]
    out = []
    for n in (n for day in span for n in e_idx.get(day, ())):
        if grid_only and not n.get("grid_condition") or "test" in n.get("tags", ()):
            continue
        if n.get("regions") and region not in n["regions"]:
            continue
        if n["timestamp_quality"] != "minute":
            day = dt.date.fromisoformat(n["issued_at"][:10])
            if board_from.date() <= day <= (d0 - dt.timedelta(days=2)).date():
                out.append({**n, "reveal_at": w0.isoformat(), "when": "board"})
            continue
        t = _issued(n)
        if board_from <= t < w0:
            out.append({**n, "reveal_at": w0.isoformat(), "when": "board"})
        elif w0 <= t < d0:
            out.append({**n, "reveal_at": d0.isoformat(), "when": "midnight"})
        elif d0 <= t < d1:
            out.append({**n, "reveal_at": reveal_at(t).isoformat(), "when": "intraday"})
    if nws:
        for v in (v for day in span for v in v_idx.get((region, day), ())):
            t = _issued(v)
            exp = dt.datetime.fromisoformat(v["expires_at_utc"].replace("Z", "+00:00"))
            if t < w0 and exp > w0 and t >= w0 - dt.timedelta(days=BOARD_DAYS):
                out.append({**v, "reveal_at": w0.isoformat(), "when": "board"})
            elif w0 <= t < d0:
                out.append({**v, "reveal_at": d0.isoformat(), "when": "midnight"})
            elif d0 <= t < d1:
                out.append({**v, "reveal_at": reveal_at(t).isoformat(), "when": "intraday"})
    out.sort(key=lambda n: (n["reveal_at"], n["issued_at_utc"] or "", n["notice_id"]))
    return out


def is_notice_day(date: str | dt.date, point: str, root: str | None = None) -> bool:
    """At least one minute-stamped ERCOT grid-condition notice issued between watch 0 (D-1 14:00) and D 24:00 CPT, or
    a load-moving NWS warning (NWS_DAY_PHENOMENA) for the point's region in effect at some time on D."""
    d0, d1 = day_bounds(date)
    for n in notices_for(date, point, root=root):
        if n["source"] == "ERCOT":
            if n["when"] != "board" and n.get("action") == "issue" and n["timestamp_quality"] == "minute":
                return True
        elif (
            n.get("significance") == NWS_WARNING
            and n.get("phenomena") in NWS_DAY_PHENOMENA
            and _issued(n) < d1
            and dt.datetime.fromisoformat(n["expires_at_utc"].replace("Z", "+00:00")) > d0
        ):
            return True
    return False


def assign_watches(notices: list[dict], watch_times: list[dt.datetime]) -> dict[str, dt.datetime]:
    """notice_id -> the first watch at or after its reveal_at (None past the last watch)."""
    ws = sorted(watch_times)
    out = {}
    for n in notices:
        r = dt.datetime.fromisoformat(n["reveal_at"])
        out[n["notice_id"]] = next((w for w in ws if w >= r), None)
    return out
