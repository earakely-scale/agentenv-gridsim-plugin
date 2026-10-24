import csv
import io
import zipfile

import numpy as np

from gridsim_core.market_auction import book, clear_hour
from gridsim_core.market_stack import aggregate, build_day, disclosure, parse_disclosure, resource_curves, simplify

GEN_COLS = (["Delivery Date", "Hour Ending", "QSE", "DME", "Resource Name", "Resource Type"]
            + [f"QSE submitted Curve-{k}{i}" for i in range(1, 11) for k in ("MW", "Price")]
            + ["Start Up Hot", "Start Up Inter", "Start Up Cold", "Min Gen Cost", "HSL", "LSL", "Resource Status",
               "Awarded Quantity", "Settlement Point Name", "Energy Settlement Point Price", "RegUp Awarded",
               "RegUp MCPC", "RegDown Awarded", "RegDown MCPC", "RRSPFR Awarded", "RRSFFR Awarded", "RRSUFR Awarded",
               "RRS MCPC", "ECRSSD Awarded", "ECRS MCPC", "NonSpin Awarded", "NonSpin MCPC"])


def _eo_cols(pre):
    return (["Delivery Date", "Hour Ending", "Settlement Point", "QSE Name"]
            + [f"{pre} {k}{i}" for i in range(1, 11) for k in ("MW", "Price")]
            + [f"{pre} ID", "Multi-Hour Block Indicator", "Block/Curve indicator"])


def _csv(cols, rows):
    f = io.StringIO()
    w = csv.DictWriter(f, cols)
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return f.getvalue()


def _gen(h, name, typ, qse, pts, hsl, lsl, award, up=0.0):
    r = {"Delivery Date": "08/20/2024", "Hour Ending": h, "QSE": qse, "Resource Name": name, "Resource Type": typ,
         "HSL": hsl, "LSL": lsl, "Awarded Quantity": award, "Resource Status": "ON", "Settlement Point Name": name,
         "Start Up Hot": 5000, "Min Gen Cost": 0, "RegUp Awarded": up}
    for i, (m, p) in enumerate(pts, 1):
        r[f"QSE submitted Curve-MW{i}"], r[f"QSE submitted Curve-Price{i}"] = m, p
    return r


def _eo(h, sp, qse, pts, pre, ind="C"):
    r = {"Delivery Date": "08/20/2024", "Hour Ending": h, "Settlement Point": sp, "QSE Name": qse,
         "Multi-Hour Block Indicator": "N", "Block/Curve indicator": ind}
    for i, (m, p) in enumerate(pts, 1):
        r[f"{pre} MW{i}"], r[f"{pre} Price{i}"] = m, p
    return r


def sample_zip(tmp_path):
    gen, bids, offers = [], [], []
    for h in range(1, 25):
        gen.append(_gen(h, "CC1", "CCGT90", "Q1", [(100, 15), (400, 25)], 400, 100, 300, up=50))
        gen.append(_gen(h, "BIGCC", "CCGT90", "Q9", [(0, 18), (30000, 40)], 30000, 0, 20000))
        gen.append(_gen(h, "PEAK", "SCGT90", "Q9", [(0, 60), (8000, 400)], 8000, 0, 0))
        for k in range(7):
            gen.append(_gen(h, f"CT{k}", "SCGT90", "Q2", [(0, 30 + k), (80, 35 + k)], 80, 30, 0))
        for k in range(3):
            gen.append(_gen(h, f"ESR{k}", "PWRSTR", "Q3", [(0, 4999), (150, 5000)], 150, 0, 0))
        gen.append(_gen(h, "WIND1", "WIND", "Q4", [(1200, -5)], 1200, 0, 1200))
        bids.append(_eo(h, "LZ_NORTH", "Q5", [(4000, 5000), (4500, 100)], "Energy Only Bid"))
        bids.append(_eo(h, "ESR0", "Q3", [(300, 8)], "Energy Only Bid", "V"))
        bids.append(_eo(h, "HB_NORTH", "Q6", [(25000, 5000), (27000, 30), (29000, 10)], "Energy Only Bid"))
        offers.append(_eo(h, "HB_NORTH", "Q7", [(500, 20)], "Energy Only Offer", "V"))
    p = tmp_path / "2024-08-20.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("60d_DAM_Gen_Resource_Data-19-OCT-24.csv", _csv(GEN_COLS, gen))
        z.writestr("60d_DAM_EnergyBids-19-OCT-24.csv", _csv(_eo_cols("Energy Only Bid"), bids))
        z.writestr("60d_DAM_EnergyOnlyOffers-19-OCT-24.csv", _csv(_eo_cols("Energy Only Offer"), offers))
        z.writestr("60d_DAM_EnergyBidAwards-19-OCT-24.csv", "Delivery Date,Hour Ending,Settlement Point,QSE Name,"
                   "Energy Only Bid Award in MW,Settlement Point Price,Bid ID\n" +
                   "".join(f"08/20/2024,{h},HB_NORTH,Q6,-28000,30,x\n" for h in range(1, 25)))
    return p


