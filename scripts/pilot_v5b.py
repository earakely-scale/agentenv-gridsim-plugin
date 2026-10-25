"""The rules-5.1 v5 pilot's pre-registered analysis (docs/prereg/v5-pilot-b.md) from the sweeps' replay-verified Episode
JSON v5, results.jsonl and the pack rows. Each column's headline is hindsight capture C = (P - P_idle)/(BR_rt - P_idle),
unclipped, beside the anchor's C and delta = C - C_anchor with its paired CI (docs/REWARD-SCALES.md); then the compliant
score with clip(C) as its profit half (the public default) and as built (R), R with its R = 1 share, the baselines on
the same floors at the same tier on each scale, the price-taker comparisons, eps_a, A's over-offering (offered and
awarded sell MWh over its energy, clipped hours) and get_forecast refusals beside the rules-5.0 pilot's, and the rest of
pilot_v5's rows. CIs are 95% percentile bootstrap over floors (10,000 resamples, seed 0), paired for differences; the
rules-5.0 comparison is unpaired over each pilot's own floors and paired on the floors both played."""

import argparse
import gzip
import json
import random
import statistics
import subprocess
from collections import Counter
from pathlib import Path

import pilot_v5
from pilot_v5 import _ci, _counts, _f, _mean, ci, spearman
from pilot_v5b_tasks import capture, compliant

from agentenv_gridsim import market_tasks
from agentenv_gridsim.sweep import slug

RUNS = Path("results/runs")
pilot_v5.BOOT = 10_000
REFS = ("idle", "anchor", "price_taker", "max_withhold", "replay_A")
V50 = {"floor-sprint": "v5-pilot-sol-amend", "floor-day": "v5-pilot-sol-day"}
V50_PACK = "4162fda:data/gridsim-market-eval/tasks.jsonl.gz"
OFFERING = ("offered_sell_e", "awarded_sell_e", "clipped_hours")


def submitted(e: dict) -> bool:
    return any(s["tool"] == "submit_offer" and (s["output"].get("accepted") or s["output"].get("submitted"))
               for s in e["steps"])


def offering(e: dict) -> dict:
    """Seat A's final DAM offer and awards against its energy, and its get_forecast calls and refusals."""
    e_mwh, hours = e["task"]["seat_A"]["e_mwh"], e["offers"]["A"].get("hours") or []
    fc = [s for s in e["steps"] if s["tool"] == "get_forecast"]
    return {"offered_sell_e": sum(q for h in hours for q, _ in h.get("sell") or []) / e_mwh,
            "offered_buy_e": sum(q for h in hours for q, _ in h.get("buy") or []) / e_mwh,
            "awarded_sell_e": sum(max(x, 0.0) for x in e["awards"]["A"]) / e_mwh,
            "clipped_hours": sum(bool(h["clipped"]) for h in e["hours"]),
            "forecast_calls": len(fc), "forecast_refused": sum("error" in s["output"] for s in fc)}


def floor(e: dict, row: dict, task: dict) -> dict:
    f = pilot_v5.floor(e, row, task)
    refs, tier, sub = task["refs"], e["tier"], submitted(e)
    c = capture(f["profit_usd"], refs, tier) if sub else 0.0
    out = f | offering(e) | {"submitted": sub, "p_hind": refs[tier]["p_br_rt"], "c": c,
                             "anchor_c": capture(f["p_anchor"], refs, tier),
                             "compliant_c": compliant(c, f["welfare_ratio"]) if sub else 0.0}
    out["delta"] = c - out["anchor_c"]
    for k, b in f["baselines"].items():
        b |= {"capture": capture(b["profit"], refs, tier), "compliant_c": compliant(capture(b["profit"], refs, tier),
                                                                                    b["welfare_ratio"])}
        out[f"delta_{k}"] = c - b["capture"]
    return out


