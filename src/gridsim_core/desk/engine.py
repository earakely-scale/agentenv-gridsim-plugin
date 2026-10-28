"""The desk market engine: the book of curves and COP, DAM clearing at the close, 5-minute SCED against the real node
LMP and the battery physics (contract sections 4-6). The Session, the references and the operator replay all drive it."""

from __future__ import annotations

import math
from dataclasses import dataclass

from gridsim_core.desk import clock
from gridsim_core.desk.curves import FLOOR, caps, clear, clear_any
from gridsim_core.desk.data import Series

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
                float(s["soc0_mwh"]))


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
    """State of one battery on the desk; time only moves forward through `advance`."""

    def __init__(self, site: Site, ser: Series, rtcb: bool):
        self.site, self.ser, self.rtcb = site, ser, rtcb
        n = ser.days
        self.H, self.K = 24 * n, 288 * n
        self.caps = caps(ser.d0, rtcb)
        self.dam_curve: list = [None] * self.H
        self.rt: list[list] = [[] for _ in range(self.H)]
        self.rt_bid: list[list] = [[] for _ in range(self.H)]
        self.cop = {"status": ["ON"] * self.H, "hsl": [site.hsl] * self.H, "lsl": [site.lsl] * self.H,
                    "hbsoc": [site.soc0] * self.H, "min_soc": [site.e_min] * self.H, "max_soc": [site.e_max] * self.H}
        self.cop_touched = [False] * self.H
        self.druc: list[dict | None] = [None] * n
        self.dam_award: list[float | None] = [None] * self.H
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

    def clear_dam(self, day: int) -> None:
        for H in range(24 * day, 24 * day + 24):
            c = self.dam_curve[H]
            mw = 0.0 if c is None else clear_any(c, self.ser.dam_spp[H])
            self.dam_award[H] = round(min(max(mw, self.cop["lsl"][H]), self.cop["hsl"][H]), 6) + 0.0

    def sced(self, k: int) -> None:
        s, t0, H = self.site, 5 * k, k // PER_H
        curve, src = self.curve_at(H, t0)
        lmp = self.ser.rt_lmp[k]
        x = clear(curve, lmp) if self.rtcb else clear_any(curve, lmp)
        ehsl, elsl, _ = self.event_limits(t0)
        soc = self.soc[k]
        lo_soc = min(0.0, -PER_H * (self.cop["max_soc"][H] - drift(s, soc)) / s.eta)
        hi_soc = max(0.0, s.eta * PER_H * (drift(s, soc) - self.cop["min_soc"][H]))
        hi = min(ehsl, self.cop["hsl"][H])
        lo = max(elsl, self.cop["lsl"][H])
        prev = self.bp[k - 1] if k else 0.0
        bp = min(max(x, prev - 5 * s.ramp), prev + 5 * s.ramp)
        bp = min(max(bp, lo), hi)
        bp = min(max(bp, lo_soc), hi_soc)
        if self.cop["status"][H] in IDLE_STATUSES:
            bp, src = 0.0, "status"
        m = bp
        for e in self.ser.unit_events:
            if t0 < e["t_start"] < t0 + 5:
                f = (t0 + 5 - e["t_start"]) / 5.0
                m = bp * (1 - f) + min(max(bp, float(e.get("lsl_mw", 0.0))), float(e.get("hsl_mw", 0.0))) * f
        m = min(max(m, lo_soc), hi_soc)
        self.bp[k], self.metered[k], self.source[k] = round(bp, 6) + 0.0, round(m, 6) + 0.0, src
        self.soc[k + 1] = next_soc(s, soc, m)

    def soc_at(self, t: float) -> float:
        return self.soc[min(max(int(t // 5), 0), self.K)]
