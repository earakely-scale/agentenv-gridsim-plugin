"""portsim-llm's harness loop as the GridSim A2A agent: one battery-day on the env's MCP tools through agent-env's model
endpoint, on the API each provider serves best. Cost is usage times PRICES, or the estimate of a request when its
usage is lost (it failed, or the harness cut its stream); when GRIDSIM_MAX_COST_USD is set, an episode stops before a
request whose estimate could take it past that: the last request's measured input tokens at the cache-read rate while
the provider reports caching and the cache is warm, the bytes added since as fresh tokens, and max_tokens of output.
The summary also gives the cost without the failed requests, which may not have been billed, and how many failed. MCP
has no done flag, so the episode ends on submit_schedule's submitted, at MAX_TOOL_CALLS calls, or after max_turns. An
env that lists advance is a live day in watches (gridsim-live): the episode ends on advance's done, with no tool-call
cap, or once a turn would start within TIME_MARGIN of the time limit, the day then graded on what was committed;
Anthropic requests carry one rolling cache breakpoint. A live env without commit_da is a hybrid site-day
(gridsim-hybrid), whose nudges speak of commit_schedule and the AS book."""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import anthropic
import httpx
import httpx2
import openai
from agentenv_protocol.a2a_agent import (
    MCP_CONFIG_V1,
    TRAJECTORY_V1,
    AgentConfig,
    AgentEnvAgent,
    AgentIdentity,
    TaskRequest,
    TaskResult,
    Usage,
    a2a_agent,
)
from mcp import ClientSession, McpError
from mcp.client.streamable_http import streamable_http_client

log = logging.getLogger("gridsim-llm")

REQUEST_TIMEOUT = 900.0
NOTES_CHARS = 8000
MAX_TOOL_CALLS = 24
TIME_MARGIN = 1200
HARNESS_CAP = "length (harness cap)"
CACHE_SECONDS = 300
BYTES_PER_TOKEN = 3.5
PRICES = {  # USD per 1M tokens: input, output, cache read. LiteLLM public price map, 2026-10-06 to 2026-10-21.
    "anthropic/claude-opus-5-5": (4.00, 20.00, 0.40),
    "anthropic/claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "anthropic/claude-haiku-5-5": (0.10, 0.50, 0.01),
    "openai/gpt-6-astra": (10.00, 50.00, 1.00),
    "openai/gpt-6.1-sol": (2.00, 10.00, 0.10),
    "openai/gpt-5.6-terra": (2.00, 12.00, 0.20),
    "openai/gpt-6-luna": (0.10, 0.50, 0.01),
    "fireworks_ai/kimi-k3": (3.00, 15.00, 0.30),
    "fireworks_ai/glm-5p3": (1.40, 4.40, 0.26),
    "fireworks_ai/glm-5p3-flash": (0.15, 0.50, 0.03),
    "fireworks_ai/qwen3p8-2p4t-a95b": (2.00, 6.00, 0.25),  # no Fireworks entry in the map: the other providers' price
    "fireworks_ai/deepseek-v4p1-flash": (0.30, 1.20, 0.006),
    "groq/qwen/qwen3.8-27b": (0.80, 4.00, 0.80),
}
MAX_OUTPUT = {"groq/qwen/qwen3.8-27b": 16384}  # the provider's limit on one reply, under the task's max_tokens
SUBMIT = "submit_schedule"
LAST_TURN = "This is your last turn: call submit_schedule now with your best schedule."
NO_CALL = ("No tool was called. Schedules only count through the tools: call submit_schedule with your final 24 "
           "actions.")
CUT_OFF = ("Your last turn ran out of output tokens before calling a tool. Your notes from it are above. Keep "
           "reasoning short now and call submit_schedule with your best schedule.")


@dataclass(frozen=True)
class Mode:
    last_turn: str
    no_call: str
    cut_off: str


V1 = Mode(LAST_TURN, NO_CALL, CUT_OFF)
LIVE = Mode("This is your last turn: commit now if your schedule needs a change (commit_da at watch 0, else "
            "commit_schedule); the rest of the day then runs on what you committed.",
            "No tool was called. Only the tools count: commit_da and commit_schedule commit your position and "
            "schedule, advance moves to the next watch.",
            "Your last turn ran out of output tokens before calling a tool. Your notes from it are above. Keep "
            "reasoning short now and call commit_schedule with your current draft, or advance.")
