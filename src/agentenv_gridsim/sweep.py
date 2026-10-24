"""`agent-env gridsim sweep`: a pack's battery-days over models and reps at one tier and harness under a spend cap, one
`agent-env run` process per attempt, retried and resumed from results.jsonl; and the report: results/eval-v1.json (the
FineEnvs eval card with the baselines from the pack's references) and results/board.md. With --env gridsim-live, a
live pack's days played live (the harness is "live"), reported to results/eval-v2.json and results/board-v2.md
against the live references; with --env gridsim-hybrid, a hybrid pack's site-days, reported to results/eval-v3.json and
results/board-v3.md against the hybrid references; with --env gridsim-forecast, a forecast pack's windows, reported to
results/eval-v4.json and results/board-v4.md against the forecast references; with --env gridsim-market, a market
pack's floors, reported to results/eval-v5.json and results/board-v5.md against the market references, on both
scorings."""

import json
import re
import signal
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import click
import numpy as np
from agent_env.config import get_config
from agent_env.store.routing import namespace_routing
from agent_env.task.store import get_task_instance_store

from gridsim_core import CONTRACT_VERSION
from gridsim_core.forecast import DAM_SUBMITS, FORECAST_CALLS, FORECAST_ENV, FORECAST_VERSION
from gridsim_core.forecast import MAX_TURNS as FORECAST_MAX_TURNS
from gridsim_core.forecast import TIERS as FORECAST_TIERS
from gridsim_core.forecast import TOOLS as FORECAST_TOOLS
from gridsim_core.grade import grade, reward_value
from gridsim_core.hybrid import HYBRID_ENV, HYBRID_VERSION
from gridsim_core.hybrid import TIERS as HYBRID_TIERS
from gridsim_core.hybrid import TOOLS as HYBRID_TOOLS
from gridsim_core.live import LIVE_ENV, LIVE_VERSION, MAX_TURNS, PLANNING_CALLS, TOOLS
from gridsim_core.live import TIERS as LIVE_TIERS
from gridsim_core.market import DATA_CALLS as MARKET_DATA_CALLS
from gridsim_core.market import MARKET_ENV, MARKET_VERSION
from gridsim_core.market import MAX_TURNS as MARKET_MAX_TURNS
from gridsim_core.market import PLANNING_CALLS as MARKET_PLANNING_CALLS
from gridsim_core.market import TIERS as MARKET_TIERS
from gridsim_core.market import TOOLS as MARKET_TOOLS

from . import forecast_tasks, hybrid_tasks, live_tasks, market_tasks, tasks
from .forecast import FORECAST_PACK_NAMES
from .hybrid import HYBRID_PACK_NAMES
from .live import LIVE_PACK_NAMES
from .market import MARKET_PACK_NAMES
from .server import PACK_NAMES, TIERS

AGENT_ENV = [sys.executable, "-m", "agent_env.cli"]
RUNS = Path("results/runs")
CARD = Path("results/eval-v1.json")
BOARD = Path("results/board.md")
LIVE_CARD = Path("results/eval-v2.json")
LIVE_BOARD = Path("results/board-v2.md")
HYBRID_CARD = Path("results/eval-v3.json")
HYBRID_BOARD = Path("results/board-v3.md")
FORECAST_CARD = Path("results/eval-v4.json")
FORECAST_BOARD = Path("results/board-v4.md")
MARKET_CARD = Path("results/eval-v5.json")
MARKET_BOARD = Path("results/board-v5.md")
EVAL_PACK = "ercot-dam-v1-eval"
LIVE_EVAL_PACK = "gridsim-live-eval"
HYBRID_EVAL_PACK = "ercot-hybrid-v3-eval"
FORECAST_EVAL_PACK = "ercot-front-v4-eval"
MARKET_EVAL_PACK = "gridsim-market-eval"
ENVS = ("gridsim", LIVE_ENV, HYBRID_ENV, FORECAST_ENV, MARKET_ENV)
LIVE_ERRORS = ("no_commit", "refused", "end_short", "clipped", "no_replanning")
HYBRID_ERRORS = ("no_commit", "refused", "ftp_charged", "end_short", "governed", "no_replanning", "as_unused")
HYBRID_BASELINES = ("sponge", "as_hog", "v2_energy")
FORECAST_ERRORS = ("no_commit", "dam_missed", "refused", "ftp_charged", "end_short", "governed", "no_replanning",
                   "no_forecasts", "as_unused")
FORECAST_BASELINES = ("naive", "blind", "roll", "roll3")
LABELS_V4 = ("front", "calm")
MARKET_ERRORS = ("no_submit", "refused", "idle", "mitigated", "clipped", "end_short", "no_schedule", "price_talk")
MARKET_BASELINES = ("max_withhold", "price_taker", "replay_A")
STRATA = ("low", "mid", "high")
NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
INSTANCE = re.compile(r"(\d+(?:\.\d+)?)s, instance (\S+)")
STOPS = ("model_endpoint", "unpriced_model")
MAX_ATTEMPTS = 3
POLL_SECONDS = 2.0
ERRORS = ("overfill", "sell_before_charge", "rate", "cycle_cap", "end_short", "all_idle")
VIOLATIONS = {"soc_above_N": "overfill", "soc_below_0": "sell_before_charge", "rate": "rate", "cycle_cap": "cycle_cap"}
BASELINES = ("random", "clock", "threshold", "greedy")
OPTIMAL = 0.99
RESAMPLES = 10_000
LABELS = {"openai/gpt-6.1-sol": "GPT-6.1 Sol"}
DAY_TYPES = {"negative_prices": lambda t: t["tags"]["neg_hours"] > 0, "spike": lambda t: bool(t["tags"]["spike"]),
             "neither": lambda t: not t["tags"]["neg_hours"] and not t["tags"]["spike"]}
