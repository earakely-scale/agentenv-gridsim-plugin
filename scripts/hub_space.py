"""Assemble the static Hugging Face Space: the viewer (web/), every Episode JSON under the runs folders re-verified
through gridsim_core, the weather sidecars, a runs index and the README. Nothing is uploaded.

usage: python scripts/hub_space.py [--runs results/runs] [--out hub/space] [--thumbs] [--hero EPISODE_ID]
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

import weather as wx  # noqa: E402

WEB = ROOT / "src" / "agentenv_gridsim" / "web"
PACKS = ("ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "showcase", "fixtures", "ercot-dam-v1-train")
HERO_TASK = "dam-v1-2025-03-15-HB_WEST-1h-t"
README = """---
title: GridSimEnv · The Battery Desk
emoji: 🔋
colorFrom: yellow
colorTo: blue
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Replays of a model running a Texas grid battery for a day
---

# GridSimEnv · The Battery Desk

An LLM agent runs one grid battery at an ERCOT hub or load zone in Texas for one day. It reads the day's 24 hourly
day-ahead prices, commits 24 hourly charge and discharge actions, and is graded against the exact optimum (dynamic
programming over every state of charge).

This Space holds **replays only**: every page plays back a recorded episode (`runs/*.json`, schema
`gridsim.episode/v1`). Nothing here calls a model. Each episode was re-verified through `gridsim_core` when the Space
was built: the schedule is settled again under the contract physics and its profit and reward must match.

The replay is a 3D scene of a battery yard in the settlement point's region, in that day's real sun and moon
position and the weather observed at the region's airport (IEM ASOS). Cyan pulses run into the yard while it charges,
amber pulses run out toward the city while it discharges. The cards say what is happening in plain English; the
expert charts sit behind the *Charts* button. Keys: space plays and pauses, the arrows step an hour, 1-4 set the speed,
D toggles the automatic camera.

{count} episodes: {models}.

## Data and attribution

- Prices: ERCOT DAM settlement point prices (public), report NP4-180-ER. Not affiliated with or endorsed by ERCOT.
- Weather: IEM ASOS observations, Iowa Environmental Mesonet, Iowa State University (public domain).

## Licences

- Viewer code: Apache-2.0. three.js 0.180.0 (vendored under `vendor/`): MIT.
- Scene and art: procedural geometry and canvas-drawn textures, CC0 (see `ASSETS.md`). No ERCOT logo or trademark is
  used, and the battery enclosures carry no brand.
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--runs", type=Path, nargs="*", default=[ROOT / "results" / "runs"])
    p.add_argument("--out", type=Path, default=ROOT / "hub" / "space")
    p.add_argument("--weather", type=Path, default=ROOT / "cache" / "weather")
    p.add_argument("--thumbs", action="store_true", help="Render a thumbnail for the featured day (headless Chrome).")
    p.add_argument("--hero", help="Episode id to feature (default: the best run on the hero day, else its optimum).")
    args = p.parse_args(argv)
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out, ignore=shutil.ignore_patterns(".DS_Store"))
    (out / "runs").mkdir()
    (out / "weather").mkdir()
    tasks = {}
    for pack in PACKS:
        for t in load_pack(pack):
            tasks.setdefault(t["task_id"], t)
    entries, rejected = [], []
    for folder in args.runs:
        for f in sorted(folder.rglob("*.json")):
            if f.name == "index.json" or "raw" in f.parts:
                continue
            ep = json.loads(f.read_text())
            if ep.get("schema") != "gridsim.episode/v1":
                continue
            why = verify(ep, tasks.get(ep["task_id"]))
            if why:
                rejected.append((f, why))
                continue
            name = f"{ep['episode_id']}.json"
            (out / "runs" / name).write_text(json.dumps(ep, separators=(",", ":")))
            entries.append(entry(ep, f"{name}"))
    for e in entries:
        side = wx.sidecar(e["point"], e["date"], args.weather)
        dst = out / "weather" / side.name
        if not dst.exists():
            shutil.copy(side, dst)
    hero = pick_hero(entries, args.hero)
    if hero:
        hero["hero"] = True
        hero["blurb"] = blurb(json.loads((out / "runs" / hero["url"]).read_text()))
        if args.thumbs:
            thumb = out / "thumbs" / f"{hero['id']}.jpg"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "record.py"), "--episode", str(out / "runs" / hero["url"]),
                            "--weather", str(out / "weather" / f"{hero['date']}_{hero['point']}.json"), "--thumb",
                            str(thumb)], check=True)
            hero["thumb"] = f"thumbs/{thumb.name}"
    (out / "runs" / "index.json").write_text(json.dumps({"schema": "gridsim.runs/v1", "episodes": entries}, indent=1))
    models = sorted({e["model"] for e in entries})
    (out / "README.md").write_text(README.replace("{count}", str(len(entries))).replace("{models}", ", ".join(models)))
    for f, why in rejected:
        print(f"REJECTED {f}: {why}")
    size = sum(x.stat().st_size for x in out.rglob("*") if x.is_file())
    print(f"{len(entries)} episodes ({len(rejected)} rejected), {len(list((out / 'weather').iterdir()))} weather "
          f"sidecars, hero {hero and hero['id']}, {size / 1e6:.1f} MB -> {out}")
    return 1 if rejected else 0


