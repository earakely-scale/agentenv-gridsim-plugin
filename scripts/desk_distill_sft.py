"""SFT rows from the stub anchor's OpenCode sessions, rendered as vLLM renders Qwen3.5-9B's requests.

A row is one wake: the request OpenCode sent for the wake's last turn, plus the reply that ended it, with a short
rationale as the reasoning of each of the wake's assistant turns. The rationale is written from what the agent saw by
then in that wake (the wake message and the tool outputs so far) and the previous plan's numbers still in the
conversation; never hindsight, references or the grade. Earlier wakes' reasoning is dropped by the chat template, as
it is when OpenCode replays the conversation. Tokens are cut at each turn's generation prompt, so every completion is
tokenised as the model generates it; only the wake's assistant turns are trained.

    python scripts/desk_distill_sft.py render --capture <dir> --tokenizer <dir> --out rows.jsonl [--show 3]
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import statistics
import sys
from pathlib import Path

from transformers import AutoTokenizer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_distill_stub as stub  # noqa: E402

GEN = "<|im_start|>assistant\n<think>\n"


def load(capture: Path) -> dict[str, list[dict]]:
    """Each session's desk requests in order: {tools, messages, params, action}."""
    out = {}
    for req in sorted(capture.glob("*.requests.jsonl")):
        key = req.name.split(".")[0]
        blobs = {}
        for line in (capture / f"{key}.blobs.jsonl").open():
            b = json.loads(line)
            blobs[b["h"]] = b["v"]
        rows = [json.loads(x) for x in req.open()]
        out[key] = [{"tools": blobs[r["tools"]], "messages": [blobs[h] for h in r["messages"]],
                     "params": r["params"], "action": r["action"]} for r in rows if r["kind"] == "desk"]
    return {k: v for k, v in out.items() if v}


def _num(x: float) -> str:
    return f"{x:,.0f}" if abs(x) >= 100 else f"{x:,.1f}"


def _hours(xs: list[int]) -> str:
    spans, i = [], 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[j + 1] == xs[j] + 1:
            j += 1
        spans.append(f"HE{xs[i]:02d}" + (f"-HE{xs[j]:02d}" if j > i else ""))
        i = j + 1
    return ", ".join(spans)


def _wake_line(w: dict) -> str:
    parts = [f"Wake at {w['now']} ({', '.join(w['reasons'])})."]
    for e in w.get("events", [])[:4]:
        parts.append(f"{e.get('kind', 'event')}: {(e.get('title') or e.get('text') or '')[:140].strip()}")
    dl = [f"{d['what']} at {d['at']}" for d in w.get("deadlines", [])[:3]]
    if dl:
        parts.append("Deadlines: " + "; ".join(dl) + ".")
    return " ".join(parts)


def _status(o: dict) -> str:
    return (f"SoC {o.get('soc_mwh')} MWh (usable {o.get('min_soc_mwh')}-{o.get('max_soc_mwh')}), status "
            f"{o.get('status')}, limits {o.get('lsl_mw')} to {o.get('hsl_mw')} MW, {o.get('cycles_today')} cycles today"
            + (f", outage {o['outage']}" if o.get("outage") else "") + ".")


def _forecast(o: dict) -> str:
    p50, p90 = o.get("p50") or [], o.get("p90") or []
    if not p50:
        return "No price forecast came back."
    lo, hi = min(range(len(p50)), key=p50.__getitem__), max(range(len(p50)), key=p50.__getitem__)
    cheap = sorted(sorted(range(len(p50)), key=p50.__getitem__)[:4])
    dear = sorted(sorted(range(len(p50)), key=p50.__getitem__)[-4:])
    return (f"Desk {o.get('market', '').upper()} P50 for {o.get('date')}: low ${_num(p50[lo])} at HE{lo + 1:02d}, high "
            f"${_num(p50[hi])} at HE{hi + 1:02d}, spread ${_num(p50[hi] - p50[lo])}; cheapest hours "
            f"{_hours([h + 1 for h in cheap])}, dearest {_hours([h + 1 for h in dear])}"
            + (f"; P90 peaks at ${_num(max(p90))}" if p90 else "") + ".")


