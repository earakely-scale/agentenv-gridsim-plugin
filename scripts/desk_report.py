"""Results report for a desk version: summary.json, README.md, gzipped raw runs and two figures (light and dark).

PYTHONPATH=src python scripts/desk_report.py --layer v2 --pack desk-v2-eval --run sol=DIR --run luna=DIR \
    --run qwen=DIR [--pilot DIR] [--regrade] --out results/desk-v2

CIs: a day-block bootstrap (10,000 resamples of operating days, seed 0, task-weighted), as results/train/4b-blind."""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import itertools
import json
import re
import shutil
from collections import Counter
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from gridsim_core.desk import fixtures  # noqa: E402
from gridsim_core.desk.data import load_series, load_tasks  # noqa: E402
from gridsim_core.desk.refs import denominator  # noqa: E402
from gridsim_core.grade import reward_value, stretch_value  # noqa: E402

B, SEED = 10_000, 0
CALLS_MAX_MB = 50
NAMES = {"sol": "GPT-6.1 Sol", "luna": "GPT-6 Luna", "qwen": "Qwen3-4B (base)", "anchor": "anchor policy",
         "idle": "idle policy", "scripted": "scripted policy"}
REFS = [("idle", "idle", "p_idle"), ("anchor", "anchor (information-matched)", "p_anchor"),
        ("hind", "hindsight optimum", "p_hind"), ("hind_phys", "hindsight, DAM = physical", "p_hind_phys"),
        ("operator_replay", "operator replay", "p_operator_replay"),
        ("operator_actual", "operator actual", "p_operator_actual")]
TOOL_SHORT = {"optimize": "optimize", "check_submission": "check", "update_cop": "COP", "get_prices": "prices",
              "get_forecasts": "forecasts", "get_grid_conditions": "grid", "get_asset_status": "asset",
              "get_position": "position"}
THEMES = {
    "light": {"bg": "#ffffff", "ink": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "faint": "#f3f2ef",
              "ref": ["#a9a7a1", "#52514e", "#7b7973", "#c9c7c1", "#8c8a84"],
              "model": {"sol": "#2a78d6", "luna": "#eb6834", "qwen": "#1baf7a"}, "extra": ["#6250d6", "#b0457c"],
              "dam": "#0b0b0b", "rt": "#9a978f", "op": "#7b7973", "charge": "#2a78d6", "discharge": "#eb6834"},
    "dark": {"bg": "#0b0f19", "ink": "#ecebe8", "muted": "#a3a19b", "grid": "#262b36", "faint": "#151a26",
             "ref": ["#77756f", "#c9c7c1", "#9c9a94", "#5d5b56", "#b3b1ab"],
             "model": {"sol": "#4a90e8", "luna": "#f07a4a", "qwen": "#2cc28a"}, "extra": ["#8f80f0", "#d0679f"],
             "dam": "#ecebe8", "rt": "#6f6d68", "op": "#a3a19b", "charge": "#4a90e8", "discharge": "#f07a4a"},
}
GRADE_KEYS = ("valid", "reward", "capture", "capture_phys", "stretch", "beats_anchor", "floored", "p", "p_idle",
              "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual")
FONTS = ["Inter", "Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"]


def boot(x, days) -> dict:
    x, days = np.asarray(x, float), np.asarray(days)
    if not len(x):
        return {"mean": None, "ci": [None, None], "n": 0, "days": 0}
    u, inv = np.unique(days, return_inverse=True)
    idx = np.random.default_rng(SEED).integers(0, len(u), (B, len(u)))
    s, c = np.bincount(inv, x), np.bincount(inv)
    m = s[idx].sum(1) / c[idx].sum(1)
    return {"mean": round(float(x.mean()), 4), "ci": [round(float(v), 4) for v in np.percentile(m, [2.5, 97.5])],
            "n": int(len(x)), "days": int(len(u))}


def paired(a, b, days) -> dict:
    d = np.asarray(a, float) - np.asarray(b, float)
    days = np.asarray(days)
    out = boot(d, days)
    if len(d):
        out |= {"ahead": round(float((d > 1e-9).mean()), 4), "level": round(float((abs(d) <= 1e-9).mean()), 4),
                "days_ahead": int(sum(d[days == x].mean() > 0 for x in np.unique(days)))}
    return out


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    opener = gzip.open if p.suffix == ".gz" else open
    with opener(p, "rt") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_run(d: Path) -> dict:
    rows = read_jsonl(d / "results.jsonl")
    last = {}
    for r in rows:
        last[r["task_id"]] = r
    eps = {}
    for tid, r in last.items():
        p = d / "episodes" / f"{tid}.{r['tag']}.json"
        if p.exists():
            eps[tid] = json.loads(p.read_text())
    return {"dir": d, "attempts": rows, "rows": last, "episodes": eps}


def regrade(g: dict, ep: dict, refs: dict) -> dict:
    p, pi, pa, ph, pp = (ep["statement"]["total"], refs["p_idle"], refs["p_anchor"], refs["p_hind"],
                         refs.get("p_hind_phys"))

    def cap(q):
        return round((p - pi) / (q - pi), 6) if q is not None and q - pi > 1e-9 else None

    eff, floored = denominator(pi, pa, pp)
    out = dict(g, p=p, p_idle=pi, p_anchor=pa, p_hind=ph, p_hind_phys=pp, capture=cap(ph), capture_phys=cap(pp),
               reward=reward_value(p, pi, eff) if g["valid"] else 0.0, beats_anchor=p > pa + 1e-9,
               floored=floored, p_reward_scale=round(eff, 2),
               stretch=stretch_value(p, pi, eff, ph) if g["valid"] else 0.0,
               p_operator_replay=refs.get("p_operator_replay"), p_operator_actual=refs.get("p_operator_actual"))
    if out["p_operator_replay"] is not None:
        out["vs_operator_replay"] = round(p - out["p_operator_replay"], 2)
    return out


def grade_rows(runs: dict, grades: dict, days: dict) -> list[dict]:
    out = []
    for name, run in runs.items():
        for tid in sorted(grades[name]):
            g, r, ep = grades[name][tid], run["rows"][tid], run["episodes"].get(tid)
            subs = (ep or {}).get("submissions", [])
            out.append({"model": name, "task_id": tid, "tag": r["tag"], "date": days[tid], "site": site_key(tid),
                        "status": r.get("status", "ok"), **{k: g.get(k) for k in GRADE_KEYS},
                        "lines": statement_lines(ep) if ep else None, "usage": r.get("usage"),
                        "submissions": len(subs), "rejected": sum(not x["accepted"] for x in subs),
                        "episode": f"episodes/{name}/{tid}.{r['tag']}.json.gz" if ep else None})
    return out


def days_of(tid: str, ep: dict | None) -> str:
    if ep and ep.get("dates"):
        return ep["dates"][0]
    m = re.search(r"\d{4}-\d{2}-\d{2}", tid)
    return m.group(0) if m else tid


def site_key(tid: str) -> str:
    m = re.search(r"-(S\d+)(?:-|$)", tid)
    return m.group(1) if m else tid


def statement_lines(ep: dict) -> dict:
    out = Counter()
    for day in ep["statement"]["days"].values():
        for k, v in day["lines"].items():
            out[k] += v or 0.0
    return dict(out)


