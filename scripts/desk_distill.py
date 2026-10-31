"""Distilling the desk's anchor into a student model.

`feas` plays the anchor on desk-v4-train days, then again with its submissions degraded the ways an imitating
student errs, and grades every play against the day's stored references:

    python scripts/desk_distill.py feas --pack <desk-v4-train dir> --out feas.jsonl
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from gridsim_core.desk import Session, grade, load_series, load_tasks, policies, system_prompt, text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import desk_distill_stub as stub  # noqa: E402

SUBMITS = ("submit_dam_offers", "submit_rt_offers", "update_cop")


def _rng(task_id: str, name: str, seed: int) -> np.random.Generator:
    return np.random.default_rng(int(hashlib.sha256(f"{task_id}|{name}|{seed}".encode()).hexdigest()[:12], 16))


def _q(x: float, step: float) -> float:
    return round(round(x / step) * step, 6)


def _repair(points: list[list[float]], lo: float, hi: float) -> list[list[float]]:
    pts = sorted([[min(max(m, lo), hi), p] for m, p in points], key=lambda x: x[0])
    out, top = [], -np.inf
    for m, p in pts:
        top = max(top, p)
        out.append([m, top])
    return out


def _map_points(args: dict, f: Callable[[float, float], tuple[float, float]]) -> dict:
    for c in args.get("curves", []):
        pts = c["points"]
        lo, hi = min(m for m, _ in pts), max(m for m, _ in pts)
        c["points"] = _repair([list(f(m, p)) for m, p in pts], lo, hi)
    for o in args.get("as_offers", []):
        pairs = [f(m, p) for m, p in zip(o["mw"], o["price"], strict=True)]
        o["mw"], o["price"] = [max(m, 0.0) for m, _ in pairs], [max(p, 0.0) for _, p in pairs]
    for r in args.get("rows", []):
        if isinstance(r.get("hbsoc_mwh"), list):
            r["hbsoc_mwh"] = [max(f(v, 0.0)[0], 0.0) for v in r["hbsoc_mwh"]]
    return args


def _hours(h) -> list[int]:
    if isinstance(h, list):
        return [int(x) for x in h]
    a, _, b = h.partition("-")
    return list(range(int(a[2:]), int((b or a)[2:]) + 1))


def _shift(args: dict) -> dict:
    for c in args.get("curves", []) + args.get("as_offers", []):
        hs = [x + 1 for x in _hours(c["hours"]) if x < 24]
        if "mw" in c:
            keep = [i for i, x in enumerate(_hours(c["hours"])) if x < 24]
            c["mw"], c["price"] = [c["mw"][i] for i in keep], [c["price"][i] for i in keep]
        c["hours"] = hs
    args["curves"] = [c for c in args.get("curves", []) if c["hours"]] if "curves" in args else None
    args["as_offers"] = [c for c in args.get("as_offers", []) if c["hours"]] if "as_offers" in args else None
    return {k: v for k, v in args.items() if v is not None}


def _smooth(args: dict) -> dict:
    cs = args.get("curves", [])
    by = {tuple(_hours(c["hours"])): c["points"] for c in cs}
    keys = list(by)
    for i, c in enumerate(cs):
        group = [by[keys[j]] for j in (i - 1, i, i + 1) if 0 <= j < len(keys) and len(by[keys[j]]) == len(c["points"])]
        avg = [[statistics.fmean(g[k][0] for g in group), statistics.fmean(g[k][1] for g in group)]
               for k in range(len(c["points"]))]
        lo, hi = min(m for m, _ in c["points"]), max(m for m, _ in c["points"])
        c["points"] = _repair(avg, lo, hi)
    return args


def _noise(rng: np.random.Generator, sd: float) -> Callable[[float, float], tuple[float, float]]:
    return lambda m, p: (m * (1 + rng.normal(0, sd)), p + abs(p) * rng.normal(0, sd))


def _ident(tool: str, a: dict) -> dict:
    return a


def _every(i: int, wake: dict) -> bool:
    return True


def variant(name: str, task_id: str, seed: int = 0):
    """(args transform or None to drop the call, wake filter) for a degradation."""
    rng = _rng(task_id, name, seed)
    table = {
        "anchor": (_ident, _every),
        "round_0.1": (lambda t, a: _map_points(a, lambda m, p: (_q(m, 0.1), _q(p, 0.1))), _every),
        "round_0.5": (lambda t, a: _map_points(a, lambda m, p: (_q(m, 0.5), _q(p, 0.5))), _every),
        "round_5mw_1usd": (lambda t, a: _map_points(a, lambda m, p: (_q(m, 5), _q(p, 1))), _every),
        "noise_5%": (lambda t, a: _map_points(a, _noise(rng, 0.05)), _every),
        "noise_15%": (lambda t, a: _map_points(a, _noise(rng, 0.15)), _every),
        "smooth_3h": (lambda t, a: _smooth(a), _every),
        "shift_+1h": (lambda t, a: _shift(a), _every),
        "no_as": (lambda t, a: {k: v for k, v in a.items() if k != "as_offers"}, _every),
        "no_rt": (lambda t, a: None if t == "submit_rt_offers" else a, _every),
        "no_cop": (lambda t, a: None if t == "update_cop" else a, _every),
        "dam_only": (lambda t, a: a if t == "submit_dam_offers" else None, _every),
        "drop_10%": (lambda t, a: None if rng.random() < 0.10 else a, _every),
        "drop_30%": (lambda t, a: None if rng.random() < 0.30 else a, _every),
        "skip_half_wakes": (_ident, lambda i, w: i % 2 == 0),
        "first_wake_only": (_ident, lambda i, w: i == 0),
        "student_mix": (lambda t, a: None if rng.random() < 0.10 else
                        _map_points(a, lambda m, p: (_q(m * (1 + rng.normal(0, 0.05)), 0.1),
                                                     _q(p + abs(p) * rng.normal(0, 0.05), 0.1))),
                        lambda i, w: rng.random() >= 0.2),
    }
    return table[name]


VARIANTS = ("anchor", "round_0.1", "round_0.5", "round_5mw_1usd", "noise_5%", "noise_15%", "smooth_3h", "shift_+1h",
            "no_as", "no_rt", "no_cop", "dam_only", "drop_10%", "drop_30%", "skip_half_wakes", "first_wake_only",
            "student_mix")


def play(task: dict, series: dict, name: str, seed: int = 0) -> dict:
    fx, keep = variant(name, task["task_id"], seed)
    s = Session(task, series)
    real = s.call
    stats = {"submits": 0, "dropped": 0, "refused": 0, "plans": 0, "wakes": 0}

    def call(tool, args=None, role="default"):
        if tool in SUBMITS and role == "default":
            a = fx(tool, copy.deepcopy(args))
            if a is None:
                stats["dropped"] += 1
                return {"dropped": True}
            out = real(tool, a, role)
            stats["submits"] += 1
            stats["refused"] += bool(out.get("error") or out.get("rejected") or out.get("as_rejected"))
            return out
        return real(tool, args, role)

    s.call = call
    wake, i = s.start(), 0
    while wake is not None:
        stats["wakes"] += 1
        if wake["reasons"] != ["reminder"]:
            if keep(i, wake):
                stats["plans"] += 1
                policies.anchor(s, wake)
            i += 1
        wake = s.end_turn("")
    g = grade(s)
    return {"task_id": task["task_id"], "variant": name, "seed": seed, "C": g["capture"], "R": g["reward"],
            "valid": g["valid"], "p": g["p"], "anchor_C": g["anchor_capture"], **stats}


def feas(a: argparse.Namespace) -> None:
    rows = [r for r in load_tasks(a.pack) if r["split"] == "train" and r["operator_ok"]
            and not r["refs"]["c_undefined"]]
    rows = rows[a.shard::a.of][:a.limit]
    names = a.variant or VARIANTS
    a.out.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with a.out.open("w") as f:
        for k, r in enumerate(rows):
            ser = load_series(a.pack, r)
            for n in names:
                for seed in range(a.seeds if n in ("noise_5%", "noise_15%", "drop_10%", "drop_30%", "student_mix")
                                  else 1):
                    rec = play(r, ser, n, seed) | {"site": r["site"]["site_id"], "window": r["tags"]["window"],
                                                    "day_kind": r["tags"]["day_kind"]}
                    f.write(json.dumps(rec) + "\n")
            f.flush()
            print(f"{k + 1}/{len(rows)} {r['task_id']} {time.monotonic() - t0:.0f}s", file=sys.stderr, flush=True)


def play_stub(task: dict, series: dict, every: int, prefix: str = "env0000_", system: str = "",
              log: Callable[[list[dict], dict], None] | None = None) -> tuple[Session, list[dict]]:
    """The stub's anchor over an OpenCode-shaped conversation, played in process: each wake a JSON-string user message,
    each call an assistant tool call and its tool result."""
    s = Session(task, series)
    msgs: list[dict] = [{"role": "system", "content": system}]

    def act_for() -> dict:
        act = stub.decide(msgs, prefix, every)
        if log:
            log(msgs, act)
        return act

    wake = s.start()
    while wake is not None:
        msgs.append({"role": "user", "content": json.dumps(text(wake))})
        while "tool" in (act := act_for()):
            cid = f"c{len(msgs)}"
            fn = {"name": act["tool"], "arguments": json.dumps(act["args"])}
            call = {"id": cid, "type": "function", "function": fn}
            msgs.append({"role": "assistant", "content": "", "tool_calls": [call]})
            out = s.call(act["tool"][len(prefix):], act["args"])
            msgs.append({"role": "tool", "tool_call_id": cid, "content": text(out)})
        msgs.append({"role": "assistant", "content": act["text"]})
        wake = s.end_turn(act["text"])
    return s, msgs


def inproc(a: argparse.Namespace) -> None:
    """Stub sessions played in process and logged in the stub's capture format, with a reference OpenCode request's
    system prompt head and tail and its tools (renamed to env0000_): for sizing before the real capture."""
    ref = json.loads(a.reference.read_text())
    old = stub.prefix_of(ref["tools"])
    tools = json.loads(json.dumps(ref["tools"]).replace(old, "env0000_"))
    ctx = json.loads(a.context.read_text())
    rows = [r for r in load_tasks(a.pack) if r["split"] == a.split][:a.limit]
    log = stub.Log(a.out)
    out = []
    for r in rows:
        ser = load_series(a.pack, r)
        s0 = Session(r, ser)
        system = ctx["head"] + system_prompt(s0) + ctx["tail"]

        def rec(msgs, act, r=r):
            log.write({"messages": json.loads(json.dumps(msgs)), "tools": tools,
                       "chat_template_kwargs": {"enable_thinking": True}, "task": r["task_id"]}, act, "desk")

        s, _ = play_stub(r, ser, a.every, system=system, log=rec)
        g = grade(s)
        out.append({"task_id": r["task_id"], "every": a.every, "C": g["capture"], "anchor_C": g["anchor_capture"],
                    "refusals": refusals(s)})
        print(json.dumps(out[-1]), flush=True)


def refusals(s: Session) -> dict:
    """Per submit tool: calls, and calls the env refused in part or whole."""
    out: dict[str, list[int]] = {}
    for t in s.turns:
        for c in t["calls"]:
            if c["tool"] in SUBMITS:
                r = c["result"]
                bad = bool(r.get("error") or r.get("rejected") or r.get("as_rejected"))
                out.setdefault(c["tool"], [0, 0])
                out[c["tool"]][0] += 1
                out[c["tool"]][1] += bad
    return out


def selftest(a: argparse.Namespace) -> None:
    for r in load_tasks(a.pack)[:a.limit]:
        ser = load_series(a.pack, r)
        ref = Session(r, ser)
        calls: list[tuple[str, dict]] = []
        real = ref.call

        def rec(name, args=None, role="default", real=real, calls=calls):
            if role == "default" and name in SUBMITS:
                calls.append((name, copy.deepcopy(args)))
            return real(name, args, role)

        ref.call = rec
        w = ref.start()
        while w is not None:
            policies.anchor(ref, w)
            w = ref.end_turn("")
        s, msgs = play_stub(r, ser, 1)
        got = [(m["tool_calls"][0]["function"]["name"][8:], json.loads(m["tool_calls"][0]["function"]["arguments"]))
               for m in msgs if m.get("tool_calls")]
        got = [x for x in got if x[0] in SUBMITS]
        print(f"{r['task_id']} anchor C {grade(ref)['capture']} stub C {grade(s)['capture']} submits {len(calls)} "
              f"identical {got == calls}")


def _boot(d: dict[str, list[float]], n: int = 10000) -> tuple[float, float]:
    rng = np.random.default_rng(0)
    blocks = list(d.values())
    ms = sorted(statistics.fmean(x for b in (blocks[i] for i in rng.integers(0, len(blocks), len(blocks))) for x in b)
                for _ in range(n))
    return ms[int(0.025 * n)], ms[int(0.975 * n)]


def feas_report(a: argparse.Namespace) -> None:
    recs = [json.loads(x) for p in a.inp for x in p.open()]
    by: dict[tuple[str, str], list[dict]] = {}
    for r in recs:
        by.setdefault((r["variant"], r["task_id"]), []).append(r)
    days = sorted({r["task_id"] for r in recs})
    win = {r["task_id"]: r["window"] for r in recs}
    c = {v: {t: statistics.fmean(x["C"] for x in by[(v, t)]) for t in days} for v in VARIANTS if (v, days[0]) in by}
    base = c["anchor"]
    m0 = statistics.fmean(base.values())
    print(f"{len(days)} train days, {len(set(win.values()))} windows; anchor C mean {m0:.4f} median "
          f"{statistics.median(base.values()):.4f}, above idle {sum(x > 0 for x in base.values()) / len(days):.0%}")
    print("variant | C mean | kept | diff vs anchor [window-block 95% CI] | above idle | >= anchor - 0.01 | "
          "refused share | submits/day | plans/day")
    for v, cv in c.items():
        d: dict[str, list[float]] = {}
        for t in days:
            d.setdefault(win[t], []).append(cv[t] - base[t])
        lo, hi = _boot(d)
        rs = [x for t in days for x in by[(v, t)]]
        sub = sum(x["submits"] for x in rs)
        print(f"{v} | {statistics.fmean(cv.values()):+.4f} | {statistics.fmean(cv.values()) / m0:.0%} | "
              f"{statistics.fmean(cv[t] - base[t] for t in days):+.4f} [{lo:+.4f}, {hi:+.4f}] | "
              f"{sum(x > 0 for x in cv.values()) / len(days):.0%} | "
              f"{sum(cv[t] >= base[t] - 0.01 for t in days) / len(days):.0%} | "
              f"{sum(x['refused'] for x in rs) / max(sub, 1):.0%} | {sub / len(rs):.1f} | "
              f"{statistics.fmean(x['plans'] for x in rs):.1f}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("feas", help="the anchor and its degradations on train days")
    f.add_argument("--pack", required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--variant", action="append")
    f.add_argument("--seeds", type=int, default=2)
    f.add_argument("--limit", type=int)
    f.add_argument("--shard", type=int, default=0)
    f.add_argument("--of", type=int, default=1)
    t = sub.add_parser("selftest", help="the stub's anchor against the anchor, call for call")
    t.add_argument("--pack", required=True)
    t.add_argument("--limit", type=int, default=3)
    i = sub.add_parser("inproc", help="stub sessions in process, in the capture format")
    i.add_argument("--pack", required=True)
    i.add_argument("--split", default="train")
    i.add_argument("--every", type=int, default=2)
    i.add_argument("--limit", type=int)
    i.add_argument("--reference", type=Path, required=True)
    i.add_argument("--context", type=Path, required=True)
    i.add_argument("--out", type=Path, required=True)
    r = sub.add_parser("feas-report", help="summarise feas output")
    r.add_argument("inp", type=Path, nargs="+")
    a = ap.parse_args()
    {"feas": feas, "feas-report": feas_report, "selftest": selftest, "inproc": inproc}[a.cmd](a)


if __name__ == "__main__":
    main()
