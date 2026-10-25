# Reward scales across GridSim versions

Which number heads each version's board, which sits beside it, and which one trains. The evidence is GPT-6.1 Sol's
committed runs (the v1 board's 1,550 and the v2 to v5 pilots' 150) with every reference stored on the same tasks, and
the references alone on the full eval packs. `scripts/reward_scales.py` regenerates every table below from committed
files (Episode JSON, `results/pilot-v5.json`, the packs' rows); it spends nothing. CIs are 95% percentile bootstrap
over tasks (10,000 resamples), paired for differences.

## The rule

| | Every version |
|---|---|
| (i) Board headline | Hindsight capture **C** = (P − P_idle)/(P_hind − P_idle), unclipped, the mean over tasks, printed beside the anchor's C on the same tasks and **Δ = C − C_anchor** with its paired 95% CI. P_hind is the clairvoyant optimum of the same settlement: v5 uses BR_rt, not BR_A. |
| (ii) Second column | **R** on the anchor scale, unchanged, with its R = 1 share and the beats-anchor share. R is reported as a level, never differenced: every paired comparison is (P − P_ref)/(P_hind − P_idle). |
| (iii) Training reward | **S**: R up to the anchor, stretched above it to 1.2 at hindsight. It is the v2 contract's training-only `stretch_reward`, used in every version. S = R wherever P ≤ P_anchor, so nothing trained or published so far moves (v1's trained 0.72 is at the foresight tier, where the anchor is the hindsight). |
| (iv) v5 | The public default stays the compliant score, with the headline's capture as its profit half: 0.5·clip(C, 0, 1) + 0.5·clip(W/W\*, 0, 1). R and regret stay on the research board. |
| (v) v1 | Foresight: P_anchor = P_hind = P_opt, so C = (R − 0.2)/0.8 and S = R; the headline is C 1.000 (99% of days at 1), the tier read as solved. Blind: C 0.896 (0.881 to 0.910) against the blind anchor's 0.901, Δ −0.005 (−0.019 to +0.009), R 0.972 second. The published r_opt (0.9165) is 0.2 + 0.8·C; C replaces it. |

## What decides it

1. **R cannot compare a policy with its anchor.** The anchor is pinned at R = 1 and every run that beats it clips to 1,
   so R − R_anchor is ≤ 0 on every task by construction. It reports deficits where the dollars are level: v1 blind
   −0.028 (−0.037 to −0.020), while Sol's profit is +$3 a day against the anchor (above it on 99 days, tied on 88,
   below on 113) and Δ is −0.005 (−0.019 to +0.009); v4 front −0.091 (−0.164 to −0.033) against Δ −0.019 (−0.056 to
   +0.016); v5 floor-day −0.142 (−0.308 to −0.015), while Sol out-earns the anchor on 6 of 10 floors (mean +$51,363,
   median +$11,999) and Δ is −0.000 (−0.114 to +0.093). The same clip biases R against whichever of two policies
   passes the anchor more often: on floor-day R puts Sol −0.131 (−0.300 to −0.008) below the price-taker, which Sol
   out-earns on 6 of 10 floors.
2. **R = 1 is a tie class, not a top score.** Sol sits at R = 1 on 20% to 60% of v2 to v5 tasks (v3 energy 80%).
   Ordinary stored references reach it on about half of each eval pack: the v5 price-taker on 53% of 200 floors, v4's
   three-scenario re-planner on 57% of 60 windows, v3's one-shot MILP on 55% of 300 days, v2's blind re-planner on 55%
   of 276. No v2 to v5 run reaches C = 1, and no run or stored reference on any pack exceeds a valid P_hind.
3. **R = 1 is a different share of the attainable in every version.** The anchor's own capture on the eval packs is
   1.00 (v1 foresight), 0.90 (v1 blind), 0.52 (v2), 0.51 and 0.44 (v3 reserves, energy), 0.51 and 0.43 (v4 front,
   front-lite), 0.38 and 0.32 (v5 floor-sprint, floor-day, against BR_rt). C is one scale across versions; R is not.
4. **C is not a training reward.** The information-matched anchor scores exactly 1 on every task under R; under C
   its score spreads with SD 0.15 to 0.25 across v2 to v5 tasks, as much as Sol's own spread (0.18 to 0.26; v5
   floor-sprint 0.44). That is task noise no policy can remove. R keeps it out, and S adds the gradient R lacks above
   the anchor: on v1 blind and v2 to v5, Sol's runs sit strictly inside R on 20% to 80% of tasks and inside S on 90%
   to 100%.

