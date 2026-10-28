"""The rules-4.1 v4 pilot's pre-registered analysis (docs/prereg/v4-pilot-b.md) from the sweeps' replay-verified
Episode JSON v4, results.jsonl and transcripts. Every window carries scripts/pilot_v4.py's fields (R, forecast reading,
DAM gates, play), and on top the cross-version headline (docs/REWARD-SCALES.md): hindsight capture
C = (P - P_idle)/(P_hind - P_idle), unclipped, beside the anchor's C and Delta = C - C_anchor (the episode's
paired_vs_anchor) with its paired CI, each stored reference on C as (P - P_ref)/(P_hind - P_idle), R second with its
R = 1 and beats-anchor shares; the rules-4.0 friction (issued_at blank or malformed, a time refused as after now, AS
hours refused at front-lite); ERCOT's forecast revisions (drift reads, DAM positions changed after one). Exploratory,
labelled: the same counts on the rules-4.0 pilot's Episode JSON and both pilots' C on the windows they share. CIs are
95% bootstrap over windows (10,000 resamples, seed 0), paired for differences."""

import argparse
import json
import re
from pathlib import Path

import pilot_v4 as v4

from agentenv_gridsim import forecast_tasks

REFS = ("naive", "blind", "roll3")
OLD = {"front (main)": "v4-pilot-sol", "front-lite": "v4-pilot-sol-lite"}
ZONED = re.compile(r"(Z|[+-]\d\d:?\d\d)$", re.IGNORECASE)
TIME_ARGS = ("issued_at", "target_hour")
PLAN_TOOLS = ("submit_dam", "commit_schedule", "check_schedule")


def friction(e: dict) -> dict:
    """The rules-4.0 pilot's misuse, call by call: issued_at sent blank or null (refused as malformed in 4.0, the
    latest vintage in 4.1), a time refused as malformed or as after now (4.0's UTC clock time read as CPT), a time sent
    with its UTC offset, a zone name refused, and hours refused because front-lite trades energy only."""
    fc = [s for s in e["steps"] if s["tool"] in v4.FORECAST]
    err = [str((s["output"] or {}).get("error") or "") if isinstance(s["output"], dict) else "" for s in fc]
    args = [s["args"] or {} for s in fc]
    lite_hours = [r for s in e["steps"] if s["tool"] in PLAN_TOOLS and isinstance(s["output"], dict)
                  for r in s["output"].get("refused") or [] if isinstance(r, dict) and r.get("rule") == "not_offered"]
    parse = [r for s in e["steps"] if s["tool"] in PLAN_TOOLS and isinstance(s["output"], dict)
             for r in s["output"].get("refused") or [] if isinstance(r, dict) and r.get("rule") == "parse"]
    return {"blank_issued_at": sum("issued_at" in a and not str(a["issued_at"] or "").strip() for a in args),
            "malformed": sum(m.startswith(tuple(f"{k} must be" for k in TIME_ARGS)) for m in err),
            "after_now": sum("is after now" in m for m in err),
            "zoned_times": sum(bool(ZONED.search(str(a.get(k) or "").strip())) for a in args for k in TIME_ARGS),
            "zone_name": sum(" zones are " in m for m in err),
            "lite_not_offered": len(lite_hours) if e["tier"] == "front-lite" else 0, "parse_refused": len(parse)}


def drift_first(e: dict) -> list[bool]:
    """Per DAM gate: a get_forecast_drift call served at the gate watch before its first submit_dam."""
    out = []
    for d in e["dam"]:
        at = [s for s in e["steps"] if s["watch"] == d["gate_watch"]]
        first = next((i for i, s in enumerate(at) if s["tool"] == "submit_dam"), len(at))
        out.append(any(s["tool"] == "get_forecast_drift" and "error" not in (s["output"] or {}) for s in at[:first]))
    return out


