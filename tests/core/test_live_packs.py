import datetime as dt
import gzip
import json
import re
from pathlib import Path

import pytest

from gridsim_core import live, live_prompt
from gridsim_core.task import battery_of

DATA = Path(__file__).resolve().parents[2] / "data"
FIX = DATA / "fixtures-live" / "tasks.jsonl.gz"
PACKS = ("gridsim-live-train", "gridsim-live-eval", "gridsim-live-test-2025", "gridsim-live-rtcb",
         "gridsim-live-showcase")
SHOWCASE = {"2023-09-06", "2021-02-15", "2022-12-23", "2024-01-16", "2023-08-20", "2026-01-26"}


def load(path: Path) -> list[dict]:
    with gzip.open(path, "rt") as f:
        return [json.loads(line) for line in f]


FIXTURES = load(FIX)


def drive(task: dict, tier: str, policy) -> live.Session:
    s = live.Session(task, tier)
    while not s.done:
        policy(s)
        out = json.loads(s.call("advance"))
        if "watch" in out:
            s.deliver_watch_notices()
    return s


def test_fixtures_cover_the_cases():
    assert len(FIXTURES) == 20
    assert {t["battery"]["archetype"][:2] for t in FIXTURES} == {"1h", "2h", "4h"}
    assert {t["split"] for t in FIXTURES} >= {"eval_2024", "test_2025", "rtcb"}
    assert sum(t["tags"]["blind_eval"] for t in FIXTURES) >= 4
    assert any(t["battery"]["s_end_min"] > t["battery"]["s0"] for t in FIXTURES)
    assert any(t["tags"]["notice_day"] for t in FIXTURES)
    assert any(n.get("derate_mw") for t in FIXTURES for n in t["notices"])
    assert all(t["battery"]["k_dis"] == 4 and t["battery"]["q_15"] == t["battery"]["p_dis_mw"] / 16 for t in FIXTURES)


@pytest.mark.parametrize("task", FIXTURES, ids=[t["task_id"] for t in FIXTURES])
def test_stored_references_recompute(task):
    tiers = tuple(k for k, v in task["refs"]["roll"].items() if v)
    r = live.references(task, tiers)
    for k in ("p_idle", "p_naive", "p_hind", "p_hind_da", "p_hind_rt", "p_lp"):
        assert r[k] == pytest.approx(task["refs"][k], abs=1e-6), k
    for tier in tiers:
        assert r["roll"][tier]["p_roll"] == pytest.approx(task["refs"]["roll"][tier]["p_roll"], abs=1e-6)
        assert r["roll"][tier]["executed"] == task["refs"]["roll"][tier]["executed"]
        assert task["refs"]["p_hind"] >= task["refs"]["roll"][tier]["p_roll"] - 1e-6
    assert task["refs"]["p_hind"] >= task["refs"]["p_naive"] - 1e-6
    assert task["refs"]["p_hind"] <= task["refs"]["p_lp"] + 1e-5
    assert r["notices_sha"] == task["notices_sha"] == live.notices_sha(task["notices"])


@pytest.mark.parametrize("task", FIXTURES[::3] + FIXTURES[-2:], ids=lambda t: t["task_id"])
def test_policies_through_call_reproduce_the_references(task):
    naive = task["refs"]["naive"]["da"]
    s = drive(task, "foresight", lambda s: s.call("commit_da", {"position": naive}) if s.watch == 0 else None)
    assert s.grade()["profit_usd"] == pytest.approx(task["refs"]["p_naive"], abs=1e-6)
    assert s.grade()["naive_reward"] == task["refs"]["roll"]["foresight"]["naive_reward"]
    s = drive(task, "foresight", live.roll_policy())
    g = s.grade()
    assert g["profit_usd"] == pytest.approx(task["refs"]["roll"]["foresight"]["p_roll"], abs=1e-6)
    assert g["reward"] == 1.0 and s.audit()["ok"], s.audit()
    ep = s.episode(path="ref")
    assert ep["references"]["p_roll"] == task["refs"]["roll"]["foresight"]["p_roll"]
    assert live.replay(task, "foresight", None, s.transcript)["ok"]


def test_synthetic_notice_and_derate_fixtures():
    notice = next(t for t in FIXTURES if t["task_id"].endswith("-notice"))
    ws = live.schedule(notice)
    assert [w.minute for w in ws] == [-600, 0, 360, 720, 870, 1080]
    assert [n.event_id for n in ws[0].notices] == ["fixture-board-1"]
    assert live.triggers(ws)[3]["actions"][0]["args"]["event_id"] == "fixture-appeal-1"
    derate = next(t for t in FIXTURES if t["task_id"].endswith("-derate"))
    s = drive(derate, "foresight", live.roll_policy())
    assert s.limits and s.limits[0]["from"] == "17:00" and s.audit()["ok"]
    sit = json.loads(s.call("get_situation"))
    assert sit["day_over"] and sit["notices"][0]["event_id"] == "fixture-derate-1"


