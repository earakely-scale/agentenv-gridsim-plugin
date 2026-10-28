"""The desk Session: the only desk state machine (contract sections 2-3). It owns the event clock (milestones, notices,
outages, reminders, turn and call budgets), the eleven tools and the Episode JSON; the env server and the in-process
runner both drive it."""

from __future__ import annotations

import copy
import json
import math

from gridsim_core.desk import ancillary as asv
from gridsim_core.desk import clock
from gridsim_core.desk import forecast as fcm
from gridsim_core.desk.curves import caps, check_eboc, check_side, clear_any
from gridsim_core.desk.data import Series, build, era_of, series_sha
from gridsim_core.desk.engine import (
    IDLE_STATUSES,
    PER_H,
    STATUSES_POST,
    STATUSES_PRE,
    Engine,
    idle_end_soc,
    site_of,
)
from gridsim_core.desk.planner import ViewError, propose
from gridsim_core.desk.settle import partial, statement

CORE_VERSION = "desk-2.0"
EPISODE_SCHEMA = "gridsim.desk.episode/v1"
LAYERS = ("v2", "v3", "v4", "v5")
BUDGETS = {"v2": {"max_turns": 40, "calls_per_turn": 12, "max_reminders": 8},
           "v3": {"max_turns": 48, "calls_per_turn": 14, "max_reminders": 8},
           "v4": {"max_turns": 100, "calls_per_turn": 14, "max_reminders": 12},
           "v5": {"max_turns": 48, "calls_per_turn": 14, "max_reminders": 8}}
TOOLS = ("get_prices", "get_forecasts", "get_grid_conditions", "get_asset_status", "get_position",
         "submit_dam_offers", "submit_rt_offers", "update_cop", "check_submission", "optimize", "set_reminder")
SUBMIT_TOOLS = ("submit_dam_offers", "submit_rt_offers", "update_cop")
MAX_VALUES = 96
NOTICE_CHARS = 300
NOTE_CHARS = 120
COP_LATE_MIN = 60


