import importlib.util
import json
from pathlib import Path

import pytest

from gridsim_core import forecast
from gridsim_core.task import load_pack

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("hub_dataset", ROOT / "scripts/hub_dataset.py")
hub = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hub)


def test_paraphrase_keeps_the_template_and_drops_the_quoted_clause():
    assert hub.paraphrase("ERCOT issued a Watch (projected reserve capacity shortage with no market solution "
                          "available for Wednesday, September 06, 2023...).") == \
        "ERCOT issued a Watch (a projected shortage of reserves)."
    assert hub.paraphrase("ERCOT cancelled its OCN (North to Houston interface).") == \
        "ERCOT cancelled its OCN (transmission conditions)."
    assert hub.paraphrase("ERCOT asked the public to conserve electricity from 3:00 p.m. to 9 p.m.") == \
        "ERCOT appealed for conservation from 15:00 to 21:00."
    assert hub.paraphrase("ERCOT declared Energy Emergency Alert level 2.") == \
        "ERCOT declared Energy Emergency Alert level 2."


@pytest.mark.parametrize("pv, pack", [(hub.V2, "gridsim-live-showcase"), (hub.V3, "ercot-hybrid-v3-showcase")])
def test_published_rows_quote_no_notice_text_and_keep_their_references(pv, pack):
    tasks = load_pack(pack)
    scrub = hub.Scrubber(tasks)
    rows = [hub.published(pv, t, scrub) for t in tasks]
    files = {f"raw/packs/{pack}.jsonl": "\n".join(json.dumps(r) for r in rows).encode()}
    assert hub.check_text(files, list(files)) > 0
    for t, r in zip(tasks, rows, strict=True):
        assert {k: v for k, v in r["refs"].items() if k != pv.sha} == \
            {k: v for k, v in t["refs"].items() if k != pv.sha}
        assert pv.core.Session(r, pv.tiers[0]).situation()


@pytest.mark.parametrize("pv, pack", [(hub.V4, "ercot-front-v4-showcase"), (hub.V5, "gridsim-market-showcase")])
def test_v4_and_v5_rows_quote_no_notice_text_and_keep_their_references(pv, pack):
    tasks = load_pack(pack)
    scrub = hub.Scrubber(tasks)
    rows = [hub.published45(pv, t, scrub) for t in tasks]
    assert rows != tasks
    files = {f"raw/packs/{pack}.jsonl": "\n".join(json.dumps(r) for r in rows).encode()}
    assert hub.check_text(files, list(files)) > 0
    for t, r in zip(tasks, rows, strict=True):
        assert {k: v for k, v in r["refs"].items() if k != "events_sha"} == \
            {k: v for k, v in t["refs"].items() if k != "events_sha"}
        if pv is hub.V4:
            assert all(forecast.stored_refs(r, tier) for tier in forecast.TIERS)
        else:
            hub.anonymous(r, pack)


def test_market_days_and_seats_carry_no_resource_or_qse_name():
    day = {"date": "2024-08-20", "parser": "966-v1", "pool": {"esr": [{"id": "e1", "size_mw": 10.0}]}}
    hub.anonymous_day(day, "x")
    for bad in ({**day, "qse": "QXYZ"}, {**day, "pool": {"esr": [{"id": "ALPHA_ESS1"}]}}):
        with pytest.raises(SystemExit):
            hub.anonymous_day(bad, "x")
    task = load_pack("gridsim-market-showcase")[0]
    hub.anonymous(task, "x")
    task["seats"]["B"]["name"] = "ALPHA_ESS1"
    with pytest.raises(SystemExit):
        hub.anonymous(task, "x")


@pytest.mark.parametrize("pv, run", [
    (hub.V2, "v2-pilot-sol-hero/live-v2-2023-09-06-HB_NORTH-2h-l-openai-gpt-6.1-sol-r1.json"),
    (hub.V3, "hybrid-reference/hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150-reserves-anchor.json"),
    (hub.V4, "forecast-view/front-v4-2026-01-24-HB_NORTH-pv150-b100x2h-poi150-anchor.json"),
    (hub.V5, "market-reference/mkt-v5-2026-01-25-A800x2-e1-floor-day-hedged.json")])
def test_an_episode_replays_on_the_plugin_row_and_paraphrased_on_the_published_row(pv, run):
    e = json.loads((ROOT / "results/runs" / run).read_text())
    tasks = {t["task_id"]: t for t in load_pack(pv.packs["showcase"])}
    scrub = hub.Scrubber(list(tasks.values()))
    task = tasks[e["task_id"]]
    publish = hub.published if pv.version in ("v2", "v3") else hub.published45
    assert hub.replay(pv, e, task)["reward"] == pytest.approx(e["reward"], abs=1e-6)
    pub = scrub(e)
    assert pub != e
    assert hub.replay(pv, pub, publish(pv, task, scrub))["reward"] == pytest.approx(e["reward"], abs=1e-6)
    e["steps"][-1]["output"] = {"tampered": True}
    with pytest.raises(hub.Mismatch):
        hub.replay(pv, e, task)


def test_check_text_refuses_notice_text_buckets_and_ticket_ids():
    notice = "ERCOT is issuing an OCN for the extreme hot weather with forecasted temperatures to be above 103°F"
    for text in (notice, "s3://a-bucket/key", "see FD-12"):
        with pytest.raises(SystemExit):
            hub.check_text({"x.json": json.dumps({"t": text}).encode()}, ["x.json"])
    assert hub.unticket(b"lane N, FD-43) and FD-42's range") == b"lane N) and the design plan's range"


@pytest.mark.parametrize("version, board", [("v1", hub.board_markdown), ("v3", hub.board_v3_markdown),
                                            ("v3b", hub.board_v3_markdown), ("v3c", hub.board_v3_markdown),
                                            ("v4", hub.board_v4_markdown),
                                            ("v4b", hub.board_v4_markdown), ("v5", hub.board_v5_markdown),
                                            ("v5b", hub.board_v5_markdown)])
def test_the_card_boards_lead_with_hindsight_capture_and_put_r_second(version, board):
    c = json.loads((ROOT / f"results/eval-{version}.json").read_text())
    text = board(c)
    assert "| C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor |" in text
    assert all(f"**{hub.mci(m['capture'])}**" in text and hub.mci(m["delta"], "+.3f") in text for m in c["models"])


def test_the_registered_4b_run_is_the_only_pre_registered_arm_and_reports_its_sampled_final():
    _, arms = hub.training(ROOT / "results/train")
    four = next(a for a in arms if a["arm"] == "4b")
    assert [a["arm"] for a in arms if a["pre_registered"]] == ["4b"] and four["model"] == "Qwen/Qwen3-4B"
    assert four["final"]["checkpoint_step"] == four["registered_bars"]["sampled"]["checkpoint_step"]
    assert four["final"]["reward_mean"] == four["registered_bars"]["sampled"]["reward_mean"]
    assert four["base"]["reward_mean"] < 0.1 and not four["registered_bars"]["sampled"]["primary_met"]
    assert "| Qwen3-4B, registered run | **yes** |" in hub.training_markdown(arms)
