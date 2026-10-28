"""The desk co-optimiser (contract section 8): one HiGHS LP over DAM positions and 5-minute RT dispatch with SoC,
standby losses, warranty cycles and the end-SoC value; water values turn the plan into ERCOT curves and a COP.

It serves the agent's `optimize` tool, the information-matched anchor and the hindsight optimum, and only ever sees the
price paths it is given."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from gridsim_core.desk.curves import monotone, reduce
from gridsim_core.desk.engine import PER_H, Site
from gridsim_core.desk.settle import SPD_FLOOR
from gridsim_core.lp import highspy

EPS_TIE = 1e-3
EPS_CYCLE = 1e-4


@dataclass
class Problem:
    """Everything the LP needs, on the episode grid; slots before `k0` are history and ignored."""

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


@dataclass
class Plan:
    objective: float
    c: np.ndarray
    d: np.ndarray
    s: np.ndarray
    q: dict
    lam: np.ndarray
    k0: int

    def net(self) -> np.ndarray:
        return self.d - self.c

    def hourly_net(self, H: int) -> float:
        lo = max(PER_H * H, self.k0)
        hi = PER_H * (H + 1)
        if hi <= self.k0:
            return 0.0
        return float(np.sum(self.net()[lo - self.k0:hi - self.k0]) / PER_H)

    def soc_at(self, k: int) -> float:
        return float(self.s[k - self.k0 - 1]) if k > self.k0 else float("nan")

    def hour_lambda(self, H: int) -> float | None:
        lo, hi = max(PER_H * H, self.k0), PER_H * (H + 1)
        if hi <= lo:
            return None
        return float(np.mean(self.lam[lo - self.k0:hi - self.k0]))


def solve(p: Problem) -> Plan:
    if highspy is None:
        raise RuntimeError("the desk optimiser needs highspy (pip install highspy)")
    s, K = p.site, 288 * p.days
    n = K - p.k0
    if n <= 0:
        return Plan(0.0, np.zeros(0), np.zeros(0), np.zeros(0), {}, np.zeros(0), p.k0)
    eta, rho = s.eta, s.rho
    shift = s.e_min * (1 - rho)
    open_h = [H for H in range(24 * p.days) if p.dam_open[H]]
    C, D, S = 0, n, 2 * n
    qi = {H: 3 * n + 3 * i for i, H in enumerate(open_h)}
    W = 3 * n + 3 * len(open_h)
    U = W + p.days
    ncol = U + 1
    cost = np.zeros(ncol)
    lo = np.zeros(ncol)
    hi = np.full(ncol, np.inf)
    ks = np.arange(p.k0, K)
    rt = np.asarray(p.rt, dtype=float)[ks]
    cost[C:C + n] = -rt / PER_H - EPS_CYCLE
    cost[D:D + n] = rt / PER_H - s.deg / PER_H - EPS_CYCLE
    hi[C:C + n] = np.maximum(-np.asarray(p.lsl, dtype=float)[ks // PER_H], 0.0)
    hi[D:D + n] = np.maximum(np.asarray(p.hsl, dtype=float)[ks // PER_H], 0.0)
    lo[S:S + n] = np.asarray(p.min_soc, dtype=float)[ks // PER_H]
    hi[S:S + n] = np.asarray(p.max_soc, dtype=float)[ks // PER_H]
    lo[S:S + n] = np.minimum(lo[S:S + n], hi[S:S + n])
    rt_all = np.asarray(p.rt, dtype=float)
    for H, j in qi.items():
        rt_mean = float(np.mean(rt_all[PER_H * H:PER_H * (H + 1)]))
        cost[j] = p.dam[H] - rt_mean
        lo[j], hi[j] = min(p.lsl[H], 0.0), max(p.hsl[H], 0.0)
        cost[j + 1] = cost[j + 2] = -EPS_TIE
    cost[W:W + p.days] = -2 * s.deg
    cost[U] = -p.pen
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
        if i:
            e.append((S + i - 1, -rho))
            add(e, shift, shift)
        else:
            add(e, rho * p.soc + shift, rho * p.soc + shift)
    for i in range(n):
        e = []
        if hi[C + i] > 0:
            e.append((C + i, 1.0 / hi[C + i]))
        if hi[D + i] > 0:
            e.append((D + i, 1.0 / hi[D + i]))
        if e:
            add(e, -np.inf, 1.0)
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
                for H in range(24 * p.days) if not p.dam_open[H] and PER_H * (H + 1) > p.k0)
    return Plan(float(h.getInfo().objective_function_value) + fixed, x[C:C + n], x[D:D + n], x[S:S + n],
                {H: float(x[j]) for H, j in qi.items()}, lam, p.k0)


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