HYBRID = Mode("This is your last turn: commit now if your book needs a change (commit_schedule; at watch 0 it also "
              "sets your DA position and DA AS awards); the rest of the day then runs on what you committed.",
              "No tool was called. Only the tools count: commit_schedule commits your energy schedule and AS book, "
              "advance moves to the next watch.",
              LIVE.cut_off)


class GridSimConfig(AgentConfig):
    model: str = "openai/gpt-6.1-sol"
    system_prompt: str = ""
    max_turns: int = 4
    model_params: dict[str, Any] = {"max_tokens": 4096}
    effort: str | None = None


class ProviderError(Exception):
    """A Responses stream that reported a failure, or ended without a response."""


@dataclass
class Tool:
    name: str
    description: str | None
    input_schema: dict | None


class EnvSession:
    """One MCP session on the env server: one episode."""

    def __init__(self, session: ClientSession):
        self.session = session

    async def tools(self) -> list[Tool]:
        return [Tool(t.name, t.description, t.inputSchema) for t in (await self.session.list_tools()).tools]

    async def call(self, name: str, arguments: dict) -> str:
        result = await self.session.call_tool(name, arguments)
        text = "\n".join(c.text for c in result.content if c.type == "text")
        return json.dumps({"error": text}) if result.isError else text


# ================================================================ model adapters

@dataclass
class Call:
    id: str
    name: str
    arguments: dict
    error: str | None = None
    raw: str = ""


@dataclass
class Turn:
    text: str
    reasoning: str
    calls: list[Call]
    stop: str
    usage: dict = field(default_factory=dict)


def _result(out: str) -> Any:
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"text": out}


def _args(raw: str) -> tuple[dict, str | None]:
    try:
        v = json.loads(raw or "{}")
    except json.JSONDecodeError as e:
        return {}, f"arguments are not valid JSON: {e.msg}"
    return (v, None) if isinstance(v, dict) else ({}, "arguments must be a JSON object")


class AnthropicAgent:
    route = "messages"

    def __init__(self, model: str, tools, system: str, max_tokens: int, base_url: str, api_key: str,
                 effort: str | None = None, cache: bool = False):
        self.client = anthropic.AsyncAnthropic(base_url=base_url, auth_token=api_key, max_retries=4,
                                               timeout=REQUEST_TIMEOUT)
        self.model, self.system, self.max_tokens, self.cache = model, system, max_tokens, cache
        self.extra = ({"extra_body": {"output_config": {"effort": effort}}} if effort in ("low", "medium", "high")
                      else {})
        self.tools = [{"name": t.name, "description": t.description or "",
                       "input_schema": t.input_schema or {"type": "object", "properties": {}}} for t in tools]
        self.messages: list[dict] = []
        self._pending: list[dict] = []

    def user(self, text: str):
        self._pending.append({"type": "text", "text": text})

    def notes(self, text: str):
        self._pending.append({"type": "text", "text": f"(Your notes from the cut-off turn)\n{text}"})

    def results(self, pairs: list[tuple[Call, str]]):
        blocks = [{"type": "tool_result", "tool_use_id": c.id, "content": [{"type": "text", "text": out}]}
                  for c, out in pairs]
        self._pending = blocks + self._pending

    def request(self) -> dict:
        if self._pending:
            self.messages.append({"role": "user", "content": self._pending})
            self._pending = []
        messages = self.messages
        if self.cache:
            *blocks, newest = messages[-1]["content"]
            messages = [*messages[:-1], {**messages[-1], "content": [
                *blocks, {**newest, "cache_control": {"type": "ephemeral"}}]}]
        return {"model": self.model, "system": self.system, "messages": messages, "tools": self.tools,
                "max_tokens": self.max_tokens, **self.extra}

    async def step(self, request: dict) -> Turn:
        async with self.client.messages.stream(**request) as s:
            msg = await s.get_final_message()
        self.messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in msg.content]})
        text, reasoning, calls = "", "", []
        for b in msg.content:
            if b.type == "text":
                text += b.text
            elif b.type == "thinking":
                reasoning += getattr(b, "thinking", "") or ""
            elif b.type == "tool_use":
                args = b.input if isinstance(b.input, dict) else {}
                calls.append(Call(b.id, b.name, args, None, json.dumps(b.input)))
        u = msg.usage
        cached, written = u.cache_read_input_tokens or 0, u.cache_creation_input_tokens or 0
        usage = {"input": (u.input_tokens or 0) + cached + written, "output": u.output_tokens or 0, "cached": cached,
                 "cache_write": written}
        return Turn(text, reasoning, calls, msg.stop_reason or "", usage)


