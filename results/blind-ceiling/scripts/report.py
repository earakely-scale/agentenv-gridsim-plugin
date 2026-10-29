"""summary.json, tables.md and ceiling.png for results/blind-ceiling from the work dir's tune/final/extend/informed.

python results/blind-ceiling/scripts/report.py --work DIR
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

OUT = Path(__file__).resolve().parents[1]
PACKS = {"eval2025": "blind eval-2025 (300 tasks, 191 days)", "fresh": "fresh 2026-10-18..27 (331 tasks, 10 days)"}
ROWS = [  # (label, source, key, group)
    ("Ensemble, point plan (registered pick)", "final", "ens_point", "reg"),
    ("LightGBM", "final", "lgb_point", "reg"),
    ("MLP", "final", "mlp_point", "reg"),
    ("Ridge-v1", "final", "ridge_point", "reg"),
    ("Persistence (D-1)", "final", "persist_point", "reg"),
    ("Ensemble, scenario plan", "final", "ens_scen", "scen"),
    ("LightGBM, scenario plan", "final", "lgb_scen", "scen"),
    ("MLP, scenario plan", "final", "mlp_scen", "scen"),
    ("Ridge-v1, scenario plan", "final", "ridge_scen", "scen"),
    ("Ensemble' (Amendment 1)", "extend", "ens", "ext"),
    ("LightGBM' (Amendment 1)", "extend", "lgb", "ext"),
    ("m7: 7-day hourly mean (Amendment 1)", "extend", "m7", "ext"),
    ("LightGBM + all 15 points' D-1 (more than the prompt)", "final", "lgb_ext_point", "more"),
    ("LightGBM + ERCOT's load/wind/solar forecasts (eval-2025 only)", "informed", "informed", "more"),
]
GROUPS = {"reg": ("#2a78d6", "registered, point plan"), "scen": ("#eb6834", "registered, scenario plan"),
          "ext": ("#1baf7a", "Amendment 1 (extended search)"), "more": ("#eda100", "exploratory: more than the prompt")}
INK, INK2, GRID, SURF = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


def f3(x: float) -> str:
    return f"{x:.3f}"


def ci(d: dict) -> str:
    return f"{f3(d['mean'])} [{f3(d['ci'][0])}, {f3(d['ci'][1])}]"


def gap(d: dict) -> str:
    return f"{d['mean']:+.3f} [{d['ci'][0]:+.3f}, {d['ci'][1]:+.3f}]"


def holdout_c(src: dict, source: str, key: str) -> str:
    v = src["extend" if source == "extend" else "tune"]["holdout"].get(key)
    return f3(v["c"]) if v else "–"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    w = Path(ap.parse_args().work)
    src = {k: json.loads((w / f"{k}.json").read_text()) for k in ("tune", "final", "extend", "informed")
           if (w / f"{k}.json").exists()}
    lines = ["# Blind ceiling: generated tables", "",
             "C = clip(0.2 + 0.8 x, 0, 1), x = (P − P_idle) / (P_opt − P_idle). CIs: day-block bootstrap, 10,000 "
             "resamples, seed 0. Δ is paired on the same tasks. \"Beats Sol\": share of tasks where the method's "
             "profit is higher (ties are common when both find the same schedule).", ""]
    for pk, title in PACKS.items():
        lines += [f"## {title}", "",
                  "| method | holdout C (2024) | C | Δ C vs Sol | Δ C vs anchor | x | beats Sol | ties |",
                  "|---|---|---|---|---|---|---|---|"]
        m = src["final"]["packs"][pk]["methods"]
        lines.append(f"| **GPT-6.1 Sol** | – | **{ci(m['sol']['c'])}** | – | {gap(m['sol']['gap_anchor_c'])} | "
                     f"{f3(m['sol']['x']['mean'])} | – | – |")
        lines.append(f"| blind anchor (oracle max, hindsight) | {holdout_c(src, 'final', 'anchor_v1_insample')}* | "
                     f"{ci(m['anchor']['c'])} | {gap(m['anchor']['gap_sol_c'])} | – | {f3(m['anchor']['x']['mean'])} | "
                     f"{m['anchor']['beats_sol']:.1%} | {m['anchor']['ties_sol']:.1%} |")
        for label, source, key, _ in ROWS:
            if source not in ("final", "extend") or source not in src:
                continue
            r = src[source]["packs"][pk]["methods"][key]
            lines.append(f"| {label} | {holdout_c(src, source, key)} | {ci(r['c'])} | {gap(r['gap_sol_c'])} | "
                         f"{gap(r['gap_anchor_c'])} | {f3(r['x']['mean'])} | {r['beats_sol']:.1%} | "
                         f"{r['ties_sol']:.1%} |")
        lines += ["", "\\* in-sample: ridge-v1 was fitted on 2014–2024. The ridge rows' holdout C is a pre-2024 refit; "
                  "eval-2025 and fresh use ridge-v1 as stored.", ""]
        lines += [f"### Forecast error, {pk} (unique point-days, $/MWh)", "",
                  "| forecaster | MAE all | RMSE all | MAE 4 dearest h | RMSE 4 dearest h | MAE 4 cheapest h | "
                  "RMSE 4 cheapest h |", "|---|---|---|---|---|---|---|"]
        fe = dict(src["final"]["packs"][pk]["forecast_err"])
        if "extend" in src:
            fe |= {f"{k}' (A1)": v for k, v in src["extend"]["packs"][pk]["forecast_err"].items()
                   if k in ("m7", "lgb", "ens")}
        for k, e in fe.items():
            lines.append(f"| {k} | {e['all']['mae']:.1f} | {e['all']['rmse']:.1f} | {e['dear4']['mae']:.1f} | "
                         f"{e['dear4']['rmse']:.1f} | {e['cheap4']['mae']:.1f} | {e['cheap4']['rmse']:.1f} |")
        lines.append("")
    if "informed" in src:
        lines += ["## Exploratory: informed blind (v4 store forecasts)", ""]
        for s, o in src["informed"]["sources"].items():
            lines += [f"### {s} forecasts, fit window {o['window'][0]}..{o['window'][1]} "
                      f"({o['n_window_point_days']} point-days)", ""]
            for pk, p in o["packs"].items():
                lines += [f"{pk}: {p['n_tasks']} tasks, {p['n_days']} days ({p['days'][0]}..{p['days'][1]})", "",
                          "| row | C or Δ C |", "|---|---|"]
                lines += [f"| C {k} | {ci(v)} |" for k, v in p["c"].items()]
                lines += [f"| Δ {k} | {gap(v)} (wins {v['wins']:.1%}) |" for k, v in p["gaps"].items()]
                lines.append("")
    (OUT / "tables.md").write_text("\n".join(lines) + "\n")
    summary = {"prereg": "docs/prereg/v1-blind-ceiling.md", "metric": "C = clip(0.2 + 0.8 x, 0, 1); x raw capture",
               "bootstrap": {"resamples": 10000, "seed": 0, "unit": "day (block), task-weighted"},
               "tune": {k: src["tune"][k] for k in ("n_fit", "n_val", "n_holdout_tasks", "n_holdout_days", "lgb_best",
                                                      "mlp_best", "ens_weights", "best_method", "holdout")},
               "registered": {"packs": src["final"]["packs"], "verdict": src["final"]["verdict"]}}
    if "extend" in src:
        e = src["extend"]
        summary["amendment_1"] = {k: e[k] for k in ("lgb_best", "ens_weights", "holdout", "best_method", "packs",
                                                    "verdict")}
    if "informed" in src:
        summary["informed_exploratory"] = src["informed"]
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    chart(src)


def c_of(src: dict, source: str, key: str, pk: str) -> dict | None:
    if source == "informed":
        return src["informed"]["sources"]["ercot"]["packs"][pk]["c"][key] if pk == "eval2025" else None
    return src[source]["packs"][pk]["methods"][key]["c"]


def chart(src: dict):
    rows = [r for r in ROWS if r[1] in src]
    fig, axes = plt.subplots(1, 2, figsize=(11, 0.42 * len(rows) + 1.9), sharey=True, facecolor=SURF)
    for ax, (pk, title) in zip(axes, PACKS.items(), strict=True):
        m = src["final"]["packs"][pk]["methods"]
        ax.set_facecolor(SURF)
        sol, anc = m["sol"]["c"], m["anchor"]["c"]
        ax.axvspan(sol["ci"][0], sol["ci"][1], color=INK, alpha=0.06, lw=0)
        ax.axvline(sol["mean"], color=INK, lw=2)
        ax.axvline(anc["mean"], color=INK2, lw=1.2)
        right = sol["mean"] >= anc["mean"]
        ax.text(sol["mean"], -0.9, f" Sol {sol['mean']:.3f} " if right else f"Sol {sol['mean']:.3f} ", color=INK,
                fontsize=8, va="bottom", ha="left" if right else "right")
        ax.text(anc["mean"], -0.9, f"anchor {anc['mean']:.3f} " if right else f" anchor {anc['mean']:.3f}",
                color=INK2, fontsize=8, va="bottom", ha="right" if right else "left")
        for i, (_, source, key, g) in enumerate(rows):
            r = c_of(src, source, key, pk)
            if r is None:
                continue
            ax.plot(r["ci"], [i, i], color=GROUPS[g][0], lw=2, solid_capstyle="round")
            ax.plot(r["mean"], i, "o", ms=8, color=GROUPS[g][0], mec=SURF, mew=2)
        ax.set_title(title, fontsize=10, color=INK, loc="left")
        ax.set_xlabel("hindsight capture C (day-block 95% CI)", fontsize=9, color=INK2)
        ax.grid(axis="x", color=GRID, lw=1)
        ax.set_axisbelow(True)
        ax.tick_params(colors=INK2, labelsize=8, length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_xlim(0.72, 0.97)
    axes[0].set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=8, color=INK)
    axes[0].set_ylim(len(rows) - 0.4, -1.2)
    handles = [plt.Line2D([], [], marker="o", ls="", ms=8, color=c, mec=SURF, mew=2, label=lab)
               for c, lab in GROUPS.values()]
    handles += [plt.Line2D([], [], color=INK, lw=2, label="GPT-6.1 Sol (band: its CI)"),
                plt.Line2D([], [], color=INK2, lw=1.2, label="blind anchor (oracle max in hindsight)")]
    fig.legend(handles=handles, loc="lower center", ncol=3, fontsize=8, frameon=False, labelcolor=INK)
    fig.suptitle("Blind tier: information-matched forecaster + exact DP vs GPT-6.1 Sol", fontsize=11, color=INK,
                 x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.08, 1, 0.97))
    fig.savefig(OUT / "ceiling.png", dpi=150, facecolor=SURF)


if __name__ == "__main__":
    main()
