"""Blind-tier ceiling check (docs/prereg/v1-blind-ceiling.md): information-matched forecasters planned with the DP.

PYTHONPATH=src:scripts python results/blind-ceiling/scripts/ceiling.py tune|final|extend --work DIR
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import gzip
import itertools
import json
import multiprocessing as mp
import time
from pathlib import Path

import build_pack as bp
import lightgbm as lgb
import numpy as np
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from threadpoolctl import threadpool_limits

from gridsim_core.baselines import ridge_features, ridge_fit
from gridsim_core.contract import P_FLOOR
from gridsim_core.dp import action_order, dp_schedule
from gridsim_core.grade import grade
from gridsim_core.physics import cash
from gridsim_core.task import battery_of, load_pack, stable_seed

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / "cache" / "parsed" / "dam-a5c0b0fae22b11ea.json.gz"
API = ROOT / "data" / "ercot-dam-v1-fresh-2026-10" / "dam_spp_api.csv.gz"
PACKS = {"eval2025": "ercot-dam-v1-eval", "fresh": "ercot-dam-v1-fresh-2026-10-blind"}
POINTS = bp.POINTS
HOLDOUT = "2024-01-01"
N_SCEN, BOOT, NT = 20, 10_000, 32
LGB_GRID = [dict(obj=o, target=t, leaves=lv, mcs=m) for o in ("l2", "huber") for t in ("level", "delta")
            for lv in (63, 255) for m in (100, 400)]
MLP_GRID = [dict(tf=t, width=w, alpha=a) for t in ("raw", "asinh") for w in (128, 512) for a in (1e-4, 1e-2)]
MLP_SEEDS = (0, 1, 2)
ROUNDS = (25, 50, 100, 200, 400, 800, 1200, 1600, 2000)
EXT_ROUNDS = (5, 10, 15, *ROUNDS)
EXT_GRID = [dict(cfg, half_life=h) for cfg in LGB_GRID if cfg["obj"] == "huber" for h in (1, 2, 4, None)]
EXT_MEMBERS = ("persist", "m7", "ridge", "lgb", "mlp")
MEMBERS = ("persist", "ridge", "lgb", "mlp")
T0 = time.time()
TASKS: list[dict] = []


def log(msg: str):
    print(f"[{time.time() - T0:7.0f}s] {msg}", flush=True)


def holidays(year: int) -> set[dt.date]:
    """US holidays that move ERCOT load: New Year, Memorial, July 4, Labor, Thanksgiving + Friday, Dec 24/25/31."""
    may31 = dt.date(year, 5, 31)
    memorial = may31 - dt.timedelta(days=may31.weekday())
    sep1 = dt.date(year, 9, 1)
    labor = sep1 + dt.timedelta(days=(7 - sep1.weekday()) % 7)
    nov1 = dt.date(year, 11, 1)
    thanks = nov1 + dt.timedelta(days=(3 - nov1.weekday()) % 7 + 21)
    return {dt.date(year, 1, 1), memorial, dt.date(year, 7, 4), labor, thanks, thanks + dt.timedelta(days=1),
            dt.date(year, 12, 24), dt.date(year, 12, 25), dt.date(year, 12, 31)}


HOL = set().union(*(holidays(y) for y in range(2013, 2028)))


def cal(dates) -> dict:
    ds = [dt.date.fromisoformat(x) for x in dates]
    doy = np.array([x.timetuple().tm_yday for x in ds]) / 365.25 * 2 * np.pi
    return {"dow": np.array([x.weekday() for x in ds]), "month": np.array([x.month for x in ds]),
            "doy_sin": np.sin(doy), "doy_cos": np.cos(doy), "year": np.array([x.year for x in ds]),
            "hol": np.array([x in HOL for x in ds], float),
            "hol_prev": np.array([x - dt.timedelta(days=1) in HOL for x in ds], float)}


def load_dam() -> dict:
    """{(date, point): prices[24]}: the parsed NP4-180-ER cache, plus the API pull for days the cache lacks."""
    with gzip.open(CACHE, "rt") as f:
        dam = {tuple(k.split("|")): np.array(v) for k, v in json.load(f)["dam"].items()}
    by: dict = {}
    with gzip.open(API, "rt") as f:
        for r in csv.DictReader(f):
            if r["DSTFlag"] != "True":
                by.setdefault((r["deliveryDate"], r["settlementPoint"]), {})[int(r["hourEnding"][:2])] = float(
                    r["settlementPointPrice"])
    for k, hv in by.items():
        if k not in dam and k[1] in POINTS and sorted(hv) == list(range(1, 25)):
            dam[k] = np.array([hv[h] for h in range(1, 25)])
    return dam


def prev(d: str, i: int = 1) -> str:
    return (dt.date.fromisoformat(d) - dt.timedelta(days=i)).isoformat()


def samples(rows, dam) -> dict:
    """rows of (date, point, P7[7,24] oldest first, y[24]) -> arrays, plus every point's D-1 (x15, exploratory)."""
    nan = np.full(24, np.nan)
    return {"date": np.array([r[0] for r in rows]), "point": np.array([POINTS.index(r[1]) for r in rows]),
            "P7": np.round(np.stack([r[2] for r in rows]), 2), "y": np.stack([r[3] for r in rows]),
            "x15": np.stack([[dam.get((prev(r[0]), q), nan) for q in POINTS] for r in rows])}


