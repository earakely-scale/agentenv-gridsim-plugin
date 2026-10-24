"""The v5 pilot's pre-registered analysis (docs/prereg/v5-pilot.md) from the sweeps' replay-verified Episode JSON v5,
results.jsonl and the pack rows: R on the disclosure-anchor scale and the compliant score against idle, the anchor,
the price-taker, max-withhold and A's real offers on the same floors (each graded in process at the run's tier, both
scorings), the price-making gain over the price-taker, hindsight capture and regret, welfare ratio, eps (seat A's, the
seats' mean and the max), conduct (mitigated hours, withholding, price talk), the CfD row, A's price impact (what its
own awards did to its price, and where its DAM position sits between the impact-aware anchor and the impact-blind
price-taker), fidelity against R, tokens, cost and turns; the floor-sprint
column overall and by peak and base floors, the floor-day column apart, the floors played at both tiers paired, the
showcase floors display only. CIs are 95% bootstrap over floors (2,000 resamples, seed 0), paired for differences."""

import argparse
import json
import random
import statistics
from collections import Counter
from pathlib import Path

import numpy as np

from agentenv_gridsim import market_tasks
from agentenv_gridsim.sweep import slug
from gridsim_core.market import HOURS, Session, anchor_policy, play
from gridsim_core.market_refs import baseline_offers, price_grid, replay_profile, self_schedule_offer, settle_profile

RUNS = Path("results/runs")
EPS = 1e-6
BOOT = 2000
IMPACT_USD = 5.0
BASELINES = ("idle", "anchor", "price_taker", "max_withhold", "replay_A")


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


