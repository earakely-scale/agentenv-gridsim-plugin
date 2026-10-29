"""Assemble results/train/4b-dpa/ for registered run 3: summary.json with the verdicts (final vs step 0, the slope of
held-out R against step with its task-bootstrap CI, greedy decoding, the greedy rule, eval-iid), the reported gaps to
runs 1-2, the train diagnostics; the eval files, gzipped episodes, curves.png and the LEVEL UP frames on the 12 days
the earlier runs used. Usage: report_dpa.py SRC RUN1_DIR RUN2_DIR DST."""

import gzip
import json
import shutil
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.task import index_pack  # noqa: E402

SRC, RUN1, RUN2, DST = (Path(a) for a in sys.argv[1:5])
DST.mkdir(parents=True, exist_ok=True)
IDX = index_pack("ercot-dam-v1-eval")
KEYS = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "rate_ok", "rate_overfill", "rate_sell_before_charge",
        "rate_end_short", "rate_rate", "rate_cycle_cap", "rate_all_idle", "rate_malformed", "rate_truncated",
        "completion_len_mean")
B = 10_000


def load(p):
    return json.loads(Path(p).read_text())


def run(res, dec):
    return next(r for r in res["runs"] if r["decoding"] == dec)


def rewards(res, dec):
    return {x["task_id"]: x["reward"] for x in run(res, dec)["per_task"]}


