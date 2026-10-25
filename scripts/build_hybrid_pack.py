"""Build the v3 hybrid packs (ercot-hybrid-v3-train/-eval/-rtcb/-showcase, data/fixtures-hybrid) from v1's DAM and v2's
RT caches, lane D3's hybrid inputs (data/hybrid/) and lane N's notices, with gridsim_core.hybrid references, and write
data/hybrid-stats.md. Sites are lane D3's EIA-860 archetypes placed at hubs and load zones, labelled `archetype`."""

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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_live_pack as v2  # noqa: E402
import build_pack as v1  # noqa: E402

from gridsim_core import hybrid as H  # noqa: E402
from gridsim_core import hybrid_inputs as HI  # noqa: E402
from gridsim_core.contract import as_era  # noqa: E402
from gridsim_core.task import stable_seed  # noqa: E402

POINTS = [p for p in v1.POINTS if p not in ("HB_HUBAVG", "HB_BUSAVG")]
SHOWCASE = {"sept06-2023": ("2023-09-06", "HB_WEST"), "aug10-2023": ("2023-08-10", "HB_NORTH"),
            "mar29-2024": ("2024-03-29", "HB_WEST"), "fern-0126-2026": ("2026-01-26", "HB_NORTH")}
HERO = "sept06-2023"
URI = ("2021-02-10", "2021-02-22")
PAD = 3
TRAIN = ("2021-01-01", "2024-12-31")
EVAL = ("2025-01-01", "2025-11-30")
RTCB = ("2025-12-05", "2026-09-30")
TARGETS = {"train": 2400, "eval": 300, "rtcb": 200}
PACKS = {"train": "ercot-hybrid-v3-train", "eval": "ercot-hybrid-v3-eval", "rtcb": "ercot-hybrid-v3-rtcb",
         "showcase": "ercot-hybrid-v3-showcase"}
DRAWS = {"train": 3, "eval": 4, "rtcb": 2}
DEFAULT_SHARE, POI_VARIANT_SHARE, OVERSIZE_SHARE = 0.4, 0.2, 0.4
OVERSIZE = (1.11, 1.25, 1.4)
C_DEG = (0.0, 2.0, 4.0, 6.0, 8.0)
FILTER = {"min_headroom_usd": 500.0, "low_spread_usd_per_mw": 22.0, "sponge_reward_max": 0.97,
          "baseline_reward_max": 0.97}
RTCB_ADAPT = 60


def log(msg: str):
    print(f"[build_hybrid_pack] {msg}", flush=True)


def near(d: str, day: str, pad: int = PAD) -> bool:
    return abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(day)).days) <= pad


def split(d: str) -> str | None:
    if d in {x for x, _ in SHOWCASE.values()}:
        return "showcase"
    if any(near(d, x) for x, _ in SHOWCASE.values()) or URI[0] <= d <= URI[1] or near(d, URI[0]) or near(d, URI[1]):
        return None
    for sp, (a, b) in (("train", TRAIN), ("eval", EVAL), ("rtcb", RTCB)):
        if a <= d <= b:
            return sp
    return None


