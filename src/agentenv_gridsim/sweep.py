"""`agent-env gridsim sweep`: a pack's battery-days over models and reps at one tier and harness under a spend cap, one
`agent-env run` process per attempt, retried and resumed from results.jsonl; and the report: results/eval-v1.json (the
FineEnvs eval card with the baselines from the pack's references) and results/board.md. With --env gridsim-live, a
live pack's days played live (the harness is "live"), reported to results/eval-v2.json and results/board-v2.md
against the live references; with --env gridsim-hybrid, a hybrid pack's site-days, reported to results/eval-v3.json and
results/board-v3.md against the hybrid references."""

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
from gridsim_core.grade import grade, reward_value
from gridsim_core.hybrid import HYBRID_ENV, HYBRID_VERSION
from gridsim_core.hybrid import TIERS as HYBRID_TIERS
from gridsim_core.hybrid import TOOLS as HYBRID_TOOLS
from gridsim_core.live import LIVE_ENV, LIVE_VERSION, MAX_TURNS, PLANNING_CALLS, TOOLS
from gridsim_core.live import TIERS as LIVE_TIERS

from . import hybrid_tasks, live_tasks, tasks
from .hybrid import HYBRID_PACK_NAMES
from .live import LIVE_PACK_NAMES
from .server import PACK_NAMES, TIERS

AGENT_ENV = [sys.executable, "-m", "agent_env.cli"]
RUNS = Path("results/runs")
CARD = Path("results/eval-v1.json")
BOARD = Path("results/board.md")
LIVE_CARD = Path("results/eval-v2.json")
LIVE_BOARD = Path("results/board-v2.md")
HYBRID_CARD = Path("results/eval-v3.json")
HYBRID_BOARD = Path("results/board-v3.md")
EVAL_PACK = "ercot-dam-v1-eval"
LIVE_EVAL_PACK = "gridsim-live-eval"
HYBRID_EVAL_PACK = "ercot-hybrid-v3-eval"
ENVS = ("gridsim", LIVE_ENV, HYBRID_ENV)
LIVE_ERRORS = ("no_commit", "refused", "end_short", "clipped", "no_replanning")
HYBRID_ERRORS = ("no_commit", "refused", "ftp_charged", "end_short", "governed", "no_replanning", "as_unused")
HYBRID_BASELINES = ("sponge", "as_hog", "v2_energy")
STRATA = ("low", "mid", "high")
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
    env: str = "gridsim"

    @property
    def live(self) -> bool:
        """Played live in watches: gridsim-live or gridsim-hybrid."""
        return self.env in (LIVE_ENV, HYBRID_ENV)

    @property
    def hybrid(self) -> bool:
        return self.env == HYBRID_ENV

    def spec(self) -> dict:
        """sweep.json: the fields, without env for a v1 sweep, so v1 sweeps resume as they were written."""
        return {k: v for k, v in asdict(self).items() if k != "env" or self.live}

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
    module = hybrid_tasks if pack in HYBRID_PACK_NAMES else live_tasks if pack in LIVE_PACK_NAMES else tasks
    known = [r["task_id"] for r in module.eligible(module.pack_rows(pack), tier)]
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
        if {"env": "gridsim", **json.loads(path.read_text())} != asdict(sweep):
            raise click.UsageError(f"{path} is another sweep; run it with its own models, tasks, k, episode cap, "
                                   f"tier, bundle, pack and env: {path.read_text().strip()}")
        return
    if sweep.live:
        (hybrid_tasks if sweep.hybrid else live_tasks).generate(
            sweep.pack, sweep.out / "bundle", tier=sweep.tier, task_ids=sweep.tasks,
            episode_cap_usd=sweep.episode_cap_usd)
    else:
        tasks.generate(sweep.pack, sweep.out / "bundle", tier=sweep.tier, bundle=sweep.bundle, task_ids=sweep.tasks,
                       episode_cap_usd=sweep.episode_cap_usd)
    path.write_text(json.dumps(sweep.spec(), indent=2) + "\n")


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


def live_errors(day: dict) -> list[str]:
    """A live day's error taxonomy: nothing committed, a refused commit, an end-of-day shortfall, clipped execution,
    no planning call after watch 0."""
    g = day.get("grade") or {}
    found = [] if g.get("submitted") else ["no_commit"]
    if day.get("refusals"):
        found.append("refused")
    if g.get("end_shortfall_units"):
        found.append("end_short")
    if (day.get("excused") or {}).get("rows"):
        found.append("clipped")
    if not sum((day.get("planning_calls") or [0])[1:]):
        found.append("no_replanning")
    return found


