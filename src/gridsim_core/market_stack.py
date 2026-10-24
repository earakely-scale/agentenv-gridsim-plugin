"""GridSimEnv v5 inputs: the days store (one row per API-era operating day), curve aggregation and simplification, the
60-day disclosure the agent reads, and the NP3-966-ER parser that builds days rows from ERCOT's 60-Day DAM Disclosure."""

from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import zipfile
from functools import cache
from pathlib import Path

import numpy as np

from gridsim_core.market_auction import (
    FINE_GRID,
    HOURS,
    NUDGE,
    RENEWABLE_REF,
    SEATS,
    Clear,
    at,
    book,
    capped,
    clear_mitigated,
    demand_xy,
    limits,
    supply_xy,
)
from gridsim_core.task import data_root

FIXTURE_PACK = "fixtures-market"
DISCLOSURE_LAG_DAYS = 60
DISCLOSURE_WINDOW_DAYS = 90
API_START = "2023-12-11"
DISCLOSURE_POINTS, DISCLOSURE_POINTS_DAY, SEAT_POINTS = 64, 16, 16


def shift(date: str, days: int) -> str:
    return (dt.date.fromisoformat(date) + dt.timedelta(days=days)).isoformat()


class DayStore:
    """Days rows by date from jsonl(.gz) files or directories of them (data/market/days, fixture days); a later source
    wins a date. A directory's month files (YYYY-MM.jsonl.gz) are read when a date of their month is first asked for,
    so a floor holds the few months it reads, not the whole store; ``rows`` reads every pending file."""

    def __init__(self, *sources):
        self._rows: dict[str, dict] = {}
        self.rank: dict[str, int] = {}
        self.pending: dict[str, list[tuple[int, Path]]] = {}
        self.sources = 0
        for src in sources or (data_root() / "market" / "days",):
            self.add(src)

    def add(self, src):
        rank, self.sources = self.sources, self.sources + 1
        if isinstance(src, dict):
            self._put(src, rank)
            return
        if isinstance(src, list):
            for r in src:
                self._put(r, rank)
            return
        p = Path(src)
        files = sorted(p.glob("*.jsonl*")) if p.is_dir() else [p] if p.exists() else []
        for f in files:
            month = f.name.split(".")[0]
            if p.is_dir() and len(month) == 7 and month[4] == "-":
                self.pending.setdefault(month, []).append((rank, f))
            else:
                self._read(f, rank)

    def _put(self, row: dict, rank: int):
        if self.rank.get(row["date"], -1) <= rank:
            self._rows[row["date"]] = row
            self.rank[row["date"]] = rank

    def _read(self, f: Path, rank: int):
        with (gzip.open(f, "rt") if f.suffix == ".gz" else open(f)) as fh:
            for line in fh:
                if line.strip():
                    self._put(json.loads(line), rank)

    def _month(self, date: str):
        for rank, f in self.pending.pop(date[:7], []):
            self._read(f, rank)

    @property
    def rows(self) -> dict[str, dict]:
        for month in list(self.pending):
            self._month(month)
        return self._rows

    def get(self, date: str) -> dict:
        self._month(date)
        if date not in self._rows:
            raise KeyError(f"no market day {date}")
        return self._rows[date]

    def __contains__(self, date: str) -> bool:
        self._month(date)
        return date in self._rows


def aggregate(curves: list, side: str, floor: float, cap: float) -> list[list[float]]:
    """The sum of cumulative curves as one cumulative curve [[mw, price], ...] on the union of their price knots."""
    xy = [(supply_xy if side == "supply" else demand_xy)(c, floor, cap) for c in curves if c]
    if not xy:
        return []
    P = np.unique(np.concatenate([x[0] for x in xy]))
    M = sum(np.interp(P, p, m) for p, m in xy)
    pts = list(zip(M, P, strict=True)) if side == "supply" else list(zip(M[::-1], P[::-1], strict=True))
    out: list[list[float]] = []
    for m, p in pts:
        if out and abs(m - out[-1][0]) < 1e-9 and abs(p - out[-1][1]) < NUDGE * 2:
            continue
        out.append([float(m), float(p)])
    return out


