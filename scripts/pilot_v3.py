"""The v3 pilot's pre-registered analysis (docs/prereg/v3-pilot.md) from the sweeps' replay-verified Episode JSON v3
and results.jsonl: R on the anchor scale against idle, AS-hog, the energy-only MILP and v2 energy-only on the same
days, hindsight capture, AS share and AS revenue against the anchor's, the DA AS book by product, failure-to-provide
charged and excused by product, under-reserved days, refusals by rule, the re-plan rate, beats-anchor, tokens, cost
and turns; the reserves-tier main column overall and by AS stratum, the energy-tier column apart, the showcase day
display only. CIs are 95% bootstrap over days (2,000 resamples, seed 0), paired for differences."""

import argparse
import json
import random
import statistics
from collections import Counter
from pathlib import Path

from agentenv_gridsim import hybrid_tasks
from agentenv_gridsim.sweep import slug
from gridsim_core.grade import reward_value
from gridsim_core.hybrid import PRODUCTS, UP, Session

RUNS = Path("results/runs")
EPS = 1e-6
BOOT = 2000
STRATA = ("low", "mid", "high")
RESERVE_RULES = ("reserve_up", "reserve_dn")


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def ci(xs: list, seed: int = 0) -> list[float] | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(xs, k=len(xs))) for _ in range(BOOT))
    return [means[int(0.025 * BOOT)], means[int(0.975 * BOOT)]]


def capture(p: float, p_idle: float, p_hind: float | None) -> float | None:
    return (p - p_idle) / (p_hind - p_idle) if p_hind is not None and p_hind - p_idle > EPS else None


def replayed(e: dict, task: dict) -> Session:
    """The episode's calls on a fresh Session, each watch's notices delivered after the advance that opens it."""
    s = Session(task, e["tier"])
    for step in e["steps"]:
        if step["tool"] not in Session.TOOLS:
            continue
        out = json.loads(s.call(step["tool"], step["args"]))
        if step["tool"] == "advance" and "watch" in out:
            s.deliver_watch_notices()
    if not s.done:
        s.end_day()
    if abs(s.grade()["reward"] - e["reward"]) > EPS:
        raise SystemExit(f"{e['task_id']}: the replay scores {s.grade()['reward']}, the episode {e['reward']}")
    return s


