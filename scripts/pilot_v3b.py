"""The v3 re-pilot's registered analysis under rules 3.1 (docs/prereg/v3-pilot-b.md), from the sweeps' replay-verified
Episode JSON v3 and results.jsonl. Headline per docs/REWARD-SCALES.md: hindsight capture C = (P - P_idle)/(P_hind -
P_idle), the anchor's C and Delta = C - C_anchor with its paired CI; R second with its R = 1 and beats-anchor shares;
a reference compared as (P - P_ref)/(P_hind - P_idle). CIs are 95% percentile bootstrap over days, 10,000 resamples,
seed 0 for levels and 1 for paired differences (scripts/reward_scales.py on lane-reward). Regulation, deployment and
format metrics replay each day and play the anchor in process; the AS, reserve and play tables are pilot_v3's."""

import argparse
import json
import statistics
from pathlib import Path

import numpy as np
import pilot_v3 as p3

from agentenv_gridsim import hybrid_tasks
from agentenv_gridsim.sweep import slug
from gridsim_core.hybrid import anchor_policy, play

RUNS = Path("results/runs")
EPS = 1e-9
BOOT = 10_000
STRATA = ("low", "mid", "high")
REFS = {"reserves": ("as_hog", "sponge", "v2_energy", "energy_only"), "energy": ("sponge", "v2_energy")}
LABEL = {"as_hog": "AS-hog", "sponge": "solar sponge", "v2_energy": "v2 energy-only", "energy_only": "energy-only MILP"}
KEEP = ("keep", None)


def boot(xs: list[float], seed: int = 0) -> tuple[float, float] | None:
    if len(xs) < 2:
        return None
    a = np.asarray(xs, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(a), size=(BOOT, len(a)))
    m = np.sort(a[idx].mean(axis=1))
    return float(m[int(0.025 * BOOT)]), float(m[int(0.975 * BOOT) - 1])


def boot_gap(xs: list[float], ys: list[float], seed: int = 2) -> tuple[float, float] | None:
    """Unpaired: mean(xs) - mean(ys), each group resampled on its own."""
    if len(xs) < 2 or len(ys) < 2:
        return None
    rng = np.random.default_rng(seed)
    a, b = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    m = np.sort(a[rng.integers(0, len(a), size=(BOOT, len(a)))].mean(axis=1)
                - b[rng.integers(0, len(b), size=(BOOT, len(b)))].mean(axis=1))
    return float(m[int(0.025 * BOOT)]), float(m[int(0.975 * BOOT) - 1])


def cap(p: float, d: dict) -> float:
    return (p - d["p_idle"]) / (d["p_hind"] - d["p_idle"])


def ref_profits(e: dict) -> dict:
    r = e["references"]
    out = {k: v["profit"] for k, v in (r.get("baselines") or {}).items()}
    if r.get("p_energy_only") is not None:
        out["energy_only"] = r["p_energy_only"]
    return out


def top_hours(task: dict, n: int = 6) -> set[int]:
    da = task["prices"]
    return set(sorted(range(24), key=lambda h: -da[h])[:n])


def regulation(sol, anc, task: dict) -> dict:
    """RegDn drift energy bought at RT and the RegDn and RegUp books, Sol's (replayed) and the anchor's (played)."""
    top = top_hours(task)

    def one(s):
        return {"dn_cost": sum(r["dn_mwh"] * task["rt"][r["h"]] for r in s.rows),
                "dn_mwh": sum(r["dn_mwh"] for r in s.rows),
                "regdn_top6": sum(r["a"]["regdn"] for r in s.rows if r["h"] in top),
                "regdn_mw_h": sum(r["a"]["regdn"] for r in s.rows), "regup_mw_h": sum(r["a"]["regup"] for r in s.rows)}

    return {"sol": one(sol), "anchor": one(anc)}


