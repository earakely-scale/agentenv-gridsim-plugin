"""From what the desk can see to optimiser proposals: the LP problem at `now`, scenario plans and ERCOT-shaped curves
and COP rows (contract 8.2-8.3). Nothing here reads a price that is not in the price view it is handed."""

from __future__ import annotations

import dataclasses

from gridsim_core.desk import ancillary as asv
from gridsim_core.desk import clock
from gridsim_core.desk import forecast as fcm
from gridsim_core.desk.curves import reduce
from gridsim_core.desk.engine import PER_H, Engine, idle_end_soc
from gridsim_core.desk.optimize import Plan, Problem, end_penalty, hour_curves, solve

WEIGHTS = {"p10": 0.25, "p50": 0.5, "p90": 0.25}
END_PEN_HARD = 10.0
RT_HOURS = 12
MAX_RISK = 2.0


class ViewError(ValueError):
    pass


def visible_awards(e: Engine, now: int) -> list[float | None]:
    return [e.dam_award[H] if e.ser.dam_posted[H // 24] <= now else None for H in range(e.H)]


def pv_view(e: Engine, now: int) -> list[float]:
    """Expected PV MW per 5-minute interval from the latest PV forecast issued by `now` (modelled)."""
    if e.site.pv_mw <= 0:
        return []
    vs = [v for v in e.ser.forecasts if v.kind == "pv" and v.issued_at <= now]
    if not vs:
        return []
    v, out = vs[-1], []
    vals = v.values["values"]
    for k in range(e.K):
        i = int((5 * k - v.start) // v.step_min)
        out.append(float(vals[i] or 0.0) if 0 <= i < len(vals) else 0.0)
    return out


def problem(e: Engine, now: int, dam: list[float], rt5: list[float], constraints: dict | None = None,
            as_q: dict | None = None) -> Problem:
    c = constraints or {}
    site = e.site
    if c.get("max_cycles") is not None:
        site = dataclasses.replace(site, warranty=float(c["max_cycles"]))
    k0 = min(max(-(-now // 5), 0), e.K)
    soc = e.soc[k0] if k0 <= e.k else e.soc[e.k]
    awards = visible_awards(e, now)
    dam_open = [e.dam_close(H // 24) > now for H in range(e.H)]
    hsl, lsl = list(e.cop["hsl"]), list(e.cop["lsl"])
    ehsl, elsl, ev = e.event_limits(now)
    if ev is not None:
        end = ev.get("t_end", float("inf"))
        for H in range(e.H):
            if 60 * H < end and 60 * (H + 1) > max(now, 0):
                hsl[H], lsl[H] = min(hsl[H], ehsl), max(lsl[H], elsl)
    for H in range(e.H):
        if e.cop["status"][H] in ("OUT", "ONHOLD"):
            hsl[H] = lsl[H] = 0.0
    day = k0 // 288
    done = sum(max(m, 0.0) for m in e.metered[288 * day:min(k0, e.k)]) / PER_H if k0 < e.K else 0.0
    target = idle_end_soc(e.site, e.K)
    pen = end_penalty(e.site, dam[e.H - 24:e.H])
    if c.get("end_soc_mwh") is not None:
        target, pen = float(c["end_soc_mwh"]), pen * END_PEN_HARD
    p = Problem(site, e.ser.days, k0, soc, list(dam), list(rt5), dam_open,
                [a or 0.0 for a in awards], hsl, lsl, list(e.cop["min_soc"]), list(e.cop["max_soc"]), done,
                target, pen)
    if e.ancillary:
        p.products, p.rtcb, p.soc_rule = tuple(e.products), e.rtcb, e.soc_rule
        p.as_dam = (as_q or {}).get("dam", {})
        p.as_rt = (as_q or {}).get("rt", {})
        p.as_fixed = [dict(e.dam_as[H]) if e.ser.dam_posted[H // 24] <= now else {} for H in range(e.H)]
        p.as_cap = [dict(x) for x in e.cop["as_cap"]]
        p.pv, p.poi = pv_view(e, now), e.site.poi_mw
    elif e.site.pv_mw > 0:
        p.pv, p.poi = pv_view(e, now), e.site.poi_mw
    return p


def _expand(values, per_day: int, days: int, name: str) -> list[float]:
    if not isinstance(values, list) or not all(isinstance(x, int | float) for x in values):
        raise ViewError(f"{name} must be a list of numbers")
    if len(values) == per_day * days:
        return [float(x) for x in values]
    if len(values) == per_day:
        return [float(x) for x in values] * days
    raise ViewError(f"{name} needs {per_day} values per operating day ({per_day * days} for {days} days)")


def scenarios_from(view, e: Engine, views: dict) -> list[tuple[str, float, list[float], list[float]]]:
    """[(name, weight, dam hourly, rt 5-minute)] from "desk" or an agent-supplied view."""
    days = e.ser.days
    if view in (None, "desk"):
        out = []
        for q, w in WEIGHTS.items():
            dam = views["dam"].q(q)
            rt15 = views["rt"].q(q)
            out.append((q, w, list(dam), [rt15[k // 3] for k in range(288 * days)]))
        return out
    if not isinstance(view, dict):
        raise ViewError('price_view must be "desk" or {"dam": [...], "rt": [...]} or {"scenarios": [...]}')
    rows = view.get("scenarios") or [dict(view, name="view", weight=1.0)]
    out = []
    base_dam = views["dam"].p50
    for i, sc in enumerate(rows):
        dam = _expand(sc["dam"], 24, days, "dam") if sc.get("dam") is not None else list(base_dam)
        rt = sc.get("rt")
        if rt is None:
            rt5 = [dam[k // PER_H] for k in range(288 * days)]
        elif len(rt) in (24, 24 * days):
            h = _expand(rt, 24, days, "rt")
            rt5 = [h[k // PER_H] for k in range(288 * days)]
        else:
            q = _expand(rt, 96, days, "rt")
            rt5 = [q[k // 3] for k in range(288 * days)]
        for H in range(e.H):
            if views["dam"].posted[H]:
                dam[H] = base_dam[H]
        out.append((str(sc.get("name", f"s{i}")), float(sc.get("weight", 1.0)), dam, rt5))
    if not out:
        raise ViewError("price_view has no scenarios")
    return out


def _group(curves: dict[int, list], d0: str) -> list[dict]:
    """[{"day", "hours", "points"}] with consecutive identical curves merged."""
    out = []
    for H in sorted(curves):
        day, h = divmod(H, 24)
        pts = curves[H]
        if out and out[-1]["_day"] == day and out[-1]["points"] == pts and out[-1]["_last"] == h:
            out[-1]["_hours"].append(h + 1)
            out[-1]["_last"] = h + 1
        else:
            out.append({"_day": day, "_hours": [h + 1], "_last": h + 1, "points": pts})
    return [{"day": f"D{g['_day']}", "date": clock.date_of(g["_day"], d0), "hours": clock.hours_label(g["_hours"]),
             "points": g["points"]} for g in out]


def _group_as(offers: dict[int, dict], d0: str) -> list[dict]:
    """One item per product and day: {"day", "product", "hours", "mw": [...], "price": [...]} (one block per hour)."""
    out = []
    for pr in asv.PRODUCTS:
        by_day: dict[int, list] = {}
        for H in sorted(offers):
            bl = offers[H].get(pr)
            if bl:
                by_day.setdefault(H // 24, []).append((H % 24 + 1, bl[0]))
        for day, rows in by_day.items():
            out.append({"day": f"D{day}", "product": pr, "hours": [h for h, _ in rows],
                        "mw": [b[0] for _, b in rows], "price": [b[1] for _, b in rows]})
    return out


def to_pre(points: list[list[float]]) -> dict:
    """An EB/OC as the pre-RTC+B combo: Gen Resource offer (MW >= 0) and charging bid (MW >= 0 consumed)."""
    zeros = [p for q, p in points if q == 0]
    dis = [(q, p) for q, p in points if q > 0]
    chg = [(q, p) for q, p in points if q < 0]
    out = {}
    if dis:
        start = zeros[-1] if zeros else dis[0][1]
        out["offer"] = reduce([(0.0, start)] + dis)
    if chg:
        top = zeros[0] if zeros else chg[-1][1]
        bid = [[0.0, top]] + [[-q, p] for q, p in reversed(chg)]
        out["bid"] = [[round(q, 3), round(p, 2)] for q, p in bid]
    return out


def propose(e: Engine, now: int, views: dict, price_view="desk", risk: float = 0.5,
            constraints: dict | None = None, fc=None, dam_basis: str | None = None) -> dict:
    c = constraints or {}
    risk = min(max(float(risk), 0.0), MAX_RISK)
    dam_basis = dam_basis or c.get("dam_position", "physical")
    if dam_basis not in ("physical", "spread"):
        raise ViewError('constraints.dam_position is "physical" (DAM backed by the planned dispatch) or "spread"')
    scen = scenarios_from(price_view, e, views)
    asv_views = fcm.as_views(e.ser, fc, now, e.rtcb) if e.ancillary and fc is not None else None
    plans: list[tuple[str, float, Plan]] = []
    for name, w, dam, rt5 in scen:
        as_q = None
        if asv_views is not None:
            q = name if name in ("p10", "p50", "p90") else "p50"
            as_q = {"dam": asv_views["dam"][q],
                    "rt": {k: [v[i // PER_H] for i in range(e.K)] for k, v in asv_views["rt"][q].items()}}
        plans.append((name, w, solve(problem(e, now, dam, rt5, c, as_q))))
    base = next((p for n, _, p in plans if n == "p50"), plans[len(plans) // 2][2])
    d0, k0 = e.ser.d0, base.k0
    hours = c.get("hours")
    want = set(clock.parse_hours(hours)) if hours is not None else None
    want_day = clock.parse_day(c["day"], d0, e.ser.days, 0) if c.get("day") is not None else None

    def keep(H: int) -> bool:
        return (want is None or H % 24 + 1 in want) and (want_day is None or H // 24 == want_day)

    dam_curves, rt_curves, cop = {}, {}, []
    first_h = k0 // PER_H
    for H in range(first_h, e.H):
        if not keep(H):
            continue
        lams = sorted(x for x in (p.hour_lambda(H) for _, _, p in plans) if x is not None)
        if not lams:
            continue
        if e.dam_close(H // 24) > now:
            nets = [p.hourly_net(H) if dam_basis == "physical" else p.q.get(H, p.hourly_net(H)) for _, _, p in plans]
            dam_curves[H] = hour_curves(e.site, lams, risk, dis_cap=max(max(nets), 0.0),
                                        ch_cap=min(min(nets), 0.0))
        if 60 * (H + 1) > now and H < first_h + RT_HOURS and now >= e.adj_open(H):
            rt_curves[H] = hour_curves(e.site, lams, risk)
        if 60 * H - 60 > now and k0 < PER_H * H:
            cop.append({"hour": H, "hbsoc_mwh": round(base.soc_at(PER_H * H), 1)})
    dam_as, rt_as = {}, {}
    if asv_views is not None:
        for H in range(first_h, e.H):
            if not keep(H):
                continue
            for pr in e.products:
                pk = asv.PRICE_KEY[pr]
                if e.dam_close(H // 24) > now:
                    mw = base.R.get((pr, H), 0.0)
                    if mw >= asv.MIN_BLOCK_MW:
                        price = min(asv_views["dam"][q][pk][H] for q in ("p10", "p50", "p90"))
                        dam_as.setdefault(H, {})[pr] = [[round(mw, 1), round(max(0.5 * price, 0.0), 1)]]
                if e.rtcb and 60 * (H + 1) > now and H < first_h + RT_HOURS and now >= e.adj_open(H):
                    mw = base.hourly_as(pr, H)
                    if mw >= asv.MIN_BLOCK_MW:
                        price = min(asv_views["rt"][q][pk][H] for q in ("p10", "p50", "p90"))
                        rt_as.setdefault(H, {})[pr] = [[round(mw, 1), round(max(0.5 * price, 0.0), 1)]]
    if not e.rtcb:
        dam_curves = {H: to_pre(v) for H, v in dam_curves.items()}
        rt_curves = {H: to_pre(v) for H, v in rt_curves.items()}
    hourly = {}
    for H in range(first_h, min(first_h + 24, e.H)):
        hourly[H] = round(base.hourly_net(H), 1)
    cop_rows = []
    for row in cop:
        H = row["hour"]
        if cop_rows and cop_rows[-1]["_day"] == H // 24:
            cop_rows[-1]["hbsoc_mwh"].append(row["hbsoc_mwh"])
            cop_rows[-1]["_hours"].append(H % 24 + 1)
        else:
            cop_rows.append({"_day": H // 24, "_hours": [H % 24 + 1], "hbsoc_mwh": [row["hbsoc_mwh"]]})
    projected = {n: round(p.objective, 0) for n, _, p in plans}
    out_as = {}
    if asv_views is not None:
        out_as = {"dam_as_offers": _group_as(dam_as, d0), "rt_as_offers": _group_as(rt_as, d0) if e.rtcb else [],
                  "as_plan_mw": {asv.NAMES[pr]: [round(base.hourly_as(pr, H), 1)
                                                 for H in range(first_h, min(first_h + 24, e.H))]
                                 for pr in e.products if any(base.hourly_as(pr, H) > 0.05
                                                             for H in range(first_h, min(first_h + 24, e.H)))}}
    return {
        **out_as,
        "dam_curves": _group(dam_curves, d0),
        "rt_curves": _group(rt_curves, d0),
        "cop": [{"day": f"D{r['_day']}", "hours": clock.hours_label(r["_hours"]), "hbsoc_mwh": r["hbsoc_mwh"]}
                for r in cop_rows],
        "schedule": {"from": clock.label(5 * k0, d0),
                     "hourly_mw": [f"{clock.he(H % 24 + 1)}{'' if H < 24 else f'@D{H // 24}'}:{v:g}"
                                   for H, v in hourly.items() if abs(v) >= 0.05]},
        "projected": {"pnl_by_scenario": projected,
                      "expected": round(sum(w * p.objective for _, w, p in plans) / sum(w for _, w, _ in plans), 0)},
        "basis": "LP on the given price view; curves from scenario water values; proposals only, nothing submitted",
        "_plans": plans,
    }
