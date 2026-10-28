"""The desk price forecast desk-qr-v1 (CONTRACT-desk 1.4 `desk_forecast`, docs/desk-data.md "Desk price forecast"):
P10/P50/P90 for the site's node DAM SPP (one vintage per operating day, issued D-1 06:00) and hourly RT SPP (hourly
vintages from D-1 06:00, each to the end of the operating day), labelled modelled.

Members follow the v1 teacher ensemble (results/train/4b-blind/scripts/teacher.py on main): P50 = 0.1 ridge + 0.5
LightGBM + 0.4 MLP; P10/P90 from LightGBM quantile models; all in asinh($/50) space, pooled over the desk nodes with the
node as a categorical. New over v1: node prices and ERCOT's as-issued load/wind/solar forecast vintages (the v4 forecast
store) as features, and an RT model by horizon.

Only data public at the issue time t enters a sample: DAM prices of days posted by t (D-1 13:30), RT SPP of hours ended
by t, the latest ERCOT vintage issued <= t. Models are refitted per operating month M on samples whose targets are
revealed before M-01 00:00 CPT (expanding window from 2024-01-08), so every vintage a task sees is out of sample.
Pinball loss is scored on every day of each refit month (all four nodes), against the core NaiveForecaster rule.

Writes $DESK_RAW/forecast/vintages/<node>_<d0>.json.gz (read by desk_data_build) and data/desk/forecast/report.json."""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_data_api as A  # noqa: E402
from desk_data_build import PACKS, SITES, STORE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "desk" / "forecast"
VDIR = A.RAW / "forecast" / "vintages"
HIST = A.RAW / "history"
MODEL = "desk-qr-v1"
CPT = "America/Chicago"
T0 = pd.Timestamp("2024-01-08", tz=CPT)
QS = (0.1, 0.5, 0.9)
W = {"ridge": 0.1, "lgb": 0.5, "mlp": 0.4}
LGB = {"learning_rate": 0.05, "num_leaves": 63, "min_data_in_leaf": 50, "feature_fraction": 0.8,
       "bagging_fraction": 0.8, "bagging_freq": 1, "lambda_l2": 1.0, "verbose": -1, "num_threads": 12}
ROUNDS = 400
RT_EVERY_H = 3
S = 50.0
START = time.time()


def log(m):
    print(f"[{time.time() - START:6.0f}s] {m}", flush=True)


def tf(x):
    return np.arcsinh(np.asarray(x, float) / S)


def itf(y):
    return np.sinh(np.asarray(y, float)) * S


# ---------------------------------------------------------------- hourly UTC timelines

def utc_index(dates, hours, dst):
    local = pd.to_datetime(pd.Series(dates)) + pd.to_timedelta(np.asarray(hours) - 1, unit="h")
    loc = local.dt.tz_localize(CPT, ambiguous=~np.asarray(dst, bool), nonexistent="shift_forward")
    return loc.dt.tz_convert("UTC").dt.floor("h")


def hourly(point: str):
    d = pd.read_parquet(HIST / f"dam_{point}.parquet")
    dam = pd.Series(d["price"].to_numpy(), index=utc_index(d["date"], d["he"], d["dst"]))
    r = pd.read_parquet(HIST / f"rt_{point}.parquet")
    idx = utc_index(r["date"], r["hour"], r["dst"])
    rt = pd.Series(r["price"].to_numpy(), index=idx).groupby(level=0).mean()
    return dam[~dam.index.duplicated()], rt


def ercot_vintages():
    parts = []
    for y in (2023, 2024, 2025, 2026):
        p = STORE / "vintages" / f"{y}.parquet"
        if p.exists():
            parts.append(pd.read_parquet(p, filters=[("kind", "in", ["ercot_load", "ercot_wind", "ercot_solar"]),
                                                     ("key", "=", "system"),
                                                     ("field", "in", ["mw", "stwpf_mw", "stppf_mw"])]))
    v = pd.concat(parts, ignore_index=True)
    out = {}
    for k in ("ercot_load", "ercot_wind", "ercot_solar"):
        x = v[v["kind"] == k].copy()
        x["issued"] = pd.to_datetime(x["issued_at_utc"], utc=True)
        x["start"] = pd.to_datetime(x["start_utc"], utc=True)
        x = x.sort_values("issued").drop_duplicates("issued", keep="last")
        vals = np.stack([np.pad(np.asarray(a, float)[:72], (0, max(0, 72 - len(a))), constant_values=np.nan)
                         for a in x["values"]])
        out[k] = (x["issued"].dt.tz_convert(None).to_numpy(), x["start"].dt.tz_convert(None).to_numpy(), vals)
    return out


