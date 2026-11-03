"""Build the Hugging Face dataset earakely-scale/GridSimEnv-AgentEnv into a folder, to look at before anything is
pushed. Two kinds of files share it:

- GridSim's, from this checkout: v1_tasks (every battery-day of the four packs at each tier it plays, with the
  battery, the prices, the blind inputs and the path-B prompt exactly as gridsim_core writes it), v1_showcase (the
  display-only famous days), v1_references (the DP optimum, the LP bound, the baselines and the blind anchors) and
  v1_episodes (each gridsim.episode/v1 JSON under --runs, graded again by gridsim_core before it is published, with
  its transcript as chat messages). The results' tables: leaderboard (every model, effort and baseline on the four
  evaluation packs, from results/overview/results.json; the default config) and eval_runs (every schedule behind it,
  re-graded from the committed per-task records by scripts/hub_results.py and checked against the leaderboard).
  Beside them, the Episode JSON the Space reads under runs/, the eval card and board under results/, and the packs as
  JSON lines under raw/packs/.
- agentenv-hf's, one pair per --bundle folder, as `agent-env hf publish` writes them: the bundle's tasks and runs and
  the bundle itself under bundles/, which `agent-env hf run` plays; the card's `agentenv` table names what it needs.

The card is hub/dataset/README.md, the desk's card. It tells the article's story (hub/article) in the article's words
and with its numbers: its prose reads them from the article's facts.json as the chapters do, checked against
results/desk-v4-bench/summary.json, and its figures are the article's charts, captured from the built article; the
rest of its blocks come from summary.json and results/overview/desk.json (scripts/hub_desk.py writes it and the desk's
tables). The v1 tables stay in the repo outside every config. --card-only writes the card alone; --figures adds the
card's figures and the article's film beside it. Every file goes through agentenv-hf's scan for keys and token shapes
before anything is written. Nothing is pushed: upload the folder with `hf upload <repo> <out> --repo-type dataset` after
reading it.

    uv run python scripts/hub_dataset.py --out build/hub/dataset
    uv run python scripts/hub_dataset.py --out build/hub/card --card-only
    uv run python scripts/hub_article.py --build && uv run python scripts/hub_dataset.py --out build/hub/card \
        --card-only --figures
    agent-env gridsim tasks generate --pack ercot-dam-v1-eval --out build/bundles/ercot-dam-v1-eval
    uv run python scripts/hub_dataset.py --out build/hub/dataset --runs results/runs --results results \
        --bundle build/bundles/ercot-dam-v1-eval
"""

import argparse
import base64
import gzip
import importlib.util
import io
import json
import math
import re
import shutil
import tempfile
import tomllib
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from html import escape
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from agent_env.store.routing import namespace_routing
from agentenv_hf import dataset, runs, tables
from agentenv_hf.messages import to_messages
from agentenv_hf.scan import known_values, scan
from huggingface_hub import DatasetCard
from PIL import Image, ImageChops

from gridsim_core.episode import SCHEMA
from gridsim_core.grade import grade
from gridsim_core.prompt import messages, situation, tool_schemas
from gridsim_core.task import data_root

ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "hub/dataset/README.md"
VERSION = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
REPO = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
SETUP = "agent-env gridsim setup --agent"
# The commit bundles/gridsim-v1 was published from; `setup --agent` builds the gridsim-llm its tasks deploy from it.
V1_PLUGIN = f"agentenv-gridsim @ git+{REPO}@3db7869e9df6ce6c9754a1b7166dd11c2906cbc7"
PACKS ={"train": "ercot-dam-v1-train", "eval_2025": "ercot-dam-v1-eval", "eval_iid": "ercot-dam-v1-eval-iid",
         "rtcb": "ercot-dam-v1-rtcb", "showcase": "showcase"}
SPLITS = ("train", "eval_2025", "eval_iid", "rtcb")
TIERS = ("foresight", "blind")
BATTERY = ("p_dis_mw", "p_ch_mw", "energy_mwh", "unit_mwh", "q_15", "k_dis", "k_ch", "soc_levels", "eta", "c_deg",
           "cycle_cap_units", "s0", "s_end_min")
UNITS = ("k_dis", "k_ch", "soc_levels", "cycle_cap_units", "s0", "s_end_min")
BASELINES = ("clock", "threshold", "greedy", "random")
PACK_FILES = ("stats.md", "ridge-v1.json")
TOLERANCE = 1e-6
DATASET = "https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv"
APP = "https://earakely-scale-gridsimenv-agentenv.static.hf.space"
VIEWER = "https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv"
ELSEWHERE = ("v2_", "v3_", "v4_", "v5_", "desk_")
RESULTS = "overview/results.json"
DESK = "overview/desk.json"
BADGES = (
    '<a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv"><img src="https://img.shields.io/badge/'
    '%F0%9F%93%96%20Article-A%20live%20ERCOT%20battery%20desk-0e7d56?style=for-the-badge&labelColor=1a1a1a" '
    'alt="The article: a live ERCOT battery desk" height="32"></a>',
    '<a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv-OpenEnv"><img src="https://img.shields.io/badge/'
    '%E2%96%B6%20Playground-Play%20the%20desk%20live-2a78d6?style=for-the-badge&labelColor=1a1a1a" '
    'alt="Playground: play the desk yourself, or connect your agent" height="32"></a>',
    f'<a href="{VIEWER}"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Replays-Every%20run%20in%203D-FFD21E?'
    'style=for-the-badge&labelColor=1a1a1a" alt="Replays: every benchmark run in 3D" height="32"></a>',
    '<a href="https://github.com/earakely-scale/agentenv-gridsim-plugin"><img src="https://img.shields.io/badge/GitHub-'
    'agentenv--gridsim--plugin-181717?style=for-the-badge&logo=github&labelColor=1a1a1a" alt="Code on GitHub" '
    'height="32"></a>',
    '<a href="https://www.agentenvframework.com"><img src="https://img.shields.io/badge/framework-AgentEnv-6f42c1?'
    'style=for-the-badge&labelColor=1a1a1a" alt="AgentEnv Framework" height="32"></a>')
ARTICLE_APP = ROOT / "hub/article/app"
ARTICLE_DATA = ARTICLE_APP / "src/content/assets/data"
FILM = "assets/gridsim-run.gif"
FIGS = "assets/article"
CARD_W, PHONE_W, PHONE = 800, 334, "(max-width: 480px)"
"""The Hub card column's width at 1440 px and on a 390 px phone, and the phone query the card's pictures switch on."""
CAPTIONS = ROOT / "results/overview/figures/captions.json"
BEAM = ROOT / "results/beam-agent/beam"
MANAGED = ("tasks", "references", "episodes", "runs", "results", "raw", "bundles", "leaderboard", "eval_runs")

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


