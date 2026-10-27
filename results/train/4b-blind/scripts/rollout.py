"""Rollout worker for registered run 4 (run 3's, with MAX_MODEL_LEN for the blind prompt): one engine on the merged
blind-SFT model serving the trainer's requests in ROLL/.
req-<k>.json {step, adapter, prompts [{task_id, prompt_ids}], seed, temperature, max_tokens} -> roll-<k>.json with each
completion's token ids, sampled-token logprobs (the behaviour policy), text and finish reason. BACKEND=vllm (the box) or
hf (CPU dry run; MOCK_P of the rollouts are replaced by the teacher forecast and plan with 0-3 perturbed hours, scored
by the current policy, so the credit path runs on parseable text).

Env: MODEL, ROLL, BACKEND, VLLM_UTIL, SEED, MOCK_P, MAX_MODEL_LEN, RL_POOL (hf only)."""

import json
import os
import random
import time
from pathlib import Path

MODEL = os.environ["MODEL"]
ROLL = Path(os.environ["ROLL"])
BACKEND = os.environ.get("BACKEND", "vllm")
SEED = int(os.environ.get("SEED", "0"))
MOCK_P = float(os.environ.get("MOCK_P", "0.5"))


def wait_for(path: Path) -> dict | None:
    while not path.exists():
        if (ROLL / "STOP").exists():
            return None
        time.sleep(0.2)
    return json.loads(path.read_text())


def write(path: Path, obj: dict):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.rename(path)


def vllm_engine():
    from vllm import LLM, SamplingParams
    from vllm.lora.request import LoRARequest

    llm = LLM(model=MODEL, enable_lora=True, max_lora_rank=32, max_loras=1, seed=SEED,
              max_model_len=int(os.environ.get("MAX_MODEL_LEN", "4096")),
              gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.85")), logprobs_mode="processed_logprobs")

    def generate(req: dict) -> list[dict]:
        params = SamplingParams(n=1, temperature=req["temperature"], top_p=1.0, max_tokens=req["max_tokens"],
                                seed=req["seed"], logprobs=0)
        lora = LoRARequest(f"step{req['step']}", req["step"] + 1, req["adapter"]) if req["adapter"] else None
        outs = llm.generate([{"prompt_token_ids": p["prompt_ids"]} for p in req["prompts"]], params,
                            lora_request=lora, use_tqdm=False)
        rows = []
        for p, o in zip(req["prompts"], outs, strict=True):
            c = o.outputs[0]
            lps = [next(v.logprob for k, v in lp.items() if k == t) for t, lp in zip(c.token_ids, c.logprobs,
                                                                                     strict=True)]
            rows.append({"task_id": p["task_id"], "prompt_ids": list(o.prompt_token_ids), "ids": list(c.token_ids),
                         "logprobs": lps, "text": c.text, "finish": c.finish_reason})
        return rows

    return generate


def hf_engine():
    import gzip

    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from gridsim_core.forecast import forecast_line

    tok = AutoTokenizer.from_pretrained(MODEL)
    with gzip.open(os.environ["RL_POOL"], "rt") as f:
        pool = {r["task"]["task_id"]: r for r in map(json.loads, f)}
    rng = random.Random(SEED)

    def logprobs(model, prompt, ids):
        x = torch.tensor([prompt + ids])
        with torch.no_grad():
            lp = torch.log_softmax(model(input_ids=x, logits_to_keep=len(ids) + 1).logits[0, :-1].float(), -1)
        return lp.gather(-1, torch.tensor(ids)[:, None])[:, 0].tolist()

    def generate(req: dict) -> list[dict]:
        model = AutoModelForCausalLM.from_pretrained(MODEL, dtype=torch.float32)
        if req["adapter"]:
            model = PeftModel.from_pretrained(model, req["adapter"])
        model.eval()
        torch.manual_seed(req["seed"])
        rows = []
        for p in req["prompts"]:
            if rng.random() < MOCK_P:
                row = pool[p["task_id"]]
                acts = list(row["plan"])
                for _ in range(rng.randint(0, 3)):
                    acts[rng.randrange(24)] += rng.choice([-1, 1])
                call = json.dumps({"name": "submit_schedule", "arguments": {"actions": acts}})
                text = f"{forecast_line(row['forecast'])}\nPlan: mock.\n<tool_call>\n{call}\n</tool_call>"
                ids, finish = tok(text, add_special_tokens=False).input_ids + [tok.eos_token_id], "stop"
            else:
                with torch.no_grad():
                    out = model.generate(torch.tensor([p["prompt_ids"]]), do_sample=True,
                                         temperature=req["temperature"], top_p=1.0, top_k=0,
                                         max_new_tokens=req["max_tokens"], pad_token_id=tok.pad_token_id)
                ids = out[0, len(p["prompt_ids"]):].tolist()
                finish = "stop" if ids and ids[-1] == tok.eos_token_id else "length"
                text = tok.decode(ids, skip_special_tokens=True)
            rows.append({"task_id": p["task_id"], "prompt_ids": p["prompt_ids"], "ids": ids,
                         "logprobs": logprobs(model, p["prompt_ids"], ids), "text": text, "finish": finish})
        return rows

    return generate


def main():
    ROLL.mkdir(parents=True, exist_ok=True)
    generate = vllm_engine() if BACKEND == "vllm" else hf_engine()
    (ROLL / "READY").write_text("1")
    k = 0
    while (req := wait_for(ROLL / f"req-{k:05d}.json")) is not None:
        t0 = time.monotonic()
        rows = generate(req)
        write(ROLL / f"roll-{k:05d}.json", {"step": k, "adapter": req["adapter"],
                                            "gen_s": round(time.monotonic() - t0, 2), "rows": rows})
        print(json.dumps({"step": k, "gen_s": round(time.monotonic() - t0, 2), "n": len(rows)}), flush=True)
        k += 1


if __name__ == "__main__":
    main()
