# Beam-1.0 with the desk playbook: results

Pre-registration: `docs/prereg/v4-bench.md` in the plugin, items 64-67 (pushed at d2792d8, before any playbook episode;
exploratory, not part of the leaderboard), Beam-1.0 against its own bench runs on the same 32 desk-v4-bench windows.
Items 68-76 (a4be130) record the run and its deviations. In the files, `beampb` is Beam-1.0 with the playbook and
`beam` its bench run.

The playbook (`bench/harness/bench-opencode-beam-playbook/PLAYBOOK.md`, 46 lines of general desk practice, frozen at
d2792d8, sha256 0dc7cb47...) was written after seeing Beam's failures on these same windows (item 67). This run shows
whether the diagnosed fixes carry over to Beam's own play; it is not performance on unseen windows.

## Headline

- **Beam-1.0 + playbook: C 18.9% [6.0%, 35.8%]**, R 0.739 [0.550, 0.900], over 32 of 32 windows (8 fronts; front-block
  bootstrap, 2026-04-03 aliased to 2026-04-17, 10,000 resamples, seed 0).
- Beam-1.0's own bench run on the same windows: C 6.7% [0.5%, 12.0%]. The desk's planner: mean C 20.9%.
- **Paired dC (playbook - Beam), all 32 windows: +12.2 pp [+1.6 pp, +26.9 pp]**; the playbook run is ahead on 59.4% of
  windows and on 6 of 8 fronts.
- Split C: pre-cutoff 23.6% [2.1%, 54.6%], post-cutoff 14.2% [2.2%, 27.8%].
- Windows missing: 0.

## Paired difference from Beam-1.0's bench run (C, front-block bootstrap)

| Scope | n | fronts | Beam + playbook C | Beam C | dC [95% CI] | windows ahead | fronts ahead |
|---|---|---|---|---|---|---|---|
| All 32 | 32 | 8 | 18.9% [6.0%, 35.8%] | 6.7% [0.5%, 12.0%] | +12.2 pp [+1.6 pp, +26.9 pp] | 59.4% | 6 of 8 |
| July-August (16) | 16 | 4 | 14.2% [2.2%, 27.8%] | 3.0% [-5.9%, 10.9%] | +11.2 pp [+5.5 pp, +19.5 pp] | 68.8% | 4 of 4 |
| Outside the 2026-01-23 front (28) | 28 | 7 | 11.8% [3.6%, 21.3%] | 6.0% [-0.8%, 11.8%] | +5.8 pp [-0.3 pp, +12.8 pp] | 53.6% | 5 of 7 |

Outside the 2026-01-23 front (Winter Storm Fern) the interval includes zero. Paired dR, all windows: 0.207 [-0.031,
0.414] (R 0.739 [0.550, 0.900] with the playbook).

## Process (exact replay of every graded episode on the frozen desk)

| | Beam-1.0 (bench) | Beam-1.0 + playbook |
|---|---|---|
| optimize calls answered (windows) | 268 (32) | 765 (32) |
| share asking `dam_position: spread`, pooled over calls | 9.3% | 95.2% |
| same, mean of per-window shares | 9.4% | 95.2% |
| mean risk asked | 0.782 | 1.733 |
| hours left after the last accepted offer, mean (median) | 23.53 (30.0) | 6.34 (6.0) |

Beam's column reproduces the failure replay's per-episode metrics on 32 of 32 windows (spread share and hours). Hours
run from the last accepted submit_dam_offers, submit_rt_offers or update_cop to the episode's end.

## Spend and provider errors

- Metered by the run's proxy at the Hugging Face router's price (item 15: $0.40 / $1.20 per 1M input / output, cached
  input at the full price): **$94.05** over 33 attempts (32 graded, 1 infrastructure), **$2.94 a graded window**;
  the network check before the run $0.014. Total $94.06 of the $150 cap.
- At the card's cost basis (item 47, Together AI's list price, $0.40 / $0.04 / $1.20): $0.4449 a graded window (Beam's
  bench run: $0.3064), $14.24 for all attempts.