LEADERBOARD = pa.schema([
    ("model", STR), ("effort", STR), ("score", F64), ("ci_low", F64), ("ci_high", F64), ("usd_per_battery_day", F64),
    ("pack", STR), ("weights", STR), ("frontier", BOOL), ("valid", F64), ("battery_days", I64), ("metric", STR),
    ("type", STR), ("source", STR),
])
EVAL_RUNS = pa.schema([
    ("model", STR), ("effort", STR), ("task_id", STR), ("score", F64), ("kind", STR), ("profit_usd_per_mw", F64),
    ("optimum_usd_per_mw", F64), ("actions", pa.list_(I64)), ("date", STR), ("settlement_point", STR),
    ("battery", STR), ("power_mw", F64), ("energy_mwh", F64), ("profit_usd", F64), ("idle_usd_per_mw", F64),
    ("forecast", pa.list_(F64)), ("prices", pa.list_(F64)), ("usd", F64), ("output_tokens", I64), ("weights", STR),
    ("tier", STR), ("source", STR),
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


def h(x: float, nd: int = 3, sign: bool = False) -> str:
    """Half-up, as the results READMEs print their stored four-decimal values; a true minus sign."""
    q = abs(Decimal(str(x))).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP)
    return f"{'−' if x < 0 and q else '+' if sign else ''}{q}"


def ci(c: list[float], nd: int = 3, sign: bool = False) -> str:
    return f"[{h(c[0], nd, sign)}, {h(c[1], nd, sign)}]"


def usd(x: float) -> str:
    return f"${x:.5f}" if x < 0.001 else f"${x:.4f}"


def kd(x: float, sign: bool = False) -> str:
    """Thousands of dollars: +$41.2k, −$3.4k."""
    return f"{'−' if x < 0 else '+' if sign else ''}${h(abs(x), 1)}k"


def md(text: str) -> str:
    return text.replace("*", "\\*")


def ev(path: str, label: str) -> str:
    return f"[{label}]({DATASET}/blob/main/{path})"


def tree(path: str) -> str:
    return f"[{path}]({DATASET}/tree/main/{path})"


def folder(rel: str) -> str:
    """The results folder that documents a file: the nearest one up from it with a README."""
    return next(p.as_posix() for p in (Path(rel), *Path(rel).parents)
                if p.parts[:1] == ("results",) and (ROOT / p / "README.md").is_file())


def captions() -> dict:
    return json.loads(CAPTIONS.read_text())


def figure(name: str, n: int, alt: str) -> str:
    """A results-page figure as the card prints it: its title above the bare chart, drawn in the page's light or dark
    theme as the Hub's theme is (Tailwind's dark: classes, which the Hub keeps on a card's HTML), then its caption and
    notes, with its sources linked into this dataset."""
    c = captions()[name]
    src = c["src"].removeprefix("Sources: ").removesuffix(" in the GridSimEnv-AgentEnv dataset.")
    src = re.sub(r"results/[\w./-]+", lambda m: tree(m[0]), src)
    note = "".join(f" {md(x)}" for x in c["notes"])
    return "\n".join([f"**{md(c['title'])}**", "",
                      f'<img class="dark:hidden" src="assets/figures/{name}.png" alt="{escape(alt)}">',
                      f'<img class="hidden dark:block" src="assets/figures/{name}-dark.png" alt="{escape(alt)}">', "",
                      f"<small>Figure {n} · {md(c['sub'])}{note} Sources: {src}.</small>"])


LINKS = {"results/train/4b-blind": "run 4", "results/cost-matched": "the cost-matched contest",
         "results/economics": "the economics", "results/train/4b-dpa": "run 3", "results/train/4b-v2": "run 2"}


def glance_block(r: dict) -> str:
    s = r["scores"]
    cells = [f'<td width="50%"><b>{escape(g["value"])}</b> {escape(g["label"])}<br><small>{escape(g["text"])} '
             "Evidence: " + " · ".join(f'<a href="{DATASET}/blob/main/{x}/README.md">{LINKS[x]}</a>'
                                       for x in g["src"]) + "</small></td>" for g in r["glance"]]
    alt = ("Before and after training. Blind capture on the 331 newest battery-days: untrained Qwen3-4B "
           f"{h(s[0]['untrained']['mean'])}, trained {h(s[0]['trained']['mean'])}, GPT-6 Luna "
           f"{h(s[0]['luna']['mean'])}, GPT-6.1 Sol {h(s[0]['sol']['mean'])}, persistence-DP "
           f"{h(s[0]['baseline']['mean'])}. Blind 2025: {h(s[1]['untrained']['mean'])} to "
           f"{h(s[1]['trained']['mean'])}. Foresight 2025: {h(s[2]['untrained']['mean'], 2)} to "
           f"{h(s[2]['trained']['mean'])}. In dollars per MW-year on 2025: {kd(dollar(r, 'base'))} to "
           f"{kd(dollar(r, '4b-sampled'))}, against persistence-DP's {kd(dollar(r, 'persistence-dp'))} and Sol's "
           f"{kd(dollar(r, 'sol'))}.")
    return "\n".join([
        "A 4-billion-parameter open model, **Qwen3-4B**, trained on this environment's exact grader, went from losing "
        "money on a Texas grid battery to **bidding as well as GPT-6 Luna at a quarter of its cost**. It still trails "
        "GPT-6.1 Sol, and a free heuristic, by thousands of dollars per MW of battery a year.", "",
        "<table>", f"<tr>{cells[0]}{cells[1]}</tr>", f"<tr>{cells[2]}{cells[3]}</tr>", "</table>", "",
        figure("before-after", 1, alt)])


def dollar(r: dict, key: str, pack: str = "eval2025") -> float:
    return next(x for x in r["dollars"]["packs"][pack]["ladder"] if x["key"] == key)["yr"]["mean"]


ORDER = ("blind-fresh", "blind-eval2025", "foresight-eval2025", "foresight-fresh")
SPLIT = {"blind-fresh": "blind_fresh", "blind-eval2025": "blind_eval_2025", "foresight-eval2025": "foresight_eval_2025",
         "foresight-fresh": "foresight_fresh"}
REFS = {"teacher-dp": "forecaster + exact DP (no LLM)", "persistence-dp": "persistence-DP (no LLM)",
        "greedy": "greedy rule (no LLM)", "threshold": "threshold rule (no LLM)"}
BASELINE_SRC = {"persistence-dp": "results/blind-ceiling", "teacher-dp": "results/train/4b-blind",
                "foresight-eval2025": "results/train/4b-dpa", "foresight-fresh": "results/fresh/2026-10"}


def leaderboard_rows(r: dict) -> list[dict]:
    """The leaderboard config: every model row of results.json's leaderboard, best first, then the baselines the article
    draws beside them, pack by pack in ORDER."""
    packs = {p["key"]: p for p in r["leaderboard"]["packs"]}
    front = {x["key"]: x["frontier"] for x in r["frontier"]["points"]}
    rows = []
    for key in ORDER:
        p = packs[key]
        common = {"pack": SPLIT[key], "metric": p["metric"], "battery_days": p["n_tasks"]}
        out = [common | {"model": x["label"], "effort": x["effort"], "weights": "open" if x["open"] else "API",
                         "type": "model", "score": x["mean"], "ci_low": x["ci"][0], "ci_high": x["ci"][1],
                         "usd_per_battery_day": x["usd"], "frontier": front[x["key"]] if key == "blind-fresh" else None,
                         "valid": x["valid"], "source": folder(x["src"])} for x in p["rows"]]
        out += [common | {"model": REFS[b["key"]], "effort": None, "weights": None, "type": "baseline",
                          "score": b["mean"], "ci_low": b["ci"][0], "ci_high": b["ci"][1], "usd_per_battery_day": None,
                          "frontier": None, "valid": None, "source": BASELINE_SRC.get(b["key"]) or BASELINE_SRC[key]}
                for b in p["baselines"] if b["key"] in REFS]
        rows += sorted(out, key=lambda x: (x["type"] == "baseline", -x["score"]))
    return rows


def result_tables(r: dict, runs: dict[str, list[dict]]) -> dict[str, bytes]:
    """The leaderboard and eval_runs configs: the leaderboard from results.json, the runs as hub_results.eval_runs
    re-grades them, each run's mean score, failure kinds and cost checked against its leaderboard row."""
    packs = {p["key"]: {x["key"]: x for x in p["rows"]} for p in r["leaderboard"]["packs"]}
    files = {"leaderboard/v1.parquet": parquet(leaderboard_rows(r), LEADERBOARD)}
    for key in ORDER:
        by: dict[str, list[dict]] = {}
        for row in runs[key]:
            by.setdefault(row["key"], []).append(row)
        if by.keys() != packs[key].keys():
            raise Mismatch(f"{key}: runs {sorted(by)}, leaderboard rows {sorted(packs[key])}")
        for k, rows in by.items():
            want, n = packs[key][k], len(rows)
            kinds = {x: sum(row["kind"] == x for row in rows) for x in {row["kind"] for row in rows}}
            cost = [row["usd"] for row in rows]
            if (n != want["n"] or abs(sum(row["score"] for row in rows) / n - want["mean"]) > 5e-5
                    or kinds != want["kinds"]
                    or (want["usd"] is None) != (None in cost)
                    or want["usd"] is not None and abs(sum(cost) / n - want["usd"]) > 5e-8):
                raise Mismatch(f"{key} {k}: the runs do not reproduce the leaderboard row")
        rank = {k: i for i, k in enumerate(sorted(packs[key], key=lambda k: -packs[key][k]["mean"]))}
        rows = [x | {"weights": "open" if x["open"] else "API", "source": folder(packs[key][x["key"]]["src"])}
                for x in sorted(runs[key], key=lambda x: (x["date"], x["task_id"], rank[x["key"]]))]
        files[f"eval_runs/v1/{SPLIT[key]}.parquet"] = parquet(rows, EVAL_RUNS)
    return files


def counts(r: dict) -> dict[str, str]:
    """The row counts the card's table of configs prints, from results.json."""
    packs = {p["key"]: p for p in r["leaderboard"]["packs"]}
    n = {k: len(packs[k]["rows"]) * packs[k]["n_tasks"] for k in ORDER}
    splits = [f"`{SPLIT[k]}` ({n[k]:,})" for k in ORDER]
    return {"leaderboard_rows": f"{len(leaderboard_rows(r)):,}", "eval_runs_rows": f"{sum(n.values()):,}",
            "eval_runs_splits": f"{', '.join(splits[:-1])} and {splits[-1]}"}


def packs_block(r: dict) -> str:
    p = {x["key"]: x for x in r["leaderboard"]["packs"]}
    f, e, fe, ff = (p[k] for k in ORDER)
    return ("- **The four evaluation packs** name `leaderboard`'s `pack` column and `eval_runs`' splits: "
            f"`blind_fresh`, ERCOT's {f['n_tasks']} newest battery-days at the blind tier ({f['when']}, the newest "
            f"days at the time of the runs); `blind_eval_2025`, {e['n_tasks']} held-out battery-days of 2025 at the "
            f"blind tier; `foresight_eval_2025`, {fe['n_tasks']} of 2025's held-out battery-days at the foresight "
            f"tier, the training runs' held-out set; and `foresight_fresh`, the {ff['n_tasks']} newest at the "
            "foresight tier. The newest days are not in `v1_tasks`: the plugin carries them as the packs "
            "`ercot-dam-v1-fresh-2026-10` and `ercot-dam-v1-fresh-2026-10-blind`.")


def gpu(x: float | None) -> str:
    return "–" if x is None else f"${x:.2f}" if x % 1 else f"${x:.0f}"


def gap(g: dict, nd: int = 3) -> str:
    return f"{h(g['mean'], nd, True)} {ci(g['ci'], nd, True)}"


def run_line(x: dict) -> str:
    kind = "pre-registered" if x["registered"] else "exploratory"
    return (f"| **{x['label']}**<br>{x['model']}, {kind} | {md(x['change'])} | {x['result']} | {md(x['lesson'])} "
            f"{ev(x['src'] + '/README.md', 'Evidence')} | {gpu(x['usd'])} |")


def stacked(g: dict) -> str:
    return f"{h(g['mean'], sign=True)}<br><small>{ci(g['ci'], sign=True)}</small>"


def pack_line(x: dict) -> str:
    u, t, b, g = x["untrained"], x["trained"], x["baseline"], x["gaps"]
    before = "not run" if u is None else h(u["mean"], 2 if u["mean"] < 0.1 else 3)
    return (f"| {x['label']}<br><small>{x['n_tasks']} battery-days</small> | {before} → **{h(t['mean'])}**<br>"
            f"<small>{t['run']}</small> | {h(x['luna']['mean'])} | {h(x['sol']['mean'])} | {h(b['mean'])}<br>"
            f"<small>{b['label']}</small> | {stacked(g['trained_minus_luna'])} | {stacked(g['trained_minus_sol'])} |")


def training_block(r: dict) -> str:
    t, c = r["training"], r["training"]["curve"]
    pl = t["planning"]
    e, fr = pl["eval2025"], pl["fresh"]
    alt_t = (f"Held-out reward against training step on 200 foresight days of 2025: run 3 with exact DP advantages "
             f"from {h(c['run3'][0]['sampled']['mean'])} to {h(c['run3'][-1]['sampled']['mean'])}; run 2, GRPO from "
             f"the same warm start, from {h(c['run2']['start']['mean'])} to {h(c['run2']['end']['mean'])}; run 1, GRPO "
             f"from a weaker warm start, from {h(c['run1']['start']['mean'])} to {h(c['run1']['end']['mean'])}. "
             f"Reference lines: GPT-6.1 Sol {h(c['sol']['mean'])}, GPT-6 Luna {h(c['luna_high']['mean'])}, the "
             f"greedy rule {h(c['greedy_rule']['mean'])}.")
    alt_p = (f"Run 4 on blind 2025: after SFT {h(e['sft']['mean'])}, after RL {h(e['final']['mean'])}, the exact DP on "
             f"its own written forecast {h(e['dp_own']['mean'])}, the teacher's forecast with the DP "
             f"{h(e['teacher']['mean'])}, GPT-6.1 Sol {h(e['sol']['mean'])}; on the newest days "
             f"{h(fr['sft']['mean'])}, {h(fr['final']['mean'])}, {h(fr['dp_own']['mean'])}, "
             f"{h(fr['teacher']['mean'])} and {h(fr['sol']['mean'])}.")
    return "\n".join([
        "Qwen3-4B (thinking off, LoRA adapters, one GPU at a time) trains on battery-days of 2014 to 2024 from the "
        "`train` split and is scored on days it never saw: 200 held-out foresight days and 300 blind days of 2025, and "
        "ERCOT's ten newest days. Each registered run committed its plan, schedule and bars before its first step.", "",
        "### How it was trained", "",
        "1. **One prompt, one completion, an exact reward.** `v1_tasks`' `prompt`, a completion that ends in a "
        "`submit_schedule` call, and `gridsim_core.trl.reward_fn`, the env's own grader: the schedule against the "
        "dynamic program's optimum, in under a millisecond.",
        "2. **SFT on solver labels.** The DP gives every training day's optimal schedule for free. Ten thousand of "
        "them, each with a rationale that tracks the state of charge and states the DP's buy-and-sell rule (SFT-10k), "
        f"took the 4B from {h(c['base']['mean'], 2)} to {h(c['run2']['start']['mean'], 2)} with no RL.",
        "3. **GRPO in TRL stalls on a confident policy.** TRL's `GRPOTrainer` with colocated vLLM lifted run 1's "
        f"weaker warm start ({h(c['run1']['gain']['mean'], sign=True)}); from SFT-10k about half the days gave eight "
        f"identical rollouts and no gradient (run 2, {h(c['run2']['gain']['mean'], sign=True)}).",
        "4. **Exact advantages instead of a group baseline.** Run 3 credits each hour with "
        "A_t = Q\\*(s_t, a_t) − V\\*(s_t) from the DP's value table, on the tokens of that hour's integer, in a "
        "PPO-clipped loop with a KL anchor to SFT-10k (PyTorch and PEFT, rollouts in vLLM): held-out reward rose "
        f"{gap(c['run3_gain'])}.",
        "5. **Blind: forecast, then plan.** Run 4 continues from run 3 on the blind tier: SFT on a teacher "
        "forecaster's written 24-hour forecast and the DP plan on it, then the same exact-advantage RL on the plan, "
        "credited against the model's own forecast.", "",
        figure("training", 3, alt_t), "",
        "### Blind: forecast, then plan", "",
        f"Run 4's written forecasts miss by {h(pl['mae']['final'], 2)} $/MWh over all hours, against its teacher's "
        f"{h(pl['mae']['teacher'], 2)} and yesterday's prices' {h(pl['mae']['persistence'], 2)}. Planned by the exact "
        f"DP they would capture {h(e['dp_own']['mean'])}, level with GPT-6.1 Sol "
        f"({gap(e['gaps']['dp_own_minus_sol'])}, reported, not registered); its own schedules capture "
        f"{h(e['final']['mean'])}, {gap(e['gaps']['final_minus_sol'])} behind Sol, the registered primary, not met.",
        "", figure("planning", 4, alt_p), "",
        "### Before and after, pack by pack", "",
        "The cost-matched contest's comparisons under one harness, with day-block 95% CIs on the paired gaps. The "
        "score is `r_opt`, the hindsight optimum's share on the reward's scale (idle 0.2, hindsight 1.0; the "
        "cross-version C of [Grading](#grading) is (r_opt − 0.2)/0.8 wherever r_opt is above 0). At the foresight "
        "tier it equals R.", "",
        "| Pack | 4B, untrained → trained | GPT-6 Luna, high | GPT-6.1 Sol, high | Simple rule | "
        "Trained − Luna [95% CI] | Trained − Sol [95% CI] |", "|---|---|---|---|---|---|---|",
        *map(pack_line, r["scores"]), "",
        f"About ${t['gpu_usd_total']:.0f} of GPU in all, from the first 1.7B arm to run 4; training called no API, "
        "and the adapters are not published. The recipes, with their scripts, logs and package versions, are under "
        f"{tree('results/train')}.", "",
        "<details>", "<summary><b>Every run</b>: what it changed, what it scored held out and what it taught</summary>",
        "", "| Run | What changed | Held-out | What it taught | GPU |", "|---|---|---|---|---:|",
        *map(run_line, t["runs"]), "",
        "Held-out is reward R on 200 foresight days of 2025 for runs 1 to 3 (500 unseen days of 2014 to 2024 for the "
        "confirmation) and blind capture on 300 days of 2025 for run 4.", "", "</details>"])


def model_name(x: dict) -> str:
    if x["label"].startswith("Qwen3-4B, trained"):
        return "**Qwen3-4B, trained**"
    return f"{x['label']}, {x['effort']}" if x.get("effort") else x["label"]


def board_line(x: dict, gaps: dict) -> str:
    band = ci([x["ci_low"], x["ci_high"]])
    if x["type"] == "baseline":
        return f"| *{x['model']}* | *{h(x['score'])}* | *{band}* | – | – | – | – |"
    name = f"{x['model']}, {x['effort']}" if x["effort"] else x["model"]
    if x["model"].startswith("Qwen3-4B, trained"):
        name, score = f"**{name}**", f"**{h(x['score'])}**"
    else:
        score = h(x["score"])
    g = gaps.get((x["model"], x["effort"]))
    return (f"| {name} | {score} | {band} | {usd(x['usd_per_battery_day'])} | {x['weights']} | "
            f"{'yes' if x['frontier'] else '–'} | {gap(g) if g else '–'} |")


def matrix(r: dict) -> list[str]:
    """Every model and baseline on every pack, the score with its CI, best on the blind newest days first."""
    packs = {p["key"]: p for p in r["leaderboard"]["packs"]}
    cells: dict[str, dict[str, str]] = {}
    for key in ORDER:
        p = packs[key]
        for x in p["rows"]:
            cells.setdefault(model_name(x), {})[key] = f"{h(x['mean'])}<br><small>{ci(x['ci'])}</small>"
        for b in p["baselines"]:
            if b["key"] in REFS:
                cells.setdefault(f"*{REFS[b['key']]}*", {})[key] = (
                    f"{h(b['mean'])}<br><small>{ci(b['ci'])}</small>")
    first = {model_name(x): x["mean"] for x in packs["blind-fresh"]["rows"]} | {
        f"*{REFS[b['key']]}*": b["mean"] for b in packs["blind-fresh"]["baselines"] if b["key"] in REFS}
    names = sorted(cells, key=lambda n: (n not in first, -first.get(n, 0), n))
    head = " | ".join(f"{packs[k]['label']} ({packs[k]['n_tasks']})" for k in ORDER)
    return [f"| Model | {head} |", "|---|" + "---|" * len(ORDER),
            *(f"| {n} | " + " | ".join(cells[n].get(k, "–") for k in ORDER) + " |" for n in names)]


INVALID = ("malformed", "truncated", "error")


def holds(ok: bool, wording: str) -> None:
    if not ok:
        raise SystemExit(f"the card says {wording!r}, which results.json no longer supports; update the wording")


def board_block(r: dict) -> str:
    f = r["frontier"]
    p, refs, ratio = {x["key"]: x for x in f["points"]}, f["refs"], f["ratios"]
    beams = sorted((x for x in f["points"] if x["family"] == "beam"), key=lambda x: -x["mean"])
    sol = p["sol"]["final_minus"]
    lb = {x["key"]: x for x in r["leaderboard"]["packs"]}
    fresh = {x["key"]: x for x in lb["blind-fresh"]["rows"]}
    rows = sorted((x for x in leaderboard_rows(r) if x["pack"] == "blind_fresh"), key=lambda x: -x["score"])
    gaps = {(x["label"], x["effort"]): x["final_minus"] for x in f["points"] if "final_minus" in x}
    ks = fresh["sol"]["kinds"]
    broke = {m: sum(v for k, v in fresh[m]["kinds"].items() if k not in ("ok", *INVALID)) for m in ("final", "sol")}
    fore = [lb[k]["rows"] for k in ("foresight-eval2025", "foresight-fresh")]
    above = {x["key"] for x in lb["blind-fresh"]["rows"] if x["mean"] > refs["persistence_dp"]["mean"]}
    holds(all(max(lb[k]["rows"], key=lambda x: x["mean"])["key"] == "sol" for k in ORDER), "Sol leads every pack")
    holds(fresh["final"]["valid"] == 1 and broke["sol"] == 0, "the 4B always submits and Sol breaks no rule")
    holds(above == {"sol", "beam-max"}, "only Sol and Beam at max effort score above persistence-DP")
    alt = ("Capture against cost per battery-day on a log scale, blind, the 331 newest battery-days. The frontier "
           f"runs through the untrained 4B ({h(p['base']['mean'])} at {usd(p['base']['usd'])}), the trained 4B "
           f"({h(p['final']['mean'])} at {usd(p['final']['usd'])}) and GPT-6.1 Sol ({h(p['sol']['mean'])} at "
           f"{usd(p['sol']['usd'])}). GPT-6 Luna at low, medium and high effort and Beam-1.0 at four efforts lie "
           "below it. Persistence-DP and a forecaster with the exact DP, which use no LLM, are drawn as lines at "
           f"{h(refs['persistence_dp']['mean'])} and {h(refs['teacher_dp']['mean'])}.")
    beam = [f"- **Beam-1.0** (open weights, untrained) is off the frontier at every effort: at its best, "
            f"{beams[0]['effort']}, it captures {h(beams[0]['mean'])} for {usd(beams[0]['usd'])} a battery-day, and "
            "Sol captures more for less."] if beams else []
    return "\n".join([
        "Every model plays the same one-call harness: the battery and the day's prices in, or at the blind tier the "
        "week before, and one `submit_schedule` call out. Training uses exactly this prompt, so trained and frontier "
        "models meet on equal terms. Scores put idle at 0.2 and the hindsight optimum at 1; the blind tier is where "
        "models separate.", "",
        f"**Bidding blind on ERCOT's {f['n_tasks']} newest battery-days** ({lb['blind-fresh']['when']}), best first:",
        "", "| Model, effort | Score | 95% CI | $ per battery-day | Weights | Frontier | Trained 4B − this [95% CI] |",
        "|---|---|---|---:|---|---|---|", *(board_line(x, gaps) for x in rows), "",
        figure("frontier", 2, alt), "",
        "- **The trained 4B is the cheapest model on the frontier above its untrained base.** It is level with GPT-6 "
        f"Luna at high effort, {gap(p['luna-high']['final_minus'])}, at a quarter of the cost (Luna costs "
        f"{h(ratio['luna_high'], 1)}× as much), and ahead of Luna at low effort, the matched cost "
        f"({h(ratio['luna_low'], 1)}×), by {gap(p['luna-low']['final_minus'])}.",
        f"- **GPT-6.1 Sol** captures {h(-sol['mean'], sign=True)} {ci([-sol['ci'][1], -sol['ci'][0]], sign=True)} "
        f"more, for {h(ratio['sol'], 0)}× the cost, and is the best model on every pack.", *beam,
        "- **Two baselines use no LLM:** persistence-DP, the exact DP on yesterday's prices, captures "
        f"{h(refs['persistence_dp']['mean'])}, and run 4's teacher forecaster planned with the exact DP "
        f"{h(refs['teacher_dp']['mean'])}. On these days only Sol and Beam at max effort score above persistence-DP.",
        f"- **How they fail.** The trained 4B always submits, and {broke['final']} of its "
        f"{lb['blind-fresh']['n_tasks']} "
        "schedules break a rule; GPT-6.1 Sol keeps every rule but sends no parseable call on "
        f"{ks.get('malformed', 0)}. `eval_runs` names the failure of every schedule.",
        "- **Foresight is nearly solved at the top.** With the day's prices in view, Sol scores "
        + " and ".join(dict.fromkeys(h(next(x for x in rs if x["key"] == "sol")["mean"]) for rs in fore))
        + " on the two foresight packs.",
        "- The 4B, Luna at high and low effort and Sol are the cost-matched contest's pre-registered rows "
        f"({tree('results/cost-matched')}); Luna at medium effort and Beam are descriptive runs under the same harness "
        f"({tree('results/beam-agent')}).", "",
        "<details>", "<summary><b>Every pack</b>: each model and baseline on the four evaluation packs</summary>", "",
        *matrix(r), "",
        "Blind packs score hindsight capture `r_opt`, foresight packs the reward R; both put idle at 0.2 and the "
        "optimum at 1. Brackets: day-block bootstrap 95% CIs. The trained 4B is run 4 on the blind packs and run 3 "
        "at foresight. The `leaderboard` config has every row with its cost, validity and source, and `eval_runs` "
        "every schedule behind it.", "", "</details>"])


ROWS = ("optimum", "sol", "persistence-dp", "luna-high", "luna-medium", "4b-sampled", "sft", "ridge-dp", "greedy-d1",
        "luna-low", "threshold-d1", "idle", "base")
SHORT = {"sol": "GPT-6.1 Sol", "persistence-dp": "persistence-DP", "luna-high": "GPT-6 Luna (high)",
         "luna-medium": "GPT-6 Luna (medium)", "4b-sampled": "trained Qwen3-4B", "ridge-dp": "ridge-DP",
         "greedy-d1": "greedy rule on yesterday's prices", "luna-low": "GPT-6 Luna (low)",
         "threshold-d1": "threshold rule on yesterday's prices", "idle": "idle", "base": "untrained Qwen3-4B"}


def yr(x: dict | None) -> str:
    return "–" if x is None else f"{h(x['yr']['mean'], 1)} {ci(x['yr']['ci'], 1)}"


def per100(x: dict | None) -> str:
    return "–" if x is None else f"{'−' if x['per_100mw_yr'] < 0 else ''}${abs(x['per_100mw_yr']) / 1000:.2f}M"


def kk(x: dict, sign: bool = False) -> str:
    return f"{kd(x['mean'], sign)} {ci(x['ci'], 1, sign)}"


def worth_block(r: dict) -> str:
    d = r["dollars"]["packs"]
    e, fr = d["eval2025"], d["fresh"]
    get = {p: {x["key"]: x for x in d[p]["ladder"]} for p in d}
    lad = get["eval2025"]
    rows = []
    for key in ROWS:
        a, b = get["eval2025"].get(key), get["fresh"].get(key)
        if a or b:
            x = a or b
            name = f"**{x['label']}**" if key == "4b-sampled" else x["label"]
            rows.append(f"| {name} | {yr(a)} | {per100(a)} | "
                        f"{'–' if a is None or a['inference'] is None else usd(a['inference'])} | {yr(b)} |")
    g, gf = e["gaps"], fr["gaps"]
    up, vb, sp = g["4b-sampled - base"], g["4b-sampled - persistence-dp"], g["sol - persistence-dp"]
    inf, pay, q = e["inference"], r["dollars"]["payback"], e["quartiles"]
    alt_l = ("Dollars per MW of battery power per year on blind 2025: " + "; ".join(
        f"{SHORT[x['key']]} {kd(x['yr']['mean'])}" for x in sorted(
            (x for x in e["ladder"] if x["key"] not in ("optimum", "sft")), key=lambda x: -x["yr"]["mean"]))
        + f"; the hindsight optimum {kd(lad['optimum']['yr']['mean'])}.")
    alt_q = ("Gain over persistence-DP in $ per MW-day by quartile of how much the day's price shape changes, blind "
             "2025. " + "; ".join(f"Q{x['q']}: Sol {h(x['sol']['mean'], 1, True)}, Luna "
                                  f"{h(x['luna-high']['mean'], 1, True)}, trained 4B "
                                  f"{h(x['4b-sampled']['mean'], 1, True)}, "
                                  f"room {h(x['shortfall']['mean'], 1)}" for x in q) + ".")
    return "\n".join([
        "Every recorded blind schedule settled again at ERCOT's day-ahead prices, its profit per MW of battery power: "
        f"× 365 for a year, × 100 for a 100 MW battery. Blind 2025 ({e['n_tasks']} battery-days on {e['n_days']} days) "
        f"and the newest days ({fr['n_tasks']} on {fr['n_days']}), day-block 95% CIs. A reply with no valid schedule "
        "settles as idle. A descriptive re-analysis computed after the results, not pre-registered "
        f"({tree('results/economics')}).", "",
        figure("ladder", 5, alt_l), "",
        f"- **Training bought {kd(up['yr']['mean'], True)} per MW-year {ci(up['yr']['ci'], 1, True)}** on 2025's "
        f"days ({kk(gf['4b-sampled - base']['yr'], True)} on the newest): from {kd(lad['base']['yr']['mean'])}, "
        f"worse than idle, to {kd(lad['4b-sampled']['yr']['mean'])}, about ${up['per_100mw_yr'] / 1000:.1f}M a year "
        "for a 100 MW battery.",
        "- **The trained 4B still earns less than persistence-DP**, the exact DP on yesterday's prices: "
        f"{kk(vb['yr'], True)} per MW-year on 2025 ({kk(gf['4b-sampled - persistence-dp']['yr'], True)} on the newest "
        f"days, not separated). **GPT-6.1 Sol beats it by {kk(sp['yr'], True)}** "
        f"({kk(gf['sol - persistence-dp']['yr'], True)}), about ${sp['per_100mw_yr']:,.0f}k a year for a 100 MW "
        "battery.",
        "- **Inference cost against value.** One call per battery-day, whatever the battery's size: Sol's "
        f"${inf['sol_over_persistence']['inference_usd_per_battery_yr']:.2f} of inference a battery-year buys that "
        f"${sp['per_100mw_yr']:,.0f}k, and its extra ${inf['sol_over_4b']['extra_inference_usd_per_battery_yr']:.2f} "
        f"over the trained 4B buys ${inf['sol_over_4b']['decision_gap_k_usd_per_100mw_yr']:,.0f}k a year of better "
        "decisions per 100 MW. At grid scale, decision quality, not inference cost, decides which model to run.",
        "- **Training payback.** Against renting the same score from GPT-6 Luna at high effort, run 4's GPU bill "
        f"(${pay['run 4']['gpu_usd']}) is repaid by its inference savings after about "
        f"{round(pay['run 4']['battery_days'], -3):,} battery-days, run 3's (${pay['run 3']['gpu_usd']}) after about "
        f"{round(pay['run 3']['battery_days'], -3):,}.", "",
        "**What these dollars are and aren't.**", "",
        "- **Day-ahead energy arbitrage only**, settled at ERCOT's hourly day-ahead prices at 7 hubs and 8 load zones. "
        "No real-time market and no ancillary services, where real ERCOT batteries earn much of their revenue: this is "
        "the value of the day-ahead decisions, not a battery's total revenue.",
        "- **A price-taker with perfect execution**: every MWh clears at the published price and moves no price.",
        "- **Archetype batteries**, 7.5 to 225 MW and 1, 2 or 4 hours, sized from the ERCOT fleet in EIA-860, with a "
        f"flat degradation cost of $4 or $8 per MWh discharged on {e['degradation_days']} of the {e['n_tasks']} "
        f"battery-days of 2025 and {fr['degradation_days']} of the {fr['n_tasks']} newest, $0 on the rest; no "
        "capacity fade, O&M or capital cost.",
        "- **× 365 is a unit, not a forecast**: 2025's 191 days run from January to November, and the newest pack is "
        "10 days of October 2026.", "",
        "### When reasoning pays", "",
        "Split 2025's 191 days into quartiles by how far the day's 24 hourly prices move from the day before's shape "
        "(1 − Pearson r). When the day repeats yesterday, persistence-DP is within "
        f"${h(q[0]['shortfall']['mean'], 1)}–{h(q[1]['shortfall']['mean'], 1)} per MW-day of the optimum: Sol stays "
        "level with it, while Luna and the 4B lose money by moving off it. When the shape changes (Q4), persistence-DP "
        f"falls ${h(q[3]['shortfall']['mean'], 1)} short; Sol recovers ${h(q[3]['sol']['mean'], 1)} of it "
        f"{ci(q[3]['sol']['ci'], 1, True)}, while Luna and the 4B only draw level. "
        f"{e['top_days']['sol_share_from_top']:.0%} of Sol's net gain over persistence-DP comes from its best "
        f"{e['top_days']['k']} days.", "",
        figure("regimes", 6, alt_q), "",
        "<details>", "<summary><b>Every policy in dollars</b>, on both blind packs</summary>", "",
        "| Policy | 2025: $k per MW-year [95% CI] | 2025: per 100 MW-year | 2025: inference per battery-day | "
        "Newest days: $k per MW-year [95% CI] |", "|---|---|---:|---:|---|", *rows, "", "</details>"])


def live_block(r: dict) -> str:
    return (f"[The live board]({APP}/board.html) tests the agents on days that have not happened. Before ERCOT's "
            "day-ahead market closes for a delivery day, GPT-6.1 Sol, GPT-6 Luna, the trained 4B (run 4) and three "
            "rules each seal a 24-hour schedule for 45 batteries (15 hubs and load zones × a 1-, 2- and 4-hour battery "
            "at 100 MW) as a timestamped commit to this dataset's `live/` folder; when ERCOT posts the day's prices, "
            "every schedule is settled at them and the cumulative P&L updates. The prices do not exist when a schedule "
            "is published, so no model can have seen them. Passes now run on demand rather than daily (amendment 1 of "
            f"the [pre-registration]({REPO}/blob/main/{r['live']['prereg']})); the first seal is for "
            f"{r['live']['first_seal']}. A descriptive track record, not a test with a verdict.")


def results_blocks(r: dict) -> dict[str, str]:
    """The card's results sections from results/overview/results.json (scripts/hub_results.py writes it)."""
    return {"glance": glance_block(r), "packs": packs_block(r), "board": board_block(r),
            "training-results": training_block(r), "worth": worth_block(r), "live": live_block(r)}


def desk_blocks(d: dict, bench: tuple[dict, list[dict]], f: dict) -> dict[str, str]:
    """The card's blocks in the article's order: the film, the before and after, Try it, the outside figures, the
    eval's cost chart and table, the rollout, the reward, the training and where models fail, each figure the article's
    chart and every number from the article's facts.json, summary.json or the article's chart data; then what is in
    the dataset and, folded, the desk, how the benchmark ran, its limitations and deviations, the earlier versions
    from results/overview/desk.json and how to run it, and the line to the archived v1."""
    s, grades = bench
    results = [f"<details>\n<summary><b>{v['version']}, {v['name']}</b>: the results</summary>\n\n"
               f"{desk_results(v, d)}\n\n</details>" for v in reversed(ladder(d))]
    checked = [f"<details>\n<summary><b>{v['version']}, {v['name']}</b>: a price-impact check on {v['check_of']}"
               f"</summary>\n\n{price_check(v, d)}\n\n</details>" for v in checks(d)]
    return {"badges": "\n".join(BADGES), "film": film_block(f, s, grades),
            "duel": duel_block(f, article("duel.json")), "tryit": tryit_block(f), "tiles": tiles_block(f),
            "pareto": pareto_figure(s, f), "beam-move": beam_move_figure(f), "board": board_card(s),
            "rollout": rollout_block(f), "reward": reward_figure(f, article("reward.json")),
            "train": train_figure(f, article("train.json")), "fail": fail_block(article("failures.json")),
            "inside": inside_card(d, bench), "ladder": ladder_block(d), "how": how_card(s),
            "bench-rule": f"- **Which half of the benchmark leads.** {s['text']['rule']} "
                          + re.split(r"(?<=\.)\s+(?=[A-Z])", s["text"]["halves"])[-1], "limits": limits_card(s),
            "deviations": deviations_card(s),
            "earlier": "\n\n".join([across(d), *results, *checked, models_block(d)]), "quickstart": run_card(s),
            "archive": ARCHIVE}


def article(name: str) -> dict:
    return json.loads((ARTICLE_DATA / name).read_text())


def dollars(x: float) -> str:
    """Whole dollars as the article prints them, the cents rounded half to even."""
    w = round(abs(x))
    return f"{'−' if x < 0 and w else ''}${w:,}"


def picture(path: str, alt: str, link: str | None = None) -> list[str]:
    """A card figure as the Hub shows it: the light or the dark version as the Hub's theme is (Tailwind's dark:
    classes, which the Hub keeps on a card's HTML), and the phone version on a phone (a source the Hub leaves as
    written, so its URL is absolute), each loaded lazily."""
    stem, ext = path.rsplit(".", 1)
    out = []
    for sfx, cls in (("", "dark:hidden"), ("-dark", "hidden dark:block")):
        pic = (f'<picture><source media="{PHONE}" srcset="{DATASET}/resolve/main/{stem}-phone{sfx}.{ext}">'
               f'<img class="{cls}" src="{stem}{sfx}.{ext}" width="{CARD_W}" alt="{escape(alt)}" loading="lazy">'
               "</picture>")
        out.append(f'<a href="{link}">{pic}</a>' if link else pic)
    return out


def film_block(f: dict, s: dict, grades: list[dict]) -> str:
    """The article's film of its lead run as a GIF (scripts/hub_desk_film.py), linking to the run's 3D replay, with the
    article's caption and the run's Episode JSON."""
    x, h = f["lead"], s["hero"]
    g = next(r for r in grades if r["model"] == h["model"] and r["task_id"] == h["task_id"])
    gif = f'<a href="{x["replay"]}"><img src="{FILM}" alt="{escape(x["film_alt"])}" width="100%"></a>'
    return "\n".join([gif, "", f"<small>{x['name']} trades a {x['mw']} battery near {x['region']} through the "
                               f"{x['month']} {x['kind']}. It made {x['P']}, {x['pct']} of the best possible profit; "
                               f"the battery's real operator made {x['op']}. The panel on the right shows each tool "
                               f"call as it happens. [Watch it in 3D]({x['replay']}) · "
                               f"[its Episode JSON]({DATASET}/blob/main/{BENCH_DIR}/{g['episode']})</small>"])


def duel_block(f: dict, duel: dict) -> str:
    """The before and after: the article's three windows where the agents most clearly beat the real operator, as its
    chart draws them, with each run's replay."""
    ws, x = duel["windows"], f["duel"]
    alt = (f"Three windows of the {x['span']} {x['kind']}, one panel each: " + "; ".join(
        f"{w['site']} ({w['region']}, {w['size']}), the real operator, as it ran, settled {dollars(w['op']['p'])}, "
        f"selling {w['op']['sold_mwh']} a day ahead, and {w['agent']['name']} {dollars(w['agent']['p'])}, selling "
        f"{w['agent']['sold_mwh']} a day ahead" for w in ws) + ". Each panel has a 3D still of the run at a moment it "
        "delivers, the node's day-ahead and real-time prices, what each side sold or bought a day ahead hour by hour, "
        "and the battery's charge.")
    links = " · ".join(f"[{w['site']}]({w['replay']})" for w in ws)
    return "\n".join([*picture(f"{FIGS}/before-after.webp", alt), "",
                      "<small>Each panel is one window. Top: the node's day-ahead price, hourly, and its real-time "
                      "price, every 15 minutes. Below, for the real operator as it ran and for the run: what it sold "
                      "(up) or bought (down) a day ahead in each hour, and the battery's charge. The windows: every "
                      f"window in {x['half']} on which at least {x['need']} of the {x['of']} models settled above the "
                      "real operator, both as it ran and with its own bids replayed through the same market; replayed, "
                      f"its own bids earn {x['replays']}. Replay {x['best']}'s runs in 3D: {links}.</small>"])


CONNECT = """Or play it from Python with the Playground's OpenEnv client, after `git clone {space}` and
`pip install ./{name}`:

```python
from gridsim_desk import GridSimDesk

with GridSimDesk(base_url="{base}").sync() as env:
    env.reset(split="bench", index={index})
    print(env.call_tool("get_forecasts", kind="price", market="dam", day="D0"))
    print(env.call_tool("end_turn", response="waiting for the DAM results"))
```"""


def tryit_block(f: dict) -> str:
    """The Playground as it is live on the article's window, linking to it, and its client opening that window."""
    t = f["tryit"]
    alt = (f"The Playground's Try Environment tab on window #{t['index']}, Battery {t['site']} in the {t['span']} "
           f"{t['kind']}: the window picker, the desk's tools, the battery site in 3D, Quick play and the market chart")
    return "\n".join([*picture(f"{FIGS}/try-it.webp", alt, t["space"]), "",
                      f"<small>It opens on window #{t['index']}, Battery {t['site']} in the {t['span']} {t['kind']}, "
                      "the run in the film above. Quick play is three clicks a wake-up (ask the optimizer, submit its "
                      "proposal, end your turn), Autopilot repeats them to the end as the desk's reference does, and "
                      f"every tool also takes raw JSON. [Open the Playground ↗]({t['space']})</small>", "",
                      CONNECT.format(space=t["space"], name=t["space"].rsplit("/", 1)[-1], base=origin(t["app"]),
                                     index=t["index"])])


def origin(url: str) -> str:
    return "/".join(url.split("/")[:3])


def tiles_block(f: dict) -> str:
    """The article's outside figures, two a row: each value, what it is, its comparison and its sources."""
    cells = []
    for t in f["why"]["tiles"]:
        unit = "" if not t["unit"] else t["unit"] if t["unit"].startswith("/") else f" {t['unit']}"
        bars = " · ".join(f"{escape(b['label'])} {escape(b['text'])}" for b in t["bars"])
        src = " · ".join(f'<a href="{x["url"]}">{escape(x["label"])}</a>' for x in t["src"])
        cells.append(f'<td width="50%"><b>{escape(t["value"])}{escape(unit)}</b> {escape(t["desc"])}<br>'
                     f"<small>{bars}<br>{src}</small></td>")
    return "\n".join(["<table>", *(f"<tr>{''.join(cells[i:i + 2])}</tr>" for i in range(0, len(cells), 2)), "</table>"])


def pareto_figure(s: dict, f: dict) -> str:
    """Capture against cost, the article's chart (hub/desk-charts), with its caption and the cost basis."""
    on, point = s["plot"]["frontier"], lambda m: (f"{m['name']} ({pc(m['all']['C']['mean'])}%, "  # noqa: E731
                                                   f"{bench_usd(m['cost']['usd_per_window'])})")
    alt = ("Scatter of hindsight capture C against cost per three-day window on a log scale, the cost frontier a step "
           f"line through {and_join([point(s['models'][k]) for k in on])}; dominated: "
           + and_join([point(m) for m in bench_models(s) if m["key"] not in on and m["n"]]) + ".")
    return "\n".join([*picture(f"{FIGS}/pareto.svg", alt), "",
                      "<small>Each point is a model: its mean capture C over the windows it finished against its mean "
                      "cost a window, on a log scale. The step line is the cost frontier, the models no other model "
                      f"beats on both; each point's 95% CI is in the table below. {f['eval']['basis']}</small>"])


CARD_REFS = {"operator_actual": "The real operator, as it ran", "operator_replay": "The real operator's bids, replayed",
             "anchor": "The desk's planner"}
CARD_BASIS = {"gpu_time": "GPU time", "metered_rate": "metered rate"}


def board_card(s: dict) -> str:
    """Every model and the references, best first: C with its 95% CI over every window and on each side of the training
    cutoffs, and the cost a window, all from summary.json."""
    ms, refs, n, cols = bench_models(s), s["references"], s["n_windows"], ("all", *BENCH_SPLITS)

    def cell(b: dict, bold: bool) -> str:
        v = f"{pc(b['mean'])}%"
        return f"{f'**{v}**' if bold else v}<br><small>[{pc(b['ci'][0])}, {pc(b['ci'][1])}]</small>"

    def cost(m: dict) -> str:
        c = m["cost"]
        return (f"{bench_usd(c['usd_per_window'])}<br><small>"
                + (f"{CARD_BASIS[c['basis']]} · " if c["basis"] in CARD_BASIS else "")
                + f"{bench_usd(c['usd_all_attempts'])} in all</small>")

    rows = [f"| **{m['name']}**<br><small>{m['harness']} · {m['setting']}"
            + ("" if m["n"] == n else f" · {m['n']} of {n} windows") + "</small> | "
            + " | ".join(cell(m[c]["C"], c == "all") for c in cols) + f" | {cost(m)} |" for m in ms if m["n"]]
    rows += [f"| *{label}* | " + " | ".join(f"*{pc(refs[k][c]['C']['mean'])}%*" for c in cols) + " | – |"
             for k, label in CARD_REFS.items()]
    head = [f"C, all {n} windows", *(f"{bench_side(s, x)}<br><small>{BENCH_SIDE[x]}</small>" for x in BENCH_SPLITS)]
    none = [m["name"] for m in ms if not m.get("cutoff")]
    gaps = {m["name"]: g["ci"] for m in ms if m["n"] and (g := bench_pair(s, m["key"], "operator_replay"))}
    ahead, behind = ([k for k, c in gaps.items() if c[0] > 0], [k for k, c in gaps.items() if c[1] < 0])
    return "\n".join([
        "| Model | " + " | ".join(head) + " | $ a window |", "|---|" + "---:|" * (len(cols) + 1), *rows, "",
        f"<small>C, hindsight capture, %. Brackets: 95% CIs, a block bootstrap over the {s['n_fronts']} weather "
        "fronts, four on each side of the cutoffs."
        + (f" No training cutoff is reported for {and_join(none)}." if none else "")
        + " $ a window: the graded attempt's tokens at the model maker's list price, or as the chart's note says; in "
        "all: every attempt, retries and stalls included. How each model ran is under How the benchmark ran, "
        "below.</small>", "",
        "**Against the real operator,** paired by window with its own bids replayed, the 95% CI on the gap is above "
        f"zero for {and_join(ahead) if ahead else 'no model'}"
        + (f", and below zero for {and_join(behind)}." if behind else ".")])


def rollout_block(f: dict) -> str:
    """The Replays Space as it is live at the minute the article's rollout opens on, linking there."""
    w = f["eval"]["watch"]
    alt = (f"The Replays Space at {w['at']} on {w['day']}: {w['name']}'s run at Battery {w['site']} ({w['region']}) "
           f"over {w['span']}, the battery site in 3D at night beside the node's prices, the battery's charge and the "
           "statement settled so far")
    return "\n".join([*picture(f"{FIGS}/rollout.webp", alt, w["app"]), "",
                      f"<small>At {w['at']} on {w['day']} in the bench's costliest run, {w['name']} at Battery "
                      f"{w['site']} ({w['region']}) over {w['span']}, the front after the film's: its evening "
                      "day-ahead sales met an all but empty battery and were bought back as real-time prices hit "
                      f"{w['spike']}. It lost {w['lost']}; the real operator made {w['op']}. [Open it in Replays "
                      f"↗]({w['app']}), or pick any model and window under Episodes.</small>"])


def reward_figure(f: dict, r: dict) -> str:
    """Every run on the film's window between idle and hindsight, the article's chart."""
    x, refs = f["reward"], r["refs"]
    alt = (f"Every model's settled P on the film's window, Battery {x['site']}, on the scale from idle "
           f"({dollars(refs['p_idle'])}) to hindsight ({dollars(refs['p_hind'])}), with the desk's planner at "
           f"{dollars(refs['p_anchor'])} and the real operator at {dollars(refs['p_operator_actual'])} as it ran and "
           f"{dollars(refs['p_operator_replay'])} with its bids replayed: " + "; ".join(
               f"{q['name']} C {pc(q['c'])}%, {dollars(q['p'])}, R {q['r']:.2f}" for q in r["runs"])
           + ". Below, R along the same scale: 0.2 at idle, rising to 1 at the planner and staying there above it.")
    return "\n".join([*picture(f"{FIGS}/reward.png", alt), "",
                      f"<small>Every model's settled P on the film's window, Battery {x['site']}, on the scale from "
                      "idle (C 0%) to hindsight (C 100%), with the desk's planner and the real operator marked; the "
                      "strip below draws R along the same scale.</small>"])


def train_figure(f: dict, t: dict) -> str:
    """The distilled model against its base on every benchmark window, the article's chart."""
    x = f["train"]
    alt = (f"{x['base_name']}, before and after fine-tuning on the planner: C on each of the {x['n']} benchmark "
           f"windows, paired, from the largest gain to the largest loss. Means: {x['base']} before, {x['sft']} after, "
           f"the planner {x['planner']}, {t['names']['lead']} {x['sol']}; better on {x['better']} of {x['n']} windows.")
    return "\n".join([*picture(f"{FIGS}/training.png", alt), "",
                      f"<small>Each row is a benchmark window: {x['base_name']}'s C (grey) and the fine-tuned model's "
                      "(blue), with the planner's C on that window as a tick. Rows run from the largest gain to the "
                      "largest loss.</small>"])


FAIL = (("end", "Do they keep trading to the end?", "last_offer_h"),
        ("live", "Do their real-time offers stay live?", "rt_live"),
        ("refused", "Does the desk accept their offers?", "refused"))
"""The article's three failure charts, in its order: each one's key, its question, and the metric it ranks by."""


def fail_block(fm: dict) -> str:
    """Where models fail: the article's three charts with every model shown, each under its question, from the exact
    replay of every graded episode (failures.json)."""
    ms = fm["models"]
    share = lambda v: f"{(Decimal(str(v)) * 100).quantize(Decimal(1), ROUND_HALF_UP)}%"  # noqa: E731
    rho = f"{fm['corr']['last_offer_vs_C_models']:.2f}".replace("-", "−")
    alts = {
        "end": "Hours between each model's last accepted offer and the window's end, the mean over its windows: "
               + "; ".join(f"{m['name']} {m['last_offer_h']:.1f} h"
                           for m in sorted(ms, key=lambda m: m["last_offer_h"])),
        "live": "How each model's 5-minute real-time intervals settled, on its live real-time curve, its day-ahead "
                f"curve or a proxy: the desk's planner {share(fm['anchor']['rt_live'])}, "
                f"{share(fm['anchor']['rt_dam'])}, {share(fm['anchor']['rt_proxy'])}; " + "; ".join(
                    f"{m['name']} {share(m['rt_live'])}, {share(m['rt_dam'])}, {share(m['rt_proxy'])}"
                    for m in sorted(ms, key=lambda m: -m["rt_live"])),
        "refused": "The share of each model's submits the desk refused: " + "; ".join(
            f"{m['name']} {share(m['refused'])}" for m in sorted(ms, key=lambda m: m["refused"]))}
    how = {"end": "Hours between each model's last accepted offer and the window's end, the mean over its windows. The "
                  "more hours a model leaves its last offer standing, the lower it scores: a rank correlation of "
                  f"{rho} across the models.",
           "live": "Each bar splits a model's 5-minute real-time intervals by what they settled on: its own live "
                   "real-time curve, its day-ahead curve carried over, or a proxy. The desk's planner is the reference "
                   "row.",
           "refused": "The share of each model's submits the desk refused, for breaking its rules or arriving after a "
                      "gate."}
    out = []
    for key, question, _ in FAIL:
        out += [f"**{question}**", "", *picture(f"{FIGS}/fail-{key}.png", alts[key] + "."), "",
                f"<small>{how[key]}</small>", ""]
    return "\n".join([*out, "<small>Means over each model's graded windows, from an exact replay of every episode. "
                            "[The article](https://huggingface.co/spaces/earakely-scale/GridSimEnv) highlights one "
                            "model at a time, with its profile.</small>"])


LOAD = """```python
from datasets import load_dataset

repo = "earakely-scale/GridSimEnv-AgentEnv"
bench = load_dataset(repo, "desk_v4_bench", split="post_cutoff")  # the benchmark, each model's every window
board = load_dataset(repo, "desk_leaderboard", split="{latest}")  # each model and reference, with CIs
runs = load_dataset(repo, "desk_runs", split="{latest}")          # each model's every task
tasks = load_dataset(repo, "desk_tasks", split="{latest}")        # every task, its site card and references
```"""
BENCH_COLUMNS = (
    ("The model", "`model`, `name`, `family`, `model_id`, `harness`, `harness_version`, `setting`, `weights`",
     ("model", "name", "family", "model_id", "harness", "harness_version", "setting", "weights")),
    ("The window", "`pack`, `task_id`, `split` (`pre_cutoff` or `post_cutoff`), `front`, `front_kind`, `site` (S01 to "
     "S04), `region`, `battery`, `dates`",
     ("pack", "task_id", "split", "front", "front_kind", "site", "region", "battery", "dates")),
    ("Whether it finished", "`status` (`scored` or `missing`), `missing_reason`, `attempts`, `retries`, `valid`",
     ("status", "missing_reason", "attempts", "retries", "valid")),
    ("The grade", "`capture` (C), `capture_phys`, `reward` (R), `p_usd` (P, the settled statement), `floored`, "
     "`beats_anchor`", ("capture", "capture_phys", "reward", "p_usd", "floored", "beats_anchor")),
    ("The references", "`p_idle`, `p_anchor` (the planner), `p_hind`, `p_hind_phys`, `p_operator_replay`, "
     "`p_operator_actual`, `capture_operator_replay`",
     ("p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay", "p_operator_actual",
      "capture_operator_replay")),
    ("How it traded", "`turns`, `wakes`, `desk_calls`, `own_tool_calls`, `shell_calls`, `reminders`, `submissions`, "
     "`rejected`",
     ("turns", "wakes", "desk_calls", "own_tool_calls", "shell_calls", "reminders", "submissions", "rejected")),
    ("Usage and cost", "`input_tokens`, `cached_tokens`, `cache_write_tokens`, `output_tokens`, `reasoning_tokens`, "
     "`usd` (the graded attempt), `usd_all_attempts`, `cost_basis`, `wall_seconds`",
     ("input_tokens", "cached_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens", "usd",
      "usd_all_attempts", "cost_basis", "wall_seconds")),
    ("The record", "`episode`, the path of its Episode JSON in this dataset", ("episode",)))
"""The default config's columns by what they tell, every column of hub_desk.BENCH once."""


def inside_card(d: dict, bench: tuple[dict, list[dict]]) -> str:
    """The configs, how to load them, the folders, and the default config's columns."""
    names = module("hub_desk", "scripts/hub_desk.py").BENCH.names
    listed = [c for _, _, cs in BENCH_COLUMNS for c in cs]
    if sorted(listed) != sorted(names):
        raise SystemExit(f"BENCH_COLUMNS lists {sorted(set(listed) ^ set(names))} unlike hub_desk.BENCH")
    return "\n".join([inside(d, bench), "", LOAD.replace("{latest}", ladder(d)[-1]["version"]), "",
                      "<details>", "<summary><b>The columns of <code>desk_v4_bench</code></b>, one row per model and "
                      "window</summary>", "", "| What | Columns |", "|---|---|",
                      *(f"| {g} | {text} |" for g, text, _ in BENCH_COLUMNS),
                      "", "</details>"])


def how_card(s: dict) -> str:
    """How the benchmark ran: the harnesses and where each model was served, the settings, the closed network and the
    budget, how to reproduce it, what it cost, how reliably it ran and each model's run notes."""
    ms, run = bench_models(s), s["run"]
    by, served, settings = {}, {}, {}
    for m in ms:
        by.setdefault((m["harness"], m["harness_version"], m.get("harness_note")), []).append(m["name"])
        settings.setdefault(m["setting"], []).append(m["name"])
        if m.get("server"):
            where = m["server"] + ("" if m.get("endpoint") == m["server"] else f" through {m['endpoint']}"
                                   if m.get("endpoint") else f" on {m['cost']['gpu']['where']}")
            served.setdefault(where, []).append(m["name"] if m["name"].startswith(m["provider"])
                                                else f"{m['provider']}'s {m['name']}")
    paid = sorted((m for m in ms if m["cost"]["usd_per_window"] is not None), key=lambda m: m["cost"]["usd_per_window"])
    notes = [f"{m['name']} ran" + (f" through {m['endpoint']}," if m.get("endpoint") else "")
             + f" on agentenv-framework {m['framework']}" + (f"; {m['note']}" if m.get("note") else "") + "."
             for m in ms if m.get("framework")]
    gpu = [f"{m['name']}'s cost is {m['cost']['gpu']['note']}." for m in ms if m["cost"].get("gpu")]
    return "\n".join(f"- {x}" for x in [
        "**Each model in its own agent harness,** through AgentEnv: " + "; ".join(
            f"{and_join(xs)} in {h}" + (f" {v}" if v else "") + (f" {note}" if note else "")
            for (h, v, note), xs in by.items()) + "."
        + (" Served by " + "; by ".join(f"{w}: {and_join(xs)}" for w, xs in served.items()) + "." if served else ""),
        "**Settings:** " + "; ".join(f"{k} for {and_join(xs)}" for k, xs in settings.items()) + ".",
        *bench_how(s)[2:4],
        "**Reproducible with `agent-env run`:** every episode is a plain run of the bench bundle"
        + (f" (`{run['bundle']}`)" if run.get("bundle") else "") + " and a config.toml"
        + (f", on agentenv-framework {run['framework']}" if run.get("framework") else "")
        + ("; these ran on EC2 boxes with local Docker rather than in the Modal sandboxes the bundle was designed for, "
           "a deviation logged with the others" if run.get("route") == "ec2" else "")
        + ". Run it yourself, below, shows how."
        + (f" Pre-registered in [{run['prereg']}]({REPO}/blob/{run.get('bundle') or 'main'}/{run['prereg']})."
           if run.get("prereg") else ""),
        f"**Cost a window** runs from {bench_usd(paid[0]['cost']['usd_per_window'])} ({paid[0]['name']}) to "
        f"{bench_usd(paid[-1]['cost']['usd_per_window'])} ({paid[-1]['name']}): the graded attempt's tokens in its "
        "harness's own trajectory at the model maker's list price; the table above also gives every attempt's."
        + "".join(f" {x}" for x in gpu) + (f" {s['text']['metered']}" if s["text"].get("metered") else "")
        + "".join(f" {m['price_note']}" for m in ms if m.get("price_note")),
        *([f"**Valid submissions.** {s['text']['valid']}"] if s["text"].get("valid") else []),
        f"**Reliability:** {s['text']['reliability']}",
        "**Run notes.** " + " ".join(notes),
        f"Every number is in [`{BENCH_DIR}`]({DATASET}/tree/main/{BENCH_DIR}) (its README, `summary.json`, "
        "`grades.jsonl.gz` and every scored Episode JSON) and in the `desk_v4_bench` config."])


DESK_LIMITS = (
    "**DAM credit screening is not modelled.** ERCOT screens a QSE's day-ahead bids and offers against its available "
    "credit; here, day-ahead positions are bounded only by the battery's MW limits. That favours large DAM/RT spread "
    "positions, and the days where those paid carry most of v2's and v4's dollars.",
    "**K1 in v3 to v5 too.** The earlier versions' reserve figures leave the calls with the spurious ASO-02 note out "
    "of the refused offers.",
    "**Modelled lines.** The co-located solar profile, degradation, warranty overage, the end-of-day energy charge and "
    "the capacity-short charge are modelled and marked as such; so is the desk's own price forecast, built only from "
    "data public at the time.",
    "**One battery is a price taker.** In v2 to v4 and the benchmark the desk clears at the real prices; the v5 "
    "price-impact check re-clears the DAM with the desk's own offers and shows that a 100–150 MW battery moves the "
    "day-ahead price by cents.",
    "**Small packs in v2 to v5.** 16 to 32 tasks per version over four to eight blocks, so the CIs are wide; the v5 "
    "check repeats v3's battery-days, and the gaps between the two runs are the scale of that noise.",
    "**Next:** a fleet desk, a QSE bidding a portfolio of batteries into the DAM at once, where price impact can "
    "matter; and more runs per task, to separate skill from run-to-run noise.")


def limits_card(s: dict) -> str:
    return "\n".join(f"- {x}" for x in [*bench_limits(s), *DESK_LIMITS])


def deviations_card(s: dict) -> str:
    """Each deviation by its first sentence; the pre-registration gives each in full."""
    link, first = bench_deviations(s), [re.split(r"(?<=\.)\s+(?=[A-Z])", x, maxsplit=1)[0] for x in s["deviations"]]
    return "\n".join([*(f"- {x}" for x in first), *(
        ["", f"The pre-registration gives each in full: [{s['run']['prereg']}#deviations]({link})."] if link else [])])


RUN = """In process, with no Docker and no model key, play the desk's planner on v2's two pilot battery-days:

```bash
git clone https://github.com/earakely-scale/agentenv-gridsim-plugin
cd agentenv-gridsim-plugin && uv sync --extra dev
uv run python scripts/desk_run.py --pack desk-v2-pilot --policy anchor --out runs/anchor
```

Each run writes every task's Episode JSON and a results row with its grade. `--policy model --model NAME --base-url URL`
plays any model behind an OpenAI-compatible endpoint the same way, with its key in `DESK_API_KEY`, and every version's
packs are under `data/desk/`. On AgentEnv, after `agent-env gridsim setup`, `scripts/desk_e2e.py` plays a task through
the gateway env, its post-turn hook and its verifier, and checks it against the in-process run byte for byte."""


def run_card(s: dict) -> str:
    keys = and_join([f"`{m['harness_key']}`" for m in bench_models(s)]).replace(" and ", " or ")
    return "\n\n".join([RUN, BENCH_QUICKSTART.replace("{deviations}", bench_deviations(s)).replace("{harnesses}",
                                                                                                   keys)])


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


BENCH_DIR = "results/desk-v4-bench"
BENCH_SPLITS = ("pre_cutoff", "post_cutoff")
BENCH_SIDE = {"pre_cutoff": "may be in training data", "post_cutoff": "after every reported cutoff"}
BENCH_REFS = {"operator_replay": "The real operator's bids, replayed", "anchor": "The anchor, the desk's own optimiser"}
BENCH_BASIS = {"gpu_time": ", GPU time", "metered_rate": ", no maker price: metered rate"}
BENCH_WHEN = {"pre_cutoff": "a window that may be in the models' training data",
              "post_cutoff": "after every reported training cutoff"}
FAKE = ("> **FAKE DATA PREVIEW.** Every benchmark number, chart and row on this page was synthesized from the pilot "
        "records to exercise the pipeline. No benchmark run is behind any of them.")


def bench_read(folder: Path) -> tuple[dict, list[dict]] | None:
    """The v4 benchmark's summary.json and grades rows (scripts/desk_bench_results.py): the card's benchmark section
    reads nothing else."""
    if not (folder / "summary.json").is_file():
        return None
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        return json.loads((folder / "summary.json").read_text()), [json.loads(x) for x in f if x.strip()]


def bench_models(s: dict) -> list[dict]:
    """The models by C over every window, highest first; a model with no finished window last."""
    return [s["models"][k] for k in s["order_by_C"]] + [m for k, m in s["models"].items() if k not in s["order_by_C"]]


def bench_side(s: dict, split: str) -> str:
    """A split's months: 'Jan–May 2026'."""
    fr = sorted(f["front"] for f in s["fronts"] if f["split"] == split)
    a, b = date.fromisoformat(fr[0]), date.fromisoformat(fr[-1]) + timedelta(days=2)
    return f"{a:%b %Y}" if (a.year, a.month) == (b.year, b.month) else f"{a:%b}–{b:%b %Y}"


def bench_pair(s: dict, a: str, b: str, scope: str = "all") -> dict | None:
    """The paired gap a − b in C over the windows both finished."""
    if x := s["paired"].get(f"{a}-{b}"):
        return x[scope]["C"]
    if x := s["paired"].get(f"{b}-{a}"):
        c = x[scope]["C"]
        return c | {"mean": -c["mean"], "ci": [-c["ci"][1], -c["ci"][0]]} if c["mean"] is not None else c
    return None


def pts_ci(b: dict, sign: bool = False) -> str:
    """A C gap in points with its CI: '+4.7 pts [−2.4, +11.9]'."""
    return f"{pc(b['mean'], 1, sign)} pts [{pc(b['ci'][0], 1, sign)}, {pc(b['ci'][1], 1, sign)}]"


def bench_usd(x: float) -> str:
    return f"${x:,.2f}" if x < 100 else f"${x:,.0f}"


def bench_pitch(s: dict) -> str:
    ms = list(s["models"].values())
    n, opened = len(ms), {}
    for m in (m for m in ms if m["weights"] == "open"):
        opened.setdefault(m["harness"], []).append(m["name"].replace("-", "-\u2060"))
    used = [*dict.fromkeys(m["harness"] for m in ms if m["weights"] != "open"),
            *(f"{h} for the open {and_join(names)}" for h, names in opened.items())]
    harnesses = used[0] if len(used) == 1 else f"{', '.join(used[:-1])}, and {used[-1]}"
    return "\n\n".join([f"**{NUM.get(n, n)} models in native agent harnesses ({harnesses}) run a real ERCOT battery's "
                        f"trading desk for three days at a time across {s['n_fronts']} real Texas weather fronts, "
                        "graded in dollars against the hindsight optimum and the battery's real operator.**",
                        *([FAKE] if s["fake"] else [])])


def bench_replay(model: str, task: str) -> str:
    return f"{APP}/index.html?v=bench&m={model}&task={task}"


def bench_deviations(s: dict) -> str | None:
    run = s["run"]
    return f"{REPO}/blob/{run['deviations_ref']}/{run['prereg']}#deviations" if run.get("prereg") and run.get(
        "deviations_ref") else None


def bench_block(s: dict, grades: list[dict], d: dict) -> str:
    """The v4 benchmark: capture either side of the training cutoffs, the headline; the table (C with CIs over every
    window and on each side of the cutoffs, cost a window); what the numbers say, how it runs and its limitations;
    every number from results/desk-v4-bench/summary.json."""
    ms, refs, charts = bench_models(s), s["references"], d["charts"]
    none = [m["name"] for m in ms if not m.get("cutoff")]
    cols = ["all", *BENCH_SPLITS] if s["lead_split"] == "all" else ["post_cutoff", "all", "pre_cutoff"]
    head = {"all": f"C, all {s['n_windows']} windows",
            **{x: f"{bench_side(s, x)}<br><small>{BENCH_SIDE[x]}</small>" for x in BENCH_SPLITS}}

    def cell(b: dict, bold: bool) -> str:
        if b["mean"] is None:
            return "–"
        v = f"{pc(b['mean'])}%"
        return f"{f'**{v}**' if bold else v}<br><small>[{pc(b['ci'][0])}, {pc(b['ci'][1])}]</small>"

    def who(m: dict) -> str:
        c, n = m["cost"], m["n"]
        cost = [] if c["usd_per_window"] is None else [
            f"{bench_usd(c['usd_per_window'])} a window" + BENCH_BASIS.get(c["basis"], ""),
            f"{bench_usd(c['usd_all_attempts'])} in all"]
        return (f"**{m['name']}**<br><small>{m['harness']} · {m['setting']}<br>"
                + (f"{m['distilled_short']}<br>" if m.get("distilled_short") else "")
                + " · ".join(cost + ([] if n == s["n_windows"] else [f"{n} of {s['n_windows']} windows"]))
                + "</small>")

    rows = [f"| {who(m)} | " + " | ".join(cell(m[c]["C"], c == cols[0]) for c in cols) + " |" for m in ms]
    rows += [f"| *{BENCH_REFS[k]}* | " + " | ".join(f"*{pc(refs[k][c]['C']['mean'])}%*" for c in cols) + " |"
             for k in BENCH_REFS]
    gpu = [m for m in ms if m["cost"].get("gpu")]
    op = refs["operator_replay"]
    alt = ("Line chart of hindsight capture C, as a percentage of the hindsight optimum's profit over idle, before and "
           "after the training cutoffs, one line per model: " + "; ".join(
               f"{m['name']} in {m['harness']} {pc(m['pre_cutoff']['C']['mean'])}% then "
               f"{pc(m['post_cutoff']['C']['mean'])}%" for m in ms if m["n"])
           + f"; the real operator's bids, replayed, {pc(op['pre_cutoff']['C']['mean'])}% then "
           f"{pc(op['post_cutoff']['C']['mean'])}%.")
    sides = " and ".join(f"{bench_side(s, x)} ({BENCH_SIDE[x]})" for x in BENCH_SPLITS)
    notes = [f"{m['name']} ran" + (" after the others," if all(m["ran"]["from"] > x["ran"]["to"] for x in ms
                                                              if x is not m) else "")
             + (f" through {m['endpoint']}," if m.get("endpoint") else "") + f" on agentenv-framework {m['framework']}"
             + (f"; {m['note']}" if m.get("note") else "") + "." for m in ms if m.get("framework")]
    notes += [m["price_note"] for m in ms if m.get("price_note")]
    if notes and bench_deviations(s):
        notes.append(f"See the [deviations]({bench_deviations(s)}).")
    return "\n".join([
        *chart("splits", alt, charts["lead"], charts["phone"]["media"], f"{BENCH_DIR}/figures"), "",
        "<small>C × 100: the share of the hindsight optimum's profit over idle that each model captured, its mean over "
        f"the windows it finished on each side of the models' reported training cutoffs, {sides}"
        + (f"; none is reported for {and_join(none)}" if none else "")
        + f"; 95% CIs, a block bootstrap over the {s['n_fronts']} fronts, are in the table below. Grey dashed: the "
        "real operator's own bids, replayed through the same clearing and settlement.</small>",
        "", "| Model | " + " | ".join(head[c] for c in cols) + " |", "|---|" + "---:|" * len(cols), *rows, "",
        f"<small>C, hindsight capture, %. Brackets: 95% CIs, a block bootstrap over the {s['n_fronts']} weather fronts "
        "(four within each side of the cutoffs). Cost a window: the graded attempt's tokens in its harness's own "
        "trajectory at the model maker's list price"
        + "".join(f"; {m['name']}'s is {m['cost']['gpu']['note']}" for m in gpu)
        + "; in all: every attempt, retries and stalls included." + (f" {s['text']['metered']}" if s[
            "text"].get("metered") else "") + " The "
        "anchor is the desk's own optimiser re-planning at every wake on the same information; the operator row "
        "replays the real operator's bids, disclosed by ERCOT 60 days later, through the same clearing and "
        "settlement." + "".join(f" {x}" for x in notes) + "</small>", "",
        *pareto_block(s, charts), "",
        *(x for d in s.get("deferred") or [] for x in (md(d), "")),
        *(f"- {x}" for x in bench_bullets(s)), "",
        "### How it runs", "", *(f"- {x}" for x in bench_how(s)), "",
        "### Known limitations of the benchmark", "", *(f"- {x}" for x in bench_limits(s)), "",
        *(["### Deviations from the pre-registration", "", *(f"- {x}" for x in s["deviations"]), "",
           *([f"The pre-registration lists its deviations at its end: [{s['run']['prereg']}#deviations]"
              f"({bench_deviations(s)}).", ""] if bench_deviations(s) else [])]
          if s.get("deviations") else []),
        f"Every number is in [`{BENCH_DIR}`]({DATASET}/tree/main/{BENCH_DIR}) (its README, `summary.json`, "
        "`grades.jsonl.gz` and every scored Episode JSON) and in the `desk_v4_bench` config, one row per model and "
        "window, split `pre_cutoff` and `post_cutoff`."])


def pareto_block(s: dict, charts: dict) -> list[str]:
    """Cost against C, the cost frontier as a step line, and its caption: which models make the frontier, the cost
    bases that differ from the makers' list price, and what the distilled model is."""
    if not s["plot"].get("frontier"):
        return []
    ms = bench_models(s)
    on = [s["models"][k] for k in s["plot"]["frontier"]]
    point = lambda m: f"{m['name']} ({pc(m['all']['C']['mean'])}%, {bench_usd(m['cost']['usd_per_window'])})"  # noqa: E731
    off = [point(m) for m in ms if m["key"] not in s["plot"]["frontier"] and m["n"]]
    alt = ("Scatter of hindsight capture C against cost per three-day window on a log scale, the cost frontier a step "
           f"line through {and_join([point(m) for m in on])}" + (f"; dominated: {and_join(off)}" if off else "") + ".")
    gpu = [m["name"] for m in ms if m["cost"]["basis"] == "gpu_time"]
    sft = any(m.get("distilled") for m in ms)
    return [*chart("pareto", alt, charts["lead"], charts["phone"]["media"], f"{BENCH_DIR}/figures"), "",
            "<small>Each point is a model's mean C over its scored windows against its mean cost a window, on a log "
            "scale: the model maker's list price for its tokens" + (f", or GPU time for {and_join(gpu)}" if gpu else "")
            + ". The step line is the cost frontier, the models no other model beats on both; the chart's notes give "
            "each cost's basis" + (" and what the distilled model is" if sft else "") + ".</small>"]


def bench_bullets(s: dict) -> list[str]:
    ms, op = bench_models(s), s["references"]["operator_replay"]
    ranked = [m for m in ms if m["n"]]
    if not ranked:
        return []
    top, out = ranked[0], []
    lead = [(m, g) for m in ranked[1:2] if (g := bench_pair(s, top["key"], m["key"]))]
    out.append(f"**{top['name']} captures the most of hindsight:** C {pc(top['all']['C']['mean'])}% "
               f"[{pc(top['all']['C']['ci'][0])}, {pc(top['all']['C']['ci'][1])}] over its {top['n']} windows, at "
               f"{bench_usd(top['cost']['usd_per_window'])} a window." + "".join(
                   f" Paired by window, its lead over {m['name']}: {pts_ci(g, True)}"
                   + (", a CI that includes zero." if g["ci"][0] <= 0 <= g["ci"][1] else ".") for m, g in lead))
    ahead = [m["name"] for m in ranked if (g := bench_pair(s, m["key"], "operator_replay")) and g["ci"][0] > 0]
    behind = [m["name"] for m in ranked if (g := bench_pair(s, m["key"], "operator_replay")) and g["ci"][1] < 0]
    out.append(f"**Against the real operator:** its own bids, replayed through the same clearing and settlement, "
               f"capture {pc(op['all']['C']['mean'])}%. Ahead of them paired by window, with a CI above zero: "
               + (and_join(ahead) if ahead else "no model") + "."
               + (f" Behind, with a CI below zero: {and_join(behind)}." if behind else ""))
    out.append(f"**Before and after the cutoffs:** {s['text']['halves']}")
    paid = sorted((m for m in ranked if m["cost"]["usd_per_window"] is not None),
                  key=lambda m: m["cost"]["usd_per_window"])
    if s["text"].get("frontier"):
        out.append(f"**Cost against score:** {s['text']['frontier']}")
    for m in (m for m in ranked if m.get("distilled") and m.get("family") in s["models"]):
        base, ref = s["models"][m["family"]], s["references"]["anchor"]["all"]["C"]["mean"]
        g = bench_pair(s, m["key"], base["key"])
        out.append(f"**{m['name']} reproduces the desk's own planner.** It is {m['distilled']} The planner captures "
                   f"{pc(ref)}% on these windows and {m['name']} {pc(m['all']['C']['mean'])}%"
                   + (f"; over base {base['name']}, served differently, {pts_ci(g, True)}" if g else "")
                   + (f", {m['primary']}" if m.get("primary") else "") + ".")
    out.append(f"**Cost a window** runs from {bench_usd(paid[0]['cost']['usd_per_window'])} ({paid[0]['name']}) to "
               f"{bench_usd(paid[-1]['cost']['usd_per_window'])} ({paid[-1]['name']}); every attempt, retries "
               "included, cost " + and_join([f"{bench_usd(m['cost']['usd_all_attempts'])} for {m['name']}"
                                             for m in ms]) + ".")
    if s["text"]["valid"]:
        out.append(f"**Valid submissions.** {s['text']['valid']}")
    out.append(f"**Reliability:** {s['text']['reliability']}")
    return out


def bench_how(s: dict) -> list[str]:
    ms, run = bench_models(s), s["run"]
    ec2, by = run.get("route") == "ec2", {}
    for m in ms:
        by.setdefault((m["harness"], m["harness_version"], m.get("harness_note")), []).append(m)
    harnesses = "; ".join(f"{and_join([m['name'] for m in xs])} in {h}" + (f" {v}" if v else "")
                          + (f" {note}" if note else "") for (h, v, note), xs in by.items())
    opened = {}
    for m in (m for m in ms if m["weights"] == "open"):
        opened.setdefault(f"served by {m['server']}" + ("" if m.get("endpoint") == m["server"] else
                                                       f" through {m['endpoint']}" if m.get("endpoint") else
                                                       f" on {m['cost']['gpu']['where']}"), []).append(
            m["name"] if m["name"].startswith(m["provider"]) else f"{m['provider']}'s {m['name']}")
    budget, ref = run.get("budget") or {}, run.get("bundle") or "main"
    return [
        f"**Each model in a native agent harness,** through AgentEnv: {harnesses}."
        + (f" The open-weight models: {'; '.join(f'{and_join(xs)}, {how}' for how, xs in opened.items())}."
           if opened else ""),
        "**At high effort:** " + "; ".join(f"{m['name']} {m['setting']}" for m in ms) + ".",
        ("**No internet.** Each run's Docker network is closed to the internet by a host rule, and the model is "
         "reached only through a proxy on the host that allows one API and one model per run and refuses provider-side "
         "web, code-execution and remote-MCP tools; the agents hold only a placeholder key, which the proxy replaces. "
         "Web search and fetch are also off in each harness's own settings; checked from inside the agent containers "
         "before the runs." if ec2 else
         "**No internet.** Each agent's sandbox allows only its model's API host (and the sandbox platform's tunnel to "
         "the env), and web search and fetch are off in each harness's own settings; checked from inside the "
         "sandboxes before the runs."),
        "**The desk's 11 tools over MCP,** beside the harness's own shell, files and planning tools"
        + (f"; v4's budget of {budget.get('max_turns')} turns, {budget.get('calls_per_turn')} desk calls a turn and "
           f"{budget.get('max_reminders')} reminders" if budget else "") + ". One run per model per window.",
        "**Reproducible with `agent-env run`:** every episode is a plain run of the bench bundle"
        + (f" (`{run['bundle']}`)" if run.get("bundle") else "") + " and a config.toml"
        + (f", on agentenv-framework {run['framework']}" if run.get("framework") else "")
        + ("; these ran on EC2 boxes with local Docker rather than in the Modal sandboxes the bundle was designed for, "
           "a deviation logged below" if ec2 else "") + ". The Quick start below shows how."
        + (f" Pre-registered in [{run['prereg']}]({REPO}/blob/{ref}/{run['prereg']})." if run.get("prereg") else "")]


def tier_note(s: dict) -> str:
    """The long-prompt rates as applied: call by call, where a maker prices a longer prompt higher."""
    ts = [(m["name"], m["cost"]["tier"]) for m in s["models"].values() if m["cost"].get("tier")]
    if not any(t["calls"] for _, t in ts):
        return " or long-context surcharges"
    return "; a maker's higher rate for a long prompt applies call by call, " + and_join(
        [f"{name}'s above {t['above'] // 1000}K tokens to {t['calls']:,} of its calls" for name, t in ts if t["calls"]])


def bench_limits(s: dict) -> list[str]:
    """The benchmark's known limitations, as the pre-registration discloses them for the route the runs took."""
    harnesses = {m["harness"] for m in s["models"].values()}
    gpu = [m["name"] for m in s["models"].values() if m["cost"].get("gpu")]
    none = [m for m in s["models"].values() if not m.get("cutoff")]
    rel, day = sorted(m["released"] for m in none if m.get("released")), {"days_per_task": 1}
    late = [short({"days_per_task": int(f["dates"][-2:]) - int(f["front"][-2:]) + 1}, f["front"]) for f in s["fronts"]
            if rel and f["split"] == "post_cutoff" and f["front"] > rel[-1]]
    return [
        "**The env's control endpoints are not authenticated** in this framework release, and an agent's shell can "
        "reach the env through its tunnel; no pilot showed an attempt to use them, and the runs are not audited for "
        "it.",
        *([] if s["run"].get("route") == "ec2" else
          ["**The model key is in the agent's sandbox,** so an agent could call another model with it."]),
        "**Model plus harness.** Each harness's own prompts, tools and context handling are part of what is measured; "
        "the harness versions are the ones the framework release pins."
        + (" Gemini CLI drops a thought signature when it resumes a session, which costs it prompt-cache hits and "
           "raises its cost, a known harness issue." if "Gemini CLI" in harnesses else ""),
        "**The training cutoffs are third-party reports, unconfirmed.**"
        + (f" None is reported for {and_join([m['name'] for m in none])}" + (
            f", reportedly released {short(day, rel[0])}–{short(day, rel[-1])} {rel[-1][:4]}, so "
            + (f"only the {and_join(late)} fronts certainly post-date " if late else "no front certainly post-dates ")
            + ("it" if len(none) == 1 else f"all {NUM.get(len(none), len(none)).lower()}") if rel else
            ", so the Jul–Aug windows are not known to be after their cutoffs") + "." if none else "")
        + " The pre-cutoff half reuses v4's 16 windows, which GPT-6.1 Sol, GPT-6 Luna and Qwen3-4B also played on the "
        "desk's own runner (below).",
        "**One run per model per window over eight fronts,** so the CIs are wide, and a single scarcity front can "
        "carry a model's dollars.",
        "**Cost is the model maker's list price:** tokens at each maker's public price per million, without batch "
        "or volume discounts" + tier_note(s) + (f"; {and_join(gpu)}'s cost is its share of the GPU time" if gpu else "")
        + "."
        + "".join(f" {m['price_note']}" for m in s["models"].values() if m.get("price_note")),
        *bench_distilled_limits(s),
        "**A known env defect, K1, in the benchmark too.** An empty reserve-offer list drew a spurious ASO-02 note "
        "while the energy curves in the same call were accepted and applied; there is no settlement effect. It is "
        "fixed on the head; the frozen runs keep it, and the benchmark plays v4's freeze."]


def bench_distilled_limits(s: dict) -> list[str]:
    """A distilled row's limits: it is served apart from its base, and the training data's spans against these
    windows (the desk-distill pre-registration's check)."""
    out = []
    for m in (m for m in s["models"].values() if m.get("distilled") and m.get("family") in s["models"]):
        base = s["models"][m["family"]]
        out += [f"**{base['name']} and {m['name']} are served differently:** {base['name']} by "
                f"{base.get('endpoint') or base.get('server')}, {m['name']} by our own {m['server']} on "
                f"{m['cost']['gpu']['where'] if m['cost'].get('gpu') else 'our GPU boxes'}, so numerics, the "
                "tool-call parser and sampling can differ between them.",
                f"**{m['name']}'s training data and these windows.** {DISTILL_SPANS} The training pack, "
                "`data/desk/desk-v4-win`, is on the plugin's `desk-distill` branch at 13d53f9 and can be rebuilt with "
                f"`scripts/desk_data_build.py` ([the check]({REPO}/blob/{s['run'].get('deviations_ref') or 'main'}/"
                "docs/prereg/desk-distill.md#after-the-results))."]
    return out


DISTILL_SPANS = ("Its training windows read D-7 to D2 of their dates, and only the 2026-05-08 front's operating days "
                 "(05-08 to 05-10, its four windows) fall inside any of those spans, as the DAM and MCPC price "
                 "history of the 16 training windows that start 2026-05-14 to 05-17. The training transcripts never "
                 "name those days, and on those four windows its C is within 1.7 points of the planner's.")


def ladder(d: dict) -> list[dict]:
    return [v for v in d["versions"] if v["role"] == "ladder"]


def checks(d: dict) -> list[dict]:
    return [v for v in d["versions"] if v["role"] == "check"]


def inside(d: dict, bench: tuple[dict, list[dict]] | None = None) -> str:
    n = {k: sum(v["rows"][k] for v in d["versions"]) for k in ("leaderboard", "runs", "tasks")}
    tick = lambda vs: and_join([f"`{v['version']}`" for v in vs])  # noqa: E731
    lead = [f"| **`desk_v4_bench`**, the default | {len(bench[1]):,} | The v4 benchmark: each model's every window, "
            "one split per side of the training cutoffs (`pre_cutoff`, `post_cutoff`): its harness and settings, the "
            "grade (C, R, P and every reference), turns, wake-ups, desk and own-tool calls, tokens, cost, attempts "
            "and the Episode JSON's path; a window a model never finished is a row marked `missing`. |"
            ] if bench else []
    return "\n".join([
        "| Config | Rows | What it holds |", "|---|---:|---|", *lead,
        f"| **`desk_leaderboard`**{'' if bench else ', the default'} | {n['leaderboard']:,} | Each model and reference "
        "of each version: "
        "each model's settings (`reasoning_effort`, `thinking`), C, P and R, the paired gaps to the anchor and to the "
        "real operator's bids with their CIs, cost and how it traded. |",
        f"| **`desk_runs`** | {n['runs']:,} | Each model's every task: its settings, its grade, every statement line, "
        "usage and its Episode JSON's path. |",
        f"| **`desk_tasks`** | {n['tasks']:,} | Every task of each version's pilot, eval and tune packs: its dates, "
        "anonymous site card, tags and the references it was graded against. |", "",
        f"The desk configs have one split per version, {tick(ladder(d))}, and one for the price-impact check, "
        f"{tick(checks(d))}. Each one's folder, `results/desk-v<N>/`, holds its README, `summary.json`, "
        "`grades.jsonl.gz`, figures, raw runs (`runs/<model>/results.jsonl.gz` and the per-call logs) and every "
        "Episode JSON (`episodes/<model>/*.json.gz`)"
        + ("; `results/desk-v4-bench/` holds the benchmark's README, `summary.json` (every number of the benchmark on "
           "this card), `grades.jsonl.gz`, figures and every scored Episode JSON" if bench else "")
        + "; `assets/` holds the article's film, the earlier desk GIFs and this card's figures."])


BENCH_QUICKSTART = """The benchmark's runs are each a plain `agent-env run` of a bundle that `scripts/desk_bench.py`
writes for one harness ({harnesses}), with a `.agentenv/config.toml` that names the model endpoint and its key. By
default the bundle's network allowlist holds only the harness vendor's API host, for a sandbox provider that enforces
it, such as Modal, which the bundle was built for. Our runs took route C instead: local Docker on EC2 boxes, with a
host egress rule and a per-run model proxy ([deviations]({deviations})):

```bash
uv run python scripts/desk_bench.py tasks --harness codex-luna --pack desk-v4-bench --out bundles/bench-codex-luna
uv run agent-env run bundles/bench-codex-luna --task desk-v4-2026-07-04-S01
```"""
ARCHIVE = ("GridSimEnv v1 (one-shot day-ahead schedule, training results) is archived at revision "
           f"[6ae10fcc]({DATASET}/tree/6ae10fcc7fea8037716a0ea7f4ef761786a34f87).")


def ladder_block(d: dict) -> str:
    done, lad, chk = {v["version"]: v for v in d["versions"]}, [x["version"] for x in d["ladder"]], checks(d)
    rows = [f"| **{x['version']}, {x['name']}**<br><small>" + (
        f"{done[x['version']]['n_tasks']} {unit(done[x['version']])}s, results under Earlier versions"
        if x["version"] in done else "next")
        + f"</small> | {md(x['adds'])} | {md(x['does'])} |" for x in d["ladder"]] + [
        f"| **{v['version']}, {v['name']}**<br><small>a price-impact check on {v['check_of']}'s {v['n_tasks']} "
        f"{unit(v)}s, results under Earlier versions</small> | {md(v['adds'])} | {md(v['does'])} |" for v in chk]
    return "\n".join([
        f"**{NUM[len(lad)]} versions ({lad[0]}–{lad[-1]}) plus a price-impact check "
        f"({and_join([v['version'] for v in chk])}).** Each version adds one kind of realism to the same desk, tools "
        "and grading. The check re-runs " + and_join([f"{v['check_of']}'s {unit(v)}s" for v in chk]) + " with the "
        "desk's day-ahead offers re-clearing the market, to measure how far one battery moves the price.", "",
        "| Version | What it adds | What the agent does |", "|---|---|---|", *rows])


def desk_results(v: dict, d: dict) -> str:
    charts = d["charts"]
    sites = ", ".join(f"{s['region']} {s['size']}" for s in v["sites"])
    a, b = (f"{date.fromisoformat(x):%-d %B %Y}" for x in v["dates"])
    rows = [desk_row(m, d["models"][m["key"]]) for m in v["models"]] + [
        f"| *{r['short']}* | *{h(r['C']['mean'])}* | *{usdk(r['P']['mean'])}* |"
        for r in v["references"] if r["key"] != "idle" or abs(r["P"]["mean"]) >= 0.5]
    gaps = [f"| {who(d['models'][m['key']])} | "
            + ("–" if m["P_minus_operator_replay"]["mean"] is None else stacked_usd(m["P_minus_operator_replay"], True))
            + f" | {stacked_usd(m['P_minus_anchor'], True)} |" for m in v["models"]]
    return "\n".join([
        f"### {v['version']}, {v['name']}: results", "",
        (f"{v['n_tasks']} battery-days: {len(v['sites'])} real batteries ({sites}) on {v['n_days']} operating days "
         f"from {a} to {b}" if v["days_per_task"] == 1 else
         f"{v['n_tasks']} windows of {v['days_per_task']} operating days: {len(v['sites'])} real batteries ({sites}) "
         f"across {v['n_days']} {v['block']}s from {a} to {last(v)}")
        + ", each old enough for ERCOT to have disclosed the operators' bids. Each model plays each one once under "
        "pre-registered settings.", "",
        f"| Desk | C, hindsight capture | P, $ a {unit(v)} |", "|---|---:|---:|", *rows, "",
        f"| Paired, $ a {unit(v)} | P − the operator's bids | P − anchor |", "|---|---:|---:|", *gaps, "",
        "<small>The anchor is the desk's own optimiser, re-planning at every wake on the same information. The "
        f"operator rows are the real operator's own bids on each {unit(v)}, disclosed by ERCOT 60 days later and "
        "replayed through the same clearing and settlement, and its actual awards and metered output settled the same "
        "way. Hindsight knows every price in advance. " + (f"{v['idle']} " if v.get("idle") else "")
        + f"Brackets: {v['block']}-block bootstrap 95% CIs over {v['n_days']} {v['block']}s.</small>", "",
        *([f"<small>{' '.join(x for x in (v.get('defects'), v.get('deviations')) if x)}</small>", ""]
          if v.get("defects") or v.get("deviations") else []),
        f"**How much of the hindsight optimum each desk captured, {by(v)}, {v['version']}**", "",
        *chart(f"desk-{v['version']}-days", days_alt(v, d), charts["width"], charts["phone"]["media"]), "",
        f"<small>{days_caption(v, d)}</small>", "", *(f"- {x}" for x in desk_bullets(v)), "",
        f"[{v['version']}'s results page]({APP}/results.html?v={v['version']}) in the Replays Space lists every "
        f"{unit(v)} with a replay of each model's run.", "",
        f"Every number is in [`{v['folder']}`]({DATASET}/tree/main/{v['folder']}) (its README, `summary.json`, "
        "`grades.jsonl.gz`, every Episode JSON and run log) and in the `desk_leaderboard` and `desk_runs` configs, "
        f"split `{v['version']}`; the code is the [`{v['ref']}`]({v['github']}) tag of the plugin."])


def chart(name: str, alt: str, width: int, media: str, base: str = "assets/figures") -> list[str]:
    """One of the card's own charts (scripts/hub_desk.py draws them from hub/desk-charts) as SVG at the width it is
    drawn at, in the page's light or dark theme as the Hub's theme is, and on a phone in its phone layout (a source
    the Hub leaves as written, so its URL is absolute)."""
    phone = f"{DATASET}/resolve/main/{base}/{name}-phone"
    return [f'<picture><source media="{media}" srcset="{phone}{sfx}.svg"><img class="{cls}" '
            f'src="{base}/{name}{sfx}.svg" width="{width}" alt="{escape(alt)}"></picture>'
            for sfx, cls in (("", "dark:hidden"), ("-dark", "hidden dark:block"))]


def by(v: dict) -> str:
    return "front by front" if v["days_per_task"] > 1 else "day by day"


def days_alt(v: dict, desk: dict) -> str:
    ds, scale, n = v["days"], desk["charts"]["days_scale"], NUM[len(ladder(desk))].lower()
    each = [f"{desk['models'][m['key']]['label']} " + ", ".join(f"{pc(d['C'][m['key']])}%" for d in ds)
            for m in v["models"]]
    each += ["the real operator's bids, replayed, " + ", ".join(f"{pc(d['C']['operator_replay'])}%" for d in ds)
             if all(d["C"].get("operator_replay") is not None for d in ds) else ""]
    named, years = [d for d in ds if d.get("named")], "–".join(sorted({d["block"][:4] for d in ds}))
    unit_ = "fronts" if v["days_per_task"] > 1 else "days"
    return (f"Line chart of hindsight capture C {by(v)}, each point the mean of the {ds[0]['n']} sites' {span(v)}s, "
            f"as a percentage of the hindsight optimum's profit over idle, on a scale of {pc(scale[0], 0)}% to "
            f"{pc(scale[1], 0)}% shared by all {n} versions, over {len(ds)} {unit_} "
            f"({', '.join(short(v, d['block']) for d in ds)} {years}): " + "; ".join(x for x in each if x) + "."
            + (f" Shaded: {named[0]['named']}, {short(v, named[0]['block'])}." if named else ""))


def days_caption(v: dict, desk: dict) -> str:
    ds, multi, scale, n = v["days"], v["days_per_task"] > 1, desk["charts"]["days_scale"], len(ladder(desk))
    named = [d for d in ds if d.get("named")]
    region = {s["name"].split()[-1]: s["region"] for s in v["sites"]}
    moved = [t for t in v["tasks"] if t["date"] != t["block"]]
    return (f"Each point is the mean C of the {ds[0]['n']} {span(v)}s {'of that front' if multi else 'that day'}, one "
            f"per site; grey dashed, the real operator's own bids, replayed. All {NUM[n].lower()} versions share one "
            f"scale, {pc(scale[0], 0)}% to {pc(scale[1], 0)}%."
            + (f" Shaded: {named[0]['named']}, {long_(v, named[0]['block'])}." if named else "")
            + "".join(f" The {region.get(t['site'], t['site'])} window of the {long_(v, t['block'])} front ran "
                      f"{long_(v, t['date'])}." for t in moved))


def pc(x: float, nd: int = 1, sign: bool = False) -> str:
    """C as a percentage, half-up to nd decimals, with a true minus: 0.3463 is 34.6."""
    q = (Decimal(str(x)) * 100).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP)
    return f"{'−' if q < 0 else '+' if sign and q > 0 else ''}{abs(q)}"


