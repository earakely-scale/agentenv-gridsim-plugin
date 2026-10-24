"""The v4 pilot's pre-registered analysis (docs/prereg/v4-pilot.md) from the sweeps' replay-verified Episode JSON v4,
results.jsonl and transcripts: R on the P_roll anchor scale against P_blind, P_naive and P_roll3 on the same windows,
r_hind, the paired (P - P_roll)/(P_hind - P_idle), hindsight capture, both by label (front, calm); forecast reading
(calls by tool and kind, ERCOT's own load/wind/solar, revisions, the forecast budget), the DAM gates (missed, submits,
reads before the first submit, revisions of Sol's own plan at the gate, the PV DA share, the harness's nudges), play
(refusals, FTP, governor, re-plans, turns, cost); the hypotheses read by their registered rules. The front-tier main
column first, the front-lite column apart, the smoke and display windows one line each. CIs are 95% bootstrap over
windows (10,000 resamples, seed 0), paired for differences, resampled within each label for front minus calm."""

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import numpy as np

from agentenv_gridsim import forecast_tasks
from agentenv_gridsim.sweep import slug

RUNS = Path("results/runs")
EPS = 1e-6
BOOT = 10_000
LABELS = ("front", "calm")
FORECAST = ("get_forecast", "get_forecast_drift")
KINDS = ("load", "wind", "solar", "weather", "price", "alerts")
ERCOT_KINDS = ("load", "wind", "solar")
GATE_NUDGE = "Not sent: this watch is a DAM gate"
MODEL_STOPS = ("cost_cap", "provider_refused")
REVISED_SHARE_OF_P = 0.10


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return statistics.mean(xs) if xs else None


def ci(xs: list, seed: int = 0) -> list[float] | None:
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    a = np.asarray(xs, dtype=float)
    means = np.sort(a[np.random.default_rng(seed).integers(0, len(a), (BOOT, len(a)))].mean(axis=1))
    return [float(means[int(0.025 * BOOT)]), float(means[int(0.975 * BOOT)])]


def ci_diff(xs: list, ys: list, seed: int = 0) -> list[float] | None:
    """The 95% bootstrap interval of mean(xs) - mean(ys), each resampled on its own."""
    if len(xs) < 2 or len(ys) < 2:
        return None
    rng = np.random.default_rng(seed)
    a, b = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    d = np.sort(a[rng.integers(0, len(a), (BOOT, len(a)))].mean(axis=1)
                - b[rng.integers(0, len(b), (BOOT, len(b)))].mean(axis=1))
    return [float(d[int(0.025 * BOOT)]), float(d[int(0.975 * BOOT)])]


def capture(p: float, p_idle: float, p_hind: float | None) -> float | None:
    return (p - p_idle) / (p_hind - p_idle) if p_hind is not None and p_hind - p_idle > EPS else None


def read(rule_ci: list[float] | None) -> str:
    if rule_ci is None:
        return "undecided (too few windows)"
    return "supported" if rule_ci[0] > 0 else "refuted" if rule_ci[1] < 0 else "undecided"


def nudges(raw: Path, row: dict) -> int | None:
    """Advance calls the harness answered with the gate-open nudge, from the run's transcript."""
    if not row.get("transcript") or not (raw / row["transcript"]).is_file():
        return None
    t = json.loads((raw / row["transcript"]).read_text())
    msgs = t.get("messages") or (t.get("payload") or {}).get("messages") or []
    return sum(m.get("role") == "tool" and GATE_NUDGE in str(m.get("content")) for m in msgs)