def deployment(e: dict, sol, anc, task: dict) -> dict | None:
    """On a deployment day: each deployed product's award over the hours its deployments touch, FTP charged in it, and
    whether Sol committed at a watch a deployment notice opened."""
    deps = task.get("deployments") or []
    if not deps:
        return None
    hours = {}
    for d in deps:
        h0, h1 = int(d["start"][11:13]), int(d["end"][11:13])
        hours.setdefault(d["product"], set()).update(range(h0, min(h1, 23) + 1))
    watches = [w["index"] for w in e["watches"] if any(str(n).startswith("dep-") for n in w.get("notices") or [])]
    committed = {c["watch"] for c in e["commits"] if c["committed"]}

    def one(s):
        return {k: {"award_mw_h": sum(s.rows[h]["a"][k] for h in hs),
                    "ftp_mwh": sum(r["charged"].get(k, 0.0) for r in s.rows)} for k, hs in hours.items()}

    return {"products": {k: sorted(v) for k, v in hours.items()}, "sol": one(sol), "anchor": one(anc),
            "deploy_watches": watches, "replanned_at": [w for w in watches if w in committed]}


def format_use(e: dict) -> dict:
    """Plans that kept an AS field by "keep" or null, and parse refusals."""
    keep = refused_keep = parse = 0
    for st in e["steps"]:
        if st["tool"] not in ("check_schedule", "commit_schedule"):
            continue
        plan = (st["args"] or {}).get("plan") or {}
        kept = isinstance(plan, dict) and any(
            (isinstance(v, str) and v.strip().lower() == "keep") or v is None for k, v in plan.items() if k != "energy")
        out = st["output"]
        rows = out.get("refused" if st["tool"] == "commit_schedule" else "issues") or []
        rules = [x.get("rule") for x in rows if isinstance(x, dict)]
        keep += kept
        refused_keep += kept and "parse" in rules
        parse += st["tool"] == "commit_schedule" and "parse" in rules
    w0 = any(c["watch"] == 0 and c["committed"] for c in e["commits"])
    return {"keep_calls": keep, "keep_parse_refused": refused_keep, "parse_refused_commits": parse,
            "watch0_book": w0}


def day(e: dict, row: dict, task: dict, with_anchor: bool) -> dict:
    d = p3.day(e, row, task)
    refs = ref_profits(e)
    d |= {"refs": refs, "c": cap(d["profit_usd"], d), "c_anchor": cap(d["p_anchor"], d),
          "deploy_day": bool(task["tags"]["deploy_day"]), "pv_poi": round(task["site"]["pv_mwac"] /
                                                                           task["site"]["poi_mw"], 2),
          "reg_source": (task.get("reg") or {}).get("source"), "format": format_use(e)}
    d["delta"] = d["c"] - d["c_anchor"]
    d["vs"] = {k: (d["profit_usd"] - v) / (d["p_hind"] - d["p_idle"]) for k, v in refs.items()}
    d["ref_c"] = {k: cap(v, d) for k, v in refs.items()}
    d["ref_r"] = {k: p3.reward_value(v, d["p_idle"], d["p_anchor"]) for k, v in refs.items()}
    d["beats"] = {k: d["profit_usd"] > v + 1e-6 for k, v in refs.items()}
    if with_anchor and e["tier"] != "energy":
        sol = p3.replayed(e, task)
        anc = play(task, e["tier"], anchor_policy())
        if abs(anc.profit() - d["p_anchor"]) > 1e-3:
            raise SystemExit(f"{e['task_id']}: the anchor plays {anc.profit()}, stored {d['p_anchor']}")
        d["reg"] = regulation(sol, anc, task)
        d["l_reg"] = (d["reg"]["sol"]["dn_cost"] - d["reg"]["anchor"]["dn_cost"]) / (d["p_hind"] - d["p_idle"])
        d["deploy"] = deployment(e, sol, anc, task)
    return d