## What P_hind is

| Version | P_hind | Kind | Exceeded by a run or reference | LP bound |
|---|---|---|---|---|
| v1 | P_opt, the exact DP on D's prices | an achievable plan (the foresight tier plays it) | never | P_lp = P_opt on every day |
| v2 | two exact DPs: the DA position on DA − RT, the physical schedule on RT | an achievable clairvoyant plan | never | P_lp above it on 2 of 40 pilot days (max $801) |
| v3 | the hindsight MILP: a DA copy and a physical copy on realised RT, drift and deployments, sharing the AS book | the exact optimum of a clairvoyant model, not a playable plan | never | P_lp = P_hind on all 40 pilot days |
| v4 | v3's hindsight over the window | as v3 | never | P_lp above it on 3 of 30 (max $185) |
| v5 | BR_A (`p_br`): the DA-clear best response, awards delivered as awarded | **not a bound**: the floor-day anchor exceeds it on 70 of 194 eval floors, Sol on 8 of 40 runs; Sol's floor-sprint C against it reaches −13.6 | yes | – |
| v5 | BR_rt (`p_br_rt`): the same with deviations settled at realised RT | the clairvoyant bound of the same settlement | never | – |

v5's C uses BR_rt: it is the object v2 to v4 call P_hind (a DA position plus physical delivery on realised RT), nothing
exceeds it, and the anchor's capture against it (0.38, 0.32) sits with v2 to v4's (0.43 to 0.52). BR_A stays as the
weight-0 DA-only row (`capture_vs_br`, `regret_norm`).

## Sol on R and C

Best other ref: the stored non-anchor reference with the highest mean profit on the column's tasks (at the v1 blind
tier, only references a blind desk can run). C − its C is the paired (P − P_ref)/(P_hind − P_idle).

| Column | n | R (95% CI) | R = 1 | C (95% CI) | C = 1 | C < 0 | Anchor's C | C − anchor's C (95% CI) | R − anchor's R (95% CI) | Best other ref | C − its C (95% CI) | R − its R (95% CI) |
|---|---:|---|---:|---|---:|---:|---:|---|---|---|---|---|
| v1 A foresight | 500 | 1.000 (1.000 to 1.000) | 0.99 | 1.000 (1.000 to 1.000) | 0.99 | 0 | 1.000 | -0.000 (-0.000 to -0.000) | -0.000 (-0.000 to -0.000) | greedy | +0.299 (+0.269 to +0.329) | +0.239 (+0.215 to +0.263) |
| v1 B foresight oneshot | 500 | 1.000 (1.000 to 1.000) | 0.99 | 1.000 (1.000 to 1.000) | 0.99 | 0 | 1.000 | -0.000 (-0.000 to -0.000) | -0.000 (-0.000 to -0.000) | greedy | +0.299 (+0.270 to +0.329) | +0.239 (+0.216 to +0.263) |
| v1 C blind | 300 | 0.972 (0.962 to 0.980) | 0.62 | 0.896 (0.881 to 0.910) | 0.13 | 1 | 0.901 | -0.005 (-0.019 to +0.009) | -0.028 (-0.037 to -0.020) | persist_dp | +0.043 (+0.027 to +0.059) | +0.015 (+0.004 to +0.027) |
| v1 D rtcb foresight | 250 | 1.000 (1.000 to 1.000) | 0.99 | 1.000 (1.000 to 1.000) | 0.99 | 0 | 1.000 | -0.000 (-0.000 to +0.000) | -0.000 (-0.000 to +0.000) | greedy | +0.346 (+0.301 to +0.392) | +0.276 (+0.240 to +0.312) |
| v2 foresight | 40 | 0.883 (0.839 to 0.924) | 0.38 | 0.437 (0.362 to 0.515) | 0.00 | 1 | 0.498 | -0.061 (-0.089 to -0.036) | -0.117 (-0.160 to -0.076) | naive | +0.012 (-0.005 to +0.028) | +0.033 (+0.011 to +0.060) |
| v3 reserves | 30 | 0.811 (0.738 to 0.877) | 0.20 | 0.397 (0.313 to 0.484) | 0.00 | 0 | 0.480 | -0.083 (-0.120 to -0.049) | -0.189 (-0.262 to -0.122) | v2_energy | +0.018 (-0.018 to +0.056) | -0.025 (-0.099 to +0.043) |
| v3 energy | 10 | 1.000 (0.999 to 1.000) | 0.80 | 0.483 (0.366 to 0.610) | 0.00 | 0 | 0.484 | -0.000 (-0.001 to +0.000) | -0.000 (-0.001 to -0.000) | v2_energy | +0.020 (+0.000 to +0.047) | +0.020 (-0.000 to +0.049) |
| v4 front | 20 | 0.909 (0.835 to 0.967) | 0.35 | 0.458 (0.361 to 0.553) | 0.00 | 0 | 0.477 | -0.019 (-0.056 to +0.016) | -0.091 (-0.164 to -0.033) | roll3 | -0.017 (-0.058 to +0.020) | -0.067 (-0.144 to -0.004) |
| v4 front-lite | 10 | 0.883 (0.738 to 0.980) | 0.50 | 0.404 (0.287 to 0.510) | 0.00 | 0 | 0.450 | -0.047 (-0.097 to -0.005) | -0.117 (-0.266 to -0.020) | roll3 | -0.072 (-0.174 to +0.002) | -0.082 (-0.238 to +0.027) |
| v5 floor-sprint | 30 | 0.801 (0.672 to 0.906) | 0.43 | 0.348 (0.181 to 0.495) | 0.00 | 4 | 0.414 | -0.067 (-0.202 to +0.057) | -0.199 (-0.324 to -0.092) | price_taker | -0.061 (-0.195 to +0.066) | -0.123 (-0.235 to -0.025) |
| v5 floor-day | 10 | 0.858 (0.695 to 0.975) | 0.60 | 0.419 (0.261 to 0.579) | 0.00 | 0 | 0.419 | -0.000 (-0.114 to +0.093) | -0.142 (-0.308 to -0.015) | price_taker | -0.002 (-0.114 to +0.087) | -0.131 (-0.300 to -0.008) |

