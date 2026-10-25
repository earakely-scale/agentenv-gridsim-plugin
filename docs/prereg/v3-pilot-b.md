# GridSimEnv v3 re-pilot under rules 3.1: pre-registration (GPT-6.1 Sol, hybrid reserves)

Committed on `v3-pilot-b` before the first Sol episode, the smoke included. Nothing below changes after a run starts,
and nothing is rerun to improve a score. Anything done differently is logged under "Deviations", appended after the
run, with this text left as it is. Like `docs/prereg/v3-pilot.md` (the 3.0 pilot, "P3" below), this gives Edgar v3
numbers and the viewer v3 replays; it is not the v3 board.

## Code: rules 3.1
- Branch `v3-pilot-b` at this commit: origin/lane-x3 0c20373 plus this file, `docs/prereg/v3-pilot-b-tasks.json`,
  `scripts/pilot_v3b_tasks.py` and `scripts/pilot_v3b.py`. Rules 3.1 against the 3.0 pilot (`docs/CONTRACT-v3.md`):
  regulation drift is the ERCOT storage fleet's measured deployment from the 60-day SCED disclosure (V3-D8; every
  eval day is measured, the aug10-2023 display day takes the fitted fallback, tagged `modelled`); a running RRS, ECRS
  or Non-Spin deployment uses up its product's duration (C3-D18); 40% of sites have PV AC above the POI (V3-D12, PV/POI
  1.11, 1.25, 1.4); `"keep"` or null keeps an AS field (V3-D13); packs rebuilt (eval 300, all measured, 13 deployment
  days).
- Env `gridsim-hybrid` and agent `gridsim-llm` as in P3 (gateway, triggers with deployment payloads, virtual clock
  frozen at each watch, the token-estimating cost guard, 16,384 output tokens a turn). One EC2 box (c7i.8xlarge,
  Ubuntu 24.04, local Docker), shared with two other lanes, this lane in its own checkout, venv, agent-env state root,
  registry prefix and systemd units. At 0c20373 on the box `agent-env gridsim setup --agent` registered
  `gridsim-hybrid` and `gridsim-llm`, and `scripts/hybrid_e2e.py` (no model spend) passed with the anchor policy on the
  bundle's day 2023-08-24 LZ_LCRA (reserves: R 1.0, $2,201,912.20), eval deployment day 2025-05-17 HB_WEST (reserves,
  the Non-Spin deployment exercised: R 1.0, $39,882.54) and eval oversized day 2025-09-08 HB_SOUTH (energy, PV/POI
  1.4: R 1.0, $43,127.68), each profit equal to the stored P_anchor, no problems. Both run again
  at this commit before the first episode.

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  hybrid rules card, 52 turns, 16,384 output tokens a turn, 7,200 s wall limit, 3 planning calls a watch, 1 h freeze.
- One run per task. The sweep retries an infrastructure failure at most twice (every attempt is kept).

## Budget, smoke and caps
- **Smoke (counts toward the budget, never toward a result):** three era-B `ercot-hybrid-v3-train` days with
  measured drift, picked by `scripts/pilot_v3b_tasks.py` (seed 4327): `hyb-v3-2024-11-09-LZ_NORTH-pv200-r40-2h-poi200`
  (deployment day) and `hyb-v3-2023-11-04-LZ_SOUTH-pv300-r80-1h-poi300` at the reserves tier (sweep `v3b-smoke`,
  `--cap-usd 2.5`, parallel 2), `hyb-v3-2024-03-16-HB_WEST-pv200-r40-1h-poi160` (PV/POI 1.25) at the energy tier
  (`v3b-smoke-energy`, `--cap-usd 1.25`), each at a $1.00 episode cap.
