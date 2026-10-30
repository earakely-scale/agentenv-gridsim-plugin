# Qwen3.5-9B on one GPU box, as root, the plugin cloned in /home/ubuntu/plugin: setup (setup-box.sh with the 9B; the
# model downloads while the env image builds), a sanity eval of one val day (generation, the LoRA weight sync, one
# episode and its reward), then pilot config 2: the base eval of the 36 val days at step 0, up to 10 steps, the final
# eval. run.sh picks the mode from the GPU count: one GPU (a p5.4xlarge's H100) colocates vLLM with the trainer, vLLM
# asleep while the trainer optimises; more (a p5.48xlarge's H100s, a p4de.24xlarge's A100s) run vLLM data parallel on
# GPUs 1..N-1 and the trainer on GPU 0. MAX_HOURS is the box's lifetime from boot; training ends after the last step
# that leaves 25 min before boot + MAX_HOURS - 15 min for the final eval and the copies. In server mode the vLLM server
# restarts between the sanity and the pilot, so the pilot's trainer opens the weight-transfer group with a fresh
# server. One line per stage goes to /home/ubuntu/run_9b.progress.
set -uo pipefail
H=/home/ubuntu
KIT=$H/plugin/results/train/desk-4b/scripts
BOOT=$(date -d "$(uptime -s)" +%s)
: "${MAX_HOURS:?the box lifetime in hours}"
DEADLINE=$(awk -v boot="$BOOT" -v hours="$MAX_HOURS" 'BEGIN {printf "%d", boot + hours * 3600 - 15 * 60}')
export MODEL_ID=Qwen/Qwen3.5-9B MODEL_REV=c202236235762e1c871ad0ccb60c8ee5ba337b9a PLUGIN_REF=${PLUGIN_REF:-desk-train-9b}
SETTINGS=(HOME=$H MODEL=models/Qwen3.5-9B MODEL_DTYPE=bfloat16 SERVED_MODEL=qwen3.5-9b CONTEXT=${CONTEXT:-32768}
          EVAL_BATCH=36 VLLM_PREFIX_CACHING=${VLLM_PREFIX_CACHING:-True}
          PATH=$H/.local/bin:/usr/local/bin:/usr/bin:/bin)
progress() { echo "$(date -u +%FT%TZ) $*" | tee -a $H/run_9b.progress; }
run() { sudo -u ubuntu env "${SETTINGS[@]}" "$@" bash $KIT/run.sh; }

progress "setup on $(nvidia-smi -L | wc -l) GPU(s), MAX_HOURS $MAX_HOURS, deadline $(date -u -d @"$DEADLINE" +%H:%M) UTC"
bash $KIT/setup-box.sh > $H/setup-box.log 2>&1 || { progress "SETUP FAILED: $(tail -3 $H/setup-box.log)"; exit 1; }
progress "setup done: $(grep -E '^(trainer|gpu):|setup took' $H/setup-box.log | tr '\n' ' ')"

progress "sanity: one val day, generation and the weight sync"
run OUT=sanity MAX_STEPS=0 EVAL_LIMIT=1 > $H/sanity.log 2>&1 || { progress "SANITY FAILED: $(tail -3 $H/sanity.log)"; exit 1; }
progress "sanity done: $(grep -o 'eval step 0: .*' $H/sanity.log)"
pkill -f "vllm-serve"; pkill -f "vllm.entrypoints"
for _ in $(seq 1 60); do
  nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | awk '$1 > 2000 {busy = 1} END {exit !busy}' || break
  sleep 5
done

STOP_AT=$((DEADLINE - 25 * 60))
progress "pilot: base eval, up to 10 steps ending by $(date -u -d @$STOP_AT +%H:%M) UTC, final eval"
run OUT=pilot MAX_STEPS=10 STOP_AT=$STOP_AT > $H/pilot.log 2>&1 || progress "PILOT FAILED: $(tail -3 $H/pilot.log)"
progress "pilot done: $(grep -o '[a-z]* step [0-9]*: .*' $H/pilot.log | tail -3 | tr '\n' ' ')"
