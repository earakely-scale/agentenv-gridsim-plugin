"""Qwen3-4B for the desk bench on a Modal GPU: vLLM 0.29.0 serving Qwen/Qwen3-4B at the revision the g5 run host
serves, with that host's flags (bf16, 32k context, hermes tool calls, prefix caching, thinking off unless a request
turns it on) plus the Qwen3 reasoning parser, which hands OpenCode the thinking as reasoning_content. The weights are
baked into the image; the API key comes from the Modal secret QWEN_SECRET names, as VLLM_API_KEY.

    QWEN_SECRET=gridsim-qwen-key modal deploy bench/qwen/vllm_modal.py
    modal app stop gridsim-qwen3-4b
"""

import os
import subprocess

import modal

MODEL = "Qwen/Qwen3-4B"
REVISION = "1cfa9a7208912126459214e8b04321603b3df60c"
WEIGHTS = "/models/qwen3-4b"
SERVE = ["vllm", "serve", WEIGHTS, "--served-model-name", "qwen3-4b", "--host", "0.0.0.0", "--port", "8000",
         "--max-model-len", "32768", "--gpu-memory-utilization", "0.88", "--dtype", "bfloat16",
         "--enable-auto-tool-choice", "--tool-call-parser", "hermes",
         "--default-chat-template-kwargs", '{"enable_thinking": false}', "--enable-prefix-caching",
         "--reasoning-parser", "qwen3"]


def download() -> None:
    from huggingface_hub import snapshot_download
    snapshot_download(MODEL, revision=REVISION, local_dir=WEIGHTS)


image = (modal.Image.debian_slim(python_version="3.12")
         .pip_install("vllm==0.29.0", "huggingface_hub[hf_transfer]")
         .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
         .run_function(download))
app = modal.App("gridsim-qwen3-4b")


@app.function(image=image, gpu=os.environ.get("QWEN_GPU", "L4"), timeout=24 * 3600, scaledown_window=300,
              max_containers=1, secrets=[modal.Secret.from_name(os.environ.get("QWEN_SECRET", "gridsim-qwen-key"))])
@modal.concurrent(max_inputs=32)
@modal.web_server(port=8000, startup_timeout=900)
def serve() -> None:
    subprocess.Popen(SERVE + ["--api-key", os.environ["VLLM_API_KEY"]])
