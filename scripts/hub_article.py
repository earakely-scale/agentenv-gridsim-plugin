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
import hashlib
import importlib.util
import json
import re
import subprocess
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from html import unescape
from pathlib import Path

import numpy as np
from agentenv_hf.scan import known_values, scan

from gridsim_core.desk import TOOLS
from gridsim_core.desk.policies import setting
from gridsim_core.desk.tools import tool_specs

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
REPLAN = ("sol", "beam")
"""The models the re-planning finding names: the leader, and the one whose losses were diagnosed run by run."""
FAIL_KEYS = {"qwen9b-sft": "qwen9bsft", "gemini": "argon"}
"""failures.json's model keys where they differ from summary.json's."""
COSTLIEST = ("sol", "desk-v4-2026-08-26-S01")
"""The run the rollout opens on, the bench's costliest; its note tells this run's story, so the build stops if the
costliest run is another."""
MAKER = {"Claude Code": "Anthropic", "Codex CLI": "OpenAI", "Gemini CLI": "Google"}
SOURCES = {
    "sheet": ("ERCOT fact sheet, Oct 2026", "https://www.ercot.com/files/docs/2022/02/08/ERCOT_Fact_Sheet.pdf",
              "21,537 MW of installed energy storage as of October 2026"),
    "jul25": ("ERCOT Monthly, Jul 2025", "https://www.ercot.com/files/docs/2025/08/06/ERCOT-Monthly-July-2025.pdf",
              "also set three new energy storage records, ending with 7,152 MW discharged at 7:59 p.m. on July 30 … "
              "The installed capacity for batteries is 14,137 MW."),
    "fern": ("Modo Energy, Apr 2026",
             "https://modoenergy.com/research/en/ercot-march-2026-bess-benchmark-batteries-fern-revenues",
             "The top 25% of optimizers achieved at least 76% of their Top-Bottom spread opportunities, while the "
             "bottom quartile only earned 27%."),
    "revenue": ("Modo Energy, Feb 2026",
                "https://modoenergy.com/research/en/why-were-ercot-battery-revenues-so-low-in-2025-weather-energy-"
                "arbitrage-builodout",
                "the Modo Energy Nowcast anticipates total-year revenues to land at $29.4/kW. That is roughly half of "
                "2024's $56/kW and one-sixth of 2023's $193/kW."),
    "queue": ("ERCOT overview, Jul 2026",
              "https://www.ercot.com/files/docs/2026/08/17/ERCOT-Monthly-Operational-Overview-July-2026.pdf",
              "Totals: Solar 158 GW (34.6%), Wind 49 GW (10.7%), Gas 80 GW (17.6%), Battery 166 GW / 398 GWh (36.3%), "
              "Other 4 GW (0.9%)"),
    "record": ("Grid Status, Aug 2026", "https://blog.gridstatus.io/ercot-record-july-2026/",
               "Solar's sister, batteries, also saw a new discharge record, hitting 11,980 MW on Wednesday, July 22.")}
"""Each outside figure in Why it matters with its source's own words, quoted verbatim when the article was written."""
TILES = (
    {"value": "21,537", "scale": 1000, "unit": "GW", "desc": "of batteries on ERCOT's grid, October 2026",
     "bars": (("Jul 2025", "14,137"), ("Oct 2026", "21,537")), "src": ("sheet", "jul25")},
    {"value": "76%", "desc": "of what perfect timing allowed, captured by the best quarter of ERCOT battery bidders in "
     "January 2026", "bars": (("Best quarter", "76%"), ("Worst quarter", "27%")),
     "share": True, "src": ("fern",)},
    {"value": "$29.4", "unit": "/kW", "desc": "a year of revenue for ERCOT batteries in 2025, Modo's estimate, down "
     "from 2023", "bars": (("2023", "$193/kW"), ("2025", "$29.4/kW")), "src": ("revenue",)},
    {"value": "166", "unit": "GW", "desc": "of batteries waiting to connect to ERCOT in July 2026, more than any other "
     "kind of plant", "bars": (("Share of the queue", "36.3%"),), "share": True, "src": ("queue",)},
    {"value": "11,980", "scale": 1000, "unit": "GW",
     "desc": "discharged at once by ERCOT's batteries, a record, on 22 July 2026",
     "bars": (("30 Jul 2025", "7,152"), ("22 Jul 2026", "11,980")), "src": ("record", "jul25")})
"""The outside tiles: a value, its bars and their sources. Every figure is a token of its sources' quotes, shown as is
or, with a scale, divided and rounded to one decimal; the build checks each token is in a quote."""
DISTILL = ROOT / "docs" / "prereg" / "desk-distill.md"
TRAINER = ROOT / "scripts" / "desk_distill_train.py"
REPO_URL = "https://github.com/earakely-scale/agentenv-gridsim-plugin"
TRAINING_DOCS = "https://www.agentenvframework.com/docs/training"
TRAIN_RUN = {"hours": "4.5", "gpu": "$104", "grpo": "18"}
"""From the training run's log, not a committed file: the SFT's wall time on its one GPU, the GPU spent on training
and every eval, and the steps of the earlier GRPO run that moved nothing."""
PITCH = ("{models} AI models run a real Texas battery's trading desk through {fronts} real weather fronts, scored in "
         "dollars against the best possible plan and the battery's real operator.")
