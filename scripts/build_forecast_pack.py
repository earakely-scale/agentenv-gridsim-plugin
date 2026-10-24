"""Build the v4 forecast windows (docs/CONTRACT-v4.md): data/fixtures-forecast now, the ercot-front-v4-* packs once
the data lane's forecast store exists. A window row gathers v1's DAM and v2's RT caches, lane D3's MCPC, solar cf and
deployments, lane N's notices and the window's vintage slice, then gridsim_core.forecast references on HiGHS.
Before the store lands the slice is the deterministic synthetic one (flagged source "synthetic")."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import numpy as np

try:
    import pyarrow.parquet as pq
except ImportError:
    pq = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_hybrid_pack as v3  # noqa: E402
import build_live_pack as v2  # noqa: E402

from gridsim_core import forecast as F  # noqa: E402
from gridsim_core import forecast_inputs as FI  # noqa: E402
from gridsim_core import hybrid as H  # noqa: E402
from gridsim_core import hybrid_inputs as HI  # noqa: E402
from gridsim_core.contract import as_era  # noqa: E402
from gridsim_core.task import stable_seed  # noqa: E402

SPLITS = {"train": ("2021-03-02", "2024-12-29"), "eval": ("2025-01-01", "2025-11-28"),
          "rtcb": ("2025-12-05", "2026-09-28")}
TARGETS = {"train": 1500, "eval": 60, "rtcb": 20}
FRONT_SHARE = {"train": 0.6, "eval": 40 / 60, "rtcb": 0.5}
CANDIDATES = {"train": 20000, "eval": 1200, "rtcb": 400}
PACKS = {"train": "ercot-front-v4-train", "eval": "ercot-front-v4-eval", "rtcb": "ercot-front-v4-rtcb",
         "showcase": "ercot-front-v4-showcase"}
SHOWCASE = {"fern-0124": ("2026-01-24", "HB_NORTH"), "heather-0114": ("2024-01-14", "HB_NORTH"),
            "uri-0213": ("2021-02-13", "HB_HOUSTON"), "spring-0328": ("2024-03-28", "HB_WEST")}
API_START = "2023-12-12"
FILTER = {"hind_headroom_low_drop_share": 0.15, "roll_headroom_min_usd_per_kw": 0.10, "roll_headroom_min_share": 0.05,
          "hind_minus_roll_share": 0.08, "roll_minus_blind_share": 0.05}
FRONT_NWS = {(p, s) for p in ("WS", "HZ", "EH", "XH", "HW") for s in ("W", "A")}
FRONT_DROP_F = 15.0

FIXTURES = [("2025-02-18", "HB_NORTH", "default"), ("2023-08-24", "HB_HOUSTON", "default"),
            ("2022-12-22", "HB_NORTH", "default"), ("2021-06-14", "HB_WEST", "default"),
            ("2026-02-10", "LZ_CPS", "default"), ("2025-07-15", "HB_WEST", "draw"),
            ("2024-05-08", "HB_HOUSTON", "draw"), ("2023-09-05", "HB_WEST", "default"),
            ("2025-10-12", "LZ_SOUTH", "draw"), ("2022-03-29", "HB_PAN", "default"),
            ("2026-04-20", "HB_SOUTH", "draw"), ("2024-07-30", "LZ_LCRA", "draw")]


def log(msg: str):
    print(f"[build_forecast_pack] {msg}", flush=True)


def dates(d1: str, a: int, b: int) -> list[str]:
    d = dt.date.fromisoformat(d1)
    return [(d + dt.timedelta(days=k)).isoformat() for k in range(a, b)]


def caches(cache: Path) -> tuple[dict, dict]:
    dam = json.load(gzip.open(next(cache.glob("dam-*.json.gz")), "rt"))["dam"]
    rt = json.load(gzip.open(next(cache.glob("rt-*.json.gz")), "rt"))["rt"]
    return dam, rt


def hourly(rt96) -> list[float]:
    return [round(float(x), 4) for x in np.asarray(rt96, dtype=float).reshape(24, 4).mean(axis=1)]


def window(d1: str, point: str, site: dict, dam: dict, rt: dict, days: int = 3) -> dict | None:
    """One window row (no slice, no refs), or None when an input day is missing or a DST day or era change falls in
    d1-1..d(n) (V4-P9)."""
    span = dates(d1, -1, days)
    if any(d in v2.v1.dst_dates(int(d[:4])) for d in span) or len({as_era(d) for d in span}) > 1:
        return None
    win = dates(d1, 0, days)
    try:
        da = [x for d in win for x in dam[f"{d}|{point}"]]
        rth = [x for d in win for x in hourly(rt[f"{d}|{point}"])]
        hist_dam = [dam[f"{d}|{point}"] for d in dates(d1, -7, 0)]
        hist_rt = [hourly(rt[f"{d}|{point}"]) for d in dates(d1, -8, -1)]
    except KeyError:
        return None
    asp = [HI.as_prices(d) for d in dates(d1, -2, days)]
    rows = [HI.solar_row(d) for d in dates(d1, -2, days)]
    if any(a is None or a["n_hours"] != 24 for a in asp) or any(r is None for r in rows):
        return None
    mcpc = {k: [x for a in asp[2:] for x in a[k]] for k in H.PRODUCTS if all(a.get(k) is not None for a in asp)}
    cf = [c for r in rows[2:] for c in r["cf"]]
    hist_pv = [H.pv_at_bus(site, r["cf"]) for r in rows[:2]]
    notices, seen = [], set()
    for d in win:
        for n in v2.day_notices(d, point):
            if n["event_id"] not in seen:
                seen.add(n["event_id"])
                notices.append(n)
    deps, dseen = [], set()
    for d in win:
        for x in v3.deployments(d):
            if x["event_id"] not in dseen:
                dseen.add(x["event_id"])
                deps.append(x)
    return F.make_task(d1, point, site, da, rth, cf, mcpc, era=as_era(d1),
                       history={"dam": hist_dam, "rt": hist_rt, "rt_d0": hourly(rt[f"{dates(d1, -1, 0)[0]}|{point}"]),
                                "pv_mw": hist_pv,
                                "mcpc_da": {k: [a[k] for a in asp[:2]] for k in mcpc}},
                       notices=notices, deployments=deps, solar_installed_mw=rows[2].get("installed_mw"), days=days)


def keys_for(t: dict, source: str) -> dict:
    """The store kinds and keys a window serves (V4-P12, V4-P17)."""
    codes = sorted(FI.zones())
    keys = {"weather": sorted({t["weather_point"]} | {z["point"] for z in FI.zones().values()}),
            "load": ["system"] + codes, "wind": ["system"], "solar": ["system"], "price": [t["settlement_point"]],
            "mcpc": sorted(t["mcpc_da"]), "load_official": ["system"]}
    if source == "ercot":
        keys |= {"ercot_load": ["system"] + codes, "ercot_wind": ["system"], "ercot_solar": ["system"]}
    return keys


def store_sha(store: Path) -> str | None:
    f = store / "manifest.json"
    return json.loads(f.read_text()).get("store_sha") if f.exists() else None


def store_ref(t: dict, store: Path, source: str) -> dict:
    """The row's reference into the store: the kinds and keys it serves, issued from 24 h before the open to the end."""
    open_utc = FI.parse_utc(F.utc(F.OPEN, t["d1"]))
    return {"store": f"v4-store@{store_sha(store)}", "source": source,
            "from": FI.iso_utc(open_utc - dt.timedelta(hours=24)),
            "to": FI.iso_utc(FI.parse_utc(F.utc(1440 * t["days"], t["d1"]))), "keys": keys_for(t, source)}


