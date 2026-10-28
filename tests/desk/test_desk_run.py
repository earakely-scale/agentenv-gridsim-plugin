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

    def __init__(self, a, preset, lane_spent, system, tools, budget=None, layer=None):
        self.max_usd, self.max_tokens, self.price = a.max_usd, None, (0.0, 0.0, 0.0)
        self.system, self.tools = system, []
        self.budget = budget or desk_run.Budget(None, 0.0)
        self.route, self.items, self.turn_starts = "chat", [], []
        self.usage = {"api_calls": 0, "input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "cost_usd": 0.0,
                      "latency_s": 0.0}
        self.n = 0
        self.compaction = (desk_run.KEEP_TURNS, desk_run.COMPACT_CHARS)
        self.prompt_target = self.context = self.max_out = None

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
    base = dict(pack=None, fixture=None, tasks=None, tasks_file=None, limit=None, layer=None, policy="model",
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


def test_small_context_compaction_and_overflow(tmp_path):
    a = _args(tmp_path, preset="qwen", base_url="http://127.0.0.1:9/v1")
    agent = desk_run.ModelAgent(a, desk_run.MODELS["qwen"], 0.0, "sys", [])
    for t in range(8):
        agent.user("wake " + "x" * 2000)
        for i in range(10 if t < 7 else 2):
            agent.items.append({"role": "assistant", "content": "", "tool_calls": []})
            agent.result(f"c{t}{i}", "y" * 3000)
    before = agent.est_tokens()
    agent.compact()
    assert before > 24_000 > agent.est_tokens()
    assert agent.out_tokens() <= 32_768 - agent.est_tokens()

    calls = {"n": 0}

    def fail(log, worst):
        calls["n"] += 1
        raise desk_run.openai.BadRequestError("maximum context length is 32768 tokens", response=_Resp(), body=None)

    agent._step = fail
    with pytest.raises(desk_run.ContextOverflow):
        agent.step(lambda r: None)
    assert calls["n"] == 2 and agent.usage["context_errors"] == 2


class _Resp:
    status_code = 400
    headers = {}
    request = None


def test_compaction_never_elides_unread_and_keeps_submission_summaries(tmp_path):
    a = _args(tmp_path, preset="qwen", base_url="http://127.0.0.1:9/v1")
    agent = desk_run.ModelAgent(a, desk_run.MODELS["qwen"], 0.0, "sys", [])
    for t in range(6):
        agent.user("wake " + "x" * 3000)
        calls = [{"id": f"r{t}{i}", "type": "function", "function": {"name": "get_prices", "arguments": "{}"}}
                 for i in range(8)]
        calls.append({"id": f"s{t}", "type": "function", "function": {"name": "submit_dam_offers", "arguments": "{}"}})
        agent.items.append({"role": "assistant", "content": "", "tool_calls": calls})
        for c in calls[:-1]:
            agent.result(c["id"], "y" * 4000)
        agent.result(f"s{t}", '{"now":"x","accepted_hours":"HE01-HE12","rejected":[{"hours":"HE13","code":"EBOC-02"}]}')
    agent.compact()
    tools = [m for m in agent.items if m.get("role") == "tool"]
    assert all(m["content"] != desk_run.ELIDED for m in tools[-9:])
    subs = [m["content"] for m in tools if m["tool_call_id"].startswith("s")]
    assert all("EBOC-02" in c for c in subs)
    assert any(m["content"] == desk_run.ELIDED for m in tools)
