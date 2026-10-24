"""GridSimEnv v5 auction core: curves, the hourly uniform-price clear on one node, offer blocks, conduct-and-impact
mitigation, the seats' settlement and the battery's projection. `market_refs` and `market` build on it.

Prices are system energy prices λ ($/MWh, cents); the hub price adds the day's real basis. The background (every offer
and bid not carved into a seat, plus seats bidding real curves) is continuous and strictly increasing, so it always sets
the price (CONTRACT-v5 V5-P4) and every seat's best response is a quantity choice."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from gridsim_core.contract import P_FLOOR, era

HOURS = 24
SEATS = ("A", "B", "G", "R", "L")
SUPPLY_SEATS = ("A", "B", "G", "R")
BATTERY_SEATS = ("A", "B")
GRID_STEPS = 20
MAX_BLOCKS = 10
SLOPE = 1e-6
NUDGE = 1e-4
FINE_GRID = 0.1
CONDUCT_USD, CONDUCT_SHARE = 10.0, 0.5
IMPACT_USD, IMPACT_SHARE = 5.0, 0.10
RENEWABLE_REF = 10.0
TOL = 1e-6


def _r2(x: float) -> float:
    return round(float(x), 2) + 0.0


def _r6(x: float) -> float:
    return round(float(x), 6) + 0.0


def dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def limits(date: str) -> tuple[float, float]:
    e = era(date)
    return float(e["floor"]), float(e["hcap"])


# curves: cumulative [[mw, price], ...]; supply prices non-decreasing, demand prices non-increasing


def _strict_up(p: np.ndarray) -> np.ndarray:
    k = np.arange(len(p)) * NUDGE
    return np.maximum.accumulate(p - k) + k


def supply_xy(pts, floor: float, cap: float) -> tuple[np.ndarray, np.ndarray]:
    """(prices strictly increasing, cumulative MW) of a supply curve; MW offered at λ = interp(λ, prices, mw)."""
    pts = [(float(m), float(p)) for m, p in pts or [] if m is not None and p is not None]
    if not pts or pts[-1][0] <= 0:
        return np.array([floor, cap]), np.zeros(2)
    mw = np.maximum.accumulate(np.array([m for m, _ in pts]))
    pr = np.clip(np.array([p for _, p in pts]), floor, cap)
    if mw[0] > 0:
        mw, pr = np.concatenate([[0.0], mw]), np.concatenate([[pr[0]], pr])
    return _strict_up(pr), mw


def demand_xy(pts, floor: float, cap: float) -> tuple[np.ndarray, np.ndarray]:
    """(prices strictly increasing, MW demanded) of a bid curve; MW bid at λ = interp(λ, prices, mw)."""
    pts = [(float(m), float(p)) for m, p in pts or [] if m is not None and p is not None]
    if not pts or pts[-1][0] <= 0:
        return np.array([floor, cap]), np.zeros(2)
    mw = np.maximum.accumulate(np.array([m for m, _ in pts]))
    pr = np.clip(np.array([p for _, p in pts]), floor, cap)
    if mw[0] > 0:
        mw, pr = np.concatenate([[0.0], mw]), np.concatenate([[pr[0]], pr])
    pa, ma = pr[::-1], mw[::-1]
    return _strict_up(pa), ma


def at(xy: tuple[np.ndarray, np.ndarray], lam):
    p, m = xy
    return np.interp(lam, p, m)


def capped(pts, ref: float):
    """A supply curve with every price above ref lowered to ref (a mitigated offer)."""
    return [[m, min(p, ref)] for m, p in pts]


@dataclass
class Book:
    """One hour's price-setting background: the net curve N(λ) = supply − demand (+ SLOPE·(λ − floor) − ε) on knots P."""

    floor: float
    cap: float
    P: np.ndarray
    N: np.ndarray
    s_cap: float
    demand: list
    curves: dict = field(default_factory=dict)

    def n(self, lam):
        return np.interp(lam, self.P, self.N)

    def inv(self, y: float) -> float:
        return float(np.interp(y, self.N, self.P))

    def demand_at(self, lam: float) -> float:
        return float(sum(at(xy, lam) for xy in self.demand))


def lift(pts, usd: float) -> list:
    return [[m, p + usd] for m, p in pts or []] if usd else pts


