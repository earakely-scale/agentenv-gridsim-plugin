# The live board: sealed schedules on ERCOT's day-ahead market

Pre-registered in [`docs/prereg/v1-live-board.md`](../docs/prereg/v1-live-board.md); run by
[`scripts/live/live.py`](../scripts/live/live.py) on a dedicated box; published on the Hugging Face dataset
[`earakely-scale/GridSimEnv-AgentEnv`](https://huggingface.co/datasets/earakely-scale/GridSimEnv-AgentEnv/tree/main/live)
under `live/`, where each file's commit time is its public timestamp. This folder mirrors it. The board's page is
[`board.html`](https://earakely-scale-gridsimenv-agentenv.static.hf.space/board.html) on the Space.

## Files
- `sealed/D.json` (`gridsim.live.sealed/v1`): written about 20 hours before the DAM for delivery day D closes
  (10:00 Central on D−1). The 45 task rows without prices, their inputs digest, the check that ERCOT showed no DAM rows
  for D, and per agent its model, setting and, per task, the submitted 24 actions, the written forecast, the reply,
  tokens and cost.
- `graded/D.json` (`gridsim.live.graded/v1`): written after ERCOT posts D's prices. D's prices at the 15 points, the
  seal's commit and whether it was valid, the references per task (idle, hindsight optimum, blind anchor), and per
  agent and task: C, R on the blind anchor's scale, the profit in $ and in $ per MW.
- `board.json` (`gridsim.live.board/v1`): the cumulative board over graded days with a valid seal, the API spend and
  the sealed-then-graded timeline with each commit.

## Checks before the first seal
- The 4B's adapters match the registered archives (sha256 `69c5f4a6…`, `05c1dcb2…`, `677547ef…`; RL step 237).
- The 4B's serving on the live box (vLLM 0.29.0, one A10G) on the 331 tasks of `ercot-dam-v1-fresh-2026-10-blind`,
  sampled as registered: **C 0.835** against the registered 0.841 (inside the pre-registered 0.03), and 81% of the
  schedules identical to the registered run's (sampling on a different GPU).