def gates(e: dict, p_mw: float) -> list[dict]:
    """Each DAM gate: missed, submits, the PV DA share, whether a forecast call came before the first submit at the
    gate watch, and for the days after the first whether the accepted DAM battery position differs from Sol's own
    book for that day as it stood before the gate watch by at least 10% of P in some accepted hour."""
    steps = e["steps"]
    out = []
    for k, d in enumerate(e["dam"]):
        g = d["gate_watch"]
        at = [s for s in steps if s["watch"] == g]
        first = next((i for i, s in enumerate(at) if s["tool"] == "submit_dam"), None)
        read_before = first is not None and any(
            s["tool"] in FORECAST and "error" not in (s["output"] or {}) for s in at[:first])
        prior = None
        for s in steps:
            o = s["output"] if isinstance(s["output"], dict) else {}
            if s["watch"] < g and "error" not in o and isinstance(o.get("book"), dict):
                prior = o["book"]["energy"][24 * k:24 * k + 24]
        accepted = set(d["accepted"] or [])
        battery = [x - pv for x, pv in zip(d["x_da_mw"] or [0.0] * 24, d["pv_da_mw"] or [0.0] * 24, strict=True)]
        planned = prior is not None and any(abs(x) > EPS for x in prior)
        delta = max((abs(battery[h] - prior[h]) for h in range(24) if h in accepted), default=0.0) if planned else None
        out.append({"day": d["day"], "k": k, "gate_watch": g, "missed": bool(d["missed"]),
                    "submits": d["submits"], "pv_da_share": d["pv_da_share"], "read_before_submit": read_before,
                    "eligible": k >= 1 and planned and bool(accepted),
                    "revised": k >= 1 and planned and bool(accepted) and delta >= REVISED_SHARE_OF_P * p_mw - EPS,
                    "max_delta_mw": delta})
    return out


def window(e: dict, row: dict, task: dict, raw: Path) -> dict:
    """One scored window's pilot fields from its Episode JSON, its results row and its pack row."""
    r = e["references"]
    p, p_idle, p_anchor, p_hind = e["profit_usd"], r["p_idle"], r["p_anchor"], r["p_hind"]
    b = r.get("baselines") or {}
    steps = e["steps"]
    fc = [s for s in steps if s["tool"] in FORECAST]
    ok = [s for s in fc if "error" not in (s["output"] or {})]
    by = Counter((s["tool"], (s["args"] or {}).get("kind")) for s in ok)
    left0 = {s["watch"] for s in fc if (s["output"] or {}).get("forecast_calls_left") == 0}
    opened = len({s["watch"] for s in steps})
    later = max(opened - 1, 0)
    replans = {c["watch"] for c in e["commits"] if c["committed"] and c["watch"] >= 1}
    gs = gates(e, task["site"]["bess"]["p_mw"])
    a_cap = capture(p_anchor, p_idle, p_hind)
    return {"task_id": e["task_id"], "tier": e["tier"], "label": task["tags"].get("label"), "source": e.get("source"),
            "point": task["settlement_point"], "d1": task["d1"], "forecast_bust": task["tags"].get("forecast_bust"),
            "reward": e["reward"], "r_hind": e["r_hind"], "paired": e["paired_vs_anchor"],
            "beats_anchor": bool(e["beats_anchor"]), "profit_usd": p, "p_idle": p_idle, "p_anchor": p_anchor,
            "p_hind": p_hind, "capture": capture(p, p_idle, p_hind), "anchor_capture": a_cap,
            "anchor_r_hind": None if a_cap is None else min(1.0, max(0.0, 0.2 + 0.8 * a_cap)),
            **{name: (b.get(name) or {}).get("reward") for name in ("naive", "blind", "roll3")},
            "forecast_calls": len(fc), "forecast_ok": len(ok), "forecast_refused": len(fc) - len(ok),
            "get_forecast": {k: by[("get_forecast", k)] for k in KINDS},
            "drift": {k: by[("get_forecast_drift", k)] for k in KINDS},
            "ercot_calls": sum(by[(t, k)] for t in FORECAST for k in ERCOT_KINDS),
            "drift_calls": sum(v for (t, _), v in by.items() if t == "get_forecast_drift"),
            "issued_at_calls": sum(bool((s["args"] or {}).get("issued_at")) for s in ok),
            "watches_with_forecast": len({s["watch"] for s in ok}), "watches": opened,
            "forecast_budget_out": len(left0),
            "gates": gs, "dam_missed": sum(g["missed"] for g in gs),
            "submits": sum(g["submits"] for g in gs), "pv_share_below_1": sum(
                g["pv_da_share"] is not None and g["pv_da_share"] < 1 - EPS for g in gs if not g["missed"]),
            "gate_nudges": nudges(raw, row),
            "refusals": row.get("refusals"), "ftp_mwh_charged": row.get("ftp_mwh_charged"),
            "governor_hours": row.get("governor_hours"), "end_short_mwh": row.get("end_short_mwh"),
            "as_usd": row.get("as_usd"), "anchor_as_usd": (r.get("roll") or {}).get("as_usd"),
            "commits": row.get("commits"), "anchor_commits": (r.get("roll") or {}).get("commits"),
            "replan_watches": len(replans), "later_watches": later,
            "end_reason": row.get("end_reason"), "finished": row.get("end_reason") == "done",
            "turns": row.get("turns"), "cost_usd": row.get("priced_cost_usd") if row.get("priced_cost_usd")
            is not None else row.get("cost_usd"), "input_tokens": row.get("input_tokens"),
            "output_tokens": row.get("output_tokens"), "cached_tokens": row.get("cached_tokens"),
            "audit_ok": e["audit"]["ok"], "errors": row.get("errors") or [], "wall_seconds": row.get("wall_seconds")}