def resolve(t: dict, store: Path, source: str) -> dict:
    """The window's slice from the store (with its site-PV vintages)."""
    return FI.slice_for(dict(t) | {"vintages": store_ref(t, store, source)}, store)


_EIA: dict = {}


def eia_rows(eia: Path) -> dict:
    """{hour_end_utc: row} of the EIA-930 ERCO table, read once per process."""
    if str(eia) not in _EIA:
        f = eia / "erco.parquet"
        _EIA[str(eia)] = {r["hour_end_utc"]: r for r in pq.read_table(f).to_pylist()} if pq and f.exists() else {}
    return _EIA[str(eia)]


def actuals(t: dict, eia: Path) -> dict | None:
    """EIA-930 ERCO actuals from d1-2 00:00 to the window end, by hour start (None without the table)."""
    rows = eia_rows(eia)
    if not rows:
        return None
    lo = FI.parse_utc(F.utc(-2880, t["d1"]))
    n = 24 * (t["days"] + 2)
    out = {"start": FI.iso_utc(lo)}
    cols = (("load_mw", "demand_mw"), ("wind_mw", "wind_mw"), ("solar_mw", "solar_mw"), ("df_mw", "df_mw"))
    for k, c in cols:
        out[k] = [(rows.get(FI.iso_utc(lo + dt.timedelta(hours=i + 1))) or {}).get(c) for i in range(n)]
    return out