def simplify(pts: list, n: int, focus: tuple[float, float] | None = None) -> list[list[float]]:
    """≤ n points of a cumulative curve by greedy insertion of the point farthest (in MW and price, each scaled to its
    range; ×10 inside the focus MW window) from the polyline of the kept points; endpoints kept; values to 0.01."""
    if len(pts) <= n:
        return [[round(m, 2), round(p, 2)] for m, p in pts]
    mw, pr = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    t = np.arange(len(pts), dtype=float)
    sm, sp = max(np.ptp(mw), 1.0), max(np.ptp(pr), 1.0)
    w = np.ones(len(pts)) if focus is None else np.where((mw >= focus[0]) & (mw <= focus[1]), 10.0, 1.0)
    keep = [0, len(pts) - 1]
    while len(keep) < n:
        k = np.array(sorted(keep))
        err = np.maximum(np.abs(np.interp(t, k, mw[k]) - mw) / sm, np.abs(np.interp(t, k, pr[k]) - pr) / sp) * w
        i = int(np.argmax(err))
        if err[i] <= 1e-9:
            break
        keep.append(i)
    return [[round(float(mw[i]), 2), round(float(pr[i]), 2)] for i in sorted(keep)]


def hour_curves(day: dict, h: int, carve: set | None = None) -> tuple[list, list]:
    """(supply curves, demand curves) of hour h: the carve-free core plus every pool member not in `carve`."""
    sup, dem = [day["background"]["supply"][h]], [day["background"]["demand"][h]]
    for members in (day.get("pool") or {}).values():
        for m in members:
            if carve and m["id"] in carve:
                continue
            if m.get("sell"):
                sup.append(m["sell"][h])
            if m.get("buy"):
                dem.append(m["buy"][h])
    return sup, dem


def disclosure(day: dict, side: str, hour: int | None = None) -> dict:
    """What get_disclosure serves for a disclosed day: the whole market's aggregate curve (anonymised), ≤ 64 points for
    one hour or ≤ 16 per hour for all 24, with the day's cleared MW and λ."""
    floor, cap = limits(day["date"])
    hours = range(HOURS) if hour is None else [hour - 1]
    n = DISCLOSURE_POINTS if hour is not None else DISCLOSURE_POINTS_DAY
    rows = []
    for h in hours:
        sup, dem = hour_curves(day, h)
        pts = aggregate(sup if side == "supply" else dem, side, floor, cap)
        cleared = (day.get("replay") or {}).get("cleared_mw", [None] * HOURS)[h]
        focus = None if cleared is None else (cleared - 10000.0, cleared + 10000.0)
        rows.append({"hour": h + 1, "curve": simplify(pts, n, focus), "cleared_mw": cleared,
                     "lambda_usd": round(float(day["lambda_usd"][h]), 2)})
    if hour is not None:
        return {"op_date": day["date"], "side": side} | rows[0]
    return {"op_date": day["date"], "side": side, "hours": rows}


def disclosed_net(day: dict, h: int) -> tuple[list, list]:
    """The anchor's view of a disclosed hour: exactly the ≤ 64-point supply and demand curves get_disclosure serves."""
    return disclosure(day, "supply", h + 1)["curve"], disclosure(day, "demand", h + 1)["curve"]


def net_load(day: dict) -> np.ndarray:
    """Actual load − wind − solar of a day (EIA-930)."""
    a = day["actuals"]
    return np.asarray(a["load_mw"], float) - np.asarray(a["wind_mw"], float) - np.asarray(a["solar_mw"], float)


def net_load_forecast(store: DayStore, date: str) -> np.ndarray:
    """What is known of a day's net load at 09:00 the day before: its day-ahead load forecast (EIA-930 DF) minus wind and
    solar persisted from two days earlier, the last complete day."""
    d, d2 = store.get(date), store.get(shift(date, -2))["actuals"]
    return np.asarray(d["df_mw"], float) - np.asarray(d2["wind_mw"], float) - np.asarray(d2["solar_mw"], float)


