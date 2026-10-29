"""Tables, paired gaps, the two diagnostic verdicts and the chart from the eval_<row>.json files.

Usage: report_diag.py RESULTS_DIR (writes summary.json and r_by_model.png there; prints the README tables)."""

import json
import sys
from pathlib import Path

import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from gridsim_core.task import load_pack  # noqa: E402

D = Path(sys.argv[1])
TRAIN = D.parent
ROWS = {
    "q4b-off512": "Qwen3-4B base, thinking off, 512",
    "q4b-on2048": "Qwen3-4B base, thinking on, 2,048",
    "q4b-on4096": "Qwen3-4B base, thinking on, 4,096",
    "q8b-off512": "Qwen3-8B base, thinking off, 512",
    "q8b-on4096": "Qwen3-8B base, thinking on, 4,096",
    "q14awq-off512": "Qwen3-14B-AWQ base, thinking off, 512",
    "q14awq-on4096": "Qwen3-14B-AWQ base, thinking on, 4,096",
    "sft-off512": "Qwen3-4B SFT-10k, thinking off, 512",
    "sft-on2048": "Qwen3-4B SFT-10k, thinking on, 2,048 (OOD)",
    "q4b-on16384-n50": "Qwen3-4B base, thinking on, 16,384 (first 50 tasks)",
    "q8b-on16384-n50": "Qwen3-8B base, thinking on, 16,384 (first 50 tasks)",
    "q4b-on4096-t06": "Qwen3-4B base, thinking on, 4,096, T 0.6/top_p 0.95",
    "q8b-on4096-t06": "Qwen3-8B base, thinking on, 4,096, T 0.6/top_p 0.95",
    "q14awq-on4096-t06": "Qwen3-14B-AWQ base, thinking on, 4,096, T 0.6/top_p 0.95",
    "sft-on2048-t06": "Qwen3-4B SFT-10k, thinking on, 2,048, T 0.6/top_p 0.95 (OOD)",
}
REASONING = [("q4b-on4096", "q4b-off512", True), ("q8b-on4096", "q8b-off512", True),
             ("q4b-on2048", "q4b-off512", False), ("q14awq-on4096", "q14awq-off512", False),
             ("sft-on2048", "sft-off512", False), ("q4b-on16384-n50", "q4b-off512", False),
             ("q8b-on16384-n50", "q8b-off512", False)]
SIZE = [("q8b-off512", "q4b-off512", True), ("q8b-on4096", "q4b-on4096", True),
        ("q14awq-off512", "q8b-off512", False), ("q14awq-on4096", "q8b-on4096", False),
        ("q8b-on16384-n50", "q4b-on16384-n50", False)]
KEYS = ("reward_mean", "ci95", "valid_rate", "feasible_rate", "exact_optima", "rate_ok", "rate_all_idle",
        "rate_overfill", "rate_sell_before_charge", "rate_rate", "rate_cycle_cap", "rate_end_short", "rate_malformed",
        "rate_truncated", "rate_trunc_in_think", "completion_len_mean", "completion_len_p50", "completion_len_p90",
        "hit_cap_rate", "think_len_mean", "think_closed_rate", "by_start")


def ci(xs, n=10_000, seed=0):
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(seed).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


def rewards(res):
    return {x["task_id"]: x["reward"] for x in res["runs"][0]["per_task"]}


def paired(a, b, tasks):
    d = np.array([a[t] - b[t] for t in tasks])
    return {"mean": round(float(d.mean()), 4), "ci95": ci(d), "win_rate": round(float((d > 0).mean()), 4),
            "tie_rate": round(float((d == 0).mean()), 4)}


def pct(x):
    return "–" if x is None else f"{100 * x:.1f}%".replace(".0%", "%")


def gap(p):
    return f"{p['mean']:+.3f} [{p['ci95'][0]:+.3f}, {p['ci95'][1]:+.3f}]"


