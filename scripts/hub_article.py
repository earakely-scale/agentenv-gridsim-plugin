"""The GridSimEnv article: a research-article Space built with tfrere's research-article-template (Astro, MDX chapters,
D3 embeds) under hub/article. It opens on what is in the environment: a recorded benchmark run filmed on the 3D viewer
(scripts/hub_desk_film.py), then the real operator against the agents on the windows where they most clearly beat it,
read from results/desk-v4-bench, its episodes and the desk-v4-bench pack. The prose states no number of its own: it
reads them from facts.json, which this script formats from summary.json, the grades and the episodes, and the front
matter's description is the dataset card's pitch.

    .venv/bin/python scripts/hub_desk_film.py --out hub/article/app/public/media/gridsim-run.gif   # the film, once
    .venv/bin/python scripts/hub_article.py             # the data, the numbers check, the scans
    .venv/bin/python scripts/hub_article.py --build     # then npm ci (once) and npm run build
    .venv/bin/python scripts/hub_article.py --publish   # then upload hub/article to the Space

The film is uploaded with the Space, not committed (hub/article/app/public/media is ignored).
"""

import argparse
import gzip
import importlib.util
import json
import re
import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np
from agentenv_hf.scan import known_values, scan

ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "hub" / "article"
APP = ARTICLE / "app"
DATA = APP / "src" / "content" / "assets" / "data"
CHAPTERS = APP / "src" / "content" / "chapters"
MEDIA = APP / "public" / "media"
FILM = MEDIA / "gridsim-run.gif"
FILM_MB = 12
SPACE = "earakely-scale/GridSimEnv"
MDX = APP / "src" / "content" / "article.mdx"
STALE = ("results.json", "anatomy.json", "advantage.json", "timeline.json", "desk.json", "bench.json", "banner.json",
         "curve.json")
STALE_SCRIPTS = ("desk-charts.js",)
BEAT_SHARE = 0.8
CONSTANT = {"$5,000", "$2,000", "−$250", "$250", "0.2", "0.8", "0.1", "1.0", "0.0", "95%"}
NUMBER = re.compile(r"[−+-]?⁠?\\?\$[\d,]+(?:\.\d+)?k?|[−+-]?\d+\.\d+¢|[−+-]?\b\d+\.\d{2,}\b|\b\d+(?:\.\d+)?%")
LEAK = re.compile(r"s3://|amazonaws|airops-runs|scale\.com|\bFD-\d|\bsk-[A-Za-z0-9_-]{12,}|litellm\.[a-z]|ocp-apim|"
                  r"b2clogin|ercot-api|\bhf_[A-Za-z0-9]{30,}|\b(?:10|172|192)\.\d+\.\d+\.\d+\b|"
                  r"gridsim/adapters|\bi-0[0-9a-f]{8,}|object storage \(`", re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--desk-repo", type=Path, default=ROOT,
                    help="A checkout of the desk: its benchmark results and pack feed the article, its packs name the "
                         "real sites and operators the article must not.")
    ap.add_argument("--build", action="store_true", help="npm ci (once) and npm run build in hub/article/app.")
    ap.add_argument("--publish", action="store_true", help="Upload hub/article to the Space.")
    args = ap.parse_args()
    folder = args.desk_repo / "results" / "desk-v4-bench"
    if not (folder / "summary.json").is_file():
        raise SystemExit(f"{args.desk_repo} holds no benchmark results: pass --desk-repo")
    card = module("hub_dataset", "scripts/hub_dataset.py")
    s, grades = card.bench_read(folder)
    if s["fake"]:
        raise SystemExit("results/desk-v4-bench holds fake data; the article states real runs only")
    pairs = duel(args.desk_repo, s, grades, card)
    out = {"facts.json": {"env": env(s), "lead": lead(s, grades, card),
                          "duel": duel_facts(args.desk_repo, s, grades, pairs, card)},
           "duel.json": duel_data(pairs, s)}
    DATA.mkdir(parents=True, exist_ok=True)
    for name in STALE:
        (DATA / name).unlink(missing_ok=True)
    for name in STALE_SCRIPTS:
        (APP / "public" / "scripts" / name).unlink(missing_ok=True)
    for name, obj in out.items():
        (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:16} {(DATA / name).stat().st_size / 1e3:7.1f} kB")
    describe(card.bench_pitch(s).strip("*"), out["facts.json"]["lead"])
    check_prose(out["facts.json"])
    check_film()
    leaks(files_to_publish())
    hk = module("hub_desk", "scripts/hub_desk.py")
    hk.anonymous(texts(files_to_publish()), hk.names(args.desk_repo))
    if args.build or args.publish:
        build()
        check_rendered(out["facts.json"])
    if args.publish:
        print("space:", publish())


