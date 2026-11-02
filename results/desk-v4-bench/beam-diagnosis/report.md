# Beam-1.0 on the GridSimEnv desk benchmark: where it loses capture

A diagnosis of Reflection's Beam-1.0 (effort high, in OpenCode 1.17.18) on the 32 windows of the desk-v4-bench, against
the desk's planner on the same windows. The planner is the desk's own optimiser re-planning at every wake, at risk 1.5
with the `spread` DAM position; the files call it the anchor. Every number comes from the bench's own Episode JSONs
(`results/desk-v4-bench/episodes/beam`), replayed in process on the frozen desk code the bench ran, and from the planner
played in process. It ran on a CPU, with no model calls.

**Replay check.** Each episode was replayed call for call on a fresh `Session`. All 32 reproduce the graded P to the
cent (worst |dP| 0.00) and every call's output, except `-0.0` vs `0.0` in a few optimiser COP values. Beam's C as
replayed is 0.0673 [0.0051, 0.1196] (the bench: 0.067 [0.005, 0.120]); the planner's is 0.2094. The gap to explain is
**0.142 C per window**.

C is a fraction here, as in `summary.json`; the dataset card states the same numbers in points (0.142 C is 14.2 points).

## Summary

Beam does not ignore the optimiser and does not garble what it proposes: 97% of the DAM curve hours and >99% of the AS
product-hours it submits are exact copies of the proposal it just got. It loses capture in two places.

1. **It asks the optimiser the wrong question.** 91% of its `optimize` calls leave `dam_position` at the default,
   `physical`, which caps DAM curves at the planned dispatch. 30% of Beam's DAM hours went in at 0 MW and 8% had no
   curve. Its DAM energy awards are a third of the planner's (497 vs 1,471 MWh |award| per window). Beam copies those
   curves faithfully.
2. **It stops re-planning.** Beam optimises at 7 of its 30 wakes per window; the planner optimises at each of its 26.
   Beam ends 18.3 of 25.9 non-reminder wakes per window without a submit. In 21 of 32 windows its last submit is ≥ 24 h
   before the end (median 30 h, at the D1 18:00 adjustment-open wake). RT curves from a proposal reach 12 h ahead, so
   31.5% of all 5-minute intervals (41% on the last day) ran on the DAM curve or ERCOT's proxy curve. The planner: 0%.

Fixing both in the replay recovers 0.140 of the 0.142 gap (98%). AS omissions, refusals, hand edits and COP
`as_capability` caps each move C by less than 0.005, within noise.

## Ranked failures: C lost per cause

C lost = C(counterfactual) − C(reference), mean over 32 windows, with the bench's paired block bootstrap (the 8 fronts as
blocks, 10,000 resamples, seed 0: `paired` in `scripts/desk_bench_results.py`). "Shapley" splits the joint fix of causes
1 and 2 by averaging both orders. Each number is rounded once from the per-window values; `cf_table.md` gives them to
four decimals.

| # | Cause | Counterfactual | ΔC [95% CI] | Windows up / down | Shapley |
|---|---|---|---|---|---|
| 1 | Optimiser question: `physical` DAM basis, risk ≤ 1 | `args_anchor` vs `a_strict` | **+0.115 [+0.007, +0.271]** | 21 / 10 | 0.103 |
| | – `spread` alone | `args_spread` vs `a_strict` | +0.109 [−0.002, +0.271] | 19 / 11 | |
| | – risk 1.5 alone, still physical | `args_risk1.5` vs `a_strict` | +0.001 [−0.011, +0.014] | 16 / 12 | |
| | – without the 01-23 storm front (28 windows) | | +0.046 [−0.008, +0.111] | | |
| 2 | Wakes ended without a submit, incl. two start wakes out of calls | (d) `d_anchor_on_skipped` | **+0.045 [+0.020, +0.074]** | 26 / 6 | 0.037 |
| | – RT curves, RT AS and COP only | `d_anchor_on_skipped_no_dam` | +0.023 [+0.007, +0.039] | 21 / 11 | |
| | – without the storm front | | +0.045 [+0.016, +0.078] | | |
| 1+2 | Both fixed | `args_anchor+d` | +0.140 [+0.030, +0.287] | 23 / 9 | 0.140 |
| 3 | AS offers left out | (b) `b_add_as` | +0.002 [−0.007, +0.013] | 12 / 7 | |
| 4 | Refused submits | (c) `c_repair` | +0.000 | 1 / 0 | |
| – | Fidelity (hand edits) | (a) `a_strict` / `a_merge` | −0.004 [−0.013, +0.006] / −0.002: no loss | 9 / 19 | |
| – | COP `as_capability` caps | (e) | −0.002 [−0.007, +0.001]: no loss | 8 / 2 | |
| ref | The planner on Beam's own wake schedule | | +0.142 [+0.033, +0.289] | 23 / 9 | |

