"""Assemble results/train/confirm-sft10k/ for the confirmatory eval (docs/prereg/v1-confirm-sft10k.md): summary.json
with the bar verdicts, the SFT-vs-final comparison and the pipeline check against run 2's committed per-task rewards;
the eval files and gzipped episodes. Usage: report_confirm.py SRC RUN2_DIR DST."""

import gzip
import json
import re
import sys
from pathlib import Path

import numpy as np

from gridsim_core.task import index_pack, load_pack

SRC, RUN2, DST = (Path(a) for a in sys.argv[1:4])
DST.mkdir(parents=True, exist_ok=True)
PACKS = {"eval_iid": ("ercot-dam-v1-eval-iid", "eval-iid"), "rtcb": ("ercot-dam-v1-rtcb", "rtcb")}
BARS = {"eval_iid": "PRIMARY / SECONDARY", "rtcb": "RTCB-PRIMARY / RTCB-SECONDARY"}
STARTS = ("empty", "half", "full")
KEYS = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "rate_ok", "rate_all_idle", "rate_overfill",
        "rate_sell_before_charge", "rate_end_short", "rate_rate", "rate_cycle_cap", "rate_malformed", "rate_truncated",
        "completion_len_mean")
NAMES = {"sft": "run 2: 4B SFT-10k (step 0)", "trained": "run 2: 4B SFT-10k + GRPO 310 (final)"}


