"""gridsim-forecast-verifier on the window data/get reports: the reward row and the weight-0 audit, r_hind,
paired_vs_anchor, beats_anchor, r_roll3, forecast_value (blind), dam_missed and baselines rows; a window that never
finished, failed its audit or was never loaded raises, so the run is not scored."""

import copy
import importlib.util
from types import SimpleNamespace

import pytest
from forecast_days import WINDOW, anchor, in_process, scripted

from agentenv_gridsim import forecast_tasks
from agentenv_gridsim.forecast import EMPTY
from gridsim_core.forecast import Session

pytestmark = pytest.mark.anyio
spec = importlib.util.spec_from_file_location("gridsim_forecast_verify", str(forecast_tasks.VERIFY))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
WEIGHT_0 = ["audit", "r_hind", "paired_vs_anchor", "beats_anchor", "r_roll3"]


@pytest.fixture
def serve(monkeypatch):
    """verify() reads this window as data/get."""
    windows = {}

    async def get_data(base_url):
        assert base_url == "http://env:18765"
        return SimpleNamespace(parts=[SimpleNamespace(data=windows["w"])])
    monkeypatch.setattr(verify.client, "get_data", get_data)
    return lambda w: windows.update(w=w)


@pytest.mark.parametrize("tier", ["front", "blind"])
async def test_the_anchor_scores_1_with_the_weight_0_rows(serve, tier):
    s, _ = in_process(WINDOW, tier, scripted(WINDOW, tier, anchor(tier)))
    serve(s.data())
    rows = await verify.verify("http://env:18765/mcp")
    g = s.grade()
    extra = ["forecast_value"] if tier == "blind" else []
    assert [(r["criterion"], r["weight"]) for r in rows] == [
        ("gridsim", 1.0), *((c, 0.0) for c in [*WEIGHT_0, *extra, "dam_missed", "baselines"])]
    assert rows[0]["episode"] == s.data() and (rows[0]["score"], rows[0]["result"]) == (1.0, True)
    by = {r["criterion"]: r for r in rows}
    assert (by["r_hind"]["value"], by["paired_vs_anchor"]["value"], by["r_roll3"]["value"]) == (
        g["r_hind"], g["paired_vs_anchor"], g["r_roll3"])
    assert by["paired_vs_anchor"]["value"] == pytest.approx(0.0, abs=1e-6) and by["beats_anchor"]["value"] is False
    assert (by["dam_missed"]["value"], by["dam_missed"]["result"]) == (0, True)
    assert by["baselines"]["value"] == WINDOW["refs"][tier]["baselines"]
    assert by["baselines"]["result"] is (1.0 > WINDOW["refs"][tier]["baselines"]["naive"]["reward"])
    if tier == "blind":
        assert by["forecast_value"]["value"] == g["forecast_value"] is not None
    assert all(isinstance(r["score"], float) for r in rows)


async def test_a_window_ended_by_the_harness_with_no_dam_scores_0(serve):
    s = Session(WINDOW, "front")
    s.end_window()
    serve(s.data())
    rows = await verify.verify("http://env:18765/mcp")
    by = {r["criterion"]: r for r in rows}
    assert rows[0]["score"] == 0.0 and (by["dam_missed"]["value"], by["dam_missed"]["result"]) == (3, False)
    assert by["r_hind"]["value"] == 0.0 and by["baselines"]["result"] is False


@pytest.mark.parametrize("break_it", ["unfinished", "audit", "unloaded"])
async def test_an_unscorable_window_raises(serve, break_it):
    s, _ = in_process(WINDOW, "front-lite", scripted(WINDOW, "front-lite", anchor("front-lite")))
    w = copy.deepcopy(s.data())
    if break_it == "unfinished":
        w = Session(WINDOW, "front-lite").data()
    elif break_it == "audit":
        w["audit"] = {"ok": False, "problems": ["call 3 served a price vintage issued after now"]}
    else:
        w = EMPTY
    serve(w)
    with pytest.raises(RuntimeError, match="no window" if break_it == "unloaded" else "can't be scored"):
        await verify.verify("http://env:18765/mcp")