**Confidence.** Cause 2 is solid: its interval excludes zero with or without the storm front, and it helps 26 of 32
windows. Cause 1 is the larger effect but leans on Winter Storm Fern (the 01-23 front, 4 windows, +0.54 to +0.72 C
each). Without that front it is +0.046, with an interval that touches zero.

The setting is not a bench fit. On 48 desk-v4-win **training** windows, which contain no bench day, the planner with
`spread` beats `physical`:
- at risk 1.5 by +0.022 [+0.005, +0.043];
- at risk 1.0 by +0.022 [+0.002, +0.044];
- `physical` at risk 0.5 is worse again (−0.040);
- risk 1.0 vs 1.5 under `spread` is a wash (+0.005 [−0.012, +0.019]).

The start-date blocks overlap, so these intervals are optimistic.

Per-window values: `cf_table.md`, and every graded variant in `cf_beam.jsonl` and `cf_beam_d_no_dam.jsonl`.

## How the counterfactuals are computed

Each variant replays Beam's recorded calls in order at the recorded wakes, changing one thing, and is graded with
`grade(session, task.refs)`. Beam's `set_reminder` calls are kept, so the wake schedule is Beam's; no variant changed a
wake. The per-turn call cap is lifted, so added calls are never refused for budget. The as-played replay is unaffected
by that, because over-budget calls are never logged.

- **(a) Verbatim.** Every submit made after an `optimize` in the same wake is replaced by that proposal's content for the
  same tool and day, exactly as the planner's `_submit_groups` sends it:
  - DAM: `dam_curves` + `dam_as_offers`;
  - RT: `rt_curves` + `rt_as_offers`;
  - COP: the `cop` rows.

  Beam's `optimize` calls are re-run live, so proposals reflect the counterfactual state. `a_strict` drops Beam's
  extras; `a_merge` keeps what the proposal does not cover; `a_strict_stale` also uses an earlier wake's proposal.
- **Arguments.** As `a_strict`, with Beam's `optimize` arguments replaced. All are measured against `a_strict`, to isolate
  the question from the copying.
  - `args_anchor`: the planner's, desk, risk 1.5, spread.
  - `args_spread`: Beam's arguments with spread.
  - `args_risk1.5`: Beam's arguments with risk 1.5.
  - `args_anchor_keep_constraints`: the planner's plus Beam's other constraints. This gives +0.113, so `end_soc_mwh` and
    `max_cycles` are not the issue.
- **(b) AS left out.** Each DAM or RT submit keeps everything Beam sent, and gains the proposal's AS product-hours for
  that day that the call lacks. The proposal is the same wake's, or else a hidden proposal on Beam's latest arguments
  (`planner.propose` directly, no call, no budget). An added product-hour can override an AS offer Beam sent in an
  earlier call.
- **(c) Repair.** A refused `update_cop` has its refused hours clipped and resent at once:
  - COP-02: SoC fields into the site bounds, with MinSOC ≤ HBSOC ≤ MaxSOC;
  - COP-03: HBSOC to the hour-to-hour rate against both neighbours;
  - COP-06: `as_capability` into [0, HSL−LSL].

  Beam's other refusals were gates (EBOC-06), frozen hours (COP-05) or malformed lists (ASO-02/07, EBOC-07): not
  clipping problems. Beam had already repaired 37 of its 43 refusals itself.
