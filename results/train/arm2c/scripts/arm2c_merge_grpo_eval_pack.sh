#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; M0=$G/models/qwen3-1.7b-arm2-step75; M=$G/models/qwen3-1.7b-arm2b-step180; R=$G/runs/arm2c
mkdir -p $R
date -u
[ -f $M/config.json ] || BASE=$M0 ADAPTER=$G/runs/arm2b/grpo/adapter OUT=$M python code/merge_adapter.py; echo MERGE_EXIT $?
DL=$(date -u -d "2026-10-24 20:00:00" +%s)
rm -rf $R/grpo
date -u
MODEL=$M OUT=$R/grpo SEED=2 LR=1e-5 LR_SCHED=cosine WARMUP=5 TEMP=1.1 CURRICULUM=mixed PROMPTS_PER_STEP=8 NUM_GEN=8 MICRO=4 \
  MAX_STEPS=150 SAVE_STEPS=25 MAX_COMPLETION=512 DEADLINE=$DL STEP_OFFSET=180 CLIFF_R=0.45 CLIFF_FEAS=0.6 \
  python code/train.py; echo GRPO2C_EXIT $?
date -u
FINAL=$(tail -n 1 $R/grpo/train_log.jsonl | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['step'])")
[ -f $R/grpo/adapter/adapter_config.json ] || { L=$(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n | tail -1); cp -r $L $R/grpo/adapter; FINAL=${L##*-}; }
SETS="start:-:180:50:sampled;"
for c in $(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n); do n=${c##*-}; [ -f $c/adapter_model.safetensors ] || continue
  [ "$n" = "$FINAL" ] && continue; g=$((180 + n)); SETS="$SETS$(printf 'ckpt-%04d' $g):$c:$g:50:sampled;"; done
SETS="${SETS}trained:$R/grpo/adapter:$((180 + FINAL)):200:sampled,greedy"
echo "$SETS"
MODEL=$M OUT=$R/eval BASE_TRAINED=grpo SETS="$SETS" python code/evaluate.py; echo EVAL_ARM2C_EXIT $?
date -u
shopt -s nullglob
rm -rf pack4; mkdir -p pack4/results/grpo pack4/adapter
cp -r $R/eval pack4/results/; cp $R/grpo/{train_log.jsonl,samples.jsonl} pack4/results/grpo/; cp logs/gs-arm2d.log pack4/results/ 2>/dev/null
[ -d $R/grpo/adapter ] && cp -r $R/grpo/adapter pack4/adapter/grpo2c-lora
for c in $R/grpo/checkpoint-*; do mkdir -p pack4/adapter/checkpoints/$(basename $c) && cp $c/adapter_* pack4/adapter/checkpoints/$(basename $c)/; done
tar -C pack4 -czf results4.tgz results; tar -C pack4 -czf adapter4.tgz adapter; ls -la results4.tgz adapter4.tgz
set +x
date -u
echo ARM2C_DONE
