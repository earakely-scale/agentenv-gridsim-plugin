"""The Training docs' SFT warm start: LoRA SFT of Qwen3-4B on the published GridSim v1 rows, then the adapter merged
into the base and saved with its tokenizer, for GRPOTrainer to start from."""

import json
import time
from pathlib import Path

from datasets import load_dataset
from peft import LoraConfig
from trl import SFTConfig, SFTTrainer

STARTED = time.monotonic()

trainer = SFTTrainer(
    model="Qwen/Qwen3-4B",
    args=SFTConfig(
        output_dir="sft",
        num_train_epochs=1,
        max_length=2048,
        per_device_train_batch_size=8,
        learning_rate=1e-4,
        lr_scheduler_type="cosine",
        warmup_steps=0.1,
        bf16=True,
        gradient_checkpointing=True,
        logging_steps=10,
        save_strategy="no",
        report_to="none",
        seed=0,
    ),
    train_dataset=load_dataset("earakely-scale/GridSimEnv-AgentEnv", data_files="sft/gridsim-v1/train.jsonl",
                               split="train"),
    peft_config=LoraConfig(r=32, lora_alpha=64, target_modules="all-linear", task_type="CAUSAL_LM"),
)
trainer.train()
trainer.model.merge_and_unload().save_pretrained("qwen3-4b-gridsim-sft")
trainer.processing_class.save_pretrained("qwen3-4b-gridsim-sft")
Path("sft").mkdir(exist_ok=True)
Path("sft/log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))
print(f"SFT done in {time.monotonic() - STARTED:.0f}s", flush=True)
