# GridSimEnv desk v3 pilot: pre-registration (GPT-6.1 Sol, Sun, Storage and Reserves)

Committed on `desk` before the first v3 pilot episode. The pilot proves the v3 layer on real days before the v3 eval
runs; it is not part of the v3 board. Anything done differently is logged under "Deviations", appended after the run.

## Code and tasks
- `desk-v3-freeze` (acff0cd): v3 adds the five ERCOT ancillary services (RegUp, RegDn, RRS, ECRS, Non-Spin) in the DAM
  and post-RTC+B real time, ERCOT proxy AS offers, DAM AS buy-back at the RT MCPC, AS duration rules on state of
  charge, deployments, capacity-short charges, hub 5-minute LMPs, and a co-located PV option (modelled from ERCOT
  regional solar). The anchor is 1.5/spread (contract §9.3).
- `desk-v3-pilot` (01b017f, refs 1a2340e): `desk-v3-2026-04-20-S01` (Far West, 100 MW / 104 MWh, with 60 MW AC of
  modelled PV; RT LMP 35–244 $/MWh, RT MCPC up to $62) and `desk-v3-2026-08-14-S03` (North, 120 MW / 187 MWh,
  a quiet day).

## Model and settings
GPT-6.1 Sol, LiteLLM Responses API, reasoning effort high, path B' on the g5 run host; v3 budgets (40 turns,
12 calls a turn); episode cap $5, lane cap $12, parallel 2.

## Pass criteria (each checked and reported)
1. Both episodes end normally with no runner or tool server error.
2. AS offers (DAM and RT) are accepted or rejected with ERCOT-style codes; at least one AS submission per episode.
3. The statement carries the AS lines (DAM AS capacity, RT AS imbalance/buy-back, capacity-short), the per-line sum
   equals P, and the grade replays from the Episode JSON to the cent.
4. The PV site's output appears in telemetry and settlement and is labelled modelled.
5. Cost per episode measured, to size the v3 eval.

## Outcome (appended after the run)
Both episodes ended normally with no tool error (25 and 27 turns, $1.40 and $1.42, 16–17 min each).
- `desk-v3-2026-04-20-S01` (PV): P $4,820 (anchor $7,673, operator replay $10,549, operator actual −$5,259, hindsight
  $127,658). Lines: DAM energy +$57,069, RT energy imbalance −$65,423 (DAM sold beyond what was then delivered),
  PV energy +$14,829 (modelled), RT AS +$691. One DAM submission rejected with EBOC-07, one COP accepted with COP-05.
- `desk-v3-2026-08-14-S03`: P $4,477 (anchor −$1,448, operator replay −$194, hindsight $23,054). Lines include DAM AS
  capacity +$867 and RT AS imbalance −$365.
Criteria 1, 3, 4 and 5 met; AS awards settle in both episodes (criterion 2). Pass.