def summary(ws: list[dict], unscored: list[dict] | None = None) -> dict:
    if not ws:
        return {"n": 0}

    def m(key):
        return _mean([w.get(key) for w in ws])

    def diff(key):
        return [w["reward"] - w[key] for w in ws if w.get(key) is not None]

    lab = {lb: [w for w in ws if w["label"] == lb] for lb in LABELS}
    gs = [g for w in ws for g in w["gates"]]
    elig = [g for g in gs if g["eligible"]]
    later = sum(w["later_watches"] for w in ws)
    out = {"n": len(ws), "reward": m("reward"), "reward_ci": ci([w["reward"] for w in ws]),
           "reward_at_1": _mean([float(w["reward"] >= 1 - EPS) for w in ws]),
           "r_hind": m("r_hind"), "r_hind_ci": ci([w["r_hind"] for w in ws]), "anchor_r_hind": m("anchor_r_hind"),
           "paired": m("paired"), "paired_ci": ci([w["paired"] for w in ws]),
           "capture": m("capture"), "anchor_capture": m("anchor_capture"),
           "beats_anchor": _mean([float(w["beats_anchor"]) for w in ws])}
    for name in ("blind", "naive", "roll3"):
        out |= {name: m(name), f"reward_minus_{name}": _mean(diff(name)), f"reward_minus_{name}_ci": ci(diff(name)),
                f"beats_{name}": _mean([float(w["reward"] > w[name] + EPS) for w in ws if w.get(name) is not None])}
    out["by_label"] = {lb: {"n": len(v), "reward": _mean([w["reward"] for w in v]),
                            "reward_ci": ci([w["reward"] for w in v]), "r_hind": _mean([w["r_hind"] for w in v]),
                            "paired": _mean([w["paired"] for w in v]), "paired_ci": ci([w["paired"] for w in v]),
                            "blind": _mean([w["blind"] for w in v]),
                            "reward_minus_blind": _mean([w["reward"] - w["blind"] for w in v])}
                       for lb, v in lab.items()}
    out["paired_front_minus_calm"] = (None if not (lab["front"] and lab["calm"]) else
                                      _mean([w["paired"] for w in lab["front"]])
                                      - _mean([w["paired"] for w in lab["calm"]]))
    out["paired_front_minus_calm_ci"] = ci_diff([w["paired"] for w in lab["front"]],
                                                [w["paired"] for w in lab["calm"]])
    out |= {"forecast_calls": m("forecast_calls"), "forecast_refused": m("forecast_refused"),
            "get_forecast": {k: _mean([w["get_forecast"][k] for w in ws]) for k in KINDS},
            "drift": {k: _mean([w["drift"][k] for w in ws]) for k in KINDS},
            "windows_with_ercot_call": _mean([float(w["ercot_calls"] > 0) for w in ws]),
            "windows_with_drift_call": _mean([float(w["drift_calls"] > 0) for w in ws]),
            "ercot_calls": m("ercot_calls"), "drift_calls": m("drift_calls"), "issued_at_calls": m("issued_at_calls"),
            "watch_share_with_forecast": sum(w["watches_with_forecast"] for w in ws) / sum(w["watches"] for w in ws),
            "windows_budget_out": _mean([float(w["forecast_budget_out"] > 0) for w in ws]),
            "gates": len(gs), "dam_missed": sum(g["missed"] for g in gs),
            "windows_with_missed_gate": sum(w["dam_missed"] > 0 for w in ws),
            "submits_per_gate": _mean([g["submits"] for g in gs]),
            "gates_read_before_submit": _mean([float(g["read_before_submit"]) for g in gs if not g["missed"]]),
            "eligible_gates": len(elig), "revised_gates": sum(g["revised"] for g in elig),
            "revised_share": _mean([float(g["revised"]) for g in elig]),
            "revised_read_before": _mean([float(g["read_before_submit"]) for g in elig if g["revised"]]),
            "pv_share_below_1_gates": sum(w["pv_share_below_1"] for w in ws),
            "gate_nudges": sum(w["gate_nudges"] or 0 for w in ws),
            "refusals": m("refusals"), "ftp_mwh_charged": m("ftp_mwh_charged"),
            "governor_hours": m("governor_hours"),
            "end_short_windows": sum((w["end_short_mwh"] or 0) > EPS for w in ws),
            "as_usd": m("as_usd"), "anchor_as_usd": m("anchor_as_usd"),
            "commits": m("commits"), "anchor_commits": m("anchor_commits"),
            "replan_rate": sum(w["replan_watches"] for w in ws) / later if later else None,
            "finished": _mean([float(w["finished"]) for w in ws]), "audit_failures": sum(not w["audit_ok"] for w in ws),
            "end_reasons": dict(Counter(w["end_reason"] for w in ws)),
            "usd_per_episode": m("cost_usd"), "usd_median": statistics.median([w["cost_usd"] for w in ws
                                                                               if w["cost_usd"] is not None]),
            "usd_max": max(w["cost_usd"] or 0 for w in ws), "turns": m("turns"), "input_tokens": m("input_tokens"),
            "output_tokens": m("output_tokens"), "cached_tokens": m("cached_tokens"),
            "wall_minutes": _mean([(w["wall_seconds"] or 0) / 60 for w in ws]),
            "errors": dict(sum((Counter(w["errors"]) for w in ws), Counter()).most_common())}
    if unscored is not None:
        zeros = [u for u in unscored if u["why"] in MODEL_STOPS]
        out["reward_with_model_stops_as_0"] = _mean([w["reward"] for w in ws] + [0.0] * len(zeros))
    return out