- The same metering for Beam's bench run: $66.52 over 36 attempts, $1.97 a graded window.
- Proxy calls: 6072; HTTP 429 (account rate limit) 1600 (26.4%), HTTP 503 (the router's circuit breaker on Baseten)
  1846 (30.4%), HTTP 402 0; OpenCode retried 429s and 503s within the turn. Beam's bench run: 429 30.9%, 503 13.8%.
- Tokens: 7,995,068 uncached input, 221,640,576 cached (96.5%), 1,828,564 output.

Per window: `window_table.md`.

## Run

- Ran 2026-11-02 20:04:11 to 2026-11-03 00:08:46 UTC by route C (one EC2 box, m7i.4xlarge, local Docker), at most 3
  windows at once, the 32 windows in Beam's pack order, every window graded; none capped, none missing.
- The bench bundle for the playbook harness was generated as Beam's was, from the repo at desk-v4-bench-run1 (2523700)
  with d2792d8's harness folder (PLAYBOOK.md sha256 0dc7cb47..., opencode.json 44a1d967...); its task files are
  identical to Beam's bundle apart from the harness-config artifact id, and its hook and verifier are identical.
  agentenv-framework 0.9.1396, OpenCode 1.17.18 (the image Beam ran).
- Its own state, proxy and caps, apart from Beam's run: Beam's proxy code unchanged, a total cap of $150, $20 an
  episode.
- Network check ($0.014), from the agent container: ercot.com, github.com, pypi.org and router.huggingface.co
  unresolvable, 1.1.1.1 refused; the model reachable only through the proxy; a placeholder key; PLAYBOOK.md and
  opencode.json in the agent's OpenCode config with d2792d8's sha256. Its reply-format verifier scored 0: Beam answered
  '84.0' (the SoC it read) without pasting the shell output, which its trajectory shows.
- Playbook load, checked on the first three windows (2026-01-23 S01-S03, launched together at 20:04) before any more
  started: the files in each agent container with d2792d8's sha256; each window's first agent request 3,719 bytes
  larger than Beam's on the same window (the playbook's 3,663 JSON-escaped bytes plus OpenCode's instruction header);
  every optimize call asking dam_position spread with price_view desk. No window ran without it.
- One hand intervention: 2026-04-03 S04 attempt 1 (started 21:42:48) never got a model answer beyond OpenCode's title
  call ($0.0006): OpenCode's 429 backoff doubles per retry, and after 21:45:56 its retry at 22:54:12 got HTTP 429 again
  with the next scheduled 8,192 s later. It was stopped by hand at 22:57:09; the driver classed it agent ('cancelled by
  SIGTERM'), and it was reclassified to infrastructure (HTTP 429, not counted), with the driver restarted at 22:57:48
  adopting the 3 running windows. Attempt 2 (22:58:49-23:06:48, $1.61) was graded.
- Windows took 19.7 min on average (3.1 to 54.0); the long ones (05-08 S01 48 min, 07-04 S01 43 min, 07-23 S03 54 min)
  sat in OpenCode's 429 backoff (up to 1,024 s between retries) and resumed on their own.

## How it was computed

- Grades: `scripts/desk_bench_results.py` (plugin d2792d8) on the run's attempts, each graded episode regraded from
  its Episode JSON against the frozen refs (regrade diffs: 0); the graded episodes are in `episodes/`. Beam's
  per-window grades: the bench's `results/desk-v4-bench/grades.jsonl.gz` (model `beam`); the same script on Beam's
  attempts reproduces them (C 0.0673 [0.0051, 0.1196], $0.3064 a window).
- C, R and the paired dC: `boot` and `paired` in `scripts/desk_bench_results.py` (blocks = the 8 fronts, 2026-04-03
  aliased to 2026-04-17, 10,000 resamples, seed 0).
- Process metrics: the failure replay's exact replay of each graded episode, every replayed P equal to the graded P.
- Spend and errors: the run proxy's per-run totals and call logs.
- Files here: `score.json` (every number above), `window_table.md`, `results.jsonl` and `attempts.jsonl` (the
  driver's graded results and every attempt, with box and path fields removed), `episodes/` (each graded Episode
  JSON). The scoring scripts are not published.