def day(e: dict, row: dict, task: dict) -> dict:
    """One scored day's pilot fields from its Episode JSON, its results row and its pack row."""
    r, tier = e["references"], e["tier"]
    p, p_idle, p_anchor = e["profit_usd"], r["p_idle"], r["p_anchor"]
    b = r.get("baselines") or {}
    s = replayed(e, task)
    charged = {k: sum(x["charged"].get(k, 0.0) for x in s.rows) for k in PRODUCTS}
    excused = {k: sum(x["excused_mw"].get(k, 0.0) for x in s.rows) for k in PRODUCTS}
    refused = [x for st in e["steps"] if st["tool"] == "commit_schedule" for x in st["output"].get("refused") or []]
    issues = [x for st in e["steps"] if st["tool"] == "check_schedule" for x in st["output"].get("issues") or []]
    reserve_refused = {k: sum(x["rule"] in RESERVE_RULES and x["field"] == k for x in refused) for k in PRODUCTS}
    later = len(e["watches"]) - 1
    replans = {c["watch"] for c in e["commits"] if c["committed"] and c["watch"] >= 1}
    da = e.get("da") or {}
    anchor_book = (r.get("anchor") or {}).get("book") or {}
    as_usd = e["cash"]["as_da"] + e["cash"]["as_rt"]
    anchor_as = (r.get("anchor") or {}).get("as_usd")
    out = {"task_id": e["task_id"], "tier": tier, "stratum": task["tags"]["as_stratum"],
           "point": task["settlement_point"], "date": task["date"], "notice_day": task["tags"]["notice_day"],
           "reward": e["reward"], "raw_ratio": e["raw_ratio"], "profit_usd": p, "p_idle": p_idle,
           "p_anchor": p_anchor, "p_hind": r.get("p_hind"),
           "capture": capture(p, p_idle, r.get("p_hind")), "anchor_capture": capture(p_anchor, p_idle, r.get("p_hind")),
           "beats_anchor": bool(e["beats_anchor"]),
           "v2_energy": (b.get("v2_energy") or {}).get("reward"),
           "beats_v2_energy": p > (b.get("v2_energy") or {}).get("profit", float("inf")) + EPS,
           "as_share": row.get("as_share"), "as_usd": as_usd, "anchor_as_usd": anchor_as,
           "as_vs_anchor": as_usd / anchor_as if anchor_as and anchor_as > EPS else None,
           "da_mwh": {k: sum(da.get(k) or [0.0]) for k in PRODUCTS},
           "anchor_da_mwh": {k: sum(anchor_book.get(k) or [0.0]) for k in PRODUCTS},
           "ftp_charged": charged, "ftp_excused": excused,
           "ftp_mwh_charged": sum(charged.values()), "ftp_mwh_excused": sum(excused.values()),
           "ftp_usd": e["cash"]["ftp"], "excused_usd": e["cash"]["excused"],
           "reserve_refused": reserve_refused,
           "under_reserved": {k: charged[k] > EPS or reserve_refused[k] > 0 for k in PRODUCTS},
           "refused_rules": dict(Counter(x["rule"] for x in refused)),
           "check_rules": dict(Counter(x["rule"] for x in issues)),
           "refused_commits": sum(bool(c["refused"]) for c in e["commits"]),
           "governor_hours": row.get("governor_hours"), "end_short_mwh": s.grade()["end_short_mwh"],
           "later_watches": later, "replan_watches": len(replans),
           "anchor_replans": max(((r.get("anchor") or {}).get("commits") or 1) - 1, 0),
           "commits": sum(bool(c["committed"]) for c in e["commits"]), "planning_calls": row.get("checks"),
           "finished": row.get("end_reason") == "done", "audit_ok": e["audit"]["ok"],
           "cost_usd": row.get("priced_cost_usd") if row.get("priced_cost_usd") is not None else row.get("cost_usd"),
           "turns": row.get("turns"), "input_tokens": row.get("input_tokens"),
           "output_tokens": row.get("output_tokens"), "cached_tokens": row.get("cached_tokens"),
           "errors": row.get("errors") or []}
    if tier != "energy":
        out |= {"as_hog": (b.get("as_hog") or {}).get("reward"),
                "beats_as_hog": p > (b.get("as_hog") or {}).get("profit", float("inf")) + EPS,
                "energy_only": reward_value(r["p_energy_only"], p_idle, p_anchor)
                if r.get("p_energy_only") is not None else None,
                "beats_energy_only": r.get("p_energy_only") is not None and p > r["p_energy_only"] + EPS}
    return out


