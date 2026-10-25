# GridSimEnv v3 re-pilot under rules 3.2: pre-registration (GPT-6.1 Sol, hybrid reserves)

Committed on `v3-pilot-c` before the first Sol episode, the smoke included. Nothing below changes after a run starts,
and nothing is rerun to improve a score. Anything done differently is logged under "Deviations", appended after the
run, with this text left as it is. The 3.0 pilot (`docs/prereg/v3-pilot.md`, "P3") and the 3.1 re-pilot
(`docs/prereg/v3-pilot-b.md`, "P3b"; `results/board-v3b.md`) stay on record as earlier pilots under their own rules;
this run gives Edgar v3 numbers under rules 3.2 and the viewer 3.2 replays. It is not the v3 board.

## Code: rules 3.2
- Branch `v3-pilot-c` at this commit: origin/lane-y3 f3bb2c1 plus this file, `docs/prereg/v3-pilot-c-tasks.json`,
  `scripts/pilot_v3c_tasks.py` and `scripts/pilot_v3c.py`. Rules 3.2 against 3.1 (`docs/CONTRACT-v3.md`): every
  shortfall is charged as it happens, nothing is excused, up awards beyond power headroom are short pro rata and the DA
  position is the projection's executed export at watch 0's end (C3-D19, reversing C3-D7); hindsight is the
  clairvoyant optimum of that settlement, so no stored reference exceeds P_hind (C3-D20); the rules card states that
  deployed energy settles at RT (V3-D15); a malformed planning call (a parse refusal or an argument error) uses no
  planning call up to three a watch and its error names the shape it needs (V3-D16); the agent's cost guard books a
  request as it will be priced (V3-D17; 1.03x the priced cost on P3b's replayed runs, was 1.26x); the energy tier is a
  secondary board column (V3-D18). Packs refilled under 3.2: eval 300, 48 replaced, every day passing every filter.
- Env `gridsim-hybrid` and agent `gridsim-llm` as in P3b. One EC2 box (c7i.4xlarge, Ubuntu 24.04, local Docker), this
  lane alone on it. At f3bb2c1 on the box `agent-env gridsim setup --agent` registered `gridsim-hybrid` and
  `gridsim-llm`, and `scripts/hybrid_e2e.py` (no model spend) passed with the anchor policy on the bundle's day
  2023-08-24 LZ_LCRA (reserves: R 1.0, $2,162,299.89), eval deployment day 2025-05-17 HB_WEST (reserves, the Non-Spin
  deployment exercised: R 1.0, $39,835.96), the replacement day 2025-07-23 HB_WEST (reserves, PV/POI 1.11: R 1.0,
  $36,470.85) and eval oversized day 2025-09-08 HB_SOUTH (energy, PV/POI 1.4: R 1.0, $43,127.68), each profit equal
  to the stored P_anchor, no problems. Both run again at this commit before the first episode.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  hybrid rules card, 52 turns, 16,384 output tokens a turn, 7,200 s wall limit, 3 planning calls a watch, 1 h freeze.
- One run per task. The sweep retries an infrastructure failure (unscored, retryable) at most twice; every attempt is
  kept.

## Budget, smoke and caps
- **Smoke (counts toward the budget, never toward a result):** P3b's three era-B `ercot-hybrid-v3-train` days with
  measured drift, all still in the refilled pack: `hyb-v3-2024-11-09-LZ_NORTH-pv200-r40-2h-poi200` (deployment day)
  and `hyb-v3-2023-11-04-LZ_SOUTH-pv300-r80-1h-poi300` at the reserves tier (sweep `v3c-smoke`, `--cap-usd 2.5`,
  parallel 2), `hyb-v3-2024-03-16-HB_WEST-pv200-r40-1h-poi160` (PV/POI 1.25) at the energy tier
  (`v3c-smoke-energy`, `--cap-usd 1.25`), each at a $1.00 episode cap.
- From the smoke: s = its spend, m = the median of its three runs' priced cost. The episode cap is
  **E = max($0.40, 4m rounded up to the cent)**. **Stop** (no main sweep, report instead) if a smoke run ends at its
  cap or unscored for a reason other than infrastructure, or if the projection s + 32m + 5m (30 reserves days and 2
  display days at m, 10 energy days at m/2) exceeds $15.
- **Total cap $15**, every sweep included. The first sweeps' `--cap-usd`, with B = $15 − s: reserves floor(0.60 B),
  energy floor(0.15 B), display floor(0.25 B), to the cent; they run at the same time, parallel 6, 3 and 2 (the sweep
  starts no attempt that could pass its cap at E).
- **Amendment rule:** each run that ends unscored, in any column, is run once more at a 2E cap in a sweep named after
  its own with `-amend` (`v3c-pilot-sol-amend`, ...), `--cap-usd` = $15 minus the spend so far, and reported as a
  labelled amendment; the primary numbers are the first sweeps alone.

## Tasks (`docs/prereg/v3-pilot-c-tasks.json`, `scripts/pilot_v3c_tasks.py`)
The 3.1 pilot's days that survive the refill, topped up by the 3.1 pilot's own rule and seeds (`pilot_v3b_tasks.draw`,
4325 for reserves, 4326 for energy) over the refilled `ercot-hybrid-v3-eval`.
- **Reserves column (scored, primary):** 30 days at the reserves tier (2025-01..11, era B, all with ERCOT-measured
  drift). The 24 surviving 3.1 days (#1-24; 2025-03-02 LZ_CPS, 2025-06-30 HB_WEST, 2025-07-14 HB_HOUSTON, 2025-07-30
  LZ_LCRA, 2025-08-18 LZ_RAYBN and 2025-11-28 HB_WEST failed a 3.2 filter and left the pack), then every deployment day
  not among them (none: the refilled pack has 12, all survivors), then 6 non-deployment days round-robin over the AS
  strata until each holds 10 (3 low, 1 mid, 2 high: #25-30), each pick on a date neither column uses whose settlement
  point and month its stratum has drawn least, then the column's least-drawn point and month. 30 days on 26 dates, 12
  deployment days, all 13 points, all 11 months, 13 notice days, none with negative-price hours; PV/POI 0.83 (10),
  1.00 (10), 1.11 (1), 1.25 (8), 1.4 (1).
- **Energy column (scored, secondary per V3-D18, reported apart, never pooled):** 10 days at the energy tier on
  oversized sites with PV/POI >= 1.25, 5 at 1.25 and 5 at 1.4, on dates the reserves column does not use: the 8
  surviving 3.1 days (#31-38; 2025-07-12 LZ_LCRA and 2025-04-09 LZ_RAYBN left the pack) and one replacement per class
  by the same rule (#39-40). 10 points, 10 months, 4 notice days, 2 with negative-price hours, 2 with no clippable
  solar.
- **Display only, never counted:** `ercot-hybrid-v3-showcase` at the reserves tier, P3b's two days: the hero
  aug10-2023 (`hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150`, 7 watches, Non-Spin and ECRS deployments, fallback
  drift) and mar29-2024 (`hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150`, 16 negative DA hours), one sweep.
- **Known before any run** (stored rules-3.2 references; R on the anchor scale, C = (P − P_idle)/(P_hind − P_idle)):
  - Reserves column: anchor's C 0.449 (deployment days 0.355, other days 0.512; low/mid/high 0.514/0.433/0.400). R
    (C): AS-hog 0.293 (0.043), solar sponge 0.269 (0.043), v2 energy-only 0.755 (0.320), energy-only MILP 0.804
    (0.350); no baseline at R = 1 on any day. The energy-only MILP and v2 energy-only differ on 11 days (7 with
    clippable solar) and coincide on 19. AS-hog scores 0 on 7 days. The anchor commits 2.4 times a day, the governor
    moves 4.5 of its hours, it pays $180 a day of FTP ($292 on deployment days; under 3.1 $18 and $41, the excused
    part now charged) and earns $6,315 a day of AS; P_anchor − P_idle has a median of $9,556.
  - Energy column: anchor's C 0.434 (PV/POI 1.25: 0.324, 1.4: 0.543); v2 energy-only R 0.842 (C 0.317; R = 1 on 3 of
    10), solar sponge R 0.442 (C 0.142); 176 clippable MWh a day (83 at 1.25, 268 at 1.4).
  - Display: aug10-2023 anchor's C 0.262 (P_anchor $1,554,645, P_hind $3,228,428; 3.1: 0.282), AS-hog R 0.366, v2
    energy-only 0.603, energy-only MILP 0.753; mar29-2024 anchor's C 0.515 (P_anchor $6,591, P_hind $12,239; 3.1:
    0.856), AS-hog R 0.339, v2 energy-only and energy-only MILP 0.823.
  - The 3.1 pilot on the common days (`results/pilot-v3b.json`, its amended set: 2025-02-17 LZ_HOUSTON is its
    amendment's run). Reserves, 24 days: under 3.1 Sol's C 0.432 against the anchor's 0.500, Δ −0.068, R 0.820. The
    same plays (each episode's calls) settled on the 3.2 Session by `scripts/pilot_v3c.py` read C 0.391 against the
    3.2 anchor's 0.449, Δ −0.058, R 0.819 (6 days at R = 1); every commit and check is accepted or refused as recorded.
    RegUp: 3.1 Sol booked 1 MW-h a day against the 3.2 anchor's 356 (RegDn 567 against 606). Format: one day
    (2025-09-25 HB_SOUTH) without an accepted watch-0 commit; 6 planning calls refused as `parse`, which 3.2 would not
    have charged a call. Energy, 8 days: C 0.426 against the anchor's 0.431, Δ −0.005, R 0.987, unchanged by the
    settlement (the energy tier has no AS).

```
python scripts/pilot_v3c_tasks.py main --json docs/prereg/v3-pilot-c-tasks.json
S="agent-env gridsim sweep run --env gridsim-hybrid --models openai/gpt-6.1-sol"
$S --name v3c-smoke --pack ercot-hybrid-v3-train --tier reserves \
  --tasks "$(python scripts/pilot_v3c_tasks.py smoke-reserves)" --cap-usd 2.5 --episode-cap-usd 1.00 --parallel 2
$S --name v3c-smoke-energy --pack ercot-hybrid-v3-train --tier energy \
  --tasks "$(python scripts/pilot_v3c_tasks.py smoke-energy)" --cap-usd 1.25 --episode-cap-usd 1.00 --parallel 1
$S --name v3c-pilot-sol --pack ercot-hybrid-v3-eval --tier reserves \
  --tasks "$(python scripts/pilot_v3c_tasks.py main)" --cap-usd <0.60 B> --episode-cap-usd <E> --parallel 6
$S --name v3c-pilot-sol-energy --pack ercot-hybrid-v3-eval --tier energy \
  --tasks "$(python scripts/pilot_v3c_tasks.py energy)" --cap-usd <0.15 B> --episode-cap-usd <E> --parallel 3
$S --name v3c-pilot-sol-show --pack ercot-hybrid-v3-showcase --tier reserves \
  --tasks "$(python scripts/pilot_v3c_tasks.py showcase)" --cap-usd <0.25 B> --episode-cap-usd <E> --parallel 2
agent-env gridsim episodes v3c-smoke v3c-smoke-energy v3c-pilot-sol v3c-pilot-sol-energy v3c-pilot-sol-show
agent-env gridsim sweep report v3c-pilot-sol v3c-pilot-sol-energy --card results/eval-v3c.json \
  --board results/board-v3c.md
python scripts/pilot_v3c.py v3c-pilot-sol --energy v3c-pilot-sol-energy --showcase v3c-pilot-sol-show \
  --extra-spend v3c-smoke v3c-smoke-energy --json results/pilot-v3c.json
```

Reserves column:

| # | Task | In 3.1 | Stratum | Deployment day | PV/POI | Watches | Notice day | Anchor − idle ($) | Anchor's C | AS-hog R (C) | Solar sponge R | v2 energy-only R (C) | Energy-only MILP R (C) |
|---:|---|---|---|---|---:|---:|---|---:|---:|---|---:|---|---|
| 1 | `hyb-v3-2025-03-05-HB_HOUSTON-pv150-b100x2h-poi180` | yes | high | yes | 0.83 | 7 | yes | 12,060 | 0.369 | 0.000 (-0.092) | 0.200 | 0.854 (0.302) | 0.854 (0.302) |
| 2 | `hyb-v3-2025-03-05-LZ_NORTH-pv100-r80-2h-poi80` | yes | mid | yes | 1.25 | 7 | yes | 11,796 | 0.537 | 0.000 (-0.141) | 0.536 | 0.786 (0.393) | 0.895 (0.466) |
| 3 | `hyb-v3-2025-03-10-LZ_CPS-pv100-r40-1h-poi120` | yes | mid | yes | 0.83 | 6 | yes | 6,004 | 0.391 | 0.607 (0.199) | 0.200 | 0.750 (0.269) | 0.750 (0.269) |
| 4 | `hyb-v3-2025-03-10-LZ_NORTH-pv150-b100x2h-poi150` | yes | high | yes | 1.00 | 6 | yes | 16,798 | 0.427 | 0.397 (0.105) | 0.200 | 0.830 (0.336) | 0.830 (0.336) |
| 5 | `hyb-v3-2025-04-07-HB_SOUTH-pv300-r80-1h-poi240` | yes | high | yes | 1.25 | 6 | no | 68,284 | 0.108 | 0.000 (-0.047) | 0.327 | 0.468 (0.036) | 0.505 (0.041) |
| 6 | `hyb-v3-2025-05-16-LZ_WEST-pv100-r67-1h-poi120` | yes | high | yes | 0.83 | 6 | yes | 57,054 | 0.186 | 0.080 (-0.028) | 0.200 | 0.383 (0.042) | 0.383 (0.042) |
| 7 | `hyb-v3-2025-05-17-HB_WEST-pv150-b100x2h-poi180` | yes | high | yes | 0.83 | 6 | yes | 9,516 | 0.292 | 0.000 (-0.174) | 0.200 | 0.642 (0.161) | 0.642 (0.161) |
| 8 | `hyb-v3-2025-05-17-LZ_WEST-pv200-r40-2h-poi200` | yes | mid | yes | 1.00 | 6 | yes | 8,522 | 0.294 | 0.000 (-0.242) | 0.200 | 0.797 (0.220) | 0.797 (0.220) |
| 9 | `hyb-v3-2025-09-04-HB_PAN-pv100-r67-2h-poi100` | yes | low | yes | 1.00 | 6 | no | 7,544 | 0.547 | 0.507 (0.210) | 0.200 | 0.763 (0.385) | 0.884 (0.468) |
| 10 | `hyb-v3-2025-10-21-HB_HOUSTON-pv200-r40-1h-poi240` | yes | mid | yes | 0.83 | 5 | no | 9,964 | 0.307 | 0.511 (0.119) | 0.200 | 0.759 (0.214) | 0.759 (0.214) |
| 11 | `hyb-v3-2025-10-21-LZ_SOUTH-pv300-r80-2h-poi300` | yes | high | yes | 1.00 | 5 | no | 51,575 | 0.238 | 0.753 (0.164) | 0.200 | 0.702 (0.149) | 0.934 (0.218) |
| 12 | `hyb-v3-2025-11-07-LZ_AEN-pv150-r67-1h-poi150` | yes | high | yes | 1.00 | 6 | no | 28,108 | 0.566 | 0.339 (0.098) | 0.200 | 0.717 (0.366) | 0.908 (0.501) |
| 13 | `hyb-v3-2025-08-09-LZ_RAYBN-pv150-b100x2h-poi120` | yes | low | no | 1.25 | 5 | yes | 8,083 | 0.688 | 0.410 (0.180) | 0.610 | 0.664 (0.399) | 0.964 (0.658) |
| 14 | `hyb-v3-2025-02-08-LZ_LCRA-pv300-r40-2h-poi300` | yes | mid | no | 1.00 | 5 | no | 9,822 | 0.622 | 0.722 (0.405) | 0.200 | 0.803 (0.468) | 0.803 (0.468) |
| 15 | `hyb-v3-2025-06-12-LZ_HOUSTON-pv300-r40-1h-poi240` | yes | high | no | 1.25 | 5 | no | 5,669 | 0.574 | 0.312 (0.080) | 0.200 | 0.683 (0.347) | 0.683 (0.347) |
| 16 | `hyb-v3-2025-01-08-HB_NORTH-pv100-r80-1h-poi80` | yes | low | no | 1.25 | 6 | yes | 4,769 | 0.587 | 0.213 (0.010) | 0.200 | 0.922 (0.529) | 0.922 (0.529) |
| 17 | `hyb-v3-2025-07-25-LZ_AEN-pv150-b100x2h-poi150` | yes | mid | no | 1.00 | 5 | no | 19,040 | 0.590 | 0.456 (0.189) | 0.200 | 0.915 (0.527) | 0.915 (0.527) |
| 18 | `hyb-v3-2025-04-12-HB_SOUTH-pv200-r40-2h-poi240` | yes | low | no | 0.83 | 5 | no | 5,309 | 0.609 | 0.100 (-0.076) | 0.200 | 0.917 (0.546) | 0.917 (0.546) |
| 19 | `hyb-v3-2025-02-17-LZ_HOUSTON-pv200-r40-1h-poi160` | yes | low | no | 1.25 | 5 | yes | 2,995 | 0.582 | 0.150 (-0.036) | 0.427 | 0.856 (0.477) | 0.863 (0.482) |
| 20 | `hyb-v3-2025-01-24-LZ_SOUTH-pv300-r40-1h-poi360` | yes | mid | no | 0.83 | 5 | no | 8,374 | 0.448 | 0.046 (-0.086) | 0.200 | 0.817 (0.345) | 0.817 (0.345) |
| 21 | `hyb-v3-2025-08-23-HB_PAN-pv150-b100x2h-poi120` | yes | mid | no | 1.25 | 5 | no | 9,887 | 0.305 | 0.838 (0.243) | 0.638 | 0.709 (0.194) | 0.902 (0.268) |
| 22 | `hyb-v3-2025-06-19-LZ_NORTH-pv100-r80-1h-poi120` | yes | low | no | 0.83 | 5 | no | 5,843 | 0.458 | 0.142 (-0.033) | 0.200 | 0.756 (0.318) | 0.756 (0.318) |
| 23 | `hyb-v3-2025-09-25-HB_SOUTH-pv200-r80-1h-poi143` | yes | mid | no | 1.40 | 5 | no | 16,827 | 0.440 | 0.497 (0.164) | 0.372 | 0.533 (0.183) | 0.651 (0.248) |
| 24 | `hyb-v3-2025-10-16-LZ_LCRA-pv150-b100x2h-poi150` | yes | low | no | 1.00 | 5 | no | 9,174 | 0.618 | 0.439 (0.184) | 0.200 | 0.723 (0.404) | 0.806 (0.468) |
| 25 | `hyb-v3-2025-07-23-HB_WEST-pv150-r67-2h-poi135` | no | low | no | 1.11 | 5 | no | 9,597 | 0.578 | 0.359 (0.115) | 0.552 | 0.873 (0.486) | 0.956 (0.546) |
| 26 | `hyb-v3-2025-04-22-HB_NORTH-pv200-r40-1h-poi200` | no | mid | no | 1.00 | 5 | no | 6,379 | 0.396 | 0.050 (-0.074) | 0.200 | 0.739 (0.267) | 0.739 (0.267) |
| 27 | `hyb-v3-2025-01-09-LZ_RAYBN-pv200-r67-2h-poi240` | no | high | no | 0.83 | 5 | yes | 16,659 | 0.683 | 0.402 (0.172) | 0.200 | 0.660 (0.393) | 0.660 (0.393) |
| 28 | `hyb-v3-2025-11-27-LZ_CPS-pv200-r40-1h-poi240` | no | low | no | 0.83 | 5 | no | 2,162 | 0.129 | 0.476 (0.045) | 0.200 | 0.955 (0.122) | 0.955 (0.122) |
| 29 | `hyb-v3-2025-02-22-HB_NORTH-pv300-r80-2h-poi300` | no | high | no | 1.00 | 5 | yes | 38,677 | 0.560 | 0.000 (-0.169) | 0.200 | 0.879 (0.475) | 0.879 (0.475) |
| 30 | `hyb-v3-2025-03-04-LZ_AEN-pv100-r80-1h-poi80` | no | low | no | 1.25 | 7 | yes | 2,937 | 0.343 | 0.000 (-0.200) | 0.200 | 0.786 (0.251) | 0.786 (0.251) |

Energy column:

| # | Task | In 3.1 | PV/POI | Clippable MWh | Watches | Notice day | Anchor − idle ($) | Anchor's C | Solar sponge R (C) | v2 energy-only R (C) |
|---:|---|---|---:|---:|---:|---|---:|---:|---|---|
| 31 | `hyb-v3-2025-06-24-LZ_WEST-pv150-b100x2h-poi120` | yes | 1.25 | 180 | 5 | no | 10,737 | 0.637 | 0.727 (0.419) | 0.872 (0.535) |
| 32 | `hyb-v3-2025-09-08-HB_SOUTH-pv200-r80-2h-poi143` | yes | 1.40 | 415 | 5 | no | 11,974 | 0.876 | 0.200 (0.000) | 0.451 (0.275) |
| 33 | `hyb-v3-2025-10-25-LZ_HOUSTON-pv150-b100x2h-poi120` | yes | 1.25 | 0 | 5 | no | 4,996 | 0.189 | 0.200 (0.000) | 1.000 (0.189) |
| 34 | `hyb-v3-2025-03-19-HB_WEST-pv150-b100x2h-poi107` | yes | 1.40 | 144 | 5 | yes | 9,644 | 0.463 | 0.200 (0.000) | 1.000 (0.463) |
| 35 | `hyb-v3-2025-11-09-HB_PAN-pv300-r80-1h-poi240` | yes | 1.25 | 97 | 6 | yes | 7,646 | 0.286 | 0.200 (0.000) | 1.000 (0.286) |
| 36 | `hyb-v3-2025-01-01-LZ_SOUTH-pv300-r80-1h-poi214` | yes | 1.40 | 178 | 5 | no | 5,558 | 0.167 | 0.722 (0.109) | 0.648 (0.093) |
| 37 | `hyb-v3-2025-02-24-HB_NORTH-pv150-r80-2h-poi120` | yes | 1.25 | 140 | 5 | yes | 11,786 | 0.318 | 0.627 (0.170) | 0.919 (0.285) |
| 38 | `hyb-v3-2025-05-10-LZ_AEN-pv150-b100x2h-poi107` | yes | 1.40 | 275 | 5 | yes | 8,242 | 0.510 | 0.649 (0.286) | 0.929 (0.465) |
| 39 | `hyb-v3-2025-04-26-LZ_CPS-pv150-r80-1h-poi120` | no | 1.25 | 0 | 5 | no | 4,628 | 0.192 | 0.200 (0.000) | 0.941 (0.178) |
| 40 | `hyb-v3-2025-07-21-LZ_LCRA-pv150-b100x2h-poi107` | no | 1.40 | 327 | 5 | no | 11,203 | 0.701 | 0.695 (0.434) | 0.657 (0.400) |

## Metrics
Computed by `scripts/pilot_v3c.py` from the replay-verified Episode JSON v3 (`agent-env gridsim episodes`) and
results.jsonl, per `docs/REWARD-SCALES.md`. CIs are 95% percentile bootstrap over days, 10,000 resamples, seed 0 for
levels and 1 for paired differences (seed 2 for the unpaired deployment gap, 3 for the 3.1 comparison), days in
task-id order. Sets: the reserves column overall, on its 12 deployment days and 18 other days, and by AS stratum; the
energy column overall and by PV/POI class; each display day as one line.
- **Primary: hindsight capture C** = (P − P_idle)/(P_hind − P_idle), unclipped, the mean over the 30 reserves days,
  beside the anchor's C on the same days and **Δ = C − C_anchor** = (P − P_anchor)/(P_hind − P_idle) with its paired
  CI.
- **Secondary:** R on the anchor scale (clip(0.2 + 0.8(P − P_idle)/(P_anchor − P_idle), 0, 1)) with its CI, the share
  of days at R = 1 and the share beating the anchor (R is a level, never differenced); Sol − AS-hog, − v2 energy-only
  and − the energy-only MILP as (P − P_ref)/(P_hind − P_idle) with paired CIs, each reference's C and R and the share
  of days Sol's profit beats it (the solar sponge too); the energy column with the same headline and its references
  (sponge, v2 energy-only).
- As in P3b, on the 3.2 settlement: the regulation table (each day replayed on a fresh Session, the anchor played in
  process, which must reproduce the stored P_anchor to $0.001; RegDn drift energy bought at RT, L_reg and the RegDn
  and RegUp books), the deployment-day table and the Δ gap (deployment days − others, unpaired CI), and
  `scripts/pilot_v3.py`'s AS, reserve and play tables (FTP is each hour's realized shortfall; the tables keep an
  excused column, which reads 0 under 3.2), the end penalty, refusals by rule, audit failures, tokens, $/episode and
  turns; unscored runs and why; spend per sweep, the smoke included.
- **Exploratory, labelled:**
  - **3.1 against 3.2 on the common days** (24 reserves, 8 energy), paired: Sol's C and Δ under 3.1 (P3b, its
    amended set) and under 3.2 (this run), C 3.2 − C 3.1 and Δ 3.2 − Δ 3.1 with CIs; and P3b's plays settled on the
    3.2 Session, so (P_3.2 run − P_3.1 play)/(P_hind − P_idle) compares the two runs under one settlement and one set of
    references. The rules, the card, the cost guard and the packs' references changed between them: this is a reading
    of the rules change and of two samples of one model, not a model comparison.
  - **Format (V3-D16):** malformed planning calls (parse refusals and argument errors), how many used no planning call
    (the replayed Session's `free_refusals`) and how many used one, planning calls that found no calls left
    (in all, and in a watch after a malformed call), plans keeping an AS field by `"keep"` or null and their parse
    refusals, and the days without an accepted watch-0 commit (the book P3b lost on 2025-09-25).
  - **RegUp (the 3.1 gap):** Sol's RegUp award MW-h a day against the anchor's, the days each books any, and on the
    common days 3.1 Sol's beside them.

## Readings registered before the run
- **The anchor gap:** Sol is called below the anchor on reserves if the CI of Δ lies wholly below 0, above it if wholly
  above 0, level at this size otherwise.
- **The reserves tier as the test:** if the CI of Sol − energy-only MILP lies below 0, the reserves tier is called
  harder than energy-only arbitrage for this model; above 0, Sol is called to earn from co-optimising AS; across 0,
  undecided at this size.
- **Deployments:** Sol handles deployment days if its mean Δ on them is no more than 0.05 below its mean Δ on the
  other days (P3b's H2 rule).
- **Energy tier saturation:** saturated for this model if the energy column's mean R is 0.95 or more.
- **Anchor scale:** compressed for this model if more than a third of the reserves days sit at R = 1 (V2-D1's rule).
- **The 3.2 format fix:** holds if every reserves and energy day has an accepted watch-0 commit and no planning call
  found no calls left after a malformed call in the same watch.
- **The RegUp gap:** persists if Sol's RegUp MW-h a day is below a tenth of the anchor's on the reserves column.
- **The 3.1 comparison:** the two runs differ under one settlement if the CI of (P_3.2 run − P_3.1 play)/(P_hind −
  P_idle) excludes 0; otherwise they are called level at this size.
- **Display days:** C, the anchor's C, Δ, R and the baselines, printed and never pooled.

## Deviations
