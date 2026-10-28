"""Fetch ERCOT's 60-Day DAM Disclosure (NP3-966-ER), the DAM system lambda (NP4-523-CD) and, optionally, the 60-Day SCED
Disclosure (NP3-965-ER) for every operating day in the public API archive, into cache/disclosure/ (docs/CONTRACT-v5.md).

One disclosure document per op day, posted on op day + 60 days. Each is kept as fetched at raw/<report>/<op_date>.zip
(never shipped), its op day checked against the Delivery Date inside; raw/<report>/index.jsonl holds docId,
postDatetime, size and sha256. Bulk archive downloads, at most ~11 requests a minute (the key is shared with other
pulls); a second failed login stops the run so a bad password cannot lock the account. The subscription key and the
login come from SSM (us-west-2) inside this process and are never printed or written."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import io
import json
import re
import subprocess
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.ercot.com/api/public-reports"
TOKEN_URL = "https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token"
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
SSM = {"key": "/gridsim/ercot-api-key", "username": "/gridsim/ercot-username", "password": "/gridsim/ercot-password"}
LAG_DAYS = {"np3-966-er": 60, "np3-965-er": 60, "np4-523-cd": -1}
FRIENDLY = {"np3-966-er": "60_Day_DAM_Disclosure", "np3-965-er": "60_Day_SCED_Disclosure"}
PROBE = {"np3-966-er": "60d_DAM_Gen_Resource_Data", "np3-965-er": "60d_SCED_EOC_Updates_in_OpHour"}
MIN_GAP_S = 5.4


def ssm(name: str) -> str:
    r = subprocess.run(["aws", "ssm", "get-parameter", "--region", "us-west-2", "--name", name, "--with-decryption",
                        "--query", "Parameter.Value", "--output", "text"], capture_output=True, text=True, check=True)
    return r.stdout.strip()


class Client:
    def __init__(self):
        self.secrets = {k: ssm(v) for k, v in SSM.items()}
        self.http = requests.Session()
        self.token, self.token_at, self.last = None, 0.0, 0.0
        self.calls, self.login_failures = 0, 0

    def _login(self):
        try:
            r = requests.post(TOKEN_URL, timeout=60, data={
                "username": self.secrets["username"], "password": self.secrets["password"], "grant_type": "password",
                "scope": f"openid {CLIENT_ID} offline_access", "client_id": CLIENT_ID, "response_type": "id_token"})
            r.raise_for_status()
            self.token, self.token_at = r.json()["id_token"], time.time()
        except (requests.RequestException, KeyError, ValueError) as e:
            self.login_failures += 1
            status = getattr(getattr(e, "response", None), "status_code", None)
            if self.login_failures >= 2:
                raise SystemExit(f"[ercot] login failed twice (last: {type(e).__name__} {status}); stopping") from None
            print(f"[ercot] login failed ({type(e).__name__} {status}); one retry in 60 s", flush=True)
            time.sleep(60)
            self._login()

    def request(self, method: str, url: str, **kw) -> requests.Response:
        for attempt in range(8):
            if self.token is None or time.time() - self.token_at > 3000:
                self._login()
            wait = self.last + MIN_GAP_S - time.time()
            if wait > 0:
                time.sleep(wait)
            self.last = time.time()
            self.calls += 1
            try:
                r = self.http.request(method, url, timeout=900, headers={
                    "Ocp-Apim-Subscription-Key": self.secrets["key"], "Authorization": f"Bearer {self.token}"}, **kw)
            except requests.RequestException as e:
                print(f"[ercot] {method} {url.split('?')[0]} failed ({type(e).__name__}), retry", flush=True)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                print("[ercot] 429, backing off", flush=True)
                time.sleep(max(60, int(r.headers.get("Retry-After") or 60) + 1))
                continue
            if r.status_code == 401:
                self.token = None
                continue
            if r.status_code >= 500:
                print(f"[ercot] {r.status_code} on {url.split('?')[0]}, retry", flush=True)
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"{method} {url.split('?')[0]} kept failing")


def list_archive(c: Client, report: str, out: Path, start: str, end: str) -> list[dict]:
    d = out / "listing" / report
    d.mkdir(parents=True, exist_ok=True)
    docs, page = [], 1
    while True:
        r = c.request("GET", f"{API}/archive/{report}", params={
            "postDatetimeFrom": start, "postDatetimeTo": end, "size": 1000, "page": page})
        (d / f"page-{page:04d}.json").write_bytes(r.content)
        body = r.json()
        docs += body.get("archives", [])
        if page >= body["_meta"]["totalPages"]:
            break
        page += 1
    print(f"[ercot] {report}: {len(docs)} documents posted {start[:10]}..{end[:10]}", flush=True)
    return docs


def op_day(report: str, doc: dict) -> str:
    return (dt.date.fromisoformat(doc["postDatetime"][:10]) - dt.timedelta(days=LAG_DAYS[report])).isoformat()


def wanted(report: str, docs: list[dict], first: str, last: str) -> dict[str, dict]:
    """Disclosure reports: the latest posting per op day. NP4-523-CD: every document (its CSV carries the date)."""
    by_op: dict[str, dict] = {}
    for doc in sorted(docs, key=lambda x: x["postDatetime"]):
        if report in FRIENDLY and doc["friendlyName"] != FRIENDLY[report]:
            continue
        op = op_day(report, doc)
        if first <= op <= last:
            by_op[op if report in FRIENDLY else f"{op}_{doc['docId']}"] = doc
    return by_op


def delivery_date(raw: bytes, report: str) -> str | None:
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = next((n for n in z.namelist() if n.startswith(PROBE.get(report, "\0"))), None)
    if name is None:
        return None
    with z.open(name) as f:
        r = csv.DictReader(io.TextIOWrapper(f, "utf-8", newline=""))
        row = next(r, None)
    if row is None:
        return None
    m, d, y = row["Delivery Date"][:10].split("/")
    return f"{y}-{m}-{d}"


def bulk(c: Client, report: str, ids: list[int]) -> dict[int, bytes]:
    r = c.request("POST", f"{API}/archive/{report}/download", json={"docIds": ids})
    z = zipfile.ZipFile(io.BytesIO(r.content))
    got = {}
    for name in z.namelist():
        m = re.match(r"(\d+)", Path(name).name)
        if m and int(m.group(1)) in ids:
            got[int(m.group(1))] = z.read(name)
    missing = set(ids) - set(got)
    if missing:
        raise RuntimeError(f"{report} bulk response lacks {len(missing)} of {len(ids)} docIds: {sorted(missing)[:5]}")
    return got


def fetch(c: Client, report: str, by_op: dict[str, dict], out: Path, batch: int):
    d = out / "raw" / report
    d.mkdir(parents=True, exist_ok=True)
    index = d / "index.jsonl"
    todo = [op for op in sorted(by_op) if not (d / f"{op}.zip").exists()]
    print(f"[ercot] {report}: {len(by_op)} op days wanted, {len(todo)} to fetch", flush=True)
    i = 0
    while i < len(todo):
        ops = todo[i:i + batch]
        t0 = time.time()
        try:
            docs = bulk(c, report, [by_op[op]["docId"] for op in ops])
        except requests.HTTPError as e:
            m = re.search(r"maximum number allowed .*\((\d+)\)", e.response.text)
            if e.response.status_code != 400 or not m:
                raise
            batch = int(m.group(1))
            print(f"[ercot] {report}: bulk limit {batch} documents", flush=True)
            continue
        rows, size = [], 0
        for op in ops:
            doc, raw = by_op[op], docs[by_op[op]["docId"]]
            real = delivery_date(raw, report) if report in PROBE else op
            if real is not None and real != op:
                print(f"[ercot] {report} doc {doc['docId']} holds {real}, not {op}", flush=True)
                op = real
            (d / f"{op}.zip").write_bytes(raw)
            size += len(raw)
            rows.append({"op_date": op, "docId": doc["docId"], "friendlyName": doc["friendlyName"],
                         "postDatetime": doc["postDatetime"], "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest()})
        with index.open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
        i += len(ops)
        print(f"[ercot] {report} {i}/{len(todo)} ({ops[0]}..{ops[-1]}): {size / 1e6:.0f} MB in {time.time() - t0:.0f}s",
              flush=True)


def lambda_jsonl(out: Path):
    rows = {}
    for p in sorted((out / "raw" / "np4-523-cd").glob("*.zip")):
        raw = p.read_bytes()
        if zipfile.is_zipfile(io.BytesIO(raw)):
            z = zipfile.ZipFile(io.BytesIO(raw))
            texts = [z.read(n).decode() for n in z.namelist()]
        else:
            texts = [raw.decode()]
        for text in texts:
            for row in csv.DictReader(io.StringIO(text)):
                m, d, y = row["DeliveryDate"].split("/")
                he = int(row["HourEnding"].split(":")[0])
                dst = row.get("DSTFlag", "N") == "Y"
                rows[(f"{y}-{m}-{d}", he, dst)] = float(row["SystemLambda"])
    with (out / "np4-523.jsonl").open("w") as f:
        for (date, he, dst), lam in sorted(rows.items()):
            f.write(json.dumps({"date": date, "he": he, "dst": dst, "lambda": lam}) + "\n")
    print(f"[ercot] np4-523.jsonl: {len(rows)} hours, {len({k[0] for k in rows})} days", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "cache" / "disclosure"))
    ap.add_argument("--first", default="2023-12-11", help="first op day")
    ap.add_argument("--last", default=dt.date.today().isoformat(), help="last op day")
    ap.add_argument("--reports", default="np3-966-er,np4-523-cd")
    ap.add_argument("--batch", type=int, default=25, help="documents per bulk download (NP3-966-ER allows 25)")
    args = ap.parse_args()
    out, c = Path(args.out), Client()
    t0 = time.time()
    for report in args.reports.split(","):
        lag = LAG_DAYS[report]
        start = (dt.date.fromisoformat(args.first) + dt.timedelta(days=lag - 1)).isoformat() + "T00:00:00"
        end = (dt.date.fromisoformat(args.last) + dt.timedelta(days=lag + 2)).isoformat() + "T00:00:00"
        by_op = wanted(report, list_archive(c, report, out, start, end), args.first, args.last)
        fetch(c, report, by_op, out, args.batch if report != "np4-523-cd" else 1000)
        if report == "np4-523-cd":
            lambda_jsonl(out)
    print(f"[ercot] done: {c.calls} requests in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
