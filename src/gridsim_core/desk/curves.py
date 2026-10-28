"""ESR offer curves: validation with ERCOT-style codes, the 0 MW extension and price-taker clearing.

Post-RTC+B a curve is the single-model Energy Bid/Offer Curve (P§4.4.9.7.1): [[mw, price], ...] from max charge
(negative MW) to max discharge. Pre-RTC+B a curve is {"offer": Gen Resource offer, "bid": charging bid}, both MW >= 0."""

from __future__ import annotations

import math

from gridsim_core.contract import era as contract_era

FLOOR = -250.0
MAX_POINTS = 10
MW_TOL = 1e-6


def caps(date: str, rtcb: bool) -> dict:
    """Offer caps in force: post-RTC+B DASWCAP $5,000 and RTSWCAP $2,000 (P§4.4.11); before, one SWCAP (HCAP)."""
    if rtcb:
        return {"dam": 5000.0, "rt": 2000.0, "floor": FLOOR}
    h = contract_era(date)["hcap"]
    return {"dam": h, "rt": h, "floor": FLOOR}


def _err(code: str, text: str) -> dict:
    return {"code": code, "text": text}


def _pairs(points, code: str) -> tuple[list[tuple[float, float]] | None, list[dict]]:
    if not isinstance(points, list | tuple) or not points:
        return None, [_err(code, "points must be a non-empty list of [mw, price] pairs")]
    out = []
    for p in points:
        if (not isinstance(p, list | tuple) or len(p) != 2
                or not all(isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x) for x in p)):
            return None, [_err(code, f"point {p!r} is not a [mw, price] pair of numbers")]
        out.append((float(p[0]), float(p[1])))
    return out, []


def _runs(pts, idx: int) -> bool:
    return any(pts[i][idx] == pts[i + 1][idx] == pts[i + 2][idx] for i in range(len(pts) - 2))


def check_eboc(points, cap: float, lsl: float, hsl: float, prefix: str = "EBOC") -> tuple[list[dict], list[dict]]:
    """(errors, warnings) for one post-RTC+B EB/OC against the cap in force and the site's nameplate limits."""
    pts, errs = _pairs(points, f"{prefix}-01")
    if errs:
        return errs, []
    if not 2 <= len(pts) <= MAX_POINTS:
        errs.append(_err(f"{prefix}-01", f"{len(pts)} points; a curve has 2 to {MAX_POINTS} price/MW points"))
    if any(b[0] < a[0] - MW_TOL or b[1] < a[1] for a, b in zip(pts, pts[1:], strict=False)):
        errs.append(_err(f"{prefix}-02", "MW and price must both be non-decreasing from max charge to max discharge"))
    if _runs(pts, 0) or _runs(pts, 1):
        errs.append(_err(f"{prefix}-03", "no more than two consecutive points may share a price or a MW value"))
    bad = [p for _, p in pts if p < FLOOR or p > cap]
    if bad:
        errs.append(_err(f"{prefix}-04", f"price {bad[0]:g} outside [{FLOOR:g}, {cap:g}] $/MWh"))
    if any(q < lsl - MW_TOL or q > hsl + MW_TOL for q, _ in pts):
        errs.append(_err(f"{prefix}-05", f"MW outside the resource's limits [{lsl:g}, {hsl:g}]"))
    return errs, []


