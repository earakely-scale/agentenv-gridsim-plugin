"""`agent-env gridsim sweep`: a pack's battery-days over models and reps at one tier and harness under a spend cap, one
`agent-env run` process per attempt, retried and resumed from results.jsonl; and the report: results/eval-v1.json (the
FineEnvs eval card with the baselines from the pack's references) and results/board.md."""

import json
import random
import re
import signal
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import click
from agent_env.config import get_config
from agent_env.store.routing import namespace_routing
from agent_env.task.store import get_task_instance_store
from gridsim_core import CONTRACT_VERSION
from gridsim_core.grade import grade

from . import tasks
from .server import PACK_NAMES, TIERS

AGENT_ENV = [sys.executable, "-m", "agent_env.cli"]
RUNS = Path("results/runs")
CARD = Path("results/eval-v1.json")
BOARD = Path("results/board.md")
EVAL_PACK = "ercot-dam-v1-eval"
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
INSTANCE = re.compile(r"(\d+(?:\.\d+)?)s, instance (\S+)")
STOPS = ("model_endpoint", "unpriced_model")
MAX_ATTEMPTS = 3
POLL_SECONDS = 2.0
ERRORS = ("overfill", "sell_before_charge", "rate", "cycle_cap", "end_short", "all_idle")
VIOLATIONS = {"soc_above_N": "overfill", "soc_below_0": "sell_before_charge", "rate": "rate", "cycle_cap": "cycle_cap"}
BASELINES = ("clock", "threshold", "greedy")


@dataclass(frozen=True)
class Sweep:
    name: str
    models: list[str]
    tasks: list[str]
    k: int
    episode_cap_usd: float
    tier: str = "foresight"
    bundle: str = "full"
    pack: str = EVAL_PACK

    @property
    def out(self) -> Path:
        """Its bundle, logs, transcripts and results.jsonl; its Episode JSON goes to RUNS/<name>/ above it."""
        return RUNS / self.name / "raw"

    def runs(self) -> list[tuple[str, str, int]]:
        """(model, task, rep), model-major, then rep, then task."""
        return [(m, t, rep) for m in self.models for rep in range(1, self.k + 1) for t in self.tasks]


@dataclass
class Attempt:
    run: tuple[str, str, int]
    number: int
    started_utc: str
    log: Path
    proc: subprocess.Popen

    @property
    def label(self) -> str:
        model, task, rep = self.run
        return f"{model} {task} r{rep} a{self.number}"


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", model)


def results(out: Path) -> list[dict]:
    path = out / "results.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def of(rows: list[dict], run: tuple[str, str, int]) -> list[dict]:
    return [r for r in rows if (r["model"], r["task_id"], r["rep"]) == run]


def final(rows: list[dict]) -> bool:
    """A run is final once scored, stopped at its cost cap, refused by the provider, or after MAX_ATTEMPTS counted
    attempts; an interrupted attempt doesn't count."""
    counted = [r for r in rows if r["outcome"] != "interrupted"]
    return (any(r["outcome"] == "scored" or r["error_code"] in ("cost_cap", "provider_refused") for r in counted)
            or len(counted) >= MAX_ATTEMPTS)


def cost(row: dict, cap: float) -> float:
    """What an attempt spent, or its episode cap when it recorded no spend: the budget counts the worst case."""
    return cap if row["cost_usd"] is None else row["cost_usd"]


def priced(row: dict) -> float | None:
    """What a run's tokens cost: its spend without the failed provider requests the cap books at their worst case."""
    return row["cost_usd"] if row.get("priced_cost_usd") is None else row["priced_cost_usd"]


def context(instance: str) -> dict:
    with namespace_routing():
        return get_task_instance_store().get(instance).context or {}


def trajectory(uri: str) -> bytes:
    with namespace_routing():
        return get_config().get_object_store_at(uri).get(uri)


def task_ids(spec: str, pack: str = EVAL_PACK, tier: str = "foresight") -> list[str]:
    """``all``, the first N, or comma-separated ids, of the pack's tasks the tier can play, in the pack's order."""
    known = [r["task_id"] for r in tasks.eligible(tasks.pack_rows(pack), tier)]
    if spec == "all":
        return known
    if spec.isdigit():
        return known[:int(spec)]
    ids = spec.split(",")
    if unknown := [i for i in ids if i not in known]:
        raise click.UsageError(f"not {tier} tasks of {pack}: {', '.join(unknown)}")
    return ids