def _plan(o: dict, prev: dict | None) -> str:
    sch = (o.get("schedule") or {}).get("hourly_mw") or []
    ch = [x.split(":")[0] for x in sch if float(x.split(":")[1]) < 0]
    dis = [x.split(":")[0] for x in sch if float(x.split(":")[1]) > 0]
    pr = o.get("projected") or {}
    start = (o.get("schedule") or {}).get("from")
    s = (f"The optimiser's schedule from {start}: charge in {', '.join(ch[:8]) or 'no hour'}"
         f"{' and more' if len(ch) > 8 else ''}, discharge in {', '.join(dis[:8]) or 'no hour'}"
         f"{' and more' if len(dis) > 8 else ''}.")
    if pr:
        sc = pr.get("pnl_by_scenario") or {}
        s += (f" Expected P&L ${_num(pr.get('expected', 0))} (P10 ${_num(sc.get('p10', 0))}, P90 "
              f"${_num(sc.get('p90', 0))})")
        if prev and (prev.get("projected") or {}).get("expected") is not None:
            s += f", against ${_num(prev['projected']['expected'])} at the last plan"
        s += "."
    as_ = sorted({g["product"] for g in o.get("dam_as_offers", []) + o.get("rt_as_offers", [])})
    if as_:
        s += f" It also offers {', '.join(as_)}."
    return s


def _submit_line(tool: str, args: dict) -> str:
    n = len(args.get("curves", []))
    a = sorted({x["product"] for x in args.get("as_offers", [])})
    if tool == "update_cop":
        return f"Next, the COP's HBSOC for {args.get('day')} {args['rows'][0]['hours']} so the plan's SoC is on file."
    kind = "DAM" if tool == "submit_dam_offers" else "RT"
    return (f"Next, {args.get('day')}'s {kind} offers as proposed: {n} hourly curves"
            + (f" with AS offers in {', '.join(a)}" if a else "") + ".")


def _result_line(out) -> str:
    if not isinstance(out, dict):
        return ""
    if out.get("error"):
        return f"That call failed: {str(out['error'])[:120]}."
    bad = [f"{x.get('hours')} {x.get('code')}" for x in (out.get("rejected") or []) + (out.get("as_rejected") or [])]
    if bad:
        return f"The env refused {', '.join(bad[:4])}; the rest stands."
    if "accepted_hours" in out:
        return f"Accepted {out['accepted_hours']}."
    return ""


def rationale(wake: dict, done: list[tuple[str, dict, object]], action: dict, prev_opt: dict | None,
              prefix: str) -> str:
    """The reasoning for the turn that takes `action`, from the wake and the turn's outputs so far."""
    names = [n[len(prefix):] if n.startswith(prefix) else n for n, _, _ in done]
    if "text" in action and not done:
        return (_wake_line(wake) + " No re-plan at this wake: the offers, AS offers and COP from the last plan stay "
                "in force, and I re-plan at the next wake.")
    if not done:
        return (_wake_line(wake) + " Re-plan at this wake: check the battery, read the desk price forecast, "
                "re-optimise and submit what the optimiser proposes.")
    last = done[-1][2]
    if names == ["get_asset_status"]:
        return _status(last) + " Now the desk price forecast."
    if names == ["get_asset_status", "get_forecasts"]:
        return (_forecast(last) + " Charge in the cheap hours and discharge into the dear ones only where the spread "
                "beats the round-trip loss and the $10/MWh degradation; the optimiser weighs that with the AS prices, "
                "so optimise on the desk view at risk 1.5 with the DAM spread position.")
    opt = done[2][2]
    head = _plan(opt, prev_opt) + " " if len(done) == 3 else _result_line(last) + " "
    if "text" in action:
        refused = sum(bool(_result_line(o).startswith(("The env refused", "That call failed"))) for _, _, o in done[3:])
        return (head + f"All {len(done) - 3} submissions are in" + (f", {refused} with refusals" if refused else "")
                + ". Done until the next wake.").strip()
    return (head + _submit_line(action["tool"][len(prefix):], action["args"])).strip()