- From the smoke: s = its spend, m = the median of its three runs' priced cost. The episode cap is
  **E = max($0.40, 4m rounded up to the cent)**. **Stop** (no main sweep, report instead) if a smoke run ends at its
  cap or unscored for a reason other than infrastructure, or if the projection s + 32m + 5m (30 reserves days and 2
  display days at m, 10 energy days at m/2, P3's ratio) exceeds $20.
- **Total cap $20**, every sweep included. The first sweeps' `--cap-usd`, with B = $20 − s: reserves
  floor(0.60 B), energy floor(0.15 B), display floor(0.25 B), to the cent; they run at the same time, parallel 6, 3
  and 2 (the sweep starts no attempt that could pass its cap at E).
- **Amendment rule:** each run that ends unscored, in any column, is run once more at a 2E cap in a sweep named after
  its own with `-amend` (`v3b-pilot-sol-amend`, ...), `--cap-usd` = $20 minus the spend so far, and reported as a
  labelled amendment; the primary numbers are the first sweeps alone.

## Tasks (`docs/prereg/v3-pilot-b-tasks.json`, `scripts/pilot_v3b_tasks.py`, seed 4325)
- **Reserves column (scored, primary):** 30 `ercot-hybrid-v3-eval` days (2025-01..11, era B) at the reserves tier:
  all 13 deployment days of the pack, then 17 other days drawn round-robin over the AS strata until each stratum holds
  10 (8 low, 6 mid, 3 high), each pick on an undrawn date whose settlement point and month its stratum has drawn least,
  then the column's least-drawn point and month. 30 days on 26 dates (four deployment dates carry two sites), all 13
  points, all 11 months, 10 notice days, 1 with negative-price hours; 9 on oversized sites (8 at PV/POI 1.25, 1 at 1.4).
- **Energy column (scored, reported apart, never pooled):** 10 eval days at the energy tier on oversized sites with
  PV/POI >= 1.25, 5 at 1.25 and 5 at 1.4 (1.40 or 1.41), on dates the reserves column does not use, by the same rule
  over points and months: 10 points, 10 months, 4 notice days, 2 with negative-price hours, 2 with no clippable solar.
- **Display only, never counted:** `ercot-hybrid-v3-showcase` at the reserves tier: the hero aug10-2023
  (`hyb-v3-2023-08-10-HB_NORTH-pv150-b100x2h-poi150`, 7 watches, Non-Spin and ECRS deployments, fallback drift; the
  day C3-D18 fixed) and mar29-2024 (`hyb-v3-2024-03-29-HB_WEST-pv150-b100x2h-poi150`, 16 negative DA hours), one
  sweep. sept06-2023 stays out (C3-D16).
- **Known before any run** (stored references; R on the anchor scale, C = (P − P_idle)/(P_hind − P_idle)):
  - Reserves column: anchor's C 0.505 (deployment days 0.375, other days 0.604; low/mid/high 0.589/0.468/0.458).
    R (C): AS-hog 0.398 (0.136), solar sponge 0.256 (0.037), v2 energy-only 0.765 (0.371), energy-only MILP 0.813
    (0.403); no baseline at R = 1 on any day. The energy-only MILP and v2 energy-only differ on 11 days (6
    oversized days with clippable solar, 5 others) and coincide on 19. AS-hog scores 0 on 4 days. The anchor commits
    2.5 times a day, the governor moves 4.5 of its hours, it pays $18 a day of FTP ($41 on deployment days) and earns
    $6,441 a day of AS; P_anchor − P_idle has a median of $9,422.
  - Energy column: anchor's C 0.426 (PV/POI 1.25: 0.299, 1.4: 0.553); v2 energy-only R 0.866 (C 0.341; R = 1 on 4 of
    10), solar sponge R 0.392 (C 0.098); 192 clippable MWh a day (83 at 1.25, 301 at 1.4).
  - Display: aug10-2023 anchor's C 0.282 (P_anchor $1,590,378, P_hind $3,188,806), AS-hog R 0.429, v2 energy-only
    0.580, energy-only MILP 0.721; mar29-2024 anchor's C 0.856, AS-hog R 0.666, v2 energy-only and energy-only MILP
    0.609.
  - P3 under rules 3.0, recomputed by `scripts/pilot_v3b.py --regulation v3-pilot-sol` at b76e14a (its own code and
    packs): Sol's RegDn drift energy bought at RT $7,022 a day against the anchor's $3,516, L_reg (below) **+0.109
    (+0.054 to +0.165)**, Sol above the anchor on 22 of 30 days; RegDn in the day's six highest-DA hours 245 MW-h
    against the anchor's 103. On the same code P3's headline reads C 0.397 (0.313 to 0.484), anchor's C 0.480, Δ
    −0.083 (−0.120 to −0.049), R 0.811; its format: 15 planning calls kept a field with `"keep"`, all 15 refused as
    `parse`, and 1 day had no accepted watch-0 commit.

