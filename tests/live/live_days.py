"""The live fixture days, the naive policy's calls, a stand-in for the gateway's clock, and the live env server."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from agentenv_gridsim import live_tasks
from gridsim_core.live import LIVE_ENV, Session

ROWS = live_tasks.pack_rows("fixtures-live")
assert ROWS, "no live fixture days in data/fixtures-live"
NOTICE_DAY = next(r for r in ROWS if r["task_id"].endswith("-notice"))
DERATE_DAY = next(r for r in ROWS if r["task_id"].endswith("-derate"))
QUIET_DAY = next(r for r in ROWS if not r["notices"])


def naive_calls(task: dict, tier: str = "foresight") -> list[list[tuple[str, dict]]]:
    """One list of calls per watch: the naive DA position at watch 0, then advance; get_situation after each advance
    that opens a watch."""
    n = len(Session(task, tier).watches)
    return [([("commit_da", {"position": task["refs"]["naive"]["da"]})] if k == 0 else []) + [("advance", {})]
            + ([("get_situation", {})] if k < n - 1 else []) for k in range(n)]


def in_process(task: dict, tier: str, calls: list) -> tuple[Session, list[str]]:
    """The calls on a Session, each watch's notices delivered after the advance that opens it, as the triggers do."""
    s, outs = Session(task, tier), []
    for name, args in (c for watch in calls for c in watch):
        outs.append(s.call(name, args))
        if name == "advance" and "watch" in json.loads(outs[-1]):
            s.deliver_watch_notices()
    return s, outs


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakeClock:
    """The gateway's clock endpoints on a free port: GET /clock/time and PUT /clock/set-time, each set recorded."""

    def __init__(self, virtual_time: str):
        self.virtual_time, self.sets = virtual_time, []

        async def get(request: Request):
            return JSONResponse({"virtual_time": self.virtual_time})

        async def put(request: Request):
            body = await request.json()
            self.sets.append(body)
            self.virtual_time = body["virtual_time"]
            return JSONResponse({"ok": True})

        app = Starlette(routes=[Route("/clock/time", get, methods=["GET"]),
                                Route("/clock/set-time", put, methods=["PUT"])])
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))

    def __enter__(self) -> "FakeClock":
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.01)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}/clock/time"
        return self

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join()


@contextmanager
def live_server(name: str = LIVE_ENV):
    """`python -m agentenv_gridsim.server` as the gateway runs it for gridsim-live (or ``name``), on a free port: its
    base URL."""
    port = free_port()
    proc = subprocess.Popen([sys.executable, "-m", "agentenv_gridsim.server"],
                            env={**os.environ, "ENVIRONMENT_NAME": name, "MCP_HOST": "127.0.0.1",
                                 "MCP_PORT": str(port)}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 30
    try:
        while True:
            try:
                httpx.get(f"{base}/.well-known/agent-env.json").raise_for_status()
                break
            except httpx.HTTPError:
                assert proc.poll() is None and time.monotonic() < deadline, "the live env server did not start"
                time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        proc.wait(10)
