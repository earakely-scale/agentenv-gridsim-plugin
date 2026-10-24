"""Score a GridSim episode: its submitted schedule graded again by gridsim_core on the task row the env played, which
must agree with the env's own grade; 0 when nothing was submitted. A weight-0 row carries the hindsight capture."""

from agentenv_protocol import client
from gridsim_core.grade import grade

TOLERANCE = 1e-6


async def verify(mcp_url: str) -> list[dict]:
    episode = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not episode.get("task_id"):
        raise RuntimeError("the gridsim env has no task loaded: no apply_server_config urn:gridsim:load-task/v1 ran")
    reward = r_opt = 0.0
    if episode["done"] and episode["schedule"] is not None:
        task = episode["task"]
        if task["task_id"] != episode["task_id"]:
            raise RuntimeError(f"the env played {task['task_id']!r}, not {episode['task_id']!r}")
        g = grade(task, episode["schedule"], episode["tier"])
        if max(abs(g["reward"] - episode["reward"]), abs(g["reward"] - episode["grade"]["reward"])) > TOLERANCE:
            raise RuntimeError(f"gridsim_core grades the schedule {g['reward']}, the env reported {episode['reward']}")
        reward, r_opt = float(g["reward"]), float(g["r_opt"])
    slim = {k: v for k, v in episode.items() if k != "task"}
    return [{"criterion": "gridsim", "description": "the day's reward, 1.0 at the anchor", "result": reward >= 1.0,
             "score": reward, "weight": 1.0, "episode": slim},
            {"criterion": "hindsight_capture", "description": "r_opt: the reward against the exact optimum",
             "result": r_opt >= 1.0, "score": r_opt, "weight": 0.0}]
