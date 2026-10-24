"""data/notices/coverage.md: counts by year and type, minute-stamp shares, archive gaps, the timezone check and the
timestamp QA against known events. python scripts/notice_report.py"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter, defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo

from gridsim_core.notices import NWS_DAY_PHENOMENA
from gridsim_core.notices import rows as notice_rows

ROOT = Path(__file__).resolve().parents[1]
D = ROOT / "data" / "notices"
CPT = ZoneInfo("America/Chicago")
YEARS = range(2018, 2027)
TYPES = [
    "EEA3",
    "EEA2",
    "EEA1",
    "Emergency",
    "conservation_appeal",
    "weather_watch",
    "Watch",
    "Advisory",
    "OCN",
    "other",
    "market_notice",
]
# (label, day, type, level, action, expected CPT clock time or None, source of the expectation)
KNOWN = [
    ("Sep 6 2023 EEA2", "2023-09-06", "EEA2", None, "issue", "19:25", "v2 plan; ERCOT System Ops Update 2023-10-09"),
    ("Sep 6 2023 EEA1 (step down)", "2023-09-06", "EEA1", None, "issue", "20:27", "v2 plan"),
    ("Sep 6 2023 normal", "2023-09-06", "Emergency", "EEA_exit", "end", "20:37", "v2 plan"),
    ("Sep 6 2023 conservation appeal", "2023-09-06", "conservation_appeal", None, "issue", None, "[to find]"),
    ("Uri EEA3", "2021-02-15", "EEA3", None, "issue", "01:23", "v2 plan (display-only)"),
    ("Uri EEA1", "2021-02-15", "EEA1", None, "issue", None, "[to find]"),
    ("Uri EEA2", "2021-02-15", "EEA2", None, "issue", None, "[to find]"),
    ("Elliott Dec 20-24 2022 (any grid notice)", "2022-12-20..2022-12-24", None, None, "issue", None, "[to find]"),
    (
        "Elliott Dec 22-24 2022: no conservation appeal",
        "2022-12-22..2022-12-24",
        "conservation_appeal",
        None,
        "issue",
        "none",
        "[to confirm]",
    ),
    ("Elliott Dec 22-24 2022: no EEA", "2022-12-22..2022-12-24", "EEA*", None, "issue", "none", "v2 plan"),
    ("Heather appeal for Jan 15 2024", "2024-01-14", "conservation_appeal", None, "issue", None, "[to find]"),
    ("Heather appeal for Jan 16 2024", "2024-01-15", "conservation_appeal", None, "issue", None, "[to find]"),
    ("Heather Jan 13-17 2024 (any grid notice)", "2024-01-13..2024-01-17", None, None, "issue", None, "[to find]"),
    ("Aug 20 2023 voluntary conservation", "2023-08-20", "conservation_appeal", None, "issue", None, "[to find]"),
    ("Fern Jan 24-27 2026: no EEA", "2026-01-24..2026-01-27", "EEA*", None, "issue", "none", "v2 plan"),
    (
        "Fern Jan 24-27 2026: no conservation",
        "2026-01-24..2026-01-27",
        "conservation_appeal",
        None,
        "issue",
        "none",
        "v2 plan",
    ),
]


NOTES = """\
## Notes and known limits

- No machine-readable ERCOT notice feed was found: no RSS or JSON behind Operations Messages, Market Notices
  or news releases, and none in the sitemap; we did not find a notice product in the public API (not checked
  exhaustively). TXANS keeps no public history. The grid-conditions dashboard is current-state only, which
  suits the daily forward capture, not history.
- ercot.com keeps Operations Messages for six months only (`?m=MM&y=YYYY` for older months returns an empty
  table). Everything older comes from Internet Archive captures of the same ERCOT page (provenance
  `ercot_ops_wayback`, `url` is the capture). The old site (to about 2021) also had monthly archive pages
  (`/opsmessages/YYYY/MM`), which the Archive captured for most months from May 2019 to Oct 2021.
