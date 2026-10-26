#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft10k-rule; R=$G/runs/reg4b2
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 30 > $R/gpu_main.csv &
NV=$!
DL=$(date -u -d "2026-10-26 10:00:00" +%s)
rm -rf $R/grpo
date -u
MODEL=$S OUT=$R/grpo SEED=0 LR=1e-5 LR_SCHED=cosine WARMUP=5 TEMP=1.1 CURRICULUM=adaptive PROMPTS_PER_STEP=8 NUM_GEN=8 \
  CANDIDATES=16 REPLAY_P=0.5 VISIT_CAP=4 MICRO=${MICRO:-4} MAX_STEPS=${STEPS:-310} SAVE_STEPS=25 MAX_COMPLETION=512 \
  VLLM_UTIL=${VLLM_UTIL:-0.4} DEADLINE=$DL CLIFF_R=0.45 CLIFF_FEAS=0.6 python code/train.py
echo GRPO_EXIT $?
kill $NV
date -u
FINAL=$(tail -n 1 $R/grpo/train_log.jsonl | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['step'])")
[ -f $R/grpo/adapter/adapter_config.json ] || { L=$(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n | tail -1); cp -r $L $R/grpo/adapter; FINAL=${L##*-}; }
SETS=""
for c in $(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n); do n=${c##*-}; [ -f $c/adapter_model.safetensors ] || continue
  [ "$n" = "$FINAL" ] && continue; SETS="$SETS$(printf 'ckpt-%04d' $n):$c:$n:50:sampled;"; done
SETS="${SETS}trained:$R/grpo/adapter:$FINAL:200:sampled,greedy"
echo "$SETS"
MODEL=$S OUT=$R/eval BASE_TRAINED=sft SETS="$SETS" python code/evaluate.py; echo EVAL_TRAINED_EXIT $?
date -u
rm -rf pack; mkdir -p pack/results/grpo pack/adapter
cp -r $R/eval pack/results/; cp $R/grpo/{train_log.jsonl,samples.jsonl,log_history.json} pack/results/grpo/ 2>/dev/null
cp $R/gpu_main.csv $R/gpu_sft.csv logs/freeze.txt pack/results/; cp $S-meta.json $S/sft_task_ids.json pack/results/
cp $R/smoke_train_log.jsonl pack/results/ 2>/dev/null
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > pack/results/gpu.csv
cp -r $S-adapter pack/adapter/sft-lora; cp -r $R/grpo/adapter pack/adapter/grpo-lora
for c in $R/grpo/checkpoint-*; do mkdir -p pack/adapter/checkpoints/$(basename $c) && cp $c/adapter_* pack/adapter/checkpoints/$(basename $c)/; done
tar -C pack -czf results-4b2.tgz results
tar -C pack -czf adapter-4b2-final.tgz adapter/sft-lora adapter/grpo-lora
tar -C pack -czf adapter-4b2-ckpts.tgz adapter/checkpoints
ls -la results-4b2.tgz adapter-4b2-final.tgz adapter-4b2-ckpts.tgz
date -u
echo MAIN_DONE