def short(v: dict, iso: str) -> str:
    """'25 Jan'; a front's three days, '23–25 Jan'."""
    a = date.fromisoformat(iso)
    b = a + timedelta(days=v["days_per_task"] - 1)
    return f"{a:%-d %b}" if a == b else f"{a:%-d}–{b:%-d %b}" if a.month == b.month else f"{a:%-d %b}–{b:%-d %b}"


def long_(v: dict, iso: str) -> str:
    a = date.fromisoformat(iso)
    b = a + timedelta(days=v["days_per_task"] - 1)
    return f"{a:%-d %B %Y}" if a == b else f"{a:%-d} to {b:%-d %B %Y}" if a.month == b.month else (
        f"{a:%-d %B} to {b:%-d %B %Y}")


def last(v: dict) -> str:
    return f"{date.fromisoformat(v['dates'][1]) + timedelta(days=v['days_per_task'] - 1):%-d %B %Y}"


def desk_row(m: dict, s: dict) -> str:
    cost = m["usd_per_episode"]
    sub = [s["setting"]] + (["open weights"] if m["weights"] == "open" else [f"${cost:.2f} a run"] if cost else [])
    return (f"| **{s['name']}**<br><small>{' · '.join(sub)}</small> | **{h(m['C']['mean'])}**<br><small>"
            f"{ci(m['C']['ci'])}</small> | {stacked_usd(m['P'])} |")


