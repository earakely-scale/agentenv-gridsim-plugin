"""Build the Hugging Face dataset earakely-scale/GridSimEnv-AgentEnv into a folder, to look at before anything is
pushed. Two kinds of files share it:

- GridSim's, from this checkout: v1_tasks (every battery-day of the four packs at each tier it plays, with the
  battery, the prices, the blind inputs and the path-B prompt exactly as gridsim_core writes it), v1_showcase (the
  display-only famous days), v1_references (the DP optimum, the LP bound, the baselines and the blind anchors) and
  v1_episodes (each gridsim.episode/v1 JSON under --runs, graded again by gridsim_core before it is published, with
  its transcript as chat messages). Beside them, the Episode JSON the Space reads under runs/, the eval card and board
  under results/, and the packs as JSON lines under raw/packs/.
- agentenv-hf's, one pair per --bundle folder, as `agent-env hf publish` writes them: the bundle's tasks and runs and
  the bundle itself under bundles/, which `agent-env hf run` plays; the card's `agentenv` table names what it needs.

The card is hub/dataset/README.md, with the episode splits found, the bundles' configs and the board from
results/eval-v1.json filled in. Every file goes through agentenv-hf's scan for keys and token shapes before anything is
written. Nothing is pushed: upload the folder with `hf upload <repo> <out> --repo-type dataset` after reading it.

    uv run python scripts/hub_dataset.py --out build/hub/dataset
    agent-env gridsim tasks generate --pack ercot-dam-v1-eval --out build/bundles/ercot-dam-v1-eval
    uv run python scripts/hub_dataset.py --out build/hub/dataset --runs results/runs --results results \
        --bundle build/bundles/ercot-dam-v1-eval
"""

import argparse
import gzip
import io
import json
import re
import shutil
import tomllib
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pyarrow as pa
import pyarrow.parquet as pq
from agent_env.store.routing import namespace_routing
from agentenv_hf import dataset, runs, tables
from agentenv_hf.card import card
from agentenv_hf.messages import to_messages
from agentenv_hf.scan import known_values, scan
from huggingface_hub import DatasetCard

from gridsim_core import hybrid, hybrid_prompt, live, live_prompt
from gridsim_core.episode import SCHEMA
from gridsim_core.grade import grade, reward_value
from gridsim_core.prompt import messages, situation, tool_schemas
from gridsim_core.task import data_root

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "hub/dataset/README.md"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
SETUP = "agent-env gridsim setup --agent"
PACKS = {"train": "ercot-dam-v1-train", "eval_2025": "ercot-dam-v1-eval", "eval_iid": "ercot-dam-v1-eval-iid",
         "rtcb": "ercot-dam-v1-rtcb", "showcase": "showcase"}
SPLITS = ("train", "eval_2025", "eval_iid", "rtcb")
TIERS = ("foresight", "blind")
BATTERY = ("p_dis_mw", "p_ch_mw", "energy_mwh", "unit_mwh", "q_15", "k_dis", "k_ch", "soc_levels", "eta", "c_deg",
           "cycle_cap_units", "s0", "s_end_min")
UNITS = ("k_dis", "k_ch", "soc_levels", "cycle_cap_units", "s0", "s_end_min")
BASELINES = ("clock", "threshold", "greedy", "random")
PACK_FILES = ("stats.md", "ridge-v1.json")
TOLERANCE = 1e-6
BOARD = re.compile(r"(<!-- board:v1 -->\n).*?(\n<!-- /board:v1 -->)", re.S)
NAMES = {"openai/gpt-6.1-sol": "GPT-6.1 Sol", "Qwen/Qwen3-1.7B": "Qwen3-1.7B", "Qwen/Qwen3-4B": "Qwen3-4B"}
MANAGED = ("tasks", "references", "episodes", "runs", "results", "raw", "bundles", "training")

F64, I64, STR, BOOL = pa.float64(), pa.int64(), pa.string(), pa.bool_()
PROMPT = pa.list_(pa.struct([("role", STR), ("content", STR)]))
TASKS = pa.schema([
    ("task_id", STR), ("tier", STR), ("has_blind", BOOL), ("split", STR), ("date", STR), ("settlement_point", STR),
    ("point_kind", STR), ("region", STR), ("archetype", STR),
    *((k, I64 if k in UNITS else F64) for k in BATTERY),
    ("prices", pa.list_(F64)), ("dam_prev_day", pa.list_(F64)), ("dam_prev_7d", pa.list_(pa.list_(F64))),
    ("system_prompt", STR), ("situation", STR), ("prompt", PROMPT), ("tools", STR),
    ("curriculum", STR), ("difficulty", F64), ("season", STR), ("binding", STR), ("neg_hours", I64), ("spike", BOOL),
    ("era", STR), ("tags", STR), ("task", STR),
])
REFERENCES = pa.schema([
    ("task_id", STR), ("has_blind", BOOL), ("date", STR), ("settlement_point", STR), ("archetype", STR),
    ("p_idle", F64), ("p_opt", F64), ("p_lp", F64), ("opt", pa.list_(I64)),
    *((f"{b}_{k}", t) for b in BASELINES for k, t in (("profit", F64), ("reward", F64), ("schedule", pa.list_(I64)))),
    ("p_persist", F64), ("persist", pa.list_(I64)), ("p_ridge", F64), ("ridge", pa.list_(I64)), ("p_anchor", F64),
    ("anchor", STR), ("r_opt_anchor", F64), ("persist_reward", F64), ("persist_r_opt", F64), ("ridge_reward", F64),
    ("ridge_r_opt", F64),
])
EPISODES = pa.schema([
    ("episode_id", STR), ("task_id", STR), ("split", STR), ("tier", STR), ("bundle", STR), ("path", STR),
    ("model", STR), ("model_label", STR), ("trained", STR), ("checkpoint_step", I64), ("seed", I64),
    ("reward", F64), ("r_opt", F64),
    ("beats_anchor", BOOL), ("submitted", BOOL), ("feasible", BOOL), ("truncated_at", I64), ("violation", STR),
    ("end_shortfall_units", I64), ("profit_usd", F64), ("p_opt", F64), ("p_idle", F64), ("p_anchor", F64),
    ("final_schedule", pa.list_(I64)), ("soc_path", pa.list_(I64)), ("checks_used", I64), ("tool_calls", I64),
    ("steps", STR), ("messages", pa.list_(tables.MESSAGE)), ("transcript", STR), ("assistant_text", STR),
    ("input_tokens", I64), ("output_tokens", I64), ("usd", F64), ("wall_seconds", F64), ("file", STR),
])


class Mismatch(Exception):
    pass


def has_blind(task: dict) -> bool:
    return bool(task.get("blind") and (task["refs"].get("blind") or {}).get("p_anchor") is not None)


def task_row(task: dict, tier: str, raw: str) -> dict:
    """One battery-day at one tier, with the path-B prompt: the oneshot harness's system prompt and situation."""
    battery, tags, blind = task["battery"], task["tags"], task.get("blind") or {}
    prompt = messages(task, tier, 0)
    return {
        "task_id": task["task_id"], "tier": tier, "has_blind": has_blind(task), "split": task["split"],
        **{k: task[k] for k in ("date", "settlement_point", "point_kind", "region")},
        "archetype": battery["archetype"], **{k: battery[k] for k in BATTERY},
        "prices": task["prices"], "dam_prev_day": blind.get("dam_prev_day"), "dam_prev_7d": blind.get("dam_prev_7d"),
        "system_prompt": prompt[0]["content"], "situation": prompt[1]["content"], "prompt": prompt,
        "tools": json.dumps(tool_schemas(tier, 0)), "curriculum": task["curriculum"], "difficulty": task["difficulty"],
        **{k: tags.get(k) for k in ("season", "binding", "neg_hours", "spike", "era")},
        "tags": json.dumps(tags), "task": raw,
    }


