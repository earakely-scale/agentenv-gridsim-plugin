"""Run desk episodes in process (path B'): any OpenAI-compatible chat-completions model (a LiteLLM gateway or a vLLM
server) or a built-in policy (anchor, idle, scripted) drives gridsim_core.desk.Session.

Writes <out>/episodes/<task_id>.<tag>.json (Episode JSON), <out>/calls/<task_id>.<tag>.jsonl (one line per API call),
<out>/ckpt/<task_id>.<tag>.json (resume state after every turn) and appends one line per episode to <out>/results.jsonl.

Credentials are read inside the process and never printed: the gateway base URL from the `LITELLM_BASE_URL=` line of
--gateway-env (or $DESK_GATEWAY_ENV), the key from AWS SSM --ssm-param with --aws-profile/--aws-region (or the
DESK_SSM_PARAM / DESK_AWS_PROFILE / DESK_AWS_REGION variables), or $DESK_API_KEY."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import openai

from gridsim_core.desk import fixtures, policies, refs
from gridsim_core.desk.data import load_series, load_tasks
from gridsim_core.desk.prompt import system_prompt
from gridsim_core.desk.session import Session
from gridsim_core.desk.tools import tool_specs

MODELS = {
    "sol": {"model": "openai/gpt-6.1-sol", "price": (2.0, 10.0, 0.10), "effort": "high"},
    "luna": {"model": "openai/gpt-6-luna", "price": (0.10, 0.50, 0.01), "effort": "high"},
    "qwen": {"model": "Qwen/Qwen3-4B", "price": (0.0, 0.0, 0.0), "effort": None, "thinking": False},
}
KEEP_TURNS = 4
COMPACT_CHARS = 120_000
ELIDED = "[elided: an earlier tool result; call the tool again if you need it]"


class SpendCap(Exception):
    pass


def gateway_url(path: str | None) -> str:
    p = path or os.environ.get("DESK_GATEWAY_ENV")
    if not p:
        raise SystemExit("set --gateway-env or DESK_GATEWAY_ENV (a file with a LITELLM_BASE_URL= line)")
    for line in Path(p).read_text().splitlines():
        line = line.strip().removeprefix("export ").strip()
        if line.startswith("LITELLM_BASE_URL="):
            return line.split("=", 1)[1].strip().strip("'\"")
    raise SystemExit(f"no LITELLM_BASE_URL= line in {p}")


def api_key(a) -> str:
    if os.environ.get("DESK_API_KEY"):
        return os.environ["DESK_API_KEY"]
    param = a.ssm_param or os.environ.get("DESK_SSM_PARAM")
    if not param:
        raise SystemExit("set DESK_API_KEY or --ssm-param / DESK_SSM_PARAM")
    cmd = ["aws", "ssm", "get-parameter", "--name", param, "--with-decryption", "--query", "Parameter.Value",
           "--output", "text", "--region", a.aws_region or os.environ.get("DESK_AWS_REGION", "us-west-2")]
    prof = a.aws_profile or os.environ.get("DESK_AWS_PROFILE")
    if prof:
        cmd += ["--profile", prof]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit("could not read the API key from SSM (check the profile and region)")
    return r.stdout.strip()


def tasks_from(a) -> list[tuple[dict, dict]]:
    if a.fixture:
        out = []
        for spec in a.fixture:
            date, _, seed = spec.partition(":")
            out.append(fixtures.make(date, seed=int(seed or 0), outage=True, layer=a.layer))
        return out
    rows = load_tasks(a.pack)
    if a.tasks:
        want = set(a.tasks)
        rows = [t for t in rows if t["task_id"] in want]
    if a.limit:
        rows = rows[:a.limit]
    return [(t, load_series(a.pack, t)) for t in rows]


def ledger(out: Path) -> float:
    p = out / "results.jsonl"
    if not p.exists():
        return 0.0
    return sum(json.loads(line).get("usage", {}).get("cost_usd", 0.0) for line in p.read_text().splitlines() if line)


def done_ids(out: Path, tag: str) -> set[str]:
    p = out / "results.jsonl"
    if not p.exists():
        return set()
    rows = [json.loads(line) for line in p.read_text().splitlines() if line]
    return {r["task_id"] for r in rows if r.get("tag") == tag}


class ModelAgent:
    def __init__(self, a, preset: dict, lane_spent: float):
        base = a.base_url or gateway_url(a.gateway_env)
        key = "EMPTY" if a.base_url and not a.ssm_param and not os.environ.get("DESK_API_KEY") else api_key(a)
        self.client = openai.OpenAI(base_url=base, api_key=key, timeout=a.timeout, max_retries=4)
        self.model = a.model or preset["model"]
        self.price = tuple(a.price) if a.price else preset["price"]
        self.effort = a.effort if a.effort is not None else preset.get("effort")
        self.thinking = preset.get("thinking")
        self.max_usd, self.lane_cap, self.lane_spent = a.max_usd, a.lane_cap_usd, lane_spent
        self.max_tokens = a.max_tokens
        self.usage = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0,
                      "latency_s": 0.0}

    def cost(self, u) -> float:
        cached = getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0
        pin, pout, pcache = self.price
        return ((u.prompt_tokens - cached) * pin + cached * pcache + u.completion_tokens * pout) / 1e6

    def complete(self, messages, tools, log) -> dict:
        if self.usage["cost_usd"] >= self.max_usd:
            raise SpendCap(f"run cap ${self.max_usd} reached")
        if self.lane_cap is not None and self.lane_spent + self.usage["cost_usd"] >= self.lane_cap:
            raise SpendCap(f"lane cap ${self.lane_cap} reached")
        kw = {"model": self.model, "messages": messages, "tools": tools, "tool_choice": "auto"}
        if self.max_tokens:
            kw["max_completion_tokens"] = self.max_tokens
        if self.effort:
            kw["reasoning_effort"] = self.effort
        if self.thinking is not None:
            kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": self.thinking}}
        t0 = time.time()
        r = self.client.chat.completions.create(**kw)
        dt = time.time() - t0
        u = r.usage
        c = self.cost(u) if u else 0.0
        cached = (getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0) if u else 0
        self.usage["api_calls"] += 1
        self.usage["input_tokens"] += u.prompt_tokens if u else 0
        self.usage["output_tokens"] += u.completion_tokens if u else 0
        self.usage["cached_tokens"] += cached
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + c, 6)
        self.usage["latency_s"] = round(self.usage["latency_s"] + dt, 2)
        msg = r.choices[0].message
        out = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            out["tool_calls"] = [{"id": tc.id, "type": "function",
                                  "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                 for tc in msg.tool_calls]
        log({"t": time.time(), "model": self.model, "latency_s": round(dt, 2), "finish": r.choices[0].finish_reason,
             "input_tokens": u.prompt_tokens if u else None, "output_tokens": u.completion_tokens if u else None,
             "cached_tokens": cached, "cost_usd": round(c, 6), "tool_calls": len(msg.tool_calls or []),
             "content": (msg.content or "")[:2000]})
        return out


def compact(messages: list[dict], turn_starts: list[int]) -> None:
    """Elide tool results older than the last KEEP_TURNS turns, all at once, so the cached prefix changes rarely."""
    if sum(len(json.dumps(m)) for m in messages) < COMPACT_CHARS or len(turn_starts) <= KEEP_TURNS:
        return
    cut = turn_starts[-KEEP_TURNS]
    for m in messages[:cut]:
        if m["role"] == "tool" and m["content"] != ELIDED:
            m["content"] = ELIDED


def run_model(task, series, a, preset, out: Path, tag: str, lane_spent: float) -> tuple[Session, dict, str]:
    tid = task["task_id"]
    ck = out / "ckpt" / f"{tid}.{tag}.json"
    calls_log = out / "calls" / f"{tid}.{tag}.jsonl"
    agent = ModelAgent(a, preset, lane_spent)
    s = Session(task, series, layer=a.layer)
    tools = tool_specs(s.layer, s.rtcb)
    messages = [{"role": "system", "content": system_prompt(s)}]
    turn_starts: list[int] = []
    wake = s.start()
    if ck.exists():
        state = json.loads(ck.read_text())
        for t in state["turns"]:
            for c in t["calls"]:
                s.call(c["tool"], c["args"])
            wake = s.end_turn(t.get("text"))
        messages, turn_starts, agent.usage = state["messages"], state["turn_starts"], state["usage"]
        print(f"  resumed {tid} at turn {len(state['turns'])}", flush=True)

    def log(row):
        with open(calls_log, "a") as f:
            f.write(json.dumps(dict(row, turn=s.turn)) + "\n")

    status = "ok"
    try:
        while wake is not None:
            turn_starts.append(len(messages))
            messages.append({"role": "user", "content": json.dumps(wake)})
            text = None
            for _ in range(s.budget["calls_per_turn"] + 3):
                compact(messages, turn_starts)
                msg = agent.complete(messages, tools, log)
                messages.append(msg)
                if not msg.get("tool_calls"):
                    text = msg["content"]
                    break
                for tc in msg["tool_calls"]:
                    try:
                        args = json.loads(tc["function"]["arguments"] or "{}")
                    except json.JSONDecodeError:
                        res = {"error": "args: arguments are not valid JSON"}
                    else:
                        res = s.call(tc["function"]["name"], args)
                    messages.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(res)})
            turns = [{"calls": [{"tool": c["tool"], "args": c["args"]} for c in t["calls"]], "text": t.get("text")}
                     for t in s.turns]
            turns[-1]["text"] = text
            wake = s.end_turn(text)
            ck.write_text(json.dumps({"turns": turns, "messages": messages, "turn_starts": turn_starts,
                                      "usage": agent.usage}))
    except SpendCap as e:
        status = f"capped: {e}"
        print(f"  {tid}: {status}; the market runs on with the standing offers", flush=True)
    s.finish()
    return s, agent.usage, status


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pack", help="a pack name under data/desk or a pack directory")
    src.add_argument("--fixture", nargs="+", help="synthetic fixture days DATE[:SEED]")
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--layer", default="v2")
    ap.add_argument("--policy", default="model", choices=["model", "anchor", "idle", "scripted"])
    ap.add_argument("--preset", default="sol", choices=sorted(MODELS))
    ap.add_argument("--model")
    ap.add_argument("--effort")
    ap.add_argument("--price", nargs=3, type=float, metavar=("IN", "OUT", "CACHED"), help="$ per 1M tokens")
    ap.add_argument("--base-url", help="an OpenAI-compatible endpoint (e.g. a vLLM server); default: the gateway")
    ap.add_argument("--gateway-env")
    ap.add_argument("--ssm-param")
    ap.add_argument("--aws-profile")
    ap.add_argument("--aws-region")
    ap.add_argument("--max-usd", type=float, default=5.0, help="per-episode spend cap")
    ap.add_argument("--lane-cap-usd", type=float, help="cap on the total spend recorded in <out>/results.jsonl")
    ap.add_argument("--max-tokens", type=int)
    ap.add_argument("--timeout", type=float, default=600.0)
    ap.add_argument("--tag")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    for d in ("episodes", "calls", "ckpt"):
        (out / d).mkdir(parents=True, exist_ok=True)
    preset = MODELS[a.preset]
    tag = a.tag or (a.policy if a.policy != "model" else (a.model or preset["model"]).split("/")[-1])
    finished = done_ids(out, tag)
    for task, series in tasks_from(a):
        tid = task["task_id"]
        if tid in finished:
            print(f"skip {tid} ({tag} done)", flush=True)
            continue
        r = refs.refs_for(task, series)
        t0 = time.time()
        if a.policy == "model":
            s, usage, status = run_model(task, series, a, preset, out, tag, ledger(out))
            pol = {"kind": "model", "model": a.model or preset["model"], "effort": a.effort or preset.get("effort")}
        else:
            s, usage, status = policies.run(task, series, a.policy, layer=a.layer), {"cost_usd": 0.0}, "ok"
            pol = {"kind": a.policy}
        g = refs.grade(s, r)
        usage = dict(usage, turns=len(s.turns), calls=sum(len(t["calls"]) for t in s.turns),
                     wall_s=round(time.time() - t0, 1))
        ep = s.episode(policy=pol, usage=usage, grade=g)
        (out / "episodes" / f"{tid}.{tag}.json").write_text(json.dumps(ep))
        row = {"task_id": tid, "tag": tag, "policy": pol, "layer": s.layer, "era": s.era, "status": status,
               "grade": g, "usage": usage, "compliance": ep["compliance"],
               "rejected": sum(1 for x in s.submissions if x["codes"]), "submissions": len(s.submissions)}
        with open(out / "results.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
        print(f"{tid} {tag}: R={g['reward']:.3f} C={g['capture']} P={g['p']:,.0f} anchor={g['p_anchor']:,.0f} "
              f"hind={g['p_hind']:,.0f} turns={usage['turns']} ${usage.get('cost_usd', 0):.3f} {status}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
