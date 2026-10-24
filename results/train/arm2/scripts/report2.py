"""Assemble results/train/arm2/: summary.json (arm 2 rows next to base, SFT-200, arm 1 and the rules, paired gaps, R by
start state), eval files, curves.png, train_log.jsonl, episodes/ and levelup/<task>/<step>.json for 12 fixed days.
Usage: report2.py ARM2_SRC ARM1_DIR DST."""

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.task import index_pack  # noqa: E402

SRC, ARM1, DST = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
DST.mkdir(parents=True, exist_ok=True)
IDX = index_pack("ercot-dam-v1-eval")
STARTS = ("empty", "half", "full")


def start_state(t: dict) -> str:
    b = t["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def ci(xs, n=10_000, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def run(res, dec):
    return next(r for r in res["runs"] if r["decoding"] == dec)


def per_task(res, dec):
    return {x["task_id"]: x for x in run(res, dec)["per_task"]}


def by_start(rewards: dict) -> dict:
    out = {}
    for st in STARTS:
        v = [r for t, r in rewards.items() if start_state(IDX[t]) == st]
        out[st] = {"n": len(v), "reward_mean": round(float(np.mean(v)), 4), "ci95": ci(v)}
    return out


evals = {"base": json.loads((ARM1 / "eval_base.json").read_text()),
         "sft200 (arm 1 warm start)": json.loads((ARM1 / "eval_sft.json").read_text()),
         "arm 1: sft200+grpo280": json.loads((ARM1 / "eval_trained.json").read_text()),
         "sft2 (arm 2 warm start)": json.loads((SRC / "eval" / "eval_sft2.json").read_text())}
if (SRC / "eval" / "eval_trained.json").exists():
    evals["arm 2: sft2+grpo"] = json.loads((SRC / "eval" / "eval_trained.json").read_text())
tasks = evals["base"]["task_ids"]
assert all(e["task_ids"] == tasks for e in evals.values())
rules = {n: {t: IDX[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks}
         for n in ("greedy", "threshold", "clock", "random")}

summary = {"n_tasks": len(tasks), "label": "arm 2 (exploratory, not pre-registered)", "rows": [], "paired": {}}
keys = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "rate_ok", "rate_all_idle", "rate_overfill",
        "rate_sell_before_charge", "rate_end_short", "rate_rate", "rate_cycle_cap", "rate_malformed",
        "rate_truncated", "completion_len_mean")
for name, res in evals.items():
    for dec in ("sampled", "greedy"):
        r = run(res, dec)
        rw = {t: x["reward"] for t, x in per_task(res, dec).items()}
        summary["rows"].append({"model": name, "decoding": dec, "checkpoint_step": r["checkpoint_step"],
                                **{k: r["summary"].get(k) for k in keys}, "by_start": by_start(rw)})
for name, rw in rules.items():
    summary["rows"].append({"model": f"rule:{name}", "reward_mean": round(float(np.mean(list(rw.values()))), 4),
                            "ci95": ci(list(rw.values())), "valid_rate": 1.0, "by_start": by_start(rw)})
summary["rows"] += [{"model": "rule:idle", "reward_mean": 0.2}, {"model": "dp optimum", "reward_mean": 1.0}]
if "arm 2: sft2+grpo" in evals:
    for dec in ("sampled", "greedy"):
        a2 = {t: x["reward"] for t, x in per_task(evals["arm 2: sft2+grpo"], dec).items()}
        others = {"arm1": {t: x["reward"] for t, x in per_task(evals["arm 1: sft200+grpo280"], dec).items()},
                  "sft2": {t: x["reward"] for t, x in per_task(evals["sft2 (arm 2 warm start)"], dec).items()},
                  "threshold": rules["threshold"], "greedy": rules["greedy"]}
        for o, rw in others.items():
            d = np.array([a2[t] - rw[t] for t in tasks])
            summary["paired"][f"arm2_{dec}_minus_{o}"] = {"mean": round(float(d.mean()), 4), "ci95": ci(d),
                                                          "win_rate": round(float((d > 0).mean()), 4)}
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

for f in ("eval_sft2.json", "eval_trained.json"):
    if (SRC / "eval" / f).exists():
        shutil.copy(SRC / "eval" / f, DST / f)
ckpts = sorted((json.loads(p.read_text()) for p in (SRC / "eval").glob("eval_ckpt-*.json")),
               key=lambda r: r["runs"][0]["checkpoint_step"])
(DST / "eval_checkpoints.json").write_text(json.dumps(
    [{"checkpoint_step": c["runs"][0]["checkpoint_step"], "n_tasks": c["n_tasks"], **c["runs"][0]["summary"]}
     for c in ckpts], indent=1))
log = [json.loads(line) for line in (SRC / "grpo" / "train_log.jsonl").open()]
shutil.copy(SRC / "grpo" / "train_log.jsonl", DST / "train_log.jsonl")
if (SRC / "crashed_run1" / "train_log.jsonl").exists():
    shutil.copy(SRC / "crashed_run1" / "train_log.jsonl", DST / "train_log_crashed_run1.jsonl")
for f in ("sft2_task_ids.json", "sft2_meta.json"):
    if (SRC / f).exists():
        shutil.copy(SRC / f, DST / f)
ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for f in (SRC / "eval" / "episodes").glob("*.jsonl"):
    shutil.copy(f, ep / f.name)
for f in ("base-sampled.jsonl", "base-greedy.jsonl"):
    shutil.copy(ARM1 / "episodes" / f, ep / f)

first50 = tasks[:50]
pick = []
for st in STARTS:
    pool = sorted((t for t in first50 if start_state(IDX[t]) == st), key=lambda t: (IDX[t]["date"], t))
    pick += [pool[int(i)] for i in np.linspace(0, len(pool) - 1, 4).round()]
frames = [("base", ep / "base-sampled.jsonl"), ("0000", ep / "sft2-sampled.jsonl")]
frames += [(f"{c['runs'][0]['checkpoint_step']:04d}", ep / f"ckpt-{c['runs'][0]['checkpoint_step']:04d}-sampled.jsonl")
           for c in ckpts]
if "arm 2: sft2+grpo" in evals:
    frames.append((f"{run(evals['arm 2: sft2+grpo'], 'sampled')['checkpoint_step']:04d}", ep / "trained-sampled.jsonl"))
lv = DST / "levelup"
if lv.exists():
    shutil.rmtree(lv)
index = []
for name, f in frames:
    eps = {e["task_id"]: e for e in map(json.loads, f.open())}
    for t in pick:
        d = lv / t
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.json").write_text(json.dumps(eps[t], indent=1))
for t in pick:
    index.append({"task_id": t, "start": start_state(IDX[t]), "region": IDX[t]["region"], "date": IDX[t]["date"],
                  "point": IDX[t]["settlement_point"], "frames": {
                      p.stem: json.loads(p.read_text())["reward"] for p in sorted((lv / t).glob("*.json"))}})
(lv / "index.json").write_text(json.dumps({"decoding": "sampled T 0.7, top_p 0.8, top_k 20, seed 0",
                                           "frames": [n for n, _ in frames], "days": index}, indent=1))

steps = [r["step"] for r in log]
k = min(10, len(log))


def roll(key, rows=log):
    v = np.array([r.get(key, np.nan) for r in rows], float)
    return np.convolve(v, np.ones(k) / k, mode="valid")


fig, ax = plt.subplots(3, 1, figsize=(10.5, 10), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.4]})
a = ax[0]
a.plot(steps, [r["reward_mean"] for r in log], color="#9bb7d4", lw=0.8, label="train reward per step (64 rollouts, T 1.1)")
a.plot(steps[k - 1:], roll("reward_mean"), color="#1f5aa6", lw=2, label=f"train reward, {k}-step mean")
for st, col in (("full", "#d1495b"), ("empty", "#2a7f3f"), ("half", "#7a4fa3")):
    a.plot(steps[k - 1:], roll(f"reward_{st}"), color=col, lw=1, ls="--", label=f"train reward, starts {st}")
