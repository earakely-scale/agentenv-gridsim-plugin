"""The windows the Space serves: the v4 benchmark's desk pack (copied without the real site and operator names, design
decision D9), each window's public card, the observed weather its 3D site shows and the benchmark's grades on it, all
written by scripts/hub_openenv.py."""

import json
import os
from functools import cache
from pathlib import Path

from gridsim_core.desk import load_series, load_tasks

ROOT = Path(__file__).resolve().parents[1]


class Windows:
    def __init__(self, data: Path):
        meta = json.loads((data / "windows.json").read_text())
        self.pack = data / meta["pack"]
        self.split = meta["split"]
        self.tasks = {t["task_id"]: t for t in load_tasks(str(self.pack))}
        self.order = meta["order"]
        self.cards = meta["windows"]
        self.scenes = meta["scenes"]
        self.bench = meta["bench"]
        self.models = meta["models"]
        self.default = meta["default"]

    def splits(self) -> list[str]:
        return [self.split]

    def ids(self, split: str) -> list[str]:
        if split != self.split:
            raise IndexError(f"there is no split {split!r}; the split is {self.split!r}")
        return self.order

    def at(self, split: str, index: int) -> str:
        ids = self.ids(split)
        if not 0 <= index < len(ids):
            raise IndexError(f"split {split!r} has {len(ids)} windows, so it has no window {index}")
        return ids[index]

    def series(self, task_id: str) -> dict:
        return load_series(str(self.pack), self.tasks[task_id])


@cache
def windows() -> Windows:
    return Windows(Path(os.environ.get("GRIDSIM_DATA") or ROOT / "data"))
