"""`agent-env gridsim record`: one Episode JSON filmed on the viewer. The viewer serves as `view` serves it; the filming
is the viewer's own recorder, ``film(base_url, episode, out, fps)`` in src/agentenv_gridsim/web/record.py."""

import importlib.util
import threading
from pathlib import Path

import click

from .sweep import RUNS
from .view import WEB, index, serve


def recorder():
    path = WEB / "record.py"
    if not path.is_file():
        raise click.ClickException(f"no recorder at {path}: it ships with the viewer")
    spec = importlib.util.spec_from_file_location("gridsim_web_record", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@click.command("record")
@click.argument("episode")
@click.option("--runs", type=click.Path(file_okay=False, path_type=Path), default=RUNS, show_default=True,
              help="The folder of Episode JSON EPISODE is under.")
@click.option("--out", type=click.Path(dir_okay=False, path_type=Path), help="The MP4 to write. Default: "
              "results/videos/<episode file name>.mp4.")
@click.option("--fps", default=30, show_default=True, help="Frames per second.")
def record_command(episode: str, runs: Path, out: Path | None, fps: int):
    """Film EPISODE (its path under --runs, as /runs/index.json lists it) on the viewer, into an MP4."""
    if episode not in {e["path"] for e in index(runs)}:
        raise click.UsageError(f"no Episode JSON {episode!r} under {runs}")
    film = recorder().film
    out = out or Path("results/videos") / (Path(episode).stem + ".mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    server = serve(runs, 0)
    try:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        film(f"http://127.0.0.1:{server.server_port}", episode, out, fps)
    finally:
        server.shutdown()
        server.server_close()
    click.echo(f"Wrote {out}")