class OpenAIResponsesAgent:
    route = "responses"

    def __init__(self, model: str, tools, system: str, max_tokens: int, base_url: str, api_key: str,
                 effort: str = "medium"):
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=3, timeout=REQUEST_TIMEOUT)
        self.model, self.system, self.max_tokens, self.effort = model, system, max_tokens, effort
        self.tools = [{"type": "function", "name": t.name, "description": t.description or "",
                       "parameters": t.input_schema or {"type": "object", "properties": {}}} for t in tools]
        self.input: list = []
        self._texts: list[str] = []

    def user(self, text: str):
        self._texts.append(text)

    def notes(self, text: str):
        self._texts.append(f"(Your notes from the cut-off turn)\n{text}")

    def results(self, pairs):
        for c, out in pairs:
            self.input.append({"type": "function_call_output", "call_id": c.id, "output": out})

    def request(self) -> dict:
        if self._texts:
            self.input.append({"role": "user", "content": [{"type": "input_text", "text": "\n\n".join(self._texts)}]})
            self._texts = []
        return {"model": self.model, "instructions": self.system, "input": self.input, "tools": self.tools,
                "max_output_tokens": self.max_tokens, "store": False, "include": ["reasoning.encrypted_content"],
                "reasoning": {"effort": self.effort, "summary": "auto"}, "stream": True}

    async def step(self, request: dict) -> Turn:
        resp = None
        async for event in await self.client.responses.create(**request):
            if event.type in ("response.completed", "response.incomplete"):
                resp = event.response
            elif event.type == "response.failed":
                raise ProviderError(f"response.failed: {event.response.error}")
            elif event.type == "error":
                raise ProviderError(f"error: {event.code}: {event.message}")
        if resp is None:
            raise ProviderError("the response stream ended without response.completed")
        self.input.extend(resp.output)
        text, reasoning, calls = "", "", []
        for item in resp.output:
            if item.type == "message":
                text += "".join(getattr(c, "text", "") for c in item.content)
            elif item.type == "reasoning":
                reasoning += "\n".join(getattr(s, "text", "") for s in (getattr(item, "summary", None) or []))
            elif item.type == "function_call":
                args, err = _args(item.arguments)
                calls.append(Call(item.call_id, item.name, args, err, item.arguments or ""))
        u = resp.usage
        stop = resp.status or ""
        if stop == "incomplete" and getattr(resp, "incomplete_details", None):
            stop = f"length ({resp.incomplete_details.reason})"
        return Turn(text, reasoning, calls, stop, {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
                                                   "cached": u.input_tokens_details.cached_tokens or 0,
                                                   "cache_write": 0})


