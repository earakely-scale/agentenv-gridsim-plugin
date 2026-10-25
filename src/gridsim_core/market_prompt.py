"""The v5 Market Floor's system prompt, opening message, per-watch note, tool schemas and the path B sprint prompt; the
gridsim-market env and training share them, so the agent reads the same text on every path."""

from __future__ import annotations

import json

from gridsim_core.market import DAM_CLOSE, DATA_CALLS, PLANNING_CALLS, Session
from gridsim_core.market_stack import DayStore

_JOB = """You run a battery portfolio (seat bess-A) large enough to move the ERCOT day-ahead price. For one operating \
day D you offer it into the day-ahead market (DAM) as an hourly curve before the DAM closes at 10:00 on D-1. The \
market re-clears ERCOT's real offers and bids of that day, with four other seats (a rival battery, a gas fleet, a wind \
and solar portfolio and a retailer) bidding as they really did. Times are Central Prevailing Time (CPT)."""

_MARKET = """The market
- Each hour of D is its own uniform-price auction on one node at the ERCOT hub average. Everyone awarded in an hour \
gets that hour's clearing price. The rest of the market is large and its curve sets the price; your MW move it along \
that curve, so selling more in an hour lowers that hour's price and buying more raises it.
- Prices and offers are in $/MWh at the hub; the cap is the era's offer cap and the floor is -$250.
- Your offer, per hour: sell blocks [[mw, price], ...] (sold when the clearing price is at or above the price) and buy \
blocks [[mw, price], ...] (bought when it is at or below). MW are whole multiples of grid_mw; sells add up to at most \
p_mw, buys too; at most 10 blocks an hour; every buy price below every sell price. An hour you leave out offers \
nothing. In an hour you list, leave a side out (or write null or "keep") to keep it as it stands in your last \
accepted offer (nothing before your first); [] offers nothing on that side. A block priced exactly at the clearing \
price may be partly awarded (rounded down to grid_mw).
- Mitigation: in an hour where you offer MW above your reference price (get_private_costs) by more than \
max($10, 50%), and pricing those MW at the reference would lower the clearing price by at least max($5, 10%), the \
market prices them at the reference."""

_SETTLE = """Delivery and settlement
- Awards are financial: an award of q MW in an hour settles q x the clearing price.
- {delivery}
- Any MW you deliver above or below your award settles at that hour's real-time (RT) price, which you do not know \
in advance and which does not respond to your offers.
- Charging c MWh stores eta x c; delivering d MWh removes d; SoC stays within 0..e_mwh. Each MWh discharged costs \
c_deg. Every MWh of SoC short of s_end_min_mwh at 24:00 is bought back at max(the day's highest real DAM price, \
$50/MWh) / eta.
- Profit = awards x price + deviations x RT price - degradation - the end shortfall. Make it as large as you can."""

_SPRINT = """How the floor runs
- It is D-1 09:00 and the DAM closes at 10:00: this is your only decision. Read the situation; use get_forecast and \
get_disclosure (6 calls between them) and up to {calls} planning calls (check_offer and submit_offer share them).
- check_offer estimates the clear from the disclosure-based forecast, not the true market.
- submit_offer is final: the market clears and the day settles. A refused offer is not a submission; a valid offer \
with no blocks is idle. Never end without a valid submit_offer."""

_DAY = """How the day runs
- Watches: D-1 06:00 and 09:00 (offers and contracts), 13:30 (awards), then D 00:00, 06:00, 12:00 and 18:00, plus a \
watch when ERCOT issues a notice. At each watch you get {calls} planning calls (check_offer, submit_offer, \
check_schedule and commit_schedule share them) and {data} data calls (get_forecast and get_disclosure); unused calls \
do not carry over. advance ends the watch; the day goes on until advance returns "done": true.
- Before 10:00 you may submit_offer as often as you like (the last accepted one counts) and sign up to 3 contracts \
for differences (CfDs) on the hub DAM price with the retailer (propose_contract, respond_contract). CfDs settle \
strike minus price on their own row, outside your profit.
- From 13:30 you may set your physical schedule (MW per hour) with commit_schedule; hours before the freeze line \
(the next full hour plus 1 hour) cannot change, and null or "keep" for an hour keeps its MW as it stands. An hour's \
RT price is shown only after the hour ends."""

_INFO = """What you can see
- get_disclosure: ERCOT publishes every DAM offer and bid 60 days later; you may read any disclosed day 61 to 90 days \
before D as the whole market's aggregate supply or demand curve (anonymised). The latest disclosed day is in the \
situation.
- get_forecast: D's day-ahead load forecast, wind and solar (the last complete day, as persistence), yesterday's DAM \
results and settled RT prices.
- message_agent reaches the other seats; they do not read messages. Do not discuss prices or offers with them."""


def system_prompt(tier: str = "floor-sprint") -> str:
    delivery = ("Your battery delivers its awards as far as its state of charge (SoC) allows, hour by hour."
                if tier == "floor-sprint" else
                "Your battery follows its awards (as far as SoC allows) until you commit a physical schedule.")
    how = (_SPRINT.format(calls=PLANNING_CALLS) if tier == "floor-sprint"
           else _DAY.format(calls=PLANNING_CALLS, data=DATA_CALLS))
    return "\n\n".join([_JOB, _MARKET, _SETTLE.format(delivery=delivery), how, _INFO])


def situation_text(s: Session) -> str:
    return json.dumps(s.situation(), ensure_ascii=False, separators=(",", ":"))


def opening(s: Session) -> str:
    left = max(0, DAM_CLOSE - s.minute)
    return (f"It is {s.situation()['time']} CPT, {left} minutes before the DAM closes. Your situation:\n"
            f"{situation_text(s)}")


