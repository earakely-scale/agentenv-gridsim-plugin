"""Assemble results/train/arm2c/: summary.json (arm 2c next to arm 2, arm 2b and the rules, paired gaps, R by start
state), eval files, curves.png over arms 2, 2b and 2c, train_log.jsonl, episodes/ and the 12 LEVEL UP days with every
frame. Usage: report2c.py ARM2C_SRC ARM2B_DIR ARM2_DIR DST."""

import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.task import index_pack  # noqa: E402

SRC, ARM2B, ARM2, DST = (Path(a) for a in sys.argv[1:5])
DST.mkdir(parents=True, exist_ok=True)
IDX = index_pack("ercot-dam-v1-eval")
STARTS = ("empty", "half", "full")


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


evals = {"arm 2: sft2+grpo75": json.loads((ARM2 / "eval_trained.json").read_text()),
         "arm 2b: grpo180": json.loads((ARM2B / "eval_trained.json").read_text())}
if (SRC / "eval" / "eval_trained.json").exists():
    evals["arm 2c: +grpo continuation"] = json.loads((SRC / "eval" / "eval_trained.json").read_text())
tasks = evals["arm 2: sft2+grpo75"]["task_ids"]
assert all(e["task_ids"] == tasks for e in evals.values())
rules = {n: {t: IDX[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks}
         for n in ("greedy", "threshold", "clock")}
keys = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "rate_ok", "rate_all_idle", "rate_overfill",
        "rate_sell_before_charge", "rate_end_short", "rate_rate", "rate_cycle_cap", "rate_malformed",
        "rate_truncated", "completion_len_mean")
summary = {"n_tasks": len(tasks), "label": "arm 2c (exploratory continuation)", "rows": [], "paired": {}}
for name, res in evals.items():
    for dec in ("sampled", "greedy"):
        r = run(res, dec)
        summary["rows"].append({"model": name, "decoding": dec, "checkpoint_step": r["checkpoint_step"],
                                **{k: r["summary"].get(k) for k in keys}, "by_start": by_start(rewards(res, dec)),
                                "by_curriculum": r["summary"].get("by_curriculum")})
for name, rw in rules.items():
    summary["rows"].append({"model": f"rule:{name}", "reward_mean": round(float(np.mean(list(rw.values()))), 4),
                            "ci95": ci(list(rw.values())), "by_start": by_start(rw)})
if "arm 2c: +grpo continuation" in evals:
    for dec in ("sampled", "greedy"):
        b = rewards(evals["arm 2c: +grpo continuation"], dec)
        for o, rw in (("arm2b", rewards(evals["arm 2b: grpo180"], dec)),
                      ("arm2", rewards(evals["arm 2: sft2+grpo75"], dec)),
                      ("threshold", rules["threshold"]), ("greedy", rules["greedy"])):
            d = np.array([b[t] - rw[t] for t in tasks])
            summary["paired"][f"arm2c_{dec}_minus_{o}"] = {"mean": round(float(d.mean()), 4), "ci95": ci(d),
                                                           "win_rate": round(float((d > 0).mean()), 4)}
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

for f in ("eval_start.json", "eval_trained.json"):
    if (SRC / "eval" / f).exists():
        shutil.copy(SRC / "eval" / f, DST / f)
ck2b = sorted((json.loads(p.read_text()) for p in (SRC / "eval").glob("eval_ckpt-*.json")),
              key=lambda r: r["runs"][0]["checkpoint_step"])
ck2 = json.loads((ARM2 / "eval_checkpoints.json").read_text()) + json.loads(
    (ARM2B / "eval_checkpoints.json").read_text())
start_file = SRC / "eval" / "eval_start.json"
start = json.loads(start_file.read_text()) if start_file.exists() else None
(DST / "eval_checkpoints.json").write_text(json.dumps(
    [{"checkpoint_step": c["runs"][0]["checkpoint_step"], "n_tasks": c["n_tasks"], **c["runs"][0]["summary"]}
     for c in ck2b], indent=1))
