"""GridSimEnv v2 "The Live Grid": one battery-day played in watches on the virtual clock, settled ERCOT two-settlement.

Session is the only v2 state machine: the gridsim-live env wraps it and path B' training imports it. Times are minutes
from D 00:00 CPT (watch 0 is -600, D 24:00 is 1440); the live grid is v1's hourly battery on 15-minute intervals."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

import numpy as np

from gridsim_core.baselines import ridge_predict
from gridsim_core.contract import DEGENERATE_EPS, ceil_to_interval
from gridsim_core.dp import TIE_TOL, dp_schedule
from gridsim_core.grade import reward_value, stretch_value
from gridsim_core.parse import ParseError, parse_actions
from gridsim_core.physics import cash, penalty_per_unit
from gridsim_core.task import Battery, battery_of, data_root

LIVE_VERSION = "2.0"
LIVE_ENV = "gridsim-live"
LIVE_LOAD_URI = "urn:gridsim:live-load/v1"
END_DAY_URI = "urn:gridsim:end-day/v1"
CLOCK_URI = "urn:agentenv:clock/v1"
EPISODE_SCHEMA = "gridsim.episode/v2"
TIERS = ("foresight", "blind", "short", "freeze6h")
TOOLS = ("get_situation", "commit_da", "check_schedule", "commit_schedule", "advance")
PLANNING_TOOLS = ("commit_da", "check_schedule", "commit_schedule")
NOTICE_TOOL = "grid_notice"
PLANNING_CALLS = 3
TURNS_PER_WATCH = 5
MAX_WATCHES = 10
MAX_TURNS = TURNS_PER_WATCH * MAX_WATCHES + 2
"""Every day gets the turns of the longest day, so the turns-left note doesn't reveal how many notices are coming."""
BARRIER_SECONDS = 60
W0, DAY_END, INTERVALS, HOURS = -600, 1440, 96, 24
REGULAR = {"foresight": (-600, 0, 360, 720, 1080), "blind": (-600, 0, 360, 720, 1080), "short": (-600, 0, 720),
           "freeze6h": (-600, 0, 360, 720, 1080)}
FREEZE_MIN = {"foresight": 60, "blind": 60, "short": 60, "freeze6h": 360}
SHORT_MAX_WATCHES = 4
BASIS_INTERVALS, BASIS_HALF_LIFE_MIN = 4, 120.0
NOTICE_CHARS = 600
TZ = ZoneInfo("America/Chicago")
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _r2(x: float) -> float:
    return round(float(x), 2) + 0.0


def _r6(x: float) -> float:
    return round(float(x), 6) + 0.0


def expand(hourly) -> list[int]:
    """An hourly list read as the same action in each of the hour's four intervals."""
    return [int(a) for a in hourly for _ in range(4)]


def freeze_line(minute: int, tier: str = "foresight") -> int:
    """ceil_to_hour(now) + 1 h (6 h in freeze6h), in minutes from D 00:00."""
    return int(ceil_to_interval(minute, 60)) + FREEZE_MIN.get(tier, 60)