```
python scripts/pilot_v3b_tasks.py main --json docs/prereg/v3-pilot-b-tasks.json
S="agent-env gridsim sweep run --env gridsim-hybrid --models openai/gpt-6.1-sol"
$S --name v3b-smoke --pack ercot-hybrid-v3-train --tier reserves \
  --tasks "$(python scripts/pilot_v3b_tasks.py smoke-reserves)" --cap-usd 2.5 --episode-cap-usd 1.00 --parallel 2
$S --name v3b-smoke-energy --pack ercot-hybrid-v3-train --tier energy \
  --tasks "$(python scripts/pilot_v3b_tasks.py smoke-energy)" --cap-usd 1.25 --episode-cap-usd 1.00 --parallel 1
$S --name v3b-pilot-sol --pack ercot-hybrid-v3-eval --tier reserves \
  --tasks "$(python scripts/pilot_v3b_tasks.py main)" --cap-usd <0.60 B> --episode-cap-usd <E> --parallel 6
$S --name v3b-pilot-sol-energy --pack ercot-hybrid-v3-eval --tier energy \
  --tasks "$(python scripts/pilot_v3b_tasks.py energy)" --cap-usd <0.15 B> --episode-cap-usd <E> --parallel 3
$S --name v3b-pilot-sol-show --pack ercot-hybrid-v3-showcase --tier reserves \
  --tasks "$(python scripts/pilot_v3b_tasks.py showcase)" --cap-usd <0.25 B> --episode-cap-usd <E> --parallel 2
agent-env gridsim episodes v3b-smoke v3b-smoke-energy v3b-pilot-sol v3b-pilot-sol-energy v3b-pilot-sol-show
agent-env gridsim sweep report v3b-pilot-sol v3b-pilot-sol-energy --card results/eval-v3b.json \
  --board results/board-v3b.md
python scripts/pilot_v3b.py v3b-pilot-sol --energy v3b-pilot-sol-energy --showcase v3b-pilot-sol-show \
  --extra-spend v3b-smoke v3b-smoke-energy --json results/pilot-v3b.json
```

Reserves column:

