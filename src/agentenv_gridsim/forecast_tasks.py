"""Forecast packs as folder bundles: one task per window at one tier, played live in watches on gridsim-forecast by
gridsim-llm on gridsim_core's forecast prompt (path B''s messages), its notices and deployment payloads delivered by one
gateway trigger per watch, and graded by gridsim-forecast-verifier. The flow is gridsim-live's (live_tasks.flow); the
blind tier also hides the forecast tools from the agent."""

import json
from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.forecast import (
    END_WINDOW_URI,
    FORECAST_ENV,
    FORECAST_LOAD_URI,
    FORECAST_TOOLS,
    MAX_TURNS,
    TIERS,
    Session,
    triggers,
)
from gridsim_core.forecast_prompt import opening, system_prompt
from gridsim_core.task import data_root

from .forecast import FORECAST_PACK_NAMES
from .live_tasks import AGENT, flow, select, write_bundle
from .server import read_pack

VERIFIER = "gridsim-forecast-verifier"
MODEL_PARAMS = {"max_tokens": 16384}
PLAY_SECONDS = 14400
EPISODE_CAP_USD = 5.0
BUNDLE = files("agentenv_gridsim.bundles") / "gridsim-forecast"
VERIFY = BUNDLE / "artifacts/gridsim-forecast-verifier/verify.py"
BUNDLE_PACK, BUNDLE_WINDOW = "fixtures-forecast", "front-v4-2022-12-22-HB_NORTH-pv150-b100x2h-poi150"
SHOWCASE_PACK = "ercot-front-v4-showcase"
LOOKAHEAD = ("Wiring check, not a trading task: first call get_forecast with kind \"price\" and issued_at \"{at}\", "
             "which is after now and must be refused; then call advance, and nothing else, until the window is over.")
LICENCE = ("Prices: ERCOT Day-Ahead and Real-Time Market settlement point prices (NP4-180-ER, NP6-785-ER) and DAM "
           "Clearing Prices for Capacity (NP4-188-CD), public ERCOT data; ERCOT does not endorse this work. Weather: "
           "NOAA HRRR as issued; NWS products from the IEM VTEC archive; ERCOT's day-ahead load forecast via EIA-930 "
           "(public domain). Desk load, wind and solar forecasts and the price guide are modelled from them. Solar "
           "from ERCOT NP4-745-CD (an availability proxy); sites are flagged archetypes; regulation drift is a seeded "
           "draw.")


def pack_rows(pack: str) -> list[dict]:
    return read_pack(data_root() / pack)


def eligible(rows: list[dict], tier: str, zone: str | None = None) -> list[dict]:
    """The pack's windows a tier can play: the tier's references are in the row."""
    return [r for r in rows if (r.get("refs") or {}).get(tier) and zone in (None, r["settlement_point"])]


def steps(task: dict, tier: str = "front", episode_cap_usd: float | None = None, play: bool = True,
          lookahead: bool = False) -> list[dict]:
    """Deploy, load the window, hide grid_notice (and, blind, the forecast tools), one trigger per watch after the
    first that delivers its notices and deployment payloads when the agent's advance opens it, deploy gridsim-llm, arm
    the clock frozen at watch 0, play on the forecast desk card, end the window and grade it. Without ``play``, no
    agent; with ``lookahead``, the opening asks for a forecast issued after now and then only advances (a turn a watch
    and one more at each DAM gate, where the harness holds the first advance back)."""
    s = Session(task, tier)
    user = opening(s)
    turns = MAX_TURNS[tier]
    if lookahead:
        user += "\n\n" + LOOKAHEAD.format(at=s.watches[1].time)
        turns = len(s.watches) + s.n + 2
    return flow(FORECAST_ENV, VERIFIER, task["task_id"], tier, s.watch_time_utc(0), triggers(s.watches),
                system_prompt(tier, s.win.era, s.source), user, episode_cap_usd, play, MODEL_PARAMS,
                load_uri=FORECAST_LOAD_URI, end=("end-window", END_WINDOW_URI), max_turns=turns,
                play_seconds=PLAY_SECONDS, tier_hidden=list(FORECAST_TOOLS) if tier == "blind" else None)


def generate(pack: str, out: Path, *, tier: str = "front", task_ids: list[str] | None = None,
             zone: str | None = None, episode_cap_usd: float | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the verifier and tasks/<task_id>.json for ``task_ids`` or every
    window of the pack the tier can play, in the pack's order."""
    if pack not in FORECAST_PACK_NAMES:
        raise click.UsageError(f"{pack} is not a forecast pack: {', '.join(FORECAST_PACK_NAMES)}")
    rows = select(eligible(pack_rows(pack), tier, zone), task_ids, f"{tier} windows of {pack}")
    readme = (f"GridSim forecast {pack}, {tier} tier: {len(rows)} solar-plus-storage windows, each played live in "
              f"watches by the {AGENT} agent on {FORECAST_ENV} and graded by {VERIFIER}.\n\n{LICENCE}\n")
    return write_bundle(out, readme, VERIFIER, VERIFY.read_bytes(),
                        {r["task_id"]: steps(r, tier, episode_cap_usd) for r in rows})


def bundle_tasks() -> dict[str, list[dict]]:
    """The gridsim-forecast bundle's tasks: the fixture window at each tier, each showcase window of the showcase pack
    (once it is built) at front, and the two wiring tasks on the fixture window at front."""
    window = next(r for r in pack_rows(BUNDLE_PACK) if r["task_id"] == BUNDLE_WINDOW)
    out = {tier: steps(window, tier) for tier in TIERS}
    for r in pack_rows(SHOWCASE_PACK):
        if (r.get("tags") or {}).get("showcase") and eligible([r], "front"):
            out[r["tags"]["showcase"]] = steps(r, "front")
    return out | {"wiring-nodam": steps(window, "front", play=False),
                  "wiring-lookahead": steps(window, "front", lookahead=True)}


def write_bundle_tasks(root: Path) -> list[str]:
    """Writes bundle_tasks() into the bundle folder ``root`` (src/agentenv_gridsim/bundles/gridsim-forecast)."""
    tasks = bundle_tasks()
    for name, task_steps in tasks.items():
        (root / "tasks" / f"{name}.json").write_text(json.dumps(task_steps, indent=2, ensure_ascii=False) + "\n")
    return list(tasks)
