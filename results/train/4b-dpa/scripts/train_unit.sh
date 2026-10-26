#!/bin/bash
# Run 3 training: rollout worker on GPU 0, trainer on GPUs 1-2 (torchrun). NAME=smoke|main, STEPS, STOP_AT (UTC).
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft10k-rule; C=$G/code; R=$G/runs/$NAME
rm -rf $R/train $R/roll $R/TRAIN_DONE; mkdir -p $R
nvidia-smi --query-gpu=timestamp,index,memory.used,utilization.gpu --format=csv,noheader -l ${GPU_EVERY:-30} > $R/gpu_train.csv &
NV=$!
DL=0; [ -n "$STOP_AT" ] && DL=$(date -u -d "$STOP_AT" +%s)
date -u
CUDA_VISIBLE_DEVICES=0 MODEL=$S ROLL=$R/roll SEED=0 VLLM_UTIL=0.85 python $C/rollout.py > $R/rollout.log 2>&1 &
RO=$!
CUDA_VISIBLE_DEVICES=1,2 MODEL=$S OUT=$R/train ROLL=$R/roll STEPS=$STEPS BATCH=32 LR=1e-5 WARMUP=5 BETA=0.04 EPS=0.2 \
  TEMP=1.0 MAX_COMPLETION=512 SAVE_EVERY=25 SEED=0 DEADLINE=$DL GUARD_R=0.6 GUARD_VALID=0.9 \
  EXCLUDE=$G/plugin/results/train/4b-v2/sft_task_ids.json torchrun --standalone --nproc_per_node 2 $C/dpa_train.py
echo TRAIN_EXIT $?
touch $R/roll/STOP; wait $RO; echo ROLLOUT_EXIT $?
kill $NV
date -u
awk -F', ' '{gsub(/ MiB/,"",$3); if ($3+0 > m[$2]) m[$2] = $3+0} END {for (g in m) print "peak MiB gpu", g, m[g]}' $R/gpu_train.csv
touch $R/TRAIN_DONE
echo TRAIN_UNIT_DONE
