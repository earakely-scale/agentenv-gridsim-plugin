"""GridSimEnv v3 "Sun, Storage and Reserves": a solar farm and a battery behind one meter, co-optimised across energy and
five ancillary services on a live ERCOT day, in v2's watches on the virtual clock, graded against a rolling MILP (HiGHS).

Session is the only v3 state machine: the gridsim-hybrid env wraps it and path B' training imports it. Hours are 0..23
(HE01..HE24, CPT) and times are minutes from D 00:00 as in v2; MW held for one hour is MWh and SoC is continuous. The rules
and their provisional decisions (C3-D*) are in docs/CONTRACT-v3.md."""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import NamedTuple

import numpy as np

from gridsim_core import hybrid_inputs, live
from gridsim_core.contract import AS_DURATION_H, DEGENERATE_EPS, P_FLOOR, as_era
from gridsim_core.grade import reward_value
from gridsim_core.live import (
    CLOCK_URI,
    DAY_END,
    END_DAY_URI,
    LIVE_LOAD_URI,
    MAX_TURNS,
    NOTICE_TOOL,
    PLANNING_CALLS,
    Notice,
    WatchDay,
    _dump,
    freeze_line,
    hhmm,
    label,
    to_minutes,
)
from gridsim_core.lp import highspy
from gridsim_core.task import REGIONS, point_kind

HYBRID_VERSION = "3.0"
HYBRID_ENV = "gridsim-hybrid"
EPISODE_SCHEMA = "gridsim.episode/v3"
TIERS = ("energy", "reserves", "rtcb")
PRODUCTS = ("regup", "regdn", "rrs", "ecrs", "nspin")
UP = ("regup", "rrs", "ecrs", "nspin")
EVENT_PRODUCTS = ("rrs", "ecrs", "nspin")
FIELDS = ("energy",) + PRODUCTS
NAMES = {"energy": "energy", "regup": "RegUp", "regdn": "RegDn", "rrs": "RRS", "ecrs": "ECRS", "nspin": "Non-Spin"}
TOOLS = ("get_situation", "check_schedule", "commit_schedule", "advance")
PLANNING_TOOLS = ("check_schedule", "commit_schedule")
HOURS = 24
TOL = 1e-4
EQ_TOL = 0.005
REG_MEAN = {"up": 0.12, "dn": 0.18}
SOFT_PENALTY = 1e5
CASH_KEYS = ("energy_da", "energy_rt", "as_da", "as_rt", "deployment_energy", "degradation", "ftp", "excused",
             "end_penalty")
ARCHETYPES = {
    "arch-dc150": {"coupling": "dc", "pv_mwac": 150.0, "pv_mwdc": 195.0, "ilr": 1.3, "poi_mw": 150.0,
                   "poi_import_mw": 150.0, "inverter_mw": 150.0, "flags": {"poi": "default", "coupling": "assumed"}},
    "arch-ac150": {"coupling": "ac", "pv_mwac": 150.0, "pv_mwdc": 195.0, "ilr": 1.3, "poi_mw": 150.0,
                   "poi_import_mw": 150.0, "inverter_mw": None, "flags": {"poi": "default", "coupling": "assumed"}},
    "arch-ac125": {"coupling": "ac", "pv_mwac": 150.0, "pv_mwdc": 195.0, "ilr": 1.3, "poi_mw": 125.0,
                   "poi_import_mw": 125.0, "inverter_mw": None, "flags": {"poi": "1.2x", "coupling": "assumed"}},
}


def _r2(x: float) -> float:
    return round(float(x), 2) + 0.0


def _r6(x: float) -> float:
    return round(float(x), 6) + 0.0


def _num(x: float):
    """A plan value as JSON: an int when whole, else 2 decimals."""
    return int(round(x)) if abs(x - round(x)) < 1e-9 else _r2(x)


# the site, the day's inputs and the task row


class Site(NamedTuple):
    p: float
    e: float
    u: float
    eta: float
    c_deg: float
    cap: float
    s0: float
    s_end: float
    meter: float
    meter_imp: float


def site_of(task: dict) -> Site:
    st, b = task["site"], task["site"]["bess"]
    exp, imp = float(st["poi_mw"]), float(st.get("poi_import_mw") or st["poi_mw"])
    if st["coupling"] == "dc" and st.get("inverter_mw"):
        exp, imp = min(exp, float(st["inverter_mw"])), min(imp, float(st["inverter_mw"]))
    return Site(float(b["p_mw"]), float(b["e_mwh"]), float(b["unit_mw"]), float(b["eta"]), float(b["c_deg"]),
                float(b["cycle_cap_mwh"]), float(b["s0_mwh"]), float(b["s_end_min_mwh"]), exp, imp)


class Day(NamedTuple):
    era: str
    pv: np.ndarray
    da: np.ndarray
    rt: np.ndarray
    mda: dict
    mrt: dict | None
    reg_up: np.ndarray
    reg_dn: np.ndarray
    mean_up: float
    mean_dn: float
    dur: dict
    era_products: tuple
    offered: tuple
    qualified: tuple
    pen: float


def day_of(task: dict, tier: str) -> Day:
    """The day's arrays for a tier: AS are offered only outside the energy tier, for the era's products with prices."""
    era = task.get("era") or as_era(task["date"])
    dur = dict(AS_DURATION_H[era])
    eps = tuple(k for k in PRODUCTS if k in dur)
    mda = {k: np.asarray(v, dtype=float) for k, v in (task.get("mcpc_da") or {}).items() if k in eps}
    mrt = task.get("mcpc_rt")
    mrt = {k: np.asarray(v, dtype=float) for k, v in mrt.items() if k in eps} if mrt else None
    offered = () if tier == "energy" else tuple(k for k in eps if k in mda)
    reg = task.get("reg") or {}
    cu, cd = min(1.0, dur.get("regup", 1.0)), min(1.0, dur.get("regdn", 1.0))
    st = task["site"]
    da = np.asarray(task["prices"], dtype=float)
    return Day(era, np.asarray(task["pv_mw"], dtype=float), da, np.asarray(task["rt"], dtype=float), mda, mrt,
               np.minimum(cu, np.asarray(reg.get("up") or [0.0] * HOURS, dtype=float)),
               np.minimum(cd, np.asarray(reg.get("dn") or [0.0] * HOURS, dtype=float)),
               min(cu, float(reg.get("mean_up", REG_MEAN["up"]))), min(cd, float(reg.get("mean_dn", REG_MEAN["dn"]))),
               dur, eps, offered, tuple(st.get("qualified") or eps),
               max(float(da.max()), P_FLOOR) / float(st["bess"]["eta"]))


def make_site(site_id: str = "arch-dc150", *, p_mw: float = 100.0, e_mwh: float = 200.0, unit_mw: float = 25.0,
              eta: float = 0.85, c_deg: float = 4.0, cycles: float = 1.5, s0_frac: float = 0.5, qualified=None,
              **over) -> dict:
    """An archetype site row (FD-4322: PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh, POI 150 MW)."""
    base = dict(ARCHETYPES.get(site_id, ARCHETYPES["arch-dc150"])) | over
    s0 = round(s0_frac * e_mwh, 6)
    return {"site_id": site_id, "source": "archetype", **base,
            "bess": {"p_mw": p_mw, "e_mwh": e_mwh, "unit_mw": unit_mw, "k": round(p_mw / unit_mw), "eta": eta,
                     "c_deg": c_deg, "cycle_cap_mwh": cycles * e_mwh, "s0_mwh": s0, "s_end_min_mwh": s0},
            "qualified": list(qualified) if qualified is not None else list(PRODUCTS),
            "flags": {"pv": "proxy", **base.get("flags", {})}}


def pv_at_bus(site: dict, cf) -> list[float]:
    """PV at the battery's bus: DC at the shared inverter for dc-coupled sites, AC after the PV inverters for ac."""
    dc = [site["pv_mwac"] * site.get("ilr", 1.3) * max(0.0, float(c)) for c in cf]
    return [round(x if site["coupling"] == "dc" else min(site["pv_mwac"], x), 3) for x in dc]


def reg_of(task_id: str) -> dict:
    """The task's regulation drift (V3-D8): lane D3's seeded draw, stored in the row so episodes replay exactly."""
    r = hybrid_inputs.reg_drift(task_id)
    return {"up": r["reg_up_frac"], "dn": r["reg_dn_frac"], "mean_up": hybrid_inputs.DRIFT_SPEC["regup"]["mean"],
            "mean_dn": hybrid_inputs.DRIFT_SPEC["regdn"]["mean"], "source": r["source"],
            "label": hybrid_inputs.DRIFT_SPEC["label"]}


def site_from_archetype(arch: dict, poi_mw: float | None = None, *, c_deg: float = 4.0, qualified=None) -> dict:
    """A site row from one of lane D3's EIA-860 archetypes (AC-coupled, C3-D15), at its POI or a variant."""
    poi = float(poi_mw if poi_mw is not None else arch["poi_mw"])
    return make_site(f"{arch['id']}-poi{poi:g}", p_mw=float(arch["bess_mw"]), e_mwh=float(arch["bess_mwh"]),
                     c_deg=c_deg, qualified=qualified, coupling="ac", pv_mwac=float(arch["pv_mwac"]),
                     pv_mwdc=float(arch["pv_mwdc"]), ilr=float(arch["ilr"]), poi_mw=poi, poi_import_mw=poi,
                     inverter_mw=None, flags={"poi": "default" if poi == float(arch["poi_mw"]) else "1.2x",
                                              "coupling": "ac (EIA-860 shows no dc-coupled ERCO sites)"})


def task_id(date: str, point: str, site_id: str) -> str:
    return f"hyb-v3-{date}-{point}-{site_id}"