def ercot_at(EV, kind, t, T):
    iss, st, vals = EV[kind]
    t = pd.DatetimeIndex(t).tz_convert(None).to_numpy()
    T = pd.DatetimeIndex(T).tz_convert(None).to_numpy()
    i = np.searchsorted(iss, t, side="right") - 1
    ok = i >= 0
    i = np.clip(i, 0, len(iss) - 1)
    h = ((T - st[i]) / np.timedelta64(1, "h")).astype(int)
    good = ok & (h >= 0) & (h < 72)
    out = np.full(len(i), np.nan)
    out[good] = vals[i[good], h[good]]
    return out


# ---------------------------------------------------------------- samples

class Node:
    def __init__(self, k: int, point: str, hub: str):
        self.k, self.point = k, point
        self.dam, self.rt = hourly(point)
        self.hub_dam, _ = hourly(hub)
        grid = pd.date_range(min(self.dam.index.min(), self.rt.index.min()), max(self.dam.index.max(),
                                                                                    self.rt.index.max()),
                             freq="h", tz="UTC")
        self.grid = grid
        self.D = self.dam.reindex(grid).to_numpy()
        self.R = self.rt.reindex(grid).to_numpy()
        self.H = self.hub_dam.reindex(grid).to_numpy()
        loc = grid.tz_convert(CPT)
        day0 = loc.normalize()
        self.dam_post = (day0 - pd.Timedelta(days=1) + pd.Timedelta(hours=13, minutes=30)).tz_convert("UTC")
        self.i0 = grid[0]

    def ix(self, T):
        return ((pd.DatetimeIndex(T) - self.i0) / pd.Timedelta(hours=1)).astype(int).to_numpy()

    def get(self, arr, idx):
        out = np.full(len(idx), np.nan)
        ok = (idx >= 0) & (idx < len(arr))
        out[ok] = arr[idx[ok]]
        return out


def features(nd: Node, EV, t: pd.DatetimeIndex, T: pd.DatetimeIndex, market: str) -> pd.DataFrame:
    iT, it = nd.ix(T), nd.ix(t.floor("h"))
    Tl = T.tz_convert(CPT)
    posted_T = nd.dam_post[np.clip(iT, 0, len(nd.dam_post) - 1)] <= t
    dam_T = np.where(posted_T, nd.get(nd.D, iT), np.nan)
    f = {"node": np.full(len(T), nd.k), "hour": Tl.hour, "dow": Tl.day_of_week, "month": Tl.month,
         "horizon": np.asarray((T - t.floor("h")) / pd.Timedelta(hours=1)), "dam_known": posted_T.astype(float),
         "dam_T": tf(dam_T), "dam_m24": tf(nd.get(nd.D, iT - 24)), "dam_m168": tf(nd.get(nd.D, iT - 168)),
         "hub_m24": tf(nd.get(nd.H, iT - 24))}
    last_rt = np.stack([nd.get(nd.R, it - k) for k in range(1, 25)])
    f["rt_last"] = tf(last_rt[0])
    f["rt_l24_mean"] = tf(np.nanmean(last_rt, axis=0))
    f["rt_l24_max"] = tf(np.nanmax(last_rt, axis=0))
    f["rt_l24_min"] = tf(np.nanmin(last_rt, axis=0))
    f["rt_dev_last"] = f["rt_last"] - tf(nd.get(nd.D, it - 1))
    rt_m24 = nd.get(nd.R, iT - 24)
    f["rt_m24"] = tf(np.where(iT - 24 < it, rt_m24, np.nan))
    ld, wd, sl = (ercot_at(EV, k, t, T) for k in ("ercot_load", "ercot_wind", "ercot_solar"))
    f["load_f"], f["wind_f"], f["solar_f"] = ld / 1e4, wd / 1e4, sl / 1e4
    f["net_f"] = (ld - wd - sl) / 1e4
    df = pd.DataFrame(f)
    day = Tl.normalize()
    g = pd.Series(df["net_f"].to_numpy()).groupby([np.asarray(t), np.asarray(day)])
    df["net_f_daymax"] = g.transform("max").to_numpy()
    df["net_f_daymin"] = g.transform("min").to_numpy()
    if market == "dam":
        df = df.drop(columns=["horizon", "dam_known", "dam_T"])
    return df