log2 = [json.loads(line) for line in (ARM2 / "train_log.jsonl").open()]
log2b = [json.loads(line) for line in (ARM2B / "train_log.jsonl").open()]
log = [json.loads(line) for line in (SRC / "grpo" / "train_log.jsonl").open()]
shutil.copy(SRC / "grpo" / "train_log.jsonl", DST / "train_log.jsonl")
ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for f in (SRC / "eval" / "episodes").glob("*.jsonl"):
    shutil.copy(f, ep / f.name)

lv = DST / "levelup"
if lv.exists():
    shutil.rmtree(lv)
shutil.copytree(ARM2B / "levelup", lv)
index = json.loads((lv / "index.json").read_text())
pick = [d["task_id"] for d in index["days"]]
frames = [(f"{c['runs'][0]['checkpoint_step']:04d}", ep / f"ckpt-{c['runs'][0]['checkpoint_step']:04d}-sampled.jsonl")
          for c in ck2b]
if "arm 2c: +grpo continuation" in evals:
    frames.append((f"{run(evals['arm 2c: +grpo continuation'], 'sampled')['checkpoint_step']:04d}",
                   ep / "trained-sampled.jsonl"))
for name, f in frames:
    eps = {e["task_id"]: e for e in map(json.loads, f.open())}
    for t in pick:
        (lv / t / f"{name}.json").write_text(json.dumps(eps[t], indent=1))
index["frames"] += [n for n, _ in frames]
for d in index["days"]:
    d["frames"] = {p.stem: json.loads(p.read_text())["reward"] for p in sorted((lv / d["task_id"]).glob("*.json"))}
(lv / "index.json").write_text(json.dumps(index, indent=1))

all_log = ([{**r, "x": r["step"]} for r in log2] + [{**r, "x": r["arm_step"]} for r in log2b]
           + [{**r, "x": r["arm_step"]} for r in log])
xs = [r["x"] for r in all_log]
k = 10


def roll(key):
    v = np.array([r.get(key, np.nan) for r in all_log], float)
    return np.convolve(v, np.ones(k) / k, mode="valid")


fig, ax = plt.subplots(3, 1, figsize=(10.5, 10), sharex=True, gridspec_kw={"height_ratios": [3, 2, 1.4]})
a = ax[0]
a.plot(xs, [r["reward_mean"] for r in all_log], color="#9bb7d4", lw=0.8,
       label="train reward per step (64 rollouts, T 1.1)")
a.plot(xs[k - 1:], roll("reward_mean"), color="#1f5aa6", lw=2, label=f"train reward, {k}-step mean")
for st, col in (("full", "#d1495b"), ("empty", "#2a7f3f"), ("half", "#7a4fa3")):
    a.plot(xs[k - 1:], roll(f"reward_{st}"), color=col, lw=1, ls="--", label=f"train reward, starts {st}")
cs = [c["checkpoint_step"] for c in ck2] + [c["runs"][0]["checkpoint_step"] for c in ck2b]
cv = [c["reward_mean"] for c in ck2] + [c["runs"][0]["summary"]["reward_mean"] for c in ck2b]
sft2_runs = json.loads((ARM2 / "eval_sft2.json").read_text())["runs"]
sft2_50 = float(np.mean([x["reward"] for x in sft2_runs[0]["per_task"][:50]]))
a2_50 = float(np.mean([x["reward"] for x in run(evals["arm 2: sft2+grpo75"], "sampled")["per_task"][:50]]))
a2b_50 = float(np.mean([x["reward"] for x in run(evals["arm 2b: grpo180"], "sampled")["per_task"][:50]]))
pts = sorted([(0, sft2_50), (75, a2_50), (180, a2b_50)] + list(zip(cs, cv, strict=True)))
if "arm 2c: +grpo continuation" in evals:
    r = run(evals["arm 2c: +grpo continuation"], "sampled")
    pts.append((r["checkpoint_step"], float(np.mean([x["reward"] for x in r["per_task"][:50]]))))
