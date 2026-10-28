"""v3 "Sun, Storage and Reserves" series fields for the desk packs (docs/CONTRACT-desk.md 10.1, docs/desk-data.md
section 10): the DAM AS Plan, the storage fleet's regulation deployment, AS deployment events, the co-located PV option
(modelled from ERCOT's regional solar actuals and forecasts) and the operator's disclosed AS offers and capability.
Called from desk_data_build.build_task for every layer above v2."""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import desk_data_api as A  # noqa: E402
import desk_data_v5 as V5  # noqa: E402

from gridsim_core import hybrid_inputs as HI  # noqa: E402

CPT = ZoneInfo("America/Chicago")
PLAN_KEY = {"REGUP": "regup", "REGDN": "regdn", "RRS": "rrs", "ECRS": "ecrs", "NSPIN": "nspin"}
OFFER_KEY = {"REGUP": "regup", "REGDN": "regdn", "RRSPFR": "rrspfr", "RRSFFR": "rrsffr", "ECRS": "ecrs",
             "OnlineNSPIN": "nspin", "NSPIN": "nspin"}
CAP_KEY = {"REGUP": "regup", "REGDN": "regdn", "RRSPFR": "rrspfr", "RRSFFR": "rrsffr", "ECRS": "ecrs", "NSPIN": "nspin"}
PRE_AWARD = {"regup": "REGUPAwarded", "regdn": "REGDNAwarded", "rrspfr": "RRSPFRAwarded", "rrsffr": "RRSFFRAwarded",
             "ecrs": "ECRSSDAwarded", "nspin": "NSPINAwarded"}
MAX_BLOCKS, MIN_BLOCK_MW = 5, 0.1
PV_SHARE, PV_ILR = 0.6, 1.3
REGION_745 = {"west": "FarWest", "houston": "SouthEast", "north": "CenterEast", "south": "SouthEast"}
REG_SOURCE = {"ercot": "measured", "ercot+modelled": "measured+modelled", "modelled": "modelled"}

V3_EVAL_DAYS = ("2026-04-11", "2026-04-24", "2026-05-26", "2026-06-06", "2026-07-21", "2026-08-22")
V3_EVAL_PV = {("2026-04-24", "S01"), ("2026-05-26", "S02"), ("2026-05-26", "S04"), ("2026-04-11", "S01"),
              ("2026-06-06", "S03"), ("2026-07-21", "S02"), ("2026-07-21", "S04"), ("2026-08-22", "S03")}
SITE_IDS = ("S01", "S02", "S03", "S04")
SOURCES = {
    "as_plan": "NP4-33-CD DAM AS Plan, latest posting <= D-1 06:00 [data]",
    "reg_deploy": "data/hybrid/reg_deploy (60-day SCED storage-fleet regulation) else the fitted fallback [modelled]",
    "deployments": "data/hybrid/deployments.jsonl (ERCOT notices) [data]",
    "rt_lmp_hub": "NP6-788-CD at the site's hub [data]",
    "pv": "MODELLED PV: NP4-745-CD regional actual / (share x EIA-860M capacity) x ILR, NP4-738-CD shape",
    "forecasts.pv": "MODELLED from NP4-745-CD regional STPPF vintages",
    "operator.dam.as_offers": "NP3-966-ER 60d DAM ESR (pre: Gen Resource) AS Offers, per product [simplified]",
    "operator.sced.as_offer_updates": "NP3-965-ER 60d SCED Resource AS Offers, incl. proxy extension [simplified]",
    "operator.cop.as_capability": "NP3-991-EX COP All Updates",
    "market": "v5: NP3-966-ER 60-Day DAM Disclosure via market_stack.build_day, site resource carved out",
}
PACKS = {
    "desk-v3-pilot": {"split": "pilot", "layer": "v3", "tasks": [("2026-04-20", "S01"), ("2026-08-14", "S03")],
                      "pv": {("2026-04-20", "S01")}},
    "desk-v3-eval": {"split": "eval", "layer": "v3", "tasks": [(d, s) for d in V3_EVAL_DAYS for s in SITE_IDS],
                     "pv": V3_EVAL_PV},
    "desk-v3-pre": {"split": "train", "layer": "v3", "tasks": [("2025-06-24", "S04"), ("2025-10-21", "S01")],
                    "pv": {("2025-06-24", "S04")}},
    **V5.PACKS,
}


