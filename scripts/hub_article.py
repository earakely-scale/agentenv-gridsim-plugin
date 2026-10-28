"""The GridSimEnv article: a research-article Space built with tfrere's research-article-template (Astro, MDX chapters,
D3 embeds) under hub/article. Its charts read results/overview/results.json (scripts/hub_results.py) and data this
script derives from committed task packs and episodes, every schedule re-graded with gridsim_core.

    .venv/bin/python scripts/hub_article.py               # the article's data, the numbers check and the leak scan
    .venv/bin/python scripts/hub_article.py --build       # then npm ci (once) and npm run build in hub/article/app
    .venv/bin/python scripts/hub_article.py --publish     # then upload hub/article to the Space

The film and the stills are recorded with scripts/record.py (--media re-records them into build/article/); the banner
reads ERCOT's prices for every settlement point from the parsed DAM cache (scripts/build_pack.py), and keeps the
committed banner.json when the cache is absent.
"""

import argparse
import gzip
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core.advantage import hour_advantages, q_value, value_table  # noqa: E402
from gridsim_core.dp import dp_schedule  # noqa: E402
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import battery_of, index_pack, load_pack, make_battery, make_task  # noqa: E402

ARTICLE = ROOT / "hub" / "article"
APP = ARTICLE / "app"
DATA = APP / "src" / "content" / "assets" / "data"
PUBLIC = APP / "public"
MEDIA = ROOT / "build" / "article"
SPACE = "earakely-scale/GridSimEnv"
RESULTS = ROOT / "results" / "overview" / "results.json"
ATLAS = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json"
BANNER_DATE = "2025-03-15"
POINTS = {  # region, name; the map draws each region at a representative city, its points side by side
    "HB_WEST": ("west", "West hub"), "LZ_WEST": ("west", "West load zone"), "HB_PAN": ("panhandle", "Panhandle hub"),
    "HB_NORTH": ("north", "North hub"), "LZ_NORTH": ("north", "North load zone"),
    "LZ_RAYBN": ("north", "Rayburn load zone"), "HB_HOUSTON": ("houston", "Houston hub"),
    "LZ_HOUSTON": ("houston", "Houston load zone"), "HB_SOUTH": ("south", "South hub"),
    "LZ_SOUTH": ("south", "South load zone"), "LZ_CPS": ("south", "CPS Energy load zone"),
    "LZ_AEN": ("central", "Austin Energy load zone"), "LZ_LCRA": ("central", "LCRA load zone"),
    "HB_HUBAVG": ("average", "Hub average"), "HB_BUSAVG": ("average", "Bus average"),
}
REGIONS = {"west": ("West Texas", -102.1, 31.9), "panhandle": ("Panhandle", -101.8, 35.2),
           "north": ("North Texas", -96.9, 32.8), "houston": ("Houston", -95.4, 29.8),
           "south": ("South Texas", -98.5, 28.6), "central": ("Austin", -97.7, 30.3)}
