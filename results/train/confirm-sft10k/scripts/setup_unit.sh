#!/bin/bash
set -euxo pipefail
export HOME=/root
G=/home/ubuntu/gs
mkdir -p $G/logs $G/models $G/runs $G/code
cd $G
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
[ -d plugin/.git ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin.git plugin
git -C plugin log --oneline -1
cp plugin/results/train/4b-v2/scripts/{evaluate.py,pathb.py} code/
[ -d .venv ] || uv venv --python 3.12 .venv
. .venv/bin/activate
uv pip install -r plugin/results/train/pip_freeze.txt
uv pip install --no-deps -e ./plugin
uv pip install "huggingface_hub[hf_transfer]"
python -c "import torch, trl, vllm, transformers, peft; print('torch', torch.__version__, torch.version.cuda, torch.cuda.is_available()); print('trl', trl.__version__, 'vllm', vllm.__version__, 'transformers', transformers.__version__, 'peft', peft.__version__)"
python -c "
import hashlib, json
from importlib.resources import files
for p in ('eval', 'eval-iid', 'rtcb'):
    d = files('gridsim_core') / 'data' / f'ercot-dam-v1-{p}'
    m = json.loads((d / 'manifest.json').read_text())
    print(p, m['count'], m['tasks_sha256'])
" || true
HF_HUB_ENABLE_HF_TRANSFER=1 hf download Qwen/Qwen3-4B --revision 1cfa9a7208912126459214e8b04321603b3df60c --local-dir $G/models/Qwen3-4B
curl -fsS -o $G/adapters.tgz "$ADAPTER_URL"
rm -rf $G/adapter && tar -C $G -xzf $G/adapters.tgz && ls -la $G/adapter/sft-lora $G/adapter/grpo-lora
sha256sum $G/adapters.tgz
python $G/code/merge.py $G/models/Qwen3-4B $G/adapter/sft-lora $G/models/qwen3-4b-sft10k-rule
ls -la $G/models/qwen3-4b-sft10k-rule
uv pip freeze > $G/logs/freeze.txt
echo SETUP_DONE
