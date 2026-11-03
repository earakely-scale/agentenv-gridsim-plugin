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

### Open-weights comparison: GLM-5.3, Kimi K3, Qwen3.8 Max

28. Selection, stated before any result: the top three open-weights models on BenchLM's agentic leaderboard (snapshot of
    2026-10-29), chosen to compare against Beam-1.0 and run in the harness Beam used. Open weights means weights
    published on Hugging Face: GLM-5.3 (`zai-org/GLM-5.3`, GLM-5.3 licence), Kimi K3 (`moonshotai/Kimi-K3`, Kimi K3
    License) and Qwen3.8 Max, whose weights are `Qwen/Qwen3.8-2.4T-A95B` (licence "qwen3.8-max"; the hosted Qwen3.8-Max
    adds vision input, a non-thinking mode, 1M context by default and built-in tools on those weights, and Fireworks
    serves that base). Kimi K3.1 Pro ranks above Kimi K3 but has no released weights and is not on our gateway, so Kimi
    K3 stands. Added after the others and run after them, from 2026-10-31, on the same 32 windows. Results are reported
    in full whatever they show.
29. Routes and prices: our LiteLLM gateway to Fireworks, `fireworks_ai/glm-5p3`, `fireworks_ai/kimi-k3` and
    `fireworks_ai/qwen3p8-max`, at Fireworks' list prices per 1M input / cached input / output tokens: GLM-5.3 $1.40 /
    $0.26 / $4.40, Kimi K3 $3.00 / $0.30 / $15.00, Qwen3.8 Max $2.00 / $0.25 / $6.00. The proxy meters each response's
    usage at those prices.
