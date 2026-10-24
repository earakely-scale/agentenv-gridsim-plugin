"""Reference v5 Market Floor days for the viewer, played through gridsim_core.market.Session: the disclosure anchor
(and the same anchor hedging with a CfD), A's real offers of the day, idle, the price-taker and max-withhold, as
gridsim.episode/v5 JSON, each replayed call by call before it is written.

usage: python scripts/market_reference_episodes.py [--out results/runs/market-reference] [--pack fixtures-market]
       [--tasks ID ...]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import market as M  # noqa: E402
from gridsim_core.market_auction import battery_of, penalty_price  # noqa: E402
from gridsim_core.market_refs import ACTS, battery_dp, replay_a  # noqa: E402
from gridsim_core.market_stack import Floor  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

KINDS = ("anchor", "hedged", "replay_a", "idle", "price_taker", "max_withhold")
SHOWCASE = {"mkt-v5-2024-08-20-A580x2-e1", "mkt-v5-2026-07-21-A1160x2-e1"}
SPRINT = {"mkt-v5-2024-08-20-A580x2-e1", "mkt-v5-2026-07-21-A400x2-e2"}
MODELS = {"anchor": "reference/disclosure-anchor", "hedged": "reference/anchor-hedged",
          "replay_a": "reference/replay-a", "idle": "reference/idle", "price_taker": "reference/price-taker",
          "max_withhold": "reference/max-withhold"}
SAY = {
    "anchor": "The disclosure anchor: at 9 am the day before it reads the latest 60-day disclosure (the aggregate "
              "offer and bid curves of D-61 and D-62), shifts them by the as-issued load, wind and solar forecasts, "
              "best-responds to its own price impact and self-schedules the quantities. On the operating day it "
              "re-plans the open hours on the awards' prices and a decaying real-time basis.",
    "hedged": "The disclosure anchor at the desk: it reads the board at 6 am, checks its offer once at 9 am, submits "
              "the anchor's self-schedule and sells retail-L a contract for difference on its discharge hours at its "
              "own forecast of the hub price. The CfD settles in its own row and never in R.",
    "replay_a": "Seat A's real offers of the day from the disclosure (the group of batteries it was carved from), "
                "snapped to its grid; on the operating day it delivers what it was awarded.",
    "idle": "Idle: a valid offer with no blocks. It is awarded nothing and earns nothing (R 0.2).",
    "price_taker": "The price-taker: the exact battery schedule on the anchor's forecast hub prices as if its own "
                   "quantity moved nothing, self-scheduled; on the operating day it delivers its awards.",
    "max_withhold": "Max-withhold: every MW offered at the $5,000 cap and every MW bid at the -$250 floor. Where that "
                    "conduct would move the price the market monitor re-prices the blocks at the seat's reference.",
}


def offer_of(F: Floor, blocks: list[list], p_mw: float) -> dict:
    """Blocks as an offer, each side cut at the seat's power (a carved pool's curve can exceed it)."""
    def side(bs, sign):
        out, room = [], p_mw
        for _, sd, mw, p, _ in bs:
            if sd == sign and room > 1e-9:
                out.append([min(mw, room), p])
                room -= out[-1][0]
        return out
    return {"hours": [{"he": h + 1, "sell": side(bs, 1), "buy": side(bs, -1)} for h, bs in enumerate(blocks) if bs]}


def schedule_offer(F: Floor, q) -> dict:
    return {"hours": [{"he": h + 1, "sell": [[round(x, 6), F.floor]] if x > 0 else [],
                       "buy": [[round(-x, 6), F.cap]] if x < 0 else []} for h, x in enumerate(q) if abs(x) > 1e-9]}


def price_taker_q(s: M.Session) -> list[float]:
    b = battery_of(s.task["seats"]["A"])
    fc = s.references()["forecast"]["forecast_hub_usd"]
    flat = np.repeat(np.asarray(fc, float)[:, None], len(ACTS), 1)
    _, ks, _ = battery_dp(b, flat, None, penalty_price(s.F.hub_real), feasible_only=True)
    return [k * b.grid for k in ks]


def at_nine(make):
    def policy(s: M.Session):
        return [("submit_offer", {"offer": make(s)})] if s.minute == -900 else []
    return policy


def hedged(s: M.Session):
    if s.minute == -1080:
        latest = s.situation()["public"]["disclosure_latest"]
        return [("get_situation", {}), ("get_forecast", {"kind": "load"}),
                ("get_disclosure", {"op_date": latest, "side": "supply", "hour": 20})]
    if s.minute != -900:
        return M.anchor_policy(s)
    sub = M.anchor_policy(s)
    offer = sub[0][1]["offer"]
    q = s.references()["floor-sprint"]["anchor"]["q_mw"]
    hours = [h + 1 for h, x in enumerate(q) if x > 0]
    calls = [("check_offer", {"offer": offer}), *sub]
    if hours:
        fair = float(np.mean([s.fc["forecast_hub_usd"][h - 1] for h in hours]))
        cap = M.CONTRACT_SHARE * min(s.task["seats"]["L"]["forecast_mw"][h - 1] for h in hours)
        mw = round(min(min(q[h - 1] for h in hours), cap) * 0.5 / s.b.grid) * s.b.grid
        if mw > 0:
            calls.append(("propose_contract", {"counterparty": s.task["seats"]["L"]["name"], "kind": "cfd",
                                               "hours": hours, "mw": mw, "strike_usd": round(fair, 2),
                                               "op_dates": [s.date]}))
    return calls


POLICIES = {
    "anchor": M.anchor_policy, "hedged": hedged,
    "replay_a": at_nine(lambda s: offer_of(s.F, replay_a(s.F), s.b.p)),
    "idle": at_nine(lambda s: {"hours": []}),
    "price_taker": at_nine(lambda s: schedule_offer(s.F, price_taker_q(s))),
    "max_withhold": at_nine(lambda s: {"hours": [{"he": h + 1, "sell": [[s.b.p, s.F.cap]], "buy": [[s.b.p, s.F.floor]]}
                                                 for h in range(24)]}),
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "market-reference")
    p.add_argument("--pack", default="fixtures-market")
    p.add_argument("--tasks", nargs="*")
    args = p.parse_args(argv)
    rows = {r["task_id"]: r for r in load_pack(args.pack)}
    args.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for tid in args.tasks or rows:
        task = rows[tid]
        plays = [("floor-day", k) for k in KINDS if k != "hedged" or tid in SHOWCASE]
        plays += [("floor-sprint", "anchor")] if tid in SPRINT else []
        for tier, kind in plays:
            s = M.play(task, tier, POLICIES[kind])
            ep = s.episode(bundle="reference", path="ref", model=MODELS[kind],
                           messages=[{"role": "assistant", "content": SAY[kind]}])
            check = M.replay(task, tier, s.notices_in, s.transcript)
            if not check["ok"] or not ep["audit"]["ok"]:
                print(f"{tid} {tier} {kind}: replay {check['problems'][:2]} audit {ep['audit']['problems'][:2]}")
                bad += 1
                continue
            out = args.out / f"{tid}-{tier}-{kind}.json"
            out.write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
            print(f"{out.name}: profit {ep['profit_usd']:,.0f} R {ep['reward']:.3f} compliant {ep['compliant_reward']} "
                  f"mitigated {len(ep['clear']['mitigated'])} contracts {len(ep['contracts'] or [])} "
                  f"{out.stat().st_size / 1e3:.0f} kB")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
