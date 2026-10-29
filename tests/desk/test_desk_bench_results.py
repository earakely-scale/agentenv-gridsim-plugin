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
import hub_article  # noqa: E402
import hub_dataset  # noqa: E402
import hub_desk  # noqa: E402
import hub_space  # noqa: E402

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


def _episode(task: dict, p: float, trades: bool = False) -> dict:
    third = round(p / 3, 2)
    subs = [{"t": -1080, "tool": "submit_dam_offers", "day": "D0", "accepted": True, "codes": []},
            *({"t": 600 * k, "tool": "submit_rt_offers", "day": "D0", "accepted": True, "codes": []} for k in range(3))]
    return {"schema": "gridsim.desk.episode/v1", "task_id": task["task_id"], "dates": task["dates"], "budget": {
        "max_turns": 100, "calls_per_turn": 14, "max_reminders": 12}, "core_version": "desk-2.1",
        "site": {"card": task["site"]["card"]}, "policy": {}, "turns": [], "wakes": [],
        "submissions": subs if trades else [],
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
                    ep = _episode(task, p, trades=h == "claude-code" or tid.endswith("S01"))
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
    first = "claude-code-desk-v4-2026-01-23-S01-0"
    shutil.copytree(root / first, root / "copies" / first)
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
                "--framework", "0.9.1378", "--redact", "ZZSECRET", "--prereg", "docs/prereg/v4-bench.md",
                "--deviations-ref", "desk-v4-bench-results", "--deviation", "Infrastructure retries ({retries})."]
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
                                "windows_missing": 1, "missing_reasons": {"sandbox or tunnel": 1},
                                "failure_kinds": {"sandbox or tunnel": 4}}
    assert qwen["attempts"]["extra"] == 1 and qwen["attempts"]["failed"] == 2 and qwen["n"] == 32
    roles = {(x["model"], x["task_id"], x["attempt"]): x["role"] for x in s["attempts"]}
    assert roles[("qwen", "desk-v4-2026-05-08-S03", 1)] == "scored"
    assert roles[("qwen", "desk-v4-2026-05-08-S03", 2)] == "extra"
    assert roles[("qwen", "desk-v4-2026-03-16-S01", 3)] == "scored"
    missing = next(g for g in grades if g["status"] == "missing")
    assert missing["retries"] == 3 and "capture" not in missing and missing["usd_all_attempts"] == 1.5
    assert not s["regraded"]["diffs"]
    assert len(list((out / "episodes" / "opus").glob("*.json.gz"))) == 31
    assert s["skipped"] == {"a turn cap": 1, "Codex as installed": 1, "another pack": 1,
                            "a copy of a run already read": 1} and "luna" not in s["models"]
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
    assert s["lead_rule"]["exposed"] == ["opus"] and set(s["halves_differ"]) <= {"opus"}
    assert s["lead_split"] == ("post_cutoff" if s["halves_differ"] else "all")
    assert s["order_by_C"] == ["opus", "qwen"] and s["hero"]["model"] == "opus"
    hero = next(g for g in grades if g["model"] == "opus" and g["task_id"] == s["hero"]["task_id"])
    assert hero["split"] == "post_cutoff" and "real-time re-offers 3" in s["hero"]["why"]


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
    assert hub_dataset.FAKE in card and "Lead GIF slot" in card and s["lead_rule"]["text"] in card
    assert s["text"]["halves"] in section and s["text"]["reliability"] in section
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
    assert f"({dbr.REPO}/blob/desk-v4-bench-results/docs/prereg/v4-bench.md#deviations)" in section


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