def summary(fs: list[dict]) -> dict:
    m = pilot_v5.summary(fs)
    if not fs:
        return m

    def col(key):
        return [f[key] for f in fs]

    calls = sum(col("forecast_calls"))
    m |= {"c": _mean(col("c")), "c_ci": ci(col("c")), "anchor_c": _mean(col("anchor_c")),
          "delta": _mean(col("delta")), "delta_ci": ci(col("delta")), "c_below_0": sum(x < 0 for x in col("c")),
          "compliant_c": _mean(col("compliant_c")), "compliant_c_ci": ci(col("compliant_c")),
          "eps_a_ci": ci(col("eps_a")),
          "price_making_gain_usd_per_mw_day_ci": ci(col("price_making_gain_usd_per_mw_day")),
          "offered_sell_e_median": statistics.median(col("offered_sell_e")),
          "floors_clipped": sum(x > 0 for x in col("clipped_hours")), "forecast_calls": calls,
          "forecast_refused": sum(col("forecast_refused")),
          "spearman_c_welfare": spearman(col("c"), col("welfare_ratio")),
          "fidelity_spearman_c": spearman(col("within_ns"), col("c"))}
    for k in ("offered_sell_e", "offered_buy_e", "awarded_sell_e", "clipped_hours"):
        m[k] = _mean(col(k))
    for b in REFS:
        if all(b in f["baselines"] for f in fs):
            m |= {f"{b}_c": _mean([f["baselines"][b]["capture"] for f in fs]),
                  f"{b}_compliant_c": _mean([f["baselines"][b]["compliant_c"] for f in fs]),
                  f"delta_{b}": _mean(col(f"delta_{b}")), f"delta_{b}_ci": ci(col(f"delta_{b}"))}
    return m


def ranks(m: dict) -> dict:
    """Sol and the baselines ranked by mean C and by the mean compliant score on C (1 = best)."""
    out = {}
    for key in ("c", "compliant_c"):
        vals = {"Sol": m.get(key)} | {b: m.get(f"{b}_{key}") for b in REFS}
        vals = {k: v for k, v in vals.items() if v is not None}
        order = sorted(vals, key=lambda k: -vals[k])
        out[key] = {k: order.index(k) + 1 for k in order}
    return out


def ci_diff(a: list[float], b: list[float], seed: int = 0) -> list[float] | None:
    """The unpaired 95% bootstrap interval of mean(a) - mean(b), each resampled on its own."""
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    d = sorted(statistics.mean(rng.choices(a, k=len(a))) - statistics.mean(rng.choices(b, k=len(b)))
               for _ in range(pilot_v5.BOOT))
    return [d[int(0.025 * pilot_v5.BOOT)], d[int(0.975 * pilot_v5.BOOT)]]


def v50(tier: str) -> list[dict]:
    """The rules-5.0 pilot's floors at the tier (committed Episode JSON v5), C against its own pack's BR_rt."""
    raw = subprocess.run(["git", "show", V50_PACK], capture_output=True, check=True).stdout
    pack = {r["task_id"]: r for r in map(json.loads, gzip.decompress(raw).decode().splitlines())}
    out = []
    for p in sorted((RUNS / V50[tier]).glob("*.json")):
        e = json.loads(p.read_text())
        sub, refs = submitted(e), pack[e["task_id"]]["refs"]
        c = capture(e["profit_usd"], refs, tier) if sub else 0.0
        out.append({"task_id": e["task_id"], "c": c, "reward": e["reward"], "compliant": e["compliant_reward"],
                    "compliant_c": compliant(c, e["rows"]["welfare_ratio"]) if sub else 0.0} | offering(e))
    return out


def versus(fs: list[dict], old: list[dict]) -> dict:
    """This pilot against the rules-5.0 pilot: unpaired over each one's floors, paired on the floors both played."""
    out = {"n": len(fs), "n_v50": len(old)}
    for k in ("c", "reward", "compliant_c", "compliant", *OFFERING):
        a, b = [f[k] for f in fs], [f[k] for f in old]
        out[k] = {"v51": _mean(a), "v50": _mean(b), "diff": _mean(a) - _mean(b), "diff_ci": ci_diff(a, b)}
    for f_set, key in ((fs, "v51"), (old, "v50")):
        calls = sum(f["forecast_calls"] for f in f_set)
        out.setdefault("forecast_refused_share", {})[key] = sum(f["forecast_refused"] for f in f_set) / calls \
            if calls else None
    prior = {f["task_id"]: f for f in old}
    both = [(f, prior[f["task_id"]]) for f in fs if f["task_id"] in prior]
    out["paired"] = {"n": len(both), "floors": [f["task_id"] for f, _ in both]}
    for k in ("c", "reward", *OFFERING):
        d = [f[k] - g[k] for f, g in both]
        out["paired"][k], out["paired"][k + "_ci"] = _mean(d), ci(d)
    return out


