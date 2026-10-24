"""`agent-env gridsim view`'s routes: the viewer, the Episode JSON under a runs folder and their index, the weather."""

import json

from conftest import TASK

from agentenv_gridsim.view import episode_url, index, route
from gridsim_core.episode import to_episode_json


def test_the_routes_serve_the_episodes_their_index_and_the_weather(tmp_path):
    runs, weather = tmp_path / "runs", tmp_path / "weather"
    (runs / "s").mkdir(parents=True)
    weather.mkdir()
    e = to_episode_json(TASK, TASK["refs"]["foresight"]["opt"], bundle="full", path="A", model="m")
    (runs / "s/day.json").write_text(json.dumps(e))
    (runs / "s/raw").mkdir()
    (runs / "s/raw/results.json").write_text(json.dumps({"not": "an episode"}))
    (weather / "2024-07-18_HB_WEST.json").write_text("{}")
    [listed] = index(runs)
    assert (listed["path"], listed["task_id"], listed["reward"], listed["model"]) == ("s/day.json", TASK["task_id"],
                                                                                      1.0, "m")
    status, headers, body = route(runs, "/runs/index.json", weather)
    assert (status, json.loads(body)) == (200, {"schema": "gridsim.runs/v1", "episodes": [listed]})
    assert (listed["url"], listed["point"], listed["profit"]) == ("s/day.json", TASK["settlement_point"],
                                                                  e["profit_usd"])
    assert route(runs, "/runs/s/day.json", weather)[2] == (runs / "s/day.json").read_bytes()
    assert route(runs, "/weather/2024-07-18_HB_WEST.json", weather)[:2] == (200, {"Content-Type": "application/json"})
    assert route(runs, "/runs/../../etc/passwd", weather)[0] == 404
    assert route(runs, "/", weather) == (302, {"Location": "/web/index.html?index=/runs/index.json&wxbase=/weather"},
                                         b"")
    assert episode_url("s/day 1.json") == "/web/index.html?episode=/runs/s/day%201.json&wxbase=/weather"