def test_article_states_the_bench_as_the_card_does(bench):
    _, _, fake, fake_grades = bench
    d = json.loads((ROOT / "results/overview/desk.json").read_text())
    with pytest.raises(SystemExit, match="fake"):
        hub_article.bench(fake, fake_grades, d, hub_dataset)
    folder = ROOT / "results/desk-v4-bench"
    s, grades = hub_dataset.bench_read(folder)
    f = hub_article.bench(s, grades, d, hub_dataset)
    block = hub_dataset.bench_block(s, grades, d)
    assert f["pitch"] == hub_dataset.bench_pitch(s).strip("*") and "**" not in f["pitch"]
    for b in (*f["say"].values(), *f["how"].values(), *f["limits"].values()):
        assert f"- **{b['head']}** {b['text']}" in block
    t = f["cap"]["table"]
    assert f"<small>{f['cap']['splits']}</small>" in block
    assert f"<small>{t['before']}[{t['label']}]({t['url']}){t['after']}</small>" in block
    assert t["url"] == f["links"]["deviations"] and f["tag"] in t["url"]
    assert [f"{x['head']}: {x['text']}" for x in (f["route"], f["late"], f["errors"])] == [
        x for x in s["deviations"] if x.startswith(("Route C", "Gemini 4 Argon:", "Provider HTTP 400s"))]
    assert f["ahead"] == f"GPT-6.1 Sol {f['m']['sol']['op']} and Claude Opus 5.5 {f['m']['opus']['op']}"
    for k, m in s["models"].items():
        got = f["m"][k]
        for name, scope in (("C", "all"), ("pre", "pre_cutoff"), ("post", "post_cutoff")):
            b = m[scope]["C"]
            assert (got[name], got[f"{name}ci"]) == (f"{_pc(b['mean'])}%", f"[{_pc(b['ci'][0])}, {_pc(b['ci'][1])}]")
        assert got["usd"] == f"${m['cost']['usd_per_window']:,.2f}"
        assert int(got["valid"]) + int(got["invalid"]) == m["n"] == 32
        assert (got["harness"], got["version"], got["setting"]) == (m["harness"], m["harness_version"], m["setting"])
    assert (f["m"]["qwen"]["valid"], f["m"]["qwen"]["temperature"], f["m"]["qwen"]["top_k"]) == ("25", "0.6", "20")
    hub_article.check_prose(hub_article.facts(d) | {"bench": f})
    hub_article.check_order(s)
    b = hub_article.hero(folder, s, grades, hub_dataset)
    lead = next(g for g in grades if g["task_id"] == s["hero"]["task_id"] and g["model"] == s["hero"]["model"])
    assert b["days"] == lead["dates"] and b["model"] == "GPT-6.1 Sol in Codex CLI" and len(b["sites"]) == 4
    assert b["replay"]["url"] == f["lead"]["replay"]["sol"] == hub_dataset.bench_replay("sol", lead["task_id"])
    assert set(f["lead"]["replay"]) == set(s["models"]) and f["lead"]["C"] == f"{_pc(lead['capture'])}%"
    gif = hub_dataset.bench_gif(s, grades, True)
    where = f"{f['lead']['site']} ({f['lead']['region']}, {f['lead']['battery']})"
    assert where in gif and all(f"[{o['name']}]({o['url']})" in gif for o in f["lead"]["others"])
    assert {o["key"] for o in f["lead"]["others"]} == set(s["models"]) - {"sol", *hub_dataset.NOT_YET_IN_VIEWER}
    for site in b["sites"]:
        assert (len(site["rt"]), len(site["soc"]), len(site["mw"])) == (288, 289, 288)
        assert all(0 <= t < 3 * 1440 for t in site["wakes"]) and site["wakes"]


