"""The play page (/play/, embedded in the Try Environment tab) and the read-only JSON it reads besides the env's own
WebSocket session:

    /api/windows                 the windows' public cards, in the split's order, and the benchmark's models
    /api/episodes/{episode}      one live episode's view (GridSimDeskEnvironment.view), by the unguessable id its
                                 reset returned; nothing lists live episodes
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from .environment import LIVE
from .windows import windows

WEB = Path(__file__).resolve().parent / "web"


def mount_viewer(app: FastAPI) -> None:
    @app.get("/api/windows", tags=["Viewer"])
    def window_cards():
        w = windows()
        return {"split": w.split, "default": w.default, "windows": [w.cards[t] for t in w.order],
                "models": w.models}

    @app.get("/api/episodes/{episode}", tags=["Viewer"])
    def episode_view(episode: str):
        env = LIVE.get(episode)
        if env is None or env.s is None:
            raise HTTPException(404, "unknown or closed episode")
        return env.view()

    @app.get("/play", include_in_schema=False)
    def play_slash():
        return RedirectResponse("/play/")

    app.mount("/play", StaticFiles(directory=str(WEB), html=True), name="play")
