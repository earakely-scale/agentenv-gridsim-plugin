"""The GridSimEnv Desk OpenEnv Space (hub/openenv): a recorded benchmark episode replays through it byte for byte, grade
included; its budgets and its end are the desk's; the play page's view never runs past the desk's minute; and every
WebSocket session and playground visitor plays alone."""

import asyncio
import gzip
import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("openenv")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "hub" / "openenv"))

from fastapi.testclient import TestClient  # noqa: E402
from gradio.context import LocalContext  # noqa: E402
from openenv.core.env_server.mcp_types import CallToolAction, CallToolObservation, ListToolsAction  # noqa: E402
from server import environment, windows  # noqa: E402
from server.app import create_server  # noqa: E402
from server.environment import GridSimDeskEnvironment, describe  # noqa: E402
from server.playground import PerVisitor  # noqa: E402

from gridsim_core.desk import Session, clock, load_series, load_tasks, text  # noqa: E402

PACK = "desk-v4-bench"
HERO = "desk-v4-2026-08-18-S02"
SOL = ROOT / "results" / PACK / "episodes" / "sol" / f"{HERO}.gpt-6.1-sol.json.gz"


@pytest.fixture(scope="module", autouse=True)
def data(tmp_path_factory):
    """The benchmark pack and a catalog with the fields the server reads; the weather is two reports a day apart."""
    root = tmp_path_factory.mktemp("space-data")
    (root / PACK).symlink_to(ROOT / "data" / "desk" / PACK)
    tasks = load_tasks(PACK)
    refs = ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual")
    (root / "windows.json").write_text(json.dumps({
        "pack": PACK, "split": "bench", "default": HERO, "order": [t["task_id"] for t in tasks], "models": {},
        "windows": {t["task_id"]: {"index": i, "task_id": t["task_id"], "title": t["task_id"]}
                    for i, t in enumerate(tasks)},
        "scenes": {t["task_id"]: {"weather": [{"t": -20.0, "temp_c": 30.0}, {"t": 4.0, "temp_c": 31.0}]}
                   for t in tasks},
        "bench": {t["task_id"]: {"refs": {k: t["refs"][k] for k in refs}, "models": []} for t in tasks}}))
    old = os.environ.get("GRIDSIM_DATA")
    os.environ["GRIDSIM_DATA"] = str(root)
    windows.windows.cache_clear()
    environment.opening.cache_clear()
    yield root
    os.environ.pop("GRIDSIM_DATA") if old is None else os.environ.update(GRIDSIM_DATA=old)
    windows.windows.cache_clear()


def call(env, name: str, **args):
    return env.step(CallToolAction(tool_name=name, arguments=args))


def test_a_benchmark_episode_replays_byte_for_byte():
    ep = json.load(gzip.open(SOL))
    env = GridSimDeskEnvironment()
    assert env.reset(task_id=HERO).metadata["prompt"] == text(ep["turns"][0]["wake"])
    for i, turn in enumerate(ep["turns"]):
        for c in turn["calls"]:
            assert call(env, c["tool"], **c["args"]).result["data"] == text(c["result"]), (i, c["tool"])
        obs = call(env, "end_turn", response=turn.get("text") or "")
        if i + 1 < len(ep["turns"]):
            assert obs.result["prompt"] == text(ep["turns"][i + 1]["wake"]), i
    assert obs.done and obs.reward == ep["grade"]["reward"]
    assert {k: obs.metadata["grade"][k] for k in ("p", "capture", "valid")} == {k: ep["grade"][k] for k in
                                                                               ("p", "capture", "valid")}
    assert obs.metadata["rubric"] == {"capture": ep["grade"]["capture"], "valid": 1.0}


