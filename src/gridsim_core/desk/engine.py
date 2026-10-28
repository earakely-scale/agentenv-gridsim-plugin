"""The desk market engine: the book of curves and COP, DAM clearing at the close, 5-minute SCED against the real node
LMP and the battery physics (contract sections 4-6). The Session, the references and the operator replay all drive it."""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

from gridsim_core.desk import ancillary as asv
from gridsim_core.desk import clock
from gridsim_core.desk.curves import FLOOR, caps, clear_any
from gridsim_core.desk.data import Series
from gridsim_core.desk.impact import Stack

PER_H = 12
STATUSES_POST = ("ON", "ONOS", "ONTEST", "ONEMR", "ONHOLD", "OUT")
STATUSES_PRE = ("ON", "ONTEST", "ONEMR", "OUT")
IDLE_STATUSES = ("OUT", "ONHOLD")


@dataclass(frozen=True)
class Site:
    site_id: str
    hsl: float
    lsl: float
    e_max: float
    e_min: float
    ramp: float
    rte: float
    loss_pct_h: float
    deg: float
    warranty: float
    soc0: float
    pv_mw: float = 0.0
    poi_mw: float | None = None

    @property
    def eta(self) -> float:
        return math.sqrt(self.rte)

    @property
    def rho(self) -> float:
        """Share of the energy above MinSOC retained over one 5-minute interval."""
        return (1.0 - self.loss_pct_h / 100.0) ** (1.0 / PER_H)

    @property
    def usable(self) -> float:
        return self.e_max - self.e_min


def site_of(task: dict) -> Site:
    s = task["site"]
    hsl = float(s["hsl_mw"])
    return Site(s["site_id"], hsl, float(s["lsl_mw"]), float(s["e_max_mwh"]), float(s.get("e_min_mwh", 0.0)),
                float(s.get("ramp_mw_per_min") or hsl / 5.0), float(s["rte"]), float(s.get("standby_loss_pct_per_h", 0.0)),
                float(s.get("deg_usd_per_mwh", 10.0)), float(s.get("warranty_cycles_per_day", 1.5)),
                float(s["soc0_mwh"]), float((s.get("pv") or {}).get("mw_ac", 0.0)),
                (s.get("pv") or {}).get("poi_mw"))


def idle_end_soc(site: Site, intervals: int) -> float:
    return site.e_min + (site.soc0 - site.e_min) * site.rho ** intervals


def drift(site: Site, soc: float) -> float:
    """SoC after one idle interval: standby losses apply to the energy above nameplate MinSOC."""
    return site.e_min + (soc - site.e_min) * site.rho


def next_soc(site: Site, soc: float, mw: float) -> float:
    return drift(site, soc) + (site.eta * max(-mw, 0.0) - max(mw, 0.0) / site.eta) / PER_H


def proxy_curve(site: Site, rt_cap: float) -> list[list[float]]:
    """ERCOT's proxy EB/OC for an On-Line ESR without a valid curve: floor for charging, RTSWCAP for discharging."""
    return [[site.lsl, FLOOR], [0.0, FLOOR], [0.0, rt_cap], [site.hsl, rt_cap]]