KIND = {"A": "battery", "B": "battery", "G": "gas", "R": "renewable", "L": "retailer"}


def unit_cost(u: dict, fuel: float) -> float:
    return u["hr"] * fuel + u["vom"]


class Floor:
    """A task's market: the day's background with the task's carve, the five seats, per-hour books for any set of seats
    bidding their real curves, and the mitigated clear. A profile maps each seat to "replay" (its real curve) or to 24
    hourly block lists."""

    def __init__(self, task: dict, store: DayStore | None = None):
        self.task, self.date = task, task["date"]
        self.store = store if store is not None else task_store(task)
        self.day = self.store.get(self.date)
        self.floor, self.cap = limits(self.date)
        self.seats = task["seats"]
        self.pool = {m["id"]: m for ms in (self.day.get("pool") or {}).values() for m in ms}
        self.carve = {s["pool_id"] for s in self.seats.values() if s.get("pool_id")}
        self.hub_real = np.asarray(self.day["hub_dam_usd"], float)
        self.lam_real = np.asarray(self.day["lambda_usd"], float)
        self.offset = hub_offset(self.day)
        self.rt = np.asarray(self.day["hub_rt_usd"], float).reshape(HOURS, 4).mean(axis=1)
        self.eps = np.zeros(HOURS)
        self.grids = {s: float(self.seats[s].get("grid_mw") or FINE_GRID) for s in SEATS if s in self.seats}
        self.refs = {s: self._refs(s) for s in SEATS if s in self.seats}
        self._books: dict = {}
        self._clears: dict = {}

    def _refs(self, seat: str) -> list[float | None]:
        st, kind = self.seats[seat], KIND[seat]
        if kind == "battery":
            return [float(x) for x in st.get("reference_usd") or [None] * HOURS]
        if kind == "gas":
            return [1.1 * max(unit_cost(u, st["fuel_usd_mmbtu"]) for u in st["units"])] * HOURS
        if kind == "renewable":
            return [RENEWABLE_REF] * HOURS
        return [None] * HOURS

    def curve(self, seat: str, h: int) -> tuple[list, list]:
        m = self.pool[self.seats[seat]["pool_id"]]
        return (m.get("sell") or [[]] * HOURS)[h], (m.get("buy") or [[]] * HOURS)[h]

    def book(self, h: int, curve_seats: frozenset, mitigated: frozenset = frozenset()):
        key = (h, curve_seats, mitigated)
        if key not in self._books:
            sup, dem = hour_curves(self.day, h, self.carve)
            curves = {}
            for s in sorted(curve_seats):
                sell, buy = self.curve(s, h)
                curves[s] = (capped(sell, self.refs[s][h]) if s in mitigated else sell, buy)
            self._books[key] = book(self.floor, self.cap, sup, dem, curves, float(self.eps[h]), float(self.offset[h]))
        return self._books[key]

    def clear(self, h: int, profile: dict) -> Clear:
        """The mitigated clear of hour h; awards for every seat (MW, + sells), curve seats read at λ'."""
        key = (h, tuple((s, o if o == "replay" else tuple(o[h])) for s, o in sorted(profile.items())))
        if key in self._clears:
            return self._clears[key]
        cs = frozenset(s for s, o in profile.items() if o == "replay")
        blocks = [b for s, o in sorted(profile.items()) if o != "replay" for b in o[h]]
        res = clear_mitigated(lambda m: self.book(h, cs, frozenset(m) & cs), blocks, self.grids,
                              {s: self.refs[s][h] for s in cs})
        bk = self.book(h, cs, frozenset(res.mitigated) & cs)
        awards = {s: 0.0 for s in profile}
        awards.update(res.awards)
        for s in cs:
            sell, buy = bk.curves[s]
            awards[s] = round(float(at(sell, res.lam) - at(buy, res.lam)), 9) + 0.0
        res.awards = awards
        self._clears[key] = res
        return res

    def hub(self, h: int, lam: float) -> float:
        return float(lam)


