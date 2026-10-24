"""`agent-env gridsim`: build and register the GridSim env and the gridsim-llm agent, write the eval tasks, sweep
models over them, report the board, turn the recorded runs into Episode JSON, and watch them."""

import json
import subprocess
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

import click
from agent_env.a2a_agent import A2AAgent
from agent_env.artifact import DockerImageArtifact
from agent_env.env import MCPServerEnv

from .episodes import episodes_command
from .record import record_command
from .sweep import sweep_group
from .tasks import AGENT, ENV, tasks_group
from .view import view_command

IMAGE = "agentenv-gridsim-env"
AGENT_IMAGE = "agentenv-gridsim-agent"
AGENT_MODEL = "openai/gpt-6.1-sol"
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"


@click.group()
def gridsim():
    """GridSim: build and register the env and agent, write the eval tasks, sweep models over them, report the board
    and watch the recorded runs."""


def _installed_commit() -> str | None:
    """The git commit a `pip install git+...` or uv git source installed this package from (PEP 610), if it did."""
    try:
        direct = json.loads(distribution("agentenv-gridsim").read_text("direct_url.json") or "{}")
    except PackageNotFoundError:
        return None
    return direct.get("vcs_info", {}).get("commit_id")


def _checkout(source: Path | None) -> str:
    """What to build from: ``source``, else the checkout an editable install runs from, else the cwd, else the commit
    of this repo a git install came from, which Docker fetches itself as a git build context."""
    for root in [source] if source else [Path(__file__).resolve().parents[2], Path.cwd()]:
        if (root / "Dockerfile").is_file() and (root / "src/agentenv_gridsim").is_dir():
            return str(root)
    if source:
        raise click.UsageError(f"{source} is not a checkout of agentenv-gridsim-plugin (no Dockerfile and src/)")
    if commit := _installed_commit():
        return f"{REPO}.git#{commit}"
    raise click.UsageError(f"no checkout of agentenv-gridsim-plugin found; clone {REPO} and pass --source")


def _context(root: str, subdir: str) -> str:
    return f"{root}:{subdir}" if "#" in root else str(Path(root) / subdir)


def _docker_platform() -> str:
    """The Docker host's own platform: the local `server` provider pulls images without emulation."""
    try:
        out = subprocess.run(["docker", "version", "--format", "{{.Server.Os}}/{{.Server.Arch}}"], capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise click.ClickException(f"docker is not available: {e}") from e
    if out.returncode:
        raise click.ClickException(f"docker is not running: {out.stderr.strip()}")
    return out.stdout.strip()


def _register_agent(root: str, build_platform: str) -> None:
    click.echo(f"Building {AGENT_IMAGE} for {build_platform}")
    build = ["docker", "build", "--platform", build_platform, "-t", AGENT_IMAGE, _context(root, f"agents/{AGENT}")]
    if subprocess.run(build).returncode:
        raise click.ClickException("docker build of the gridsim-llm agent failed")
    artifact = DockerImageArtifact.put(id=AGENT_IMAGE, image_name=AGENT_IMAGE,
                                       description="gridsim-llm: GridSim's harness loop as an A2A agent")
    agent = A2AAgent.put(id=AGENT, docker_image_artifact=artifact, metadata={"default_model": AGENT_MODEL})
    click.echo(f"Registered A2A agent {agent.id!r} version {agent.version} (image {artifact.image_name})")


@gridsim.command()
@click.option("--platform", "build_platform",
              help="Platform to build for. Default: the Docker host's (linux/arm64 on Apple Silicon); "
                   "remote sandboxes need linux/amd64.")
@click.option("--source", type=click.Path(exists=True, file_okay=False, path_type=Path),
              help="Checkout of this repo to build. Default: the one an editable install runs from, the cwd, or the "
                   "GitHub commit a git install came from.")
@click.option("--agent", is_flag=True, help="Also build the gridsim-llm agent for the same platform and register it.")
def setup(build_platform: str | None, source: Path | None, agent: bool):
    """Build the env image and register it as the MCP server env `gridsim` on the `server` provider; with --agent,
    the gridsim-llm agent too."""
    root = _checkout(source)
    build_platform = build_platform or _docker_platform()
    click.echo(f"Building {IMAGE} for {build_platform} from {root}")
    if subprocess.run(["docker", "build", "--platform", build_platform, "-t", IMAGE, root]).returncode:
        raise click.ClickException("docker build failed")
    click.echo("Storing the image (docker save, can take a minute)")
    artifact = DockerImageArtifact.put(id=IMAGE, image_name=IMAGE,
                                       description="GridSim env: the battery-desk MCP server and the ERCOT DAM packs")
    env = MCPServerEnv.put(id=ENV, docker_image_artifact=artifact, environment_name=ENV, env_provider_type="server")
    click.echo(f"Registered env {env.id!r} version {env.version} (image {artifact.image_name})")
    if agent:
        _register_agent(root, build_platform)
    click.echo("Next: agent-env run gridsim --task smoke")


gridsim.add_command(tasks_group)
gridsim.add_command(sweep_group)
gridsim.add_command(episodes_command)
gridsim.add_command(view_command)
gridsim.add_command(record_command)