def make_task(date: str, point: str, site: dict, prices, rt, pv_cf, mcpc_da: dict, mcpc_rt: dict | None = None, *,
              notices=(), deployments=(), **extra) -> dict:
    """A task row without refs (Session computes them on demand)."""
    era = as_era(date)
    tid = task_id(date, point, site["site_id"])
    return {"task_id": tid, "hybrid_version": HYBRID_VERSION, "contract_version": "1.0", "date": date, "era": era,
            "settlement_point": point, "point_kind": point_kind(point), "region": REGIONS.get(point, "central"),
            "site": site, "prices": [float(p) for p in prices], "rt": [float(p) for p in rt],
            "pv_cf": [round(float(c), 5) for c in pv_cf], "pv_mw": pv_at_bus(site, pv_cf),
            "mcpc_da": {k: [float(x) for x in v] for k, v in mcpc_da.items()},
            "mcpc_rt": {k: [float(x) for x in v] for k, v in mcpc_rt.items()} if mcpc_rt else None,
            "reg": reg_of(tid), "notices": list(notices), "deployments": list(deployments),
            "flags": {"pv_availability": "proxy", "reg_drift": "seeded", "poi": site.get("flags", {}).get("poi"),
                      "site": site.get("source", "archetype")}, **extra}


# events: notices plus deployments


def events_of(task: dict, notices=None, deployments=None) -> list[dict]:
    """The day's v2 notices plus one deployment notice per deployment, carrying its deploy payload."""
    ns = list(task.get("notices") or []) if notices is None else list(notices)
    ds = list(task.get("deployments") or []) if deployments is None else list(deployments)
    return ns + [_deploy_notice(d, task["date"]) for d in ds]


def _deploy_notice(d: dict, date: str) -> dict:
    if d.get("product") not in EVENT_PRODUCTS:
        raise ValueError(f"deployment {d.get('event_id')}: product must be one of {', '.join(EVENT_PRODUCTS)}")
    start = d["start_min"] if "start_min" in d else math.floor(to_minutes(d["start"], date))
    end = d["end_min"] if "end_min" in d else math.ceil(to_minutes(d["end"], date))
    frac = min(1.0, max(0.0, float(d.get("frac", 1.0))))
    name = NAMES[d["product"]]
    title = d.get("title") or f"{name} deployed"
    text = d.get("text") or (f"ERCOT deployed {name} at {frac:.0%} of awards from {hhmm(int(start) % DAY_END)} to "
                             f"{hhmm(int(end) % DAY_END if int(end) < DAY_END else DAY_END)}.")
    return {"event_id": d["event_id"], "source": d.get("source") or "ERCOT", "kind": "deployment",
            "level": d.get("level"), "issued_at": d["issued_at"], "name": d.get("name") or "ERCOT", "title": title,
            "text": text, "deploy": {"product": d["product"], "frac": frac, "start_min": int(start),
                                     "end_min": int(end)}}


def events_sha(task: dict, notices=None, deployments=None) -> str:
    return live.notices_sha(events_of(task, notices, deployments))


def schedule(task: dict, tier: str = "reserves", notices=None, deployments=None) -> list[live.Watch]:
    """v2's watches (the regular five plus notice and deployment watches, 1 h freeze) for the day's events."""
    return live.schedule(task, "foresight", events_of(task, notices, deployments))


def triggers(watches: list[live.Watch]) -> list[dict]:
    return live.triggers(watches)


def deploy_hours(payloads, dur: dict) -> list[dict]:
    """Fraction-hours each event product deploys in each hour: frac over the first dur_k hours of its window."""
    out = [dict.fromkeys(EVENT_PRODUCTS, 0.0) for _ in range(HOURS)]
    for d in payloads:
        k = d["product"]
        if k not in dur:
            continue
        a, b = max(0, d["start_min"]), min(DAY_END, d["end_min"], d["start_min"] + round(dur[k] * 60))
        for h in range(HOURS):
            ov = max(0, min(b, 60 * h + 60) - max(a, 60 * h))
            if ov:
                out[h][k] = min(1.0, out[h][k] + d["frac"] * ov / 60)
    return out


# one hour of plant physics, shared by the projection, settlement and the rule checks


def r_up(dur: dict, a: dict) -> float:
    return sum(dur.get(k, 0.0) * a[k] for k in UP)


def r_dn(st: Site, dur: dict, a: dict) -> float:
    return st.eta * dur.get("regdn", 0.0) * a["regdn"]


def _inv(S: float, y: float, eta: float) -> float:
    """The base move that ends the hour at SoC y from S."""
    return S - y if S >= y else (S - y) / eta


def step(st: Site, dur: dict, S: float, cyc: float, e: float, a: dict, s: float, price: float, U: float,
         D: float) -> dict:
    """One hour: the governor (C3-D6), the AS shortfall (C3-D8), deployments limited by SoC (C3-D9) and the
    controller's PV curtailment (C3-D4). U and D are the requested up and down deployment MWh."""
    S, s, price, U, D = float(S), float(s), float(price), float(U), float(D)
    up, rd = sum(a[k] for k in UP), a["regdn"]
    rup, rdn = r_up(dur, a), r_dn(st, dur, a)
    lo = max(-st.p, -st.p + rd, -st.meter_imp + rd, -(st.e - S) / st.eta)
    hi = min(st.p, st.p - up, st.meter - up, S, st.cap - cyc)
    hi = max(hi, lo)
    band_lo, band_hi = _inv(S, st.e - rdn, st.eta), _inv(S, rup, st.eta)
    blo, bhi = max(lo, band_lo), min(hi, band_hi)
    if blo <= bhi + TOL:
        b = e if blo - TOL <= e <= bhi + TOL else min(max(e, blo), bhi)
    elif band_lo > band_hi + TOL:
        b = min(max(e, lo), hi)
    else:
        b = hi if band_lo > hi else lo
    dis, ch = max(b, 0.0), max(-b, 0.0)
    B = min(st.e, max(0.0, S - dis + st.eta * ch))
    cover, room = min(S, B), st.e - max(S, B)
    f = 1.0 if rup <= TOL or cover >= rup - TOL else max(0.0, cover / rup)
    g = 1.0 if rdn <= TOL or room >= rdn - TOL else max(0.0, room / rdn)
    short = {k: (1 - f) * a[k] for k in UP if a[k] > 0 and f < 1}
    if rd > 0 and g < 1:
        short["regdn"] = (1 - g) * rd
    u_del = min(U, B)
    d_del = max(0.0, min(D, (st.e - B + u_del) / st.eta))
    pv = 0.0 if price < 0 else min(s, max(0.0, st.meter - b - up))
    return {"b": b, "B": B, "S": B - u_del + st.eta * d_del, "dis": dis, "pv": pv, "x": pv + b + u_del - d_del,
            "up_mwh": u_del, "dn_mwh": d_del, "short": short, "governed": bool(abs(b - e) > TOL),
            "clip_rec": max(0.0, pv - st.meter), "clippable": max(0.0, s - st.meter), "curtailed": s - pv,
            "margin": min(cover - rup, st.e - rdn - max(S, B))}


def x_da_of(st: Site, s: float, da: float, e: float, a: dict) -> float:
    """The DA position of an hour's book entry (C3-D3): PV at DA (curtailed at negative DA prices or to keep the meter
    and up-award headroom) plus the base move."""
    up = sum(a[k] for k in UP)
    return (0.0 if da < 0 else min(s, max(0.0, st.meter - e - up))) + e


# the plan format


class PlanError(ValueError):
    def __init__(self, field: str, msg: str):
        super().__init__(msg)
        self.field = field

    def row(self) -> dict:
        return {"hour": None, "field": self.field, "rule": "parse", "detail": str(self)}


_HOUR = re.compile(r"^\s*(\d{1,2})(?::00)?\s*$")


def _from_hour(v) -> int:
    if isinstance(v, bool):
        raise PlanError("from_hour", f"from_hour must be an hour 0..23, got {v!r}")
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, str) and (m := _HOUR.match(v)):
        v = int(m.group(1))
    if not isinstance(v, int) or not 0 <= v < HOURS:
        raise PlanError("from_hour", f"from_hour must be an hour 0..23, got {v!r}")
    return v