def paired(day: list[dict], sprint: list[dict]) -> dict:
    """floor-day minus floor-sprint on the floors played at both tiers."""
    s = {f["task_id"]: f for f in sprint}
    both = [(f, s[f["task_id"]]) for f in day if f["task_id"] in s]
    out = {"n": len(both)}
    for key in ("c", "reward", "compliant_c", "welfare_ratio"):
        d = [a[key] - b[key] for a, b in both if a[key] is not None and b[key] is not None]
        out[key], out[key + "_ci"] = _mean(d), ci(d)
    return out


def terciles(fs: list[dict]) -> list[dict]:
    order = sorted(fs, key=lambda f: f["within_ns"])
    k = len(order) // 3
    groups = [order[:k], order[k:len(order) - k], order[len(order) - k:]] if k else [order]
    return [{"within_ns": [g[0]["within_ns"], g[-1]["within_ns"]], "n": len(g), "c": _mean([f["c"] for f in g]),
             "reward": _mean([f["reward"] for f in g])} for g in groups if g]


def load(name: str) -> tuple[list[dict], list[dict]]:
    """A sweep's scored floors (from its Episode JSON) and its runs that ended unscored."""
    out = RUNS / name
    spec = json.loads((out / "raw" / "sweep.json").read_text())
    rows = [json.loads(x) for x in (out / "raw" / "results.jsonl").read_text().splitlines() if x.strip()]
    tasks = {r["task_id"]: r for r in market_tasks.pack_rows(spec["pack"])}
    floors, unscored = [], []
    for task_id in spec["tasks"]:
        mine = [r for r in rows if r["task_id"] == task_id]
        scored = next((r for r in mine if r["outcome"] == "scored"), None)
        path = out / f"{task_id}-{slug(scored['model'])}-r{scored['rep']}.json" if scored else None
        if scored and path.is_file():
            floors.append(floor(json.loads(path.read_text()), scored, tasks[task_id]))
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine), "why": "no episode (replay failed)" if scored
                             else (last.get("error_code") or last.get("outcome") or "not run")})
    return floors, unscored


def tables(cells: list[tuple[str, dict]]) -> list[str]:
    head = ["| Set | Floors | C (95% CI) | Anchor's C | C − anchor's C (95% CI) | C < 0 | Compliant on C (95% CI) "
            "| Compliant as built | R (95% CI) | R = 1 | Beats anchor | eps A (95% CI) |",
            "|---|---:|---|---:|---|---:|---|---:|---|---:|---:|---|"]
    base = ["| Set | Floors | Idle C | Anchor C | Price-taker C | Max-withhold C | Replay A C "
            "| C − price-taker (95% CI) | C − replay A (95% CI) | C − max-withhold (95% CI) "
            "| Compliant on C: anchor / price-taker / replay A / max-withhold / idle | Beats price-taker "
            "| Beats replay A | Rank by C | Rank by compliant on C |",
            "|---|---:|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---|---|"]
    pt = ["| Set | Floors | Price-taker R | R − price-taker (95% CI) | Price-making gain $/MW-day (95% CI) | Impact $ "
          "| Impact-hour MWh sold | Anchor's | Price-taker's | Toward price-taker | Welfare ratio | Price-taker's "
          "| Anchor's |", "|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    offer = ["| Set | Floors | Offered sell / energy (median) | Offered buy / energy | Awarded sell / energy "
             "| Exec ≠ award h (floors) | get_forecast calls (refused) | Regret (norm) | Mitigated h (floors) "
             "| Withholding | CfDs/floor (floors) | Submits | Checks | Refused | $/episode | Turns | Output tok |",
             "|---|---:|---|---:|---:|---|---|---:|---|---:|---|---:|---:|---:|---:|---:|---:|"]
    for label, m in cells:
        if not m["n"]:
            continue
        head.append(" | ".join([
            f"| {label}", str(m["n"]), _ci(m, "c"), _f(m["anchor_c"]), _ci(m, "delta"), str(m["c_below_0"]),
            _ci(m, "compliant_c"), _f(m["compliant"]), _ci(m, "reward"), _f(m["reward_at_1"]), _f(m["beats_anchor"]),
            _ci(m, "eps_a")]) + " |")
        base.append(" | ".join([
            f"| {label}", str(m["n"])] + [_f(m.get(f"{b}_c")) for b in ("idle", "anchor", "price_taker", "max_withhold",
                                                                        "replay_A")]
            + [_ci(m, f"delta_{b}") for b in ("price_taker", "replay_A", "max_withhold")]
            + [" / ".join(_f(m.get(f"{b}_compliant_c")) for b in ("anchor", "price_taker", "replay_A", "max_withhold",
                                                                     "idle")),
               _f(m.get("beats_price_taker")), _f(m.get("beats_replay_A"))]
            + [", ".join(f"{k} {v}" for k, v in ranks(m)[key].items()) for key in ("c", "compliant_c")]) + " |")
        pt.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m.get("price_taker_reward")), _ci(m, "reward_minus_price_taker"),
            _ci(m, "price_making_gain_usd_per_mw_day"), _f(m["impact_usd"], ",.0f"),
            _f(m["impact_hour_mwh"], ",.0f"), _f(m["anchor_impact_hour_mwh"], ",.0f"),
            _f(m["price_taker_impact_hour_mwh"], ",.0f"), _f(m["toward_price_taker"], ".2f"), _f(m["welfare_ratio"]),
            _f(m.get("price_taker_welfare_ratio")), _f(m.get("anchor_welfare_ratio"))]) + " |")
        offer.append(" | ".join([
            f"| {label}", str(m["n"]), f"{_f(m['offered_sell_e'], '.2f')} ({_f(m['offered_sell_e_median'], '.2f')})",
            _f(m["offered_buy_e"], ".2f"), _f(m["awarded_sell_e"], ".2f"),
            f"{_f(m['clipped_hours'], '.2f')} ({m['floors_clipped']})",
            f"{m['forecast_calls']} ({m['forecast_refused']})", _f(m["regret_norm"]),
            f"{m['mitigated_hours']} ({m['floors_mitigated']})", _f(m["withholding_index"]),
            f"{_f(m['contracts'], '.2f')} ({m['floors_with_contract']})", _f(m["submits"], ".2f"),
            _f(m["checks"], ".2f"), str(m["refused"]),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}", _f(m["turns"], ".1f"),
            _f(m["output_tokens"], ",.0f")]) + " |")
    return head + [""] + base + [""] + pt + [""] + offer