def book(floor: float, cap: float, supply: list, demand: list, curves: dict | None = None, eps: float = 0.0,
         offset: float = 0.0) -> Book:
    """The background book of an hour from supply and demand point lists plus seats bidding curves
    ({seat: (sell_pts, buy_pts)}), every price raised by `offset` (the hub offset, V5-P2) and shifted left by eps MW."""
    sx = [supply_xy(lift(s, offset), floor, cap) for s in supply]
    dx = [demand_xy(lift(d, offset), floor, cap) for d in demand]
    cx = {k: (supply_xy(lift(s, offset), floor, cap), demand_xy(lift(b, offset), floor, cap))
          for k, (s, b) in (curves or {}).items()}
    knots = [np.array([floor, cap])] + [x[0] for x in sx + dx] + [x[0] for v in cx.values() for x in v]
    P = np.unique(np.clip(np.concatenate(knots), floor, cap))
    N = sum((at(x, P) for x in sx), np.zeros(len(P))) - sum((at(x, P) for x in dx), np.zeros(len(P)))
    N = N + sum((at(s, P) - at(b, P) for s, b in cx.values()), np.zeros(len(P)))
    N = N + SLOPE * (P - floor) - eps
    s_cap = float(sum(x[1][-1] for x in sx) + sum(s[1][-1] for s, _ in cx.values()))
    return Book(floor, cap, P, N, s_cap, dx + [b for _, b in cx.values()], cx)


# blocks: (seat, side, mw, price, ref); side +1 sells, −1 buys


@dataclass
class Clear:
    lam: float
    awards: dict
    curtailed: float = 0.0
    spilled: float = 0.0
    mitigated: list = field(default_factory=list)


def _floor_to(x: float, g: float) -> float:
    return math.floor(x / g + 1e-9) * g if g > 0 else x


def clear_hour(bk: Book, blocks: list, grids: dict) -> Clear:
    """λ' = min{λ : N(λ) + Σ seat injection(λ) ≥ 0}. Sells priced at the floor and buys at the cap always clear (as
    self-schedules); marginal seat blocks share the gap pro rata, each seat's share rounded down to its grid, and the
    background takes the remainder at its own price."""
    floor, cap = bk.floor, bk.cap
    fixed, awards, live = 0.0, {}, []
    for s, side, mw, p, _ in blocks:
        if mw <= 0:
            continue
        if (side > 0 and p <= floor) or (side < 0 and p >= cap):
            fixed += side * mw
            awards[s] = awards.get(s, 0.0) + side * mw
        else:
            live.append((s, side, mw, min(max(p, floor), cap)))
    sells = sorted((p, mw, s) for s, side, mw, p in live if side > 0)
    buys = sorted((p, mw, s) for s, side, mw, p in live if side < 0)
    sp, bp = np.array([x[0] for x in sells]), np.array([x[0] for x in buys])
    sc = np.concatenate([[0.0], np.cumsum([x[1] for x in sells])])
    bc = np.concatenate([[0.0], np.cumsum([x[1] for x in buys])])
    btot = bc[-1]
    C = np.unique(np.concatenate([[floor, cap], sp, bp]))
    nc = bk.n(C) + fixed
    s_lt, s_le = sc[np.searchsorted(sp, C, "left")], sc[np.searchsorted(sp, C, "right")]
    b_ge, b_gt = btot - bc[np.searchsorted(bp, C, "left")], btot - bc[np.searchsorted(bp, C, "right")]
    fl, fr = nc + s_lt - b_ge, nc + s_le - b_gt
    out = Clear(0.0, awards)

    def add(s, q):
        awards[s] = awards.get(s, 0.0) + q

    if fl[0] >= 0:
        for _, mw, s in buys:
            add(s, -mw)
        out.spilled = float(fl[0])
        out.lam = floor
        return out
    q_int = s_le[:-1] - b_gt[:-1]
    point = (fl < 0) & (fr >= 0)
    inter = np.zeros(len(C), bool)
    inter[:-1] = (fr[:-1] < 0) & (nc[1:] + q_int >= 0)
    ev = np.flatnonzero(np.ravel(np.column_stack([point, inter])))
    if not len(ev):
        for _, mw, s in sells:
            add(s, mw)
        out.curtailed = float(-fr[-1])
        out.lam = cap
        return out
    k, is_int = divmod(int(ev[0]), 2)
    if is_int:
        for p, mw, s in sells:
            if p <= C[k]:
                add(s, mw)
        for p, mw, s in buys:
            if p >= C[k + 1]:
                add(s, -mw)
    else:
        c = C[k]
        for p, mw, s in sells:
            if p < c:
                add(s, mw)
        for p, mw, s in buys:
            if p > c:
                add(s, -mw)
        g = -(nc[k] + s_lt[k] - b_gt[k])
        sm, bm = s_le[k] - s_lt[k], b_ge[k] - b_gt[k]
        xb = min(bm, sm - g)
        xs = g + xb
        for side, total, x, lst in ((1, sm, xs, sells), (-1, bm, xb, buys)):
            if total <= 0:
                continue
            share: dict = {}
            for p, mw, s in lst:
                if p == c:
                    share[s] = share.get(s, 0.0) + mw * max(0.0, min(x, total)) / total
            for s, v in share.items():
                add(s, side * _floor_to(v, grids.get(s, FINE_GRID)))
    net = sum(awards.values())
    out.lam = min(cap, max(floor, bk.inv(-net)))
    out.awards = {s: round(v, 9) + 0.0 for s, v in awards.items()}
    return out


