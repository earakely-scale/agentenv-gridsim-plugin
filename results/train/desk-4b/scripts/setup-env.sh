# The env server's install, as the user that runs it (setup-box.sh runs it as ubuntu): the plugin at PLUGIN_REF for the
# bundle writer, a venv with the framework's openenv extra, the desk-v4-train bundle in ~/bundles, and an isolated local
# agent-env profile (~/envbox.toml, state in ~/state). serve.py then serves it; its first start builds the env image.
set -euxo pipefail
cd "$HOME"
export PATH=$HOME/.local/bin:$PATH
FRAMEWORK=${FRAMEWORK:-0.9.1387}
REF=${PLUGIN_REF:-desk-train}
command -v uv || curl -LsSf https://astral.sh/uv/install.sh | sh
docker --version
[ -d plugin ] || git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
git -C plugin fetch -q origin
git -C plugin checkout -q --detach "origin/$REF" 2>/dev/null || git -C plugin checkout -q --detach "$REF"
[ -d envbox ] || uv venv -q -p 3.12 envbox
install_framework() {  # the pinned release, or its wheel from PyPI's JSON API while the simple index lags behind it
  for _ in 1 2 3; do
    VIRTUAL_ENV=$HOME/envbox uv pip install -q --refresh-package agentenv-framework -e ./plugin \
      "agentenv-framework[openenv]==$FRAMEWORK" && return 0
    sleep 30
  done
  url=$(curl -fsS "https://pypi.org/pypi/agentenv-framework/$FRAMEWORK/json" | python3 -c \
    'import json, sys; print(next(f["url"] for f in json.load(sys.stdin)["urls"] if f["filename"].endswith(".whl")))')
  VIRTUAL_ENV=$HOME/envbox uv pip install -q -e ./plugin "agentenv-framework[openenv] @ $url"
}
install_framework
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
rm -rf bundles/desk-v4-train
(cd plugin && ../envbox/bin/python scripts/desk_train.py bundle --out ../bundles/desk-v4-train)
envbox/bin/python -c "import importlib.metadata as m; print('env server: agentenv-framework', m.version('agentenv-framework'), 'protocol', m.version('agentenv-framework-protocol'))"
echo "plugin $(git -C plugin rev-parse --short HEAD)"
