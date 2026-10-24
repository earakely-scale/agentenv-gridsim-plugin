#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs
date -u
rm -rf $G/runs/grpo
MODEL=${MODEL:-$G/models/qwen3-1.7b-sft200} OUT=$G/runs/grpo LR=${LR:-2e-5} MAX_STEPS=${STEPS:-280} SAVE_STEPS=50 python code/train.py; echo GRPO_EXIT $?
date -u
echo PHASE2_DONE