30. Harness: OpenCode 1.17.18 as Beam's in 16 except for each model's entry: `reasoning_effort: "high"` on every request
    (effort high in the framework), reasoning on, context limit 1,040,000 tokens for GLM-5.3 and Kimi K3 (Fireworks'
    served context) and 262,144 for Qwen3.8 Max (its open weights' context), output limit 32,768, the provider's default
    sampling, and web fetch, web search and code search denied. High is GLM-5.3's middle level: its levels are low, high
    and max, and it defaults to max, which reasoned several times longer than high in our probes. All three return
    reasoning_content, OpenCode sends the earlier turns' reasoning back, and the gateway accepts it.
    agentenv-framework 0.9.1396; each bundle is generated at `desk-v4-bench-run1` (2523700) with an opencode-<model>
    preset beside opencode-qwen, exactly as for the other harnesses.
31. The same route C on the box Beam used (resized to m7i.8xlarge), each model with its own state, port cursor, proxy
    lanes and driver: egress closed by the host rule, the agent holding a placeholder key, the proxy injecting the
    gateway key. Each model's netcheck runs first and checks from inside its agent's container that the internet is
    unreachable and the model reachable.
32. Retries: the rules the others ran under, as for Beam in 20. Infrastructure failures are retried at most twice, a
    launch that fails before any model call at $0 does not count, and agent-side outcomes are final. HTTP 429 and HTTP
    402 are infrastructure and do not count toward the retry limit, with the safety stop at 6 attempts a window. A
    provider answer with no choices, seen twice in GLM-5.3 probes through the gateway, is infrastructure too.
33. Pace and caps: the three models at once, at most 4 windows of each at a time, in pack order. $20 a window: an
    attempt stopped by it is final and reported as capped, with its spend, not retried or scored, as in 22. $130 a
    model, its smoke and netchecks included: no window starts once the model's spend so far, its running windows at
    their likely cost (the larger of their spend and the mean graded window's cost, 1.3 times the smoke's cost before
    three are graded) and its windows left at that mean would pass $130.
34. Smokes, not scored: the pilot window (2026-02-03..05 S01) on 2026-10-31, on route C, one each. GLM-5.3 completed
    25 of 25 wakes, 69 model calls, C 0.095, $1.88; Kimi K3 25 of 25, 72 calls, C 0.111, $2.64; Qwen3.8 Max 22 of 22,
    62 calls, C 0.112, $2.66. Each kept one session with no compaction, cached 97–98% of input tokens and had no HTTP
    429 or other error.
35. Decided while the runs were in progress, at 07:39 UTC, after the first GLM-5.3 attempt hit it and while Kimi K3 had
    2 windows graded and Qwen3.8 Max none, none of which had hit it: a call that ends at OpenCode's 32,000-token output
    limit with no content or tool call makes the harness exit (`opencode exited … without completing`), a harness
    termination, not an agent decision. Such an attempt is infrastructure and counts toward the two-retry limit; a
    window that uses its three attempts on it is reported as missing. It applies to all three models; Beam never came
    near the limit (largest output 2.3k tokens). The attempts it ends, their windows, and C on windows graded after a
    retry against C on windows graded at once are reported per model.
36. Budget and pace, decided while the runs were in progress: from 08:05 UTC the three models shared $390 (Edgar's
    approval; the $130 a model of 33 was a split of it), with a guard on the box that stopped admitting windows of
    every model while the combined projection (spend so far, running windows at their likely cost, the windows left at
    each model's mean) passed it and set the proxy to refuse every call at $389 of actual spend; the $20 a window
    stayed. Admission paused from 08:56 to 14:07 UTC. Pool raised $390 → $480 by Edgar at 14:07Z after a pause from
    08:56Z; no attempt was retried or rerun because of the pause. The proxy's own total stop went from $400 to $490 at
    the same time, restarted with nothing running. Raising Qwen3.8 Max to 6 windows at a time once the other two had
    finished was approved but not applied: by then Qwen3.8 Max had one window left to start. All three ran 07:17 to
    16:24 UTC.
37. Hand reclassifications, corrections under the rules above rather than deviations, each keeping the original class
    and its time. GLM-5.3 2026-01-23 S01 attempt 1, ended 07:26:22 UTC, agent to infrastructure at 07:40 under 35:
    "opencode exited with code 0 without completing" after its last call stopped at the 32,000-token limit. GLM-5.3
    2026-05-08 S02 attempt 1, ended 08:24:47 UTC, agent to infrastructure at 08:27 as a provider failure:
    "litellm.MidStreamFallbackError: litellm.APIConnectionError: APIConnectionError: Fireworks_aiException - Connection
    closed." After each, the driver was changed to class such an attempt that way itself, and a rescan of every
    attempt found no other.
38. Windows not graded: Kimi K3 2026-03-16 S04 (60 turns, 404 model calls, 214k-token peak context, $18.95),
    2026-05-08 S04 (34 turns, 447 calls, 221k, $18.96), 2026-07-23 S04 (46 turns, 396 calls, 209k, $18.94) and
    2026-08-26 S01 (50 turns, 449 calls, 198k, $19.02), each stopped by the $20 window cap and final under 33: in each
    Kimi K3 polled the desk tools hundreds of times over a long, fully cached context. Kimi K3's C is over its other
    28 windows. GLM-5.3 and Qwen3.8 Max have all 32. No window used its three attempts on 35.
    Under 35: GLM-5.3 11 attempts on 8 windows (2026-03-16 S03, 2026-04-17 S03 and 2026-05-08 S04 graded on attempt
    3; 2026-01-23 S01, 2026-03-16 S02, 2026-07-23 S01, 2026-07-23 S02 and 2026-08-26 S01 on attempt 2), C 0.213 on the
    23 windows graded at once against 0.109 on the 9 graded after a retry; Kimi K3 1 attempt (2026-01-23 S01, after
    $13.03 at a 395k-token context; graded on attempt 2, C 0.821, against 0.148 on its 27 graded at once); Qwen3.8 Max
    3 attempts on 2 windows (2026-03-16 S03 on attempt 3, 2026-05-08 S04 on attempt 2), 0.174 against 0.136 on 30.
39. Provider errors and spend: no HTTP 429 for any model; HTTP 503 ("upstream connect error") 2 for GLM-5.3 and 4 for
    Kimi K3, retried by OpenCode within the turn; one mid-stream provider failure (37). Metered at the prices in 29:
    GLM-5.3 $108.23 over 44 attempts, Kimi K3 $192.83 over 33 ($75.87 of it in the four capped attempts), Qwen3.8 Max
    $128.98 over 35, and $7.41 for the smokes and netchecks: $437.45 of the $480. 97–98% of input tokens were cached.

### Base Qwen3.5-9B

40. Added after the others at Edgar's request: Qwen3.5-9B is the size we train (the desk-distill fine-tune), and the
    untrained Qwen3-4B row stays as the reference. Base `Qwen/Qwen3.5-9B`, untrained, run from 2026-10-31 on the same
    32 windows; results reported in full whatever they show. This row is served by a Fireworks dedicated deployment
    through our LiteLLM gateway, `fireworks_ai/deployed/y4w64k4w` (the key reaches only that explicit route; the
    catalog alias `qwen3p5-9b` is denied), while the fine-tuned 9B in desk-distill is served by our own vLLM. The
    deployment scales from zero: a first call took 184 s, warm calls 0.3 s.
41. Harness: desk-distill's `opencode-qwen35-long` (its prereg items 7 and 8): OpenCode 1.17.18, thinking on
    (`chat_template_kwargs.enable_thinking`), temperature 0.6, top_p 0.95, top_k 20, min_p 0, no reasoning_effort,
    output limit 8,192, `agent.build.steps` 20, and a context limit of 262,143 tokens, the deployment's maximum
    measured by a probe (a 268,017-token prompt was refused at "maximum context length: 262143"), one token under
    desk-distill's 262,144. top_k reaches Fireworks through LiteLLM: at top_k 1 and temperature 1.5 three calls gave the
    same word, unset three different ones. agentenv-framework 0.9.1396; the bundle generated at `desk-v4-bench-run1`
    exactly as for the other harnesses; route C as in 31, with its own state, proxy lanes and driver, and its netcheck
    first.
42. Rules: those of 32, with 35's for OpenCode's 8,192-token output cap here: an attempt that ends there is
    infrastructure, at most three attempts a window. Up to 16 windows at once to start, raised while per-call latency
    and HTTP 429s allow, lowered on 429s or errors; the concurrency where latency degrades is reported.
43. Caps: $20 a window and $100 for the row, metered by the proxy from each response's usage at the price LiteLLM reports
    for the route, $0.20 per 1M input and output tokens, cached input included at that price since no cached price is
    reported. A dedicated deployment is billed by GPU time, not by token, so the token totals are reported beside it.
44. Concurrency, decided while the run was in progress: 16 windows at once from 23:55 UTC on 2026-10-31. The
    deployment's prompt cache gave way as contexts grew: 93% of input tokens cached at 11 windows of about 30k-token
    prompts, 47–64% at 13 to 16 windows of 55k to 90k, with the median call from 1.6 s to 11 s and calls a minute
    falling. Admission was lowered to 12 at 00:12 UTC and to 6 at 00:23 UTC, with no running window stopped; at 6 the
    cache held (97%) and the median call took 2.2 s. Per-call latency degrades from about 12 windows at once, so the
    run did not go to 32.
45. Cap: the row's cap went from $100 to $130 at 00:48:59 UTC on 2026-11-01, raised by the coordinator; the metered
    cost is notional because the dedicated deployment bills by GPU-hour. Applied live to the proxy and the driver; the
    $20 a window and the metering of 43 are unchanged. The driver had stopped admitting at 00:47 UTC on a $101.02
    projection and resumed at 00:49; no window was stopped or retried because of it. Metered $105.79 over 36 attempts
    ($102.52 for the 32 graded) on 78.3M uncached input tokens, 449.3M cached (85.2%) and 1.34M output tokens.
46. Under 42: the 8,192-token output cap ended 4 attempts, one each on 2026-01-23 S03, 2026-03-16 S03, 2026-05-08 S03
    and 2026-07-23 S03, each graded on attempt 2; C 0.091 on the 28 windows graded at once against -0.052 on those 4.
    4 HTTP 503s were retried within their turns; no HTTP 429. All 32 windows graded, 23:55 to 01:20 UTC.

### Cost basis, and the anchor-distilled Qwen3.5-9B

47. Cost basis, decided after every run above, on 2026-11-01: a model's cost is its tokens at its maker's list price.
    Every price above already was, but Beam-1.0's: Reflection publishes no price (its API is a free beta), and 15
    costed it at the Hugging Face router's $0.40 / $1.20 per 1M input / output tokens with cached input at the full
    input price, an upper bound of $1.97 a graded window; the router's actual bill to Baseten for the run was about
    $32. Beam-1.0 is now costed at Together AI's list price, $0.40 / $0.04 / $1.20 per 1M input / cached input /
    output tokens: $0.3064 a graded window and $10.44 for its 36 attempts (the two the 402 ended, metered at the
    router's price, scaled by the two prices' ratio on their trajectory tokens). That one figure is used everywhere.
48. Base Qwen3.5-9B has no maker price: Alibaba Cloud Model Studio sells Qwen3.5 by the token only from 27B up (its
    pricing page, updated 2026-10-29) and offers Qwen3.5-9B only for fine-tuning and for dedicated deployment billed
    by the hour. Its cost is therefore the metered rate of 43, $0.20 per 1M tokens with cached input at that rate:
    $3.20 a graded window and $105.76 for its 36 attempts. The dedicated deployment itself bills by GPU time.
49. Qwen3.5-9B + desk SFT, added after the others: the secondary comparison of `docs/prereg/desk-distill.md`, a LoRA
    SFT of Qwen3.5-9B with TRL, through AgentEnv, on OpenCode transcripts of the desk's own planner (the anchor
    policy, which calls `optimize` and submits its proposal), so it reproduces the planner rather than trading on its
    own; on that pre-registration's primary test, 18 held-out windows, it missed the pre-registered bar (+0.038
    [−0.034, +0.106] over base). It played the 32 windows from 03:51 to 06:31 UTC on 2026-11-01, served by our own
    vLLM 0.29.0 on two g7e.8xlarge boxes in us-east-1 with the harness `opencode-qwen35-long`, while base Qwen3.5-9B
    (40 to 46) was served by a Fireworks dedicated deployment: the two 9B rows are served differently, and numerics,
    the tool-call parser and sampling can differ between the servers. Both 9B harnesses are OpenCode 1.17.18 with
    thinking on, temperature 0.6, top_p 0.95, top_k 20, an 8,192-token output limit, a 20-step cap a turn and a
    262k-token context (262,144 for the student, 262,143 for base), where Qwen3-4B's harness has a 32,768-token context
    and no step cap. Its cost is GPU time: each run's share of its box's time at the $4.5013 an hour spot price paid,
    $0.56 a graded window. The output limit ended 1 attempt (2026-04-03 S04), retried as infrastructure under 42.