class Engine:
    """State of one battery on the desk; time only moves forward through `advance`. With `ancillary` (v3+) the DAM
    and SCED co-clear energy and the five AS products, AS deployments move energy, and PV shares the POI."""

    def __init__(self, site: Site, ser: Series, rtcb: bool, ancillary: bool = False, impact: bool = False):
        if impact:
            ser = dataclasses.replace(ser, dam_spp=list(ser.dam_spp))
        self.site, self.ser, self.rtcb, self.ancillary = site, ser, rtcb, ancillary
        self.real_dam = list(ser.dam_spp)
        self.stacks: dict[int, Stack] = {}
        if impact:
            lo, hi = caps(ser.d0, rtcb)["floor"], caps(ser.d0, rtcb)["dam"]
            for j, d in enumerate(ser.dates):
                if d in ser.market:
                    self.stacks[j] = Stack(ser.market[d], ser.dam_spp[24 * j:24 * j + 24], lo, hi)
        n = ser.days
        self.H, self.K = 24 * n, 288 * n
        self.caps = caps(ser.d0, rtcb)
        self.products = asv.products_on(ser.d0) if ancillary else ()
        self.dur = asv.durations(rtcb)
        self.soc_rule = rtcb or asv.soc_rule_pre(ser.d0)
        self.dam_curve: list = [None] * self.H
        self.rt: list[list] = [[] for _ in range(self.H)]
        self.rt_bid: list[list] = [[] for _ in range(self.H)]
        self.dam_as_offer: list[dict] = [{} for _ in range(self.H)]
        self.rt_as_offer: list[list] = [[] for _ in range(self.H)]
        self.cop = {"status": ["ON"] * self.H, "hsl": [site.hsl] * self.H, "lsl": [site.lsl] * self.H,
                    "hbsoc": [site.soc0] * self.H, "min_soc": [site.e_min] * self.H, "max_soc": [site.e_max] * self.H,
                    "as_cap": [{} for _ in range(self.H)]}
        self.cop_touched = [False] * self.H
        self.druc: list[dict | None] = [None] * n
        self.dam_award: list[float | None] = [None] * self.H
        self.dam_as: list[dict] = [{} for _ in range(self.H)]
        self.rt_as: list[dict] = [{} for _ in range(self.K)]
        self.as_short: list[dict] = [{} for _ in range(self.K)]
        self.deploy_short = [0.0] * self.K
        self.pv = [0.0] * self.K
        self.bp = [0.0] * self.K
        self.metered = [0.0] * self.K
        self.soc = [site.soc0] + [0.0] * self.K
        self.source = [""] * self.K
        self.k = 0
        self.t = clock.START

    def hour_start(self, H: int) -> int:
        return 60 * H

    def dam_close(self, day: int) -> int:
        return day * clock.DAY + clock.DAM_CLOSE

    def adj_open(self, H: int) -> int:
        return (H // 24) * clock.DAY + clock.ADJ_OPEN

    def dam_cleared(self, day: int) -> bool:
        return self.dam_award[24 * day] is not None

    @property
    def range_mw(self) -> float:
        return self.site.hsl - self.site.lsl

    def curve_at(self, H: int, t: int):
        """(curve, source) in force for SCED at time t in hour H."""
        if self.rtcb:
            v = [c for tt, c in self.rt[H] if tt <= t]
            if v:
                return v[-1], "rt"
            if self.dam_curve[H] is not None:
                return self.dam_curve[H], "dam"
            return proxy_curve(self.site, self.caps["rt"]), "proxy"
        base = self.dam_curve[H] or {}
        offers = [c for tt, c in self.rt[H] if tt <= t]
        bids = [c for tt, c in self.rt_bid[H] if tt <= t]
        offer = offers[-1] if offers else base.get("offer")
        bid = bids[-1] if bids else base.get("bid")
        src = "rt" if offers or bids else "dam" if base else "none"
        return {"offer": offer, "bid": bid}, src

    def as_offers_at(self, H: int, t: int) -> tuple[dict, dict]:
        """Post-RTC+B RT AS offers in force per product (RT, else DAM, else ERCOT's proxy) and their sources."""
        merged, src = {}, {}
        for p in self.products:
            v = [o[p] for tt, o in self.rt_as_offer[H] if tt <= t and p in o]
            if v:
                merged[p], src[p] = v[-1], "rt"
            elif p in self.dam_as_offer[H]:
                merged[p], src[p] = self.dam_as_offer[H][p], "dam"
        highest = max((pr for bl in merged.values() for _, pr in bl), default=None)
        for p in self.products:
            if p not in merged:
                pk = asv.PRICE_KEY[p]
                asdc = (self.ser.asdc.get(pk) or [None] * self.H)[H]
                plan = (self.ser.as_plan.get(pk) or [None] * self.H)[H]
                mw = self.range_mw
                merged[p], src[p] = [[mw, asv.proxy_offer(mw, asdc, plan, highest)[0][1]]], "proxy"
        return merged, src

    def event_limits(self, t: float) -> tuple[float, float, dict | None]:
        hsl, lsl, ev = self.site.hsl, self.site.lsl, None
        for e in self.ser.unit_events:
            if e["t_start"] <= t < e.get("t_end", math.inf):
                hsl, lsl, ev = min(hsl, float(e.get("hsl_mw", 0.0))), max(lsl, float(e.get("lsl_mw", 0.0))), e
        return hsl, lsl, ev

    def advance(self, t: int) -> None:
        """Run the market to minute t: DAM clearings at their close, SCED intervals starting before t."""
        if t < self.t:
            raise ValueError(f"time moves forward only ({t} < {self.t})")
        for day in range(self.ser.days):
            if not self.dam_cleared(day) and self.dam_close(day) <= t:
                self.clear_dam(day)
            if self.druc[day] is None and day * clock.DAY + clock.DRUC <= t:
                self.druc[day] = {k: v[24 * day:24 * day + 24] for k, v in self.cop.items()}
        while self.k < self.K and 5 * self.k < t:
            self.sced(self.k)
            self.k += 1
        self.t = t

    def _caps(self, H: int, rt: bool) -> dict:
        out = {}
        if rt:
            for p, v in self.cop["as_cap"][H].items():
                out[p] = min(out.get(p, v), v)
        return out

    def clear_dam(self, day: int) -> None:
        stack = self.stacks.get(day)
        for H in range(24 * day, 24 * day + 24):
            c = self.dam_curve[H]
            if stack is not None:
                self.ser.dam_spp[H], _ = stack.clear(H - 24 * day, c, self.rtcb)
            offers = {p: b for p, b in self.dam_as_offer[H].items() if p in self.products}
            hi, lo = self.cop["hsl"][H], self.cop["lsl"][H]
            if offers:
                mcpc = {k: v[H] for k, v in self.ser.dam_mcpc.items()}
                curve = c if c is not None else ([[0.0, FLOOR], [0.0, self.caps["dam"]]] if self.rtcb else {})
                mw, aw = asv.co_clear(curve, self.rtcb, self.ser.dam_spp[H], offers, mcpc, hi, lo, self._caps(H, False))
                self.dam_as[H] = aw
            else:
                mw = 0.0 if c is None else clear_any(c, self.ser.dam_spp[H])
            self.dam_award[H] = round(min(max(mw, lo), hi), 6) + 0.0

    def reg_fraction(self, H: int) -> tuple[float, float]:
        if self.ser.reg_up:
            return self.ser.reg_up[H], self.ser.reg_dn[H]
        return asv.REG_MEAN["up"], asv.REG_MEAN["dn"]

    def deployed(self, t0: float, awards: dict) -> float:
        """MW of RRS/ECRS/Non-Spin deployed in [t0, t0 + 5) from the interval's awards (time-weighted)."""
        out = 0.0
        for d in self.ser.deployments:
            a, b = max(d["t_start"], t0), min(d.get("t_end", t0 + 5), t0 + 5)
            if b <= a:
                continue
            prods = ("rrspfr", "rrsffr") if d["product"] == "rrs" else (d["product"],)
            frac = 1.0 if d.get("frac") is None else float(d["frac"])
            out += sum(awards.get(p, 0.0) for p in prods) * frac * (b - a) / 5.0
        return out

    def sced(self, k: int) -> None:
        s, t0, H = self.site, 5 * k, k // PER_H
        curve, src = self.curve_at(H, t0)
        price = self.ser.rt_lmp[k]
        ehsl, elsl, _ = self.event_limits(t0)
        soc = self.soc[k]
        hi = min(ehsl, self.cop["hsl"][H])
        lo = max(elsl, self.cop["lsl"][H])
        pv = 0.0
        if self.ser.pv and s.pv_mw > 0:
            pv = 0.0 if price < 0 else min(self.ser.pv[k], s.pv_mw)
            if s.poi_mw is not None:
                hi = min(hi, s.poi_mw - pv)
                lo = max(lo, -s.poi_mw - pv)
        self.pv[k] = pv
        e_up = (drift(s, soc) - self.cop["min_soc"][H]) * s.eta
        e_dn = (self.cop["max_soc"][H] - drift(s, soc)) / s.eta
        idle = self.cop["status"][H] in IDLE_STATUSES
        awards: dict = {}
        if self.ancillary and self.rtcb and not idle:
            offers, _ = self.as_offers_at(H, t0)
            mcpc = {pk: v[k] for pk, v in self.ser.rt_mcpc.items()}
            x, awards = asv.co_clear(curve, True, price, offers, mcpc, hi, lo, self._caps(H, True), e_up, e_dn,
                                     self.dur)
        else:
            x = clear_any(curve, price)
            if self.ancillary and not self.rtcb and not idle:
                awards = dict(self.dam_as[H])
        up_sum = sum(awards.get(p, 0.0) for p in asv.UP)
        dn_sum = awards.get("regdn", 0.0)
        if awards and not self.rtcb:
            m_in = t0 - 60 * H
            need_up = sum(awards.get(p, 0.0) * asv.remaining_hour_duration(p, m_in) for p in asv.UP)
            need_dn = dn_sum * asv.remaining_hour_duration("regdn", m_in)
            f_up = 1.0 if up_sum <= 1e-9 else min(1.0, max(hi, 0.0) / up_sum)
            f_dn = 1.0 if dn_sum <= 1e-9 else min(1.0, max(-lo, 0.0) / dn_sum)
            if self.soc_rule:
                if need_up > 1e-9:
                    f_up = min(f_up, max(e_up, 0.0) / need_up)
                if need_dn > 1e-9:
                    f_dn = min(f_dn, max(e_dn, 0.0) / need_dn)
                e_up -= min(need_up, max(e_up, 0.0))
                e_dn -= min(need_dn, max(e_dn, 0.0))
            short = {p: awards[p] * (1 - (f_dn if p == "regdn" else f_up)) for p in awards}
            self.as_short[k] = {p: round(v, 6) for p, v in short.items() if v > 1e-6}
        elif awards:
            e_up -= sum(awards.get(p, 0.0) * self.dur[p] for p in asv.UP)
            e_dn -= dn_sum * self.dur["regdn"]
        if awards:
            hi, lo = max(hi - up_sum, min(hi, 0.0)), min(lo + dn_sum, max(lo, 0.0))
        hi_soc = max(0.0, PER_H * e_up)
        lo_soc = min(0.0, -PER_H * e_dn)
        prev = self.bp[k - 1] if k else 0.0
        bp = min(max(x, prev - 5 * s.ramp), prev + 5 * s.ramp)
        bp = min(max(bp, min(lo, hi)), max(hi, lo))
        bp = min(max(bp, lo_soc), hi_soc)
        if idle:
            bp, src = 0.0, "status"
        if self.rtcb:
            self.rt_as[k] = awards
        m = bp
        if awards:
            fu, fd = self.reg_fraction(H)
            reg = awards.get("regup", 0.0) * fu - awards.get("regdn", 0.0) * fd
            dep = self.deployed(t0, awards)
            bp += dep + reg
            m = bp
        for e in self.ser.unit_events:
            if t0 < e["t_start"] < t0 + 5:
                f = (t0 + 5 - e["t_start"]) / 5.0
                m = m * (1 - f) + min(max(m, float(e.get("lsl_mw", 0.0))), float(e.get("hsl_mw", 0.0))) * f
        ceil_hi = max(0.0, s.eta * PER_H * (drift(s, soc) - self.cop["min_soc"][H]))
        floor_lo = min(0.0, -PER_H * (self.cop["max_soc"][H] - drift(s, soc)) / s.eta)
        m2 = min(max(m, floor_lo, min(elsl, 0.0)), ceil_hi, max(ehsl, 0.0))
        if awards:
            self.deploy_short[k] = round(max(m - m2, 0.0) if m > 0 else max(m2 - m, 0.0), 6)
        self.bp[k], self.metered[k], self.source[k] = round(bp, 6) + 0.0, round(m2, 6) + 0.0, src
        self.soc[k + 1] = next_soc(s, soc, m2)

    def soc_at(self, t: float) -> float:
        return self.soc[min(max(int(t // 5), 0), self.K)]
