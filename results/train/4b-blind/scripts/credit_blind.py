"""Token credit for registered run 4: run 3's DP-exact credit, computed on the model's OWN written forecast. Planning on
a forecast is a foresight problem on that forecast, so A_t = Q*(s_t, a_t) - V*(s_t) by gridsim_core.advantage with
prices = the parsed forecast (scale 0.8 / (P_opt - P_idle) of the day, as run 3). The sign token of each submitted
integer gets Q*(sign class) - V*, its digit tokens Q*(a) - Q*(sign class); the forecast line's tokens get 0 (frozen
to the SFT behaviour through the KL term alone); every other token gets the plan's total, sum_t A_t. A completion
without a valid schedule or a parseable forecast gets -1 on every token. Every value is clipped to [-1, 0]."""

import re

from pathb_blind import score

from gridsim_core.advantage import hour_advantages
from gridsim_core.forecast_line import forecast_span

CALL = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|$)", re.S)
LIST = re.compile(r'"actions"\s*:\s*\[([^\[\]]*)\]')
INT = re.compile(r"-?\d+")


def pieces_of(tok, ids: list[int]) -> list[str]:
    """Each token's text; the end-of-turn token decodes to nothing, as in vLLM's text."""
    return ["" if i in (tok.eos_token_id, tok.pad_token_id) else tok.decode([i], skip_special_tokens=False)
            for i in ids]


def action_spans(text: str, acts: list[int]) -> list[tuple[int, int]] | None:
    """Character spans of the submitted integers: the first submit_schedule actions list that parses to acts."""
    for m in CALL.finditer(text):
        for lst in LIST.finditer(text, m.start(1), m.end(1)):
            ints = list(INT.finditer(text, lst.start(1), lst.end(1)))
            if [int(x.group()) for x in ints] == acts:
                return [(x.start(), x.end()) for x in ints]
    return None


def clip(x: float) -> float:
    return min(0.0, max(-1.0, x))


def token_credit(task: dict, pieces: list[str], truncated: bool = False) -> dict:
    """Per-token advantages for one completion, plus C on the day, the plan's capture on its forecast and the hours."""
    text, n = "".join(pieces), len(pieces)
    r = score(task, text, truncated)
    out = {"reward": r["c"], "c": r["c"], "valid": r["valid"], "kind": r["kind"], "forecast": r["forecast"] is not None,
           "feasible": bool(r["valid"] and r["grade"]["feasible"]), "c_f": r.get("c_f"),
           "is_dp_own": r.get("is_dp_own"), "mapped": False, "hour_adv": None}
    if not r["valid"] or r["forecast"] is None:
        return {**out, "adv": [-1.0] * n}
    h = hour_advantages(task, r["actions"], prices=r["forecast"])
    cut = h["truncated_at"]
    total = clip(sum(h["adv"]))
    adv = [total] * n
    ends, pos = [], 0
    for p in pieces:
        pos += len(p)
        ends.append(pos)
    starts = [e - len(p) for e, p in zip(ends, pieces, strict=True)]
    f0, f1 = forecast_span(text)
    for i in range(n):
        if starts[i] < f1 and ends[i] > f0 and pieces[i]:
            adv[i] = 0.0
    out |= {"hour_adv": h["adv"][:24 if cut is None else cut + 1], "plan_adv": sum(h["adv"])}
    spans = action_spans(text, r["actions"])
    if spans is None:
        return {**out, "adv": adv}
    hour_adv = list(adv)
    for t, (a, b) in enumerate(spans):
        d0 = a + (text[a] == "-")
        digits = [i for i in range(n) if starts[i] < b and ends[i] > d0 and pieces[i]]
        if not digits or digits[0] == 0:
            return {**out, "adv": adv}
        hour_adv[digits[0] - 1] = clip(h["sign"][t])
        for i in digits:
            hour_adv[i] = clip(h["digit"][t])
    return {**out, "adv": hour_adv, "mapped": True}