def front_label(t: dict, sl: dict) -> tuple[str, dict]:
    """front (V4-P19) when, at any weather-zone point inside the window, the stitched near-analysis 2 m temperature (the
    first 6 h of consecutive HRRR runs) is >= 15 F below the same hour 24 h earlier, or an NWS winter storm, hard
    freeze, excessive heat or high wind product is in force; else calm. The diurnal cycle alone is not a front."""
    vint = F.Vintages(sl, t["d1"])
    best = (0.0, None)
    for z in FI.zones().values():
        temp = {}
        for r in vint.all("weather", z["point"]):
            for i in range(6):
                x = F.Vintages.at(r, "t2m_f", r.h0 + i)
                if x is not None:
                    temp[r.h0 + i] = x
        for h in sorted(temp):
            if -14 <= h < 24 * t["days"] and h - 24 in temp and temp[h - 24] - temp[h] > best[0]:
                best = (temp[h - 24] - temp[h], z["name"])
    nws = sorted({n["kind"][4:] for n in t["notices"] if n.get("kind", "").startswith("nws:")
                  and tuple(n["kind"][4:].split(".")) in FRONT_NWS})
    lab = "front" if best[0] >= FRONT_DROP_F or nws else "calm"
    return lab, {"t2m_drop_f": round(best[0], 1), "zone": best[1], "nws": nws}


def forecast_bust(t: dict) -> bool | None:
    a = t.get("actuals")
    if not a:
        return None
    for k in range(t["days"]):
        i = 48 + 24 * k
        df, ld = a["df_mw"][i:i + 24], a["load_mw"][i:i + 24]
        if None in df or None in ld:
            continue
        if abs(max(df) / max(ld) - 1) >= 0.05:
            return True
    return False


def ercot_ok(sl: dict, d1: str) -> bool:
    """A posting of each ERCOT kind within 2 h before every fixed watch (V4-P17)."""
    vint = F.Vintages(sl, d1)
    for kind in ("ercot_load", "ercot_wind", "ercot_solar"):
        for m in F.fixed_watches(3):
            r = vint.latest(kind, "system", m)
            if r is None or m - r.minute > 120:
                return False
    return True


def score(t: dict, tier: str) -> dict:
    r, p = t["refs"][tier], t["site"]["bess"]["p_mw"] * 1000
    head = r["p_hind"] - r["p_idle"]
    return {"hind_headroom_usd_per_kw": head / p, "roll_headroom_usd_per_kw": (r["p_roll"] - r["p_idle"]) / p,
            "hind_minus_roll_share": (r["p_hind"] - r["p_roll"]) / head if head > 0 else 0.0,
            "roll_minus_blind_share": (r["p_roll"] - r["p_blind"]) / head if head > 0 else 0.0}


def hind_floor(rows: list, tier: str) -> float:
    """The split's low-spread cut (V4-P18): the 15th percentile of hindsight headroom per kW over its candidates."""
    x = [r["_score"][tier]["hind_headroom_usd_per_kw"] for r in rows]
    return float(np.quantile(x, FILTER["hind_headroom_low_drop_share"])) if x else 0.0


def eligible(x: dict, floor: float) -> bool:
    """V4-P18: above the split's low-spread cut, P_roll - P_idle >= max($0.10/kW, 5% of P_hind - P_idle), P_hind -
    P_roll >= 8% and P_roll - P_blind >= 5% of P_hind - P_idle."""
    return (x["hind_headroom_usd_per_kw"] >= floor
            and x["roll_headroom_usd_per_kw"] >= max(FILTER["roll_headroom_min_usd_per_kw"],
                                                     FILTER["roll_headroom_min_share"] * x["hind_headroom_usd_per_kw"])
            and x["hind_minus_roll_share"] >= FILTER["hind_minus_roll_share"]
            and x["roll_minus_blind_share"] >= FILTER["roll_minus_blind_share"])


