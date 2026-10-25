# Reward scales across GridSim versions

Which number heads each version's board, which sits beside it, and which one trains. The evidence is GPT-6.1 Sol's
committed runs (the v1 board's 1,550 and the v2 to v5 pilots' 150) with every reference stored on the same tasks, and
the references alone on the full eval packs. `scripts/reward_scales.py` regenerates every table below from committed
files (Episode JSON, `results/pilot-v5b.json`, the packs' rows as the pilots played them, at b5edf82); it spends
nothing. CIs are 95% percentile bootstrap over tasks (10,000 resamples), paired for differences. The rule was adopted
on the rules-3.0/4.0/5.0 pilots; the v3 to v5 evidence below is regenerated on the rules-3.1/4.1/5.1 re-pilots
(`results/board-v3b.md`, `board-v4b.md`, `board-v5b.md`) and their packs. v1 and v2 did not change.

**Adopted** by Edgar on 2026-10-25, as the rule below, and applied wherever results are reported: `agent-env gridsim
sweep report` (every `results/eval-v*.json` card and board), the dataset card and the Space; training reads S
(`grade.stretch_value`, `grade()["stretch_reward"]` in the v2 to v5 Sessions, v5's `reward_fn`). The contract text is
[CONTRACT.md, Scoring across versions](CONTRACT.md#scoring-across-versions-adopted).

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
   below on 113) and Δ is −0.005 (−0.019 to +0.009); v4 front-lite −0.127 (−0.234 to −0.039) against Δ −0.040
   (−0.090 to +0.008); v5 floor-day −0.103 (−0.228 to +0.000), while Sol out-earns the anchor on 7 of 10 floors (mean
   +$169,795, median +$40,484) and Δ is +0.120 (−0.015 to +0.248). On the re-pilot v4 front is below on both, R
   −0.089 (−0.142 to −0.044) and Δ −0.032 (−0.065 to −0.001); at rules 4.0 it was this finding's example (R −0.091,
   Δ level). The same clip biases R against whichever of two policies passes the anchor more often: on floor-sprint R
   puts Sol −0.234 (−0.408 to −0.063) below the price-taker where C reads −0.101 (−0.261 to +0.054), and on floor-day
   −0.083 (−0.208 to +0.017) where C reads +0.129 (−0.005 to +0.260) and Sol out-earns the price-taker on 7 of 10
   floors.
2. **R = 1 is a tie class, not a top score.** Sol sits at R = 1 on 20% to 70% of v2 to v5 tasks. Ordinary stored
   references reach it on about half of each eval pack: the v5 price-taker on 53% of 289 floors, v4's three-scenario
   re-planner on 53% of 60 windows, v3's one-shot MILP on 60% of 300 days, v2's blind re-planner on 55% of 276. No v2
   to v5 run reaches C = 1 or exceeds P_hind. One stored reference did at rules 3.1 (none at 3.0): on the v3 eval
   pack the reserves anchor settled $1,651 above P_hind on 2025-06-28 LZ_AEN (below); rules 3.2 fixed the cause
   (CONTRACT-v3 C3-D19, C3-D20), and no stored v3 reference exceeds P_hind now.
3. **R = 1 is a different share of the attainable in every version.** The anchor's own capture on the eval packs is
   1.00 (v1 foresight), 0.90 (v1 blind), 0.52 (v2), 0.52 and 0.47 (v3 reserves, energy), 0.51 and 0.43 (v4 front,
   front-lite), 0.40 and 0.34 (v5 floor-sprint, floor-day, against BR_rt). C is one scale across versions; R is not.
4. **C is not a training reward.** The information-matched anchor scores exactly 1 on every task under R; under C
   its score spreads with SD 0.13 to 0.26 across v2 to v5 tasks, as much as Sol's own spread (0.16 to 0.27; v5
   floor-sprint 0.49). That is task noise no policy can remove. R keeps it out, and S adds the gradient R lacks above
   the anchor: on v1 blind and v2 to v5, Sol's runs sit strictly inside R on 30% to 80% of tasks and inside S on 95%
   to 100% (v5 floor-sprint 77%: its seven floors below idle sit at 0 on both).

