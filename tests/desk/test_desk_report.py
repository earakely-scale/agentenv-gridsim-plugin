import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("matplotlib")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import desk_report  # noqa: E402
import desk_run  # noqa: E402

from gridsim_core.desk import fixtures  # noqa: E402


def _run(out: Path, policy: str, seeds) -> None:
    a = SimpleNamespace(policy=policy, layer="v2", max_turns=None)
    for d in ("episodes", "calls", "ckpt"):
        (out / d).mkdir(parents=True, exist_ok=True)
    budget = desk_run.Budget(None, 0.0)
    with open(out / "results.jsonl", "a") as f:
        for date, seed in seeds:
            task, series = fixtures.make(date, seed=seed, outage=True)
            f.write(json.dumps(desk_run.episode(task, series, a, None, out, policy, budget)) + "\n")


def test_report_on_policy_runs(tmp_path, monkeypatch):
    seeds = [("2026-02-14", 1), ("2026-02-15", 2), ("2026-02-16", 3)]
    for p in ("anchor", "scripted"):
        _run(tmp_path / p, p, seeds)
    out = tmp_path / "report"
    monkeypatch.setattr(sys, "argv", ["desk_report.py", "--layer", "v2", "--pack", "fixtures",
                                      "--run", f"sol={tmp_path / 'anchor'}", "--run", f"qwen={tmp_path / 'scripted'}",
                                      "--pilot", str(tmp_path / "anchor"), "--out", str(out)])
    desk_report.main()
    s = json.loads((out / "summary.json").read_text())
    sol, qwen = s["models"]["sol"], s["models"]["qwen"]
    assert s["n_tasks"] == 3 and s["n_days"] == 3 and sol["n"] == qwen["n"] == 3
    assert sol["R"]["mean"] == pytest.approx(1.0) and sol["valid_share"] == 1.0
    assert sol["P"]["mean"] == pytest.approx(s["references"]["anchor"]["P"]["mean"])
    assert sol["P"]["ci"][0] <= sol["P"]["mean"] <= sol["P"]["ci"][1]
    assert sum(sol["lines"].values()) == pytest.approx(sol["P"]["mean"], abs=0.05)
    gap = s["paired"]["sol-qwen"]["P"]
    assert gap["mean"] == pytest.approx(sol["P"]["mean"] - qwen["P"]["mean"], abs=0.01) and gap["ahead"] == 1.0
    assert set(s["references"]) == {"idle", "anchor", "hind", "hind_phys", "operator_replay", "operator_actual"}
    assert s["references"]["hind"]["C"]["mean"] == pytest.approx(1.0)
    assert "sol-operator_replay" in s["paired"] and sol["calls_by_tool"]["optimize"] > 0
    assert s["hero"]["model"] == "sol" and s["hero"]["operator_soc"]
    for f in ("p-bars", "p-bars-dark", "hero", "hero-dark"):
        assert (out / "figures" / f"{f}.png").stat().st_size > 10_000
    rows = [json.loads(x) for x in gzip.open(out / "runs" / "qwen" / "results.jsonl.gz", "rt")]
    assert len(rows) == 3 and len(list((out / "episodes" / "sol").glob("*.json.gz"))) == 3
    readme = (out / "README.md").read_text()
    assert readme.index("| model |") < readme.index("## What the numbers say") < readme.index("## Method")
    assert len(s["pilot"]) == 3
