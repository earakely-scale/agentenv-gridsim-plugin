"""The v3 re-pilot's registered analysis under rules 3.2 (docs/prereg/v3-pilot-c.md), from the sweeps' replay-verified
Episode JSON v3 and results.jsonl: pilot_v3b's headline (C, the anchor's C, Delta with its paired CI, then R),
reference, regulation and deployment tables on the 3.2 settlement, where every shortfall is charged (C3-D19); the
format block counts malformed planning calls and the calls they cost (V3-D16). Exploratory: RegUp booked against the
anchor, and the 3.1 pilot's surviving days paired with this run's, its play also re-settled on the 3.2 Session."""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import pilot_v3 as p3
import pilot_v3b as b

from agentenv_gridsim import hybrid_tasks
from agentenv_gridsim.sweep import slug
from gridsim_core.hybrid import PRODUCTS, Session, anchor_policy, play

RUNS = Path("results/runs")
EPS = 1e-6
PRIOR = Path("results/pilot-v3b.json")
PRIOR_RUNS = {"reserves": ("v3b-pilot-sol", "v3b-pilot-sol-amend"), "energy": ("v3b-pilot-sol-energy",)}
STRATA = ("low", "mid", "high")


def calls(e: dict, task: dict) -> Session:
    """The episode's calls on a fresh rules-3.2 Session, each watch's notices delivered after the advance opening it."""
    s = Session(task, e["tier"])
    for step in e["steps"]:
        if step["tool"] in Session.TOOLS:
            out = json.loads(s.call(step["tool"], step["args"]))
            if step["tool"] == "advance" and "watch" in out:
                s.deliver_watch_notices()
    if not s.done:
        s.end_day()
    return s


def replayed(e: dict, task: dict) -> Session:
    s = calls(e, task)
    if abs(s.grade()["reward"] - e["reward"]) > EPS:
        raise SystemExit(f"{e['task_id']}: the replay scores {s.grade()['reward']}, the episode {e['reward']}")
    return s


def base(e: dict, row: dict, task: dict, s: Session) -> dict:
    """pilot_v3.day's fields on the 3.2 settlement: FTP is each hour's realized shortfall, nothing is excused."""
    r, tier = e["references"], e["tier"]
    p, p_idle, p_anchor = e["profit_usd"], r["p_idle"], r["p_anchor"]
    bl = r.get("baselines") or {}
    charged = {k: sum(x["short"].get(k, 0.0) for x in s.rows) for k in PRODUCTS}
    refused = [x for st in e["steps"] if st["tool"] == "commit_schedule" for x in st["output"].get("refused") or []]
    issues = [x for st in e["steps"] if st["tool"] == "check_schedule" for x in st["output"].get("issues") or []]
    reserve_refused = {k: sum(x["rule"] in p3.RESERVE_RULES and x["field"] == k for x in refused) for k in PRODUCTS}
    replans = {c["watch"] for c in e["commits"] if c["committed"] and c["watch"] >= 1}
    da, anchor = e.get("da") or {}, r.get("anchor") or {}
    as_usd, anchor_as = e["cash"]["as_da"] + e["cash"]["as_rt"], anchor.get("as_usd")
    out = {"task_id": e["task_id"], "tier": tier, "stratum": task["tags"]["as_stratum"],
           "point": task["settlement_point"], "date": task["date"], "notice_day": task["tags"]["notice_day"],
           "reward": e["reward"], "raw_ratio": e["raw_ratio"], "profit_usd": p, "p_idle": p_idle,
           "p_anchor": p_anchor, "p_hind": r["p_hind"], "capture": p3.capture(p, p_idle, r["p_hind"]),
           "anchor_capture": p3.capture(p_anchor, p_idle, r["p_hind"]), "beats_anchor": bool(e["beats_anchor"]),
           "v2_energy": (bl.get("v2_energy") or {}).get("reward"),
           "beats_v2_energy": p > (bl.get("v2_energy") or {}).get("profit", float("inf")) + EPS,
           "as_share": row.get("as_share"), "as_usd": as_usd, "anchor_as_usd": anchor_as,
           "as_vs_anchor": as_usd / anchor_as if anchor_as and anchor_as > EPS else None,
           "da_mwh": {k: sum(da.get(k) or [0.0]) for k in PRODUCTS},
           "anchor_da_mwh": {k: sum((anchor.get("book") or {}).get(k) or [0.0]) for k in PRODUCTS},
           "ftp_charged": charged, "ftp_excused": dict.fromkeys(PRODUCTS, 0.0),
           "ftp_mwh_charged": sum(charged.values()), "ftp_mwh_excused": 0.0, "ftp_usd": e["cash"]["ftp"],
           "end_penalty_usd": e["cash"]["end_penalty"], "reserve_refused": reserve_refused,
           "under_reserved": {k: charged[k] > EPS or reserve_refused[k] > 0 for k in PRODUCTS},
           "refused_rules": dict(Counter(x["rule"] for x in refused)),
           "check_rules": dict(Counter(x["rule"] for x in issues)),
           "refused_commits": sum(bool(c["refused"]) for c in e["commits"]),
           "governor_hours": row.get("governor_hours"), "end_short_mwh": s.grade()["end_short_mwh"],
           "later_watches": len(e["watches"]) - 1, "replan_watches": len(replans),
           "anchor_replans": max((anchor.get("commits") or 1) - 1, 0),
           "commits": sum(bool(c["committed"]) for c in e["commits"]), "planning_calls": row.get("checks"),
           "finished": row.get("end_reason") == "done", "audit_ok": e["audit"]["ok"],
           "cost_usd": row.get("priced_cost_usd") if row.get("priced_cost_usd") is not None else row.get("cost_usd"),
           "turns": row.get("turns"), "input_tokens": row.get("input_tokens"),
           "output_tokens": row.get("output_tokens"), "cached_tokens": row.get("cached_tokens"),
           "errors": row.get("errors") or []}
    if tier != "energy":
        out |= {"as_hog": (bl.get("as_hog") or {}).get("reward"),
                "beats_as_hog": p > (bl.get("as_hog") or {}).get("profit", float("inf")) + EPS,
                "energy_only": p3.reward_value(r["p_energy_only"], p_idle, p_anchor),
                "beats_energy_only": p > r["p_energy_only"] + EPS}
    return out