def live_fields(day: dict) -> dict:
    """A scored live run's row fields from its day (data/get): the grade, references and play counts."""
    g = day["grade"]
    return {"profit": g["profit_usd"], "profit_idle": g["p_idle"], "profit_anchor": g["p_roll"],
            "profit_opt": g["p_hind"], "profit_naive": g["p_naive"], "naive_reward": g["naive_reward"],
            "capture": g["capture_vs_hindsight"], "regret_usd_per_mw": g["regret_usd_per_mw"],
            "excused_usd": g["excused_usd"], "commits": g["commits"], "watches": day["watches"],
            "watch_reached": day["frozen"][-1]["watch"] if day["frozen"] else None,
            "checks": sum(day["planning_calls"]), "planning_calls": day["planning_calls"],
            "da_position": day["da_position"], "schedule": day["executed"], "errors": live_errors(day),
            "audit_ok": day["audit"]["ok"]}


def hybrid_errors(day: dict) -> list[str]:
    """A hybrid day's error taxonomy: nothing committed, a refused commit, charged failure-to-provide, an end-of-day
    shortfall, governed hours, no planning call after watch 0, no AS revenue on a tier that offers AS."""
    g = day.get("grade") or {}
    found = [] if g.get("submitted") else ["no_commit"]
    found += [e for e, hit in [("refused", day.get("refusals")), ("ftp_charged", g.get("ftp_mwh_charged")),
                               ("end_short", g.get("end_short_mwh")), ("governed", g.get("governor_hours")),
                               ("no_replanning", not sum((day.get("planning_calls") or [0])[1:])),
                               ("as_unused", day.get("tier") != "energy" and not g.get("as_share"))] if hit]
    return found


def hybrid_fields(day: dict) -> dict:
    """A scored hybrid run's row fields from its day (data/get): the grade, its weight-0 rows and play counts."""
    g = day["grade"]
    return {"profit": g["profit_usd"], "profit_idle": g["p_idle"], "profit_anchor": g["p_anchor"],
            "profit_opt": g["p_hind"], "raw_ratio": g["raw_ratio"], "valid": bool(g["submitted"]),
            "capture": g["capture_vs_hindsight"], "energy_only_reward": g["energy_only_reward"],
            "as_share": g["as_share"], "clip_recovered_pct": g["clip_recovered_pct"],
            "curtailed_mwh": g["curtailed_mwh"], "ftp_mwh_charged": g["ftp_mwh_charged"],
            "ftp_mwh_excused": g["ftp_mwh_excused"], "governor_hours": g["governor_hours"],
            "refusals": g["refusals"], "commits": g["commits"], "watches": day["watches"],
            "watch_reached": day["frozen"][-1]["watch"] if day["frozen"] else None,
            "checks": sum(day["planning_calls"]), "planning_calls": day["planning_calls"], "book": day["book"],
            "da": day["da"], "schedule": day["executed"], "errors": hybrid_errors(day), "audit_ok": day["audit"]["ok"]}


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
           "schedule": episode.get("schedule"), "checks": episode.get("checks_used"),
           "calls": episode.get("calls_used"),
           "env_end_reason": episode.get("end_reason"),
           **{key: s.get(key) for key in ("end_reason", "effort", "turns", "tool_calls", "input_tokens",
                                          "output_tokens", "cached_tokens", "cache_write_tokens")},
           "cost_usd": spent, "priced_cost_usd": s.get("priced_cost_usd"), "failed_requests": s.get("failed_requests"),
           "transcript": transcript}
    if sweep.live and scored:
        row |= (hybrid_fields if sweep.hybrid else live_fields)(episode)
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
    inputs, graded by gridsim_core at the blind tier (its reward against the blind anchor, and its r_opt)."""
    out: dict = {"idle": 0.2}
    for name in BASELINES:
        out[name] = _r(_mean([r["refs"]["foresight"]["baselines"][name]["reward"] for r in rows]))
    blind = [r for r in rows if r.get("blind") and (r["refs"].get("blind") or {}).get("persist")]
    graded = [grade(r, r["refs"]["blind"]["persist"], "blind") for r in blind]
    out["persistence_dp_blind"] = _r(_mean([g["reward"] for g in graded]))
    out["persistence_dp_blind_r_opt"] = _r(_mean([g["r_opt"] for g in graded]))
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
        out = {"model": model, "trained": "base", "tier": tier, "bundle": bundle,
               "effort": effort[0] if effort else None,
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

    def tier_rows(self, tier: str) -> list[dict]:
        """The days played at ``tier``, which its baselines are averaged over when sweeps at two tiers share a
        board."""
        cells = [cell for cell in self.cells if cell[1] == tier]
        ids = {t for cell in cells for t in self.scored(cell)} or {t for s in self.sweeps if s.tier == tier
                                                                   for t in s.tasks}
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
    h = c["harness"]
    lines = ["# GridSim v1 board", "",
             f"Tasks: {c['tasks']['n']} battery-days ({', '.join(c['tasks']['packs'])}). Harness: {h['agent']}, "
             f"{h['max_turns']} turns, {h['max_tokens']} output tokens a turn, effort {h['effort']}. Reward: "
             f"{c['grading']['reward']}; foresight anchor P_opt, blind anchor max(P_persist, P_ridge). Mean R over "
             "tasks with a 95% bootstrap CI; valid: submitted and feasible.", "",
             f"Baselines on these tasks: idle {_f(b['idle'])}, clock {_f(b['clock'])}, threshold "
             f"{_f(b['threshold'])}, greedy {_f(b['greedy'])}, persistence-DP (blind, {b['n_blind']} tasks) "
             f"{_f(b['persistence_dp_blind'])}.", "",
             "| Model | Tier | Bundle | Tasks | Runs/planned | Mean R (95% CI) | Hindsight r_opt | Valid "
             "| Beats anchor | Checks used | $/episode | Spend |",
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


# ================================================================ live report
def _live_capture(r: dict, p: float) -> float | None:
    head = r["p_hind"] - r["p_idle"]
    return (p - r["p_idle"]) / head if head > 1e-9 else None


def live_baselines(rows: list[dict], tier: str) -> dict:
    """The references' means over these days at one tier: naive's reward under the shared contract, and naive's and
    the anchor's hindsight capture."""
    refs = [r["refs"] for r in rows if (r["refs"]["roll"].get(tier) or {}).get("p_roll") is not None]
    nc = [x for x in (_live_capture(r, r["p_naive"]) for r in refs) if x is not None]
    ac = [x for x in (_live_capture(r, r["roll"][tier]["p_roll"]) for r in refs) if x is not None]
    return {"tier": tier, "n": len(refs), "idle": 0.2, "anchor": 1.0,
            "naive": _r(_mean([r["roll"][tier]["naive_reward"] for r in refs])), "naive_capture": _r(_mean(nc)),
            "anchor_capture": _r(_mean(ac)),
            "anchor_commits": _r(_mean([r["roll"][tier]["commits"] for r in refs]), 2)}