def prepare(sweep: Sweep) -> None:
    """Writes the sweep's bundle and sweep.json on its first run; a later run must be the same sweep."""
    if not NAME.fullmatch(sweep.name):
        raise click.UsageError("a sweep's name is 1 to 41 lowercase letters, digits and dashes, starting with no dash")
    path = sweep.out / "sweep.json"
    if path.is_file():
        if json.loads(path.read_text()) != asdict(sweep):
            raise click.UsageError(f"{path} is another sweep; run it with its own models, tasks, k, episode cap, "
                                   f"tier, bundle and pack: {path.read_text().strip()}")
        return
    tasks.generate(sweep.pack, sweep.out / "bundle", tier=sweep.tier, bundle=sweep.bundle, task_ids=sweep.tasks,
                   episode_cap_usd=sweep.episode_cap_usd)
    path.write_text(json.dumps(asdict(sweep), indent=2) + "\n")


def preflight(sweep: Sweep, task: str) -> str | None:
    """The problem a dry run of ``task`` finds, as `agent-env run` would before its first step, or None."""
    log = sweep.out / "logs" / "preflight.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w") as f:
        code = subprocess.run([*AGENT_ENV, "run", str((sweep.out / "bundle").absolute()), "--task", task, "--dry-run"],
                              stdout=f, stderr=subprocess.STDOUT).returncode
    return f"the dry run of {task} exited {code}:\n{log.read_text(errors='replace').rstrip()}" if code else None