def candidates(split: str, n: int) -> list[tuple[str, str]]:
    """A stable sample of (d1, point) pairs in the split, showcase windows and their 3-day margins excluded."""
    a, b = (dt.date.fromisoformat(x) for x in SPLITS[split])
    days = [(a + dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]
    show = [dt.date.fromisoformat(d) for d, _ in SHOWCASE.values()]
    days = [d for d in days if all(abs((dt.date.fromisoformat(d) - s).days) > 3 + 3 for s in show)]
    pool = sorted(((d, p) for d in days for p in v3.POINTS), key=lambda x: stable_seed(f"v4|{split}|{x[0]}|{x[1]}"))
    return pool[:n]


def build_store_row(args: tuple) -> dict | None:
    """One candidate window from the store: inputs, slice, source, label, refs and filter scores."""
    d1, point, split, tiers, store, eia, showcase = args
    dam, rt = _CACHES
    arch = HI.archetypes()
    site = site_for("default" if showcase else "draw", d1, point, arch)
    t = window(d1, point, site, dam, rt, days=3)
    if t is None:
        return None
    store = Path(store)
    t["actuals"] = actuals(t, Path(eia))
    source = "ercot" if split != "train" and d1 >= API_START else "desk"
    sl = resolve(t, store, source)
    if source == "ercot" and not ercot_ok(sl, d1):
        source = sl["source"] = "desk"
    t["source"], t["pack"], t["split"] = source, PACKS[split], split
    lab, sig = front_label(t, sl)
    t0 = time.perf_counter()
    try:
        out = F.attach(t, sl, tiers=tiers)
    except (RuntimeError, ValueError) as e:
        return {"_error": str(e), "task_id": t["task_id"]}
    if split == "train":
        out["vintages"] = store_ref(t, store, source)
    out["tags"] = {"label": lab, "front_signal": sig, "forecast_bust": forecast_bust(out),
                   "watches": {tier: len(F.Session(t | {"vintages": sl}, tier, reference=True).watches)
                               for tier in tiers},
                   "season": "winter" if int(d1[5:7]) in (12, 1, 2) else "spring" if int(d1[5:7]) <= 5 else
                   "summer" if int(d1[5:7]) <= 9 else "fall", "neg_hours": int(sum(x < 0 for x in out["prices"])),
                   "era": out["era"], "dam_max": max(out["prices"]), "rt_max": max(out["rt"]), "showcase": showcase}
    out["_score"] = {tier: score(out, tier) for tier in tiers}
    out["_ms"] = round(1000 * (time.perf_counter() - t0))
    return out


_CACHES: tuple = ({}, {})


def _init(cache: str):
    global _CACHES
    _CACHES = caches(Path(cache))


def select(ok: list, n: int, front_share: float, salt: str) -> list:
    """A stable draw of n rows, front_share of them front-labelled, at most one per d1 per round."""
    out = []
    for lab, k in (("front", round(n * front_share)), ("calm", n - round(n * front_share))):
        rows = sorted((t for t in ok if t["tags"]["label"] == lab), key=lambda t: stable_seed(f"{salt}|{t['task_id']}"))
        seen, take = set(), []
        for t in rows:
            if t["d1"] not in seen and len(take) < k:
                seen.add(t["d1"])
                take.append(t)
        out += take
    return sorted(out, key=lambda t: (t["d1"], t["settlement_point"]))


def site_for(kind: str, d1: str, point: str, arch: dict) -> dict:
    if kind == "default":
        return H.site_from_archetype(arch["default"], c_deg=4.0)
    return v3.pick_site(d1, point, "forecast-fixtures", arch)


def build_one(args: tuple) -> dict:
    t, tiers = args
    t0 = time.perf_counter()
    sl = FI.synthetic_slice(t)
    out = F.attach(t, sl, tiers=tiers)
    out["_ms"] = round(1000 * (time.perf_counter() - t0))
    return out


def write(out: Path, name: str, tasks: list, meta: dict):
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(d / "tasks.jsonl.gz", "wb", mtime=0) as f:
        for t in tasks:
            f.write((json.dumps({k: v for k, v in t.items() if not k.startswith("_")}, separators=(",", ":")) + "\n")
                    .encode())
    (d / "manifest.json").write_text(json.dumps({
        "pack": name, "forecast_version": F.FORECAST_VERSION, "tasks": len(tasks),
        "dates": [min(t["d1"] for t in tasks), max(t["d1"] for t in tasks)] if tasks else None,
        "tiers": list(F.TIERS), "sources": sorted({t["source"] for t in tasks}),
        "flags": {"vintages": "synthetic until the forecast store lands (V4-P12)", "site": "archetype",
                  "pv_availability": "proxy, system-wide cf", "reg_drift": "seeded", "rt_as": "not modelled (V4-P6)"},
        "licence": "ERCOT data with attribution and no endorsement; NOAA and IEM with attribution; EIA public domain"}
        | meta, indent=1) + "\n")


def build_packs(args):
    """The ercot-front-v4-* packs from the store: candidates per split, refs, filters, the front/calm draw."""
    store, eia = Path(args.store), Path(args.eia)
    out = Path(args.out)
    t0 = time.time()
    stats = {}
    jobs = []
    for split in [s for s in args.splits if s != "showcase"]:
        tiers = ("front-lite",) if split == "train" else F.TIERS
        n = args.limit or CANDIDATES[split]
        jobs += [(d1, p, split, tiers, str(store), str(eia), None) for d1, p in candidates(split, n)]
    if "showcase" in args.splits or not args.splits:
        jobs += [(d1, p, "showcase", F.TIERS, str(store), str(eia), name) for name, (d1, p) in SHOWCASE.items()]
    with mp.Pool(args.workers, initializer=_init, initargs=(args.cache,)) as pool:
        rows = [r for r in pool.imap_unordered(build_store_row, jobs, chunksize=1) if r is not None]
    errors = [r for r in rows if "_error" in r]
    rows = [r for r in rows if "_error" not in r]
    for split in [s for s in args.splits if s != "showcase"]:
        tier = "front-lite" if split == "train" else "front"
        pool_rows = [r for r in rows if r["split"] == split]
        floor = hind_floor(pool_rows, tier)
        ok = [r for r in pool_rows if eligible(r["_score"][tier], floor)]
        chosen = select(ok, args.limit and min(len(ok), TARGETS[split]) or TARGETS[split], FRONT_SHARE[split], split)
        labels = collections.Counter(r["tags"]["label"] for r in pool_rows)
        stats[split] = {"candidates": len(pool_rows), "candidate_labels": dict(labels),
                        "hind_floor_usd_per_kw": round(floor, 4), "eligible": len(ok),
                        "eligible_labels": dict(collections.Counter(r["tags"]["label"] for r in ok)),
                        "eligible_d1": {lab: len({r["d1"] for r in ok if r["tags"]["label"] == lab}) for lab in labels},
                        "chosen": len(chosen), "front": sum(r["tags"]["label"] == "front" for r in chosen),
                        "sources": dict(collections.Counter(r["source"] for r in chosen)),
                        "mean_ms": round(float(np.mean([r["_ms"] for r in pool_rows])), 1) if pool_rows else None}
        write(out, PACKS[split], chosen, {"filters": FILTER, "stats": stats[split], "store": args.store})
    show = sorted((r for r in rows if r["split"] == "showcase"), key=lambda r: r["d1"])
    if show:
        write(out, PACKS["showcase"], show, {"display_only": True})
    log(f"packs {stats}; {len(errors)} errors; {time.time() - t0:.0f} s")
    for e in errors[:5]:
        log(f"error {e['task_id']}: {e['_error']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fixtures", action="store_true", help="build data/fixtures-forecast (synthetic slices)")
    ap.add_argument("--store", help="the forecast store (cache/forecast/store): build the ercot-front-v4-* packs")
    ap.add_argument("--eia", default=str(ROOT / "cache" / "forecast" / "eia930"))
    ap.add_argument("--splits", nargs="*", default=["train", "eval", "rtcb", "showcase"])
    ap.add_argument("--limit", type=int, default=0, help="candidates per split (a smoke run)")
    ap.add_argument("--cache", default=str(ROOT / "cache" / "parsed"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 2))
    args = ap.parse_args()
    if args.store:
        build_packs(args)
        return
    if not args.fixtures:
        ap.error("pass --fixtures, or --store for the packs")
    dam, rt = caches(Path(args.cache))
    arch = HI.archetypes()
    rows = []
    for i, (d1, point, kind) in enumerate(FIXTURES):
        t = window(d1, point, site_for(kind, d1, point, arch), dam, rt, days=3)
        if t is None:
            log(f"skip {d1} {point}: missing input or DST/era")
            continue
        t["pack"], t["split"] = "fixtures-forecast", "fixtures"
        t["tags"] = {"fixture": i, "showcase": None}
        rows.append(t)
    t0 = time.time()
    with mp.Pool(min(args.workers, len(rows))) as pool:
        built = pool.map(build_one, [(t, F.TIERS) for t in rows])
    for t in built:
        tr = t["refs"]
        log(f"{t['task_id']}: {t['_ms']} ms, front roll {tr['front']['p_roll']:.0f} idle {tr['front']['p_idle']:.0f} "
            f"hind {tr['front']['p_hind']:.0f}; lite roll {tr['front-lite']['p_roll']:.0f}")
    write(Path(args.out), "fixtures-forecast", built, {"build_seconds": round(time.time() - t0, 1),
                                                       "build_command": "python scripts/build_forecast_pack.py "
                                                                        "--fixtures"})
    log(f"wrote {len(built)} fixtures in {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
