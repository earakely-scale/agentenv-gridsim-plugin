# The trainer's install, as the user that runs it (setup-box.sh runs it as ubuntu): the framework's trl extra with TRL,
# PEFT and vLLM (and flash-linear-attention for Qwen3.5's linear-attention layers), the model at its pinned revision in
# ~/models/<name> (MODEL_ID, MODEL_REV; Qwen3-4B at the benchmark's revision by default; the trainer and vLLM load the
# same files), and the plugin for this kit. No Docker and no GridSim install: the envs run in the env server.
set -euxo pipefail
cd "$HOME"
export PATH=$HOME/.local/bin:$PATH
FRAMEWORK=${FRAMEWORK:-0.9.1387}
REF=${PLUGIN_REF:-desk-train}
MODEL_ID=${MODEL_ID:-Qwen/Qwen3-4B}
MODEL_REV=${MODEL_REV:-1cfa9a7208912126459214e8b04321603b3df60c}
nvidia-smi --query-gpu=index,name,memory.total,driver_version,compute_cap --format=csv
DRIVER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)
[ "${DRIVER%%.*}" -ge 580 ] || { echo "NVIDIA driver $DRIVER: torch's CUDA 13 build needs 580 or newer"; exit 1; }
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
[ -d plugin ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
git -C plugin fetch -q origin
git -C plugin checkout -q --detach "origin/$REF" 2>/dev/null || git -C plugin checkout -q --detach "$REF"
[ -f "models/${MODEL_ID##*/}/config.json" ] || uvx -q --from "huggingface-hub==1.33.0" hf download "$MODEL_ID" \
  --revision "$MODEL_REV" --local-dir "models/${MODEL_ID##*/}" > download.log 2>&1 &
DOWNLOAD=$!
[ -d trainer ] || uv venv -q -p 3.12 trainer
STACK=("trl[vllm,peft]==1.16.*" "vllm==0.29.*" "flash-linear-attention" ninja)
install_framework() {  # the pinned release, or its wheel from PyPI's JSON API while the simple index lags behind it
  for _ in 1 2 3; do
    VIRTUAL_ENV=$HOME/trainer uv pip install --refresh-package agentenv-framework \
      "agentenv-framework[trl]==$FRAMEWORK" "${STACK[@]}" > install.log 2>&1 && return 0
    sleep 30
  done
  url=$(curl -fsS "https://pypi.org/pypi/agentenv-framework/$FRAMEWORK/json" | python3 -c \
    'import json, sys; print(next(f["url"] for f in json.load(sys.stdin)["urls"] if f["filename"].endswith(".whl")))')
  VIRTUAL_ENV=$HOME/trainer uv pip install "agentenv-framework[trl] @ $url" "${STACK[@]}" > install.log 2>&1
}
install_framework
VIRTUAL_ENV=$HOME/trainer uv pip freeze > pip_freeze.txt
wait "$DOWNLOAD" || { tail -5 download.log; exit 1; }
du -sh "models/${MODEL_ID##*/}"
trainer/bin/python - <<'PY'
import importlib.metadata as m

import torch
import transformers
import trl
import vllm

cap = torch.cuda.get_device_capability(0)
arch = f"sm_{cap[0]}{cap[1]}"
print("trainer: trl", trl.__version__, "vllm", vllm.__version__, "transformers", transformers.__version__, "torch",
      torch.__version__, "cuda", torch.version.cuda, "agentenv-framework", m.version("agentenv-framework"))
print("gpu:", torch.cuda.device_count(), "x", torch.cuda.get_device_name(0), arch, "torch archs",
      torch.cuda.get_arch_list(), "bf16 matmul on it:", float((torch.ones(64, 64, device="cuda",
                                                                       dtype=torch.bfloat16) @ torch.ones(64, 64,
                                                                       device="cuda", dtype=torch.bfloat16))[0, 0]))
PY