def ci(xs, n=10_000, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def load(p):
    return json.loads(Path(p).read_text())


def run(res, dec):
    return next(r for r in res["runs"] if r["decoding"] == dec)


def rewards(res, dec):
    return {x["task_id"]: x["reward"] for x in run(res, dec)["per_task"]}


def paired(a, b, tasks):
    d = np.array([a[t] - b[t] for t in tasks])
    return {"mean": round(float(d.mean()), 4), "ci95": ci(d), "win_rate": round(float((d > 0).mean()), 4),
            "tie_rate": round(float((d == 0).mean()), 4)}


def start_state(t):
    b = t["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def by_start(rw, idx):
    out = {}
    for st in STARTS:
        v = [r for t, r in rw.items() if start_state(idx[t]) == st]
        out[st] = {"n": len(v), "reward_mean": round(float(np.mean(v)), 4), "ci95": ci(v)}
    return out


def verdict(primary, p):
    if primary:
        return "CONFIRMED"
    if p["ci95"][0] > 0:
        return "NOT CONFIRMED, BUT AHEAD PAIRED"
    return "REFUTED" if p["ci95"][1] < 0 else "NOT CONFIRMED"


def grpo(p):
    return "GRPO added" if p["ci95"][0] > 0 else "GRPO cost" if p["ci95"][1] < 0 else "no difference shown"


def day(tid):
    return re.match(r"dam-v1-(\d{4}-\d{2}-\d{2})-", tid).group(1)


sft_ids = load(RUN2 / "sft_task_ids.json")
train = load_pack("ercot-dam-v1-train")
summary = {"label": "confirmatory, pre-registered (docs/prereg/v1-confirm-sft10k.md)", "model": "Qwen/Qwen3-4B",
           "revision": "1cfa9a7208912126459214e8b04321603b3df60c",
           "post_hoc_observation": {"pack": "ercot-dam-v1-eval (200 eval-2025 tasks)", "sft10k_sampled": 0.8405,
                                    "sft10k_ci95": [0.8015, 0.877], "greedy_rule_ci95": [0.7259, 0.7998]},
           "overlap": {}, "verdicts": {}, "bars": {}, "comparison": {}, "packs": {}, "paired": {}}
for key, (pack, short) in PACKS.items():
    tasks_all = load_pack(pack)
    ids, days = {t["task_id"] for t in tasks_all}, {day(t["task_id"]) for t in tasks_all}
    summary["overlap"][key] = {
        "tasks": len(ids), "dates": len(days), "ids_in_sft10k": len(ids & set(sft_ids)),
        "dates_in_sft10k": len(days & {day(t) for t in sft_ids}),
        "ids_in_train_pack": len(ids & {t["task_id"] for t in train}),
        "dates_in_train_pack": len(days & {day(t["task_id"]) for t in train})}
    idx = index_pack(pack)
    res = {lab: load(SRC / f"{short}-{lab}" / f"eval_{lab}.json") for lab in ("sft", "trained")}
    tasks = res["sft"]["task_ids"]
    assert res["trained"]["task_ids"] == tasks and len(tasks) == len(tasks_all)
    rules = {n: {t: idx[t]["refs"]["foresight"]["baselines"][n]["reward"] for t in tasks}
             for n in ("greedy", "threshold", "clock")}
    rows = []
    for lab, r in res.items():
        for dec in ("sampled", "greedy"):
            x = run(r, dec)
            rows.append({"model": NAMES[lab], "decoding": dec, "checkpoint_step": x["checkpoint_step"],
                         **{k: x["summary"].get(k) for k in KEYS}, "by_start": by_start(rewards(r, dec), idx),
                         "by_curriculum": x["summary"].get("by_curriculum")})
    for n, rw in rules.items():
        rows.append({"model": f"rule:{n}", "reward_mean": round(float(np.mean(list(rw.values()))), 4),
                     "ci95": ci(list(rw.values())), "by_start": by_start(rw, idx)})
    summary["packs"][key] = {"pack": pack, "n_tasks": len(tasks), "rows": rows}
    gci = ci(list(rules["greedy"].values()))
    for dec in ("sampled", "greedy"):
        s, t = rewards(res["sft"], dec), rewards(res["trained"], dec)
        pp = {"sft_minus_greedy": paired(s, rules["greedy"], tasks),
              "sft_minus_threshold": paired(s, rules["threshold"], tasks),
              "final_minus_greedy": paired(t, rules["greedy"], tasks),
              "final_minus_threshold": paired(t, rules["threshold"], tasks),
              "final_minus_sft": paired(t, s, tasks)}
        summary["paired"][f"{key}_{dec}"] = pp
        x = run(res["sft"], dec)["summary"]
        primary = x["ci95"][0] > gci[1] and x["valid_rate"] >= 0.98
        summary["bars"].setdefault(key, {})[dec] = {
            "bars": BARS[key], "role": "registered test" if dec == "sampled" else "reported (secondary decoding)",
            "model": NAMES["sft"], "reward_mean": x["reward_mean"], "ci95": x["ci95"], "valid_rate": x["valid_rate"],
            "greedy_rule_mean": round(float(np.mean(list(rules["greedy"].values()))), 4), "greedy_rule_ci95": gci,
            "cis_apart": x["ci95"][0] > gci[1], "valid_ge_98": x["valid_rate"] >= 0.98, "primary_met": primary,
            "paired_minus_greedy": pp["sft_minus_greedy"], "secondary_met": pp["sft_minus_greedy"]["ci95"][0] > 0,
            "verdict": verdict(primary, pp["sft_minus_greedy"])}
        summary["comparison"].setdefault(key, {})[dec] = {
            "role": ("registered (eval-iid, sampled)" if key == "eval_iid" and dec == "sampled" else "reported"),
            "final_minus_sft": pp["final_minus_sft"], "reading": grpo(pp["final_minus_sft"])}
    summary["verdicts"][key] = summary["bars"][key]["sampled"]["verdict"]
    for lab in ("sft", "trained"):
        (DST / f"{key}_{'final' if lab == 'trained' else lab}.json").write_text(json.dumps(res[lab], indent=1))

ck, run2 = SRC / "check", {"sft": load(RUN2 / "eval_sft.json"), "trained": load(RUN2 / "eval_trained.json")}
gate = load(ck / "gate.json")
check = {"pack": "ercot-dam-v1-eval (run 2's 200 tasks)", "gate": gate, "runs": {}}
for lab in ("sft", "trained"):
    mine = load(ck / f"eval_{lab}.json")
    assert mine["task_ids"] == run2[lab]["task_ids"]
    tasks = mine["task_ids"]
    for dec in ("sampled", "greedy"):
        a, b = rewards(mine, dec), rewards(run2[lab], dec)
        m, o = run(mine, dec), run(run2[lab], dec)
        same = sum(x["actions"] == y["actions"] for x, y in zip(m["per_task"], o["per_task"], strict=True))
        check["runs"][f"{lab}_{dec}"] = {
            "this_box": m["summary"]["reward_mean"], "this_box_ci95": m["summary"]["ci95"],
            "this_box_valid": m["summary"]["valid_rate"], "run2": o["summary"]["reward_mean"],
            "run2_ci95": o["summary"]["ci95"], "same_schedule_share": round(same / len(tasks), 4),
            "this_box_minus_run2": paired(a, b, tasks)}
    (DST / f"check_eval2025_{'final' if lab == 'trained' else lab}.json").write_text(json.dumps(mine, indent=1))
summary["pipeline_check"] = check

ep = DST / "episodes"
ep.mkdir(exist_ok=True)
for d in sorted(SRC.iterdir()):
    for f in sorted((d / "episodes").glob("*.jsonl")) if (d / "episodes").is_dir() else []:
        name = f"{'check-eval2025' if d.name == 'check' else d.name.rsplit('-', 1)[0]}-{f.stem}.jsonl.gz"
        with gzip.GzipFile(ep / name, "wb", mtime=0) as g:
            g.write(f.read_bytes())
(DST / "summary.json").write_text(json.dumps(summary, indent=1))
print(json.dumps({"verdicts": summary["verdicts"], "bars": {k: {d: {x: v[x] for x in ("reward_mean", "ci95",
      "valid_rate", "greedy_rule_ci95", "primary_met", "secondary_met")} | {"paired": v["paired_minus_greedy"]}
      for d, v in b.items()} for k, b in summary["bars"].items()},
      "comparison": summary["comparison"], "check": check["runs"]}, indent=1))
