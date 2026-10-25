# GridSimEnv v4 pilot B: pre-registration (GPT-6.1 Sol, Weather Front, rules 4.1)

Committed on `v4-pilot-b` before the first episode of this pilot. Nothing below changes after a run starts, and nothing
is rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs, with this
text left as it is. This pilot re-runs the rules-4.0 pilot (`docs/prereg/v4-pilot.md`, v4-preview befeefe), which stays
on record (V4-P25), on rules 4.1 and the rebuilt packs, with the cross-version reward rule (`docs/REWARD-SCALES.md`,
lane-reward f6eae2d) as its headline. It gives Edgar v4 numbers on 4.1 and the viewer 4.1 replays; it is not the v4
board.

## What changed since the 4.0 pilot
Rules 4.1 (V4-P23..P25): a blank or null `issued_at` is the latest vintage at or before now; every time the env shows is
ISO 8601 CPT with its UTC offset, and a time the agent sends with an offset or `Z` is converted; `front-lite`'s card,
`submit_dam` description and schema are energy-only; an AS field sent as `"keep"` or null is unchanged (V4-P24). The
packs are rebuilt on the same store with solver 2 and each tier's stored anchor calls (V4-P22): eval 60 (40 front / 20
calm, 57 of the 4.0 ids), so P_anchor replays to the cent on every platform. The headline is now hindsight capture C,
not R (below).

## Code
- Branch `v4-pilot-b` at this commit: origin/lane-x4 e304940 (rules 4.1, packs `ercot-front-v4-{eval,rtcb,showcase,
  train}` rebuilt, FORECAST_VERSION 4.1) plus this file, `docs/prereg/v4-pilot-b-tasks.json` and
  `scripts/pilot_v4b.py`. 826 tests pass, ruff clean.
