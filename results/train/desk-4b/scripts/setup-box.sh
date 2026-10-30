# One GPU box for the pilot, the env server and the trainer together; run as root (e.g. through SSM). System prep, then
# setup-env.sh and setup.sh as BOX_USER (ubuntu), then the env server as the systemd unit desk-env on 127.0.0.1:8000,
# whose first start builds the env image, while setup.sh installs the trainer and downloads the model. Waits until
# both are done and the server answers. FRAMEWORK, PLUGIN_REF, MODEL_ID and MODEL_REV pass through.
# Docker gets 256 /24 address pools: every episode makes a network, and the default pools hold about 30.
set -euxo pipefail
T0=$(date +%s)
U=${BOX_USER:-ubuntu}
H=$(getent passwd "$U" | cut -d: -f6)
systemctl stop unattended-upgrades apt-daily.timer apt-daily-upgrade.timer 2>/dev/null || true
printf 'fs.inotify.max_user_instances=8192\nfs.inotify.max_user_watches=1048576\n' > /etc/sysctl.d/90-inotify.conf
sysctl -q -p /etc/sysctl.d/90-inotify.conf
usermod -aG docker "$U"
python3 - <<'PY'
import json, pathlib
p = pathlib.Path("/etc/docker/daemon.json")
d = json.loads(p.read_text()) if p.exists() and p.read_text().strip() else {}
d["default-address-pools"] = [{"base": "10.200.0.0/16", "size": 24}]
p.write_text(json.dumps(d, indent=1) + "\n")
PY
systemctl restart docker
nvidia-smi --query-gpu=index,name,memory.total,driver_version,compute_cap --format=csv
docker --version
REF=${PLUGIN_REF:-desk-train}
[ -d "$H/plugin" ] || sudo -iu "$U" git clone -q https://github.com/earakely-scale/agentenv-gridsim-plugin plugin
sudo -iu "$U" git -C plugin fetch -q origin
sudo -iu "$U" git -C plugin checkout -q --detach "origin/$REF" 2>/dev/null || sudo -iu "$U" git -C plugin checkout -q --detach "$REF"
ARGS=(env FRAMEWORK="${FRAMEWORK:-0.9.1387}" PLUGIN_REF="$REF" MODEL_ID="${MODEL_ID:-Qwen/Qwen3-4B}"
      MODEL_REV="${MODEL_REV:-1cfa9a7208912126459214e8b04321603b3df60c}")
sudo -iu "$U" "${ARGS[@]}" bash "$H/plugin/results/train/desk-4b/scripts/setup.sh" > "$H/setup-trainer.log" 2>&1 &
TRAINER=$!
sudo -iu "$U" "${ARGS[@]}" bash "$H/plugin/results/train/desk-4b/scripts/setup-env.sh"
sed "s#@HOME@#$H#g; s#@USER@#$U#g" "$H/plugin/results/train/desk-4b/scripts/desk-env.service" \
  > /etc/systemd/system/desk-env.service
systemctl daemon-reload
systemctl enable -q desk-env
systemctl restart desk-env
for _ in $(seq 1 180); do
  curl -sf -m 5 http://127.0.0.1:8000/list_environments > /dev/null && break
  systemctl is-active -q desk-env || { tail -30 "$H/desk-env.log"; exit 1; }
  sleep 10
done
curl -sf -m 5 http://127.0.0.1:8000/list_environments
wait "$TRAINER" || { tail -30 "$H/setup-trainer.log"; exit 1; }
grep -E "^(trainer|gpu):" "$H/setup-trainer.log"
echo "setup took $(( $(date +%s) - T0 ))s"