def check_side(points, cap: float, limit: float, side: str) -> list[dict]:
    """Pre-RTC+B Gen Resource offer (`offer`, GOC) or charging bid (`bid`, LRB); MW >= 0 consumed or produced."""
    code = "GOC" if side == "offer" else "LRB"
    pts, errs = _pairs(points, f"{code}-01")
    if errs:
        return errs
    lo = 2 if side == "offer" else 1
    if not lo <= len(pts) <= MAX_POINTS:
        errs.append(_err(f"{code}-01", f"{len(pts)} points; {lo} to {MAX_POINTS} allowed"))
    if any(q < -MW_TOL for q, _ in pts) or any(b[0] <= a[0] for a, b in zip(pts, pts[1:], strict=False)):
        errs.append(_err(f"{code}-02", "MW must be >= 0 and increasing"))
    mono = (lambda a, b: b[1] < a[1]) if side == "offer" else (lambda a, b: b[1] > a[1])
    if any(mono(a, b) for a, b in zip(pts, pts[1:], strict=False)):
        errs.append(_err(f"{code}-03", "offer prices must be non-decreasing" if side == "offer"
                         else "bid prices must be non-increasing as MW increases"))
    bad = [p for _, p in pts if p < FLOOR or p > cap]
    if bad:
        errs.append(_err(f"{code}-04", f"price {bad[0]:g} outside [{FLOOR:g}, {cap:g}] $/MWh"))
    if any(q > limit + MW_TOL for q, _ in pts):
        errs.append(_err("GOC-05", f"MW above the resource's limit {limit:g}"))
    return errs


def extend_to_zero(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """A curve that misses 0 MW is extended to 0 at the nearest point's price (RTCBTF "DAM ESR Offers", 2025-02-07)."""
    if pts[0][0] > 0:
        return [(0.0, pts[0][1])] + pts
    if pts[-1][0] < 0:
        return pts + [(0.0, pts[-1][1])]
    return pts


def clear(points, price: float) -> float:
    """MW cleared at `price`: max{q : price(q) <= p} on the piecewise-linear curve, the first MW below its price."""
    pts = extend_to_zero([(float(q), float(p)) for q, p in points])
    if price < pts[0][1]:
        return pts[0][0]
    if price >= pts[-1][1]:
        return pts[-1][0]
    j = max(i for i, (_, p) in enumerate(pts) if p <= price)
    (q0, p0), (q1, p1) = pts[j], pts[j + 1]
    return q0 + (q1 - q0) * (price - p0) / (p1 - p0)


def bid_as_curve(bid) -> list[tuple[float, float]]:
    """A pre-RTC+B charging bid (MW >= 0 consumed, price non-increasing) as the charge side of an EB/OC."""
    pts = [(-float(q), float(p)) for q, p in reversed(bid)]
    return pts if pts[-1][0] == 0 else pts + [(0.0, pts[-1][1])]


def clear_pre(curve: dict, price: float) -> float:
    """Net MW of a pre-RTC+B combo: gen offer cleared minus charging bid cleared."""
    out = 0.0
    if curve.get("offer"):
        out += max(clear(curve["offer"], price), 0.0)
    if curve.get("bid"):
        out += min(clear(bid_as_curve(curve["bid"]), price), 0.0)
    return out


def clear_any(curve, price: float) -> float:
    return clear_pre(curve, price) if isinstance(curve, dict) else clear(curve, price)


def reduce(points) -> list[list[float]]:
    """Drop exact duplicates and the middle of any three consecutive points sharing a price or a MW (no change in q(p))."""
    pts = []
    for q, p in points:
        pt = (round(float(q), 3), round(float(p), 2))
        if not pts or pt != pts[-1]:
            pts.append(pt)
    i = 0
    while i < len(pts) - 2:
        a, b, c = pts[i], pts[i + 1], pts[i + 2]
        if a[0] == b[0] == c[0] or a[1] == b[1] == c[1]:
            del pts[i + 1]
        else:
            i += 1
    return [list(p) for p in pts]


def monotone(points) -> list[list[float]]:
    """Sort by MW and lift prices to be non-decreasing."""
    pts = sorted((float(q), float(p)) for q, p in points)
    out, top = [], -math.inf
    for q, p in pts:
        top = max(top, p)
        out.append((q, top))
    return reduce(out)


def flat(mw: float = 0.0) -> list[list[float]]:
    """A self-schedule at `mw`: the same MW at the floor and at the RT cap."""
    return [[mw, FLOOR], [mw, 2000.0]]
