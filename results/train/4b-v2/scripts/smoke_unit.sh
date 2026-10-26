#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft10k-rule; R=$G/runs/smoke4b2
rm -rf $R; mkdir -p $R
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 2 > $R/gpu.csv &
NV=$!
date -u
MODEL=$S OUT=$R SEED=0 LR=1e-5 LR_SCHED=cosine WARMUP=5 TEMP=1.1 CURRICULUM=adaptive PROMPTS_PER_STEP=8 NUM_GEN=8 \
  CANDIDATES=16 REPLAY_P=0.5 VISIT_CAP=4 MICRO=${MICRO:-4} MAX_STEPS=5 SAVE_STEPS=1000 MAX_COMPLETION=512 VLLM_UTIL=${VLLM_UTIL:-0.4} python code/train.py
echo SMOKE_EXIT $?
kill $NV
date -u
awk -F', ' '{gsub(/ MiB/,"",$2); if ($2+0 > m) m = $2+0} END {print "peak MiB", m}' $R/gpu.csv
cp $R/train_log.jsonl $G/runs/reg4b2/smoke_train_log.jsonl
echo SMOKE_DONE