SHORT = "{n} AI models trade a real Texas battery"
SHORT_MAX = 60
STALE = ("results.json", "anatomy.json", "advantage.json", "timeline.json", "desk.json", "curve.json")
ATLAS = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json"
REGIONS = {"Far West": (-102.4, 31.3), "North": (-97.0, 32.9), "Houston": (-95.4, 29.8), "South": (-98.3, 28.2)}
BEAT_SHARE = 0.8
CONSTANT = {"$5,000", "$2,000", "−$250", "$250", "0.2", "0.8", "0.1", "1.0", "0.0", "95%", "0%", "100%"}
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
           "duel.json": duel_data(pairs, s), "bench.json": bench_chart(s), "reward.json": reward_chart(s, grades),
           "banner.json": banner(folder, s, grades, card),
           "train.json": train_chart(s, grades), "beam.json": beam_data(folder, s, grades, card)}
    f = out["facts.json"]
    f |= {"why": why_tiles(f["eval"]["watch"]), "reward": reward(s, grades, card), "train": train(s, grades, card),
          "links": links(s, card),
          "beam": card.beam_facts(out["beam.json"], s, json.loads((DATA / "failures.json").read_text()))}
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
        check_rendered(out["facts.json"], s)
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
    closed, opened = [m for m in ms if m["weights"] != "open"], {m["harness"] for m in ms if m["weights"] == "open"}
    if any(MAKER.get(m["harness"]) != m["provider"] for m in closed) or len(opened) != 1:
        raise SystemExit("the eval says each closed model ran in its maker's own harness and every open-weight model "
                         "in one harness: rewrite it")
    hs = sorted({m["harness"] for m in closed})
    return {"closed": f"{', '.join(hs[:-1])} or {hs[-1]}", "open": opened.pop(), "calls": str(budget["calls_per_turn"]),
            "turns": str(budget["max_turns"]), "runs": str(len(scored)), "viewer": VIEWER,
            "basis": basis_line(ms, card), "m": {m["key"]: point(m, s, card) for m in ms},
            "lead": lead_gap(s, ms, card), "halves": halves(s, ms, grades, pairs[0]["front"]["front"], card),
            "replan": replan(s, ms, card), "watch": watch(repo, s, scored, card)}


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


def replan(s: dict, ms: list[dict], card) -> dict:
    """The third finding, on the measure the "Where models fail" charts draw (failures.json, from the exact replay of
    every graded episode): the hours left in a window after a model's last accepted offer, the mean over its windows,
    and their rank correlation with C over the models, stated as the later the last offer, the higher the score; and
    what distilling the desk's planner did for the model distilled."""
    late, rho = lateness(s)
    if rho < 0.5:
        raise SystemExit(f"the rank correlation of late offers with C is {rho:.2f}: rewrite the third finding")
    a, b = REPLAN
    sft = next(m for m in ms if m.get("distilled"))
    base = s["models"][sft["family"]]
    pct = lambda x: f"{card.pc(x)}%"  # noqa: E731
    return {"rho": f"{rho:.2f}", "a": s["models"][a]["name"], "ah": f"{late[a]:.1f}", "b": s["models"][b]["name"],
            "bh": f"{late[b]:.1f}", "base": base["name"], "baseC": pct(base["all"]["C"]["mean"]),
            "sftC": pct(sft["all"]["C"]["mean"]), "planner": pct(s["references"]["anchor"]["all"]["C"]["mean"])}


def lateness(s: dict) -> tuple[dict[str, float], float]:
    """failures.json's hours left after each model's last accepted offer, by summary.json's keys, and their rank
    correlation with C signed as the later, the higher: failures.json's own, which must be its rows' rank correlation
    against summary.json's C over the same models."""
    fm = json.loads((DATA / "failures.json").read_text())
    late = {FAIL_KEYS.get(m["key"], m["key"]): m["last_offer_h"] for m in fm["models"]}
    if late.keys() != s["models"].keys():
        raise SystemExit(f"failures.json covers {sorted(late)}, summary.json {sorted(s['models'])}: replay them again")
    keys, rho = list(late), -fm["corr"]["last_offer_vs_C_models"]
    if abs(rho - spearman([s["models"][k]["all"]["C"]["mean"] for k in keys], [-late[k] for k in keys])) > 1e-9:
        raise SystemExit("failures.json's rank correlation is not its rows' against summary.json's C: replay again")
    return late, rho


