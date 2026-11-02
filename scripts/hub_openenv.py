"""The GridSimEnv Desk OpenEnv Space (hub/openenv): the desk served by OpenEnv, with a Try Environment tab that plays a
v4 benchmark window by hand beside the battery site in 3D and OpenEnv's MCP playground. This stages the Space in
build/hub/openenv: hub/openenv, gridsim_core, the desk-v4-bench pack copied without the real site and operator names
(design decision D9), data/windows.json (each window's card, its observed weather and the benchmark's grades on it) and
the viewer's 3D kit. Then it plays every desk tool at every wake-up of every window and writes those outputs to
build/hub/openenv-outputs, and nothing is staged unless they and every staged file are clean of the real names and of
leaks.

    .venv/bin/python scripts/hub_openenv.py              # stage and scan
    .venv/bin/python scripts/hub_openenv.py --docker     # then build the image and run it on port 8000
    .venv/bin/python scripts/hub_openenv.py --publish    # then make the Space's files exactly the staged ones
"""

import argparse
import gzip
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import date, timedelta
from pathlib import Path

from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import weather as wx  # noqa: E402

from gridsim_core.desk import (  # noqa: E402
    Session,
    clock,
    grade,
    load_series,
    load_tasks,
    policies,
    system_prompt,
    text,
)

SPACE = "earakely-scale/GridSimEnv-OpenEnv"
SOURCE = ROOT / "hub" / "openenv"
OUT = ROOT / "build" / "hub" / "openenv"
OUTPUTS = ROOT / "build" / "hub" / "openenv-outputs"
WEB = ROOT / "src" / "agentenv_gridsim" / "web"
PACK = "desk-v4-bench"
BENCH = ROOT / "results" / "desk-v4-bench"
SPLIT = "bench"
DEFAULT = "desk-v4-2026-08-18-S02"
SCENES = {"LZ_WEST": "west", "LZ_HOUSTON": "houston", "LZ_NORTH": "north", "LZ_SOUTH": "south"}
WEATHER = ROOT / "cache" / "weather" / "iem-desk"
OBS = ("t", "temp_c", "cover", "clouds", "cloud_base_ft", "ceiling_ft", "wx", "precip_in", "wind_kt", "wind_dir",
       "gust_kt", "vis_sm")
SITE_KEEP = ("site_id", "load_zone", "hub", "region", "hsl_mw", "lsl_mw", "e_max_mwh", "e_min_mwh", "ramp_mw_per_min",
             "rte", "standby_loss_pct_per_h", "calibration", "deg_usd_per_mwh", "warranty_cycles_per_day", "soc0_mwh",
             "soc0_source", "card", "pv")
REFS = ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual", "floored",
        "c_undefined", "anchor_setting", "core_version")
KIT = ("places.js", "data.js", "stage", "desk/scene.js", "desk/fmt.js", "desk/base.css", "desk/fonts",
       "vendor/three-0.180.0")
SKIP = ("__pycache__", ".DS_Store", ".pytest_cache")
GITATTRIBUTES = "".join(f"*.{x} filter=lfs diff=lfs merge=lfs -text\n" for x in ("woff2", "gz"))
READS = (("get_prices", [{"market": m, "point": p, "day": d} for m in ("dam", "rt", "sced") for p in ("node", "hub")
                         for d in ("D-1", "D0", "D1", "D2")]
          + [{"market": m, "day": d} for m in ("as_dam", "as_rt", "asdc") for d in ("D-1", "D0", "D1")]),
         ("get_forecasts", [{"kind": k, "market": m, "day": d} for k in ("price", "as_price") for m in ("dam", "rt")
                            for d in ("D0", "D1", "D2")]
          + [{"kind": k, "day": d} for k in ("load", "wind", "solar", "net_load", "outages", "weather", "pv")
             for d in ("D0", "D1", "D2")]),
         ("get_grid_conditions", [{}, {"start": "D-1 06:00"}]),
         ("get_asset_status", [{}]),
         ("get_position", [{"day": d, "detail": x} for d in ("D0", "D1", "D2") for x in ("summary", "hourly")]),
         ("optimize", [{}, {"price_view": "desk", "risk": 1.5, "constraints": {"dam_position": "spread"}}]),
         ("set_reminder", [{"at": "23:55", "note": "check the evening ramp"}]))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--docker", action="store_true", help="Build the staged Space's image and run it on port 8000.")
    ap.add_argument("--publish", action="store_true", help=f"Upload the staged Space to {SPACE}.")
    ap.add_argument("--quick", action="store_true", help="Play the tools on the default window only (a dev loop); "
                                                         "--publish refuses it.")
    args = ap.parse_args()
    if args.publish and args.quick:
        raise SystemExit("--publish needs every window's outputs scanned: drop --quick")
    stage()
    sweep([DEFAULT] if args.quick else None)
    hd = module("hub_desk", "scripts/hub_desk.py")
    hr = module("hub_results", "scripts/hub_results.py")
    for folder in (OUT, OUTPUTS):
        files = texts(folder)
        hr.leaks(files)
        hd.anonymous(files, hd.names(ROOT))
    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"staged {OUT.relative_to(ROOT)}: {sum(1 for p in OUT.rglob('*') if p.is_file())} files, {size / 1e6:.1f} MB")
    if args.docker:
        docker()
    if args.publish:
        print("space:", publish())


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def stage() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    copy(SOURCE, OUT)
    copy(ROOT / "src" / "gridsim_core", OUT / "gridsim_core")
    for rel in KIT:
        copy(WEB / rel, OUT / "server" / "web" / "kit" / rel)
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(ROOT / name, OUT / name)
    (OUT / ".gitattributes").write_text(GITATTRIBUTES)
    pack()
    (OUT / "data" / "windows.json").write_text(json.dumps(catalog(), ensure_ascii=False, separators=(",", ":")))


