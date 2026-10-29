"""Score a GridSim desk episode for training by its hindsight capture C = (P - P_idle) / (P_hind - P_idle) floored at
-1: idle 0, gains count fully and losses count against, down to -1; C undefined (P_hind - P_idle <= $1) counts as 0.
A verifier step's score is clamped to [0, 1], so the score is (max(C, -1) + 1) / 2 and the training reward is
2 * score - 1. Read through the env's hidden grade tool as the hook role, as gridsim-desk-verifier reads R; an episode
that is not over raises, so the run is not scored."""

import json

import httpx

ROLE = "hook"
FLOOR = -1.0


async def verify(mcp_url: str) -> list[dict]:
    grade = await _hidden(mcp_url, "grade")
    capture = grade.get("capture")
    floored = 0.0 if capture is None else max(capture, FLOOR)
    return [{"criterion": "capture", "description": "(max(C, -1) + 1) / 2, C = (P - P_idle) / (P_hind - P_idle), 0 "
                                                    "when undefined; the training reward is 2 * score - 1",
             "result": floored >= 1.0, "score": (floored + 1.0) / 2.0, "weight": 1.0,
             "metadata": {"reward": floored} | {k: grade.get(k) for k in ("capture", "c_undefined", "valid", "p",
                                                                           "p_idle", "p_hind", "p_anchor")}}]


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