def hub_offset(day: dict) -> np.ndarray:
    """Per hour, the real hub DAM price minus the copper-plate re-clear of every real offer: the AS, congestion and loss
    component the re-clear does not model, held fixed so the replay clears at the real hub price (V5-P2)."""
    return np.asarray(day["hub_dam_usd"], float) - np.asarray(day["replay"]["lambda_usd"], float)


def task_store(task: dict) -> DayStore:
    """The days a task reads: its inline days if it carries them, else the packaged store, under the fixture days for
    a fixture task (they were built from the sample and differ from the store on a few dates). Shared per process."""
    if task.get("days"):
        return DayStore(task["days"])
    return packaged_store(task.get("pack") == FIXTURE_PACK)


@cache
def packaged_store(fixtures: bool) -> DayStore:
    srcs = [data_root() / "market" / "days"] + ([data_root() / FIXTURE_PACK / "days.jsonl.gz"] if fixtures else [])
    return DayStore(*[p for p in srcs if p.exists()])


# NP3-966-ER 60-Day DAM Disclosure → days rows (CONTRACT-v5 "Background")

FILES = {"gen": "60d_DAM_Gen_Resource_Data", "esr": "60d_DAM_ESR_Data", "offers": "60d_DAM_EnergyOnlyOffers-",
         "bids": "60d_DAM_EnergyBids-", "offer_awards": "60d_DAM_EnergyOnlyOfferAwards",
         "bid_awards": "60d_DAM_EnergyBidAwards"}
UP_AS = ("RegUp Awarded", "RRSPFR Awarded", "RRSFFR Awarded", "RRSUFR Awarded", "ECRSSD Awarded", "NonSpin Awarded")
DOWN_AS = ("RegDown Awarded",)
ESR_TYPES, CT_TYPES, RENEW_TYPES = {"PWRSTR", "ESR"}, {"SCGT90", "SCLE90"}, {"WIND", "PVGR"}
LSL_AT_FLOOR = False
POOL_SIZES = {"esr": (300.0, 1500.0, 4), "ct": (6, 12, 2), "renew": (1000.0, 3000.0, 2), "load": (3000.0, 8000.0, 2)}


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def read_disclosure(path) -> dict[str, list[dict]]:
    """The CSV tables of one NP3-966-ER zip by kind (file names carry the posting date, so match on the prefix)."""
    out = {k: [] for k in FILES}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            kind = next((k for k, pre in FILES.items() if Path(name).name.startswith(pre)), None)
            if kind:
                with z.open(name) as fh:
                    out[kind] = list(csv.DictReader(io.TextIOWrapper(fh, "utf-8-sig", newline="")))
    return out


def _pts(row: dict, mw_key: str, price_key: str) -> list[tuple[float, float]]:
    out = []
    for i in range(1, 11):
        m, p = _f(row.get(f"{mw_key}{i}")), _f(row.get(f"{price_key}{i}"))
        if m is not None and p is not None:
            out.append((m, p))
    return out


def _cum(pts, block: bool) -> list[list[float]]:
    """Cumulative points of a submitted curve: a curve is linear between its points and flat from 0 to its first MW;
    a block (variable or fixed) is flat at each price."""
    out, prev = [], 0.0
    for i, (m, p) in enumerate(pts):
        if m < prev - 1e-9:
            continue
        if i == 0 or block:
            out += [[prev, p], [m, p]]
        else:
            out.append([m, p])
        prev = m
    return out


