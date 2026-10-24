import datetime as dt
import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridsim_core import CONTRACT_VERSION
from gridsim_core.contract import (AS_DURATION_H, AS_ERAS, ERAS, as_duration_h, as_era, as_products, ceil_to_interval,
                                   era, price_violations)


def test_version():
    assert CONTRACT_VERSION == "1.0"


def test_era_boundaries():
    assert era("2021-12-31")["hcap"] == 9000 and era("2022-01-01")["hcap"] == 5000
    assert era("2014-01-01")["floor"] == era("2026-10-17")["floor"] == -250
    assert not era("2023-06-09")["ecrs"] and era("2023-06-10")["ecrs"]
    assert not era("2025-12-04")["rtcb"] and era(dt.date(2025, 12, 5))["rtcb"]
    starts = [r["start"] for r in ERAS]
    assert starts == sorted(starts)
    assert all(a["hcap"] >= b["hcap"] for a, b in itertools.pairwise(ERAS))


def test_price_violations():
    assert price_violations("2021-02-15", [9000.0] * 24) == []
    assert price_violations("2023-08-01", [5000.01] + [-250.0] * 23) == [0]
    assert price_violations("2023-08-01", [-250.01] + [0.0] * 23) == [0]


@given(st.datetimes(min_value=dt.datetime(2014, 1, 1), max_value=dt.datetime(2030, 1, 1)),
       st.sampled_from([5, 15, 60]))
def test_ceil_to_interval_datetime(t, m):
    c = ceil_to_interval(t, m)
    on = t.second == 0 and t.microsecond == 0 and (t.hour * 60 + t.minute) % m == 0
    assert c >= t and (c == t) == on and c - t < dt.timedelta(minutes=m)
    assert c.second == 0 and c.microsecond == 0 and (c.hour * 60 + c.minute) % m == 0 or c.time() == dt.time(0)


@given(st.integers(0, 10**6), st.sampled_from([15, 60]))
def test_ceil_to_interval_minutes(t, m):
    c = ceil_to_interval(t, m)
    assert c >= t and (c == t) == (t % m == 0) and c % m == 0


def test_as_duration_table():
    assert [as_era(d) for d in ("2021-01-01", "2023-06-09", "2023-06-10", "2025-12-04", "2025-12-05")] == list("AABBC")
    assert "ecrs" not in as_products("2023-06-09") and "ecrs" in as_products("2023-06-10")
    assert as_duration_h("regup", "2024-01-01") == 1.0 and as_duration_h("regdn", "2026-01-01") == 0.5
    assert as_duration_h("ecrs", "2025-12-04") == 2.0 and as_duration_h("ecrs", "2025-12-05") == 1.0
    assert as_duration_h("nspin", "2021-06-01") == as_duration_h("nspin", "2026-06-01") == 4.0
    with pytest.raises(KeyError):
        as_duration_h("ecrs", "2022-07-01")
    assert all(set(AS_DURATION_H[r["era"]]) == set(r["products"]) for r in AS_ERAS)