def with_reasoning(req: dict) -> list[dict] | None:
    """The wake's conversation with every assistant turn of the wake given its rationale, ending with the reply."""
    msgs = copy.deepcopy(req["messages"])
    prefix = stub.prefix_of(req["tools"])
    wakes = stub.wakes_of(msgs)
    if not wakes or "text" not in req["action"]:
        return None
    i0, wake = wakes[-1]
    prev_opt = None
    for m in msgs[:i0]:
        if m.get("role") == "tool":
            o = stub._json(stub._text(m.get("content")))
            if isinstance(o, dict) and "dam_curves" in o and "projected" in o:
                prev_opt = o
    msgs.append({"role": "assistant", "content": req["action"]["text"]})
    done: list[tuple[str, dict, object]] = []
    by_id: dict[str, int] = {}
    for m in msgs[i0 + 1:]:
        if m["role"] == "assistant":
            calls = m.get("tool_calls") or []
            act = ({"tool": calls[0]["function"]["name"], "args": stub._json(calls[0]["function"]["arguments"]) or {}}
                   if calls else {"text": m.get("content", "")})
            m["reasoning_content"] = rationale(wake, done, act, prev_opt, prefix)
            assert m["reasoning_content"].strip(), "a trained turn without reasoning"
            for c in calls:
                by_id[c["id"]] = len(done)
                done.append((c["function"]["name"], stub._json(c["function"]["arguments"]) or {}, None))
        elif m["role"] == "tool" and m.get("tool_call_id") in by_id:
            j = by_id[m["tool_call_id"]]
            done[j] = (done[j][0], done[j][1], stub._json(stub._text(m.get("content"))))
    return msgs


def _vllm(messages: list[dict]) -> list[dict]:
    """vLLM hands the template each tool call's arguments as an object."""
    out = copy.deepcopy(messages)
    for m in out:
        for c in m.get("tool_calls") or []:
            if isinstance(c["function"].get("arguments"), str):
                c["function"]["arguments"] = json.loads(c["function"]["arguments"] or "{}")
    return out


def render(tok, tools: list[dict], messages: list[dict], kwargs: dict) -> dict:
    """input_ids and completion_mask for one wake: the prompt up to each assistant turn of the wake, then the turn."""
    msgs = _vllm(messages)
    i0 = stub.wakes_of(msgs)[-1][0]
    turns = [j for j in range(i0 + 1, len(msgs)) if msgs[j]["role"] == "assistant"]

    def text(upto: int, gen: bool) -> str:
        return tok.apply_chat_template(msgs[:upto], tools=tools, tokenize=False, add_generation_prompt=gen, **kwargs)

    ids, mask, pos = [], [], ""
    for j in turns:
        prompt = text(j, True)
        full = text(j + 1, False)
        assert prompt.startswith(pos) and full.startswith(prompt), "render is not prefix-consistent"
        gap = tok(prompt[len(pos):], add_special_tokens=False)["input_ids"]
        comp = full[len(prompt):]
        comp = comp[:comp.rindex("<|im_end|>") + len("<|im_end|>")]
        cids = tok(comp, add_special_tokens=False)["input_ids"]
        ids += gap + cids
        mask += [0] * len(gap) + [1] * len(cids)
        pos = prompt + comp
    return {"input_ids": ids, "completion_mask": mask, "text": pos}


def pick(n: int, per: int, key: str) -> list[int]:
    """``per`` wakes of ``n``, one from each of ``per`` equal parts of the window, seeded by the session."""
    if not per or per >= n:
        return list(range(n))
    rng = random.Random(key)
    cuts = [round(i * n / per) for i in range(per + 1)]
    return [rng.randrange(cuts[i], cuts[i + 1]) for i in range(per) if cuts[i + 1] > cuts[i]]