def summary(days: list[dict]) -> dict:
    if not days:
        return {"n": 0}

    def m(key):
        return _mean([d.get(key) for d in days])

    def rate(key):
        return _mean([float(bool(d.get(key))) for d in days if key in d])

    def diff(key):
        return [d["reward"] - d[key] for d in days if d.get(key) is not None]

    later = sum(d["later_watches"] for d in days)
    out = {"n": len(days), "reward": m("reward"), "reward_ci": ci([d["reward"] for d in days]),
           "reward_at_1": _mean([float(d["reward"] >= 1 - EPS) for d in days]),
           "capture": m("capture"), "capture_ci": ci([d["capture"] for d in days]),
           "anchor_capture": m("anchor_capture"),
           "capture_minus_anchor": _mean([d["capture"] - d["anchor_capture"] for d in days
                                          if d["capture"] is not None and d["anchor_capture"] is not None]),
           "capture_minus_anchor_ci": ci([d["capture"] - d["anchor_capture"] for d in days
                                          if d["capture"] is not None and d["anchor_capture"] is not None]),
           "beats_anchor": rate("beats_anchor"), "v2_energy": m("v2_energy"),
           "reward_minus_v2_energy": _mean(diff("v2_energy")), "reward_minus_v2_energy_ci": ci(diff("v2_energy")),
           "beats_v2_energy": rate("beats_v2_energy"),
           "as_share": m("as_share"), "as_usd": m("as_usd"), "anchor_as_usd": m("anchor_as_usd"),
           "as_vs_anchor_median": statistics.median([d["as_vs_anchor"] for d in days if d["as_vs_anchor"] is not None])
           if any(d["as_vs_anchor"] is not None for d in days) else None,
           "da_mwh": {k: _mean([d["da_mwh"][k] for d in days]) for k in PRODUCTS},
           "anchor_da_mwh": {k: _mean([d["anchor_da_mwh"][k] for d in days]) for k in PRODUCTS},
           "ftp_mwh_charged": m("ftp_mwh_charged"), "ftp_mwh_excused": m("ftp_mwh_excused"),
           "ftp_charged_by_product": {k: sum(d["ftp_charged"][k] for d in days) for k in PRODUCTS},
           "ftp_excused_by_product": {k: sum(d["ftp_excused"][k] for d in days) for k in PRODUCTS},
           "days_ftp_charged": sum(d["ftp_mwh_charged"] > EPS for d in days),
           "under_reserved_days": sum(any(d["under_reserved"][k] for k in UP + ("regdn",)) for d in days),
           "under_reserved_days_by_product": {k: sum(d["under_reserved"][k] for d in days) for k in PRODUCTS},
           "refused_rows_by_rule": dict(sum((Counter(d["refused_rules"]) for d in days), Counter()).most_common()),
           "check_issues_by_rule": dict(sum((Counter(d["check_rules"]) for d in days), Counter()).most_common()),
           "refused_commits": sum(d["refused_commits"] for d in days),
           "days_with_refusal": sum(d["refused_commits"] > 0 for d in days),
           "governor_hours": m("governor_hours"), "end_short_days": sum(d["end_short_mwh"] > EPS for d in days),
           "replan_rate": sum(d["replan_watches"] for d in days) / later if later else None,
           "replanned_days": _mean([float(d["replan_watches"] > 0) for d in days]),
           "anchor_replan_rate": sum(min(d["anchor_replans"], d["later_watches"]) for d in days) / later if later
           else None,
           "finished": rate("finished"), "audit_failures": sum(not d["audit_ok"] for d in days),
           "usd_per_episode": m("cost_usd"), "turns": m("turns"), "input_tokens": m("input_tokens"),
           "output_tokens": m("output_tokens"), "cached_tokens": m("cached_tokens"),
           "errors": dict(sum((Counter(d["errors"]) for d in days), Counter()).most_common())}
    if any("as_hog" in d for d in days):
        out |= {"as_hog": m("as_hog"), "reward_minus_as_hog": _mean(diff("as_hog")),
                "reward_minus_as_hog_ci": ci(diff("as_hog")), "beats_as_hog": rate("beats_as_hog"),
                "energy_only": m("energy_only"), "reward_minus_energy_only": _mean(diff("energy_only")),
                "reward_minus_energy_only_ci": ci(diff("energy_only")), "beats_energy_only": rate("beats_energy_only")}
    return out


def load(name: str) -> tuple[list[dict], list[dict]]:
    """A sweep's scored days (from its Episode JSON) and its runs that ended unscored."""
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
            days.append(day(json.loads(path.read_text()), scored, tasks[task_id]))
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return days, unscored


def spend(name: str) -> float:
    rows = (RUNS / name / "raw" / "results.jsonl").read_text().splitlines()
    return sum(json.loads(x).get("cost_usd") or 0.0 for x in rows if x.strip())


def _f(x, fmt: str = ".3f") -> str:
    return "–" if x is None else format(x, fmt)


def _ci(m: dict, key: str) -> str:
    c = m.get(key + "_ci")
    return _f(m.get(key)) + (f" ({_f(c[0])} to {_f(c[1])})" if c else "")


def _counts(c: dict) -> str:
    return ", ".join(f"{k} {v}" for k, v in c.items()) or "none"


def _by_product(c: dict, fmt: str = ".1f") -> str:
    return " / ".join(_f(c[k], fmt) for k in PRODUCTS)


