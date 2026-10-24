#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; B=$G/models/Qwen3-1.7B; S=$G/models/qwen3-1.7b-sft1500soc; R=$G/runs/arm2
mkdir -p $R
date -u
MODEL=$B OUT=$S N_SFT=1500 EPOCHS=1 RATIONALE=soc STRATIFY=start python code/sft.py; echo SFT2_EXIT $?
date -u
MODEL=$S OUT=$R/eval BASE_TRAINED=sft SETS="sft2:-:0:200:sampled,greedy" python code/evaluate.py; echo EVAL_SFT2_EXIT $?
date -u
MAXC=$(python3 -c "import json; m=json.load(open('$S-meta.json'))['completion_tokens_max']; print(384 if m <= 330 else 512)")
echo "MAX_COMPLETION=$MAXC"
DL=$(date -u -d "2026-10-24 ${ARM2_DEADLINE:-13:05}:00" +%s)
rm -rf $R/grpo
MODEL=$S OUT=$R/grpo LR=1.5e-5 TEMP=1.1 CURRICULUM=mixed PROMPTS_PER_STEP=8 NUM_GEN=8 MICRO=4 MAX_STEPS=${STEPS:-100} \
  SAVE_STEPS=25 MAX_COMPLETION=$MAXC DEADLINE=$DL python code/train.py; echo GRPO2_EXIT $?
date -u
FINAL=$(tail -n 1 $R/grpo/train_log.jsonl | python3 -c "import json,sys; print(json.loads(sys.stdin.read())['step'])")
SETS=""
for c in $(ls -d $R/grpo/checkpoint-* | sort -t- -k2 -n); do n=${c##*-}; [ -f $c/adapter_model.safetensors ] || continue
  [ "$n" = "$FINAL" ] && continue; SETS="$SETS$(printf 'ckpt-%04d' $n):$c:$n:50:sampled;"; done
SETS="${SETS}trained:$R/grpo/adapter:$FINAL:200:sampled,greedy"
echo "$SETS"
MODEL=$S OUT=$R/eval BASE_TRAINED=sft SETS="$SETS" python code/evaluate.py; echo EVAL_ARM2_EXIT $?
date -u
echo ARM2_DONE
