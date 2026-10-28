"""Build v3's regulation drift inputs (V3-D8) from the reduced 60-Day SCED Disclosure days in
cache/raw/hybrid/sced60/days/ (scripts/fetch_reg_deployment.py): data/hybrid/reg_deploy.jsonl.gz (ERCOT's storage fleet
regulation deployment per hour), data/hybrid/reg_model.json (its means and the imbalance-driven fallback fitted to it)
and data/hybrid/reg_deploy.md (method, coverage and checks).

Per disclosed snapshot, the fleet's deployment fraction is the regulation carriers' summed deviation from base point
over their RegUp responsibility (when up) or RegDn responsibility (when down), clipped to [-1, 1]; an hour's RegUp
(RegDn) fraction is the mean of its snapshots' positive (negative) parts."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_live_pack as v2  # noqa: E402
import build_pack as v1  # noqa: E402

DAYS = ROOT / "cache" / "raw" / "hybrid" / "sced60" / "days"
OUT = ROOT / "data" / "hybrid"
POINT = "HB_HUBAVG"
RTCB = "2025-12-05"
URI = ("2021-02-07", "2021-02-25")
SCALES = (1, 2, 3, 5, 10, 20, 30, 50, 100, 200)
NOISE_SD = 0.02
LABEL_DATA = ("Regulation drift is ERCOT's energy storage fleet regulation deployment in that hour (60-Day SCED "
              "Disclosure, NP3-965-ER)")
LABEL_MODEL = ("Regulation drift is modelled: RegUp deploys when the hour's RT clears above DA, RegDn when below, "
               "fitted to ERCOT's storage fleet deployment")


def log(msg: str):
    print(f"[build_reg_drift] {msg}", flush=True)


def _order(key: str) -> tuple:
    m, d, y = key[:10].split("/")
    return y, m, d, key[11:13], key.endswith("R"), key[14:19]


def frac(e: list, ref: str = "bp1") -> float | None:
    """A snapshot's signed fleet deployment fraction (+ up), or None without carriers. ref is the base point the
    output is measured from: the run's own (bp), the previous disclosed run's (bp1), three runs back (bp3), or the
    target the base points imply at the run's time, two thirds of the way from bp1 (bp3) to bp (i1, i3)."""
    tno, bp, bp1, bp3, ru, rd, _, _, n = e
    if not n:
        return None
    dev = tno - {"bp": bp, "bp1": bp1, "bp3": bp3, "i1": (2 * bp + bp1) / 3, "i3": (2 * bp + bp3) / 3}[ref]
    f = dev / ru if dev > 0 and ru > 0 else dev / rd if dev < 0 and rd > 0 else 0.0
    return max(-1.0, min(1.0, f))


def hourly(snaps: list[tuple[str, dict]], ref: str) -> tuple[list[float], list[float], list[int]]:
    by = collections.defaultdict(list)
    for k, s in snaps:
        if (f := frac(s["esr"], ref)) is not None:
            by[int(k[11:13])].append(f)
    up = [round(float(np.mean([max(0.0, x) for x in by[h]])), 4) if by[h] else 0.0 for h in range(24)]
    dn = [round(float(np.mean([max(0.0, -x) for x in by[h]])), 4) if by[h] else 0.0 for h in range(24)]
    return up, dn, [len(by[h]) for h in range(24)]


