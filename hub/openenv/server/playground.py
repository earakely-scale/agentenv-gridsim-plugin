"""OpenEnv's MCP playground with an episode per visitor: OpenEnv's own page (build_gradio_app) on a manager that hands
each Gradio session its own WebInterfaceManager, so one visitor's reset never ends another's episode. Sessions idle
past IDLE_S are closed, and past CAP the longest idle goes first."""

import os
import threading
import time
from collections import OrderedDict

from gradio.context import LocalContext
from openenv.core.env_server.web_interface import WebInterfaceManager

CAP = int(os.environ.get("PLAYGROUND_SESSIONS", "48"))
IDLE_S = float(os.environ.get("SESSION_IDLE_S", "1200"))


class PerVisitor:
    def __init__(self, factory, action_cls, observation_cls, metadata):
        self.factory, self.action_cls, self.observation_cls = factory, action_cls, observation_cls
        self.metadata = metadata
        self.env = factory()
        self.managers: OrderedDict[str, tuple[WebInterfaceManager, float]] = OrderedDict()
        self.lock = threading.Lock()

    def mine(self) -> WebInterfaceManager:
        request = LocalContext.request.get(None)
        key = getattr(request, "session_hash", None) or "shared"
        now = time.monotonic()
        with self.lock:
            stale = [k for k, (_, seen) in self.managers.items() if now - seen > IDLE_S and k != key]
            while len(self.managers) - len(stale) >= CAP and key not in self.managers:
                stale.append(next(k for k in self.managers if k not in stale))
            for k in stale:
                gone = self.managers.pop(k)[0]
                gone.env.close()
                gone._executor.shutdown(wait=False)
            manager = self.managers.pop(key, (None, 0.0))[0] or WebInterfaceManager(
                self.factory, self.action_cls, self.observation_cls, self.metadata)
            self.managers[key] = (manager, now)
        return manager

    async def reset_environment(self, reset_kwargs=None):
        return await self.mine().reset_environment(reset_kwargs)

    async def step_environment(self, action_data):
        return await self.mine().step_environment(action_data)

    def get_state(self):
        return self.mine().get_state()