def check_replan(f: dict, fm: dict) -> list[str]:
    """The eval's re-planning finding states the measure the "Where models fail" charts draw: its rank correlation and
    its hours are failures.json's, as those charts print them."""
    late, r = {m["name"]: m["last_offer_h"] for m in fm["models"]}, f["eval"]["replan"]
    want = {"rho": f"{-fm['corr']['last_offer_vs_C_models']:.2f}", "ah": f"{late[r['a']]:.1f}",
            "bh": f"{late[r['b']]:.1f}"}
    return [f"F.eval.replan.{k} = {r[k]!r}, where the failure charts give {v!r}" for k, v in want.items() if r[k] != v]


BEAM_EFFECTS = {"question": ("args_anchor", "a_strict"), "replan": ("d_anchor_on_skipped", "as_played"),
                "both": ("args_anchor+d", "as_played"), "as": ("b_add_as", "as_played"),
                "repair": ("c_repair", "as_played"), "verbatim": ("a_strict", "as_played"),
                "merge": ("a_merge", "as_played")}
"""Each change the Beam section states, as cf_beam.jsonl names it, against what it changes: the planner's question
against Beam's own with its proposals copied verbatim (a_strict), the rest against Beam as it played. "both" asks the
planner's question and fills each wake Beam ended without a submit."""


def beam_data(folder: Path, s: dict, grades: list[dict], card) -> dict:
    """beam.json, the Beam-1.0 diagnosis in results/desk-v4-bench/beam-diagnosis: each graded episode replayed call for
    call on the frozen desk, then with one thing changed and graded again (cf_beam.jsonl, cf_beam_d_no_dam.jsonl), and
    what its calls held (analysis_beam.jsonl). Each change is its mean paired difference in C, in points, with the
    bench's block bootstrap over the fronts; the replay as played must reproduce every graded P to the cent, and the
    planner's gap must be summary.json's."""
    d, R = folder / "beam-diagnosis", module("desk_bench_results", "scripts/desk_bench_results.py")
    rows = [json.loads(x) for n in ("cf_beam.jsonl", "cf_beam_d_no_dam.jsonl")
            for x in (d / n).read_text().splitlines() if x.strip()]
    an = [json.loads(x) for x in (d / "analysis_beam.jsonl").read_text().splitlines() if x.strip()]
    g = {x["task_id"]: x for x in grades if x["model"] == card.BEAM and x["status"] == "scored"}
    by = defaultdict(dict)
    for r in rows:
        by[r["variant"]][r["task_id"]] = r
    played = by["as_played"]
    if played.keys() != g.keys() or {r["task_id"] for r in an} != g.keys() or any(
            abs(played[t]["p"] - g[t]["p"]) >= 0.005 or abs(played[t]["C"] - g[t]["capture"]) > 1e-6 for t in g):
        raise SystemExit("the Beam diagnosis does not replay every graded Beam-1.0 window to the cent: replay it again")
    ids = sorted(g)

    def effect(v: str, ref: str, out: str | None = None) -> dict:
        keep = [t for t in ids if g[t]["front"] != out]
        p = R.paired([100 * by[v][t]["C"] for t in keep], [100 * by[ref][t]["C"] for t in keep],
                     [g[t]["front"] for t in keep])
        return {"variant": v, "vs": ref, "windows": len(keep), "fronts": p["fronts"], "mean": p["mean"], "ci": p["ci"]}

    eff = {k: effect(*v) for k, v in BEAM_EFFECTS.items()}
    per_front = defaultdict(list)
    for t in ids:
        per_front[g[t]["front"]].append(by["args_anchor"][t]["C"] - by["a_strict"][t]["C"])
    storm = max(per_front, key=lambda x: np.mean(per_front[x]))
    name = next(f["why"] for f in s["fronts"] if f["front"] == storm).split(",")[0]
    if not name.startswith("Winter Storm"):
        raise SystemExit(f"the planner's question gains most on the {storm} front, not a winter storm: rewrite the "
                         "Beam section's caveat")
    eff["calm"] = effect(*BEAM_EFFECTS["question"], out=storm)
    if min(eff[k]["ci"][0] for k in ("question", "replan", "both")) <= 0 or eff["calm"]["ci"][0] > 0:
        raise SystemExit("the Beam section says each fix adds capture and the question leans on the storm: rewrite it")
    gap = float(np.mean([100 * (r["anchor_C"] - r["C"]) for r in played.values()]))
    ref = s["references"]["anchor"]["all"]["C"]["mean"] - s["models"][card.BEAM]["all"]["C"]["mean"]
    if abs(gap - 100 * ref) > 0.02:
        raise SystemExit(f"the diagnosis's gap to the planner, {gap:.2f} points, is not summary.json's: replay again")
    opt, dam = defaultdict(int), defaultdict(int)
    for r in an:
        for k, n in r["opt"]["args"].items():
            opt[k.rsplit("|", 1)[-1]] += n
        for k, n in r["fidelity"]["submit_dam_offers"].items():
            dam[k] += n
    compared = sum(n for k, n in dam.items() if k.startswith("curve_") and k not in
                   ("curve_hours_omitted", "curve_hour_not_in_proposal"))
    default = re.search(r"(\w+) \(default\): DAM curves", json.dumps(tool_specs(s["layer"])))[1]
    return {"model": card.BEAM, "windows": len(ids), "unit": "points of C", "gap": round(gap, 4), "effects": eff,
            "storm": {"front": storm, "name": name, "windows": len(per_front[storm])},
            "optimize": {"calls": sum(opt.values()), "physical": opt["physical"]},
            "dam_curve_hours": {"exact": dam["curve_exact"], "compared": compared},
            "wakes": round(float(np.mean([r["timing"]["wakes"] for r in an])), 2),
            "last_submit_h": round(float(np.mean([r["timing"]["hours_after_last_submit"] for r in an])), 2),
            "planner": setting(s["layer"]) | {"default": default},
            "playbook": beam_playbook(folder / "beam-playbook", s, g, storm, opt["spread"], sum(opt.values()), R)}


