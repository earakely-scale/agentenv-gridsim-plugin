GridSim market, "The Market Floor": offer a battery portfolio large enough to move the price (seat bess-A) into ERCOT's day-ahead market, re-cleared on one node from the real 60-day disclosure of every offer and bid of the day, with a rival battery, a gas fleet, a wind and solar portfolio and a retailer bidding as they really did; graded against the disclosure best-responder.

Every task deploys the env registered as `gridsim-market` on the gateway provider (run `agent-env gridsim setup` once;
it is the `gridsim` image) and loads one floor of the market fixture pack at a tier through the env's
`urn:gridsim:market-load/v1` extension: `floor-sprint` (one decision at D-1 09:00, the DAM closing at 10:00; the
floor-day tools are hidden from the agent's role) or `floor-day` (watches at D-1 06:00 and 09:00, the awards at 13:30,
then the operating day at 00:00, 06:00, 12:00 and 18:00, plus a watch per ISO notice; offers re-submittable and CfDs
with the retailer until 10:00, then the physical schedule). It hides the env's `grid_notice` tool from the agent,
registers one trigger per watch after the first that delivers the watch's notices when the agent's `advance` opens it,
and arms the gateway clock frozen at watch 0. After the play, `urn:gridsim:end-floor/v1` clears the market if it hasn't
cleared, runs the day on the awards (or the committed schedule) and grades it. The `gridsim-market-verifier` artifact
reads the floor from the env's `data/get` and scores seat A's reward, or, on a compliant task, 0.5 R + 0.5 clip(welfare
ratio); the audit, hindsight capture and regret against BR_A, the other scoring, epsilon-Nash, the welfare ratio, the
CfD row, conduct, rank and the day's re-clear fidelity are weight-0 rows. A floor that never finished, or whose audit
failed, fails the step, so the run is not scored.

- `sprint` plays floor-sprint on 2024-08-20 (an ERCOT summer peak) with a 580 MW, 2 h portfolio, with the gridsim-llm
  agent (`agent-env gridsim setup --agent`, `--model <litellm model id>`), 6 turns.
- `sprint-compliant` is the same floor scored compliant.
- `day` plays floor-day on 2026-07-21 (after RTC+B) with a 1,160 MW, 2 h portfolio, 36 turns.
- `aug24-0820` is the 2024-08-20 showcase: floor-day with a 1,500 MW, 4 h portfolio, scored compliant.
- `wiring-noplay` runs `day` without the agent and needs no model: the floor ends with no offer and scores 0, its
  audit passing.
- `wiring-late` plays `day` without the agent through the env's `urn:gridsim:market-calls/v1` (seat A's calls made by
  the harness): the disclosure best-responder's offer at 09:00, then a late idle offer after 10:00, which is refused,
  so the 09:00 offer stands (0.828241).
- `wiring-disclosure` plays `sprint` the same way: `get_disclosure` refuses a day newer than 60 days and one older than
  the 90-day window, serves the latest disclosed day, and an idle offer scores 0.2.

Market: ERCOT 60-Day DAM Disclosure Reports (NP3-966-ER), DAM System Lambda (NP4-523-CD) and hub settlement point
prices (NP4-180-ER, NP6-905-CD), public ERCOT data re-cleared as derived, anonymised aggregates; ERCOT does not endorse
this work. Load, wind and solar from EIA-930; CT heat rates from EIA-923 (public domain). Copper plate, AS truncation,
commitment, mitigation and private costs are modelled.
