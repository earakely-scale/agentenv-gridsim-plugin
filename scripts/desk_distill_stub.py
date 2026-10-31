"""A chat-completions endpoint that plays the desk anchor from the conversation alone, so OpenCode on route C can be
driven by the anchor and every request it sends captured verbatim. It never calls a model.

At each wake the anchor plans at (every wake but reminders, or every other one with --every 2) it reads the asset
status and the price forecast, calls `optimize` as the anchor does (risk 1.5, DAM position spread) and submits what it
proposes one call at a time, in the anchor's order; then it replies without a tool call, which ends OpenCode's turn.
Every request is logged under --log as JSON lines, messages content-addressed per session.

    python scripts/desk_distill_stub.py --port 4900 --log /home/ubuntu/distill/capture --every 2
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

OPTIMIZE_ARGS = {"price_view": "desk", "risk": 1.5, "constraints": {"dam_position": "spread"}}
DAY, ADJ_OPEN = 1440, -360
DAM_FOR = re.compile(r"DAM for \w{3} (\d\d-\d\d) closes")
LABEL = re.compile(r"\w{3} (\d\d)-(\d\d) (\d\d):(\d\d)")


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def _unquote(s: str) -> str:
    """A message OpenCode delivered quoted: decoded as JSON when it is, else with only its quotes unescaped."""
    if len(s) < 2 or s[0] != '"' or s[-1] != '"':
        return s
    try:
        x = json.loads(s)
    except ValueError:
        return s[1:-1].replace('\\"', '"')
    return x if isinstance(x, str) else s


def _json(s: str):
    if not isinstance(s, str):
        return None
    s = _unquote(s)
    try:
        return json.loads(s, strict=False)
    except ValueError:
        i = s.find("{")
        if i < 0:
            return None
        try:
            return json.loads(s[i:], strict=False)
        except ValueError:
            return None


def wake_of(msg: dict) -> dict | None:
    if msg.get("role") != "user":
        return None
    w = _json(_text(msg.get("content")))
    return w if isinstance(w, dict) and "reasons" in w and "now" in w else None


def prefix_of(tools: list[dict]) -> str | None:
    for t in tools or []:
        name = (t.get("function") or {}).get("name", "")
        if name.endswith("_optimize"):
            return name[: -len("optimize")]
    return None


def _date(mmdd: str, ref: dt.date) -> dt.date:
    m, d = map(int, mmdd.split("-"))
    return min((dt.date(y, m, d) for y in (ref.year - 1, ref.year, ref.year + 1)), key=lambda x: abs((x - ref).days))


def _minute(label: str, d0: dt.date) -> int:
    mo, d, h, mi = map(int, LABEL.match(label).groups())
    day = _date(f"{mo:02d}-{d:02d}", d0)
    return (day - d0).days * DAY + h * 60 + mi


def submits(out: dict, d0: dt.date) -> list[tuple[str, dict]]:
    """The anchor's calls for an `optimize` proposal, in its order (gridsim_core.desk.policies.anchor)."""
    calls: list[tuple[str, dict]] = []

    def groups(tool: str, curves: list[dict], as_offers: list[dict] | None) -> None:
        by_day: dict[str, dict] = {}
        for g in curves:
            c = {"hours": g["hours"]}
            if isinstance(g["points"], dict):
                c.update(g["points"])
            else:
                c["points"] = g["points"]
            by_day.setdefault(g["day"], {}).setdefault("curves", []).append(c)
        for g in as_offers or []:
            by_day.setdefault(g["day"], {}).setdefault("as_offers", []).append(
                {"hours": g["hours"], "product": g["product"], "mw": g["mw"], "price": g["price"]})
        calls.extend((tool, {"day": day, **args}) for day, args in by_day.items())

    now = _minute(out["now"], d0)
    groups("submit_dam_offers", out["dam_curves"], out.get("dam_as_offers"))
    groups("submit_rt_offers", [g for g in out["rt_curves"] if now >= int(g["day"][1:]) * DAY + ADJ_OPEN],
           out.get("rt_as_offers"))
    calls.extend(("update_cop", {"day": r["day"], "rows": [{"hours": r["hours"], "hbsoc_mwh": r["hbsoc_mwh"]}]})
                 for r in out["cop"])
    return calls


def wakes_of(messages: list[dict]) -> list[tuple[int, dict]]:
    return [(i, w) for i, m in enumerate(messages) if (w := wake_of(m))]