def main():
    res = {k: json.loads((D / f"eval_{k}.json").read_text()) for k in ROWS if (D / f"eval_{k}.json").exists()}
    first = res["q4b-off512"]
    tasks = first["task_ids"]
    assert all(r["task_ids"] == tasks[:len(r["task_ids"])] for r in res.values())
    rw = {k: rewards(r) for k, r in res.items()}
    reg = {"registered 4B base (run 1)": json.loads((TRAIN / "4b/eval_base.json").read_text()),
           "registered SFT-10k (run 2)": json.loads((TRAIN / "4b-v2/eval_sft.json").read_text())}
    reg_rw = {k: {x["task_id"]: x["reward"] for x in next(r for r in v["runs"] if r["decoding"] == "sampled")
                  ["per_task"]} for k, v in reg.items()}
    base = first["baselines"]
    rows = {}
    for k, r in res.items():
        run = r["runs"][0]
        s = run["summary"]
        rows[k] = {"name": ROWS[k], "n": r["n_tasks"], "model": r["model"], "revision": r["revision"],
                   "trained": r["trained"],
                   "params": run["params"], "wall_s": run["wall_s"], "prompt_len_mean": run["prompt_len_mean"],
                   "prompts_sha256": run["prompts_sha256"], **{x: s.get(x) for x in KEYS}}
        closed = [x["think_len"] for x in run["per_task"] if x["think_closed"]]
        if run["think"]:
            rows[k]["think_closed_rate"] = round(len(closed) / len(run["per_task"]), 4)
            rows[k]["think_len_mean"] = round(float(np.mean(closed)), 1) if closed else None

    def verdicts(pairs):
        out = []
        for a, b, registered in pairs:
            if a in rw and b in rw:
                sub = [t for t in tasks if t in rw[a] and t in rw[b]]
                p = paired(rw[a], rw[b], sub)
                out.append({"a": a, "b": b, "registered": registered, "n": len(sub), **p, "met": p["ci95"][0] > 0})
        return out

    reasoning, size = verdicts(REASONING), verdicts(SIZE)
    done = {k: {x["task_id"] for x in r["runs"][0]["per_task"] if x["valid"]} for k, r in res.items()}
    for p in reasoning:
        sub = [t for t in tasks if t in done[p["a"]] and t in rw[p["b"]]]
        p["when_on_submits"] = {"n": len(sub), "on": round(float(np.mean([rw[p["a"]][t] for t in sub])), 4) if sub
                                else None, "off": round(float(np.mean([rw[p["b"]][t] for t in sub])), 4) if sub
                                else None}
    greedy = {t: x["refs"]["foresight"]["baselines"]["greedy"]["reward"] for t, x in task_refs(tasks).items()}
    probes = {}
    for k in ("q4b-on16384-n50", "q8b-on16384-n50"):
        if k in rw:
            sub, ok = list(rw[k]), [t for t in rw[k] if t in done[k]]
            probes[k] = {name: {"all": round(float(np.mean([r[t] for t in sub])), 4),
                                "when_probe_submits": round(float(np.mean([r[t] for t in ok])), 4) if ok else None}
                         for name, r in ((k, rw[k]), ("sft-off512", rw["sft-off512"]), ("greedy rule", greedy))}
            probes[k]["n"], probes[k]["n_submitted"] = len(sub), len(ok)
    checks = [{"a": "q4b-off512", "b": "registered 4B base (run 1)"},
              {"a": "sft-off512", "b": "registered SFT-10k (run 2)"}]
    for c in checks:
        if c["a"] in rw:
            c.update(paired(rw[c["a"]], reg_rw[c["b"]], tasks))
    summary = {
        "lane": "diag-reasoning-size", "kind": "diagnostic, pre-registered (docs/prereg/v1-diag-reasoning-size.md)",
        "pack": first["pack"], "n_tasks": len(tasks), "rows": rows,
        "references": {"greedy_rule": base["greedy"], "threshold_rule": base["threshold"],
                       "sft10k_registered": {"reward_mean": 0.8405, "ci95": [0.802, 0.877]}, "idle": 0.2, "dp": 1.0},
        "reasoning_pairs": reasoning, "size_pairs": size, "probe_context": probes, "pipeline_vs_registered": checks,
        "verdicts": {
            "reasoning_helps": any(p["met"] for p in reasoning if p["registered"]),
            "size_helps": any(p["met"] for p in size if p["registered"]),
        },
    }
    (D / "summary.json").write_text(json.dumps(summary, indent=1))
    print_tables(rows, reasoning, size, checks, base, summary["verdicts"])
    print("probe context:", json.dumps(probes))
    chart(rows, base)


def task_refs(ids):
    want = set(ids)
    return {t["task_id"]: t for t in load_pack("ercot-dam-v1-eval") if t["task_id"] in want}


