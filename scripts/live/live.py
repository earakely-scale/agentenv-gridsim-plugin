"""The live board: sealed day-ahead schedules on the ERCOT DAM, graded once prices post (docs/prereg/v1-live-board.md).

usage: live.py pass [--poll] | build DAY | agents DAY | seal DAY | grade DAY | board | status
State lives under $LIVE_STATE. Secrets (ERCOT, LiteLLM key, HF token) are read from SSM inside the process and never
written; the LiteLLM endpoint comes from the `LITELLM_BASE_URL=` line of $LIVE_ENV. Every step is idempotent: a sealed
day is never resealed, an agent record is never rerun, a graded day is never regraded."""

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import numpy as np
import openai
import requests

ROOT = Path(__file__).resolve().parents[2]
for p in ("src", "scripts", "results/train/4b-blind/scripts", "results/cost-matched/scripts",
          "results/fresh/2026-10/scripts"):
    sys.path.insert(0, str(ROOT / p))
import ercot_pull  # noqa: E402
import sol_blind  # noqa: E402
from build_pack import battery_for, lags  # noqa: E402
from luna_eval import Harness  # noqa: E402
from luna_eval import cost as luna_cost  # noqa: E402
from pathb_blind import graded  # noqa: E402

from gridsim_core import CONTRACT_VERSION, baselines  # noqa: E402
from gridsim_core.contract import price_violations  # noqa: E402
from gridsim_core.forecast import parse_forecast  # noqa: E402
from gridsim_core.grade import grade, references  # noqa: E402
from gridsim_core.task import REGIONS, point_kind, task_id  # noqa: E402
from gridsim_core.trl import extract_actions  # noqa: E402

CT, UTC = ZoneInfo("America/Chicago"), dt.UTC
STATE = Path(os.environ.get("LIVE_STATE", "/home/ubuntu/gl/state"))
POINTS = ercot_pull.POINTS
ARCHETYPES = ("1h-c", "2h-b", "4h-f")
REPO_ID = "earakely-scale/GridSimEnv-AgentEnv"
CAP_USD, ATTEMPTS, CONCURRENCY = 25.0, 3, 8
FIRST_DAY = "2026-10-29"
LLM = {"gpt-6.1-sol": ("openai/gpt-6.1-sol", "high"), "gpt-6-luna": ("openai/gpt-6-luna", "high")}
QWEN = "qwen3-4b-gridsim-run4"
RULES = ("persistence_dp", "ridge_dp", "greedy_d1")
AGENTS = (*LLM, QWEN, *RULES)
ARCH_TABLE = json.loads((ROOT / "data/ercot-dam-v1-rtcb/manifest.json").read_text())["letters"]
RIDGE = json.loads((ROOT / "data/ridge-v1.json").read_text())


def log(msg: str):
    print(f"[{dt.datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}] {msg}", flush=True)


def ssm(name: str) -> str:
    return boto3.client("ssm", region_name="us-west-2").get_parameter(Name=name, WithDecryption=True)[
        "Parameter"]["Value"]


def day(d: str, n: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=n)).isoformat()


def deadline(d: str) -> dt.datetime:
    """DAM for delivery day d closes 10:00 Central Prevailing Time on d - 1."""
    return dt.datetime.combine(dt.date.fromisoformat(day(d, -1)), dt.time(10), CT).astimezone(UTC)


def utc(t: dt.datetime | None = None) -> str:
    return (t or dt.datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def dump(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1) + "\n")
    tmp.replace(path)
    return path


