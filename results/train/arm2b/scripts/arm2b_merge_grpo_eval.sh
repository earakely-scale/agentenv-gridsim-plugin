#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-1.7b-sft1500soc; M=$G/models/qwen3-1.7b-arm2-step75; R=$G/runs/arm2b
mkdir -p $R
date -u
[ -f $M/config.json ] || BASE=$S ADAPTER=$G/runs/arm2/grpo/adapter OUT=$M python code/merge_adapter.py; echo MERGE_EXIT $?
DL=$(date -u -d "2026-10-24 ${DEADLINE_HHMM:-16:10}:00" +%s)
rm -rf $R/grpo
date -u
MODEL=$M OUT=$R/grpo SEED=1 LR=1e-5 LR_SCHED=cosine WARMUP=5 TEMP=1.1 CURRICULUM=mixed PROMPTS_PER_STEP=8 NUM_GEN=8 MICRO=4 \
  MAX_STEPS=${STEPS:-105} SAVE_STEPS=25 MAX_COMPLETION=512 DEADLINE=$DL STEP_OFFSET=75 CLIFF_R=0.45 CLIFF_FEAS=0.6 \
  python code/train.py; echo GRPO2B_EXIT $?
date -u
FINAL=$(tail -n 1 $R/grpo/train_log.jsonl | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['step'])")
[ -f $R/grpo/adapter/adapter_config.json ] || { L=$(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n | tail -1); cp -r $L $R/grpo/adapter; FINAL=${L##*-}; }
SETS="start:-:75:50:sampled;"
for c in $(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n); do n=${c##*-}; [ -f $c/adapter_model.safetensors ] || continue
  [ "$n" = "$FINAL" ] && continue; g=$((75 + n)); SETS="$SETS$(printf 'ckpt-%04d' $g):$c:$g:50:sampled;"; done
SETS="${SETS}trained:$R/grpo/adapter:$((75 + FINAL)):200:sampled,greedy"
echo "$SETS"
MODEL=$M OUT=$R/eval BASE_TRAINED=grpo SETS="$SETS" python code/evaluate.py; echo EVAL_ARM2B_EXIT $?
date -u
echo ARM2B_DONE
