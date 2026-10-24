"""`agent-env gridsim sweep run --env gridsim-hybrid`, its report and `episodes` with a stand-in `agent-env run`: the
hybrid rows, eval-v3.json and board-v3.md against the hybrid references, and Episode JSON v3 replayed byte for byte
through the hybrid Session."""

import json
from pathlib import Path

from click.testing import CliRunner
from hybrid_days import DAY, scripted
from sweep_fake import play, stored, summary

from agentenv_gridsim import hybrid_tasks, sweep
from agentenv_gridsim.cli import gridsim
from gridsim_core.hybrid import EPISODE_SCHEMA, HYBRID_ENV, NOTICE_TOOL, Session, as_hog_policy

SOL = "openai/gpt-6.1-sol"
HYBRID = ["--env", "gridsim-hybrid", "--pack", "fixtures-hybrid"]


def hybrid_play(task: dict, tier: str = "reserves", tamper: bool = False) -> tuple[dict, Session]:
    """gridsim-llm's record of the AS-hog day through the gateway (a get_time read before each turn's calls), and the
    day the env holds once played."""
    s, steps, tools = Session(task, tier), [], []
    calls = scripted(task, tier, as_hog_policy)
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
              "usage": {"input_tokens": 9000, "output_tokens": 900}, "turns": len(calls), "end_reason": "done",
              "errors": [], "messages": [{"role": "assistant", "content": "Hold the reserves.", "tool_calls": []},
                                         *tools]}
    return record, s


def hybrid_scored(s: Session, trajectory: str) -> dict:
    g = s.grade()
    return stored(play(s.task["task_id"], SOL, summary(SOL, "done", live=True, reward=g["reward"]),
                       trajectory=trajectory),
                  verifications={"gridsim": {"results": [
                      {"criterion": "gridsim", "result": g["reward"] >= 1.0, "score": g["reward"], "weight": 1.0,
                       "episode": json.loads(json.dumps(s.data()))},
                      {"criterion": "audit", "result": True, "score": 1.0, "weight": 0.0},
                      {"criterion": "hindsight_capture", "result": False, "score": g["capture_vs_hindsight"],
                       "weight": 0.0}], "score": g["reward"]}})


def run_hybrid(fake, tamper: bool = False, tier: str = "reserves"):
    (fake.root / "records").mkdir(exist_ok=True)
    record, s = hybrid_play(DAY, tier, tamper)
    (fake.root / "records" / f"{DAY['task_id']}.json").write_text(json.dumps(record))
    fake.script({f"{SOL}|{DAY['task_id']}": [{"context": hybrid_scored(s, f"file:///{DAY['task_id']}.json")}]})
    return CliRunner().invoke(gridsim, ["sweep", "run", "--name", "hy", *HYBRID, "--models", SOL, "--tasks",
                                        DAY["task_id"], "--tier", tier, "--cap-usd", "10"])


def test_a_hybrid_attempt_is_a_row_with_the_hybrid_grade(fake):
    result = run_hybrid(fake)
    assert result.exit_code == 0, result.output
    [row] = sweep.results(Path("results/runs/hy/raw"))
    g = hybrid_play(DAY)[1].grade()
    assert (row["outcome"], row["reward"], row["r_opt"], row["bundle"], row["tier"]) == (
        "scored", g["reward"], g["capture_vs_hindsight"], "live", "reserves")
    assert (row["profit"], row["profit_anchor"], row["profit_opt"], row["as_share"], row["energy_only_reward"]) == (
        g["profit_usd"], g["p_anchor"], g["p_hind"], g["as_share"], g["energy_only_reward"])
    assert (row["valid"], row["commits"], row["audit_ok"], row["end_reason"]) == (True, 1, True, "done")
    assert "no_replanning" in row["errors"] and "no_commit" not in row["errors"]
    spec = json.loads(Path("results/runs/hy/raw/sweep.json").read_text())
    assert (spec["env"], spec["bundle"], spec["pack"], spec["tier"]) == (HYBRID_ENV, "live", "fixtures-hybrid",
                                                                         "reserves")
    bundle = json.loads(Path(f"results/runs/hy/raw/bundle/tasks/{DAY['task_id']}.json").read_text())
    assert bundle[-1]["file_artifact_id"] == "gridsim-hybrid-verifier"