def live_model(board: Board, cell) -> dict:
    name, tier, bundle = cell
    by_task = board.scored(cell)
    mean = {t: statistics.mean(r["reward"] for r in rs) for t, rs in by_task.items()}
    runs = [r for rs in by_task.values() for r in rs]
    rewards = list(mean.values())
    lo_hi = ci(rewards) if rewards else None
    capture = [statistics.mean(r["r_opt"] for r in rs) for rs in by_task.values()]
    costs = [priced(r) for r in runs if priced(r) is not None]
    known, unknown = board.spend(cell)
    effort = sorted({r.get("effort") for r in runs if r.get("effort")})
    return {"model": name, "trained": "base", "tier": tier, "bundle": bundle, "effort": effort[0] if effort else None,
            "runs": len(runs), "planned": board.planned(cell), "tasks": len(mean),
            "mean": _r(_mean(rewards)), "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None,
            "hindsight_capture": _r(_mean(capture)),
            "beats_anchor": _r(_mean([float(bool(r["beats_anchor"])) for r in runs])),
            "beats_naive": _r(_mean([float(r["reward"] > r["naive_reward"]) for r in runs])),
            "valid": _r(_mean([float(r["valid"]) for r in runs])),
            "submitted": _r(_mean([float(r["submitted"]) for r in runs])),
            "errors": {e: sum(e in (r["errors"] or []) for r in runs) for e in LIVE_ERRORS},
            "planning_calls": _r(_mean([r["checks"] for r in runs]), 2),
            "commits": _r(_mean([r["commits"] for r in runs]), 2),
            "finished_by_agent": _r(_mean([float(r["end_reason"] == "done") for r in runs])),
            "turns": _r(_mean([r["turns"] for r in runs if r["turns"] is not None]), 1),
            "usd_per_episode": _r(_mean(costs)), "spend_usd": round(known, 4), "unknown_spend_attempts": unknown}


