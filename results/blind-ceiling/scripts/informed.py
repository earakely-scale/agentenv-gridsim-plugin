"""Exploratory "informed blind" estimate (docs/prereg/v1-blind-ceiling.md): the blind LightGBM with and without day D's
system load, wind and solar forecasts from the v4 store, the last posting at or before the DAM's 10:00 CPT close on D-1.

PYTHONPATH=src:scripts:results/blind-ceiling/scripts python results/blind-ceiling/scripts/informed.py --store DIR
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import multiprocessing as mp
from pathlib import Path
from zoneinfo import ZoneInfo

import ceiling as c
import lightgbm as lgb
import numpy as np
import pyarrow.parquet as pq

from gridsim_core.task import load_pack

CT = ZoneInfo("America/Chicago")
SOURCES = {"ercot": {"load": ("ercot_load", "mw"), "wind": ("ercot_wind", "stwpf_mw"),
                     "solar": ("ercot_solar", "stppf_mw")},
           "desk": {"load": ("load", "mw"), "wind": ("wind", "mw"), "solar": ("solar", "mw")}}
WINDOW = {"ercot": ("2023-12-12", "2024-12-31"), "desk": ("2021-01-08", "2024-12-31")}
INNER = "2024-09-01"
MAX_AGE_H = 6
FC_NAMES = ["fc_load", "fc_wind", "fc_solar", "fc_net", "fc_net_rel", "fc_load_max", "fc_net_max", "fc_net_min",
            "fc_net_mean", "fc_wind_mean", "fc_solar_max"]
STACK_NAMES = ["base", "base_mean", "base_max", "base_min", "hour", "dow", "month", "hol", "hol_prev", "point", "hub"]


def series(store: Path, source: str) -> dict:
    """{load|wind|solar: (reveal_at[], start[], values[])} of the source's system series, sorted by reveal_at."""
    kinds = SOURCES[source]
    idx = pq.read_table(store / "index.parquet", columns=["kind", "run_id", "reveal_at_utc"],
                        filters=[("key", "=", "system"), ("kind", "in", [k for k, _ in kinds.values()])]).to_pylist()
    reveal = {(r["kind"], r["run_id"]): r["reveal_at_utc"] for r in idx}
    out = {}
    for name, (kind, field) in kinds.items():
        rows = []
        for f in sorted((store / "vintages").glob("*.parquet")):
            rows += pq.read_table(f, columns=["run_id", "start_utc", "values"], filters=[
                ("kind", "=", kind), ("key", "=", "system"), ("field", "=", field)]).to_pylist()
        rows.sort(key=lambda r: reveal[(kind, r["run_id"])])
        out[name] = (np.array([np.datetime64(reveal[(kind, r["run_id"])][:-1], "s") for r in rows]),
                     np.array([np.datetime64(r["start_utc"][:-1], "s") for r in rows]),
                     [np.array(r["values"], float) for r in rows])
    return out


def utc(d: dt.date, hour: int) -> np.datetime64:
    return np.datetime64(dt.datetime.combine(d, dt.time(hour), CT).astimezone(dt.UTC).replace(tzinfo=None), "s")


