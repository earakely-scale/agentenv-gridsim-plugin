"""Assemble the static Hugging Face Space: the viewer (web/), every Episode JSON under the runs folders re-verified
through gridsim_core (a .jsonl holds one per line), the weather sidecars, a runs index with the featured days and the
README. Nothing is uploaded.

usage: python scripts/hub_space.py [--runs results/runs results/train] [--out build/hub/space] [--thumbs]
       [--hero EPISODE_ID]
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

import forecast_view  # noqa: E402
import hybrid_view  # noqa: E402
import weather as wx  # noqa: E402

from gridsim_core import forecast, hybrid, live, market  # noqa: E402
from gridsim_core.contract import DEGENERATE_EPS  # noqa: E402
from gridsim_core.grade import grade  # noqa: E402
from gridsim_core.physics import simulate  # noqa: E402
from gridsim_core.task import data_root, load_pack  # noqa: E402

WEB = ROOT / "src" / "agentenv_gridsim" / "web"
PACKS = ("ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "showcase", "fixtures",
         "ercot-dam-v1-train")
HERO_TASK = "dam-v1-2025-03-15-HB_WEST-1h-t"
LIVE_PACKS = ("gridsim-live-showcase", "gridsim-live-eval", "gridsim-live-test-2025", "gridsim-live-rtcb",
              "fixtures-live", "gridsim-live-train")
LIVE_HERO_TASK = "live-v2-2023-09-06-HB_NORTH-2h-l"
HYBRID_PACKS = ("ercot-hybrid-v3-showcase", "ercot-hybrid-v3-eval", "ercot-hybrid-v3-rtcb", "fixtures-hybrid",
                "ercot-hybrid-v3-train")
HYBRID_HERO_TASKS = ("hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150",
                     "hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150")
FORECAST_PACKS = ("ercot-front-v4-showcase", "ercot-front-v4-eval", "ercot-front-v4-rtcb", "fixtures-forecast",
                  "ercot-front-v4-train")
FORECAST_HERO = "fern-0124"
MARKET_PACKS = ("gridsim-market-showcase", "gridsim-market-eval", "gridsim-market-rtcb", "fixtures-market",
                "gridsim-market-train")
MARKET_NAMES = {"reference/disclosure-anchor": "Disclosure anchor (reference)",
                "reference/anchor-hedged": "Anchor at the desk, with a CfD (reference)",
                "reference/replay-a": "Seat A's real offers (reference)", "reference/idle": "Idle (reference)",
                "reference/price-taker": "Price-taker (reference)",
                "reference/max-withhold": "Max-withhold (reference)"}
MARKET_HERO = "aug24-0820"
CARDS = {2: "eval-v2.json", 3: "eval-v3c.json", 4: "eval-v4b.json", 5: "eval-v5b.json"}
LABELS = {"openai/gpt-6.1-sol": "GPT-6.1 Sol", "reference/rolling-anchor": "the rolling anchor (reference)",
          "reference/rolling-p50": "the rolling anchor (reference)",
          "reference/persistence": "the blind re-planner (reference)",
          "reference/naive-dam": "the naive DAM bidder (reference)",
          "reference/naive": "naive (reference)", "reference/as-hog": "AS-hog (reference)",
          "reference/solar-sponge": "the solar sponge (reference)",
          "reference/v2-energy-only": "v2's energy-only plan (reference)",
          "reference/disclosure-anchor": "the disclosure anchor (reference)",
          "reference/anchor-hedged": "the disclosure anchor with a CfD (reference)",
          "reference/replay-a": "seat A's real offers (reference)", "reference/idle": "idle (reference)",
          "reference/price-taker": "the price-taker (reference)", "reference/max-withhold": "max-withhold (reference)"}
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
    p.add_argument("--runs", type=Path, nargs="*", default=[ROOT / "results" / "runs", ROOT / "results" / "train"])
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
        for f in sorted(folder.rglob("*.json*")):
            if f.suffix not in (".json", ".jsonl") or f.name == "index.json" \
                    or "raw" in f.relative_to(folder).parts[:-1]:
                continue
            text = f.read_text()
            rows = [json.loads(x) for x in text.splitlines() if x.strip()] if f.suffix == ".jsonl" \
                else [json.loads(text)]
            for ep in rows:
                schema = ep.get("schema") if isinstance(ep, dict) else None
                if schema in ("gridsim.levelup/v1", "gridsim.race/v1"):
                    views[schema.split(".")[1].split("/")[0]] = ep
                    continue
                if schema not in ("gridsim.episode/v1", live.EPISODE_SCHEMA, hybrid.EPISODE_SCHEMA,
                                  forecast.EPISODE_SCHEMA, market.EPISODE_SCHEMA):
                    continue
                if ep["episode_id"] in seen:
                    continue
                seen.add(ep["episode_id"])
                v2, v3 = schema == live.EPISODE_SCHEMA, schema == hybrid.EPISODE_SCHEMA
                if schema == forecast.EPISODE_SCHEMA:
                    task = forecast_tasks().get(ep["task_id"])
                    if why := verify_forecast(ep, task):
                        rejected.append((f, why))
                        continue
                    ep = ep | {"race": forecast_race(task, ep["tier"], ep.get("model"))}
                    name = f"{ep['episode_id']}.json"
                    (out / "runs" / name).write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
                    entries.append(forecast_entry(ep, name, task))
                    continue
                if schema == market.EPISODE_SCHEMA:
                    task = market_tasks().get(ep["task_id"])
                    if why := verify_market(ep, task):
                        rejected.append((f, why))
                        continue
                    ep = ep | {"seats_view": seats_view(task),
                               "p_br_rt": ((task.get("refs") or {}).get(ep["tier"]) or {}).get("p_br_rt")}
                    name = f"{ep['episode_id']}.json"
                    (out / "runs" / name).write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
                    entries.append(market_entry(ep, name, task))
                    continue
                if (v2 and ep["task_id"] in fixture_ids) or (v3 and ep["task_id"] in hybrid_fixtures()):
                    skipped.append(f)
                    continue
                task = (hybrid_tasks().get(ep["task_id"]) if v3 else live_tasks().get(ep["task_id"]) if v2
                        else tasks.get(ep["task_id"]))
                if why := (verify_hybrid(ep, task) if v3 else verify_live(ep, task) if v2 else verify(ep, task)):
                    rejected.append((f, why))
                    continue
                if v3:
                    ep = ep | {"race": race(task, ep["tier"], ep.get("model"))}
                name = f"{ep['episode_id']}.json"
                (out / "runs" / name).write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
                entries.append(hybrid_entry(ep, name) if v3 else live_entry(ep, name) if v2 else entry(ep, name, task))
    if any(e["version"] == "v4" and not e["synthetic"] for e in entries):
        dropped = [e for e in entries if e["version"] == "v4" and e["synthetic"]]
        for e in dropped:
            (out / "runs" / e["url"]).unlink()
        entries = [e for e in entries if e not in dropped]
        if dropped:
            print(f"v4: dropped {len(dropped)} episodes on CI fixture windows (synthetic vintages); real packs exist")
    for e in entries:
        side = (wx.window_sidecar(e["point"], e["date"], e["days"], args.weather) if e["version"] == "v4"
                else wx.sidecar(e["point"], e["date"], args.weather, d1=e["version"] == "v5"))
        if not (out / "weather" / side.name).exists():
            shutil.copy(side, out / "weather" / side.name)
        e["weather"] = f"weather/{side.name}"
    featured = feature([e for e in entries if e["version"] == "v1"], args.hero, out)
    if lv := feature_live(entries, out):
        featured.append(lv)
    if hv := feature_hybrid(entries, out):
        featured.append(hv)
    if fv := feature_forecast(entries, out):
        featured.append(fv)
    if mv := feature_market(entries, out):
        featured.append(mv)
    hero = next((e for e in featured if e.get("hero")), None)
    if args.thumbs:
        for e in featured:
            if e is not hero:
                thumbnail(out, e)
        if hero:
            still(out, hero)
    training = write_views(views, entries, out, args.thumbs)
    index = [{k: v for k, v in e.items() if v is not None and k != "weather"} for e in entries]
    (out / "runs" / "index.json").write_text(json.dumps({"schema": "gridsim.runs/v1", "episodes": index}
                                                        | ({"training": training} if training else {}),
                                                        separators=(",", ":")))
    (out / "README.md").write_text(readme(entries, hero, training))
    for f, why in rejected:
        print(f"REJECTED {f}: {why}")
    if skipped:
        print(f"skipped {len(skipped)} episodes on CI fixture days (synthetic notices)")
    print(f"v3: {sum(e['version'] == 'v3' for e in entries)} episodes replayed through gridsim_core.hybrid")
    print(f"v4: {sum(e['version'] == 'v4' for e in entries)} episodes replayed through gridsim_core.forecast")
    print(f"v5: {sum(e['version'] == 'v5' for e in entries)} episodes replayed through gridsim_core.market")
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
            {"model": m["model"], "gain": m["gain"], "note": m["note"], "frames": len(m["frames"]),
             "overall": overall(m.get("context") or {}), "reading": (m.get("context") or {}).get("reading")}
            if kind == "levelup" else {"lanes": [x["label"] for x in m["lanes"]]} | (
                {"verdict": m["verdict"]} if m.get("verdict") else {}))
        if thumbs:
            e = next(e for e in entries if e["id"] == refs[0])
            thumb = out / "thumbs" / f"{kind}.jpg"
            record("--view", f"{kind}={out / 'runs' / f'{kind}.json'}", "--weather",
                   str(out / "weather" / f"{e['date']}_{e['point']}.json"), "--thumb", str(thumb), "--t",
                   str(5 + 6.5 * len(refs) + 1.5 if kind == "levelup" else 2 + 72 * 19.5 / 24))
            training[kind]["thumb"] = f"thumbs/{thumb.name}"
    return training or None


def capture(p: float | None, p_idle: float | None, p_hind: float | None) -> float | None:
    """Hindsight capture C = (P - P_idle)/(P_hind - P_idle), the cross-version headline (docs/REWARD-SCALES.md)."""
    if p is None or p_idle is None or p_hind is None or p_hind - p_idle <= DEGENERATE_EPS:
        return None
    return (p - p_idle) / (p_hind - p_idle)


def versus(d: dict, what: str) -> str:
    """A paired gap with its CI, read as above, below or level with ``what`` by whether the CI excludes 0."""
    lo, hi = d["ci95"]
    where = "above" if lo > 0 else "below" if hi < 0 else "level with"
    return f"{where} {what}: {d['mean']:+.3f} ({lo:+.3f} to {hi:+.3f})"


def card(version: int) -> dict | None:
    path = ROOT / "results" / CARDS[version]
    return json.loads(path.read_text()) if path.is_file() else None


def overall(c: dict) -> str | None:
    """The run over every held-out day, for the list card and the README."""
    if c.get("trained") is None:
        return None
    arc = "".join(f" to {a['reward']:.2f} at step {a['step']} of {a['label']}" for a in c.get("arms") or []
                  if a.get("label")) or f" to {c['trained']:.2f} (GRPO)"
    return (f"{c.get('tasks', '')} held-out days the model goes from {c['base']:.2f} (base) to {c['sft']:.2f} (SFT)"
            f"{arc}; the greedy rule scores {c.get('greedy', float('nan')):.2f}"
            + (f", the threshold rule {c['threshold']:.2f}" if c.get("threshold") is not None else ""))


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


_HYBRID: dict | None = None
_RACE: dict = {}


def hybrid_tasks() -> dict:
    global _HYBRID
    if _HYBRID is None:
        _HYBRID = {}
        for pack in HYBRID_PACKS:
            for t in load_pack(pack):
                _HYBRID.setdefault(t["task_id"], t)
    return _HYBRID


def hybrid_fixtures() -> set[str]:
    """CI hybrid fixture days that are in no real hybrid pack."""
    real_ids = {t["task_id"] for p in HYBRID_PACKS if p != "fixtures-hybrid" for t in load_pack(p)}
    return {t["task_id"] for t in load_pack("fixtures-hybrid")} - real_ids


def verify_hybrid(ep: dict, task: dict | None) -> str | None:
    """Every recorded call replayed through a fresh gridsim_core.hybrid Session on the pack's day gives the recorded
    output; the day's profit and reward must match."""
    if task is None:
        return "not in any hybrid pack"
    s = hybrid.Session(task, ep["tier"])
    for i, st in enumerate(ep["steps"]):
        args = dict(st["args"])
        if st["tool"] == hybrid.NOTICE_TOOL:
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