def tables(cells: list[tuple[str, dict]], reserves: bool) -> list[str]:
    """The scores against the baselines, then AS and reserves, then how the model played."""
    if reserves:
        scores = ["| Set | Days | R (95% CI) | R = 1 | AS-hog R | R − AS-hog (95% CI) | Energy-only MILP R "
                  "| R − energy-only (95% CI) | v2 energy-only R | Capture (95% CI) | Anchor capture "
                  "| Capture − anchor (95% CI) | Beats anchor | Beats energy-only | Beats AS-hog |",
                  "|---|---:|---|---:|---:|---|---:|---|---:|---|---:|---|---:|---:|---:|"]
    else:
        scores = ["| Set | Days | R (95% CI) | R = 1 | v2 energy-only R | R − v2 energy-only (95% CI) "
                  "| Capture (95% CI) | Anchor capture | Capture − anchor (95% CI) | Beats anchor "
                  "| Beats v2 energy-only |", "|---|---:|---|---:|---:|---|---|---:|---|---:|---:|"]
    reserve = ["| Set | Days | AS share | AS $/day | Anchor AS $/day | AS $ ÷ anchor's (median) "
               "| DA AS MWh regup/regdn/rrs/ecrs/nspin | Anchor's | FTP MWh charged | FTP MWh excused "
               "| Days FTP charged | Under-reserved days (regup/regdn/rrs/ecrs/nspin) | Governor h/day "
               "| End short days |", "|---|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|"]
    play = ["| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits "
            "| Refused rows by rule | Audit failures | Input tok | Output tok | Cached tok | $/episode | Turns |",
            "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for label, m in cells:
        if not m["n"]:
            scores.append(f"| {label} | 0 |" + " – |" * (13 if reserves else 9))
            reserve.append(f"| {label} | 0 |" + " – |" * 12)
            play.append(f"| {label} | 0 |" + " – |" * 12)
            continue
        if reserves:
            scores.append(" | ".join([
                f"| {label}", str(m["n"]), _ci(m, "reward"), _f(m["reward_at_1"]), _f(m["as_hog"]),
                _ci(m, "reward_minus_as_hog"), _f(m["energy_only"]), _ci(m, "reward_minus_energy_only"),
                _f(m["v2_energy"]), _ci(m, "capture"), _f(m["anchor_capture"]), _ci(m, "capture_minus_anchor"),
                _f(m["beats_anchor"]), _f(m["beats_energy_only"]), _f(m["beats_as_hog"])]) + " |")
        else:
            scores.append(" | ".join([
                f"| {label}", str(m["n"]), _ci(m, "reward"), _f(m["reward_at_1"]), _f(m["v2_energy"]),
                _ci(m, "reward_minus_v2_energy"), _ci(m, "capture"), _f(m["anchor_capture"]),
                _ci(m, "capture_minus_anchor"), _f(m["beats_anchor"]), _f(m["beats_v2_energy"])]) + " |")
        reserve.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["as_share"]), _f(m["as_usd"], ",.0f"), _f(m["anchor_as_usd"], ",.0f"),
            _f(m["as_vs_anchor_median"]), _by_product(m["da_mwh"]), _by_product(m["anchor_da_mwh"]),
            _f(m["ftp_mwh_charged"], ".2f"), _f(m["ftp_mwh_excused"], ".2f"), str(m["days_ftp_charged"]),
            f"{m['under_reserved_days']} ({_by_product(m['under_reserved_days_by_product'], 'd')})",
            _f(m["governor_hours"], ".2f"), str(m["end_short_days"])]) + " |")
        play.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["replan_rate"]), _f(m["replanned_days"]), _f(m["anchor_replan_rate"]),
            _f(m["finished"]), f"{m['refused_commits']} on {m['days_with_refusal']} days",
            _counts(m["refused_rows_by_rule"]), str(m["audit_failures"]), _f(m["input_tokens"], ",.0f"),
            _f(m["output_tokens"], ",.0f"), _f(m["cached_tokens"], ",.0f"),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}", _f(m["turns"], ".1f")]) + " |")
    return scores + [""] + reserve + [""] + play


