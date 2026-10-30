"""Pilot config 2 on one Modal H100: train.py as committed, at CONTEXT 40,960 with vLLM asleep while the trainer
optimises, and the desk-v4-train bundle served in the same container by serve.py with every episode a Modal sandbox,
its env image built on Modal from the bundle's build context (desk-v4-freeze plus both packs). Modal keys come from AWS
Secrets Manager in this process (profile agent-environments-admin) and reach the container as a secret that lives as
long as the run; nothing prints or stores them. Outputs (metrics, rollouts, completions, checkpoints, the adapter and
the server's log) land in the gridsim-desk-train volume under RUN.

    python modal_pilot.py check                     # no GPU: the images, one episode as a sandbox, the rendered tools
    RUN=pilot2-h100 python modal_pilot.py train     # the pilot, detached; MAX_STEPS, EVAL_LIMIT, ... pass through
"""

import inspect
import json
import os
import subprocess
import sys
import time
import urllib.request

import modal

NAME = "gridsim-desk-train"
REF = os.environ.get("PLUGIN_REF", "desk-train-v2")
REV = "1cfa9a7208912126459214e8b04321603b3df60c"
FRAMEWORK = "0.9.1387"
PLUGIN = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
KIT = "/root/plugin/results/train/desk-4b/scripts"
URL = "http://127.0.0.1:8000"
HOURS = 8
SETTINGS = ("MAX_STEPS", "EVAL_STEPS", "EVAL_ON_START", "EVAL_LIMIT", "EVAL_BATCH", "SAVE_STEPS", "LR", "VLLM_MEM",
            "VLLM_SLEEP", "FORMAT_PENALTY", "CONTEXT", "EVAL_SPLIT")
SERVER_CONFIG = """[stores]
document = "local"
object   = "local"
image    = "local"
secret   = "local"

[sandbox]
default       = "modal"
agent_default = "modal"
"""


def modal_keys() -> dict[str, str]:
    session = boto3.Session(profile_name="agent-environments-admin", region_name="us-west-2")
    ci = json.loads(session.client("secretsmanager").get_secret_value(
        SecretId="team/frontier-data/agent-env-ci-keys")["SecretString"])
    return {"MODAL_TOKEN_ID": ci["modal_token_id"], "MODAL_TOKEN_SECRET": ci["modal_token_secret"],
            "MODAL_ENVIRONMENT": "genai-agent-env"}


def plugin_commit() -> str:
    """The commit REF names now, so a new commit rebuilds the image's plugin layer."""
    heads = subprocess.run(["git", "ls-remote", PLUGIN, f"refs/heads/{REF}"], capture_output=True, text=True,
                           check=True)
    return heads.stdout.split()[0]


if modal.is_local():
    import boto3

    os.environ.pop("MODAL_PROFILE", None)
    os.environ.update(KEYS := modal_keys())
    COMMIT = plugin_commit()
else:
    KEYS, COMMIT = {}, ""

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "curl")
    .uv_pip_install(f"agentenv-framework[trl]=={FRAMEWORK}", "trl[vllm,peft]==1.16.*", "vllm==0.29.*",
                    "transformers==5.22.*")
    .run_commands(
        f"git clone -q {PLUGIN} /root/plugin && git -C /root/plugin checkout -q --detach {COMMIT}",
        "python -m venv /root/envbox && /root/envbox/bin/pip install -q uv",
        f"/root/envbox/bin/uv pip install -q --python /root/envbox/bin/python -e /root/plugin "
        f"'agentenv-framework[openenv]=={FRAMEWORK}'",
        "cd /root/plugin && /root/envbox/bin/python scripts/desk_train.py bundle --out /root/bundles/desk-v4-train",
        f"hf download Qwen/Qwen3-4B --revision {REV} --local-dir /root/models/Qwen3-4B",
    )
)
with image.imports():
    from agent_env.training.trl import AgentEnv
    from transformers import AutoTokenizer
volume = modal.Volume.from_name(NAME, create_if_missing=True)
keys = modal.Secret.from_dict(KEYS)
app = modal.App(NAME, image=image)


