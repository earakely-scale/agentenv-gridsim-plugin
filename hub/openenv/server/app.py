"""The GridSimEnv Desk Space: OpenEnv's server for the desk (/reset, /step, /state, /schema, /ws, /mcp, /health and the
Task API under /gridsim_desk/...), its page at /web with two tabs, Try Environment (play a window by hand beside the
battery site in 3D) and OpenEnv's MCP playground with an episode per visitor, and the play page's JSON under /api.

    uvicorn server.app:app --port 8000 --ws-ping-interval 60 --ws-ping-timeout 600
"""

import os

import gradio as gr
import uvicorn
from openenv.core.env_server.gradio_ui import build_gradio_app
from openenv.core.env_server.http_server import create_app
from openenv.core.env_server.mcp_types import CallToolAction, CallToolObservation
from openenv.core.env_server.types import ConcurrencyConfig
from starlette.responses import Response

from .environment import ENV_NAME, DeskState, GridSimDeskEnvironment
from .playground import IDLE_S, PerVisitor
from .ui import build_try
from .viewer import mount_viewer
from .windows import windows

TITLE = "GridSimEnv Playground"
ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="4" y="9" width="22" height="14" rx="3" '
        'fill="none" stroke="#14202b" stroke-width="2.5"/><rect x="27" y="13" width="3" height="6" rx="1" '
        'fill="#14202b"/><rect x="7" y="12" width="11" height="8" rx="1" fill="#10855a"/></svg>')
MAX_SESSIONS = int(os.environ.get("MAX_CONCURRENT_ENVS", "32"))


def create_server():
    w = windows()

    def builder(web_manager, action_fields, metadata, is_chat_env, title, quick_start_md):
        visitors = PerVisitor(GridSimDeskEnvironment, web_manager.action_cls, web_manager.observation_cls, metadata)
        playground = build_gradio_app(visitors, action_fields, metadata, is_chat_env, title=metadata.name,
                                      quick_start_md=installable(quick_start_md))
        return gr.TabbedInterface([build_try(), playground], ["Try Environment", "Playground"], title=TITLE)

    os.environ.setdefault("ENABLE_WEB_INTERFACE", "true")
    app = create_app(GridSimDeskEnvironment, CallToolAction, CallToolObservation, env_name=ENV_NAME,
                     concurrency_config=ConcurrencyConfig(max_concurrent_envs=MAX_SESSIONS, session_timeout=IDLE_S),
                     gradio_builder=builder, show_default_tab=False, title_override=TITLE, state_cls=DeskState)
    mount_viewer(app)

    @app.get("/manifest.json", include_in_schema=False)
    def manifest():
        return {"name": TITLE, "short_name": "GridSimEnv Playground", "start_url": "/web/", "display": "standalone",
                "icons": [{"src": "/favicon.ico", "sizes": "any", "type": "image/svg+xml"}]}

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(ICON, media_type="image/svg+xml")

    @app.get("/healthz", include_in_schema=False)
    def healthz():
        return {"status": "ok", "windows": {s: len(w.ids(s)) for s in w.splits()}}

    return app


def installable(md: str) -> str:
    """pip installs a git URL from a partial clone, which Hugging Face's git server cannot complete, so the quick start
    clones the Space and installs the folder."""
    space = os.environ.get("SPACE_ID", "")
    return md.replace(f"pip install git+https://huggingface.co/spaces/{space}",
                      f"git clone https://huggingface.co/spaces/{space}\npip install ./{space.split('/')[-1]}")


def __getattr__(name: str):
    if name == "app":
        globals()["app"] = create_server()
        return globals()["app"]
    raise AttributeError(name)


def main(host: str = "0.0.0.0", port: int | None = None) -> None:
    uvicorn.run(create_server(), host=host, port=port or int(os.environ.get("PORT", "8000")), ws_ping_interval=60,
                ws_ping_timeout=600)


if __name__ == "__main__":
    main()
