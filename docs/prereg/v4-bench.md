# GridSimEnv desk v4 benchmark: pre-registration

Committed before the first scored benchmark episode. Nothing below changes after a scored run starts, and nothing is
rerun to improve a score. Anything done differently is logged under "Deviations", appended after the runs.

## What is measured
How well each model, in its own vendor's agent harness, runs a real ERCOT battery's trading desk over three-day windows
across real weather fronts (desk v4 "Weather Front"; contract `docs/CONTRACT-desk.md`). The agent submits ERCOT's own
objects (day-ahead and real-time offer curves, ancillary-service offers, the COP); clearing, 5-minute physics and ERCOT
settlement decide the money; the agent wakes at market milestones, notices, outages and its own reminders. Score:
hindsight capture C = (P − P_idle)/(P_hind − P_idle), the share of the hindsight optimum's profit over idle; R and P are
reported too. Cost: USD per three-day window at the providers' public list prices.

## How it runs
- Designed as a plain `agent-env run` of the published bundle `bench/desk-v4-bench` at tag `desk-v4-bench-run1` (commit
  199cf89) with agentenv-framework 0.9.1378 (protocol 0.1.393): agents in Modal containers with a network allowlist, the
  desk env in a Modal VM built from the bundle (frozen desk code `desk-v4-freeze`, be6ff8c). No framework change.
- **Run here on route C (deviation, decided before any scored episode):** the Modal environments available to us were
  unusable (one stops every app after about 15–25 minutes, the default one is over its spend limit, and creating a new
  environment needs a workspace manager). So the episodes run with the same bundle tasks and harness configs on EC2 boxes
  with local Docker: the desk env from the freeze image built on each box; egress closed by a host rule rejecting all
  traffic from the Docker bridge to the internet, and the models reached only through a per-lane proxy on the host that
  allows one API and one model per harness and refuses provider-side web, code-execution and remote-MCP tools. API models
  run on one box; Qwen3-4B on GPU boxes, each serving the same vLLM build, model revision and flags.
- Our runs reach the models through our LiteLLM gateway, through a private overlay of the bundle that differs only in the
  allowlist host; the published bundle allowlists the vendors' API hosts.
- Network: checked from inside the agent containers before the runs (Modal pilots and the route-C boxes): ercot.com and
  1.1.1.1 unreachable (also github.com and pypi.org on Modal); model endpoint and desk tools reachable.

## Benchmark pack
`desk-v4-bench` (629630a): 32 three-day windows = 8 fronts × 4 real ERCOT batteries (Far West 100 MW / 104 MWh,
Houston 100 MW / 206 MWh, North 120 MW / 187 MWh, South 150 MW / 185 MWh), every day ≥ 60 days old with complete
operator disclosures.
- `pre_cutoff` (16): 2026-01-23..25 (winter storm Fern), 03-16..18, 04-17..19 (South: 04-03..05, outage swap),
  05-08..10.
- `post_cutoff` (16), after every model's reported training cutoff (Gemini 4 Argon ≈ 2026-03, GPT-6.1 Sol ≈ 2026-04-30,
  GPT-6 Luna ≈ 2026-05-18, Claude Opus 5.5 ≈ 2026-06; third-party reports, unconfirmed): 07-04..06 (severe-storm line),
  07-23..25 (tropical storm), 08-18..20 (heat wave), 08-26..28 (heat break and storm line).
- References from the frozen core, anchor 1.5/spread; 8 of 32 floored; C defined on all 32.

## Models and harnesses (all at high effort)
| Model | Harness (version) | Setting |
|---|---|---|
| Claude Opus 5.5 | Claude Code (2.1.280) | effort high; the desk brief as the system prompt (AgentEnv default) |
| GPT-6.1 Sol | Codex CLI (0.147) | model_reasoning_effort high; OpenAI's Codex catalog entries for the model |
| GPT-6 Luna | Codex CLI (0.147) | as Sol |
| Gemini 4 Argon | Gemini CLI (0.38.2) | thinkingLevel HIGH |
| Qwen3-4B (untrained, Qwen/Qwen3-4B rev 1cfa9a72) | OpenCode (as installed by the framework release; recorded per run) | thinking on; temperature 0.6, top_p 0.95, top_k 20; served by vLLM 0.29.0 on a Modal GPU |

Each harness keeps its local workspace (shell, files, its own planning tools) and the desk's 11 tools over MCP; web search
and fetch are switched off in each harness's own settings. v4 budgets: 100 turns, 14 calls a turn.

