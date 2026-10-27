#!/bin/bash
set -euxo pipefail
export HOME=/root
G=/home/ubuntu/gs7
mkdir -p $G/logs $G/models $G/runs $G/code $G/adapters $G/data
cd $G
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
[ -d plugin/.git ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin.git plugin
git -C plugin log --oneline -1
[ -d .venv ] || uv venv --python 3.12 .venv
. .venv/bin/activate
uv pip install -r plugin/results/train/pip_freeze.txt
uv pip install --no-deps -e ./plugin
uv pip install "huggingface_hub[hf_transfer]"
python -c "import torch, vllm, transformers, peft; print('torch', torch.__version__, torch.cuda.is_available(), 'vllm', vllm.__version__, 'transformers', transformers.__version__, 'peft', peft.__version__)"
HF_HUB_ENABLE_HF_TRANSFER=1 hf download Qwen/Qwen3-4B --revision 1cfa9a7208912126459214e8b04321603b3df60c --local-dir $G/models/Qwen3-4B
u2=$(sed -n 1p code/.urls); u3=$(sed -n 2p code/.urls)
curl -fsS -o adapters/reg2.tgz "$u2"; curl -fsS -o adapters/reg3.tgz "$u3"; rm -f code/.urls
sha256sum adapters/reg2.tgz adapters/reg3.tgz | tee adapters/sha256.txt
mkdir -p adapters/reg2 adapters/reg3; tar xzf adapters/reg2.tgz -C adapters/reg2; tar xzf adapters/reg3.tgz -C adapters/reg3
find adapters/reg2 adapters/reg3 -maxdepth 3 -type d
M=plugin/results/train/4b-dpa/scripts/merge.py
CUDA_VISIBLE_DEVICES=0 python $M $G/models/Qwen3-4B adapters/reg2/adapter/sft-lora $G/models/sft10k
CUDA_VISIBLE_DEVICES=0 python $M $G/models/sft10k adapters/reg3/adapter/dpa-lora $G/models/run3
uv pip freeze > $G/logs/freeze.txt
nproc; free -g | head -2; df -h / | tail -1
echo SETUP_DONE