def _range_curve(pts, lo: float, hi: float, floor: float, mg_per_mwh: float, committed: bool) -> list[list[float]]:
    """A three-part offer inside [lo, hi] (AS-truncated, V5-P6): committed units offer up to LSL at the floor, uncommitted
    ones at the curve's first price plus min-gen cost per MWh (V5-P7); linear between points above."""
    if not pts or hi <= 0:
        return []
    mw, pr = np.array([m for m, _ in pts]), np.array([p for _, p in pts])
    hi = min(hi, float(mw[-1]))
    if hi <= 0:
        return []
    price_at = lambda m: float(np.interp(m, mw, pr))  # noqa: E731
    lo = min(max(lo, 0.0), hi)
    out = []
    if lo > 0:
        p0 = floor if committed and LSL_AT_FLOOR else price_at(lo) + (0.0 if committed else mg_per_mwh)
        out += [[0.0, p0], [lo, p0]]
    else:
        out.append([0.0, price_at(0.0)])
    out += [[float(m), float(p)] for m, p in pts if lo < m < hi]
    out.append([hi, price_at(hi)])
    return out


def resource_curves(row: dict, floor: float) -> tuple[list, list]:
    """(supply, demand) cumulative curves of one Gen Resource or ESR row; ESR curves are split at 0 MW."""
    pts = _pts(row, "QSE submitted Curve-MW", "QSE submitted Curve-Price")
    if not pts:
        return [], []
    hsl, lsl = _f(row.get("HSL")) or 0.0, _f(row.get("LSL")) or 0.0
    up = sum(_f(row.get(k)) or 0.0 for k in UP_AS)
    dn = sum(_f(row.get(k)) or 0.0 for k in DOWN_AS)
    award = _f(row.get("Awarded Quantity")) or 0.0
    if row.get("Resource Type") == "ESR" or any(m < 0 for m, _ in pts):
        sell = [(m, p) for m, p in pts if m >= 0]
        buy = sorted(((-m, p) for m, p in pts if m <= 0), key=lambda x: (x[0], -x[1]))
        s = _range_curve(sell, 0.0, max(0.0, hsl - up), floor, 0.0, False) if sell else []
        d = [[0.0, buy[0][1]]] + [[m, p] for m, p in buy] if buy and buy[-1][0] > 0 else []
        return s, d
    mg = (_f(row.get("Min Gen Cost")) or 0.0) / lsl if lsl > 0 else 0.0
    return _range_curve(pts, lsl + dn, hsl - up, floor, mg, award > 0), []


def parse_disclosure(path, date: str) -> list[dict]:
    """Per hour: every supply and demand curve of the day with its owner (kind, QSE, name, type, settlement point)."""
    t = read_disclosure(path)
    floor, _ = limits(date)
    hours = [{"supply": [], "demand": []} for _ in range(HOURS)]
    for kind in ("gen", "esr"):
        for r in t[kind]:
            h = int(str(r["Hour Ending"]).split(":")[0]) - 1
            if not 0 <= h < HOURS:
                continue
            s, d = resource_curves(r, floor)
            own = {"kind": kind, "qse": r.get("QSE"), "name": r.get("Resource Name"), "type": r.get("Resource Type"),
                   "sp": r.get("Settlement Point Name"), "hsl": _f(r.get("HSL")) or 0.0, "lsl": _f(r.get("LSL")) or 0.0,
                   "start_usd": _f(r.get("Start Up Hot")) or 0.0, "award": _f(r.get("Awarded Quantity")) or 0.0}
            if s:
                hours[h]["supply"].append((own, s))
            if d:
                hours[h]["demand"].append((own, d))
    for kind, side, pre in (("offers", "supply", "Energy Only Offer"), ("bids", "demand", "Energy Only Bid")):
        for r in t[kind]:
            h = int(str(r["Hour Ending"]).split(":")[0]) - 1
            pts = _pts(r, f"{pre} MW", f"{pre} Price")
            if not 0 <= h < HOURS or not pts:
                continue
            block = r.get("Block/Curve indicator") in ("V", "F")
            own = {"kind": kind, "qse": r.get("QSE Name"), "sp": r.get("Settlement Point")}
            hours[h][side].append((own, _cum(sorted(pts, key=lambda x: (x[0], x[1] if side == "supply" else -x[1])),
                                             block)))
    cleared = [0.0] * HOURS
    for r in t["bid_awards"]:
        h = int(str(r["Hour Ending"]).split(":")[0]) - 1
        if 0 <= h < HOURS:
            cleared[h] -= _f(r.get("Energy Only Bid Award in MW")) or 0.0
    for h in range(HOURS):
        hours[h]["cleared_mw"] = cleared[h]
    return hours