def print_tables(rows, reasoning, size, checks, base, verdicts):
    print("| row | tasks | mean R | 95% CI | valid | feasible | all idle | overfill | sell before charge | rate "
          "| cycle cap | end short | malformed | truncated (in thinking) | R ≥ 0.99 | tokens mean / p90 | hit cap "
          "| closed </think>, thinking tokens when closed | wall (s) |")
    print("|" + "---|" * 19)
    for r in rows.values():
        think = "–" if r["think_closed_rate"] is None else pct(r["think_closed_rate"])
        if r["think_len_mean"] is not None:
            think += f", {r['think_len_mean']:.0f}"
        print(f"| {r['name']} | {r['n']} | {r['reward_mean']:.3f} | [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] "
              f"| {pct(r['valid_rate'])} | {pct(r['feasible_rate'])} | {pct(r['rate_all_idle'])} "
              f"| {pct(r['rate_overfill'])} | {pct(r['rate_sell_before_charge'])} | {pct(r['rate_rate'])} "
              f"| {pct(r['rate_cycle_cap'])} | {pct(r['rate_end_short'])} | {pct(r['rate_malformed'])} "
              f"| {pct(r['rate_truncated'])} ({pct(r['rate_trunc_in_think'])}) | {r['exact_optima']} "
              f"| {r['completion_len_mean']:.0f} / {r['completion_len_p90']:.0f} | {pct(r['hit_cap_rate'])} "
              f"| {think} | {r['wall_s']:.0f} |")
    for name in ("greedy", "threshold"):
        print(f"| {name} rule | 200 | {base[name]['reward_mean']:.3f} | [{base[name]['ci95'][0]:.3f}, "
              f"{base[name]['ci95'][1]:.3f}] | 100% |" + " |" * 14)
    for title, ps in (("reasoning", reasoning), ("size", size)):
        print(f"\n| {title}: pair | tasks | paired gap | wins / ties | registered | CI > 0 | when on submits |\n"
              + "|---" * 7 + "|")
        for p in ps:
            w = p.get("when_on_submits")
            w = "–" if not w else "none" if not w["n"] else f"{w['n']} days: {w['on']:.3f} vs {w['off']:.3f}"
            print(f"| {p['a']} − {p['b']} | {p['n']} | {gap(p)} | {pct(p['win_rate'])} / {pct(p['tie_rate'])} "
                  f"| {'yes' if p['registered'] else 'no'} | {'**yes**' if p['met'] else 'no'} | {w} |")
    print("\npipeline vs registered:", [(c["a"], c["b"], gap(c)) for c in checks if "mean" in c])
    print("verdicts:", verdicts)


def chart(rows, base):
    blue, orange, ink, muted, surface = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#fcfcfb"
    groups = [("Qwen3-4B\nbase", "q4b"), ("Qwen3-8B\nbase", "q8b"), ("Qwen3-14B-AWQ\nbase (int4)", "q14awq"),
              ("Qwen3-4B SFT-10k\n(thinking on is OOD)", "sft")]
    variants = [("off512", "thinking off, 512", blue, "o", True), ("on2048", "thinking on, 2,048", orange, "s", False),
                ("on4096", "thinking on, 4,096", orange, "o", True),
                ("on16384-n50", "thinking on, 16,384 (first 50 tasks)", orange, "D", False)]
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    fig.patch.set_facecolor(surface)
    ax.set_facecolor(surface)
    for y, label, style in ((base["greedy"]["reward_mean"], "greedy rule", (0, (5, 3))),
                            (base["threshold"]["reward_mean"], "threshold rule", (0, (1, 3))),
                            (0.8405, "SFT-10k, registered\n(thinking off)", (0, (8, 2, 2, 2))),
                            (0.2, "idle", "solid")):
        ax.hlines(y, -0.5, 3.4, color=muted, lw=1, ls=style, zorder=1)
        ax.text(3.45, y, label, color=muted, fontsize=8, va="center", ha="left")
    seen = set()
    for gi, (_, key) in enumerate(groups):
        for vi, (suffix, vlabel, color, marker, filled) in enumerate(variants):
            k = f"{key}-{suffix}"
            if k not in rows:
                continue
            r = rows[k]
            x = gi + (vi - 1.5) * 0.17
            lo, hi = r["ci95"]
            ax.plot([x, x], [lo, hi], color=color, lw=2, solid_capstyle="round", zorder=2)
            ax.plot(x, r["reward_mean"], marker=marker, ms=8, color=color, mfc=color if filled else surface,
                    mew=2, ls="none", zorder=3, label=vlabel if vlabel not in seen else None)
            seen.add(vlabel)
            if r["reward_mean"] > 0:
                ax.text(x + 0.05, r["reward_mean"], f"{r['reward_mean']:.2f}", color=ink, fontsize=7.5, va="center")
    ax.set_xticks(range(len(groups)), [g[0] for g in groups], fontsize=9, color=ink)
    ax.set_xlim(-0.5, 4.4)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("mean R on 200 eval-2025 days (95% CI)", color=muted, fontsize=9)
    ax.tick_params(colors=muted, labelsize=8.5)
    ax.grid(axis="y", color="#e4e3df", lw=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color("#c9c8c2")
    ax.text(1.17, 0.045, "R 0 = every completion cut off inside <think>, no schedule submitted", color=muted,
            fontsize=7.5)
    fig.legend(frameon=False, fontsize=8.5, loc="lower center", ncol=4, labelcolor=ink)
    ax.set_title("GridSimEnv v1: reasoning budget vs model size (diagnostic; T 0.7 sampling, one sample per day)",
                 fontsize=10, color=ink, loc="left")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(D / "r_by_model.png", facecolor=surface)


if __name__ == "__main__":
    main()
