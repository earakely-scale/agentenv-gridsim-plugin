"""ERCOT public API access for the desk data pipeline (docs/desk-data.md): paged report queries and archive bulk
downloads through fetch_disclosure.Client (credentials from SSM, never printed or written). Raw responses are cached
under the scratchpad raw dir ($DESK_RAW), never in git."""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
import re
import sys
import zipfile
from pathlib import Path

os.environ["AWS_PROFILE"] = os.environ.get("DESK_AWS_PROFILE", "agent-environments-admin")
sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_disclosure as FD  # noqa: E402

API = FD.API
RAW = Path(os.environ.get(
    "DESK_RAW",
    "/private/tmp/claude-502/-Users-edgar-arakelyan-agent-env/720d667c-6230-4b0f-8e7a-8181257c53ff/scratchpad/gridsim/desk/raw"))
FD.MIN_GAP_S = float(os.environ.get("DESK_API_GAP", "4.5"))
_client: FD.Client | None = None


def client() -> FD.Client:
    global _client
    if _client is None:
        _client = FD.Client()
    return _client


def _key(parts: dict) -> str:
    return hashlib.sha1(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:16]


def product(emil: str) -> dict:
    p = RAW / "meta" / f"{emil}.json"
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(client().request("GET", f"{API}/{emil}").content)
    return json.loads(p.read_text())


def query(path: str, params: dict, size: int = 50000) -> tuple[list[str], list[list]]:
    """GET /{path} with params, all pages; cached as gzip JSON per (path, params)."""
    p = RAW / "query" / path.replace("/", "__") / f"{_key(params)}.json.gz"
    if p.exists():
        j = json.loads(gzip.decompress(p.read_bytes()))
        return j["fields"], j["data"]
    rows, fields, page = [], None, 1
    while True:
        try:
            r = client().request("GET", f"{API}/{path}", params={**params, "size": size, "page": page})
        except FD.requests.HTTPError as e:
            if e.response is None or e.response.status_code != 499 or size <= 2000:
                raise
            print(f"[desk-api] {path}: 499 at size {size}, restarting with {size // 4}", flush=True)
            size, page, rows = size // 4, 1, []
            continue
        j = r.json()
        fields = [f["name"] for f in j.get("fields", [])]
        rows += j.get("data", [])
        if page >= int(j.get("_meta", {}).get("totalPages") or 1):
            break
        page += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(gzip.compress(json.dumps({"path": path, "params": params, "fields": fields, "data": rows}).encode()))
    return fields, rows


def archive_list(emil: str, start: str, end: str) -> list[dict]:
    p = RAW / "listing" / emil / f"{start[:13]}_{end[:13]}.json"
    if p.exists():
        return json.loads(p.read_text())
    docs, page = [], 1
    while True:
        r = client().request("GET", f"{API}/archive/{emil}", params={
            "postDatetimeFrom": start, "postDatetimeTo": end, "size": 1000, "page": page})
        body = r.json()
        docs += body.get("archives", [])
        if page >= body["_meta"]["totalPages"]:
            break
        page += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(docs))
    return docs


def archive_fetch(emil: str, docs: list[dict], batch: int = 1000) -> dict[int, Path]:
    """Download docs (cached at raw/archive/{emil}/{docId}.zip); returns docId -> path."""
    d = RAW / "archive" / emil
    d.mkdir(parents=True, exist_ok=True)
    out = {doc["docId"]: d / f"{doc['docId']}.zip" for doc in docs}
    todo = [i for i, p in out.items() if not p.exists()]
    while todo:
        ids = todo[:batch]
        try:
            r = client().request("POST", f"{API}/archive/{emil}/download", json={"docIds": ids})
        except FD.requests.HTTPError as e:
            m = re.search(r"maximum number allowed .*\((\d+)\)", e.response.text)
            if e.response.status_code != 400 or not m:
                raise
            batch = int(m.group(1))
            continue
        z = zipfile.ZipFile(io.BytesIO(r.content))
        got = set()
        for name in z.namelist():
            m = re.match(r"(\d+)", Path(name).name)
            if m and int(m.group(1)) in ids:
                out[int(m.group(1))].write_bytes(z.read(name))
                got.add(int(m.group(1)))
        if not got:
            raise RuntimeError(f"{emil}: bulk download returned none of {len(ids)} docs")
        todo = [i for i in todo if i not in got]
        print(f"[desk-api] {emil}: {len(out) - len(todo)}/{len(out)} docs", flush=True)
    return out


def read_zip_csv(path: Path, prefix: str | None = None):
    import pandas as pd
    z = zipfile.ZipFile(path)
    names = [n for n in z.namelist() if prefix is None or Path(n).name.startswith(prefix)]
    frames = []
    for n in names:
        raw = z.read(n)
        if n.endswith(".zip"):
            zz = zipfile.ZipFile(io.BytesIO(raw))
            raw = zz.read(zz.namelist()[0])
        frames.append(pd.read_csv(io.BytesIO(raw), low_memory=False))
    return pd.concat(frames, ignore_index=True) if frames else None
