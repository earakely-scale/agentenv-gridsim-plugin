#!/bin/bash
# sft_unit.sh: the main SFT (START_MODEL, N, DEADLINE from the environment), then RL step 0 = the merged SFT model on eval2025+fresh.
set -x
. /home/ubuntu/gs7/code/env.sh
date -u
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 60 > $R/gpu_sft.csv &
NV=$!
[ -f $R/sft/sft_done.json ] || PYTORCH_CUDA_ALLOC_CONF=$TRAIN_ALLOC MODEL=$START_MODEL START=0 OUT=$R/sft DATA=$G/data/sft_rows.jsonl.gz N=$N LR=1e-4 SEED=0 GC=0 MERGE=1 DEADLINE=$DEADLINE python $C/sft_blind.py
echo "SFT_EXIT $?"; date -u
kill $NV
[ -f $R/rl-eval/eval_rl-0000.json ] || MODEL=$R/sft/merged OUT=$R/rl-eval TRAINED=sft VLLM_UTIL=0.85 SETS="rl-0000:-:0:eval2025+fresh:sampled,greedy" python $C/evaluate_blind.py
echo "EVAL_EXIT rl-0000 $?"; date -u
touch $R/sft/DONE; echo UNIT_DONE
