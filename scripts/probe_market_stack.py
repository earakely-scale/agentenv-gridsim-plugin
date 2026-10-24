"""v5 feasibility probe: fit a 2-parameter EIA merit order (thermal availability alpha_D, implied gas price g_D) to the
real HB_HUBAVG DAM, make the replay exact with a per-hour residual eps_h, and measure a QSE battery's price impact and
best-response value on the calibrated curve. The modelled-stack prior in CONTRACT-v5; no pack uses it (V5-P1).

Inputs under --cache/raw: eia860/eia8602025.zip, eia923/f923_2025.zip (eia.gov/electricity/data/eia923/xls/),
eia930/Region_TEX.xlsx (eia.gov/electricity/gridmonitor/knownissues/xls/), ercot/DAMLZHBSPP_*.zip (cached NP4-180-ER).
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import numpy as np
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_pack as v1  # noqa: E402

THERMAL = {"Natural Gas Fired Combined Cycle": "cc", "Natural Gas Fired Combustion Turbine": "ct",
           "Natural Gas Internal Combustion Engine": "ic", "Natural Gas Steam Turbine": "st",
           "Conventional Steam Coal": "coal", "Petroleum Liquids": "ic", "Other Gases": "st",
           "Natural Gas with Compressed Air Storage": "ct", "Petroleum Coke": "coal"}
PM_CLASS = {"CT": "cc", "CA": "cc", "CS": "cc", "GT": "ct", "IC": "ic", "ST": "st"}
COAL_FUELS = {"BIT", "SUB", "LIG", "RC", "WC"}
VOM = {"cc": 3.0, "ct": 5.0, "ic": 6.0, "st": 4.0, "coal": 4.5}
HR_DEFAULT = {"cc": 7.2, "ct": 10.5, "ic": 9.5, "st": 11.5, "coal": 10.8}
HR_BOUNDS = {"cc": (6.2, 9.5), "ct": (8.5, 14.0), "ic": (8.0, 13.0), "st": (9.0, 16.0), "coal": (9.5, 13.5)}
COAL_FUEL = 2.0
SEG = np.array([0.90, 0.97, 1.03, 1.10])
SEG_W = np.array([0.40, 0.25, 0.20, 0.15])
TAIL_AMP, TAIL_TAU_GW, EMERGENCY_MW = 3000.0, 2.0, 1000.0
MUST_LO, MUST_HI = -25.0, -1.0
HCAP, FLOOR = 5000.0, -250.0
ALPHAS = np.round(np.arange(0.50, 1.0001, 0.02), 3)
GAS = np.exp(np.linspace(np.log(0.6), np.log(12.0), 50))
SIZES = (400, 800, 1500)
NS_PRICE = 100.0


def sheet_rows(book: bytes, sheet: str, key: str):
    """Data rows of a sheet as dicts, the header being the first row (of the first 10) that contains `key`."""
    wb = openpyxl.load_workbook(io.BytesIO(book), read_only=True, data_only=True)
    rows = wb[sheet].iter_rows(values_only=True)
    for _ in range(10):
        head = [str(h).replace("\n", " ").strip() if h is not None else "" for h in next(rows)]
        if key in head:
            break
    for r in rows:
        yield dict(zip(head, r, strict=False))


def num(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_fleet(raw: Path) -> list[dict]:
    z860 = zipfile.ZipFile(raw / "eia860" / "eia8602025.zip")
    erco = {int(r["Plant Code"]) for r in sheet_rows(z860.read("2___Plant_Y2025.xlsx"), "Plant", "Plant Code")
            if r.get("Balancing Authority Code") == "ERCO" and num(r.get("Plant Code"))}
    z923 = zipfile.ZipFile(raw / "eia923" / "f923_2025.zip")
    name = next(n for n in z923.namelist() if n.startswith("EIA923_Schedules_2_3_4_5"))
    fuel, gen = {}, {}
    for r in sheet_rows(z923.read(name), "Page 1 Generation and Fuel Data", "Plant Id"):
        pid, pm = num(r.get("Plant Id")), r.get("Reported Prime Mover")
        if pid is None or int(pid) not in erco or pm not in PM_CLASS:
            continue
        cls = PM_CLASS[pm]
        if cls == "st" and r.get("Reported Fuel Type Code") in COAL_FUELS:
            cls = "coal"
        k = (int(pid), cls)
        fuel[k] = fuel.get(k, 0.0) + (num(r.get("Elec Fuel Consumption MMBtu")) or 0.0)
        gen[k] = gen.get(k, 0.0) + (num(r.get("Net Generation (Megawatthours)")) or 0.0)
    book = z860.read("3_1_Generator_Y2025.xlsx")
    units = []
    for sheet in ("Operable", "Retired and Canceled"):
        for r in sheet_rows(book, sheet, "Plant Code"):
            pid, cls = num(r.get("Plant Code")), THERMAL.get(r.get("Technology"))
            cap = num(r.get("Summer Capacity (MW)"))
            if pid is None or int(pid) not in erco or cls is None or not cap or cap <= 0:
                continue
            ret = num(r.get("Retirement Year"))
            if sheet != "Operable" and (ret is None or ret < 2022):
                continue
            g = gen.get((int(pid), cls), 0.0)
            hr = fuel.get((int(pid), cls), 0.0) / g if g > 0 else None
            lo, hi = HR_BOUNDS[cls]
            ok = hr is not None and lo <= hr <= hi
            minl = min(max(num(r.get("Minimum Load (MW)")) or 0.0, 0.0), cap) if cls in ("cc", "coal") else 0.0
            units.append({"cls": cls, "cap_s": cap, "cap_w": num(r.get("Winter Capacity (MW)")) or cap, "minl": minl,
                          "hr": hr if ok else HR_DEFAULT[cls], "hr_source": "eia923" if ok else "class_default",
                          "from_year": int(num(r.get("Operating Year")) or 1900), "to_year": int(ret) if ret else None})
    return units


def load_tex(raw: Path) -> dict:
    book = (raw / "eia930" / "Region_TEX.xlsx").read_bytes()
    cols = {"df": "Demand forecast", "ti": "Total interchange", "wnd": "NG: WND", "sun": "NG: SUN", "nuc": "NG: NUC",
            "wat": "NG: WAT", "oth": "NG: OTH", "bat": "NG: BAT"}
    days: dict[str, dict] = {}
    for r in sheet_rows(book, "Published Hourly Data", "Demand forecast"):
        d, h = r.get("Local date"), num(r.get("Hour"))
        if not isinstance(d, dt.datetime) or h is None or d.year < 2022:
            continue
        days.setdefault(d.date().isoformat(), {})[int(h)] = {k: num(r.get(c)) for k, c in cols.items()}
    out = {}
    for d, hours in days.items():
        if sorted(hours) != list(range(1, 25)) or any(hours[h]["df"] is None or hours[h]["df"] <= 0 for h in hours):
            continue
        a = {k: np.array([hours[h][k] or 0.0 for h in range(1, 25)]) for k in cols}
        out[d] = {"df": a["df"], "must": a["wnd"] + a["sun"] + a["nuc"] + a["wat"] + a["oth"] + a["bat"] - a["ti"]}
    return out


def live_units(units: list[dict], date: str) -> dict:
    y, summer = int(date[:4]), 5 <= int(date[5:7]) <= 10
    u = [x for x in units if x["from_year"] <= y and (x["to_year"] is None or x["to_year"] > y)]
    return {"cap": np.array([x["cap_s"] if summer else x["cap_w"] for x in u]),
            "minl": np.array([x["minl"] for x in u]), "hr": np.array([x["hr"] for x in u]),
            "vom": np.array([VOM[x["cls"]] for x in u]), "coal": np.array([x["cls"] == "coal" for x in u])}


def curve(fl: dict, gas: float, alpha: float, must: float) -> tuple[np.ndarray, np.ndarray]:
    """Breakpoints (x = thermal residual MW, price) of the continuous, strictly increasing background inverse supply."""
    mc = fl["hr"] * np.where(fl["coal"], COAL_FUEL, gas) + fl["vom"]
    cap, ml = fl["cap"] * alpha, np.minimum(fl["minl"], fl["cap"]) * alpha
    price, mw = (mc[:, None] * SEG).ravel(), ((cap - ml)[:, None] * SEG_W).ravel()
    o = np.argsort(price, kind="stable")
    price, mw = price[o][mw[o] > 0], mw[o][mw[o] > 0]
    xs = np.concatenate([[-max(must, 1000.0), 0.0, ml.sum()], ml.sum() + np.cumsum(mw)])
    ps = np.maximum.accumulate(np.concatenate([[MUST_LO, MUST_HI, price[0]], price]))
    total = xs[-1]
    fine = np.unique(np.concatenate([xs, np.linspace(max(0.0, total - 15000.0), total, 301)]))
    pf = np.interp(fine, xs, ps) + TAIL_AMP * np.exp(-np.maximum(total - fine, 0) / 1000.0 / TAIL_TAU_GW)
    pf = np.minimum(np.maximum.accumulate(pf), HCAP - 1.0)
    fine, pf = np.append(fine, total + EMERGENCY_MW), np.append(pf, HCAP)
    return fine, pf + np.arange(len(pf)) * 1e-7


def price_at(c, x):
    xs, ps = c
    return np.where(x > xs[-1], HCAP, np.where(x < xs[0], FLOOR, np.interp(x, xs, ps)))


def x_at(c, p):
    xs, ps = c
    return float(np.interp(min(max(p, ps[0]), ps[-1]), ps, xs))


def fit_day(fl: dict, inp: dict, real: np.ndarray):
    resid, must_med = inp["df"] - inp["must"], float(np.median(np.maximum(inp["must"], 1000.0)))
    best = (np.inf, 1.0, 3.0)
    for g in GAS:
        for a in ALPHAS:
            err = float(np.abs(price_at(curve(fl, g, a, must_med), resid) - real).sum())
            if err < best[0]:
                best = (err, a, g)
    _, a, g = best
    curves = [curve(fl, g, a, float(inp["must"][h])) for h in range(24)]
    return a, g, resid, curves, np.array([float(price_at(curves[h], resid[h])) for h in range(24)])


def dp(stage, n: int, acts: list[int], s0: int) -> tuple[float, list[int]]:
    v, pol = np.zeros(n + 1), []
    for h in range(23, -1, -1):
        q = np.full((len(acts), n + 1), -np.inf)
        for i, a in enumerate(acts):
            lo, hi = max(0, a), min(n, n + a)
            if lo <= hi:
                q[i, lo:hi + 1] = stage(h, a) + v[lo - a:hi - a + 1]
        pol.append(q.argmax(0))
        v = q.max(0)
    s, out = s0, []
    for p in pol[::-1]:
        out.append(acts[p[s]])
        s -= out[-1]
    return float(v[s0]), out


def within(p, real):
    return np.abs(p - real) <= np.maximum(5.0, 0.10 * np.abs(real))


def probe_day(d: str, fl: dict, inp: dict, real: np.ndarray) -> dict:
    a, g, resid, curves, p = fit_day(fl, inp, real)
    eps = np.array([x_at(curves[h], real[h]) - resid[h] for h in range(24)])
    x0 = resid + eps
    pc = lambda h, x: float(price_at(curves[h], x))  # noqa: E731
    ns = real < NS_PRICE
    row = {"date": d, "alpha": a, "gas": g, "mae": float(np.abs(p - real).mean()),
           "mae_ns": float(np.abs(p - real)[ns].mean()) if ns.any() else None,
           "within_ns": float(within(p, real)[ns].mean()) if ns.any() else None, "ns_hours": int(ns.sum()),
           "eps_abs_mw": float(np.abs(eps).mean()), "eps_share_df": float((np.abs(eps) / inp["df"]).mean()),
           "replay_err": max(abs(pc(h, x0[h]) - real[h]) for h in range(24))}
    avail = inp["must"] + np.array([c[0][-1] - EMERGENCY_MW for c in curves]) - eps
    for size in SIZES:
        row[f"impact_h_{size}"] = int(sum(pc(h, x0[h]) - pc(h, x0[h] - size) >= 5.0 for h in range(24)))
        rsi = (avail - size) / inp["df"]
        row[f"rsi_min_{size}"], row[f"pivotal_h_{size}"] = float(rsi.min()), int((rsi < 1).sum())
        row |= battery_values(pc, x0, real, size)
    return row


def battery_values(pc, x0, real, size: int, eta: float = 0.85) -> dict:
    """A 2 h battery on a P/20 grid: price-maker BR on the calibrated curve vs a price-taker DP on the real prices."""
    unit, acts, memo = size / 20, list(range(-20, 21)), {}

    def mw(a: int) -> float:
        return a * unit if a > 0 else a * unit / eta

    def maker(h: int, a: int) -> float:
        if (h, a) not in memo:
            memo[(h, a)] = mw(a) * pc(h, x0[h] - mw(a))
        return memo[(h, a)]

    v_pt, s_pt = dp(lambda h, a: mw(a) * real[h], 40, acts, 20)
    return {f"br_{size}": dp(maker, 40, acts, 20)[0], f"pt_plan_{size}": v_pt,
            f"pt_settled_{size}": sum(maker(h, a) for h, a in enumerate(s_pt))}


def summary(rows: list[dict]) -> dict:
    col = lambda k: np.array([r[k] for r in rows if r[k] is not None], float)  # noqa: E731
    out = {"days": len(rows), "within_ns": col("within_ns").mean(), "mae_ns_usd": col("mae_ns").mean(),
           "days_within_ns_ge_0.9": (col("within_ns") >= 0.9).mean(),
           "days_within_ns_ge_0.5": (col("within_ns") >= 0.5).mean(),
           "eps_abs_mw": col("eps_abs_mw").mean(), "eps_share_df": col("eps_share_df").mean(),
           "survive_filter": np.mean([(r["within_ns"] or 0) >= 0.5 and r["eps_share_df"] <= 0.15 for r in rows]),
           "replay_exact": (col("replay_err") <= 0.01).mean(), "alpha_median": np.median(col("alpha")),
           "gas_median": np.median(col("gas"))}
    for s in SIZES:
        br, pts, ptp = col(f"br_{s}"), col(f"pt_settled_{s}"), col(f"pt_plan_{s}")
        out |= {f"pivotal_days_{s}": (col(f"pivotal_h_{s}") > 0).mean(),
                f"rsi_min_p05_{s}": np.quantile(col(f"rsi_min_{s}"), 0.05),
                f"impact_ge2h_{s}": (col(f"impact_h_{s}") >= 2).mean(),
                f"impact_hours_{s}": col(f"impact_h_{s}").mean(), f"br_usd_per_mw_day_{s}": np.median(br / s),
                f"price_taker_overstates_{s}": np.median((ptp - pts) / ptp),
                f"br_over_price_taker_{s}": np.median((br - pts) / br)}
    return {k: round(float(v), 4) for k, v in out.items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=ROOT / "cache")
    ap.add_argument("--days", type=int, default=330)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--start", default="2023-01-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()
    t0 = time.time()
    raw = args.cache / "raw"
    units = load_fleet(raw)
    tex = load_tex(raw)
    dam, _ = v1.load_dam(raw / "ercot", args.cache / "parsed", 4)
    hub = {d: p for (d, pt), p in dam.items() if pt == "HB_HUBAVG"}
    pool = sorted(d for d in hub if args.start <= d <= args.end and d in tex)
    days = sorted(np.random.default_rng(args.seed).choice(pool, min(args.days, len(pool)), replace=False))
    rows = [probe_day(d, live_units(units, d), tex[d], np.asarray(hub[d], float)) for d in days]
    res = {"all": summary(rows)} | {y: summary([r for r in rows if r["date"][:4] == y])
                                    for y in sorted({r["date"][:4] for r in rows})}
    res["fleet"] = {c: {"units": sum(u["cls"] == c and u["to_year"] is None for u in units),
                        "summer_mw": round(sum(u["cap_s"] for u in units if u["cls"] == c and u["to_year"] is None)),
                        "hr_eia923": round(np.mean([u["hr_source"] == "eia923" for u in units if u["cls"] == c]), 3)}
                    for c in VOM}
    res["seconds"] = round(time.time() - t0)
    print(json.dumps(res, indent=1))
    if args.out:
        args.out.write_text(json.dumps({"summary": res, "days": rows}, indent=1))


if __name__ == "__main__":
    main()