class ChatAgent:
    """OpenAI-compatible chat completions, streamed. Eight retries, about 40 s of backoff: a provider's
    tokens-per-minute limit answers 429 until its minute turns. A call whose arguments aren't a JSON object goes back
    into the history as {}, its result saying why, since Fireworks refuses a history that holds one; the record keeps
    what the model sent."""

    route = "chat"

    def __init__(self, model: str, tools, system: str, max_tokens: int, base_url: str, api_key: str,
                 effort: str | None = None):
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, max_retries=8, timeout=REQUEST_TIMEOUT)
        self.model, self.max_tokens = model, max_tokens
        self.extra = {"reasoning_effort": effort} if effort in ("low", "medium", "high") else {}
        self.tools = [{"type": "function", "function": {
            "name": t.name, "description": t.description or "",
            "parameters": t.input_schema or {"type": "object", "properties": {}}}} for t in tools]
        self.messages: list[dict] = [{"role": "system", "content": system}]
        self._texts: list[str] = []

    def user(self, text: str):
        self._texts.append(text)

    def notes(self, text: str):
        if self.messages and self.messages[-1]["role"] == "assistant" and not self.messages[-1].get("content"):
            self.messages[-1]["content"] = f"(notes so far, cut off by the output limit)\n{text}"
        else:
            self._texts.append(f"(Your notes from the cut-off turn)\n{text}")

    def results(self, pairs):
        for c, out in pairs:
            self.messages.append({"role": "tool", "tool_call_id": c.id, "content": out})

    def request(self) -> dict:
        if self._texts:
            self.messages.append({"role": "user", "content": "\n\n".join(self._texts)})
            self._texts = []
        return {"model": self.model, "messages": self.messages, "tools": self.tools, "max_tokens": self.max_tokens,
                "stream": True, "stream_options": {"include_usage": True}, **self.extra}

    async def step(self, request: dict) -> Turn:
        stream = await self.client.chat.completions.create(**request)
        content, reasoning, calls, stop = [], [], {}, ""
        usage = {"input": 0, "output": 0, "cached": 0, "cache_write": 0}
        budget, seen = self.max_tokens * 5, 0
        async for chunk in stream:
            if seen > budget:
                stop = HARNESS_CAP
                await stream.close()
                break
            if u := getattr(chunk, "usage", None):
                details = u.prompt_tokens_details
                usage = {"input": u.prompt_tokens or 0, "output": u.completion_tokens or 0,
                         "cached": (details.cached_tokens or 0) if details else 0, "cache_write": 0}
            if not chunk.choices:
                continue
            ch = chunk.choices[0]
            d = ch.delta
            if ch.finish_reason:
                stop = ch.finish_reason
            if d is None:
                continue
            if d.content:
                content.append(d.content)
                seen += len(d.content)
            extra = getattr(d, "model_extra", None) or {}
            r = getattr(d, "reasoning_content", None) or extra.get("reasoning_content") or extra.get("reasoning")
            if isinstance(r, str):
                reasoning.append(r)
                seen += len(r)
            for tc in d.tool_calls or []:
                e = calls.setdefault(tc.index or 0, {"id": "", "name": "", "args": ""})
                if tc.id:
                    e["id"] = tc.id
                if tc.function and tc.function.name:
                    e["name"] = tc.function.name if not e["name"] else e["name"]
                if tc.function and tc.function.arguments:
                    e["args"] += tc.function.arguments
        text = "".join(content)
        think = "".join(reasoning)
        if not think and "</think>" in text:
            think, text = text.split("</think>", 1)
            think = think.replace("<think>", "")
        out = []
        for i in sorted(calls):
            e = calls[i]
            args, err = _args(e["args"])
            out.append(Call(e["id"] or f"call_{uuid.uuid4().hex[:8]}", e["name"], args, err, e["args"]))
        msg: dict[str, Any] = {"role": "assistant", "content": text}
        if out:
            msg["tool_calls"] = [{"id": c.id, "type": "function",
                                  "function": {"name": c.name, "arguments": "{}" if c.error else c.raw or "{}"}}
                                 for c in out]
        self.messages.append(msg)
        return Turn(text, think, out, stop, usage)


def route(model: str) -> str:
    return "messages" if model.startswith("anthropic/") else "responses" if model.startswith("openai/") else "chat"


def effort_of(model: str, effort: str | None) -> str | None:
    """The reasoning effort a request carries: the task's, else medium on the Responses API, else the provider's."""
    return effort or ("medium" if route(model) == "responses" else None)


def make_agent(model: str, tools, system: str, max_tokens: int, effort: str | None, root: str, key: str,
               cache: bool = False):
    if route(model) == "messages":
        return AnthropicAgent(model, tools, system, max_tokens, root, key, effort, cache)
    if route(model) == "responses":
        return OpenAIResponsesAgent(model, tools, system, max_tokens, f"{root}/v1", key, effort or "medium")
    return ChatAgent(model, tools, system, max_tokens, f"{root}/v1", key, effort)


