"""No leaks: before the episode is done, no tool output and no data/get carries the reward, the optimum's profit, a
reference schedule or (blind) the day's prices; the env card and the tools say nothing of them either."""

import json

import httpx
import pytest
from conftest import BLIND, FIXTURES

pytestmark = pytest.mark.anyio
WORDS = ("reward", "r_opt", "p_opt", "profit_opt", "profit_anchor", "p_anchor", "refs", "baselines", "persist", "ridge",
         "greedy", "threshold", "p_idle", "profit_idle", "hindsight")


def secrets(task: dict, tier: str) -> list[str]:
    """Strings that would give a reference away: its schedules, the optimum's profit (unless greedy, which the probes
    check, reaches it), and in blind the day's prices."""
    f = task["refs"]["foresight"]
    found = [json.dumps(f["opt"]), json.dumps(f["opt"], separators=(",", ":"))]
    found += [json.dumps(b["schedule"], separators=(",", ":")) for b in f["baselines"].values() if any(b["schedule"])]
    if f["baselines"]["greedy"]["profit"] < f["p_opt"] - 0.01:
        found += [f"{round(f['p_opt'], 2)}"]
    if tier == "blind":
        found += [json.dumps(task["refs"]["blind"][k], separators=(",", ":")) for k in ("persist", "ridge")]
        found += [json.dumps([round(p, 2) for p in task["prices"]], separators=(", ", ": "))]
    return [s for s in found if s not in ("[]", "0")]


def leaks(text: str, task: dict, tier: str) -> list[str]:
    lowered = text.lower()
    return [w for w in WORDS if w in lowered] + [s for s in secrets(task, tier) if s in text]


CASES = [(FIXTURES[0], "foresight"), (BLIND[0], "blind")]


@pytest.mark.parametrize(("task", "tier"), CASES, ids=["foresight", "blind"])
async def test_nothing_before_done_gives_a_reference_away(harness, task, tier):
    await harness.load_task(task, tier)
    f = task["refs"]["foresight"]
    probes = [("get_situation", {}), ("check_schedule", {"actions": [0] * 24}),
              ("check_schedule", {"actions": f["baselines"]["greedy"]["schedule"]}),
              ("check_schedule", {"actions": "1 2"}), ("check_schedule", {"actions": [0] * 24}),
              ("submit_schedule", {"actions": "nope"}), ("no_such_tool", {}), ("check_schedule", {})]
    async with harness.session() as session:
        listed = json.dumps([t.model_dump(mode="json") for t in (await session.list_tools()).tools])
        assert leaks(listed, task, tier) == []
        for name, args in probes:
            out = await harness.call(session, name, args)
            assert leaks(out, task, tier) == [], (name, out)
            data = await harness.data()
            assert (data["done"], data["grade"], data["reward"], data["task"], data["schedule"]) == (
                False, None, None, None, None)
            assert [s for s in secrets(task, tier) if s in json.dumps(data)] == []
        out = await harness.call(session, "submit_schedule", {"actions": f["opt"]})
        assert not {"reward", "r_opt", "profit_opt"} & json.loads(out).keys()
    data = await harness.data()
    assert data["done"] and data["reward"] is not None and data["task"]["task_id"] == task["task_id"]


async def test_the_env_card_carries_no_task(harness):
    card = httpx.get(f"{harness.base_url}/.well-known/agent-env.json").text
    assert leaks(card.replace("urn:agentenv:", ""), FIXTURES[0], "foresight") == []
