"""One desk bench run's report from what the run recorded: the framework's task instance (prompt responses, post-turn
hook records, the verifier's grade and Episode JSON) and the harness's per-turn trajectories, whose usage gives the
tokens and, at public list prices (LiteLLM's price map), the cost; a model proxy's per-call log joins it when given.

    python scripts/desk_bench_report.py --state <XDG_STATE_HOME> --run-log <run.log> --proxy-log <run.jsonl> \
        --harness codex-luna --out report.json

Counts tool calls by kind (desk MCP tools versus the harness's own), checks the harness kept one session across wakes
(one session id in every turn's trajectory, the conversation growing in the proxy log), and sets the env's wakes beside
the hook's and the harness's turns and beside the wakes the desk's fixed milestones alone would give (the idle policy)."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from desk_bench import pack_source
from gridsim_core.desk import load_series, load_task, policies

PRICES = {"claude-opus-5-5": {"in": 4.0, "cached": 0.2, "write": 5.0, "write_1h": 8.0, "out": 20.0},
          "gpt-6.1-sol": {"in": 2.0, "cached": 0.1, "write": 2.5, "out": 10.0,
                          "above": 272000, "tier": {"in": 4.0, "cached": 0.2, "write": 5.0, "out": 15.0}},
          "gpt-6-luna": {"in": 0.1, "cached": 0.01, "write": 0.125, "out": 0.5,
                         "above": 272000, "tier": {"in": 0.2, "cached": 0.02, "write": 0.25, "out": 0.75}},
          "gemini-4-argon": {"in": 2.0, "cached": 0.1, "write": 0.0, "out": 10.0},
          "beam-1.0-501b-a23b": {"in": 0.4, "cached": 0.4, "write": 0.4, "out": 1.2},
          "glm-5.3": {"in": 1.4, "cached": 0.26, "write": 1.4, "out": 4.4},
          "kimi-k3": {"in": 3.0, "cached": 0.3, "write": 3.0, "out": 15.0},
          "qwen3.8-max": {"in": 2.0, "cached": 0.25, "write": 2.0, "out": 6.0},
          "qwen3-4b": {"in": 0.0, "cached": 0.0, "write": 0.0, "out": 0.0}}
DESK_TOOLS = ("get_prices", "get_forecasts", "get_grid_conditions", "get_asset_status", "get_position",
              "submit_dam_offers", "submit_rt_offers", "update_cop", "check_submission", "optimize", "set_reminder")
BUDGET = "budget: end your turn"


def desk_tool(name: str) -> str | None:
    return next((t for t in DESK_TOOLS if name == t or name.endswith("_" + t)), None)


def instance(state: Path, run_log: str) -> dict:
    ids = re.findall(r"instance (@local/\S+)", run_log)
    if not ids:
        raise SystemExit("no instance id in the run log")
    con = sqlite3.connect(state / "agent-env" / "document_store" / "local.db")
    for (doc,) in con.execute("select doc from docs_task_instances"):
        d = json.loads(doc)
        if d.get("instance_id") == ids[-1]:
            return d
    raise SystemExit(f"instance {ids[-1]} not in the store")


def calls_of(event: dict) -> list[tuple[str, bool]]:
    """The tool calls one trajectory event records, as (name, failed)."""
    t = event.get("type")
    if t == "assistant":
        return [(c.get("name", "?"), False) for c in (event.get("message") or {}).get("content") or []
                if isinstance(c, dict) and c.get("type") == "tool_use"]
    if t == "item.completed":
        item = event.get("item") or {}
        kind = item.get("type")
        failed = item.get("status") in ("failed", "error") or bool(item.get("error"))
        if kind == "mcp_tool_call":
            return [(f"{item.get('server')}_{item.get('tool')}", failed)]
        if kind in ("command_execution", "file_change", "web_search", "collab_tool_call", "todo_list"):
            return [(kind, failed)]
        return []
    if t == "tool_use":
        part = event.get("part")
        if isinstance(part, dict):
            state = part.get("state") or {}
            return [(part.get("tool", "?"), state.get("status") == "error")]
        return [(event.get("tool_name", "?"), False)]
    return []


def session_of(event: dict) -> str | None:
    if event.get("type") == "system" and event.get("subtype") == "init":
        return event.get("session_id")
    if event.get("type") == "thread.started":
        return event.get("thread_id")
    if event.get("type") == "init":
        return event.get("session_id")
    return event.get("sessionID")


def trajectories(prompt_response: dict) -> list[list[dict]]:
    out = []
    for url in prompt_response.get("target_agent_per_turn_trajectory_object_urls") or []:
        path = Path(urlparse(url).path) if url else None
        events = json.loads(path.read_text()) if path and path.exists() else []
        out.append(events if isinstance(events, list) else events.get("events", []))
    return out


def harness_side(turns: list[list[dict]]) -> dict:
    tools, sessions, errors, compactions = Counter(), [], 0, 0
    for events in turns:
        ids = {s for e in events if isinstance(e, dict) and (s := session_of(e))}
        sessions.append(sorted(ids))
        for e in events:
            if not isinstance(e, dict):
                continue
            for name, failed in calls_of(e):
                tools[name] += 1
                errors += failed
            if "compact" in json.dumps({k: e.get(k) for k in ("type", "subtype")}).lower():
                compactions += 1
            if e.get("type") == "item.completed" and (e.get("item") or {}).get("type") == "context_compaction":
                compactions += 1
    desk = Counter()
    builtin = Counter()
    for name, n in tools.items():
        (desk if desk_tool(name) else builtin)[desk_tool(name) or name] += n
    distinct = {s for ids in sessions for s in ids}
    return {"turns": len(turns), "desk_calls": sum(desk.values()), "builtin_calls": sum(builtin.values()),
            "desk_by_tool": dict(desk.most_common()), "builtin_by_tool": dict(builtin.most_common()),
            "failed_calls": errors, "compaction_events": compactions, "session_ids": sorted(distinct),
            "turns_with_session_id": sum(1 for ids in sessions if ids)}


def usage_of(turns: list[list[dict]], model: str) -> dict:
    """Tokens from the turns' own usage records: Claude Code's per-turn result (and its cumulative total_cost_usd),
    Codex's turn.completed (cumulative over the thread), Gemini CLI's per-turn result stats (thinking is total less
    input and output) and OpenCode's per-step step_finish."""
    u, claude_cost, codex = Counter(), None, None
    for events in turns:
        for e in events:
            if not isinstance(e, dict):
                continue
            t = e.get("type")
            if t == "result" and "usage" in e:
                x = e["usage"]
                hour = (x.get("cache_creation") or {}).get("ephemeral_1h_input_tokens") or 0
                u.update({"input": x.get("input_tokens", 0), "cached": x.get("cache_read_input_tokens", 0),
                          "cache_write": x.get("cache_creation_input_tokens", 0), "cache_write_1h": hour,
                          "output": x.get("output_tokens", 0),
                          "reasoning": (x.get("output_tokens_details") or {}).get("thinking_tokens", 0)})
                claude_cost = max(claude_cost or 0, e.get("total_cost_usd") or 0)
            elif t == "result" and "stats" in e:
                s = e["stats"]
                thoughts = (s.get("total_tokens") or 0) - (s.get("input_tokens") or 0) - (s.get("output_tokens") or 0)
                u.update({"input": s.get("input", 0), "cached": s.get("cached", 0),
                          "output": (s.get("output_tokens") or 0) + thoughts, "reasoning": thoughts})
            elif t == "turn.completed":
                codex = e.get("usage") or {}
            elif t == "step_finish":
                tk = (e.get("part") or {}).get("tokens") or {}
                u.update({"input": tk.get("input", 0), "cached": (tk.get("cache") or {}).get("read", 0),
                          "cache_write": (tk.get("cache") or {}).get("write", 0),
                          "output": tk.get("output", 0) + tk.get("reasoning", 0), "reasoning": tk.get("reasoning", 0)})
    if codex is not None:
        cached, write = codex.get("cached_input_tokens", 0), codex.get("cache_write_input_tokens", 0)
        u = Counter({"input": codex.get("input_tokens", 0) - cached - write, "cached": cached, "cache_write": write,
                     "output": codex.get("output_tokens", 0), "reasoning": codex.get("reasoning_output_tokens", 0)})
    return {"tokens": dict(u), "cost_usd_list_price": list_price(u, model),
            "claude_code_total_cost_usd": claude_cost,
            "note": "Codex counts are its cumulative thread totals; per-call long-context tiers are not applied"}