PLAYBOOK = ROOT / "bench" / "harness" / "bench-opencode-beam-playbook" / "PLAYBOOK.md"
PLAYBOOK_SHA = "0dc7cb47eb500057"
"""The playbook as pre-registered and frozen (docs/prereg/v4-bench.md), the prefix of its sha256."""


def beam_playbook(d: Path, s: dict, g: dict, storm: str, spread: int, calls: int, R) -> dict:
    """The playbook pilot in results/desk-v4-bench/beam-playbook (pre-registered in docs/prereg/v4-bench.md, not a
    leaderboard entry): Beam-1.0 with the desk playbook on the bench's windows. C and its paired difference from Beam's
    bench run, in points, over every window, July and August, and outside the storm front, recomputed from score.json's
    windows with the bench's block bootstrap; Beam's side must be the bench's grades and the diagnosis's calls, the
    recomputation score.json's own, and the playbook the one that ran."""
    sc = json.loads((d / "score.json").read_text())
    w = {x["task_id"]: x for x in sc["windows"]}
    if w.keys() != g.keys() or any(abs(w[t]["beam_C"] - g[t]["capture"]) > 1e-6 or w[t]["front"] != g[t]["front"]
                                   or w[t]["beampb_status"] != "scored" for t in g):
        raise SystemExit("the playbook run's windows are not the bench's Beam-1.0 windows: score it again")
    if hashlib.sha256(PLAYBOOK.read_bytes()).hexdigest()[:len(PLAYBOOK_SHA)] != PLAYBOOK_SHA:
        raise SystemExit(f"{PLAYBOOK.relative_to(ROOT)} is not the playbook that ran")
    before, after = sc["process"]["beam"], sc["process"]["beampb"]
    if (before["spread_calls"], before["optimize_ok"]) != (spread, calls):
        raise SystemExit("the playbook run's process metrics for Beam-1.0 are not the diagnosis's: replay them again")
    ids = sorted(w)

    def scope(key: str, keep) -> dict:
        k = [t for t in ids if keep(w[t])]
        p = R.paired([100 * w[t]["beampb_C"] for t in k], [100 * w[t]["beam_C"] for t in k], [w[t]["front"] for t in k])
        ref = sc["paired"][key]["dC"]
        if any(abs(a - 100 * x) > 0.01 for a, x in zip([p["mean"], *p["ci"]], [ref["mean"], *ref["ci"]], strict=True)):
            raise SystemExit(f"score.json's paired difference over {key} is not its windows': score it again")
        return {"windows": len(k), "fronts": p["fronts"], "mean": p["mean"], "ci": p["ci"],
                "ahead": round(p["ahead"] * len(k)), "fronts_ahead": p["fronts_ahead"]}

    scopes = {"all": scope("all", lambda x: True), "jul_aug": scope("jul_aug", lambda x: x["split"] == "post_cutoff"),
              "calm": scope(f"outside_{storm}", lambda x: x["front"] != storm)}
    if scopes["all"]["ci"][0] <= 0 or scopes["calm"]["ci"][0] > 0:
        raise SystemExit("the playbook section says the gain excludes zero over every window and not outside the "
                         "storm: rewrite it")
    C = R.boot([100 * w[t]["beampb_C"] for t in ids], [w[t]["front"] for t in ids])
    spend = sc["spend"]
    return {"C": {"mean": C["mean"], "ci": C["ci"]}, "scopes": scopes, "lines": len(PLAYBOOK.read_text().splitlines()),
            "spread": {"before": [before["spread_calls"], before["optimize_ok"]],
                       "after": [after["spread_calls"], after["optimize_ok"]]},
            "late_h": {"before": [before["hours_after_last_accepted_mean"], before["hours_after_last_accepted_median"]],
                       "after": [after["hours_after_last_accepted_mean"], after["hours_after_last_accepted_median"]]},
            "usd_list": sc["beampb"]["cost"]["usd_per_window"],
            "usd_metered": {"before": spend["beam"]["metered_per_graded_window_usd"],
                            "after": spend["beampb"]["metered_per_graded_window_usd"]}}


