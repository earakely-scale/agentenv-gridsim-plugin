"""Desk bench: a desk pack's tasks for one native agent harness through AgentEnv, as a folder bundle a plain
`agent-env run` plays with a config.toml.

Each harness is a framework agent (claude-code, codex, gemini, opencode) on its model at its effort. The bundle holds:
- the pack's gridsim-desk tasks with the harness's agent and model, a `harness-config` load_artifact step that puts the
  harness's own configuration file into the agent's sandbox before the first turn (web search and fetch off; for Gemini
  the thinking level, for OpenCode the sampling, thinking and context limit, for Codex OpenAI's catalog entries for the
  GPT-6 models, which Codex 0.147 lacks), and the agent's network policy: an
  allowlist of the model endpoint's host (the sandbox platform adds its own tunnel hosts, where the env is reached);
- the gridsim-desk env itself, `envs/<env>/`, built where it deploys from the plugin's tree at desk-v4-freeze;
- a `netcheck` task that deploys the same env and agent and asks the agent to curl hosts outside the allowlist and to
  call a desk tool.
The hook and the verifier are gridsim-desk's, unchanged; the hook finds the task's one desk env itself, since a
bundle's env is deployed under its bundle-qualified id. The allowlist names each vendor's API host; `--allow-host`
replaces it, for a run whose model endpoint is elsewhere.

    python scripts/desk_bench.py tasks --harness codex-sol --pack desk-v4-pilot --out results/bundles/bench-codex-sol
    agent-env run results/bundles/bench-codex-sol --task netcheck
    agent-env run results/bundles/bench-codex-sol --task desk-v4-2026-02-03-S01
"""

from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from agentenv_gridsim.desk_tasks import generate

ROOT = Path(__file__).resolve().parent.parent
CONFIGS = ROOT / "bench" / "harness"
CONSTRAINTS = ROOT / "bench" / "env" / "constraints.txt"
AGENT_NAME = "default-agent"
FREEZE = "be6ff8c8ac2403da414b765009bcdc99e9cd9061"
REPO = "earakely-scale/agentenv-gridsim-plugin"
PACKS = {"desk-v4-bench": "629630ab7662aa1f6ff5db2a5d16be69a7e0f0bb"}
HARNESSES = {
    "claude-code": {"agent": "claude-code", "model": "claude-opus-5-5", "effort": "high",
                    "config": ("bench-claude-code", "/etc/claude-code"), "hosts": ["api.anthropic.com"]},
    "codex-sol": {"agent": "codex", "model": "gpt-6.1-sol", "effort": "high",
                  "config": ("bench-codex-catalog", "/etc/codex"), "hosts": ["api.openai.com"]},
    "codex-luna": {"agent": "codex", "model": "gpt-6-luna", "effort": "high",
                   "config": ("bench-codex-catalog", "/etc/codex"), "hosts": ["api.openai.com"]},
    "gemini": {"agent": "gemini", "model": "gemini-4-argon", "effort": None, "config": ("bench-gemini", "/etc/gemini-cli"),
               "hosts": ["generativelanguage.googleapis.com"]},
    "opencode-qwen": {"agent": "opencode", "model": "qwen3-4b", "effort": None,
                      "config": ("bench-opencode", "/data/config/opencode"), "hosts": []},
    "opencode-qwen35": {"agent": "opencode", "model": "qwen3.5-9b", "effort": None,
                        "config": ("bench-opencode-qwen35", "/data/config/opencode"), "hosts": []},
}
NETCHECK = ("Run this exact command in your shell and include its complete output in your reply:\n\n"
            "for u in https://www.ercot.com https://github.com https://pypi.org/simple/ https://1.1.1.1; do "
            "curl -sS -m 20 -o /dev/null -w \"$u HTTP=%{http_code}\\n\" \"$u\" 2>&1; echo \"EXIT=$?\"; done\n\n"
            "Then call the desk's get_asset_status tool once and add the soc_mwh it returns.")
PACK_LAYER = f"""ADD https://codeload.github.com/{REPO}/tar.gz/{{commit}} /tmp/pack.tar.gz
RUN mkdir /tmp/pack && tar -xzf /tmp/pack.tar.gz -C /tmp/pack --strip-components=1 \\
    && cp -r /tmp/pack/data/desk/{{pack}} /app/gridsim_core/data/desk/{{pack}} && rm -rf /tmp/pack /tmp/pack.tar.gz
"""
ENV_TOML = 'environment_name = "{name}"\nenv_provider_type = "gateway"\n'
ENV_DOCKERFILE = f"""FROM python:3.12.16-slim@sha256:8523d6abeb48ceae0b7240d30c5808fc26cb79c1a635bacdf19cf3baecfbec07
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONPATH=/app
COPY constraints.txt /tmp/constraints.txt
RUN pip install -c /tmp/constraints.txt "agentenv-framework-protocol==0.1.370" "fastmcp==3.4.8" "mcp==1.30.0" \\
    "pydantic==2.13.5" "numpy>=2,<3" "highspy==1.15.1"
WORKDIR /app
ADD https://codeload.github.com/{REPO}/tar.gz/{FREEZE} /tmp/src.tar.gz
RUN mkdir /tmp/src && tar -xzf /tmp/src.tar.gz -C /tmp/src --strip-components=1 \\
    && cp /tmp/src/LICENSE /tmp/src/NOTICE /app/ && mkdir /app/gridsim_core && cp -r /tmp/src/data /app/gridsim_core/data \\
    && cp -r /tmp/src/src/gridsim_core/. /app/gridsim_core/ && cp -r /tmp/src/src/agentenv_gridsim /app/agentenv_gridsim \\
    && rm -rf /app/agentenv_gridsim/web /tmp/src /tmp/src.tar.gz
{{pack}}RUN useradd --create-home --uid 1000 gridsim
USER gridsim
EXPOSE 18765
CMD ["python", "-m", "agentenv_gridsim.server"]
"""