def reference_row(task: dict) -> dict:
    f, b = task["refs"]["foresight"], task["refs"].get("blind") or {}
    row = {"task_id": task["task_id"], "has_blind": has_blind(task),
           **{k: task[k] for k in ("date", "settlement_point")}, "archetype": task["battery"]["archetype"],
           **{k: f[k] for k in ("p_idle", "p_opt", "p_lp", "opt")}}
    for name in BASELINES:
        row |= {f"{name}_{k}": f["baselines"][name][k] for k in ("profit", "reward", "schedule")}
    if not row["has_blind"]:
        return row
    row |= {k: b[k] for k in ("p_persist", "persist", "p_ridge", "ridge", "p_anchor", "r_opt_anchor")}
    row["anchor"] = "persist" if b["p_persist"] >= b["p_ridge"] else "ridge"
    for name in ("persist", "ridge"):
        g = grade(task, b[name], "blind")
        row |= {f"{name}_reward": g["reward"], f"{name}_r_opt": g["r_opt"]}
    return row


def parquet(rows: list[dict], schema: pa.Schema) -> bytes:
    """The rows as agentenv-hf types its tables, compressed with zstd: the task rows' JSON and prompts halve."""
    sink = io.BytesIO()
    pq.write_table(pq.read_table(io.BytesIO(tables.parquet(rows, schema))), sink, compression="zstd")
    return sink.getvalue()


def pack_lines(pack: str) -> list[str]:
    with gzip.open(data_root() / pack / "tasks.jsonl.gz", "rt") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def verify(e: dict, task: dict) -> dict:
    """gridsim_core's grade of the episode's schedule; Mismatch when the episode's situation, reward, hindsight capture
    or profit is not what gridsim_core gives."""
    tier, checks = e["tier"], e["situation"]["checks"]
    if tier == "blind" and not has_blind(task):
        raise Mismatch(f"blind episode of {task['task_id']}, which has no blind tier")
    if e["situation"] != situation(task, tier, checks):
        raise Mismatch("its situation is not gridsim_core's")
    g = grade(task, e["final_schedule"], tier)
    if abs(e["reward"] - g["reward"]) > TOLERANCE or abs((e["r_opt"] or 0.0) - g.get("r_opt", 0.0)) > TOLERANCE:
        raise Mismatch(f"reward {e['reward']}, r_opt {e['r_opt']}; gridsim_core {g['reward']}, {g.get('r_opt')}")
    if g["submitted"] and abs(e["profit_usd"] - g["profit"]) > TOLERANCE * max(1.0, abs(g["profit"])):
        raise Mismatch(f"profit {e['profit_usd']}; gridsim_core {g['profit']}")
    return g


def recorded(episode_file: Path, e: dict) -> dict | None:
    """The agent's own record of a path-A run, when its sweep's raw folder sits beside the episode: the transcript of
    the scored attempt whose instance id ends in the episode id."""
    raw = episode_file.parent / "raw"
    results = raw / "results.jsonl"
    if not results.is_file():
        return None
    for line in results.read_text().splitlines():
        row = json.loads(line)
        if row.get("outcome") == "scored" and (row.get("instance") or "").rsplit("/", 1)[-1] == e["episode_id"]:
            return json.loads((raw / row["transcript"]).read_text()) if row.get("transcript") else None
    return None


def rebuilt(e: dict, task: dict) -> list[dict]:
    """The chat as the Episode JSON has it: the prompts, then each tool call with its output; the agent's text goes on
    its calls only when there is one text per call, since the Episode JSON keeps no turn boundaries."""
    out = messages(task, e["tier"], e["situation"]["checks"])
    texts = [m["content"] for m in e.get("messages") or [] if m.get("role") == "assistant" and m.get("content")]
    paired = len(texts) == len(e["steps"])
    for i, step in enumerate(e["steps"]):
        call = f"call_{i}"
        out.append({"role": "assistant", "content": texts[i] if paired else None, "tool_calls": [
            {"id": call, "type": "function", "function": {"name": step["tool"], "arguments": step["args"]}}]})
        out.append({"role": "tool", "tool_call_id": call, "name": step["tool"],
                    "content": json.dumps(step["output"], ensure_ascii=False)})
    return out


def episode_row(e: dict, task: dict, g: dict, record: dict | None, file: str) -> dict:
    usage = e.get("usage") or {}
    refs = task["refs"]
    texts = [m["content"] for m in e.get("messages") or [] if m.get("role") == "assistant" and m.get("content")]
    return {
        **{k: e.get(k) for k in ("episode_id", "task_id", "tier", "bundle", "path", "model", "model_label", "trained",
                                 "checkpoint_step", "seed", "reward", "r_opt", "truncated_at", "violation",
                                 "end_shortfall_units", "profit_usd", "final_schedule", "soc_path")},
        "split": task["split"], "beats_anchor": g.get("beats_anchor"), "submitted": g["submitted"],
        "feasible": g.get("feasible"), "p_opt": refs["foresight"]["p_opt"], "p_idle": refs["foresight"]["p_idle"],
        "p_anchor": g.get("profit_anchor"), "checks_used": sum(s["tool"] == "check_schedule" for s in e["steps"]),
        "tool_calls": len(e["steps"]), "steps": json.dumps(e["steps"], ensure_ascii=False),
        "messages": to_messages(record) if record else to_messages(rebuilt(e, task)),
        "transcript": "record" if record else "rebuilt", "assistant_text": "\n\n".join(texts) or None,
        "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
        "usd": usage.get("usd"), "wall_seconds": e.get("wall_seconds"), "file": file,
    }


def episodes(runs_dir: Path, by_id: dict[str, dict]) -> tuple[list[dict], dict[str, bytes], list[dict]]:
    """Every gridsim.episode/v1 JSON under ``runs_dir`` (sweeps' raw folders skipped): its row, its file for the Space
    under runs/, and the Space's index of them. Raises at the first episode gridsim_core does not reproduce."""
    rows, files, index = [], {}, []
    paths = sorted(runs_dir.rglob("*.json")) if runs_dir.is_dir() else []
    for path in paths:
        rel = path.relative_to(runs_dir)
        if "raw" in rel.parts[:-1]:
            continue
        e = json.loads(path.read_text())
        if not isinstance(e, dict) or e.get("schema") != SCHEMA:
            continue
        task = by_id.get(e["task_id"])
        if task is None:
            raise Mismatch(f"{rel}: {e['task_id']} is not a task of the published packs")
        try:
            g = verify(e, task)
        except Mismatch as err:
            raise Mismatch(f"{rel}: {err}") from None
        file = f"runs/{rel.as_posix()}"
        rows.append(episode_row(e, task, g, recorded(path, e), file))
        files[file] = path.read_bytes()
        index.append({"path": rel.as_posix(), "episode_id": e["episode_id"], "task_id": e["task_id"],
                      "tier": e["tier"], "bundle": e["bundle"], "path_kind": e["path"], "model": e["model"],
                      "trained": e.get("trained"), "reward": e["reward"], "r_opt": e["r_opt"],
                      "profit_usd": e["profit_usd"], "date": task["date"],
                      "settlement_point": task["settlement_point"], "region": task["region"]})
    return rows, files, index


def bundle_split(name: str) -> str:
    """The split a bundle's tasks come from: the pack its name starts with, the longest that matches."""
    matches = [(len(pack), split) for split, pack in PACKS.items() if name == pack or name.startswith(pack + "-")]
    if not matches:
        raise SystemExit(f"--bundle {name}: name the folder after the pack it plays, e.g. {PACKS['eval_2025']}")
    return max(matches)[1]


