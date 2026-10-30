# The main run (pilot config 2 at 96k context) on one GPU box, as root, the plugin cloned in /home/ubuntu/plugin and
# setup-box.sh done (setup-box.done). `run_main.sh sanity`: the trainer's peak at 96k with the activation offload
# (fused_probe.py), then one val day through train.py at the full config, its turns capped at 40. `run_main.sh main`:
# the base eval of the 36 val days, up to 20 steps of 32 rollouts with evals at steps 10 and 20, a checkpoint every
# step (the latest and steps 10 and 20 kept), the final eval and the adapter, in /home/ubuntu/main; a main/ holding a
# checkpoint resumes from it. ROLLOUTS, EVAL_STEPS and EVAL_ON_START override the run's 32, 10 and 1. vLLM (colocated, asleep while the trainer optimises) gets the GPU less 23.5 GiB for the
# trainer. MAX_HOURS is the box's lifetime from boot: training ends after the last step that leaves RESERVE_MIN
# (default 120) before boot + MAX_HOURS - 15 min for the final eval and the copies. One line per stage goes to
# /home/ubuntu/run_main.progress.
set -uo pipefail
STAGE=${1:?sanity or main}
H=/home/ubuntu
KIT=$H/plugin/results/train/desk-4b/scripts
: "${MAX_HOURS:?the box lifetime in hours}"
BOOT=$(date -d "$(uptime -s)" +%s)
DEADLINE=$(awk -v boot="$BOOT" -v hours="$MAX_HOURS" 'BEGIN {printf "%d", boot + hours * 3600 - 15 * 60}')
TOTAL_MIB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)
VLLM_MEM=$(awk -v mib="$TOTAL_MIB" 'BEGIN {printf "%.3f", (mib / 1024 - 23.5) / (mib / 1024)}')
SETTINGS=(HOME=$H MODEL=models/Qwen3.5-9B MODEL_DTYPE=bfloat16 SERVED_MODEL=qwen3.5-9b CONTEXT=98304
          OFFLOAD_ACTIVATIONS=1 THINK_BUDGET=2048 VLLM_MEM=$VLLM_MEM EVAL_BATCH=36 FORMAT_PENALTY=0.1
          PATH=$H/.local/bin:/usr/local/bin:/usr/bin:/bin)
progress() { echo "$(date -u +%FT%TZ) $*" | tee -a $H/run_main.progress; }
run() { sudo -u ubuntu env "${SETTINGS[@]}" "$@" bash $KIT/run.sh; }
[ -f $H/setup-box.done ] || { progress "SETUP NOT DONE"; exit 1; }

if [ "$STAGE" = sanity ]; then
  progress "sanity on $(nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader), vLLM at $VLLM_MEM"
  sudo -u ubuntu env HOME=$H OFFLOAD=1 PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True $H/trainer/bin/python \
    $KIT/fused_probe.py $H/models/Qwen3.5-9B $H/probe-main.json 98304 > $H/probe-main.log 2>&1
  progress "probe at 96k with offload: $(grep -o "{'tokens'.*" $H/probe-main.log | tail -1)"
  run OUT=sanity-main MAX_STEPS=0 EVAL_LIMIT=1 MAX_TOOL_ITERATIONS=40 > $H/sanity-main.log 2>&1 \
    || { progress "SANITY FAILED: $(tail -3 $H/sanity-main.log)"; exit 1; }
  progress "vLLM: $(grep -oE 'Available KV cache memory: [0-9.]+ GiB|Maximum concurrency for [0-9,]+ tokens per request: [0-9.]+x' $H/sanity-main.log | head -2 | tr '\n' ' ')"
  progress "sanity done: $(grep -o 'eval step 0: .*' $H/sanity-main.log)"
  exit 0
fi

STOP_AT=$((DEADLINE - ${RESERVE_MIN:-120} * 60))
LAST=$(ls -d $H/main/checkpoint-* 2>/dev/null | sed 's/.*-//' | sort -n | tail -1)
progress "main: up to 20 steps ending by $(date -u -d @$STOP_AT +%H:%M) UTC, deadline $(date -u -d @"$DEADLINE" +%H:%M) UTC, vLLM at $VLLM_MEM${LAST:+, resuming after step $LAST}"
progress "main settings: ROLLOUTS ${ROLLOUTS:-32}, EVAL_STEPS ${EVAL_STEPS:-10}, EVAL_ON_START ${EVAL_ON_START:-1}"
run OUT=main MAX_STEPS=20 EVAL_STEPS=${EVAL_STEPS:-10} EVAL_ON_START=${EVAL_ON_START:-1} ROLLOUTS=${ROLLOUTS:-32} \
  SAVE_STEPS=1 KEEP_CHECKPOINTS=10,20 MAX_TOOL_ITERATIONS=200 STOP_AT=$STOP_AT >> $H/main.log 2>&1 \
  || progress "MAIN FAILED: $(tail -3 $H/main.log)"
progress "main done: $(grep -o '[a-z]* step [0-9]*: .*' $H/main.log | tail -3 | tr '\n' ' ')"