def serve(log: str) -> subprocess.Popen:
    """serve.py on 127.0.0.1:8000 with Modal sandboxes, once it answers."""
    os.makedirs("/root/state", exist_ok=True)
    with open("/root/server.toml", "w") as f:
        f.write(SERVER_CONFIG)
    env = {**os.environ, "AGENT_ENV_CONFIG": "/root/server.toml", "XDG_STATE_HOME": "/root/state",
           "AGENT_ENV_MODAL_APP_NAME": f"{NAME}-envs", "BUNDLE": "/root/bundles/desk-v4-train",
           "MAX_CONCURRENT_ENVS": "48", "HOST": "127.0.0.1", "PORT": "8000", "PYTHONUNBUFFERED": "1"}
    server = subprocess.Popen(["/root/envbox/bin/python", f"{KIT}/serve.py"], env=env, stdout=open(log, "a"),
                              stderr=subprocess.STDOUT)
    while True:
        if server.poll() is not None:
            raise RuntimeError(f"serve.py exited with {server.returncode}; see {log}")
        try:
            urllib.request.urlopen(f"{URL}/list_environments", timeout=5)
            return server
        except OSError:
            time.sleep(5)


@app.function(cpu=4.0, memory=16 * 1024, timeout=3600, secrets=[keys])
def check() -> dict:
    """No GPU: the server up, the factory built (one probe episode, the env image built on its first deploy), the tools
    as TRL collects and Qwen3-4B's template renders them, and one more episode's deploy."""
    started = time.monotonic()
    server = serve("/root/server.log")
    out = {"server_start_s": round(time.monotonic() - started)}
    try:
        env = AgentEnv(URL, split="train", tool_timeout=300, reset_timeout=1800)
        t = time.monotonic()
        environment = env.factory()
        out["factory_s"] = round(time.monotonic() - t)
        tools = [getattr(environment, name) for name, _ in inspect.getmembers(type(environment), inspect.isfunction)
                 if name not in ("reset", "get_reward") and not name.startswith("_")]
        out["tools"] = {getattr(tool, "__name__", "?"): type(tool).__name__ for tool in tools}
        row = env.dataset[0]
        text = AutoTokenizer.from_pretrained("/root/models/Qwen3-4B").apply_chat_template(
            row["prompt"], tools=tools, tokenize=False, add_generation_prompt=True, enable_thinking=True)
        out["submit_dam_offers"] = next(line for line in text.splitlines() if '"submit_dam_offers"' in line)
        t = time.monotonic()
        environment.reset(**row)
        out["first_call"] = environment.get_asset_status()[:120]
        out["deploy_s"] = round(time.monotonic() - t)
        t = time.monotonic()
        out["idle_day_reward"] = environment.get_reward()
        out["idle_day_s"] = round(time.monotonic() - t)
        env.close()
    finally:
        server.terminate()
        server.wait(timeout=600)
    out["total_s"] = round(time.monotonic() - started)
    out["server_log_tail"] = open("/root/server.log").read()[-1500:]
    return out


@app.function(gpu="H100", cpu=8.0, memory=96 * 1024, timeout=HOURS * 3600, volumes={"/out": volume}, secrets=[keys])
def train(run: str, settings: dict[str, str]) -> None:
    """train.py with pilot config 2 at CONTEXT 40,960, the server beside it; the volume committed every minute."""
    os.makedirs(f"/out/{run}", exist_ok=True)
    server = serve(f"/out/{run}/server.log")
    env = {**os.environ, "ENV_URL": URL, "MODEL": "/root/models/Qwen3-4B", "OUT": f"/out/{run}", "MAX_STEPS": "10",
           "CONTEXT": "40960", "FORMAT_PENALTY": "0.1", "VLLM_MODE": "colocate", "PYTHONUNBUFFERED": "1",
           "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True", **settings}
    with open(f"/out/{run}/train.log", "a") as log:
        trainer = subprocess.Popen([sys.executable, f"{KIT}/train.py"], env=env, stdout=log, stderr=subprocess.STDOUT)
        while True:
            try:
                trainer.wait(timeout=60)
                break
            except subprocess.TimeoutExpired:
                volume.commit()
    server.terminate()
    server.wait(timeout=900)
    volume.commit()
    if trainer.returncode:
        raise RuntimeError(f"train.py exited with {trainer.returncode}")


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        with modal.enable_output(), app.run():
            print(json.dumps(check.remote(), indent=1))
    elif sys.argv[1:] == ["train"]:
        with modal.enable_output(), app.run(detach=True):
            call = train.spawn(os.environ.get("RUN", "pilot2-h100"), {key: os.environ[key] for key in SETTINGS
                                                                       if key in os.environ})
            print(f"spawned {call.object_id} on plugin {COMMIT[:7]}; outputs in the {NAME} volume")
    else:
        sys.exit(__doc__)
