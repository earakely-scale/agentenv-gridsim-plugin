"""The GridSimEnv desk article: a research-article Space built with tfrere's research-article-template (Astro, MDX
chapters, D3 embeds) under hub/article. It leads with the v4 benchmark, read from results/desk-v4-bench
(scripts/desk_bench_results.py) and drawn by the dataset card's own bench charts (hub/desk-charts/charts.js); then the
desk's development ladder, read from results/overview/desk.json (scripts/hub_desk.py) and the desk's committed episodes
and grades. The prose states no number of its own: it reads them from facts.json, which this script formats from
summary.json and desk.json under the same rules as the dataset card and the viewer Space, and the front matter's
description is the card's pitch, written here.

    .venv/bin/python scripts/hub_article.py --desk-repo DIR             # the data, the numbers check, the scans
    .venv/bin/python scripts/hub_article.py --desk-repo DIR --build     # then npm ci (once) and npm run build
    .venv/bin/python scripts/hub_article.py --desk-repo DIR --publish   # then upload hub/article to the Space

DIR is a checkout of the desk (results/desk-v<N>/, data/desk/); the repository itself once the desk is on main.
"""

import argparse
import gzip
import importlib.util
import json
import re
import subprocess
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import numpy as np
from agentenv_hf.scan import known_values, scan