def race(task: dict, tier: str, model: str | None) -> list[dict]:
    """The v3 replay's race lanes (hybrid_view.lanes), solved once per day, tier and reference."""
    key = (task["task_id"], tier, hybrid_view.SELF.get(model))
    if key not in _RACE:
        _RACE[key] = hybrid_view.lanes(task, tier, model)
    return _RACE[key]


def hybrid_entry(ep: dict, url: str) -> dict:
    t, st, r = ep["task"], ep["task"]["site"], ep.get("references") or {}
    deps = [n for n in ep.get("notices") or [] if n.get("deploy")]
    c = ep.get("cash") or {}
    as_rev = (c.get("as_da") or 0) + (c.get("as_rt") or 0)
    gain = max(0.0, (c.get("energy_da") or 0) + (c.get("energy_rt") or 0) - (r.get("p_idle") or 0))
    curtailed = sum(h["curtailed_mw"] for h in ep["hours"])
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label"), "version": "v3", "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "reward": ep.get("reward"),
            "r_opt": ep.get("capture_vs_hindsight"), "capture": ep.get("capture_vs_hindsight"),
            "profit": ep.get("profit_usd"), "p_opt": r.get("p_hind"),
            "p_anchor": r.get("p_anchor"), "beats_anchor": ep.get("beats_anchor"), "date": t["date"],
            "point": t["settlement_point"], "region": t["region"], "era": t.get("era"),
            "battery": f"PV {st['pv_mwac']:g} MWac · {st['bess']['p_mw']:g} MW / {st['bess']['e_mwh']:g} MWh",
            "watches": len(ep["watches"]), "deployments": len(deps),
            "as_share": round(as_rev / (as_rev + gain), 3) if as_rev + gain > 1e-6 else None,
            "curtailed_mwh": round(curtailed, 1), "neg_hours": sum(1 for p in t["rt"] if p < 0),
            "interest": round(len(deps) + min(4.0, max(t["rt"]) / max(10.0, sorted(t["prices"])[12])), 3)}