def module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def usd(x: float, sign: bool = False) -> str:
    """Whole dollars as the results READMEs print them, a word joiner keeping the sign on the amount."""
    v = f"{abs(x):,.0f}"
    s = "" if v == "0" else "−" if x < 0 else "+" if sign else ""
    return f"{s}⁠${v}" if s else f"${v}"


def mwh(x: float) -> str:
    return f"{x:,.0f} MWh"


def day(iso: str) -> str:
    return f"{date.fromisoformat(iso):%-d %B %Y}"


def span(a: str, b: str, sep: str = " to ") -> str:
    x, y = date.fromisoformat(a), date.fromisoformat(b)
    return day(a) if x == y else f"{x:%-d}{sep}{y:%-d %B %Y}" if (x.year, x.month) == (y.year, y.month) else (
        f"{x:%-d %B}{sep}{y:%-d %B %Y}")


def env(s: dict) -> dict:
    """The environment's shape, from summary.json: windows, fronts, batteries, days a window, models."""
    return {"windows": str(s["n_windows"]), "fronts": str(s["n_fronts"]), "sites": str(len(s["sites"])),
            "models": str(len(s["models"]))}


def lead(s: dict, grades: list[dict], card) -> dict:
    """The film's run, summary.json's hero, as its caption states it: the model, the window, P and C as the dataset card
    prints them, the real operator's two figures and the run's 3D replay in the viewer Space."""
    h = s["hero"]
    m, g = s["models"][h["model"]], next(x for x in grades if x["model"] == h["model"] and x["task_id"] == h["task_id"])
    front = next(f for f in s["fronts"] if f["front"] == g["front"])
    who = (f"{m['name']} trades Battery {g['site']} ({g['region']}, {g['battery']}) through the "
           f"{span(g['dates'][0], g['dates'][-1])} {front['kind']}")
    return {"name": m["name"], "harness": m["harness"], "site": f"Battery {g['site']}", "region": g["region"],
            "battery": g["battery"], "span": span(g["dates"][0], g["dates"][-1]), "kind": front["kind"],
            "P": usd(g["p"]), "C": f"{card.pc(g['capture'])}%", "op": usd(g["p_operator_actual"]),
            "op_replay": usd(g["p_operator_replay"]), "replay": card.bench_replay(h["model"], h["task_id"]),
            "film_alt": (f"{who}: the battery site in 3D, the agent's tool calls one by one in the desk beside it, the "
                         "node's price and the battery's charge below as they post, then the settled grade beside the "
                         "real operator's"),
            "og_alt": (f"{who}: the battery site in 3D at dusk, discharging, beside the desk's clock and the agent's "
                       "wake-ups, the node's price and the battery's charge below")}


