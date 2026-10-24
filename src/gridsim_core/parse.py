"""Parse a submitted schedule: exactly 24 integers as a JSON list or a comma/whitespace-separated string."""

from __future__ import annotations

import re

from gridsim_core.contract import HOURS

_INT = re.compile(r"[+-]?\d+")


class ParseError(ValueError):
    """The input is not a submission."""


def parse_actions(actions, hours: int = HOURS) -> list[int]:
    """list[int] of length 24, or ParseError with the reason; out-of-range values parse and truncate later."""
    if isinstance(actions, str):
        s = actions.strip()
        if s.startswith("[") and s.endswith("]"):
            s = s[1:-1]
        if "[" in s or "]" in s:
            raise ParseError("nested lists are not allowed")
        tokens = [t for t in re.split(r"[\s,]+", s) if t]
        bad = [t for t in tokens if not _INT.fullmatch(t)]
        if bad:
            raise ParseError(f"not an integer: {bad[0]!r}")
        out = [int(t) for t in tokens]
    elif isinstance(actions, (list, tuple)):
        for a in actions:
            if isinstance(a, bool) or not isinstance(a, int):
                raise ParseError(f"not an integer: {a!r}")
        out = [int(a) for a in actions]
    else:
        raise ParseError(f"expected a list of {hours} integers or a string, got {type(actions).__name__}")
    if len(out) != hours:
        raise ParseError(f"expected exactly {hours} integers, got {len(out)}")
    return out