def load(name: str, with_anchor: bool = True) -> tuple[list[dict], list[dict]]:
    out = RUNS / name
    spec = json.loads((out / "raw" / "sweep.json").read_text())
    rows = [json.loads(x) for x in (out / "raw" / "results.jsonl").read_text().splitlines() if x.strip()]
    tasks = {r["task_id"]: r for r in hybrid_tasks.pack_rows(spec["pack"])}
    days, unscored = [], []
    for task_id in spec["tasks"]:
        mine = [r for r in rows if r["task_id"] == task_id]
        scored = next((r for r in mine if r["outcome"] == "scored"), None)
        path = out / f"{task_id}-{slug(scored['model'])}-r{scored['rep']}.json" if scored else None
        if scored and path.is_file():
            days.append(day(json.loads(path.read_text()), scored, tasks[task_id], with_anchor))
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return sorted(days, key=lambda d: d["task_id"]), unscored


def _f(x, fmt: str = ".3f") -> str:
    return "–" if x is None else format(x, fmt)


def _m(xs: list[float], fmt: str = ".3f", seed: int = 0) -> str:
    if not xs:
        return "–"
    c = boot(xs, seed)
    return _f(statistics.mean(xs), fmt) + (f" ({_f(c[0], fmt)} to {_f(c[1], fmt)})" if c else "")


def headline(days: list[dict]) -> dict:
    n = len(days)
    if not n:
        return {"n": 0}
    c, ca, dl, r = ([d[k] for d in days] for k in ("c", "c_anchor", "delta", "reward"))
    return {"n": n, "c": statistics.mean(c), "c_ci": boot(c), "c_anchor": statistics.mean(ca),
            "delta": statistics.mean(dl), "delta_ci": boot(dl, 1), "r": statistics.mean(r), "r_ci": boot(r),
            "r_at_1": statistics.mean(float(x >= 1 - 1e-6) for x in r),
            "beats_anchor": statistics.mean(float(d["beats_anchor"]) for d in days),
            "refs": {k: {"c": statistics.mean(d["ref_c"][k] for d in days),
                         "r": statistics.mean(d["ref_r"][k] for d in days),
                         "vs": statistics.mean(d["vs"][k] for d in days), "vs_ci": boot([d["vs"][k] for d in days], 1),
                         "beats": statistics.mean(float(d["beats"][k]) for d in days)}
                     for k in days[0]["refs"] if all(k in d["refs"] for d in days)}}


def headline_tables(cells: list[tuple[str, list[dict]]], tier: str) -> list[str]:
    out = ["| Set | Days | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |",
           "|---|---:|---|---:|---|---|---:|---:|"]
    refs = ["| Set | Reference | Its C | Its R | Sol − it: (P − P_ref)/(P_hind − P_idle) (95% CI) | Sol beats it |",
            "|---|---|---:|---:|---|---:|"]
    for label, ds in cells:
        if not ds:
            out.append(f"| {label} | 0 |" + " – |" * 6)
            continue
        out.append(" | ".join([f"| {label}", str(len(ds)), _m([d["c"] for d in ds]),
                               _f(statistics.mean(d["c_anchor"] for d in ds)), _m([d["delta"] for d in ds], "+.3f", 1),
                               _m([d["reward"] for d in ds]), _f(statistics.mean(float(d["reward"] >= 1 - 1e-6)
                                                                                for d in ds), ".2f"),
                               _f(statistics.mean(float(d["beats_anchor"]) for d in ds), ".2f")]) + " |")
        for k in REFS[tier]:
            if not all(k in d["refs"] for d in ds):
                continue
            refs.append(" | ".join([f"| {label}", LABEL[k], _f(statistics.mean(d["ref_c"][k] for d in ds)),
                                    _f(statistics.mean(d["ref_r"][k] for d in ds)),
                                    _m([d["vs"][k] for d in ds], "+.3f", 1),
                                    _f(statistics.mean(float(d["beats"][k]) for d in ds), ".2f")]) + " |")
    return out + [""] + refs


