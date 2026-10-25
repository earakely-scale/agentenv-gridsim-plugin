"""Build the GridSimEnv v2 live packs from cache/raw: python scripts/build_live_pack.py [--workers N].

python scripts/build_live_pack.py --merge-notices data/notices/notices.jsonl re-attaches notices to the built packs
and recomputes their references, eligibility and tags without re-parsing."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import multiprocessing as mp
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pack as v1  # noqa: E402

from gridsim_core import CONTRACT_VERSION, live  # noqa: E402
from gridsim_core import notices as archive  # noqa: E402
from gridsim_core.contract import era  # noqa: E402
from gridsim_core.grade import reward_value  # noqa: E402
from gridsim_core.task import REGIONS, make_battery, point_kind, stable_seed  # noqa: E402

POINTS = v1.POINTS
SHOWCASE = {"sep23-0906": "2023-09-06", "uri-0215": "2021-02-15", "elliott-1223": "2022-12-23",
            "heather-0116": "2024-01-16", "aug23-0820": "2023-08-20", "fern-0126": "2026-01-26"}
HERO = "sep23-0906"
SHOWCASE_PAD = 3
TRAIN = ("2019-01-01", "2024-12-31")
EVAL_YEAR = "2024"
TEST = ("2025-01-01", "2025-11-30")
RTCB = ("2025-12-05", "2026-10-17")
TARGETS = {"train": 4000, "eval": 300, "test": 200, "rtcb": 100}
PACKS = {"train": "gridsim-live-train", "eval": "gridsim-live-eval", "test": "gridsim-live-test-2025",
         "rtcb": "gridsim-live-rtcb", "showcase": "gridsim-live-showcase", "fixtures": "fixtures-live"}
SPLITS = {"train": "train", "eval": "eval_2024", "test": "test_2025", "rtcb": "rtcb", "showcase": "showcase",
          "fixtures": "fixtures"}
EP_MIX = v1.EP_MIX
FILTER = {"divergence_usd_per_mw": 40.0, "roll_minus_naive_share": 0.05, "roll_minus_naive_usd_per_mw": 5.0,
          "hind_headroom_usd_per_mw": 10.0}
NAIVE_R_CEILING = 0.7
NOTICE_DAYS_EXEMPT = True
"""Contract L-D9: notice days skip the anchor-beats-naive criterion (X6 days, scored by the beat-anchor rate)."""
NOTICE_SHARE = {"train": 0.40, "eval": 0.50, "test": 0.30, "rtcb": 0.30}
"""Notice-day share: a target for train and eval, a cap for test and rtcb (L-D9 lets notice days pass the filter)."""
NWS_KEEP = {(ph, sg) for ph in archive.NWS_DAY_PHENOMENA for sg in ("W", "A")} | {("HT", "Y")}
NWS_LEVEL = {"W": "Warning", "A": "Watch", "Y": "Advisory"}
ERCOT_EVAL_DAYS: set[str] = set()
SHARE_STEPS = (0.05, 0.075, 0.10, 0.125, 0.15)
TUNE_DIVERGENCE = (20.0, 40.0, 60.0)
BLIND_MIN_USD_PER_MW = 1.0
SALTS = {"train": 8, "eval": 12, "test": 3, "rtcb": 3}
"""Battery draws per point-day: the anchor beats naive by the filter's margin on only a few percent of draws."""


def log(msg: str):
    print(f"[build_live_pack] {msg}", flush=True)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _parse_rt_year(path: str) -> tuple[dict, dict]:
    """{(date, point): {interval 0..95: price}} and duplicate/repeated-hour counts; load zones use LZ, not LZEW."""
    z = zipfile.ZipFile(path)
    wb = openpyxl.load_workbook(io.BytesIO(z.read(z.namelist()[0])), read_only=True, data_only=True)
    vals, flags = collections.defaultdict(dict), collections.defaultdict(int)
    for ws in wb.worksheets:
        ws.reset_dimensions()
        rows = ws.iter_rows(values_only=True)
        head = [str(h).strip() for h in next(rows)]
        i_d, i_h, i_i = head.index("Delivery Date"), head.index("Delivery Hour"), head.index("Delivery Interval")
        i_r, i_p, i_v = head.index("Repeated Hour Flag"), head.index("Settlement Point Name"), head.index(
            "Settlement Point Price")
        i_k = head.index("Settlement Point Type")
        for r in rows:
            if r[i_d] is None or str(r[i_p]).strip() not in POINTS or str(r[i_k]).strip() == "LZEW":
                continue
            d = r[i_d]
            d = d.date().isoformat() if isinstance(d, dt.datetime) else dt.datetime.strptime(str(d), "%m/%d/%Y").date(
            ).isoformat()
            key = (d, str(r[i_p]).strip())
            if str(r[i_r]).strip().upper() == "Y":
                flags[key] += 1
                continue
            t = (int(r[i_h]) - 1) * 4 + int(r[i_i]) - 1
            if t in vals[key]:
                flags[key] += 1
            vals[key][t] = float(r[i_v])
    return dict(vals), dict(flags)


