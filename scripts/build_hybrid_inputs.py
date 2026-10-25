"""Build v3's real-data inputs into data/hybrid/ from cache/raw (run scripts/fetch_hybrid_inputs.py first):
DA AS clearing prices, the hourly solar capacity factor, AS deployment events from lane N's notice archive, the
era-keyed duration table, the regulation-drift fallback and the EIA-860 hybrid archetypes. Writes manifest.json (every
source's sha256, counts) and coverage.md. python scripts/build_hybrid_inputs.py [--workers N]"""

# ruff: noqa: E501
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import math
import re
import statistics
import sys
import zipfile
from pathlib import Path
from zoneinfo import ZoneInfo

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import build_live_pack as live_pack  # noqa: E402

from gridsim_core import hybrid_inputs as hi  # noqa: E402
from gridsim_core.contract import (  # noqa: E402
    AS_DURATION_H,
    AS_DURATION_NOTES,
    AS_ERAS,
    AS_PRODUCTS,
    as_era,
    as_products,
)

RAW = ROOT / "cache" / "raw" / "hybrid"
EIA860 = ROOT / "cache" / "raw" / "eia860" / "eia8602025.zip"
OUT = ROOT / "data" / "hybrid"
NOTICES = ROOT / "data" / "notices"
CPT = ZoneInfo("America/Chicago")
START = dt.date(2021, 1, 1)
COLS = {"REGUP": "regup", "REGDN": "regdn", "RRS": "rrs", "ECRS": "ecrs", "NSPIN": "nspin"}
REPAIR_HUB = "HB_HUBAVG"
REPAIR_WINDOW = 3
CALIB_MONTHS = 6
NEAR_KM = 3.0
DEPLOY_CAP_H = {"rrs": 2.0, "ecrs": 2.0, "nspin": 4.0}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl_gz(p: Path, rows: list[dict]) -> None:
    with gzip.GzipFile(p, "wb", mtime=0) as g:
        g.write("".join(json.dumps(r, separators=(",", ":")) + "\n" for r in rows).encode())


def mdy(s) -> dt.date:
    return s.date() if isinstance(s, dt.datetime) else dt.datetime.strptime(str(s).strip(), "%m/%d/%Y").date()


def fnum(v) -> float | None:
    return None if v in (None, "") else float(v)


# ---- DA AS clearing prices (NP4-181-ER yearly, NP4-188-CD daily tail) ----

def as_prices() -> tuple[list[dict], dict]:
    hours: dict[dt.date, dict] = collections.defaultdict(dict)
    origin: dict[dt.date, str] = {}
    for z in sorted((RAW / "dam_mcpc_yearly").glob("DAMASMCPC_*.zip")):
        zf = zipfile.ZipFile(z)
        name = zf.namelist()[0]
        if name.endswith(".csv"):
            rows = list(csv.reader(io.TextIOWrapper(zf.open(name), encoding="utf-8-sig")))
        else:
            ws = openpyxl.load_workbook(io.BytesIO(zf.read(name)), read_only=True).worksheets[0]
            rows = [r for r in ws.iter_rows(values_only=True) if r and r[0] not in (None, "")][1:]
        head = [str(h).strip().upper() for h in rows[0]]
        for r in rows[1:]:
            d = mdy(r[0])
            if d < START:
                continue
            key = (str(r[1]).strip(), str(r[2]).strip().upper() == "Y")
            hours[d][key] = {COLS[c]: fnum(r[i]) for i, c in enumerate(head) if c in COLS}
            origin[d] = f"NP4-181-ER {z.stem}"
    for z in sorted((RAW / "dam_mcpc_daily").glob("*.zip")):
        zf = zipfile.ZipFile(z)
        for r in csv.DictReader(io.TextIOWrapper(zf.open(zf.namelist()[0]), encoding="utf-8-sig")):
            d = mdy(r["DeliveryDate"])
            if d in origin and origin[d].startswith("NP4-181"):
                continue
            key = (r["HourEnding"].strip(), r["DSTFlag"].strip().upper() == "Y")
            hours[d].setdefault(key, {})[COLS[r["AncillaryType"].strip().upper()]] = float(r["MCPC"])
            origin.setdefault(d, "NP4-188-CD daily")
    out, st = [], collections.Counter()
    for d in sorted(hours):
        keys = sorted(hours[d], key=lambda k: (k[0], k[1]))
        row = {"date": d.isoformat(), "era": as_era(d), "n_hours": len(keys), "source": origin[d]}
        if len(keys) != 24:
            row["hour_ending"] = [k[0] + ("*" if k[1] else "") for k in keys]
            st["dst_days"] += 1
        for p in AS_PRODUCTS:
            vals = [hours[d][k].get(p) for k in keys]
            row[p] = None if p not in as_products(d) or all(v is None for v in vals) else vals
            if p in as_products(d) and (row[p] is None or None in row[p]):
                st[f"missing_{p}"] += 1
        out.append(row)
        st[f"era_{row['era']}"] += 1
    first_ecrs = next(r["date"] for r in out if r["ecrs"])
    return out, {"days": len(out), "first": out[0]["date"], "last": out[-1]["date"], "first_ecrs": first_ecrs,
                 "gaps": missing_dates(out), **st}


def missing_dates(rows: list[dict]) -> list[str]:
    have = {r["date"] for r in rows}
    d, end, gaps = dt.date.fromisoformat(rows[0]["date"]), dt.date.fromisoformat(rows[-1]["date"]), []
    while d <= end:
        if d.isoformat() not in have:
            gaps.append(d.isoformat())
        d += dt.timedelta(days=1)
    return gaps


# ---- solar capacity factor ----

def pg7_solar() -> dict[dt.date, tuple[list[float], list[float]]]:
    """{date: (hourly MW, installed MW)} from PG7-126-M (system-wide ERCOT.PVGR.GEN, 'Total Solar Installed, MW'). The
    sheet's Date column is the hour-ending stamp's calendar date, so HE24 is keyed by (stamp - 1 h)."""
    out: dict[dt.date, tuple[list, list]] = {}
    for p in sorted((RAW / "wind_solar_yearly").glob("*.xlsx")):
        ws = openpyxl.load_workbook(p, read_only=True, data_only=True)["Solar Data"]
        rows = ws.iter_rows(values_only=True)
        head = [str(h).strip() if h else "" for h in next(rows)]
        i_t, i_g = head.index("Time (Hour-Ending)"), head.index("ERCOT.PVGR.GEN")
        i_c = head.index("Total Solar Installed, MW")
        for r in rows:
            if not isinstance(r[i_t], dt.datetime) or r[i_g] is None:
                continue
            g, c = out.setdefault((r[i_t] - dt.timedelta(hours=1)).date(), ([], []))
            g.append(float(r[i_g]))
            c.append(float(r[i_c]))
    return out


