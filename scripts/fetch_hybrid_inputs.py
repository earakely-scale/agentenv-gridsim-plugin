"""Download v3's raw inputs into cache/raw/hybrid/: ERCOT MIS reports by report type id (doc list, then yearly or daily
zips), ERCOT's yearly fuel-mix workbooks and EIA-860M. One request per second per host, a named user agent, every
body cached, and cache/raw/hybrid/sources.json records url, bytes and sha256 per file."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "cache" / "raw" / "hybrid"
UA = ("ScaleAI-GridSimEnv-research/0.1 (+https://github.com/earakely-scale/agentenv-gridsim-plugin; "
      "edgar.arakelyan@scale.com)")
ERCOT = "https://www.ercot.com"
DOCLIST = ERCOT + "/misapp/servlets/IceDocListJsonWS?reportTypeId={}"
DOWNLOAD = ERCOT + "/misdownload/servlets/mirDownload?doclookupId={}"
YEARS = range(2021, 2027)
MIS = {
    "dam_mcpc_yearly": {"product": "NP4-181-ER", "rtid": 13091, "prefix": "DAMASMCPC_"},
    "rt_adders_yearly": {"product": "NP6-793-ER", "rtid": 13240, "prefix": "HIST_RT15MPRICEADDER_"},
    "wind_solar_yearly": {"product": "PG7-126-M", "rtid": 13424, "prefix": "ERCOT_",
                          "suffix": "_Hourly_WindSolar_Output"},
}
FILES = {
    "fuel_mix/FuelMixReport_PreviousYears.zip": ERCOT + "/files/docs/2021/03/10/FuelMixReport_PreviousYears.zip",
    "fuel_mix/IntGenbyFuel2026.xlsx": ERCOT + "/files/docs/2026/02/09/IntGenbyFuel2026.xlsx",
    "nprr/1186NPRR-36_PUCT_Report_041124.docx":
        ERCOT + "/files/docs/2024/04/12/1186NPRR-36%20PUCT%20Report%20041124.docx",
    "eia860m/september_generator2026.xlsx":
        "https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx",
}
DAILY_TAIL = {"key": "dam_mcpc_daily", "product": "NP4-188-CD", "rtid": 12329, "suffix": "_csv",
              "after": "dam_mcpc_yearly"}
SAMPLES = {
    "np4_745/PVGR_20261024_0655.zip": ("NP4-745-CD", 21809, 1290252298),
    "np6_331/MCPC15Min_20261024_0717.zip": ("NP6-331-CD", 24898, 1290257737),
}
_last: dict[str, float] = {}


def fetch(url: str, dest: Path, *, delay: float = 1.0, retries: int = 4) -> bytes:
    if dest.exists():
        return dest.read_bytes()
    dest.parent.mkdir(parents=True, exist_ok=True)
    host = url.split("/")[2]
    for attempt in range(retries):
        wait = _last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=120) as r:
                body = r.read()
            dest.write_bytes(body)
            print(f"fetched {dest.relative_to(RAW)} ({len(body)} B)", flush=True)
            return body
        except urllib.error.HTTPError as e:
            if e.code not in (429, 500, 502, 503, 504):
                raise
            print(f"HTTP {e.code} on {url}; backing off", file=sys.stderr, flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            print(f"{e!r} on {url}; backing off", file=sys.stderr, flush=True)
        time.sleep(10 * 2**attempt)
    raise RuntimeError(f"gave up on {url}")


def doclist(rtid: int, *, refresh: bool = False) -> list[dict]:
    dest = RAW / "lists" / f"{rtid}.json"
    if refresh and dest.exists():
        dest.unlink()
    body = json.loads(fetch(DOCLIST.format(rtid), dest))
    return [d["Document"] for d in body["ListDocsByRptTypeRes"].get("DocumentList", [])]


def mis_yearly(key: str, sources: dict) -> None:
    spec = MIS[key]
    for d in doclist(spec["rtid"], refresh=True):
        name = d["FriendlyName"]
        year = name.removeprefix(spec["prefix"]).removesuffix(spec.get("suffix", ""))
        if not name.startswith(spec["prefix"]) or not year.isdigit() or int(year) not in YEARS:
            continue
        url = DOWNLOAD.format(d["DocID"])
        dest = RAW / key / f"{name}{Path(d['ConstructedName']).suffix}"
        record(sources, dest, url, product=spec["product"], rtid=spec["rtid"], published=d["PublishDate"])
        fetch(url, dest)


def mis_daily_tail(sources: dict) -> None:
    """The daily NP4-188-CD csvs published since the in-year NP4-181-ER file (one day before its publish date)."""
    yearly = [v["published"] for k, v in sources.items() if k.startswith(DAILY_TAIL["after"] + "/")]
    since = (dt.date.fromisoformat(max(yearly)[:10]) - dt.timedelta(days=1)).isoformat()
    for d in doclist(DAILY_TAIL["rtid"], refresh=True):
        if d["FriendlyName"].endswith(DAILY_TAIL["suffix"]) and d["PublishDate"][:10] >= since:
            dest = RAW / DAILY_TAIL["key"] / d["ConstructedName"]
            url = DOWNLOAD.format(d["DocID"])
            record(sources, dest, url, product=DAILY_TAIL["product"], rtid=DAILY_TAIL["rtid"],
                   published=d["PublishDate"])
            fetch(url, dest)


def record(sources: dict, dest: Path, url: str, **meta) -> None:
    sources[str(dest.relative_to(RAW))] = {"url": url, **meta}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", default=None)
    args = ap.parse_args()
    manifest = RAW / "sources.json"
    sources = json.loads(manifest.read_text()) if manifest.exists() else {}
    for key in MIS:
        if args.only is None or key in args.only:
            mis_yearly(key, sources)
    if args.only is None or DAILY_TAIL["key"] in args.only:
        mis_daily_tail(sources)
    for rel, (product, rtid, doc) in SAMPLES.items():
        if (RAW / rel).exists() and rel not in sources:
            record(sources, RAW / rel, DOWNLOAD.format(doc), product=product, rtid=rtid,
                   note="layout sample; MIS keeps ~7 days")
    for rel, url in FILES.items():
        if args.only is None or rel.split("/")[0] in args.only:
            record(sources, RAW / rel, url)
            fetch(url, RAW / rel)
    for rel, row in sources.items():
        p = RAW / rel
        if p.exists():
            row.update(bytes=p.stat().st_size, sha256=sha256(p))
    manifest.write_text(json.dumps(dict(sorted(sources.items())), indent=1) + "\n")


if __name__ == "__main__":
    main()