def extend(ser: dict, site: dict, days: list[dt.date], era: str, spec: dict, d0: str, sid: str, info) -> dict:
    """Add the v3 fields to a series in place; returns extra task tags and the AS part of operator_ok."""
    import desk_data_build as D
    ser["rt_lmp_hub"] = {str(d): D.lmp_day(site["hub"], d)[0] for d in [days[0] - dt.timedelta(days=1)] + days}
    ser["as_plan"] = {str(d): as_plan_day(d) for d in days}
    ser["reg_deploy"] = {str(d): reg_deploy(ser["task_id"], ser, d) for d in days}
    ser["deployments"] = deployments(days)
    pv = (d0, sid) in spec.get("pv", ())
    if pv:
        add_pv(ser, site, days)
    as_ok = True
    for d in days:
        k = str(d)
        op_dam, op_sced, op_cop = ser["operator"]["dam"][k], ser["operator"]["sced"][k], ser["operator"]["cop"][k]
        rng = site["hsl_mw"] - site["lsl_mw"]
        if era == "rtcb":
            op_dam["as_offers"] = dam_as_offers("np3-966-er/60d_dam_esr_as_offers", site["resource"], d, rng)
            if op_sced is not None:
                op_sced["as_offer_updates"], n = sced_as_offers(site["resource"], d, rng)
                as_ok = as_ok and n > 0
            else:
                as_ok = False
            if op_cop is not None:
                op_cop["as_capability"] = cop_capability(site["resource"], d)
        else:
            op_dam["as_offers"] = dam_as_offers("np3-966-er/60_dam_gen_res_as_offers", site["resource_pre"]["gen"],
                                                d, site["hsl_mw"])
            op_dam["as_awards"] = pre_awards(site["resource_pre"]["gen"], d)
        info["as_offer_hours"] += sum(1 for v in op_dam["as_offers"].values() for x in v if x)
    if spec["layer"] == "v5":
        V5.extend(ser, site, days, info)
    rt_mcpc = ser.get("rt_mcpc") or {}
    tags = {"pv": pv, "deployments": len(ser["deployments"]),
            "max_rt_mcpc": max((max(v) for d in days for v in (rt_mcpc.get(str(d)) or {}).values() if v),
                               default=None),
            "max_dam_mcpc": max(max(v) for d in days for v in ser["dam_mcpc"][str(d)].values() if v)}
    return {"tags": tags, "operator_ok": as_ok}


# ---------------------------------------------------------------- system inputs

def parse_local(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s[:19]).replace(tzinfo=CPT)


def local_iso(t: dt.datetime) -> str:
    z = t.astimezone(CPT).strftime("%z")
    return t.astimezone(CPT).strftime("%Y-%m-%dT%H:%M:%S") + z[:3] + ":" + z[3:]


def as_plan_day(day: dt.date) -> dict:
    """NP4-33-CD DAM AS Plan for `day`: the latest posting at or before D-1 06:00 (else the first)."""
    f, r = A.query("np4-33-cd/dam_as_plan", {"deliveryDateFrom": str(day), "deliveryDateTo": str(day)})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["DSTFlag"].astype(bool)]
    cutoff = f"{day - dt.timedelta(days=1)}T06:00:00"
    posts = sorted(df["postedDatetime"].unique())
    pick = max([p for p in posts if p <= cutoff], default=posts[0])
    x = df[df["postedDatetime"] == pick]
    out = {}
    for t, key in PLAN_KEY.items():
        y = x[x["ancillaryType"] == t]
        v = {int(he.split(":")[0]): float(q) for he, q in zip(y["hourEnding"], y["quantity"], strict=False)}
        out[key] = [v.get(h) for h in range(1, 25)]
    out["posted_at"] = local_iso(parse_local(pick))
    return out


def reg_deploy(task_id: str, ser: dict, day: dt.date) -> dict:
    da = ser["dam_spp"][str(day)]
    rt15 = ser["rt_spp"][str(day)]
    rt = [sum(rt15[4 * h:4 * h + 4]) / 4 for h in range(24)]
    r = HI.reg_hourly(task_id, str(day), da, rt)
    return {"up": r["up"], "dn": r["dn"], "source": REG_SOURCE.get(r["source"], r["source"]), "label": r["label"]}