def day_forecast(ser: dict, d: str) -> np.ndarray | None:
    """[3, 24] load, wind, solar for day d (HE01..HE24) from the last posting at or before 10:00 CPT on d-1."""
    day = dt.date.fromisoformat(d)
    close, h0 = utc(day - dt.timedelta(days=1), 10), utc(day, 0)
    out = []
    for name in ("load", "wind", "solar"):
        rev, start, vals = ser[name]
        i = int(np.searchsorted(rev, close, side="right")) - 1
        if i < 0 or close - rev[i] > np.timedelta64(MAX_AGE_H, "h"):
            return None
        k = int((h0 - start[i]) // np.timedelta64(1, "h"))
        if k < 0 or k + 24 > len(vals[i]):
            return None
        out.append(vals[i][k:k + 24])
    return np.array(out)


def fc_X(F: np.ndarray) -> np.ndarray:
    load, wind, solar = F[:, 0], F[:, 1], F[:, 2]
    net = load - wind - solar

    def rep(a):
        return np.repeat(a, 24)

    return np.column_stack([load.ravel(), wind.ravel(), solar.ravel(), net.ravel(),
                            (net - net.mean(1, keepdims=True)).ravel(), rep(load.max(1)), rep(net.max(1)),
                            rep(net.min(1)), rep(net.mean(1)), rep(wind.mean(1)), rep(solar.max(1))]).astype(np.float32)


def stack_X(s: dict, base: np.ndarray) -> np.ndarray:
    k = c.cal(s["date"])

    def rep(a):
        return np.repeat(np.asarray(a, float), 24)

    cols = [base.ravel(), rep(base.mean(1)), rep(base.max(1)), rep(base.min(1)), np.tile(np.arange(24), len(base))]
    cols += [rep(k[x]) for x in ("dow", "month", "hol", "hol_prev")]
    cols += [rep(s["point"]), rep([c.POINTS[i].startswith("HB_") for i in s["point"]])]
    return np.column_stack(cols).astype(np.float32)


class Variant:
    """A LightGBM on a design (base | informed | stack | stack_informed), its target offset and the chosen rounds."""

    def __init__(self, kind: str, cfg: dict, base_model=None):
        self.kind, self.cfg, self.base_model, self.rounds = kind, cfg, base_model, None

    def design(self, s: dict, F) -> tuple[np.ndarray, list[str], np.ndarray]:
        if self.kind.startswith("stack"):
            base = c.lgb_predict(self.base_model, s, self.cfg)
            X, names, off = stack_X(s, base), list(STACK_NAMES), base
        else:
            X, names = c.lgb_X(s), list(c.LGB_NAMES)
            off = s["P7"].mean(1) if self.cfg["target"] == "delta" else np.zeros_like(s["y"])
        if self.kind.endswith("informed"):
            X, names = np.hstack([X, fc_X(F)]), names + FC_NAMES
        return X, names, off

    def fit(self, s: dict, F, rounds: int):
        X, names, off = self.design(s, F)
        return c.lgb_train(X, (s["y"] - off).ravel(), self.cfg, rounds, names)

    def predict(self, m, s: dict, F, it: int | None = None) -> np.ndarray:
        X, _, off = self.design(s, F)
        return m.predict(X, num_iteration=it, num_threads=c.NT).reshape(-1, 24) + off


def covered(s: dict, fc: dict) -> np.ndarray:
    return np.array([fc.get(d) is not None for d in s["date"]])


def run(source: str, ser: dict, pool, tr: dict, sets: dict, inner: tuple, cfg: dict, pre, main: dict) -> dict:
    lo, hi = WINDOW[source]
    days = sorted(set(tr["date"][(tr["date"] >= lo) & (tr["date"] <= hi)]) | {t["date"] for t in inner[0]}
                  | {t["date"] for v in sets.values() for t in v[0]})
    fc = {d: day_forecast(ser, d) for d in days}
    win = c.sub(tr, (tr["date"] >= lo) & (tr["date"] <= hi))
    win = c.sub(win, covered(win, fc))

    def ff(s: dict) -> np.ndarray:
        return np.stack([fc[d] for d in s["date"]])

    ins = c.task_samples(inner[0], {})
    keep = covered(ins, fc)
    ins, iidx = c.sub(ins, keep), inner[1][keep]
    out = {"window": [lo, hi], "n_window_point_days": len(win["date"]), "n_inner_tasks": len(iidx),
           "forecast_days_missing": sorted(d for d, v in fc.items() if v is None)[:50], "variants": {}, "packs": {}}
    kinds = ["base", "informed"] + (["stack", "stack_informed"] if source == "ercot" else [])
    models = {}
    for kind in kinds:
        v = Variant(kind, cfg, pre)
        fit = c.sub(win, win["date"] < INNER)
        if kind.startswith("stack"):
            fit = c.sub(fit, fit["date"] >= c.HOLDOUT)
        m = v.fit(fit, ff(fit), c.ROUNDS[-1])
        cs = {k: round(float(c.plan(pool, iidx, v.predict(m, ins, ff(ins), k))[:, 0].mean()), 4) for k in c.ROUNDS}
        v.rounds = max(cs, key=cs.get)
        full = c.sub(win, win["date"] >= c.HOLDOUT) if kind.startswith("stack") else win
        models[kind] = (v, v.fit(full, ff(full), v.rounds))
        out["variants"][kind] = {"rounds": v.rounds, "inner_c_by_rounds": cs, "n_fit_point_days": len(full["date"])}
        c.log(f"{source} {kind}: rounds {v.rounds} inner C {cs[v.rounds]}")
    for name, (tasks, idx) in sets.items():
        s = c.task_samples(tasks, {})
        keep = covered(s, fc)
        if not keep.any():
            continue
        s, idx, tk = c.sub(s, keep), idx[keep], [t for t, k in zip(tasks, keep, strict=True) if k]
        res = {k: c.plan(pool, idx, v.predict(m, s, ff(s))) for k, (v, m) in models.items()}
        if source == "ercot":
            res["pre2024_lgb"] = c.plan(pool, idx, c.lgb_predict(pre, s, cfg))
        pos = {t: i for i, t in enumerate(main[name]["task_id"])}
        j = [pos[t["task_id"]] for t in tk]
        for k in ("sol", "anchor", main["best"]):
            res[k] = np.asarray(main[name][k])[j]
        dates = s["date"]
        u = c.unique_days(s)
        pk = {"n_tasks": len(tk), "n_days": len(set(dates)), "days": [min(dates), max(dates)],
              "c": {k: c.boot(dates, r[:, 0]) for k, r in res.items()},
              "forecast_err": {k: c.err(v.predict(m, s, ff(s))[u], s["y"][u]) for k, (v, m) in models.items()},
              "gaps": {}}
        pairs = [("informed", "base"), ("informed", "sol"), ("base", "sol"), ("informed", main["best"])]
        if source == "ercot":
            pairs += [("stack_informed", "stack"), ("stack", "pre2024_lgb"), ("stack_informed", "pre2024_lgb"),
                      ("stack_informed", "sol")]
        for a, b in pairs:
            g = c.boot(dates, res[a][:, 0] - res[b][:, 0])
            pk["gaps"][f"{a} - {b}"] = g | {"wins": round(float((res[a][:, 2] > res[b][:, 2] + 1e-6).mean()), 4)}
            c.log(f"{source} {name} {a} - {b}: {g}")
        out["packs"][name] = pk
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", required=True)
    ap.add_argument("--work", default=str(c.ROOT / "results" / "blind-ceiling" / "runs"))
    a = ap.parse_args()
    work, store = Path(a.work), Path(a.store)
    tune = json.loads((work / "tune.json").read_text())
    with gzip.open(work / "per_task.json.gz", "rt") as f:
        main_res = json.load(f)
    best = json.loads((work / "final.json").read_text())["verdict"]["best_method"]
    main_res = {k: v for k, v in main_res.items()} | {"best": best}
    cfg = tune["lgb_best"]["cfg"]
    pre = lgb.Booster(model_file=str(work / "lgb_pre2024.txt"))
    dam = c.load_dam()
    tr = c.train_samples(dam)
    inner = [t for t in load_pack("ercot-dam-v1-train") if t["date"] >= INNER and t["tags"].get("blind_eval")]
    sets = {k: [t for t in load_pack(v) if t["tags"].get("blind_eval")] for k, v in c.PACKS.items()}
    c.TASKS.extend(inner)
    inner_idx, off, sets_idx = np.arange(len(inner)), len(inner), {}
    for k, v in sets.items():
        c.TASKS.extend(v)
        sets_idx[k] = (v, np.arange(off, off + len(v)))
        off += len(v)
    sers = {src: series(store, src) for src in SOURCES}
    c.log(f"store series loaded: { {s: {k: len(v[0]) for k, v in x.items()} for s, x in sers.items()} }")
    out = {"exploratory": True, "cfg": cfg, "max_age_h": MAX_AGE_H, "inner_split": INNER, "sources": {}}
    with mp.get_context("fork").Pool(c.NT) as pool:
        for src, ser in sers.items():
            out["sources"][src] = run(src, ser, pool, tr, sets_idx, (inner, inner_idx), cfg, pre, main_res)
    (work / "informed.json").write_text(json.dumps(out, indent=1) + "\n")
    c.log("done")


if __name__ == "__main__":
    main()
