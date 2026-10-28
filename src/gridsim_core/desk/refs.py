"""References and grading (contract section 9): idle, the information-matched anchor, the hindsight optimum, the
operator replay and the operator's own outcome, all settled by the one statement function."""

from __future__ import annotations

import dataclasses
import math

from gridsim_core.desk import ancillary as asv
from gridsim_core.desk import clock, policies
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


def _recleared(e: Engine, positions: list[float]) -> Series:
    """v5: the series with each DAM hour priced by the re-clear with `positions` self-scheduled (else unchanged)."""
    if not e.stacks:
        return e.ser
    dam = list(e.ser.dam_spp)
    for j, st in e.stacks.items():
        for h in range(24):
            dam[24 * j + h] = st.self_schedule(h, positions[24 * j + h])
    return dataclasses.replace(e.ser, dam_spp=dam)


def _anc(task: dict) -> bool:
    return task.get("layer", "v2") != "v2"


PRODUCT_ALIASES = {"rrs_pfr": "rrspfr", "rrs_ffr": "rrsffr"}


def _awards(block: dict | None, n: int, offset: int = 0) -> list[dict]:
    """[{product: MW}] per slot from a disclosed {product: [values]} block (aliases mapped)."""
    out = [{} for _ in range(n)]
    for k, v in (block or {}).items():
        p = PRODUCT_ALIASES.get(k, k)
        if p not in asv.PRODUCTS or v is None:
            continue
        for i, x in enumerate(v[:n]):
            if x:
                out[i][p] = float(x)
    return out