def config_step(h: dict) -> dict:
    artifact, destination = h["config"]
    return {"id": "harness-config", "type": "load_artifact", "agent_name": AGENT_NAME, "artifact_id": artifact,
            "destination_path": destination}


def harness_steps(steps: list[dict], h: dict, hosts: list[str]) -> list[dict]:
    out = []
    for step in steps:
        step = dict(step)
        if step["type"] == "deploy_agent":
            policy = {"mode": "allowlist", "allow_hosts": hosts}
            out += [step | {"a2a_agent_id": h["agent"], "network_policy": policy}, config_step(h)]
            continue
        if step["type"] == "prompt_agent":
            step.pop("model_params", None)
            step.pop("effort", None)
            step |= {"model": h["model"]} | ({"effort": h["effort"]} if h["effort"] else {})
            step["post_turn_hooks"] = [hook | {"params": {k: v for k, v in hook.get("params", {}).items() if k != "env_id"}}
                                       for hook in step.get("post_turn_hooks", [])]
        out.append(step)
    return out


def netcheck_steps(desk: list[dict], h: dict) -> list[dict]:
    setup = desk[:[s["id"] for s in desk].index("play")]
    return setup + [
        {"id": "ask", "type": "prompt_agent", "prompt_id": "netcheck", "prompt": NETCHECK, "model": h["model"],
         "timeout_seconds": 900} | ({"effort": h["effort"]} if h["effort"] else {}),
        {"id": "check", "type": "agent_prompt_response_verifier", "prompt_id": "netcheck", "verifier_id": "netcheck",
         "criteria": [{"type": "response_contains", "needles": ["EXIT="]}]}]


def pack_source(pack: str, tmp: Path) -> str:
    """A pack added after the freeze, read from its commit (the env image adds it from the same commit)."""
    if pack not in PACKS:
        return pack
    tar = subprocess.run(["git", "-C", str(ROOT), "archive", PACKS[pack], f"data/desk/{pack}"], check=True,
                         capture_output=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    return str(tmp / "data" / "desk" / pack)


def write(name: str, pack: str, out: Path, task_ids: list[str] | None, hosts: list[str] | None = None,
          codex_as_installed: bool = False) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        return _write(name, pack, out, task_ids, hosts, codex_as_installed, Path(tmp))


def _write(name: str, pack: str, out: Path, task_ids: list[str] | None, hosts: list[str] | None,
           codex_as_installed: bool, tmp: Path) -> list[str]:
    h = HARNESSES[name]
    if codex_as_installed and h["agent"] == "codex":
        h = h | {"config": ("bench-codex", "/etc/codex")}
    hosts = hosts or h["hosts"]
    if not hosts:
        raise SystemExit(f"{name} has no default model host: pass --allow-host")
    ids = generate(pack_source(pack, tmp), out, task_ids=task_ids)
    envs = set()
    for task_id in ids:
        path = out / "tasks" / f"{task_id}.json"
        steps = harness_steps(json.loads(path.read_text()), h, hosts)
        envs |= {s["env_id"] for s in steps if s["type"] == "deploy_env"}
        path.write_text(json.dumps(steps, indent=2, ensure_ascii=False) + "\n")
    first = json.loads((out / "tasks" / f"{ids[0]}.json").read_text())
    (out / "tasks" / "netcheck.json").write_text(json.dumps(netcheck_steps(first, h), indent=2, ensure_ascii=False) + "\n")
    for env in sorted(envs):
        folder = out / "envs" / env
        folder.mkdir(parents=True, exist_ok=True)
        layer = PACK_LAYER.format(commit=PACKS[pack], pack=pack) if pack in PACKS else ""
        (folder / "Dockerfile").write_text(ENV_DOCKERFILE.replace("{pack}", layer))
        shutil.copy(CONSTRAINTS, folder / "constraints.txt")
        (folder / "env.toml").write_text(ENV_TOML.format(name=env))
    artifact = h["config"][0]
    shutil.copytree(CONFIGS / artifact, out / "artifacts" / artifact, dirs_exist_ok=True)
    readme = out / "README.md"
    readme.write_text(readme.read_text() + f"\nHarness {name}: agent {h['agent']}, model {h['model']}, effort "
                      f"{h['effort'] or 'harness default'}; {artifact} loaded into {h['config'][1]}; the agent's "
                      f"network allows {', '.join(hosts)} and the sandbox platform's tunnel hosts. The env "
                      f"{', '.join(sorted(envs))} builds where it deploys from {REPO} at {FREEZE[:7]} (desk-v4-freeze)"
                      + (f", with the {pack} pack from {PACKS[pack][:7]}" if pack in PACKS else "") + ".\n")
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tasks", help="write a harness's bundle for a desk pack")
    t.add_argument("--harness", required=True, choices=sorted(HARNESSES))
    t.add_argument("--pack", required=True)
    t.add_argument("--task", action="append", dest="task_ids")
    t.add_argument("--allow-host", action="append", dest="hosts", help="the model endpoint's host (repeatable), in "
                   "place of the harness vendor's API host")
    t.add_argument("--codex-as-installed", action="store_true", help="run Codex on its own model metadata, without "
                   "OpenAI's catalog entries for the GPT-6 models")
    t.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    ids = write(a.harness, a.pack, a.out, a.task_ids, a.hosts, a.codex_as_installed)
    print(f"Wrote {len(ids)} desk tasks and netcheck into {a.out}")


if __name__ == "__main__":
    main()
