GridSim hybrid: run a solar farm and a battery behind one meter at an ERCOT node through an operating day, live on the virtual clock: commit the day-ahead position and AS book at watch 0, re-plan the hourly battery schedule at each watch as real-time prices settle, regulation drifts the state of charge and ERCOT deploys reserves, graded against the information-matched rolling MILP.

Every task deploys the env registered as `gridsim-hybrid` on the gateway provider (run `agent-env gridsim setup` once;
it is the `gridsim` image) and loads one site-day of the hybrid fixture pack at a tier (`energy`, `reserves` or `rtcb`)
through the env's `urn:gridsim:live-load/v1` extension. It hides the env's `grid_notice` tool from the agent's role,
registers one trigger per watch after the first that delivers the watch's notices through `grid_notice` when the
agent's `advance` opens it (a reserve deployment's with its payload; the deployment acts at its real time either way),
and arms the gateway clock frozen at watch 0 (D-1 14:00 CPT). After the play, `urn:gridsim:end-day/v1` runs any watches
the agent didn't reach on its committed book and grades the day. The `gridsim-hybrid-verifier` artifact reads the day
from the env's `data/get` and scores the run with the day's reward; the audit, hindsight capture, the energy-only
anchor's reward, the AS share, clipping recovered and failure-to-provide are weight-0 rows. A day that never finished,
or whose audit failed, fails the step, so the run is not scored.

- `day` plays a fixture deployment day (2022-01-16 at LZ_CPS, an RRS deployment at 19:03) at the `reserves` tier
  with the gridsim-llm agent (`agent-env gridsim setup --agent`, `--model <litellm model id>`), 52 turns.
- `wiring-noplay` runs the same steps without the agent and needs no model: end-day delivers every watch's notices
  itself, the day ends with nothing committed, and it scores 0 with the audit passing.

Prices: ERCOT Day-Ahead and Real-Time Market settlement point prices (NP4-190-CD, NP6-905-CD) and DAM Clearing Prices
for Capacity (NP4-188-CD), public ERCOT data; ERCOT does not endorse this work. Solar from ERCOT NP4-745-CD (an
availability proxy); sites from EIA-860 (public domain) or flagged archetypes; regulation drift is a seeded draw.
