"""Score a GridSim forecast window with the reward of the window it executed (1.0 at the information-matched rolling
MILP on the desk's P50 guide; blind: on persistence); a window that never finished, or whose audit failed, raises, so
the run is not scored. Weight-0 rows carry the audit, the reward against hindsight, the paired gap to the anchor,
beating it, the reward against the three-scenario re-planner, the value of forecasts (blind), missed DAM gates and the
stored baselines."""

from agentenv_protocol import client


def row(criterion: str, description: str, value, score: float, result: bool) -> dict:
    return {"criterion": criterion, "description": description, "result": result, "score": score, "weight": 0.0,
            "value": value}


async def verify(mcp_url: str) -> list[dict]:
    w = (await client.get_data(mcp_url.removesuffix("/mcp"))).parts[0].data
    if not w.get("task_id"):
        raise RuntimeError("the gridsim-forecast env has no window: no apply_server_config "
                           "urn:gridsim:forecast-load/v1 ran")
    if not w["done"] or not w["audit"]["ok"]:
        raise RuntimeError(f"the window can't be scored: done {w['done']}, audit {w['audit']}")
    g = w["grade"]
    reward, r_hind, paired, roll3 = g["reward"], g["r_hind"], g["paired_vs_anchor"], g["r_roll3"]
    naive = ((g.get("baselines") or {}).get("naive") or {}).get("reward")
    rows = [{"criterion": "gridsim", "description": "the window's reward, 1.0 at the information-matched rolling MILP "
                                                    "on the desk's P50 guide (blind: on persistence)",
             "result": reward >= 1.0, "score": reward, "weight": 1.0, "episode": w},
            row("audit", "every watch got its notices and deployments in order before the agent's next call, none "
                         "early or twice; every forecast served was revealed by then and matches its sha, no DA price "
                         "or MCPC before its results, no RT price or PV actual before its hour ended, each DAM entry "
                         "accepted at its own gate; every output replays byte for byte", True, 1.0, True),
            row("r_hind", "the reward against hindsight: clip(0.2 + 0.8 (P - P_idle) / (P_hind - P_idle), 0, 1)",
                r_hind, r_hind or 0.0, r_hind is not None and r_hind >= 1.0),
            row("paired_vs_anchor", "(P - P_anchor) / (P_hind - P_idle); passes at or above the anchor", paired,
                float(paired is not None and paired >= 0), paired is not None and paired >= 0),
            row("beats_anchor", "the window's profit beat the anchor's", g["beats_anchor"], float(g["beats_anchor"]),
                bool(g["beats_anchor"])),
            row("r_roll3", "the reward against the re-planner on the P10/P50/P90 scenarios' mean", roll3, roll3 or 0.0,
                roll3 is not None and roll3 >= 1.0)]
    if g["tier"] == "blind":
        fv = g["forecast_value"]
        rows.append(row("forecast_value", "the blind run's reward against P_roll, the anchor that reads the forecasts",
                        fv, fv or 0.0, fv is not None and fv >= 1.0))
    return rows + [
        row("dam_missed", "DAM gates without an accepted hour", g["dam_missed"], float(not g["dam_missed"]),
            not g["dam_missed"]),
        row("baselines", "the stored baselines' profit and reward on this window; passes when the window beat naive's "
                         "reward", g.get("baselines"), float(naive is not None and reward > naive),
            naive is not None and reward > naive)]
