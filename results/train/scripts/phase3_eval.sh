#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; R=$G/runs/grpo
SETS=""
for c in $(ls -d $R/checkpoint-* | sort -t- -k2 -n); do n=${c##*-}; [ -f $c/adapter_model.safetensors ] || continue
  [ "$n" = "${STEPS:-280}" ] && continue; SETS="$SETS$(printf 'ckpt-%04d' $n):$c:$n:50:sampled;"; done
SETS="${SETS}trained:$R/adapter:${STEPS:-280}:200:sampled,greedy"
echo "$SETS"
date -u
MODEL=${MODEL:-$G/models/qwen3-1.7b-sft200} OUT=$G/runs/eval BASE_TRAINED=sft SETS="$SETS" python code/evaluate.py; echo EVAL3_EXIT $?
date -u
echo PHASE3_DONE
