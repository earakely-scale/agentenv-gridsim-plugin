"""`agent-env gridsim episodes`: a sweep's scored runs as gridsim.episode/v1 JSON (gridsim_core.episode), each recorded
tool call played again on a fresh gridsim env through its MCP tools and its output checked against the record, and
the verifier's reward against gridsim_core's grade of the schedule, so the viewer shows only what replays."""

import asyncio
import json
from pathlib import Path

import click
from fastmcp import Client

from gridsim_core.episode import to_episode_json
from gridsim_core.grade import grade

from .server import GridSimEnv, TaskIndex, pack_dirs
from .sweep import LABELS, RUNS, Sweep, load, results, slug
from .tasks import BUNDLES, HIDDEN_IN_ONESHOT

TOLERANCE = 1e-6
EXCERPT_CHARS = 2000


class ReplayError(Exception):
    pass


async def _replay(task: dict, tier: str, bundle: str, steps: list[dict]) -> dict:
    env = GridSimEnv()
    env.create_app()
    env.load_task(task["task_id"], tier, BUNDLES[bundle], task=task)
    if bundle == "oneshot":
        env.disable("default", HIDDEN_IN_ONESHOT)
    async with Client(env.mcp) as client:
        for step in steps:
            result = await client.call_tool_mcp(step["tool"], step["args"])
            text = "\n".join(c.text for c in result.content if c.type == "text")
            out = {"error": text} if result.isError else json.loads(text)
            if out != step["output"]:
                raise ReplayError(f"call {step['t']} {step['tool']} returns {json.dumps(out)}, recorded "
                                  f"{json.dumps(step['output'])}")
    return env.get()[0].data


def replay(task: dict, tier: str, bundle: str, steps: list[dict]) -> dict:
    """The env's data/get once the recorded calls are played again; ReplayError at the first output that differs."""
    return asyncio.run(_replay(task, tier, bundle, steps))


def episode(sweep: Sweep, row: dict, task: dict) -> dict:
    """The run's Episode JSON, once every recorded output replays and the rewards agree."""
    if not row.get("transcript"):
        raise ReplayError("no transcript recorded")
    record = json.loads((sweep.out / row["transcript"]).read_text())
    steps = [{"t": s["t"], "tool": s["tool"], "args": s["args"], "output": s["output"]} for s in record["steps"]]
    data = replay(task, sweep.tier, sweep.bundle, steps)
    schedule = data["schedule"]
    graded = grade(task, schedule, sweep.tier)["reward"] if schedule is not None else 0.0
    if abs((data["reward"] or 0.0) - graded) > TOLERANCE or abs(row["reward"] - graded) > TOLERANCE:
        raise ReplayError(f"rewards differ: replay {data['reward']}, gridsim_core {graded}, verifier {row['reward']}")
    usage = record["usage"] | {"usd": row["cost_usd"]}
    excerpt = [{"role": "assistant", "content": m["content"][:EXCERPT_CHARS]}
               for m in record["messages"] if m["role"] == "assistant" and m.get("content")]
    e = to_episode_json(task, schedule, sweep.tier, BUNDLES[sweep.bundle], steps=steps, bundle=sweep.bundle,
                        path="A", model=row["model"], trained="base", messages=excerpt, usage=usage,
                        wall_seconds=row["wall_seconds"], episode_id=row["instance"].rsplit("/", 1)[-1])
    return e | {"model_label": LABELS.get(row["model"], row["model"])}


def write(name: str, echo=click.echo) -> tuple[list[Path], list[str]]:
    """Writes each scored run of the sweep ``name`` as RUNS/<name>/<task>-<model>-r<rep>.json; returns the files and
    the runs that didn't replay."""
    sweep = load(name)
    index = TaskIndex(pack_dirs())
    done, failed = [], []
    for row in results(sweep.out):
        if row["outcome"] != "scored":
            continue
        label = f"{row['model']} {row['task_id']} r{row['rep']} a{row['attempt']}"
        try:
            e = episode(sweep, row, index.get(row["task_id"]))
        except ReplayError as err:
            failed.append(f"{label}: {err}")
            echo(click.style(f"MISMATCH {label}: {err}", fg="red", bold=True), err=True)
            continue
        path = RUNS / name / f"{row['task_id']}-{slug(row['model'])}-r{row['rep']}.json"
        path.write_text(json.dumps(e, indent=1) + "\n")
        done.append(path)
    return done, failed


@click.command("episodes")
@click.argument("names", nargs=-1, required=True)
def episodes_command(names: tuple[str, ...]):
    """Write the sweeps NAMES' scored runs as Episode JSON under results/runs/<name>/, each replayed on a fresh env;
    a run whose recorded output or reward doesn't replay is listed and left out, and the command exits 1."""
    failed = []
    for name in names:
        done, bad = write(name)
        failed += bad
        click.echo(f"{name}: {len(done)} episodes written, {len(bad)} didn't replay")
    if failed:
        raise click.ClickException(f"{len(failed)} runs didn't replay:\n" + "\n".join(failed))