def who(s: dict) -> str:
    """A model as the card's tables name it: its name over its setting, the two halves of its label."""
    return f"**{s['name']}**<br><small>{s['setting']}</small>"


def models_block(d: dict) -> str:
    lead, *each = models_lines(d)
    return "\n".join([f"- **Models and settings.** {lead}", *(f"  - {x}" for x in each)])


def models_lines(d: dict) -> list[str]:
    """The models and their settings in Markdown, from desk.json's `models`: how every run was played, then what each
    label's setting is and how the model was served. desk.json carries them as `models_lines` for the viewer."""
    api = [s for s in d["models"].values() if s["weights"] == "API"]
    q = next(s for s in d["models"].values() if s["weights"] == "open")
    names, ids = and_join([f"**{s['label']}**" for s in api]), ", ".join(f"`{s['model_id']}`" for s in api)
    return ["One sampled run per model per task, with the same system prompt, the same 11 tools and the same turn "
            "budget.",
            f"{names} ({ids}): reasoning effort {api[0]['reasoning_effort']}, through the {api[0]['api']}.",
            f"**{q['label']}** (`{q['checkpoint']}`): thinking {'on' if q['thinking'] else 'off'}, temperature "
            f"{q['temperature']}, top_p {q['top_p']}; served by {q['server']} in {q['dtype']} with a "
            f"{q['context_tokens']:,}-token context and the {q['tool_parser']} tool parser; prompts compacted to about "
            f"{q['prompt_tokens'] // 1000}k tokens, with up to {q['max_output_tokens']:,} output tokens a call."]


