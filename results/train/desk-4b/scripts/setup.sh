# The trainer box (one H100): the framework's trl extra with TRL, PEFT and vLLM, Qwen3-4B at the benchmark's revision
# in ~/models/Qwen3-4B (the trainer and its colocated vLLM load the same files), and this kit from the plugin repo. No
# Docker and no GridSim install: the envs run on the env box.
set -euxo pipefail
nvidia-smi --query-gpu=index,name,memory.total,driver_version --format=csv
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
[ -d trainer ] || uv venv -q -p 3.12 trainer
VIRTUAL_ENV=$HOME/trainer uv pip install "agentenv-framework[trl]==${FRAMEWORK:-0.9.1386}" "trl[vllm,peft]==1.16.*" \
  "vllm==0.29.*" > install.log 2>&1
VIRTUAL_ENV=$HOME/trainer uv pip freeze > pip_freeze.txt
trainer/bin/hf download Qwen/Qwen3-4B --revision 1cfa9a7208912126459214e8b04321603b3df60c --local-dir models/Qwen3-4B \
  > download.log 2>&1
[ -d plugin ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
git -C plugin fetch -q origin && git -C plugin checkout -q "${PLUGIN_REF:-desk-train}"
trainer/bin/python -c "import trl, vllm, transformers, torch, peft, agent_env.training.trl, importlib.metadata as m; print('trl', trl.__version__, 'vllm', vllm.__version__, 'transformers', transformers.__version__, 'torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'agentenv-framework', m.version('agentenv-framework'))"