def train_samples(dam) -> dict:
    kept, _ = bp.dedup(dam)
    rows = []
    for d, p in kept:
        if d <= "2024-12-31" and bp.split(d) == "train":
            lag = [dam.get((prev(d, i), p)) for i in range(7, 0, -1)]
            if all(x is not None for x in lag):
                rows.append((d, p, np.stack(lag), dam[(d, p)]))
    return samples(rows, dam)


def task_samples(tasks, dam) -> dict:
    return samples([(t["date"], t["settlement_point"], np.array(t["blind"]["dam_prev_7d"]), np.array(t["prices"]))
                    for t in tasks], dam)


def sub(s: dict, m) -> dict:
    return {k: v[m] for k, v in s.items()}


def core(s: dict) -> dict:
    return {k: s[k] for k in ("date", "point", "P7", "y")}


LGB_NAMES = ([f"lag{k}" for k in range(1, 8)] + ["p1_prev_h", "p1_next_h", "d1_mean", "d1_std", "d1_min", "d1_max",
             "w_mean", "w_std", "w_min", "w_max", "m7_h", "hour", "dow", "month", "doy_sin", "doy_cos", "year", "hol",
             "hol_prev", "point", "hub"])


def lgb_X(s: dict, extended: bool = False) -> np.ndarray:
    n, P7 = len(s["date"]), s["P7"]
    p1, flat, c = P7[:, -1], P7.reshape(len(P7), -1), cal(s["date"])

    def rep(a):
        return np.repeat(np.asarray(a, float), 24)

    cols = [P7[:, 7 - k].ravel() for k in range(1, 8)]
    cols += [np.concatenate([p1[:, :1], p1[:, :-1]], 1).ravel(), np.concatenate([p1[:, 1:], p1[:, -1:]], 1).ravel()]
    cols += [rep(f(p1, 1)) for f in (np.mean, np.std, np.min, np.max)]
    cols += [rep(f(flat, 1)) for f in (np.mean, np.std, np.min, np.max)]
    cols += [P7.mean(1).ravel(), np.tile(np.arange(24), n)]
    cols += [rep(c[k]) for k in ("dow", "month", "doy_sin", "doy_cos", "year", "hol", "hol_prev")]
    cols += [rep(s["point"]), rep([POINTS[i].startswith("HB_") for i in s["point"]])]
    if extended:
        cols += [s["x15"][:, q].ravel() for q in range(len(POINTS))]
    return np.column_stack(cols).astype(np.float32)


def lgb_names(extended: bool) -> list[str]:
    return LGB_NAMES + ([f"d1_{q}" for q in POINTS] if extended else [])


def lgb_fit(s: dict, cfg: dict, rounds: int, extended: bool = False):
    w = None
    if cfg.get("half_life"):
        year = np.array([int(d[:4]) for d in s["date"]])
        w = np.repeat(0.5 ** ((year.max() - year) / cfg["half_life"]), 24)
    return lgb_train(lgb_X(s, extended), lgb_target(s, cfg), cfg, rounds, lgb_names(extended), w)


def lgb_train(X: np.ndarray, y: np.ndarray, cfg: dict, rounds: int, names: list[str], weight=None):
    params = dict(objective=cfg["obj"], learning_rate=0.05, num_leaves=cfg["leaves"],
                  min_child_samples=cfg["mcs"], feature_fraction=0.8, bagging_fraction=0.8, bagging_freq=1,
                  lambda_l2=1.0, verbose=-1, num_threads=NT, seed=0)
    if cfg["obj"] == "huber":
        params["alpha"] = 20.0
    return lgb.train(params, lgb.Dataset(X, y, weight=weight, feature_name=names, categorical_feature=["point"]),
                     rounds)


