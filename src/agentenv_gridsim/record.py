"""`agent-env gridsim record`: one Episode JSON filmed on the viewer by the viewer's own recorder, scripts/record.py in
the checkout (headless Chrome frame by frame into an MP4, a still or a thumbnail)."""

import json
import subprocess
import sys
from pathlib import Path

import click

from .view import WEATHER

ROOTS = [Path(__file__).resolve().parents[2], Path.cwd()]


def recorder() -> Path:
    for root in ROOTS:
        if (path := root / "scripts" / "record.py").is_file() and (root / "src/agentenv_gridsim/web").is_dir():
            return path
    raise click.UsageError("no scripts/record.py: run `agent-env gridsim record` from a checkout of "
                           "agentenv-gridsim-plugin")


@click.command("record", context_settings={"ignore_unknown_options": True})
@click.argument("episode", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path),
              help="The MP4 to write. Default: results/videos/<episode file name>.mp4.")
@click.option("--weather", type=click.Path(file_okay=False, path_type=Path), default=WEATHER, show_default=True,
              help="The weather sidecars, <date>_<point>.json.")
@click.argument("extra", nargs=-1, type=click.UNPROCESSED)
def record_command(episode: Path, out: Path | None, weather: Path, extra: tuple[str, ...]):
    """Film EPISODE, an Episode JSON file, on the viewer; options after it (--still, --thumb, --t, --seconds, --fps,
    --size, --reduced) go to the recorder."""
    script = recorder()
    sidecar = weather / f"{_key(episode)}.json"
    args = ["--episode", str(episode.resolve()), *(["--weather", str(sidecar.resolve())] if sidecar.is_file() else [])]
    if not {"--still", "--thumb"} & set(extra):
        out = out or Path("results/videos") / f"{episode.stem}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        args += ["--out", str(out.resolve())]
    code = subprocess.run([sys.executable, str(script), *args, *extra], cwd=script.parents[1]).returncode
    if code:
        raise click.ClickException(f"the recorder exited {code}")


def _key(episode: Path) -> str:
    """The weather sidecar's name for the episode's day: <date>_<point>."""
    task = json.loads(episode.read_text())["task"]
    return f"{task['date']}_{task['settlement_point']}"
