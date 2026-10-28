# GridSim v2 live board

Tasks: 40 live battery-days (gridsim-live-eval). Harness: gridsim-llm on gridsim-live, 52 turns, 3 planning calls a watch, 8192 output tokens a turn, effort high. R: clip(0.2+0.8(P-P_idle)/(P_roll-P_idle),0,1); no accepted commit scores 0; the anchor (1.0) is the notice-blind rolling re-planner.

Headline: hindsight capture C = (P − P_idle)/(P_hind − P_idle), unclipped, with P_hind the clairvoyant optimum of the same settlement (the DA position on DA − RT, the physical schedule on RT, both exact DPs): idle 0, hindsight 1. It is printed beside the anchor's own C on the same tasks and Δ = C − C_anchor, the paired gap with its 95% CI. Second: R on the anchor scale (the anchor 1.0), a level that is never differenced, with its R = 1 share (a tie with the anchor or better) and the beats-anchor share. Every comparison with a reference is (P − P_ref)/(P_hind − P_idle). CIs bootstrap over tasks; the rule and its evidence: docs/REWARD-SCALES.md.

Baselines (foresight, 40 days): C idle 0, naive (v1's plan, never re-planned) 0.425, anchor 0.498, hindsight 1; R idle 0.200, naive 0.850, anchor 1.000.

| Model | Tier | Days | Runs/planned | C (95% CI) | Anchor's C | Δ vs anchor (95% CI) | R (95% CI) | R = 1 | Beats anchor | Beats naive | Valid | Planning calls | Commits | Finished | $/episode | Spend |
|---|---|---:|---:|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | foresight | 40 | 40/40 | 0.437 (0.361 to 0.513) | 0.498 | -0.061 (-0.089 to -0.035) | 0.883 (0.838 to 0.924) | 0.375 | 0.225 | 0.250 | 1.000 | 2.42 | 2.33 | 1.000 | $0.0462 | $1.95 |

## Against the references

| Model | Tier | Reference | Its C | Model − it (95% CI) | Tasks |
|---|---|---|---:|---|---:|
| openai/gpt-6.1-sol | foresight | naive | 0.425 | +0.012 (-0.004 to +0.028) | 40 |

## Errors

Scored runs by what went wrong; a run can show several.

| Model | Tier | no_commit | refused | end_short | clipped | no_replanning |
|---|---|---:|---:|---:|---:|---:|
| openai/gpt-6.1-sol | foresight | 0 | 1 | 0 | 0 | 28 |

## Unscored runs

None.

## Pilot (pre-registered in docs/prereg/v2-pilot.md, f27af9f)

GPT-6.1 Sol, effort high, 52 turns, $0.60 episode cap, on 40 gridsim-live-eval foresight days (20 notice, 20 quiet,
`scripts/pilot_tasks.py`, seed 4321) after the prompt fix 7fbb569. Computed by `scripts/pilot_v2.py` from the 40
replay-verified Episode JSON v2 (`results/pilot-v2.json`). Capture is (P − P_idle)/(P_hind − P_idle): idle 0,
hindsight 1. Beats naive compares profit, not R (naive's R is clipped at 1 on 14 of these days), so it differs from
the board row above, which compares R. Re-plan rate: the watches after watch 0 with an accepted `commit_schedule`,
over all watches after watch 0. CIs are 95% bootstrap over days, paired for differences.

| Set | Days | R (95% CI) | Naive R | R − naive R (95% CI) | R = 1 | Capture (95% CI) | Naive capture | Anchor capture | Capture − naive (95% CI) | Capture − anchor (95% CI) | Beats naive | Ties naive | Beats anchor |
|---|---:|---|---:|---|---:|---|---:|---:|---|---|---:|---:|---:|
| primary: all | 40 | 0.883 (0.840 to 0.924) | 0.850 | 0.033 (0.010 to 0.060) | 0.375 | 0.437 (0.360 to 0.517) | 0.425 | 0.498 | 0.012 (-0.004 to 0.028) | -0.061 (-0.088 to -0.035) | 0.250 | 0.600 | 0.225 |
| primary: notice | 20 | 0.968 (0.928 to 0.997) | 0.940 | 0.028 (-0.002 to 0.069) | 0.700 | 0.447 (0.325 to 0.564) | 0.451 | 0.450 | -0.004 (-0.027 to 0.011) | -0.003 (-0.029 to 0.019) | 0.250 | 0.600 | 0.450 |
| primary: quiet | 20 | 0.797 (0.740 to 0.853) | 0.759 | 0.039 (0.008 to 0.074) | 0.050 | 0.426 (0.338 to 0.521) | 0.399 | 0.546 | 0.028 (0.006 to 0.053) | -0.120 (-0.153 to -0.088) | 0.250 | 0.600 | 0.000 |
| primary: anchor ≠ naive | 35 | 0.867 (0.821 to 0.914) | 0.828 | 0.039 (0.014 to 0.069) | 0.314 | 0.435 (0.357 to 0.517) | 0.421 | 0.505 | 0.014 (-0.005 to 0.032) | -0.070 (-0.100 to -0.040) | 0.286 | 0.571 | 0.257 |
| primary: a notice watch | 18 | 0.957 (0.912 to 0.993) | 0.920 | 0.036 (-0.001 to 0.084) | 0.667 | 0.467 (0.322 to 0.622) | 0.466 | 0.478 | 0.001 (-0.029 to 0.024) | -0.010 (-0.043 to 0.018) | 0.333 | 0.444 | 0.444 |

| Set | Days | Re-plan rate | Days re-planned | Anchor re-plan rate | Finished | Refused commits | Audit failures | $/episode | Turns |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| primary: all | 40 | 0.071 | 0.300 | 0.386 | 1.000 | 1 on 1 days | 0 | $0.0462 | 15.1 |
| primary: notice | 20 | 0.078 | 0.350 | 0.343 | 1.000 | 1 on 1 days | 0 | $0.0506 | 16.1 |
| primary: quiet | 20 | 0.061 | 0.250 | 0.439 | 1.000 | 0 on 0 days | 0 | $0.0419 | 14.1 |
| primary: anchor ≠ naive | 35 | 0.083 | 0.343 | 0.452 | 1.000 | 1 on 1 days | 0 | $0.0465 | 15.0 |
| primary: a notice watch | 18 | 0.094 | 0.444 | 0.344 | 1.000 | 0 on 0 days | 0 | $0.0552 | 17.1 |

Hero (display only): live-v2-2023-09-06-HB_NORTH-2h-l: R 0.596 (naive 0.596), capture 0.077 (naive 0.077, anchor 0.156), profit $14,940 (naive $14,940, anchor $30,157, hindsight $193,619), re-planned 0 of 9 later watches, $0.0778, 23 turns

Unscored: none.
Spend: v2-pilot-sol $1.95, v2-pilot-sol-hero $0.08.

## Reading

- **Sol plays naive and holds it.** At watch 0 Sol committed v1's naive DA position on 33 of 40 days, an equally
  profitable variant on 1, and its own plan on 6, mostly with an extra cycle the DP had skipped (the 4 of those it
  never re-planned lost $1.5 to $307 to naive). After the prompt fix it finished all 41 days
  with its own `advance` (12 to 23 turns, no nudges), but it re-planned on only 12 of 40 days, 7.1% of later watches
  against the anchor's 38.6%. It used 3 dry runs in 41 days. Pre-registered expectations: finishing on 90% or more
  of runs, met (100%); re-planning on half the days or more, not met (30%).
- **When Sol re-plans, it mostly gains.** 10 of the 12 re-planned days beat naive (+$21 to +$9,418), mostly at the
  regular 12:00 and 18:00 watches, on the settled RT prices. Two re-plans fell on notice watches: +$8,167 at a 12:30
  watch (2024-05-09 LZ_HOUSTON) and −$2,870 at a 03:45 watch (2024-07-08 LZ_LCRA).
- **Against naive.** R 0.883 (0.840 to 0.924) against naive's 0.850 on the same days, +0.033 (0.010 to 0.060).
  Capture 0.437 against 0.425, +0.012 (−0.004 to 0.028). Sol beats naive on 10 days, ties on 24 and trails on 6.
- **Against the anchor and hindsight.** Capture − anchor is −0.061 (−0.088 to −0.035). The anchor itself captures
  only 0.498, so half the hindsight value is still open above it. Sol beats the anchor on 9 days, all of them notice
  days.
- **Notice vs quiet.** The registered direction holds on paper: beats-anchor 0.45 on notice days vs 0.00 on quiet
  days, capture − anchor −0.003 vs −0.120. That is the pack, not the notices. Notice days skip the anchor-beats-naive
  filter (L-D9), so on these 20 days naive beats the anchor 9 times, ties it 5 times and trails it 6 times. Sol beats
  the anchor on exactly those 9 days. Sol's capture − naive on notice days is −0.004 (−0.027 to 0.011): no sign that
  it uses the notices. A policy that just holds naive "beats the notice-blind anchor on notice days" 45% of the time,
  so the X6 metric needs naive as a floor (beat max(P_naive, P_roll), or capture − naive) before it can say anything.
- **Hero day (sep23-0906, HB_NORTH, display only).** Sol read the ERCOT Watch at 09:45 ("keeping the battery full for
  the evening risk window") and kept its 18:00 to 20:00 discharge, and it never re-planned across 9 later watches,
  through the conservation appeal, the EEA2 at 19:30 and the exits. R 0.596 = naive, capture 0.077 against the
  anchor's 0.156. Profit $14,940 against the anchor's $30,157 and hindsight's $193,619.
- **V2-D1.** By the registered rule the anchor scale is compressed for this model: 37.5% of Sol's days sit at R = 1
  (70% of notice days), and naive alone scores 0.850. On R, the useful range between naive and the anchor is
  0.85 to 1.0 (0.94 to 1.0 on notice days). Hindsight capture keeps the order idle 0 < naive 0.425 < anchor 0.498 <
  hindsight 1, leaves headroom above the anchor, and separates Sol from the anchor with a CI that excludes 0. The
  pilot supports hindsight capture as the headline, with R on the anchor scale as a secondary row and naive as the
  floor for the notice-day claim.
- **Cost.** $1.95 for the 40 days ($0.046 a day, at most $0.147) and $0.08 for the hero: $2.03 of the $15 budget. No
  run hit the $0.60 cap, all 40 scored on the first attempt, and every episode replayed byte for byte with its audit
  passing.