def start(sweep: Sweep, run: tuple[str, str, int], number: int) -> Attempt:
    model, task, rep = run
    log = sweep.out / "logs" / slug(model) / f"{task}-r{rep}-a{number}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with log.open("w") as f:
        proc = subprocess.Popen([*AGENT_ENV, "run", str((sweep.out / "bundle").absolute()), "--task", task,
                                 "--model", model], stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    return Attempt(run, number, started, log, proc)


def errors_of(episode: dict) -> list[str]:
    """The error taxonomy of a submitted schedule: the rule it broke, an end-of-day shortfall, an all-idle day."""
    g = episode.get("grade") or {}
    if not g.get("submitted"):
        return []
    found = [VIOLATIONS.get(g.get("violation"), g.get("violation"))] if g.get("violation") else []
    if g.get("end_shortfall_units"):
        found.append("end_short")
    if not any(episode.get("schedule") or []):
        found.append("all_idle")
    return found


def outcome(sweep: Sweep, attempt: Attempt, earlier: list[dict], interrupted: bool = False, read: bool = True) -> dict:
    """The attempt's row, from the instance its run stored: the verifier's rows and episode, and the play step's
    summary, failure and trajectory. Without ``read`` (the sweep itself failed), from the log alone."""
    model, task, rep = attempt.run
    found = INSTANCE.findall(attempt.log.read_text(errors="replace"))
    wall, instance = (float(found[-1][0]), found[-1][1]) if found else (None, None)
    ctx = context(instance) if instance and read else {}
    m = ctx.get("metadata") or {}
    v = (m.get("verifications") or {}).get("gridsim") or {}
    pr = next((p for p in ctx.get("prompt_responses") or [] if p.get("step_id") == "play"), None)
    s = (pr or {}).get("structured_output") or {}
    failed = m.get("failed_steps") or []
    scored = "score" in v
    if s:
        spent = s.get("cost_usd")
    elif instance and not interrupted and pr is None and "play" not in {f["step_id"] for f in failed}:
        spent = 0.0
    else:
        spent = None
    transcript = None
    if pr and pr.get("agent_trajectory_object_url"):
        path = sweep.out / "transcripts" / slug(model) / f"{task}-r{rep}-a{attempt.number}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(trajectory(pr["agent_trajectory_object_url"]))
        transcript = path.relative_to(sweep.out).as_posix()
    rows = {r["criterion"]: r for r in v.get("results") or []}
    episode = rows["gridsim"]["episode"] if scored else {}
    g = episode.get("grade") or {}
    error_code = error = failed_step = None
    if not scored and not interrupted:
        error_code = (pr or {}).get("error_code") or (failed[-1]["error_type"] if failed else "no_instance")
        error = (pr or {}).get("error_message") or (failed[-1]["error"] if failed else None)
        failed_step = failed[-1]["step_id"] if failed else None
    row = {"sweep": sweep.name, "model": model, "task_id": task, "rep": rep, "attempt": attempt.number,
           "tier": sweep.tier, "bundle": sweep.bundle, "started_utc": attempt.started_utc, "wall_seconds": wall,
           "exit": attempt.proc.returncode, "instance": instance,
           "outcome": "scored" if scored else "interrupted" if interrupted else "failed",
           "failed_step": failed_step, "error_code": error_code, "error": error and error[:500], "retryable": False,
           "reward": v["score"] if scored else None,
           "r_opt": rows["hindsight_capture"]["score"] if scored else None,
           "submitted": bool(g.get("submitted")) if scored else None,
           "valid": bool(g.get("submitted") and g.get("feasible")) if scored else None,
           "feasible": g.get("feasible"), "violation": g.get("violation"), "truncated_at": g.get("truncated_at"),
           "end_shortfall_units": g.get("end_shortfall_units"), "errors": errors_of(episode) if scored else None,
           "profit": g.get("profit"), "profit_idle": g.get("profit_idle"), "profit_anchor": g.get("profit_anchor"),
           "profit_opt": g.get("profit_opt"), "beats_anchor": g.get("beats_anchor"),
           "schedule": episode.get("schedule"), "checks": episode.get("checks_used"), "calls": episode.get("calls_used"),
           "env_end_reason": episode.get("end_reason"),
           **{key: s.get(key) for key in ("end_reason", "effort", "turns", "tool_calls", "input_tokens",
                                          "output_tokens", "cached_tokens", "cache_write_tokens")},
           "cost_usd": spent, "priced_cost_usd": s.get("priced_cost_usd"), "failed_requests": s.get("failed_requests"),
           "transcript": transcript}
    row["retryable"] = not final([*earlier, row])
    return row


def _money(row: dict, cap: float) -> str:
    return f"${row['cost_usd']:.4f}" if row["cost_usd"] is not None else f"no spend recorded, counted as ${cap:.2f}"


def _attempts(n: int) -> str:
    return f"{n} attempt{'' if n == 1 else 's'}"


def _spend(rows: list[dict], cap: float) -> str:
    unknown = sum(r["cost_usd"] is None for r in rows)
    known = sum(r["cost_usd"] or 0.0 for r in rows)
    return f"${known:.2f} spent" + (f", {_attempts(unknown)} with no spend recorded (${unknown * cap:.2f} at the cap)"
                                    if unknown else "")


def run(sweep: Sweep, cap_usd: float, parallel: int, echo=click.echo) -> int:
    """Plays the runs results.jsonl doesn't hold as final, `parallel` attempts at a time, while the spend so far plus
    the episode cap of every attempt running and the next stays within ``cap_usd``. Returns the exit code: 0 when
    every run is final, 1 when the sweep stopped early, 130 when a signal stopped it. If the sweep itself fails, it
    tears its attempts down and records them from their logs, at their caps, before the error propagates."""
    cap = sweep.episode_cap_usd
    rows = results(sweep.out)
    queue = [r for r in sweep.runs() if not final(of(rows, r))]
    spent = sum(cost(r, cap) for r in rows)
    running: list[Attempt] = []
    stopped = None
    caught: list[int] = []
    previous = {s: signal.signal(s, lambda signum, _: caught.append(signum)) for s in (signal.SIGINT, signal.SIGTERM)}

    def record(attempt: Attempt, interrupted: bool = False, read: bool = True) -> dict:
        nonlocal spent
        row = outcome(sweep, attempt, of(rows, attempt.run), interrupted, read)
        running.remove(attempt)
        rows.append(row)
        spent += cost(row, cap)
        with (sweep.out / "results.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def finish(attempt: Attempt) -> dict:
        row = record(attempt)
        if row["outcome"] == "scored":
            echo(f"done {attempt.label}: reward {row['reward']} ({row['end_reason']}), {_money(row, cap)} "
                 f"(spent ${spent:.2f})")
        else:
            echo(f"failed {attempt.label}: {row['error_code']} {'retry' if row['retryable'] else 'final'} "
                 f"({_money(row, cap)})")
        return row

    def tear_down(read: bool) -> None:
        for attempt in running:
            attempt.proc.terminate()
        for attempt in list(running):
            attempt.proc.wait()
            echo(f"interrupted {attempt.label} ({_money(record(attempt, interrupted=True, read=read), cap)})")

    try:
        if queue:
            stopped = preflight(sweep, queue[0][1])
        while not caught and (running or (queue and not stopped)):
            while (queue and not stopped and len(running) < parallel
                   and spent + (len(running) + 1) * cap <= cap_usd + 1e-9):
                r = queue.pop(0)
                attempt = start(sweep, r, len(of(rows, r)) + 1)
                running.append(attempt)
                echo(f"start {attempt.label} (spent ${spent:.2f} of ${cap_usd:.2f})")
            if not running:
                stopped = (f"another attempt could take the spend past ${cap_usd:.2f} (${spent:.2f} spent, "
                           f"${cap:.2f} an attempt at most); {len(queue)} runs not final")
                break
            time.sleep(POLL_SECONDS)
            for attempt in [a for a in running if a.proc.poll() is not None]:
                row = finish(attempt)
                if row["error_code"] in STOPS:
                    stopped = f"{row['error_code']} from {attempt.label}: {row['error']}"
                elif row["retryable"]:
                    queue.append(attempt.run)
        if caught:
            for attempt in [a for a in running if a.proc.poll() is not None]:
                finish(attempt)
            tear_down(read=True)
            return 130
    except BaseException:
        tear_down(read=False)
        raise
    finally:
        for s, handler in previous.items():
            signal.signal(s, handler)
    for model in sweep.models:
        planned = [r for r in sweep.runs() if r[0] == model]
        scored = sum(any(x["outcome"] == "scored" for x in of(rows, r)) for r in planned)
        unscored = sum(final(of(rows, r)) for r in planned) - scored
        echo(f"{model}: {scored} scored, {unscored} unscored, {len(planned) - scored - unscored} not final, of "
             f"{len(planned)} runs; {_spend([x for x in rows if x['model'] == model], cap)}")
    if stopped:
        echo(f"stopped: {stopped}")
    return 0 if all(final(of(rows, r)) for r in sweep.runs()) else 1


# ================================================================ report

def ci(xs: list[float], n: int = 2000, seed: int = 0) -> tuple[float, float]:
    rng = random.Random(seed)
    means = sorted(statistics.mean(rng.choices(xs, k=len(xs))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n)]


def load(name: str) -> Sweep:
    path = RUNS / name / "raw" / "sweep.json"
    if not path.is_file():
        raise click.UsageError(f"no sweep {name!r}: {path} doesn't exist")
    return Sweep(**json.loads(path.read_text()))


def _r(x: float | None, digits: int = 4) -> float | None:
    return None if x is None else round(x, digits)


def _mean(xs: list[float]) -> float | None:
    return statistics.mean(xs) if xs else None


def baselines(rows: list[dict]) -> dict:
    """The references' mean rewards over these tasks: idle by construction; clock, threshold and greedy as the pack
    stored them on the day's prices; persistence-DP, its D-1-price schedule settled on the day, on the tasks with blind
    inputs, graded by gridsim_core at the blind tier."""
    out: dict = {"idle": 0.2}
    for name in BASELINES:
        out[name] = _r(_mean([r["refs"]["foresight"]["baselines"][name]["reward"] for r in rows]))
    blind = [r for r in rows if r.get("blind") and (r["refs"].get("blind") or {}).get("persist")]
    out["persistence_dp_blind"] = _r(_mean([grade(r, r["refs"]["blind"]["persist"], "blind")["reward"]
                                            for r in blind]))
    out["n"] = len(rows)
    out["n_blind"] = len(blind)
    return out


class Board:
    """The named sweeps' scored runs, one cell per (model, tier, bundle): each task's value is the mean of its scored
    reps; the CIs bootstrap over tasks."""

    def __init__(self, sweeps: list[Sweep]):
        self.sweeps = sweeps
        self.rows = {s.name: results(s.out) for s in sweeps}
        self.caps = {s.name: s.episode_cap_usd for s in sweeps}
        packs = {s.pack for s in sweeps}
        self.tasks = {r["task_id"]: r for p in sorted(packs) for r in tasks.pack_rows(p)}
        self.cells: dict[tuple[str, str, str], list[tuple[Sweep, list[dict]]]] = {}
        for s in sweeps:
            for m in s.models:
                self.cells.setdefault((m, s.tier, s.bundle), []).append(
                    (s, [r for r in self.rows[s.name] if r["model"] == m]))

    def scored(self, cell) -> dict[str, list[dict]]:
        by_task: dict[str, list[dict]] = {}
        for s, rows in self.cells[cell]:
            for run in s.runs():
                if run[0] != cell[0]:
                    continue
                if row := next((r for r in of(rows, run) if r["outcome"] == "scored"), None):
                    by_task.setdefault(run[1], []).append(row)
        return by_task

    def planned(self, cell) -> int:
        return sum(1 for s, _ in self.cells[cell] for run in s.runs() if run[0] == cell[0])

    def spend(self, cell) -> tuple[float, int]:
        attempts = [r for _, rows in self.cells[cell] for r in rows]
        return sum(r["cost_usd"] or 0.0 for r in attempts), sum(r["cost_usd"] is None for r in attempts)

    def model(self, cell) -> dict:
        model, tier, bundle = cell
        by_task = self.scored(cell)
        mean = {t: statistics.mean(r["reward"] for r in rs) for t, rs in by_task.items()}
        runs = [r for rs in by_task.values() for r in rs]
        rewards = list(mean.values())
        lo_hi = ci(rewards) if rewards else None
        r_opt = [statistics.mean(r["r_opt"] for r in rs) for rs in by_task.values()]
        costs = [priced(r) for r in runs if priced(r) is not None]
        known, unknown = self.spend(cell)
        errors = {e: sum(e in (r["errors"] or []) for r in runs) for e in ERRORS}
        effort = sorted({r.get("effort") for r in runs if r.get("effort")})
        out = {"model": model, "trained": "base", "tier": tier, "bundle": bundle, "effort": effort[0] if effort else None,
               "runs": len(runs), "planned": self.planned(cell), "tasks": len(mean),
               "mean": _r(_mean(rewards)), "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None,
               "hindsight_capture": _r(_mean(r_opt)),
               "valid": _r(_mean([float(r["valid"]) for r in runs])),
               "submitted": _r(_mean([float(r["submitted"]) for r in runs])),
               "errors": errors, "checks_used": _r(_mean([r["checks"] for r in runs if r["checks"] is not None]), 2),
               "usd_per_episode": _r(_mean(costs)), "spend_usd": round(known, 4), "unknown_spend_attempts": unknown}
        if tier == "blind":
            out["beats_anchor"] = _r(_mean([float(bool(r["beats_anchor"])) for r in runs]))
        return out

    def task_rows(self) -> list[dict]:
        ids = {t for cell in self.cells for t in self.scored(cell)} or {t for s in self.sweeps for t in s.tasks}
        return [self.tasks[t] for t in sorted(ids) if t in self.tasks]


def card(board: Board) -> dict:
    models = [board.model(cell) for cell in board.cells]
    rows = board.task_rows()
    split = sorted({r.get("split") for r in rows if r.get("split")})
    return {
        "env": "gridsim-battery", "version": "v1", "contract_version": CONTRACT_VERSION,
        "authors": [{"name": "Edgar Arakelyan", "github": "earakely-scale", "affiliation": "Scale AI"},
                    {"name": "Adithya S Kolavi", "github": "adithya-s-k", "affiliation": "Hugging Face"}],
        "framework": "agentenv",
        "tasks": {"split": split[0] if len(split) == 1 else split, "n": len(rows), "unit": "battery-hub-days",
                  "packs": sorted({s.pack for s in board.sweeps}),
                  "source": "ERCOT NP4-180-ER hub/LZ DAM SPPs; EIA-860 archetypes",
                  "selection": "low-spread and greedy-easy filters; 2025 held out"},
        "harness": {"agent": tasks.AGENT, "tools": ["get_situation", "check_schedule", "submit_schedule"],
                    "max_turns": tasks.MAX_TURNS, "max_tokens": tasks.MODEL_PARAMS["max_tokens"],
                    "effort": tasks.EFFORT, "bundles": {"full": "3 checks", "oneshot": "submit_schedule only"}},
        "grading": {"reference": "exact DP over integer SoC (LP bound reported)",
                    "reward": "clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1)",
                    "anchor": {"foresight": "P_opt (exact DP)", "blind": "max(P_persist, P_ridge)"},
                    "hindsight_capture": "r_opt: the reward against P_opt, a weight-0 row", "excused": "none",
                    "judge": False},
        "baselines": baselines(rows),
        "models": models,
        "errors": {"taxonomy": list(ERRORS),
                   "meaning": {"overfill": "soc_above_N", "sell_before_charge": "soc_below_0", "rate": "rate",
                               "cycle_cap": "cycle_cap", "end_short": "end SoC below s_end_min",
                               "all_idle": "a schedule of 24 zeros"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps],
        "links": {"runs": "hf dataset", "replays": "hf space", "code": "github"},
    }


def _f(x: float | None, f: str = ".3f") -> str:
    return "–" if x is None else format(x, f)


def board_md(c: dict) -> str:
    b = c["baselines"]
    lines = ["# GridSim v1 board", "",
             f"Tasks: {c['tasks']['n']} battery-days ({', '.join(c['tasks']['packs'])}). Harness: {c['harness']['agent']},"
             f" {c['harness']['max_turns']} turns, {c['harness']['max_tokens']} output tokens a turn, effort "
             f"{c['harness']['effort']}. Reward: {c['grading']['reward']}; foresight anchor P_opt, blind anchor "
             "max(P_persist, P_ridge). Mean R over tasks with a 95% bootstrap CI; valid: submitted and feasible.", "",
             f"Baselines on these tasks: idle {_f(b['idle'])}, clock {_f(b['clock'])}, threshold "
             f"{_f(b['threshold'])}, greedy {_f(b['greedy'])}, persistence-DP (blind, {b['n_blind']} tasks) "
             f"{_f(b['persistence_dp_blind'])}.", "",
             "| Model | Tier | Bundle | Tasks | Runs/planned | Mean R (95% CI) | Hindsight r_opt | Valid | Beats anchor "
             "| Checks used | $/episode | Spend |",
             "|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci95 = f" ({_f(m['ci95'][0])} to {_f(m['ci95'][1])})" if m["ci95"] else ""
        lines.append(" | ".join([
            f"| {m['model']}", m["tier"], m["bundle"], str(m["tasks"]), f"{m['runs']}/{m['planned']}",
            _f(m["mean"]) + ci95, _f(m["hindsight_capture"]), _f(m["valid"]), _f(m.get("beats_anchor")),
            _f(m["checks_used"], ".2f"), "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}",
            f"${m['spend_usd']:.2f}" + (f" + {m['unknown_spend_attempts']} unknown" if m["unknown_spend_attempts"]
                                        else "")]) + " |")
    lines += ["", "## Errors", "", "Scored runs whose submitted schedule broke a rule (it executes up to that hour), "
              "ended short of the end-of-day state of charge, or idled all day.", "",
              "| Model | Tier | Bundle | " + " | ".join(ERRORS) + " |", "|---|---|---|" + "---:|" * len(ERRORS)]
    lines += [f"| {m['model']} | {m['tier']} | {m['bundle']} | " + " | ".join(str(m["errors"][e]) for e in ERRORS)
              + " |" for m in c["models"]]
    return "\n".join(lines) + "\n"


def unscored(board: Board) -> list[str]:
    out = []
    for cell in board.cells:
        done = board.scored(cell)
        for s, rows in board.cells[cell]:
            for run in s.runs():
                if run[0] == cell[0] and run[1] not in done:
                    rs = of(rows, run)
                    last = (rs[-1]["error_code"] or rs[-1]["outcome"]) if rs else "not run"
                    out.append(f"| {s.name} | {run[0]} | {run[1]} | {run[2]} | {len(rs)} | {last} |")
    return (["| Sweep | Model | Task | Rep | Attempts | Last outcome |", "|---|---|---|---:|---:|---|", *out]
            if out else ["None."])


def report(sweeps: list[Sweep], card_path: Path = CARD, board_path: Path = BOARD) -> dict:
    board = Board(sweeps)
    c = card(board)
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(c, indent=2) + "\n")
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(board_md(c) + "\n## Unscored runs\n\n" + "\n".join(unscored(board)) + "\n")
    return c


@click.group("sweep")
def sweep_group():
    """Sweeps: a pack's battery-days over models and reps at one tier and harness under a spend cap, and the report."""


@sweep_group.command("run")
@click.option("--name", required=True,
              help="The sweep's name: its results go to results/runs/<name>/raw/, its Episode JSON to results/runs/<name>/.")
@click.option("--models", required=True, help="Comma-separated LiteLLM model ids, e.g. openai/gpt-6.1-sol.")
@click.option("--tasks", "task_spec", required=True,
              help="all, N (the pack's first N), or comma-separated task ids of the pack the tier can play.")
@click.option("--pack", type=click.Choice(PACK_NAMES), default=EVAL_PACK, show_default=True, help="The task pack.")
@click.option("--tier", type=click.Choice(TIERS), default="foresight", show_default=True)
@click.option("--bundle", type=click.Choice(list(tasks.BUNDLES)), default="full", show_default=True,
              help="full: three checks; oneshot: submit_schedule only.")
@click.option("--cap-usd", type=float, required=True,
              help="The model spend the sweep stays within: no attempt starts that could take it past this at the "
                   "episode cap.")
@click.option("--k", type=click.IntRange(min=1), default=1, show_default=True, help="Reps of each model and task.")
@click.option("--episode-cap-usd", type=float, default=1.0, show_default=True,
              help="An episode's cost cap, passed to the agent as GRIDSIM_MAX_COST_USD.")
@click.option("--parallel", type=click.IntRange(min=1), default=4, show_default=True, help="Attempts at a time.")
def run_command(name: str, models: str, task_spec: str, pack: str, tier: str, bundle: str, cap_usd: float, k: int,
                episode_cap_usd: float, parallel: int):
    """Play each model on each task k times, one `agent-env run` per attempt, logged under results/runs/<name>/raw/logs.
    Each attempt is a line of results.jsonl; a failed one is retried up to twice, and running the sweep again plays
    the runs that aren't final yet. Ctrl-C tears the running attempts down."""
    if "" in models.split(","):
        raise click.UsageError("--models takes comma-separated model ids, none empty")
    sweep = Sweep(name, models.split(","), task_ids(task_spec, pack, tier), k, episode_cap_usd, tier, bundle, pack)
    if not sweep.tasks:
        raise click.UsageError(f"no {tier} tasks in {pack} for --tasks {task_spec}")
    prepare(sweep)
    raise SystemExit(run(sweep, cap_usd, parallel))


@sweep_group.command("report")
@click.argument("names", nargs=-1, required=True)
@click.option("--card", "card_path", type=click.Path(dir_okay=False, path_type=Path), default=CARD, show_default=True,
              help="The eval card to write.")
@click.option("--board", "board_path", type=click.Path(dir_okay=False, path_type=Path), default=BOARD,
              show_default=True, help="The Markdown board to write.")
def report_command(names: tuple[str, ...], card_path: Path, board_path: Path):
    """Report the sweeps NAMES: each model at each tier and harness, its mean reward with a 95% bootstrap CI, hindsight
    capture, valid rate, error taxonomy, checks used and cost, next to the pack references' baselines."""
    c = report([load(name) for name in names], card_path, board_path)
    click.echo(f"Wrote {card_path} and {board_path}: {len(c['models'])} model rows over {c['tasks']['n']} tasks")
