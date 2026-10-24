"""Polite cached HTTP for the notice scrapers: one request per `delay` seconds per host, a named user agent, raw bytes
cached under cache/raw/notices/ so a re-run makes no requests."""

from __future__ import annotations

import hashlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "cache" / "raw" / "notices"
UA = ("ScaleAI-GridSimEnv-research/0.1 (+https://github.com/earakely-scale/agentenv-gridsim-plugin; "
      "edgar.arakelyan@scale.com)")
_last: dict[str, float] = {}


def cache_path(url: str, sub: str) -> Path:
    u = urllib.parse.urlsplit(url)
    stem = (u.path.strip("/").replace("/", "_") + ("_" + u.query if u.query else ""))[-120:]
    stem = "".join(c if c.isalnum() or c in "-_.=&" else "_" for c in stem)
    return CACHE / sub / f"{stem}_{hashlib.sha1(url.encode()).hexdigest()[:10]}"


def fetch(url: str, sub: str, *, delay: float = 1.0, retries: int = 4) -> tuple[bytes | None, Path, bool]:
    """(body, cache file, fetched_now). body is None on a 404 (cached as a .404 marker)."""
    p = cache_path(url, sub)
    if p.exists():
        return p.read_bytes(), p, False
    if p.with_suffix(".404").exists():
        return None, p, False
    p.parent.mkdir(parents=True, exist_ok=True)
    host = urllib.parse.urlsplit(url).netloc
    for attempt in range(retries):
        wait = _last.get(host, 0) + delay - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                body = r.read()
            p.write_bytes(body)
            return body, p, True
        except urllib.error.HTTPError as e:
            if e.code == 404:
                p.with_suffix(".404").write_text(url)
                return None, p, True
            if e.code not in (429, 500, 502, 503, 504):
                raise
            print(f"HTTP {e.code} on {url}; backing off", file=sys.stderr, flush=True)
            time.sleep(10 * 2**attempt)
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            time.sleep(10 * 2**attempt)
    raise RuntimeError(f"gave up on {url}")