## What P_hind is

| Version | P_hind | Kind | Exceeded by a run or reference | LP bound |
|---|---|---|---|---|
| v1 | P_opt, the exact DP on D's prices | an achievable plan (the foresight tier plays it) | never | P_lp = P_opt on every day |
| v2 | two exact DPs: the DA position on DA − RT, the physical schedule on RT | an achievable clairvoyant plan | never | P_lp above it on 2 of 40 pilot days (max $801) |
| v3 | the hindsight MILP: a DA copy and a physical copy on realised RT, drift and deployments, sharing the AS book | the exact optimum of a clairvoyant model, not a playable plan | by no run; at rules 3.1 by one stored reference, the reserves anchor on 2025-06-28 LZ_AEN, $53,542 against P_hind's $51,890 (P_lp equals P_hind there), 1 of 300 eval days; at rules 3.2 the Session charges every shortfall and P_hind is the clairvoyant optimum of that settlement (CONTRACT-v3 C3-D19, C3-D20), and no stored reference exceeds it | P_lp above it on 8 of 40 pilot days (max $2,863) |
| v4 | v3's hindsight over the window | as v3 | never | P_lp above it on 4 of 30 (max $345) |
| v5 | BR_A (`p_br`): the DA-clear best response, awards delivered as awarded | **not a bound**: the floor-day anchor exceeds it on 102 of 284 eval floors, Sol on 11 of 40 runs; Sol's floor-sprint C against it reaches −2.8 | yes | – |
| v5 | BR_rt (`p_br_rt`): the same with deviations settled at realised RT | the clairvoyant bound of the same settlement | never | – |

v5's C uses BR_rt: it is the object v2 to v4 call P_hind (a DA position plus physical delivery on realised RT), nothing
exceeds it, and the anchor's capture against it (0.40, 0.34) sits with v2 to v4's (0.43 to 0.52). BR_A stays as the
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
| v3 reserves | 30 | 0.845 (0.757 to 0.918) | 0.30 | 0.451 (0.365 to 0.534) | 0.00 | 1 | 0.505 | -0.054 (-0.092 to -0.019) | -0.155 (-0.244 to -0.082) | energy_only_milp | +0.048 (+0.008 to +0.092) | +0.032 (-0.030 to +0.089) |
| v3 energy | 10 | 0.990 (0.969 to 1.000) | 0.40 | 0.427 (0.273 to 0.587) | 0.00 | 0 | 0.426 | +0.001 (-0.009 to +0.010) | -0.010 (-0.031 to -0.000) | v2_energy | +0.086 (+0.011 to +0.209) | +0.123 (+0.022 to +0.248) |
| v4 front | 20 | 0.911 (0.859 to 0.955) | 0.35 | 0.463 (0.373 to 0.552) | 0.00 | 0 | 0.496 | -0.032 (-0.065 to -0.001) | -0.089 (-0.142 to -0.044) | roll3 | -0.031 (-0.058 to -0.004) | -0.063 (-0.100 to -0.029) |
| v4 front-lite | 10 | 0.873 (0.769 to 0.961) | 0.20 | 0.362 (0.266 to 0.461) | 0.00 | 0 | 0.402 | -0.040 (-0.090 to +0.008) | -0.127 (-0.234 to -0.039) | roll3 | -0.058 (-0.146 to +0.005) | -0.071 (-0.185 to +0.016) |
| v5 floor-sprint | 30 | 0.696 (0.545 to 0.834) | 0.40 | 0.296 (0.116 to 0.468) | 0.00 | 7 | 0.419 | -0.123 (-0.275 to +0.021) | -0.304 (-0.457 to -0.163) | price_taker | -0.101 (-0.261 to +0.054) | -0.234 (-0.408 to -0.063) |
| v5 floor-day | 10 | 0.897 (0.776 to 1.000) | 0.70 | 0.566 (0.399 to 0.734) | 0.00 | 0 | 0.446 | +0.120 (-0.015 to +0.248) | -0.103 (-0.228 to +0.000) | price_taker | +0.129 (-0.005 to +0.260) | -0.083 (-0.208 to +0.017) |

