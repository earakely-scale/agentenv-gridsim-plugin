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

The card is hub/dataset/README.md with its results sections and row counts filled in from
results/overview/results.json (scripts/hub_results.py writes that file, the figures and their captions) and the
bundles' configs. The v1 board and the v2 to v5 previews are kept as the card has them: their tables and boards are
built on the previews branch. --card-only writes the card alone. Every file goes through agentenv-hf's scan for keys
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
from agentenv_hf.card import card
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
ELSEWHERE = ("v2_", "v3_", "v4_", "v5_", "desk_")
RESULTS = "overview/results.json"
DESK = "overview/desk.json"
DESK_MD = ROOT / "hub/dataset/desk.md"
DESK_RUN = ROOT / "hub/dataset/desk-run.md"
DESK_BADGE = (f'<a href="{APP}/desk.html"><img src="https://img.shields.io/badge/%F0%9F%93%88%20Desk-A%20live%20ERCOT%20'
              'battery%20desk-2a78d6?style=for-the-badge&labelColor=1a1a1a" alt="The desk: a live ERCOT battery desk" '
              'height="32"></a>')
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


def desk_blocks(d: dict) -> dict[str, str]:
    """The card's desk section, its quick start and, when the desk's hero GIF leads the card, the lead; from
    results/overview/desk.json (scripts/hub_desk.py writes it). The newest version's results are open, earlier ones
    fold; a desk GIF that does not lead opens the desk section instead."""
    vs, latest, gif = d["versions"], d["versions"][-1], d.get("gif")
    results = [desk_results(v) for v in reversed(vs)]
    results[1:] = [f"<details>\n<summary><b>{v['version']}, {v['name']}</b>: the results</summary>\n\n{r}\n\n"
                   "</details>" for v, r in zip(reversed(vs[:-1]), results[1:], strict=True)]
    inline = f"{gif_block(gif)}\n\n" if gif and not gif["lead"] else ""
    desk = DESK_MD.read_text().format(gif=inline, ladder=ladder_block(d), results="\n\n".join(results),
                                      across=across(d))
    out = {"desk": desk.rstrip(), "desk-run": DESK_RUN.read_text().format(ref=latest["ref"],
                                                                          latest=latest["version"]).rstrip()}
    if gif and gif["lead"]:
        out["hero"] = gif_block(gif)
    n = {k: sum(v["rows"][k] for v in vs) for k in ("leaderboard", "runs")}
    splits = ", ".join(f"`{v['version']}`" for v in vs)
    out["desk-configs"] = (
        f"  The desk's configs: **`desk_leaderboard`** ({n['leaderboard']:,} rows), each model and reference of each "
        "desk version with its C, P, R and paired gaps and their CIs, cost and how it traded; and **`desk_runs`** "
        f"({n['runs']:,} rows), each model's every battery-day with its grade, every statement line, usage and its "
        f"Episode JSON's path under `results/desk-v<N>/`. One split per version: {splits}.")
    return out


def ladder_block(d: dict) -> str:
    done = {v["version"]: v for v in d["versions"]}
    rows = [f"| **{x['version']}, {x['name']}**<br><small>" + (
        f"{done[x['version']]['n_tasks']} {unit(done[x['version']])}s, results above" if x["version"] in done
        else "next")
        + f"</small> | {md(x['adds'])} | {md(x['does'])} |" for x in d["ladder"]]
    return "\n".join(["**The version ladder.** Each version adds one kind of realism to the same desk, tools and "
                      "grading.", "", "| Version | What it adds | What the agent does |", "|---|---|---|", *rows])


