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

The card is hub/dataset/README.md, the desk's card, with its blocks filled in from
results/overview/desk.json (scripts/hub_desk.py writes it and the desk's tables); the v1 tables stay in the
repo outside every config. --card-only writes the card alone. Every file goes through agentenv-hf's scan for keys
and token shapes before anything is written. Nothing is pushed: upload the folder with
`hf upload <repo> <out> --repo-type dataset` after reading it.

    uv run python scripts/hub_dataset.py --out build/hub/dataset
    uv run python scripts/hub_dataset.py --out build/hub/card --card-only
    agent-env gridsim tasks generate --pack ercot-dam-v1-eval --out build/bundles/ercot-dam-v1-eval
    uv run python scripts/hub_dataset.py --out build/hub/dataset --runs results/runs --results results \
        --bundle build/bundles/ercot-dam-v1-eval
"""

import argparse
import gzip
import importlib.util
import io
import json
import re
import shutil
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

from gridsim_core.episode import SCHEMA
from gridsim_core.grade import grade
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
    f'<a href="{VIEWER}"><img src="https://img.shields.io/badge/%F0%9F%A4%97%20Space-Every%20run%2C%20version%20by'
    '%20version-FFD21E?style=for-the-badge&labelColor=1a1a1a" alt="The viewer Space: every run, version by version" '
    'height="32"></a>',
    '<a href="https://github.com/earakely-scale/agentenv-gridsim-plugin"><img src="https://img.shields.io/badge/GitHub-'
    'agentenv--gridsim--plugin-181717?style=for-the-badge&logo=github&labelColor=1a1a1a" alt="Code on GitHub" '
    'height="32"></a>',
    '<a href="https://www.agentenvframework.com"><img src="https://img.shields.io/badge/framework-AgentEnv-6f42c1?'
    'style=for-the-badge&labelColor=1a1a1a" alt="AgentEnv Framework" height="32"></a>')
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


def desk_blocks(d: dict, bench: tuple[dict, list[dict]] | None = None, gif: bool = False) -> dict[str, str]:
    """The card's blocks: the v4 benchmark first, from results/desk-v4-bench/ alone (its pitch, lead GIF, charts,
    table, how it runs and its limitations), then the earlier versions folded, from results/overview/desk.json
    (scripts/hub_desk.py writes it): the results across the ladder's versions, each version's results and the
    price-impact check; then the quick start, the versions, the configs and files, and the line to the archived v1."""
    vs = ladder(d)
    results = [f"<details>\n<summary><b>{v['version']}, {v['name']}</b>: the results</summary>\n\n"
               f"{desk_results(v, d)}\n\n</details>" for v in reversed(vs)]
    checked = [f"<details>\n<summary><b>{v['version']}, {v['name']}</b>: a price-impact check on {v['check_of']}"
               f"</summary>\n\n{price_check(v, d)}\n\n</details>" for v in checks(d)]
    earlier = "\n\n".join([across(d), *results, *checked])
    quick = QUICKSTART.replace("{bench}", BENCH_QUICKSTART + "\n\n" if bench else "").replace(
        "{bench_table}", BENCH_TABLE if bench else "").replace("{latest}", vs[-1]["version"])
    if bench:
        quick = quick.replace("{deviations}", bench_deviations(bench[0]))
    blocks = {"badges": "\n".join(BADGES), "quickstart": quick,
              "ladder": ladder_block(d), "models": models_block(d), "inside": inside(d, bench), "archive": ARCHIVE}
    if bench is None:
        return blocks | {"pitch": "", "gif": gif_block(d["gif"]), "bench": "", "earlier": f"## Results\n\n{earlier}",
                         "bench-rule": ""}
    s, grades = bench
    return blocks | {"pitch": bench_pitch(s), "gif": bench_gif(s, grades, gif),
                     "bench": "## The v4 benchmark: models in native agent harnesses\n\n"
                              + bench_block(s, grades, d),
                     "earlier": "## Earlier versions\n\n<details>\n<summary><b>v2 to v4 on the desk's own runner, and "
                                "the v5 price-impact check</b></summary>\n\n" + earlier + "\n\n</details>",
                     "bench-rule": f"- **Which half of the benchmark leads.** {s['text']['rule']}"}


BENCH_DIR = "results/desk-v4-bench"
BENCH_GIF = "assets/gridsim-desk-bench.gif"
BENCH_SPLITS = ("pre_cutoff", "post_cutoff")
BENCH_SIDE = {"pre_cutoff": "may be in training data", "post_cutoff": "after every cutoff"}
BENCH_REFS = {"operator_replay": "The real operator's bids, replayed", "anchor": "The anchor, the desk's own optimiser"}
NOT_YET_IN_VIEWER = ("argon",)
BENCH_WHEN = {"pre_cutoff": "a window that may be in the models' training data",
              "post_cutoff": "after every model's training cutoff"}
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
    n, opened = len(ms), [m for m in ms if m["weights"] == "open"]
    used = [*dict.fromkeys(m["harness"] for m in ms if m["weights"] != "open"),
            *(f"{m['harness']} for the open {m['name']}" for m in opened)]
    harnesses = used[0] if len(used) == 1 else f"{', '.join(used[:-1])}, and {used[-1]}"
    return "\n\n".join([f"**{NUM.get(n, n)} models in native agent harnesses ({harnesses}) run a real ERCOT battery's "
                        f"trading desk for three days at a time across {s['n_fronts']} real Texas weather fronts, "
                        "graded in dollars against the hindsight optimum and the battery's real operator.**",
                        *([FAKE] if s["fake"] else [])])


def bench_gif(s: dict, grades: list[dict], attached: bool) -> str:
    """The lead GIF: the best-looking run of the model with the highest C (summary.json's `hero`), its caption from
    that run's grade, with links to that run and to each other model's run of its window in the viewer Space's 3D
    replay; without the GIF file, the slot it fills."""
    h = s.get("hero")
    if not h:
        return ""
    g = next(r for r in grades if r["model"] == h["model"] and r["task_id"] == h["task_id"])
    m, front = s["models"][h["model"]], next(f for f in s["fronts"] if f["front"] == g["front"])
    where, when = f"Battery {g['site']} ({g['region']}, {g['battery']})", long_(
        {"days_per_task": len(g["dates"])}, g["dates"][0])
    others = [f"[{x['name']}]({bench_replay(x['key'], h['task_id'])})" for x in bench_models(s)
              if x["key"] != h["model"] and x["key"] not in NOT_YET_IN_VIEWER]
    caption = (f"The v4 benchmark: {m['name']} in {m['harness']} trades {where}, a real ERCOT battery, over {when}, "
               f"through a {front['kind']}, {BENCH_WHEN[g['split']]}. It settles at {usd0(g['p'])}, hindsight "
               f"capture C {pc(g['capture'])}%"
               + (f"; the real operator's own bids, replayed, earn {usd0(g['p_operator_replay'])}"
                  if g["p_operator_replay"] is not None else "")
               + f". [Replay it in 3D]({bench_replay(h['model'], h['task_id'])})"
               + (f", or watch {' or '.join([', '.join(others[:-1]), others[-1]] if len(others) > 1 else others)} "
                  "trade the same window" if others else "")
               + f". [Its Episode JSON]({DATASET}/blob/main/{BENCH_DIR}/{g['episode']}). Data: ERCOT and NWS, "
               "public; not affiliated with or endorsed by ERCOT.")
    if not attached:
        return "\n".join([f"> **Lead GIF slot.** {caption}", ">",
                          f"> Filmed from `{BENCH_DIR}/{g['episode']}` by `scripts/hub_desk_hero.py`: the best-looking "
                          f"run of the model with the highest C by its ranking ({h['why']})."])
    alt = (f"{m['name']} at the desk of {where} over {when}: the node's prices as they post, the battery's state of "
           "charge and dispatch, and each wake-up's tool calls with their results, then the settled grade")
    return "\n".join([f'<a href="{bench_replay(h["model"], h["task_id"])}"><img src="{BENCH_GIF}" '
                      f'alt="{escape(alt)}" width="100%"></a>', "", f"<small>{caption}</small>"])


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
            f"{bench_usd(c['usd_per_window'])} a window" + (", GPU time" if c["basis"] == "gpu_time" else ""),
            f"{bench_usd(c['usd_all_attempts'])} in all"]
        return (f"**{m['name']}**<br><small>{m['harness']} · {m['setting']}<br>"
                + " · ".join(cost + ([] if n == s["n_windows"] else [f"{n} of {s['n_windows']} windows"]))
                + "</small>")

    rows = [f"| {who(m)} | " + " | ".join(cell(m[c]["C"], c == cols[0]) for c in cols) + " |" for m in ms]
    rows += [f"| *{BENCH_REFS[k]}* | " + " | ".join(f"*{pc(refs[k][c]['C']['mean'])}%*" for c in cols) + " |"
             for k in BENCH_REFS]
    gpu = next((m["cost"]["gpu"] for m in ms if m["cost"].get("gpu")), None)
    op = refs["operator_replay"]
    alt = ("Line chart of hindsight capture C, as a percentage of the hindsight optimum's profit over idle, before and "
           "after the training cutoffs, one line per model: " + "; ".join(
               f"{m['name']} in {m['harness']} {pc(m['pre_cutoff']['C']['mean'])}% then "
               f"{pc(m['post_cutoff']['C']['mean'])}%" for m in ms if m["n"])
           + f"; the real operator's bids, replayed, {pc(op['pre_cutoff']['C']['mean'])}% then "
           f"{pc(op['post_cutoff']['C']['mean'])}%.")
    sides = " and ".join(f"{bench_side(s, x)} ({BENCH_SIDE[x]})" for x in BENCH_SPLITS)
    return "\n".join([
        *chart("splits", alt, charts["lead"], charts["phone"]["media"], f"{BENCH_DIR}/figures"), "",
        "<small>C × 100: the share of the hindsight optimum's profit over idle that each model captured, its mean over "
        f"the windows it finished on each side of the models' reported training cutoffs, {sides}; 95% CIs, a block "
        f"bootstrap over the {s['n_fronts']} fronts, are in the table below. Grey dashed: the real operator's own "
        "bids, replayed through the same clearing and settlement.</small>",
        "", "| Model | " + " | ".join(head[c] for c in cols) + " |", "|---|" + "---:|" * len(cols), *rows, "",
        f"<small>C, hindsight capture, %. Brackets: 95% CIs, a block bootstrap over the {s['n_fronts']} weather fronts "
        "(four within each side of the cutoffs). Cost a window: the graded attempt's tokens in its harness's own "
        "trajectory at the provider's public list price"
        + (f"; {and_join([m['name'] for m in ms if m['cost'].get('gpu')])}'s is {gpu['note']}" if gpu else "")
        + "; in all: every attempt, retries and stalls included." + (f" {s['text']['metered']}" if s[
            "text"].get("metered") else "") + " The "
        "anchor is the desk's own optimiser re-planning at every wake on the same information; the operator row "
        "replays the real operator's bids, disclosed by ERCOT 60 days later, through the same clearing and "
        "settlement." + "".join(
            f" {m['name']} ran" + (" after the others," if all(m["ran"]["from"] > x["ran"]["to"] for x in ms
                                                              if x is not m) else "")
            + f" on agentenv-framework {m['framework']}"
            + (f"; see the [deviations]({bench_deviations(s)})" if bench_deviations(s) else "") + "."
            for m in ms if m.get("framework")) + "</small>", "",
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
    harnesses = and_join([f"{and_join([m['name'] for m in xs])} in {h}" + (f" {v}" if v else "")
                          + (f" {note}" if note else "") for (h, v, note), xs in by.items()])
    open_ = [m for m in ms if m["weights"] == "open" and m["cost"].get("gpu")]
    budget, ref = run.get("budget") or {}, run.get("bundle") or "main"
    return [
        f"**Each model in a native agent harness,** through AgentEnv: {harnesses}"
        + (f"; {and_join([m['name'] for m in open_])} served by {open_[0].get('server') or 'vLLM'} on "
           f"{open_[0]['cost']['gpu']['where']}" if open_ else "") + ".",
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


def bench_limits(s: dict) -> list[str]:
    """The benchmark's known limitations, as the pre-registration discloses them for the route the runs took."""
    harnesses = {m["harness"] for m in s["models"].values()}
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
        "**The training cutoffs are third-party reports, unconfirmed.** The pre-cutoff half reuses v4's 16 windows, "
        "which GPT-6.1 Sol, GPT-6 Luna and Qwen3-4B also played on the desk's own runner (below).",
        "**One run per model per window over eight fronts,** so the CIs are wide, and a single scarcity front can "
        "carry a model's dollars.",
        "**Cost is list price:** tokens at each provider's public price per million, without batch or volume "
        "discounts or long-context surcharges; the open model's cost is its share of the GPU time.",
        "**A known env defect, K1, in the benchmark too.** An empty reserve-offer list drew a spurious ASO-02 note "
        "while the energy curves in the same call were accepted and applied; there is no settlement effect. It is "
        "fixed on the head; the frozen runs keep it, and the benchmark plays v4's freeze."]


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
        + ("; `results/desk-v4-bench/` holds the benchmark's README, `summary.json` (every number on this card's "
           "benchmark section), `grades.jsonl.gz`, figures and every scored Episode JSON" if bench else "")
        + "; `assets/` holds the desk GIFs and this card's charts."])


