"""Score a hybrid GridSim day with the reward of the day it executed (1.0 at the information-matched rolling MILP); a
day that never finished, or whose audit failed, raises, so the run is not scored. Weight-0 rows carry the audit,
hindsight capture, the energy-only anchor's reward, the AS share, clipping recovered and failure-to-provide."""

from agentenv_protocol import client


def row(criterion: str, description: str, value, score: float, result: bool) -> dict:
    return {"criterion": criterion, "description": description, "result": result, "score": score, "weight": 0.0,
            "value": value}


async def verify(mcp_url: str) -> list[dict]:
    day = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not day.get("task_id"):
        raise RuntimeError("the gridsim-hybrid env has no day: no apply_server_config urn:gridsim:live-load/v1 ran")
    if not day["done"] or not day["audit"]["ok"]:
        raise RuntimeError(f"the day can't be scored: done {day['done']}, audit {day['audit']}")
    g = day["grade"]
    capture, energy, share, clip = (g["capture_vs_hindsight"], g["energy_only_reward"], g["as_share"],
                                    g["clip_recovered_pct"])
    return [{"criterion": "gridsim", "description": "the day's reward, 1.0 at the information-matched rolling MILP",
             "result": g["reward"] >= 1.0, "score": g["reward"], "weight": 1.0, "episode": day},
            row("audit", "every watch got its notices and deployments in order before the agent's next call, none "
                         "early or twice, no RT price or RT MCPC before its hour ended, and every output replays byte "
                         "for byte", True, 1.0, True),
            row("hindsight_capture", "(P - P_idle) / (P_hind - P_idle)", capture, capture or 0.0,
                capture is not None and capture >= 1.0),
            row("energy_only", "the energy-only rolling MILP's reward on this day against this tier's anchor; passes "
                               "when the day beat it", energy, energy or 0.0,
                energy is not None and g["reward"] > energy),
            row("as_share", "AS revenue / (energy gain + AS revenue)", share, share or 0.0, bool(share)),
            row("clip_recovered", "PV above the meter limit the battery caught, as a fraction of the clippable MWh",
                clip, (clip or 0.0) / 100, bool(clip)),
            row("ftp", "failure-to-provide MW-h charged", g["ftp_mwh_charged"],
                1.0 if not g["ftp_mwh_charged"] else 0.0, not g["ftp_mwh_charged"])]
