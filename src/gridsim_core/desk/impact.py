"""v5 "The Market Floor": the battery's DAM curve re-cleared against the day's disclosed offer stack (NP3-966-ER,
the site's own resource carved out), reusing the previews' market_auction book and uniform-price clear. The re-cleared
system price moves the node price by the same amount (the node-hub basis is held at its real value); RT stays
price-taker. No market-power mitigation is applied [simplified]."""

from __future__ import annotations

import numpy as np

from gridsim_core.desk.ancillary import segments
from gridsim_core.desk.curves import clear_any
from gridsim_core.market_auction import book, clear_hour
from gridsim_core.market_stack import hour_curves

SEAT = "desk"
GRID_MW = 0.1


class Stack:
    """One operating day's re-clear: per hour the background book at hub prices and the node basis."""

    def __init__(self, day: dict, node_dam: list[float], floor: float, cap: float):
        self.day, self.floor, self.cap = day, floor, cap
        hub = np.asarray(day["hub_dam_usd"], float)
        replay = np.asarray((day.get("replay") or {}).get("lambda_usd") or day["lambda_usd"], float)
        self.offset = hub - replay
        self.basis = np.asarray(node_dam, float) - hub
        self._books: dict[int, object] = {}

    def book(self, h: int):
        if h not in self._books:
            sup, dem = hour_curves(self.day, h)
            self._books[h] = book(self.floor, self.cap, sup, dem, {}, 0.0, float(self.offset[h]))
        return self._books[h]

    def blocks(self, curve, rtcb: bool, h: int) -> list:
        dis, chg = segments(curve, rtcb)
        b = float(self.basis[h])
        return ([(SEAT, 1, mw, p - b, None) for mw, p in dis if mw > 0]
                + [(SEAT, -1, mw, p - b, None) for mw, p in chg if mw > 0])

    def clear(self, h: int, curve, rtcb: bool) -> tuple[float, float]:
        """(node DAM price, the battery's MW) of hour h with `curve` in the auction (None: not in it)."""
        blocks = self.blocks(curve, rtcb, h) if curve is not None else []
        res = clear_hour(self.book(h), blocks, {SEAT: GRID_MW})
        price = float(res.lam) + float(self.basis[h])
        mw = float(res.awards.get(SEAT, 0.0))
        if curve is not None and abs(mw - clear_any(curve, price)) > 1.0:
            mw = clear_any(curve, price)
        return round(price, 4), mw

    def self_schedule(self, h: int, mw: float) -> float:
        """Node DAM price with a fixed `mw` position (+ sells) in the auction."""
        if abs(mw) < 1e-9:
            return self.clear(h, None, True)[0]
        blocks = [(SEAT, 1 if mw > 0 else -1, abs(mw), self.floor if mw > 0 else self.cap, None)]
        res = clear_hour(self.book(h), blocks, {SEAT: GRID_MW})
        return round(float(res.lam) + float(self.basis[h]), 4)
