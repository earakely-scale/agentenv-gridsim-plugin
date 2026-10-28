# GridSimEnv desk v5 pilot: pre-registration (GPT-6.1 Sol, The Market Floor)

Committed on `desk` before the first v5 pilot episode; not part of the v5 board. Deviations appended after the run.

## Code and tasks
- `desk-v5-freeze` (be6ff8c): v5 = the v3 desk plus DAM price impact. At each DAM close the battery's curves are
  re-cleared against that day's 60-day disclosed DAM offer stack (NP3-966-ER) with the site's own resource carved out;
  the book is shifted so that, without the battery, it posts the real price (exact on all 576 checked hours). AS and
  RT stay price-taker; no market-power mitigation is applied (labelled).
- `desk-v5-pilot` (63ed11d, refs 3b93a2a): the two v3 pilot battery-days, 2026-04-20 S01 (PV) and 2026-08-14 S03.

## Known before the run
On these days the re-clear moves the anchor's P by $0.44 and $5.61 and the hindsight by about $100: a 100–150 MW ESR
barely moves ERCOT's DAM price. v5 results are expected to track v3 unless a model takes much larger DAM positions.

## Model, settings and criteria
GPT-6.1 Sol, as the v3 pilot (effort high, $5 an episode, lane $12, parallel 2). Pass when both episodes end normally,
the DAM prices the agent sees after the close are the re-cleared ones (and equal the real price when its awards are
zero), the statement sums to P, and the grade replays from the Episode JSON.

## Outcome (appended after the run)
Both episodes ended normally with no tool error. `desk-v5-2026-04-20-S01`: P −$6,983 (45 turns, $3.33); selling about
70 MW in eight DAM hours lowered the re-cleared price by $0.02–0.14/MWh. `desk-v5-2026-08-14-S03`: P $10,416 (28 turns,
$1.40); 30–110 MW sales lowered it by $0.01–0.06/MWh. In every hour without an award the price the agent saw equals the
real DAM price; statements sum to P. Pass.