def unit(v: dict) -> str:
    return "battery-day" if v["days_per_task"] == 1 else f"{v['days_per_task']}-day window"


def stacked_usd(b: dict, sign: bool = False) -> str:
    return f"{usdk(b['mean'], sign)}<br><small>[{usdk(b['ci'][0], sign)}, {usdk(b['ci'][1], sign)}]</small>"


def usdk(x: float, sign: bool = False) -> str:
    """Thousands of dollars to one decimal, a whole dollar figure under $1,000; a word joiner keeps the sign on it."""
    v = f"{h(abs(x) / 1000, 1)}k" if abs(x) >= 999.5 else f"{abs(x):.0f}"
    return f"{'' if v == '0' else '−' if x < 0 else '+' if sign else ''}\u2060${v}"


def desk_bullets(v: dict) -> list[str]:
    ms, refs = v["models"], {r["key"]: r for r in v["references"]}
    top, others = ms[0], ms[1:]
    pairs = {(x["a"], x["b"]): x["C"] for x in v["paired"] if "C" in x}
    pairs |= {(b, a): {"mean": -c["mean"], "ci": [-c["ci"][1], -c["ci"][0]]} for (a, b), c in list(pairs.items())
              if (b, a) not in pairs}
    leads = [(m, pairs[top["key"], m["key"]]) for m in others if (top["key"], m["key"]) in pairs]
    out = [f"**{top['name']} captures the most of hindsight:** C {h(top['C']['mean'])} {ci(top['C']['ci'])}, "
           f"{usd0(top['P']['mean'])} a {unit(v)}" + (", against " + " and ".join(
               f"{h(m['C']['mean'])} for {m['name']}" for m in others) if others else "") + "."
           + (f" Paired by {unit(v)}, its lead in C: " + "; ".join(
               f"{m['name']} {gap(d)}" + (", a CI that includes zero" if d["ci"][0] <= 0 <= d["ci"][1] else "")
               for m, d in leads) + "." if leads else "")]
    if "operator_replay" in refs:
        op = refs["operator_replay"]["P"]["mean"]
        gaps = [f"{m['name']} {usd0(m['P_minus_operator_replay']['mean'], True)} "
                f"{usd0_ci(m['P_minus_operator_replay']['ci'], True)}" for m in ms
                if m["P_minus_operator_replay"]["mean"] is not None]
        ahead = [m["name"] for m in ms if m["P_minus_operator_replay"]["mean"] is not None
                 and m["P_minus_operator_replay"]["ci"][0] > 0]
        behind = [m["name"] for m in ms if m["P_minus_operator_replay"]["mean"] is not None
                  and m["P_minus_operator_replay"]["ci"][1] < 0]
        out.append(f"**Against the real operator:** its own bids, replayed through the same clearing and settlement, "
                   f"earn {usd0(op)} a {unit(v)}; paired, {'; '.join(gaps)}. "
                   + (f"Ahead with a CI above zero: {' and '.join(ahead)}." if ahead else
                      "No model is ahead with a CI above zero.")
                   + (f" Behind with a CI below zero: {' and '.join(behind)}." if behind else ""))
    out += sensitivity(v) + reserves(v) + dam_days(v)
    a, spread = refs["anchor"], "anchor" in (v.get("sensitivity") or {}).get("bought_back", [])
    out.append("**The anchor,** the desk's own optimiser on the same information, "
               + ("" if spread else "free to take DAM/RT spread positions, ")
               + f"captures C {h(a['C']['mean'])} ({usd0(a['P']['mean'])} a {unit(v)})"
               + (", partly from DAM/RT spread positions that pay off on scarcity days" if spread else "")
               + f"; paired against it, a {unit(v)}: " + "; ".join(
                   f"{m['name']} {usd0(m['P_minus_anchor']['mean'], True)} {usd0_ci(m['P_minus_anchor']['ci'], True)}"
                   for m in ms) + ".")
    paid = [f"{m['name']} ${m['usd_per_episode']:.2f}" for m in ms if m["weights"] != "open" and m["usd_per_episode"]]
    local = [m["name"] for m in ms if m["weights"] == "open"]
    if paid:
        out.append(f"**A {unit(v)}'s inference** costs {' and '.join(paid)} at list prices"
                   + (f"; {' and '.join(local)} runs on one GPU." if local else "."))
    return out


