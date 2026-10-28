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
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from pathlib import Path

import openai

try:
    import boto3
except ImportError:
    boto3 = None

from gridsim_core.desk import fixtures, policies, refs
from gridsim_core.desk.data import load_series, load_tasks, pack_dir
from gridsim_core.desk.prompt import system_prompt
from gridsim_core.desk.session import Session, text
from gridsim_core.desk.tools import tool_specs

MODELS = {
    "sol": {"model": "openai/gpt-6.1-sol", "price": (2.0, 10.0, 0.10), "effort": "high", "route": "responses"},
    "luna": {"model": "openai/gpt-6-luna", "price": (0.10, 0.50, 0.01), "effort": "high", "route": "responses"},
    "qwen": {"model": "qwen3-4b", "price": (0.0, 0.0, 0.0), "effort": None, "thinking": False, "route": "chat",
             "context": 32_768, "prompt_target": 24_000, "max_out": 4096, "keep_turns": 3,
             "sampling": {"temperature": 0.7, "top_p": 0.8}},
}
KEEP_TURNS = 4
COMPACT_CHARS = 120_000
COMPACTION = {"v4": (3, 80_000)}
ELIDED = "[elided: an earlier tool result; call the tool again if you need it]"
SUMMARY = "[summary of an earlier result] "
KEEP_SUMMARY = ("submit_dam_offers", "submit_rt_offers", "update_cop", "check_submission", "set_reminder")


def summary(name: str, content: str) -> str:
    """One line kept for an elided submission: what was accepted and every rejection code."""
    try:
        r = json.loads(content)
    except json.JSONDecodeError:
        return ELIDED
    parts = [name, r.get("now", "")]
    if r.get("error"):
        parts.append(f"error {r['error'][:80]}")
    for k in ("date", "accepted_hours", "as_accepted", "at"):
        if r.get(k):
            parts.append(f"{k}={r[k]}")
    codes = sorted({f"{x.get('hours')}:{x.get('code')}" for k in ("rejected", "as_rejected") for x in r.get(k) or []})
    if codes:
        parts.append("rejected " + ",".join(codes)[:200])
    return SUMMARY + " ".join(str(p) for p in parts if p)


WORST_OUT = 16_000
CHARS_PER_TOKEN = 3


class SpendCap(Exception):
    pass


class ContextOverflow(Exception):
    pass


class Stopped(Exception):
    pass


class Budget:
    """The lane cap shared by every episode in the process: each call reserves its worst case before it is sent and
    settles to the real cost after, so concurrent episodes can never overrun the cap together."""

    def __init__(self, cap: float | None, spent: float):
        self.cap, self.spent, self.inflight = cap, spent, 0.0
        self.lock = threading.Lock()
        self.stop = threading.Event()

    def reserve(self, worst: float) -> None:
        with self.lock:
            if self.stop.is_set():
                raise Stopped("stop requested")
            if self.cap is not None and self.spent + self.inflight + worst > self.cap:
                raise SpendCap(f"lane cap ${self.cap} reached (spent ${self.spent:.2f}, "
                               f"in flight ${self.inflight:.2f})")
            self.inflight += worst

    def settle(self, worst: float, actual: float) -> None:
        with self.lock:
            self.inflight -= worst
            self.spent += actual


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


def task_layer(task: dict, a) -> str:
    """The task's own layer; --layer may only confirm it (refs are built for the task's layer)."""
    layer = task.get("layer", "v2")
    if a.layer and a.layer != layer:
        raise SystemExit(f"--layer {a.layer} does not match {task['task_id']}'s layer {layer}")
    return layer


def budgets(a) -> dict | None:
    return {"max_turns": a.max_turns} if a.max_turns else None


