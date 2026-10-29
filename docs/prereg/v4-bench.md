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
