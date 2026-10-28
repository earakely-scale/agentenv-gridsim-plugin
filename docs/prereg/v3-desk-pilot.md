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
