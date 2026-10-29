import datetime as dt
import gzip
import json
import re
import shutil
import sys
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("matplotlib")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import desk_bench_results as dbr  # noqa: E402
import desk_report  # noqa: E402
import hub_dataset  # noqa: E402
import hub_desk  # noqa: E402

from gridsim_core.desk.data import load_tasks  # noqa: E402

PACK = "desk-v4-bench"
LEVEL = {"claude-code": 0.3, "opencode-qwen": 0.02}
FAILS = {("claude-code", "desk-v4-2026-07-23-S02"): 1, ("claude-code", "desk-v4-2026-08-26-S01"): 3,
         ("opencode-qwen", "desk-v4-2026-03-16-S01"): 2}
EXTRA = {("opencode-qwen", "desk-v4-2026-05-08-S03")}


def test_boot_is_desk_reports_block_bootstrap():
    rng = np.random.default_rng(3)
    x, blocks = rng.normal(0.2, 0.1, 32), np.repeat([f"f{i}" for i in range(8)], 4)
    ours, theirs = dbr.boot(x, blocks), desk_report.boot(x, blocks)
    assert ours["mean"] == theirs["mean"] and ours["ci"] == theirs["ci"] and ours["fronts"] == theirs["days"] == 8
    assert dbr.boot([], [])["mean"] is None


def test_split_ci_draws_only_its_own_fronts():
    rng = np.random.default_rng(4)
    x, blocks = rng.normal(0.2, 0.1, 32), np.repeat([f"f{i}" for i in range(8)], 4)
    half = dbr.boot(x[:16], blocks[:16])
    assert half["fronts"] == 4 and half["n"] == 16
    assert half["mean"] == round(float(x[:16].mean()), 4)
    assert half["ci"] != dbr.boot(x, blocks)["ci"]


def test_split_gap_is_post_minus_pre_with_a_stratified_ci():
    blocks = np.repeat([f"f{i}" for i in range(8)], 4)
    splits = np.array(["pre_cutoff"] * 16 + ["post_cutoff"] * 16)
    flat = dbr.split_gap(np.r_[np.full(16, 0.1), np.full(16, 0.3)], blocks, splits)
    assert flat["mean"] == pytest.approx(0.2) and flat["ci"] == pytest.approx([0.2, 0.2])
    noisy = np.r_[np.full(16, 0.1), np.full(16, 0.3)] + np.repeat(np.random.default_rng(5).normal(0, 0.05, 8), 4)
    g = dbr.split_gap(noisy, blocks, splits)
    assert g["ci"][0] < g["mean"] < g["ci"][1] and g["ci"][0] > 0
    assert dbr.split_gap(noisy[:16], blocks[:16], splits[:16])["mean"] is None


def test_paired_counts_fronts_ahead():
    blocks = np.repeat(["a", "b"], 2)
    b = dbr.paired([1.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 1.0], blocks)
    assert b["mean"] == 0.0 and b["ahead"] == 0.5 and b["fronts_ahead"] == 1


def _episode(task: dict, p: float) -> dict:
    third = round(p / 3, 2)
    return {"schema": "gridsim.desk.episode/v1", "task_id": task["task_id"], "dates": task["dates"], "budget": {
        "max_turns": 100, "calls_per_turn": 14, "max_reminders": 12}, "core_version": "desk-2.1",
        "site": {"card": task["site"]["card"]}, "policy": {}, "turns": [], "wakes": [], "submissions": [],
        "rt": {d: {"lmp": [20.0, 60.0]} for d in task["dates"]},
        "statement": {"total": p, "days": {d: {"lines": {"dam_energy": third}, "total": third} for d in task["dates"]}}}


