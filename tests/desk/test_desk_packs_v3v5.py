import datetime as dt

import pytest

from gridsim_core.desk import data
from gridsim_core.desk.impact import Stack
from gridsim_core.market_auction import limits
from gridsim_core.task import data_root

PACKS = [p.name for p in sorted((data_root() / "desk").glob("desk-v[35]-*")) if (p / "tasks.jsonl.gz").exists()]
pytestmark = pytest.mark.skipif(not PACKS, reason="no v3/v5 desk packs")


@pytest.mark.parametrize("pack", PACKS)
def test_v3_fields(pack):
    for t in data.load_tasks(pack):
        s = data.load_series(pack, t)
        ser = data.build(t, s)
        assert t["layer"] in ("v3", "v5")
        assert set(ser.dam_mcpc) >= {"regup", "regdn", "rrs", "nspin"}
        assert ser.as_plan and ser.reg_up and len(ser.reg_up) == 24 * len(t["dates"])
        for d in t["dates"]:
            op = s["operator"]["dam"][d]
            assert "as_offers" in op
            for blocks in (b for v in op["as_offers"].values() for b in v if b):
                assert 1 <= len(blocks) <= 5 and all(mw >= 0.1 and p >= 0 for mw, p in blocks)
        if t["era"] == "rtcb":
            assert ser.rt_mcpc and ser.asdc
            assert all(s["operator"]["sced"][d]["as_offer_updates"] for d in t["dates"]) or not t["operator_ok"]
        if t["site"]["pv"]:
            assert len(ser.pv) == 288 * len(t["dates"]) and max(ser.pv) <= t["site"]["pv"]["mw_ac"]
            assert any(f["kind"] == "pv" for f in s["forecasts"])
        else:
            assert not ser.pv


@pytest.mark.parametrize("pack", [p for p in PACKS if p.startswith("desk-v5")])
def test_v5_market_reclear_without_battery_posts_real_price(pack):
    for t in data.load_tasks(pack):
        s = data.load_series(pack, t)
        for d in t["dates"]:
            day = s["market"][d]
            assert day["carved"]["resource"] == t["site"]["resource"]
            floor, cap = limits(d)
            st = Stack(day, s["dam_spp"][d], floor, cap)
            assert all(abs(st.clear(h, None, True)[0] - s["dam_spp"][d][h]) < 1e-3 for h in range(24))


TRAIN = data_root() / "desk" / "desk-v4-train"
HELD = ("desk-v4-bench", "desk-v4-eval", "desk-v4-pilot")
PERIODS = (("2025-12-20", "2026-01-22"), ("2026-05-11", "2026-07-03"))


@pytest.mark.skipif(not (TRAIN / "tasks.jsonl.gz").exists(), reason="no desk-v4-train pack")
def test_v4_train_days_come_from_disjoint_three_day_windows_away_from_the_benchmark():
    tasks = data.load_tasks(str(TRAIN))
    day = dt.date.fromisoformat
    held = {day(d) for p in HELD for t in data.load_tasks(p) for d in t["dates"]}
    windows: dict[str, set] = {}
    for t in tasks:
        [d] = t["dates"]
        w, k = t["tags"]["window"], int(t["tags"]["window_day"][1:])
        assert (t["layer"], t["era"], t["task_id"]) == ("v4", "rtcb", f"desk-v4-{d}-{t['site']['site_id']}")
        assert day(d) == day(w) + dt.timedelta(days=k) and t["split"] in ("train", "val")
        assert any(a <= d <= b for a, b in PERIODS) and min(abs((day(d) - h).days) for h in held) > 3
        assert t["refs"]["series_sha"] and t["refs"]["p_hind"] >= t["refs"]["p_idle"] - 1
        windows.setdefault(w, set()).add((d, t["site"]["site_id"], t["split"]))
    starts = sorted(map(day, windows))
    assert all(b - a >= dt.timedelta(days=3) for a, b in zip(starts, starts[1:], strict=False))
    assert all(len({s for _, _, s in v}) == 1 for v in windows.values())
    val = [w for w, v in windows.items() if {s for _, _, s in v} == {"val"}]
    assert len(val) == 3 and all(len(windows[w]) == 12 for w in val)
    series = data.load_series(str(TRAIN), tasks[0])
    [dam] = [v for v in series["desk_forecast"] if v["market"] == "dam"]
    assert dam["issued_at"].startswith(str(day(tasks[0]["dates"][0]) - dt.timedelta(days=1)) + "T06:00")