def _route_c(root: Path) -> None:
    tasks = {t["task_id"]: t for t in load_tasks(PACK)}
    t0 = dt.datetime(2026, 10, 29, 7, tzinfo=dt.UTC)
    plan = {"qwen": ("opencode-qwen", "g5.xlarge", [("desk-v4-2026-07-04-S01", 0, 1000, "ok"),
                                                   ("desk-v4-2026-07-04-S02", 500, 1500, "ok")]),
            "sol": ("codex-sol", "m7i.16xlarge", [("desk-v4-2026-07-04-S01", 0, 300, "infra"),
                                                  ("desk-v4-2026-07-04-S01", 400, 900, "ok"),
                                                  ("desk-v4-2026-07-04-S02", 0, 700, "agent")])}
    for key, (harness, kind, runs) in plan.items():
        bench = root / key / "box1" / "bench"
        (bench / "episodes").mkdir(parents=True)
        (root / key / "assignment.json").write_text(json.dumps({"pack": PACK}))
        rows = []
        for k, (tid, a, b, cls) in enumerate(runs):
            unit = f"bench-{key}-{tid}-a{k}"
            row = {"task_id": tid, "attempt": k + 1, "unit": unit, "class": cls, "why": "" if cls == "ok" else
                   "setup step deploy did not complete", "t_start": (t0 + dt.timedelta(seconds=a)).isoformat(),
                   "t_end": (t0 + dt.timedelta(seconds=b)).isoformat(), "wall_s": float(b - a), "box": "box1",
                   "instance_type": kind, "harness": harness, "status": "completed" if cls == "ok" else "failed",
                   "usage": {"tokens": {"input": 10}, "cost_usd_list_price": 0.0 if key == "qwen" else 1.25}}
            if key == "sol" and cls != "agent":
                row["proxy_cost_usd"] = 0.4 if cls == "infra" else 1.3
            if key == "sol":
                row["agent_version"] = "codex 0.147.0 (src-0d9e; agentenv-framework 0.9.1383)"
            rows.append(row)
            if cls == "ok":
                ep = _episode(tasks[tid], round(tasks[tid]["refs"]["p_idle"] + 1000, 2))
                g = desk_report.regrade({"valid": True}, ep, tasks[tid]["refs"])
                run = bench / "runs" / unit
                run.mkdir(parents=True)
                (run / "report.json").write_text(json.dumps({
                    "status": "completed", "wall_s": float(b - a), "episode": ep, "usage": row["usage"],
                    "grade": {x: g[x] for x in ("reward", "capture", "capture_phys", "p", "valid")}}))
        (bench / "attempts.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (root / key / "attempts.jsonl").write_text((bench / "attempts.jsonl").read_text())


def test_route_c_runs_box_shares_and_final_failures(tmp_path):
    _route_c(tmp_path / "runs")
    out = tmp_path / "out"
    argv = sys.argv
    sys.argv = ["desk_bench_results.py", "--runs", str(tmp_path / "runs"), "--out", str(out), "--no-figures",
                "--deferred", "Gemini 4 Argon (Gemini CLI): deferred; projected $15–20 per window.",
                "--prereg", "docs/prereg/v4-bench.md", "--deviations-ref", "desk-v4-bench-results"]
    try:
        dbr.main()
    finally:
        sys.argv = argv
    s = json.loads((out / "summary.json").read_text())
    qwen, sol = s["models"]["qwen"], s["models"]["sol"]
    assert s["run"]["route"] == "ec2" and not s["skipped"] and s["deferred"] and set(s["models"]) == {"sol", "qwen"}
    assert qwen["cost"]["gpu"]["basis"] == "ec2" and qwen["cost"]["gpu"]["gpu_hours"] == pytest.approx(1500 / 3600,
                                                                                                         abs=1e-3)
    assert qwen["cost"]["usd_per_window"] == pytest.approx(750 / 3600 * 1.006, abs=1e-4) and qwen["n"] == 2
    assert sol["n"] == 1 and sol["cost"]["usd_per_window"] == 1.25 and sol["cost"]["usd_all_attempts"] == 2.9
    assert s["run"]["metered_attempts"] == 1 and s["text"]["metered"] == dbr.METERED
    assert (sol["harness_version"], sol["framework"], qwen["framework"]) == ("0.147.0", "0.9.1383", None)
    assert sol["ran"] == {"from": "2026-10-29T07:00:00+00:00", "to": "2026-10-29T07:15:00+00:00"}
    assert s["order_by_C"] == ["qwen", "sol"] and list(s["paired"]) == ["qwen-sol", "qwen-operator_replay",
                                                                         "sol-operator_replay"]
    agent = "agent-side failure, final, no grade possible"
    assert sol["attempts"]["missing_reasons"] == {agent: 1, "no attempt": 30}
    assert sol["attempts"]["failure_kinds"] == {"infrastructure": 1, agent: 1}
    assert s["deviations"] == ["Agent-side failures with no grade (GPT-6.1 Sol 1): the harness failed during play, so "
                               "the verifier never ran and these windows could not be scored as settled; they are "
                               "reported missing and not imputed."]
    assert s["lead_rule"]["exposed"] == ["sol"] and s["lead_rule"]["unexposed"] == ["qwen"]
    readme = (out / "README.md").read_text()
    assert readme.index("| **Qwen3-4B** |") < readme.index("| **GPT-6.1 Sol** |")
    assert "Gemini 4 Argon (Gemini CLI): deferred" in readme and s["text"]["halves"] in readme and dbr.METERED in readme
    assert f"({dbr.REPO}/blob/desk-v4-bench-results/docs/prereg/v4-bench.md#deviations)" in readme
    assert ("Qwen3-4B, no attempt ×30; GPT-6.1 Sol, no attempt ×30, agent-side failure, final, no grade possible ×1."
            in s["text"]["reliability"])


def test_space_keys_each_bench_run_with_its_harness_run(tmp_path, monkeypatch):
    s, grades = hub_dataset.bench_read(hub_space.BENCH)
    hero = s["hero"]
    rows = [g for g in grades if g["task_id"] in (hero["task_id"], "desk-v4-2026-03-16-S01")]
    monkeypatch.setattr(hub_space, "task_view", lambda key, task, raw, ser: (
        {"task": task["task_id"], "version": key}, {"site": task["site"]["site_id"]}))
    (tmp_path / "ep" / "bench").mkdir(parents=True)
    (tmp_path / "task").mkdir()
    cat = {"tasks": {}, "episodes": {}}
    v = hub_space.bench(s, rows, tmp_path, cat, hub_dataset)
    assert set(cat["episodes"]) == {f"bench/{g['task_id']}.{g['model']}" for g in rows}
    assert v["lead"] == f"bench/{hero['task_id']}.{hero['model']}" and v["models"] == s["order_by_C"]
    assert {k: r["label"] for k, r in v["roster"].items()} == {
        k: f"{m['name']} · {m['harness']} · {m['setting']}" for k, m in s["models"].items()}
    assert [x["label"] for x in v["splits"].values()] == ["Jan–May 2026", "Jul–Aug 2026"] and v["days_per_task"] == 3
    for g in rows:
        key = f"bench/{g['task_id']}.{g['model']}"
        view = json.loads((tmp_path / "ep" / f"{key}.json").read_text())
        e = cat["episodes"][key]
        assert (e["C"], e["R"], e["P"], e["valid"], e["usd"], e["own"]) == (
            g["capture"], g["reward"], g["p"], g["valid"], g["usd"], g["own_tool_calls"])
        assert (e["split"], e["front"], view["version"], view["run"]["own"]) == (
            g["split"], g["front"], "bench", g["own_tools"])
        assert all(len(t["q"]) <= 901 and (len(t["q"]) < 901 or t["q"].endswith("…")) for t in view["turns"])
    assert cat["episodes"]["bench/desk-v4-2026-03-16-S01.qwen"]["own"] > 0


def test_space_keeps_one_task_view_and_refuses_a_different_one(tmp_path):
    (tmp_path / "task").mkdir()
    cat, view = {"tasks": {}}, {"task": "desk-v4-2026-01-23-S01", "version": "v4", "prices": [1.0]}
    hub_space.put_task(tmp_path, cat, view, {"m": 1})
    hub_space.put_task(tmp_path, cat, view | {"version": "bench"}, {"m": 2})
    assert json.loads((tmp_path / "task" / f"{view['task']}.json").read_text()) == view
    assert cat["tasks"] == {view["task"]: {"m": 1}}
    with pytest.raises(SystemExit, match="task views differ"):
        hub_space.put_task(tmp_path, cat, view | {"version": "bench", "prices": [2.0]}, {})


def test_space_page_and_card_lead_with_the_benchmark():
    s, grades = hub_dataset.bench_read(hub_space.BENCH)
    desk = json.loads((ROOT / "results/overview/desk.json").read_text())
    page = hub_space.bench_page(s, grades, desk, hub_dataset)
    assert "attempts" not in page and page["card"]["bullets"] == hub_dataset.bench_bullets(s)
    cap, block = page["card"]["captions"], hub_dataset.bench_block(s, grades, desk)
    assert [cap[k][:12] for k in ("splits", "table")] == ["C × 100: the", "C, hindsight"]
    assert block.index("/figures/splits.svg") < block.index(cap["splits"]) < block.index("| Model |") < block.index(
        cap["table"]) and "cost-vs-score" not in block
    assert not any("Quick start below" in x for x in page["card"]["how"])
    links = page["links"]
    assert links["prereg"] == f"{dbr.REPO}/blob/desk-v4-bench-run1/docs/prereg/v4-bench.md"
    assert links["deviations"] == f"{dbr.REPO}/blob/desk-v4-bench-results-2/docs/prereg/v4-bench.md#deviations"
    assert links["folder"] == f"{dbr.REPO}/tree/desk-v4-bench-results-2/results/desk-v4-bench"
    assert (f"Gemini 4 Argon ran after the others, on agentenv-framework 0.9.1383; see the [deviations]"
            f"({links['deviations']}).</small>") in block
    text = hub_space.readme({"versions": [], "episodes": {}}, desk, s, grades, hub_dataset)
    lead = f"{hub_space.APP}/index.html?v=bench&m={s['hero']['model']}&task={s['hero']['task_id']}"
    assert text.index(f"[Replay the lead run]({lead})") < text.index("## The development ladder")
    assert "against cost" not in text
    for m in s["models"].values():
        assert f"| **{m['name']}** | {m['harness']} · {m['setting']} | {_pc(m['all']['C']['mean'])}% [" in text
    gif = hub_dataset.bench_gif(s, grades, True)
    assert gif.startswith(f'<a href="{lead}"><img src="{hub_dataset.BENCH_GIF}"')
    assert f"[Replay it in 3D]({lead})" in gif
    for k, m in s["models"].items():
        assert (f"[{m['name']}]({hub_space.APP}/index.html?v=bench&m={k}&task={s['hero']['task_id']})" in gif) == (
            k != s["hero"]["model"] and k not in hub_dataset.NOT_YET_IN_VIEWER)


def test_space_scan_reads_gzip_and_refuses_what_it_cannot_read(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "catalog.json").write_text('{"episodes": {}}')
    hub_space.scan(tmp_path)
    real = next(x for x in hub_desk.names(ROOT) if len(x) > 4)
    for body, why in ((f'{{"name": "{real}"}}', "real site or operator"), ('{"host": "ip-10-0-1-2"}', "or host")):
        (tmp_path / "data" / "ep.json.gz").write_bytes(gzip.compress(body.encode()))
        with pytest.raises(SystemExit, match=why):
            hub_space.scan(tmp_path)
    (tmp_path / "data" / "ep.json.gz").unlink()
    (tmp_path / "data" / "ep.bin").write_bytes(b"\0")
    with pytest.raises(SystemExit, match="no scan reads a .bin file"):
        hub_space.scan(tmp_path)