def list_price(tokens: dict, model: str | None) -> float | None:
    p = next((v for k, v in PRICES.items() if k in (model or "")), None)
    if p is None:
        return None
    u = Counter(tokens)
    hour = u["cache_write_1h"]
    return round((u["input"] * p["in"] + u["cached"] * p["cached"] + (u["cache_write"] - hour) * p["write"]
                  + hour * p.get("write_1h", p["write"]) + u["output"] * p["out"]) / 1e6, 4)


def proxy_side(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    model_rows = [r for r in rows if r["req"]]
    tot = Counter()
    for r in model_rows:
        for k, v in (r.get("usage") or {}).items():
            tot[k] += v or 0
    prompt = [sum((r.get("usage") or {}).get(k, 0) for k in ("input", "cached", "cache_write")) for r in model_rows]
    effort = Counter(json.dumps({k: r["req"].get(k) for k in ("reasoning", "output_config", "thinking",
                                                              "generationConfig", "temperature", "top_p", "top_k",
                                                              "chat_template_kwargs") if k in r["req"]},
                                sort_keys=True) for r in model_rows)
    tools = Counter(tuple(r["req"].get("tools") or []) for r in model_rows)
    t = [datetime.fromisoformat(r["t"].replace("Z", "+00:00")) for r in rows]
    return {"calls": len(model_rows), "errors": [{"t": r["t"], "status": r["status"], "err": (r.get("err") or "")[:300]}
                                                 for r in rows if r["status"] >= 400],
            "tokens": dict(tot), "cost_usd": round(sum(r.get("cost") or 0 for r in model_rows), 4),
            "max_prompt_tokens": max(prompt, default=0),
            "prompt_tokens_by_call": prompt,
            "request_settings": [{"settings": json.loads(k), "calls": n} for k, n in effort.most_common()],
            "tool_lists": [{"tools": list(k), "calls": n} for k, n in tools.most_common()],
            "models": dict(Counter(r["req"].get("model") for r in model_rows)),
            "first_call": rows[0]["t"] if rows else None, "last_call": rows[-1]["t"] if rows else None,
            "span_s": round((max(t) - min(t)).total_seconds()) if t else 0}


def report(a) -> dict:
    run_log = Path(a.run_log).read_text()
    inst = instance(Path(a.state), run_log)
    ctx = inst.get("context") or {}
    md = ctx.get("metadata") or {}
    play = next((p for p in ctx.get("prompt_responses") or [] if p.get("step_id") == "play"), {})
    hooks = (md.get("post_turn_hooks") or {}).get("play") or []
    verification = (md.get("verifications") or {}).get("gridsim-desk") or {}
    rows = verification.get("results") or []
    first = rows[0] if rows else {}
    grade = (first.get("metadata") or {}).get("grade") or {}
    episode = first.get("episode") or {}
    steps = {m.group(2): float(m.group(3)) for m in re.finditer(r"step (\d+)/\d+ (\S+) \(\S+\)\n.*?step \1/\d+ \2 done in ([\d.]+)s",
                                                                  run_log, re.S)}
    ep_turns = episode.get("turns") or []
    ep_calls = [c for t in ep_turns for c in t.get("calls") or []]
    idle = None
    if a.pack:
        with tempfile.TemporaryDirectory() as tmp:
            pack = pack_source(a.pack, Path(tmp))
            task = load_task(pack, a.task)
            idle = policies.run(task, load_series(pack, task), "idle").episode()
    ran = re.findall(r"\] (?:passed|failed|scored below 1|cancelled) in ([\d.]+)s", run_log)
    return {
        "harness": a.harness, "instance_id": inst.get("instance_id"), "status": inst.get("status"),
        "error": inst.get("error"), "completed_steps": inst.get("completed_steps"), "total_steps": inst.get("total_steps"),
        "wall_s": float(ran[-1]) if ran else None,
        "step_seconds": steps,
        "grade": grade,
        "wakes": {"env_episode": len(episode.get("wakes") or []),
                  "env_reasons": dict(Counter(r for w in episode.get("wakes") or [] for r in w.get("reasons") or [])),
                  "hook_delivered": sum(1 for h in hooks if h.get("reasons")) + 1,
                  "hook_end": [h.get("end") for h in hooks if h.get("end")],
                  "harness_turns": len(play.get("target_agent_per_turn_trajectory_object_urls") or []),
                  "idle_policy_milestones": len(idle["wakes"]) if idle else None,
                  "agent_reminders_set": sum(1 for c in ep_calls if c.get("tool") == "set_reminder" and c.get("ok"))},
        "env_calls": {"total": len(ep_calls), "by_tool": dict(Counter(c.get("tool") for c in ep_calls).most_common()),
                      "rejected_or_error": sum(1 for c in ep_calls if not c.get("ok")),
                      "budget_hits": sum(1 for c in ep_calls if BUDGET in json.dumps(c.get("result")))},
        "prompt_response": {k: play.get(k) for k in ("tool_call_count", "agent_session_id", "a2a_context_id",
                                                     "error_type", "error_code", "error_message", "model")},
        "harness": harness_side(trajectories(play)),
        "usage": usage_of(trajectories(play), play.get("model")),
        "proxy": proxy_side(Path(a.proxy_log) if a.proxy_log else None),
        "episode": episode if a.with_episode else {"keys": sorted(episode)},
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", required=True, help="the XDG_STATE_HOME agent-env ran with")
    ap.add_argument("--run-log", required=True, help="agent-env run's output, which names the instance")
    ap.add_argument("--proxy-log", help="the model proxy's JSONL for this run")
    ap.add_argument("--harness", required=True)
    ap.add_argument("--pack", help="the desk pack, for the idle policy's wakes")
    ap.add_argument("--task", help="the desk task id, with --pack")
    ap.add_argument("--with-episode", action="store_true", help="include the whole Episode JSON")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    a.out.write_text(json.dumps(report(a), indent=1, default=str) + "\n")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
