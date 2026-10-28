"""The dataset card's hero GIF: a v3 replay filmed in the viewer, one still camera per shot, with the viewer's own place
card and news line, and the race against the references at the end.

Each shot holds one camera and the light of its middle hour while the clock, the battery and the line move, so a frame
differs from the one before only where something happens; pixels that move less than --hold levels keep the previous
frame's value, and each shot gets its own 256 colours. --space is a built viewer Space with the v3 replay: the previews
branch's build/hub/space, or a download of the Space earakely-scale/GridSimEnv-AgentEnv.

    .venv/bin/python scripts/hub_hero.py --space SPACE_DIR --out build/hub/hero/gridsim-hero.gif
"""

import argparse
import base64
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
EPISODE = "runs/hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150-0xqk8eef.json"
SHOTS = ((8.00, 8.90, 3.0, "establish"), (14.20, 15.10, 2.8, "ramp"), (16.00, 16.80, 3.2, "city"),
         (19.00, 19.30, 2.8, "deploy"), (20.10, 20.60, 2.8, "city"), (22.00, 23.00, 2.4, "establish"),
         (24.00, 24.30, 3.0, "high"))
CSS = (".ep .pnl, .ep .bulletins, .ep .timeline, .ep .back-link, .ep .intro, .ep .settings, .ep .drawer, .ep .attrib, "
       ".ep .right { display: none !important; } .ep .place .meta, .ep .place .plantrow, .ep .place .soc .bands "
       "{ display: none !important; } .ep .news { left: auto !important; right: var(--gap) !important; transform: none "
       "!important; max-width: 470px !important; white-space: normal !important; border-radius: 16px !important; } "
       ".ep .news span:last-child { overflow: visible !important; } .ep.endcard .right { display: flex !important; } "
       ".ep.endcard .right > :not(.race), .ep.endcard .right .race .score, .ep.endcard .news "
       "{ display: none !important; }")
SUN = ("(() => { const s = gridsim.stage.sky, u = s.update, a = s.sunAt; "
       "s.update = (t, w, x) => u(window.sunT ?? t, w, x); s.sunAt = (t) => a(window.sunT ?? t); })()")


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def film(space: Path, episode: str, frames: Path, size: tuple[int, int], scale: float, fps: int) -> list[int]:
    rec = module("record", "scripts/record.py")
    w, h = size
    counts = []
    with rec.serve(space) as port, tempfile.TemporaryDirectory() as profile:
        proc = subprocess.Popen(rec.chrome_args(rec.find_chrome(None), Path(profile), w, h), stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        try:
            with rec.connect(rec.devtools(Path(profile), proc), max_size=None) as ws:
                page = rec.Page(ws)
                page.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=scale,
                          mobile=False)
                page.call("Runtime.enable")
                page.call("Page.navigate", url=f"http://127.0.0.1:{port}/index.html?record=1&t=0&reduced=1&episode={episode}")
                page.js("new Promise((r, j) => { const s = Date.now(); const f = () => window.gridsim ? r() : "
                        "Date.now() - s > 90000 ? j('timeout') : setTimeout(f, 50); f(); })")
                page.js("gridsim.ready.then(() => document.fonts.ready).then(() => true)")
                page.js(f"document.head.insertAdjacentHTML('beforeend', {json.dumps(f'<style>{CSS}</style>')})")
                page.js(SUN)
                i = 0
                for t0, t1, seconds, kind in SHOTS:
                    n = round(seconds * fps)
                    page.js(f"gridsim.stage.force = {json.dumps(kind)}; window.sunT = {(t0 + t1) / 2}; "
                            f"document.querySelector('.ep').classList.toggle('endcard', {json.dumps(t0 >= 24)})")
                    for _ in range(3):
                        page.js(f"gridsim.time({t0}, {{dt: 0}})")
                    for k in range(n):
                        page.js(f"gridsim.time({t0 + (t1 - t0) * k / (n - 1):.5f}, {{dt: {1 / fps}}})")
                        png = base64.b64decode(page.call("Page.captureScreenshot", format="png")["data"])
                        (frames / f"f{i:05d}.png").write_bytes(png)
                        i += 1
                    counts.append(n)
        finally:
            proc.terminate()
            proc.wait()
    return counts


def held(frames: Path, start: int, n: int, w: int, h: int, hold: int) -> bytes:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-start_number", str(start), "-i", str(frames / "f%05d.png"),
                          "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    seq = np.frombuffer(raw, np.uint8).reshape(n, h, w, 3).copy()
    for k in range(1, n):
        move = np.abs(seq[k].astype(np.int16) - seq[k - 1]).max(axis=2) > hold
        seq[k][~move] = seq[k - 1][~move]
    return seq.tobytes()


def segment(raw: bytes, out: Path, w: int, h: int, fps: int) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r",
                    str(fps), "-i", "-", "-filter_complex",
                    "split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=2:"
                    "diff_mode=rectangle", str(out)], input=raw, check=True)


def blocks(b: bytes, i: int) -> int:
    while b[i]:
        i += b[i] + 1
    return i + 1


def frames_of(path: Path) -> list[bytes]:
    b = path.read_bytes()
    bits = b[10] & 7
    table = b[13:13 + 3 * 2 ** (bits + 1)]
    i, gce, out = 13 + len(table), b"", []
    while b[i] != 0x3B:
        if b[i] == 0x21:
            j = blocks(b, i + 2)
            gce = b[i:j] if b[i + 1] == 0xF9 else gce
            i = j
        else:
            desc = bytearray(b[i:i + 10])
            assert not desc[9] & 0x80
            desc[9] |= 0x80 | bits
            j = blocks(b, i + 11)
            out.append(gce + desc + table + b[i + 10:j])
            i, gce = j, b""
    return out


def join(parts: list[Path], out: Path, w: int, h: int) -> int:
    frames = [f for p in parts for f in frames_of(p)]
    head = b"GIF89a" + w.to_bytes(2, "little") + h.to_bytes(2, "little") + bytes([0x70, 0, 0])
    out.write_bytes(head + b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00" + b"".join(frames) + b"\x3b")
    return len(frames)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--space", type=Path, required=True, help="A built viewer Space with the v3 replay.")
    ap.add_argument("--episode", default=EPISODE)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--css-size", default="960x540", help="The viewer's CSS size; the GIF is this times --scale.")
    ap.add_argument("--scale", type=float, default=1.5)
    ap.add_argument("--fps", type=int, default=20)
    ap.add_argument("--hold", type=int, default=3)
    args = ap.parse_args()
    cw, ch = (int(v) for v in args.css_size.split("x"))
    w, h = round(cw * args.scale), round(ch * args.scale)
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp)
        counts = film(args.space, args.episode, frames, (cw, ch), args.scale, args.fps)
        parts, start = [], 0
        for k, n in enumerate(counts):
            parts.append(frames / f"shot{k}.gif")
            segment(held(frames, start, n, w, h, args.hold), parts[-1], w, h, args.fps)
            start += n
        args.out.parent.mkdir(parents=True, exist_ok=True)
        n = join(parts, args.out, w, h)
    print(f"{args.out}: {w}x{h}, {n} frames at {args.fps} fps, {n / args.fps:.1f} s, "
          f"{args.out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