- **(d) The planner on skipped wakes.** At each wake Beam ended without any submit call (reminder-only wakes excluded,
  as the planner skips those too), the planner (`policies.anchor`) runs after Beam's calls. `_no_dam` drops the
  planner's DAM submits, which isolates re-planning coverage. A partly planned wake is not filled.
- **(e)** strips `as_capability` from Beam's COP rows.

**Approximations.**
- **Open loop.** Calls a variant does not rewrite are sent as Beam sent them, though Beam chose them after seeing
  different outputs. Examples: COP HBSOC typed for the SoC it had; RT curves it wrote itself or copied. 82 of Beam's 697
  submits had no same-wake proposal.
- **Budget.** In (d) the planner's calls come on top of Beam's in the same wake, which the real 14-call cap would
  sometimes forbid.
- **Overlap.** Causes 1 and 2 overlap (0.115 + 0.045 > 0.140), because (d) also submits `spread` DAM curves at skipped
  DAM-morning wakes; hence the Shapley split.
- **Weighting.** Each window counts equally in C.

## Behaviour in detail

Per-window table: `window_table.md`; the per-window counts behind it and below: `analysis_beam.jsonl`.

**1. Optimiser use.**
- Volume: 268 calls (8.4 per window) at 7.0 wakes per window, against the planner's 830 (25.9 per window, one per
  non-reminder wake). About 1.2 calls per wake, often to compare settings.
- Wake reasons when Beam optimised: checkpoint 137, reminder 92, adjustment-open 73, DAM-morning 54, start 42,
  DAM-results 42, NWS 10, notice 5.
- `dam_position`: physical (the default) in 243 calls (91%); spread in 25, in 6 windows.
- Risk: 1 in 169 calls (63%), 0.5 in 60, 0 in 33, 2 in 6.
- Constraints: `end_soc_mwh` in 255; `max_cycles` in 241 (always equal to the warranty, so no effect); `day` in 96;
  `hours` in 15.
- Malformed price views: 19 calls in 3 windows (`{"source":"desk"}` 13× in 08-18-S02, `{"prices":{...}}` 5×,
  `{"dam_p10":...}` 1×). The tool ignores unknown keys without an error and plans on one desk-P50 path with RT equal to
  DAM.
- No `optimize` call errored.

**2. Fidelity**, against the latest proposal in the same wake. 615 of 697 submits had one; 82 used an earlier wake's.

| Tool | Calls | Copied | Partial | Edited | Own |
|---|---|---|---|---|---|
| DAM | 151 | 111 | 28 | 12 | – |
| RT | 216 | 117 | 41 | 58 | – |
| COP | 330 | 230 | 7 | 92 | 1 |

Per hour or product-hour:
- DAM curves: 2,827 exact of 2,904 compared (75 had price or shape changes, 2 MW changes).
- DAM AS: 3,128 exact of 3,131.
- RT curves: 1,217 exact of 1,259.
- RT AS: 2,224 exact of 2,226.
- COP HBSOC: 5,853 exact of 6,091.

Beam's edits are mostly additions:
- whole-day RT curves sent without a fresh proposal (769 hours in 50 calls);
- its own RT AS offers (465 product-hours);
- COP fields the optimiser does not set (`as_capability` on 3,143 hour-rows, 2,250 entries at 0; `max_soc` 4,594;
  `min_soc` 3,735).

Proposals not submitted in their wake:

| Proposal part | Not submitted | Of |
|---|---|---|
| DAM curves | 37 | 150 |
| DAM AS | 32 | 138 |
| RT curves | 9 | 150 |
| RT AS | 33 | 148 |
| COP | 204 | 457 |

**3. AS offers.** DAM AS offered at the close: 14,125 MWh per window vs the planner's 20,120. Awarded: 6,839 vs 9,408.

| Day | Beam offered (MWh) | Planner offered (MWh) |
|---|---|---|
| D0 | 4,542 | 4,870 |
| D1 | 5,122 | 7,312 |
| D2 | 4,461 | 7,938 |

