# The env box (CPU, Docker): the plugin at this kit's commit for the bundle writer, a venv with the framework's openenv
# extra, the desk-v4-train bundle written into ~/bundles, and an isolated local agent-env profile. serve.py then serves
# it; the first rollouts build the env image from the bundle's envs/ folder.
set -euxo pipefail
sysctl -w fs.inotify.max_user_instances=8192 fs.inotify.max_user_watches=1048576
docker --version
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH=$HOME/.local/bin:$PATH
[ -d plugin ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
git -C plugin fetch -q origin && git -C plugin checkout -q "${PLUGIN_REF:-desk-train}"
[ -d envbox ] || uv venv -q -p 3.12 envbox
VIRTUAL_ENV=$HOME/envbox uv pip install -q -e ./plugin "agentenv-framework[openenv]==${FRAMEWORK:-0.9.1386}"
mkdir -p state
cat > envbox.toml <<'TOML'
[stores]
document = "local"
object   = "local"
image    = "local"
secret   = "local"

[sandbox]
default       = "local"
agent_default = "local"
TOML
(cd plugin && ../envbox/bin/python scripts/desk_train.py bundle --out ../bundles/desk-v4-train)
ls bundles/desk-v4-train/evals; ls bundles/desk-v4-train/tasks | wc -l
