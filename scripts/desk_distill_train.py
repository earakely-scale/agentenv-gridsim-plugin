"""SFT of Qwen3.5-9B (thinking on, LoRA) with TRL's SFTTrainer on the anchor's OpenCode rows (desk_distill_sft.py):
one row a wake, the exact request OpenCode sent for the wake's last turn, loss on the wake's assistant turns only.

Rows run to about 136k tokens, so the trainer keeps what the forward saves for backward in pinned CPU memory and
applies the 248k-vocabulary LM head only where a token is trained, a chunk at a time, never over the whole row. Before
training, one forward and backward on the longest row reports the peak memory; a row is never truncated.

    python scripts/desk_distill_train.py --rows rows.jsonl --model models/Qwen3.5-9B --out out
    python scripts/desk_distill_train.py merge --model models/Qwen3.5-9B --adapter out/adapter --out models/student
"""

from __future__ import annotations

import argparse
import contextlib
import json
import random
import shutil
import sys
import time
from pathlib import Path

import torch
import torch.nn.functional as F
from torch.utils.checkpoint import checkpoint
from datasets import Dataset
from peft import LoraConfig, PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer, TrainerCallback
from trl import SFTConfig, SFTTrainer


def _ce(h: torch.Tensor, t: torch.Tensor, w: torch.Tensor) -> torch.Tensor:
    return F.cross_entropy((h @ w.T).float(), t, reduction="sum")


class DeskSFT(SFTTrainer):
    offload = True
    chunk = 1024

    def compute_loss(self, model, inputs, return_outputs=False, num_items_in_batch=None):
        """The decoder's last hidden states, then the LM head and cross-entropy at the trained positions only, a chunk
        at a time and recomputed in backward, so no row's logits are ever held whole."""
        ids, labels = inputs["input_ids"], inputs["labels"]
        pos = (labels[0, 1:] != -100).nonzero().squeeze(-1)
        base = model.get_base_model() if hasattr(model, "get_base_model") else model
        ctx = torch.autograd.graph.save_on_cpu(pin_memory=True) if self.offload else contextlib.nullcontext()
        with ctx:
            h = base.model(input_ids=ids, use_cache=False).last_hidden_state[0, pos]
        tgt, w = ids[0, pos + 1], base.lm_head.weight
        loss = sum(checkpoint(_ce, h[i:i + self.chunk], tgt[i:i + self.chunk], w, use_reentrant=False)
                   for i in range(0, len(pos), self.chunk))
        loss = loss / (num_items_in_batch if num_items_in_batch is not None else max(len(pos), 1))
        return (loss, None) if return_outputs else loss


