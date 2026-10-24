"""Fetch ERCOT's own forecast vintages (NP3-565-CD load, NP4-732-CD and NP4-742-CD wind, NP4-745-CD solar) as posted,
through the ERCOT public API archive (docs/CONTRACT-v4.md, V4-P17), into cache/forecast/ercot/raw/{report}/.

Lists every posting from 2023-12-11 (the API's archive start) through the archive listing, then downloads the CSV
documents with the bulk archive download (up to 1,000 documents a request), at most ~12 requests a minute (the key
is shared). A second failed login stops the run, so a bad password cannot lock the account. The listing
pages and the bulk zips are kept as fetched, so a stopped run resumes and the store builds from them alone. The
subscription key and the login come from SSM (us-west-2) inside this process and are never printed or written."""

from __future__ import annotations

import argparse
import datetime as dt
import io
import json
import subprocess
import time
import zipfile
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.ercot.com/api/public-reports"
TOKEN_URL = ("https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token")
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"
REPORTS = ("np3-565-cd", "np4-732-cd", "np4-742-cd", "np4-745-cd")
SSM = {"key": "/gridsim/ercot-api-key", "username": "/gridsim/ercot-username", "password": "/gridsim/ercot-password"}
API_START = "2023-12-11T00:00:00"
MIN_GAP_S = 5.1
BATCH = 1000


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
                r = self.http.request(method, url, timeout=300, headers={
                    "Ocp-Apim-Subscription-Key": self.secrets["key"], "Authorization": f"Bearer {self.token}"}, **kw)
            except requests.RequestException as e:
                print(f"[ercot] {method} {url.split('?')[0]} failed ({type(e).__name__}), retry", flush=True)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 429:
                print("[ercot] 429, backing off", flush=True)
                time.sleep(max(60, int(r.headers.get("Retry-After", 60)) + 1))
                continue
            if r.status_code == 401:
                self.token = None
                continue
            if r.status_code >= 500:
                time.sleep(10 * (attempt + 1))
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"{method} {url.split('?')[0]} kept failing")


def list_report(c: Client, report: str, out: Path, end: str) -> list[dict]:
    d = out / report / "listing"
    d.mkdir(parents=True, exist_ok=True)
    stamp = d / f"done-{end.replace(':', '')}.json"
    if stamp.exists():
        return json.loads(stamp.read_text())
    docs, page = [], 1
    while True:
        r = c.request("GET", f"{API}/archive/{report}", params={
            "postDatetimeFrom": API_START, "postDatetimeTo": end, "size": BATCH, "page": page})
        (d / f"page-{page:04d}.json").write_bytes(r.content)
        body = r.json()
        docs += body.get("archives", [])
        total = body["_meta"]["totalPages"]
        print(f"[ercot] {report} listing page {page}/{total}: {len(docs)} docs", flush=True)
        if page >= total:
            break
        page += 1
    stamp.write_text(json.dumps(docs))
    return docs


def download(c: Client, report: str, docs: list[dict], out: Path):
    d = out / report / "bulk"
    d.mkdir(parents=True, exist_ok=True)
    csv = sorted((x for x in docs if x["friendlyName"].lower().endswith("csv")), key=lambda x: x["docId"])
    have = set()
    for f in d.glob("*.json"):
        have.update(json.loads(f.read_text()))
    todo = [x["docId"] for x in csv if x["docId"] not in have]
    print(f"[ercot] {report}: {len(csv)} csv docs, {len(todo)} to fetch", flush=True)
    for i in range(0, len(todo), BATCH):
        ids = todo[i:i + BATCH]
        name = f"{ids[0]:012d}_{ids[-1]:012d}"
        r = c.request("POST", f"{API}/archive/{report}/download", json={"docIds": ids})
        (d / f"{name}.zip").write_bytes(r.content)
        (d / f"{name}.json").write_text(json.dumps(ids))
        print(f"[ercot] {report} bulk {i + len(ids)}/{len(todo)}: {len(r.content) / 1e6:.1f} MB", flush=True)


def spot(c: Client, report: str, posted_from: str, posted_to: str, out: Path):
    """Fetch the postings in [from, to] (ERCOT local) one by one, for the archive-vs-API spot check."""
    d = out / "spot"
    d.mkdir(parents=True, exist_ok=True)
    r = c.request("GET", f"{API}/archive/{report}", params={"postDatetimeFrom": posted_from,
                                                            "postDatetimeTo": posted_to, "size": 50})
    for doc in r.json().get("archives", []):
        if not doc["friendlyName"].lower().endswith("csv"):
            continue
        body = c.request("GET", f"{API}/archive/{report}", params={"download": doc["docId"]}).content
        stamp = doc["postDatetime"].replace(":", "").replace("-", "")[:15]
        (d / f"{report}_{stamp}_{doc['docId']}.zip").write_bytes(body)
        z = zipfile.ZipFile(io.BytesIO(body))
        inner = z.read(z.namelist()[0])
        if inner[:2] == b"PK":
            iz = zipfile.ZipFile(io.BytesIO(inner))
            inner = iz.read(iz.namelist()[0])
        (d / f"{report}_{stamp}_{doc['docId']}.csv").write_bytes(inner)
        print(f"[ercot] spot {report} {doc['postDatetime']} doc {doc['docId']}: {len(inner)} bytes", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(ROOT / "cache" / "forecast" / "ercot" / "raw"))
    ap.add_argument("--end", default=dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT00:00:00"),
                    help="postDatetimeTo (ERCOT local time)")
    ap.add_argument("--reports", default=",".join(REPORTS))
    ap.add_argument("--probe", action="store_true", help="list one page of five documents per report and stop")
    ap.add_argument("--spot", nargs=3, metavar=("REPORT", "FROM", "TO"),
                    help="fetch the postings of REPORT posted in [FROM, TO] (local) into OUT/../spot and stop")
    args = ap.parse_args()
    out, c = Path(args.out), Client()
    t0 = time.time()
    if args.spot:
        spot(c, args.spot[0], args.spot[1], args.spot[2], out.parent)
        return
    for report in args.reports.split(","):
        if args.probe:
            r = c.request("GET", f"{API}/archive/{report}", params={"postDatetimeFrom": API_START, "size": 5})
            print(json.dumps(r.json())[:1500])
            continue
        download(c, report, list_report(c, report, out, args.end), out)
    print(f"[ercot] done: {c.calls} requests in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