def lgb_target(s: dict, cfg: dict) -> np.ndarray:
    return (s["y"] - (s["P7"].mean(1) if cfg["target"] == "delta" else 0)).ravel()


def lgb_predict(model, s: dict, cfg: dict, extended: bool = False, it: int | None = None) -> np.ndarray:
    f = model.predict(lgb_X(s, extended), num_iteration=it, num_threads=NT).reshape(-1, 24)
    return f + (s["P7"].mean(1) if cfg["target"] == "delta" else 0)


def mlp_X(s: dict, tf: str) -> np.ndarray:
    n, c = len(s["date"]), cal(s["date"])
    lag = s["P7"].reshape(n, -1)
    lag = np.arcsinh(lag / 50) if tf == "asinh" else lag / 100
    return np.column_stack([lag, np.eye(7)[c["dow"]], np.eye(12)[c["month"] - 1], c["doy_sin"], c["doy_cos"],
                            (c["year"] - 2019) / 5, c["hol"], c["hol_prev"], np.eye(len(POINTS))[s["point"]]])


def mlp_fit_one(args):
    s, cfg, seed = args
    with threadpool_limits(2):
        x = mlp_X(s, cfg["tf"])
        z = np.arcsinh(s["y"] / 50) if cfg["tf"] == "asinh" else s["y"] / 100
        sx, sz = StandardScaler().fit(x), StandardScaler().fit(z)
        m = MLPRegressor(hidden_layer_sizes=(cfg["width"], cfg["width"]), alpha=cfg["alpha"], batch_size=256,
                         learning_rate_init=1e-3, max_iter=300, early_stopping=True, n_iter_no_change=15,
                         random_state=seed)
        m.fit(sx.transform(x), sz.transform(z))
        model = {"cfg": cfg, "sx": sx, "sz": sz, "m": m, "corr": np.zeros(24)}
        model["corr"] = (s["y"] - mlp_predict_one(model, s)).mean(0) if cfg["tf"] == "asinh" else np.zeros(24)
        return model


def mlp_predict_one(model: dict, s: dict) -> np.ndarray:
    z = model["sz"].inverse_transform(model["m"].predict(model["sx"].transform(mlp_X(s, model["cfg"]["tf"]))))
    return (50 * np.sinh(z) if model["cfg"]["tf"] == "asinh" else 100 * z) + model["corr"]


def mlp_predict(models: list[dict], s: dict) -> np.ndarray:
    return np.mean([mlp_predict_one(m, s) for m in models], 0)


def dp_ppu(b, prices, ppu: float) -> list[int]:
    """dp.dp_schedule with the end-shortfall penalty per unit given (its scenario mean) instead of read off prices."""
    n, cap, acts = b.n, b.cap, action_order(b)
    v = np.repeat((-np.maximum(0, b.s_end_min - np.arange(n + 1)) * ppu)[:, None], cap + 1, 1)
    policy = np.empty((len(prices), n + 1, cap + 1), dtype=np.int8)
    q = np.empty((len(acts), n + 1, cap + 1))
    for h in range(len(prices) - 1, -1, -1):
        q.fill(-np.inf)
        for i, a in enumerate(acts):
            lo, hi, da = max(0, a), min(n, n + a), max(a, 0)
            if lo <= hi and da <= cap:
                q[i, lo:hi + 1, :cap + 1 - da] = cash(b, prices[h], a)[1] + v[lo - a:hi - a + 1, da:]
        pick = np.argmax(q >= q.max(axis=0) - 1e-7, axis=0)
        policy[h] = pick
        v = np.take_along_axis(q, pick[None], 0)[0]
    s, d, out = b.s0, 0, []
    for h in range(len(prices)):
        a = acts[policy[h, s, d]]
        out.append(a)
        s, d = s - a, d + max(a, 0)
    return out


def _plan(args) -> tuple[float, float, float]:
    i, f, ppu = args
    t = TASKS[i]
    b = battery_of(t)
    sched = dp_schedule(b, [float(x) for x in f]) if ppu is None else dp_ppu(b, f, ppu)
    g = grade(t, sched, "blind")
    return g["r_opt"], capture(g["profit"], g), g["profit"]


def capture(p: float, g: dict) -> float:
    """Raw hindsight capture x = (P - P_idle) / (P_opt - P_idle)."""
    return (p - g["profit_idle"]) / (g["profit_opt"] - g["profit_idle"])