C's unpaired CI is wider than R's (v2: 0.153 against 0.085) because it carries each task's information headroom; the
paired Δ removes it (v2 0.053, v3 0.072, v4 0.064), which is why C is never printed without Δ.

## The candidates

| Scale | Formula | Reading |
|---|---|---|
| (a) R | clip(0.2 + 0.8·(P − P_idle)/(P_anchor − P_idle), 0, 1) | Bounded, information-matched, no task noise at the anchor: right for training up to the anchor. On the board it saturates, is one-sided against the anchor, moves with the anchor and changes meaning across versions. **Second column.** |
| (b) C | (P − P_idle)/(P_hind − P_idle) | No ceiling where P_hind is a bound (no v2 to v5 run at 1); keeps idle 0 < rule-based heuristics < anchor < hindsight 1 on every pack and shows the three packs where another stored re-planner out-captures the anchor; independent of the anchor; one scale across versions; below 0 on 10 of 1,700 runs (min −0.83). Wide unpaired CI and task noise, so it heads the board with Δ and does not train. **Headline.** |
| (c) Δ | (P − P_anchor)/(P_hind − P_idle) = C − C_anchor | Two-sided, the tightest paired CI: the comparison printed with the headline (v4's `paired_vs_anchor`). Not a headline alone: its zero is the anchor. |
| (d1) Rh | clip(0.2 + 0.8·C, 0, 1), v1's r_opt and v4's r_hind | An affine copy of C with the same z, plus a floor at C = −0.25 that hides losses (v5 floor-sprint: 13% of floors at 0; z against the anchor 0.60 against C's 0.83). The boards print three hindsight numbers today: Rh (v1's r_opt, v4's r_hind), C (v2, v3, v4's capture) and C against BR_A (v5); C replaces them. |
| (d2) Q | (P − P_anchor)/(P_hind − P_anchor) | Undefined where the anchor is the hindsight (v1 foresight), unbounded below (v2 −1.2; v5 against BR_A −14). Used only inside S above the anchor, where it is in [0, 1]. |
| (d3) S | R; above the anchor min(1.2, 1 + 0.2·Q) | R's information matching plus a gradient above the anchor (no v2 to v5 run at 1.2). A dollar above the anchor still weighs c_a/(4(1 − c_a)) of one below it (a quarter at anchor capture c_a = 0.5), so it is not a board statistic. **Training reward.** |
| (d4) K | 0.2 + 0.6·(P − P_idle)/(P_anchor − P_idle) up to the anchor, then 0.8 + 0.2·Q | No ceiling and keeps the order, but the same kink under-credits play above the anchor (v4 front-lite: −0.090, its CI excluding 0, where Δ is level), and it moves the anchor off 1.0 under every published R. Rejected. |

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
| v3 reserves | R | 0.845 | 0.30 | 0.00 | 1.92 | 0.54 | 0.226 |
| v3 reserves | C | 0.451 | 0.00 | 0.00 | 1.49 | 1.14 | 0.240 |
| v3 reserves | Rh | 0.561 | 0.00 | 0.00 | 1.49 | 1.14 | 0.192 |
| v3 reserves | G | -0.054 | – | 0.70 | 1.49 | 1.14 | 0.101 |
| v3 reserves | Q | -0.104 | – | 0.70 | 1.19 | 1.29 | 0.244 |
| v3 reserves | S | 0.853 | 0.00 | 0.00 | 1.77 | 0.64 | 0.232 |
| v3 reserves | K | 0.691 | 0.00 | 0.00 | 1.72 | 0.67 | 0.176 |
| v3 energy | R | 0.990 | 0.40 | 0.00 | 0.67 | 1.09 | 0.031 |
| v3 energy | C | 0.427 | 0.00 | 0.00 | 0.12 | 0.87 | 0.256 |
| v3 energy | Rh | 0.542 | 0.00 | 0.00 | 0.12 | 0.87 | 0.205 |
| v3 energy | G | 0.001 | – | 0.60 | 0.12 | 0.87 | 0.016 |
| v3 energy | Q | 0.006 | – | 0.60 | 0.31 | 0.72 | 0.033 |
| v3 energy | S | 0.992 | 0.00 | 0.00 | 0.45 | 1.10 | 0.032 |
| v3 energy | K | 0.795 | 0.00 | 0.00 | 0.39 | 1.11 | 0.025 |
| v4 front | R | 0.911 | 0.35 | 0.00 | 1.83 | 1.76 | 0.111 |
| v4 front | C | 0.463 | 0.00 | 0.00 | 1.02 | 1.13 | 0.206 |
| v4 front | Rh | 0.571 | 0.00 | 0.00 | 1.02 | 1.13 | 0.165 |
| v4 front | G | -0.032 | – | 0.65 | 1.02 | 1.13 | 0.072 |
| v4 front | Q | -0.104 | – | 0.65 | 1.37 | 1.38 | 0.171 |
| v4 front | S | 0.916 | 0.00 | 0.00 | 1.65 | 1.70 | 0.116 |
| v4 front | K | 0.738 | 0.00 | 0.00 | 1.60 | 1.67 | 0.088 |
| v4 front-lite | R | 0.873 | 0.20 | 0.00 | 1.30 | 0.70 | 0.157 |
| v4 front-lite | C | 0.362 | 0.00 | 0.00 | 0.82 | 0.77 | 0.160 |
| v4 front-lite | Rh | 0.489 | 0.00 | 0.00 | 0.82 | 0.77 | 0.128 |
| v4 front-lite | G | -0.040 | – | 0.80 | 0.82 | 0.77 | 0.080 |
| v4 front-lite | Q | -0.068 | – | 0.80 | 0.81 | 0.79 | 0.137 |
| v4 front-lite | S | 0.878 | 0.00 | 0.00 | 1.22 | 0.71 | 0.162 |
| v4 front-lite | K | 0.710 | 0.00 | 0.00 | 1.19 | 0.71 | 0.123 |
| v5 floor-sprint | R | 0.696 | 0.40 | 0.23 | 2.07 | 1.36 | 0.408 |
| v5 floor-sprint | C | 0.296 | 0.00 | 0.00 | 0.83 | 0.64 | 0.493 |
| v5 floor-sprint | Rh | 0.482 | 0.00 | 0.13 | 0.60 | 0.37 | 0.312 |
| v5 floor-sprint | G | -0.123 | – | 0.60 | 0.83 | 0.64 | 0.419 |
| v5 floor-sprint | Q | -0.285 | – | 0.60 | 0.97 | 0.83 | 0.837 |
| v5 floor-sprint | S | 0.725 | 0.00 | 0.23 | 1.77 | 1.13 | 0.434 |
| v5 floor-sprint | K | 0.590 | 0.00 | 0.23 | 1.66 | 1.09 | 0.352 |
| v5 floor-day | R | 0.897 | 0.70 | 0.00 | 0.91 | 0.74 | 0.179 |
| v5 floor-day | C | 0.566 | 0.00 | 0.00 | 0.92 | 0.97 | 0.274 |
| v5 floor-day | Rh | 0.653 | 0.00 | 0.00 | 0.92 | 0.97 | 0.219 |
| v5 floor-day | G | 0.120 | – | 0.30 | 0.92 | 0.97 | 0.212 |
| v5 floor-day | Q | 0.230 | – | 0.30 | 0.83 | 0.95 | 0.444 |
| v5 floor-day | S | 0.964 | 0.00 | 0.00 | 0.26 | 0.13 | 0.223 |
| v5 floor-day | K | 0.790 | 0.00 | 0.00 | 0.09 | 0.03 | 0.180 |

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
| v3 reserves (eval 300) | 0.524 (0.26 to 0.78) | v2_energy | 0.764 | 0.00 | 0.373 | 0.00 | 1 |
|  |  | as_hog | 0.470 | 0.00 | 0.183 | 0.00 |  |
|  |  | oneshot_milp | 0.953 | 0.60 | 0.537 | 0.60 |  |
|  |  | energy_only_milp | 0.801 | 0.00 | 0.398 | 0.00 |  |
| v3 energy (eval 300) | 0.467 (0.18 to 0.78) | v2_energy | 0.953 | 0.69 | 0.438 | 0.02 | 0 |
|  |  | oneshot_milp | 0.968 | 0.80 | 0.450 | 0.01 |  |
| v4 front (eval 60) | 0.511 (0.21 to 0.85) | naive | 0.598 | 0.00 | 0.285 | 0.00 | 0 |
|  |  | blind_roll | 0.738 | 0.00 | 0.377 | 0.00 |  |
|  |  | roll3 | 0.970 | 0.53 | 0.504 | 0.53 |  |
| v4 front-lite (eval 60) | 0.434 (0.22 to 0.66) | naive | 0.472 | 0.03 | 0.134 | 0.03 | 0 |
|  |  | blind_roll | 0.961 | 0.53 | 0.458 | 0.53 |  |
|  |  | roll3 | 0.949 | 0.48 | 0.451 | 0.47 |  |
| v5 floor-sprint vs BR_rt (eval 289) | 0.399 (0.12 to 0.73) | price_taker | 0.937 | 0.53 | 0.390 | 0.44 | 0 |
|  |  | max_withhold | 0.199 | 0.00 | -0.002 | 0.00 |  |
|  |  | replay_A | 0.159 | 0.00 | -0.024 | 0.00 |  |
| v5 floor-day vs BR_rt (eval 284) | 0.341 (0.16 to 0.56) | sprint_anchor | 0.780 | 0.15 | 0.252 | 0.15 | 0 |
| v5 floor-sprint vs BR_A (eval 289) | 0.687 (0.33 to 0.96) | price_taker | 0.937 | 0.53 | 0.669 | 0.44 | 1 |
|  |  | max_withhold | 0.199 | 0.00 | -0.002 | 0.00 |  |
|  |  | replay_A | 0.159 | 0.00 | -0.045 | 0.00 |  |
| v5 floor-day vs BR_A (eval 284) | 0.978 (0.69 to 1.28) | sprint_anchor | 0.780 | 0.15 | 0.689 | 0.15 | 102 |

Under C the stored anchor is not always the best stored reference: v2's blind re-planner (0.531 against 0.524), v3's
one-shot MILP (0.537 against 0.524) and v4 front-lite's blind and three-scenario re-planners (0.458 and 0.451
against 0.434) out-capture it. R shows each as a tie at 1 on about half the tasks. A weak anchor is a fact about the
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
| v3 reserves | (stored) | 0.505 | 0.845 | 0.30 | 1.000 |
| v3 reserves | energy_only_milp | 0.403 | 0.912 | 0.77 | 1.000 |
| v4 front | (stored) | 0.496 | 0.911 | 0.35 | 1.000 |
| v4 front | blind_roll | 0.375 | 0.976 | 0.75 | 1.000 |
| v4 front | roll3 | 0.494 | 0.920 | 0.30 | 0.979 |
| v4 front-lite | (stored) | 0.402 | 0.873 | 0.20 | 1.000 |
| v4 front-lite | blind_roll | 0.390 | 0.863 | 0.40 | 0.950 |
| v4 front-lite | roll3 | 0.420 | 0.881 | 0.50 | 0.923 |
| v5 floor-sprint | (stored) | 0.419 | 0.696 | 0.40 | 1.000 |
| v5 floor-sprint | price_taker | 0.397 | 0.693 | 0.37 | 0.989 |
| v5 floor-day | (stored) | 0.446 | 0.897 | 0.70 | 1.000 |
| v5 floor-day | price_taker | 0.438 | 0.902 | 0.70 | 0.986 |