_FORECAST: dict | None = None
_FRACE: dict = {}


def forecast_tasks() -> dict:
    global _FORECAST
    if _FORECAST is None:
        _FORECAST = {}
        for pack in FORECAST_PACKS:
            if (data_root() / pack).is_dir():
                for t in load_pack(pack):
                    _FORECAST.setdefault(t["task_id"], t)
    return _FORECAST


def verify_forecast(ep: dict, task: dict | None) -> str | None:
    """Every recorded call replayed through a fresh gridsim_core.forecast Session on the pack's window gives the
    recorded output; the window's profit and reward must match."""
    if task is None:
        return "not in any forecast pack"
    s = forecast.Session(task, ep["tier"], source=ep.get("source"))
    for i, st in enumerate(ep["steps"]):
        args = dict(st["args"])
        if st["tool"] == forecast.NOTICE_TOOL:
            args.setdefault("_via", "trigger")
        if json.loads(s.call(st["tool"], args)) != st["output"]:
            return f"step {i} ({st['tool']}) does not replay"
    if not s.done:
        s.end_window()
    g = s.grade()
    if abs(g["profit_usd"] - ep["profit_usd"]) > 0.01:
        return f"profit {ep['profit_usd']} != {g['profit_usd']}"
    if abs(g["reward"] - ep["reward"]) > 1e-6:
        return f"reward {ep['reward']} != {g['reward']}"
    return None


def forecast_race(task: dict, tier: str, model: str | None) -> list[dict]:
    """The v4 replay's race lanes (forecast_view.lanes), solved once per window, tier and reference."""
    key = (task["task_id"], tier, forecast_view.SELF.get(model))
    if key not in _FRACE:
        _FRACE[key] = forecast_view.lanes(task, tier, model)
    return _FRACE[key]


def drift(ep: dict) -> float:
    """How far the price guide moved: per window hour the range of the RT P50 across the runs that covered it, in
    $/MWh, averaged over the window."""
    t, d1 = ep["task"], datetime.fromisoformat(ep["task"]["d1"]).replace(tzinfo=CPT)
    by: dict[int, list[float]] = {}
    for v in ep["vintages"]["series"]:
        if v["kind"] != "price" or v["key"] != t["settlement_point"]:
            continue
        h0 = round((datetime.fromisoformat(v["start"].replace("Z", "+00:00")) - d1).total_seconds() / 3600)
        for i, x in enumerate(v["fields"].get("rt_p50") or []):
            if 0 <= h0 + i < len(ep["hours"]):
                by.setdefault(h0 + i, []).append(x)
    spans = [max(x) - min(x) for x in by.values() if len(x) > 1]
    return round(sum(spans) / len(spans), 2) if spans else 0.0


def forecast_entry(ep: dict, url: str, task: dict) -> dict:
    t, st, r = ep["task"], ep["task"]["site"], ep.get("references") or {}
    deps = [n for n in ep.get("notices") or [] if n.get("deploy")]
    top = max((n for n in ep.get("notices") or [] if not n.get("deploy")),
              key=lambda n: SEVERITY.get(n.get("level"), 0), default=None)
    lite = ep["tier"] == "front-lite"
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label"), "version": "v4", "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "reward": ep.get("reward"), "r_opt": ep.get("r_hind"),
            "capture": capture(ep.get("profit_usd"), r.get("p_idle"), r.get("p_hind")),
            "profit": ep.get("profit_usd"), "p_opt": r.get("p_hind"), "p_anchor": r.get("p_anchor"),
            "p_blind": r.get("p_blind"), "beats_anchor": ep.get("beats_anchor"), "date": t["d1"],
            "days": len(ep["hours"]) // 24, "point": t["settlement_point"], "region": t["region"], "era": t.get("era"),
            "source": ep.get("source"),
            "battery": (f"{st['bess']['p_mw']:g} MW / {st['bess']['e_mwh']:g} MWh" if lite else
                        f"PV {st['pv_mwac']:g} MWac · {st['bess']['p_mw']:g} MW / {st['bess']['e_mwh']:g} MWh"),
            "watches": len(ep["watches"]), "deployments": len(deps), "top_notice": top and top.get("level"),
            "reads": len(ep.get("forecasts_served") or []), "drift": drift(ep),
            "synthetic": (ep.get("vintages") or {}).get("source") == "synthetic",
            "showcase": ((task or {}).get("tags") or {}).get("showcase"), "rt_max": max(t["rt"])}


def feature_forecast(entries: list[dict], out: Path) -> dict | None:
    """The v4 preview's featured window: the best real front-tier run on fern-0124, else its rolling anchor, else the
    window whose price guide drifted the most."""
    pool = [e for e in entries if e["version"] == "v4"]
    fern = [e for e in pool if e["showcase"] == FORECAST_HERO and e["tier"] == "front"]
    e = (max([x for x in fern if real(x)], key=lambda x: (x["reward"] or 0, x["profit"] or 0), default=None)
         or next((x for x in fern if x["model"] == "reference/rolling-p50"), None)
         or max([x for x in pool if x["tier"] == "front"] or pool, key=lambda x: (x["drift"], x["id"]), default=None))
    if e is None:
        return None
    ep = json.loads((out / "runs" / e["url"]).read_text())
    t, mom = forecast_moment(ep)
    e |= {"featured": "forecast", "blurb": forecast_blurb(ep, e) + (forecast_pilot(e) if real(e) else ""),
          "hero_moment": mom, "t_moment": t, "shot": "establish"}
    return e