def deployments(days: list[dt.date]) -> list[dict]:
    seen, out = set(), []
    for d in days:
        for e in HI.deployments(d):
            if e["event_id"] in seen:
                continue
            seen.add(e["event_id"])
            out.append({"event_id": e["event_id"], "product": e["product"], "start": e["start"], "end": e["end"],
                        "frac": e.get("frac"), "mw_max": e.get("mw_max"), "end_basis": e.get("end_basis"),
                        "summary": e.get("summary"), "notice_ids": e.get("notice_ids", []),
                        "source": "ERCOT notices (data/hybrid/deployments.jsonl)"})
    return sorted(out, key=lambda e: e["start"])


# ---------------------------------------------------------------- PV option (modelled)

def add_pv(ser: dict, site: dict, days: list[dt.date]) -> None:
    """A co-located PV plant at the site: AC nameplate PV_SHARE x HSL, DC/AC PV_ILR, behind the site's POI (= HSL).
    Hourly output = regional capacity factor (ERCOT NP4-745-CD actual generation of the site's solar region over the
    region's capacity, estimated as its share of system output x the EIA-860M system AC capacity) x ILR, clipped at
    nameplate; shaped within the hour by the 5-minute system solar actual (NP4-738-CD). The forecast vintages apply the
    same scaling to the region's as-issued STPPF. Everything here is modelled."""
    region = REGION_745[site["region"]]
    mw_ac = float(round(PV_SHARE * site["hsl_mw"] / 5) * 5)
    d0, dl = days[0], days[-1]
    f, r = A.query("np4-745-cd/spp_hrly_actual_fcast_geo",
                   {"postedDatetimeFrom": f"{d0 - dt.timedelta(days=1)}T00:00:00",
                    "postedDatetimeTo": f"{dl + dt.timedelta(days=1)}T01:59:59"})
    df = pd.DataFrame(r, columns=f)
    df = df[~df["DSTFlag"].astype(bool)].sort_values("postedDatetime")
    issue0 = f"{d0 - dt.timedelta(days=1)}T06:00:00"
    first = df[df["postedDatetime"] <= issue0]["postedDatetime"].max()
    base = df[(df["postedDatetime"] == first) & df["genSystemWide"].notna()]
    share = float(base[f"gen{region}"].sum() / base["genSystemWide"].sum())
    inst = HI.solar_row(d0 - dt.timedelta(days=1))["installed_mw"]
    cap = share * inst
    act = df[df[f"gen{region}"].notna()].drop_duplicates(["deliveryDate", "hourEnding"], keep="last")
    act = {(a, int(h)): float(g) for a, h, g in zip(act["deliveryDate"], act["hourEnding"], act[f"gen{region}"],
                                                    strict=False)}
    ser["pv"] = {}
    for d in days:
        sys5 = ser["system"][str(d)]["solar_mw"]
        out = []
        for h in range(24):
            g = act.get((str(d), h + 1))
            if g is None:
                raise ValueError(f"PV: no {region} actual for {d} HE{h + 1}")
            mw = mw_ac * PV_ILR * g / cap
            s = [x or 0.0 for x in sys5[12 * h:12 * h + 12]]
            m = sum(s) / 12
            out += [round(min(mw_ac, mw * (x / m if m > 1.0 else 1.0)), 2) for x in s]
        ser["pv"][str(d)] = out
    end = dt.datetime(dl.year, dl.month, dl.day) + dt.timedelta(days=2)
    model = f"modelled PV ({mw_ac:.0f} MWac, ILR {PV_ILR}) from ERCOT STPPF {region} (NP4-745-CD)"
    vint = []
    for posted, g in df[df["postedDatetime"] < f"{dl + dt.timedelta(days=1)}T00:00:00"].groupby("postedDatetime"):
        t = dt.datetime.fromisoformat(posted[:19])
        start = t.replace(minute=0, second=0)
        g = {(a, int(h)): v for a, h, v in zip(g["deliveryDate"], g["hourEnding"], g[f"STPPF{region}"], strict=False)}
        vals, s = [], start
        while s < end:
            v = g.get((s.date().isoformat(), s.hour + 1))
            if v is None:
                break
            vals.append(round(min(mw_ac, mw_ac * PV_ILR * float(v) / cap), 1))
            s += dt.timedelta(hours=1)
        if vals:
            vint.append({"kind": "pv", "issued_at": local_iso(parse_local(posted)),
                         "start": local_iso(start.replace(tzinfo=CPT)), "step_min": 60, "values": vals,
                         "model": model, "zone": region})
    ser["forecasts"] = ser["forecasts"] + vint
    site["pv"] = {"mw_ac": mw_ac, "poi_mw": site["hsl_mw"], "ilr": PV_ILR, "profile": "modelled",
                  "region": region, "capacity_mw_est": round(cap, 1), "region_share": round(share, 4),
                  "source": "NP4-745-CD regional actual/STPPF x EIA-860M system AC capacity; NP4-738-CD 5-min shape"}