def _owner_key(o: dict) -> tuple:
    return (o["kind"], o.get("name") or o.get("sp"), o.get("qse"))


def choose_pool(hours: list[dict]) -> dict[str, list[dict]]:
    """Candidate seat portfolios of a day, each a set of owner keys: one QSE's ESRs (300–1,500 MW), CTs (6–12 units),
    wind and solar (1–3 GW) and load-zone energy bids (3–8 GW); the nearest size when none is in range."""
    esr, ct, ren, load, sps = {}, {}, {}, {}, {}
    for h, hr in enumerate(hours):
        for o, _ in hr["supply"]:
            q, t = o.get("qse"), o.get("type")
            if o["kind"] in ("gen", "esr") and t in ESR_TYPES:
                esr.setdefault(q, {}).setdefault(o["name"], [0.0] * HOURS)[h] = o["hsl"]
                sps.setdefault(q, set()).add(o.get("sp"))
            elif o["kind"] == "gen" and t in CT_TYPES:
                ct.setdefault(q, {})[o["name"]] = o
            elif o["kind"] == "gen" and t in RENEW_TYPES:
                ren.setdefault(q, {}).setdefault(o["name"], [0.0] * HOURS)[h] = o["hsl"]
        for o, c in hr["demand"]:
            if o["kind"] == "bids" and str(o.get("sp", "")).startswith("LZ_"):
                load.setdefault(o.get("qse"), [0.0] * HOURS)[h] += c[-1][0]
    out = {}

    def pick(sizes: dict, lo: float, hi: float, n: int) -> list:
        inside = sorted((q for q, v in sizes.items() if lo <= v <= hi), key=lambda q: (-sizes[q], str(q)))
        if not inside and sizes:
            inside = [min(sizes, key=lambda q: (min(abs(sizes[q] - lo), abs(sizes[q] - hi)), str(q)))]
        return inside[:n]

    lo, hi, n = POOL_SIZES["esr"]
    sizes = {q: max(sum(v[h] for v in u.values()) for h in range(HOURS)) for q, u in esr.items()}
    out["esr"] = [{"qse": q, "names": set(esr[q]), "sps": sps.get(q, set()), "size": sizes[q]} for q in pick(sizes, lo, hi, n)]
    lo, hi, n = POOL_SIZES["ct"]
    sizes = {q: float(len(u)) for q, u in ct.items()}
    out["ct"] = [{"qse": q, "names": set(sorted(ct[q])[:int(hi)]),
                  "units": [ct[q][k] for k in sorted(ct[q])[:int(hi)]], "size": min(sizes[q], hi)}
                 for q in pick(sizes, lo, 1e9, n)]
    lo, hi, n = POOL_SIZES["renew"]
    sizes = {q: max(sum(v[h] for v in u.values()) for h in range(HOURS)) for q, u in ren.items()}
    out["renew"] = [{"qse": q, "names": set(ren[q]), "size": sizes[q]} for q in pick(sizes, lo, hi, n)]
    lo, hi, n = POOL_SIZES["load"]
    sizes = {q: max(v) for q, v in load.items()}
    out["load"] = [{"qse": q, "size": sizes[q]} for q in pick(sizes, lo, hi, n)]
    return out


def _member(kind: str, cand: dict, o: dict, side: str) -> bool:
    q = o.get("qse")
    if q != cand["qse"]:
        return False
    if kind == "esr":
        return o.get("name") in cand["names"] or (side == "demand" and o["kind"] == "bids" and o.get("sp") in cand["sps"])
    if kind in ("ct", "renew"):
        return o.get("name") in cand["names"]
    return o["kind"] == "bids" and str(o.get("sp", "")).startswith("LZ_")


