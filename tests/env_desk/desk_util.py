"""Shared by the desk env tests: a one-task desk pack folder as the env loads packs, and the anyio and local-store
fixtures (here rather than in a conftest, which would shadow tests/plugin's `from conftest import`)."""

import gzip
import json
import os

import pytest
from agent_env.config import reset_config


def pack(tmp_path, task, series):
    (tmp_path / "series").mkdir()
    with gzip.open(tmp_path / "tasks.jsonl.gz", "wt") as f:
        f.write(json.dumps(task) + "\n")
    with gzip.open(tmp_path / task["series"], "wt") as f:
        json.dump(series, f)
    return str(tmp_path)


@pytest.fixture
def anyio_backend():
    return "asyncio"


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
