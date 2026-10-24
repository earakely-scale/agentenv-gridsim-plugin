"""Task rows: battery construction, ids, regions and pack loading."""

from __future__ import annotations

import gzip
import hashlib
import json
import math
from pathlib import Path
from typing import NamedTuple

from gridsim_core.contract import CONTRACT_VERSION

REGIONS = {
    "HB_WEST": "west", "LZ_WEST": "west", "HB_PAN": "panhandle",
    "HB_NORTH": "north", "LZ_NORTH": "north", "LZ_RAYBN": "north",
    "HB_HOUSTON": "houston", "LZ_HOUSTON": "houston",
    "HB_SOUTH": "south", "LZ_SOUTH": "south", "LZ_CPS": "south",
    "LZ_AEN": "central", "LZ_LCRA": "central", "HB_BUSAVG": "central", "HB_HUBAVG": "central",
}
TIERS = ("foresight", "blind")


class Battery(NamedTuple):
    q: float
    k_dis: int
    k_ch: int
    n: int
    eta: float
    c_deg: float
    cap: int
    s0: int
    s_end_min: int


def battery_of(task_or_battery: dict) -> Battery:
    """The physics view of a task's battery dict."""
    b = task_or_battery.get("battery", task_or_battery)
    return Battery(float(b["unit_mwh"]), int(b["k_dis"]), int(b["k_ch"]), int(b["soc_levels"]), float(b["eta"]),
                   float(b["c_deg"]), int(b["cycle_cap_units"]), int(b["s0"]), int(b["s_end_min"]))


def make_battery(p_dis_mw: float, energy_mwh: float, k_dis: int, *, k_ch: int | None = None, eta: float = 0.85,
                 c_deg: float = 0.0, cycles: float = 1.0, s0: int | None = None, s_end_min: int | None = None,
                 archetype: str = "custom") -> dict:
    """A battery dict on the contract grid: q = p_dis/k_dis MWh per unit, N = E/q."""
    k_ch = k_dis if k_ch is None else k_ch
    q = p_dis_mw / k_dis
    n = round(energy_mwh / q)
    if abs(n * q - energy_mwh) > 1e-6 or not 1 <= n <= 16:
        raise ValueError(f"energy {energy_mwh} MWh is not a grid of N<=16 units of {q} MWh")
    s0 = n // 2 if s0 is None else s0
    return {"archetype": archetype, "source": "archetype" if archetype != "custom" else "custom",
            "p_dis_mw": p_dis_mw, "p_ch_mw": k_ch * q, "energy_mwh": energy_mwh, "unit_mwh": q, "q_15": q / 4,
            "k_dis": k_dis, "k_ch": k_ch, "soc_levels": n, "eta": eta, "c_deg": c_deg,
            "cycle_cap_units": math.floor(cycles * n + 0.5), "s0": s0,
            "s_end_min": s0 if s_end_min is None else s_end_min}


def make_task(prices, battery: dict, *, date: str = "2024-07-18", point: str = "HB_WEST", blind: dict | None = None,
              **extra) -> dict:
    """A minimal task row (no refs); grade() computes missing foresight refs on the fly."""
    arch = battery.get("archetype", "custom")
    return {"task_id": task_id(date, point, arch), "contract_version": CONTRACT_VERSION, "date": date,
            "settlement_point": point, "point_kind": point_kind(point), "region": REGIONS.get(point, "central"),
            "prices": [float(p) for p in prices], "blind": blind, "battery": battery, **extra}


def task_id(date: str, point: str, arch: str) -> str:
    return f"dam-v1-{date}-{point}-{arch}"


def point_kind(point: str) -> str:
    return "hub" if point.startswith("HB_") else "load_zone"


def data_root() -> Path:
    """The packs directory: the repo's data/ in a checkout, gridsim_core/data in a wheel."""
    here = Path(__file__).resolve().parent
    for p in (here / "data", here.parent.parent / "data"):
        if p.is_dir():
            return p
    return here.parent.parent / "data"


def load_pack(pack: str | Path) -> list[dict]:
    """Tasks of a pack by name (under data_root()) or by directory/file path."""
    p = Path(pack)
    if not p.exists():
        p = data_root() / str(pack)
    if p.is_dir():
        p = p / "tasks.jsonl.gz"
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def index_pack(pack: str | Path) -> dict[str, dict]:
    return {t["task_id"]: t for t in load_pack(pack)}


def stable_seed(s: str) -> int:
    """A 32-bit seed from a string, stable across runs and machines."""
    return int.from_bytes(hashlib.sha256(s.encode()).digest()[:4], "big")
