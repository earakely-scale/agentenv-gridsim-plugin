"""The GridSimEnv article: a research-article Space built with tfrere's research-article-template (Astro, MDX chapters,
D3 embeds) under hub/article. It opens on what is in the environment: a recorded benchmark run filmed on the 3D viewer
(scripts/hub_desk_film.py, an MP4 with a GIF inside it as the fallback), then the real operator against the agents on
the windows where they most clearly beat it, the environment live, and the eval: the dataset card's cost chart
(hub/desk-charts/charts.js) and a rollout in the viewer Space,
read from results/desk-v4-bench, its episodes and the desk-v4-bench pack. The prose states no number of its own: it
reads them from facts.json, which this script formats from summary.json, the grades and the episodes, and the front
matter's description is the dataset card's pitch.

    .venv/bin/python scripts/hub_desk_film.py --out hub/article/app/public/media/gridsim-run.mp4   # the film, once
    .venv/bin/python scripts/hub_desk_film.py --out hub/article/app/public/media/gridsim-run.gif   # and its fallback
    .venv/bin/python scripts/hub_article.py             # the data, the numbers check, the scans
    .venv/bin/python scripts/hub_article.py --build     # then npm ci (once) and npm run build
    .venv/bin/python scripts/hub_article.py --publish   # then upload hub/article to the Space

The films are uploaded with the Space, not committed (hub/article/app/public/media is ignored).
"""

import argparse
import gzip
import importlib.util
import json
import re
import subprocess
from collections import defaultdict
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import numpy as np
from agentenv_hf.scan import known_values, scan

from gridsim_core.desk import TOOLS

ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "hub" / "article"
APP = ARTICLE / "app"
DATA = APP / "src" / "content" / "assets" / "data"
CHAPTERS = APP / "src" / "content" / "chapters"
MEDIA = APP / "public" / "media"
FILMS = {MEDIA / "gridsim-run.mp4": 10, MEDIA / "gridsim-run.gif": 10}
MOMENT_KB = 400
MOMENTS = {
    "desk-v4-2026-08-18-S01": {"t": 4080, "kind": "delivers", "shot": "push", "drift": 0.3, "crop": 0.5,
                               "scene": "the yard at sunset, its containers lit as they discharge"},
    "desk-v4-2026-08-18-S02": {"t": 4160, "kind": "delivers", "shot": "city", "drift": 0.3, "crop": 0.85,
                               "scene": "the line carrying the battery's power toward the city's lights at night"},
    "desk-v4-2026-08-18-S03": {"t": 1170, "kind": "peak", "shot": "establish", "drift": 0.3, "crop": 0.5,
                               "scene": "the whole yard at dusk, discharging into the line"}}
"""Each before and after card's moment in 3D: a minute of the run that tells its story, a camera shot of the viewer's
director, and what the picture shows. The caption's values come from the run and the operator's records at that
minute, and must bear out its kind: "delivers", the run discharging at full power what it sold a day ahead for that
hour while the operator holds back; "peak", the run discharging at full power into the window's highest price."""
SPACE = "earakely-scale/GridSimEnv"
MDX = APP / "src" / "content" / "article.mdx"
README = ARTICLE / "README.md"
TRY_SPACE = "https://huggingface.co/spaces/earakely-scale/GridSimEnv-OpenEnv"
TRY_APP = "https://earakely-scale-gridsimenv-openenv.hf.space/web/"
TRY_CODE = "https://github.com/earakely-scale/agentenv-gridsim-plugin/tree/main/hub/openenv"
TRY_SCRIPT = ROOT / "scripts" / "hub_openenv.py"
VIEWER = "https://huggingface.co/spaces/earakely-scale/GridSimEnv-AgentEnv"
CHARTS = ROOT / "hub" / "desk-charts" / "charts.js"
BASIS = {"gpu_time": "GPU time", "metered_rate": "metered rate"}
OFFERS = ("submit_dam_offers", "submit_rt_offers")
REPLAN = ("sol", "beam")
"""The models the re-planning finding names: the leader, and the one whose losses were diagnosed run by run."""
COSTLIEST = ("sol", "desk-v4-2026-08-26-S01")
"""The run the rollout opens on, the bench's costliest; its note tells this run's story, so the build stops if the
costliest run is another."""
PITCH = ("{models} AI models run a real Texas battery's trading desk through {fronts} real weather fronts, scored in "
         "dollars against the best possible plan and the battery's real operator.")
