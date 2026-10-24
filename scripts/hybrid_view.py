"""What the v3 replay shows beyond an episode: the race lanes on the episode's day and tier (the rolling anchor, the
energy-only anchor, AS-hog and hindsight), each as hourly cash and SoC, played or solved through gridsim_core.hybrid."""

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import hybrid as H  # noqa: E402
from gridsim_core import live  # noqa: E402

LABELS = {"anchor": "Rolling anchor", "energy": "Energy-only anchor", "as_hog": "AS-hog", "hind": "Hindsight"}
SELF = {"reference/rolling-anchor": "anchor", "reference/as-hog": "as_hog"}


def session_lane(s: H.Session) -> tuple[list[float], list[float]]:
    """Hourly cash (energy DA + RT + AS - degradation - charged FTP; the end penalty in the last hour) and SoC."""
    cash = [r["cash"]["energy_da"] + r["cash"]["energy_rt"] + r["cash"]["as_da"] + r["cash"]["as_rt"]
            - r["cash"]["degradation"] - r["ftp"] for r in s.rows]
    cash[-1] -= s.cash["end_penalty"]
    return cash, list(s.soc_hist)


def hind_lane(task: dict, tier: str) -> tuple[list[float], list[float]] | None:
    """Hindsight (C3-D13) solved as in gridsim_core.hybrid.hindsight, with each hour's share of the objective."""
    st, day = H.site_of(task), H.day_of(task, tier)
    events = H.events_of(task)
    dep = H.deploy_hours([n.deploy for n in (live.parse_notice(x, task["date"]) for x in events) if n.deploy], day.dur)
    zero = [dict.fromkeys(H.EVENT_PRODUCTS, 0.0) for _ in range(H.HOURS)]
    m = H._Model()
    prods = tuple(k for k in day.offered if k in day.qualified)
    a_da = H._awards(m, H.HOURS, 0, prods, None, st.p)
    a_rt = H._awards(m, H.HOURS, 0, prods, None, st.p) if tier == "rtcb" else a_da
    cp = H._plant(m, st, day.dur, st.s0, st.cap, day.pv, day.da, [day.mean_up] * H.HOURS,
                  [day.mean_dn] * H.HOURS, zero, a_da, integer=True, free_curtail=True)
    ph = H._plant(m, st, day.dur, st.s0, st.cap, day.pv, day.rt, day.reg_up, day.reg_dn, dep, a_rt, integer=True)
    short = m.var(0, math.inf)
    m.add(short + ph["S"][-1], lo=st.s_end)
    hours, obj = [], H._Lin()
    for h in range(H.HOURS):
        e = cp["xb"][h] * float(day.da[h] - day.rt[h]) + ph["x"][h] * float(day.rt[h])
        e = e - (ph["dis"][h] + ph["U"][h]) * st.c_deg
        for k in prods:
            e = e + a_da[h][k] * float(day.mda[k][h])
            if tier == "rtcb":
                e = e + (a_rt[h][k] - a_da[h][k]) * float(day.mrt[k][h])
        hours.append(e)
        obj = obj + e
    m.obj = obj - short * day.pen
    res = m.solve()
    if res is None:
        return None
    _, x = res
    cash = [H._value(e, x) for e in hours]
    cash[-1] -= H._value(short, x) * day.pen
    return cash, [H._value(s, x) for s in ph["S"]]


def lanes(task: dict, tier: str, model: str | None = None) -> list[dict]:
    """The ghosts the agent races, leaving out the one the episode itself is."""
    out = []

    def add(k: str, got):
        if got is None or SELF.get(model) == k:
            return
        cash, soc = got
        cum, run = [], 0.0
        for c in cash:
            run += c
            cum.append(round(run, 2))
        out.append({"k": k, "label": LABELS[k], "cum": cum, "final": cum[-1], "soc": [round(v, 3) for v in soc]})

    add("anchor", session_lane(H.play(task, tier, H.anchor_policy())))
    if tier != "energy":
        add("energy", session_lane(H.play(task, "energy", H.anchor_policy())))
        add("as_hog", session_lane(H.play(task, tier, H.as_hog_policy)))
    add("hind", hind_lane(task, tier))
    return out