ANATOMY = [  # (task id, tier, the story the article tells about it)
    ("dam-v1-2025-03-12-LZ_WEST-1h-c", "foresight",
     "Prices dip below zero at midday. The greedy rule pairs the wrong hours; the trained 4B matches the optimum."),
    ("dam-v1-2025-07-16-HB_HOUSTON-2h-e", "foresight",
     "Two round trips and an end obligation. The warm start bought into a full battery; after run 3 it does not."),
    ("dam-v1-2025-03-18-HB_WEST-4h-i", "foresight",
     "A deep negative trough. The trained 4B still overfills: the day stops there, and it keeps $1,673 of $2,205."),
    ("dam-v1-2026-10-19-HB_NORTH-2h-u", "blind",
     "The day's shape changed overnight. Yesterday's plan captures 0.74; the trained 4B's forecast-then-plan, 1.00."),
    ("dam-v1-2026-10-18-LZ_WEST-1h-e", "blind",
     "Night prices are high and midday is almost free. Yesterday's plan earns $489; the optimum $2,750."),
    ("dam-v1-2026-10-21-HB_NORTH-2h-t", "blind",
     "The trained 4B sells before it has charged and breaks the day; GPT-6.1 Sol does not."),
]
ADVANTAGE_TASK = "dam-v1-2025-07-16-HB_HOUSTON-2h-e"
LEAK = re.compile(r"s3://|amazonaws|airops-runs|scale\.com|\bFD-\d|\bsk-[A-Za-z0-9_-]{12,}|litellm\.[a-z]|ocp-apim|"
                  r"b2clogin|ercot-api|\bhf_[A-Za-z0-9]{30,}|\b(?:10|172|192)\.\d+\.\d+\.\d+\b|"
                  r"gridsim/adapters|\bi-0[0-9a-f]{8,}|object storage \(`", re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--media", action="store_true", help="Re-record the film and the stills with scripts/record.py.")
    ap.add_argument("--build", action="store_true", help="npm ci (once) and npm run build in hub/article/app.")
    ap.add_argument("--publish", action="store_true", help="Upload hub/article and the media to the Space.")
    ap.add_argument("--link", action="store_true",
                    help="Link the article from the dataset card and from the viewer Space's card and pages.")
    args = ap.parse_args()
    if args.media:
        record_media()
    res = json.loads(RESULTS.read_text())
    DATA.mkdir(parents=True, exist_ok=True)
    out = {"results.json": res, "anatomy.json": anatomy(), "advantage.json": advantage(),
           "timeline.json": timeline()}
    if (b := banner()) is not None:
        out["banner.json"] = b
    for name, obj in out.items():
        (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:16} {(DATA / name).stat().st_size / 1e3:7.1f} kB")
    copy_media()
    check_numbers(res)
    leaks(files_to_publish())
    if args.build or args.publish:
        build()
    if args.publish:
        print("space:", publish())
    if args.link:
        link()


def regrade(t: dict, actions, tier: str) -> dict:
    """A schedule's grade, path and error kind as the article shows it; None actions is no valid submission."""
    if actions is None:
        return {"valid": False, "score": 0.0, "profit": None, "kind": "no valid schedule"}
    g = grade(t, actions, tier)
    if not g.get("submitted"):
        return {"valid": False, "score": 0.0, "profit": None, "kind": "no valid schedule"}
    sim = simulate(t, actions)
    kind = ("all idle" if not any(actions) else
            {"soc_above_N": "overfill", "soc_below_0": "sell before charge", "rate": "rate",
             "cycle_cap": "cycle cap"}.get(g["violation"], g["violation"]) if g["violation"] else
            "end short" if g["end_shortfall_units"] else "ok")
    return {"valid": True, "actions": [int(a) for a in actions], "executed": sim["executed"], "soc": sim["soc_path"],
            "cash": [round(float(x), 2) for x in np.cumsum(sim["cashflow"])], "penalty": round(sim["penalty_usd"], 2),
            "profit": round(g["profit"], 2), "score": g["r_opt"] if tier == "blind" else g["reward"],
            "reward": g["reward"], "kind": kind, "truncated_at": g["truncated_at"]}


def jsonl(path: Path) -> dict:
    with gzip.open(path, "rt") if path.suffix == ".gz" else open(path) as f:
        return {r["task_id"]: r for r in map(json.loads, filter(str.strip, f))}


def eval_run(path: str, pack: str | None = None) -> dict:
    ev = json.loads((ROOT / path).read_text())
    run = next(r for r in ev["runs"] if r["decoding"] == "sampled" and (pack is None or r.get("pack") == pack))
    return {t["task_id"]: t for t in run["per_task"]}


def episode_texts(path: str, ids: set) -> dict:
    out = {}
    with gzip.open(ROOT / path, "rt") as f:
        for line in f:
            if line.strip():
                e = json.loads(line)
                if e["task_id"] in ids:
                    out[e["task_id"]] = e["messages"][-1]["content"].split("<tool_call>")[0].strip()
    return out


def sol_board() -> dict:
    """GPT-6.1 Sol's one-call (oneshot) runs of the v1 board, as the cost-matched contest reads them."""
    out = {}
    for d in ("results/runs/v1-board-sol-oneshot", "results/runs/v1-board-sol-oneshot-amend"):
        for f in sorted((ROOT / d).glob("*.json")):
            e = json.loads(f.read_text())
            out[e["task_id"]] = {"actions": e["final_schedule"], "usd": e["usage"]["usd"]}
    return out


def anatomy() -> dict:
    """Real battery-days, each with the DP optimum and every model's schedule on it, re-graded."""
    ev = index_pack("ercot-dam-v1-eval")
    fresh = {t["task_id"]: t for t in load_pack("ercot-dam-v1-fresh-2026-10-blind")}
    ids = {i for i, _, _ in ANATOMY}
    fore = {"base": eval_run("results/train/4b/eval_base.json"),
            "sft": eval_run("results/train/4b-dpa/eval_step0.json"),
            "final": eval_run("results/train/4b-dpa/eval_trained.json"), "sol": sol_board(),
            "luna-high": jsonl(ROOT / "results/cost-matched/luna/luna-foresight-eval2025-high.jsonl.gz")}
    blind = {"base": eval_run("results/train/4b-blind/eval_step0_base.json", "fresh"),
             "final": eval_run("results/train/4b-blind/eval_final.json", "fresh"),
             "sol": jsonl(ROOT / "results/train/4b-blind/sol/sol-ercot-dam-v1-fresh-2026-10-blind.jsonl.gz"),
             "luna-high": jsonl(ROOT / "results/cost-matched/luna/luna-blind-fresh-high.jsonl.gz"),
             "beam-max": jsonl(ROOT / "results/beam-agent/beam/beam-blind-fresh-max.jsonl.gz")}
    texts = {"foresight": episode_texts("results/train/4b-dpa/episodes/ckpt-0300-sampled.jsonl.gz", ids),
             "blind": episode_texts("results/train/4b-blind/episodes/final-fresh-sampled.jsonl.gz", ids)}
    labels = {"base": ("Qwen3-4B, untrained", "base"), "sft": ("Qwen3-4B, SFT-10k warm start", "qwen-sft"),
              "sol": ("GPT-6.1 Sol", "sol"), "luna-high": ("GPT-6 Luna, high", "luna"),
              "beam-max": ("Beam-1.0, max", "beam")}
    days = []
    for tid, tier, story in ANATOMY:
        t = ev[tid] if tier == "foresight" else fresh[tid]
        f = t["refs"]["foresight"]
        models = []
        src = fore if tier == "foresight" else blind
        for key in (("base", "sft", "final", "luna-high", "sol") if tier == "foresight" else
                    ("base", "final", "luna-high", "beam-max", "sol")):
            r = src[key].get(tid)
            if r is None:
                continue
            label, color = labels.get(key, (f"Qwen3-4B, trained ({'run 3' if tier == 'foresight' else 'run 4'})",
                                            "qwen"))
            g = regrade(t, r.get("actions"), tier)
            if "c" in r and g["valid"]:
                assert abs(g["score"] - r["c"]) < 1e-6, (tid, key)
            m = {"key": key, "label": label, "color": color, **g}
            if r.get("forecast"):
                m["forecast"] = [round(float(x), 1) for x in r["forecast"]]
            if key == "final" and tid in texts[tier]:
                m["text"] = texts[tier][tid]
            models.append(m)
        rules = [("greedy", "greedy rule", t["refs"]["foresight"]["baselines"]["greedy"]["schedule"])]
        if tier == "blind":
            rules = [("persistence-dp", "persistence-DP", t["refs"]["blind"]["persist"])]
        for key, label, sched in rules:
            models.append({"key": key, "label": label, "color": "rule", **regrade(t, sched, tier)})
        opt = regrade(t, f["opt"], tier)
        b = t["battery"]
        days.append({"id": tid, "tier": tier, "story": story, "date": t["date"], "point": t["settlement_point"],
                     "name": POINTS[t["settlement_point"]][1], "battery": {k: b[k] for k in (
                         "archetype", "p_dis_mw", "energy_mwh", "unit_mwh", "soc_levels", "k_dis", "k_ch", "eta",
                         "c_deg", "cycle_cap_units", "s0", "s_end_min")},
                     "prices": [round(p, 2) for p in t["prices"]],
                     "prev_day": [round(p, 2) for p in t["blind"]["dam_prev_day"]] if tier == "blind" else None,
                     "p_opt": round(f["p_opt"], 2), "p_idle": round(f["p_idle"], 2),
                     "p_anchor": round(t["refs"]["blind"]["p_anchor"], 2) if tier == "blind" else None,
                     "opt": opt, "models": models})
    return {"days": days}


def advantage() -> dict:
    """One held-out completion before and after run 3, credited hour by hour with the DP's exact advantage; at each
    visited state, the advantage of every action the hour allows."""
    t = index_pack("ercot-dam-v1-eval")[ADVANTAGE_TASK]
    b, p = battery_of(t), t["prices"]
    v = value_table(b, p)
    f = t["refs"]["foresight"]
    variants = []
    for key, label, path in (("sft", "Qwen3-4B after SFT-10k (run 3, step 0)",
                              "results/train/4b-dpa/episodes/step-0000-sampled.jsonl.gz"),
                             ("final", "after 300 steps of run 3",
                              "results/train/4b-dpa/episodes/ckpt-0300-sampled.jsonl.gz")):
        with gzip.open(ROOT / path, "rt") as fh:
            e = next(x for x in map(json.loads, filter(str.strip, fh)) if x["task_id"] == ADVANTAGE_TASK)
        acts = e["final_schedule"]
        ha = hour_advantages(t, acts)
        g = grade(t, acts)
        assert abs(g["reward"] - e["reward"]) < 1e-6
        s, d, q = b.s0, 0, []
        for h, a in enumerate(acts):
            if ha["truncated_at"] is not None and h > ha["truncated_at"]:
                q.append(None)
                continue
            base = float(v[h, s, d])
            q.append({"s": s, "d": d, "adv": {str(x): round((q_value(b, p, v, h, s, d, x) - base) * ha["scale"], 5)
                                              for x in range(-b.k_ch, b.k_dis + 1)}})
            if ha["truncated_at"] == h:
                continue
            s, d = s - a, d + max(a, 0)
        sim = simulate(t, acts)
        variants.append({"key": key, "label": label, "reward": g["reward"], "profit": round(g["profit"], 2),
                         "actions": acts, "soc": sim["soc_path"], "truncated_at": ha["truncated_at"],
                         "violation": g["violation"], "adv": [round(x, 5) for x in ha["adv"]],
                         "sign": [round(x, 5) for x in ha["sign"]], "digit": [round(x, 5) for x in ha["digit"]],
                         "opt": ha["opt"], "q": q,
                         "text": e["messages"][-1]["content"].split("<tool_call>")[0].strip()})
    bat = t["battery"]
    return {"id": ADVANTAGE_TASK, "date": t["date"], "point": t["settlement_point"],
            "name": POINTS[t["settlement_point"]][1], "prices": [round(x, 2) for x in p],
            "battery": {k: bat[k] for k in ("p_dis_mw", "energy_mwh", "unit_mwh", "soc_levels", "k_dis", "k_ch", "eta",
                                            "c_deg", "cycle_cap_units", "s0", "s_end_min")},
            "p_opt": round(f["p_opt"], 2), "p_idle": round(f["p_idle"], 2), "opt": f["opt"],
            "opt_soc": simulate(t, f["opt"])["soc_path"], "variants": variants}


def timeline() -> dict:
    """Which days train, which are held out, and when: each pack's dates and counts from its manifest."""
    packs = []
    for name, split, role in (("ercot-dam-v1-train", "train", "train"),
                              ("ercot-dam-v1-eval-iid", "eval_iid", "held out (every 10th day of 2014–2024)"),
                              ("ercot-dam-v1-eval", "eval_2025", "held out"),
                              ("ercot-dam-v1-rtcb", "rtcb", "held out, after RTC+B"),
                              ("ercot-dam-v1-fresh-2026-10", "fresh", "ERCOT's newest days")):
        m = json.loads((ROOT / "data" / name / "manifest.json").read_text())
        n_blind = m.get("count_blind")
        if name == "ercot-dam-v1-fresh-2026-10":
            n_blind = json.loads((ROOT / "data/ercot-dam-v1-fresh-2026-10-blind/manifest.json").read_text()).get(
                "count", n_blind)
        packs.append({"pack": name, "split": split, "role": role, "from": m["date_range"][0],
                      "to": m["date_range"][1], "n": m["count"], "n_blind": n_blind})
    return {"packs": packs, "rtcb": "2025-12-05", "live_first_seal": "2026-10-29",
            "showcase": [["2021-02-10", "2021-02-22", "Uri"], ["2022-12-22", "2022-12-24", "Elliott"],
                         ["2023-08-01", "2023-08-31", "August 2023"], ["2023-09-06", "2023-09-06", "6 Sep 2023"],
                         ["2024-01-13", "2024-01-17", "Heather"]]}


def texas() -> list:
    """Texas from the U.S. Census Bureau's cartographic boundaries (us-atlas 3.0.1, TopoJSON), simplified."""
    cache = ROOT / "cache" / "article" / "states-10m.json"
    if not cache.is_file():
        import urllib.request
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(ATLAS, timeout=60) as r:
            cache.write_bytes(r.read())
    topo = json.loads(cache.read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        q = np.cumsum(np.array(arc, float), axis=0)
        arcs.append(np.column_stack([q[:, 0] * sx + tx, q[:, 1] * sy + ty]))
    geom = next(g for g in topo["objects"]["states"]["geometries"] if g["id"] == "48")
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    ring = max((np.vstack([arcs[i] if i >= 0 else arcs[~i][::-1] for i in poly[0]]) for poly in polys), key=len)
    return [[round(x, 3), round(y, 3)] for x, y in simplify(ring, 0.02)]


def simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker, iterative."""
    keep = np.zeros(len(pts), bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab, rest = b - a, pts[i + 1:j] - a
        n = np.hypot(*ab)
        d = np.hypot(rest[:, 0], rest[:, 1]) if n < 1e-9 else np.abs(ab[0] * rest[:, 1] - ab[1] * rest[:, 0]) / n
        k = int(np.argmax(d))
        if d[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


def banner() -> dict | None:
    """One real day at all 15 settlement points: ERCOT's day-ahead prices on BANNER_DATE and the exact DP schedule of
    one 100 MW, 2-hour battery at each, for the hero map."""
    cache = sorted((ROOT / "cache" / "parsed").glob("dam-*.json.gz"))
    if not cache:
        print("banner: no parsed DAM cache (scripts/build_pack.py); keeping the committed banner.json")
        return None
    dam = json.loads(gzip.open(cache[-1], "rt").read())["dam"]
    bat = make_battery(100.0, 200.0, 2, eta=0.85, c_deg=0.0, cycles=1.5, s0=0, s_end_min=0, archetype="banner")
    pts = []
    for pid, (region, name) in POINTS.items():
        v = dam[f"{BANNER_DATE}|{pid}"]
        prices = v["prices"] if isinstance(v, dict) else v
        t = make_task(prices, bat, date=BANNER_DATE, point=pid)
        acts = dp_schedule(battery_of(t), prices)
        sim = simulate(t, acts)
        pts.append({"id": pid, "name": name, "region": region, "kind": "hub" if pid.startswith("HB_") else "load zone",
                    "prices": [round(p, 2) for p in prices], "actions": acts, "soc": sim["soc_path"],
                    "profit": round(sim["profit_usd"], 2)})
    return {"date": BANNER_DATE, "battery": {k: bat[k] for k in ("p_dis_mw", "energy_mwh", "unit_mwh", "soc_levels",
                                                                  "eta", "cycle_cap_units")},
            "regions": {k: {"name": n, "lon": x, "lat": y} for k, (n, x, y) in REGIONS.items()},
            "texas": texas(), "points": pts,
            "source": "ERCOT DAM settlement point prices (NP4-180-ER); Texas outline: U.S. Census Bureau via us-atlas"}


def record_media() -> None:
    """The film (the trained 4B, run 4, blind on 2026-10-19 at HB_NORTH) and the stills, recorded headless."""
    ep = MEDIA / "episodes"
    ep.mkdir(parents=True, exist_ok=True)
    picks = {"dam-v1-2026-10-19-HB_NORTH-2h-u", "dam-v1-2026-10-21-LZ_HOUSTON-4h-x", "dam-v1-2026-10-19-HB_PAN-2h-l"}
    with gzip.open(ROOT / "results/train/4b-blind/episodes/final-fresh-sampled.jsonl.gz", "rt") as f:
        for e in map(json.loads, filter(str.strip, f)):
            if e["task_id"] in picks:
                (ep / f"run4-{e['task_id']}.json").write_text(json.dumps(e))
    sol = ROOT / "results/runs/v1-board-sol-full/dam-v1-2025-03-15-HB_WEST-1h-t-openai-gpt-6.1-sol-r1.json"
    py, rec = sys.executable, str(ROOT / "scripts" / "record.py")
    weather = [str(ROOT / "scripts" / "weather.py"), "HB_NORTH", "2026-10-19", "LZ_HOUSTON", "2026-10-21",
               "HB_PAN", "2026-10-19", "HB_WEST", "2025-03-15"]
    subprocess.run([py, *weather], check=True)
    film = MEDIA / "media" / "run4-north-2026-10-19-1080.mp4"
    subprocess.run([py, rec, "--episode", str(ep / "run4-dam-v1-2026-10-19-HB_NORTH-2h-u.json"), "--out", str(film),
                    "--seconds", "40", "--size", "1920x1080"], check=True)
    web = MEDIA / "media" / "gridsim-run4-north-2026-10-19.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(film), "-vf", "scale=1600:900:flags=lanczos", "-c:v",
                    "libx264", "-preset", "slow", "-crf", "26", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-an", str(web)], check=True)
    poster = MEDIA / "media" / "poster.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "37", "-i", str(film), "-frames:v", "1", "-q:v", "3",
                    str(poster)], check=True)
    stills = [(sol, 12.5, "establish", "gridsim-west-noon"), (sol, 20.6, "establish", "gridsim-west-night"),
              (ep / "run4-dam-v1-2026-10-21-LZ_HOUSTON-4h-x.json", 18.6, "city", "gridsim-houston-sunset"),
              (ep / "run4-dam-v1-2026-10-19-HB_PAN-2h-l.json", 18.4, "city", "gridsim-panhandle-wind")]
    (MEDIA / "img").mkdir(parents=True, exist_ok=True)
    for episode, t, shot, name in stills:
        png = MEDIA / "stills" / f"{name}.png"
        subprocess.run([py, rec, "--episode", str(episode), "--still", str(png), "--t", str(t), "--size",
                        "1600x900", "--extra", f"ui=0&shot={shot}"], check=True)
        subprocess.run(["cwebp", "-quiet", "-q", "82", str(png), "-o", str(MEDIA / "img" / f"{name}.webp")],
                       check=True)
    subprocess.run(["cwebp", "-quiet", "-q", "84", "-resize", "1600", "0", str(poster), "-o",
                    str(MEDIA / "img" / "gridsim-run4-poster.webp")], check=True)


def copy_media() -> None:
    """The stills (small, committed under app/public/img) and the film (uploaded to the Space, not committed)."""
    for src, dst, pattern in ((MEDIA / "img", PUBLIC / "img", "gridsim-*.webp"),
                              (MEDIA / "media", PUBLIC / "media", "gridsim-*.mp4")):
        for f in sorted(src.glob(pattern)):
            dst.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst / f.name)


def h(x: float, nd: int = 3, sign: bool = False) -> str:
    """Half-up, a true minus sign, as the results READMEs print."""
    q = Decimal(str(x)).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP)
    return (f"{q:+}" if sign else f"{q}").replace("-", "−")


def ci(c, nd: int = 3, sign: bool = True) -> str:
    return f"[{h(c[0], nd, sign)}, {h(c[1], nd, sign)}]"


def neg(g: dict) -> dict:
    return {"mean": -g["mean"], "ci": [-g["ci"][1], -g["ci"][0]]}


def checks(r: dict) -> list[tuple[str, str]]:
    """(chapter, text): every number the prose states that results.json holds, formatted from results.json."""
    fr = {p["key"]: p for p in r["frontier"]["points"]}
    lb = {p["key"]: {x["key"]: x for x in p["rows"]} | {f"ref:{b['key']}": b for b in p["baselines"]}
          for p in r["leaderboard"]["packs"]}
    e, n = r["dollars"]["packs"]["eval2025"], r["dollars"]["packs"]["fresh"]
    eg, ng = e["gaps"], n["gaps"]
    lad = {x["key"]: x for x in e["ladder"]}
    t, pl = r["training"]["curve"], r["training"]["planning"]
    pe, pf = pl["eval2025"]["gaps"], pl["fresh"]["gaps"]
    q4, inf = e["quartiles"][3], e["inference"]
    pay = r["dollars"]["payback"]

    def gap(g, nd=3):
        return f"{h(g['mean'], nd, True)} {ci(g['ci'], nd)}"

    def usd(x, nd=1):
        return f"${h(x, nd)}"

    def kyr(g, s=""):
        m = g["yr"]["mean"]
        return f"{'+' if m > 0 else '−'}{usd(abs(m))}k{s} {ci(g['yr']['ci'], 1)}"

    lf, bf = lb["blind-fresh"], lb["blind-eval2025"]
    sol_m, beam_m = fr["sol"]["final_minus"], fr["beam-max"]["final_minus"]
    return [
        ("eval.mdx", f"Sol captures {h(fr['sol']['mean'])} of"), ("eval.mdx", f"{h(bf['sol']['mean'])} on 2025"),
        ("eval.mdx", f"captures {h(lf['ref:persistence-dp']['mean'])} and {h(bf['ref:persistence-dp']['mean'])}"),
        ("eval.mdx", f"scores {h(lb['foresight-eval2025']['final']['mean'])} and "
                     f"{h(lb['foresight-fresh']['final']['mean'])} at foresight and {h(bf['final']['mean'])} and "
                     f"{h(lf['final']['mean'])} blind"),
        ("eval.mdx", gap(fr["luna-high"]["final_minus"])), ("eval.mdx", gap(fr["luna-low"]["final_minus"])),
        ("eval.mdx", f"captures {h(-sol_m['mean'])} more** {ci(neg(sol_m)['ci'])}"),
        ("eval.mdx", f"captures {h(fr['beam-max']['mean'])}, ahead of the trained 4B ({gap(neg(beam_m))})"),
        ("eval.mdx", f"for {usd(fr['beam-max']['usd'], 4)} a battery-day"),
        ("eval.mdx", f"for {h(r['frontier']['ratios']['sol'], 0)} times the 4B's"),
        ("worth.mdx", f"Training bought {kyr(eg['4b-sampled - base'])}".replace("k [", "k per MW-year** [")),
        ("worth.mdx", kyr(ng["4b-sampled - base"])),
        ("worth.mdx", f"from −{usd(-lad['base']['yr']['mean'])}k"),
        ("worth.mdx", f"to {usd(lad['4b-sampled']['yr']['mean'])}k"),
        ("worth.mdx", f"about {usd(eg['4b-sampled - base']['per_100mw_yr'] / 1000)}M a year"),
        ("worth.mdx", f"{kyr(eg['4b-sampled - persistence-dp'])} per MW-year on 2025"),
        ("worth.mdx", f"{kyr(ng['4b-sampled - persistence-dp'])} on the newest"),
        ("worth.mdx", f"by {kyr(eg['sol - persistence-dp'])}".replace("k [", "k** [")),
        ("worth.mdx", kyr(ng["sol - persistence-dp"])),
        ("worth.mdx", f"about {usd(eg['sol - persistence-dp']['per_100mw_yr'], 0)}k a year"),
        ("worth.mdx", f"falls {usd(q4['shortfall']['mean'])} short"),
        ("worth.mdx", f"recovers {usd(q4['sol']['mean'])} of it {ci(q4['sol']['ci'], 1)}"),
        ("worth.mdx", f"{round(100 * e['top_days']['sol_share_from_top'])}% of its net gain over persistence-DP on "
                      f"2025 comes from its best {e['top_days']['k']} days"),
        ("worth.mdx", f"Sol costs {usd(inf['models']['sol']['usd_per_battery_yr'], 2)} of inference"),
        ("worth.mdx", f"extra {usd(inf['sol_over_4b']['extra_inference_usd_per_battery_yr'], 2)} a year"),
        ("worth.mdx", f"buys {usd(inf['sol_over_4b']['decision_gap_k_usd_per_100mw_yr'], 0)}k a year"),
        ("training.mdx", f"rose {gap(t['run3_gain'])}**, to {h(t['run3'][-1]['sampled']['mean'])}"),
        ("training.mdx", f"gained {gap(t['run1']['gain'])} in {t['run1']['end']['step']} steps"),
        ("training.mdx", f"moved {gap(t['run2']['gain'])} in {t['run2']['end']['step']} steps"),
        ("training.mdx", f"miss by {usd(pl['mae']['final'], 2)}/MWh"),
        ("training.mdx", f"forecaster's {usd(pl['mae']['teacher'], 2)}"),
        ("training.mdx", f"yesterday's prices' {usd(pl['mae']['persistence'], 2)}"),
        ("training.mdx", f"{h(pl['eval2025']['dp_own']['mean'])} against Sol's {h(pl['eval2025']['sol']['mean'])} on "
                         f"2025 ({gap(pe['dp_own_minus_sol'])}"),
        ("training.mdx", f"Only {round(100 * pl['eval2025']['exact_dp_share'])}% of its schedules"),
        ("training.mdx", f"{gap(pe['final_minus_sol'])} on 2025 and {gap(pf['final_minus_sol'])} on the newest"),
        ("training.mdx", f"{gap(pe['final_minus_sft'])} on 2025 and {gap(pf['final_minus_sft'])} on the newest"),
        ("training.mdx", f"About {usd(r['training']['gpu_usd_total'], 0)} of GPU"),
        ("training.mdx", f"after about {round(pay['run 4']['battery_days'], -3):,.0f} battery-days, run 3's after "
                         f"about {round(pay['run 3']['battery_days'], -3):,.0f}"),
        ("environment.mdx", f"captures {h(fr['final']['mean'])} of hindsight on average"),
    ]


def check_numbers(res: dict) -> None:
    """Every number the prose states from results.json, against results.json."""
    chapters = {p.name: re.sub(r"\s+", " ", p.read_text().replace("\\$", "$"))
                for p in (APP / "src" / "content" / "chapters").glob("*.mdx")}
    bad = [f"{c}: {text!r}" for c, text in checks(res) if text not in chapters.get(c, "")]
    if bad:
        raise SystemExit("numbers check failed, not in the prose:\n  " + "\n  ".join(bad))
    print(f"numbers check: {len(checks(res))} stated numbers match results.json")


def files_to_publish() -> dict[str, Path]:
    skip = re.compile(r"(^|/)(node_modules|dist|\.astro|\.DS_Store)(/|$)|^app/public/data(/|$)")
    out = {}
    for p in sorted(ARTICLE.rglob("*")):
        rel = p.relative_to(ARTICLE).as_posix()
        if p.is_file() and not p.is_symlink() and not skip.search(rel):
            out[rel] = p
    return out


def leaks(files: dict[str, Path]) -> None:
    from agentenv_hf.scan import known_values, scan
    text = {k: p.read_bytes() for k, p in files.items() if p.suffix in (".md", ".mdx", ".html", ".json", ".js", ".mjs",
                                                                         ".astro", ".ts", ".css", ".bib", ".txt")}
    scan(text, known_values())
    for k, v in text.items():
        if hit := LEAK.search(v.decode()):
            raise SystemExit(f"{k} holds {hit[0]!r}; nothing was published")
    print(f"leak scan: {len(text)} text files clean")


def build() -> None:
    if not (APP / "node_modules").is_dir():
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=APP, check=True)
    subprocess.run(["npm", "run", "build"], cwd=APP, check=True)


GITATTRIBUTES = "".join(f"*.{x} filter=lfs diff=lfs merge=lfs -text\n" for x in ("mp4", "webp", "jpg", "png"))


def publish() -> str:
    """Create the Docker Space if needed and make its files exactly hub/article's (with the film and stills)."""
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api = HfApi()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", exist_ok=True)
    files = files_to_publish()
    live = set(api.list_repo_files(SPACE, repo_type="space"))
    ops = [CommitOperationAdd(path_in_repo=".gitattributes", path_or_fileobj=GITATTRIBUTES.encode())]
    ops += [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(p)) for k, p in files.items()]
    ops += [CommitOperationDelete(path_in_repo=k) for k in sorted(live - set(files) - {".gitattributes"})]
    info = api.create_commit(SPACE, repo_type="space", operations=ops,
                             commit_message="GridSimEnv article: running a grid battery on ERCOT's real prices")
    return info.commit_url


ARTICLE_URL = f"https://huggingface.co/spaces/{SPACE}"
SPACE_PAR = (f"**[The article]({ARTICLE_URL}):** GridSimEnv, running a grid battery on ERCOT's real prices: the "
             "environment, how\nfrontier models bid, how a 4B open model was trained on its exact grader, and what the "
             "decisions are worth in dollars.\n\n")


def link() -> None:
    """The article in the dataset card's links (hub/dataset/README.md, built as hub_dataset builds it) and in the viewer
    Space's card and pages. The dataset's card must lose nothing the live card has; nothing else is touched."""
    from huggingface_hub import CommitOperationAdd, HfApi
    spec = importlib.util.spec_from_file_location("hub_results", ROOT / "scripts" / "hub_results.py")
    hr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hr)
    hd = hr.module("hub_dataset", "scripts/hub_dataset.py")
    card, live_card = hd.card_only(ROOT / "results"), hr.live_file("dataset", "README.md")
    if hr.card_diff(card, live_card):
        raise SystemExit("the built card drops lines of the live card; rebuild the dataset with hub_results.py first")
    readme = hr.live_file("space", "README.md")
    if ARTICLE_URL + ")" not in readme:
        anchor = readme.index("**[What training bought, in dollars]")
        readme = readme[:anchor] + SPACE_PAR + readme[anchor:]
    space = {"README.md": readme.encode(), **{n: (hr.WEB / n).read_bytes() for n in ("index.html", "results.html",
                                                                                     "board.html")}}
    hr.leaks({"README.md": card.encode()} | {f"space/{k}": v for k, v in space.items()})
    api = HfApi()
    for repo_type, files, msg in (("dataset", {"README.md": card.encode()}, "Card: link the article"),
                                  ("space", space, "Link the article from the viewer's pages and card")):
        ops = [CommitOperationAdd(path_in_repo=k, path_or_fileobj=v) for k, v in files.items()]
        info = api.create_commit(hr.HF, repo_type=repo_type, operations=ops, commit_message=msg)
        print(f"{repo_type}:", info.commit_url)


if __name__ == "__main__":
    main()
