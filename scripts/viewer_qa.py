"""QA the replay viewer headlessly: stills across regions, light, weather and battery states (v1, v2, and v3, v4 and v5
from the built Space; v4 and v5 rows name a task and a model, resolved through the Space's index) into a contact sheet,
a check that each page loads without console errors or off-host requests, and a full-day run that tracks frame time,
GPU memory counts and the JS heap.

usage: python scripts/viewer_qa.py --out DIR [--only LABEL] [--perf EPISODE] [--determinism]
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import ROOT, find_chrome, serve, session, viewer_url, weather_path  # noqa: E402

R = "results/runs/reference/"
LIVE = "../live-reference/"
V3 = "../../../build/hub/space/runs/"
V3_SOL = "hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150-1x0k609v"
V4 = {"fern": "v4:2026-01-24-HB_NORTH:rolling-p50:front", "heather": "v4:2024-01-14-HB_NORTH:rolling-p50:front",
      "uri": "v4:2021-02-13-HB_HOUSTON:rolling-p50:front", "spring": "v4:2024-03-28-HB_WEST:rolling-p50:front",
      "pan": "v4:2025-10-19-HB_PAN:rolling-p50:front", "storm": "v4:2025-04-02-LZ_RAYBN:gpt-6.1-sol:front",
      "sol": "v4:2026-01-24-HB_NORTH:gpt-6.1-sol:front"}
V5 = {"hedged": "v5:2024-08-20-A800x2:anchor-hedged:floor-day", "withhold": "v5:2025-05-20:max-withhold:floor-day",
      "sprint": "v5:2024-08-20-A800x2:disclosure-anchor:floor-sprint",
      "july": "v5:2025-07-30:disclosure-anchor:floor-day", "sol": "v5:2024-08-20-A800x2:gpt-6.1-sol:floor-day"}
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
    ("v3 · the day before: the day-ahead book", f"{V3}5a642a2295c50ed7", -1.0, None),
    ("v3 · noon solar peak", f"{V3}5a642a2295c50ed7", 12.6, "solar"),
    ("v3 · the meter holds headroom for ECRS", f"{V3}5a642a2295c50ed7", 9.5, "poi"),
    ("v3 · negative price: panels stowed", f"{V3}2346944264970b1d", 11.5, "stow"),
    ("v3 · late-afternoon discharge with ECRS reserved", f"{V3}f14206b2ec7970ae", 16.5, None),
    ("v3 · oversized site: the meter clips the PV", f"{V3}52a2ac2c6fcae71e", 12.6, "poi"),
    ("v3 · ECRS deployed: the band drains", f"{V3}5a642a2295c50ed7", 17.45, None),
    ("v3 · AS-hog: failures to provide", f"{V3}e404f193e182a3c3", 8.6, None),
    ("v3 · Sunset EEA, energy tier", f"{V3}8b2c0b970fb5813b", 19.6, None),
    ("v3 · RTC+B as T2, January", f"{V3}c1ba1700279f89aa", 10.5, None),
    ("v3 · aerial over the array", f"{V3}f99c37e0cf969880", 9.5, "array"),
    ("v3 · night", f"{V3}5a642a2295c50ed7", 22.5, None),
    ("v3 · end score", f"{V3}e404f193e182a3c3", 24.5, None),
    ("v3 · GPT-6.1 Sol, 10 August 2023: its ECRS is called", f"{V3}{V3_SOL}", 15.85, None),
    ("v3 · GPT-6.1 Sol, 10 August 2023: the score", f"{V3}{V3_SOL}", 24.5, None),
    ("v3 · phone layout", f"{V3}5a642a2295c50ed7", 17.45, None, "390x844"),
    ("v4 · Fern: the window opens at the first DAM gate", V4["fern"], -13.7, None),
    ("v4 · Heather: the Arctic front reaches DFW", V4["heather"], -7.4, "front"),
    ("v4 · Heather: the front through, 14 °C in three hours", V4["heather"], -6.9, None),
    ("v4 · Heather: frost on the panels at sunrise", V4["heather"], 7.2, "frost"),
    ("v4 · Fern: snow on the plant", V4["fern"], 8.0, "establish"),
    ("v4 · Fern: day 1's DAM results at 2 pm", V4["fern"], 14.15, None),
    ("v4 · Uri: reserves deployed in the load shed", V4["uri"], 51.8, None),
    ("v4 · Uri: hard-freeze night", V4["uri"], 50.5, None),
    ("v4 · Panhandle front at night, turbines", V4["pan"], 43.9, "line"),
    ("v4 · East Texas thunderstorm", V4["storm"], 63.3, "establish"),
    ("v4 · Spring: calm, negative prices at noon", V4["spring"], 12.5, None),
    ("v4 · pinned to a watch: what it read", V4["fern"], 30.5, "fan=load&fanw=9"),
    ("v4 · charts", V4["fern"], 30.5, "charts=1"),
    ("v4 · GPT-6.1 Sol in Fern, the top RT hour", V4["sol"], 42.6, None),
    ("v4 · GPT-6.1 Sol in Fern, the score", V4["sol"], 72.6, None),
    ("v4 · reduced motion", V4["heather"], 11.6, "reduced=1"),
    ("v4 · phone layout", V4["fern"], 9.2, None, "390x844"),
    ("v5 · 6 am, the trading floor opens", V5["hedged"], -5.75, "room"),
    ("v5 · 9:15, morning sun through the east glass", V5["hedged"], -4.62, "window"),
    ("v5 · seat A's desk: the offer ladder", V5["hedged"], -4.45, "desk"),
    ("v5 · the CfD on the turret", V5["hedged"], -4.1, "deal"),
    ("v5 · 10:00, the DAM closes", V5["hedged"], -3.47, "clock"),
    ("v5 · 1:30 pm, the merit order at the peak", V5["hedged"], -1.7, "merit"),
    ("v5 · the day's prices and awards", V5["hedged"], -0.9, "prices"),
    ("v5 · 3:30 am, seat A charges", V5["hedged"], 3.5, "push"),
    ("v5 · 2 pm, gas-G's peakers running", V5["hedged"], 14.0, "gas"),
    ("v5 · 12:30 pm, renew-R's trackers", V5["hedged"], 12.5, "solar"),
    ("v5 · the rival's yard", V5["hedged"], 15.5, "byard"),
    ("v5 · renew-R's wind farm", V5["hedged"], 17.5, "wind"),
    ("v5 · 7 pm peak, discharging toward Austin", V5["hedged"], 19.5, "ramp"),
    ("v5 · Austin at the peak", V5["hedged"], 20.2, "city"),
    ("v5 · the market monitor mitigates seat A", V5["withhold"], 17.5, None),
    ("v5 · the desk at the 6 pm watch", V5["hedged"], 18.2, "desk"),
    ("v5 · end score", V5["hedged"], 24.5, None),
    ("v5 · floor-sprint, the awards", V5["sprint"], -1.0, None),
    ("v5 · July 2025, the evening peak", V5["july"], 19.6, None),
    ("v5 · GPT-6.1 Sol at the desk", V5["sol"], -4.45, "desk"),
    ("v5 · GPT-6.1 Sol's operating day, the peak", V5["sol"], 19.5, None),
    ("v5 · charts drawer", V5["hedged"], 20.0, "charts=1"),
    ("v5 · reduced motion", V5["hedged"], 11.2, "reduced=1"),
    ("v5 · phone layout", V5["hedged"], -4.45, None, "390x844"),
    ("v5 · phone, operating day", V5["hedged"], 19.5, None, "390x844"),
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
            wx = weather_path(e)
            raw = shot and "=" in shot
            url = viewer_url(port, ep, wx, raw and shot == "reduced=1", (shot if raw and shot != "reduced=1" else "")
                             if raw else f"shot={shot}" if shot else "")
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
            wx = weather_path(e)
            with session(viewer_url(port, ep, wx, False), chrome, w, h) as (page, _, gl):
                rows = []
                t0, span = ((-14, len(e["hours"]) + 16) if e.get("schema") == "gridsim.episode/v4"
                            else (-6, 30) if e.get("schema") == "gridsim.episode/v5" else (-2, 26))
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
                           (f"{V3}5a642a2295c50ed7", 17.45), (f"{V3}2346944264970b1d", 11.5),
                           (V4["heather"], -6.9), (V4["fern"], 8.0),
                           (V5["hedged"], -4.45), (V5["hedged"], 19.5)):
                ep = episode(eid)
                e = json.loads(ep.read_text())
                wx = weather_path(e)
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
    if eid.startswith(("v4:", "v5:")):
        space = ROOT / "build" / "hub" / "space" / "runs"
        index = json.loads((space / "index.json").read_text())["episodes"]
        version, task, *rest = eid.split(":")
        model, tier = rest or ("", "front")
        hit = next(e for e in index if e["version"] == version and task in e["task_id"] and e["tier"] == tier
                   and model in e["model"])
        return space / hit["url"]
    return ROOT / os.path.normpath(f"{R}{eid}.json")


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