def check_beam(f: dict, b: dict, s: dict, fm: dict, card) -> list[str]:
    """The article's Beam-1.0 subsection and the card's section read the same facts.json beam, which must be beam.json's
    diagnosis as the card formats it; its last accepted offer, failures.json's, must be the diagnosis's last submit."""
    want = card.beam_facts(b, s, fm)
    bad = [f"F.beam.{k} = {f['beam'].get(k)!r}, where beam.json gives {v!r}" for k, v in want.items()
           if f["beam"].get(k) != v]
    if not want["late"] == f"{b['last_submit_h']:.1f}" == want["pb"]["late0"]:
        bad.append(f"Beam-1.0's last accepted offer, {want['late']} h, is not the diagnosis's last submit or the "
                   "playbook run's replay of Beam")
    return bad


def spearman(a: list[float], b: list[float]) -> float:
    ra, rb = (np.argsort(np.argsort(x)).astype(float) for x in (a, b))
    return float(np.corrcoef(ra, rb)[0, 1])


def watch(repo: Path, s: dict, scored: list[dict], card) -> dict:
    """The rollout the viewer opens on: the bench's costliest run, at the minute of its window's highest real-time
    price, with what it lost and what the real operator made there. Why it matters says it lost nearly twice what the
    same model made at the same battery a week earlier."""
    g = min(scored, key=lambda x: x["p"])
    if (g["model"], g["task_id"]) != COSTLIEST:
        raise SystemExit(f"the costliest run is now {g['model']} on {g['task_id']}: rewrite the rollout's note")
    same = [x for x in scored if x["model"] == g["model"] and x["site"] == g["site"] and x["dates"][0] < g["dates"][0]]
    prev = max(same, key=lambda x: x["dates"][0])
    days = (date.fromisoformat(g["dates"][0]) - date.fromisoformat(prev["dates"][0])).days
    if not (prev["p"] > 0 and 1.7 <= -g["p"] / prev["p"] <= 2.0 and days <= 8):
        raise SystemExit(f"the costliest run lost {-g['p'] / prev['p']:.2f} times what {g['model']} made at "
                         f"{g['site']} {days} days earlier, not nearly twice a week earlier: rewrite Why it matters")
    ep = json.loads(gzip.decompress((repo / "results" / "desk-v4-bench" / g["episode"]).read_bytes()))
    d, i, top = max(((d, i, x) for d in ep["dates"] for i, x in enumerate(ep["rt"][d]["spp"])), key=lambda r: r[2])
    t = (date.fromisoformat(d) - date.fromisoformat(ep["dates"][0])).days * 1440 + i * 1440 // len(ep["rt"][d]["spp"])
    return {"name": s["models"][g["model"]]["name"], "site": g["site"], "region": g["region"],
            "span": span(g["dates"][0], g["dates"][-1]), "day": f"{date.fromisoformat(d):%-d %B}",
            "at": f"{t % 1440 // 60:02d}:{t % 60:02d}", "spike": usd(top),
            "da": usd(ep["dam"][d]["spp"][t % 1440 // 60]),
            "lost": usd(-g["p"]), "op": usd(g["p_operator_actual"]),
            "app": f"{card.bench_replay(g['model'], g['task_id'])}&t={t}"}


def why_tiles(w: dict) -> dict:
    """Why it matters' tiles: the outside figures (TILES), each checked against its sources' quotes, and the rollout's
    own spike against the day-ahead price at that hour."""
    tiles = []
    for t in TILES:
        quotes = " ".join(SOURCES[k][2] for k in t["src"])
        for tok in (t["value"], *(b for _, b in t["bars"])):
            if not re.search(rf"(?<![\d,.]){re.escape(tok)}(?![\d,])", quotes):
                raise SystemExit(f"a Why it matters tile shows {tok!r}, which its sources' quotes do not hold")
        scale = t.get("scale")
        show = (lambda x, k=scale: f"{amount(x) / k:.1f}" if k else x)  # noqa: E731
        top = max(amount(b) for _, b in t["bars"])
        tiles.append({"value": show(t["value"]), "unit": t.get("unit"), "desc": t["desc"],
                      "bars": [{"label": a, "text": f"{show(b)} {t['unit']}" if t.get("scale") else b,
                                "w": f"{amount(b) if t.get('share') else 100 * amount(b) / top:.1f}%",
                                "hot": len(t["bars"]) == 1 or b == t["value"] or b.startswith(f"{t['value']}/")}
                               for a, b in t["bars"]],
                      "src": [{"label": SOURCES[k][0], "url": SOURCES[k][1]} for k in t["src"]]})
    tiles.append({"value": w["spike"], "unit": "/MWh",
                  "desc": f"real-time price at Battery {w['site']} at {w['at']} on {w['day']}, the rollout's spike, "
                          "against that hour's day-ahead price",
                  "bars": [{"label": "Day ahead", "text": w["da"], "hot": False,
                            "w": f"{100 * amount(w['da']) / amount(w['spike']):.1f}%"},
                           {"label": "Real time", "text": w["spike"], "w": "100.0%", "hot": True}],
                  "src": [{"label": "This benchmark, replayed", "url": w["app"]}]})
    return {"tiles": tiles}


def amount(x: str) -> float:
    return float(re.sub(r"[^\d.]", "", x))


def reward(s: dict, grades: list[dict], card) -> dict:
    """How the reward works: the film's window, every model's settled P, C and R there, the references, and the worked
    example of the film's run."""
    h = s["hero"]
    gs = [g for g in grades if g["task_id"] == h["task_id"] and g["status"] == "scored"]
    g, r = next(x for x in gs if x["model"] == h["model"]), gs[0]
    if g["floored"] or not g["valid"]:
        raise SystemExit("the reward section's example assumes the film's run is valid and its planner unfloored")
    c = (g["p"] - r["p_idle"]) / (r["p_hind"] - r["p_idle"])
    if f"{card.pc(c)}%" != f"{card.pc(g['capture'])}%":
        raise SystemExit("the worked example's arithmetic does not give the grader's C")
    cap = lambda p: f"{card.pc((p - r['p_idle']) / (r['p_hind'] - r['p_idle']))}%"  # noqa: E731
    return {"name": s["models"][g["model"]]["name"], "site": g["site"], "P": usd(g["p"]), "idle": usd(r["p_idle"]),
            "hind": usd(r["p_hind"]), "C": f"{card.pc(g['capture'])}%", "plan": usd(r["p_anchor"]),
            "planC": cap(r["p_anchor"]), "op": usd(r["p_operator_actual"]), "opC": cap(r["p_operator_actual"]),
            "beats": str(sum(x["p"] > r["p_anchor"] for x in gs)), "of": str(len(gs))}


def reward_chart(s: dict, grades: list[dict]) -> dict:
    """What the reward chart draws: the film's window, its references and every model's P, C and R there."""
    h = s["hero"]
    gs = sorted((g for g in grades if g["task_id"] == h["task_id"] and g["status"] == "scored"), key=lambda g: -g["p"])
    r = gs[0]
    return {"refs": {k: r[k] for k in ("p_idle", "p_anchor", "p_hind", "p_operator_actual", "p_operator_replay")},
            "den": r["p_anchor"] - r["p_idle"],
            "runs": [{"key": g["model"], "name": s["models"][g["model"]]["name"], "tag": s["models"][g["model"]]["tag"],
                      "harness": s["models"][g["model"]]["harness"], "p": g["p"], "c": g["capture"], "r": g["reward"],
                      "valid": g["valid"]} for g in gs]}


def train(s: dict, grades: list[dict], card) -> dict:
    """Training on GridSimEnv: the recipe from the desk-distill pre-registration and the trainer's own defaults, and
    the result from the benchmark's rows, each checked against the pre-registration's numbers."""
    pre, code = re.sub(r"\s+", " ", DISTILL.read_text()), TRAINER.read_text()
    sft = next(m for m in s["models"].values() if m.get("distilled"))
    base, pair = s["models"][sft["family"]], s["paired"][f"{sft['key']}-{sft['family']}"]["all"]["C"]

    def arg(name: str) -> str:
        return re.search(rf'"--{name}", type=\w+, default=([\d.e-]+)\)', code)[1]

    def find(pat: str) -> re.Match:
        return re.search(pat, pre)

    def pts(x: str) -> str:
        return card.pc(float(x.replace("−", "-")), 1, True)

    pc = lambda x: f"{card.pc(x)}%"  # noqa: E731
    kept = find(r"\((\d+) kept, ([\d.]+)M tokens, ([\d.]+)M trained\)")
    held = find(r"C\(student\) − C\(base\) = ([+−-][\d.]+), 95% window-block interval \[([−-]?[\d.]+), "
                r"([+−-]?[\d.]+)\]")
    bench = find(r"C\(student\) − C\(base\) = ([+−-][\d.]+), 95% front-block interval \[([+−-]?[\d.]+), "
                 r"([+−-]?[\d.]+)\].*?student better on (\d+)")
    refused = find(r"refused DAM / RT / COP submits \| ([\d.]+)% / [\d.]+% / [\d.]+% \| ([\d.]+)% ")
    box = find(r"Base ran on one ([\w.]+) \(one ([\w ]+?), ")
    cap, ctx = int(find(r"the cap is ([\d,]+)")[1].replace(",", "")), int(find(r"--max-model-len (\d+)")[1])
    accum, lead = int(arg("grad-accum")), s["models"][s["order_by_C"][0]]
    out = {"windows": find(r"\*\*Training, (\d+) site-windows")[1], "rows": find(r"(\d+) rows, [\d.]+M tokens")[1],
           "kept": kept[1], "tokens": f"{round(float(kept[2]))}M", "trained": f"{float(kept[3]):.1f}M",
           "cap": f"{cap // 1000}k", "rank": arg("rank"), "alpha": str(2 * int(arg("rank"))), "lr": arg("lr"),
           "epochs": str(int(float(arg("epochs")))), "accum": str(accum), "steps": str(-(-int(kept[1]) // accum)),
           **TRAIN_RUN, "base": pc(base["all"]["C"]["mean"]), "sft": pc(sft["all"]["C"]["mean"]),
           "planner": pc(s["references"]["anchor"]["all"]["C"]["mean"]), "sol": pc(lead["all"]["C"]["mean"]),
           "gain": card.pc(pair["mean"], 1, True), "lo": card.pc(pair["ci"][0], 1, True),
           "hi": card.pc(pair["ci"][1], 1, True), "better": str(round(pair["ahead"] * pair["n"])), "n": str(pair["n"]),
           "usd": card.bench_usd(sft["cost"]["usd_per_window"]), "held": find(r"Over the committed (\d+) held-out")[1],
           "hgain": pts(held[1]), "hlo": pts(held[2]), "hhi": pts(held[3]),
           "hplan": card.pc(float(find(r"the anchor itself is ([\d.]+) above base")[1])),
           "refused": f"{refused[1]}%", "refusedSft": f"{refused[2]}%", "base_name": base["name"],
           "mem": find(r"of the GPU's (\d+) GiB")[1], "gpu_name": box[2], "box": box[1], "ctx": f"{ctx:,}",
           "prereg": f"{REPO_URL}/blob/main/docs/prereg/desk-distill.md",
           "rows_code": f"{REPO_URL}/blob/main/scripts/desk_distill_sft.py",
           "code": f"{REPO_URL}/blob/main/scripts/desk_distill_train.py"}
    if (pts(bench[1]), pts(bench[2]), pts(bench[3]), bench[4]) != (out["gain"], out["lo"], out["hi"], out["better"]):
        raise SystemExit("the benchmark's paired gain for the fine-tuned model differs from the pre-registration's")
    return out


def train_chart(s: dict, grades: list[dict]) -> dict:
    """What the training chart draws: each bench window's C for the base model, the fine-tuned one and the planner."""
    sft = next(m for m in s["models"].values() if m.get("distilled"))
    by = {(g["model"], g["task_id"]): g for g in grades if g["status"] == "scored"}
    rows = []
    for t in sorted({g["task_id"] for g in grades}):
        a, b = by[(sft["family"], t)], by[(sft["key"], t)]
        front = next(f for f in s["fronts"] if f["front"] == a["front"])
        rows.append({"task": t, "site": a["site"], "dates": a["dates"], "kind": front["kind"], "split": a["split"],
                     "base": a["capture"], "sft": b["capture"],
                     "plan": (a["p_anchor"] - a["p_idle"]) / (a["p_hind"] - a["p_idle"])})
    return {"rows": rows, "means": {"base": s["models"][sft["family"]]["all"]["C"]["mean"],
                                    "sft": sft["all"]["C"]["mean"],
                                    "plan": s["references"]["anchor"]["all"]["C"]["mean"],
                                    "lead": s["models"][s["order_by_C"][0]]["all"]["C"]["mean"]},
            "names": {"base": s["models"][sft["family"]]["name"], "sft": sft["name"],
                      "lead": s["models"][s["order_by_C"][0]]["name"]}}


def links(s: dict, card) -> dict:
    """The Links section: the environment, the replays and results, the dataset, the code, the pre-registration and
    AgentEnv's training guide."""
    return {"env": TRY_SPACE, "replays": VIEWER, "results": f"{card.APP}/results.html?v=bench", "dataset": card.DATASET,
            "code": REPO_URL, "prereg": f"{REPO_URL}/blob/main/{s['run']['prereg']}", "training": TRAINING_DOCS}


def banner(folder: Path, s: dict, grades: list[dict], card) -> dict:
    """The hero banner: the film's model on the film's front at all four batteries, each node's real-time price, the
    battery's state of charge and metered output every 15 minutes over the three days, its wake-ups, its settled P and
    the real operator's as it ran, and the film's replay."""
    h = s["hero"]
    lead = next(g for g in grades if g["model"] == h["model"] and g["task_id"] == h["task_id"])
    rows = sorted((g for g in grades if g["model"] == h["model"] and g["front"] == lead["front"]
                   and g["status"] == "scored"), key=lambda g: g["site"])
    if len(rows) != 4:
        raise SystemExit(f"banner: {len(rows)} {h['model']} windows on the {lead['front']} front, expected 4")
    sites = []
    for g in rows:
        ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
        rt, c = [ep["rt"][iso] for iso in ep["dates"]], ep["site"]["card"]
        soc, end = [x for r in rt[:-1] for x in r["soc_mwh"][:-1:3]] + rt[-1]["soc_mwh"][::3], 1440 * len(rt)
        sites.append({"task": g["task_id"], "name": c["name"], "region": c["region"], "size": c["size"],
                      "e_max": ep["site"]["e_max_mwh"], "p_max": ep["site"]["hsl_mw"],
                      "rt": [round(x, 2) for r in rt for x in r["spp"]], "soc": [round(x, 2) for x in soc],
                      "mw": [round(float(np.mean(r["metered_mw"][i:i + 3])), 1) for r in rt for i in range(0, 288, 3)],
                      "wakes": [w["t"] for w in ep["wakes"] if w.get("turn") is not None and 0 <= w["t"] < end],
                      "p": round(g["p"], 2), "p_operator_actual": g["p_operator_actual"]})
    front = next(f for f in s["fronts"] if f["front"] == lead["front"])
    return {"days": lead["dates"], "span": span(lead["dates"][0], lead["dates"][-1]), "kind": front["kind"],
            "model": s["models"][h["model"]]["name"], "lead": h["task_id"],
            "regions": {k: {"lon": x, "lat": y} for k, (x, y) in REGIONS.items()}, "texas": texas(), "sites": sites,
            "replay": {"task": h["task_id"], "url": card.bench_replay(h["model"], h["task_id"])},
            "source": "ERCOT's node prices as the episodes recorded them; Texas: U.S. Census Bureau via us-atlas"}


def texas() -> list:
    """Texas from the U.S. Census Bureau's cartographic boundaries (us-atlas 3.0.1, TopoJSON), simplified."""
    cache = ROOT / "cache" / "article" / "states-10m.json"
    if not cache.is_file():
        cache.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(ATLAS, timeout=60) as r:
            cache.write_bytes(r.read())
    topo = json.loads(cache.read_text())
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        q = np.cumsum(np.array(arc, float), axis=0)
        arcs.append(np.column_stack([q[:, 0] * sx + tx, q[:, 1] * sy + ty]))
    geom = next(g for g in topo["objects"]["states"]["geometries"] if g["id"] == "48")
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    ring = max((np.vstack([arcs[i] if i >= 0 else arcs[~i][::-1] for i in poly[0]]) for poly in polys), key=len)
    return [[round(x, 3), round(y, 3)] for x, y in simplify(ring, 0.02)]


def simplify(pts: np.ndarray, tol: float) -> np.ndarray:
    """Douglas-Peucker, iterative."""
    keep = np.zeros(len(pts), bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = pts[i], pts[j]
        ab, rest = b - a, pts[i + 1:j] - a
        n = np.hypot(*ab)
        dist = np.hypot(rest[:, 0], rest[:, 1]) if n < 1e-9 else np.abs(ab[0] * rest[:, 1] - ab[1] * rest[:, 0]) / n
        k = int(np.argmax(dist))
        if dist[k] > tol:
            keep[i + 1 + k] = True
            stack += [(i, i + 1 + k), (i + 1 + k, j)]
    return pts[keep]


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


def check_rendered(f: dict, s: dict) -> None:
    """After the build: every fact the prose names appears on the page as facts.json formats it, a link as an href."""
    html = (APP / "dist" / "index.html").read_text()
    text = re.sub(r"<[^>]+>", "", html).replace("&#36;", "$").replace("&amp;", "&").replace("&#39;", "'")
    known, links = leaves(f), html.replace("&amp;", "&")
    used = {e for p in CHAPTERS.glob("*.mdx") for e in FACT.findall(p.read_text())}
    missing = [f"{e} = {known[e]!r}" for e in sorted(used)
               if not ((f'href="{known[e]}"' in links or f'src="{known[e]}"' in links) if known[e].startswith("https://")
                       else known[e] in text or f'"{known[e]}"' in links)]
    missing += [f"media/{p.name}" for p in FILMS if not (APP / "dist" / "media" / p.name).is_file()]
    hero = json.loads((DATA / "banner.json").read_text())
    missing += [] if 'class="gs-banner"' in html and hero["model"] == f["lead"]["name"] and \
        hero["replay"]["url"] == f["lead"]["replay"] else ["the hero banner, on the film's run"]
    missing += [f"the tile {t['value']} {t['unit'] or ''}" for t in f["why"]["tiles"]
                if t["value"] not in text or any(b["text"] not in text for b in t["bars"])]
    missing += [f"a tile's source {x['url']}" for t in f["why"]["tiles"] for x in t["src"]
                if f'href="{x["url"]}"' not in links]
    built = {n: json.loads((APP / "dist" / "data" / n).read_text())
             for n in ("facts.json", "failures.json", "beam.json")}
    missing += check_replan(built["facts.json"], built["failures.json"])
    missing += check_beam(built["facts.json"], built["beam.json"], s, built["failures.json"],
                          module("hub_dataset", "scripts/hub_dataset.py"))
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
          "page's descriptions, the films and the cards' pictures, the eval's re-planning finding on the failure "
          "charts' numbers, and the Beam-1.0 section on the diagnosis's beam.json")


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
