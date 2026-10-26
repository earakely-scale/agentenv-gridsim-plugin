#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
G=/home/ubuntu/gs; S=$G/models/qwen3-4b-sft10k-rule; A=$G/adapter/grpo-lora; R=$G/runs/confirm
cd $G; . .venv/bin/activate
mkdir -p $R
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > $R/gpu.csv
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 30 > $R/gpu_eval.csv &
NV=$!
ev() { MODEL=$S BASE_TRAINED=sft OUT=$R/$1 EVAL_PACK=ercot-dam-v1-$2 N=$3 SETS="$4" python code/evaluate.py; echo "EVAL_EXIT $1 $4 $?"; date -u; }
date -u
ev check eval 200 "sft:-:0:200:sampled,greedy;trained:$A:310:200:sampled,greedy"
python code/gate.py $R/check || { echo GATE_FAIL; kill $NV; exit 1; }
ev eval-iid-sft eval-iid 500 "sft:-:0:500:sampled,greedy"
ev rtcb-sft rtcb 250 "sft:-:0:250:sampled,greedy"
ev eval-iid-trained eval-iid 500 "trained:$A:310:500:sampled,greedy"
ev rtcb-trained rtcb 250 "trained:$A:310:250:sampled,greedy"
kill $NV
tar -C $G/runs -czf $G/results-confirm.tgz confirm
ls -la $G/results-confirm.tgz
echo EVAL_DONE