| # | Task | Stratum | Deployment day | PV/POI | Watches | Notice day | Anchor − idle ($) | Anchor's C | AS-hog R (C) | Solar sponge R | v2 energy-only R (C) | Energy-only MILP R (C) |
|---:|---|---|---|---:|---:|---|---:|---:|---|---:|---|---|
| 1 | `hyb-v3-2025-03-02-LZ_CPS-pv150-b100x2h-poi150` | low | yes | 1.00 | 5 | no | 8,151 | 0.223 | 0.000 (-0.057) | 0.200 | 0.866 (0.186) | 0.866 (0.186) |
| 2 | `hyb-v3-2025-03-05-HB_HOUSTON-pv150-b100x2h-poi180` | high | yes | 0.83 | 7 | yes | 14,126 | 0.465 | 0.296 (0.056) | 0.200 | 0.758 (0.324) | 0.758 (0.324) |
| 3 | `hyb-v3-2025-03-05-LZ_NORTH-pv100-r80-2h-poi80` | mid | yes | 1.25 | 7 | yes | 11,817 | 0.573 | 0.121 (-0.056) | 0.535 | 0.784 (0.419) | 0.894 (0.497) |
| 4 | `hyb-v3-2025-03-10-LZ_CPS-pv100-r40-1h-poi120` | mid | yes | 0.83 | 6 | yes | 6,191 | 0.423 | 0.676 (0.252) | 0.200 | 0.733 (0.282) | 0.733 (0.282) |
| 5 | `hyb-v3-2025-03-10-LZ_NORTH-pv150-b100x2h-poi150` | high | yes | 1.00 | 6 | yes | 16,799 | 0.451 | 0.444 (0.137) | 0.200 | 0.830 (0.355) | 0.830 (0.355) |
| 6 | `hyb-v3-2025-04-07-HB_SOUTH-pv300-r80-1h-poi240` | high | yes | 1.25 | 6 | no | 69,050 | 0.111 | 0.000 (-0.041) | 0.325 | 0.465 (0.037) | 0.502 (0.042) |
| 7 | `hyb-v3-2025-05-16-LZ_WEST-pv100-r67-1h-poi120` | high | yes | 0.83 | 6 | yes | 58,318 | 0.193 | 0.138 (-0.015) | 0.200 | 0.379 (0.043) | 0.379 (0.043) |
| 8 | `hyb-v3-2025-05-17-HB_WEST-pv150-b100x2h-poi180` | high | yes | 0.83 | 6 | yes | 9,562 | 0.308 | 0.000 (-0.122) | 0.200 | 0.640 (0.169) | 0.640 (0.169) |
| 9 | `hyb-v3-2025-05-17-LZ_WEST-pv200-r40-2h-poi200` | mid | yes | 1.00 | 6 | yes | 8,604 | 0.314 | 0.000 (-0.205) | 0.200 | 0.792 (0.232) | 0.792 (0.232) |
| 10 | `hyb-v3-2025-09-04-HB_PAN-pv100-r67-2h-poi100` | low | yes | 1.00 | 6 | no | 7,684 | 0.594 | 0.573 (0.277) | 0.200 | 0.753 (0.411) | 0.872 (0.499) |
| 11 | `hyb-v3-2025-10-21-HB_HOUSTON-pv200-r40-1h-poi240` | mid | yes | 0.83 | 5 | no | 10,073 | 0.353 | 0.555 (0.157) | 0.200 | 0.753 (0.244) | 0.753 (0.244) |
| 12 | `hyb-v3-2025-10-21-LZ_SOUTH-pv300-r80-2h-poi300` | high | yes | 1.00 | 5 | no | 51,648 | 0.247 | 0.777 (0.178) | 0.200 | 0.701 (0.155) | 0.933 (0.227) |
| 13 | `hyb-v3-2025-11-07-LZ_AEN-pv150-r67-1h-poi150` | high | yes | 1.00 | 6 | no | 28,362 | 0.622 | 0.388 (0.146) | 0.200 | 0.712 (0.399) | 0.901 (0.546) |
| 14 | `hyb-v3-2025-08-09-LZ_RAYBN-pv150-b100x2h-poi120` | low | no | 1.25 | 5 | yes | 8,748 | 0.819 | 0.429 (0.234) | 0.579 | 0.629 (0.439) | 0.906 (0.723) |
| 15 | `hyb-v3-2025-02-08-LZ_LCRA-pv300-r40-2h-poi300` | mid | no | 1.00 | 5 | no | 10,156 | 0.685 | 0.749 (0.470) | 0.200 | 0.783 (0.499) | 0.783 (0.499) |
| 16 | `hyb-v3-2025-06-12-LZ_HOUSTON-pv300-r40-1h-poi240` | high | no | 1.25 | 5 | no | 5,832 | 0.652 | 0.358 (0.129) | 0.200 | 0.670 (0.383) | 0.670 (0.383) |
| 17 | `hyb-v3-2025-01-08-HB_NORTH-pv100-r80-1h-poi80` | low | no | 1.25 | 6 | yes | 5,262 | 0.678 | 0.267 (0.057) | 0.200 | 0.854 (0.554) | 0.854 (0.554) |
| 18 | `hyb-v3-2025-07-25-LZ_AEN-pv150-b100x2h-poi150` | mid | no | 1.00 | 5 | no | 19,062 | 0.625 | 0.515 (0.246) | 0.200 | 0.915 (0.558) | 0.915 (0.558) |
| 19 | `hyb-v3-2025-08-18-LZ_RAYBN-pv200-r80-1h-poi200` | high | no | 1.00 | 5 | no | 32,460 | 0.624 | 0.416 (0.168) | 0.200 | 0.937 (0.575) | 0.937 (0.575) |
| 20 | `hyb-v3-2025-04-12-HB_SOUTH-pv200-r40-2h-poi240` | low | no | 0.83 | 5 | no | 5,314 | 0.661 | 0.764 (0.466) | 0.200 | 0.917 (0.592) | 0.917 (0.592) |
| 21 | `hyb-v3-2025-06-30-HB_WEST-pv100-r67-1h-poi100` | mid | no | 1.00 | 5 | no | 7,199 | 0.397 | 0.655 (0.226) | 0.200 | 0.915 (0.355) | 0.915 (0.355) |
| 22 | `hyb-v3-2025-07-30-LZ_LCRA-pv150-r80-2h-poi150` | high | no | 1.00 | 5 | no | 120,949 | 0.910 | 0.522 (0.366) | 0.200 | 0.904 (0.800) | 0.965 (0.870) |
| 23 | `hyb-v3-2025-02-17-LZ_HOUSTON-pv200-r40-1h-poi160` | low | no | 1.25 | 5 | yes | 3,029 | 0.723 | 0.224 (0.022) | 0.424 | 0.848 (0.586) | 0.856 (0.593) |
| 24 | `hyb-v3-2025-01-24-LZ_SOUTH-pv300-r40-1h-poi360` | mid | no | 0.83 | 5 | no | 8,506 | 0.511 | 0.094 (-0.068) | 0.200 | 0.807 (0.388) | 0.807 (0.388) |
| 25 | `hyb-v3-2025-11-28-HB_WEST-pv300-r40-1h-poi240` | low | no | 1.25 | 5 | no | 3,492 | 0.420 | 0.361 (0.084) | 0.200 | 0.968 (0.403) | 0.968 (0.403) |
| 26 | `hyb-v3-2025-08-23-HB_PAN-pv150-b100x2h-poi120` | mid | no | 1.25 | 5 | no | 10,006 | 0.328 | 0.846 (0.265) | 0.632 | 0.703 (0.206) | 0.894 (0.284) |
| 27 | `hyb-v3-2025-06-19-LZ_NORTH-pv100-r80-1h-poi120` | low | no | 0.83 | 5 | no | 5,875 | 0.491 | 0.265 (0.040) | 0.200 | 0.753 (0.339) | 0.753 (0.339) |
| 28 | `hyb-v3-2025-09-25-HB_SOUTH-pv200-r80-1h-poi143` | mid | no | 1.40 | 5 | no | 16,995 | 0.468 | 0.526 (0.190) | 0.370 | 0.530 (0.193) | 0.646 (0.261) |
| 29 | `hyb-v3-2025-07-14-HB_HOUSTON-pv100-r67-2h-poi100` | low | no | 1.00 | 5 | no | 5,728 | 0.572 | 0.524 (0.232) | 0.200 | 0.941 (0.530) | 0.941 (0.530) |
| 30 | `hyb-v3-2025-10-16-LZ_LCRA-pv150-b100x2h-poi150` | low | no | 1.00 | 5 | no | 9,282 | 0.713 | 0.474 (0.244) | 0.200 | 0.717 (0.460) | 0.799 (0.533) |