C's unpaired CI is wider than R's (v2: 0.153 against 0.085) because it carries each task's information headroom; the
paired Δ removes it (v2 0.053, v3 0.071, v4 0.072), which is why C is never printed without Δ.

## The candidates

| Scale | Formula | Reading |
|---|---|---|
| (a) R | clip(0.2 + 0.8·(P − P_idle)/(P_anchor − P_idle), 0, 1) | Bounded, information-matched, no task noise at the anchor: right for training up to the anchor. On the board it saturates, is one-sided against the anchor, moves with the anchor and changes meaning across versions. **Second column.** |
| (b) C | (P − P_idle)/(P_hind − P_idle) | No ceiling where P_hind is a bound (no v2 to v5 run at 1); keeps idle 0 < rule-based heuristics < anchor < hindsight 1 on every pack and shows the three packs where another stored re-planner out-captures the anchor; independent of the anchor; one scale across versions; below 0 on 6 of 1,700 runs (min −0.95). Wide unpaired CI and task noise, so it heads the board with Δ and does not train. **Headline.** |
| (c) Δ | (P − P_anchor)/(P_hind − P_idle) = C − C_anchor | Two-sided, the tightest paired CI: the comparison printed with the headline (v4's `paired_vs_anchor`). Not a headline alone: its zero is the anchor. |
| (d1) Rh | clip(0.2 + 0.8·C, 0, 1), v1's r_opt and v4's r_hind | An affine copy of C with the same z, plus a floor at C = −0.25 that hides losses (v5 floor-sprint: 10% of floors at 0; z against the anchor 0.16 against C's 0.51). The boards print three hindsight numbers today: Rh (v1's r_opt, v4's r_hind), C (v2, v3, v4's capture) and C against BR_A (v5); C replaces them. |
| (d2) Q | (P − P_anchor)/(P_hind − P_anchor) | Undefined where the anchor is the hindsight (v1 foresight), unbounded below (v2 −1.2; v5 against BR_A −77). Used only inside S above the anchor, where it is in [0, 1]. |
| (d3) S | R; above the anchor min(1.2, 1 + 0.2·Q) | R's information matching plus a gradient above the anchor (no v2 to v5 run at 1.2). A dollar above the anchor still weighs c_a/(4(1 − c_a)) of one below it (a quarter at anchor capture c_a = 0.5), so it is not a board statistic. **Training reward.** |
| (d4) K | 0.2 + 0.6·(P − P_idle)/(P_anchor − P_idle) up to the anchor, then 0.8 + 0.2·Q | No ceiling and keeps the order, but the same kink under-credits play above the anchor (v4 front: −0.061, its CI excluding 0, where Δ is level), and it moves the anchor off 1.0 under every published R. Rejected. |

<details><summary>Every scale on every column</summary>

At max and at min are shares of runs (for G and Q, the share below 0); z is |paired mean| over the CI half-width,
so z > 1 means the CI excludes 0.

| Column | Scale | Sol | At max | At min (< 0 for G, Q) | z vs anchor | z vs best other | SD over tasks |
|---|---|---:|---:|---:|---:|---:|---:|
| v1 A foresight | R | 1.000 | 0.99 | 0.00 | 0.92 | 10.10 | 0.002 |
| v1 A foresight | C | 1.000 | 0.99 | 0.00 | 0.92 | 10.04 | 0.002 |
| v1 A foresight | Rh | 1.000 | 0.99 | 0.00 | 0.92 | 10.10 | 0.002 |
| v1 A foresight | G | -0.000 | – | 0.01 | 0.92 | 10.04 | 0.002 |
| v1 A foresight | S | 1.000 | 0.00 | 0.00 | 0.92 | 10.10 | 0.002 |
| v1 A foresight | K | 0.800 | 0.00 | 0.00 | 0.92 | 10.09 | 0.001 |
| v1 C blind | R | 0.972 | 0.62 | 0.00 | 3.18 | 1.29 | 0.079 |
| v1 C blind | C | 0.896 | 0.13 | 0.00 | 0.34 | 2.71 | 0.129 |
| v1 C blind | Rh | 0.917 | 0.13 | 0.00 | 0.34 | 2.71 | 0.103 |
| v1 C blind | G | -0.005 | – | 0.38 | 0.34 | 2.71 | 0.126 |
| v1 C blind | S | 1.006 | 0.05 | 0.00 | 0.46 | 3.39 | 0.109 |
| v1 C blind | K | 0.813 | 0.05 | 0.00 | 1.19 | 3.80 | 0.093 |
| v2 foresight | R | 0.883 | 0.38 | 0.00 | 2.80 | 1.36 | 0.137 |
| v2 foresight | C | 0.437 | 0.00 | 0.00 | 2.31 | 0.71 | 0.248 |
| v2 foresight | Rh | 0.549 | 0.00 | 0.00 | 2.31 | 0.71 | 0.198 |
| v2 foresight | G | -0.061 | – | 0.62 | 2.31 | 0.71 | 0.087 |
| v2 foresight | Q | -0.166 | – | 0.62 | 2.00 | 0.92 | 0.269 |
| v2 foresight | S | 0.885 | 0.00 | 0.00 | 2.68 | 1.29 | 0.139 |
| v2 foresight | K | 0.715 | 0.00 | 0.00 | 2.64 | 1.27 | 0.105 |
| v3 reserves | R | 0.811 | 0.20 | 0.00 | 2.70 | 0.36 | 0.195 |
| v3 reserves | C | 0.397 | 0.00 | 0.00 | 2.32 | 0.48 | 0.240 |
| v3 reserves | Rh | 0.518 | 0.00 | 0.00 | 2.32 | 0.48 | 0.192 |
| v3 reserves | G | -0.083 | – | 0.80 | 2.32 | 0.48 | 0.100 |
| v3 reserves | Q | -0.160 | – | 0.80 | 1.62 | 1.07 | 0.275 |
| v3 reserves | S | 0.817 | 0.00 | 0.00 | 2.53 | 0.27 | 0.201 |
| v3 reserves | K | 0.664 | 0.00 | 0.00 | 2.48 | 0.24 | 0.152 |
| v3 energy | R | 1.000 | 0.80 | 0.00 | 0.67 | 0.83 | 0.001 |
| v3 energy | C | 0.483 | 0.00 | 0.00 | 0.67 | 0.85 | 0.199 |
| v3 energy | Rh | 0.586 | 0.00 | 0.00 | 0.67 | 0.85 | 0.159 |
| v3 energy | G | -0.000 | – | 0.20 | 0.67 | 0.85 | 0.001 |
| v3 energy | Q | -0.004 | – | 0.20 | 0.67 | 0.73 | 0.012 |
| v3 energy | S | 1.000 | 0.00 | 0.00 | 0.67 | 0.83 | 0.001 |
| v3 energy | K | 0.800 | 0.00 | 0.00 | 0.67 | 0.83 | 0.001 |
| v4 front | R | 0.909 | 0.35 | 0.00 | 1.39 | 0.95 | 0.152 |
| v4 front | C | 0.458 | 0.00 | 0.00 | 0.53 | 0.44 | 0.221 |
| v4 front | Rh | 0.566 | 0.00 | 0.00 | 0.53 | 0.44 | 0.177 |
| v4 front | G | -0.019 | – | 0.65 | 0.53 | 0.44 | 0.083 |
| v4 front | Q | -0.051 | – | 0.65 | 0.80 | 0.55 | 0.147 |
| v4 front | S | 0.916 | 0.00 | 0.00 | 1.24 | 0.88 | 0.157 |
| v4 front | K | 0.739 | 0.00 | 0.00 | 1.19 | 0.85 | 0.119 |
| v4 front-lite | R | 0.883 | 0.50 | 0.00 | 0.95 | 0.62 | 0.209 |
| v4 front-lite | C | 0.404 | 0.00 | 0.00 | 1.01 | 0.82 | 0.180 |
| v4 front-lite | Rh | 0.523 | 0.00 | 0.00 | 1.01 | 0.82 | 0.144 |
| v4 front-lite | G | -0.047 | – | 0.50 | 1.01 | 0.82 | 0.076 |
| v4 front-lite | Q | -0.089 | – | 0.50 | 1.14 | 0.97 | 0.127 |
| v4 front-lite | S | 0.885 | 0.00 | 0.00 | 0.93 | 0.65 | 0.211 |
| v4 front-lite | K | 0.714 | 0.00 | 0.00 | 0.92 | 0.66 | 0.158 |
| v5 floor-sprint | R | 0.801 | 0.43 | 0.10 | 1.72 | 1.18 | 0.328 |
| v5 floor-sprint | C | 0.348 | 0.00 | 0.00 | 0.51 | 0.46 | 0.441 |
| v5 floor-sprint | Rh | 0.520 | 0.00 | 0.10 | 0.16 | 0.09 | 0.251 |
| v5 floor-sprint | G | -0.067 | – | 0.57 | 0.51 | 0.46 | 0.367 |
| v5 floor-sprint | Q | -0.173 | – | 0.57 | 0.74 | 0.68 | 0.661 |
| v5 floor-sprint | S | 0.827 | 0.00 | 0.10 | 1.42 | 0.93 | 0.347 |
| v5 floor-sprint | K | 0.672 | 0.00 | 0.10 | 1.31 | 0.86 | 0.278 |
| v5 floor-day | R | 0.858 | 0.60 | 0.00 | 0.97 | 0.90 | 0.239 |
| v5 floor-day | C | 0.419 | 0.00 | 0.00 | 0.00 | 0.02 | 0.260 |
| v5 floor-day | Rh | 0.535 | 0.00 | 0.00 | 0.00 | 0.02 | 0.208 |
| v5 floor-day | G | -0.000 | – | 0.40 | 0.00 | 0.02 | 0.168 |
| v5 floor-day | Q | 0.038 | – | 0.40 | 0.19 | 0.17 | 0.334 |
| v5 floor-day | S | 0.887 | 0.00 | 0.00 | 0.72 | 0.67 | 0.258 |
| v5 floor-day | K | 0.723 | 0.00 | 0.00 | 0.64 | 0.60 | 0.199 |

</details>

## The references alone, on the eval packs

No model: each stored reference's mean R, its share at R = 1, its C and how often it beats the anchor; the last column
counts any reference (the anchor included) above P_hind.

| Pack, tier | Anchor's C: mean (p10 to p90) | Reference | R | R = 1 | C | Beats anchor | Above hindsight (any ref) |
|---|---|---|---:|---:|---:|---:|---:|
| v1 foresight (eval 500) | 1.000 (1.00 to 1.00) | clock | 0.485 | 0.00 | 0.341 | 0.00 | 0 |
|  |  | threshold | 0.642 | 0.01 | 0.543 | 0.00 |  |
|  |  | greedy | 0.761 | 0.11 | 0.701 | 0.00 |  |
| v1 blind (eval 300) | 0.901 (0.73 to 1.00) | clock | 0.516 | 0.04 | 0.349 | 0.04 | 0 |
|  |  | persist_dp | 0.957 | 0.71 | 0.852 | 0.00 |  |
|  |  | ridge_dp | 0.861 | 0.36 | 0.747 | 0.00 |  |
| v2 foresight (eval 300) | 0.524 (0.16 to 0.85) | naive | 0.857 | 0.33 | 0.433 | 0.15 | 0 |
|  |  | blind_roll | 0.939 | 0.55 | 0.531 | 0.43 |  |
| v3 reserves (eval 300) | 0.505 (0.20 to 0.80) | v2_energy | 0.786 | 0.00 | 0.369 | 0.00 | 0 |
|  |  | as_hog | 0.492 | 0.00 | 0.198 | 0.00 |  |
|  |  | oneshot_milp | 0.966 | 0.55 | 0.509 | 0.55 |  |
|  |  | energy_only_milp | 0.794 | 0.00 | 0.374 | 0.00 |  |
| v3 energy (eval 300) | 0.438 (0.15 to 0.76) | v2_energy | 0.989 | 0.93 | 0.432 | 0.01 | 0 |
|  |  | oneshot_milp | 0.971 | 0.84 | 0.421 | 0.01 |  |
| v4 front (eval 60) | 0.507 (0.21 to 0.84) | naive | 0.599 | 0.00 | 0.280 | 0.00 | 0 |
|  |  | blind_roll | 0.737 | 0.00 | 0.373 | 0.00 |  |
|  |  | roll3 | 0.974 | 0.57 | 0.503 | 0.57 |  |
| v4 front-lite (eval 60) | 0.431 (0.14 to 0.66) | naive | 0.462 | 0.03 | 0.129 | 0.03 | 0 |
|  |  | blind_roll | 0.961 | 0.48 | 0.452 | 0.48 |  |
|  |  | roll3 | 0.950 | 0.48 | 0.448 | 0.47 |  |
| v5 floor-sprint vs BR_rt (eval 200) | 0.379 (0.11 to 0.75) | price_taker | 0.949 | 0.53 | 0.372 | 0.48 | 0 |
|  |  | max_withhold | 0.199 | 0.00 | -0.002 | 0.00 |  |
|  |  | replay_A | 0.176 | 0.00 | -0.013 | 0.00 |  |
| v5 floor-day vs BR_rt (eval 194) | 0.317 (0.12 to 0.53) | sprint_anchor | 0.791 | 0.16 | 0.241 | 0.16 | 0 |
| v5 floor-sprint vs BR_A (eval 200) | 0.685 (0.34 to 0.95) | price_taker | 0.949 | 0.53 | 0.669 | 0.48 | 0 |
|  |  | max_withhold | 0.199 | 0.00 | -0.003 | 0.00 |  |
|  |  | replay_A | 0.176 | 0.00 | -0.029 | 0.00 |  |
| v5 floor-day vs BR_A (eval 194) | 0.962 (0.65 to 1.30) | sprint_anchor | 0.791 | 0.16 | 0.692 | 0.16 | 70 |

Under C the stored anchor is not always the best stored reference: v2's blind re-planner (0.531 against 0.524), v3's
one-shot MILP (0.509 against 0.505) and v4 front-lite's blind and three-scenario re-planners (0.452 and 0.448
against 0.431) out-capture it. R shows each as a tie at 1 on about half the tasks. A weak anchor is a fact about the
pack that C exposes and R hides.

