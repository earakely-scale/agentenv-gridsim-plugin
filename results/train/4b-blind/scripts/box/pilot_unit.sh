#!/bin/bash
set -x
. /home/ubuntu/gs7/code/env.sh
date -u
pilot() { [ -f $R/pilot-$1/sft_done.json ] || MODEL=$2 OUT=$R/pilot-$1 DATA=$G/data/sft_rows.jsonl.gz N=1000 LR=1e-4 SEED=0 GC=${GC:-0} MERGE=0 python $C/sft_blind.py; echo "PILOT_EXIT $1 $?"; date -u; }
pilot a $G/models/Qwen3-4B
while [ ! -f $R/step0/DONE ]; do sleep 20; done
pilot b $G/models/run3
for x in a:$G/models/Qwen3-4B b:$G/models/run3; do n=${x%%:*}; m=${x#*:}
  [ -f $R/pilot-eval/eval_pilot-$n.json ] || MODEL=$m OUT=$R/pilot-eval TRAINED=sft VLLM_UTIL=0.85 SETS="pilot-$n:$R/pilot-$n/adapter:0:holdout2024:sampled" python $C/evaluate_blind.py
  echo "EVAL_EXIT pilot-$n $?"; date -u
done
touch $R/pilot-eval/DONE; echo UNIT_DONE
