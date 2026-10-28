"""GridSimEnv v5 references: the disclosure best-responder (the anchor, reward 1.0), every seat's hindsight best
response on the price-making residual, the iterated-BR reference profile and ε-Nash, the welfare LP, the card
baselines and the battery references the mitigation uses."""

from __future__ import annotations

import numpy as np

from gridsim_core.contract import DEGENERATE_EPS
from gridsim_core.grade import reward_value
from gridsim_core.market_auction import (
    GRID_STEPS,
    HOURS,
    SEATS,
    Battery,
    Book,
    at,
    battery_of,
    curve_blocks,
    demand_xy,
    lift,
    limits,
    offer_blocks,
    parse_offer,
    penalty_price,
    project,
    seat_profit,
    self_schedule,
    settle_battery,
    supply_xy,
)
from gridsim_core.market_stack import (
    KIND,
    DayStore,
    Floor,
    disclosed_net,
    hour_curves,
    hub_offset,
    net_load,
    net_load_forecast,
    shift,
    unit_cost,
)

try:
    import highspy
except ImportError:
    highspy = None

ACTS = list(range(-GRID_STEPS, GRID_STEPS + 1))
ORDER = sorted(range(len(ACTS)), key=lambda i: (abs(ACTS[i]), ACTS[i]))
TIE = 1e-7
DELTA_GRID = np.arange(-15000.0, 15000.0 + 1, 100.0)
MAX_SWEEPS, GAIN_USD = 50, 1.0

MARKET_VERSION = "5.1"


