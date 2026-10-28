GridSim desk: trade one real ERCOT battery (an energy storage resource at its own node) as a QSE's battery desk from the day-ahead market through real time, on a frozen virtual clock that moves only between turns; graded by settlement against an information-matched anchor.

Every task deploys the gridsim-desk env for its layer and era (`gridsim-desk-v2`..`v5` post-RTC+B, `-pre` for
pre-RTC+B days; `agent-env gridsim setup` registers them) and loads one episode through `urn:gridsim:desk-load/v1`.
The env's eleven desk tools are the agent's; `next_wakeup`, `advance_to`, `episode` and `grade` are hidden by default
and shown to the `hook` role only, and the gateway's `get_time` is hidden from the agent. The clock is armed frozen
at D-1 06:00 CPT and the agent is prompted with the start wake. After each turn the `gridsim-desk-hook` post-turn
hook reads the desk's next wake-up (market milestones, notices, outages, deployments and the agent's reminders),
takes the earlier of it and the gateway triggers' `next_event_at`, advances the clock there, has the env run the
market to that minute and wakes the agent with the wake message; when nothing is left it runs the market to the end
and ends the conversation. `gridsim-desk-verifier` reads the grade through the hidden `grade` tool: the score is the
reward R, with the hindsight capture C and the references in the result's metadata.

`agent-env gridsim desk-tasks --pack <pack>` writes a bundle of a desk pack's tasks; `scripts/desk_e2e.py` plays one
end to end through the framework's Episode API, with a core policy ($0) or a model, and checks it against the
in-process Session byte for byte.

Prices and system data: ERCOT public reports; ERCOT does not endorse this work. Weather alerts: NWS.
