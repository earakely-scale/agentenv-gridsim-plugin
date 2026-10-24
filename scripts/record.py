"""Film an episode on the viewer: headless Chrome over the DevTools protocol drives window.gridsim frame by frame, each
frame a JPEG piped to ffmpeg for an H.264 MP4. --still writes one PNG at an hour, --thumb a 640x360 list thumbnail.

usage: python scripts/record.py --episode results/runs/reference/X.json --out cache/films/X.mp4 [--seconds 84]
       python scripts/record.py --episode E.json --still out.png --t 19.5 [--size 1920x1080]
       python scripts/record.py --episode E.json --thumb out.jpg
       python scripts/record.py --view levelup=results/runs/train/levelup.json --out levelup.mp4   (or race=...)
"""

import argparse
import base64
import functools
import io
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
WEB = "src/agentenv_gridsim/web"
CHROMES = ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "google-chrome", "chromium",
           "chromium-browser"]
ATTRIBUTION = ("Prices: ERCOT DAM settlement point prices (public). Not affiliated with or endorsed by ERCOT. "
               "Weather: IEM ASOS.")
RENDERER = ("(() => { const g = document.createElement('canvas').getContext('webgl2'); if (!g) return null; "
            "const x = g.getExtension('WEBGL_debug_renderer_info'); "
            "return x ? g.getParameter(x.UNMASKED_RENDERER_WEBGL) : 'webgl2'; })()")
