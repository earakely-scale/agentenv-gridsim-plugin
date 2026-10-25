"""The cross-version reward-scale study behind docs/REWARD-SCALES.md: Sol's pilot and board runs and every stored
reference on the same tasks, scored on R (anchor scale), hindsight capture C, the paired gap, R against hindsight, the
anchor-to-hindsight gap, the stretch and the knee; then the stored references on the full eval packs. Reads only
committed Episode JSON, results/pilot-v5.json and the packs' rows as the pilots played them (PACKS_AT: rules 3.1, 4.1
and 5.1 rebuilt the v3 to v5 packs after). CIs are 95% percentile bootstrap over tasks (10,000 resamples, seed 0),
paired for differences."""

import gzip
import json
import statistics
import subprocess
from pathlib import Path

import numpy as np

RUNS = Path("results/runs")
PACKS_AT = "7b9fd7c"
EPS = 1e-9
BOOT = 10_000
COLUMNS = [("v1 A foresight", "foresight", ["v1-board-sol-full", "v1-board-sol-full-amend"], "ercot-dam-v1-eval"),
           ("v1 B foresight oneshot", "foresight", ["v1-board-sol-oneshot", "v1-board-sol-oneshot-amend"],
            "ercot-dam-v1-eval"),
           ("v1 C blind", "blind", ["v1-board-sol-blind", "v1-board-sol-blind-amend"], "ercot-dam-v1-eval"),
           ("v1 D rtcb foresight", "foresight", ["v1-board-sol-rtcb", "v1-board-sol-rtcb-amend"], "ercot-dam-v1-rtcb")]
OTHERS = {"v1 A foresight": ["clock", "threshold", "greedy"],
          "v1 B foresight oneshot": ["clock", "threshold", "greedy"],
          "v1 C blind": ["clock", "persist_dp", "ridge_dp"], "v1 D rtcb foresight": ["clock", "threshold", "greedy"],
          "v2 foresight": ["naive"], "v3 reserves": ["as_hog", "v2_energy", "energy_only_milp"],
          "v3 energy": ["v2_energy"], "v4 front": ["naive", "blind_roll", "roll3"],
          "v4 front-lite": ["naive", "blind_roll", "roll3"],
          "v5 floor-sprint": ["replay_A", "max_withhold", "price_taker"],
          "v5 floor-day": ["replay_A", "max_withhold", "price_taker"]}
ALTERNATE_ANCHORS = {"v1 C blind": ["persist_dp", "ridge_dp"], "v2 foresight": ["naive"],
                     "v3 reserves": ["energy_only_milp"], "v4 front": ["blind_roll", "roll3"],
                     "v4 front-lite": ["blind_roll", "roll3"], "v5 floor-sprint": ["price_taker"],
                     "v5 floor-day": ["price_taker"]}


def reward(p: float, p_idle: float, p_anchor: float) -> float:
    d = p_anchor - p_idle
    if d <= EPS:
        return 1.0 if p >= p_anchor - 1e-6 else 0.0
    return min(1.0, max(0.0, 0.2 + 0.8 * (p - p_idle) / d))


def scales(p: float, t: dict) -> dict:
    """Every candidate scale for profit p on task t (p_idle, p_anchor, p_hind)."""
    i, a, h = t["p_idle"], t["p_anchor"], t["p_hind"]
    c = (p - i) / (h - i)
    q = (p - a) / (h - a) if h - a > EPS else None
    above = q is not None and p > a
    x = (p - i) / (a - i) if a - i > EPS else float(p >= a)
    return {"R": reward(p, i, a), "C": c, "G": (p - a) / (h - i), "Rh": min(1.0, max(0.0, 0.2 + 0.8 * c)), "Q": q,
            "S": min(1.2, 1 + 0.2 * q) if above else reward(p, i, a),
            "K": min(1.0, 0.8 + 0.2 * q) if above else max(0.0, 0.2 + 0.6 * x)}