def tasks_from(a) -> list[tuple[dict, dict]]:
    if a.fixture:
        out = []
        for spec in a.fixture:
            date, _, seed = spec.partition(":")
            out.append(fixtures.make(date, seed=int(seed or 0), outage=True, layer=a.layer or "v2"))
        return out
    rows = load_tasks(a.pack)
    want = set(a.tasks or [])
    if a.tasks_file:
        for line in Path(a.tasks_file).read_text().splitlines():
            line = line.strip()
            if line:
                want.add(json.loads(line)["task_id"] if line.startswith("{") else line)
    if want:
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

    def __init__(self, a, preset: dict, lane_spent: float, system: str, tools: list[dict],
                 budget: Budget | None = None, layer: str | None = None):
        base = a.base_url or gateway_url(a.gateway_env)
        key = "EMPTY" if a.base_url and not a.ssm_param and not os.environ.get("DESK_API_KEY") else api_key(a)
        self.client = openai.OpenAI(base_url=base, api_key=key, timeout=a.timeout, max_retries=4)
        self.model = a.model or preset["model"]
        self.route = preset.get("route", "chat")
        self.price = tuple(a.price) if a.price else preset["price"]
        self.effort = a.effort if a.effort is not None else preset.get("effort")
        self.sampling = preset.get("sampling", {})
        self.thinking = preset.get("thinking")
        self.max_usd = a.max_usd
        self.budget = budget or Budget(getattr(a, "lane_cap_usd", None), lane_spent)
        self.max_tokens = a.max_tokens
        self.system = system
        if self.route == "responses":
            self.tools = [{"type": "function", **t["function"]} for t in tools]
            self.items: list[dict] = []
        else:
            self.tools = tools
            self.items = [{"role": "system", "content": system}]
        self.turn_starts: list[int] = []
        self.compaction = COMPACTION.get(layer or getattr(a, "layer", None) or "v2", (KEEP_TURNS, COMPACT_CHARS))
        self.context = preset.get("context")
        self.prompt_target = preset.get("prompt_target")
        self.max_out = preset.get("max_out")
        self.tok_per_char = 0.5
        if self.prompt_target:
            self.compaction = (preset.get("keep_turns", 3), self.prompt_target)
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

    def chars(self) -> int:
        return sum(len(json.dumps(m)) for m in self.items) + len(self.system) + len(json.dumps(self.tools))

    def est_tokens(self) -> int:
        return int(self.chars() * self.tok_per_char)

    def _names(self) -> dict[str, str]:
        out = {}
        for m in self.items:
            if m.get("type") == "function_call":
                out[m["call_id"]] = m["name"]
            for tc in m.get("tool_calls") or []:
                out[tc["id"]] = tc["function"]["name"]
        return out

    def _read_upto(self) -> int:
        """Index after the last model item: tool outputs past it have not been read yet and are never elided."""
        for i in range(len(self.items) - 1, -1, -1):
            m = self.items[i]
            if m.get("role") == "assistant" or m.get("type") in ("function_call", "message", "reasoning"):
                return i
        return 0

    def _elide(self, upto: int, spare_last: int = 0) -> None:
        """Elide read tool outputs before `upto`: reads first; submissions keep a one-line summary of what was
        accepted and rejected; the last `spare_last` read outputs stay whole."""
        key = "output" if self.route == "responses" else "content"
        names = self._names()
        upto = min(upto, self._read_upto(), self.turn_starts[-1] if self.turn_starts else upto)
        recent = self.turn_starts[-2] if len(self.turn_starts) >= 2 else 0
        outs = [(i, m) for i, m in enumerate(self.items[:upto])
                if m.get("type") == "function_call_output" or m.get("role") == "tool"]
        if spare_last:
            outs = outs[:max(len(outs) - spare_last, 0)]
        for i, m in outs:
            if m[key] == ELIDED or m[key].startswith(SUMMARY):
                continue
            name = names.get(m.get("call_id") or m.get("tool_call_id"), "")
            if name in KEEP_SUMMARY:
                if i < recent:
                    m[key] = summary(name, m[key])
            else:
                m[key] = ELIDED

    def compact(self, hard: bool = False) -> None:
        """Elide read tool outputs older than the last `keep` turns, all at once, so the cached prefix changes rarely.
        With a token budget (a small-context model) it measures in tokens and, if needed, also elides inside the kept
        turns down to the last two read outputs; outputs the model has not read are never elided."""
        keep, limit = self.compaction
        if self.prompt_target:
            if not hard and self.est_tokens() < limit:
                return
            if len(self.turn_starts) > keep:
                self._elide(self.turn_starts[-keep])
            if hard or self.est_tokens() >= limit:
                self._elide(len(self.items), spare_last=2)
            return
        if sum(len(json.dumps(m)) for m in self.items) < limit or len(self.turn_starts) <= keep:
            return
        self._elide(self.turn_starts[-keep])

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
        self.compact()
        for attempt in range(2):
            worst = self.worst()
            self.budget.reserve(worst)
            try:
                return self._step(log, worst)
            except openai.BadRequestError as e:
                self.budget.settle(worst, 0.0)
                if "context" not in str(e).lower() and "maximum" not in str(e).lower():
                    raise
                self.usage["context_errors"] = self.usage.get("context_errors", 0) + 1
                if attempt:
                    raise ContextOverflow(str(e)[:300]) from e
                self.compact(hard=True)
            except BaseException:
                self.budget.settle(worst, 0.0)
                raise
        raise ContextOverflow("unreachable")

    def out_tokens(self) -> int | None:
        if not self.context:
            return self.max_tokens
        room = self.context - self.est_tokens() - 256
        return max(256, min(self.max_tokens or self.max_out or 4096, room))

    def worst(self) -> float:
        pin, pout, _ = self.price
        n_in = (sum(len(json.dumps(m)) for m in self.items) + len(self.system) + len(json.dumps(self.tools))) \
            // CHARS_PER_TOKEN
        return (n_in * pin + (self.max_tokens or WORST_OUT) * pout) / 1e6

    def _step(self, log, worst: float) -> tuple[str, list[tuple[str, str, str]]]:
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
            out_cap = self.out_tokens()
            if out_cap:
                kw["max_completion_tokens"] = out_cap
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
        if inp:
            self.tok_per_char = max(0.25, inp / max(self.chars(), 1))
        self.budget.settle(worst, c)
        log({"t": time.time(), "model": self.model, "route": self.route, "latency_s": round(dt, 2), "finish": finish,
             "input_tokens": inp, "output_tokens": outp, "cached_tokens": cached, "cost_usd": round(c, 6),
             "tool_calls": [n for _, n, _ in calls], "content": text[:2000], "reasoning": reasoning[:2000]})
        return text, calls