def spearman(xs: list, ys: list) -> float | None:
    pairs = [(x, y) for x, y in zip(xs, ys, strict=True) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    rx, ry = (np.argsort(np.argsort([p[i] for p in pairs], kind="stable"), kind="stable") for i in (0, 1))
    return float(np.corrcoef(rx, ry)[0, 1]) if np.std(rx) and np.std(ry) else None


def capture(p: float, p_idle: float, p_br: float) -> float | None:
    return (p - p_idle) / (p_br - p_idle) if p_br - p_idle > EPS else None


def offers(task: dict) -> dict[str, dict]:
    """Each baseline's DAM offer on the floor: the core's legal card baselines, idle (no blocks) and the anchor's
    self-schedule."""
    s = Session(task, "floor-sprint")
    q = task["refs"]["floor-sprint"]["anchor"]["q_mw"]
    return ({"idle": {"hours": []}, "anchor": self_schedule_offer(q, s.F.floor, s.F.cap)}
            | baseline_offers(s.F, s.fc))


def submit_at_nine(offer: dict, replan: bool = True):
    """Submit the offer at D-1 09:00; on the op day, with ``replan``, the anchor's re-planner."""
    def policy(s: Session) -> list:
        if s.minute == -900:
            return [("submit_offer", {"offer": offer})]
        return anchor_policy(s) if replan else []
    return policy


def baselines(task: dict, tier: str) -> dict:
    """Each baseline played on the floor at the tier in process: the anchor by its policy, idle by submitting no
    blocks, the others by submitting their offer at D-1 09:00 and, in floor-day, re-planning the op day on their
    awards with the anchor's re-planner (so a floor-day baseline differs from the anchor only in its DAM offer)."""
    out = {}
    for name, offer in offers(task).items():
        s = play(task, tier, anchor_policy if name == "anchor" else submit_at_nine(offer, name != "idle"))
        g = s.grade()
        out[name] = {"reward": g["reward"], "compliant": g["compliant_reward"], "welfare_ratio": g.get("welfare_ratio"),
                     "profit": g["profit_usd"], "submitted": g["submitted"],
                     "awards": [round(x, 2) for x in s.cleared["awards"]] if s.cleared else [0.0] * HOURS}
    return out


def impact(e: dict, task: dict, base: dict) -> dict:
    """What A's DAM position did to the price: impact_usd = Σ award × (price − the price without A's offer), as the
    grade's row (negative when its sales lowered its own price); the hours where A's full sale moves the price by
    >= $5 and the MWh A, the anchor and the price-taker sold in them; and, in
    the hours where the impact-aware anchor and the impact-blind price-taker take different positions, how far A's
    award sits from the anchor's toward the price-taker's (0 at the anchor, 1 at the price-taker)."""
    s = Session(task, e["tier"])
    others = replay_profile(s.F)
    idle_hub = settle_profile(s.F, {"A": [[] for _ in range(HOURS)]}, others)["hub"]
    full = price_grid(s.F, "A", others, [0.0, s.b.p])
    hours = [h for h in range(HOURS) if full[h, 0] - full[h, 1] >= IMPACT_USD]
    aw, hub = e["awards"]["A"], e["clear"]["hub_usd"]
    qa, qp = base["anchor"]["awards"], base["price_taker"]["awards"]
    diff = [h for h in range(HOURS) if abs(qp[h] - qa[h]) > EPS]
    num = sum((aw[h] - qa[h]) * (1 if qp[h] > qa[h] else -1) for h in diff)
    den = sum(abs(qp[h] - qa[h]) for h in diff)

    def sold(q):
        return round(sum(max(q[h], 0.0) for h in hours), 2)

    return {"impact_hours": [h + 1 for h in hours],
            "impact_usd": round(sum(aw[h] * (hub[h] - idle_hub[h]) for h in range(HOURS)), 2),
            "impact_hour_mwh": sold(aw), "anchor_impact_hour_mwh": sold(qa), "price_taker_impact_hour_mwh": sold(qp),
            "split_hours": len(diff), "toward_price_taker_num": num, "toward_price_taker_den": den,
            "toward_price_taker": num / den if den > EPS else None}


def floor(e: dict, row: dict, task: dict) -> dict:
    """One scored floor's pilot fields from its Episode JSON, its results row and its pack row."""
    r, tier = e["references"], e["tier"]
    p, p_idle, p_anchor, p_br = e["profit_usd"], r["p_idle"], r["p_anchor"], r["p_br"]
    base = baselines(task, tier)
    imp = impact(e, task, base)
    rows = e["rows"]
    contract = rows.get("contract") or {}
    conduct = rows.get("conduct") or {}
    out = {"task_id": e["task_id"], "tier": tier, "date": task["date"], "stratum": task["tags"].get("stratum"),
           "within_ns": task["fidelity"]["within_ns"], "notice_day": task["tags"].get("notice_day"),
           "p_mw": task["seats"]["A"]["p_mw"], "reward": e["reward"], "compliant": e["compliant_reward"],
           "raw_ratio": e["raw_ratio"], "profit_usd": p, "p_idle": p_idle, "p_anchor": p_anchor, "p_br": p_br,
           "capture": capture(p, p_idle, p_br), "anchor_capture": capture(p_anchor, p_idle, p_br),
           "price_making_gain_usd_per_mw_day": (p - base["price_taker"]["profit"]) / task["seats"]["A"]["p_mw"]
           if "price_taker" in base else None,
           "regret_norm": rows.get("regret_norm"), "beats_anchor": p > p_anchor + EPS,
           "welfare_ratio": rows.get("welfare_ratio"), "dwl_usd": rows.get("dwl_usd"), "eps_nash": rows.get("eps_nash"),
           "eps_a": rows.get("eps_a"), "eps_mean": rows.get("eps_mean"),
           "rank": rows.get("rank"), "mitigated_hours": conduct.get("mitigated_hours"),
           "withholding_index": conduct.get("withholding_index"), "message_flags": conduct.get("message_flags"),
           "contracts": len(contract.get("contracts") or []), "contract_value_usd": contract.get(
               "value_at_signing_usd"), "contract_settled_usd": contract.get("settled_usd"),
           "clipped_hours": sum(bool(h["clipped"]) for h in e["hours"]),
           "submits": sum(st["tool"] == "submit_offer" for st in e["steps"]),
           "checks": sum(st["tool"] == "check_offer" for st in e["steps"]),
           "disclosure_calls": sum(st["tool"] == "get_disclosure" for st in e["steps"]),
           "refused": sum(st["tool"] in ("submit_offer", "commit_schedule") and (
               st["output"].get("accepted") is False or bool(st["output"].get("issues"))) for st in e["steps"]),
           "baselines": {k: {x: v[x] for x in ("reward", "compliant", "welfare_ratio", "profit")}
                         for k, v in base.items()},
           **imp, "audit_ok": e["audit"]["ok"],
           "cost_usd": row.get("priced_cost_usd") if row.get("priced_cost_usd") is not None else row.get("cost_usd"),
           "turns": row.get("turns"), "end_reason": row.get("end_reason"), "input_tokens": row.get("input_tokens"),
           "output_tokens": row.get("output_tokens"), "cached_tokens": row.get("cached_tokens"),
           "errors": row.get("errors") or []}
    for k, v in base.items():
        out[f"beats_{k}"] = p > v["profit"] + EPS
    return out


def summary(fs: list[dict]) -> dict:
    if not fs:
        return {"n": 0}

    def m(key):
        return _mean([f.get(key) for f in fs])

    def diffs(key, base):
        return [f[key] - f["baselines"][base][key] for f in fs if base in f["baselines"]
                and f[key] is not None and f["baselines"][base][key] is not None]

    num = sum(f["toward_price_taker_num"] for f in fs)
    den = sum(f["toward_price_taker_den"] for f in fs)
    out = {"n": len(fs), "reward": m("reward"), "reward_ci": ci([f["reward"] for f in fs]),
           "compliant": m("compliant"), "compliant_ci": ci([f["compliant"] for f in fs]),
           "reward_at_1": _mean([float(f["reward"] >= 1 - EPS) for f in fs]),
           "beats_anchor": _mean([float(f["beats_anchor"]) for f in fs]),
           "capture": m("capture"), "capture_ci": ci([f["capture"] for f in fs]), "anchor_capture": m("anchor_capture"),
           "regret_norm": m("regret_norm"), "welfare_ratio": m("welfare_ratio"), "dwl_usd": m("dwl_usd"),
           "eps_nash": m("eps_nash"), "eps_a": m("eps_a"), "eps_mean": m("eps_mean"), "rank": m("rank"),
           "mitigated_hours": sum(f["mitigated_hours"] or 0 for f in fs),
           "floors_mitigated": sum(bool(f["mitigated_hours"]) for f in fs),
           "withholding_index": m("withholding_index"), "message_flags": sum(f["message_flags"] or 0 for f in fs),
           "contracts": m("contracts"), "floors_with_contract": sum(f["contracts"] > 0 for f in fs),
           "contract_value_usd": m("contract_value_usd"), "contract_settled_usd": m("contract_settled_usd"),
           "impact_usd": m("impact_usd"), "impact_hour_mwh": m("impact_hour_mwh"),
           "price_making_gain_usd_per_mw_day": m("price_making_gain_usd_per_mw_day"),
           "anchor_impact_hour_mwh": m("anchor_impact_hour_mwh"),
           "price_taker_impact_hour_mwh": m("price_taker_impact_hour_mwh"),
           "split_hours": sum(f["split_hours"] for f in fs), "floors_split": sum(f["split_hours"] > 0 for f in fs),
           "toward_price_taker": num / den if den > EPS else None,
           "clipped_hours": m("clipped_hours"), "refused": sum(f["refused"] for f in fs), "submits": m("submits"),
           "checks": m("checks"), "disclosure_calls": m("disclosure_calls"),
           "audit_failures": sum(not f["audit_ok"] for f in fs), "usd_per_episode": m("cost_usd"), "turns": m("turns"),
           "input_tokens": m("input_tokens"), "output_tokens": m("output_tokens"), "cached_tokens": m("cached_tokens"),
           "errors": dict(sum((Counter(f["errors"]) for f in fs), Counter()).most_common()),
           "fidelity_spearman_reward": spearman([f["within_ns"] for f in fs], [f["reward"] for f in fs]),
           "fidelity_spearman_regret": spearman([f["within_ns"] for f in fs], [f["regret_norm"] for f in fs])}
    for b in BASELINES:
        if not any(b in f["baselines"] for f in fs):
            continue
        for key in ("reward", "compliant"):
            d = diffs(key, b)
            out[f"{b}_{key}"] = _mean([f["baselines"][b][key] for f in fs if b in f["baselines"]])
            out[f"{key}_minus_{b}"], out[f"{key}_minus_{b}_ci"] = _mean(d), ci(d)
        out[f"{b}_welfare_ratio"] = _mean([f["baselines"][b]["welfare_ratio"] for f in fs if b in f["baselines"]])
        out[f"beats_{b}"] = _mean([float(f[f"beats_{b}"]) for f in fs if f"beats_{b}" in f])
    return out


def ranks(m: dict) -> dict:
    """Sol and the baselines ranked by mean R and by mean compliant score (1 = best)."""
    out = {}
    for key in ("reward", "compliant"):
        vals = {"Sol": m.get(key)} | {b: m.get(f"{b}_{key}") for b in BASELINES}
        vals = {k: v for k, v in vals.items() if v is not None}
        order = sorted(vals, key=lambda k: -vals[k])
        out[key] = {k: order.index(k) + 1 for k in order}
    return out


def paired(day: list[dict], sprint: list[dict]) -> dict:
    """floor-day minus floor-sprint on the floors played at both tiers."""
    s = {f["task_id"]: f for f in sprint}
    both = [(f, s[f["task_id"]]) for f in day if f["task_id"] in s]
    out = {"n": len(both)}
    for key in ("reward", "compliant", "welfare_ratio", "capture"):
        d = [a[key] - b[key] for a, b in both if a[key] is not None and b[key] is not None]
        out[key], out[key + "_ci"] = _mean(d), ci(d)
    return out


def terciles(fs: list[dict]) -> list[dict]:
    order = sorted(fs, key=lambda f: f["within_ns"])
    k = len(order) // 3
    groups = [order[:k], order[k:len(order) - k], order[len(order) - k:]] if k else [order]
    return [{"within_ns": [g[0]["within_ns"], g[-1]["within_ns"]], "n": len(g),
             "reward": _mean([f["reward"] for f in g]), "regret_norm": _mean([f["regret_norm"] for f in g])}
            for g in groups if g]


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
            unscored.append({"task_id": task_id, "attempts": len(mine),
                             "why": "no episode (replay failed)" if scored else (last.get("error_code") or
                                                                                 last.get("outcome") or "not run")})
    return floors, unscored


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


def tables(cells: list[tuple[str, dict]]) -> list[str]:
    """The two scorings against the baselines, then the market rows, then price impact and play."""
    scores = ["| Set | Floors | R (95% CI) | Compliant (95% CI) | R = 1 | Price-taker R | R − price-taker (95% CI) "
              "| Replay A R | R − replay A (95% CI) | Max-withhold R | Beats anchor | Beats price-taker | Capture "
              "| Anchor capture |", "|---|---:|---|---|---:|---:|---|---:|---|---:|---:|---:|---:|---:|"]
    compliant = ["| Set | Floors | Compliant | Anchor | Price-taker | Replay A | Max-withhold | Idle "
                 "| Compliant − price-taker (95% CI) | Welfare ratio | Price-taker's | Anchor's | Rank by R "
                 "| Rank by compliant |", "|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|---|"]
    market = ["| Set | Floors | Regret (norm) | eps A | eps mean | eps-Nash (max seat) | Rank among seats "
              "| Mitigated h (floors) | Withholding | Price talk | CfDs/floor (floors) | CfD value at signing $ "
              "| CfD settled $ | Clipped h |",
              "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|"]
    impact = ["| Set | Floors | Impact $ | Price-making gain $/MW-day | Impact-hour MWh sold | Anchor's "
              "| Price-taker's | Split hours (floors) | Toward price-taker | Submits | Checks | Disclosure calls "
              "| Refused | $/episode | Turns | Output tok |",
              "|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label, m in cells:
        if not m["n"]:
            continue
        rk = ranks(m)
        scores.append(" | ".join([
            f"| {label}", str(m["n"]), _ci(m, "reward"), _ci(m, "compliant"), _f(m["reward_at_1"]),
            _f(m.get("price_taker_reward")), _ci(m, "reward_minus_price_taker"), _f(m.get("replay_A_reward")),
            _ci(m, "reward_minus_replay_A"), _f(m.get("max_withhold_reward")), _f(m["beats_anchor"]),
            _f(m.get("beats_price_taker")), _f(m["capture"]), _f(m["anchor_capture"])]) + " |")
        compliant.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["compliant"]), _f(m.get("anchor_compliant")),
            _f(m.get("price_taker_compliant")), _f(m.get("replay_A_compliant")), _f(m.get("max_withhold_compliant")),
            _f(m.get("idle_compliant")), _ci(m, "compliant_minus_price_taker"), _f(m["welfare_ratio"]),
            _f(m.get("price_taker_welfare_ratio")), _f(m.get("anchor_welfare_ratio")),
            ", ".join(f"{k} {v}" for k, v in rk["reward"].items()),
            ", ".join(f"{k} {v}" for k, v in rk["compliant"].items())]) + " |")
        market.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["regret_norm"]), _f(m["eps_a"]), _f(m["eps_mean"]), _f(m["eps_nash"]),
            _f(m["rank"], ".2f"),
            f"{m['mitigated_hours']} ({m['floors_mitigated']})", _f(m["withholding_index"]), str(m["message_flags"]),
            f"{_f(m['contracts'], '.2f')} ({m['floors_with_contract']})", _f(m["contract_value_usd"], ",.0f"),
            _f(m["contract_settled_usd"], ",.0f"), _f(m["clipped_hours"], ".2f")]) + " |")
        impact.append(" | ".join([
            f"| {label}", str(m["n"]), _f(m["impact_usd"], ",.0f"), _f(m["price_making_gain_usd_per_mw_day"], ",.2f"),
            _f(m["impact_hour_mwh"], ",.0f"),
            _f(m["anchor_impact_hour_mwh"], ",.0f"), _f(m["price_taker_impact_hour_mwh"], ",.0f"),
            f"{m['split_hours']} ({m['floors_split']})", _f(m["toward_price_taker"], ".2f"), _f(m["submits"], ".2f"),
            _f(m["checks"], ".2f"), _f(m["disclosure_calls"], ".2f"), str(m["refused"]),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}", _f(m["turns"], ".1f"),
            _f(m["output_tokens"], ",.0f")]) + " |")
    return scores + [""] + compliant + [""] + market + [""] + impact


