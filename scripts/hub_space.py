"""Assemble the static Hugging Face Space: the viewer (web/), every Episode JSON under the runs folders re-verified
through gridsim_core, the weather sidecars, a runs index with the featured days and the README. Nothing is uploaded.

usage: python scripts/hub_space.py [--runs results/runs] [--out build/hub/space] [--thumbs] [--hero EPISODE_ID]
"""

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import weather as wx  # noqa: E402

from gridsim_core.contract import DEGENERATE_EPS  # noqa: E402
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

WEB = ROOT / "src" / "agentenv_gridsim" / "web"
PACKS = ("ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "showcase", "fixtures",
         "ercot-dam-v1-train")
HERO_TASK = "dam-v1-2025-03-15-HB_WEST-1h-t"
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv"
APP = "https://earakely-scale-gridsimenv-agentenv.static.hf.space"
REGIONS = {"west": "West Texas", "panhandle": "the Panhandle", "north": "North Texas", "houston": "Houston",
           "south": "South Texas", "central": "Central Texas"}
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

[![{hero_alt}](thumbs/{hero_still})]({app}/index.html?episode=runs/{hero_url})

An LLM agent runs one grid battery at an ERCOT hub or load zone in Texas for one day. It reads the day's 24 hourly
day-ahead prices, commits 24 hourly charge and discharge actions, and is graded against the exact optimum (dynamic
programming over every state of charge). At the blind tier it sees only the days before and is graded against the
better of two forecasters a desk could build from the same inputs.

**[What training bought, in dollars]({app}/results.html):** Qwen3-4B, trained on this environment's exact grader,
went from below idle to bidding as well as GPT-6 Luna at a quarter of its cost, with GPT-6.1 Sol still ahead: the
before and after, the score-against-cost frontier, the training runs and what the decisions earn per MW of battery.

**The featured day,** {hero_caption}

**[The live board]({app}/board.html):** on each pass, GPT-6.1 Sol, GPT-6 Luna, the trained 4B and three rules seal a
schedule for 45 batteries before ERCOT's day-ahead market closes; the first seal is for 2026-10-29, and passes run on
demand. The schedules are settled at the prices ERCOT then posts, and the P&L adds up day by day.

The viewer holds **replays only**: every replay plays back a recorded episode (`runs/*.json`, schema
`gridsim.episode/v1`). Nothing here calls a model. Each episode was re-verified through `gridsim_core` when the Space
was built: the schedule is settled again under the contract physics and its profit and reward must match.

The replay is a 3D scene of a battery yard in the settlement point's region, in that day's real sun and moon
position and the weather observed at the region's airport (IEM ASOS). Cyan pulses run into the yard while it charges,
amber pulses run out toward the city while it discharges. The cards say what is happening in plain English; the
expert charts sit behind the *Charts* button. Keys: space plays and pauses, the arrows step an hour, 1-4 set the speed,
D toggles the automatic camera.

{count} episodes: {models}.

## Links

- The runs, with their transcripts, and every battery-day: the dataset [earakely-scale/GridSimEnv-AgentEnv]({dataset})
  (`v1_episodes`).
- The board: [results/board.md]({repo}/blob/main/results/board.md), registered before the first run in
  [docs/prereg/v1-board.md]({repo}/blob/main/docs/prereg/v1-board.md).