def lattice_move(b: Battery, s: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """(next SoC in sub-units, executed grid MW) of an award of k grid units from SoC s, delivered as far as SoC allows."""
    if k > 0:
        x = np.minimum(GRID_STEPS * k, s)
        return s - x, x * b.sub
    if k < 0:
        stored = np.minimum(b.gain * -k, b.levels - s)
        return s + stored, -stored * b.sub / b.eta
    return s, np.zeros_like(s, dtype=float)


def battery_dp(b: Battery, hub: np.ndarray, rt: np.ndarray | None, pen: float, feasible_only: bool = False,
               start: int = 0, s_start: float | None = None, hard_end: bool = False):
    """Exact best awards on the grid (k ∈ −20..20 units per hour) for hours start..23 with price-making hub prices
    hub[h, k + 20]; delivery is the projection and deviations settle at rt (rt None or feasible_only: no deviation).
    The end target is a penalty at `pen` per MWh stored short, or hard. Returns (value, k[start:], V[start..24])."""
    n = b.levels
    s = np.arange(n + 1)
    end = int(round(b.s_end / b.sub))
    v = np.where(s >= end, 0.0, -np.inf) if hard_end else -np.maximum(0, end - s) * b.sub / b.eta * pen
    vs, pol = [v], []
    for h in range(HOURS - 1, start - 1, -1):
        q = np.full((len(ACTS), n + 1), -np.inf)
        for i, k in enumerate(ACTS):
            if not np.isfinite(hub[h, i]):
                continue
            nxt, x = lattice_move(b, s, k)
            award = k * b.grid
            val = award * hub[h, i] - b.c_deg * np.maximum(x, 0.0) + v[nxt]
            if rt is None or feasible_only:
                val = np.where(np.abs(x - award) <= 1e-9, val, -np.inf)
            else:
                val = val + (x - award) * rt[h]
            q[i] = val
        best = q.max(axis=0)
        pick = np.asarray(ORDER)[np.argmax(q[ORDER] >= best - TIE, axis=0)]
        pol.append(pick)
        v = best
        vs.append(v)
    pol, vs = pol[::-1], vs[::-1]
    s0 = int(round((b.s0 if s_start is None else s_start) / b.sub))
    st, ks = s0, []
    for p in pol:
        k = ACTS[p[st]]
        ks.append(k)
        st = int(lattice_move(b, np.array([st]), k)[0][0])
    return float(vs[0][s0]), ks, vs


def marginal_values(b: Battery, prices) -> list[float]:
    """μ_h: the value of one more MWh stored at the start of hour h along the price-taker optimum on `prices`."""
    hub = np.repeat(np.asarray(prices, float)[:, None], len(ACTS), 1)
    _, ks, vs = battery_dp(b, hub, None, max(max(prices), 50.0), feasible_only=True)
    st, out = int(round(b.s0 / b.sub)), []
    for h in range(HOURS):
        v = vs[h + 1] if h + 1 < len(vs) else vs[-1]
        hi = min(b.levels, st + GRID_STEPS)
        lo = max(0, st - GRID_STEPS)
        dv = (v[hi] - v[lo]) / ((hi - lo) * b.sub) if hi > lo else 0.0
        out.append(round(float(dv) if np.isfinite(dv) else 0.0, 2))
        st = int(lattice_move(b, np.array([st]), ks[h])[0][0])
    return out


def reference_prices(b: Battery, forecast_hub) -> list[float]:
    """The battery's mitigation reference: 1.1·max(c_deg, μ_h) on the anchor's forecast (CONTRACT-v5 V5-P5)."""
    return [round(1.1 * max(b.c_deg, m), 2) for m in marginal_values(b, forecast_hub)]


# the anchor: the disclosure best-responder


def forecast_books(store: DayStore, task: dict) -> dict:
    """The anchor's forecast of D's market from the disclosed days D−61 (for D) and D−62 (for D−1): the disclosed net curve
    shifted by the forecast net-load change and one δ fitted on D−1's published λ. Never reads D's own offers."""
    d = task["date"]
    x, x1, prev = store.get(shift(d, -61)), store.get(shift(d, -62)), store.get(shift(d, -1))
    floor, cap = limits(d)

    def books(day):
        out = []
        for h in range(HOURS):
            sup, dem = disclosed_net(day, h)
            sx, dx = supply_xy(sup, floor, cap), demand_xy(dem, floor, cap)
            P = np.unique(np.concatenate([[floor, cap], sx[0], dx[0]]))
            out.append((P, at(sx, P) - at(dx, P) + 1e-6 * (P - floor)))
        return out

    bx1, bx = books(x1), books(x)
    off1, off = hub_offset(x1), hub_offset(x)
    d1 = net_load_forecast(store, shift(d, -1)) - net_load(x1)
    hub_prev = np.asarray(prev["hub_dam_usd"], float)
    err = np.zeros(len(DELTA_GRID))
    for h in range(HOURS):
        P, N = bx1[h]
        err += np.abs(np.interp(d1[h] + DELTA_GRID, N, P) + off1[h] - hub_prev[h])
    best = err.min()
    delta = float(DELTA_GRID[min(np.flatnonzero(err <= best + 1e-9), key=lambda i: abs(DELTA_GRID[i]))])
    dd = net_load_forecast(store, d) - net_load(x)
    shifts = dd + delta
    lam0 = [float(np.interp(shifts[h], bx[h][1], bx[h][0])) for h in range(HOURS)]
    return {"delta_mw": delta, "shift_mw": [float(v) for v in shifts], "books": bx, "basis": off,
            "forecast_lambda_usd": [round(v, 2) for v in lam0],
            "forecast_hub_usd": [round(float(v + off[h]), 2) for h, v in enumerate(lam0)],
            "mae_prev_usd": float(best / HOURS), "floor": floor, "cap": cap}


def forecast_book(fc: dict, h: int) -> Book:
    """The anchor's forecast book of hour h in hub prices (the disclosed day's offset added)."""
    P, N = fc["books"][h]
    return Book(fc["floor"], fc["cap"], P + fc["basis"][h], N - fc["shift_mw"][h], float("inf"), [], {})


def forecast_hub(fc: dict, b: Battery) -> np.ndarray:
    """hub[h, k + 20]: the anchor's forecast hub price when the battery's award is k grid units."""
    out = np.empty((HOURS, len(ACTS)))
    for h in range(HOURS):
        P, N = fc["books"][h]
        for i, k in enumerate(ACTS):
            out[h, i] = np.interp(fc["shift_mw"][h] - k * b.grid, N, P) + fc["basis"][h]
    return out


def anchor(F: Floor, fc: dict | None = None) -> dict:
    """The disclosure best-responder's self-schedule and its settled profit in the true re-clear (others on replay)."""
    fc = fc or forecast_books(F.store, F.task)
    b = battery_of(F.seats["A"])
    pen = penalty_price(F.hub_real)
    _, ks, _ = battery_dp(b, forecast_hub(fc, b), None, pen, feasible_only=True)
    q = [k * b.grid for k in ks]
    return settle_profile(F, {"A": schedule_blocks(F, "A", q)}) | {"q_mw": q, "forecast": fc}


def schedule_blocks(F: Floor, seat: str, q) -> list[list]:
    return [self_schedule(seat, float(q[h]), F.floor, F.cap, F.refs[seat][h]) for h in range(HOURS)]


def replay_profile(F: Floor) -> dict:
    return {s: "replay" for s in SEATS if s in F.seats and s != "A"}


def settle_profile(F: Floor, a_profile: dict, others: dict | None = None) -> dict:
    """Clear every hour with A's profile entry (blocks) and the others on replay (or `others`); A's awards, projection
    and settlement at the hub price."""
    prof = (others if others is not None else replay_profile(F)) | a_profile
    clears = [F.clear(h, prof) for h in range(HOURS)]
    awards = [c.awards.get("A", 0.0) for c in clears]
    hub = [F.hub(h, c.lam) for h, c in enumerate(clears)]
    b = battery_of(F.seats["A"])
    pj = project(b, awards)
    pnl = settle_battery(b, awards, pj["exec_mw"], hub, F.rt, penalty_price(F.hub_real))
    return {"profit": pnl["total_usd"], "pnl": pnl, "awards": awards, "lambda": [c.lam for c in clears], "hub": hub,
            "exec": pj["exec_mw"], "mitigated": [h + 1 for h, c in enumerate(clears) if "A" in c.mitigated],
            "clears": clears}


# hindsight best responses (others' offers fixed as played)


def price_grid(F: Floor, seat: str, profile: dict, qs) -> np.ndarray:
    """hub[h, j]: the hub price when `seat` self-schedules qs[j] MW in hour h, the rest of `profile` fixed."""
    out = np.empty((HOURS, len(qs)))
    for h in range(HOURS):
        for j, q in enumerate(qs):
            prof = profile | {seat: [self_schedule(seat, q, F.floor, F.cap, F.refs[seat][h]) if i == h else []
                                     for i in range(HOURS)]}
            out[h, j] = F.hub(h, F.clear(h, prof).lam)
    return out


def br_battery(F: Floor, seat: str, profile: dict, tier: str = "floor-sprint", rt: bool = False) -> dict:
    """A battery's hindsight best response with the others' offers fixed. Default: the best SoC-feasible awards,
    delivered as awarded (hindsight on the DA clear, V5-P19). rt=True adds deviations settled at the realised RT
    price, the upper bound every offer is tested against: the sprint projection DP, or for floor-day the separable
    financial position plus the physical LP."""
    b = battery_of(F.seats[seat])
    hub = price_grid(F, seat, profile, [k * b.grid for k in ACTS])
    pen = penalty_price(F.hub_real)
    if not rt:
        v, ks, _ = battery_dp(b, hub, None, pen, feasible_only=True)
        return {"value": v, "q_mw": [k * b.grid for k in ks]}
    if tier == "floor-sprint":
        v, ks, _ = battery_dp(b, hub, F.rt, pen)
        return {"value": v, "q_mw": [k * b.grid for k in ks]}
    fin = [(hub[h] - F.rt[h]) * np.array(ACTS) * b.grid for h in range(HOURS)]
    ks = [ACTS[int(np.argmax(f))] for f in fin]
    phys = physical_lp(b, F.rt)
    return {"value": float(sum(f.max() for f in fin)) + phys, "q_mw": [k * b.grid for k in ks], "physical_usd": phys}


def br_gas(F: Floor, profile: dict) -> dict:
    st = F.seats["G"]
    fuel = st["fuel_usd_mmbtu"]
    units = sorted(st["units"], key=lambda u: (unit_cost(u, fuel), u["id"]))
    caps = np.concatenate([[0.0], np.cumsum([u["mw"] for u in units])])
    cost = np.concatenate([[0.0], np.cumsum([u["mw"] * unit_cost(u, fuel) for u in units])])
    starts = np.array([u["start_usd"] for u in units])
    hub = price_grid(F, "G", profile, caps)
    n = len(caps)
    v = np.zeros(n)
    pol = []
    for h in range(HOURS - 1, -1, -1):
        stage = caps * hub[h] - cost
        q = np.empty((n, n))
        for kp in range(n):
            q[kp] = stage - np.array([starts[kp:k].sum() if k > kp else 0.0 for k in range(n)]) + v
        pol.append(q.argmax(axis=1))
        v = q.max(axis=1)
    k, out = 0, []
    for p in pol[::-1]:
        k = int(p[k])
        out.append(float(caps[k]))
    return {"value": float(v[0]), "q_mw": out}


def _per_hour_br(F: Floor, seat: str, profile: dict, qs, value, allowed) -> dict:
    hub = price_grid(F, seat, profile, qs)
    tot, out = 0.0, []
    for h in range(HOURS):
        vals = [value(h, q, hub[h, j]) if allowed(h, q) else -np.inf for j, q in enumerate(qs)]
        j = int(np.argmax(vals))
        tot += vals[j]
        out.append(float(qs[j]))
    return {"value": tot, "q_mw": out}


def br_renewable(F: Floor, profile: dict) -> dict:
    """Per hour, the best DA sale no larger than the hour's actual output (no hindsight speculation on RT)."""
    st = F.seats["R"]
    act, fc = np.asarray(st["actual_mw"], float), np.asarray(st["forecast_mw"], float)
    g = max(float(max(act.max(), fc.max())), 1.0) / GRID_STEPS
    res = _per_hour_br(F, "R", profile, [k * g for k in range(GRID_STEPS + 1)],
                       lambda h, q, p: q * p + (act[h] - q) * F.rt[h], lambda h, q: q <= act[h] + 1e-9)
    return res | {"value": res["value"] + st["ptc_usd"] * st["ptc_share"] * float(act.sum())}


def br_retailer(F: Floor, profile: dict) -> dict:
    """Per hour, the best DA purchase no larger than the hour's actual load."""
    st = F.seats["L"]
    load = np.asarray(st["load_mw"], float)
    g = 1.2 * max(float(np.max(st["forecast_mw"])), 1.0) / GRID_STEPS
    res = _per_hour_br(F, "L", profile, [-k * g for k in range(GRID_STEPS + 1)],
                       lambda h, q, p: q * p - (load[h] + q) * F.rt[h], lambda h, q: -q <= load[h] + 1e-9)
    return res | {"value": res["value"] + st["tariff_usd"] * float(load.sum())}


def best_response(F: Floor, seat: str, profile: dict, tier: str = "floor-sprint") -> dict:
    kind = KIND[seat]
    if kind == "battery":
        return br_battery(F, seat, profile, tier)
    return {"gas": br_gas, "renewable": br_renewable, "retailer": br_retailer}[kind](F, profile)


def profile_results(F: Floor, profile: dict) -> dict:
    """Every seat's awards and profit under a profile (each seat's own settlement)."""
    clears = [F.clear(h, profile) for h in range(HOURS)]
    hub = [F.hub(h, c.lam) for h, c in enumerate(clears)]
    pen = penalty_price(F.hub_real)
    out = {}
    for s in profile:
        aw = [c.awards.get(s, 0.0) for c in clears]
        out[s] = {"awards": aw, "profit": seat_profit(KIND[s], F.seats[s], aw, hub, F.rt, pen)}
    return out | {"_lambda": [c.lam for c in clears], "_hub": hub}


def idle_profit(F: Floor, seat: str) -> float:
    return seat_profit(KIND[seat], F.seats[seat], [0.0] * HOURS, F.hub_real, F.rt, penalty_price(F.hub_real))


def eps_nash(F: Floor, profile: dict, tier: str = "floor-sprint") -> dict:
    """Each seat's regret against its hindsight best response (others fixed), in $ and as a share in [0, 1] of the
    seat's range from the worse of its profit and its idle profit up to the best response (0 when that range is under
    $1); ε-Nash is the largest share (V5-P20)."""
    res = profile_results(F, profile)
    rows = {}
    for s in profile:
        br = best_response(F, s, {k: v for k, v in profile.items() if k != s}, tier)["value"]
        pi, idle = res[s]["profit"], idle_profit(F, s)
        den = br - min(pi, idle)
        rows[s] = {"profit_usd": round(pi, 2), "br_usd": round(br, 2), "regret_usd": round(br - pi, 2),
                   "eps": round(min(1.0, max(0.0, (br - pi) / den)), 6) if den > 1.0 else 0.0}
    return {"eps": max(r["eps"] for r in rows.values()), "seats": rows}


def nash(F: Floor, start: dict | None = None, tier: str = "floor-sprint") -> dict:
    """Gauss-Seidel iterated best response from the replay profile (A on its real curve), seats in order A, B, G, R, L."""
    prof = dict(start) if start is not None else replay_full(F)
    converged, sweeps = False, 0
    while sweeps < MAX_SWEEPS:
        sweeps += 1
        moved = False
        for s in [x for x in SEATS if x in prof]:
            cur = profile_results(F, prof)[s]["profit"]
            br = best_response(F, s, {k: v for k, v in prof.items() if k != s}, tier)
            if br["value"] > cur + GAIN_USD:
                prof[s] = schedule_blocks(F, s, br["q_mw"])
                moved = True
        if not moved:
            converged = True
            break
    res = profile_results(F, prof)
    out = {"sweeps": sweeps, "converged": converged,
           "lambda_usd": [round(v, 2) for v in res["_lambda"]],
           "profit_usd": {s: round(res[s]["profit"], 2) for s in prof}}
    if not converged:
        out["eps"] = eps_nash(F, prof, tier)["eps"]
    return out


# welfare


def physical_lp(b: Battery, prices) -> float:
    """Upper bound on Σ price·x − c_deg·discharge for a continuous schedule with the hard end target (HiGHS)."""
    p = np.asarray(prices, float)
    t = len(p)
    cols = {"dis": (np.zeros(t), np.full(t, b.p), p - b.c_deg), "ch": (np.zeros(t), np.full(t, b.p), -p),
            "soc": (np.zeros(t), np.full(t, b.e), np.zeros(t))}
    rows = []
    for h in range(t):
        r = {("soc", h): 1.0, ("dis", h): 1.0, ("ch", h): -b.eta}
        if h:
            r[("soc", h - 1)] = -1.0
        rows.append((r, b.s0 if h == 0 else 0.0, b.s0 if h == 0 else 0.0))
    rows.append(({("soc", t - 1): 1.0}, b.s_end, np.inf))
    return _lp(cols, rows)


def _lp(cols: dict, rows: list) -> float:
    if highspy is None:
        raise RuntimeError("the welfare and physical references need highspy")
    index, lo, hi, cost = {}, [], [], []
    for name, (lb, u, c) in cols.items():
        for h in range(len(lb)):
            index[(name, h)] = len(lo)
            lo.append(lb[h])
            hi.append(u[h])
            cost.append(c[h])
    lp = highspy.HighsLp()
    lp.num_col_, lp.num_row_ = len(lo), len(rows)
    lp.col_cost_, lp.col_lower_, lp.col_upper_ = np.array(cost), np.array(lo), np.array(hi)
    lp.row_lower_ = np.array([r[1] for r in rows], float)
    lp.row_upper_ = np.array([r[2] for r in rows], float)
    lp.sense_ = highspy.ObjSense.kMaximize
    lp.a_matrix_.format_ = highspy.MatrixFormat.kRowwise
    start, idx, val = [0], [], []
    for r, _, _ in rows:
        for k, v in sorted((index[k], v) for k, v in r.items()):
            idx.append(k)
            val.append(v)
        start.append(len(idx))
    lp.a_matrix_.start_, lp.a_matrix_.index_, lp.a_matrix_.value_ = start, idx, val
    h = highspy.Highs()
    h.setOptionValue("output_flag", False)
    h.passModel(lp)
    h.run()
    if h.getModelStatus() != highspy.HighsModelStatus.kOptimal:
        raise RuntimeError(f"LP not optimal: {h.modelStatusToString(h.getModelStatus())}")
    return float(h.getInfo().objective_function_value)


def _segments(F: Floor, h: int, profile: dict) -> tuple[list, list]:
    """Supply and demand segments [(mw, midpoint price)] of everyone bidding curves (background and curve seats)."""
    sup, dem = hour_curves(F.day, h, F.carve)
    for s, o in profile.items():
        if o == "replay" and KIND[s] != "battery":
            sell, buy = F.curve(s, h)
            sup, dem = sup + [sell], dem + [buy]
    segs = {"supply": [], "demand": []}
    for side, curves in (("supply", sup), ("demand", dem)):
        for c in curves:
            p, m = (supply_xy if side == "supply" else demand_xy)(lift(c, float(F.offset[h])), F.floor, F.cap)
            dm = np.diff(m)
            mids = (p[1:] + p[:-1]) / 2
            segs[side] += [(float(abs(x)), float(y), float(p[i]), float(p[i + 1]), side) for i, (x, y) in
                           enumerate(zip(dm, mids, strict=True)) if abs(x) > 1e-9]
    return segs["supply"], segs["demand"]


def welfare(F: Floor, profile: dict, exec_mw: dict) -> float:
    """As-bid welfare of the day with the batteries at their executed MW (re-cleared as self-schedules)."""
    prof = dict(profile)
    for s, x in exec_mw.items():
        prof[s] = schedule_blocks(F, s, x)
    w = 0.0
    for h in range(HOURS):
        c = F.clear(h, prof)
        sup, dem = _segments(F, h, prof)
        for mw, mid, p0, p1, _ in sup:
            w -= mid * mw * float(np.clip((c.lam - p0) / (p1 - p0), 0, 1))
        for mw, mid, p0, p1, _ in dem:
            w += mid * mw * float(np.clip((p1 - c.lam) / (p1 - p0), 0, 1))
        for s, o in prof.items():
            if o == "replay" or s in exec_mw:
                continue
            for seat, side, mw, price, _ in o[h]:
                got = abs(c.awards.get(seat, 0.0))
                w += (-price if side > 0 else price) * min(mw, got)
    for s, x in exec_mw.items():
        w -= battery_of(F.seats[s]).c_deg * sum(max(v, 0.0) for v in x)
    return w


def welfare_lp(F: Floor, profile: dict) -> float:
    """W*: the as-bid welfare optimum with A's and B's SoC (others as they bid)."""
    cols: dict = {}
    rows = []
    bal = [dict() for _ in range(HOURS)]
    for h in range(HOURS):
        sup, dem = _segments(F, h, profile)
        for i, (mw, mid, *_r) in enumerate(sup):
            cols[f"s{h}_{i}"] = ([0.0], [mw], [-mid])
            bal[h][(f"s{h}_{i}", 0)] = 1.0
        for i, (mw, mid, *_r) in enumerate(dem):
            cols[f"d{h}_{i}"] = ([0.0], [mw], [mid])
            bal[h][(f"d{h}_{i}", 0)] = -1.0
        for s, o in profile.items():
            if o == "replay" or KIND[s] == "battery":
                continue
            for j, (_, side, mw, price, _) in enumerate(o[h]):
                cols[f"b{h}_{s}_{j}"] = ([0.0], [mw], [-price if side > 0 else price])
                bal[h][(f"b{h}_{s}_{j}", 0)] = float(side)
    for s in [x for x in ("A", "B") if x in profile]:
        b = battery_of(F.seats[s])
        z = np.zeros(HOURS)
        cols[f"dis{s}"] = (z, np.full(HOURS, b.p), np.full(HOURS, -b.c_deg))
        cols[f"ch{s}"] = (z, np.full(HOURS, b.p), z)
        cols[f"soc{s}"] = (z, np.full(HOURS, b.e), z)
        for h in range(HOURS):
            bal[h][(f"dis{s}", h)] = 1.0
            bal[h][(f"ch{s}", h)] = -1.0
            r = {(f"soc{s}", h): 1.0, (f"dis{s}", h): 1.0, (f"ch{s}", h): -b.eta}
            if h:
                r[(f"soc{s}", h - 1)] = -1.0
            rows.append((r, b.s0 if h == 0 else 0.0, b.s0 if h == 0 else 0.0))
        rows.append(({(f"soc{s}", HOURS - 1): 1.0}, b.s_end, np.inf))
    for h in range(HOURS):
        e = float(F.eps[h])
        rows.append((bal[h], e, e))
    return _lp(cols, rows)


def welfare_rows(F: Floor, profile: dict, exec_mw: dict) -> dict:
    w = welfare(F, profile, exec_mw)
    w0 = welfare(F, profile, {s: [0.0] * HOURS for s in exec_mw})
    ws = welfare_lp(F, profile)
    den = ws - w0
    return {"w": w, "w0": w0, "w_star": ws, "welfare_ratio": round((w - w0) / den, 6) if den > 1.0 else 1.0,
            "dwl_usd": round(ws - w, 2)}


# baselines and the references stored in the task row


def replay_a(F: Floor) -> list[list]:
    """A's real curve of the day as a legal offer: each side scaled from the group's largest hourly volume to A's p_mw,
    snapped to A's grid (≤ 5 sell and 5 buy blocks an hour, the replay_A baseline); buys kept below the lowest sell."""
    b = a_battery(F)
    return offer_blocks("A", parse_offer(replay_a_offer(F), b.p, b.grid, F.floor, F.cap)[0], F.refs["A"])


def a_battery(F: Floor) -> Battery:
    return battery_of(F.seats["A"])


def replay_a_offer(F: Floor) -> dict:
    b = a_battery(F)
    curves = [F.curve("A", h) for h in range(HOURS)]
    top = [max((c[i][-1][0] if c[i] else 0.0) for c in curves) for i in (0, 1)]
    ks = [min(1.0, b.p / t) if t > 0 else 1.0 for t in top]
    hours = []
    for h, (sell, buy) in enumerate(curves):
        sb = _legal(curve_blocks([[m * ks[0], p] for m, p in sell], b.grid, "sell", 5), F)
        bb = _legal(curve_blocks([[m * ks[1], p] for m, p in buy], b.grid, "buy", 5), F)
        if sb and bb:
            low = min(p for _, p in sb)
            bb = [(m, round(min(p, low - 0.01), 2)) for m, p in bb if min(p, low - 0.01) >= F.floor]
        if sb or bb:
            hours.append({"he": h + 1, "sell": [[m, p] for m, p in sb], "buy": [[m, p] for m, p in bb]})
    return {"hours": hours}


def _legal(blocks, F: Floor) -> list[tuple[float, float]]:
    return [(m, round(min(F.cap, max(F.floor, p)), 2)) for m, p in blocks]


def replay_full(F: Floor) -> dict:
    """Every seat on its real offers of the day (A snapped to its grid): the profile the fidelity check re-clears."""
    return replay_profile(F) | ({"A": replay_a(F)} if F.seats["A"].get("pool_id") in F.pool else {})


def self_schedule_offer(q, floor: float, cap: float) -> dict:
    return {"hours": [{"he": h + 1, "sell": [[x, floor]] if x > 0 else [], "buy": [[-x, cap]] if x < 0 else []}
                      for h, x in enumerate(q) if abs(x) > 1e-9]}


def baseline_offers(F: Floor, fc: dict) -> dict:
    """The card baselines as offers seat A could submit: price_taker (its forecast DP ignoring its own impact,
    self-scheduled), max_withhold (all MW at the cap, buys at the floor) and replay_A (its real offers, scaled)."""
    b = a_battery(F)
    flat = np.repeat(np.asarray(fc["forecast_hub_usd"], float)[:, None], len(ACTS), 1)
    _, ks, _ = battery_dp(b, flat, None, penalty_price(F.hub_real), feasible_only=True)
    out = {"price_taker": self_schedule_offer([k * b.grid for k in ks], F.floor, F.cap),
           "max_withhold": {"hours": [{"he": h, "sell": [[b.p, F.cap]], "buy": [[b.p, F.floor]]}
                                      for h in range(1, HOURS + 1)]}}
    if F.seats["A"].get("pool_id") in F.pool:
        out["replay_A"] = replay_a_offer(F)
    return out


def baselines(F: Floor, fc: dict) -> tuple[dict, dict]:
    """(settled baselines, refused ones): every baseline goes through parse_offer, so each is a legal offer."""
    b = a_battery(F)
    out, bad = {}, {}
    for name, offer in baseline_offers(F, fc).items():
        parsed, issues = parse_offer(offer, b.p, b.grid, F.floor, F.cap)
        if issues:
            bad[name] = issues[:3]
            continue
        out[name] = settle_profile(F, {"A": offer_blocks("A", parsed, F.refs["A"])})
    return out, bad


def references(task: dict, store: DayStore | None = None, nash_ref: bool = False) -> dict:
    """Every reference a grade needs, computed on the true day (never shown to the agent). p_br is the hindsight best
    response on SoC-feasible awards delivered as awarded (V5-P19); p_br_rt adds RT deviations, the bound every offer
    is tested against."""
    F = Floor(task, store)
    fc = forecast_books(F.store, task)
    idle = settle_profile(F, {"A": [[] for _ in range(HOURS)]})["profit"]
    anc = anchor(F, fc)
    others = replay_profile(F)
    br = br_battery(F, "A", others)
    br_rt_s = br_battery(F, "A", others, "floor-sprint", rt=True)
    br_rt_d = br_battery(F, "A", others, "floor-day", rt=True)
    base, bad = baselines(F, fc)
    p_anchor = anc["profit"]

    def row(r):
        return {"profit": round(r["profit"], 2), "reward": reward_value(r["profit"], idle, p_anchor)}

    out = {"market_version": MARKET_VERSION, "p_idle": round(idle, 6),
           "forecast": {k: fc[k] for k in ("delta_mw", "forecast_lambda_usd", "forecast_hub_usd", "mae_prev_usd")},
           "floor-sprint": {"p_anchor": round(p_anchor, 6), "anchor": {"q_mw": anc["q_mw"],
                                                                     "hub_usd": [round(x, 2) for x in anc["hub"]]},
                            "p_br": round(br["value"], 6), "br": {"q_mw": br["q_mw"]},
                            "p_br_rt": round(br_rt_s["value"], 6),
                            "baselines": {k: row(v) for k, v in base.items()}},
           "floor-day": {"p_br": round(br["value"], 6), "br": {"q_mw": br["q_mw"]},
                         "p_br_rt": round(br_rt_d["value"], 6)},
           "replay_lambda_usd": [round(F.clear(h, replay_full(F)).lam, 2) for h in range(HOURS)]}
    if bad:
        out["baseline_issues"] = bad
    b = a_battery(F)
    out["headroom_usd_per_mw"] = {"br": round((br["value"] - idle) / b.p, 2), "anchor": round((p_anchor - idle) / b.p, 2)}
    pt = base.get("price_taker")
    out["price_taker_gap_usd_per_mw"] = round((p_anchor - pt["profit"]) / b.p, 2) if pt else None
    out["impact_hours"] = impact_hours(F, others, b)
    if nash_ref:
        out["nash"] = nash(F)
    return out


def impact_hours(F: Floor, others: dict, b: Battery) -> int:
    """Hours where A's full sale moves λ' by ≥ $5 (the V5-P12 pivotal-hour filter)."""
    hub = price_grid(F, "A", others, [0.0, b.p])
    return int(sum(hub[h, 0] - hub[h, 1] >= 5.0 for h in range(HOURS)))


def degenerate(refs: dict) -> bool:
    return refs["floor-sprint"]["p_anchor"] - refs["p_idle"] <= DEGENERATE_EPS