- Every pilot window is an eval or showcase row, which carry their forecast slices inline: no window reads the store.
  All 35 windows are `source: ercot` (ERCOT's own load, wind and solar vintages, V4-P17); the price guide is the desk's.
- Env `gridsim-forecast` (gateway, one trigger per watch, virtual clock frozen at each watch), verifier
  `gridsim-forecast-verifier`, agent `gridsim-llm`, on one EC2 box (c7i.8xlarge, x86_64, Ubuntu 24.04, local Docker)
  shared with two other lanes: this pilot has its own checkout, venv, agent-env state root, registry prefix and unit
  names, and its sweep processes run under a 10-vCPU quota. `agent-env gridsim setup --agent --platform linux/amd64`
  built the env image from this branch on the box (rules 4.1 checked inside the image) and registered the env and
  gridsim-llm v1 there.
- Checks on the box before any episode, at e304940 (the code this commit runs): `scripts/forecast_e2e.py` (the
  anchor's stored calls through Docker with a scripted fake model, zero spend) on the eval windows 2025-03-04 LZ_RAYBN
  and 2025-05-03 LZ_HOUSTON at `front`, 2025-10-20 LZ_SOUTH at `front-lite` and fern-0124 at `front`, each required to
  score R 1.0 at the stored P_anchor to the cent with no problems; and every pilot window's stored P_anchor (replayed),
  P_blind, P_roll3, P_naive (re-solved, solver 2) and P_idle played in process against the row. Results under
  "Checks".

## Model and settings
- One model: GPT-6.1 Sol (`openai/gpt-6.1-sol`) through LiteLLM, reasoning effort `high`, agent `gridsim-llm` on the
  v4 desk card (`gridsim_core.forecast_prompt`, rules 4.1), 16,384 output tokens a turn, turns per V4-P10 (`front`
  122, `front-lite` 72), 14,400 s play limit, 3 planning calls and 6 forecast calls a watch, 3 DAM submits a gate, 1 h
  freeze. As the 4.0 pilot.
- One run per window. An attempt that fails for infrastructure is retried by the sweep at most twice (three attempts in
  all); every attempt is kept in results.jsonl and counted in the spend. A run stopped at its cost cap or refused by the
  provider is final and unscored. No amendment sweeps.

## Budget and the smoke
- Total cap $30 for everything below, smoke included.
- **Smoke** (`v4b-pilot-sol-smoke`): the three smoke windows at `front`, episode cap $3, `--cap-usd 9`, parallel 3. Let
  s be its spend and m the median priced cost of its three final attempts.
- **Stop rule:** if any smoke run ends at its cap, or s + 22 m + 10 × 0.6 m > $30 (the main column and the two display
  windows at m, the front-lite column at 0.6 m), nothing else runs and the pilot stops for a decision.
- **Episode cap** E = max($1, 4 m rounded up to the cent) for every later sweep (`--episode-cap-usd`).
- **Main sweeps**, run at the same time: `v4b-pilot-sol` (20 windows, `front`) with `--cap-usd` (30 − s − 2E) × 20/26
  and `v4b-pilot-sol-lite` (10 windows, `front-lite`) with (30 − s − 2E) × 6/26, each rounded down to the cent; parallel
  5 and 3. If a main sweep stops at its cap with runs not final, it is resumed once, after both have stopped, with its
  cap raised to its own spend plus (30 − total spend − 2E).
- **Display** (`v4b-pilot-sol-show`): fern-0124 and heather-0114 at `front`, after the main sweeps, `--cap-usd` 30 −
  total spend, parallel 2.

## Tasks
Windows of the rebuilt `ercot-front-v4-eval` (d1 2025-01-01..2025-10-29, all `source: ercot`), redrawn by the
unchanged `scripts/pilot_v4_tasks.py` (seed 4324): one seeded draw in slots, each slot a column and a label in a fixed
order (main 14 front / 6 calm, then front-lite 7 / 3, then smoke 2 / 1, calm slots spread evenly); a slot takes the
window of its label, not drawn yet, on a d1 the draw hasn't used, whose settlement point and then month its column has
drawn least, then the point and month the whole draw has drawn least, ties broken by the seeded shuffle. The main column
covers all 13 settlement points and 10 months; all 33 picks have distinct d1. The rebuilt pack's labels and ids move the
draw: 11 of the 20 main windows, 4 of the 10 front-lite and 0 of the 3 smoke are the 4.0 pilot's (16, 7 and 2 are in
some 4.0 column); the display windows are the same. The list and its references are in
`docs/prereg/v4-pilot-b-tasks.json`.

Known before any run (stored references on these windows; C = (P − P_idle)/(P_hind − P_idle), R on the anchor scale):
- Main column: the anchor's C 0.496, P_roll3 0.494, P_blind 0.375, P_naive 0.270; on R, P_blind 0.762, P_naive
  0.612, P_roll3 0.973 (at 1.0 on 11 of 20). Front windows (14): anchor C 0.424, P_blind 0.296; calm (6): anchor C
  0.662, P_blind 0.560. Median P_anchor − P_idle $54,238. P_blind is below R 0.99 on all 20.
- Front-lite column: anchor C 0.402, P_roll3 0.420, P_blind 0.390, P_naive 0.107; on R, P_blind 0.930 (at 0.99 or more
  on 6 of 10), P_roll3 0.944, P_naive 0.457. Median P_anchor − P_idle $17,228.
- Smoke: anchor C 0.464, P_blind 0.363. Display: Fern anchor C 0.603, P_blind 0.356, P_anchor − P_idle $913,792;
  Heather anchor C 0.768, P_blind 0.664, $1,548,294.

```
python scripts/pilot_v4_tasks.py main --json docs/prereg/v4-pilot-b-tasks.json
agent-env gridsim sweep run --env gridsim-forecast --name v4b-pilot-sol-smoke --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front --tasks "$(python scripts/pilot_v4_tasks.py smoke)" \
  --episode-cap-usd 3 --cap-usd 9 --parallel 3
agent-env gridsim sweep run --env gridsim-forecast --name v4b-pilot-sol --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front --tasks "$(python scripts/pilot_v4_tasks.py main)" \
  --episode-cap-usd E --cap-usd "(30 - s - 2E) x 20/26" --parallel 5
agent-env gridsim sweep run --env gridsim-forecast --name v4b-pilot-sol-lite --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-eval --tier front-lite --tasks "$(python scripts/pilot_v4_tasks.py lite)" \
  --episode-cap-usd E --cap-usd "(30 - s - 2E) x 6/26" --parallel 3
agent-env gridsim sweep run --env gridsim-forecast --name v4b-pilot-sol-show --models openai/gpt-6.1-sol \
  --pack ercot-front-v4-showcase --tier front --tasks "$(python scripts/pilot_v4_tasks.py display)" \
  --episode-cap-usd E --cap-usd "30 - spend" --parallel 2
agent-env gridsim episodes v4b-pilot-sol-smoke v4b-pilot-sol v4b-pilot-sol-lite v4b-pilot-sol-show
agent-env gridsim sweep report v4b-pilot-sol v4b-pilot-sol-lite --card results/eval-v4b.json --board results/board-v4b.md
python scripts/pilot_v4b.py v4b-pilot-sol --lite v4b-pilot-sol-lite --smoke v4b-pilot-sol-smoke \
  --display v4b-pilot-sol-show --json results/pilot-v4b.json
```

Main column (`front` tier, scored):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | Anchor C | P_naive C | P_blind C | P_roll3 C | P_blind R | P_roll3 R |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `front-v4-2025-03-04-LZ_RAYBN-pv150-r80-1h-poi180` | front | LZ_RAYBN | 2025-03-04 | 20 | 5 | no | 57,545 | 0.540 | 0.376 | 0.297 | 0.529 | 0.639 | 0.984 |
| 2 | `front-v4-2025-07-19-LZ_LCRA-pv200-r80-2h-poi240` | calm | LZ_LCRA | 2025-07-19 | 17 | 0 | no | 67,031 | 0.813 | 0.507 | 0.760 | 0.793 | 0.948 | 0.981 |
| 3 | `front-v4-2025-08-03-HB_SOUTH-pv200-r40-1h-poi200` | front | HB_SOUTH | 2025-08-03 | 18 | 2 | no | 60,227 | 0.871 | 0.714 | 0.680 | 0.857 | 0.825 | 0.988 |
| 4 | `front-v4-2025-04-30-LZ_AEN-pv150-b100x2h-poi150` | front | LZ_AEN | 2025-04-30 | 20 | 0 | yes | 56,156 | 0.324 | 0.030 | 0.217 | 0.261 | 0.736 | 0.844 |
| 5 | `front-v4-2025-01-21-HB_WEST-pv150-b100x2h-poi150` | calm | HB_WEST | 2025-01-21 | 20 | 2 | no | 111,290 | 0.597 | 0.376 | 0.521 | 0.515 | 0.899 | 0.890 |
| 6 | `front-v4-2025-05-03-LZ_HOUSTON-pv150-b100x2h-poi150` | front | LZ_HOUSTON | 2025-05-03 | 20 | 0 | yes | 34,895 | 0.565 | 0.082 | 0.469 | 0.566 | 0.864 | 1.000 |
| 7 | `front-v4-2025-10-24-HB_PAN-pv150-b100x2h-poi150` | front | HB_PAN | 2025-10-24 | 20 | 0 | no | 17,591 | 0.171 | 0.092 | 0.061 | 0.182 | 0.484 | 1.000 |
| 8 | `front-v4-2025-06-15-HB_HOUSTON-pv150-b100x2h-poi150` | front | HB_HOUSTON | 2025-06-15 | 16 | 0 | yes | 26,172 | 0.342 | 0.060 | 0.268 | 0.341 | 0.828 | 0.999 |
| 9 | `front-v4-2025-02-24-LZ_WEST-pv150-b100x2h-poi150` | calm | LZ_WEST | 2025-02-24 | 20 | 3 | yes | 52,221 | 0.445 | 0.429 | 0.357 | 0.482 | 0.841 | 1.000 |
| 10 | `front-v4-2025-01-01-LZ_NORTH-pv150-r40-2h-poi150` | front | LZ_NORTH | 2025-01-01 | 19 | 1 | yes | 8,147 | 0.275 | 0.103 | 0.203 | 0.248 | 0.790 | 0.921 |
| 11 | `front-v4-2025-03-29-LZ_SOUTH-pv200-r80-2h-poi240` | front | LZ_SOUTH | 2025-03-29 | 19 | 0 | yes | 38,079 | 0.246 | 0.101 | 0.072 | 0.247 | 0.433 | 1.000 |
| 12 | `front-v4-2025-10-14-HB_NORTH-pv300-r40-1h-poi300` | calm | HB_NORTH | 2025-10-14 | 18 | 0 | no | 79,497 | 0.885 | 0.517 | 0.697 | 0.882 | 0.830 | 0.998 |
| 13 | `front-v4-2025-09-25-LZ_HOUSTON-pv150-b100x2h-poi150` | front | LZ_HOUSTON | 2025-09-25 | 18 | 0 | no | 20,738 | 0.299 | 0.184 | 0.207 | 0.307 | 0.754 | 1.000 |
| 14 | `front-v4-2025-07-30-LZ_LCRA-pv100-r40-1h-poi100` | front | LZ_LCRA | 2025-07-30 | 20 | 0 | no | 67,776 | 0.678 | 0.229 | 0.616 | 0.682 | 0.928 | 1.000 |
| 15 | `front-v4-2025-08-16-LZ_CPS-pv150-r40-2h-poi150` | calm | LZ_CPS | 2025-08-16 | 19 | 0 | no | 83,892 | 0.662 | 0.476 | 0.551 | 0.689 | 0.866 | 1.000 |
| 16 | `front-v4-2025-04-02-LZ_RAYBN-pv200-r67-2h-poi200` | front | LZ_RAYBN | 2025-04-02 | 21 | 4 | yes | 53,096 | 0.355 | 0.074 | 0.235 | 0.295 | 0.731 | 0.864 |
| 17 | `front-v4-2025-05-04-LZ_NORTH-pv200-r67-2h-poi200` | front | LZ_NORTH | 2025-05-04 | 19 | 0 | yes | 59,098 | 0.587 | 0.153 | 0.525 | 0.615 | 0.915 | 1.000 |
| 18 | `front-v4-2025-06-28-HB_PAN-pv150-r40-2h-poi150` | front | HB_PAN | 2025-06-28 | 18 | 0 | no | 15,911 | 0.351 | 0.127 | 0.255 | 0.371 | 0.782 | 1.000 |
| 19 | `front-v4-2025-09-01-LZ_WEST-pv150-b100x2h-poi180` | calm | LZ_WEST | 2025-09-01 | 17 | 0 | no | 52,992 | 0.572 | 0.456 | 0.475 | 0.638 | 0.865 | 1.000 |
| 20 | `front-v4-2025-03-03-LZ_AEN-pv300-r80-1h-poi360` | front | LZ_AEN | 2025-03-03 | 19 | 5 | no | 55,380 | 0.337 | 0.316 | 0.039 | 0.377 | 0.293 | 1.000 |

Secondary column (`front-lite` tier, reported apart, never pooled):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | Anchor C | P_naive C | P_blind C | P_roll3 C | P_blind R | P_roll3 R |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `front-v4-2025-01-28-HB_WEST-pv150-b100x2h-poi150` | front | HB_WEST | 2025-01-28 | 12 | 0 | no | 15,049 | 0.370 | 0.224 | 0.380 | 0.232 | 1.000 | 0.703 |
| 2 | `front-v4-2025-07-05-HB_HOUSTON-pv150-b100x2h-poi180` | calm | HB_HOUSTON | 2025-07-05 | 11 | 0 | no | 6,786 | 0.308 | 0.203 | 0.302 | 0.453 | 0.984 | 1.000 |
| 3 | `front-v4-2025-08-02-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2025-08-02 | 13 | 0 | no | 20,329 | 0.651 | 0.306 | 0.662 | 0.639 | 1.000 | 0.985 |
| 4 | `front-v4-2025-10-20-LZ_SOUTH-pv150-b100x2h-poi150` | front | LZ_SOUTH | 2025-10-20 | 14 | 0 | no | 27,797 | 0.321 | 0.168 | 0.178 | 0.317 | 0.642 | 0.989 |
| 5 | `front-v4-2025-04-22-HB_SOUTH-pv150-r80-2h-poi150` | calm | HB_SOUTH | 2025-04-22 | 13 | 0 | yes | 20,888 | 0.470 | 0.255 | 0.482 | 0.522 | 1.000 | 1.000 |
| 6 | `front-v4-2025-02-19-LZ_HOUSTON-pv300-r40-1h-poi300` | front | LZ_HOUSTON | 2025-02-19 | 13 | 8 | yes | 49,353 | 0.257 | -0.242 | 0.332 | 0.494 | 1.000 | 1.000 |
| 7 | `front-v4-2025-05-05-LZ_NORTH-pv200-r40-2h-poi200` | front | LZ_NORTH | 2025-05-05 | 13 | 0 | yes | 6,229 | 0.217 | 0.115 | 0.325 | 0.231 | 1.000 | 1.000 |
| 8 | `front-v4-2025-06-10-LZ_LCRA-pv150-b100x2h-poi180` | front | LZ_LCRA | 2025-06-10 | 14 | 0 | no | 19,407 | 0.370 | 0.021 | 0.287 | 0.275 | 0.820 | 0.794 |
| 9 | `front-v4-2025-04-27-LZ_AEN-pv200-r40-2h-poi200` | calm | LZ_AEN | 2025-04-27 | 13 | 0 | no | 13,047 | 0.527 | 0.172 | 0.525 | 0.519 | 0.998 | 0.988 |
| 10 | `front-v4-2025-02-15-LZ_RAYBN-pv200-r40-2h-poi200` | front | LZ_RAYBN | 2025-02-15 | 14 | 5 | no | 7,987 | 0.529 | -0.156 | 0.431 | 0.516 | 0.853 | 0.981 |

Smoke (`front` tier, for the budget; one line each, never pooled):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | Anchor C | P_naive C | P_blind C | P_roll3 C | P_blind R | P_roll3 R |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `front-v4-2025-01-17-LZ_WEST-pv150-b100x2h-poi180` | front | LZ_WEST | 2025-01-17 | 19 | 5 | no | 44,532 | 0.375 | 0.297 | 0.250 | 0.437 | 0.733 | 1.000 |
| 2 | `front-v4-2025-07-17-HB_NORTH-pv150-r40-1h-poi150` | calm | HB_NORTH | 2025-07-17 | 16 | 0 | no | 29,049 | 0.830 | 0.668 | 0.761 | 0.832 | 0.933 | 1.000 |
| 3 | `front-v4-2025-10-21-HB_WEST-pv150-b100x2h-poi150` | front | HB_WEST | 2025-10-21 | 20 | 0 | no | 24,716 | 0.185 | 0.058 | 0.078 | 0.160 | 0.537 | 0.894 |

Display only (`front` tier, pack `ercot-front-v4-showcase`, never counted):

| # | Window | Label | Point | d1 | Watches | Notices | DF bust | Anchor − idle ($) | Anchor C | P_naive C | P_blind C | P_roll3 C | P_blind R | P_roll3 R |
|---:|---|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | `front-v4-2026-01-24-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2026-01-24 | 21 | 6 | yes | 913,792 | 0.603 | 0.042 | 0.356 | 0.491 | 0.673 | 0.851 |
| 2 | `front-v4-2024-01-14-HB_NORTH-pv150-b100x2h-poi150` | front | HB_NORTH | 2024-01-14 | 24 | 12 | yes | 1,548,294 | 0.768 | 0.210 | 0.664 | 0.759 | 0.892 | 0.991 |

## Metrics
Computed by `scripts/pilot_v4b.py` (committed here; it reads every per-window field of `scripts/pilot_v4.py`,
unchanged) from the replay-verified Episode JSON v4 (`agent-env gridsim episodes`), results.jsonl and the transcripts:
the main column over its 20 windows and by label, the front-lite column on its own, the smoke and display windows one
line each. CIs are 95% bootstrap over windows (10,000 resamples, seed 0), paired where a difference is shown; front
minus calm resamples within each label.
- **Primary: hindsight capture C** = (P − P_idle)/(P_hind − P_idle), unclipped, the mean over the scored main windows
  with its CI, printed beside the anchor's C on the same windows and **Δ = C − C_anchor** (the episode's
  `paired_vs_anchor`) with its paired CI; the counts at C ≥ 1 and below 0. A sensitivity line counts each
  model-caused unscored window (cost cap, provider refusal) as C = 0 (Δ = −C_anchor).