def _number(v, field: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise PlanError(field, f"{field}: not a number: {v!r}")
    return float(v)


def _values(field: str, v, fh: int) -> list[float]:
    n = HOURS - fh
    if isinstance(v, dict):
        v = [v]
    if isinstance(v, str):
        s = v.strip().removeprefix("[").removesuffix("]")
        toks = [t for t in re.split(r"[\s,]+", s) if t]
        try:
            v = [float(t) for t in toks]
        except ValueError:
            raise PlanError(field, f"{field}: expected numbers, got {v[:60]!r}") from None
    if not isinstance(v, list):
        raise PlanError(field, f"{field}: expected a list of MW values or blocks, got {type(v).__name__}")
    if not v:
        return [0.0] * n
    if all(isinstance(b, dict) for b in v):
        out = [0.0] * n
        seen = set()
        for b in v:
            if set(b) != {"from", "to", "mw"}:
                raise PlanError(field, f'{field}: a block is {{"from": h, "to": h, "mw": v}}, got {json.dumps(b)[:80]}')
            h1, h2 = b["from"], b["to"]
            if isinstance(h1, bool) or isinstance(h2, bool) or not isinstance(h1, int) or not isinstance(h2, int):
                raise PlanError(field, f"{field}: block hours must be integers, got {h1!r}..{h2!r}")
            if not fh <= h1 < h2 <= HOURS:
                raise PlanError(field, f"{field}: block {h1}..{h2} must satisfy {fh} <= from < to <= 24")
            if seen & set(range(h1, h2)):
                raise PlanError(field, f"{field}: blocks overlap at hour {min(seen & set(range(h1, h2)))}")
            seen |= set(range(h1, h2))
            mw = _number(b["mw"], field)
            for h in range(h1, h2):
                out[h - fh] = mw
        return out
    vals = [_number(x, field) for x in v]
    if len(vals) == HOURS and fh:
        vals = vals[fh:]
    if len(vals) != n:
        raise PlanError(field, f"{field}: expected {n} values (hours {fh}..23) or 24, got {len(vals)}")
    return vals


def parse_plan(plan, from_hour) -> tuple[int, dict[str, list[float]]]:
    """(from_hour, {field: MW values for hours from_hour..23}); omitted AS fields keep the book."""
    fh = _from_hour(from_hour)
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            raise PlanError("plan", "plan: not a JSON object") from None
    if not isinstance(plan, dict):
        raise PlanError("plan", f"plan: expected an object with energy and AS fields, got {type(plan).__name__}")
    extra = sorted(set(plan) - set(FIELDS))
    if extra:
        raise PlanError("plan", f"plan: unknown field {extra[0]!r}; fields are {', '.join(FIELDS)}")
    if "energy" not in plan:
        raise PlanError("energy", "plan: energy is required")
    return fh, {f: _values(f, v, fh) for f, v in plan.items() if v is not None}


# the session


class Session(WatchDay):
    """One live hybrid site-day. Drive it through call() so outputs, messages and the transcript match path A."""

    TOOLS = TOOLS
    NOTICE_ARGS = WatchDay.NOTICE_ARGS + ("deploy",)
    RT_MINUTES = 60

    def __init__(self, task: dict, tier: str = "reserves", notices=None, deployments=None, *, reference: bool = False):
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; tiers are {', '.join(TIERS)}")
        self.task, self.tier, self.date, self.reference = task, tier, task["date"], reference
        self.notices_in = list(task.get("notices") or []) if notices is None else list(notices)
        self.deployments_in = list(task.get("deployments") or []) if deployments is None else list(deployments)
        events = events_of(task, self.notices_in, self.deployments_in)
        self.site, self.day = site_of(task), day_of(task, tier)
        if tier == "rtcb" and (self.day.era != "C" or self.day.mrt is None):
            raise ValueError(f"{task['task_id']} is not an rtcb day (era C with RT MCPC)")
        if tier != "energy" and not self.day.offered:
            raise ValueError(f"{task['task_id']} has no DA AS prices; only the energy tier loads")
        self.watches = live.schedule(task, "foresight", events)
        self.scheduled = {n.event_id: (n, w.index) for w in self.watches for n in w.notices}
        self.dep_real = deploy_hours([n.deploy for n in (live.parse_notice(x, self.date) for x in events)
                                      if n.deploy], self.day.dur)
        self._dep_cache: tuple[int, list[dict]] | None = None
        self.done, self.end_reason = False, None
        self.watch, self.calls, self.planning_calls = 0, 0, [0]
        self.book = {f: [0] * HOURS for f in FIELDS}
        self.da: dict | None = None
        self.S, self.cyc = self.site.s0, 0.0
        self.soc_hist = [self.site.s0]
        self.rows: list[dict] = []
        self.cash = dict.fromkeys(CASH_KEYS, 0.0)
        self.snap: list[dict | None] = [None] * HOURS
        self.end_snap: float | None = None
        self.end_short = self.end_short_charged = 0.0
        self.governor: list[dict] = []
        self.excused: list[dict] = []
        self.refusals: list[dict] = []
        self.commits: list[dict] = []
        self._init_watch_log()
        self.frozen = [self._frozen_row()]
        self._grade: dict | None = None
        self._refs: dict | None = None
        for n in self.watches[0].notices:
            self.notice(**self._kw(n), via="load")

    # clock and state

    @property
    def minute(self) -> int:
        return DAY_END if self.done else self.watches[self.watch].minute

    @property
    def last(self) -> bool:
        return self.watch == len(self.watches) - 1

    @property
    def settled(self) -> int:
        return len(self.rows)

    @property
    def first_open(self) -> int:
        return HOURS if self.done else min(HOURS, max(0, freeze_line(self.minute) // 60))

    @property
    def calls_left(self) -> int:
        return PLANNING_CALLS - self.planning_calls[-1]

    def watch_time_utc(self, k: int) -> str:
        return self.watches[k].time_utc

    def status(self) -> str:
        fo = self.first_open
        return "".join("S" if h < self.settled else "F" if h < fo else "O" for h in range(HOURS))

    def entry(self, h: int, book: dict | None = None) -> tuple[float, dict]:
        book = self.book if book is None else book
        return float(book["energy"][h]), {k: float(book[k][h]) for k in PRODUCTS}

    def a_da(self, h: int, book: dict | None = None) -> dict:
        if self.da is not None:
            return {k: float(self.da[k][h]) for k in PRODUCTS}
        return self.entry(h, book)[1]

    def x_da(self, h: int, book: dict | None = None) -> float:
        if self.da is not None:
            return float(self.da["x_da"][h])
        e, a = self.entry(h, book)
        return x_da_of(self.site, self.day.pv[h], self.day.da[h], e, a)

    def profit(self) -> float:
        c = self.cash
        return float(c["energy_da"] + c["energy_rt"] + c["as_da"] + c["as_rt"] - c["degradation"] - c["ftp"]
                     - c["end_penalty"])

    def cash_out(self) -> dict:
        return {k: _r2(v) for k, v in self.cash.items()} | {"total": _r2(self.profit())}

    def _frozen_row(self) -> dict:
        return {"watch": self.watch, "time": label(self.minute, self.date),
                "freeze_line": label(freeze_line(self.minute), self.date), "frozen_until_hour": self.first_open,
                "call": self.calls}

    def _msg(self, n: Notice, minute: int) -> dict:
        out = {"time": label(minute, self.date), "issued_at": label(n.issued, self.date), "event_id": n.event_id,
               "source": n.source, "level": n.level, "name": n.name, "title": n.title, "text": n.text}
        return out if n.deploy is None else out | {"deploy": self._deploy_row(n)}

    def _deploy_row(self, n: Notice) -> dict:
        d = n.deploy
        return {"event_id": n.event_id, "product": d["product"], "frac": d["frac"],
                "from": hhmm(max(0, d["start_min"]) % DAY_END), "until": hhmm(min(DAY_END, d["end_min"]))}

    def _dep_known(self) -> list[dict]:
        if self._dep_cache is None or self._dep_cache[0] != len(self.delivered):
            pays = [self.scheduled[e][0].deploy for e in self.delivered if self.scheduled[e][0].deploy]
            self._dep_cache = (len(self.delivered), deploy_hours(pays, self.day.dur))
        return self._dep_cache[1]

    # the agent's tools

    def _dispatch(self, tool: str, args: dict) -> dict:
        want = {"get_situation": (), "advance": (), "check_schedule": ("plan", "from_hour"),
                "commit_schedule": ("plan", "from_hour")}[tool]
        extra = sorted(set(args) - set(want))
        missing = [k for k in want if k != "from_hour" and k not in args]
        if extra or missing:
            bad = f"unexpected argument {extra[0]!r}" if extra else f"missing argument {missing[0]!r}"
            if tool in PLANNING_TOOLS and not self.done and self.calls_left:
                self.planning_calls[-1] += 1
            return {"error": f"{tool}: {bad}", "calls_left": self.calls_left}
        return getattr(self, tool)(**args)

    def _log_rt(self, out: dict):
        hrs = out.get("hours") or {}
        n = len(hrs.get("rt_usd") or [])
        for v in (hrs.get("mcpc_rt") or {}).values():
            n = max(n, len(v))
        if out.get("realized"):
            n = max(n, max(r["h"] for r in out["realized"]) + 1)
        self.rt_log.append({"call": self.calls, "minute": self.minute, "rt_shown": n})

    def situation(self) -> dict:
        t, st, d = self.task, self.site, self.day
        n = self.settled
        proj = self._project()
        out = {"task_id": t["task_id"], "tier": self.tier, "date": self.date, "era": d.era,
               "settlement_point": t["settlement_point"], "site_id": t["site"]["site_id"], "region": t.get("region"),
               "watch": self.watch, "time": label(self.minute, self.date), "frozen_until_hour": self.first_open,
               "calls_left": 0 if self.done else self.calls_left, "day_over": self.done,
               "site": {"coupling": t["site"]["coupling"], "pv_mwac": t["site"]["pv_mwac"],
                        "pv_mwdc": t["site"]["pv_mwdc"], "meter_mw": st.meter, "meter_import_mw": st.meter_imp,
                        "p_mw": st.p, "e_mwh": st.e, "unit_mw": st.u, "eta": st.eta, "c_deg": st.c_deg,
                        "cycle_cap_mwh": st.cap, "s_end_min_mwh": st.s_end},
               "as_rules": {"products": list(d.offered), "qualified": [k for k in d.offered if k in d.qualified],
                            "duration_h": {k: d.dur[k] for k in d.offered},
                            "reg_drift_mean": {"regup": d.mean_up, "regdn": d.mean_dn} if d.offered else {},
                            "as_fixed_after_watch_0": self.tier == "reserves"},
               "hours": {"pv_mw": [round(float(x), 1) for x in d.pv], "da_usd": [_r2(x) for x in d.da],
                         "rt_usd": [_r2(x) for x in d.rt[:n]],
                         "mcpc_da": {k: [_r2(x) for x in d.mda[k]] for k in d.offered},
                         "mcpc_rt": {k: [_r2(x) for x in d.mrt[k][:n]] for k in d.offered if k in d.mrt}
                         if d.mrt and self.tier == "rtcb" else None},
               "soc_mwh": _r2(self.S), "discharged_mwh": _r2(self.cyc), "status": self.status(),
               "book": self._book_out(),
               "da": None if self.da is None else {"x_da_mw": [_r2(x) for x in self.da["x_da"]]} | {
                   k: [_num(x) for x in self.da[k]] for k in d.offered},
               "projected": proj["summary"] | {"soc_mwh": proj["soc"], "reserve_margin_mwh": proj["margin"]},
               "cash": self.cash_out(),
               "deployments": [self._deploy_row(self.scheduled[e][0]) for e in self.delivered
                               if self.scheduled[e][0].deploy],
               "notices": [self._msg(self.scheduled[e["event_id"]][0], e["minute"]) for e in self.log if e["first"]]}
        if self.done:
            out["result"] = self._done_result()
        return out

    def get_situation(self) -> dict:
        return self.situation()

    def _book_out(self, book: dict | None = None) -> dict:
        book = self.book if book is None else book
        return {f: [_num(x) for x in book[f]] for f in ("energy",) + self.day.offered}

    def _planning(self) -> dict | None:
        if self.done:
            return {"error": "the day is over", "calls_left": 0}
        if not self.calls_left:
            return {"error": f"no planning calls left in this watch ({PLANNING_CALLS} used): call advance",
                    "calls_left": 0}
        self.planning_calls[-1] += 1
        return None

    def _issue(self, h, field, rule, detail) -> dict:
        return {"hour": h, "field": field, "rule": rule, "detail": detail}

    def rules(self, h: int, S: float, cyc: float, e: float, a: dict) -> list[dict]:
        """The rule failures of one hour's entry on the SoC path that reaches it (C3-D5)."""
        st, d = self.site, self.day
        out = []
        for f, v in (("energy", e),) + tuple((k, a[k]) for k in PRODUCTS):
            if f == "energy" and abs(v) > st.p + TOL:
                out.append(self._issue(h, f, "power", f"{_num(abs(v))} MW > {_num(st.p)} MW"))
            elif f != "energy" and (v < 0 or v > st.p + TOL):
                out.append(self._issue(h, f, "power", f"{NAMES[f]} {_num(v)} MW is outside 0..{_num(st.p)} MW"))
            elif f != "energy" and v and f not in d.offered:
                why = "the energy tier has no AS" if self.tier == "energy" else f"{NAMES[f]} is not offered on {self.date}"
                out.append(self._issue(h, f, "not_offered", why))
            elif f != "energy" and v and f not in d.qualified:
                out.append(self._issue(h, f, "not_qualified", f"the site is not qualified for {NAMES[f]}"))
            elif f != "energy" and self.tier == "reserves" and self.da is not None and abs(v - self.da[f][h]) > EQ_TOL:
                out.append(self._issue(h, f, "as_fixed", f"AS are fixed to the DA book after watch 0 ({NAMES[f]} "
                                                         f"{_num(self.da[f][h])} MW at hour {h})"))
        if out:
            return out
        up, rd = sum(a[k] for k in UP), a["regdn"]
        upf = max(UP, key=lambda k: (d.dur.get(k, 0) * a[k], k == "regup")) if up else "energy"
        if e + up > st.p + TOL:
            out.append(self._issue(h, upf, "headroom_up", f"discharge {_num(e)} + up awards {_num(up)} > "
                                                          f"{_num(st.p)} MW"))
        if e - rd < -st.p - TOL:
            out.append(self._issue(h, "regdn", "headroom_dn", f"charge {_num(-e)} + RegDn {_num(rd)} > {_num(st.p)} MW"))
        if e + up > st.meter + TOL:
            out.append(self._issue(h, upf, "meter_up", f"battery {_num(e)} + up awards {_num(up)} > meter "
                                                       f"{_num(st.meter)} MW"))
        if e - rd < -st.meter_imp - TOL:
            out.append(self._issue(h, "regdn", "meter_dn", f"import {_num(rd - e)} > meter {_num(st.meter_imp)} MW"))
        if out:
            return out
        dis, ch = max(e, 0.0), max(-e, 0.0)
        B = S - dis + st.eta * ch
        if B < -TOL:
            out.append(self._issue(h, "energy", "soc_empty", f"discharging {_num(dis)} MW needs {dis:.2f} MWh, SoC "
                                                             f"{S:.2f}"))
        if B > st.e + TOL:
            out.append(self._issue(h, "energy", "soc_full", f"charging {_num(ch)} MW stores {st.eta * ch:.2f} MWh, "
                                                            f"room {st.e - S:.2f}"))
        if cyc + dis > st.cap + TOL:
            out.append(self._issue(h, "energy", "cycle_cap", f"discharge {_num(dis)} MWh > {st.cap - cyc:.2f} MWh "
                                                             f"left of the {_num(st.cap)} MWh cap"))
        rup, rdn = r_up(d.dur, a), r_dn(st, d.dur, a)
        if min(S, B) < rup - TOL:
            when, soc = (h, S) if S <= B else (h + 1, B)
            parts = " + ".join(f"{NAMES[k]} {_num(d.dur[k])}h" for k in UP if a[k])
            out.append(self._issue(h, upf, "reserve_up", f"{parts} need {rup:.2f} MWh at {hhmm(60 * when)}, SoC "
                                                         f"{soc:.2f}"))
        if max(S, B) > st.e - rdn + TOL:
            when, soc = (h, S) if S >= B else (h + 1, B)
            out.append(self._issue(h, "regdn", "reserve_dn", f"RegDn {_num(d.dur['regdn'])}h needs {rdn:.2f} MWh of "
                                                             f"room at {hhmm(60 * when)}, room {st.e - soc:.2f}"))
        return out

    def _expected(self, h: int, a: dict, dep: list[dict]) -> tuple[float, float]:
        d = self.day
        return (d.mean_up * a["regup"] + sum(dep[h][k] * a[k] for k in EVENT_PRODUCTS), d.mean_dn * a["regdn"])

    def _evaluate(self, fields: dict, fh: int) -> tuple[dict, list[int], list[int], list[dict]]:
        """C3-D2: the candidate book hour by hour from the settled boundary; (book, committed, refused, issues)."""
        fo, cand = self.first_open, {f: list(self.book[f]) for f in FIELDS}
        for f, vals in fields.items():
            cand[f][fh:] = [b if abs(v - b) <= EQ_TOL else v for v, b in zip(vals, self.book[f][fh:], strict=True)]
        issues, refused = [], []
        for h in range(fh, min(fo, HOURS)):
            diff = [f for f in FIELDS if cand[f][h] != self.book[f][h]]
            if diff:
                state = "settled" if h < self.settled else "frozen"
                issues.append(self._issue(h, diff[0], "frozen", f"hour {h} is {state}; hours from {fo} are open"))
                refused.append(h)
        new, committed = {f: list(self.book[f]) for f in FIELDS}, []
        S, cyc, dep, d = self.S, self.cyc, self._dep_known(), self.day
        for h in range(self.settled, HOURS):
            if h >= max(fh, fo):
                e, a = self.entry(h, cand)
                if iss := self.rules(h, S, cyc, e, a):
                    issues += iss
                    refused.append(h)
                    if e != new["energy"][h] and not self.rules(h, S, cyc, e, self.entry(h, new)[1]):
                        new["energy"][h] = cand["energy"][h]
                        committed.append(h)
                else:
                    committed.append(h)
                    for f in FIELDS:
                        new[f][h] = cand[f][h]
            e, a = self.entry(h, new)
            r = step(self.site, d.dur, S, cyc, e, a, d.pv[h], d.da[h], *self._expected(h, a, dep))
            S, cyc = r["S"], cyc + r["dis"]
        return new, committed, sorted(refused), issues

    def _project(self, book: dict | None = None) -> dict:
        """The day as known now: settled hours as settled, the rest at DA prices with expected drift and delivered
        deployments; per-hour shortfalls and governor flags feed the charged/excused snapshot (C3-D7)."""
        book = self.book if book is None else book
        st, d, dep = self.site, self.day, self._dep_known()
        S, cyc = self.S, self.cyc
        soc = [_r2(x) for x in self.soc_hist]
        margin = [_r2(r["margin"]) for r in self.rows]
        tot = dict(self.cash)
        clip_rec = sum(r["clip_rec"] for r in self.rows)
        curtailed = sum(r["curtailed"] for r in self.rows)
        short, governed = {}, {}
        for h in range(self.settled, HOURS):
            e, a = self.entry(h, book)
            r = step(st, d.dur, S, cyc, e, a, d.pv[h], d.da[h], *self._expected(h, a, dep))
            c = self._hour_cash(h, r, self.x_da(h, book), a, self.a_da(h, book), d.da[h], None)
            for k in ("energy_da", "energy_rt", "as_da", "as_rt", "degradation"):
                tot[k] += c[k]
            tot["ftp"] += c["ftp_full"]
            short[h], governed[h] = r["short"], r["governed"]
            clip_rec, curtailed = clip_rec + r["clip_rec"], curtailed + r["curtailed"]
            S, cyc = r["S"], cyc + r["dis"]
            soc.append(_r2(S))
            margin.append(_r2(r["margin"]))
        end_short = max(0.0, st.s_end - S) if not self.done else self.end_short
        if not self.done:
            tot["end_penalty"] = end_short * d.pen
        total = (tot["energy_da"] + tot["energy_rt"] + tot["as_da"] + tot["as_rt"] - tot["degradation"] - tot["ftp"]
                 - tot["end_penalty"])
        summary = {"energy_usd": _r2(tot["energy_da"] + tot["energy_rt"]), "as_usd": _r2(tot["as_da"] + tot["as_rt"]),
                   "degradation_usd": _r2(tot["degradation"]), "ftp_usd": _r2(tot["ftp"]),
                   "end_penalty_usd": _r2(tot["end_penalty"]), "total_usd": _r2(total), "end_soc_mwh": _r2(S)}
        return {"summary": summary, "soc": soc, "margin": margin, "short": short, "governed": governed,
                "end_short": end_short, "total": total, "S": S, "cyc": cyc, "clip_rec": clip_rec,
                "curtailed": curtailed}

    def _hour_cash(self, h: int, r: dict, x_da: float, a: dict, a_da: dict, price: float, mrt) -> dict:
        """Settlement of one hour at an energy price; mrt is the hour's RT MCPC (None: RT expected at DA)."""
        d, st = self.day, self.site
        pi_rt = {k: (mrt[k] if mrt is not None and k in mrt else d.mda[k][h]) for k in d.mda}
        rtcb = self.tier == "rtcb"
        ftp_price = {k: max(d.mda[k][h], pi_rt[k]) if k in d.mda else 0.0 for k in PRODUCTS}
        return {"energy_da": x_da * d.da[h], "energy_rt": (r["x"] - x_da) * price,
                "as_da": sum(a_da[k] * d.mda[k][h] for k in d.mda),
                "as_rt": sum((a[k] - a_da[k]) * pi_rt[k] for k in d.mda) if rtcb else 0.0,
                "degradation": st.c_deg * (r["dis"] + r["up_mwh"]),
                "deployment_energy": (r["up_mwh"] - r["dn_mwh"]) * price,
                "ftp_price": ftp_price, "ftp_full": sum(v * ftp_price[k] for k, v in r["short"].items())}

    def check_schedule(self, plan=None, from_hour=None) -> dict:
        if err := self._planning():
            return err
        try:
            fh, fields = parse_plan(plan, self.first_open if from_hour is None else from_hour)
        except PlanError as e:
            return {"feasible": False, "issues": [e.row()], "refused": [], "projected": None,
                    "clip_recovered_mwh": None, "curtailed_mwh": None, "reserve_margin_mwh_by_hour": None,
                    "excused": self._excused_rows(), "calls_left": self.calls_left}
        new, _, refused, issues = self._evaluate(fields, fh)
        proj = self._project(new)
        return {"feasible": not issues, "issues": issues, "refused": refused,
                "projected": proj["summary"] | {"soc_mwh": proj["soc"]}, "clip_recovered_mwh": _r2(proj["clip_rec"]),
                "curtailed_mwh": _r2(proj["curtailed"]), "reserve_margin_mwh_by_hour": proj["margin"],
                "excused": self._excused_rows(), "calls_left": self.calls_left}

    def commit_schedule(self, plan=None, from_hour=None) -> dict:
        if err := self._planning():
            return err
        try:
            fh, fields = parse_plan(plan, self.first_open if from_hour is None else from_hour)
        except PlanError as e:
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": [e.row()]})
            self.commits.append({"watch": self.watch, "from_hour": None, "committed": [], "refused": [],
                                 "call": self.calls})
            return {"committed": [], "refused": [e.row()], "frozen_until_hour": self.first_open,
                    "book": self._book_out(), "projected": self._project()["summary"], "calls_left": self.calls_left}
        new, committed, refused, issues = self._evaluate(fields, fh)
        if issues:
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": issues})
        self.book = new
        self.commits.append({"watch": self.watch, "from_hour": fh, "committed": committed, "refused": refused,
                             "call": self.calls})
        return {"committed": committed, "refused": issues, "frozen_until_hour": self.first_open,
                "book": self._book_out(), "projected": self._project()["summary"], "calls_left": self.calls_left}

    def _da_out(self) -> dict | None:
        if self.da is None:
            return None
        return {"x_da_mw": [_r6(x) for x in self.da["x_da"]]} | {k: [_num(x) for x in self.da[k]] for k in self.day.offered}

    def _excused_rows(self) -> list[dict]:
        return [{k: (_r2(v) if isinstance(v, float) else v) for k, v in r.items()} for r in self.excused]

    def advance(self) -> dict:
        if self.done:
            return {"error": "the day is over", "calls_left": 0}
        self._close_watch()
        if self.last:
            realized = self._settle(HOURS)
            self._finish("done")
            return {"done": True, "time": label(DAY_END, self.date), "realized": realized, "soc_mwh": _r2(self.S),
                    "cash": self.cash_out(), **self._done_result()}
        nxt = self.watches[self.watch + 1]
        realized = self._settle(min(HOURS, max(0, nxt.minute // 60)))
        self._open()
        return {"watch": self.watch, "time": label(self.minute, self.date), "frozen_until_hour": self.first_open,
                "realized": realized, "soc_mwh": _r2(self.S), "cash": self.cash_out(), "calls_left": self.calls_left}

    def _close_watch(self):
        """The charged/excused snapshot of every open hour (C3-D7); at watch 0 the book becomes the DA position."""
        proj, fo = self._project(), self.first_open
        for h in range(fo, HOURS):
            self.snap[h] = {"short": proj["short"][h], "governed": proj["governed"][h]}
        if fo < HOURS:
            self.end_snap = proj["end_short"]
        if self.watch == 0 and self.da is None:
            self.da = {"x_da": [self.x_da(h) for h in range(HOURS)]} | {k: list(self.book[k]) for k in PRODUCTS}

    def _open(self):
        self.watch += 1
        self.planning_calls.append(0)
        self.frozen.append(self._frozen_row())

    def _settle(self, upto: int) -> list[dict]:
        st, d, out = self.site, self.day, []
        for h in range(self.settled, upto):
            e, a = self.entry(h)
            a_da = self.a_da(h)
            U = d.reg_up[h] * a["regup"] + sum(self.dep_real[h][k] * a[k] for k in EVENT_PRODUCTS)
            D = d.reg_dn[h] * a["regdn"]
            r = step(st, d.dur, self.S, self.cyc, e, a, d.pv[h], d.rt[h], U, D)
            mrt = {k: d.mrt[k][h] for k in d.mrt} if d.mrt else None
            c = self._hour_cash(h, r, self.x_da(h), a, a_da, d.rt[h], mrt)
            snap = self.snap[h] or {"short": {}, "governed": False}
            charged = {k: min(v, snap["short"].get(k, 0.0)) for k, v in r["short"].items()}
            excused = {k: v - charged[k] for k, v in r["short"].items() if v - charged[k] > TOL}
            ftp = sum(v * c["ftp_price"][k] for k, v in charged.items())
            exc = sum(v * c["ftp_price"][k] for k, v in excused.items())
            for k in ("energy_da", "energy_rt", "as_da", "as_rt", "degradation", "deployment_energy"):
                self.cash[k] += c[k]
            self.cash["ftp"] += ftp
            self.cash["excused"] += exc
            for k, v in excused.items():
                self.excused.append({"hour": h, "product": k, "mw": v, "usd": v * c["ftp_price"][k]})
            if r["governed"]:
                self.governor.append({"hour": h, "committed": e, "executed": _r6(r["b"]),
                                      "excused": not snap["governed"]})
            row = {"h": h, "rt_usd": _r2(d.rt[h])}
            if mrt is not None and self.tier == "rtcb":
                row["mcpc_rt"] = {k: _r2(mrt[k]) for k in d.offered if k in mrt}
            row |= {"pv_mw": _r2(r["pv"]), "export_mw": _r2(r["x"]), "curtailed_mw": _r2(r["curtailed"]),
                    "clip_recovered_mw": _r2(r["clip_rec"]), "b_mw": _r2(r["b"]), "soc_mwh": _r2(r["S"]),
                    "reg_up_frac": _r2(d.reg_up[h]) if a["regup"] else 0.0,
                    "reg_dn_frac": _r2(d.reg_dn[h]) if a["regdn"] else 0.0,
                    "deployed_up_mwh": _r2(r["up_mwh"]), "deployed_dn_mwh": _r2(r["dn_mwh"]),
                    "governor": r["governed"], "ftp_mw": _r2(sum(charged.values())),
                    "excused_mw": _r2(sum(excused.values()))}
            self.rows.append(r | {"h": h, "e": e, "a": a, "a_da": a_da, "x_da": self.x_da(h), "cash": c, "ftp": ftp,
                                  "excused_usd": exc, "charged": charged, "excused_mw": excused})
            self.S, self.cyc = r["S"], self.cyc + r["dis"]
            self.soc_hist.append(self.S)
            out.append(row)
        return out

    def _finish(self, reason: str):
        self.end_short = max(0.0, self.site.s_end - self.S)
        self.end_short_charged = min(self.end_short, self.end_snap or 0.0)
        self.cash["end_penalty"] = self.end_short_charged * self.day.pen
        self.cash["excused"] += (self.end_short - self.end_short_charged) * self.day.pen
        self.done, self.end_reason = True, reason

    def _done_result(self) -> dict:
        if self.reference:
            return {"profit_usd": _r2(self.profit())}
        g = self.grade()
        return {"profit_usd": _r2(g["profit_usd"]), "reward": g["reward"],
                "capture_vs_hindsight": g["capture_vs_hindsight"]}

    def end_day(self) -> dict:
        """urn:gridsim:end-day/v1: play the unreached watches on the committed book, then grade and audit."""
        while not self.done and not self.last:
            self._close_watch()
            nxt = self.watches[self.watch + 1]
            self._settle(min(HOURS, max(0, nxt.minute // 60)))
            self._open()
            for n in self.watches[self.watch].notices:
                self.notice(**self._kw(n), via="env")
        if not self.done:
            self._close_watch()
            self._settle(HOURS)
            self._finish("end_day")
        g = self.grade()
        return {"end_reason": self.end_reason, "watch": self.watch, "profit_usd": _r2(g["profit_usd"]),
                "reward": g["reward"], "audit": self.audit()}

    # grading

    def references(self) -> dict:
        if self._refs is None:
            self._refs = stored_refs(self.task, self.tier, self.notices_in, self.deployments_in) or references(
                self.task, tiers=tuple(dict.fromkeys(("energy", self.tier))), notices=self.notices_in,
                deployments=self.deployments_in)
        return self._refs

    def grade(self) -> dict:
        if not self.done:
            raise ValueError("the day is not over: advance to the end or call end_day")
        if self._grade is None:
            r = self.references()
            tr = r[self.tier]
            p, p_idle, p_anchor = self.profit(), r["p_idle"], tr["p_anchor"]
            submitted = any(c["committed"] for c in self.commits)
            den = p_anchor - p_idle
            c = self.cash
            as_rev = c["as_da"] + c["as_rt"]
            en_gain = max(0.0, c["energy_da"] + c["energy_rt"] - p_idle)
            clippable = sum(x["clippable"] for x in self.rows)
            p_hind = tr.get("p_hind")
            self._grade = {
                "submitted": submitted, "tier": self.tier,
                "reward": reward_value(p, p_idle, p_anchor) if submitted else 0.0,
                "raw_ratio": _r6((p - p_idle) / den) if den > DEGENERATE_EPS else None, "profit_usd": _r6(p),
                "cash": self.cash_out(), "p_idle": p_idle, "p_anchor": p_anchor, "p_hind": p_hind,
                "p_lp": tr.get("p_lp"),
                "capture_vs_hindsight": _r6((p - p_idle) / (p_hind - p_idle))
                if p_hind is not None and p_hind - p_idle > DEGENERATE_EPS else None,
                "beats_anchor": p > p_anchor + DEGENERATE_EPS,
                "energy_only_reward": reward_value(tr["p_energy_only"], p_idle, p_anchor)
                if tr.get("p_energy_only") is not None else None,
                "as_share": _r6(as_rev / (as_rev + en_gain)) if as_rev + en_gain > DEGENERATE_EPS else None,
                "clip_recovered_pct": _r6(100 * sum(x["clip_rec"] for x in self.rows) / clippable)
                if clippable > TOL else None,
                "curtailed_mwh": _r6(sum(x["curtailed"] for x in self.rows)),
                "ftp_mwh_charged": _r6(sum(sum(x["charged"].values()) for x in self.rows)),
                "ftp_mwh_excused": _r6(sum(sum(x["excused_mw"].values()) for x in self.rows)),
                "end_short_mwh": _r6(self.end_short), "governor_hours": len(self.governor),
                "refusals": sum(len(x["refused"]) for x in self.refusals),
                "commits": sum(bool(x["committed"]) for x in self.commits)}
        return self._grade

    def audit(self, get_time_reads=None) -> dict:
        problems = self._audit_watches(get_time_reads)
        if self.transcript:
            problems += replay(self.task, self.tier, self.notices_in, self.deployments_in, self.transcript)["problems"]
        return {"ok": not problems, "problems": problems}

    def data(self) -> dict:
        return {"task_id": self.task["task_id"], "tier": self.tier, "watches": len(self.watches), "watch": self.watch,
                "time": label(self.minute, self.date), "done": self.done, "end_reason": self.end_reason,
                "calls_used": self.calls, "planning_calls": self.planning_calls, "book": self._book_out(),
                "da": self._da_out(), "executed": [_r6(r["b"]) for r in self.rows], "status": self.status(), "notices": self.log,
                "frozen": self.frozen, "refusals": self.refusals, "governor": self.governor,
                "excused": {"rows": self._excused_rows(), "usd": _r6(self.cash["excused"]),
                            "end_short_mwh": _r6(self.end_short - self.end_short_charged)},
                "settled": self.settled, "audit": self.audit() if self.done else None,
                "grade": self.grade() if self.done else None, "reward": self.grade()["reward"] if self.done else None}

    def episode(self, *, bundle: str = "train", path: str = "B'", model: str | None = None, trained: str | None = None,
                checkpoint_step: int | None = None, seed: int | None = None, messages: list | None = None,
                usage: dict | None = None, wall_seconds: float | None = None, episode_id: str | None = None) -> dict:
        """The gridsim.episode/v3 record of a finished day."""
        if not self.done:
            self.end_day()
        g, r, t, d = self.grade(), self.references(), self.task, self.day
        eid = episode_id or hashlib.sha256(_dump([t["task_id"], self.tier, bundle, path, model, trained, checkpoint_step,
                                                   seed, [s["output"] for s in self.transcript]]).encode()).hexdigest()[:16]
        when = {e["event_id"]: e["watch"] for e in self.log if e["first"]}
        steps, watch = [], 0
        for i, s in enumerate(self.transcript):
            out = json.loads(s["output"])
            steps.append({"t": i, "watch": watch, "tool": s["tool"], "args": s["args"], "output": out})
            if s["tool"] == "advance" and "watch" in out:
                watch = out["watch"]
        hours = [{"h": x["h"], "da": _r2(d.da[x["h"]]), "rt": _r2(d.rt[x["h"]]), "pv_mw": _r6(d.pv[x["h"]]),
                  "x_da_mw": _r6(x["x_da"]), "export_mw": _r6(x["x"]), "curtailed_mw": _r6(x["curtailed"]),
                  "clip_recovered_mw": _r6(x["clip_rec"]), "e_mw": _num(x["e"]), "b_mw": _r6(x["b"]),
                  "awards": {k: _num(x["a"][k]) for k in d.offered},
                  "reg_up_frac": _r6(d.reg_up[x["h"]]), "reg_dn_frac": _r6(d.reg_dn[x["h"]]),
                  "deployed_up_mwh": _r6(x["up_mwh"]), "deployed_dn_mwh": _r6(x["dn_mwh"]),
                  "soc_mwh": _r6(self.soc_hist[x["h"] + 1]), "energy_da_usd": _r6(x["cash"]["energy_da"]),
                  "energy_rt_usd": _r6(x["cash"]["energy_rt"]), "as_da_usd": _r6(x["cash"]["as_da"]),
                  "as_rt_usd": _r6(x["cash"]["as_rt"]), "deg_usd": _r6(x["cash"]["degradation"]),
                  "ftp_usd": _r6(x["ftp"]), "excused_usd": _r6(x["excused_usd"]), "governor": x["governed"]}
                 for x in self.rows]
        tr = r[self.tier]
        return {"schema": EPISODE_SCHEMA, "episode_id": eid, "env": HYBRID_ENV, "version": "v3", "task_id": t["task_id"],
                "tier": self.tier, "bundle": bundle, "path": path, "model": model, "trained": trained,
                "checkpoint_step": checkpoint_step, "seed": seed,
                "task": {k: t.get(k) for k in ("date", "era", "settlement_point", "point_kind", "region", "site",
                                               "prices", "rt", "pv_mw", "mcpc_da", "mcpc_rt")},
                "watches": [{"index": w.index, "time": w.time, "time_utc": w.time_utc,
                             "freeze_line": label(w.freeze_line, self.date),
                             "notices": [n.event_id for n in w.notices]} for w in self.watches],
                "notices": [{"event_id": n.event_id, "source": n.source, "kind": n.kind, "level": n.level,
                             "issued_at": n.issued_at, "reveal_at": label(n.reveal, self.date),
                             "watch": when.get(n.event_id), "name": n.name, "title": n.title, "text": n.text,
                             "deploy": n.deploy} for n, _ in self.scheduled.values()],
                "steps": steps, "book": self._book_out(),
                "da": self._da_out(), "soc_path": [_r6(x) for x in self.soc_hist], "hours": hours,
                "commits": self.commits, "cash": self.cash_out(), "profit_usd": g["profit_usd"], "reward": g["reward"],
                "raw_ratio": g["raw_ratio"], "capture_vs_hindsight": g["capture_vs_hindsight"],
                "beats_anchor": g["beats_anchor"],
                "references": {"p_idle": r["p_idle"], "p_anchor": tr["p_anchor"], "p_hind": tr.get("p_hind"),
                               "p_lp": tr.get("p_lp"), "p_energy_only": tr.get("p_energy_only"),
                               "anchor": tr.get("anchor"), "baselines": tr.get("baselines")},
                "audit": self.audit(), "messages": messages or [], "usage": usage, "wall_seconds": wall_seconds}


def replay(task: dict, tier: str, notices, deployments, transcript: list[dict]) -> dict:
    """Re-run a recorded transcript through a fresh Session and compare every output byte for byte."""
    s, problems = Session(task, tier, notices, deployments), []
    for i, st in enumerate(transcript):
        args = dict(st["args"])
        if st["tool"] == NOTICE_TOOL:
            args.setdefault("_via", "trigger")
        try:
            out = s.call(st["tool"], args)
        except ValueError as e:
            out = f"error: {e}"
        if out != st["output"]:
            problems.append(f"step {i} ({st['tool']}) does not replay byte-identically")
    return {"ok": not problems, "problems": problems}


def play(task: dict, tier: str, policy, notices=None, deployments=None, *, reference: bool = True) -> Session:
    """Run a policy at every watch through call(), each watch's notices delivered after advance as the gateway's
    triggers do, to the end of the day."""
    s = Session(task, tier, notices, deployments, reference=reference)
    while not s.done:
        policy(s)
        s.call("advance")
        s.deliver_watch_notices()
    return s


# the MILP (HiGHS): one model for the rolling anchor, the oneshot optimum and hindsight


class _Lin:
    """A linear expression: {column: coefficient} plus a constant."""

    __slots__ = ("c", "k")

    def __init__(self, c: dict | None = None, k: float = 0.0):
        self.c, self.k = c or {}, float(k)

    def __add__(self, o):
        if not isinstance(o, _Lin):
            return _Lin(dict(self.c), self.k + o)
        c = dict(self.c)
        for i, v in o.c.items():
            c[i] = c.get(i, 0.0) + v
        return _Lin(c, self.k + o.k)

    __radd__ = __add__

    def __sub__(self, o):
        return self + (o * -1.0 if isinstance(o, _Lin) else -o)

    def __rsub__(self, o):
        return self * -1.0 + o

    def __mul__(self, f: float):
        return _Lin({i: v * f for i, v in self.c.items()}, self.k * f)

    __rmul__ = __mul__


class _Model:
    def __init__(self):
        self.lo, self.hi, self.integer, self.rows = [], [], [], []
        self.obj = _Lin()

    def var(self, lo: float, hi: float, integer: bool = False) -> _Lin:
        self.lo.append(float(lo))
        self.hi.append(float(hi))
        self.integer.append(integer)
        return _Lin({len(self.lo) - 1: 1.0})

    def add(self, e: _Lin, lo: float = -math.inf, hi: float = math.inf):
        self.rows.append((e.c, lo - e.k, hi - e.k))

    def solve(self) -> tuple[float, np.ndarray] | None:
        """(objective, column values), or None when infeasible. Maximises."""
        if highspy is None:
            raise RuntimeError("the hybrid references need highspy: pip install 'agentenv-gridsim[lp]'")
        lp = highspy.HighsLp()
        n = len(self.lo)
        cost = np.zeros(n)
        for i, v in self.obj.c.items():
            cost[i] += v
        lp.num_col_, lp.num_row_ = n, len(self.rows)
        lp.col_cost_, lp.col_lower_, lp.col_upper_ = cost, np.array(self.lo), np.array(self.hi)
        lp.offset_ = self.obj.k
        lp.row_lower_ = np.array([r[1] for r in self.rows])
        lp.row_upper_ = np.array([r[2] for r in self.rows])
        lp.sense_ = highspy.ObjSense.kMaximize
        lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
        start, index, value = [0], [], []
        for c, _, _ in self.rows:
            for i in sorted(c):
                index.append(i)
                value.append(c[i])
            start.append(len(index))
        lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = start, index, value
        if any(self.integer):
            lp.integrality_ = [highspy.HighsVarType.kInteger if t else highspy.HighsVarType.kContinuous
                               for t in self.integer]
        h = highspy.Highs()
        for k, v in (("output_flag", False), ("threads", 1), ("random_seed", 0), ("mip_rel_gap", 1e-7),
                     ("mip_abs_gap", 1e-4)):
            h.setOptionValue(k, v)
        h.passModel(lp)
        h.run()
        status = h.getModelStatus()
        if status in (highspy.HighsModelStatus.kInfeasible, highspy.HighsModelStatus.kUnboundedOrInfeasible):
            return None
        if status != highspy.HighsModelStatus.kOptimal:
            raise RuntimeError(f"MILP not optimal: {h.modelStatusToString(status)}")
        return float(h.getInfo().objective_function_value), np.asarray(h.getSolution().col_value)


def _plant(m: _Model, st: Site, dur: dict, S0: float, cyc_left: float, pv, price, mu, md, dep, aw, *,
           integer: bool, soft: bool = False, free_curtail: bool = False) -> dict:
    """One copy of the plant over len(pv) hours from SoC S0: integer energy levels with a direction binary, the AS
    awards aw[t][k] (expressions in MW), the C3-D5 rules on the base path and the expected/realized drift dynamics."""
    S = _Lin(k=S0)
    out = {"x": [], "xb": [], "dis": [], "U": [], "dl": [], "cl": [], "S": [S], "slack": []}
    dsum = _Lin()
    for t in range(len(pv)):
        dis, ch, z = m.var(0, st.p), m.var(0, st.p), m.var(0, 1, integer)
        m.add(dis - z * st.p, hi=0.0)
        m.add(ch + z * st.p, hi=st.p)
        dl, cl = dis, ch
        b = dis - ch
        a = aw[t]
        up = sum((a[k] for k in UP), _Lin())
        rd = a["regdn"]
        rup = sum((a[k] * dur.get(k, 0.0) for k in UP), _Lin())
        rdn = rd * (st.eta * dur.get("regdn", 0.0))
        B = S - dis + ch * st.eta
        m.add(B, 0.0, st.e)
        su = m.var(0, math.inf) if soft else _Lin()
        sd = m.var(0, math.inf) if soft else _Lin()
        if soft:
            out["slack"] += [su, sd]
        m.add(B - rup + su, lo=0.0)
        m.add(S - rup + su, lo=0.0)
        m.add(B + rdn - sd, hi=st.e)
        m.add(S + rdn - sd, hi=st.e)
        m.add(b + up, hi=min(st.p, st.meter))
        m.add(b - rd, lo=-min(st.p, st.meter_imp))
        U = a["regup"] * mu[t] + sum((a[k] * dep[t][k] for k in EVENT_PRODUCTS), _Lin())
        D = rd * md[t]
        nxt = m.var(-math.inf if soft else 0.0, st.e)
        m.add(nxt - B + U - D * st.eta, 0.0, 0.0)
        s = float(pv[t])
        if price[t] < 0 and not free_curtail:
            c = _Lin(k=s)
        else:
            c = m.var(0.0, s)
            m.add(c - b - up, lo=s - st.meter)
        xb = b + (s - c)
        out["x"].append(xb + U - D)
        out["xb"].append(xb)
        out["dis"].append(dis)
        out["U"].append(U)
        out["dl"].append(dl)
        out["cl"].append(cl)
        dsum = dsum + dis
        S = nxt
        out["S"].append(S)
    m.add(dsum, hi=cyc_left)
    return out


def _awards(m: _Model, n: int, h0: int, products, fixed: dict | None, p: float) -> list[dict]:
    """Award expressions per hour (MW): variables for products, constants from fixed, zero otherwise."""
    out = []
    for t in range(n):
        row = {}
        for k in PRODUCTS:
            if fixed is not None:
                row[k] = _Lin(k=float(fixed[k][h0 + t]))
            elif k in products:
                row[k] = m.var(0, p)
            else:
                row[k] = _Lin()
        out.append(row)
    return out


def _value(e: _Lin, x: np.ndarray) -> float:
    return e.k + sum(v * x[i] for i, v in e.c.items())


def _clean(v: float):
    """A solver value as a plan value: 6 decimals, an int when whole."""
    v = round(float(v), 6) + 0.0
    return int(v) if v.is_integer() else v


def solve_day(st: Site, day: Day, h0: int, S0: float, cyc: float, *, products=(), fixed: dict | None = None,
              dep=None, pv=None, integer: bool = True) -> dict | None:
    """The best book for hours h0..23 from SoC S0 (cyc MWh discharged): RT expected at DA, MCPC at DA, expected drift,
    known deployments dep; AS variable for `products` or fixed. Soft reservations only if the hard model is infeasible."""
    n = HOURS - h0
    dep = dep or [dict.fromkeys(EVENT_PRODUCTS, 0.0) for _ in range(HOURS)]
    pv = day.pv if pv is None else pv
    for soft in (False, True):
        m = _Model()
        aw = _awards(m, n, h0, products, fixed, st.p)
        price = day.da[h0:]
        p = _plant(m, st, day.dur, S0, st.cap - cyc, pv[h0:], price, [day.mean_up] * n, [day.mean_dn] * n,
                   dep[h0:], aw, integer=integer, soft=soft)
        short = m.var(0, math.inf)
        m.add(short + p["S"][-1], lo=st.s_end)
        obj = _Lin()
        for t in range(n):
            h = h0 + t
            obj = obj + p["x"][t] * float(price[t]) - (p["dis"][t] + p["U"][t]) * st.c_deg
            if fixed is None:
                obj = obj + sum((aw[t][k] * float(day.mda[k][h]) for k in products), _Lin())
        obj = obj - short * day.pen - sum(p["slack"], _Lin()) * SOFT_PENALTY
        m.obj = obj
        res = m.solve()
        if res is None:
            continue
        val, x = res
        book = {"energy": [_clean(_value(p["dl"][t], x) - _value(p["cl"][t], x)) for t in range(n)]}
        for k in PRODUCTS:
            book[k] = [_clean(max(0.0, _value(aw[t][k], x))) for t in range(n)]
        return {"objective": val, "book": book, "soft": soft}
    return None


def hindsight(task: dict, tier: str, notices=None, deployments=None, *, integer: bool = True) -> float | None:
    """P_hind (C3-D13): a DA-position copy on expected drift and a physical copy on realized RT, drift and deployments,
    sharing the AS book (separate RT awards in rtcb). integer=False gives the LP bound."""
    st, day = site_of(task), day_of(task, tier)
    events = events_of(task, notices, deployments)
    dep = deploy_hours([n.deploy for n in (live.parse_notice(x, task["date"]) for x in events) if n.deploy], day.dur)
    zero = [dict.fromkeys(EVENT_PRODUCTS, 0.0) for _ in range(HOURS)]
    m = _Model()
    prods = tuple(k for k in day.offered if k in day.qualified)
    a_da = _awards(m, HOURS, 0, prods, None, st.p)
    a_rt = _awards(m, HOURS, 0, prods, None, st.p) if tier == "rtcb" else a_da
    cp = _plant(m, st, day.dur, st.s0, st.cap, day.pv, day.da, [day.mean_up] * HOURS, [day.mean_dn] * HOURS, zero,
                a_da, integer=integer, free_curtail=True)
    ph = _plant(m, st, day.dur, st.s0, st.cap, day.pv, day.rt, day.reg_up, day.reg_dn, dep, a_rt, integer=integer)
    short = m.var(0, math.inf)
    m.add(short + ph["S"][-1], lo=st.s_end)
    obj = _Lin()
    for h in range(HOURS):
        obj = obj + cp["xb"][h] * float(day.da[h] - day.rt[h]) + ph["x"][h] * float(day.rt[h])
        obj = obj - (ph["dis"][h] + ph["U"][h]) * st.c_deg
        for k in prods:
            obj = obj + a_da[h][k] * float(day.mda[k][h])
            if tier == "rtcb":
                obj = obj + (a_rt[h][k] - a_da[h][k]) * float(day.mrt[k][h])
    m.obj = obj - short * day.pen
    res = m.solve()
    return None if res is None else res[0]


# policies: the anchor, the oneshot optimum and the baselines, each played through a Session


def projected_state(s: Session, h: int) -> tuple[float, float]:
    """SoC and discharged MWh at the start of hour h on the current projection."""
    st, d, dep = s.site, s.day, s._dep_known()
    S, cyc = s.S, s.cyc
    for t in range(s.settled, h):
        e, a = s.entry(t)
        r = step(st, d.dur, S, cyc, e, a, d.pv[t], d.da[t], *s._expected(t, a, dep))
        S, cyc = r["S"], cyc + r["dis"]
    return S, cyc


def anchor_plan(s: Session, *, energy_only: bool = False, pv_blind: bool = False) -> dict | None:
    """One MILP solve from the freeze line on the day as known at this watch; None when nothing is open."""
    fo = s.first_open
    if fo >= HOURS:
        return None
    S, cyc = projected_state(s, fo)
    st, day = s.site, s.day
    fixed = None
    prods = () if energy_only else tuple(k for k in day.offered if k in day.qualified)
    if s.tier == "reserves" and s.da is not None and not energy_only:
        fixed = {k: [float(x) for x in s.da[k]] for k in PRODUCTS}
    if pv_blind:
        st = st._replace(meter=1e9, meter_imp=1e9)
    res = solve_day(st, day, fo, S, cyc, products=prods, fixed=fixed, dep=s._dep_known(),
                    pv=np.zeros(HOURS) if pv_blind else None)
    if res is None:
        return None
    plan = {"energy": res["book"]["energy"]}
    if fixed is None:
        plan |= {k: res["book"][k] for k in day.offered}
    return plan


def anchor_policy(*, energy_only: bool = False, pv_blind: bool = False):
    """The information-matched rolling MILP: one solve per watch, committed when it changes the book (always at
    watch 0), with one planning call."""

    def policy(s: Session):
        if not s.calls_left or (plan := anchor_plan(s, energy_only=energy_only, pv_blind=pv_blind)) is None:
            return
        fo = s.first_open
        cur = s._book_out()
        if s.watch == 0 or any(abs(a - b) > EQ_TOL for f in plan for a, b in zip(plan[f], cur[f][fo:], strict=True)):
            s.call("commit_schedule", {"plan": plan, "from_hour": fo})

    return policy


def idle_policy(s: Session):
    return None


def sponge_policy(s: Session):
    """Charge only from PV the meter cannot export, discharge it in the top DA hours; no AS; never re-plans."""
    if s.watch != 0 or s.commits:
        return
    st, d = s.site, s.day
    e = [0.0] * HOURS

    def ok(plan) -> bool:
        S, cyc = st.s0, 0.0
        for b in plan:
            S, cyc = (S - b, cyc + b) if b > 0 else (S - st.eta * b, cyc)
            if S < -TOL or S > st.e + TOL or cyc > st.cap + TOL:
                return False
        return S >= st.s_end - TOL

    def most(h: int, hi: float, sign: float) -> float:
        lo = 0.0
        for _ in range(40):
            mid = (lo + hi) / 2
            e[h] = sign * mid
            lo, hi = (mid, hi) if ok(e) else (lo, mid)
        e[h] = sign * lo
        return lo

    for h in range(HOURS):
        clip = max(0.0, d.pv[h] - st.meter) if d.da[h] >= 0 else 0.0
        if clip > TOL:
            most(h, min(st.p, clip), -1.0)
    for h in sorted((h for h in range(HOURS) if e[h] == 0 and d.da[h] > st.c_deg), key=lambda h: (-d.da[h], h)):
        most(h, st.p, 1.0)
    s.call("commit_schedule", {"plan": {"energy": [_clean(x) for x in e]}, "from_hour": 0})


def as_hog_policy(s: Session):
    """Energy idle, the most RegUp + RegDn the reservation and the meter allow without curtailing PV, each hour on the
    expected path; at watch 0 only."""
    if s.watch != 0 or s.commits:
        return
    st, d = s.site, s.day
    have = [k for k in ("regup", "regdn") if k in d.offered and k in d.qualified]
    if not have:
        return
    plan = {k: [0.0] * HOURS for k in have}
    S = st.s0
    for h in range(HOURS):
        ru = min(st.p, max(0.0, st.meter - d.pv[h]), S / d.dur["regup"]) if "regup" in have else 0.0
        rd = min(st.p, st.meter_imp, (st.e - S) / (st.eta * d.dur["regdn"])) if "regdn" in have else 0.0
        ru, rd = max(0.0, math.floor(ru * 1e4) / 1e4), max(0.0, math.floor(rd * 1e4) / 1e4)
        for k, v in (("regup", ru), ("regdn", rd)):
            if k in have:
                plan[k][h] = _clean(v)
        S = S - d.mean_up * ru + st.eta * d.mean_dn * rd
    s.call("commit_schedule", {"plan": {"energy": [0] * HOURS} | plan, "from_hour": 0})


# references


def oneshot_ref(task: dict, tier: str) -> dict:
    """The path B optimum: the watch-0 MILP on the day with RT = DA, expected drift and no deployments, valued by the
    same projection oneshot_grade uses."""
    s = Session(task, tier, [], [], reference=True)
    p_idle = s._project()["total"]
    plan = anchor_plan(s)
    s.commit_schedule(plan, 0)
    return {"p_idle": _r6(p_idle), "p_milp": _r6(s._project()["total"]), "plan": blocks(plan)}


def oneshot_grade(task: dict, plan, tier: str = "reserves") -> dict:
    """Grade one watch-0 commit (path B, hybrid-oneshot) against the day's MILP with RT = DA."""
    ref = ((task.get("refs") or {}).get(tier) or {}).get("oneshot") or oneshot_ref(task, tier)
    s = Session(task, tier, [], [], reference=True)
    out = s.commit_schedule(plan, 0)
    if not out["committed"]:
        return {"submitted": False, "reward": 0.0, "profit_usd": None, "p_idle": ref["p_idle"],
                "p_milp": ref["p_milp"], "committed": 0, "refused": out["refused"]}
    p = s._project()["total"]
    return {"submitted": True, "reward": reward_value(p, ref["p_idle"], ref["p_milp"]), "profit_usd": _r6(p),
            "p_idle": ref["p_idle"], "p_milp": ref["p_milp"], "committed": len(out["committed"]),
            "refused": out["refused"]}


def blocks(plan: dict) -> dict:
    """A plan's lists as blocks (runs of equal values; zeros dropped)."""
    out = {}
    for f, vals in plan.items():
        runs, h = [], 0
        while h < len(vals):
            j = h
            while j + 1 < len(vals) and vals[j + 1] == vals[h]:
                j += 1
            if vals[h]:
                runs.append({"from": h, "to": j + 1, "mw": vals[h]})
            h = j + 1
        out[f] = runs
    return out


def references(task: dict, tiers=("energy", "reserves"), notices=None, deployments=None, lp: bool = True) -> dict:
    """The refs block: idle, the rolling anchor per tier, hindsight (+ LP bound), the oneshot optimum and baselines."""
    kw = {"notices": notices, "deployments": deployments}
    p_idle = play(task, "energy", idle_policy, **kw).profit()
    sponge = play(task, "energy", sponge_policy, **kw).profit()
    v2e = play(task, "energy", anchor_policy(energy_only=True, pv_blind=True), **kw).profit()
    out = {"hybrid_version": HYBRID_VERSION, "events_sha": events_sha(task, notices, deployments), "p_idle": _r6(p_idle)}
    for tier in dict.fromkeys(("energy",) + tuple(tiers)):
        try:
            Session(task, tier, notices, deployments, reference=True)
        except ValueError:
            out[tier] = None
            continue
        anc = play(task, tier, anchor_policy(), **kw)
        p_anchor = anc.profit()

        def entry(p, p_anchor=p_anchor):
            return {"profit": _r6(p), "reward": reward_value(p, p_idle, p_anchor)}

        bl = {"sponge": entry(sponge), "v2_energy": entry(v2e)}
        if tier != "energy":
            bl["as_hog"] = entry(play(task, tier, as_hog_policy, **kw).profit())
        hind = hindsight(task, tier, notices, deployments)
        row = {"p_anchor": _r6(p_anchor),
               "anchor": {"book": anc._book_out(), "commits": sum(bool(c["committed"]) for c in anc.commits),
                          "watches": len(anc.watches), "governor_hours": len(anc.governor),
                          "ftp_usd": _r6(anc.cash["ftp"]), "as_usd": _r6(anc.cash["as_da"] + anc.cash["as_rt"])},
               "p_hind": None if hind is None else _r6(hind),
               "p_lp": _r6(hindsight(task, tier, notices, deployments, integer=False)) if lp else None,
               "oneshot": oneshot_ref(task, tier), "baselines": bl}
        if tier != "energy":
            row["p_energy_only"] = out["energy"]["p_anchor"]
        out[tier] = row
    return out


def stored_refs(task: dict, tier: str, notices=None, deployments=None) -> dict | None:
    """The task row's refs when they were computed for these events and hold this tier."""
    r = task.get("refs")
    if r and r.get("events_sha") == events_sha(task, notices, deployments) and r.get(tier) and r.get("energy"):
        return r
    return None


__all__ = ["Session", "schedule", "triggers", "references", "replay", "play", "oneshot_grade", "events_of",
           "parse_plan", "PlanError", "solve_day", "HYBRID_VERSION", "HYBRID_ENV", "EPISODE_SCHEMA", "TIERS",
           "PRODUCTS", "TOOLS", "NOTICE_TOOL", "LIVE_LOAD_URI", "END_DAY_URI", "CLOCK_URI", "PLANNING_CALLS",
           "MAX_TURNS"]