def behaviour(ep: dict) -> dict:
    tools = Counter(c["tool"] for t in ep["turns"] for c in t["calls"])
    subs = ep.get("submissions", [])
    rej = Counter(c for s in subs if not s["accepted"] for c in s["codes"] or ["?"])
    warn = Counter(c for s in subs if s["accepted"] for c in s["codes"])
    by_tool = Counter((s["tool"], s["accepted"]) for s in subs)
    reminders = sum(1 for t in ep["turns"] for c in t["calls"] if c["tool"] == "set_reminder" and c.get("ok"))
    days = ep["statement"]["days"].values()
    return {"turns": len(ep["turns"]), "calls": sum(tools.values()), "tools": dict(tools),
            "accepted": sum(s["accepted"] for s in subs), "rejected": sum(not s["accepted"] for s in subs),
            "rejected_codes": dict(rej), "accepted_codes": dict(warn),
            "submissions_by_tool": {f"{k}:{'accepted' if a else 'rejected'}": v for (k, a), v in by_tool.items()},
            "reminders": reminders, "cycles": sum(d.get("cycles", 0.0) for d in days),
            "discharged_mwh": sum(d.get("discharged_mwh", 0.0) for d in days),
            "cop_late": (ep.get("compliance") or {}).get("cop_late", 0), "wakes": len(ep.get("wakes", [])),
            "ancillary": ancillary(ep)}


AS_NAMES = {"RegUp": "regup", "RegDn": "regdn", "RRS-FFR": "rrsffr", "RRS-PFR": "rrspfr", "ECRS": "ecrs",
            "Non-Spin": "nspin"}
AS_LABEL = {v: k for k, v in AS_NAMES.items()}


def ancillary(ep: dict) -> dict | None:
    """AS offers accepted per product and market, AS rejection codes, and awarded MWh per product (v3+)."""
    d0 = ep["dates"][0]
    if "as_award_mw" not in ep["dam"].get(d0, {}) and "as_award_mw" not in ep["rt"].get(d0, {}):
        return None
    acc, rej = Counter(), Counter()
    for t in ep["turns"]:
        for c in t["calls"]:
            if c["tool"] not in ("submit_dam_offers", "submit_rt_offers") or not isinstance(c.get("result"), dict):
                continue
            mkt = "dam" if c["tool"] == "submit_dam_offers" else "rt"
            for k in c["result"].get("as_accepted") or {}:
                acc[f"{mkt}:{AS_NAMES.get(k, k)}"] += 1
            for x in c["result"].get("as_rejected") or []:
                rej[x.get("code", "?") if isinstance(x, dict) else "?"] += 1
    dam, rt = Counter(), Counter()
    for d in ep["dates"]:
        for h in ep["dam"].get(d, {}).get("as_award_mw") or []:
            dam.update({k: v for k, v in (h or {}).items() if v})
        for i in ep["rt"].get(d, {}).get("as_award_mw") or []:
            rt.update({k: v / 12 for k, v in (i or {}).items() if v})
    return {"accepted": dict(acc), "rejected_codes": dict(rej), "dam_mwh": dict(dam), "rt_mwh": dict(rt)}


def mean_counter(cs: list[dict]) -> dict:
    tot = Counter()
    for c in cs:
        tot.update(c)
    return {k: round(v / max(1, len(cs)), 3) for k, v in sorted(tot.items(), key=lambda kv: -kv[1])}


def sum_counter(cs: list[dict]) -> dict:
    tot = Counter()
    for c in cs:
        tot.update(c)
    return dict(tot.most_common())


def model_block(run: dict, grades: dict, days: dict) -> dict:
    tids = sorted(grades)
    d = np.array([days[t] for t in tids])
    g = [grades[t] for t in tids]
    eps = [run["episodes"].get(t) for t in tids]
    beh = [behaviour(e) for e in eps if e]
    lines = [statement_lines(e) for e in eps if e]
    usage = [run["rows"][t].get("usage", {}) for t in tids]

    def num(k):
        return [x.get(k) or 0 for x in usage]

    def sub(key):
        pairs = [(x[key], days[t]) for t, x in zip(tids, g, strict=True) if x.get(key) is not None]
        return [p for p, _ in pairs], [q for _, q in pairs]

    def gap(key):
        pairs = [(x["p"] - x[key], days[t]) for t, x in zip(tids, g, strict=True) if x.get(key) is not None]
        return boot([p for p, _ in pairs], [q for _, q in pairs])

    c, cd = sub("capture")
    cp, cpd = sub("capture_phys")
    status = Counter(run["rows"][t].get("status", "ok").split(":")[0] for t in tids)
    pol = run["rows"][tids[0]].get("policy", {}) if tids else {}
    return {
        "policy": pol, "n": len(tids), "days": len(set(d)), "status": dict(status),
        "valid_share": round(float(np.mean([x["valid"] for x in g])), 4) if g else None,
        "R": boot([x["reward"] for x in g], d), "C": boot(c, cd), "C_phys": boot(cp, cpd),
        "P": boot([x["p"] for x in g], d),
        "lines": {k: round(float(np.mean([ln.get(k, 0.0) for ln in lines])), 2) for k in
                  dict.fromkeys(k for ln in lines for k in ln)},
        "P_minus_anchor": gap("p_anchor"),
        "floored": sum(bool(x.get("floored")) for x in g),
        "beats_anchor_share": round(float(np.mean([x["p"] > x["p_anchor"] + 1e-9 for x in g])), 4) if g else None,
        "P_minus_operator_replay": gap("p_operator_replay"), "P_minus_operator_actual": gap("p_operator_actual"),
        "turns": round(float(np.mean([b["turns"] for b in beh])), 2) if beh else None,
        "wakes": round(float(np.mean([b["wakes"] for b in beh])), 2) if beh else None,
        "calls": round(float(np.mean([b["calls"] for b in beh])), 2) if beh else None,
        "calls_by_tool": mean_counter([b["tools"] for b in beh]),
        "submissions": {"accepted": round(float(np.mean([b["accepted"] for b in beh])), 2) if beh else None,
                        "rejected": round(float(np.mean([b["rejected"] for b in beh])), 2) if beh else None,
                        "by_tool_total": sum_counter([b["submissions_by_tool"] for b in beh]),
                        "rejected_codes_total": sum_counter([b["rejected_codes"] for b in beh]),
                        "accepted_with_codes_total": sum_counter([b["accepted_codes"] for b in beh])},
        "reminders": round(float(np.mean([b["reminders"] for b in beh])), 2) if beh else None,
        "cycles": round(float(np.mean([b["cycles"] for b in beh])), 3) if beh else None,
        "discharged_mwh": round(float(np.mean([b["discharged_mwh"] for b in beh])), 1) if beh else None,
        "cop_late": round(float(np.mean([b["cop_late"] for b in beh])), 2) if beh else None,
        "ancillary": {"offers_accepted": mean_counter([x["accepted"] for x in anc]),
                      "rejected_codes_total": sum_counter([x["rejected_codes"] for x in anc]),
                      "dam_award_mwh": mean_counter([x["dam_mwh"] for x in anc]),
                      "rt_award_mwh": mean_counter([x["rt_mwh"] for x in anc]),
                      "episodes_with_awards": sum(1 for x in anc if x["dam_mwh"] or x["rt_mwh"])}
        if (anc := [b["ancillary"] for b in beh if b["ancillary"]]) else None,
        "cost_usd": {"per_episode": round(float(np.mean(num("cost_usd"))), 4) if tids else None,
                     "total_scored": round(float(np.sum(num("cost_usd"))), 4),
                     "total_all_attempts": round(sum((r.get("usage") or {}).get("cost_usd", 0.0)
                                                     for r in run["attempts"]), 4),
                     "attempts": len(run["attempts"])},
        "tokens": {k: round(float(np.mean(num(k))), 1) if tids else None
                   for k in ("api_calls", "input_tokens", "output_tokens", "cached_tokens")},
        "wall_s": round(float(np.mean(num("wall_s"))), 1) if tids else None,
    }


