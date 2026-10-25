#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft1500soc; R=$G/runs/smoke4b
rm -rf $R; mkdir -p $R
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 2 > $R/gpu.csv &
NV=$!
date -u
MODEL=$S OUT=$R SEED=0 LR=1e-5 LR_SCHED=cosine WARMUP=5 TEMP=1.1 CURRICULUM=mixed PROMPTS_PER_STEP=8 NUM_GEN=8 \
  MICRO=${MICRO:-4} MAX_STEPS=5 SAVE_STEPS=1000 MAX_COMPLETION=512 VLLM_UTIL=${VLLM_UTIL:-0.4} python code/train.py
echo SMOKE_EXIT $?
kill $NV
date -u
awk -F', ' '{gsub(/ MiB/,"",$2); if ($2+0 > m) m = $2+0} END {print "peak MiB", m}' $R/gpu.csv
echo SMOKE_DONE
