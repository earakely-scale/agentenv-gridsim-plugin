"""Desk packs as folder bundles: one task per episode on the layer's gridsim-desk env, its clock armed frozen at D-1
06:00 CPT, played on gridsim_core.desk's start message and woken between turns by the gridsim-desk-hook post-turn hook,
and graded by gridsim-desk-verifier through the env's hidden grade tool."""

import json
from importlib.resources import files
from pathlib import Path

import click

from gridsim_core.desk import Session, load_series, load_tasks
from gridsim_core.desk.clock import START, to_utc

from .desk import HIDDEN, HOOK_ROLE, LOAD_URI, env_name, text

HOOK = "gridsim-desk-hook"
VERIFIER = "gridsim-desk-verifier"
ARTIFACTS = files("agentenv_gridsim.bundles") / "gridsim-desk/artifacts"
CLOCK_TOOL = "get_time"
MODEL_PARAMS = {"max_tokens": 8192}
EFFORT = "high"
PLAY_SECONDS = 4 * 3600
SYSTEM = ("You are the battery trader at a QSE running one battery energy storage resource in ERCOT. Act through your "
          "tools: submit DAM and real-time offer curves and keep the COP current; clearing decides what the battery "
          "does. Time is frozen while you work and moves only when you end your turn (reply without a tool call): you "
          "are woken at market milestones, notices, outages and your own reminders. Each wake-up is a JSON message "
          "with the time, the reasons, the events since and your budget.")
LICENCE = ("Prices and system data: ERCOT public reports (Nodal Protocols market data); ERCOT does not endorse this "
           "work. Weather alerts: NWS.")


def steps(task: dict, series: dict, pack: str, agent: str | None = None, system: str = SYSTEM) -> list[dict]:
    """deploy the layer's desk env, load the task, show the hidden tools to the hook role and hide get_time from the
    agent, deploy the agent, arm the clock frozen at the start, play from the start wake with the hook, grade."""
    s = Session(task, series)
    env = env_name(s.layer, s.era)
    return [
        {"id": "deploy", "type": "deploy_env", "env_id": env},
        {"id": "load-task", "type": "apply_server_config", "env_id": env,
         "directives": [{"service": env, "uri": LOAD_URI, "args": {"task_id": task["task_id"], "pack": pack}}]},
        {"id": "hook-tools", "type": "modify_env_tool_access", "env_id": env, "action": "enable", "role": HOOK_ROLE,
         "tools": list(HIDDEN)},
        {"id": "hide-clock", "type": "modify_env_tool_access", "env_id": env, "action": "disable", "role": "default",
         "tools": [CLOCK_TOOL]},
        {"id": "deploy-agent", "type": "deploy_agent", "env_ids": [env]} | ({"a2a_agent_id": agent} if agent else {}),
        {"id": "clock", "type": "sync_env_clock", "env_id": env, "virtual_time": to_utc(START, s.d0),
         "virtual_seconds_per_real_second": 0, "tolerate_missing_sync_time": False},
        {"id": "play", "type": "prompt_agent", "prompt_id": task["task_id"], "system_prompt": system,
         "prompt": text(s.start()), "max_conversation_turns": s.budget["max_turns"], "model_params": MODEL_PARAMS,
         "effort": EFFORT, "timeout_seconds": PLAY_SECONDS,
         "post_turn_hooks": [{"file_artifact_id": HOOK, "params": {"env_id": env}}]},
        {"id": "grade", "type": "env_outcome_verifier", "env_id": env, "file_artifact_id": VERIFIER,
         "verifier_id": "gridsim-desk", "score_aggregator": "weighted_average"},
    ]


def generate(pack: str, out: Path, *, task_ids: list[str] | None = None, agent: str | None = None,
             image_pack: str | None = None) -> list[str]:
    """Writes the bundle into ``out``: README.md, the hook, the verifier and tasks/<task_id>.json for ``task_ids`` or
    every task of the pack, in the pack's order. ``image_pack`` is the pack's name in the env image, by default the
    pack's (folder) name."""
    rows = load_tasks(pack)
    if task_ids is not None:
        if unknown := sorted(set(task_ids) - {r["task_id"] for r in rows}):
            raise click.UsageError(f"not tasks of {pack}: {', '.join(unknown)}")
        rows = [r for r in rows if r["task_id"] in task_ids]
    _write(out / "README.md", (f"GridSim desk {pack}: {len(rows)} episodes on the gridsim-desk envs, each woken by "
                               f"{HOOK} and graded by {VERIFIER}.\n\n{LICENCE}\n").encode())
    for artifact, name in ((HOOK, "hook.py"), (VERIFIER, "verify.py")):
        _write(out / "artifacts" / artifact / name, (ARTIFACTS / artifact / name).read_bytes())
    for row in rows:
        task_steps = steps(row, load_series(pack, row), image_pack or Path(pack).name, agent)
        _write(out / "tasks" / f"{row['task_id']}.json",
               (json.dumps(task_steps, indent=2, ensure_ascii=False) + "\n").encode())
    return [r["task_id"] for r in rows]


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@click.command("desk-tasks")
@click.option("--pack", required=True, help="A desk pack under data/desk/ (or its folder).")
@click.option("--task", "task_ids", multiple=True, help="Only these task ids.")
@click.option("--agent", help="The A2A agent id the tasks deploy; default the framework's default agent.")
@click.option("--out", type=click.Path(file_okay=False, path_type=Path), help="Default: results/bundles/desk-<pack>.")
def desk_tasks_command(pack: str, task_ids: tuple[str, ...], agent: str | None, out: Path | None):
    """Write a bundle with one task per desk episode of the pack."""
    out = out or Path("results/bundles") / f"desk-{Path(pack).name}"
    names = generate(pack, out, task_ids=list(task_ids) or None, agent=agent)
    click.echo(f"Wrote {len(names)} tasks into {out}; play one with: agent-env run {out} --task {names[0]}")