def forecast_moment(ep: dict) -> tuple[float, str]:
    """The hour the card's picture shows: the dearest real-time hour of the window, a little past the half hour."""
    rt = ep["task"]["rt"]
    h = max(range(len(rt)), key=lambda i: rt[i])
    return h + 0.6, f"the window's top real-time price, {hour(h % 24)} on day {h // 24 + 1}"


def forecast_blurb(ep: dict, e: dict) -> str:
    t, r = ep["task"], ep.get("references") or {}
    region = REGIONS.get(t["region"], t["region"])
    who = ep.get("model_label") or LABELS.get(ep.get("model"), (ep.get("model") or "the agent").split("/")[-1])
    h = max(range(len(t["rt"])), key=lambda i: t["rt"][i])
    gates = sum(1 for x in ep.get("dam") or [] if not x.get("missed"))
    synth = (" The forecast vintages in this CI window are synthetic; prices, PV and the weather are real."
             if e["synthetic"] else "")
    days = len(ep["hours"]) // 24
    sold = [sum(max(0.0, x["x_da_mw"]) for x in ep["hours"][d * 24:(d + 1) * 24]) for d in range(days)]
    top = max(range(days), key=lambda d: sold[d])
    vs = (f"the rolling anchor's ${r['p_anchor']:,.0f}, " if real(e) and r.get("p_anchor") is not None else "")
    c, a = capture(ep["profit_usd"], r.get("p_idle"), r.get("p_hind")), capture(r.get("p_anchor"), r.get("p_idle"),
                                                                                 r.get("p_hind"))
    score = (f"C {c:.2f}" + (f" against the anchor's {a:.2f}" if real(e) and a is not None else "")
             + f"; R {ep['reward']:.2f}") if c is not None else f"R {ep['reward']:.2f}"
    book = (f" Its book: ${ep['cash']['as_da']:,.0f} of reserves; its largest day-ahead discharge, "
            f"{sold[top]:,.0f} MWh, on {t['dates'][top]}." if real(e) else "")
    return (f"{region}, {days} operating days from {t['d1']}: {who} bids each day's book at the 10 am DAM gate "
            f"the day before ({gates} of {days} gates) and re-plans at {len(ep['watches'])} watches as weather "
            f"runs and bulletins arrive. The price guide moves ${e['drift']:,.0f}/MWh between runs on an average hour; "
            f"real time reaches ${t['rt'][h]:,.0f}/MWh on day {h // 24 + 1}. It makes ${ep['profit_usd']:,.0f} "
            f"against {vs}the blind re-planner's ${r.get('p_blind', 0):,.0f} and hindsight's "
            f"${r.get('p_hind', 0):,.0f} ({score}).{book}" + synth)


def forecast_pilot(e: dict) -> str:
    """The v4 pilot's reading (results/eval-v4b.json, rules 4.1): Sol's front-tier hindsight capture against the rolling
    anchor's and the blind re-planner's, R second; a showcase window is display-only."""
    c = card(4)
    m = next((x for x in (c or {}).get("models") or [] if x["tier"] == "front"), None)
    if m is None:
        return ""
    lo, hi = m["capture"]["ci95"]
    return ((" This window is display-only, outside the pilot." if e["showcase"] else "")
            + f" In the pre-registered pilot (rules 4.1) on {m['tasks']} eval windows Sol's front capture is "
            f"{m['capture']['mean']:.3f} ({lo:.3f} to {hi:.3f}) against the rolling anchor's "
            f"{m['anchor_capture']:.3f}, "
            f"{versus(m['delta'], 'the anchor')}, and {versus(m['refs']['blind']['delta'], 'the blind re-planner')}; "
            f"R {m['mean']:.3f} on the anchor scale.")


def feature_hybrid(entries: list[dict], out: Path) -> dict | None:
    """The v3 preview's featured day: the best real reserves-tier run on the first hero day that has one, else the first
    hero day's rolling anchor, else the v3 day with the most deployments."""
    pool = [e for e in entries if e["version"] == "v3"]
    runs = [[x for x in pool if x["task_id"] == t and x["tier"] == "reserves" and real(x)] for t in HYBRID_HERO_TASKS]
    e = (next((max(rs, key=lambda x: x["reward"] or 0) for rs in runs if rs), None)
         or next((x for x in pool if x["task_id"] == HYBRID_HERO_TASKS[0] and x["model"] == "reference/rolling-anchor"),
                 None)
         or max(pool, key=lambda x: x["interest"], default=None))
    if e is None:
        return None
    ep = json.loads((out / "runs" / e["url"]).read_text())
    t, mom = hybrid_moment(ep)
    e |= {"featured": "hybrid", "blurb": hybrid_blurb(ep) + (hybrid_pilot(e) if real(e) else ""), "hero_moment": mom,
          "t_moment": t,
          "shot": "deploy" if "deployment" in mom else "ramp"}
    return e