HUB = "https://huggingface.co"
LINKS = {"runs": f"{HUB}/datasets/earakely-scale/GridSimEnv-AgentEnv/viewer/v1_episodes",
         "replays": f"{HUB}/spaces/earakely-scale/GridSimEnv-AgentEnv",
         "code": "https://github.com/earakely-scale/agentenv-gridsim-plugin"}


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
        """Played live in watches: gridsim-live, gridsim-hybrid or gridsim-forecast."""
        return self.env in (LIVE_ENV, HYBRID_ENV, FORECAST_ENV)

    @property
    def hybrid(self) -> bool:
        return self.env == HYBRID_ENV

    @property
    def forecast(self) -> bool:
        return self.env == FORECAST_ENV

    @property
    def market(self) -> bool:
        return self.env == MARKET_ENV

    def spec(self) -> dict:
        """sweep.json: the fields, without env for a v1 sweep, so v1 sweeps resume as they were written."""
        return {k: v for k, v in asdict(self).items() if k != "env" or self.live or self.market}

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
    module = (market_tasks if pack in MARKET_PACK_NAMES else hybrid_tasks if pack in HYBRID_PACK_NAMES
              else live_tasks if pack in LIVE_PACK_NAMES else forecast_tasks if pack in FORECAST_PACK_NAMES else tasks)
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
    if sweep.market:
        market_tasks.generate(sweep.pack, sweep.out / "bundle", tier=sweep.tier, compliant=sweep.bundle == "compliant",
                              task_ids=sweep.tasks, episode_cap_usd=sweep.episode_cap_usd)
    elif sweep.live:
        (hybrid_tasks if sweep.hybrid else forecast_tasks if sweep.forecast else live_tasks).generate(
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


def forecast_errors(w: dict) -> list[str]:
    """A forecast window's error taxonomy: nothing accepted, a missed DAM gate, a refused hour, charged
    failure-to-provide, an end-of-window shortfall, governed hours, no planning call after watch 0, no forecast call
    on a tier that serves them, no AS revenue on a tier that offers AS."""
    g = w.get("grade") or {}
    return [e for e, hit in [("no_commit", not g.get("submitted")), ("dam_missed", g.get("dam_missed")),
                             ("refused", w.get("refusals")), ("ftp_charged", g.get("ftp_mwh_charged")),
                             ("end_short", g.get("end_short_mwh")), ("governed", g.get("governor_hours")),
                             ("no_replanning", not sum((w.get("planning_calls") or [0])[1:])),
                             ("no_forecasts", w.get("tier") != "blind" and not g.get("forecast_calls")),
                             ("as_unused", w.get("tier") != "front-lite" and not (g.get("cash") or {}).get("as_da"))]
            if hit]


def forecast_fields(w: dict) -> dict:
    """A scored forecast run's row fields from its window (data/get): the grade, its weight-0 rows and play counts."""
    g = w["grade"]
    return {"profit": g["profit_usd"], "profit_idle": g["p_idle"], "profit_anchor": g["p_anchor"],
            "profit_opt": g["p_hind"], "raw_ratio": g["raw_ratio"], "valid": bool(g["submitted"]),
            "source": g["source"], "paired_vs_anchor": g["paired_vs_anchor"], "r_roll3": g["r_roll3"],
            "forecast_value": g["forecast_value"], "dam_missed": g["dam_missed"], "dam_submits": g["dam_submits"],
            "forecast_calls": g["forecast_calls"], "as_usd": (g.get("cash") or {}).get("as_da"),
            "ftp_mwh_charged": g["ftp_mwh_charged"], "ftp_mwh_excused": g["ftp_mwh_excused"],
            "end_short_mwh": g["end_short_mwh"], "governor_hours": g["governor_hours"], "refusals": g["refusals"],
            "commits": g["commits"], "watches": w["watches"],
            "watch_reached": w["frozen"][-1]["watch"] if w["frozen"] else None,
            "checks": sum(w["planning_calls"]), "planning_calls": w["planning_calls"],
            "forecast_calls_by_watch": w["forecast_calls"], "dam": w["dam"], "book": w["book"],
            "schedule": w["executed"], "errors": forecast_errors(w), "audit_ok": w["audit"]["ok"]}


def market_errors(floor: dict) -> list[str]:
    """A floor's error taxonomy: no valid offer, a refused offer or commit, an offer with no blocks, a mitigated hour,
    delivery clipped off the awards, an end-of-day shortfall, no physical schedule in floor-day, price talk."""
    g = floor.get("grade") or {}
    return [e for e, hit in [("no_submit", not g.get("submitted")), ("refused", floor.get("refusals")),
                             ("idle", g.get("submitted") and not (floor.get("offer") or {}).get("hours")),
                             ("mitigated", g.get("mitigated_hours")), ("clipped", g.get("clipped_hours")),
                             ("end_short", (g.get("pnl") or {}).get("shortfall_usd")),
                             ("no_schedule", floor.get("tier") == "floor-day"
                              and not any(c["accepted"] for c in floor.get("commits") or [])),
                             ("price_talk", (g.get("conduct") or {}).get("message_flags"))] if hit]


def market_fields(floor: dict) -> dict:
    """A scored market run's row fields from its floor (data/get): both scorings, the references, the weight-0 rows
    and play counts."""
    g = floor["grade"]
    contract = g.get("contract") or {}
    return {"profit": g["profit_usd"], "profit_idle": g["p_idle"], "profit_anchor": g["p_anchor"],
            "profit_opt": g["p_br"], "raw_ratio": g["raw_ratio"], "valid": bool(g["submitted"]),
            "market_reward": g["reward"], "compliant_reward": g["compliant_reward"], "compliant": floor["compliant"],
            "regret_usd": g["regret_usd"], "regret_norm": g["regret_norm"], "eps_nash": g["eps_nash"],
            "welfare_ratio": g["welfare_ratio"], "dwl_usd": g["dwl_usd"], "rank": g["rank"],
            "mitigated_hours": len(g["mitigated_hours"]), "withholding_index": g["conduct"]["withholding_index"],
            "message_flags": g["conduct"]["message_flags"], "contracts": len(contract.get("contracts") or []),
            "contract_value_usd": contract.get("value_at_signing_usd"),
            "contract_settled_usd": contract.get("settled_usd"), "refusals": len(floor["refusals"]),
            "commits": sum(c["accepted"] for c in floor["commits"]), "watches": floor["watches"],
            "watch_reached": floor["frozen"][-1]["watch"] if floor["frozen"] else None,
            "checks": sum(floor["planning_calls"]), "planning_calls": floor["planning_calls"],
            "data_calls": sum(floor["data_calls"]), "offer": floor["offer"], "schedule": floor["executed"],
            "errors": market_errors(floor), "audit_ok": floor["audit"]["ok"]}


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
           "r_opt": (rows.get("hindsight_capture") or rows.get("r_hind") or {}).get("score") if scored else None,
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
    if sweep.market and scored:
        row |= market_fields(episode)
    elif sweep.live and scored:
        row |= (hybrid_fields if sweep.hybrid else forecast_fields if sweep.forecast else live_fields)(episode)
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

def ci(xs: list[float], n: int = RESAMPLES, seed: int = 0) -> tuple[float, float]:
    """The 95% bootstrap interval of the mean over n resamples of xs."""
    a = np.asarray(xs, dtype=float)
    means = np.sort(a[np.random.default_rng(seed).integers(0, len(a), (n, len(a)))].mean(axis=1))
    return float(means[int(0.025 * n)]), float(means[int(0.975 * n)])


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
    """The references' mean rewards over these tasks: idle by construction; clock, threshold, greedy and random as
    the pack stored them on the day's prices; persistence-DP, its D-1-price schedule settled on the day, on the tasks
    with blind inputs, graded by gridsim_core at the blind tier (its reward against the blind anchor, and its r_opt)."""
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


def references(rows: list[dict], tier: str) -> dict:
    """Each reference policy graded at the tier on these tasks, its mean reward and r_opt: idle, the pack's random,
    clock, threshold and greedy schedules and the DP optimum on every task; persistence-DP, ridge-DP and the blind
    anchor (the better of the two on the day) on the tasks with blind inputs."""
    graded: dict[str, list[dict]] = {}
    for t in rows:
        f, b = t["refs"]["foresight"], t["refs"].get("blind")
        plays = {"idle": [0] * len(t["prices"]), **{k: f["baselines"][k]["schedule"] for k in BASELINES}}
        if b:
            plays |= {"persistence_dp": b["persist"], "ridge_dp": b["ridge"],
                      "blind_anchor": b["persist"] if b["p_persist"] >= b["p_ridge"] else b["ridge"]}
        plays["dp_optimum"] = f["opt"]
        for name, schedule in plays.items():
            graded.setdefault(name, []).append(grade(t, schedule, tier))
    return {name: {"reward": _r(_mean([g["reward"] for g in gs])), "r_opt": _r(_mean([g["r_opt"] for g in gs])),
                   "n": len(gs)} for name, gs in graded.items()}


def lp(rows: list[dict]) -> dict:
    """The LP relaxation bound against the exact DP optimum over these tasks, in $."""
    f = [r["refs"]["foresight"] for r in rows]
    gaps = [x["p_lp"] - x["p_opt"] for x in f]
    return {"p_opt_mean": _r(_mean([x["p_opt"] for x in f]), 2), "p_lp_mean": _r(_mean([x["p_lp"] for x in f]), 2),
            "gap_usd_mean": _r(_mean(gaps), 2), "gap_usd_max": _r(max(gaps), 2),
            "tasks_with_gap": sum(g > 0.005 for g in gaps), "n": len(f)}


class Board:
    """The named sweeps' scored runs, one cell per (model, pack, tier, bundle): each task's value is the mean of its
    scored reps; the CIs bootstrap over tasks. ``amend`` maps a sweep to the sweep that re-ran its unscored runs under
    an amendment: the cell's headline then takes a run's score from either, and its ``prereg`` from the registered
    sweep alone. ``columns`` labels a sweep's cells."""

    def __init__(self, sweeps: list[Sweep], amend: dict[str, Sweep] | None = None,
                 columns: dict[str, str] | None = None):
        self.sweeps, self.amend, self.columns = sweeps, amend or {}, columns or {}
        named = {s.name: s for s in sweeps}
        for name, a in self.amend.items():
            s = named.get(name)
            if s is None or (a.models, a.tier, a.bundle, a.pack) != (s.models, s.tier, s.bundle, s.pack) \
                    or not set(a.tasks) <= set(s.tasks):
                raise click.UsageError(f"--amend {name}={a.name}: an amendment re-runs tasks of a sweep reported, "
                                       "with its models, tier, bundle and pack")
        self.rows = {s.name: results(s.out) for s in [*sweeps, *self.amend.values()]}
        self.tasks = {r["task_id"]: r for p in sorted({s.pack for s in sweeps}) for r in tasks.pack_rows(p)}
        self.cells: dict[tuple[str, str, str, str], list[Sweep]] = {}
        for s in sweeps:
            for m in s.models:
                self.cells.setdefault((m, s.pack, s.tier, s.bundle), []).append(s)

    def sources(self, s: Sweep, amended: bool) -> list[Sweep]:
        return [s, self.amend[s.name]] if amended and s.name in self.amend else [s]

    def scored(self, cell, amended: bool = True) -> dict[str, list[dict]]:
        by_task: dict[str, list[dict]] = {}
        for s in self.cells[cell]:
            for run in s.runs():
                if run[0] == cell[0] and (row := next((r for src in self.sources(s, amended)
                                                       for r in of(self.rows[src.name], run)
                                                       if r["outcome"] == "scored"), None)):
                    by_task.setdefault(run[1], []).append(row)
        return by_task

    def attempts(self, cell, amended: bool = True) -> list[dict]:
        return [r for s in self.cells[cell] for src in self.sources(s, amended) for r in self.rows[src.name]
                if r["model"] == cell[0]]

    def planned(self, cell) -> int:
        return sum(1 for s in self.cells[cell] for run in s.runs() if run[0] == cell[0])

    def spend(self, cell) -> tuple[float, int]:
        attempts = self.attempts(cell)
        return sum(r["cost_usd"] or 0.0 for r in attempts), sum(r["cost_usd"] is None for r in attempts)

    def played(self, cell) -> list[dict]:
        return [self.tasks[t] for t in dict.fromkeys(t for s in self.cells[cell] for t in s.tasks)]

    def summary(self, cell, amended: bool) -> dict:
        by_task = self.scored(cell, amended)
        runs = [r for rs in by_task.values() for r in rs]
        rewards = [statistics.mean(r["reward"] for r in rs) for rs in by_task.values()]
        lo_hi = ci(rewards) if rewards else None
        out = {"runs": len(runs), "planned": self.planned(cell), "unscored": self.planned(cell) - len(runs),
               "tasks": len(rewards), "mean": _r(_mean(rewards)),
               "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None,
               "hindsight_capture": _r(_mean([statistics.mean(r["r_opt"] for r in rs) for rs in by_task.values()])),
               "optimal": _r(_mean([float(r["reward"] >= OPTIMAL) for r in runs])),
               "r_opt_optimal": _r(_mean([float(r["r_opt"] >= OPTIMAL) for r in runs])),
               "valid": _r(_mean([float(r["valid"]) for r in runs])),
               "submitted": _r(_mean([float(r["submitted"]) for r in runs])),
               "errors": {e: sum(e in (r["errors"] or []) for r in runs) for e in ERRORS},
               "checks_used": _r(_mean([r["checks"] for r in runs if r["checks"] is not None]), 2)}
        if cell[2] == "blind":
            out["beats_anchor"] = _r(_mean([float(bool(r["beats_anchor"])) for r in runs]))
        return out

    def by(self, by_task: dict[str, list[dict]], key) -> dict:
        """Mean reward and r_opt of the tasks in each group ``key`` puts a task row in."""
        groups: dict[str, list[list[dict]]] = {}
        for t, rs in by_task.items():
            for g in key(self.tasks[t]):
                groups.setdefault(str(g), []).append(rs)
        return {g: {"n": len(v), "mean": _r(_mean([statistics.mean(r["reward"] for r in rs) for rs in v])),
                    "r_opt": _r(_mean([statistics.mean(r["r_opt"] for r in rs) for rs in v]))}
                for g, v in sorted(groups.items())}

    def model(self, cell) -> dict:
        model, pack, tier, bundle = cell
        by_task = self.scored(cell)
        runs = [r for rs in by_task.values() for r in rs]
        attempts = self.attempts(cell)
        costs = [priced(r) for r in runs if priced(r) is not None]
        walls = [r["wall_seconds"] for r in runs if r["wall_seconds"] is not None]
        checks: dict[str, list[dict]] = {}
        for r in runs:
            checks.setdefault(str(r["checks"]), []).append(r)
        effort = sorted({r.get("effort") for r in runs if r.get("effort")})
        out = {"model": model, "label": LABELS.get(model, model), "trained": "base",
               "column": self.columns.get(self.cells[cell][0].name), "pack": pack, "tier": tier, "bundle": bundle,
               "effort": effort[0] if effort else None, "sweeps": [s.name for s in self.cells[cell]],
               **self.summary(cell, True),
               "checks": {c: len(rs) for c, rs in sorted(checks.items())},
               "by_checks": {c: {"n": len(rs), "mean": _r(_mean([r["reward"] for r in rs])),
                                 "r_opt": _r(_mean([r["r_opt"] for r in rs]))} for c, rs in sorted(checks.items())},
               "by_archetype": self.by(by_task, lambda t: [t["battery"]["archetype"].split("-")[0]]),
               "by_binding": self.by(by_task, lambda t: [t["tags"]["binding"]]),
               "by_day": self.by(by_task, lambda t: [d for d, f in DAY_TYPES.items() if f(t)]),
               "usd_per_episode": _r(_mean(costs)), "usd_median": _r(statistics.median(costs)) if costs else None,
               "spend_usd": round(sum(r["cost_usd"] or 0.0 for r in attempts), 4),
               "unscored_spend_usd": round(sum(r["cost_usd"] or 0.0 for r in attempts if r["outcome"] != "scored"), 4),
               "unknown_spend_attempts": sum(r["cost_usd"] is None for r in attempts),
               "attempts": len(attempts),
               "unscored_attempts": dict(Counter(r["error_code"] or r["outcome"] for r in attempts
                                                 if r["outcome"] != "scored")),
               "tokens": {k: _r(_mean([r[f"{k}_tokens"] or 0 for r in runs]), 1) for k in ("input", "output", "cached")}
               | {"total": sum((r["input_tokens"] or 0) + (r["output_tokens"] or 0) for r in attempts)},
               "wall_seconds": {"median": _r(statistics.median(walls), 1) if walls else None,
                                "mean": _r(_mean(walls), 1), "max": max(walls, default=None)},
               "started_utc": [min(r["started_utc"] for r in attempts), max(r["started_utc"] for r in attempts)],
               "baselines": references(self.played(cell), tier), "lp_bound": lp(self.played(cell))}
        if amends := [self.amend[s.name] for s in self.cells[cell] if s.name in self.amend]:
            out["prereg"] = self.summary(cell, False)
            out["amendment"] = {"sweeps": [a.name for a in amends], "runs": sum(len(a.tasks) * a.k for a in amends),
                                "episode_cap_usd": sorted({a.episode_cap_usd for a in amends}),
                                "prereg_episode_cap_usd": sorted({s.episode_cap_usd for s in self.cells[cell]})}
        return out

    def task_rows(self) -> list[dict]:
        ids = {t for cell in self.cells for t in self.scored(cell)} or {t for s in self.sweeps for t in s.tasks}
        return [self.tasks[t] for t in sorted(ids) if t in self.tasks]

    def tier_rows(self, tier: str) -> list[dict]:
        """The days played at ``tier``, which its baselines are averaged over when sweeps at two tiers share a
        board."""
        cells = [cell for cell in self.cells if cell[2] == tier]
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
                    "hindsight_capture": "r_opt: the reward against P_opt, a weight-0 row",
                    "optimal": f"R >= {OPTIMAL}", "ci": f"95% bootstrap over tasks, {RESAMPLES:,} resamples",
                    "excused": "none", "judge": False},
        "baselines": baselines(rows),
        "models": models,
        "errors": {"taxonomy": list(ERRORS),
                   "meaning": {"overfill": "soc_above_N", "sell_before_charge": "soc_below_0", "rate": "rate",
                               "cycle_cap": "cycle_cap", "end_short": "end SoC below s_end_min",
                               "all_idle": "a schedule of 24 zeros"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps]
        + [asdict(a) | {"tasks": len(a.tasks), "amends": name} for name, a in board.amend.items()],
        "links": LINKS,
        "date": max((m["started_utc"][1] for m in models), default="")[:10] or None,
    }


