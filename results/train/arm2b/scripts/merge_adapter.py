"""Merge a LoRA adapter into its base and save the merged model (the starting policy of a continuation)."""

import os

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

BASE, ADAPTER, OUT = os.environ["BASE"], os.environ["ADAPTER"], os.environ["OUT"]
model = AutoModelForCausalLM.from_pretrained(BASE, dtype=torch.bfloat16)
merged = PeftModel.from_pretrained(model, ADAPTER).merge_and_unload()
merged.save_pretrained(OUT)
AutoTokenizer.from_pretrained(BASE).save_pretrained(OUT)
print(f"merged {ADAPTER} into {BASE} -> {OUT}", flush=True)
