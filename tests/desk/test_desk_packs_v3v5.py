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
