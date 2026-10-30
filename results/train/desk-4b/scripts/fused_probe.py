"""Peak training memory of one Qwen3.5-9B sequence as GRPOTrainer trains it in TRL 1.16: bf16 weights, LoRA r 32 on
every linear layer but the vision tower, gradient checkpointing, and TRL's fused LM head (`add_fused_lm_head`), which
scores the completion's log-probs in tiles without the full logits. Sequences are desk-shaped: an 8k prompt, the rest
completion. First, the fused log-probs against plain `log_softmax` of the full logits on a short sequence. OFFLOAD=1
keeps the tensors saved for backward (the checkpointed layer inputs) in pinned CPU memory.

    python fused_probe.py MODEL_DIR OUT.json 32768 65536 98304
"""

import contextlib
import json
import os
import sys
import time

import torch
import transformers
from peft import LoraConfig, get_peft_model
from trl.trainer.utils import add_fused_lm_head

PROMPT = 8192
TEMPERATURE = 0.8
path, out_path, lengths = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3:]]
config = transformers.AutoConfig.from_pretrained(path)
model = getattr(transformers, config.architectures[0]).from_pretrained(path, dtype=torch.bfloat16).cuda()
model.gradient_checkpointing_enable()
model.config.use_cache = False
model = get_peft_model(model, LoraConfig(r=32, lora_alpha=64, target_modules="all-linear",
                                         exclude_modules=r".*visual.*", task_type="CAUSAL_LM"))
add_fused_lm_head(model.get_base_model(), temperature=TEMPERATURE, outputs=("log_probs", "entropy"))
model.enable_input_require_grads()
result = {"class": type(model.get_base_model()).__name__,
          "attn": model.get_base_model().config._attn_implementation,
          "loaded_gib": round(torch.cuda.memory_allocated() / 2**30, 2),
          "total_gib": round(torch.cuda.get_device_properties(0).total_memory / 2**30, 2)}
print(result, flush=True)


def batch(n: int) -> tuple[torch.Tensor, torch.Tensor]:
    ids = torch.randint(0, 240000, (1, n), device="cuda")
    labels = ids.clone()
    labels[:, :min(PROMPT, n // 2)] = -100
    return ids, labels


torch.manual_seed(0)
model.eval()
with torch.no_grad():
    ids, labels = batch(2048)
    fused = model(input_ids=ids, labels=labels, fused_lm_head=True).log_probs[0]
    logits = model(input_ids=ids).logits[0, :-1].float() / TEMPERATURE
    plain = torch.log_softmax(logits, -1).gather(-1, ids[0, 1:, None]).squeeze(-1)
    mask = labels[0, 1:] != -100
    diff = (fused[mask] - plain[mask]).abs()
    result["agreement"] = {"tokens": int(mask.sum()), "max_abs": float(diff.max()), "mean_abs": float(diff.mean()),
                           "mean_logp": float(plain[mask].mean())}
    print("agreement", result["agreement"], flush=True)
    del logits, plain, fused
model.train()
result["peaks"] = []
for n in lengths:
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    ids, labels = batch(n)
    started = time.time()
    offload = torch.autograd.graph.save_on_cpu(pin_memory=True) if os.environ.get("OFFLOAD") == "1" else (
        contextlib.nullcontext())
    try:
        with offload:
            out = model(input_ids=ids, labels=labels, fused_lm_head=True)
            mask = labels[:, 1:] != -100
            loss = -(out.log_probs * mask).sum() / mask.sum()
        forward_gib = round(torch.cuda.max_memory_allocated() / 2**30, 2)
        loss.backward()
        model.zero_grad(set_to_none=True)
        row = {"tokens": n, "completion": int(mask.sum()), "forward_peak_gib": forward_gib,
               "peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2),
               "reserved_gib": round(torch.cuda.max_memory_reserved() / 2**30, 2), "s": round(time.time() - started, 1)}
    except torch.OutOfMemoryError:
        row = {"tokens": n, "oom_at_gib": round(torch.cuda.max_memory_allocated() / 2**30, 2)}
    out = loss = None
    result["peaks"].append(row)
    print(row, flush=True)
    if "oom_at_gib" in row:
        break
json.dump(result, open(out_path, "w"), indent=1)
