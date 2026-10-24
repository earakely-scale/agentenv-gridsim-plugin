import os
import sys
from pathlib import Path

import pytest
from agent_env.config import reset_config
from fastmcp import Client

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / d) for d in ("plugin", "live")]

from sweep_fake import fake  # noqa: E402, F401

from agentenv_gridsim.forecast import FORECAST_PACK_NAMES, GridSimForecastEnv  # noqa: E402
from agentenv_gridsim.server import TaskIndex, pack_dirs  # noqa: E402


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def env():
    env = GridSimForecastEnv(TaskIndex(pack_dirs(FORECAST_PACK_NAMES)))
    env.create_app()
    return env


@pytest.fixture
async def client(env):
    async with Client(env.mcp) as c:
        yield c


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
