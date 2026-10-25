"""`agent-env gridsim sweep run --env gridsim-market`, its report and `episodes` with a stand-in `agent-env run`: the
market rows with both scorings, eval-v5.json and board-v5.md against the market references, and Episode JSON v5
replayed byte for byte through the market Session."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from market_floors import DAY, SPRINT, policies, scripted
from sweep_fake import play, stored, summary

from agentenv_gridsim import market_tasks, sweep
from agentenv_gridsim.cli import gridsim
from gridsim_core.market import EPISODE_SCHEMA, MARKET_ENV, Session

SOL = "openai/gpt-6.1-sol"
MARKET = ["--env", MARKET_ENV, "--pack", "fixtures-market"]


def market_play(task: dict, tier: str, policy: str = "anchor", tamper: bool = False,
                compliant: bool = False) -> tuple[dict, Session]:
    """gridsim-llm's record of the policy's floor through the gateway (a get_time read before each turn's calls), and
    the floor the env holds once played."""
    s, steps, tools = Session(task, tier, compliant=compliant), [], []
    calls = scripted(task, tier, policies(task)[policy])
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
        tools[-1]["content"] = tools[-1]["content"].replace('"messages":[]', '"messages":[],"x":1')
    end = "done" if tier == "floor-day" else "submitted"
    record = {"model": SOL, "effort": "high", "steps": steps, "final": {"done": True}, "turns": len(calls),
              "usage": {"input_tokens": 9000, "output_tokens": 900}, "end_reason": end, "errors": [],
              "messages": [{"role": "assistant", "content": "Offer the peak.", "tool_calls": []}, *tools]}
    return record, s


def market_scored(s: Session, trajectory: str) -> dict:
    g = s.grade()
    score = g["compliant_reward"] if s.compliant else g["reward"]
    end = "done" if s.tier == "floor-day" else "submitted"
    return stored(play(s.task["task_id"], SOL, summary(SOL, end, live=s.tier == "floor-day"), trajectory=trajectory),
                  verifications={"gridsim": {"results": [
                      {"criterion": "gridsim", "result": score >= 1.0, "score": score, "weight": 1.0,
                       "episode": json.loads(json.dumps(s.data() | {"compliant": s.compliant}))},
                      {"criterion": "audit", "result": True, "score": 1.0, "weight": 0.0},
                      {"criterion": "hindsight_capture", "result": False, "score": 1 - g["regret_norm"],
                       "weight": 0.0}], "score": score}})


def run_market(fake, name: str = "mk", task: dict = SPRINT, tier: str = "floor-sprint", policy: str = "anchor",
               tamper: bool = False, compliant: bool = False):
    (fake.root / "records").mkdir(exist_ok=True)
    record, s = market_play(task, tier, policy, tamper, compliant)
    (fake.root / "records" / f"{task['task_id']}-{tier}.json").write_text(json.dumps(record))
    fake.script({f"{SOL}|{task['task_id']}": [{"context": market_scored(s, f"file:///{task['task_id']}-{tier}.json")}]})
    return CliRunner().invoke(gridsim, ["sweep", "run", "--name", name, *MARKET, "--models", SOL, "--tasks",
                                        task["task_id"], "--tier", tier, *(["--compliant"] if compliant else []),
                                        "--cap-usd", "10"])


def test_a_market_attempt_is_a_row_with_both_scorings(fake):
    result = run_market(fake)
    assert result.exit_code == 0, result.output
    [row] = sweep.results(Path("results/runs/mk/raw"))
    g = market_play(SPRINT, "floor-sprint")[1].grade()
    assert (row["outcome"], row["reward"], row["market_reward"], row["compliant_reward"], row["bundle"]) == (
        "scored", 1.0, 1.0, g["compliant_reward"], "live")
    assert (row["profit"], row["profit_anchor"], row["profit_opt"], row["welfare_ratio"], row["eps_nash"]) == (
        g["profit_usd"], g["p_anchor"], g["p_br"], g["welfare_ratio"], g["eps_nash"])
    assert (row["valid"], row["audit_ok"], row["end_reason"], row["errors"]) == (True, True, "submitted", [])
    spec = json.loads(Path("results/runs/mk/raw/sweep.json").read_text())
    assert (spec["env"], spec["tier"], spec["episode_cap_usd"]) == (MARKET_ENV, "floor-sprint",
                                                                    market_tasks.EPISODE_CAP_USD["floor-sprint"])
    bundle = json.loads(Path(f"results/runs/mk/raw/bundle/tasks/{SPRINT['task_id']}.json").read_text())
    assert bundle[-1]["file_artifact_id"] == "gridsim-market-verifier"
    assert next(s for s in bundle if s["id"] == "deploy-agent")["env_vars"] == {"GRIDSIM_MAX_COST_USD": "1"}


def test_the_market_report_writes_eval_v5_and_the_market_board(fake):
    assert run_market(fake).exit_code == 0
    assert run_market(fake, "mk-day", DAY, "floor-day", compliant=True).exit_code == 0
    result = CliRunner().invoke(gridsim, ["sweep", "report", "mk", "mk-day"])
    assert result.exit_code == 0, result.output
    card = json.loads(Path("results/eval-v5.json").read_text())
    assert (card["env"], card["version"], card["tasks"]["n"], card["tasks"]["op_days"]) == (MARKET_ENV, "v5", 2, 2)
    sprint, day = sorted(card["models"], key=lambda m: m["tier"], reverse=True)
    g = market_play(DAY, "floor-day", compliant=True)[1].grade()
    gs = market_play(SPRINT, "floor-sprint")[1].grade()
    assert (sprint["scoring"], sprint["sweep_scoring"], sprint["mean"], sprint["reward"]["mean"]) == (
        "compliant", "reward", round(gs["compliant_reward"], 4), 1.0)
    assert (day["scoring"], day["mean"], day["reward"]["mean"], day["compliant_reward"]["mean"]) == (
        "compliant", round(g["compliant_reward"], 4), 1.0, round(g["compliant_reward"], 4))
    assert sprint["peak"]["n"] == int(sweep.market_peak(SPRINT)) == card["tasks"]["peak"]
    assert sprint["price_making_gain_usd_per_mw_day"] == round(gs["price_making_gain_usd_per_mw_day"], 2)
    b = card["baselines"]["floor-sprint"]
    assert (b["n"], b["replay_A"]) == (1, round(SPRINT["refs"]["floor-sprint"]["baselines"]["replay_A"]["reward"], 4))
    assert (b["played"]["reward"]["anchor"], b["played"]["compliant"]["anchor"]) == (
        1.0, round(gs["compliant_reward"], 4))
    assert card["baselines"]["floor-day"]["replay_A"] is None and day["errors"]["no_schedule"] == 0
    assert card["grading"]["headline"] == "compliant"
    board = Path("results/board-v5.md").read_text()
    public, research = board.split("## Research board")
    assert board.startswith("# GridSim v5 market board") and "## Public board" in public
    assert "Peak floors" in public and "| R (95% CI) |" not in public and "Regret" not in public
    assert "| R (95% CI) | R peak | Regret (norm) |" in research and "| reward |" in research


def test_market_episodes_replay_byte_for_byte_into_episode_json_v5(fake):
    assert run_market(fake, "mk-day", DAY, "floor-day", compliant=True).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "mk-day"])
    assert result.exit_code == 0, result.output
    [path] = Path("results/runs/mk-day").glob("*.json")
    e = json.loads(path.read_text())
    _, s = market_play(DAY, "floor-day", compliant=True)
    assert (e["schema"], e["env"], e["path"], e["bundle"], e["model"], e["tier"], e["compliant"]) == (
        EPISODE_SCHEMA, MARKET_ENV, "A", "compliant", SOL, "floor-day", True)
    assert (e["reward"], e["compliant_reward"]) == (1.0, s.grade()["compliant_reward"])
    assert [x["tool"] for x in e["steps"]] == [x["tool"] for x in s.transcript]
    assert e["audit"] == {"ok": True, "problems": []} and e["messages"] == [{"role": "assistant",
                                                                            "content": "Offer the peak."}]
    assert len(e["stack"]) == 24 and e["clear"]["lambda_replay"] == DAY["refs"]["replay_lambda_usd"]


def test_a_tampered_market_record_does_not_replay(fake):
    assert run_market(fake, tamper=True).exit_code == 0
    result = CliRunner().invoke(gridsim, ["episodes", "mk"])
    assert result.exit_code == 1 and f"MISMATCH {SOL} {SPRINT['task_id']} r1 a1: call" in result.output
    assert not list(Path("results/runs/mk").glob("*.json"))


def test_a_market_and_a_hybrid_sweep_are_reported_apart(fake):
    assert run_market(fake).exit_code == 0
    other = sweep.Sweep("hy", [SOL], ["t"], 1, 1.0, pack="fixtures-hybrid", env="gridsim-hybrid", bundle="live",
                        tier="reserves")
    other.out.mkdir(parents=True)
    (other.out / "sweep.json").write_text(json.dumps(other.spec()))
    result = CliRunner().invoke(gridsim, ["sweep", "report", "mk", "hy"])
    assert result.exit_code == 2 and "market sweeps each on their own" in result.output


@pytest.mark.parametrize(("args", "error"), [
    (["--env", MARKET_ENV, "--pack", "fixtures-hybrid"], "fixtures-hybrid is not a market pack"),
    (["--pack", "fixtures-market"], "fixtures-market is a market pack: play it with --env gridsim-market"),
    (["--env", "gridsim-live", "--pack", "fixtures-live", "--compliant"], "use it with --env gridsim-market"),
    ([*MARKET, "--tier", "reserves"], "plays the tiers floor-sprint, floor-day in one harness, not reserves"),
    ([*MARKET, "--bundle", "oneshot"], "in one harness"),
    ([*MARKET, "--episode-cap-usd", "0.1"], "so no turn could start")])
def test_a_market_sweep_takes_market_packs_and_tiers_only(fake, args, error):
    result = CliRunner().invoke(gridsim, ["sweep", "run", "--name", "x", *args, "--models", SOL, "--tasks", "1",
                                          "--cap-usd", "1"])
    assert result.exit_code == 2 and error in result.output, result.output
