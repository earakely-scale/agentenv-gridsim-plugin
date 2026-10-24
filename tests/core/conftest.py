import gzip
import json
from pathlib import Path

import pytest
from hypothesis import strategies as st

from gridsim_core.task import make_task

FIXTURES = Path(__file__).resolve().parents[2] / "data" / "fixtures" / "tasks.jsonl.gz"


def battery_dict(n, k_dis, k_ch, eta, c_deg, cap, s0, s_end_min, q=10.0):
    return {"archetype": "t", "source": "custom", "p_dis_mw": k_dis * q, "p_ch_mw": k_ch * q, "energy_mwh": n * q,
            "unit_mwh": q, "q_15": q / 4, "k_dis": k_dis, "k_ch": k_ch, "soc_levels": n, "eta": eta, "c_deg": c_deg,
            "cycle_cap_units": cap, "s0": s0, "s_end_min": s_end_min}


@st.composite
def batteries(draw, max_n=16, k_min=2, k_max=4):
    n = draw(st.integers(1, max_n))
    k_dis, k_ch = draw(st.integers(k_min, k_max)), draw(st.integers(k_min, k_max))
    return battery_dict(n, k_dis, k_ch, draw(st.sampled_from([0.8, 0.85, 0.9])), draw(st.sampled_from([0.0, 4.0, 8.0])),
                        draw(st.integers(0, 2 * n)), draw(st.integers(0, n)), draw(st.integers(0, n)),
                        q=draw(st.sampled_from([2.5, 10.0, 25.0])))


price = st.floats(-250, 600, allow_nan=False).map(lambda x: round(x, 2))
nonpos = st.floats(-250, 0, allow_nan=False).map(lambda x: round(x, 2))


@st.composite
def tasks(draw, hours=24, **kw):
    prices = draw(st.one_of(st.lists(price, min_size=hours, max_size=hours),
                            st.lists(nonpos, min_size=hours, max_size=hours)))
    return make_task(prices, draw(batteries(**kw)))


def load_fixtures():
    if not FIXTURES.exists():
        return []
    with gzip.open(FIXTURES, "rt") as f:
        return [json.loads(line) for line in f]


@pytest.fixture(scope="session")
def fixtures():
    return load_fixtures()