def samples_for_day(nd: Node, EV, d: pd.Timestamp, market: str, rt_every: int = 1, span: int = 1):
    """d: first operating day (CPT midnight); span: operating days in the window. Returns (t, T, X, y) for the DAM
    vintage of d or the RT vintages issued hourly (every rt_every h) from d-1 06:00 to the window's last hour."""
    d = d.tz_localize(CPT) if d.tzinfo is None else d
    end = (d + pd.Timedelta(days=span)).tz_convert("UTC")
    if market == "dam":
        t0 = (d - pd.Timedelta(hours=18)).tz_convert("UTC")
        T = pd.date_range(d.tz_convert("UTC"), (d + pd.Timedelta(days=1)).tz_convert("UTC"), freq="h",
                          inclusive="left")
        t = pd.DatetimeIndex([t0] * len(T))
    else:
        issues = pd.date_range((d - pd.Timedelta(hours=18)).tz_convert("UTC"), end - pd.Timedelta(hours=1),
                               freq=f"{rt_every}h")
        ts, Ts = [], []
        for t0 in issues:
            T = pd.date_range(t0.floor("h"), end, freq="h", inclusive="left")
            ts += [t0] * len(T)
            Ts += list(T)
        t, T = pd.DatetimeIndex(ts), pd.DatetimeIndex(Ts)
    X = features(nd, EV, t, T, market)
    y = nd.get(nd.D if market == "dam" else nd.R, nd.ix(T))
    return t, T, X, y


def build_set(nodes, EV, days, market, rt_every, span: int = 1):
    parts = []
    days = list(days)
    for nd in nodes:
        for d in days:
            t, T, X, y = samples_for_day(nd, EV, d, market, rt_every, span)
            X = X.assign(_y=y, _t=t, _T=T, _day=d.date())
            parts.append(X)
    df = pd.concat(parts, ignore_index=True)
    return df[np.isfinite(df["_y"])]


# ---------------------------------------------------------------- models

def fill(X: pd.DataFrame) -> np.ndarray:
    Z = X.copy()
    if "dam_T" in Z:
        Z["dam_T"] = Z["dam_T"].fillna(Z["dam_m24"])
    Z["rt_m24"] = Z["rt_m24"].fillna(Z["dam_m24"])
    Z = Z.fillna(Z.median(numeric_only=True)).fillna(0.0)
    oh = pd.get_dummies(Z["hour"].astype(int), prefix="h").reindex(columns=[f"h_{i}" for i in range(24)],
                                                                     fill_value=0)
    on = pd.get_dummies(Z["node"].astype(int), prefix="n").reindex(columns=[f"n_{i}" for i in range(len(SITES))],
                                                                     fill_value=0)
    return np.hstack([Z.drop(columns=["hour", "node"]).to_numpy(float), oh.to_numpy(float), on.to_numpy(float)])


class QR:
    def fit(self, X: pd.DataFrame, y: np.ndarray, seed: int = 0):
        yt = tf(y)
        self.cols = list(X.columns)
        self.lgb = {}
        for q in QS:
            ds = lgb.Dataset(X, yt, categorical_feature=["node"], free_raw_data=False)
            self.lgb[q] = lgb.train({**LGB, "objective": "quantile", "alpha": q, "seed": seed}, ds, ROUNDS)
        F = fill(X)
        self.sc = StandardScaler().fit(F)
        Fs = self.sc.transform(F)
        self.ridge = Ridge(alpha=10.0).fit(Fs, yt)
        rng = np.random.default_rng(seed)
        sub = rng.choice(len(yt), min(len(yt), 150_000), replace=False)
        self.mlp = MLPRegressor(hidden_layer_sizes=(64, 32), alpha=1e-3, learning_rate_init=1e-3, max_iter=60,
                                early_stopping=True, random_state=seed).fit(Fs[sub], yt[sub])
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        Fs = self.sc.transform(fill(X))
        lg = {q: m.predict(X[self.cols]) for q, m in self.lgb.items()}
        p50 = W["ridge"] * self.ridge.predict(Fs) + W["lgb"] * lg[0.5] + W["mlp"] * self.mlp.predict(Fs)
        out = np.sort(np.stack([lg[0.1], p50, lg[0.9]], axis=1), axis=1)
        return itf(out)


def pinball(y, P):
    out = {}
    for j, q in enumerate(QS):
        e = y - P[:, j]
        out[f"q{int(q * 100)}"] = float(np.mean(np.maximum(q * e, (q - 1) * e)))
    out["mean"] = float(np.mean(list(out.values())))
    out["cover_80"] = float(np.mean((y >= P[:, 0]) & (y <= P[:, 2])))
    out["mae_p50"] = float(np.mean(np.abs(y - P[:, 1])))
    return out


