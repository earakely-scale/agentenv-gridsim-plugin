"""GPT-6 Luna under exactly the harness Sol and the 4B already used: the request and the scoring are the committed Sol
scripts' own functions (foresight: results/fresh/2026-10/scripts/sol_eval.py; blind: results/train/4b-blind/scripts/
sol_blind.py), imported unchanged; only the model, the reasoning effort and the price differ.

usage: luna_eval.py CONTEST OUT_DIR --base-url-file FILE --effort E [--cap USD] [--later N] [--concurrency N]
CONTEST: foresight-eval2025 | foresight-fresh | blind-eval2025 | blind-fresh. The endpoint is read from the
`LITELLM_BASE_URL=` line of FILE and the key from SSM inside this process; neither is printed or written.
Spend is summed over every luna-*.jsonl in OUT_DIR, re-read before each request, so --cap is the lane's total even
with two runs side by side. A request starts only if spend plus this run's in-flight worst cases plus its own worst
case stays under the cap; from 25 finished tasks on, no request starts once
spend + this run's mean cost x (its unstarted tasks + --later tasks of planned runs) exceeds the cap. An infra failure
(no response) is retried at most twice and recorded; a response is never retried. Resumable."""

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

import boto3
import openai

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from gridsim_core.episode import to_episode_json  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

MODEL = "openai/gpt-6-luna"
PRICE = (0.10, 0.50, 0.01)  # USD per 1M input, output, cached input: agents/gridsim-llm/agent.py's PRICES
ATTEMPTS = 3
CONTESTS = {
    "foresight-eval2025": ("foresight", "ercot-dam-v1-eval", "results/train/4b-dpa/eval_trained.json"),
    "foresight-fresh": ("foresight", "ercot-dam-v1-fresh-2026-10", None),
    "blind-eval2025": ("blind", "ercot-dam-v1-eval", None),
    "blind-fresh": ("blind", "ercot-dam-v1-fresh-2026-10-blind", None),
}
SRC = {"foresight": "results/fresh/2026-10/scripts/sol_eval.py", "blind": "results/train/4b-blind/scripts/sol_blind.py"}


def load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def cost(u: dict) -> float:
    return ((u["input"] - u["cached"]) * PRICE[0] + u["cached"] * PRICE[2] + u["output"] * PRICE[1]) / 1e6


def rows(p: Path) -> list[dict]:
    """A run's records; a line another run is still writing is skipped."""
    out = []
    for x in p.read_text().splitlines() if p.exists() else []:
        try:
            out.append(json.loads(x))
        except json.JSONDecodeError:
            pass
    return out


def tasks_of(contest: str) -> list[dict]:
    tier, pack, ids_from = CONTESTS[contest]
    tasks = load_pack(pack)
    if tier == "blind":
        return [t for t in tasks if t["tags"]["blind_eval"]]
    if ids_from:
        by = {t["task_id"]: t for t in tasks}
        return [by[i] for i in json.loads((ROOT / ids_from).read_text())["task_ids"]]
    return tasks