def ref_block(grades_any: dict, days: dict) -> dict:
    out = {}
    tids = sorted(grades_any)
    for key, label, field in REFS:
        rows = [(grades_any[t], days[t]) for t in tids if grades_any[t].get(field) is not None]
        p = [g[field] for g, _ in rows]
        d = [x for _, x in rows]
        c = [((g[field] - g["p_idle"]) / (g["p_hind"] - g["p_idle"]), x) for g, x in rows
             if g["p_hind"] - g["p_idle"] > 1e-9]
        cp = [((g[field] - g["p_idle"]) / (g["p_hind_phys"] - g["p_idle"]), x) for g, x in rows
              if g.get("p_hind_phys") is not None and g["p_hind_phys"] - g["p_idle"] > 1e-9]
        out[key] = {"label": label, "P": boot(p, d), "C": boot([a for a, _ in c], [b for _, b in c]),
                    "C_phys": boot([a for a, _ in cp], [b for _, b in cp])}
    return out


def series_for(pack: str, tid: str, layer: str, ep: dict) -> dict | None:
    try:
        task = next(t for t in load_tasks(pack) if t["task_id"] == tid)
        return load_series(pack, task)
    except (FileNotFoundError, StopIteration, OSError, KeyError):
        pass
    m = re.match(r"desk-\w+-(\d{4}-\d{2}-\d{2})-S\d+-f(\d+)$", tid)
    if not m:
        return None
    task, series = fixtures.make(m.group(1), seed=int(m.group(2)), outage=True, layer=layer,
                                 days=len(ep.get("dates", [1])))
    return series if task["task_id"] == tid else None


def date_span(dates: list[str]) -> str:
    a, b = dt.date.fromisoformat(dates[0]), dt.date.fromisoformat(dates[-1])
    return a.strftime("%a %d %b %Y") if a == b else f"{a.strftime('%a %d')} – {b.strftime('%a %d %b %Y')}"


def gz_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with open(src, "rb") as f, gzip.open(dst, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)


def copy_raw(name: str, run: dict, out: Path) -> dict:
    d = run["dir"]
    rd, ed = out / "runs" / name, out / "episodes" / name
    for p in (rd, ed):
        if p.exists():
            shutil.rmtree(p)
    if (d / "results.jsonl").exists():
        gz_copy(d / "results.jsonl", rd / "results.jsonl.gz")
    for p in sorted((d / "episodes").glob("*.json")):
        gz_copy(p, ed / (p.name + ".gz"))
    calls = sorted((d / "calls").glob("*.jsonl")) if (d / "calls").exists() else []
    size = sum(p.stat().st_size for p in calls)
    kept = size <= CALLS_MAX_MB * 2 ** 20
    if kept:
        for p in calls:
            gz_copy(p, rd / "calls" / (p.name + ".gz"))
    return {"episodes": len(list((d / "episodes").glob("*.json"))), "calls_mb": round(size / 2 ** 20, 2),
            "calls_copied": kept and bool(calls)}


def fmt_ci(b: dict, money: bool = False, signed: bool = False, digits: int = 3) -> str:
    if b.get("mean") is None:
        return "—"
    f = (lambda v: money_s(v, signed)) if money else \
        (lambda v: (f"{v:+.{digits}f}" if signed else f"{v:.{digits}f}").replace("-", "−"))
    return f"{f(b['mean'])} [{f(b['ci'][0])}, {f(b['ci'][1])}]"


def money_s(v: float, signed: bool = False) -> str:
    s = f"{abs(v):,.0f}"
    sign = "−" if v < 0 else ("+" if signed else "")
    return f"{sign}${s}"


def pct(v) -> str:
    return "—" if v is None else f"{100 * v:.0f}%"


def theme_rc(th: dict) -> dict:
    return {"font.family": "sans-serif", "font.sans-serif": FONTS, "axes.edgecolor": th["grid"],
            "axes.labelcolor": th["muted"], "xtick.color": th["muted"], "ytick.color": th["muted"],
            "text.color": th["ink"], "figure.facecolor": th["bg"], "axes.facecolor": th["bg"],
            "savefig.facecolor": th["bg"], "text.parse_math": False}


def model_color(th: dict, name: str, i: int) -> str:
    return th["model"].get(name) or th["extra"][i % len(th["extra"])]


def fig_bars(summary: dict, path: Path, mode: str) -> None:
    th = THEMES[mode]
    rows = []
    for i, (k, m) in enumerate(summary["models"].items()):
        if m["P"]["mean"] is not None:
            rows.append((NAMES.get(k, k), m["P"], model_color(th, k, i), True))
    refs = summary["references"]
    for j, key in enumerate(["anchor", "operator_replay", "operator_actual", "hind_phys", "idle"]):
        r = refs.get(key)
        if r and r["P"]["mean"] is not None:
            rows.append((r["label"], r["P"], th["ref"][j % len(th["ref"])], False))
    rows.sort(key=lambda r: -r[1]["mean"])
    hind = refs.get("hind", {}).get("P", {}).get("mean")
    with plt.rc_context(theme_rc(th)):
        fig, ax = plt.subplots(figsize=(10, 0.46 * len(rows) + 1.7))
        lo = min([0.0] + [r[1]["ci"][0] for r in rows])
        hi = max([r[1]["ci"][1] for r in rows] + [hind or 0.0])
        span = hi - lo or 1.0
        for i, (_, b, col, is_model) in enumerate(rows):
            ax.barh(i, b["mean"], height=0.62, color=col, lw=0, zorder=2)
            ax.plot(b["ci"], [i, i], color=th["ink"], lw=1.0, zorder=3, solid_capstyle="butt")
            x = max(b["ci"][1], b["mean"], 0.0) + 0.012 * span
            ax.text(x, i, money_s(b["mean"]), va="center", ha="left", fontsize=9, color=th["ink"],
                    fontweight="bold" if is_model else "normal")
        if hind is not None:
            ax.axvline(hind, color=th["ink"], lw=1.0, ls=(0, (4, 3)), zorder=1)
            ax.text(hind - 0.008 * span, -0.75, f"hindsight optimum {money_s(hind)}", ha="right", va="bottom",
                    fontsize=8.5, color=th["muted"])
        ax.axvline(0, color=th["muted"], lw=0.8, zorder=1)
        ax.set_yticks(range(len(rows)), [r[0] for r in rows], fontsize=9.5, color=th["ink"])
        for t, r in zip(ax.get_yticklabels(), rows, strict=True):
            t.set_fontweight("bold" if r[3] else "normal")
        ax.invert_yaxis()
        ax.set_xlim(lo - 0.04 * span, hi + 0.16 * span)
        ax.set_ylim(len(rows) - 0.4, -1.1)
        ax.grid(axis="x", color=th["grid"], lw=0.8, zorder=0)
        ax.tick_params(axis="x", labelsize=8.5, length=0)
        ax.tick_params(axis="y", length=0)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: money_s(v)))
        for s in ax.spines.values():
            s.set_visible(False)
        ax.set_xlabel(f"mean P per battery-day ($, settled statement), 95% day-block CI, n = {summary['n_tasks']}",
                      fontsize=9)
        ax.set_title(f"Mean P per battery-day on {summary['pack']}: models (bold) against the references",
                     loc="left", fontsize=11, color=th["ink"], pad=14)
        fig.tight_layout()
        fig.savefig(path, dpi=200)
        plt.close(fig)


def pick_hero(summary: dict, runs: dict, grades: dict, want: str | None) -> tuple[str, str] | None:
    name = want.split(":")[0] if want else ("sol" if "sol" in runs else next(iter(runs), None))
    if name is None or name not in runs:
        return None
    if want and ":" in want:
        return name, want.split(":", 1)[1]
    cands = [(g.get("capture") if g.get("capture") is not None else -1e9, g["p"], t)
             for t, g in grades[name].items() if t in runs[name]["episodes"] and g["valid"]]
    if not cands:
        return None
    return name, max(cands)[2]


def clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n - 1] + "…"


def turn_label(ep: dict, turn: dict) -> str:
    acts, seen = [], Counter()
    subs = [s for s in ep.get("submissions", []) if s["t"] == turn["t"]]
    for c in turn["calls"]:
        seen[c["tool"]] += 1
    groups = {}
    for s in subs:
        if s.get("as"):
            continue
        g = groups.setdefault((s["tool"], s.get("day") if len(ep.get("dates", [])) > 1 else None, s["accepted"]),
                              {"hours": set(), "codes": []})
        g["hours"].update(s.get("hours") or [])
        g["codes"] += [c for c in s["codes"] if c not in g["codes"]]
    for (tool, day, ok), g in groups.items():
        what = {"submit_dam_offers": "DAM offers", "submit_rt_offers": "RT curves", "update_cop": "COP"}.get(tool, tool)
        hrs = g["hours"]
        span = "" if not hrs or tool == "update_cop" else \
            f" HE{min(hrs)}" if min(hrs) == max(hrs) else f" HE{min(hrs)}–{max(hrs)}"
        acts.append(f"{what}{f' {day}' if day else ''}{span}"
                    + ("" if ok else f" (rejected {','.join(g['codes'][:2])})"))
    for c in turn["calls"]:
        res = c.get("result") if isinstance(c.get("result"), dict) else {}
        if c["tool"] in ("submit_dam_offers", "submit_rt_offers") and res.get("as_accepted"):
            acts.append(f"AS {'DAM' if c['tool'] == 'submit_dam_offers' else 'RT'} " + ", ".join(res["as_accepted"]))
    for c in turn["calls"]:
        if c["tool"] == "set_reminder" and c.get("ok"):
            at = (c.get("args") or {}).get("at")
            acts.append(f"reminder {str(at)[-5:]}" if at else "reminder")
    if seen.get("optimize"):
        acts.insert(0, "optimize" + (f" ×{seen['optimize']}" if seen["optimize"] > 1 else ""))
    reads = [TOOL_SHORT[k] for k in TOOL_SHORT if k.startswith("get_") and seen.get(k)]
    if reads and not acts:
        acts.append("read " + ", ".join(reads))
    return "; ".join(acts) if acts else "no calls"