## Moving the anchor moves R, not C

Sol's R if a stored alternative were the anchor (the anchor's C is unchanged: it is one reference row).

| Column | Anchor | Its C | Sol's R | Sol at R = 1 | Stored anchor's R on it |
|---|---|---:|---:|---:|---:|
| v1 C blind | (stored) | 0.901 | 0.972 | 0.62 | 1.000 |
| v1 C blind | persist_dp | 0.852 | 0.988 | 0.79 | 1.000 |
| v1 C blind | ridge_dp | 0.747 | 0.979 | 0.78 | 1.000 |
| v2 foresight | (stored) | 0.498 | 0.883 | 0.38 | 1.000 |
| v2 foresight | naive | 0.425 | 0.971 | 0.85 | 0.964 |
| v3 reserves | (stored) | 0.480 | 0.811 | 0.20 | 1.000 |
| v3 reserves | energy_only_milp | 0.379 | 0.892 | 0.50 | 1.000 |
| v4 front | (stored) | 0.477 | 0.909 | 0.35 | 1.000 |
| v4 front | blind_roll | 0.346 | 0.979 | 0.75 | 1.000 |
| v4 front | roll3 | 0.475 | 0.909 | 0.45 | 0.976 |
| v4 front-lite | (stored) | 0.450 | 0.883 | 0.50 | 1.000 |
| v4 front-lite | blind_roll | 0.485 | 0.841 | 0.30 | 0.915 |
| v4 front-lite | roll3 | 0.476 | 0.858 | 0.40 | 0.924 |
| v5 floor-sprint | (stored) | 0.414 | 0.801 | 0.43 | 1.000 |
| v5 floor-sprint | price_taker | 0.408 | 0.794 | 0.47 | 0.966 |
| v5 floor-day | (stored) | 0.419 | 0.858 | 0.60 | 1.000 |
| v5 floor-day | price_taker | 0.421 | 0.864 | 0.60 | 0.988 |

