"""One desk bench run's report: the framework's task instance (prompt responses, post-turn hook records, the verifier's
grade and Episode JSON, the harness's per-turn trajectories) joined with the model proxy's per-call log.

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
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from gridsim_core.desk import load_series, load_task, policies

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
    task = load_task(a.pack, a.task) if a.pack else None
    idle = policies.run(task, load_series(a.pack, task), "idle").episode() if task else None
    ran = re.findall(r"\] (?:passed|failed|scored below 1|cancelled) in ([\d.]+)s", run_log)
    return {
        "harness": a.harness, "instance_id": inst.get("instance_id"), "status": inst.get("status"),
        "error": inst.get("error"), "completed_steps": inst.get("completed_steps"), "total_steps": inst.get("total_steps"),
        "wall_s": float(ran[-1]) if ran else None,
        "step_seconds": steps,
        "grade": {k: grade.get(k) for k in ("reward", "capture", "capture_phys", "p", "p_idle", "p_anchor", "p_hind",
                                            "p_hind_phys", "p_operator_replay", "valid") if k in grade},
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