## Runs
One run per window per model, 32 × 5. An episode that fails for infrastructure (provider 5xx or transient 4xx, sandbox
or tunnel failure) is retried at most twice; every attempt is kept and counted in the spend. An episode the agent itself
ends early, or that exhausts its budget, is final and scored as settled. Spend cap: $700 API in total for the scored
runs, split by projection; a model whose spend projects past its share is stopped and reported, not overrun.

## Reported
- Per model: mean C (headline), R and P, each with a front-block 95% bootstrap CI (8 fronts, 10,000 resamples, seed 0),
  for all 32 windows and for each half (`pre_cutoff`, `post_cutoff`); if the halves differ, the post-cutoff half leads.
- Cost per window (tokens × list price), turns, tool calls, wake-ups, reminders, shell use, failures and retries.
- The plot: C against cost per window (log scale), one point per model.
- Paired gaps (front-block CIs) between models, and each model against the real operator's replayed bids.

## Known limitations, disclosed
- The env gateway's control endpoints are not authenticated in this framework release, and the agent's shell can reach
  the env through its tunnel; no exploitation was seen in any pilot, and runs are not audited for it.
- On route C the agents hold only a placeholder key; the host proxy injects the real one and allows one model per lane.
- Gemini CLI drops thought signatures when it resumes a session (provider accepted the requests in testing).
- Harness versions are those of the framework release; differences in each harness's prompting are part of what is
  measured (model plus native harness).

## Pilots (the pilot window, 2026-02-03..05 S01, before this file)
Pilot window 2026-02-03..05 at S01, one episode per harness (information only, not scored):
- Claude Code + Opus 5.5: completed (GPU box and Modal), 17–21 wakes in one session, 43–61 desk calls, no shell use, C 0.12–0.13, $1.65–2.17.
- Codex + Sol: completed on the GPU box (56 wakes incl. 39 own reminders, 260 desk calls, C 0.23, $4.43, 83 min); Codex + Luna: completed (18 wakes, C 0.07, $0.24). OpenAI's Codex catalog entries for the GPT-6 models accepted by Codex 0.147 and used for all Codex runs.
- Gemini CLI + Argon: first pilot failed at wake 13 on a transient Google 400 (the identical request replays fine); rerun on route C.
- OpenCode + Qwen3-4B (thinking on): completed mechanically but submitted nothing valid (its tool-call JSON for nested offers is malformed and it repeats it); diagnosed as the untrained model's limitation, not configuration. Its benchmark score is reported as the untrained baseline.
- A $0 parity check showed the bench bundle's hook and env reproduce the frozen desk byte for byte on Linux.

## Deviations
1. Route C, as recorded above before the first scored episode: API models on one EC2 box (m7i.16xlarge, no GPU
   needed), Qwen3-4B on four EC2 GPU boxes (g5.xlarge and g5.2xlarge, A10G) each serving the same vLLM 0.29.0 build,
   model revision and flags, not on a Modal GPU. Qwen3-4B's cost is the boxes' on-demand GPU-hours shared by episode.
2. The API box ran agentenv-framework 0.9.1377, the Qwen boxes 0.9.1378. The two releases differ only in
   `agent_env.openenv` and `agent_env.training`, which `agent-env run` does not use.
3. Gemini 4 Argon was not run. Its route-C smoke on the pilot window stopped at its $12.47 cap after 40 minutes and
   30 wakes (5.5M uncached input tokens), which projects $15–20 a window and $480–640 for 32, past its share of the
   cap; per the spend rule it is reported, not run. Its smoke is not scored.
4. Retries, decided at 09:25 UTC while runs were in progress (Opus had finished and its results had been read; the rule
   is by failure type and applies to every model): launch attempts that failed while deploying, before the first model
   call, at $0, do not count toward the two-retry limit. All 81 such failures (Opus 27, Sol 35, Luna 19) were a port
   race in our launcher on the shared box; the last ended at 08:21 UTC, after the launcher was fixed. Sol 2026-03-16
   S04 and 2026-04-17 S02 were each graded on attempt 4 (two $0 deploy failures, then one paid stall).
5. Codex CLI stalls: the framework's agent CLI inactivity watchdog (300 s) ended 7 Codex episodes whose CLI printed
   nothing for 300 s (Sol 4, $7.68; Luna 3, $0.61). They were treated as infrastructure failures and retried; their
   spend is counted. A longer watchdog (900 s) is recommended for the next run.
