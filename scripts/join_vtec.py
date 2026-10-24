"""NWS watches, warnings and advisories (VTEC) for the GridSimEnv regions, from the Iowa Environmental Mesonet archive.

One request per year (IEM's vtec_events_bystate, one row per VTEC event, so CON/EXT/EXP/CAN updates are already folded),
at IEM's robots.txt crawl delay of 120 s, cached under cache/raw/notices/iem/. Writes data/notices/nws_vtec.jsonl: one
row per (event, region) for the weather phenomena a battery desk cares about, in the counties that stand for each
region of gridsim_core.task.REGIONS.

python scripts/join_vtec.py [--years 2019-2026] [--no-fetch]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notice_fetch import cache_path, fetch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "notices"
URL = "https://mesonet.agron.iastate.edu/json/vtec_events_bystate.py?state=TX&year={y}"
CRAWL_DELAY = 120

# Counties whose weather stands for each region (weather proxies, not ERCOT zone membership; the Panhandle hub's wind
# sits in ERCOT counties east of Amarillo, but Amarillo's zones carry the regional winter and heat products).
REGION_COUNTIES = {
    "west": ["Midland", "Ector", "Tom Green", "Taylor", "Howard"],
    "panhandle": ["Potter", "Randall", "Gray", "Carson", "Wilbarger"],
    "north": ["Dallas", "Tarrant", "Collin", "Denton", "Grayson"],
    "houston": ["Harris", "Fort Bend", "Montgomery", "Brazoria", "Galveston"],
    "south": ["Bexar", "Nueces", "Hidalgo", "Cameron", "Webb"],
    "central": ["Travis", "Williamson", "Hays", "Bastrop", "McLennan"],
}
# phenomena code -> name; IEM names are kept as given, these are the ones a battery desk acts on.
PHENOMENA = {
    "HT": "Heat",
    "EH": "Excessive Heat",
    "XH": "Extreme Heat",
    "WS": "Winter Storm",
    "WW": "Winter Weather",
    "BZ": "Blizzard",
    "IS": "Ice Storm",
    "ZR": "Freezing Rain",
    "WC": "Wind Chill",
    "EC": "Extreme Cold",
    "CW": "Cold Weather",
    "HZ": "Hard Freeze",
    "FZ": "Freeze",
    "SV": "Severe Thunderstorm",
    "TO": "Tornado",
    "HU": "Hurricane",
    "TR": "Tropical Storm",
    "SS": "Storm Surge",
    "HW": "High Wind",
    "EW": "Extreme Wind",
    "DS": "Dust Storm",
}
KEEP_SIG = {"W", "A", "Y"}
MARINE = re.compile(r"\b(Island|Islands|Peninsula|Bay|Waters|Coastal Waters|Offshore|nm|Gulf)\b")


def fetch_year(y: int, do_fetch: bool) -> list[dict]:
    url = URL.format(y=y)
    p = cache_path(url, "iem")
    if not p.exists() and not do_fetch:
        return []
    body = fetch(url, "iem", delay=CRAWL_DELAY)[0]
    return json.loads(body)["events"]


def regions_of(locations: str) -> dict[str, list[str]]:
    names = [re.sub(r"\s*\[TX\]\s*$", "", s.strip()) for s in locations.split(",") if s.strip().endswith("[TX]")]
    hit: dict[str, list[str]] = {}
    for region, counties in REGION_COUNTIES.items():
        for c in counties:
            pat = re.compile(rf"\b{re.escape(c)}\b")
            if any(pat.search(n) and not MARINE.search(n) for n in names):
                hit.setdefault(region, []).append(c)
    return hit


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", default="2019-2026")
    ap.add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    y0, y1 = map(int, a.years.split("-"))
    rows, seen = [], Counter()
    for y in range(y0, y1 + 1):
        evs = fetch_year(y, not a.no_fetch)
        seen[y] = len(evs)
        for e in evs:
            if e["phenomena"] not in PHENOMENA or e["significance"] not in KEEP_SIG:
                continue
            hit = regions_of(e.get("locations") or "")
            for region, counties in sorted(hit.items()):
                rows.append(
                    {
                        "notice_id": f"VTEC-{e['wfo']}-{e['phenomena']}.{e['significance']}-{y}-"
                        f"{e['eventid']:04d}-{region}",
                        "source": "NWS",
                        "channel": "nws_vtec",
                        "region": region,
                        "phenomena": e["phenomena"],
                        "significance": e["significance"],
                        "name": f"{e['ph_name']} {e['sig_name']}",
                        "issued_at_utc": e.get("product_issue") or e["issue"],
                        "effective_from_utc": e["issue"],
                        "expires_at_utc": e["expire"],
                        "init_expire_utc": e.get("init_expire"),
                        "wfo": e["wfo"],
                        "eventid": e["eventid"],
                        "year": y,
                        "counties": counties,
                        "n_locations": len((e.get("locations") or "").split(",")),
                        "area_km2": e.get("area"),
                        "url": "https://mesonet.agron.iastate.edu" + e["uri"],
                        "timestamp_quality": "minute",
                    }
                )
    rows.sort(key=lambda r: (r["issued_at_utc"], r["notice_id"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "nws_vtec.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    print(len(rows), dict(seen))


if __name__ == "__main__":
    main()