SHORT = "{n} AI models trade a real Texas battery"
SHORT_MAX = 60
STALE = ("results.json", "anatomy.json", "advantage.json", "timeline.json", "desk.json", "banner.json", "curve.json")
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
    out = {"facts.json": {"header": header(s, card), "env": env(s, card), "lead": lead(s, grades, card),
                          "tryit": tryit(args.desk_repo, s, grades, card),
                          "duel": duel_facts(args.desk_repo, s, grades, pairs, card),
                          "eval": evals(args.desk_repo, s, grades, pairs, card)},
           "duel.json": duel_data(pairs, s), "bench.json": bench_chart(s)}
    DATA.mkdir(parents=True, exist_ok=True)
    for name in STALE:
        (DATA / name).unlink(missing_ok=True)
    for name, obj in out.items():
        (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:16} {(DATA / name).stat().st_size / 1e3:7.1f} kB")
    (APP / "public" / "scripts" / "desk-charts.js").write_bytes(CHARTS.read_bytes())
    describe(out["facts.json"]["header"], out["facts.json"]["lead"])
    check_prose(out["facts.json"])
    check_film()
    check_moments(out["duel.json"])
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


def header(s: dict, card) -> dict:
    """The header's line under the title, which is also the page's description, and the Space card's short one."""
    models, fronts = card.NUM[len(s["models"])], str(s["n_fronts"])
    short = SHORT.format(n=len(s["models"]))
    if len(short) > SHORT_MAX:
        raise SystemExit(f"the Space card's short description is over {SHORT_MAX} characters: {short!r}")
    return {"models": models, "fronts": fronts, "pitch": PITCH.format(models=models, fronts=fronts), "short": short}


def tryit(repo: Path, s: dict, grades: list[dict], card) -> dict:
    """The Try it section: the OpenEnv Space (scripts/hub_openenv.py, hub/openenv), the desk's tools it serves, and the
    window it opens on, which is the film's, at its index in the pack's order as the Space lists them."""
    m = re.search(r'^DEFAULT = "([^"]+)"$', TRY_SCRIPT.read_text(), re.M)
    task = m and m[1]
    if task != s["hero"]["task_id"]:
        raise SystemExit(f"the Try it Space opens on {task}, not the film's run {s['hero']['task_id']}: rewrite the "
                         "section's caption")
    with gzip.open(repo / "data" / "desk" / s["pack"] / "tasks.jsonl.gz", "rt") as f:
        order = [json.loads(x)["task_id"] for x in f if x.strip()]
    g = next(x for x in grades if x["task_id"] == task)
    front = next(f for f in s["fronts"] if f["front"] == g["front"])
    return {"tools": card.NUM[len(TOOLS)].lower(), "index": str(order.index(task)), "site": g["site"],
            "span": span(g["dates"][0], g["dates"][-1]), "kind": front["kind"], "space": TRY_SPACE, "app": TRY_APP,
            "code": TRY_CODE}


def evals(repo: Path, s: dict, grades: list[dict], pairs: list[dict], card) -> dict:
    """The eval: who ran what under which budget, each model's point in the cost chart, the three findings and the
    rollout the viewer opens on, from the summary, the grades and the episodes."""
    ms, budget = card.bench_models(s), s["run"]["budget"]
    scored = [g for g in grades if g["status"] == "scored"]
    hs = sorted({m["harness"] for m in ms})
    return {"harnesses": f"{', '.join(hs[:-1])} or {hs[-1]}", "calls": str(budget["calls_per_turn"]),
            "turns": str(budget["max_turns"]), "runs": str(len(scored)), "viewer": VIEWER,
            "basis": basis_line(ms, card), "m": {m["key"]: point(m, s, card) for m in ms},
            "lead": lead_gap(s, ms, card), "halves": halves(s, ms, grades, pairs[0]["front"]["front"], card),
            "replan": replan(repo, s, ms, scored, card), "watch": watch(repo, s, scored, card)}