def deployment(e: dict, sol: Session, anc: Session, task: dict) -> dict | None:
    """pilot_v3b's deployment block with FTP as the realized shortfall in each deployed product."""
    deps = task.get("deployments") or []
    if not deps:
        return None
    hours = {}
    for d in deps:
        hours.setdefault(d["product"], set()).update(range(int(d["start"][11:13]), min(int(d["end"][11:13]), 23) + 1))
    watches = [w["index"] for w in e["watches"] if any(str(n).startswith("dep-") for n in w.get("notices") or [])]
    committed = {c["watch"] for c in e["commits"] if c["committed"]}

    def one(s):
        return {k: {"award_mw_h": sum(s.rows[h]["a"][k] for h in hs),
                    "ftp_mwh": sum(r["short"].get(k, 0.0) for r in s.rows)} for k, hs in hours.items()}

    return {"products": {k: sorted(v) for k, v in hours.items()}, "sol": one(sol), "anchor": one(anc),
            "deploy_watches": watches, "replanned_at": [w for w in watches if w in committed]}


def malformed(st: dict) -> str | None:
    """A planning call refused as malformed (V3-D16): a parse refusal or an argument error."""
    out = st["output"]
    rows = out.get("refused" if st["tool"] == "commit_schedule" else "issues") or []
    if any(isinstance(x, dict) and x.get("rule") == "parse" for x in rows):
        return "parse"
    err = out.get("error") or ""
    return "argument" if "unexpected argument" in err or "missing argument" in err else None


def format_use(e: dict, s: Session) -> dict:
    """Malformed planning calls and the calls they cost, "keep" plans, and the watch-0 book."""
    plans = [st for st in e["steps"] if st["tool"] in ("check_schedule", "commit_schedule")]
    kinds = Counter(k for st in plans if (k := malformed(st)))
    keep = refused_keep = 0
    for st in plans:
        plan = (st["args"] or {}).get("plan") or {}
        kept = isinstance(plan, dict) and any((isinstance(v, str) and v.strip().lower() == "keep") or v is None
                                              for k, v in plan.items() if k != "energy")
        keep += kept
        refused_keep += kept and malformed(st) == "parse"
    n, free, bad, after = sum(kinds.values()), sum(s.free_refusals), set(), 0
    for st in plans:
        after += st["watch"] in bad and (st["output"].get("error") or "").startswith("no planning calls left")
        if malformed(st):
            bad.add(st["watch"])
    return {"malformed": n, "parse": kinds["parse"], "argument": kinds["argument"], "free": free,
            "charged_call": n - free,
            "no_calls_left": sum((st["output"].get("error") or "").startswith("no planning calls left")
                                 for st in plans), "no_calls_after_malformed": after,
            "keep_calls": keep, "keep_parse_refused": refused_keep,
            "watch0_book": any(c["watch"] == 0 and c["committed"] for c in e["commits"])}


