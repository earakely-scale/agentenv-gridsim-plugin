export HOME=/root PYTHONUNBUFFERED=1 HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false VLLM_LOGGING_LEVEL=WARNING MODEL_ID=Qwen/Qwen3-4B
G=/home/ubuntu/gs7; C=$G/plugin/results/train/4b-blind/scripts; R=$G/runs
. $G/.venv/bin/activate
export PYTHONPATH=$G/plugin/src HOLDOUT=$G/data/holdout2024.json
export TRAIN_ALLOC=expandable_segments:True
