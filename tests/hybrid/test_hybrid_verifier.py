"""gridsim-hybrid-verifier on the day data/get reports: the reward row and the weight-0 audit, hindsight, energy-only,
AS share, clipping and failure-to-provide rows; a day that never finished, failed its audit or was never loaded
raises, so the run is not scored."""

import copy
import importlib.util
from types import SimpleNamespace

import pytest
from hybrid_days import DAY, in_process, scripted

from agentenv_gridsim import hybrid_tasks
from agentenv_gridsim.hybrid import EMPTY
from gridsim_core.hybrid import Session, as_hog_policy

pytestmark = pytest.mark.anyio
spec = importlib.util.spec_from_file_location("gridsim_hybrid_verify", str(hybrid_tasks.VERIFY))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
WEIGHT_0 = ["audit", "hindsight_capture", "energy_only", "as_share", "clip_recovered", "ftp"]


@pytest.fixture
def serve(monkeypatch):
    """verify() reads this day as data/get."""
    days = {}

    async def get_data(base_url):
        assert base_url == "http://env:18765"
        return SimpleNamespace(parts=[SimpleNamespace(data=days["day"])])
    monkeypatch.setattr(verify.client, "get_data", get_data)
    return lambda day: days.update(day=day)


async def test_a_finished_day_scores_its_reward_with_the_weight_0_rows(serve):
    s, _ = in_process(DAY, "reserves", scripted(DAY, "reserves", as_hog_policy))
    serve(s.data())
    rows = await verify.verify("http://env:18765/mcp")
    g = s.grade()
    assert [(r["criterion"], r["weight"]) for r in rows] == [("gridsim", 1.0), *((c, 0.0) for c in WEIGHT_0)]
    assert rows[0]["episode"] == s.data() and (rows[0]["score"], rows[0]["result"]) == (g["reward"], g["reward"] >= 1)
    by = {r["criterion"]: r for r in rows}
    assert (by["hindsight_capture"]["value"], by["energy_only"]["value"], by["as_share"]["value"]) == (
        g["capture_vs_hindsight"], g["energy_only_reward"], g["as_share"])
    assert by["as_share"]["score"] == g["as_share"] > 0 and by["as_share"]["result"] is True
    assert by["energy_only"]["result"] is (g["reward"] > g["energy_only_reward"])
    assert by["ftp"]["value"] == {"charged": g["ftp_mwh_charged"], "excused": g["ftp_mwh_excused"]}
    assert all(isinstance(r["score"], float) for r in rows)


async def test_an_idle_day_ended_by_the_harness_scores_0(serve):
    s = Session(DAY, "reserves")
    s.end_day()
    serve(s.data())
    rows = await verify.verify("http://env:18765/mcp")
    assert rows[0]["score"] == 0.0 and {r["criterion"]: r["result"] for r in rows}["as_share"] is False


@pytest.mark.parametrize("break_it", ["unfinished", "audit", "unloaded"])
async def test_an_unscorable_day_raises(serve, break_it):
    s, _ = in_process(DAY, "reserves", scripted(DAY, "reserves", as_hog_policy))
    day = copy.deepcopy(s.data())
    if break_it == "unfinished":
        day = Session(DAY, "reserves").data()
    elif break_it == "audit":
        day["audit"] = {"ok": False, "problems": ["dev-dep-rrs revealed 2 times"]}
    else:
        day = EMPTY
    serve(day)
    with pytest.raises(RuntimeError, match="no day" if break_it == "unloaded" else "can't be scored"):
        await verify.verify("http://env:18765/mcp")