def rows(capture: Path, tok, kwargs: dict, per: int = 0) -> list[dict]:
    out = []
    for key, reqs in load(capture).items():
        ends = [r for r in reqs if "text" in r["action"]]
        keep = set(pick(len(ends), per, key))
        for k, req in enumerate(ends):
            if k not in keep:
                continue
            msgs = with_reasoning(req)
            if msgs is None:
                continue
            kw = kwargs | (req["params"].get("chat_template_kwargs") or {})
            r = render(tok, req["tools"], msgs, kw)
            out.append({"session": key, "wake": k, "of": len(ends), "n": len(r["input_ids"]),
                        "n_completion": sum(r["completion_mask"]), **r})
    return out


def stats(capture: Path, tok, kwargs: dict) -> list[dict]:
    """Per session from its last request: the tokens of the whole conversation as the template renders it (no
    reasoning), and at the end of each wake, whose sum sizes the rows; wakes and planning wakes."""
    out = []
    for key, reqs in load(capture).items():
        last = reqs[-1]
        msgs = _vllm(last["messages"] + ([{"role": "assistant", "content": last["action"]["text"]}]
                                         if "text" in last["action"] else []))
        txt = tok.apply_chat_template(msgs, tools=last["tools"], tokenize=False, add_generation_prompt=False,
                                      **(kwargs | (last["params"].get("chat_template_kwargs") or {})))
        enc = tok(txt, add_special_tokens=False, return_offsets_mapping=True)
        starts = [s0 for s0, _ in enc["offset_mapping"]]
        cuts = [i for i in range(len(txt)) if txt.startswith("<|im_start|>user\n\"{", i)][1:] + [len(txt)]
        ends = [sum(1 for s0 in starts if s0 < c) for c in cuts]
        plans = sum(1 for m in last["messages"] if m.get("role") == "assistant" and any(
            c["function"]["name"].endswith("_optimize") for c in m.get("tool_calls") or []))
        out.append({"session": key, "task": last["params"].get("task"), "tokens": len(enc["input_ids"]),
                    "wakes": len(ends), "plans": plans, "row_tokens": sum(ends)})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render")
    r.add_argument("--capture", type=Path, required=True)
    r.add_argument("--tokenizer", required=True)
    r.add_argument("--out", type=Path, required=True)
    r.add_argument("--show", type=int, default=0)
    r.add_argument("--per-window", type=int, default=0, help="wakes per window, one from each part (0: all)")
    t = sub.add_parser("stats")
    t.add_argument("--capture", type=Path, required=True)
    t.add_argument("--tokenizer", required=True)
    t.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    if a.cmd == "stats":
        tok = AutoTokenizer.from_pretrained(a.tokenizer)
        st = stats(a.capture, tok, {"enable_thinking": True})
        a.out.write_text("".join(json.dumps(x) + "\n" for x in st))
        for k in ("tokens", "row_tokens", "wakes", "plans"):
            v = sorted(x[k] for x in st)
            print(f"{k}: p50 {statistics.median(v):.0f} p90 {v[int(0.9 * (len(v) - 1))]} max {v[-1]} sum {sum(v)}")
        return
    tok = AutoTokenizer.from_pretrained(a.tokenizer)
    rs = rows(a.capture, tok, {"enable_thinking": True}, a.per_window)
    with a.out.open("w") as f:
        for x in rs:
            f.write(json.dumps({k: v for k, v in x.items() if k != "text"}) + "\n")
    for x in rs[:a.show]:
        print(f"===== {x['session']} wake {x['wake']}: {x['n']} tokens, {x['n_completion']} trained")
        print(x["text"][-6000:])
    ns = [x["n"] for x in rs]
    if ns:
        print(f"{len(rs)} rows; tokens p50 {statistics.median(ns):.0f} max {max(ns)}; trained "
              f"{sum(x['n_completion'] for x in rs)} of {sum(ns)}")


if __name__ == "__main__":
    main()
