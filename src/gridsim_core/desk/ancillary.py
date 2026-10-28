"""Ancillary services on the desk (contract section 10, v3): the ESR's products, their SoC duration rules per era,
AS offer validation, ERCOT's proxy AS offers and the price-taker energy + AS co-clearing used by the DAM and by SCED.

Sources (desk-research.md): products and ESR restrictions §2c, §4; durations §4a (NPRR1282 post-RTC+B; NPRR1186
remaining-hour rule before); PFR at most 20% of (HSL - LSL) §4a; proxy AS offers §2d (P§6.5.7.3(5)); DAM linkage
§3 (P§4.5.1(4)(c)(iii), P§3.18)."""

from __future__ import annotations

import datetime as dt

import numpy as np

from gridsim_core.contract import ECRS_START
from gridsim_core.desk.curves import bid_as_curve, clear, clear_any, extend_to_zero
from gridsim_core.lp import highspy

PRODUCTS = ("regup", "regdn", "rrspfr", "rrsffr", "ecrs", "nspin")
PRICE_KEY = {"regup": "regup", "regdn": "regdn", "rrspfr": "rrs", "rrsffr": "rrs", "ecrs": "ecrs", "nspin": "nspin"}
PRICES = ("regup", "regdn", "rrs", "ecrs", "nspin")
UP = ("regup", "rrspfr", "rrsffr", "ecrs", "nspin")
DOWN = ("regdn",)
NAMES = {"regup": "RegUp", "regdn": "RegDn", "rrspfr": "RRS-PFR", "rrsffr": "RRS-FFR", "ecrs": "ECRS",
         "nspin": "Non-Spin"}
DURATION_POST = {"regup": 0.5, "regdn": 0.5, "rrspfr": 0.5, "rrsffr": 0.25, "ecrs": 1.0, "nspin": 4.0}
DURATION_PRE = {"regup": 1.0, "regdn": 1.0, "rrspfr": 1.0, "rrsffr": 0.25, "ecrs": 2.0, "nspin": 4.0}
PFR_SHARE = 0.2
MAX_BLOCKS = 5
MIN_BLOCK_MW = 0.1
NPRR1186_START = dt.date(2024, 6, 27)
PROXY_FALLBACK = 1999.99
SUBSTEPS = 4
DEPLOY_FACTOR = 0.5
RT_DA_RATIO = {"regup": 1.20 / 3.57, "regdn": 1.13 / 1.79, "rrs": 0.41 / 3.30, "ecrs": 0.71 / 3.67,
               "nspin": 1.10 / 3.94}
REG_MEAN = {"up": 0.17, "dn": 0.20}


def products_on(date: str) -> tuple[str, ...]:
    return PRODUCTS if dt.date.fromisoformat(date) >= ECRS_START else tuple(p for p in PRODUCTS if p != "ecrs")


def durations(rtcb: bool) -> dict[str, float]:
    return DURATION_POST if rtcb else DURATION_PRE


def soc_rule_pre(date: str) -> bool:
    """Before RTC+B SCED reserved SoC for AS responsibilities only from NPRR1186 (2024-06-27)."""
    return dt.date.fromisoformat(date) >= NPRR1186_START


def remaining_hour_duration(product: str, minute_in_hour: float) -> float:
    """NPRR1186: responsibility x the time left in the operating hour; FFR 0.25 h (desk-research.md §4a)."""
    return 0.25 if product == "rrsffr" else max(60.0 - minute_in_hour, 0.0) / 60.0


def _err(code: str, text: str) -> dict:
    return {"code": code, "text": text}


def check_as_offer(product, blocks, cap: float, range_mw: float, date: str) -> list[dict]:
    """ASO codes for one product's offer in one hour: blocks [[mw, price], ...] (P§4.4.7.2.1, MSVR)."""
    if product not in PRODUCTS:
        return [_err("ASO-01", f"product {product!r} not in {list(PRODUCTS)} (an ESR may not offer UFR, off-line "
                               "reserves or ECRS-MD)")]
    if product not in products_on(date):
        return [_err("ASO-01", "ECRS does not exist before 2023-06-10")]
    if not isinstance(blocks, list) or not 1 <= len(blocks) <= MAX_BLOCKS:
        return [_err("ASO-02", f"1 to {MAX_BLOCKS} blocks of [mw, price]")]
    errs = []
    for b in blocks:
        if (not isinstance(b, list | tuple) or len(b) != 2
                or not all(isinstance(x, int | float) and not isinstance(x, bool) for x in b)):
            return [_err("ASO-02", f"block {b!r} is not [mw, price]")]
        if b[0] < MIN_BLOCK_MW:
            errs.append(_err("ASO-03", f"block of {b[0]:g} MW; minimum {MIN_BLOCK_MW} MW"))
        if not 0.0 <= b[1] <= cap:
            errs.append(_err("ASO-04", f"price {b[1]:g} outside [0, {cap:g}] $/MW/h"))
    total = sum(float(b[0]) for b in blocks)
    limit = PFR_SHARE * range_mw if product == "rrspfr" else range_mw
    if total > limit + 1e-6:
        errs.append(_err("ASO-05", f"{total:g} MW offered; at most {limit:g} MW of {NAMES[product]}"))
    return errs[:1]


def proxy_offer(site_range: float, asdc_hour: list | None, plan_mw: float | None, highest: float | None) -> list:
    """ERCOT's linked proxy AS offer: HSL - LSL MW at min($2,000, ASDC price at 95% of the AS Plan) - $0.01, or the
    resource's highest submitted price if higher (P§6.5.7.3(5))."""
    price = PROXY_FALLBACK
    if asdc_hour and plan_mw:
        price = min(2000.0, asdc_price(asdc_hour, 0.95 * plan_mw)) - 0.01
    if highest is not None:
        price = max(price, highest)
    return [[site_range, round(max(price, 0.0), 2)]]