def desk_results(v: dict) -> str:
    sites = ", ".join(f"{s['region']} {s['size']}" for s in v["sites"])
    a, b = (f"{date.fromisoformat(x):%-d %B %Y}" for x in v["dates"])
    rows = [desk_row(m) for m in v["models"]] + [
        f"| *{r['short']}* | *{h(r['C']['mean'])}* | *{usdk(r['P']['mean'])}* |"
        for r in v["references"] if r["key"] != "idle" or abs(r["P"]["mean"]) >= 0.5]
    gaps = [f"| **{m['name']}** | "
            + ("–" if m["P_minus_operator_replay"]["mean"] is None else stacked_usd(m["P_minus_operator_replay"], True))
            + f" | {stacked_usd(m['P_minus_anchor'], True)} |" for m in v["models"]]
    fig = f"assets/figures/desk-{v['version']}-capture"
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
        f"**How much of the hindsight optimum each desk captured, {v['version']}**", "",
        f'<img class="dark:hidden" src="{fig}.png" alt="{escape(capture_alt(v))}">',
        f'<img class="hidden dark:block" src="{fig}-dark.png" alt="{escape(capture_alt(v))}">', "",
        "<small>C with its 95% CI for each model, the anchor and the real operator; idle is 0 and the hindsight "
        "optimum 1 by definition.</small>", "", *(f"- {x}" for x in desk_bullets(v)), "",
        f"Every number is in [`{v['folder']}`]({DATASET}/tree/main/{v['folder']}) (its README, `summary.json`, "
        "`grades.jsonl.gz`, every Episode JSON and run log) and in the `desk_leaderboard` and `desk_runs` configs, "
        f"split `{v['version']}`; the code is the [`{v['ref']}`]({v['github']}) tag of the plugin."])


def last(v: dict) -> str:
    return f"{date.fromisoformat(v['dates'][1]) + timedelta(days=v['days_per_task'] - 1):%-d %B %Y}"


def desk_row(m: dict) -> str:
    cost = m["usd_per_episode"]
    sub = ([f"{m['effort']} effort"] if m.get("effort") else ["open weights"] if m["weights"] == "open"
           else []) + ([f"${cost:.2f} a run"] if cost and m["weights"] != "open" else [])
    return (f"| **{m['name']}**<br><small>{' · '.join(sub)}</small> | **{h(m['C']['mean'])}**<br><small>"
            f"{ci(m['C']['ci'])}</small> | {stacked_usd(m['P'])} |")


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
    out += sensitivity(v) + reserves(v) + dam_days(v) + impact(v) + versus(v)
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


def impact(v: dict) -> list[str]:
    """v5: what the desk's own DAM offers did to the price they cleared at, from the report's re-clear."""
    pi = v.get("price_impact")
    if not pi:
        return []
    ms = {m["key"]: m["name"] for m in v["models"]}
    name = lambda k: ms.get(k, SHORTS.get(k, k))  # noqa: E731
    keys = [k for k in [*ms, "anchor"] if k in pi]
    cents = lambda x: f"{'−' if x < 0 else '+' if x > 0 else ''}{abs(x) * 100:.1f}¢"  # noqa: E731
    big = max(pi[k]["max_abs_usd_per_mwh"] for k in keys)
    return ["**One battery moves the DAM price by cents.** Re-clearing the DAM against the day's real offers with "
            "each desk's own moves the node's price on its sales, MWh-weighted over its awarded hours, by: "
            + "; ".join(
                f"{name(k)} {cents(pi[k]['sales_mwh_weighted_usd_per_mwh'])}/MWh" for k in keys)
            + f". The largest single move is ${big:.2f}/MWh; on revenue it is worth " + and_join(
                [f"{name(k)} {usd0(pi[k]['revenue_effect_usd_per_episode'], True)}" for k in keys])
            + f" a {unit(v)}. A single 100–150 MW battery is a price taker here, so {v['version']} matches "
            f"{(v.get('versus') or {}).get('label', 'v3')} by construction of the market, as pre-registered. A next "
            "step is a portfolio desk: a QSE bidding its whole fleet of batteries into the DAM at once."]


def versus(v: dict) -> list[str]:
    """v5: each model's paired gap to the version it repeats, on the same tasks."""
    vs = v.get("versus")
    if not vs:
        return []
    ms = {m["key"]: m["name"] for m in v["models"]}
    gaps = "; ".join(f"{ms.get(k, k)} {usd0(b['P']['mean'], True)} {usd0_ci(b['P']['ci'], True)}"
                     for k, b in vs["models"].items())
    noise = all(b[x]["ci"][0] <= 0 <= b[x]["ci"][1] for b in vs["models"].values() for x in ("P", "R", "C"))
    return [f"**{v['version']} against {vs['label']},** paired on the same {v['n_tasks']} {unit(v)}s, P a {unit(v)}: "
            f"{gaps}." + (" Every P, R and C gap has a CI that includes zero: two runs of the same model differ "
                          "this much, while the price moved by cents." if noise else "")]


