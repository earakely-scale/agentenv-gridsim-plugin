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

The card is hub/dataset/README.md with its results sections filled in from results/overview/results.json
(scripts/hub_results.py writes that file and the figures) and the bundles' configs. The v1 board and the v2 to v5
previews are kept as the card has them: their tables and boards are built on the previews branch. --card-only writes
the card alone. Every file goes through agentenv-hf's scan for keys and token shapes before anything is written.
Nothing is pushed: upload the folder with `hf upload <repo> <out> --repo-type dataset` after reading it.

    uv run python scripts/hub_dataset.py --out build/hub/dataset
    uv run python scripts/hub_dataset.py --out build/hub/card --card-only
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
from decimal import ROUND_HALF_UP, Decimal
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
PREVIEWS = ("v2_", "v3_", "v4_", "v5_")
RESULTS = "overview/results.json"
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


def fig(name: str, alt: str) -> str:
    return f"![{alt}](assets/figures/{name}.png)"


NB = "\u00a0"
LINKS = {"results/train/4b-blind": "run 4", "results/cost-matched": "cost-matched contest",
         "results/economics": "economics", "results/train/4b-dpa": "run 3", "results/train/4b-v2": "run 2"}


def glance_block(r: dict) -> str:
    s = r["scores"]
    rows = [f"| **{g['value'].replace(' ', NB)}** | **{g['label'][0].upper()}{g['label'][1:]}.** {g['text']} | "
            + " · ".join(ev(f"{x}/README.md", LINKS[x]) for x in g["src"]) + " |" for g in r["glance"]]
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
        "GPT-6.1 Sol, and a free heuristic, by thousands of dollars per MW of battery a year. Every number links to "
        f"its evidence; the [results page]({APP}/results.html) has the same charts with every CI on hover.", "",
        "| Number | What it is | Evidence |", "|---|---|---|", *rows, "", fig("before-after", alt)])


def dollar(r: dict, key: str, pack: str = "eval2025") -> float:
    return next(x for x in r["dollars"]["packs"][pack]["ladder"] if x["key"] == key)["yr"]["mean"]


def gpu(x: float | None) -> str:
    return "–" if x is None else f"${x:.2f}" if x % 1 else f"${x:.0f}"


def level(v: dict | None) -> str:
    if v is None:
        return "not run"
    nd = 2 if v["mean"] < 0.1 else 3
    return f"{h(v['mean'], nd)} {ci(v['ci'], nd)}"


def gap(g: dict, nd: int = 3) -> str:
    return f"{h(g['mean'], nd, True)} {ci(g['ci'], nd, True)}"


def run_row(x: dict) -> str:
    kind = "pre-registered" if x["registered"] else "exploratory"
    return (f"| **{x['label']}**<br>{x['model']}, {kind} | {md(x['change'])} | {x['result']} | {md(x['lesson'])} "
            f"{ev(x['src'] + '/README.md', 'Evidence')} | {gpu(x['usd'])} |")