def run_model(task, series, a, preset, out: Path, tag: str, budget: Budget) -> tuple[Session, dict, str]:
    tid = task["task_id"]
    ck = out / "ckpt" / f"{tid}.{tag}.json"
    calls_log = out / "calls" / f"{tid}.{tag}.jsonl"
    spent = out / "ckpt" / f"{tid}.{tag}.usage.json"
    s = Session(task, series, layer=task_layer(task, a), budgets=budgets(a))
    agent = ModelAgent(a, preset, 0.0, system_prompt(s), tool_specs(s.layer, s.rtcb), budget, layer=s.layer)
    wake = s.start()
    if ck.exists():
        state = json.loads(ck.read_text())
        for t in state["turns"]:
            for c in t["calls"]:
                s.call(c["tool"], c["args"])
            wake = s.end_turn(t.get("text"))
        agent.load(state["agent"])
        if spent.exists():
            seen = json.loads(spent.read_text())
            if seen.get("cost_usd", 0.0) > agent.usage.get("cost_usd", 0.0):
                agent.usage = dict(agent.usage, **{k: v for k, v in seen.items() if k != "latency_s"})
        print(f"  resumed {tid} at turn {len(state['turns'])}", flush=True)

    def log(row):
        with open(calls_log, "a") as f:
            f.write(json.dumps(dict(row, turn=s.turn)) + "\n")
        spent.write_text(json.dumps(agent.usage))

    status = "ok"
    try:
        while wake is not None:
            agent.user(text(wake))
            reply = None
            for _ in range(s.budget["calls_per_turn"] + 3):
                if budget.stop.is_set():
                    raise Stopped("stop requested")
                try:
                    reply, calls = agent.step(log)
                except ContextOverflow as e:
                    reply = f"[error: context overflow, turn ended: {e}]"
                    log({"t": time.time(), "error": "context_overflow", "detail": str(e)[:300]})
                    break
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


def _refs_row(args) -> str:
    task, series = args
    return json.dumps({"task_id": task["task_id"], "refs": refs.build_refs(task, series)})


