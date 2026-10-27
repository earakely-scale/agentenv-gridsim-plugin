#!/bin/bash
# ckpt_unit.sh: every RL checkpoint on eval2025 (sampled); the final also on fresh and with greedy decoding.
set -x
. /home/ubuntu/gs7/code/env.sh
while [ ! -f $R/rl-main/DONE ]; do sleep 20; done
M=$R/sft/merged; K=$R/rl-main/train/checkpoints
F=$(ls -d $K/ckpt-* | grep -v tmp | sort | tail -1)
S=""
for c in $(ls -d $K/ckpt-* | grep -v tmp | sort); do n=$(basename $c); st=$((10#${n#ckpt-}))
  if [ "$c" = "$F" ]; then S="$S;final:$c:$st:eval2025+fresh:sampled,greedy"; else S="$S;$n:$c:$st:eval2025:sampled"; fi
done
date -u
MODEL=$M OUT=$R/rl-eval TRAINED=rl VLLM_UTIL=0.85 SETS="$S" python $C/evaluate_blind.py
echo "EVAL_EXIT $?"; date -u
touch $R/rl-eval/DONE; echo UNIT_DONE
