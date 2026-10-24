import json
import os
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager

import httpx
import pytest
from agent_env.config import reset_config
from agentenv_protocol import client
from fastmcp import Client
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sweep_fake import fake  # noqa: F401

from agentenv_gridsim.server import LOAD_URI, GridSimEnv, read_pack
from gridsim_core.task import data_root

FIXTURES = read_pack(data_root() / "fixtures")
assert FIXTURES, f"no fixture tasks at {data_root() / 'fixtures'}"
BLIND = [t for t in FIXTURES if t.get("blind") and (t.get("refs") or {}).get("blind")]
assert BLIND, "no fixture task has a blind tier"
TASK = FIXTURES[0]
OPT = TASK["refs"]["foresight"]["opt"]


@pytest.fixture
def anyio_backend():
    return "asyncio"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def server():
    """The env server at GRIDSIM_URL (CI points it at the image), else `python -m agentenv_gridsim.server`, as the
    image runs it, on a free port."""
    if url := os.environ.get("GRIDSIM_URL"):
        yield url
        return
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "agentenv_gridsim.server"],
                            env={**os.environ, "MCP_HOST": "127.0.0.1", "MCP_PORT": str(port)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    while True:
        try:
            httpx.get(f"{base}/.well-known/agent-env.json").raise_for_status()
            break
        except httpx.HTTPError:
            assert proc.poll() is None and time.monotonic() < deadline, "the env server did not start"
            time.sleep(0.1)
    yield base
    proc.terminate()
    proc.wait(10)


class Harness:
    """Drives the env server as agent-env does: its extensions over REST, its tools over MCP."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.card = httpx.get(f"{base_url}/.well-known/agent-env.json").json()

    async def invoke(self, uri: str, args: dict, method: str | None = None):
        return await client.invoke_extension(self.base_url, self.card, uri, args, method=method)

    async def load_task(self, task: dict, tier: str = "foresight", checks: int = 3, explicit: bool = False) -> None:
        await self.invoke(LOAD_URI, {"task_id": task["task_id"], "tier": tier, "checks": checks}
                          | ({"task": task} if explicit else {}))

    async def data(self) -> dict:
        return (await client.get_data(self.base_url)).parts[0].data

    @asynccontextmanager
    async def session(self):
        async with streamable_http_client(f"{self.base_url}/mcp") as (read, write, _), \
                ClientSession(read, write) as session:
            await session.initialize()
            yield session

    @staticmethod
    async def call(session: ClientSession, name: str, arguments: dict) -> str:
        """The tool's output as gridsim-llm hands it to the model: its text, or {"error": text}."""
        result = await session.call_tool(name, arguments)
        text = "\n".join(block.text for block in result.content if block.type == "text")
        return json.dumps({"error": text}) if result.isError else text


@pytest.fixture(scope="session")
def harness(server):
    return Harness(server)


class Tools:
    """Calls tools as an MCP client does: through argument validation and the episode middleware."""

    def __init__(self, client: Client):
        self.client = client

    async def __call__(self, name: str, **arguments) -> dict:
        result = await self.client.call_tool_mcp(name, arguments)
        assert not result.isError, result.content[0].text
        return json.loads(result.content[0].text)

    async def error(self, name: str, **arguments) -> str:
        result = await self.client.call_tool_mcp(name, arguments)
        assert result.isError
        return result.content[0].text


@pytest.fixture
def env():
    env = GridSimEnv()
    env.create_app()
    env.load_task(TASK["task_id"])
    return env


@pytest.fixture
async def tools(env):
    async with Client(env.mcp) as c:
        yield Tools(c)


@pytest.fixture
def local_stores(monkeypatch, tmp_path):
    """agent-env on its local default stores under tmp_path, whatever config the machine has."""
    config = tmp_path / "config.toml"
    config.write_text("")
    for var in [v for v in os.environ if v.startswith("AGENT_ENV_")]:
        monkeypatch.delenv(var)
    monkeypatch.setenv("AGENT_ENV_CONFIG", str(config))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    reset_config()
    yield tmp_path / "state"
    reset_config()