QUICKSTART = """In process, with no Docker and no model key, play the anchor policy on v2's two pilot battery-days:

```bash
git clone https://github.com/earakely-scale/agentenv-gridsim-plugin
cd agentenv-gridsim-plugin && uv sync --extra dev
uv run python scripts/desk_run.py --pack desk-v2-pilot --policy anchor --out runs/anchor
```

Each run writes every task's Episode JSON and a results row with its grade. `--policy model --model NAME --base-url URL`
plays any model behind an OpenAI-compatible endpoint the same way, with its key in `DESK_API_KEY`, and every version's
packs are under `data/desk/`. On AgentEnv, after `agent-env gridsim setup`, `scripts/desk_e2e.py` plays a task through
the gateway env, its post-turn hook and its verifier, and checks it against the in-process run byte for byte.

{bench}The tables:

```python
from datasets import load_dataset

repo = "earakely-scale/GridSimEnv-AgentEnv"
{bench_table}board = load_dataset(repo, "desk_leaderboard", split="{latest}")  # each model and reference, with CIs
runs = load_dataset(repo, "desk_runs", split="{latest}")          # each model's every task
tasks = load_dataset(repo, "desk_tasks", split="{latest}")        # every task, its site card and references
```"""
BENCH_QUICKSTART = """The v4 benchmark's runs are each a plain `agent-env run` of a bundle that `scripts/desk_bench.py`
writes for one harness (`claude-code`, `codex-sol`, `codex-luna`, `gemini` or `opencode-qwen`), with a
`.agentenv/config.toml` that names the model endpoint and its key. By default the bundle's network allowlist holds
only the harness vendor's API host, for a sandbox provider that enforces it, such as Modal, which the bundle was built
for. Our runs took route C instead: local Docker on EC2 boxes, with a host egress rule and a per-run model proxy
([deviations]({deviations})):

```bash
uv run python scripts/desk_bench.py tasks --harness codex-luna --pack desk-v4-bench --out bundles/bench-codex-luna
uv run agent-env run bundles/bench-codex-luna --task desk-v4-2026-07-04-S01
```"""
BENCH_TABLE = ('bench = load_dataset(repo, "desk_v4_bench", split="post_cutoff")  '
               "# the benchmark, each model's every window\n")