An anchor weaker by 0.07 to 0.13 of capture lifts Sol's R by 0.07 to 0.09 in v2 to v4 and its R = 1 share to 50% to
85%.

## Training fitness

Inside: strictly between the scale's floor and its ceiling (a gradient exists). The anchor's SD is the spread an
information-matched policy shows across tasks. At the v1 foresight tier P_hind = P_anchor, so S = R and its
effective ceiling is 1, not 1.2.

| Column | Sol inside R | Sol inside S | Sol inside C [0, 1] | Anchor's SD under R | Anchor's SD under C | Sol's SD under R | Sol's SD under C |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 A foresight | 0.01 | 1.00 | 0.01 | 0.000 | 0.000 | 0.002 | 0.002 |
| v1 C blind | 0.38 | 0.95 | 0.86 | 0.000 | 0.124 | 0.079 | 0.129 |
| v2 foresight | 0.62 | 1.00 | 0.97 | 0.000 | 0.247 | 0.137 | 0.248 |
| v3 reserves | 0.80 | 1.00 | 1.00 | 0.000 | 0.203 | 0.195 | 0.240 |
| v3 energy | 0.20 | 1.00 | 1.00 | 0.000 | 0.200 | 0.001 | 0.199 |
| v4 front | 0.65 | 1.00 | 1.00 | 0.000 | 0.211 | 0.152 | 0.221 |
| v4 front-lite | 0.50 | 1.00 | 1.00 | 0.000 | 0.150 | 0.209 | 0.180 |
| v5 floor-sprint | 0.47 | 0.90 | 0.87 | 0.000 | 0.232 | 0.328 | 0.441 |
| v5 floor-day | 0.40 | 1.00 | 1.00 | 0.000 | 0.158 | 0.239 | 0.260 |