def reg_summary(days: list[dict]) -> dict:
    ds = [d for d in days if d.get("reg")]
    if not ds:
        return {"n": 0}

    def m(who, k):
        return statistics.mean(d["reg"][who][k] for d in ds)

    gap = [d["reg"]["sol"]["dn_cost"] - d["reg"]["anchor"]["dn_cost"] for d in ds]
    return {"n": len(ds), "l_reg": statistics.mean(d["l_reg"] for d in ds), "l_reg_ci": boot([d["l_reg"] for d in ds],
                                                                                            1),
            "dn_cost_sol": m("sol", "dn_cost"), "dn_cost_anchor": m("anchor", "dn_cost"),
            "dn_cost_gap": statistics.mean(gap), "dn_cost_gap_median": statistics.median(gap),
            "days_sol_above": sum(g > 1e-6 for g in gap),
            **{f"{k}_{w}": m(w, k) for k in ("dn_mwh", "regdn_top6", "regdn_mw_h", "regup_mw_h")
               for w in ("sol", "anchor")}}


def reg_table(cells: list[tuple[str, list[dict]]]) -> list[str]:
    out = ["| Set | Days | L_reg: (Sol − anchor RegDn drift $)/(P_hind − P_idle) (95% CI) | RegDn drift bought $/day "
           "Sol / anchor | Sol − anchor $/day (median) | Days Sol pays more | RegDn drift MWh/day Sol / anchor "
           "| RegDn MW-h in the 6 top-DA hours Sol / anchor | RegDn MW-h/day Sol / anchor "
           "| RegUp MW-h/day Sol / anchor |", "|---|---:|---|---|---|---:|---|---|---|---|"]
    for label, ds in cells:
        s = reg_summary(ds)
        if not s["n"]:
            continue
        ci = s["l_reg_ci"]
        out.append(" | ".join([
            f"| {label}", str(s["n"]),
            f"{s['l_reg']:+.3f}" + (f" ({ci[0]:+.3f} to {ci[1]:+.3f})" if ci else ""),
            f"{s['dn_cost_sol']:,.0f} / {s['dn_cost_anchor']:,.0f}",
            f"{s['dn_cost_gap']:+,.0f} ({s['dn_cost_gap_median']:+,.0f})", f"{s['days_sol_above']} of {s['n']}",
            f"{s['dn_mwh_sol']:.1f} / {s['dn_mwh_anchor']:.1f}", f"{s['regdn_top6_sol']:.0f} / "
            f"{s['regdn_top6_anchor']:.0f}", f"{s['regdn_mw_h_sol']:.0f} / {s['regdn_mw_h_anchor']:.0f}",
            f"{s['regup_mw_h_sol']:.0f} / {s['regup_mw_h_anchor']:.0f}"]) + " |")
    return out


def deploy_lines(days: list[dict]) -> tuple[list[str], dict]:
    dep = [d for d in days if d["deploy_day"]]
    other = [d for d in days if not d["deploy_day"]]
    out = ["| Day | Deployed (hours) | Award MW-h in those hours Sol / anchor | FTP MWh charged in it Sol / anchor "
           "| Deployment watches, Sol committed at | C | Anchor's C | Δ | R |",
           "|---|---|---|---|---|---:|---:|---:|---:|"]
    for d in dep:
        x = d.get("deploy") or {}
        prods = x.get("products") or {}
        out.append(" | ".join([
            f"| `{d['task_id']}`", ", ".join(f"{k} {v[0]}-{v[-1]}" for k, v in prods.items()) or "–",
            ", ".join(f"{k} {x['sol'][k]['award_mw_h']:.0f} / {x['anchor'][k]['award_mw_h']:.0f}" for k in prods),
            ", ".join(f"{k} {x['sol'][k]['ftp_mwh']:.2f} / {x['anchor'][k]['ftp_mwh']:.2f}" for k in prods),
            f"{x.get('deploy_watches')} / {x.get('replanned_at')}", _f(d["c"]), _f(d["c_anchor"]),
            _f(d["delta"], "+.3f"), _f(d["reward"])]) + " |")
    a, b = [d["delta"] for d in dep], [d["delta"] for d in other]
    gap = statistics.mean(a) - statistics.mean(b) if a and b else None
    summ = {"deploy_days": len(dep), "delta_deploy": statistics.mean(a) if a else None,
            "delta_other": statistics.mean(b) if b else None, "gap": gap, "gap_ci": boot_gap(a, b),
            "ftp_sol": sum(x["sol"][k]["ftp_mwh"] for d in dep if (x := d.get("deploy")) for k in x["sol"]),
            "ftp_anchor": sum(x["anchor"][k]["ftp_mwh"] for d in dep if (x := d.get("deploy")) for k in x["anchor"]),
            "deploy_watches": sum(len(d["deploy"]["deploy_watches"]) for d in dep if d.get("deploy")),
            "replanned": sum(len(d["deploy"]["replanned_at"]) for d in dep if d.get("deploy"))}
    ci = summ["gap_ci"]
    out += ["", f"Δ on deployment days {_f(summ['delta_deploy'], '+.3f')} against {_f(summ['delta_other'], '+.3f')} "
                f"on the others: gap {_f(gap, '+.3f')}" + (f" ({ci[0]:+.3f} to {ci[1]:+.3f}, unpaired)" if ci else "")
            + f"; FTP charged in the deployed products {summ['ftp_sol']:.2f} MWh (anchor {summ['ftp_anchor']:.2f}); "
              f"Sol committed at {summ['replanned']} of {summ['deploy_watches']} deployment watches."]
    return out, summ


