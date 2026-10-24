"""Assemble results/train/ from the box's results: curves.png, eval_base.json, eval_trained.json, eval_checkpoints.json,
train_log.jsonl and episodes/, plus a summary.json with CIs and paired differences. Usage: report.py SRC DST."""

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

SRC, DST = Path(sys.argv[1]), Path(sys.argv[2])
DST.mkdir(parents=True, exist_ok=True)


def load(name):
    p = SRC / "eval" / f"eval_{name}.json"
    return json.loads(p.read_text()) if p.exists() else None


def ci(xs, n=10_000, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def run(res, dec):
    return next(r for r in res["runs"] if r["decoding"] == dec)


def rewards(res, dec):
    return {x["task_id"]: x["reward"] for x in run(res, dec)["per_task"]}


base, sft, trained = load("base"), load("sft"), load("trained")
ckpts = sorted((json.loads(p.read_text()) for p in (SRC / "eval").glob("eval_ckpt-*.json")),
               key=lambda r: r["runs"][0]["checkpoint_step"])
log = [json.loads(line) for line in (SRC / "grpo" / "train_log.jsonl").open()]
pure = [json.loads(line) for line in (SRC / "grpo_pure" / "train_log.jsonl").open()]
tasks = trained["task_ids"] if trained else sft["task_ids"]
from gridsim_core.task import index_pack  # noqa: E402

idx = index_pack("ercot-dam-v1-eval")
refs = {name: {t: idx[t]["refs"]["foresight"]["baselines"][name]["reward"] for t in tasks}
        for name in ("greedy", "threshold", "clock", "random")}

summary = {"n_tasks": len(tasks), "rows": []}
for name, res in (("base", base), ("sft200", sft), ("sft200+grpo", trained)):
    if not res:
        continue
    for dec in ("sampled", "greedy"):
        r = run(res, dec)
        s = r["summary"]
        summary["rows"].append({"model": name, "decoding": dec, "reward_mean": s["reward_mean"], "ci95": s["ci95"],
                                "valid_rate": s["valid_rate"], "feasible_rate": s["feasible_rate"],
                                "rate_all_idle": s["rate_all_idle"], "rate_overfill": s["rate_overfill"],
                                "rate_sell_before_charge": s["rate_sell_before_charge"],
                                "rate_end_short": s["rate_end_short"], "rate_rate": s["rate_rate"],
                                "rate_cycle_cap": s["rate_cycle_cap"], "rate_malformed": s["rate_malformed"],
                                "rate_truncated": s["rate_truncated"], "completion_len_mean": s["completion_len_mean"]})
for name, rs in refs.items():
    v = [rs[t] for t in tasks]
    summary["rows"].append({"model": f"baseline:{name}", "reward_mean": round(float(np.mean(v)), 4), "ci95": ci(v),
                            "valid_rate": 1.0})
summary["rows"] += [{"model": "baseline:idle", "reward_mean": 0.2, "ci95": [0.2, 0.2]},
                    {"model": "baseline:dp", "reward_mean": 1.0, "ci95": [1.0, 1.0]}]
if trained:
    paired = {}
    for dec in ("sampled", "greedy"):
        tr = rewards(trained, dec)
        for other, o in (("greedy", refs["greedy"]), ("threshold", refs["threshold"]), ("sft200", rewards(sft, dec))):
            d = np.array([tr[t] - o[t] for t in tasks])
            paired[f"trained_{dec}_minus_{other}"] = {"mean": round(float(d.mean()), 4), "ci95": ci(d),
                                                       "win_rate": round(float((d > 0).mean()), 4)}
    summary["paired"] = paired
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

shutil.copy(SRC / "grpo" / "train_log.jsonl", DST / "train_log.jsonl")
shutil.copy(SRC / "grpo_pure" / "train_log.jsonl", DST / "train_log_pure_grpo.jsonl")
if (SRC / "grpo_lr5e-6" / "train_log.jsonl").exists():
    shutil.copy(SRC / "grpo_lr5e-6" / "train_log.jsonl", DST / "train_log_lr5e-6.jsonl")
for name, res in (("base", base), ("sft", sft), ("trained", trained)):
    if res:
        (DST / f"eval_{name}.json").write_text(json.dumps(res, indent=1))
if ckpts:
    (DST / "eval_checkpoints.json").write_text(json.dumps(
        [{"checkpoint_step": c["runs"][0]["checkpoint_step"], "n_tasks": c["n_tasks"], **c["runs"][0]["summary"]}
         for c in ckpts], indent=1))
ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for f in (SRC / "eval" / "episodes").glob("*.jsonl"):
    shutil.copy(f, ep / f.name)

steps = [r["step"] for r in log]
mean = np.array([r["reward_mean"] for r in log])
k = 10
smooth = np.convolve(mean, np.ones(k) / k, mode="valid")
fig, ax = plt.subplots(2, 1, figsize=(10.5, 8), sharex=True, gridspec_kw={"height_ratios": [3, 2]})
a = ax[0]
a.plot(steps, mean, color="#9bb7d4", lw=0.8, label="train reward, per step (32 rollouts)")
a.plot(steps[k - 1:], smooth, color="#1f5aa6", lw=2, label=f"train reward, {k}-step mean")
a.plot([r["step"] for r in pure], [r["reward_mean"] for r in pure], color="#000", lw=2.5,
       label="GRPO from the base model, no warm start (0 valid)")
low = SRC / "grpo_lr5e-6" / "train_log.jsonl"
if low.exists():
    lo = [json.loads(line) for line in low.open()]
    a.plot([r["step"] for r in lo], [r["reward_mean"] for r in lo], color="#e39b3c", lw=1,
           label="SFT + GRPO at the pre-registered lr 5e-6 (stopped at step 31)")
if ckpts:
    cs = [0] + [c["runs"][0]["checkpoint_step"] for c in ckpts]
    cv = [float(np.mean([x["reward"] for x in run(sft, "sampled")["per_task"][:50]]))] + [
        c["runs"][0]["summary"]["reward_mean"] for c in ckpts]
    if trained:
        cs.append(run(trained, "sampled")["checkpoint_step"])
        cv.append(float(np.mean([x["reward"] for x in run(trained, "sampled")["per_task"][:50]])))
    a.plot(cs, cv, "o-", color="#d1495b", lw=1.5, label="held-out 2025, fixed 50 tasks (T 0.7); step 0 = SFT-200")
g = float(np.mean(list(refs["greedy"].values())))
th = float(np.mean(list(refs["threshold"].values())))
for y, lab, c, ls in ((1.0, "DP optimum 1.0", "#2a7f3f", "-"), (g, f"greedy rule {g:.3f} (eval)", "#444", "--"),
                      (th, f"threshold rule {th:.3f} (eval)", "#888", ":"), (0.2, "idle 0.2", "#b07a1a", "-.")):
    a.axhline(y, color=c, ls=ls, lw=1)
    a.text(steps[-1], y + 0.01, lab, ha="right", va="bottom", fontsize=8, color=c)
for s, lab in ((0, "C0"), (int(0.2 * steps[-1]), "C1"), (int(0.6 * steps[-1]), "C2")):
    a.axvline(s, color="#ccc", lw=0.8)
    a.text(s + 2, 0.02, lab, fontsize=8, color="#888")
a.set_ylim(0, 1.05)
a.set_xlim(-5, steps[-1] + 5)
a.set_ylabel("reward R (0-1)")
a.set_title("GridSimEnv v1 path B: Qwen3-1.7B, SFT-200 warm start + GRPO (LoRA, one L4)")
a.legend(loc="upper left", bbox_to_anchor=(0.0, 0.93), fontsize=8, framealpha=0.95)
b = ax[1]


def roll(key):
    v = np.array([r[key] for r in log])
    return np.convolve(v, np.ones(k) / k, mode="valid")


for key, lab, col in (("valid_rate", "valid submit", "#1f5aa6"), ("feasible_rate", "feasible (no rule broken)", "#2a7f3f"),
                      ("rate_overfill", "overfill", "#d1495b"), ("rate_sell_before_charge", "sell before charge", "#b07a1a"),
                      ("rate_end_short", "end short", "#7a4fa3"), ("rate_malformed", "malformed (not 24 ints)", "#444"),
                      ("frac_zero_spread_groups", "groups with zero reward spread", "#999")):
    b.plot(steps[k - 1:], roll(key), label=lab, color=col, lw=1.6, ls=":" if key == "frac_zero_spread_groups" else "-")
b.set_title(f"train rollouts, {k}-step means", fontsize=9)
b.set_ylim(0, 1.02)
b.set_xlabel("GRPO step")
b.set_ylabel("share of rollouts")
b.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
fig.tight_layout()
fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps(summary, indent=1))