sft2_50 = float(np.mean([x["reward"] for x in run(evals["sft2 (arm 2 warm start)"], "sampled")["per_task"][:50]]))
cs, cv = [0], [sft2_50]
for c in ckpts:
    cs.append(c["runs"][0]["checkpoint_step"])
    cv.append(c["runs"][0]["summary"]["reward_mean"])
if "arm 2: sft2+grpo" in evals:
    r = run(evals["arm 2: sft2+grpo"], "sampled")
    cs.append(r["checkpoint_step"])
    cv.append(float(np.mean([x["reward"] for x in r["per_task"][:50]])))
a.plot(cs, cv, "o-", color="#e07a1f", lw=1.8, label="held-out 2025, fixed 50 tasks (T 0.7); step 0 = SFT-2")
a1 = float(np.mean([x["reward"] for x in run(evals["arm 1: sft200+grpo280"], "sampled")["per_task"]]))
g, th = float(np.mean(list(rules["greedy"].values()))), float(np.mean(list(rules["threshold"].values())))
for y, lab, c, ls in ((1.0, "DP optimum 1.0", "#2a7f3f", "-"), (g, f"greedy rule {g:.3f}", "#444", "--"),
                      (th, f"threshold rule {th:.3f}", "#888", ":"), (a1, f"arm 1 final {a1:.3f}", "#9bb7d4", "-"),
                      (0.2, "idle 0.2", "#b07a1a", "-.")):
    a.axhline(y, color=c, ls=ls, lw=1)
    a.text(steps[-1], y + 0.01, lab, ha="right", va="bottom", fontsize=8, color=c)