def across(d: dict) -> str:
    """The models' C version by version, and what the paired gaps between them say."""
    vs = d["versions"]
    if len(vs) < 2:
        return ""
    keys = list(dict.fromkeys(m["key"] for v in vs for m in v["models"]))
    names = {m["key"]: m["name"] for v in vs for m in v["models"]}
    cell = lambda v, k: next((f"{h(m['C']['mean'])}<br><small>{ci(m['C']['ci'])}</small>" for m in v["models"]  # noqa: E731
                              if m["key"] == k), "–")
    rows = [f"| **{names[k]}** | " + " | ".join(cell(v, k) for v in vs) + " |" for k in keys]
    return "\n".join(["**Across versions:** hindsight capture C, with its 95% CI.", "",
                      "| Desk | " + " | ".join(f"{v['version']}, {v['name']}" for v in vs) + " |",
                      "|---|" + "---:|" * len(vs), *rows, "", across_text(d)])


def across_text(d: dict) -> str:
    """Where the paired C gap between GPT-6.1 Sol and GPT-6 Luna excludes zero, and whether the untrained model is
    last in every version."""
    vs, out = d["versions"], []
    keys = {m["key"] for v in vs for m in v["models"]}
    pair = lambda v, a, b: next((x["C"] for x in v["paired"] if {x["a"], x["b"]} == {a, b} and "C" in x), None)  # noqa: E731
    if {"sol", "luna"} <= keys:
        clear = [v for v in vs if (g := pair(v, "sol", "luna")) and (g["ci"][0] > 0 or g["ci"][1] < 0)]
        rest = [v["version"] for v in vs if v not in clear]
        out.append("Paired by task, GPT-6.1 Sol and GPT-6 Luna differ in C with a CI that excludes zero only in "
                   + and_join([f"{v['version']}" + (f", on {v['days_per_task']}-day weather fronts"
                                                     if v["days_per_task"] > 1 else "") for v in clear])
                   + f" (Sol ahead); in {and_join(rest)} they are close." if clear else
                   "Paired by task, GPT-6.1 Sol and GPT-6 Luna never differ in C with a CI that excludes zero.")
    if "qwen" in keys and all(min(v["models"], key=lambda m: m["C"]["mean"])["key"] == "qwen" for v in vs):
        out.append("The untrained Qwen3-4B has the lowest C in every version.")
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


NUM = {2: "Two", 3: "Three", 4: "Four", 5: "Five"}


def and_join(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else f"{', '.join(xs[:-1])} and {xs[-1]}"


BUYBACK = ("day-ahead sales bought back in real time: positions the DAM allows because it ignores state of charge, and "
           "which ERCOT's DAM credit screening, not modelled here, would limit")
SHORTS = {"anchor": "the anchor", "operator_replay": "the operator's bids",
          "operator_actual": "the operator as settled"}


def capture_alt(v: dict) -> str:
    rows = [(m["name"], m["C"]) for m in v["models"]] + [
        (r["short"], r["C"]) for r in v["references"] if r["key"] not in ("hind", "idle")]
    return (f"Hindsight capture on {v['pack']}, with 95% CIs: "
            + "; ".join(f"{n} {h(c['mean'])} {ci(c['ci'])}" for n, c in rows) + ". Idle is 0, the hindsight optimum 1.")


def gif_block(gif: dict) -> str:
    return "\n".join([f'<a href="{gif["link"]}"><img src="{gif["path"]}" alt="{escape(gif["alt"])}" width="100%"></a>',
                      "", f"<small>{gif['caption']}</small>"])


def usd0(x: float, sign: bool = False) -> str:
    v = f"{abs(x):,.0f}"
    return f"{'' if v == '0' else '−' if x < 0 else '+' if sign else ''}\u2060${v}"


def usd0_ci(c: list[float], sign: bool = False) -> str:
    return f"[{usd0(c[0], sign)}, {usd0(c[1], sign)}]"


def desk_configs(d: dict) -> list[dict]:
    return [{"config_name": f"desk_{name}", "data_files": [
        {"split": v["version"], "path": f"desk_{name}/{v['version']}.parquet"} for v in d["versions"]]}
        for name in ("leaderboard", "runs")]


def eval_runs() -> dict[str, list[dict]]:
    """Every schedule behind the leaderboard, as scripts/hub_results.py re-grades them from the committed records."""
    spec = importlib.util.spec_from_file_location("hub_results", ROOT / "scripts/hub_results.py")
    hr = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hr)
    return hr.eval_runs(BEAM)


