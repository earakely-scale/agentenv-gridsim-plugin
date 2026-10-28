"""A one-task desk pack folder, as the env loads packs."""

import gzip
import json


def pack(tmp_path, task, series):
    (tmp_path / "series").mkdir()
    with gzip.open(tmp_path / "tasks.jsonl.gz", "wt") as f:
        f.write(json.dumps(task) + "\n")
    with gzip.open(tmp_path / task["series"], "wt") as f:
        json.dump(series, f)
    return str(tmp_path)