def _f(x: float | None, f: str = ".3f") -> str:
    return "–" if x is None else format(x, f)


def _pct(x: float | None) -> str:
    return "–" if x is None else f"{100 * x:.1f}%"


def _col(m: dict) -> str:
    return " ".join([m.get("column") or m["label"], m["pack"].removeprefix("ercot-dam-v1-"), m["tier"], m["bundle"]])


def _cells(models: list[dict], field: str, groups: dict[str, str]) -> list[str]:
    """A breakdown as a table: a row per group, a column per model row; blind cells give R / r_opt."""
    lines = ["| | " + " | ".join(_col(m) for m in models) + " |", "|---|" + "---:|" * len(models)]
    for g, name in groups.items():
        cells = []
        for m in models:
            x = m[field].get(g)
            cells.append("–" if not x else _f(x["mean"], ".4f")
                         + (f" / {_f(x['r_opt'], '.4f')}" if m["tier"] == "blind" else "") + f" ({x['n']})")
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return lines


def headline(m: dict, s: dict, scoring: str) -> str:
    ci95 = f" ({_f(s['ci95'][0], '.4f')} to {_f(s['ci95'][1], '.4f')})" if s["ci95"] else ""
    return " | ".join([f"| {m.get('column') or ''}", scoring, m["label"], m["pack"], m["tier"], m["bundle"],
                       f"{s['runs']}/{s['planned']}", _f(s["mean"], ".4f") + ci95, _f(s["hindsight_capture"], ".4f"),
                       _pct(s["optimal"]), _pct(s["valid"]), _pct(s.get("beats_anchor")),
                       _f(s["checks_used"], ".2f")]) + " |"


