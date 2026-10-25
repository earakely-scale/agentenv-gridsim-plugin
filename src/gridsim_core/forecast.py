"""GridSimEnv v4 "Weather Front": v3's solar-plus-storage plant run for two or three operating days on forecasts served
as issued. Each day's day-ahead (DAM) position is bid at 10:00 the day before; the real-time book is re-planned at each
watch as weather runs, notices and DAM results arrive. Graded against a rolling MILP on the desk price guide's P50.

Session is the only v4 state machine: the gridsim-forecast env wraps it and path B' imports it. Time is minutes from
d1 00:00 CPT (the clock opens at d1-1 10:00, minute -840); window hour h covers [60h, 60h + 60). The rules and their
decisions (V4-P*) are in docs/CONTRACT-v4.md."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from typing import NamedTuple

import numpy as np

from gridsim_core import forecast_inputs as FI
from gridsim_core import hybrid as HY
from gridsim_core import hybrid_inputs, live
from gridsim_core.contract import AS_DURATION_H, DEGENERATE_EPS, P_FLOOR, as_era, ceil_to_interval
from gridsim_core.grade import reward_value
from gridsim_core.hybrid import (
    EQ_TOL,
    EVENT_PRODUCTS,
    FIELDS,
    NAMES,
    PRODUCTS,
    TOL,
    UP,
    PlanError,
    _awards,
    _clean,
    _Lin,
    _Model,
    _num,
    _plant,
    _r2,
    _r6,
    _value,
    deploy_hours,
    govern,
    hour_rules,
    limits,
    parse_plan,
    site_of,
    step,
    x_da_of,
)
from gridsim_core.live import (
    CLOCK_URI,
    NOTICE_TOOL,
    PLANNING_CALLS,
    TURNS_PER_WATCH,
    Notice,
    Watch,
    WatchDay,
    _day0,
    _dump,
    parse_notice,
    utc,
)
from gridsim_core.task import REGIONS, point_kind

FORECAST_VERSION = "4.1"
FORECAST_ENV = "gridsim-forecast"
EPISODE_SCHEMA = "gridsim.episode/v4"
TIERS = ("front-lite", "front", "blind", "freeze-6h")
TOOLS = ("get_situation", "get_forecast", "get_forecast_drift", "check_schedule", "commit_schedule", "submit_dam",
         "advance")
PLANNING_TOOLS = ("check_schedule", "commit_schedule")
FORECAST_TOOLS = ("get_forecast", "get_forecast_drift")
FORECAST_LOAD_URI = "urn:gridsim:forecast-load/v1"
END_WINDOW_URI = "urn:gridsim:end-window/v1"
URIS = (FORECAST_LOAD_URI, END_WINDOW_URI, CLOCK_URI)
FORECAST_CALLS = 6
DAM_SUBMITS = 3
DAYS = {"front-lite": 2, "front": 3, "blind": 3, "freeze-6h": 3}
MAX_WATCHES = {"front-lite": 14, "front": 24, "blind": 24, "freeze-6h": 24}
MAX_TURNS = {t: TURNS_PER_WATCH * c + 2 for t, c in MAX_WATCHES.items()}
FREEZE_MIN = {"freeze-6h": 360}
OPEN = -840
GATE_HOUR, RESULTS_MIN = 10, 810
KINDS = ("load", "wind", "solar", "weather", "price", "alerts")
DRIFT_KINDS = ("load", "wind", "solar", "weather", "price")
HRRR_MOVE, HRRR_FLOOR, HRRR_PRIORITY = 0.10, 10.0, 5
SOLVER = 2
TIE_EPS = 1e-4
ANCHOR_MODE = {"front-lite": "p50", "front": "p50", "blind": "persist", "freeze-6h": "p50"}
CASH_KEYS = ("energy_da", "energy_rt", "as_da", "deployment_energy", "degradation", "ftp", "excused", "end_penalty")
_STAMP = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})[ T](\d{1,2}):(\d{2})(?::00(?:\.0+)?)?\s*(Z|[+-]\d{2}:?\d{2})?\s*$", re.I)
KEEP = "keep"
_INT = re.compile(r"^\s*-?\d+\s*$")


def fixed_watches(days: int) -> tuple[int, ...]:
    out = [OPEN, -600, -360]
    for k in range(days - 1):
        out += [1440 * k + m for m in (0, 360, 600, 840, 1080)]
    return tuple(out + [1440 * (days - 1) + m for m in (0, 360, 1080)])


def gate_minute(k: int) -> int:
    return 1440 * k - 1440 + 60 * GATE_HOUR


def results_minute(k: int) -> int:
    return 1440 * k - 1440 + RESULTS_MIN


def freeze_line(minute: float, tier: str = "front") -> int:
    return int(ceil_to_interval(minute, 60)) + FREEZE_MIN.get(tier, 60)


def stamp(minute: float, d1: str) -> str:
    """The CPT time of a minute from d1 00:00 as ISO 8601 with its UTC offset, e.g. 2025-01-28T10:00-06:00."""
    return (_day0(d1) + dt.timedelta(minutes=minute)).replace(tzinfo=live.TZ).isoformat(timespec="minutes")


def to_minute(s: str, d1: str) -> int | None:
    """Minutes from d1 00:00 of a time: "YYYY-MM-DD HH:MM" or ISO 8601, read as CPT without an offset (24:00 is the
    next day's 00:00) and converted to CPT with one (Z or +-HH:MM)."""
    m = _STAMP.match(str(s))
    if not m:
        return None
    hh, mm, tz = int(m.group(2)), int(m.group(3)), m.group(4)
    if hh > 24 or mm > 59 or (hh == 24 and (mm or tz)):
        return None
    day = dt.date.fromisoformat(m.group(1))
    if tz is None:
        return int((day - dt.date.fromisoformat(d1)).days * 1440 + hh * 60 + mm)
    off = dt.UTC if tz.upper() == "Z" else dt.timezone(
        (-1 if tz[0] == "-" else 1) * dt.timedelta(hours=int(tz[1:3]), minutes=int(tz[-2:])))
    t = dt.datetime.combine(day, dt.time(hh, mm), off).astimezone(live.TZ).replace(tzinfo=None)
    return int((t - _day0(d1)).total_seconds() // 60)


def kept(plan):
    """The plan without its AS fields sent as "keep" or null: both mean unchanged, as a field left out."""
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            return plan
    if not isinstance(plan, dict):
        return plan
    return {f: v for f, v in plan.items()
            if not (f in PRODUCTS and (v is None or isinstance(v, str) and v.strip().lower() == KEEP))}


# the window's arrays, site and events


class Window(NamedTuple):
    era: str
    days: int
    hours: int
    dur: dict
    offered: tuple
    qualified: tuple
    pv: np.ndarray
    da: np.ndarray
    rt: np.ndarray
    mda: dict
    reg_up: np.ndarray
    reg_dn: np.ndarray
    mean_up: float
    mean_dn: float
    pen: float


def window_of(task: dict, tier: str) -> Window:
    n = DAYS[tier]
    hrs = 24 * n
    era = task.get("era") or as_era(task["d1"])
    dur = dict(AS_DURATION_H[era])
    eps = tuple(k for k in PRODUCTS if k in dur)
    mda = {k: np.asarray(v[:hrs], dtype=float) for k, v in (task.get("mcpc_da") or {}).items() if k in eps}
    offered = () if tier == "front-lite" else tuple(k for k in eps if k in mda)
    reg = task.get("reg") or {}
    cu, cd = min(1.0, dur.get("regup", 1.0)), min(1.0, dur.get("regdn", 1.0))
    da = np.asarray(task["prices"][:hrs], dtype=float)
    pv = np.zeros(hrs) if tier == "front-lite" else np.asarray(task["pv_mw"][:hrs], dtype=float)
    return Window(era, n, hrs, dur, offered, tuple(task["site"].get("qualified") or eps), pv, da,
                  np.asarray(task["rt"][:hrs], dtype=float), mda,
                  np.minimum(cu, np.asarray((reg.get("up") or [0.0] * hrs)[:hrs], dtype=float)),
                  np.minimum(cd, np.asarray((reg.get("dn") or [0.0] * hrs)[:hrs], dtype=float)),
                  min(cu, float(reg.get("mean_up", HY.REG_MEAN["up"]))),
                  min(cd, float(reg.get("mean_dn", HY.REG_MEAN["dn"]))),
                  max(float(da.max()), P_FLOOR) / float(task["site"]["bess"]["eta"]))


def site_for(task: dict, tier: str) -> HY.Site:
    """v3's site with the cycle cap pooled over the window (1.5 E per day)."""
    return site_of(task)._replace(cap=float(task["site"]["bess"]["cycle_cap_mwh"]) * DAYS[tier])


def events_of(task: dict, notices=None, deployments=None) -> list[dict]:
    return HY.events_of({"date": task["d1"], "notices": task.get("notices"), "deployments": task.get("deployments")},
                        notices, deployments)


def events_sha(task: dict, notices=None, deployments=None) -> str:
    return live.notices_sha(events_of(task, notices, deployments))


def priority(n: Notice) -> int:
    """Which event watches survive the cap (V4-P10, V4-P11): deployments and emergencies first, then conservation,
    ERCOT watches, NWS warnings and watches, weather-run moves, advisories, the rest, cancellations last."""
    lv = str(n.level or "")
    if n.deploy is not None:
        return 0
    if n.action == "cancel":
        return 8
    if n.source == "NWS" or n.kind.startswith("nws:"):
        return {"Warning": 3, "Watch": 4}.get(lv, 7)
    if n.derate_mw is not None or lv.startswith("EEA") and lv != "EEA_exit" or lv == "Emergency":
        return 0
    return {"conservation": 1, "EEA_exit": 2, "Watch": 2, "Advisory": 6}.get(lv, 7)


def keep_hint(e: PlanError) -> PlanError:
    """A field's parse error that says how to keep the field as it is (agents wrote "keep" for an AS field)."""
    if e.field == "energy":
        return PlanError(e.field, f"{e}; energy is always sent: to keep an hour as booked, send its booked MW")
    if e.field in PRODUCTS:
        return PlanError(e.field, f"{e}; to keep {NAMES[e.field]} as it is, leave {e.field} out of the plan (or send "
                                  f"\"{KEEP}\")")
    return e


# vintages: the window's forecasts as issued


class VRec(NamedTuple):
    minute: float
    h0: int
    n: int
    v: dict


class Vintages:
    """The window's vintages by (kind, key), each placed on the window's clock (issue minute, first window hour)."""

    def __init__(self, sl: dict, d1: str):
        self.slice = sl
        base = FI.parse_utc(utc(0, d1))
        self.by: dict[tuple, list[VRec]] = {}
        for v in sl.get("series") or []:
            m = (FI.parse_utc(v["issued_at"]) - base).total_seconds() / 60
            h0 = round((FI.parse_utc(v["start"]) - base).total_seconds() / 3600)
            n = max((len(x) for x in v["fields"].values() if isinstance(x, list)), default=0)
            self.by.setdefault((v["kind"], v["key"]), []).append(VRec(m, h0, n, v))
        for lst in self.by.values():
            lst.sort(key=lambda r: (r.minute, r.v["issued_at"]))

    def all(self, kind: str, key: str, minute: float = math.inf) -> list[VRec]:
        return [r for r in self.by.get((kind, key), ()) if r.minute <= minute]

    def latest(self, kind: str, key: str, minute: float) -> VRec | None:
        rs = self.all(kind, key, minute)
        return rs[-1] if rs else None

    def previous(self, kind: str, key: str, rec: VRec) -> VRec | None:
        lst = self.by.get((kind, key), [])
        i = next(i for i, r in enumerate(lst) if r is rec)
        return lst[i - 1] if i else None

    @staticmethod
    def at(rec: VRec, field: str, h: int):
        vals = rec.v["fields"].get(field)
        i = h - rec.h0
        return vals[i] if vals is not None and 0 <= i < len(vals) else None

    def served(self, kind: str, key: str, field: str, minute: float, h: int):
        """The hour's value from the latest vintage revealed by `minute` that covers it; past that vintage's range,
        the same hour of its last covered day."""
        rs = self.all(kind, key, minute)
        for r in reversed(rs):
            x = self.at(r, field, h)
            if x is not None:
                return x
        if rs:
            r = rs[-1]
            last = r.h0 + r.n - 1
            if h > last:
                return self.at(r, field, h - 24 * math.ceil((h - last) / 24))
        return None


def hrrr_moves(task: dict, tier: str, vint: Vintages) -> list[int]:
    """Minutes of weather runs whose guide RT P50 at the site's point moves >= 10% over the open hours (V4-P11)."""
    hrs, out = 24 * DAYS[tier], []
    rs = vint.all("price", task["settlement_point"])
    for prev, cur in zip(rs, rs[1:], strict=False):
        m = int(cur.minute)
        lo = max(0, freeze_line(m, tier) // 60)
        pairs = [(Vintages.at(cur, "rt_p50", h), Vintages.at(prev, "rt_p50", h)) for h in range(lo, hrs)]
        pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
        if pairs:
            d = np.mean([abs(a - b) for a, b in pairs])
            if d / max(np.mean([abs(b) for _, b in pairs]), HRRR_FLOOR) >= HRRR_MOVE:
                out.append(m)
    return out


def schedule(task: dict, tier: str = "front", notices=None, deployments=None, vintages=None
             ) -> tuple[list[Watch], list[str]]:
    """The fixed watches plus one per event hour (notices, deployments, weather-run moves), merged on the hour and
    capped (V4-P10); every notice is delivered at the first watch at or after its reveal (ceil to the hour)."""
    d1, n = task["d1"], DAYS[tier]
    end, fixed = 1440 * n, fixed_watches(n)
    ns = sorted((parse_notice(x, d1, 60) for x in events_of(task, notices, deployments)),
                key=lambda x: (x.reveal, x.issued, x.event_id))
    cand: dict[int, int] = {}
    for x in ns:
        if OPEN < x.reveal and freeze_line(x.reveal, tier) < end and x.reveal not in fixed:
            cand[x.reveal] = min(cand.get(x.reveal, 99), priority(x))
    if tier != "blind" and vintages is not None:
        for m in hrrr_moves(task, tier, vintages):
            if OPEN < m and freeze_line(m, tier) < end and m not in fixed:
                cand[m] = min(cand.get(m, 99), HRRR_PRIORITY)
    kept = sorted(cand.items(), key=lambda kv: (kv[1], kv[0]))[:MAX_WATCHES[tier] - len(fixed)]
    times = sorted(set(fixed) | {m for m, _ in kept})
    slots: dict[int, list[Notice]] = {m: [] for m in times}
    for x in ns:
        m = next((t for t in times if t >= x.reveal), None)
        if m is not None:
            slots[m].append(x)
    watches = [Watch(k, m, stamp(m, d1), utc(m, d1), freeze_line(m, tier), tuple(slots[m]))
               for k, m in enumerate(times)]
    return watches, ["fixed" if m in fixed else "event" for m in times]


def triggers(watches: list[Watch]) -> list[dict]:
    return live.triggers(watches)


# the session


class Session(WatchDay):
    """One live forecast window. Drive it through call() so outputs, messages and the transcript match path A."""

    TOOLS = TOOLS
    NOTICE_ARGS = WatchDay.NOTICE_ARGS + ("deploy",)
    RT_MINUTES = 60

    def __init__(self, task: dict, tier: str = "front", notices=None, deployments=None, vintages=None, *,
                 source: str | None = None, reference: bool = False):
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; tiers are {', '.join(TIERS)}")
        self.task, self.tier, self.reference = task, tier, reference
        self.d1 = self.date = task["d1"]
        self.dates = [(dt.date.fromisoformat(self.d1) + dt.timedelta(days=k)).isoformat() for k in range(DAYS[tier])]
        self.notices_in = list(task.get("notices") or []) if notices is None else list(notices)
        self.deployments_in = list(task.get("deployments") or []) if deployments is None else list(deployments)
        self.slice = vintages if vintages is not None else FI.slice_for(task)
        self.source = source or task.get("source") or self.slice.get("source") or "desk"
        if self.source not in FI.SOURCES:
            raise ValueError(f"unknown forecast source {self.source!r}")
        self.vint = Vintages(self.slice, self.d1)
        self.site, self.win = site_for(task, tier), window_of(task, tier)
        self.n, self.H, self.end = self.win.days, self.win.hours, 1440 * self.win.days
        if tier != "front-lite" and not self.win.offered:
            raise ValueError(f"{task['task_id']} has no DA AS prices; only front-lite loads")
        self.watches, self.watch_kinds = schedule(task, tier, self.notices_in, self.deployments_in, self.vint)
        self.scheduled = {n.event_id: (n, w.index) for w in self.watches for n in w.notices}
        events = events_of(task, self.notices_in, self.deployments_in)
        self.dep_real = deploy_hours([n.deploy for n in (parse_notice(x, self.d1, 60) for x in events) if n.deploy],
                                     self.win.dur, self.H)
        self._dep_cache: tuple[int, list[dict]] | None = None
        self._basis_cache: dict = {}
        self.done, self.end_reason = False, None
        self.watch, self.calls = 0, 0
        self.planning_calls, self.forecast_calls, self.dam_submits = [0], [0], [0]
        self.book = {f: [0] * self.H for f in FIELDS}
        self.xda: list[float | None] = [None] * self.H
        self.pv_da: list[float] = [0.0] * self.H
        self.dam = [{"day": self.day_date(k), "gate_watch": None, "submits": 0, "accepted": [], "share": None,
                     "final": False, "missed": False} for k in range(self.n)]
        self.S, self.cyc = self.site.s0, 0.0
        self.soc_hist = [self.site.s0]
        self.rows: list[dict] = []
        self.cash = dict.fromkeys(CASH_KEYS, 0.0)
        self.snap: list[dict | None] = [None] * self.H
        self.end_snap: float | None = None
        self.end_short = self.end_short_charged = 0.0
        self.governor, self.excused, self.refusals, self.commits = [], [], [], []
        self.forecast_log: list[dict] = []
        self.da_log: list[dict] = []
        self.dam_log: list[dict] = []
        self._init_watch_log()
        self.frozen = [self._frozen_row()]
        self._grade: dict | None = None
        self._refs: dict | None = None
        self.anchor_log: list[dict] = []
        for n in self.watches[0].notices:
            self.notice(**self._kw(n), via="load")

    # clock and state

    @property
    def minute(self) -> int:
        return self.end if self.done else self.watches[self.watch].minute

    @property
    def last(self) -> bool:
        return self.watch == len(self.watches) - 1

    @property
    def settled(self) -> int:
        return len(self.rows)

    @property
    def first_open(self) -> int:
        return self.H if self.done else min(self.H, max(0, freeze_line(self.minute, self.tier) // 60))

    @property
    def calls_left(self) -> int:
        return PLANNING_CALLS - self.planning_calls[-1]

    @property
    def forecast_calls_left(self) -> int:
        return 0 if self.tier == "blind" else FORECAST_CALLS - self.forecast_calls[-1]

    @property
    def submits_left(self) -> int:
        return DAM_SUBMITS - self.dam_submits[-1] if self.gate_day() is not None else 0

    def gate_day(self) -> int | None:
        """The operating day whose DAM gate is this watch, if any."""
        if self.done:
            return None
        k = next((k for k in range(self.n) if gate_minute(k) == self.minute), None)
        return k

    def day_date(self, k: int) -> str:
        return (dt.date.fromisoformat(self.d1) + dt.timedelta(days=k)).isoformat()

    def da_revealed(self, k: int, minute: float | None = None) -> bool:
        return (self.minute if minute is None else minute) >= results_minute(k)

    def da_at(self, h: int) -> float:
        """The DA price of a window hour, or of d1-1 (h -24..-1) from the row's history."""
        if h >= 0:
            return float(self.win.da[h])
        return float(((self.task.get("history") or {}).get("dam") or [[0.0] * 24])[-1][h + 24])

    def mcpc_at(self, p: str, h: int) -> float:
        if h >= 0:
            return float(self.win.mda[p][h])
        last = ((self.task.get("history") or {}).get("mcpc_da") or {}).get(p)
        return float(last[-1][h + 24]) if last else 0.0

    def watch_time_utc(self, k: int) -> str:
        return self.watches[k].time_utc

    def status(self) -> str:
        fo = self.first_open
        return "".join("S" if h < self.settled else "F" if h < fo else "O" for h in range(self.H))

    def clock(self, minute: float) -> str:
        return stamp(minute, self.d1)

    def _when(self) -> str:
        return f'a time like "{self.clock(600)}" (CPT without an offset)'

    def entry(self, h: int, book: dict | None = None) -> tuple[float, dict]:
        book = self.book if book is None else book
        return float(book["energy"][h]), {k: float(book[k][h]) for k in PRODUCTS}

    def profit(self) -> float:
        c = self.cash
        return float(c["energy_da"] + c["energy_rt"] + c["as_da"] - c["degradation"] - c["ftp"] - c["end_penalty"])

    def cash_out(self) -> dict:
        return {k: _r2(v) for k, v in self.cash.items()} | {"total": _r2(self.profit())}

    def _frozen_row(self) -> dict:
        return {"watch": self.watch, "time": self.clock(self.minute),
                "freeze_line": self.clock(freeze_line(self.minute, self.tier)),
                "frozen_until_hour": self.first_open, "call": self.calls}

    def _msg(self, n: Notice, minute: int) -> dict:
        out = {"time": self.clock(minute), "issued_at": self.clock(n.issued), "event_id": n.event_id,
               "source": n.source, "level": n.level, "name": n.name, "title": n.title, "text": n.text}
        return out if n.deploy is None else out | {"deploy": self._deploy_row(n)}

    def _deploy_row(self, n: Notice) -> dict:
        d = n.deploy
        return {"event_id": n.event_id, "product": d["product"], "frac": d["frac"],
                "from": self.clock(d["start_min"]), "until": self.clock(d["end_min"])}

    def _dep_known(self) -> list[dict]:
        if self._dep_cache is None or self._dep_cache[0] != len(self.delivered):
            pays = [self.scheduled[e][0].deploy for e in self.delivered if self.scheduled[e][0].deploy]
            self._dep_cache = (len(self.delivered), deploy_hours(pays, self.win.dur, self.H))
        return self._dep_cache[1]

    def _expected(self, h: int, a: dict, dep: list[dict]) -> tuple[float, float]:
        w = self.win
        return (w.mean_up * a["regup"] + sum(dep[h][k] * a[k] for k in EVENT_PRODUCTS), w.mean_dn * a["regdn"])

    def day_fixed(self, k: int) -> bool:
        """The day's DA position is fixed: its gate has closed (or this is its gate and an entry was accepted)."""
        return self.dam[k]["final"] or bool(self.dam[k]["accepted"])

    def x_da(self, h: int, book: dict | None = None, basis: dict | None = None) -> float:
        """The hour's DA position: the accepted DAM entry's, 0 for a closed gate without one, and for a gate still
        ahead the book's projected export at the served P50s (as if the book were bid)."""
        k = h // 24
        if self.xda[h] is not None:
            return float(self.xda[h])
        if self.day_fixed(k):
            return 0.0
        b = self.basis() if basis is None else basis
        e, a = self.entry(h, book)
        return x_da_of(self.site, float(b["pv"][h]), float(b["da"][h]), e, a)

    # forecasts and the projection basis

    def kind_of(self, kind: str) -> tuple[str, str]:
        """(store kind, P50 field) of a served load/wind/solar kind for the window's source."""
        return (FI.ERCOT_KINDS if self.source == "ercot" else FI.DESK_KINDS)[kind]

    def basis(self, mode: str | None = None) -> dict:
        """Per window hour as known now: DA (revealed or the guide's), RT, MCPC, site PV and the end-penalty price.
        Modes: p50 (the front tiers), mean3 (the mean of P10, P50 and P90), persist (blind: the last revealed DA day,
        RT expected at DA, PV of the last settled day)."""
        mode = mode or ("persist" if self.tier == "blind" else "p50")
        key = (self.minute, mode, self.settled)
        if key in self._basis_cache:
            return self._basis_cache[key]
        w, m, pt = self.win, self.minute, self.task["settlement_point"]
        hist = self.task.get("history") or {}
        da, rt, pv = np.zeros(self.H), np.zeros(self.H), np.zeros(self.H)
        mcpc = {k: np.zeros(self.H) for k in w.offered}
        known = [k for k in range(self.n) if self.da_revealed(k, m)]
        solar_kind = ("ercot_solar" if self.source == "ercot" else "solar", "site", "mw")

        def q(kind, key, field, h):
            if mode == "mean3":
                xs = [self.vint.served(kind, key, field.replace("p50", s), m, h) for s in ("p10", "p50", "p90")]
                return None if any(x is None for x in xs) else float(np.mean(xs))
            return self.vint.served(kind, key, field, m, h)

        for h in range(self.H):
            k, hr = h // 24, h % 24
            if k in known:
                da[h] = w.da[h]
                for p in w.offered:
                    mcpc[p][h] = w.mda[p][h]
            elif mode == "persist" or q("price", pt, "da_p50", h) is None:
                j = max(known) if known else None
                da[h] = w.da[24 * j + hr] if j is not None else float((hist.get("dam") or [[0.0] * 24])[-1][hr])
                for p in w.offered:
                    last = (hist.get("mcpc_da") or {}).get(p)
                    mcpc[p][h] = w.mda[p][24 * j + hr] if j is not None else float(last[-1][hr] if last else 0.0)
            else:
                da[h] = q("price", pt, "da_p50", h)
                for p in w.offered:
                    x = q("mcpc", p, "p50", h)
                    mcpc[p][h] = max(0.0, x) if x is not None else 0.0
            x = None if mode == "persist" else q("price", pt, "rt_p50", h)
            rt[h] = da[h] if x is None else x
            if self.tier != "front-lite":
                x = None if mode == "persist" else self.vint.served(*solar_kind[:2], solar_kind[2], m, h)
                pv[h] = self._pv_persist(h, m) if x is None else max(0.0, x)
        for h in range(self.settled):
            da[h], rt[h], pv[h] = w.da[h], w.rt[h], w.pv[h]
        out = {"da": da, "rt": rt, "pv": pv, "mcpc": mcpc, "mode": mode,
               "pen": max(float(da.max()), P_FLOOR) / self.site.eta}
        self._basis_cache[key] = out
        return out

    def _pv_persist(self, h: int, minute: float) -> float:
        hr = h % 24
        settled = [hh for hh in range(hr, self.settled, 24)]
        if settled:
            return float(self.win.pv[settled[-1]])
        hist = (self.task.get("history") or {}).get("pv_mw") or [[0.0] * 24, [0.0] * 24]
        return float(hist[-1][hr] if minute >= -1440 + 60 * (hr + 1) else hist[-2][hr])

    def projected_state(self, h: int, book: dict | None = None) -> tuple[float, float]:
        """SoC and discharged MWh at the start of hour h on the projection of a book."""
        st, w, dep, b = self.site, self.win, self._dep_known(), self.basis()
        S, cyc = self.S, self.cyc
        for t in range(self.settled, h):
            e, a = self.entry(t, book)
            r = step(st, w.dur, S, cyc, e, a, b["pv"][t], self._curtail_price(t, b), *self._expected(t, a, dep))
            S, cyc = r["S"], cyc + r["dis"]
        return S, cyc

    def _curtail_price(self, h: int, b: dict) -> float:
        return float(b["rt"][h] if self.day_fixed(h // 24) else b["da"][h])

    def _project(self, book: dict | None = None) -> dict:
        """The window as known now: settled hours as settled, the rest on the served P50s (C3-D7 snapshot source)."""
        book = self.book if book is None else book
        st, w, dep, b = self.site, self.win, self._dep_known(), self.basis()
        S, cyc = self.S, self.cyc
        soc, margin = [_r2(x) for x in self.soc_hist], [_r2(r["margin"]) for r in self.rows]
        tot = dict(self.cash)
        short, governed = {}, {}
        for h in range(self.settled, self.H):
            e, a = self.entry(h, book)
            r = step(st, w.dur, S, cyc, e, a, b["pv"][h], self._curtail_price(h, b), *self._expected(h, a, dep))
            xda = self.x_da(h, book, b)
            tot["energy_da"] += xda * b["da"][h]
            tot["energy_rt"] += (r["x"] - xda) * b["rt"][h]
            tot["as_da"] += sum(a[k] * b["mcpc"][k][h] for k in w.offered)
            tot["degradation"] += st.c_deg * (r["dis"] + r["up_mwh"])
            tot["ftp"] += sum(v * b["mcpc"].get(k, np.zeros(self.H))[h] for k, v in r["short"].items())
            short[h], governed[h] = r["short"], r["governed"]
            S, cyc = r["S"], cyc + r["dis"]
            soc.append(_r2(S))
            margin.append(_r2(r["margin"]))
        end_short = max(0.0, st.s_end - S) if not self.done else self.end_short
        if not self.done:
            tot["end_penalty"] = end_short * b["pen"]
        total = (tot["energy_da"] + tot["energy_rt"] + tot["as_da"] - tot["degradation"] - tot["ftp"]
                 - tot["end_penalty"])
        summary = {"soc_end_mwh": _r2(S), "reserve_margin_min_mwh": min(margin[self.settled:], default=None),
                   "energy_da_usd": _r2(tot["energy_da"]), "energy_rt_usd": _r2(tot["energy_rt"]),
                   "as_usd": _r2(tot["as_da"]), "degradation_usd": _r2(tot["degradation"]),
                   "ftp_usd": _r2(tot["ftp"]), "end_penalty_usd": _r2(tot["end_penalty"]), "total_usd": _r2(total),
                   "basis": "persistence" if b["mode"] == "persist" else "P50 as of now"}
        return {"summary": summary, "soc": soc, "margin": margin, "short": short, "governed": governed,
                "end_short": end_short, "S": S}

    # tools

    def _dispatch(self, tool: str, args: dict) -> dict:
        want = {"get_situation": (), "advance": (), "get_forecast": ("kind", "zone", "hours", "issued_at"),
                "get_forecast_drift": ("kind", "target_hour", "zone"), "check_schedule": ("plan", "from_hour"),
                "commit_schedule": ("plan", "from_hour"), "submit_dam": ("operating_day", "plan", "pv_da_share")}[tool]
        need = {"get_forecast": ("kind",), "get_forecast_drift": ("kind", "target_hour"), "check_schedule": ("plan",),
                "commit_schedule": ("plan",), "submit_dam": ("operating_day", "plan")}.get(tool, ())
        extra = sorted(set(args) - set(want))
        missing = [k for k in need if k not in args]
        if extra or missing:
            bad = f"unexpected argument {extra[0]!r}" if extra else f"missing argument {missing[0]!r}"
            return self._spend(tool) | {"error": f"{tool}: {bad}"}
        return getattr(self, tool)(**args)

    def _spend(self, tool: str) -> dict:
        """Use the tool's call when one is left (L-D7) and return its budget row."""
        if tool in PLANNING_TOOLS:
            if not self.done and self.calls_left:
                self.planning_calls[-1] += 1
            return {"calls_left": 0 if self.done else self.calls_left}
        if tool in FORECAST_TOOLS:
            if not self.done and self.forecast_calls_left:
                self.forecast_calls[-1] += 1
            return {"forecast_calls_left": 0 if self.done else self.forecast_calls_left}
        if tool == "submit_dam":
            if not self.done and self.submits_left:
                self.dam_submits[-1] += 1
            return {"submits_left": self.submits_left}
        return {}

    def _log_rt(self, out: dict):
        n = len(out.get("rt_usd_last_24h") or []) and self.settled
        if out.get("realized"):
            n = max(n, max(r["h"] for r in out["realized"]) + 1)
        self.rt_log.append({"call": self.calls, "minute": self.minute, "rt_shown": n})
        for k in sorted(self._shown_da_days(out)):
            self.da_log.append({"call": self.calls, "minute": self.minute, "day": k})

    def _shown_da_days(self, out: dict) -> set[int]:
        """The window days whose DA prices or MCPCs an output shows (the audit checks each against its reveal)."""
        days = {i for i, d in enumerate(out.get("days") or []) if d.get("da_usd") is not None or d.get("mcpc_da")}
        if out.get("dam_results"):
            days.add(self.dates.index(out["dam_results"]["operating_day"]))
        if out.get("kind") == "price" and out.get("from"):
            h0 = to_minute(out["from"], self.d1) // 60
            days |= {(h0 + i) // 24 for i, known in enumerate(out["da"]["known"]) if known}
            for p, q in (out.get("mcpc_da") or {}).items():
                days |= {(h0 + i) // 24 for i, v in enumerate(q["p50"]) if _r2(self.mcpc_at(p, h0 + i)) == v
                         and self.da_revealed((h0 + i) // 24)}
        return days

    def situation(self) -> dict:
        t, st, w = self.task, self.site, self.win
        proj = self._project()
        n = self.settled
        k = self.gate_day()
        days = []
        for d in range(self.n):
            rev = self.da_revealed(d)
            dm = self.dam[d]
            if dm["final"]:
                state = "submitted" if dm["accepted"] else "missed"
            else:
                state = "submitted" if dm["accepted"] else "open" if k == d else "pending"
            days.append({"date": self.day_date(d), "first_hour": 24 * d, "dam": state,
                         "da_usd": [_r2(x) for x in w.da[24 * d:24 * d + 24]] if rev else None,
                         "mcpc_da": {p: [_r2(x) for x in w.mda[p][24 * d:24 * d + 24]] for p in w.offered}
                         if rev and w.offered else None,
                         "x_da_mw": [_r2(self.xda[h] or 0.0) for h in range(24 * d, 24 * d + 24)]
                         if dm["accepted"] or dm["final"] else None,
                         "awards": {p: [_num(self.book[p][h]) for h in range(24 * d, 24 * d + 24)] for p in w.offered}
                         if dm["accepted"] and w.offered else None,
                         "pv_da_share": dm["share"]})
        site = {"coupling": t["site"]["coupling"], "pv_mwac": 0 if self.tier == "front-lite" else t["site"]["pv_mwac"],
                "meter_mw": st.meter, "meter_import_mw": st.meter_imp, "p_mw": st.p, "e_mwh": st.e, "eta": st.eta,
                "c_deg": st.c_deg, "cycle_cap_mwh": _r2(st.cap), "cycle_used_mwh": _r2(self.cyc),
                "s_end_min_mwh": st.s_end}
        out = {"task_id": t["task_id"], "tier": self.tier, "era": w.era, "source": self.source,
               "settlement_point": t["settlement_point"], "zone": t.get("zone"), "site_id": t["site"]["site_id"],
               "region": t.get("region"),
               "window": {"days": [self.day_date(d) for d in range(self.n)], "open": self.clock(OPEN),
                          "end": self.clock(self.end), "hour_0": self.clock(0)},
               "watch": self.watch, "time": self.clock(self.minute), "phase": "dam_gate" if k is not None else "rt",
               "frozen_until_hour": self.first_open, "calls_left": 0 if self.done else self.calls_left,
               "forecast_calls_left": 0 if self.done else self.forecast_calls_left, "window_over": self.done,
               "dam_gate": {"operating_day": self.day_date(k), "submits_left": self.submits_left,
                            "submitted": bool(self.dam[k]["accepted"])} if k is not None else None,
               "site": site}
        if w.offered:
            out["as_rules"] = {"products": list(w.offered), "qualified": [p for p in w.offered if p in w.qualified],
                               "duration_h": {p: w.dur[p] for p in w.offered},
                               "reg_drift_mean": {"regup": w.mean_up, "regdn": w.mean_dn}, "set_by": "submit_dam"}
        out |= {"days": days, "rt_usd_last_24h": [_r2(x) for x in w.rt[max(0, n - 24):n]],
                "pv_mw_last_24h": [_r2(r["pv"]) for r in self.rows[max(0, n - 24):n]] if self.tier != "front-lite"
                else None, "soc_mwh": _r2(self.S), "status": self.status(),
                "book": {"energy": [_num(x) for x in self.book["energy"]]}, "projected": proj["summary"],
                "cash": self.cash_out(), "latest_vintages": self._latest_vintages(),
                "active_alerts": self._alerts()[:5],
                "notices": [self._msg(self.scheduled[e["event_id"]][0], e["minute"]) for e in self.log if e["first"]]}
        if self.done:
            out["result"] = self._done_result()
        return out

    def get_situation(self) -> dict:
        return self.situation()

    def _latest_vintages(self) -> dict | None:
        if self.tier == "blind":
            return None
        m, out = self.minute, {}
        keys = {"weather": ("weather", self.task.get("weather_point") or FI.site_point(self.task["settlement_point"])),
                "load": (self.kind_of("load")[0], "system"), "wind": (self.kind_of("wind")[0], "system"),
                "solar": (self.kind_of("solar")[0], "system"), "price": ("price", self.task["settlement_point"]),
                "load_official": ("load_official", "system")}
        for name, (kind, key) in keys.items():
            r = self.vint.latest(kind, key, m)
            out[name] = self.clock(r.minute) if r else None
        return out

    def _alerts(self) -> list[dict]:
        out = []
        for e in self.log:
            if not e["first"]:
                continue
            n = self.scheduled[e["event_id"]][0]
            if n.source != "NWS":
                continue
            until = live.to_minutes(n.until, self.d1) if n.until else None
            if (until is None and e["minute"] > self.minute - 1440) or (until is not None and until > self.minute):
                out.append({"event_id": n.event_id, "name": n.name, "title": n.title,
                            "until": self.clock(until) if until is not None else None})
        return out[::-1]

    def _forecast_err(self, msg: str) -> dict:
        return {"error": msg, "forecast_calls_left": self.forecast_calls_left}

    def _forecast_gate(self) -> dict | None:
        if self.tier == "blind":
            return {"error": "forecasts are withheld in the blind tier", "forecast_calls_left": 0}
        if self.done:
            return {"error": "the window is over", "forecast_calls_left": 0}
        if not self.forecast_calls_left:
            return {"error": f"no forecast calls left in this watch ({FORECAST_CALLS} used): call advance",
                    "forecast_calls_left": 0}
        self.forecast_calls[-1] += 1
        return None

    def _key(self, kind: str, zone) -> tuple[str, str] | str:
        """(store kind, key) for a forecast request, or an error message."""
        pt = self.task.get("weather_point") or FI.site_point(self.task["settlement_point"])
        if kind == "weather":
            if zone in (None, "site"):
                return "weather", pt
            if str(zone) in FI.points():
                return "weather", str(zone)
            code = FI.zone_code(str(zone))
            if code is None:
                return f"unknown zone or point {zone!r}"
            return "weather", FI.zones()[code]["point"]
        if kind == "price":
            return "price", self.task["settlement_point"]
        sk = self.kind_of(kind)[0]
        if kind == "load":
            if zone in (None, "system"):
                return sk, "system"
            code = FI.zone_code(str(zone))
            return (sk, code) if code else f"unknown zone {zone!r}; zones are {', '.join(self._zone_names())}"
        if kind == "wind":
            return (sk, "system") if zone in (None, "system") else "wind is served for the system only"
        if zone in (None, "site") and self.tier != "front-lite":
            return sk, "site"
        if zone in (None, "system"):
            return sk, "system"
        return "solar zones are system and site"

    @staticmethod
    def _zone_label(key: str) -> str:
        return FI.zones()[key]["name"] if key in FI.zones() else key

    @staticmethod
    def _zone_names() -> list[str]:
        return [v["name"] for v in FI.zones().values()]

    def _log_vintage(self, r: VRec):
        self.forecast_log.append({"call": self.calls, "minute": self.minute, "kind": r.v["kind"], "key": r.v["key"],
                                  "issued_at": r.v["issued_at"], "sha": r.v["sha"], "reveal_minute": r.minute})

    def get_forecast(self, kind, zone=None, hours=48, issued_at=None) -> dict:
        if err := self._forecast_gate():
            return err
        if kind not in KINDS:
            return self._forecast_err(f"kind must be one of {', '.join(KINDS)}")
        if isinstance(hours, bool) or not isinstance(hours, int) or not 1 <= hours <= 72:
            return self._forecast_err("hours must be an integer 1..72")
        cutoff = self.minute
        if issued_at is not None and str(issued_at).strip():
            m = to_minute(str(issued_at), self.d1)
            if m is None:
                return self._forecast_err(f"issued_at must be {self._when()}, or blank for the latest")
            if m > self.minute:
                return self._forecast_err(f"issued_at is after now ({self.clock(self.minute)}): forecasts are "
                                          "served as issued")
            cutoff = m
        h_from = math.ceil(self.minute / 60)
        hrs = range(h_from, min(h_from + hours, self.H))
        if kind == "alerts":
            return {"kind": "alerts", "alerts": self._alerts(), "forecast_calls_left": self.forecast_calls_left}
        sk = self._key(kind, zone)
        if isinstance(sk, str):
            return self._forecast_err(sk)
        r = self.vint.latest(*sk, cutoff)
        if r is None:
            return self._forecast_err(f"no {kind} forecast was issued by {self.clock(cutoff)}")
        self._log_vintage(r)
        cover = [h for h in hrs if Vintages.at(r, next(iter(r.v["fields"])), h) is not None]
        out = {"kind": kind, ("point" if kind in ("price", "weather") else "zone"): self._zone_label(sk[1]),
               "issued_at": self.clock(r.minute), "source": self._source_label(r),
               "from": self.clock(60 * cover[0]) if cover else None}

        def vals(field, rec=r):
            return [_r2(Vintages.at(rec, field, h)) for h in cover]

        if kind == "weather":
            out["zone"] = next((v["name"] for v in FI.zones().values() if v["point"] == sk[1]), None)
            for f in ("t2m_f", "wind80_ms", "dswrf_wm2", "cloud_pct"):
                out[f] = [round(float(Vintages.at(r, f, h)), 1) for h in cover]
        elif kind == "price":
            da = {q: vals(f"da_{q}") for q in ("p10", "p50", "p90")}
            known = [self.da_revealed(h // 24) for h in cover]
            for i, h in enumerate(cover):
                if known[i]:
                    for q in da:
                        da[q][i] = _r2(self.da_at(h))
            out["da"] = da | {"known": known}
            out["rt"] = {q: vals(f"rt_{q}") for q in ("p10", "p50", "p90")}
            if self.win.offered:
                mc = {}
                for p in self.win.offered:
                    rp = self.vint.latest("mcpc", p, cutoff)
                    if rp is None:
                        continue
                    self._log_vintage(rp)
                    mc[p] = {q: [_r2(self.mcpc_at(p, h)) if self.da_revealed(h // 24) else
                                 _r2(Vintages.at(rp, q, h) or 0.0) for h in cover] for q in ("p10", "p50", "p90")}
                out["mcpc_da"] = mc
        else:
            field = self.kind_of(kind)[1] if sk[0].startswith("ercot") and sk[1] != "site" else "mw"
            out["mw"] = vals(field)
            if sk[0].startswith("ercot") and sk[1] != "site":
                p80 = "wgrpp_mw" if kind == "wind" else "pvgrpp_mw" if kind == "solar" else None
                if p80 and p80 in r.v["fields"]:
                    out["p80_mw"] = vals(p80)
            prev = self.vint.previous(*sk, r)
            if prev is not None:
                self._log_vintage(prev)
                out["prev_vintage_delta_mw"] = [
                    None if Vintages.at(prev, field, h) is None else _r2(Vintages.at(r, field, h)
                                                                         - Vintages.at(prev, field, h))
                    for h in cover]
            else:
                out["prev_vintage_delta_mw"] = None
            if kind == "load":
                out["official"] = self._official(cutoff, cover)
        out["forecast_calls_left"] = self.forecast_calls_left
        return out

    def _official(self, cutoff: float, cover: list[int]) -> dict | None:
        rs = [r for r in self.vint.all("load_official", "system", cutoff)
              if any(Vintages.at(r, "mw", h) is not None for h in cover)]
        if not rs:
            return None
        r = rs[-1]
        self._log_vintage(r)
        hrs = [h for h in cover if Vintages.at(r, "mw", h) is not None]
        return {"issued_at": self.clock(r.minute), "source": "ERCOT day-ahead forecast via EIA-930",
                "from": self.clock(60 * hrs[0]), "mw": [_r2(Vintages.at(r, "mw", h)) for h in hrs]}

    def _source_label(self, r: VRec) -> str:
        kind, run = r.v["kind"], r.v.get("run_id") or ""
        if kind.startswith("ercot_"):
            return {"ercot_load": "ERCOT NP3-565 (model in use)", "ercot_wind": "ERCOT NP4-732 STWPF",
                    "ercot_solar": "ERCOT NP4-745 STPPF"}[kind]
        cyc = run[-3:] if run.endswith("Z") else run
        if kind == "weather":
            return f"NOAA HRRR {cyc} run" + (" (synthetic)" if r.v.get("source") == "synthetic" else "")
        if kind in ("price", "mcpc"):
            return "desk price guide (modelled)" + (" (synthetic)" if r.v.get("source") == "synthetic" else "")
        return f"desk {kind} model on HRRR {cyc}" + (" (synthetic)" if r.v.get("source") == "synthetic" else "")

    def get_forecast_drift(self, kind, target_hour, zone=None) -> dict:
        if err := self._forecast_gate():
            return err
        if kind not in DRIFT_KINDS:
            return self._forecast_err(f"kind must be one of {', '.join(DRIFT_KINDS)}")
        h = self._hour_arg(target_hour)
        if h is None or not 0 <= h < self.H:
            return self._forecast_err(f"target_hour must be a window hour 0..{self.H - 1} or {self._when()}")
        sk = self._key(kind, zone)
        if isinstance(sk, str):
            return self._forecast_err(sk)
        rows = []
        for r in self.vint.all(*sk, self.minute):
            if kind == "price":
                x = {f: Vintages.at(r, f, h) for f in ("da_p50", "rt_p50", "da_p10", "da_p90")}
                if x["da_p50"] is None:
                    continue
                value = {f: _r2(v) for f, v in x.items() if v is not None}
            elif kind == "weather":
                x = Vintages.at(r, "t2m_f", h)
                if x is None:
                    continue
                value = {"t2m_f": round(float(x), 1), "wind80_ms": round(float(Vintages.at(r, "wind80_ms", h)), 1)}
            else:
                field = self.kind_of(kind)[1] if sk[0].startswith("ercot") and sk[1] != "site" else "mw"
                x = Vintages.at(r, field, h)
                if x is None:
                    continue
                value = _r2(x)
            self._log_vintage(r)
            rows.append({"issued_at": self.clock(r.minute), "value": value})
        if kind == "load":
            for r in self.vint.all("load_official", "system", self.minute):
                x = Vintages.at(r, "mw", h)
                if x is not None:
                    self._log_vintage(r)
                    rows.append({"issued_at": self.clock(r.minute), "value": _r2(x), "official": True})
            rows.sort(key=lambda x: x["issued_at"])
        return {"kind": kind, "key": self._zone_label(sk[1]), "target": self.clock(60 * h), "vintages": rows,
                "forecast_calls_left": self.forecast_calls_left}

    def _hour_arg(self, v) -> int | None:
        if isinstance(v, bool):
            return None
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        if isinstance(v, int):
            return v
        if isinstance(v, str) and _INT.match(v):
            return int(v)
        m = to_minute(str(v), self.d1)
        return m // 60 if m is not None and m % 60 == 0 else None

    def _planning(self) -> dict | None:
        if self.done:
            return {"error": "the window is over", "calls_left": 0}
        if not self.calls_left:
            return {"error": f"no planning calls left in this watch ({PLANNING_CALLS} used): call advance",
                    "calls_left": 0}
        self.planning_calls[-1] += 1
        return None

    def _issue(self, h, field, rule, detail) -> dict:
        return {"hour": h, "field": field, "rule": rule, "detail": detail}

    def rules(self, h: int, S: float, cyc: float, e: float, a: dict, inherited: bool = False) -> list[dict]:
        w = self.win
        return hour_rules(self.site, w.dur, h, S, cyc, e, a, inherited, offered=w.offered, qualified=w.qualified,
                          not_offered=lambda f: "front-lite trades energy only" if self.tier == "front-lite"
                          else f"{NAMES[f]} is not offered in this window", clock=self.clock)

    def _parse_energy(self, plan, from_hour) -> tuple[int, list[float]]:
        if isinstance(plan, str):
            try:
                plan = json.loads(plan)
            except json.JSONDecodeError:
                raise PlanError("plan", "plan: not a JSON object") from None
        plan = kept(plan)
        if isinstance(plan, dict) and set(plan) & set(PRODUCTS):
            raise PlanError("plan", "plan: AS are set by submit_dam at the DAM gate; this tool takes energy only")
        fh = self._hour_arg(self.first_open if from_hour is None else from_hour)
        if fh is None:
            raise PlanError("from_hour", f"from_hour must be a window hour 0..{self.H - 1} or {self._when()}")
        try:
            fh, fields = parse_plan(plan, fh, self.H, ("energy",))
        except PlanError as e:
            raise keep_hint(e) from None
        return fh, fields["energy"]

    def _evaluate(self, vals: list[float], fh: int) -> tuple[dict, list[int], list[int], list[dict]]:
        """C3-D2 for energy over window hours, AS as the DAM set them (inherited, C3-D17)."""
        fo, cand = self.first_open, list(self.book["energy"])
        cand[fh:] = [b if abs(v - b) <= EQ_TOL else v for v, b in zip(vals, self.book["energy"][fh:], strict=True)]
        issues, refused = [], []
        for h in range(fh, min(fo, self.H)):
            if cand[h] != self.book["energy"][h]:
                state = "settled" if h < self.settled else "frozen"
                issues.append(self._issue(h, "energy", "frozen", f"hour {h} is {state}; hours from {fo} are open"))
                refused.append(h)
        new, committed = {f: list(v) for f, v in self.book.items()}, []
        st, w, dep, b = self.site, self.win, self._dep_known(), self.basis()
        S, cyc = self.S, self.cyc
        for h in range(self.settled, self.H):
            if h >= max(fh, fo):
                e, a = cand[h], self.entry(h, new)[1]
                if iss := self.rules(h, S, cyc, e, a, True):
                    issues += iss
                    refused.append(h)
                else:
                    committed.append(h)
                    new["energy"][h] = cand[h]
            e, a = self.entry(h, new)
            r = step(st, w.dur, S, cyc, e, a, b["pv"][h], self._curtail_price(h, b), *self._expected(h, a, dep))
            S, cyc = r["S"], cyc + r["dis"]
        return new, committed, sorted(refused), issues

    def check_schedule(self, plan=None, from_hour=None) -> dict:
        if err := self._planning():
            return err
        try:
            fh, vals = self._parse_energy(plan, from_hour)
        except PlanError as e:
            return {"feasible": False, "issues": [e.row()], "refused": [], "projected": None, "soc_mwh_path": None,
                    "reserve_margin_mwh_by_hour": None, "calls_left": self.calls_left}
        new, _, refused, issues = self._evaluate(vals, fh)
        proj = self._project(new)
        return {"feasible": not issues, "issues": issues, "refused": refused, "projected": proj["summary"],
                "soc_mwh_path": proj["soc"][fh:], "reserve_margin_mwh_by_hour": proj["margin"][fh:],
                "calls_left": self.calls_left}

    def commit_schedule(self, plan=None, from_hour=None) -> dict:
        if err := self._planning():
            return err
        try:
            fh, vals = self._parse_energy(plan, from_hour)
        except PlanError as e:
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": [e.row()]})
            self.commits.append({"watch": self.watch, "from_hour": None, "committed": [], "refused": [],
                                 "call": self.calls})
            return {"committed": [], "refused": [e.row()], "frozen_until_hour": self.first_open,
                    "book": {"energy": [_num(x) for x in self.book["energy"]]},
                    "projected": self._project()["summary"], "calls_left": self.calls_left}
        new, committed, refused, issues = self._evaluate(vals, fh)
        if issues:
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": issues})
        self.book = new
        self.commits.append({"watch": self.watch, "from_hour": fh, "committed": committed, "refused": refused,
                             "call": self.calls})
        return {"committed": committed, "refused": issues, "frozen_until_hour": self.first_open,
                "book": {"energy": [_num(x) for x in self.book["energy"]]}, "projected": self._project()["summary"],
                "calls_left": self.calls_left}

    def submit_dam(self, operating_day=None, plan=None, pv_da_share=1.0) -> dict:
        k = self.gate_day()
        if self.done:
            return {"error": "the window is over", "submits_left": 0}
        if k is None:
            nxt = next((self.clock(gate_minute(d)) for d in range(self.n) if gate_minute(d) > self.minute), None)
            return {"error": "submit_dam is open only at the 10:00 DAM watch the day before an operating day"
                             + (f" (next: {nxt})" if nxt else " (no gate is left)"), "submits_left": 0}
        if not self.submits_left:
            return {"error": f"no DAM submits left at this gate ({DAM_SUBMITS} used): call advance", "submits_left": 0}
        self.dam_submits[-1] += 1
        day = self.day_date(k)
        if str(operating_day) != day:
            return {"error": f"this gate takes the DAM for {day}, not {operating_day!r}",
                    "submits_left": self.submits_left}
        if isinstance(pv_da_share, bool) or not isinstance(pv_da_share, (int, float)) or not 0 <= pv_da_share <= 1:
            return {"error": "pv_da_share must be a number in 0..1", "submits_left": self.submits_left}
        try:
            _, fields = parse_plan(kept(plan), 0, 24, FIELDS)
        except PlanError as e:
            e = keep_hint(e)
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": [e.row()]})
            return {"accepted": [], "refused": [e.row()], "operating_day": day, "x_da_mw": None, "pv_da_mw": None,
                    "awards": None, "projected": self._project()["summary"], "submits_left": self.submits_left}
        new, acc, ref, issues = self._evaluate_dam(k, fields)
        b = self.basis()
        share = float(pv_da_share)
        for h in acc:
            e, a = self.entry(h, new)
            up = sum(a[p] for p in UP)
            s = 0.0 if self.tier == "front-lite" or b["da"][h] < 0 else min(
                share * float(b["pv"][h]), max(0.0, self.site.meter - e - up))
            self.pv_da[h], self.xda[h] = s, e + s
        self.book = new
        dm = self.dam[k]
        dm["accepted"] = sorted(set(dm["accepted"]) | {h - 24 * k for h in acc})
        dm["submits"] += 1
        dm["gate_watch"] = self.watch
        if acc:
            dm["share"] = share
        self.dam_log.append({"day": k, "watch": self.watch, "minute": self.minute, "accepted": [h - 24 * k for h in acc],
                             "call": self.calls})
        if issues:
            self.refusals.append({"watch": self.watch, "call": self.calls, "refused": issues})
        hrs = range(24 * k, 24 * k + 24)
        return {"accepted": [h - 24 * k for h in acc], "refused": issues, "operating_day": day,
                "x_da_mw": [_r2(self.xda[h] or 0.0) for h in hrs], "pv_da_mw": [_r2(self.pv_da[h]) for h in hrs],
                "awards": {p: [_num(self.book[p][h]) for h in hrs] for p in self.win.offered},
                "projected": self._project()["summary"], "submits_left": self.submits_left}

    def _evaluate_dam(self, k: int, fields: dict) -> tuple[dict, list[int], list[int], list[dict]]:
        """C3-D2 and C3-D5 on day k's 24 hours from the projected SoC at its start: an hour whose entry fails keeps its
        previous entry, unless its energy alone passes with the previous awards."""
        h0 = 24 * k
        new = {f: list(v) for f, v in self.book.items()}
        cand = {f: list(v) for f, v in self.book.items()}
        for f, vals in fields.items():
            for i, v in enumerate(vals):
                cur = self.book[f][h0 + i]
                cand[f][h0 + i] = cur if abs(v - cur) <= EQ_TOL else v
        issues, acc, ref = [], [], []
        st, w, dep, b = self.site, self.win, self._dep_known(), self.basis()
        S, cyc = self.projected_state(h0)
        for h in range(h0, h0 + 24):
            e, a = self.entry(h, cand)
            booked = self.entry(h, new)[1]
            if iss := self.rules(h, S, cyc, e, a, a == booked):
                issues += [x | {"hour": h - h0} for x in iss]
                ref.append(h)
                if not self.rules(h, S, cyc, e, booked, True):
                    new["energy"][h] = cand["energy"][h]
                    acc.append(h)
            else:
                acc.append(h)
                for f in FIELDS:
                    new[f][h] = cand[f][h]
            e, a = self.entry(h, new)
            r = step(st, w.dur, S, cyc, e, a, b["pv"][h], b["da"][h], *self._expected(h, a, dep))
            S, cyc = r["S"], cyc + r["dis"]
        return new, acc, ref, issues

    def advance(self) -> dict:
        if self.done:
            return {"error": "the window is over", "calls_left": 0}
        prev = self.minute
        self._close_watch()
        if self.last:
            realized = self._settle(self.H)
            self._finish("done")
            return {"done": True, "time": self.clock(self.end), "realized": realized, "soc_mwh": _r2(self.S),
                    "cash": self.cash_out(), **self._done_result()}
        nxt = self.watches[self.watch + 1]
        realized = self._settle(min(self.H, max(0, nxt.minute // 60)))
        self._open()
        res = next((k for k in range(self.n) if prev < results_minute(k) <= self.minute), None)
        out = {"watch": self.watch, "time": self.clock(self.minute),
               "phase": "dam_gate" if self.gate_day() is not None else "rt", "frozen_until_hour": self.first_open,
               "realized": realized, "dam_results": self._dam_results(res) if res is not None else None,
               "new_vintages": self._new_vintages(prev), "soc_mwh": _r2(self.S), "cash": self.cash_out(),
               "calls_left": self.calls_left, "forecast_calls_left": self.forecast_calls_left}
        return out

    def _dam_results(self, k: int) -> dict:
        w, hrs = self.win, range(24 * k, 24 * k + 24)
        xda = [float(self.xda[h] or 0.0) for h in hrs]
        energy = sum(x * w.da[h] for x, h in zip(xda, hrs, strict=True))
        as_v = sum(self.book[p][h] * w.mda[p][h] for p in w.offered for h in hrs) if self.dam[k]["accepted"] else 0.0
        return {"operating_day": self.day_date(k), "da_usd": [_r2(w.da[h]) for h in hrs],
                "mcpc_da": {p: [_r2(w.mda[p][h]) for h in hrs] for p in w.offered} if w.offered else None,
                "x_da_mw": [_r2(x) for x in xda], "value_usd": {"energy": _r2(energy), "as": _r2(as_v)}}

    def _new_vintages(self, prev: float) -> list[dict]:
        if self.tier == "blind":
            return []
        out, m, pt = [], self.minute, self.task["settlement_point"]
        lk = self.kind_of("load")[0]
        for r in self.vint.all("price", pt, m):
            if prev < r.minute <= m:
                out.append({"kind": "weather_run", "issued_at": self.clock(r.minute), "source": self._run_label(r),
                            "headline": self._headline(r, lk)})
        if self.source == "ercot":
            new = [r for kk in ("ercot_load", "ercot_wind", "ercot_solar") for r in self.vint.all(kk, "system", m)
                   if prev < r.minute <= m]
            if new:
                last = max(r.minute for r in new)
                out.append({"kind": "ercot_postings", "issued_at": self.clock(last), "source": "ERCOT",
                            "headline": f"{len(new)} new ERCOT load, wind and solar postings"})
        for r in self.vint.all("load_official", "system", m):
            if prev < r.minute <= m:
                peak = max(r.v["fields"]["mw"])
                out.append({"kind": "load_official", "issued_at": self.clock(r.minute),
                            "source": "ERCOT day-ahead forecast via EIA-930",
                            "headline": f"ERCOT's day-ahead load forecast for {self.clock(60 * r.h0)[:10]}: peak "
                                        f"{peak:,.0f} MW"})
        return out

    def _run_label(self, r: VRec) -> str:
        run = r.v.get("run_id") or ""
        return f"HRRR {run[-3:]} run" if run.endswith("Z") else run

    def _headline(self, r: VRec, load_kind: str) -> str:
        m = r.minute
        fo = max(0, freeze_line(m, self.tier) // 60)
        prev = self.vint.previous("price", self.task["settlement_point"], r)
        parts = [self._run_label(r)]
        lr = self.vint.latest(load_kind, "system", m) if load_kind == "load" else self.vint.latest("load", "system", m)
        if lr is not None:
            vals = [(Vintages.at(lr, "mw", h), h) for h in range(fo, min(fo + 48, self.H))]
            vals = [(v, h) for v, h in vals if v is not None]
            if vals:
                peak, ph = max(vals)
                pl = self.vint.previous(lr.v["kind"], "system", lr)
                pp = Vintages.at(pl, "mw", ph) if pl is not None else None
                parts.append(f"desk peak load {peak:,.0f} MW at {self.clock(60 * ph)}"
                             + (f" ({peak - pp:+,.0f})" if pp is not None else ""))
        if prev is not None:
            pairs = [(Vintages.at(r, "rt_p50", h), Vintages.at(prev, "rt_p50", h)) for h in range(fo, self.H)]
            pairs = [(a, b) for a, b in pairs if a is not None and b is not None]
            if pairs:
                base = max(np.mean([abs(b) for _, b in pairs]), HRRR_FLOOR)
                parts.append(f"site RT P50 {100 * (np.mean([a for a, _ in pairs]) - np.mean([b for _, b in pairs])) / base:+.0f}%")
        return "; ".join(parts)

    def _close_watch(self):
        """The charged/excused snapshot of every open hour (C3-D7); a gate closes its day's DAM."""
        proj, fo = self._project(), self.first_open
        for h in range(fo, self.H):
            self.snap[h] = {"short": proj["short"][h], "governed": proj["governed"][h]}
        if fo < self.H:
            self.end_snap = proj["end_short"]
        k = self.gate_day()
        if k is not None:
            dm = self.dam[k]
            dm["final"], dm["missed"] = True, not dm["accepted"]
            if dm["gate_watch"] is None:
                dm["gate_watch"] = self.watch

    def _open(self):
        self.watch += 1
        self.planning_calls.append(0)
        self.forecast_calls.append(0)
        self.dam_submits.append(0)
        self.frozen.append(self._frozen_row())

    def _settle(self, upto: int) -> list[dict]:
        st, w, out = self.site, self.win, []
        for h in range(self.settled, upto):
            e, a = self.entry(h)
            U = w.reg_up[h] * a["regup"] + sum(self.dep_real[h][k] * a[k] for k in EVENT_PRODUCTS)
            D = w.reg_dn[h] * a["regdn"]
            r = step(st, w.dur, self.S, self.cyc, e, a, w.pv[h], w.rt[h], U, D)
            xda = float(self.xda[h] or 0.0)
            ftp_price = {k: float(w.mda[k][h]) if k in w.mda else 0.0 for k in PRODUCTS}
            c = {"energy_da": xda * w.da[h], "energy_rt": (r["x"] - xda) * w.rt[h],
                 "as_da": sum(a[k] * w.mda[k][h] for k in w.offered),
                 "degradation": st.c_deg * (r["dis"] + r["up_mwh"]),
                 "deployment_energy": (r["up_mwh"] - r["dn_mwh"]) * w.rt[h]}
            snap = self.snap[h] or {"short": {}, "governed": False}
            charged = {k: min(v, snap["short"].get(k, 0.0)) for k, v in r["short"].items()}
            excused = {k: v - charged[k] for k, v in r["short"].items() if v - charged[k] > TOL}
            ftp = sum(v * ftp_price[k] for k, v in charged.items())
            exc = sum(v * ftp_price[k] for k, v in excused.items())
            for k in ("energy_da", "energy_rt", "as_da", "degradation", "deployment_energy"):
                self.cash[k] += c[k]
            self.cash["ftp"] += ftp
            self.cash["excused"] += exc
            for k, v in excused.items():
                self.excused.append({"hour": h, "product": k, "mw": v, "usd": v * ftp_price[k]})
            if r["governed"]:
                self.governor.append({"hour": h, "committed": e, "executed": _r6(r["b"]),
                                      "excused": not snap["governed"]})
            out.append({"h": h, "time": self.clock(60 * h), "rt_usd": _r2(w.rt[h]), "pv_mw": _r2(r["pv"]),
                        "x_da_mw": _r2(xda), "export_mw": _r2(r["x"]), "curtailed_mw": _r2(r["curtailed"]),
                        "b_mw": _r2(r["b"]), "soc_mwh": _r2(r["S"]),
                        "reg_up_frac": _r2(w.reg_up[h]) if a["regup"] else 0.0,
                        "reg_dn_frac": _r2(w.reg_dn[h]) if a["regdn"] else 0.0,
                        "deployed_up_mwh": _r2(r["up_mwh"]), "deployed_dn_mwh": _r2(r["dn_mwh"]),
                        "governor": r["governed"], "ftp_mw": _r2(sum(charged.values())),
                        "excused_mw": _r2(sum(excused.values()))})
            self.rows.append(r | {"h": h, "e": e, "a": a, "x_da": xda, "cash": c, "ftp": ftp, "excused_usd": exc,
                                  "charged": charged, "excused_mw": excused})
            self.S, self.cyc = r["S"], self.cyc + r["dis"]
            self.soc_hist.append(self.S)
        return out

    def _finish(self, reason: str):
        self.end_short = max(0.0, self.site.s_end - self.S)
        self.end_short_charged = min(self.end_short, self.end_snap or 0.0)
        self.cash["end_penalty"] = self.end_short_charged * self.win.pen
        self.cash["excused"] += (self.end_short - self.end_short_charged) * self.win.pen
        self.done, self.end_reason = True, reason
        for dm in self.dam:
            if not dm["final"]:
                dm["final"], dm["missed"] = True, not dm["accepted"]

    def _done_result(self) -> dict:
        if self.reference:
            return {"profit_usd": _r2(self.profit())}
        g = self.grade()
        return {"profit_usd": _r2(g["profit_usd"]), "reward": g["reward"], "r_hind": g["r_hind"]}

    def end_window(self) -> dict:
        """urn:gridsim:end-window/v1: play the unreached watches on the committed book, then grade and audit."""
        while not self.done and not self.last:
            self._close_watch()
            nxt = self.watches[self.watch + 1]
            self._settle(min(self.H, max(0, nxt.minute // 60)))
            self._open()
            for n in self.watches[self.watch].notices:
                self.notice(**self._kw(n), via="env")
        if not self.done:
            self._close_watch()
            self._settle(self.H)
            self._finish("end_window")
        g = self.grade()
        return {"end_reason": self.end_reason, "watch": self.watch, "profit_usd": _r2(g["profit_usd"]),
                "reward": g["reward"], "audit": self.audit()}

    # grading

    def references(self) -> dict:
        if self._refs is None:
            self._refs = stored_refs(self.task, self.tier, self.notices_in, self.deployments_in, self.slice,
                                     self.source) or references(self.task, (self.tier,), self.notices_in,
                                                                self.deployments_in, self.slice, self.source)
        return self._refs

    def grade(self) -> dict:
        if not self.done:
            raise ValueError("the window is not over: advance to the end or call end_window")
        if self._grade is None:
            r = self.references()
            tr = r[self.tier]
            p, p_idle, p_anchor = self.profit(), tr["p_idle"], tr["p_anchor"]
            submitted = any(c["committed"] for c in self.commits) or any(x["accepted"] for x in self.dam_log)
            den = p_anchor - p_idle
            p_hind = tr.get("p_hind")
            hd = None if p_hind is None else p_hind - p_idle
            self._grade = {
                "submitted": submitted, "tier": self.tier, "source": self.source,
                "reward": reward_value(p, p_idle, p_anchor) if submitted else 0.0,
                "raw_ratio": _r6((p - p_idle) / den) if den > DEGENERATE_EPS else None, "profit_usd": _r6(p),
                "cash": self.cash_out(), "p_idle": p_idle, "p_anchor": p_anchor, "p_roll": tr.get("p_roll"),
                "p_roll3": tr.get("p_roll3"), "p_blind": tr.get("p_blind"), "p_naive": tr.get("p_naive"),
                "p_hind": p_hind, "p_lp": tr.get("p_lp"),
                "r_hind": reward_value(p, p_idle, p_hind) if submitted and p_hind is not None else (
                    0.0 if p_hind is not None else None),
                "paired_vs_anchor": _r6((p - p_anchor) / hd) if hd is not None and hd > DEGENERATE_EPS else None,
                "beats_anchor": _r6(p) > p_anchor + 1e-6,
                "r_roll3": reward_value(p, p_idle, tr["p_roll3"]) if submitted and tr.get("p_roll3") is not None
                else None,
                "forecast_value": reward_value(p, p_idle, tr["p_roll"]) if submitted and self.tier == "blind"
                and tr.get("p_roll") is not None else None,
                "dam_missed": sum(dm["missed"] for dm in self.dam),
                "ftp_mwh_charged": _r6(sum(sum(x["charged"].values()) for x in self.rows)),
                "ftp_mwh_excused": _r6(sum(sum(x["excused_mw"].values()) for x in self.rows)),
                "end_short_mwh": _r6(self.end_short), "governor_hours": len(self.governor),
                "refusals": sum(len(x["refused"]) for x in self.refusals),
                "commits": sum(bool(x["committed"]) for x in self.commits),
                "dam_submits": len(self.dam_log), "forecast_calls": sum(self.forecast_calls),
                "baselines": tr.get("baselines")}
        return self._grade

    def audit(self, get_time_reads=None) -> dict:
        problems = self._audit_watches(get_time_reads)
        index = {(v["kind"], v["key"], v["issued_at"]): v for v in self.slice.get("series") or []}
        for f in self.forecast_log:
            v = index.get((f["kind"], f["key"], f["issued_at"]))
            if v is None:
                problems.append(f"call {f['call']} served a {f['kind']} vintage not in the index")
            elif FI.vintage_sha(v["fields"]) != f["sha"] or v["sha"] != f["sha"]:
                problems.append(f"call {f['call']}: {f['kind']} {f['key']} {f['issued_at']} does not match its sha")
            if f["reveal_minute"] > f["minute"]:
                problems.append(f"call {f['call']} served a {f['kind']} vintage issued after now")
        for d in self.da_log:
            if d["minute"] < results_minute(d["day"]):
                problems.append(f"call {d['call']} showed day {d['day']}'s DA prices before their results")
        for d in self.dam_log:
            if d["accepted"] and d["minute"] != gate_minute(d["day"]):
                problems.append(f"day {d['day']}'s DAM entry was accepted outside its gate")
        if self.transcript:
            problems += replay(self.task, self.tier, self.notices_in, self.deployments_in, self.slice, self.transcript,
                               self.source, reference=self.reference)["problems"]
        return {"ok": not problems, "problems": problems}

    def data(self) -> dict:
        return {"task_id": self.task["task_id"], "tier": self.tier, "source": self.source,
                "watches": len(self.watches), "watch": self.watch, "time": self.clock(self.minute), "done": self.done,
                "end_reason": self.end_reason, "calls_used": self.calls, "planning_calls": self.planning_calls,
                "forecast_calls": self.forecast_calls, "dam": self._dam_out(),
                "book": {f: [_num(x) for x in self.book[f]] for f in ("energy",) + self.win.offered},
                "executed": [_r6(r["b"]) for r in self.rows], "status": self.status(), "notices": self.log,
                "forecast_log": self.forecast_log, "frozen": self.frozen, "refusals": self.refusals,
                "governor": self.governor,
                "excused": {"rows": [{k: (_r2(v) if isinstance(v, float) else v) for k, v in r.items()}
                                     for r in self.excused], "usd": _r6(self.cash["excused"]),
                            "end_short_mwh": _r6(self.end_short - self.end_short_charged)},
                "settled": self.settled, "audit": self.audit() if self.done else None,
                "grade": self.grade() if self.done else None, "reward": self.grade()["reward"] if self.done else None}

    def _dam_out(self) -> list[dict]:
        out = []
        for k, dm in enumerate(self.dam):
            hrs = range(24 * k, 24 * k + 24)
            out.append({"day": dm["day"], "gate_watch": dm["gate_watch"], "submits": dm["submits"],
                        "accepted": dm["accepted"], "x_da_mw": [_r6(self.xda[h] or 0.0) for h in hrs],
                        "pv_da_mw": [_r6(self.pv_da[h]) for h in hrs],
                        "awards": {p: [_num(self.book[p][h]) if dm["accepted"] else 0 for h in hrs]
                                   for p in self.win.offered},
                        "pv_da_share": dm["share"], "missed": dm["missed"]})
        return out

    def episode(self, *, bundle: str = "train", path: str = "B'", model: str | None = None, trained: str | None = None,
                checkpoint_step: int | None = None, seed: int | None = None, messages: list | None = None,
                usage: dict | None = None, wall_seconds: float | None = None, episode_id: str | None = None) -> dict:
        """The gridsim.episode/v4 record of a finished window."""
        if not self.done:
            self.end_window()
        g, r, t, w = self.grade(), self.references(), self.task, self.win
        eid = episode_id or hashlib.sha256(_dump([t["task_id"], self.tier, self.source, bundle, path, model, trained,
                                                   checkpoint_step, seed, [s["output"] for s in self.transcript]]
                                                  ).encode()).hexdigest()[:16]
        when = {e["event_id"]: e["watch"] for e in self.log if e["first"]}
        steps, watch = [], 0
        for i, s in enumerate(self.transcript):
            out = json.loads(s["output"])
            steps.append({"t": i, "watch": watch, "tool": s["tool"], "args": s["args"], "output": out})
            if s["tool"] == "advance" and "watch" in out:
                watch = out["watch"]
        b0 = {k: self._gate_pv(k) for k in range(self.n)}
        hours = [{"h": x["h"], "time": self.clock(60 * x["h"]), "da": _r2(w.da[x["h"]]), "rt": _r2(w.rt[x["h"]]),
                  "pv_mw": _r6(w.pv[x["h"]]), "pv_p50_gate": b0[x["h"] // 24][x["h"] % 24],
                  "x_da_mw": _r6(x["x_da"]), "export_mw": _r6(x["x"]), "curtailed_mw": _r6(x["curtailed"]),
                  "b_mw": _r6(x["b"]), "awards": {k: _num(x["a"][k]) for k in w.offered},
                  "reg_up_frac": _r6(w.reg_up[x["h"]]), "reg_dn_frac": _r6(w.reg_dn[x["h"]]),
                  "deployed_up_mwh": _r6(x["up_mwh"]), "deployed_dn_mwh": _r6(x["dn_mwh"]),
                  "soc_mwh": _r6(self.soc_hist[x["h"] + 1]), "energy_da_usd": _r6(x["cash"]["energy_da"]),
                  "energy_rt_usd": _r6(x["cash"]["energy_rt"]), "as_da_usd": _r6(x["cash"]["as_da"]),
                  "deg_usd": _r6(x["cash"]["degradation"]), "ftp_usd": _r6(x["ftp"]),
                  "excused_usd": _r6(x["excused_usd"]), "governor": x["governed"]} for x in self.rows]
        tr = r[self.tier]
        new_v = self._watch_vintages()
        return {"schema": EPISODE_SCHEMA, "episode_id": eid, "env": FORECAST_ENV, "version": "v4",
                "task_id": t["task_id"], "tier": self.tier, "source": self.source, "bundle": bundle, "path": path,
                "model": model, "trained": trained, "checkpoint_step": checkpoint_step, "seed": seed,
                "task": {k: t.get(k) for k in ("d1", "days", "dates", "era", "settlement_point", "point_kind", "region",
                                               "zone", "weather_point", "site", "prices", "rt", "mcpc_da", "pv_mw",
                                               "actuals")},
                "watches": [{"index": wa.index, "time": wa.time, "time_utc": wa.time_utc,
                             "freeze_line": self.clock(wa.freeze_line), "kind": self.watch_kinds[wa.index],
                             "notices": [n.event_id for n in wa.notices], "new_vintages": new_v[wa.index]}
                            for wa in self.watches],
                "notices": [{"event_id": n.event_id, "source": n.source, "kind": n.kind, "level": n.level,
                             "issued_at": n.issued_at, "reveal_at": self.clock(n.reveal),
                             "watch": when.get(n.event_id), "name": n.name, "title": n.title, "text": n.text,
                             "deploy": n.deploy} for n, _ in self.scheduled.values()],
                "vintages": {"source": self.slice.get("source"), "runs": self.slice.get("runs", []),
                             "series": [v for v in self.slice.get("series", []) if v["kind"] != "mcpc" and (
                                 v["kind"] != "weather" or v["key"] == t.get("weather_point"))]},
                "forecasts_served": [{k: f[k] for k in ("call", "kind", "key", "issued_at", "sha")}
                                     | {"watch": self._watch_at(f["minute"])} for f in self.forecast_log],
                "steps": steps, "dam": self._dam_out(), "book": {"energy": [_num(x) for x in self.book["energy"]]},
                "soc_path": [_r6(x) for x in self.soc_hist], "hours": hours, "commits": self.commits,
                "cash": self.cash_out(), "profit_usd": g["profit_usd"], "reward": g["reward"],
                "raw_ratio": g["raw_ratio"], "r_hind": g["r_hind"], "paired_vs_anchor": g["paired_vs_anchor"],
                "beats_anchor": g["beats_anchor"],
                "references": {k: tr.get(k) for k in ("p_idle", "p_anchor", "p_roll", "p_roll3", "p_blind", "p_naive",
                                                      "p_hind", "p_lp", "roll", "baselines")},
                "audit": self.audit(), "messages": messages or [], "usage": usage, "wall_seconds": wall_seconds}

    def _gate_pv(self, k: int) -> list[float | None]:
        if self.tier == "front-lite":
            return [0.0] * 24
        kind = "ercot_solar" if self.source == "ercot" else "solar"
        m = gate_minute(k)
        return [None if (x := self.vint.served(kind, "site", "mw", m, 24 * k + i)) is None else _r6(x)
                for i in range(24)]

    def _watch_at(self, minute: float) -> int:
        return max(w.index for w in self.watches if w.minute <= minute) if minute >= OPEN else 0

    def _watch_vintages(self) -> list[list[str]]:
        out = []
        for i, wa in enumerate(self.watches):
            prev = self.watches[i - 1].minute if i else -math.inf
            out.append([r.v["issued_at"] for r in self.vint.all("price", self.task["settlement_point"], wa.minute)
                        if prev < r.minute <= wa.minute])
        return out


def replay(task: dict, tier: str, notices, deployments, vintages, transcript: list[dict], source=None, *,
           reference: bool = False) -> dict:
    """Re-run a recorded transcript through a fresh Session and compare every output byte for byte."""
    s, problems = Session(task, tier, notices, deployments, vintages, source=source, reference=reference), []
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


def play(task: dict, tier: str, policy, notices=None, deployments=None, vintages=None, *, source: str | None = None,
         reference: bool = True) -> Session:
    """Run a policy at every watch through call(), each watch's notices delivered after advance, to the end."""
    s = Session(task, tier, notices, deployments, vintages, source=source, reference=reference)
    while not s.done:
        policy(s)
        s.call("advance")
        s.deliver_watch_notices()
    return s


# the rolling MILP (HiGHS): one solve per watch over the open hours to the window end


def solver_of(task: dict) -> int:
    """The MILP version a row's references were built with: 1 before V4-P20 (no tie-break), else the stored one;
    a row without refs is being built now."""
    r = task.get("refs")
    return SOLVER if not r else int(r.get("solver", 1))


def solve_window(s: Session, mode: str = "p50", *, integer: bool = True, solver: int | None = None) -> dict | None:
    """The best book from the freeze line on the window as known now. Days whose gate is still open (or ahead) have
    their DA entry and AS as variables valued at the basis' DA and MCPC (x_DA = the hour's base export, V4-P5) and their
    drift at RT; days with a closed gate have their position and awards fixed and the rest valued at RT. Hard, then the
    soft model, then its LP relaxation, as v3's solve_day."""
    fo = s.first_open
    if fo >= s.H:
        return None
    st, w, b = s.site, s.win, s.basis(mode)
    S0, cyc = s.projected_state(fo)
    n = s.H - fo
    free = [not s.day_fixed((fo + t) // 24) for t in range(n)]
    prods = tuple(k for k in w.offered if k in w.qualified)
    dep = s._dep_known()
    penalty = 10 * max(100.0, float(np.abs(b["da"]).max()), b["pen"],
                       max((float(v.max()) for v in b["mcpc"].values()), default=0.0))
    for soft, integral in ((False, integer), (True, integer), (True, False)):
        m = _Model()
        aw = []
        for t in range(n):
            h = fo + t
            row = {}
            for k in PRODUCTS:
                if free[t] and k in prods:
                    row[k] = m.var(0, st.p)
                else:
                    row[k] = _Lin(k=float(s.book[k][h]) if not free[t] else 0.0)
            aw.append(row)
        price = [float(b["da"][fo + t] if free[t] else b["rt"][fo + t]) for t in range(n)]
        p = _plant(m, st, w.dur, S0, st.cap - cyc, b["pv"][fo:], price, [w.mean_up] * n, [w.mean_dn] * n, dep[fo:],
                   aw, integer=integral, soft=soft, inherited=[not f for f in free])
        short = m.var(0, math.inf)
        m.add(short + p["S"][-1], lo=st.s_end)
        obj = _Lin()
        for t in range(n):
            h = fo + t
            if free[t]:
                obj = obj + p["xb"][t] * price[t] + (p["x"][t] - p["xb"][t]) * float(b["rt"][h])
                obj = obj + sum((aw[t][k] * float(b["mcpc"][k][h]) for k in prods), _Lin())
            else:
                obj = obj + p["x"][t] * float(b["rt"][h])
            obj = obj - (p["dis"][t] + p["U"][t]) * st.c_deg
            if (solver or solver_of(s.task)) >= 2:
                w_t = TIE_EPS * (1 + t / 1000)
                obj = obj - (p["dl"][t] + p["cl"][t]) * w_t
                obj = obj - sum((aw[t][k] * (w_t * (1 + i / 100)) for i, k in enumerate(prods) if free[t]), _Lin())
        m.obj = obj - short * b["pen"] - sum(p["slack"], _Lin()) * penalty
        res = m.solve(retry_infeasible=True)
        if res is None:
            continue
        _, x = res
        book = {"energy": [_clean(_value(p["dl"][t], x) - _value(p["cl"][t], x)) for t in range(n)]}
        for k in PRODUCTS:
            book[k] = [_clean(max(0.0, _value(aw[t][k], x))) for t in range(n)]
        return {"from": fo, "book": book, "soft": soft}
    return None


def repair_commit(s: Session, fo: int, energy: list[float]) -> tuple[list[float], int]:
    """Walk an energy plan for hours fo.. through the Session's rules on its projection; a refused entry becomes the
    governor's move with the booked awards (C3-D17)."""
    st, w, dep, b = s.site, s.win, s._dep_known(), s.basis()
    S, cyc = s.projected_state(fo)
    out, n = list(energy), 0
    for i, h in enumerate(range(fo, s.H)):
        a = s.entry(h)[1]
        e = float(out[i])
        if s.rules(h, S, cyc, e, a, True):
            n += 1
            e = _clean(govern(e, *limits(st, w.dur, S, cyc, a)))
            out[i] = e
        r = step(st, w.dur, S, cyc, e, a, b["pv"][h], s._curtail_price(h, b), *s._expected(h, a, dep))
        S, cyc = r["S"], cyc + r["dis"]
    return out, n


def repair_dam(s: Session, k: int, plan: dict) -> tuple[dict, int]:
    """Walk day k's DAM plan from the projected SoC at its start; an entry the rules refuse drops its awards and takes
    the governor's move."""
    st, w, dep, b = s.site, s.win, s._dep_known(), s.basis()
    h0 = 24 * k
    S, cyc = s.projected_state(h0)
    out, n = {f: list(v) for f, v in plan.items()}, 0
    zero = dict.fromkeys(PRODUCTS, 0.0)
    for i in range(24):
        h = h0 + i
        a = {p: float(out[p][i]) if p in out else 0.0 for p in PRODUCTS}
        e = float(out["energy"][i])
        if s.rules(h, S, cyc, e, a, False):
            n += 1
            a = zero
            e = _clean(govern(e, *limits(st, w.dur, S, cyc, a)))
            out["energy"][i] = e
            for p in out:
                if p != "energy":
                    out[p][i] = 0
        r = step(st, w.dur, S, cyc, e, a, b["pv"][h], b["da"][h], *s._expected(h, a, dep))
        S, cyc = r["S"], cyc + r["dis"]
    return out, n


def stored_calls(s: Session, mode: str) -> dict[int, list[dict]] | None:
    """The tier anchor's calls stored in the row (V4-P20), by watch, when the row's refs hold for this Session's
    events, vintages and source and the mode is the tier's anchor; else None (re-solve)."""
    if not hasattr(s, "_stored_calls"):
        r = stored_refs(s.task, s.tier, s.notices_in, s.deployments_in, s.slice, s.source) if s.task.get("refs") else None
        calls = (r or {}).get(s.tier, {}).get("anchor_calls") if r else None
        s._stored_calls = None
        if calls is not None:
            s._stored_calls = {}
            for c in calls:
                s._stored_calls.setdefault(c["watch"], []).append(c)
    return s._stored_calls if mode == ANCHOR_MODE[s.tier] else None


def anchor_calls(s: Session) -> list[dict]:
    """A played Session's agent decisions (commits and DAM submits) with the watch they were made at."""
    out, watch = [], 0
    for st in s.transcript:
        if st["tool"] in ("commit_schedule", "submit_dam"):
            out.append({"watch": watch, "tool": st["tool"], "args": st["args"]})
        elif st["tool"] == "advance":
            watch = json.loads(st["output"]).get("watch", watch)
    return out


def anchor_policy(mode: str = "p50", *, replay: bool = True, solver: int | None = None):
    """The information-matched rolling re-planner: at each watch one solve; commit its open hours (when it changes
    the book, and always at a gate), then at a gate submit its plan for the gated day (share 1.0). On a row that
    stores the tier anchor's calls (V4-P20) it replays them instead, so the anchor is the same on every platform."""

    def policy(s: Session):
        if s.done or s.first_open >= s.H:
            return
        if replay and (calls := stored_calls(s, mode)) is not None:
            for c in calls.get(s.watch, ()):
                s.call(c["tool"], c["args"])
            return
        sol = solve_window(s, mode, solver=solver)
        if sol is None:
            return
        fo, k = sol["from"], s.gate_day()
        energy, n1 = repair_commit(s, fo, sol["book"]["energy"])
        if s.calls_left and (s.watch == 0 or k is not None or any(
                abs(a - b) > EQ_TOL for a, b in zip(energy, s.book["energy"][fo:], strict=True))):
            s.call("commit_schedule", {"plan": {"energy": energy}, "from_hour": fo})
        n2 = 0
        if k is not None and s.submits_left:
            i0 = 24 * k - fo
            plan = {"energy": sol["book"]["energy"][i0:i0 + 24]}
            plan |= {p: sol["book"][p][i0:i0 + 24] for p in s.win.offered}
            plan, n2 = repair_dam(s, k, plan)
            s.call("submit_dam", {"operating_day": s.day_date(k), "plan": plan, "pv_da_share": 1.0})
        s.anchor_log.append({"watch": s.watch, "soft": sol["soft"], "repaired": n1 + n2})

    return policy


def idle_policy(s: Session):
    return None


def naive_policy(s: Session):
    """At each gate: charge P in the day's 4 cheapest and discharge P in its 4 dearest DA P50 hours (governed, no AS);
    never re-planned."""
    k = s.gate_day()
    if k is None or not s.submits_left:
        return
    da = s.basis()["da"][24 * k:24 * k + 24]
    order = sorted(range(24), key=lambda i: (da[i], i))
    e = [0.0] * 24
    for i in order[:4]:
        e[i] = -s.site.p
    for i in order[-4:]:
        e[i] = s.site.p
    plan, _ = repair_dam(s, k, {"energy": e})
    s.call("submit_dam", {"operating_day": s.day_date(k), "plan": plan, "pv_da_share": 1.0})


def hindsight(task: dict, tier: str, notices=None, deployments=None, *, integer: bool = True) -> float | None:
    """P_hind: v3's hindsight (C3-D13) over the window, a DA copy on DA prices (expected drift, free curtailment) and a
    physical copy on realized RT, PV, drift and deployments, sharing the AS book. integer=False gives the LP bound."""
    st, w = site_for(task, tier), window_of(task, tier)
    events = events_of(task, notices, deployments)
    dep = deploy_hours([n.deploy for n in (parse_notice(x, task["d1"], 60) for x in events) if n.deploy], w.dur, w.hours)
    zero = [dict.fromkeys(EVENT_PRODUCTS, 0.0) for _ in range(w.hours)]
    m = _Model()
    prods = tuple(k for k in w.offered if k in w.qualified)
    a = _awards(m, w.hours, 0, prods, None, st.p)
    cp = _plant(m, st, w.dur, st.s0, st.cap, w.pv, w.da, [w.mean_up] * w.hours, [w.mean_dn] * w.hours, zero, a,
                integer=integer, free_curtail=True)
    ph = _plant(m, st, w.dur, st.s0, st.cap, w.pv, w.rt, w.reg_up, w.reg_dn, dep, a, integer=integer)
    short = m.var(0, math.inf)
    m.add(short + ph["S"][-1], lo=st.s_end)
    obj = _Lin()
    for h in range(w.hours):
        obj = obj + cp["xb"][h] * float(w.da[h] - w.rt[h]) + ph["x"][h] * float(w.rt[h])
        obj = obj - (ph["dis"][h] + ph["U"][h]) * st.c_deg
        obj = obj + sum((a[h][k] * float(w.mda[k][h]) for k in prods), _Lin())
    m.obj = obj - short * w.pen
    res = m.solve(retry_infeasible=True)
    if res is None and integer:
        return hindsight(task, tier, notices, deployments, integer=False)
    return None if res is None else res[0]


def _anchor_row(s: Session) -> dict:
    return {"dam": [{"day": d["day"], "accepted": len(d["accepted"]), "missed": d["missed"]} for d in s.dam],
            "commits": sum(bool(c["committed"]) for c in s.commits), "watches": len(s.watches),
            "governor_hours": len(s.governor), "ftp_usd": _r6(s.cash["ftp"]), "as_usd": _r6(s.cash["as_da"]),
            "soft_solves": sum(x["soft"] for x in s.anchor_log),
            "repaired_entries": sum(x["repaired"] for x in s.anchor_log)}


def references(task: dict, tiers=TIERS, notices=None, deployments=None, vintages=None, source: str | None = None,
               lp: bool = True) -> dict:
    """The refs block per tier: idle, the anchor (P_roll; blind: P_blind), P_roll3, P_blind, P_naive, hindsight and
    its LP bound."""
    sl = vintages if vintages is not None else FI.slice_for(task)
    src = source or task.get("source") or sl.get("source") or "desk"
    kw = {"notices": notices, "deployments": deployments, "vintages": sl, "source": src}
    solver = solver_of(task)
    out = {"forecast_version": FORECAST_VERSION, "source": src, "solver": solver,
           "events_sha": events_sha(task, notices, deployments), "vintages_sha": FI.vintages_sha(sl.get("series") or [])}
    cache: dict = {}

    def run(tier, policy, name):
        if (tier, name) not in cache:
            cache[(tier, name)] = play(task, tier, policy, **kw)
        return cache[(tier, name)]

    for tier in tiers:
        try:
            Session(task, tier, notices, deployments, sl, source=src, reference=True)
        except ValueError:
            out[tier] = None
            continue
        plant = "front-lite" if tier == "front-lite" else "front"
        p_idle = run(tier, idle_policy, "idle").profit()
        roll = run(plant if tier == "blind" else tier, anchor_policy("p50", replay=False, solver=solver), "roll")
        p_roll = roll.profit()
        p_blind = run("blind" if plant == "front" else tier, anchor_policy("persist", replay=False, solver=solver),
                      "blind").profit()
        p_roll3 = run(plant if tier == "blind" else tier, anchor_policy("mean3", replay=False, solver=solver),
                      "roll3").profit()
        p_naive = run(tier, naive_policy, "naive").profit()
        p_anchor = p_blind if tier == "blind" else p_roll
        anc = cache[("blind", "blind")] if tier == "blind" else roll
        hind = hindsight(task, tier, notices, deployments)

        def entry(p, p_idle=p_idle, p_anchor=p_anchor):
            return {"profit": _r6(p), "reward": reward_value(p, p_idle, p_anchor)}

        out[tier] = {"p_idle": _r6(p_idle), "p_anchor": _r6(p_anchor), "p_roll": _r6(p_roll), "p_roll3": _r6(p_roll3),
                     "p_blind": _r6(p_blind), "p_naive": _r6(p_naive), "anchor": _anchor_row(anc),
                     "anchor_calls": anchor_calls(anc),
                     "roll": _anchor_row(roll),
                     "p_hind": None if hind is None else _r6(hind),
                     "p_lp": _r6(hindsight(task, tier, notices, deployments, integer=False)) if lp else None,
                     "baselines": {"naive": entry(p_naive), "blind": entry(p_blind), "roll": entry(p_roll),
                                   "roll3": entry(p_roll3)}}
    return out


def stored_refs(task: dict, tier: str, notices=None, deployments=None, vintages=None, source=None) -> dict | None:
    """The row's refs when they were computed on the same events, vintages and source."""
    r = task.get("refs")
    sl = vintages if vintages is not None else FI.slice_for(task)
    src = source or task.get("source") or sl.get("source") or "desk"
    if not r or not r.get(tier) or r.get("source") != src:
        return None
    if r.get("events_sha") != events_sha(task, notices, deployments):
        return None
    if r.get("vintages_sha") != FI.vintages_sha(sl.get("series") or []):
        return None
    return r


# the task row


def task_id(d1: str, point: str, site_id: str) -> str:
    return f"front-v4-{d1}-{point}-{site_id}"


def make_task(d1: str, point: str, site: dict, prices, rt, pv_cf, mcpc_da: dict, *, era: str | None = None,
              history: dict | None = None, actuals: dict | None = None, notices=(), deployments=(),
              solar_installed_mw: float | None = None, days: int = 3, **extra) -> dict:
    """A window row without vintages or refs (the pack builder attaches the slice, then the refs)."""
    hrs = 24 * days
    tid = task_id(d1, point, site["site_id"])
    reg = hybrid_inputs.reg_drift(tid, n_hours=hrs)
    era = era or as_era(d1)
    return {"task_id": tid, "forecast_version": FORECAST_VERSION, "contract_version": "1.0", "d1": d1, "days": days,
            "dates": [(dt.date.fromisoformat(d1) + dt.timedelta(days=k)).isoformat() for k in range(days)],
            "open": f"{(dt.date.fromisoformat(d1) - dt.timedelta(days=1)).isoformat()} 10:00", "era": era,
            "settlement_point": point, "point_kind": point_kind(point), "region": REGIONS.get(point, "central"),
            "zone": FI.points()[FI.site_point(point)]["zone"], "weather_point": FI.site_point(point), "site": site,
            "prices": [float(p) for p in prices[:hrs]], "rt": [float(p) for p in rt[:hrs]],
            "mcpc_da": {k: [float(x) for x in v[:hrs]] for k, v in mcpc_da.items()},
            "pv_cf": [round(float(c), 5) for c in pv_cf[:hrs]], "pv_mw": HY.pv_at_bus(site, pv_cf[:hrs]),
            "solar_installed_mw": solar_installed_mw, "history": history or {}, "actuals": actuals,
            "reg": {"up": reg["reg_up_frac"], "dn": reg["reg_dn_frac"],
                    "mean_up": hybrid_inputs.DRIFT_SPEC["regup"]["mean"],
                    "mean_dn": hybrid_inputs.DRIFT_SPEC["regdn"]["mean"], "source": reg["source"],
                    "label": hybrid_inputs.DRIFT_SPEC["label"]},
            "notices": list(notices), "deployments": list(deployments),
            "flags": {"forecasts": "desk (modelled from NOAA HRRR as issued)", "load_official": "EIA-930 DF",
                      "price_guide": "modelled", "pv_availability": "proxy", "reg_drift": "seeded",
                      "rt_as": "not_modelled" if era == "C" else "n/a", "site": site.get("source", "archetype")},
            **extra}


def attach(task: dict, sl: dict, *, tiers=TIERS, lp: bool = True) -> dict:
    """The row with its inline slice, source, shas and refs."""
    t = {k: v for k, v in task.items() if k != "refs"}
    t["vintages"] = sl
    t["source"] = t.get("source") or ("desk" if sl.get("source") == "synthetic" else sl.get("source", "desk"))
    t["vintages_sha"] = FI.vintages_sha(sl.get("series") or [])
    t["events_sha"] = events_sha(t)
    t["refs"] = references(t, tiers, vintages=sl, source=t["source"], lp=lp)
    return t