def quarter_first(snaps: list[tuple[str, dict]]) -> list[tuple[str, dict]]:
    """The first SCED run in each 15-minute window: what the disclosure carried before RTC+B."""
    seen, out = set(), []
    for k, s in snaps:
        q = (k[:13], k.endswith("R"), int(k[14:16]) // 15)
        if q not in seen:
            seen.add(q)
            out.append((k, s))
    return out


def day_row(d: dict, ref: str) -> dict:
    snaps = sorted(d["snapshots"].items(), key=lambda x: _order(x[0]))
    every_run = d["date"] >= RTCB
    up, dn, n = hourly(snaps, "bp1" if every_run else ref)
    e = [s["esr"] for _, s in snaps if s["esr"][8]]
    coh = [max(x[6], x[7]) / (x[6] + x[7]) for x in e if x[6] + x[7]]
    return {"date": d["date"], "up": up, "dn": dn, "n": n,
            "sampling": "every SCED run" if every_run else "one SCED run per 15 minutes",
            "carriers": round(float(np.mean([x[8] for x in e])), 1) if e else 0,
            "regup_mw": round(float(np.mean([x[4] for x in e])), 1) if e else 0,
            "regdn_mw": round(float(np.mean([x[5] for x in e])), 1) if e else 0,
            "coherence": round(float(np.mean(coh)), 3) if coh else None,
            "doc_id": d["doc_id"], "sha256": d["sha256"]}


def validate(days: list[dict]) -> dict:
    """On RTC+B days (every run disclosed), the hourly fractions from the first run per 15 minutes measured from the
    base point a 15-minute disclosure offers (the run's own, the one 15 minutes back, or the target between them)
    against every run measured from the previous run's: which reference the pre-RTC+B days should use (bp3 there is
    bp1 before RTC+B, i3 is i1)."""
    out = {}
    for ref in ("bp3", "bp", "i3") if days else ():
        a, b = [], []
        for d in days:
            snaps = sorted(d["snapshots"].items(), key=lambda x: _order(x[0]))
            tu, td, tn = hourly(snaps, "bp1")
            su, sd, sn = hourly(quarter_first(snaps), ref)
            for h in range(24):
                if tn[h] and sn[h]:
                    a.append((tu[h], td[h]))
                    b.append((su[h], sd[h]))
        a, b = np.array(a), np.array(b)
        out[ref] = {"hours": len(a), "corr_up": round(float(np.corrcoef(a[:, 0], b[:, 0])[0, 1]), 3),
                    "corr_dn": round(float(np.corrcoef(a[:, 1], b[:, 1])[0, 1]), 3),
                    "mae_up": round(float(np.abs(a[:, 0] - b[:, 0]).mean()), 4),
                    "mae_dn": round(float(np.abs(a[:, 1] - b[:, 1]).mean()), 4),
                    "mean_truth": [round(float(x), 4) for x in a.mean(0)],
                    "mean_sample": [round(float(x), 4) for x in b.mean(0)]}
    return out


def fit_side(x: np.ndarray, y: np.ndarray) -> dict:
    """y ~ a * tanh(x / S) for x > 0: the scale with the least squared error and its least-squares a."""
    best = None
    for S in SCALES:
        g = np.tanh(x / S)
        a = float(np.clip((g * y).sum() / (g * g).sum(), 0.0, 1.0))
        sse = float(((y - a * g) ** 2).sum())
        if best is None or sse < best["sse"]:
            best = {"scale_usd": S, "max": round(a, 4), "sse": sse}
    return best


def spread_table(dlt: np.ndarray, up: np.ndarray, dn: np.ndarray, m: dict) -> list[dict]:
    rows = []
    edges = (-math.inf, -100, -20, -5, 0, 5, 20, 100, math.inf)
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        k = (dlt >= lo) & (dlt < hi)
        if not k.any():
            continue
        g = np.tanh(dlt[k] / m["scale_usd"])
        rows.append({"rt_minus_da": [lo, hi], "hours": int(k.sum()), "up": round(float(up[k].mean()), 3),
                     "dn": round(float(dn[k].mean()), 3),
                     "model_up": round(float((m["up_max"] * np.maximum(g, 0)).mean()), 3),
                     "model_dn": round(float((m["dn_max"] * np.maximum(-g, 0)).mean()), 3)})
    return rows


def model_means(dlt: np.ndarray, m: dict, seed: int = 4322) -> tuple[float, float]:
    """The fallback's expected fractions over a spread sample, noise included (the projection's reg_drift_mean)."""
    rng = random.Random(seed)
    g = np.tanh(dlt / m["scale_usd"])
    up = [min(1.0, max(0.0, m["up_max"] * max(x, 0.0) + rng.gauss(0.0, NOISE_SD))) for x in g]
    dn = [min(1.0, max(0.0, m["dn_max"] * max(-x, 0.0) + rng.gauss(0.0, NOISE_SD))) for x in g]
    return round(float(np.mean(up)), 4), round(float(np.mean(dn)), 4)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--raw", default=str(ROOT / "cache" / "raw"))
    ap.add_argument("--cache", default=str(ROOT / "cache" / "parsed"))
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    files = sorted(DAYS.glob("*.json.gz"))
    raw = [json.loads(gzip.open(p, "rt").read()) for p in files]
    log(f"{len(raw)} reduced days {raw[0]['date']}..{raw[-1]['date']}")
    val = validate([d for d in raw if d["date"] >= RTCB])
    log(f"pre-RTC+B reference check on {sum(d['date'] >= RTCB for d in raw)} RTC+B days: {val}")
    pick = min(val, key=lambda k: val[k]["mae_up"] + val[k]["mae_dn"]) if val else "bp3"
    ref = {"bp3": "bp1", "bp": "bp", "i3": "i1"}[pick]
    rows = [day_row(d, ref) for d in raw]
    dam, _ = v1.load_dam(Path(args.raw) / "ercot", Path(args.cache), args.workers)
    rt, _ = v2.load_rt(Path(args.raw) / "ercot-rt", Path(args.cache), args.workers)
    rth = {k: v.reshape(24, 4).mean(axis=1) for k, v in rt.items() if k[1] == POINT}
    dlt, up, dn = [], [], []
    for r in rows:
        k = (r["date"], POINT)
        if k in dam and k in rth:
            for h in range(24):
                if r["n"][h]:
                    dlt.append(rth[k][h] - dam[k][h])
                    up.append(r["up"][h])
                    dn.append(r["dn"][h])
    dlt, up, dn = np.array(dlt), np.array(up), np.array(dn)
    fu, fd = fit_side(dlt[dlt > 0], up[dlt > 0]), fit_side(-dlt[dlt < 0], dn[dlt < 0])
    best = None
    for S in SCALES:
        gu, gd = np.tanh(np.maximum(dlt, 0) / S), np.tanh(np.maximum(-dlt, 0) / S)
        au = float(np.clip((gu * up).sum() / (gu * gu).sum(), 0, 1))
        ad = float(np.clip((gd * dn).sum() / (gd * gd).sum(), 0, 1))
        sse = float(((up - au * gu) ** 2).sum() + ((dn - ad * gd) ** 2).sum())
        if best is None or sse < best[0]:
            best = (sse, S, au, ad)
    _, scale, au, ad = best
    fb = {"rule": "up = up_max * tanh(max(RT - DA, 0) / scale), dn = dn_max * tanh(max(DA - RT, 0) / scale), each "
                  "plus N(0, noise_sd) clipped to [0, 1]; RT and DA are the task's settlement point's hourly prices",
          "up_max": round(au, 4), "dn_max": round(ad, 4), "scale_usd": scale, "noise_sd": NOISE_SD,
          "seed": "gridsim_core.task.stable_seed(task_id + '|reg-model'), random.Random",
          "fit": f"least squares over {len(dlt)} measured hours at {POINT}, scale on a grid {list(SCALES)}",
          "label": LABEL_MODEL, "per_side": {"up": fu, "dn": fd}}
    fall = np.concatenate([rth[k] - dam[k] for k in sorted(dam) if k[1] == POINT and k in rth
                           and "2021-01-01" <= k[0] < rows[0]["date"] and not URI[0] <= k[0] <= URI[1]])
    fb["mean_up"], fb["mean_dn"] = model_means(fall, fb)
    full = [r for r in rows if all(r["n"])]
    data = {"source": "ERCOT public API, NP3-965-ER 60-Day SCED Disclosure Reports (archive from 2023-12-11 "
                      "postings)", "first": rows[0]["date"], "last": rows[-1]["date"], "days": len(rows),
            "days_all_hours": len(full),
            "mean_up": round(float(np.mean([x for r in full for x in r["up"]])), 4),
            "mean_dn": round(float(np.mean([x for r in full for x in r["dn"]])), 4),
            "mean_by_hour": {"up": [round(float(np.mean([r["up"][h] for r in full])), 3) for h in range(24)],
                             "dn": [round(float(np.mean([r["dn"][h] for r in full])), 3) for h in range(24)]},
            "coherence_mean": round(float(np.mean([r["coherence"] for r in rows if r["coherence"]])), 3),
            "corr_net_vs_spread": round(float(np.corrcoef(up - dn, np.clip(dlt, -100, 100))[0, 1]), 3),
            "label": LABEL_DATA,
            "method": "per snapshot: carriers' sum of (telemetered net output - base point) over their RegUp "
                      "responsibility when positive, RegDn when negative, clipped to [-1, 1]; charging-side CLRs "
                      "before RTC+B count consumption as negative output; hourly up/dn = mean positive/negative part",
            "reference_bp": {"bp1": "the resource's previous disclosed base point (about 15 minutes earlier)",
                             "bp": "the disclosed run's own base point",
                             "i1": "the target the base points imply at the run's time, two thirds of the way from "
                                   "the previous disclosed base point to the run's own"}[ref]
                            + " before RTC+B; the previous SCED run's base point from RTC+B",
            "reference_pre_rtcb": ref, "validation": val}
    model = {"schema": "gridsim.reg-drift/v1", "data": data, "fallback": fb,
             "spread_table": spread_table(dlt, up, dn, fb), "point": POINT}
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / "reg_deploy.jsonl.gz", "wt") as f:
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    (OUT / "reg_model.json").write_text(json.dumps(model, indent=1) + "\n")
    (OUT / "reg_deploy.md").write_text(report(model, rows))
    man = json.loads((OUT / "manifest.json").read_text())
    for name in ("reg_deploy.jsonl.gz", "reg_model.json", "reg_deploy.md"):
        p = OUT / name
        man["outputs"][name] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    man["built_from"]["cache/raw/hybrid/sced60/days"] = {
        "days": len(raw), "product": "NP3-965-ER", "via": "api.ercot.com/api/public-reports/archive/np3-965-er",
        "sha256_of_doc_sha256s": hashlib.sha256("".join(d["sha256"] for d in raw).encode()).hexdigest()}
    (OUT / "manifest.json").write_text(json.dumps(man, indent=1, default=str) + "\n")
    log(f"data means up {data['mean_up']} dn {data['mean_dn']}; fallback {fb['up_max']}/{fb['dn_max']} scale "
        f"{scale} means {fb['mean_up']}/{fb['mean_dn']}")


