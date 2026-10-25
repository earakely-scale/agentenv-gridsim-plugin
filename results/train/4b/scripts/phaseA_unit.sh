#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; B=$G/models/Qwen3-4B; S=$G/models/qwen3-4b-sft1500soc; R=$G/runs/reg4b
mkdir -p $R
date -u
MODEL=$B OUT=$R/eval BASE_TRAINED=base SETS="base:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_BASE_EXIT $?
date -u
MODEL=$B OUT=$S N_SFT=1500 EPOCHS=1 RATIONALE=soc STRATIFY=start SEED=0 python code/sft.py; echo SFT_EXIT $?
date -u
MODEL=$S OUT=$R/eval BASE_TRAINED=sft SETS="sft:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_SFT_EXIT $?
date -u
echo PHASEA_DONE