| Product | Beam offered / window | Planner offered / window | Product-days the planner offers and Beam doesn't |
|---|---|---|---|
| RegUp | 1,774 | 2,605 | 7 of 46 |
| RegDn | 9,012 | 11,954 | 11 of 78 |
| RRS-PFR | 111 | 214 | 7 of 18 |
| RRS-FFR | 1,748 | 3,234 | 14 of 72 |
| ECRS | 676 | 1,031 | 13 of 57 |
| Non-Spin | 802 | 1,081 | 15 of 83 |

- 13 of 96 window-days had no DAM AS at all.
- In real time, Beam's own RT AS offers were in force for 17% of product-intervals (the planner 40%, GPT-6.1 Sol 95%);
  the rest ran on its DAM AS offers (12%) or ERCOT's proxy offers (71%).
- Adding the left-out AS is worth +0.002. The AS gap is a consequence of causes 1 and 2, not a separate failure.

Statement lines against the planner, in C:

| Line | ΔC |
|---|---|
| DAM energy | −0.243 |
| RT energy imbalance | +0.129 |
| DAM AS capacity | −0.034 |
| RT AS imbalance | −0.013 |
| Degradation | +0.017 |

**4. Refusals.**

| Tool | Beam | The planner (same windows) |
|---|---|---|
| DAM | 2/151 (1.3%) | 0% |
| RT | 5/216 (2.3%) | 0% |
| COP | 36/330 (10.9%) | 21.9% (413/1,890: COP-02 390, COP-03 23) |

- Beam's codes: COP-03 15, COP-02 11, COP-05 6, EBOC-06 4, COP-06 4, ASO-02/ASO-07/EBOC-07 1 each.
- Repaired: 37 of 43; 26 in the same wake, median 2 calls and 0 minutes later.
- Unrepaired: 4 frozen hours, 1 COP-03, 1 DAM sent after the close.
- The 14-call cap blocked 21 of Beam's calls in 12 windows: 3 DAM, 7 COP, 9 reminders, 2 checks (from the
  trajectories).
- Instant clip-repair is worth +0.000.

**5. Coverage and timing.**
- **DAM gates.** 8 of 96 window-days had no DAM energy curve at the close:
  - two start wakes ran out of calls before the D0 DAM (04-03-S04, 07-04-S04);
  - one day got nothing (03-16-S01 D2);
  - five got AS-only DAM calls. 19 of Beam's 151 DAM calls carried AS without curves, typically after a `physical`
    proposal of 0 MW curves.

  33% of the DAM hours that had a curve were at 0 MW. The planner: 0 and 0.
- **COP.** Every hour was updated before its freeze (the planner: 1.6 hours per window untouched).
- **Wakes.** 30.0 per window, 25.9 non-reminder. 22.0 ended without a submit (18.3 non-reminder) and 18.2 without any
  call. No-submit wake reasons: checkpoint 240, notice 172, reminder 130, NWS 89, DAM-results 68.
- **Early end.** No episode ended early; all ran to their last scheduled wake and were graded. Beam stops acting
  instead: last submit 23.5 h before the end on average (median 30 h). The longest submit gap inside the operating days
  averages 26.5 h; the planner re-plans at least every 6 h.
- **RT intervals.** 67.5% on an RT curve, 31.5% on the DAM curve, 1.0% on the proxy. By day: D0 76/24/1, D1 70/30/0,
  D2 56/41/2. The planner and GPT-6.1 Sol 100% RT, GLM-5.3 94%.

## Examples

1. **07-04-S02, Fri 07-03 13:19 (DAM results).** Beam calls
   `optimize {"price_view":"desk","risk":1,"constraints":{"end_soc_mwh":47.4}}`.
   - The proposal's D1 DAM curves are 0 MW in every hour (`HE01 [[0,28.95],[0,29.95]]`, …), with RRS-FFR 1,525, ECRS
     474.5 and Non-Spin 703.2 MW-h of AS.
   - At the same moment, the planner's arguments give the same AS and non-zero MW in all 24 hours (−100 to +100 in 17).
   - The projected expected P is $56,434 vs $56,513, so the proposal gives no hint of the difference.
   - Beam copies its proposal exactly.
   - C: Beam 0.148, `args_anchor` 0.249, the planner 0.414.
