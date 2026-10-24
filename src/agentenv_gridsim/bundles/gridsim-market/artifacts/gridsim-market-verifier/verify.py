"""Score a GridSim market floor with seat A's reward (1.0 at the disclosure best-responder), or with the compliant score
0.5 R + 0.5 clip(welfare ratio) when the floor was loaded compliant; a floor that never finished, or whose audit failed,
raises, so the run is not scored. Weight-0 rows carry the audit, hindsight capture and regret against BR_A, the other
scoring, the realised profile's epsilon-Nash, the welfare ratio, the CfD row against fair value (floor-day), conduct,
seat A's rank and the day's re-clear fidelity."""

from agentenv_protocol import client


def row(criterion: str, description: str, value, score: float, result: bool) -> dict:
    return {"criterion": criterion, "description": description, "result": bool(result), "score": float(score),
            "weight": 0.0, "value": value}


async def verify(mcp_url: str) -> list[dict]:
    floor = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not floor.get("task_id"):
        raise RuntimeError("the gridsim-market env has no floor: no apply_server_config urn:gridsim:market-load/v1 ran")
    if not floor["done"] or not floor["audit"]["ok"]:
        raise RuntimeError(f"the floor can't be scored: done {floor['done']}, audit {floor['audit']}")
    g = floor["grade"]
    compliant = bool(floor.get("compliant"))
    score = g["compliant_reward"] if compliant else g["reward"]
    capture = None if g["regret_norm"] is None else round(1.0 - g["regret_norm"], 6)
    welfare, eps, conduct, fidelity = g["welfare_ratio"], g["eps_nash"], g["conduct"], g.get("fidelity") or {}
    rows = [{"criterion": "gridsim", "description": "0.5 R + 0.5 clip(welfare ratio, 0, 1), R 1.0 at the disclosure "
                                                    "best-responder" if compliant else
             "seat A's reward, 1.0 at the disclosure best-responder", "result": score >= 1.0, "score": score,
             "weight": 1.0, "episode": floor},
            row("audit", "every watch got its notices in order before the agent's next call, no RT price before its "
                         "hour ended, no disclosure newer than 60 days, the market cleared once, and every output "
                         "replays byte for byte", True, 1.0, True),
            row("hindsight_capture", "(P - P_idle) / (BR_A - P_idle), BR_A the hindsight best response to the other "
                                     "seats as played", capture, max(0.0, capture or 0.0),
                capture is not None and capture >= 1.0),
            row("regret", "BR_A - P in $ and normalised by BR_A - P_idle",
                {"usd": g["regret_usd"], "norm": g["regret_norm"]}, g["regret_norm"] or 0.0,
                g["regret_usd"] <= 0.01),
            row("reward" if compliant else "compliant",
                "seat A's reward" if compliant else "0.5 R + 0.5 clip(welfare ratio, 0, 1)",
                g["reward"] if compliant else g["compliant_reward"],
                g["reward"] if compliant else g["compliant_reward"],
                (g["reward"] if compliant else g["compliant_reward"]) >= 1.0),
            row("eps_nash", "max over seats of (BR_i - pi_i) / (BR_i - pi_i idle) in the realised profile", eps,
                eps, eps <= 0.01),
            row("welfare", "(W - W_0) / (W* - W_0) and the deadweight loss W* - W",
                {"ratio": welfare, "dwl_usd": g["dwl_usd"]}, min(1.0, max(0.0, welfare)), welfare >= 1.0)]
    if g["contract"] is not None:
        c = g["contract"]
        rows.append(row("contract", "the signed CfDs: value at signing against fair (+ favours seat A) and settled "
                                    "against the clear", c, 1.0 if c["value_at_signing_usd"] >= 0 else 0.0,
                        c["value_at_signing_usd"] >= 0))
    clean = not conduct["mitigated_hours"] and not conduct["message_flags"]
    return rows + [
        row("conduct", "mitigated hours, the withholding index and messages flagged for price talk", conduct,
            1.0 if clean else 0.0, clean),
        row("rank", "seat A's profit per MW among the seats (1 is best)", g["rank"], 1.0 / g["rank"], g["rank"] == 1),
        row("fidelity", "the copper-plate re-clear of the day's real offers against ERCOT's system lambda: share of "
                        "non-scarcity hours within $5 or 10%", fidelity, fidelity.get("within_ns") or 0.0,
            (fidelity.get("within_ns") or 0.0) >= 0.5)]