def refs_only(a, out: Path) -> None:
    """Compute every task's refs block in parallel and write <out>/refs.jsonl (the data lane merges it), with the
    floored tasks reported in <out>/refs-report.json and, with --manifest, in the pack's manifest.json."""
    items = tasks_from(a)
    rows = []
    with ProcessPoolExecutor(max_workers=a.workers) as ex, open(out / "refs.jsonl", "w") as f:
        for line in ex.map(_refs_row, items, chunksize=1):
            f.write(line + "\n")
            r = json.loads(line)
            rows.append(r)
            print(r["task_id"], {k: r["refs"][k] for k in ("p_idle", "p_anchor", "p_hind", "p_hind_phys",
                                                           "p_operator_replay", "floored")}, flush=True)
    floored = sorted(r["task_id"] for r in rows if r["refs"]["floored"])
    c_undef = sorted(r["task_id"] for r in rows if r["refs"].get("c_undefined"))
    report = {"pack": a.pack, "tasks": len(rows), "floored": len(floored), "floored_tasks": floored,
              "c_undefined": len(c_undef), "c_undefined_tasks": c_undef,
              "anchor_setting": rows[0]["refs"]["anchor_setting"] if rows else None,
              "core_version": rows[0]["refs"]["core_version"] if rows else None}
    (out / "refs-report.json").write_text(json.dumps(report, indent=1))
    print(f"floored: {len(floored)} of {len(rows)} {floored}; C undefined: {len(c_undef)} {c_undef}", flush=True)
    if a.manifest and a.pack:
        mp = pack_dir(a.pack) / "manifest.json"
        man = json.loads(mp.read_text()) if mp.exists() else {}
        man["refs_report"] = report
        mp.write_text(json.dumps(man, indent=1) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pack", help="a pack name under data/desk or a pack directory")
    src.add_argument("--fixture", nargs="+", help="synthetic fixture days DATE[:SEED]")
    ap.add_argument("--tasks", nargs="*")
    ap.add_argument("--tasks-file", help="task ids, one per line (or a jsonl with task_id)")
    ap.add_argument("--parallel", type=int, default=1, help="episodes run concurrently in this process")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--layer", help="must match the tasks' layer when given (fixtures: the layer to build)")
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
    ap.add_argument("--refs-only", action="store_true", help="only compute refs for the tasks (parallel)")
    ap.add_argument("--workers", type=int, default=os.cpu_count())
    ap.add_argument("--manifest", action="store_true", help="with --refs-only: write the floored report into the pack")
    a = ap.parse_args()
    out = Path(a.out)
    for d in ("episodes", "calls", "ckpt"):
        (out / d).mkdir(parents=True, exist_ok=True)
    if a.refs_only:
        refs_only(a, out)
        return
    preset = MODELS[a.preset]
    tag = a.tag or (a.policy if a.policy != "model" else (a.model or preset["model"]).split("/")[-1])
    finished = done_ids(out, tag)
    todo = []
    for task, series in tasks_from(a):
        if task["task_id"] in finished:
            print(f"skip {task['task_id']} ({tag} done)", flush=True)
        else:
            todo.append((task, series))
    budget = Budget(a.lane_cap_usd, ledger(out))
    signal.signal(signal.SIGTERM, lambda *_: budget.stop.set())
    signal.signal(signal.SIGINT, lambda *_: budget.stop.set())
    print(f"{tag}: {len(todo)} episodes to run, {len(finished)} done, lane spend ${budget.spent:.2f}, "
          f"parallel {a.parallel}", flush=True)
    with ThreadPoolExecutor(max_workers=a.parallel) as ex:
        futs = {ex.submit(episode, task, series, a, preset, out, tag, budget): task["task_id"] for task, series in todo}
        for f in as_completed(futs):
            try:
                row = f.result()
            except Exception as e:  # noqa: BLE001
                print(f"{futs[f]}: FAILED {type(e).__name__}: {e}", flush=True)
                continue
            if row is None:
                print(f"{futs[f]}: stopped; checkpoint kept", flush=True)
                continue
            with open(out / "results.jsonl", "a") as fh:
                fh.write(json.dumps(row) + "\n")
            g, usage = row["grade"], row["usage"]
            print(f"{row['task_id']} {tag}: R={g['reward']:.3f} C={g['capture']} C_phys={g['capture_phys']} "
                  f"P={g['p']:,.0f} anchor={g['p_anchor']:,.0f} hind={g['p_hind']:,.0f} turns={usage['turns']} "
                  f"${usage.get('cost_usd', 0):.3f} {row['status']}", flush=True)
    if budget.stop.is_set():
        print("stopped on signal; rerun the same command to resume", flush=True)


def episode(task, series, a, preset, out: Path, tag: str, budget: Budget) -> dict | None:
    """One episode, played and graded; None when a stop signal interrupted it (its checkpoint stays)."""
    tid = task["task_id"]
    if budget.stop.is_set():
        return None
    r = refs.refs_for(task, series)
    t0 = time.time()
    if a.policy == "model":
        try:
            s, usage, status = run_model(task, series, a, preset, out, tag, budget)
        except Stopped:
            return None
        pol = {"kind": "model", "model": a.model or preset["model"], "effort": a.effort or preset.get("effort")}
    else:
        s = policies.run(task, series, a.policy, layer=task_layer(task, a), budgets=budgets(a))
        usage, status = {"cost_usd": 0.0}, "ok"
        pol = {"kind": a.policy}
    g = refs.grade(s, r)
    usage = dict(usage, turns=len(s.turns), calls=sum(len(t["calls"]) for t in s.turns),
                 wall_s=round(time.time() - t0, 1))
    ep = s.episode(policy=pol, usage=usage, grade=g)
    (out / "episodes" / f"{tid}.{tag}.json").write_text(json.dumps(ep))
    return {"task_id": tid, "tag": tag, "policy": pol, "layer": s.layer, "era": s.era, "status": status,
            "grade": g, "capture": g["capture"], "capture_phys": g["capture_phys"], "usage": usage,
            "compliance": ep["compliance"], "rejected": sum(1 for x in s.submissions if x["codes"]),
            "submissions": len(s.submissions)}

if __name__ == "__main__":
    sys.exit(main())