def size_of(request: dict) -> int:
    return len(json.dumps(request, default=lambda o: o.model_dump(mode="json")).encode())


def estimate(agent, size: int, last: tuple[int, int] | None, cached: bool, price: tuple[float, float, float]) -> float:
    """What a request of ``size`` bytes likely costs at most: the last request's measured input tokens (``last`` is
    (tokens, bytes)) at the cache-read rate when ``cached`` (the provider reports caching and the cache is warm), else
    fresh; the bytes added since at BYTES_PER_TOKEN a token, fresh (a cache write on Messages); and its output limit in
    output tokens."""
    tokens, sent = last or (0, 0)
    fresh = max(0, size - sent) / BYTES_PER_TOKEN + (0 if cached else tokens)
    out = agent.max_tokens * (5 if agent.route == "chat" else 1)
    return ((tokens if cached else 0) * price[2] + fresh * price[0] * (1.25 if agent.route == "messages" else 1)
            + out * price[1]) / 1e6


def cost(usage: dict, price: tuple[float, float, float]) -> float:
    fresh = usage["input"] - usage["cached"] - usage["cache_write"]
    return (fresh * price[0] + usage["cached"] * price[2] + usage["cache_write"] * 1.25 * price[0]
            + usage["output"] * price[1]) / 1e6


PROVIDER_ERRORS = (anthropic.APIError, openai.APIError, httpx.HTTPError, httpx2.HTTPError, ProviderError)
REFUSED = {401, 402, 403}  # the key or the account: nothing billed, and a retry gets the same answer
STREAM_RETRIES = 2


def mid_stream(error: BaseException) -> bool:
    """A reply cut or failed after its stream began: the SDKs' retries end where the stream starts, and no tool has run
    on it, so the same request can be sent again."""
    return not isinstance(error, (anthropic.APIStatusError, openai.APIStatusError, anthropic.APIConnectionError,
                                  openai.APIConnectionError))


# ================================================================ episode