def plan(pool, idx, F, ppu=None) -> np.ndarray:
    """[n, 3] (C, raw capture x, profit) of the DP plan on each forecast row, graded on the realized day."""
    ppu = [None] * len(idx) if ppu is None else ppu
    return np.array(pool.map(_plan, list(zip(idx, F, ppu, strict=True)), chunksize=64))


def scenarios(F: np.ndarray, tasks: list[dict], pool_dates, pool_res, key: str, exclude_same_day: bool):
    """Scenario-mean prices and the scenario-mean penalty per unit for each task (N_SCEN residual day-vectors)."""
    pm = np.array([dt.date.fromisoformat(d).month for d in pool_dates])
    mean, ppu = [], []
    for f, t in zip(F, tasks, strict=True):
        m = dt.date.fromisoformat(t["date"]).month
        ok = np.minimum((pm - m) % 12, (m - pm) % 12) <= 1
        if exclude_same_day:
            ok &= pool_dates != t["date"]
        cand = np.flatnonzero(ok)
        pick = np.random.default_rng(stable_seed(f"{t['task_id']}|{key}")).choice(cand, N_SCEN, replace=False)
        sc = f[None] + pool_res[pick]
        b = battery_of(t)
        mean.append(sc.mean(0))
        ppu.append(float(np.mean([b.q / b.eta * max(x.max(), P_FLOOR) for x in sc])))
    return np.array(mean), ppu


def err(F: np.ndarray, Y: np.ndarray) -> dict:
    """MAE / RMSE over all hours and over each day's 4 dearest and 4 cheapest realized hours."""
    o = np.argsort(Y, 1)
    out = {}
    for name, m in (("all", np.ones_like(Y, bool)), ("dear4", np.zeros_like(Y, bool)),
                    ("cheap4", np.zeros_like(Y, bool))):
        if name != "all":
            np.put_along_axis(m, o[:, -4:] if name == "dear4" else o[:, :4], True, 1)
        e = (F - Y)[m]
        out[name] = {"mae": round(float(np.abs(e).mean()), 3), "rmse": round(float(np.sqrt((e ** 2).mean())), 3)}
    return out


def unique_days(s: dict) -> np.ndarray:
    _, i = np.unique(np.char.add(s["date"], s["point"].astype(str)), return_index=True)
    return np.sort(i)


def boot(dates, v, seed: int = 0) -> dict:
    """Mean and day-block 95% CI (every task of a drawn day, task-weighted)."""
    days, inv = np.unique(dates, return_inverse=True)
    s, c = np.bincount(inv, v), np.bincount(inv)
    idx = np.random.default_rng(seed).integers(0, len(days), (BOOT, len(days)))
    m = s[idx].sum(1) / c[idx].sum(1)
    return {"mean": round(float(np.mean(v)), 4), "ci": [round(float(x), 4) for x in np.percentile(m, [2.5, 97.5])]}


def ens(F: dict, w, members=MEMBERS) -> np.ndarray:
    return sum(wi * F[k] for wi, k in zip(w, members, strict=True))


def simplex(step: float = 0.1, n: int = len(MEMBERS)):
    k = round(1 / step)
    for c in itertools.product(range(k + 1), repeat=n - 1):
        if sum(c) <= k:
            yield tuple(round(x * step, 2) for x in (*c, k - sum(c)))


