"""Score a GridSim desk episode with its reward R (desk contract 9.1), read through the env's hidden grade tool as the
hook role; hindsight capture C and the references ride along as metadata and weight-0 rows. An episode that is not
over raises, so the run is not scored."""

import json

import httpx

ROLE = "hook"


async def verify(mcp_url: str) -> list[dict]:
    grade = await _hidden(mcp_url, "grade")
    episode = await _hidden(mcp_url, "episode")
    capture = grade.get("capture")
    refs = {k: grade.get(k) for k in ("p", "p_idle", "p_anchor", "p_hind", "p_hind_phys", "p_operator_replay",
                                      "p_operator_actual") if k in grade}
    return [{"criterion": "gridsim-desk", "description": "R = clip(0.2 + 0.8 (P - P_idle)/(P_anchor - P_idle), 0, 1); "
                                                         "0 with no accepted submission",
             "result": grade["reward"] >= 1.0, "score": grade["reward"], "weight": 1.0,
             "metadata": {"grade": grade, "capture": capture, "refs": refs}, "episode": episode},
            {"criterion": "hindsight_capture", "description": "C = (P - P_idle) / (P_hind - P_idle)",
             "result": capture is not None and capture >= 1.0, "score": capture or 0.0, "weight": 0.0},
            {"criterion": "valid", "description": "at least one accepted DAM or RT submission",
             "result": bool(grade.get("valid")), "score": 1.0 if grade.get("valid") else 0.0, "weight": 0.0}]


async def _hidden(mcp_url: str, tool: str) -> dict:
    async with httpx.AsyncClient() as http:
        r = await http.post(f"{mcp_url.removesuffix('/mcp')}/step", headers={"AgentEnv-Role": ROLE}, timeout=300,
                            json={"action": "call_tool", "tool_name": tool, "arguments": {}})
    if r.status_code >= 400:
        raise RuntimeError(f"the desk's {tool} failed (HTTP {r.status_code}): {r.text[:500]}")
    body = r.json()
    out = "".join(c.get("text", "") for c in body.get("content") or [] if c.get("type") == "text")
    if body.get("isError"):
        raise RuntimeError(f"the desk's {tool} failed: {out[:500]}")
    return json.loads(out)
