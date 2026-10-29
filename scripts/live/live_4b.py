"""The trained Qwen3-4B (registered run 4 final) on a live day's sealed tasks: evaluate_blind.py's engine, prompt and
sampled decoding (T 0.7, top_p 0.8, top_k 20, seed 0, max_tokens 768, thinking off), without grading.

usage: live_4b.py TASKS_JSON OUT_JSONL. Env: QWEN_MODEL (run 4's merged SFT model), QWEN_ADAPTER (its rl-lora),
VLLM_UTIL. TASKS_JSON may also be a pack name (the reproduction check against eval_final.json)."""

import json
import os
import sys
import time
from pathlib import Path

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "results/train/4b-blind/scripts"))
from pathb_blind import prompt_text, tool_call  # noqa: E402

from gridsim_core.forecast_line import parse_forecast  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402
from gridsim_core.trl import extract_actions  # noqa: E402


def main():
    src, out = sys.argv[1:3]
    tasks = json.loads(Path(src).read_text())["tasks"] if src.endswith(".json") else [
        t for t in load_pack(src) if t["tags"].get("blind_eval")]
    model, adapter = os.environ["QWEN_MODEL"], os.environ["QWEN_ADAPTER"]
    tok = AutoTokenizer.from_pretrained(model)
    llm = LLM(model=model, enable_lora=True, max_lora_rank=32, max_loras=1, max_model_len=4096, seed=0,
              gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.85")))
    params = SamplingParams(max_tokens=768, seed=0, temperature=0.7, top_p=0.8, top_k=20)
    t0 = time.monotonic()
    outs = llm.generate([prompt_text(tok, t) for t in tasks], params, lora_request=LoRARequest("final", 1, adapter),
                        use_tqdm=False)
    wall = round(time.monotonic() - t0, 2)
    with open(out, "w") as f:
        for t, o in zip(tasks, outs, strict=True):
            c = o.outputs[0]
            f.write(json.dumps({"task_id": t["task_id"], "agent": "qwen3-4b-gridsim-run4", "text": c.text,
                                "finish_reason": c.finish_reason, "truncated": c.finish_reason == "length",
                                "sent": extract_actions(c.text), "forecast": parse_forecast(c.text),
                                "tool_call": tool_call(c.text), "tokens": len(c.token_ids),
                                "prompt_tokens": len(o.prompt_token_ids), "usd": 0.0, "wall_s": wall,
                                "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}) + "\n")
    print(json.dumps({"tasks": len(tasks), "wall_s": wall}), flush=True)


if __name__ == "__main__":
    main()
