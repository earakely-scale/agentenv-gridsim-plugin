"""What the v4 replay shows beyond an episode: the race lanes on the episode's window and tier (the rolling anchor on
the guide's P50, the blind re-planner on persistence, the naive DAM bidder and hindsight), each as hourly cash and SoC,
played or solved through gridsim_core.forecast; and the viewer's reference episodes, whose rolling anchor reads the
desk forecasts at every watch so the vintage scrubber has recorded tool outputs to show.

usage: python scripts/forecast_view.py [--packs fixtures-forecast] [--tasks ID ...] [--out results/runs/forecast-view]
"""

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import forecast as F  # noqa: E402
from gridsim_core.hybrid import _awards, _Lin, _Model, _plant, _value, deploy_hours  # noqa: E402
from gridsim_core.live import parse_notice  # noqa: E402
from gridsim_core.task import data_root, load_pack  # noqa: E402

LABELS = {"roll": "Rolling anchor", "blind": "Blind re-planner", "naive": "Naive DAM bidder", "hind": "Hindsight"}
SELF = {"reference/rolling-p50": "roll", "reference/persistence": "blind", "reference/naive-dam": "naive"}
PACKS = ("ercot-front-v4-showcase", "ercot-front-v4-eval", "fixtures-forecast")
READS = (("get_forecast", {"kind": "price"}), ("get_forecast", {"kind": "load"}),
         ("get_forecast", {"kind": "solar"}), ("get_forecast", {"kind": "wind"}), ("get_forecast", {"kind": "weather"}))


def session_lane(s: F.Session) -> tuple[list[float], list[float]]:
    """Hourly cash (energy DA + RT + AS - degradation - charged FTP; the end penalty in the last hour) and SoC."""
    ep = s.episode(bundle="reference", path="ref")
    cash = [h["energy_da_usd"] + h["energy_rt_usd"] + h["as_da_usd"] - h["deg_usd"] - h["ftp_usd"] for h in ep["hours"]]
    cash[-1] -= ep["cash"]["end_penalty"]
    return cash, ep["soc_path"]


def hind_lane(task: dict, tier: str) -> tuple[list[float], list[float]] | None:
    """P_hind (gridsim_core.forecast.hindsight) with each hour's share of the objective."""
    st, w = F.site_for(task, tier), F.window_of(task, tier)
    events = F.events_of(task)
    dep = deploy_hours([n.deploy for n in (parse_notice(x, task["d1"], 60) for x in events) if n.deploy], w.dur,
                       w.hours)
    zero = [dict.fromkeys(F.EVENT_PRODUCTS, 0.0) for _ in range(w.hours)]
    for integer in (True, False):
        m = _Model()
        prods = tuple(k for k in w.offered if k in w.qualified)
        a = _awards(m, w.hours, 0, prods, None, st.p)
        cp = _plant(m, st, w.dur, st.s0, st.cap, w.pv, w.da, [w.mean_up] * w.hours, [w.mean_dn] * w.hours, zero, a,
                    integer=integer, free_curtail=True)
        ph = _plant(m, st, w.dur, st.s0, st.cap, w.pv, w.rt, w.reg_up, w.reg_dn, dep, a, integer=integer)
        short = m.var(0, math.inf)
        m.add(short + ph["S"][-1], lo=st.s_end)
        hours, obj = [], _Lin()
        for h in range(w.hours):
            e = cp["xb"][h] * float(w.da[h] - w.rt[h]) + ph["x"][h] * float(w.rt[h])
            e = e - (ph["dis"][h] + ph["U"][h]) * st.c_deg
            e = e + sum((a[h][k] * float(w.mda[k][h]) for k in prods), _Lin())
            hours.append(e)
            obj = obj + e
        m.obj = obj - short * w.pen
        res = m.solve(retry_infeasible=True)
        if res is None:
            continue
        _, x = res
        cash = [_value(e, x) for e in hours]
        cash[-1] -= _value(short, x) * w.pen
        return cash, [_value(s, x) for s in ph["S"]]
    return None


def lanes(task: dict, tier: str, model: str | None = None) -> list[dict]:
    """The lanes the agent races on its own window, leaving out the one the episode itself is."""
    out = []
    plant = "front-lite" if tier == "front-lite" else "front"

    def add(k: str, got):
        if got is None or SELF.get(model) == k and (k != "roll" or tier != "blind"):
            return
        cash, soc = got
        cum, run = [], 0.0
        for c in cash:
            run += float(c)
            cum.append(round(run, 2))
        out.append({"k": k, "label": LABELS[k], "cum": cum, "final": cum[-1], "soc": [round(v, 3) for v in soc]})

    add("roll", session_lane(F.play(task, plant if tier == "blind" else tier, F.anchor_policy("p50"),
                                    reference=False)))
    if plant == "front":
        add("blind", session_lane(F.play(task, "blind", F.anchor_policy("persist"), reference=False)))
    add("naive", session_lane(F.play(task, tier, F.naive_policy, reference=False)))
    add("hind", hind_lane(task, tier))
    return out


def reading(policy):
    """A policy that first reads the desk forecasts (price, load, solar, wind, weather and the price drift at the
    window's next DA peak) with the watch's six forecast calls, then plays as before."""

    def wrapped(s: F.Session):
        if not s.done and s.tier != "blind":
            for tool, args in READS:
                s.call(tool, args)
            h = max(range(s.first_open, s.H), key=lambda i: s.basis()["da"][i], default=None)
            if h is not None:
                s.call("get_forecast_drift", {"kind": "price", "target_hour": h})
        policy(s)

    return wrapped


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "forecast-view")
    p.add_argument("--packs", nargs="*", default=[x for x in PACKS if (data_root() / x).is_dir()])
    p.add_argument("--tasks", nargs="*")
    p.add_argument("--lanes", nargs="*", default=["anchor"])
    args = p.parse_args(argv)
    rows = {r["task_id"]: r for pack in args.packs for r in load_pack(pack)}
    plays = {"anchor": ("front", reading(F.anchor_policy("p50")), "reference/rolling-p50"),
             "blind": ("blind", F.anchor_policy("persist"), "reference/persistence"),
             "naive": ("front", reading(F.naive_policy), "reference/naive-dam"),
             "lite-anchor": ("front-lite", reading(F.anchor_policy("p50")), "reference/rolling-p50")}
    args.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for tid in args.tasks or list(rows):
        for lane in args.lanes:
            tier, policy, model = plays[lane]
            s = F.play(rows[tid], tier, policy, reference=False)
            ep = s.episode(bundle="reference", path="ref", model=model)
            if not ep["audit"]["ok"]:
                bad += 1
                print(f"{tid} {lane}: audit failed {ep['audit']['problems'][:2]}", flush=True)
                continue
            (args.out / f"{tid}-{lane}.json").write_text(json.dumps(ep, separators=(",", ":")) + "\n")
            print(f"{tid} {lane}: reward {ep['reward']} profit ${ep['profit_usd']:,.0f} "
                  f"reads {len(ep['forecasts_served'])}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