def start_d0(wakes: list[tuple[int, dict]]) -> dt.date:
    """D0 on a stand-in year: the start wake is D-1 06:00, and the conversation never names the year."""
    mo, d = map(int, LABEL.match(wakes[0][1]["now"]).groups()[:2])
    return dt.date(2000, mo, d) + dt.timedelta(days=1)


def d0_of(out: dict) -> dt.date | None:
    for g in out.get("dam_curves", []) + out.get("rt_curves", []):
        if g.get("day") and g.get("date"):
            return dt.date.fromisoformat(g["date"]) - dt.timedelta(days=int(g["day"][1:]))
    return None


def plan_index(wakes: list[tuple[int, dict]]) -> int | None:
    """The current wake's place among the non-reminder wakes, None for a reminder-only wake."""
    if wakes[-1][1]["reasons"] == ["reminder"]:
        return None
    return sum(w["reasons"] != ["reminder"] for _, w in wakes) - 1


def turn(messages: list[dict]) -> list[tuple[str, dict, dict | None]]:
    """The current wake's (tool, args, output) so far."""
    i = max(i for i, m in enumerate(messages) if wake_of(m))
    out, by_id = [], {}
    for m in messages[i + 1:]:
        if m.get("role") == "assistant":
            for tc in m.get("tool_calls") or []:
                f = tc.get("function") or {}
                by_id[tc.get("id")] = len(out)
                out.append([f.get("name", ""), _json(f.get("arguments") or "{}") or {}, None])
        elif m.get("role") == "tool" and m.get("tool_call_id") in by_id:
            out[by_id[m["tool_call_id"]]][2] = _json(_text(m.get("content")))
    return [tuple(x) for x in out]


def forecast_args(wakes: list[tuple[int, dict]]) -> dict:
    dam = [m.group(1) for x in wakes[-1][1].get("deadlines", []) if (m := DAM_FOR.search(x.get("what", "")))]
    if dam:
        ref = start_d0(wakes)
        return {"kind": "price", "market": "dam", "day": f"D{(_date(dam[0], ref) - ref).days}"}
    return {"kind": "price", "market": "rt", "step": "1h"}


NETCHECK = re.compile(r"Run this exact command in your shell[^\n]*\n\n(.+?)\n\nThen call", re.S)


def netcheck(messages: list[dict], prefix: str) -> dict:
    """The bundle's netcheck: run its command with OpenCode's bash tool, read the SoC, report both."""
    i = max(i for i, m in enumerate(messages) if m.get("role") == "user")
    cmd = NETCHECK.search(_unquote(_text(messages[i]["content"]))).group(1)
    outs = [_text(m.get("content")) for m in messages[i + 1:] if m.get("role") == "tool"]
    if not outs:
        return {"tool": "bash", "args": {"command": cmd, "description": "Network check"}}
    if len(outs) == 1:
        return {"tool": prefix + "get_asset_status", "args": {}}
    soc = (_json(outs[1]) or {}).get("soc_mwh")
    return {"text": f"{outs[0].strip()}\nsoc_mwh: {soc}"}


def decide(messages: list[dict], prefix: str, every: int) -> dict:
    """The next assistant action: {"tool", "args"} or {"text"}."""
    wakes = wakes_of(messages)
    if not wakes and any(NETCHECK.search(_text(m.get("content"))) for m in messages if m.get("role") == "user"):
        return netcheck(messages, prefix)
    if not wakes:
        return {"text": "Waiting for the desk's first wake-up."}
    k = plan_index(wakes)
    if k is None or k % every:
        return {"text": "No re-plan at this wake; the offers and COP in force stand."}
    done = turn(messages)
    names = [n[len(prefix):] if n.startswith(prefix) else n for n, _, _ in done]
    if any(isinstance(o, dict) and str(o.get("error", "")).startswith("budget") for _, _, o in done):
        return {"text": "Out of tool calls this turn; the offers in force stand."}
    if not names:
        return {"tool": prefix + "get_asset_status", "args": {}}
    if names == ["get_asset_status"]:
        return {"tool": prefix + "get_forecasts", "args": forecast_args(wakes)}
    if names == ["get_asset_status", "get_forecasts"]:
        return {"tool": prefix + "optimize", "args": json.loads(json.dumps(OPTIMIZE_ARGS))}
    opt = done[2][2]
    if not isinstance(opt, dict) or "error" in opt or "dam_curves" not in opt:
        return {"text": "The optimizer returned no proposal; the offers in force stand."}
    plan = submits(opt, d0_of(opt) or start_d0(wakes))
    n = len(done) - 3
    if n < len(plan):
        tool, args = plan[n]
        return {"tool": prefix + tool, "args": args}
    return {"text": "Submitted the re-optimised plan."}


