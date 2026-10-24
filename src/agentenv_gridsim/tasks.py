"""`agent-env gridsim tasks`: a task pack as a folder bundle, one task per battery-day, each played by gridsim-llm on
gridsim_core's prompt, at one tier (foresight or blind) and in one harness (full: three checks; oneshot:
submit_schedule only), and graded by gridsim-verifier; a live pack's days played live on gridsim-live (live_tasks), a
hybrid pack's site-days on gridsim-hybrid (hybrid_tasks), a market pack's floors on gridsim-market (market_tasks)."""

import json
from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.hybrid import TIERS as HYBRID_TIERS
from gridsim_core.live import TIERS as LIVE_TIERS
from gridsim_core.market import TIERS as MARKET_TIERS
from gridsim_core.prompt import messages
from gridsim_core.task import data_root

from . import hybrid_tasks, live_tasks, market_tasks
from .hybrid import HYBRID_PACK_NAMES
from .live import LIVE_PACK_NAMES
from .market import MARKET_PACK_NAMES
from .server import LOAD_URI, MAX_CHECKS, PACK_NAMES, TIERS, TaskIndex, pack_dirs, read_pack

ENV = "gridsim"
AGENT = "gridsim-llm"
VERIFIER = "gridsim-verifier"
VERIFY = files("agentenv_gridsim.bundles") / "gridsim/artifacts/gridsim-verifier/verify.py"
BUNDLES = {"full": MAX_CHECKS, "oneshot": 0}
HIDDEN_IN_ONESHOT = ["get_situation", "check_schedule"]
MAX_TURNS = 4
MODEL_PARAMS = {"max_tokens": 4096}
EFFORT = "high"
PLAY_SECONDS = 1800
LICENCE = ("Prices: ERCOT Day-Ahead Market settlement point prices (NP4-180-ER), public ERCOT data; ERCOT does not "
           "endorse this work. Battery archetypes from EIA-860 (public domain).")


def pack_rows(pack: str) -> list[dict]:
    return read_pack(data_root() / pack)


def find_task(task_id: str) -> dict:
    task = TaskIndex(pack_dirs()).get(task_id)
    if task is None:
        raise click.UsageError(f"no task {task_id!r} in the packs")
    return task


def agent_env(episode_cap_usd: float | None) -> dict[str, dict[str, str]]:
    """The agent's environment: a cost cap only when one is asked for (a sweep's), so a published task carries none."""
    return {"env_vars": {"GRIDSIM_MAX_COST_USD": format(episode_cap_usd, "g")}} if episode_cap_usd is not None else {}


def load_step(task_id: str, tier: str, checks: int) -> dict:
    return {"id": "load-task", "type": "apply_server_config", "env_id": ENV,
            "directives": [{"service": ENV, "uri": LOAD_URI,
                            "args": {"task_id": task_id, "tier": tier, "checks": checks}}]}


def grade_step() -> dict:
    return {"id": "grade", "type": "env_outcome_verifier", "env_id": ENV, "file_artifact_id": VERIFIER,
            "verifier_id": "gridsim", "score_aggregator": "weighted_average"}


def steps(task: dict, tier: str = "foresight", bundle: str = "full", episode_cap_usd: float | None = None
          ) -> list[dict]:
    """deploy_env gridsim, load the task, (oneshot) hide every tool but submit_schedule, deploy gridsim-llm, play it on
    gridsim_core's system prompt with the situation as the opening message, as path B does, and grade it."""
    checks = BUNDLES[bundle]
    system, user = (m["content"] for m in messages(task, tier, checks))
    out = [{"id": "deploy", "type": "deploy_env", "env_id": ENV}, load_step(task["task_id"], tier, checks)]
    if bundle == "oneshot":
        out.append({"id": "submit-only", "type": "modify_env_tool_access", "env_id": ENV, "action": "disable",
                    "role": "default", "tools": HIDDEN_IN_ONESHOT})
    return out + [
        {"id": "deploy-agent", "type": "deploy_agent", "a2a_agent_id": AGENT, "env_ids": [ENV],
         **agent_env(episode_cap_usd)},
        {"id": "play", "type": "prompt_agent", "prompt_id": task["task_id"],
         "system_prompt": system, "prompt": user,
         "max_turns": MAX_TURNS, "model_params": MODEL_PARAMS, "effort": EFFORT, "timeout_seconds": PLAY_SECONDS},
        grade_step(),
    ]