def hybrid_moment(ep: dict) -> tuple[float, str]:
    """The first reserve deployment the plant holds an award for, else the evening peak."""
    for n in sorted((n for n in ep["notices"] if n.get("deploy")), key=lambda n: n["deploy"]["start_min"]):
        h = min(23, n["deploy"]["start_min"] // 60)
        if (ep["hours"][h]["awards"].get(n["deploy"]["product"]) or 0) > 0:
            return n["deploy"]["start_min"] / 60 + 0.35, "the first reserve deployment"
    return evening(ep), "the evening peak"


def hybrid_blurb(ep: dict) -> str:
    t, r = ep["task"], ep.get("references") or {}
    region = REGIONS.get(t["region"], t["region"])
    who = ep.get("model_label") or LABELS.get(ep.get("model"), (ep.get("model") or "the agent").split("/")[-1])
    deps = sorted((n for n in ep["notices"] if n.get("deploy")), key=lambda n: n["deploy"]["start_min"])
    names = {"rrs": "RRS", "ecrs": "ECRS", "nspin": "Non-Spin"}
    held = next((n for n in deps if ep["hours"][min(23, n["deploy"]["start_min"] // 60)]["awards"].get(
        n["deploy"]["product"])), None)
    dep = (f" ERCOT deploys {' and '.join(dict.fromkeys(names[n['deploy']['product']] for n in deps))} from "
           f"{hm(deps[0]['deploy']['start_min'])}" if deps else "")
    dep += (f"; at {hm(held['deploy']['start_min'])} the {names[held['deploy']['product']]} it holds is called and "
            "the reserved charge drains to the line." if held else "." if deps else "")
    h = max(range(24), key=lambda i: t["rt"][i])
    c = ep["cash"]
    cap, a = (capture(p, r.get("p_idle"), r.get("p_hind")) for p in (ep["profit_usd"], r.get("p_anchor")))
    score = (f" (C {cap:.2f}" + (f", the rolling anchor's {a:.2f}" if a is not None else "") + ")"
             if cap is not None else "")
    vs = f"the rolling anchor's ${r['p_anchor']:,.0f} and " if r.get("p_anchor") is not None else ""
    return (f"{region}, a {t['site']['pv_mwac']:g} MWac solar farm and a {t['site']['bess']['p_mw']:g} MW battery "
            f"behind one meter: {who} sells a day-ahead book of energy and reserves at 2 pm the day before, then "
            f"re-plans at {len(ep['watches']) - 1} watches.{dep} Real-time prices reach ${t['rt'][h]:,.0f}/MWh at "
            f"{hour(h)}. "
            f"It makes ${ep['profit_usd']:,.0f} (reserves ${c['as_da'] + c['as_rt']:,.0f}), against {vs}hindsight's "
            f"${r.get('p_hind', 0):,.0f}{score}.")


def hybrid_pilot(e: dict) -> str:
    """The v3 pilot's reading (results/pilot-v3c.json, rules 3.2): Sol's reserves-tier hindsight capture on its
    registered days against the rolling anchor's and the energy-only plan's, R second; a hero day is display-only."""
    path = ROOT / "results" / "pilot-v3c.json"
    if not path.is_file():
        return ""
    p = json.loads(path.read_text())["columns"]["reserves"]["primary"]["headline"]["reserves primary: all"]
    eo = p["refs"]["energy_only"]
    return ((" This day is display-only, outside the pilot." if e["task_id"] in HYBRID_HERO_TASKS else "")
            + f" In the pre-registered pilot (rules 3.2) on {p['n']} reserves-tier eval days Sol's capture is "
            f"{p['c']:.3f} ({p['c_ci'][0]:.3f} to {p['c_ci'][1]:.3f}) against the rolling anchor's "
            f"{p['c_anchor']:.3f}, "
            f"{versus({'mean': p['delta'], 'ci95': p['delta_ci']}, 'the anchor')}, and "
            f"{versus({'mean': eo['vs'], 'ci95': eo['vs_ci']}, 'the energy-only plan')}; R {p['r']:.3f} on the anchor "
            f"scale, {round(p['r_at_1'] * p['n'])} of {p['n']} days at R = 1.")


def live_entry(ep: dict, url: str) -> dict:
    t, b, r = ep["task"], ep["task"]["battery"], ep.get("references") or {}
    top = max(ep.get("notices") or [], key=lambda n: SEVERITY.get(n.get("level"), 0), default=None)
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label"), "version": "v2", "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "reward": ep.get("reward"),
            "r_opt": ep.get("capture_vs_hindsight"), "capture": ep.get("capture_vs_hindsight"),
            "profit": ep.get("profit_usd"), "p_opt": r.get("p_hind"),
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
    cap, a = (capture(p, r.get("p_idle"), r.get("p_hind")) for p in (ep["profit_usd"], r.get("p_roll")))
    tail = (f"It makes ${ep['profit_usd']:,.0f}, against the rolling anchor's ${r.get('p_roll', 0):,.0f} and "
            f"hindsight's ${r.get('p_hind', 0):,.0f}"
            + (f": C {cap:.2f} against the anchor's {a:.2f}." if cap is not None and a is not None else "."))
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
    r = ep.get("references") or {}
    hind = (r.get("p_idle"), r.get("p_opt"))
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "version": "v1", "model_label": ep.get("model_label"), "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "checkpoint_step": ep.get("checkpoint_step"),
            "reward": ep.get("reward"), "r_opt": ep.get("r_opt"), "profit": ep.get("profit_usd"),
            "capture": capture(ep.get("profit_usd"), *hind) if ep.get("profit_usd") is not None else None,
            "p_opt": (ep.get("references") or {}).get("p_opt"), "date": t["date"], "point": t["settlement_point"],
            "region": t["region"], "archetype": b.get("archetype"),
            "battery": f"{b['p_dis_mw']:g} MW / {b['energy_mwh']:g} MWh",
            "truncated": ep.get("truncated_at") is not None, "interest": round(interest(t["prices"]), 3),
            **({"p_anchor": blind["p_anchor"], "anchor_r_opt": blind["r_opt_anchor"],
                "anchor_capture": capture(blind["p_anchor"], *hind),
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
    blind = [e for e in entries if real(e) and e["tier"] == "blind" and e.get("anchor_capture") is not None
             and e["capture"] is not None]
    beats = max((e for e in blind if e["beats_anchor"]), key=lambda e: e["capture"] - e["anchor_capture"],
                default=None)
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
        return (f"Blind: with only the days before to go on, the agent's hindsight capture C is {e['capture']:.3f}, "
                f"where the better of the two forecasters reaches {e['anchor_capture']:.3f}. The day topped out at "
                f"{top}.")
    if kind == "trails":
        made = f"made ${e['profit']:,.0f}" if e["profit"] >= 0 else f"lost ${-e['profit']:,.0f}"
        return (f"Blind: the agent's plan {made} on a day the better forecaster's plan made ${e['p_anchor']:,.0f}; "
                f"its hindsight capture C is {e['capture']:.3f} against the forecaster's {e['anchor_capture']:.3f} (R "
                f"{e['reward']:.2f} against its 1.0). The day topped out at {top}.")
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
    record("--episode", str(path), "--weather", str(out / e["weather"]), "--thumb",
           str(thumb), "--t", str(t), "--extra",
           f"ui=0&shot={e.get('shot', 'establish')}" if hero or "t_moment" in e else "ui=0")
    e["thumb"] = f"thumbs/{thumb.name}"


def still(out: Path, e: dict) -> None:
    """The hero day at its evening ramp, 1600x900: the featured card's picture and the README's."""
    path = out / "runs" / e["url"]
    record("--episode", str(path), "--weather", str(out / e["weather"]), "--still",
           str(out / "thumbs" / "hero.jpg"), "--size", "1600x900", "--t", str(evening(json.loads(path.read_text()))),
           "--extra", "ui=0&shot=establish")
    e["thumb"] = "thumbs/hero.jpg"


_MARKET: dict | None = None


def market_tasks() -> dict:
    global _MARKET
    if _MARKET is None:
        _MARKET = {}
        for pack in MARKET_PACKS:
            if (data_root() / pack / "tasks.jsonl.gz").exists():
                for t in load_pack(pack):
                    _MARKET.setdefault(t["task_id"], t)
    return _MARKET


def verify_market(ep: dict, task: dict | None) -> str | None:
    """Every recorded call replayed through a fresh gridsim_core.market Session on the pack's day gives the recorded
    output; the floor's profit, reward and compliant score must match."""
    if task is None:
        return "not in any market pack"
    s = market.Session(task, ep["tier"], compliant=ep.get("compliant", False))
    for i, st in enumerate(ep["steps"]):
        if s.done:
            return f"step {i}: the floor ended before {st['tool']}"
        if json.loads(s.call(st["tool"], dict(st["args"]))) != st["output"]:
            return f"step {i} ({st['tool']}) does not replay"
    if not s.done:
        s.end_floor()
    g = s.grade()
    if abs(g["profit_usd"] - ep["profit_usd"]) > 0.01:
        return f"profit {ep['profit_usd']} != {g['profit_usd']}"
    if abs(g["reward"] - ep["reward"]) > 1e-6:
        return f"reward {ep['reward']} != {g['reward']}"
    if (g["compliant_reward"] is None) != (ep["compliant_reward"] is None) or (
            g["compliant_reward"] is not None and abs(g["compliant_reward"] - ep["compliant_reward"]) > 1e-6):
        return f"compliant {ep['compliant_reward']} != {g['compliant_reward']}"
    return None


def seats_view(task: dict) -> dict:
    """What the scene needs to size the other seats' assets: public sizes, never their private costs or offers."""
    st = task["seats"]
    out = {}
    if b := st.get("B"):
        out["B"] = {"p_mw": b["p_mw"], "e_mwh": b["e_mwh"], "eta": b["eta"], "s0_mwh": b["s0_mwh"]}
    if g := st.get("G"):
        out["G"] = {"units": len(g["units"]), "mw": round(sum(u["mw"] for u in g["units"]), 1)}
    if r := st.get("R"):
        out["R"] = {"mw": round(max(r["actual_mw"]), 1)}
    if ld := st.get("L"):
        out["L"] = {"mw": round(max(ld["load_mw"]), 1)}
    return out


def market_entry(ep: dict, url: str, task: dict) -> dict:
    t, a, r = ep["task"], ep["task"]["seat_A"], ep.get("references") or {}
    hind = ((task.get("refs") or {}).get(ep["tier"]) or {}).get("p_br_rt")
    c = capture(ep["profit_usd"], r.get("p_idle"), hind) if ep.get("profit_usd") is not None else None
    w = (ep.get("rows") or {}).get("welfare_ratio")
    return {"id": ep["episode_id"], "url": url, "task_id": ep["task_id"], "model": ep.get("model") or "unknown",
            "model_label": ep.get("model_label") or MARKET_NAMES.get(ep.get("model")), "version": "v5",
            "tier": ep["tier"], "bundle": ep.get("bundle"),
            "path": ep.get("path"), "trained": ep.get("trained"), "reward": ep.get("reward"),
            "compliant": ep.get("compliant_reward"), "capture": c, "score": None if c is None or w is None else round(
                0.5 * min(1.0, max(0.0, c)) + 0.5 * min(1.0, max(0.0, w)), 6),
            "profit": ep.get("profit_usd"), "p_anchor": r.get("p_anchor"),
            "p_br": r.get("p_br"), "date": t["date"], "point": t["point"], "region": t.get("region"),
            "battery": f"{a['p_mw']:,.0f} MW / {a['e_mwh']:,.0f} MWh", "watches": len(ep["watches"]),
            "mitigated": len([m for m in ep["clear"]["mitigated"] if m["seat"] == "A"]),
            "contracts": len([c for c in ep.get("contracts") or [] if c.get("status") == "accepted"]),
            "peak": max(ep["clear"]["hub_usd"]), "showcase": (task.get("tags") or {}).get("showcase")}


def feature_market(entries: list[dict], out: Path) -> dict | None:
    """The v5 preview's featured day: the best real floor-day run on a showcase floor by the public score (the
    compliant score on C; the hero day's first on a tie), else the best real floor-day run, else the hero day's anchor
    at the desk (or the disclosure anchor), else the v5 day with the highest peak."""
    pool = [e for e in entries if e["version"] == "v5"]
    runs = [x for x in pool if x["tier"] == "floor-day" and real(x)]

    def best(xs: list[dict]) -> dict | None:
        return max(xs, key=lambda x: (x["score"] or 0, x["capture"] or 0, x["showcase"] == MARKET_HERO, x["id"]),
                   default=None)

    e = (best([x for x in runs if x["showcase"]]) or best(runs)
         or next((x for m in ("reference/anchor-hedged", "reference/disclosure-anchor") for x in pool
                  if x["showcase"] == MARKET_HERO and x["model"] == m and x["tier"] == "floor-day"), None)
         or max(pool, key=lambda x: x["peak"], default=None))
    if e is None:
        return None
    ep = json.loads((out / "runs" / e["url"]).read_text())
    shown = " This floor is display-only, outside the pilot." if real(e) and e["showcase"] else ""
    e |= {"featured": "market", "blurb": market_blurb(ep) + shown + (market_pilot() if real(e) else ""),
          "hero_moment": "the trading room at 9:40, before the close", "t_moment": -4.0, "shot": "room"}
    return e


def market_pilot() -> str:
    """The v5 pilot's reading (results/eval-v5b.json and pilot-v5b.json, rules 5.1): Sol's compliant score on C against
    the anchor's, its C against the price-taker's, R second; its offers, its conduct."""
    path, c = ROOT / "results" / "pilot-v5b.json", card(5)
    if not path.is_file() or c is None:
        return ""
    cols = json.loads(path.read_text())["columns"]
    sprint = cols["floor-sprint"]["primary"]["floor-sprint primary: all"]
    day = cols["floor-day"]["primary"]["floor-day primary: all"]
    m = {x["tier"]: x for x in c["models"]}
    mitigated = day["floors_mitigated"] + sprint["floors_mitigated"]

    def tier(x: dict) -> str:
        return (f"at {x['tier']} {x['mean']:.2f} against the anchor's {x['anchor_headline']:.2f} (C "
                f"{x['capture']['mean']:.2f}, {versus(x['refs']['price_taker']['delta'], 'the price-taker')}; R "
                f"{x['reward']['mean']:.2f})")
    return (f" In the pre-registered pilot (rules 5.1; {sprint['n']} floor-sprint and {day['n']} floor-day eval "
            f"floors) Sol's compliant score, 0.5 clip(C) + 0.5 clip(welfare ratio) with C against hindsight BR_rt, is "
            + " and ".join(tier(m[k]) for k in ("floor-sprint", "floor-day") if k in m) + ". "
            f"It takes day-ahead positions beyond what its battery stores and settles the part it cannot deliver at "
            f"real time, a day-ahead/real-time spread trade ({day['clipped_hours']:.0f} hours a floor-day floor "
            f"clipped off its awards); it was "
            + (f"mitigated on {mitigated} of" if mitigated else "never mitigated on its")
            + f" {sprint['n'] + day['n']} floors, and "
            + (f"signed a CfD on {day['floors_with_contract']} floor-day floors." if day["floors_with_contract"]
               else "signed no CfD."))


def market_blurb(ep: dict) -> str:
    t, c, a = ep["task"], ep["clear"], ep["task"]["seat_A"]
    refs = (market_tasks().get(ep["task_id"]) or {}).get("refs") or {}
    tr = refs.get(ep["tier"]) or {}
    cap = capture(ep["profit_usd"], refs.get("p_idle"), tr.get("p_br_rt"))
    anchor = capture(tr.get("p_anchor"), refs.get("p_idle"), tr.get("p_br_rt"))
    w = (ep.get("rows") or {}).get("welfare_ratio")
    vs = (f" against the disclosure anchor's ${tr['p_anchor']:,.0f} and hindsight's ${tr['p_br_rt']:,.0f}"
          if cap is not None and anchor is not None else "")
    score = (f"C {cap:.2f} of hindsight" + (f" against the anchor's {anchor:.2f}" if anchor is not None else "")
             + (f", compliant score {0.5 * min(1.0, max(0.0, cap)) + 0.5 * min(1.0, max(0.0, w)):.2f}"
                if w is not None else "") + f" (R {ep['reward']:.2f})" if cap is not None
             else f"R {ep['reward']:.2f}")
    who = ep.get("model_label") or LABELS.get(ep.get("model"), (ep.get("model") or "the agent").split("/")[-1])
    h = max(range(24), key=lambda i: c["hub_usd"][i])
    sell = sum(max(0.0, x) for x in ep["awards"]["A"])
    cfd = [x for x in ep.get("contracts") or [] if x.get("status") == "accepted"]
    deal = (f" and signs a {cfd[0]['mw']:,.0f} MW CfD with the retailer" if cfd else "")
    mw = f"{a['p_mw']:,.0f}"
    article = "an" if mw.startswith("8") or mw.split(",")[0] in ("11", "18") else "a"
    return (f"ERCOT's day-ahead market on {t['date']}, re-cleared from the real 60-day disclosure: {who} offers "
            f"seat A, {article} {mw} MW battery portfolio, against four anonymised real portfolios at 9 am the day "
            f"before{deal}. The hub clears ${c['hub_usd'][h]:,.0f}/MWh at {hour(h)} (ERCOT's real "
            f"${t['hub_dam_real'][h]:,.0f}); seat A sells {sell:,.0f} MWh. It makes ${ep['profit_usd']:,.0f}{vs}: "
            f"{score}.")


def readme(entries: list[dict], hero: dict | None, training: dict | None = None) -> str:
    entries_all = entries
    v2 = [e for e in entries if e["version"] == "v2"]
    entries = [e for e in entries if e["version"] == "v1"]
    trained = [e for e in entries if e.get("path") == "B" and e.get("trained")]
    tids = {e["id"] for e in trained}
    counts = Counter(e.get("model_label") or e["model"] for e in entries if real(e) and e["id"] not in tids)
    refs = sum(not real(e) for e in entries)
    stages = Counter(e["trained"] for e in trained)
    models = ", ".join(f"{n:,} runs of {m}" for m, n in counts.most_common()) + (
        f", {len(trained):,} episodes from the training run of {trained[0]['model'].split('/')[-1]} ("
        + ", ".join(f"{stages[k]:,} {k if k == 'base' else k.upper()}" for k in ("base", "sft", "grpo") if stages[k])
        + ")" if trained else "") + (
        f" and {refs} reference episodes (the DP optimum and the baselines)" if refs else "")
    caption = (f"{hero['date']} at {hero['point']} ({hero['archetype']}, {hero['battery']}): {hero['blurb']} "
               f"{hero['model_label'] or hero['model']} captured "
               + (f"{hero['capture']:.1%} of hindsight (R {hero['reward']:.3f})." if hero.get("capture") is not None
                  else f"R {hero['reward']:.3f}.") if hero else "")
    fields = {"count": f"{len(entries):,}", "models": models, "hero_still": "hero.jpg",
              "hero_url": hero["url"] if hero else "", "hero_caption": caption, "repo": REPO, "dataset": DATASET,
              "app": APP,
              "hero_alt": f"The battery yard at {hero['point']} on {hero['date']}" if hero else "The battery yard"}
    text = README
    for k, v in fields.items():
        text = text.replace("{" + k + "}", v)
    v5 = [e for e in entries_all if e["version"] == "v5"]
    if v5:
        counts5 = Counter(e["model"] for e in v5)
        mv = next((e for e in v5 if e.get("featured") == "market"), None)
        text = text.replace("\n## Links\n", MARKET_README.format(
            n=len(v5), models=", ".join(f"{n} of {LABELS.get(m, m)}" for m, n in counts5.most_common()),
            hero=f"\n\n**The featured v5 day,** [{mv['date']}]({APP}/index.html?episode=runs/{mv['url']}): "
                 f"{mv['blurb']}" if mv else "") + "\n## Links\n")
    v4 = [e for e in entries_all if e["version"] == "v4"]
    if v4:
        counts4 = Counter(e.get("model_label") or e["model"] for e in v4)
        fv = next((e for e in v4 if e.get("featured") == "forecast"), None)
        text = text.replace("\n## Links\n", FORECAST_README.format(
            n=len(v4), models=", ".join(f"{n} of {LABELS.get(m, m)}" for m, n in counts4.most_common()),
            synth=" These are CI fixture windows: their forecast vintages are synthetic until the forecast store "
                  "lands; prices, PV, bulletins and the weather are real." if all(e["synthetic"] for e in v4) else "",
            hero=f"\n\n**The featured v4 window,** [{fv['date']} at {fv['point']}]"
                 f"({APP}/index.html?episode=runs/{fv['url']}): {fv['blurb']}" if fv else "") + "\n## Links\n")
    v3 = [e for e in entries_all if e["version"] == "v3"]
    if v3:
        counts3 = Counter(e.get("model_label") or e["model"] for e in v3)
        hv = next((e for e in v3 if e.get("featured") == "hybrid"), None)
        text = text.replace("\n## Links\n", HYBRID_README.format(
            n=len(v3), models=", ".join(f"{n} of {LABELS.get(m, m)}" for m, n in counts3.most_common()),
            hero=f"\n\n**The featured v3 day,** [{hv['date']} at {hv['point']}]"
                 f"({APP}/index.html?episode=runs/{hv['url']}): {hv['blurb']}" if hv else "") + "\n## Links\n")
    if v2:
        live_counts = Counter(e.get("model_label") or e["model"] for e in v2)
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
                         + (f" {lu['note'][:1].upper()}{lu['note'][1:]}." if lu.get("note") else "")
                         + (f" Over all {lu['overall']}"
                            + (f"; the final model is {lu['reading']}." if lu.get("reading")
                               else ": valid plans, not yet the simple rules.") if lu.get("overall") else ""))
        if rc := training.get("race"):
            lines.append(f"- [The race]({APP}/index.html?race=runs/race.json): {', '.join(rc['lanes'])} on the same "
                         f"day ({rc['task_id']})." + (f" {rc['verdict']}" if rc.get("verdict") else ""))
        text = text.replace("\n## Links\n", "\n".join(lines) + "\n\n## Links\n")
    return text


FORECAST_README = """
## v4 preview: Weather Front (provisional anchor)

{n} multi-day windows ({models}), schema `gridsim.episode/v4`. v3's solar farm and battery run for three operating days
(two at the battery-only front-lite tier). Each day's day-ahead book is bid at the 10 am DAM gate the day before, with
results at 2 pm; between gates the agent re-plans at watches as NOAA HRRR runs, ERCOT and NWS bulletins and prices
arrive, reading forecasts as they were issued: the desk's load, wind and solar models and its price guide (P10 to P90),
ERCOT's own forecasts where the window has them. The replay draws each forecast as issued, older runs fading, the
realized line only up to now, and a scrubber pins the card to what was on the desk, and what the agent read, at any
watch. The scene follows the observed weather over the three days: the cold front's shelf cloud, the wind shift, frost
and snow on the panels. Hindsight capture C heads the scores (idle 0, the plan that knows the realised window 1),
beside the rolling MILP anchor's own C; R, idle 0.2 and the anchor on the guide's P50 1.0, comes second, and the blind
re-planner is a reference. Every v4 episode was replayed call by call through `gridsim_core.forecast` when the Space
was built.{synth}{hero}
"""


LIVE_README = """
## v2 preview: The Live Grid (provisional anchor)

{n} live battery-days ({models}), schema `gridsim.episode/v2`. The agent commits a day-ahead position at 2 pm the day
before, then re-plans its 15-minute schedule at watches through the day, never inside the freeze line an hour ahead,
while real-time prices settle and ERCOT and NWS bulletins arrive (paraphrased summaries only). Settlement is
two-settlement: the position at day-ahead prices, every deviation at real-time prices. Hindsight capture C heads the
scores (idle 0, the clairvoyant plan 1), beside the rolling anchor's own C; R, idle 0.2 and the anchor 1.0, comes
second. Every v2 episode was replayed call by call through `gridsim_core.live` when the Space was built.{board}{hero}
"""


MARKET_README = """
## v5 preview: The Market Floor (provisional anchor)

{n} market days ({models}), schema `gridsim.episode/v5`. A model runs seat A, a battery portfolio carved from ERCOT's
real 60-day DAM disclosure, and offers MW at prices for each hour at 9 am the day before; at 10:00 the day-ahead market
closes and is re-cleared on one node from every other real offer and bid of that day, with four rival portfolios
(a battery, gas peakers, wind and solar, a retailer) carved out, anonymised and offering what they really offered. A
market monitor mitigates conduct that moves the price. Awards post at 1:30 pm; on the operating day the battery
delivers them and settles deviations at real-time prices. The replay starts in the desk's trading room (the market
clock, the merit order of the hour on the video wall) and cuts to the assets in the field. The public score is
compliant: half its hindsight capture C (against the best response settled at real-time prices), half its welfare
ratio, beside the disclosure anchor's; R, idle 0.2 and the anchor 1.0, comes second; regret, ε-Nash and the CfD row
are reported, not scored. Private costs, the copper plate and the rivals' scripts are modelled. Every v5 episode was
replayed call by call through `gridsim_core.market` when the Space was built.{hero}
"""


HYBRID_README = """
## v3 preview: Sun, Storage and Reserves (provisional anchor)

{n} solar-plus-storage days ({models}), schema `gridsim.episode/v3`. A solar farm and a battery share one meter: at 2 pm
the day before the agent sells a day-ahead book of battery MW and five ancillary services (RegUp, RegDn, RRS, ECRS,
Non-Spin), each backed by charge for its duration, then re-plans the battery at watches through the day while
real-time prices settle, regulation drifts the charge and ERCOT deploys what it bought. The scene adds the tracker rows
(following the real sun, stowed when the price goes negative), the inverter skids, the collector feeders and the meter;
the reserve bands sit on the battery's charge gauge, told apart by letter and hatch. Hindsight capture C heads the
scores (the solar-only plant 0, hindsight 1), beside the rolling MILP anchor's own C; R, the plant 0.2 and the anchor
1.0, comes second; AS share, curtailment and failures to provide are reported, not scored. PV is ERCOT's system-wide
availability (a proxy), clipped at the meter on oversized sites; regulation drift is ERCOT's storage-fleet deployment
from late 2023, modelled from RT against DA before. Every v3 episode was replayed call by call through
`gridsim_core.hybrid` when the Space was built.{hero}
"""


def live_board() -> str:
    """The v2 pilot's headline from results/eval-v2.json: hindsight capture beside the anchor's and the paired gap, R
    second."""
    c = card(2)
    if c is None:
        return ""
    b = c["baselines"].get("foresight") or {}
    rows = [f"{LABELS.get(m['model'], m['model'])} captures {m['capture']['mean']:.1%} of hindsight over "
            f"{m['tasks']} days, {versus(m['delta'], 'the rolling anchor')} (R {m['mean']:.3f})" for m in c["models"]]
    return (f"\n\nThe pilot, pre-registered: {'; '.join(rows)}; naive captures "
            f"{b.get('naive_capture', 0):.1%} (R {b.get('naive', 0):.3f}) and the rolling anchor "
            f"{b.get('anchor_capture', 0):.1%} (R 1.000) on the same days.")


if __name__ == "__main__":
    sys.exit(main())
