"""Reference v3 hybrid days for the viewer, played through gridsim_core.hybrid.Session: the rolling anchor, AS-hog, the
solar sponge and v2's energy-only rolling plan on showcase and eval days, as gridsim.episode/v3 JSON, each replayed
call by call before it is written.

usage: python scripts/hybrid_reference_episodes.py [--out results/runs/hybrid-reference] [--tasks ID ...]
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gridsim_core import hybrid as H  # noqa: E402
from gridsim_core.task import load_pack  # noqa: E402

PACKS = ("ercot-hybrid-v3-showcase", "ercot-hybrid-v3-eval")
ALL = ("anchor", "as_hog", "sponge", "v2_energy")
TASKS = {
    "hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150": ("reserves", ALL),
    "hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150": ("reserves", ALL),
    "hyb-v3-2026-01-26-HB_NORTH-pv150-b100x2h-poi150": ("reserves", ("anchor", "as_hog", "v2_energy")),
    "hyb-v3-2023-09-06-HB_WEST-pv150-b100x2h-poi150": ("energy", ("anchor", "sponge")),
    "hyb-v3-2025-11-07-HB_NORTH-pv300-r80-2h-poi300": ("reserves", ("anchor", "as_hog")),
    "hyb-v3-2025-04-18-HB_PAN-pv300-r80-2h-poi300": ("reserves", ("anchor", "sponge")),
    "hyb-v3-2025-03-05-LZ_NORTH-pv100-r80-2h-poi100": ("reserves", ("anchor", "as_hog")),
    "hyb-v3-2025-05-13-HB_PAN-pv100-r40-1h-poi100": ("reserves", ("anchor", "v2_energy")),
    "hyb-v3-2025-03-02-LZ_CPS-pv150-b100x2h-poi150": ("reserves", ("anchor", "as_hog")),
    "hyb-v3-2025-02-15-LZ_WEST-pv150-b100x2h-poi150": ("reserves", ("anchor", "sponge")),
}
MODELS = {"anchor": "reference/rolling-anchor", "as_hog": "reference/as-hog", "sponge": "reference/solar-sponge",
          "v2_energy": "reference/v2-energy-only"}
POLICIES = {"anchor": H.anchor_policy(), "as_hog": H.as_hog_policy, "sponge": H.sponge_policy,
            "v2_energy": H.anchor_policy(energy_only=True, pv_blind=True)}
SAY = {
    "anchor": "The rolling anchor: at every watch one exact solve (HiGHS) over the open hours, energy and every "
              "reserve product together, on DA prices and DA clearing prices with the expected regulation drift and "
              "the deployments known so far. It never sees a real-time price before the hour ends.",
    "as_hog": "AS-hog: the battery holds no energy position and sells the most RegUp and RegDn its charge and the "
              "meter can back every hour, committed once at 2 pm the day before.",
    "sponge": "The solar sponge: charge only from PV the meter cannot export, discharge it in the dearest day-ahead "
              "hours, no reserves, never re-planned.",
    "v2_energy": "v2's energy-only rolling plan: re-planned at every watch like the anchor, but blind to the solar "
                 "farm, the meter and reserves; the governor clips it at the meter.",
}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", type=Path, default=ROOT / "results" / "runs" / "hybrid-reference")
    p.add_argument("--tasks", nargs="*")
    args = p.parse_args(argv)
    rows = {r["task_id"]: r for pack in PACKS for r in load_pack(pack)}
    args.out.mkdir(parents=True, exist_ok=True)
    bad = 0
    for tid in args.tasks or TASKS:
        task = rows[tid]
        tier, kinds = TASKS.get(tid, ("reserves", ALL))
        for kind in kinds:
            s = H.play(task, tier, POLICIES[kind], reference=False)
            ep = s.episode(bundle="reference", path="ref", model=MODELS[kind],
                           messages=[{"role": "assistant", "content": SAY[kind]}])
            check = H.replay(task, tier, s.notices_in, s.deployments_in, s.transcript)
            if not check["ok"] or not ep["audit"]["ok"]:
                print(f"{tid} {kind}: replay {check['problems'][:2]} audit {ep['audit']['problems'][:2]}")
                bad += 1
                continue
            out = args.out / f"{tid}-{tier}-{kind}.json"
            out.write_text(json.dumps(ep, ensure_ascii=False, separators=(",", ":")))
            g = s.grade()
            print(f"{out.name}: profit {ep['profit_usd']:,.0f} reward {ep['reward']:.3f} AS share "
                  f"{g['as_share'] if g['as_share'] is None else round(g['as_share'], 3)} governor "
                  f"{g['governor_hours']} ftp {g['ftp_mwh_charged']:.1f}/{g['ftp_mwh_excused']:.1f} MWh "
                  f"watches {len(ep['watches'])} {out.stat().st_size / 1e3:.0f} kB")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