def boot(xs: list[float], seed: int = 0) -> tuple[float, float]:
    a = np.asarray(xs, dtype=float)
    idx = np.random.default_rng(seed).integers(0, len(a), size=(BOOT, len(a)))
    m = np.sort(a[idx].mean(axis=1))
    return float(m[int(0.025 * BOOT)]), float(m[int(0.975 * BOOT) - 1])


def pack(name: str) -> dict:
    blob = subprocess.run(["git", "show", f"{PACKS_AT}:data/{name}/tasks.jsonl.gz"], capture_output=True,
                          check=True).stdout
    return {r["task_id"]: r for r in (json.loads(x) for x in gzip.decompress(blob).decode().splitlines())}


def episodes(sweep: str) -> list[dict]:
    return [json.loads(f.read_text()) for f in sorted((RUNS / sweep).glob("*.json"))]


def v1_refs(t: dict, tier: str) -> dict:
    f, b = t["refs"]["foresight"], t["refs"].get("blind")
    refs = {"idle": f["p_idle"]} | {k: f["baselines"][k]["profit"] for k in ("random", "clock", "threshold", "greedy")}
    if b:
        refs |= {"persist_dp": b["p_persist"], "ridge_dp": b["p_ridge"], "blind_anchor": b["p_anchor"]}
    anchor = "blind_anchor" if tier == "blind" else "dp_opt"
    refs["dp_opt"] = f["p_opt"]
    return {"p_idle": f["p_idle"], "p_anchor": refs[anchor], "p_hind": f["p_opt"], "anchor": anchor, "refs": refs}


def columns() -> dict[str, list[dict]]:
    """Each board or pilot column: per task, Sol's profit and the stored references, all on the same task."""
    cols = {}
    for name, tier, sweeps, pk in COLUMNS:
        rows = pack(pk)
        cols[name] = [{"p": e["profit_usd"]} | v1_refs(rows[e["task_id"]], tier) for s in sweeps for e in episodes(s)]
    live = pack("gridsim-live-eval")
    cols["v2 foresight"] = []
    for e in episodes("v2-pilot-sol"):
        r = live[e["task_id"]]["refs"]
        refs = {"idle": r["p_idle"], "naive": r["p_naive"], "anchor": r["roll"]["foresight"]["p_roll"]}
        cols["v2 foresight"].append({"p": e["profit_usd"], "p_idle": r["p_idle"], "p_anchor": refs["anchor"],
                                     "p_hind": r["p_hind"], "anchor": "anchor", "refs": refs})
    for name, sweep in [("v3 reserves", "v3-pilot-sol"), ("v3 energy", "v3-pilot-sol-energy")]:
        cols[name] = []
        for e in episodes(sweep):
            r = e["references"]
            refs = {"idle": r["p_idle"], "anchor": r["p_anchor"]} | {k: v["profit"] for k, v in r["baselines"].items()}
            if r.get("p_energy_only") is not None:
                refs["energy_only_milp"] = r["p_energy_only"]
            cols[name].append({"p": e["profit_usd"], "p_idle": r["p_idle"], "p_anchor": r["p_anchor"],
                               "p_hind": r["p_hind"], "anchor": "anchor", "refs": refs})
    for name, sweep in [("v4 front", "v4-pilot-sol"), ("v4 front-lite", "v4-pilot-sol-lite")]:
        cols[name] = []
        for e in episodes(sweep):
            r = e["references"]
            refs = {"idle": r["p_idle"], "naive": r["p_naive"], "blind_roll": r["p_blind"], "roll3": r["p_roll3"],
                    "anchor": r["p_anchor"]}
            cols[name].append({"p": e["profit_usd"], "p_idle": r["p_idle"], "p_anchor": r["p_anchor"],
                               "p_hind": r["p_hind"], "anchor": "anchor", "refs": refs})
    mkt = pack("gridsim-market-eval")
    pilot = json.loads(Path("results/pilot-v5.json").read_text())["columns"]
    for name, tier, floors in [("v5 floor-sprint", "floor-sprint", pilot["floor-sprint"]["amended"]["floors"]),
                               ("v5 floor-day", "floor-day", pilot["floor-day"]["primary"]["floors"])]:
        cols[name] = []
        for f in floors:
            t, b = mkt[f["task_id"]]["refs"][tier], f["baselines"]
            cols[name].append({"p": f["profit_usd"], "p_idle": f["p_idle"], "p_anchor": f["p_anchor"],
                               "p_hind": t["p_br_rt"], "p_br_da": f["p_br"], "anchor": "anchor",
                               "refs": {k: b[k]["profit"] for k in ("idle", "replay_A", "max_withhold", "price_taker",
                                                                     "anchor")},
                               "w": f["welfare_ratio"], "ref_w": {k: b[k]["welfare_ratio"] for k in b}})
    return cols


