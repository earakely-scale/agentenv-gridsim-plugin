"""Token credit for registered run 3: the DP's exact hour advantages on the tokens of the 24 submitted integers
(sign token = the token right before an integer's first digit, gets Q*(sign class) - V*; digit tokens get
Q*(a) - Q*(sign class)), the sequence advantage R - 1 on every other token, -1 on every token of an unparseable
completion. Every token's advantage is clipped to [-1, 0], the reward's own range."""

import re

from pathb import score

from gridsim_core.advantage import hour_advantages

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


def token_credit(task: dict, pieces: list[str], truncated: bool = False) -> dict:
    """Per-token advantages for one completion, plus R, the error kind and the hour diagnostics."""
    text, n = "".join(pieces), len(pieces)
    r = score(task, text, truncated)
    out = {"reward": r["reward"], "valid": r["valid"], "kind": r["kind"], "feasible": bool(r["valid"] and
           r["grade"]["feasible"]), "mapped": False, "hour_adv": None, "opt": None, "actions": r["actions"]}
    if not r["valid"]:
        return {**out, "adv": [-1.0] * n}
    adv = [r["reward"] - 1.0] * n
    spans = action_spans(text, r["actions"])
    if spans is None:
        return {**out, "adv": adv}
    h = hour_advantages(task, r["actions"])
    ends, pos = [], 0
    for p in pieces:
        pos += len(p)
        ends.append(pos)
    starts = [e - len(p) for e, p in zip(ends, pieces, strict=True)]
    for t, (a, b) in enumerate(spans):
        d0 = a + (text[a] == "-")
        digits = [i for i in range(n) if starts[i] < b and ends[i] > d0 and pieces[i]]
        if not digits or digits[0] == 0:
            return {**out, "adv": [r["reward"] - 1.0] * n}
        adv[digits[0] - 1] = min(0.0, max(-1.0, h["sign"][t]))
        for i in digits:
            adv[i] = min(0.0, max(-1.0, h["digit"][t]))
    cut = h["truncated_at"]
    executed = h["adv"][:24 if cut is None else cut + 1]
    return {**out, "adv": adv, "mapped": True, "hour_adv": executed, "opt": h["opt"]}