def day(e: dict, row: dict, task: dict) -> dict:
    s = replayed(e, task)
    d = base(e, row, task, s)
    refs = b.ref_profits(e)
    d |= {"refs": refs, "c": b.cap(d["profit_usd"], d), "c_anchor": b.cap(d["p_anchor"], d),
          "deploy_day": bool(task["tags"]["deploy_day"]),
          "pv_poi": round(task["site"]["pv_mwac"] / task["site"]["poi_mw"], 2),
          "reg_source": (task.get("reg") or {}).get("source"), "format": format_use(e, s)}
    d["delta"] = d["c"] - d["c_anchor"]
    d["vs"] = {k: (d["profit_usd"] - v) / (d["p_hind"] - d["p_idle"]) for k, v in refs.items()}
    d["ref_c"] = {k: b.cap(v, d) for k, v in refs.items()}
    d["ref_r"] = {k: p3.reward_value(v, d["p_idle"], d["p_anchor"]) for k, v in refs.items()}
    d["beats"] = {k: d["profit_usd"] > v + EPS for k, v in refs.items()}
    if e["tier"] != "energy":
        anc = play(task, e["tier"], anchor_policy())
        if abs(anc.profit() - d["p_anchor"]) > 1e-3:
            raise SystemExit(f"{e['task_id']}: the anchor plays {anc.profit()}, stored {d['p_anchor']}")
        d["reg"] = b.regulation(s, anc, task)
        d["l_reg"] = (d["reg"]["sol"]["dn_cost"] - d["reg"]["anchor"]["dn_cost"]) / (d["p_hind"] - d["p_idle"])
        d["deploy"] = deployment(e, s, anc, task)
    return d


def load(name: str) -> tuple[list[dict], list[dict]]:
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
            days.append(day(json.loads(path.read_text()), scored, tasks[task_id]) | {"attempts": len(mine)})
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return sorted(days, key=lambda d: d["task_id"]), unscored


def format_line(days: list[dict]) -> tuple[str, dict]:
    keys = ("malformed", "parse", "argument", "free", "charged_call", "no_calls_left", "no_calls_after_malformed",
            "keep_calls", "keep_parse_refused")
    f = {k: sum(d["format"][k] for d in days) for k in keys}
    f["days_with_malformed"] = sum(d["format"]["malformed"] > 0 for d in days)
    f["days_without_watch0_book"] = [d["task_id"] for d in days if not d["format"]["watch0_book"]]
    return (f"Format (V3-D16): {f['malformed']} malformed planning calls on {f['days_with_malformed']} days "
            f"({f['parse']} parse refusals, {f['argument']} argument errors), {f['free']} used no planning call and "
            f"{f['charged_call']} used one; {f['no_calls_left']} planning calls found no calls left "
            f"({f['no_calls_after_malformed']} in a watch after a malformed call); "
            f"{f['keep_calls']} plans kept an AS field by \"keep\" or null, {f['keep_parse_refused']} refused as "
            f"parse; days without an accepted watch-0 commit: {len(f['days_without_watch0_book'])}"
            + (f" ({', '.join(f['days_without_watch0_book'])})" if f["days_without_watch0_book"] else "") + "."), f


