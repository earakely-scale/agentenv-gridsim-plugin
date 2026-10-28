"""gridsim-market-verifier on the floor data/get reports: the reward row (or the compliant score on a compliant floor)
and the weight-0 audit, hindsight, regret, other-scoring, epsilon-Nash, welfare, CfD, conduct, rank and fidelity rows; a
floor that never finished, failed its audit or was never loaded raises, so the run is not scored."""

import copy
import importlib.util
from types import SimpleNamespace

import pytest
from market_floors import DAY, SPRINT, in_process, policies, scripted

from agentenv_gridsim import market_tasks
from agentenv_gridsim.market import EMPTY
from gridsim_core.market import Session

pytestmark = pytest.mark.anyio
spec = importlib.util.spec_from_file_location("gridsim_market_verify", str(market_tasks.VERIFY))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
SPRINT_ROWS = ["audit", "hindsight_capture", "regret", "compliant", "eps_nash", "welfare", "conduct", "rank",
               "fidelity"]


@pytest.fixture
def serve(monkeypatch):
    """verify() reads this floor as data/get."""
    floors = {}

    async def get_data(base_url):
        assert base_url == "http://env:18765"
        return SimpleNamespace(parts=[SimpleNamespace(data=floors["floor"])])
    monkeypatch.setattr(verify.client, "get_data", get_data)
    return lambda floor: floors.update(floor=floor)


def floor(task: dict, tier: str, policy: str = "anchor", compliant: bool = False) -> tuple[Session, dict]:
    s, _ = in_process(task, tier, scripted(task, tier, policies(task)[policy]))
    return s, s.data() | {"compliant": compliant}


async def test_a_sprint_scores_its_reward_with_the_weight_0_rows(serve):
    s, data = floor(SPRINT, "floor-sprint")
    serve(data)
    rows = await verify.verify("http://env:18765/mcp")
    g = s.grade()
    assert [(r["criterion"], r["weight"]) for r in rows] == [("gridsim", 1.0), *((c, 0.0) for c in SPRINT_ROWS)]
    assert rows[0]["episode"] == data and (rows[0]["score"], rows[0]["result"]) == (1.0, True)
    by = {r["criterion"]: r for r in rows}
    assert by["hindsight_capture"]["value"] == round(1 - g["regret_norm"], 6)
    assert by["regret"]["value"] == {"usd": g["regret_usd"], "norm": g["regret_norm"]}
    assert (by["compliant"]["value"], by["eps_nash"]["value"]) == (g["compliant_reward"], g["eps_nash"])
    assert by["welfare"]["value"] == {"ratio": g["welfare_ratio"], "dwl_usd": g["dwl_usd"]}
    assert (by["conduct"]["value"], by["rank"]["value"], by["fidelity"]["value"]) == (
        g["conduct"], g["rank"], SPRINT["fidelity"])
    assert all(isinstance(r["score"], float) and isinstance(r["result"], bool) for r in rows)


async def test_a_compliant_day_scores_the_compliant_reward_and_carries_the_contract_row(serve):
    s, data = floor(DAY, "floor-day", compliant=True)
    serve(data)
    rows = await verify.verify("http://env:18765/mcp")
    g = s.grade()
    by = {r["criterion"]: r for r in rows}
    assert rows[0]["score"] == g["compliant_reward"] < 1.0 and by["reward"]["value"] == g["reward"] == 1.0
    assert "compliant" not in by and by["contract"]["value"] == g["contract"]
    assert by["contract"]["result"] is True


async def test_an_idle_floor_ended_by_the_harness_scores_0(serve):
    s = Session(DAY, "floor-day")
    s.end_floor()
    serve(s.data() | {"compliant": False})
    rows = await verify.verify("http://env:18765/mcp")
    assert rows[0]["score"] == 0.0 and rows[0]["result"] is False


@pytest.mark.parametrize("break_it", ["unfinished", "audit", "unloaded"])
async def test_an_unscorable_floor_raises(serve, break_it):
    _, data = floor(SPRINT, "floor-sprint")
    data = copy.deepcopy(data)
    if break_it == "unfinished":
        data = Session(SPRINT, "floor-sprint").data() | {"compliant": False}
    elif break_it == "audit":
        data["audit"] = {"ok": False, "problems": ["get_disclosure served 2024-07-01 at 2024-08-19 09:00"]}
    else:
        data = EMPTY
    serve(data)
    with pytest.raises(RuntimeError, match="no floor" if break_it == "unloaded" else "can't be scored"):
        await verify.verify("http://env:18765/mcp")
