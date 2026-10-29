"""Registered run 4's GPT-6.1 Sol arm: one Responses request per blind task with exactly the 4B's prompt (the blind
path-B prompt + the forecast-first paragraph, the submit_schedule tool, no checks), reasoning effort high, scored by
pathb_blind.score (gridsim_core.trl.extract_actions then grade), as the 4B is. Adapted from
results/fresh/2026-10/scripts/sol_eval.py.

usage: sol_blind.py PACK OUT_DIR --base-url-file FILE [--cap USD] [--concurrency N]. The endpoint is read from the
`LITELLM_BASE_URL=` line of FILE and the key from SSM inside this process; neither is printed or written. Resumable:
tasks already in OUT_DIR/sol-PACK.jsonl are skipped; --spent USD adds earlier spend to the cap."""

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import boto3
import openai

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pathb_blind import graded  # noqa: E402

from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.forecast_line import parse_forecast  # noqa: E402
from gridsim_core.prompt import situation_text, system_prompt, tool_schemas  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402
from gridsim_core.trl import extract_actions  # noqa: E402

MODEL, EFFORT, MAX_OUT = "openai/gpt-6.1-sol", "high", 16384
PRICE = (2.00, 10.00, 0.10)  # USD per 1M input, output, cached input: LiteLLM public price map, as the board used


def cost(u: dict) -> float:
    return ((u["input"] - u["cached"]) * PRICE[0] + u["cached"] * PRICE[2] + u["output"] * PRICE[1]) / 1e6


def request(task: dict, tier: str = "blind") -> dict:
    tools = [{"type": "function", "name": f["function"]["name"], "description": f["function"]["description"],
              "parameters": f["function"]["parameters"]} for f in tool_schemas(tier, 0)]
    return {"model": MODEL, "instructions": system_prompt(task, tier, 0, forecast=True), "tools": tools,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": situation_text(task, tier, 0)}]}],
            "max_output_tokens": MAX_OUT, "reasoning": {"effort": EFFORT, "summary": "auto"}, "store": False,
            "stream": True}


async def call(client, req: dict):
    resp = None
    async for ev in await client.responses.create(**req):
        if ev.type in ("response.completed", "response.incomplete"):
            resp = ev.response
        elif ev.type in ("response.failed", "error"):
            raise RuntimeError(f"{ev.type}: {getattr(ev, 'message', None) or getattr(ev.response, 'error', None)}")
    if resp is None:
        raise RuntimeError("stream ended without a response")
    return resp


def score(task: dict, resp) -> dict:
    text, reasoning, calls = "", "", []
    for item in resp.output:
        if item.type == "message":
            text += "".join(getattr(c, "text", "") for c in item.content)
        elif item.type == "reasoning":
            reasoning += "\n".join(getattr(s, "text", "") for s in (getattr(item, "summary", None) or []))
        elif item.type == "function_call":
            calls.append({"function": {"name": item.name, "arguments": item.arguments or ""}})
    sent = extract_actions({"role": "assistant", "content": text, "tool_calls": calls})
    tc = any(c["function"]["name"] == "submit_schedule" and "actions" in _loads(c["function"]["arguments"])
             for c in calls)
    u = resp.usage
    usage = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
             "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "reasoning": getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0}
    rec = {"status": resp.status, "tool_call": tc, "usage": usage, "usd": round(cost(usage), 6), "text": text,
           "reasoning_summary": reasoning, "calls": calls}
    r = graded(task, sent, parse_forecast(text), tc, resp.status == "incomplete")
    return rec | {k: r.get(k) for k in ("reward", "c", "valid", "kind", "actions", "args", "grade", "forecast", "c_f",
                                        "c_dp_own", "is_dp_own")}


def _loads(s: str) -> dict:
    try:
        v = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return v if isinstance(v, dict) else {}


def worst(task: dict, tier: str = "blind") -> float:
    n_in = (len(system_prompt(task, tier, 0, True)) + len(situation_text(task, tier, 0))) // 2 + 500
    return cost({"input": n_in, "cached": 0, "output": MAX_OUT})


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pack")
    ap.add_argument("out")
    ap.add_argument("--base-url-file", required=True)
    ap.add_argument("--cap", type=float, default=20.0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--spent", type=float, default=0.0)
    a = ap.parse_args()
    base = re.search(r"LITELLM_BASE_URL=[\"']?([^\s\"']+)", Path(a.base_url_file).read_text()).group(1)
    key = boto3.Session(profile_name="agent-environments-admin", region_name="us-west-2").client("ssm").get_parameter(
        Name="/gridsim/litellm-key", WithDecryption=True)["Parameter"]["Value"]
    client = openai.AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=900.0)
    tasks = [t for t in load_pack(a.pack) if t["tags"]["blind_eval"]]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    name = Path(a.pack).name
    log, eps = out / f"sol-{name}.jsonl", out / f"sol-{name}-episodes.jsonl"
    done = {json.loads(x)["task_id"] for x in log.read_text().splitlines()} if log.exists() else set()
    spent = a.spent + (sum(json.loads(x).get("usd", 0.0) for x in log.read_text().splitlines()) if log.exists()
                       else 0.0)
    todo = [t for t in tasks if t["task_id"] not in done][: a.limit or None]
    state = {"spent": spent, "inflight": 0.0, "skipped": []}
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()
    print(f"{len(tasks)} tasks, {len(done)} done, {len(todo)} to run, spent ${spent:.4f}", flush=True)

    async def one(t):
        async with sem:
            w = worst(t)
            async with lock:
                if state["spent"] + state["inflight"] + w > a.cap:
                    state["skipped"].append(t["task_id"])
                    return
                state["inflight"] += w
            t0, err, resp = time.monotonic(), None, None
            for attempt in range(4):
                try:
                    resp = await call(client, request(t))
                    break
                except Exception as e:  # noqa: BLE001
                    err = f"{type(e).__name__}: {str(e)[:300]}"
                    await asyncio.sleep(5 * (attempt + 1))
            wall = round(time.monotonic() - t0, 2)
            rec = {"task_id": t["task_id"], "date": t["date"], "tier": "blind", "wall_s": wall}
            if resp is None:
                rec |= {"reward": 0.0, "c": 0.0, "valid": False, "kind": "error", "error": err, "usd": 0.0,
                        "usage": None, "tool_call": False, "actions": None, "forecast": None}
            else:
                rec |= score(t, resp)
            async with lock:
                state["inflight"] -= w
                state["spent"] += rec["usd"]
                g = rec.pop("grade", None)
                args = rec.pop("args", None)
                with log.open("a") as f:
                    f.write(json.dumps(rec | {"grade": g}) + "\n")
                if resp is not None:
                    ep = to_episode_json(t, args, "blind", 0, bundle="oneshot", path="B", model=MODEL,
                                         messages=[{"role": "assistant", "content": rec["text"],
                                                    "tool_calls": rec["calls"]}],
                                         usage={"input_tokens": rec["usage"]["input"],
                                                "output_tokens": rec["usage"]["output"], "usd": rec["usd"]},
                                         wall_seconds=wall)
                    with eps.open("a") as f:
                        f.write(json.dumps(ep) + "\n")
                print(f"{t['task_id']} C {rec['c']:.4f} {rec['kind']} fc {rec['forecast'] is not None} "
                      f"${rec['usd']:.4f} {wall}s "
                      f"total ${state['spent']:.3f}", flush=True)

    await asyncio.gather(*(one(t) for t in todo))
    print(json.dumps({"spent_usd": round(state["spent"], 4), "skipped_by_cap": state["skipped"]}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
