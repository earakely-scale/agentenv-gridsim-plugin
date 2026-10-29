"""Merge the SFT-10k LoRA into the base the way scripts/sft.py did (bf16 on the GPU, merge_and_unload)."""

import sys

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base, adapter, out = sys.argv[1:4]
model = AutoModelForCausalLM.from_pretrained(base, dtype=torch.bfloat16).cuda()
PeftModel.from_pretrained(model, adapter).merge_and_unload().save_pretrained(out)
AutoTokenizer.from_pretrained(base).save_pretrained(out)
print(f"merged {adapter} -> {out}", flush=True)