## v5: the compliant score

The profit half on R (as built) and on clip(C, 0, 1) against BR_rt; the welfare half is clip(W/W\*, 0, 1) in both.
Reference rows are the pilot's in-process baselines on the same floors.

| Tier | Profit half | Sol (95% CI) | − anchor (95% CI) | of which profit half | of which welfare half | − price-taker (95% CI) | Anchor | Price-taker | Replay A | Idle |
|---|---|---|---|---:|---:|---|---:|---:|---:|---:|
| floor-sprint | R | 0.550 (0.455 to 0.635) | -0.169 (-0.266 to -0.080) | -0.100 | -0.070 | -0.127 (-0.217 to -0.045) | 0.719 | 0.677 | 0.104 | 0.103 |
| floor-sprint | clip(C, 0, 1) | 0.362 (0.285 to 0.441) | -0.064 (-0.144 to +0.014) | +0.006 | -0.070 | -0.057 (-0.138 to +0.022) | 0.427 | 0.419 | 0.015 | 0.003 |
| floor-sprint | dollars | Sol − anchor: mean $-114,371, median $-5,029, Sol above on 13 of 30 | | | | | | | | |
| floor-day | R | 0.652 (0.542 to 0.756) | -0.148 (-0.244 to -0.065) | -0.071 | -0.077 | -0.143 (-0.239 to -0.060) | 0.800 | 0.795 | 0.733 | 0.102 |
| floor-day | clip(C, 0, 1) | 0.432 (0.304 to 0.566) | -0.078 (-0.155 to -0.009) | -0.000 | -0.077 | -0.079 (-0.155 to -0.012) | 0.510 | 0.511 | 0.478 | 0.002 |
| floor-day | dollars | Sol − anchor: mean $+51,363, median $+11,999, Sol above on 6 of 10 | | | | | | | | |

