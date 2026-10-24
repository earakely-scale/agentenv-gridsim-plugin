"""v3 real-data inputs in data/hybrid/ (built by scripts/build_hybrid_inputs.py): DA AS clearing prices, the hourly
solar capacity factor, AS deployment events, the EIA-860 hybrid archetypes and the seeded regulation-drift fallback."""

from __future__ import annotations

import datetime as dt
import gzip
import json
import random
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from gridsim_core.contract import AS_PRODUCTS
from gridsim_core.task import data_root, stable_seed

CPT = ZoneInfo("America/Chicago")
DRIFT_SPEC = {
    "kind": "seeded fallback (V3-D8); system-level regulation fractions were not derived",
    "label": "Regulation drift is a seeded draw, not ERCOT telemetry",
    "distribution": "independent Beta per hour, mean m, concentration k: Beta(m*k, (1-m)*k)",
    "regup": {"mean": 0.12, "concentration": 6.0},
    "regdn": {"mean": 0.18, "concentration": 6.0},
    "seed": "gridsim_core.task.stable_seed(task_id + '|reg-drift'), random.Random",
    "units": "fraction of the hour's RegUp (RegDn) award energy delivered (absorbed) in that hour",
    "rounding": 4,
}
__all__ = ["AS_PRODUCTS", "DRIFT_SPEC", "archetypes", "as_prices", "deployments", "pv_profile_mw", "reg_drift",
           "solar_cf", "solar_row"]


def root() -> Path:
    return data_root() / "hybrid"


@lru_cache(maxsize=4)
def _by_date(name: str, base: str | None = None) -> dict[str, dict]:
    p = Path(base or root()) / name
    if not p.exists():
        return {}
    with gzip.open(p, "rt") as f:
        return {r["date"]: r for r in map(json.loads, f)}


def as_prices(date: str | dt.date, base: str | None = None) -> dict | None:
    """The day's DA MCPC row: {date, era, n_hours, source, regup, regdn, rrs, ecrs, nspin}, $/MW per hour; a product
    that did not exist that day (ECRS before 2023-06-10) is None. DST days carry `hour_ending` and 23 or 25 values."""
    return _by_date("as_dam_mcpc.jsonl.gz", base).get(str(date))


def solar_row(date: str | dt.date, base: str | None = None) -> dict | None:
    return _by_date("solar_cf.jsonl.gz", base).get(str(date))


def solar_cf(date: str | dt.date, region: str | None = None, base: str | None = None) -> list[float] | None:
    """Hourly PV availability capacity factor (availability / installed AC). System-wide ERCOT for every region: no
    regional history was available (`scope: "system"` in the row)."""
    row = solar_row(date, base)
    return None if row is None else row["cf"]


def pv_profile_mw(cf: list[float], mwac: float, ilr: float) -> list[float]:
    """The plan's plant PV availability at the battery's bus: AC nameplate x ILR x cf_t (clipping is the core's)."""
    return [round(mwac * ilr * c, 3) for c in cf]


@lru_cache(maxsize=2)
def _deployments(base: str | None = None) -> tuple[dict, ...]:
    p = Path(base or root()) / "deployments.jsonl"
    return tuple(json.loads(line) for line in p.read_text().splitlines()) if p.exists() else ()


def deployments(date: str | dt.date | None = None, base: str | None = None) -> list[dict]:
    """AS deployment events (rrs, ecrs, nspin) whose [start, end) overlaps operating day `date` (CPT), or all."""
    ev = _deployments(base)
    if date is None:
        return list(ev)
    d = dt.date.fromisoformat(str(date))
    d0 = dt.datetime.combine(d, dt.time(0), CPT)
    d1 = d0 + dt.timedelta(days=1)
    return [e for e in ev if dt.datetime.fromisoformat(e["start"]) < d1 and dt.datetime.fromisoformat(e["end"]) > d0]


def archetypes(base: str | None = None) -> dict:
    return json.loads((Path(base or root()) / "archetypes.json").read_text())


def reg_drift(task_id: str, n_hours: int = 24) -> dict:
    """The seeded regulation-drift fallback stored per task: hourly fractions of the RegUp and RegDn awards."""
    rng = random.Random(stable_seed(task_id + "|reg-drift"))
    out = {}
    for p, key in (("regup", "reg_up_frac"), ("regdn", "reg_dn_frac")):
        m, k = DRIFT_SPEC[p]["mean"], DRIFT_SPEC[p]["concentration"]
        out[key] = [round(rng.betavariate(m * k, (1 - m) * k), DRIFT_SPEC["rounding"]) for _ in range(n_hours)]
    return {**out, "source": "seeded"}