def copy(src: Path, dst: Path) -> None:
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*SKIP), dirs_exist_ok=True)


def pack() -> None:
    """The pack as the env reads it, without the real names: each site keeps its card, limits and calibration, each
    series loses the operator's own disclosures (only the references read them, and the task rows keep their totals)."""
    src, dst = ROOT / "data" / "desk" / PACK, OUT / "data" / PACK
    (dst / "series").mkdir(parents=True)
    rows = []
    for t in load_tasks(PACK):
        rows.append(dict(t, site={k: t["site"][k] for k in SITE_KEEP if k in t["site"]},
                         refs={k: t["refs"][k] for k in REFS}))
        series = load_series(PACK, t)
        series.pop("operator", None)
        with gzip.open(dst / t["series"], "wt") as f:
            json.dump(series, f, ensure_ascii=False, separators=(",", ":"))
    with gzip.open(dst / "tasks.jsonl.gz", "wt") as f:
        f.writelines(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows)
    m = json.loads((src / "manifest.json").read_text())
    (dst / "manifest.json").write_text(json.dumps({k: m[k] for k in ("pack", "schema", "split", "layer", "n_tasks",
                                                                     "sites", "dates", "sources", "cutoff")}, indent=1))


def catalog() -> dict:
    """data/windows.json: the windows in the pack's order with their public cards, each one's observed weather (the
    server shows it up to the episode's minute) and the benchmark's grades on it, read only once a window is over."""
    hd = module("hub_dataset", "scripts/hub_dataset.py")
    summary, grades = hd.bench_read(BENCH)
    if summary["fake"]:
        raise SystemExit("results/desk-v4-bench holds fake data")
    fronts = {f["front"]: f for f in summary["fronts"]}
    named = module("hub_desk", "scripts/hub_desk.py").NAMED["v4"]
    by_task: dict[str, list[dict]] = {}
    for g in grades:
        by_task.setdefault(g["task_id"], []).append(g)
    tasks = load_tasks(PACK)
    windows, scenes, bench = {}, {}, {}
    for i, t in enumerate(tasks):
        site, card, tid = t["site"], t["site"]["card"], t["task_id"]
        g0 = by_task[tid][0]
        front = fronts[g0["front"]]
        station = wx.STATION[site["load_zone"]]
        airport, lat, lon = wx.AIRPORTS[station]
        n = len(t["dates"])
        windows[tid] = {
            "index": i, "task_id": tid, "dates": t["dates"],
            "title": f"{card['name']}, {card['region']}, {span(t['dates'])}",
            "start": clock.label(clock.START, t["dates"][0]), "end": clock.label(clock.DAY * n, t["dates"][0]),
            "season": t["tags"].get("season"), "cutoff": g0["split"],
            "front": {"date": g0["front"], "kind": front["kind"], "name": named.get(g0["front"])},
            "site": {"id": site["site_id"], "name": card["name"], "region": card["region"], "size": card["size"],
                     "scene": SCENES[site["load_zone"]], "hsl": site["hsl_mw"], "lsl": site["lsl_mw"],
                     "emax": site["e_max_mwh"], "emin": site.get("e_min_mwh", 0.0), "rte": site["rte"],
                     "soc0": site["soc0_mwh"], "pv": site.get("pv")},
            "place": {"lat": lat, "lon": lon, "airport": airport, "station": station}}
        scenes[tid] = {"weather": observed(station, t["dates"])}
        refs = {k: t["refs"][k] for k in ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay",
                                          "p_operator_actual")}
        rows = [[g["model"], g["capture"], g["reward"], g["p"], g["valid"]] for g in by_task[tid]
                if g["status"] == "scored"]
        bench[tid] = {"refs": refs, "models": sorted(rows, key=lambda r: -(r[1] if r[1] is not None else -1e9))}
    models = {k: {"name": m["name"], "tag": m.get("tag") or m["name"], "harness": m["harness"],
                  "provider": m.get("provider"), "C": m["all"]["C"]["mean"]} for k, m in summary["models"].items()}
    return {"schema": "gridsim.openenv.windows/v1", "pack": PACK, "split": SPLIT, "default": DEFAULT,
            "order": [t["task_id"] for t in tasks], "windows": windows, "scenes": scenes, "bench": bench,
            "models": models, "weather_source": wx.TERMS}