def versus_lines(col: str, v: dict) -> list[str]:
    def cell(k, fmt=".3f"):
        x = v[k]
        c = x["diff_ci"]
        return (f"{_f(x['v51'], fmt)} vs {_f(x['v50'], fmt)}, {_f(x['diff'], '+' + fmt)}"
                + (f" ({_f(c[0], '+' + fmt)} to {_f(c[1], '+' + fmt)})" if c else ""))

    p = v["paired"]
    share = v["forecast_refused_share"]
    return [f"{col} against the rules-5.0 pilot ({v['n']} floors vs its {v['n_v50']}, different floors, unpaired): "
            f"C {cell('c')}; R {cell('reward')}; compliant on C {cell('compliant_c')}; as built {cell('compliant')}; "
            f"offered sell / energy {cell('offered_sell_e', '.2f')}; awarded sell / energy "
            f"{cell('awarded_sell_e', '.2f')}; exec ≠ award h {cell('clipped_hours', '.2f')}; get_forecast refused "
            f"{_f(share['v51'], '.2f')} vs {_f(share['v50'], '.2f')} of calls.", "",
            f"{col} on the {p['n']} floors both pilots played (5.1 − 5.0, paired): C {_ci(p, 'c')}, R "
            f"{_ci(p, 'reward')}, offered sell / energy {_ci(p, 'offered_sell_e')}, awarded sell / energy "
            f"{_ci(p, 'awarded_sell_e')}, exec ≠ award h {_ci(p, 'clipped_hours')}.", ""]


def showcase_line(f: dict) -> str:
    return (f"{f['task_id']}: C {_f(f['c'])} (anchor {_f(f['anchor_c'])}), compliant on C {_f(f['compliant_c'])} (as "
            f"built {_f(f['compliant'])}), R {_f(f['reward'])}, profit ${f['profit_usd']:,.0f} (anchor "
            f"${f['p_anchor']:,.0f}, hindsight BR_rt ${f['p_hind']:,.0f}), welfare ratio {_f(f['welfare_ratio'])}, "
            f"CfDs {f['contracts']}, mitigated h {f['mitigated_hours']}, ${f['cost_usd'] or 0:.4f}, {f['turns']} turns")


