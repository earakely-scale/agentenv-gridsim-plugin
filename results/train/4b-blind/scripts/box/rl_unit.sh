#!/bin/bash
# rl_unit.sh: NAME=smoke|main, STEPS, STOP_AT (UTC). Rollout worker and trainer share the one GPU.
set -x
. /home/ubuntu/gs7/code/env.sh
M=$R/sft/merged; D=$R/rl-$NAME
rm -rf $D/train $D/roll; mkdir -p $D
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 30 > $D/gpu.csv &
NV=$!
DL=0; [ -n "$STOP_AT" ] && DL=$(date -u -d "$STOP_AT" +%s)
date -u
MODEL=$M ROLL=$D/roll SEED=0 VLLM_UTIL=${VLLM_UTIL:-0.40} MAX_MODEL_LEN=4096 python $C/rollout.py > $D/rollout.log 2>&1 &
RO=$!
while [ ! -f $D/roll/READY ]; do kill -0 $RO 2>/dev/null || { echo "ROLLOUT_DIED"; exit 1; }; sleep 5; done
PYTORCH_CUDA_ALLOC_CONF=$TRAIN_ALLOC MODEL=$M OUT=$D/train ROLL=$D/roll RL_POOL=$G/data/sft_rows.jsonl.gz STEPS=$STEPS BATCH=32 LR=1e-5 WARMUP=5 BETA=0.04 \
  EPS=0.2 TEMP=1.0 MAX_COMPLETION=768 SAVE_EVERY=25 SEED=0 DEADLINE=$DL GUARD_CF=0.6 GUARD_VALID=0.9 GC=${GC:-1} \
  python $C/rl_blind.py
echo "TRAIN_EXIT $?"
touch $D/roll/STOP; wait $RO; echo "ROLLOUT_EXIT $?"
kill $NV; date -u
awk -F', ' '{gsub(/ MiB/,"",$2); if ($2+0 > m) m = $2+0} END {print "peak MiB", m}' $D/gpu.csv
touch $D/DONE; echo UNIT_DONE