def pick_site(d: str, p: str, salt: str, arch: dict) -> dict:
    """The default archetype (the v3 plan's) or a weighted draw from lane D3's EIA-860 grid; POI at PV AC, its 1.2x
    variant, or below PV AC by one of OVERSIZE (PV AC / POI) so the meter clips; degradation $0-8/MWh by draw."""
    h = stable_seed(f"site|{salt}|{d}|{p}")
    u = (h % 10007) / 10007
    if u < DEFAULT_SHARE:
        a = arch["default"]
    else:
        w = np.array([x["weight"] for x in arch["archetypes"]])
        a = arch["archetypes"][int(np.searchsorted(np.cumsum(w / w.sum()), (h // 10007 % 9973) / 9973))]
    v = (h // 7 % 1000) / 1000
    poi = (a["poi_variants_mw"][-1] if v < POI_VARIANT_SHARE else
           round(a["pv_mwac"] / OVERSIZE[h // 31 % len(OVERSIZE)]) if v < POI_VARIANT_SHARE + OVERSIZE_SHARE else
           a["poi_mw"])
    c_deg = 4.0 if a is arch["default"] else C_DEG[h // 13 % len(C_DEG)]
    return H.site_from_archetype(a, poi, c_deg=c_deg)


def deployments(d: str) -> list[dict]:
    """Lane D3's events as Session deployments: frac 1.0 of the award for min(window, duration) (C3-D14)."""
    out = []
    for e in HI.deployments(d):
        name = H.NAMES[e["product"]] + (f" ({e['variant']})" if e.get("variant") else "")
        out.append({"event_id": e["event_id"], "issued_at": e["start"], "product": e["product"], "frac": 1.0,
                    "start": e["start"], "end": e["end"], "name": "ERCOT", "title": f"{name} deployed",
                    "level": None})
    return out


def make_candidate(d: str, p: str, salt: str, dam: dict, rt: dict, arch: dict,
                   default: bool = False) -> dict | None:
    asp, cf = HI.as_prices(d), HI.solar_cf(d)
    if asp is None or cf is None or asp["n_hours"] != 24 or len(cf) != 24:
        return None
    site = H.site_from_archetype(arch["default"], c_deg=4.0) if default else pick_site(d, p, salt, arch)
    mcpc = {k: asp[k] for k in H.PRODUCTS if asp.get(k) is not None}
    rth = rt[(d, p)].reshape(24, 4).mean(axis=1)
    t = H.make_task(d, p, site, np.round(dam[(d, p)], 2), np.round(rth, 4), cf, mcpc, None,
                    notices=v2.day_notices(d, p), deployments=deployments(d))
    t["flags"] |= {"pv_scope": "system", "deploy_frac": "1.0 assumed (stress case)",
                   "pv_shape": "ILR x fleet-AC cf (approximate)"}
    if as_era(d) == "C":
        t["flags"]["rt_as"] = "not_modelled"
    return t


def _refs(t: dict) -> dict:
    t0 = time.perf_counter()
    try:
        t["refs"] = H.references(t)
    except RuntimeError as e:
        t["_error"] = str(e)
    t["_ms"] = 1000 * (time.perf_counter() - t0)
    return t


def score(t: dict) -> dict:
    """Eligibility numbers: headroom over idle per tier, per MW, and the sponge's reward."""
    r, p = t["refs"], t["site"]["bess"]["p_mw"]
    e, s = r["energy"], r["reserves"]
    return {"headroom_energy_usd": e["p_anchor"] - r["p_idle"], "headroom_reserves_usd": s["p_anchor"] - r["p_idle"],
            "spread_usd_per_mw": (e["p_anchor"] - r["p_idle"]) / p,
            "sponge_reward": max(e["baselines"]["sponge"]["reward"], s["baselines"]["sponge"]["reward"]),
            "best_baseline_reward": max([b["reward"] for b in s["baselines"].values()]
                                        + [H.reward_value(e["p_anchor"], r["p_idle"], s["p_anchor"])]),
            "as_value_usd": s["oneshot"]["p_milp"] - e["oneshot"]["p_milp"],
            "as_value_realized_usd": s["p_anchor"] - e["p_anchor"]}


def eligible(t: dict, f: dict = FILTER) -> bool:
    x = t["_score"]
    return (x["headroom_reserves_usd"] >= f["min_headroom_usd"] and x["headroom_energy_usd"] >= f["min_headroom_usd"]
            and x["spread_usd_per_mw"] >= f["low_spread_usd_per_mw"] and x["sponge_reward"] < f["sponge_reward_max"]
            and x["best_baseline_reward"] < f["baseline_reward_max"])


def filter_counts(pool: list) -> dict:
    f = FILTER
    return {"candidates": len(pool),
            "fail_headroom": sum(min(c["_score"]["headroom_energy_usd"], c["_score"]["headroom_reserves_usd"])
                                 < f["min_headroom_usd"] for c in pool),
            "fail_spread": sum(c["_score"]["spread_usd_per_mw"] < f["low_spread_usd_per_mw"] for c in pool),
            "fail_sponge": sum(c["_score"]["sponge_reward"] >= f["sponge_reward_max"] for c in pool),
            "fail_baseline": sum(c["_score"]["best_baseline_reward"] >= f["baseline_reward_max"] for c in pool),
            "eligible": sum(eligible(c) for c in pool)}


def tags(t: dict, showcase: str | None = None) -> dict:
    s = H.Session(t, "reserves", reference=True)
    st = H.site_of(t)
    m = int(t["date"][5:7])
    return {"watches": len(s.watches), "short_ok": len(s.watches) <= 5,
            "notice_day": bool(t["notices"]), "deploy_day": bool(t["deployments"]),
            "season": "winter" if m in (12, 1, 2) else "spring" if m <= 5 else "summer" if m <= 9 else "fall",
            "as_value_usd": round(t["_score"]["as_value_usd"], 2) if "_score" in t else None, "as_stratum": None,
            "clip_mwh": round(sum(max(0.0, x - st.meter) for x in t["pv_mw"]), 3),
            "neg_hours": int(sum(x < 0 for x in t["prices"])), "showcase": showcase}


def select(ok: list, n: int, salt: str) -> list:
    """Round-robin over dates (one task per date per round), dates and draws in a stable shuffled order."""
    by_date = collections.defaultdict(list)
    for t in sorted(ok, key=lambda t: stable_seed(f"{salt}|{t['task_id']}")):
        by_date[t["date"]].append(t)
    dates = sorted(by_date, key=lambda d: stable_seed(f"{salt}|{d}"))
    out, k = [], 0
    while len(out) < n and any(len(v) > k for v in by_date.values()):
        out += [by_date[d][k] for d in dates if len(by_date[d]) > k][:n - len(out)]
        k += 1
    return out


def finalize(t: dict, sp: str, showcase: str | None = None) -> dict:
    t = dict(t)
    t["pack"], t["split"] = PACKS.get(sp, "fixtures-hybrid"), sp
    t["events_sha"] = t["refs"]["events_sha"]
    t["tags"] = tags(t, showcase) | ({"as_stratum": t["_stratum"]} if t.get("_stratum") else {})
    if sp == "rtcb":
        t["tags"]["rtcb_role"] = t.get("_role")
    return {k: v for k, v in t.items() if not k.startswith("_")}


def write_pack(out: Path, name: str, tasks: list, meta: dict):
    d = out / name
    d.mkdir(parents=True, exist_ok=True)
    with gzip.open(d / "tasks.jsonl.gz", "wt") as f:
        for t in tasks:
            f.write(json.dumps(t, separators=(",", ":")) + "\n")
    eras = collections.Counter(t["era"] for t in tasks)
    (d / "manifest.json").write_text(json.dumps({
        "pack": name, "hybrid_version": H.HYBRID_VERSION, "tasks": len(tasks), "eras": dict(sorted(eras.items())),
        "dates": [min(t["date"] for t in tasks), max(t["date"] for t in tasks)] if tasks else None,
        "tiers": ["energy", "reserves"], "filters": FILTER,
        "flags": {"site": "archetype (no crosswalk tonight; V3-D11)", "pv_availability": "proxy, system-wide cf",
                  "reg_drift": "ERCOT storage fleet deployment from 2023-10-12, modelled before "
                               "(hybrid_inputs.reg_hourly; V3-D8)",
                  "deploy_frac": "1.0 assumed (C3-D14)",
                  "poi": f"PV AC, its 1.2x variant, or PV AC / {', '.join(map(str, OVERSIZE))} (V3-D7, V3-D12)",
                  "coupling": "ac only (C3-D15)",
                  "rt_as": "not modelled (T3 dropped, V3-D10)"},
        "licence": "ERCOT data with attribution and no endorsement; EIA public domain"} | meta, indent=1) + "\n")


def mean(xs) -> float | None:
    xs = [x for x in xs if x is not None]
    return round(float(np.mean(xs)), 4) if xs else None


def pack_stats(tasks: list) -> dict:
    out = {}
    for tier in ("energy", "reserves"):
        rows = [t["refs"][tier] for t in tasks]
        bl = {k: mean(r["baselines"][k]["reward"] for r in rows if k in r["baselines"])
              for k in ("sponge", "v2_energy", "as_hog")}
        out[tier] = {"n": len(rows), "anchor_minus_idle_usd": mean(r["p_anchor"] - t["refs"]["p_idle"]
                                                                   for r, t in zip(rows, tasks, strict=True)),
                     "capture_anchor_vs_hind": mean((r["p_anchor"] - t["refs"]["p_idle"]) /
                                                    (r["p_hind"] - t["refs"]["p_idle"])
                                                    for r, t in zip(rows, tasks, strict=True)
                                                    if r["p_hind"] - t["refs"]["p_idle"] > 1e-6),
                     "oneshot_milp_over_idle_usd": mean(r["oneshot"]["p_milp"] - r["oneshot"]["p_idle"] for r in rows),
                     "baseline_reward_mean": bl,
                     "energy_only_reward_mean": mean(H.reward_value(r["p_energy_only"], t["refs"]["p_idle"],
                                                                    r["p_anchor"])
                                                     for r, t in zip(rows, tasks, strict=True)
                                                     if r.get("p_energy_only") is not None),
                     "anchor_governor_hours_mean": mean(r["anchor"]["governor_hours"] for r in rows),
                     "anchor_soft_share": mean(r["anchor"]["soft_solves"] / max(1, r["anchor"]["watches"])
                                               for r in rows),
                     "anchor_repaired_mean": mean(r["anchor"]["repaired_entries"] for r in rows),
                     "clip_mwh_total": round(sum(t["tags"]["clip_mwh"] for t in tasks), 3),
                     "anchor_ftp_usd_mean": mean(r["anchor"]["ftp_usd"] for r in rows),
                     "anchor_as_usd_mean": mean(r["anchor"]["as_usd"] for r in rows)}
    return out


def write_stats(out: Path, packs: dict, cands: dict, filt: dict, timing: dict, args, kept: bool = False):
    lines = ["# v3 hybrid packs: counts, filters and baselines", "",
             f"Built by `scripts/build_hybrid_pack.py` ({dt.date.today().isoformat()}"
             f"{'; references rebuilt in place with --refs-only' if kept else ''}). References: "
             "`gridsim_core.hybrid.references` (rolling MILP anchor, HiGHS; hindsight + LP bound; oneshot optimum; "
             "baselines played through the Session). Rewards use the contract's R = clip(0.2 + 0.8 (P - P_idle) / "
             "(P_anchor - P_idle), 0, 1), so idle is 0.2 and the anchor 1.0 by construction.", "",
             "## Packs", "", "| Pack | Tasks | Eras | Dates | Notice days | Deploy days | Short (<=5 watches) |",
             "|---|---|---|---|---|---|---|"]
    for name, ts in packs.items():
        eras = collections.Counter(t["era"] for t in ts)
        lines.append(f"| `{name}` | {len(ts)} | {', '.join(f'{k} {v}' for k, v in sorted(eras.items()))} | "
                     f"{min(t['date'] for t in ts)}..{max(t['date'] for t in ts)} | "
                     f"{sum(t['tags']['notice_day'] for t in ts)} | {sum(t['tags']['deploy_day'] for t in ts)} | "
                     f"{sum(t['tags']['short_ok'] for t in ts)} |")
    lines += ["", "## Filters (the v3 plan)", "",
              f"Thresholds: P_anchor - P_idle >= ${FILTER['min_headroom_usd']:.0f} in both tiers; v1's low-spread drop "
              f"(energy-tier anchor - idle >= ${FILTER['low_spread_usd_per_mw']:.0f} per MW of battery); sponge reward "
              f"< {FILTER['sponge_reward_max']} (the sponge within 3% of the anchor); and, extending that rule "
              f"(C3-D16), every reserves-tier baseline (sponge, AS-hog, v2 energy-only) and the energy-only MILP below "
              f"{FILTER['baseline_reward_max']} against the reserves anchor. Uri and every showcase day +/-3 days are "
              "out of every split; DST days and days without 24 hourly inputs are dropped.", "",
              *(["The days are the rules-3.1 build's, kept as they were; under the rules-3.2 references (C3-D19, "
                 "C3-D20) the table counts how many of them each filter would now drop.", ""] if kept else []),
              "| Split | Candidates | Fail headroom | Fail low spread | Fail sponge | Fail baseline >= 0.97 | Eligible "
              "| Kept |",
              "|---|---|---|---|---|---|---|---|"]
    for sp, f in filt.items():
        lines.append(f"| {sp} | {f['candidates']} | {f['fail_headroom']} | {f['fail_spread']} | {f['fail_sponge']} | "
                     f"{f['fail_baseline']} | {f['eligible']} | {f['kept']} |")
    lines += ["", "## Baselines and references (means over each pack)", "",
              "| Pack | Tier | Anchor - idle ($) | Anchor / hindsight capture | Sponge | v2 energy-only (blind) | "
              "AS-hog | Energy-only MILP | Anchor AS revenue ($) | Anchor governor hours | Anchor soft solves "
              "(share of watches) | Anchor entries repaired |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, ts in packs.items():
        st = pack_stats(ts)
        for tier in ("energy", "reserves"):
            x = st[tier]
            b = x["baseline_reward_mean"]
            lines.append(f"| `{name}` | {tier} | {x['anchor_minus_idle_usd']} | {x['capture_anchor_vs_hind']} | "
                         f"{b['sponge']} | {b['v2_energy']} | {b['as_hog'] if b['as_hog'] is not None else '-'} | "
                         f"{x['energy_only_reward_mean'] if x['energy_only_reward_mean'] is not None else '-'} | "
                         f"{x['anchor_as_usd_mean']} | {x['anchor_governor_hours_mean']} | {x['anchor_soft_share']} | "
                         f"{x['anchor_repaired_mean']} |")
    lines += ["", "## Energy tier by POI (PV AC / POI): the solar sponge and v2 energy-only against the energy anchor",
              "", "| Pack | POI | Tasks | Clippable MWh/day | Sponge | v2 energy-only | Anchor - idle ($) |",
              "|---|---|---|---|---|---|---|"]
    for name, ts in packs.items():
        for cls in ("at or above PV AC", "oversized"):
            part = [t for t in ts if str(t["site"]["flags"].get("poi")).startswith("oversized") == (cls == "oversized")]
            if not part:
                continue
            e = [t["refs"]["energy"] for t in part]
            lines.append(f"| `{name}` | {cls} | {len(part)} | {mean(t['tags']['clip_mwh'] for t in part)} | "
                         f"{mean(r['baselines']['sponge']['reward'] for r in e)} | "
                         f"{mean(r['baselines']['v2_energy']['reward'] for r in e)} | "
                         f"{mean(r['p_anchor'] - t['refs']['p_idle'] for r, t in zip(e, part, strict=True))} |")
    lines += ["", "## Regulation drift source (V3-D8)", "", "| Pack | ercot | ercot+modelled | modelled |",
              "|---|---|---|---|"]
    for name, ts in packs.items():
        c = collections.Counter(t["reg"]["source"] for t in ts)
        lines.append(f"| `{name}` | {c['ercot']} | {c['ercot+modelled']} | {c['modelled']} |")
    ev = packs.get(PACKS["eval"], [])
    if ev:
        lines += ["", "## Eval strata (by AS value at DA: the reserves-tier oneshot optimum minus the energy-tier one, "
                  "so drift noise does not move a day between strata)", "",
                  "| Stratum | Tasks | AS value range ($) | Reserves-tier AS-hog | Energy-only MILP |",
                  "|---|---|---|---|---|"]
        for s in ("low", "mid", "high"):
            ts = [t for t in ev if t["tags"]["as_stratum"] == s]
            if not ts:
                continue
            v = [t["tags"]["as_value_usd"] for t in ts]
            st = pack_stats(ts)["reserves"]
            lines.append(f"| {s} | {len(ts)} | {min(v):.0f}..{max(v):.0f} | {st['baseline_reward_mean']['as_hog']} | "
                         f"{st['energy_only_reward_mean']} |")
    lines += ["", "## Timing", "", f"- references: {timing['refs_ms_per_task']} ms per task-core (both tiers; about 15 "
              "MILP solves, 2 hindsight MILPs and 2 LPs per task)",
              f"- MILP solve (watch 0, 24 open hours): median {timing['solve_ms_median']} ms, p95 "
              f"{timing['solve_ms_p95']} ms over {timing['solve_n']} solves",
              f"- build wall time {timing['wall_s']} s on {args.workers} workers", "",
              "## Flags", "", "- Sites are archetypes at hubs and load zones (no crosswalk, V3-D11): 40% the v3 "
              "plan's default (PV 150 MWac / 195 MWdc, BESS 100 MW / 200 MWh), 60% lane D3's EIA-860 grid by weight; "
              f"POI = PV AC, {POI_VARIANT_SHARE:.0%} at the 1.2x variant and {OVERSIZE_SHARE:.0%} below PV AC "
              f"(PV AC / POI one of {', '.join(map(str, OVERSIZE))}; V3-D12); AC coupling only (C3-D15).",
              "- PV is the system-wide availability cf (lane D3) for every region, ILR x cf clipped at PV AC (proxy).",
              "- Oversized sites clip at the meter (clippable MWh, every pack: "
              + ", ".join(f"{n} {round(sum(t['tags']['clip_mwh'] for t in ts))}" for n, ts in packs.items())
              + "), so the energy tier tests charging from clipped solar and the sponge is no longer idle.",
              "- Anchor soft solves: after watch 0 the reserves tier keeps the DA awards, and realized drift can leave "
              "an hour whose awards no move can back; the hard MILP is then infeasible, the soft one minimises the "
              "shortfall, and the repair walk turns the entries the Session refuses into the governor's move (C3-D17), "
              "so the anchor's commits are never refused. A hard solution is never repaired (tested).",
              "- Regulation drift is ERCOT's storage fleet deployment (60-Day SCED Disclosure) on days it covers "
              "(from 2023-10-12) and the imbalance-driven fallback before (data/hybrid/reg_deploy.md); deployments use "
              "frac 1.0 (stress case).",
              "- Era C days (rtcb pack) are played as T2 with DA AS only; RT AS (T3) is not modelled tonight.", ""]
    (out / "hybrid-stats.md").write_text("\n".join(lines))


def solve_times(tasks: list, n: int = 60) -> list[float]:
    out = []
    for t in tasks[:n]:
        st, day = H.site_of(t), H.day_of(t, "reserves")
        t0 = time.perf_counter()
        H.solve_day(st, day, 0, st.s0, 0.0, products=day.offered)
        out.append(1000 * (time.perf_counter() - t0))
    return out


def fixtures(packs: dict) -> list:
    """20 CI tasks: the hero, a negative-price day, deployment and notice days, every era, POI variants, small sites."""
    pool = [t for ts in packs.values() for t in ts]
    picks, seen = [], set()

    def take(pred, k=1):
        for t in sorted(pool, key=lambda t: stable_seed("fx|" + t["task_id"])):
            if len([x for x in picks if pred(x)]) >= k:
                return
            if pred(t) and t["task_id"] not in seen:
                picks.append(t)
                seen.add(t["task_id"])

    take(lambda t: t["tags"]["showcase"] == HERO)
    take(lambda t: t["tags"]["showcase"] == "mar29-2024")
    take(lambda t: t["era"] == "A", 4)
    take(lambda t: t["era"] == "B" and t["tags"]["deploy_day"], 3)
    take(lambda t: t["era"] == "C", 3)
    take(lambda t: t["tags"]["neg_hours"] >= 3, 2)
    take(lambda t: t["site"]["flags"].get("poi") == "1.2x", 2)
    take(lambda t: str(t["site"]["flags"].get("poi")).startswith("oversized"), 3)
    take(lambda t: t["site"]["bess"]["p_mw"] <= 75, 2)
    take(lambda t: t["tags"]["short_ok"], 1)
    take(lambda t: True, 20)
    return [t | {"pack": "fixtures-hybrid", "split": "fixtures", "source_pack": t["pack"]} for t in picks[:20]]


def build(args):
    t0 = time.time()
    raw, out = Path(args.raw), Path(args.out)
    rt, _ = v2.load_rt(raw / "ercot-rt", Path(args.cache), args.workers)
    dam, _ = v1.load_dam(raw / "ercot", Path(args.cache), args.workers)
    arch = HI.archetypes()
    log(f"{len(rt)} RT and {len(dam)} DA point-days at {time.time() - t0:.0f}s")
    dates = sorted({d for d, p in dam if p in POINTS and (d, p) in rt and split(d) is not None})
    cands = []
    for d in dates:
        sp = split(d)
        if sp == "showcase":
            continue
        pts = sorted((p for p in POINTS if (d, p) in dam and (d, p) in rt), key=lambda p: stable_seed(f"pt|{d}|{p}"))
        for i in range(min(DRAWS[sp], len(pts))):
            if (c := make_candidate(d, pts[i], f"v3{i}", dam, rt, arch)) is not None:
                c["_split"] = sp
                cands.append(c)
    shows = {}
    for name, (d, p) in SHOWCASE.items():
        if (d, p) in dam and (d, p) in rt and (c := make_candidate(d, p, "show", dam, rt, arch, default=True)):
            c["flags"]["display_only"] = True
            c["_split"] = "showcase"
            shows[name] = c
    if args.limit:
        cands = sorted(cands, key=lambda c: stable_seed("lim|" + c["task_id"]))[:args.limit]
    log(f"{len(cands)} candidates and {len(shows)} showcase days; references on {args.workers} workers")
    with mp.Pool(args.workers) as pool:
        cands = pool.map(_refs, cands + list(shows.values()), chunksize=8)
    errors = [c for c in cands if "_error" in c]
    for c in errors:
        log(f"references failed on {c['task_id']}: {c['_error']}")
    cands = [c for c in cands if "_error" not in c]
    shows = {name: next(c for c in cands if c["task_id"] == s["task_id"]) for name, s in shows.items()}
    cands = [c for c in cands if c["_split"] != "showcase"]
    ms = [c["_ms"] for c in cands]
    log(f"references at {time.time() - t0:.0f}s ({np.mean(ms):.0f} ms per task-core)")
    for c in cands:
        c["_score"] = score(c)
    filt, packs = {}, {}
    for sp in ("train", "eval", "rtcb"):
        pool = [c for c in cands if c["_split"] == sp]
        ok = [c for c in pool if eligible(c)]
        filt[sp] = filter_counts(pool)
        if sp == "eval":
            v = sorted(c["_score"]["as_value_usd"] for c in ok)
            q1, q2 = (v[len(v) // 3], v[2 * len(v) // 3]) if v else (0, 0)
            sel = []
            for s, lo, hi in (("low", -np.inf, q1), ("mid", q1, q2), ("high", q2, np.inf)):
                part = [c | {"_stratum": s} for c in ok if lo <= c["_score"]["as_value_usd"] < hi]
                sel += select(part, TARGETS[sp] // 3, f"eval|{s}")
        else:
            sel = select(ok, TARGETS[sp], sp)
            if sp == "rtcb":
                adapt = {c["task_id"] for c in select(sel, RTCB_ADAPT, "rtcb|adapt")}
                sel = [c | {"_role": "adapt" if c["task_id"] in adapt else "eval"} for c in sel]
        filt[sp]["kept"] = len(sel)
        packs[PACKS[sp]] = [finalize(c, sp) for c in sel]
    packs[PACKS["showcase"]] = [finalize(c | {"_score": score(c)}, "showcase", name) for name, c in shows.items()]
    for name, ts in packs.items():
        write_pack(out, name, ts, {"split": ts[0]["split"] if ts else None})
        log(f"{name}: {len(ts)}")
    fx = fixtures(packs)
    write_pack(out, "fixtures-hybrid", fx, {"split": "fixtures"})
    log(f"fixtures-hybrid: {len(fx)}")
    st = solve_times(packs[PACKS["eval"]] or cands)
    timing = {"refs_ms_per_task": round(float(np.mean(ms)), 1), "solve_ms_median": round(float(np.median(st)), 1),
              "solve_ms_p95": round(float(np.percentile(st, 95)), 1), "solve_n": len(st),
              "wall_s": round(time.time() - t0)}
    write_stats(out, packs | {"fixtures-hybrid": fx}, cands, filt, timing, args)
    log(f"done at {time.time() - t0:.0f}s: {timing}")


def refs_only(args):
    """Every pack's references recomputed on the current rules, its days kept (rules 3.2, C3-D19 and C3-D20)."""
    t0 = time.time()
    out = Path(args.out)
    names = [*PACKS.values(), "fixtures-hybrid"]
    packs = {n: [json.loads(line) for line in gzip.open(out / n / "tasks.jsonl.gz", "rt")] for n in names}
    rows = list({t["task_id"]: t for ts in packs.values() for t in ts}.values())
    log(f"{len(rows)} days; references on {args.workers} workers")
    with mp.Pool(args.workers) as pool:
        done = {t["task_id"]: t for t in pool.map(_refs, [dict(t) for t in rows], chunksize=8)}
    if errors := [t for t in done.values() if "_error" in t]:
        raise SystemExit(f"references failed on {len(errors)} days: {errors[0]['task_id']}: {errors[0]['_error']}")
    ms = [t["_ms"] for t in done.values()]
    filt = {}
    for name, ts in packs.items():
        packs[name] = [t | {"hybrid_version": H.HYBRID_VERSION, "refs": done[t["task_id"]]["refs"]} for t in ts]
        write_pack(out, name, packs[name], {"split": ts[0]["split"]})
        sp = ts[0]["split"]
        if sp in TARGETS:
            filt[sp] = filter_counts([t | {"_score": score(t)} for t in packs[name]]) | {"kept": len(ts)}
        log(f"{name}: {len(ts)}")
    st = solve_times(packs[PACKS["eval"]])
    timing = {"refs_ms_per_task": round(float(np.mean(ms)), 1), "solve_ms_median": round(float(np.median(st)), 1),
              "solve_ms_p95": round(float(np.percentile(st, 95)), 1), "solve_n": len(st),
              "wall_s": round(time.time() - t0)}
    write_stats(out, packs, [], filt, timing, args, kept=True)
    log(f"done at {time.time() - t0:.0f}s: {timing}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--raw", default=str(ROOT / "cache" / "raw"))
    ap.add_argument("--cache", default=str(ROOT / "cache" / "parsed"))
    ap.add_argument("--out", default=str(ROOT / "data"))
    ap.add_argument("--workers", type=int, default=max(1, mp.cpu_count() - 2))
    ap.add_argument("--limit", type=int, default=0, help="build from this many candidates (a smoke run)")
    ap.add_argument("--refs-only", action="store_true",
                    help="recompute the references of the packs in --out in place, keeping their days")
    args = ap.parse_args()
    (refs_only if args.refs_only else build)(args)


if __name__ == "__main__":
    main()
