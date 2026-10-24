import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridsim_core.parse import ParseError, parse_actions


@given(st.lists(st.integers(-10**6, 10**6), min_size=24, max_size=24), st.sampled_from([",", " ", ", ", "\n", " ,\t"]))
def test_string_and_list_equivalent(acts, sep):
    s = sep.join(map(str, acts))
    assert parse_actions(acts) == parse_actions(s) == parse_actions(f"[{s}]") == parse_actions(f"  {s}  ") == acts


@pytest.mark.parametrize("bad", [
    [0] * 23, [0] * 25, [], "", "   ", "[]", " ".join(["0"] * 23), " ".join(["0"] * 25),
    [0.0] * 24, [1.5] + [0] * 23, " ".join(["1.0"] * 24), [[0] * 24], [[0]] * 24, f"[[{','.join(['0'] * 24)}]]",
    [True] + [0] * 23, ["1"] * 24, " ".join(["a"] * 24), None, 5, {"actions": [0] * 24}, "1e2 " * 24,
])
def test_rejects(bad):
    with pytest.raises(ParseError):
        parse_actions(bad)


def test_out_of_range_parses():
    assert parse_actions([99] + [-99] * 23)[0] == 99