def hindsight(task: dict, series) -> dict:
    """The rules-bound optimum on real prices (all DAM hours open at D-1 06:00, unit events, regulation and AS
    deployments known) and the physical optimum without DAM/RT spread positions: the better of the plan with no DAM
    energy position and the plan whose DAM position equals its own dispatch, each solved and settled on its own."""
    ser, site, rtcb, anc = _ser(task, series), site_of(task), _rtcb(task), _anc(task)
    e = Engine(site, ser, rtcb, ancillary=anc, impact=task.get("layer") == "v5")
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

    def problem(dam_open: bool, tied: bool) -> Problem:
        p = Problem(site, ser.days, 0, site.soc0, list(ser.dam_spp), rt5, [dam_open] * H, [0.0] * H, hsl, lsl,
                    [site.e_min] * H, [site.e_max] * H, 0.0, target, end_penalty(site, ser.dam_spp[H - 24:H]))
        p.dam_tied = tied
        if anc:
            p.products, p.rtcb, p.soc_rule = tuple(e.products), rtcb, e.soc_rule
            p.as_dam = dict(ser.dam_mcpc)
            p.as_rt = {k: [ser.rt_mcpc_15[k][i // 3] if k in ser.rt_mcpc_15 else v[i] for i in range(K)]
                       for k, v in ser.rt_mcpc.items()}
            p.reg_up, p.reg_dn = list(ser.reg_up), list(ser.reg_dn)
        if site.pv_mw > 0 and ser.pv:
            p.pv = [0.0 if ser.rt_lmp[k] < 0 else min(ser.pv[k], site.pv_mw) for k in range(K)]
            p.poi = site.poi_mw
        return p

    def run(p: Problem) -> tuple[dict, list, list, object]:
        plan = solve(p)
        net = list(plan.net())
        dam_as = [{pr: plan.R[(pr, h)] for pr in e.products if plan.R.get((pr, h), 0.0) > 1e-6} for h in range(H)]
        rt_as = [{pr: float(plan.r[pr][k]) for pr in plan.r if plan.r[pr][k] > 1e-6} for k in range(K)] if rtcb \
            else [dam_as[k // PER_H] for k in range(K)]
        metered, soc, socs = [], site.soc0, [site.soc0]
        for k in range(K):
            a, b, _ = e.event_limits(5 * k)
            m = min(max(net[k], b), a)
            if anc:
                fu, fd = e.reg_fraction(k // PER_H)
                aw = rt_as[k]
                m += aw.get("regup", 0.0) * fu - aw.get("regdn", 0.0) * fd + e.deployed(5 * k, aw)
            hi = max(0.0, site.eta * PER_H * (drift(site, soc) - site.e_min))
            lo = min(0.0, -PER_H * (site.e_max - drift(site, soc)) / site.eta)
            m = min(max(m, lo), hi)
            metered.append(float(m))
            soc = next_soc(site, soc, m)
            socs.append(soc)
        q = [min(max(plan.q.get(h, 0.0), lsl[h]), hsl[h]) for h in range(H)]
        ancillary = None
        if anc:
            druc = [{"hbsoc": [socs[288 * j + PER_H * h] for h in range(24)], "min_soc": [site.e_min] * 24}
                    for j in range(ser.days)]
            ancillary = {"dam_as": dam_as, "rt_as": rt_as if rtcb else None, "short": [{} for _ in range(K)],
                         "druc": druc, "pv": p.pv or None}
        elif p.pv:
            ancillary = {"dam_as": [{} for _ in range(H)], "rt_as": None, "short": None, "druc": None, "pv": p.pv}
        st = statement(site, _recleared(e, q), rtcb, q, metered, metered, soc, target, ancillary)
        return st, q, metered, (plan, dam_as)

    full, q, metered, (plan, dam_as) = run(problem(True, False))
    rt_only = run(problem(False, False))[0]
    tied = run(problem(True, True))[0]
    return {"p_hind": full["total"], "p_hind_phys": max(rt_only["total"], tied["total"]),
            "p_hind_rt_only": rt_only["total"], "p_hind_tied": tied["total"],
            "lp_objective": round(plan.objective, 2),
            "dam_mw": [round(x, 3) for x in q], "rt_mw_15": [round(sum(metered[3 * i:3 * i + 3]) / 3, 3)
                                                             for i in range(K // 3)],
            "dam_as_mw": [{k: round(v, 2) for k, v in d.items()} for d in dam_as] if anc else None}


def operator_replay(task: dict, series) -> dict | None:
    """The operator's disclosed DAM and SCED curves and AS offers through our clearing, physics and settlement."""
    ser, site, rtcb, anc = _ser(task, series), site_of(task), _rtcb(task), _anc(task)
    op = ser.operator
    if not op or not op.get("dam") or not all(d in op["dam"] for d in ser.dates):
        return None
    e = Engine(site, ser, rtcb, ancillary=anc, impact=task.get("layer") == "v5")
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
            if anc:
                for k, v in (day.get("as_offers") or {}).items():
                    pr = PRODUCT_ALIASES.get(k, k)
                    if pr in e.products and v and v[h]:
                        e.dam_as_offer[H][pr] = v[h]
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
        if anc and rtcb:
            for row in sced.get("as_offer_updates") or []:
                t = int(round(clock.to_minutes(row["t"], ser.d0)))
                H = min(max(t // 60, 24 * j), 24 * j + 23)
                pr = PRODUCT_ALIASES.get(row["product"], row["product"])
                if pr in e.products:
                    e.rt_as_offer[H].append((t, {pr: row["blocks"]}))
    _carry(e)
    e.advance(ser.end)
    target = idle_end_soc(site, e.K)
    rec = {"dam_as": e.dam_as, "rt_as": e.rt_as if rtcb else None, "short": e.as_short, "druc": e.druc,
           "pv": e.pv if site.pv_mw > 0 else None} if anc else None
    st = statement(site, e.ser, rtcb, e.dam_award, e.bp, e.metered, e.soc[-1], target, rec)
    return {"p": st["total"], "dam_award_mw": e.dam_award, "statement": st}


def _carry(e: Engine) -> None:
    """The disclosure lists SCED curves and AS offers only where they changed: carry the last one at or before each
    hour's start into that hour, so an hour without its own row keeps the operator's real-time curve."""
    for books in (e.rt, e.rt_bid, e.rt_as_offer):
        rows = sorted(((t, c) for H in range(e.H) for t, c in books[H]), key=lambda r: r[0])
        if not rows:
            continue
        for H in range(e.H):
            before = [r for r in rows if r[0] <= 60 * H]
            if before and not any(t == 60 * H for t, _ in books[H]):
                last_t, last_c = before[-1]
                if books is e.rt_as_offer:
                    merged = {}
                    for _, c in before:
                        merged.update(c)
                    last_c = merged
                books[H].insert(0, (60 * H, last_c))


def operator_actual(task: dict, series) -> dict | None:
    """The operator's disclosed DAM awards (energy and AS), SCED AS awards and telemetered output settled directly
    (their own SoC path; AS deployments are inside their telemetry)."""
    ser, site, rtcb, anc = _ser(task, series), site_of(task), _rtcb(task), _anc(task)
    op = ser.operator
    try:
        award, bp, tel, soc, dam_as, rt_as = [], [], [], [], [], []
        for d in ser.dates:
            day = op["dam"][d]
            award += [float(x or 0.0) for x in day["award_mw"]]
            sc = op["sced"][d]
            bp += [float(x or 0.0) for x in sc["base_point_mw"]]
            tel += [float(x or 0.0) for x in sc["telemetry_mw"]]
            soc += [x for x in sc.get("soc_mwh", []) if x is not None]
            dam_as += _awards(day.get("as_awards") or day.get("as_award_mw"), 24)
            rt_as += _awards(sc.get("as_awards") or sc.get("as_award_mw"), 288)
    except (KeyError, TypeError):
        return None
    target = idle_end_soc(site, 288 * ser.days)
    soc_end = soc[-1] if soc else target
    rec = {"dam_as": dam_as, "rt_as": rt_as if rtcb else None, "short": None, "druc": None, "pv": None} if anc \
        else None
    st = statement(site, ser, rtcb, award, bp, tel, soc_end, target, rec)
    return {"p": st["total"], "statement": st}


def build_refs(task: dict, series) -> dict:
    """The task row's `refs` block."""
    ser = _ser(task, series)
    idle = _policy(task, ser, "idle")
    anc = _policy(task, ser, "anchor")
    hind = hindsight(task, ser)
    rep = operator_replay(task, ser)
    act = operator_actual(task, ser)
    floored = denominator(idle.result["total"], anc.result["total"], hind["p_hind_phys"])[1]
    return {"p_idle": idle.result["total"], "p_anchor": anc.result["total"], "p_hind": hind["p_hind"],
            "p_hind_phys": hind["p_hind_phys"], "p_hind_rt_only": hind["p_hind_rt_only"],
            "p_hind_tied": hind["p_hind_tied"], "floored": floored,
            "anchor_setting": policies.setting(task.get("layer", "v2")),
            "p_operator_replay": rep["p"] if rep else None, "p_operator_actual": act["p"] if act else None,
            "anchor": {"statement": anc.result, "turns": len(anc.turns)},
            "hind": {"dam_mw": hind["dam_mw"], "rt_mw_15": hind["rt_mw_15"]},
            "core_version": CORE_VERSION, "series_sha": series_sha(ser.raw)}


def _policy(task: dict, ser: Series, name: str) -> Session:
    return run(task, ser, name)


def refs_for(task: dict, series) -> dict:
    ser = _ser(task, series)
    r = task.get("refs")
    setting = policies.setting(task.get("layer", "v2"))
    if (r and r.get("series_sha") == series_sha(ser.raw) and r.get("core_version") == CORE_VERSION
            and r.get("anchor_setting") == setting):
        return r
    return build_refs(task, ser)


FLOOR_SHARE = 0.1


def denominator(p_idle: float, p_anchor: float, p_hind_phys: float | None) -> tuple[float, bool]:
    """(the anchor P the reward scales to, floored): den = max(P_anchor - P_idle, 0.1 (P_hind_phys - P_idle))."""
    den = p_anchor - p_idle
    floor = FLOOR_SHARE * (p_hind_phys - p_idle) if p_hind_phys is not None else -math.inf
    if floor > den:
        return p_idle + floor, True
    return p_anchor, False


def desk_reward(p: float, p_idle: float, p_anchor: float, p_hind_phys: float | None) -> tuple[float, bool]:
    """The 9.1 reward with the denominator floor; a flat day (den <= 0) keeps the degenerate rule."""
    eff, floored = denominator(p_idle, p_anchor, p_hind_phys)
    return reward_value(p, p_idle, eff), floored


def grade(session: Session, refs: dict | None = None) -> dict:
    """The 9.1 grade of a finished session."""
    st = session.finish()
    r = refs or refs_for(session.task, session.ser)
    p, p_idle, p_anchor, p_hind = st["total"], r["p_idle"], r["p_anchor"], r["p_hind"]
    valid = session.valid
    eff, floored = denominator(p_idle, p_anchor, r.get("p_hind_phys"))
    reward = reward_value(p, p_idle, eff) if valid else 0.0
    den = p_hind - p_idle
    out = {"valid": valid, "reward": reward, "p": p, "p_idle": p_idle, "p_anchor": p_anchor, "p_hind": p_hind,
           "p_hind_phys": r.get("p_hind_phys"), "capture": round((p - p_idle) / den, 6) if den > 1e-9 else None,
           "anchor_capture": round((p_anchor - p_idle) / den, 6) if den > 1e-9 else None,
           "capture_phys": _cap(p, p_idle, r.get("p_hind_phys")),
           "anchor_capture_phys": _cap(p_anchor, p_idle, r.get("p_hind_phys")),
           "beats_anchor": p > p_anchor + 1e-9, "floored": floored, "p_reward_scale": round(eff, 2),
           "stretch": stretch_value(p, p_idle, eff, p_hind) if valid else 0.0,
           "p_operator_replay": r.get("p_operator_replay"), "p_operator_actual": r.get("p_operator_actual")}
    if r.get("p_operator_replay") is not None:
        out["vs_operator_replay"] = round(p - r["p_operator_replay"], 2)
    return out


def _cap(p: float, p_idle: float, p_hind: float | None) -> float | None:
    if p_hind is None or p_hind - p_idle <= 1e-9:
        return None
    return round((p - p_idle) / (p_hind - p_idle), 6)
