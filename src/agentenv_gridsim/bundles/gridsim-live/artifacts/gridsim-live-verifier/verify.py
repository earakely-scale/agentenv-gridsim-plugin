"""Score a live GridSim day with the reward of the day it executed (1.0 at the notice-blind rolling re-planner); a day
that never finished, or whose audit failed, raises, so the run is not scored. Weight-0 rows carry the audit and the
hindsight capture."""

from agentenv_protocol import client


async def verify(mcp_url: str) -> list[dict]:
    day = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not day.get("task_id"):
        raise RuntimeError("the gridsim-live env has no day: no apply_server_config urn:gridsim:live-load/v1 ran")
    if not day["done"] or not day["audit"]["ok"]:
        raise RuntimeError(f"the day can't be scored: done {day['done']}, audit {day['audit']}")
    g = day["grade"]
    capture = g["capture_vs_hindsight"]
    return [{"criterion": "gridsim", "description": "the day's reward, 1.0 at the notice-blind rolling re-planner",
             "result": g["reward"] >= 1.0, "score": g["reward"], "weight": 1.0, "episode": day},
            {"criterion": "audit", "description": "every watch got its notices in order before the agent's next call, "
                                                  "none early or twice, no RT price before its interval ended, and "
                                                  "every output replays byte for byte",
             "result": True, "score": 1.0, "weight": 0.0},
            {"criterion": "hindsight_capture", "description": "(P - P_idle) / (P_hind - P_idle)",
             "result": capture is not None and capture >= 1.0, "score": capture or 0.0, "weight": 0.0}]
