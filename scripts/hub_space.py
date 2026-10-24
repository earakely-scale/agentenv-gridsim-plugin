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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import weather as wx  # noqa: E402

from gridsim_core import live  # noqa: E402
from gridsim_core.contract import DEGENERATE_EPS  # noqa: E402
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

WEB = ROOT / "src" / "agentenv_gridsim" / "web"
PACKS = ("ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "showcase", "fixtures",
         "ercot-dam-v1-train")
HERO_TASK = "dam-v1-2025-03-15-HB_WEST-1h-t"
LIVE_PACKS = ("gridsim-live-showcase", "gridsim-live-eval", "gridsim-live-test-2025", "gridsim-live-rtcb",
              "fixtures-live", "gridsim-live-train")
LIVE_HERO_TASK = "live-v2-2023-09-06-HB_NORTH-2h-l"
LABELS = {"openai/gpt-6.1-sol": "GPT-6.1 Sol"}
CPT = ZoneInfo("America/Chicago")
SEVERITY = {"EEA3": 7, "EEA2": 6, "EEA1": 5, "Emergency": 5, "conservation": 4, "Watch": 3, "Warning": 3, "Advisory": 2,
            "OCN": 1}
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

**The featured day,** {hero_caption}

This Space holds **replays only**: every page plays back a recorded episode (`runs/*.json`, schema
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
    entries, rejected, skipped, views = [], [], [], {}
    fixture_ids, seen = fixtures(), set()
    for folder in args.runs:
        for f in sorted(folder.rglob("*.json")):
            if f.name == "index.json" or "raw" in f.relative_to(folder).parts[:-1]:
                continue
            ep = json.loads(f.read_text())
            schema = ep.get("schema") if isinstance(ep, dict) else None
            if schema in ("gridsim.levelup/v1", "gridsim.race/v1"):
                views[schema.split(".")[1].split("/")[0]] = ep
                continue
            if schema not in ("gridsim.episode/v1", live.EPISODE_SCHEMA):
                continue
            if ep["episode_id"] in seen:
                continue
            seen.add(ep["episode_id"])
            v2 = schema == live.EPISODE_SCHEMA
            if v2 and ep["task_id"] in fixture_ids:
                skipped.append(f)
                continue
            task = live_tasks().get(ep["task_id"]) if v2 else tasks.get(ep["task_id"])
            if why := (verify_live(ep, task) if v2 else verify(ep, task)):
                rejected.append((f, why))
                continue
            name = f"{ep['episode_id']}.json"
            (out / "runs" / name).write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
            entries.append(live_entry(ep, name) if v2 else entry(ep, name, task))
    for e in entries:
        side = wx.sidecar(e["point"], e["date"], args.weather)
        if not (out / "weather" / side.name).exists():
            shutil.copy(side, out / "weather" / side.name)
    featured = feature([e for e in entries if e["version"] == "v1"], args.hero, out)
    if lv := feature_live(entries, out):
        featured.append(lv)
    if args.thumbs:
        for e in featured[1:]:
            thumbnail(out, e)
        still(out, featured[0])
    training = write_views(views, entries, out, args.thumbs)
    index = [{k: v for k, v in e.items() if v is not None} for e in entries]
    (out / "runs" / "index.json").write_text(json.dumps({"schema": "gridsim.runs/v1", "episodes": index}
                                                        | ({"training": training} if training else {}),
                                                        separators=(",", ":")))
    (out / "README.md").write_text(readme(entries, featured[0] if featured else None, training))
    for f, why in rejected:
        print(f"REJECTED {f}: {why}")
    if skipped:
        print(f"skipped {len(skipped)} episodes on CI fixture days (synthetic notices)")
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


_LIVE: dict | None = None


def live_tasks() -> dict:
    global _LIVE
    if _LIVE is None:
        _LIVE = {t["task_id"]: t for pack in LIVE_PACKS for t in load_pack(pack)}
    return _LIVE


def write_views(views: dict, entries: list[dict], out: Path, thumbs: bool) -> dict | None:
    """The training views whose every episode made it into the Space, as runs/<view>.json, with thumbnails."""
    ids = {e["id"] for e in entries}
    training = {}
    for kind, m in views.items():
        refs = [x["episode_id"] for x in m.get("frames") or m.get("lanes") or []]
        if not refs or not set(refs) <= ids:
            print(f"the {kind} view is left out: {len(set(refs) - ids)} of its episodes are not in the Space")
            continue
        (out / "runs" / f"{kind}.json").write_text(json.dumps(m, separators=(",", ":")))
        training[kind] = {"url": f"runs/{kind}.json", "task_id": m["task_id"]} | (
            {"model": m["model"], "gain": m["gain"], "note": m["note"], "frames": len(m["frames"])}
            if kind == "levelup" else {"lanes": [x["label"] for x in m["lanes"]]})
        if thumbs:
            e = next(e for e in entries if e["id"] == refs[0])
            thumb = out / "thumbs" / f"{kind}.jpg"
            record("--view", f"{kind}={out / 'runs' / f'{kind}.json'}", "--weather",
                   str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--thumb", str(thumb), "--t",
                   str(3.2 + 6.5 * len(refs) + 1.5 if kind == "levelup" else 2 + 72 * 19.5 / 24))
            training[kind]["thumb"] = f"thumbs/{thumb.name}"
    return training or None


def fixtures() -> set[str]:
    """CI fixture days that are in no real live pack."""
    real_ids = {t["task_id"] for p in LIVE_PACKS if p != "fixtures-live" for t in load_pack(p)}
    return {t["task_id"] for t in load_pack("fixtures-live")} - real_ids


def verify_live(ep: dict, task: dict | None) -> str | None:
    """Every recorded call replayed through a fresh Session on the pack's day and notices gives the recorded output;
    the day's profit and reward must match."""
    if task is None:
        return "not in any live pack"
    s = live.Session(task, ep["tier"])
    for i, st in enumerate(ep["steps"]):
        args = dict(st["args"])
        if st["tool"] == live.NOTICE_TOOL:
            args.setdefault("_via", "trigger")
        if json.loads(s.call(st["tool"], args)) != st["output"]:
            return f"step {i} ({st['tool']}) does not replay"
    if not s.done:
        s.end_day()
    g = s.grade()
    if abs(g["profit_usd"] - ep["profit_usd"]) > 0.01:
        return f"profit {ep['profit_usd']} != {g['profit_usd']}"
    if abs(g["reward"] - ep["reward"]) > 1e-6:
        return f"reward {ep['reward']} != {g['reward']}"
    return None


def live_entry(ep: dict, url: str) -> dict:
    t, b, r = ep["task"], ep["task"]["battery"], ep.get("references") or {}
    top = max(ep.get("notices") or [], key=lambda n: SEVERITY.get(n.get("level"), 0), default=None)
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label"), "version": "v2", "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "reward": ep.get("reward"),
            "r_opt": ep.get("capture_vs_hindsight"), "profit": ep.get("profit_usd"), "p_opt": r.get("p_hind"),
            "p_anchor": r.get("p_roll"), "p_naive": r.get("p_naive"), "naive_reward": ep.get("naive_reward"),
            "beats_anchor": ep.get("beats_anchor"), "date": t["date"], "point": t["settlement_point"],
            "region": t["region"], "archetype": b.get("archetype"),
            "battery": f"{b['p_dis_mw']:g} MW / {b['energy_mwh']:g} MWh", "watches": len(ep["watches"]),
            "notices": len(ep.get("notices") or []), "top_notice": top and top.get("level"),
            "rt_max": max(t["rt"]), "interest": round(max(t["rt"]) / max(10.0, sorted(t["prices"])[12]), 3)}