def verify(ep: dict, task: dict | None) -> str | None:
    """Settle the schedule again; profit and reward must match the episode."""
    acts = ep.get("final_schedule")
    if acts is None:
        return None if ep.get("reward") == 0 else "no schedule but a non-zero reward"
    if task is None:
        task = {**ep["task"], "task_id": ep["task_id"]}
    sim = simulate(task, acts)
    if ep.get("profit_usd") is not None and abs(sim["profit_usd"] - ep["profit_usd"]) > 0.01:
        return f"profit {ep['profit_usd']} != {sim['profit_usd']:.4f}"
    if sim["truncated_at"] != ep.get("truncated_at"):
        return f"truncated_at {ep.get('truncated_at')} != {sim['truncated_at']}"
    if task.get("refs"):
        g = grade(task, acts, ep["tier"])
        if abs(g["reward"] - (ep.get("reward") or 0)) > 1e-6:
            return f"reward {ep.get('reward')} != {g['reward']}"
    return None


def entry(ep: dict, url: str) -> dict:
    t, b = ep["task"], ep["task"]["battery"]
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "tier": ep["tier"], "bundle": ep.get("bundle"), "path": ep.get("path"), "trained": ep.get("trained"),
            "checkpoint_step": ep.get("checkpoint_step"), "reward": ep.get("reward"), "r_opt": ep.get("r_opt"),
            "profit": ep.get("profit_usd"), "p_opt": (ep.get("references") or {}).get("p_opt"), "date": t["date"],
            "point": t["settlement_point"], "region": t["region"], "archetype": b.get("archetype"),
            "battery": f"{b['p_dis_mw']:g} MW / {b['energy_mwh']:g} MWh", "truncated": ep.get("truncated_at") is not None}


def pick_hero(entries: list[dict], wanted: str | None) -> dict | None:
    if wanted:
        return next((e for e in entries if e["id"] == wanted), None)
    day = [e for e in entries if e["task_id"] == HERO_TASK]
    real = [e for e in day if not e["model"].startswith("reference/")]
    pool = real or [e for e in day if e["model"] == "reference/dp-optimum"] or entries
    return max(pool, key=lambda e: e["reward"] or 0, default=None)


def blurb(ep: dict) -> str:
    p = ep["task"]["prices"]
    neg = sum(1 for x in p if x < 0)
    peak = max(range(24), key=lambda h: p[h])
    hour = lambda h: "noon" if h == 12 else f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"
    return (f"West Texas on a spring day: {neg} hours of negative prices around midday, when the battery is paid to "
            f"charge, then an evening ramp to ${p[peak]:.0f}/MWh at {hour(peak)}." if neg else
            f"The day peaks at ${p[peak]:.0f}/MWh at {hour(peak)}.")


if __name__ == "__main__":
    sys.exit(main())
