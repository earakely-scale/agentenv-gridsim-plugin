"""The desk co-optimiser (contract section 8): one HiGHS LP over DAM positions and 5-minute RT dispatch with SoC,
standby losses, warranty cycles and the end-SoC value; water values turn the plan into ERCOT curves and a COP.

It serves the agent's `optimize` tool, the information-matched anchor and the hindsight optimum, and only ever sees the
price paths it is given."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from gridsim_core.desk.ancillary import (
    DEPLOY_FACTOR,
    DURATION_POST,
    PRICE_KEY,
    REG_MEAN,
    remaining_hour_duration,
)
from gridsim_core.desk.curves import monotone, reduce
from gridsim_core.desk.engine import PER_H, Site
from gridsim_core.desk.settle import SPD_FLOOR
from gridsim_core.lp import highspy

EPS_TIE = 1e-3
EPS_CYCLE = 1e-4
SHORT_PEN = 500.0


@dataclass
class Problem:
    """Everything the LP needs, on the episode grid; slots before `k0` are history and ignored. The AS fields are
    empty for the energy-only layer."""

    site: Site
    days: int
    k0: int
    soc: float
    dam: list[float]
    rt: list[float]
    dam_open: list[bool]
    dam_fixed: list[float]
    hsl: list[float]
    lsl: list[float]
    min_soc: list[float]
    max_soc: list[float]
    discharged_today: float
    target: float
    pen: float
    products: tuple = ()
    rtcb: bool = True
    soc_rule: bool = True
    as_dam: dict = field(default_factory=dict)
    as_rt: dict = field(default_factory=dict)
    as_fixed: list = field(default_factory=list)
    as_cap: list = field(default_factory=list)
    reg_up: list = field(default_factory=list)
    reg_dn: list = field(default_factory=list)
    pv: list = field(default_factory=list)
    poi: float | None = None
    dam_tied: bool = False
    dam_hsl: list = field(default_factory=list)
    dam_lsl: list = field(default_factory=list)


@dataclass
class Plan:
    objective: float
    c: np.ndarray
    d: np.ndarray
    s: np.ndarray
    q: dict
    lam: np.ndarray
    k0: int
    r: dict = field(default_factory=dict)
    R: dict = field(default_factory=dict)

    def net(self) -> np.ndarray:
        return self.d - self.c

    def hourly_net(self, H: int) -> float:
        lo = max(PER_H * H, self.k0)
        hi = PER_H * (H + 1)
        if hi <= self.k0:
            return 0.0
        return float(np.sum(self.net()[lo - self.k0:hi - self.k0]) / PER_H)

    def hourly_as(self, product: str, H: int) -> float:
        """Mean planned RT award (post) or the DAM reservation (pre) of `product` over hour H."""
        if (product, H) in self.R and product not in self.r:
            return self.R[(product, H)]
        v = self.r.get(product)
        lo, hi = max(PER_H * H, self.k0), PER_H * (H + 1)
        if v is None or hi <= lo:
            return 0.0
        return float(np.mean(v[lo - self.k0:hi - self.k0]))

    def soc_at(self, k: int) -> float:
        return float(self.s[k - self.k0 - 1]) if k > self.k0 else float("nan")

    def hour_lambda(self, H: int) -> float | None:
        lo, hi = max(PER_H * H, self.k0), PER_H * (H + 1)
        if hi <= lo:
            return None
        return float(np.mean(self.lam[lo - self.k0:hi - self.k0]))


def _dur(p: Problem, product: str, k: int) -> float:
    if p.rtcb:
        return DURATION_POST[product]
    return remaining_hour_duration(product, 5 * (k % PER_H))


def solve(p: Problem) -> Plan:
    if highspy is None:
        raise RuntimeError("the desk optimiser needs highspy (pip install highspy)")
    s, K = p.site, 288 * p.days
    n = K - p.k0
    if n <= 0:
        return Plan(0.0, np.zeros(0), np.zeros(0), np.zeros(0), {}, np.zeros(0), p.k0)
    eta, rho = s.eta, s.rho
    shift = s.e_min * (1 - rho)
    nH = 24 * p.days
    open_h = [H for H in range(nH) if p.dam_open[H]]
    first_h = p.k0 // PER_H
    C, D, S = 0, n, 2 * n
    qi = {H: 3 * n + 3 * i for i, H in enumerate(open_h)}
    col = 3 * n + 3 * len(open_h)
    W = col
    U = W + p.days
    col = U + 1
    prods = tuple(p.products)
    ri: dict[str, int] = {}
    if p.rtcb:
        for pr in prods:
            ri[pr] = col
            col += n
    Ri: dict[tuple[str, int], int] = {}
    for pr in prods:
        for H in open_h:
            Ri[(pr, H)] = col
            col += 1
    ncol = col
    cost = np.zeros(ncol)
    lo = np.zeros(ncol)
    hi = np.full(ncol, np.inf)
    ks = np.arange(p.k0, K)
    hs = ks // PER_H
    rt = np.asarray(p.rt, dtype=float)[ks]
    cost[C:C + n] = -rt / PER_H - EPS_CYCLE
    cost[D:D + n] = rt / PER_H - s.deg / PER_H - EPS_CYCLE
    hsl = np.asarray(p.hsl, dtype=float)[hs]
    lsl = np.asarray(p.lsl, dtype=float)[hs]
    if p.pv and p.poi is not None:
        pvk = np.asarray(p.pv, dtype=float)[ks]
        hsl = np.minimum(hsl, p.poi - pvk)
        lsl = np.maximum(lsl, -p.poi - pvk)
    hi[C:C + n] = np.maximum(-lsl, 0.0)
    hi[D:D + n] = np.maximum(hsl, 0.0)
    cop_lo = np.asarray(p.min_soc, dtype=float)[hs]
    cop_hi = np.asarray(p.max_soc, dtype=float)[hs]
    lo[S:S + n] = min(s.e_min, p.soc)
    hi[S:S + n] = max(s.e_max, p.soc)
    rt_all = np.asarray(p.rt, dtype=float)
    for H, j in qi.items():
        rt_mean = float(np.mean(rt_all[PER_H * H:PER_H * (H + 1)]))
        cost[j] = p.dam[H] - rt_mean
        lo[j] = min((p.dam_lsl or p.lsl)[H], 0.0)
        hi[j] = max((p.dam_hsl or p.hsl)[H], 0.0)
        cost[j + 1] = cost[j + 2] = -EPS_TIE
        if p.dam_tied:
            hi[j + 1] = hi[j + 2] = 0.0
    cost[W:W + p.days] = -2 * s.deg
    cost[U] = -p.pen
    rng = s.hsl - s.lsl
    fu = np.asarray(p.reg_up or [REG_MEAN["up"]] * nH, dtype=float)[hs]
    fd = np.asarray(p.reg_dn or [REG_MEAN["dn"]] * nH, dtype=float)[hs]

    def cap(pr: str, H: int) -> float:
        c = rng
        if p.as_cap and p.as_cap[H] and pr in p.as_cap[H]:
            c = min(c, p.as_cap[H][pr])
        return c

    for pr in prods:
        pk = PRICE_KEY[pr]
        dam_p = np.asarray(p.as_dam.get(pk, [0.0] * nH), dtype=float)
        for H in open_h:
            j = Ri[(pr, H)]
            hi[j] = cap(pr, H)
            if p.rtcb:
                rt_p = np.asarray(p.as_rt.get(pk, [0.0] * K), dtype=float)
                cost[j] = dam_p[H] - float(np.mean(rt_p[PER_H * H:PER_H * (H + 1)]))
            else:
                cost[j] = dam_p[H]
        if p.rtcb:
            rt_p = np.asarray(p.as_rt.get(pk, [0.0] * K), dtype=float)[ks]
            cost[ri[pr]:ri[pr] + n] = rt_p / PER_H - EPS_TIE / PER_H
            if pr == "regup":
                cost[ri[pr]:ri[pr] + n] += rt * fu / PER_H
            if pr == "regdn":
                cost[ri[pr]:ri[pr] + n] -= rt * fd / PER_H
            for i in range(n):
                hi[ri[pr] + i] = cap(pr, int(hs[i]))
        elif pr in ("regup", "regdn"):
            for H in open_h:
                k_in = [k for k in range(PER_H * H, PER_H * (H + 1)) if k >= p.k0]
                val = sum(p.rt[k] * (fu[k - p.k0] if pr == "regup" else -fd[k - p.k0]) for k in k_in) / PER_H
                cost[Ri[(pr, H)]] += val

    def as_terms(pr: str, i: int) -> tuple[list, float]:
        """(column entries, constant MW) of product pr's award in interval i."""
        H = int(hs[i])
        if p.rtcb:
            return [(ri[pr] + i, 1.0)], 0.0
        if (pr, H) in Ri:
            return [(Ri[(pr, H)], 1.0)], 0.0
        fixed = p.as_fixed[H].get(pr, 0.0) if p.as_fixed else 0.0
        return [], fixed

    rows, cols, vals, rlo, rhi = [], [], [], [], []
    r = 0

    def add(entries, a, b):
        nonlocal r
        for c_, v in entries:
            rows.append(r)
            cols.append(c_)
            vals.append(v)
        rlo.append(a)
        rhi.append(b)
        r += 1

    bal0 = r
    for i in range(n):
        e = [(S + i, 1.0), (C + i, -eta / PER_H), (D + i, 1.0 / (eta * PER_H))]
        const = 0.0
        for pr, f, sign in (("regup", fu[i], 1.0), ("regdn", fd[i], -1.0)):
            if pr in prods:
                terms, fixed = as_terms(pr, i)
                coef = (1.0 / eta if sign > 0 else -eta) * f / PER_H
                e += [(c_, coef * v) for c_, v in terms]
                const -= coef * fixed
        if i:
            e.append((S + i - 1, -rho))
            add(e, shift + const, shift + const)
        else:
            add(e, rho * p.soc + shift + const, rho * p.soc + shift + const)
    for i in range(n):
        e = []
        if hi[C + i] > 0:
            e.append((C + i, 1.0 / hi[C + i]))
        if hi[D + i] > 0:
            e.append((D + i, 1.0 / hi[D + i]))
        if e:
            add(e, -np.inf, 1.0)
    slack_cols: list[int] = []

    def slack() -> list[tuple[int, float]]:
        slack_cols.append(len(cost_extra))
        cost_extra.append(-SHORT_PEN / PER_H)
        return [(ncol + len(cost_extra) - 1, 1.0)]

    cost_extra: list[float] = []
    for i in range(n):
        if cop_lo[i] > lo[S + i] + 1e-9:
            add([(S + i, 1.0)] + slack(), float(cop_lo[i]), np.inf)
        if cop_hi[i] < hi[S + i] - 1e-9:
            add([(S + i, 1.0)] + [(c_, -v) for c_, v in slack()], -np.inf, float(cop_hi[i]))
    if prods:
        for i in range(n):
            up_e, up_c, soc_e, soc_c = [], 0.0, [], 0.0
            for pr in prods:
                if pr == "regdn":
                    continue
                terms, fixed = as_terms(pr, i)
                up_e += terms
                up_c += fixed
                d_ = _dur(p, pr, p.k0 + i)
                soc_e += [(c_, v * d_) for c_, v in terms]
                soc_c += fixed * d_
            relax = [(c_, -v) for c_, v in slack()] if up_c else []
            add([(D + i, 1.0), (C + i, -1.0)] + up_e + relax, -np.inf, float(hsl[i]) - up_c)
            if "regdn" in prods:
                terms, fixed = as_terms("regdn", i)
                relax = slack() if fixed else []
                add([(D + i, 1.0), (C + i, -1.0)] + [(c_, -v) for c_, v in terms] + relax, float(lsl[i]) + fixed,
                    np.inf)
                if p.soc_rule:
                    d_ = _dur(p, "regdn", p.k0 + i)
                    relax = [(c_, -v) for c_, v in slack()]
                    add([(S + i, 1.0 / eta)] + [(c_, v * d_) for c_, v in terms] + relax, -np.inf,
                        float(cop_hi[i]) / eta - fixed * d_)
            if p.soc_rule and (soc_e or soc_c):
                relax = slack()
                add([(S + i, eta)] + [(c_, -v) for c_, v in soc_e] + relax, float(cop_lo[i]) * eta + soc_c, np.inf)
    if prods:
        for H, j in qi.items():
            up = [(Ri[(pr, H)], 1.0) for pr in prods if pr != "regdn" and (pr, H) in Ri]
            add([(j, 1.0)] + up, -np.inf, max((p.dam_hsl or p.hsl)[H], 0.0))
            k_start = PER_H * H - p.k0
            if p.rtcb and up and k_start >= 1:
                add([(S + k_start - 1, eta)] + [(Ri[(pr, H)], -DURATION_POST[pr] * DEPLOY_FACTOR)
                                                for pr in prods if pr != "regdn" and (pr, H) in Ri],
                    float(cop_lo[k_start - 1]) * eta, np.inf)
            if ("regdn", H) in Ri:
                add([(j, 1.0), (Ri[("regdn", H)], -1.0)], min((p.dam_lsl or p.lsl)[H], 0.0), np.inf)
    if prods and p.rtcb and p.as_fixed:
        for H in range(first_h + 1, nH):
            need = sum(mw * DURATION_POST[pr] * DEPLOY_FACTOR for pr, mw in p.as_fixed[H].items() if pr != "regdn")
            k_start = PER_H * H - p.k0
            if need > 0 and not p.dam_open[H] and 1 <= k_start <= n:
                add([(S + k_start - 1, eta)] + slack(), float(cop_lo[k_start - 1]) * eta + need, np.inf)
    for H, j in qi.items():
        e = [(j, 1.0), (j + 1, -1.0), (j + 2, 1.0)]
        for k in range(max(PER_H * H, p.k0), PER_H * (H + 1)):
            e += [(D + k - p.k0, -1.0 / PER_H), (C + k - p.k0, 1.0 / PER_H)]
        add(e, 0.0, 0.0)
    for day in range(p.days):
        ks_day = [k for k in range(288 * day, 288 * day + 288) if k >= p.k0]
        if not ks_day:
            continue
        done = p.discharged_today if p.k0 // 288 == day else 0.0
        add([(D + k - p.k0, 1.0 / PER_H) for k in ks_day] + [(W + day, -1.0)], -np.inf,
            s.warranty * s.usable - done)
    add([(S + n - 1, 1.0), (U, 1.0)], p.target, np.inf)
    if cost_extra:
        cost = np.concatenate([cost, cost_extra])
        lo = np.concatenate([lo, np.zeros(len(cost_extra))])
        hi = np.concatenate([hi, np.full(len(cost_extra), np.inf)])
        ncol += len(cost_extra)
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = ncol, r
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = cost, lo, hi
    lp.row_lower_, lp.row_upper_ = np.array(rlo, dtype=float), np.array(rhi, dtype=float)
    lp.sense_ = highspy.ObjSense.kMaximize
    order = np.lexsort((np.asarray(cols), np.asarray(rows)))
    rr, cc, vv = np.asarray(rows)[order], np.asarray(cols)[order], np.asarray(vals)[order]
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    lp.a_matrix_.start_ = np.searchsorted(rr, np.arange(r + 1)).astype(np.int32)
    lp.a_matrix_.index_ = cc.astype(np.int32)
    lp.a_matrix_.value_ = vv
    h.passModel(lp)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"desk LP not optimal: {h.modelStatusToString(h.getModelStatus())}")
    x = np.asarray(h.getSolution().col_value)
    lam = np.asarray(h.getSolution().row_dual)[bal0:bal0 + n].copy()
    fixed = sum(p.dam_fixed[H] * (p.dam[H] - float(np.mean(rt_all[PER_H * H:PER_H * (H + 1)])))
                for H in range(nH) if not p.dam_open[H] and PER_H * (H + 1) > p.k0)
    if p.as_fixed:
        for H in range(max(first_h, 0), nH):
            if p.dam_open[H] or not p.as_fixed[H]:
                continue
            for pr, mw in p.as_fixed[H].items():
                pk = PRICE_KEY[pr]
                rt_m = float(np.mean(np.asarray(p.as_rt.get(pk, [0.0] * K))[PER_H * H:PER_H * (H + 1)])) \
                    if p.rtcb else 0.0
                fixed += mw * ((p.as_dam.get(pk) or [0.0] * nH)[H] - rt_m)
    return Plan(float(h.getInfo().objective_function_value) + fixed, x[C:C + n], x[D:D + n], x[S:S + n],
                {H: float(x[j]) for H, j in qi.items()}, lam, p.k0,
                {pr: x[c_:c_ + n].copy() for pr, c_ in ri.items()}, {key: float(x[c_]) for key, c_ in Ri.items()})


