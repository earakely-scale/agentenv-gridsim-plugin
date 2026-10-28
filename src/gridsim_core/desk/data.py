"""Desk packs: task records, series documents, and the minute-indexed view the engine reads (contract section 1)."""

from __future__ import annotations

import datetime as dt
import gzip
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from gridsim_core.contract import RTCB_START
from gridsim_core.desk import clock
from gridsim_core.task import data_root

PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")
RT_LMP_LAG, RT_SPP_LAG = 1, 2


def pack_dir(pack: str) -> Path:
    p = Path(pack)
    return p if p.is_dir() else data_root() / "desk" / pack


def load_tasks(pack: str) -> list[dict]:
    with gzip.open(pack_dir(pack) / "tasks.jsonl.gz", "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_task(pack: str, task_id: str) -> dict:
    t = next((t for t in load_tasks(pack) if t["task_id"] == task_id), None)
    if t is None:
        raise KeyError(f"{task_id} not in {pack}")
    return t


def load_series(pack: str, task: dict) -> dict:
    path = pack_dir(pack) / task["series"]
    with gzip.open(path, "rt") if path.suffix == ".gz" else open(path) as f:
        return json.load(f)


def series_sha(series: dict) -> str:
    return hashlib.sha256(json.dumps(series, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def era_of(dates: list[str]) -> str:
    rt = [dt.date.fromisoformat(d) >= RTCB_START for d in dates]
    if any(rt) and not all(rt):
        raise ValueError(f"window {dates[0]}..{dates[-1]} straddles RTC+B go-live")
    return "rtcb" if rt[0] else "pre"


@dataclass
class Vintage:
    kind: str
    issued_at: int
    start: int
    step_min: int
    values: dict
    model: str = ""
    product: str = ""


@dataclass
class Series:
    """The operating days' prices on flat minute grids plus every timed item converted to minutes from D0 00:00."""

    d0: str
    dates: list[str]
    dam_spp: list[float]
    dam_spp_hub: list[float]
    rt_spp: list[float]
    rt_spp_hub: list[float]
    rt_lmp: list[float]
    dam_posted: list[int]
    history_dam: dict
    history_dam_hub: dict
    history_rt: dict
    history_lmp: dict
    system: dict
    forecasts: list[Vintage]
    outage_capacity: list[Vintage]
    desk_forecast: list[Vintage]
    unit_events: list[dict]
    notices: list[dict]
    nws: list[dict]
    deployments: list[dict]
    operator: dict
    raw: dict = field(repr=False, default_factory=dict)
    dam_mcpc: dict = field(default_factory=dict)
    rt_mcpc: dict = field(default_factory=dict)
    rt_mcpc_15: dict = field(default_factory=dict)
    asdc: dict = field(default_factory=dict)
    as_plan: dict = field(default_factory=dict)
    reg_up: list = field(default_factory=list)
    reg_dn: list = field(default_factory=list)
    reg_source: str = "none"
    pv: list = field(default_factory=list)
    history_mcpc: dict = field(default_factory=dict)
    history_rt_mcpc: dict = field(default_factory=dict)
    market: dict = field(default_factory=dict)

    @property
    def days(self) -> int:
        return len(self.dates)

    @property
    def end(self) -> int:
        return clock.DAY * self.days

    def dam_posted_at(self, day: int) -> int:
        return self.dam_posted[day]


def _flat(block: dict, dates: list[str], n: int, key: str) -> list[float]:
    out = []
    for d in dates:
        v = block.get(d)
        if v is None or len(v) != n or any(x is None for x in v):
            raise ValueError(f"series {key} for {d}: need {n} values")
        out += [float(x) for x in v]
    return out


def _vintages(rows, d0: str, kind_key: str = "kind") -> list[Vintage]:
    out = []
    for r in rows or []:
        vals = {k: r[k] for k in ("values", "p10", "p50", "p90") if k in r}
        out.append(Vintage(r.get(kind_key) or r.get("market") or "", int(round(clock.to_minutes(r["issued_at"], d0))),
                           int(round(clock.to_minutes(r["start"], d0))), int(r.get("step_min", 60)), vals,
                           r.get("model", ""), r.get("product", "")))
    return sorted(out, key=lambda v: (v.kind, v.issued_at))


def _timed(rows, d0: str, *keys) -> list[dict]:
    out = []
    for r in rows or []:
        r = dict(r)
        for k in keys:
            if r.get(k):
                r[f"t_{k}"] = clock.to_minutes(r[k], d0)
        out.append(r)
    return sorted(out, key=lambda r: r.get(f"t_{keys[0]}", 0))


def _by_product(block: dict, dates: list[str], n: int) -> dict[str, list]:
    """{product: flat list over `dates`} for products present on every date (missing values become None)."""
    if not block or not all(d in block for d in dates):
        return {}
    keys = set.intersection(*(set(block[d]) for d in dates))
    out = {}
    for k in PRODUCTS:
        if k in keys:
            vals = []
            for d in dates:
                v = block[d][k]
                vals += list(v) if v is not None and len(v) == n else [None] * n
            out[k] = vals
    return out


def _ancillary(ser: Series, series: dict, dates: list[str], hist: list[str]) -> None:
    ser.dam_mcpc = {k: [float(x or 0.0) for x in v] for k, v in _by_product(series.get("dam_mcpc"), dates, 24).items()}
    ser.rt_mcpc = {k: [float(x or 0.0) for x in v] for k, v in _by_product(series.get("rt_mcpc"), dates, 288).items()}
    ser.rt_mcpc_15 = {k: [float(x or 0.0) for x in v]
                      for k, v in _by_product(series.get("rt_mcpc_15"), dates, 96).items()}
    ser.asdc = _by_product(series.get("asdc"), dates, 24)
    ser.as_plan = _by_product(series.get("as_plan"), dates, 24)
    reg = series.get("reg_deploy") or {}
    if all(d in reg for d in dates):
        ser.reg_up = [float(x) for d in dates for x in reg[d]["up"]]
        ser.reg_dn = [float(x) for d in dates for x in reg[d]["dn"]]
        ser.reg_source = reg[dates[0]].get("source", "measured")
    pv = series.get("pv") or {}
    if all(d in pv for d in dates):
        ser.pv = [float(x or 0.0) for d in dates for x in pv[d]]
    ser.history_mcpc = {d: series["dam_mcpc"][d] for d in hist if d in (series.get("dam_mcpc") or {})}
    ser.history_rt_mcpc = {d: series["rt_mcpc_15"][d] for d in hist if d in (series.get("rt_mcpc_15") or {})}
    ser.market = {d: series["market"][d] for d in dates if d in (series.get("market") or {})}


def build(task: dict, series: dict) -> Series:
    d0, dates = series["d0"], task["dates"]
    if d0 != dates[0]:
        raise ValueError(f"series d0 {d0} != task dates[0] {dates[0]}")
    posted = (series.get("posted") or {}).get("dam") or {}
    dam_posted = [int(round(clock.to_minutes(posted[d], d0))) if d in posted else j * clock.DAY + clock.DAM_RESULTS
                  for j, d in enumerate(dates)]
    hist = [d for d in series.get("history_days", []) if d not in dates]
    dam_hub = series.get("dam_spp_hub") or {}
    rt_hub = series.get("rt_spp_hub") or {}
    ser = Series(
        d0=d0, dates=list(dates),
        dam_spp=_flat(series["dam_spp"], dates, 24, "dam_spp"),
        dam_spp_hub=_flat(dam_hub, dates, 24, "dam_spp_hub") if all(d in dam_hub for d in dates) else [],
        rt_spp=_flat(series["rt_spp"], dates, 96, "rt_spp"),
        rt_spp_hub=_flat(rt_hub, dates, 96, "rt_spp_hub") if all(d in rt_hub for d in dates) else [],
        rt_lmp=_flat(series["rt_lmp"], dates, 288, "rt_lmp"),
        dam_posted=dam_posted,
        history_dam={d: series["dam_spp"][d] for d in hist if d in series["dam_spp"]},
        history_dam_hub={d: dam_hub[d] for d in hist if d in dam_hub},
        history_rt={d: series["rt_spp"][d] for d in hist if d in series.get("rt_spp", {})},
        history_lmp={d: series["rt_lmp"][d] for d in hist if d in series.get("rt_lmp", {})},
        system=series.get("system") or {},
        forecasts=_vintages(series.get("forecasts"), d0),
        outage_capacity=_vintages([dict(r, kind="outages") for r in series.get("outage_capacity") or []], d0),
        desk_forecast=_vintages(series.get("desk_forecast"), d0, kind_key="market"),
        unit_events=_timed(series.get("unit_events"), d0, "start", "end"),
        notices=_timed(series.get("notices"), d0, "issued_at"),
        nws=_timed(series.get("nws"), d0, "issued_at", "expires"),
        deployments=_timed(series.get("deployments"), d0, "start", "end"),
        operator=series.get("operator") or {},
        raw=series,
    )
    _ancillary(ser, series, list(dates), hist)
    return ser
