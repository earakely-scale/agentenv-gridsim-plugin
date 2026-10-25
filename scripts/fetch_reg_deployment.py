"""Fetch ERCOT's 60-Day SCED Disclosure (NP3-965-ER) through the public API archive and reduce each operating day to
the energy storage fleet's regulation deployment per disclosed SCED snapshot, into cache/raw/hybrid/sced60/days/.

The archive starts with postings on 2023-12-11 (operating days from 2023-10-12). Each posting is one operating day's zip
(~9 MB); it is downloaded in bulk batches, reduced, and dropped, keeping its docId, size and sha256 in the day file.
Per snapshot (one SCED run per 15 minutes is disclosed) the reducer sums, over regulation carriers (RegUp or RegDn
responsibility > 0): the deviation from base point (telemetered net output - base point for generation-side and
single-model ESRs; consumption - base point for the charging-side Controllable Load Resources before RTC+B, sign
flipped so + is up) and the responsibilities; online non-carrier ESRs are summed as a control. Login and
rate rules are fetch_ercot_vintages': SSM secrets read in-process, ~12 requests a minute at most, two failed logins
stop the run."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import multiprocessing as mp
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_ercot_vintages as api  # noqa: E402

REPORT = "np3-965-er"
OUT = ROOT / "cache" / "raw" / "hybrid" / "sced60"
BATCH = 10
ESR_TYPES = ("PWRSTR", "ESR")


def num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _rows(z: zipfile.ZipFile, part: str, needle: bytes | None = None):
    """A disclosure file's rows as dicts of the columns named in COLS, skipping lines without `needle`."""
    names = [n for n in z.namelist() if part in n]
    if not names:
        return None

    def gen():
        with z.open(names[0]) as f:
            head = next(csv.reader([f.readline().decode("utf-8-sig")]))
            ix = {h.strip(): i for i, h in enumerate(head) if h.strip() in COLS}
            for line in f:
                if needle is None or needle in line:
                    r = next(csv.reader([line.decode()]))
                    yield {k: r[i] for k, i in ix.items()}

    return gen()


def _resp(r: dict, product: str) -> float:
    return max(num(r.get(f"Ancillary Service {product}")), num(r.get(f"AS Awards {product}")))


COLS = {"SCED Time Stamp", "Repeated Hour Flag", "Resource Name", "Resource Type", "Telemetered Resource Status",
        "Base Point", "Telemetered Net Output", "Real Power Consumption", "AS Responsibility for RegUp",
        "AS Responsibility for RegDown", "Ancillary Service REGUP", "Ancillary Service REGDN", "AS Awards REGUP",
        "AS Awards REGDN"}


def _order(key: str) -> tuple:
    m, d, y = key[:10].split("/")
    return y, m, d, key[11:13], key.endswith("R"), key[14:19]