def board_md(c: dict, intro: str = "") -> str:
    models = c["models"]
    lines = ["# GridSim v1 board", "", *([intro, ""] if intro else []),
             "## Columns", "",
             f"Reward R = {c['grading']['reward']}: foresight against P_opt, blind against max(P_persist, P_ridge); "
             f"r_opt is R against P_opt. Mean R over battery-days, its CI a {c['grading']['ci']}. Optimal: "
             f"{c['grading']['optimal']} (at the blind tier, at or within 1% of the anchor's scale). Valid: submitted "
             "and feasible. An amended row adds the amendment's re-runs to the pre-registered sweep's scored runs.", "",
             "| Column | Scoring | Model | Pack | Tier | Harness | Scored/planned | Mean R (95% CI) | r_opt "
             "| Optimal | Valid | Beats anchor | Checks used |",
             "|---|---|---|---|---|---|---:|---|---:|---:|---:|---:|---:|"]
    for m in models:
        if "prereg" in m:
            lines += [headline(m, m, "amended"), headline(m, m["prereg"], "pre-registered")]
        else:
            lines.append(headline(m, m, "pre-registered"))
    lines += ["", "## Errors", "", "Scored runs whose submitted schedule broke a rule (it executes up to that hour), "
              "ended short of the end-of-day state of charge, or idled all day.", "",
              "| Column | " + " | ".join(ERRORS) + " |", "|---|" + "---:|" * len(ERRORS)]
    lines += [f"| {_col(m)} | " + " | ".join(str(m["errors"][e]) for e in ERRORS) + " |" for m in models]
    checks = sorted({k for m in models for k in m["by_checks"]}, key=int)
    lines += ["", "## Checks", "", "Runs by the number of `check_schedule` calls, with their mean R (and r_opt at "
              "the blind tier); the count of runs in brackets.", "",
              *_cells(models, "by_checks", {k: f"{k} check{'' if k == '1' else 's'}" for k in checks}),
              "", "## By battery class, binding constraint and day type", "",
              "Mean R (and r_opt at the blind tier) over the battery-days in each group, the count in brackets. The "
              "binding constraint is the pack's tag for what limits the optimum; a day with negative-price hours and a "
              "spike counts in both.", "",
              *_cells(models, "by_archetype", {"1h": "1 h battery", "2h": "2 h battery", "4h": "4 h battery"}), "",
              *_cells(models, "by_binding", {"none": "No constraint binds", "rate": "Rate", "cycle_cap": "Cycle cap",
                                             "end_soc": "End-of-day charge"}), "",
              *_cells(models, "by_day", {"negative_prices": "Negative-price hours", "spike": "Price spike",
                                         "neither": "Neither"}),
              "", "## Cost, tokens and time", "",
              "Per scored run: model spend at the agent's price table, tokens and wall time of the whole `agent-env "
              "run`. Spend counts every attempt, the unscored ones included.", "",
              "| Column | $/episode (median) | Spend (unscored) | Input tokens (cached) | Output tokens | Wall s, "
              "median (max) | Attempts | Unscored attempts |", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for m in models:
        t, w = m["tokens"], m["wall_seconds"]
        lines.append(f"| {_col(m)} | ${_f(m['usd_per_episode'], '.4f')} (${_f(m['usd_median'], '.4f')}) | "
                     f"${m['spend_usd']:.2f} (${m['unscored_spend_usd']:.2f}) | {t['input']:,.0f} ({t['cached']:,.0f})"
                     f" | {t['output']:,.0f} | {_f(w['median'], '.1f')} ({_f(w['max'], '.1f')}) | {m['attempts']} | "
                     + (", ".join(f"{k} {v}" for k, v in m["unscored_attempts"].items()) or "none") + " |")
    names = {"idle": "Idle", "random": "Random feasible", "clock": "Clock", "threshold": "Threshold",
             "greedy": "Greedy", "persistence_dp": "Persistence-DP", "ridge_dp": "Ridge-DP",
             "blind_anchor": "Blind anchor", "dp_optimum": "DP optimum"}
    lines += ["", "## Baselines on the same tasks", "",
              "Each reference policy graded by `gridsim_core` at the column's tier on the column's battery-days: mean "
              "R, and r_opt at the blind tier; persistence-DP, ridge-DP and the blind anchor need the blind inputs, so "
              "on foresight columns they cover only the days that have them (count in brackets). Threshold and greedy "
              "read the day's own prices, so at the blind tier they are not policies a blind desk could run.", "",
              "| | " + " | ".join(_col(m) for m in models) + " |", "|---|" + "---:|" * len(models)]
    for key, name in names.items():
        cells = []
        for m in models:
            b = m["baselines"].get(key)
            cells.append("–" if not b else _f(b["reward"]) + (f" / {_f(b['r_opt'])}" if m["tier"] == "blind" else "")
                         + (f" ({b['n']})" if b["n"] != m["planned"] else ""))
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    lines.append("| **Model** | " + " | ".join(f"**{_f(m['mean'])}**" + (f" / **{_f(m['hindsight_capture'])}**"
                                                                         if m["tier"] == "blind" else "")
                                               for m in models) + " |")
    lines += ["", "LP bound (the convex relaxation, in $) against the exact DP optimum on each column's days:", ""]
    for m in models:
        b = m["lp_bound"]
        lines.append(f"- {_col(m)}: mean P_opt ${b['p_opt_mean']:,.2f}, mean P_lp ${b['p_lp_mean']:,.2f}; P_lp exceeds "
                     f"P_opt on {b['tasks_with_gap']} of {b['n']} days (largest gap ${b['gap_usd_max']:,.2f}).")
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
    name, _, tier, bundle = cell
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
    name, _, tier, bundle = cell
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


# ================================================================ forecast report
def forecast_baselines(rows: list[dict], tier: str) -> dict:
    """The references' means over these windows at one tier: each stored baseline's reward against this tier's anchor,
    and the anchor's hindsight capture."""
    refs = [r["refs"] for r in rows if (r["refs"].get(tier) or {}).get("p_anchor") is not None]
    out: dict = {"tier": tier, "n": len(refs), "idle": 0.2, "anchor": 1.0}
    for name in FORECAST_BASELINES:
        out[name] = _r(_mean([r[tier]["baselines"][name]["reward"] for r in refs
                              if name in (r[tier].get("baselines") or {})]))
    caps = [_live_capture({"p_idle": r[tier]["p_idle"], "p_hind": r[tier]["p_hind"]}, r[tier]["p_anchor"])
            for r in refs if r[tier].get("p_hind") is not None]
    out["anchor_capture"] = _r(_mean([x for x in caps if x is not None]))
    return out


def forecast_model(board: Board, cell) -> dict:
    name, _, tier, bundle = cell
    by_task = board.scored(cell)
    mean = {t: statistics.mean(r["reward"] for r in rs) for t, rs in by_task.items()}
    runs = [r for rs in by_task.values() for r in rs]
    rewards = list(mean.values())
    lo_hi = ci(rewards) if rewards else None
    costs = [priced(r) for r in runs if priced(r) is not None]
    known, unknown = board.spend(cell)
    effort = sorted({r.get("effort") for r in runs if r.get("effort")})
    tag = {t: (board.tasks.get(t, {}).get("tags") or {}).get("label") for t in mean}
    source = {t: rs[0].get("source") for t, rs in by_task.items()}

    def avg(key: str, digits: int = 4):
        return _r(_mean([r[key] for r in runs if r.get(key) is not None]), digits)

    return {"model": name, "trained": "base", "tier": tier, "bundle": bundle, "effort": effort[0] if effort else None,
            "runs": len(runs), "planned": board.planned(cell), "tasks": len(mean),
            "mean": _r(_mean(rewards)), "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None,
            "by_label": {lb: _r(_mean([v for t, v in mean.items() if tag[t] == lb])) for lb in LABELS_V4},
            "by_source": {sc: _r(_mean([v for t, v in mean.items() if source[t] == sc])) for sc in ("desk", "ercot")},
            "hindsight_capture": _r(_mean([statistics.mean(r["r_opt"] for r in rs) for rs in by_task.values()])),
            "paired_vs_anchor": avg("paired_vs_anchor"),
            "beats_anchor": _r(_mean([float(bool(r["beats_anchor"])) for r in runs])),
            "r_roll3": avg("r_roll3"), "forecast_value": avg("forecast_value"),
            "valid": _r(_mean([float(r["valid"]) for r in runs])), "dam_missed": avg("dam_missed", 2),
            "dam_submits": avg("dam_submits", 2), "forecast_calls": avg("forecast_calls", 2),
            "as_usd": avg("as_usd", 2), "ftp_mwh_charged": avg("ftp_mwh_charged", 3),
            "ftp_mwh_excused": avg("ftp_mwh_excused", 3), "refusals": avg("refusals", 2),
            "governor_hours": avg("governor_hours", 2),
            "errors": {e: sum(e in (r["errors"] or []) for r in runs) for e in FORECAST_ERRORS},
            "planning_calls": _r(_mean([r["checks"] for r in runs]), 2), "commits": avg("commits", 2),
            "finished_by_agent": _r(_mean([float(r["end_reason"] == "done") for r in runs])),
            "turns": _r(_mean([r["turns"] for r in runs if r["turns"] is not None]), 1),
            "tokens": {k: _r(_mean([r[f"{k}_tokens"] or 0 for r in runs]), 1) for k in ("input", "output", "cached")},
            "usd_per_episode": _r(_mean(costs)), "usd_max": _r(max(costs, default=None)),
            "spend_usd": round(known, 4), "unknown_spend_attempts": unknown}


def forecast_card(board: Board) -> dict:
    models = [forecast_model(board, cell) for cell in board.cells]
    rows = board.task_rows()
    split = sorted({r.get("split") for r in rows if r.get("split")})
    tiers = sorted({s.tier for s in board.sweeps})
    flags = sorted({f"{k}: {v}" for r in rows for k, v in (r.get("flags") or {}).items() if v})
    return {
        "env": FORECAST_ENV, "version": "v4", "forecast_version": FORECAST_VERSION,
        "contract_version": CONTRACT_VERSION,
        "authors": [{"name": "Edgar Arakelyan", "github": "earakely-scale", "affiliation": "Scale AI"},
                    {"name": "Adithya S Kolavi", "github": "adithya-s-k", "affiliation": "Hugging Face"}],
        "framework": "agentenv",
        "tasks": {"split": split[0] if len(split) == 1 else split, "n": len(rows), "unit": "forecast windows",
                  "packs": sorted({s.pack for s in board.sweeps}),
                  "labels": {lb: sum((r.get("tags") or {}).get("label") == lb for r in rows) for lb in LABELS_V4},
                  "sources": dict(Counter(r.get("source") or "desk" for r in rows)),
                  "source": "ERCOT DAM/RT SPPs and DAM AS MCPCs; NOAA HRRR runs as issued; NWS VTEC; ERCOT notices; "
                            "EIA-930 DF; desk forecasts and the price guide modelled from them",
                  "selection": "the v4 filters (hindsight headroom, forecast value, anchor over idle) per kW",
                  "flags": flags},
        "harness": {"agent": live_tasks.AGENT, "env": FORECAST_ENV, "tools": [*FORECAST_TOOLS, "get_time"],
                    "max_turns": {t: FORECAST_MAX_TURNS[t] for t in tiers}, "planning_calls_per_watch": PLANNING_CALLS,
                    "forecast_calls_per_watch": FORECAST_CALLS, "dam_submits_per_gate": DAM_SUBMITS,
                    "max_tokens": forecast_tasks.MODEL_PARAMS["max_tokens"], "effort": live_tasks.EFFORT,
                    "path": "A: every step ran through AgentEnv (gateway env, triggers with deploy payloads, virtual "
                            "clock)"},
        "grading": {"reference": "the rolling MILP (HiGHS) played through the Session at every watch",
                    "reward": "clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no accepted hour in any submit_dam or "
                              "commit_schedule scores 0",
                    "idle": "no DAM, the battery idle, PV exported at RT",
                    "anchor": {"front": "P_roll on the desk's P50 guide", "front-lite": "P_roll, battery only",
                               "freeze-6h": "P_roll under the 6 h freeze", "blind": "P_blind on persistence"},
                    "hindsight_capture": "r_hind: the reward against P_hind, a weight-0 row",
                    "weight_0": ["audit", "r_hind", "paired_vs_anchor", "beats_anchor", "r_roll3", "forecast_value",
                                 "dam_missed", "baselines"],
                    "audit": "weight 0; a failed audit makes the run unscored",
                    "excused": "AS shortfall or end-SoC shortfall from drift or deployments after the hour froze",
                    "judge": False},
        "baselines": {t: forecast_baselines(board.tier_rows(t), t) for t in tiers},
        "models": models,
        "errors": {"taxonomy": list(FORECAST_ERRORS),
                   "meaning": {"no_commit": "no accepted hour in any submit_dam or commit_schedule (scores 0)",
                               "dam_missed": "a DAM gate without an accepted hour",
                               "refused": "a submit or commit with a refused hour",
                               "ftp_charged": "AS failure-to-provide charged",
                               "end_short": "SoC at the window end below s_end_min",
                               "governed": "the governor moved an hour",
                               "no_replanning": "no planning call after watch 0",
                               "no_forecasts": "no forecast call on a tier that serves them",
                               "as_unused": "no AS revenue on a tier that offers AS"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps],
        "links": {"runs": "hf dataset", "replays": "hf space", "code": "github"},
    }


def forecast_board_md(c: dict) -> str:
    h = c["harness"]
    turns = ", ".join(f"{t} {n}" for t, n in h["max_turns"].items())
    lines = ["# GridSim v4 forecast board", "",
             f"Tasks: {c['tasks']['n']} forecast windows ({', '.join(c['tasks']['packs'])}; "
             + ", ".join(f"{k} {v}" for k, v in c["tasks"]["labels"].items()) + "; sources "
             + ", ".join(f"{k} {v}" for k, v in c["tasks"]["sources"].items()) + f"). Harness: {h['agent']} on "
             f"{h['env']}, turns {turns}, {h['planning_calls_per_watch']} planning and "
             f"{h['forecast_calls_per_watch']} forecast calls a watch, {h['dam_submits_per_gate']} DAM submits a gate, "
             f"{h['max_tokens']} output tokens a turn, effort {h['effort']}. Reward: {c['grading']['reward']}; idle "
             "(0.2) is no DAM and the battery idle, the anchor (1.0) the rolling MILP on the desk's P50 guide "
             "(blind: on persistence). Mean R over windows with a 95% bootstrap CI.", ""]
    if c["tasks"]["flags"]:
        lines += ["Proxies and flags: " + "; ".join(c["tasks"]["flags"]) + ".", ""]
    for tier, b in c["baselines"].items():
        lines.append(f"Baselines ({tier}, {b['n']} windows): idle {_f(b['idle'])}, naive {_f(b['naive'])}, P_blind "
                     f"{_f(b['blind'])}, P_roll {_f(b['roll'])}, P_roll3 {_f(b['roll3'])}, anchor {_f(b['anchor'])}; "
                     f"anchor hindsight capture {_f(b['anchor_capture'])}.")
    lines += ["", "| Model | Tier | Windows | Runs/planned | Mean R (95% CI) | R front/calm | r_hind "
              "| Paired vs anchor | Beats anchor | r_roll3 | Forecast value | DAM missed | Forecast calls | Refusals "
              "| Planning calls | Turns | Finished | $/episode (max) | Spend |",
              "|---|---|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci95 = f" ({_f(m['ci95'][0])} to {_f(m['ci95'][1])})" if m["ci95"] else ""
        lines.append(" | ".join([
            f"| {m['model']}", m["tier"], str(m["tasks"]), f"{m['runs']}/{m['planned']}", _f(m["mean"]) + ci95,
            "/".join(_f(m["by_label"][lb]) for lb in LABELS_V4), _f(m["hindsight_capture"]),
            _f(m["paired_vs_anchor"]), _f(m["beats_anchor"]), _f(m["r_roll3"]), _f(m["forecast_value"]),
            _f(m["dam_missed"], ".2f"), _f(m["forecast_calls"], ".1f"), _f(m["refusals"], ".2f"),
            _f(m["planning_calls"], ".2f"), _f(m["turns"], ".1f"), _f(m["finished_by_agent"]),
            "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f} (${m['usd_max']:.4f})",
            f"${m['spend_usd']:.2f}" + (f" + {m['unknown_spend_attempts']} unknown" if m["unknown_spend_attempts"]
                                        else "")]) + " |")
    lines += ["", "## Errors", "", "Scored runs by what went wrong; a run can show several.", "",
              "| Model | Tier | " + " | ".join(FORECAST_ERRORS) + " |", "|---|---|" + "---:|" * len(FORECAST_ERRORS)]
    lines += [f"| {m['model']} | {m['tier']} | " + " | ".join(str(m["errors"][e]) for e in FORECAST_ERRORS) + " |"
              for m in c["models"]]
    return "\n".join(lines) + "\n"


# ================================================================ market report
def market_baselines(rows: list[dict], tier: str) -> dict:
    """The references' means over these floors at one tier: idle 0.2 and the anchor 1.0 by construction, the stored
    floor-sprint baselines (max-withhold, price-taker, the seat's real offers) at that tier, and the anchor's hindsight
    capture against BR_A."""
    refs = [r["refs"] for r in rows if (r["refs"].get(tier) or {}).get("p_anchor") is not None]
    out: dict = {"tier": tier, "n": len(refs), "idle": 0.2, "anchor": 1.0}
    for name in MARKET_BASELINES:
        out[name] = None if tier != "floor-sprint" else _r(_mean([
            r["floor-sprint"]["baselines"][name]["reward"] for r in refs if name in r["floor-sprint"]["baselines"]]))
    caps = [_live_capture({"p_idle": r["p_idle"], "p_hind": r[tier]["p_br"]}, r[tier]["p_anchor"]) for r in refs]
    out["anchor_capture"] = _r(_mean([x for x in caps if x is not None]))
    out["impact_hours"] = _r(_mean([r.get("impact_hours") for r in refs if r.get("impact_hours") is not None]), 2)
    return out


def market_model(board: Board, cell) -> dict:
    name, pack, tier, bundle = cell
    by_task = board.scored(cell)
    runs = [r for rs in by_task.values() for r in rs]
    costs = [priced(r) for r in runs if priced(r) is not None]
    known, unknown = board.spend(cell)
    effort = sorted({r.get("effort") for r in runs if r.get("effort")})

    def per_task(key: str) -> list[float]:
        return [statistics.mean(r[key] for r in rs) for rs in by_task.values() if all(r.get(key) is not None
                                                                                      for r in rs)]

    def mean_ci(key: str) -> dict:
        xs = per_task(key)
        lo_hi = ci(xs) if xs else None
        return {"mean": _r(_mean(xs)), "ci95": [_r(lo_hi[0]), _r(lo_hi[1])] if lo_hi else None}

    def avg(key: str, digits: int = 4):
        return _r(_mean([r[key] for r in runs if r.get(key) is not None]), digits)

    headline = mean_ci("reward")
    return {"model": name, "trained": "base", "pack": pack, "tier": tier, "bundle": bundle,
            "scoring": "compliant" if bundle == "compliant" else "reward", "effort": effort[0] if effort else None,
            "runs": len(runs), "planned": board.planned(cell), "tasks": len(by_task), **headline,
            "reward": mean_ci("market_reward"), "compliant_reward": mean_ci("compliant_reward"),
            "hindsight_capture": _r(_mean(per_task("r_opt"))), "regret_norm": avg("regret_norm"),
            "beats_anchor": _r(_mean([float(bool(r["beats_anchor"])) for r in runs])),
            "valid": _r(_mean([float(r["valid"]) for r in runs])), "eps_nash": avg("eps_nash"),
            "welfare_ratio": avg("welfare_ratio"), "dwl_usd": avg("dwl_usd", 2), "rank": avg("rank", 2),
            "mitigated_hours": avg("mitigated_hours", 2), "withholding_index": avg("withholding_index"),
            "contracts": avg("contracts", 2), "contract_value_usd": avg("contract_value_usd", 2),
            "errors": {e: sum(e in (r["errors"] or []) for r in runs) for e in MARKET_ERRORS},
            "planning_calls": _r(_mean([r["checks"] for r in runs]), 2), "data_calls": avg("data_calls", 2),
            "commits": avg("commits", 2), "refusals": avg("refusals", 2),
            "finished_by_agent": _r(_mean([float(r["end_reason"] in ("done", "submitted")) for r in runs])),
            "turns": _r(_mean([r["turns"] for r in runs if r["turns"] is not None]), 1),
            "usd_per_episode": _r(_mean(costs)), "spend_usd": round(known, 4), "unknown_spend_attempts": unknown}


def market_card(board: Board) -> dict:
    models = [market_model(board, cell) for cell in board.cells]
    rows = board.task_rows()
    split = sorted({r.get("split") for r in rows if r.get("split")})
    tiers = sorted({s.tier for s in board.sweeps})
    flags = sorted({f"{k}: {v}" for r in rows for k, v in (r.get("flags") or {}).items() if v})
    return {
        "env": MARKET_ENV, "version": "v5", "market_version": MARKET_VERSION, "contract_version": CONTRACT_VERSION,
        "authors": [{"name": "Edgar Arakelyan", "github": "earakely-scale", "affiliation": "Scale AI"},
                    {"name": "Adithya S Kolavi", "github": "adithya-s-k", "affiliation": "Hugging Face"}],
        "framework": "agentenv",
        "tasks": {"split": split[0] if len(split) == 1 else split, "n": len(rows), "unit": "market floors",
                  "packs": sorted({s.pack for s in board.sweeps}), "op_days": len({r["date"] for r in rows}),
                  "source": "ERCOT NP3-966-ER 60-day DAM disclosure re-cleared on one node; NP4-523-CD lambda; "
                            "HB_HUBAVG DAM/RT; EIA-930, EIA-923", "flags": flags},
        "harness": {"agent": live_tasks.AGENT, "env": MARKET_ENV, "tools": [*MARKET_TOOLS, "get_time"],
                    "max_turns": MARKET_MAX_TURNS, "planning_calls_per_watch": MARKET_PLANNING_CALLS,
                    "data_calls_per_watch": MARKET_DATA_CALLS,
                    "max_tokens": {t: market_tasks.MODEL_PARAMS[t]["max_tokens"] for t in MARKET_TIERS},
                    "effort": live_tasks.EFFORT, "bidders": "scripted on their real offers",
                    "path": "A: every step ran through AgentEnv (gateway env, triggers, virtual clock)"},
        "grading": {"reference": "the disclosure best-responder, information-matched at D-1 09:00",
                    "reward": "clip(0.2+0.8(P-P_idle)/(P_anchor-P_idle),0,1); no valid submit_offer scores 0",
                    "compliant": "0.5 R + 0.5 clip(welfare_ratio, 0, 1)",
                    "hindsight_capture": "(P-P_idle)/(BR_A-P_idle), BR_A the hindsight best response, a weight-0 row",
                    "weight_0": ["audit", "hindsight_capture", "regret", "compliant or reward", "eps_nash", "welfare",
                                 "contract (floor-day)", "conduct", "rank", "fidelity"],
                    "audit": "weight 0; a failed audit makes the run unscored", "judge": False},
        "baselines": {t: market_baselines(board.tier_rows(t), t) for t in tiers},
        "models": models,
        "errors": {"taxonomy": list(MARKET_ERRORS),
                   "meaning": {"no_submit": "no valid submit_offer (scores 0)",
                               "refused": "a refused offer or schedule", "idle": "a valid offer with no blocks",
                               "mitigated": "an hour of seat A mitigated", "clipped": "delivery clipped off the awards",
                               "end_short": "SoC at 24:00 below s_end_min", "no_schedule": "floor-day: no accepted "
                                                                                          "commit_schedule",
                               "price_talk": "a message flagged for price talk"}},
        "sweeps": [asdict(s) | {"tasks": len(s.tasks)} for s in board.sweeps],
        "links": {"runs": "hf dataset", "replays": "hf space", "code": "github"},
    }


def market_board_md(c: dict) -> str:
    h = c["harness"]
    lines = ["# GridSim v5 market board", "",
             f"Tasks: {c['tasks']['n']} market floors on {c['tasks']['op_days']} operating days "
             f"({', '.join(c['tasks']['packs'])}). Harness: {h['agent']} on {h['env']} as seat A, the other seats "
             f"{h['bidders']}; turns {', '.join(f'{k} {v}' for k, v in h['max_turns'].items())}, "
             f"{h['planning_calls_per_watch']} planning and {h['data_calls_per_watch']} data calls a watch, effort "
             f"{h['effort']}. Reward R: {c['grading']['reward']}; compliant: {c['grading']['compliant']}. Each row's "
             "headline is its sweep's scoring; both are shown. Means over floors with a 95% bootstrap CI.", ""]
    if c["tasks"]["flags"]:
        lines += ["Modelled and flagged: " + "; ".join(c["tasks"]["flags"]) + ".", ""]
    for tier, b in c["baselines"].items():
        extra = ", ".join(f"{k} {_f(b[k])}" for k in MARKET_BASELINES if b.get(k) is not None)
        lines.append(f"Baselines ({tier}, {b['n']} floors): idle {_f(b['idle'])}, anchor {_f(b['anchor'])}"
                     + (f", {extra}" if extra else "") + f"; anchor hindsight capture {_f(b['anchor_capture'])}, "
                     f"impact hours {_f(b['impact_hours'], '.2f')}.")
    lines += ["", "| Model | Pack | Tier | Scoring | Floors | Runs/planned | Headline (95% CI) | R | Compliant "
              "| Hindsight capture | Beats anchor | Welfare ratio | eps-Nash | Mitigated h | Withholding | CfDs "
              "| Finished | $/episode | Spend |", "|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:"
              "|---:|---:|---:|---:|---:|"]
    for m in c["models"]:
        ci95 = f" ({_f(m['ci95'][0])} to {_f(m['ci95'][1])})" if m["ci95"] else ""
        lines.append(" | ".join([
            f"| {m['model']}", m["pack"], m["tier"], m["scoring"], str(m["tasks"]), f"{m['runs']}/{m['planned']}",
            _f(m["mean"]) + ci95, _f(m["reward"]["mean"]), _f(m["compliant_reward"]["mean"]),
            _f(m["hindsight_capture"]), _f(m["beats_anchor"]), _f(m["welfare_ratio"]), _f(m["eps_nash"]),
            _f(m["mitigated_hours"], ".2f"), _f(m["withholding_index"]), _f(m["contracts"], ".2f"),
            _f(m["finished_by_agent"]), "–" if m["usd_per_episode"] is None else f"${m['usd_per_episode']:.4f}",
            f"${m['spend_usd']:.2f}" + (f" + {m['unknown_spend_attempts']} unknown" if m["unknown_spend_attempts"]
                                        else "")]) + " |")
    lines += ["", "## Errors", "", "Scored runs by what went wrong; a run can show several.", "",
              "| Model | Tier | " + " | ".join(MARKET_ERRORS) + " |", "|---|---|" + "---:|" * len(MARKET_ERRORS)]
    lines += [f"| {m['model']} | {m['tier']} | " + " | ".join(str(m["errors"][e]) for e in MARKET_ERRORS) + " |"
              for m in c["models"]]
    return "\n".join(lines) + "\n"


def unscored(board: Board) -> list[str]:
    """Every pre-registered run with no scored attempt, and how its amendment, if any, ended."""
    out = []
    for cell in board.cells:
        done = board.scored(cell, amended=False)
        for s in board.cells[cell]:
            for run in s.runs():
                if run[0] == cell[0] and run[1] not in done:
                    rs = of(board.rows[s.name], run)
                    last = (rs[-1]["error_code"] or rs[-1]["outcome"]) if rs else "not run"
                    a = board.amend.get(s.name)
                    ar = of(board.rows[a.name], run) if a else []
                    amended = ("–" if not a else "not run" if not ar else
                               f"scored {ar[-1]['reward']:.4f}" if ar[-1]["outcome"] == "scored"
                               else ar[-1]["error_code"] or ar[-1]["outcome"])
                    cost = sum(r["cost_usd"] or 0.0 for r in rs)
                    out.append(f"| {s.name} | {run[1]} | {run[2]} | {len(rs)} | {last} (${cost:.4f}) | "
                               f"{a.name if a else '–'} | {amended} |")
    return (["| Sweep | Task | Rep | Attempts | Last outcome (spend) | Amendment | Amended outcome |",
             "|---|---|---:|---:|---|---|---|", *out] if out else ["None."])


REPORTS = {"gridsim": (card, board_md, CARD, BOARD), LIVE_ENV: (live_card, live_board_md, LIVE_CARD, LIVE_BOARD),
           HYBRID_ENV: (hybrid_card, hybrid_board_md, HYBRID_CARD, HYBRID_BOARD),
           FORECAST_ENV: (forecast_card, forecast_board_md, FORECAST_CARD, FORECAST_BOARD),
           MARKET_ENV: (market_card, market_board_md, MARKET_CARD, MARKET_BOARD)}


def report(sweeps: list[Sweep], card_path: Path | None = None, board_path: Path | None = None,
           amend: dict[str, Sweep] | None = None, columns: dict[str, str] | None = None, narrate=None) -> dict:
    """v1 sweeps to results/eval-v1.json and board.md; live sweeps to eval-v2.json and board-v2.md; hybrid sweeps to
    eval-v3.json and board-v3.md; forecast sweeps to eval-v4.json and board-v4.md; market sweeps to eval-v5.json and
    board-v5.md. ``narrate(card, board)`` returns the fields to add to the card and the text to put under the board's
    title and after its tables."""
    if len({s.env for s in sweeps}) > 1:
        raise click.UsageError("report v1 and live sweeps separately, and hybrid, forecast and market sweeps each on "
                               "their own: their references differ")
    make_card, make_board, default_card, default_board = REPORTS[sweeps[0].env]
    board = Board(sweeps, amend, columns)
    c = make_card(board)
    extra, intro, outro = narrate(c, board) if narrate else ({}, "", "")
    c |= extra
    card_path = card_path or default_card
    board_path = board_path or default_board
    card_path.parent.mkdir(parents=True, exist_ok=True)
    card_path.write_text(json.dumps(c, indent=2) + "\n")
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text((make_board(c, intro) if intro else make_board(c)) + (f"\n{outro}\n" if outro else "")
                          + "\n## Unscored runs\n\n" + "\n".join(unscored(board)) + "\n")
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
                   f"{HYBRID_ENV}: a hybrid pack's solar-plus-storage site-days played live; {FORECAST_ENV}: a "
                   f"forecast pack's windows played live on forecasts as issued; {MARKET_ENV}: a market pack's floors.")
@click.option("--pack", type=click.Choice(PACK_NAMES + LIVE_PACK_NAMES + HYBRID_PACK_NAMES + FORECAST_PACK_NAMES
                                          + MARKET_PACK_NAMES),
              help=f"The task pack. Default: {EVAL_PACK}, {LIVE_EVAL_PACK} with --env {LIVE_ENV}, "
                   f"{HYBRID_EVAL_PACK} with --env {HYBRID_ENV}, {FORECAST_EVAL_PACK} with --env {FORECAST_ENV}, or "
                   f"{MARKET_EVAL_PACK} with --env {MARKET_ENV}.")
@click.option("--tier", type=click.Choice(list(dict.fromkeys(LIVE_TIERS + HYBRID_TIERS + FORECAST_TIERS + MARKET_TIERS))),
              help="foresight (the default) or blind; live days also take short and freeze6h; hybrid days take "
                   "energy, reserves (the default) or rtcb; forecast windows take front-lite, front (the default), "
                   "blind or freeze-6h; market floors floor-sprint (the default) or floor-day.")
@click.option("--compliant", is_flag=True,
              help="Market floors: score 0.5 R + 0.5 welfare ratio (the report shows both scorings either way).")
@click.option("--bundle", type=click.Choice(list(tasks.BUNDLES)), default="full", show_default=True,
              help="full: three checks; oneshot: submit_schedule only. Not for live or hybrid days.")
@click.option("--cap-usd", type=float, required=True,
              help="The model spend the sweep stays within: no attempt starts that could take it past this at the "
                   "episode cap.")
@click.option("--k", type=click.IntRange(min=1), default=1, show_default=True, help="Reps of each model and task.")
@click.option("--episode-cap-usd", type=float,
              help="An episode's cost cap, passed to the agent as GRIDSIM_MAX_COST_USD. Default: $1, "
                   f"${forecast_tasks.EPISODE_CAP_USD:g} with --env {FORECAST_ENV}, or the market tier's ($1 "
                   "floor-sprint, $2 floor-day).")
@click.option("--parallel", type=click.IntRange(min=1), default=4, show_default=True, help="Attempts at a time.")
def run_command(name: str, models: str, task_spec: str, env: str, pack: str | None, tier: str | None,
                compliant: bool, bundle: str, cap_usd: float, k: int, episode_cap_usd: float | None, parallel: int):
    """Play each model on each task k times, one `agent-env run` per attempt, logged under results/runs/<name>/raw/logs.
    Each attempt is a line of results.jsonl; a failed one is retried up to twice, and running the sweep again plays
    the runs that aren't final yet. Ctrl-C tears the running attempts down."""
    if "" in models.split(","):
        raise click.UsageError("--models takes comma-separated model ids, none empty")
    market = env == MARKET_ENV
    if compliant and not market:
        raise click.UsageError(f"--compliant scores market floors: use it with --env {MARKET_ENV}")
    if not market and pack in MARKET_PACK_NAMES:
        raise click.UsageError(f"{pack} is a market pack: play it with --env {MARKET_ENV}")
    if market and pack is not None and pack not in MARKET_PACK_NAMES:
        raise click.UsageError(f"{pack} is not a market pack; {env} plays {', '.join(MARKET_PACK_NAMES)}")
    if market:
        tier = tier or "floor-sprint"
        if tier not in MARKET_TIERS or bundle != "full":
            raise click.UsageError(f"{env} plays the tiers {', '.join(MARKET_TIERS)} in one harness, not {tier} "
                                   f"{bundle}")
        pack = pack or MARKET_EVAL_PACK
        sweep = Sweep(name, models.split(","), task_ids(task_spec, pack, tier), k,
                      market_tasks.EPISODE_CAP_USD[tier] if episode_cap_usd is None else episode_cap_usd, tier,
                      "compliant" if compliant else "live", pack, env)
        if not sweep.tasks:
            raise click.UsageError(f"no {tier} floors in {pack} for --tasks {task_spec}")
        prepare(sweep)
        raise SystemExit(run(sweep, cap_usd, parallel))
    live, hybrid, forecast = env == LIVE_ENV, env == HYBRID_ENV, env == FORECAST_ENV
    pack = pack or (LIVE_EVAL_PACK if live else HYBRID_EVAL_PACK if hybrid else FORECAST_EVAL_PACK if forecast
                    else EVAL_PACK)
    tier = tier or ("reserves" if hybrid else "front" if forecast else "foresight")
    episode_cap_usd = episode_cap_usd or (forecast_tasks.EPISODE_CAP_USD if forecast else 1.0)
    if forecast != (pack in FORECAST_PACK_NAMES):
        raise click.UsageError(f"{pack} is {'not ' if forecast else ''}a forecast pack; {env} plays "
                               f"{'forecast' if forecast else 'v1, live or hybrid'} packs")
    if forecast and tier not in FORECAST_TIERS:
        raise click.UsageError(f"{env} plays the tiers {', '.join(FORECAST_TIERS)}, not {tier}")
    if not forecast and tier in FORECAST_TIERS and tier not in LIVE_TIERS:
        raise click.UsageError(f"{tier} is a forecast tier; {env} doesn't play it")
    if hybrid != (pack in HYBRID_PACK_NAMES):
        raise click.UsageError(f"{pack} is {'not ' if hybrid else ''}a hybrid pack; {env} plays "
                               f"{'hybrid' if hybrid else 'v1 or live'} packs")
    if live != (pack in LIVE_PACK_NAMES):
        raise click.UsageError(f"{pack} is {'not ' if live else ''}a live pack; {env} plays "
                               f"{'live' if live else 'v1'} packs")
    if hybrid != (tier in HYBRID_TIERS):
        raise click.UsageError(f"{env} plays the tiers {', '.join(HYBRID_TIERS)}, not {tier}" if hybrid
                               else f"{tier} is a hybrid tier; {env} doesn't play it")
    if (live or hybrid or forecast) and bundle != "full":
        raise click.UsageError("--bundle is for v1 sweeps; a live day has one harness")
    if not (live or hybrid or forecast) and tier not in TIERS:
        raise click.UsageError(f"the v1 packs have the tiers {', '.join(TIERS)}, not {tier}")
    sweep = Sweep(name, models.split(","), task_ids(task_spec, pack, tier), k, episode_cap_usd, tier,
                  "live" if live or hybrid or forecast else bundle, pack, env)
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
@click.option("--amend", multiple=True, metavar="SWEEP=AMENDMENT",
              help="A sweep of NAMES and the sweep that re-ran some of its tasks under an amendment: the headline "
                   "takes each run's score from either, and `prereg` reports the sweep alone. Repeatable.")
def report_command(names: tuple[str, ...], card_path: Path | None, board_path: Path | None, amend: tuple[str, ...]):
    """Report the sweeps NAMES: each model at each pack, tier and harness, its mean reward with a 95% bootstrap CI,
    hindsight capture, optimal and valid rates, error taxonomy, checks used, the breakdowns by battery class, binding
    constraint and day type, and cost, next to the baselines graded on the same tasks. Live sweeps report against the
    live references: naive, the rolling anchor and hindsight."""
    if bad := [a for a in amend if a.count("=") != 1]:
        raise click.UsageError(f"--amend takes SWEEP=AMENDMENT, not {bad[0]}")
    sweeps = [load(name) for name in names]
    c = report(sweeps, card_path, board_path, {k: load(v) for k, v in (a.split("=") for a in amend)})
    _, _, default_card, default_board = REPORTS[sweeps[0].env]
    click.echo(f"Wrote {card_path or default_card} and {board_path or default_board}: {len(c['models'])} model rows "
               f"over {c['tasks']['n']} tasks")
