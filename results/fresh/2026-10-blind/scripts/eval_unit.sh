#!/bin/bash
# eval_unit.sh GPU: the blind tier on the fresh-2026-10-blind pack, SFT-10k then run 3 final, sampled and greedy.
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
D=/home/ubuntu/gridsim-fresh; P=$D/plugin; C=$P/results/fresh/2026-10-blind/scripts
. /home/ubuntu/gs/.venv/bin/activate
export PYTHONPATH=$P/src CUDA_VISIBLE_DEVICES=$1 MODEL=$D/models/qwen3-4b-sft10k-rule BASE_TRAINED=sft TIER=blind MAX_MODEL_LEN=4096
date -u
[ -f $D/runs/blind/eval_run3.json ] || OUT=$D/runs/blind EVAL_PACK=$P/data/ercot-dam-v1-fresh-2026-10-blind N=331 \
  SETS="sft10k:-:0:331:sampled,greedy;run3:$D/adapters/reg3/adapter/dpa-lora:300:331:sampled,greedy" python $C/evaluate.py
echo "EVAL_EXIT $?"; date -u; echo UNIT_DONE
