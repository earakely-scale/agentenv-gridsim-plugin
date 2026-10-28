"""References and grading (contract section 9): idle, the information-matched anchor, the hindsight optimum, the
operator replay and the operator's own outcome, all settled by the one statement function."""

from __future__ import annotations

from gridsim_core.desk import clock
from gridsim_core.desk.data import Series, build, era_of, series_sha
from gridsim_core.desk.engine import PER_H, Engine, drift, idle_end_soc, next_soc, site_of
from gridsim_core.desk.optimize import Problem, end_penalty, solve
from gridsim_core.desk.policies import run
from gridsim_core.desk.session import CORE_VERSION, Session
from gridsim_core.desk.settle import statement
from gridsim_core.grade import reward_value, stretch_value


def _ser(task: dict, series) -> Series:
    return series if isinstance(series, Series) else build(task, series)


def _rtcb(task: dict) -> bool:
    return (task.get("era") or era_of(task["dates"])) == "rtcb"


def hindsight(task: dict, series) -> dict:
    """The rules-bound optimum on real prices (all DAM hours open at D-1 06:00), and the same with DA = physical."""
    ser, site, rtcb = _ser(task, series), site_of(task), _rtcb(task)
    e = Engine(site, ser, rtcb)
    K, H = e.K, e.H
    hsl, lsl = [], []
    for h in range(H):
        hs, ls = site.hsl, site.lsl
        for k in range(PER_H * h, PER_H * (h + 1)):
            a, b, _ = e.event_limits(5 * k)
            hs, ls = min(hs, a), max(ls, b)
        hsl.append(hs)
        lsl.append(ls)
    rt5 = [ser.rt_spp[k // 3] for k in range(K)]
    target = idle_end_soc(site, K)
    p = Problem(site, ser.days, 0, site.soc0, list(ser.dam_spp), rt5, [True] * H, [0.0] * H, hsl, lsl,
                [site.e_min] * H, [site.e_max] * H, 0.0, target, end_penalty(site, ser.dam_spp[H - 24:H]))
    plan = solve(p)
    net = list(plan.net())
    metered, soc = [], site.soc0
    for k in range(K):
        a, b, _ = e.event_limits(5 * k)
        m = min(max(net[k], b), a)
        hi = max(0.0, site.eta * PER_H * (drift(site, soc) - site.e_min))
        lo = min(0.0, -PER_H * (site.e_max - drift(site, soc)) / site.eta)
        m = min(max(m, lo), hi)
        metered.append(float(m))
        soc = next_soc(site, soc, m)
    q = [min(max(plan.q.get(h, 0.0), lsl[h]), hsl[h]) for h in range(H)]
    phys = [sum(metered[PER_H * h:PER_H * (h + 1)]) / PER_H for h in range(H)]
    full = statement(site, ser, rtcb, q, metered, metered, soc, target)
    st_phys = statement(site, ser, rtcb, phys, metered, metered, soc, target)
    return {"p_hind": full["total"], "p_hind_phys": st_phys["total"], "lp_objective": round(plan.objective, 2),
            "dam_mw": [round(x, 3) for x in q], "rt_mw_15": [round(sum(metered[3 * i:3 * i + 3]) / 3, 3)
                                                             for i in range(K // 3)]}


def operator_replay(task: dict, series) -> dict | None:
    """The operator's disclosed DAM and SCED curves through our clearing, physics and settlement."""
    ser, site, rtcb = _ser(task, series), site_of(task), _rtcb(task)
    op = ser.operator
    if not op or not op.get("dam") or not all(d in op["dam"] for d in ser.dates):
        return None
    e = Engine(site, ser, rtcb)
    for j, d in enumerate(ser.dates):
        day = op["dam"][d]
        for h in range(24):
            H = 24 * j + h
            if rtcb:
                c = (day.get("curves") or [None] * 24)[h]
                e.dam_curve[H] = c if c else None
            else:
                pre = day.get("pre") or {}
                c = {k: (pre.get(k) or [None] * 24)[h] for k in ("offer", "bid")}
                e.dam_curve[H] = c if any(c.values()) else None
        sced = (op.get("sced") or {}).get(d) or {}
        for row in sced.get("curves") or []:
            t = int(round(clock.to_minutes(row["t"], ser.d0)))
            H = min(max(t // 60, 24 * j), 24 * j + 23)
            if rtcb and row.get("points"):
                e.rt[H].append((t, row["points"]))
            elif not rtcb:
                if row.get("points"):
                    e.rt[H].append((t, row["points"]))
                if row.get("bid_points"):
                    e.rt_bid[H].append((t, row["bid_points"]))
    e.advance(ser.end)
    target = idle_end_soc(site, e.K)
    st = statement(site, ser, rtcb, e.dam_award, e.bp, e.metered, e.soc[-1], target)
    return {"p": st["total"], "dam_award_mw": e.dam_award, "statement": st}


def operator_actual(task: dict, series) -> dict | None:
    """The operator's disclosed DAM awards and telemetered output settled directly (their own SoC path)."""
    ser, site, rtcb = _ser(task, series), site_of(task), _rtcb(task)
    op = ser.operator
    try:
        award, bp, tel, soc = [], [], [], []
        for d in ser.dates:
            award += [float(x or 0.0) for x in op["dam"][d]["award_mw"]]
            sc = op["sced"][d]
            bp += [float(x or 0.0) for x in sc["base_point_mw"]]
            tel += [float(x or 0.0) for x in sc["telemetry_mw"]]
            soc += [x for x in sc.get("soc_mwh", []) if x is not None]
    except (KeyError, TypeError):
        return None
    target = idle_end_soc(site, 288 * ser.days)
    soc_end = soc[-1] if soc else target
    st = statement(site, ser, rtcb, award, bp, tel, soc_end, target)
    return {"p": st["total"], "statement": st}


def build_refs(task: dict, series) -> dict:
    """The task row's `refs` block."""
    ser = _ser(task, series)
    idle = _policy(task, ser, "idle")
    anc = _policy(task, ser, "anchor")
    hind = hindsight(task, ser)
    rep = operator_replay(task, ser)
    act = operator_actual(task, ser)
    return {"p_idle": idle.result["total"], "p_anchor": anc.result["total"], "p_hind": hind["p_hind"],
            "p_hind_phys": hind["p_hind_phys"],
            "p_operator_replay": rep["p"] if rep else None, "p_operator_actual": act["p"] if act else None,
            "anchor": {"statement": anc.result, "turns": len(anc.turns)},
            "hind": {"dam_mw": hind["dam_mw"], "rt_mw_15": hind["rt_mw_15"]},
            "core_version": CORE_VERSION, "series_sha": series_sha(ser.raw)}


def _policy(task: dict, ser: Series, name: str) -> Session:
    return run(task, ser, name)


def refs_for(task: dict, series) -> dict:
    ser = _ser(task, series)
    r = task.get("refs")
    if r and r.get("series_sha") == series_sha(ser.raw) and r.get("core_version") == CORE_VERSION:
        return r
    return build_refs(task, ser)


def grade(session: Session, refs: dict | None = None) -> dict:
    """The 9.1 grade of a finished session."""
    st = session.finish()
    r = refs or refs_for(session.task, session.ser)
    p, p_idle, p_anchor, p_hind = st["total"], r["p_idle"], r["p_anchor"], r["p_hind"]
    valid = session.valid
    reward = reward_value(p, p_idle, p_anchor) if valid else 0.0
    den = p_hind - p_idle
    out = {"valid": valid, "reward": reward, "p": p, "p_idle": p_idle, "p_anchor": p_anchor, "p_hind": p_hind,
           "p_hind_phys": r.get("p_hind_phys"), "capture": round((p - p_idle) / den, 6) if den > 1e-9 else None,
           "anchor_capture": round((p_anchor - p_idle) / den, 6) if den > 1e-9 else None,
           "capture_phys": _cap(p, p_idle, r.get("p_hind_phys")),
           "anchor_capture_phys": _cap(p_anchor, p_idle, r.get("p_hind_phys")),
           "beats_anchor": p > p_anchor + 1e-9, "stretch": stretch_value(p, p_idle, p_anchor, p_hind) if valid else 0.0,
           "p_operator_replay": r.get("p_operator_replay"), "p_operator_actual": r.get("p_operator_actual")}
    if r.get("p_operator_replay") is not None:
        out["vs_operator_replay"] = round(p - r["p_operator_replay"], 2)
    return out


def _cap(p: float, p_idle: float, p_hind: float | None) -> float | None:
    if p_hind is None or p_hind - p_idle <= 1e-9:
        return None
    return round((p - p_idle) / (p_hind - p_idle), 6)
