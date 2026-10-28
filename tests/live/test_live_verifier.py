"""gridsim-live-verifier on the day data/get reports: the reward row and the weight-0 audit and hindsight rows; a day
that never finished, failed its audit or was never loaded raises, so the run is not scored."""

import copy
import importlib.util
from types import SimpleNamespace

import pytest
from live_days import NOTICE_DAY, in_process, naive_calls

from agentenv_gridsim import live_tasks
from agentenv_gridsim.live import EMPTY
from gridsim_core.live import Session

pytestmark = pytest.mark.anyio
spec = importlib.util.spec_from_file_location("gridsim_live_verify", str(live_tasks.VERIFY))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)


@pytest.fixture
def serve(monkeypatch):
    """verify() reads this day as data/get."""
    days = {}

    async def get_data(base_url):
        assert base_url == "http://env:18765"
        return SimpleNamespace(parts=[SimpleNamespace(data=days["day"])])
    monkeypatch.setattr(verify.client, "get_data", get_data)
    return lambda day: days.update(day=day)


async def test_a_finished_day_scores_its_reward_with_the_audit_and_hindsight_at_weight_0(serve):
    s, _ = in_process(NOTICE_DAY, "foresight", naive_calls(NOTICE_DAY))
    serve(s.data())
    rows = await verify.verify("http://env:18765/mcp")
    g = s.grade()
    assert [(r["criterion"], r["score"], r["weight"]) for r in rows] == [
        ("gridsim", g["reward"], 1.0), ("audit", 1.0, 0.0), ("hindsight_capture", g["capture_vs_hindsight"], 0.0)]
    assert rows[0]["episode"] == s.data() and rows[0]["result"] is (g["reward"] >= 1.0)


async def test_an_idle_day_ended_by_the_harness_scores_0(serve):
    s = Session(NOTICE_DAY)
    s.end_day()
    serve(s.data())
    assert (await verify.verify("http://env:18765/mcp"))[0]["score"] == 0.0


@pytest.mark.parametrize("break_it", ["unfinished", "audit", "unloaded"])
async def test_an_unscorable_day_raises(serve, break_it):
    s, _ = in_process(NOTICE_DAY, "foresight", naive_calls(NOTICE_DAY))
    day = copy.deepcopy(s.data())
    if break_it == "unfinished":
        day = Session(NOTICE_DAY).data()
    elif break_it == "audit":
        day["audit"] = {"ok": False, "problems": ["fixture-appeal-1 revealed 2 times"]}
    else:
        day = EMPTY
    serve(day)
    with pytest.raises(RuntimeError, match="no day" if break_it == "unloaded" else "can't be scored"):
        await verify.verify("http://env:18765/mcp")