def conduct(price: float, ref: float | None) -> bool:
    return ref is not None and price > ref + max(CONDUCT_USD, CONDUCT_SHARE * abs(ref))


def impact(before: float, after: float) -> bool:
    return before - after >= max(IMPACT_USD, IMPACT_SHARE * abs(before))


def rsi(bk: Book, blocks: list, seat: str, res: Clear) -> float:
    sup = bk.s_cap + sum(mw for s, side, mw, _, _ in blocks if side > 0 and s != seat)
    sup -= at(bk.curves[seat][0], bk.cap) if seat in bk.curves else 0.0
    dem = bk.demand_at(res.lam) + sum(-v for v in res.awards.values() if v < 0)
    return float(sup / dem) if dem > 0 else math.inf


def clear_mitigated(hour_books, blocks: list, grids: dict, refs: dict) -> Clear:
    """The clear with conduct-and-impact mitigation for supply seats in order A, B, G, R (V5-P5). `hour_books(m)` gives
    the book with the curve seats in the set m mitigated; refs[seat] is that seat's hour reference (blocks carry their
    own)."""
    mit: frozenset = frozenset()
    bk = hour_books(mit)
    res = clear_hour(bk, blocks, grids)
    for seat in SUPPLY_SEATS:
        if seat in bk.curves:
            ref = refs.get(seat)
            sell = bk.curves[seat][0]
            thr = None if ref is None else ref + max(CONDUCT_USD, CONDUCT_SHARE * abs(ref))
            if thr is None or at(sell, bk.cap) - at(sell, thr) <= TOL:
                continue
            alt_bk = hour_books(mit | {seat})
            alt = clear_hour(alt_bk, blocks, grids)
            if impact(res.lam, alt.lam) or rsi(bk, blocks, seat, res) < 1:
                mit, bk, res = mit | {seat}, alt_bk, alt
                res.mitigated = sorted(mit)
            continue
        hit = [i for i, b in enumerate(blocks) if b[0] == seat and b[1] > 0 and conduct(b[3], b[4])]
        if not hit:
            continue
        alt_blocks = [(b[0], b[1], b[2], b[4], b[4]) if i in hit else b for i, b in enumerate(blocks)]
        alt = clear_hour(bk, alt_blocks, grids)
        if impact(res.lam, alt.lam) or rsi(bk, blocks, seat, res) < 1:
            blocks, res = alt_blocks, alt
            mit = mit | {seat}
            res.mitigated = sorted(mit)
    res.mitigated = sorted(mit)
    return res


# offers


class OfferError(ValueError):
    pass


def _num(x) -> float:
    v = float(x)
    if not math.isfinite(v):
        raise ValueError("not finite")
    return v