def load_rt(rt_dir: Path, cache: Path, workers: int) -> tuple[dict, dict]:
    """{(date, point): np.array[96]} for complete non-DST days, plus parse statistics; cached by zip hashes."""
    zips = sorted(rt_dir.glob("RTMLZHBSPP_*.zip"))
    key = hashlib.sha256("".join(sha256(z) for z in zips).encode()).hexdigest()[:16]
    cache.mkdir(parents=True, exist_ok=True)
    cp = cache / f"rt-{key}.json.gz"
    if cp.exists():
        with gzip.open(cp, "rt") as f:
            blob = json.load(f)
        return {tuple(k.split("|")): np.array(v) for k, v in blob["rt"].items()}, blob["stats"]
    with mp.Pool(min(workers, len(zips))) as pool:
        parts = pool.map(_parse_rt_year, [str(z) for z in zips])
    rt, st = {}, collections.Counter()
    dst = set().union(*(v1.dst_dates(y) for y in range(2014, 2028)))
    for vals, flags in parts:
        for k, tv in vals.items():
            st["point_days_raw"] += 1
            if k[0] in dst:
                st["dst_dropped"] += 1
                continue
            if flags.get(k) or sorted(tv) != list(range(96)):
                st["not_96_dropped"] += 1
                continue
            rt[k] = np.array([tv[t] for t in range(96)])
    stats = dict(st) | {"clean_point_days": len(rt), "first_date": min(d for d, _ in rt),
                        "last_date": max(d for d, _ in rt), "zips": [z.name for z in zips]}
    with gzip.open(cp, "wt") as f:
        json.dump({"rt": {f"{k[0]}|{k[1]}": v.tolist() for k, v in rt.items()}, "stats": stats}, f)
    return rt, stats


def dedup(keys: list, dam: dict, rt: dict) -> tuple[list, dict]:
    """Within a date, drop a point whose DA and RT prices both match a kept one (max abs diff < $1, corr > 0.999)."""
    def same(x, y):
        return np.abs(x - y).max() < 1.0 and (x.std() < 1e-9 or y.std() < 1e-9 or np.corrcoef(x, y)[0, 1] > 0.999)

    by_date = collections.defaultdict(list)
    for d, p in keys:
        by_date[d].append(p)
    kept, dropped = [], collections.Counter()
    for d in sorted(by_date):
        chosen = []
        for p in sorted(by_date[d], key=POINTS.index):
            dup = next((q for q in chosen if same(dam[(d, p)], dam[(d, q)]) and same(rt[(d, p)], rt[(d, q)])), None)
            if dup:
                dropped[p] += 1
            else:
                chosen.append(p)
                kept.append((d, p))
    return kept, {"dropped": sum(dropped.values()), "by_point": dict(sorted(dropped.items()))}


def near_showcase(d: str) -> str | None:
    day = dt.date.fromisoformat(d)
    for name, s in SHOWCASE.items():
        if abs((day - dt.date.fromisoformat(s)).days) <= SHOWCASE_PAD:
            return name
    return None


def split(d: str) -> str | None:
    """train | eval | test | rtcb | showcase | None; eval is every third 2024 date plus every 2024 ERCOT notice day,
    out of train."""
    if d in SHOWCASE.values():
        return "showcase"
    if near_showcase(d):
        return None
    if d.startswith(EVAL_YEAR) and ((dt.date.fromisoformat(d) - dt.date(2024, 1, 1)).days % 3 == 1
                                    or d in ERCOT_EVAL_DAYS):
        return "eval"
    if TRAIN[0] <= d <= TRAIN[1]:
        return "train"
    if TEST[0] <= d <= TEST[1]:
        return "test"
    if RTCB[0] <= d <= RTCB[1]:
        return "rtcb"
    return None


def live_battery(row: dict) -> dict:
    """A v1 archetype letter re-gridded to k_dis = 4 (contract L-D6)."""
    ep, n_v1 = row["ep_h"], row["soc_levels"]
    n = 4 * ep
    k_ch = 4 if row["k_ch"] >= row["k_dis"] else 3
    return make_battery(row["p_dis_mw"], row["p_dis_mw"] * ep, 4, k_ch=k_ch, eta=row["eta"], c_deg=row["c_deg"],
                        cycles=row["cycles"], s0=math.floor(row["s0"] / n_v1 * n + 0.5),
                        s_end_min=math.floor(row["s_end_min"] / n_v1 * n + 0.5), archetype=f"{ep}h-{row['letter']}")


