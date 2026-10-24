"""Build data/notices/notices.jsonl, the ERCOT notice archive for GridSimEnv v2 (FD-4325).

Sources (raw pages cached under cache/raw/notices/, so a re-run only parses):
  ops_live     ERCOT Operations Messages (control-room OCN/Advisory/Watch/Emergency/EEA, AS deployments), the last six
               months that ercot.com keeps, timestamps to the second.
  ops_wayback  The same page as captured by the Internet Archive since 2018: every snapshot's table, unioned.
  news         ERCOT news releases (conservation appeals, Weather Watches, EEA declarations), dated to the day.
  mkt          ERCOT Market Notices: the archive listing (last three years, dated), detail pages for the operational
               subset (sent time to the minute), and ids listed in the sitemap.

python scripts/scrape_notices.py [--no-fetch] [--sources ops_live,ops_wayback,news,mkt]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from notice_fetch import CACHE, cache_path, fetch  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "notices"
CPT = ZoneInfo("America/Chicago")
ERCOT = "https://www.ercot.com"
OPS = f"{ERCOT}/services/comm/mkt_notices/opsmessages"
CDX = (
    "https://web.archive.org/cdx/search/cdx?url=ercot.com/services/comm/mkt_notices/opsmessages*&output=json"
    "&fl=timestamp,original,statuscode,digest,length&filter=statuscode:200&collapse=digest"
)
NEWS_YEARS = range(2018, 2027)
WAYBACK_DELAY = 4.0
MKT_FROM = "2023-10-24"
GRID_WORDS = re.compile(
    r"conserv|emergenc|\bEEA\b|energy emergency|watch|advisory|alert|tight grid|grid condition|winter storm|"
    r"extreme (cold|heat|weather)|freez|cold weather|heat|weather|demand record|peak demand|TXANS|rotating|"
    r"load shed|outage|reserve|capacity|enforcement discretion|202\(c\)|reliability unit commitment|\bRUC\b",
    re.I,
)
MKT_OPS_WORDS = re.compile(
    r"conserv|emergenc|\bEEA\b|weather|cold|heat|winter|storm|freez|enforcement discretion|202\(c\)|"
    r"reliability unit commitment|\bRUC\b|reserve|capacity|load shed|rotating|emergency pricing|watch|advisory|"
    r"\bOCN\b|operating condition|demand response|ERS\b|deploy",
    re.I,
)


def clean(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s)).replace("\x92", "'").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------- timestamps


def parse_ops_time(s: str) -> tuple[dt.datetime, str] | None:
    """An ops-message timestamp as an aware datetime, and how its zone was decided."""
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}) (\d{4}) (\d{2}):(\d{2}):(\d{2}) (CST|CDT|CPT)", s)
    if m:
        mon, d, y, hh, mm, ss, z = m.groups()
        naive = dt.datetime.strptime(f"{mon} {d} {y} {hh}:{mm}:{ss}", "%b %d %Y %H:%M:%S")
        return naive.replace(tzinfo=CPT), f"label_{z}"
    m = re.fullmatch(r"([A-Z][a-z]{2}) (\d{1,2}), (\d{4}) (\d{1,2}):(\d{2}):(\d{2}) ([AP]M)", s)
    if m:
        naive = dt.datetime.strptime(s, "%b %d, %Y %I:%M:%S %p")
        return naive.replace(tzinfo=CPT), "cpt_assumed"
    return None


def iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


# ---------------------------------------------------------------- ops messages


def ops_rows(page: str) -> list[dict]:
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        cells = [clean(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if len(cells) < 3:
            continue
        t = parse_ops_time(cells[0])
        if not t:
            continue
        rows.append(
            {
                "issued": t[0],
                "tz_basis": t[1],
                "text": cells[1],
                "ercot_type": cells[2],
                "status": cells[3] if len(cells) > 3 else "",
            }
        )
    return rows


def collect_ops_live(do_fetch: bool) -> list[dict]:
    page, path, _ = fetch(OPS, "ops_live") if do_fetch else (cache_read(OPS, "ops_live"), None, False)
    if page is None:
        return []
    s = page.decode("utf-8", "replace")
    urls = [OPS] + [f"{OPS}?m={m}&y={y}" for m, y in re.findall(r"href=\?m=(\d+)&y=(\d+)", s)]
    out = []
    for url in urls:
        body = fetch(url, "ops_live")[0] if do_fetch else cache_read(url, "ops_live")
        if body is None:
            continue
        fetched = dt.datetime.fromtimestamp(cache_path(url, "ops_live").stat().st_mtime, dt.UTC)
        for r in ops_rows(decode(body)):
            out.append({**r, "source": "ercot_ops_live", "url": url, "seen_at": fetched})
    return out


def collect_ops_wayback(do_fetch: bool) -> list[dict]:
    body = fetch(CDX, "wayback", delay=2)[0] if do_fetch else cache_read(CDX, "wayback")
    out = []
    for ts, orig, *_ in json.loads(body)[1:]:
        if ts < "2018":
            continue
        url = f"https://web.archive.org/web/{ts}id_/{orig}"
        page = fetch(url, "wayback", delay=WAYBACK_DELAY)[0] if do_fetch else cache_read(url, "wayback")
        if page is None:
            continue
        snap = dt.datetime.strptime(ts, "%Y%m%d%H%M%S").replace(tzinfo=dt.UTC)
        for r in ops_rows(decode(page)):
            out.append(
                {**r, "source": "ercot_ops_wayback", "url": f"https://web.archive.org/web/{ts}/{orig}", "seen_at": snap}
            )
    return out


def decode(page: bytes) -> str:
    try:
        return page.decode("utf-8")
    except UnicodeDecodeError:
        return page.decode("cp1252", "replace")


def cache_read(url: str, sub: str) -> bytes | None:
    p = cache_path(url, sub)
    return p.read_bytes() if p.exists() else None


# ---------------------------------------------------------------- news releases


def collect_news(do_fetch: bool) -> list[dict]:
    out = []
    for y in NEWS_YEARS:
        url = f"{ERCOT}/news/releases?year={y}" if y < 2026 else f"{ERCOT}/news/releases"
        body = fetch(url, "news")[0] if do_fetch else cache_read(url, "news")
        if body is None:
            continue
        s = body.decode("utf-8", "replace")
        for d, href, title in re.findall(
            r"(\d{2}/\d{2}/\d{4})\s*</td>\s*<td[^>]*>\s*<a[^>]*href=\"(/news/release/[^\"]+)\"[^>]*>(.*?)</a>", s, re.S
        ):
            title = clean(title)
            if not GRID_WORDS.search(title) or re.search(
                r"\b(emite|alerta|pide|solicita|conservación|ahora|está)\b", title, re.I
            ):
                continue
            rel = fetch(ERCOT + href, "news")[0] if do_fetch else cache_read(ERCOT + href, "news")
            text = news_text(rel.decode("utf-8", "replace")) if rel else ""
            day = dt.datetime.strptime(d, "%m/%d/%Y").date()
            out.append({"source": "ercot_news", "url": ERCOT + href, "day": day, "title": title, "text": text})
    return out


def news_text(page: str) -> str:
    m = re.search(r"News Release</h\d>(.*?)###", page, re.S) or re.search(r"(\(Austin, TX\).*?)###", page, re.S)
    body = m.group(1) if m else page
    return re.sub(r"^.*?document\.title\s*=\s*'.*?';\s*", "", clean(body))


# ---------------------------------------------------------------- market notices

MKT_ID = re.compile(r"[A-Z]-[A-Z]?\d{6}(?:-\d+)?[A-Z]?")


def collect_mkt(do_fetch: bool) -> list[dict]:
    listed: dict[str, dict] = {}
    for page in range(1, 200):
        url = (
            f"{ERCOT}/services/comm/mkt_notices/archives?page={page}&sf=&order=down&category=&keyword="
            f"&sd={MKT_FROM}&ed=2026-10-24&pageSize=100"
        )
        body = fetch(url, "mkt_list")[0] if do_fetch else cache_read(url, "mkt_list")
        if body is None:
            break
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", body.decode("utf-8", "replace"), re.S)
        n = 0
        for tr in rows:
            m = re.search(
                r"(\d{2}/\d{2}/\d{4}).*?href=\"/services/comm/mkt_notices/([^\"]+)\"[^>]*>(.*?)</a>", tr, re.S
            )
            if not m:
                continue
            n += 1
            nid, subject = m.group(2), clean(m.group(3))
            subject = re.sub(rf"^{re.escape(nid)}\s*", "", subject)
            listed.setdefault(
                nid, {"id": nid, "day": dt.datetime.strptime(m.group(1), "%m/%d/%Y").date(), "subject": subject}
            )
        if n < 100:
            break
    sitemap = (CACHE / "sitemap.xml").read_text() if (CACHE / "sitemap.xml").exists() else ""
    for nid in re.findall(r"/services/comm/mkt_notices/([A-Z]-[A-Z]\d{6}-\d+)</loc>", sitemap):
        listed.setdefault(nid, {"id": nid, "day": None, "subject": ""})
    out = []
    for nid, row in sorted(listed.items()):
        want = row["day"] is None or MKT_OPS_WORDS.search(row["subject"])
        url = f"{ERCOT}/services/comm/mkt_notices/{nid}"
        body = (fetch(url, "mkt_detail")[0] if do_fetch else cache_read(url, "mkt_detail")) if want else None
        det = mkt_detail(body.decode("utf-8", "replace")) if body else {}
        out.append(
            {
                "source": "ercot_market_notice",
                "url": url,
                "id": nid,
                "day": row["day"],
                "subject": det.get("subject") or row["subject"],
                **det,
            }
        )
    return out


def mkt_detail(page: str) -> dict:
    t = clean(re.sub(r"</(p|div|tr|li|h\d)>", "\n", page))
    sent = re.search(r"Sent:\s*(\d{1,2}/\d{1,2}/\d{2}),?\s*(\d{1,2}:\d{2})\s*([AP]M)", t)
    out = {}
    if sent:
        out["sent"] = dt.datetime.strptime(" ".join(sent.groups()), "%m/%d/%y %I:%M %p").replace(tzinfo=CPT)
    subj = re.search(r"Subject:\s*(\S+)\s+(.*?)\s+NOTICE DATE:", t)
    if subj:
        out["subject"] = subj.group(2)
    ntype = re.search(r"NOTICE TYPE:\s*\S+\s+(.*?)\s+SHORT DESCRIPTION:", t)
    if ntype:
        out["notice_category"] = ntype.group(1)
    long = re.search(r"SHORT DESCRIPTION:(.*?)(?:CONTACT:|If you are receiving email)", t, re.S)
    out["text"] = long.group(1).strip() if long else ""
    aff = re.search(r"DAYS AFFECTED:\s*(.*?)\s+LONG DESCRIPTION:", t)
    if aff:
        out["days_affected"] = aff.group(1)
    return out


# ---------------------------------------------------------------- classification

EEA_RE = re.compile(r"(?:EEA|Energy Emergency Alert)\s*(?:\(EEA\)\s*)?(?:Level\s*|level\s*|-\s*)?([123])\b")
STEP_RE = re.compile(
    r"from (?:EEA|Energy Emergency Alert)\s*(?:Level\s*)?[123] to (?:(?:EEA|Energy Emergency Alert)\s*(?:Level\s*)?"
    r"([123])|(Normal))",
    re.I,
)
EXIT_RE = re.compile(
    r"return(?:ing|ed)? to normal|no longer in (?:an )?(?:EEA|emergency)|exited (?:EEA|emergency)|"
    r"(?:EEA|emergency operations) (?:has|have) ended|\bend(?:ing|s)? (?:EEA|Energy Emergency Alert)",
    re.I,
)
AT_RE = re.compile(r"(?:\b[Aa]t\s+(\d{1,2}):?(\d{2})\b|^(?:[A-Za-z ]+:\s*)?(\d{1,2}):(\d{2})\b)")
CANCEL = "ercot has cancelled the following notice:"
AREAS = {  # phrases ERCOT uses for local conditions -> GridSimEnv regions (gridsim_core.task.REGIONS values)
    "far west": "west",
    "west texas": "west",
    "permian": "west",
    "taylor county": "west",
    "abilene": "west",
    "san angelo": "west",
    "odessa": "west",
    "midland": "west",
    "rio grande valley": "south",
    "the valley": "south",
    "valley": "south",
    "laredo": "south",
    "corpus christi": "south",
    "san antonio": "south",
    "panhandle": "panhandle",
    "houston": "houston",
    "freeport": "houston",
    "dallas": "north",
    "fort worth": "north",
    "dfw": "north",
    "austin": "central",
    "north central": "north",
    "south central": "central",
    "coast": "houston",
    "west": "west",
    "north": "north",
    "south": "south",
}
SYSTEM_TYPES = {"EEA1", "EEA2", "EEA3", "conservation_appeal", "weather_watch", "Watch", "Emergency", "Advisory", "OCN"}


def classify_ops(text: str, ercot_type: str) -> tuple[str, str, str, list[str]]:
    """(type, level, action, tags) for an ops message; action is issue, cancel (ERCOT's cancellation of an earlier
    message, classified as that message) or end (a return to normal)."""
    cancel = text.lower().startswith(CANCEL)
    body = text[len(CANCEL) :].strip() if cancel else text
    tl, et = body.lower(), ercot_type.strip()
    tags = []
    if re.search(r"\btest\b", tl) and re.search(r"notification|test of", tl):
        return "other", "test", "cancel" if cancel else "issue", ["test"]
    if "cm-asm-notf" in tl or re.search(
        r"(responsive reserve|non-spin|ecrs|regulation|load resources?|emergency response service)\b.*"
        r"(deployed|recalled|released|deployment)",
        tl,
    ):
        tags.append("as_deployment")
    if re.search(r"\bruc\b|reliability unit commitment", tl):
        tags.append("ruc")
    if "dc tie" in tl:
        tags.append("dc_tie")
    if "sudden loss of generation" in tl:
        tags.append("daily_loss_of_gen")
    if "transmission emergency" in tl:
        tags.append("transmission_emergency")
    if re.search(
        r"solution (?:run |processing )?time|running solution|long run|internal (?:issue|system)|"
        r"input error|price validation|currently unavailable|not solv|has not solved|timeline deviation|"
        r"not completing|failure for he|software|tool|postpone|\bdam is complete|druc will|long dam|"
        r"dam solution|long (?:solution|run|iteration)|mis posting|mis page|dam (?:is still running|for od)|"
        r"disregard|as posting|failover|has published|failure of sced|sudden loss of generation|rsasm|sasm",
        tl,
    ):
        tags.append("market_system")
    if re.search(
        r"generic transmission constraint|\bgtc\b|\birol\b|transmission watch|post-contingency|"
        r"unsolved contingency|local congestion|\bdc_[a-z]\b",
        tl,
    ):
        tags.append("transmission")
    action = "cancel" if cancel else "issue"
    step = STEP_RE.search(body)
    if (step and step.group(2)) or (not step and EXIT_RE.search(body)):
        return "Emergency", "EEA_exit", "cancel" if cancel else "end", tags
    if step:
        return f"EEA{step.group(1)}", f"EEA{step.group(1)}", action, tags
    m = EEA_RE.search(body)
    if m and "continuation of EEA" not in body:
        return f"EEA{m.group(1)}", f"EEA{m.group(1)}", action, tags
    if "conserv" in tl and re.search(r"appeal|request|conservation notice|conserve", tl):
        return "conservation_appeal", "conservation", action, tags
    if "weather watch" in tl:
        return "weather_watch", "Weather Watch", action, tags
    key = et.lower()
    for typ in ("Watch", "Advisory", "OCN"):
        if key.startswith(typ.lower()):
            return typ, typ, action, tags
    if key.startswith("emergency") or key.startswith("energy emergency"):
        return "Emergency", "Emergency", action, tags
    if "operating condition notice" in tl or re.search(r"\bocn\b", tl):
        return "OCN", "OCN", action, tags
    if re.search(r"\badvisory\b", tl) and re.search(r"issu|advisory (?:has been|is) (?:issued|in effect)", tl):
        return "Advisory", "Advisory", action, tags
    if re.search(r"(?:issued|issuing) a watch|watch (?:has been |is )?issued", tl):
        return "Watch", "Watch", action, tags
    return "other", et or "Operational Information", action, tags


def grid_condition(typ: str, tags: list[str]) -> bool:
    """A system-wide supply, demand or weather condition (EEA, conservation, Weather Watch, capacity Watch/Advisory/OCN
    or Emergency), not a market-system delay, a local transmission problem or a test."""
    if typ in ("EEA1", "EEA2", "EEA3", "conservation_appeal", "weather_watch"):
        return True
    return typ in ("Watch", "Advisory", "OCN", "Emergency") and not set(tags) & {
        "market_system",
        "transmission_emergency",
        "transmission",
        "dc_tie",
        "test",
    }


def classify_news(title: str) -> tuple[str, str, str]:
    tt = title.lower()
    if re.search(r"\btest\b|no conservation|minimum operating reserves|creates|program", tt):
        return "other", "news", "issue"
    if re.search(r"exit|return(ed)? to normal|\bend\b|ended", tt) and re.search(r"emergenc|eea", tt):
        return "Emergency", "EEA_exit", "end"
    m = EEA_RE.search(title)
    if m:
        return f"EEA{m.group(1)}", f"EEA{m.group(1)}", "issue"
    if re.search(r"calls for rotating outages|rotating outages (?:begin|are in progress)", tt):
        return "EEA3", "EEA3", "issue"
    if "conserv" in tt and re.search(r"request|appeal|notice|conserve", tt):
        return "conservation_appeal", "voluntary conservation notice" if "voluntary" in tt else "conservation", "issue"
    if "weather watch" in tt:
        return "weather_watch", "Weather Watch", "issue"
    if re.search(r"(?:enter|initiat|declar)\w* (?:emergency|energy emergency)", tt):
        return "Emergency", "Emergency", "issue"
    return "other", "news", "issue"


def affects_of(text: str, typ: str) -> tuple[str | None, list[str] | None]:
    """(affects, regions): a stated local area and the GridSimEnv regions it maps to, else system-wide."""
    m = re.search(
        r"\b(?:in|for|near|around) (?:the )?((?:[A-Z][\w.'-]*\s?){1,4}?)(?: County| Counties| area| Area| "
        r"region| Region| Texas| zone| Load Zone)\b",
        text,
    ) or re.search(
        r"\b(?:in|for) (?:the )?(Far West Texas|Rio Grande Valley|Lower Rio Grande Valley|Valley|Panhandle|"
        r"Houston|Laredo|Corpus Christi)\b",
        text,
    )
    if m:
        area = m.group(0).split(" ", 1)[1].removeprefix("the ").strip()
        area = area.removeprefix("ERCOT ").strip()
        low = area.lower()
        if low in ("region", "system", "ercot region") or not low:
            return "system-wide", None
        regions = sorted({r for k, r in AREAS.items() if k in low})
        return area, regions or None
    if typ in SYSTEM_TYPES:
        return "system-wide", None
    return None, None


def due_to(text: str) -> str:
    """The stated subject of a notice: 'OCN for <x>' or 'due to <x>', cut at the first sentence end."""
    m = re.search(
        r"\b(?:OCN|Advisory|Watch|Notice|AAN)\s+(?:issued\s+|has been issued\s+|continues\s+)?for\s+"
        r"(?:an?\s+|the\s+)?(.+?)(?:\.\s|\.$|;|$)",
        text,
    ) or re.search(r"\bdue to (?:the |a |an )?(.+?)(?:\.\s|\.$|;|$)", text, re.I)
    return m.group(1).strip().rstrip(",. ") if m else ""


def summarise(typ: str, level: str, action: str, text: str, tags: list[str]) -> str:
    """A one-line paraphrase (<=200 chars) from templates: type, level, the stated reason and window, never the
    verbatim text."""
    why = due_to(text)
    if len(why) > 110:
        why = why[:107].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    why = f" ({why})" if why else ""
    if "test" in tags:
        return "ERCOT tested its emergency notification system; no action needed."
    if level == "EEA_exit":
        if action == "cancel":
            return "ERCOT withdrew an earlier end-of-emergency message (superseded by a later one)."
        return "ERCOT ended the Energy Emergency Alert; the grid is back to normal operations."
    name = {"conservation_appeal": "conservation appeal", "weather_watch": "Weather Watch"}.get(typ, typ)
    if typ.startswith("EEA"):
        name = f"Energy Emergency Alert level {typ[-1]}"
    if action == "cancel":
        if typ == "other":
            return f"ERCOT cancelled an earlier operations message{why}."[:200]
        return f"ERCOT cancelled its {name}{why}."[:200]
    if typ.startswith("EEA"):
        return f"ERCOT declared {name}{why}."[:200]
    if typ == "conservation_appeal":
        w = window_of(text)
        return f"ERCOT asked the public to conserve electricity{(' ' + w) if w else ''}{why}."[:200]
    if typ in ("weather_watch", "Watch", "Advisory", "OCN", "Emergency"):
        art = "an" if name[0] in "AEIOU" else "a"
        local = " for a local transmission problem" if "transmission_emergency" in tags else ""
        return f"ERCOT issued {art} {name}{local}{why}."[:200]
    if "as_deployment" in tags:
        prod = next(
            (
                p
                for p in ("Non-Spin", "Responsive Reserve", "ECRS", "Regulation", "Load Resource")
                if p.lower() in text.lower()
            ),
            "ancillary service",
        )
        verb = "recalled" if re.search(r"recall|released|DEPLOY_MW: 0\.0", text, re.I) else "deployed"
        mw = re.search(r"DEPLOY_MW:\s*([\d.]+)", text)
        return f"ERCOT {verb} {prod}{(' (' + mw.group(1) + ' MW)') if mw and verb == 'deployed' else ''}."
    if "dc_tie" in tags:
        return f"DC tie availability or curtailment notice{why}."[:200]
    if "daily_loss_of_gen" in tags:
        return "Daily report: no sudden loss of generation above 450 MW on the previous day."
    if "ruc" in tags:
        return f"Reliability Unit Commitment notice{why}."[:200]
    return f"ERCOT operations message ({level}){why}."[:200]


def window_of(text: str) -> str:
    m = re.search(
        r"(?:from|between)\s+(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)\s*(?:to|and|until|-|–)\s*"
        r"(\d{1,2}(?::\d{2})?\s*[ap]\.?m\.?)",
        text,
        re.I,
    )
    return f"from {m.group(1)} to {m.group(2).rstrip('.')}" if m else ""


def event_time(text: str, issued: dt.datetime) -> str | None:
    """'At 19:25 ERCOT ...': the stated event time on the issue day (or the day before if it would be later)."""
    m = AT_RE.search(re.sub(r"^" + CANCEL, "", text, flags=re.I).strip())
    if not m:
        return None
    hh, mm = (int(m.group(1)), int(m.group(2))) if m.group(1) else (int(m.group(3)), int(m.group(4)))
    if hh > 23 or mm > 59:
        return None
    ev = issued.replace(hour=hh, minute=mm, second=0)
    if ev > issued + dt.timedelta(minutes=5):
        ev -= dt.timedelta(days=1)
    return iso(ev)


def sha(*parts) -> str:
    return hashlib.sha1("\x1f".join(map(str, parts)).encode()).hexdigest()


# ---------------------------------------------------------------- assemble


def build_ops(raw: list[dict]) -> list[dict]:
    """Union rows across live pages and snapshots: one notice per (second, text, type)."""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in raw:
        groups[(iso(r["issued"]), r["text"], r["ercot_type"])].append(r)
    rows = []
    for (issued_s, text, et), rs in groups.items():
        issued = rs[0]["issued"]
        status = Counter(r["status"] for r in rs).most_common(1)[0][0]
        typ, level, action, tags = classify_ops(text, et)
        affects, regions = affects_of(text, typ)
        if not set(tags) & {"transmission", "transmission_emergency"}:
            regions = None
        first_seen = min(r["seen_at"] for r in rs)
        srcs = sorted({r["source"] for r in rs})
        url = next(
            (r["url"] for r in rs if r["source"] == "ercot_ops_live"), min(rs, key=lambda r: r["seen_at"])["url"]
        )
        rows.append(
            {
                "notice_id": "OPS-" + sha(issued_s, text, et)[:12],
                "source": "ERCOT",
                "channel": "operations_message",
                "type": typ,
                "level": level,
                "action": action,
                "ercot_type": et,
                "status": status,
                "title": text if len(text) <= 160 else text[:157] + "...",
                "issued_at": issued_s,
                "issued_at_utc": iso(issued.astimezone(dt.UTC)),
                "timestamp_quality": "minute",
                "tz_basis": rs[0]["tz_basis"],
                "event_time": event_time(text, issued),
                "url": url,
                "provenance": srcs,
                "first_seen_utc": iso(first_seen),
                "n_snapshots": len(rs),
                "text": text,
                "summary": summarise(typ, level, action, text, tags),
                "affects": affects,
                "regions": regions,
                "tags": tags,
                "operator_relevant": typ != "other" or bool(set(tags) & {"as_deployment", "ruc"}),
                "grid_condition": grid_condition(typ, tags),
            }
        )
    by_text: dict[str, list[dict]] = defaultdict(list)
    for r in sorted(rows, key=lambda r: r["issued_at_utc"]):
        if r["action"] == "cancel":
            orig = r["text"][len(CANCEL) :].strip()
            prev = [p for p in by_text.get(orig, []) if p["issued_at_utc"] <= r["issued_at_utc"]]
            if prev:
                r["cancels"] = prev[-1]["notice_id"]
        by_text[r["text"]].append(r)
    return rows


def ops_coverage(raw: list[dict]) -> dict:
    """Each page (live or snapshot) shows every message from its oldest row to when it was seen (a monthly page: to
    its month end). The union of those windows, per CPT day, is how much of the day the archive covers."""
    pages: dict[str, list[dict]] = defaultdict(list)
    for r in raw:
        pages[r["url"]].append(r)
    wins, snaps, late = [], [], []
    for url, rs in pages.items():
        seen = rs[0]["seen_at"]
        lo = min(r["issued"] for r in rs)
        hi = seen
        m = re.search(r"m=(\d+)&(?:amp;)?y=(\d+)", url)
        m2 = re.search(r"/opsmessages/(\d{4})/(\d{2})", url)
        if m or m2:
            y, mo = (int(m.group(2)), int(m.group(1))) if m else (int(m2.group(1)), int(m2.group(2)))
            end = dt.datetime(y + mo // 12, mo % 12 + 1, 1, tzinfo=CPT)
            lo = min(lo, dt.datetime(y, mo, 1, tzinfo=CPT))
            hi = min(seen, end)
        wins.append((lo.astimezone(dt.UTC), hi))
        snaps.append({"url": url, "seen_utc": iso(seen), "oldest_utc": iso(lo.astimezone(dt.UTC)), "rows": len(rs)})
        late += [
            {"url": url, "issued_at": iso(r["issued"]), "seen_utc": iso(seen), "text": r["text"][:80]}
            for r in rs
            if r["issued"] > seen + dt.timedelta(minutes=1)
        ]
    wins.sort()
    merged: list[list[dt.datetime]] = []
    for lo, hi in wins:
        if merged and lo <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    days: dict[str, float] = {}
    for lo, hi in merged:
        d = lo.astimezone(CPT).date()
        while True:
            a = dt.datetime.combine(d, dt.time(0), CPT)
            b = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(0), CPT)
            if a >= hi:
                break
            ov = (min(b, hi) - max(a, lo)).total_seconds()
            if ov > 0:
                days[d.isoformat()] = round(min(1.0, days.get(d.isoformat(), 0.0) + ov / (b - a).total_seconds()), 4)
            d += dt.timedelta(days=1)
    return {
        "days": dict(sorted(days.items())),
        "windows": [[iso(a), iso(b)] for a, b in merged],
        "pages": sorted(snaps, key=lambda s: s["seen_utc"]),
        "seen_before_issued": late,
    }


def build_news(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        typ, level, action = classify_news(r["title"])
        affects, regions = affects_of(r["text"][:600], typ)
        day = r["day"]
        rows.append(
            {
                "notice_id": "NR-" + r["url"].rsplit("/", 1)[-1],
                "source": "ERCOT",
                "channel": "news_release",
                "type": typ,
                "level": level,
                "action": action,
                "ercot_type": "News Release",
                "status": "",
                "title": r["title"],
                "issued_at": day.isoformat(),
                "issued_at_utc": None,
                "timestamp_quality": "day",
                "tz_basis": "date_only",
                "event_time": None,
                "url": r["url"],
                "provenance": ["ercot_news"],
                "first_seen_utc": None,
                "n_snapshots": 1,
                "text": r["text"],
                "summary": summarise(typ, level, action, r["title"] + ". " + r["text"][:400], []),
                "affects": affects,
                "regions": regions,
                "tags": ["news_release"],
                "effective_window": window_of(r["title"]) or window_of(r["text"][:600]) or None,
                "operator_relevant": typ != "other",
                "grid_condition": grid_condition(typ, []),
            }
        )
    return rows


def build_mkt(raw: list[dict]) -> list[dict]:
    rows = []
    for r in raw:
        sent = r.get("sent")
        day = r["day"] or (sent.date() if sent else mkt_id_day(r["id"]))
        if day is None:
            continue
        subj = r["subject"]
        cat = r.get("notice_category", "")
        tl = (subj + " " + r.get("text", "")[:600]).lower()
        typ, level = "market_notice", cat or "Market Notice"
        tags = ["market_notice"]
        if re.search(r"enforcement discretion|202\(c\)", tl):
            tags.append("weather_emergency_order")
        if re.search(r"\bruc\b|reliability unit commitment", tl):
            tags.append("ruc")
        if "suspension of operations" in tl:
            tags.append("nso")
        rows.append(
            {
                "notice_id": r["id"],
                "source": "ERCOT",
                "channel": "market_notice",
                "type": typ,
                "level": level,
                "action": "issue",
                "ercot_type": "Market Notice",
                "status": "",
                "title": subj,
                "issued_at": iso(sent) if sent else day.isoformat(),
                "issued_at_utc": iso(sent.astimezone(dt.UTC)) if sent else None,
                "timestamp_quality": "minute" if sent else "day",
                "tz_basis": "cpt_assumed" if sent else "date_only",
                "event_time": None,
                "url": r["url"],
                "provenance": ["ercot_market_notice"],
                "first_seen_utc": None,
                "n_snapshots": 1,
                "text": r.get("text", ""),
                "summary": f"ERCOT market notice {r['id']}{(' (' + cat + ')') if cat else ''}.",
                "affects": None,
                "regions": None,
                "tags": tags,
                "days_affected": r.get("days_affected"),
                "operator_relevant": len(tags) > 1,
                "grid_condition": False,
            }
        )
    return rows


def mkt_id_day(nid: str) -> dt.date | None:
    m = re.match(r"[A-Z]-[A-Z]?(\d{2})(\d{2})(\d{2})", nid)
    if not m:
        return None
    try:
        return dt.date(2000 + int(m.group(3)), int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-fetch", action="store_true", help="parse the cache only")
    ap.add_argument("--sources", default="ops_live,ops_wayback,news,mkt")
    a = ap.parse_args()
    do_fetch = not a.no_fetch
    srcs = set(a.sources.split(","))
    rows: list[dict] = []
    raw_ops = []
    if "ops_live" in srcs:
        raw_ops += collect_ops_live(do_fetch)
    if "ops_wayback" in srcs:
        raw_ops += collect_ops_wayback(do_fetch)
    rows += build_ops(raw_ops)
    if raw_ops:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "ops_coverage.json").write_text(json.dumps(ops_coverage(raw_ops), indent=0) + "\n")
    if "news" in srcs:
        rows += build_news(collect_news(do_fetch))
    if "mkt" in srcs:
        rows += build_mkt(collect_mkt(do_fetch))
    rows.sort(key=lambda r: (r["issued_at_utc"] or r["issued_at"] + "T23:59:59", r["notice_id"]))
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "notices.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=False) + "\n")
    c = Counter((r["channel"], r["timestamp_quality"]) for r in rows)
    print(len(rows), dict(c))


if __name__ == "__main__":
    main()
