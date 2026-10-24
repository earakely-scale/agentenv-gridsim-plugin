GridSim live: run one battery at an ERCOT hub or load zone through an operating day, live on the virtual clock: commit a day-ahead position at watch 0, re-plan the 15-minute dispatch at each watch as real-time prices settle and ERCOT notices arrive, graded against the notice-blind rolling re-planner.

Every task deploys the env registered as `gridsim-live` on the gateway provider (run `agent-env gridsim setup` once;
it is the `gridsim` image) and loads one battery-day of the live fixture pack through the env's
`urn:gridsim:live-load/v1` extension. It hides the env's `grid_notice` tool from the agent's role, registers one
trigger per watch after the first that delivers the watch's notices through `grid_notice` when the agent's `advance`
opens it, and arms the gateway clock frozen at watch 0 (D-1 14:00 CPT). After the play, `urn:gridsim:end-day/v1`
runs any watches the agent didn't reach on its committed schedule and grades the day. The `gridsim-live-verifier`
artifact reads the day from the env's `data/get` and scores the run with the day's reward, with the audit and the
hindsight capture as weight-0 rows; a day that never finished, or whose audit failed, fails the step, so the run is
not scored.

- `day` plays the fixture notice day (a synthetic CI notice board and conservation appeal on a real day, 2024-01-02
  at LZ_CPS) with the gridsim-llm agent (`agent-env gridsim setup --agent`, `--model <litellm model id>`), 52 turns.
- `wiring-noplay` runs the same steps without the agent and needs no model: end-day delivers every watch's notices
  itself, the day ends with nothing committed, and it scores 0 with the audit passing.

Prices: ERCOT Day-Ahead Market and Real-Time Market settlement point prices (NP4-180-ER, NP6-785-ER), public ERCOT
data; ERCOT does not endorse this work. Battery archetypes from EIA-860 (public domain). The fixture's notices are
synthetic and are not ERCOT notices.