ANSWER_SECONDS = 180
INTRO, DAY, OUTRO = 5.0, 72.0, 7.0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--episode", type=Path)
    p.add_argument("--view", help="A training view instead of an episode: levelup=MANIFEST or race=MANIFEST.")
    p.add_argument("--page",
                   help="Capture a page under the checkout instead, e.g. build/hub/space/index.html (with --still).")
    p.add_argument("--weather", type=Path, help="The weather sidecar (default cache/weather/DATE_POINT.json).")
    p.add_argument("--out", type=Path, help="An MP4 to write.")
    p.add_argument("--gif", type=Path, help="Also a GIF of the film (640 px wide, 10 fps).")
    p.add_argument("--still", type=Path, help="One PNG at --t.")
    p.add_argument("--thumb", type=Path, help="A 640x360 JPEG at the day's most telling hour.")
    p.add_argument("--t", type=float, default=19.5, help="Hour of the day for --still.")
    p.add_argument("--seconds", type=float, default=DAY, help="Seconds the 24 hours take in the film.")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--reduced", action="store_true", help="Reduced motion.")
    p.add_argument("--extra", default="", help="Extra query string for the viewer.")
    p.add_argument("--chrome")
    args = p.parse_args(argv)
    width, height = (int(v) for v in args.size.lower().split("x"))
    chrome = find_chrome(args.chrome)
    if args.page:
        with serve(ROOT) as port, session(f"http://127.0.0.1:{port}/{args.page}", chrome, width,
                                          height) as (page, _, gl):
            args.still.parent.mkdir(parents=True, exist_ok=True)
            args.still.write_bytes(base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"]))
            print(f"wrote {args.still} ({gl})")
        return 0
    if args.view:
        kind, manifest = args.view.split("=", 1)
        m = json.loads(Path(manifest).read_text())
        first = (m.get("frames") or m.get("lanes"))[0]["episode_id"]
        ep = json.loads((Path(manifest).parent / f"{first}.json").read_text())
    else:
        ep = json.loads(args.episode.read_text())
    wx = args.weather or weather_path(ep)
    with serve(ROOT) as port:
        url = (view_url(port, kind, Path(manifest), wx, args.reduced, args.extra) if args.view
               else viewer_url(port, args.episode, wx, args.reduced, args.extra))
        if args.thumb:
            width, height = 1280, 720
        with session(url, chrome, width, height) as (page, ready, gl):
            print(f"renderer: {gl}; shots: {[s['kind'] for s in ready['shots']]}")
            if args.still or args.thumb:
                t = args.t if args.still or args.t != 19.5 else telling_hour(ep)
                for w in (0, 1 / 30, 1 / 30):
                    page.js(f"gridsim.time({t}, {{dt: {w}}})")
                out = args.still or args.thumb
                out.parent.mkdir(parents=True, exist_ok=True)
                fmt = "png" if out.suffix == ".png" else "jpeg"
                quality = {"quality": 88} if fmt == "jpeg" else {}
                data = base64.b64decode(page.call("Page.captureScreenshot", format=fmt, **quality)["data"])
                if args.thumb:
                    from PIL import Image  # only thumbnails need Pillow, which the plugin's venv doesn't install

                    Image.open(io.BytesIO(data)).convert("RGB").resize((640, 360), Image.LANCZOS).save(out, quality=86)
                else:
                    out.write_bytes(data)
                print(f"wrote {out}")
            if args.out:
                film(page, args.out, args.fps, args.seconds, ep, ready.get("duration"))
                probe(args.out)
                if args.gif:
                    gif(args.out, args.gif)
    return 0


def weather_path(ep: dict) -> Path:
    """The cached sidecar an episode plays in (a v5 floor's also holds the day before)."""
    t = ep["task"]
    if ep.get("schema") == "gridsim.episode/v5":
        return ROOT / "cache" / "weather" / f"{t['date']}_{t['point']}_d1.json"
    return ROOT / "cache" / "weather" / f"{t['date']}_{t['settlement_point']}.json"


def telling_hour(ep: dict) -> float:
    if ep.get("schema") == "gridsim.episode/v5":
        hub = ep["clear"]["hub_usd"]
        return max(range(24), key=lambda h: hub[h]) + 0.55
    if ep.get("schema") == "gridsim.episode/v3":
        for n in sorted((n for n in ep["notices"] if n.get("deploy")), key=lambda n: n["deploy"]["start_min"]):
            if ep["hours"][min(23, n["deploy"]["start_min"] // 60)]["awards"].get(n["deploy"]["product"]):
                return n["deploy"]["start_min"] / 60 + 0.35
        rt = ep["task"]["rt"]
        return max(range(24), key=lambda h: rt[h]) + 0.5
    if ep.get("schema") == "gridsim.episode/v2":
        rt = ep["task"]["rt"]
        return (max(range(96), key=lambda i: rt[i]) + 1) / 4 + 0.1
    prices = ep["task"]["prices"]
    acts = ep.get("final_schedule") or [0] * 24
    best = max(range(24), key=lambda h: abs(prices[h]) * (1 + abs(acts[h])))
    return best + 0.5


def rel(p: Path) -> str:
    return "/" + quote(str(Path(os.path.abspath(p)).relative_to(ROOT)))


def view_url(port: int, kind: str, manifest: Path, weather: Path, reduced: bool, extra: str = "") -> str:
    return (f"http://127.0.0.1:{port}/{WEB}/index.html?record=1&{kind}={rel(manifest)}&weather={rel(weather)}"
            f"&reduced={1 if reduced else 0}{'&' + extra if extra else ''}")


def viewer_url(port: int, episode: Path, weather: Path, reduced: bool, extra: str = "") -> str:
    return (f"http://127.0.0.1:{port}/{WEB}/index.html?record=1&t=0&episode={rel(episode)}&weather={rel(weather)}"
            f"&reduced={1 if reduced else 0}{'&' + extra if extra else ''}")


def film(page, out: Path, fps: int, seconds: float, ep: dict, duration: float | None = None) -> None:
    """INTRO seconds before the day, the day at seconds per 24 h, OUTRO on the score; a training view plays its own
    duration in seconds. A v5 floor opens at 6 am the day before: its pre-day (t -6..0) takes three seconds a unit."""
    out.parent.mkdir(parents=True, exist_ok=True)
    start, intro = (-6.0, 18.0) if ep.get("schema") == "gridsim.episode/v5" else (-2.0, INTRO)
    total = duration or intro + seconds + OUTRO
    frames = round(total * fps)
    encoder = subprocess.Popen(ffmpeg_args(find("ffmpeg"), out, fps, ep["episode_id"]), stdin=subprocess.PIPE)
    t0 = time.monotonic()
    try:
        for i in range(frames):
            s = i / fps
            t = (s if duration else start - start * s / intro if s < intro else min(24.0, (s - intro) / seconds * 24)
                 if s < intro + seconds else 24 + (s - intro - seconds) / 4)
            page.js(f"gridsim.time({t:.5f}, {{dt: {1 / fps}}})")
            shot = page.call("Page.captureScreenshot", format="jpeg", quality=90)
            encoder.stdin.write(base64.b64decode(shot["data"]))
            if i % (fps * 5) == 0:
                print(f"  {i}/{frames} frames, {time.monotonic() - t0:.0f} s", flush=True)
    finally:
        encoder.stdin.close()
        encoder.wait()
    if encoder.returncode:
        raise SystemExit(f"ffmpeg exited {encoder.returncode}")


def gif(mp4: Path, out: Path, width: int = 640, fps: int = 10) -> None:
    """A palette GIF of the film; ordered dither keeps the terrain from bloating it."""
    f = f"fps={fps},scale={width}:-1:flags=lanczos"
    subprocess.run([find("ffmpeg"), "-v", "error", "-y", "-i", str(mp4), "-filter_complex",
                    f"[0:v]{f},split[a][b];[a]palettegen=max_colors=96:stats_mode=full[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=4", str(out)], check=True)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


def ffmpeg_args(ffmpeg: str, out: Path, fps: int, name: str) -> list[str]:
    return [ffmpeg, "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-c:v", "mjpeg", "-i", "-",
            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-vf", "scale=out_range=tv:out_color_matrix=bt709",
            "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
            "-movflags", "+faststart", "-metadata", f"title={name}", "-metadata", f"comment={ATTRIBUTION}", str(out)]


def probe(path: Path) -> None:
    info = json.loads(subprocess.run([find("ffprobe"), "-v", "error", "-show_entries",
                                      "stream=codec_name,width,height,nb_frames:format=duration,size", "-of", "json",
                                      str(path)], capture_output=True, text=True, check=True).stdout)
    s, f = info["streams"][0], info["format"]
    print(f"ffprobe {path.name}: {s['codec_name']} {s['width']}x{s['height']}, {s.get('nb_frames')} frames, "
          f"{float(f['duration']):.1f} s, {int(f['size']) / 1e6:.1f} MB")


@contextmanager
def serve(root: Path):
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield server.server_port
    finally:
        server.shutdown()


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.ids = itertools.count(1)
        self.events: list[dict] = []

    def call(self, method: str, **params) -> dict:
        i = next(self.ids)
        self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        try:
            while (message := json.loads(self.ws.recv(timeout=ANSWER_SECONDS))).get("id") != i:
                if "method" in message:
                    self.events.append(message)
        except TimeoutError as e:
            raise SystemExit(f"Chrome did not answer {method} in {ANSWER_SECONDS} s") from e
        if "error" in message:
            raise SystemExit(f"{method}: {message['error']}")
        return message["result"]

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            d = result["exceptionDetails"]
            raise SystemExit(f"{expression[:160]}: {d.get('exception', {}).get('description', d['text'])}")
        return result["result"].get("value")


def chrome_args(chrome: str, profile: Path, width: int, height: int) -> list[str]:
    return [chrome, "--headless=new", "--remote-debugging-port=0", f"--user-data-dir={profile}",
            f"--window-size={width},{height}", "--hide-scrollbars", "--mute-audio", "--no-first-run",
            "--disable-smooth-scrolling", "--force-device-scale-factor=1", "--enable-unsafe-swiftshader",
            "--ignore-gpu-blocklist", "about:blank"]


@contextmanager
def session(url: str, chrome: str, width: int, height: int, enable=("Runtime", "Log")):
    with tempfile.TemporaryDirectory() as profile:
        browser = subprocess.Popen(chrome_args(chrome, Path(profile), width, height), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
        try:
            with connect(devtools(Path(profile), browser), max_size=None) as ws:
                page = Page(ws)
                renderer = page.js(RENDERER)
                page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=1,
                          mobile=False)
                for domain in enable:
                    page.call(f"{domain}.enable")
                page.call("Page.navigate", url=url)
                page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.gridsim ? r() : "
                        "document.querySelector('.error') ? j(document.querySelector('.error').innerText) : "
                        "Date.now() - s > 60000 ? j('timeout') : setTimeout(f, 50); f(); })")
                ready = page.js("gridsim.ready")
                yield page, ready, renderer
        finally:
            browser.terminate()
            browser.wait()


def devtools(profile: Path, chrome: subprocess.Popen) -> str:
    port_file = profile / "DevToolsActivePort"
    deadline = time.monotonic() + 30
    while not port_file.is_file():
        if chrome.poll() is not None or time.monotonic() > deadline:
            raise SystemExit("Chrome did not start its DevTools server")
        time.sleep(0.05)
    port = port_file.read_text().split()[0]
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as r:
        return next(t["webSocketDebuggerUrl"] for t in json.load(r) if t["type"] == "page")


def find_chrome(path: str | None) -> str:
    for candidate in [path] if path else CHROMES:
        if candidate and (found := shutil.which(candidate) or (Path(candidate).is_file() and candidate)):
            return found
    raise SystemExit("no Chrome found: pass --chrome PATH")


def find(tool: str) -> str:
    if found := shutil.which(tool):
        return found
    raise SystemExit(f"no {tool} on PATH")


if __name__ == "__main__":
    sys.exit(main())