def text(obj) -> str:
    """The one serializer for tool outputs and wake messages, shared by every path."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _r(x, nd: int = 2):
    return None if x is None else round(float(x), nd) + 0.0


def _stats(vals: list[float]) -> dict:
    return {"min": _r(min(vals)), "max": _r(max(vals)), "mean": _r(sum(vals) / len(vals))} if vals else {}


class Session:
    def __init__(self, task: dict, series: dict | Series, layer: str | None = None, budgets: dict | None = None,
                 forecaster=None):
        self.task = task
        self.layer = layer or task.get("layer", "v2")
        if self.layer not in LAYERS:
            raise ValueError(f"layer {self.layer!r} not in {LAYERS}")
        raw = series.raw if isinstance(series, Series) else series
        self.ser = series if isinstance(series, Series) else build(task, series)
        self.series_sha = series_sha(raw)
        self.site = site_of(task)
        self.era = task.get("era") or era_of(task["dates"])
        self.rtcb = self.era == "rtcb"
        self.d0 = self.ser.d0
        self.days = self.ser.days
        self.end = self.ser.end
        self.budget = dict(BUDGETS[self.layer], **(budgets or {}))
        self.engine = Engine(self.site, self.ser, self.rtcb, ancillary=self.layer != "v2", impact=self.layer == "v5")
        self.ser = self.engine.ser
        self.fc = forecaster or fcm.forecaster_for(self.ser)
        self.caps = caps(self.d0, self.rtcb)
        self.target = idle_end_soc(self.site, self.engine.K)
        self.now = clock.START
        self.turn = -1
        self.calls = 0
        self.reminders: dict[int, str] = {}
        self.delivered: set[str] = set()
        self.turns: list[dict] = []
        self.wakes: list[dict] = []
        self.events: list[dict] = []
        self.submissions: list[dict] = []
        self.cop_updates: list[int] = []
        self.valid = False
        self.done = False
        self.result: dict | None = None
        self._items = self._schedule()

    # ---- event clock -------------------------------------------------------------------------------------------

    def _schedule(self) -> list[dict]:
        """Every timed item of the episode: (t, reason, wakes, payload)."""
        items, d0 = [], self.d0
        for j in range(self.days):
            day = clock.day_label(j, d0)
            if j:
                items.append({"t": j * clock.DAY + clock.START, "reason": "dam_morning", "wakes": True,
                              "text": f"Morning postings for {day}; its DAM closes at 10:00"})
            items.append({"t": j * clock.DAY + clock.DAM_CLOSE, "reason": "dam_close", "wakes": False,
                          "text": f"DAM for {day} closed"})
            items.append({"t": self.ser.dam_posted[j], "reason": "dam_results", "wakes": True, "day": j})
            items.append({"t": j * clock.DAY + clock.DRUC, "reason": "druc", "wakes": False,
                          "text": f"DRUC snapshot of your COP for {day} taken (no RUC instruction for an ESR)"})
            items.append({"t": j * clock.DAY + clock.ADJ_OPEN, "reason": "adjustment_open", "wakes": True,
                          "text": f"Adjustment period open for {day}: RT offers and COP updates accepted"})
            for c in clock.CHECKPOINTS:
                items.append({"t": j * clock.DAY + c, "reason": "checkpoint", "wakes": True})
        for n in self.ser.notices:
            t = n["t_issued_at"]
            if t < clock.START - clock.DAY:
                continue
            items.append({"t": max(t, clock.START), "reason": "notice", "wakes": t > clock.START, "notice": n,
                          "id": n.get("event_id")})
        for n in self.ser.nws:
            t = n["t_issued_at"]
            items.append({"t": max(t, clock.START), "reason": "nws", "wakes": t > clock.START, "nws": n,
                          "id": n.get("event_id")})
        for e in self.ser.unit_events:
            items.append({"t": max(e["t_start"], clock.START), "reason": "outage", "wakes": True, "unit": e,
                          "phase": "start"})
            if e.get("t_end") is not None and e["t_end"] < self.end:
                items.append({"t": e["t_end"], "reason": "outage", "wakes": True, "unit": e, "phase": "end"})
        if self.layer != "v2":
            for d in self.ser.deployments:
                items.append({"t": d["t_start"], "reason": "deployment", "wakes": True, "deployment": d})
        items = [i for i in items if clock.START <= i["t"] < self.end]
        return sorted(items, key=lambda i: (i["t"], i["reason"]))

    @property
    def turns_left(self) -> int:
        return self.budget["max_turns"] - (self.turn + 1)

    def next_wakeup(self) -> dict:
        """The env's own next wake-up after now (2.4); `at` is None when nothing more wakes the agent."""
        if self.done or self.turns_left <= 0:
            return {"at": None, "at_utc": None, "reasons": []}
        cands = [(i["t"], i["reason"]) for i in self._items if i["wakes"] and i["t"] > self.now]
        cands += [(t, "reminder") for t in self.reminders if t > self.now]
        cands = [c for c in cands if c[0] < self.end]
        if not cands:
            return {"at": None, "at_utc": None, "reasons": []}
        t = min(c[0] for c in cands)
        t = int(math.ceil(t))
        reasons = sorted({r for tt, r in cands if math.ceil(tt) == t})
        return {"at": t, "at_utc": clock.to_utc(t, self.d0), "label": clock.label(t, self.d0), "reasons": reasons}

    def start(self) -> dict:
        if self.turn >= 0:
            raise RuntimeError("session already started")
        self.engine.advance(clock.START)
        return self._wake(clock.START, ["start"], self._collect(clock.START - 1, clock.START))

    def end_turn(self, text: str | None = None) -> dict | None:
        """Close the current turn and run to the next wake-up; None when the episode is over."""
        self.close_turn(text)
        nxt = self.next_wakeup()
        if nxt["at"] is None:
            self.finish()
            return None
        return self.advance_to(nxt["at"])

    def advance_to(self, t: int) -> dict | None:
        """Run the market to minute t; the wake due at t (a new turn), or None at the end or with no turns left."""
        if self.done:
            return None
        t = int(min(max(t, self.now), self.end))
        prev = self.now
        reasons = sorted({i["reason"] for i in self._items if i["wakes"] and math.ceil(i["t"]) == t}
                         | ({"reminder"} if t in self.reminders else set()))
        self.engine.advance(t)
        self.now = t
        evs = self._collect(prev, t)
        if t >= self.end:
            self.finish()
            return None
        if self.turns_left <= 0:
            return None
        return self._wake(t, reasons or ["gateway"], evs)

    def finish(self) -> dict:
        if self.result is not None:
            return self.result
        if self.turn >= 0 and self.turns and self.turns[-1].get("open"):
            self.close_turn(None)
        self.engine.advance(self.end)
        self._collect(self.now, self.end)
        self.now = self.end
        e = self.engine
        self.result = statement(self.site, self.ser, self.rtcb, e.dam_award, e.bp, e.metered, e.soc[-1], self.target,
                                self.ancillary_record())
        self.done = True
        return self.result

    def _collect(self, t0: float, t1: float) -> list[dict]:
        out = []
        for i in self._items:
            if t0 < i["t"] <= t1 or (t0 < clock.START + 1 and i["t"] == clock.START and t1 == clock.START):
                key = f"{i['reason']}@{i['t']}@{i.get('id') or i.get('phase') or ''}"
                if key in self.delivered:
                    continue
                self.delivered.add(key)
                ev = self._event(i)
                if ev:
                    out.append(ev)
        for t in sorted(self.reminders):
            if t0 < t <= t1:
                out.append({"t": clock.label(t, self.d0), "kind": "reminder", "text": self.reminders.pop(t)})
        for ev in out:
            self.events.append(dict(ev, t_min=self.now if "t_min" not in ev else ev["t_min"]))
        return out

    def _notice_event(self, n: dict, board: bool = False) -> dict:
        ev = {"t": clock.label(n["t_issued_at"], self.d0), "kind": "notice", "level": n.get("level"),
              "title": n.get("title"), "text": (n.get("text") or "")[:NOTICE_CHARS]}
        if board:
            ev["board"] = True
        return ev

    def _event(self, i: dict) -> dict | None:
        r, t = i["reason"], clock.label(i["t"], self.d0)
        if r == "notice":
            return self._notice_event(i["notice"], board=i["notice"]["t_issued_at"] < clock.START)
        if r == "nws":
            n = i["nws"]
            return {"t": t, "kind": "weather", "event": n.get("event"), "severity": n.get("severity"),
                    "text": (n.get("headline") or "")[:NOTICE_CHARS],
                    "expires": clock.label(n["t_expires"], self.d0) if n.get("t_expires") is not None else None}
        if r == "outage":
            u = i["unit"]
            if i["phase"] == "start":
                end = clock.label(u["t_end"], self.d0) if u.get("t_end") is not None else "unknown"
                return {"t": t, "kind": "outage", "text": f"{u['kind'].replace('_', ' ')}: HSL {u.get('hsl_mw', 0):g} MW,"
                        f" LSL {u.get('lsl_mw', 0):g} MW until {end} (expected). Update your COP within 60 minutes"}
            return {"t": t, "kind": "outage", "text": "Unit back to normal limits"}
        if r == "dam_results":
            return {"t": t, "kind": "dam_results", "text": self._dam_summary(i["day"])}
        if r == "checkpoint":
            return {"t": t, "kind": "checkpoint", "text": self._checkpoint_text()}
        if r == "deployment":
            d = i["deployment"]
            return {"t": t, "kind": "deployment", "product": d.get("product"), "text": d.get("summary", "")}
        if r in ("dam_close", "druc", "adjustment_open", "dam_morning"):
            return {"t": t, "kind": r, "text": i["text"]}
        return None

    def _dam_summary(self, day: int) -> str:
        a = self.engine.dam_award[24 * day:24 * day + 24]
        p = self.ser.dam_spp[24 * day:24 * day + 24]
        if any(x is None for x in a):
            return f"DAM results for {clock.day_label(day, self.d0)} posted"
        sold = sum(x for x in a if x > 0)
        bought = -sum(x for x in a if x < 0)
        hrs = sum(1 for x in a if abs(x) > 1e-6)
        val = sum(x * y for x, y in zip(a, p, strict=True))
        return (f"DAM results for {clock.day_label(day, self.d0)}: awards in {hrs} of 24 hours, sold {sold:.1f} MWh, "
                f"bought {bought:.1f} MWh, net value ${val:,.0f}; DAM SPP at your node {min(p):.2f}..{max(p):.2f}")

    def _checkpoint_text(self) -> str:
        e = self.engine
        k = e.k
        lo = max(k - PER_H, 0)
        net = sum(e.metered[lo:k]) / PER_H if k else 0.0
        return f"Shift checkpoint: SoC {e.soc[k]:.1f} MWh; last hour net {net:+.1f} MWh; shadow P&L {self._pnl_to_date():,.0f} $"

    def _pnl_to_date(self) -> float:
        e = self.engine
        upto = max(int((self.now - 2) // 15), 0)
        return partial(self.site, self.ser, self.rtcb, e.dam_award, e.bp, e.metered, upto, self.ancillary_record())["total"] if self.now > 0 else 0.0

    def _deadlines(self) -> list[dict]:
        out = []
        for j in range(self.days):
            close = j * clock.DAY + clock.DAM_CLOSE
            if self.now < close and close - self.now <= clock.DAY:
                out.append({"what": f"DAM for {clock.day_label(j, self.d0)} closes", "at": clock.label(close, self.d0)})
        nxt = (max(self.now, -60) // 60 + 1) * 60
        if nxt - 60 < self.end and nxt < self.end:
            out.append({"what": f"COP and{'' if self.rtcb else ' charging bid for'} {clock.he((nxt // 60) % 24 + 1)}"
                        f" {clock.day_label(nxt // clock.DAY, self.d0)} freeze", "at": clock.label(nxt - 60, self.d0)})
        out.append({"what": "episode ends", "at": clock.label(self.end, self.d0)})
        return out

    def _wake(self, t: int, reasons: list[str], evs: list[dict]) -> dict:
        self.turn += 1
        self.calls = 0
        w = {"now": clock.label(t, self.d0), "reasons": reasons, "events": evs, "deadlines": self._deadlines(),
             "budget": {"turns_left": self.turns_left, "calls_per_turn": self.budget["calls_per_turn"]}}
        self.wakes.append({"t": t, "label": w["now"], "reasons": reasons, "turn": self.turn})
        self.turns.append({"turn": self.turn, "t": t, "wake": copy.deepcopy(w), "calls": [], "text": None, "open": True})
        return w

    def close_turn(self, text: str | None) -> None:
        if self.turns and self.turns[-1].get("open"):
            self.turns[-1]["open"] = False
            self.turns[-1]["text"] = text

    # ---- tool dispatch -----------------------------------------------------------------------------------------

    def call(self, name: str, args: dict | None = None, role: str = "default") -> dict:
        args = args or {}
        if name == "next_wakeup" and role == "hook":
            return self.next_wakeup()
        if self.done:
            return {"error": "over: the episode has ended"}
        if name not in TOOLS:
            return self._log(name, args, {"now": self._now(), "error": f"unknown_tool: {name} is not a desk tool"}, False)
        if self.calls >= self.budget["calls_per_turn"]:
            return {"now": self._now(), "error": "budget: no tool calls left this turn; end your turn"}
        self.calls += 1
        if not isinstance(args, dict):
            return self._log(name, args, {"now": self._now(), "error": "args: arguments must be an object"}, False)
        try:
            out = getattr(self, f"_t_{name}")(**args)
        except clock.TimeError as e:
            out = {"error": f"args: {e}"}
        except ViewError as e:
            out = {"error": f"price_view: {e}"}
        except TypeError as e:
            out = {"error": f"args: {e}"}
        out = {"now": self._now(), **out}
        return self._log(name, args, out, "error" not in out)

    def _log(self, name, args, out, ok) -> dict:
        if self.turns and self.turns[-1].get("open"):
            self.turns[-1]["calls"].append({"tool": name, "args": copy.deepcopy(args), "result": copy.deepcopy(out),
                                            "ok": ok})
        return out

    def _now(self) -> str:
        return clock.label(self.now, self.d0)

    def _day(self, day) -> int:
        default = min(max(self.now, 0) // clock.DAY, self.days - 1)
        return clock.parse_day(day, self.d0, self.days, default)

    # ---- read tools ----------------------------------------------------------------------------------------------

    def _price_day(self, day) -> tuple[int | None, str]:
        """Operating-day index or None for a history date, and the ISO date."""
        if isinstance(day, str) and day.strip().startswith("D-"):
            date = clock.date_of(int(day.strip()[1:]), self.d0)
            return None, date
        if isinstance(day, str) and len(day) == 10 and day not in self.ser.dates:
            return None, day
        j = self._day(day)
        return j, self.ser.dates[j]

    def _window(self, start, end, day: int, default_hours: int, step: int) -> tuple[int, int]:
        lo_day, hi_day = day * clock.DAY, day * clock.DAY + clock.DAY
        e = clock.parse_time(end, self.d0, day) if end is not None else min(max(self.now, lo_day), hi_day)
        s = clock.parse_time(start, self.d0, day) if start is not None else e - 60 * default_hours
        s, e = max(s, lo_day), min(e, hi_day)
        return (s // step) * step, -(-e // step) * step

    def _t_get_prices(self, market: str = "rt", point: str = "node", day=None, start=None, end=None,
                      step: str | None = None) -> dict:
        if market not in ("dam", "rt", "sced", "as_dam", "as_rt", "asdc"):
            return {"error": "args: market is one of dam, rt, sced, as_dam, as_rt, asdc"}
        if market in ("as_dam", "as_rt", "asdc"):
            if self.layer == "v2":
                return {"error": "layer: ancillary service prices arrive with the v3 desk; this desk is energy only"}
            return self._as_prices(market, day, start, end, step)
        if point not in ("node", "hub"):
            return {"error": "args: point is node or hub"}
        j, date = self._price_day(day)
        hub = point == "hub"
        if market == "dam":
            if j is None:
                vals = (self.ser.history_dam_hub if hub else self.ser.history_dam).get(date)
                if vals is None:
                    return {"error": f"data: no DAM prices on the desk for {date}"}
            else:
                if self.ser.dam_posted[j] > self.now:
                    return {"error": f"not_posted: DAM prices for {date} post at "
                                     f"{clock.label(self.ser.dam_posted[j], self.d0)}"}
                src = self.ser.dam_spp_hub if hub else self.ser.dam_spp
                if not src:
                    return {"error": "data: no hub prices in this pack"}
                vals = src[24 * j:24 * j + 24]
            return {"market": "dam", "point": point, "unit": "$/MWh", "date": date, "step": "1h", "start": "HE01",
                    "values": [_r(v) for v in vals], "stats": _stats(vals)}
        if j is None:
            hist = self.ser.history_rt if market == "rt" else self.ser.history_lmp
            vals = hist.get(date) if not hub else None
            if vals is None:
                return {"error": f"data: no {market} prices on the desk for {date}"}
            base_step = 15 if market == "rt" else 5
            want = {"5m": 5, "15m": 15, "1h": 60}.get(step or "", 60)
            want = max(want, base_step)
            agg = [sum(vals[i:i + want // base_step]) / (want // base_step) for i in range(0, len(vals), want // base_step)]
            return {"market": market, "point": point, "unit": "$/MWh", "date": date, "step": f"{want}m",
                    "start": "00:00", "values": [_r(v) for v in agg], "stats": _stats(vals)}
        base_step, lag = (15, 2) if market == "rt" else (5, 1)
        if market == "rt":
            src = self.ser.rt_spp_hub if hub else self.ser.rt_spp
        else:
            if hub:
                return {"error": "data: SCED LMPs are shown for your node only"}
            src = self.ser.rt_lmp
        if not src:
            return {"error": "data: no hub prices in this pack"}
        default_h = 6 if market == "rt" else 2
        s, e = self._window(start, end, j, default_h, base_step)
        e = min(e, ((self.now - lag) // base_step) * base_step)
        if e <= s:
            return {"market": market, "point": point, "unit": "$/MWh", "date": date, "values": [],
                    "note": "no intervals posted in that window yet"}
        vals = [src[t // base_step] for t in range(s, e, base_step)]
        want = {"5m": 5, "15m": 15, "1h": 60}.get(step or "", base_step)
        want = max(want, base_step)
        while len(vals) // (want // base_step) > MAX_VALUES:
            want = 60 if want < 60 else want * 2
        g = want // base_step
        agg = [sum(vals[i:i + g]) / len(vals[i:i + g]) for i in range(0, len(vals), g)]
        return {"market": market, "point": point, "unit": "$/MWh", "date": date, "step": f"{want}m",
                "start": clock.label(s, self.d0), "end": clock.label(e, self.d0),
                "values": [_r(v) for v in agg], "stats": _stats(vals)}

    def _as_prices(self, market: str, day, start, end, step) -> dict:
        j, date = self._price_day(day)
        if market == "as_dam":
            if j is None:
                block = self.ser.history_mcpc.get(date)
                if block is None:
                    return {"error": f"data: no DAM MCPCs on the desk for {date}"}
                vals = {k: [_r(x) for x in v] for k, v in block.items()}
            else:
                if self.ser.dam_posted[j] > self.now:
                    return {"error": f"not_posted: DAM MCPCs for {date} post at "
                                     f"{clock.label(self.ser.dam_posted[j], self.d0)}"}
                vals = {k: [_r(x) for x in v[24 * j:24 * j + 24]] for k, v in self.ser.dam_mcpc.items()}
            return {"market": "as_dam", "unit": "$/MW/h", "date": date, "step": "1h", "start": "HE01", "mcpc": vals}
        if market == "asdc":
            if not self.rtcb:
                return {"error": "rule: AS demand curves start with RTC+B (2025-12-05)"}
            if j is None or not self.ser.asdc:
                return {"error": f"data: no AS demand curves for {date}"}
            posted = (self.ser.raw.get("posted") or {}).get("asdc", {}).get(date)
            t_post = clock.to_minutes(posted, self.d0) if posted else j * clock.DAY + clock.START
            if t_post > self.now:
                return {"error": f"not_posted: ASDCs for {date} post at {clock.label(t_post, self.d0)}"}
            h = min(max(self.now, 0) // 60, 24 * j + 23) % 24 if start is None else clock.parse_hours(start)[0] - 1
            return {"market": "asdc", "unit": "MW, $/MW/h", "date": date, "hour": clock.he(h + 1),
                    "curves": {k: v[24 * j + h] for k, v in self.ser.asdc.items() if v[24 * j + h]}}
        if not self.rtcb:
            return {"error": "rule: no real-time AS prices before RTC+B (scarcity was the ORDC adder in the RT SPP)"}
        if j is None:
            block = self.ser.history_rt_mcpc.get(date)
            if block is None:
                return {"error": f"data: no RT MCPCs on the desk for {date}"}
            return {"market": "as_rt", "unit": "$/MW/h", "date": date, "step": "1h", "start": "00:00",
                    "mcpc": {k: [_r(sum(v[i:i + 4]) / 4) for i in range(0, 96, 4)] for k, v in block.items()}}
        s_, e_ = self._window(start, end, j, 2, 5)
        e_ = min(e_, ((self.now - 1) // 5) * 5)
        if e_ <= s_:
            return {"market": "as_rt", "date": date, "mcpc": {}, "note": "no SCED intervals posted in that window yet"}
        want = {"5m": 5, "15m": 15, "1h": 60}.get(step or "", 15)
        g = want // 5
        out = {}
        for k, v in self.ser.rt_mcpc.items():
            vals = [v[t // 5] for t in range(s_, e_, 5)]
            out[k] = [_r(sum(vals[i:i + g]) / len(vals[i:i + g])) for i in range(0, len(vals), g)]
        return {"market": "as_rt", "unit": "$/MW/h", "date": date, "step": f"{want}m",
                "start": clock.label(s_, self.d0), "end": clock.label(e_, self.d0), "mcpc": out}

    def _t_get_forecasts(self, kind: str = "price", market: str = "dam", day=None, vintage="latest",
                         step: str | None = None) -> dict:
        at = self.now if vintage in (None, "latest") else clock.parse_time(vintage, self.d0, 0)
        if at > self.now:
            return {"error": "args: vintage is in the future; only issued forecasts can be read"}
        j = self._day(day if day is not None else (0 if self.now < 0 else None))
        date = self.ser.dates[j]
        if kind == "price":
            if market not in ("dam", "rt"):
                return {"error": "args: market is dam or rt"}
            v = fcm.views(self.ser, self.fc, at)[market]
            if market == "dam":
                sl = slice(24 * j, 24 * j + 24)
                g = 1
            else:
                sl = slice(96 * j, 96 * j + 96)
                g = 1 if step == "15m" else 4
            out = {q: [_r(sum(v.q(q)[sl][i:i + g]) / g, 1) for i in range(0, len(v.q(q)[sl]), g)]
                   for q in ("p10", "p50", "p90")}
            posted = v.posted[sl][::g]
            res = {"kind": "price", "market": market, "date": date, "step": "1h" if g == 4 or market == "dam" else "15m",
                   "start": "HE01" if g != 1 or market == "dam" else "00:00",
                   "issued_at": fcm.issued_label(v, self.d0), "model": v.model,
                   "label": fcm.label(v.model), **out}
            if any(posted):
                res["posted_slots"] = sum(posted)
                res["note"] = "slots already posted show the real price in all three quantiles"
            return res
        if kind == "as_price":
            if self.layer == "v2":
                return {"error": "layer: ancillary service prices arrive with the v3 desk; this desk is energy only"}
            v = fcm.as_views(self.ser, self.fc, at, self.rtcb)[market if market in ("dam", "rt") else "dam"]
            sl = slice(24 * j, 24 * j + 24)
            return {"kind": "as_price", "market": v["market"], "date": date, "step": "1h", "start": "HE01",
                    "unit": "$/MW/h", "model": v["model"], "label": fcm.label(v["model"]),
                    "p50": {k: [_r(x, 2) for x in q[sl]] for k, q in v["p50"].items()},
                    "p10": {k: [_r(x, 2) for x in q[sl]] for k, q in v["p10"].items()},
                    "p90": {k: [_r(x, 2) for x in q[sl]] for k, q in v["p90"].items()}}
        if kind == "pv":
            if self.site.pv_mw <= 0:
                return {"error": "data: this site has no co-located PV"}
            vs = [v for v in self.ser.forecasts if v.kind == "pv" and v.issued_at <= at]
            if not vs:
                return {"error": "data: no PV forecast issued yet"}
            return {"kind": "pv", "date": date, "issued_at": clock.label(vs[-1].issued_at, self.d0),
                    "model": vs[-1].model, "label": "modelled PV", "step": "1h", "start": "HE01", "unit": "MW",
                    "values": self._vintage_day(vs[-1], j)}
        if kind in ("load", "wind", "solar", "outages"):
            pool = self.ser.outage_capacity if kind == "outages" else self.ser.forecasts
            vs = [v for v in pool if v.kind == kind and v.issued_at <= at]
            if not vs:
                return {"error": f"data: no {kind} forecast issued by {clock.label(at, self.d0)} in this pack"}
            v = vs[-1]
            return {"kind": kind, "date": date, "issued_at": clock.label(v.issued_at, self.d0), "model": v.model,
                    "step": "1h", "start": "HE01", "unit": "MW", "values": self._vintage_day(v, j)}
        if kind == "net_load":
            parts = {}
            for k in ("load", "wind", "solar"):
                vs = [v for v in self.ser.forecasts if v.kind == k and v.issued_at <= at]
                if not vs:
                    return {"error": f"data: no {k} forecast issued yet"}
                parts[k] = self._vintage_day(vs[-1], j)
            vals = [None if any(parts[k][h] is None for k in parts) else
                    _r(parts["load"][h] - parts["wind"][h] - parts["solar"][h], 0) for h in range(24)]
            return {"kind": "net_load", "date": date, "step": "1h", "start": "HE01", "unit": "MW", "values": vals}
        if kind == "weather":
            alerts = [n for n in self.ser.nws if n["t_issued_at"] <= at and n.get("t_expires", math.inf) > at]
            return {"kind": "weather", "alerts": [{"event": n.get("event"), "severity": n.get("severity"),
                                                    "issued": clock.label(n["t_issued_at"], self.d0),
                                                    "expires": clock.label(n["t_expires"], self.d0)
                                                    if n.get("t_expires") is not None else None,
                                                    "headline": (n.get("headline") or "")[:160]} for n in alerts[-8:]]}
        return {"error": "args: kind is price, as_price, pv, load, wind, solar, net_load, outages or weather"}

    def _vintage_day(self, v, j: int) -> list:
        vals = v.values["values"]
        out = []
        for h in range(24):
            t = j * clock.DAY + 60 * h
            i = int((t - v.start) // v.step_min)
            out.append(_r(vals[i], 0) if 0 <= i < len(vals) and vals[i] is not None else None)
        return out

    def _t_get_grid_conditions(self, start=None, end=None) -> dict:
        e_ = clock.parse_time(end, self.d0, 0) if end is not None else self.now
        s_ = clock.parse_time(start, self.d0, 0) if start is not None else e_ - 120
        e_ = min(e_, self.now - 1)
        out = {}
        rows = []
        for t in range((s_ // 5) * 5, e_ - 4, 5):
            day, k = divmod(t // 5, 288)
            date = clock.date_of(day, self.d0)
            sysd = self.ser.system.get(date)
            if sysd:
                rows.append((t, sysd, k))
        if rows:
            for key in ("prc_mw", "lambda", "load_mw", "wind_mw", "solar_mw"):
                vals = [r[1][key][r[2]] for r in rows if key in r[1] and r[1][key][r[2]] is not None]
                if vals:
                    out[key] = {"last": _r(vals[-1], 1), "min": _r(min(vals), 1), "max": _r(max(vals), 1)}
            kind = rows[-1][1].get("prc_kind")
            if "prc_mw" in out and kind:
                out["prc_mw"]["kind"] = "real" if kind == "real" else "proxy (modelled from public SCED fields)"
            out["window"] = f"{clock.label(rows[0][0], self.d0)}..{clock.label(rows[-1][0] + 5, self.d0)}"
        else:
            out["note"] = "no system telemetry posted for that window"
        recent = [n for n in self.ser.notices if self.now - clock.DAY <= n["t_issued_at"] <= self.now]
        eea = next((n.get("level") for n in reversed(recent) if str(n.get("level", "")).upper().startswith("EEA")), None)
        out["eea_level"] = eea
        out["notices_recent"] = [{"t": clock.label(n["t_issued_at"], self.d0), "level": n.get("level"),
                                  "title": n.get("title")} for n in recent[-5:]]
        return out

    def _t_get_asset_status(self) -> dict:
        e, s = self.engine, self.site
        t = max(self.now, 0)
        H = min(t // 60, e.H - 1)
        hsl, lsl, ev = e.event_limits(t)
        k = e.k
        last = [{"t": clock.label(5 * i, self.d0), "bp_mw": _r(e.bp[i], 1)} for i in range(max(k - 6, 0), k)]
        curve, src = e.curve_at(H, max(self.now, 0)) if self.now >= 0 else (None, "n/a before the operating day")
        day = min(t // clock.DAY, self.days - 1)
        dis = sum(max(m, 0.0) for m in e.metered[288 * day:k]) / PER_H if self.now > 0 else 0.0
        return {"status": e.cop["status"][H] if self.now >= 0 else "ON", "soc_mwh": _r(e.soc[k], 1),
                "min_soc_mwh": _r(e.cop["min_soc"][H], 1), "max_soc_mwh": _r(e.cop["max_soc"][H], 1),
                "hsl_mw": _r(hsl, 1), "lsl_mw": _r(lsl, 1),
                "nameplate": {"hsl_mw": s.hsl, "lsl_mw": s.lsl, "e_max_mwh": s.e_max, "e_min_mwh": s.e_min,
                              "ramp_mw_per_min": _r(s.ramp, 1)},
                "last_base_points": last, "metered_mw": _r(e.metered[k - 1], 1) if k else 0.0,
                "outage": None if ev is None else {"kind": ev["kind"], "until": clock.label(ev["t_end"], self.d0)
                                                   if ev.get("t_end") is not None else None},
                "curve_in_force": src, "cycles_today": _r(dis / s.usable, 3),
                "rte": s.rte, "standby_loss_pct_per_h": s.loss_pct_h,
                "deg_usd_per_mwh": s.deg, "warranty_cycles_per_day": s.warranty,
                "params_label": "rte and standby loss calibrated from disclosures; degradation and warranty modelled",
                **self._as_status(H, k)}

    def _as_status(self, H: int, k: int) -> dict:
        e = self.engine
        if not e.ancillary:
            return {}
        out = {}
        aw = e.rt_as[k - 1] if self.rtcb and k else e.dam_as[H] if self.now >= 0 else {}
        out["as_awards_mw"] = {asv.NAMES[p]: _r(v, 1) for p, v in aw.items() if v}
        if e.cop["as_cap"][H]:
            out["as_capability_mw"] = {asv.NAMES[p]: v for p, v in e.cop["as_cap"][H].items()}
        if self.site.pv_mw > 0:
            out["pv_mw"] = _r(e.pv[k - 1], 1) if k else 0.0
            out["pv_label"] = "co-located PV (modelled), POI limit shared"
        return out

    def _t_get_position(self, day=None, detail: str = "summary") -> dict:
        e = self.engine
        j = self._day(day)
        hs = range(24 * j, 24 * j + 24)
        posted = self.ser.dam_posted[j] <= self.now
        dam = {"date": self.ser.dates[j]}
        if posted:
            a = [e.dam_award[H] for H in hs]
            p = self.ser.dam_spp[24 * j:24 * j + 24]
            dam.update({"sold_mwh": _r(sum(x for x in a if x > 0), 1), "bought_mwh": _r(-sum(x for x in a if x < 0), 1),
                        "value_usd": _r(sum(x * y for x, y in zip(a, p, strict=True)), 0)})
            if detail == "hourly":
                dam["award_mw"] = [_r(x, 1) for x in a]
        else:
            n = sum(1 for H in hs if e.dam_curve[H] is not None)
            dam["status"] = ("open" if e.dam_close(j) > self.now else "cleared, results pending")
            dam["curves_submitted_hours"] = n
        k0, k1 = 288 * j, min(e.k, 288 * j + 288)
        rt = {"intervals_run": max(k1 - k0, 0)}
        if k1 > k0:
            m = e.metered[k0:k1]
            rt.update({"discharged_mwh": _r(sum(x for x in m if x > 0) / PER_H, 1),
                       "charged_mwh": _r(-sum(x for x in m if x < 0) / PER_H, 1)})
            if detail == "hourly":
                rt["hourly_net_mw"] = [_r(sum(e.metered[i:i + PER_H]) / PER_H, 1) for i in range(k0, k1, PER_H)]
        srcs = []
        for H in hs:
            t = max(self.now, 60 * H)
            if self.rtcb:
                c, src = e.curve_at(H, t)
            else:
                c, src = e.curve_at(H, t)
            srcs.append(src)
        groups, a = [], 0
        for h in range(1, 25):
            if h == 24 or srcs[h] != srcs[a]:
                groups.append(f"{clock.hours_label(list(range(a + 1, h + 1)))}:{srcs[a]}")
                a = h
        cop = {"hbsoc_mwh": [_r(e.cop["hbsoc"][H], 1) for H in hs]}
        st = sorted({e.cop["status"][H] for H in hs})
        cop["status"] = st[0] if len(st) == 1 else {clock.he(H % 24 + 1): e.cop["status"][H] for H in hs}
        if detail == "hourly":
            cop.update({"hsl_mw": [_r(e.cop["hsl"][H], 1) for H in hs], "lsl_mw": [_r(e.cop["lsl"][H], 1) for H in hs]})
        out = {"date": self.ser.dates[j], "dam": dam, "rt": rt, "curves": groups, "cop": cop}
        if e.ancillary:
            out["as"] = self._as_position(j, posted, detail)
        if detail == "hourly":
            nxt = min(max(self.now, 0) // 60, e.H - 1)
            out["next_curves"] = {clock.he(H % 24 + 1): e.curve_at(H, max(self.now, 60 * H))[0]
                                  for H in range(max(nxt, 24 * j), min(nxt + 3, 24 * j + 24))}
        upto = max(int((self.now - 2) // 15), 0)
        if self.now > 0:
            out["shadow_statement"] = partial(self.site, self.ser, self.rtcb, e.dam_award, e.bp, e.metered, upto, self.ancillary_record())
            out["shadow_statement"]["label"] = "settled intervals so far; degradation modelled"
        return out

    def _as_position(self, j: int, posted: bool, detail: str) -> dict:
        e = self.engine
        hs = range(24 * j, 24 * j + 24)
        out: dict = {}
        if posted:
            tot = {asv.NAMES[p]: _r(sum(e.dam_as[H].get(p, 0.0) for H in hs), 1) for p in e.products}
            val = sum(e.dam_as[H].get(p, 0.0) * self.ser.dam_mcpc.get(asv.PRICE_KEY[p], [0.0] * e.H)[H]
                      for H in hs for p in e.products)
            out["dam_awards_mwh"] = {k: v for k, v in tot.items() if v}
            out["dam_value_usd"] = _r(val, 0)
            if detail == "hourly":
                out["dam_award_mw"] = {asv.NAMES[p]: [_r(e.dam_as[H].get(p, 0.0), 1) for H in hs]
                                       for p in e.products if any(e.dam_as[H].get(p) for H in hs)}
        offered = {asv.NAMES[p]: sum(1 for H in hs if p in e.dam_as_offer[H]) for p in e.products}
        out["dam_offers_hours"] = {k: v for k, v in offered.items() if v}
        if self.rtcb and e.k > 288 * j:
            k1 = min(e.k, 288 * j + 288)
            ks = range(288 * j, k1)
            out["rt_awards_mwh"] = {asv.NAMES[p]: _r(sum(e.rt_as[k].get(p, 0.0) for k in ks) / PER_H, 1)
                                    for p in e.products if any(e.rt_as[k].get(p) for k in ks)}
            if self.now >= 0 and 60 * (self.now // 60) // 60 < e.H:
                _, src = e.as_offers_at(min(self.now // 60, e.H - 1), self.now)
                out["rt_offers_in_force"] = {asv.NAMES[p]: v for p, v in src.items()}
        if not self.rtcb:
            short = sum(sum(x.values()) for x in e.as_short[288 * j:min(e.k, 288 * j + 288)]) / PER_H
            out["responsibility_short_mwh"] = _r(short, 2)
        return out

    # ---- submissions -------------------------------------------------------------------------------------------

    def _items_of(self, curves) -> list[tuple[list[int] | None, dict, str | None]]:
        if not isinstance(curves, list) or not curves:
            return [(None, {}, "curves must be a non-empty list of {hours, points} objects")]
        out = []
        for c in curves:
            if not isinstance(c, dict):
                out.append((None, {}, "each curve is an object with hours and points"))
                continue
            try:
                out.append((clock.parse_hours(c.get("hours", "all")), c, None))
            except clock.TimeError as e:
                out.append((None, c, str(e)))
        return out

    def _validate_curve(self, c: dict, cap: float, market: str, H: int) -> tuple[list[dict], list[dict], object]:
        s = self.site
        if self.rtcb:
            if "points" not in c:
                return [{"code": "EBOC-01", "text": "points missing"}], [], None
            errs, warns = check_eboc(c["points"], cap, s.lsl, s.hsl)
            if not errs:
                lo, hi = self.engine.cop["lsl"][H], self.engine.cop["hsl"][H]
                if any(q < lo - 1e-6 or q > hi + 1e-6 for q, _ in c["points"]):
                    warns.append({"code": "EBOC-W1", "text": f"MW beyond the COP limits [{lo:g}, {hi:g}]; "
                                                             "the market bounds the award"})
            return errs, warns, [[float(q), float(p)] for q, p in c.get("points", [])]
        if "points" in c and not ("offer" in c or "bid" in c):
            return [{"code": "GOC-00", "text": "before RTC+B a battery submits a Gen Resource offer ('offer') and "
                                              "a charging bid ('bid'), not one curve"}], [], None
        errs = []
        cur = {}
        for side, limit in (("offer", s.hsl), ("bid", -s.lsl)):
            if c.get(side) is not None:
                errs += check_side(c[side], cap, limit, side)
                cur[side] = [[float(q), float(p)] for q, p in c[side]] if not errs else None
        if not cur:
            errs.append({"code": "GOC-00", "text": "give an 'offer', a 'bid' or both"})
        return errs, [], cur

    def _submit(self, tool: str, day, curves, apply: bool) -> dict:
        e = self.engine
        j = self._day(day if day is not None else (0 if self.now < 0 else None))
        market = "dam" if tool == "submit_dam_offers" else "rt"
        cap = self.caps[market]
        accepted, rejected, warnings = [], [], []
        changes = []
        for hours, c, perr in self._items_of(curves):
            if perr:
                rejected.append({"hours": c.get("hours") if isinstance(c, dict) else None, "code": "EBOC-07",
                                 "text": perr})
                continue
            for h in hours:
                H = 24 * j + h - 1
                errs, warns, cur = self._validate_curve(c, cap, market, H)
                if market == "dam" and e.dam_close(j) <= self.now:
                    errs = [{"code": "EBOC-06", "text": f"the DAM for {self.ser.dates[j]} closed at "
                                                        f"{clock.label(e.dam_close(j), self.d0)}"}] + errs
                if market == "rt":
                    if self.now < e.adj_open(H):
                        errs = [{"code": "EBOC-06", "text": f"RT offers for {self.ser.dates[j]} open at "
                                                            f"{clock.label(e.adj_open(H), self.d0)}"}] + errs
                    elif self.now >= 60 * (H + 1):
                        errs = [{"code": "EBOC-06", "text": f"{clock.he(h)} has ended"}] + errs
                    elif not self.rtcb and cur and cur.get("bid") is not None and self.now >= 60 * H - 60:
                        frozen = {"code": "LRB-05", "text": f"the charging bid for {clock.he(h)} froze at "
                                                            f"{clock.label(60 * H - 60, self.d0)}"}
                        if cur.get("offer") is None:
                            errs = [frozen] + errs
                        else:
                            rejected.append({"hours": clock.he(h), **frozen})
                            cur = {"offer": cur["offer"]}
                if errs:
                    rejected.append({"hours": clock.he(h), **errs[0]})
                    continue
                warnings += [{"hours": clock.he(h), **w} for w in warns]
                accepted.append(h)
                changes.append((H, cur))
        if apply:
            for H, cur in changes:
                if market == "dam":
                    if self.rtcb:
                        e.dam_curve[H] = cur
                    else:
                        merged = dict(e.dam_curve[H] or {})
                        merged.update(cur)
                        e.dam_curve[H] = merged
                elif self.rtcb:
                    e.rt[H].append((self.now, cur))
                else:
                    if cur.get("offer") is not None:
                        e.rt[H].append((self.now, cur["offer"]))
                    if cur.get("bid") is not None:
                        e.rt_bid[H].append((self.now, cur["bid"]))
            if changes:
                self.valid = True
            self.submissions.append({"t": self.now, "tool": tool, "day": f"D{j}", "hours": accepted,
                                     "accepted": bool(accepted), "codes": sorted({r["code"] for r in rejected})})
        rej = self._compact_rejects(rejected)
        out = {"date": self.ser.dates[j], "accepted_hours": clock.hours_label(sorted(set(accepted))),
               "rejected": rej, "warnings": self._compact_rejects(warnings)}
        if apply and accepted:
            out["effective"] = ("clears at the DAM close" if market == "dam" else "from the next SCED run")
        return out

    @staticmethod
    def _compact_rejects(rows: list[dict]) -> list[dict]:
        out = []
        for r in rows:
            if out and out[-1]["code"] == r["code"] and out[-1]["text"] == r["text"]:
                out[-1]["hours"] = f"{out[-1]['hours']},{r['hours']}"
            else:
                out.append(dict(r))
        return out[:8]

    def _t_submit_dam_offers(self, curves=None, day=None, as_offers=None) -> dict:
        return self._offers("submit_dam_offers", day, curves, as_offers, True)

    def _t_submit_rt_offers(self, curves=None, day=None, as_offers=None) -> dict:
        return self._offers("submit_rt_offers", day, curves, as_offers, True)

    def _offers(self, tool: str, day, curves, as_offers, apply: bool) -> dict:
        if as_offers is not None and self.layer == "v2":
            return {"error": "layer: AS offers arrive with the v3 desk; this desk is energy only"}
        if curves is None and as_offers is None:
            return {"error": "args: give curves, as_offers or both"}
        out = self._submit(tool, day, curves, apply) if curves is not None else {}
        if as_offers is not None:
            out.update(self._submit_as(tool, day, as_offers, apply))
        return out

    def _submit_as(self, tool: str, day, items, apply: bool) -> dict:
        """AS offers per hour and product: [{"hours", "product", "blocks": [[mw, $/MW/h], ...]}] (the same blocks each
        hour; [] cancels) or [{"hours", "product", "mw": [...], "price": [...]}] (one block per hour; 0 MW cancels)."""
        e = self.engine
        j = self._day(day if day is not None else (0 if self.now < 0 else None))
        market = "dam" if tool == "submit_dam_offers" else "rt"
        if market == "rt" and not self.rtcb:
            return {"as_rejected": [{"hours": "all", "code": "ASO-06",
                                     "text": "no real-time AS market before RTC+B: DAM awards are your responsibility"}]}
        if not isinstance(items, list) or not items:
            return {"as_rejected": [{"hours": None, "code": "ASO-02", "text": "as_offers is a list of objects"}]}
        cap = self.caps[market]
        accepted, rejected, changes = [], [], []
        for it in items:
            if not isinstance(it, dict):
                rejected.append({"hours": None, "code": "ASO-02", "text": "each AS offer is an object"})
                continue
            try:
                hours = clock.parse_hours(it.get("hours", "all"))
            except clock.TimeError as ex:
                rejected.append({"hours": it.get("hours"), "code": "ASO-07", "text": str(ex)})
                continue
            p = it.get("product")
            per_hour = "mw" in it or "price" in it
            if per_hour:
                mw, pr = it.get("mw"), it.get("price")
                if not isinstance(mw, list) or not isinstance(pr, list) or not len(mw) == len(pr) == len(hours):
                    rejected.append({"hours": it.get("hours"), "code": "ASO-02",
                                     "text": "mw and price must be lists with one value per hour"})
                    continue
            for n_h, h in enumerate(hours):
                H = 24 * j + h - 1
                blocks = ([] if not mw[n_h] else [[mw[n_h], pr[n_h]]]) if per_hour else it.get("blocks")
                why = [] if blocks == [] and p in e.products else asv.check_as_offer(
                    p, blocks, cap, e.range_mw, self.ser.dates[j])
                if market == "dam" and e.dam_close(j) <= self.now:
                    why = [{"code": "ASO-06", "text": f"the DAM for {self.ser.dates[j]} closed"}] + why
                if market == "rt" and (self.now < e.adj_open(H) or self.now >= 60 * (H + 1)):
                    why = [{"code": "ASO-06", "text": f"{clock.he(h)} is not open for RT AS offers"}] + why
                if why:
                    rejected.append({"hours": clock.he(h), "product": p, **why[0]})
                    continue
                accepted.append(f"{asv.NAMES[p]} {clock.he(h)}")
                changes.append((H, p, [[float(a), float(b)] for a, b in blocks]))
            mw = pr = None
        if apply:
            for H, p, bl in changes:
                if market == "dam":
                    if bl:
                        e.dam_as_offer[H][p] = bl
                    else:
                        e.dam_as_offer[H].pop(p, None)
                else:
                    e.rt_as_offer[H].append((self.now, {p: bl}))
            if changes:
                self.valid = True
                self.submissions.append({"t": self.now, "tool": tool, "day": f"D{j}", "as": True,
                                         "hours": sorted({H % 24 + 1 for H, _, _ in changes}), "accepted": True,
                                         "codes": sorted({r["code"] for r in rejected})})
        by_p: dict[str, list[int]] = {}
        for H, p, _ in changes:
            by_p.setdefault(asv.NAMES[p], []).append(H % 24 + 1)
        return {"as_accepted": {k: clock.hours_label(sorted(set(v))) for k, v in by_p.items()},
                "as_rejected": self._compact_rejects(rejected)}

    def _cop_check(self, j: int, rows, apply: bool) -> dict:
        e, s = self.engine, self.site
        if not isinstance(rows, list) or not rows:
            return {"error": "args: rows must be a non-empty list of {hours, ...} objects"}
        new = {k: list(v) for k, v in e.cop.items()}
        accepted, rejected, touched = [], [], set()
        statuses = STATUSES_POST if self.rtcb else STATUSES_PRE
        if any(isinstance(r, dict) and "as_capability" in r for r in rows):
            if self.layer == "v2":
                return {"error": "layer: AS capability arrives with the v3 desk; this desk is energy only"}
            if not self.rtcb:
                return {"error": "rule: before RTC+B the COP carries AS Resource Responsibility, which follows your "
                                 "DAM AS awards here"}
        keys = {"status": "status", "hsl_mw": "hsl", "lsl_mw": "lsl", "hbsoc_mwh": "hbsoc",
                "min_soc_mwh": "min_soc", "max_soc_mwh": "max_soc"}
        for row in rows:
            if not isinstance(row, dict):
                rejected.append({"hours": None, "code": "COP-00", "text": "each row is an object"})
                continue
            try:
                hours = clock.parse_hours(row.get("hours", "all"))
            except clock.TimeError as ex:
                rejected.append({"hours": row.get("hours"), "code": "COP-00", "text": str(ex)})
                continue
            unknown = [k for k in row if k not in keys and k not in ("hours", "as_capability")]
            if unknown:
                rejected.append({"hours": row.get("hours"), "code": "COP-00",
                                 "text": f"unknown fields {unknown}" + ("; AS capability arrives with v3"
                                                                         if "as_capability" in unknown else "")})
                continue
            for i, h in enumerate(hours):
                H = 24 * j + h - 1
                if self.now >= 60 * H - 60:
                    rejected.append({"hours": clock.he(h), "code": "COP-05",
                                     "text": f"{clock.he(h)} froze at {clock.label(60 * H - 60, self.d0)}"})
                    continue
                for k, f in keys.items():
                    if k in row:
                        v = row[k]
                        if isinstance(v, list):
                            if len(v) != len(hours):
                                rejected.append({"hours": clock.he(h), "code": "COP-00",
                                                 "text": f"{k} list must match the number of hours"})
                                break
                            v = v[i]
                        if f == "status":
                            if v not in statuses:
                                rejected.append({"hours": clock.he(h), "code": "COP-01",
                                                 "text": f"status {v!r} not in {list(statuses)}"})
                                break
                            new[f][H] = v
                        else:
                            if not isinstance(v, int | float) or isinstance(v, bool) or not math.isfinite(v):
                                rejected.append({"hours": clock.he(h), "code": "COP-00", "text": f"{k} must be a number"})
                                break
                            new[f][H] = float(v)
                else:
                    if "as_capability" in row:
                        capd = row["as_capability"]
                        bad_cap = (not isinstance(capd, dict) or any(
                            p not in e.products or not isinstance(v, int | float) or isinstance(v, bool)
                            or not 0 <= v <= e.range_mw + 1e-6 for p, v in capd.items()))
                        if bad_cap:
                            rejected.append({"hours": clock.he(h), "code": "COP-06",
                                             "text": f"as_capability maps products {list(e.products)} to MW in "
                                                     f"[0, {e.range_mw:g}]"})
                            continue
                        new["as_cap"][H] = dict(new["as_cap"][H], **{p: float(v) for p, v in capd.items()})
                    touched.add(H)
        bad: dict[int, dict] = {}
        for H in sorted(touched):
            h = H % 24 + 1
            if not (s.e_min - 1e-6 <= new["min_soc"][H] <= new["hbsoc"][H] + 1e-6
                    and new["hbsoc"][H] <= new["max_soc"][H] + 1e-6 and new["max_soc"][H] <= s.e_max + 1e-6):
                bad[H] = {"hours": clock.he(h), "code": "COP-02",
                          "text": f"need {s.e_min:g} <= MinSOC <= HBSOC <= MaxSOC <= {s.e_max:g}"}
            elif not (s.lsl - 1e-6 <= new["lsl"][H] <= new["hsl"][H] + 1e-6 and new["hsl"][H] <= s.hsl + 1e-6):
                bad[H] = {"hours": clock.he(h), "code": "COP-04", "text": f"need {s.lsl:g} <= LSL <= HSL <= {s.hsl:g}"}
            else:
                for G in (H - 1, H + 1):
                    if 0 <= G < e.H and G // 24 == H // 24:
                        a, b = (new["hbsoc"][G], new["hbsoc"][H]) if G < H else (new["hbsoc"][H], new["hbsoc"][G])
                        loss = a * s.loss_pct_h / 100 + 0.01
                        if b - a > s.eta * -s.lsl + 0.01 or a - b > s.hsl / s.eta + loss:
                            bad[H] = {"hours": clock.he(h), "code": "COP-03",
                                      "text": "HBSOC change between consecutive hours exceeds the max charge/discharge rate"}
        for H in sorted(touched):
            if H in bad:
                rejected.append(bad[H])
                for f in new:
                    new[f][H] = e.cop[f][H]
            else:
                accepted.append(H % 24 + 1)
        warnings = []
        acc = sorted(set(accepted))
        if acc and len({round(new["hbsoc"][24 * j + h - 1], 1) for h in acc}) == 1 and len(acc) > 3:
            warnings.append({"hours": clock.hours_label(acc), "code": "COP-W2", "text": "flat HBSOC"})
        if apply and acc:
            for f in new:
                for h in acc:
                    e.cop[f][24 * j + h - 1] = new[f][24 * j + h - 1]
                    e.cop_touched[24 * j + h - 1] = True
            self.cop_updates.append(self.now)
            self.submissions.append({"t": self.now, "tool": "update_cop", "day": f"D{j}", "hours": acc,
                                     "accepted": True, "codes": sorted({r["code"] for r in rejected})})
        return {"date": self.ser.dates[j], "accepted_hours": clock.hours_label(acc),
                "rejected": self._compact_rejects(rejected), "warnings": warnings}

    def _t_update_cop(self, rows=None, day=None) -> dict:
        j = self._day(day if day is not None else (0 if self.now < 0 else None))
        return self._cop_check(j, rows, True)

    def _t_check_submission(self, kind: str = "dam", payload: dict | None = None) -> dict:
        payload = payload or {}
        if not isinstance(payload, dict):
            return {"error": "args: payload is the arguments object of the matching submit tool"}
        if kind == "cop":
            j = self._day(payload.get("day") if payload.get("day") is not None else (0 if self.now < 0 else None))
            out = self._cop_check(j, payload.get("rows"), False)
        elif kind in ("dam", "rt"):
            tool = "submit_dam_offers" if kind == "dam" else "submit_rt_offers"
            out = self._offers(tool, payload.get("day"), payload.get("curves"), payload.get("as_offers"), False)
            if kind == "dam" and "error" not in out and out.get("accepted_hours"):
                j = self._day(payload.get("day") if payload.get("day") is not None else (0 if self.now < 0 else None))
                p50 = fcm.views(self.ser, self.fc, self.now)["dam"].p50
                clears = {}
                for hours, c, perr in self._items_of(payload.get("curves")):
                    if perr:
                        continue
                    for h in hours:
                        H = 24 * j + h - 1
                        _, _, cur = self._validate_curve(c, self.caps["dam"], "dam", H)
                        if cur:
                            clears[h] = _r(clear_any(cur, p50[H]), 1)
                out["would_clear_at_desk_p50"] = [f"{clock.he(h)}:{v:g}" for h, v in sorted(clears.items())]
        else:
            return {"error": "args: kind is dam, rt or cop"}
        if "error" in out:
            return out
        out["ok"] = not out.get("rejected") and not out.get("as_rejected")
        return out

    def _t_optimize(self, price_view="desk", risk: float = 0.5, constraints: dict | None = None) -> dict:
        if not isinstance(risk, int | float) or isinstance(risk, bool):
            return {"error": "args: risk is a number in [0, 1]"}
        if constraints is not None and not isinstance(constraints, dict):
            return {"error": "args: constraints is an object"}
        try:
            out = propose(self.engine, self.now, fcm.views(self.ser, self.fc, self.now), price_view, risk, constraints,
                          self.fc)
        except RuntimeError as e:
            return {"error": f"optimize: {e}"}
        out.pop("_plans", None)
        return out

    def _t_set_reminder(self, at=None, note: str = "") -> dict:
        if at is None:
            return {"error": "args: at is required"}
        t = clock.parse_time(at, self.d0, max(self.now, 0) // clock.DAY)
        t = -(-t // 5) * 5
        if t <= self.now:
            return {"error": f"args: {clock.label(t, self.d0)} is not after now"}
        if t >= self.end:
            return {"error": "args: that is after the episode ends"}
        if t not in self.reminders and len(self.reminders) >= self.budget["max_reminders"]:
            return {"error": f"budget: {self.budget['max_reminders']} reminders already pending"}
        self.reminders[t] = str(note)[:NOTE_CHARS]
        return {"ok": True, "at": clock.label(t, self.d0), "pending": len(self.reminders)}

    # ---- results -------------------------------------------------------------------------------------------------

    def ancillary_record(self) -> dict | None:
        e = self.engine
        if not e.ancillary:
            return None
        return {"dam_as": e.dam_as, "rt_as": e.rt_as if self.rtcb else None, "short": e.as_short, "druc": e.druc,
                "pv": e.pv if self.site.pv_mw > 0 else None}

    def compliance(self) -> dict:
        late = 0
        for ev in self.ser.unit_events:
            t0 = ev["t_start"]
            if t0 < 0 or t0 >= self.end:
                continue
            if not any(t0 <= t <= t0 + COP_LATE_MIN for t in self.cop_updates):
                late += 1
        out = {"cop_late": late}
        if self.engine.ancillary:
            out["deployment_short_mwh"] = round(sum(self.engine.deploy_short) / PER_H, 3)
        return out

    def episode(self, policy: dict | None = None, usage: dict | None = None, grade: dict | None = None) -> dict:
        e = self.engine
        dam, rt = {}, {}
        for j, d in enumerate(self.ser.dates):
            hs, ks = slice(24 * j, 24 * j + 24), slice(288 * j, 288 * j + 288)
            dam[d] = {"spp": self.ser.dam_spp[hs], "award_mw": e.dam_award[hs],
                      "curves": [e.dam_curve[H] for H in range(24 * j, 24 * j + 24)]}
            if e.ancillary:
                dam[d]["as_award_mw"] = e.dam_as[hs]
            rt[d] = {"lmp": self.ser.rt_lmp[ks], "spp": self.ser.rt_spp[96 * j:96 * j + 96],
                     "base_point_mw": e.bp[ks], "metered_mw": e.metered[ks],
                     "soc_mwh": [round(x, 3) for x in e.soc[288 * j:288 * j + 289]], "curve_source": e.source[ks]}
            if e.ancillary:
                rt[d]["as_award_mw"] = e.rt_as[ks] if self.rtcb else None
                rt[d]["deploy_short_mw"] = e.deploy_short[ks]
            if self.site.pv_mw > 0:
                rt[d]["pv_mw"] = e.pv[ks]
        site = self.task["site"]
        return {"schema": EPISODE_SCHEMA, "task_id": self.task["task_id"], "layer": self.layer, "era": self.era,
                "dates": self.ser.dates,
                "site": {"card": site.get("card"), "hsl_mw": self.site.hsl, "lsl_mw": self.site.lsl,
                         "e_max_mwh": self.site.e_max, "e_min_mwh": self.site.e_min, "rte": self.site.rte},
                "policy": policy or {}, "wakes": self.wakes,
                "turns": [{k: v for k, v in t.items() if k != "open"} for t in self.turns],
                "submissions": self.submissions, "dam": dam, "rt": rt,
                "events": [{k: v for k, v in ev.items()} for ev in self.events],
                "statement": self.result, "grade": grade, "compliance": self.compliance(),
                "usage": usage or {}, "budget": self.budget, "series_sha": self.series_sha,
                "core_version": CORE_VERSION}


def is_idle_status(s: str) -> bool:
    return s in IDLE_STATUSES