Energy column:

| # | Task | PV/POI | Clippable MWh | Watches | Notice day | Anchor − idle ($) | Anchor's C | Solar sponge R (C) | v2 energy-only R (C) |
|---:|---|---:|---:|---:|---|---:|---:|---|---|
| 31 | `hyb-v3-2025-06-24-LZ_WEST-pv150-b100x2h-poi120` | 1.25 | 180 | 5 | no | 10,737 | 0.637 | 0.727 (0.419) | 0.872 (0.535) |
| 32 | `hyb-v3-2025-09-08-HB_SOUTH-pv200-r80-2h-poi143` | 1.40 | 415 | 5 | no | 11,974 | 0.876 | 0.200 (0.000) | 0.451 (0.275) |
| 33 | `hyb-v3-2025-10-25-LZ_HOUSTON-pv150-b100x2h-poi120` | 1.25 | 0 | 5 | no | 4,996 | 0.189 | 0.200 (0.000) | 1.000 (0.189) |
| 34 | `hyb-v3-2025-03-19-HB_WEST-pv150-b100x2h-poi107` | 1.40 | 144 | 5 | yes | 9,644 | 0.463 | 0.200 (0.000) | 1.000 (0.463) |
| 35 | `hyb-v3-2025-11-09-HB_PAN-pv300-r80-1h-poi240` | 1.25 | 97 | 6 | yes | 7,646 | 0.286 | 0.200 (0.000) | 1.000 (0.286) |
| 36 | `hyb-v3-2025-01-01-LZ_SOUTH-pv300-r80-1h-poi214` | 1.40 | 178 | 5 | no | 5,558 | 0.167 | 0.722 (0.109) | 0.648 (0.093) |
| 37 | `hyb-v3-2025-07-12-LZ_LCRA-pv100-r67-2h-poi80` | 1.25 | 0 | 5 | no | 5,594 | 0.064 | 0.200 (0.000) | 0.845 (0.051) |
| 38 | `hyb-v3-2025-04-09-LZ_RAYBN-pv200-r40-1h-poi143` | 1.40 | 494 | 5 | no | 7,679 | 0.751 | 0.200 (0.000) | 1.000 (0.765) |
| 39 | `hyb-v3-2025-02-24-HB_NORTH-pv150-r80-2h-poi120` | 1.25 | 140 | 5 | yes | 11,786 | 0.318 | 0.627 (0.170) | 0.919 (0.285) |
| 40 | `hyb-v3-2025-05-10-LZ_AEN-pv150-b100x2h-poi107` | 1.40 | 275 | 5 | yes | 8,242 | 0.510 | 0.649 (0.286) | 0.929 (0.465) |