def _f(x, fmt: str = ".3f") -> str:
    return "–" if x is None else format(x, fmt)


def _ci(xs: list[float], seed: int = 0) -> str:
    lo, hi = boot(xs, seed)
    return f"{_f(statistics.mean(xs), '+.3f')} ({_f(lo, '+.3f')} to {_f(hi, '+.3f')})"


def _m(xs: list[float]) -> str:
    lo, hi = boot(xs)
    return f"{statistics.mean(xs):.3f} ({lo:.3f} to {hi:.3f})"


def share(xs: list[float], v: float) -> float:
    return statistics.mean(float(abs(x - v) <= 1e-6) for x in xs)


def best_other(name: str, rows: list[dict]) -> str:
    return max(OTHERS[name], key=lambda k: statistics.mean(r["refs"][k] for r in rows))


def headline_table(cols: dict) -> list[str]:
    out = ["| Column | n | R (95% CI) | R = 1 | C (95% CI) | C = 1 | C < 0 | Anchor's C | C − anchor's C (95% CI) "
           "| R − anchor's R (95% CI) | Best other ref | C − its C (95% CI) | R − its R (95% CI) |",
           "|---|---:|---|---:|---|---:|---:|---:|---|---|---|---|---|"]
    for name, rows in cols.items():
        sol = [scales(r["p"], r) for r in rows]
        anc = [scales(r["p_anchor"], r) for r in rows]
        k = best_other(name, rows)
        oth = [scales(r["refs"][k], r) for r in rows]
        out.append(" | ".join([
            f"| {name}", str(len(rows)), _m([s["R"] for s in sol]), _f(share([s["R"] for s in sol], 1.0), ".2f"),
            _m([s["C"] for s in sol]), _f(share([s["C"] for s in sol], 1.0), ".2f"),
            str(sum(s["C"] < -EPS for s in sol)), _f(statistics.mean(a["C"] for a in anc)),
            _ci([s["C"] - a["C"] for s, a in zip(sol, anc, strict=True)], 1),
            _ci([s["R"] - a["R"] for s, a in zip(sol, anc, strict=True)], 1),
            k, _ci([s["C"] - o["C"] for s, o in zip(sol, oth, strict=True)], 1),
            _ci([s["R"] - o["R"] for s, o in zip(sol, oth, strict=True)], 1)]) + " |")
    return out