def span(dates: list[str]) -> str:
    a, b = date.fromisoformat(dates[0]), date.fromisoformat(dates[-1])
    return f"{a:%-d}–{b:%-d %b %Y}" if a.month == b.month else f"{a:%-d %b}–{b:%-d %b %Y}"


def observed(station: str, dates: list[str]) -> list[dict]:
    """The airport's reports from the evening before the desk opens to the window's end, hours from D0 00:00."""
    raw = WEATHER / f"{station}_{dates[0]}_{len(dates)}d.csv"
    if not raw.is_file():
        WEATHER.mkdir(parents=True, exist_ok=True)
        start = (date.fromisoformat(dates[0]) - timedelta(days=1)).isoformat()
        raw.write_text(wx.fetch(wx.url(station, start, len(dates) + 1)))
    point = next(p for p, s in wx.STATION.items() if s == station)
    side = wx.build(point, dates[0], raw.read_text(), (-21, 24 * len(dates) + 2))
    return [{k: o[k] for k in OBS if o.get(k) not in (None, [], "")} for o in side["obs"]]


def sweep(only: list[str] | None) -> None:
    """Every desk tool at every wake-up of each window, with the arguments READS lists, the window's start prompt and
    desk brief, every wake-up message, the anchor's submissions and the final grade, as files to scan. The Session's
    call budget is lifted here so every read runs at every wake; the outputs are the Session's own."""
    if OUTPUTS.exists():
        shutil.rmtree(OUTPUTS)
    OUTPUTS.mkdir(parents=True)
    with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 1)) as pool:
        for line in pool.map(play_all, only or [t["task_id"] for t in load_tasks(PACK)]):
            print(line)


def play_all(tid: str) -> str:
    t = next(x for x in load_tasks(PACK) if x["task_id"] == tid)
    s = Session(t, load_series(PACK, t), budgets={"calls_per_turn": 10_000, "max_reminders": 10_000})
    lines = [system_prompt(s)]
    wake = s.start()
    while wake is not None:
        lines.append(text(wake))
        for name, variants in READS:
            lines += [text(s.call(name, a)) for a in variants]
        lines += [text(s.call("check_submission", {"kind": k, "payload": {}})) for k in ("dam", "rt", "cop")]
        policies.anchor(s, wake)
        wake = s.end_turn("ok")
    g = grade(s, t["refs"])
    lines += [text(g), text(s.episode(grade=g))]
    with gzip.open(OUTPUTS / f"{tid}.txt.gz", "wt") as f:
        f.write("\n".join(lines))
    return f"  {tid}: {len(lines)} outputs, P {g['p']:,.0f} (anchor {g['p_anchor']:,.0f})"


def texts(folder: Path) -> dict[str, bytes]:
    binary = (".woff2", ".png", ".jpg", ".webp", ".gif", ".mp4", ".ico")
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*"))
            if p.is_file() and p.suffix not in binary}


def docker() -> None:
    subprocess.run(["docker", "build", "-t", "gridsim-desk-openenv", str(OUT)], check=True)
    subprocess.run(["docker", "rm", "-f", "gridsim-desk-openenv"], check=False, capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", "gridsim-desk-openenv", "-p", "8000:8000", "--cpus", "2",
                    "--memory", "16g", "gridsim-desk-openenv"], check=True)
    print("running: http://localhost:8000/web/")


def publish() -> str:
    api = HfApi()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", exist_ok=True)
    files = {p.relative_to(OUT).as_posix(): p for p in sorted(OUT.rglob("*")) if p.is_file()}
    live = set(api.list_repo_files(SPACE, repo_type="space"))
    ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(p)) for k, p in files.items()]
    ops += [CommitOperationDelete(path_in_repo=k) for k in sorted(live - set(files))]
    info = api.create_commit(SPACE, repo_type="space", operations=ops, commit_message=(
        "GridSimEnv Desk on OpenEnv: try a benchmark window by hand, and the playground"))
    return info.commit_url


if __name__ == "__main__":
    main()