def card_text(files: dict[str, bytes] | None, bundles: dict[str, str], plugin: str, results_dir: Path) -> str:
    """The card with its results blocks and counts filled in from results.json, and each bundle's configs and needs as
    agentenv-hf writes them. Given the files this build wrote, v1_episodes lists the splits that have episodes and a
    v1 config whose tables are all empty is left off (`datasets` can't load a parquet file with no rows); the previews'
    configs stay as the card lists them, since their tables are built on the previews branch, and so do the desk's,
    which scripts/hub_desk.py builds. Without files, every config stays as listed."""
    text = CARD.read_text()
    if (results_dir / RESULTS).is_file():
        r = json.loads((results_dir / RESULTS).read_text())
        for name, block in results_blocks(r).items():
            text, n = re.subn(rf"(<!-- {name} -->\n).*?([ \t]*<!-- /{name} -->)",
                              lambda m, b=block: f"{m[1]}{b}\n{m[2]}", text, flags=re.S)
            if n != 1:
                raise SystemExit(f"{CARD} has no <!-- {name} --> block")
        values = counts(r)
        text = re.sub(r"<!-- =(\w+) -->", lambda m: values[m[1]], text)
    desk = json.loads((results_dir / DESK).read_text()) if (results_dir / DESK).is_file() else None
    if desk and desk["versions"]:
        for name, block in desk_blocks(desk).items():
            text, n = re.subn(rf"(<!-- {name} -->\n).*?([ \t]*<!-- /{name} -->)",
                              lambda m, b=block: f"{m[1]}{b}\n{m[2]}", text, flags=re.S)
            if n != 1:
                raise SystemExit(f"{CARD} has no <!-- {name} --> block")
        space = text.index('<a href="https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv"><img')
        text = text[:space] + DESK_BADGE + "\n" + text[space:]
    for name, split in bundles.items():
        text = card(text, name=name, split=split, repo=None, description=None, license=None,
                    needs={"plugins": [plugin], "setup": SETUP})
    result = DatasetCard(text)
    if desk and desk["versions"]:
        at = next(i for i, c in enumerate(result.data.configs) if c["config_name"] == "eval_runs") + 1
        result.data.configs[at:at] = desk_configs(desk)
    if files is not None:
        episodes_config = {"config_name": "v1_episodes", "data_files": [
            {"split": s, "path": f"episodes/v1/{s}.parquet"} for s in (*SPLITS, "showcase")
            if f"episodes/v1/{s}.parquet" in files]}
        configs = [episodes_config if c["config_name"] == "v1_episodes" else c for c in result.data.configs]
        result.data.configs = [c for c in configs if c["config_name"].startswith(ELSEWHERE) or any(
            f["path"] in files and pq.read_metadata(io.BytesIO(files[f["path"]])).num_rows for f in c["data_files"])]
    if bundles:
        result.data.agentenv = {"default": next(iter(bundles)), **result.data.agentenv}
    return str(result)


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
    return files | {"README.md": card_text(files, bundles, plugin, results_dir).encode()}


def write(files: dict[str, bytes], out: Path) -> None:
    for folder in MANAGED:
        shutil.rmtree(out / folder, ignore_errors=True)
    for path, content in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(content)


def card_only(results_dir: Path) -> str:
    return card_text(None, {}, "", results_dir)


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
