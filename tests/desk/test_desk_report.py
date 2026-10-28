import gzip
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
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
    assert sol["valid_share"] == 1.0 and 0.2 <= sol["R"]["mean"] <= 1.0
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
    assert "| floored |" in readme and isinstance(sol["floored"], int)


def test_grades_rows_reproduce_summary(tmp_path, monkeypatch):
    seeds = [("2026-02-14", 1), ("2026-02-15", 2), ("2026-02-16", 3)]
    for p in ("anchor", "scripted", "idle"):
        _run(tmp_path / p, p, seeds)
    out = tmp_path / "report"
    runs = [x for p in ("anchor", "scripted", "idle") for x in ("--run", f"{p}={tmp_path / p}")]
    monkeypatch.setattr(sys, "argv", ["desk_report.py", "--layer", "v2", "--pack", "fixtures", "--no-copy", *runs,
                                      "--out", str(out)])
    desk_report.main()
    s = json.loads((out / "summary.json").read_text())
    rows = [json.loads(x) for x in gzip.open(out / "grades.jsonl.gz", "rt")]
    assert len(rows) == 9 and {r["model"] for r in rows} == set(s["models"])
    for name, m in s["models"].items():
        mine = [r for r in rows if r["model"] == name]
        caps = [r["capture"] for r in mine if r["capture"] is not None]
        assert np.mean([r["reward"] for r in mine]) == pytest.approx(m["R"]["mean"], abs=1e-4)
        assert np.mean(caps) == pytest.approx(m["C"]["mean"], abs=1e-4)
        assert np.mean([r["p"] for r in mine]) == pytest.approx(m["P"]["mean"], abs=1e-2)
        assert sum(r["floored"] for r in mine) == m["floored"]
        assert all(r["episode"] == f"episodes/{name}/{r['task_id']}.{r['tag']}.json.gz" for r in mine)
        assert all(sum(r["lines"].values()) == pytest.approx(r["p"], abs=0.05) for r in mine)