def ci(xs, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (B, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def paired(a, b, tasks):
    d = np.array([a[t] - b[t] for t in tasks])
    return {"mean": round(float(d.mean()), 4), "ci95": ci(d), "win_rate": round(float((d > 0).mean()), 4),
            "tie_rate": round(float((d == 0).mean()), 4)}


def slope(steps, mat):
    """LS slope of the per-checkpoint mean against step, and its 95% CI from resampling the tasks (one resample
    applied to every checkpoint)."""
    x = np.asarray(steps, float)
    xc = x - x.mean()
    mean = mat.mean(1)
    est = float((xc * (mean - mean.mean())).sum() / (xc ** 2).sum())
    idx = np.random.default_rng(0).integers(0, mat.shape[1], (B, mat.shape[1]))
    ms = mat[:, idx].mean(2)
    bs = (xc[:, None] * (ms - ms.mean(0))).sum(0) / (xc ** 2).sum()
    return {"per_step": est, "per_100_steps": round(est * 100, 4),
            "ci95_per_100_steps": [round(float(np.percentile(bs, 2.5)) * 100, 4),
                                   round(float(np.percentile(bs, 97.5)) * 100, 4)],
            "share_of_resamples_above_0": round(float((bs > 0).mean()), 4)}


ev, evi = SRC / "eval", SRC / "eval-iid"
step0 = load(ev / "eval_step-0000.json")
ckpts = sorted((load(p) for p in ev.glob("eval_ckpt-*.json")), key=lambda r: r["runs"][0]["checkpoint_step"])
final = ckpts[-1]
tasks = step0["task_ids"]
assert all(c["task_ids"] == tasks for c in ckpts)
evals = [step0, *ckpts]
steps = [e["runs"][0]["checkpoint_step"] for e in evals]
r1, r2 = load(RUN1 / "eval_trained.json"), load(RUN2 / "eval_trained.json")
r2sft = load(RUN2 / "eval_sft.json")
assert r1["task_ids"] == tasks and r2["task_ids"] == tasks
rules = {n: {t: IDX[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks} for n in ("greedy", "threshold")}
greedy_ci = ci(list(rules["greedy"].values()))
mats = {d: np.array([[rewards(e, d)[t] for t in tasks] for e in evals]) for d in ("sampled", "greedy")}
fs, fg, s0s, s0g = (rewards(final, "sampled"), rewards(final, "greedy"), rewards(step0, "sampled"),
                    rewards(step0, "greedy"))

a = paired(fs, s0s, tasks)
b = slope(steps, mats["sampled"])
n_after = len(ckpts)
prim = {"a_final_minus_step0_sampled": {**a, "met": a["ci95"][0] > 0},
        "b_slope_sampled": {**b, "met": b["ci95_per_100_steps"][0] > 0},
        "checkpoints_after_step0": n_after, "enough_checkpoints": n_after >= 5}
prim["met"] = prim["a_final_minus_step0_sampled"]["met"] and prim["b_slope_sampled"]["met"] and n_after >= 5
g = paired(fg, s0g, tasks)
fsum = run(final, "sampled")["summary"]
sec = {"1_greedy_final_minus_step0": {**g, "bar": "ci95 lower >= -0.01", "met": g["ci95"][0] >= -0.01},
       "2_final_vs_greedy_rule": {"reward_mean": fsum["reward_mean"], "ci95": fsum["ci95"],
                                  "valid_rate": fsum["valid_rate"], "greedy_rule_ci95": greedy_ci,
                                  "cis_apart": fsum["ci95"][0] > greedy_ci[1],
                                  "valid_ge_98": fsum["valid_rate"] >= 0.98,
                                  "paired_minus_greedy_rule": paired(fs, rules["greedy"], tasks),
                                  "met": fsum["ci95"][0] > greedy_ci[1] and fsum["valid_rate"] >= 0.98}}
iid = {}
if (evi / "eval_final.json").exists():
    i0, i1 = load(evi / "eval_sft.json"), load(evi / "eval_final.json")
    it = i0["task_ids"]
    assert i1["task_ids"] == it
    for d in ("sampled", "greedy"):
        iid[d] = {"step0": {k: run(i0, d)["summary"][k] for k in KEYS},
                  "final": {k: run(i1, d)["summary"][k] for k in KEYS},
                  "final_minus_step0": paired(rewards(i1, d), rewards(i0, d), it)}
    sec["3_eval_iid_final_minus_step0_sampled"] = {**iid["sampled"]["final_minus_step0"],
                                                   "met": iid["sampled"]["final_minus_step0"]["ci95"][0] > 0}
reported = {d: {"final_minus_run1_final": paired(rewards(final, d), rewards(r1, d), tasks),
                "final_minus_run2_final": paired(rewards(final, d), rewards(r2, d), tasks),
                "final_minus_run2_sft10k_l40s": paired(rewards(final, d), rewards(r2sft, d), tasks),
                "step0_minus_run2_sft10k_l40s": paired(rewards(step0, d), rewards(r2sft, d), tasks)}
            for d in ("sampled", "greedy")}
reported["greedy_slope"] = slope(steps, mats["greedy"])
curve = [{"step": s, **{d: {k: run(e, d)["summary"][k] for k in KEYS} for d in ("sampled", "greedy")}}
         for s, e in zip(steps, evals, strict=True)]

log = [json.loads(x) for x in (SRC / "train" / "train_log.jsonl").read_text().splitlines()]


def window(key, lo, hi):
    v = [r[key] for r in log if lo <= r["step"] <= hi and r.get(key) is not None]
    return round(float(np.mean(v)), 5) if v else None


last = log[-1]["step"]
wins = [(lo, min(lo + 49, last)) for lo in range(1, last + 1, 50)]
diag = {f"{lo}-{hi}": {k: window(k, lo, hi) for k in ("reward_mean", "valid_rate", "feasible_rate", "share_opt",
                                                       "hour_adv_mean", "share_hours_neg", "entropy", "kl",
                                                       "clip_frac", "ratio_mean", "grad_norm", "rate_overfill",
                                                       "rate_end_short", "rate_sell_before_charge",
                                                       "rate_cycle_cap", "rate_rate", "rate_malformed",
                                                       "rate_truncated", "completion_len_mean", "mapped_rate",
                                                       "step_s")}
        for lo, hi in wins}
notes = [{"step": r["step"], "note": r["note"]} for r in log if r.get("note")]
summary = {"label": "registered run 3 (docs/prereg/v1-train-4b-dpa.md)", "model": "Qwen/Qwen3-4B",
           "revision": "1cfa9a7208912126459214e8b04321603b3df60c", "start": "run 2's SFT-10k, merged",
           "n_tasks": len(tasks), "steps_trained": last, "final_checkpoint_step": steps[-1],
           "evaluated_steps": steps, "primary": prim, "secondary": sec,
           "verdict": {"primary": "MET" if prim["met"] else "NOT MET",
                       **{k: "MET" if v["met"] else "NOT MET" for k, v in sec.items()}},
           "reported": reported, "curve": curve, "eval_iid": iid,
           "greedy_rule": {"reward_mean": round(float(np.mean(list(rules["greedy"].values()))), 4),
                           "ci95": greedy_ci},
           "threshold_rule": {"reward_mean": round(float(np.mean(list(rules["threshold"].values()))), 4)},
           "diagnostics": {"windows": diag, "notes": notes,
                           "entropy_below_0.02_steps": sum(r["entropy"] < 0.02 for r in log),
                           "hours_scored": sum(r["hours_scored"] for r in log)}}
(DST / "summary.json").write_text(json.dumps(summary, indent=1))

shutil.copy(ev / "eval_step-0000.json", DST / "eval_step0.json")
(DST / "eval_checkpoints.json").write_text(json.dumps(ckpts, indent=1))
shutil.copy(ev / f"eval_ckpt-{steps[-1]:04d}.json", DST / "eval_trained.json")
for name in ("sft", "final"):
    if (evi / f"eval_{name}.json").exists():
        shutil.copy(evi / f"eval_{name}.json", DST / f"eval_iid_{'step0' if name == 'sft' else name}.json")
for f in ("train_log.jsonl", "samples.jsonl"):
    shutil.copy(SRC / "train" / f, DST / f)
epd = DST / "episodes"
if epd.exists():
    shutil.rmtree(epd)
epd.mkdir()
for d, pre in ((ev / "episodes", ""), (evi / "episodes", "iid-")):
    for f in sorted(d.glob("*.jsonl")):
        with f.open("rb") as i, gzip.open(epd / f"{pre}{f.name}.gz", "wb", compresslevel=9) as o:
            shutil.copyfileobj(i, o)

lv = DST / "levelup"
if lv.exists():
    shutil.rmtree(lv)
lv.mkdir()
days = [{k: d[k] for k in ("task_id", "start", "region", "date", "point")}
        for d in load(RUN2 / "levelup" / "index.json")["days"]]
frames = [("base", RUN1 / "episodes" / "base-sampled.jsonl"), ("0000", ev / "episodes" / "step-0000-sampled.jsonl")]
frames += [(f"{s:04d}", ev / "episodes" / f"ckpt-{s:04d}-sampled.jsonl") for s in steps[1:]]
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

k = 10


def roll(key):
    v = np.array([r.get(key) if r.get(key) is not None else np.nan for r in log], float)
    return np.convolve(v, np.ones(k) / k, mode="valid")


xs = [r["step"] for r in log]
fig, ax = plt.subplots(4, 1, figsize=(10.5, 13), sharex=True, gridspec_kw={"height_ratios": [3, 1.6, 1.4, 1.4]})
p = ax[0]
for d, col, mk in (("sampled", "#1f5aa6", "o-"), ("greedy", "#7a4fa3", "s--")):
    m = mats[d].mean(1)
    lohi = np.array([run(e, d)["summary"]["ci95"] for e in evals])
    p.plot(steps, m, mk, color=col, lw=1.8, ms=4, label=f"run 3 held-out, all 200 eval-2025 tasks, {d}"
           + (" (T 0.7)" if d == "sampled" else ""))
    if d == "sampled":
        p.fill_between(steps, lohi[:, 0], lohi[:, 1], color=col, alpha=0.12, lw=0, label="95% CI, sampled")
        fit = np.polyfit(steps, m, 1)
        p.plot(steps, np.polyval(fit, steps), color=col, lw=1, ls=":",
               label=f"LS fit, slope {b['per_100_steps']:+.4f} per 100 steps "
                     f"[{b['ci95_per_100_steps'][0]:+.4f}, {b['ci95_per_100_steps'][1]:+.4f}]")
gm = summary["greedy_rule"]["reward_mean"]
p.axhspan(greedy_ci[0], greedy_ci[1], color="#444", alpha=0.07, lw=0)
for y, lab, c, ls in ((gm, f"greedy rule {gm:.3f} (band: 95% CI)", "#444", "--"),
                      (run(r1, "sampled")["summary"]["reward_mean"], "run 1 (T4) final, 200 tasks, L40S", "#a0522d",
                       "-."),
                      (run(r2, "sampled")["summary"]["reward_mean"], "run 2 (T5) final, 200 tasks, L40S", "#e07a1f",
                       "-."),
                      (run(r2sft, "sampled")["summary"]["reward_mean"], "run 2 SFT-10k, 200 tasks, L40S", "#2a7f3f",
                       ":")):
    p.axhline(y, color=c, ls=ls, lw=1, label=f"{lab} {y:.3f}" if "greedy" not in lab else lab)
p.set_ylim(0.70, 1.0)
p.set_ylabel("held-out reward R")
p.set_title("Registered run 3: Qwen3-4B SFT-10k + policy gradient with the DP's exact per-hour advantages", fontsize=10)
p.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
q = ax[1]
q.plot(xs, [r["reward_mean"] for r in log], color="#9bb7d4", lw=0.7, label="train R per step (32 days, T 1.0)")
q.plot(xs[k - 1:], roll("reward_mean"), color="#1f5aa6", lw=1.8, label=f"train R, {k}-step mean")
q.plot(xs[k - 1:], roll("feasible_rate"), color="#2a7f3f", lw=1.4, label="feasible")
q.plot(xs[k - 1:], roll("share_opt"), color="#e07a1f", lw=1.4, label="share at R = 1")
q.plot(xs[k - 1:], roll("rate_overfill"), color="#d1495b", lw=1.2, label="overfill")
q.plot(xs[k - 1:], roll("rate_end_short"), color="#7a4fa3", lw=1.2, label="end short")
q.set_ylim(0, 1.02)
q.set_ylabel("train rollouts")
q.legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=7)
h = ax[2]
h.plot(xs[k - 1:], roll("hour_adv_mean"), color="#1f5aa6", lw=1.6, label="mean A_t per executed hour")
h.set_ylabel("A_t (reward units)")
h2 = h.twinx()
h2.plot(xs[k - 1:], roll("share_hours_neg"), color="#d1495b", lw=1.4, ls="--", label="share of hours with A_t < 0")
h2.set_ylabel("share")
h.legend(loc="upper left", bbox_to_anchor=(1.12, 1.0), fontsize=7)
h2.legend(loc="upper left", bbox_to_anchor=(1.12, 0.6), fontsize=7)
e = ax[3]
e.plot(xs, [r["entropy"] for r in log], color="#1f5aa6", lw=1.0, label="policy entropy (per token)")
e.axhline(0.02, color="#d1495b", lw=0.8, ls=":")
e.set_ylabel("entropy")
e2 = e.twinx()
e2.plot(xs, [r["kl"] for r in log], color="#e07a1f", lw=1.0, label="KL to SFT-10k (k3, per token)")
e2.set_ylabel("KL")
e.legend(loc="upper left", bbox_to_anchor=(1.12, 1.0), fontsize=7)
e2.legend(loc="upper left", bbox_to_anchor=(1.12, 0.6), fontsize=7)
e.set_xlabel("training step")
fig.tight_layout()
fig.savefig(DST / "curves.png", dpi=150)
print(json.dumps({"verdict": summary["verdict"], "primary": prim, "secondary": sec,
                  "curve": [(c["step"], c["sampled"]["reward_mean"], c["greedy"]["reward_mean"]) for c in curve],
                  "reported": {d: {k2: v["mean"] for k2, v in reported[d].items()} for d in ("sampled", "greedy")},
                  "eval_iid": {d: v["final_minus_step0"] for d, v in iid.items()}}, indent=1))
