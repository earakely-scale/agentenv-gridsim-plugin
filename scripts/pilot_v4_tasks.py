"""The v4 pilot's windows (docs/prereg/v4-pilot.md): one seeded draw over ercot-front-v4-eval in slots, each slot a
column and a label (front or calm) in a fixed order. A slot takes the window of its label, not drawn yet, whose d1 the
draw hasn't used, whose settlement point and then month its column has drawn least, then the point and month the whole
draw has drawn least, ties broken by a seeded shuffle. Main: 20 windows at the front tier (14 front, 6 calm); lite: 10
at front-lite (7 front, 3 calm); smoke: 3 at front (2 front, 1 calm). The display windows are fixed."""

import argparse
import json
import random
from collections import Counter
from pathlib import Path

from agentenv_gridsim import forecast_tasks

SEED = 4324
PACK = "ercot-front-v4-eval"
SHOWCASE_PACK = "ercot-front-v4-showcase"
DISPLAY = ("fern-0124", "heather-0114")
LABELS = ("front", "calm")
COLUMNS = {"main": ("front", 14, 6), "lite": ("front-lite", 7, 3), "smoke": ("front", 2, 1)}


def slots(n_front: int, n_calm: int) -> list[str]:
    """The labels in draw order: each calm slot as evenly spaced among the front slots as the counts allow."""
    n = n_front + n_calm
    calm = {round((i + 0.5) * n / n_calm - 0.5) for i in range(n_calm)} if n_calm else set()
    return ["calm" if i in calm else "front" for i in range(n)]


def draw(rows: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    rng = random.Random(seed)
    order = sorted(rows, key=lambda r: r["task_id"])
    rng.shuffle(order)
    rank = {r["task_id"]: i for i, r in enumerate(order)}
    points, months, d1s, taken = Counter(), Counter(), set(), set()
    out: dict[str, list[dict]] = {}
    for col, (_, n_front, n_calm) in COLUMNS.items():
        cp, cm, picked = Counter(), Counter(), []
        for label in slots(n_front, n_calm):
            pool = [r for r in order if r["tags"]["label"] == label and r["task_id"] not in taken]
            r = min(pool, key=lambda r: (r["d1"] in d1s, cp[r["settlement_point"]], cm[r["d1"][:7]],
                                         points[r["settlement_point"]], months[r["d1"][:7]], rank[r["task_id"]]))
            picked.append(r)
            taken.add(r["task_id"])
            d1s.add(r["d1"])
            for c, k in ((cp, r["settlement_point"]), (cm, r["d1"][:7]), (points, r["settlement_point"]),
                         (months, r["d1"][:7])):
                c[k] += 1
        out[col] = picked
    return out


def capture(p: float, p_idle: float, p_hind: float) -> float | None:
    return round((p - p_idle) / (p_hind - p_idle), 6) if p_hind - p_idle > 1e-9 else None


def row(r: dict, tier: str) -> dict:
    """A picked window with the references the pre-registration states before any run."""
    t = r["refs"][tier]
    b = t["baselines"]
    a = t["anchor"]
    return {"task_id": r["task_id"], "tier": tier, "label": r["tags"]["label"], "point": r["settlement_point"],
            "d1": r["d1"], "site": r["site"]["site_id"], "source": r.get("source"), "era": r["era"],
            "watches": r["tags"]["watches"][tier], "notices": len(r.get("notices") or []),
            "deployments": len(r.get("deployments") or []), "forecast_bust": r["tags"]["forecast_bust"],
            "t2m_drop_f": (r["tags"].get("front_signal") or {}).get("t2m_drop_f"),
            "nws": (r["tags"].get("front_signal") or {}).get("nws") or [], "dam_max": r["tags"]["dam_max"],
            "rt_max": r["tags"]["rt_max"], "neg_hours": r["tags"]["neg_hours"],
            "p_idle": round(t["p_idle"], 2), "p_anchor": round(t["p_anchor"], 2), "p_hind": round(t["p_hind"], 2),
            "anchor_minus_idle_usd": round(t["p_anchor"] - t["p_idle"], 2),
            "anchor_capture": capture(t["p_anchor"], t["p_idle"], t["p_hind"]),
            "anchor_commits": a["commits"], "anchor_as_usd": round(a["as_usd"], 2),
            "anchor_ftp_usd": round(a["ftp_usd"], 2), "anchor_governor_hours": a["governor_hours"],
            **{name: b[name]["reward"] for name in ("naive", "blind", "roll3")}}


def column(name: str) -> list[dict]:
    if name == "display":
        rows = forecast_tasks.pack_rows(SHOWCASE_PACK)
        by = {(r.get("tags") or {}).get("showcase"): r for r in rows}
        return [row(by[d], "front") for d in DISPLAY]
    tier = COLUMNS[name][0]
    rows = forecast_tasks.pack_rows(PACK)
    for t in {c[0] for c in COLUMNS.values()}:
        rows = forecast_tasks.eligible(rows, t)
    return [row(r, tier) for r in draw(rows)[name]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("column", nargs="?", choices=[*COLUMNS, "display"], default="main")
    ap.add_argument("--json", type=Path, help="Write every column's windows with their references here.")
    args = ap.parse_args()
    if args.json:
        args.json.write_text(json.dumps({"pack": PACK, "seed": SEED, "showcase_pack": SHOWCASE_PACK,
                                         "columns": {c: column(c) for c in [*COLUMNS, "display"]}}, indent=1) + "\n")
    print(",".join(dict.fromkeys(t["task_id"] for t in column(args.column))))


if __name__ == "__main__":
    main()