def tune(work: Path, pool, dam, tr, hold_tasks, hidx):
    fit, val = sub(tr, tr["date"] < HOLDOUT), sub(tr, tr["date"] >= HOLDOUT)
    hs = task_samples(hold_tasks, dam)
    log(f"train rows {len(tr['date'])}: fit {len(fit['date'])}, 2024 val {len(val['date'])}; holdout tasks {len(hidx)}")
    out = {"n_fit": len(fit["date"]), "n_val": len(val["date"]), "n_holdout_tasks": len(hidx),
           "n_holdout_days": len(set(t["date"] for t in hold_tasks))}
    FV, FH = {"persist": val["P7"][:, -1]}, {"persist": hs["P7"][:, -1]}
    rows = [(d, POINTS[p], P7, y) for d, p, P7, y in zip(fit["date"], fit["point"], fit["P7"], fit["y"], strict=True)]
    ridge = ridge_fit([(r[0], r[2][-1], r[2], r[3]) for r in rows], 1e4)
    FV["ridge"], FH["ridge"] = ridge_predict(val, ridge["coef"]), ridge_predict(hs, ridge["coef"])
    out["lgb"] = []
    best = None
    for cfg in LGB_GRID:
        m = lgb_fit(fit, cfg, ROUNDS[-1])
        c, it, fh = rounds_by_c(pool, hidx, m, hs, cfg)
        fv = lgb_predict(m, val, cfg, it=it)
        row = dict(cfg=cfg, best_iter=it, holdout_c=round(float(c[it]), 4), holdout_c_by_rounds=c,
                   val_err=err(fv, val["y"]))
        out["lgb"].append(row)
        log(f"lgb {cfg} rounds {it} val MAE {row['val_err']['all']['mae']} holdout C {c}")
        if best is None or c[it] > best[0]:
            best, FV["lgb"], FH["lgb"] = (c[it], row), fv, fh
            m.save_model(str(work / "lgb_pre2024.txt"), num_iteration=it)
    out["lgb_best"] = best[1]
    with mp.get_context("spawn").Pool(16) as mpool:
        models = mpool.map(mlp_fit_one, [(core(fit), cfg, sd) for cfg in MLP_GRID for sd in MLP_SEEDS])
    out["mlp"], best = [], None
    for i, cfg in enumerate(MLP_GRID):
        ms = models[i * len(MLP_SEEDS):(i + 1) * len(MLP_SEEDS)]
        fv, fh = mlp_predict(ms, val), mlp_predict(ms, hs)
        c = plan(pool, hidx, fh)[:, 0].mean()
        row = dict(cfg=cfg, iters=[m["m"].n_iter_ for m in ms], holdout_c=round(float(c), 4), val_err=err(fv, val["y"]))
        out["mlp"].append(row)
        log(f"mlp {cfg} holdout C {c:.4f} val MAE {row['val_err']['all']['mae']}")
        if best is None or c > best[0]:
            best, FV["mlp"], FH["mlp"] = (c, row), fv, fh
    out["mlp_best"] = best[1]
    grid = list(simplex())
    res = plan(pool, np.tile(hidx, len(grid)), np.concatenate([ens(FH, w) for w in grid]))[:, 0]
    cs = res.reshape(len(grid), len(hidx)).mean(1)
    w = grid[int(np.argmax(cs))]
    out["ens_weights"] = dict(zip(MEMBERS, w, strict=True))
    out["ens_grid_top"] = [{"w": grid[i], "c": round(float(cs[i]), 4)} for i in np.argsort(-cs)[:10]]
    FV["ens"], FH["ens"] = ens(FV, w), ens(FH, w)
    log(f"ensemble weights {out['ens_weights']} holdout C {cs.max():.4f}")
    pools = {k: val["y"] - FV[k] for k in ("persist", "ridge", "lgb", "mlp", "ens")}
    out["holdout"], out["holdout_err"] = {}, {}
    hu = unique_days(hs)
    for k in ("persist", "ridge", "lgb", "mlp", "ens"):
        out["holdout_err"][k] = err(FH[k][hu], hs["y"][hu])
        r = plan(pool, hidx, FH[k])
        out["holdout"][f"{k}_point"] = {"c": round(float(r[:, 0].mean()), 4), "x": round(float(r[:, 1].mean()), 4)}
        if k != "persist":
            mean, ppu = scenarios(FH[k], hold_tasks, val["date"], pools[k], k, True)
            r = plan(pool, hidx, mean, ppu)
            out["holdout"][f"{k}_scen"] = {"c": round(float(r[:, 0].mean()), 4), "x": round(float(r[:, 1].mean()), 4)}
        log(f"holdout {k}: {out['holdout'].get(f'{k}_point')} {out['holdout'].get(f'{k}_scen')}")
    a = np.array([t["refs"]["blind"]["r_opt_anchor"] for t in hold_tasks])
    out["holdout"]["anchor_v1_insample"] = {"c": round(float(a.mean()), 4)}
    cands = {k: v["c"] for k, v in out["holdout"].items() if k.split("_")[0] in ("ridge", "lgb", "mlp", "ens")}
    out["best_method"] = max(cands, key=cands.get)
    log(f"best information-matched method on the 2024 holdout: {out['best_method']} C {cands[out['best_method']]}")
    ext = lgb_fit(fit, best_cfg(out), ROUNDS[-1], extended=True)
    c, it, fh = rounds_by_c(pool, hidx, ext, hs, best_cfg(out), extended=True)
    r = plan(pool, hidx, fh)
    out["holdout"]["lgb_ext_point"] = {"c": round(float(r[:, 0].mean()), 4), "x": round(float(r[:, 1].mean()), 4),
                                       "best_iter": it, "holdout_c_by_rounds": c, "exploratory": True}
    out["holdout_err"]["lgb_ext"] = err(fh[hu], hs["y"][hu])
    log(f"holdout lgb extended (exploratory): {out['holdout']['lgb_ext_point']}")
    (work / "tune.json").write_text(json.dumps(out, indent=1) + "\n")
    np.savez(work / "pools.npz", dates=val["date"], **{f"res_{k}": v for k, v in pools.items()},
             **{f"fv_{k}": v for k, v in FV.items()})