# ---------------------------------------------------------------- operator AS

def _blocks(row: dict, n: int, prices: dict[str, str], cumulative: bool) -> dict[str, list]:
    """Per product, incremental [MW, $] blocks of one AS offer row. DAM rows give each block's own MW (`cumulative`
    False); SCED rows give each product's cumulative MW over the blocks it prices (True)."""
    out: dict[str, list] = {}
    prev: dict[str, float] = {}
    for i in range(1, n + 1):
        q = row.get(f"quantityMW{i}")
        if q is None or pd.isna(q) or float(q) <= 0:
            continue
        for col, key in prices.items():
            p = row.get(f"price{i}{col}")
            if p is None or pd.isna(p):
                continue
            mw = float(q) - prev.get(key, 0.0) if cumulative else float(q)
            if cumulative:
                prev[key] = max(prev.get(key, 0.0), float(q))
            if mw > 0:
                out.setdefault(key, []).append([mw, float(p)])
    return out


def _tidy(blocks: list, cap_mw: float) -> list | None:
    """Sort by price, merge equal prices, at most MAX_BLOCKS (adjacent blocks merged at their MW-weighted price), total
    MW capped at `cap_mw`, blocks below 0.1 MW dropped."""
    m: dict[float, float] = {}
    for mw, p in blocks:
        m[round(p, 2)] = m.get(round(p, 2), 0.0) + mw
    b = sorted([[mw, p] for p, mw in m.items()], key=lambda x: x[1])
    while len(b) > MAX_BLOCKS:
        i = min(range(len(b) - 1), key=lambda i: b[i + 1][1] - b[i][1])
        mw = b[i][0] + b[i + 1][0]
        b[i:i + 2] = [[mw, (b[i][0] * b[i][1] + b[i + 1][0] * b[i + 1][1]) / mw]]
    out, left = [], cap_mw
    for mw, p in b:
        mw = min(mw, left)
        left -= mw
        if mw >= MIN_BLOCK_MW:
            out.append([round(mw, 1), round(p, 2)])
    return out or None


def _caps(rng: float) -> dict[str, float]:
    return {k: rng for k in set(OFFER_KEY.values())}


def dam_as_offers(path: str, resource: str, day: dt.date, rng: float) -> dict:
    """{product: [24 x blocks | None]} from the 60-day DAM AS offers (each row one offer; quantities cumulative)."""
    f, r = A.query(path, {"resourceName": resource, "deliveryDateFrom": str(day), "deliveryDateTo": str(day)})
    df = pd.DataFrame(r, columns=f)
    prices = {c[len("price1"):]: OFFER_KEY[c[len("price1"):]] for c in df.columns
              if c.startswith("price1") and c[len("price1"):] in OFFER_KEY}
    per: dict[str, list] = {k: [[] for _ in range(24)] for k in set(prices.values())}
    for row in df.to_dict("records"):
        h = int(str(row["hourEnding"]).split(":")[0]) - 1
        for k, b in _blocks(row, 5, prices, False).items():
            per[k][h] += b
    caps = _caps(rng)
    out = {k: [_tidy(v, caps[k]) if v else None for v in hours] for k, hours in per.items()}
    return {k: v for k, v in out.items() if any(v)}


def sced_as_offers(resource: str, day: dt.date, rng: float) -> tuple[list, int]:
    """[{t, product, blocks}] at every SCED run where a product's offer in force changed (60-day SCED Resource AS
    offers: the QSE's RT offer, the DAM offer carried into RT, or ERCOT's proxy extension), online products only."""
    f, r = A.query("np3-965-er/60d_sced_resource_as_offers", {"resourceName": resource,
                                                               "SCEDTimestampFrom": f"{day}T00:00:00",
                                                               "SCEDTimestampTo": f"{day}T23:59:59"})
    df = pd.DataFrame(r, columns=f)
    if df.empty:
        return [], 0
    df = df[~df["repeatHourFlag"].astype(bool) & df["offerType"].isin(["ONRES", "REGDN"])]
    prices = {c[len("price1"):]: OFFER_KEY[c[len("price1"):]] for c in df.columns
              if c.startswith("price1") and c[len("price1"):] in OFFER_KEY}
    caps = _caps(rng)
    out, last = [], {}
    for ts, g in df.sort_values("SCEDTimestamp").groupby("SCEDTimestamp", sort=True):
        per: dict[str, list] = {}
        for row in g.to_dict("records"):
            for k, b in _blocks(row, 6, prices, True).items():
                per.setdefault(k, []).extend(b)
        cur = {k: _tidy(v, caps[k]) for k, v in per.items()}
        for k in sorted(set(cur) | set(last)):
            if cur.get(k) != last.get(k) and cur.get(k):
                out.append({"t": local_iso(parse_local(ts)), "product": k, "blocks": cur[k]})
        last = cur
    return out, df["SCEDTimestamp"].nunique()


