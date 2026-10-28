import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import desk_run  # noqa: E402

from gridsim_core.desk import fixtures, policies  # noqa: E402


class FakeAgent(desk_run.ModelAgent):
    """A model that checks its position once per turn; every call costs a fixed amount."""

    COST = 0.02

    def __init__(self, a, preset, lane_spent, system, tools, budget=None):
        self.max_usd, self.max_tokens, self.price = a.max_usd, None, (0.0, 0.0, 0.0)
        self.system, self.tools = system, []
        self.budget = budget or desk_run.Budget(None, 0.0)
        self.route, self.items, self.turn_starts = "chat", [], []
        self.usage = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0,
                      "latency_s": 0.0}
        self.n = 0

    def worst(self) -> float:
        return self.COST

    def _step(self, log, worst):
        self.n += 1
        self.usage["cost_usd"] = round(self.usage["cost_usd"] + self.COST, 6)
        self.budget.settle(worst, self.COST)
        if self.n % 2:
            self.items.append({"role": "assistant", "content": ""})
            return "", [(f"c{self.n}", "get_position", "{}")]
        self.items.append({"role": "assistant", "content": "done"})
        return "done", []


def _args(out, **kw):
    base = dict(pack=None, fixture=None, tasks=None, tasks_file=None, limit=None, layer="v2", policy="model",
                preset="luna", model="fake", effort=None, price=None, base_url=None, gateway_env=None, ssm_param=None,
                aws_profile=None, aws_region=None, max_usd=5.0, lane_cap_usd=None, max_tokens=None, max_turns=None,
                timeout=1.0, tag="fake", parallel=3)
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture
def fake(monkeypatch):
    monkeypatch.setattr(desk_run, "ModelAgent", FakeAgent)


def test_shared_lane_cap_never_overrun(tmp_path, fake):
    items = [fixtures.make("2026-02-14", seed=i) for i in range(3)]
    a = _args(tmp_path, lane_cap_usd=0.25)
    budget = desk_run.Budget(a.lane_cap_usd, 0.0)
    rows = []
    threads = [threading.Thread(target=lambda t=t, s=s: rows.append(
        desk_run.episode(t, s, a, desk_run.MODELS["luna"], tmp_path, "fake", budget))) for t, s in items]
    for d in ("episodes", "calls", "ckpt"):
        (tmp_path / d).mkdir()
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert budget.spent <= 0.25 + 1e-9 and budget.inflight == pytest.approx(0.0)
    assert len(rows) == 3 and all(r["status"].startswith("capped") for r in rows)
    assert all("capture_phys" in r for r in rows)


def test_stop_keeps_checkpoint_and_resumes(tmp_path, fake):
    task, series = fixtures.make("2026-02-14", seed=4)
    a = _args(tmp_path)
    for d in ("episodes", "calls", "ckpt"):
        (tmp_path / d).mkdir()
    budget = desk_run.Budget(None, 0.0)
    calls = {"n": 0}
    orig = FakeAgent._step

    def stopping(self, log, worst):
        calls["n"] += 1
        if calls["n"] == 7:
            budget.stop.set()
        return orig(self, log, worst)

    FakeAgent._step = stopping
    try:
        assert desk_run.episode(task, series, a, desk_run.MODELS["luna"], tmp_path, "fake", budget) is None
    finally:
        FakeAgent._step = orig
    ck = json.loads((tmp_path / "ckpt" / f"{task['task_id']}.fake.json").read_text())
    full = len(policies.run(task, series, "idle").turns)
    assert 1 <= len(ck["turns"]) < full
    row = desk_run.episode(task, series, a, desk_run.MODELS["luna"], tmp_path, "fake", desk_run.Budget(None, 0.0))
    assert row["status"] == "ok" and row["usage"]["turns"] == full