An anchor weaker by 0.07 to 0.12 of capture lifts Sol's R by 0.07 to 0.09 in v2 to v4 and its R = 1 share to 75% to
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
| v3 reserves | 0.70 | 1.00 | 0.97 | 0.000 | 0.190 | 0.226 | 0.240 |
| v3 energy | 0.60 | 1.00 | 1.00 | 0.000 | 0.254 | 0.031 | 0.256 |
| v4 front | 0.65 | 1.00 | 1.00 | 0.000 | 0.208 | 0.111 | 0.206 |
| v4 front-lite | 0.80 | 1.00 | 1.00 | 0.000 | 0.131 | 0.157 | 0.160 |
| v5 floor-sprint | 0.37 | 0.77 | 0.77 | 0.000 | 0.262 | 0.408 | 0.493 |
| v5 floor-day | 0.30 | 1.00 | 1.00 | 0.000 | 0.203 | 0.179 | 0.274 |

## v5: the compliant score

The profit half on R (as built) and on clip(C, 0, 1) against BR_rt; the welfare half is clip(W/W\*, 0, 1) in both.
Reference rows are the pilot's in-process baselines on the same floors.

| Tier | Profit half | Sol (95% CI) | − anchor (95% CI) | of which profit half | of which welfare half | − price-taker (95% CI) | Anchor | Price-taker | Replay A | Idle |
|---|---|---|---|---:|---:|---|---:|---:|---:|---:|
| floor-sprint | R | 0.458 (0.362 to 0.547) | -0.243 (-0.329 to -0.163) | -0.152 | -0.091 | -0.200 (-0.301 to -0.102) | 0.700 | 0.658 | 0.106 | 0.106 |
| floor-sprint | clip(C, 0, 1) | 0.308 (0.231 to 0.389) | -0.101 (-0.162 to -0.043) | -0.011 | -0.091 | -0.083 (-0.152 to -0.012) | 0.410 | 0.391 | 0.019 | 0.006 |
| floor-sprint | dollars | Sol − anchor: mean $+33,879, median $-5,731, Sol above on 12 of 30 | | | | | | | | |
| floor-day | R | 0.718 (0.662 to 0.767) | -0.073 (-0.135 to -0.024) | -0.052 | -0.021 | -0.063 (-0.126 to -0.012) | 0.791 | 0.781 | 0.699 | 0.104 |
| floor-day | clip(C, 0, 1) | 0.553 (0.453 to 0.650) | +0.039 (-0.028 to +0.104) | +0.060 | -0.021 | +0.043 (-0.025 to +0.111) | 0.514 | 0.510 | 0.485 | 0.004 |
| floor-day | dollars | Sol − anchor: mean $+169,795, median $+40,484, Sol above on 7 of 10 | | | | | | | | |