- **Secondary: R** on the anchor scale, clip(0.2 + 0.8(P − P_idle)/(P_anchor − P_idle), 0, 1) (no accepted hour in any
  `submit_dam` or `commit_schedule` scores 0), with its CI, its R = 1 share and the beats-anchor share (P > P_anchor at
  6 decimals). R is a level, never differenced.
- **References on the same windows:** P_blind, P_roll3 and P_naive as stored, each as its C and as Sol's
  (P − P_ref)/(P_hind − P_idle) with its paired CI, the share of windows Sol out-earns it, and its stored R.
- **By label** (front, calm): n, C, the anchor's C, Δ with its CI, P_blind's C and C − P_blind's C with its CI, R;
  front minus calm of Δ with its CI.
- **The 4.0 friction:** forecast calls sending `issued_at` blank or null (refused as malformed in 4.0, the latest vintage
  in 4.1); forecast calls refused for a malformed time (`issued_at` or `target_hour`); forecast calls refused as issued
  after now (4.0's UTC clock time read as CPT); times sent with a UTC offset or `Z`; zone names refused; at `front-lite`,
  hours refused because the tier trades energy only (`not_offered`); plan rows refused at parse. Each as calls (or
  hours) and windows with one.
- **ERCOT's revisions:** `get_forecast_drift` calls a window and the windows with one; kept gates where a drift call was
  served at the gate watch before the first `submit_dam`; of the eligible gates (below), those revised and those with
  a drift read first.
- **As the 4.0 pilot (`scripts/pilot_v4.py`'s tables):** r_hind; forecast reading (`get_forecast` by kind, drift calls,
  refused calls, the share of windows with an ERCOT load, wind or solar call and with a drift call, calls with
  `issued_at`, watches with a forecast call, windows where the forecast budget ran out); DAM gates (missed, submits a
  gate, read before submit, **revision of Sol's own plan at a gate**: for the second and later days a gate is eligible
  when Sol's book for that day as it stood before the gate watch had a non-zero hour and the gate accepted an hour, and
  revised when the accepted DA battery position differs from that book by at least 10% of P in some accepted hour;
  `pv_da_share` below 1; gate nudges); play (refusals, FTP, governor hours, end short, AS revenue and commits against
  the anchor's, the re-plan rate, finished by the agent's own `advance`, audit failures, unscored runs and why, turns,
  tokens, $ per episode, wall minutes, spend per sweep).
- **Exploratory, labelled, not a hypothesis:** against the rules-4.0 pilot (its committed Episode JSON,
  `results/runs/v4-pilot-sol{,-lite}`): each column's C, the anchor's C, Δ, R, R = 1 share, the friction counts, the
  windows with a drift call and forecast calls side by side; on the windows both pilots ran, C(4.1) − C(4.0) and
  Δ(4.1) − Δ(4.0) with paired CIs, each pilot on its own pack's references, and how far the anchor's C moved there.
  It mixes the rules change, the redraw and run-to-run noise, so it is read as a description only.

## Hypotheses (main column unless named)
- **Primary reading, Sol against the anchor:** Δ's paired CI above 0 reads "above the anchor", below 0 "below", else
  "level". Expectation, not a bar: level (4.0: −0.019, −0.057 to +0.017).
- **H1, forecasts are worth reading for Sol:** Sol out-earns persistence on the same windows: C − P_blind's C. Supported
  if its paired CI lies above 0, refuted if below, undecided otherwise.
- **H2, the front gap:** front minus calm of Δ is negative. Supported if its CI lies below 0, refuted if above,
  undecided otherwise (14 against 6 windows: a weak test).
- **H3a, Sol reads ERCOT's own forecasts and their revisions:** supported if at least 75% of the main windows have a
  load, wind or solar call and at least 50% have a `get_forecast_drift` call (4.0: 100% and 35%); otherwise not
  supported, with the counts.
- **H3b, Sol revises its DAM position on new forecasts:** supported if at least half of the eligible gates are revised
  (4.0: 12 of 12, of 40 later-day gates); otherwise not supported. The eligible count and the drift-read-first counts
  are reported with it.
- **H4, the DAM gates hold:** Sol misses at most 1 of the 60 main-column gates.
- **H5, the 4.0 friction is gone:** supported if, over the 30 main and front-lite windows, at most 1 window has a
  forecast call refused for a malformed time (4.0: 24 of 30), at most 1 main window has a call refused as issued after
  now (4.0: 10 of 20), and at most 1 front-lite window has an hour refused as `not_offered` (4.0: 8 of 10); otherwise
  not supported, with the counts.
- Expectations, not success bars: main C in 0.40 to 0.55 (4.0: 0.458 on its draw); R in 0.85 to 0.95; Sol above
  P_naive's C.

## Readings for the open v4 decisions (registered before the run)
- **Front-lite as a scored tier:** called saturated for this model if Sol's front-lite R is 0.95 or more; it shows
  forecast value only if C − P_blind's C has a CI above 0 there. Otherwise the 4.0 reading (a training and warm-up tier)
  stands.
- **Anchor scale at `front`:** compressed for this model, by V2-D1's rule, if more than a third of the main windows sit
  at R = 1 (C heads the board either way).
- **The front/calm label (V4-P19) as a stratifier:** kept as a board breakdown if H2 is supported or refuted; called
  uninformative at this size if undecided.
- **Forecast budget (V4-P14):** binding if it ran out at some watch in a quarter or more of the main windows.
- **Turn and watch caps (V4-P10) and the episode cap:** binding if any main run ends by the turn limit or its cost cap.
- **DA PV share (V4-P5):** used if Sol sets `pv_da_share` below 1 at a fifth or more of its kept main gates.

## Checks

Done on the box at e304940 before this commit, zero spend:
- `scripts/forecast_e2e.py` through Docker, each R 1.0 at the stored P_anchor to the cent, audit ok, no problems:
  2025-03-04 LZ_RAYBN `front` $84,820.48; 2025-05-03 LZ_HOUSTON `front` $104,537.42; 2025-10-20 LZ_SOUTH `front-lite`
  $27,797.16; fern-0124 `front` $1,039,165.64. The env image reports FORECAST_VERSION 4.1.
- In process, all 35 pilot windows: the anchor's stored calls reproduce P_anchor to the cent with R 1.0 on 35 of 35;
  P_idle, P_blind and P_naive on 35 of 35; P_roll3 on 34 (2025-02-24 LZ_WEST re-solves $0.84 off on Linux x86_64, a
  re-solve tie-break; its stored value is the one reported).

## Deviations

None in the registered rules; one infrastructure event used the retry and resume rules as written. The smoke spent
s = $1.60 (3 scored at the first attempt: $0.687, $0.416, $0.495; m = $0.4954), so the projection was $15.47 and the
pilot went on with E = $1.99, `--cap-usd` 18.78 (main) and 5.63 (front-lite). Around 03:45 to 03:52 UTC the provider
answered six attempts with "Gateway cannot authenticate upstream services" (`provider_error`): four main windows
(2025-01-01 LZ_NORTH, 2025-05-03 LZ_HOUSTON, 2025-06-15 HB_HOUSTON, 2025-02-24 LZ_WEST) and two front-lite ones
(2025-02-19 LZ_HOUSTON, 2025-05-05 LZ_NORTH), after 13 to 41 turns. The sweeps retried each once and all six scored at
the second attempt; the failed attempts' $7.01 counts in the spend. The main sweep finished inside its cap (20 of 20,
$17.04). The front-lite sweep stopped at its cap with 6 scored and 4 not final ($3.78); after both had stopped it was
resumed once, as registered, with `--cap-usd` 7.37 (its $3.78 plus 30 − $22.42 − 2E), and the 4 scored. The display
sweep ran with `--cap-usd` 6.69 (30 − $23.31). Total spend $24.92 of $30 (smoke $1.60, main $17.04, front-lite $4.67,
display $1.61); nothing unscored, no amendment.

Every episode replays byte for byte into Episode JSON v4 on the box (`agent-env gridsim episodes`, 35 written, 0 that
didn't replay) and again through a fresh Session on the laptop, every audit ok. The box ran at 11852c0 with the env
image built at e304940 (11852c0 adds only this file, the task list and `scripts/pilot_v4b.py`). As in the 4.0 pilot,
the 10-vCPU quota bound the sweep processes, not the Docker containers they started. `scripts/pilot_v4b.py` is
unchanged since this file's commit; `agent-env gridsim sweep report v4b-pilot-sol v4b-pilot-sol-lite --card
results/eval-v4b.json --board results/board-v4b.md` wrote the card and board, and the Pilot and Reading sections were
added below the generated board. Results: `results/board-v4b.md`, `results/pilot-v4b.json`, the Episode JSON under
`results/runs/v4b-pilot-sol*/`.