def pack_row(x: dict) -> str:
    u, t, b, g = x["untrained"], x["trained"], x["baseline"], x["gaps"]
    before = "not run" if u is None else h(u["mean"], 2 if u["mean"] < 0.1 else 3)
    return (f"| {x['label']}, {x['n_tasks']} | {before} → **{h(t['mean'])}** ({t['run']}) | {h(x['luna']['mean'])} | "
            f"{h(x['sol']['mean'])} | {h(b['mean'])} {b['label']} | {gap(g['trained_minus_luna'])} | "
            f"{gap(g['trained_minus_sol'])} |")


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
        fig("training", alt_t), "",
        "Qwen3-4B (thinking off, LoRA adapters, one GPU at a time) trains on battery-days of 2014 to 2024 from the "
        "`train` split and is scored on days it never saw: 200 held-out foresight days and 300 blind days of 2025, and "
        "ERCOT's ten newest days. Each registered run committed its plan, schedule and bars before its first step.", "",
        "**How it was trained.**", "",
        "1. **One prompt, one completion, an exact reward.** Path B: `v1_tasks`' `prompt`, a completion that ends in a "
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
        "| Run | What changed | Held-out | What it taught | GPU |", "|---|---|---|---|---:|",
        *map(run_row, t["runs"]), "",
        f"About ${t['gpu_usd_total']:.0f} of GPU in all, from the first 1.7B arm to run 4; training called no API, "
        "and the adapters are not published. Held-out is reward R on 200 foresight days of 2025 for runs 1 to 3 (500 "
        "unseen days of 2014 to 2024 for the confirmation) and blind capture on 300 days of 2025 for run 4.", "",
        fig("planning", alt_p), "",
        f"Run 4's written forecasts miss by {h(pl['mae']['final'], 2)} $/MWh over all hours, against its teacher's "
        f"{h(pl['mae']['teacher'], 2)} and yesterday's prices' {h(pl['mae']['persistence'], 2)}. Planned by the exact "
        f"DP they would capture {h(e['dp_own']['mean'])}, level with GPT-6.1 Sol "
        f"({gap(e['gaps']['dp_own_minus_sol'])}, reported, not registered); its own schedules capture "
        f"{h(e['final']['mean'])}, "
        f"{gap(e['gaps']['final_minus_sol'])} behind Sol, the registered primary, not met.", "",
        "**Before and after, pack by pack.** The cost-matched contest's comparisons under one harness, with day-block "
        "95% CIs on the paired gaps. Capture is `r_opt`, the hindsight optimum's share on the reward's scale (idle "
        "0.2, hindsight 1.0; the cross-version C of [Grading](#grading) is (r_opt − 0.2)/0.8 wherever r_opt is above "
        "0). At the foresight tier it equals R.", "",
        "| Pack, battery-days | 4B, untrained → trained | GPT-6 Luna, high | GPT-6.1 Sol, high | Simple rule | "
        "Trained − Luna [95% CI] | Trained − Sol [95% CI] |", "|---|---|---|---|---|---|---|",
        *map(pack_row, r["scores"])])


NAME = {"qwen": "Qwen3-4B", "luna": "GPT-6 Luna", "sol": "GPT-6.1 Sol", "beam": "Beam-1.0"}
SHORT = {"sol": "GPT-6.1 Sol", "persistence-dp": "persistence-DP", "luna-high": "GPT-6 Luna (high)",
         "luna-medium": "GPT-6 Luna (medium)", "4b-sampled": "trained Qwen3-4B", "ridge-dp": "ridge-DP",
         "greedy-d1": "greedy rule on yesterday's prices", "luna-low": "GPT-6 Luna (low)",
         "threshold-d1": "threshold rule on yesterday's prices", "idle": "idle", "base": "untrained Qwen3-4B"}


def point_row(x: dict) -> str:
    name = f"{NAME[x['family']]}, {x['effort'] or ('trained (run 4)' if x['key'] == 'final' else 'untrained')}"
    name = f"**{name}**" if x["key"] == "final" else name
    vs = gap(x["final_minus"]) if "final_minus" in x else "–"
    return (f"| {name} | {h(x['mean'])} | {ci(x['ci'])} | {usd(x['usd'])} | {'open' if x['open'] else 'API'} | "
            f"{'yes' if x['frontier'] else '–'} | {vs} |")