def board_markdown(eval_card: dict) -> str:
    """The card's board: each column's headline, amended when the board was, then its pre-registered scoring and the
    baselines on its days, all from the eval card."""
    def f(x, fmt=".4f"):
        return "–" if x is None else format(x, fmt)

    def pct(x):
        return "–" if x is None else f"{100 * x:.1f}%"

    models = eval_card["models"]
    lines = ["| Column | Model | Pack | Tier | Harness | Battery-days | Mean reward (95% CI) | r_opt | Optimal | Valid "
             "| Beats anchor | $ per episode |", "|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for m in models:
        ci = f" ({f(m['ci95'][0])} to {f(m['ci95'][1])})" if m.get("ci95") else ""
        usd = "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}"
        lines.append(f"| {m.get('column') or ''} | {m.get('label') or NAMES.get(m['model'], m['model'])} | "
                     f"`{m['pack']}` | {m['tier']} | {m['bundle']} | {m['tasks']} | **{f(m['mean'])}**{ci} | "
                     f"{f(m['hindsight_capture'])} | {pct(m.get('optimal'))} | {pct(m['valid'])} | "
                     f"{pct(m.get('beats_anchor'))} | {usd} |")
    names = {"idle": "idle", "random": "random", "clock": "clock", "threshold": "threshold", "greedy": "greedy",
             "persistence_dp": "persistence-DP", "ridge_dp": "ridge-DP", "blind_anchor": "blind anchor"}
    lines += ["", "Baselines graded on each column's battery-days (mean reward; r_opt in brackets at the blind tier):",
              ""]
    for m in models:
        b = m.get("baselines") or {}
        parts = [f"{name} {f(b[k]['reward'], '.3f')}" + (f" ({f(b[k]['r_opt'], '.3f')})" if m["tier"] == "blind"
                                                         else "") + ("" if b[k]["n"] == m["planned"]
                                                                     else f" on {b[k]['n']}")
                 for k, name in names.items() if k in b]
        lines.append(f"- {m.get('column') or m['model']}: " + ", ".join(parts) + "; the DP optimum 1.000.")
    if amended := [m for m in models if m.get("prereg")]:
        a = eval_card.get("amendment") or {}
        caps = a.get("episode_cap_usd") or {}
        stopped = ", ".join(f"{k} {v}" for k, v in (a.get("stopped") or {}).items())
        lines += ["", f"The headline is the amended board. The pre-registered ${caps.get('prereg', 0):.2f} episode cap "
                  f"stopped runs before they submitted ({stopped}): the agent's own pre-request cost guard, not the "
                  f"model. Those runs were re-run once at ${caps.get('amended', 0):.2f} and all scored. The "
                  "pre-registered scoring, its scored runs only: " + "; ".join(
                      f"{m.get('column') or m['model']} {f(m['prereg']['mean'])} ({m['prereg']['runs']} of "
                      f"{m['prereg']['planned']})" for m in amended) + ". Dropping the stopped runs would bias the "
                  "blind column toward easy days, so the amended column is the headline."]
    return "\n".join(lines)


def card_text(files: dict[str, bytes], bundles: dict[str, str], plugin: str, board: str | None,
              blocks: dict[str, str] | None = None, preview_ref: str | None = None) -> str:
    """The card with each version's episodes config on the splits that have episodes, the board and the generated
    blocks when there are, the preview links on ``preview_ref``, and each bundle's configs and needs as agentenv-hf
    writes them. A config whose tables are all empty is left off: `datasets` can't load a parquet file with no rows."""
    text = CARD.read_text()
    if board:
        text = BOARD.sub(lambda m: f"{m[1]}{board}{m[2]}", text)
    for name, block in (blocks or {}).items():
        text = re.sub(rf"(<!-- {name} -->\n).*?(\n<!-- /{name} -->)", lambda m, b=block: f"{m[1]}{b}{m[2]}", text,
                      flags=re.S)
    if preview_ref:
        text = text.replace("/blob/PREVIEW_REF/", f"/blob/{preview_ref}/")
    for name, split in bundles.items():
        text = card(text, name=name, split=split, repo=None, description=None, license=None,
                    needs={"plugins": [plugin], "setup": SETUP})
    result = DatasetCard(text)
    episodes = {f"{v}_episodes": {"config_name": f"{v}_episodes", "data_files": [
        {"split": s, "path": f"episodes/{v}/{s}.parquet"} for s in splits if f"episodes/{v}/{s}.parquet" in files]}
        for v, splits in (("v1", (*SPLITS, "showcase")), ("v2", tuple(V2.packs)), ("v3", tuple(V3.packs)))}
    configs = [episodes.get(c["config_name"], c) for c in result.data.configs]
    result.data.configs = [c for c in configs if any(
        f["path"] in files and pq.read_metadata(io.BytesIO(files[f["path"]])).num_rows for f in c["data_files"])]
    if bundles:
        result.data.agentenv = {"default": next(iter(bundles)), **result.data.agentenv}
    return str(result)


def build(runs_dir: Path, results_dir: Path, bundle_dirs: list[Path], plugin: str,
          extras: "Extras | None" = None) -> dict[str, bytes]:
    """v1's files, then, unless ``extras`` is None, the v2 and v3 previews and the training summary, and the card."""
    files: dict[str, bytes] = {}
    by_id: dict[str, dict] = {}
    for split, pack in PACKS.items():
        lines = pack_lines(pack)
        tasks = [json.loads(line) for line in lines]
        by_id |= {t["task_id"]: t for t in tasks}
        rows = [task_row(t, tier, line) for tier in TIERS for t, line in zip(tasks, lines, strict=True)
                if tier == "foresight" or has_blind(t)]
        files[f"tasks/v1/{split}.parquet"] = parquet(rows, TASKS)
        files[f"references/v1/{split}.parquet"] = parquet([reference_row(t) for t in tasks], REFERENCES)
        files[f"raw/packs/{pack}.jsonl"] = ("\n".join(lines) + "\n").encode()
        files[f"raw/packs/{pack}.manifest.json"] = (data_root() / pack / "manifest.json").read_bytes()
    for name in PACK_FILES:
        files[f"raw/packs/{name}"] = (data_root() / name).read_bytes()
    rows, run_files, index = episodes(runs_dir, by_id)
    rows.sort(key=lambda r: (r["model"] or "", r["trained"] or "", r["tier"], r["bundle"], r["task_id"]))
    for split in (*SPLITS, "showcase"):
        if any(r["split"] == split for r in rows):
            files[f"episodes/v1/{split}.parquet"] = parquet([r for r in rows if r["split"] == split], EPISODES)
    files |= run_files
    if index:
        files["runs/index.json"] = json.dumps(index, indent=1).encode()
    board = None
    for name in ("eval-v1.json", "board.md"):
        if (results_dir / name).is_file():
            files[f"results/{name}"] = (results_dir / name).read_bytes()
    if "results/eval-v1.json" in files:
        board = board_markdown(json.loads(files["results/eval-v1.json"]))
    bundles = {}
    for path in bundle_dirs:
        bundles[path.name] = bundle_split(path.name)
        files |= dataset.build(runs.locate(str(path)), name=path.name, split=bundles[path.name],
                               which="latest").files
    if extras is None:
        return files | {"README.md": card_text(files, bundles, plugin, board).encode()}
    more, blocks = previews(extras)
    files |= more
    files["README.md"] = card_text(files, bundles, plugin, board, blocks, extras.preview_ref).encode()
    n = check_text(files, [*more, "README.md"])
    print(f"{n:,} distinct strings of the previews, the training summary and the card checked: no notice text "
          f"verbatim, no bucket, host, key or ticket id")
    return files


# ================================================================ v2 and v3 previews
@dataclass(frozen=True)
class Preview:
    """What differs between the v2 and v3 previews: packs, tiers, core module, prompts and the episode schema."""
    version: str
    packs: dict[str, str]
    tiers: tuple[str, ...]
    core: ModuleType
    prompts: ModuleType
    sha: str


V2 = Preview("v2", {"train": "gridsim-live-train", "eval_2024": "gridsim-live-eval",
                    "test_2025": "gridsim-live-test-2025", "rtcb": "gridsim-live-rtcb",
                    "showcase": "gridsim-live-showcase"},
             ("foresight", "blind", "short", "freeze6h"), live, live_prompt, "notices_sha")
V3 = Preview("v3", {"train": "ercot-hybrid-v3-train", "eval": "ercot-hybrid-v3-eval", "rtcb": "ercot-hybrid-v3-rtcb",
                    "showcase": "ercot-hybrid-v3-showcase"},
             ("energy", "reserves"), hybrid, hybrid_prompt, "events_sha")
PREVIEW_STATS = ("live-stats.md", "hybrid-stats.md")
PREVIEW_RESULTS = {"v2": ("eval-v2.json", "board-v2.md", "pilot-v2.json"), "v3": ("eval-v3.json", "board-v3.md",
                                                                                   "pilot-v3.json")}
LABELS = {**NAMES, "reference/rolling-anchor": "rolling anchor", "reference/naive": "naive",
          "reference/as-hog": "AS-hog", "reference/solar-sponge": "solar sponge",
          "reference/v2-energy-only": "v2 energy-only"}
TIME = r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\.?"
CONSERVE = re.compile(rf"ERCOT asked the public to conserve electricity(?: from {TIME} to {TIME})?")
NOTE = re.compile(r"(?P<head>.*?)(?: \((?P<why>.*)\))?\.?", re.S)
REASONS = ((r"tropical|hurricane|cyclone", "a tropical storm"), (r"fire", "wildfire risk"),
           (r"freez|winter|\bic[ey]\b|snow", "freezing precipitation"), (r"cold", "extreme cold"),
           (r"\bhot\b|heat|high temperatures|°F", "extreme heat"),
           (r"severe weather|tornado|high wind|thunderstorm", "severe storms"),
           (r"physical responsive capability|\bPRC\b", "low physical responsive capability"),
           (r"\bSCED\b", "a failure of the real-time dispatch software"),
           (r"geomagnetic|\bGMD\b", "a geomagnetic disturbance"),
           (r"interface|transmission|line operations|constraint|outage", "transmission conditions"),
           (r"reserve|capacity|shortage|emergency condition|deficien|wind|solar|demand",
            "a projected shortage of reserves"))
WORD = re.compile(r"[a-z0-9]+(?:['’.:-][a-z0-9]+)*")
SHINGLE = 7
ORG = re.compile(r"(?:the )?Electric Reliability Council of Texas,? Inc\.?(?: \(ERCOT\))?", re.I)
LEAK = re.compile(r"s3://|amazonaws|airops-runs|scale\.com|\bFD-\d|\bsk-[A-Za-z0-9_-]{12,}|litellm\.[a-z]", re.I)
TRAIN_ARMS = (("arm1", ".", "arm 1: SFT-200 warm start, then GRPO 280 steps", True),
              ("arm2", "arm2", "arm 2: SoC-aware SFT-1500 warm start, then GRPO 75 steps", False),
              ("arm2b", "arm2b", "arm 2b: arm 2, then GRPO from its step 75", False))
TRAIN_FILES = ("summary.json", "eval_checkpoints.json", "curves.png")

LIVE_TASKS = pa.schema([
    ("task_id", STR), ("tier", STR), ("split", STR), ("pack", STR), ("date", STR), ("settlement_point", STR),
    ("point_kind", STR), ("region", STR), ("archetype", STR), *((k, I64 if k in UNITS else F64) for k in BATTERY),
    ("prices", pa.list_(F64)), ("rt", pa.list_(F64)), ("dam_prev_day", pa.list_(F64)),
    ("dam_prev_7d", pa.list_(pa.list_(F64))), ("watches", I64), ("notice_count", I64), ("notices", STR),
    ("day_kind", STR), ("system_prompt", STR), ("situation", STR), ("prompt", PROMPT), ("tools", STR),
    ("p_idle", F64), ("p_naive", F64), ("p_roll", F64), ("p_hind", F64), ("p_lp", F64), ("naive_reward", F64),
    ("naive_capture", F64), ("anchor_capture", F64), ("anchor_commits", I64), ("season", STR), ("era", STR),
    ("neg_intervals", I64), ("rt_spike", BOOL), ("short_ok", BOOL), ("notice_day", BOOL), ("showcase", STR),
    ("tags", STR), ("eligibility", STR), ("task", STR),
])
HYBRID_TASKS = pa.schema([
    ("task_id", STR), ("tier", STR), ("split", STR), ("pack", STR), ("date", STR), ("era", STR),
    ("settlement_point", STR), ("point_kind", STR), ("region", STR), ("site_id", STR), ("site_source", STR),
    ("coupling", STR), ("pv_mwac", F64), ("pv_mwdc", F64), ("ilr", F64), ("poi_mw", F64), ("poi_import_mw", F64),
    ("p_mw", F64), ("e_mwh", F64), ("eta", F64), ("c_deg", F64), ("cycle_cap_mwh", F64), ("s0_mwh", F64),
    ("s_end_min_mwh", F64), ("qualified", pa.list_(STR)), ("prices", pa.list_(F64)), ("rt", pa.list_(F64)),
    ("pv_cf", pa.list_(F64)), ("pv_mw", pa.list_(F64)), ("mcpc_da", STR), ("reg_up", pa.list_(F64)),
    ("reg_dn", pa.list_(F64)), ("watches", I64), ("notice_count", I64), ("notices", STR), ("deployments", STR),
    ("system_prompt", STR), ("situation", STR), ("prompt", PROMPT), ("oneshot_prompt", PROMPT), ("tools", STR),
    ("p_idle", F64), ("p_anchor", F64), ("p_hind", F64), ("p_lp", F64), ("anchor_capture", F64),
    ("oneshot_p_milp", F64), ("anchor_commits", I64), ("anchor_as_usd", F64), ("sponge_reward", F64),
    ("as_hog_reward", F64), ("v2_energy_reward", F64), ("energy_only_reward", F64), ("season", STR),
    ("as_value_usd", F64), ("as_stratum", STR), ("notice_day", BOOL), ("deploy_day", BOOL), ("neg_hours", I64),
    ("clip_mwh", F64), ("showcase", STR), ("tags", STR), ("flags", STR), ("task", STR),
])
LIVE_REFERENCES = pa.schema([
    ("task_id", STR), ("split", STR), ("date", STR), ("settlement_point", STR), ("archetype", STR),
    ("notice_day", BOOL), ("p_idle", F64), ("p_naive", F64), ("naive_da", pa.list_(I64)), ("p_hind", F64),
    ("p_hind_da", F64), ("p_hind_rt", F64), ("hind_da", pa.list_(I64)), ("hind_schedule", pa.list_(I64)),
    ("p_lp", F64),
    *((f"{t}_{k}", typ) for t in V2.tiers for k, typ in (
        ("p_roll", F64), ("roll_da", pa.list_(I64)), ("roll_executed", pa.list_(I64)), ("roll_commits", I64),
        ("naive_reward", F64), ("anchor_capture", F64))),
    ("blind_via", STR), ("divergence_usd_per_mw", F64), ("roll_minus_naive_share", F64),
    ("roll_minus_naive_usd_per_mw", F64), ("hind_headroom_usd_per_mw", F64),
])
HYBRID_REFERENCES = pa.schema([
    ("task_id", STR), ("split", STR), ("date", STR), ("era", STR), ("settlement_point", STR), ("site_id", STR),
    ("as_stratum", STR), ("p_idle", F64),
    *((f"{t}_{k}", typ) for t in V3.tiers for k, typ in (
        ("p_anchor", F64), ("anchor_book", STR), ("anchor_commits", I64), ("anchor_as_usd", F64), ("p_hind", F64),
        ("p_lp", F64), ("anchor_capture", F64), ("oneshot_p_milp", F64), ("oneshot_plan", STR),
        ("sponge_profit", F64), ("sponge_reward", F64), ("v2_energy_profit", F64), ("v2_energy_reward", F64))),
    ("reserves_as_hog_profit", F64), ("reserves_as_hog_reward", F64), ("reserves_p_energy_only", F64),
    ("reserves_energy_only_reward", F64),
])
EPISODE_HEAD = [
    ("episode_id", STR), ("task_id", STR), ("split", STR), ("tier", STR), ("bundle", STR), ("path", STR),
    ("model", STR), ("model_label", STR), ("trained", STR), ("checkpoint_step", I64), ("seed", I64),
    ("reward", F64), ("capture_vs_hindsight", F64), ("beats_anchor", BOOL), ("profit_usd", F64), ("p_idle", F64),
    ("p_hind", F64),
]
EPISODE_TAIL = [
    ("commits", I64), ("tool_calls", I64), ("watches", I64), ("notices", I64), ("steps", STR),
    ("messages", pa.list_(tables.MESSAGE)), ("transcript", STR), ("assistant_text", STR), ("input_tokens", I64),
    ("output_tokens", I64), ("usd", F64), ("wall_seconds", F64), ("audit_ok", BOOL), ("verified", BOOL), ("file", STR),
]
LIVE_EPISODES = pa.schema([
    *EPISODE_HEAD, ("p_naive", F64), ("p_roll", F64), ("naive_reward", F64), ("stretch_reward", F64),
    ("feasible", BOOL), ("da_position", pa.list_(I64)), ("schedule", pa.list_(I64)), ("executed", pa.list_(I64)),
    ("soc_path", pa.list_(I64)), ("pnl", STR), *EPISODE_TAIL,
])
HYBRID_EPISODES = pa.schema([
    *EPISODE_HEAD, ("p_anchor", F64), ("raw_ratio", F64), ("energy_only_reward", F64), ("as_share", F64),
    ("ftp_mwh_charged", F64), ("ftp_mwh_excused", F64), ("governor_hours", I64), ("refusals", I64), ("book", STR),
    ("da", STR), ("soc_path", pa.list_(F64)), ("cash", STR), ("deployments", I64), *EPISODE_TAIL,
])


def _clock(h: str, m: str | None, ap: str) -> str:
    return f"{int(h) % 12 + (12 if ap.lower() == 'p' else 0):02d}:{m or '00'}"


def _conserve(m: re.Match) -> str:
    if not m[1]:
        return "ERCOT appealed for conservation"
    return f"ERCOT appealed for conservation from {_clock(m[1], m[2], m[3])} to {_clock(m[4], m[5], m[6])}"


def paraphrase(text: str) -> str:
    """An ERCOT notice summary in our own words: lane N's template head, its clock times as HH:MM, and the clause the
    summary quoted from ERCOT's text replaced by a reason category, so no notice text reaches the Hub verbatim."""
    m = NOTE.fullmatch(text)
    why = m["why"]
    reason = next((r for p, r in REASONS if re.search(p, why, re.I)), None) if why else None
    head = CONSERVE.sub(_conserve, m["head"])
    return f"{head} ({reason})." if reason else f"{head}."


class Scrubber:
    """Every ERCOT notice summary of the published packs, and the clause each quoted, mapped to its paraphrase; applied
    to every string of a task or an episode, the agent's own words included."""

    def __init__(self, tasks: list[dict]):
        self.table: dict[str, str] = {}
        for n in (n for t in tasks for n in t.get("notices") or [] if n.get("source") == "ERCOT"):
            new = paraphrase(n["text"])
            if new != n["text"]:
                self.table[n["text"]] = new
            if (why := NOTE.fullmatch(n["text"])["why"]) and len(why.split()) >= 4:
                reason = new[new.find("(") + 1:-2] if new.endswith(").") else "an ERCOT notice"
                self.table.setdefault(why, reason)
                self.table.setdefault(why.removesuffix("..."), reason)
        keys = sorted(self.table, key=len, reverse=True)
        self.rx = re.compile("|".join(map(re.escape, keys))) if keys else None

    def __call__(self, x):
        if isinstance(x, str):
            return self.rx.sub(lambda m: self.table[m[0]], x) if self.rx else x
        if isinstance(x, dict):
            return {k: self(v) for k, v in x.items()}
        if isinstance(x, list):
            return [self(v) for v in x]
        return x


def published(pv: Preview, task: dict, scrub: Scrubber) -> dict:
    """The task row as published: notices paraphrased and their sha recomputed over the published text, so a Session
    keeps the stored references (they depend on the notices' times, levels and derates, never on their text)."""
    t = scrub(task)
    if t != task:
        sha = live.notices_sha(t["notices"]) if pv is V2 else hybrid.events_sha(t)
        t[pv.sha] = t["refs"][pv.sha] = sha
    return t


def capture(p: float | None, p_idle: float, p_hind: float) -> float | None:
    return None if p is None or p_hind - p_idle <= 1e-9 else round((p - p_idle) / (p_hind - p_idle), 6)


def live_task_row(task: dict, tier: str, raw: str, pack: str) -> dict:
    s = live.Session(task, tier)
    prompt = live_prompt.messages(s)
    refs, roll, b, tags = task["refs"], task["refs"]["roll"][tier], task["battery"], task["tags"]
    blind = task.get("blind") or {}
    return {
        **{k: task[k] for k in ("task_id", "split", "date", "settlement_point", "point_kind", "region", "prices",
                                "rt")},
        "tier": tier, "pack": pack, "archetype": b["archetype"], **{k: b[k] for k in BATTERY},
        "dam_prev_day": blind.get("dam_prev_day"), "dam_prev_7d": blind.get("dam_prev_7d"), "watches": len(s.watches),
        "notice_count": len(task["notices"]), "notices": json.dumps(task["notices"], ensure_ascii=False),
        "day_kind": tags.get("day_kind"), "system_prompt": prompt[0]["content"], "situation": prompt[1]["content"],
        "prompt": prompt, "tools": json.dumps(live_prompt.tool_schemas(tier)),
        **{k: refs[k] for k in ("p_idle", "p_naive", "p_hind", "p_lp")}, "p_roll": roll["p_roll"],
        "naive_reward": roll["naive_reward"], "naive_capture": capture(refs["p_naive"], refs["p_idle"], refs["p_hind"]),
        "anchor_capture": capture(roll["p_roll"], refs["p_idle"], refs["p_hind"]), "anchor_commits": roll["commits"],
        **{k: tags.get(k) for k in ("season", "era", "neg_intervals", "rt_spike", "short_ok", "notice_day",
                                    "showcase")},
        "tags": json.dumps(tags), "eligibility": json.dumps(task.get("eligibility")), "task": raw,
    }


def hybrid_task_row(task: dict, tier: str, raw: str, pack: str) -> dict:
    s = hybrid.Session(task, tier)
    prompt = hybrid_prompt.messages(s)
    site, bess, tags = task["site"], task["site"]["bess"], task["tags"]
    p_idle, t = task["refs"]["p_idle"], task["refs"][tier]
    base = t["baselines"]
    return {
        **{k: task[k] for k in ("task_id", "split", "date", "era", "settlement_point", "point_kind", "region", "prices",
                                "rt", "pv_cf", "pv_mw")},
        "tier": tier, "pack": pack, "site_id": site["site_id"], "site_source": site["source"],
        **{k: site[k] for k in ("coupling", "pv_mwac", "pv_mwdc", "ilr", "poi_mw", "poi_import_mw", "qualified")},
        **{k: bess[k] for k in ("p_mw", "e_mwh", "eta", "c_deg", "cycle_cap_mwh", "s0_mwh", "s_end_min_mwh")},
        "mcpc_da": json.dumps(task["mcpc_da"]), "reg_up": task["reg"]["up"], "reg_dn": task["reg"]["dn"],
        "watches": len(s.watches), "notice_count": len(task["notices"]),
        "notices": json.dumps(task["notices"], ensure_ascii=False), "deployments": json.dumps(task["deployments"]),
        "system_prompt": prompt[0]["content"], "situation": prompt[1]["content"], "prompt": prompt,
        "oneshot_prompt": hybrid_prompt.oneshot_messages(task, tier),
        "tools": json.dumps(hybrid_prompt.tool_schemas(tier)),
        "p_idle": p_idle, **{k: t[k] for k in ("p_anchor", "p_hind", "p_lp")},
        "anchor_capture": capture(t["p_anchor"], p_idle, t["p_hind"]), "oneshot_p_milp": t["oneshot"]["p_milp"],
        "anchor_commits": t["anchor"]["commits"], "anchor_as_usd": t["anchor"]["as_usd"],
        **{f"{b}_reward": (base.get(b) or {}).get("reward") for b in ("sponge", "as_hog", "v2_energy")},
        "energy_only_reward": None if t.get("p_energy_only") is None
        else reward_value(t["p_energy_only"], p_idle, t["p_anchor"]),
        **{k: tags.get(k) for k in ("season", "as_value_usd", "as_stratum", "notice_day", "deploy_day", "neg_hours",
                                    "clip_mwh", "showcase")},
        "tags": json.dumps(tags), "flags": json.dumps(task.get("flags")), "task": raw,
    }


def live_reference_row(task: dict) -> dict:
    r, e = task["refs"], task.get("eligibility") or {}
    row = {**{k: task[k] for k in ("task_id", "split", "date", "settlement_point")},
           "archetype": task["battery"]["archetype"], "notice_day": task["tags"].get("notice_day"),
           **{k: r[k] for k in ("p_idle", "p_naive", "p_hind", "p_hind_da", "p_hind_rt", "p_lp")},
           "naive_da": r["naive"]["da"], "hind_da": r["hind"]["da"], "hind_schedule": r["hind"]["schedule"],
           "blind_via": (r["roll"].get("blind") or {}).get("via"),
           **{k: e.get(k) for k in ("divergence_usd_per_mw", "roll_minus_naive_share", "roll_minus_naive_usd_per_mw",
                                    "hind_headroom_usd_per_mw")}}
    for tier in V2.tiers:
        x = r["roll"].get(tier) or {}
        row |= {f"{tier}_p_roll": x.get("p_roll"), f"{tier}_roll_da": x.get("da"),
                f"{tier}_roll_executed": x.get("executed"), f"{tier}_roll_commits": x.get("commits"),
                f"{tier}_naive_reward": x.get("naive_reward"),
                f"{tier}_anchor_capture": capture(x.get("p_roll"), r["p_idle"], r["p_hind"])}
    return row


def hybrid_reference_row(task: dict) -> dict:
    r = task["refs"]
    row = {**{k: task[k] for k in ("task_id", "split", "date", "era", "settlement_point")},
           "site_id": task["site"]["site_id"], "as_stratum": task["tags"].get("as_stratum"), "p_idle": r["p_idle"]}
    for tier in V3.tiers:
        t, base = r[tier], r[tier]["baselines"]
        row |= {f"{tier}_p_anchor": t["p_anchor"], f"{tier}_anchor_book": json.dumps(t["anchor"]["book"]),
                f"{tier}_anchor_commits": t["anchor"]["commits"], f"{tier}_anchor_as_usd": t["anchor"]["as_usd"],
                f"{tier}_p_hind": t["p_hind"], f"{tier}_p_lp": t["p_lp"],
                f"{tier}_anchor_capture": capture(t["p_anchor"], r["p_idle"], t["p_hind"]),
                f"{tier}_oneshot_p_milp": t["oneshot"]["p_milp"],
                f"{tier}_oneshot_plan": json.dumps(t["oneshot"]["plan"]),
                **{f"{tier}_{b}_{k}": base[b][k] for b in ("sponge", "v2_energy") for k in ("profit", "reward")}}
    t = r["reserves"]
    return row | {"reserves_as_hog_profit": t["baselines"]["as_hog"]["profit"],
                  "reserves_as_hog_reward": t["baselines"]["as_hog"]["reward"],
                  "reserves_p_energy_only": t.get("p_energy_only"),
                  "reserves_energy_only_reward": None if t.get("p_energy_only") is None
                  else reward_value(t["p_energy_only"], r["p_idle"], t["p_anchor"])}


def replay(pv: Preview, e: dict, task: dict) -> dict:
    """The episode's every recorded call played again through a fresh gridsim_core Session on the task, byte for byte,
    then its audit and grade; Mismatch at the first output, audit row or score that differs."""
    s = pv.core.Session(task, e["tier"])
    for i, step in enumerate(e["steps"]):
        args = dict(step["args"]) | ({"_via": "trigger"} if step["tool"] == pv.core.NOTICE_TOOL else {})
        if s.call(step["tool"], args) != json.dumps(step["output"], ensure_ascii=False, separators=(",", ":")):
            raise Mismatch(f"call {i} ({step['tool']}) does not replay byte for byte")
    if not s.done:
        s.end_day()
    if not (audit := s.audit())["ok"]:
        raise Mismatch(f"the audit fails: {audit['problems'][:2]}")
    g = s.grade()
    for k in ("reward", "capture_vs_hindsight", "beats_anchor"):
        if (g[k] is None) != (e.get(k) is None) or (g[k] is not None and abs(float(g[k]) - float(e[k])) > TOLERANCE):
            raise Mismatch(f"{k} {e.get(k)}; gridsim_core {g[k]}")
    if abs(g["profit_usd"] - e["profit_usd"]) > TOLERANCE * max(1.0, abs(g["profit_usd"])):
        raise Mismatch(f"profit {e['profit_usd']}; gridsim_core {g['profit_usd']}")
    return g


def rebuilt_live(pv: Preview, e: dict, task: dict) -> list[dict]:
    """The chat as path B' sends it: the system prompt and the watch-0 opening, then each agent call with its output
    (the bulletins arrive inside the outputs' messages); the agent's text goes on its calls only when there is one
    text per call."""
    out = pv.prompts.messages(pv.core.Session(task, e["tier"]))
    steps = [s for s in e["steps"] if s["tool"] != pv.core.NOTICE_TOOL]
    texts = [m["content"] for m in e.get("messages") or [] if m.get("role") == "assistant" and m.get("content")]
    paired = len(texts) == len(steps)
    for i, step in enumerate(steps):
        call = f"call_{i}"
        out.append({"role": "assistant", "content": texts[i] if paired else None, "tool_calls": [
            {"id": call, "type": "function", "function": {"name": step["tool"], "arguments": step["args"]}}]})
        out.append({"role": "tool", "tool_call_id": call, "name": step["tool"],
                    "content": json.dumps(step["output"], ensure_ascii=False, separators=(",", ":"))})
    return out


def preview_episode_row(pv: Preview, e: dict, task: dict, g: dict, file: str) -> dict:
    usage = e.get("usage") or {}
    texts = [m["content"] for m in e.get("messages") or [] if m.get("role") == "assistant" and m.get("content")]
    row = {**{k: e.get(k) for k in ("episode_id", "task_id", "tier", "bundle", "path", "model", "trained",
                                    "checkpoint_step", "seed", "reward", "profit_usd", "soc_path")},
           "split": task["split"], "model_label": LABELS.get(e["model"], e["model"]),
           **{k: g[k] for k in ("capture_vs_hindsight", "beats_anchor", "p_idle", "p_hind", "commits")},
           "tool_calls": sum(s["tool"] != pv.core.NOTICE_TOOL for s in e["steps"]), "watches": len(e["watches"]),
           "notices": len(e["notices"]), "steps": json.dumps(e["steps"], ensure_ascii=False),
           "messages": to_messages(rebuilt_live(pv, e, task)), "transcript": "rebuilt",
           "assistant_text": "\n\n".join(texts) or None, "input_tokens": usage.get("input_tokens"),
           "output_tokens": usage.get("output_tokens"), "usd": usage.get("usd"), "wall_seconds": e.get("wall_seconds"),
           "audit_ok": True, "verified": True, "file": file}
    if pv is V2:
        return row | {k: g[k] for k in ("p_naive", "p_roll", "naive_reward", "stretch_reward", "feasible")} | {
            k: e.get(k) for k in ("da_position", "schedule", "executed")} | {"pnl": json.dumps(e.get("pnl"))}
    return row | {k: g[k] for k in ("p_anchor", "raw_ratio", "energy_only_reward", "as_share", "ftp_mwh_charged",
                                    "ftp_mwh_excused", "governor_hours", "refusals")} | {
        "book": json.dumps(e.get("book")), "da": json.dumps(e.get("da")), "cash": json.dumps(e.get("cash")),
        "deployments": sum(bool(n.get("deploy")) for n in e["notices"])}


def preview_episodes(pv: Preview, roots: list[Path], tasks: dict[str, tuple[dict, dict]],
                     scrub: Scrubber) -> tuple[list[dict], dict[str, bytes], Counter]:
    """Every gridsim.episode/<version> JSON under the roots (sweeps' raw folders skipped), replayed byte for byte on
    the plugin's pack row and again, paraphrased, on the published row: its table row and its file under runs/
    (runs/<root>/<file> for a root of episodes, runs/<folder>/<file> for a root of folders). Raises at the first
    episode that does not replay."""
    rows, files, counts = [], {}, Counter()
    schema = pv.core.EPISODE_SCHEMA
    for root in roots:
        for path in sorted(root.rglob("*.json")):
            rel = path.relative_to(root)
            if "raw" in rel.parts[:-1]:
                continue
            e = json.loads(path.read_text())
            if not isinstance(e, dict) or e.get("schema") != schema:
                continue
            file = f"runs/{root.name}/{rel.as_posix()}" if len(rel.parts) == 1 else f"runs/{rel.as_posix()}"
            if e["task_id"] not in tasks:
                raise Mismatch(f"{file}: {e['task_id']} is not a task of the published {pv.version} packs")
            if file in files:
                raise Mismatch(f"{file}: two episodes would publish to the same path")
            original, public = tasks[e["task_id"]]
            try:
                replay(pv, e, original)
                pub = scrub(e)
                g = replay(pv, pub, public)
            except Mismatch as err:
                raise Mismatch(f"{file}: {err}") from None
            rows.append(preview_episode_row(pv, pub, public, g, file))
            files[file] = path.read_bytes() if pub == e else json.dumps(pub, ensure_ascii=False).encode()
            counts[file.split("/")[1]] += 1
    rows.sort(key=lambda r: (r["model"] or "", r["tier"], r["bundle"] or "", r["task_id"]))
    return rows, files, counts


def preview(pv: Preview, roots: list[Path]) -> tuple[dict[str, bytes], Counter]:
    """tasks/<v>, references/<v>, episodes/<v>, the packs under raw/packs/ and the episodes under runs/, notice text
    paraphrased everywhere."""
    files: dict[str, bytes] = {}
    packs = {split: pack_lines(pack) for split, pack in pv.packs.items()}
    originals = {split: [json.loads(line) for line in lines] for split, lines in packs.items()}
    scrub = Scrubber([t for ts in originals.values() for t in ts])
    task_row = live_task_row if pv is V2 else hybrid_task_row
    reference_row = live_reference_row if pv is V2 else hybrid_reference_row
    by_id: dict[str, tuple[dict, dict]] = {}
    for split, pack in pv.packs.items():
        public = [published(pv, t, scrub) for t in originals[split]]
        lines = [line if p == t else json.dumps(p, ensure_ascii=False, separators=(",", ":"))
                 for line, t, p in zip(packs[split], originals[split], public, strict=True)]
        by_id |= {t["task_id"]: (t, p) for t, p in zip(originals[split], public, strict=True)}
        rows = [task_row(p, tier, line, pack) for p, line in zip(public, lines, strict=True) for tier in pv.tiers
                if (p["refs"]["roll"].get(tier) if pv is V2 else p["refs"].get(tier))]
        files[f"tasks/{pv.version}/{split}.parquet"] = parquet(rows, LIVE_TASKS if pv is V2 else HYBRID_TASKS)
        files[f"references/{pv.version}/{split}.parquet"] = parquet(
            [reference_row(p) for p in public], LIVE_REFERENCES if pv is V2 else HYBRID_REFERENCES)
        files[f"raw/packs/{pack}.jsonl"] = ("\n".join(lines) + "\n").encode()
        files[f"raw/packs/{pack}.manifest.json"] = unticket((data_root() / pack / "manifest.json").read_bytes())
    rows, run_files, counts = preview_episodes(pv, roots, by_id, scrub)
    for split in pv.packs:
        if any(r["split"] == split for r in rows):
            files[f"episodes/{pv.version}/{split}.parquet"] = parquet(
                [r for r in rows if r["split"] == split], LIVE_EPISODES if pv is V2 else HYBRID_EPISODES)
    return files | run_files, counts


def unticket(content: bytes) -> bytes:
    """A stats file, manifest or board as published: its tracker ids taken out of the prose."""
    text = re.sub(r",\s*FD-\d+|\s*\(FD-\d+\)", "", content.decode())
    text = re.sub(r"\b(?:the )?FD-\d+(?:'s)?", "the design plan's", text)
    return text.encode()


@dataclass(frozen=True)
class Extras:
    v2_runs: list[Path]
    v3_runs: list[Path]
    v2_results: Path
    v3_results: Path
    train: Path
    preview_ref: str


def previews(x: Extras) -> tuple[dict[str, bytes], dict[str, str]]:
    """The v2 and v3 previews, their pilots' eval cards and boards, the pack statistics and the training summary; and
    the card's blocks made from them."""
    files: dict[str, bytes] = {}
    blocks: dict[str, str] = {}
    for pv, roots, results in ((V2, x.v2_runs, x.v2_results), (V3, x.v3_runs, x.v3_results)):
        out, counts = preview(pv, roots)
        files |= out
        print(f"{pv.version}: {sum(counts.values())} episodes replayed byte for byte and graded again, 0 mismatched ("
              + ", ".join(f"{k} {n}" for k, n in sorted(counts.items())) + ")")
        for name in PREVIEW_RESULTS[pv.version]:
            if (results / name).is_file():
                files[f"results/{name}"] = unticket((results / name).read_bytes())
    for name in PREVIEW_STATS:
        files[f"raw/packs/{name}"] = unticket((data_root() / name).read_bytes())
    if "results/eval-v3.json" in files:
        blocks["board:v3"] = board_v3_markdown(json.loads(files["results/eval-v3.json"]))
    train_files, arms = training(x.train)
    files |= train_files
    if arms:
        blocks["training"] = training_markdown(arms)
    return files, blocks

def shingles(text: str) -> set[tuple[str, ...]]:
    w = WORD.findall(ORG.sub("ERCOT", text).lower())
    return {tuple(w[i:i + SHINGLE]) for i in range(len(w) - SHINGLE + 1)}


def strings(x) -> Iterator[str]:
    if isinstance(x, str):
        if x[:1] in "{[":
            try:
                yield from strings(json.loads(x))
                return
            except ValueError:
                pass
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


def readable(path: str, content: bytes):
    if path.endswith(".parquet"):
        return pq.read_table(io.BytesIO(content)).to_pylist()
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in content.decode().splitlines() if line.strip()]
    if path.endswith(".json"):
        return json.loads(content)
    return content.decode() if path.endswith(".md") else None