def light(e: dict) -> dict:
    """What both rules versions' Episode JSON give without the pack: C, the anchor's, Delta, each reference's C, R,
    the friction, the drift reads."""
    r = e["references"]
    span = r["p_hind"] - r["p_idle"]
    c = (e["profit_usd"] - r["p_idle"]) / span
    ok = [s for s in e["steps"] if s["tool"] in v4.FORECAST and "error" not in (s["output"] or {})]
    return {"task_id": e["task_id"], "tier": e["tier"], "C": c, "C_anchor": (r["p_anchor"] - r["p_idle"]) / span,
            "delta": e["paired_vs_anchor"], "reward": e["reward"], "beats_anchor": bool(e["beats_anchor"]),
            **{f"C_{k}": (r[f"p_{k}"] - r["p_idle"]) / span for k in REFS},
            **{f"beats_{k}": e["profit_usd"] > r[f"p_{k}"] + v4.EPS for k in REFS},
            "drift_calls": sum(s["tool"] == "get_forecast_drift" for s in ok),
            "forecast_calls": sum(s["tool"] in v4.FORECAST for s in e["steps"]),
            "drift_first": drift_first(e), **friction(e)}


def load(name: str) -> tuple[list[dict], list[dict]]:
    """A sweep's scored windows (pilot_v4's fields with light()'s) and its unscored runs with the anchor's C."""
    ws, unscored = v4.load(name)
    eps = {e["task_id"]: e for e in (json.loads(f.read_text()) for f in (v4.RUNS / name).glob("*.json"))}
    for w in ws:
        w |= light(eps[w["task_id"]])
        for g, first in zip(w["gates"], w["drift_first"], strict=True):
            g["drift_first"] = first
    if unscored:
        spec = json.loads((v4.RUNS / name / "raw" / "sweep.json").read_text())
        rows = {r["task_id"]: r for r in forecast_tasks.pack_rows(spec["pack"])}
        for u in unscored:
            t = rows[u["task_id"]]["refs"][spec["tier"]]
            u["C_anchor"] = (t["p_anchor"] - t["p_idle"]) / (t["p_hind"] - t["p_idle"])
    return ws, unscored


def old(name: str) -> list[dict]:
    return [light(json.loads(f.read_text())) for f in sorted((v4.RUNS / name).glob("*.json"))]


def frictions(ws: list[dict]) -> dict:
    keys = ("blank_issued_at", "malformed", "after_now", "zoned_times", "zone_name", "lite_not_offered",
            "parse_refused")
    return {k: sum(w[k] for w in ws) for k in keys} | {f"{k}_windows": sum(w[k] > 0 for w in ws) for k in keys}


def headline(ws: list[dict], unscored: list[dict] | None = None) -> dict:
    """C with the anchor's and Delta (paired), each reference on C, R second; by label; drift and friction."""
    if not ws:
        return {"n": 0}
    m = v4._mean
    lab = {lb: [w for w in ws if w["label"] == lb] for lb in v4.LABELS}
    gs = [g for w in ws for g in w["gates"]]
    elig = [g for g in gs if g["eligible"]]
    out = {"n": len(ws), "C": m([w["C"] for w in ws]), "C_ci": v4.ci([w["C"] for w in ws]),
           "C_anchor": m([w["C_anchor"] for w in ws]), "delta": m([w["delta"] for w in ws]),
           "delta_ci": v4.ci([w["delta"] for w in ws]), "C_below_0": sum(w["C"] < -v4.EPS for w in ws),
           "C_at_1": sum(w["C"] >= 1 - v4.EPS for w in ws), "R": m([w["reward"] for w in ws]),
           "R_ci": v4.ci([w["reward"] for w in ws]), "R_at_1": m([float(w["reward"] >= 1 - v4.EPS) for w in ws]),
           "beats_anchor": m([float(w["beats_anchor"]) for w in ws])}
    for k in REFS:
        d = [w["C"] - w[f"C_{k}"] for w in ws]
        out |= {f"C_{k}": m([w[f"C_{k}"] for w in ws]), f"delta_{k}": m(d), f"delta_{k}_ci": v4.ci(d),
                f"beats_{k}": m([float(w[f"beats_{k}"]) for w in ws]), f"R_{k}": m([w[k] for w in ws])}
    out["by_label"] = {lb: {"n": len(v), "C": m([w["C"] for w in v]), "C_anchor": m([w["C_anchor"] for w in v]),
                            "delta": m([w["delta"] for w in v]), "delta_ci": v4.ci([w["delta"] for w in v]),
                            "C_blind": m([w["C_blind"] for w in v]),
                            "delta_blind": m([w["C"] - w["C_blind"] for w in v]),
                            "delta_blind_ci": v4.ci([w["C"] - w["C_blind"] for w in v]),
                            "R": m([w["reward"] for w in v])} for lb, v in lab.items()}
    fd, cd = [w["delta"] for w in lab["front"]], [w["delta"] for w in lab["calm"]]
    out["delta_front_minus_calm"] = m(fd) - m(cd) if fd and cd else None
    out["delta_front_minus_calm_ci"] = v4.ci_diff(fd, cd)
    out |= {"drift_calls": m([w["drift_calls"] for w in ws]),
            "windows_with_drift": sum(w["drift_calls"] > 0 for w in ws),
            "gates_drift_first": sum(g["drift_first"] for g in gs if not g["missed"]),
            "kept_gates": sum(not g["missed"] for g in gs), "eligible_gates": len(elig),
            "revised_gates": sum(g["revised"] for g in elig),
            "eligible_drift_first": sum(g["drift_first"] for g in elig),
            "revised_drift_first": sum(g["revised"] and g["drift_first"] for g in elig)}
    out["friction"] = frictions(ws)
    if unscored is not None:
        stops = [u for u in unscored if u["why"] in v4.MODEL_STOPS]
        out["C_with_model_stops_as_0"] = m([w["C"] for w in ws] + [0.0] * len(stops))
        out["delta_with_model_stops_as_0"] = m([w["delta"] for w in ws] + [-u["C_anchor"] for u in stops])
    return out