def fuel_mix_solar() -> dict[dt.date, list[float]]:
    """{date: hourly MW} from ERCOT's Fuel Mix Report (15-minute MWh per interval, summed per hour), 2021, 2022, 2026."""
    books = {}
    zf = zipfile.ZipFile(RAW / "fuel_mix" / "FuelMixReport_PreviousYears.zip")
    for y in (2021, 2022):
        books[y] = openpyxl.load_workbook(io.BytesIO(zf.read(f"IntGenbyFuel{y}.xlsx")), read_only=True, data_only=True)
    books[2026] = openpyxl.load_workbook(RAW / "fuel_mix" / "IntGenbyFuel2026.xlsx", read_only=True, data_only=True)
    out = {}
    for wb in books.values():
        for ws in wb.worksheets[4:]:
            rows = ws.iter_rows(values_only=True)
            head = next(rows, None)
            if not head:
                continue
            for r in rows:
                if r[1] != "Solar" or not isinstance(r[0], dt.datetime):
                    continue
                v = [float(x) for x in r[4:] if isinstance(x, (int, float))]
                if len(v) % 4 == 0 and len(v) // 4 in (23, 24, 25):
                    out[r[0].date()] = [sum(v[4 * h:4 * h + 4]) for h in range(len(v) // 4)]
    return out


def eia_solar_mw() -> dict[str, float]:
    """{YYYY-MM: operable ERCO PV nameplate MWac at month end} from EIA-860M (Operating and Retired sheets)."""
    wb = openpyxl.load_workbook(RAW / "eia860m" / "september_generator2026.xlsx", read_only=True, data_only=True)
    gens = []
    for sheet in ("Operating", "Retired"):
        rows = list(wb[sheet].iter_rows(values_only=True))
        hi_ = next(i for i, r in enumerate(rows) if r and "Balancing Authority Code" in r)
        head = rows[hi_]
        ix = {k: head.index(k) for k in ("Balancing Authority Code", "Technology", "Nameplate Capacity (MW)",
                                          "Operating Month", "Operating Year")}
        ret = (head.index("Retirement Month"), head.index("Retirement Year")) if sheet == "Retired" else None
        for r in rows[hi_ + 1:]:
            if r[ix["Balancing Authority Code"]] != "ERCO" or r[ix["Technology"]] != "Solar Photovoltaic":
                continue
            on = (int(r[ix["Operating Year"]]), int(r[ix["Operating Month"]]))
            off = (int(r[ret[1]]), int(r[ret[0]])) if ret else None
            gens.append((on, off, float(r[ix["Nameplate Capacity (MW)"]])))
    out, y, m = {}, 2020, 12
    while (y, m) <= (2026, 12):
        out[f"{y}-{m:02d}"] = sum(mw for on, off, mw in gens if on <= (y, m) and (off is None or off > (y, m)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def solar_cf(workers: int) -> tuple[list[dict], dict]:
    log("solar: PG7-126-M")
    pg7 = pg7_solar()
    log("solar: fuel mix")
    fm = fuel_mix_solar()
    eia = eia_solar_mw()
    monthly = collections.defaultdict(list)
    for d, (_, cap) in pg7.items():
        monthly[f"{d:%Y-%m}"].append(statistics.fmean(cap))
    ratios = {k: statistics.fmean(v) / eia[k] for k, v in sorted(monthly.items()) if eia.get(k)}
    keys = sorted(ratios)
    calib = {"before": statistics.median(ratios[k] for k in keys[:CALIB_MONTHS]),
             "after": statistics.median(ratios[k] for k in keys[-CALIB_MONTHS:])}
    log(f"solar: ERCOT/EIA installed ratio {calib}")
    rt = hub_rt(workers)
    days: dict[dt.date, dict] = {}
    for d, (g, cap) in pg7.items():
        if d >= START:
            days[d] = {"mw": g, "installed": cap, "source": "PG7-126-M"}
    for d, g in fm.items():
        if d >= START and d not in days:
            r = calib["before"] if f"{d:%Y-%m}" < keys[0] else calib["after"]
            days[d] = {"mw": g, "installed": [eia[f"{d:%Y-%m}"] * r] * len(g), "source": "fuel-mix+EIA-860M"}
    cf = {d: [min(1.0, max(0.0, x / c)) for x, c in zip(v["mw"], v["installed"], strict=True)] for d, v in days.items()}
    rows, st = [], collections.Counter()
    for d in sorted(days):
        a = cf[d]
        avail, fixed = list(a), []
        neg = rt.get(d)
        if neg is not None and len(a) == 24:
            for h in range(24):
                if neg[h] > 0:
                    continue
                ref = [cf[e][h] for k in range(-REPAIR_WINDOW, REPAIR_WINDOW + 1)
                       if k and (e := d + dt.timedelta(days=k)) in cf and len(cf[e]) == 24
                       and rt.get(e) is not None and rt[e][h] > 0]
                if ref and statistics.median(ref) > a[h] + 1e-4:
                    avail[h] = statistics.median(ref)
                    fixed.append(h)
        st["days"] += 1
        st[f"src_{days[d]['source']}"] += 1
        st["repaired_days"] += bool(fixed)
        st["repaired_hours"] += len(fixed)
        rows.append({"date": d.isoformat(), "n_hours": len(a), "cf": [round(x, 4) for x in avail],
                     "cf_actual": [round(x, 4) for x in a], "repaired_hours": fixed,
                     "installed_mw": round(statistics.fmean(days[d]["installed"]), 1), "source": days[d]["source"],
                     "scope": "system"})
    ex = next(r for r in rows if r["date"] == "2024-03-29")
    h = ex["repaired_hours"]
    example = (f"2024-03-29 HE{h[0] + 1:02d}-HE{h[-1] + 1:02d} cf {min(ex['cf_actual'][i] for i in h)}-"
               f"{max(ex['cf_actual'][i] for i in h)} actual, {min(ex['cf'][i] for i in h)}-{max(ex['cf'][i] for i in h)}"
               " repaired") if h else "2024-03-29 not repaired"
    return rows, {**st, "example": example, "first": rows[0]["date"], "last": rows[-1]["date"], "gaps": missing_dates(rows),
                  "ercot_over_eia_installed": {"used_before_2023": round(calib["before"], 4),
                                               "used_after_2025": round(calib["after"], 4),
                                               "min": round(min(ratios.values()), 4),
                                               "max": round(max(ratios.values()), 4), "months": len(ratios)}}


def hub_rt(workers: int) -> dict[dt.date, list[float]]:
    """Hourly mean RT SPP at REPAIR_HUB from v2's parsed RT cache (non-DST days only)."""
    rt, _ = live_pack.load_rt(ROOT / "cache" / "raw" / "ercot-rt", ROOT / "cache" / "parsed", workers)
    return {dt.date.fromisoformat(d): [float(v[4 * h:4 * h + 4].mean()) for h in range(24)]
            for (d, p), v in rt.items() if p == REPAIR_HUB}


# ---- AS deployments from lane N's archive ----

PRODUCT_RE = (("nspin", re.compile(r"non-?spin|\bnspin\b", re.I)), ("ecrs", re.compile(r"ecrs|contingency reserve", re.I)),
              ("rrs", re.compile(r"responsive reserve|\brrs\b", re.I)), ("ers", re.compile(r"emergency response", re.I)))
MW_TOTAL = re.compile(r"(?:for a total (?:deployment )?of|total of) approximately\s*([\d,]+(?:\.\d+)?)\s*MW", re.I)
MW_LEAVE = re.compile(r"(?:leaving approximate(?:ly|d)|and)\s*([\d,]+(?:\.\d+)?)\s*MW[^.]*?(?:deployed|remains)", re.I)
MW_ANY = re.compile(r"(?:DEPLOY_MW:\s*|approximately\s*|approximated\s*|,\s*|^At \S+\s+)([\d,]+(?:\.\d+)?)\s*(?:MW)?",
                    re.I)
MW_DEPLOY = re.compile(r"DEPLOY_MW:\s*([\d.]+)")
CM_TIMES = re.compile(r"BEGIN_TIME:\s*([\d-]+ [\d:]+),\s*END_TIME:\s*([\d-]+ [\d:]+)")
AT_TIME = re.compile(r"\bAt\s+(\d{1,2}):(\d{2})")


def deployments() -> tuple[list[dict], dict]:
    rows = [json.loads(line) for line in gzip.open(NOTICES / "notices.jsonl.gz", "rt")]
    cov = json.loads((NOTICES / "ops_coverage.json").read_text())["days"]
    tagged = sorted((r for r in rows if "as_deployment" in r.get("tags", ())), key=lambda r: r["issued_at_utc"])
    st = collections.Counter(tagged=len(tagged), ruc=sum("ruc" in r.get("tags", ()) for r in rows))
    cancelled = set()
    for i, r in enumerate(tagged):
        if r["action"] == "cancel":
            body = (r["text"] or "").split("notice:", 1)[-1].strip()[:50]
            orig = next((o for o in reversed(tagged[:i]) if o["action"] != "cancel" and body
                         and (o["text"] or "").startswith(body)), None)
            if orig:
                cancelled.add(orig["notice_id"])
    msgs = []
    for r in tagged:
        if r["action"] == "cancel" or r["notice_id"] in cancelled:
            st["cancel_or_cancelled"] += 1
            continue
        m = parse_deployment(r)
        if m is None:
            st["unparsed"] += 1
            continue
        if m["product"] == "ers":
            st["ers_skipped"] += 1
            continue
        msgs.append(m)
    events = []
    for key in sorted({(m["product"], m["variant"]) for m in msgs}, key=str):
        events += assemble([m for m in msgs if (m["product"], m["variant"]) == key])
    events.sort(key=lambda e: (e["start"], e["product"]))
    for e in events:
        st[f"events_{e['product']}"] += 1
        st[f"end_{e['end_basis']}"] += 1
        st[f"year_{e['start'][:4]}"] += 1
    by_year = collections.defaultdict(list)
    for d, v in cov.items():
        if d >= START.isoformat():
            by_year[d[:4]].append(v)
    return events, {**st, "messages": len(msgs),
                    "archive_coverage_by_year": {y: round(statistics.fmean(v), 3) for y, v in sorted(by_year.items())}}


def parse_deployment(r: dict) -> dict | None:
    text = r["text"] or r["title"] or ""
    low = text.lower()
    if r["type"] in ("EEA1", "EEA2", "EEA3") or "energy emergency alert" in low or "eea level" in low:
        return None
    product = next((p for p, rx in PRODUCT_RE if rx.search(text)), None)
    if product is None:
        return None
    issued = dt.datetime.fromisoformat(r["issued_at_utc"].replace("Z", "+00:00")).astimezone(CPT)
    at = issued
    if (t := AT_TIME.search(text)) and int(t.group(1)) < 24:
        cand = issued.replace(hour=int(t.group(1)), minute=int(t.group(2)), second=0, microsecond=0)
        at = cand if cand <= issued + dt.timedelta(minutes=5) else cand - dt.timedelta(days=1)
    planned_end, mw = None, None
    if cm := CM_TIMES.search(text):
        begin = dt.datetime.strptime(cm.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CPT)
        planned_end = dt.datetime.strptime(cm.group(2), "%Y-%m-%d %H:%M:%S").replace(tzinfo=CPT)
        at = max(begin, issued) if begin > issued else begin
    if d := MW_DEPLOY.search(text):
        mw = float(d.group(1))
    recall = "recall" in low or "has completed" in low or mw == 0.0
    level = None
    if recall:
        if lv := MW_LEAVE.search(text):
            level, recall = float(lv.group(1).replace(",", "")), False
    elif tot := MW_TOTAL.search(text):
        level = float(tot.group(1).replace(",", ""))
    elif mw is not None:
        level = mw
    elif product == "nspin" and (a := re.search(r"approximate(?:ly|d)?\s*([\d,]+(?:\.\d+)?)\s*MW", text, re.I)):
        level = float(a.group(1).replace(",", ""))
    variant = "online" if "onecrs" in low else "offline" if "offecrs" in low else None
    return {"notice_id": r["notice_id"], "summary": r["summary"], "product": product, "variant": variant,
            "kind": "recall" if recall else "deploy", "at": at, "issued": issued, "mw": level, "planned_end": planned_end}


def assemble(msgs: list[dict]) -> list[dict]:
    """Deploy/recall messages of one product into events: a deploy opens (or updates) an event, a full recall closes
    it; an event never recalled ends at its planned END_TIME, the next deploy, or DEPLOY_CAP_H, whichever is first.
    Messages apply in issue order, so a recall drops the hourly re-deployments scheduled after it."""
    out, cur = [], None
    for m in sorted(msgs, key=lambda m: (m["issued"], m["kind"] != "recall")):
        if m["kind"] == "deploy":
            if cur is None:
                cur = {"msgs": [m], "start": m["at"], "steps": [], "planned_end": m["planned_end"]}
            else:
                cur["msgs"].append(m)
                cur["start"] = min(cur["start"], m["at"])
                if m["planned_end"]:
                    cur["planned_end"] = m["planned_end"]
            if m["mw"] is not None:
                cur["steps"].append((m["at"], m["mw"]))
            continue
        if cur is None:
            continue
        cur["msgs"].append(m)
        if m["mw"] is not None:
            cur["steps"].append((m["at"], m["mw"]))
            continue
        out.append(close(cur, m["at"], "recall"))
        cur = None
    if cur is not None:
        out.append(close(cur, None, None))
    return [fix_open(e, out) for e in out]


def close(cur: dict, end: dt.datetime | None, basis: str | None) -> dict:
    first = cur["msgs"][0]
    product = first["product"]
    steps = [{"at": t.isoformat(), "mw": mw} for t, mw in sorted(cur["steps"], key=lambda x: x[0])
             if end is None or t < end]
    mws = [s["mw"] for s in steps]
    what = {"nspin": "Non-Spin", "rrs": "Responsive Reserve", "ecrs": "ECRS"}[product]
    if first["variant"]:
        what += f" ({first['variant']})"
    return {"event_id": f"dep-{product}{'-' + first['variant'] if first['variant'] else ''}-"
                        f"{cur['start']:%Y%m%dT%H%M}",
            "product": product, "variant": first["variant"], "date": cur["start"].date().isoformat(),
            "start": cur["start"].isoformat(), "end": end.isoformat() if end else None, "end_basis": basis,
            "planned_end": cur["planned_end"].isoformat() if cur["planned_end"] else None,
            "mw_max": max(mws) if mws else None, "mw_steps": steps, "frac": None,
            "source_notice_id": first["notice_id"], "notice_ids": [m["notice_id"] for m in cur["msgs"]],
            "summary": f"ERCOT deployed {what}" + (f", up to {max(mws):g} MW system-wide" if mws else "") + "."}


def fix_open(e: dict, events: list[dict]) -> dict:
    if e["end"] is not None:
        return e
    start = dt.datetime.fromisoformat(e["start"])
    nxt = [dt.datetime.fromisoformat(o["start"]) for o in events
           if o["product"] == e["product"] and o["variant"] == e["variant"] and o["start"] > e["start"]]
    cands = [(start + dt.timedelta(hours=DEPLOY_CAP_H[e["product"]]), "cap")]
    if e["planned_end"]:
        cands.append((dt.datetime.fromisoformat(e["planned_end"]), "planned_end"))
    if nxt:
        cands.append((min(nxt), "next_deploy"))
    end, basis = min(cands)
    return {**e, "end": end.isoformat(), "end_basis": basis}


# ---- EIA-860 hybrid archetypes ----

def sheet_rows(zf: zipfile.ZipFile, name: str, sheet: str | None = None) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(zf.read(name)), read_only=True, data_only=True)
    rows = (wb[sheet] if sheet else wb.worksheets[0]).iter_rows(values_only=True)
    next(rows)
    head = [str(h).strip() if h else "" for h in next(rows)]
    return [dict(zip(head, r, strict=False)) for r in rows if r and r[0] not in (None, "")]


def yes(v) -> bool:
    return str(v or "").strip().upper() == "Y"


def num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def archetypes() -> dict:
    zf = zipfile.ZipFile(EIA860)
    plants = {r["Plant Code"]: r for r in sheet_rows(zf, "2___Plant_Y2025.xlsx")
              if r.get("Balancing Authority Code") == "ERCO"}
    pv = collections.defaultdict(list)
    for r in sheet_rows(zf, "3_3_Solar_Y2025.xlsx", "Operable"):
        if r["Plant Code"] in plants and r.get("Prime Mover") == "PV":
            pv[r["Plant Code"]].append(r)
    es = collections.defaultdict(list)
    for r in sheet_rows(zf, "3_4_Energy_Storage_Y2025.xlsx", "Operable"):
        if r["Plant Code"] in plants or num(r.get("Direct Support Plant ID 1")) in plants:
            es[r["Plant Code"]].append(r)
    linked, how = collections.defaultdict(list), {}
    for code, gens in es.items():
        for g in gens:
            host = code if code in pv else int(num(g.get("Direct Support Plant ID 1"))) or None
            if host in pv:
                linked[host].append(g)
                how[host] = "same_plant" if host == code else "direct_support"
    for code, gens in es.items():
        if code in pv or any(g in v for v in linked.values() for g in gens):
            continue
        host = next((h for h in pv if km(plants[code], plants[h]) <= NEAR_KM and name_key(plants[code]["Plant Name"])
                     == name_key(plants[h]["Plant Name"])), None)
        if host is not None:
            linked[host] += gens
            how.setdefault(host, "nearby_named")
    sites = []
    for code, bats in linked.items():
        gens = pv[code]
        ac = sum(num(g["Nameplate Capacity (MW)"]) for g in gens)
        dc = sum(num(g.get("DC Net Capacity (MW)")) for g in gens)
        dc_ok = all(num(g.get("DC Net Capacity (MW)")) > 0 for g in gens)
        bmw = sum(max(num(b.get("Maximum Discharge Rate (MW)")), num(b["Nameplate Capacity (MW)"])) for b in bats)
        bmwh = sum(num(b.get("Nameplate Energy Capacity (MWh)")) for b in bats)
        coup = "dc" if any(yes(b.get("DC Coupled")) or yes(b.get("DC Tightly Coupled")) for b in bats) else \
            "ac" if any(yes(b.get("AC Coupled")) for b in bats) else "independent"
        p = plants[code]
        sites.append({"plant_code": code, "pv_mwac": round(ac, 1), "pv_mwdc": round(dc, 1) if dc_ok else None,
                      "ilr": round(dc / ac, 3) if dc_ok and ac else None, "bess_mw": round(bmw, 1),
                      "bess_mwh": round(bmwh, 1), "duration_h": round(bmwh / bmw, 2) if bmw else None,
                      "bess_over_pv": round(bmw / ac, 3) if ac else None, "coupling": coup,
                      "colocated_by": how[code], "region": region_of(num(p.get("Latitude")), num(p.get("Longitude")))})
    sites.sort(key=lambda s: -s["pv_mwac"])
    in_win = [s for s in sites if 100 <= s["pv_mwac"] <= 300 and s["bess_over_pv"] and 0.4 <= s["bess_over_pv"] <= 0.8
              and s["duration_h"] and 1 <= s["duration_h"] <= 2.05]
    ilrs = [s["ilr"] for s in sites if s["ilr"]]
    coup = collections.Counter(s["coupling"] for s in sites)
    fit = {"sites": len(sites), "in_archetype_window": len(in_win),
           "pv_mwac": quant([s["pv_mwac"] for s in sites]), "ilr": quant(ilrs),
           "bess_over_pv": quant([s["bess_over_pv"] for s in sites if s["bess_over_pv"]]),
           "duration_h": quant([s["duration_h"] for s in sites if s["duration_h"]]),
           "ilr_missing": sum(s["ilr"] is None for s in sites),
           "coupling_share": {k: round(v / len(sites), 3) for k, v in coup.most_common()},
           "coupling_share_ac_vs_dc": round(coup["ac"] / max(1, coup["ac"] + coup["dc"]), 3),
           "colocated_by": dict(collections.Counter(s["colocated_by"] for s in sites).most_common()),
           "regions": dict(collections.Counter(s["region"] for s in sites).most_common())}
    ilr_med = round(statistics.median(ilrs), 2) if ilrs else 1.30
    grid = []
    for pv_ac in (100, 150, 200, 300):
        for ratio in (0.4, 0.67, 0.8):
            for dur in (1, 2):
                n = sum(1 for s in in_win if nearest(s["pv_mwac"], (100, 150, 200, 300)) == pv_ac
                        and nearest(s["bess_over_pv"], (0.4, 0.67, 0.8)) == ratio
                        and nearest(s["duration_h"], (1, 2)) == dur)
                bmw = round(pv_ac * ratio / 25) * 25 or 25
                grid.append({"id": f"pv{pv_ac}-r{round(ratio * 100)}-{dur}h", "pv_mwac": pv_ac, "pv_mwdc": round(pv_ac * ilr_med),
                             "ilr": ilr_med, "bess_over_pv": ratio, "bess_mw": bmw, "bess_mwh": bmw * dur, "poi_mw": pv_ac,
                             "poi_variants_mw": [pv_ac, round(pv_ac * 1.2)], "weight": n + 0.5})
    tot = sum(a["weight"] for a in grid)
    for a in grid:
        a["weight"] = round(a["weight"] / tot, 4)
    default = {"id": "pv150-b100x2h", "pv_mwac": 150, "pv_mwdc": 195, "ilr": 1.30, "bess_mw": 100, "bess_mwh": 200,
               "poi_mw": 150, "poi_variants_mw": [150, 180], "coupling": "ac", "source": "FD-4322 example (archetype)"}
    return {"default": default, "fit": fit, "ilr_median": ilr_med, "archetypes": grid, "sites": sites,
            "notes": ["sites = ERCO plants (EIA-860 2025 2___Plant BA code) with operable PV (3_3) and operable storage "
                      "(3_4) at the same plant code, linked by Direct Support Plant ID 1, or a storage plant within NEAR_KM whose "
                      "name starts with the same word (nearby_named)",
                      "POI is not public: it defaults to the PV AC nameplate, with a 1.2x variant (V3-D7)",
                      "weights: in-window site counts per nearest grid cell plus 0.5 smoothing",
                      "region from plant lat/lon by coarse boxes (approximate)"]}


def km(a: dict, b: dict) -> float:
    la1, lo1, la2, lo2 = (num(a["Latitude"]), num(a["Longitude"]), num(b["Latitude"]), num(b["Longitude"]))
    return math.hypot((la1 - la2) * 111.0, (lo1 - lo2) * 111.0 * math.cos(math.radians(la1)))


def name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", (str(name).lower().split() or [""])[0])


def quant(v: list[float]) -> dict:
    if not v:
        return {}
    q = statistics.quantiles(sorted(v), n=10) if len(v) > 1 else [v[0]] * 9
    return {"n": len(v), "p10": round(q[0], 3), "median": round(statistics.median(v), 3), "p90": round(q[-1], 3),
            "min": round(min(v), 3), "max": round(max(v), 3)}


def nearest(x: float, grid: tuple) -> float:
    return min(grid, key=lambda g: abs(g - x))


def region_of(lat: float, lon: float) -> str:
    """Coarse GridSimEnv region for a plant location (approximate boxes around the hub/LZ footprints)."""
    if lat >= 33.6 and lon <= -99.5:
        return "panhandle"
    if lon <= -100.0:
        return "west"
    if 29.2 <= lat <= 30.6 and -96.3 <= lon <= -94.0:
        return "houston"
    if lat < 29.8:
        return "south"
    if lat >= 31.8:
        return "north"
    return "central"


# ---- main ----

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {"schema": "gridsim.hybrid-inputs/v1", "built_from": {}, "outputs": {}}
    log("AS prices")
    as_rows, as_st = as_prices()
    write_jsonl_gz(OUT / "as_dam_mcpc.jsonl.gz", as_rows)
    log("solar")
    sol_rows, sol_st = solar_cf(args.workers)
    write_jsonl_gz(OUT / "solar_cf.jsonl.gz", sol_rows)
    log("deployments")
    dep, dep_st = deployments()
    (OUT / "deployments.jsonl").write_text("".join(json.dumps(e, separators=(",", ":")) + "\n" for e in dep))
    log("archetypes")
    arch = archetypes()
    (OUT / "archetypes.json").write_text(json.dumps(arch, indent=1) + "\n")
    durations = {"eras": [{**r, "products": list(r["products"])} for r in AS_ERAS], "duration_h": AS_DURATION_H,
                 "notes": AS_DURATION_NOTES, "module": "gridsim_core.contract.as_duration_h"}
    (OUT / "durations.json").write_text(json.dumps(durations, indent=1) + "\n")
    (OUT / "drift.json").write_text(json.dumps(hi.DRIFT_SPEC, indent=1) + "\n")
    srcs = json.loads((RAW / "sources.json").read_text())
    for rel, row in srcs.items():
        manifest["built_from"][f"cache/raw/hybrid/{rel}"] = {k: row.get(k) for k in ("url", "product", "rtid",
                                                                                     "published", "bytes", "sha256")}
    for p in [EIA860, NOTICES / "notices.jsonl.gz", NOTICES / "ops_coverage.json",
              *sorted((ROOT / "cache" / "raw" / "ercot-rt").glob("RTMLZHBSPP_202[1-6].zip"))]:
        manifest["built_from"][str(p.relative_to(ROOT))] = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    stats = {"as_dam_mcpc": as_st, "solar_cf": sol_st, "deployments": dep_st, "archetypes": arch["fit"]}
    for p in sorted(OUT.iterdir()):
        if p.name not in ("manifest.json", "coverage.md"):
            manifest["outputs"][p.name] = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    manifest["stats"] = stats
    manifest["tables"] = tables(as_rows, sol_rows, dep)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, default=str) + "\n")
    (OUT / "coverage.md").write_text(coverage_md(manifest, arch))
    log(json.dumps(stats, default=str)[:3000])


def tables(as_rows: list[dict], sol_rows: list[dict], dep: list[dict]) -> dict:
    asy = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in as_rows:
        for p in AS_PRODUCTS:
            if r[p]:
                asy[r["date"][:4]][p] += [v for v in r[p] if v is not None]
    sol = collections.defaultdict(list)
    for r in sol_rows:
        sol[r["date"][:4]].append(r)
    dy = collections.defaultdict(collections.Counter)
    for e in dep:
        if e["date"] >= START.isoformat():
            dy[e["date"][:4]][e["product"]] += 1
            dy[e["date"][:4]]["mw_stated"] += e["mw_max"] is not None
    return {
        "as_by_year": {y: {p: {"mean": round(statistics.fmean(v), 2), "max": max(v)} for p, v in ps.items()}
                       for y, ps in sorted(asy.items())},
        "solar_by_year": {y: {"days": len(rs), "mean_cf": round(statistics.fmean(statistics.fmean(r["cf"]) for r in rs), 3),
                              "repaired_days": sum(bool(r["repaired_hours"]) for r in rs),
                              "sources": dict(collections.Counter(r["source"] for r in rs))}
                          for y, rs in sorted(sol.items())},
        "deployments_by_year": {y: dict(c) for y, c in sorted(dy.items())},
    }


def coverage_md(m: dict, arch: dict) -> str:
    st, tb = m["stats"], m["tables"]
    a, s, d, f = st["as_dam_mcpc"], st["solar_cf"], st["deployments"], st["archetypes"]
    L = ["# v3 hybrid inputs: sources, coverage and caveats", "",
         "Built by `scripts/build_hybrid_inputs.py` from `cache/raw/hybrid/` (fetched by `scripts/fetch_hybrid_inputs.py`), "
         "`cache/raw/eia860/`, `cache/raw/ercot-rt/` and lane N's notice archive (`data/notices/`). Times are Central "
         "prevailing time (CPT). Every source file and its sha256 is in `manifest.json` (`built_from`).", "",
         "## Files", "",
         "| File | What | Key fields |", "|---|---|---|",
         "| `as_dam_mcpc.jsonl.gz` | DA AS clearing prices (MCPC), one row per operating day | `date, era, n_hours, "
         "regup, regdn, rrs, ecrs, nspin` ($/MW per hour, HE01..HE24; `ecrs` null in era A; DST days carry "
         "`hour_ending` and 23/25 values), `source` |",
         "| `solar_cf.jsonl.gz` | Hourly PV availability capacity factor, system-wide | `cf` (availability proxy), "
         "`cf_actual`, `repaired_hours`, `installed_mw`, `source`, `scope: system` |",
         "| `deployments.jsonl` | RRS, ECRS and Non-Spin deployment events | `event_id, product, variant, date, start, "
         "end, end_basis, planned_end, mw_max, mw_steps, frac, source_notice_id, notice_ids, summary` |",
         "| `durations.json` | The era-keyed AS duration table (same as `gridsim_core.contract.AS_DURATION_H`) | |",
         "| `drift.json` | v4's seeded regulation-drift spec (`gridsim_core.hybrid_inputs.reg_drift`) | |",
         "| `reg_deploy.jsonl.gz` | ERCOT's storage fleet regulation deployment per hour (scripts/build_reg_drift.py) | "
         "`date, up, dn, n, sampling, carriers, regup_mw, regdn_mw, coherence, doc_id, sha256` |",
         "| `reg_model.json`, `reg_deploy.md` | Its means, method and checks, and the fitted imbalance fallback (v3) | |",
         "| `archetypes.json` | EIA-860 2025 co-located PV+BESS sites in ERCO, the fit, the archetype grid, the default | |",
         "", "Loader: `gridsim_core.hybrid_inputs` (`as_prices`, `solar_cf`, `pv_profile_mw`, `deployments`, "
         "`archetypes`, `reg_drift`, `reg_hourly`).", "",
         "## Sources", "",
         "| Input | ERCOT/EIA product | Report type id | Files |", "|---|---|---|---|",
         "| DA AS MCPC, yearly | NP4-181-ER Historical DAM Clearing Prices for Capacity | 13091 | DAMASMCPC_2021..2026 "
         "(2021-2025 csv, 2026 xlsx through 2026-10-17) |",
         "| DA AS MCPC, daily tail | NP4-188-CD DAM Clearing Prices for Capacity | 12329 | 7 daily csvs, delivery "
         "2026-10-18..2026-10-24 |",
         "| Solar, system-wide 2023-2025 | PG7-126-M Hourly Aggregated Wind and Solar Output | 13424 | "
         "ERCOT_2023..2025_Hourly_WindSolar_Output.xlsx (ERCOT.PVGR.GEN, Total Solar Installed MW) |",
         "| Solar, system-wide 2021-2022 and 2026 | ERCOT Fuel Mix Report (gridinfo/generation) | n/a (files/docs) | "
         "FuelMixReport_PreviousYears.zip (IntGenbyFuel2021/2022), IntGenbyFuel2026.xlsx (through 2026-09-30) |",
         "| Solar capacity 2021-2022, 2026 | EIA-860M September 2026 (Operating + Retired, BA ERCO, Solar Photovoltaic) | "
         "n/a | september_generator2026.xlsx |",
         "| Curtailment hours | NP6-785-ER RT SPPs (v2's RTMLZHBSPP zips) at HB_HUBAVG | 13061 | RTMLZHBSPP_2021..2026 |",
         "| Regional solar (layout only) | NP4-745-CD Solar Power Production, Hourly Averaged Actual and Forecasted "
         "Values by Geographical Region | 21809 | one sample file |",
         "| RT AS MCPC era C (layout only) | NP6-331-CD Real-Time Clearing Prices for Capacity by 15-Minute "
         "Settlement Interval | 24898 | one sample file |",
         "| RT AS price adders era C | NP6-793-ER Historical RT ORDC and Reliability Deployment Prices (15-min) | "
         "13240 | HIST_RT15MPRICEADDER_2025, _2026 (fetched, not built) |",
         "| Deployments | lane N's archive: ERCOT Operations Messages tagged `as_deployment` | n/a | "
         "data/notices/notices.jsonl.gz |",
         "| Hybrid configs | EIA-860 2025 (2___Plant, 3_3 Solar, 3_4 Energy Storage) | n/a | eia8602025.zip |",
         "| Pre-RTC+B SoC rule | NPRR1186 PUCT Report (ercot.com/mktrules/issues/NPRR1186) | n/a | "
         "1186NPRR-36_PUCT_Report_041124.docx |", "",
         "ERCOT MIS endpoints (`/misapp/servlets/IceDocListJsonWS`, `/misdownload/servlets/mirDownload`) are listed "
         "under `Disallow` in ercot.com's robots.txt. They were used as v1 used them, at 1 request per second with a "
         "named user agent, about 30 MIS requests in all; everything is cached so a rebuild makes no requests. EIA files come "
         "from `/electricity/data/eia860m/xls/` (allowed; `/archive/` is disallowed and was not used).", "",
         "## 1. DA AS clearing prices", "",
         f"- Coverage: {a['first']} to {a['last']}, {a['days']} days, no missing dates (gaps: {len(a['gaps'])}); "
         f"era A {a.get('era_A', 0)}, era B {a.get('era_B', 0)}, era C {a.get('era_C', 0)} days; {a.get('dst_days', 0)} "
         "DST days kept with 23/25 hours. First ECRS price: " + a["first_ecrs"] + ".",
         "- Product mapping: the file columns REGUP, REGDN, RRS, ECRS and NSPIN map one to one to `regup, regdn, rrs, "
         "ecrs, nspin` in every era, including after RTC+B (the 2025 file's December rows and the 2026 file keep the "
         "same five columns). The DAM clears one RRS MCPC for all RRS sub-types (PFR, FFR, UFR/Load Resources), so "
         "v3's single RRS product uses it unchanged; ECRS is one DAM MCPC (on- and off-line ECRS are not priced "
         "separately). Non-Spin is the NSPIN column (on- and off-line Non-Spin share it).",
         "- MCPCs are as published. Winter Storm Uri (February 2021) cleared AS above the $9,000 HCAP (up to $25,674 "
         "for RRS); those days are out of every split (Uri ±3 days).",
         "", "| Year | regup mean / max | regdn mean / max | rrs mean / max | ecrs mean / max | nspin mean / max |",
         "|---|---|---|---|---|---|"]
    for y, ps in tb["as_by_year"].items():
        L.append(f"| {y} | " + " | ".join(f"{ps[p]['mean']} / {ps[p]['max']}" if p in ps else "-" for p in AS_PRODUCTS)
                 + " |")
    ratio = s["ercot_over_eia_installed"]
    L += ["", "## 2. Solar profile", "",
          f"- Coverage: {s['first']} to {s['last']}, {s['days']} days, no missing dates (gaps: {len(s['gaps'])}). "
          "2026-10 is not covered: ERCOT's 2026 fuel-mix workbook stops at 2026-09-30 and MIS keeps NP4-745-CD for "
          "about a week.",
          "- **System-wide only, used for every region.** NP4-745-CD (regional actual, COP HSL, STPPF, PVGRPP; regions "
          "CenterWest, NorthWest, FarWest, FarEast, SouthEast, CenterEast, plus SYSTEM_WIDE_HSL) is real, but the MIS "
          "document list keeps only the last ~7 days (350 docs, 2026-10-17..24). ERCOT's public API archive (said to "
          "start 2023-12-11) needs a subscription key and was not used. So `scope` is `system` in every row and "
          "`solar_cf(date, region)` ignores the region. Flagged.",
          "- cf_t = system solar MW / installed MW. 2023-2025 use ERCOT's own hourly `Total Solar Installed, MW` "
          "(PG7-126-M). 2021-2022 and 2026 use the fuel-mix 15-minute solar MWh summed per hour, over EIA-860M operable "
          "ERCO PV nameplate at month end times ERCOT/EIA calibration: ERCOT's installed figure runs "
          f"{ratio['min']}-{ratio['max']}x EIA's over the {ratio['months']} overlap months, so 2021-2022 use the median "
          f"of the first 6 overlap months ({ratio['used_before_2023']}) and 2026 the median of the last 6 "
          f"({ratio['used_after_2025']}). Expect about +/-10% level error in those years.",
          f"- **Availability proxy (flagged).** Actual output is curtailed output. Where an hour's HB_HUBAVG RT SPP "
          f"(mean of its four 15-minute prices) is <= 0, `cf` = max(actual, median cf of the same hour on the days "
          f"within +/-{REPAIR_WINDOW} whose same hour priced above 0); otherwise `cf` = actual. `cf_actual` keeps the "
          f"unrepaired value (for the weight-0 historical-operator row). {s['repaired_hours']} hours on "
          f"{s['repaired_days']} days were raised (example: {s['example']}). HSL-based "
          "availability (max(actual, HSL)) needs NP4-745's history, which is not available, so it is not applied. "
          "West-only curtailment at positive hub prices is not detected.",
          "- The plan's plant profile AC x ILR x cf_t (`pv_profile_mw`) treats the fleet cf, which is AC output already "
          "clipped at the fleet's inverters (fleet ILR ~1.3), as a DC-side shape; it overstates midday DC potential "
          "slightly and is a proxy.", "",
          "| Year | Days | Mean cf | Days with repaired hours | Sources |", "|---|---|---|---|---|"]
    for y, r in tb["solar_by_year"].items():
        L.append(f"| {y} | {r['days']} | {r['mean_cf']} | {r['repaired_days']} | "
                 + ", ".join(f"{k} {v}" for k, v in r["sources"].items()) + " |")
    L += ["", "## 3. AS duration table (era-keyed)", "",
          "`gridsim_core.contract.AS_DURATION_H`, `as_era(d)`, `as_products(d)`, `as_duration_h(product, d)`; new code, "
          "nothing existing changed. Era A 2021-01-01..2023-06-09, B 2023-06-10..2025-12-04, C from 2025-12-05.", "",
          "| Product | Era A | Era B | Era C (NPRR1282) |", "|---|---|---|---|"]
    for p in AS_PRODUCTS:
        L.append(f"| {p} | " + " | ".join(f"{AS_DURATION_H[e][p]:g} h" if p in AS_DURATION_H[e] else "n/a"
                                          for e in "ABC") + " |")
    L += ["", "- **The pre-RTC+B rule, from the NPRR1186 protocol text** (PUCT Report 1186NPRR-36, approved 2024-04-11; "
          "Nodal Protocols 8.1(4)(a)(ii)(A) and 6.5.5.2(14)(a)(ii)(A); fetched to `cache/raw/hybrid/nprr/`): the SoC an "
          "ESR must hold for each up AS (ECRS, Non-Spin, RRS, Reg-Up; FFR and FRRS aside) is its responsibility R times "
          "(the time left in the operating hour + the AS duration − 1 h); RRS from FFR needs R × 0.25 h; Reg-Down needs "
          "headroom R × the time left in the hour. At the top of each hour that is R × duration, sloping to R × "
          "(duration − 1 h) at its end.",
          "- What stays open (V3-D1): the text uses \"the duration of the Ancillary Service\" without stating the "
          "values. 1 h for Reg and RRS is consistent with it (the (duration − 1 h) term implies at least 1 h) and is "
          "kept, flagged. ECRS 2 h and Non-Spin 4 h follow NPRR1096's sustained-capability titles. NPRR1186 went live "
          "2024-06-27 (ERCOT notice M-B060424-01); before that no SoC rule applied, so applying the table from 2021 is "
          "a modelling choice. v3's check of R × duration at both ends of each hour is conservative against the "
          "in-hour slope.", "",
          "## 4. Deployments", "",
          f"- From {d['tagged']} archive rows tagged `as_deployment` ({d['messages']} parsed messages; {d['ers_skipped']} "
          f"ERS rows and EEA rows skipped; {d['cancel_or_cancelled']} cancellations and cancelled rows dropped; "
          f"{d['unparsed']} unparsed). {d['ruc']} rows are tagged `ruc` (counted, not events).",
          f"- Events: RRS {d.get('events_rrs', 0)}, ECRS {d.get('events_ecrs', 0)}, Non-Spin {d.get('events_nspin', 0)} "
          f"(all years 2017-2026). End basis: recall {d.get('end_recall', 0)}, planned END_TIME "
          f"{d.get('end_planned_end', 0)}, next deploy {d.get('end_next_deploy', 0)}, capped {d.get('end_cap', 0)}.",
          "- Times are minute-stamped. A Non-Spin `CM-ASM-NOTF` message's BEGIN_TIME (often the next hour) is its step "
          "time; \"At HH:MM\" in the text is used when given. Messages apply in issue order, so a recall drops hourly "
          "re-deployments scheduled after it.",
          "- MW: Non-Spin messages state system MW (`mw_max`, `mw_steps`). RRS and ECRS messages never state MW or a "
          "fraction, so `mw_max` is null. `frac` is null on every event: the system deployed share of the procured "
          "quantity needs the hourly AS plan or DAM procured MW, not fetched tonight. Core needs a labelled rule for "
          "frac (for example 1.0 of the award for the event window capped by the era's duration, the stress case the "
          "reservation rule already covers).",
          "- `summary` is generated from the parsed fields; no verbatim notice text is stored.",
          "- The archive has no RRS deployment message after 2023 and no ECRS one after 2025 (no untagged RRS/ECRS "
          "deployment wording either); after RTC+B, SCED releases reserves itself and only Non-Spin messages remain. "
          "Era C days therefore carry Non-Spin events only.",
          "- Coverage follows the archive's operations-message coverage: " + ", ".join(
              f"{y} {v}" for y, v in d["archive_coverage_by_year"].items()) + " (share of each day covered).", "",
          "| Year | RRS | ECRS | Non-Spin | events with MW |", "|---|---|---|---|---|"]
    for y, c in tb["deployments_by_year"].items():
        L.append(f"| {y} | {c.get('rrs', 0)} | {c.get('ecrs', 0)} | {c.get('nspin', 0)} | {c.get('mw_stated', 0)} |")
    L += ["", "## 5. Regulation drift", "",
          "v3's drift (V3-D8) is built by `scripts/build_reg_drift.py`: ERCOT's storage fleet regulation deployment "
          "from the 60-Day SCED Disclosure (NP3-965-ER, public API archive) on the days it covers, and an "
          "imbalance-driven fallback fitted to it before; `reg_deploy.md` has the method, coverage and checks, and "
          "`gridsim_core.hybrid_inputs.reg_hourly(task_id, date, da, rt)` loads it. `drift.json` keeps v4's seeded "
          "draw (`reg_drift(task_id)`: Beta(m·k, (1−m)·k) with m = 0.12 and 0.18, k = 6, seeded by "
          "`stable_seed(task_id + '|reg-drift')`).", "",
          "## 6. EIA-860 hybrid archetypes", "",
          f"- {f['sites']} co-located PV+BESS sites in ERCO in EIA-860 2025 ({', '.join(f'{k} {v}' for k, v in f['colocated_by'].items())}); "
          f"{f['in_archetype_window']} fall in the archetype window (PV 100-300 MWac, BESS 0.4-0.8 of PV MW, 1-2 h).",
          f"- PV MWac median {f['pv_mwac']['median']} (p10 {f['pv_mwac']['p10']}, p90 {f['pv_mwac']['p90']}); ILR median "
          f"{f['ilr']['median']} (p10 {f['ilr']['p10']}, p90 {f['ilr']['p90']}; MWdc reported for all); BESS/PV MW "
          f"median {f['bess_over_pv']['median']}; duration median {f['duration_h']['median']} h.",
          f"- Coupling flags (3_4): {', '.join(f'{k} {v}' for k, v in f['coupling_share'].items())}. No matched ERCO site "
          "reports DC or DC-tightly coupled storage, so the plan's ~70% AC / ~30% DC split is not supported by "
          "EIA-860 2025; many sites flag neither (\"independent\").",
          f"- Regions (coarse lat/lon boxes): {', '.join(f'{k} {v}' for k, v in f['regions'].items())}.",
          f"- Default: {arch['default']['pv_mwac']} MWac / {arch['default']['pv_mwdc']} MWdc PV, "
          f"{arch['default']['bess_mw']} MW / {arch['default']['bess_mwh']} MWh BESS, {arch['default']['poi_mw']} MW POI "
          "(variant 180 MW). The grid (`archetypes`) is PV 100/150/200/300 MWac × BESS 0.4/0.67/0.8 of PV × 1/2 h, ILR at "
          "the fit median, POI = PV AC with a 1.2× variant; weights are in-window site counts per nearest cell plus 0.5 "
          "smoothing (the sample is small, so weights are near uniform).", "",
          "## 7. RT AS MCPC (era C)", "",
          "- The post-RTC+B report is **NP6-331-CD, Real-Time Clearing Prices for Capacity by 15-Minute Settlement "
          "Interval, report type 24898** (long format: DeliveryDate, DeliveryHour, DeliveryInterval, RepeatedHourFlag, "
          "ASType in REGUP/REGDN/RRS/ECRS/NSPIN, MCPC). The SCED-interval version is NP6-332-CD (24891).",
          "- History: MIS keeps 7 days (702 csvs, 2026-10-17..24). No yearly historical file for RT MCPC was found. "
          "NP6-793-ER (13240) has HIST_RT15MPRICEADDER_2025/2026 from 2025-12-05 with per-AS reliability deployment "
          "price adders (RTRDPRU, RTRDPRD, RTRDPRRS, RTRDPECRS, RTRDPNS), which are adders, not MCPCs. ERCOT's API "
          "archive may hold the history but needs a key. **T3 cannot be built tonight; drop it, or start a daily "
          "NP6-331-CD capture.**", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
