"""Hourly weather for a (settlement point, date) from the point's representative airport: IEM ASOS observations
(routine and special METARs), cached as a sidecar per (point, date) the viewer reads.

usage: python scripts/weather.py HB_WEST 2024-04-14 [HB_HOUSTON 2024-07-18 ...] [--out cache/weather] [--force]
       python scripts/weather.py --episodes results/runs   (every (point, date) the runs use)
A v4 window gets one sidecar over its whole span (window_sidecar: d1-1 10:00 to the window end, hours from d1 00:00).
"""

import argparse
import csv
import io
import json
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
IEM = ("https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station={station}&data=all&sts={sts}T00:00Z"
       "&ets={ets}T00:00Z&tz=Etc/UTC&format=onlycomma&latlon=no&missing=empty&trace=T&report_type=3&report_type=4")
CT = ZoneInfo("America/Chicago")
AIRPORTS = {
    "MAF": ("Midland International", 31.9425, -102.2019),
    "AMA": ("Amarillo Rick Husband International", 35.2194, -101.7059),
    "DFW": ("Dallas/Fort Worth International", 32.8998, -97.0403),
    "TYR": ("Tyler Pounds Regional", 32.3541, -95.4024),
    "IAH": ("Houston George Bush Intercontinental", 29.9844, -95.3414),
    "SAT": ("San Antonio International", 29.5337, -98.4698),
    "CRP": ("Corpus Christi International", 27.7704, -97.5012),
    "AUS": ("Austin-Bergstrom International", 30.1945, -97.6699),
}
STATION = {"HB_WEST": "MAF", "LZ_WEST": "MAF", "HB_PAN": "AMA", "HB_NORTH": "DFW", "LZ_NORTH": "DFW",
           "LZ_RAYBN": "TYR", "HB_HOUSTON": "IAH", "LZ_HOUSTON": "IAH", "HB_SOUTH": "SAT", "LZ_CPS": "SAT",
           "LZ_SOUTH": "CRP", "LZ_AEN": "AUS", "LZ_LCRA": "AUS", "HB_BUSAVG": "AUS", "HB_HUBAVG": "AUS"}
COVER = {"CLR": 0.0, "SKC": 0.0, "NSC": 0.0, "FEW": 0.2, "SCT": 0.45, "BKN": 0.78, "OVC": 1.0, "VV": 1.0}
MIN_GAP_S = 1.0
LAST = [0.0]
TERMS = ("Iowa Environmental Mesonet (IEM), Iowa State University: ASOS/AWOS archive "
         "(https://mesonet.agron.iastate.edu/request/download.phtml). Public domain observations.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("pairs", nargs="*", help="POINT DATE pairs.")
    p.add_argument("--episodes", type=Path, help="A folder of Episode JSON: fetch every (point, date) they use.")
    p.add_argument("--out", type=Path, default=ROOT / "cache" / "weather")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)
    pairs = list(zip(args.pairs[::2], args.pairs[1::2], strict=True))
    if args.episodes:
        for f in sorted(args.episodes.rglob("*.json")):
            if "raw" in f.relative_to(args.episodes).parts[:-1]:
                continue
            ep = json.loads(f.read_text())
            if isinstance(ep, dict) and ep.get("schema") == "gridsim.episode/v1":
                pairs.append((ep["task"]["settlement_point"], ep["task"]["date"]))
    for point, day in dict.fromkeys(pairs):
        path = sidecar(point, day, args.out, force=args.force)
        print(f"{point} {day} -> {path}")
    return 0


def sidecar_path(out: Path, point: str, day: str) -> Path:
    return out / f"{day}_{point}.json"


def sidecar(point: str, day: str, out: Path, force: bool = False) -> Path:
    path = sidecar_path(out, point, day)
    if path.exists() and not force:
        return path
    station = STATION[point]
    raw = out / "iem" / f"{station}_{day}.csv"
    if force or not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(fetch(url(station, day)))
    path.write_text(json.dumps(build(point, day, raw.read_text()), separators=(",", ":")))
    return path


def url(station: str, day: str, days: int = 1) -> str:
    d = date.fromisoformat(day)
    return IEM.format(station=station, sts=(d - timedelta(days=1)).isoformat(),
                      ets=(d + timedelta(days=days + 1)).isoformat())


