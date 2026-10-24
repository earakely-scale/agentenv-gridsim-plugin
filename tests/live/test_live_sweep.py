"""`agent-env gridsim sweep run --env gridsim-live`, its report and `episodes` with a stand-in `agent-env run`: the live
rows, eval-v2.json and board-v2.md against the live references, and Episode JSON v2 replayed byte for byte through
the Session."""

import json
from pathlib import Path

from click.testing import CliRunner
from live_days import NOTICE_DAY, QUIET_DAY, naive_calls
from sweep_fake import play, stored, summary

from agentenv_gridsim import sweep
from agentenv_gridsim.cli import gridsim
from gridsim_core.live import EPISODE_SCHEMA, NOTICE_TOOL, Session

SOL = "openai/gpt-6.1-sol"
LIVE = ["--env", "gridsim-live", "--pack", "fixtures-live"]


def live_play(task: dict, tier: str = "foresight", tamper: bool = False) -> tuple[dict, Session]:
    """gridsim-llm's record of the naive day through the gateway (a get_time read before each turn's calls), and the
    day the env holds once played."""
    s, steps, tools = Session(task, tier), [], []
    for turn, calls in enumerate(naive_calls(task, tier), 1):
        for name, args in [("get_time", {}), *calls]:
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
              "usage": {"input_tokens": 9000, "output_tokens": 900}, "turns": len(naive_calls(task, tier)),
              "end_reason": "done", "errors": [],
              "messages": [{"role": "assistant", "content": "Follow the DA plan.", "tool_calls": []}, *tools]}
    return record, s


def live_scored(s: Session, trajectory: str) -> dict:
    g = s.grade()
    return stored(play(s.task["task_id"], SOL, summary(SOL, "done", live=True, reward=g["reward"]),
                       trajectory=trajectory),
                  verifications={"gridsim": {"results": [
                      {"criterion": "gridsim", "result": g["reward"] >= 1.0, "score": g["reward"], "weight": 1.0,
                       "episode": json.loads(json.dumps(s.data()))},
                      {"criterion": "audit", "result": True, "score": 1.0, "weight": 0.0},
                      {"criterion": "hindsight_capture", "result": False, "score": g["capture_vs_hindsight"],
                       "weight": 0.0}], "score": g["reward"]}})


def run_live(fake, tasks: list[dict], tamper: set[str] = frozenset()):
    (fake.root / "records").mkdir(exist_ok=True)
    script = {}
    for task in tasks:
        record, s = live_play(task, tamper=task["task_id"] in tamper)
        (fake.root / "records" / f"{task['task_id']}.json").write_text(json.dumps(record))
        script[f"{SOL}|{task['task_id']}"] = [{"context": live_scored(s, f"file:///{task['task_id']}.json")}]
    fake.script(script)
    return CliRunner().invoke(gridsim, ["sweep", "run", "--name", "lv", *LIVE, "--models", SOL, "--tasks",
                                        ",".join(t["task_id"] for t in tasks), "--cap-usd", "10"])


def test_a_live_attempt_is_a_row_with_the_live_grade(fake):
    result = run_live(fake, [NOTICE_DAY])
    assert result.exit_code == 0, result.output
    [row] = sweep.results(Path("results/runs/lv/raw"))
    _, s = live_play(NOTICE_DAY)
    g = s.grade()
    assert (row["outcome"], row["reward"], row["r_opt"], row["bundle"], row["tier"]) == (
        "scored", g["reward"], g["capture_vs_hindsight"], "live", "foresight")
    assert (row["profit"], row["profit_anchor"], row["profit_naive"], row["naive_reward"], row["commits"]) == (
        g["profit_usd"], g["p_roll"], g["p_naive"], g["naive_reward"], 1)
    assert (row["checks"], row["errors"], row["valid"], row["audit_ok"], row["end_reason"]) == (
        1, ["no_replanning"], True, True, "done")
    spec = json.loads(Path("results/runs/lv/raw/sweep.json").read_text())
    assert (spec["env"], spec["bundle"], spec["pack"]) == ("gridsim-live", "live", "fixtures-live")
    bundle = json.loads(Path(f"results/runs/lv/raw/bundle/tasks/{NOTICE_DAY['task_id']}.json").read_text())
    assert bundle[-1]["file_artifact_id"] == "gridsim-live-verifier"


def test_the_live_report_writes_eval_v2_and_the_live_board(fake):
    assert run_live(fake, [NOTICE_DAY, QUIET_DAY]).exit_code == 0
    result = CliRunner().invoke(gridsim, ["sweep", "report", "lv"])
    assert result.exit_code == 0, result.output
    card = json.loads(Path("results/eval-v2.json").read_text())
    [m] = card["models"]
    rewards = [live_play(t)[1].grade()["reward"] for t in (NOTICE_DAY, QUIET_DAY)]
    assert (card["env"], card["version"], m["tier"], m["tasks"], m["mean"]) == (
        "gridsim-live", "v2", "foresight", 2, round(sum(rewards) / 2, 4))
    assert card["baselines"]["foresight"]["naive"] == round(sum(
        t["refs"]["roll"]["foresight"]["naive_reward"] for t in (NOTICE_DAY, QUIET_DAY)) / 2, 4)
    assert (m["errors"]["no_replanning"], m["beats_naive"], m["finished_by_agent"]) == (2, 0.0, 1.0)
    assert Path("results/board-v2.md").read_text().startswith("# GridSim v2 live board")


def test_a_v1_and_a_live_sweep_are_reported_apart(fake):
    assert run_live(fake, [QUIET_DAY]).exit_code == 0
    v1 = sweep.Sweep("v1", [SOL], ["t"], 1, 1.0, pack="fixtures")
    (v1.out).mkdir(parents=True)
    (v1.out / "sweep.json").write_text(json.dumps(v1.spec()))
    result = CliRunner().invoke(gridsim, ["sweep", "report", "lv", "v1"])
    assert result.exit_code == 2 and "report v1 and live sweeps separately" in result.output
    assert "env" not in v1.spec()


def test_live_episodes_replay_byte_for_byte_into_episode_json_v2(fake):
    assert run_live(fake, [NOTICE_DAY, QUIET_DAY], tamper={QUIET_DAY["task_id"]}).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "lv"])
    assert result.exit_code == 1
    assert f"MISMATCH {SOL} {QUIET_DAY['task_id']} r1 a1: call" in result.output
    [path] = Path("results/runs/lv").glob("*.json")
    e = json.loads(path.read_text())
    _, s = live_play(NOTICE_DAY)
    assert (e["schema"], e["env"], e["path"], e["bundle"], e["model"], e["reward"]) == (
        EPISODE_SCHEMA, "gridsim-live", "A", "live", SOL, s.grade()["reward"])
    assert [x["tool"] for x in e["steps"]] == [x["tool"] for x in s.transcript]
    assert NOTICE_TOOL in {x["tool"] for x in e["steps"]} and e["audit"] == {"ok": True, "problems": []}
    assert e["messages"] == [{"role": "assistant", "content": "Follow the DA plan."}]


def test_a_live_sweep_takes_live_packs_only(fake):
    for args, error in [(["--env", "gridsim-live", "--pack", "fixtures"], "fixtures is not a live pack"),
                        (["--pack", "fixtures-live"], "fixtures-live is a live pack"),
                        ([*LIVE, "--bundle", "oneshot"], "a live day has one harness")]:
        result = CliRunner().invoke(gridsim, ["sweep", "run", "--name", "x", *args, "--models", SOL, "--tasks", "1",
                                              "--cap-usd", "1"])
        assert result.exit_code == 2 and error in result.output, result.output
