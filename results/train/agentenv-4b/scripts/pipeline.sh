# The run, unattended: the base model's eval on the 200 eval days, the SFT warm start, then GRPO from it with evals at
# steps 0, 20 and 40. Each stage logs to /home/ubuntu/<stage>.log; a failed stage stops the pipeline.
set -euo pipefail
cd /home/ubuntu
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
stage() { echo "$(date -u +%FT%TZ) START $1" >> pipeline.log; shift; "$@"; echo "$(date -u +%FT%TZ) DONE" >> pipeline.log; }
[ -f out-base/log_history.json ] || stage base env MODEL=Qwen/Qwen3-4B MAX_STEPS=0 OUT=out-base trainer/bin/python kit/train.py >> base.log 2>&1
[ -f qwen3-4b-gridsim-sft/config.json ] || stage sft trainer/bin/python kit/sft.py >> sft.log 2>&1
[ -f out-grpo/log_history.json ] || stage grpo env MODEL=qwen3-4b-gridsim-sft MAX_STEPS=40 EVAL_STEPS=20 OUT=out-grpo trainer/bin/python kit/train.py >> grpo.log 2>&1
echo "$(date -u +%FT%TZ) ALL DONE" >> pipeline.log
