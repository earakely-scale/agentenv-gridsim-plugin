"""Score a GridSim v1 episode from the env's own report: the day's reward for the schedule it settled, graded by the
env against the exact DP optimum, with the hindsight capture r_opt as a weight-0 row; 0 when nothing was submitted.
It imports nothing but the framework, so the training bundle scores with no GridSim installed where it is served."""

from agentenv_protocol import client

TOLERANCE = 1e-6


async def verify(mcp_url: str) -> list[dict]:
    episode = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not episode.get("task_id"):
        raise RuntimeError("the gridsim env has no task loaded: no apply_server_config urn:gridsim:load-task/v1 ran")
    reward = r_opt = 0.0
    if episode["done"] and episode["schedule"] is not None:
        if episode["task"]["task_id"] != episode["task_id"]:
            raise RuntimeError(f"the env played {episode['task']['task_id']!r}, not {episode['task_id']!r}")
        grade = episode["grade"]
        if abs(grade["reward"] - episode["reward"]) > TOLERANCE:
            raise RuntimeError(f"the env graded the schedule {grade['reward']} and reported {episode['reward']}")
        reward, r_opt = float(grade["reward"]), float(grade["r_opt"])
    slim = {k: v for k, v in episode.items() if k != "task"}
    return [{"criterion": "gridsim", "description": "the day's reward, 1.0 at the DP optimum", "result": reward >= 1.0,
             "score": reward, "weight": 1.0, "episode": slim},
            {"criterion": "hindsight_capture", "description": "r_opt: the reward against the exact optimum",
             "result": r_opt >= 1.0, "score": r_opt, "weight": 0.0}]