def naive(nd: Node, df: pd.DataFrame, market: str) -> np.ndarray:
    """CONTRACT-desk 8.4 NaiveForecaster on the same samples: P50 = latest posted DAM day by hour (RT: the target
    hour's DAM once posted); band = +- the hour's mean absolute deviation over the posted history days (min $5)."""
    t, T = pd.DatetimeIndex(df["_t"]), pd.DatetimeIndex(df["_T"])
    iT = nd.ix(T)
    posted = nd.dam_post[np.clip(iT, 0, len(nd.dam_post) - 1)] <= t
    lag = np.where(posted, 0, 24)
    lag = np.where(nd.dam_post[np.clip(iT - lag, 0, len(nd.dam_post) - 1)] <= t, lag, lag + 24)
    p50 = nd.get(nd.D, iT - lag)
    hist = np.stack([nd.get(nd.D, iT - lag - 24 * k) for k in range(1, 8)])
    band = np.maximum(np.nanmean(np.abs(hist - p50), axis=0), 5.0)
    return np.stack([p50 - band, p50, p50 + band], axis=1)


# ---------------------------------------------------------------- main

def months_needed():
    ms = set()
    for spec in PACKS.values():
        for d0, _ in spec["tasks"]:
            ms.add(d0[:7])
    for m in pd.period_range("2025-12", "2026-08", freq="M"):
        ms.add(str(m))
    return sorted(ms | {str(pd.Period(m, "M") - 1) for m in ms})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", nargs="*")
    ap.add_argument("--packs", nargs="*", help="write vintages only for these packs' tasks")
    a = ap.parse_args()
    EV = ercot_vintages()
    log("ERCOT vintages loaded")
    nodes = []
    for k, s in enumerate(SITES.values()):
        reg = pd.read_parquet(ROOT / "data" / "desk" / "sites.parquet").set_index("resource_name")
        nodes.append(Node(k, reg.loc[s["resource"], "settlement_point"], s["hub"]))
    log("node timelines ready")
    by_point = {nd.point: nd for nd in nodes}
    task_days = {}
    for name, spec in PACKS.items():
        if a.packs and name not in a.packs:
            continue
        for d0, sid in spec["tasks"]:
            task_days.setdefault(d0[:7], set()).add((d0, sid))
    VDIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    rp = OUT / "report.json"
    report = json.loads(rp.read_text()) if rp.exists() else {"model": MODEL, "months": {}}
    reg = pd.read_parquet(ROOT / "data" / "desk" / "sites.parquet").set_index("resource_name")
    months = a.months or months_needed()
    first_test = pd.Timestamp(f"{months[0]}-01", tz=CPT)
    last_day = pd.Timestamp("2026-08-31", tz=CPT)
    full = {mk: build_set(nodes, EV, pd.date_range(T0, last_day, freq="D"), mk, RT_EVERY_H) for mk in ("dam", "rt")}
    log(f"training pools: dam {len(full['dam'])}, rt {len(full['rt'])}")
    tests = {mk: build_set(nodes, EV, [d for d in pd.date_range(first_test, last_day, freq="D")
                                       if d.strftime("%Y-%m") in months], mk, 1).reset_index(drop=True)
             for mk in ("dam", "rt")}
    log(f"test pools: dam {len(tests['dam'])}, rt {len(tests['rt'])}")
    prev: dict = {}
    for m in months:
        m0 = pd.Timestamp(f"{m}-01", tz=CPT)
        pm = str(pd.Period(m, "M") - 1)
        rec = {"train": [str(T0.date()), str((m0 - pd.Timedelta(days=1)).date())], "test_month": m}
        for market in ("dam", "rt"):
            tr = full[market]
            tr = tr[pd.DatetimeIndex(tr["_T"]) + pd.Timedelta(hours=1) <= m0.tz_convert("UTC")]
            cols = [c for c in tr.columns if not c.startswith("_")]
            model = QR().fit(tr[cols], tr["_y"].to_numpy())
            te = tests[market]
            te = te[pd.DatetimeIndex(te["_day"].astype(str)).strftime("%Y-%m") == m].reset_index(drop=True)
            y = te["_y"].to_numpy()
            P_raw = model.predict(te[cols])
            kb = band_scale(*prev[(pm, market)]) if (pm, market) in prev else (1.0, 1.0)
            P = widen(P_raw, kb)
            prev[(m, market)] = (y, P_raw)
            nv = np.full_like(P, np.nan)
            for k, g in te.groupby("node"):
                nv[g.index] = naive(nodes[int(k)], g, market)
            ok = np.isfinite(nv).all(axis=1)
            rec[market] = {"n_train": int(len(tr)), "n_test": int(len(te)), "model": pinball(y, P),
                           "band_scale": [round(kb[0], 3), round(kb[1], 3)], "band_from": pm if kb != (1.0, 1.0)
                           else None, "model_raw_band": pinball(y, P_raw),
                           "naive": pinball(y[ok], nv[ok]), "model_on_naive_rows": pinball(y[ok], P[ok]),
                           "by_node": {nodes[int(k)].point: pinball(g["_y"].to_numpy(), P[g.index])
                                       for k, g in te.groupby("node")}}
            log(f"{m} {market}: train {len(tr)} test {len(te)} pinball {rec[market]['model']['mean']:.2f} "
                f"vs naive {rec[market]['naive']['mean']:.2f}; cover80 {rec[market]['model']['cover_80']:.2f}")
            for d0, sid in sorted(task_days.get(m, ())):
                point = reg.loc[SITES[sid]["resource"], "settlement_point"]
                nd = by_point[point]
                d = pd.Timestamp(d0, tz=CPT)
                t, T, X, _ = samples_for_day(nd, EV, d, market, 1)
                Pd = widen(model.predict(X[cols]), kb)
                vin = write_vintages(t, T, Pd, market)
                p = VDIR / f"{point}_{d0}.json.gz"
                old = json.loads(gzip.decompress(p.read_bytes())) if p.exists() else []
                old = [v for v in old if v["market"] != market] + vin
                p.write_bytes(gzip.compress(json.dumps(old).encode(), mtime=0))
        report["months"][m] = rec
        report.update({"model": MODEL, "quantiles": list(QS), "weights": W, "lgb": LGB, "rounds": ROUNDS,
                       "rt_train_issue_every_h": RT_EVERY_H, "transform": f"asinh(x/{S})",
                       "label": "modelled desk forecast"})
        rp.write_text(json.dumps(report, indent=1))
    summarize(report)
    rp.write_text(json.dumps(report, indent=1))


