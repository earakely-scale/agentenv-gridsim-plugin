"""The Training docs' hand-played rollout on the downloaded GridSim bundle: each docs snippet's expression, printed as
the docs show it, with the seconds each took. An idle schedule scores 0.2 and a 23-entry one is refused by the env."""

import inspect
import json
import time

from agent_env.training.trl import AgentEnv


def show(label, value, started):
    print(f"## {label} ({time.monotonic() - started:.1f}s)\n{value!r}\n", flush=True)


started = time.monotonic()
env = AgentEnv.local("bundles/gridsim-v1", split="train", max_concurrent_envs=2)
show("serve", env.url, started)
show("sizes", (len(env.dataset), len(env.dataset_for("eval"))), started)
row = env.dataset[0]
cut = {k: (v if k != "prompt" else [{"role": m["role"], "content": m["content"][:160] + "…"} for m in v])
       for k, v in row.items()}
print("## row\n" + json.dumps(cut, indent=2), flush=True)
print("## methods", [name for name in vars(env.factory) if not name.startswith("_")])
print("## signature", inspect.signature(env.factory.submit_schedule))
print("## doc", inspect.getdoc(env.factory.submit_schedule), flush=True)

environment = env.factory()
t = time.monotonic()
show("reset", environment.reset(**row), t)
t = time.monotonic()
show("submit 23", environment.submit_schedule(actions=[0] * 23), t)
t = time.monotonic()
show("submit idle", environment.submit_schedule(actions=[0] * 24), t)
t = time.monotonic()
show("end_turn", environment.end_turn(response="Submitted."), t)
t = time.monotonic()
show("reward", environment.get_reward(), t)

for _ in range(3):
    t = time.monotonic()
    environment.reset(**row)
    reset_s = time.monotonic() - t
    environment.submit_schedule(actions=[0] * 24)
    print(f"## rollout: reset {reset_s:.2f}s, reward {environment.get_reward()} after {time.monotonic() - t:.2f}s",
          flush=True)
env.close()
show("closed", None, started)
