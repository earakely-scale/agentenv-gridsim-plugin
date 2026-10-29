#!/bin/bash
# Run 3 evals on EVAL_GPU (default 2) with the unchanged evaluate.py: step 0 (200 eval-2025 + 500 eval-iid), every checkpoint as it
# lands (200 eval-2025, sampled + greedy), then the final adapter on eval-iid.
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
cd /home/ubuntu/gs; . .venv/bin/activate
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft10k-rule; C=$G/code; R=$G/runs/main; E=$R/eval
mkdir -p $E $R/eval-iid
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > $R/gpu.csv
ev() { CUDA_VISIBLE_DEVICES=${EVAL_GPU:-2} MODEL=$S BASE_TRAINED=sft OUT=$1 EVAL_PACK=ercot-dam-v1-$2 N=$3 SETS="$4" python $C/evaluate.py; echo "EVAL_EXIT $4 $?"; date -u; }
pending() { for c in $(ls -d $R/train/checkpoints/ckpt-* 2>/dev/null | grep -v tmp | sort); do [ -f $E/eval_$(basename $c).json ] || echo $c; done; }
date -u
[ -f $E/eval_step-0000.json ] || ev $E eval 200 "step-0000:-:0:200:sampled,greedy"
[ -f $R/eval-iid/eval_sft.json ] || ev $R/eval-iid eval-iid 500 "sft:-:0:500:sampled,greedy"
while :; do
  for c in $(pending); do n=$(basename $c); ev $E eval 200 "$n:$c:$((10#${n#ckpt-})):200:sampled,greedy"; done
  [ -f $R/TRAIN_DONE ] && [ -z "$(pending)" ] && break
  sleep 30
done
F=$(ls -d $R/train/checkpoints/ckpt-* | grep -v tmp | sort | tail -1)
[ -f $R/eval-iid/eval_final.json ] || ev $R/eval-iid eval-iid 500 "final:$F:$((10#$(basename $F | cut -d- -f2))):500:sampled,greedy"
touch $R/EVAL_DONE
echo EVAL_UNIT_DONE