def check_text(files: dict[str, bytes], paths: list[str]) -> int:
    """Fails the build when a published v2 or v3 file holds a run of SHINGLE words from an ERCOT notice of the archive
    (its text or title), or a bucket, internal host, key or ticket id; returns how many strings were checked."""
    with gzip.open(data_root() / "notices/notices.jsonl.gz", "rt") as f:
        archive = [json.loads(line) for line in f if line.strip()]
    known = set().union(*(shingles(n.get(k) or "") for n in archive for k in ("text", "title")))
    seen: set[str] = set()
    for path in paths:
        for s in strings(readable(path, files[path])):
            if s in seen:
                continue
            seen.add(s)
            if leak := LEAK.search(s):
                raise SystemExit(f"{path} holds {leak[0]!r}; nothing was written")
            if hit := next((g for g in shingles(s) if g in known), None):
                raise SystemExit(f"{path} quotes ERCOT notice text verbatim ({' '.join(hit)!r}); nothing was written")
    return len(seen)


def training(train_dir: Path) -> tuple[dict[str, bytes], list[dict]]:
    """training/<arm>/ (each arm's summary, checkpoint evals and curves, as results/train has them) and
    training/arms.json: per arm, its final policy on the 200 eval_2025 tasks against the two rules it was held to."""
    files, arms = {}, []
    for name, sub, recipe, prereg in TRAIN_ARMS:
        d = train_dir / sub
        if not (d / "summary.json").is_file():
            continue
        for f in TRAIN_FILES:
            if (d / f).is_file():
                files[f"training/{name}/{f}"] = (d / f).read_bytes()
        s = json.loads((d / "summary.json").read_text())
        policies = [r for r in s["rows"] if r.get("decoding") == "sampled"]
        rules = {r["model"].removeprefix("rule:"): r for r in s["rows"] if r["model"].startswith("rule:")}
        if not rules:
            ev = json.loads((d / "eval_trained.json").read_text())["baselines"]
            rules = {k: {"model": f"rule:{k}", **v} for k, v in ev.items()}
        final, base = policies[-1], policies[0]
        bars = [{"bar": f"beats the {rule} rule: 95% CIs apart, valid >= 98%", "rule": rule,
                 "rule_reward": rules[rule]["reward_mean"], "rule_ci95": rules[rule]["ci95"],
                 "met": final["ci95"][0] > rules[rule]["ci95"][1] and final["valid_rate"] >= 0.98}
                for rule in ("greedy", "threshold")]
        arms.append({"arm": name, "label": s.get("label") or recipe, "recipe": recipe, "pre_registered": prereg,
                     "model": "Qwen/Qwen3-1.7B", "tasks": s["n_tasks"], "split": "eval_2025", "tier": "foresight",
                     "harness": "oneshot (path B)", "base": {k: base[k] for k in ("reward_mean", "ci95", "valid_rate")},
                     "final": {k: final.get(k) for k in ("model", "checkpoint_step", "reward_mean", "ci95",
                                                         "valid_rate", "feasible_rate")},
                     "rules": {k: {"reward_mean": v["reward_mean"], "ci95": v.get("ci95")} for k, v in rules.items()},
                     "bars": bars, "paired": s.get("paired")})
    if arms:
        files["training/arms.json"] = (json.dumps(arms, indent=1) + "\n").encode()
    return files, arms


