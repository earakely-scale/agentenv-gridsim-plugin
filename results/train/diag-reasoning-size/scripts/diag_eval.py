"""Diagnostic eval: one vLLM engine per model, the oneshot prompt with thinking on or off, one sample per task,
graded by pathb.score (gridsim_core.trl.reward_fn's extraction, which drops <think> blocks, then grade).

Env: MODEL, MODEL_ID, REVISION, TRAINED, OUT, N, SEED, VLLM_UTIL, MAX_MODEL_LEN,
SETS ("label:think(0|1):max_tokens:decoding;...", decoding in DECODE)."""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evaluate import baselines, ci, eval_tasks, start_state  # noqa: E402
from pathb import CHECKS, TIER, prompt_text, score, summarize  # noqa: E402

from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.prompt import messages, tool_schemas  # noqa: E402

MODEL = os.environ["MODEL"]
MODEL_ID = os.environ["MODEL_ID"]
OUT = Path(os.environ["OUT"])
SEED = int(os.environ.get("SEED", "0"))
TRAINED = os.environ.get("TRAINED", "base")
DECODE = {"sampled": dict(temperature=0.7, top_p=0.8, top_k=20),
          "qwen_think": dict(temperature=0.6, top_p=0.95, top_k=20)}
END_THINK = "</think>"


def prompt(tok, task: dict, think: bool) -> str:
    p = tok.apply_chat_template(messages(task, TIER, CHECKS), tools=tool_schemas(TIER, CHECKS), tokenize=False,
                                add_generation_prompt=True, enable_thinking=think)
    assert think or p == prompt_text(tok, task)
    return p


def think_tokens(tok, text: str) -> int:
    i = text.find(END_THINK)
    return len(tok(text[:i + len(END_THINK)], add_special_tokens=False).input_ids) if i >= 0 else 0


def run_set(llm, tok, tasks, label, think, max_tokens, decoding) -> dict:
    prompts = [prompt(tok, t, think) for t in tasks]
    params = SamplingParams(max_tokens=max_tokens, seed=SEED, **DECODE[decoding])
    t0 = time.monotonic()
    outs = llm.generate(prompts, params, use_tqdm=False)
    wall = time.monotonic() - t0
    recs, eps = [], []
    for t, o in zip(tasks, outs, strict=True):
        c = o.outputs[0]
        r = score(t, c.text, truncated=c.finish_reason == "length")
        closed = END_THINK in c.text
        r.update(len=len(c.token_ids), task_id=t["task_id"], finish=c.finish_reason, think_closed=closed,
                 think_len=think_tokens(tok, c.text) if think else 0,
                 trunc_in_think=think and c.finish_reason == "length" and not closed)
        recs.append(r)
        eps.append(to_episode_json(t, r.get("args"), TIER, 0, steps=None if r["valid"] else [], bundle="oneshot",
                                   path="B", model=MODEL_ID, trained=TRAINED, checkpoint_step=0, seed=SEED,
                                   messages=[{"role": "assistant", "content": c.text}],
                                   usage={"input_tokens": len(o.prompt_token_ids), "output_tokens": len(c.token_ids),
                                          "usd": 0.0},
                                   wall_seconds=round(wall / len(tasks), 4)))
    ep_dir = OUT / "episodes"
    ep_dir.mkdir(parents=True, exist_ok=True)
    with (ep_dir / f"{label}.jsonl").open("w") as f:
        f.writelines(json.dumps(e) + "\n" for e in eps)
    s = summarize(recs)
    lens = np.array([r["len"] for r in recs])
    s.update(ci95=ci([r["reward"] for r in recs]), completion_len_p50=float(np.median(lens)),
             completion_len_p90=float(np.percentile(lens, 90)),
             hit_cap_rate=round(float((lens >= max_tokens).mean()), 4),
             think_closed_rate=round(float(np.mean([r["think_closed"] for r in recs])), 4) if think else None,
             think_len_mean=round(float(np.mean([r["think_len"] for r in recs])), 1) if think else None,
             rate_trunc_in_think=round(float(np.mean([r["trunc_in_think"] for r in recs])), 4),
             exact_optima=int(sum(r["reward"] >= 0.99 for r in recs)))
    groups: dict = {}
    for t, r in zip(tasks, recs, strict=True):
        groups.setdefault(start_state(t), []).append(r["reward"])
    s["by_start"] = {k: {"n": len(v), "reward_mean": round(float(np.mean(v)), 4)} for k, v in sorted(groups.items())}
    print(json.dumps({"label": label, "wall_s": round(wall, 1), **{k: v for k, v in s.items() if k != "by_start"}}),
          flush=True)
    return {"label": label, "think": think, "decoding": decoding,
            "params": {"max_tokens": max_tokens, "seed": SEED, "enable_thinking": think, **DECODE[decoding]},
            "wall_s": round(wall, 1), "prompts_sha256": hashlib.sha256("\n".join(prompts).encode()).hexdigest(),
            "prompt_len_mean": round(float(np.mean([len(o.prompt_token_ids) for o in outs])), 1), "summary": s,
            "per_task": [{"task_id": r["task_id"], "reward": r["reward"], "valid": r["valid"], "kind": r["kind"],
                          "tool_call": r["tool_call"], "len": r["len"], "finish": r["finish"],
                          "think_closed": r["think_closed"], "think_len": r["think_len"], "actions": r["actions"]}
                         for r in recs]}


def main():
    tasks = eval_tasks()
    tok = AutoTokenizer.from_pretrained(MODEL)
    llm = LLM(model=MODEL, max_model_len=int(os.environ.get("MAX_MODEL_LEN", "6144")),
              gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.92")), seed=SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    for spec in (s for s in os.environ["SETS"].split(";") if s):
        label, think, max_tokens, decoding = spec.split(":")
        res = {"model": MODEL_ID, "revision": os.environ.get("REVISION"), "trained": TRAINED, "engine_model": MODEL,
               "pack": os.environ.get("EVAL_PACK", "ercot-dam-v1-eval"), "tier": TIER, "bundle": "oneshot",
               "n_tasks": len(tasks), "task_ids": [t["task_id"] for t in tasks], "baselines": baselines(tasks),
               "runs": [run_set(llm, tok, tasks, label, think == "1", int(max_tokens), decoding)]}
        (OUT / f"eval_{label}.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
