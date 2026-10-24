"""Build the v5 packs data/gridsim-market-{train,eval,rtcb,showcase}/ (tasks.jsonl.gz + manifest.json) from the days
store data/market/days/ (scripts/build_market_days.py): seats drawn from each day's real pool
(`market_stack.sample_seats`) and every reference filled by `market.finalize_task` (CONTRACT-v5 V5-P2, P11, P12, P16).

A task needs its op day D as a full row, D−61 and D−62 as full rows (the anchor's disclosure) and D−1..D−3 (any row).
Filters: raw fidelity within_ns ≥ 0.5 (V5-P2); headroom BR_A − P_idle ≥ $25/MW-day and P_anchor − P_idle ≥ $10/MW-day
(V5-P11); train keeps tasks with ≥ 1 hour where A's full sale moves the hub price by ≥ $2 (V5-P12 option b) and every
row records its impact hours (≥ $5, the plan's measure, and ≥ $2). Eval keeps a stratum of peak days (≥ 2 impact
hours). Appends the survival per filter to data/market/stats.md."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import sys
import time
import zlib
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from build_live_pack import day_info  # noqa: E402

from gridsim_core.contract import era  # noqa: E402
from gridsim_core.market import finalize_task  # noqa: E402
from gridsim_core.market_auction import battery_of  # noqa: E402
from gridsim_core.market_refs import price_grid, replay_profile  # noqa: E402
from gridsim_core.market_stack import DayStore, Floor, sample_seats, shift  # noqa: E402

SPLITS = {"train": ("2024-02-11", "2024-12-31"), "eval": ("2025-01-01", "2025-11-30"), "rtcb": ("2025-12-05", None)}
SHOWCASE = {"fern-0123": ("2026-01-23", "2026-01-24", "2026-01-25", "2026-01-26", "2026-01-27"),
            "aug24-0820": ("2024-08-20",)}
SHOWCASE_GUARD_DAYS = 3
DRAWS = {"train": 9, "eval": 3, "rtcb": 3}
SIZES, SIZE_W = (400, 600, 800, 1000, 1200, 1500), (0.10, 0.15, 0.25, 0.20, 0.15, 0.15)
DURS, DUR_W = (1.0, 2.0, 4.0), (0.25, 0.5, 0.25)
ETAS, C_DEGS = (0.80, 0.85, 0.90, 0.95), (0.0, 2.0, 4.0, 8.0)
MIN_WITHIN_NS = 0.5
HEADROOM_BR, HEADROOM_ANCHOR = 25.0, 10.0
IMPACT_USD, IMPACT_LOOSE_USD = 5.0, 2.0
EVAL_TASKS, EVAL_PEAK, FLOOR_DAY, FLOOR_DAY_PEAK = 200, 50, 60, 20
FLAGS = {"stack": "real", "copper_plate": True, "as": "truncated", "costs": "modelled", "forecast": "eia930",
         "calibration": "hub_offset"}


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def dates(first: str, last: str):
    d, end = dt.date.fromisoformat(first), dt.date.fromisoformat(last)
    while d <= end:
        yield d.isoformat()
        d += dt.timedelta(days=1)


def guarded() -> set[str]:
    g = SHOWCASE_GUARD_DAYS
    return {shift(d, k) for ds in SHOWCASE.values() for d in ds for k in range(-g, g + 1)}


def needs(d: str) -> list[str]:
    return [d, shift(d, -1), shift(d, -2), shift(d, -3), shift(d, -61), shift(d, -62)]


def day_check(store: DayStore, d: str) -> str | None:
    """Why op day d cannot carry a task (None when it can)."""
    for k, need_full in ((d, True), (shift(d, -61), True), (shift(d, -62), True), (shift(d, -1), False),
                         (shift(d, -2), False), (shift(d, -3), False)):
        if k not in store:
            return "missing day row"
        if need_full and store.get(k).get("parser") == "light":
            return "missing disclosure"
    row = store.get(d)
    w = row["fidelity"]["within_ns"]
    if w is None or w < MIN_WITHIN_NS:
        return "fidelity"
    pool = row.get("pool") or {}
    if len(pool.get("esr") or []) < 2 or not pool.get("ct") or not pool.get("renew") or not pool.get("load"):
        return "pool"
    return None


def impact(task: dict, store: DayStore) -> tuple[int, int]:
    F = Floor(task, store)
    b = battery_of(task["seats"]["A"])
    hub = price_grid(F, "A", replay_profile(F), [0.0, b.p])
    dp = hub[:, 0] - hub[:, 1]
    return int((dp >= IMPACT_USD).sum()), int((dp >= IMPACT_LOOSE_USD).sum())


def tags(row: dict, imp: tuple[int, int], notice_day: bool, showcase: str | None) -> dict:
    m = int(row["date"][5:7])
    hub = row["hub_dam_usd"]
    return {"season": "winter" if m in (12, 1, 2) else "spring" if m <= 5 else "summer" if m <= 9 else "fall",
            "neg_hours": int(sum(x < 0 for x in hub)), "spike": bool(max(hub) >= 500.0), "notice_day": notice_day,
            "rtcb": row["date"] >= "2025-12-05", "showcase": showcase, "impact_hours": imp[0],
            "impact_hours_2usd": imp[1], "within_ns": row["fidelity"]["within_ns"]}


def draw(rng, esr_ids: list[str], k: int) -> tuple:
    return (esr_ids[k % len(esr_ids)], float(rng.choice(SIZES, p=SIZE_W)), float(rng.choice(DURS, p=DUR_W)),
            float(rng.choice(ETAS)), float(rng.choice(C_DEGS)))


def make_tasks(pack: str, d: str, rows: list[dict], cts: list[float], n: int, with_notices: bool,
               showcase: str | None) -> tuple[str, list[dict], list[str]]:
    """Up to n finalized task rows for op day d (each with its filter verdict in `_why`)."""
    store = DayStore(rows)
    day = store.get(d)
    rng = np.random.default_rng(zlib.crc32(f"gridsim-market-v5|{pack}|{d}".encode()))
    esr_ids = [m["id"] for m in day["pool"]["esr"]]
    notices, kind = day_info(d, "HB_HUBAVG") if with_notices else ([], None)
    notice_day = kind == "notice"
    out, seen, errors = [], set(), []
    for k in range(n * 6):
        if len(out) >= n:
            break
        pool_id, size, dur, eta, c_deg = (("e1", 800.0, 2.0, 0.85, 4.0) if showcase else draw(rng, esr_ids, k))
        try:
            seats = sample_seats(day, rng, cts, size, dur, eta, c_deg, pool_id)
            p = int(seats["A"]["p_mw"])
            tid = f"mkt-v5-{d}-A{p}x{int(dur)}-{pool_id}"
            if tid in seen:
                continue
            seen.add(tid)
            task = {"task_id": tid, "market_version": "5.0", "contract_version": "1.0", "pack": pack,
                    "split": pack.removeprefix("gridsim-market-"), "date": d, "era": era(d)["name"],
                    "point": "HB_HUBAVG", "region": "central", "seats": seats, "notices": notices,
                    "flags": dict(FLAGS)}
            finalize_task(task, store)
            imp = impact(task, store)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{d} draw {k}: {type(e).__name__}: {e}")
            continue
        r = task["refs"]
        task["tags"] = tags(day, imp, notice_day, showcase)
        hr = r["headroom_usd_per_mw"]
        why = ("headroom" if hr["br"] < HEADROOM_BR or hr["anchor"] < HEADROOM_ANCHOR
               else "impact" if pack.endswith("train") and imp[1] < 1 else None)
        task["_why"] = why
        out.append(task)
        if showcase:
            break
    return d, out, errors


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=Path, default=ROOT / "data" / "market" / "days")
    ap.add_argument("--data", type=Path, default=ROOT / "data")
    ap.add_argument("--packs", default="train,eval,rtcb,showcase")
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()
    store = DayStore(args.days)
    cts = json.loads((args.data / "market" / "ct_heat_rates.json").read_text())["heat_rates"]
    latest = max(d for d, r in store.rows.items() if r.get("parser") != "light")
    guard = guarded()
    stats_lines = ["", "## Packs (scripts/build_market_pack.py)", ""]
    for pack in args.packs.split(","):
        name = f"gridsim-market-{pack}"
        if pack == "showcase":
            plan = [(d, tag) for tag, ds in SHOWCASE.items() for d in ds]
        else:
            first, last = SPLITS[pack]
            plan = [(d, None) for d in dates(first, last or latest) if d not in guard]
        verdict: Counter = Counter()
        jobs = []
        for d, tag in plan:
            why = day_check(store, d)
            if why and not (tag and why in ("fidelity", "pool")):
                verdict[why] += 1
                continue
            if why:
                log(f"{name} {d}: {why} (showcase, kept for display)")
            jobs.append((d, tag))
        log(f"{name}: {len(plan)} dates, {len(jobs)} pass the day checks {dict(verdict)}")
        tasks, errors, t0 = [], [], time.time()
        with ProcessPoolExecutor(args.workers) as ex:
            futs = [ex.submit(make_tasks, name, d, [store.get(k) for k in needs(d) if k in store], cts,
                              1 if tag else DRAWS[pack], pack != "train", tag) for d, tag in jobs]
            for i, f in enumerate(as_completed(futs), 1):
                d, ts, errs = f.result()
                tasks += ts
                errors += errs
                if i % 50 == 0 or i == len(futs):
                    log(f"{name}: {i}/{len(futs)} dates ({time.time() - t0:.0f}s), {len(tasks)} tasks, "
                        f"{len(errors)} errors")
        tasks.sort(key=lambda t: t["task_id"])
        task_verdict = Counter(t["_why"] or "kept" for t in tasks)
        kept = [t for t in tasks if t["_why"] is None or pack == "showcase"]
        if pack in ("eval", "rtcb"):
            first_per_day = {}
            for t in kept:
                first_per_day.setdefault(t["date"], t)
            kept = sorted(first_per_day.values(), key=lambda t: t["task_id"])
        if pack == "eval":
            kept = select_eval(kept)
        for t in tasks:
            t.pop("_why", None)
        out = args.data / name
        out.mkdir(parents=True, exist_ok=True)
        with gzip.open(out / "tasks.jsonl.gz", "wt", compresslevel=9) as f:
            f.writelines(json.dumps(t, separators=(",", ":")) + "\n" for t in kept)
        rewards = [t["refs"]["headroom_usd_per_mw"]["anchor"] for t in kept]
        manifest = {"pack": name, "tasks": len(kept), "dates": len({t["date"] for t in kept}),
                    "first": min((t["date"] for t in kept), default=None),
                    "last": max((t["date"] for t in kept), default=None),
                    "day_checks": {"dates": len(plan), "passed": len(jobs), "dropped": dict(verdict)},
                    "task_filters": dict(task_verdict), "errors": errors[:50], "n_errors": len(errors),
                    "impact_hours": dict(Counter(t["tags"]["impact_hours"] for t in kept)),
                    "impact_hours_2usd": dict(Counter(t["tags"]["impact_hours_2usd"] for t in kept)),
                    "anchor_headroom_usd_per_mw_median": float(np.median(rewards)) if rewards else None,
                    "filters": {"within_ns_min": MIN_WITHIN_NS, "headroom_br_usd_per_mw": HEADROOM_BR,
                                "headroom_anchor_usd_per_mw": HEADROOM_ANCHOR,
                                "impact": "train: >= 1 hour of >= $2 (V5-P12 b); others: tagged only"},
                    "draws": {"sizes_mw": SIZES, "size_weights": SIZE_W, "durations_h": DURS, "etas": ETAS,
                              "c_deg": C_DEGS, "per_date": 1 if pack == "showcase" else DRAWS[pack]},
                    "showcase_guard": f"±{SHOWCASE_GUARD_DAYS} days around the showcase days",
                    "note": "derived, anonymised aggregates only; ERCOT data, not endorsed by ERCOT"}
        if pack == "eval":
            manifest["floor_day_task_ids"] = [t["task_id"] for t in kept if t["tags"].get("floor_day")]
            manifest["strata"] = dict(Counter(t["tags"]["stratum"] for t in kept))
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
        log(f"{name}: {len(kept)} tasks on {manifest['dates']} dates; {dict(task_verdict)}; {len(errors)} errors")
        stats_lines += [f"### {name}", "",
                        f"- dates {len(plan)}; day checks dropped {dict(verdict)}; passed {len(jobs)}",
                        f"- drawn tasks {len(tasks)}: {dict(task_verdict)} (headroom = V5-P11, impact = V5-P12 b)",
                        f"- shipped {len(kept)} tasks on {manifest['dates']} dates; impact hours ≥ $5: "
                        f"{dict(sorted(manifest['impact_hours'].items()))}; ≥ $2: "
                        f"{dict(sorted(manifest['impact_hours_2usd'].items()))}", ""]
    stats = args.data / "market" / "stats.md"
    text = stats.read_text().split("\n## Packs")[0].rstrip("\n") if stats.exists() else "# v5 market days"
    stats.write_text(text + "\n" + "\n".join(stats_lines) + "\n")


def select_eval(kept: list[dict]) -> list[dict]:
    """EVAL_TASKS dates: every peak day (≥ 2 impact hours) up to EVAL_PEAK, the rest drawn at random; FLOOR_DAY of them
    (up to FLOOR_DAY_PEAK peak) also run as floor-day."""
    rng = np.random.default_rng(20250101)
    peak = [t for t in kept if t["tags"]["impact_hours"] >= 2]
    base = [t for t in kept if t["tags"]["impact_hours"] < 2]
    peak = [peak[i] for i in sorted(rng.permutation(len(peak))[:EVAL_PEAK])]
    base = [base[i] for i in sorted(rng.permutation(len(base))[:max(0, EVAL_TASKS - len(peak))])]
    for t in peak:
        t["tags"]["stratum"] = "peak"
    for t in base:
        t["tags"]["stratum"] = "base"
    fd = ([peak[i] for i in sorted(rng.permutation(len(peak))[:FLOOR_DAY_PEAK])]
          + [base[i] for i in sorted(rng.permutation(len(base))[:FLOOR_DAY - min(FLOOR_DAY_PEAK, len(peak))])])
    for t in peak + base:
        t["tags"]["floor_day"] = any(t is x for x in fd)
    return sorted(peak + base, key=lambda t: t["task_id"])


if __name__ == "__main__":
    main()