def band_scale(y, P):
    """Split-conformal band widths from the previous month's out-of-sample errors (targets revealed before M-01)."""
    lo = (P[:, 1] - y) / np.maximum(P[:, 1] - P[:, 0], 0.5)
    hi = (y - P[:, 1]) / np.maximum(P[:, 2] - P[:, 1], 0.5)
    return (float(np.clip(np.quantile(lo, 0.9), 0.7, 4.0)), float(np.clip(np.quantile(hi, 0.9), 0.7, 4.0)))


def widen(P, k):
    out = P.copy()
    out[:, 0] = P[:, 1] - k[0] * (P[:, 1] - P[:, 0])
    out[:, 2] = P[:, 1] + k[1] * (P[:, 2] - P[:, 1])
    return out


def write_vintages(t, T, P, market):
    out = []
    for t0 in sorted(set(t)):
        sel = np.asarray(t == t0)
        Ts = T[sel]
        out.append({"market": market, "issued_at": iso(t0), "start": iso(Ts[0]), "step_min": 60,
                    "p10": [round(float(x), 2) for x in P[sel, 0]], "p50": [round(float(x), 2) for x in P[sel, 1]],
                    "p90": [round(float(x), 2) for x in P[sel, 2]], "model": MODEL})
    return out


def iso(ts):
    x = pd.Timestamp(ts).tz_convert(CPT)
    s = x.strftime("%Y-%m-%dT%H:%M:%S%z")
    return s[:-2] + ":" + s[-2:]


def summarize(report):
    tot = {}
    for market in ("dam", "rt"):
        rows = [(v[market]["n_test"], v[market]["model"], v[market]["naive"]) for k, v in report["months"].items()
                if market in v and "2025-12" <= k <= "2026-08"]
        n = sum(r[0] for r in rows)
        if not n:
            continue
        tot[market] = {"n_test": n, "months": len(rows),
                       "model": {k: round(sum(r[0] * r[1][k] for r in rows) / n, 3) for k in rows[0][1]},
                       "naive": {k: round(sum(r[0] * r[2][k] for r in rows) / n, 3) for k in rows[0][2]}}
    report["held_out_post_rtcb"] = tot