def showcase_line(f: dict) -> str:
    return (f"{f['task_id']}: R {_f(f['reward'])}, compliant {_f(f['compliant'])}, profit ${f['profit_usd']:,.0f} "
            f"(anchor ${f['p_anchor']:,.0f}, hindsight ${f['p_br']:,.0f}), welfare ratio {_f(f['welfare_ratio'])}, "
            f"CfDs {f['contracts']}, mitigated h {f['mitigated_hours']}, ${f['cost_usd'] or 0:.4f}, {f['turns']} turns")


def column(label: str, fs: list[dict]) -> list[tuple[str, dict]]:
    return ([(f"{label}: all", summary(fs))]
            + [(f"{label}: {s}", summary([f for f in fs if f["stratum"] == s])) for s in ("peak", "base")])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sprint", help="The pre-registered floor-sprint sweep (v5-pilot-sol).")
    ap.add_argument("--day", help="The floor-day sweep (v5-pilot-sol-day).")
    ap.add_argument("--amend", nargs="*", default=[], help="The labelled amendment sweeps.")
    ap.add_argument("--showcase", nargs="*", default=[], help="The showcase sweeps (display only).")
    ap.add_argument("--smoke", nargs="*", default=[], help="The smoke sweeps (spend only).")
    ap.add_argument("--json", type=Path, help="Write the numbers here too.")
    args = ap.parse_args()
    names = [n for n in [args.sprint, args.day, *args.amend, *args.showcase, *args.smoke] if n]
    out = {"columns": {}, "unscored": {}, "spend_usd": {n: round(spend(n), 4) for n in names}}
    amended = {a: load(a) for a in args.amend}
    lines: list[str] = []
    floors = {}
    for col, name in (("floor-sprint", args.sprint), ("floor-day", args.day)):
        if not name:
            continue
        fs, unscored = load(name)
        floors[col] = fs
        out["unscored"][col] = unscored
        cells = column(f"{col} primary", fs)
        extra = [f for a, (ds, _) in amended.items() if json.loads(
            (RUNS / a / "raw" / "sweep.json").read_text())["tier"] == col for f in ds]
        if extra:
            cells += column(f"{col} amended", fs + [f for f in extra if f["task_id"] not in {x["task_id"] for x in fs}])
        out["columns"][col] = {lab: m for lab, m in cells} | {"floors": fs, "fidelity_terciles": terciles(fs)}
        lines += tables(cells) + [""]
        m = cells[0][1]
        lines += [f"{col}: fidelity (within_ns) Spearman with R {_f(m['fidelity_spearman_reward'], '.2f')}, with "
                  f"regret {_f(m['fidelity_spearman_regret'], '.2f')}; terciles "
                  + "; ".join(f"{t['within_ns'][0]:.2f}-{t['within_ns'][1]:.2f}: R {_f(t['reward'])} (n {t['n']})"
                              for t in terciles(fs)) + f"; errors {_counts(m['errors'])}.", ""]
    if "floor-day" in floors and "floor-sprint" in floors:
        p = paired(floors["floor-day"], floors["floor-sprint"])
        out["paired_day_minus_sprint"] = p
        lines += [f"floor-day minus floor-sprint on the {p['n']} floors played at both: R {_ci(p, 'reward')}, "
                  f"compliant {_ci(p, 'compliant')}, welfare ratio {_ci(p, 'welfare_ratio')}, capture "
                  f"{_ci(p, 'capture')}.", ""]
    show = []
    for name in args.showcase:
        fs, missing = load(name)
        show += fs
        out["unscored"][name] = missing
        lines += ["Showcase (display only): " + ("; ".join(showcase_line(f) for f in fs) or f"unscored: {missing}"),
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
