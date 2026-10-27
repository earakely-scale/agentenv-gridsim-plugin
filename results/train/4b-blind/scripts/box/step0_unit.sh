#!/bin/bash
set -x
. /home/ubuntu/gs7/code/env.sh
export VLLM_UTIL=0.85
while [ ! -f $R/pilot-a/sft_done.json ]; do sleep 15; done
sleep 20
mkdir -p $R/step0; date -u
[ -f $R/step0/eval_base.json ] || MODEL=$G/models/Qwen3-4B OUT=$R/step0 TRAINED=base SETS="base:-:0:eval2025+fresh:sampled,greedy" python $C/evaluate_blind.py
echo "EVAL_EXIT base $?"; date -u
[ -f $R/step0/eval_run3.json ] || MODEL=$G/models/run3 OUT=$R/step0 TRAINED=run3 SETS="run3:-:0:eval2025+fresh:sampled,greedy" python $C/evaluate_blind.py
echo "EVAL_EXIT run3 $?"; date -u
touch $R/step0/DONE; echo UNIT_DONE
