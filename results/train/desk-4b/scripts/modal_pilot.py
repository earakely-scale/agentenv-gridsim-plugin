"""Pilot config 2 on one Modal H100: train.py with the desk-v4-train bundle served in the same container by serve.py,
every episode a Modal sandbox whose env image Modal builds from the bundle's build context (desk-v4-freeze plus both
packs). MODEL picks the model (a Hub id at a pinned revision; Qwen3.5-9B by default) and with it the served name the
OpenCode-aligned rows carry, the context and the trainer's dtype. Modal keys come from AWS Secrets Manager in this
process (profile agent-environments-admin) and reach the container as a secret that lives as long as the run; nothing
prints or stores them. Outputs (metrics, rollouts, completions, endings, checkpoints, the adapter, the logs) land in the
gridsim-desk-train volume under RUN.

    python modal_pilot.py check                          # no GPU: images, one episode as a sandbox, the rendered tools
    RUN=base-9b python modal_pilot.py eval               # the base model on the 36 val days, detached
    RUN=pilot2-9b python modal_pilot.py train            # the 10-step pilot, detached; MAX_STEPS, EVAL_LIMIT, ... pass
"""

import glob
import inspect
import json
import os
import re
import statistics
import subprocess
import sys
import time
import urllib.request

import modal

NAME = "gridsim-desk-train"
REF = os.environ.get("PLUGIN_REF", "desk-train-9b")
FRAMEWORK = "0.9.1387"
PLUGIN = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
KIT = "/root/plugin/results/train/desk-4b/scripts"
URL = "http://127.0.0.1:8000"
HOURS = 10
MODELS = {
    "Qwen/Qwen3.5-9B": {"revision": "c202236235762e1c871ad0ccb60c8ee5ba337b9a", "served": "qwen3.5-9b",
                        "context": "28672", "dtype": "bfloat16"},
    "Qwen/Qwen3-4B": {"revision": "1cfa9a7208912126459214e8b04321603b3df60c", "served": "qwen3-4b",
                      "context": "40960", "dtype": "float32"},
}
MODEL = os.environ.get("MODEL", "Qwen/Qwen3.5-9B")
SPEC = MODELS[MODEL]
MODEL_DIR = f"/root/models/{MODEL.split('/')[-1]}"
SETTINGS = ("MAX_STEPS", "EVAL_STEPS", "EVAL_ON_START", "EVAL_LIMIT", "EVAL_BATCH", "SAVE_STEPS", "LR", "VLLM_MEM",
            "VLLM_SLEEP", "FORMAT_PENALTY", "CONTEXT", "EVAL_SPLIT", "MODEL_DTYPE", "SERVED_MODEL")
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
                    "transformers==5.22.*", "flash-linear-attention")
    .run_commands(f"hf download {MODEL} --revision {SPEC['revision']} --local-dir {MODEL_DIR}")
    .run_commands(
        f"git clone -q {PLUGIN} /root/plugin && git -C /root/plugin checkout -q --detach {COMMIT}",
        "python -m venv /root/envbox && /root/envbox/bin/pip install -q uv",
        f"/root/envbox/bin/uv pip install -q --python /root/envbox/bin/python -e /root/plugin "
        f"'agentenv-framework[openenv]=={FRAMEWORK}'",
        "cd /root/plugin && /root/envbox/bin/python scripts/desk_train.py bundle --out /root/bundles/desk-v4-train",
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


def endings(out: str) -> dict:
    """How each logged rollout ended, with its mean C: the model's own end_turn through the day, a parsed tool call TRL
    did not run (the length or iteration cap), an unparseable tool call, or a reply without one."""
    rollouts = [json.loads(line) for line in open(f"{out}/rollouts.jsonl")]
    summary = {}
    for path in glob.glob(f"{out}/completions-*-*.jsonl"):
        phase, step = re.findall(r"completions-(\w+)-(\d+)\.jsonl", path)[0]
        logged = [r for r in rollouts if r["phase"] == phase and r["step"] == int(step)]
        completions = [json.loads(line) for line in open(path)]
        size = min(len(logged), len(completions))
        kinds: dict[str, list[float]] = {}
        for done, rollout in zip(completions[len(completions) - size:], logged[len(logged) - size:], strict=True):
            last = done["completion"][-1]
            text = str(last.get("content") or "")
            kind = ("full_day" if rollout["finished_by_model"] else "cap" if last.get("tool_calls")
                    else "malformed" if "<tool_call>" in text else "plain" if text.strip() else "empty")
            kinds.setdefault(kind, []).append(rollout["reward"] if rollout["reward"] is not None else float("nan"))
        summary[f"{phase}{step}"] = {kind: [len(c), round(statistics.fmean(c), 4)] for kind, c in sorted(kinds.items())}
    return summary


@app.function(cpu=4.0, memory=16 * 1024, timeout=3600, secrets=[keys])
def check() -> dict:
    """No GPU: the server up, the factory built (one probe episode, the env image built on its first deploy), the tools
    as TRL collects them and the model's template renders them, and one more episode's deploy."""
    started = time.monotonic()
    server = serve("/root/server.log")
    out = {"model": MODEL, "server_start_s": round(time.monotonic() - started)}
    try:
        env = AgentEnv(URL, split="train", tool_timeout=300, reset_timeout=1800)
        t = time.monotonic()
        environment = env.factory()
        out["factory_s"] = round(time.monotonic() - t)
        tools = [getattr(environment, name) for name, _ in inspect.getmembers(type(environment), inspect.isfunction)
                 if name not in ("reset", "get_reward") and not name.startswith("_")]
        out["tools"] = {getattr(tool, "__name__", "?"): type(tool).__name__ for tool in tools}
        row = env.dataset[0]
        tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
        text = tokenizer.apply_chat_template(row["prompt"], tools=tools, tokenize=False, add_generation_prompt=True,
                                             enable_thinking=True)
        out["prompt_tokens"] = len(tokenizer(text, add_special_tokens=False)["input_ids"])
        out["submit_dam_offers"] = next(line for line in text.splitlines() if '"submit_dam_offers"' in line)
        out["generation_prompt"] = text[-40:]
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
    out["server_log_tail"] = open("/root/server.log").read()[-1000:]
    return out


@app.function(gpu="H100", cpu=8.0, memory=96 * 1024, timeout=HOURS * 3600, volumes={"/out": volume}, secrets=[keys])
def run(name: str, settings: dict[str, str]) -> None:
    """train.py with pilot config 2 for MODEL, the server beside it; the volume committed every minute, and the
    endings of every logged batch written at the end. MAX_STEPS=0 evaluates only."""
    out = f"/out/{name}"
    os.makedirs(out, exist_ok=True)
    server = serve(f"{out}/server.log")
    env = {**os.environ, "ENV_URL": URL, "MODEL": MODEL_DIR, "OUT": out, "MAX_STEPS": "10", "CONTEXT": SPEC["context"],
           "MODEL_DTYPE": SPEC["dtype"], "SERVED_MODEL": SPEC["served"], "FORMAT_PENALTY": "0.1",
           "VLLM_MODE": "colocate", "PYTHONUNBUFFERED": "1", "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
           **settings}
    with open(f"{out}/train.log", "a") as log:
        trainer = subprocess.Popen([sys.executable, f"{KIT}/train.py"], env=env, stdout=log, stderr=subprocess.STDOUT)
        while True:
            try:
                trainer.wait(timeout=60)
                break
            except subprocess.TimeoutExpired:
                volume.commit()
    server.terminate()
    server.wait(timeout=900)
    if os.path.exists(f"{out}/rollouts.jsonl"):
        with open(f"{out}/endings.json", "w") as f:
            json.dump(endings(out), f, indent=1)
    volume.commit()
    if trainer.returncode:
        raise RuntimeError(f"train.py exited with {trainer.returncode}")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    settings = {key: os.environ[key] for key in SETTINGS if key in os.environ}
    if mode == "check":
        with modal.enable_output(), app.run():
            print(json.dumps(check.remote(), indent=1))
    elif mode in ("eval", "train"):
        settings = ({"MAX_STEPS": "0"} if mode == "eval" else {}) | settings
        with modal.enable_output(), app.run(detach=True):
            call = run.spawn(os.environ.get("RUN", f"{mode}-{SPEC['served']}"), settings)
            print(f"spawned {call.object_id}: {mode} of {MODEL} on plugin {COMMIT[:7]}, outputs in the {NAME} volume")
    else:
        sys.exit(__doc__)