def sensitivity(v: dict) -> list[str]:
    """The post-hoc check of the block that carries the means (the report's, else the one scripts/hub_desk.py derives
    from the grades): what each desk earned there, which desks made more than half their total P there and, where the
    statements show it, how; the means without it, the medians over every task and each model's losing tasks."""
    sv = v.get("sensitivity") or {}
    w = sv.get("without") or sv.get("derived")
    if not w:
        return []
    ms, u, blk = {m["key"]: m for m in v["models"]}, unit(v), sv.get("block", "day")
    name = lambda k: ms[k]["name"] if k in ms else SHORTS.get(k, k)  # noqa: E731
    days = {d: block_label(v, d) for d in w["days"]}
    on = {label: ", ".join(f"{name(k)} {usd0(x)}" for k, x in {
        **sv["per_day_mean_P"][d]["models"], **sv["per_day_mean_P"][d]["references"]}.items() if x is not None)
        for d, label in days.items()}
    wo = "; ".join(f"{name(k)} {usd0(b['P']['mean'])}" + (f" {usd0_ci(b['P']['ci'])}" if "ci" in b["P"] else "")
                   for k, b in w["means"]["models"].items())
    wr = " and ".join(f"{name(k)} {usd0(b['P']['mean'])}" for k, b in w["means"]["references"].items()
                      if k in ("operator_replay", "anchor"))
    med = "; ".join(f"{name(k)} {usd0(x)}" for k, x in {**sv["median_P"], **sv["median_P_references"]}.items()
                    if k in ms or k == "operator_replay")
    loss = "; ".join(f"{name(k)} {x['tasks_p_below_0']} of {v['n_tasks']}"
                     + (f" (worst {usd0(x['worst_p'])})" if x["tasks_p_below_0"] else "")
                     for k, x in sv["losses"].items())
    who, bb = [name(k) for k in sv.get("carried", [])], [name(k) for k in sv.get("bought_back", [])]
    one, there = len(days) == 1, "there" if blk != "day" else "that day"
    head = (f"One {blk} carries" if one else f"A few {blk}s carry") + " the means" if who else \
        f"Without {and_join(list(days.values()))}"
    when = (f"Mean P a {u} {next(iter(on))}" + (f", {sv['why_short']}" if sv.get("why_short") else "")
            + f": {next(iter(on.values()))}." if one else f"Mean P a {u}: " + "; ".join(
                f"{d}, {x}" for d, x in on.items()) + ".")
    return [f"**{head}.** {when}"
            + (f" {and_join(who)} made more than half of {'its' if len(who) == 1 else 'their'} total P "
               f"{there if one else f'in those {blk}s'}" + ("" if not bb else f", from {BUYBACK}" if bb == who
                                                             else f"; {and_join(bb)} from {BUYBACK}") + "."
               if who else "")
            + f" Without {'it' if one else 'them'} ({w['n_tasks']} {u}s): {wo}, against {wr}. Over every {u}, the "
            f"medians are {med}. P below zero: {loss}. A post-hoc check, not pre-registered."]


def block_label(v: dict, d: str) -> str:
    """'on 25 January 2026' for a day; 'on the front of 23 to 25 January 2026 (winter storm Fern)' for a window."""
    a = date.fromisoformat(d)
    if v["days_per_task"] == 1:
        return f"on {a:%-d %B %Y}"
    b = a + timedelta(days=v["days_per_task"] - 1)
    named = (v.get("sensitivity") or {}).get("names", {}).get(d)
    return (f"on the front of {a:%-d} to {b:%-d %B %Y}" if a.month == b.month else
            f"on the front of {a:%-d %B} to {b:%-d %B %Y}") + (f" ({named})" if named else "")


AS_CODES = {"ASO-01": "a product the battery may not offer", "ASO-02": "the shape check",
            "ASO-06": "after the market window closed"}


def reserves(v: dict) -> list[str]:
    """What each model's reserve offers won and earned, and which ERCOT-style checks refused them (v3 on)."""
    ms = [m for m in v["models"] if m.get("ancillary")]
    if not ms:
        return []
    def one(m: dict) -> str:
        a, rc = m["ancillary"], m["ancillary"]["rejected_codes_total"]
        got = m["lines"].get("dam_as_capacity", 0.0) + m["lines"].get("rt_as_imbalance", 0.0)
        why = "; ".join((f"{c} ×{k}" if len(rc) > 1 else c) + (f", {AS_CODES[c]}" if c in AS_CODES else "")
                        for c, k in rc.items())
        no = f", AS offers refused {sum(rc.values())} times ({why})" if rc else ""
        return (f"{m['name']}: AS awards in {a['episodes_with_awards']} of {m['n']} {unit(v)}s, {usd0(got, True)} a "
                f"{unit(v)} from the AS lines{no}")
    return ["**Reserves.** " + "; ".join(one(m) for m in ms) + "."]


def price_check(v: dict, d: dict) -> str:
    """v5: the battery-days of the version it checks, re-run with each desk's DAM curves re-cleared against the day's
    real offers; how far that moved the price, and each model's gap to its own run there, paired by task."""
    pi, vs, u, of = v["price_impact"], v["versus"]["models"], unit(v), v["check_of"]
    names = {m["key"]: m["name"] for m in v["models"]}
    top = max((k for k in names if k in pi), key=lambda k: abs(pi[k]["revenue_effect_usd_per_episode"]))
    mw, move = sorted({int(x["size"].split()[0]) for x in v["sites"]}), pi[top]["sales_mwh_weighted_usd_per_mwh"] * 100
    effect = usd0(pi[top]["revenue_effect_usd_per_episode"], True)
    noise = all(b[x]["ci"][0] <= 0 <= b[x]["ci"][1] for b in vs.values() for x in ("P", "R", "C"))
    rows = [f"| {who(d['models'][m['key']])} | {h(m['C']['mean'])}<br><small>{ci(m['C']['ci'])}</small> | "
            f"{stacked(vs[m['key']]['C'])} | {stacked_usd(vs[m['key']]['P'], True)} |" for m in v["models"]]
    return "\n".join([
        f"### {v['version']} · {v['name']}: a price-impact check", "",
        f"{v['version']} re-runs {of}'s {v['n_tasks']} {u}s with each desk's day-ahead curves re-cleared against the "
        f"day's real offer stack, as ERCOT disclosed it 60 days later. One {mw[0]}–{mw[-1]} MW battery moves the price "
        f"by cents: {names[top]}'s offers moved it by {'−' if move < 0 else '+'}{abs(move):.1f}¢/MWh on its sales, at "
        f"most ${pi[top]['max_abs_usd_per_mwh']:.2f}/MWh, about {effect} in revenue a {u}. "
        + (f"Paired by {u}, every {v['version']} − {of} difference in C, P and R has a 95% CI that includes zero: "
           f"{v['version']} reproduces {of}. " if noise else "")
        + "The next step that would make price impact matter is a fleet desk: a QSE trading a portfolio of batteries.",
        "", f"| Desk | C in {v['version']} | {v['version']} − {of} in C | {v['version']} − {of} in P, $ a {u} |",
        "|---|---:|---:|---:|", *rows, "",
        f"<small>{v['version']} − {of}: each model's {v['version']} run minus its {of} run on the same {u}, averaged. "
        f"Brackets: {v['block']}-block bootstrap 95% CIs over {v['n_days']} {v['block']}s.</small>", "",
        f"Every number is in [`{v['folder']}`]({DATASET}/tree/main/{v['folder']}) and in the `desk_leaderboard` and "
        f"`desk_runs` configs, split `{v['version']}`; the code is the [`{v['ref']}`]({v['github']}) tag of the "
        "plugin."])