def bench_chart(s: dict) -> dict:
    """What the card's cost chart (hub/desk-charts) reads: the summary's plot, and each model's windows, its cost basis
    note and, for the distilled model, what it is."""
    return {k: s[k] for k in ("fake", "n_windows", "n_fronts", "splits", "fronts", "plot")} | {"models": {
        k: {x: m.get(x) for x in ("key", "family", "name", "n", "price_note", "distilled", "distilled_short")}
        for k, m in s["models"].items()}}


def point(m: dict, s: dict, card) -> dict:
    """A model's point as the chart's tooltip states it: C over its windows with its CI, and its cost."""
    c, C = m["cost"], m["all"]["C"]
    return {"name": m["name"], "harness": m["harness"], "setting": m["setting"], "n": str(m["n"]),
            "of": str(s["n_windows"]), "C": f"{card.pc(C['mean'])}%",
            "ci": f"[{card.pc(C['ci'][0])}, {card.pc(C['ci'][1])}]",
            "usd": card.bench_usd(c["usd_per_window"]), "spent": card.bench_usd(c["usd_all_attempts"]),
            "basis": BASIS.get(c["basis"])}


def basis_line(ms: list[dict], card) -> str:
    """The cost chart's price basis in one line: the makers' list price, and each model priced another way."""
    listed, metered = [], []
    for m in ms:
        b, note = m["cost"]["basis"], m.get("price_note") or ""
        if b == "list_price_tokens" and note:
            seller = re.search(r"at (.+?)'s list price", note)
            listed.append(seller and f"{m['name']} at {seller[1]}'s")
        elif b == "metered_rate":
            seller = re.search(r"metered (\S+) rate", note)
            metered.append(seller and f"{m['name']} at {seller[1]}' metered rate")
    other = listed + metered
    if not all(other):
        raise SystemExit("a price note names no seller: rewrite basis_line for it")
    gpu = [m["name"] for m in ms if m["cost"]["basis"] == "gpu_time"]
    return "; ".join(["Cost: each window's tokens at the model maker's list price", *other,
                      *([f"{card.and_join(gpu)} in GPU time"] if gpu else [])]) + "."


def lead_gap(s: dict, ms: list[dict], card) -> dict:
    """The first finding: the leader, the runner-up close behind at a fraction of the cost, and their paired gap."""
    a, b = ms[:2]
    gap = card.bench_pair(s, a["key"], b["key"])
    if not gap["ci"][0] <= 0 <= gap["ci"][1]:
        raise SystemExit(f"{a['name']}'s lead over {b['name']} has a CI that excludes zero: rewrite the first finding")
    side = lambda m: {"name": m["name"], "C": f"{card.pc(m['all']['C']['mean'])}%",  # noqa: E731
                      "usd": card.bench_usd(m["cost"]["usd_per_window"])}
    return {"a": side(a), "b": side(b), "lo": card.pc(gap["ci"][0], 1, True), "hi": card.pc(gap["ci"][1], 1, True)}


def halves(s: dict, ms: list[dict], grades: list[dict], front: str, card) -> dict:
    """The second finding: every model lower in the second half, one of them trained before every window, so the
    second half is harder; and the next front after the before and after's, where most models lost money."""
    first = min(f["front"] for f in s["fronts"])
    old = [m["name"] for m in ms if m.get("cutoff") and str(m["cutoff"]) < first]
    if any(m["post_cutoff"]["C"]["mean"] >= m["pre_cutoff"]["C"]["mean"] for m in ms) or len(old) != 1:
        raise SystemExit("the second finding has every model lower in the second half and one model trained before "
                         "every window: rewrite it")
    nxt = min(f["front"] for f in s["fronts"] if f["split"] == "post_cutoff" and f["front"] > front)
    money = defaultdict(float)
    for g in grades:
        if g["front"] == nxt and g["status"] == "scored":
            money[g["model"]] += g["p"]
    lost = sum(x < 0 for x in money.values())
    if lost * 2 <= len(money):
        raise SystemExit("most models no longer lose money on the next front: rewrite the second finding")
    pre, post = ([f["front"] for f in s["fronts"] if f["split"] == x] for x in card.BENCH_SPLITS)
    return {"pre": month_words(pre), "post": month_words(post), "old": old[0], "lost": str(lost)}


