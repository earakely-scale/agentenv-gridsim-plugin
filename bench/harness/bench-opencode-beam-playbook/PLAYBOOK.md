# Desk playbook

`optimize` turns the desk forecast into ERCOT-ready DAM and RT curves, AS offers and a COP. Your edge: ask it the
right question, send all of it before each gate, re-plan whenever the picture changes, and fix what is refused.

## A planning wake (every wake except a reminder you set only as a note)
1. Read little first: the wake message already lists the events, notices and deadlines. A full plan costs 4 to 6 of
   your 14 calls (optimize, one DAM call per open day, one RT call per day, one COP call per day). Skip
   check_submission for optimiser output; it validates.
2. `optimize` with `price_view: "desk"`, `risk: 1.5`, `constraints: {"dam_position": "spread"}`, the desk's house
   setting, tuned on separate tuning days.
   - `spread` lets the DAM curves take the forecast DAM/RT spread. `physical`, the default when you leave it out, caps
     the DAM curves at the planned dispatch, so most DAM hours go in at 0 MW and the day-ahead position is lost.
   - The projected P barely moves between settings; do not pick the setting by it.
   - Risk is your call within 1 to 2: wider when notices or a wide P10-P90 band point to spikes or scarcity, about 1
     when prices are calm. Below 1 the curves close in on the median and capture less.
   - Your own price view goes in at the top level: `{"dam": [24 per day], "rt": [24 or 96 per day]}` or
     `{"scenarios": [...]}`. Other keys are ignored without an error: the tool then plans on one desk-P50 path for
     both markets.
3. Send the proposal in the same turn, numbers as given:
   - `submit_dam_offers` per day in `dam_curves`: that day's `curves` AND its `dam_as_offers` in ONE call. Never send
     AS without the curves: a day with no DAM curve sells no DAM energy, and without RT curves runs on ERCOT's proxy.
   - `submit_rt_offers` per day in `rt_curves`: `curves` AND that day's `rt_as_offers`.
   - `update_cop` with the proposal's `cop` rows (hours, hbsoc_mwh).
4. End the turn.

## Gates and timing
- The first DAM closes at 10:00, four hours after the start: at the start wake, plan and submit before any research.
- A later day's DAM: plan at its `dam_morning` wake (06:00 the day before), again after anything that changes the
  picture, before 10:00.
- RT offers for a day open at 18:00 the day before; set reminders for them at 18:00, not before.
- RT curves from a proposal reach only 12 hours ahead. When they lapse, SCED runs your DAM curve, else the proxy.
  Re-plan at every checkpoint (00:00, 06:00, 12:00, 18:00), DAM results, adjustment open and every notice, outage or
  deployment wake, through the LAST operating day until the episode ends. The last day pays like the first.
- Skip a wake only when nothing has changed and your RT curves still cover at least the next 6 hours.

## Judgment: where you beat the plain optimiser
- Outage or derate: `update_cop` the limits (hsl_mw, lsl_mw, status) within 60 minutes, then optimize again; it
  plans within the COP.
- EEA, scarcity, extreme-weather or price-spike notices: re-plan now and consider a wider risk.
- Refusals: read the code, fix and resend in the same turn:
  - COP-02: clip hbsoc into [min_soc, max_soc] within the site's limits; COP-03: smooth hbsoc so each hour-to-hour
    change fits the charge or discharge rate; COP-05: that hour froze, drop it;
  - EBOC-06 or ASO-06: the gate is closed or not open yet, wait for it; ASO-02: one mw and one price per listed hour.
- Do not hand-edit the proposal's numbers. If a notice tells you something the forecast lacks, re-run optimize with
  your own price view and send that proposal.