def test_the_budget_and_the_end_are_the_desks():
    env = GridSimDeskEnvironment()
    assert [t.name for t in env.step(ListToolsAction()).tools][-1] == "end_turn"
    with pytest.raises(RuntimeError):
        call(env, "get_asset_status")
    env.reset(task_id=HERO)
    outs = [call(env, "get_asset_status") for _ in range(15)]
    assert outs[13].metadata["desk"]["calls_left"] == 0
    assert json.loads(outs[14].result["data"])["error"].startswith("budget:")
    assert call(env, "not_a_tool").error.error_type == "tool_not_found"
    obs = call(env, "end_turn")
    assert obs.metadata["desk"]["calls_left"] == 14 and not obs.done and obs.reward == 0.0
    while not obs.done:
        obs = call(env, "end_turn")
    assert obs.reward == 0.0 and obs.metadata["grade"]["valid"] is False
    assert json.loads(call(env, "get_asset_status").result["data"]) == {"error": "over: the episode has ended"}


def test_the_view_never_runs_past_the_desks_minute():
    env = GridSimDeskEnvironment()
    env.reset(task_id=HERO)
    while env.s.now < 300:
        call(env, "end_turn")
    s, v = env.s, env.view()
    assert v["desk"]["minute"] == s.now
    assert len(v["m"]) == s.engine.k and len(v["soc"]) == s.engine.k + 1
    assert len(v["pnl"]) == (s.now - 2) // 15 // 4 and v["settled"]["upto"] == (s.now - 2) // 15
    assert [o["t"] for o in v["weather"]] == [-20.0, 4.0] and "grade" not in v
    env.reset(task_id=HERO)
    assert [o["t"] for o in env.view()["weather"]] == [-20.0] and env.view()["m"] == []
    assert [w[0] for w in v["wakes"]] == [w["t"] for w in s.wakes]


def test_the_task_api_describes_windows_as_agentenvs_adapter_does():
    tasks = {t["task_id"]: t for t in load_tasks(PACK)}
    d = describe("bench", 25)
    assert (d["id"], d["index"], d["turns"]) == (HERO, 25, 1)
    assert set(d["toolset"]) == {"envs", "versions", "role", "access", "bash"}
    assert d["prompt"] == text(Session(tasks[HERO], load_series(PACK, tasks[HERO])).start())
    with pytest.raises(IndexError):
        describe("bench", 32)


def test_each_websocket_session_plays_alone():
    with TestClient(create_server()) as client:
        assert client.get("/healthz").json()["windows"] == {"bench": 32}
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 1}).json()
        assert [t["name"] for t in listed["result"]["tools"]][-1] == "end_turn" and len(listed["result"]["tools"]) == 12
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            ask = lambda ws, msg: (ws.send_text(json.dumps(msg)), json.loads(ws.receive_text()))[1]  # noqa: E731
            ta = ask(a, {"type": "reset", "data": {"task_id": HERO}})["data"]["observation"]["metadata"]["episode"]
            tb = ask(b, {"type": "reset", "data": {"split": "bench", "index": 0}})["data"]["observation"]["metadata"][
                "episode"]
            for _ in range(3):
                ask(a, {"type": "step", "data": {"type": "call_tool", "tool_name": "end_turn", "arguments": {}}})
            ask(b, {"type": "step", "data": {"type": "call_tool", "tool_name": "get_asset_status", "arguments": {}}})
            va, vb = client.get(f"/api/episodes/{ta}").json(), client.get(f"/api/episodes/{tb}").json()
            assert va["desk"]["turn"] == 4 and va["desk"]["minute"] > clock.START
            assert vb["desk"] == {**vb["desk"], "turn": 1, "minute": clock.START, "calls_left": 13}
        assert client.get(f"/api/episodes/{ta}").status_code == 404
        assert client.get(f"/api/episodes/{'0' * 32}").status_code == 404


def test_the_playground_keeps_an_episode_per_visitor():
    visitors = PerVisitor(GridSimDeskEnvironment, CallToolAction, CallToolObservation, None)

    async def as_visitor(key: str, *actions):
        LocalContext.request.set(type("Request", (), {"session_hash": key})())
        await visitors.reset_environment()
        for a in actions:
            await visitors.step_environment(a)

    end = {"type": "call_tool", "tool_name": "end_turn", "arguments": {}}
    asyncio.run(as_visitor("a", end, end))
    asyncio.run(as_visitor("b"))
    a, b = (visitors.managers[k][0].env.s for k in ("a", "b"))
    assert a.turn == 2 and b.turn == 0 and a.now > b.now == clock.START