def window_sidecar(point: str, d1: str, days: int, out: Path, force: bool = False) -> Path:
    """The weather over a v4 window: observations from 16 h before d1 00:00 to 3 h after its end, t in hours from
    d1 00:00 (negative before it), and `hourly` for each window hour."""
    path = out / f"{d1}_{point}_{days}d.json"
    if path.exists() and not force:
        return path
    station = STATION[point]
    raw = out / "iem" / f"{station}_{d1}_{days}d.csv"
    if force or not raw.exists():
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(fetch(url(station, d1, days)))
    side = build(point, d1, raw.read_text(), (-16, 24 * days + 3))
    side["hourly"] = [nearest(side["obs"], he) for he in range(1, 24 * days + 1)]
    path.write_text(json.dumps(side | {"days": days}, separators=(",", ":")))
    return path


def fetch(u: str, tries: int = 4) -> str:
    """One IEM request at a time, at most one a second."""
    for i in range(tries):
        time.sleep(max(0.0, LAST[0] + MIN_GAP_S - time.monotonic()))
        LAST[0] = time.monotonic()
        try:
            req = urllib.request.Request(u, headers={"User-Agent": "agentenv-gridsim weather sidecar"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode()
        except OSError:
            if i == tries - 1:
                raise
            time.sleep(2 + 3 * i)
    raise RuntimeError(u)


def build(point: str, day: str, text: str, span: tuple[float, float] = (-3, 27)) -> dict:
    station = STATION[point]
    name, lat, lon = AIRPORTS[station]
    midnight = datetime.fromisoformat(day).replace(tzinfo=CT)
    obs = []
    for r in csv.DictReader(io.StringIO(text)):
        if not r.get("valid"):
            continue
        at = datetime.strptime(r["valid"], "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("UTC"))
        t = (at - midnight).total_seconds() / 3600
        if span[0] <= t <= span[1]:
            obs.append(observation(r, round(t, 3)))
    obs.sort(key=lambda o: o["t"])
    return {"schema": "gridsim.weather/v1", "point": point, "date": day, "tz": "America/Chicago", "station": station,
            "airport": name, "lat": lat, "lon": lon, "source": TERMS, "obs": obs,
            "hourly": [nearest(obs, he) for he in range(1, 25)]}


def observation(r: dict, t: float) -> dict:
    layers = [(r[f"skyc{i}"].strip(), number(r[f"skyl{i}"])) for i in range(1, 5) if r.get(f"skyc{i}", "").strip()]
    cover = max((COVER.get(c, 0.0) for c, _ in layers), default=0.0)
    ceiling = min((h for c, h in layers if c in ("BKN", "OVC", "VV") and h is not None), default=None)
    base = min((h for c, h in layers if h is not None and COVER.get(c, 0) > 0), default=None)
    tf, df = number(r.get("tmpf")), number(r.get("dwpf"))
    return {"t": t, "temp_c": None if tf is None else round((tf - 32) * 5 / 9, 1),
            "dew_c": None if df is None else round((df - 32) * 5 / 9, 1), "cover": cover,
            "clouds": [[c, h] for c, h in layers], "cloud_base_ft": base, "ceiling_ft": ceiling,
            "wx": r.get("wxcodes", "").split(), "precip_in": number(r.get("p01i")) or 0.0,
            "wind_kt": number(r.get("sknt")) or 0, "wind_dir": number(r.get("drct")), "gust_kt": number(r.get("gust")),
            "vis_sm": number(r.get("vsby")), "metar": r.get("metar", "").strip()}


def nearest(obs: list[dict], he: int) -> dict | None:
    """The observation nearest the middle of hour-ending `he` (local)."""
    mid = he - 0.5
    return min(obs, key=lambda o: abs(o["t"] - mid), default=None)


def number(s: str | None) -> float | None:
    if s in (None, "", "M", "T"):
        return 0.0001 if s == "T" else None
    try:
        v = float(s)
    except ValueError:
        return None
    return int(v) if v.is_integer() else v


if __name__ == "__main__":
    sys.exit(main())
