# Scoring the trained LoRA on the desk-v4 leaderboard: OpenCode, route C

The fine-tuned Qwen3-4B is scored the way base Qwen3-4B was: the 32 `desk-v4-bench` windows, each played by OpenCode
against the plain bench bundle (`desk_bench.py tasks --harness opencode-qwen`, code at `desk-v4-bench-run1`), on a Qwen
box with route C (local Docker, the host egress rule and the strict lane proxy; `docs/prereg/v4-bench.md`). The only
change is the model server: the same vLLM build and flags as base Qwen's bench run, plus the LoRA, at 32,768 tokens of
context. The bundle, the env image, OpenCode and its config, the proxy and the driver stay as they were, so the
bundle's model id `qwen3-4b` must reach the adapter.

The route C kit is the operator's (not in this repo): the box `setup.sh`, `qwen-vllm.service` with the `benchrun.conf`
drop-in, `proxy.py` with `lanes.json`, the driver `bench_c.py`, `bench_launch.sh` and `pull.py`, as the base Qwen run
used them on 2026-10-29.

## 1. The box

One g5.xlarge or g5.2xlarge (one A10G, as base Qwen's four boxes), set up with the kit's `setup.sh` unchanged: Qwen3-4B
at revision `1cfa9a7208912126459214e8b04321603b3df60c`, the vLLM venv from `vllm_freeze.txt` (vLLM 0.29.0, torch
2.13.0+cu130, transformers 5.17.0), the harness venv (agentenv-framework 0.9.1378, the plugin at `desk-v4-bench`), the
bench bundle stripped for route C, the env image, the registry, the proxy, the egress rule and the netcheck.

## 2. Serve the LoRA as `qwen3-4b`

Copy the adapter folder the trainer wrote (`out/adapter`, or a checkpoint's `out/checkpoint-N`; it holds
`adapter_config.json` and `adapter_model.safetensors`) to `/home/ubuntu/gl/adapters/desk-4b` on the box. Add a drop-in
after `benchrun.conf` that keeps base Qwen's flags, serves the base under another name and the adapter under the
bundle's:

```ini
# /etc/systemd/system/qwen-vllm.service.d/lora.conf
[Service]
ExecStart=
ExecStart=/home/ubuntu/gl/.venv/bin/vllm serve /home/ubuntu/gl/models/Qwen3-4B --served-model-name qwen3-4b-base --host 127.0.0.1 --port 8000 --gpu-memory-utilization 0.88 --dtype bfloat16 --enable-auto-tool-choice --tool-call-parser hermes --default-chat-template-kwargs '{"enable_thinking": false}' --enable-prefix-caching --max-model-len 32768 --reasoning-parser qwen3 --enable-prompt-tokens-details --enable-lora --max-lora-rank 32 --max-loras 1 --lora-modules qwen3-4b=/home/ubuntu/gl/adapters/desk-4b
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart qwen-vllm
curl -s localhost:8000/v1/models | python3 -c "import json,sys; print([m['id'] for m in json.load(sys.stdin)['data']])"
# ['qwen3-4b-base', 'qwen3-4b']
```

OpenCode still asks for `qwen3-4b` with thinking on (its config sends `enable_thinking: true`, temperature 0.6, top_p
0.95, top_k 20), the lane still admits only `qwen3-4b`, and every request now runs through the adapter. To score the
base model again on the same box, remove `lora.conf` and restart.

## 3. Quick check on a pilot checkpoint: two windows

One pre-cutoff and one post-cutoff window, which base Qwen also played:

```bash
printf 'desk-v4-2026-01-23-S02\ndesk-v4-2026-08-18-S02\n' > /home/ubuntu/harness/bench/qwen-ft/tasks-quick.txt
cd /home/ubuntu/harness/repo && /home/ubuntu/harness/.venv/bin/python /home/ubuntu/harness/proxy/bench_c.py \
  --key qwen-ft --harness opencode-qwen --tasks-file /home/ubuntu/harness/bench/qwen-ft/tasks-quick.txt \
  --parallel 2 --box qwen-ft1 --agent-version "<as bench_launch.sh prints it>"
```

(`bench_launch.sh` runs the same command under a systemd unit with `--key qwen`; pass `--key qwen-ft` so the results go
to `bench/qwen-ft/`.) Base Qwen's windows took 24 minutes at the median (77 at most) four at a time on one A10G. Read
`bench/qwen-ft/results.jsonl` for R, C and validity, and the proxy log for the number of calls the model sent to a tool
it doesn't have: the trained model ends its turns with `end_turn`, which OpenCode doesn't offer (see the README's
"Train and eval gap").

## 4. All 32 windows

As base Qwen: the 32 windows split over four boxes (eight each, `--parallel 4`), `bench_launch.sh` per box with the
adapter's drop-in in place, then `pull.py` for the results and each attempt's GPU share, and
`scripts/desk_bench_results.py` to score them beside the five models (C with its interval, pre and post cutoff,
cost per window). The fine-tuned model is an added entry, so its runs are reported against the pre-registered rules
with a deviation note for the added model.

## Qwen3.5-9B

The leaderboard rows for Qwen3.5-9B (base and fine-tuned) run the same way, with the `opencode-qwen35` harness:
`desk_bench.py tasks --harness opencode-qwen35 --pack desk-v4-bench --allow-host 127.0.0.1` writes the bench bundle
for model id `qwen3.5-9b`, and `bench/harness/bench-opencode-qwen35/opencode.json` is the 4B's OpenCode config with
that model id (temperature 0.6, top_p 0.95, top_k 20, thinking on, 32,768 tokens of context). Base Qwen3.5-9B has no
bench run yet, so it needs one as well, under the same harness.

- **Box:** the weights are 19 GB in bf16, too many for the A10G's 24 GB with a 32k context. Use one L40S
  (`g6e.xlarge`) or larger. Download `Qwen/Qwen3.5-9B` at revision `c202236235762e1c871ad0ccb60c8ee5ba337b9a`.
- **vLLM 0.29**, the bench run's other flags kept, the parsers Qwen3.5 needs, and the vision tower left out:

```bash
vllm serve /home/ubuntu/gl/models/Qwen3.5-9B --served-model-name qwen3.5-9b --host 127.0.0.1 --port 8000 \
  --gpu-memory-utilization 0.88 --dtype bfloat16 --enable-auto-tool-choice --tool-call-parser qwen3_coder \
  --reasoning-parser qwen3 --default-chat-template-kwargs '{"enable_thinking": false}' --enable-prefix-caching \
  --max-model-len 32768 --enable-prompt-tokens-details --language-model-only
```

  Qwen3.5 writes tool calls as XML (`<tool_call><function=…><parameter=…>`), which vLLM's `qwen3_coder` parser reads.
  OpenCode turns thinking on per request, as for the 4B.
- **The fine-tuned model:** merge the adapter into the base (`PeftModel.from_pretrained(base, adapter)
  .merge_and_unload().save_pretrained(...)`, with the base's tokenizer and processor files copied beside it) and serve
  the merged folder under the same name with the same flags. This avoids depending on vLLM's LoRA support for
  Qwen3.5's linear-attention projections, which the adapter also covers.
- **The quick check and the full run** are as above, with `--harness opencode-qwen35` and `--key qwen35-base` or
  `--key qwen35-ft`. The proxy lane's `models` list is `["qwen3.5-9b"]`.