Edgar's decision holds: the public default is the compliant score. R inside it does not. On floor-day its profit half
puts Sol −0.071 below the anchor while Sol out-earns the anchor on 6 of 10 floors (mean +$51,363), because R pins the
anchor at 1 and clips Sol's gains above it. With clip(C, 0, 1) the profit half reads −0.000 and the score's gap to the
anchor, −0.078 (−0.155 to −0.009), is the welfare half (−0.077), which is what a compliant score is for. Both halves
are then shares of a full-information optimum: W/W\* is welfare's capture (W\* the LP optimum, W_0 the clear with the
batteries idle), C is profit's. On floor-sprint clip(C) floors the four below-idle floors at 0 (R floored three of them); C's
own column shows them. What the switch costs: the published compliant means fall (floor-sprint 0.550 to 0.362,
floor-day 0.652 to 0.432), and floor-sprint's separation from the price-taker, −0.127 (−0.217 to −0.045), becomes
−0.057 (−0.138 to +0.022), because half of it was R's clip.

## Edgar's decisions

- **v2 headline = hindsight capture: holds.** C keeps idle 0 < naive 0.425 < anchor 0.498 < hindsight 1 and separates
  Sol from the anchor, Δ −0.061 (−0.089 to −0.036); R puts 38% of Sol's days and 33% of naive's eval days at 1.