def test_packs_manifests_and_holdouts():
    seen = {}
    for name in PACKS:
        tasks = load(DATA / name / "tasks.jsonl.gz")
        m = json.loads((DATA / name / "manifest.json").read_text())
        assert m["count"] == len(tasks) > 0 and len({t["task_id"] for t in tasks}) == len(tasks)
        seen[name] = tasks
    near = {(dt.date.fromisoformat(d) + dt.timedelta(days=k)).isoformat() for d in SHOWCASE for k in range(-3, 4)}
    for name in PACKS[:4]:
        assert not near & {t["date"] for t in seen[name]}
    assert {t["date"] for t in seen["gridsim-live-showcase"]} == SHOWCASE
    train = {t["date"] for t in seen["gridsim-live-train"]}
    assert not train & {t["date"] for t in seen["gridsim-live-eval"]}
    assert all("2019-01-01" <= d <= "2024-12-31" for d in train)
    assert all(t["date"].startswith("2024") for t in seen["gridsim-live-eval"])
    assert all("2025-01-01" <= t["date"] <= "2025-11-30" for t in seen["gridsim-live-test-2025"])
    assert all("2025-12-05" <= t["date"] <= "2026-10-17" for t in seen["gridsim-live-rtcb"])
    m = json.loads((DATA / "gridsim-live-showcase" / "manifest.json").read_text())
    assert set(m["bundles"]) == {"sep23-0906", "uri-0215", "elliott-1223", "heather-0116", "aug23-0820", "fern-0126"}


def test_prompt_is_shared_and_leaks_nothing():
    task = FIXTURES[0]
    s = live.Session(task)
    text = live_prompt.system_prompt("foresight")
    assert not re.search(r"\d+\.\d+", text) and task["settlement_point"] not in text
    assert "next full hour plus 6 hours" in live_prompt.system_prompt("freeze6h")
    assert "before seeing D's DA prices" in live_prompt.system_prompt("blind")
    sit = json.loads(s.call("get_situation"))
    sit.pop("messages")
    assert json.loads(live_prompt.situation_text(s)) == sit
    assert live_prompt.opening(s).endswith(live_prompt.situation_text(s))
    assert [f["function"]["name"] for f in live_prompt.tool_schemas()] == list(live.TOOLS)
    assert "p_hind" not in live_prompt.situation_text(s) and "refs" not in live_prompt.situation_text(s)
    m = live_prompt.messages(s)
    assert m[0]["role"] == "system" and m[1]["role"] == "user"
    assert live_prompt.watch_text(s).startswith("Watch 0 at ")
    assert battery_of(task).k_dis == 4


def test_merge_notices_attaches_and_recomputes(tmp_path):
    import argparse
    import shutil
    import sys

    sys.path.insert(0, str(DATA.parent / "scripts"))
    import build_live_pack as blp

    shutil.copytree(DATA / "fixtures-live", tmp_path / "fixtures-live")
    task = next(t for t in FIXTURES if not t["task_id"].endswith(("-notice", "-derate")))
    day = task["date"]
    iso = blp.local_iso(day, 16 * 60 + 5)
    row = {"notice_id": "OPS-test-1", "source": "ERCOT", "channel": "operations_message", "type": "conservation",
           "level": "conservation", "action": "issue", "issued_at": iso,
           "issued_at_utc": live._as_utc(iso).isoformat(), "timestamp_quality": "minute",
           "summary": "ERCOT asked the public to conserve electricity.", "text": "VERBATIM ERCOT TEXT " * 40,
           "grid_condition": True, "regions": None, "tags": []}
    arch = tmp_path / "notices"
    arch.mkdir()
    (arch / "notices.jsonl").write_text(json.dumps(row) + "\n")
    (arch / "nws_vtec.jsonl").write_text("")
    days = {(dt.date.fromisoformat(day) + dt.timedelta(days=k)).isoformat(): 1.0 for k in range(-5, 3)}
    (arch / "ops_coverage.json").write_text(json.dumps({"days": days}))
    blp.merge_notices(argparse.Namespace(merge_notices=str(arch), out=str(tmp_path), workers=2))
    merged = {t["task_id"]: t for t in load(tmp_path / "fixtures-live" / "tasks.jsonl.gz")}
    t = merged[task["task_id"]]
    assert [n["event_id"] for n in t["notices"]] == ["OPS-test-1"]
    assert t["notices"][0]["text"] == row["summary"] and "VERBATIM" not in json.dumps(merged)
    assert t["tags"]["day_kind"] == "notice" and t["tags"]["watches"] == 6
    assert t["notices_sha"] == live.notices_sha(t["notices"]) and t["refs"]["notices_sha"] == t["notices_sha"]
    assert live.stored_refs(t, "foresight") is not None
    m = json.loads((tmp_path / "fixtures-live" / "manifest.json").read_text())
    assert m["notices"]["tasks_changed"] >= 1
