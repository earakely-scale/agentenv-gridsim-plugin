"""`agent-env gridsim view`: the GridSim viewer (src/agentenv_gridsim/web) served read-only on loopback, with the
Episode JSON under a runs folder and the weather sidecars: the viewer at /web/, every episode at /runs/<path>, their
index at /runs/index.json and the sidecars at /weather/<date>_<point>.json; an episode plays at
/web/index.html?episode=/runs/<path>&wxbase=/weather."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

import click

from .sweep import RUNS

WEB = Path(__file__).resolve().parent / "web"
WEATHER = Path("cache/weather")
SCHEMA = "gridsim.episode/v1"
TYPES = {".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8", ".json": "application/json",
         ".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp", ".svg": "image/svg+xml",
         ".glb": "model/gltf-binary", ".hdr": "application/octet-stream", ".mp4": "video/mp4",
         ".gz": "application/gzip"}
NOT_FOUND = (404, {"Content-Type": "text/plain"}, b"not found")

Response = tuple[int, dict[str, str], bytes]


def index(runs: Path) -> list[dict]:
    """Every Episode JSON under ``runs``, by its path there, with what a list of episodes shows."""
    out = []
    for path in sorted(runs.rglob("*.json")):
        try:
            e = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(e, dict) or e.get("schema") != SCHEMA:
            continue
        task = e.get("task") or {}
        out.append({"path": path.relative_to(runs).as_posix(), "episode_id": e.get("episode_id"),
                    "task_id": e.get("task_id"), "tier": e.get("tier"), "bundle": e.get("bundle"),
                    "path_kind": e.get("path"), "model": e.get("model"), "reward": e.get("reward"),
                    "r_opt": e.get("r_opt"), "profit_usd": e.get("profit_usd"), "date": task.get("date"),
                    "settlement_point": task.get("settlement_point"), "region": task.get("region")})
    return out


def _file(root: Path, name: str) -> Response:
    root = root.resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        return NOT_FOUND
    return 200, {"Content-Type": TYPES.get(path.suffix, "application/octet-stream")}, path.read_bytes()


def episode_url(path: str) -> str:
    return f"/web/index.html?episode=/runs/{quote(path)}&wxbase=/weather"


def route(runs: Path, path: str, weather: Path = WEATHER) -> Response:
    url = urlsplit(path)
    parts = [unquote(p) for p in url.path.split("/") if p]
    if url.path in ("/", "/web", "/web/"):
        return 302, {"Location": "/web/index.html"}, b""
    match parts:
        case ["web", *rest]:
            return _file(WEB, "/".join(rest))
        case ["runs", "index.json"]:
            return 200, {"Content-Type": "application/json"}, json.dumps(index(runs)).encode()
        case ["runs", *rest]:
            return _file(runs, "/".join(rest))
        case ["weather", name]:
            return _file(weather, name)
    return NOT_FOUND


def serve(runs: Path, port: int, host: str = "127.0.0.1", weather: Path = WEATHER) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = route(runs, self.path, weather)
            self.send_response(status)
            for key, value in (headers | {"Cache-Control": "no-cache", "Content-Length": str(len(body))}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)


@click.command("view")
@click.option("--runs", type=click.Path(file_okay=False, path_type=Path), default=RUNS, show_default=True,
              help="The folder of Episode JSON to serve: `agent-env gridsim episodes` writes them under it.")
@click.option("--weather", type=click.Path(file_okay=False, path_type=Path), default=WEATHER, show_default=True,
              help="The weather sidecars (<date>_<point>.json) the viewer lights and dresses each day with.")
@click.option("--port", default=8239, show_default=True, help="Port to serve on.")
@click.option("--host", default="127.0.0.1", show_default=True,
              help="Address to serve on: 0.0.0.0 for every interface, as in a container or a Space.")
def view_command(runs: Path, weather: Path, port: int, host: str):
    """Serve the GridSim viewer on the Episode JSON under --runs: the battery yard in that day's light and weather,
    the plain-English card, and the expert charts behind a toggle."""
    if not (WEB / "index.html").is_file():
        raise click.UsageError(f"no viewer at {WEB}: this install has no src/agentenv_gridsim/web")
    found = index(runs) if runs.is_dir() else []
    if not found:
        raise click.UsageError(f"no Episode JSON under {runs}: run `agent-env gridsim episodes` first")
    try:
        server = serve(runs, port, host, weather)
    except OSError as e:
        raise click.UsageError(f"can't serve on port {port} ({e.strerror}): pass another --port") from e
    base = f"http://{host}:{server.server_port}"
    click.echo(f"Serving {len(found)} episodes from {runs} at {base}/web/ (Ctrl-C to stop); the first plays at "
               f"{base}{episode_url(found[0]['path'])}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