def variants_table(cols: dict) -> list[str]:
    """Each scale on each column: Sol's mean, ceiling and floor shares, and |paired gap| over the CI half-width
    against the anchor and the best other reference (z > 1: the CI excludes 0)."""
    out = ["| Column | Scale | Sol | At max | At min (< 0 for G, Q) | z vs anchor | z vs best other | SD over tasks |",
           "|---|---|---:|---:|---:|---:|---:|---:|"]
    top = {"R": 1.0, "C": 1.0, "Rh": 1.0, "S": 1.2, "K": 1.0}
    for name, rows in cols.items():
        if name.startswith("v1 B") or name.startswith("v1 D"):
            continue
        k = best_other(name, rows)
        for s in ("R", "C", "Rh", "G", "Q", "S", "K"):
            xs = [scales(r["p"], r)[s] for r in rows]
            if any(x is None for x in xs):
                continue
            zs = []
            for ref in ("p_anchor", k):
                ys = [scales(r[ref] if ref == "p_anchor" else r["refs"][ref], r)[s] for r in rows]
                d = [x - y for x, y in zip(xs, ys, strict=True)]
                lo, hi = boot(d, 1)
                zs.append(abs(statistics.mean(d)) / ((hi - lo) / 2) if hi > lo else None)
            lo_share = share(xs, 0.0) if s in top else statistics.mean(float(x < -EPS) for x in xs)
            out.append(f"| {name} | {s} | {statistics.mean(xs):.3f} | "
                       f"{_f(share(xs, top[s]) if s in top else None, '.2f')} | {lo_share:.2f} | {_f(zs[0], '.2f')} | "
                       f"{_f(zs[1], '.2f')} | {statistics.pstdev(xs):.3f} |")
    return out


def stability_table(cols: dict) -> list[str]:
    out = ["| Column | Anchor | Its C | Sol's R | Sol at R = 1 | Stored anchor's R on it |",
           "|---|---|---:|---:|---:|---:|"]
    for name, alts in ALTERNATE_ANCHORS.items():
        rows = cols[name]
        for alt in ["(stored)"] + alts:
            a = (lambda r: r["p_anchor"]) if alt == "(stored)" else (lambda r, alt=alt: r["refs"][alt])
            rr = [reward(r["p"], r["p_idle"], a(r)) for r in rows]
            out.append(f"| {name} | {alt} | {statistics.mean(scales(a(r), r)['C'] for r in rows):.3f} | "
                       f"{statistics.mean(rr):.3f} | {share(rr, 1.0):.2f} | "
                       f"{statistics.mean(reward(r['p_anchor'], r['p_idle'], a(r)) for r in rows):.3f} |")
    return out


def inside(xs: list[float], lo: float, hi: float) -> float:
    return statistics.mean(float(lo + 1e-6 < x < hi - 1e-6) for x in xs)


def clip(x: float) -> float:
    return min(1.0, max(0.0, x))