def hypotheses(s: dict) -> dict:
    """H1-H4 read by their registered rules on the main column."""
    if not s.get("n"):
        return {}
    h3a = s["windows_with_ercot_call"] >= 0.75 and s["windows_with_drift_call"] >= 0.5
    return {"H1_beats_blind": read(s["reward_minus_blind_ci"]),
            "H2_front_behind_calm": read(None if s["paired_front_minus_calm_ci"] is None else
                                         [-x for x in reversed(s["paired_front_minus_calm_ci"])]),
            "H3a_reads_ercot_and_revisions": "supported" if h3a else "not supported",
            "H3b_revises_dam": ("undecided (no eligible gate)" if s["revised_share"] is None else
                                "supported" if s["revised_share"] >= 0.5 else "not supported"),
            "H4_gates_kept": "supported" if s["dam_missed"] <= 1 else "not supported"}


def load(name: str) -> tuple[list[dict], list[dict]]:
    """A sweep's scored windows (from its Episode JSON) and its runs that ended unscored."""
    out = RUNS / name
    raw = out / "raw"
    spec = json.loads((raw / "sweep.json").read_text())
    rows = [json.loads(x) for x in (raw / "results.jsonl").read_text().splitlines() if x.strip()]
    tasks = {r["task_id"]: r for r in forecast_tasks.pack_rows(spec["pack"])}
    ws, unscored = [], []
    for task_id in spec["tasks"]:
        mine = [r for r in rows if r["task_id"] == task_id]
        scored = next((r for r in mine if r["outcome"] == "scored"), None)
        path = out / f"{task_id}-{slug(scored['model'])}-r{scored['rep']}.json" if scored else None
        if scored and path.is_file():
            ws.append(window(json.loads(path.read_text()), scored, tasks[task_id], raw))
        else:
            last = mine[-1] if mine else {}
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return ws, unscored