def main_v4(packs: list[str]):
    """v4 windows (CONTRACT-desk 10.2): a DAM vintage for each operating day at its D-1 06:00 and hourly RT vintages
    from D-1 06:00 to D2 23:00 with horizons to D2 24:00, from an RT model trained on 3-day spans (issues every 6 h).
    Bands are widened by the previous month's out-of-sample errors on the same span; scores go to report["v4"]."""
    EV = ercot_vintages()
    reg = pd.read_parquet(ROOT / "data" / "desk" / "sites.parquet").set_index("resource_name")
    nodes = [Node(k, reg.loc[s["resource"], "settlement_point"], s["hub"]) for k, s in enumerate(SITES.values())]
    by_point = {nd.point: nd for nd in nodes}
    tasks = [(d0, sid) for name in packs for d0, sid in PACKS[name]["tasks"]]
    months = sorted({d0[:7] for d0, _ in tasks})
    last_day = pd.Timestamp("2026-08-31", tz=CPT)
    pool = {"dam": build_set(nodes, EV, pd.date_range(T0, last_day, freq="D"), "dam", 1),
            "rt": build_set(nodes, EV, pd.date_range(T0, last_day - pd.Timedelta(days=2), freq="D"), "rt", 6, 3)}
    log(f"v4 pools: dam {len(pool['dam'])}, rt {len(pool['rt'])}")
    rp = OUT / "report.json"
    report = json.loads(rp.read_text())
    report.setdefault("v4", {})
    for m in months:
        m0 = pd.Timestamp(f"{m}-01", tz=CPT)
        pm0 = m0 - pd.offsets.MonthBegin(1)
        rec = {}
        for market in ("dam", "rt"):
            cols = [c for c in pool[market].columns if not c.startswith("_")]
            T = pd.DatetimeIndex(pool[market]["_T"])
            day = pd.DatetimeIndex(pool[market]["_day"].astype(str))
            prev_tr = pool[market][T + pd.Timedelta(hours=1) <= pm0.tz_convert("UTC")]
            a0, a1 = pm0.tz_localize(None), (m0 - pd.Timedelta(days=3)).tz_localize(None)
            prev_te = pool[market][(day >= a0) & (day <= a1)]
            mp = QR().fit(prev_tr[cols], prev_tr["_y"].to_numpy())
            kb = band_scale(prev_te["_y"].to_numpy(), mp.predict(prev_te[cols]))
            tr = pool[market][T + pd.Timedelta(hours=1) <= m0.tz_convert("UTC")]
            model = QR().fit(tr[cols], tr["_y"].to_numpy())
            b0, b1 = m0.tz_localize(None), (m0 + pd.offsets.MonthBegin(1)).tz_localize(None)
            te = pool[market][(day >= b0) & (day < b1)]
            P = widen(model.predict(te[cols]), kb)
            rec[market] = {"n_train": int(len(tr)), "n_test": int(len(te)), "band_scale": [round(x, 3) for x in kb],
                           "model": pinball(te["_y"].to_numpy(), P)}
            mm = rec[market]["model"]
            log(f"v4 {m} {market}: pinball {mm['mean']:.2f} cover80 {mm['cover_80']:.2f}")
            for d0, sid in tasks:
                if d0[:7] != m:
                    continue
                nd = by_point[reg.loc[SITES[sid]["resource"], "settlement_point"]]
                d = pd.Timestamp(d0, tz=CPT)
                p = VDIR / f"{nd.point}_{d0}_3d.json.gz"
                old = json.loads(gzip.decompress(p.read_bytes())) if p.exists() else []
                old = [v for v in old if v["market"] != market]
                if market == "dam":
                    for k in range(3):
                        t, Tt, X, _ = samples_for_day(nd, EV, d + pd.Timedelta(days=k), "dam")
                        old += write_vintages(t, Tt, widen(model.predict(X[cols]), kb), "dam")
                else:
                    t, Tt, X, _ = samples_for_day(nd, EV, d, "rt", 1, 3)
                    old += write_vintages(t, Tt, widen(model.predict(X[cols]), kb), "rt")
                p.write_bytes(gzip.compress(json.dumps(old).encode(), mtime=0))
        report["v4"][m] = rec
        report["v4_method"] = "dam as v2 at each day's D-1 06:00; rt trained on 3-day spans, issues every 6 h"
        rp.write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    if "--v4" in sys.argv:
        main_v4([a for a in sys.argv[sys.argv.index("--v4") + 1:]])
    else:
        main()
