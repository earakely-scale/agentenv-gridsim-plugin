import json

from gridsim_core import prompt
from gridsim_core.dp import solve_dp
from gridsim_core.episode import SCHEMA, check_result, submit_result, to_episode_json
from gridsim_core.grade import grade
from gridsim_core.task import make_battery, make_task
from gridsim_core.trl import extract_actions, reward_fn

PRICES = [10.0] * 4 + [30.0] * 12 + [100.0] * 4 + [30.0] * 4
TASK = make_task(PRICES, make_battery(100, 200, 4, eta=0.85, c_deg=4.0, cycles=1.5),
                 blind={"dam_prev_day": PRICES, "dam_prev_7d": [PRICES] * 7})
OPT = solve_dp(TASK)[1]


def qwen(acts, name="submit_schedule"):
    return f'<tool_call>\n{json.dumps({"name": name, "arguments": {"actions": acts}})}\n</tool_call>'


def test_reward_fn_forms():
    s = " ".join(map(str, OPT))
    completions = [
        "<think>plan</think>\n" + qwen(OPT),
        qwen(s),
        [{"role": "assistant", "content": "", "tool_calls": [
            {"type": "function", "function": {"name": "submit_schedule", "arguments": json.dumps({"actions": OPT})}}]}],
        f"My schedule: {json.dumps(OPT)}",
        qwen(OPT[:23]) + qwen(OPT),
        qwen([0] * 24, "check_schedule"),
        qwen(OPT[:23]),
        "no answer",
        "<think>" + qwen(OPT),
        [{"role": "assistant", "content": [{"type": "text", "text": qwen([0] * 24)}]}],
    ]
    got = reward_fn(["p"] * len(completions), completions, task=[TASK] * len(completions))
    assert got == [1.0, 1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.2]
    assert reward_fn(["p"], [qwen(OPT)], task=[json.dumps(TASK)]) == [1.0]


def test_extract_prefers_first_valid_submit():
    assert extract_actions(qwen([0] * 24) + qwen(OPT)) == [0] * 24
    assert extract_actions(qwen("bad") + qwen(OPT)) == OPT


def test_prompt_is_task_number_free_and_stable():
    for tier in ("foresight", "blind"):
        for checks in (0, 3):
            sp = prompt.system_prompt(TASK, tier, checks)
            assert sp == prompt.system_prompt(dict(TASK, prices=[1.0] * 24), tier, checks)
            assert "submit_schedule" in sp and ("check_schedule" in sp) == bool(checks)
    sit = prompt.situation(TASK, "foresight", 3)
    assert sit["prices_usd_per_mwh"] == PRICES and "dam_prev_day_usd_per_mwh" not in sit
    blind = prompt.situation(TASK, "blind", 0)
    assert "prices_usd_per_mwh" not in blind and len(blind["dam_prev_7d_usd_per_mwh"]) == 7
    assert json.loads(prompt.situation_text(TASK, "blind", 0)) == blind
    msgs = prompt.messages(TASK, "foresight", 0)
    assert [m["role"] for m in msgs] == ["system", "user"]
    names = [t["function"]["name"] for t in prompt.tool_schemas("foresight", 3, get_situation=True)]
    assert names == ["get_situation", "check_schedule", "submit_schedule"]
    assert [t["function"]["name"] for t in prompt.tool_schemas("foresight", 0)] == ["submit_schedule"]


def test_tool_outputs():
    c = check_result(TASK, OPT, 2)
    assert c["feasible"] and c["checks_left"] == 2 and c["profit_usd"] == round(solve_dp(TASK)[0], 2)
    assert check_result(TASK, OPT, 2, "blind")["profit_usd"] is None
    assert "error" in check_result(TASK, [0], 1)
    s = submit_result(TASK, OPT)
    assert s["submitted"] and set(s) == {"submitted", "feasible", "truncated_at", "violation", "soc_path", "profit_usd"}
    assert submit_result(TASK, "x")["submitted"] is False


def test_episode_json():
    e = to_episode_json(TASK, OPT, "foresight", 0, model="qwen3-1.7b", trained="grpo", checkpoint_step=100)
    assert e["schema"] == SCHEMA and e["reward"] == 1.0 and e["r_opt"] == 1.0
    assert e["final_schedule"] == OPT and len(e["hourly"]) == 24 and len(e["soc_path"]) == 25
    assert e["steps"][0]["tool"] == "submit_schedule" and e["steps"][0]["output"]["submitted"]
    assert e["situation"] == prompt.situation(TASK, "foresight", 0)
    assert abs(sum(h["cash"] for h in e["hourly"]) - e["profit_usd"]) < 1e-3
    assert e == to_episode_json(TASK, OPT, "foresight", 0, model="qwen3-1.7b", trained="grpo", checkpoint_step=100)
    bad = to_episode_json(TASK, "nope")
    assert bad["reward"] == 0.0 and bad["final_schedule"] is None and bad["hourly"] is None
    json.dumps(e)
    assert abs(grade(TASK, e["final_schedule"])["profit"] - e["profit_usd"]) < 1e-6