def duel(repo: Path, s: dict, grades: list[dict], card) -> list[dict]:
    """The before and after: every window after all the models' reported training cutoffs on which at least BEAT_SHARE
    of the models scored there settled above the real operator, both as it ran and with its own bids replayed, each
    with the run that made the most. The operator's side comes from ERCOT's 60-day disclosures in the window's series:
    its day-ahead awards, its telemetered output and its state of charge; the agent's from its episode."""
    by = defaultdict(list)
    for g in grades:
        if g["status"] == "scored":
            by[g["task_id"]].append(g)
    pack = repo / "data" / "desk" / s["pack"]
    rows = {t["task_id"]: t for t in map(json.loads, gzip.open(pack / "tasks.jsonl.gz", "rt"))}
    out = []
    for task, gs in sorted(by.items()):
        g0 = gs[0]
        if g0["split"] != "post_cutoff" or g0["p_operator_actual"] is None or g0["p_operator_replay"] is None:
            continue
        ahead = [g for g in gs if g["p"] > g0["p_operator_actual"] and g["p"] > g0["p_operator_replay"]]
        if len(ahead) < BEAT_SHARE * len(gs):
            continue
        best = max(gs, key=lambda g: g["p"])
        ser = json.loads(gzip.decompress((pack / rows[task]["series"]).read_bytes()))
        ep = json.loads(gzip.decompress((repo / "results" / "desk-v4-bench" / best["episode"]).read_bytes()))
        op, dates = ser["operator"], g0["dates"]
        da = [x for d in dates for x in ser["dam_spp"][d]]
        rt = [x for d in dates for x in ser["rt_spp"][d]]
        sides = {"op": {"p": g0["p_operator_actual"], "replay": g0["p_operator_replay"],
                        "award": [x or 0.0 for d in dates for x in op["dam"][d]["award_mw"]],
                        "mw": [x or 0.0 for d in dates for x in op["sced"][d]["telemetry_mw"]],
                        "soc": [x for d in dates for x in op["sced"][d]["soc_mwh"]]},
                 "agent": {"p": best["p"], "award": [x or 0.0 for d in dates for x in ep["dam"][d]["award_mw"]],
                           "mw": [x for d in dates for x in ep["rt"][d]["metered_mw"]],
                           "soc": [x for d in dates for x in ep["rt"][d]["soc_mwh"][:-1]]}}
        for x in sides.values():
            x |= moves(x, da, rt)
        out.append({"task": task, "g": g0, "best": best, "n": len(gs), "ahead": len(ahead), "da": da, "rt": rt,
                    "e_max": ep["site"]["e_max_mwh"], "p_max": ep["site"]["hsl_mw"],
                    "front": next(f for f in s["fronts"] if f["front"] == g0["front"]),
                    "replay": card.bench_replay(best["model"], task), **sides})
    if not out:
        raise SystemExit("no window after the cutoffs on which the models clearly beat the operator")
    return out


def moves(x: dict, da: list[float], rt: list[float]) -> dict:
    """What a side sold a day ahead and at what prices, against the real-time prices of those hours; what it put
    through the battery and at what real-time prices; and its P in two parts: the battery's own energy at real-time
    prices, and the day-ahead position, each hour's award times the day-ahead price's premium over real time."""
    aw, mw, p15 = np.array(x["award"]), np.array(x["mw"]), np.array(rt)
    hourly, sold = p15.reshape(-1, 4).mean(1), np.clip(aw, 0, None)
    dis, chg, p5 = np.clip(mw, 0, None) / 12, np.clip(-mw, 0, None) / 12, np.repeat(p15, 3)
    w = lambda q, p: float((q * p).sum() / q.sum()) if q.sum() > 1e-9 else None  # noqa: E731
    return {"sold": float(sold.sum()), "sold_da": w(sold, np.array(da)), "sold_rt": w(sold, hourly),
            "dis": float(dis.sum()), "dis_px": w(dis, p5), "chg": float(chg.sum()), "chg_px": w(chg, p5),
            "energy": float((p15 * mw.reshape(-1, 3).mean(1)).sum() / 4),
            "position": float((np.repeat(aw, 4) * (np.repeat(np.array(da), 4) - p15)).sum() / 4)}