def across(d: dict) -> str:
    """The models' C over the ladder's versions, as the card's lead chart and a table, and what the paired gaps between
    them say."""
    vs = ladder(d)
    if len(vs) < 2:
        return ""
    keys = list(dict.fromkeys(m["key"] for v in vs for m in v["models"]))
    names = {m["key"]: m["name"] for v in vs for m in v["models"]}
    cell = lambda v, k: next((f"{h(m['C']['mean'])}<br><small>{ci(m['C']['ci'])}</small>" for m in v["models"]  # noqa: E731
                              if m["key"] == k), "–")
    rows = [f"| {who(d['models'][k])} | " + " | ".join(cell(v, k) for v in vs) + " |" for k in keys]
    return "\n".join(["**How much of the hindsight optimum each desk captured, version by version**", "",
                      *chart("desk-across", across_alt(d, keys, names), d["charts"]["lead"],
                             d["charts"]["phone"]["media"]), "",
                      f"<small>{across_caption(d, names)}</small>", "",
                      "| Desk | " + " | ".join(v["version"] for v in vs) + " |",
                      "|---|" + "---:|" * len(vs), *rows, "", across_text(d)])


def across_alt(d: dict, keys: list[str], names: dict[str, str]) -> str:
    vs = ladder(d)
    each = [f"{d['models'][k]['label']} " + ", ".join(f"{pc(m['C']['mean'])}%" for v in vs if (m := next(
        (x for x in v["models"] if x["key"] == k), None))) for k in keys]
    ops = [next((r for r in v["references"] if r["key"] == "operator_replay"), None) for v in vs]
    op = ["the real operator's bids, replayed, " + ", ".join(f"{pc(r['C']['mean'])}%" for r in ops)] if all(
        ops) else []
    gaps = [f" In {v['version']}, {names['sol']} − {names['luna']}, paired by {span(v)}: {pc(g['mean'], 1, True)} "
            f"points [{pc(g['ci'][0])}, {pc(g['ci'][1])}]." for v, g in clear_gaps(d)]
    names_ = "; ".join(f"{v['version']} {v['name']}, {count(v)}" for v in vs)
    return ("Line chart of hindsight capture C, as a percentage of the hindsight optimum's profit over idle, across "
            f"the {NUM[len(vs)].lower()} versions ({names_}): " + "; ".join(each + op) + "." + "".join(gaps)
            + " Each value's 95% CI is in the table below.")


def across_caption(d: dict, names: dict[str, str]) -> str:
    multi = [f"in {v['version']}, over its {v['n_days']} {v['block']}s" for v in ladder(d) if v["block"] != "day"]
    clear = clear_gaps(d)
    return ("C × 100: the share of the hindsight optimum's profit over idle that each desk captured; the table below "
            "gives each value with its 95% CI (a block bootstrap over operating days"
            + (f"; {'; '.join(multi)}" if multi else "") + "). Grey dashed: the real operator's own bids, replayed "
            "through the same clearing and settlement."
            + (f" The callout in {and_join([v['version'] for v, _ in clear])} is {names['sol']}'s lead over "
               f"{names['luna']} in points, paired by {and_join(list(dict.fromkeys(span(v) for v, _ in clear)))}, with "
               f"its 95% CI; {and_join([v['version'] for v, _ in clear])} "
               f"{'is the only version' if len(clear) == 1 else 'are the only versions'} where that CI excludes zero."
               if clear else "")
            + "".join(f" {v['version']} is not on the chart: it re-runs {v['check_of']}'s {unit(v)}s as a price-impact "
                      "check, in its own section below." for v in checks(d)))


def count(v: dict) -> str:
    """'32 battery-days'; '16 three-day windows over 4 fronts'."""
    return f"{v['n_tasks']} {span(v)}s" + (f" over {v['n_days']} {v['block']}s" if v["days_per_task"] > 1 else "")


def span(v: dict) -> str:
    d = v["days_per_task"]
    return f"{NUM.get(d, str(d)).lower()}-day window" if d > 1 else "battery-day"


def clear_gaps(d: dict) -> list[tuple[dict, dict]]:
    """The versions where GPT-6.1 Sol and GPT-6 Luna's paired C gap has a CI that excludes zero, Sol minus Luna."""
    return [(v, g) for v in ladder(d) if (g := paired_c(v, "sol", "luna")) and (g["ci"][0] > 0 or g["ci"][1] < 0)]


def paired_c(v: dict, a: str, b: str) -> dict | None:
    for x in v["paired"]:
        if (x["a"], x["b"]) == (a, b) and "C" in x:
            return x["C"]
        if (x["a"], x["b"]) == (b, a) and "C" in x:
            return {"mean": -x["C"]["mean"], "ci": [-x["C"]["ci"][1], -x["C"]["ci"][0]]}
    return None


def across_text(d: dict) -> str:
    """The card's one-liner, also desk.json's `across`: where GPT-6.1 Sol and GPT-6 Luna's paired C gap is within noise
    and where it is not, by how long the ladder's tasks run, and whether the untrained model is last in every
    version."""
    vs, clear = ladder(d), clear_gaps(d)
    close = [v for v in vs if all(v is not c for c, _ in clear)]
    on = lambda xs: "single days" if all(v["days_per_task"] == 1 for v in xs) else (  # noqa: E731
        f"{xs[0]['days_per_task']}-day weather fronts")
    out = [f"Paired by task, GPT-6.1 Sol and GPT-6 Luna are within noise on {on(close)} "
           f"({', '.join(v['version'] for v in close)}) and {'Sol' if clear[0][1]['mean'] > 0 else 'Luna'} is clearly "
           f"ahead on {on([v for v, _ in clear])} (" + "; ".join(
               f"{v['version']}: {pc(g['mean'], 1, True)} pts of hindsight capture, 95% CI [{pc(g['ci'][0])}, "
               f"{pc(g['ci'][1])}]" for v, g in clear) + ")."]
    if all(min(v["models"], key=lambda m: m["C"]["mean"])["key"] == "qwen" for v in vs):
        out.append("The untrained Qwen3-4B has the lowest capture throughout.")
    return " ".join(out)


def dam_days(v: dict) -> list[str]:
    """Over a multi-day window: how often each model's day-ahead bids for each operating day were accepted."""
    ms = [m for m in v["models"] if m.get("submissions_by_day") and v["days_per_task"] > 1]
    if not ms:
        return []
    days = [f"D{i}" for i in range(v["days_per_task"])]
    return [f"**{NUM[len(days)]} day-ahead markets.** Accepted DAM submissions a window for each operating day, "
            + "/".join(days) + ": " + "; ".join(
                f"{m['name']} " + "/".join(f"{m['submissions_by_day'].get(f'dam:{d}', 0):.2f}" for d in days)
                for m in ms) + ". A mean above one means a desk rebid some of those markets as forecasts moved."]


NUM = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight", 9: "Nine", 10: "Ten",
       11: "Eleven", 12: "Twelve", 13: "Thirteen", 14: "Fourteen", 15: "Fifteen", 16: "Sixteen"}


def and_join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


BUYBACK = ("day-ahead sales bought back in real time: positions the DAM allows because it ignores state of charge, and "
           "which ERCOT's DAM credit screening, not modelled here, would limit")
SHORTS = {"anchor": "the anchor", "operator_replay": "the operator's bids",
          "operator_actual": "the operator as settled"}


def usd0(x: float, sign: bool = False) -> str:
    v = f"{abs(x):,.0f}"
    return f"{'' if v == '0' else '−' if x < 0 else '+' if sign else ''}\u2060${v}"


def usd0_ci(c: list[float], sign: bool = False) -> str:
    return f"[{usd0(c[0], sign)}, {usd0(c[1], sign)}]"


def desk_configs(d: dict, bench: tuple[dict, list[dict]] | None = None) -> list[dict]:
    """The desk's configs; with the benchmark, `desk_v4_bench` (one row per model and window, a split per side of
    the training cutoffs) leads as the default."""
    lead = [{"config_name": "desk_v4_bench", "default": True, "data_files": [
        {"split": s, "path": f"desk_v4_bench/{s}.parquet"} for s in BENCH_SPLITS]}] if bench else []
    return lead + [{"config_name": f"desk_{name}", **({"default": True} if name == "leaderboard" and not bench else {}),
                    "data_files": [{"split": v["version"], "path": f"desk_{name}/{v['version']}.parquet"}
                                   for v in d["versions"]]} for name in ("leaderboard", "runs", "tasks")]


def eval_runs() -> dict[str, list[dict]]:
    """Every schedule behind the leaderboard, as scripts/hub_results.py re-grades them from the committed records."""
    spec = importlib.util.spec_from_file_location("hub_results", ROOT / "scripts/hub_results.py")
    hr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hr)
    return hr.eval_runs(BEAM)


def card_text(results_dir: Path) -> str:
    """The desk's card: hub/dataset/README.md with the article's facts in its prose and each block filled in, from the
    article's data, results/desk-v4-bench/ and results/overview/desk.json, and the desk's configs as the only ones; the
    v1 files stay in the repo, outside every config."""
    d = json.loads((results_dir / DESK).read_text())
    bench = bench_read(results_dir / "desk-v4-bench")
    if bench is None or bench[0]["fake"]:
        raise SystemExit(f"{results_dir / 'desk-v4-bench'} holds no real benchmark results; the card states real runs")
    f = facts(*bench)
    text = CARD.read_text()
    check_numbers(text)
    for name, block in desk_blocks(d, bench, f).items():
        text, n = re.subn(rf"^<!-- {name} -->$", lambda m, b=block: b, text, flags=re.M)
        if n != 1:
            raise SystemExit(f"{CARD} has no <!-- {name} --> line")
    if left := re.findall(r"^<!-- [\w-]+ -->$", text, flags=re.M):
        raise SystemExit(f"{CARD} has lines no block fills: {left}")
    text = fill(text, f)
    banned(text)
    out = DatasetCard(re.sub(r"\n{3,}", "\n\n", text))
    out.data.configs = desk_configs(d, bench)
    out.data.agentenv = {"bundles": {"gridsim-v1": {"plugins": [V1_PLUGIN], "setup": SETUP}}}
    return str(out)


FACT = re.compile(r"\{(F(?:\.[A-Za-z0-9_]+)+)\}")
NUMBER = re.compile(r"[−+-]?⁠?\\?\$[\d,]+(?:\.\d+)?k?|[−+-]?\d+\.\d+¢|[−+-]?\b\d+\.\d{2,}\b|\b\d+(?:\.\d+)?%")
CONSTANT = {"0.2", "0.8", "95%", "0%", "100%"}
BANNED = ((re.compile(r"every model[’']s (?:\w+ )?training cut-?off", re.I),
           "the cutoffs are reported ones: say after every reported training cutoff"),
          (re.compile(r"\$5,000"), "the card states no offer cap"),
          (re.compile(r"\bTexas has\b"), "write ERCOT's grid"))
"""What the card must not say, and why."""


def facts(s: dict, grades: list[dict]) -> dict:
    """The article's facts.json (scripts/hub_article.py formats it from summary.json, the grades, the episodes and the
    failure replay's failures.json), which the card's prose reads as the article's chapters do. Where it states what
    those files state, they must agree, so a facts.json older than the results stops the build."""
    f = article("facts.json")
    ms, plan = s["models"], s["references"]["anchor"]["all"]["C"]["mean"]
    hero = next(g for g in grades if g["model"] == s["hero"]["model"] and g["task_id"] == s["hero"]["task_id"])
    sft = next(m for m in ms.values() if m.get("distilled"))
    want = {"F.env.windows": str(s["n_windows"]), "F.env.fronts": str(s["n_fronts"]), "F.env.models": str(len(ms)),
            "F.eval.runs": str(sum(m["n"] for m in ms.values())), "F.lead.name": ms[hero["model"]]["name"],
            "F.lead.P": dollars(hero["p"]), "F.lead.op": dollars(hero["p_operator_actual"]),
            "F.reward.name": ms[hero["model"]]["name"], "F.reward.P": dollars(hero["p"]),
            "F.reward.C": f"{pc(hero['capture'])}%", "F.train.base_name": ms[sft["family"]]["name"],
            "F.train.base": f"{pc(ms[sft['family']]['all']['C']['mean'])}%",
            "F.train.sft": f"{pc(sft['all']['C']['mean'])}%",
            "F.train.planner": f"{pc(plan)}%", "F.train.usd": bench_usd(sft["cost"]["usd_per_window"])}
    for k, m in ms.items():
        c = m["all"]["C"]
        want |= {f"F.eval.m.{k}.name": m["name"], f"F.eval.m.{k}.n": str(m["n"]),
                 f"F.eval.m.{k}.C": f"{pc(c['mean'])}%",
                 f"F.eval.m.{k}.ci": f"[{pc(c['ci'][0])}, {pc(c['ci'][1])}]",
                 f"F.eval.m.{k}.usd": bench_usd(m["cost"]["usd_per_window"]),
                 f"F.eval.m.{k}.spent": bench_usd(m["cost"]["usd_all_attempts"])}
    fm, r = article("failures.json"), f["eval"]["replan"]
    late = {m["name"]: m["last_offer_h"] for m in fm["models"]}
    want |= {"F.eval.replan.rho": f"{-fm['corr']['last_offer_vs_C_models']:.2f}",
             "F.eval.replan.ah": f"{late[r['a']]:.1f}", "F.eval.replan.bh": f"{late[r['b']]:.1f}"}
    want |= leaves(beam_facts(article("beam.json"), s, fm), "F.beam")
    have = leaves(f)
    if bad := [f"{k} is {have.get(k)!r}, the results give {v!r}" for k, v in want.items() if have.get(k) != v]:
        raise SystemExit("facts.json does not match the benchmark's results, the failure charts' failures.json or the "
                         "Beam diagnosis's beam.json; run scripts/hub_article.py:\n  " + "\n  ".join(bad))
    return f


BEAM = "beam"
BEAM_DIR = "desk-v4-bench/beam-diagnosis"
BEAM_PLAYBOOK_DIR = "desk-v4-bench/beam-playbook"
BEAM_MINOR = ("as", "repair", "verbatim", "merge")
"""The changes worth less than the bound the section states: AS left out, refused submits repaired, and Beam's own
edits to what it copied, dropped or kept."""
ARTICLE_APP = "https://earakely-scale-gridsimenv.hf.space"


def beam_facts(b: dict, s: dict, fm: dict) -> dict:
    """The Beam-1.0 section's facts, which the card's section and the article's short one both state: beam.json's
    diagnosis (scripts/hub_article.py's beam_data), summary.json's run of the model and its references, and
    failures.json's last accepted offer, the measure the eval's re-planning finding states."""
    m, e, refs = s["models"][b["model"]], b["effects"], s["references"]
    late = next(x["last_offer_h"] for x in fm["models"] if x["key"] == b["model"])
    pts = lambda x: pc(x / 100, 1, True)  # noqa: E731
    ci = lambda x: f"[{pts(x['ci'][0])}, {pts(x['ci'][1])}]"  # noqa: E731
    share = lambda a, n: f"{pc(a / n, 0)}%"  # noqa: E731
    minor = math.ceil(max(abs(e[k]["mean"]) for k in BEAM_MINOR) * 2) / 2
    ident = "-".join(p.upper() if re.search(r"\d", p) and re.search(r"[a-z]", p) else p.capitalize()
                     for p in m["model_id"].split("-"))
    heading, seller = f"{m['name']} on GridSimEnv", re.search(r"at (.+?)'s list price", m["price_note"])[1]
    return {"name": m["name"], "id": ident, "provider": m["provider"], "setting": m["setting"], "seller": seller,
            "harness": f"{m['harness']} {m['harness_version']}", "server": m["server"], "framework": m["framework"],
            "n": str(b["windows"]), "days": NUM[int(s["unit"].split("-")[0])].lower(), "wakes": f"{b['wakes']:.0f}",
            "copied": share(b["dam_curve_hours"]["exact"], b["dam_curve_hours"]["compared"]),
            "physical": share(b["optimize"]["physical"], b["optimize"]["calls"]), "default": b["planner"]["default"],
            "position": b["planner"]["dam_position"], "risk": str(b["planner"]["risk"]),
            "question": pts(e["question"]["mean"]), "question_ci": ci(e["question"]),
            "storm": b["storm"]["name"], "storm_n": NUM[b["storm"]["windows"]].lower(),
            "calm": pts(e["calm"]["mean"]), "calm_ci": ci(e["calm"]), "late": f"{late:.1f}",
            "replan": pts(e["replan"]["mean"]), "replan_ci": ci(e["replan"]),
            "both": pts(e["both"]["mean"]), "both_ci": ci(e["both"]), "gap": pc(b["gap"] / 100),
            "share": share(e["both"]["mean"], b["gap"]), "minor": pc(minor / 100),
            "operator": f"{pc(refs['operator_replay']['all']['C']['mean'])}%",
            "planner": f"{pc(refs['anchor']['all']['C']['mean'])}%",
            "replay": bench_replay(b["model"], s["hero"]["task_id"]), "picker": f"{ARTICLE_APP}/#where-models-fail",
            "files": f"{DATASET}/tree/main/results/{BEAM_DIR}",
            "report": f"{DATASET}/blob/main/results/{BEAM_DIR}/report.md",
            "heading": heading, "card": f"{DATASET}#{slug(heading)}", "pb": beam_playbook_facts(b, s, pts, ci)}


PLAYBOOK_REF = "a4be130"
"""The plugin commit the section links the playbook and its pre-registration at: the run's record and result."""


def beam_playbook_facts(b: dict, s: dict, pts, ci) -> dict:
    """The playbook pilot as the Beam section states it: C, the paired difference from Beam's bench run over each
    scope, what changed in how Beam ran the desk, and the cost a window at the card's basis and as metered."""
    p, m = b["playbook"], s["models"][b["model"]]
    pct = lambda a, n: f"{pc(a / n)}%"  # noqa: E731
    out = {"C": f"{pc(p['C']['mean'] / 100)}%", "ci": f"[{pc(p['C']['ci'][0] / 100)}, {pc(p['C']['ci'][1] / 100)}]",
           "lines": str(p["lines"]), "storm": b["storm"]["name"],
           "spread": pct(*p["spread"]["after"]), "calls": f"{p['spread']['after'][1]:,}",
           "spread0": pct(*p["spread"]["before"]), "calls0": f"{p['spread']['before'][1]:,}",
           "late": f"{p['late_h']['after'][0]:.1f}", "late_med": f"{p['late_h']['after'][1]:.1f}",
           "late0": f"{p['late_h']['before'][0]:.1f}", "late0_med": f"{p['late_h']['before'][1]:.1f}",
           "usd": bench_usd(p["usd_list"]), "usd0": bench_usd(m["cost"]["usd_per_window"]),
           "metered": bench_usd(p["usd_metered"]["after"]), "metered0": bench_usd(p["usd_metered"]["before"]),
           "playbook": f"{REPO}/blob/{PLAYBOOK_REF}/bench/harness/bench-opencode-beam-playbook/PLAYBOOK.md",
           "prereg": f"{REPO}/blob/{PLAYBOOK_REF}/docs/prereg/v4-bench.md#"
                     f"{slug(m['name'] + ' with the desk playbook (exploratory, added after the bench)')}",
           "record": f"{REPO}/blob/{PLAYBOOK_REF}/docs/prereg/v4-bench.md#"
                     f"{slug('Deviations and run record, ' + m['name'] + ' with the desk playbook')}",
           "results": f"{DATASET}/blob/main/results/{BEAM_PLAYBOOK_DIR}/RESULTS.md",
           "files": f"{DATASET}/tree/main/results/{BEAM_PLAYBOOK_DIR}"}
    for k, x in p["scopes"].items():
        out[k] = {"d": pts(x["mean"]), "ci": ci(x), "n": str(x["windows"]), "ahead": str(x["ahead"]),
                  "fronts": str(x["fronts"]), "fronts_ahead": str(x["fronts_ahead"])}
    return out | {"move": beam_move(b, s, out)}


