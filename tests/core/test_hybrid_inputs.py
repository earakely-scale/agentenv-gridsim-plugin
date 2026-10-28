import datetime as dt
import statistics

from gridsim_core import hybrid_inputs as hi
from gridsim_core.contract import as_products


def test_as_prices_eras():
    a, b, c = hi.as_prices("2022-07-01"), hi.as_prices("2023-09-06"), hi.as_prices("2026-01-26")
    assert (a["era"], b["era"], c["era"]) == ("A", "B", "C")
    assert a["ecrs"] is None and len(b["ecrs"]) == 24 and len(c["nspin"]) == 24
    for row in (a, b, c):
        assert all(len(row[p]) == row["n_hours"] for p in as_products(row["date"]))


def test_as_prices_cover_every_day():
    d, end = dt.date(2021, 1, 1), dt.date(2026, 10, 17)
    while d <= end:
        assert hi.as_prices(d) is not None, d
        d += dt.timedelta(days=7)


def test_solar_cf():
    cf = hi.solar_cf("2023-09-06", "west")
    assert len(cf) == 24 and all(0 <= x <= 1 for x in cf) and max(cf) > 0.5 and cf[0] < 0.01
    row = hi.solar_row("2024-03-29")
    assert row["repaired_hours"] and all(a >= b for a, b in zip(row["cf"], row["cf_actual"], strict=True))
    assert hi.pv_profile_mw([0.5], 150, 1.3) == [97.5]


def test_deployments_hero_day():
    ev = hi.deployments("2023-09-06")
    assert {e["product"] for e in ev} == {"rrs", "ecrs", "nspin"}
    assert all(e["start"] < e["end"] and e["summary"] and e["source_notice_id"] for e in ev)
    ns = next(e for e in ev if e["product"] == "nspin")
    assert ns["start"].startswith("2023-09-06T15:06") and ns["mw_max"] == 254.5


def test_reg_drift_seeded():
    a, b = hi.reg_drift("hyb-v3-x"), hi.reg_drift("hyb-v3-x")
    assert a == b and len(a["reg_up_frac"]) == 24 and a != hi.reg_drift("hyb-v3-y")
    up = [x for i in range(200) for x in hi.reg_drift(f"t{i}")["reg_up_frac"]]
    dn = [x for i in range(200) for x in hi.reg_drift(f"t{i}")["reg_dn_frac"]]
    assert abs(statistics.fmean(up) - 0.12) < 0.01 and abs(statistics.fmean(dn) - 0.18) < 0.01
    assert all(0 <= x <= 1 for x in up + dn)


def test_archetypes_default():
    a = hi.archetypes()
    assert a["default"]["pv_mwac"] == 150 and a["default"]["bess_mwh"] == 200 and a["default"]["poi_mw"] == 150
    assert abs(sum(x["weight"] for x in a["archetypes"]) - 1) < 1e-3
    assert len({x["id"] for x in a["archetypes"]}) == len(a["archetypes"])


def test_reg_drift_measured_where_ercot_covers_the_day_and_modelled_before():
    m, row = hi.reg_model(), hi.reg_series("2024-03-29")
    assert row and len(row["up"]) == len(row["dn"]) == 24 and all(row["n"]) and hi.reg_series("2023-10-11") is None
    assert 0.05 < m["data"]["mean_up"] < 0.4 and 0.05 < m["data"]["mean_dn"] < 0.4
    da, rt = [30.0] * 24, [80.0 if h >= 12 else -20.0 for h in range(24)]
    r = hi.reg_hourly("t", "2024-03-29", da, rt)
    assert r["source"] == "ercot" and r["up"] == row["up"] and r["dn"] == row["dn"]
    assert (r["mean_up"], r["mean_dn"]) == (m["data"]["mean_up"], m["data"]["mean_dn"])
    f = hi.reg_hourly("t", "2022-07-01", da, rt)
    assert f["source"] == "modelled" and f == hi.reg_hourly("t", "2022-07-01", da, rt)
    assert f != hi.reg_hourly("u", "2022-07-01", da, rt)
    assert all(u > d for u, d in zip(f["up"][12:], f["dn"][12:], strict=True))
    assert all(d > u for u, d in zip(f["up"][:12], f["dn"][:12], strict=True))
    assert all(0 <= x <= 1 for x in f["up"] + f["dn"])