def compare(new: list[dict], was: list[dict]) -> dict:
    """Exploratory: the rules-4.1 column against the rules-4.0 one, each on its own pack's references; paired on the
    windows both ran."""
    by = {w["task_id"]: w for w in was}
    both = [(w, by[w["task_id"]]) for w in new if w["task_id"] in by]

    def col(ws):
        return {"n": len(ws), "C": v4._mean([w["C"] for w in ws]), "C_anchor": v4._mean([w["C_anchor"] for w in ws]),
                "delta": v4._mean([w["delta"] for w in ws]), "R": v4._mean([w["reward"] for w in ws]),
                "R_at_1": v4._mean([float(w["reward"] >= 1 - v4.EPS) for w in ws]),
                "drift_windows": sum(w["drift_calls"] > 0 for w in ws),
                "forecast_calls": v4._mean([w["forecast_calls"] for w in ws]), "friction": frictions(ws)}

    dc = [a["C"] - b["C"] for a, b in both]
    dd = [a["delta"] - b["delta"] for a, b in both]
    return {"rules_4_1": col(new), "rules_4_0": col(was), "shared": len(both),
            "C_4_1_minus_4_0": v4._mean(dc), "C_4_1_minus_4_0_ci": v4.ci(dc),
            "delta_4_1_minus_4_0": v4._mean(dd), "delta_4_1_minus_4_0_ci": v4.ci(dd),
            "anchor_C_moved": v4._mean([a["C_anchor"] - b["C_anchor"] for a, b in both])}


def side(ci: list[float] | None) -> str:
    if ci is None:
        return "undecided (too few windows)"
    return "above" if ci[0] > 0 else "below" if ci[1] < 0 else "level"


def hypotheses(s: dict, sec: dict, main_ws: list[dict], lite_ws: list[dict]) -> dict:
    """The registered readings on the main column (s: headline(), sec: pilot_v4's summary); H5 also on front-lite."""
    if not s.get("n"):
        return {}
    h = v4.hypotheses(sec)
    f_all, f_main, f_lite = frictions(main_ws + lite_ws), frictions(main_ws), frictions(lite_ws)
    return {"primary_vs_anchor": side(s["delta_ci"]),
            "H1_beats_blind": v4.read(s["delta_blind_ci"]),
            "H2_front_behind_calm": v4.read(None if s["delta_front_minus_calm_ci"] is None else
                                            [-x for x in reversed(s["delta_front_minus_calm_ci"])]),
            "H3a_reads_ercot_and_revisions": h["H3a_reads_ercot_and_revisions"],
            "H3b_revises_dam": h["H3b_revises_dam"], "H4_gates_kept": h["H4_gates_kept"],
            "H5_friction_gone": "supported" if (f_all["malformed_windows"] <= 1 and f_main["after_now_windows"] <= 1
                                                and f_lite["lite_not_offered_windows"] <= 1) else "not supported"}