def eligible(rows: list[dict], tier: str, zone: str | None = None) -> list[dict]:
    """The pack's tasks a tier can play (blind needs the task's blind inputs), at one settlement point if asked."""
    return [r for r in rows if (tier == "foresight" or (r.get("blind") and (r.get("refs") or {}).get("blind")))
            and zone in (None, r["settlement_point"])]


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def generate(pack: str, out: Path, *, tier: str = "foresight", bundle: str = "full", task_ids: list[str] | None = None,
             zone: str | None = None, episode_cap_usd: float | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the verifier and tasks/<task_id>.json for ``task_ids`` or every
    task of the pack the tier can play, in the pack's order."""
    rows = eligible(pack_rows(pack), tier, zone)
    if task_ids is not None:
        known = {r["task_id"] for r in rows}
        if unknown := [t for t in task_ids if t not in known]:
            raise click.UsageError(f"not {tier} tasks of {pack}: {', '.join(unknown)}")
        rows = [r for r in rows if r["task_id"] in task_ids]
    harness = "three checks" if bundle == "full" else "submit_schedule only"
    _write(out / "README.md", f"GridSim {pack}, {tier} tier, {bundle} harness ({harness}): {len(rows)} battery-days, "
                              f"each played by the {AGENT} agent and graded by {VERIFIER}.\n\n{LICENCE}\n".encode())
    _write(out / f"artifacts/{VERIFIER}/verify.py", VERIFY.read_bytes())
    for row in rows:
        _write(out / "tasks" / f"{row['task_id']}.json",
               (json.dumps(steps(row, tier, bundle, episode_cap_usd), indent=2, ensure_ascii=False) + "\n").encode())
    return [r["task_id"] for r in rows]


@click.group("tasks")
def tasks_group():
    """GridSim tasks for a model: a task pack as a bundle `agent-env run` plays."""


@tasks_group.command("generate")
@click.option("--pack", type=click.Choice(PACK_NAMES + LIVE_PACK_NAMES + HYBRID_PACK_NAMES + MARKET_PACK_NAMES),
              required=True,
              help="The task pack; a gridsim-live pack (or fixtures-live) writes live days on gridsim-live, a hybrid "
                   "pack (or fixtures-hybrid) site-days on gridsim-hybrid, a market pack (or fixtures-market) floors "
                   "on gridsim-market.")
@click.option("--tier", type=click.Choice(LIVE_TIERS + HYBRID_TIERS + MARKET_TIERS),
              help="foresight (the default): the day's prices; blind: the day before's and the week before's. Live "
                   "packs also take short (the regular watches D-1 14:00, D 00:00 and 12:00 plus notice watches) and "
                   "freeze6h. Hybrid packs take energy, reserves (the default) or rtcb. Market packs take "
                   "floor-sprint (the default) or floor-day.")
@click.option("--compliant", is_flag=True, help="Market packs: score 0.5 R + 0.5 welfare ratio instead of R.")
@click.option("--bundle", "bundle", type=click.Choice(list(BUNDLES)), default="full", show_default=True,
              help="full: get_situation, three checks and submit_schedule; oneshot: submit_schedule only. Not for "
                   "live or hybrid packs.")
@click.option("--zone", metavar="POINT", help="Only this settlement point's days, e.g. HB_WEST.")
@click.option("--out", type=click.Path(file_okay=False, path_type=Path),
              help="The bundle folder to write. Default: results/bundles/<pack>-<tier>-<bundle>.")
def generate_command(pack: str, tier: str | None, compliant: bool, bundle: str, zone: str | None, out: Path | None):
    """Write a bundle with one task per battery-day of the pack the tier can play: deploy the env, load the day,
    play it with gridsim-llm on gridsim_core's prompt and grade it with gridsim-verifier. A live pack's days are
    played live on gridsim-live in watches, its notices delivered by triggers, and graded by gridsim-live-verifier; a
    hybrid pack's site-days likewise on gridsim-hybrid, graded by gridsim-hybrid-verifier; a market pack's floors on
    gridsim-market, graded by gridsim-market-verifier."""
    market = pack in MARKET_PACK_NAMES
    if market != (tier in MARKET_TIERS) and tier is not None or compliant and not market:
        raise click.UsageError(f"market packs take the tiers {', '.join(MARKET_TIERS)} and --compliant; {pack} does "
                               f"not take {tier if market != (tier in MARKET_TIERS) else '--compliant'}")
    if market:
        if bundle != "full" or zone:
            raise click.UsageError("--bundle and --zone are not for market packs")
        tier = tier or "floor-sprint"
        out = out or Path("results/bundles") / f"{pack}-{tier}{'-compliant' if compliant else ''}"
        names = market_tasks.generate(pack, out, tier=tier, compliant=compliant)
        if not names:
            raise click.UsageError(f"{pack} has no {tier} floors")
        click.echo(f"Wrote {len(names)} tasks into {out}; play one with: agent-env run {out} --task {names[0]} "
                   "--model <litellm model id>")
        return
    hybrid = pack in HYBRID_PACK_NAMES
    tier = tier or ("reserves" if hybrid else "foresight")
    if hybrid != (tier in HYBRID_TIERS):
        raise click.UsageError(f"hybrid packs have the tiers {', '.join(HYBRID_TIERS)}; {pack} doesn't take {tier}"
                               if hybrid else f"{tier} is a hybrid tier; {pack} is not a hybrid pack")
    if (pack in LIVE_PACK_NAMES or hybrid) and bundle != "full":
        raise click.UsageError("--bundle is for the v1 packs; a live day has one harness")
    if hybrid:
        out = out or Path("results/bundles") / f"{pack}-{tier}"
        names = hybrid_tasks.generate(pack, out, tier=tier, zone=zone)
    elif pack in LIVE_PACK_NAMES:
        out = out or Path("results/bundles") / f"{pack}-{tier}"
        names = live_tasks.generate(pack, out, tier=tier, zone=zone)
    elif tier not in TIERS:
        raise click.UsageError(f"the v1 packs have the tiers {', '.join(TIERS)}, not {tier}")
    else:
        out = out or Path("results/bundles") / f"{pack}-{tier}-{bundle}"
        names = generate(pack, out, tier=tier, bundle=bundle, zone=zone)
    if not names:
        raise click.UsageError(f"{pack} has no {tier} tasks" + (f" at {zone}" if zone else ""))
    click.echo(f"Wrote {len(names)} tasks into {out}; play one with: agent-env run {out} --task {names[0]} "
               "--model <litellm model id>")
