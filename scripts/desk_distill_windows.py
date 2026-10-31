"""The distillation's three-day windows: the held-out eval windows, the training starts and the leakage checks.

A window starting d0 reads the dates of its span, D-7 (history) to D2 (the last operating day). No training span holds
a held-out operating day, so nothing a held-out window is scored on is read by any training window.

    python scripts/desk_distill_windows.py               # the lists and the span check
    python scripts/desk_distill_windows.py --pack <dir>  # also every date string in the built pack's series
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from gridsim_core.desk import load_tasks

PACK = "desk-v4-win"
ID = "desk-v4w"
SITES = ("S01", "S02", "S03", "S04")
N_DAYS, LOOKBACK, MARGIN = 3, 7, 3
PERIODS = (("2025-12-20", "2026-01-22"), ("2026-05-11", "2026-07-03"))
EVAL = ("2026-01-09", "2026-01-13", "2026-01-17", "2026-06-06", "2026-06-09", "2026-06-12", "2026-06-15", "2026-06-18",
        "2026-06-22")
VAL = ("2026-01-13", "2026-06-06", "2026-06-09")
NO_PRICE_HISTORY = ("2026-01-08", "2026-06-04")
RESERVED_PACKS = ("desk-v4-bench", "desk-v4-eval", "desk-v4-pilot")
CPT = ZoneInfo("America/Chicago")
DATE = re.compile(r"(20\d\d-\d\d-\d\d)")
INDEX = re.compile(r"\[\d+\]")


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s)


def operating(d0: str) -> list[dt.date]:
    return [_d(d0) + dt.timedelta(days=k) for k in range(N_DAYS)]


def span(d0: str) -> set[dt.date]:
    return {_d(d0) + dt.timedelta(days=k) for k in range(-LOOKBACK, N_DAYS)}


def reserved() -> set[dt.date]:
    return {_d(d) for p in RESERVED_PACKS for t in load_tasks(p) for d in t["dates"]}


def _dst_free(days: list[dt.date]) -> bool:
    return len({dt.datetime(d.year, d.month, d.day, 12, tzinfo=CPT).utcoffset() for d in days}) == 1


def admissible(d0: str, res: set[dt.date]) -> bool:
    days = operating(d0)
    return (any(_d(a) <= days[0] and days[-1] <= _d(b) for a, b in PERIODS)
            and not {_d(x) for x in NO_PRICE_HISTORY} & set(days)
            and all(abs((d - r).days) > MARGIN for d in days for r in res)
            and _dst_free(sorted(span(d0)) + [days[0] - dt.timedelta(days=LOOKBACK + 1)]))


def train_starts(res: set[dt.date] | None = None) -> list[str]:
    res = reserved() if res is None else res
    held = {d for e in EVAL for d in operating(e)}
    out = []
    for a, b in PERIODS:
        d = _d(a)
        while d <= _d(b):
            s = str(d)
            if admissible(s, res) and not span(s) & held:
                out.append(s)
            d += dt.timedelta(days=1)
    return out


def tid(d0: str, sid: str) -> str:
    return f"{ID}-{d0}-{sid}"


def pack_spec() -> dict:
    starts = train_starts()
    return {"split": "train", "layer": "v4", "n_days": N_DAYS, "id": ID,
            "eval": {(d, s) for d in EVAL for s in SITES},
            "tasks": [(d, s) for d in sorted(set(EVAL) | set(starts)) for s in SITES],
            "selection": {"periods": [f"{a}..{b}" for a, b in PERIODS], "eval_windows": list(EVAL),
                          "train_starts": starts, "rule": "docs/prereg/desk-distill.md"}}


def check_spans(starts: list[str], res: set[dt.date]) -> dict:
    held = {e: set(operating(e)) for e in EVAL}
    bad = [(s, e) for s in starts for e, op in held.items() if span(s) & op]
    assert not bad, f"training spans hold held-out operating days: {bad}"
    assert set(VAL) <= set(EVAL)
    assert all(admissible(e, res) for e in EVAL), "a held-out window breaks the window rules"
    gap = min(abs((a - b).days) for s in starts for a in span(s) for op in held.values() for b in op)
    return {"train_starts": len(starts), "eval_windows": len(EVAL), "overlaps": 0,
            "min_days_from_a_training_span_to_a_held_out_day": gap,
            "train_operating_days": len({d for s in starts for d in operating(s)}),
            "reserved_days_within_margin": 0}


def _dates(obj, path: str = "") -> list[tuple[str, str]]:
    if isinstance(obj, dict):
        return [x for k, v in obj.items() for x in _dates(v, f"{path}/{k}") + [(m, f"{path}/{k}")
                                                                              for m in DATE.findall(str(k))]]
    if isinstance(obj, list):
        return [x for i, v in enumerate(obj) for x in _dates(v, f"{path}[{i}]")]
    return [(m, path) for m in DATE.findall(obj)] if isinstance(obj, str) else []


def check_pack(pack: str) -> dict:
    """Every date string anywhere in each training task's series, against the held-out windows' operating days."""
    held = {d for e in EVAL for d in operating(e)}
    rows = load_tasks(pack)
    hits: dict[str, list[str]] = {}
    for t in rows:
        if t["split"] != "train":
            continue
        with gzip.open(Path(pack) / t["series"], "rt") as f:
            ser = json.load(f)
        for m, p in _dates(ser):
            if _d(m) in held:
                hits.setdefault(t["task_id"], []).append(f"{m} {INDEX.sub('[]', p)}")
    return {"train_tasks": sum(t["split"] == "train" for t in rows),
            "eval_tasks": sum(t["split"] == "eval" for t in rows),
            "tasks_mentioning_held_out_days": len(hits),
            "mentions": {k: sorted(set(v))[:8] for k, v in sorted(hits.items())}}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack")
    a = ap.parse_args()
    res = reserved()
    starts = train_starts(res)
    print(json.dumps({"eval": list(EVAL), "train_starts": starts, "span_check": check_spans(starts, res)}, indent=1))
    if a.pack:
        print(json.dumps(check_pack(a.pack), indent=1))


if __name__ == "__main__":
    main()