class Episode:
    def __init__(self, config: GridSimConfig, environ: dict[str, str]):
        self.config, self.model = config, config.model
        self.base, self.key = environ.get("LITELLM_BASE_URL", ""), environ.get("LITELLM_API_KEY", "")
        cap = environ.get("GRIDSIM_MAX_COST_USD")
        self.max_cost = None if cap is None else float(cap)
        self.effort = effort_of(self.model, config.effort)
        self.started = time.time()
        self.record: dict[str, Any] = {"model": self.model, "effort": self.effort, "messages": [], "steps": [],
                                       "final": {"submitted": False, "schedule": None},
                                       "usage": {"input_tokens": 0, "output_tokens": 0}, "turns": 0,
                                       "end_reason": None, "errors": []}
        self.live = self.commit_da = self.caching = False
        self.last: tuple[int, int] | None = None
        self.last_at = 0.0
        self.reward: float | None = None
        self.tool_calls = self.checks = self.cached = self.written = 0
        self.spent = self.unbilled = 0.0
        self.failed_requests = 0
        self.failure: tuple[str, str] | None = None
        self.error: str | None = None

    def describe(self, error: BaseException) -> str:
        return f"{type(error).__name__}: {str(error).replace(self.key, '<LITELLM_API_KEY>')[:800]}"

    def fail(self, code: str, message: str | None = None, error: BaseException | None = None) -> None:
        if error is not None:
            self.error = self.describe(error)
            self.record["errors"].append(self.error)
        self.failure = (code, message or self.error)
        self.record["end_reason"] = code

    async def run(self, server: dict, opening: str) -> None:
        if not self.base or not self.key:
            return self.fail("model_endpoint", "no model endpoint: agent-env passes LITELLM_BASE_URL and "
                                               "LITELLM_API_KEY ([model] in .agentenv/config.toml)")
        if self.model not in PRICES:
            return self.fail("unpriced_model", f"no price for {self.model}; priced: {', '.join(PRICES)}")
        try:
            async with httpx.AsyncClient(headers=server.get("headers"), timeout=300) as http, \
                    streamable_http_client(server["url"], http_client=http) as (read, write, _), \
                    ClientSession(read, write) as session:
                await session.initialize()
                await self.play(EnvSession(session), opening)
        except* (McpError, httpx.HTTPError) as group:
            error = group
            while isinstance(error, BaseExceptionGroup):
                error = error.exceptions[0]
            self.fail("env_error", error=error)

    async def play(self, env: EnvSession, opening: str) -> None:
        system = self.config.system_prompt
        self.record["messages"] += [{"role": "system", "content": system}, {"role": "user", "content": opening}]
        tools = await env.tools()
        self.record["tools"] = [{"name": t.name, "description": t.description, "input_schema": t.input_schema}
                                for t in tools]
        self.live = any(t.name == "advance" for t in tools)
        self.commit_da = any(t.name == "commit_da" for t in tools)
        limit = self.config.model_params["max_tokens"]
        agent = make_agent(self.model, tools, system, min(limit, MAX_OUTPUT.get(self.model, limit)), self.effort,
                           self.base.rstrip("/").removesuffix("/v1"), self.key, self.live)
        agent.user(opening)
        async with agent.client:
            await self.turns(env, agent)

    async def turns(self, env: EnvSession, agent) -> None:
        config, record, price = self.config, self.record, PRICES[self.model]
        mode = (LIVE if self.commit_da else HYBRID) if self.live else V1
        max_turns = config.max_turns
        empty = 0
        for turn in range(max_turns):
            elapsed = time.time() - self.started
            if self.live and elapsed > config.timeout_seconds - TIME_MARGIN:
                record["end_reason"] = "time_limit"
                break
            if elapsed > config.timeout_seconds:
                return self.fail("wall_clock",
                                 f"turn {turn + 1} would start after the {config.timeout_seconds} s limit")
            last = turn == max_turns - 1
            if last:
                agent.user(mode.last_turn)
                record["messages"].append({"role": "user", "content": mode.last_turn})
            request = agent.request()
            size = size_of(request)
            warm = self.caching and time.monotonic() - self.last_at < CACHE_SECONDS
            most = estimate(agent, size, self.last, warm, price)
            if self.max_cost is not None and self.spent + most > self.max_cost:
                return self.fail("cost_cap", f"the next request could cost ${most:.4f}, past the ${self.max_cost:g} "
                                             f"cap with ${self.spent:.4f} spent")
            for resend in range(STREAM_RETRIES + 1):
                try:
                    t = await agent.step(request)
                    break
                except PROVIDER_ERRORS as e:
                    if getattr(e, "status_code", None) in REFUSED:
                        return self.fail("provider_refused", error=e)
                    self.spent += most
                    self.unbilled += most
                    self.failed_requests += 1
                    if resend == STREAM_RETRIES or not mid_stream(e) or (
                            self.max_cost is not None and self.spent + most > self.max_cost):
                        return self.fail("provider_error", error=e)
                    self.record["errors"].append(f"{self.describe(e)} (turn {turn + 1} sent again)")
                    log.warning("turn %d: the reply failed mid-stream, sending it again", turn + 1)
            self.spent += most if t.stop == HARNESS_CAP else cost(t.usage, price)
            self.last, self.last_at = (t.usage["input"] or round(size / BYTES_PER_TOKEN), size), time.monotonic()
            self.caching = self.caching or bool(t.usage["cached"] or t.usage["cache_write"])
            self.cached += t.usage["cached"]
            self.written += t.usage["cache_write"]
            record["turns"] += 1
            record["usage"]["input_tokens"] += t.usage.get("input", 0)
            record["usage"]["output_tokens"] += t.usage.get("output", 0)
            record["messages"].append({"role": "assistant", "content": t.text, "reasoning": t.reasoning, "stop": t.stop,
                                       "tool_calls": [{"id": c.id, "name": c.name,
                                                       "arguments": c.raw or json.dumps(c.arguments)}
                                                      for c in t.calls]})
            log.info("turn %d: %d tool calls, stop %s, $%.4f spent", turn + 1, len(t.calls), t.stop, self.spent)
            if not t.calls:
                empty += 1
                if empty >= 2 or last:
                    record["end_reason"] = "no_tool_call"
                    break
                if t.stop.startswith("length") and t.reasoning:
                    agent.notes(t.reasoning[-NOTES_CHARS:])
                    nudge = mode.cut_off
                else:
                    nudge = mode.no_call
                agent.user(nudge)
                record["messages"].append({"role": "user", "content": nudge})
                continue
            empty = 0
            pairs, done = [], False
            for c in t.calls:
                if done:
                    out = json.dumps({"error": "the episode is over"})
                elif c.error:
                    out = json.dumps({"error": c.error})
                else:
                    out = await env.call(c.name, c.arguments)
                    res = _result(out)
                    record["steps"].append({"t": self.tool_calls, "turn": turn + 1, "call_id": c.id, "tool": c.name,
                                            "args": c.arguments, "output": res})
                    self.tool_calls += 1
                    if c.name == "check_schedule":
                        self.checks += 1
                    if self.live and c.name == "advance" and isinstance(res, dict) and res.get("done") is True:
                        done = True
                        self.reward = float(res["reward"])
                        record["final"] = {"done": True, "reward": self.reward}
                        record["end_reason"] = "done"
                    elif c.name == SUBMIT and isinstance(res, dict) and res.get("submitted") is True:
                        done = True
                        record["final"] = {"submitted": True, "schedule": c.arguments.get("actions")}
                        record["end_reason"] = "submitted"
                    elif not self.live and self.tool_calls >= MAX_TOOL_CALLS:
                        done = True
                        record["end_reason"] = "tool_call_limit"
                left = max_turns - turn - 1
                text = out if done else f"{out}\n(turns left: {left})"
                pairs.append((c, text))
                record["messages"].append({"role": "tool", "tool_call_id": c.id, "name": c.name, "content": out})
            agent.results(pairs)
            if done:
                break
        else:
            record["end_reason"] = record["end_reason"] or "turn_limit"

    def result(self) -> TaskResult:
        record = self.record
        record["seconds"] = round(time.time() - self.started, 1)
        usage = record["usage"]
        summary = {"agent": "gridsim-llm", "model": self.model, "route": route(self.model), "effort": self.effort,
                   "end_reason": record["end_reason"], "submitted": record["end_reason"] == "submitted",
                   "turns": record["turns"], "tool_calls": self.tool_calls, "checks": self.checks,
                   "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                   "cached_tokens": self.cached, "cache_write_tokens": self.written, "cost_usd": round(self.spent, 6),
                   "max_cost_usd": self.max_cost, "priced_cost_usd": round(self.spent - self.unbilled, 6),
                   "failed_requests": self.failed_requests, "seconds": record["seconds"], "error": self.error}
        if self.live:
            summary |= {"live": True, "reward": self.reward}
        text = (f"{record['end_reason']}: {record['turns']} turns, {self.tool_calls} tool calls, ${self.spent:.4f} "
                f"({self.model})")
        builder = TaskResult.builder()
        builder = builder.failed(*self.failure, error_type="infra_error") if self.failure else builder.succeeded()
        return (builder.add_text(text).add_structured_output(summary)
                .usage(Usage(tool_call_count=self.tool_calls, input_tokens=usage["input_tokens"],
                             output_tokens=usage["output_tokens"],
                             total_tokens=usage["input_tokens"] + usage["output_tokens"],
                             cost_usd=round(self.spent, 6),
                             provider_details={"cached_tokens": self.cached, "cache_write_tokens": self.written}))
                .native_trajectory(format="gridsim-rollout", payload=record).build())


@a2a_agent(
    identity=AgentIdentity(
        name="gridsim-llm",
        description="GridSim's harness loop: a model runs one battery at an ERCOT hub or load zone for a day through "
                    "the env's tools, on agent-env's model endpoint.",
        version="0.1.0",
    ),
    config=GridSimConfig,
    extensions=(MCP_CONFIG_V1, TRAJECTORY_V1),
)
class GridSimLLM(AgentEnvAgent):
    async def run(self, request: TaskRequest[GridSimConfig]) -> TaskResult:
        [part] = request.parts
        [server] = request.mcp_servers.values()
        episode = Episode(request.config, dict(os.environ))
        await episode.run(server, part.text)
        return episode.result()


if __name__ == "__main__":
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log.setLevel(logging.INFO)
    GridSimLLM().serve()