def _ci(m: dict, key: str, fmt: str = "+.3f") -> str:
    c = m.get(f"{key}_ci")
    return v4._f(m.get(key), fmt) + (f" ({v4._f(c[0], fmt)} to {v4._f(c[1], fmt)})" if c else "")


def c_tables(cells: list[tuple[str, dict]]) -> list[str]:
    f = v4._f
    lines = ["| Column | n | C (95% CI) | Anchor's C | Δ = C − C_anchor (95% CI) | C < 0 | R (95% CI) | R = 1 | "
             "Beats anchor |", "|---|---:|---|---:|---|---:|---|---:|---:|"]
    for name, m in cells:
        if m.get("n"):
            lines.append(f"| {name} | {m['n']} | {_ci(m, 'C', '.3f')} | {f(m['C_anchor'])} | {_ci(m, 'delta')} | "
                         f"{m['C_below_0']} | {_ci(m, 'R', '.3f')} | {f(m['R_at_1'], '.2f')} | "
                         f"{f(m['beats_anchor'], '.2f')} |")
    lines += ["", "| Column | Reference | Its C | C − its C (95% CI) | Sol above it | Its R |",
              "|---|---|---:|---|---:|---:|"]
    for name, m in cells:
        for k in REFS if m.get("n") else ():
            lines.append(f"| {name} | P_{k} | {f(m[f'C_{k}'])} | {_ci(m, f'delta_{k}')} | "
                         f"{f(m[f'beats_{k}'], '.2f')} | {f(m[f'R_{k}'])} |")
    lines += ["", "| Column | Label | n | C | Anchor's C | Δ (95% CI) | P_blind C | C − P_blind C (95% CI) | R |",
              "|---|---|---:|---:|---:|---|---:|---|---:|"]
    for name, m in cells:
        for lb, v in (m.get("by_label") or {}).items():
            if v["n"]:
                lines.append(f"| {name} | {lb} | {v['n']} | {f(v['C'])} | {f(v['C_anchor'])} | {_ci(v, 'delta')} | "
                             f"{f(v['C_blind'])} | {_ci(v, 'delta_blind')} | {f(v['R'])} |")
    lines += ["", "| Column | issued_at blank or null (windows) | Malformed time refused (windows) | After now refused "
              "(windows) | Times sent with an offset | Zone name refused | Front-lite AS hours refused (windows) | "
              "Plan parse refusals |", "|---|---|---|---|---:|---:|---|---:|"]
    for name, m in cells:
        if m.get("n"):
            x = m["friction"]
            lines.append(f"| {name} | {x['blank_issued_at']} ({x['blank_issued_at_windows']}) | {x['malformed']} "
                         f"({x['malformed_windows']}) | {x['after_now']} ({x['after_now_windows']}) | "
                         f"{x['zoned_times']} | {x['zone_name']} | {x['lite_not_offered']} "
                         f"({x['lite_not_offered_windows']}) | {x['parse_refused']} |")
    lines += ["", "| Column | Drift calls a window | Windows with a drift call | Kept gates with a drift read before "
              "the submit | Eligible gates | Revised | Eligible with a drift read first | Revised with one |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, m in cells:
        if m.get("n"):
            lines.append(f"| {name} | {f(m['drift_calls'], '.2f')} | {m['windows_with_drift']} of {m['n']} | "
                         f"{m['gates_drift_first']} of {m['kept_gates']} | {m['eligible_gates']} | "
                         f"{m['revised_gates']} | {m['eligible_drift_first']} | {m['revised_drift_first']} |")
    return lines


def compare_lines(cmp: dict) -> list[str]:
    f = v4._f
    lines = ["| Column | Rules | n | C | Anchor's C | Δ | R | R = 1 | Malformed time (windows) | After now (windows) | "
             "Front-lite AS hours (windows) | Windows with drift | Forecast calls |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|---|---|---:|---:|"]
    for name, c in cmp.items():
        for rules in ("rules_4_0", "rules_4_1"):
            m, x = c[rules], c[rules]["friction"]
            lines.append(f"| {name} | {rules[6:].replace('_', '.')} | {m['n']} | {f(m['C'])} | {f(m['C_anchor'])} | "
                         f"{f(m['delta'], '+.3f')} | {f(m['R'])} | {f(m['R_at_1'], '.2f')} | {x['malformed']} "
                         f"({x['malformed_windows']}) | {x['after_now']} ({x['after_now_windows']}) | "
                         f"{x['lite_not_offered']} ({x['lite_not_offered_windows']}) | {m['drift_windows']} | "
                         f"{f(m['forecast_calls'], '.1f')} |")
    lines.append("")
    for name, c in cmp.items():
        lines.append(f"- {name}, the {c['shared']} windows both pilots ran: C 4.1 − 4.0 "
                     f"{_ci(c, 'C_4_1_minus_4_0')}, Δ 4.1 − 4.0 {_ci(c, 'delta_4_1_minus_4_0')}; the anchor's C moved "
                     f"{f(c['anchor_C_moved'], '+.3f')} (solver 2, V4-P22)")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The pre-registered front-tier sweep (v4b-pilot-sol).")
    ap.add_argument("--lite", help="The front-lite sweep (v4b-pilot-sol-lite).")
    ap.add_argument("--smoke", help="The smoke sweep (v4b-pilot-sol-smoke), one line a window.")
    ap.add_argument("--display", nargs="*", default=[], help="The display sweeps (fern-0124, heather-0114).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    main_ws, main_un = load(args.main)
    lite_ws, lite_un = load(args.lite) if args.lite else ([], [])
    cells = [("front (main)", v4.summary(main_ws, main_un))] + ([("front-lite", v4.summary(lite_ws, lite_un))]
                                                                if args.lite else [])
    heads = [("front (main)", headline(main_ws, main_un))] + ([("front-lite", headline(lite_ws, lite_un))]
                                                              if args.lite else [])
    cmp = {name: compare(ws, old(OLD[name])) for name, ws in (("front (main)", main_ws), ("front-lite", lite_ws))
           if ws and (v4.RUNS / OLD[name]).is_dir()}
    out = {"headline": dict(heads), "secondary": dict(cells),
           "hypotheses": hypotheses(heads[0][1], cells[0][1], main_ws, lite_ws), "main_windows": main_ws,
           "main_unscored": main_un, "lite_windows": lite_ws, "lite_unscored": lite_un, "rules_4_0_comparison": cmp,
           "spend": {args.main: v4.spend(args.main)}}
    if args.lite:
        out["spend"][args.lite] = v4.spend(args.lite)
    for key, names in (("smoke", [args.smoke] if args.smoke else []), ("display", args.display)):
        out[key], out[f"{key}_unscored"] = [], []
        for name in names:
            got, un = load(name)
            out[key] += got
            out[f"{key}_unscored"] += un
            out["spend"][name] = v4.spend(name)
    out["spend_total"] = sum(out["spend"].values())
    print("\n".join(c_tables(heads)))
    print("\nSecondary (as the rules-4.0 pilot):\n")
    print("\n".join(v4.tables(cells)))
    print("\nHypotheses:", json.dumps(out["hypotheses"]))
    if cmp:
        print("\nExploratory, rules 4.0 against 4.1:\n")
        print("\n".join(compare_lines(cmp)))
    for key in ("smoke", "display"):
        for w in out[key]:
            print(f"{key}: {v4.line(w)}; C {v4._f(w['C'])} (anchor {v4._f(w['C_anchor'])}), Δ {v4._f(w['delta'])}")
    for key in ("main_unscored", "lite_unscored", "smoke_unscored", "display_unscored"):
        for u in out.get(key) or []:
            print(f"unscored ({key}): {u}")
    print("spend:", json.dumps({k: round(v, 4) for k, v in out["spend"].items()}), f"total ${out['spend_total']:.2f}")
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
