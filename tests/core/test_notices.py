import datetime as dt
import json
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st

from gridsim_core import notices
from gridsim_core.notices import assign_watches, is_notice_day, notices_for, reveal_at, watch0

CPT = ZoneInfo("America/Chicago")
UTC = dt.UTC


def t(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s)


def test_reveal_at_boundaries():
    assert reveal_at(t("2023-09-06T19:15:00-05:00")) == t("2023-09-06T19:15:00-05:00")
    assert reveal_at(t("2023-09-06T19:15:01-05:00")) == t("2023-09-06T19:30:00-05:00")
    assert reveal_at(t("2023-09-06T19:25:40-05:00")) == t("2023-09-06T19:30:00-05:00")
    assert reveal_at(t("2023-09-06T23:59:30-05:00")) == t("2023-09-07T00:00:00-05:00")


def test_reveal_at_across_dst():
    for issued, want in [
        ("2023-03-12T01:59:30-06:00", "2023-03-12T03:00:00-05:00"),
        ("2023-11-05T01:50:00-05:00", "2023-11-05T01:00:00-06:00"),
        ("2023-11-05T01:50:00-06:00", "2023-11-05T02:00:00-06:00"),
    ]:
        assert reveal_at(t(issued)).astimezone(UTC) == t(want).astimezone(UTC)


@given(st.datetimes(min_value=dt.datetime(2018, 1, 1), max_value=dt.datetime(2027, 1, 1), timezones=st.just(UTC)))
def test_reveal_never_early_and_within_15_min(x):
    r = reveal_at(x)
    assert x <= r < x + dt.timedelta(minutes=15)
    assert r.astimezone(UTC).minute % 15 == 0 and r.second == 0 and r.microsecond == 0


def write(tmp, ercot, vtec=(), days=None):
    (tmp / "notices.jsonl").write_text("".join(json.dumps(r) + "\n" for r in ercot))
    (tmp / "nws_vtec.jsonl").write_text("".join(json.dumps(r) + "\n" for r in vtec))
    (tmp / "ops_coverage.json").write_text(json.dumps({"days": days or {}}))
    return str(tmp)


def row(nid, issued_cpt, typ="EEA2", action="issue", regions=None, quality="minute"):
    ts = t(issued_cpt) if quality == "minute" else None
    return {
        "notice_id": nid,
        "source": "ERCOT",
        "type": typ,
        "level": typ,
        "action": action,
        "grid_condition": True,
        "timestamp_quality": quality,
        "issued_at": issued_cpt,
        "issued_at_utc": ts.astimezone(UTC).isoformat() if ts else None,
        "regions": regions,
        "tags": [],
    }


def test_notices_for_buckets_and_watches(tmp_path):
    root = write(
        tmp_path,
        [
            row("old", "2023-09-01T12:00:00-05:00"),
            row("board", "2023-09-05T09:00:00-05:00", "weather_watch"),
            row("mid", "2023-09-05T16:10:00-05:00", "conservation_appeal"),
            row("eea2", "2023-09-06T19:25:40-05:00"),
            row("eea1", "2023-09-06T20:27:10-05:00", "EEA1"),
            row("west", "2023-09-06T12:00:00-05:00", "Emergency", regions=["west"]),
            row("dated", "2023-09-03", "conservation_appeal", quality="day"),
            row("dated_d1", "2023-09-05", "conservation_appeal", quality="day"),
            row("next", "2023-09-07T00:00:00-05:00"),
        ],
        [
            {
                "notice_id": "v1",
                "source": "NWS",
                "region": "houston",
                "significance": "W",
                "phenomena": "EH",
                "issued_at_utc": "2023-09-06T15:00:00Z",
                "expires_at_utc": "2023-09-07T01:00:00Z",
            }
        ],
    )
    got = {n["notice_id"]: n for n in notices_for("2023-09-06", "HB_HOUSTON", root=root)}
    assert set(got) == {"board", "mid", "eea2", "eea1", "dated", "v1"}
    assert got["board"]["when"] == got["dated"]["when"] == "board"
    assert got["board"]["reveal_at"] == watch0("2023-09-06").isoformat() == "2023-09-05T14:00:00-05:00"
    assert got["mid"]["reveal_at"] == "2023-09-06T00:00:00-05:00"
    assert got["eea2"]["reveal_at"] == "2023-09-06T19:30:00-05:00"
    assert got["v1"]["reveal_at"] == "2023-09-06T10:00:00-05:00"
    assert "west" in {n["notice_id"] for n in notices_for("2023-09-06", "HB_WEST", root=root)}
    ws = [t(f"2023-09-06T{h}:00-05:00") for h in ("00:00", "06:00", "12:00", "18:00", "19:30", "20:30")]
    w = assign_watches(list(got.values()), ws)
    assert w["eea2"] == t("2023-09-06T19:30:00-05:00") and w["eea1"] == t("2023-09-06T20:30:00-05:00")
    assert all(w[k] is None or w[k] >= t(got[k]["reveal_at"]) for k in got if got[k]["when"] == "intraday")
    assert notices_for("2023-09-06", "HB_HOUSTON", root=root) == notices_for("2023-09-06", "HB_HOUSTON", root=root)
    assert is_notice_day("2023-09-06", "HB_HOUSTON", root=root)
    assert not is_notice_day("2023-08-01", "HB_HOUSTON", root=root)


@pytest.mark.skipif(not (notices.data_root() / "notices" / "notices.jsonl").exists(), reason="no notice archive")
def test_sep6_2023_hero_timeline():
    ns = notices_for("2023-09-06", "HB_NORTH")
    ops = [n for n in ns if n.get("channel") == "operations_message" and n["when"] == "intraday"]
    eea2 = [n for n in ops if n["type"] == "EEA2" and n["action"] == "issue"]
    eea1 = [n for n in ops if n["type"] == "EEA1" and n["action"] == "issue"]
    end = [n for n in ops if n["level"] == "EEA_exit"]
    assert eea2 and eea1 and end
    assert t(eea2[0]["event_time"]).strftime("%H:%M") == "19:25" and eea2[0]["reveal_at"].startswith("2023-09-06T19:30")
    assert t(eea1[0]["event_time"]).strftime("%H:%M") == "20:27"
    assert t(end[0]["event_time"]).strftime("%H:%M") == "20:37"
    for n in ns:
        if n["timestamp_quality"] == "minute":
            assert t(n["reveal_at"]) >= t(n["issued_at_utc"].replace("Z", "+00:00"))
