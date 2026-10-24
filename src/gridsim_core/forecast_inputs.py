"""v4 forecast inputs: the HRRR points and weather zones, the reveal table, vintage hashing, the window's vintage slice
(inline in the row, or read from the forecast store) and a deterministic synthetic slice for tests and fixtures before
the store exists. docs/CONTRACT-v4.md fixes the shapes."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from gridsim_core import hybrid_inputs
from gridsim_core.hybrid import pv_at_bus
from gridsim_core.task import data_root, stable_seed

try:
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    pa = pq = None

TZ_NAME = "America/Chicago"
HRRR_ISSUE_MIN = 120
HRRR_CYCLES = (0, 6, 12, 18)
HORIZON_H = 72
WEATHER_HORIZON_H = 48
DF_REVEAL_MIN = 360
DA_REVEAL_MIN = 810
LOAD_SHARES = {"COAS": 0.2, "EAST": 0.05, "FWES": 0.08, "NCEN": 0.3, "NRTH": 0.03, "SCEN": 0.17, "SOUT": 0.09,
               "WEST": 0.08}
SOURCES = ("desk", "ercot", "synthetic")
DESK_KINDS = {"load": ("load", "mw"), "wind": ("wind", "mw"), "solar": ("solar", "mw")}
ERCOT_KINDS = {"load": ("ercot_load", "mw"), "wind": ("ercot_wind", "stwpf_mw"), "solar": ("ercot_solar", "stppf_mw")}


@lru_cache(maxsize=1)
def points_doc() -> dict:
    return json.loads((data_root() / "forecast" / "points.json").read_text())


@lru_cache(maxsize=1)
def reveal_doc() -> dict:
    return json.loads((data_root() / "forecast" / "reveal.json").read_text())


def points() -> dict[str, dict]:
    return {p["id"]: p for p in points_doc()["points"]}


def zones() -> dict[str, dict]:
    """{EIA subregion code: {"name": agent-facing name, "point": weather point id}}."""
    return points_doc()["zones"]


def zone_code(name: str) -> str | None:
    """An agent-facing zone name (COAST, NORTH_C, ...) or an EIA code to the EIA code."""
    z = zones()
    if name in z:
        return name
    return next((c for c, v in z.items() if v["name"] == str(name).upper()), None)


def site_point(settlement_point: str) -> str:
    """The weather point of a settlement point: the v1 airport its label names (approximate, V4-P15)."""
    for p in points_doc()["points"]:
        if p["role"] == "site" and settlement_point in p["label"]:
            return p["id"]
    return "AUS"


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def vintage_sha(fields: dict) -> str:
    return hashlib.sha256(canonical(fields).encode()).hexdigest()


def vintages_sha(series: list[dict]) -> str:
    rows = sorted((v["kind"], v["key"], v["issued_at"], v["sha"]) for v in series)
    return hashlib.sha256(canonical(rows).encode()).hexdigest()


def iso_utc(t: dt.datetime) -> str:
    return t.astimezone(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.UTC)


def vintage(kind: str, key: str, issued_at: str, run_id: str, source: str, start: str, fields: dict) -> dict:
    fields = {k: [round(float(x), 2) for x in v] if isinstance(v, (list, tuple, np.ndarray)) else v
              for k, v in fields.items()}
    return {"kind": kind, "key": key, "issued_at": issued_at, "run_id": run_id, "source": source, "start": start,
            "fields": fields, "sha": vintage_sha(fields)}


# the store (built by the data lane): read the vintages a window can serve


def store_root() -> Path:
    return Path(__file__).resolve().parents[2] / "cache" / "forecast" / "store"


def slice_for(task: dict, store: str | Path | None = None) -> dict:
    """The window's vintages: inline rows return their own; a store reference reads every vintage of the referenced
    kinds and keys issued between 24 h before the open and the window end."""
    v = task.get("vintages") or {}
    if v.get("series") is not None:
        return v
    if pq is None:
        raise RuntimeError("reading the forecast store needs pyarrow")
    root = Path(store or store_root())
    if not (root / "manifest.json").exists():
        raise FileNotFoundError(f"{task['task_id']} reads the forecast store, and {root} has none")
    found = json.loads((root / "manifest.json").read_text()).get("store_sha")
    if v.get("store") and v["store"] != f"v4-store@{found}":
        raise ValueError(f"{task['task_id']} was built on {v['store']}; {root} holds v4-store@{found}")
    lo, hi = parse_utc(v["from"]), parse_utc(v["to"])
    want = {(k, key) for k, keys in v["keys"].items() for key in keys}
    series = []
    for year in range(lo.year, hi.year + 1):
        f = root / "vintages" / f"{year}.parquet"
        if not f.exists():
            continue
        kinds = sorted({k for k, _ in want})
        rows = pq.read_table(f, filters=[("issued_at_utc", ">=", iso_utc(lo)), ("issued_at_utc", "<=", iso_utc(hi)),
                                         ("kind", "in", kinds)]).to_pylist()
        for r in rows:
            t = parse_utc(r["issued_at_utc"])
            if lo <= t <= hi and (r["kind"], r["key"]) in want:
                series.append(r)
    grouped: dict[tuple, dict] = {}
    for r in series:
        g = grouped.setdefault((r["kind"], r["key"], r["issued_at_utc"]), {
            "kind": r["kind"], "key": r["key"], "issued_at": r["issued_at_utc"], "run_id": r["run_id"],
            "source": r.get("source") or "desk", "start": r["start_utc"], "fields": {}})
        g["fields"][r["field"]] = [round(float(x), 2) for x in r["values"]]
    out = []
    for g in grouped.values():
        g["sha"] = vintage_sha(g["fields"])
        out.append(g)
    out += site_vintages(task, out)
    return {"source": v.get("source", "desk"), "store": v.get("store"), "runs": v.get("runs", []),
            "series": sorted(out, key=lambda x: (x["issued_at"], x["kind"], x["key"]))}


def site_vintages(task: dict, series: list[dict]) -> list[dict]:
    """solar/site and ercot_solar/site vintages (field mw) from the system series: cf = MW / the day's installed MW
    (lane D3), then v3's plant at the bus (V4-P17)."""
    d1 = dt.date.fromisoformat(task["d1"])
    base = dt.datetime.combine(d1, dt.time(0), ZoneInfo(TZ_NAME)).astimezone(dt.UTC)
    out = []
    for v in series:
        kind = {"solar": ("solar", "mw"), "ercot_solar": ("ercot_solar", "stppf_mw")}.get(v["kind"])
        if kind is None or v["key"] != "system" or kind[1] not in v["fields"]:
            continue
        h0 = round((parse_utc(v["start"]) - base).total_seconds() / 3600)
        mw = []
        for i, x in enumerate(v["fields"][kind[1]]):
            day = (d1 + dt.timedelta(days=(h0 + i) // 24)).isoformat()
            inst = float((hybrid_inputs.solar_row(day) or {}).get("installed_mw") or task.get("solar_installed_mw")
                         or 1.0)
            mw.append(pv_at_bus(task["site"], [max(0.0, float(x)) / inst])[0])
        out.append(vintage(kind[0], "site", v["issued_at"], v["run_id"], v.get("source") or "desk", v["start"],
                           {"mw": mw}))
    return out


def write_store(series: list[dict], root: str | Path, meta: dict | None = None) -> str:
    """Write vintages in the store layout (vintages/YYYY.parquet one row per field, index.parquet, manifest.json) and
    return the store sha; the data lane's builder writes through this so the reader and the schema cannot drift."""
    if pq is None:
        raise RuntimeError("writing the forecast store needs pyarrow")
    root = Path(root)
    (root / "vintages").mkdir(parents=True, exist_ok=True)
    by_year: dict[int, list[dict]] = {}
    index = []
    for v in sorted(series, key=lambda x: (x["issued_at"], x["kind"], x["key"])):
        sha = vintage_sha(v["fields"])
        if v.get("sha") not in (None, sha):
            raise ValueError(f"{v['kind']} {v['key']} {v['issued_at']}: sha does not match its fields")
        for f, vals in sorted(v["fields"].items()):
            by_year.setdefault(parse_utc(v["issued_at"]).year, []).append({
                "issued_at_utc": v["issued_at"], "run_id": v["run_id"], "kind": v["kind"], "key": v["key"],
                "source": v.get("source") or "desk", "start_utc": v["start"], "field": f,
                "values": [float(x) for x in vals], "sha": sha})
        n = max(len(x) for x in v["fields"].values())
        index.append({"kind": v["kind"], "key": v["key"], "issued_at_utc": v["issued_at"],
                      "reveal_at_utc": v["issued_at"], "run_id": v["run_id"], "start_utc": v["start"], "n_hours": n,
                      "sha": sha})
    for year, rows in by_year.items():
        pq.write_table(pa.Table.from_pylist(rows), root / "vintages" / f"{year}.parquet", compression="zstd")
    pq.write_table(pa.Table.from_pylist(index), root / "index.parquet", compression="zstd")
    store = vintages_sha([{"kind": r["kind"], "key": r["key"], "issued_at": r["issued_at_utc"], "sha": r["sha"]}
                          for r in index])
    (root / "manifest.json").write_text(json.dumps({"store_sha": store, "vintages": len(index),
                                                    "years": sorted(by_year)} | (meta or {}), indent=1) + "\n")
    return store


# a deterministic synthetic slice (tests and fixtures before the store exists; flagged source "synthetic")


def _noisy(rng, truth, rel: float, base: float, growth: float = 0.01):
    sd = (rel * np.abs(truth) + base) * (1 + growth * np.arange(1, len(truth) + 1))
    return truth + rng.normal(0, 1, len(truth)) * sd, sd


def _truth_at(arr, h: int):
    return arr[min(max(h, 0), len(arr) - 1)]


def synthetic_slice(task: dict, days: int | None = None) -> dict:
    """Vintages shaped like the store's: HRRR-timed runs (cycle + 120 min) every 6 h from 24 h before the open to the
    window end, each 72 h of price, MCPC, desk load/wind/solar and 48 h of weather, built as truth plus seeded errors
    that grow with the horizon, plus one EIA DF per operating day at 06:00. Display and test data only."""
    tz = ZoneInfo(TZ_NAME)
    n = days or task["days"]
    d1 = dt.date.fromisoformat(task["d1"])
    t0 = dt.datetime.combine(d1, dt.time(0), tz)
    open_t = t0 - dt.timedelta(hours=14)
    end_t = t0 + dt.timedelta(days=n)
    hours = 24 * n
    da = np.asarray(task["prices"][:hours], dtype=float)
    rt = np.asarray(task["rt"][:hours], dtype=float)
    mcpc = {k: np.asarray(v[:hours], dtype=float) for k, v in (task.get("mcpc_da") or {}).items()}
    cf = np.asarray(task["pv_cf"][:hours], dtype=float)
    act = task.get("actuals") or {}
    hh = np.arange(-48, hours + 96)
    load_truth = np.asarray(act.get("load_mw") or (45000 + 9000 * np.sin((hh % 24 - 9) / 24 * 2 * math.pi)), float)
    wind_truth = 12000 + 6000 * np.cos(hh / 17.0)
    temp_truth = 60 + 15 * np.sin((hh % 24 - 9) / 24 * 2 * math.pi) - 0.1 * hh
    installed = float(task.get("solar_installed_mw") or 25000.0)
    point = task.get("weather_point") or site_point(task["settlement_point"])
    wpts = [point] + [z["point"] for z in zones().values() if z["point"] != point]
    series, runs = [], []
    cyc = dt.datetime.combine(d1 - dt.timedelta(days=3), dt.time(0), dt.UTC)
    while cyc <= end_t:
        issued = cyc + dt.timedelta(minutes=HRRR_ISSUE_MIN)
        if open_t - dt.timedelta(hours=24) <= issued <= end_t:
            run_id = f"{cyc:%Y-%m-%dT%H}Z"
            start = issued.replace(minute=0) + dt.timedelta(hours=1)
            h0 = int((start - t0).total_seconds() // 3600)
            rng = np.random.default_rng(stable_seed(f"{task['task_id']}|{run_id}"))
            idx = [h0 + i for i in range(HORIZON_H)]

            def noisy(truth, rel, base, rng=rng):
                return _noisy(rng, truth, rel, base)

            iso = iso_utc(issued)
            st = iso_utc(start)
            for name, arr, base in (("da", da, 3.0), ("rt", rt, 6.0)):
                p50, sd = noisy(np.array([_truth_at(arr, h) for h in idx]), 0.08, base)
                if name == "da":
                    da50, dasd = p50, sd
                else:
                    rt50, rtsd = p50, sd
            series.append(vintage("price", task["settlement_point"], iso, run_id, "synthetic", st, {
                "da_p10": da50 - 1.2816 * dasd, "da_p50": da50, "da_p90": da50 + 1.2816 * dasd,
                "rt_p10": rt50 - 1.2816 * rtsd, "rt_p50": rt50, "rt_p90": rt50 + 1.2816 * rtsd}))
            for k, arr in mcpc.items():
                p50, sd = noisy(np.array([_truth_at(arr, h) for h in idx]), 0.1, 1.0)
                p50 = np.maximum(p50, 0)
                series.append(vintage("mcpc", k, iso, run_id, "synthetic", st, {
                    "p10": np.maximum(0, p50 - 1.2816 * sd), "p50": p50, "p90": p50 + 1.2816 * sd}))
            cf_f = np.clip(np.array([_truth_at(cf, h) for h in idx]) * (1 + rng.normal(0, 0.06, HORIZON_H)), 0, 1)
            series.append(vintage("solar", "system", iso, run_id, "synthetic", st, {"mw": cf_f * installed}))
            site = task["site"]
            dc = site["pv_mwac"] * site.get("ilr", 1.3) * cf_f
            pv_f = dc if site["coupling"] == "dc" else np.minimum(site["pv_mwac"], dc)
            series.append(vintage("solar", "site", iso, run_id, "synthetic", st, {"mw": np.round(pv_f, 3)}))
            li = [h + 48 for h in idx]
            lf, _ = noisy(np.array([_truth_at(load_truth, i) for i in li]), 0.02, 300.0)
            series.append(vintage("load", "system", iso, run_id, "synthetic", st, {"mw": lf}))
            for code, share in LOAD_SHARES.items():
                series.append(vintage("load", code, iso, run_id, "synthetic", st, {"mw": lf * share}))
            wf, _ = noisy(np.array([_truth_at(wind_truth, i) for i in li]), 0.1, 500.0)
            series.append(vintage("wind", "system", iso, run_id, "synthetic", st, {"mw": np.maximum(wf, 0)}))
            for j, p in enumerate(wpts):
                t2 = np.array([_truth_at(temp_truth, i) for i in li[:WEATHER_HORIZON_H]]) - 2 * j
                series.append(vintage("weather", p, iso, run_id, "synthetic", st, {
                    "t2m_f": t2 + rng.normal(0, 1.5, WEATHER_HORIZON_H),
                    "wind80_ms": np.abs(8 + 3 * rng.normal(0, 1, WEATHER_HORIZON_H)),
                    "dswrf_wm2": np.array([_truth_at(cf, h) for h in idx[:WEATHER_HORIZON_H]]) * 900,
                    "cloud_pct": np.clip(40 + 30 * rng.normal(0, 1, WEATHER_HORIZON_H), 0, 100)}))
            runs.append({"run_id": run_id, "cycle": iso_utc(cyc), "issued_at": iso, "hrrr": "synthetic",
                         "fh_max": 48, "backfilled": False})
        cyc += dt.timedelta(hours=6)
    for k in range(n):
        day0 = t0 + dt.timedelta(days=k)
        issued = day0 + dt.timedelta(minutes=DF_REVEAL_MIN)
        rng = np.random.default_rng(stable_seed(f"{task['task_id']}|df|{k}"))
        truth = np.array([load_truth[48 + 24 * k + h] for h in range(24)])
        series.append(vintage("load_official", "system", iso_utc(issued), f"eia-df-{day0:%Y-%m-%d}", "synthetic",
                              iso_utc(day0), {"mw": truth * (1 + rng.normal(0.01, 0.02))}))
    series.sort(key=lambda v: (v["issued_at"], v["kind"], v["key"]))
    return {"source": "synthetic", "store": None, "runs": runs, "series": series}