6. No window is missing: each model run has exactly one graded run on each of the 32 windows. Qwen3-4B submitted
   nothing valid on 7 windows, which are scored as settled (R = 0).

### Gemini 4 Argon

7. Deferred on cost under 3 (at $15–20 a window, the projection was well past its share of the cap), Gemini 4 Argon
   was then run after the others, on 2026-10-29 from 16:41 to 19:45 UTC, on agentenv-framework 0.9.1383. That release
   contains scaleapi/agentenv-framework#388: the Gemini harness used to write the AgentEnv system prompt to a file named
   with a new UUID each turn, and Gemini CLI puts that path into the system instruction, so every turn start missed the
   prompt cache. 0.9.1383 and 0.9.1377 differ only in the Gemini harness and in `agent_env.openenv` and
   `agent_env.training`, which `agent-env run` does not use. The bundle was generated at `desk-v4-bench-run1`
   (2523700), exactly as for the other harnesses.
8. The same route C, on its own box (m7i.8xlarge) with separate state and its own port cursor.
9. Provider HTTP 400 INVALID_ARGUMENT: 19 of 1,488 wake starts (1.28%), all on a wake's first request from turn 12
   onwards, rising with prompt size (0% under 75k tokens, 2.7% at 175k and above). The identical request succeeded on
   replay, so these are transient 4xx and infrastructure under the pre-registered rule. The driver first classed them
   as agent-side, and 6 attempts were reclassified by hand. From 18:06 UTC, decided while the run was in progress, an
   attempt that ended on this 400 did not count toward the two-retry limit, with a safety stop at 6 attempts a window.
   No window used more than 4: 16 took 1, 13 took 2, 2 took 3 and 1 took 4.
10. From 18:08:39 UTC, new attempts went through a proxy that resends such a 400 once. It carried 2 attempts and resent
    nothing.
11. Caps: the per-episode cap was raised from $15 to $30 at 17:35:50 UTC, after the first attempt on 2026-07-23 S02
    had been stopped at $15.02; that attempt was retried as infrastructure. The Gemini model cap was raised from $300
    to $330 at 18:06 UTC.
12. Admission was paused from 17:09:53 to 17:14:54 and from 17:38:20 to 18:06:16 UTC, so retries ran out of pack
    order. The driver restarted nine times, each time adopting the running units.
13. Selection, descriptive: attempts that failed on a 400 ended at turn 21.4 on average, at a 172k-token prompt;
    graded attempts averaged 32.3 turns and a largest prompt of 207k tokens. Windows graded on the first try: 32.5
    turns, 204k tokens, C 0.170; windows graded after a retry: 32.1 turns, 210k tokens, C 0.227.
14. Prompt cache: 61% of wake starts hit the cache fully, and 32% hit only the ~15k-token prefix, because Gemini CLI
    drops a thoughtSignature when it resumes a session; that remains a known harness issue.

### Reflection Beam-1.0

15. Added after the others for the Reflection "Build with Beam" contest, and run after them, from 2026-10-31, on the
    same 32 windows: Reflection Beam-1.0 (`reflection/Beam-1.0-501B-A23B`) through the Hugging Face router to Baseten
    (`reflection/Beam-1.0-501B-A23B:baseten`, Chat Completions) at the router's list price of $0.40 / $1.20 per 1M
    input / output tokens. The router lists no cached-input price, so input tokens Baseten reports as cached are costed
    at the full input price; whether they are billed lower is not visible from the API, so Beam's cost is an upper
    bound. Committed before Beam's first scored call.
16. Harness: OpenCode 1.17.18, the harness and agent image Qwen3-4B used, with a model entry for Beam: effort high
    (`reasoning_effort: "high"` on every request), reasoning on, context limit 1,048,576 tokens (Beam's served
    context), output limit 32,768 (OpenCode caps a request at 32,000), the provider's default sampling, and web fetch,
    web search and code search denied. OpenCode sends the earlier turns' `reasoning_content` back, which Beam's API
    asks for, and the router accepts it. The bundle `bench-opencode-beam-desk-v4-bench` is generated at
    `desk-v4-bench-run1` (2523700) with this preset beside `opencode-qwen`, exactly as for the other harnesses; its desk
    tasks, hook and verifier are the others'.
