"""vLLM's per-request thinking budget on Qwen3.5 (offline LLM with the qwen3 reasoning parser): the thinking tokens
before `</think>` with and without `thinking_token_budget`, and whether a tool call follows.

    python think_budget_check.py MODEL_DIR OUT.json [END_STR]
"""

import json
import sys

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.config.reasoning import ReasoningConfig

path, out_path = sys.argv[1], sys.argv[2]
reasoning = {"reasoning_parser": "qwen3"} | ({"reasoning_end_str": sys.argv[3]} if len(sys.argv) > 3 else {})
tok = AutoTokenizer.from_pretrained(path)
tools = [{"type": "function", "function": {"name": "submit_dam_offers", "description": "Submit day-ahead offer curves",
                                           "parameters": {"type": "object", "properties": {"curves": {"type": "array"}},
                                                          "required": ["curves"]}}},
         {"type": "function", "function": {"name": "end_turn", "description": "End this wake",
                                           "parameters": {"type": "object", "properties": {}}}}]
question = ("You run a 100 MW / 400 MWh battery. Tomorrow's forecast day-ahead prices by hour are 22, 20, 19, 19, 21, "
            "30, 55, 70, 48, 35, 28, 25, 24, 26, 31, 45, 80, 140, 120, 75, 50, 38, 30, 25 $/MWh. Round-trip efficiency "
            "is 88% and the state of charge starts at 50%. Work out carefully which hours to charge and discharge, "
            "then submit day-ahead offers with submit_dam_offers and end your turn.")
ids = tok.apply_chat_template([{"role": "user", "content": question}], tools=tools, add_generation_prompt=True,
                              enable_thinking=True, tokenize=True, return_dict=False)
end_id = tok.convert_tokens_to_ids("</think>")
llm = LLM(model=path, max_model_len=16384, gpu_memory_utilization=0.85, reasoning_parser="qwen3",
          reasoning_config=ReasoningConfig(**reasoning))
result = {"reasoning": reasoning, "runs": []}
for budget in (None, 64, 256, 1024):
    params = SamplingParams(n=4, temperature=0.8, top_p=0.95, top_k=20, max_tokens=6144, seed=0,
                            thinking_token_budget=budget)
    outs = llm.generate([{"prompt_token_ids": ids}], params)[0].outputs
    rows = []
    for o in outs:
        toks = list(o.token_ids)
        think = toks.index(end_id) if end_id in toks else None
        text = tok.decode(toks)
        rows.append({"thinking_tokens": think, "total_tokens": len(toks), "tool_call": "<tool_call>" in text,
                     "tail": text[-160:] if think is None else tok.decode(toks[max(0, think - 12):think + 40])})
    result["runs"].append({"budget": budget, "samples": rows})
    print(budget, [(r["thinking_tokens"], r["total_tokens"], r["tool_call"]) for r in rows], flush=True)
json.dump(result, open(out_path, "w"), indent=1)