def format_line(days: list[dict]) -> tuple[str, dict]:
    f = {k: sum(d["format"][k] for d in days) for k in ("keep_calls", "keep_parse_refused", "parse_refused_commits")}
    f["days_without_watch0_book"] = sum(not d["format"]["watch0_book"] for d in days)
    return (f"Format: {f['keep_calls']} planning calls kept an AS field by \"keep\" or null, "
            f"{f['keep_parse_refused']} of them refused as parse; {f['parse_refused_commits']} commits refused as "
            f"parse in all; {f['days_without_watch0_book']} days without an accepted watch-0 commit."), f


def showcase_line(d: dict) -> str:
    refs = ", ".join(f"{LABEL[k]} C {d['ref_c'][k]:.3f} R {d['ref_r'][k]:.3f}" for k in REFS["reserves"]
                     if k in d["ref_c"])
    reg = d.get("reg") or {}
    dep = d.get("deploy") or {}
    return (f"{d['task_id']} ({d['tier']}): C {d['c']:.3f} (anchor {d['c_anchor']:.3f}, Δ {d['delta']:+.3f}), "
            f"R {d['reward']:.3f}; {refs}; profit ${d['profit_usd']:,.0f} (idle ${d['p_idle']:,.0f}, anchor "
            f"${d['p_anchor']:,.0f}, hindsight ${d['p_hind']:,.0f}); AS share {_f(d['as_share'])}; FTP "
            f"{d['ftp_mwh_charged']:.2f} MWh charged / {d['ftp_mwh_excused']:.2f} excused"
            + (f"; RegDn drift bought ${reg['sol']['dn_cost']:,.0f} (anchor ${reg['anchor']['dn_cost']:,.0f})"
               if reg else "")
            + (f"; deployment watches {dep['deploy_watches']}, committed at {dep['replanned_at']}" if dep else "")
            + f"; re-planned {d['replan_watches']} of {d['later_watches']} later watches; ${d['cost_usd']:.4f}, "
              f"{d['turns']} turns")


def spend(name: str) -> float:
    rows = (RUNS / name / "raw" / "results.jsonl").read_text().splitlines()
    return sum(json.loads(x).get("cost_usd") or 0.0 for x in rows if x.strip())