def first_open(minute: int, tier: str = "foresight") -> int:
    return min(INTERVALS, max(0, freeze_line(minute, tier) // 15))


def live_grid(task: dict) -> Battery:
    """The live 15-minute grid of the task's hourly battery: unit q/4, rates per interval, levels and caps x4."""
    b = battery_of(task)
    return Battery(b.q / 4, b.k_dis, b.k_ch, 4 * b.n, b.eta, b.c_deg, 4 * b.cap, 4 * b.s0, 4 * b.s_end_min)


def grid_dict(task: dict) -> dict:
    b, g = task["battery"], live_grid(task)
    return {"p_dis_mw": b["p_dis_mw"], "p_ch_mw": b["p_ch_mw"], "energy_mwh": b["energy_mwh"], "unit_mwh": g.q,
            "k_dis": g.k_dis, "k_ch": g.k_ch, "soc_levels": g.n, "eta": g.eta, "c_deg": g.c_deg,
            "cycle_cap_units": g.cap, "s0": g.s0, "s_end_min": g.s_end_min}


def _day0(date: str) -> dt.datetime:
    return dt.datetime.fromisoformat(date)


def label(minute: float, date: str) -> str:
    return (_day0(date) + dt.timedelta(minutes=minute)).strftime("%Y-%m-%d %H:%M")


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def utc(minute: float, date: str) -> str:
    local = (_day0(date) + dt.timedelta(minutes=minute)).replace(tzinfo=TZ)
    return local.astimezone(dt.UTC).strftime(TIME_FORMAT)


def to_minutes(iso: str, date: str) -> float:
    """Wall-clock minutes from D 00:00 CPT of an ISO time (offset or Z; naive means CPT)."""
    t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    if t.tzinfo is not None:
        t = t.astimezone(TZ).replace(tzinfo=None)
    return (t - _day0(date)).total_seconds() / 60


@dataclass(frozen=True)
class Notice:
    event_id: str
    source: str
    kind: str
    level: str | None
    issued_at: str
    issued: float
    reveal: int
    name: str
    title: str
    text: str
    derate_mw: float | None = None
    start: str | None = None
    until: str | None = None
    action: str | None = None
    deploy: dict | None = field(default=None, hash=False)

    @property
    def priority(self) -> int:
        """Which notice watches survive the 10-watch cap: emergencies and deployments first, cancellations last."""
        lv = str(self.level or "")
        if self.deploy is not None:
            return 0
        if self.action == "cancel":
            return 8
        if self.source == "NWS" or self.kind.startswith("nws:"):
            return {"Warning": 5, "Watch": 6}.get(lv, 7)
        if self.derate_mw is not None or lv.startswith("EEA") and lv != "EEA_exit" or lv == "Emergency":
            return 0
        return {"conservation": 1, "EEA_exit": 2, "Watch": 2, "Advisory": 3, "OCN": 4}.get(lv, 4)

    def args(self) -> dict:
        out = {"event_id": self.event_id, "name": self.name, "text": self.text, "level": self.level,
               "derate_mw": self.derate_mw, "from": self.start, "until": self.until}
        return out if self.deploy is None else out | {"deploy": self.deploy}


@dataclass(frozen=True)
class Watch:
    index: int
    minute: int
    time: str
    time_utc: str
    freeze_line: int
    notices: tuple[Notice, ...]


def parse_notice(n: dict, date: str, reveal_minutes: int = 15) -> Notice:
    issued = to_minutes(n["issued_at"], date)
    text = str(n.get("text") or "")[:NOTICE_CHARS]
    return Notice(str(n["event_id"]), str(n.get("source") or "ERCOT"), str(n.get("kind") or "other"), n.get("level"),
                  n["issued_at"], issued, int(ceil_to_interval(issued, reveal_minutes)), str(n.get("name") or n.get("source") or
                                                                                 "ERCOT"),
                  str(n.get("title") or text.split(".")[0][:120]), text,
                  None if n.get("derate_mw") is None else float(n["derate_mw"]), n.get("from"), n.get("until"),
                  n.get("action"), _deploy(n.get("deploy")))


def _deploy(d: dict | None) -> dict | None:
    """A deployment payload in its canonical shape: {product, frac, start_min, end_min}."""
    if d is None:
        return None
    return {"product": str(d["product"]), "frac": float(d["frac"]), "start_min": int(d["start_min"]),
            "end_min": int(d["end_min"])}


def notices_sha(notices) -> str:
    return hashlib.sha256(_dump(sorted(notices or [], key=lambda n: (n["issued_at"], n["event_id"]))).encode()).hexdigest()


def schedule(task: dict, tier: str = "foresight", notices=None, regular=None) -> list[Watch]:
    """The day's watches: the tier's regular watches (or `regular`, minutes) plus one per notice freeze class (contract
    L-D4); over the cap, the classes with the most urgent notices (Notice.priority, then the earliest) keep theirs."""
    date = task["date"]
    ns = sorted((parse_notice(n, date) for n in (task.get("notices") or [] if notices is None else notices)),
                key=lambda n: (n.reveal, n.issued, n.event_id))
    regular, fl = REGULAR[tier] if regular is None else tuple(regular), FREEZE_MIN.get(tier, 60)
    classes: dict[int, tuple[int, int]] = {}
    for n in ns:
        c = int(ceil_to_interval(n.reveal, 60))
        if 0 < n.reveal < DAY_END and c + fl < DAY_END and c not in regular:
            m, pr = classes.get(c, (n.reveal, n.priority))
            classes[c] = (max(m, n.reveal), min(pr, n.priority))
    kept = sorted(classes.values(), key=lambda mp: (mp[1], mp[0]))[:MAX_WATCHES - len(regular)]
    times = sorted(set(regular) | {m for m, _ in kept})
    slots: dict[int, list[Notice]] = {m: [] for m in times}
    for n in ns:
        m = next((m for m in times if m >= n.reveal), None)
        if m is not None:
            slots[m].append(n)
    return [Watch(k, m, label(m, date), utc(m, date), freeze_line(m, tier), tuple(slots[m])) for k, m in enumerate(times)]


def after_day(task: dict, tier: str = "foresight", notices=None) -> list[str]:
    """Event ids no watch delivers (revealed after the last watch)."""
    got = {n.event_id for w in schedule(task, tier, notices) for n in w.notices}
    return [n["event_id"] for n in (task.get("notices") or [] if notices is None else notices) if n["event_id"] not in got]


def triggers(watches: list[Watch]) -> list[dict]:
    """Gateway triggers (PortSim shape): after advance opens watch k, deliver its notices through grid_notice."""
    return [{"id": f"watch-{w.index}",
             "when": {"type": "action", "tool": "advance", "where": {"result.watch": {"equals": w.index}}},
             "barrier": {"at": "provoking_call", "timeout_seconds": BARRIER_SECONDS},
             "actions": [{"type": "tool", "tool": NOTICE_TOOL, "args": n.args()} for n in w.notices]}
            for w in watches[1:]]


def plan_dp(b: Battery, prices, s0: int, d0: int = 0, pen_unit: float | None = None, kd=None, kc=None) -> list[int] | None:
    """Exact best schedule over len(prices) steps from SoC s0 with d0 discharge units used, per-step rate limits; a hard
    end target when pen_unit is None (None if unreachable), else the per-unit shortfall penalty. v1's tie order. The
    discharge dimension is dropped when the cycle cap cannot bind."""
    t_n, n, cap = len(prices), b.n, b.cap - d0
    kd = [b.k_dis] * t_n if kd is None else list(kd)
    kc = [b.k_ch] * t_n if kc is None else list(kc)
    free = cap >= min(sum(kd), s0 + sum(kc))
    w = 1 if free else cap + 1
    acts = sorted(range(-b.k_ch, b.k_dis + 1), key=lambda a: (abs(a), a))
    short = np.maximum(0, b.s_end_min - np.arange(n + 1))
    v = np.repeat((np.where(short > 0, -np.inf, 0.0) if pen_unit is None else -short * pen_unit)[:, None], w, 1)
    policy = np.zeros((t_n, n + 1, w), dtype=np.int8)
    q = np.empty((len(acts), n + 1, w))
    for h in range(t_n - 1, -1, -1):
        q.fill(-np.inf)
        for i, a in enumerate(acts):
            lo, hi, da = max(0, a), min(n, n + a), 0 if free else max(a, 0)
            if -kc[h] <= a <= kd[h] and lo <= hi and da < w:
                q[i, lo:hi + 1, :w - da] = cash(b, prices[h], a)[1] + v[lo - a:hi - a + 1, da:]
        pick = np.argmax(q >= q.max(axis=0) - TIE_TOL, axis=0)
        policy[h] = pick
        v = np.take_along_axis(q, pick[None], 0)[0]
    if not np.isfinite(v[s0, 0]):
        return None
    s, d, out = s0, 0, []
    for h in range(t_n):
        a = acts[policy[h, s, d]]
        out.append(a)
        s, d = s - a, d + (0 if free else max(a, 0))
    return out


def hourly_plan(b: Battery, prices) -> list[int]:
    """v1's DP plan on hourly prices, or the hard-end plan when v1's ends short of the target."""
    plan = dp_schedule(b, prices)
    s = b.s0 - sum(plan)
    return plan if s >= b.s_end_min else plan_dp(b, prices, b.s0)


def _violation(a: int, s: int, d: int, kd: int, kc: int, g: Battery) -> str | None:
    return ("rate" if a > kd or a < -kc else "soc_below_0" if s - a < 0 else "soc_above_max" if s - a > g.n
            else "cycle_cap" if d + max(a, 0) > g.cap else None)


def _clip(a: int, s: int, d: int, kd: int, kc: int, g: Battery) -> int:
    return min(a, kd, s, g.cap - d) if a > 0 else -min(-a, kc, g.n - s) if a < 0 else 0


class WatchDay:
    """The watch machinery v2 and v3 share: tool dispatch with the exact output string, messages and the transcript;
    notice delivery and its log; the audit's watch, reveal, RT and get_time rows. A subclass sets TOOLS, RT_MINUTES and
    the state the hooks read (watches, watch, minute, done, scheduled, calls, frozen)."""

    TOOLS: tuple[str, ...] = ()
    NOTICE_ARGS: tuple[str, ...] = ("event_id", "name", "text", "level", "derate_mw", "until")
    RT_MINUTES = 15

    def _init_watch_log(self):
        self.log: list[dict] = []
        self.delivered: list[str] = []
        self.messages: list[dict] = []
        self.rt_log: list[dict] = []
        self.transcript: list[dict] = []

    def call(self, tool: str, args: dict | None = None) -> str:
        """The exact output string of a tool call; agent tools carry the messages delivered since the last call."""
        args = dict(args or {})
        if tool == NOTICE_TOOL:
            kw = {k: args.get(k) for k in self.NOTICE_ARGS}
            out = self.notice(**kw, start=args.get("from"), via=args.pop("_via", "trigger"))
        elif tool in self.TOOLS:
            self.calls += 1
            out = self._dispatch(tool, args)
            out["messages"] = self.drain()
            self._log_rt(out)
        else:
            raise ValueError(f"unknown tool {tool!r}")
        text = _dump(out)
        self.transcript.append({"tool": tool, "args": args, "output": text})
        return text

    def drain(self) -> list[dict]:
        out, self.messages = self.messages, []
        return out

    def notice(self, event_id: str, name: str, text: str, level=None, derate_mw=None, start=None, until=None,
               deploy=None, via: str = "trigger") -> dict:
        if event_id not in self.scheduled:
            raise ValueError(f"unknown event {event_id!r}")
        if self.done:
            raise ValueError("the day is over")
        n, _ = self.scheduled[event_id]
        first = event_id not in self.delivered
        self.log.append({"event_id": event_id, "watch": self.watch, "minute": self.minute, "via": via,
                         "call": self.calls, "first": first,
                         "matches": (name, text, level, derate_mw, start, until, _deploy(deploy)) == (
                             n.name, n.text, n.level, n.derate_mw, n.start, n.until, n.deploy)})
        if first:
            self.delivered.append(event_id)
            self._apply_notice(n)
            if via != "load":
                self.messages.append(self._msg(n, self.minute))
        return {"applied": event_id, "watch": self.watch}

    def _apply_notice(self, n: Notice):
        """What a notice changes in the plant when it is first delivered."""

    def _kw(self, n: Notice) -> dict:
        kw = {"event_id": n.event_id, "name": n.name, "text": n.text, "level": n.level, "derate_mw": n.derate_mw,
              "start": n.start, "until": n.until}
        return kw if n.deploy is None else kw | {"deploy": n.deploy}

    def deliver_watch_notices(self, via: str = "trigger") -> list[str]:
        """What the gateway's trigger does after advance opens a watch: grid_notice for each of its notices, in order."""
        if self.done:
            return []
        return [self.call(NOTICE_TOOL, n.args() | {"_via": via}) for n in self.watches[self.watch].notices]

    def _audit_watches(self, get_time_reads=None) -> list[str]:
        problems = []
        reached = range(len(self.watches)) if self.done else range(self.watch + 1)
        for k in reached:
            got = [e["event_id"] for e in self.log if e["watch"] == k]
            want = [n.event_id for n in self.watches[k].notices]
            if got != want:
                problems.append(f"watch {k} got {got} instead of {want}")
        for e in self.log:
            n, _ = self.scheduled[e["event_id"]]
            if e["via"] == "trigger" and e["call"] != self.frozen[e["watch"]]["call"]:
                problems.append(f"{e['event_id']} arrived after the agent's next call in watch {e['watch']}")
            if not e["matches"]:
                problems.append(f"{e['event_id']}: the delivered notice differs from the schedule")
            if e["minute"] < n.reveal:
                problems.append(f"{e['event_id']}: delivered at {hhmm(e['minute'] % DAY_END)} before its reveal time")
        for r in self.rt_log:
            if r["rt_shown"] * self.RT_MINUTES > max(0, r["minute"]):
                problems.append(f"call {r['call']} showed {r['rt_shown']} RT prices at minute {r['minute']}")
        for k, iso in get_time_reads or []:
            if _as_utc(iso) != _as_utc(self.watches[k].time_utc):
                problems.append(f"get_time read {iso} in watch {k}, not {self.watches[k].time_utc}")
        for event_id in self.scheduled:
            c = self.delivered.count(event_id)
            if c > 1 or (self.done and c != 1):
                problems.append(f"{event_id} revealed {c} times")
        return problems


class Session(WatchDay):
    """One live battery-day. Drive it through call() so outputs, messages and the transcript match path A exactly."""

    TOOLS = TOOLS

    def __init__(self, task: dict, tier: str = "foresight", notices=None, *, reference: bool = False):
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; tiers are {', '.join(TIERS)}")
        if tier == "blind" and not task.get("blind"):
            raise ValueError(f"{task.get('task_id')} has no blind inputs; it is not a blind-tier task")
        self.task, self.tier, self.date, self.reference = task, tier, task["date"], reference
        self.done, self.end_reason = False, None
        self.notices_in = list(task.get("notices") or []) if notices is None else list(notices)
        self.grid, self.hb = live_grid(task), battery_of(task)
        self.da = np.asarray(task["prices"], dtype=float)
        self.rt = np.asarray(task["rt"], dtype=float)
        self.pen_unit = penalty_per_unit(self.grid, self.da)
        self.watches = schedule(task, tier, self.notices_in)
        self.scheduled = {n.event_id: (n, w.index) for w in self.watches for n in w.notices}
        self.watch, self.calls, self.planning_calls = 0, 0, [0]
        self.da_pos: list[int] | None = None
        self.sched, self.sched_committed = [0] * INTERVALS, False
        self.executed: list[int] = []
        self.soc_hist, self.d_used = [self.grid.s0], 0
        self.kd, self.kc = [self.grid.k_dis] * INTERVALS, [self.grid.k_ch] * INTERVALS
        self.limits: list[dict] = []
        self.clips: list[dict] = []
        self.cash = {"da_usd": 0.0, "rt_usd": 0.0, "deg_usd": 0.0, "excused_usd": 0.0}
        self.rows: list[dict] = []
        self.shortfall_units, self.shortfall_usd, self.excused_short_units = 0, 0.0, 0
        self._init_watch_log()
        self.frozen = [self._frozen_row()]
        self.refusals: list[dict] = []
        self.commits: list[dict] = []
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
        return len(self.executed)

    @property
    def first_open(self) -> int:
        return INTERVALS if self.done else first_open(self.minute, self.tier)

    @property
    def soc(self) -> int:
        return self.soc_hist[-1]

    @property
    def da_visible(self) -> bool:
        return self.tier != "blind" or self.minute >= 0

    @property
    def calls_left(self) -> int:
        return PLANNING_CALLS - self.planning_calls[-1]

    def watch_time_utc(self, k: int) -> str:
        return self.watches[k].time_utc

    def display(self) -> list[int]:
        return self.executed + self.sched[self.settled:]

    def status(self) -> str:
        fo = self.first_open
        return "".join("E" if t < self.settled else "F" if t < fo else "O" for t in range(INTERVALS))

    def m_da(self, h: int) -> float:
        return 4 * cash(self.grid, 0.0, self.da_pos[h])[0] if self.da_pos else 0.0

    def da_value(self) -> float:
        return sum(self.da[h] * self.m_da(h) for h in range(HOURS))

    def profit(self) -> float:
        c = self.cash
        return float(c["da_usd"] + c["rt_usd"] - c["deg_usd"] - self.shortfall_usd + c["excused_usd"])

    def pnl(self) -> dict:
        c = self.cash
        return {"da_usd": _r2(c["da_usd"]), "rt_deviation_usd": _r2(c["rt_usd"]), "degradation_usd": _r2(c["deg_usd"]),
                "shortfall_usd": _r2(self.shortfall_usd), "excused_usd": _r2(c["excused_usd"]),
                "total_usd": _r2(self.profit())}

    def _frozen_row(self) -> dict:
        return {"watch": self.watch, "time": label(self.minute, self.date), "freeze_line": label(
            freeze_line(self.minute, self.tier), self.date), "first_open_interval": self.first_open, "call": self.calls}

    def _msg(self, n: Notice, minute: int) -> dict:
        return {"time": label(minute, self.date), "issued_at": label(n.issued, self.date), "event_id": n.event_id,
                "source": n.source, "level": n.level, "name": n.name, "title": n.title, "text": n.text}

    # the agent's tools

    def _dispatch(self, tool: str, args: dict) -> dict:
        want = {"get_situation": (), "advance": (), "commit_da": ("position",),
                "check_schedule": ("actions", "start", "step"), "commit_schedule": ("actions", "start", "step")}[tool]
        extra = sorted(set(args) - set(want))
        missing = [k for k in want if k != "step" and k not in args]
        if extra or missing:
            bad = f"unexpected argument {extra[0]!r}" if extra else f"missing argument {missing[0]!r}"
            if tool in PLANNING_TOOLS and not self.done and self.calls_left:
                self.planning_calls[-1] += 1
            return {"error": f"{tool}: {bad}", "planning_calls_left": self.calls_left}
        return getattr(self, tool)(**args)

    def _log_rt(self, out: dict):
        n = len(out.get("rt_prices_usd_per_mwh") or [])
        if out.get("settled"):
            n = max(n, max(r["interval"] for r in out["settled"]) + 1)
        self.rt_log.append({"call": self.calls, "minute": self.minute, "rt_shown": n})

    def situation(self) -> dict:
        t = self.task
        out = {"task_id": t["task_id"], "tier": self.tier, "date": self.date, "settlement_point": t["settlement_point"],
               "point_kind": t.get("point_kind"), "market": "ERCOT two-settlement: DAM + 15-minute real time",
               "watch": self.watch, "time": label(self.minute, self.date),
               "freeze_line": label(freeze_line(self.minute, self.tier), self.date) if not self.done else None,
               "first_open_interval": self.first_open, "planning_calls_left": 0 if self.done else self.calls_left,
               "day_over": self.done, "battery": grid_dict(t), "limits": self.limits, "soc_units": self.soc,
               "discharge_units_used": self.d_used, "cycle_units_left": self.grid.cap - self.d_used,
               "da_prices_usd_per_mwh": [_r2(p) for p in self.da] if self.da_visible else None}
        if self.tier == "blind":
            out["dam_prev_day_usd_per_mwh"] = [_r2(p) for p in t["blind"]["dam_prev_day"]]
            out["dam_prev_7d_usd_per_mwh"] = [[_r2(p) for p in d] for d in t["blind"]["dam_prev_7d"]]
        proj = self._project(self.display())
        out |= {"da_position": self.da_pos,
                "da_value_usd": _r2(self.da_value()) if self.da_pos and self.da_visible else None,
                "rt_prices_usd_per_mwh": [_r2(p) for p in self.rt[:self.settled]], "schedule": self.display(),
                "schedule_status": self.status(), "projected_end_soc_units": proj["soc_path"][-1], "pnl": self.pnl(),
                "notices": [self._msg(self.scheduled[e["event_id"]][0], e["minute"]) for e in self.log
                            if e["first"]]}
        if self.done:
            out["result"] = self._done_result()
        return out

    def get_situation(self) -> dict:
        return self.situation()

    def _planning(self) -> dict | None:
        if self.done:
            return {"error": "the day is over", "planning_calls_left": 0}
        if not self.calls_left:
            return {"error": f"no planning calls left in this watch ({PLANNING_CALLS} used): call advance",
                    "planning_calls_left": 0}
        self.planning_calls[-1] += 1
        return None

    def commit_da(self, position) -> dict:
        if err := self._planning():
            return err
        if self.watch != 0:
            return self._refuse("commit_da", [{"hour": None, "reason": "closed: the DA position is committed at "
                                                                           "watch 0 only"}])
        if self.da_pos is not None:
            return self._refuse("commit_da", [{"hour": None, "reason": "already committed"}])
        try:
            pos = parse_actions(position, HOURS)
        except ParseError as e:
            return self._refuse("commit_da", [{"hour": None, "reason": f"parse: {e}"}])
        g, s, d = self.grid, self.grid.s0, 0
        for t, a in enumerate(expand(pos)):
            if why := _violation(a, s, d, g.k_dis, g.k_ch, g):
                return self._refuse("commit_da", [{"hour": f"HE{t // 4 + 1:02d}", "reason": why}])
            s, d = s - a, d + max(a, 0)
        if s < g.s_end_min:
            return self._refuse("commit_da", [{"hour": "HE24", "reason": "end_target"}])
        self.da_pos = pos
        follows = not self.sched_committed
        if follows:
            self.sched = expand(pos)
        self.commits.append({"watch": self.watch, "tool": "commit_da", "start": None, "step": "1h", "accepted": True,
                             "call": self.calls})
        return {"accepted": True, "refusals": [], "da_value_usd": _r2(self.da_value()) if self.da_visible else None,
                "schedule_follows_da": follows, "planning_calls_left": self.calls_left}

    def _refuse(self, tool: str, refusals: list[dict], **extra) -> dict:
        self.refusals.append({"watch": self.watch, "call": self.calls, "tool": tool, "refusals": refusals})
        self.commits.append({"watch": self.watch, "tool": tool, "start": extra.pop("start", None),
                             "step": extra.pop("step", None), "accepted": False, "call": self.calls})
        return {"accepted": False, "refusals": refusals, **extra, "planning_calls_left": self.calls_left}

    def _candidate(self, actions, start, step) -> tuple[list[int] | None, int | None, str | None]:
        """(the candidate 96-interval day, start interval, parse error)."""
        if step not in ("15m", "1h"):
            return None, None, f'step must be "15m" or "1h", got {step!r}'
        m = _HHMM.match(str(start).strip()) if isinstance(start, str) else None
        if not m or int(m.group(2)) >= 60:
            return None, None, f'start must be "HH:MM" on the operating day, got {start!r}'
        minute = int(m.group(1)) * 60 + int(m.group(2))
        size = 60 if step == "1h" else 15
        if minute >= DAY_END or minute % size:
            return None, None, f"start {start} is not a {step} boundary before 24:00"
        n = (DAY_END - minute) // size
        try:
            acts = parse_actions(actions, n)
        except ParseError as e:
            return None, None, f"{e} (from {start} to 24:00 at {step})"
        t0 = minute // 15
        return self.display()[:t0] + (expand(acts) if step == "1h" else acts), t0, None

    def _assess(self, cand: list[int]) -> tuple[list[dict], dict]:
        """Refusals (frozen changes, the first open-interval physics failure, end target) and the projection."""
        fo, cur, g = self.first_open, self.display(), self.grid
        refusals = [{"interval": t, "time": hhmm(15 * t), "reason": "frozen"} for t in range(fo) if cand[t] != cur[t]]
        s, d = self.soc, self.d_used
        for t in range(self.settled, fo):
            a = _clip(cur[t], s, d, self.kd[t], self.kc[t], g)
            s, d = s - a, d + max(a, 0)
        physics = None
        for t in range(fo, INTERVALS):
            if why := _violation(cand[t], s, d, self.kd[t], self.kc[t], g):
                physics = {"interval": t, "time": hhmm(15 * t), "reason": why}
                break
            s, d = s - cand[t], d + max(cand[t], 0)
        if physics:
            refusals.append(physics)
        elif s < g.s_end_min:
            refusals.append({"interval": INTERVALS - 1, "time": hhmm(15 * (INTERVALS - 1)), "reason": "end_target"})
        merged = cur[:fo] + cand[fo:]
        return refusals, self._project(merged)

    def _project(self, plan: list[int]) -> dict:
        """SoC path (executed history, then the plan with v1 truncation) and the day's P&L with unsettled intervals at
        DA prices (None while DA prices are hidden)."""
        g, fo = self.grid, self.first_open
        s, d, soc = self.soc, self.d_used, list(self.soc_hist)
        cut = False
        val = self.cash["da_usd"] + self.cash["rt_usd"] - self.cash["deg_usd"] + self.cash["excused_usd"]
        for t in range(self.settled, INTERVALS):
            a = plan[t]
            if t < fo:
                a = _clip(a, s, d, self.kd[t], self.kc[t], g)
            elif cut or _violation(a, s, d, self.kd[t], self.kc[t], g):
                cut, a = True, 0
            mwh, _, deg = cash(g, 0.0, a)
            h = t // 4
            val += self.da[h] * self.m_da(h) / 4 + self.da[h] * (mwh - self.m_da(h) / 4) - deg
            s, d = s - a, d + max(a, 0)
            soc.append(s)
        val -= max(0, g.s_end_min - s) * self.pen_unit
        return {"soc_path": soc, "end_soc_units": s, "discharge_units": d,
                "pnl_at_da_prices_usd": _r2(val) if self.da_visible else None}

    def check_schedule(self, actions, start, step: str = "15m") -> dict:
        if err := self._planning():
            return err
        cand, _, perr = self._candidate(actions, start, step)
        if perr:
            return {"feasible": False, "refusals": [{"interval": None, "time": None, "reason": f"parse: {perr}"}],
                    "projected": None, "excused_usd": _r2(self.cash["excused_usd"]),
                    "planning_calls_left": self.calls_left}
        refusals, proj = self._assess(cand)
        return {"feasible": not refusals, "refusals": refusals, "projected": proj,
                "excused_usd": _r2(self.cash["excused_usd"]), "planning_calls_left": self.calls_left}

    def commit_schedule(self, actions, start, step: str = "15m") -> dict:
        if err := self._planning():
            return err
        cand, _, perr = self._candidate(actions, start, step)
        if perr:
            return self._refuse("commit_schedule", [{"interval": None, "time": None, "reason": f"parse: {perr}"}],
                                start=start, step=step, schedule_status=self._status_row())
        refusals, _ = self._assess(cand)
        if refusals:
            return self._refuse("commit_schedule", refusals, start=start, step=step, schedule_status=self._status_row())
        fo = self.first_open
        self.sched = self.sched[:fo] + cand[fo:]
        self.sched_committed = True
        self.commits.append({"watch": self.watch, "tool": "commit_schedule", "start": start, "step": step,
                             "accepted": True, "call": self.calls})
        return {"accepted": True, "refusals": [], "schedule_status": self._status_row(),
                "planning_calls_left": self.calls_left}

    def _status_row(self) -> dict:
        st, proj = self.status(), self._project(self.display())
        return {"executed": st.count("E"), "frozen": st.count("F"), "open": st.count("O"),
                "freeze_line": None if self.done else label(freeze_line(self.minute, self.tier), self.date),
                "end_soc_units": proj["end_soc_units"], "discharge_units": proj["discharge_units"]}

    def advance(self) -> dict:
        if self.done:
            return {"error": "the day is over", "planning_calls_left": 0}
        if self.last:
            settled = self._settle(INTERVALS)
            self._finish("done")
            return {"done": True, "time": label(DAY_END, self.date), "settled": settled, "soc_units": self.soc,
                    "pnl": self.pnl(), **self._done_result()}
        nxt = self.watches[self.watch + 1]
        settled = self._settle(min(INTERVALS, max(0, nxt.minute // 15)))
        self._open()
        return {"watch": self.watch, "time": label(self.minute, self.date),
                "freeze_line": label(freeze_line(self.minute, self.tier), self.date),
                "first_open_interval": self.first_open, "settled": settled, "soc_units": self.soc, "pnl": self.pnl(),
                "planning_calls_left": self.calls_left}

    def _open(self):
        self.watch += 1
        self.planning_calls.append(0)
        self.frozen.append(self._frozen_row())

    def _settle(self, upto: int) -> list[dict]:
        g, out = self.grid, []
        for t in range(self.settled, upto):
            planned = self.sched[t]
            a = _clip(planned, self.soc, self.d_used, self.kd[t], self.kc[t], g)
            if a != planned:
                self.clips.append({"interval": t, "committed": planned, "executed": a, "frozen": False,
                                   "excused_usd": 0.0})
            mwh, _, deg = cash(g, 0.0, a)
            h = t // 4
            da_usd = self.da[h] * self.m_da(h) / 4
            rt_usd = self.rt[t] * (mwh - self.m_da(h) / 4)
            for c in self.clips:
                if c["interval"] == t and c["frozen"]:
                    c["excused_usd"] = max(0.0, self._rt_cash(t, c["committed"]) - self._rt_cash(t, a))
                    self.cash["excused_usd"] += c["excused_usd"]
            self.cash["da_usd"] += da_usd
            self.cash["rt_usd"] += rt_usd
            self.cash["deg_usd"] += deg
            self.executed.append(a)
            self.soc_hist.append(self.soc - a)
            self.d_used += max(a, 0)
            row = {"interval": t, "time": hhmm(15 * t), "rt_spp": _r2(self.rt[t]), "q_units": a,
                   "da_units": self.da_pos[h] if self.da_pos else 0, "usd": _r2(da_usd + rt_usd - deg)}
            self.rows.append(row | {"mwh": mwh, "da_usd": da_usd, "rt_usd": rt_usd, "deg_usd": deg})
            out.append(row)
        return out

    def _rt_cash(self, t: int, a: int) -> float:
        mwh, _, deg = cash(self.grid, 0.0, a)
        return self.rt[t] * mwh - deg

    def _finish(self, reason: str):
        g = self.grid
        self.shortfall_units = max(0, g.s_end_min - self.soc)
        self.shortfall_usd = self.shortfall_units * self.pen_unit
        removed = sum(max(0, c["executed"] - c["committed"]) for c in self.clips if c["frozen"] and c["committed"] < 0)
        self.excused_short_units = min(self.shortfall_units, removed)
        self.cash["excused_usd"] += self.excused_short_units * self.pen_unit
        self.done, self.end_reason = True, reason

    def _done_result(self) -> dict:
        if self.reference:
            return {"feasible": self.feasible(), "profit_usd": _r2(self.profit())}
        g = self.grade()
        return {"feasible": g["feasible"], "profit_usd": _r2(g["profit_usd"]), "reward": g["reward"],
                "capture_vs_hindsight": g["capture_vs_hindsight"]}

    def feasible(self) -> bool:
        return not self.clips and not self.shortfall_units

    # the harness's side

    def _apply_notice(self, n: Notice):
        if n.derate_mw is not None:
            self._derate(n)

    def _derate(self, n: Notice):
        g, p = self.grid, float(self.task["battery"]["p_dis_mw"])
        lo = 0 if n.start is None else max(0, math.floor(to_minutes(n.start, self.date)))
        hi = DAY_END if n.until is None else min(DAY_END, math.ceil(to_minutes(n.until, self.date)))
        kd = max(0, math.floor(g.k_dis * (p - n.derate_mw) / p + 1e-9))
        kc = max(0, math.floor(g.k_ch * (p - n.derate_mw) / p + 1e-9))
        ts = [t for t in range(INTERVALS) if lo <= 15 * t < hi]
        if not ts:
            return
        self.limits.append({"from": hhmm(15 * ts[0]), "until": hhmm(15 * ts[-1] + 15), "k_dis": kd, "k_ch": kc,
                            "event_id": n.event_id})
        fo = self.first_open
        for t in ts:
            self.kd[t], self.kc[t] = min(self.kd[t], kd), min(self.kc[t], kc)
            if self.settled <= t < fo:
                a = self.sched[t]
                c = min(a, self.kd[t]) if a > 0 else max(a, -self.kc[t])
                if c != a:
                    self.clips.append({"interval": t, "committed": a, "executed": c, "frozen": True,
                                       "excused_usd": 0.0, "event_id": n.event_id})
                    self.sched[t] = c

    def end_day(self) -> dict:
        """urn:gridsim:end-day/v1: play the unreached watches on the committed schedule, then grade and audit."""
        while not self.done and not self.last:
            nxt = self.watches[self.watch + 1]
            self._settle(min(INTERVALS, max(0, nxt.minute // 15)))
            self._open()
            for n in self.watches[self.watch].notices:
                self.notice(**self._kw(n), via="env")
        if not self.done:
            self._settle(INTERVALS)
            self._finish("end_day")
        g = self.grade()
        return {"end_reason": self.end_reason, "watch": self.watch, "feasible": g["feasible"],
                "profit_usd": _r2(g["profit_usd"]), "reward": g["reward"], "audit": self.audit()}

    # grading

    def references(self) -> dict:
        if self._refs is None:
            self._refs = stored_refs(self.task, self.tier, self.notices_in) or references(
                self.task, self.tier, self.notices_in)
        return self._refs

    def grade(self) -> dict:
        if not self.done:
            raise ValueError("the day is not over: advance to the end or call end_day")
        if self._grade is None:
            r = self.references()
            roll = r["roll"][self.tier]
            p, p_idle, p_roll, p_hind = self.profit(), r["p_idle"], roll["p_roll"], r["p_hind"]
            submitted = any(c["accepted"] for c in self.commits)
            reward = reward_value(p, p_idle, p_roll) if submitted else 0.0
            stretch = stretch_value(p, p_idle, p_roll, p_hind) if submitted else 0.0
            mw = float(self.task["battery"]["p_dis_mw"])
            self._grade = {
                "submitted": submitted, "tier": self.tier, "reward": reward, "profit_usd": _r6(p), "pnl": self.pnl(),
                "p_idle": p_idle, "p_naive": r["p_naive"], "p_roll": p_roll, "p_hind": p_hind,
                "capture_vs_hindsight": _r6((p - p_idle) / (p_hind - p_idle)) if p_hind - p_idle > DEGENERATE_EPS
                else None,
                "beats_anchor": p > p_roll + DEGENERATE_EPS, "regret_usd": _r6(p_hind - p),
                "regret_usd_per_mw": _r6((p_hind - p) / mw), "naive_reward": reward_value(r["p_naive"], p_idle, p_roll),
                "stretch_reward": stretch, "excused_usd": _r6(self.cash["excused_usd"]), "feasible": self.feasible(),
                "end_shortfall_units": self.shortfall_units, "commits": sum(c["accepted"] for c in self.commits)}
        return self._grade

    def audit(self, get_time_reads=None) -> dict:
        problems = self._audit_watches(get_time_reads)
        if self.transcript:
            problems += replay(self.task, self.tier, self.notices_in, self.transcript)["problems"]
        return {"ok": not problems, "problems": problems}

    def data(self) -> dict:
        return {"task_id": self.task["task_id"], "tier": self.tier, "watches": len(self.watches), "watch": self.watch,
                "time": label(self.minute, self.date), "done": self.done, "end_reason": self.end_reason,
                "calls_used": self.calls, "planning_calls": self.planning_calls, "da_position": self.da_pos,
                "schedule": self.display(), "executed": self.executed, "schedule_status": self.status(),
                "notices": self.log, "frozen": self.frozen, "refusals": self.refusals,
                "excused": {"usd": _r6(self.cash["excused_usd"]), "rows": self.clips,
                            "shortfall_units": self.excused_short_units},
                "settled": self.settled, "audit": self.audit() if self.done else None,
                "grade": self.grade() if self.done else None, "reward": self.grade()["reward"] if self.done else None}

    def episode(self, *, bundle: str = "train", path: str = "B'", model: str | None = None, trained: str | None = None,
                checkpoint_step: int | None = None, seed: int | None = None, messages: list | None = None,
                usage: dict | None = None, wall_seconds: float | None = None, episode_id: str | None = None) -> dict:
        """The gridsim.episode/v2 record of a finished day."""
        if not self.done:
            self.end_day()
        g, r, t = self.grade(), self.references(), self.task
        eid = episode_id or hashlib.sha256(_dump([t["task_id"], self.tier, bundle, path, model, trained, checkpoint_step,
                                                   seed, [s["output"] for s in self.transcript]]).encode()).hexdigest()[:16]
        when = {e["event_id"]: e["watch"] for e in self.log if e["first"]}
        steps, watch = [], 0
        for i, s in enumerate(self.transcript):
            out = json.loads(s["output"])
            steps.append({"t": i, "watch": watch, "tool": s["tool"], "args": s["args"], "output": out})
            if s["tool"] == "advance" and "watch" in out:
                watch = out["watch"]
        intervals = [{"i": x["interval"], "time": x["time"], "da": _r2(self.da[x["interval"] // 4]), "rt": x["rt_spp"],
                      "q_units": x["q_units"], "da_units": x["da_units"], "mwh": _r6(x["mwh"]),
                      "da_usd": _r6(x["da_usd"]), "rt_usd": _r6(x["rt_usd"]), "deg_usd": _r6(x["deg_usd"]),
                      "soc": self.soc_hist[x["interval"] + 1],
                      "clipped": any(c["interval"] == x["interval"] for c in self.clips)} for x in self.rows]
        return {"schema": EPISODE_SCHEMA, "episode_id": eid, "env": LIVE_ENV, "version": "v2", "task_id": t["task_id"],
                "tier": self.tier, "bundle": bundle, "path": path, "model": model, "trained": trained,
                "checkpoint_step": checkpoint_step, "seed": seed,
                "task": {k: t.get(k) for k in ("date", "settlement_point", "point_kind", "region", "battery", "prices",
                                               "rt", "blind")},
                "grid": grid_dict(t),
                "watches": [{"index": w.index, "time": w.time, "time_utc": w.time_utc,
                             "freeze_line": label(w.freeze_line, self.date),
                             "notices": [n.event_id for n in w.notices]} for w in self.watches],
                "notices": [{"event_id": n.event_id, "source": n.source, "kind": n.kind, "level": n.level,
                             "issued_at": n.issued_at, "reveal_at": label(n.reveal, self.date),
                             "watch": when.get(n.event_id), "name": n.name, "title": n.title, "text": n.text}
                            for n, _ in self.scheduled.values()],
                "steps": steps, "da_position": self.da_pos, "schedule": self.sched, "executed": self.executed,
                "soc_path": self.soc_hist, "intervals": intervals, "commits": self.commits, "pnl": self.pnl(),
                "profit_usd": g["profit_usd"], "reward": g["reward"], "capture_vs_hindsight": g["capture_vs_hindsight"],
                "stretch_reward": g["stretch_reward"], "beats_anchor": g["beats_anchor"],
                "naive_reward": g["naive_reward"],
                "references": {k: r.get(k) for k in ("p_idle", "p_naive", "p_hind", "p_hind_da", "p_hind_rt", "p_lp",
                                                     "naive", "hind")} | {"p_roll": r["roll"][self.tier]["p_roll"],
                                                                          "roll": r["roll"][self.tier]},
                "audit": self.audit(), "messages": messages or [], "usage": usage, "wall_seconds": wall_seconds}


def _as_utc(iso: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)


def replay(task: dict, tier: str, notices, transcript: list[dict]) -> dict:
    """Re-run a recorded transcript through a fresh Session and compare every output byte for byte."""
    s, problems = Session(task, tier, notices), []
    for i, step in enumerate(transcript):
        args = dict(step["args"])
        if step["tool"] == NOTICE_TOOL:
            args.setdefault("_via", "trigger")
        try:
            out = s.call(step["tool"], args)
        except ValueError as e:
            out = f"error: {e}"
        if out != step["output"]:
            problems.append(f"step {i} ({step['tool']}) does not replay byte-identically")
    return {"ok": not problems, "problems": problems}


# references: idle, naive, the rolling anchor and hindsight


def forecast(s: Session, da_pred=None) -> np.ndarray:
    """The anchor's RT forecast: DA (or the predicted DA while hidden) plus the last-hour basis decayed with a 2 h
    half-life from now."""
    base = np.repeat(s.da if s.da_visible or da_pred is None else np.asarray(da_pred, dtype=float), 4)
    n = s.settled
    b = float(np.mean([s.rt[t] - s.da[t // 4] for t in range(max(0, n - BASIS_INTERVALS), n)])) if n else 0.0
    starts = 15.0 * np.arange(INTERVALS)
    return base + b * 0.5 ** ((starts - s.minute) / BASIS_HALF_LIFE_MIN)


def roll_policy(da_pred=None, da_plan=None):
    """The notice-blind rolling re-planner: DA position at watch 0, then the exact DP over open intervals on the
    decayed-basis forecast at every watch, committed when it differs. It plays through call(), as an agent would."""

    def policy(s: Session):
        if s.watch == 0 and s.da_pos is None:
            pos = da_plan if da_plan is not None else hourly_plan(s.hb, s.da if da_pred is None else da_pred)
            s.call("commit_da", {"position": pos})
        fo = s.first_open
        if fo >= INTERVALS or not s.calls_left:
            return
        g, st, d = s.grid, s.soc, s.d_used
        cur = s.display()
        for t in range(s.settled, fo):
            a = _clip(cur[t], st, d, s.kd[t], s.kc[t], g)
            st, d = st - a, d + max(a, 0)
        f = forecast(s, da_pred)[fo:]
        plan = plan_dp(g, f, st, d, None, s.kd[fo:], s.kc[fo:])
        if plan is None:
            plan = plan_dp(g, f, st, d, s.pen_unit, s.kd[fo:], s.kc[fo:])
        if plan != cur[fo:]:
            s.call("commit_schedule", {"actions": plan, "start": hhmm(15 * fo), "step": "15m"})

    return policy


def naive_policy(da_plan):
    def policy(s: Session):
        if s.watch == 0 and s.da_pos is None:
            s.call("commit_da", {"position": da_plan})

    return policy


def play(task: dict, tier: str, notices, policy, *, reference: bool = True) -> Session:
    """Run a policy at every watch through call(), with each watch's notices delivered after advance as the gateway's
    triggers do, to the end of the day; the transcript replays byte for byte."""
    s = Session(task, tier, notices, reference=reference)
    while not s.done:
        policy(s)
        s.call("advance")
        s.deliver_watch_notices()
    return s


def settle_plan(task: dict, da_pos, phys) -> float:
    """Two-settlement profit of a DA position and a feasible physical schedule on the true day (no derates)."""
    g = live_grid(task)
    da, rt = np.asarray(task["prices"], dtype=float), np.asarray(task["rt"], dtype=float)
    m = [4 * cash(g, 0.0, a)[0] for a in da_pos]
    p, s = sum(da[h] * m[h] for h in range(HOURS)), g.s0
    for t, a in enumerate(phys):
        mwh, _, deg = cash(g, 0.0, a)
        p += rt[t] * (mwh - m[t // 4] / 4) - deg
        s -= a
    return p - max(0, g.s_end_min - s) * penalty_per_unit(g, da)


def hindsight(task: dict) -> dict:
    """P_hind as two exact DPs: the DA position on the hourly DA - mean RT spread, the physical schedule on RT."""
    hb, g = battery_of(task), live_grid(task)
    da, rt = np.asarray(task["prices"], dtype=float), np.asarray(task["rt"], dtype=float)
    spread = da - rt.reshape(HOURS, 4).mean(axis=1)
    hda = plan_dp(hb._replace(c_deg=0.0), spread, hb.s0)
    phys = plan_dp(g, rt, g.s0)
    m = [4 * cash(g, 0.0, a)[0] for a in hda]
    p_da = sum(spread[h] * m[h] for h in range(HOURS))
    p_rt = sum(rt[t] * cash(g, 0.0, a)[0] - cash(g, 0.0, a)[2] for t, a in enumerate(phys))
    return {"p_hind": p_da + p_rt, "p_hind_da": p_da, "p_hind_rt": p_rt, "da": hda, "schedule": phys}


def lp_hind(task: dict) -> float | None:
    """Joint LP relaxation of the hindsight problem (DA position and physical schedule), or None without highspy."""
    from gridsim_core.lp import highspy

    if highspy is None:
        return None
    hb, g = battery_of(task), live_grid(task)
    da, rt = np.asarray(task["prices"], dtype=float), np.asarray(task["rt"], dtype=float)
    return _lp(hb._replace(c_deg=0.0), da - rt.reshape(HOURS, 4).mean(axis=1)) + _lp(g, rt)


def _lp(b: Battery, p: np.ndarray) -> float:
    from gridsim_core.lp import highspy

    t = len(p)
    c_, x_, s_ = 0, t, 2 * t
    cost = np.concatenate([-p * b.q / b.eta, (p - b.c_deg) * b.q, np.zeros(t)])
    upper = np.concatenate([np.full(t, b.k_ch), np.full(t, b.k_dis), np.full(t, b.n)]).astype(float)
    lower = np.zeros(3 * t)
    lower[s_ + t - 1] = b.s_end_min
    rows, rlo, rhi = [], [], []
    for h in range(t):
        r = {s_ + h: 1.0, c_ + h: -1.0, x_ + h: 1.0}
        if h:
            r[s_ + h - 1] = -1.0
        rows.append(r)
        rlo.append(float(b.s0) if h == 0 else 0.0)
        rhi.append(float(b.s0) if h == 0 else 0.0)
        rows.append({c_ + h: float(b.k_dis), x_ + h: float(b.k_ch)})
        rlo.append(-np.inf)
        rhi.append(float(b.k_ch * b.k_dis))
    rows.append({x_ + h: 1.0 for h in range(t)})
    rlo.append(-np.inf)
    rhi.append(float(b.cap))
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = 3 * t, len(rows)
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = cost, lower, upper
    lp.row_lower_, lp.row_upper_ = np.array(rlo), np.array(rhi)
    lp.sense_ = highspy.ObjSense.kMaximize
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    start, index, value = [0], [], []
    for r in rows:
        for k, v in sorted(r.items()):
            index.append(k)
            value.append(v)
        start.append(len(index))
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = start, index, value
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.passModel(lp)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"LP not optimal: {h.modelStatusToString(h.getModelStatus())}")
    return float(h.getInfo().objective_function_value)


_RIDGE: dict | None = None


def ridge_model() -> dict:
    global _RIDGE
    if _RIDGE is None:
        _RIDGE = json.loads((data_root() / "ridge-v1.json").read_text())
    return _RIDGE


def roll_ref(task: dict, tier: str, notices=None, ridge: dict | None = None, p_idle: float | None = None,
             p_naive: float | None = None) -> dict:
    """The anchor on one tier: {p_roll, da, executed, commits, naive_reward} (blind: the better predictor, L-D8)."""
    runs = []
    if tier == "blind":
        hb = battery_of(task)
        preds = {"persist": task["blind"]["dam_prev_day"], "ridge": ridge_predict(task, ridge or ridge_model())}
        for via, pred in preds.items():
            runs.append((via, play(task, tier, notices, roll_policy(da_pred=pred, da_plan=hourly_plan(hb, pred)))))
    else:
        runs.append((None, play(task, tier, notices, roll_policy())))
    via, s = max(runs, key=lambda r: r[1].profit())
    out = {"p_roll": _r6(s.profit()), "da": s.da_pos, "executed": s.executed,
           "commits": sum(c["accepted"] for c in s.commits), "watches": len(s.watches)}
    if via:
        out["via"] = via
    if p_idle is not None and p_naive is not None:
        out["naive_reward"] = reward_value(p_naive, p_idle, out["p_roll"])
    return out


def references(task: dict, tier: str | tuple = "foresight", notices=None, ridge: dict | None = None,
               lp: bool = True) -> dict:
    """The refs block: idle, naive, hindsight (+ LP bound) and the anchor for each requested tier."""
    hb, g = battery_of(task), live_grid(task)
    da = np.asarray(task["prices"], dtype=float)
    p_idle = -max(0, g.s_end_min - g.s0) * penalty_per_unit(g, da)
    naive_da = hourly_plan(hb, da)
    p_naive = settle_plan(task, naive_da, expand(naive_da))
    hind = hindsight(task)
    tiers = (tier,) if isinstance(tier, str) else tuple(tier)
    roll = {t: roll_ref(task, t, notices, ridge, p_idle, p_naive) for t in tiers}
    p_lp = lp_hind(task) if lp else None
    return {"live_version": LIVE_VERSION,
            "notices_sha": notices_sha(task.get("notices") if notices is None else notices),
            "p_idle": _r6(p_idle), "p_naive": _r6(p_naive), "naive": {"da": naive_da},
            "p_hind": _r6(hind["p_hind"]), "p_hind_da": _r6(hind["p_hind_da"]), "p_hind_rt": _r6(hind["p_hind_rt"]),
            "hind": {"da": hind["da"], "schedule": hind["schedule"]},
            "p_lp": None if p_lp is None else _r6(p_lp), "roll": roll}


def stored_refs(task: dict, tier: str, notices=None) -> dict | None:
    """The task row's refs when they were computed for these notices and hold this tier's anchor."""
    r = task.get("refs")
    sha = notices_sha(task.get("notices") if notices is None else notices)
    if r and r.get("notices_sha") == sha and (r.get("roll") or {}).get(tier):
        return r
    return None