def test_the_hybrid_report_writes_eval_v3_and_the_hybrid_board(fake):
    assert run_hybrid(fake).exit_code == 0
    result = CliRunner().invoke(gridsim, ["sweep", "report", "hy"])
    assert result.exit_code == 0, result.output
    card = json.loads(Path("results/eval-v3.json").read_text())
    [m] = card["models"]
    g = hybrid_play(DAY)[1].grade()
    assert (card["env"], card["version"], m["tier"], m["tasks"], m["mean"], m["as_share"]) == (
        HYBRID_ENV, "v3", "reserves", 1, round(g["reward"], 4), round(g["as_share"], 4))
    b = card["baselines"]["reserves"]
    refs = DAY["refs"]["reserves"]
    assert (b["n"], b["as_hog"], b["sponge"]) == (1, round(refs["baselines"]["as_hog"]["reward"], 4),
                                                  round(refs["baselines"]["sponge"]["reward"], 4))
    assert m["by_as_stratum"] == {s: m["mean"] if s == DAY["tags"].get("as_stratum") else None for s in sweep.STRATA}
    assert m["beats_sponge"] == float(g["reward"] > refs["baselines"]["sponge"]["reward"])
    assert Path("results/board-v3.md").read_text().startswith("# GridSim v3 hybrid board")


def test_each_tier_s_baselines_are_over_the_days_played_at_it(fake):
    assert run_hybrid(fake).exit_code == 0
    other = next(t for t in hybrid_tasks.pack_rows("fixtures-hybrid") if t["task_id"] != DAY["task_id"])
    record, s = hybrid_play(other, "energy")
    (fake.root / "records" / f"{other['task_id']}.json").write_text(json.dumps(record))
    fake.script({f"{SOL}|{other['task_id']}": [{"context": hybrid_scored(s, f"file:///{other['task_id']}.json")}]})
    result = CliRunner().invoke(gridsim, ["sweep", "run", "--name", "hy-e", *HYBRID, "--models", SOL, "--tasks",
                                          other["task_id"], "--tier", "energy", "--cap-usd", "10"])
    assert result.exit_code == 0, result.output
    assert CliRunner().invoke(gridsim, ["sweep", "report", "hy", "hy-e"]).exit_code == 0
    b = json.loads(Path("results/eval-v3.json").read_text())["baselines"]
    assert (b["reserves"]["n"], b["energy"]["n"]) == (1, 1)
    assert (b["reserves"]["as_hog"], b["energy"]["v2_energy"]) == (
        round(DAY["refs"]["reserves"]["baselines"]["as_hog"]["reward"], 4),
        round(other["refs"]["energy"]["baselines"]["v2_energy"]["reward"], 4))


def test_a_hybrid_and_a_live_sweep_are_reported_apart(fake):
    assert run_hybrid(fake).exit_code == 0
    live = sweep.Sweep("lv", [SOL], ["t"], 1, 1.0, pack="fixtures-live", env="gridsim-live", bundle="live")
    live.out.mkdir(parents=True)
    (live.out / "sweep.json").write_text(json.dumps(live.spec()))
    result = CliRunner().invoke(gridsim, ["sweep", "report", "hy", "lv"])
    assert result.exit_code == 2 and "hybrid sweeps on their own" in result.output


def test_hybrid_episodes_replay_byte_for_byte_into_episode_json_v3(fake):
    assert run_hybrid(fake).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "hy"])
    assert result.exit_code == 0, result.output
    [path] = Path("results/runs/hy").glob("*.json")
    e = json.loads(path.read_text())
    _, s = hybrid_play(DAY)
    assert (e["schema"], e["env"], e["path"], e["bundle"], e["model"], e["reward"], e["tier"]) == (
        EPISODE_SCHEMA, HYBRID_ENV, "A", "live", SOL, s.grade()["reward"], "reserves")
    assert [x["tool"] for x in e["steps"]] == [x["tool"] for x in s.transcript]
    assert NOTICE_TOOL in {x["tool"] for x in e["steps"]} and e["audit"] == {"ok": True, "problems": []}
    assert any(n["deploy"] for n in e["notices"]) and e["messages"] == [{"role": "assistant",
                                                                          "content": "Hold the reserves."}]


def test_a_tampered_record_does_not_replay(fake):
    assert run_hybrid(fake, tamper=True).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "hy"])
    assert result.exit_code == 1 and f"MISMATCH {SOL} {DAY['task_id']} r1 a1: call" in result.output
    assert not list(Path("results/runs/hy").glob("*.json"))


def test_a_hybrid_sweep_takes_hybrid_packs_and_tiers_only(fake):
    for args, error in [(["--env", "gridsim-hybrid", "--pack", "fixtures-live"], "fixtures-live is not a hybrid pack"),
                        (["--pack", "fixtures-hybrid"], "fixtures-hybrid is a hybrid pack"),
                        ([*HYBRID, "--tier", "foresight"], "plays the tiers energy, reserves, rtcb, not foresight"),
                        (["--env", "gridsim-live", "--pack", "fixtures-live", "--tier", "energy"],
                         "energy is a hybrid tier"),
                        ([*HYBRID, "--bundle", "oneshot"], "a live day has one harness")]:
        result = CliRunner().invoke(gridsim, ["sweep", "run", "--name", "x", *args, "--models", SOL, "--tasks", "1",
                                              "--cap-usd", "1"])
        assert result.exit_code == 2 and error in result.output, result.output
