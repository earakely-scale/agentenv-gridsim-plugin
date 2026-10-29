#!/bin/bash
# eval_unit.sh GPU LABEL ADAPTER STEP LO HI: pipeline check on 200 eval-2025 (sampled), gate, then the fresh pack (sampled, greedy).
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
D=/home/ubuntu/gridsim-fresh; P=$D/plugin; C=$P/results/train/4b-dpa/scripts
. /home/ubuntu/gs/.venv/bin/activate
export PYTHONPATH=$P/src CUDA_VISIBLE_DEVICES=$1 MODEL=$D/models/qwen3-4b-sft10k-rule BASE_TRAINED=sft
G=$1 L=$2 A=$3 S=$4
date -u
[ -f $D/runs/check/eval_chk-$L.json ] || OUT=$D/runs/check EVAL_PACK=ercot-dam-v1-eval N=200 SETS="chk-$L:$A:$S:200:sampled" python $C/evaluate.py
python $D/code/gate.py $D/runs/check/eval_chk-$L.json $5 $6 || { echo "UNIT_STOP gate"; exit 1; }
date -u
[ -f $D/runs/fresh/eval_$L.json ] || OUT=$D/runs/fresh EVAL_PACK=$P/data/ercot-dam-v1-fresh-2026-10 N=362 SETS="$L:$A:$S:362:sampled,greedy" python $C/evaluate.py
echo "EVAL_EXIT $?"; date -u; echo UNIT_DONE