def test_resource_curve_truncates_as_and_prices_lsl():
    r = _gen(1, "CC1", "CCGT90", "Q1", [(100, 15), (400, 25)], 400, 100, 300, up=50)
    s, d = resource_curves({k: str(v) for k, v in r.items()}, -250.0)
    assert d == [] and s[0] == [0.0, 15.0] and s[1] == [100.0, 15.0] and s[-1][0] == 350.0
    assert abs(s[-1][1] - (15 + 10 * 250 / 300)) < 1e-9


def test_esr_curve_splits_at_zero():
    r = _gen(1, "E", "ESR", "Q", [(-50, -250), (0, -250), (0, 5000), (50, 5000)], 50, -50, 0)
    s, d = resource_curves({k: str(v) for k, v in r.items()}, -250.0)
    assert s[-1] == [50.0, 5000.0] and d[-1] == [50.0, -250.0]


def test_parse_and_build_day(tmp_path):
    p = sample_zip(tmp_path)
    hours = parse_disclosure(p, "2024-08-20")
    assert len(hours) == 24 and hours[0]["cleared_mw"] == 28000
    sup = [c for _, c in hours[17]["supply"]]
    dem = [c for _, c in hours[17]["demand"]]
    lam = clear_hour(book(-250.0, 5000.0, sup, dem), [], {}).lam
    z = np.zeros(24)
    row = build_day(p, "2024-08-20", [lam] * 24, [lam + 1] * 24, [lam] * 96, {"load_mw": z, "wind_mw": z,
                                                                              "solar_mw": z}, z)
    assert {m["id"] for m in row["pool"]["esr"]} == {"e1"} and row["pool"]["ct"][0]["units"][0]["id"] == "u1"
    assert len(row["pool"]["ct"][0]["units"]) == 7 and row["pool"]["load"][0]["size_mw"] == 4500
    assert "CT0" not in str(row) and "Q2" not in str(row)
    assert row["fidelity"]["within_ns"] == 1.0
    assert all(abs(a - b) < 0.05 for a, b in zip(row["replay"]["lambda_usd"], row["replay"]["full_lambda_usd"],
                                                 strict=True))
    d = disclosure(row | {"date": "2024-08-20"}, "supply", 18)
    assert len(d["curve"]) <= 64 and d["curve"][-1][0] > 30000


def test_aggregate_and_simplify_keep_the_curve():
    curves = [[[0, 10], [100, 20]], [[0, 15], [50, 15], [50, 40], [80, 40]]]
    agg = aggregate(curves, "supply", -250.0, 5000.0)
    assert abs(agg[-1][0] - 180) < 1e-6
    s = simplify(agg, 4)
    assert len(s) <= 4 and s[0] == [0.0, 10.0]