a.set_ylim(0, 1.05)
a.set_ylabel("reward R (0-1)")
a.set_title("Arm 2 (exploratory): Qwen3-1.7B, SoC-aware SFT-1500 + GRPO 8x8 at T 1.1", fontsize=10)
a.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
b = ax[1]
for key, lab, col in (("valid_rate", "valid submit", "#1f5aa6"), ("feasible_rate", "feasible", "#2a7f3f"),
                      ("rate_overfill", "overfill", "#d1495b"), ("rate_sell_before_charge", "sell before charge",
                                                                  "#b07a1a"),
                      ("rate_end_short", "end short", "#7a4fa3"), ("rate_malformed", "malformed", "#444")):
    b.plot(steps[k - 1:], roll(key), label=lab, color=col, lw=1.6)
b.set_ylim(0, 1.02)
b.set_ylabel(f"share, {k}-step mean")
b.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
c = ax[2]
c.plot(steps, [r.get("entropy", np.nan) for r in log], color="#1f5aa6", lw=1.2, label="policy entropy")
c.axhline(0.02, color="#d1495b", lw=0.8, ls=":")
c.text(steps[0], 0.022, "0.02", fontsize=7, color="#d1495b")
c.set_ylabel("entropy")
c2 = c.twinx()
c2.plot(steps[k - 1:], roll("frac_zero_spread_groups"), color="#999", ls="--", lw=1.4, label="zero-spread groups")
c2.set_ylim(0, 1)
c2.set_ylabel("zero-spread share")
c.legend(loc="upper left", bbox_to_anchor=(1.08, 1.0), fontsize=7)
c2.legend(loc="upper left", bbox_to_anchor=(1.08, 0.7), fontsize=7)
c.set_xlabel("GRPO step")
fig.tight_layout()
fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps({"rows": [{k2: r.get(k2) for k2 in ("model", "decoding", "reward_mean", "ci95", "valid_rate",
                                                     "by_start")} for r in summary["rows"]],
                  "paired": summary["paired"], "levelup": pick}, indent=1))
