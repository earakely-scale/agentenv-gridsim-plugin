import importlib.util
import json
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("pv, run", [
    (hub.V2, "v2-pilot-sol-hero/live-v2-2023-09-06-HB_NORTH-2h-l-openai-gpt-6.1-sol-r1.json"),
    (hub.V3, "hybrid-reference/hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150-reserves-anchor.json")])
def test_an_episode_replays_on_the_plugin_row_and_paraphrased_on_the_published_row(pv, run):
    e = json.loads((ROOT / "results/runs" / run).read_text())
    tasks = {t["task_id"]: t for t in load_pack(pv.packs["showcase"])}
    scrub = hub.Scrubber(list(tasks.values()))
    task = tasks[e["task_id"]]
    assert hub.replay(pv, e, task)["reward"] == pytest.approx(e["reward"], abs=1e-6)
    pub = scrub(e)
    assert pub != e
    assert hub.replay(pv, pub, hub.published(pv, task, scrub))["reward"] == pytest.approx(e["reward"], abs=1e-6)
    e["steps"][-1]["output"] = {"tampered": True}
    with pytest.raises(hub.Mismatch):
        hub.replay(pv, e, task)


def test_check_text_refuses_notice_text_buckets_and_ticket_ids():
    notice = "ERCOT is issuing an OCN for the extreme hot weather with forecasted temperatures to be above 103°F"
    for text in (notice, "s3://a-bucket/key", "see FD-1234"):
        with pytest.raises(SystemExit):
            hub.check_text({"x.json": json.dumps({"t": text}).encode()}, ["x.json"])
    assert hub.unticket(b"lane N, FD-4325) and FD-4322's range") == b"lane N) and the design plan's range"