def spend(name: str) -> float:
    rows = (RUNS / name / "raw" / "results.jsonl").read_text().splitlines()
    return sum(json.loads(x).get("cost_usd") or 0.0 for x in rows if x.strip())


def _f(x, fmt: str = ".3f") -> str:
    return "–" if x is None else format(x, fmt)


def _ci(m: dict, key: str) -> str:
    c = m.get(f"{key}_ci")
    return _f(m.get(key)) + (f" ({_f(c[0])} to {_f(c[1])})" if c else "")


def tables(cells: list[tuple[str, dict]]) -> list[str]:
    lines = ["| Column | n | R (95% CI) | r_hind (anchor) | Paired vs anchor (95% CI) | Beats anchor | R at 1 | "
             "P_blind | R - P_blind (95% CI) | P_naive | R - P_naive | P_roll3 | R - P_roll3 | Capture (anchor) |",
             "|---|---:|---|---|---|---:|---:|---:|---|---:|---:|---:|---:|---|"]
    for name, m in cells:
        if not m.get("n"):
            continue
        lines.append(" | ".join([
            f"| {name}", str(m["n"]), _ci(m, "reward"), f"{_f(m['r_hind'])} ({_f(m['anchor_r_hind'])})",
            _ci(m, "paired"), _f(m["beats_anchor"], ".2f"), _f(m["reward_at_1"], ".2f"), _f(m["blind"]),
            _ci(m, "reward_minus_blind"), _f(m["naive"]), _f(m["reward_minus_naive"]), _f(m["roll3"]),
            _f(m["reward_minus_roll3"]), f"{_f(m['capture'])} ({_f(m['anchor_capture'])})"]) + " |")
    lines += ["", "| Column | Label | n | R (95% CI) | r_hind | Paired vs anchor (95% CI) | P_blind | R - P_blind |",
              "|---|---|---:|---|---:|---|---:|---:|"]
    for name, m in cells:
        for lb, v in (m.get("by_label") or {}).items():
            if v["n"]:
                lines.append(f"| {name} | {lb} | {v['n']} | {_ci(v, 'reward')} | {_f(v['r_hind'])} | "
                             f"{_ci(v, 'paired')} | {_f(v['blind'])} | {_f(v['reward_minus_blind'])} |")
    lines += ["", "| Column | Forecast calls (refused) | get_forecast load/wind/solar/weather/price/alerts | Drift "
              "calls | Windows with ERCOT load/wind/solar call | Windows with drift call | Watches with a forecast "
              "call | Budget out (windows) |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for name, m in cells:
        if m.get("n"):
            gf = "/".join(_f(m["get_forecast"][k], ".1f") for k in KINDS)
            lines.append(f"| {name} | {_f(m['forecast_calls'], '.1f')} ({_f(m['forecast_refused'], '.1f')}) | {gf} | "
                         f"{_f(m['drift_calls'], '.1f')} | {_f(m['windows_with_ercot_call'], '.2f')} | "
                         f"{_f(m['windows_with_drift_call'], '.2f')} | {_f(m['watch_share_with_forecast'], '.2f')} | "
                         f"{_f(m['windows_budget_out'], '.2f')} |")
    lines += ["", "| Column | Gates | Missed (windows) | Submits/gate | Read before submit | Eligible gates | Revised "
              "(share) | Revised and read first | PV share < 1 | Gate nudges |",
              "|---|---:|---|---:|---:|---:|---|---:|---:|---:|"]
    for name, m in cells:
        if m.get("n"):
            lines.append(f"| {name} | {m['gates']} | {m['dam_missed']} ({m['windows_with_missed_gate']}) | "
                         f"{_f(m['submits_per_gate'], '.2f')} | {_f(m['gates_read_before_submit'], '.2f')} | "
                         f"{m['eligible_gates']} | {m['revised_gates']} ({_f(m['revised_share'], '.2f')}) | "
                         f"{_f(m['revised_read_before'], '.2f')} | {m['pv_share_below_1_gates']} | "
                         f"{m['gate_nudges']} |")
    lines += ["", "| Column | Refusals | FTP MWh | Governor h | End short | AS $ (anchor) | Commits (anchor) | Re-plan "
              "rate | Finished | Turns | $/episode (median, max) | Output tok | Wall min |",
              "|---|---:|---:|---:|---:|---|---|---:|---:|---:|---|---:|---:|"]
    for name, m in cells:
        if m.get("n"):
            lines.append(f"| {name} | {_f(m['refusals'], '.2f')} | {_f(m['ftp_mwh_charged'], '.2f')} | "
                         f"{_f(m['governor_hours'], '.1f')} | {m['end_short_windows']} | "
                         f"{_f(m['as_usd'], ',.0f')} ({_f(m['anchor_as_usd'], ',.0f')}) | "
                         f"{_f(m['commits'], '.1f')} ({_f(m['anchor_commits'], '.1f')}) | "
                         f"{_f(m['replan_rate'], '.2f')} | "
                         f"{_f(m['finished'], '.2f')} | {_f(m['turns'], '.1f')} | ${_f(m['usd_per_episode'], '.3f')} "
                         f"(${_f(m['usd_median'], '.3f')}, ${_f(m['usd_max'], '.3f')}) | "
                         f"{_f(m['output_tokens'], ',.0f')} | {_f(m['wall_minutes'], '.1f')} |")
    return lines


def line(w: dict) -> str:
    return (f"{w['task_id']} ({w['tier']}, {w['label']}): R {_f(w['reward'])}, r_hind {_f(w['r_hind'])}, paired "
            f"{_f(w['paired'])}, profit ${w['profit_usd']:,.0f} vs anchor ${w['p_anchor']:,.0f}, P_blind R "
            f"{_f(w['blind'])}; {w['forecast_calls']} forecast calls ({w['ercot_calls']} ERCOT load/wind/solar, "
            f"{w['drift_calls']} drift), {w['dam_missed']} gates missed, {w['turns']} turns, "
            f"${_f(w['cost_usd'], '.3f')}, {w['end_reason']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("main", help="The pre-registered front-tier sweep (v4-pilot-sol).")
    ap.add_argument("--lite", help="The front-lite sweep (v4-pilot-sol-lite).")
    ap.add_argument("--smoke", help="The smoke sweep (v4-pilot-sol-smoke), one line a window.")
    ap.add_argument("--display", nargs="*", default=[], help="The display sweeps (fern-0124, heather-0114).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    main_ws, main_un = load(args.main)
    cells = [("front (main)", summary(main_ws, main_un))]
    out = {"main": cells[0][1], "main_unscored": main_un, "hypotheses": hypotheses(cells[0][1]),
           "main_windows": main_ws, "spend": {args.main: spend(args.main)}}
    if args.lite:
        lite_ws, lite_un = load(args.lite)
        cells.append(("front-lite", summary(lite_ws, lite_un)))
        out |= {"lite": cells[-1][1], "lite_unscored": lite_un, "lite_windows": lite_ws,
                "spend": out["spend"] | {args.lite: spend(args.lite)}}
    for lines_key, names in (("smoke", [args.smoke] if args.smoke else []), ("display", args.display)):
        ws = []
        for name in names:
            got, un = load(name)
            ws += got
            out[f"{lines_key}_unscored"] = out.get(f"{lines_key}_unscored", []) + un
            out["spend"][name] = spend(name)
        out[lines_key] = ws
    out["spend_total"] = sum(out["spend"].values())
    print("\n".join(tables(cells)))
    print("\nHypotheses:", json.dumps(out["hypotheses"]))
    for key in ("smoke", "display"):
        for w in out.get(key) or []:
            print(f"{key}: {line(w)}")
    for key in ("main_unscored", "lite_unscored", "smoke_unscored", "display_unscored"):
        for u in out.get(key) or []:
            print(f"unscored ({key}): {u}")
    print("spend:", json.dumps({k: round(v, 4) for k, v in out["spend"].items()}), f"total ${out['spend_total']:.2f}")
    if args.json:
        args.json.write_text(json.dumps(out, indent=1) + "\n")


if __name__ == "__main__":
    main()