def ridge_predict(s: dict, coef) -> np.ndarray:
    x = np.stack([ridge_features(d, P7[-1], P7) for d, P7 in zip(s["date"], s["P7"], strict=True)])
    return np.einsum("nhf,hf->nh", x, np.asarray(coef))


def rounds_by_c(pool, hidx, model, hs: dict, cfg: dict, extended: bool = False, rounds=ROUNDS):
    """Holdout C at each checkpoint; the best checkpoint and its holdout forecasts."""
    fs = {k: lgb_predict(model, hs, cfg, extended, it=k) for k in rounds}
    c = {k: round(float(plan(pool, hidx, f)[:, 0].mean()), 4) for k, f in fs.items()}
    it = max(c, key=c.get)
    return c, it, fs[it]


def best_cfg(t: dict) -> dict:
    return t["lgb_best"]["cfg"]


def sol_schedules(name: str) -> dict:
    if name == "eval2025":
        out = {}
        for d in ("v1-board-sol-blind", "v1-board-sol-blind-amend"):
            for f in glob.glob(str(ROOT / "results" / "runs" / d / "*.json")):
                e = json.loads(Path(f).read_text())
                out[e["task_id"]] = e["final_schedule"]
        return out
    with gzip.open(ROOT / "results" / "fresh" / "2026-10-blind" / "eval_sol.jsonl.gz", "rt") as f:
        rows = [json.loads(line) for line in f]
    return {r["task_id"]: r["actions"] for r in rows}


def final(work: Path, pool, dam, tr, sets: dict):
    t = json.loads((work / "tune.json").read_text())
    pz = np.load(work / "pools.npz")
    cfg = best_cfg(t)
    log(f"refit lgb {cfg} for {t['lgb_best']['best_iter']} rounds on {len(tr['date'])} rows")
    lgbm = lgb_fit(tr, cfg, t["lgb_best"]["best_iter"])
    ext = lgb_fit(tr, cfg, t["holdout"]["lgb_ext_point"]["best_iter"], extended=True)
    with mp.get_context("spawn").Pool(len(MLP_SEEDS)) as mpool:
        mlps = mpool.map(mlp_fit_one, [(core(tr), t["mlp_best"]["cfg"], sd) for sd in MLP_SEEDS])
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())["coef"]
    w = [t["ens_weights"][k] for k in MEMBERS]
    out = {"tune": {k: t[k] for k in ("lgb_best", "mlp_best", "ens_weights", "best_method", "holdout", "holdout_err",
                                      "n_fit", "n_val", "n_holdout_tasks", "n_holdout_days")}, "packs": {}}
    per_task = {}
    for name, (tasks, idx) in sets.items():
        s = task_samples(tasks, dam)
        F = {"persist": s["P7"][:, -1], "ridge": ridge_predict(s, ridge), "lgb": lgb_predict(lgbm, s, cfg),
             "mlp": mlp_predict(mlps, s)}
        F["ens"] = ens(F, w)
        F["lgb_ext"] = lgb_predict(ext, s, cfg, extended=True)
        res = {}
        for k in ("persist", "ridge", "lgb", "mlp", "ens", "lgb_ext"):
            res[f"{k}_point"] = plan(pool, idx, F[k])
            if k in ("ridge", "lgb", "mlp", "ens"):
                mean, ppu = scenarios(F[k], tasks, pz["dates"], pz[f"res_{k}"], k, False)
                res[f"{k}_scen"] = plan(pool, idx, mean, ppu)
        pk, per_task[name] = score_pack(name, tasks, s, res, F)
        stored = np.array([[tk["refs"]["blind"]["p_persist"], tk["refs"]["blind"]["p_ridge"]] for tk in tasks])
        pk["check_stored_refs_max_abs_diff_usd"] = {
            "persist": round(float(np.abs(res["persist_point"][:, 2] - stored[:, 0]).max()), 6),
            "ridge": round(float(np.abs(res["ridge_point"][:, 2] - stored[:, 1]).max()), 6)}
        out["packs"][name] = pk
    out["verdict"] = verdict(out["packs"], t["best_method"])
    (work / "final.json").write_text(json.dumps(out, indent=1) + "\n")
    with gzip.open(work / "per_task.json.gz", "wt") as f:
        json.dump(per_task, f)


