"""Path B eval on held-out tasks with one vLLM engine: the base model and any LoRA adapters, Qwen3 non-thinking
sampling (T 0.7, top_p 0.8, top_k 20, one sample per task) and greedy. Writes eval_<label>.json with mean R, a 95%
bootstrap CI, valid rate and the error taxonomy, the reference baselines on the same tasks, and Episode JSON lines.

Env: MODEL, OUT, EVAL_PACK, N (tasks), SETS ("label:adapter_dir_or_-:step:n:decodings;..."), SEED."""

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathb import TIER, prompt_text, score, summarize  # noqa: E402

from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

MODEL = os.environ.get("MODEL", "/home/ubuntu/gs/models/Qwen3-1.7B")
MODEL_ID = "Qwen/Qwen3-1.7B"
OUT = Path(os.environ.get("OUT", "/home/ubuntu/gs/runs/eval"))
N = int(os.environ.get("N", "200"))
SEED = int(os.environ.get("SEED", "0"))
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "512"))
TRAINED = os.environ.get("BASE_TRAINED", "base")
DECODE = {"sampled": dict(temperature=0.7, top_p=0.8, top_k=20), "greedy": dict(temperature=0.0)}
BASELINES = ("greedy", "threshold", "clock", "random")


def eval_tasks() -> list[dict]:
    """N foresight tasks from the eval pack, a fixed seeded sample (the first 50 are the checkpoint subset)."""
    tasks = [t for t in load_pack(os.environ.get("EVAL_PACK", "ercot-dam-v1-eval"))]
    rng = np.random.default_rng(20251)
    idx = rng.permutation(len(tasks))[:N]
    return [tasks[i] for i in idx]


def start_state(task: dict) -> str:
    b = task["battery"]
    return "empty" if b["s0"] == 0 else "full" if b["s0"] == b["soc_levels"] else "half"


def ci(xs, n=10_000, seed=0) -> list[float]:
    xs = np.asarray(xs, dtype=float)
    rng = np.random.default_rng(seed)
    means = xs[rng.integers(0, len(xs), (n, len(xs)))].mean(axis=1)
    return [round(float(np.percentile(means, 2.5)), 4), round(float(np.percentile(means, 97.5)), 4)]


def baselines(tasks: list[dict]) -> dict:
    out = {}
    for name in BASELINES:
        rs = [t["refs"]["foresight"]["baselines"][name]["reward"] for t in tasks]
        out[name] = {"reward_mean": round(float(np.mean(rs)), 4), "ci95": ci(rs)}
    out["idle"] = {"reward_mean": 0.2, "ci95": [0.2, 0.2]}
    out["dp"] = {"reward_mean": 1.0, "ci95": [1.0, 1.0]}
    return out


def run_set(llm, tok, tasks, label, adapter, step, decoding, lora_id) -> dict:
    prompts = [prompt_text(tok, t) for t in tasks]
    params = SamplingParams(max_tokens=MAX_TOKENS, seed=SEED, **DECODE[decoding])
    lora = LoRARequest(label, lora_id, adapter) if adapter else None
    t0 = time.monotonic()
    outs = llm.generate(prompts, params, lora_request=lora, use_tqdm=False)
    wall = time.monotonic() - t0
    recs, eps = [], []
    for t, o in zip(tasks, outs, strict=True):
        c = o.outputs[0]
        r = score(t, c.text, truncated=c.finish_reason == "length")
        r.update(len=len(c.token_ids), task_id=t["task_id"])
        recs.append(r)
        steps = None if r["valid"] else []
        eps.append(to_episode_json(t, r.get("args"), TIER, 0, steps=steps, bundle="oneshot", path="B",
                                   model=MODEL_ID, trained=TRAINED if not adapter else "grpo", checkpoint_step=step,
                                   seed=SEED if decoding == "sampled" else None,
                                   messages=[{"role": "assistant", "content": c.text}],
                                   usage={"input_tokens": len(o.prompt_token_ids), "output_tokens": len(c.token_ids),
                                          "usd": 0.0},
                                   wall_seconds=round(wall / len(tasks), 4)))
    ep_dir = OUT / "episodes"
    ep_dir.mkdir(parents=True, exist_ok=True)
    with (ep_dir / f"{label}-{decoding}.jsonl").open("w") as f:
        for e in eps:
            f.write(json.dumps(e) + "\n")
    s = summarize(recs)
    s["ci95"] = ci([r["reward"] for r in recs])
    for name, key in (("by_start", start_state), ("by_curriculum", lambda t: t.get("curriculum"))):
        groups: dict = {}
        for t, r in zip(tasks, recs, strict=True):
            groups.setdefault(key(t), []).append(r["reward"])
        s[name] = {k: {"n": len(v), "reward_mean": round(float(np.mean(v)), 4), "ci95": ci(v)}
                   for k, v in sorted(groups.items())}
    print(json.dumps({"label": label, "decoding": decoding, "step": step, "wall_s": round(wall, 1),
                      **{k: v for k, v in s.items() if k != "by_curriculum"}}), flush=True)
    return {"label": label, "adapter": adapter, "checkpoint_step": step, "decoding": decoding,
            "params": {"max_tokens": MAX_TOKENS, "seed": SEED, **DECODE[decoding]}, "wall_s": round(wall, 1),
            "summary": s,
            "per_task": [{"task_id": r["task_id"], "reward": r["reward"], "valid": r["valid"], "kind": r["kind"],
                          "tool_call": r["tool_call"], "len": r["len"], "actions": r["actions"]} for r in recs]}


def main():
    tasks = eval_tasks()
    tok = AutoTokenizer.from_pretrained(MODEL)
    llm = LLM(model=MODEL, enable_lora=True, max_lora_rank=32, max_loras=1, max_model_len=2048,
              gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.85")), seed=SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    base_refs = baselines(tasks)
    for k, spec in enumerate(s for s in os.environ.get("SETS", "base:-:0:200:sampled,greedy").split(";") if s):
        label, adapter, step, n, decs = spec.split(":")
        sub = tasks[:int(n)]
        res = {"model": MODEL_ID, "pack": os.environ.get("EVAL_PACK", "ercot-dam-v1-eval"), "tier": TIER,
               "bundle": "oneshot", "engine_model": MODEL, "n_tasks": len(sub), "task_ids": [t["task_id"] for t in sub],
               "baselines": base_refs if len(sub) == len(tasks) else baselines(sub), "runs": []}
        for dec in decs.split(","):
            res["runs"].append(run_set(llm, tok, sub, label, None if adapter == "-" else adapter,
                                       int(step), dec, k + 1))
        (OUT / f"eval_{label}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
