"""Registered run 4's path-B eval: one vLLM engine on MODEL, any LoRA adapters, the forecast-then-plan blind prompt,
Qwen3 non-thinking sampling (T 0.7, top_p 0.8, top_k 20, seed 0) and greedy decoding, max_tokens 768. Every task of
each pack, once per decoding. Writes OUT/eval_<label>.json (per task: C, R, actions, the written forecast and the plan
diagnostics) and OUT/episodes/<label>-<pack>-<decoding>.jsonl (gridsim.episode/v1).

Env: MODEL, MODEL_ID, OUT, SETS ("label:adapter_dir_or_-:step:pack+pack:decoding,decoding;..."), HOLDOUT (json),
TRAINED, VLLM_UTIL, MAX_TOKENS."""

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
from pathb_blind import TIER, prompt_text, score, summarize  # noqa: E402

from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

MODEL = os.environ["MODEL"]
MODEL_ID = os.environ.get("MODEL_ID", "Qwen/Qwen3-4B")
OUT = Path(os.environ["OUT"])
SEED = 0
MAX_TOKENS = int(os.environ.get("MAX_TOKENS", "768"))
DECODE = {"sampled": dict(temperature=0.7, top_p=0.8, top_k=20), "greedy": dict(temperature=0.0)}


def packs() -> dict:
    blind = lambda ts: [t for t in ts if t["tags"].get("blind_eval")]  # noqa: E731
    out = {"eval2025": blind(load_pack("ercot-dam-v1-eval")),
           "fresh": blind(load_pack("ercot-dam-v1-fresh-2026-10-blind"))}
    if os.environ.get("HOLDOUT"):
        ids = json.loads(Path(os.environ["HOLDOUT"]).read_text())["task_ids"]
        train = {t["task_id"]: t for t in load_pack("ercot-dam-v1-train")}
        out["holdout2024"] = [train[i] for i in ids]
    return out


def run_set(llm, tok, tasks, label, pack, adapter, step, decoding, lora_id) -> dict:
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
        r.update(len=len(c.token_ids), task_id=t["task_id"], date=t["date"])
        recs.append(r)
        eps.append(to_episode_json(t, r.get("args"), TIER, 0, steps=None if r["valid"] else [], bundle="oneshot",
                                   path="B", model=MODEL_ID, trained=os.environ.get("TRAINED", "base"),
                                   checkpoint_step=step, seed=SEED if decoding == "sampled" else None,
                                   messages=[{"role": "assistant", "content": c.text}],
                                   usage={"input_tokens": len(o.prompt_token_ids), "output_tokens": len(c.token_ids),
                                          "usd": 0.0}, wall_seconds=round(wall / len(tasks), 4)))
    (OUT / "episodes").mkdir(parents=True, exist_ok=True)
    with (OUT / "episodes" / f"{label}-{pack}-{decoding}.jsonl").open("w") as f:
        for e in eps:
            f.write(json.dumps(e) + "\n")
    s = summarize(recs)
    print(json.dumps({"label": label, "pack": pack, "decoding": decoding, "step": step, "wall_s": round(wall, 1),
                      **s}), flush=True)
    keep = ("task_id", "date", "c", "reward", "valid", "kind", "tool_call", "len", "actions", "forecast", "c_f",
            "c_dp_own", "is_dp_own")
    return {"label": label, "pack": pack, "adapter": adapter, "checkpoint_step": step, "decoding": decoding,
            "params": {"max_tokens": MAX_TOKENS, "seed": SEED, **DECODE[decoding]}, "wall_s": round(wall, 1),
            "summary": s, "per_task": [{k: r.get(k) for k in keep} for r in recs]}


def main():
    sets = [s for s in os.environ["SETS"].split(";") if s]
    tok = AutoTokenizer.from_pretrained(MODEL)
    llm = LLM(model=MODEL, enable_lora=True, max_lora_rank=32, max_loras=1, max_model_len=4096, seed=SEED,
              gpu_memory_utilization=float(os.environ.get("VLLM_UTIL", "0.85")))
    OUT.mkdir(parents=True, exist_ok=True)
    all_packs = packs()
    for k, spec in enumerate(sets):
        label, adapter, step, names, decs = spec.split(":")
        res = {"model": MODEL_ID, "engine_model": MODEL, "tier": TIER, "prompt": "blind path B + forecast note",
               "runs": []}
        for name in names.split("+"):
            for dec in decs.split(","):
                res["runs"].append(run_set(llm, tok, all_packs[name], label, name, None if adapter == "-" else adapter,
                                           int(step), dec, k + 1))
        res["c_means"] = {f"{r['pack']}-{r['decoding']}": r["summary"]["c_mean"] for r in res["runs"]}
        res["task_ids"] = {n: [t["task_id"] for t in all_packs[n]] for n in names.split("+")}
        (OUT / f"eval_{label}.json").write_text(json.dumps(res) + "\n")
        print(json.dumps({"label": label, "c_means": res["c_means"],
                          "ci_eval2025": ci([r["c"] for r in res["runs"][0]["per_task"]])}), flush=True)


def ci(xs, n=2000) -> list[float]:
    xs = np.asarray(xs, float)
    m = xs[np.random.default_rng(0).integers(0, len(xs), (n, len(xs)))].mean(1)
    return [round(float(np.percentile(m, 2.5)), 4), round(float(np.percentile(m, 97.5)), 4)]


if __name__ == "__main__":
    main()