def live_card(board: Board) -> dict:
    models = [live_model(board, cell) for cell in board.cells]
    rows = board.task_rows()
    split = sorted({r.get("split") for r in rows if r.get("split")})
    tiers = sorted({s.tier for s in board.sweeps})
    return {
        "env": "gridsim-live", "version": "v2", "live_version": LIVE_VERSION,
        "authors": [{"name": "Edgar Arakelyan", "github": "earakely-scale", "affiliation": "Scale AI"},
                    {"name": "Adithya S Kolavi", "github": "adithya-s-k", "affiliation": "Hugging Face"}],
        "framework": "agentenv",
        "tasks": {"split": split[0] if len(split) == 1 else split, "n": len(rows), "unit": "live battery-days",
                  "packs": sorted({s.pack for s in board.sweeps}),
                  "source": "ERCOT NP4-180-ER DAM and NP6-785-ER RT hub/LZ SPPs; EIA-860 archetypes",
                  "selection": "the live eligibility filter (RT-DA divergence, anchor over naive, hindsight headroom)"},
        "harness": {"agent": live_tasks.AGENT, "env": "gridsim-live", "tools": [*TOOLS, "get_time"],
                    "max_turns": MAX_TURNS, "planning_calls_per_watch": PLANNING_CALLS,
                    "max_tokens": live_tasks.MODEL_PARAMS["max_tokens"], "effort": live_tasks.EFFORT,
                    "path": "A: every step ran through AgentEnv (gateway env, triggers, virtual clock)"},
        "grading": {"reference": "exact DPs on the true day; LP bound reported",
                    "reward": "clip(0.2+0.8(P-P_idle)/(P_roll-P_idle),0,1); no accepted commit scores 0",
                    "anchor": "P_roll: the notice-blind rolling re-planner under the agent's freeze, budget, DA rule",
                    "hindsight_capture": "(P-P_idle)/(P_hind-P_idle), a weight-0 row",
                    "audit": "weight 0; a failed audit makes the run unscored",
                    "excused": "derate clipping inside the freeze", "judge": False},
        "baselines": {t: live_baselines(board.tier_rows(t), t) for t in tiers},
        "models": models,
        "errors": {"taxonomy": list(LIVE_ERRORS),
                   "meaning": {"no_commit": "no accepted commit_da or commit_schedule (scores 0)",
                               "refused": "a refused commit", "end_short": "SoC at 24:00 below s_end_min",
                               "clipped": "an interval executed clipped", "no_replanning": "no planning call after "
                                                                                           "watch 0"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps],
        "links": {"runs": "hf dataset", "replays": "hf space", "code": "github"},
    }


def live_board_md(c: dict) -> str:
    h = c["harness"]
    lines = ["# GridSim v2 live board", "",
             f"Tasks: {c['tasks']['n']} live battery-days ({', '.join(c['tasks']['packs'])}). Harness: {h['agent']} "
             f"on {h['env']}, {h['max_turns']} turns, {h['planning_calls_per_watch']} planning calls a watch, "
             f"{h['max_tokens']} output tokens a turn, effort {h['effort']}. Reward: {c['grading']['reward']}; the "
             "anchor (1.0) is the notice-blind rolling re-planner. Mean R over days with a 95% bootstrap CI.", ""]
    for tier, b in c["baselines"].items():
        lines.append(f"Baselines ({tier}, {b['n']} days): idle {_f(b['idle'])}, naive (v1's plan, never re-planned) "
                     f"{_f(b['naive'])}, anchor {_f(b['anchor'])}; hindsight capture naive "
                     f"{_f(b['naive_capture'])}, anchor {_f(b['anchor_capture'])}.")
    lines += ["", "| Model | Tier | Days | Runs/planned | Mean R (95% CI) | Hindsight capture | Beats anchor "
              "| Beats naive | Valid | Planning calls | Commits | Finished | $/episode | Spend |",
              "|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci95 = f" ({_f(m['ci95'][0])} to {_f(m['ci95'][1])})" if m["ci95"] else ""
        lines.append(" | ".join([
            f"| {m['model']}", m["tier"], str(m["tasks"]), f"{m['runs']}/{m['planned']}", _f(m["mean"]) + ci95,
            _f(m["hindsight_capture"]), _f(m["beats_anchor"]), _f(m["beats_naive"]), _f(m["valid"]),
            _f(m["planning_calls"], ".2f"), _f(m["commits"], ".2f"), _f(m["finished_by_agent"]),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}",
            f"${m['spend_usd']:.2f}" + (f" + {m['unknown_spend_attempts']} unknown" if m["unknown_spend_attempts"]
                                        else "")]) + " |")
    lines += ["", "## Errors", "", "Scored runs by what went wrong; a run can show several.", "",
              "| Model | Tier | " + " | ".join(LIVE_ERRORS) + " |", "|---|---|" + "---:|" * len(LIVE_ERRORS)]
    lines += [f"| {m['model']} | {m['tier']} | " + " | ".join(str(m["errors"][e]) for e in LIVE_ERRORS) + " |"
              for m in c["models"]]
    return "\n".join(lines) + "\n"


# ================================================================ hybrid report
def hybrid_baselines(rows: list[dict], tier: str) -> dict:
    """The references' means over these site-days at one tier: each baseline's stored reward, the energy-only anchor's
    reward against this tier's anchor, and the anchor's hindsight capture."""
    refs = [r["refs"] for r in rows if (r["refs"].get(tier) or {}).get("p_anchor") is not None]
    out: dict = {"tier": tier, "n": len(refs), "idle": 0.2, "anchor": 1.0}
    for name in HYBRID_BASELINES:
        out[name] = _r(_mean([r[tier]["baselines"][name]["reward"] for r in refs
                              if name in (r[tier].get("baselines") or {})]))
    out["energy_only"] = _r(_mean([reward_value(r[tier]["p_energy_only"], r["p_idle"], r[tier]["p_anchor"])
                                   for r in refs if r[tier].get("p_energy_only") is not None]))
    caps = [_live_capture({"p_idle": r["p_idle"], "p_hind": r[tier]["p_hind"]}, r[tier]["p_anchor"])
            for r in refs if r[tier].get("p_hind") is not None]
    out["anchor_capture"] = _r(_mean([x for x in caps if x is not None]))
    return out


def hybrid_model(board: Board, cell) -> dict:
    name, tier, bundle = cell
    by_task = board.scored(cell)
    mean = {t: statistics.mean(r["reward"] for r in rs) for t, rs in by_task.items()}
    runs = [r for rs in by_task.values() for r in rs]
    rewards = list(mean.values())
    lo_hi = ci(rewards) if rewards else None
    costs = [priced(r) for r in runs if priced(r) is not None]
    known, unknown = board.spend(cell)
    effort = sorted({r.get("effort") for r in runs if r.get("effort")})
    sponge = {t: ((board.tasks.get(t, {}).get("refs") or {}).get(tier) or {}).get("baselines", {}).get("sponge")
              for t in mean}
    stratum = {t: (board.tasks.get(t, {}).get("tags") or {}).get("as_stratum") for t in mean}

    def avg(key: str, digits: int = 4):
        return _r(_mean([r[key] for r in runs if r.get(key) is not None]), digits)

    return {"model": name, "trained": "base", "tier": tier, "bundle": bundle, "effort": effort[0] if effort else None,
            "runs": len(runs), "planned": board.planned(cell), "tasks": len(mean),
            "mean": _r(_mean(rewards)), "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None,
            "by_as_stratum": {s: _r(_mean([v for t, v in mean.items() if stratum[t] == s])) for s in STRATA},
            "hindsight_capture": _r(_mean([statistics.mean(r["r_opt"] for r in rs) for rs in by_task.values()])),
            "beats_anchor": _r(_mean([float(bool(r["beats_anchor"])) for r in runs])),
            "beats_sponge": _r(_mean([float(v > sponge[t]["reward"]) for t, v in mean.items() if sponge[t]])),
            "valid": _r(_mean([float(r["valid"]) for r in runs])),
            "as_share": avg("as_share"), "energy_only_reward": avg("energy_only_reward"),
            "clip_recovered_pct": avg("clip_recovered_pct", 2), "ftp_mwh_charged": avg("ftp_mwh_charged", 3),
            "ftp_mwh_excused": avg("ftp_mwh_excused", 3), "refusals": avg("refusals", 2),
            "governor_hours": avg("governor_hours", 2),
            "errors": {e: sum(e in (r["errors"] or []) for r in runs) for e in HYBRID_ERRORS},
            "planning_calls": _r(_mean([r["checks"] for r in runs]), 2), "commits": avg("commits", 2),
            "finished_by_agent": _r(_mean([float(r["end_reason"] == "done") for r in runs])),
            "turns": _r(_mean([r["turns"] for r in runs if r["turns"] is not None]), 1),
            "usd_per_episode": _r(_mean(costs)), "spend_usd": round(known, 4), "unknown_spend_attempts": unknown}


def hybrid_card(board: Board) -> dict:
    models = [hybrid_model(board, cell) for cell in board.cells]
    rows = board.task_rows()
    split = sorted({r.get("split") for r in rows if r.get("split")})
    tiers = sorted({s.tier for s in board.sweeps})
    flags = sorted({f"{k}: {v}" for r in rows for k, v in (r.get("flags") or {}).items() if v})
    return {
        "env": HYBRID_ENV, "version": "v3", "hybrid_version": HYBRID_VERSION, "contract_version": CONTRACT_VERSION,
        "authors": [{"name": "Edgar Arakelyan", "github": "earakely-scale", "affiliation": "Scale AI"},
                    {"name": "Adithya S Kolavi", "github": "adithya-s-k", "affiliation": "Hugging Face"}],
        "framework": "agentenv",
        "tasks": {"split": split[0] if len(split) == 1 else split, "n": len(rows), "unit": "hybrid site-days",
                  "packs": sorted({s.pack for s in board.sweeps}),
                  "as_strata": {s: sum((r.get("tags") or {}).get("as_stratum") == s for r in rows) for s in STRATA},
                  "source": "ERCOT DAM/RT SPPs and DAM AS MCPCs; NP4-745 solar (availability proxy); EIA-860 sites or "
                            "archetypes",
                  "selection": "low-spread, sponge-near-anchor and P_anchor - P_idle < $500 days dropped; Uri +-3 "
                               "days out", "flags": flags},
        "harness": {"agent": live_tasks.AGENT, "env": HYBRID_ENV, "tools": [*HYBRID_TOOLS, "get_time"],
                    "max_turns": MAX_TURNS, "planning_calls_per_watch": PLANNING_CALLS,
                    "max_tokens": hybrid_tasks.MODEL_PARAMS["max_tokens"], "effort": live_tasks.EFFORT,
                    "path": "A: every step ran through AgentEnv (gateway env, triggers with deploy payloads, virtual "
                            "clock)"},
        "grading": {"reference": "information-matched rolling MILP (HiGHS) played through the Session",
                    "reward": "clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted commit scores 0",
                    "idle": "the solar-only plant", "anchor": "P_anchor: one MILP solve per watch on the day as known "
                                                              "then, the same freeze, call budget and governor",
                    "hindsight_capture": "(P-P_idle)/(P_hind-P_idle), a weight-0 row",
                    "weight_0": ["audit", "hindsight_capture", "energy_only", "as_share", "clip_recovered", "ftp"],
                    "audit": "weight 0; a failed audit makes the run unscored",
                    "excused": "AS shortfall or end-SoC shortfall from drift or deployments after the hour froze",
                    "judge": False},
        "baselines": {t: hybrid_baselines(board.tier_rows(t), t) for t in tiers},
        "models": models,
        "errors": {"taxonomy": list(HYBRID_ERRORS),
                   "meaning": {"no_commit": "no accepted hour in any commit (scores 0)",
                               "refused": "a commit with a refused hour",
                               "ftp_charged": "AS failure-to-provide charged",
                               "end_short": "SoC at 24:00 below s_end_min", "governed": "the governor moved an hour",
                               "no_replanning": "no planning call after watch 0",
                               "as_unused": "no AS revenue on a tier that offers AS"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps],
        "links": {"runs": "hf dataset", "replays": "hf space", "code": "github"},
    }


def hybrid_board_md(c: dict) -> str:
    h = c["harness"]
    lines = ["# GridSim v3 hybrid board", "",
             f"Tasks: {c['tasks']['n']} hybrid site-days ({', '.join(c['tasks']['packs'])}; AS strata "
             + ", ".join(f"{k} {v}" for k, v in c["tasks"]["as_strata"].items()) + f"). Harness: {h['agent']} on "
             f"{h['env']}, {h['max_turns']} turns, {h['planning_calls_per_watch']} planning calls a watch, "
             f"{h['max_tokens']} output tokens a turn, effort {h['effort']}. Reward: {c['grading']['reward']}; idle "
             "(0.2) is the solar-only plant, the anchor (1.0) the information-matched rolling MILP. Mean R over days "
             "with a 95% bootstrap CI.", ""]
    if c["tasks"]["flags"]:
        lines += ["Proxies and flags: " + "; ".join(c["tasks"]["flags"]) + ".", ""]
    for tier, b in c["baselines"].items():
        lines.append(f"Baselines ({tier}, {b['n']} days): idle {_f(b['idle'])}, sponge {_f(b['sponge'])}, AS-hog "
                     f"{_f(b['as_hog'])}, v2 energy-only {_f(b['v2_energy'])}, energy-only MILP "
                     f"{_f(b['energy_only'])}, anchor {_f(b['anchor'])}; anchor hindsight capture "
                     f"{_f(b['anchor_capture'])}.")
    lines += ["", "| Model | Tier | Days | Runs/planned | Mean R (95% CI) | R low/mid/high AS | Hindsight capture "
              "| Beats anchor | Beats sponge | AS share | Clip recovered % | FTP MWh | Refusals | Planning calls "
              "| Finished | $/episode | Spend |",
              "|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci95 = f" ({_f(m['ci95'][0])} to {_f(m['ci95'][1])})" if m["ci95"] else ""
        lines.append(" | ".join([
            f"| {m['model']}", m["tier"], str(m["tasks"]), f"{m['runs']}/{m['planned']}", _f(m["mean"]) + ci95,
            "/".join(_f(m["by_as_stratum"][s]) for s in STRATA), _f(m["hindsight_capture"]),
            _f(m["beats_anchor"]), _f(m["beats_sponge"]), _f(m["as_share"]), _f(m["clip_recovered_pct"], ".1f"),
            _f(m["ftp_mwh_charged"]), _f(m["refusals"], ".2f"), _f(m["planning_calls"], ".2f"),
            _f(m["finished_by_agent"]), "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}",
            f"${m['spend_usd']:.2f}" + (f" + {m['unknown_spend_attempts']} unknown" if m["unknown_spend_attempts"]
                                        else "")]) + " |")
    lines += ["", "## Errors", "", "Scored runs by what went wrong; a run can show several.", "",
              "| Model | Tier | " + " | ".join(HYBRID_ERRORS) + " |", "|---|---|" + "---:|" * len(HYBRID_ERRORS)]
    lines += [f"| {m['model']} | {m['tier']} | " + " | ".join(str(m["errors"][e]) for e in HYBRID_ERRORS) + " |"
              for m in c["models"]]
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


REPORTS = {"gridsim": (card, board_md, CARD, BOARD), LIVE_ENV: (live_card, live_board_md, LIVE_CARD, LIVE_BOARD),
           HYBRID_ENV: (hybrid_card, hybrid_board_md, HYBRID_CARD, HYBRID_BOARD)}


def report(sweeps: list[Sweep], card_path: Path | None = None, board_path: Path | None = None) -> dict:
    """v1 sweeps to results/eval-v1.json and board.md; live sweeps to eval-v2.json and board-v2.md; hybrid sweeps to
    eval-v3.json and board-v3.md."""
    if len({s.env for s in sweeps}) > 1:
        raise click.UsageError("report v1 and live sweeps separately, and hybrid sweeps on their own: their references "
                               "differ")
    make_card, make_board, default_card, default_board = REPORTS[sweeps[0].env]
    board = Board(sweeps)
    c = make_card(board)
    card_path = card_path or default_card
    board_path = board_path or default_board
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(c, indent=2) + "\n")
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(make_board(c) + "\n## Unscored runs\n\n" + "\n".join(unscored(board)) + "\n")
    return c


@click.group("sweep")
def sweep_group():
    """Sweeps: a pack's battery-days over models and reps at one tier and harness under a spend cap, and the report."""


@sweep_group.command("run")
@click.option("--name", required=True,
              help="The sweep's name: its results go to results/runs/<name>/raw/, its Episode JSON to "
                   "results/runs/<name>/.")
@click.option("--models", required=True, help="Comma-separated LiteLLM model ids, e.g. openai/gpt-6.1-sol.")
@click.option("--tasks", "task_spec", required=True,
              help="all, N (the pack's first N), or comma-separated task ids of the pack the tier can play.")
@click.option("--env", type=click.Choice(ENVS), default="gridsim", show_default=True,
              help=f"gridsim: the v1 battery desk; {LIVE_ENV}: a live pack's days played live in watches; "
                   f"{HYBRID_ENV}: a hybrid pack's solar-plus-storage site-days played live.")
@click.option("--pack", type=click.Choice(PACK_NAMES + LIVE_PACK_NAMES + HYBRID_PACK_NAMES),
              help=f"The task pack. Default: {EVAL_PACK}, {LIVE_EVAL_PACK} with --env {LIVE_ENV}, or "
                   f"{HYBRID_EVAL_PACK} with --env {HYBRID_ENV}.")
@click.option("--tier", type=click.Choice(LIVE_TIERS + HYBRID_TIERS),
              help="foresight (the default) or blind; live days also take short and freeze6h; hybrid days take "
                   "energy, reserves (the default) or rtcb.")
@click.option("--bundle", type=click.Choice(list(tasks.BUNDLES)), default="full", show_default=True,
              help="full: three checks; oneshot: submit_schedule only. Not for live or hybrid days.")
@click.option("--cap-usd", type=float, required=True,
              help="The model spend the sweep stays within: no attempt starts that could take it past this at the "
                   "episode cap.")
@click.option("--k", type=click.IntRange(min=1), default=1, show_default=True, help="Reps of each model and task.")
@click.option("--episode-cap-usd", type=float, default=1.0, show_default=True,
              help="An episode's cost cap, passed to the agent as GRIDSIM_MAX_COST_USD.")
@click.option("--parallel", type=click.IntRange(min=1), default=4, show_default=True, help="Attempts at a time.")
def run_command(name: str, models: str, task_spec: str, env: str, pack: str | None, tier: str | None, bundle: str,
                cap_usd: float, k: int, episode_cap_usd: float, parallel: int):
    """Play each model on each task k times, one `agent-env run` per attempt, logged under results/runs/<name>/raw/logs.
    Each attempt is a line of results.jsonl; a failed one is retried up to twice, and running the sweep again plays
    the runs that aren't final yet. Ctrl-C tears the running attempts down."""
    if "" in models.split(","):
        raise click.UsageError("--models takes comma-separated model ids, none empty")
    live, hybrid = env == LIVE_ENV, env == HYBRID_ENV
    pack = pack or (LIVE_EVAL_PACK if live else HYBRID_EVAL_PACK if hybrid else EVAL_PACK)
    tier = tier or ("reserves" if hybrid else "foresight")
    if hybrid != (pack in HYBRID_PACK_NAMES):
        raise click.UsageError(f"{pack} is {'not ' if hybrid else ''}a hybrid pack; {env} plays "
                               f"{'hybrid' if hybrid else 'v1 or live'} packs")
    if live != (pack in LIVE_PACK_NAMES):
        raise click.UsageError(f"{pack} is {'not ' if live else ''}a live pack; {env} plays "
                               f"{'live' if live else 'v1'} packs")
    if hybrid != (tier in HYBRID_TIERS):
        raise click.UsageError(f"{env} plays the tiers {', '.join(HYBRID_TIERS)}, not {tier}" if hybrid
                               else f"{tier} is a hybrid tier; {env} doesn't play it")
    if (live or hybrid) and bundle != "full":
        raise click.UsageError("--bundle is for v1 sweeps; a live day has one harness")
    if not (live or hybrid) and tier not in TIERS:
        raise click.UsageError(f"the v1 packs have the tiers {', '.join(TIERS)}, not {tier}")
    sweep = Sweep(name, models.split(","), task_ids(task_spec, pack, tier), k, episode_cap_usd, tier,
                  "live" if live or hybrid else bundle, pack, env)
    if not sweep.tasks:
        raise click.UsageError(f"no {tier} tasks in {pack} for --tasks {task_spec}")
    prepare(sweep)
    raise SystemExit(run(sweep, cap_usd, parallel))


@sweep_group.command("report")
@click.argument("names", nargs=-1, required=True)
@click.option("--card", "card_path", type=click.Path(dir_okay=False, path_type=Path),
              help=f"The eval card to write. Default: {CARD}, or {LIVE_CARD} for live sweeps.")
@click.option("--board", "board_path", type=click.Path(dir_okay=False, path_type=Path),
              help=f"The Markdown board to write. Default: {BOARD}, or {LIVE_BOARD} for live sweeps.")
def report_command(names: tuple[str, ...], card_path: Path | None, board_path: Path | None):
    """Report the sweeps NAMES: each model at each tier and harness, its mean reward with a 95% bootstrap CI, hindsight
    capture, valid rate, error taxonomy, checks used and cost, next to the pack references' baselines. Live sweeps
    report against the live references: naive, the rolling anchor and hindsight."""
    sweeps = [load(name) for name in names]
    c = report(sweeps, card_path, board_path)
    _, _, default_card, default_board = REPORTS[sweeps[0].env]
    click.echo(f"Wrote {card_path or default_card} and {board_path or default_board}: {len(c['models'])} model rows "
               f"over {c['tasks']['n']} tasks")