def regup(days: list[dict], prior: dict) -> tuple[str, dict]:
    """Exploratory: RegUp booked (DA award MW-h a day) against the anchor's; on the common days also the 3.1 run's."""
    ds = [d for d in days if d.get("reg")]
    if not ds:
        return "", {}
    com = [d for d in ds if d["task_id"] in prior and prior[d["task_id"]].get("reg")]
    out = {"n": len(ds), "sol": statistics.mean(d["reg"]["sol"]["regup_mw_h"] for d in ds),
           "anchor": statistics.mean(d["reg"]["anchor"]["regup_mw_h"] for d in ds),
           "days_sol_books": sum(d["reg"]["sol"]["regup_mw_h"] > EPS for d in ds),
           "days_anchor_books": sum(d["reg"]["anchor"]["regup_mw_h"] > EPS for d in ds),
           "common": len(com),
           "common_sol": statistics.mean(d["reg"]["sol"]["regup_mw_h"] for d in com) if com else None,
           "common_sol_31": statistics.mean(prior[d["task_id"]]["reg"]["sol"]["regup_mw_h"] for d in com)
           if com else None,
           "common_anchor": statistics.mean(d["reg"]["anchor"]["regup_mw_h"] for d in com) if com else None}
    return (f"RegUp (exploratory): Sol books {out['sol']:.0f} MW-h a day against the anchor's {out['anchor']:.0f} "
            f"(on {out['days_sol_books']} and {out['days_anchor_books']} of {out['n']} days); on the "
            f"{out['common']} days common with the 3.1 pilot {b._f(out['common_sol'], '.0f')} against 3.1 Sol's "
            f"{b._f(out['common_sol_31'], '.0f')} and the 3.2 anchor's {b._f(out['common_anchor'], '.0f')}."), out


def resettled(task_id: str, tier: str, task: dict) -> float | None:
    """The 3.1 pilot's play of a day (its scored episode's calls) settled on the 3.2 Session."""
    for name in PRIOR_RUNS[tier]:
        for f in sorted((RUNS / name).glob(f"{task_id}-*.json")):
            return calls(json.loads(f.read_text()), task).grade()["profit_usd"]
    return None


def compare(days: list[dict], tier: str, prior: dict, tasks: dict) -> tuple[list[str], dict]:
    """Exploratory, labelled (the rules changed, so not a model comparison): the 3.1 pilot's days that survive,
    paired. C and Delta each on its own rules; the 3.1 play re-settled under 3.2 holds the settlement fixed."""
    com = [d for d in days if d["task_id"] in prior]
    if len(com) < 2:
        return [], {"n": len(com)}
    rows = []
    for d in com:
        q, p31 = prior[d["task_id"]], resettled(d["task_id"], tier, tasks[d["task_id"]])
        span = d["p_hind"] - d["p_idle"]
        rows.append({"task_id": d["task_id"], "c31": q["c"], "d31": q["delta"], "r31": q["reward"], "c32": d["c"],
                     "d32": d["delta"], "r32": d["reward"], "c31_32": (p31 - d["p_idle"]) / span,
                     "d31_32": (p31 - d["p_anchor"]) / span, "same": (d["profit_usd"] - p31) / span})

    def m(k):
        return statistics.mean(x[k] for x in rows)

    def ci(xs):
        c = b.boot(xs, 3)
        return f" ({c[0]:+.3f} to {c[1]:+.3f})" if c else ""

    dc, dd, same = ([x["c32"] - x["c31"] for x in rows], [x["d32"] - x["d31"] for x in rows],
                    [x["same"] for x in rows])
    out = {"n": len(rows), "days": rows, **{k: m(k) for k in ("c31", "d31", "r31", "c32", "d32", "r32", "c31_32",
                                                               "d31_32", "same")},
           "c_diff_ci": b.boot(dc, 3), "delta_diff_ci": b.boot(dd, 3), "same_ci": b.boot(same, 3),
           "r1_31": sum(x["r31"] >= 1 - EPS for x in rows), "r1_32": sum(x["r32"] >= 1 - EPS for x in rows)}
    lines = ["| Days | Sol 3.1, 3.1 rules: C / Δ | Sol 3.1's play settled under 3.2: C / Δ | Sol 3.2: C / Δ "
             "| C 3.2 − C 3.1 (95% CI) | Δ 3.2 − Δ 3.1 (95% CI) | Sol 3.2 − Sol 3.1's play, both under 3.2: "
             "(P − P')/(P_hind − P_idle) (95% CI) | R 3.1 / 3.2 | R = 1 3.1 / 3.2 |",
             "|---:|---|---|---|---|---|---|---|---|",
             f"| {out['n']} | {out['c31']:.3f} / {out['d31']:+.3f} | {out['c31_32']:.3f} / {out['d31_32']:+.3f} "
             f"| {out['c32']:.3f} / {out['d32']:+.3f} | {statistics.mean(dc):+.3f}{ci(dc)} "
             f"| {statistics.mean(dd):+.3f}{ci(dd)} | {statistics.mean(same):+.3f}{ci(same)} "
             f"| {out['r31']:.3f} / {out['r32']:.3f} | {out['r1_31']} / {out['r1_32']} |"]
    return lines, out


