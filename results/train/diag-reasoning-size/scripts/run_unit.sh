#!/bin/bash
set -x
export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING
export CUDA_VISIBLE_DEVICES=3
G=/home/ubuntu/gridsim-diag; M=$G/models; R=$G/runs/diag
cd $G; . .venv/bin/activate
mkdir -p $R
nvidia-smi -i 3 --query-gpu=name,memory.total,driver_version --format=csv > $R/gpu.csv
nvidia-smi -i 3 --query-gpu=timestamp,memory.used,utilization.gpu --format=csv,noheader -l 30 > $R/gpu_eval.csv &
NV=$!
Q4="Qwen3-4B Qwen/Qwen3-4B 1cfa9a7208912126459214e8b04321603b3df60c base"
Q8="Qwen3-8B Qwen/Qwen3-8B b968826d9c46dd6066d109eabc6255188de91218 base"
Q14="Qwen3-14B-AWQ Qwen/Qwen3-14B-AWQ 31c69efc29464b6bb0aee1398b5a7b50a99340c3 base"
SFT="qwen3-4b-sft10k-rule Qwen/Qwen3-4B 1cfa9a7208912126459214e8b04321603b3df60c sft"
ev() {
  local tag=$1 sets=$6
  date -u; MODEL=$M/$2 MODEL_ID=$3 REVISION=$4 TRAINED=$5 OUT=$R SETS="$sets" python code/diag_eval.py
  echo "EVAL_EXIT $tag $?"
}
ev check-4b $Q4 "q4b-off512:0:512:sampled"
ev check-sft $SFT "sft-off512:0:512:sampled"
python code/gate_diag.py $R || { echo GATE_FAIL; kill $NV; exit 1; }
ev p1-4b $Q4 "q4b-on4096:1:4096:sampled;q4b-on2048:1:2048:sampled"
ev p1-8b $Q8 "q8b-off512:0:512:sampled;q8b-on4096:1:4096:sampled"
ev p1-14b $Q14 "q14awq-off512:0:512:sampled;q14awq-on4096:1:4096:sampled"
ev p1-sft $SFT "sft-on2048:1:2048:sampled"
echo PRIMARY_DONE; date -u
[ "$(date -u +%Y%m%d%H%M)" -lt 202610270130 ] && ev p2-4b $Q4 "q4b-on4096-t06:1:4096:qwen_think"
[ "$(date -u +%Y%m%d%H%M)" -lt 202610270130 ] && ev p2-8b $Q8 "q8b-on4096-t06:1:4096:qwen_think"
[ "$(date -u +%Y%m%d%H%M)" -lt 202610270130 ] && ev p2-14b $Q14 "q14awq-on4096-t06:1:4096:qwen_think"
[ "$(date -u +%Y%m%d%H%M)" -lt 202610270130 ] && ev p2-sft $SFT "sft-on2048-t06:1:2048:qwen_think"
kill $NV
tar -C $G/runs -czf $G/results-diag.tgz diag
ls -la $G/results-diag.tgz
echo DIAG_DONE