a.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color="#e07a1f", lw=1.8,
       label="held-out 2025, fixed 50 tasks (T 0.7); step 0 = SFT-2")
for name, res, col in (("arm 2 (step 75)", evals["arm 2: sft2+grpo75"], "#888"),
                       ("arm 2b (step 180)", evals["arm 2b: grpo180"], "#a0522d"),
                       ("arm 2c final", evals.get("arm 2c: +grpo continuation"), "#e07a1f")):
    if res:
        m = run(res, "sampled")["summary"]["reward_mean"]
        a.plot([run(res, "sampled")["checkpoint_step"]], [m], "s", color=col, ms=8,
               label=f"{name}: 200-task eval {m:.3f}")
g, th = float(np.mean(list(rules["greedy"].values()))), float(np.mean(list(rules["threshold"].values())))
for y, lab, c, ls in ((1.0, "DP optimum 1.0", "#2a7f3f", "-"), (g, f"greedy rule {g:.3f}", "#444", "--"),
                      (th, f"threshold rule {th:.3f}", "#888", ":"), (0.2, "idle 0.2", "#b07a1a", "-.")):
    a.axhline(y, color=c, ls=ls, lw=1)
    a.text(xs[-1], y + 0.01, lab, ha="right", va="bottom", fontsize=8, color=c)
for axx in ax:
    axx.axvline(75.5, color="#bbb", lw=1)
    axx.axvline(180.5, color="#bbb", lw=1)
a.text(76.5, 0.05, "arm 2b (seed 1)", fontsize=8, color="#888")
a.text(181.5, 0.05, "arm 2c (seed 2)", fontsize=8, color="#888")
a.set_ylim(0, 1.05)
a.set_ylabel("reward R (0-1)")
a.set_title("Arms 2 + 2b + 2c (exploratory): Qwen3-1.7B, SoC-aware SFT-1500 + GRPO 8x8 at T 1.1", fontsize=10)
a.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
b = ax[1]
for key, lab, col in (("valid_rate", "valid submit", "#1f5aa6"), ("feasible_rate", "feasible", "#2a7f3f"),
                      ("rate_overfill", "overfill", "#d1495b"), ("rate_sell_before_charge", "sell before charge",
                                                                  "#b07a1a"),
                      ("rate_end_short", "end short", "#7a4fa3"), ("rate_malformed", "malformed", "#444")):
    b.plot(xs[k - 1:], roll(key), label=lab, color=col, lw=1.6)
b.set_ylim(0, 1.02)
b.set_ylabel(f"share, {k}-step mean")
b.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
c = ax[2]
c.plot(xs, [r.get("entropy", np.nan) for r in all_log], color="#1f5aa6", lw=1.2, label="policy entropy")
c.axhline(0.02, color="#d1495b", lw=0.8, ls=":")
c.set_ylabel("entropy")
c2 = c.twinx()
c2.plot(xs[k - 1:], roll("frac_zero_spread_groups"), color="#999", ls="--", lw=1.4, label="zero-spread groups")
c2.set_ylim(0, 1)
c2.set_ylabel("zero-spread share")
c.legend(loc="upper left", bbox_to_anchor=(1.08, 1.0), fontsize=7)
c2.legend(loc="upper left", bbox_to_anchor=(1.08, 0.7), fontsize=7)
c.set_xlabel("GRPO step (arm 2: 1-75, arm 2b: 76-180, arm 2c: 181-)")
fig.tight_layout()
fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps({"rows": [{k2: r.get(k2) for k2 in ("model", "decoding", "reward_mean", "ci95", "valid_rate",
                                                     "feasible_rate")} | {"by_start": {s: v["reward_mean"] for s, v in
                                                                                       r["by_start"].items()}}
                           for r in summary["rows"]], "paired": summary["paired"],
                  "start_check": start and start["runs"][0]["summary"]["reward_mean"]}, indent=1))
