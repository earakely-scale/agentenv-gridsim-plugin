"""GridSimEnv v5 "The Market Floor": a price-making battery offers into a re-cleared ERCOT day-ahead market.

Session is the only v5 state machine: the gridsim-market env wraps it, path B (`floor-sprint`) grades with
grade_offer and path B' plays `floor-day` in-process. Times are minutes from D 00:00 CPT (D-1 09:00 is −900, DAM close
−840, awards −630); prices in offers are system energy prices λ, settlement is at the hub (λ + the real basis)."""

from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np

from gridsim_core.contract import AS_PRODUCTS, DEGENERATE_EPS
from gridsim_core.grade import reward_value, stretch_value
from gridsim_core.live import (
    BARRIER_SECONDS,
    CLOCK_URI,
    NOTICE_TOOL,
    WatchDay,
    freeze_line,
    label,
    notices_sha,
    to_minutes,
)
from gridsim_core.live import schedule as live_schedule
from gridsim_core.live import triggers as live_triggers
from gridsim_core.market_auction import (
    HOURS,
    SEATS,
    Book,
    OfferError,
    _r2,
    _r6,
    battery_of,
    clear_mitigated,
    dump,
    kept,
    lift,
    offer_blocks,
    offer_json,
    parse_offer,
    penalty_price,
    project,
    settle_battery,
)
from gridsim_core.market_refs import (
    ACTS,
    MARKET_VERSION,
    anchor,
    baseline_offers,
    battery_dp,
    eps_nash,
    forecast_book,
    forecast_books,
    reference_prices,
    references,
    replay_profile,
    welfare_rows,
)
from gridsim_core.market_stack import (
    API_START,
    DISCLOSURE_LAG_DAYS,
    DISCLOSURE_WINDOW_DAYS,
    KIND,
    DayStore,
    Floor,
    aggregate,
    disclosure,
    hour_curves,
    shift,
    simplify,
    task_store,
)
from gridsim_core.trl import _THINK, _TOOL_CALL, _flatten, _name_args

__all__ = ["Session", "OfferError", "parse_offer", "project", "grade_offer", "reward_fn", "references", "replay",
           "play", "schedule", "triggers", "finalize_task", "MARKET_VERSION", "MARKET_ENV", "EPISODE_SCHEMA", "TIERS",
           "TOOLS", "SEATS", "LOAD_URI", "END_URI", "CLOCK_URI", "PLANNING_CALLS", "MAX_TURNS"]

MARKET_ENV = "gridsim-market"
EPISODE_SCHEMA = "gridsim.episode/v5"
TIERS = ("floor-sprint", "floor-day")
LOAD_URI = "urn:gridsim:market-load/v1"
END_URI = "urn:gridsim:end-floor/v1"
SPRINT_TOOLS = ("get_situation", "get_forecast", "get_disclosure", "get_private_costs", "check_offer", "submit_offer")
TOOLS = SPRINT_TOOLS + ("get_award", "check_schedule", "commit_schedule", "advance", "propose_contract",
                        "respond_contract", "message_agent")
PLANNING_TOOLS = ("check_offer", "submit_offer", "check_schedule", "commit_schedule")
DATA_TOOLS = ("get_forecast", "get_disclosure")
PLANNING_CALLS, DATA_CALLS = 3, 6
MAX_TURNS = {"floor-sprint": 6, "floor-day": 36}
MAX_CALLS = {"floor-sprint": 24, "floor-day": 120}
REGULAR = {"floor-sprint": (-900,), "floor-day": (-1080, -900, -630, 0, 360, 720, 1080)}
DAM_CLOSE, AWARDS, DAY_END = -840, -630, 1440
MAX_CONTRACTS, CONTRACT_SHARE = 3, 0.25
BASIS_HOURS, BASIS_HALF_LIFE_MIN = 4, 120.0
PRICE_TALK = re.compile(r"\$\s?\d|\bprices?\b|\bbids?\b|\boffers?\b|withh?old|\bcap\b|\bclear", re.I)
ARGS = {"get_situation": (), "get_forecast": ("kind", "issued_at"), "get_disclosure": ("op_date", "side", "hour"),
        "get_private_costs": (), "check_offer": ("offer",), "submit_offer": ("offer",), "get_award": ("op_date",),
        "check_schedule": ("plan", "from_hour"), "commit_schedule": ("plan", "from_hour"), "advance": (),
        "propose_contract": ("counterparty", "kind", "hours", "mw", "strike_usd", "op_dates"),
        "respond_contract": ("contract_id", "action", "strike_usd"), "message_agent": ("agent_name", "text")}
REQUIRED = {"get_forecast": ("kind",), "get_disclosure": ("op_date",), "check_offer": ("offer",),
            "submit_offer": ("offer",), "check_schedule": ("plan",), "commit_schedule": ("plan",),
            "propose_contract": ("hours", "mw", "strike_usd"), "respond_contract": ("contract_id", "action"),
            "message_agent": ("agent_name", "text")}


def schedule(task: dict, tier: str = "floor-sprint", notices=None) -> list:
    """The watches: `floor-sprint` one at D-1 09:00 with no ISO; `floor-day` the regular watches plus notice watches."""
    ns = [] if tier == "floor-sprint" else (task.get("notices") or [] if notices is None else notices)
    return live_schedule(task, tier, ns, regular=REGULAR[tier])


def triggers(watches: list) -> list[dict]:
    return live_triggers(watches)


def finalize_task(task: dict, store: DayStore | None = None, nash_ref: bool = False) -> dict:
    """Fill a task row's battery references (V5-P5), refs and fidelity from its days; what the pack builder calls."""
    store = store if store is not None else task_store(task)
    fc = forecast_books(store, task)
    for s in ("A", "B"):
        if s in task["seats"]:
            task["seats"][s]["reference_usd"] = reference_prices(battery_of(task["seats"][s]), fc["forecast_hub_usd"])
    task["refs"] = references(task, store, nash_ref)
    day = store.get(task["date"])
    task["fidelity"] = day.get("fidelity")
    task["notices_sha"] = notices_sha(task.get("notices"))
    p_day = play(task, "floor-day", anchor_policy, store=store).profit()
    refs = task["refs"]
    refs["floor-day"]["p_anchor"] = round(p_day, 6)
    refs["headroom_usd_per_mw"]["anchor_day"] = round((p_day - refs["p_idle"]) / task["seats"]["A"]["p_mw"], 2)
    return task