class Log(TrainerCallback):
    def __init__(self, path: Path, rows: list[dict]):
        self.path, self.rows, self.t0 = path, rows, time.monotonic()

    def on_log(self, args, state, control, logs=None, **kw):
        rec = {"step": state.global_step, "epoch": state.epoch, "elapsed_s": round(time.monotonic() - self.t0),
               "peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 1), **(logs or {})}
        with self.path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        print(json.dumps(rec), flush=True)


def load_rows(path: Path, max_tokens: int) -> tuple[list[dict], list[dict]]:
    rows = [json.loads(x) for x in path.open()]
    keep = [r for r in rows if r["n"] <= max_tokens]
    return keep, [r for r in rows if r["n"] > max_tokens]


def train(a: argparse.Namespace) -> None:
    rows, dropped = load_rows(a.rows, a.max_tokens)
    random.Random(a.seed).shuffle(rows)
    a.out.mkdir(parents=True, exist_ok=True)
    config = {k: str(v) for k, v in vars(a).items()} | {
        "rows": len(rows), "dropped_over_max_tokens": [(r["session"], r["wake"], r["n"]) for r in dropped],
        "tokens": sum(r["n"] for r in rows), "trained_tokens": sum(r["n_completion"] for r in rows)}
    (a.out / "run_config.json").write_text(json.dumps(config, indent=1))
    print(json.dumps({k: v for k, v in config.items() if k != "dropped_over_max_tokens"}), flush=True)
    ds = Dataset.from_list([{"input_ids": r["input_ids"], "completion_mask": r["completion_mask"]} for r in rows])
    trainer = DeskSFT(
        model=a.model,
        args=SFTConfig(
            output_dir=str(a.out), num_train_epochs=a.epochs, per_device_train_batch_size=1,
            gradient_accumulation_steps=a.grad_accum, learning_rate=a.lr, lr_scheduler_type="cosine",
            warmup_steps=a.warmup, weight_decay=0.0, max_grad_norm=1.0, bf16=True,
            model_init_kwargs={"dtype": torch.bfloat16}, gradient_checkpointing=True,
            gradient_checkpointing_kwargs={"use_reentrant": False}, max_length=None, packing=False,
            completion_only_loss=True, logging_steps=1, save_strategy="steps", save_steps=a.save_steps,
            save_only_model=False, report_to="none", seed=a.seed, dataloader_num_workers=0),
        train_dataset=ds,
        processing_class=AutoTokenizer.from_pretrained(a.model),
        peft_config=LoraConfig(r=a.rank, lora_alpha=2 * a.rank, lora_dropout=0.0, target_modules="all-linear",
                               exclude_modules=r".*visual.*", task_type="CAUSAL_LM"),
        callbacks=[Log(a.out / "log.jsonl", rows)],
    )
    trainer.model_accepts_loss_kwargs = True
    trainer.chunk = a.chunk
    base = trainer.model.get_base_model()
    print(json.dumps({"model_class": type(base).__name__, "trainable": trainer.model.get_nb_trainable_parameters()}),
          flush=True)
    longest = max(range(len(ds)), key=lambda i: len(ds[i]["input_ids"]))
    batch = trainer.data_collator([ds[longest]])
    batch = {k: v.to(trainer.model.device) for k, v in batch.items()}
    torch.cuda.reset_peak_memory_stats()
    t0 = time.monotonic()
    trainer.model.train()
    trainer.compute_loss(trainer.model, batch).backward()
    trainer.model.zero_grad(set_to_none=True)
    probe = {"probe_tokens": len(ds[longest]["input_ids"]), "probe_s": round(time.monotonic() - t0, 1),
             "probe_peak_gib": round(torch.cuda.max_memory_allocated() / 2**30, 1)}
    print(json.dumps(probe), flush=True)
    (a.out / "probe.json").write_text(json.dumps(probe))
    if a.probe_only:
        return
    trainer.train(resume_from_checkpoint=a.resume)
    trainer.save_model(str(a.out / "adapter"))
    (a.out / "log_history.json").write_text(json.dumps(trainer.state.log_history, indent=1))


def merge(a: argparse.Namespace) -> None:
    base = AutoModelForImageTextToText.from_pretrained(a.model, dtype=torch.bfloat16)
    model = PeftModel.from_pretrained(base, str(a.adapter)).merge_and_unload()
    model.save_pretrained(str(a.out))
    for p in Path(a.model).iterdir():
        if p.is_file() and not p.name.startswith("model") and p.suffix in (".json", ".jinja", ".txt", ".model"):
            if p.name not in ("config.json", "generation_config.json") or not (a.out / p.name).exists():
                shutil.copy(p, a.out / p.name)
    print(json.dumps({"merged": str(a.out), "files": sorted(x.name for x in a.out.iterdir())}))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if len(sys.argv) > 1 and sys.argv[1] == "merge":
        ap.add_argument("cmd")
        ap.add_argument("--model", required=True)
        ap.add_argument("--adapter", type=Path, required=True)
        ap.add_argument("--out", type=Path, required=True)
        merge(ap.parse_args())
        return
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--model", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--grad-accum", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--warmup", type=float, default=0.05)
    ap.add_argument("--rank", type=int, default=32)
    ap.add_argument("--max-tokens", type=int, default=150000)
    ap.add_argument("--save-steps", type=int, default=10)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--chunk", type=int, default=1024, help="trained positions per LM-head chunk")
    ap.add_argument("--resume")
    ap.add_argument("--probe-only", action="store_true")
    train(ap.parse_args())


if __name__ == "__main__":
    main()