## Metrics
Computed by `scripts/pilot_v3b.py` from the replay-verified Episode JSON v3 (`agent-env gridsim episodes`) and
results.jsonl, per the adopted cross-version rule (`docs/REWARD-SCALES.md` on lane-reward). CIs are 95% percentile
bootstrap over days, 10,000 resamples, seed 0 for levels and 1 for paired differences (`scripts/reward_scales.py`'s
`boot`), days in task-id order. Sets: the reserves column overall, on its 13 deployment days and 17 other days, and by
AS stratum; the energy column overall and by PV/POI class; each display day as one line.
- **Headline: hindsight capture C** = (P − P_idle)/(P_hind − P_idle), unclipped, the mean over days, beside the
  anchor's C on the same days and **Δ = C − C_anchor** = (P − P_anchor)/(P_hind − P_idle) with its paired CI.
- **Second: R** on the anchor scale (clip(0.2 + 0.8(P − P_idle)/(P_anchor − P_idle), 0, 1)), its CI, the share of
  days at R = 1 and the share beating the anchor (`beats_anchor`). R is a level, never differenced.
- **Baselines on the same days** (as stored): AS-hog, the solar sponge, v2 energy-only and, at the reserves tier, the
  energy-only MILP. Each: its C, its R, Sol − it as (P − P_ref)/(P_hind − P_idle) with a paired CI, and the share of
  days Sol's profit beats it.
- **Regulation (reserves):** each day replayed through `gridsim_core.hybrid.Session` and the anchor played in process
  (`anchor_policy`, which must reproduce the stored P_anchor to $0.001). RegDn drift cost = Σ_h RegDn drift MWh × RT_h
  (energy the drift bought); **L_reg** = (Sol's − the anchor's)/(P_hind − P_idle), mean with a paired CI; also $/day,
  the days Sol pays more, drift MWh, RegDn MW-h in the day's six highest-DA hours and RegDn and RegUp MW-h a day, Sol
  against the anchor.
- **Deployment days (reserves):** per day, each deployed product's hours, Sol's and the anchor's award in those hours,
  FTP MWh charged in that product, the watches a deployment notice opened and whether Sol committed at them, C, the
  anchor's C, Δ and R; the gap Δ(deployment days) − Δ(other days) with an unpaired bootstrap CI (seed 2).
- **Format:** planning calls that keep an AS field by `"keep"` or null and how many were refused as `parse`; commits
  refused as `parse`; days without an accepted watch-0 commit.