class Harness:
    def __init__(self, tier: str, effort: str):
        self.tier, self.effort = tier, effort
        self.sol = load(f"sol_{tier}", ROOT / SRC[tier])

    def request(self, task: dict) -> dict:
        req = self.sol.request(task, self.tier) if self.tier == "foresight" else self.sol.request(task)
        return req | {"model": MODEL, "reasoning": req["reasoning"] | {"effort": self.effort}}

    def score(self, task: dict, resp) -> dict:
        rec = self.sol.score(task, self.tier, resp) if self.tier == "foresight" else self.sol.score(task, resp)
        return rec | {"usd": round(cost(rec["usage"]), 8)}

    def worst(self, task: dict) -> float:
        req = self.request(task)
        n_in = (len(req["instructions"]) + len(req["input"][0]["content"][0]["text"])) // 2 + 500
        return cost({"input": n_in, "cached": 0, "output": req["max_output_tokens"]})


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("contest", choices=CONTESTS)
    ap.add_argument("out")
    ap.add_argument("--base-url-file", required=True)
    ap.add_argument("--effort", default="high")
    ap.add_argument("--cap", type=float, default=10.0)
    ap.add_argument("--later", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pack", help="override the contest's pack (the smoke uses the fixtures)")
    a = ap.parse_args()
    tier = CONTESTS[a.contest][0]
    h = Harness(tier, a.effort)
    base = re.search(r"LITELLM_BASE_URL=[\"']?([^\s\"']+)", Path(a.base_url_file).read_text()).group(1)
    key = boto3.Session(profile_name="agent-environments-admin", region_name="us-west-2").client("ssm").get_parameter(
        Name="/gridsim/litellm-key", WithDecryption=True)["Parameter"]["Value"]
    client = openai.AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=900.0)
    tasks = load_pack(a.pack) if a.pack else tasks_of(a.contest)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tag = f"{a.contest}-{a.effort}" + ("-smoke" if a.pack else "")
    log, eps = out / f"luna-{tag}.jsonl", out / f"luna-{tag}-episodes.jsonl"
    done = {r["task_id"] for r in rows(log)}
    lane = lambda: sum(r.get("usd", 0.0) for p in out.glob("luna-*.jsonl")  # noqa: E731
                       if not p.name.endswith("-episodes.jsonl") for r in rows(p))
    spent = lane()
    todo = [t for t in tasks if t["task_id"] not in done][: a.limit or None]
    st = {"inflight": 0.0, "run_usd": 0.0, "run_n": 0, "started": 0, "skipped": [], "stop": None}
    sem, lock = asyncio.Semaphore(a.concurrency), asyncio.Lock()
    print(f"{a.contest} effort {a.effort}: {len(tasks)} tasks, {len(done)} done, {len(todo)} to run, "
          f"lane spend ${spent:.4f}", flush=True)

    async def one(t):
        async with sem:
            w = h.worst(t)
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
                    resp = await h.sol.call(client, h.request(t))
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{type(e).__name__}: {str(e).replace(key, '<key>').replace(base, '<url>')[:300]}")
                    if attempt + 1 < ATTEMPTS:
                        await asyncio.sleep(5 * (attempt + 1))
            wall = round(time.monotonic() - t0, 2)
            rec = {"task_id": t["task_id"], "date": t["date"], "tier": tier, "model": MODEL, "effort": a.effort,
                   "wall_s": wall, "attempts": len(errors) + (resp is not None), "infra_errors": errors}
            if resp is None:
                rec |= {"reward": 0.0, "c": 0.0, "valid": False, "kind": "error", "usd": 0.0, "usage": None,
                        "tool_call": False, "actions": None}
            else:
                rec |= h.score(t, resp)
            async with lock:
                st["inflight"] -= w
                st["run_usd"] += rec["usd"]
                st["run_n"] += 1
                g, args = rec.pop("grade", None), rec.pop("args", None)
                with log.open("a") as f:
                    f.write(json.dumps(rec | {"grade": g}) + "\n")
                if resp is not None:
                    ep = to_episode_json(t, args, tier, 0, bundle="oneshot", path="B", model=MODEL,
                                         messages=[{"role": "assistant", "content": rec["text"],
                                                    "tool_calls": rec["calls"]}],
                                         usage={"input_tokens": rec["usage"]["input"],
                                                "output_tokens": rec["usage"]["output"], "usd": rec["usd"]},
                                         wall_seconds=wall)
                    with eps.open("a") as f:
                        f.write(json.dumps(ep) + "\n")
                score = rec.get("c") if tier == "blind" else rec["reward"]
                print(f"{t['task_id']} {'C' if tier == 'blind' else 'R'} {score:.4f} {rec['kind']} "
                      f"${rec['usd']:.5f} out {(rec['usage'] or {}).get('output')} {wall}s try {rec['attempts']} "
                      f"lane ${lane():.4f}", flush=True)

    await asyncio.gather(*(one(t) for t in todo))
    print(json.dumps({"contest": a.contest, "effort": a.effort, "lane_spent_usd": round(lane(), 5),
                      "run_usd": round(st["run_usd"], 5), "run_n": st["run_n"], "stopped": st["stop"],
                      "skipped": len(st["skipped"])}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