def why(w: dict, name: str) -> str:
    """One line on where the agent's money came from: the day-ahead position when it is most of the gap, the battery's
    own cycle against the operator's, each as the two sides' moves show it."""
    a, o = w["agent"], w["op"]
    gap, trade = a["p"] - o["p"], a["position"] - o["position"]
    alike = abs(a["dis"] - o["dis"]) <= 0.15 * o["dis"] and abs(a["dis_px"] - o["dis_px"]) <= 0.2 * o["dis_px"]
    cycle = ("the battery itself moved much as the operator's did" if alike else
             f"the rest is a {'bigger' if a['dis'] > o['dis'] else 'different'} cycle"
             f"{' at better prices' if a['dis_px'] > o['dis_px'] else ''}, {mwh(a['dis'])} out at {usd(a['dis_px'])} a "
             f"MWh against the operator's {mwh(o['dis'])} at {usd(o['dis_px'])}")
    if trade < 0.5 * gap:
        return f"{cycle[0].upper()}{cycle[1:].removeprefix('the rest is ')}."
    op = "none" if o["sold"] < 0.5 else mwh(o["sold"])
    return (f"Most of the gap is day-ahead trading: {name} sold {mwh(a['sold'])} a day ahead at {usd(a['sold_da'])} a "
            f"MWh on average and bought it back in real time at {usd(a['sold_rt'])}, where the operator sold {op}; "
            f"{cycle}.")


def duel_data(pairs: list[dict], s: dict) -> dict:
    """What the before and after draws: per window, the node's day-ahead and real-time prices, and for each side what
    it sold a day ahead each hour and the battery's charge every 15 minutes, with the money and the line on why."""
    out = []
    for w in pairs:
        g, b = w["g"], w["best"]
        m = s["models"][b["model"]]
        out.append({"task": w["task"], "site": f"Battery {g['site']}", "region": g["region"], "size": g["battery"],
                    "dates": g["dates"], "kind": w["front"]["kind"], "p_max": w["p_max"],
                    "da": [round(v, 2) for v in w["da"]], "rt": [round(v, 2) for v in w["rt"]],
                    "op": side(w["op"], w["e_max"]),
                    "agent": side(w["agent"], w["e_max"]) | {"key": b["model"], "name": m["name"]},
                    "n": w["n"], "ahead": w["ahead"], "why": why(w, m.get("tag") or m["name"]), "replay": w["replay"],
                    "table": table(w)})
    return {"windows": out, "source": "ERCOT's 60-day disclosures for the operator; the benchmark's episodes for the "
                                      "agents; ERCOT's node prices"}


def side(x: dict, e_max: float) -> dict:
    return {"p": round(x["p"], 2), "sold": [round(v, 1) for v in x["award"]],
            "sold_mwh": mwh(x["sold"]) if x["sold"] >= 0.5 else "nothing",
            "soc": [None if v is None else round(100 * v / e_max, 1) for v in x["soc"][::3]]}


def table(w: dict) -> list[list[str]]:
    """The numbers behind a window's panel, for its table view."""
    a, o = w["agent"], w["op"]
    px = lambda x: "–" if x is None else usd(x)  # noqa: E731
    return [["Settled P", usd(o["p"]), usd(a["p"])],
            ["Its own bids, replayed", usd(o["replay"]), "–"],
            ["Sold a day ahead", mwh(o["sold"]), mwh(a["sold"])],
            ["… at a day-ahead price of", px(o["sold_da"]), px(a["sold_da"])],
            ["… against real time at", px(o["sold_rt"]), px(a["sold_rt"])],
            ["Discharged", mwh(o["dis"]), mwh(a["dis"])],
            ["… at a real-time price of", px(o["dis_px"]), px(a["dis_px"])],
            ["Charged", mwh(o["chg"]), mwh(a["chg"])],
            ["… at a real-time price of", px(o["chg_px"]), px(a["chg_px"])]]