def pick_letter(d: str, p: str, table: dict, salt: str = "live", ep: int | None = None) -> dict:
    h = stable_seed(f"{salt}|{d}|{p}")
    if ep is None:
        u, acc, ep = (h % 100000) / 100000, 0.0, 4
        for e, w in EP_MIX.items():
            acc += w
            if u < acc:
                ep = e
                break
    return table[f"{ep}h"][(h // 100000) % 26]


def core_notice(n: dict, date: str) -> dict:
    """An archive row as the Session's notice: ids, times, level and lane N's paraphrased summary, never the verbatim
    text (V2-D4); NWS rows get a generated one-line summary."""
    if n["source"] == "NWS":
        cs = n.get("counties") or []
        where = ", ".join(cs[:3]) + (f" and {len(cs) - 3} more counties" if len(cs) > 3 else "")
        until = live.label(live.to_minutes(n["expires_at_utc"], date), date)
        text = f"NWS {n['wfo']}: {n['name']} for {where or n['region']} until {until} CPT."
        return {"event_id": n["notice_id"], "source": "NWS", "kind": f"nws:{n['phenomena']}.{n['significance']}",
                "level": NWS_LEVEL.get(n["significance"]), "issued_at": n["issued_at_utc"], "name": f"NWS {n['wfo']}",
                "title": n["name"], "text": text[:live.NOTICE_CHARS]}
    minute = n["timestamp_quality"] == "minute" and n.get("issued_at_utc")
    label = f"ERCOT {n.get('level') or n.get('type') or 'notice'}"
    return {"event_id": n["notice_id"], "source": "ERCOT", "kind": str(n.get("type") or "other"),
            "level": n.get("level"), "issued_at": n["issued_at_utc"] if minute else n["reveal_at"], "name": "ERCOT",
            "title": label + (" cancelled" if n.get("action") == "cancel" else ""), "action": n.get("action"),
            "text": str(n.get("summary") or n.get("level") or "")[:live.NOTICE_CHARS]}


def day_notices(date: str, point: str, root: str | None = None) -> list[dict]:
    """The live day's notices at a point: ERCOT grid-condition rows and the region's load-moving NWS warnings and
    watches plus heat advisories (provisional)."""
    rows = [n for n in archive.notices_for(date, point, root=root)
            if n["source"] == "ERCOT" or (n.get("phenomena"), n.get("significance")) in NWS_KEEP]
    return [core_notice(n, date) for n in rows]


def day_kind(date: str, point: str, root: str | None = None) -> str:
    """notice | quiet (fully covered by the archive, no notice) | unknown (an archive gap: not known quiet)."""
    if archive.is_notice_day(date, point, root):
        return "notice"
    return "quiet" if archive.coverage(date, root) >= 1.0 else "unknown"


def ercot_notice_day(date: str) -> bool:
    return any(n["source"] == "ERCOT" and n["when"] != "board" and n.get("action") == "issue"
               and n["timestamp_quality"] == "minute" for n in archive.notices_for(date, "HB_HUBAVG", nws=False))


_DAY: dict = {}


def day_info(date: str, point: str) -> tuple[list, str]:
    if (date, point) not in _DAY:
        _DAY[(date, point)] = (day_notices(date, point), day_kind(date, point))
    return _DAY[(date, point)]


def make_candidate(key: tuple, dam: dict, rt: dict, table: dict, ep: int | None = None, salt: str = "live") -> dict:
    d, p = key
    b = live_battery(pick_letter(d, p, table, salt, ep))
    ns, kind = day_info(d, p)
    return {"task_id": f"live-v2-{d}-{p}-{b['archetype']}", "live_version": live.LIVE_VERSION,
            "contract_version": CONTRACT_VERSION, "pack": None, "split": None, "date": d, "settlement_point": p,
            "point_kind": point_kind(p), "region": REGIONS[p], "prices": [round(float(v), 2) for v in dam[key]],
            "rt": [round(float(v), 2) for v in rt[key]], "blind": v1.lags(dam, d, p), "battery": b, "notices": ns,
            "notices_sha": live.notices_sha(ns), "_kind": kind}


def eligibility(t: dict) -> dict:
    r, mw = t["refs"], float(t["battery"]["p_dis_mw"])
    da, rt = np.repeat(np.asarray(t["prices"]), 4), np.asarray(t["rt"])
    roll = r["roll"]["foresight"]["p_roll"]
    head = r["p_hind"] - r["p_idle"]
    return {"divergence_usd_per_mw": round(float(np.abs(rt - da).sum() * 0.25), 4),
            "roll_minus_naive_share": round((roll - r["p_naive"]) / head, 6) if head > 1e-9 else None,
            "roll_minus_naive_usd_per_mw": round((roll - r["p_naive"]) / mw, 6),
            "hind_headroom_usd_per_mw": round(head / mw, 6)}


def eligible(e: dict, f: dict = FILTER, notice: bool = False) -> bool:
    """The v2 plan's filter; a notice day skips the anchor-beats-naive criterion when NOTICE_DAYS_EXEMPT (L-D9)."""
    base = (e["divergence_usd_per_mw"] >= f["divergence_usd_per_mw"]
            and e["hind_headroom_usd_per_mw"] >= f["hind_headroom_usd_per_mw"])
    if notice and NOTICE_DAYS_EXEMPT:
        return base
    return (base and e["roll_minus_naive_share"] is not None
            and e["roll_minus_naive_share"] >= f["roll_minus_naive_share"]
            and e["roll_minus_naive_usd_per_mw"] >= f["roll_minus_naive_usd_per_mw"])


def tags(t: dict, showcase: str | None = None) -> dict:
    rt = np.asarray(t["rt"])
    m = int(t["date"][5:7])
    season = "winter" if m in (12, 1, 2) else "spring" if m <= 5 else "summer" if m <= 8 else "fall"
    ws = live.schedule(t, "foresight")
    kind = t.get("_kind") or day_info(t["date"], t["settlement_point"])[1]
    return {"watches": len(ws), "short_ok": len(live.schedule(t, "short")) <= live.SHORT_MAX_WATCHES,
            "day_kind": kind, "notice_day": kind == "notice", "coverage": archive.coverage(t["date"]),
            "notices": len(t["notices"]), "notice_watches": len(ws) - len(live.REGULAR["foresight"]),
            "after_day": len(live.after_day(t)), "season": season,
            "era": era(t["date"])["name"], "neg_intervals": int((rt < 0).sum()),
            "rt_spike": bool(rt.max() >= max(500.0, 3 * float(np.median(np.abs(rt))))),
            "blind_eval": bool((t["refs"]["roll"].get("blind") or {}).get("p_roll") is not None),
            "showcase": showcase}


def _foresight_worker(t: dict) -> dict:
    t["refs"] = live.references(t, "foresight", lp=False)
    t["eligibility"] = eligibility(t)
    return t


_RIDGE = None


def _init_worker(ridge):
    global _RIDGE
    _RIDGE = ridge


def _full_worker(t: dict) -> dict:
    """Every tier's anchor, the LP bound, eligibility and tags for a selected task."""
    base = live.references(t, ("foresight", "short", "freeze6h") + (("blind",) if t["blind"] else ()), ridge=_RIDGE)
    if t["blind"]:
        bl = base["roll"]["blind"]
        if bl["p_roll"] - base["p_idle"] < BLIND_MIN_USD_PER_MW * float(t["battery"]["p_dis_mw"]):
            base["roll"]["blind"] = None
    else:
        base["roll"]["blind"] = None
    if not live.schedule(t, "short") or len(live.schedule(t, "short")) > live.SHORT_MAX_WATCHES:
        base["roll"]["short"] = None
    t["refs"] = base
    t["eligibility"] = eligibility(t)
    if base["roll"]["blind"] is None:
        t["blind"] = None
    return t


def stratified(tasks: list, n: int, salt: str) -> list:
    return v1.stratified(tasks, n, lambda t: (t["settlement_point"], t["battery"]["archetype"].split("-")[0],
                                              t["date"][5:7]), salt)


def select(ok: list, n: int, sp: str) -> list:
    """Up to n tasks, one battery per point-day first (hash order, stratified outside train), then a second, ..."""
    ranked = collections.defaultdict(list)
    for t in sorted(ok, key=lambda t: stable_seed(sp + "|rank|" + t["task_id"])):
        ranked[(t["date"], t["settlement_point"])].append(t)
    out, depth = [], 0
    while len(out) < n and any(len(v) > depth for v in ranked.values()):
        layer = [v[depth] for v in ranked.values() if len(v) > depth]
        need = n - len(out)
        if sp == "train":
            out += sorted(layer, key=lambda t: stable_seed("train|" + t["task_id"]))[:need]
        else:
            out += stratified(layer, need, f"{sp}|{depth}|")
        depth += 1
    return out


def naive_r(t: dict) -> float:
    r = t["refs"]
    return reward_value(r["p_naive"], r["p_idle"], r["roll"]["foresight"]["p_roll"])


def capture(t: dict, p: float) -> float | None:
    r = t["refs"]
    head = r["p_hind"] - r["p_idle"]
    return (p - r["p_idle"]) / head if head > 1e-9 else None


def tune(cands: list) -> tuple[dict, list]:
    """The eligibility table over thresholds, and the filter V2-D5 picks: the smallest anchor-beats-naive share whose
    eval naive mean R is at most NAIVE_R_CEILING (capped at 15%)."""
    rows = []
    for div in TUNE_DIVERGENCE:
        for share in SHARE_STEPS:
            f = FILTER | {"divergence_usd_per_mw": div, "roll_minus_naive_share": share}
            for sp in ("train", "eval", "test", "rtcb"):
                pool = [c for c in cands if c["_split"] == sp and c["_kind"] != "notice"]
                kept = [c for c in pool if eligible(c["eligibility"], f)]
                nr = [naive_r(c) for c in kept]
                rows.append({"split": sp, "divergence": div, "share": share, "candidates": len(pool),
                             "kept": len(kept), "kept_share": round(len(kept) / max(len(pool), 1), 4),
                             "naive_r_mean": round(float(np.mean(nr)), 4) if nr else None})
    chosen = dict(FILTER)
    for share in SHARE_STEPS:
        chosen["roll_minus_naive_share"] = share
        ev = [naive_r(c) for c in cands if c["_split"] == "eval" and c["_kind"] != "notice"
              and eligible(c["eligibility"], chosen)]
        if ev and float(np.mean(ev)) <= NAIVE_R_CEILING:
            break
    return chosen, rows


def finalize(t: dict, sp: str, showcase: str | None = None) -> dict:
    out = {k: v for k, v in t.items() if not k.startswith("_")}
    out["pack"] = PACKS[sp]
    if sp != "fixtures":
        out["split"] = SPLITS[sp]
    out["tags"] = tags(out, showcase)
    if not out["tags"]["blind_eval"]:
        out["blind"] = None
    order = ["task_id", "live_version", "contract_version", "pack", "split", "date", "settlement_point", "point_kind",
             "region", "prices", "rt", "blind", "battery", "notices", "notices_sha", "refs", "eligibility", "tags"]
    return {k: out[k] for k in order}


def local_iso(date: str, minute: int) -> str:
    """CPT wall time at minute from D 00:00, with its UTC offset."""
    return (dt.datetime.fromisoformat(date) + dt.timedelta(minutes=minute)).replace(tzinfo=live.TZ).isoformat()


def fixture_derate(t: dict) -> dict:
    """A synthetic derate fixture on a real day (contract V2-D7: built and tested, never shipped as a bulletin)."""
    d = t["date"]
    n = {"event_id": "fixture-derate-1", "source": "asset", "kind": "derate", "level": None,
         "issued_at": local_iso(d, 16 * 60 + 50), "name": "Plant operator",
         "title": "Synthetic CI fixture: inverter derate",
         "text": "Synthetic CI fixture, not an ERCOT notice: half the battery's inverters trip from 17:00 to 20:00.",
         "derate_mw": float(t["battery"]["p_dis_mw"]) / 2, "from": local_iso(d, 17 * 60),
         "until": local_iso(d, 20 * 60)}
    return attach(t, [n], "derate")


def fixture_notice(t: dict) -> dict:
    d = t["date"]
    ns = [{"event_id": "fixture-board-1", "source": "ERCOT", "kind": "watch", "level": "Watch",
           "issued_at": local_iso(d, -15 * 60), "name": "ERCOT",
           "title": "Synthetic CI fixture: weather watch",
           "text": "Synthetic CI fixture, not an ERCOT notice: a weather watch for the operating day."},
          {"event_id": "fixture-appeal-1", "source": "ERCOT", "kind": "conservation", "level": "Advisory",
           "issued_at": local_iso(d, 14 * 60 + 20), "name": "ERCOT",
           "title": "Synthetic CI fixture: conservation appeal",
           "text": "Synthetic CI fixture, not an ERCOT notice: conserve power from 16:00 to 21:00."}]
    return attach(t, ns, "notice")


def attach(t: dict, notices: list, kind: str) -> dict:
    out = dict(t, notices=notices, notices_sha=live.notices_sha(notices), task_id=f"{t['task_id']}-{kind}")
    return out


def fixtures(packs: dict) -> list:
    """20 CI tasks: every E/P class and split, blind, short, an s_end_min > s0 day, negative RT, an RT spike, a
    synthetic notice day and a synthetic derate day."""
    pool = packs["eval"] + packs["test"] + packs["rtcb"]
    out, seen = [], set()

    def take(pred, n):
        for t in sorted(pool, key=lambda t: stable_seed("fxl|" + t["task_id"])):
            if len([x for x in out if pred(x)]) >= n or len(out) >= 18:
                return
            if pred(t) and t["task_id"] not in seen:
                out.append(t)
                seen.add(t["task_id"])

    take(lambda t: t["tags"]["blind_eval"], 4)
    take(lambda t: t["battery"]["s_end_min"] > t["battery"]["s0"], 2)
    for ep in ("1h", "2h", "4h"):
        take(lambda t, ep=ep: t["battery"]["archetype"].startswith(ep), 3)
    for sp in ("eval_2024", "test_2025", "rtcb"):
        take(lambda t, sp=sp: t["split"] == sp, 3)
    take(lambda t: t["tags"]["neg_intervals"] > 0, 1)
    take(lambda t: t["tags"]["rt_spike"], 1)
    take(lambda t: True, 18)
    base = [t for t in pool if t["task_id"] not in seen] or pool
    extra = [fixture_notice(base[0]), fixture_derate(base[1])]
    return [dict(t, pack=PACKS["fixtures"]) for t in out[:18]] + [dict(t, pack=PACKS["fixtures"]) for t in extra]


def write_pack(out: Path, name: str, tasks: list, meta: dict):
    d = out / PACKS[name]
    d.mkdir(parents=True, exist_ok=True)
    with gzip.GzipFile(d / "tasks.jsonl.gz", "wb", mtime=0) as f:
        for t in tasks:
            f.write((json.dumps(t, separators=(",", ":")) + "\n").encode())
    manifest = {"pack": PACKS[name], "live_version": live.LIVE_VERSION, "contract_version": CONTRACT_VERSION,
                "count": len(tasks), "count_blind": sum(t["tags"]["blind_eval"] for t in tasks),
                "count_short": sum(t["tags"]["short_ok"] for t in tasks),
                "count_notice_days": sum(t["tags"]["notice_day"] for t in tasks),
                "date_range": [min(t["date"] for t in tasks), max(t["date"] for t in tasks)] if tasks else None,
                "by_ep": dict(sorted(collections.Counter(t["battery"]["archetype"][:2] for t in tasks).items())),
                "by_point": dict(sorted(collections.Counter(t["settlement_point"] for t in tasks).items())),
                "means": means(tasks), "tasks_sha256": sha256(d / "tasks.jsonl.gz"), **meta}
    if name == "showcase":
        manifest["bundles"] = meta.get("bundles")
    (d / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")


def means(tasks: list) -> dict:
    if not tasks:
        return {}
    out = {"naive_reward": round(float(np.mean([naive_r(t) for t in tasks])), 4)}
    for name, f in (("naive_capture", lambda t: capture(t, t["refs"]["p_naive"])),
                    ("roll_capture", lambda t: capture(t, t["refs"]["roll"]["foresight"]["p_roll"]))):
        xs = [x for x in (f(t) for t in tasks) if x is not None]
        out[name] = round(float(np.mean(xs)), 4) if xs else None
    out["watches"] = round(float(np.mean([t["tags"]["watches"] for t in tasks])), 3)
    out["roll_commits"] = round(float(np.mean([t["refs"]["roll"]["foresight"]["commits"] for t in tasks])), 3)
    return out


def quantiles(xs) -> str:
    xs = np.asarray([x for x in xs if x is not None], dtype=float)
    if not xs.size:
        return "| - | - | - | - | - | - |"
    qs = " | ".join(f"{np.quantile(xs, q):.4f}" for q in (0.05, 0.25, 0.5, 0.75, 0.95))
    return f"| {qs} | {xs.mean():.4f} |"


def write_stats(out: Path, packs: dict, cands: list, chosen: dict, tuning: list, filt: dict, rt_stats: dict,
                dedup_stats: dict, timing: dict):
    lines = ["# GridSimEnv v2 live pack statistics", "",
             f"Built by `scripts/build_live_pack.py` (live {live.LIVE_VERSION}, core contract {CONTRACT_VERSION}). "
             "All numbers are measured on the packs. Notices come from lane N's archive (`gridsim_core.notices`); "
             "a day is `notice`, `quiet` (archive coverage 1.0, no notice) or `unknown` (an archive gap).",
             "",
             "## Packs", "",
             "| pack | tasks | notice / quiet / unknown | blind | short | naive R | naive R notice | naive R quiet | "
             "naive capture | anchor capture | watches | anchor commits |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, tasks in packs.items():
        m = means(tasks)
        k = collections.Counter(t["tags"]["day_kind"] for t in tasks)
        by = {kind: [naive_r(t) for t in tasks if t["tags"]["day_kind"] == kind] for kind in ("notice", "quiet")}
        nr = {kind: round(float(np.mean(v)), 4) if v else None for kind, v in by.items()}
        lines.append(f"| {PACKS[name]} | {len(tasks)} | {k['notice']} / {k['quiet']} / {k['unknown']} | "
                     f"{sum(t['tags']['blind_eval'] for t in tasks)} | {sum(t['tags']['short_ok'] for t in tasks)} | "
                     f"{m.get('naive_reward')} | {nr['notice']} | {nr['quiet']} | {m.get('naive_capture')} | "
                     f"{m.get('roll_capture')} | {m.get('watches')} | {m.get('roll_commits')} |")
    lines += ["", "Naive R is naive's reward under the shared contract with the rolling anchor at 1.0 (idle 0.2). "
              "Capture is (P - P_idle) / (P_hind - P_idle), the weight-0 hindsight row.", ""]
    lines += ["## Distributions (quantiles p5, p25, p50, p75, p95, mean)", ""]
    for name in ("eval", "test", "rtcb", "train"):
        tasks = packs.get(name) or []
        if not tasks:
            continue
        lines += [f"### {PACKS[name]}", "", "| row | p5 | p25 | p50 | p75 | p95 | mean |",
                  "|---|---|---|---|---|---|---|",
                  "| naive R " + quantiles(naive_r(t) for t in tasks),
                  "| naive capture " + quantiles(capture(t, t["refs"]["p_naive"]) for t in tasks),
                  "| anchor capture " + quantiles(capture(t, t["refs"]["roll"]["foresight"]["p_roll"]) for t in tasks),
                  "| hindsight DA share " + quantiles(t["refs"]["p_hind_da"] / max(t["refs"]["p_hind"] -
                                                                                     t["refs"]["p_idle"], 1e-9)
                                                     for t in tasks),
                  "| freeze6h anchor capture " + quantiles(
                      capture(t, t["refs"]["roll"]["freeze6h"]["p_roll"]) for t in tasks),
                  "| blind anchor capture " + quantiles(capture(t, t["refs"]["roll"]["blind"]["p_roll"])
                                                        for t in tasks if t["refs"]["roll"].get("blind")),
                  "| RT-DA divergence $/MW " + quantiles(t["eligibility"]["divergence_usd_per_mw"] for t in tasks),
                  ""]
    lines += ["## Notices", "",
              "| pack | tasks with a notice watch | notice watches (mean) | at the 10-watch cap | notices after the "
              "last watch | anchor beats naive on notice days | distinct notice point-days |",
              "|---|---|---|---|---|---|---|"]
    for name, tasks in packs.items():
        nt = [t for t in tasks if t["tags"]["day_kind"] == "notice"]
        beats = sum(t["refs"]["roll"]["foresight"]["p_roll"] > t["refs"]["p_naive"] + 1e-6 for t in nt)
        lines.append(f"| {PACKS[name]} | {sum(t['tags']['notice_watches'] > 0 for t in tasks)} | "
                     f"{np.mean([t['tags']['notice_watches'] for t in tasks]):.2f} | "
                     f"{sum(t['tags']['watches'] >= live.MAX_WATCHES for t in tasks)} | "
                     f"{sum(t['tags']['after_day'] for t in tasks)} | {beats} of {len(nt)} | "
                     f"{len({(t['date'], t['settlement_point']) for t in nt})} |")
    lines += ["", "Candidates and eligible tasks by day kind (notice days skip the anchor-beats-naive criterion, L-D9; "
              "the last column is how many notice-day candidates would pass without that exemption):", "",
              "| split | notice | quiet | unknown | notice eligible without L-D9 | kept by kind |",
              "|---|---|---|---|---|---|"]
    for sp, s_ in filt.items():
        bk = s_["by_kind"]
        lines.append(f"| {sp} | {bk['notice'][0]} / {bk['notice'][1]} | {bk['quiet'][0]} / {bk['quiet'][1]} | "
                     f"{bk['unknown'][0]} / {bk['unknown'][1]} | {s_['notice_eligible_without_exemption']} | "
                     f"{json.dumps(s_['kept_by_kind'])} |")
    lines += ["", "## Eligibility filter", "",
              f"Chosen: {json.dumps(chosen)}. Spec start: {json.dumps(FILTER)}. V2-D5: the anchor-beats-naive share "
              f"is raised in steps {list(SHARE_STEPS)} until naive's mean R on the eval pool is at most "
              f"{NAIVE_R_CEILING} (capped at 15%), measured on non-notice candidates.", "",
              f"Candidates are point-days x battery draws per point-day ({json.dumps(SALTS)}); selection takes one "
              "battery per point-day before a second.", "",
              "| split | candidates | eligible | share | kept |", "|---|---|---|---|---|"]
    for sp, s in filt.items():
        lines.append(f"| {sp} | {s['candidates']} | {s['eligible']} | {s['eligible_share']} | {s['kept']} "
                     f"({s['point_days']} point-days) |")
    lines += ["", "Why candidates fail (foresight, chosen thresholds; a task can fail several):", "",
              "| split | divergence | hindsight headroom | anchor beats naive (share) | anchor beats naive ($/MW) |",
              "|---|---|---|---|---|"]
    for sp, s in filt.items():
        lines.append(f"| {sp} | {s['fail_divergence']} | {s['fail_headroom']} | {s['fail_share']} | {s['fail_usd']} |")
    lines += ["", "### Tuning table", "",
              "| split | divergence $/MW | share | candidates | kept | kept share | naive R |",
              "|---|---|---|---|---|---|---|"]
    for r in tuning:
        lines.append(f"| {r['split']} | {r['divergence']} | {r['share']} | {r['candidates']} | {r['kept']} | "
                     f"{r['kept_share']} | {r['naive_r_mean']} |")
    allc = [c for c in cands if c["_split"] in ("train", "eval", "test", "rtcb")]
    rn = [(c["refs"]["roll"]["foresight"]["p_roll"] - c["refs"]["p_naive"]) for c in allc]
    lines += ["", "## All candidates (before the filter)", "",
              f"- Candidates: {len(allc)}; anchor above naive on {sum(x > 1e-6 for x in rn)}, equal on "
              f"{sum(abs(x) <= 1e-6 for x in rn)}, below on {sum(x < -1e-6 for x in rn)}.",
              "- naive R " + quantiles(naive_r(c) for c in allc),
              "- anchor capture " + quantiles(capture(c, c["refs"]["roll"]["foresight"]["p_roll"]) for c in allc),
              "- naive capture " + quantiles(capture(c, c["refs"]["p_naive"]) for c in allc), ""]
    lines += ["## Data", "", f"- RT SPPs (NP6-785-ER, report 13061): {json.dumps(rt_stats)}.",
              f"- Within-date dedup on DA and RT dropped {dedup_stats['dropped']}: {dedup_stats['by_point']}.",
              f"- Showcase days and ±{SHOWCASE_PAD} days are out of every split: {json.dumps(SHOWCASE)}.",
              f"- Timing: {json.dumps(timing)}.", ""]
    (out / "live-stats.md").write_text("\n".join(lines) + "\n")


def build(args):
    t0 = time.time()
    raw, out = Path(args.raw), Path(args.out)
    rt, rt_stats = load_rt(raw / "ercot-rt", Path(args.cache), args.workers)
    dam, _ = v1.load_dam(raw / "ercot", ROOT / "cache" / "parsed", args.workers)
    log(f"{len(rt)} RT and {len(dam)} DA point-days at {time.time() - t0:.0f}s")
    ERCOT_EVAL_DAYS.update(d for d in sorted({k[0] for k in rt if k[0].startswith(EVAL_YEAR)}) if ercot_notice_day(d))
    log(f"{len(ERCOT_EVAL_DAYS)} {EVAL_YEAR} ERCOT notice days join the eval dates")
    keys = sorted(k for k in rt if k in dam and split(k[0]) is not None)
    keys, dedup_stats = dedup(keys, dam, rt)
    table = json.loads((ROOT / "data" / "ercot-dam-v1-train" / "manifest.json").read_text())["letters"]
    split_of = {k: split(k[0]) for k in keys}
    cands = [make_candidate(k, dam, rt, table, salt=f"live{i}") for k in keys if split_of[k] != "showcase"
             for i in range(SALTS[split_of[k]])]
    cands = list({c["task_id"]: c for c in cands}.values())
    if args.limit:
        cands = sorted(cands, key=lambda c: stable_seed("lim|" + c["task_id"]))[:args.limit]
    log(f"{len(cands)} candidates; foresight references on {args.workers} workers")
    t1 = time.time()
    with mp.Pool(args.workers) as pool:
        cands = pool.map(_foresight_worker, cands, chunksize=32)
    timing = {"foresight_refs_ms_per_task": round(1000 * (time.time() - t1) * args.workers / max(len(cands), 1), 2)}
    log(f"foresight refs at {time.time() - t0:.0f}s ({timing})")
    for c in cands:
        c["_split"] = split_of[(c["date"], c["settlement_point"])]
    chosen, tuning = tune(cands)
    log(f"filter {chosen}")
    filt, sel = {}, {}
    for sp in ("train", "eval", "test", "rtcb"):
        pool = [c for c in cands if c["_split"] == sp]
        ok = [c for c in pool if eligible(c["eligibility"], chosen, c["_kind"] == "notice")]
        e, f = [c["eligibility"] for c in pool], chosen
        kinds = collections.Counter(c["_kind"] for c in pool)
        okk = collections.Counter(c["_kind"] for c in ok)
        strict = sum(eligible(c["eligibility"], chosen) for c in pool if c["_kind"] == "notice")
        filt[sp] = {"candidates": len(pool), "eligible": len(ok),
                    "eligible_share": round(len(ok) / max(len(pool), 1), 4),
                    "by_kind": {k: [kinds[k], okk[k]] for k in ("notice", "quiet", "unknown")},
                    "notice_eligible_without_exemption": strict,
                    "fail_divergence": sum(x["divergence_usd_per_mw"] < f["divergence_usd_per_mw"] for x in e),
                    "fail_headroom": sum(x["hind_headroom_usd_per_mw"] < f["hind_headroom_usd_per_mw"] for x in e),
                    "fail_share": sum((x["roll_minus_naive_share"] or -1) < f["roll_minus_naive_share"] for x in e),
                    "fail_usd": sum(x["roll_minus_naive_usd_per_mw"] < f["roll_minus_naive_usd_per_mw"] for x in e)}
        if sp in NOTICE_SHARE:
            notice = select([c for c in ok if c["_kind"] == "notice"], round(NOTICE_SHARE[sp] * TARGETS[sp]), sp + "|n")
            rest = [c for c in ok if c["_kind"] == ("quiet" if sp == "eval" else c["_kind"]) and c["_kind"] != "notice"]
            sel[sp] = notice + select(rest, TARGETS[sp] - len(notice), sp + "|q")
            if sp == "eval" and len(sel[sp]) < TARGETS[sp]:
                sel[sp] += select([c for c in ok if c["_kind"] == "unknown"], TARGETS[sp] - len(sel[sp]), "eval|u")
        else:
            sel[sp] = select(ok, TARGETS[sp], sp)
        filt[sp]["kept"] = len(sel[sp])
        filt[sp]["kept_by_kind"] = dict(collections.Counter(c["_kind"] for c in sel[sp]))
        filt[sp]["point_days"] = len({(t["date"], t["settlement_point"]) for t in sel[sp]})
    show = []
    for name, d in SHOWCASE.items():
        for p in POINTS:
            if (d, p) in rt and (d, p) in dam:
                c = make_candidate((d, p), dam, rt, table, ep=2)
                c["_showcase"] = name
                show.append(c)
    chosen_tasks = [t for sp in sel for t in sel[sp]] + show
    log(f"{len(chosen_tasks)} selected; every tier's anchor and the LP bound")
    t1 = time.time()
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())
    with mp.Pool(args.workers, initializer=_init_worker, initargs=(ridge,)) as pool:
        done = pool.map(_full_worker, chosen_tasks, chunksize=8)
    timing["all_tier_refs_ms_per_task"] = round(1000 * (time.time() - t1) * args.workers / max(len(done), 1), 2)
    by_id = {t["task_id"]: t for t in done}
    packs = {sp: [finalize(by_id[t["task_id"]], sp) for t in sorted(sel[sp], key=lambda t: (t["date"], t["task_id"]))]
             for sp in sel}
    packs["showcase"] = [finalize(by_id[t["task_id"]], "showcase", t["_showcase"])
                         for t in sorted(show, key=lambda t: (t["date"], POINTS.index(t["settlement_point"])))]
    bundles = {}
    for name in SHOWCASE:
        day = [t for t in packs["showcase"] if t["tags"]["showcase"] == name]
        if day:
            bundles[name] = max(day, key=lambda t: (t["eligibility"]["divergence_usd_per_mw"], t["task_id"]))["task_id"]
    fx = fixtures(packs)
    with mp.Pool(args.workers, initializer=_init_worker, initargs=(ridge,)) as pool:
        fx[-2:] = pool.map(_full_worker, fx[-2:])
    packs["fixtures"] = [finalize(t, "fixtures", t["tags"]["showcase"] if "tags" in t else None) for t in fx]
    sources = {p.name: sha256(p) for p in sorted((raw / "ercot-rt").glob("RTMLZHBSPP_*.zip"))}
    sources.update({p.name: sha256(p) for p in sorted((raw / "ercot").glob("DAMLZHBSPP_*.zip"))})
    cmd = "python scripts/build_live_pack.py " + " ".join(sys.argv[1:])
    meta = {"sources": sources, "filter": chosen, "filter_spec": FILTER, "per_split": filt,
            "holdouts": {"train": TRAIN, "eval": f"every third {EVAL_YEAR} date ((d - 2024-01-01) % 3 == 1) and every "
                                                 f"{EVAL_YEAR} ERCOT notice day", "eval_ercot_notice_days":
                         sorted(ERCOT_EVAL_DAYS),
                         "test": TEST, "rtcb": RTCB, "showcase": SHOWCASE, "showcase_pad_days": SHOWCASE_PAD},
            "notices": {"archive": "data/notices (lane N)", "payload": "summary, ids, times, levels (V2-D4)",
                        "nws_kept": sorted(f"{a}.{b}" for a, b in NWS_KEEP), "notice_days_exempt": NOTICE_DAYS_EXEMPT,
                        "notice_share_targets": NOTICE_SHARE},
            "build_command": cmd.strip(), "bundles": bundles,
            "hero": HERO}
    for name, tasks in packs.items():
        write_pack(out, name, tasks, meta)
    slim = [{"task_id": c["task_id"], "_split": c["_split"], "_kind": c["_kind"], "eligibility": c["eligibility"],
             "refs": {k: c["refs"][k] for k in ("p_idle", "p_naive", "p_hind")} | {"roll": {"foresight": {
                 "p_roll": c["refs"]["roll"]["foresight"]["p_roll"]}}}} for c in cands]
    with gzip.open(Path(args.cache) / "stats-input.json.gz", "wt") as f:
        json.dump({"cands": slim, "chosen": chosen, "tuning": tuning, "filt": filt, "rt_stats": rt_stats,
                   "dedup_stats": dedup_stats, "timing": timing}, f)
    write_stats(out, packs, cands, chosen, tuning, filt, rt_stats, dedup_stats, timing)
    log(f"done in {time.time() - t0:.0f}s: " + ", ".join(f"{PACKS[k]} {len(v)}" for k, v in packs.items()))


def merge_notices(args):
    """Re-attach the archive's notices (gridsim_core.notices at --merge-notices, a data/notices directory) to every
    built live pack and recompute refs, eligibility and tags of the tasks whose notices changed (filters not re-run)."""
    root = str(Path(args.merge_notices))
    archive.load.cache_clear()
    archive._by_day.cache_clear()
    out = Path(args.out)
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())
    for name in ("train", "eval", "test", "rtcb", "showcase", "fixtures"):
        d = out / PACKS[name]
        if not (d / "tasks.jsonl.gz").exists():
            continue
        with gzip.open(d / "tasks.jsonl.gz", "rt") as f:
            tasks = [json.loads(line) for line in f]
        changed = []
        for t in tasks:
            if t["task_id"].endswith(("-notice", "-derate")):
                continue
            ns = day_notices(t["date"], t["settlement_point"], root)
            _DAY[(t["date"], t["settlement_point"])] = (ns, day_kind(t["date"], t["settlement_point"], root))
            if live.notices_sha(ns) != t["notices_sha"]:
                t["notices"], t["notices_sha"] = ns, live.notices_sha(ns)
                changed.append(t)
        with mp.Pool(args.workers, initializer=_init_worker, initargs=(ridge,)) as pool:
            redone = {t["task_id"]: t for t in pool.map(_full_worker, changed, chunksize=8)}
        tasks = [finalize(redone.get(t["task_id"], t), name, t["tags"]["showcase"]) for t in tasks]
        meta = json.loads((d / "manifest.json").read_text())
        keep = ("sources", "filter", "filter_spec", "per_split", "holdouts", "build_command", "bundles", "hero")
        meta = {k: v for k, v in meta.items() if k in keep + ("notices",)}
        meta["notices"] = dict(meta.get("notices") or {}, merged_from=root, tasks_changed=len(changed))
        write_pack(out, name, tasks, meta)
        log(f"{PACKS[name]}: {len(changed)} tasks got new notices")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=str(ROOT / "cache" / "raw"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--cache", default=str(ROOT / "build" / "live-cache"))
    ap.add_argument("--workers", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    ap.add_argument("--limit", type=int, default=0, help="candidates to keep (a quick dry run)")
    ap.add_argument("--parse-only", action="store_true")
    ap.add_argument("--stats-only", action="store_true", help="rewrite live-stats.md from the packs and the last build")
    ap.add_argument("--merge-notices", default=None, help="a notices archive directory (data/notices) to re-attach")
    args = ap.parse_args()
    if args.merge_notices:
        return merge_notices(args)
    if args.stats_only:
        with gzip.open(Path(args.cache) / "stats-input.json.gz", "rt") as f:
            st = json.load(f)
        packs = {k: [json.loads(line) for line in gzip.open(Path(args.out) / v / "tasks.jsonl.gz", "rt")]
                 for k, v in PACKS.items()}
        return write_stats(Path(args.out), packs, st["cands"], st["chosen"], st["tuning"], st["filt"], st["rt_stats"],
                           st["dedup_stats"], st["timing"])
    if args.parse_only:
        rt, st = load_rt(Path(args.raw) / "ercot-rt", Path(args.cache), args.workers)
        return log(f"{len(rt)} RT point-days: {st}")
    build(args)


if __name__ == "__main__":
    main()
