#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; B=$G/models/Qwen3-4B; S=$G/models/qwen3-4b-sft10k-rule; R=$G/runs/reg4b2
mkdir -p $R
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 30 > $R/gpu_sft.csv &
NV=$!
date -u
MODEL=$B OUT=$S N_SFT=10000 EPOCHS=1 RATIONALE=rule STRATIFY=start MAX_TOKENS=448 MICRO=4 SEED=0 python code/sft.py; echo SFT_EXIT $?
kill $NV
date -u
MODEL=$S OUT=$R/eval BASE_TRAINED=sft SETS="sft:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_SFT_EXIT $?
date -u
echo PHASEA_DONE
