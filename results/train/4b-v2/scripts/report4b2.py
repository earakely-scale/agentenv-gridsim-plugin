"""Assemble results/train/4b-v2/ for registered run 2: summary.json with the bar verdicts, the registered comparisons
(run 2 vs run 1, SFT-10k vs SFT-1500, GRPO's gain), CIs, paired gaps and the diagnostics; the eval files, curves.png
with run 1 as reference lines, train_log.jsonl, episodes/ and the LEVEL UP frames on the 12 days the 1.7B arms used.
Usage: report4b2.py SRC RUN1_DIR ARM2C_DIR DST."""

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.task import index_pack  # noqa: E402

SRC, RUN1, ARM2C, DST = (Path(a) for a in sys.argv[1:5])
DST.mkdir(parents=True, exist_ok=True)
IDX = index_pack("ercot-dam-v1-eval")
STARTS = ("empty", "half", "full")
KEYS = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "rate_ok", "rate_all_idle", "rate_overfill",
        "rate_sell_before_charge", "rate_end_short", "rate_rate", "rate_cycle_cap", "rate_malformed", "rate_truncated",
        "completion_len_mean")


def start_state(t):
    b = t["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def ci(xs, n=10_000, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def run(res, dec):
    return next(r for r in res["runs"] if r["decoding"] == dec)


def rewards(res, dec):
    return {x["task_id"]: x["reward"] for x in run(res, dec)["per_task"]}


def by_start(rw):
    out = {}
    for st in STARTS:
        v = [r for t, r in rw.items() if start_state(IDX[t]) == st]
        out[st] = {"n": len(v), "reward_mean": round(float(np.mean(v)), 4), "ci95": ci(v)}
    return out


def load(p):
    return json.loads(Path(p).read_text())


def paired(a, b, tasks):
    d = np.array([a[t] - b[t] for t in tasks])
    return {"mean": round(float(d.mean()), 4), "ci95": ci(d), "win_rate": round(float((d > 0).mean()), 4),
            "tie_rate": round(float((d == 0).mean()), 4)}


ev = SRC / "eval"
v2 = {"sft": load(ev / "eval_sft.json")}
if (ev / "eval_trained.json").exists():
    v2["trained"] = load(ev / "eval_trained.json")
r1 = {"base": load(RUN1 / "eval_base.json"), "sft": load(RUN1 / "eval_sft.json"),
      "trained": load(RUN1 / "eval_trained.json")}
arm2c = load(ARM2C / "eval_trained.json")
tasks = arm2c["task_ids"]
assert all(e["task_ids"] == tasks for e in [*v2.values(), *r1.values()])
rules = {n: {t: IDX[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks}
         for n in ("greedy", "threshold", "clock")}
names = {"Qwen3-4B base (zero-shot, run 1's eval)": r1["base"], "run 1: 4B SFT-1500 (step 0)": r1["sft"],
         "run 1: 4B SFT-1500 + GRPO 330 (final)": r1["trained"], "run 2: 4B SFT-10k (step 0)": v2["sft"]}
if "trained" in v2:
    names["run 2: 4B SFT-10k + GRPO (final)"] = v2["trained"]
summary = {"n_tasks": len(tasks), "label": "registered run 2 (docs/prereg/v1-train-4b-v2.md)",
           "model": "Qwen/Qwen3-4B", "revision": "1cfa9a7208912126459214e8b04321603b3df60c", "bars": {},
           "comparisons": {}, "contributions": {}, "rows": [], "paired": {}, "diagnostics": {}}
for name, res in [*names.items(), ("1.7B arm 2c (step 330)", arm2c)]:
    for dec in ("sampled", "greedy"):
        r = run(res, dec)
        summary["rows"].append({"model": name, "decoding": dec, "checkpoint_step": r["checkpoint_step"],
                                **{k: r["summary"].get(k) for k in KEYS}, "by_start": by_start(rewards(res, dec)),
                                "by_curriculum": r["summary"].get("by_curriculum")})
for name, rw in rules.items():
    summary["rows"].append({"model": f"rule:{name}", "reward_mean": round(float(np.mean(list(rw.values()))), 4),
                            "ci95": ci(list(rw.values())), "by_start": by_start(rw)})
greedy_ci = ci(list(rules["greedy"].values()))
for dec in ("sampled", "greedy"):
    others = {"greedy": rules["greedy"], "threshold": rules["threshold"], "arm2c_1.7b": rewards(arm2c, dec),
              "run1_final": rewards(r1["trained"], dec), "run1_sft": rewards(r1["sft"], dec),
              "base": rewards(r1["base"], dec), "run2_sft": rewards(v2["sft"], dec)}
    for head in ("sft", "trained"):
        if head not in v2:
            continue
        b = rewards(v2[head], dec)
        for o, rw in others.items():
            if not (head == "sft" and o == "run2_sft"):
                summary["paired"][f"run2_{head}_{dec}_minus_{o}"] = paired(b, rw, tasks)
    summary["paired"][f"run1_final_{dec}_minus_run1_sft"] = paired(rewards(r1["trained"], dec),
                                                                 rewards(r1["sft"], dec), tasks)
    if "trained" in v2:
        s = run(v2["trained"], dec)["summary"]
        p = summary["paired"][f"run2_trained_{dec}_minus_greedy"]
        summary["bars"][dec] = {
            "role": "primary bar and secondary bar" if dec == "sampled" else "reported (secondary decoding)",
            "checkpoint_step": run(v2["trained"], dec)["checkpoint_step"], "reward_mean": s["reward_mean"],
            "ci95": s["ci95"], "valid_rate": s["valid_rate"], "greedy_rule_ci95": greedy_ci,
            "cis_apart": s["ci95"][0] > greedy_ci[1], "valid_ge_98": s["valid_rate"] >= 0.98,
            "primary_met": s["ci95"][0] > greedy_ci[1] and s["valid_rate"] >= 0.98,
            "paired_minus_greedy": p, "secondary_met": p["ci95"][0] > 0}
        comp = {"run2_final_minus_run1_final": summary["paired"][f"run2_trained_{dec}_minus_run1_final"],
                "run2_sft_minus_run1_sft": summary["paired"][f"run2_sft_{dec}_minus_run1_sft"],
                "run2_final_minus_run2_sft": summary["paired"][f"run2_trained_{dec}_minus_run2_sft"]}
    else:
        comp = {"run2_sft_minus_run1_sft": summary["paired"][f"run2_sft_{dec}_minus_run1_sft"]}
    summary["comparisons"][dec] = {k: {**v, "shown": v["ci95"][0] > 0} for k, v in comp.items()}
heads = (("run1_sft", r1["sft"]), ("run1_final", r1["trained"]), ("run2_sft", v2["sft"]))
mean = {k: run(v, "sampled")["summary"]["reward_mean"] for k, v in heads}
if "trained" in v2:
    mean["run2_final"] = run(v2["trained"], "sampled")["summary"]["reward_mean"]
summary["contributions"] = {
    "decoding": "sampled", "means": mean,
    "sft_change_1": summary["paired"]["run2_sft_sampled_minus_run1_sft"],
    "grpo_run1": summary["paired"]["run1_final_sampled_minus_run1_sft"],
    **({"grpo_run2": summary["paired"]["run2_trained_sampled_minus_run2_sft"],
        "total_run2_minus_run1": summary["paired"]["run2_trained_sampled_minus_run1_final"]}
       if "trained" in v2 else {}),
    "note": "grpo_run2 is GRPO with change 2 on top of change 1's warm start; no arm isolates change 2"}
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

for label in ("sft", "trained"):
    if (ev / f"eval_{label}.json").exists():
        shutil.copy(ev / f"eval_{label}.json", DST / f"eval_{label}.json")
ck = sorted((load(p) for p in ev.glob("eval_ckpt-*.json")), key=lambda r: r["runs"][0]["checkpoint_step"])
(DST / "eval_checkpoints.json").write_text(json.dumps(
    [{"checkpoint_step": c["runs"][0]["checkpoint_step"], "n_tasks": c["n_tasks"], **c["runs"][0]["summary"]}
     for c in ck], indent=1))
log_file = SRC / "grpo" / "train_log.jsonl"
log = [json.loads(line) for line in log_file.open()] if log_file.exists() else []
if log:
    shutil.copy(log_file, DST / "train_log.jsonl")
log1 = [json.loads(line) for line in (RUN1 / "train_log.jsonl").open()]
ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for f in (ev / "episodes").glob("*.jsonl"):
    shutil.copy(f, ep / f.name)


def window(rows, key, lo, hi):
    v = [r[key] for r in rows if lo < r["step"] <= hi and r.get(key) is not None]
    return round(float(np.mean(v)), 4) if v else None


if log:
    diag = {}
    for name, rows, keys in (("run2", log, ("frac_zero_spread_groups", "frac_zero_spread_fresh",
                                            "frac_zero_spread_replay", "frac_zero_spread_kept", "entropy",
                                            "reward_mean", "reward_mean_kept", "reward_mean_all")),
                             ("run1", log1, ("frac_zero_spread_groups", "entropy", "reward_mean"))):
        diag[name] = {k: {f"{lo + 1}-{min(hi, len(rows))}": window(rows, k, lo, hi) for lo, hi in
                          ((0, 50), (50, 100), (100, 150), (150, 200), (200, 250), (250, 300), (300, 330))}
                      for k in keys}
        diag[name]["steps"] = len(rows)
        diag[name]["entropy_below_0.02_steps"] = sum(r.get("entropy", 1) < 0.02 for r in rows)
        diag[name]["first_step_entropy_below_0.02"] = next((r["step"] for r in rows if r.get("entropy", 1) < 0.02),
                                                           None)
        diag[name]["entropy_first_last"] = [rows[0].get("entropy"), rows[-1].get("entropy")]
    diag["run2"]["topped_up_steps"] = sum(r.get("frac_zero_spread_kept", 0) > 0 for r in log)
    diag["run2"]["topped_up_groups"] = int(round(sum(r.get("frac_zero_spread_kept", 0) * r.get("groups_kept", 8)
                                                     for r in log)))
    diag["run2"]["replay_share_mean"] = round(float(np.mean([r.get("groups_replay", 0) / 16 for r in log])), 4)
    diag["run2"]["seen_days_final"] = log[-1].get("seen_days")
    diag["run2"]["guard"] = {"armed_step": next((r["step"] for r in log if r.get("guard_armed")), None),
                             "notes": [(r["step"], r["note"]) for r in log if "cliff" in (r.get("note") or "")]}
    summary["diagnostics"] = diag
    (DST / "summary.json").write_text(json.dumps(summary, indent=1))

lv = DST / "levelup"
if lv.exists():
    shutil.rmtree(lv)
lv.mkdir()
days = [{k: d[k] for k in ("task_id", "start", "region", "date", "point")}
        for d in load(ARM2C / "levelup" / "index.json")["days"]]
frames = [("base", RUN1 / "episodes" / "base-sampled.jsonl"), ("0000", ep / "sft-sampled.jsonl")]
frames += [(f"{c['runs'][0]['checkpoint_step']:04d}", ep / f"ckpt-{c['runs'][0]['checkpoint_step']:04d}-sampled.jsonl")
           for c in ck]
if "trained" in v2:
    frames.append((f"{run(v2['trained'], 'sampled')['checkpoint_step']:04d}", ep / "trained-sampled.jsonl"))
for name, f in frames:
    eps = {e["task_id"]: e for e in map(json.loads, f.open())}
    for d in days:
        (lv / d["task_id"]).mkdir(exist_ok=True)
        (lv / d["task_id"] / f"{name}.json").write_text(json.dumps(eps[d["task_id"]], indent=1))
for d in days:
    d["frames"] = {n: json.loads((lv / d["task_id"] / f"{n}.json").read_text())["reward"] for n, _ in frames}
(lv / "index.json").write_text(json.dumps({"decoding": "sampled T 0.7, top_p 0.8, top_k 20, seed 0",
                                           "base": "run 1's base eval (same model, tasks and decoding)",
                                           "frames": [n for n, _ in frames], "days": days}, indent=1))

if log:
    k = 10

    def roll(rows, key):
        v = np.array([r.get(key, np.nan) for r in rows], float)
        return np.convolve(v, np.ones(k) / k, mode="valid")

    xs, xs1 = [r["step"] for r in log], [r["step"] for r in log1]
    fig, ax = plt.subplots(3, 1, figsize=(10.5, 10), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.4]})
    a = ax[0]
    a.plot(xs, [r["reward_mean"] for r in log], color="#9bb7d4", lw=0.8,
           label="run 2 train reward per step (fresh draws, T 1.1)")
    a.plot(xs[k - 1:], roll(log, "reward_mean"), color="#1f5aa6", lw=2,
           label=f"run 2 train reward, fresh, {k}-step mean")
    a.plot(xs[k - 1:], roll(log, "reward_mean_kept"), color="#5e8fcf", lw=1, ls="--",
           label="run 2 train reward, kept groups")
    a.plot(xs1[k - 1:], roll(log1, "reward_mean"), color="#999", lw=1.4, label="run 1 train reward, 10-step mean")
    sft50 = float(np.mean([x["reward"] for x in run(v2["sft"], "sampled")["per_task"][:50]]))
    pts = [(0, sft50)] + [(c["runs"][0]["checkpoint_step"], c["runs"][0]["summary"]["reward_mean"]) for c in ck]
    r1ck = load(RUN1 / "eval_checkpoints.json")
    r1sft50 = float(np.mean([x["reward"] for x in run(r1["sft"], "sampled")["per_task"][:50]]))
    r1fin50 = float(np.mean([x["reward"] for x in run(r1["trained"], "sampled")["per_task"][:50]]))
    p1 = [(0, r1sft50)] + [(c["checkpoint_step"], c["reward_mean"]) for c in r1ck] + [(330, r1fin50)]
    a.plot([p[0] for p in p1], [p[1] for p in p1], "o--", color="#c9a27e", lw=1.2, ms=3,
           label="run 1 held-out, fixed 50 tasks")
    if "trained" in v2:
        r = run(v2["trained"], "sampled")
        pts.append((r["checkpoint_step"], float(np.mean([x["reward"] for x in r["per_task"][:50]]))))
        m, lo_hi = r["summary"]["reward_mean"], r["summary"]["ci95"]
        a.errorbar([r["checkpoint_step"]], [m], yerr=[[m - lo_hi[0]], [lo_hi[1] - m]], fmt="s", color="#e07a1f",
                   ms=8, capsize=4, label=f"run 2 final, 200-task eval {m:.3f} [{lo_hi[0]:.3f}, {lo_hi[1]:.3f}]")
    a.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color="#e07a1f", lw=1.8,
           label="run 2 held-out 2025, fixed 50 tasks (T 0.7); step 0 = SFT-10k")
    g = float(np.mean(list(rules["greedy"].values())))
    th = float(np.mean(list(rules["threshold"].values())))
    f1 = run(r1["trained"], "sampled")["summary"]["reward_mean"]
    s2 = run(v2["sft"], "sampled")["summary"]["reward_mean"]
    a.axhspan(greedy_ci[0], greedy_ci[1], color="#444", alpha=0.08, lw=0)
    for y, lab, c, ls in ((1.0, "DP optimum 1.0", "#2a7f3f", "-"),
                          (g, f"greedy rule {g:.3f} (band: 95% CI)", "#444", "--"),
                          (f1, f"run 1 final {f1:.3f}", "#a0522d", "-."),
                          (s2, f"run 2 SFT-10k, 200 tasks {s2:.3f}", "#2a7f3f", ":"),
                          (th, f"threshold rule {th:.3f}", "#888", ":"), (0.2, "idle 0.2", "#b07a1a", "-.")):
        a.axhline(y, color=c, ls=ls, lw=1, label=lab)
    a.set_ylim(0, 1.05)
    a.set_ylabel("reward R (0-1)")
    a.set_title("Registered run 2: Qwen3-4B, SFT-10k with the DP's rule + GRPO with adaptive and dynamic sampling",
                fontsize=10)
    a.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    b = ax[1]
    for key, lab, col in (("valid_rate", "valid submit", "#1f5aa6"), ("feasible_rate", "feasible", "#2a7f3f"),
                          ("rate_overfill", "overfill", "#d1495b"),
                          ("rate_sell_before_charge", "sell before charge", "#b07a1a"),
                          ("rate_end_short", "end short", "#7a4fa3"), ("rate_malformed", "malformed", "#444")):
        b.plot(xs[k - 1:], roll(log, key), label=lab, color=col, lw=1.6)
    b.plot(xs1[k - 1:], roll(log1, "feasible_rate"), color="#999", lw=1.2, ls="--", label="run 1 feasible")
    b.set_ylim(0, 1.02)
    b.set_ylabel(f"share (fresh draws), {k}-step mean")
    b.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    c = ax[2]
    c.plot(xs, [r.get("entropy", np.nan) for r in log], color="#1f5aa6", lw=1.2, label="run 2 policy entropy")
    c.plot(xs1, [r.get("entropy", np.nan) for r in log1], color="#999", lw=1.0, label="run 1 policy entropy")
    c.axhline(0.02, color="#d1495b", lw=0.8, ls=":")
    c.set_ylabel("entropy")
    c2 = c.twinx()
    c2.plot(xs[k - 1:], roll(log, "frac_zero_spread_groups"), color="#e07a1f", ls="--", lw=1.4,
            label="run 2 zero-spread, all 16 groups")
    c2.plot(xs[k - 1:], roll(log, "frac_zero_spread_fresh"), color="#e07a1f", ls=":", lw=1.2,
            label="run 2 zero-spread, fresh draws")
    c2.plot(xs[k - 1:], roll(log, "frac_zero_spread_kept"), color="#2a7f3f", ls="-", lw=1.2,
            label="run 2 zero-spread, kept 8")
    c2.plot(xs1[k - 1:], roll(log1, "frac_zero_spread_groups"), color="#999", ls="--", lw=1.2,
            label="run 1 zero-spread")
    c2.set_ylim(0, 1)
    c2.set_ylabel("zero-spread share")
    c.legend(loc="upper left", bbox_to_anchor=(1.08, 1.0), fontsize=7)
    c2.legend(loc="upper left", bbox_to_anchor=(1.08, 0.6), fontsize=7)
    c.set_xlabel("GRPO step")
    fig.tight_layout()
    fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps({"bars": summary["bars"], "comparisons": summary["comparisons"],
                  "contributions": summary["contributions"],
                  "rows": [{k2: r.get(k2) for k2 in ("model", "decoding", "reward_mean", "ci95", "valid_rate",
                                                     "feasible_rate")} for r in summary["rows"]],
                  "diagnostics": summary.get("diagnostics")}, indent=1))