def strip(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("refs",)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The reserves-tier sweep (v3b-pilot-sol).")
    ap.add_argument("--energy", help="The energy-tier sweep (v3b-pilot-sol-energy).")
    ap.add_argument("--amend", nargs="*", default=[], help="Labelled amendment sweeps (unscored runs at 2x cap).")
    ap.add_argument("--showcase", nargs="*", default=[], help="Display-only sweeps.")
    ap.add_argument("--extra-spend", nargs="*", default=[], help="Other sweeps whose spend counts (the smoke).")
    ap.add_argument("--regulation", action="store_true", help="Only the regulation table for MAIN (any rules).")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    if args.regulation:
        days, _ = load(args.main)
        print("\n".join(reg_table([(f"{args.main}: all", days)])))
        print(json.dumps(reg_summary(days), indent=1))
        return
    names = [n for n in [*args.extra_spend, args.main, args.energy, *args.amend, *args.showcase] if n]
    out = {"columns": {}, "unscored": {}, "spend_usd": {n: round(spend(n), 4) for n in names}}
    amends = {a: load(a) for a in args.amend}
    lines: list[str] = []
    for tier, name in (("reserves", args.main), ("energy", args.energy)):
        if not name:
            continue
        days, unscored = load(name)
        out["unscored"][tier] = unscored
        sets = {"primary": days}
        extra = [d for a, (ds, _) in amends.items() for d in ds if d["tier"] == tier]
        if extra:
            sets["amended"] = days + [d for d in extra if d["task_id"] not in {x["task_id"] for x in days}]
        out["columns"][tier] = {}
        for label, ds in sets.items():
            cells = [(f"{tier} {label}: all", ds)]
            if tier == "reserves":
                cells += [(f"{tier} {label}: deployment days", [d for d in ds if d["deploy_day"]]),
                          (f"{tier} {label}: other days", [d for d in ds if not d["deploy_day"]])]
                cells += [(f"{tier} {label}: {s} AS", [d for d in ds if d["stratum"] == s]) for s in STRATA]
            else:
                cells += [(f"{tier} {label}: PV/POI {r}", [d for d in ds if (d["pv_poi"] >= 1.3) == (r == "1.4")])
                          for r in ("1.25", "1.4")]
            col = {"headline": {lab: headline(x) for lab, x in cells}, "days": [strip(d) for d in ds]}
            lines += [f"### {tier} {label}", ""] + headline_tables(cells, tier) + [""]
            v3 = [(lab, p3.summary(x)) for lab, x in cells]
            t = p3.tables(v3, tier == "reserves")
            lines += t[t.index("") + 1:] + [""]
            if tier == "reserves":
                col["regulation"] = {lab: reg_summary(x) for lab, x in cells}
                lines += reg_table(cells) + [""]
                dl, col["deployment"] = deploy_lines(ds)
                lines += dl + [""]
            fl, col["format"] = format_line(ds)
            m = p3.summary(ds)
            col["v3_summary"] = m
            lines += [fl, "", f"{tier} {label}: check_schedule issues by rule: "
                              f"{p3._counts(m.get('check_issues_by_rule') or {})}; FTP MWh charged by product "
                              f"(regup/regdn/rrs/ecrs/nspin) {p3._by_product(m['ftp_charged_by_product'], '.2f')}, "
                              f"excused {p3._by_product(m['ftp_excused_by_product'], '.2f')}; error taxonomy "
                              f"{p3._counts(m.get('errors') or {})}.", ""]
            out["columns"][tier][label] = col
    show = []
    for name in args.showcase:
        ds, missing = load(name)
        show += [strip(d) for d in ds]
        out["unscored"][name] = missing
        lines += ["Display only: " + ("; ".join(showcase_line(d) for d in ds) or f"unscored: {missing}"), ""]
    out["showcase"] = show
    unscored = [f"{u['task_id']} ({c}: {u['why']}, {u['attempts']} attempts)" for c, us in out["unscored"].items()
                for u in us]
    lines += ["Unscored: " + ("; ".join(unscored) or "none") + ".",
              "Spend: " + ", ".join(f"{n} ${v:.2f}" for n, v in out["spend_usd"].items())
              + f"; total ${sum(out['spend_usd'].values()):.2f}."]
    if args.json:
        args.json.write_text(json.dumps(out, indent=1, default=lambda x: sorted(x) if isinstance(x, set) else str(x))
                             + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
