"""Market packs as folder bundles: one task per floor at one tier, played on gridsim-market by gridsim-llm on
gridsim_core's market prompt (path B's rules card), its ISO notices delivered by one gateway trigger per watch, and
graded by gridsim-market-verifier, on seat A's reward or, compliant, on 0.5 R + 0.5 welfare ratio. The flow is
gridsim-live's (live_tasks.flow)."""

from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.market import END_URI, LOAD_URI, MARKET_ENV, MAX_TURNS, SPRINT_TOOLS, TOOLS, Session, triggers
from gridsim_core.market_prompt import opening, system_prompt
from gridsim_core.task import data_root

from .live_tasks import AGENT, flow, select, write_bundle
from .market import CALLS_URI, MARKET_PACK_NAMES
from .server import read_pack

VERIFIER = "gridsim-market-verifier"
MODEL_PARAMS = {"floor-sprint": {"max_tokens": 16384}, "floor-day": {"max_tokens": 16384}}
PLAY_SECONDS = {"floor-sprint": 3600, "floor-day": 7200}
EPISODE_CAP_USD = {"floor-sprint": 1.0, "floor-day": 2.0}
"""A sweep's default episode cap for GPT-6.1 Sol at effort high: about six worst-case turns of 16,384 output tokens a
sprint, twelve a day; the agent's guard stops before a request whose estimate could pass it."""
DAY_ONLY = [t for t in TOOLS if t not in SPRINT_TOOLS]
VERIFY = files("agentenv_gridsim.bundles") / "gridsim-market/artifacts/gridsim-market-verifier/verify.py"
LICENCE = ("Market: ERCOT 60-Day DAM Disclosure Reports (NP3-966-ER), DAM System Lambda (NP4-523-CD) and hub "
           "settlement point prices (NP4-180-ER, NP6-905-CD), public ERCOT data re-cleared as derived, anonymised "
           "aggregates; ERCOT does not endorse this work. Load, wind and solar from EIA-930; CT heat rates from "
           "EIA-923 (public domain). Copper plate, AS truncation, commitment, mitigation and private costs are "
           "modelled.")


def pack_rows(pack: str) -> list[dict]:
    return read_pack(data_root() / pack)


def eligible(rows: list[dict], tier: str) -> list[dict]:
    """The pack's floors a tier can play: the tier's references are in the row, and for floor-day the pack didn't tag
    the floor out of its floor-day subset (the eval pack's floor_day tag)."""
    return [r for r in rows if (r.get("refs") or {}).get(tier)
            and (tier != "floor-day" or (r.get("tags") or {}).get("floor_day") is not False)]


def load_step(task_id: str, tier: str, compliant: bool) -> dict:
    return {"id": "load-task", "type": "apply_server_config", "env_id": MARKET_ENV,
            "directives": [{"service": MARKET_ENV, "uri": LOAD_URI,
                            "args": {"floor_id": task_id, "tier": tier} | ({"compliant": True} if compliant else {})}]}


def calls_step(calls: list[tuple[str, dict]]) -> dict:
    return {"id": "seat-calls", "type": "apply_server_config", "env_id": MARKET_ENV,
            "directives": [{"service": MARKET_ENV, "uri": CALLS_URI,
                            "args": {"calls": [{"tool": t, "args": a} for t, a in calls]}}]}


def steps(task: dict, tier: str = "floor-sprint", compliant: bool = False, episode_cap_usd: float | None = None,
          play: bool = True, calls: list[tuple[str, dict]] | None = None) -> list[dict]:
    """Deploy, load the floor, hide grid_notice (and in floor-sprint the floor-day tools), one trigger per watch after
    the first that delivers its notices when the agent's advance opens it, deploy gridsim-llm, arm the clock frozen at
    watch 0, play on the market rules card, end the floor and grade it. Without ``play``, no agent; ``calls`` are
    played as seat A by the harness before the floor ends."""
    s = Session(task, tier)
    out = flow(MARKET_ENV, VERIFIER, task["task_id"], tier, s.watch_time_utc(0), triggers(s.watches),
               system_prompt(tier), opening(s), episode_cap_usd, play, MODEL_PARAMS[tier], load_uri=LOAD_URI,
               end=("end-floor", END_URI), max_turns=MAX_TURNS[tier], play_seconds=PLAY_SECONDS[tier],
               tier_hidden=DAY_ONLY if tier == "floor-sprint" else None)
    out = [load_step(task["task_id"], tier, compliant) if x["id"] == "load-task" else x for x in out
           if x["id"] != "watches" or x["triggers"]]
    if calls:
        out.insert(next(i for i, x in enumerate(out) if x["id"] == "end-floor"), calls_step(calls))
    return out


def generate(pack: str, out: Path, *, tier: str = "floor-sprint", compliant: bool = False,
             task_ids: list[str] | None = None, episode_cap_usd: float | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the verifier and tasks/<task_id>.json for ``task_ids`` or every
    floor of the pack the tier can play, in the pack's order."""
    if pack not in MARKET_PACK_NAMES:
        raise click.UsageError(f"{pack} is not a market pack: {', '.join(MARKET_PACK_NAMES)}")
    rows = select(eligible(pack_rows(pack), tier), task_ids, f"{tier} floors of {pack}")
    scoring = "the compliant score (0.5 R + 0.5 welfare ratio)" if compliant else "seat A's reward"
    readme = (f"GridSim market {pack}, {tier} tier: {len(rows)} floors, each played on {MARKET_ENV} by the {AGENT} "
              f"agent as seat A and graded by {VERIFIER} on {scoring}.\n\n{LICENCE}\n")
    return write_bundle(out, readme, VERIFIER, VERIFY.read_bytes(),
                        {r["task_id"]: steps(r, tier, compliant, episode_cap_usd) for r in rows})