def build_day(path, date: str, lam, hub_dam, hub_rt, actuals: dict, df) -> dict:
    """One days row from an NP3-966-ER zip and the day's public series: the carve-free background (≤ 64 points per hour
    and side), the anonymised candidate pool (≤ 16 points), the replay re-clear on what ships, and its fidelity."""
    hours = parse_disclosure(path, date)
    floor, cap = limits(date)
    cands = choose_pool(hours)
    prefix = {"esr": "e", "ct": "c", "renew": "r", "load": "l"}
    pool = {k: [] for k in cands}
    bg_sup, bg_dem, full_lam = [], [], []
    taken = [[{"supply": [], "demand": []} for _ in range(HOURS)] for _ in range(sum(len(v) for v in cands.values()))]
    order = [(k, i, c) for k in cands for i, c in enumerate(cands[k])]
    for h, hr in enumerate(hours):
        rest = {"supply": [], "demand": []}
        for side in ("supply", "demand"):
            for o, c in hr[side]:
                j = next((j for j, (k, _, cand) in enumerate(order) if _member(k, cand, o, side)), None)
                (taken[j][h][side] if j is not None else rest[side]).append(c)
        c = hr["cleared_mw"]
        focus = (c - 10000.0, c + 10000.0)
        bg_sup.append(simplify(aggregate(rest["supply"], "supply", floor, cap), DISCLOSURE_POINTS, focus))
        bg_dem.append(simplify(aggregate(rest["demand"], "demand", floor, cap), DISCLOSURE_POINTS, focus))
        full = book(floor, cap, [x for _, x in hr["supply"]], [x for _, x in hr["demand"]])
        full_lam.append(clear_mitigated(lambda m, full=full: full, [], {}, {}).lam)
    for j, (k, i, cand) in enumerate(order):
        sell = [simplify(aggregate(taken[j][h]["supply"], "supply", floor, cap), SEAT_POINTS) for h in range(HOURS)]
        buy = [simplify(aggregate(taken[j][h]["demand"], "demand", floor, cap), SEAT_POINTS) for h in range(HOURS)]
        m = {"id": f"{prefix[k]}{i + 1}", "size_mw": round(cand["size"], 2) if k != "ct" else None}
        if k == "ct":
            m["units"] = [{"id": f"u{n + 1}", "mw": round(u["hsl"], 2), "lsl": round(u["lsl"], 2),
                           "start_usd": round(u["start_usd"], 2)} for n, u in enumerate(cand["units"])]
            m["size_mw"] = round(sum(u["hsl"] for u in cand["units"]), 2)
        if any(sell):
            m["sell"] = sell
        if any(buy):
            m["buy"] = buy
        pool[k].append(m)
    row = {"date": date, "dst": False, "parser": "966-rtcb-v1" if date >= "2025-12-05" else "966-v1",
           "lambda_usd": [round(float(x), 4) for x in lam], "hub_dam_usd": [round(float(x), 2) for x in hub_dam],
           "hub_rt_usd": [round(float(x), 2) for x in hub_rt], "df_mw": [round(float(x), 1) for x in df],
           "actuals": {k: [round(float(x), 1) for x in v] for k, v in actuals.items()},
           "background": {"supply": bg_sup, "demand": bg_dem}, "pool": pool,
           "implied_gas_usd_mmbtu": implied_gas(hours)}
    replay = []
    for h in range(HOURS):
        sup, dem = hour_curves(row, h)
        bk = book(floor, cap, sup, dem)
        replay.append(round(clear_mitigated(lambda m, bk=bk: bk, [], {}, {}).lam, 4))
    row["replay"] = {"lambda_usd": replay, "full_lambda_usd": [round(x, 4) for x in full_lam],
                     "cleared_mw": [round(hr["cleared_mw"], 1) for hr in hours]}
    row["fidelity"] = fidelity(np.asarray(lam, float), np.asarray(full_lam), np.asarray(replay))
    return row