def load(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def digest(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ercot:
    """NP4-190-CD through the public API, at most one request per ercot_pull.GAP_S seconds."""

    def __init__(self):
        self.head, self.last = None, 0.0

    def get(self, **params) -> dict:
        if self.head is None:
            self.head = {"Ocp-Apim-Subscription-Key": ssm("/gridsim/ercot-api-key"),
                         "Authorization": f"Bearer {self.token()}"}
        for attempt in range(3):
            time.sleep(max(0.0, ercot_pull.GAP_S - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            r = requests.get(ercot_pull.API, headers=self.head, timeout=120, params=params)
            if r.status_code == 200:
                return r.json()
            log(f"ERCOT HTTP {r.status_code} (attempt {attempt + 1})")
            if r.status_code == 401:
                self.head["Authorization"] = f"Bearer {self.token()}"
        raise RuntimeError("ERCOT API failed three times")

    def token(self) -> str:
        form = {"username": ssm("/gridsim/ercot-username"), "password": ssm("/gridsim/ercot-password"),
                "grant_type": "password", "scope": f"openid {ercot_pull.CLIENT} offline_access",
                "client_id": ercot_pull.CLIENT, "response_type": "id_token"}
        for _ in range(2):
            r = requests.post(ercot_pull.TOKEN_URL, data=form, timeout=60)
            if r.status_code == 200 and r.json().get("id_token"):
                return r.json()["id_token"]
            time.sleep(ercot_pull.GAP_S)
        raise RuntimeError("ERCOT login failed twice")

    def records(self, d: str) -> int:
        """Rows the API holds for delivery day d, over every settlement point."""
        j = self.get(deliveryDateFrom=d, deliveryDateTo=d, size=1, page=1)
        return int(j.get("_meta", {}).get("totalRecords") or 0)

    def pull(self, d0: str, d1: str) -> Path:
        out = STATE / "api" / f"{utc().replace(':', '')}_{d0}_{d1}"
        out.mkdir(parents=True, exist_ok=True)
        for p in POINTS:
            page, rows, fields = 1, [], None
            while True:
                j = self.get(deliveryDateFrom=d0, deliveryDateTo=d1, settlementPoint=p, size=5000, page=page)
                fields = [f["name"] for f in j.get("fields", [])]
                rows += j.get("data", [])
                if page >= int(j.get("_meta", {}).get("totalPages") or 1):
                    break
                page += 1
            dump(out / f"{p}.json", {"point": p, "from": d0, "to": d1, "fields": fields, "data": rows,
                                     "fetched_utc": utc()})
        log(f"pulled {d0}..{d1} for {len(POINTS)} points -> {out.name}")
        return out


def prices() -> dict:
    """{date: {point: [24]}} from every pull: HE01..HE24 with the fall-back day's repeated hour (DSTFlag) dropped,
    i.e. the battery idles in it; a point-day that is not exactly 24 hours or breaks the era caps is left out. Later
    pulls of a point-day must agree with earlier ones."""
    out, src = {}, {}
    for f in sorted((STATE / "api").glob("*/*.json")):
        j = json.loads(f.read_text())
        ix = {k: j["fields"].index(k) for k in ("deliveryDate", "hourEnding", "settlementPoint",
                                                  "settlementPointPrice", "DSTFlag")} if j["fields"] else {}
        hours = {}
        for r in j["data"]:
            if str(r[ix["DSTFlag"]]).lower() == "true":
                continue
            hours.setdefault(str(r[ix["deliveryDate"]]), {})[int(str(r[ix["hourEnding"]]).split(":")[0])] = float(
                r[ix["settlementPointPrice"]])
        for d, hv in hours.items():
            if sorted(hv) != list(range(1, 25)):
                continue
            v = [hv[h] for h in range(1, 25)]
            if price_violations(d, v):
                continue
            old = out.get(d, {}).get(j["point"])
            if old is not None and old != v:
                raise RuntimeError(f"{d} {j['point']}: {f} disagrees with {src[(d, j['point'])]}")
            out.setdefault(d, {})[j["point"]] = v
            src[(d, j["point"])] = f
    return out


def complete(px: dict, d: str) -> bool:
    return all(p in px.get(d, {}) for p in POINTS)


def build(d: str, px: dict) -> list[dict]:
    """The sealed task rows for delivery day d: 15 points x the three 100 MW archetypes, blind inputs only (D-7..D-1),
    no prices and no refs."""
    dam = {(k, p): np.asarray(v) for k, ps in px.items() if k < d for p, v in ps.items()}
    rows = {r["ep_h"]: r for r in (row for rs in ARCH_TABLE.values() for row in rs)
            if f"{r['ep_h']}h-{r['letter']}" in ARCHETYPES}
    tasks = []
    for p in POINTS:
        blind = lags(dam, d, p)
        for ep in (1, 2, 4):
            b = battery_for(rows[ep])
            tasks.append({"task_id": task_id(d, p, b["archetype"]), "contract_version": CONTRACT_VERSION,
                          "pack": "ercot-dam-v1-live", "split": "live", "date": d, "settlement_point": p,
                          "point_kind": point_kind(p), "region": REGIONS[p], "battery": b, "blind": blind,
                          "tags": {"blind_eval": True, "live": True}})
    return tasks


def day_dir(d: str) -> Path:
    return STATE / "days" / d


def tasks_of(d: str) -> list[dict]:
    return load(day_dir(d) / "tasks.json")["tasks"]


def spent() -> float:
    return sum(r.get("usd") or 0.0 for f in (STATE / "days").glob("*/agents/*.jsonl") for r in rows(f))


def rows(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()] if p.exists() else []


def llm_record(resp) -> dict:
    """sol_blind.score's extraction, without the grade: the day's prices are not known yet."""
    text, reasoning, calls = "", "", []
    for item in resp.output:
        if item.type == "message":
            text += "".join(getattr(c, "text", "") for c in item.content)
        elif item.type == "reasoning":
            reasoning += "\n".join(getattr(s, "text", "") for s in (getattr(item, "summary", None) or []))
        elif item.type == "function_call":
            calls.append({"function": {"name": item.name, "arguments": item.arguments or ""}})
    tc = any(c["function"]["name"] == "submit_schedule" and "actions" in sol_blind._loads(c["function"]["arguments"])
             for c in calls)
    u = resp.usage
    usage = {"input": u.input_tokens or 0, "output": u.output_tokens or 0,
             "cached": getattr(u.input_tokens_details, "cached_tokens", 0) or 0,
             "reasoning": getattr(u.output_tokens_details, "reasoning_tokens", 0) or 0}
    return {"status": resp.status, "response_model": getattr(resp, "model", None), "tool_call": tc,
            "truncated": resp.status == "incomplete", "usage": usage,
            "sent": extract_actions({"role": "assistant", "content": text, "tool_calls": calls}),
            "forecast": parse_forecast(text), "text": text, "reasoning_summary": reasoning, "calls": calls}


async def run_llm(d: str, name: str):
    model, effort = LLM[name]
    path = day_dir(d) / "agents" / f"{name}.jsonl"
    done = {r["task_id"] for r in rows(path)}
    todo = [t for t in tasks_of(d) if t["task_id"] not in done]
    if not todo:
        return
    h = Harness("blind", effort)
    req = (lambda t: sol_blind.request(t)) if name == "gpt-6.1-sol" else h.request
    price = sol_blind.cost if name == "gpt-6.1-sol" else luna_cost
    base = re.search(r"LITELLM_BASE_URL=[\"']?([^\s\"']+)", Path(os.environ["LIVE_ENV"]).read_text()).group(1)
    key = ssm("/gridsim/litellm-key")
    client = openai.AsyncOpenAI(base_url=base, api_key=key, max_retries=0, timeout=900.0)
    st, lock, sem = {"inflight": 0.0}, asyncio.Lock(), asyncio.Semaphore(CONCURRENCY)
    log(f"{d} {name}: {len(todo)} tasks, lane spend ${spent():.4f}")

    async def one(t):
        async with sem:
            r0 = req(t)
            n_in = (len(r0["instructions"]) + len(r0["input"][0]["content"][0]["text"])) // 2 + 500
            w = price({"input": n_in, "cached": 0, "output": r0["max_output_tokens"]})
            async with lock:
                if spent() + st["inflight"] + w > CAP_USD:
                    log(f"{t['task_id']} {name}: skipped by the ${CAP_USD:g} cap")
                    return
                st["inflight"] += w
            t0, errors, resp = time.monotonic(), [], None
            for attempt in range(ATTEMPTS):
                try:
                    resp = await sol_blind.call(client, req(t))
                    break
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{type(e).__name__}: {str(e).replace(key, '<key>').replace(base, '<url>')[:300]}")
                    if attempt + 1 < ATTEMPTS:
                        await asyncio.sleep(5 * (attempt + 1))
            rec = {"task_id": t["task_id"], "agent": name, "model": model, "effort": effort,
                   "wall_s": round(time.monotonic() - t0, 2), "attempts": len(errors) + (resp is not None),
                   "infra_errors": errors, "finished_utc": utc()}
            if resp is None:
                rec |= {"status": "error", "sent": None, "tool_call": False, "truncated": False, "forecast": None,
                        "usage": None, "usd": 0.0}
            else:
                rec |= llm_record(resp)
                rec["usd"] = round(price(rec["usage"]), 8)
            async with lock:
                st["inflight"] -= w
                with path.open("a") as f:
                    f.write(json.dumps(rec) + "\n")
            log(f"{t['task_id']} {name} {rec['status']} sent {rec['sent'] is not None} ${rec['usd']:.4f} "
                f"{rec['wall_s']}s try {rec['attempts']}")

    path.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.gather(*(one(t) for t in todo))


def run_qwen(d: str):
    path = day_dir(d) / "agents" / f"{QWEN}.jsonl"
    if rows(path):
        return
    py = os.environ.get("QWEN_PYTHON", sys.executable)
    out = path.with_suffix(".tmp")
    r = subprocess.run([py, str(Path(__file__).with_name("live_4b.py")), str(day_dir(d) / "tasks.json"), str(out)],
                       capture_output=True, text=True)
    (day_dir(d) / "qwen.log").write_text(r.stdout[-20000:] + r.stderr[-20000:])
    if r.returncode or not out.exists():
        log(f"{d} {QWEN}: failed (exit {r.returncode}); see {day_dir(d) / 'qwen.log'}")
        return
    out.replace(path)
    log(f"{d} {QWEN}: {len(rows(path))} records")


def run_rules(d: str):
    path = day_dir(d) / "agents" / "rules.json"
    if path.exists():
        return
    out = {}
    for t in tasks_of(d):
        out[t["task_id"]] = {"persistence_dp": baselines.persistence_dp(t), "ridge_dp": baselines.ridge_dp(t, RIDGE),
                             "greedy_d1": baselines.greedy(dict(t, prices=t["blind"]["dam_prev_day"]))}
    dump(path, out)


def agents(d: str):
    run_rules(d)

    async def all_():
        await asyncio.gather(asyncio.to_thread(run_qwen, d), *(run_llm(d, n) for n in LLM))

    asyncio.run(all_())


AGENT_META = {
    "gpt-6.1-sol": {"label": "GPT-6.1 Sol", "kind": "llm", "model": "openai/gpt-6.1-sol", "effort": "high",
                    "harness": "results/train/4b-blind/scripts/sol_blind.py request + call (Responses API, one call)"},
    "gpt-6-luna": {"label": "GPT-6 Luna", "kind": "llm", "model": "openai/gpt-6-luna", "effort": "high",
                   "harness": "results/cost-matched/scripts/luna_eval.py Harness('blind', 'high')"},
    QWEN: {"label": "Qwen3-4B trained (run 4)", "kind": "trained", "model": "Qwen/Qwen3-4B",
           "revision": "1cfa9a7208912126459214e8b04321603b3df60c",
           "chain": "base -> reg2 sft-lora (merged) -> reg3 dpa-lora (merged) -> reg4 sft-lora (merged) -> reg4 "
                    "rl-lora (vLLM LoRA, RL step 237)",
           "decoding": {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "seed": 0, "max_tokens": 768,
                        "enable_thinking": False}},
    "persistence_dp": {"label": "Persistence + DP", "kind": "rule", "rule": "gridsim_core.baselines.persistence_dp"},
    "ridge_dp": {"label": "Ridge + DP", "kind": "rule", "rule": "gridsim_core.baselines.ridge_dp, data/ridge-v1.json"},
    "greedy_d1": {"label": "Greedy on D-1", "kind": "rule", "rule": "gridsim_core.baselines.greedy on D-1 prices"},
}


def schedules(d: str) -> dict:
    """{agent: {task_id: record}} of what is sealed for d."""
    out = {n: {r["task_id"]: r for r in rows(day_dir(d) / "agents" / f"{n}.jsonl")} for n in (*LLM, QWEN)}
    rules = load(day_dir(d) / "agents" / "rules.json", {})
    for n in RULES:
        out[n] = {k: {"task_id": k, "sent": v[n]} for k, v in rules.items()}
    return out


def seal(d: str, er: Ercot) -> dict | None:
    """Write the sealed file once (never rewritten), then publish it until the deadline."""
    sealed = day_dir(d) / "sealed.json"
    if not sealed.exists():
        now = dt.datetime.now(UTC)
        if now > deadline(d) - dt.timedelta(minutes=10):
            log(f"{d}: past the seal deadline {utc(deadline(d))}; not sealed")
            return None
        n = er.records(d)
        check = {"checked_utc": utc(), "api_records_for_delivery_day": n,
                 "query": "NP4-190-CD deliveryDateFrom = deliveryDateTo = the delivery day, every settlement point"}
        if n:
            log(f"{d}: the API already shows {n} DAM rows for the delivery day; not sealed")
            dump(day_dir(d) / "not_sealed.json", check)
            return None
        tasks = tasks_of(d)
        ids = [t["task_id"] for t in tasks]
        sch = schedules(d)
        meta = load(STATE / "meta.json", {})
        ag = {}
        for n in AGENTS:
            recs = sch.get(n, {})
            have = [i for i in ids if i in recs]
            ag[n] = AGENT_META[n] | meta.get(n, {}) | {
                "sealed": len(have) == len(ids), "missing_tasks": len(ids) - len(have),
                "usd": round(sum(recs[i].get("usd") or 0.0 for i in have), 6),
                "records": [_public(recs[i]) for i in have]}
        doc = {"schema": "gridsim.live.sealed/v1", "delivery_day": d, "market": "ERCOT DAM (NP4-190-CD)",
               "sealed_utc": utc(), "dam_close_utc": utc(deadline(d)),
               "rule": "valid if this file's public commit time and the no-prices check are both before dam_close_utc "
                       "and the check found no DAM rows for the delivery day",
               "no_prices_check": check, "inputs_digest": digest(tasks), "tasks": tasks, "agents": ag,
               "missing_agents": [n for n in AGENTS if not ag[n]["sealed"]],
               "dropped_tasks": load(day_dir(d) / "tasks.json")["dropped"],
               "lane_spend_usd": round(spent(), 4), "prereg": "docs/prereg/v1-live-board.md"}
        dump(sealed, doc)
        log(f"{d}: sealed file written ({len(ids)} tasks, missing {doc['missing_agents']})")
    return publish_seal(d)


def _public(r: dict) -> dict:
    keep = ("task_id", "sent", "forecast", "tool_call", "truncated", "status", "finish_reason", "response_model",
            "usage", "usd", "attempts", "infra_errors", "text", "reasoning_summary", "tokens", "prompt_tokens")
    return {k: r[k] for k in keep if k in r}


def hf_token() -> str | None:
    try:
        return ssm("/gridsim/hf-token")
    except Exception as e:  # noqa: BLE001
        log(f"no HF token ({type(e).__name__})")
        return None


def commit(files: dict[str, Path], message: str) -> dict | None:
    from huggingface_hub import CommitOperationAdd, HfApi

    tok = hf_token()
    if not tok:
        return None
    try:
        info = HfApi(token=tok).create_commit(REPO_ID, repo_type="dataset", commit_message=message, operations=[
            CommitOperationAdd(path_in_repo=k, path_or_fileobj=str(v)) for k, v in files.items()])
        when = next((c.created_at for c in HfApi().list_repo_commits(REPO_ID, repo_type="dataset")
                     if c.commit_id == info.oid), None)
    except Exception as e:  # noqa: BLE001
        log(f"HF commit failed: {type(e).__name__}: {str(e)[:200]}")
        return None
    return {"oid": info.oid, "url": info.commit_url, "created_utc": utc(when.astimezone(UTC)) if when else None,
            "files": sorted(files)}


def published(path: str, local: Path) -> dict | None:
    """The commit that last touched path on the dataset, if the file there is byte-identical to local (a seal
    published from elsewhere, e.g. by hand)."""
    from huggingface_hub import HfApi, hf_hub_download

    try:
        info = HfApi().get_paths_info(REPO_ID, [path], repo_type="dataset", expand=True)
        if not info:
            return None
        f = hf_hub_download(REPO_ID, path, repo_type="dataset", revision=info[0].last_commit.oid,
                            cache_dir=str(STATE / "hf-cache"))
    except Exception as e:  # noqa: BLE001
        log(f"HF lookup of {path} failed: {type(e).__name__}")
        return None
    if Path(f).read_bytes() != local.read_bytes():
        return None
    lc = info[0].last_commit
    return {"oid": lc.oid, "url": f"https://huggingface.co/datasets/{REPO_ID}/commit/{lc.oid}",
            "created_utc": utc(lc.date.astimezone(UTC)), "files": [path], "published_elsewhere": True}


def publish_seal(d: str) -> dict | None:
    rec = day_dir(d) / "seal_commit.json"
    if rec.exists():
        return load(rec)
    if dt.datetime.now(UTC) > deadline(d):
        log(f"{d}: sealed file was not published before the deadline")
        return None
    path = f"live/sealed/{d}.json"
    c = published(path, day_dir(d) / "sealed.json") or commit({path: day_dir(d) / "sealed.json"}, f"live: seal {d}")
    if c:
        dump(rec, c)
        log(f"{d}: seal published {c['url']} at {c['created_utc']}")
        commit({"live/board.json": dump(STATE / "board.json", board())}, f"live: board after the {d} seal")
    return c


def grade_day(d: str, px: dict) -> dict | None:
    out = day_dir(d) / "graded.json"
    if out.exists():
        return load(out)
    sealed, sc = load(day_dir(d) / "sealed.json"), load(day_dir(d) / "seal_commit.json")
    if not (sealed and sc and complete(px, d)):
        return None
    valid = bool(sc["created_utc"] and sc["created_utc"] < sealed["dam_close_utc"]
                 and sealed["no_prices_check"]["checked_utc"] < sealed["dam_close_utc"]
                 and sealed["no_prices_check"]["api_records_for_delivery_day"] == 0)
    tasks = {}
    for t in sealed["tasks"]:
        t = dict(t, prices=[round(float(v), 2) for v in px[d][t["settlement_point"]]])
        t["refs"] = references(t, ridge=RIDGE)
        tasks[t["task_id"]] = t
    per = {}
    for n, a in sealed["agents"].items():
        if not a["sealed"]:
            per[n] = {"label": a["label"], "sealed": False}
            continue
        res = []
        for r in a["records"]:
            t = tasks[r["task_id"]]
            if a["kind"] == "rule":
                g = grade(t, r["sent"], "blind")
                s = {"c": g["r_opt"], "reward": g["reward"], "valid": True, "kind": None, "grade": g}
            else:
                s = graded(t, r["sent"], r.get("forecast"), r.get("tool_call", False), r.get("truncated", False))
            f = t["refs"]["foresight"]
            profit = s["grade"]["profit"] if s["valid"] else f["p_idle"]
            res.append({"task_id": r["task_id"], "c": s["c"], "reward": s["reward"], "valid": s["valid"],
                        "kind": s["kind"], "profit_usd": round(profit, 2),
                        "usd_per_mw": round(profit / t["battery"]["p_dis_mw"], 4)})
        per[n] = {"label": a["label"], "sealed": a.get("sealed", False), "tasks": res, "day": summary(res, tasks)}
    refs = {}
    for k, t in tasks.items():
        f, b = t["refs"]["foresight"], t["refs"]["blind"]
        refs[k] = {"p_idle": f["p_idle"], "p_opt": f["p_opt"], "p_anchor": b["p_anchor"],
                   "c_anchor": b["r_opt_anchor"], "opt": f["opt"]}
    ref_rows = {"hindsight_dp": [{"task_id": k, "c": 1.0, "profit_usd": v["p_opt"], "valid": True} for k, v in
                                 refs.items()],
                "blind_anchor": [{"task_id": k, "c": v["c_anchor"], "profit_usd": v["p_anchor"], "valid": True} for
                                 k, v in refs.items()]}
    doc = {"schema": "gridsim.live.graded/v1", "delivery_day": d, "graded_utc": utc(), "seal_commit": sc,
           "seal_valid": valid, "dam_close_utc": sealed["dam_close_utc"],
           "prices": {p: px[d][p] for p in POINTS}, "references": refs,
           "reference_days": {k: summary(v, tasks) for k, v in ref_rows.items()}, "agents": per}
    dump(out, doc)
    log(f"{d}: graded (seal valid {valid})")
    return doc


def summary(res: list[dict], tasks: dict) -> dict:
    by = {}
    for r in res:
        by.setdefault(tasks[r["task_id"]]["battery"]["archetype"].split("-")[0], []).append(r)
    s = lambda rs: {"n": len(rs), "c_mean": round(float(np.mean([r["c"] for r in rs])), 4),  # noqa: E731
                    "usd_per_mw": round(float(np.mean([r["profit_usd"] / 100.0 for r in rs])), 2),
                    "pnl_usd": round(float(sum(r["profit_usd"] for r in rs)), 2),
                    "valid_rate": round(float(np.mean([r["valid"] for r in rs])), 4)}
    return s(res) | {"by_duration": {k: s(v) for k, v in sorted(by.items())}}


def board() -> dict:
    """Cumulative over graded days with a valid seal: per agent, day by day and summed; paired gaps against
    persistence + DP with a day-block bootstrap CI (descriptive)."""
    days = sorted(p.parent.name for p in (STATE / "days").glob("*/graded.json"))
    gs = {d: load(day_dir(d) / "graded.json") for d in days}
    ok = [d for d in days if gs[d]["seal_valid"]]
    names = list(AGENT_META) + ["blind_anchor", "hindsight_dp"]
    out = {"schema": "gridsim.live.board/v1", "updated_utc": utc(), "prereg": "docs/prereg/v1-live-board.md",
           "battery_mw": 100, "archetypes": list(ARCHETYPES), "points": POINTS, "graded_days": ok,
           "invalid_seal_days": [d for d in days if d not in ok], "agents": {}, "timeline": timeline()}
    for n in names:
        daily = {}
        for d in ok:
            g = gs[d]
            s = g["reference_days"].get(n) if n in ("blind_anchor", "hindsight_dp") else (
                g["agents"].get(n, {}).get("day") if g["agents"].get(n, {}).get("sealed") else None)
            if s:
                daily[d] = s
        cum = np.cumsum([daily[d]["usd_per_mw"] for d in daily]).round(2).tolist()
        out["agents"][n] = {"label": AGENT_META.get(n, {}).get("label") or {"blind_anchor": "Blind anchor",
                                                                             "hindsight_dp": "Hindsight optimum"}[n],
                            "kind": AGENT_META.get(n, {}).get("kind", "reference"), "days": daily,
                            "cum_usd_per_mw": dict(zip(daily, cum, strict=True)),
                            "total_usd_per_mw": cum[-1] if cum else None,
                            "c_mean": round(float(np.mean([v["c_mean"] for v in daily.values()])), 4) if daily
                            else None,
                            "vs_persistence_dp": paired_gap(n, gs, ok)}
    return out


def paired_gap(n: str, gs: dict, ok: list[str]) -> dict | None:
    if n in ("persistence_dp", "blind_anchor", "hindsight_dp"):
        return None
    dc, du, dd = [], [], []
    for d in ok:
        a, b = gs[d]["agents"].get(n), gs[d]["agents"].get("persistence_dp")
        if not (a and b and a["sealed"] and b["sealed"]):
            continue
        bb = {r["task_id"]: r for r in b["tasks"]}
        for r in a["tasks"]:
            dc.append(r["c"] - bb[r["task_id"]]["c"])
            du.append(r["usd_per_mw"] - bb[r["task_id"]]["usd_per_mw"])
            dd.append(d)
    if not dd:
        return None
    dd = np.asarray(dd)
    cum = sum(float(np.mean(np.asarray(du)[dd == d])) for d in np.unique(dd))
    return {"days": int(len(np.unique(dd))), "c": boot(dc, dd), "usd_per_mw_per_day": boot(du, dd),
            "cum_usd_per_mw": round(cum, 2)}


def boot(x, days, b: int = 10000) -> dict:
    """Task-weighted mean and day-block 95% CI (report_blind.boot's resampling, seed 0)."""
    x = np.asarray(x, float)
    u, inv = np.unique(days, return_inverse=True)
    idx = np.random.default_rng(0).integers(0, len(u), (b, len(u)))
    s, c = np.bincount(inv, x), np.bincount(inv)
    m = s[idx].sum(1) / c[idx].sum(1)
    return {"mean": round(float(x.mean()), 4), "ci": [round(float(v), 4) for v in np.percentile(m, [2.5, 97.5])],
            "n": int(len(x)), "days": int(len(u))}


def timeline() -> list[dict]:
    out = []
    for p in sorted((STATE / "days").glob("*")):
        d = p.name
        s, sc, g = load(p / "sealed.json"), load(p / "seal_commit.json"), load(p / "graded.json")
        gc = load(p / "grade_commit.json")
        out.append({"delivery_day": d, "dam_close_utc": utc(deadline(d)),
                    "sealed_utc": s and s["sealed_utc"], "seal_commit": sc and {k: sc[k] for k in
                                                                                  ("oid", "url", "created_utc")},
                    "missing_agents": s and s["missing_agents"], "graded_utc": g and g["graded_utc"],
                    "seal_valid": g and g["seal_valid"], "grade_commit": gc and {k: gc[k] for k in ("oid", "url")},
                    "not_sealed": load(p / "not_sealed.json")})
    return out


def publish_grade(d: str):
    rec = day_dir(d) / "grade_commit.json"
    if rec.exists() or not (day_dir(d) / "graded.json").exists():
        return
    b = dump(STATE / "board.json", board())
    c = commit({f"live/graded/{d}.json": day_dir(d) / "graded.json", "live/board.json": b}, f"live: grade {d}")
    if c:
        dump(rec, c)
        dump(STATE / "board.json", board())
        log(f"{d}: grade published {c['url']}")


def one_pass(er: Ercot, poll_until: dt.datetime | None = None):
    """Grade every sealed day whose prices are out; seal every day whose inputs are out and whose DAM is still open."""
    today = dt.datetime.now(CT).date().isoformat()
    target = day(today, 1)
    while poll_until and not er.records(target):
        if dt.datetime.now(UTC) > poll_until:
            log(f"no DAM prices for {target} by {utc(poll_until)}; giving up")
            break
        log(f"waiting for {target}'s DAM prices")
        time.sleep(300)
    if poll_until:
        time.sleep(90)
    px = prices()
    need = day(today, -7)
    if not complete(px, target) or any(not complete(px, day(need, i)) for i in range(9)):
        er.pull(need, target)
        px = prices()
    for p in sorted((STATE / "days").glob("*/sealed.json")):
        d = p.parent.name
        if not (p.parent / "seal_commit.json").exists():
            publish_seal(d)
        if grade_day(d, px):
            publish_grade(d)
    for d in (day(today, 1), day(today, 2)):
        if d < FIRST_DAY or (day_dir(d) / "sealed.json").exists() or dt.datetime.now(UTC) > deadline(d):
            continue
        if not complete(px, day(d, -1)):
            continue
        prepare(d, px)
        agents(d)
        seal(d, er)


def prepare(d: str, px: dict):
    f = day_dir(d) / "tasks.json"
    if f.exists():
        return
    tasks = build(d, px)
    dropped = [t["task_id"] for t in tasks if not t["blind"]]
    tasks = [t for t in tasks if t["blind"]]
    dump(f, {"delivery_day": d, "built_utc": utc(), "inputs_digest": digest(tasks), "tasks": tasks,
             "dropped": dropped})
    log(f"{d}: {len(tasks)} tasks built ({len(dropped)} without D-7..D-1 inputs), digest {digest(tasks)[:12]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["pass", "build", "agents", "seal", "grade", "board", "status"])
    ap.add_argument("day", nargs="?")
    ap.add_argument("--poll", action="store_true")
    a = ap.parse_args()
    er = Ercot()
    if a.cmd == "pass":
        until = None
        if a.poll:
            until = dt.datetime.combine(dt.datetime.now(UTC).date(), dt.time(23, 30), UTC)
        one_pass(er, until)
    elif a.cmd == "build":
        prepare(a.day, prices())
    elif a.cmd == "agents":
        agents(a.day)
    elif a.cmd == "seal":
        print(json.dumps(seal(a.day, er)))
    elif a.cmd == "grade":
        if grade_day(a.day, prices()):
            publish_grade(a.day)
    elif a.cmd == "board":
        print(json.dumps(dump(STATE / "board.json", board()).name))
    else:
        print(json.dumps({"spent_usd": round(spent(), 4), "timeline": timeline()}, indent=1))


if __name__ == "__main__":
    main()
