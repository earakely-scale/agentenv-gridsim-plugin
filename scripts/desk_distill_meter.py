"""A pass-through in front of the model server that logs each chat completion's usage per OpenCode session (prompt and
completion tokens, cached prompt tokens, finish reason, message count), so the eval can report the largest prompt a
window sent. Streams are relayed line by line; nothing is changed.

    python scripts/desk_distill_meter.py --listen 172.17.0.1:8001 --upstream 172.17.0.1:8000 --log meter.jsonl
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _text(content) -> str:
    if isinstance(content, list):
        return "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else ""


def session_key(msgs: list[dict]) -> str:
    first = next((_text(m.get("content")) for m in msgs if m.get("role") == "user"), "")
    return hashlib.sha1((_text(msgs[0].get("content")) if msgs else "").encode() + first.encode()).hexdigest()[:12]


SITE = re.compile(r"Battery (S\d\d)\b")
D0 = re.compile(r"starts operating day \w{3} (\d\d-\d\d)")


def window(msgs: list[dict]) -> str | None:
    sys = _text(msgs[0].get("content")) if msgs else ""
    s, d = SITE.search(sys), D0.search(sys)
    return f"{d.group(1)}-{s.group(1)}" if s and d else None


def serve(listen: tuple[str, int], upstream: tuple[str, int], log_path: str) -> None:
    lock = threading.Lock()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            return

        def _relay(self, method: str, body: bytes | None):
            c = http.client.HTTPConnection(*upstream, timeout=3600)
            c.request(method, self.path, body=body, headers={"Content-Type": "application/json"})
            return c.getresponse()

        def do_GET(self):
            r = self._relay("GET", None)
            data = r.read()
            self.send_response(r.status)
            self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            req = json.loads(body or b"{}")
            msgs = req.get("messages") or []
            t0 = time.time()
            r = self._relay("POST", body)
            self.send_response(r.status)
            self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
            self.end_headers()
            usage, finish = None, None
            while line := r.readline():
                self.wfile.write(line)
                self.wfile.flush()
                if line.startswith(b"data: {"):
                    ch = json.loads(line[6:])
                    usage = ch.get("usage") or usage
                    for c in ch.get("choices") or []:
                        finish = c.get("finish_reason") or finish
                elif line.startswith(b"{"):
                    ch = json.loads(line)
                    usage = ch.get("usage") or usage
                    finish = ((ch.get("choices") or [{}])[0]).get("finish_reason") or finish
            rec = {"t": t0, "s": round(time.time() - t0, 2), "key": session_key(msgs), "window": window(msgs),
                   "status": r.status,
                   "messages": len(msgs), "tools": len(req.get("tools") or []), "usage": usage, "finish": finish}
            with lock, open(log_path, "a") as f:
                f.write(json.dumps(rec) + "\n")

    ThreadingHTTPServer(listen, H).serve_forever()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--listen", required=True)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    lh, lp = a.listen.rsplit(":", 1)
    uh, up = a.upstream.rsplit(":", 1)
    serve((lh, int(lp)), (uh, int(up)), a.log)


if __name__ == "__main__":
    main()
