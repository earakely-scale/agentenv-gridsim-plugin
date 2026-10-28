GridSim forecast ("Weather Front"): run a solar farm and a battery behind one meter at an ERCOT node for two or three operating days on weather, load and price forecasts served as they were issued: bid each day's DAM position and AS awards at its 10:00 gate the day before, re-plan the real-time battery book at each watch as weather runs, notices and DAM results arrive, graded against the information-matched rolling MILP on the desk's P50 price guide.

Every task deploys the env registered as `gridsim-forecast` on the gateway provider (run `agent-env gridsim setup`
once; it is the `gridsim` image) and loads one window of the forecast fixture pack at a tier (`front-lite`, `front`,
`blind` or `freeze-6h`) through the env's `urn:gridsim:forecast-load/v1` extension. It hides the env's `grid_notice`
tool from the agent's role (and, at the blind tier, `get_forecast` and `get_forecast_drift`), registers one trigger per
watch after the first that delivers the watch's notices through `grid_notice` when the agent's `advance` opens it (a
reserve deployment's with its payload; the deployment acts at its real time either way), and arms the gateway clock
frozen at watch 0 (10:00 CPT the day before the first operating day). After the play, `urn:gridsim:end-window/v1` runs
any watches the agent didn't reach on its DAM entries and committed book and grades the window. The
`gridsim-forecast-verifier` artifact reads the window from the env's `data/get` and scores the run with its reward;
the audit, the reward against hindsight, the paired gap to the anchor, beating it, the three-scenario re-planner's
reward, the value of forecasts (blind), missed DAM gates and the stored baselines are weight-0 rows. A window that
never finished, or whose audit failed, fails the step, so the run is not scored.

- `front-lite`, `front`, `blind` and `freeze-6h` play the fixture window 2022-12-22..24 at HB_NORTH (Winter Storm
  Elliott's notices and a Non-Spin deployment; its forecast vintages are synthetic until the forecast store lands) at
  that tier with the gridsim-llm agent (`agent-env gridsim setup --agent`, `--model <litellm model id>`): 72 turns
  for `front-lite`, 122 for the others, 16,384 output tokens a turn.
- `fern-0124` (Winter Storm Fern, 2026-01-24..26 at HB_NORTH), `heather-0114` (2024-01-14..16 at HB_NORTH),
  `uri-0213` (Winter Storm Uri, 2021-02-13..15 at HB_HOUSTON, desk forecasts) and `spring-0328` (a calm spring window
  with negative prices, 2024-03-28..30 at HB_WEST) play the showcase pack's windows at the `front` tier, on ERCOT's own
  load, wind and solar postings except Uri's.
- `wiring-nodam` runs the fixture window's steps without the agent and needs no model: end-window delivers every
  watch's notices itself, every DAM gate is missed, and it scores 0 with the audit passing.
- `wiring-lookahead` asks the agent for a price forecast issued after now, which the env refuses, and then only to
  advance: it scores 0 with the audit passing and no forecast served.

Prices: ERCOT Day-Ahead and Real-Time Market settlement point prices (NP4-180-ER, NP6-785-ER) and DAM Clearing Prices
for Capacity (NP4-188-CD), public ERCOT data; ERCOT does not endorse this work. Weather: NOAA HRRR as issued; NWS
products from the IEM VTEC archive; ERCOT's day-ahead load forecast via EIA-930 (public domain). Desk load, wind and
solar forecasts and the price guide are modelled from them. Solar from ERCOT NP4-745-CD (an availability proxy); sites
are flagged archetypes; regulation drift is a seeded draw.