def duel_facts(repo: Path, s: dict, grades: list[dict], pairs: list[dict], card) -> dict:
    """The before and after's numbers in the prose: the rule, the windows it picked and the run each shows, the
    operator's bids replayed, and the next front, where the trade turned."""
    w0, n_models = pairs[0], len(s["models"])
    best = {w["best"]["model"] for w in pairs}
    front = w0["front"]
    out = {"n": str(len(pairs)), "need": str(int(np.ceil(BEAT_SHARE * n_models))), "of": str(n_models),
           "sites": card.and_join([w["g"]["site"] for w in pairs]),
           "span": span(w0["g"]["dates"][0], w0["g"]["dates"][-1]), "kind": front["kind"],
           "replays": card.and_join([usd(w["op"]["replay"]) for w in pairs]),
           "best": s["models"][best.pop()]["name"] if len(best) == 1 else None}
    if len({w["g"]["front"] for w in pairs}) != 1 or out["best"] is None:
        raise SystemExit("the before and after's prose describes one front and one model: rewrite it for these windows")
    nxt = sorted({g["front"] for g in grades if g["split"] == "post_cutoff" and g["front"] > front["front"]})
    if nxt:
        gs = [g for g in grades if g["front"] == nxt[0] and g["status"] == "scored"]
        by = defaultdict(list)
        for g in gs:
            by[g["task_id"]].append(g)
        behind = min(sum(g["p"] < g["p_operator_actual"] for g in xs) for xs in by.values())
        top = max(x for g in gs for x in rt_of(repo, g))
        out["next"] = {"span": span(gs[0]["dates"][0], gs[0]["dates"][-1]), "behind": str(behind),
                       "rt": usd(round(top, -1)), "sites": str(len(by))}
    return out


def rt_of(repo: Path, g: dict) -> list[float]:
    ep = json.loads(gzip.decompress((repo / "results" / "desk-v4-bench" / g["episode"]).read_bytes()))
    return [x for d in ep["dates"] for x in ep["rt"][d]["spp"]]


def leaves(f: dict, path: str = "F") -> dict[str, str]:
    out = {}
    for k, x in f.items():
        if isinstance(x, dict):
            out |= leaves(x, f"{path}.{k}")
        elif x is not None:
            out[f"{path}.{k}"] = x
    return out


FACT = re.compile(r"\{(F(?:\.[A-Za-z0-9_]+)+)\}")


def check_prose(f: dict) -> None:
    """The chapters state no number of their own: every amount, capture, cent or share in the prose outside code is a
    {F.…} expression read from facts.json, or one of the contract's constants; every expression names a fact."""
    known = leaves(f)
    bad, used = [], set()
    for p in sorted(CHAPTERS.glob("*.mdx")):
        text = re.sub(r"```.*?```", "", p.read_text(), flags=re.S)
        text = re.sub(r"<HtmlEmbed.*?/>", "", text, flags=re.S)
        for e in FACT.findall(text):
            used.add(e)
            if e not in known:
                bad.append(f"{p.name}: {{{e}}} names no fact")
        prose = re.sub(r"\{[^{}]*\}|`[^`]*`|^import .*$", "", text, flags=re.M | re.S)
        for n in NUMBER.findall(prose):
            if n.replace("\\", "").replace("⁠", "") not in CONSTANT:
                bad.append(f"{p.name}: {n!r} is written into the prose; read it from facts.json")
    if bad:
        raise SystemExit("numbers check failed:\n  " + "\n  ".join(bad))
    print(f"numbers check: {len(used)} stated numbers read from facts.json, formatted from summary.json, the grades "
          "and the episodes; none written in")


