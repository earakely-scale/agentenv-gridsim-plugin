"""`agent-env gridsim sweep run --env gridsim-forecast`, its report and `episodes` with a stand-in `agent-env run`: the
forecast rows, eval-v4.json and board-v4.md against the forecast references, and Episode JSON v4 replayed byte for
byte through the forecast Session."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from forecast_days import ROWS, WINDOW, anchor, scripted
from sweep_fake import play, stored, summary

from agentenv_gridsim import forecast_tasks, sweep
from agentenv_gridsim.cli import gridsim
from gridsim_core.forecast import EPISODE_SCHEMA, FORECAST_ENV, NOTICE_TOOL, Session

SOL = "openai/gpt-6.1-sol"
FORECAST = ["--env", "gridsim-forecast", "--pack", "fixtures-forecast"]


def forecast_play(task: dict, tier: str = "front", tamper: bool = False) -> tuple[dict, Session]:
    """gridsim-llm's record of the anchor's window through the gateway (a get_time read before each turn's calls), and
    the window the env holds once played."""
    s, steps, tools = Session(task, tier), [], []
    calls = scripted(task, tier, anchor(tier))
    for turn, watch in enumerate(calls, 1):
        for name, args in [("get_time", {}), *watch]:
            out = (json.dumps({"current_time": s.watch_time_utc(s.watch)}) if name == "get_time"
                   else s.call(name, args))
            cid = f"call_{len(steps)}"
            steps.append({"t": len(steps), "turn": turn, "call_id": cid, "tool": name, "args": args,
                          "output": json.loads(out)})
            tools.append({"role": "tool", "tool_call_id": cid, "name": name, "content": out})
            if name == "advance" and "watch" in json.loads(out):
                s.deliver_watch_notices()
    if tamper:
        tools[-1]["content"] = tools[-1]["content"].replace('"done":true', '"done":true,"x":1')
    record = {"model": SOL, "effort": "high", "steps": steps, "final": {"done": True, "reward": s.grade()["reward"]},
              "usage": {"input_tokens": 90000, "output_tokens": 9000}, "turns": len(calls), "end_reason": "done",
              "errors": [], "messages": [{"role": "assistant", "content": "Bid the cold front.", "tool_calls": []},
                                         *tools]}
    return record, s


def forecast_scored(s: Session, trajectory: str) -> dict:
    g = s.grade()
    return stored(play(s.task["task_id"], SOL, summary(SOL, "done", live=True, reward=g["reward"]),
                       trajectory=trajectory),
                  verifications={"gridsim": {"results": [
                      {"criterion": "gridsim", "result": g["reward"] >= 1.0, "score": g["reward"], "weight": 1.0,
                       "episode": json.loads(json.dumps(s.data()))},
                      {"criterion": "audit", "result": True, "score": 1.0, "weight": 0.0},
                      {"criterion": "r_hind", "result": False, "score": g["r_hind"], "weight": 0.0}],
                      "score": g["reward"]}})


def run_forecast(fake, task: dict = WINDOW, tier: str = "front", name: str = "fc", tamper: bool = False,
                 extra: tuple = ()):
    (fake.root / "records").mkdir(exist_ok=True)
    record, s = forecast_play(task, tier, tamper)
    (fake.root / "records" / f"{task['task_id']}.json").write_text(json.dumps(record))
    fake.script({f"{SOL}|{task['task_id']}": [{"context": forecast_scored(s, f"file:///{task['task_id']}.json")}]})
    return CliRunner().invoke(gridsim, ["sweep", "run", "--name", name, *FORECAST, "--models", SOL, "--tasks",
                                        task["task_id"], "--tier", tier, "--cap-usd", "20", *extra])


def test_a_forecast_attempt_is_a_row_with_the_forecast_grade(fake):
    result = run_forecast(fake)
    assert result.exit_code == 0, result.output
    [row] = sweep.results(Path("results/runs/fc/raw"))
    g = forecast_play(WINDOW)[1].grade()
    assert (row["outcome"], row["reward"], row["r_opt"], row["bundle"], row["tier"], row["source"]) == (
        "scored", 1.0, g["r_hind"], "live", "front", "desk")
    assert (row["profit"], row["profit_anchor"], row["profit_opt"], row["dam_missed"], row["paired_vs_anchor"]) == (
        g["profit_usd"], g["p_anchor"], g["p_hind"], 0, g["paired_vs_anchor"])
    assert (row["valid"], row["audit_ok"], row["end_reason"], row["dam_submits"]) == (True, True, "done", 3)
    assert "no_forecasts" in row["errors"] and "no_commit" not in row["errors"] and "dam_missed" not in row["errors"]
    spec = json.loads(Path("results/runs/fc/raw/sweep.json").read_text())
    assert (spec["env"], spec["bundle"], spec["pack"], spec["tier"], spec["episode_cap_usd"]) == (
        FORECAST_ENV, "live", "fixtures-forecast", "front", forecast_tasks.EPISODE_CAP_USD)
    bundle = json.loads(Path(f"results/runs/fc/raw/bundle/tasks/{WINDOW['task_id']}.json").read_text())
    assert bundle[-1]["file_artifact_id"] == "gridsim-forecast-verifier"
    assert next(s for s in bundle if s["id"] == "deploy-agent")["env_vars"] == {
        "GRIDSIM_MAX_COST_USD": format(forecast_tasks.EPISODE_CAP_USD, "g")}


def test_the_forecast_report_writes_eval_v4_and_the_forecast_board(fake):
    assert run_forecast(fake).exit_code == 0
    other = next(r for r in ROWS if r["task_id"] != WINDOW["task_id"])
    assert run_forecast(fake, other, "blind", "fc-b").exit_code == 0
    result = CliRunner().invoke(gridsim, ["sweep", "report", "fc", "fc-b"])
    assert result.exit_code == 0, result.output
    card = json.loads(Path("results/eval-v4.json").read_text())
    front, blind = card["models"]
    assert (card["env"], card["version"], card["tasks"]["n"], card["tasks"]["sources"]) == (
        FORECAST_ENV, "v4", 2, {"desk": 2})
    assert (front["tier"], front["tasks"], front["mean"], front["dam_missed"], blind["tier"], blind["mean"]) == (
        "front", 1, 1.0, 0.0, "blind", 1.0)
    assert front["by_source"] == {"desk": 1.0, "ercot": None} and blind["forecast_value"] is not None
    assert card["harness"]["max_turns"] == {"blind": 122, "front": 122}
    b = card["baselines"]
    assert (b["front"]["n"], b["blind"]["n"]) == (1, 1)
    assert (b["front"]["naive"], b["blind"]["roll"]) == (
        round(WINDOW["refs"]["front"]["baselines"]["naive"]["reward"], 4),
        round(other["refs"]["blind"]["baselines"]["roll"]["reward"], 4))
    board = Path("results/board-v4.md").read_text()
    assert board.startswith("# GridSim v4 forecast board") and "| openai/gpt-6.1-sol | blind | 1 |" in board


def test_a_forecast_and_a_hybrid_sweep_are_reported_apart(fake):
    assert run_forecast(fake).exit_code == 0
    hy = sweep.Sweep("hy", [SOL], ["t"], 1, 1.0, tier="reserves", pack="fixtures-hybrid", env="gridsim-hybrid",
                     bundle="live")
    hy.out.mkdir(parents=True)
    (hy.out / "sweep.json").write_text(json.dumps(hy.spec()))
    result = CliRunner().invoke(gridsim, ["sweep", "report", "fc", "hy"])
    assert result.exit_code == 2 and "their references differ" in result.output


def test_forecast_episodes_replay_byte_for_byte_into_episode_json_v4(fake):
    assert run_forecast(fake).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "fc"])
    assert result.exit_code == 0, result.output
    [path] = Path("results/runs/fc").glob("*.json")
    e = json.loads(path.read_text())
    _, s = forecast_play(WINDOW)
    assert (e["schema"], e["env"], e["path"], e["bundle"], e["model"], e["reward"], e["tier"]) == (
        EPISODE_SCHEMA, FORECAST_ENV, "A", "live", SOL, 1.0, "front")
    assert [x["tool"] for x in e["steps"]] == [x["tool"] for x in s.transcript]
    assert NOTICE_TOOL in {x["tool"] for x in e["steps"]} and e["audit"] == {"ok": True, "problems": []}
    assert [d["missed"] for d in e["dam"]] == [False] * 3 and len(e["hours"]) == 72
    assert e["messages"] == [{"role": "assistant", "content": "Bid the cold front."}]


def test_a_tampered_record_does_not_replay(fake):
    assert run_forecast(fake, tamper=True).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "fc"])
    assert result.exit_code == 1 and f"MISMATCH {SOL} {WINDOW['task_id']} r1 a1: call" in result.output
    assert not list(Path("results/runs/fc").glob("*.json"))


@pytest.mark.parametrize(("args", "error"), [
    (["--env", "gridsim-forecast", "--pack", "fixtures-hybrid"], "fixtures-hybrid is not a forecast pack"),
    (["--pack", "fixtures-forecast"], "fixtures-forecast is a forecast pack"),
    ([*FORECAST, "--tier", "reserves"], "plays the tiers front-lite, front, blind, freeze-6h, not reserves"),
    (["--env", "gridsim-hybrid", "--pack", "fixtures-hybrid", "--tier", "front"], "front is a forecast tier"),
    ([*FORECAST, "--bundle", "oneshot"], "a live day has one harness")])
def test_a_forecast_sweep_takes_forecast_packs_and_tiers_only(fake, args, error):
    result = CliRunner().invoke(gridsim, ["sweep", "run", "--name", "x", *args, "--models", SOL, "--tasks", "1",
                                          "--cap-usd", "1"])
    assert result.exit_code == 2 and error in result.output, result.output
