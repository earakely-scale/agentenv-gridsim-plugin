# The docs' steps on a fresh GPU box: install the framework's trl extra with TRL and vLLM, download the bundle from the
# Hub, and check the stack imports. No registry and no GridSim install: the bundle is served from its folder.
set -euxo pipefail
systemctl stop unattended-upgrades apt-daily.timer apt-daily-upgrade.timer || true
sysctl -w fs.inotify.max_user_instances=8192 fs.inotify.max_user_watches=1048576
nvidia-smi --query-gpu=index,name,memory.total,driver_version,compute_cap --format=csv
docker --version
usermod -aG docker ubuntu
sudo -iu ubuntu bash <<'EOS'
set -euxo pipefail
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
[ -d trainer ] || uv venv -q -p 3.12 trainer
VIRTUAL_ENV=$HOME/trainer uv pip install "agentenv-framework[trl]==${FRAMEWORK:-0.9.1380}" "trl[vllm,peft]==1.16.*" "vllm==0.29.*" > install.log 2>&1
VIRTUAL_ENV=$HOME/trainer uv pip freeze > pip_freeze.txt
trainer/bin/hf download earakely-scale/GridSimEnv-AgentEnv --repo-type dataset --include "bundles/gridsim-v1/*" --local-dir . > download.log 2>&1
ls bundles/gridsim-v1; ls bundles/gridsim-v1/tasks | wc -l; du -sh bundles/gridsim-v1
trainer/bin/python -c "import trl, vllm, transformers, torch, peft, agent_env.training.trl, importlib.metadata as m; print('trl', trl.__version__, 'vllm', vllm.__version__, 'transformers', transformers.__version__, 'torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'agentenv-framework', m.version('agentenv-framework'), 'openenv', m.version('openenv'))"
EOS
