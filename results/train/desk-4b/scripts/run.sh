# The pilot (or an eval) on a box setup-box.sh prepared, as its user. One GPU: vLLM colocated with the trainer. More:
# a vLLM server (`trl vllm-serve`: data parallel over GPUs 1..N-1, tensor parallel 1; the trainer pushes the
# LoRA-merged weights to it every step) and the trainer on GPU 0. TRL asks the server for the whole completion budget
# (CONTEXT - 9216) at every turn of a day and the server refuses a request past its length, so it takes 2 x CONTEXT -
# 9216 tokens; TRL still cuts each completion at the budget. VLLM_MODE overrides the choice; MAX_STEPS, OUT,
# LR, EVAL_STEPS, EVAL_LIMIT and the rest pass through to train.py.
set -euo pipefail
cd "$HOME"
GPUS=$(nvidia-smi -L | wc -l)
MODE=${VLLM_MODE:-$([ "$GPUS" -gt 1 ] && echo server || echo colocate)}
export MODEL=${MODEL:-models/Qwen3-4B} ENV_URL=${ENV_URL:-http://127.0.0.1:8000} VLLM_MODE=$MODE
export VLLM_PORT=${VLLM_PORT:-8001} PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
curl -sf -m 10 "$ENV_URL/list_environments" > /dev/null || { echo "no env server at $ENV_URL"; exit 1; }
if [ "$MODE" = server ]; then
  [ "$GPUS" -gt 1 ] || { echo "VLLM_MODE=server needs a second GPU for vLLM"; exit 1; }
  SERVER_LEN=$((2 * ${CONTEXT:-40960} - 9216))
  if ! curl -sf -m 5 "http://127.0.0.1:$VLLM_PORT/health" > /dev/null; then
    CUDA_VISIBLE_DEVICES=$(seq -s, 1 $((GPUS - 1))) nohup trainer/bin/trl vllm-serve --model "$MODEL" \
      --tensor_parallel_size 1 --data_parallel_size $((GPUS - 1)) --max_model_len "$SERVER_LEN" --host 127.0.0.1 \
      --port "$VLLM_PORT" --enable_prefix_caching "${VLLM_PREFIX_CACHING:-True}" > vllm-serve.log 2>&1 &
    SERVER=$!
    until curl -sf -m 5 "http://127.0.0.1:$VLLM_PORT/health" > /dev/null; do
      kill -0 "$SERVER" 2>/dev/null || { tail -30 vllm-serve.log; exit 1; }
      sleep 10
    done
  fi
  export CUDA_VISIBLE_DEVICES=0
fi
echo "$(date -u +%FT%TZ) $GPUS GPU(s), vLLM $MODE"
exec trainer/bin/python plugin/results/train/desk-4b/scripts/train.py