def fidelity(lam: np.ndarray, full: np.ndarray, shipped: np.ndarray) -> dict:
    """The re-clear of every real offer against NP4-523 λ (non-scarcity hours: λ < $100), and the simplification error."""
    ns = lam < 100
    within = np.abs(full - lam) <= np.maximum(5.0, 0.10 * np.abs(lam))
    return {"within_ns": round(float(within[ns].mean()), 4) if ns.any() else None, "ns_hours": int(ns.sum()),
            "mae_ns_usd": round(float(np.abs(full - lam)[ns].mean()), 2) if ns.any() else None,
            "mae_usd": round(float(np.abs(full - lam).mean()), 2), "max_err_usd": round(float(np.abs(full - lam).max()), 2),
            "simplify_err_usd": round(float(np.abs(shipped - full).max()), 2)}


def implied_gas(hours: list[dict], heat_rate: float = 7.2, vom: float = 3.0) -> float:
    """The day's gas price implied by real CC offers: median mid-curve price of combined-cycle resources, HE13–HE18."""
    mids = []
    for h in range(12, 18):
        for o, c in hours[h]["supply"]:
            if o.get("type") in ("CCGT90", "CCLE90") and len(c) >= 2:
                mids.append(c[len(c) // 2][1])
    if not mids:
        return 3.0
    return round(max(0.5, (float(np.median(mids)) - vom) / heat_rate), 3)


def sample_seats(day: dict, rng, ct_heat_rates: list[float], a_size: float | None = None, dur: float = 2.0,
                 eta: float = 0.85, c_deg: float = 4.0, a_pool: str | None = None) -> dict:
    """Seats for a task carved from a day's pool: A and B two ESR groups, G the first CT group (heat rates drawn from
    EIA-923's ERCOT CT distribution), R and L the first renewable and load groups."""
    pool = day["pool"]
    esr = pool.get("esr") or []
    a = next((m for m in esr if m["id"] == a_pool), esr[0])
    b = next(m for m in esr if m["id"] != a["id"])
    p = float(a_size if a_size is not None else round(a["size_mw"] / 20) * 20)

    def battery(name, m, pw, d, e_, c):
        pw = max(20.0, round(pw / 20) * 20)
        return {"name": name, "kind": "battery", "pool_id": m["id"], "p_mw": pw, "e_mwh": pw * d, "grid_mw": pw / 20,
                "eta": e_, "c_deg": c, "s0_mwh": pw * d / 2, "s_end_min_mwh": pw * d / 2}

    seats = {"A": battery("bess-A", a, p, dur, eta, c_deg),
             "B": battery("bess-B", b, b["size_mw"], 1.0 if b["size_mw"] < 600 else 2.0, 0.9, 2.0)}
    g = pool["ct"][0]
    seats["G"] = {"name": "gas-G", "kind": "gas", "pool_id": g["id"], "fuel_usd_mmbtu": day["implied_gas_usd_mmbtu"],
                  "units": [{"id": u["id"], "mw": u["mw"], "lsl": u["lsl"], "hr": round(float(rng.choice(ct_heat_rates)), 3),
                             "vom": 5.0, "start_usd": u["start_usd"]} for u in g["units"]]}
    r = pool["renew"][0]
    a_ = day["actuals"]
    fc = [s[-1][0] if s else 0.0 for s in r.get("sell") or [[]] * HOURS]
    seats["R"] = {"name": "renew-R", "kind": "renewable", "pool_id": r["id"], "forecast_mw": [round(x, 2) for x in fc],
                  "actual_mw": [round(x, 2) for x in fc], "ptc_usd": 27.5, "ptc_share": 0.6}
    lg = pool["load"][0]
    lfc = [s[-1][0] if s else 0.0 for s in lg.get("buy") or [[]] * HOURS]
    seats["L"] = {"name": "retail-L", "kind": "retailer", "pool_id": lg["id"], "forecast_mw": [round(x, 2) for x in lfc],
                  "load_mw": [round(x * a_["load_mw"][h] / max(1.0, day["df_mw"][h]), 2) for h, x in enumerate(lfc)],
                  "tariff_usd": 95.0, "dr_share": 0.07, "dr_usd": 150.0, "risk_lambda": 0.5}
    return seats