17. agentenv-framework 0.9.1396 (protocol 0.1.411). Its OpenCode agent, source and image, is unchanged since 0.9.1377;
    the releases since 0.9.1383 add security fixes (sandbox shell code, artifact staging, the gateway's compose file)
    and features this bundle does not use (the gateway's new notifications have nothing to deliver to it). The smoke
    in 23 ran this release.
18. Training cutoff: Beam's reported cutoff is 2026-06-30, so the 16 `post_cutoff` windows (from 2026-07-04) are after
    it and the 16 `pre_cutoff` windows before it.
19. The same route C on the Gemini box (resized to m7i.2xlarge), with separate state and its own port cursor: egress
    closed by the host rule, the agent holding a placeholder key, and a host proxy lane that allows only Beam's Chat
    Completions on the router and injects the key. As the gateway does for the other models, the lane drops LiteLLM's
    `additional_drop_params` and the `tool_choice` it names (OpenCode only sends the default, "auto"). The netcheck runs
    first: the internet unreachable from the agent container, the model and the desk tools reachable.
20. Retries: the rules the others ran under. Infrastructure failures are retried at most twice, a launch that fails
    before any model call at $0 does not count, and agent-side outcomes are final. HTTP 429, the account's rate limit,
    is handled by OpenCode's own backoff and is not a failure; an attempt that still ends on a 429 is infrastructure
    and does not count toward the retry limit, with the safety stop at 6 attempts a window, as for Gemini's 400s.
21. Pace: the account allows 1,000,000 tokens a minute, cached tokens included, which one episode reaches at about a
    75k-token prompt, so the windows run near-serially (at most 2 at once), in pack order.
22. Caps, metered by the proxy at the prices in 15: $20 a window, a guard against a runaway episode (raised from $8
    before the first scored call, since $8 could stop windows as long as Sol's), and $200 in total for Beam, its own
    budget apart from the $700 above: the proxy stops at $198.07, which with the $1.93 smoke in 23 is $200. An attempt
    stopped by the window cap is final and reported as capped, with its spend; it is not retried or scored. No window
    starts once the spend so far, each running window at its likely cost (the larger of its spend and the mean graded
    window's cost, $5 before three are graded) and the windows left at that mean would pass $198.07; windows not run
    are reported as not run.
23. Smoke, not scored: the pilot window (2026-02-03..05 S01) on 2026-10-30, on local Docker rather than route C (the
    internet was not blocked; Beam made no shell or builtin call). Completed, 19 of 19 wakes in one session, 82 model
    requests plus 21 HTTP 429s that OpenCode retried, 71 desk calls, largest prompt 88k tokens, no compaction, C 0.13,
    $1.92 at the prices in 15 (97% of input tokens cached), 4 minutes.
24. Ran from 23:17 UTC on 2026-10-30 (not 2026-10-31, as 15 has it) to 02:30 UTC on 2026-10-31, at most 2 windows at
    once, after the netcheck in 19 passed: the agent's container on the Docker bridge the egress rule covers, ercot.com,
    github.com, pypi.org and the router unreachable from it, the model reachable through the proxy.
25. Out of credits, decided while the run was in progress: the Hugging Face account ran out of prepaid credits at
    01:55:02 UTC, after 29 windows had been graded ($58.71 metered). From then the router answered HTTP 402 ("You have
    no remaining credits"), which ended four attempts on the 2026-08-26 front: S02 after $2.82 and S03 after $0.69,
    both mid-episode, and S04 twice at $0, before any call. The driver classed the two mid-episode attempts as
    agent-side. All four were reclassified by hand as infrastructure, a billing stop on our side and not the agent's
    doing, and none counts toward the retry limit; the driver was then changed to class an HTTP 402 that way.
    Admission was paused from 01:57 to 02:09 UTC while credits were added; S02 and S03 were graded on attempt 2, S04
    on attempt 3, and the other 29 windows on attempt 1. All four 08-26 windows scored below zero, S01 included, which
    ran before the halt.
26. Provider errors handled inside the harness: of 4,457 requests through the proxy, 1,376 (30.9%) were HTTP 429, the
    account's rate limit, and 617 (13.8%) HTTP 503, the router pausing Baseten for Beam ("paused by the circuit
    breaker", retry-after 5 s). OpenCode retried both, and neither ended an attempt.
27. Spend: $66.52 metered for the 36 attempts ($63.01 for the 32 graded ones, $3.51 for the two the 402 ended
    mid-episode), $0.01 for the netcheck and $1.93 for the smoke: $68.46 for Beam, under its $200. 96% of input
    tokens were cached; at the full input price of 15 that is $1.97 a graded window.