Edgar's decision holds: the public default is the compliant score. R inside it does not. On floor-day its profit half
puts Sol −0.052 below the anchor while Sol out-earns the anchor on 7 of 10 floors (mean +$169,795), because R pins the
anchor at 1 and clips Sol's gains above it. With clip(C, 0, 1) the profit half reads +0.060 and the score sits level
with the anchor, +0.039 (−0.028 to +0.104), the welfare half (−0.021) taking back part of the profit half's lead,
which is what a compliant score is for. (At rules 5.0 the profit half read −0.000 and the whole gap, −0.078, was the
welfare half.) Both halves are then shares of a full-information optimum: W/W\* is welfare's capture (W\* the LP
optimum, W_0 the clear with the batteries idle), C is profit's. On floor-sprint clip(C) and R both floor the seven
below-idle floors at 0; C's own column shows them. What the switch costs: the published compliant means fall
(floor-sprint 0.458 to 0.308, floor-day 0.718 to 0.553), and floor-sprint's separation from the price-taker, −0.200
(−0.301 to −0.102), shrinks to −0.083 (−0.152 to −0.012), still below 0: R's clip was 0.117 of it.

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
- v3: reserves C 0.451 against the anchor's 0.505, Δ −0.054 (−0.092 to −0.019); energy C 0.427 against 0.426, Δ
  +0.001.
- v4: r_hind (0.571) becomes C (0.463); Δ is the contract's `paired_vs_anchor`.
- v5: C against BR_rt (floor-sprint 0.296 and floor-day 0.566, the anchor 0.419 and 0.446); the compliant score on C;
  `capture_vs_br` stays as the DA-only row.
- `reward_fn` in every version: S; in v5 with BR_rt (BR_A can sit below the anchor, which leaves S undefined). v1's
  `trl.reward_fn` stays as it is, byte for byte: it trains at the foresight tier, where S = R.

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