def prior_days(tier: str) -> dict:
    col = json.loads(PRIOR.read_text())["columns"].get(tier) or {}
    return {d["task_id"]: d for d in (col.get("amended") or col.get("primary") or {}).get("days", [])}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The reserves-tier sweep (v3c-pilot-sol).")
    ap.add_argument("--energy", help="The energy-tier sweep (v3c-pilot-sol-energy).")
    ap.add_argument("--amend", nargs="*", default=[], help="Labelled amendment sweeps (unscored runs at 2x cap).")
    ap.add_argument("--showcase", nargs="*", default=[], help="Display-only sweeps.")
    ap.add_argument("--extra-spend", nargs="*", default=[], help="Other sweeps whose spend counts (the smoke).")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args()
    names = [n for n in [*args.extra_spend, args.main, args.energy, *args.amend, *args.showcase] if n]
    out = {"columns": {}, "unscored": {}, "spend_usd": {n: round(b.spend(n), 4) for n in names}}
    amends = {a: load(a) for a in args.amend}
    lines: list[str] = []
    for tier, name in (("reserves", args.main), ("energy", args.energy)):
        if not name:
            continue
        days, unscored = load(name)
        tasks = {r["task_id"]: r for r in hybrid_tasks.pack_rows(json.loads((RUNS / name / "raw" / "sweep.json")
                                                                           .read_text())["pack"])}
        out["unscored"][tier] = unscored
        sets = {"primary": days}
        miss = {u["task_id"] for u in unscored}
        extra = [d for ds, _ in amends.values() for d in ds if d["tier"] == tier and d["task_id"] in miss]
        if extra:
            sets["amended"] = sorted(days + extra, key=lambda d: d["task_id"])
        prior = prior_days(tier)
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
            col = {"headline": {lab: b.headline(x) for lab, x in cells}, "days": [b.strip(d) for d in ds]}
            lines += [f"### {tier} {label}", ""] + b.headline_tables(cells, tier) + [""]
            t = p3.tables([(lab, p3.summary(x)) for lab, x in cells], tier == "reserves")
            lines += t[t.index("") + 1:] + [""]
            if tier == "reserves":
                col["regulation"] = {lab: b.reg_summary(x) for lab, x in cells}
                lines += b.reg_table(cells) + [""]
                dl, col["deployment"] = b.deploy_lines(ds)
                lines += dl + [""]
                rl, col["regup"] = regup(ds, prior)
                lines += [rl, ""]
            fl, col["format"] = format_line(ds)
            m = p3.summary(ds)
            col["v3_summary"] = m
            lines += [fl, "", f"{tier} {label}: check_schedule issues by rule: "
                              f"{p3._counts(m.get('check_issues_by_rule') or {})}; FTP MWh charged by product "
                              f"(regup/regdn/rrs/ecrs/nspin) {p3._by_product(m['ftp_charged_by_product'], '.2f')}; "
                              f"end penalty ${statistics.mean(d['end_penalty_usd'] for d in ds):,.0f} a day on "
                              f"{sum(d['end_penalty_usd'] > EPS for d in ds)} days; error taxonomy "
                              f"{p3._counts(m.get('errors') or {})}.", ""]
            cl, col["vs_3_1"] = compare(ds, tier, prior, tasks)
            if cl:
                lines += [f"{tier} {label}, exploratory: the 3.1 pilot's surviving days, paired (rules changed: "
                          "not a model comparison)", ""] + cl + [""]
            out["columns"][tier][label] = col
    show = []
    for name in args.showcase:
        ds, missing = load(name)
        show += [b.strip(d) for d in ds]
        out["unscored"][name] = missing
        lines += ["Display only: " + ("; ".join(b.showcase_line(d).replace(" / 0.00 excused", "") for d in ds)
                                      or f"unscored: {missing}"), ""]
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