def cop_capability(resource: str, day: dt.date) -> dict:
    """COP AS capability per hour from the update in force at T-60 (the same rule as the COP block)."""
    f, r = A.query("np3-991-ex/60_cop_all_updates", {"resourceName": resource, "deliveryDateFrom": str(day),
                                                     "deliveryDateTo": str(day)})
    df = pd.DataFrame(r, columns=f)
    out = {k: [None] * 24 for k in CAP_KEY.values()}
    if df.empty:
        return out
    df = df[~df["cancelFlag"].astype(bool)]
    df["he"] = df["hourEnding"].str.split(":").str[0].astype(int)
    for he in range(1, 25):
        frz = f"{day}T{he - 2:02d}:00:00" if he >= 2 else f"{day - dt.timedelta(days=1)}T23:00:00"
        x = df[(df["he"] == he) & (df["submitTime"] <= frz)].sort_values("submitTime")
        if x.empty:
            x = df[df["he"] == he].sort_values("submitTime")
        if x.empty:
            continue
        row = x.iloc[-1]
        for c, k in CAP_KEY.items():
            v = row.get(c)
            out[k][he - 1] = None if v is None or pd.isna(v) else round(float(v), 3)
    return out


def _num(v) -> float:
    return 0.0 if v is None or pd.isna(v) else round(float(v), 3)


def pre_awards(gen: str, day: dt.date) -> dict:
    f, r = A.query("np3-966-er/60_dam_gen_res_data", {"resourceName": gen, "deliveryDateFrom": str(day),
                                                      "deliveryDateTo": str(day)})
    rows = {int(x["hourEnding"]): x for x in pd.DataFrame(r, columns=f).to_dict("records")}
    out = {}
    for k, c in PRE_AWARD.items():
        if any(c in x for x in rows.values()):
            out[k] = [_num(rows[h].get(c)) if h in rows else None for h in range(1, 25)]
    return out


def merge_refs(pack: str, refs_path: str) -> int:
    """Write the refs blocks from `desk_run.py --refs-only` (refs.jsonl) into the pack's task rows."""
    import gzip
    import json
    root = Path(__file__).resolve().parents[1] / "data" / "desk" / pack
    refs = {r["task_id"]: r["refs"] for r in map(json.loads, open(refs_path)) if r.get("refs")}
    tasks = [json.loads(x) for x in gzip.open(root / "tasks.jsonl.gz", "rt")]
    n = 0
    for t in tasks:
        r = refs.get(t["task_id"])
        if r:
            t["refs"] = r
            n += 1
    with gzip.GzipFile(root / "tasks.jsonl.gz", "wb", mtime=0) as f:
        for t in tasks:
            f.write((json.dumps(t, separators=(",", ":")) + "\n").encode())
    rs = [t["refs"] for t in tasks if t.get("refs")]
    m = json.loads((root / "manifest.json").read_text())
    m["refs"] = {"n": len(rs), "core_version": sorted({r.get("core_version") for r in rs}),
                 "anchor_setting": sorted({json.dumps(r.get("anchor_setting"), sort_keys=True) for r in rs}),
                 "floored": [t["task_id"] for t in tasks if (t.get("refs") or {}).get("floored")],
                 "c_undefined": [t["task_id"] for t in tasks if (t.get("refs") or {}).get("c_undefined")],
                 "anchor_below_idle": [t["task_id"] for t in tasks
                                       if t.get("refs") and t["refs"]["p_anchor"] < t["refs"]["p_idle"]]}
    report = Path(refs_path).with_name("refs-report.json")
    if report.exists():
        m["refs_report"] = json.loads(report.read_text())
    (root / "manifest.json").write_text(json.dumps(m, indent=1))
    return n


if __name__ == "__main__":
    print(merge_refs(sys.argv[1], sys.argv[2]))