def frontier_block(r: dict) -> str:
    f = r["frontier"]
    p, refs, ratio = {x["key"]: x for x in f["points"]}, f["refs"], f["ratios"]
    beams = sorted((x for x in f["points"] if x["family"] == "beam"), key=lambda x: -x["mean"])
    sol = p["sol"]["final_minus"]
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
        fig("frontier", alt), "",
        f"Bidding blind on the {f['n_tasks']} newest battery-days (18 to 27 October 2026), with the identical one-call "
        "prompt. Cost per battery-day: API models at their recorded token usage × list price (Beam-1.0 at Baseten's "
        "price on the Hugging Face router); the 4Bs at their logged batched-generation time on one L40S, "
        f"${f['l40s_usd_per_h']:.2f} an hour, engine start and idle time not charged.", "",
        "| Model, effort | Capture | 95% CI | $ per battery-day | Weights | Frontier | Trained 4B − this [95% CI] |",
        "|---|---|---|---:|---|---|---|",
        *map(point_row, sorted(f["points"], key=lambda x: x["usd"])), "",
        "- **The trained 4B is the cheapest model on the frontier above its untrained base.** It is level with GPT-6 "
        f"Luna at high effort, {gap(p['luna-high']['final_minus'])}, at a quarter of the cost (Luna costs "
        f"{h(ratio['luna_high'], 1)}× as much), and ahead of Luna at low effort, the matched cost "
        f"({h(ratio['luna_low'], 1)}×), by {gap(p['luna-low']['final_minus'])}.",
        f"- **GPT-6.1 Sol** captures {h(-sol['mean'], sign=True)} {ci([-sol['ci'][1], -sol['ci'][0]], sign=True)} "
        f"more, for {h(ratio['sol'], 0)}× the cost.", *beam,
        "- **Two baselines use no LLM:** persistence-DP, the exact DP on yesterday's prices, captures "
        f"{h(refs['persistence_dp']['mean'])}, and run 4's teacher forecaster planned with the exact DP "
        f"{h(refs['teacher_dp']['mean'])}. On these days only Sol and Beam at max effort score above persistence-DP.",
        "- The 4B, Luna at high and low effort and Sol are the cost-matched contest's pre-registered rows "
        f"({ev('results/cost-matched/README.md', 'results/cost-matched')}); Luna at medium effort and Beam are "
        f"descriptive runs under the same harness ({ev('results/beam-agent/README.md', 'results/beam-agent')})."])


ROWS = ("optimum", "sol", "persistence-dp", "luna-high", "luna-medium", "4b-sampled", "sft", "ridge-dp", "greedy-d1",
        "luna-low", "threshold-d1", "idle", "base")


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
            rows.append(f"| {name} | {yr(a)} | {per100(a)} | {yr(b)} | "
                        f"{'–' if x['inference'] is None else usd(x['inference'])} |")
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
        fig("ladder", alt_l), "",
        "Every recorded blind schedule settled again at ERCOT's day-ahead prices, its profit per MW of battery power: "
        f"× 365 for a year, × 100 for a 100 MW battery. Blind 2025 ({e['n_tasks']} battery-days on {e['n_days']} days) "
        f"and the newest days ({fr['n_tasks']} on {fr['n_days']}), day-block 95% CIs. A reply with no valid schedule "
        "settles as idle. A descriptive re-analysis computed after the results, not pre-registered "
        f"({ev('results/economics/README.md', 'results/economics')}).", "",
        "| Policy | 2025: $k per MW-year [95% CI] | Per 100 MW-year | Newest days: $k per MW-year [95% CI] | "
        "Inference per battery-day |", "|---|---|---:|---|---:|", *rows, "",
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
        fig("regimes", alt_q), "",
        "**When reasoning pays.** Split 2025's 191 days into quartiles by how far the day's 24 hourly prices move from "
        "the day before's shape (1 − Pearson r). When the day repeats yesterday, persistence-DP is within "
        f"${h(q[0]['shortfall']['mean'], 1)}–{h(q[1]['shortfall']['mean'], 1)} per MW-day of the optimum: Sol stays "
        "level with it, while Luna and the 4B lose money by moving off it. When the shape changes (Q4), persistence-DP "
        f"falls ${h(q[3]['shortfall']['mean'], 1)} short; Sol recovers ${h(q[3]['sol']['mean'], 1)} of it "
        f"{ci(q[3]['sol']['ci'], 1, True)}, while Luna and the 4B only draw level. "
        f"{e['top_days']['sol_share_from_top']:.0%} of Sol's net gain over persistence-DP comes from its best "
        f"{e['top_days']['k']} days.", "",
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
        "10 days of October 2026."])


