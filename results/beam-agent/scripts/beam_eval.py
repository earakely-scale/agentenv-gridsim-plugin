"""Beam (reflection/Beam-1.0-501B-A23B on Baseten through the Hugging Face router) under the prompt, tool and scoring
Sol, Luna and the 4B got on the blind packs; only the API shape (Chat Completions), the model, the effort, max_tokens
and the price differ.

usage: beam_eval.py OUT_DIR --effort E [--cap USD] [--later N] [--concurrency N] [--limit N] [--pack PACK]
The HF token is read from ~/.cache/huggingface/token inside this process and never printed or written. Spend is
summed over every beam-*.jsonl in OUT_DIR before each request. Resumable."""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

import openai

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "results/train/4b-blind/scripts"))
from pathb_blind import graded  # noqa: E402

from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.forecast import parse_forecast  # noqa: E402
from gridsim_core.prompt import situation_text, system_prompt, tool_schemas  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402
from gridsim_core.trl import extract_actions  # noqa: E402

MODEL, ROUTE = "reflection/Beam-1.0-501B-A23B", "reflection/Beam-1.0-501B-A23B:baseten"
BASE = "https://router.huggingface.co/v1"
PRICE = (0.40, 1.20)  # USD per 1M input, output: Baseten on the HF router, 2026-10-27
PACK, ATTEMPTS = "ercot-dam-v1-fresh-2026-10-blind", 3


def max_tokens(effort: str) -> int:
    return 65536 if effort == "max" else 32768


def cost(u: dict) -> float:
    return (u["input"] * PRICE[0] + u["output"] * PRICE[1]) / 1e6


def request(task: dict, effort: str) -> dict:
    return {"model": ROUTE, "messages": [{"role": "system", "content": system_prompt(task, "blind", 0, forecast=True)},
                                         {"role": "user", "content": situation_text(task, "blind", 0)}],
            "tools": tool_schemas("blind", 0), "max_tokens": max_tokens(effort), "reasoning_effort": effort}


def worst(task: dict, effort: str) -> float:
    n_in = (len(system_prompt(task, "blind", 0, True)) + len(situation_text(task, "blind", 0))) // 2 + 500
    return cost({"input": n_in, "output": max_tokens(effort)})


def score(task: dict, resp) -> dict:
    ch = resp.choices[0]
    m = ch.message.model_dump()
    text = m.get("content") or ""
    calls = [{"function": {"name": c["function"]["name"], "arguments": c["function"]["arguments"] or ""}}
             for c in m.get("tool_calls") or []]
    sent = extract_actions({"role": "assistant", "content": text, "tool_calls": calls})
    tc = any(c["function"]["name"] == "submit_schedule" and "actions" in _loads(c["function"]["arguments"])
             for c in calls)
    u = resp.usage
    usage = {"input": u.prompt_tokens or 0, "output": u.completion_tokens or 0,
             "reasoning": getattr(u.completion_tokens_details, "reasoning_tokens", 0) or 0}
    rec = {"finish_reason": ch.finish_reason, "tool_call": tc, "usage": usage, "usd": round(cost(usage), 8),
           "text": text, "reasoning": m.get("reasoning_content") or "", "calls": calls}
    r = graded(task, sent, parse_forecast(text), tc, ch.finish_reason == "length")
    return rec | {k: r.get(k) for k in ("reward", "c", "valid", "kind", "actions", "args", "grade", "forecast", "c_f",
                                        "c_dp_own", "is_dp_own")}


def _loads(s: str) -> dict:
    try:
        v = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return v if isinstance(v, dict) else {}