50. The student's training spans against these windows, checked after its run with the span logic of
    `scripts/desk_distill_windows.py` (a window starting d0 reads D-7 to D2): only the 2026-05-08 front's operating
    days, 05-08 to 05-10 (its four windows, S01 to S04), fall inside any training window's span, as the DAM and MCPC
    price history, D-7 to D-4, of the 16 training site-windows that start 2026-05-14 to 05-17. The training
    transcripts never name those days (none of the 147 captured sessions does), and on those four windows the
    student's C is within 0.017 of the planner's. The full check is in `docs/prereg/desk-distill.md`.
51. The training pack, `data/desk/desk-v4-win`, is not on main: it is on the branch `desk-distill` at 13d53f9, where
    `scripts/desk_bench.py` reads it from its pinned commit, and `scripts/desk_data_build.py desk-v4-win` rebuilds it.

### Three small models: Claude Haiku 5.5, GLM-5.3-Flash, DeepSeek V4.1 Flash

52. Added after the others at Edgar's request, for more models in the $0.2–0.5-a-window range, and run from 2026-11-01
    on the same 32 windows; results reported in full whatever they show.
53. Routes and harnesses, each route probed first with a tiny call through our LiteLLM gateway. Claude Haiku 5.5 at
    `claude-haiku-5-5` on the gateway's Anthropic Messages route, in Claude Code exactly as Claude Opus 5.5's row: the
    claude-code preset of `scripts/desk_bench.py` with the model swapped, effort high, `bench-claude-code` (web search
    and fetch denied), and the Claude Code the Opus row ran, 2.1.280, which agentenv-framework 0.9.1396 still pins.
    GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`) at `fireworks_ai/glm-5p3-flash` and DeepSeek V4.1 Flash
    (`deepseek-ai/DeepSeek-V4.1-Flash`, MIT) at `fireworks_ai/deepseek-v4p1-flash`, in OpenCode 1.17.18 as GLM-5.3 in 30:
    `reasoning_effort: "high"`, output limit 32,768, context limit 1,040,000 (both took a 300,016-token prompt; the
    weights' maximum is 1,048,576), the provider's default sampling, web tools denied. Thinking works through the
    gateway for both; for GLM-5.3-Flash, high is again below its default level. agentenv-framework 0.9.1396; bundles
    generated at `desk-v4-bench-run1` exactly as for the others; route C as in 31, each model with its own state,
    proxy lanes and driver, its netcheck first.
54. Rules: those of 32 to 35 and 37. Provider failures are infrastructure; an OpenCode exit at its output limit is
    infrastructure, counted, at most three attempts a window; an attempt stopped by its window cap is final and
    unscored.
55. Caps and prices: $5 a window, $20 a model, $60 for the three, with the proxy stopping every call at $59 combined.
    Metered at the makers' list prices per 1M tokens (47). Claude Haiku 5.5: $0.10 input, $0.01 cache read, $0.125
    cache write (5 minutes; 1-hour writes at twice the input price, $0.20) and $0.50 output for prompts up to 100K
    tokens, and $0.50 / $0.05 / $0.625 ($1.00) / $2.50 above, the tier set by the whole prompt. GLM-5.3-Flash (Z.ai):
    $0.15 input, $0.03 cached, $0.50 output. DeepSeek V4.1 Flash (DeepSeek's official rates): $0.30 on a cache miss,
    $0.006 on a hit, $1.20 output, its peak price throughout although part of the run falls in its half-price
    off-peak hours. The three models run at once, about 10 to 12 windows of each at a time.
56. GPT-6.1 Terra, added beside them at Edgar's request (decided 2026-11-01 before its first scored call, while the three
    above were running): `azure_ai/gpt-6.1-terra` through our gateway on Codex's path (`/openai/v1/responses`), in
    Codex exactly as GPT-6.1 Sol and GPT-6 Luna: codex-cli 0.147.0, the image the Sol and Luna rows ran (agentenv-framework
    0.9.1396 still pins it), `model_reasoning_effort` high, web search off, and OpenAI's Codex catalog entries, with an
    entry for Terra copied from Sol's (GPT-6.1 family; only the slug and name differ) since the catalog has none. A probe
    returned function calls and encrypted reasoning, effort honoured (130 reasoning tokens at low, 594 at high). Metered
    at OpenAI's list price per 1M tokens: $1.00 input, $0.05 cached, $1.25 cache write (30 minutes), $5.00 output, and
    above 272K input $2.00, $0.10, $2.50 and $7.50. Caps: $5 a window and $100 for Terra; the four models' pool rises
    from $60 to $160, with every call stopped at $159 combined. About 10 to 12 windows at once; the three above have
    priority.
57. Run: Claude Haiku 5.5 from 16:02 to 16:40 UTC on 2026-11-01, GLM-5.3-Flash 16:03 to 16:40 and DeepSeek V4.1 Flash
    16:04 to 17:16, each at up to 12 windows at once; GPT-6.1 Terra 16:16 to 19:02, at 10 windows at once and from
    16:34 at 4 (58). All four graded all 32 windows; none was capped or missing. Tags: `claude-haiku-5-5`,
    `glm-5.3-flash`, `deepseek-v4.1-flash`, `gpt-6.1-terra`.
58. Concurrency, decided while the run was in progress: at 10 windows at once, Terra's Azure deployment answered with
    its token rate limit inside the response stream, and Codex retried the call three times and exited, the same error
    each time: "codex CLI exited with code 1 on attempt 3: stream disconnected before completion: Your requests to
    gpt-6.1-terra for gpt-6.1-terra in westus have exceeded token rate limit." It ended six first attempts, each graded
    on attempt 2: 2026-01-23 S03 (ended 16:35:44 UTC, $1.63), 2026-01-23 S04 (16:29:50, $0.60), 2026-03-16 S03
    (16:29:52, $0.58), 2026-04-17 S02 (16:29:13, $0.41), 2026-04-17 S03 (16:32:26, $0.10) and 2026-05-08 S02 (16:34:13,
    $0.14). Terra's admission went from 10 to 4 at 16:34 UTC with no running window stopped, and no rate limit followed.
59. Hand reclassifications, corrections under 32 (an HTTP 429 is infrastructure and does not count toward the retry
    limit) rather than deviations, each keeping its original class and time: Terra 2026-04-17 S02, 2026-01-23 S04 and
    2026-03-16 S03 attempt 1, agent to infrastructure at 16:31 UTC, because the driver's 429 pattern did not match that
    in-stream wording. The driver was then changed to class it as a 429 itself, and it classed the other three of 58.
    No attempt of the four models is classed agent-side.
60. Under 54: OpenCode's output limit ended 2 DeepSeek V4.1 Flash attempts ("opencode exited with code 0 without
    completing" after a call that finished at the limit), 2026-04-17 S01 (ended 16:16:51 UTC) and 2026-08-26 S01
    (16:54:25), $0.06 each, each graded on attempt 2; C 0.260 on the 30 windows graded at once against 0.033 on those 2.
    No other model hit it.
61. Provider errors: HTTP 503 ("upstream connect error or disconnect/reset before headers") 2 for DeepSeek V4.1 Flash
    and 6 for Terra, each retried by the harness within its turn; none ended an attempt. No HTTP 429 for the three small
    models. Claude Code's `HEAD /api/hello` connectivity check reached Haiku's proxy lane 931 times and was refused
    (403), the lane serving only model calls; no attempt failed on it.
62. Driver fixes while the run was in progress, none changing a result. At the first launch, 16:02 UTC, the small
    models' drivers took the default cap ($130 less the model's spend) instead of $20, and Haiku's record named
    OpenCode as its agent; they were relaunched at 16:06 with $20 ($19.99 for Haiku after its netcheck) and
    claude-code 2.1.280, adopting their running windows, before any window had finished. That stop left two run folders
    without their start marker (GLM-5.3-Flash 2026-01-23 S04, DeepSeek V4.1 Flash 2026-01-23 S02), on which those two
    drivers stopped; the empty folders were removed and both relaunched at 16:08, starting those windows as attempt 1.
    Around 16:30 Haiku's driver stopped on reading the proxy's totals file mid-rewrite; the read now retries. At 16:53
    Terra's driver stopped writing its first episode, whose file name took the route's slash
    (`azure_ai/gpt-6.1-terra`); the tag is now the route's last segment, the half-written row for 2026-03-16 S01
    attempt 1 was removed (a backup kept), and the relaunched driver recorded that run and the five that had finished
    meanwhile from their stored results. No window was rerun.
63. Spend at the prices of 55 and 56, probes and netchecks included: Claude Haiku 5.5 $12.79 over 32 attempts ($0.40 a
    graded window; 1,101 of its 2,022 model calls, $10.59, at the above-100K tier, and no 1-hour cache writes),
    GLM-5.3-Flash $4.88 over 32 ($0.15), DeepSeek V4.1 Flash $12.17 over 34 ($0.38; at its peak price throughout, so an
    upper bound) and GPT-6.1 Terra $66.49 over 38 ($1.97 a graded window; $3.46 of the total in the six attempts of 58;
    its largest prompt, 231k tokens, stayed under the 272K tier): $96.33 of the $160. The most expensive windows were
    $0.65, $0.26, $0.59 and $3.23, so no window reached $5, no model its cap, and the $159 stop never fired. Cached
    share of input tokens: 96.7%, 98.0%, 98.1% and 97.5%.

### Beam-1.0 with the desk playbook (exploratory, added after the bench)

64. Added on 2026-11-02, after every bench result and after the exact-replay diagnosis of Beam-1.0's 32 runs
    (`results/desk-v4-bench/beam-diagnosis/`), and before any playbook episode. It asks one question: when Beam-1.0 is
    given the two habits the diagnosis found it lacks, does its own play recover what the replay predicts? It is not
    part of the leaderboard; it is reported only as Beam-1.0 against its own bench runs.
65. The harness is Beam-1.0's, `opencode-beam`, unchanged: OpenCode 1.17.18 at effort high, the same route (Hugging Face
    Inference Providers, Baseten), agentenv-framework 0.9.1396, the bundle `desk-v4-bench-run1`, the same tools,
    budgets, egress rule and proxy. One file is added: `bench/harness/bench-opencode-beam-playbook/PLAYBOOK.md`
    (46 lines, sha256 0dc7cb47eb500057…), which `opencode.json` loads as instructions (`opencode-beam-playbook`). It is
    general desk practice: ask `optimize` with `price_view` desk, `risk` 1.5 (1 to 2 by judgment) and `dam_position`
    spread, send the whole proposal before each gate, and re-plan at every checkpoint through the last operating day.
    Its `spread` setting was checked on 48 desk-v4-win training windows with no bench day (+0.022 [+0.005, +0.043] over
    `physical`); it names no window, date, price or result. Frozen at this commit.
66. Runs: all 32 bench windows, once each, in pack order, at most 3 at once; the first attempt that reaches the grade
    is scored. Retries, 429s, 503s and HTTP 402 are handled as in 20, 25 and 26. Caps: $20 a window and $150 in all, on
    Edgar's Hugging Face account; a window not run is reported as not run.
67. Reported whatever the result, with no rerun to improve a score: C and R of Beam-1.0 with the playbook; the paired
    difference from Beam-1.0's own bench run on each window, front-block bootstrap (10,000 resamples, seed 0), over
    all 32 and separately over the 16 July–August windows and over the 28 outside the 2026-01-23 front; the share of
    `optimize` calls asking `spread`; and the hours left after the last accepted offer. The playbook was written after
    seeing Beam's failures on these same windows, so this measures whether the diagnosed fixes carry over to Beam's own
    play, not performance on unseen windows.

#### Deviations and run record, Beam-1.0 with the desk playbook

68. Ran from 20:04:11 UTC on 2026-11-02 to 00:08:46 UTC on 2026-11-03 on the route-C box Beam used
    (i-0b5437b2bcfbb608e, now m7i.4xlarge), at most 3 windows at once, in Beam's pack order. All 32 windows were
    graded, 31 on attempt 1 and 2026-04-03 S04 on attempt 2 (72); none was capped or missing. The run had its own
    state (port cursor 30000), its own proxy service running Beam's proxy unchanged on lanes 4710-4712 (netcheck
    4719) under the label `opencode-beam-playbook` with a $150 total stop, and Beam's driver unchanged, with $20 a
    window and $149.98 in all ($150 less the netcheck). Beam's state, lanes, proxy and results were left as they were.
69. The bundle was generated on the box as Beam's was, from the repo at `desk-v4-bench-run1` (2523700) with the
    `opencode-beam-playbook` preset of d2792d8 and d2792d8's harness folder. That commit was fetched into the box's
    clone without moving HEAD, so the desk tasks are those Beam played, and the folder was taken from it with
    `git archive` (PLAYBOOK.md sha256 0dc7cb47eb500057…, opencode.json 44a1d967cef50889…). All 33 task files
    matched Beam's bundle apart from the harness-config artifact id, and the hook and verifier matched byte for byte.
    agentenv-framework 0.9.1396 and OpenCode 1.17.18, the image Beam ran.
70. Netcheck ($0.014), run first as in 19. From the agent container on docker0, ercot.com, github.com, pypi.org and
    router.huggingface.co did not resolve, 1.1.1.1 was refused, and the model was reachable only through the proxy.
    The agent held the placeholder key, and PLAYBOOK.md and opencode.json were in /data/config/opencode with the
    hashes in 69. The netcheck's own reply check scored 0: Beam answered "84.0" (the state of charge it had read)
    without pasting the shell output, which its trajectory shows (every host unreachable). The netcheck is not scored.
71. Before more windows started, the playbook was confirmed loaded on the first three (2026-01-23 S01 to S03,
    launched together at 20:04). Each agent container held the two files with the hashes in 69. Each window's first
    agent request was 3,719 bytes larger than Beam's on the same window: the playbook's 3,663 JSON-escaped bytes plus
    OpenCode's instruction header, in the system message. Every optimize call so far asked `dam_position` spread with
    `price_view` desk. No window ran without the playbook, and none was excluded.
72. Hand intervention, decided while the run was in progress: 2026-04-03 S04 attempt 1 started at 21:42:48. Apart
    from OpenCode's title call ($0.0006) it got no model answer and made no desk call, and it stayed in OpenCode's
    HTTP 429 backoff, which doubles with each retry. Its retry at 22:54:12 (4,096 s after the one before) was refused
    with a 429 again, and the next was due 8,192 s later (about 01:11 UTC), past the time set for results. It was
    stopped by hand at 22:57:09 and treated as an attempt ending on HTTP 429: infrastructure under 20, not counted.
    The driver had classed it agent-side ("cancelled by SIGTERM"); it was reclassified by hand, keeping the original
    class. The driver was stopped and relaunched at 22:57:48 with the same arguments, adopting the 3 running windows.
    Attempt 2 (22:58:49 to 23:06:48, $1.61) was graded. No attempt that had reached the desk was stopped.
73. Admission estimate, not pre-registered: before three windows were graded, each window was projected at $4 rather
    than Beam's $5 (22), since $5 × 32 = $160 would have blocked the first window under the $150 total. It never bound:
    the projection stayed at or under $128.01 of $149.98.
74. Provider errors: of 6,072 requests through the proxy, 1,600 (26.4%) were HTTP 429, the account's rate limit, and
    1,846 (30.4%) were HTTP 503, the router pausing Baseten ("paused by the circuit breaker"). There was no HTTP 402.
    OpenCode retried them within the turn, and apart from 72 none ended an attempt. Its 429 backoff reached 1,024 s
    between retries in graded windows, so windows took 19.7 minutes on average (3.1 to 54.0). The run was bound by
    the account's 1,000,000 tokens a minute, not by the 3-window limit.
75. Spend: $94.05 metered at the router's price of 15 for the 33 attempts ($94.05 for the 32 graded, $0.0006 for the
    stopped one) plus $0.014 for the netcheck, $94.06 of the $150. That is $2.94 a graded window, against Beam's $1.97
    in its bench run; the most expensive window was $6.08. At the cost basis of 47 it is $0.4449 a graded window
    ($14.24 for all attempts), against Beam's $0.3064. 96.5% of input tokens were cached.
76. Result, as pre-registered in 67, from `scripts/desk_bench_results.py` on the run's attempts. Every graded episode
    was regraded from its Episode JSON, with no difference from the verifier's grade. C is 0.189 [0.060, 0.358] and R
    0.739 [0.550, 0.900], against 0.067 [0.005, 0.120] in Beam's bench run. The paired difference in C from Beam's
    bench run, front-block bootstrap (10,000 resamples, seed 0):
    - all 32 windows: +0.122 [+0.016, +0.269], ahead on 19 windows and 6 of 8 fronts;
    - the 16 July–August windows: +0.112 [+0.055, +0.195], ahead on 11 windows and 4 of 4 fronts;
    - the 28 windows outside the 2026-01-23 front: +0.058 [−0.003, +0.128], ahead on 15 windows and 5 of 7 fronts.
    By exact replay, 95.2% of the 765 answered `optimize` calls asked `spread` (Beam's bench run: 9.3% of 268). The
    hours left after the last accepted offer were 6.3 on average (median 6.0), against Beam's 23.5 (30.0).
