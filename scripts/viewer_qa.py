"""QA the replay viewer headlessly: stills across regions, light, weather and battery states (v1, v2, and v3 and v4
from the built Space; v4 rows name a task id, resolved through the Space's index) into a contact sheet, a check that
each page loads without console errors or off-host requests, and a full-day run that tracks frame time, GPU memory
counts and the JS heap.

usage: python scripts/viewer_qa.py --out DIR [--runs results/runs/reference] [--perf EPISODE]
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import ROOT, find_chrome, serve, session, viewer_url  # noqa: E402

R = "results/runs/reference/"
LIVE = "../live-reference/"
V3 = "../../../build/hub/space/runs/"
MATRIX = [
    ("west · noon · idle (negative price)", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 12.6, "establish"),
    ("west · dusk · discharge", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 20.3, "ramp"),
    ("west · dawn · charge", "dam-v1-2022-03-30-HB_WEST-2h-e-foresight-opt", 7.4, None),
    ("west · violation, then grey", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-flawed", 8.5, None),
    ("west · line toward Midland", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 15.5, "line"),
    ("panhandle · day", "dam-v1-2025-05-14-HB_PAN-1h-c-foresight-opt", 13.5, "establish"),
    ("panhandle · line", "dam-v1-2025-05-14-HB_PAN-1h-c-foresight-opt", 17.5, "line"),
    ("north · noon", "dam-v1-2025-02-20-LZ_NORTH-1h-v-foresight-opt", 12.5, "establish"),
    ("north · city at dusk", "dam-v1-2025-02-20-LZ_NORTH-1h-v-foresight-opt", 18.6, "city"),
    ("north · Uri snow", "dam-v1-2021-02-15-HB_NORTH-4h-f-foresight-opt", 10.5, "establish"),
    ("houston · day · refinery", "dam-v1-2023-08-26-LZ_HOUSTON-2h-j-foresight-opt", 15.5, "ramp"),
    ("houston · night · charge", "dam-v1-2023-08-26-LZ_HOUSTON-2h-j-foresight-opt", 23.5, "ramp"),
    ("houston · night skyline and refinery", "dam-v1-2023-08-26-LZ_HOUSTON-2h-j-foresight-opt", 21.6, "city"),
    ("houston · thunderstorm", "dam-v1-2024-05-16-HB_HOUSTON-1h-z-foresight-opt", 19.2, "ramp"),
    ("houston · snow and fog", "dam-v1-2025-01-21-LZ_HOUSTON-2h-v-foresight-opt", 9.5, "establish"),
    ("south · afternoon", "dam-v1-2025-07-29-LZ_CPS-2h-o-foresight-opt", 16.5, "ramp"),
    ("central · hill country", "dam-v1-2025-08-11-LZ_AEN-4h-v-foresight-opt", 10.5, "establish"),
    ("central · night", "dam-v1-2025-08-11-LZ_AEN-4h-v-foresight-opt", 21.5, "city"),
    ("blind · before the day", "dam-v1-2021-02-14-HB_WEST-2h-p-blind-persist", -1.0, None),
    ("end · score and penalty bill", "dam-v1-2024-04-10-HB_WEST-1h-q-foresight-short", 24.5, None),
    ("v2 · the day before: DA position", f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-roll", -1.0, None),
    ("v2 · morning watch, ERCOT Watch", f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-roll", 10.2, None),
    ("v2 · EEA2 and the real-time spike", f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-roll", 19.75, None),
    ("v2 · naive holds through the spike", f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-naive", 19.75,
     "establish"),
    ("v2 · derate clips the frozen plan", f"{LIVE}live-v2-2024-01-02-LZ_CPS-1h-y-derate-foresight-roll", 18.6, None),
    ("v2 · Uri, re-planning in the freeze", f"{LIVE}live-v2-2021-02-15-HB_HOUSTON-2h-i-foresight-roll", 7.6, None),
    ("v2 · end score", f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-roll", 24.5, None),
    ("v3 · the day before: the day-ahead book", f"{V3}8bb20ee94689d6d1", -1.0, None),
    ("v3 · noon solar peak", f"{V3}8bb20ee94689d6d1", 12.6, "solar"),
    ("v3 · the meter holds headroom for ECRS", f"{V3}8bb20ee94689d6d1", 9.5, "poi"),
    ("v3 · negative price: panels stowed", f"{V3}62d7779181dafa09", 11.5, "stow"),
    ("v3 · evening discharge with ECRS reserved", f"{V3}bf8e0cd185d70bde", 18.5, None),
    ("v3 · ECRS deployed: the band drains", f"{V3}8bb20ee94689d6d1", 17.45, None),
    ("v3 · AS-hog: failures to provide", f"{V3}0c85533ede822715", 8.6, None),
    ("v3 · Sunset EEA, energy tier", f"{V3}8b2c0b970fb5813b", 19.6, None),
    ("v3 · RTC+B as T2, January", f"{V3}fe6271215e91838d", 10.5, None),
    ("v3 · aerial over the array", f"{V3}57253e9887c8bed7", 9.5, "array"),
    ("v3 · night", f"{V3}8bb20ee94689d6d1", 22.5, None),
    ("v3 · end score", f"{V3}0c85533ede822715", 24.5, None),
    ("v3 · phone layout", f"{V3}8bb20ee94689d6d1", 17.45, None, "390x844"),
    ("v4 · the window opens: the first DAM gate", "v4:2023-08-24-HB_HOUSTON", -13.7, None),
    ("v4 · a cold front's shelf cloud, DFW", "v4:2025-02-18-HB_NORTH", 10.6, "front"),
    ("v4 · the front through: 45 to 25 °F in an hour", "v4:2022-12-22-HB_NORTH", 9.4, None),
    ("v4 · frost on the panels at sunrise", "v4:2022-12-22-HB_NORTH", 32.2, "frost"),
    ("v4 · snow on the plant", "v4:2025-02-18-HB_NORTH", 38.5, "establish"),
    ("v4 · day 1's DAM results at 2 pm", "v4:2023-08-24-HB_HOUSTON", 14.15, None),
    ("v4 · the evening peak, reserves deployed", "v4:2023-08-24-HB_HOUSTON", 43.6, None),
    ("v4 · hard-freeze night", "v4:2022-12-22-HB_NORTH", 21.5, None),
    ("v4 · Panhandle front at night, turbines", "v4:2022-03-29-HB_PAN", 26.8, "line"),
    ("v4 · pinned to a watch: what it read", "v4:2022-12-22-HB_NORTH", 30.5, "fan=load&fanw=9"),
    ("v4 · charts", "v4:2022-12-22-HB_NORTH", 30.5, "charts=1"),
    ("v4 · end of the window: the score", "v4:2023-08-24-HB_HOUSTON", 72.6, None),
    ("v4 · reduced motion", "v4:2025-02-18-HB_NORTH", 11.6, "reduced=1"),
    ("v4 · phone layout", "v4:2022-12-22-HB_NORTH", 9.2, None, "390x844"),
]
QUIET = ("favicon",)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--only", help="Substring of the labels to render.")
    p.add_argument("--perf", help="Episode id for the full-day frame-time and memory run.")
    p.add_argument("--size", default="1920x1080")
    p.add_argument("--determinism", action="store_true",
                   help="Render a v1 and a v2 frame in two fresh sessions each; the PNGs must be byte-identical.")
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in args.size.split("x"))
    chrome = find_chrome(None)
    stills, failures = [], []
    with serve(ROOT) as port:
        for label, eid, t, shot, *size in MATRIX:
            if args.only and args.only not in label:
                continue
            ep = episode(eid)
            e = json.loads(ep.read_text())
            wx = sidecar(e)
            url = viewer_url(port, ep, wx, False, extra(shot))
            sw, sh = (int(v) for v in size[0].split("x")) if size else (w, h)
            with session(url, chrome, sw, sh, enable=("Runtime", "Log", "Network")) as (page, ready, gl):
                for dt in (0, 1 / 30, 1 / 30):
                    page.js(f"gridsim.time({t}, {{dt: {dt}}})")
                png = base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"])
                name = label.split(" · ")[0] + "-" + str(len(stills)) + ".png"
                (args.out / name).write_bytes(png)
                stills.append((label, args.out / name))
                for ev in page.events:
                    m = ev.get("method")
                    logged = m == "Log.entryAdded" and ev["params"]["entry"]["level"] == "error"
                    console = m == "Runtime.consoleAPICalled" and ev["params"]["type"] in ("error", "warn")
                    if m == "Runtime.exceptionThrown" or logged or (console and "toNonIndexed" not in json.dumps(ev)):
                        text = json.dumps(ev["params"])[:300]
                        if not any(q in text for q in QUIET):
                            failures.append(f"{label}: {text}")
                    if m == "Network.requestWillBeSent":
                        u = ev["params"]["request"]["url"]
                        if not u.startswith(("http://127.0.0.1", "data:", "blob:")):
                            failures.append(f"{label}: off-host request {u}")
                print(f"{label}: ok ({gl})")
        if args.perf:
            ep = episode(args.perf)
            e = json.loads(ep.read_text())
            wx = sidecar(e)
            with session(viewer_url(port, ep, wx, False), chrome, w, h) as (page, _, gl):
                rows = []
                t0, span = (-14, 24 * e["task"]["days"] + 16) if "d1" in e["task"] else (-2, 26)
                for i in range(0, 2161):
                    t = t0 + i * span / 2160
                    page.js(f"gridsim.time({t:.4f}, {{dt: 1 / 30}})")
                    if i % 216 == 0:
                        rows.append(page.js("({...gridsim.state(), heap: performance.memory ? "
                                            "performance.memory.usedJSHeapSize / 1e6 : null})"))
                (args.out / "perf.json").write_text(json.dumps(rows, indent=1))
                for r in rows:
                    print(f"t={r['t']:.1f} shot={r['shot']} p50={r['frameMsP50']:.1f}ms p95={r['frameMsP95']:.1f}ms "
                          f"calls={r['calls']} tris={r['tris']} geo={r['geometries']} tex={r['textures']} "
                          f"heap={r['heap']:.0f}MB")
        if args.determinism:
            for eid, t in (("dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 20.3),
                           (f"{LIVE}live-v2-2023-09-06-HB_NORTH-2h-l-foresight-roll", 19.75),
                           (f"{V3}8bb20ee94689d6d1", 17.45), (f"{V3}62d7779181dafa09", 11.5),
                           ("v4:2022-12-22-HB_NORTH", 9.4), ("v4:2025-02-18-HB_NORTH", 10.6)):
                ep = episode(eid)
                e = json.loads(ep.read_text())
                wx = sidecar(e)
                pngs = []
                for _ in range(2):
                    with session(viewer_url(port, ep, wx, False), chrome, w, h) as (page, _, _gl):
                        for dt in (0, 1 / 30, 1 / 30):
                            page.js(f"gridsim.time({t}, {{dt: {dt}}})")
                        pngs.append(base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"]))
                same = pngs[0] == pngs[1]
                print(f"determinism {Path(eid).name} t={t}: {'identical' if same else 'DIFFERENT'}")
                if not same:
                    failures.append(f"determinism: {eid} at {t} differs between sessions")
    if stills:
        sheet(stills, args.out / "qa-contact.jpg")
    for f in failures:
        print("FAIL", f)
    print(f"{len(stills)} stills, {len(failures)} failures -> {args.out / 'qa-contact.jpg'}")
    return 1 if failures else 0


def episode(eid: str) -> Path:
    if eid.startswith("v4:"):
        space = ROOT / "build" / "hub" / "space" / "runs"
        index = json.loads((space / "index.json").read_text())["episodes"]
        hit = next(e for e in index if e["version"] == "v4" and eid[3:] in e["task_id"] and e["tier"] == "front")
        return space / hit["url"]
    return ROOT / os.path.normpath(f"{R}{eid}.json")


def sidecar(e: dict) -> Path:
    t = e["task"]
    name = f"{t['d1']}_{t['settlement_point']}_{t['days']}d" if "d1" in t else f"{t['date']}_{t['settlement_point']}"
    return ROOT / "cache" / "weather" / f"{name}.json"


def extra(shot: str | None) -> str:
    return "" if not shot else shot if "=" in shot else f"shot={shot}"


def sheet(stills, out: Path, cols: int = 3, tw: int = 640, th: int = 360) -> None:
    rows = (len(stills) + cols - 1) // cols
    im = Image.new("RGB", (cols * tw, rows * (th + 26)), "#f4f3ef")
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 17)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, path) in enumerate(stills):
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        src = Image.open(path).convert("RGB")
        k = min(tw / src.width, th / src.height)
        fit = src.resize((round(src.width * k), round(src.height * k)), Image.LANCZOS)
        im.paste(fit, (x + (tw - fit.width) // 2, y + 26 + (th - fit.height) // 2))
        d.text((x + 8, y + 4), label, fill="#1c2329", font=font)
    im.save(out, quality=86)


if __name__ == "__main__":
    sys.exit(main())