2. **Same window, D2.** Beam's last submit is Sun 07-05 18:00. It then answers the D2 checkpoints at 00:00, 06:00, 12:00
   and 18:00 with "no action needed". 216 of D2's 288 intervals run on the DAM curve. D2 P is $2,838 vs the planner's
   $10,343. With (d), the window goes 0.148 → 0.253.
3. **Start wakes.**
   - 04-03-S04, Thu 04-02 06:00: 11 reads, an `optimize` and two `check_submission` calls exhaust the 14 calls ("Need
     retry submissions next wake"). The D0 DAM closes empty.
   - 07-04-S04: 10 reads and four `optimize` calls (risk 1 physical, then spread at risk 1, 0 and 2), out of calls again.
   - The same window later sends RT at 17:55 and gets EBOC-06; the RT gate opens at 18:00.
4. **05-08-S01, every DAM day.** The `physical` proposal at the default risk 0.5 gives all-0 MW curves. Beam checks
   curves and AS, then submits the AS only, on D0, D1 and D2 ("DAM energy cleared zero; AS awards are in place"). The
   window has no DAM energy at all (a quiet window: C 0.097 vs the planner 0.079).
5. **08-18-S02.** 13 `optimize` calls with `price_view {"source":"desk"}`. The tool reads that as one P50 path with RT
   equal to DAM, so the curves collapse to the median at any risk. C 0.128 vs the planner 0.464; `args_anchor` gives
   0.481.

## Against GPT-6.1 Sol and GLM-5.3

|  | Beam-1.0 | GPT-6.1 Sol | GLM-5.3 | The planner |
|---|---|---|---|---|
| C | 0.067 | 0.270 | 0.184 | 0.209 |
| optimize / window (wakes with one) | 8.4 (7.0) | 2.8 (2.5) | 4.1 (3.1) | 25.9 |
| Main args | risk 1, physical | risk 0.5–0.7, spread ~45% | risk 0.3–0.5, physical | risk 1.5, spread |
| Submit calls / window | 21.8 | 58.0 | 21.7 | ~103 |
| Verbatim copies (DAM / RT) | 74% / 54% | 0% / 0% | 19% / 8% | 100% |
| DAM \|award\| MWh / window | 497 | 3,675 | 1,862 | 1,471 |
| DAM AS offered MWh / window | 14,125 | 6,705 | 8,161 | 20,120 |
| RT intervals on an RT curve | 67.5% | 100% | 94% | 100% |
| RT AS from own offers | 17% | 95% | 35% | 40% |
| Last submit, h before end | 23.5 | 1.3 | 10.7 | ~0 |
| COP refusals | 10.9% | 3.0% | 16.3% | 21.9% |

- **GPT-6.1 Sol** barely copies the optimiser. It uses it as a reference, writes its own full-range DAM curves (±100,
  ±120 or ±150/160 MW in 97% of its DAM curve groups), beats the planner's DAM energy line by +0.30 C, and re-sends RT
  curves about 28 times a window to the end. It wins even though it offers less AS than the planner (−0.09 C on that
  line).
- **GLM-5.3** works from physical proposals but widens many DAM curves by hand, keeps RT curves 94% in force, and stops
  10.7 h before the end.
- The common thread of the two winners is what Beam lacks: a real DAM position, and RT curves kept live through the
  last day.

## What it would take

Beam reads the desk and follows the planner well. What it lacks is the desk's habits: a `spread` DAM position, and
re-planning to the end of the window. A short playbook or fine-tuning could teach them. No pilot has been run, so
nothing here measures that.

## Files

- `report.md`: this report.
- `cf_table.md`: each counterfactual's mean C, its difference from its reference with the paired block bootstrap, the
  windows it lifts and lowers, and every window's C under every variant.
- `cf_beam.jsonl`, `cf_beam_d_no_dam.jsonl`: one row per window and variant, as graded: C, P, the statement lines, the
  planner's C on the window and the number of submits.
- `window_table.md`: one row per window, Beam against the planner.
- `analysis_beam.jsonl`: one row per window, what Beam's calls held: optimiser use, fidelity to each proposal, AS,
  refusals, coverage and timing.

The replay and counterfactual scripts are not yet published.