def describe(pitch: str, lead_: dict) -> None:
    """The front matter's two lines that state results: the description, the hero's subtitle and the page's meta
    description, is the card's pitch; the social image's alt text names the film's run."""
    text = MDX.read_text()
    for key, value in (("description", pitch), ("seoImageAlt", lead_["og_alt"])):
        text, n = re.subn(rf'^{key}: ".*"$', lambda _, k=key, v=value: f"{k}: {json.dumps(v, ensure_ascii=False)}",
                          text, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{MDX.name} has no one-line {key} to write")
    MDX.write_text(text)


def check_film() -> None:
    """The film ships with the Space, not the repository: it must be in place before a build or a publish."""
    if not FILM.is_file():
        raise SystemExit(f"{FILM.relative_to(ROOT)} is missing: film it with scripts/hub_desk_film.py --out {FILM}")
    if FILM.stat().st_size > FILM_MB * 1e6 or FILM.read_bytes()[:6] != b"GIF89a":
        raise SystemExit(f"{FILM.name} is not a GIF of at most {FILM_MB} MB")
    print(f"film: {FILM.name}, {FILM.stat().st_size / 1e6:.1f} MB")


def check_rendered(f: dict) -> None:
    """After the build: every fact the prose names appears on the page as facts.json formats it, a link as an href."""
    html = (APP / "dist" / "index.html").read_text()
    text = re.sub(r"<[^>]+>", "", html).replace("&#36;", "$").replace("&amp;", "&").replace("&#39;", "'")
    known, links = leaves(f), html.replace("&amp;", "&")
    used = {e for p in CHAPTERS.glob("*.mdx") for e in FACT.findall(p.read_text())}
    missing = [f"{e} = {known[e]!r}" for e in sorted(used)
               if not (f'href="{known[e]}"' in links if known[e].startswith("https://")
                       else known[e] in text or f'"{known[e]}"' in links)]
    if not (APP / "dist" / "media" / FILM.name).is_file():
        missing.append(f"media/{FILM.name}")
    if missing:
        raise SystemExit("rendered check failed, not on the page:\n  " + "\n  ".join(missing))
    print(f"rendered check: all {len(used)} facts on the page as formatted, and the film")


def files_to_publish() -> dict[str, Path]:
    skip = re.compile(r"(^|/)(node_modules|dist|\.astro|\.DS_Store)(/|$)|^app/public/data(/|$)")
    out = {}
    for p in sorted(ARTICLE.rglob("*")):
        rel = p.relative_to(ARTICLE).as_posix()
        if p.is_file() and not p.is_symlink() and not skip.search(rel):
            out[rel] = p
    return out


IMAGES = (".jpg", ".png", ".webp", ".gif")


def texts(files: dict[str, Path]) -> dict[str, bytes]:
    """Every published file the scans read: all of them but the images, which must be images."""
    out = {}
    for k, p in files.items():
        b = p.read_bytes()
        try:
            b.decode()
        except UnicodeDecodeError:
            if p.suffix not in IMAGES:
                raise SystemExit(f"{k} is neither text nor an image; nothing was published") from None
            continue
        out[k] = b
    return out


def leaks(files: dict[str, Path]) -> None:
    text = texts(files)
    scan(text, known_values())
    for k, v in text.items():
        if hit := LEAK.search(v.decode()):
            raise SystemExit(f"{k} holds {hit[0]!r}; nothing was published")
    print(f"leak scan: {len(text)} text files clean")


def build() -> None:
    if not (APP / "node_modules").is_dir():
        subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=APP, check=True)
    subprocess.run(["npm", "run", "build"], cwd=APP, check=True)


GITATTRIBUTES = "".join(f"*.{x} filter=lfs diff=lfs merge=lfs -text\n" for x in ("mp4", "webp", "jpg", "png", "gif"))


def publish() -> str:
    """Create the Docker Space if needed and make its files exactly hub/article's."""
    from huggingface_hub import CommitOperationAdd, CommitOperationDelete, HfApi
    api = HfApi()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", exist_ok=True)
    files = files_to_publish()
    live = set(api.list_repo_files(SPACE, repo_type="space"))
    ops = [CommitOperationAdd(path_in_repo=".gitattributes", path_or_fileobj=GITATTRIBUTES.encode())]
    ops += [CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(p)) for k, p in files.items()]
    ops += [CommitOperationDelete(path_in_repo=k) for k in sorted(live - set(files) - {".gitattributes"})]
    info = api.create_commit(SPACE, repo_type="space", operations=ops, commit_message=(
        "GridSimEnv article: what is in the environment, a run in 3D, and the real operator against the agents"))
    return info.commit_url


if __name__ == "__main__":
    main()
