#!/bin/bash
set -euxo pipefail
export HOME=/root
G=/home/ubuntu/gs
mkdir -p $G/logs $G/models $G/runs $G/code
cd $G
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
uv --version
[ -d plugin/.git ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin.git plugin
git -C plugin log --oneline -1
[ -d .venv ] || uv venv --python 3.12 .venv
. .venv/bin/activate
uv pip install -r plugin/results/train/pip_freeze.txt
uv pip install --no-deps -e ./plugin
uv pip install "huggingface_hub[hf_transfer]"
python -c "import torch, trl, vllm, transformers, peft; print('torch', torch.__version__, torch.version.cuda, torch.cuda.is_available()); print('trl', trl.__version__, 'vllm', vllm.__version__, 'transformers', transformers.__version__, 'peft', peft.__version__)"
python -c "from gridsim_core.task import load_pack; print(len(load_pack('ercot-dam-v1-eval')), len(load_pack('ercot-dam-v1-train')))"
HF_HUB_ENABLE_HF_TRANSFER=1 hf download Qwen/Qwen3-4B --revision 1cfa9a7208912126459214e8b04321603b3df60c --local-dir $G/models/Qwen3-4B
ls -la $G/models/Qwen3-4B
uv pip freeze > $G/logs/freeze.txt
echo SETUP_DONE
