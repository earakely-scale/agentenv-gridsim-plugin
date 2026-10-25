"""Hybrid packs as folder bundles: one task per site-day at one tier, played live in watches on gridsim-hybrid by
gridsim-llm on gridsim_core's hybrid prompt (path B''s messages), its notices and deployment payloads delivered by
one gateway trigger per watch, and graded by gridsim-hybrid-verifier. The flow is gridsim-live's (live_tasks.flow)."""

from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.hybrid import HYBRID_ENV, Session, triggers
from gridsim_core.hybrid_prompt import opening, system_prompt
from gridsim_core.task import data_root

from .hybrid import HYBRID_PACK_NAMES
from .live_tasks import AGENT, flow, select, write_bundle
from .server import read_pack

VERIFIER = "gridsim-hybrid-verifier"
MODEL_PARAMS = {"max_tokens": 16384}
VERIFY = files("agentenv_gridsim.bundles") / "gridsim-hybrid/artifacts/gridsim-hybrid-verifier/verify.py"
LICENCE = ("Prices: ERCOT Day-Ahead and Real-Time Market settlement point prices (NP4-190-CD, NP6-905-CD) and DAM "
           "Clearing Prices for Capacity (NP4-188-CD), public ERCOT data; ERCOT does not endorse this work. Solar from "
           "ERCOT NP4-745-CD (an availability proxy); sites from EIA-860 (public domain) or flagged archetypes.")


def pack_rows(pack: str) -> list[dict]:
    return read_pack(data_root() / pack)


def eligible(rows: list[dict], tier: str, zone: str | None = None) -> list[dict]:
    """The pack's site-days a tier can play: the tier's references are in the row (rtcb's only on era C days with RT
    MCPC)."""
    return [r for r in rows if (r.get("refs") or {}).get(tier) and zone in (None, r["settlement_point"])]


def steps(task: dict, tier: str = "reserves", episode_cap_usd: float | None = None, play: bool = True) -> list[dict]:
    """The v3 plan's episode flow: deploy, load the day, hide grid_notice, one trigger per watch after the first that
    delivers its notices and deployment payloads when the agent's advance opens it, deploy gridsim-llm, arm the clock
    frozen at watch 0, play on the hybrid rules card, end the day and grade it. Without ``play``, no agent."""
    s = Session(task, tier)
    return flow(HYBRID_ENV, VERIFIER, task["task_id"], tier, s.watch_time_utc(0), triggers(s.watches),
                system_prompt(tier, s.day.era), opening(s), episode_cap_usd, play, MODEL_PARAMS)


def generate(pack: str, out: Path, *, tier: str = "reserves", task_ids: list[str] | None = None,
             zone: str | None = None, episode_cap_usd: float | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the verifier and tasks/<task_id>.json for ``task_ids`` or every
    site-day of the pack the tier can play, in the pack's order."""
    if pack not in HYBRID_PACK_NAMES:
        raise click.UsageError(f"{pack} is not a hybrid pack: {', '.join(HYBRID_PACK_NAMES)}")
    rows = select(eligible(pack_rows(pack), tier, zone), task_ids, f"{tier} days of {pack}")
    readme = (f"GridSim hybrid {pack}, {tier} tier: {len(rows)} solar-plus-storage site-days, each played live in "
              f"watches by the {AGENT} agent on {HYBRID_ENV} and graded by {VERIFIER}.\n\n{LICENCE}\n")
    return write_bundle(out, readme, VERIFIER, VERIFY.read_bytes(),
                        {r["task_id"]: steps(r, tier, episode_cap_usd) for r in rows})