def month_words(fronts: list[str]) -> str:
    """The months a split's three-day windows cover: 'January to May', 'July and August'."""
    a = date.fromisoformat(min(fronts))
    b = date.fromordinal(date.fromisoformat(max(fronts)).toordinal() + 2)
    n = (b.year - a.year) * 12 + b.month - a.month
    return f"{a:%B}" if n == 0 else f"{a:%B} and {b:%B}" if n == 1 else f"{a:%B} to {b:%B}"


def replan(repo: Path, s: dict, ms: list[dict], scored: list[dict], card) -> dict:
    """The third finding: how late each model sends its last offers, a window's mean hours before its end, against its
    C, a rank correlation over the models; and what distilling the desk's planner did for the model distilled."""
    hours = defaultdict(list)
    for g in scored:
        ep = json.loads(gzip.decompress((repo / "results" / "desk-v4-bench" / g["episode"]).read_bytes()))
        offers = [x["t"] for x in ep["submissions"] if x["accepted"] and x["tool"] in OFFERS]
        t = max(offers, default=ep["wakes"][0]["t"])
        hours[g["model"]].append((len(ep["dates"]) * 1440 - t) / 60)
    keys = [m["key"] for m in ms]
    late = {k: float(np.mean(hours[k])) for k in keys}
    rho = spearman([s["models"][k]["all"]["C"]["mean"] for k in keys], [-late[k] for k in keys])
    if rho < 0.5:
        raise SystemExit(f"the rank correlation of late offers with C is {rho:.2f}: rewrite the third finding")
    a, b = REPLAN
    sft = next(m for m in ms if m.get("distilled"))
    base = s["models"][sft["family"]]
    pct = lambda x: f"{card.pc(x)}%"  # noqa: E731
    return {"rho": f"{rho:.2f}", "a": s["models"][a]["name"], "ah": f"{late[a]:.1f}", "b": s["models"][b]["name"],
            "bh": f"{late[b]:.1f}", "base": base["name"], "baseC": pct(base["all"]["C"]["mean"]),
            "sftC": pct(sft["all"]["C"]["mean"]), "planner": pct(s["references"]["anchor"]["all"]["C"]["mean"])}


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = (np.argsort(np.argsort(x)).astype(float) for x in (a, b))
    return float(np.corrcoef(ra, rb)[0, 1])


def watch(repo: Path, s: dict, scored: list[dict], card) -> dict:
    """The rollout the viewer opens on: the bench's costliest run, at the minute of its window's highest real-time
    price, with what it lost and what the real operator made there."""
    g = min(scored, key=lambda x: x["p"])
    if (g["model"], g["task_id"]) != COSTLIEST:
        raise SystemExit(f"the costliest run is now {g['model']} on {g['task_id']}: rewrite the rollout's note")
    ep = json.loads(gzip.decompress((repo / "results" / "desk-v4-bench" / g["episode"]).read_bytes()))
    d, i, top = max(((d, i, x) for d in ep["dates"] for i, x in enumerate(ep["rt"][d]["spp"])), key=lambda r: r[2])
    t = (date.fromisoformat(d) - date.fromisoformat(ep["dates"][0])).days * 1440 + i * 1440 // len(ep["rt"][d]["spp"])
    return {"name": s["models"][g["model"]]["name"], "site": g["site"], "region": g["region"],
            "span": span(g["dates"][0], g["dates"][-1]), "day": f"{date.fromisoformat(d):%-d %B}",
            "at": f"{t % 1440 // 60:02d}:{t % 60:02d}", "spike": usd(top), "lost": usd(-g["p"]),
            "op": usd(g["p_operator_actual"]), "app": f"{card.bench_replay(g['model'], g['task_id'])}&t={t}"}


def env(s: dict, card) -> dict:
    """The environment's shape, from summary.json: windows, fronts, batteries, models."""
    return {"windows": str(s["n_windows"]), "fronts": str(s["n_fronts"]), "sites": str(len(s["sites"])),
            "sites_word": card.NUM[len(s["sites"])].lower(), "models": str(len(s["models"]))}