def watch_text(s: Session) -> str:
    if s.done:
        return "The day is over."
    return f"Watch {s.watch} at {s.situation()['time']} ({s.phase}). Read the situation, act, then advance."


def tool_schemas(tier: str = "floor-sprint") -> list[dict]:
    blocks = {"anyOf": [{"type": "array", "items": {"type": "array", "items": {"type": "number"}, "minItems": 2,
                                                     "maxItems": 2}},
                        {"type": "string", "enum": ["keep"]}],
              "description": 'Blocks [[mw, price], ...]; leave out, null or "keep" to keep this side of your last '
                             "accepted offer, [] for none."}
    offer = {"type": "object", "properties": {"hours": {"type": "array", "items": {
        "type": "object", "properties": {"he": {"type": "integer", "minimum": 1, "maximum": 24}, "sell": blocks,
                                         "buy": blocks}, "required": ["he"]}}}, "required": ["hours"]}
    none = {"type": "object", "properties": {}}
    out = [_fn("get_situation", "The floor's state as JSON. Free.", none),
           _fn("get_forecast", "A forecast or public series: load, wind, solar, dam_prices or rt_prices. A data call.",
               {"type": "object", "properties": {"kind": {"type": "string", "enum": ["load", "wind", "solar",
                                                                                      "dam_prices", "rt_prices"]},
                                                  "issued_at": {"type": "string"}}, "required": ["kind"]}),
           _fn("get_disclosure", "A disclosed day's aggregate supply or demand curve, one hour (64 points) or all 24 "
                                 "(16 each). Only days at least 60 days old. A data call.",
               {"type": "object", "properties": {"op_date": {"type": "string"}, "side": {"type": "string",
                                                                                          "enum": ["supply", "demand"]},
                                                  "hour": {"type": "integer"}}, "required": ["op_date"]}),
           _fn("get_private_costs", "Your seat's costs and mitigation reference prices. Free.", none),
           _fn("check_offer", "Validate an offer and estimate its clear on the disclosure-based forecast. A planning "
                              "call.", {"type": "object", "properties": {"offer": offer}, "required": ["offer"]}),
           _fn("submit_offer", "Submit the DAM offer." + (" Final: the market clears and the floor ends."
                                                         if tier == "floor-sprint" else " The last one before 10:00 "
                                                                                        "counts.") + " A planning call.",
               {"type": "object", "properties": {"offer": offer}, "required": ["offer"]})]
    if tier == "floor-day":
        mw = {"anyOf": [{"type": "number"}, {"type": "string", "enum": ["keep"]}]}
        plan = {"type": "object", "properties": {"plan": {"type": "array", "items": mw,
                                                          "description": 'MW per hour from from_hour; null or "keep" '
                                                                         "keeps an hour's MW as it stands."},
                                                 "from_hour": {"type": "integer", "minimum": 0, "maximum": 23}},
                "required": ["plan"]}
        out += [_fn("get_award", "Your awards and the clearing prices, from 13:30. Free.",
                    {"type": "object", "properties": {"op_date": {"type": "string"}}}),
                _fn("check_schedule", "Dry-run a physical schedule (MW per hour from from_hour). A planning call.", plan),
                _fn("commit_schedule", "Set the physical schedule from from_hour, all or nothing. A planning call.",
                    plan),
                _fn("advance", "End this watch. Free.", none),
                _fn("propose_contract", "Propose a CfD on the hub DAM price to the retailer (mw > 0: you sell it). "
                                        "Before 10:00 only.",
                    {"type": "object", "properties": {"counterparty": {"type": "string"}, "kind": {"type": "string"},
                                                      "hours": {"type": "array", "items": {"type": "integer"}},
                                                      "mw": {"type": "number"}, "strike_usd": {"type": "number"},
                                                      "op_dates": {"type": "array", "items": {"type": "string"}}},
                     "required": ["hours", "mw", "strike_usd"]}),
                _fn("respond_contract", "Accept or reject a countered CfD.",
                    {"type": "object", "properties": {"contract_id": {"type": "string"},
                                                      "action": {"type": "string", "enum": ["accept", "reject"]},
                                                      "strike_usd": {"type": "number"}},
                     "required": ["contract_id", "action"]}),
                _fn("message_agent", "Send a note to another seat.",
                    {"type": "object", "properties": {"agent_name": {"type": "string"}, "text": {"type": "string"}},
                     "required": ["agent_name", "text"]})]
    return out


def _fn(name: str, description: str, parameters: dict) -> dict:
    return {"type": "function", "function": {"name": name, "description": description, "parameters": parameters}}


_ONESHOT = """This is a one-shot version: reply with one submit_offer tool call whose offer argument is your whole \
offer for D. The latest disclosed day's aggregate curves are summarised below the situation."""


def sprint_messages(task: dict, store: DayStore | None = None) -> list[dict]:
    """The path B prompt: the rules card, the one-shot note, the situation and the latest disclosure (16 points/hour)."""
    s = Session(task, "floor-sprint", store=store)
    latest = s.situation()["public"]["disclosure_latest"]
    disc = json.loads(s.call("get_disclosure", {"op_date": latest, "side": "supply"}))
    dem = json.loads(s.call("get_disclosure", {"op_date": latest, "side": "demand"}))
    note = json.dumps({"disclosure": {"op_date": latest, "supply": disc.get("hours"), "demand": dem.get("hours")}},
                      separators=(",", ":"))
    return [{"role": "system", "content": system_prompt("floor-sprint") + "\n\n" + _ONESHOT},
            {"role": "user", "content": opening(s) + "\n" + note}]