def column(label: str, fs: list[dict]) -> list[tuple[str, dict]]:
    return ([(f"{label}: all", summary(fs))]
            + [(f"{label}: {s}", summary([f for f in fs if f["stratum"] == s])) for s in ("peak", "base")])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sprint", help="The pre-registered floor-sprint sweep (v5b-pilot-sol).")
    ap.add_argument("--day", help="The floor-day sweep (v5b-pilot-sol-day).")
    ap.add_argument("--amend", nargs="*", default=[], help="The labelled amendment sweeps.")
    ap.add_argument("--showcase", nargs="*", default=[], help="The showcase sweeps (display only).")
    ap.add_argument("--smoke", nargs="*", default=[], help="The smoke sweeps (spend only).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    names = [n for n in [args.sprint, args.day, *args.amend, *args.showcase, *args.smoke] if n]
    out = {"columns": {}, "unscored": {}, "versus_v50": {},
           "spend_usd": {n: round(pilot_v5.spend(n), 4) for n in names}}
    amended = {a: load(a) for a in args.amend}
    lines: list[str] = []
    sets: dict[str, dict[str, list[dict]]] = {}
    for col, name in (("floor-sprint", args.sprint), ("floor-day", args.day)):
        if not name:
            continue
        fs, unscored = load(name)
        out["unscored"][col] = unscored
        sets[col] = {"primary": fs}
        extra = [f for a, (ds, _) in amended.items() if json.loads(
            (RUNS / a / "raw" / "sweep.json").read_text())["tier"] == col for f in ds]
        if extra:
            sets[col]["amended"] = fs + [f for f in extra if f["task_id"] not in {x["task_id"] for x in fs}]
        out["columns"][col] = {}
        old = v50(col)
        for label, ds in sets[col].items():
            cells = column(f"{col} {label}", ds)
            out["columns"][col][label] = {lab: m | {"ranks": ranks(m)} for lab, m in cells} | {"floors": ds,
                                                                         "fidelity_terciles": terciles(ds)}
            lines += tables(cells) + [""]
            m = cells[0][1]
            if not m["n"]:
                continue
            ts = terciles(ds)
            lines += [f"{col} {label}: Spearman of C with the welfare ratio {_f(m['spearman_c_welfare'], '.2f')}"
                      + "".join(f" ({c[0]} {_f(c[1]['spearman_c_welfare'], '.2f')})" for c in cells[1:])
                      + f"; fidelity (within_ns) with C {_f(m['fidelity_spearman_c'], '.2f')}, terciles "
                      + "; ".join(f"{t['within_ns'][0]:.2f}-{t['within_ns'][1]:.2f}: C {_f(t['c'])}, "
                                  f"R {_f(t['reward'])} (n {t['n']})" for t in ts)
                      + f"; errors {_counts(m['errors'])}.", ""]
            v = versus(ds, old)
            out["versus_v50"].setdefault(col, {})[label] = v
            lines += versus_lines(f"{col} {label}", v)
    if "floor-day" in sets and "floor-sprint" in sets:
        out["paired_day_minus_sprint"] = {}
        for label, ds in sets["floor-sprint"].items():
            p = paired(sets["floor-day"]["primary"], ds)
            out["paired_day_minus_sprint"][label] = p
            lines += [f"floor-day minus floor-sprint {label} on the {p['n']} floors played at both: C {_ci(p, 'c')}, "
                      f"R {_ci(p, 'reward')}, compliant on C {_ci(p, 'compliant_c')}, welfare ratio "
                      f"{_ci(p, 'welfare_ratio')}.", ""]
    show = []
    for name in args.showcase:
        fs, missing = load(name)
        show += fs
        out["unscored"][name] = missing
        lines += ["Showcase (display only): " + ("; ".join(showcase_line(f) for f in fs) or f"unscored: {missing}"),
                  ""]
    out["showcase"] = show
    unscored = [f"{c} {len(us)} ({_counts(dict(Counter(u['why'] for u in us)))})"
                for c, us in out["unscored"].items() if us]
    lines += ["Unscored: " + ("; ".join(unscored) or "none") + ".",
              "Spend: " + ", ".join(f"{n} ${v:.2f}" for n, v in out["spend_usd"].items())
              + f"; total ${sum(out['spend_usd'].values()):.2f}."]
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