ARCHIVE = ("GridSimEnv v1 (one-shot day-ahead schedule, training results) is archived at revision "
           f"[6ae10fcc]({DATASET}/tree/6ae10fcc7fea8037716a0ea7f4ef761786a34f87).")


def ladder_block(d: dict) -> str:
    done, lad, chk = {v["version"]: v for v in d["versions"]}, [x["version"] for x in d["ladder"]], checks(d)
    rows = [f"| **{x['version']}, {x['name']}**<br><small>" + (
        f"{done[x['version']]['n_tasks']} {unit(done[x['version']])}s, results above" if x["version"] in done
        else "next")
        + f"</small> | {md(x['adds'])} | {md(x['does'])} |" for x in d["ladder"]] + [
        f"| **{v['version']}, {v['name']}**<br><small>a price-impact check on {v['check_of']}'s {v['n_tasks']} "
        f"{unit(v)}s, results above</small> | {md(v['adds'])} | {md(v['does'])} |" for v in chk]
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
        f"[{v['version']}'s results page]({APP}/results.html?v={v['version']}) in the viewer lists every "
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


NUM = {1: "One", 2: "Two", 3: "Three", 4: "Four", 5: "Five", 6: "Six", 7: "Seven", 8: "Eight"}


def and_join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


BUYBACK = ("day-ahead sales bought back in real time: positions the DAM allows because it ignores state of charge, and "
           "which ERCOT's DAM credit screening, not modelled here, would limit")