def fig_hero(ep: dict, series: dict | None, name: str, label: str, path: Path, mode: str) -> None:
    th = THEMES[mode]
    accent = th["model"].get(name, th["extra"][0])
    dates = ep["dates"]
    nd = len(dates)
    dam = np.concatenate([ep["dam"][d]["spp"] for d in dates])
    award = np.concatenate([ep["dam"][d]["award_mw"] for d in dates])
    lmp = np.concatenate([ep["rt"][d]["lmp"] for d in dates])
    metered = np.concatenate([ep["rt"][d]["metered_mw"] for d in dates])
    soc = np.concatenate([ep["rt"][d]["soc_mwh"][:-1] for d in dates] + [[ep["rt"][dates[-1]]["soc_mwh"][-1]]])
    op_soc = None
    if series and series.get("operator"):
        try:
            op_soc = np.concatenate([[np.nan if x is None else x for x in series["operator"]["sced"][d]["soc_mwh"]]
                                     for d in dates]).astype(float)
        except (KeyError, TypeError):
            op_soc = None
    t5 = np.arange(len(lmp)) * 5
    th_ = np.arange(len(dam) + 1) * 60
    t0 = min([w["t"] for w in ep["wakes"]] + [0])
    k = min(0.6, 0.25 * nd)
    fns = (lambda x: np.where(np.asarray(x) < 0, np.asarray(x) * k, x),
           lambda x: np.where(np.asarray(x) < 0, np.asarray(x) / k, x))
    turns = {t["turn"]: t for t in ep["turns"]}
    wakes = [w for w in ep["wakes"] if w.get("turn") in turns]
    items = []
    for i, w in enumerate(wakes, 1):
        tr = turns[w["turn"]]
        acted = any(s["t"] == tr["t"] for s in ep.get("submissions", []))
        items.append((i, w, tr, acted))
    shown = items if len(items) <= 24 else [x for x in items if x[3] or x[0] == 1][:24]
    with plt.rc_context(theme_rc(th)):
        fig = plt.figure(figsize=(14, 7.6))
        gs = fig.add_gridspec(3, 2, width_ratios=[3.1, 1.25], height_ratios=[1.25, 1.0, 0.8], hspace=0.12,
                              wspace=0.04, left=0.06, right=0.99, top=0.80, bottom=0.08)
        ax_p, ax_s, ax_d = (fig.add_subplot(gs[i, 0]) for i in range(3))
        ax_t = fig.add_subplot(gs[:, 1])
        ax_t.axis("off")
        for ax in (ax_p, ax_s, ax_d):
            ax.set_xscale("function", functions=fns)
            ax.set_xlim(t0, 1440 * nd)
            if t0 < 0:
                ax.axvspan(t0, 0, color=th["faint"], lw=0, zorder=0)
            ax.grid(axis="y", color=th["grid"], lw=0.7, zorder=0)
            ax.tick_params(length=0, labelsize=8.5)
            for s in ax.spines.values():
                s.set_visible(False)
            for _, w, _, acted in items:
                ax.axvline(w["t"], color=accent if acted else th["muted"], lw=0.7 if acted else 0.5,
                           alpha=0.55 if acted else 0.3, zorder=1)
        top = max(float(np.nanmax(dam)), float(np.nanpercentile(lmp, 99.5))) * 1.25
        bot = min(0.0, float(np.nanmin(dam)), float(np.nanpercentile(lmp, 0.5))) * 1.1
        ax_p.plot(t5, np.clip(lmp, bot, top), color=th["rt"], lw=0.8, zorder=2, label="RT LMP (5-min, node)")
        ax_p.step(th_, np.append(dam, dam[-1]), where="post", color=th["dam"], lw=1.6, zorder=3,
                  label="DAM SPP (hourly, node)")
        if np.nanmax(lmp) > top:
            j = int(np.nanargmax(lmp))
            ax_p.annotate(f"RT peak {money_s(float(lmp[j]))}", (t5[j], top), xytext=(4, -2),
                          textcoords="offset points", fontsize=8, color=th["muted"], va="top")
        ax_p.set_ylim(bot, top)
        ax_p.set_ylabel("$/MWh", fontsize=9)
        span_x = 1440 * nd - t0 * k
        lanes: list[float] = []
        for i, w, _, acted in items:
            x = w["t"] * k if w["t"] < 0 else w["t"]
            level = next((j for j, v in enumerate(lanes) if x - v >= 0.017 * span_x), len(lanes))
            if level >= 4:
                level = int(np.argmin(lanes))
            if level < len(lanes):
                lanes[level] = x
            else:
                lanes.append(x)
            ax_p.annotate(str(i), (w["t"], top), xytext=(0, 9 + 14 * level), textcoords="offset points", ha="center",
                          va="center", fontsize=7.5, color=th["bg"] if acted else th["ink"], annotation_clip=False,
                          bbox={"boxstyle": "circle,pad=0.22", "fc": accent if acted else th["bg"],
                                "ec": accent if acted else th["muted"], "lw": 0.8})
        ax_p.legend(loc="upper left", fontsize=8.5, frameon=False, ncol=2, bbox_to_anchor=(0, 0.99))
        ts = np.arange(len(soc)) * 5
        e_max = ep["site"]["e_max_mwh"]
        ax_s.axhline(e_max, color=th["grid"], lw=1.0, ls=(0, (2, 2)))
        if op_soc is not None:
            ax_s.plot(np.arange(len(op_soc)) * 5, op_soc, color=th["op"], lw=1.3, ls=(0, (4, 2)), zorder=2,
                      label="the operator's SoC (disclosed)")
        ax_s.plot(ts, soc, color=accent, lw=1.8, zorder=3, label=f"{NAMES.get(name, name)} SoC")
        ax_s.set_ylim(0, e_max * 1.3)
        ax_s.set_ylabel("MWh", fontsize=9)
        ax_s.legend(loc="upper left", fontsize=8.5, frameon=False, ncol=2)
        ax_d.fill_between(t5, 0, np.where(metered > 0, metered, 0), step="post", color=th["discharge"], lw=0,
                          alpha=0.85, zorder=2, label="discharge")
        ax_d.fill_between(t5, 0, np.where(metered < 0, metered, 0), step="post", color=th["charge"], lw=0,
                          alpha=0.85, zorder=2, label="charge")
        ax_d.step(th_, np.append(award, award[-1]), where="post", color=th["ink"], lw=1.0, zorder=3, label="DAM award")
        for mkt, key, n, tt in (("DAM", "dam", 24, th_), ("RT", "rt", 288, np.append(t5, t5[-1] + 5))):
            aw = [i or {} for d in dates for i in (ep[key][d].get("as_award_mw") or [{}] * n)]
            up = np.array([sum(v or 0.0 for k, v in i.items() if k != "regdn") for i in aw])
            dn = np.array([-(i.get("regdn") or 0.0) for i in aw])
            for y, lab, ls in ((up, "AS up", (0, (1.5, 1.5))), (dn, "RegDn", (0, (4, 1.5)))):
                if y.any():
                    ax_d.step(tt, np.append(y, y[-1]), where="post", color=th["muted"] if key == "dam" else th["ink"],
                              lw=1.1, ls=ls, zorder=3, label=f"{lab} award ({mkt})")
        ax_d.axhline(0, color=th["muted"], lw=0.6)
        ax_d.set_ylim(ep["site"]["lsl_mw"] * 1.1, ep["site"]["hsl_mw"] * 1.5)
        ax_d.set_ylabel("MW", fontsize=9)
        ax_d.legend(loc="upper left", fontsize=8, frameon=False, ncol=4)
        ticks = ([t for t in ((-1080, -360) if nd == 1 else (-1080,)) if t >= t0] if t0 < 0 else []) + \
            [d * 1440 + h for d in range(nd) for h in (0, 360, 720, 1080)] + [1440 * nd]
        names = []
        for t in ticks:
            if t < 0:
                names.append({-1080: "06:00", -360: "18:00"}[t])
            else:
                names.append(f"{(t % 1440) // 60:02d}:00" if t % 1440 else
                             (dt.date.fromisoformat(dates[0]) + dt.timedelta(days=t // 1440)).strftime("%a %d %b")
                             if t < 1440 * nd else "24:00")
        for ax in (ax_p, ax_s):
            ax.set_xticks(ticks, [""] * len(ticks))
        ax_d.set_xticks(ticks, names)
        if t0 < 0:
            ax_p.text((t0 + 0) / 2, bot + 0.04 * (top - bot), "day before:\nDAM bids", ha="center", va="bottom",
                      fontsize=8, color=th["muted"])
        g = ep["grade"]
        title = (f"{NAMES.get(name, name)} on {label}: P {money_s(g['p'])}, R {g['reward']:.2f}, "
                 f"C {g['capture']:.2f}" if g.get("capture") is not None else f"{NAMES.get(name, name)} on {label}")
        sub = [f"anchor {money_s(g['p_anchor'])}", f"hindsight {money_s(g['p_hind'])}"]
        if g.get("p_operator_replay") is not None:
            sub.append(f"operator replay {money_s(g['p_operator_replay'])}")
        if g.get("p_operator_actual") is not None:
            sub.append(f"operator actual {money_s(g['p_operator_actual'])}")
        fig.text(0.06, 0.955, title, fontsize=12.5, color=th["ink"], fontweight="bold", ha="left")
        fig.text(0.06, 0.92, "   ·   ".join(sub), fontsize=9.5, color=th["muted"], ha="left")
        ax_t.text(0.02, 1.0, "Wake-ups and what the desk did", fontsize=9.5, color=th["ink"], fontweight="bold",
                  va="top", transform=ax_t.transAxes)
        y, step = 0.955, min(0.04, 0.93 / max(1, len(shown)))
        for i, w, tr, acted in shown:
            reasons = ",".join(r.replace("_", " ") for r in w.get("reasons", []))
            ax_t.text(0.02, y, f"{i:>2}", fontsize=7.8, color=accent if acted else th["muted"], va="top",
                      fontweight="bold", transform=ax_t.transAxes, family="monospace")
            ax_t.text(0.1, y, f"{w['label'][4:]} {reasons}", fontsize=7.8, color=th["ink"], va="top",
                      transform=ax_t.transAxes)
            ax_t.text(0.1, y - step * 0.45, clip(turn_label(ep, tr), 58), fontsize=7.4,
                      color=th["ink"] if acted else th["muted"], va="top", transform=ax_t.transAxes)
            y -= step
        if len(shown) < len(items):
            ax_t.text(0.1, y, f"+{len(items) - len(shown)} wake-ups without a submission", fontsize=7.4,
                      color=th["muted"], va="top", transform=ax_t.transAxes)
        fig.savefig(path, dpi=200)
        plt.close(fig)


def bullets(summary: dict) -> list[str]:
    ms, refs, out = summary["models"], summary["references"], []
    order = sorted(ms, key=lambda k: -(ms[k]["P"]["mean"] or -1e18))
    if order:
        top = order[0]
        m = ms[top]
        out.append(f"{NAMES.get(top, top)} has the highest mean P, {money_s(m['P']['mean'])} per battery-day "
                   f"(R {m['R']['mean']:.2f}, C {m['C']['mean']:.2f}), against the anchor's "
                   f"{money_s(refs['anchor']['P']['mean'])} and the hindsight optimum's "
                   f"{money_s(refs['hind']['P']['mean'])}.")
    for k in order:
        m = ms[k]
        g = m["P_minus_anchor"]
        if g["mean"] is not None:
            side = "above" if g["ci"][0] > 0 else "below" if g["ci"][1] < 0 else "level with"
            out.append(f"{NAMES.get(k, k)} is {side} the anchor: {fmt_ci(g, money=True, signed=True)} per "
                       f"battery-day; it beats the anchor on {pct(m['beats_anchor_share'])} of tasks.")
    for b in summary["paired"].values():
        if b["b"] == "operator_replay" or b["P"]["mean"] is None:
            continue
        a, c = b["a"], b["b"]
        if b["P"]["ci"][0] > 0 or b["P"]["ci"][1] < 0:
            out.append(f"{NAMES.get(a, a)} − {NAMES.get(c, c)}: {fmt_ci(b['P'], money=True, signed=True)} per "
                       f"battery-day; the CI excludes zero.")
        else:
            out.append(f"{NAMES.get(a, a)} − {NAMES.get(c, c)}: {fmt_ci(b['P'], money=True, signed=True)}; the CI "
                       f"includes zero.")
    op = refs.get("operator_replay", {}).get("P", {})
    if op.get("mean") is not None:
        ahead = [NAMES.get(k, k) for k in order if (ms[k]["P_minus_operator_replay"].get("ci") or [None])[0]
                 is not None and ms[k]["P_minus_operator_replay"]["ci"][0] > 0]
        out.append(f"The operator's own bids, replayed through the same clearing, earn {money_s(op['mean'])}; "
                   + (f"{', '.join(ahead)} beat{'s' if len(ahead) == 1 else ''} that with a CI above zero."
                      if ahead else "no model beats that with a CI above zero."))
    return out[:5]


def anchor_note(refs_by: dict, days: dict) -> list[str]:
    c = Counter(f"risk {x['anchor_setting']['risk']}, DAM position {x['anchor_setting']['dam_position']}"
                if x.get("anchor_setting") else "setting not recorded" for t, x in refs_by.items() if t in days)
    return [k if len(c) == 1 else f"{k} ×{v}" for k, v in c.items()]


def sensitivity(grades: dict, days: dict, union: dict, exclude: list[str]) -> dict:
    """Post hoc views: medians, means without the excluded days, per-day mean P, loss counts."""
    refk = (("anchor", "p_anchor"), ("operator_replay", "p_operator_replay"), ("operator_actual", "p_operator_actual"))
    out = {"median_P": {m: round(float(np.median([g["p"] for g in gs.values()])), 2) for m, gs in grades.items()
                        if gs},
           "median_P_references": {k: round(float(np.median(v)), 2) for k, f in refk
                                   if (v := [g[f] for g in union.values() if g.get(f) is not None])}}
    keep = [t for t in union if days[t] not in exclude]
    if exclude:
        w = {"models": {}, "references": {}}
        for m, gs in grades.items():
            ts = [t for t in gs if t in keep]
            dd = [days[t] for t in ts]
            cs = [(gs[t]["capture"], days[t]) for t in ts if gs[t]["capture"] is not None]
            cp = [(gs[t]["capture_phys"], days[t]) for t in ts if gs[t].get("capture_phys") is not None]
            w["models"][m] = {"P": boot([gs[t]["p"] for t in ts], dd), "R": boot([gs[t]["reward"] for t in ts], dd),
                    "C": boot([a for a, _ in cs], [b for _, b in cs]), "C_phys": boot([a for a, _ in cp],
                                                                                  [b for _, b in cp])}
        for k, f in refk:
            ts = [t for t in keep if union[t].get(f) is not None]
            w["references"][k] = {"P": boot([union[t][f] for t in ts], [days[t] for t in ts])}
        out["without"] = {"days": exclude, "n_tasks": len(keep), "means": w}
    by = {}
    for d in sorted({days[t] for t in union}):
        row = {"models": {}, "references": {}}
        for m, gs in grades.items():
            v = [g["p"] for t, g in gs.items() if days[t] == d]
            row["models"][m] = round(float(np.mean(v)), 2) if v else None
        for k, f in refk:
            v = [union[t][f] for t in union if days[t] == d and union[t].get(f) is not None]
            row["references"][k] = round(float(np.mean(v)), 2) if v else None
        by[d] = row
    out["per_day_mean_P"] = by
    loss = {}
    for m, gs in grades.items():
        if not gs:
            continue
        worst = min(gs, key=lambda t: gs[t]["p"])
        loss[m] = {"tasks_p_below_0": sum(g["p"] < 0 for g in gs.values()),
                   "days_mean_p_below_0": sum(1 for d in by if (by[d]["models"].get(m) or 0) < 0),
                   "worst_task": worst, "worst_p": gs[worst]["p"]}
    out["losses"] = loss
    return out


def as_md(ms: dict) -> str:
    rows = []
    for k, m in ms.items():
        a = m.get("ancillary")
        if not a:
            continue
        prods = [p for p in AS_LABEL if any(p in a[f] or f"dam:{p}" in a[f] or f"rt:{p}" in a[f]
                                            for f in ("offers_accepted", "dam_award_mwh", "rt_award_mwh"))]
        for p in prods:
            rows.append([NAMES.get(k, k), AS_LABEL[p], f"{a['offers_accepted'].get(f'dam:{p}', 0):.2f}",
                         f"{a['offers_accepted'].get(f'rt:{p}', 0):.2f}", f"{a['dam_award_mwh'].get(p, 0):,.1f}",
                         f"{a['rt_award_mwh'].get(p, 0):,.1f}"])
        codes = ", ".join(f"{c} ×{v}" for c, v in list(a["rejected_codes_total"].items())[:4]) or "none"
        rows.append([NAMES.get(k, k), "all", "", "", "", f"{a['episodes_with_awards']}/{m['n']} episodes with an AS "
                     f"award; AS rejections: {codes}"])
    if not rows:
        return ""
    return "\n".join(["### Ancillary services (mean per episode)", "",
                      table(["model", "product", "DAM submissions accepted", "RT submissions accepted",
                             "DAM award MWh", "RT award MWh"], rows), "", ""])


def sens_md(summary: dict) -> str:
    sv, ms = summary.get("sensitivity"), summary["models"]
    if not sv:
        return ""
    refs = ("anchor", "operator_replay", "operator_actual")
    lm = {k: NAMES.get(k, k) for k in ms}
    lr = {k: summary["references"][k]["label"] for k in refs}
    parts = ["## Sensitivity (post hoc, not pre-registered)", "",
             table(["", *lm.values(), *lr.values()],
                   [["median P", *[money_s(sv["median_P"][k]) for k in ms],
                     *[money_s(sv["median_P_references"][k]) if k in sv["median_P_references"] else "—"
                       for k in refs]]])]
    w = sv.get("without")
    if w:
        parts += ["", f"Means without {', '.join(w['days'])} ({w['n_tasks']} tasks):", "",
                  table(["", "n", "mean P", "R", "C", "C_phys"],
                        [[lm[k] if g == "models" else lr[k], str(v["P"]["n"]), fmt_ci(v["P"], money=True),
                          fmt_ci(v["R"], digits=2) if "R" in v else "—", fmt_ci(v["C"], digits=2) if "C" in v else "—",
                          fmt_ci(v["C_phys"], digits=2) if "C_phys" in v else "—"]
                         for g in ("models", "references") for k, v in w["means"][g].items()])]
    parts += ["", "Mean P per operating day:", "",
              table(["day", *lm.values(), *lr.values()],
                    [[d, *["—" if v is None else money_s(v) for v in [*row["models"].values(),
                                                                     *row["references"].values()]]]
                     for d, row in sv["per_day_mean_P"].items()]),
              "", table(["model", "tasks with P < 0", "days with mean P < 0", "worst task", "worst P"],
                        [[lm[k], str(v["tasks_p_below_0"]), str(v["days_mean_p_below_0"]), v["worst_task"],
                          money_s(v["worst_p"])] for k, v in sv["losses"].items()]), ""]
    return "\n".join(parts) + "\n"


def plural(n: int) -> str:
    return "" if n == 1 else "s"


def table(head: list[str], rows: list[list[str]]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
                     + ["| " + " | ".join(r) + " |" for r in rows])


def readme(summary: dict, out: Path, notes: list[str] | None) -> str:
    ms, refs, lay = summary["models"], summary["references"], summary["layer"]
    t1 = table(["model", "n", "valid", "floored", "R", "C (hindsight)", "C_phys", "mean P", "P − anchor",
                "beats anchor", "P − operator replay", "P − operator actual", "$ / episode"],
               [[NAMES.get(k, k), str(m["n"]), pct(m["valid_share"]), str(m["floored"]), fmt_ci(m["R"], digits=2),
                 fmt_ci(m["C"], digits=2), fmt_ci(m["C_phys"], digits=2), fmt_ci(m["P"], money=True),
                 fmt_ci(m["P_minus_anchor"], money=True, signed=True), pct(m["beats_anchor_share"]),
                 fmt_ci(m["P_minus_operator_replay"], money=True, signed=True),
                 fmt_ci(m["P_minus_operator_actual"], money=True, signed=True),
                 f"${m['cost_usd']['per_episode']:.2f}" if m["cost_usd"]["per_episode"] is not None else "—"]
                for k, m in ms.items()])
    t2 = table(["reference", "n", "mean P", "C", "C_phys"],
               [[r["label"], str(r["P"]["n"]), fmt_ci(r["P"], money=True),
                 f"{r['C']['mean']:.2f}" if r["C"]["mean"] is not None else "—",
                 f"{r['C_phys']['mean']:.2f}" if r["C_phys"]["mean"] is not None else "—"] for r in refs.values()])
    t3 = table(["paired gap", "n", "Δ P", "Δ R", "Δ C", "ahead (tasks)", "days ahead"],
               [[f"{NAMES.get(b['a'], b['a'])} − {NAMES.get(b['b'], b['b']).replace('_', ' ')}", str(b["P"]["n"]),
                 fmt_ci(b["P"], money=True, signed=True), fmt_ci(b["R"], signed=True, digits=2) if "R" in b else "—",
                 fmt_ci(b["C"], signed=True, digits=2) if "C" in b else "—", pct(b["P"].get("ahead")),
                 f"{b['P'].get('days_ahead', '—')}/{b['P']['days']}"] for k, b in summary["paired"].items()])
    lines = list(dict.fromkeys(ln for m in ms.values() for ln in m["lines"]))
    t4 = table(["line"] + [NAMES.get(k, k) for k in ms],
               [[ln] + [money_s(m["lines"][ln], signed=True) if ln in m["lines"] else "—" for m in ms.values()]
                for ln in lines] + [["**P**"] + [f"**{money_s(m['P']['mean'], signed=True)}**"
                                                 if m["P"]["mean"] is not None else "—" for m in ms.values()]])
    t5 = table(["model", "turns", "wakes", "calls", "top tools", "submissions ok / rejected", "rejection codes",
                "reminders", "cycles", "COP late", "input tok", "output tok", "cached tok"],
               [[NAMES.get(k, k), f"{m['turns']}", f"{m['wakes']}", f"{m['calls']}",
                 ", ".join(f"{t} {v:.1f}" for t, v in list(m["calls_by_tool"].items())[:4]),
                 f"{m['submissions']['accepted']} / {m['submissions']['rejected']}",
                 ", ".join(f"{c} ×{v}" for c, v in list(m["submissions"]["rejected_codes_total"].items())[:4]) or "—",
                 f"{m['reminders']}", f"{m['cycles']}", f"{m['cop_late']}",
                 f"{m['tokens']['input_tokens'] or 0:,.0f}", f"{m['tokens']['output_tokens'] or 0:,.0f}",
                 f"{m['tokens']['cached_tokens'] or 0:,.0f}"] for k, m in ms.items()])
    meth = summary["method"]
    settings = "; ".join(f"{NAMES.get(k, k)}: " + ", ".join(f"{a} {b}" for a, b in m["policy"].items() if b)
                         for k, m in ms.items())
    attempts = ", ".join(f"{NAMES.get(k, k)} ${m['cost_usd']['total_all_attempts']:.2f} ({m['cost_usd']['attempts']})"
                         for k, m in ms.items())
    pilot = ""
    if summary.get("pilot"):
        pilot = "\n## Pilot\n\nThe pilot pack, graded as the runner wrote it (not in the tables above).\n\n" + table(
            ["task", "policy", "R", "C", "P", "anchor", "operator replay", "turns", "$"],
            [[p["task_id"], p["tag"], f"{p['reward']:.2f}",
              "—" if p["capture"] is None else f"{p['capture']:.2f}".replace("-", "−"),
              money_s(p["p"]), money_s(p["p_anchor"]),
              "—" if p["p_operator_replay"] is None else money_s(p["p_operator_replay"]), str(p["turns"]),
              f"${p['cost_usd']:.2f}"] for p in summary["pilot"]]) + "\n"
    fig = ("![Mean P per battery-day against the references](figures/p-bars.png)\n\n"
           + (f"![{summary['hero']['model']} on {summary['hero']['task_id']}](figures/hero.png)\n"
              if summary.get("hero") else ""))
    return f"""# GridSimEnv desk {lay}: results on `{summary['pack']}`

{summary['n_tasks']} battery-days ({summary['n_days']} operating days), {len(ms)} models. P is the settled ERCOT
statement in $ per battery-day; R the contract reward (anchor = 1.0, idle = 0.2); C the hindsight capture
(P − P_idle)/(P_hind − P_idle); C_phys the same against the hindsight optimum with its DAM position tied to dispatch.
"floored" counts tasks whose reward scale is floored at 10% of (P_hind_phys − P_idle) because the anchor
earns less (contract §9.1). Brackets are 95% day-block CIs.

{t1}

### References (every task, the same clearing, physics and settlement)

{t2}

### Paired gaps (same tasks)

{t3}

### Statement lines (mean $ per battery-day)

{t4}

### Behaviour (mean per episode; codes are totals)

{t5}

{as_md(ms)}{sens_md(summary)}
{fig}
## What the numbers say

{chr(10).join('- ' + b for b in (notes or bullets(summary)))}
{pilot}
## Method

- Pack `{summary['pack']}`, layer {lay}: {summary['n_tasks']} tasks, {summary['n_days']} operating days,
  {meth['sites']} site{plural(meth['sites'])}, era{plural(len(meth['eras']))} {', '.join(meth['eras'])}.
  Every model plays every task once (`scripts/desk_run.py`, path B', the in-process Session); {meth['grading']}.
- Settings: {settings}.
- Budgets per episode: {meth['budget']}.
- CIs: day-block bootstrap, {B:,} resamples of operating days, seed {SEED}, task-weighted means (as
  `results/train/4b-blind`); paired gaps resample days over the tasks both sides played. "days ahead" counts days whose
  mean gap is positive.
- References are settled by the same clearing, physics and settlement code (contract §9.2): idle, the
  information-matched anchor, the hindsight optimum, the hindsight optimum with the DAM position tied to physical
  dispatch, the operator's disclosed curves replayed through our clearing, and the operator's disclosed awards and
  telemetry settled directly.
- Cost is the runner's metered API cost of the scored attempts; all attempts (count): {attempts}.
- Raw outputs: `runs/<model>/results.jsonl.gz`, `episodes/<model>/*.json.gz` (Episode JSON
  `gridsim.desk.episode/v1`){meth['calls_note']}. Core {meth['core_versions']}.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", required=True)
    ap.add_argument("--pack", required=True)
    ap.add_argument("--run", action="append", required=True, metavar="NAME=DIR")
    ap.add_argument("--pilot", action="append", default=[], metavar="DIR")
    ap.add_argument("--regrade", action="store_true", help="grade every episode against the pack's frozen refs")
    ap.add_argument("--refs", help="a refs.jsonl ({task_id, refs} per line) that overrides the pack's task refs")
    ap.add_argument("--hero", help="MODEL or MODEL:TASK_ID for the timeline (default: the best Sol episode by C)")
    ap.add_argument("--exclude-day", action="append", default=[], metavar="DATE",
                    help="post hoc: also report means without these operating days (Sensitivity section)")
    ap.add_argument("--notes", help="a file of README bullets (one per line) instead of the generated ones")
    ap.add_argument("--no-copy", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "figures").mkdir(parents=True, exist_ok=True)
    runs = {}
    for spec in a.run:
        name, _, d = spec.partition("=")
        runs[name] = load_run(Path(d))
    try:
        pack_tasks = {t["task_id"]: t for t in load_tasks(a.pack)}
    except (FileNotFoundError, OSError):
        pack_tasks = {}
    refs_by = {t: x["refs"] for t, x in pack_tasks.items() if x.get("refs")}
    if a.refs:
        refs_by.update({x["task_id"]: x["refs"] for x in read_jsonl(Path(a.refs))})
    grades, days, eps_any = {}, {}, {}
    regraded, diffs, unrefd = Counter(), [], Counter()
    for name, run in runs.items():
        grades[name] = {}
        for tid, r in run["rows"].items():
            ep = run["episodes"].get(tid)
            g = r["grade"]
            refs = refs_by.get(tid)
            if a.regrade and not (refs and ep):
                unrefd[name] += 1
            if a.regrade and refs and ep:
                g2 = regrade(g, ep, refs)
                regraded[name] += int(abs(g2["reward"] - g["reward"]) > 1e-6)
                d = {k: (g.get(k), g2.get(k)) for k in ("reward", "capture", "capture_phys", "p", "p_anchor", "p_hind",
                                                       "p_hind_phys", "floored")
                     if (g.get(k) is None) != (g2.get(k) is None) or (g.get(k) is not None and abs(
                         float(g[k]) - float(g2[k])) > (1e-3 if k in ("reward", "capture", "capture_phys") else 0.005))}
                if d:
                    diffs.append({"model": name, "task_id": tid, "changed": d})
                g = g2
            grades[name][tid] = g
            days[tid] = days_of(tid, ep)
            if ep:
                eps_any.setdefault(tid, ep)
    union = {}
    for name in runs:
        for tid, g in grades[name].items():
            union.setdefault(tid, g)
    models = {name: model_block(run, grades[name], days) for name, run in runs.items()}
    pairs = {}
    names = list(runs)
    for x, y in itertools.combinations(names, 2):
        common = sorted(set(grades[x]) & set(grades[y]))
        dd = [days[t] for t in common]
        b = {"P": paired([grades[x][t]["p"] for t in common], [grades[y][t]["p"] for t in common], dd),
             "R": paired([grades[x][t]["reward"] for t in common], [grades[y][t]["reward"] for t in common], dd)}
        cc = [t for t in common if grades[x][t]["capture"] is not None and grades[y][t]["capture"] is not None]
        b["C"] = paired([grades[x][t]["capture"] for t in cc], [grades[y][t]["capture"] for t in cc],
                        [days[t] for t in cc])
        pairs[f"{x}-{y}"] = {"a": x, "b": y, **b}
    for x in names:
        cc = [t for t in sorted(grades[x]) if grades[x][t].get("p_operator_replay") is not None]
        pairs[f"{x}-operator_replay"] = {"a": x, "b": "operator_replay", "P": paired([grades[x][t]["p"] for t in cc],
                                                     [grades[x][t]["p_operator_replay"] for t in cc],
                                                     [days[t] for t in cc])}
    copies = {}
    if not a.no_copy:
        for name, run in runs.items():
            copies[name] = copy_raw(name, run, out)
        for i, p in enumerate(a.pilot):
            copies[f"pilot{i or ''}"] = copy_raw(f"pilot{i or ''}", load_run(Path(p)), out)
    pilot = []
    for p in a.pilot:
        pr = load_run(Path(p))
        for tid, r in pr["rows"].items():
            g = r["grade"]
            pilot.append({"task_id": tid, "tag": r["tag"], "status": r.get("status"), "reward": g["reward"],
                          "capture": g.get("capture"), "capture_phys": g.get("capture_phys"), "p": g["p"],
                          "p_anchor": g["p_anchor"], "p_hind": g["p_hind"],
                          "p_operator_replay": g.get("p_operator_replay"), "turns": r["usage"].get("turns"),
                          "cost_usd": r["usage"].get("cost_usd", 0.0)})
    eps_all = list(eps_any.values())
    budget = eps_all[0].get("budget") if eps_all else None
    calls_mb = {k: v["calls_mb"] for k, v in copies.items()}
    skipped = [k for k, v in copies.items() if not v["calls_copied"] and v["calls_mb"]]
    summary = {
        "schema": "gridsim.desk.report/v1", "layer": a.layer, "pack": a.pack, "generated": dt.datetime.now(
            dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_tasks": len(union), "n_days": len(set(days[t] for t in union)),
        "missing": {name: sorted(set(pack_tasks) - set(grades[name])) for name in runs} if pack_tasks else None,
        "ci": {"method": "day-block bootstrap, task-weighted", "resamples": B, "seed": SEED, "level": 0.95},
        "models": models, "references": ref_block(union, days), "paired": pairs, "pilot": pilot or None,
        "sensitivity": sensitivity(grades, days, union, a.exclude_day),
        "regraded": {"applied": a.regrade, "refs": a.refs or ("pack task rows" if a.regrade else None),
                     "reward_changed": dict(regraded), "not_regraded": dict(unrefd), "diffs": diffs,
                     "anchor_settings": dict(Counter(json.dumps(x.get("anchor_setting"), sort_keys=True)
                                                     for t, x in refs_by.items() if t in days)),
                     "core_versions": dict(Counter(x.get("core_version") for t, x in refs_by.items() if t in days))},
        "copies": copies,
        "method": {"sites": len({site_key(t) for t in union}),
                   "eras": sorted({e.get("era", "?") for e in eps_all}),
                   "core_versions": ", ".join(sorted({e.get("core_version", "?") for e in eps_all})),
                   "budget": ", ".join(f"{k} {v}" for k, v in (budget or {}).items()) or "the layer's",
                   "grading": f"every grade replayed from its Episode JSON against the frozen refs "
                   f"({'`' + a.refs + '`' if a.refs else 'the pack task rows'}; anchor "
                   f"{', '.join(anchor_note(refs_by, days))})" if a.regrade else
                   "grades as the runner wrote them (refs from the task row or recomputed)",
                   "calls_note": (f"; per-call logs `runs/<model>/calls/*.jsonl.gz` (not copied for "
                                  f"{', '.join(skipped)}: over {CALLS_MAX_MB} MB)" if skipped else
                                  "; per-call logs `runs/<model>/calls/*.jsonl.gz`") if copies else "",
                   "calls_mb": calls_mb},
    }
    hero = pick_hero(summary, runs, grades, a.hero)
    if hero:
        name, tid = hero
        ep = runs[name]["episodes"][tid]
        ser = series_for(a.pack, tid, a.layer, ep)
        g = grades[name][tid]
        ep = dict(ep, grade=dict(ep["grade"], **{k: g[k] for k in ("p", "reward", "capture", "p_anchor", "p_hind",
                                                                     "p_operator_replay", "p_operator_actual")}))
        card = (ep.get("site") or {}).get("card") or {}
        label = f"{card.get('name', tid)} ({card.get('region', '')}, {card.get('size', '')}), " + \
            date_span(ep["dates"])
        for mode, suf in (("light", ""), ("dark", "-dark")):
            fig_hero(ep, ser, name, label, out / "figures" / f"hero{suf}.png", mode)
        summary["hero"] = {"model": name, "task_id": tid, "operator_soc": ser is not None, "label": label}
    for mode, suf in (("light", ""), ("dark", "-dark")):
        fig_bars(summary, out / "figures" / f"p-bars{suf}.png", mode)
    with gzip.open(out / "grades.jsonl.gz", "wt") as f:
        for row in grade_rows(runs, grades, days):
            f.write(json.dumps(row) + "\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    notes = [x.strip().lstrip("- ") for x in Path(a.notes).read_text().splitlines() if x.strip()] if a.notes else None
    (out / "README.md").write_text(readme(summary, out, notes))
    print(f"{out}: {summary['n_tasks']} tasks, models {', '.join(runs)}; hero {summary.get('hero')}")


if __name__ == "__main__":
    main()
