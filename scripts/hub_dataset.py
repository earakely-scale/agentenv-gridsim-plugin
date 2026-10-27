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
BOARD = re.compile(r"(<!-- board:v1 -->\n).*?(\n<!-- /board:v1 -->)", re.S)
ECONOMICS = re.compile(r"(<!-- economics:v1 -->\n).*?(\n<!-- /economics:v1 -->)", re.S)
ECONOMICS_ROWS = ("optimum", "anchor", "sol", "persistence-dp", "luna-high", "4b-sampled", "ridge-dp", "idle")
NAMES = {"openai/gpt-6.1-sol": "GPT-6.1 Sol", "Qwen/Qwen3-1.7B": "Qwen3-1.7B", "Qwen/Qwen3-4B": "Qwen3-4B"}
MANAGED = ("tasks", "references", "episodes", "runs", "results", "raw", "bundles")

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


def economics_markdown(econ: dict) -> str:
    """The card's economics block from results/economics/summary.json: blind eval-2025 in dollars per MW of battery
    power, the paired gaps against persistence-DP on both packs, and what Sol's inference costs."""
    def ci(x, sign=""):
        return f"({x['ci'][0]:{sign}.1f} to {x['ci'][1]:{sign}.1f})".replace("-", "−")

    ev, fr = econ["packs"]["eval2025"], econ["packs"]["fresh"]
    lines = [f"| Blind eval-2025 ({ev['n_tasks']} battery-days, {ev['n_days']} days) | $ per MW-day (95% CI) | "
             "$k per MW-year | Per 100 MW-year |", "|---|---|---:|---:|"]
    for k in ECONOMICS_ROWS:
        r = ev["rows"][k]
        d, y, h = r["usd_per_mw_day"], r["k_usd_per_mw_yr"], r["k_usd_per_100mw_yr"]
        lines.append(f"| {r['label']} | {d['mean']:.1f} {ci(d)} | {y['mean']:.1f} | "
                     f"{'−' if h['mean'] < 0 else ''}${abs(h['mean']) / 1000:.2f}M |".replace("| -", "| −"))

    def gap(p, key):
        g = p["gaps"][key]["k_usd_per_mw_yr"]
        return f"{'−' if g['mean'] < 0 else '+'}${abs(g['mean']):.1f}k per MW-year {ci(g, '+')}"

    sp, fb = "sol - persistence-dp", "4b-sampled - persistence-dp"
    sol = ev["rows"]["sol"]["usd_inference_per_battery_day"] * 365
    inf = econ["inference"]["packs"]["eval2025"]["sol_over_4b"]
    per100 = ev["gaps"][sp]["k_usd_per_100mw_yr"]["mean"]
    lines += ["", f"- **GPT-6.1 Sol − persistence-DP** (the exact optimum on yesterday's prices): {gap(ev, sp)} on "
              f"eval-2025 and {gap(fr, sp)} on the fresh days of {fr['dates'][0]} to {fr['dates'][1]}; about "
              f"${per100:,.0f}k a year for a 100 MW battery.",
              f"- **Trained Qwen3-4B (run 4) − persistence-DP:** {gap(ev, fb)} on eval-2025, {gap(fr, fb)} on the "
              "fresh days.",
              f"- **Inference:** Sol costs ${sol:.2f} per battery-year whatever the battery's size; its extra "
              f"${inf['extra_inference_usd_per_battery_yr']:.2f} over the trained 4B buys "
              f"${inf['decision_gap_k_usd_per_100mw_yr']:,.0f}k a year per 100 MW on eval-2025."]
    return "\n".join(lines)


def card_text(files: dict[str, bytes], bundles: dict[str, str], plugin: str, board: str | None,
              economics: str | None = None) -> str:
    """The card with v1_episodes on the splits that have episodes, the board when there is one, and each bundle's
    configs and needs as agentenv-hf writes them. A config whose tables are all empty is left off: `datasets` can't
    load a parquet file with no rows."""
    text = CARD.read_text()
    if board:
        text = BOARD.sub(lambda m: f"{m[1]}{board}{m[2]}", text)
    if economics:
        text = ECONOMICS.sub(lambda m: f"{m[1]}{economics}{m[2]}", text)
    for name, split in bundles.items():
        text = card(text, name=name, split=split, repo=None, description=None, license=None,
                    needs={"plugins": [plugin], "setup": SETUP})
    result = DatasetCard(text)
    episodes_config = {"config_name": "v1_episodes", "data_files": [
        {"split": s, "path": f"episodes/v1/{s}.parquet"} for s in (*SPLITS, "showcase")
        if f"episodes/v1/{s}.parquet" in files]}
    configs = [episodes_config if c["config_name"] == "v1_episodes" else c for c in result.data.configs]
    result.data.configs = [c for c in configs if any(
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
    econ = results_dir / "economics" / "summary.json"
    economics = economics_markdown(json.loads(econ.read_text())) if econ.is_file() else None
    return files | {"README.md": card_text(files, bundles, plugin, board, economics).encode()}


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
    args = ap.parse_args()
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
