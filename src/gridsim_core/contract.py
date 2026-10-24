"""Frozen v1 contract constants, the ERCOT era table and the interval helpers used from v2."""

from __future__ import annotations

import datetime as dt
import math

CONTRACT_VERSION = "1.0"
P_FLOOR = 50.0
HOURS = 24
DEGENERATE_EPS = 1e-9

ERAS = (
    {"start": "2014-01-01", "name": "pre-2022", "hcap": 9000.0, "floor": -250.0, "ecrs": False, "rtcb": False},
    {"start": "2022-01-01", "name": "hcap-5000", "hcap": 5000.0, "floor": -250.0, "ecrs": False, "rtcb": False},
    {"start": "2023-06-10", "name": "ecrs", "hcap": 5000.0, "floor": -250.0, "ecrs": True, "rtcb": False},
    {"start": "2025-12-05", "name": "rtc+b", "hcap": 5000.0, "floor": -250.0, "ecrs": True, "rtcb": True},
)
ERA_NOTES = {
    "hcap": "PUCT HCAP $9,000/MWh through 2021-12-31, $5,000/MWh from 2022-01-01",
    "floor": "offer floor -$250/MWh",
    "ecrs": "ERCOT Contingency Reserve Service from 2023-06-10",
    "rtcb": "Real-Time Co-optimization plus Batteries from 2025-12-05",
    "lcap_epp": "LCAP/EPP apply to real time, not the DAM; not used in v1",
    "as_duration": None,
}
ECRS_START = dt.date(2023, 6, 10)
RTCB_START = dt.date(2025, 12, 5)


def _as_date(d: str | dt.date) -> dt.date:
    return d if isinstance(d, dt.date) else dt.date.fromisoformat(d)


def era(d: str | dt.date) -> dict:
    """The era row in force on date d."""
    d = _as_date(d)
    row = ERAS[0]
    for r in ERAS:
        if d >= dt.date.fromisoformat(r["start"]):
            row = r
    return dict(row)


AS_PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")
AS_ERAS = (
    {"era": "A", "start": "2021-01-01", "end": "2023-06-09", "products": ("regup", "regdn", "rrs", "nspin")},
    {"era": "B", "start": "2023-06-10", "end": "2025-12-04", "products": AS_PRODUCTS},
    {"era": "C", "start": "2025-12-05", "end": None, "products": AS_PRODUCTS},
)
AS_DURATION_H = {
    "A": {"regup": 1.0, "regdn": 1.0, "rrs": 1.0, "nspin": 4.0},
    "B": {"regup": 1.0, "regdn": 1.0, "rrs": 1.0, "ecrs": 2.0, "nspin": 4.0},
    "C": {"regup": 0.5, "regdn": 0.5, "rrs": 0.5, "ecrs": 1.0, "nspin": 4.0},
}
AS_DURATION_NOTES = {
    "A-B regup, regdn, rrs": "1 h, a conservative assumption (V3-D1, not settled from protocol text). NPRR1186 (in "
                             "force 2024-06-27) asks SoC to cover the AS responsibility for the rest of the operating "
                             "hour, 1 MWh per MW at the top of the hour",
    "B ecrs, A-B nspin": "2 h ECRS and 4 h Non-Spin sustained capability (NPRR1096)",
    "C": "NPRR1282 under RTC+B (PUCT-approved 2025-07-31): Reg and RRS 0.5 h, ECRS 1 h, Non-Spin 4 h",
}


def as_era(d: str | dt.date) -> str:
    """The v3 AS era on date d: A before ECRS, B from 2023-06-10, C (RTC+B) from 2025-12-05."""
    d = _as_date(d)
    return "C" if d >= RTCB_START else "B" if d >= ECRS_START else "A"


def as_products(d: str | dt.date) -> tuple[str, ...]:
    return next(r["products"] for r in AS_ERAS if r["era"] == as_era(d))


def as_duration_h(product: str, d: str | dt.date) -> float:
    """Hours of SoC held per MW of `product` award on date d; KeyError when the product does not exist that day."""
    return AS_DURATION_H[as_era(d)][product]


def price_violations(d: str | dt.date, prices) -> list[int]:
    """0-based hours whose price lies outside the era's [floor, hcap]."""
    e = era(d)
    return [h for h, p in enumerate(prices) if p < e["floor"] or p > e["hcap"]]


def ceil_to_interval(t, minutes: int = 15):
    """Round t up to the next interval boundary; t is a datetime or a number of minutes."""
    if isinstance(t, dt.datetime):
        base = t.replace(hour=0, minute=0, second=0, microsecond=0)
        us, step = (t - base) // dt.timedelta(microseconds=1), minutes * 60_000_000
        return base + dt.timedelta(microseconds=-(-us // step) * step)
    return math.ceil(t / minutes) * minutes


def freeze_time(interval_start: dt.datetime, hours: float = 1.0) -> dt.datetime:
    """The latest decision time for an interval under the v2 1 h freeze rule."""
    return interval_start - dt.timedelta(hours=hours)
