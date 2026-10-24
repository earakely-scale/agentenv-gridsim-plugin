"""Live packs as folder bundles: one task per battery-day at one tier, played live in watches on gridsim-live by
gridsim-llm on gridsim_core's live prompt (path B''s messages), its notices delivered by one gateway trigger per watch,
and graded by gridsim-live-verifier."""

import json
from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.live import END_DAY_URI, LIVE_ENV, LIVE_LOAD_URI, MAX_TURNS, NOTICE_TOOL, Session, triggers
from gridsim_core.live_prompt import messages
from gridsim_core.task import data_root

from .live import LIVE_PACK_NAMES
from .server import read_pack

AGENT = "gridsim-llm"
VERIFIER = "gridsim-live-verifier"
VERIFY = files("agentenv_gridsim.bundles") / "gridsim-live/artifacts/gridsim-live-verifier/verify.py"
MODEL_PARAMS = {"max_tokens": 8192}
EFFORT = "high"
PLAY_SECONDS = 7200
LICENCE = ("Prices: ERCOT Day-Ahead Market and Real-Time Market settlement point prices (NP4-180-ER, NP6-785-ER), "
           "public ERCOT data; ERCOT does not endorse this work. Battery archetypes from EIA-860 (public domain).")


def pack_rows(pack: str) -> list[dict]:
    return read_pack(data_root() / pack)


def eligible(rows: list[dict], tier: str, zone: str | None = None) -> list[dict]:
    """The pack's days a tier can play: the tier's anchor is in the refs (blind also needs the blind inputs)."""
    return [r for r in rows if ((r.get("refs") or {}).get("roll") or {}).get(tier) and (tier != "blind" or r["blind"])
            and zone in (None, r["settlement_point"])]


def agent_env(episode_cap_usd: float | None) -> dict[str, dict[str, str]]:
    return {"env_vars": {"GRIDSIM_MAX_COST_USD": format(episode_cap_usd, "g")}} if episode_cap_usd is not None else {}


def load_step(task_id: str, tier: str, env: str = LIVE_ENV, uri: str = LIVE_LOAD_URI,
              extra: dict | None = None) -> dict:
    return {"id": "load-task", "type": "apply_server_config", "env_id": env,
            "directives": [{"service": env, "uri": uri, "args": {"task_id": task_id, "tier": tier} | (extra or {})}]}


def steps(task: dict, tier: str = "foresight", episode_cap_usd: float | None = None, play: bool = True) -> list[dict]:
    """FD-4321's episode flow: deploy, load the day, hide grid_notice, one trigger per watch after the first that
    delivers its notices when the agent's advance opens it, deploy gridsim-llm, arm the clock frozen at watch 0, play,
    end the day and grade it. Without ``play``, no agent: end-day delivers every watch's notices itself."""
    s = Session(task, tier)
    system, user = (m["content"] for m in messages(s))
    return flow(LIVE_ENV, VERIFIER, task["task_id"], tier, s.watch_time_utc(0), triggers(s.watches), system, user,
                episode_cap_usd, play)


def flow(env: str, verifier: str, task_id: str, tier: str, watch_0_utc: str, watch_triggers: list[dict], system: str,
         user: str, episode_cap_usd: float | None = None, play: bool = True, model_params: dict = MODEL_PARAMS, *,
         load_uri: str = LIVE_LOAD_URI, end: tuple[str, str] = ("end-day", END_DAY_URI), max_turns: int = MAX_TURNS,
         play_seconds: int = PLAY_SECONDS, tier_hidden: list[str] | None = None,
         load_args: dict | None = None) -> list[dict]:
    """The steps of a day (or window) in watches on a gateway env, shared by gridsim-live, gridsim-hybrid and
    gridsim-forecast: ``end`` is the end step's id and extension, ``tier_hidden`` the agent tools the tier hides,
    ``load_args`` what the load takes beyond the task id and tier."""
    out = [{"id": "deploy", "type": "deploy_env", "env_id": env}, load_step(task_id, tier, env, load_uri, load_args),
           {"id": "hide-grid-notice", "type": "modify_env_tool_access", "env_id": env, "action": "disable",
            "role": "default", "tools": [NOTICE_TOOL]}]
    if tier_hidden:
        out.append({"id": "hide-tier-tools", "type": "modify_env_tool_access", "env_id": env, "action": "disable",
                    "role": "default", "tools": tier_hidden})
    out.append({"id": "watches", "type": "register_env_triggers", "env_id": env, "watch_roles": ["default"],
                "triggers": watch_triggers})
    if play:
        out.append({"id": "deploy-agent", "type": "deploy_agent", "a2a_agent_id": AGENT, "env_ids": [env],
                    **agent_env(episode_cap_usd)})
    out.append({"id": "clock", "type": "sync_env_clock", "env_id": env, "virtual_time": watch_0_utc,
                "virtual_seconds_per_real_second": 0, "tolerate_missing_sync_time": False})
    if play:
        out.append({"id": "play", "type": "prompt_agent", "prompt_id": task_id, "system_prompt": system,
                    "prompt": user, "max_turns": max_turns, "model_params": model_params, "effort": EFFORT,
                    "timeout_seconds": play_seconds})
    return out + [
        {"id": end[0], "type": "apply_server_config", "env_id": env,
         "directives": [{"service": env, "uri": end[1], "args": {}}]},
        {"id": "grade", "type": "env_outcome_verifier", "env_id": env, "file_artifact_id": verifier,
         "verifier_id": "gridsim", "score_aggregator": "weighted_average"},
    ]


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def generate(pack: str, out: Path, *, tier: str = "foresight", task_ids: list[str] | None = None,
             zone: str | None = None, episode_cap_usd: float | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the verifier and tasks/<task_id>.json for ``task_ids`` or every day
    of the pack the tier can play, in the pack's order."""
    if pack not in LIVE_PACK_NAMES:
        raise click.UsageError(f"{pack} is not a live pack: {', '.join(LIVE_PACK_NAMES)}")
    rows = select(eligible(pack_rows(pack), tier, zone), task_ids, f"{tier} days of {pack}")
    readme = (f"GridSim live {pack}, {tier} tier: {len(rows)} battery-days, each played live in watches by the {AGENT} "
              f"agent on {LIVE_ENV} and graded by {VERIFIER}.\n\n{LICENCE}\n")
    return write_bundle(out, readme, VERIFIER, VERIFY.read_bytes(),
                        {r["task_id"]: steps(r, tier, episode_cap_usd) for r in rows})


def select(rows: list[dict], task_ids: list[str] | None, what: str) -> list[dict]:
    if task_ids is None:
        return rows
    known = {r["task_id"] for r in rows}
    if unknown := [t for t in task_ids if t not in known]:
        raise click.UsageError(f"not {what}: {', '.join(unknown)}")
    return [r for r in rows if r["task_id"] in task_ids]


def write_bundle(out: Path, readme: str, verifier: str, verify: bytes, tasks: dict[str, list[dict]]) -> list[str]:
    _write(out / "README.md", readme.encode())
    _write(out / f"artifacts/{verifier}/verify.py", verify)
    for task_id, task_steps in tasks.items():
        _write(out / "tasks" / f"{task_id}.json",
               (json.dumps(task_steps, indent=2, ensure_ascii=False) + "\n").encode())
    return list(tasks)