def parse_offer(offer, p_mw: float, grid_mw: float, floor: float, cap: float) -> tuple[dict, list[dict]]:
    """({he: {"sell": [(mw, price)], "buy": [(mw, price)]}}, issues). Any issue refuses the whole offer."""
    if isinstance(offer, str):
        try:
            offer = json.loads(offer)
        except json.JSONDecodeError as e:
            return {}, [{"he": None, "rule": "parse", "detail": f"not JSON: {e.msg}"}]
    if isinstance(offer, list):
        offer = {"hours": offer}
    if not isinstance(offer, dict) or not isinstance(offer.get("hours"), list):
        return {}, [{"he": None, "rule": "parse", "detail": 'expected {"hours": [{"he", "sell", "buy"}, ...]}'}]
    extra = sorted(set(offer) - {"hours", "as_awards"})
    if extra:
        return {}, [{"he": None, "rule": "parse", "detail": f"unexpected key {extra[0]!r}"}]
    if offer.get("as_awards"):
        return {}, [{"he": None, "rule": "not_offered", "detail": "no ancillary services in the v5 preview"}]
    out, issues = {}, []
    for row in offer["hours"]:
        if not isinstance(row, dict) or sorted(set(row) - {"he", "sell", "buy"}):
            issues.append({"he": None, "rule": "parse", "detail": f"bad hour row {str(row)[:60]}"})
            continue
        try:
            he = int(row.get("he"))
        except (TypeError, ValueError):
            issues.append({"he": None, "rule": "parse", "detail": f"bad he {row.get('he')!r}"})
            continue
        if not 1 <= he <= HOURS or he in out:
            issues.append({"he": he, "rule": "parse", "detail": "he must be 1..24, once each"})
            continue
        sides = {}
        for side in ("sell", "buy"):
            blocks = []
            for b in row.get(side) or []:
                try:
                    mw, price = _num(b[0]), _num(b[1])
                    if len(b) != 2:
                        raise ValueError
                except (TypeError, ValueError, IndexError):
                    issues.append({"he": he, "rule": "parse", "detail": f"{side} block {str(b)[:40]} is not [mw, price]"})
                    continue
                k = mw / grid_mw
                if mw <= 0 or abs(k - round(k)) > 1e-6:
                    issues.append({"he": he, "rule": "grid", "detail": f"{side} {mw} MW is not a positive multiple "
                                                                       f"of {grid_mw:g} MW"})
                if not floor <= price <= cap:
                    issues.append({"he": he, "rule": "price_range", "detail": f"{price} outside [{floor:g}, {cap:g}]"})
                blocks.append((round(k) * grid_mw, round(price, 2)))
            sides[side] = blocks
        if len(sides["sell"]) + len(sides["buy"]) > MAX_BLOCKS:
            issues.append({"he": he, "rule": "blocks", "detail": f"more than {MAX_BLOCKS} blocks"})
        for side in ("sell", "buy"):
            if sum(m for m, _ in sides[side]) > p_mw + 1e-6:
                issues.append({"he": he, "rule": "power", "detail": f"{side} total above {p_mw:g} MW"})
        if sides["sell"] and sides["buy"] and max(p for _, p in sides["buy"]) >= min(p for _, p in sides["sell"]):
            issues.append({"he": he, "rule": "crossed", "detail": "a buy price is at or above a sell price"})
        out[he] = sides
    return out, issues


def offer_blocks(seat: str, parsed: dict, ref=None) -> list[list]:
    """Per-hour block lists [(seat, side, mw, price, ref)] of a parsed offer; ref is a [24] list or None."""
    hours = [[] for _ in range(HOURS)]
    for he, sides in parsed.items():
        r = None if ref is None else float(ref[he - 1])
        hours[he - 1] += [(seat, 1, mw, p, r) for mw, p in sides["sell"]]
        hours[he - 1] += [(seat, -1, mw, p, None) for mw, p in sides["buy"]]
    return hours


def self_schedule(seat: str, q: float, floor: float, cap: float, ref=None) -> list:
    if q > 0:
        return [(seat, 1, q, floor, ref)]
    if q < 0:
        return [(seat, -1, -q, cap, None)]
    return []


def offer_json(parsed: dict) -> dict:
    return {"hours": [{"he": he, "sell": [[_r2(m), _r2(p)] for m, p in s["sell"]],
                       "buy": [[_r2(m), _r2(p)] for m, p in s["buy"]]} for he, s in sorted(parsed.items())]}


def curve_blocks(pts, grid: float, side: str, max_blocks: int = MAX_BLOCKS) -> list[tuple[float, float]]:
    """A cumulative curve snapped to whole grid units as ≤ max_blocks blocks [(mw, price)] (price of each unit's last MW)."""
    pts = [(float(m), float(p)) for m, p in pts or []]
    if not pts or pts[-1][0] < grid:
        return []
    units = int(math.floor(pts[-1][0] / grid + 1e-9))
    mw, pr = np.array([m for m, _ in pts]), np.array([p for _, p in pts])
    prices = [float(np.interp(k * grid, mw, pr)) for k in range(1, units + 1)]
    groups = np.array_split(np.arange(units), min(max_blocks, units))
    pick = max if side == "sell" else min
    return [(len(g) * grid, round(pick(prices[i] for i in g), 2)) for g in groups if len(g)]


# battery seats: SoC on a lattice of grid/20 MWh so sells (−20 per unit) and buys (+20η per unit) stay on it


