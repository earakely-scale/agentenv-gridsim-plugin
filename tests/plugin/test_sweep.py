"""`agent-env gridsim sweep run|report` and `episodes` with a stand-in `agent-env run`: the rows the sweep records, its
spend cap, retries, stops and resume; the eval card and board; and Episode JSON replayed from the records."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from conftest import BLIND, FIXTURES
from sweep_fake import agent_failed, scored, step_failed

from agentenv_gridsim import sweep
from agentenv_gridsim.cli import gridsim
from gridsim_core.episode import check_result, submit_result
from gridsim_core.grade import grade
from gridsim_core.prompt import situation

SOL = "openai/gpt-6.1-sol"
T1, T2, T3 = FIXTURES[1], FIXTURES[2], FIXTURES[3]
ARGS = ["--pack", "fixtures"]


def sweep_run(*args: str, name: str = "s"):
    return CliRunner().invoke(gridsim, ["sweep", "run", "--name", name, *ARGS, *args])


def rows(name: str = "s") -> list[dict]:
    return sweep.results(Path("results/runs") / name / "raw")


def brief(row: dict) -> tuple:
    return row["task_id"], row["attempt"], row["outcome"], row["error_code"], row["cost_usd"], row["retryable"]


def opt(task: dict) -> list[int]:
    return task["refs"]["foresight"]["opt"]


def greedy(task: dict) -> list[int]:
    return task["refs"]["foresight"]["baselines"]["greedy"]["schedule"]


def test_an_attempt_is_one_row_with_the_grade_the_episode_and_the_agents_summary(fake):
    fake.script({"*": [{"context": scored(T1, SOL, greedy(T1))}]})
    result = sweep_run("--models", SOL, "--tasks", T1["task_id"], "--cap-usd", "10")
    assert result.exit_code == 0, result.output
    [row] = rows()
    g = grade(T1, greedy(T1))
    assert (row["outcome"], row["reward"], row["r_opt"], row["valid"], row["submitted"], row["errors"]) == (
        "scored", g["reward"], g["r_opt"], True, True, [])
    assert (row["profit"], row["profit_opt"], row["schedule"], row["checks"], row["calls"]) == (
        g["profit"], g["profit_opt"], greedy(T1), 1, 3)
    assert (row["effort"], row["cost_usd"], row["tier"], row["bundle"], row["wall_seconds"]) == (
        "high", 0.0123, "foresight", "full", 12.5)
    out = Path("results/runs/s/raw")
    assert json.loads((out / "sweep.json").read_text()) == {
        "name": "s", "models": [SOL], "tasks": [T1["task_id"]], "k": 1, "episode_cap_usd": 1.0, "tier": "foresight",
        "bundle": "full", "pack": "fixtures"}
    assert [p.name for p in (out / "bundle/tasks").iterdir()] == [f"{T1['task_id']}.json"]
    bundle = str(out.absolute() / "bundle")
    assert fake.calls()[0]["argv"] == ["run", bundle, "--task", T1["task_id"], "--dry-run"]
    assert fake.runs() == [["run", bundle, "--task", T1["task_id"], "--model", SOL]]
    assert result.output.splitlines()[-1] == f"{SOL}: 1 scored, 0 unscored, 0 not final, of 1 runs; $0.01 spent"


def test_failures_are_retried_twice_a_capped_episode_is_final_and_a_deploy_failure_costs_nothing(fake):
    ids = [t["task_id"] for t in (T1, T2, T3)]
    fake.script({
        f"{SOL}|{ids[0]}": [{"context": agent_failed(ids[0], SOL, "provider_error"), "exit": 1}],
        f"{SOL}|{ids[1]}": [{"context": agent_failed(ids[1], SOL, "cost_cap", cost=0.49), "exit": 1}],
        f"{SOL}|{ids[2]}": [{"context": step_failed("deploy", "deploy_env"), "exit": 1},
                            {"context": scored(T3, SOL, opt(T3))}],
    })
    result = sweep_run("--models", SOL, "--tasks", ",".join(ids), "--cap-usd", "10", "--episode-cap-usd", "0.5",
                       "--parallel", "1")
    assert result.exit_code == 0, result.output
    assert [brief(r) for r in rows()] == [
        (ids[0], 1, "failed", "provider_error", 0.05, True), (ids[1], 1, "failed", "cost_cap", 0.49, False),
        (ids[2], 1, "failed", "RuntimeError", 0.0, True), (ids[0], 2, "failed", "provider_error", 0.05, True),
        (ids[2], 2, "scored", None, 0.0123, False), (ids[0], 3, "failed", "provider_error", 0.05, False)]


def test_the_spend_cap_stops_the_sweep_and_a_rerun_resumes_it(fake):
    ids = f"{T1['task_id']},{T2['task_id']}"
    fake.script({"*": [{"context": scored(T1, SOL, opt(T1), cost=0.3)}]})
    first = sweep_run("--models", SOL, "--tasks", ids, "--episode-cap-usd", "0.5", "--cap-usd", "0.6")
    assert first.exit_code == 1
    assert first.output.splitlines()[-1] == ("stopped: another attempt could take the spend past $0.60 ($0.30 spent, "
                                             "$0.50 an attempt at most); 1 runs not final")
    second = sweep_run("--models", SOL, "--tasks", ids, "--episode-cap-usd", "0.5", "--cap-usd", "5")
    assert second.exit_code == 0, second.output
    assert [r["task_id"] for r in rows()] == ids.split(",")
    refused = sweep_run("--models", SOL, "--tasks", ids, "--episode-cap-usd", "0.5", "--cap-usd", "5", "--tier",
                        "blind")
    assert refused.exit_code == 2 and "is another sweep" in refused.output


@pytest.mark.parametrize("code", ["model_endpoint", "unpriced_model"])
def test_a_missing_endpoint_or_price_starts_nothing_new(fake, code):
    fake.script({"*": [{"context": agent_failed(T1["task_id"], SOL, code, cost=0.0), "exit": 1}]})
    result = sweep_run("--models", SOL, "--tasks", f"{T1['task_id']},{T2['task_id']}", "--cap-usd", "10",
                       "--parallel", "1")
    assert result.exit_code == 1 and len(rows()) == 1
    assert result.output.splitlines()[-1].startswith(f"stopped: {code} from {SOL}")


def test_task_specs():
    ids = [t["task_id"] for t in FIXTURES]
    assert sweep.task_ids("all", "fixtures") == ids and sweep.task_ids("2", "fixtures") == ids[:2]
    assert sweep.task_ids("all", "fixtures", "blind") == [t["task_id"] for t in BLIND]
    with pytest.raises(Exception, match="not blind tasks of fixtures"):
        sweep.task_ids(FIXTURES[-1]["task_id"], "fixtures", "blind")


def test_the_report_writes_the_card_and_the_board_with_the_pack_baselines_and_an_amendment(fake):
    blind = BLIND[0]
    fake.script({f"{SOL}|{T1['task_id']}": [{"context": scored(T1, SOL, opt(T1))}],
                 f"{SOL}|{T2['task_id']}": [{"context": agent_failed(T2["task_id"], SOL, "cost_cap", cost=0.04),
                                             "exit": 1}],
                 f"{SOL}|{blind['task_id']}": [{"context": scored(blind, SOL, blind["refs"]["blind"]["persist"],
                                                                  "blind")}]})
    assert sweep_run("--models", SOL, "--tasks", f"{T1['task_id']},{T2['task_id']}", "--cap-usd", "5").exit_code == 0
    assert sweep_run("--models", SOL, "--tasks", blind["task_id"], "--tier", "blind", "--bundle", "oneshot",
                     "--cap-usd", "5", name="b").exit_code == 0
    fake.script({f"{SOL}|{T2['task_id']}": [{"context": scored(T2, SOL, [0] * 24)}]})
    assert sweep_run("--models", SOL, "--tasks", T2["task_id"], "--cap-usd", "5", "--episode-cap-usd", "4",
                     name="s-amend").exit_code == 0
    result = CliRunner().invoke(gridsim, ["sweep", "report", "s", "b", "--amend", "s=s-amend"])
    assert result.exit_code == 0, result.output
    card = json.loads(Path("results/eval-v1.json").read_text())
    assert (card["env"], card["version"], card["contract_version"], card["framework"]) == (
        "gridsim-battery", "v1", "1.0", "agentenv")
    assert card["grading"]["judge"] is False and card["harness"]["max_turns"] == 4
    days = [T1, T2, blind]
    assert card["tasks"]["n"] == 3
    assert card["baselines"]["idle"] == 0.2
    for name in ("clock", "threshold", "greedy"):
        assert card["baselines"][name] == round(sum(t["refs"]["foresight"]["baselines"][name]["reward"]
                                                    for t in days) / 3, 4)
    blinds = [t for t in days if t.get("blind") and (t.get("refs") or {}).get("blind")]
    assert card["baselines"]["persistence_dp_blind"] == round(
        sum(grade(t, t["refs"]["blind"]["persist"], "blind")["reward"] for t in blinds) / len(blinds), 4)
    [fore, bl] = card["models"]
    idle2 = grade(T2, [0] * 24)["reward"]
    assert (fore["tier"], fore["bundle"], fore["runs"], fore["mean"]) == ("foresight", "full", 2,
                                                                          round((1.0 + idle2) / 2, 4))
    assert (fore["prereg"]["runs"], fore["prereg"]["unscored"], fore["prereg"]["mean"]) == (1, 1, 1.0)
    assert fore["amendment"] == {"sweeps": ["s-amend"], "runs": 1, "episode_cap_usd": [4.0],
                                 "prereg_episode_cap_usd": [1.0]}
    assert (fore["attempts"], fore["unscored_attempts"], fore["spend_usd"]) == (3, {"cost_cap": 1}, 0.0646)
    assert fore["optimal"] == 0.5 and fore["checks"] == {"1": 2}
    assert fore["baselines"]["greedy"]["reward"] == round(
        sum(t["refs"]["foresight"]["baselines"]["greedy"]["reward"] for t in (T1, T2)) / 2, 4)
    assert sum(g["n"] for g in fore["by_archetype"].values()) == 2
    assert fore["errors"]["all_idle"] == 1 and fore["ci95"][0] <= fore["mean"] <= fore["ci95"][1]
    assert (bl["tier"], bl["bundle"], bl["beats_anchor"]) == ("blind", "oneshot", 0.0) and "prereg" not in bl
    assert [s["name"] for s in card["sweeps"]] == ["s", "b", "s-amend"] and card["sweeps"][2]["amends"] == "s"
    board = Path("results/board.md").read_text()
    assert board.startswith("# GridSim v1 board")
    assert "| amended | GPT-6.1 Sol | fixtures | foresight | full | 2/2 |" in board
    assert "| pre-registered | GPT-6.1 Sol | fixtures | foresight | full | 1/2 |" in board
    assert "| pre-registered | GPT-6.1 Sol | fixtures | blind | oneshot | 1/1 |" in board
    assert f"| s | {T2['task_id']} | 1 | 1 | cost_cap ($0.0400) | s-amend | scored {idle2:.4f} |" in board
    assert CliRunner().invoke(gridsim, ["sweep", "report", "s", "--amend", "b=s-amend"]).exit_code == 2


def record(task: dict, tier: str = "foresight", checks: int = 3, *, tamper: bool = False) -> dict:
    """gridsim-llm's record of a day: get_situation, a check of greedy, a submit of the optimum."""
    check = check_result(task, greedy(task), checks - 1, tier)
    if tamper:
        check = check | {"checks_left": 9}
    steps = [{"t": 0, "turn": 1, "call_id": "a", "tool": "get_situation", "args": {},
              "output": situation(task, tier, checks)},
             {"t": 1, "turn": 1, "call_id": "b", "tool": "check_schedule", "args": {"actions": greedy(task)},
              "output": json.loads(json.dumps(check))},
             {"t": 2, "turn": 2, "call_id": "c", "tool": "submit_schedule", "args": {"actions": opt(task)},
              "output": json.loads(json.dumps(submit_result(task, opt(task))))}]
    return {"model": SOL, "effort": "high", "steps": steps, "final": {"submitted": True, "schedule": opt(task)},
            "usage": {"input_tokens": 6000, "output_tokens": 1200}, "turns": 2, "end_reason": "submitted",
            "errors": [], "messages": [{"role": "assistant", "content": "Charge at night, sell at the peak."}]}