def extend(work: Path, pool, dam, tr, hold: list[dict], hidx, sets: dict):
    """Amendment 1: Huber LightGBM with recency weights and lower round checkpoints, m7-DP, a 5-member ensemble."""
    t = json.loads((work / "tune.json").read_text())
    fit, hs = sub(tr, tr["date"] < HOLDOUT), task_samples(hold, dam)
    ridge_pre = ridge_fit([(d, P7[-1], P7, y) for d, P7, y in zip(fit["date"], fit["P7"], fit["y"], strict=True)], 1e4)
    FH = {"persist": hs["P7"][:, -1], "m7": hs["P7"].mean(1), "ridge": ridge_predict(hs, ridge_pre["coef"])}
    out, best = {"lgb": []}, None
    for cfg in EXT_GRID:
        m = lgb_fit(fit, cfg, ROUNDS[-1])
        c, it, fh = rounds_by_c(pool, hidx, m, hs, cfg, rounds=EXT_ROUNDS)
        out["lgb"].append({"cfg": cfg, "best_iter": it, "holdout_c": c[it], "holdout_c_by_rounds": c})
        log(f"ext lgb {cfg} rounds {it} holdout C {c[it]}")
        if best is None or c[it] > best[0]:
            best, FH["lgb"] = (c[it], out["lgb"][-1]), fh
    out["lgb_best"] = best[1]
    with mp.get_context("spawn").Pool(len(MLP_SEEDS)) as mpool:
        FH["mlp"] = mlp_predict(mpool.map(mlp_fit_one, [(core(fit), t["mlp_best"]["cfg"], sd) for sd in MLP_SEEDS]), hs)
    grid = list(simplex(0.1, len(EXT_MEMBERS)))
    cs = plan(pool, np.tile(hidx, len(grid)), np.concatenate([ens(FH, w, EXT_MEMBERS) for w in grid]))[:, 0]
    cs = cs.reshape(len(grid), len(hidx)).mean(1)
    w = grid[int(np.argmax(cs))]
    out["ens_weights"] = dict(zip(EXT_MEMBERS, w, strict=True))
    out["ens_grid_top"] = [{"w": grid[i], "c": round(float(cs[i]), 4)} for i in np.argsort(-cs)[:10]]
    FH["ens"] = ens(FH, w, EXT_MEMBERS)
    hu = unique_days(hs)
    out["holdout"] = {k: {"c": round(float(r[:, 0].mean()), 4), "x": round(float(r[:, 1].mean()), 4)}
                      for k, r in ((k, plan(pool, hidx, f)) for k, f in FH.items())}
    out["holdout_err"] = {k: err(f[hu], hs["y"][hu]) for k, f in FH.items()}
    out["best_method"] = max(out["holdout"], key=lambda k: out["holdout"][k]["c"])
    log(f"ext holdout {out['holdout']}; ensemble {out['ens_weights']}; best {out['best_method']}")
    cfg = out["lgb_best"]["cfg"]
    lgbm = lgb_fit(tr, cfg, out["lgb_best"]["best_iter"])
    with mp.get_context("spawn").Pool(len(MLP_SEEDS)) as mpool:
        mlps = mpool.map(mlp_fit_one, [(core(tr), t["mlp_best"]["cfg"], sd) for sd in MLP_SEEDS])
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())["coef"]
    out["packs"], per_task = {}, {}
    for name, (tasks, idx) in sets.items():
        s = task_samples(tasks, dam)
        F = {"persist": s["P7"][:, -1], "m7": s["P7"].mean(1), "ridge": ridge_predict(s, ridge),
             "lgb": lgb_predict(lgbm, s, cfg), "mlp": mlp_predict(mlps, s)}
        F["ens"] = ens(F, w, EXT_MEMBERS)
        res = {k: plan(pool, idx, f) for k, f in F.items()}
        out["packs"][name], per_task[name] = score_pack(name, tasks, s, res, F)
    out["verdict"] = verdict(out["packs"], out["best_method"])
    (work / "extend.json").write_text(json.dumps(out, indent=1) + "\n")
    with gzip.open(work / "per_task_extend.json.gz", "wt") as f:
        json.dump(per_task, f)