def hour_curves(site: Site, lams: list[float], risk: float, dis_cap: float | None = None,
                ch_cap: float | None = None, lsl: float | None = None, hsl: float | None = None) -> list[list[float]]:
    """An EB/OC from scenario water values: charge below eta*lambda, discharge above lambda/eta + degradation."""
    eta = site.eta
    mid = lams[len(lams) // 2] if len(lams) % 2 else sum(lams) / len(lams)
    lo_l = mid - risk * (mid - min(lams))
    hi_l = mid + risk * (max(lams) - mid)
    lsl = site.lsl if lsl is None else lsl
    hsl = site.hsl if hsl is None else hsl
    lsl = max(lsl, ch_cap) if ch_cap is not None else lsl
    hsl = min(hsl, dis_cap) if dis_cap is not None else hsl
    pts = []
    if lsl < 0:
        pts += [(lsl, eta * lo_l), (0.0, eta * hi_l)]
    pts += [(0.0, lo_l / eta + site.deg)]
    if hsl > 0:
        pts += [(hsl, hi_l / eta + site.deg)]
    pts = [(q, min(max(p, -250.0), 2000.0)) for q, p in pts]
    out = monotone(pts)
    if len(out) < 2:
        out = reduce([out[0], [out[0][0], min(out[0][1] + 1.0, 2000.0)]])
    return out


def end_penalty(site: Site, last_day_dam: list[float]) -> float:
    return max(sum(last_day_dam) / len(last_day_dam), SPD_FLOOR) / site.eta