- The environment, the agent and this viewer: [agentenv-gridsim-plugin]({repo}).

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
    p.add_argument("--out", type=Path, default=ROOT / "build" / "hub" / "space")
    p.add_argument("--weather", type=Path, default=ROOT / "cache" / "weather")
    p.add_argument("--thumbs", action="store_true",
                   help="Render the featured days' thumbnails and the README's hero still (headless Chrome).")
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
            if f.name == "index.json" or "raw" in f.relative_to(folder).parts[:-1]:
                continue
            ep = json.loads(f.read_text())
            if not isinstance(ep, dict) or ep.get("schema") != "gridsim.episode/v1":
                continue
            task = tasks.get(ep["task_id"])
            if why := verify(ep, task):
                rejected.append((f, why))
                continue
            name = f"{ep['episode_id']}.json"
            (out / "runs" / name).write_text(json.dumps(ep, separators=(",", ":")))
            entries.append(entry(ep, name, task))
    for e in entries:
        side = wx.sidecar(e["point"], e["date"], args.weather)
        if not (out / "weather" / side.name).exists():
            shutil.copy(side, out / "weather" / side.name)
    featured = feature(entries, args.hero, out)
    if args.thumbs:
        for e in featured[1:]:
            thumbnail(out, e)
        still(out, featured[0])
    index = [{k: v for k, v in e.items() if v is not None} for e in entries]
    (out / "runs" / "index.json").write_text(json.dumps({"schema": "gridsim.runs/v1", "episodes": index},
                                                        separators=(",", ":")))
    (out / "README.md").write_text(readme(entries, featured[0] if featured else None))
    for f, why in rejected:
        print(f"REJECTED {f}: {why}")
    size = sum(x.stat().st_size for x in out.rglob("*") if x.is_file())
    print(f"{len(entries)} episodes ({len(rejected)} rejected), {len(list((out / 'weather').iterdir()))} weather "
          f"sidecars, featured {[e['id'] for e in featured]}, {size / 1e6:.1f} MB -> {out}")
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


def entry(ep: dict, url: str, task: dict | None) -> dict:
    t, b = ep["task"], ep["task"]["battery"]
    blind = ((task or {}).get("refs") or {}).get("blind") if ep["tier"] == "blind" else None
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label"), "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "checkpoint_step": ep.get("checkpoint_step"),
            "reward": ep.get("reward"), "r_opt": ep.get("r_opt"), "profit": ep.get("profit_usd"),
            "p_opt": (ep.get("references") or {}).get("p_opt"), "date": t["date"], "point": t["settlement_point"],
            "region": t["region"], "archetype": b.get("archetype"),
            "battery": f"{b['p_dis_mw']:g} MW / {b['energy_mwh']:g} MWh",
            "truncated": ep.get("truncated_at") is not None, "interest": round(interest(t["prices"]), 3),
            **({"p_anchor": blind["p_anchor"], "anchor_r_opt": blind["r_opt_anchor"],
                "beats_anchor": (ep.get("profit_usd") or 0) > blind["p_anchor"] + DEGENERATE_EPS} if blind else {})}


def interest(p: list[float]) -> float:
    """How much a day shows: negative midday hours and an evening ramp well above the median."""
    med = sorted(p)[12]
    return sum(1 for x in p[9:17] if x < 0) + min(4.0, max(p[16:22]) / max(10.0, med))


def real(e: dict) -> bool:
    return not e["model"].startswith("reference/")


def pick_hero(entries: list[dict], wanted: str | None) -> dict | None:
    if wanted:
        return next((e for e in entries if e["id"] == wanted), None)
    day = [e for e in entries if e["task_id"] == HERO_TASK]
    if runs := [e for e in day if real(e)]:
        return max(runs, key=lambda e: (e["reward"] or 0, e["bundle"] == "full"))
    if others := [e for e in entries if real(e) and e["tier"] == "foresight"]:
        return max(others, key=lambda e: ((e["reward"] or 0) >= 0.85, e["interest"], e["reward"] or 0))
    pool = [e for e in day if e["model"] == "reference/dp-optimum"] or entries
    return max(pool, key=lambda e: e["reward"] or 0, default=None)


def feature(entries: list[dict], wanted: str | None, out: Path) -> list[dict]:
    """The hero day, then the blind-tier run that beats its anchor by the most hindsight capture and the one that
    trails it furthest, each with its blurb."""
    hero = pick_hero(entries, wanted)
    blind = [e for e in entries if real(e) and e["tier"] == "blind" and "anchor_r_opt" in e]
    beats = max((e for e in blind if e["beats_anchor"]), key=lambda e: e["r_opt"] - e["anchor_r_opt"], default=None)
    trails = min(blind, key=lambda e: e["reward"], default=None)
    picked = []
    for e, kind in ((hero, "hero"), (beats, "beats"), (trails, "trails")):
        if e:
            ep = json.loads((out / "runs" / e["url"]).read_text())
            e |= {"featured": kind, "blurb": blurb(ep, e, kind), "hero_moment": moment(ep, kind)}
            if kind == "hero":
                e["hero"] = True
            picked.append(e)
    return picked


