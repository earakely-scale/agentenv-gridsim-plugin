"""What the v3 replay shows beyond an episode: the race lanes on the episode's day and tier (the rolling anchor, the
energy-only anchor, AS-hog and hindsight), each as hourly cash and SoC, played or solved through gridsim_core.hybrid."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import hybrid as H  # noqa: E402

LABELS = {"anchor": "Rolling anchor", "energy": "Energy-only anchor", "as_hog": "AS-hog", "hind": "Hindsight"}
SELF = {"reference/rolling-anchor": "anchor", "reference/as-hog": "as_hog"}


def session_lane(s: H.Session) -> tuple[list[float], list[float]]:
    """Hourly cash (energy DA + RT + AS - degradation - charged FTP; the end penalty in the last hour) and SoC."""
    cash = [r["cash"]["energy_da"] + r["cash"]["energy_rt"] + r["cash"]["as_da"] + r["cash"]["as_rt"]
            - r["cash"]["degradation"] - r["ftp"] for r in s.rows]
    cash[-1] -= s.cash["end_penalty"]
    return cash, list(s.soc_hist)


def hind_lane(task: dict, tier: str) -> tuple[list[float], list[float]] | None:
    """Hindsight (C3-D13, C3-D20) solved as gridsim_core.hybrid.hindsight does, with each hour's share of the
    objective and the end penalty in the last hour."""
    m, hours, penalty, soc = H.hindsight_model(task, tier)
    res = m.solve()
    if res is None:
        return None
    _, x = res
    cash = [H._value(e, x) for e in hours]
    cash[-1] -= H._value(penalty, x)
    return cash, [H._value(s, x) for s in soc]


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
