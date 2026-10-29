"""The env box's OpenEnv server: the desk-v4-train bundle served by agent_env.openenv.build_app under uvicorn, for a
trainer on another machine reading it with AgentEnv("http://ENV_HOST:PORT"). Each session plays one operating day in
local Docker; the reward is the hindsight capture C floored at -1, made from the bundle's `capture` step (scored as
(max(C, -1) + 1) / 2), or R with REWARD=grade. MAX_CONCURRENT_ENVS must cover every environment the trainer holds:
one per rollout it generates at once."""

import os

import uvicorn
from agent_env.openenv import build_app


def capture(scores: dict[str, float]) -> float:
    return 2 * scores["capture"] - 1


reward = capture if os.environ.get("REWARD", "capture") == "capture" else "grade"
app = build_app(os.environ.get("BUNDLE", "bundles/desk-v4-train"), reward=reward,
                max_concurrent_envs=int(os.environ.get("MAX_CONCURRENT_ENVS", "48")))
uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", "8000")), log_level="warning")