def rows(p: Path) -> list[dict]:
    out = []
    for x in p.read_text().splitlines() if p.exists() else []:
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            pass
    return out


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--effort", required=True, choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--cap", type=float, default=30.0)
    ap.add_argument("--later", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pack", help="override the pack (the smoke uses the fixtures)")
    a = ap.parse_args()
    token = (Path.home() / ".cache/huggingface/token").read_text().strip()
    client = openai.AsyncOpenAI(base_url=BASE, api_key=token, max_retries=0, timeout=1800.0)
    tasks = [t for t in load_pack(a.pack or PACK) if t["tags"].get("blind_eval")]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"blind-fresh-{a.effort}" + ("-smoke" if a.pack else "")
    log, eps = out / f"beam-{tag}.jsonl", out / f"beam-{tag}-episodes.jsonl"
    done = {r["task_id"] for r in rows(log)}
    lane = lambda: sum(r.get("usd", 0.0) for p in out.glob("beam-*.jsonl")  # noqa: E731
                       if not p.name.endswith("-episodes.jsonl") for r in rows(p))
    todo = [t for t in tasks if t["task_id"] not in done][: a.limit or None]
    st = {"inflight": 0.0, "run_usd": 0.0, "run_n": 0, "started": 0, "skipped": [], "stop": None}
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()
    print(f"{tag}: {len(tasks)} tasks, {len(done)} done, {len(todo)} to run, lane spend ${lane():.4f}", flush=True)

    async def one(t):
        async with sem:
            w = worst(t, a.effort)
            async with lock:
                now = lane()
                if st["run_n"] >= 25:
                    proj = now + st["run_usd"] / st["run_n"] * (len(todo) - st["started"] + a.later)
                    if proj > a.cap:
                        st["stop"] = st["stop"] or f"projection ${proj:.2f} > cap ${a.cap:g}"
                if st["stop"] or now + st["inflight"] + w > a.cap:
                    st["skipped"].append(t["task_id"])
                    return
                st["inflight"] += w
                st["started"] += 1
            t0, errors, resp = time.monotonic(), [], None
            for attempt in range(ATTEMPTS):
                try:
                    resp = await client.chat.completions.create(**request(t, a.effort))
                    break
                except openai.APIStatusError as e:
                    errors.append(f"{e.status_code}: {str(e.message).replace(token, '<token>')[:300]}")
                    if e.status_code == 429 and e.response.headers.get("x-should-retry") == "false":
                        st["stop"] = st["stop"] or "429 with x-should-retry: false"
                        break
                    wait = float(e.response.headers.get("retry-after") or 10 * (attempt + 1))
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{type(e).__name__}: {str(e).replace(token, '<token>')[:300]}")
                    wait = 10 * (attempt + 1)
                if attempt + 1 < ATTEMPTS:
                    await asyncio.sleep(min(wait, 120))
            wall = round(time.monotonic() - t0, 2)
            rec = {"task_id": t["task_id"], "date": t["date"], "tier": "blind", "model": MODEL, "effort": a.effort,
                   "wall_s": wall, "attempts": len(errors) + (resp is not None), "infra_errors": errors}
            if resp is None:
                rec |= {"reward": 0.0, "c": 0.0, "valid": False, "kind": "error", "usd": 0.0, "usage": None,
                        "tool_call": False, "actions": None}
            else:
                rec |= score(t, resp)
            async with lock:
                st["inflight"] -= w
                st["run_usd"] += rec["usd"]
                st["run_n"] += 1
                g, args = rec.pop("grade", None), rec.pop("args", None)
                with log.open("a") as f:
                    f.write(json.dumps(rec | {"grade": g}) + "\n")
                if resp is not None:
                    ep = to_episode_json(t, args, "blind", 0, bundle="oneshot", path="B", model=MODEL,
                                         messages=[{"role": "assistant", "content": rec["text"],
                                                    "reasoning_content": rec["reasoning"], "tool_calls": rec["calls"]}],
                                         usage={"input_tokens": rec["usage"]["input"],
                                                "output_tokens": rec["usage"]["output"], "usd": rec["usd"]},
                                         wall_seconds=wall)
                    with eps.open("a") as f:
                        f.write(json.dumps(ep) + "\n")
                print(f"{t['task_id']} C {rec['c']:.4f} {rec['kind']} ${rec['usd']:.5f} "
                      f"out {(rec['usage'] or {}).get('output')} {rec.get('finish_reason')} {wall}s "
                      f"try {rec['attempts']} lane ${lane():.4f}", flush=True)

    await asyncio.gather(*(one(t) for t in todo))
    print(json.dumps({"effort": a.effort, "lane_spent_usd": round(lane(), 5), "run_usd": round(st["run_usd"], 5),
                      "run_n": st["run_n"], "stopped": st["stop"], "skipped": len(st["skipped"])}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
