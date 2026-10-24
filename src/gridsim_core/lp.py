"""LP relaxation bound (HiGHS): continuous charge/discharge on the convex hull of each hour's action set."""

from __future__ import annotations

import numpy as np

from gridsim_core.physics import penalty_per_unit
from gridsim_core.task import battery_of

try:
    import highspy
except ImportError:
    highspy = None


def lp_bound(task: dict, prices=None) -> float | None:
    """Upper bound on profit, or None when highspy is not installed."""
    if highspy is None:
        return None
    b, p = battery_of(task), np.asarray(task["prices"] if prices is None else prices, dtype=float)
    t = len(p)
    c_, x_, s_, u_ = 0, t, 2 * t, 3 * t
    ncol = 3 * t + 1
    cost = np.concatenate([-p * b.q / b.eta, (p - b.c_deg) * b.q, np.zeros(t), [-penalty_per_unit(b, p)]])
    lower = np.zeros(ncol)
    upper = np.concatenate([np.full(t, b.k_ch), np.full(t, b.k_dis), np.full(t, b.n), [np.inf]]).astype(float)
    rows, rlo, rhi = [], [], []
    for h in range(t):
        r = {s_ + h: 1.0, c_ + h: -1.0, x_ + h: 1.0}
        if h:
            r[s_ + h - 1] = -1.0
        rows.append(r)
        rlo.append(float(b.s0) if h == 0 else 0.0)
        rhi.append(float(b.s0) if h == 0 else 0.0)
        rows.append({c_ + h: 1.0 / b.k_ch, x_ + h: 1.0 / b.k_dis})
        rlo.append(-np.inf)
        rhi.append(1.0)
    rows.append({x_ + h: 1.0 for h in range(t)})
    rlo.append(-np.inf)
    rhi.append(float(b.cap))
    rows.append({u_: 1.0, s_ + t - 1: 1.0})
    rlo.append(float(b.s_end_min))
    rhi.append(np.inf)
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = ncol, len(rows)
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = cost, lower, upper
    lp.row_lower_, lp.row_upper_ = np.array(rlo), np.array(rhi)
    lp.sense_ = highspy.ObjSense.kMaximize
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    start, index, value = [0], [], []
    for r in rows:
        for k, v in sorted(r.items()):
            index.append(k)
            value.append(v)
        start.append(len(index))
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = start, index, value
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.passModel(lp)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"LP not optimal: {h.modelStatusToString(h.getModelStatus())}")
    return float(h.getInfo().objective_function_value)
