"""The SFT teacher for registered run 4: the blind ceiling check's registered ensemble (0.1 ridge + 0.5 LightGBM + 0.4
MLP, results/blind-ceiling/runs/tune.json), CROSS-FITTED by year. Each 2014-2024 point-day's forecast comes from
members fitted on every other year, so the targets carry the teacher's real out-of-sample error. The eval packs get
the full 2014-2024 fit, as the ceiling check scored it.

PYTHONPATH=src:scripts:results/blind-ceiling/scripts python results/train/4b-blind/scripts/teacher.py OUT.json.gz"""

import gzip
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

import ceiling as cl
import numpy as np

from gridsim_core.baselines import ridge_fit
from gridsim_core.task import load_pack

ROOT = Path(__file__).resolve().parents[4]
TUNE = json.loads((ROOT / "results" / "blind-ceiling" / "runs" / "tune.json").read_text())
LGB_CFG, ROUNDS, MLP_CFG = TUNE["lgb_best"]["cfg"], TUNE["lgb_best"]["best_iter"], TUNE["mlp_best"]["cfg"]
W = {k: TUNE["ens_weights"][k] for k in ("ridge", "lgb", "mlp")}
YEARS = range(2014, 2025)
T0 = time.time()


def log(msg: str):
    print(f"[{time.time() - T0:6.0f}s] {msg}", flush=True)


def members(fit: dict, pred: dict, mlps: list, ridge_coef=None) -> dict:
    coef = ridge_coef if ridge_coef is not None else ridge_fit(
        [(d, P7[-1], P7, y) for d, P7, y in zip(fit["date"], fit["P7"], fit["y"], strict=True)], 1e4)["coef"]
    m = cl.lgb_fit(fit, LGB_CFG, ROUNDS)
    out = {"persist": pred["P7"][:, -1], "ridge": cl.ridge_predict(pred, coef), "lgb": cl.lgb_predict(m, pred, LGB_CFG),
           "mlp": cl.mlp_predict(mlps, pred)}
    out["ens"] = sum(w * out[k] for k, w in W.items())
    return out


def keyed(s: dict, f: np.ndarray) -> dict:
    return {f"{d}|{cl.POINTS[p]}": [round(float(x), 2) for x in row] for d, p, row in zip(s["date"], s["point"], f,
                                                                                         strict=True)}


def main():
    out = Path(sys.argv[1])
    dam = cl.load_dam()
    tr = cl.train_samples(dam)
    year = np.array([int(d[:4]) for d in tr["date"]])
    log(f"training targets {len(tr['date'])} ({min(tr['date'])}..{max(tr['date'])}); lgb {LGB_CFG} x{ROUNDS}; "
        f"mlp {MLP_CFG}; weights {W}")
    jobs = [(cl.core(cl.sub(tr, year != y)), MLP_CFG, sd) for y in YEARS for sd in cl.MLP_SEEDS]
    jobs += [(cl.core(tr), MLP_CFG, sd) for sd in cl.MLP_SEEDS]
    with mp.get_context("spawn").Pool(int(sys.argv[2]) if len(sys.argv) > 2 else 7) as pool:
        fitted = pool.map(cl.mlp_fit_one, jobs, chunksize=1)
    log(f"{len(fitted)} MLPs fitted")
    k = len(cl.MLP_SEEDS)
    cross, diag = {}, {}
    F_all = {m: np.zeros_like(tr["y"]) for m in ("persist", "ridge", "lgb", "mlp", "ens")}
    for i, y in enumerate(YEARS):
        fit, pred = cl.sub(tr, year != y), cl.sub(tr, year == y)
        F = members(fit, pred, fitted[i * k:(i + 1) * k])
        for m, f in F.items():
            F_all[m][year == y] = f
        cross.update(keyed(pred, F["ens"]))
        diag[str(y)] = {"n": int((year == y).sum()), **{m: cl.err(f, pred["y"])["all"]["mae"] for m, f in F.items()}}
        log(f"fold {y}: {diag[str(y)]}")
    diag["all"] = {m: cl.err(f, tr["y"]) for m, f in F_all.items()}
    full = fitted[len(YEARS) * k:]
    ridge = json.loads((ROOT / "data" / "ridge-v1.json").read_text())["coef"]
    evals, packs = {}, {}
    for name, pack in cl.PACKS.items():
        tasks = [t for t in load_pack(pack) if t["tags"].get("blind_eval")]
        s = cl.task_samples(tasks, dam)
        F = members(tr, s, full, ridge)
        evals.update(keyed(s, F["ens"]))
        packs[name] = {"tasks": tasks, "F": F, "s": s}
    hold = [t for t in load_pack("ercot-dam-v1-train") if t["date"] >= "2024-01-01" and t["tags"].get("blind_eval")]
    hs = cl.task_samples(hold, dam)
    packs["holdout2024_crossfit"] = {"tasks": hold, "s": hs, "F": {"ens": np.array(
        [cross[f"{t['date']}|{t['settlement_point']}"] for t in hold]), "persist": hs["P7"][:, -1]}}
    log("full fit done; scoring the eval packs and the cross-fitted 2024 holdout with the DP")
    cl.TASKS.extend(t for v in packs.values() for t in v["tasks"])
    off, check = 0, {}
    with mp.get_context("fork").Pool(8) as pool:
        for name, v in packs.items():
            idx = np.arange(off, off + len(v["tasks"]))
            off += len(v["tasks"])
            r = cl.plan(pool, idx, v["F"]["ens"])
            u = cl.unique_days(v["s"])
            check[name] = {"n": len(idx), "ens_c": round(float(r[:, 0].mean()), 4),
                           "err": {m: cl.err(f[u], v["s"]["y"][u]) for m, f in v["F"].items()}}
            log(f"{name}: ens C {check[name]['ens_c']} (ceiling: eval2025 0.9119, fresh 0.9194, holdout 0.905)")
    meta = {"source": "results/blind-ceiling registered ensemble, cross-fitted by year", "lgb_cfg": LGB_CFG,
            "lgb_rounds": ROUNDS, "mlp_cfg": MLP_CFG, "mlp_seeds": list(cl.MLP_SEEDS), "weights": W,
            "ridge_lambda_crossfit": 1e4, "eval_ridge": "data/ridge-v1.json", "years": list(YEARS),
            "crossfit_mae_by_year": diag, "eval_check": check, "n_crossfit": len(cross), "n_eval": len(evals)}
    with gzip.open(out, "wt") as f:
        json.dump({"meta": meta, "crossfit": cross, "eval": evals}, f)
    log(f"wrote {out}: {len(cross)} cross-fitted + {len(evals)} eval point-days")


if __name__ == "__main__":
    main()