def _runs(root: Path) -> None:
    rng = np.random.default_rng(11)
    t0 = dt.datetime(2026, 10, 29, 9, tzinfo=dt.UTC)
    for h, level in LEVEL.items():
        for i, task in enumerate(load_tasks(PACK)):
            tid, refs = task["task_id"], task["refs"]
            fails = FAILS.get((h, tid), 0)
            plan = ["fail"] * fails + ([] if fails >= 3 else ["ok"]) + (["ok"] if (h, tid) in EXTRA else [])
            start = t0 + dt.timedelta(minutes=10 * i)
            for k, kind in enumerate(plan):
                run = root / f"{h}-{tid}-{k}"
                run.mkdir(parents=True)
                wall = 600.0
                meta = {"harness": h, "task": tid, "pack": PACK, "fake": True, "started": start.isoformat(),
                        "wall_s": wall}
                rep = {"status": "failed", "error": "The agent on sandbox sb-x stopped answering", "wall_s": wall,
                       "usage": {"tokens": {"input": 1000, "output": 10}, "cost_usd_list_price": 0.5}}
                if kind == "ok":
                    c = level + float(rng.normal(0, 0.05))
                    p = round(refs["p_idle"] + c * (refs["p_hind"] - refs["p_idle"]), 2)
                    ep = _episode(task, p)
                    if (h, i) == ("claude-code", 0):
                        ep["turns"] = [{"turn": 0, "t": 0, "text": "noted ZZSECRET twice: ZZSECRET", "calls": []}]
                    g = desk_report.regrade({"valid": True}, ep, refs)
                    rep = {"status": "completed", "wall_s": wall, "episode": ep,
                           "grade": {k2: g[k2] for k2 in ("reward", "capture", "capture_phys", "p", "valid")},
                           "usage": {"tokens": {"input": 2000, "cached": 50000, "output": 300},
                                     "cost_usd_list_price": 2.0},
                           "harness": {"turns": 20, "desk_calls": 60, "builtin_calls": 2,
                                       "builtin_by_tool": {"Bash": 1, "TodoWrite": 1}, "session_ids": ["s"]},
                           "wakes": {"env_episode": 20, "agent_reminders_set": 3}}
                (run / "meta.json").write_text(json.dumps(meta))
                (run / "report.json").write_text(json.dumps(rep))
                start += dt.timedelta(seconds=wall + 30)
    for k, extra in enumerate(({"max_turns": 4}, {"codex_as_installed": True}, {"pack": "desk-v4-pilot"})):
        run = root / f"check-{k}"
        run.mkdir(parents=True)
        (run / "meta.json").write_text(json.dumps({"harness": "codex-luna", "task": "desk-v4-2026-07-04-S01",
                                                   "pack": PACK, "fake": True, "started": t0.isoformat()} | extra))


@pytest.fixture(scope="module")
def bench(tmp_path_factory):
    root = tmp_path_factory.mktemp("bench")
    _runs(root / "runs")
    out = root / "results" / "desk-v4-bench"
    argv = sys.argv
    sys.argv = ["desk_bench_results.py", "--runs", str(root / "runs"), "--out", str(out), "--no-figures",
                "--framework", "0.9.1378", "--redact", "ZZSECRET"]
    try:
        dbr.main()
    finally:
        sys.argv = argv
    s = json.loads((out / "summary.json").read_text())
    with gzip.open(out / "grades.jsonl.gz", "rt") as f:
        grades = [json.loads(x) for x in f]
    return root, out, s, grades


def test_results_score_first_graded_attempt_and_never_impute(bench):
    _, out, s, grades = bench
    opus, qwen = s["models"]["opus"], s["models"]["qwen"]
    assert s["fake"] and s["n_windows"] == 32 and s["n_fronts"] == 8
    assert s["block_alias"] == {"2026-04-03": "2026-04-17"}
    assert len(grades) == 64 and opus["n"] == 31 and opus["missing"] == ["desk-v4-2026-08-26-S01"]
    assert opus["attempts"] == {"total": 35, "scored": 31, "failed": 4, "extra": 0, "windows_retried": 2,
                                "windows_missing": 1, "failure_kinds": {"sandbox or tunnel": 4}}
    assert qwen["attempts"]["extra"] == 1 and qwen["attempts"]["failed"] == 2 and qwen["n"] == 32
    roles = {(x["model"], x["task_id"], x["attempt"]): x["role"] for x in s["attempts"]}
    assert roles[("qwen", "desk-v4-2026-05-08-S03", 1)] == "scored"
    assert roles[("qwen", "desk-v4-2026-05-08-S03", 2)] == "extra"
    assert roles[("qwen", "desk-v4-2026-03-16-S01", 3)] == "scored"
    missing = next(g for g in grades if g["status"] == "missing")
    assert missing["retries"] == 3 and "capture" not in missing and missing["usd_all_attempts"] == 1.5
    assert not s["regraded"]["diffs"]
    assert len(list((out / "episodes" / "opus").glob("*.json.gz"))) == 31
    assert s["skipped"] == {"a turn cap": 1, "Codex as installed": 1, "another pack": 1} and "luna" not in s["models"]
    assert s["redactions"] == {"ZZSECRET": 2}
    first = gzip.decompress((out / grades[0]["episode"]).read_bytes()).decode()
    assert "ZZSECRET" not in first and "<redacted>" in first and '"name": "Claude Opus 5.5"' in first