def asdc_price(points: list, mw: float) -> float:
    """The demand curve's price at `mw` (piecewise linear, flat beyond its ends)."""
    pts = sorted((float(q), float(p)) for q, p in points)
    if mw <= pts[0][0]:
        return pts[0][1]
    for (q0, p0), (q1, p1) in zip(pts, pts[1:], strict=False):
        if mw <= q1:
            return p0 + (p1 - p0) * (mw - q0) / (q1 - q0) if q1 > q0 else p1
    return pts[-1][1]


def segments(curve, rtcb: bool) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """(discharge increments, charge increments) as (MW, price) steps of the piecewise-linear curve."""
    if rtcb:
        pts = extend_to_zero([(float(q), float(p)) for q, p in curve])
    else:
        pts = []
        if curve.get("bid"):
            pts += bid_as_curve(curve["bid"])
        if curve.get("offer"):
            pts += extend_to_zero([(float(q), float(p)) for q, p in curve["offer"]])
    dis, chg = [], []
    for (qa, pa), (qb, pb) in zip(pts, pts[1:], strict=False):
        if qb <= qa:
            continue
        for i in range(SUBSTEPS):
            lo, hi = qa + (qb - qa) * i / SUBSTEPS, qa + (qb - qa) * (i + 1) / SUBSTEPS
            price = pa + (pb - pa) * ((lo + hi) / 2 - qa) / (qb - qa)
            if lo >= 0:
                dis.append((hi - lo, price))
            elif hi <= 0:
                chg.append((hi - lo, price))
            else:
                dis.append((hi, price))
                chg.append((-lo, price))
    return dis, chg


def co_clear(curve, rtcb: bool, price: float, offers: dict, mcpc: dict, hi: float, lo: float,
             caps: dict | None = None, soc_up: float | None = None, soc_dn: float | None = None,
             dur: dict | None = None, dt_h: float = 1 / 12) -> tuple[float, dict]:
    """Price-taker co-clearing of one interval: energy MW and AS awards maximising the offers' surplus at `price`
    and `mcpc`, with up/down headroom inside [lo, hi] (P§3.18) and, when given, the SoC energy the awards need
    (`soc_up` / `soc_dn` grid MWh available over `dur` hours each)."""
    offers = {p: b for p, b in (offers or {}).items() if b}
    if not offers:
        x = clear(curve, price) if rtcb else clear_any(curve, price)
        return min(max(x, lo), hi), {}
    dis, chg = segments(curve, rtcb)
    blocks = [(p, float(mw), float(pr)) for p, bl in offers.items() for mw, pr in bl]
    nd, nc, nb = len(dis), len(chg), len(blocks)
    n = nd + nc + nb
    cost = np.array([price - p for _, p in dis] + [p - price for _, p in chg]
                    + [mcpc.get(PRICE_KEY[p], 0.0) - pr for p, _, pr in blocks])
    upper = np.array([m for m, _ in dis] + [m for m, _ in chg] + [m for _, m, _ in blocks])
    rows = []
    g = [(i, 1.0) for i in range(nd)]
    lneg = [(nd + j, -1.0) for j in range(nc)]
    up = [(nd + nc + b, 1.0) for b, (p, _, _) in enumerate(blocks) if p in UP]
    dn = [(nd + nc + b, -1.0) for b, (p, _, _) in enumerate(blocks) if p in DOWN]
    rows.append((g + lneg + up, -np.inf, hi))
    rows.append((g + lneg + dn, lo, np.inf))
    for p in {p for p, _, _ in blocks}:
        cap = (caps or {}).get(p)
        if cap is not None:
            rows.append(([(nd + nc + b, 1.0) for b, (q, _, _) in enumerate(blocks) if q == p], -np.inf, cap))
    if soc_up is not None and dur:
        rows.append(([(i, dt_h) for i in range(nd)] + [(nd + nc + b, dur[p]) for b, (p, _, _) in enumerate(blocks)
                                                         if p in UP], -np.inf, max(soc_up, 0.0)))
    if soc_dn is not None and dur:
        rows.append(([(nd + j, dt_h) for j in range(nc)] + [(nd + nc + b, dur[p]) for b, (p, _, _)
                                                            in enumerate(blocks) if p in DOWN], -np.inf,
                     max(soc_dn, 0.0)))
    x = solve_small(cost, upper, rows, n)
    q = float(sum(x[:nd]) - sum(x[nd:nd + nc]))
    awards: dict[str, float] = {}
    for b, (p, _, _) in enumerate(blocks):
        if x[nd + nc + b] > 1e-7:
            awards[p] = awards.get(p, 0.0) + float(x[nd + nc + b])
    return q, {p: round(v, 6) for p, v in awards.items()}


def solve_small(cost, upper, rows, n: int) -> np.ndarray:
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = n, len(rows)
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = np.asarray(cost, float), np.zeros(n), np.asarray(upper, float)
    lp.row_lower_ = np.array([a for _, a, _ in rows], float)
    lp.row_upper_ = np.array([b for _, _, b in rows], float)
    lp.sense_ = highspy.ObjSense.kMaximize
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    start, index, value = [0], [], []
    for entries, _, _ in rows:
        for c, v in sorted(entries):
            index.append(c)
            value.append(v)
        start.append(len(index))
    lp.a_matrix_.start_ = np.array(start, np.int32)
    lp.a_matrix_.index_ = np.array(index, np.int32)
    lp.a_matrix_.value_ = np.array(value, float)
    h.passModel(lp)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        return np.zeros(n)
    return np.asarray(h.getSolution().col_value)