class Session(WatchDay):
    """One floor (seat A). Drive it through call() so outputs, messages and the transcript match path A exactly."""

    TOOLS = TOOLS
    RT_MINUTES = 60

    def __init__(self, task: dict, tier: str = "floor-sprint", notices=None, *, store: DayStore | None = None,
                 compliant: bool = False):
        if tier not in TIERS:
            raise ValueError(f"unknown tier {tier!r}; tiers are {', '.join(TIERS)}")
        self.task, self.tier, self.date, self.compliant = task, tier, task["date"], compliant
        self.tools = SPRINT_TOOLS if tier == "floor-sprint" else TOOLS
        self.store = store if store is not None else task_store(task)
        self.F = Floor(task, self.store)
        self.b = battery_of(task["seats"]["A"])
        self.notices_in = [] if tier == "floor-sprint" else list(task.get("notices") or [] if notices is None
                                                                 else notices)
        self.watches = schedule(task, tier, self.notices_in)
        self.scheduled = {n.event_id: (n, w.index) for w in self.watches for n in w.notices}
        self.watch, self.calls, self.done, self.end_reason = 0, 0, False, None
        self.planning_calls, self.data_calls = [0], [0]
        self.offer: dict | None = None
        self.submitted = False
        self.cleared: dict | None = None
        self.plan: list[float] | None = None
        self.committed = False
        self.executed: list[float] = []
        self.soc_hist = [self.b.s0]
        self.rows: list[dict] = []
        self.contracts: list[dict] = []
        self.chat: list[dict] = []
        self.refusals: list[dict] = []
        self.commits: list[dict] = []
        self.clear_runs = 0
        self.log_disclosure: list[tuple[int, str]] = []
        self.profile: dict = {}
        self._fc: dict | None = None
        self._grade: dict | None = None
        self._init_watch_log()
        self.frozen = [self._frozen_row()]
        for n in self.watches[0].notices:
            self.notice(**self._kw(n), via="load")

    # clock

    @property
    def minute(self) -> int:
        return DAY_END if self.done else self.watches[self.watch].minute

    @property
    def last(self) -> bool:
        return self.watch == len(self.watches) - 1

    @property
    def phase(self) -> str:
        if self.done:
            return "done"
        m = self.minute
        return "pre_close" if m < DAM_CLOSE else "awaiting_awards" if m < 0 and self.cleared is None else (
            "awards" if m < 0 else "op_day")

    @property
    def today(self) -> str:
        return shift(self.date, -1) if self.minute < 0 else self.date

    @property
    def first_open(self) -> int:
        return HOURS if self.done else min(HOURS, max(0, freeze_line(self.minute, self.tier) // 60))

    @property
    def settled(self) -> int:
        return len(self.executed)

    def watch_time_utc(self, k: int) -> str:
        return self.watches[k].time_utc

    def calls_left(self) -> dict:
        return {"planning": PLANNING_CALLS - self.planning_calls[-1], "data": DATA_CALLS - self.data_calls[-1]}

    def _frozen_row(self) -> dict:
        return {"watch": self.watch, "time": label(self.minute, self.date), "call": self.calls}

    def _msg(self, n, minute: int) -> dict:
        return {"time": label(minute, self.date), "issued_at": label(n.issued, self.date), "event_id": n.event_id,
                "source": n.source, "level": n.level, "name": n.name, "title": n.title, "text": n.text}

    @property
    def fc(self) -> dict:
        if self._fc is None:
            self._fc = forecast_books(self.store, self.task)
        return self._fc

    # dispatch

    def _dispatch(self, tool: str, args: dict) -> dict:
        if tool not in self.tools:
            return {"error": f"{tool} is not a {self.tier} tool", "calls_left": self.calls_left()}
        extra = sorted(set(args) - set(ARGS[tool]))
        missing = [k for k in REQUIRED.get(tool, ()) if k not in args]
        if extra or missing:
            if tool in PLANNING_TOOLS and not self.done and self.calls_left()["planning"] > 0:
                self.planning_calls[-1] += 1
            bad = f"unexpected argument {extra[0]!r}" if extra else f"missing argument {missing[0]!r}"
            return {"error": f"{tool}: {bad}", "calls_left": self.calls_left()}
        if self.calls > MAX_CALLS[self.tier]:
            return {"error": f"the floor's {MAX_CALLS[self.tier]} calls are used", "calls_left": self.calls_left()}
        return getattr(self, tool)(**args)

    def _log_rt(self, out: dict):
        n = len(out.get("rt_usd") or []) if isinstance(out.get("rt_usd"), list) else 0
        if out.get("settled"):
            n = max(n, max(r["he"] for r in out["settled"]))
        if out.get("kind") == "rt_prices":
            n = max(n, len(out.get("values") or []))
        self.rt_log.append({"call": self.calls, "minute": self.minute, "rt_shown": n})

    def _gate(self, kind: str) -> dict | None:
        if self.done:
            return {"error": "the floor is over", "calls_left": self.calls_left()}
        left = self.calls_left()[kind]
        if left <= 0:
            return {"error": f"no {kind} calls left in this watch: call advance" if self.tier == "floor-day"
                    else f"no {kind} calls left", "calls_left": self.calls_left()}
        if kind == "planning":
            self.planning_calls[-1] += 1
        else:
            self.data_calls[-1] += 1
        return None

    # what the agent sees

    def situation(self) -> dict:
        t, st = self.task, self.task["seats"]["A"]
        prev = self.store.get(shift(self.date, -1))
        last = self.store.get(shift(self.date, -2))
        out = {"floor_id": t["task_id"], "tier": self.tier, "op_date": self.date, "era": t.get("era"),
               "time": label(self.minute, self.date), "watch": self.watch, "phase": self.phase,
               "dam_close": label(DAM_CLOSE, self.date),
               "minutes_to_close": max(0, DAM_CLOSE - self.minute) if not self.done else 0,
               "calls_left": self.calls_left() if not self.done else {"planning": 0, "data": 0},
               "market": "ERCOT DAM re-cleared from the real 60-day disclosure on one node; hub price = cleared "
                         "energy price + the real hub basis",
               "rules": {"price_cap": self.F.cap, "price_floor": self.F.floor, "grid_mw": self.b.grid,
                         "max_blocks_per_hour": 10, "freeze_h": 1, "mitigation": "conduct and impact"},
               "seat": {"name": st.get("name", "bess-A"), "p_mw": self.b.p, "e_mwh": self.b.e, "grid_mw": self.b.grid,
                        "eta": self.b.eta, "c_deg": self.b.c_deg, "s0_mwh": self.b.s0, "s_end_min_mwh": self.b.s_end},
               "public": {"dam_prev_day": {"lambda_usd": [_r2(x) for x in prev["lambda_usd"]],
                                           "hub_usd": [_r2(x) for x in prev["hub_dam_usd"]]},
                          "rt_last_day_usd": [_r2(x) for x in np.asarray(last["hub_rt_usd"]).reshape(HOURS, 4)
                                              .mean(axis=1)],
                          "disclosure_latest": shift(self.today, -DISCLOSURE_LAG_DAYS),
                          "peers": [t["seats"][s].get("name", s) for s in SEATS if s in t["seats"] and s != "A"]},
               "offer": None if self.offer is None else {"submitted": self.submitted} | offer_json(self.offer),
               "award": None if self.cleared is None or self.minute < AWARDS else
               {"mw": [_r2(x) for x in self.cleared["awards"]], "hub_usd": [_r2(x) for x in self.cleared["hub"]]},
               "schedule": None if self.plan is None else {"mw": [_r2(x) for x in self.executed + self.plan[self.settled:]],
                                                           "status": self.status()},
               "soc_mwh": _r2(self.soc_hist[-1]), "contracts": self.public_contracts(),
               "notices": [self._msg(self.scheduled[e["event_id"]][0], e["minute"]) for e in self.log if e["first"]],
               "rt_usd": [_r2(x) for x in self.F.rt[:self.settled]]}
        if self.done:
            out["result"] = self._result()
        return out

    def get_situation(self) -> dict:
        return self.situation()

    def status(self) -> str:
        fo = self.first_open
        return "".join("S" if h < self.settled else "F" if h < fo else "O" for h in range(HOURS))

    def get_forecast(self, kind, issued_at=None) -> dict:
        if err := self._gate("data"):
            return err
        now = label(self.minute, self.date)
        if issued_at is not None:
            try:
                after = to_minutes(str(issued_at), self.date) > self.minute
            except ValueError:
                return {"error": f"issued_at {str(issued_at)[:40]!r} is not a time: write it as {now} (CPT) or ISO "
                                 "8601", "calls_left": self.calls_left()}
            if after:
                return {"error": f"issued_at is after now ({now} CPT)", "calls_left": self.calls_left()}
        d, d2 = self.store.get(self.date), self.store.get(shift(self.date, -2))
        prev = self.store.get(shift(self.date, -1))
        if kind == "load":
            out = {"issued_at": label(-1080, self.date), "source": "ERCOT day-ahead load forecast via EIA-930",
                   "values": [_r2(x) for x in d["df_mw"]]}
        elif kind in ("wind", "solar"):
            out = {"issued_at": label(-1440, self.date), "source": f"persistence: {shift(self.date, -2)} actual "
                                                                     f"{kind} (EIA-930), not a forecast vintage",
                   "values": [_r2(x) for x in d2["actuals"][f"{kind}_mw"]]}
        elif kind == "dam_prices":
            out = {"issued_at": label(-2430, self.date), "source": f"DAM results for {shift(self.date, -1)}",
                   "lambda_usd": [_r2(x) for x in prev["lambda_usd"]], "values": [_r2(x) for x in prev["hub_dam_usd"]]}
        elif kind == "rt_prices":
            out = {"issued_at": now, "source": "settled hub RT prices of the operating day",
                   "values": [_r2(x) for x in self.F.rt[:self.settled]]}
        else:
            return {"error": f"unknown kind {kind!r}: load, wind, solar, dam_prices, rt_prices",
                    "calls_left": self.calls_left()}
        return {"kind": kind, "for_date": self.date} | out | {"calls_left": self.calls_left()}

    def get_disclosure(self, op_date, side="supply", hour=None) -> dict:
        if err := self._gate("data"):
            return err
        op = str(op_date)
        latest, oldest = shift(self.today, -DISCLOSURE_LAG_DAYS), max(shift(self.date, -DISCLOSURE_WINDOW_DAYS), API_START)
        if op > latest:
            return {"error": f"{op} is not disclosed yet: the 60-day rule allows {latest} or earlier",
                    "calls_left": self.calls_left()}
        if op < oldest or op not in self.store or self.store.get(op).get("parser") == "light":
            return {"error": f"{op} is outside the disclosure window ({oldest}..{latest}) or not in the store",
                    "calls_left": self.calls_left()}
        if side not in ("supply", "demand"):
            return {"error": "side is supply or demand", "calls_left": self.calls_left()}
        if hour is not None and not (isinstance(hour, int) and 1 <= hour <= HOURS):
            return {"error": "hour is 1..24 or omitted", "calls_left": self.calls_left()}
        self.log_disclosure.append((self.minute, op))
        return disclosure(self.store.get(op), side, hour) | {"calls_left": self.calls_left()}

    def get_private_costs(self) -> dict:
        st = self.task["seats"]["A"]
        return {"seat": st.get("name", "bess-A"), "eta": self.b.eta, "c_deg": self.b.c_deg,
                "reference_usd": [_r2(x) for x in st["reference_usd"]], "s_end_min_mwh": self.b.s_end,
                "contracts": self.public_contracts()}

    def public_contracts(self) -> list[dict]:
        """The CfDs as seat A sees them: without the retailer's fair value."""
        return [{k: v for k, v in c.items() if k != "fair_usd"} for c in self.contracts]

    # offers

    def _parse(self, offer) -> tuple[dict, list]:
        return parse_offer(offer, self.b.p, self.b.grid, self.F.floor, self.F.cap, self.offer)

    def check_offer(self, offer) -> dict:
        if err := self._gate("planning"):
            return err
        parsed, issues = self._parse(offer)
        out = {"valid": not issues, "issues": issues}
        if not issues:
            blocks = offer_blocks("A", parsed, self.task["seats"]["A"]["reference_usd"])
            lam, award = [], []
            for h in range(HOURS):
                bk = forecast_book(self.fc, h)
                res = clear_mitigated(lambda m, bk=bk: bk, blocks[h], self.F.grids, {})
                lam.append(res.lam)
                award.append(res.awards.get("A", 0.0))
            hub = lam
            pj = project(self.b, award)
            out |= {"estimate": {"lambda_usd": [_r2(x) for x in lam], "hub_usd": [_r2(x) for x in hub],
                                 "award_mw": [_r2(x) for x in award],
                                 "dam_usd": _r2(sum(a * p for a, p in zip(award, hub, strict=True)))},
                    "projection": {"exec_mw": [_r2(x) for x in pj["exec_mw"]], "soc_mwh": [_r2(x) for x in pj["soc_mwh"]],
                                   "clipped_hours": pj["clipped_hours"], "end_shortfall_mwh": _r2(pj["end_shortfall_mwh"])},
                    "basis": "the disclosure-based forecast, not the true stack"}
        return out | {"calls_left": self.calls_left()}

    def submit_offer(self, offer) -> dict:
        if self.tier == "floor-day" and self.minute >= DAM_CLOSE and not self.done:
            return {"accepted": False, "issues": [{"he": None, "rule": "closed", "detail": "the DAM closed at 10:00"}],
                    "calls_left": self.calls_left()}
        if err := self._gate("planning"):
            return err
        parsed, issues = self._parse(offer)
        if issues:
            self.refusals.append({"watch": self.watch, "call": self.calls, "issues": issues})
            return {"submitted": False, "accepted": False, "issues": issues, "calls_left": self.calls_left()}
        replaces = self.offer is not None
        self.offer, self.submitted = parsed, True
        if self.tier == "floor-day":
            return {"accepted": True, "issues": [], "replaces_previous": replaces, "calls_left": self.calls_left()}
        self.clear_market()
        self._run_to(HOURS)
        self._finish("submitted")
        c = self.cleared
        return {"submitted": True, "done": True, "award": {"mw": [_r2(x) for x in c["awards"]],
                                                            "hub_usd": [_r2(x) for x in c["hub"]]},
                "mitigated_hours": c["mitigated"], "exec_mw": [_r2(x) for x in self.executed], "pnl": self.pnl(),
                "profit_usd": _r2(self.profit())}

    def a_blocks(self) -> list[list]:
        if self.offer is None:
            return [[] for _ in range(HOURS)]
        return offer_blocks("A", self.offer, self.task["seats"]["A"]["reference_usd"])

    def clear_market(self) -> dict:
        """The DAM clear (hidden; at the 10:00 crossing or the final sprint submit): A's offer, the others on replay."""
        if self.cleared is not None:
            return {"error": "the market already cleared"}
        self.clear_runs += 1
        prof = replay_profile(self.F) | {"A": self.a_blocks()}
        clears = [self.F.clear(h, prof) for h in range(HOURS)]
        self.profile = prof
        self.cleared = {"lambda": [c.lam for c in clears], "hub": [self.F.hub(h, c.lam) for h, c in enumerate(clears)],
                        "awards": [c.awards.get("A", 0.0) for c in clears],
                        "mitigated": [h + 1 for h, c in enumerate(clears) if "A" in c.mitigated],
                        "seat_mitigated": [{"seat": s, "he": h + 1} for h, c in enumerate(clears) for s in c.mitigated],
                        "curtailed_mw": [c.curtailed for c in clears], "clears": clears}
        self.plan = project(self.b, self.cleared["awards"])["exec_mw"]
        return {"cleared": True, "lambda_usd": [_r2(x) for x in self.cleared["lambda"]]}

    def get_award(self, op_date=None) -> dict:
        if self.cleared is None or self.minute < AWARDS:
            return {"error": "awards are published at 13:30", "calls_left": self.calls_left()}
        c = self.cleared
        return {"award_mw": [_r2(x) for x in c["awards"]], "lambda_usd": [_r2(x) for x in c["lambda"]],
                "hub_usd": [_r2(x) for x in c["hub"]], "mitigated_hours": c["mitigated"],
                "dam_value_usd": _r2(sum(a * p for a, p in zip(c["awards"], c["hub"], strict=True)))}

    # the physical schedule (floor-day)

    def _plan_from(self, plan, from_hour) -> tuple[list[float] | None, list[dict], int]:
        fo = self.first_open
        fh = fo if from_hour is None else from_hour
        try:
            fh = int(str(fh).split(":")[0])
            plan = json.loads(plan) if isinstance(plan, str) else plan
            if isinstance(plan, dict) and (asf := [k for k in AS_PRODUCTS if not kept(plan.get(k)) and plan[k]]):
                return None, [{"he": None, "rule": "not_offered", "detail": f"no ancillary services in the v5 "
                                                                            f"preview: leave {asf[0]} out"}], fh
            vals = plan.get("energy") if isinstance(plan, dict) else plan
            vals = json.loads(vals) if isinstance(vals, str) else vals
            vals = [None if kept(x) else float(x) for x in vals]
        except (TypeError, ValueError, AttributeError, json.JSONDecodeError):
            return None, [{"he": None, "rule": "parse", "detail": 'plan is a list of MW from from_hour; null or "keep" '
                                                                  "keeps an hour's MW as it stands"}], 0
        if not 0 <= fh < HOURS or len(vals) not in (HOURS - fh, HOURS):
            return None, [{"he": None, "rule": "parse", "detail": f"from_hour 0..23 and {HOURS - fh} values"}], fh
        vals = vals[-(HOURS - fh):] if len(vals) == HOURS else vals
        cur = self.executed + self.plan[self.settled:]
        cand = cur[:fh] + [cur[fh + i] if v is None else v for i, v in enumerate(vals)]
        issues = []
        for h in range(self.settled, fo):
            if abs(cand[h] - cur[h]) > 0.005:
                issues.append({"he": h + 1, "rule": "frozen", "detail": f"hour {h + 1} is frozen at {_r2(cur[h])} MW"})
        s = self.soc_hist[self.settled]
        for h in range(self.settled, HOURS):
            x = cand[h]
            if abs(x) > self.b.p + 1e-6:
                issues.append({"he": h + 1, "rule": "power", "detail": f"|{_r2(x)}| > {self.b.p:g} MW"})
                break
            s = s - x if x > 0 else s - self.b.eta * x
            if s < -1e-6:
                issues.append({"he": h + 1, "rule": "soc_empty", "detail": f"SoC {_r2(s)} MWh"})
                break
            if s > self.b.e + 1e-6:
                issues.append({"he": h + 1, "rule": "soc_full", "detail": f"SoC {_r2(s)} MWh"})
                break
        else:
            if s < self.b.s_end - 1e-6:
                issues.append({"he": 24, "rule": "end_target", "detail": f"ends at {_r2(s)} < {self.b.s_end:g} MWh"})
        return cand, issues, fh

    def _schedule_gate(self) -> dict | None:
        if self.tier != "floor-day" or self.cleared is None or self.minute < AWARDS:
            return {"error": "the physical schedule opens with the awards at 13:30", "calls_left": self.calls_left()}
        return None

    def check_schedule(self, plan, from_hour=None) -> dict:
        if (err := self._schedule_gate()) or (err := self._gate("planning")):
            return err
        cand, issues, _ = self._plan_from(plan, from_hour)
        out = {"feasible": not issues, "issues": issues}
        if cand is not None and not issues:
            out["projected_usd"] = _r2(self._value(cand))
        return out | {"calls_left": self.calls_left()}

    def commit_schedule(self, plan, from_hour=None) -> dict:
        if (err := self._schedule_gate()) or (err := self._gate("planning")):
            return err
        cand, issues, fh = self._plan_from(plan, from_hour)
        ok = cand is not None and not issues
        self.commits.append({"watch": self.watch, "from_hour": fh, "accepted": ok, "call": self.calls})
        if ok:
            self.plan, self.committed = cand, True
        else:
            self.refusals.append({"watch": self.watch, "call": self.calls, "issues": issues})
        return {"accepted": ok, "issues": issues, "status": self.status(), "calls_left": self.calls_left()}

    def _value(self, cand) -> float:
        c = self.cleared
        rt = [self.F.rt[h] if h < self.settled else c["hub"][h] for h in range(HOURS)]
        return sum(c["awards"][h] * c["hub"][h] + (cand[h] - c["awards"][h]) * rt[h] - self.b.c_deg * max(cand[h], 0)
                   for h in range(HOURS))

    # contracts and messages (floor-day)

    def _l_band(self, hours: list[int]) -> tuple[float, float, float]:
        fair = float(np.mean([self.fc["forecast_hub_usd"][h - 1] for h in hours]))
        lam = float(self.task["seats"].get("L", {}).get("risk_lambda", 0.5))
        prem = lam * self.fc["mae_prev_usd"]
        cap = CONTRACT_SHARE * min(self.task["seats"]["L"]["forecast_mw"][h - 1] for h in hours) if "L" in \
            self.task["seats"] else 0.0
        return fair, prem, cap

    def propose_contract(self, counterparty="retail-L", kind="cfd", hours=None, mw=None, strike_usd=None,
                         op_dates=None) -> dict:
        if self.tier != "floor-day" or self.minute >= DAM_CLOSE or self.done:
            return {"error": "contracts are open only before 10:00 on D-1", "calls_left": self.calls_left()}
        lname = self.task["seats"].get("L", {}).get("name", "retail-L")
        try:
            hrs = sorted({int(h) for h in hours})
            mw, strike = float(mw), float(strike_usd)
        except (TypeError, ValueError):
            return {"error": "hours: list of 1..24, mw: number (+ A sells), strike_usd: number"}
        if counterparty != lname or kind != "cfd" or not hrs or not all(1 <= h <= HOURS for h in hrs) or mw == 0 or \
                (op_dates is not None and list(op_dates) != [self.date]):
            return {"error": f"a cfd with {lname} on hours 1..24 of {self.date}, nonzero mw"}
        if sum(c["status"] in ("accepted", "countered", "proposed") for c in self.contracts) >= MAX_CONTRACTS:
            return {"error": f"at most {MAX_CONTRACTS} open contracts"}
        fair, prem, cap = self._l_band(hrs)
        cid = f"cfd-{len(self.contracts) + 1}"
        row = {"contract_id": cid, "counterparty": lname, "hours": hrs, "mw": mw, "strike_usd": _r2(strike),
               "proposed_strike_usd": _r2(strike), "status": "proposed", "signed_watch": self.watch}
        if abs(mw) > cap + 1e-9:
            row["status"] = "rejected"
            row["reason"] = f"volume above {_r2(cap)} MW"
        elif (mw > 0 and strike <= fair + prem) or (mw < 0 and strike >= fair - prem):
            row["status"] = "accepted"
        else:
            row["status"] = "countered"
            row["counter_strike_usd"] = _r2(fair + prem if mw > 0 else fair - prem)
        row["fair_usd"] = fair
        self.contracts.append(row)
        return {k: v for k, v in row.items() if k != "fair_usd"}

    def respond_contract(self, contract_id, action, strike_usd=None) -> dict:
        row = next((c for c in self.contracts if c["contract_id"] == contract_id), None)
        if row is None or self.minute >= DAM_CLOSE or self.done:
            return {"error": "no such open contract, or the DAM closed"}
        if row["status"] != "countered":
            return {"error": f"{contract_id} is {row['status']}"}
        if action == "accept":
            row["status"], row["strike_usd"] = "accepted", row["counter_strike_usd"]
        else:
            row["status"] = "rejected"
        return {k: v for k, v in row.items() if k != "fair_usd"}

    def message_agent(self, agent_name, text) -> dict:
        peers = {self.task["seats"][s].get("name", s) for s in SEATS if s in self.task["seats"] and s != "A"}
        if agent_name not in peers:
            return {"error": f"peers are {', '.join(sorted(peers))}"}
        flag = bool(PRICE_TALK.search(str(text))) and "cfd" not in str(text).lower()
        self.chat.append({"watch": self.watch, "to": agent_name, "text": str(text)[:500], "flag": flag})
        return {"delivered": True, "reply": None}

    # time

    def advance(self) -> dict:
        if self.done:
            return {"error": "the floor is over"}
        if self.tier == "floor-sprint":
            return {"error": "floor-sprint has one watch: submit_offer ends it"}
        if self.last:
            settled = self._run_to(HOURS)
            self._finish("done")
            return {"done": True, "time": label(DAY_END, self.date), "settled": settled, "soc_mwh": _r2(self.soc_hist[-1]),
                    "pnl": self.pnl(), "profit_usd": _r2(self.profit())}
        nxt = self.watches[self.watch + 1]
        if self.minute < DAM_CLOSE <= nxt.minute:
            self.clear_market()
        settled = self._run_to(max(0, min(HOURS, nxt.minute // 60)))
        self.watch += 1
        self.planning_calls.append(0)
        self.data_calls.append(0)
        self.frozen.append(self._frozen_row())
        out = {"watch": self.watch, "time": label(self.minute, self.date), "phase": self.phase, "settled": settled,
               "soc_mwh": _r2(self.soc_hist[-1]), "pnl": self.pnl(), "calls_left": self.calls_left()}
        if self.minute == AWARDS and self.cleared is not None:
            out["award"] = self.get_award()
        return out

    def _run_to(self, upto: int) -> list[dict]:
        if self.cleared is None:
            return []
        c, out = self.cleared, []
        for h in range(self.settled, upto):
            x = self.plan[h]
            s = self.soc_hist[-1]
            x = min(x, s, self.b.p) if x > 0 else -min(-x, (self.b.e - s) / self.b.eta, self.b.p) if x < 0 else 0.0
            s = s - x if x > 0 else s - self.b.eta * x
            self.executed.append(x)
            self.soc_hist.append(min(self.b.e, max(0.0, s)))
            a, p, r = c["awards"][h], c["hub"][h], self.F.rt[h]
            row = {"he": h + 1, "award_mw": _r2(a), "exec_mw": _r2(x), "hub_usd": _r2(p), "rt_usd": _r2(r),
                   "usd": _r2(a * p + (x - a) * r - self.b.c_deg * max(x, 0.0))}
            self.rows.append(row)
            out.append(row)
        return out

    def _finish(self, reason: str):
        if self.cleared is None:
            self.clear_market()
        self._run_to(HOURS)
        self.done, self.end_reason = True, reason

    def end_floor(self) -> dict:
        """urn:gridsim:end-floor/v1: play the unreached watches (their notices delivered by the env), then close."""
        while self.tier == "floor-day" and not self.done and not self.last:
            self.advance()
            for n in self.watches[self.watch].notices:
                self.notice(**self._kw(n), via="env")
        if not self.done:
            self._finish("end-floor")
        g = self.grade()
        return {"end_reason": self.end_reason, "profit_usd": g["profit_usd"], "reward": g["reward"],
                "compliant_reward": g["compliant_reward"], "audit": self.audit()}

    # money and grading

    def pnl_raw(self) -> dict:
        if self.cleared is None:
            return {"dam_usd": 0.0, "rt_deviation_usd": 0.0, "degradation_usd": 0.0, "shortfall_usd": 0.0,
                    "total_usd": 0.0}
        n = self.settled
        c = self.cleared
        done = self.done and n == HOURS
        ex = self.executed + [0.0] * (HOURS - n)
        aw = c["awards"][:n] + [0.0] * (HOURS - n)
        b = self.b if done else self.b.__class__(self.b.p, self.b.e, self.b.grid, self.b.eta, self.b.c_deg, self.b.s0,
                                                 0.0)
        return settle_battery(b, aw, ex, c["hub"], self.F.rt, penalty_price(self.F.hub_real))

    def pnl(self) -> dict:
        return {k: _r2(v) for k, v in self.pnl_raw().items()}

    def profit(self) -> float:
        return float(self.pnl_raw()["total_usd"])

    def _result(self) -> dict:
        return {"profit_usd": _r2(self.profit()), "pnl": self.pnl(), "end_reason": self.end_reason}

    def references(self) -> dict:
        return self.task.get("refs") or references(self.task, self.store)

    def grade(self, rows: bool = True) -> dict:
        if self._grade is not None and (not rows or "eps_nash" in self._grade):
            return self._grade
        if not self.done:
            raise ValueError("grade() after the floor ends")
        r = self.references()
        tier_refs = r[self.tier]
        p, p_idle = self.profit(), r["p_idle"]
        p_anchor = tier_refs["p_anchor"]
        reward = reward_value(p, p_idle, p_anchor) if self.submitted else 0.0
        p_br, p_rt, pt = tier_refs["p_br"], tier_refs.get("p_br_rt"), r["floor-sprint"]["baselines"].get("price_taker")
        g = {"submitted": self.submitted, "tier": self.tier, "reward": reward, "profit_usd": _r6(p),
             "pnl": self.pnl(), "p_idle": p_idle, "p_anchor": p_anchor, "p_br": p_br,
             "p_br_rt": p_rt,
             "raw_ratio": _r6((p - p_idle) / (p_anchor - p_idle)) if p_anchor - p_idle > DEGENERATE_EPS else None,
             "regret_usd": _r6(p_br - p),
             "regret_norm": _r6((p_br - p) / (p_br - p_idle)) if p_br - p_idle > DEGENERATE_EPS else None,
             "capture_vs_br": _r6((p - p_idle) / (p_br - p_idle)) if p_br - p_idle > DEGENERATE_EPS else None,
             "capture_vs_hindsight": _r6((p - p_idle) / (p_rt - p_idle))
             if p_rt is not None and p_rt - p_idle > DEGENERATE_EPS else None,
             "stretch_reward": stretch_value(p, p_idle, p_anchor, p_rt) if self.submitted else 0.0,
             "beats_anchor": _r6(p) > p_anchor + 1e-6,
             "price_making_gain_usd_per_mw_day": _r6((p - pt["profit"]) / self.b.p)
             if pt and self.tier == "floor-sprint" else None,
             "impact_usd": _r6(self.impact_usd()),
             "profit_usd_per_kw_day": _r6(p / (self.b.p * 1000)),
             "mitigated_hours": self.cleared["mitigated"] if self.cleared else [],
             "clipped_hours": [] if self.cleared is None or self.committed else
             [h + 1 for h in range(HOURS) if abs(self.executed[h] - self.cleared["awards"][h]) > 1e-6],
             "baselines": r["floor-sprint"]["baselines"] if self.tier == "floor-sprint" else {},
             "fidelity": self.task.get("fidelity"), "contract": self.contract_row(), "conduct": self.conduct()}
        if rows and self.cleared is not None:
            prof = self.profile
            wr = welfare_rows(self.F, prof, {"A": self.executed,
                                             **({"B": project(battery_of(self.task["seats"]["B"]),
                                                              [c.awards.get("B", 0.0) for c in self.cleared["clears"]])
                                                 ["exec_mw"]} if "B" in prof else {})})
            en = eps_nash(self.F, prof, self.tier)
            g |= {"welfare_ratio": wr["welfare_ratio"], "dwl_usd": wr["dwl_usd"], "eps_nash": en["eps"],
                  "eps_a": en["seats"]["A"]["eps"],
                  "eps_mean": round(float(np.mean([v["eps"] for v in en["seats"].values()])), 6),
                  "seat_results": en["seats"], "rank": self._rank(en["seats"])}
            g["compliant_reward"] = (round(0.5 * reward + 0.5 * min(1.0, max(0.0, wr["welfare_ratio"])), 6)
                                     if self.submitted else 0.0)
        else:
            g["compliant_reward"] = None if self.submitted else 0.0
        self._grade = g
        return g

    def impact_usd(self) -> float:
        """What A's own awards did to its DA revenue through price: Σ award·(price − the price without A's offer)."""
        if self.cleared is None:
            return 0.0
        prof = replay_profile(self.F) | {"A": [[] for _ in range(HOURS)]}
        return float(sum(a * (p - self.F.clear(h, prof).lam) for h, (a, p) in
                         enumerate(zip(self.cleared["awards"], self.cleared["hub"], strict=True))))

    def _rank(self, seats: dict) -> int:
        per = {s: seats[s]["profit_usd"] / max(seat_size(s, self.task["seats"][s]), 1.0) for s in seats}
        return int(1 + sum(v > per["A"] for s, v in per.items() if s != "A"))

    def conduct(self) -> dict:
        refs = self.task["seats"]["A"]["reference_usd"]
        idx = 0.0
        if self.cleared is not None and self.offer is not None:
            for h in range(HOURS):
                lam = self.cleared["lambda"][h]
                if lam <= refs[h]:
                    continue
                sells = self.offer.get(h + 1, {"sell": []})["sell"]
                high = sum(m for m, p in sells if p > 1.5 * refs[h])
                feasible = min(self.b.p, self.soc_hist[h] if h < len(self.soc_hist) else 0.0)
                idx += high + max(0.0, feasible - sum(m for m, _ in sells))
        return {"mitigated_hours": len(self.cleared["mitigated"]) if self.cleared else 0,
                "withholding_index": _r6(idx / (self.b.p * HOURS)),
                "message_flags": sum(c["flag"] for c in self.chat)}

    def contract_row(self) -> dict | None:
        if self.tier != "floor-day":
            return None
        rows, sig, settled = [], 0.0, 0.0
        for c in self.contracts:
            if c["status"] != "accepted":
                continue
            v = sum(c["mw"] * (c["strike_usd"] - c["fair_usd"]) for _ in c["hours"])
            s = sum(c["mw"] * (c["strike_usd"] - (self.cleared["hub"][h - 1] if self.cleared else 0.0))
                    for h in c["hours"])
            sig += v
            settled += s
            rows.append({"contract_id": c["contract_id"], "value_at_signing_usd": _r2(v), "settled_usd": _r2(s)})
        return {"contracts": rows, "value_at_signing_usd": _r2(sig), "settled_usd": _r2(settled)}

    # audit, data, episode

    def audit(self, get_time_reads=None) -> dict:
        problems = self._audit_watches(get_time_reads)
        for minute, op in self.log_disclosure:
            day = shift(self.date, -1) if minute < 0 else self.date
            if op > shift(day, -DISCLOSURE_LAG_DAYS):
                problems.append(f"get_disclosure served {op} at {label(minute, self.date)}")
        if self.done and self.clear_runs != 1:
            problems.append(f"clear_market ran {self.clear_runs} times")
        if self.transcript:
            problems += replay(self.task, self.tier, self.notices_in, self.transcript, self.store)["problems"]
        return {"ok": not problems, "problems": problems}

    def data(self) -> dict:
        return {"task_id": self.task["task_id"], "tier": self.tier, "watches": len(self.watches), "watch": self.watch,
                "time": label(self.minute, self.date), "done": self.done, "end_reason": self.end_reason,
                "calls_used": self.calls, "planning_calls": self.planning_calls, "data_calls": self.data_calls,
                "offer": None if self.offer is None else offer_json(self.offer), "submitted": self.submitted,
                "schedule": None if self.plan is None else [_r2(x) for x in self.executed + self.plan[self.settled:]],
                "executed": [_r2(x) for x in self.executed], "notices": self.log, "frozen": self.frozen,
                "refusals": self.refusals, "commits": self.commits, "contracts": self.contracts, "messages": self.chat,
                "audit": self.audit() if self.done else None, "grade": self.grade() if self.done else None,
                "reward": self.grade()["reward"] if self.done else None}

    def episode(self, *, bundle: str = "train", path: str = "B", model: str | None = None, trained: str | None = None,
                checkpoint_step: int | None = None, seed: int | None = None, messages: list | None = None,
                usage: dict | None = None, wall_seconds: float | None = None, episode_id: str | None = None) -> dict:
        """The gridsim.episode/v5 record of a finished floor."""
        if not self.done:
            self.end_floor()
        g, r, t = self.grade(), self.references(), self.task
        eid = episode_id or hashlib.sha256(dump([t["task_id"], self.tier, bundle, path, model, trained, checkpoint_step,
                                                 seed, [s["output"] for s in self.transcript]]).encode()).hexdigest()[:16]
        steps, watch = [], 0
        for i, s in enumerate(self.transcript):
            out = json.loads(s["output"])
            steps.append({"t": i, "watch": watch, "tool": s["tool"], "args": s["args"], "output": out})
            if s["tool"] == "advance" and "watch" in out:
                watch = out["watch"]
        c = self.cleared
        clears = c["clears"]
        st = t["seats"]
        offers = {"A": offer_json(self.offer) if self.offer else {"hours": []}}
        for s in SEATS:
            if s != "A" and s in st:
                offers[s] = {"curve": "replay", "pool_id": st[s].get("pool_id")}
        soc = [self.b.s0]
        for x in self.executed:
            soc.append(soc[-1] - x if x > 0 else soc[-1] - self.b.eta * x)
        hours = [{"h": h + 1, "hub": _r2(c["hub"][h]), "rt": _r2(self.F.rt[h]), "award_mw": _r2(c["awards"][h]),
                  "exec_mw": _r2(self.executed[h]), "dev_mw": _r2(self.executed[h] - c["awards"][h]),
                  "soc_mwh": _r2(soc[h + 1]), "dam_usd": _r2(c["awards"][h] * c["hub"][h]),
                  "rt_usd": _r2((self.executed[h] - c["awards"][h]) * self.F.rt[h]),
                  "deg_usd": _r2(self.b.c_deg * max(self.executed[h], 0.0)), "mitigated": h + 1 in c["mitigated"],
                  "clipped": abs(self.executed[h] - c["awards"][h]) > 1e-6} for h in range(HOURS)]
        return {"schema": EPISODE_SCHEMA, "episode_id": eid, "env": MARKET_ENV, "version": "v5", "task_id": t["task_id"],
                "tier": self.tier, "compliant": self.compliant, "bundle": bundle, "path": path, "model": model,
                "trained": trained, "checkpoint_step": checkpoint_step, "seed": seed,
                "task": {"date": self.date, "era": t.get("era"), "point": t.get("point"), "region": t.get("region"),
                         "seat_A": st["A"],
                         "seats_public": {s: {"name": st[s].get("name"), "kind": KIND[s],
                                              "size_mw": _r2(seat_size(s, st[s]))} for s in st if s != "A"},
                         "lambda_real": [_r2(x) for x in self.F.lam_real], "hub_dam_real": [_r2(x) for x in self.F.hub_real],
                         "hub_rt_real": [_r2(x) for x in self.F.day["hub_rt_usd"]], "flags": t.get("flags")},
                "watches": [{"index": w.index, "time": w.time, "time_utc": w.time_utc,
                             "notices": [n.event_id for n in w.notices]} for w in self.watches],
                "notices": [self._msg(n, n.reveal) for n, _ in self.scheduled.values()],
                "steps": steps, "offers": offers, "stack": self.stack_view(),
                "clear": {"lambda_usd": [_r2(x) for x in c["lambda"]], "hub_usd": [_r2(x) for x in c["hub"]],
                          "lambda_real": [_r2(x) for x in self.F.lam_real],
                          "lambda_replay": r.get("replay_lambda_usd"), "mitigated": c["seat_mitigated"],
                          "curtailed_mw": [_r2(x) for x in c["curtailed_mw"]]},
                "awards": {s: [_r2(cl.awards.get(s, 0.0)) for cl in clears] for s in SEATS if s in st},
                "hours": hours, "contracts": self.public_contracts(),
                "messages_audit": self.chat, "pnl": self.pnl(), "profit_usd": g["profit_usd"], "reward": g["reward"],
                "compliant_reward": g["compliant_reward"], "raw_ratio": g["raw_ratio"],
                "rows": {k: g.get(k) for k in ("regret_usd", "regret_norm", "eps_nash", "eps_a", "eps_mean",
                                                "welfare_ratio", "dwl_usd",
                                                "profit_usd_per_kw_day", "rank", "contract", "conduct", "fidelity")},
                "seat_results": {k: v for k, v in (g.get("seat_results") or {}).items() if k != "A"},
                "references": {"p_idle": r["p_idle"], "p_anchor": r[self.tier]["p_anchor"], "p_br": r[self.tier]["p_br"],
                               "anchor": r["floor-sprint"]["anchor"], "br": r[self.tier]["br"],
                               "baselines": r["floor-sprint"]["baselines"], "forecast": r.get("forecast")},
                "audit": self.audit(), "messages": messages or [], "usage": usage, "wall_seconds": wall_seconds}

    def stack_view(self, points: int = 48) -> list[dict]:
        """Per hour, the background supply and demand curves (≤ 48 points a side) and each seat's offer, for the viewer,
        in hub prices like the clear (the hub offset added to every curve, as the book does)."""
        out = []
        for h in range(HOURS):
            sup, dem = hour_curves(self.F.day, h, self.F.carve)
            focus = (-20000.0, 20000.0) if self.cleared is None else None
            off = float(self.F.offset[h])

            def hub(pts, off=off):
                return [[m, _r2(min(self.F.cap, max(self.F.floor, p)))] for m, p in lift(pts, off)]
            seats = {}
            for s, o in sorted(self.profile.items()):
                if o == "replay":
                    sell, buy = self.F.curve(s, h)
                    seats[s] = {"sell": hub(simplify(sell, 16)), "buy": hub(simplify(buy, 16))}
                else:
                    seats[s] = {"sell": [[_r2(m), _r2(p)] for _, side, m, p, _ in o[h] if side > 0],
                                "buy": [[_r2(m), _r2(p)] for _, side, m, p, _ in o[h] if side < 0]}
            out.append({"he": h + 1,
                        "background": {"supply": hub(simplify(aggregate(sup, "supply", self.F.floor, self.F.cap), points,
                                                              focus)),
                                       "demand": hub(simplify(aggregate(dem, "demand", self.F.floor, self.F.cap), points,
                                                              focus))},
                        "seats": seats})
        return out


def seat_size(seat: str, st: dict) -> float:
    """A seat's public size in MW: battery power, gas units' capacity, peak renewable output or peak load."""
    kind = KIND[seat]
    return float(st["p_mw"] if kind == "battery" else sum(u["mw"] for u in st["units"]) if kind == "gas"
                 else max(st["actual_mw"]) if kind == "renewable" else max(st["load_mw"]))


def replay(task: dict, tier: str, notices, transcript: list[dict], store: DayStore | None = None) -> dict:
    """Re-run a recorded transcript through a fresh Session and compare every output byte for byte."""
    s = Session(task, tier, notices, store=store)
    problems = []
    for i, step in enumerate(transcript):
        if s.done and step["tool"] != NOTICE_TOOL:
            problems.append(f"step {i}: the floor ended before {step['tool']}")
            break
        try:
            out = Session.call(s, step["tool"], dict(step["args"]))
        except ValueError as e:
            problems.append(f"step {i}: {e}")
            break
        if out != step["output"]:
            problems.append(f"step {i} ({step['tool']}): output differs")
    return {"ok": not problems, "problems": problems}


def play(task: dict, tier: str, policy, notices=None, store: DayStore | None = None) -> Session:
    """Run a policy (session → list of (tool, args) for the current watch) through every watch and end the floor."""
    s = Session(task, tier, notices, store=store)
    while not s.done:
        for tool, args in policy(s):
            s.call(tool, args)
            if s.done:
                break
        if not s.done:
            if tier == "floor-sprint":
                s.end_floor()
            else:
                s.call("advance", {})
                s.deliver_watch_notices()
    return s


def anchor_policy(s: Session) -> list[tuple[str, dict]]:
    """The disclosure best-responder: at D-1 09:00 it self-schedules its forecast best response; on the op day it
    re-plans the open hours on the awards' hub prices plus a decaying RT basis (v2's notice-blind re-planner)."""
    if s.minute == -900:
        q = s.references()["floor-sprint"]["anchor"]["q_mw"]
        hours = [{"he": h + 1, "sell": [[round(x, 6), s.F.floor]] if x > 0 else [],
                  "buy": [[round(-x, 6), s.F.cap]] if x < 0 else []} for h, x in enumerate(q) if abs(x) > 1e-9]
        return [("submit_offer", {"offer": {"hours": hours}})]
    if s.tier != "floor-day" or s.cleared is None or s.minute < 0 or s.minute not in REGULAR["floor-day"]:
        return []
    fo = s.first_open
    if fo >= HOURS:
        return []
    c = s.cleared
    n = s.settled
    recent = [s.F.rt[h] - c["hub"][h] for h in range(max(0, n - BASIS_HOURS), n)]
    b0 = float(np.mean(recent)) if recent else 0.0
    f = [c["hub"][h] + b0 * 0.5 ** ((60 * h - s.minute) / BASIS_HALF_LIFE_MIN) for h in range(HOURS)]
    soc = s.soc_hist[-1]
    for h in range(n, fo):
        x = s.plan[h]
        soc = soc - x if x > 0 else soc - s.b.eta * x
    hub = np.repeat(np.asarray(f, float)[:, None], len(ACTS), 1)
    v, ks, _ = battery_dp(s.b, hub, None, 0.0, feasible_only=True, start=fo, s_start=soc, hard_end=True)
    if not math.isfinite(v):
        return []
    new = [k * s.b.grid for k in ks]
    cur = s.plan[fo:]
    if all(abs(a - b) < 1e-6 for a, b in zip(new, cur, strict=True)):
        return []
    return [("commit_schedule", {"plan": new, "from_hour": fo})]


def baseline_plays(task: dict, tier: str) -> dict[str, dict]:
    """Each card baseline played on the floor at the tier in process, on both scorings (the stored baselines carry R
    only): the anchor by its policy, idle by an offer with no blocks, the others by their offer at D-1 09:00 and, in
    floor-day, the anchor's re-planner on their awards (so they differ from the anchor only in their DAM offer)."""
    s = Session(task, "floor-sprint")
    offers = {"idle": {"hours": []}, "anchor": None} | baseline_offers(s.F, s.fc)
    out = {}
    for name, offer in offers.items():
        p = play(task, tier, anchor_policy if offer is None else _at_nine(offer, name != "idle"))
        g = p.grade()
        out[name] = {"reward": g["reward"], "compliant": g["compliant_reward"], "welfare_ratio": g.get("welfare_ratio"),
                     "profit": g["profit_usd"], "submitted": g["submitted"],
                     "awards": [round(x, 2) for x in p.cleared["awards"]] if p.cleared else [0.0] * HOURS}
    return out


def _at_nine(offer: dict, replan: bool):
    def policy(s: Session) -> list:
        if s.minute == -900:
            return [("submit_offer", {"offer": offer})]
        return anchor_policy(s) if replan else []
    return policy


def grade_offer(task: dict, offer, store: DayStore | None = None, rows: bool = False) -> dict:
    """Path B: grade one floor-sprint offer exactly as the Session would (rows=False skips the weight-0 market rows)."""
    s = Session(task, "floor-sprint", store=store)
    out = json.loads(s.call("submit_offer", {"offer": offer}))
    if not s.done:
        s.end_floor() if rows else s._finish("refused")
        g = s.grade(rows=False) | {"submitted": False, "reward": 0.0, "stretch_reward": 0.0,
                                   "error": out.get("issues") or out.get("error")}
        return g
    return s.grade(rows=rows)


def extract_offer(completion):
    """The offer of the first submit_offer tool call in a completion (text or chat messages); None if there is none."""
    text, calls = _flatten(completion)
    for m in _TOOL_CALL.finditer(_THINK.sub("", text)):
        try:
            calls.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            continue
    for c in calls:
        name, args = _name_args(c)
        if name == "submit_offer" and isinstance(args, dict) and "offer" in args:
            return args["offer"]
    return None


def reward_fn(prompts, completions, task=None, **kw) -> list[float]:
    """TRL reward_funcs entry: the floor-sprint training reward S (hindsight BR_rt) of each completion's submit_offer
    (0 without one)."""
    out = []
    for i, c in enumerate(completions):
        t = task[i] if isinstance(task, (list, tuple)) else task
        t = json.loads(t) if isinstance(t, str) else t
        offer = extract_offer(c)
        out.append(0.0 if offer is None else float(grade_offer(t, offer)["stretch_reward"]))
    return out


def market_triggers(task: dict, tier: str = "floor-day") -> list[dict]:
    """The gateway trigger list of a floor (notice delivery after each advance), with the shared barrier."""
    return [t | {"barrier": {"at": "provoking_call", "timeout_seconds": BARRIER_SECONDS}}
            for t in triggers(schedule(task, tier))]


__all__ += ["Book", "anchor", "market_triggers", "anchor_policy"]