ROOT = Path(__file__).resolve().parents[1]
ARTICLE = ROOT / "hub" / "article"
APP = ARTICLE / "app"
DATA = APP / "src" / "content" / "assets" / "data"
CHAPTERS = APP / "src" / "content" / "chapters"
SPACE = "earakely-scale/GridSimEnv"
DESK = ROOT / "results" / "overview" / "desk.json"
MDX = APP / "src" / "content" / "article.mdx"
CHARTS = ROOT / "hub" / "desk-charts" / "charts.js"
OPENCODE = ROOT / "bench" / "harness" / "bench-opencode" / "opencode.json"
ATLAS = "https://cdn.jsdelivr.net/npm/us-atlas@3.0.1/states-10m.json"
STALE = ("results.json", "anatomy.json", "advantage.json", "timeline.json")
CURVE = ("v2", "desk-v2-2026-08-23-S02", "sol", 18)
REGIONS = {"Far West": (-102.4, 31.3), "North": (-97.0, 32.9), "Houston": (-95.4, 29.8), "South": (-98.3, 28.2)}
CONSTANT = {"$5,000", "$2,000", "−$250", "$250", "0.2", "0.8", "0.1", "1.0", "0.0", "95%"}
NUMBER = re.compile(r"[−+-]?⁠?\\?\$[\d,]+(?:\.\d+)?k?|[−+-]?\d+\.\d+¢|[−+-]?\b\d+\.\d{2,}\b|\b\d+(?:\.\d+)?%")
LEAK = re.compile(r"s3://|amazonaws|airops-runs|scale\.com|\bFD-\d|\bsk-[A-Za-z0-9_-]{12,}|litellm\.[a-z]|ocp-apim|"
                  r"b2clogin|ercot-api|\bhf_[A-Za-z0-9]{30,}|\b(?:10|172|192)\.\d+\.\d+\.\d+\b|"
                  r"gridsim/adapters|\bi-0[0-9a-f]{8,}|object storage \(`", re.I)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--desk-repo", type=Path, default=ROOT,
                    help="A checkout of the desk: its results and episodes feed the charts, its packs name the real "
                         "sites and operators the article must not.")
    ap.add_argument("--build", action="store_true", help="npm ci (once) and npm run build in hub/article/app.")
    ap.add_argument("--publish", action="store_true", help="Upload hub/article to the Space.")
    args = ap.parse_args()
    desk = json.loads(DESK.read_text())
    if not (args.desk_repo / "results" / "desk-v2" / "summary.json").is_file():
        raise SystemExit(f"{args.desk_repo} holds no desk results: pass --desk-repo")
    card = module("hub_dataset", "scripts/hub_dataset.py")
    s, grades = card.bench_read(args.desk_repo / "results" / "desk-v4-bench")
    DATA.mkdir(parents=True, exist_ok=True)
    out = {"desk.json": desk, "facts.json": facts(desk) | {"bench": bench(s, grades, desk, card)},
           "bench.json": {k: s[k] for k in ("fake", "n_windows", "n_fronts", "splits", "fronts", "plot")},
           "banner.json": hero(args.desk_repo / "results" / "desk-v4-bench", s, grades),
           "curve.json": curve(args.desk_repo, desk)}
    for name in STALE:
        (DATA / name).unlink(missing_ok=True)
    for name, obj in out.items():
        (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        print(f"{name:16} {(DATA / name).stat().st_size / 1e3:7.1f} kB")
    (APP / "public" / "scripts" / "desk-charts.js").write_bytes(CHARTS.read_bytes())
    describe(out["facts.json"]["bench"]["pitch"], out["banner.json"])
    check_prose(out["facts.json"])
    check_order(s)
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


def h(x: float, nd: int = 3, sign: bool = False) -> str:
    """Half-up on the stored decimal, a true minus sign, as the dataset card and the desk page print C."""
    q = abs(Decimal(str(x))).quantize(Decimal(1).scaleb(-nd), ROUND_HALF_UP)
    return f"{'−' if x < 0 and q else '+' if sign else ''}{q}"


def ci(c: list[float], nd: int = 3, sign: bool = False) -> str:
    return f"[{h(c[0], nd, sign)}, {h(c[1], nd, sign)}]"


def usd(x: float, sign: bool = False) -> str:
    """Whole dollars as the results READMEs print them, a word joiner keeping the sign on the amount."""
    v = f"{abs(x):,.0f}"
    s = "" if v == "0" else "−" if x < 0 else "+" if sign else ""
    return f"{s}⁠${v}" if s else f"${v}"


def usd_ci(c: list[float], sign: bool = False) -> str:
    return f"[{usd(c[0], sign)}, {usd(c[1], sign)}]"


def cents(x: float) -> str:
    return f"{'−' if x < 0 else '+' if x > 0 else ''}{abs(x) * 100:.1f}¢"


def day(iso: str) -> str:
    return f"{date.fromisoformat(iso):%-d %B %Y}"


def span(iso: str, n: int) -> str:
    a = date.fromisoformat(iso)
    b = date.fromordinal(a.toordinal() + n - 1)
    return day(iso) if n == 1 else f"{a:%-d} to {b:%-d %B %Y}" if a.month == b.month else f"{a:%-d %B} to {b:%-d %B %Y}"


def unit(v: dict) -> str:
    return "battery-day" if v["days_per_task"] == 1 else f"{v['days_per_task']}-day window"


def facts(d: dict) -> dict:
    """Every number the prose states, formatted from desk.json; the chapters read them as {F.v2.m.sol.C} and so on."""
    out = {"across": d["across"], "resamples": f"{d['versions'][0]['ci']['resamples']:,}", "models": models(d)}
    for v in d["versions"]:
        f = {"name": v["name"], "n": str(v["n_tasks"]), "blocks": str(v["n_days"]), "block": v["block"],
             "unit": unit(v), "from": day(v["dates"][0]), "to": day(v["dates"][1]), "ref": v["ref"], "m": {}, "r": {},
             "pair": {}}
        for m in v["models"]:
            f["m"][m["key"]] = {
                "name": m["name"], "C": h(m["C"]["mean"]), "Cci": ci(m["C"]["ci"]), "P": usd(m["P"]["mean"]),
                "Pci": usd_ci(m["P"]["ci"]), "R": h(m["R"]["mean"], 2),
                "vsOp": usd(m["P_minus_operator_replay"]["mean"], True),
                "vsOpci": usd_ci(m["P_minus_operator_replay"]["ci"], True),
                "vsA": usd(m["P_minus_anchor"]["mean"], True), "vsAci": usd_ci(m["P_minus_anchor"]["ci"], True),
                "valid": f"{100 * m['valid']:.0f}%"}
        for r in v["references"]:
            f["r"][r["key"]] = {"C": h(r["C"]["mean"]), "P": usd(r["P"]["mean"])}
        for p in v["paired"]:
            if "C" in p:
                f["pair"][f"{p['a']}_{p['b']}"] = {"C": h(p["C"]["mean"], 3, True), "Cci": ci(p["C"]["ci"], 3, True)}
        sv = v.get("sensitivity") or {}
        w = sv.get("without") or sv.get("derived")
        if w and sv.get("carried"):
            per = sv["per_day_mean_P"][w["days"][0]]
            f["sens"] = {"day": day(w["days"][0]), "span": span(w["days"][0], v["days_per_task"]),
                         "n": str(w["n_tasks"]),
                         "on": {x: usd(y) for x, y in {**per["models"], **per["references"]}.items() if y is not None},
                         "without": {x: usd(b["P"]["mean"]) for g in ("models", "references")
                                     for x, b in w["means"][g].items()}}
        if any(m.get("ancillary") for m in v["models"]):
            f["as"] = {m["key"]: {"awards": str(m["ancillary"]["episodes_with_awards"]),
                                  "lines": usd(m["lines"].get("dam_as_capacity", 0.0)
                                               + m["lines"].get("rt_as_imbalance", 0.0), True),
                                  "refused": str(sum(m["ancillary"]["rejected_codes_total"].values())),
                                  "shape": str(m["ancillary"]["rejected_codes_total"].get("ASO-02", 0))}
                       for m in v["models"] if m.get("ancillary")}
        if pi := v.get("price_impact"):
            f["impact"] = {k: {"sales": cents(x["sales_mwh_weighted_usd_per_mwh"]),
                               "revenue": usd(x["revenue_effect_usd_per_episode"], True),
                               "max": f"${x['max_abs_usd_per_mwh']:.2f}"} for k, x in pi.items()}
        if vs := v.get("versus"):
            f["versus"] = {k: {"P": usd(b["P"]["mean"], True), "Pci": usd_ci(b["P"]["ci"], True)}
                           for k, b in vs["models"].items()}
        out[v["version"]] = f
    return out


def models(d: dict) -> dict:
    """Each model's label and the settings the methods state, from desk.json's `models`."""
    out = {}
    for k, s in d["models"].items():
        f = {"name": s["name"], "setting": s["setting"], "label": s["label"], "id": s["model_id"]}
        if s["reasoning_effort"]:
            f |= {"effort": s["reasoning_effort"], "api": s["api"]}
        if s["thinking"] is not None:
            f |= {"thinking": "on" if s["thinking"] else "off", "checkpoint": s["checkpoint"],
                  "temperature": str(s["temperature"]), "top_p": str(s["top_p"]), "server": s["server"],
                  "dtype": s["dtype"], "parser": s["tool_parser"], "context": f"{s['context_tokens']:,}",
                  "prompt": f"{s['prompt_tokens'] // 1000}k", "out": f"{s['max_output_tokens']:,}"}
        out[k] = f
    return out


def bench(s: dict, grades: list[dict], d: dict, card) -> dict:
    """The v4 benchmark under the dataset card's rules (scripts/hub_dataset.py, the card): from its summary.json and
    grades, the card's pitch, bullets, notes and captions word for word, C in % half-up on the stored decimal, R to two
    places, cost as the card prints it, and the open model's sampling as its harness config set it."""
    if s["fake"]:
        raise SystemExit("results/desk-v4-bench holds fake data; the article states real runs only")
    block, refs = card.bench_block(s, grades, d).splitlines(), s["references"]
    how = {x["head"]: x for x in map(bold, card.bench_how(s))}
    side = {k: {"name": card.bench_side(s, sp), "note": card.BENCH_SIDE[sp], "n": str(s["splits"][sp]["windows"]),
                "fronts": str(len(s["splits"][sp]["fronts"]))} for k, sp in zip(SIDES, card.BENCH_SPLITS, strict=True)}
    out = {"pitch": card.bench_pitch(s).strip("*"), "n": str(s["n_windows"]), "fronts": str(s["n_fronts"]),
           "sites": str(len(s["sites"])), "framework": s["run"]["framework"], "side": side,
           "m": {m["key"]: bench_model(m, s, grades, card) for m in card.bench_models(s)},
           "r": {k: {x: f"{card.pc(refs[k][sc]['C']['mean'])}%" for x, sc in SCOPES} | {"label": label}
                 for k, label in card.BENCH_REFS.items()},
           "say": dict(zip(("lead", "operator"), map(bold, card.bench_bullets(s)), strict=False)),
           "text": {k: s["text"][k] for k in ("halves", "reliability", "rule")},
           "how": {"harness": how["Each model in a native agent harness,"], "internet": how["No internet."],
                   "tools": how["The desk's 11 tools over MCP,"]},
           "limits": {f"l{i}": bold(x) for i, x in enumerate(card.bench_limits(s))},
           "route": colon(next(x for x in s["deviations"] if x.startswith("Route C"))),
           "gemini": colon(next(x for x in s["deviations"] if x.startswith("Gemini"))),
           "cap": {"cost": small(block, "C × 100"), "table": small(block, "C, hindsight capture")}}
    q = json.loads(OPENCODE.read_text())
    agent, opts = q["agent"]["build"], next(iter(q["provider"].values()))["models"][s["models"]["qwen"]["model_id"]]
    if opts["options"]["chat_template_kwargs"]["enable_thinking"] != (s["models"]["qwen"]["setting"] == "thinking on"):
        raise SystemExit(f"{OPENCODE.name} and summary.json disagree on Qwen3-4B's thinking")
    out["m"]["qwen"] |= {"temperature": str(agent["temperature"]), "top_p": str(agent["top_p"]),
                         "top_k": str(opts["options"]["top_k"])}
    return out


SIDES = ("pre", "post")
SCOPES = (("C", "all"), ("pre", "pre_cutoff"), ("post", "post_cutoff"))


def bench_model(m: dict, s: dict, grades: list[dict], card) -> dict:
    scored = [g for g in grades if g["model"] == m["key"] and g["status"] == "scored"]
    c, gap, valid = m["cost"], card.bench_pair(s, m["key"], "operator_replay"), sum(g["valid"] for g in scored)
    out = {"name": m["name"], "harness": m["harness"], "version": m["harness_version"], "setting": m["setting"],
           "n": str(m["n"]), "valid": str(valid), "invalid": str(len(scored) - valid),
           "R": h(m["all"]["R"]["mean"], 2), "Rci": ci(m["all"]["R"]["ci"], 2),
           "usd": card.bench_usd(c["usd_per_window"]), "spent": card.bench_usd(c["usd_all_attempts"]),
           "op": card.pts_ci(gap, True)}
    for k, sc in SCOPES:
        b = m[sc]["C"]
        out |= {k: f"{card.pc(b['mean'])}%", f"{k}ci": f"[{card.pc(b['ci'][0])}, {card.pc(b['ci'][1])}]"}
    return out | ({"basis": "GPU time"} if c["basis"] == "gpu_time" else {})


BOLD = re.compile(r"\*\*(.+?)\*\*\s*(.*)", re.S)


def bold(x: str) -> dict:
    """A card bullet, its bold lead apart from the rest."""
    m = BOLD.fullmatch(x)
    return {"head": m[1], "text": m[2]}


def colon(x: str) -> dict:
    """A deviation as the card logs it, its subject apart from the rest."""
    head, text = x.split(": ", 1)
    return {"head": head, "text": text}


def small(block: list[str], head: str) -> str:
    """One of the card's notes under the benchmark's charts and table, by its first words."""
    return next(x for x in block if x.startswith(f"<small>{head}")).removeprefix("<small>").removesuffix("</small>")


def hero(folder: Path, s: dict, grades: list[dict]) -> dict:
    """The benchmark's lead front at all four batteries: the windows of summary.json's hero model on the front of its
    hero window, the dataset card's lead GIF, each battery's node prices, state of charge and metered output every 15
    minutes over the three days, its wake-ups and its settled P from grades.jsonl.gz."""
    h = s["hero"]
    lead = next(g for g in grades if g["model"] == h["model"] and g["task_id"] == h["task_id"])
    rows = sorted((g for g in grades if g["model"] == h["model"] and g["front"] == lead["front"]
                   and g["status"] == "scored"), key=lambda g: g["site"])
    if len(rows) != 4:
        raise SystemExit(f"hero: {len(rows)} {h['model']} windows on the {lead['front']} front, expected 4")
    sites = []
    for g in rows:
        ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
        rt, card = [ep["rt"][iso] for iso in ep["dates"]], ep["site"]["card"]
        soc, end = [x for r in rt[:-1] for x in r["soc_mwh"][:-1:3]] + rt[-1]["soc_mwh"][::3], 1440 * len(rt)
        sites.append({"task": g["task_id"], "name": card["name"], "region": card["region"], "size": card["size"],
                      "e_max": ep["site"]["e_max_mwh"], "p_max": ep["site"]["hsl_mw"],
                      "rt": [round(x, 2) for r in rt for x in r["spp"]], "soc": [round(x, 2) for x in soc],
                      "mw": [round(float(np.mean(r["metered_mw"][i:i + 3])), 1) for r in rt for i in range(0, 288, 3)],
                      "wakes": [w["t"] for w in ep["wakes"] if w.get("turn") is not None and 0 <= w["t"] < end],
                      "p": round(g["p"], 2), "p_operator_replay": g["p_operator_replay"]})
    m, front = s["models"][h["model"]], next(f for f in s["fronts"] if f["front"] == lead["front"])
    old = DATA / "banner.json"
    prev = json.loads(old.read_text()) if old.is_file() else {}
    return {"days": lead["dates"], "span": span(lead["dates"][0], len(lead["dates"])), "kind": front["kind"],
            "model": f"{m['name']} in {m['harness']}", "lead": h["task_id"],
            "regions": {k: {"lon": x, "lat": y} for k, (x, y) in REGIONS.items()},
            "texas": prev.get("texas") or texas(), "sites": sites,
            "source": "ERCOT's node prices as the episodes recorded them; Texas: U.S. Census Bureau via us-atlas"}


def curve(repo: Path, d: dict) -> dict:
    """The day-ahead energy bid/offer curves one episode submitted, the node's real day-ahead price and the award each
    cleared at, for the chapter on ERCOT's objects."""
    key, task, model, hour = CURVE
    folder = repo / "results" / f"desk-{key}"
    with gzip.open(folder / "grades.jsonl.gz", "rt") as f:
        g = next(x for x in map(json.loads, filter(str.strip, f)) if x["model"] == model and x["task_id"] == task)
    ep = json.loads(gzip.decompress((folder / g["episode"]).read_bytes()))
    iso = ep["dates"][0]
    dam = ep["dam"][iso]
    card = ep["site"]["card"]
    sub = next(s for s in ep["submissions"] if s["tool"] == "submit_dam_offers" and s["accepted"])
    return {"version": key, "task": task, "date": iso, "site": f"{card['name']} ({card['region']}, {card['size']})",
            "model": d["models"][model]["label"], "submitted": sub["t"],
            "hour": hour, "curves": dam["curves"], "spp": dam["spp"],
            "award": [round(x, 2) for x in dam["award_mw"]], "p_min": ep["site"]["lsl_mw"],
            "p_max": ep["site"]["hsl_mw"]}


def texas() -> list:
    """Texas from the U.S. Census Bureau's cartographic boundaries (us-atlas 3.0.1, TopoJSON), simplified."""
    cache = ROOT / "cache" / "article" / "states-10m.json"
    if not cache.is_file():
        import urllib.request
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


def leaves(f: dict, path: str = "F") -> dict[str, str]:
    out = {}
    for k, x in f.items():
        if isinstance(x, dict):
            out |= leaves(x, f"{path}.{k}")
        else:
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
    print(f"numbers check: {len(used)} stated numbers read from facts.json, formatted from summary.json and desk.json; "
          "none written in")


def describe(pitch: str, b: dict) -> None:
    """The front matter's two lines that state results: the description, the hero's subtitle and the page's meta
    description, is the card's pitch; the social image's alt text names the banner's front."""
    alt = ("GridSimEnv Desk: a dot map of Texas with four anonymised batteries, in the Far West, Houston, the North "
           f"and the South, charging and discharging as {b['model']} traded them in the benchmark over a real weather "
           f"front, a {b['kind']}, {b['span']}.")
    text = MDX.read_text()
    for key, value in (("description", pitch), ("seoImageAlt", alt)):
        text, n = re.subn(rf'^{key}: ".*"$', lambda _, k=key, v=value: f"{k}: {json.dumps(v, ensure_ascii=False)}",
                          text, count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"{MDX.name} has no one-line {key} to write")
    MDX.write_text(text)


def check_order(s: dict) -> None:
    """The benchmark's table lists the models as the card does: by C over every window, highest first."""
    text = (CHAPTERS / "bench.mdx").read_text()
    body = text[text.index("<tbody>"):text.index("</tbody>")]
    at = [body.find(f"{{F.bench.m.{k}.name}}") for k in s["order_by_C"]]
    if -1 in at or at != sorted(at):
        raise SystemExit(f"bench.mdx's table does not list {', '.join(s['order_by_C'])} in that order")


def check_rendered(f: dict) -> None:
    """After the build: every fact the prose names appears on the page as facts.json formats it."""
    html = (APP / "dist" / "index.html").read_text()
    text = re.sub(r"<[^>]+>", "", html).replace("&#36;", "$").replace("&amp;", "&").replace("&#39;", "'")
    known = leaves(f)
    used = {e for p in CHAPTERS.glob("*.mdx") for e in FACT.findall(p.read_text())}
    missing = [f"{e} = {known[e]!r}" for e in sorted(used) if known[e] not in text]
    if missing:
        raise SystemExit("rendered check failed, not on the page:\n  " + "\n  ".join(missing))
    print(f"rendered check: all {len(used)} facts on the page as formatted")


def files_to_publish() -> dict[str, Path]:
    skip = re.compile(r"(^|/)(node_modules|dist|\.astro|\.DS_Store)(/|$)|^app/public/data(/|$)")
    out = {}
    for p in sorted(ARTICLE.rglob("*")):
        rel = p.relative_to(ARTICLE).as_posix()
        if p.is_file() and not p.is_symlink() and not skip.search(rel):
            out[rel] = p
    return out


IMAGES = (".jpg", ".png", ".webp")


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


GITATTRIBUTES = "".join(f"*.{x} filter=lfs diff=lfs merge=lfs -text\n" for x in ("mp4", "webp", "jpg", "png"))


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
        "GridSimEnv Desk article: the v4 benchmark, then the ladder, v2 to v4, and the v5 price-impact check"))
    return info.commit_url


if __name__ == "__main__":
    main()
