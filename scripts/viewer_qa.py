"""QA the replay viewer headlessly: stills across regions, light, weather and battery states into a contact sheet, a
check that each page loads without console errors or off-host requests, and a full-day run that tracks frame time,
GPU memory counts and the JS heap.

usage: python scripts/viewer_qa.py --out DIR [--runs results/runs/reference] [--perf EPISODE]
"""

import argparse
import base64
import io
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from record import ROOT, find_chrome, serve, session, viewer_url  # noqa: E402

R = "results/runs/reference/"
MATRIX = [
    ("west · noon · idle (negative price)", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 12.6, "establish"),
    ("west · dusk · discharge", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-opt", 20.3, "ramp"),
    ("west · dawn · charge", "dam-v1-2022-03-30-HB_WEST-2h-e-foresight-opt", 7.4, None),
    ("west · violation, then grey", "dam-v1-2025-03-15-HB_WEST-1h-t-foresight-flawed", 8.5, None),
    ("panhandle · day", "dam-v1-2025-05-14-HB_PAN-1h-c-foresight-opt", 13.5, "establish"),
    ("panhandle · line", "dam-v1-2025-05-14-HB_PAN-1h-c-foresight-opt", 17.5, "line"),
    ("north · noon", "dam-v1-2025-02-20-LZ_NORTH-1h-v-foresight-opt", 12.5, "establish"),
    ("north · city at dusk", "dam-v1-2025-02-20-LZ_NORTH-1h-v-foresight-opt", 18.6, "city"),
    ("north · Uri snow", "dam-v1-2021-02-15-HB_NORTH-4h-f-foresight-opt", 10.5, "establish"),
    ("houston · day · refinery", "dam-v1-2023-08-26-LZ_HOUSTON-2h-j-foresight-opt", 15.5, "ramp"),
    ("houston · night · charge", "dam-v1-2023-08-26-LZ_HOUSTON-2h-j-foresight-opt", 23.5, "ramp"),
    ("houston · thunderstorm", "dam-v1-2024-05-16-HB_HOUSTON-1h-z-foresight-opt", 19.2, "ramp"),
    ("houston · snow and fog", "dam-v1-2025-01-21-LZ_HOUSTON-2h-v-foresight-opt", 9.5, "establish"),
    ("south · afternoon", "dam-v1-2025-07-29-LZ_CPS-2h-o-foresight-opt", 16.5, "ramp"),
    ("central · hill country", "dam-v1-2025-08-11-LZ_AEN-4h-v-foresight-opt", 10.5, "establish"),
    ("central · night", "dam-v1-2025-08-11-LZ_AEN-4h-v-foresight-opt", 21.5, "city"),
    ("blind · before the day", "dam-v1-2021-02-14-HB_WEST-2h-p-blind-persist", -1.0, None),
    ("end · score and penalty bill", "dam-v1-2024-04-10-HB_WEST-1h-q-foresight-short", 24.5, None),
]
QUIET = ("favicon",)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--only", help="Substring of the labels to render.")
    p.add_argument("--perf", help="Episode id for the full-day frame-time and memory run.")
    p.add_argument("--size", default="1920x1080")
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in args.size.split("x"))
    chrome = find_chrome(None)
    stills, failures = [], []
    with serve(ROOT) as port:
        for label, eid, t, shot in MATRIX:
            if args.only and args.only not in label:
                continue
            ep = ROOT / f"{R}{eid}.json"
            e = json.loads(ep.read_text())
            wx = ROOT / "cache" / "weather" / f"{e['task']['date']}_{e['task']['settlement_point']}.json"
            url = viewer_url(port, ep, wx, False, f"shot={shot}" if shot else "")
            with session(url, chrome, w, h, enable=("Runtime", "Log", "Network")) as (page, ready, gl):
                for dt in (0, 1 / 30, 1 / 30):
                    page.js(f"gridsim.time({t}, {{dt: {dt}}})")
                png = base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"])
                name = label.split(" · ")[0] + "-" + str(len(stills)) + ".png"
                (args.out / name).write_bytes(png)
                stills.append((label, args.out / name))
                for ev in page.events:
                    m = ev.get("method")
                    if m == "Runtime.exceptionThrown" or (m == "Log.entryAdded" and ev["params"]["entry"]["level"] == "error"):
                        text = json.dumps(ev["params"])[:300]
                        if not any(q in text for q in QUIET):
                            failures.append(f"{label}: {text}")
                    if m == "Network.requestWillBeSent":
                        u = ev["params"]["request"]["url"]
                        if not u.startswith(("http://127.0.0.1", "data:", "blob:")):
                            failures.append(f"{label}: off-host request {u}")
                print(f"{label}: ok ({gl})")
        if args.perf:
            ep = ROOT / f"{R}{args.perf}.json"
            e = json.loads(ep.read_text())
            wx = ROOT / "cache" / "weather" / f"{e['task']['date']}_{e['task']['settlement_point']}.json"
            with session(viewer_url(port, ep, wx, False), chrome, w, h) as (page, _, gl):
                rows = []
                for i in range(0, 2161):
                    t = -2 + i * 26 / 2160
                    page.js(f"gridsim.time({t:.4f}, {{dt: 1 / 30}})")
                    if i % 216 == 0:
                        rows.append(page.js("({...gridsim.state(), heap: performance.memory ? performance.memory.usedJSHeapSize / 1e6 : null})"))
                (args.out / "perf.json").write_text(json.dumps(rows, indent=1))
                for r in rows:
                    print(f"t={r['t']:.1f} shot={r['shot']} p50={r['frameMsP50']:.1f}ms p95={r['frameMsP95']:.1f}ms "
                          f"calls={r['calls']} tris={r['tris']} geo={r['geometries']} tex={r['textures']} heap={r['heap']:.0f}MB")
    if stills:
        sheet(stills, args.out / "qa-contact.jpg")
    for f in failures:
        print("FAIL", f)
    print(f"{len(stills)} stills, {len(failures)} failures -> {args.out / 'qa-contact.jpg'}")
    return 1 if failures else 0


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
        im.paste(Image.open(path).convert("RGB").resize((tw, th), Image.LANCZOS), (x, y + 26))
        d.text((x + 8, y + 4), label, fill="#1c2329", font=font)
    im.save(out, quality=86)


if __name__ == "__main__":
    sys.exit(main())