def live_block(r: dict) -> str:
    return (f"[The live board]({APP}/board.html) tests the agents on days that have not happened. Before ERCOT's "
            "day-ahead market closes for a delivery day, GPT-6.1 Sol, GPT-6 Luna, the trained 4B (run 4) and three "
            "rules each seal a 24-hour schedule for 45 batteries (15 hubs and load zones × a 1-, 2- and 4-hour battery "
            "at 100 MW) as a timestamped commit to this dataset's `live/` folder; when ERCOT posts the day's prices, "
            "every schedule is settled at them and the cumulative P&L updates. The prices do not exist when a schedule "
            "is published, so no model can have seen them. Passes now run on demand rather than daily (amendment 1 of "
            f"the [pre-registration]({REPO}/blob/main/{r['live']['prereg']})); the first seal is for "
            f"{r['live']['first_seal']}. A descriptive track record, not a test with a verdict.")


def results_blocks(results_dir: Path) -> dict[str, str]:
    """The card's results sections from results/overview/results.json (scripts/hub_results.py writes it)."""
    path = results_dir / RESULTS
    if not path.is_file():
        return {}
    r = json.loads(path.read_text())
    return {"glance": glance_block(r), "training-results": training_block(r), "frontier": frontier_block(r),
            "worth": worth_block(r), "live": live_block(r)}


def card_text(files: dict[str, bytes] | None, bundles: dict[str, str], plugin: str, blocks: dict[str, str]) -> str:
    """The card with its generated blocks and each bundle's configs and needs as agentenv-hf writes them. Given the
    files this build wrote, v1_episodes lists the splits that have episodes and a v1 config whose tables are all empty
    is left off (`datasets` can't load a parquet file with no rows); the previews' configs stay as the card lists them,
    since their tables are built on the previews branch. Without files, every config stays as listed."""
    text = CARD.read_text()
    for name, block in blocks.items():
        text, n = re.subn(rf"(<!-- {name} -->\n).*?(<!-- /{name} -->)", lambda m, b=block: f"{m[1]}{b}\n{m[2]}",
                          text, flags=re.S)
        if n != 1:
            raise SystemExit(f"{CARD} has no <!-- {name} --> block")
    for name, split in bundles.items():
        text = card(text, name=name, split=split, repo=None, description=None, license=None,
                    needs={"plugins": [plugin], "setup": SETUP})
    result = DatasetCard(text)
    if files is not None:
        episodes_config = {"config_name": "v1_episodes", "data_files": [
            {"split": s, "path": f"episodes/v1/{s}.parquet"} for s in (*SPLITS, "showcase")
            if f"episodes/v1/{s}.parquet" in files]}
        configs = [episodes_config if c["config_name"] == "v1_episodes" else c for c in result.data.configs]
        result.data.configs = [c for c in configs if c["config_name"].startswith(PREVIEWS) or any(
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
    bundles = {}
    for path in bundle_dirs:
        bundles[path.name] = bundle_split(path.name)
        files |= dataset.build(runs.locate(str(path)), name=path.name, split=bundles[path.name],
                               which="latest").files
    return files | {"README.md": card_text(files, bundles, plugin, results_blocks(results_dir)).encode()}


def write(files: dict[str, bytes], out: Path) -> None:
    for folder in MANAGED:
        shutil.rmtree(out / folder, ignore_errors=True)
    for path, content in files.items():
        (out / path).parent.mkdir(parents=True, exist_ok=True)
        (out / path).write_bytes(content)


def card_only(results_dir: Path) -> str:
    return card_text(None, {}, "", results_blocks(results_dir))


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