def lead(s: dict, grades: list[dict], card) -> dict:
    """The film's run, summary.json's hero, as its caption states it: the model, the battery's power, where and when,
    its P and C (to the whole percent), the real operator's P, and the run's 3D replay in the viewer Space."""
    h = s["hero"]
    m, g = s["models"][h["model"]], next(x for x in grades if x["model"] == h["model"] and x["task_id"] == h["task_id"])
    front = next(f for f in s["fronts"] if f["front"] == g["front"])
    a, b = date.fromisoformat(g["dates"][0]), date.fromisoformat(g["dates"][-1])
    who = (f"{m['name']} trades Battery {g['site']} ({g['region']}, {g['battery']}) through the "
           f"{span(g['dates'][0], g['dates'][-1])} {front['kind']}")
    return {"name": m["name"], "mw": g["battery"].split(" / ")[0], "region": g["region"], "kind": front["kind"],
            "month": f"{a:%B %Y}" if a.month == b.month else f"{a:%B}–{b:%B %Y}",
            "P": usd(g["p"]), "pct": f"{card.pc(g['capture'], 0)}%", "op": usd(g["p_operator_actual"]),
            "replay": card.bench_replay(h["model"], h["task_id"]),
            "film_alt": (f"A recorded benchmark run: {who}. The battery site in 3D, the agent's tool calls one by "
                         "one in the desk beside it, the node's price and the battery's charge below as they post, "
                         "then the settled grade beside the real operator's"),
            "og_alt": (f"{who}: the battery site in 3D at dusk, discharging, beside the desk's clock and the agent's "
                       "wake-ups, the node's price and the battery's charge below")}


