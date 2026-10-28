"""Policies that play the desk through the same tools an agent uses: idle, the information-matched anchor and a
fixed-rule scripted desk. `run` drives any of them over a whole episode."""

from __future__ import annotations

from collections.abc import Callable

from gridsim_core.desk.curves import FLOOR
from gridsim_core.desk.session import Session

Policy = Callable[[Session, dict], None]


def _dam_open_days(s: Session) -> list[int]:
    return [j for j in range(s.days) if s.engine.dam_close(j) > s.now]


def idle(s: Session, wake: dict) -> None:
    """A 0 MW self-schedule for every hour at the start, then nothing: P_idle."""
    if "start" not in wake["reasons"]:
        return
    curve = {"hours": "all", "points": [[0.0, FLOOR], [0.0, s.caps["dam"]]]} if s.rtcb else \
        {"hours": "all", "bid": [[0.0, s.caps["dam"]]]}
    for j in _dam_open_days(s):
        s.call("submit_dam_offers", {"day": f"D{j}", "curves": [curve]})


SETTINGS = {"v2": {"risk": 1.25, "dam_position": "spread"}, "v3": {"risk": 1.5, "dam_position": "spread"}}
DEFAULT = {"risk": 0.5, "dam_position": "physical"}
OVERRIDE: dict | None = None


def setting(layer: str) -> dict:
    """The anchor's (risk, DAM basis) for a layer, chosen on its tune pack (contract 9.3); OVERRIDE is for sweeps."""
    return dict(OVERRIDE or SETTINGS.get(layer, DEFAULT))


def _submit_groups(s: Session, tool: str, groups: list[dict], as_groups: list[dict] | None = None) -> None:
    by_day: dict[str, dict] = {}
    for g in groups:
        c = {"hours": g["hours"]}
        if s.rtcb:
            c["points"] = g["points"]
        else:
            c.update(g["points"])
        by_day.setdefault(g["day"], {}).setdefault("curves", []).append(c)
    for g in as_groups or []:
        by_day.setdefault(g["day"], {}).setdefault("as_offers", []).append(
            {"hours": g["hours"], "product": g["product"], "mw": g["mw"], "price": g["price"]})
    for day, args in by_day.items():
        s.call(tool, {"day": day, **args})


def anchor(s: Session, wake: dict) -> None:
    """At every wake-up but reminders: optimise on the desk forecast and submit what it proposes (contract 9.2)."""
    if wake["reasons"] == ["reminder"]:
        return
    st = setting(s.layer)
    out = s.call("optimize", {"price_view": "desk", "risk": st["risk"],
                              "constraints": {"dam_position": st["dam_position"]}})
    if "error" in out:
        return
    _submit_groups(s, "submit_dam_offers", out["dam_curves"], out.get("dam_as_offers"))
    rt = [g for g in out["rt_curves"] if s.now >= s.engine.adj_open(24 * int(g["day"][1:]))]
    _submit_groups(s, "submit_rt_offers", rt, out.get("rt_as_offers"))
    for row in out["cop"]:
        s.call("update_cop", {"day": row["day"], "rows": [{"hours": row["hours"], "hbsoc_mwh": row["hbsoc_mwh"]}]})


def scripted(s: Session, wake: dict) -> None:
    """A fixed-rule desk: at the start it reads the desk DAM P50 and self-schedules the cheapest hours to charge and
    the dearest to discharge (energy-feasible blocks), then leaves the curves in force."""
    if "start" not in wake["reasons"] and "dam_morning" not in wake["reasons"]:
        return
    site = s.site
    for j in _dam_open_days(s):
        fc = s.call("get_forecasts", {"kind": "price", "market": "dam", "day": f"D{j}"})
        if "error" in fc:
            continue
        p50 = fc["p50"]
        n = max(int(site.usable / max(site.hsl, 1e-6) * 0.8), 1)
        mw_d = min(site.hsl, 0.9 * site.usable * site.eta / n)
        mw_c = min(-site.lsl, mw_d / site.rte)
        order = sorted(range(24), key=lambda h: p50[h])
        cheap, dear = sorted(order[:n]), sorted(order[-n:])
        if min(p50[h] for h in dear) - max(p50[h] for h in cheap) < 10:
            continue
        curves = []
        for h in range(24):
            mw = -mw_c if h in cheap else mw_d if h in dear else 0.0
            if s.rtcb:
                curves.append({"hours": [h + 1], "points": [[mw, FLOOR], [mw, s.caps["dam"]]]})
            elif mw > 0:
                curves.append({"hours": [h + 1], "offer": [[0.0, FLOOR], [mw, FLOOR]]})
            elif mw < 0:
                curves.append({"hours": [h + 1], "bid": [[0.0, s.caps["dam"]], [-mw, s.caps["dam"]]]})
            else:
                curves.append({"hours": [h + 1], "bid": [[0.0, s.caps["dam"]]]})
        s.call("submit_dam_offers", {"day": f"D{j}", "curves": curves})


POLICIES: dict[str, Policy] = {"idle": idle, "anchor": anchor, "scripted": scripted}


def run(task: dict, series, policy: Policy | str, layer: str | None = None, **kw) -> Session:
    pol = POLICIES[policy] if isinstance(policy, str) else policy
    s = Session(task, series, layer=layer, **kw)
    wake = s.start()
    while wake is not None:
        pol(s, wake)
        wake = s.end_turn()
    return s