- Market Notices: the archive search reaches back three years (from 2023-10-24); older notices are reachable
  only by id (ids listed in ercot.com's sitemap are included). Detail pages, which carry the `Sent:` minute,
  were fetched only for subjects that look operational; the rest are dated rows tagged `market_notice`.
- News releases carry a date only; their `effective_window` is parsed from the title or first paragraph when
  stated (for example 'from 6 p.m. to 9 p.m.'). They never become intraday bulletins.
- `summary` is built from templates (type, level, the stated reason or window), not copied text, per the V2-D4
  recommendation; `text` is verbatim and for local use only.
- Crawling: ercot.com at 1 request/s, web.archive.org at one request per 4 s, IEM at its robots.txt crawl
  delay (120 s); a named user agent; every response cached under `cache/raw/notices/` (git-ignored), so a
  rebuild (`--no-fetch`) makes no requests. No source blocked the crawl.
- About 70 Archive captures came back gzip-encoded (the raw bytes ERCOT served); they are decompressed before
  parsing.
- Uri EEA3: ERCOT's own message says "At 01:20, rotating outages are in progress" and was posted at 01:25:40
  CST; the plan's 01:23 is not in ERCOT's log (it matches neither the stated nor the posted time). For the
  reveal rule only the posted time matters: it reveals at 01:30 either way.
- Notice days come to about 10-30% of fully covered days per year (ERCOT notices or load-moving NWS
  warnings), below the plan's ~40% estimate. Counting NWS heat advisories (HT.Y, the second most common
  product) as well would raise the share in summer; `NWS_DAY_PHENOMENA` in `gridsim_core.notices` sets this.
- `text` is verbatim ERCOT text inside `notices.jsonl.gz`, which sits in `data/` and so ships in the wheel
  and the env image. Strip it (or drop `data/notices` from the wheel) before anything public, per V2-D4.