def training_markdown(arms: list[dict]) -> str:
    r = {k: v["reward_mean"] for k, v in arms[0]["rules"].items()}
    lines = ["| Arm | Pre-registered | Recipe | Mean R, sampled (95% CI) | Valid | Beats threshold | Beats greedy |",
             "|---|---|---|---|---:|---|---|"]
    for a in arms:
        f, met = a["final"], {b["rule"]: "met" if b["met"] else "not met" for b in a["bars"]}
        lines.append(f"| {a['arm'].replace('arm', 'arm ')} | {'yes' if a['pre_registered'] else 'no (exploratory)'} | "
                     f"{a['recipe'].split(': ', 1)[1]} | **{f['reward_mean']:.3f}** ({f['ci95'][0]:.3f} to "
                     f"{f['ci95'][1]:.3f}) | {100 * f['valid_rate']:.1f}% | {met['threshold']} | {met['greedy']} |")
    return "\n".join(lines + ["", f"On the same 200 tasks: base Qwen3-1.7B {arms[0]['base']['reward_mean']:.3f} (no "
                              f"valid schedule), the threshold rule {r['threshold']:.3f}, the greedy rule "
                              f"{r['greedy']:.3f}, idle 0.200, the DP optimum 1.000."])


def board_v3_markdown(c: dict) -> str:
    """The v3 pilot's board from its eval card: each model and tier's mean reward with its CI, the weight-0 rows and
    the cost."""
    def f(x, fmt=".4f"):
        return "–" if x is None else format(x, fmt)

    lines = ["| Model | Tier | Days | Mean R (95% CI) | Hindsight capture | Beats anchor | Energy-only R | AS share "
             "| $ per episode |", "|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci = f" ({f(m['ci95'][0])} to {f(m['ci95'][1])})" if m.get("ci95") else ""
        lines.append(f"| {LABELS.get(m['model'], m['model'])} | {m['tier']} | {m['tasks']} | **{f(m['mean'])}**{ci} | "
                     f"{f(m['hindsight_capture'], '.3f')} | {f(100 * m['beats_anchor'], '.1f')}% | "
                     f"{f(m.get('energy_only_reward'))} | {f(m.get('as_share'), '.3f')} | "
                     f"${f(m.get('usd_per_episode'))} |")
    return "\n".join(lines)


def write(files: dict[str, bytes], out: Path) -> None:
    for folder in MANAGED:
        shutil.rmtree(out / folder, ignore_errors=True)
    for path, content in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(content)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="The folder to write, e.g. build/hub/dataset.")
    ap.add_argument("--runs", type=Path, default=ROOT / "results/runs",
                    help="A folder of gridsim.episode/v1 JSON, searched recursively; none there, no episodes.")
    ap.add_argument("--results", type=Path, default=ROOT / "results",
                    help="The folder with the sweep report's eval-v1.json and board.md, when there are.")
    ap.add_argument("--bundle", type=Path, action="append", default=[],
                    help="A bundle folder to publish with agentenv-hf, named after its pack, e.g. "
                         "build/bundles/ercot-dam-v1-eval. Repeat for several.")
    ap.add_argument("--plugin-ref", default=f"v{VERSION}", help="The plugin tag the card's bundles pin.")
    ap.add_argument("--v1-only", action="store_true", help="v1's files and card only: no previews, no training.")
    ap.add_argument("--v2-runs", type=Path, action="append",
                    help="A folder of gridsim.episode/v2 JSON, or of such folders, published under runs/<folder>/. "
                         "Repeat for several. Default: results/runs/v2-pilot-sol and v2-pilot-sol-hero.")
    ap.add_argument("--v3-runs", type=Path, action="append",
                    help="The same for gridsim.episode/v3 JSON. Default: results/runs/hybrid-reference and the four "
                         "v3-pilot-sol* folders.")
    ap.add_argument("--v2-results", type=Path, default=ROOT / "results",
                    help="The folder with eval-v2.json, board-v2.md and pilot-v2.json, when there are.")
    ap.add_argument("--v3-results", type=Path, default=ROOT / "results",
                    help="The folder with eval-v3.json, board-v3.md and pilot-v3.json, when there are.")
    ap.add_argument("--train", type=Path, default=ROOT / "results/train",
                    help="results/train: arm 1 at its top, arm 2 in arm2/, arm 2b in arm2b/ when it has landed.")
    ap.add_argument("--preview-ref", default="lane-hub2", help="The branch the card's v2 and v3 links point at.")
    args = ap.parse_args()
    plugin = f"agentenv-gridsim @ git+{REPO}@{args.plugin_ref}"
    runs_root = ROOT / "results/runs"
    extras = None if args.v1_only else Extras(
        args.v2_runs or [runs_root / "v2-pilot-sol", runs_root / "v2-pilot-sol-hero"],
        args.v3_runs or [runs_root / n for n in ("hybrid-reference", "v3-pilot-sol", "v3-pilot-sol-energy",
                                                  "v3-pilot-sol-show-energy", "v3-pilot-sol-show-reserves")],
        args.v2_results, args.v3_results, args.train, args.preview_ref)
    with namespace_routing():
        files = build(args.runs, args.results, args.bundle, plugin, extras)
    scan(files, known_values())
    write(files, args.out)
    for path in sorted(files):
        rows = f"{pq.read_metadata(io.BytesIO(files[path])).num_rows:7} rows" if path.endswith(".parquet") else ""
        if not path.startswith(("runs/", "bundles/")):
            print(f"{len(files[path]) / 1e6:9.2f} MB {rows:>12}  {path}")
    for top in ("runs/", "bundles/"):
        sized = [len(c) for p, c in files.items() if p.startswith(top)]
        if sized:
            print(f"{sum(sized) / 1e6:9.2f} MB {len(sized):7} files  {top}")
    tops = Counter(p.split("/")[0] for p in files)
    for top in sorted(tops):
        print(f"{sum(len(c) for p, c in files.items() if p.split('/')[0] == top) / 1e6:9.2f} MB {tops[top]:7} files  "
              f"{top}{'/' if top in MANAGED else ''}")
    print(f"into {args.out}")


if __name__ == "__main__":
    main()
