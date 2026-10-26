"""Build a fresh pack from ERCOT public-API DAM prices with build_pack.py's logic:
python scripts/build_fresh_pack.py --api DIR_OR_CSV --start 2026-10-18 --end 2026-10-27 --name fresh-2026-10.

Days come from the API pull (NP4-190-CD); the blind tier's D-7..D-1 history also reads cache/raw's NP4-180-ER files,
and the two must agree exactly on every day they share. Each (date, point) after the within-date dedup gets
--draws archetype draws: draw 1 is rtcb's (salt ""), the rest use the train split's salt mechanism. Then the
low-spread and greedy-easy filters, every surviving task kept (no subsampling), blind inputs and refs where the
blind anchor clears the low-spread margin, as rtcb did."""

from __future__ import annotations

import argparse
import collections
import csv
import gzip
import io
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_pack import (  # noqa: E402
    EP_MIX,
    GREEDY_EASY,
    GREEDY_EASY_DROP,
    LOW_SPREAD_PER_MW,
    POINTS,
    _init_worker,
    _refs_worker,
    baseline_means,
    blind_ok,
    dedup,
    dst_dates,
    finalize,
    greedy_easy_drop,
    load_dam,
    low_spread,
    make_candidate,
    sha256,
)

from gridsim_core import CONTRACT_VERSION  # noqa: E402
from gridsim_core.contract import price_violations  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = ("NP4-190-CD (DAM Settlement Point Prices), ERCOT public API, "
          "/api/public-reports/np4-190-cd/dam_stlmnt_pnt_prices")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--draws", type=int, default=4)
    ap.add_argument("--raw", default=str(ROOT / "cache" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    args = ap.parse_args()
    pack = f"ercot-dam-v1-{args.name}"
    out = Path(args.out) / pack
    out.mkdir(parents=True, exist_ok=True)
    rows = api_rows(Path(args.api))
    csv_path = out / "dam_spp_api.csv.gz"
    if Path(args.api).resolve() != csv_path.resolve():
        write_csv(csv_path, rows)
    api, api_stats = clean(rows)
    hist, _ = load_dam(Path(args.raw) / "ercot", ROOT / "cache" / "parsed", 4)
    shared = sorted(k for k in api if k in hist)
    diff = max((float(np.abs(api[k] - hist[k]).max()) for k in shared), default=0.0)
    if diff > 0:
        sys.exit(f"API and NP4-180-ER disagree on shared point-days (max abs diff {diff})")
    dam = {**hist, **api}
    fresh = {k: v for k, v in api.items() if args.start <= k[0] <= args.end}
    kept, dedup_stats = dedup(fresh)
    table = json.loads((ROOT / "data" / "ercot-dam-v1-rtcb" / "manifest.json").read_text())["letters"]
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())
    salts = [""] + [str(i) for i in range(2, args.draws + 1)]
    cands = {}
    for k in kept:
        for s in salts:
            c = make_candidate(k, dam, table, s)
            c["_draw"] = salts.index(s) + 1
            cands.setdefault(c["task_id"], c)
    _init_worker(ridge)
    cands = [_refs_worker(c) for c in cands.values()]
    ls = [c for c in cands if low_spread(c)]
    pool = [c for c in cands if not low_spread(c)]
    easy = [c for c in pool if greedy_easy_drop(c)]
    pool = sorted((c for c in pool if not greedy_easy_drop(c)), key=lambda t: (t["date"], POINTS.index(
        t["settlement_point"]), t["task_id"]))
    tasks = []
    for c in pool:
        t = finalize(c, "rtcb", bool(c["blind"]) and blind_ok(c))
        t["pack"], t["split"] = pack, args.name.replace("-", "_")
        t["tags"]["draw"] = c["_draw"]
        tasks.append(t)
    with gzip.GzipFile(out / "tasks.jsonl.gz", "wb", mtime=0) as f:
        for t in tasks:
            f.write((json.dumps(t, separators=(",", ":")) + "\n").encode())
    days = sorted({k[0] for k in fresh})
    count = collections.Counter
    manifest = {
        "pack": pack, "contract_version": CONTRACT_VERSION, "count": len(tasks),
        "count_blind": sum(t["tags"]["blind_eval"] for t in tasks),
        "blind_task_ids": sorted(t["task_id"] for t in tasks if t["tags"]["blind_eval"]),
        "date_range": [args.start, args.end], "days": days,
        "by_date": dict(sorted(count(t["date"] for t in tasks).items())),
        "by_ep": dict(sorted(count(t["battery"]["archetype"].split("-")[0] for t in tasks).items())),
        "by_point": dict(sorted(count(t["settlement_point"] for t in tasks).items())),
        "by_curriculum": dict(sorted(count(t["curriculum"] for t in tasks).items())),
        "by_draw": dict(sorted(count(t["tags"]["draw"] for t in tasks).items())),
        "means": baseline_means(tasks), "tasks_sha256": sha256(out / "tasks.jsonl.gz"),
        "archetype_mix": {f"{k}h": v for k, v in EP_MIX.items()}, "draws_per_point_day": args.draws,
        "draw_salts": salts,
        "filters": {"low_spread_per_mw": LOW_SPREAD_PER_MW, "greedy_easy": GREEDY_EASY,
                    "greedy_easy_drop": GREEDY_EASY_DROP, "dedup": "corr > 0.999 and max abs diff < $1 within a date",
                    "point_days": len(fresh), "dedup_kept": len(kept), "candidates": len(cands),
                    "low_spread_dropped": len(ls), "greedy_easy_dropped": len(easy), "kept": len(tasks),
                    "blind_candidates": sum(bool(c["blind"]) for c in pool),
                    "blind_anchor_dropped": sum(bool(c["blind"]) and not blind_ok(c) for c in pool),
                    "subsample": "none: every surviving task is kept"},
        "dedup": dedup_stats, "letters_from": "data/ercot-dam-v1-rtcb/manifest.json letters (the v1 table)",
        "ridge": "data/ridge-v1.json",
        "sources": {"api_report": REPORT, "api_csv": csv_path.name, "api_csv_sha256": sha256(csv_path),
                    "api_parse": api_stats,
                    "history": "cache/raw/ercot/DAMLZHBSPP_2026.zip (NP4-180-ER) before the API days",
                    "history_sha256": sha256(Path(args.raw) / "ercot" / "DAMLZHBSPP_2026.zip"),
                    "api_vs_np4_180_er": {"shared_point_days": len(shared),
                                          "shared_dates": sorted({k[0] for k in shared}), "max_abs_diff": diff}},
        "build_command": "python scripts/build_fresh_pack.py " + " ".join(sys.argv[1:]),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(json.dumps({k: manifest[k] for k in ("count", "count_blind", "by_date", "by_ep", "means", "filters")}))


def api_rows(src: Path) -> list[dict]:
    if src.is_dir():
        rows = []
        for f in sorted(src.glob("*.json")):
            j = json.loads(f.read_text())
            rows += [dict(zip(j["fields"], r, strict=True)) for r in j["data"]]
        return [{"deliveryDate": str(r["deliveryDate"]), "hourEnding": str(r["hourEnding"]),
                 "settlementPoint": str(r["settlementPoint"]), "settlementPointPrice": float(r["settlementPointPrice"]),
                 "DSTFlag": str(r["DSTFlag"])} for r in rows]
    with gzip.open(src, "rt") as f:
        return [dict(r, settlementPointPrice=float(r["settlementPointPrice"])) for r in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict]):
    buf = io.StringIO()
    w = csv.DictWriter(buf, ["deliveryDate", "hourEnding", "settlementPoint", "settlementPointPrice", "DSTFlag"],
                       lineterminator="\n")
    w.writeheader()
    for r in sorted(rows, key=lambda r: (r["deliveryDate"], r["settlementPoint"], r["hourEnding"])):
        w.writerow(r)
    with gzip.GzipFile(path, "wb", mtime=0) as f:
        f.write(buf.getvalue().encode())


def clean(rows: list[dict]) -> tuple[dict, dict]:
    """build_pack.load_dam's checks on API rows: the v1 points, no DST day, exactly HE1..24, inside the era caps."""
    vals, flags, st = collections.defaultdict(dict), collections.Counter(), collections.Counter()
    for r in rows:
        k = (r["deliveryDate"], r["settlementPoint"])
        he = int(r["hourEnding"].split(":")[0])
        if r["DSTFlag"].lower() == "true" or he in vals[k]:
            flags[k] += 1
            continue
        vals[k][he] = r["settlementPointPrice"]
    dst = set().union(*(dst_dates(y) for y in range(2025, 2028)))
    dam = {}
    for k, hv in vals.items():
        st["point_days_raw"] += 1
        if k[1] not in POINTS:
            st["other_point"] += 1
        elif k[0] in dst:
            st["dst_dropped"] += 1
        elif flags.get(k) or sorted(hv) != list(range(1, 25)):
            st["not_24_dropped"] += 1
        elif price_violations(k[0], [hv[h] for h in range(1, 25)]):
            st["era_flagged"] += 1
        else:
            dam[k] = np.array([hv[h] for h in range(1, 25)])
    st["clean_point_days"] = len(dam)
    return dam, dict(st) | {"dates": sorted({k[0] for k in dam})}


if __name__ == "__main__":
    main()