def test_episodes_replays_each_record_into_episode_json_and_lists_a_mismatch_loudly(fake):
    good, bad = T1, T2
    (fake.root / "records").mkdir()
    (fake.root / "records/good.json").write_text(json.dumps(record(good)))
    (fake.root / "records/bad.json").write_text(json.dumps(record(bad, tamper=True)))
    fake.script({f"{SOL}|{good['task_id']}": [{"context": scored(good, SOL, opt(good), trajectory="file:///good.json")}],
                 f"{SOL}|{bad['task_id']}": [{"context": scored(bad, SOL, opt(bad), trajectory="file:///bad.json")}]})
    assert sweep_run("--models", SOL, "--tasks", f"{good['task_id']},{bad['task_id']}", "--cap-usd", "5").exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "s"])
    assert result.exit_code == 1
    assert f"MISMATCH {SOL} {bad['task_id']} r1 a1: call 1 check_schedule returns" in result.output
    assert "1 runs didn't replay" in result.output
    [path] = Path("results/runs/s").glob("*.json")
    assert path.name == f"{good['task_id']}-openai-gpt-6.1-sol-r1.json"
    e = json.loads(path.read_text())
    assert (e["schema"], e["path"], e["bundle"], e["tier"], e["model"], e["trained"]) == (
        "gridsim.episode/v1", "A", "full", "foresight", SOL, "base")
    assert (e["reward"], e["final_schedule"], [s["tool"] for s in e["steps"]]) == (
        1.0, opt(good), ["get_situation", "check_schedule", "submit_schedule"])
    assert e["situation"] == situation(good, "foresight", 3) and e["usage"]["usd"] == 0.0123
    assert e["messages"] == [{"role": "assistant", "content": "Charge at night, sell at the peak."}]