- `scripts/pilot_v3.py`'s tables as in P3: AS share and revenue against the anchor's, the DA AS book by product, FTP
  charged and excused by product, under-reserved days, governor hours, end-short days, re-plan rate, refusals by rule,
  audit failures, tokens, $/episode and turns; unscored runs and why; spend per sweep, the smoke included.

## Hypotheses
- **H1 (regulation): Sol's regulation loss shrinks under measured drift.** Supported if the 95% CI of L_reg on the
  reserves column lies wholly below P3's +0.109; not supported if its point estimate is +0.109 or more; undecided
  otherwise. Also read on the 17 non-deployment days alone.
- **H2 (deployments): Sol handles deployment days.** Supported if Sol's mean Δ on the 13 deployment days is no more
  than 0.05 below its mean Δ on the 17 other days (point estimate of the gap ≥ −0.05); not supported otherwise. The
  per-day table shows how.
- **H3 (energy tier on oversized sites): the energy tier now separates Sol from the PV-blind and sponge baselines.**
  Supported if the paired CIs of Sol − v2 energy-only and Sol − solar sponge (each (P − P_ref)/(P_hind − P_idle)) on
  the energy column both lie above 0; not supported if either point estimate is 0 or below; undecided otherwise.
- **H4 (format, V3-D13): the keep rule removes P3's format losses.** Supported if no planning call that keeps an AS
  field by `"keep"` or null is refused as `parse` and every reserves day has an accepted watch-0 commit.
- Expectations, not success bars: Sol's reserves C beats AS-hog's and the sponge's; reserves Δ above P3's −0.083.

## Readings registered before the run
- **The reserves tier as the test:** if the CI of Sol − energy-only MILP lies below 0, the reserves tier is called
  harder than energy-only arbitrage for this model; above 0, Sol is called to earn from co-optimising AS; across 0,
  undecided at this size.
- **Energy tier saturation:** saturated for this model if Sol's energy-column mean R is 0.95 or more, as in P3; H3
  reads separation from the baselines, this reads the ceiling.
- **Anchor scale:** compressed for this model if more than a third of the reserves days sit at R = 1 (V2-D1's rule).
- **Display days:** C, the anchor's C, Δ, R and the baselines, printed and never pooled.

## Deviations

Run as registered, with one infrastructure event and one amendment. Smoke: 3 of 3 scored at the first attempt
(reserves deployment day R 0.413, $0.132; reserves quiet day R 1.0, $0.161; energy day R 1.0, $0.052): s $0.345, m
$0.1317, projection $5.22, so E = $0.53 and B = $19.66, giving `--cap-usd` 11.79 (reserves), 2.94 (energy) and 4.91
(display); the three ran at the same time.
- Five first attempts in `v3b-pilot-sol` ended `provider_error` within a few minutes of each other (the upstream model
  gateway refused authentication); the sweep retried each as registered and all five scored at their second attempt.
  The failed attempts cost $0.24.
- 2025-02-17 LZ_HOUSTON stopped at its cap at turn 20 (the guard's estimate, $0.363 spent plus a $0.17 turn, passed
  $0.53; its priced cost was $0.193). Per the amendment rule it ran once more at $1.06 in `v3b-pilot-sol-amend`
  (`--cap-usd` 11.38, $20 less the spend so far) and scored R 1.0 for $0.13. The primary reserves numbers are the 29
  first-sweep days; the 30-day set is reported as amended.
- The amendment rule adds `--amend v3b-pilot-sol=v3b-pilot-sol-amend` to `sweep report` and `--amend
  v3b-pilot-sol-amend` to `scripts/pilot_v3b.py`. No code changed after this file was committed; nothing was rerun.
- H4's registered count includes one keep call refused as `parse` for its 18-value energy list, not for its kept
  fields; it is reported as registered.

Spend $8.75 of $20 (smoke $0.35, reserves $7.46, energy $0.46, display $0.35, amendment $0.13). All 45 Episode JSON
(the smoke's 3 included) replay byte for byte on a fresh Session, audits ok. Results: `results/board-v3b.md` (Pilot
under rules 3.1 and Reading), `results/pilot-v3b.json`, `results/eval-v3b.json`.