def beam_move(b: dict, s: dict, pb: dict) -> dict:
    """The before and after figure (hub/desk-charts' cost chart with a move): Beam-1.0 and Beam-1.0 with the playbook
    on the leaderboard's frontier, whose step line stays the leaderboard models'. The gap below the frontier at a
    point's own cost is the step line's C there (the costliest frontier model at most that cost) less its own."""
    pts = {x["key"]: x for x in s["plot"]["points"]}
    front = sorted((pts[k] for k in s["plot"]["frontier"]), key=lambda x: x["usd"])
    step = lambda usd: [x for x in front if x["usd"] <= usd][-1]  # noqa: E731
    a, p = pts[b["model"]], b["playbook"]
    usd, C = p["usd_list"], p["C"]["mean"] / 100
    lo, hi = step(a["usd"]), step(usd)
    if not (hi["C"]["mean"] > C and hi["usd"] < usd and hi["key"] in s["plot"]["frontier"]):
        raise SystemExit("the playbook point is no longer below the frontier and dominated: rewrite the caption")
    gap = [pc(lo["C"]["mean"] - a["C"]["mean"]), pc(hi["C"]["mean"] - C)]
    m = s["models"][b["model"]]
    name, seller = m["name"], re.search(r"at (.+?)'s list price", m["price_note"])[1]
    caption = (f"The arrow takes {name} from {pc(a['C']['mean'])}% at {bench_usd(a['usd'])} to {pb['C']} at "
               f"{pb['usd']} a window with the playbook, toward the cost frontier but still below it: at its own cost "
               f"the gap to the frontier narrows from {gap[0]} to {gap[1]} points, and {hi['name']} stays cheaper "
               f"and higher. The frontier and the other models are the leaderboard's; {name} + playbook is not a "
               f"leaderboard entry, and its playbook was written after seeing {name}'s failures on these same windows.")
    return {"from": b["model"], "usd": usd, "C": C, "label": f"{name} + playbook", "gap0": gap[0], "gap1": gap[1],
            "dominant": hi["name"], "title": f"{name} with the playbook: {pb['all']['d']} points, toward the frontier",
            "caption": caption, "notes": [f"{caption} Cost at {seller}'s list price."]}


def beam_move_figure(f: dict) -> str:
    """The before and after figure under the playbook's table, with its caption."""
    m = f["beam"]["pb"]["move"]
    alt = (f"The card's cost chart with the leaderboard's frontier, the other models faded: an arrow from "
           f"{f['beam']['name']} at {f['eval']['m']['beam']['C']} and {f['eval']['m']['beam']['usd']} to "
           f"{m['label']} at {f['beam']['pb']['C']} and {f['beam']['pb']['usd']}, still below the frontier, which "
           f"{m['dominant']} holds at a lower cost.")
    return "\n".join([*picture(f"{FIGS}/beam-move.svg", alt), "", f"<small>{m['caption']}</small>"])


def slug(heading: str) -> str:
    """A heading's anchor as the Hub's Markdown renders it: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


def leaves(f: dict, path: str = "F") -> dict[str, str]:
    out = {}
    for k, x in f.items():
        if isinstance(x, dict):
            out |= leaves(x, f"{path}.{k}")
        elif x is not None:
            out[f"{path}.{k}"] = x
    return out


def check_numbers(text: str) -> None:
    """The card's prose states no number of its own, as the article's chapters do not: every amount, cent, share and
    decimal outside code, tags and link targets is a {F.…} expression read from facts.json, or one of the reward's
    constants. The blocks take theirs from the results files."""
    prose = re.sub(r"\A---\n.*?\n---\n|```.*?```", "", text, flags=re.S)
    prose = FACT.sub("", re.sub(r"\]\([^)\s]*\)|<[^>]*>|`[^`]*`", "", prose))
    if bad := [n for n in NUMBER.findall(prose) if n.replace("⁠", "") not in CONSTANT]:
        raise SystemExit(f"{CARD.name} writes numbers into its prose; read them from facts.json: {bad}")


def fill(text: str, f: dict) -> str:
    known = leaves(f)
    if missing := sorted({e for e in FACT.findall(text) if e not in known}):
        raise SystemExit(f"{CARD.name} names facts that facts.json lacks: {', '.join(missing)}")
    return FACT.sub(lambda m: str(known[m[1]]), text)


def banned(text: str) -> None:
    if hits := [f"{m[0]!r}: {why}" for rx, why in BANNED for m in rx.finditer(text)]:
        raise SystemExit("the card says what it must not:\n  " + "\n  ".join(hits))


def build(runs_dir: Path, results_dir: Path, bundle_dirs: list[Path], plugin: str) -> dict[str, bytes]:
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
    for name in ("eval-v1.json", "board.md"):
        if (results_dir / name).is_file():
            files[f"results/{name}"] = (results_dir / name).read_bytes()
    files |= result_tables(json.loads((results_dir / RESULTS).read_text()), eval_runs())
    bundles = {}
    for path in bundle_dirs:
        bundles[path.name] = bundle_split(path.name)
        files |= dataset.build(runs.locate(str(path)), name=path.name, split=bundles[path.name],
                               which="latest").files
    return files | {"README.md": card_text(results_dir).encode()}


def write(files: dict[str, bytes], out: Path) -> None:
    for folder in MANAGED:
        shutil.rmtree(out / folder, ignore_errors=True)
    for path, content in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(content)


def card_only(results_dir: Path) -> str:
    return card_text(results_dir)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True, help="The folder to write, e.g. build/hub/dataset.")
    ap.add_argument("--runs", type=Path, default=ROOT / "results/runs",
                    help="A folder of gridsim.episode/v1 JSON, searched recursively; none there, no episodes.")
    ap.add_argument("--results", type=Path, default=ROOT / "results",
                    help="The folder with the sweep report's eval-v1.json and board.md and overview/results.json.")
    ap.add_argument("--bundle", type=Path, action="append", default=[],
                    help="A bundle folder to publish with agentenv-hf, named after its pack, e.g. "
                         "build/bundles/ercot-dam-v1-eval. Repeat for several.")
    ap.add_argument("--plugin-ref", default=f"v{VERSION}", help="The plugin tag the card's bundles pin.")
    ap.add_argument("--card-only", action="store_true",
                    help="Write README.md alone, every config as the card lists it.")
    ap.add_argument("--figures", action="store_true",
                    help="Also write the card's figures and the article's film: the article's charts from its build "
                         "(scripts/hub_article.py --build), the cost chart from hub/desk-charts, and the Try it Space "
                         "and the viewer as they are live.")
    args = ap.parse_args()
    figs = card_figures(args.results) if args.figures else {}
    scan(texts(figs), known_values())
    if args.card_only:
        files = {"README.md": card_only(args.results).encode()} | figs
        scan(texts(files), known_values())
        for path, content in files.items():
            (args.out / path).parent.mkdir(parents=True, exist_ok=True)
            (args.out / path).write_bytes(content)
            print(f"{len(content) / 1e3:9.1f} kB  {args.out / path}")
        return
    plugin = f"agentenv-gridsim @ git+{REPO}@{args.plugin_ref}"
    with namespace_routing():
        files = build(args.runs, args.results, args.bundle, plugin)
    scan(files, known_values())
    write(files | figs, args.out)
    for path in sorted(files):
        rows = f"{pq.read_metadata(io.BytesIO(files[path])).num_rows:7} rows" if path.endswith(".parquet") else ""
        if not path.startswith(("runs/", "bundles/")):
            print(f"{len(files[path]) / 1e6:9.2f} MB {rows:>12}  {path}")
    for top in ("runs/", "bundles/"):
        sized = [len(c) for p, c in files.items() if p.startswith(top)]
        if sized:
            print(f"{sum(sized) / 1e6:9.2f} MB {len(sized):7} files  {top}")
    print(f"into {args.out}")


def texts(files: dict[str, bytes]) -> dict[str, bytes]:
    """The files the key scan reads: the card and the SVGs, their embedded fonts left out."""
    return {k: re.sub(rb"base64,[\w+/=]+", b"base64,", v) for k, v in files.items() if k.endswith((".md", ".svg"))}


def card_figures(results_dir: Path) -> dict[str, bytes]:
    """The card's figures and the article's film, beside the card: the article's charts captured from its build, which
    must have been built from the chart data in this checkout; the cost chart as SVG; the Try it Space and the viewer
    as they are live; and the article's film GIF, which ships with the article, not the repository."""
    s, grades = bench_read(results_dir / "desk-v4-bench")
    f, dist = facts(s, grades), ARTICLE_APP / "dist"
    built = lambda n: (dist / "data" / n).is_file() and (dist / "data" / n).read_bytes() == (  # noqa: E731
        ARTICLE_DATA / n).read_bytes()
    if stale := [n for n in ("facts.json", "duel.json", "reward.json", "train.json", "failures.json", "bench.json")
                 if not built(n)]:
        raise SystemExit(f"{dist} is not built from this checkout's {', '.join(stale)}: scripts/hub_article.py --build")
    film = (ARTICLE_APP / "public/media/gridsim-run.gif").read_bytes()
    if film[:6] != b"GIF89a" or len(film) > 10e6:
        raise SystemExit("the article's film is not a GIF of at most 10 MB: scripts/hub_desk_film.py --out "
                         "hub/article/app/public/media/gridsim-run.gif")
    hr = module("hub_results", "scripts/hub_results.py")
    return {FILM: film, **embed_figures(dist, hr), **pareto_svgs(s, hr), **posters(f, hr)}


EMBEDS = {"before-after": ("before-after", 940, None), "reward": ("reward-window", CARD_W, None),
          "training": ("train-paired", CARD_W, None),
          **{f"fail-{k}": ("failure-modes", CARD_W, i) for i, (k, _, _) in enumerate(FAIL)}}
"""Each card figure from the article: its embed, the width it is captured at on a desktop (the before and after sets
its windows side by side from 900 px and keeps its labels on one line from 940, so it is captured there and shown at
the card's width), and for the failure modes, which of its charts."""
PHOTOS = ("before-after",)
CAPTURE = (':root, :root[data-theme="dark"] {{ --page-bg: {bg} !important; --surface-bg: {bg} !important; }} '
           "html, body {{ background: transparent !important; }} "
           "figure.card-cap {{ width: {w}px !important; max-width: none !important; min-width: 0 !important; "
           "margin: 0 !important; padding: 8px !important; box-sizing: content-box !important; "
           "transform: none !important; "
           "-webkit-mask: none !important; mask: none !important; }} "
           "figure.card-cap > :is(.html-embed__title, .html-embed__desc), figure.card-cap .html-embed__download, "
           ".card-cap :is(.ba-3d, details, .ba-foot a, .pick, .q, .how) {{ display: none !important; }} "
           "figure.card-cap > .html-embed__card {{ border: 0 !important; background: transparent !important; "
           "box-shadow: none !important; padding: 0 !important; }}")
"""The capture's page: the Hub's page colour behind the halos and nothing else, one figure at the width captured, and
none of what a picture cannot do: the title and caption the card prints itself, the tables behind a click, the links,
the model picker, and the failure charts' questions and notes, which the card prints above and below each chart."""
PICK = """(([id, css, panel]) => {
  document.getElementById('card-cap')?.remove();
  document.head.insertAdjacentHTML('beforeend', `<style id="card-cap">${css}</style>`);
  document.querySelectorAll('figure.card-cap').forEach((e) => e.classList.remove('card-cap'));
  const fig = document.getElementById(id).closest('figure');
  fig.classList.add('card-cap');
  [...fig.querySelectorAll('.gs-fail > div')].filter((e) => !e.className)
    .forEach((e, i) => { e.style.display = panel === null || i === panel ? '' : 'none'; });
  fig.scrollIntoView();
  return true;
})(%s)"""
SETTLE = ("new Promise((r) => setTimeout(r, 1200)).then(() => Promise.all([...document.querySelectorAll("
          "'figure.card-cap img')].map((i) => i.decode().catch(() => null))))")


def embed_figures(dist: Path, hr) -> dict[str, bytes]:
    """The article's charts as the card shows them: each embed of the built article on its own, in the article's light
    and dark themes on the Hub's page colours, at the card's width at 2x and at a phone's at 3x."""
    out = {}
    with hr.browser(dist, None) as (page, base):
        for phone, (width, scale) in ((False, (1440, 2)), (True, (390, 3))):
            page.call("Emulation.setDeviceMetricsOverride", width=width, height=1000, deviceScaleFactor=scale,
                      mobile=phone)
            page.call("Page.navigate", url=f"{base}/index.html")
            page.js("new Promise((r) => { const f = () => document.readyState === 'complete' ? "
                    "document.fonts.ready.then(() => setTimeout(r, 2500)) : setTimeout(f, 100); f(); })")
            page.call("Emulation.setDefaultBackgroundColorOverride", color={"r": 0, "g": 0, "b": 0, "a": 0})
            for sfx, theme, bg in hr.THEMES:
                page.js(f"document.documentElement.setAttribute('data-theme', '{theme}')")
                for name, (embed, w, panel) in EMBEDS.items():
                    page.js(PICK % json.dumps([embed, CAPTURE.format(bg=bg, w=PHONE_W if phone else w), panel]))
                    page.js(SETTLE)
                    box = page.js("(() => { const r = document.querySelector('figure.card-cap')"
                                  ".getBoundingClientRect(); return {x: r.x + scrollX, y: r.y + scrollY, "
                                  "width: r.width, height: r.height, scale: 1}; })()")
                    im = tight(base64.b64decode(page.call("Page.captureScreenshot", format="png",
                                                          captureBeyondViewport=True, clip=box)["data"]), bg, 6 * scale)
                    stem = f"{FIGS}/{name}{'-phone' if phone else ''}{sfx}"
                    out |= {f"{stem}.webp": encode(im, "WEBP", quality=90, method=6)} if name in PHOTOS else {
                        f"{stem}.png": encode(im, "PNG", optimize=True)}
            page.call("Emulation.setDefaultBackgroundColorOverride")
    return out


def tight(png: bytes, bg: str, pad: int) -> Image.Image:
    """A capture on the Hub's page colour, its empty rows above and below cut to pad pixels; its width kept, so every
    figure shows at one scale."""
    im = Image.open(io.BytesIO(png)).convert("RGBA")
    ground = Image.new("RGBA", im.size, bg)
    flat = Image.alpha_composite(ground, im).convert("RGB")
    _, y0, _, y1 = ImageChops.difference(flat, ground.convert("RGB")).getbbox()
    return flat.crop((0, max(0, y0 - pad), im.width, min(im.height, y1 + pad)))


def encode(im: Image.Image, fmt: str, **kw) -> bytes:
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


def pareto_svgs(s: dict, hr) -> dict[str, bytes]:
    """The article's cost chart (hub/desk-charts) as standalone SVG, its notes left to the card's caption, at the
    card's width and a phone's, light and dark, each theme's text halo the Hub's page colour."""
    web, out = ROOT / "src/agentenv_gridsim/web/desk", {}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        shutil.copytree(web / "fonts", root / "fonts")
        shutil.copy(web / "base.css", root / "base.css")
        for src in (ROOT / "hub/desk-charts").iterdir():
            shutil.copy(src, root / src.name)
        (root / "bench.json").write_text(json.dumps(s, ensure_ascii=False))
        with hr.browser(root, None) as (page, base):
            page.call("Emulation.setDeviceMetricsOverride", width=1000, height=900, deviceScaleFactor=2, mobile=False)
            page.call("Page.navigate", url=f"{base}/charts.html?notes=0&lead={CARD_W}&phone={PHONE_W}")
            page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.chartsReady ? r() : "
                    "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
            page.js("document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 400)))")
            for sfx, theme, bg in hr.THEMES:
                page.js(f"document.documentElement.dataset.theme = '{theme}'; "
                        f"document.documentElement.style.setProperty('--halo', '{bg}')")
                svgs = page.js("chartsSvg()")
                out |= {f"{FIGS}/pareto{sfx}.svg": svgs["bench-pareto"].encode(),
                        f"{FIGS}/pareto-phone{sfx}.svg": svgs["bench-pareto-phone"].encode()}
            move = article("facts.json")["beam"]["pb"]["move"] | {"notes": []}
            (root / "move.json").write_text(json.dumps(move, ensure_ascii=False))
            page.call("Page.navigate", url=f"{base}/charts.html?move=./move.json&lead={CARD_W}&phone={PHONE_W}")
            page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.chartsReady ? r() : "
                    "Date.now() - s > 30000 ? j('timeout') : setTimeout(f, 50); f(); })")
            page.js("document.fonts.ready.then(() => new Promise((r) => setTimeout(r, 400)))")
            for sfx, theme, bg in hr.THEMES:
                page.js(f"document.documentElement.dataset.theme = '{theme}'; "
                        f"document.documentElement.style.setProperty('--halo', '{bg}')")
                svgs = page.js("chartsSvg()")
                out |= {f"{FIGS}/beam-move{sfx}.svg": svgs["beam-move"].encode(),
                        f"{FIGS}/beam-move-phone{sfx}.svg": svgs["beam-move-phone"].encode()}
    return out


POSTER = {"desk": (1280, 800, 2, (CARD_W * 2, CARD_W * 5 // 4)), "phone": (390, 844, 3, None)}
"""Each poster's viewport and scale and the size it is stored at: a desktop view at twice the card's width, and a
phone's screen at 3x, of which each view keeps the top (KEEP)."""
KEEP = {"try-it": 844, "rollout": 600}


DRAWN = ("new Promise((r, j) => { const s = Date.now(); const docs = () => [document, ...[...document.querySelectorAll("
         "'iframe')].map((i) => { try { return i.contentDocument; } catch (e) { return null; } })].filter(Boolean); "
         "const f = () => document.readyState === 'complete' && docs().some((d) => d.querySelector('canvas')) ? "
         "setTimeout(r, 12000) : Date.now() - s > 180000 ? j('timeout') : setTimeout(f, 250); f(); })")
"""A live view is drawn when its page has loaded and a 3D canvas is up, in the page or a frame of it from the same
site, and has run a while."""


def posters(f: dict, hr) -> dict[str, bytes]:
    """The two live views the article frames, as they are now: the Try it Space's page as the article embeds it, on the
    article's window, and the viewer at the minute its rollout opens on, each in its light and dark theme, on a desktop
    and on a phone."""
    t = f["tryit"]
    views = {"try-it": t["app"] + "?__theme={theme}", "rollout": f["eval"]["watch"]["app"]}
    out = {}
    with tempfile.TemporaryDirectory() as tmp, hr.browser(Path(tmp), None) as (page, _):
        for name, url in views.items():
            for kind, (w, h, scale, size) in POSTER.items():
                for sfx, theme, _ in hr.THEMES:
                    page.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": theme}])
                    page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale,
                              mobile=kind == "phone")
                    page.call("Page.navigate", url=url.replace("{theme}", theme))
                    page.js(DRAWN)
                    keep = KEEP[name] if kind == "phone" else h
                    im = Image.open(io.BytesIO(base64.b64decode(page.call("Page.captureScreenshot", format="png", clip={
                        "x": 0, "y": 0, "width": w, "height": keep, "scale": 1})["data"])))
                    out[f"{FIGS}/{name}{'-phone' if kind == 'phone' else ''}{sfx}.webp"] = encode(
                        im.resize(size, Image.LANCZOS) if size else im, "WEBP", quality=86, method=6)
    return out


if __name__ == "__main__":
    main()