- **v5 public default = compliant: holds,** with C as its profit half (above).
- **R as the training reward: holds up to the anchor.** S is R plus the gradient above it that the v2 contract already
  specifies.

## What changes on the boards

- Every board: the headline is C with the anchor's C and Δ (paired 95% CI); R second with its R = 1 and beats-anchor
  shares; comparisons with any reference on C, never as a difference of R.
- v1: r_opt (0.9165 on the blind column) becomes C (0.896); the foresight columns show C 1.000 and read as solved.
- v3: reserves C 0.397 against the anchor's 0.480, Δ −0.083 (−0.120 to −0.049); energy C 0.483 against 0.484, Δ
  −0.000.
- v4: r_hind (0.566) becomes C (0.458); Δ is the contract's `paired_vs_anchor`.
- v5: C against BR_rt (floor-sprint 0.348 and floor-day 0.419, the anchor 0.414 and 0.419); the compliant score on C;
  `capture_vs_br` stays as the DA-only row.
- `reward_fn` in every version: S; in v5 with BR_rt (BR_A can sit below the anchor, which leaves S undefined).

## Formulas

```
P: the run's settled profit; P_idle, P_anchor, P_hind: the task's stored references; no valid submit: every row 0.
P_hind:     v1 p_opt; v2, v3, v4 p_hind; v5 the tier's p_br_rt.

C         = (P - P_idle) / (P_hind - P_idle)                              headline, unclipped
Delta     = (P - P_anchor) / (P_hind - P_idle)  = C - C_anchor            printed with the headline, paired CI
Delta_ref = (P - P_ref) / (P_hind - P_idle)                               any other comparison
R         = clip(0.2 + 0.8 (P - P_idle) / (P_anchor - P_idle), 0, 1)      second column (degenerate anchor: 1 if
                                                                          P >= P_anchor else 0)
S         = R                                          if P <= P_anchor or P_hind - P_anchor <= 1e-9
          = min(1.2, 1 + 0.2 (P - P_anchor) / (P_hind - P_anchor))  otherwise                       training
v5 compliant = 0.5 clip(C, 0, 1) + 0.5 clip(W/W*, 0, 1),   W/W* = (W - W_0) / (W* - W_0)
```
