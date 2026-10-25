import json

import pytest

from gridsim_core import hybrid as H
from gridsim_core import hybrid_inputs as HI
from gridsim_core.task import data_root, load_pack

FIX = data_root() / "fixtures-hybrid" / "tasks.jsonl.gz"
PACKS = ("ercot-hybrid-v3-train", "ercot-hybrid-v3-eval", "ercot-hybrid-v3-rtcb", "ercot-hybrid-v3-showcase")


@pytest.fixture(scope="module")
def fixtures():
    return load_pack(FIX)


def scripted(s: H.Session):
    s.call("get_situation")
    if s.watch == 0:
        offered = s.day.offered
        plan = {"energy": [{"from": 1, "to": 5, "mw": -25}, {"from": 18, "to": 21, "mw": 25}]}
        if "regdn" in offered:
            plan["regdn"] = [{"from": 0, "to": 6, "mw": 10}]
        if "rrs" in offered:
            plan["rrs"] = {"from": 17, "to": 20, "mw": 10}
        s.call("commit_schedule", {"plan": plan, "from_hour": 0})


def test_fixtures_cover_the_cases(fixtures):
    assert len(fixtures) == 20
    assert {t["era"] for t in fixtures} == {"A", "B", "C"}
    assert any(t["tags"]["showcase"] == "sept06-2023" for t in fixtures)
    assert any(t["tags"]["deploy_day"] for t in fixtures) and any(t["tags"]["neg_hours"] for t in fixtures)
    for t in fixtures:
        assert t["hybrid_version"] == H.HYBRID_VERSION and len(t["prices"]) == len(t["rt"]) == len(t["pv_mw"]) == 24
        assert t["refs"]["events_sha"] == H.events_sha(t) and t["refs"]["energy"] and t["refs"]["reserves"]
        assert t["flags"]["reg_drift"] == t["reg"]["source"] and len(t["reg"]["up"]) == 24
        assert t["reg"]["source"] == ("ercot" if HI.reg_series(t["date"]) else "modelled")
    assert any(str(t["site"]["flags"]["poi"]).startswith("oversized") and t["tags"]["clip_mwh"] > 0 for t in fixtures)


def test_stored_refs_reproduce(fixtures):
    for t in fixtures[:4]:
        assert H.references(t) == t["refs"]


@pytest.mark.parametrize("tier", ["energy", "reserves"])
def test_anchor_replays_its_reward_and_scripted_days_audit(fixtures, tier):
    for t in fixtures:
        anc = H.play(t, tier, H.anchor_policy(), reference=False)
        assert anc.grade()["reward"] == pytest.approx(1.0) and anc.profit() == pytest.approx(t["refs"][tier]["p_anchor"])
        s = H.play(t, tier, scripted, reference=False)
        a = s.audit()
        assert a["ok"], (t["task_id"], a["problems"])
        assert 0.0 <= s.grade()["reward"] <= 1.0
        assert len(s.watches) <= 10


def test_hero_day_has_its_deployments_and_notices(fixtures):
    hero = next(t for t in fixtures if t["tags"]["showcase"] == "sept06-2023")
    assert {d["product"] for d in hero["deployments"]} == {"rrs", "ecrs", "nspin"}
    s = H.Session(hero)
    got = [n.event_id for w in s.watches for n in w.notices]
    assert sum(e.startswith("dep-") for e in got) >= 4 and any("EEA2" in json.dumps(n) for n in hero["notices"])
    assert H.oneshot_grade(hero, hero["refs"]["reserves"]["oneshot"]["plan"])["reward"] == pytest.approx(1.0)


def test_showcase_reserves_anchor_beats_energy_only():
    t = next(t for t in load_pack("ercot-hybrid-v3-showcase") if t["tags"]["showcase"] == "aug10-2023")
    r = t["refs"]
    assert r["reserves"]["p_anchor"] > r["energy"]["p_anchor"]
    assert H.reward_value(r["energy"]["p_anchor"], r["p_idle"], r["reserves"]["p_anchor"]) < 0.97


def test_oversized_sites_clip_and_the_energy_tier_is_not_saturated():
    ts = load_pack("ercot-hybrid-v3-eval")
    big = [t for t in ts if str(t["site"]["flags"]["poi"]).startswith("oversized")]
    assert 0.3 * len(ts) <= len(big) <= 0.5 * len(ts)
    assert sum(t["tags"]["clip_mwh"] > 0 for t in big) > 0.5 * len(big)
    v2 = [t["refs"]["energy"]["baselines"]["v2_energy"]["reward"] for t in big]
    assert sum(v2) / len(v2) < 0.95


@pytest.mark.parametrize("pack", PACKS)
def test_pack_manifests(pack):
    p = data_root() / pack / "manifest.json"
    m = json.loads(p.read_text())
    assert m["pack"] == pack and m["tasks"] > 0 and m["hybrid_version"] == H.HYBRID_VERSION


def _sample(pack: str, n: int) -> list[dict]:
    ts = load_pack(pack)
    return ts[:: max(1, len(ts) // n)][:n]


@pytest.mark.parametrize("pack,n", [("fixtures-hybrid", 20), ("ercot-hybrid-v3-showcase", 4),
                                    ("ercot-hybrid-v3-eval", 30), ("ercot-hybrid-v3-train", 30)])
def test_anchor_commits_are_never_refused_and_settle_to_p_anchor(pack, n):
    for t in _sample(pack, n):
        for tier in ("energy", "reserves"):
            s = H.play(t, tier, H.anchor_policy())
            assert not s.refusals, (t["task_id"], tier, s.refusals[:2])
            assert all(c["committed"] for c in s.commits)
            assert s.profit() == pytest.approx(t["refs"][tier]["p_anchor"], abs=1e-6)
            assert all(x["repaired"] == 0 for x in s.anchor_log if not x["soft"]), (t["task_id"], s.anchor_log)