def score_pack(name: str, tasks: list[dict], s: dict, res: dict, F: dict) -> tuple[dict, dict]:
    """C and x with day-block CIs, paired gaps to Sol and the anchor, and forecast error, for one pack."""
    sol = sol_schedules(name)
    sg = [grade(tk, sol[tk["task_id"]], "blind") for tk in tasks]
    res = dict(res, sol=np.array([[g["r_opt"], capture(g["profit"], g), g["profit"]] for g in sg]),
               anchor=np.array([[tk["refs"]["blind"]["r_opt_anchor"], capture(tk["refs"]["blind"]["p_anchor"], g),
                                 tk["refs"]["blind"]["p_anchor"]] for tk, g in zip(tasks, sg, strict=True)]))
    dates, u = s["date"], unique_days(s)
    pk = {"n_tasks": len(tasks), "n_days": len(set(dates)), "n_point_days": len(u),
          "forecast_err": {k: err(F[k][u], s["y"][u]) for k in F}, "methods": {}}
    for k, r in res.items():
        row = {"c": boot(dates, r[:, 0]), "x": boot(dates, r[:, 1])}
        if k != "sol":
            d = r[:, 2] - res["sol"][:, 2]
            row |= {"gap_sol_c": boot(dates, r[:, 0] - res["sol"][:, 0]),
                    "gap_sol_x": boot(dates, r[:, 1] - res["sol"][:, 1]),
                    "beats_sol": round(float((d > 1e-6).mean()), 4),
                    "ties_sol": round(float((abs(d) <= 1e-6).mean()), 4),
                    "beats_sol_days": int(sum(np.mean(r[dates == x, 0]) > np.mean(res["sol"][dates == x, 0])
                                              for x in set(dates)))}
        if k != "anchor":
            row["gap_anchor_c"] = boot(dates, r[:, 0] - res["anchor"][:, 0])
        pk["methods"][k] = row
        log(f"{name} {k}: C {row['c']} vs Sol {row.get('gap_sol_c')}")
    return pk, {"task_id": [tk["task_id"] for tk in tasks], "date": list(dates),
                **{k: np.round(v, 6).tolist() for k, v in res.items()}}


def verdict(packs: dict, best: str) -> dict:
    """The pre-registered decision rule for the holdout-chosen method."""
    ev, fr = packs["eval2025"]["methods"][best], packs["fresh"]["methods"][best]
    c1 = ev["gap_sol_c"]["ci"][0] > 0
    c2 = fr["gap_sol_c"]["mean"] >= -0.01 and fr["gap_sol_c"]["ci"][1] >= 0
    out = {"best_method": best, "eval2025_gap_sol_c": ev["gap_sol_c"], "fresh_gap_sol_c": fr["gap_sol_c"],
           "criterion_1_eval2025_ci_above_0": c1, "criterion_2_fresh_no_worse": c2, "headroom": bool(c1 and c2)}
    log(f"verdict {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("tune", "final", "extend"))
    ap.add_argument("--work", default=str(ROOT / "results" / "blind-ceiling" / "runs"))
    a = ap.parse_args()
    work = Path(a.work)
    work.mkdir(parents=True, exist_ok=True)
    dam = load_dam()
    tr = train_samples(dam)
    log(f"dam point-days {len(dam)}; training targets {len(tr['date'])} ({min(tr['date'])}..{max(tr['date'])})")
    hold = [t for t in load_pack("ercot-dam-v1-train") if t["date"] >= HOLDOUT and t["tags"].get("blind_eval")]
    sets = {k: [t for t in load_pack(v) if t["tags"].get("blind_eval")] for k, v in PACKS.items()}
    TASKS.extend(hold)
    hidx = np.arange(len(hold))
    off, idx = len(TASKS), {}
    for k, v in sets.items():
        TASKS.extend(v)
        idx[k] = np.arange(off, off + len(v))
        off += len(v)
    with mp.get_context("fork").Pool(NT) as pool:
        if a.stage == "tune":
            tune(work, pool, dam, tr, hold, hidx)
        elif a.stage == "final":
            final(work, pool, dam, tr, {k: (sets[k], idx[k]) for k in sets})
        else:
            extend(work, pool, dam, tr, hold, hidx, {k: (sets[k], idx[k]) for k in sets})
    log("done")


if __name__ == "__main__":
    main()