def duel(repo: Path, s: dict, grades: list[dict], card) -> list[dict]:
    """The before and after: every window after every reported training cutoff on which at least BEAT_SHARE
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
                    "table": table(w), "moment": moment(w, m.get("tag") or m["name"])})
    return {"windows": out, "source": "ERCOT's 60-day disclosures for the operator; the benchmark's episodes for the "
                                      "agents; ERCOT's node prices"}


def moment(w: dict, name: str) -> dict:
    """The card's moment in 3D (MOMENTS): the picture's file, its link to that minute of the run in the viewer, and its
    caption, checked against what the run and the operator did then."""
    spec = MOMENTS.get(w["task"])
    if spec is None:
        raise SystemExit(f"{w['task']} has no moment in 3D: pick one in hub_article.MOMENTS")
    t, cap = spec["t"], w["p_max"]
    mw, op, rt = w["agent"]["mw"][t // 5], w["op"]["mw"][t // 5], w["rt"][t // 15]
    da, sold = w["da"][t // 60], w["agent"]["award"][t // 60]
    them = "the real operator's battery sits idle" if abs(op) < 2 else f"the real operator puts out {op:.0f} MW"
    if spec["kind"] == "delivers" and mw >= 0.95 * cap and sold >= 0.95 * cap and op < 0.3 * cap:
        text = (f"{name} discharges {mw:.0f} MW that it sold a day ahead at {usd(da)} a MWh, while the real-time "
                f"price is {usd(rt)}; {them}.")
    elif spec["kind"] == "peak" and mw >= 0.95 * cap and rt == max(w["rt"]) and op < mw:
        text = f"{name} discharges {mw:.0f} MW into the window's highest real-time price, {usd(rt)} a MWh; {them}."
    else:
        raise SystemExit(f"{w['task']} at minute {t} is not a {spec['kind']!r} moment: {name} {mw:.0f} MW, sold "
                         f"{sold:.0f} MW a day ahead, operator {op:.0f} MW, real time {usd(rt)}")
    day = date.fromisoformat(w["g"]["dates"][0]) + timedelta(t // 1440)
    when = f"{day:%a} {day.day} {day:%b}, {t % 1440 // 60:02d}:{t % 60:02d}"
    site = w["g"]["site"]
    return {"t": t, "when": when, "text": text, "img": f"/media/moment-{site}.webp", "href": f"{w['replay']}&t={t}",
            "alt": f"Watch in 3D: {name}'s run at Battery {site} ({w['g']['region']}), {when}, {spec['scene']}",
            **{x: spec[x] for x in ("shot", "drift", "crop")}}


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
           "half": months(s["splits"]["post_cutoff"]["fronts"]),
           "best": s["models"][best.pop()]["name"] if len(best) == 1 else None}
    if len({w["g"]["front"] for w in pairs}) != 1 or out["best"] is None:
        raise SystemExit("the before and after's prose describes one front and one model: rewrite it for these windows")
    most = majority(grades, front["front"])
    if most != len(pairs):
        raise SystemExit(f"the opening says most models beat the operator at {len(pairs)} batteries on the "
                         f"{front['kind']}; {most} have a majority above it: rewrite it")
    out |= {"front": f"{date.fromisoformat(front['front']):%B} {front['kind']}", "most": card.NUM[most].lower()}
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


def months(fronts: list[str]) -> str:
    """The months a split's three-day windows cover, as words: 'July and August 2026'."""
    a = date.fromisoformat(min(fronts))
    b = date.fromordinal(date.fromisoformat(max(fronts)).toordinal() + 2)
    names = [date(a.year + (a.month + i - 1) // 12, (a.month + i - 1) % 12 + 1, 1)
             for i in range((b.year - a.year) * 12 + b.month - a.month + 1)]
    one = a.year == b.year
    words = [f"{d:%B}" if one else f"{d:%B %Y}" for d in names]
    joined = words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"
    return f"{joined} {b:%Y}" if one else joined


def majority(grades: list[dict], front: str) -> int:
    """The front's batteries at which more than half of the models scored there settled above the real operator, both
    as it ran and with its own bids replayed: the opening's claim, on the before and after's measure."""
    by = defaultdict(list)
    for g in grades:
        if g["front"] == front and g["status"] == "scored":
            by[g["site"]].append(g["p"] > g["p_operator_actual"] and g["p"] > g["p_operator_replay"])
    return sum(2 * sum(x) > len(x) for x in by.values())


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
QUOTED = re.compile(r"\[[^\]]*\]\(https://(?![a-z0-9-]+\.hf\.space/|huggingface\.co/|github\.com/earakely-scale/)[^)\s]+\)")


def check_prose(f: dict) -> None:
    """The chapters state no number of their own: every amount, capture, cent or share in the prose outside code is a
    {F.…} expression read from facts.json, one of the contract's constants, or quoted in the text of a link to its
    outside source; every expression names a fact."""
    known = leaves(f)
    bad, used, quoted = [], set(), 0
    for p in sorted(CHAPTERS.glob("*.mdx")):
        text = re.sub(r"```.*?```", "", p.read_text(), flags=re.S)
        text = re.sub(r"<HtmlEmbed.*?/>", "", text, flags=re.S)
        for e in FACT.findall(text):
            used.add(e)
            if e not in known:
                bad.append(f"{p.name}: {{{e}}} names no fact")
        prose = re.sub(r"\{[^{}]*\}|`[^`]*`|^import .*$", "", text, flags=re.M)
        quoted += sum(len(NUMBER.findall(q)) for q in QUOTED.findall(prose))
        prose = QUOTED.sub("", prose)
        for n in NUMBER.findall(prose):
            if n.replace("\\", "").replace("⁠", "") not in CONSTANT:
                bad.append(f"{p.name}: {n!r} is written into the prose; read it from facts.json")
    if bad:
        raise SystemExit("numbers check failed:\n  " + "\n  ".join(bad))
    print(f"numbers check: {len(used)} stated numbers read from facts.json, formatted from summary.json, the grades "
          f"and the episodes; none written in, {quoted} quoted in links to their outside sources")


def describe(head: dict, lead_: dict) -> None:
    """The lines that state results outside the chapters: the description (the hero's subtitle and the page's meta,
    Open Graph and Twitter descriptions) and the social image's alt text in the front matter, and the Space card's
    short description in its README."""
    for path, pairs, form in ((MDX, (("description", head["pitch"]), ("seoImageAlt", lead_["og_alt"])), "quoted"),
                              (README, (("short_description", head["short"]),), "plain")):
        text = path.read_text()
        for key, value in pairs:
            new = f"{key}: {json.dumps(value, ensure_ascii=False) if form == 'quoted' else value}"
            text, n = re.subn(rf"^{key}: .*$", lambda _, x=new: x, text, count=1, flags=re.M)
            if n != 1:
                raise SystemExit(f"{path.name} has no one-line {key} to write")
        path.write_text(text)


def check_moments(duel: dict) -> None:
    """The cards' pictures ship with the Space, like the films: each must be in place, a WebP, at most MOMENT_KB."""
    for w in duel["windows"]:
        path = APP / "public" / w["moment"]["img"].lstrip("/")
        if not path.is_file():
            raise SystemExit(f"{path.relative_to(ROOT)} is missing: render it with scripts/hub_desk_film.py --moments "
                             f"{(DATA / 'duel.json').relative_to(ROOT)} --out {path.parent.relative_to(ROOT)}")
        head = path.read_bytes()[:12]
        if head[:4] != b"RIFF" or head[8:12] != b"WEBP" or path.stat().st_size > MOMENT_KB * 1e3:
            raise SystemExit(f"{path.name} is not a WebP of at most {MOMENT_KB} kB")
    print(f"moments: {len(duel['windows'])} pictures in 3D, "
          f"{max((APP / 'public' / w['moment']['img'].lstrip('/')).stat().st_size for w in duel['windows']) / 1e3:.0f}"
          " kB at most")


def check_film() -> None:
    """The films ship with the Space, not the repository: they must be in place before a build or a publish, the MP4
    with its index ahead of its media so it plays as it loads."""
    for path, mb in FILMS.items():
        if not path.is_file():
            raise SystemExit(f"{path.relative_to(ROOT)} is missing: film it with scripts/hub_desk_film.py --out {path}")
        head = path.read_bytes()[:1 << 20]
        kind = head[:6] == b"GIF89a" if path.suffix == ".gif" else (
            head[4:8] == b"ftyp" and -1 < head.find(b"moov") < (head.find(b"mdat") % len(head)))
        if not kind or path.stat().st_size > mb * 1e6:
            raise SystemExit(f"{path.name} is not a {path.suffix[1:]} of at most {mb} MB that plays as it loads")
        print(f"film: {path.name}, {path.stat().st_size / 1e6:.1f} MB")


def check_rendered(f: dict) -> None:
    """After the build: every fact the prose names appears on the page as facts.json formats it, a link as an href."""
    html = (APP / "dist" / "index.html").read_text()
    text = re.sub(r"<[^>]+>", "", html).replace("&#36;", "$").replace("&amp;", "&").replace("&#39;", "'")
    known, links = leaves(f), html.replace("&amp;", "&")
    used = {e for p in CHAPTERS.glob("*.mdx") for e in FACT.findall(p.read_text())}
    missing = [f"{e} = {known[e]!r}" for e in sorted(used)
               if not ((f'href="{known[e]}"' in links or f'src="{known[e]}"' in links) if known[e].startswith("https://")
                       else known[e] in text or f'"{known[e]}"' in links)]
    missing += [f"media/{p.name}" for p in FILMS if not (APP / "dist" / "media" / p.name).is_file()]
    duel = json.loads((DATA / "duel.json").read_text())
    missing += [w["moment"]["img"] for w in duel["windows"]
                if not (APP / "dist" / w["moment"]["img"].lstrip("/")).is_file()]
    pitch, shown = f["header"]["pitch"], {
        "the subtitle": re.findall(r'<p class="hero-desc"[^>]*>([^<]*)<', html),
        **{f"the {k} description": re.findall(rf'<meta {a}="{k}" content="([^"]*)"', html)
           for a, k in (("name", "description"), ("property", "og:description"), ("name", "twitter:description"))}}
    missing += [f"{what} = {pitch!r}" for what, found in shown.items() if [unescape(x) for x in found] != [pitch]]
    if missing:
        raise SystemExit("rendered check failed, not on the page:\n  " + "\n  ".join(missing))
    print(f"rendered check: all {len(used)} facts on the page as formatted, the header's line in the subtitle and the "
          "page's descriptions, the films and the cards' pictures")


def files_to_publish() -> dict[str, Path]:
    skip = re.compile(r"(^|/)(node_modules|dist|\.astro|\.DS_Store)(/|$)|^app/public/data(/|$)")
    out = {}
    for p in sorted(ARTICLE.rglob("*")):
        rel = p.relative_to(ARTICLE).as_posix()
        if p.is_file() and not p.is_symlink() and not skip.search(rel):
            out[rel] = p
    return out


IMAGES = (".jpg", ".png", ".webp", ".gif", ".mp4")


def texts(files: dict[str, Path]) -> dict[str, bytes]:
    """Every published file the scans read: all of them but the images and films, which must be images or films."""
    out = {}
    for k, p in files.items():
        b = p.read_bytes()
        try:
            b.decode()
        except UnicodeDecodeError:
            if p.suffix not in IMAGES:
                raise SystemExit(f"{k} is neither text nor an image or film; nothing was published") from None
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