def feature_live(entries: list[dict], out: Path) -> dict | None:
    """The v2 preview's featured day: the best real run on the hero day, else its rolling anchor, else the live day
    with the most urgent bulletin."""
    pool = [e for e in entries if e["version"] == "v2"]
    day = [e for e in pool if e["task_id"] == LIVE_HERO_TASK]
    e = (max([x for x in day if real(x)], key=lambda x: x["reward"] or 0, default=None)
         or next((x for x in day if x["model"] == "reference/rolling-anchor"), None)
         or max(pool, key=lambda x: (SEVERITY.get(x["top_notice"], 0), x["interest"]), default=None))
    if e is None:
        return None
    ep = json.loads((out / "runs" / e["url"]).read_text())
    e |= {"featured": "live", "blurb": live_blurb(ep), "hero_moment": "the most urgent bulletin's watch",
          "t_moment": live_moment(ep)}
    return e


def live_moment(ep: dict) -> float:
    w = max((x for x in ep["watches"] if x["index"] > 0), key=lambda x: max(
        [SEVERITY.get(n["level"], 0) for n in ep["notices"] if n["event_id"] in x["notices"]], default=0))
    hh, mm = w["time"].split(" ")[1].split(":")
    return int(hh) + int(mm) / 60 + 0.3


def hm(minute: int) -> str:
    h, m = divmod(minute, 60)
    return f"{h % 12 or 12}{f':{m:02d}' if m else ''} {'am' if h % 24 < 12 else 'pm'}"