""".splitlines()


def rows(name):
    return list(notice_rows(D, name))


def local(r):
    if r["timestamp_quality"] != "minute":
        return None
    return dt.datetime.fromisoformat(r["issued_at_utc"]).astimezone(CPT)


def match(ns, day, typ, level, action):
    if ".." in day:
        a, b = day.split("..")
        days = {
            (dt.date.fromisoformat(a) + dt.timedelta(n)).isoformat()
            for n in range((dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days + 1)
        }
    else:
        days = {day}
    out = []
    for r in ns:
        if r["issued_at"][:10] not in days or r.get("action") != action:
            continue
        if typ is None and not r.get("grid_condition"):
            continue
        if typ == "EEA*" and not r["type"].startswith("EEA"):
            continue
        if typ not in (None, "EEA*") and r["type"] != typ:
            continue
        if level and r["level"] != level:
            continue
        out.append(r)
    return sorted(out, key=lambda r: (r["timestamp_quality"] != "minute", r["issued_at"]))


def fmt(r):
    t = local(r)
    when = t.strftime("%H:%M:%S %Z") if t else f"{r['issued_at']} (day)"
    ev = f", stated {dt.datetime.fromisoformat(r['event_time']).strftime('%H:%M')}" if r.get("event_time") else ""
    return f"{r['channel'].replace('_', ' ')} {when}{ev}"


def span(day):
    if ".." not in day:
        return [day]
    a, b = (dt.date.fromisoformat(x) for x in day.split(".."))
    return [(a + dt.timedelta(n)).isoformat() for n in range((b - a).days + 1)]


def qa(ns, days):
    lines = ["| Event | Expected (CPT) | Found | Verdict |", "|---|---|---|---|"]
    mism = []
    for label, day, typ, level, action, exp, src in KNOWN:
        hits = match(ns, day, typ, level, action)
        cov = min(days.get(d, 0.0) for d in span(day))
        if exp == "none":
            verdict = (
                f"MISMATCH: {len(hits)} found"
                if hits
                else "OK (none, days fully covered)"
                if cov >= 0.999
                else f"UNKNOWN (none found, archive covers only {cov:.0%} of the days)"
            )
            found = "; ".join(fmt(h) for h in hits[:3]) or "none in the archive"
            if hits or cov < 0.999:
                mism.append(label)
            lines.append(f"| {label} | none ({src}) | {found} | {verdict} |")
            continue
        found = (
            "; ".join(
                fmt(h) + (f" [{h['notice_id']}]" if h["channel"] != "operations_message" else "") for h in hits[:4]
            )
            or "not in the archive"
        )
        if not exp:
            verdict = "found" if hits else "MISSING"
            if not hits:
                mism.append(label)
        else:
            mins = [h for h in hits if h["timestamp_quality"] == "minute"]
            eh, em = map(int, exp.split(":"))
            best = None
            for h in mins:
                ev = dt.datetime.fromisoformat(h["event_time"]).astimezone(CPT) if h.get("event_time") else None
                t = local(h)
                d_ev = (ev.hour * 60 + ev.minute) - (eh * 60 + em) if ev else None
                d_is = (t.hour * 60 + t.minute) - (eh * 60 + em)
                cand = (abs(d_ev) if d_ev is not None else abs(d_is), d_ev, d_is)
                best = min(best, cand) if best else cand
            if best is None:
                verdict = "MISSING (no minute-stamped row)"
                mism.append(label)
            elif best[0] == 0:
                verdict = "OK (exact)" if best[1] == 0 else f"OK (issued at the stated minute; posted {best[2]:+d} min)"
            else:
                verdict = (
                    f"MISMATCH: stated time {best[1]:+d} min, posted {best[2]:+d} min vs expected"
                    if best[1] is not None
                    else f"MISMATCH: posted {best[2]:+d} min vs expected"
                )
                mism.append(label)
        if not hits and cov < 0.999:
            verdict += f" (ops archive covers {cov:.0%} of the day)"
        lines.append(f"| {label} | {exp or '?'} ({src}) | {found} | {verdict} |")
    return lines, mism


def notice_day_table(ns, vt, days):
    """Share of days that are notice days (gridsim_core.notices.is_notice_day's rule), per year."""
    ercot = set()
    for r in ns:
        if r.get("grid_condition") and r.get("action") == "issue" and r["timestamp_quality"] == "minute":
            t = local(r)
            ercot.add(t.date())
            if t.hour >= 14:
                ercot.add(t.date() + dt.timedelta(days=1))
    nws = defaultdict(set)
    for v in vt:
        if v["significance"] != "W" or v["phenomena"] not in NWS_DAY_PHENOMENA:
            continue
        a = dt.datetime.fromisoformat(v["issued_at_utc"].replace("Z", "+00:00")).astimezone(CPT).date()
        b = dt.datetime.fromisoformat(v["expires_at_utc"].replace("Z", "+00:00")).astimezone(CPT).date()
        for k in range((b - a).days + 1):
            nws[v["region"]].add(a + dt.timedelta(days=k))
    regions = ["west", "panhandle", "north", "houston", "south", "central"]
    out = [
        "## Notice days",
        "",
        "A notice day (`gridsim_core.notices.is_notice_day`) has a minute-stamped ERCOT grid-condition notice issued "
        "between D-1 14:00 and D 24:00, or a load-moving NWS warning (heat, cold, winter, tropical, high wind; not "
        "severe-thunderstorm or tornado) in effect for the point's region on D. ERCOT shares are over days the ops "
        "archive fully covers (D-1 and D); NWS shares are over all days.",
        "",
        "| Year | covered days | ERCOT notice days (share of covered) | "
        + " | ".join(f"NWS {r}" for r in regions)
        + " | either, mean over regions (covered days) |",
        "|---" * (4 + len(regions)) + "|",
    ]
    for y in range(2019, YEARS.stop):
        start, end = dt.date(y, 1, 1), min(dt.date(y, 12, 31), dt.date(2026, 10, 23))
        ds = [start + dt.timedelta(k) for k in range((end - start).days + 1)]
        cov = [
            d for d in ds if min(days.get(d.isoformat(), 0), days.get((d - dt.timedelta(1)).isoformat(), 0)) >= 0.999
        ]
        e = sum(d in ercot for d in cov)
        nshare = [sum(d in nws[r] for d in ds) / len(ds) for r in regions]
        either = (
            sum(sum((d in ercot) or (d in nws[r]) for d in cov) for r in regions) / (len(cov) * len(regions))
            if cov
            else 0
        )
        out.append(
            f"| {y} | {len(cov)} | {e} ({(e / len(cov) if cov else 0):.0%}) | "
            + " | ".join(f"{x:.0%}" for x in nshare)
            + f" | {either:.0%} |"
        )
    return out + [""]


def main():
    ns, vt = rows("notices"), rows("nws_vtec")
    cov = json.loads((D / "ops_coverage.json").read_text()) if (D / "ops_coverage.json").exists() else {"days": {}}
    out = [
        "# ERCOT notice archive: coverage and QA",
        "",
        f"Generated by `scripts/notice_report.py` from `notices.jsonl.gz` ({len(ns)} rows), `nws_vtec.jsonl.gz` "
        f"({len(vt)} rows) and `ops_coverage.json`. Times are Central prevailing time (CPT) unless marked UTC.",
        "",
    ]
    out += [
        "## Sources",
        "",
        "| Channel | What it is | Timestamps | Depth |",
        "|---|---|---|---|",
        "| operations_message | ERCOT control-room Operations Messages (OCN, Advisory, Watch, Emergency, EEA, "
        "conservation, "
        "AS deployments, DC ties). ercot.com keeps the last 6 months; older months come from Internet Archive "
        "snapshots of the same page | to the second, as posted | 2018 on, gappy before May 2026 (see coverage) |",
        "| news_release | ERCOT news releases (conservation appeals, Weather Watches, EEA declarations and exits) | "
        "date only | 2018 on |",
        "| market_notice | ERCOT Market Notices (settlement, IT, rules, GTCs, NSOs, TCEQ enforcement discretion) | "
        "detail page `Sent:` to the minute; listing date only | archive search covers the last 3 years "
        "(from 2023-10-24); older ids only by direct link |",
        "| nws_vtec | NWS watches/warnings/advisories from IEM, per GridSimEnv region | to the minute (UTC) | "
        "2019 on |",
        "",
    ]
    by = defaultdict(Counter)
    minute = defaultdict(Counter)
    for r in ns:
        y = int(r["issued_at"][:4])
        k = r["type"] if r["channel"] != "market_notice" else "market_notice"
        by[y][(r["channel"], k, r.get("action", "issue"))] += 1
        minute[y][r["channel"]] += r["timestamp_quality"] == "minute"
    out += [
        "## Counts by year and type (issued, not cancellations)",
        "",
        "| Year | " + " | ".join(TYPES) + " | all rows | minute-stamped |",
        "|---" * (len(TYPES) + 3) + "|",
    ]
    for y in YEARS:
        c = Counter()
        tot = 0
        for (_, k, act), n in by[y].items():
            tot += n
            if act != "cancel":
                c[k] += n
        m = sum(minute[y].values())
        out.append(
            f"| {y} | " + " | ".join(str(c[t]) for t in TYPES) + f" | {tot} | {m} ({m / tot:.0%}) |"
            if tot
            else f"| {y} | " + " | ".join("0" for _ in TYPES) + " | 0 | - |"
        )
    out += [
        "",
        "Counts include every channel; `Emergency` holds local Transmission Emergency Notices and EEA exits "
        "(level `EEA_exit`). An ERCOT cancellation is its own row (`action: cancel`) with `cancels` pointing at the "
        "original when the original is in the archive.",
        "",
    ]
    out += [
        "### By channel and year",
        "",
        "| Year | operations_message | news_release | market_notice | minute share |",
        "|---|---|---|---|---|",
    ]
    for y in YEARS:
        ch = Counter()
        for (c, _, _), n in by[y].items():
            ch[c] += n
        tot = sum(ch.values())
        m = sum(minute[y].values())
        out.append(
            f"| {y} | {ch['operations_message']} | {ch['news_release']} | {ch['market_notice']} | "
            f"{(m / tot if tot else 0):.0%} |"
        )
    gc = Counter(r["issued_at"][:4] for r in ns if r.get("grid_condition") and r.get("action") == "issue")
    gcm = Counter(
        r["issued_at"][:4]
        for r in ns
        if r.get("grid_condition") and r.get("action") == "issue" and r["timestamp_quality"] == "minute"
    )
    out += [
        "",
        "### Grid-condition notices (the ones a battery desk acts on)",
        "",
        "`grid_condition` = EEA, conservation appeal, Weather Watch, or a Watch/Advisory/OCN/Emergency that is not a "
        "market-system delay, a geomagnetic advisory, a local transmission problem, a DC tie or a test.",
        "",
        "| Year | issued | minute-stamped | share |",
        "|---|---|---|---|",
    ]
    for y in YEARS:
        n, m = gc[str(y)], gcm[str(y)]
        out.append(f"| {y} | {n} | {m} | {(m / n if n else 0):.0%} |")
    days = cov.get("days", {})
    out += [
        "",
        "## Archive gaps (operations messages)",
        "",
        "A page shows every message from its oldest row to the moment it was fetched or captured (a monthly page: "
        "the whole month). The union of those windows is the covered time. A day with no notices is only "
        "known-quiet when it is fully covered; `gridsim_core.notices.coverage(date)` exposes this.",
        "",
        "| Year | days fully covered | partly | none | covered share of the year |",
        "|---|---|---|---|---|",
    ]
    for y in YEARS:
        start, end = dt.date(y, 1, 1), min(dt.date(y, 12, 31), dt.date(2026, 10, 23))
        n = (end - start).days + 1
        full = part = 0
        tot = 0.0
        for k in range(n):
            f = days.get((start + dt.timedelta(k)).isoformat(), 0.0)
            tot += f
            full += f >= 0.999
            part += 0 < f < 0.999
        out.append(f"| {y} | {full} | {part} | {n - full - part} | {tot / n:.0%} |")
    gaps = []
    run = None
    d0 = dt.date(2019, 1, 1)
    for k in range((dt.date(2026, 10, 23) - d0).days + 1):
        d = d0 + dt.timedelta(k)
        if days.get(d.isoformat(), 0.0) < 0.999:
            run = [d, d] if run is None else [run[0], d]
        elif run:
            gaps.append(run)
            run = None
    if run:
        gaps.append(run)
    big = sorted(gaps, key=lambda g: -(g[1] - g[0]).days)[:15]
    out += ["", f"{len(gaps)} gaps since 2019-01-01; the longest:", ""]
    out += [f"- {a} .. {b} ({(b - a).days + 1} days)" for a, b in sorted(big)]
    late = cov.get("seen_before_issued", [])
    pages = cov.get("pages", [])
    out += [
        "",
        "## Time zones",
        "",
        "- New ercot.com pages print `Oct 24, 2026 12:40:07 AM` with no zone; read as America/Chicago. Old pages "
        "(to about 2021) print `... CST` all year, including summer.",
        f"- Check: across {len(pages)} pages, {len(late)} rows would post-date the page that shows them under the "
        "prevailing-time reading (must be 0).",
    ]
    lit = lit_n = 0
    summer = [
        r
        for r in ns
        if r["channel"] == "operations_message"
        and r.get("tz_basis") == "label_CST"
        and dt.datetime.fromisoformat(r["issued_at"]).utcoffset() == dt.timedelta(hours=-5)
    ]
    for r in summer:
        lit_n += 1
        seen = dt.datetime.fromisoformat(r["first_seen_utc"])
        if dt.datetime.fromisoformat(r["issued_at_utc"]) + dt.timedelta(hours=1) > seen:
            lit += 1
    out += [
        f"- Summer rows labelled `CST`: {lit_n}. Read literally (UTC-6), {lit} of them would post-date the "
        "first snapshot that shows them, which is impossible, so the label means prevailing Central time; "
        "the stated `At HH:MM` times inside messages agree (posted a few minutes after the stated time, not an hour).",
        "- DST transitions: rows are stored with their UTC offset (`issued_at`) and in UTC (`issued_at_utc`); the "
        "reveal rule works in UTC, so a 23- or 25-hour day needs no special case. The repeated 01:00-02:00 hour on "
        "the fall-back night is ambiguous on the new pages (no zone printed); those rows take the first (CDT) "
        "reading.",
    ]
    lags = defaultdict(list)
    for r in ns:
        if (
            r["channel"] == "operations_message"
            and r.get("event_time")
            and r.get("grid_condition")
            and r.get("action") != "cancel"
        ):
            t = dt.datetime.fromisoformat(r["issued_at"])
            k = f"{r['tz_basis']}, {'summer' if t.utcoffset() == dt.timedelta(hours=-5) else 'winter'}"
            lags[k].append((t - dt.datetime.fromisoformat(r["event_time"])).total_seconds() / 60)
    out.append(
        "- Posted minus stated time (`At HH:MM` in the text), median minutes: "
        + "; ".join(
            f"{k} {sorted(v)[len(v) // 2]:.1f} (n={len(v)}, {sum(0 <= x < 30 for x in v) / len(v):.0%} within 0-30 min)"
            for k, v in sorted(lags.items())
        )
        + ". Grid-condition messages only. The same few minutes in summer and winter rules out an hour's shift."
    )
    fb = [
        r
        for r in ns
        if r["channel"] == "operations_message"
        and r.get("tz_basis") == "cpt_assumed"
        and r["issued_at"][11:13] == "01"
        and any(r["issued_at"].startswith(d) for d in ("2023-11-05", "2024-11-03", "2025-11-02"))
    ]
    out.append(f"- Rows in an ambiguous fall-back hour: {len(fb)}.")
    out += ["", "## Timestamp QA against known events", ""]
    lines, mism = qa(ns, days)
    out += lines
    out += ["", "Mismatches: " + (", ".join(mism) if mism else "none") + ".", ""]
    out += notice_day_table(ns, vt, days)
    out += [
        "## NWS alerts (IEM VTEC)",
        "",
        "`nws_vtec.jsonl.gz`: one row per (VTEC event, GridSimEnv region) for heat, cold, winter, severe-storm, "
        "tropical and wind products (warning W, watch A, advisory Y) whose zones or counties include one of the "
        "region's representative counties (`scripts/join_vtec.py` REGION_COUNTIES). `issued_at_utc` is the product "
        "issue time (IEM `product_issue`), `effective_from_utc` the VTEC begin time, `expires_at_utc` the final "
        "expiry. IEM folds CON/EXT/EXP/CAN updates into one event row, so there is nothing more to dedupe. Data: "
        "NOAA/NWS via the Iowa Environmental Mesonet; attribution required, no endorsement implied. An event's IEM "
        "page is `https://mesonet.agron.iastate.edu/vtec/?year={year}&wfo=K{wfo}&phenomena={phenomena}"
        "&significance={significance}&eventid={eventid}`.",
        "",
        "| Year | rows | "
        + " | ".join(["west", "panhandle", "north", "houston", "south", "central"])
        + " | warnings |",
        "|---" * 9 + "|",
    ]
    for y in YEARS:
        rs = [r for r in vt if r["year"] == y]
        if not rs:
            continue
        rg = Counter(r["region"] for r in rs)
        out.append(
            f"| {y} | {len(rs)} | "
            + " | ".join(str(rg[k]) for k in ["west", "panhandle", "north", "houston", "south", "central"])
            + f" | {sum(r['significance'] == 'W' for r in rs)} |"
        )
    ph = Counter((r["phenomena"], r["significance"]) for r in vt)
    out += ["", "By product: " + ", ".join(f"{p}.{s} {n}" for (p, s), n in ph.most_common()) + ".", ""]
    out += NOTES
    (D / "coverage.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
