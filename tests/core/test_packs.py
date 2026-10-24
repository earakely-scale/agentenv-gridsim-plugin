import datetime as dt
import json
import random

import pytest

from gridsim_core.dp import solve_dp
from gridsim_core.grade import grade, references
from gridsim_core.task import data_root, load_pack

PACKS = ["ercot-dam-v1-train", "ercot-dam-v1-eval", "ercot-dam-v1-eval-iid", "ercot-dam-v1-rtcb", "showcase", "fixtures"]
SHOWCASE = [("2021-02-10", "2021-02-22"), ("2022-12-22", "2022-12-24"), ("2023-08-01", "2023-08-31"),
            ("2023-09-06", "2023-09-06"), ("2024-01-13", "2024-01-17")]


@pytest.fixture(scope="module", params=[p for p in PACKS if (data_root() / p / "tasks.jsonl.gz").exists()])
def pack(request):
    return request.param, load_pack(request.param), json.loads((data_root() / request.param / "manifest.json").read_text())


def test_manifest_and_ids(pack):
    name, tasks, man = pack
    assert man["count"] == len(tasks) and man["contract_version"] == "1.0"
    assert len({t["task_id"] for t in tasks}) == len(tasks)
    assert man["count_blind"] == sum(t["tags"]["blind_eval"] for t in tasks)
    for t in tasks:
        assert t["task_id"] == f"dam-v1-{t['date']}-{t['settlement_point']}-{t['battery']['archetype']}"
        assert len(t["prices"]) == 24 and t["battery"]["soc_levels"] <= 16
        assert (t["blind"] is not None) == t["tags"]["blind_eval"] == (t["refs"]["blind"] is not None) or name in (
            "showcase", "fixtures")


def test_holdouts(pack):
    name, tasks, _ = pack
    for t in tasks:
        d = t["date"]
        showcase = any(a <= d <= b for a, b in SHOWCASE)
        iid = (dt.date.fromisoformat(d) - dt.date(2014, 1, 1)).days % 10 == 9
        if name == "ercot-dam-v1-train":
            assert d < "2025-01-01" and not showcase and not iid
        elif name == "ercot-dam-v1-eval":
            assert "2025-01-01" <= d <= "2025-11-30"
        elif name == "ercot-dam-v1-eval-iid":
            assert d < "2025-01-01" and iid and not showcase
        elif name == "ercot-dam-v1-rtcb":
            assert "2025-12-05" <= d <= "2026-10-17"


def test_refs_reproduce(pack):
    _, tasks, _ = pack
    ridge = json.loads((data_root() / "ridge-v1.json").read_text())
    for t in random.Random(0).sample(tasks, min(40, len(tasks))):
        p, s = solve_dp(t)
        assert s == t["refs"]["foresight"]["opt"] and round(p, 6) == t["refs"]["foresight"]["p_opt"]
        assert grade(t, s)["reward"] == 1.0 and grade(t, [0] * 24)["reward"] == 0.2
        fresh = references(t, ridge=ridge if t["blind"] else None)
        assert fresh["foresight"]["baselines"] == t["refs"]["foresight"]["baselines"]
        assert fresh["blind"] == t["refs"]["blind"]


def test_reward_fn_resolves_task_ids():
    from gridsim_core.trl import reward_fn

    fx = load_pack("fixtures")
    opt = [t["refs"]["foresight"]["opt"] for t in fx[:3]]
    assert reward_fn(["p"] * 3, [str(o) for o in opt], task_id=[t["task_id"] for t in fx[:3]]) == [1.0] * 3