def test_results_scopes_and_splits(bench):
    _, _, s, grades = bench
    for k, m in s["models"].items():
        rows = [g for g in grades if g["model"] == k and g["status"] == "scored"]
        assert m["all"]["C"]["mean"] == round(float(np.mean([g["capture"] for g in rows])), 4)
        assert m["all"]["C"]["fronts"] == 8
        for sp in ("pre_cutoff", "post_cutoff"):
            part = [g for g in rows if g["split"] == sp]
            assert m[sp]["n"] == len(part) and m[sp]["C"]["fronts"] == 4
            assert m[sp]["C"]["mean"] == round(float(np.mean([g["capture"] for g in part])), 4)
            assert m[sp]["C"]["ci"][0] <= m[sp]["C"]["mean"] <= m[sp]["C"]["ci"][1]
        gap = m["split_gap"]["C"]
        assert gap["mean"] == pytest.approx(m["post_cutoff"]["C"]["mean"] - m["pre_cutoff"]["C"]["mean"], abs=2e-4)
    pair = s["paired"]["opus-qwen"]["all"]
    assert pair["n"] == 31 and pair["C"]["mean"] > 0.2
    assert s["references"]["hind"]["all"]["C"]["mean"] == pytest.approx(1.0)
    assert s["references"]["operator_replay"]["all"]["n"] == 32
    assert s["order_by_C"] == ["opus", "qwen"] and s["hero"]["model"] == "opus"


def test_results_cost_list_price_and_gpu_share(bench):
    _, _, s, grades = bench
    opus, qwen = s["models"]["opus"], s["models"]["qwen"]
    assert opus["cost"]["basis"] == "list_price_tokens" and opus["cost"]["usd_per_window"] == 2.0
    assert opus["cost"]["usd_all_attempts"] == pytest.approx(31 * 2.0 + 4 * 0.5)
    gpu = qwen["cost"]["gpu"]
    assert qwen["cost"]["basis"] == "gpu_time" and gpu["gpu"] == "L4" and not gpu["measured"]
    assert gpu["usd_total"] == pytest.approx(gpu["gpu_hours"] * 3600 * dbr.GPU_USD_PER_S["L4"], rel=1e-3)
    assert sum(g["usd_all_attempts"] for g in grades if g["model"] == "qwen") == pytest.approx(gpu["usd_total"],
                                                                                               abs=0.01)


def _pc(x: float) -> str:
    q = (Decimal(str(x)) * 100).quantize(Decimal("0.1"), ROUND_HALF_UP)
    return f"{'−' if q < 0 else ''}{abs(q)}"


def test_card_numbers_are_summary_json(bench, tmp_path):
    root, out, s, grades = bench
    results = tmp_path / "results"
    (results / "overview").mkdir(parents=True)
    shutil.copy(ROOT / "results/overview/desk.json", results / "overview/desk.json")
    shutil.copytree(out, results / "desk-v4-bench")
    card = hub_dataset.card_text(results)
    section = card[card.index("## The v4 benchmark"):card.index("## Earlier versions")]
    assert hub_dataset.FAKE in card and "Lead GIF slot" in card
    scopes = ("all", "pre_cutoff", "post_cutoff") if s["lead_split"] == "all" else ("post_cutoff", "all", "pre_cutoff")
    head = next(x for x in section.splitlines() if x.startswith("| Model |"))
    assert [h.split("<br>")[0].strip() for h in head.split(" | ")[1:]] == [
        "C, all 32 windows" if x == "all" else hub_dataset.bench_side(s, x) for x in scopes]
    for m in s["models"].values():
        row = next(x for x in section.splitlines() if x.startswith(f"| **{m['name']}**"))
        cells = [re.sub(r"<[^>]+>|\*", " ", c).split() for c in row.rstrip(" |").split(" | ")[1:]]
        for c, scope in zip(cells, scopes, strict=True):
            b = m[scope]["C"]
            assert c == [f"{_pc(b['mean'])}%", f"[{_pc(b['ci'][0])},", f"{_pc(b['ci'][1])}]"]
        assert f"${m['cost']['usd_per_window']:,.2f} a window" in row
        assert (f"{m['n']} of 32 windows" in row) == (m["n"] < 32)
    for k in ("operator_replay", "anchor"):
        r = s["references"][k]
        assert " | ".join(f"*{_pc(r[x]['C']['mean'])}%*" for x in scopes) in section
    gap = hub_dataset.bench_pair(s, "opus", "qwen")
    assert f"{_pc(gap['mean']).replace('−', '')} pts" in section
    assert "desk_v4_bench/pre_cutoff.parquet" in card and "default: true" in card.split("desk_leaderboard")[0]


def test_hub_checks_bench_grades_and_refuses_fake(bench, monkeypatch):
    _, out, s, grades = bench
    hub_desk.check_bench(s, grades)
    bad = [dict(g, capture=(g.get("capture") or 0) + 0.5) if g["model"] == "opus" else g for g in grades]
    with pytest.raises(hub_desk.Mismatch):
        hub_desk.check_bench(s, bad)
    with pytest.raises(SystemExit, match="FAKE"):
        hub_desk.bench_files(out, publish=True)
    files = hub_desk.bench_files(out, publish=False)
    assert {"desk_v4_bench/pre_cutoff.parquet", "desk_v4_bench/post_cutoff.parquet",
            "results/desk-v4-bench/summary.json"} <= set(files)
