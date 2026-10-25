"""Assemble results/train/4b/ for the registered Qwen3-4B run: summary.json with the bar verdicts, CIs and paired
gaps (vs greedy, threshold, the 1.7B arm 2c, the SFT-only and base 4B), the eval files, curves.png, train_log.jsonl,
episodes/ and the LEVEL UP frames on the 12 days the 1.7B arms used. Usage: report4b.py SRC ARM2C_DIR DST."""

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.task import index_pack  # noqa: E402

SRC, ARM2C, DST = (Path(a) for a in sys.argv[1:4])
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


ev = SRC / "eval"
evals = {"Qwen3-4B base (zero-shot)": load(ev / "eval_base.json"), "4B SFT-1500 (step 0)": load(ev / "eval_sft.json")}
if (ev / "eval_trained.json").exists():
    evals["4B SFT + GRPO (final)"] = load(ev / "eval_trained.json")
arm2c = load(ARM2C / "eval_trained.json")
tasks = arm2c["task_ids"]
assert all(e["task_ids"] == tasks for e in evals.values())
rules = {n: {t: IDX[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks}
         for n in ("greedy", "threshold", "clock")}
summary = {"n_tasks": len(tasks), "label": "registered run (docs/prereg/v1-train-4b.md)", "model": "Qwen/Qwen3-4B",
           "revision": "1cfa9a7208912126459214e8b04321603b3df60c", "bars": {}, "rows": [], "paired": {}}
for name, res in [*evals.items(), ("1.7B arm 2c (step 330)", arm2c)]:
    for dec in ("sampled", "greedy"):
        r = run(res, dec)
        summary["rows"].append({"model": name, "decoding": dec, "checkpoint_step": r["checkpoint_step"],
                                **{k: r["summary"].get(k) for k in KEYS}, "by_start": by_start(rewards(res, dec)),
                                "by_curriculum": r["summary"].get("by_curriculum")})
for name, rw in rules.items():
    summary["rows"].append({"model": f"rule:{name}", "reward_mean": round(float(np.mean(list(rw.values()))), 4),
                            "ci95": ci(list(rw.values())), "by_start": by_start(rw)})
others = {"greedy": lambda dec: rules["greedy"], "threshold": lambda dec: rules["threshold"],
          "arm2c_1.7b": lambda dec: rewards(arm2c, dec),
          "sft": lambda dec: rewards(evals["4B SFT-1500 (step 0)"], dec),
          "base": lambda dec: rewards(evals["Qwen3-4B base (zero-shot)"], dec)}
heads = {"trained": evals.get("4B SFT + GRPO (final)"), "sft": evals["4B SFT-1500 (step 0)"]}
for hname, res in heads.items():
    if not res:
        continue
    for dec in ("sampled", "greedy"):
        b = rewards(res, dec)
        for o, f in others.items():
            if o == hname:
                continue
            rw = f(dec)
            d = np.array([b[t] - rw[t] for t in tasks])
            summary["paired"][f"{hname}_{dec}_minus_{o}"] = {"mean": round(float(d.mean()), 4), "ci95": ci(d),
                                                             "win_rate": round(float((d > 0).mean()), 4)}
greedy_ci = ci(list(rules["greedy"].values()))
if heads["trained"]:
    for dec in ("sampled", "greedy"):
        s = run(heads["trained"], dec)["summary"]
        p = summary["paired"][f"trained_{dec}_minus_greedy"]
        summary["bars"][dec] = {
            "role": "primary bar and secondary bar" if dec == "sampled" else "reported (secondary decoding)",
            "checkpoint_step": run(heads["trained"], dec)["checkpoint_step"],
            "reward_mean": s["reward_mean"], "ci95": s["ci95"], "valid_rate": s["valid_rate"],
            "greedy_rule_ci95": greedy_ci,
            "cis_apart": s["ci95"][0] > greedy_ci[1], "valid_ge_98": s["valid_rate"] >= 0.98,
            "primary_met": s["ci95"][0] > greedy_ci[1] and s["valid_rate"] >= 0.98,
            "paired_minus_greedy": p, "secondary_met": p["ci95"][0] > 0}
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

for label in ("base", "sft", "trained"):
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
ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for f in (ev / "episodes").glob("*.jsonl"):
    shutil.copy(f, ep / f.name)

lv = DST / "levelup"
if lv.exists():
    shutil.rmtree(lv)
lv.mkdir()
days = [{k: d[k] for k in ("task_id", "start", "region", "date", "point")}
        for d in load(ARM2C / "levelup" / "index.json")["days"]]
frames = [("base", ep / "base-sampled.jsonl"), ("0000", ep / "sft-sampled.jsonl")]
frames += [(f"{c['runs'][0]['checkpoint_step']:04d}", ep / f"ckpt-{c['runs'][0]['checkpoint_step']:04d}-sampled.jsonl")
           for c in ck]
if heads["trained"]:
    frames.append((f"{run(heads['trained'], 'sampled')['checkpoint_step']:04d}", ep / "trained-sampled.jsonl"))
for name, f in frames:
    eps = {e["task_id"]: e for e in map(json.loads, f.open())}
    for d in days:
        (lv / d["task_id"]).mkdir(exist_ok=True)
        (lv / d["task_id"] / f"{name}.json").write_text(json.dumps(eps[d["task_id"]], indent=1))
for d in days:
    d["frames"] = {n: json.loads((lv / d["task_id"] / f"{n}.json").read_text())["reward"] for n, _ in frames}
(lv / "index.json").write_text(json.dumps({"decoding": "sampled T 0.7, top_p 0.8, top_k 20, seed 0",
                                           "frames": [n for n, _ in frames], "days": days}, indent=1))

if log:
    xs = [r["step"] for r in log]
    k = 10

    def roll(key):
        v = np.array([r.get(key, np.nan) for r in log], float)
        return np.convolve(v, np.ones(k) / k, mode="valid")

    fig, ax = plt.subplots(3, 1, figsize=(10.5, 10), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.4]})
    a = ax[0]
    a.plot(xs, [r["reward_mean"] for r in log], color="#9bb7d4", lw=0.8,
           label="train reward per step (64 rollouts, T 1.1)")
    a.plot(xs[k - 1:], roll("reward_mean"), color="#1f5aa6", lw=2, label=f"train reward, {k}-step mean")
    for st, col in (("full", "#d1495b"), ("empty", "#2a7f3f"), ("half", "#7a4fa3")):
        a.plot(xs[k - 1:], roll(f"reward_{st}"), color=col, lw=1, ls="--", label=f"train reward, starts {st}")
    sft50 = float(np.mean([x["reward"] for x in run(evals["4B SFT-1500 (step 0)"], "sampled")["per_task"][:50]]))
    pts = [(0, sft50)] + [(c["runs"][0]["checkpoint_step"], c["runs"][0]["summary"]["reward_mean"]) for c in ck]
    if heads["trained"]:
        r = run(heads["trained"], "sampled")
        pts.append((r["checkpoint_step"], float(np.mean([x["reward"] for x in r["per_task"][:50]]))))
        m, lo_hi = r["summary"]["reward_mean"], r["summary"]["ci95"]
        a.errorbar([r["checkpoint_step"]], [m], yerr=[[m - lo_hi[0]], [lo_hi[1] - m]], fmt="s", color="#e07a1f",
                   ms=8, capsize=4, label=f"final, 200-task eval {m:.3f} [{lo_hi[0]:.3f}, {lo_hi[1]:.3f}]")
    a.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color="#e07a1f", lw=1.8,
           label="held-out 2025, fixed 50 tasks (T 0.7); step 0 = SFT")
    g, th = float(np.mean(list(rules["greedy"].values()))), float(np.mean(list(rules["threshold"].values())))
    a2c = run(arm2c, "sampled")["summary"]["reward_mean"]
    a.axhspan(greedy_ci[0], greedy_ci[1], color="#444", alpha=0.08, lw=0)
    for y, lab, c, ls in ((1.0, "DP optimum 1.0", "#2a7f3f", "-"),
                          (g, f"greedy rule {g:.3f} (band: 95% CI)", "#444", "--"),
                          (a2c, f"1.7B arm 2c {a2c:.3f}", "#a0522d", "-."),
                          (th, f"threshold rule {th:.3f}", "#888", ":"), (0.2, "idle 0.2", "#b07a1a", "-.")):
        a.axhline(y, color=c, ls=ls, lw=1, label=lab)
    a.set_ylim(0, 1.05)
    a.set_ylabel("reward R (0-1)")
    a.set_title("Registered run: Qwen3-4B, SoC-aware SFT-1500 + GRPO 8x8 at T 1.1, lr 1e-5 cosine", fontsize=10)
    a.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    b = ax[1]
    for key, lab, col in (("valid_rate", "valid submit", "#1f5aa6"), ("feasible_rate", "feasible", "#2a7f3f"),
                          ("rate_overfill", "overfill", "#d1495b"),
                          ("rate_sell_before_charge", "sell before charge", "#b07a1a"),
                          ("rate_end_short", "end short", "#7a4fa3"), ("rate_malformed", "malformed", "#444")):
        b.plot(xs[k - 1:], roll(key), label=lab, color=col, lw=1.6)
    b.set_ylim(0, 1.02)
    b.set_ylabel(f"share, {k}-step mean")
    b.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
    c = ax[2]
    c.plot(xs, [r.get("entropy", np.nan) for r in log], color="#1f5aa6", lw=1.2, label="policy entropy")
    c.axhline(0.02, color="#d1495b", lw=0.8, ls=":")
    c.set_ylabel("entropy")
    c2 = c.twinx()
    c2.plot(xs[k - 1:], roll("frac_zero_spread_groups"), color="#999", ls="--", lw=1.4, label="zero-spread groups")
    c2.set_ylim(0, 1)
    c2.set_ylabel("zero-spread share")
    c.legend(loc="upper left", bbox_to_anchor=(1.08, 1.0), fontsize=7)
    c2.legend(loc="upper left", bbox_to_anchor=(1.08, 0.7), fontsize=7)
    c.set_xlabel("GRPO step")
    fig.tight_layout()
    fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps({"bars": summary["bars"],
                  "rows": [{k2: r.get(k2) for k2 in ("model", "decoding", "reward_mean", "ci95", "valid_rate",
                                                     "feasible_rate")} for r in summary["rows"]],
                  "paired": summary["paired"]}, indent=1))