@dataclass(frozen=True)
class Battery:
    p: float
    e: float
    grid: float
    eta: float
    c_deg: float
    s0: float
    s_end: float

    @property
    def sub(self) -> float:
        return self.grid / GRID_STEPS

    @property
    def levels(self) -> int:
        return int(round(self.e / self.sub))

    @property
    def gain(self) -> int:
        return int(round(self.eta * GRID_STEPS))


def battery_of(seat: dict) -> Battery:
    b = Battery(float(seat["p_mw"]), float(seat["e_mwh"]), float(seat["grid_mw"]), float(seat["eta"]),
                float(seat["c_deg"]), float(seat["s0_mwh"]), float(seat["s_end_min_mwh"]))
    for name, v in (("eta·20", b.eta * GRID_STEPS), ("E/sub", b.e / b.sub), ("s0/sub", b.s0 / b.sub),
                    ("s_end/sub", b.s_end / b.sub), ("P/grid", b.p / b.grid)):
        if abs(v - round(v)) > 1e-6:
            raise ValueError(f"battery {name} = {v} is not whole")
    return b


def project(b: Battery, awards) -> dict:
    """SoC-feasible delivery of hourly awards: each hour's award clipped to the SoC room (sells ≤ SoC, buys ≤ (E − SoC)/η)."""
    s, ex, soc, clipped = b.s0, [], [b.s0], []
    for h, a in enumerate(awards):
        x = min(a, s, b.p) if a > 0 else -min(-a, (b.e - s) / b.eta, b.p) if a < 0 else 0.0
        if abs(x - a) > 1e-9:
            clipped.append(h + 1)
        s = s - x if x > 0 else s - b.eta * x
        s = min(b.e, max(0.0, s))
        ex.append(round(x, 9) + 0.0)
        soc.append(round(s, 9) + 0.0)
    return {"exec_mw": ex, "soc_mwh": soc, "clipped_hours": clipped,
            "end_shortfall_mwh": round(max(0.0, b.s_end - s), 9) + 0.0}


def penalty_price(hub_real) -> float:
    return float(max(max(hub_real), P_FLOOR))


def settle_battery(b: Battery, awards, exec_mw, hub, rt, pen_price: float) -> dict:
    s = b.s0
    for x in exec_mw:
        s = s - x if x > 0 else s - b.eta * x
    short = max(0.0, b.s_end - s)
    dam = float(sum(a * p for a, p in zip(awards, hub, strict=True)))
    dev = float(sum((x - a) * r for a, x, r in zip(awards, exec_mw, rt, strict=True)))
    deg = float(b.c_deg * sum(max(x, 0.0) for x in exec_mw))
    pen = short / b.eta * pen_price
    return {"dam_usd": dam, "rt_deviation_usd": dev, "degradation_usd": deg, "shortfall_usd": pen,
            "total_usd": dam + dev - deg - pen}


def gas_cost(units: list[dict], fuel: float, g_mw) -> tuple[float, float]:
    """(energy cost, start cost) of hourly gas output filled cheapest unit first; a unit starts when it turns on."""
    order = sorted(units, key=lambda u: (u["hr"] * fuel + u["vom"], u["id"]))
    energy = starts = 0.0
    on_prev: set = set()
    for g in g_mw:
        left, on = max(0.0, g), set()
        for u in order:
            if left <= 1e-9:
                break
            x = min(u["mw"], left)
            energy += x * (u["hr"] * fuel + u["vom"])
            left -= x
            on.add(u["id"])
        starts += sum(u["start_usd"] for u in order if u["id"] in on - on_prev)
        on_prev = on
    return energy, starts


def seat_profit(kind: str, seat: dict, awards, hub, rt, pen_price: float) -> float:
    if kind == "battery":
        b = battery_of(seat)
        return settle_battery(b, awards, project(b, awards)["exec_mw"], hub, rt, pen_price)["total_usd"]
    if kind == "gas":
        e, st = gas_cost(seat["units"], seat["fuel_usd_mmbtu"], awards)
        return float(sum(a * p for a, p in zip(awards, hub, strict=True))) - e - st
    if kind == "renewable":
        act = seat["actual_mw"]
        return float(sum(a * p + (x - a) * r for a, p, x, r in zip(awards, hub, act, rt, strict=True))
                     + seat["ptc_usd"] * seat["ptc_share"] * sum(act))
    if kind == "retailer":
        load = seat["load_mw"]
        return float(seat["tariff_usd"] * sum(load) + sum(a * p + (x + a) * -r for a, p, x, r in
                                                          zip(awards, hub, load, rt, strict=True)))
    raise ValueError(kind)