def clock(label: str) -> str:
    return hm(int(label[-5:-3]) * 60 + int(label[-2:]))


def live_blurb(ep: dict) -> str:
    """What the featured live day shows: the most urgent bulletin, when the agent read it and whether it re-planned
    after, the real-time peak, and its profit beside the anchor's and hindsight's."""
    t, r = ep["task"], ep.get("references") or {}
    region = REGIONS.get(t["region"], t["region"])
    rt = max(range(96), key=lambda i: t["rt"][i])
    who = ep.get("model_label") or LABELS.get(ep.get("model"), (ep.get("model") or "the agent").split("/")[-1])
    peak = f"real-time prices reach ${t['rt'][rt]:,.0f}/MWh at {hm(15 * rt)}"
    tail = (f"It makes ${ep['profit_usd']:,.0f}, against the rolling anchor's ${r.get('p_roll', 0):,.0f} and "
            f"hindsight's ${r.get('p_hind', 0):,.0f}.")
    top = max(ep["notices"], key=lambda n: SEVERITY.get(n.get("level"), 0), default=None)
    if not top or top.get("watch") is None:
        return f"{region}, live: {peak}. {tail}"
    w = ep["watches"][top["watch"]]
    at = datetime.fromisoformat(top["issued_at"].replace("Z", "+00:00")).astimezone(CPT)
    replans = any(c["accepted"] and c["watch"] >= top["watch"] and c["tool"] == "commit_schedule"
                  for c in ep.get("commits") or [])
    posted = hm(at.hour * 60 + at.minute)
    return (f"{region}, live: ERCOT posts its {top['level']} notice at {posted}. {who} reads it at the "
            f"{clock(w['time'])} watch, with the freeze line at {clock(w['freeze_line'])}, and "
            f"{'re-plans' if replans else 'holds its plan'} as {peak}. {tail}")


def entry(ep: dict, url: str, task: dict | None) -> dict:
    t, b = ep["task"], ep["task"]["battery"]
    blind = ((task or {}).get("refs") or {}).get("blind") if ep["tier"] == "blind" else None
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "version": "v1", "model_label": ep.get("model_label"), "tier": ep["tier"], "bundle": ep.get("bundle"),
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
    t = e.get("t_moment") or (evening(ep) if hero else peak(ep) + 0.6)
    record("--episode", str(path), "--weather", str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--thumb",
           str(thumb), "--t", str(t), "--extra", "ui=0&shot=establish" if hero or "t_moment" in e else "ui=0")
    e["thumb"] = f"thumbs/{thumb.name}"