class Log:
    def __init__(self, root: Path):
        self.root, self.lock, self.seen = root, threading.Lock(), {}
        root.mkdir(parents=True, exist_ok=True)

    def write(self, body: dict, action: dict, kind: str) -> None:
        msgs = body.get("messages") or []
        first = next((_text(m.get("content")) for m in msgs if m.get("role") == "user"), "")
        key = hashlib.sha1((_text(msgs[0].get("content")) if msgs else "").encode() + first.encode()).hexdigest()[:12]
        hs = []
        with self.lock:
            seen = self.seen.setdefault(key, set())
            with (self.root / f"{key}.blobs.jsonl").open("a") as f:
                for obj in [body.get("tools") or []] + msgs:
                    h = hashlib.sha1(json.dumps(obj, sort_keys=True).encode()).hexdigest()
                    if h not in seen:
                        seen.add(h)
                        f.write(json.dumps({"h": h, "v": obj}, ensure_ascii=False) + "\n")
                    hs.append(h)
            rec = {"t": time.time(), "kind": kind, "tools": hs[0], "messages": hs[1:],
                   "params": {k: v for k, v in body.items() if k not in ("messages", "tools")}, "action": action}
            with (self.root / f"{key}.requests.jsonl").open("a") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def tool_call(action: dict) -> dict:
    return {"id": f"chatcmpl-tool-{uuid.uuid4().hex[:16]}", "type": "function",
            "function": {"name": action["tool"], "arguments": json.dumps(action["args"])}}


def chunks(action: dict, model: str) -> list[dict]:
    cid, created = f"chatcmpl-{uuid.uuid4().hex[:24]}", int(time.time())

    def c(delta, finish=None):
        return {"id": cid, "object": "chat.completion.chunk", "created": created, "model": model,
                "choices": [{"index": 0, "delta": delta, "logprobs": None, "finish_reason": finish}]}

    out = [c({"role": "assistant", "content": ""})]
    if "tool" in action:
        out.append(c({"tool_calls": [{"index": 0} | tool_call(action)]}))
        out.append(c({}, "tool_calls"))
    else:
        out.append(c({"content": action["text"]}))
        out.append(c({}, "stop"))
    out.append({"id": cid, "object": "chat.completion.chunk", "created": created, "model": model, "choices": [],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
    return out


def serve(port: int, hosts: list[str], log: Log, every: int) -> None:
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            return

        def _send(self, code: int, obj: dict) -> None:
            b = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send(200, {"object": "list", "data": [{"id": "qwen3.5-9b", "object": "model"}]})

        def do_POST(self):
            if not self.path.rstrip("/").endswith("/chat/completions"):
                return self._send(404, {"error": {"message": "only chat completions"}})
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            msgs, prefix = body.get("messages") or [], prefix_of(body.get("tools"))
            if prefix is None:
                action, kind = {"text": "Battery desk window"}, "aux"
            else:
                try:
                    action, kind = decide(msgs, prefix, every), "desk"
                except Exception as e:
                    action, kind = {"text": "No action."}, f"error: {type(e).__name__}: {e}"
            log.write(body, action, kind)
            model = body.get("model", "qwen3.5-9b")
            if not body.get("stream"):
                msg = {"role": "assistant", "content": action.get("text", "")}
                if "tool" in action:
                    msg["tool_calls"] = [tool_call(action)]
                return self._send(200, {"id": f"chatcmpl-{uuid.uuid4().hex[:24]}", "object": "chat.completion",
                                        "created": int(time.time()), "model": model,
                                        "choices": [{"index": 0, "message": msg, "finish_reason":
                                                     "tool_calls" if "tool" in action else "stop"}],
                                        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            for ch in chunks(action, model):
                self.wfile.write(f"data: {json.dumps(ch)}\n\n".encode())
                self.wfile.flush()
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    servers = [ThreadingHTTPServer((h, port), H) for h in hosts]
    for srv in servers[1:]:
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    servers[0].serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--host", action="append", help="address to bind (repeatable; default loopback)")
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--every", type=int, default=1)
    a = ap.parse_args()
    serve(a.port, a.host or ["127.0.0.1"], Log(a.log), a.every)


if __name__ == "__main__":
    main()