SHORTS = {"anchor": "the anchor", "operator_replay": "the operator's bids",
          "operator_actual": "the operator as settled"}


def gif_block(gif: dict) -> str:
    return "\n".join([f'<a href="{gif["link"]}"><img src="{gif["path"]}" alt="{escape(gif["alt"])}" width="100%"></a>',
                      "", f"<small>{gif['caption']}</small>"])


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


def card_text(results_dir: Path, gif: bool = False) -> str:
    """The desk's card: hub/dataset/README.md with each block filled in, the v4 benchmark's from
    results/desk-v4-bench/ and the rest from results/overview/desk.json, and the desk's configs as the only ones; the
    v1 files stay in the repo, outside every config. `gif`: the benchmark's lead GIF ships beside the card."""
    d = json.loads((results_dir / DESK).read_text())
    bench = bench_read(results_dir / "desk-v4-bench")
    text = CARD.read_text()
    for name, block in desk_blocks(d, bench, gif).items():
        text, n = re.subn(rf"^<!-- {name} -->$", lambda m, b=block: b, text, flags=re.M)
        if n != 1:
            raise SystemExit(f"{CARD} has no <!-- {name} --> line")
    out = DatasetCard(re.sub(r"\n{3,}", "\n\n", text))
    out.data.configs = desk_configs(d, bench)
    return str(out)


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


def card_only(results_dir: Path, gif: bool = False) -> str:
    return card_text(results_dir, gif)


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
    args = ap.parse_args()
    if args.card_only:
        files = {"README.md": card_only(args.results).encode()}
        scan(files, known_values())
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "README.md").write_bytes(files["README.md"])
        print(f"{len(files['README.md']) / 1e3:.1f} kB  {args.out / 'README.md'}")
        return
    plugin = f"agentenv-gridsim @ git+{REPO}@{args.plugin_ref}"
    with namespace_routing():
        files = build(args.runs, args.results, args.bundle, plugin)
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
    print(f"into {args.out}")


if __name__ == "__main__":
    main()