def still(out: Path, e: dict) -> None:
    """The hero day at its evening ramp, 1600x900: the featured card's picture and the README's."""
    path = out / "runs" / e["url"]
    record("--episode", str(path), "--weather", str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--still",
           str(out / "thumbs" / "hero.jpg"), "--size", "1600x900", "--t", str(evening(json.loads(path.read_text()))),
           "--extra", "ui=0&shot=establish")
    e["thumb"] = "thumbs/hero.jpg"


def readme(entries: list[dict], hero: dict | None, training: dict | None = None) -> str:
    v2 = [e for e in entries if e["version"] == "v2"]
    entries = [e for e in entries if e["version"] == "v1"]
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
    if v2:
        live_counts = Counter(e["model_label"] or e["model"] for e in v2)
        lv = next((e for e in v2 if e.get("featured") == "live"), None)
        text = text.replace("\n## Links\n", LIVE_README.format(
            n=len(v2), models=", ".join(f"{n} of {LABELS.get(m, m)}" for m, n in live_counts.most_common()),
            board=live_board(),
            hero=f"\n\n**The featured live day,** [{lv['date']} at {lv['point']}]"
                 f"({APP}/index.html?episode=runs/{lv['url']}): {lv['blurb']}" if lv else "") + "\n## Links\n")
    if training:
        lines = ["", "## Training views", ""]
        if lu := training.get("levelup"):
            name = lu["model"].split("/")[-1]
            lines.append(f"- [LEVEL UP]({APP}/index.html?levelup=runs/levelup.json): {name} on one held-out day "
                         f"({lu['task_id']}) at each of {lu['frames']} checkpoints, reward gain {lu['gain']:+.2f}."
                         + (f" {lu['note']}." if lu.get("note") else ""))
        if rc := training.get("race"):
            lines.append(f"- [The race]({APP}/index.html?race=runs/race.json): {', '.join(rc['lanes'])} on the same "
                         f"day ({rc['task_id']}).")
        text = text.replace("\n## Links\n", "\n".join(lines) + "\n\n## Links\n")
    return text


LIVE_README = """
## v2 preview: The Live Grid (provisional anchor)

{n} live battery-days ({models}), schema `gridsim.episode/v2`. The agent commits a day-ahead position at 2 pm the day
before, then re-plans its 15-minute schedule at watches through the day, never inside the freeze line an hour ahead,
while real-time prices settle and ERCOT and NWS bulletins arrive (paraphrased summaries only). Settlement is
two-settlement: the position at day-ahead prices, every deviation at real-time prices. R puts idle at 0.2 and the
rolling anchor at 1.0; the anchor is provisional and sits near naive on many days, so each replay also shows hindsight
capture. Every v2 episode was replayed call by call through `gridsim_core.live` when the Space was built.{board}{hero}
"""


def live_board() -> str:
    """The v2 pilot's headline from results/eval-v2.json: hindsight capture first, R second."""
    card = ROOT / "results" / "eval-v2.json"
    if not card.exists():
        return ""
    c = json.loads(card.read_text())
    b = c["baselines"].get("foresight") or {}
    rows = [f"{LABELS.get(m['model'], m['model'])} captures {m['hindsight_capture']:.0%} of hindsight over "
            f"{m['tasks']} days (R {m['mean']:.3f})" for m in c["models"]]
    return (f"\n\nThe pilot, pre-registered: {'; '.join(rows)}; naive captures "
            f"{b.get('naive_capture', 0):.0%} (R {b.get('naive', 0):.3f}) and the rolling anchor "
            f"{b.get('anchor_capture', 0):.0%} (R 1.000) on the same days.")


if __name__ == "__main__":
    sys.exit(main())
