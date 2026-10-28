"""Desk bench: a desk pack's tasks for one native agent harness through AgentEnv, as a folder bundle.

Each harness is a framework agent (claude-code, codex, gemini, opencode) on its model at its effort. The bundle holds the
pack's gridsim-desk tasks with the harness's agent and model, plus a `harness-config` load_artifact step that puts the
harness's own configuration file into the agent's sandbox before the first turn (web search and fetch off; for Gemini
the thinking level, for OpenCode the sampling, thinking and context limit), and a `netcheck` task that deploys the same
agent with the same configuration and asks it to curl www.ercot.com from its shell. The env, the hook and the verifier
are gridsim-desk's, unchanged.

    python scripts/desk_bench.py tasks --harness codex-sol --pack desk-v4-pilot --out results/bundles/bench-codex-sol
    agent-env run results/bundles/bench-codex-sol --task netcheck
    agent-env run results/bundles/bench-codex-sol --task desk-v4-2026-02-03-S01
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from agentenv_gridsim.desk_tasks import generate

CONFIGS = Path(__file__).resolve().parent.parent / "bench" / "harness"
AGENT_NAME = "default-agent"
HARNESSES = {
    "claude-code": {"agent": "claude-code", "model": "claude-opus-5-5", "effort": "high",
                    "config": ("bench-claude-code", "/etc/claude-code")},
    "codex-sol": {"agent": "codex", "model": "gpt-6.1-sol", "effort": "high", "config": ("bench-codex", "/etc/codex")},
    "codex-luna": {"agent": "codex", "model": "gpt-6-luna", "effort": "high", "config": ("bench-codex", "/etc/codex")},
    "gemini": {"agent": "gemini", "model": "gemini-4-argon", "effort": None, "config": ("bench-gemini", "/etc/gemini-cli")},
    "opencode-qwen": {"agent": "opencode", "model": "qwen3-4b", "effort": None,
                      "config": ("bench-opencode", "/data/config/opencode")},
}
NETCHECK = ("Run this exact command in your shell and reply with its complete output and nothing else:\n\n"
            "curl -sS -m 20 -o /dev/null -w 'HTTP=%{http_code}\\n' https://www.ercot.com; echo EXIT=$?")


def config_step(h: dict) -> dict:
    artifact, destination = h["config"]
    return {"id": "harness-config", "type": "load_artifact", "agent_name": AGENT_NAME, "artifact_id": artifact,
            "destination_path": destination}


def harness_steps(steps: list[dict], h: dict) -> list[dict]:
    out = []
    for step in steps:
        step = dict(step)
        if step["type"] == "deploy_agent":
            out += [step | {"a2a_agent_id": h["agent"]}, config_step(h)]
            continue
        if step["type"] == "prompt_agent":
            step.pop("model_params", None)
            step.pop("effort", None)
            step |= {"model": h["model"]} | ({"effort": h["effort"]} if h["effort"] else {})
        out.append(step)
    return out


def netcheck_steps(h: dict) -> list[dict]:
    return [{"id": "deploy-agent", "type": "deploy_agent", "a2a_agent_id": h["agent"], "env_ids": []}, config_step(h),
            {"id": "ask", "type": "prompt_agent", "prompt_id": "netcheck", "prompt": NETCHECK, "model": h["model"],
             "timeout_seconds": 900} | ({"effort": h["effort"]} if h["effort"] else {}),
            {"id": "check", "type": "agent_prompt_response_verifier", "prompt_id": "netcheck", "verifier_id": "netcheck",
             "criteria": [{"type": "response_contains", "needles": ["EXIT="]}]}]


def write(name: str, pack: str, out: Path, task_ids: list[str] | None) -> list[str]:
    h = HARNESSES[name]
    ids = generate(pack, out, task_ids=task_ids)
    for task_id in ids:
        path = out / "tasks" / f"{task_id}.json"
        path.write_text(json.dumps(harness_steps(json.loads(path.read_text()), h), indent=2, ensure_ascii=False) + "\n")
    (out / "tasks" / "netcheck.json").write_text(json.dumps(netcheck_steps(h), indent=2) + "\n")
    artifact = h["config"][0]
    shutil.copytree(CONFIGS / artifact, out / "artifacts" / artifact, dirs_exist_ok=True)
    readme = out / "README.md"
    readme.write_text(readme.read_text() + f"\nHarness {name}: agent {h['agent']}, model {h['model']}, effort "
                      f"{h['effort'] or 'harness default'}; {artifact} loaded into {h['config'][1]}.\n")
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tasks", help="write a harness's bundle for a desk pack")
    t.add_argument("--harness", required=True, choices=sorted(HARNESSES))
    t.add_argument("--pack", required=True)
    t.add_argument("--task", action="append", dest="task_ids")
    t.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    ids = write(a.harness, a.pack, a.out, a.task_ids)
    print(f"Wrote {len(ids)} desk tasks and netcheck into {a.out}")


if __name__ == "__main__":
    main()