def training_table(cols: dict) -> list[str]:
    """Training fitness: the share of Sol's runs strictly inside each scale (a gradient exists), and the spread over
    tasks of an information-matched policy (the anchor) under each scale: task noise a policy cannot remove."""
    out = ["| Column | Sol inside R | Sol inside S | Sol inside C [0, 1] | Anchor's SD under R | Anchor's SD under C "
           "| Sol's SD under R | Sol's SD under C |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for name, rows in cols.items():
        if name.startswith("v1 B") or name.startswith("v1 D"):
            continue
        sol = [scales(r["p"], r) for r in rows]
        anc = [scales(r["p_anchor"], r) for r in rows]
        out.append(f"| {name} | {inside([s['R'] for s in sol], 0, 1):.2f} | "
                   f"{inside([s['S'] for s in sol], 0, 1.2):.2f} | "
                   f"{inside([s['C'] for s in sol], 0, 1):.2f} | {statistics.pstdev(a['R'] for a in anc):.3f} | "
                   f"{statistics.pstdev(a['C'] for a in anc):.3f} | {statistics.pstdev(s['R'] for s in sol):.3f} | "
                   f"{statistics.pstdev(s['C'] for s in sol):.3f} |")
    return out


def compliant_table(cols: dict) -> list[str]:
    out = ["| Tier | Profit half | Sol (95% CI) | − anchor (95% CI) | of which profit half | of which welfare half "
           "| − price-taker (95% CI) | Anchor | Price-taker | Replay A | Idle |",
           "|---|---|---|---|---:|---:|---|---:|---:|---:|---:|"]
    for name in ("v5 floor-sprint", "v5 floor-day"):
        rows = cols[name]
        for half in ("R", "C"):
            def score(p, w, r, half=half):
                ph = scales(p, r)["R"] if half == "R" else clip(scales(p, r)["C"])
                return 0.5 * ph + 0.5 * clip(w), 0.5 * ph, 0.5 * clip(w)
            sol = [score(r["p"], r["w"], r) for r in rows]
            ref = {k: [score(r["refs"][k], r["ref_w"][k], r) for r in rows] for k in ("anchor", "price_taker",
                                                                                      "replay_A", "idle")}
            da = [s[0] - a[0] for s, a in zip(sol, ref["anchor"], strict=True)]
            out.append(" | ".join([
                f"| {name[3:]}", "R" if half == "R" else "clip(C, 0, 1)", _m([s[0] for s in sol]), _ci(da, 1),
                _f(statistics.mean(s[1] - a[1] for s, a in zip(sol, ref["anchor"], strict=True)), "+.3f"),
                _f(statistics.mean(s[2] - a[2] for s, a in zip(sol, ref["anchor"], strict=True)), "+.3f"),
                _ci([s[0] - a[0] for s, a in zip(sol, ref["price_taker"], strict=True)], 1)]
                + [_f(statistics.mean(x[0] for x in ref[k])) for k in ("anchor", "price_taker", "replay_A", "idle")])
                + " |")
        d = [r["p"] - r["p_anchor"] for r in rows]
        out.append(f"| {name[3:]} | dollars | Sol − anchor: mean ${statistics.mean(d):+,.0f}, median "
                   f"${statistics.median(d):+,.0f}, Sol above on {sum(x > 1e-6 for x in d)} of {len(d)}"
                   + " |" * 9)
    return out


def v5_hindsight_lines(cols: dict) -> list[str]:
    out = []
    for name in ("v5 floor-sprint", "v5 floor-day"):
        rows = cols[name]
        da = [(r["p"] - r["p_idle"]) / (r["p_br_da"] - r["p_idle"]) for r in rows]
        over = sum(r["p"] > r["p_br_da"] + 1e-6 for r in rows)
        refs_over = sum(v > r["p_br_da"] + 1e-6 for r in rows for k, v in r["refs"].items())
        out.append(f"- {name}: against BR_A Sol's C is {statistics.mean(da):.3f} (median {statistics.median(da):.3f}, "
                   f"min {min(da):.2f}); Sol exceeds BR_A on {over} of {len(rows)} floors and the references "
                   f"{refs_over} times. Against BR_rt: none exceeds it, min C "
                   f"{min(scales(r['p'], r)['C'] for r in rows):.2f}.")
    return out


def pack_table() -> list[str]:
    """Every stored reference on the full eval packs, no model: the anchor's capture, and each other reference's
    mean R, its share at R = 1, its C and how often it beats the anchor; and whether anything exceeds the hindsight."""
    sets = {}
    v1 = pack("ercot-dam-v1-eval")
    sets["v1 foresight (eval 500)"] = [v1_refs(t, "foresight") for t in v1.values()]
    sets["v1 blind (eval 300)"] = [v1_refs(t, "blind") for t in v1.values() if t["refs"].get("blind")]
    for label, s in sets.items():
        for r in s:
            r["refs"] = {k: r["refs"][k] for k in OTHERS["v1 C blind" if "blind" in label else "v1 A foresight"]}
    rows = []
    for t in pack("gridsim-live-eval").values():
        r = t["refs"]
        rows.append({"p_idle": r["p_idle"], "p_anchor": r["roll"]["foresight"]["p_roll"], "p_hind": r["p_hind"],
                     "refs": {"naive": r["p_naive"], **({"blind_roll": r["roll"]["blind"]["p_roll"]}
                                                        if r["roll"].get("blind") else {})}})
    sets["v2 foresight (eval 300)"] = rows
    hyb = pack("ercot-hybrid-v3-eval")
    for tier in ("reserves", "energy"):
        rows = []
        for t in hyb.values():
            x = t["refs"][tier]
            refs = {k: v["profit"] for k, v in x["baselines"].items() if k != "sponge"} | {
                "oneshot_milp": x["oneshot"]["p_milp"]}
            if x.get("p_energy_only") is not None:
                refs["energy_only_milp"] = x["p_energy_only"]
            rows.append({"p_idle": t["refs"]["p_idle"], "p_anchor": x["p_anchor"], "p_hind": x["p_hind"], "refs": refs})
        sets[f"v3 {tier} (eval 300)"] = rows
    fc = pack("ercot-front-v4-eval")
    for tier in ("front", "front-lite"):
        sets[f"v4 {tier} (eval 60)"] = [
            {"p_idle": x["p_idle"], "p_anchor": x["p_anchor"], "p_hind": x["p_hind"],
             "refs": {"naive": x["p_naive"], "blind_roll": x["p_blind"], "roll3": x["p_roll3"]}}
            for x in (t["refs"][tier] for t in fc.values())]
    mkt = pack("gridsim-market-eval")
    for hk in ("p_br_rt", "p_br"):
        tag = "BR_rt" if hk == "p_br_rt" else "BR_A"
        sets[f"v5 floor-sprint vs {tag} (eval 200)"] = [
            {"p_idle": t["refs"]["p_idle"], "p_anchor": s["p_anchor"], "p_hind": s[hk],
             "refs": {k: v["profit"] for k, v in s["baselines"].items()}}
            for t, s in ((t, t["refs"]["floor-sprint"]) for t in mkt.values())]
        day = [t for t in mkt.values() if (t.get("tags") or {}).get("floor_day_ok")]
        sets[f"v5 floor-day vs {tag} (eval {len(day)})"] = [
            {"p_idle": t["refs"]["p_idle"], "p_anchor": d["p_anchor"], "p_hind": d[hk],
             "refs": {"sprint_anchor": t["refs"]["floor-sprint"]["p_anchor"]}}
            for t, d in ((t, t["refs"]["floor-day"]) for t in day)]
    out = ["| Pack, tier | Anchor's C: mean (p10 to p90) | Reference | R | R = 1 | C | Beats anchor "
           "| Above hindsight (any ref) |",
           "|---|---|---|---:|---:|---:|---:|---:|"]
    for label, rows in sets.items():
        caps = sorted((r["p_anchor"] - r["p_idle"]) / (r["p_hind"] - r["p_idle"]) for r in rows)
        above = sum(v > r["p_hind"] + 1e-6 for r in rows for v in [r["p_anchor"], *r["refs"].values()])
        for i, k in enumerate(rows[0]["refs"]):
            have = [r for r in rows if r["refs"].get(k) is not None]
            rr = [reward(r["refs"][k], r["p_idle"], r["p_anchor"]) for r in have]
            out.append(" | ".join([
                f"| {label if i == 0 else ''}",
                f"{statistics.mean(caps):.3f} ({caps[len(caps) // 10]:.2f} to {caps[9 * len(caps) // 10]:.2f})"
                if i == 0
                else "", k, f"{statistics.mean(rr):.3f}", f"{share(rr, 1.0):.2f}",
                f"{statistics.mean(scales(r['refs'][k], r)['C'] for r in have):.3f}",
                f"{statistics.mean(float(r['refs'][k] > r['p_anchor'] + 1e-6) for r in have):.2f}",
                str(above) if i == 0 else ""]) + " |")
    return out


def main() -> None:
    cols = columns()
    for title, lines in [("Sol on R and C", headline_table(cols)), ("Every scale", variants_table(cols)),
                         ("Other anchors", stability_table(cols)), ("Training fitness", training_table(cols)),
                         ("v5 compliant", compliant_table(cols)), ("v5 hindsight", v5_hindsight_lines(cols)),
                         ("References on the eval packs", pack_table())]:
        print(f"## {title}\n")
        print("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