def report(m: dict, rows: list[dict]) -> str:
    d, f = m["data"], m["fallback"]
    yrs = collections.Counter(r["date"][:4] for r in rows)
    lines = ["# v3 regulation drift: ERCOT's storage fleet deployment and the fallback", "",
             f"Built by `scripts/build_reg_drift.py` ({dt.date.today().isoformat()}) from the reduced 60-Day SCED "
             "Disclosure days (`scripts/fetch_reg_deployment.py`). Loader: `gridsim_core.hybrid_inputs.reg_hourly`.",
             "", "## Source", "",
             "ERCOT publishes no regulation deployment or ACE series. Its public API lists 120 products; the closest "
             "are the AS deployment factors (NP5-520-ER, NP5-526-CD, NP5-528-CD), which are RUC planning inputs from "
             "2025-12-05, not deployments. The 60-Day SCED Disclosure (NP3-965-ER) gives, per resource and disclosed "
             "SCED run, the telemetered net output, the base point and the RegUp/RegDn responsibility (awards from "
             "RTC+B). Regulation is the gap between a carrier's output and its base point, so the energy storage "
             "fleet's summed gap over its responsibility is its deployed fraction. Storage carries most of ERCOT's "
             "regulation and tracks base points closely, so only storage carriers are summed (online storage without "
             "a regulation award is kept as a control in the reduced days).", "",
             f"- Coverage: {d['first']}..{d['last']}, {d['days']} operating days "
             f"({', '.join(f'{k} {v}' for k, v in sorted(yrs.items()))}); "
             f"{d['days_all_hours']} with every hour measured. Before {d['first']} (the archive starts with postings "
             "on 2023-12-11) the fallback is used.",
             "- Sampling: one SCED run per 15 minutes is disclosed before RTC+B (2025-12-05) and every run after.",
             f"- Signal check: the carriers deviating more than 0.5 MW agree in sign on {d['coherence_mean']:.0%} of "
             "them per snapshot on average (a fleet-wide LFC signal, not tracking noise).",
             f"- Reference base point: {d['reference_bp']}." + (
                 " On RTC+B days, the hourly fractions from the first run per 15 minutes against the base point about "
                 "15 minutes old reproduce every-run fractions with correlation (up/down) "
                 + ", ".join(f"{k} {v[k]['corr_up']}/{v[k]['corr_dn']} (MAE {v[k]['mae_up']}/{v[k]['mae_dn']})"
                             for k in v) + " (bp3: 15 minutes back; bp: the run's own; i3: the implied target)."
                 if (v := d["validation"]) else ""), "", "## Measured", "",
             f"- Mean fractions of the award: RegUp {d['mean_up']}, RegDn {d['mean_dn']} (the projection's "
             "`reg_drift_mean` on measured days).",
             f"- Correlation of the hourly net (up - dn) with RT - DA at {m['point']}: {d['corr_net_vs_spread']}.",
             "- By hour (HE01..HE24) RegUp: " + " ".join(f"{x:.2f}" for x in d["mean_by_hour"]["up"]),
             "- By hour RegDn: " + " ".join(f"{x:.2f}" for x in d["mean_by_hour"]["dn"]), "",
             "## Fallback (no measured series: 2021-01-01 until the series starts)", "",
             f"`{f['rule']}`: up_max {f['up_max']}, dn_max {f['dn_max']}, scale ${f['scale_usd']}/MWh, noise sd "
             f"{f['noise_sd']}, seeded per task. Fit: {f['fit']}. Expected fractions over 2021..{d['first']} at "
             f"{m['point']}: RegUp {f['mean_up']}, RegDn {f['mean_dn']} (the projection's `reg_drift_mean` on "
             "modelled days). Labelled modelled in every task row.", "",
             "| RT - DA ($/MWh) | Hours | Measured up | Measured dn | Model up | Model dn |",
             "|---|---|---|---|---|---|"]
    for r in m["spread_table"]:
        lo, hi = r["rt_minus_da"]
        lines.append(f"| {lo:g}..{hi:g} | {r['hours']} | {r['up']} | {r['dn']} | {r['model_up']} | "
                     f"{r['model_dn']} |")
    lines += ["", "The measured fleet deploys in both directions within most hours, so the one-sided fallback "
              "understates the gross deployment in the direction against the spread; it is the rule V3-D8 asked for, "
              "fitted to the measured fraction in the spread's direction.", ""]
    return "\n".join(lines)


if __name__ == "__main__":
    main()
