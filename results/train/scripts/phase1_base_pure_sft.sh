#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; B=$G/models/Qwen3-1.7B; S=$G/models/qwen3-1.7b-sft200
date -u
# 1. base eval, 200 eval-2025 tasks, sampled + greedy
MODEL=$B OUT=$G/runs/eval SETS="base:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_BASE_EXIT $?
date -u
# 2. pre-registered recipe as is (with the fallback format credit), short, as evidence of signal or none
rm -rf $G/runs/grpo_pure
MODEL=$B OUT=$G/runs/grpo_pure MAX_STEPS=${PURE_STEPS:-12} SAVE_STEPS=1000 FORMAT_CREDIT=0.05 python code/train.py; echo PURE_EXIT $?
date -u
# 3. SFT warm start on 200 DP-optimal train schedules
MODEL=$B OUT=$S python code/sft.py; echo SFT_EXIT $?
date -u
# 4. SFT eval
MODEL=$S OUT=$G/runs/eval BASE_TRAINED=sft SETS="sft:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_SFT_EXIT $?
date -u
echo PHASE1_DONE