def hour(h: int) -> str:
    return "noon" if h == 12 else "midnight" if h == 0 else f"{h % 12 or 12} {'am' if h < 12 else 'pm'}"


def peak(ep: dict) -> int:
    p = ep["task"]["prices"]
    return max(range(24), key=lambda h: p[h])


def evening(ep: dict) -> float:
    """The hour a hero picture shows: the evening peak (4 pm to 10 pm), a little past the half hour."""
    p = ep["task"]["prices"]
    return max(range(16, 22), key=lambda h: p[h]) + 0.6


def moment(ep: dict, kind: str) -> str:
    return "the evening ramp" if kind == "hero" else f"the day's top price, at {hour(peak(ep))}"


def blurb(ep: dict, e: dict, kind: str) -> str:
    p, place = ep["task"]["prices"], REGIONS.get(e["region"], e["region"])
    top = f"${p[peak(ep)]:.0f}/MWh at {hour(peak(ep))}"
    if kind == "beats":
        return (f"Blind: with only the days before to go on, the agent captured {e['r_opt']:.0%} of what hindsight "
                f"could make, where the better of the two forecasters captured {e['anchor_r_opt']:.0%}. The day topped "
                f"out at {top}.")
    if kind == "trails":
        made = f"made ${e['profit']:,.0f}" if e["profit"] >= 0 else f"lost ${-e['profit']:,.0f}"
        return (f"Blind: the agent's plan {made} on a day the better forecaster's plan made ${e['p_anchor']:,.0f}; "
                f"reward {e['reward']:.2f} against its 1.0. The day topped out at {top}.")
    neg = sum(1 for x in p if x < 0)
    if neg:
        return (f"{place} on a spring day: {neg} hours of negative prices around midday, when the battery is paid to "
                f"charge, then an evening ramp to {top}.")
    return f"{place}: the day peaks at {top}."


def record(*args: str) -> None:
    subprocess.run([sys.executable, str(ROOT / "scripts" / "record.py"), *args], check=True)


def thumbnail(out: Path, e: dict) -> None:
    path = out / "runs" / e["url"]
    ep = json.loads(path.read_text())
    thumb = out / "thumbs" / f"{e['id']}.jpg"
    hero = e["featured"] == "hero"
    record("--episode", str(path), "--weather", str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--thumb",
           str(thumb), "--t", str(evening(ep) if hero else peak(ep) + 0.6), "--extra",
           "ui=0&shot=ramp" if hero else "ui=0")
    e["thumb"] = f"thumbs/{thumb.name}"


def still(out: Path, e: dict) -> None:
    """The hero day at its evening ramp, 1600x900: the featured card's picture and the README's."""
    path = out / "runs" / e["url"]
    record("--episode", str(path), "--weather", str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--still",
           str(out / "thumbs" / "hero.jpg"), "--size", "1600x900", "--t", str(evening(json.loads(path.read_text()))),
           "--extra", "ui=0&shot=ramp")
    e["thumb"] = "thumbs/hero.jpg"


def readme(entries: list[dict], hero: dict | None) -> str:
    counts = Counter(e["model_label"] or e["model"] for e in entries if real(e))
    refs = sum(not real(e) for e in entries)
    models = ", ".join(f"{n:,} runs of {m}" for m, n in counts.most_common()) + (
        f" and {refs} reference episodes (the DP optimum and the baselines)" if refs else "")
    caption = (f"{hero['date']} at {hero['point']} ({hero['archetype']}, {hero['battery']}): {hero['blurb']} "
               f"{hero['model_label'] or hero['model']} scored {hero['reward']:.3f}." if hero else "")
    fields = {"count": f"{len(entries):,}", "models": models, "hero_still": "hero.jpg",
              "hero_url": hero["url"] if hero else "", "hero_caption": caption, "repo": REPO, "dataset": DATASET,
              "app": APP,
              "hero_alt": f"The battery yard at {hero['point']} on {hero['date']}" if hero else "The battery yard"}
    text = README
    for k, v in fields.items():
        text = text.replace("{" + k + "}", v)
    return text


if __name__ == "__main__":
    sys.exit(main())