def reduce_day(blob: bytes) -> dict:
    """One operating day's disclosed SCED snapshots, in time order: {t: {"esr": [tno, bp, bp1, bp3, ru, rd, pos, neg,
    n], "ctrl": [tno, bp, bp1, n]}}. MW, oriented up (a charging CLR's
    consumption counts negative); bp1 and bp3 are the resource's base points one and three disclosed snapshots
    earlier (its own bp when it has none); pos/neg count carriers more than 0.5 MW above/below bp1."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    res: dict[str, list] = {}
    fmt = []
    single = any("ESR_Data" in n for n in z.namelist())
    parts = (("ESR_Data", "esr", None),) if single else (("Gen_Resource_Data", "gen", b"PWRSTR"),
                                                           ("Load_Resource_Data", "clr", None))
    for part, kind, needle in parts:
        rows = _rows(z, part, needle)
        if rows is None:
            continue
        fmt.append(kind)
        for r in rows:
            key = r["SCED Time Stamp"] + ("R" if str(r.get("Repeated Hour Flag", "N")).upper()[:1] in "YT" else "")
            if kind == "clr":
                ru, rd = num(r.get("AS Responsibility for RegUp")), num(r.get("AS Responsibility for RegDown"))
                if ru <= 0 and rd <= 0:
                    continue
                cls, tno, bp = "esr", -num(r.get("Real Power Consumption")), -num(r.get("Base Point"))
            else:
                ru, rd = _resp(r, "REGUP"), _resp(r, "REGDN")
                tno, bp = num(r.get("Telemetered Net Output")), num(r.get("Base Point"))
                if kind != "esr" and r.get("Resource Type") not in ESR_TYPES:
                    continue
                online = str(r.get("Telemetered Resource Status", "")).upper() not in ("OFF", "OUT", "OFFNS", "")
                cls = "esr" if ru > 0 or rd > 0 else "ctrl" if online else None
            res.setdefault(f"{kind}|{r['Resource Name']}", []).append((key, cls, tno, bp, ru, rd))
    keys = sorted({x[0] for v in res.values() for x in v}, key=_order)
    idx = {k: i for i, k in enumerate(keys)}
    snaps = {k: {"esr": [0.0] * 6 + [0, 0, 0], "ctrl": [0.0] * 3 + [0]} for k in keys}
    for rows in res.values():
        rows.sort(key=lambda x: idx[x[0]])
        at = {idx[x[0]]: x[3] for x in rows}
        for key, cls, tno, bp, ru, rd in rows:
            if cls is None:
                continue
            i = idx[key]
            bp1, bp3 = at.get(i - 1, bp), at.get(i - 3, bp)
            s = snaps[key][cls]
            if cls == "esr":
                for j, v in enumerate((tno, bp, bp1, bp3, ru, rd)):
                    s[j] += v
                s[6] += tno - bp1 > 0.5
                s[7] += tno - bp1 < -0.5
                s[8] += 1
            else:
                for j, v in enumerate((tno, bp, bp1)):
                    s[j] += v
                s[3] += 1
    for s in snaps.values():
        for k in s:
            s[k] = [round(x, 3) if isinstance(x, float) else x for x in s[k]]
    return {"format": "+".join(fmt), "snapshots": snaps}


def op_date(snaps: dict) -> str:
    days = sorted({k[:10] for k in snaps})
    m, d, y = days[len(days) // 2].split("/")
    return f"{y}-{m}-{d}"


def _work(item):
    doc, post, blob = item
    red = reduce_day(blob)
    date = op_date(red["snapshots"])
    return {"date": date, "doc_id": doc, "post_datetime": post, "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(), "source": "ERCOT public API, NP3-965-ER 60-Day SCED "
            "Disclosure Reports (archive)", **red}


def listing(c: api.Client, end: str) -> list[dict]:
    d = OUT / "listing"
    d.mkdir(parents=True, exist_ok=True)
    stamp = d / f"done-{end.replace(':', '')}.json"
    if stamp.exists():
        return json.loads(stamp.read_text())
    docs, page = [], 1
    while True:
        r = c.request("GET", f"{api.API}/archive/{REPORT}", params={
            "postDatetimeFrom": api.API_START, "postDatetimeTo": end, "size": 1000, "page": page})
        body = r.json()
        docs += body.get("archives", [])
        if page >= body["_meta"]["totalPages"]:
            break
        page += 1
    stamp.write_text(json.dumps(docs))
    return docs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--end", default=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT00:00:00"))
    ap.add_argument("--from-post", default="2023-12-11", help="first posting date to fetch")
    ap.add_argument("--to-post", default="9999", help="last posting date to fetch")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--gap", type=float, default=6.0, help="seconds between API requests")
    args = ap.parse_args()
    api.MIN_GAP_S = max(api.MIN_GAP_S, args.gap)
    days = OUT / "days"
    days.mkdir(parents=True, exist_ok=True)
    have = {json.loads(gzip.open(p, "rt").read())["doc_id"] for p in days.glob("*.json.gz")}
    c = api.Client()
    docs = [x for x in listing(c, args.end) if args.from_post <= x["postDatetime"][:10] <= args.to_post
            and x["docId"] not in have]
    docs.sort(key=lambda x: x["postDatetime"])
    if args.limit:
        docs = docs[:args.limit]
    post = {x["docId"]: x["postDatetime"] for x in docs}
    print(f"[sced60] {len(docs)} postings to fetch ({len(have)} done)", flush=True)
    t0 = time.time()
    def save(row):
        with gzip.open(days / f"{row['date']}.json.gz", "wt") as f:
            f.write(json.dumps(row, separators=(",", ":")))

    with mp.Pool(args.workers) as pool:
        pending = []
        for i in range(0, len(docs), BATCH):
            ids = [x["docId"] for x in docs[i:i + BATCH]]
            r = c.request("POST", f"{api.API}/archive/{REPORT}/download", json={"docIds": ids})
            outer = zipfile.ZipFile(io.BytesIO(r.content))
            items = [(int(n.split(".")[0]), post.get(int(n.split(".")[0])), outer.read(n)) for n in outer.namelist()]
            while len(pending) > 2 * args.workers:
                pending.pop(0).wait()
            pending += [pool.apply_async(_work, (it,), callback=save) for it in items]
            print(f"[sced60] {i + len(ids)}/{len(docs)} postings, {len(r.content) / 1e6:.0f} MB, "
                  f"{time.time() - t0:.0f}s", flush=True)
        for x in pending:
            x.get()
    print(f"[sced60] done: {c.calls} requests in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