def showcase_line(d: dict) -> str:
    base = (f"AS-hog {_f(d.get('as_hog'))}, energy-only {_f(d.get('energy_only'))}, " if d["tier"] != "energy"
            else "") + f"v2 energy-only {_f(d['v2_energy'])}"
    return (f"{d['task_id']} ({d['tier']}): R {_f(d['reward'])} ({base}), capture {_f(d['capture'])} (anchor "
            f"{_f(d['anchor_capture'])}), profit ${d['profit_usd']:,.0f} (idle ${d['p_idle']:,.0f}, anchor "
            f"${d['p_anchor']:,.0f}, hindsight ${d['p_hind']:,.0f}), AS share {_f(d['as_share'])}, FTP "
            f"{d['ftp_mwh_charged']:.2f} MWh charged / {d['ftp_mwh_excused']:.2f} excused, refused rows "
            f"{_counts(d['refused_rules'])}, re-planned {d['replan_watches']} of {d['later_watches']} later watches, "
            f"${d['cost_usd']:.4f}, {d['turns']} turns")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The pre-registered reserves-tier sweep (v3-pilot-sol).")
    ap.add_argument("--energy", help="The energy-tier sweep (v3-pilot-sol-energy).")
    ap.add_argument("--amend", nargs="*", default=[],
                    help="The labelled amendment sweeps: unscored runs again at the $2.00 cap.")
    ap.add_argument("--showcase", nargs="*", default=[], help="The showcase day's sweeps (display only).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    amends = {a: load(a) for a in args.amend}
    out = {"columns": {}, "unscored": {}, "spend_usd": {n: round(spend(n), 4) for n in
                                                         [args.main, args.energy, *args.amend, *args.showcase] if n}}
    lines: list[str] = []
    for col, name in (("reserves", args.main), ("energy", args.energy)):
        if not name:
            continue
        days, unscored = load(name)
        sets = {"primary": days}
        extra = [d for a, (ds, _) in amends.items() if json.loads(
            (RUNS / a / "raw" / "sweep.json").read_text())["tier"] == col for d in ds]
        if extra:
            sets["amended"] = days + [d for d in extra if d["task_id"] not in {x["task_id"] for x in days}]
        out["unscored"][col] = unscored
        out["columns"][col] = {}
        for label, ds in sets.items():
            cells = [(f"{col} {label}: all", summary(ds))]
            if col == "reserves":
                cells += [(f"{col} {label}: {s} AS", summary([d for d in ds if d["stratum"] == s])) for s in STRATA]
                cells += [(f"{col} {label}: notice days", summary([d for d in ds if d["notice_day"]])),
                          (f"{col} {label}: quiet days", summary([d for d in ds if not d["notice_day"]]))]
            out["columns"][col][label] = {lab: m for lab, m in cells} | {"days": ds}
            lines += tables(cells, col == "reserves") + [""]
            m = cells[0][1]
            lines += [f"{col} {label}: check_schedule issues by rule: {_counts(m.get('check_issues_by_rule') or {})}; "
                      f"FTP MWh charged by product (regup/regdn/rrs/ecrs/nspin) "
                      f"{_by_product(m.get('ftp_charged_by_product') or dict.fromkeys(PRODUCTS, 0.0), '.2f')}, "
                      f"excused {_by_product(m.get('ftp_excused_by_product') or dict.fromkeys(PRODUCTS, 0.0), '.2f')}; "
                      f"error taxonomy {_counts(m.get('errors') or {})}.", ""]
    show = []
    for name in args.showcase:
        ds, missing = load(name)
        show += ds
        out["unscored"][name] = missing
        lines += ["Showcase (display only): " + ("; ".join(showcase_line(d) for d in ds) or f"unscored: {missing}"),
                  ""]
    out["showcase"] = show
    unscored = [f"{u['task_id']} ({c}: {u['why']}, {u['attempts']} attempts)" for c, us in out["unscored"].items()
                for u in us]
    lines += ["Unscored: " + ("; ".join(unscored) or "none") + ".",
              "Spend: " + ", ".join(f"{n} ${v:.2f}" for n, v in out["spend_usd"].items())
              + f"; total ${sum(out['spend_usd'].values()):.2f}."]
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
