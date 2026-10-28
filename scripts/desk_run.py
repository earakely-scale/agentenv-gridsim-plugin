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

try:
    import boto3
except ImportError:
    boto3 = None

from gridsim_core.desk import fixtures, policies, refs
from gridsim_core.desk.data import load_series, load_tasks
from gridsim_core.desk.prompt import system_prompt
from gridsim_core.desk.session import Session, text
from gridsim_core.desk.tools import tool_specs

MODELS = {
    "sol": {"model": "openai/gpt-6.1-sol", "price": (2.0, 10.0, 0.10), "effort": "high", "route": "responses"},
    "luna": {"model": "openai/gpt-6-luna", "price": (0.10, 0.50, 0.01), "effort": "high", "route": "responses"},
    "qwen": {"model": "qwen3-4b", "price": (0.0, 0.0, 0.0), "effort": None, "thinking": False, "route": "chat",
             "sampling": {"temperature": 0.7, "top_p": 0.8}},
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
            url = line.split("=", 1)[1].strip().strip("'\"").rstrip("/")
            return url if url.endswith("/v1") else url + "/v1"
    raise SystemExit(f"no LITELLM_BASE_URL= line in {p}")


def api_key(a) -> str:
    if os.environ.get("DESK_API_KEY"):
        return os.environ["DESK_API_KEY"]
    param = a.ssm_param or os.environ.get("DESK_SSM_PARAM")
    if not param:
        raise SystemExit("set DESK_API_KEY or --ssm-param / DESK_SSM_PARAM")
    region = a.aws_region or os.environ.get("DESK_AWS_REGION", "us-west-2")
    prof = a.aws_profile or os.environ.get("DESK_AWS_PROFILE")
    if boto3 is not None:
        sess = boto3.Session(profile_name=prof, region_name=region) if prof else boto3.Session(region_name=region)
        return sess.client("ssm").get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    cmd = ["aws", "ssm", "get-parameter", "--name", param, "--with-decryption", "--query", "Parameter.Value",
           "--output", "text", "--region", region] + (["--profile", prof] if prof else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not r.stdout.strip():
        raise SystemExit("could not read the API key from SSM (check the profile and region)")
    return r.stdout.strip()


def budgets(a) -> dict | None:
    return {"max_turns": a.max_turns} if a.max_turns else None


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
    """One model behind either route: `responses` (the gateway's GPT models: tools with reasoning effort) or `chat`
    (chat completions, e.g. vLLM). The transcript is a list of plain dicts so a checkpoint can restore it."""

    def __init__(self, a, preset: dict, lane_spent: float, system: str, tools: list[dict]):
        base = a.base_url or gateway_url(a.gateway_env)
        key = "EMPTY" if a.base_url and not a.ssm_param and not os.environ.get("DESK_API_KEY") else api_key(a)
        self.client = openai.OpenAI(base_url=base, api_key=key, timeout=a.timeout, max_retries=4)
        self.model = a.model or preset["model"]
        self.route = preset.get("route", "chat")
        self.price = tuple(a.price) if a.price else preset["price"]
        self.effort = a.effort if a.effort is not None else preset.get("effort")
        self.sampling = preset.get("sampling", {})
        self.thinking = preset.get("thinking")
        self.max_usd, self.lane_cap, self.lane_spent = a.max_usd, a.lane_cap_usd, lane_spent
        self.max_tokens = a.max_tokens
        self.system = system
        if self.route == "responses":
            self.tools = [{"type": "function", **t["function"]} for t in tools]
            self.items: list[dict] = []
        else:
            self.tools = tools
            self.items = [{"role": "system", "content": system}]
        self.turn_starts: list[int] = []
        self.usage = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0,
                      "latency_s": 0.0}

    def state(self) -> dict:
        return {"items": self.items, "turn_starts": self.turn_starts, "usage": self.usage}

    def load(self, st: dict) -> None:
        self.items, self.turn_starts, self.usage = st["items"], st["turn_starts"], st["usage"]

    def user(self, text: str) -> None:
        self.turn_starts.append(len(self.items))
        if self.route == "responses":
            self.items.append({"role": "user", "content": [{"type": "input_text", "text": text}]})
        else:
            self.items.append({"role": "user", "content": text})

    def result(self, call_id: str, output: str) -> None:
        if self.route == "responses":
            self.items.append({"type": "function_call_output", "call_id": call_id, "output": output})
        else:
            self.items.append({"role": "tool", "tool_call_id": call_id, "content": output})

    def compact(self) -> None:
        """Elide tool results older than the last KEEP_TURNS turns, all at once, so the cached prefix changes rarely."""
        if sum(len(json.dumps(m)) for m in self.items) < COMPACT_CHARS or len(self.turn_starts) <= KEEP_TURNS:
            return
        key = "output" if self.route == "responses" else "content"
        for m in self.items[:self.turn_starts[-KEEP_TURNS]]:
            if (m.get("type") == "function_call_output" or m.get("role") == "tool") and m[key] != ELIDED:
                m[key] = ELIDED

    def _charge(self, inp: int, out: int, cached: int, dt: float) -> float:
        pin, pout, pcache = self.price
        c = ((inp - cached) * pin + cached * pcache + out * pout) / 1e6
        self.usage["api_calls"] += 1
        self.usage["input_tokens"] += inp
        self.usage["output_tokens"] += out
        self.usage["cached_tokens"] += cached
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + c, 6)
        self.usage["latency_s"] = round(self.usage["latency_s"] + dt, 2)
        return c

    def step(self, log) -> tuple[str, list[tuple[str, str, str]]]:
        """One model call: (text, [(call_id, name, arguments json)])."""
        if self.usage["cost_usd"] >= self.max_usd:
            raise SpendCap(f"run cap ${self.max_usd} reached")
        if self.lane_cap is not None and self.lane_spent + self.usage["cost_usd"] >= self.lane_cap:
            raise SpendCap(f"lane cap ${self.lane_cap} reached")
        self.compact()
        t0 = time.time()
        if self.route == "responses":
            kw = {"model": self.model, "instructions": self.system, "input": self.items, "tools": self.tools,
                  "store": False, "include": ["reasoning.encrypted_content"]}
            if self.effort:
                kw["reasoning"] = {"effort": self.effort, "summary": "auto"}
            if self.max_tokens:
                kw["max_output_tokens"] = self.max_tokens
            r = self.client.responses.create(**kw)
            dt = time.time() - t0
            out = [item.model_dump(exclude_none=True) for item in r.output]
            self.items.extend(out)
            text = "".join(c.get("text", "") for i in out if i.get("type") == "message" for c in i.get("content", []))
            calls = [(i["call_id"], i["name"], i.get("arguments") or "{}") for i in out
                     if i.get("type") == "function_call"]
            reasoning = "\n".join(x.get("text", "") for i in out if i.get("type") == "reasoning"
                                  for x in i.get("summary", []))
            u = r.usage
            inp, outp = (u.input_tokens or 0, u.output_tokens or 0) if u else (0, 0)
            cached = (u.input_tokens_details.cached_tokens or 0) if u and u.input_tokens_details else 0
            finish = r.status
        else:
            kw = {"model": self.model, "messages": self.items, "tools": self.tools, "tool_choice": "auto",
                  **self.sampling}
            if self.max_tokens:
                kw["max_completion_tokens"] = self.max_tokens
            if self.effort:
                kw["reasoning_effort"] = self.effort
            if self.thinking is not None:
                kw["extra_body"] = {"chat_template_kwargs": {"enable_thinking": self.thinking}}
            r = self.client.chat.completions.create(**kw)
            dt = time.time() - t0
            msg = r.choices[0].message
            m = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                m["tool_calls"] = [{"id": tc.id, "type": "function",
                                    "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                                   for tc in msg.tool_calls]
            self.items.append(m)
            text = msg.content or ""
            calls = [(tc.id, tc.function.name, tc.function.arguments or "{}") for tc in msg.tool_calls or []]
            reasoning = ""
            u = r.usage
            inp, outp = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
            cached = (getattr(getattr(u, "prompt_tokens_details", None), "cached_tokens", 0) or 0) if u else 0
            finish = r.choices[0].finish_reason
        c = self._charge(inp, outp, cached, dt)
        log({"t": time.time(), "model": self.model, "route": self.route, "latency_s": round(dt, 2), "finish": finish,
             "input_tokens": inp, "output_tokens": outp, "cached_tokens": cached, "cost_usd": round(c, 6),
             "tool_calls": [n for _, n, _ in calls], "content": text[:2000], "reasoning": reasoning[:2000]})
        return text, calls


def run_model(task, series, a, preset, out: Path, tag: str, lane_spent: float) -> tuple[Session, dict, str]:
    tid = task["task_id"]
    ck = out / "ckpt" / f"{tid}.{tag}.json"
    calls_log = out / "calls" / f"{tid}.{tag}.jsonl"
    s = Session(task, series, layer=a.layer, budgets=budgets(a))
    agent = ModelAgent(a, preset, lane_spent, system_prompt(s), tool_specs(s.layer, s.rtcb))
    wake = s.start()
    if ck.exists():
        state = json.loads(ck.read_text())
        for t in state["turns"]:
            for c in t["calls"]:
                s.call(c["tool"], c["args"])
            wake = s.end_turn(t.get("text"))
        agent.load(state["agent"])
        print(f"  resumed {tid} at turn {len(state['turns'])}", flush=True)

    def log(row):
        with open(calls_log, "a") as f:
            f.write(json.dumps(dict(row, turn=s.turn)) + "\n")

    status = "ok"
    try:
        while wake is not None:
            agent.user(text(wake))
            reply = None
            for _ in range(s.budget["calls_per_turn"] + 3):
                reply, calls = agent.step(log)
                if not calls:
                    break
                for call_id, name, raw in calls:
                    try:
                        args = json.loads(raw)
                    except json.JSONDecodeError:
                        res = {"error": "args: arguments are not valid JSON"}
                    else:
                        res = s.call(name, args)
                    agent.result(call_id, text(res))
            turns = [{"calls": [{"tool": c["tool"], "args": c["args"]} for c in t["calls"]], "text": t.get("text")}
                     for t in s.turns]
            turns[-1]["text"] = reply
            wake = s.end_turn(reply)
            ck.write_text(json.dumps({"turns": turns, "agent": agent.state()}))
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
    ap.add_argument("--max-turns", type=int, help="override the layer's turn budget (smoke runs)")
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
            s = policies.run(task, series, a.policy, layer=a.layer, budgets=budgets(a))
            usage, status = {"cost_usd": 0.0}, "ok"
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
