"""Client for GridSimEnv Desk: an OpenEnv MCP client over the desk's eleven tools and end_turn.

    from gridsim_desk import GridSimDesk

    with GridSimDesk(base_url="https://earakely-scale-gridsimenv-openenv.hf.space").sync() as env:
        env.reset(split="bench", index=25)
        print(env.call_tool("get_asset_status"))
        env.call_tool("end_turn", response="waiting for the DAM results")
"""

from openenv.core.mcp_client import MCPToolClient


class GridSimDesk(MCPToolClient):
    """A WebSocket session on a GridSimEnv Desk server: one battery window at a time, graded when its last turn ends."""
