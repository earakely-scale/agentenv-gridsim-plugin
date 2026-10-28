"""Write data/desk/fixtures-env: the desk env's fixture pack (gridsim_core.desk.fixtures), which the env image carries
for the gridsim-desk bundle's tasks and scripts/desk_e2e.py: a post-RTC+B outage day, a quiet one and a pre-RTC+B day.

    python tests/env_desk/make_fixture_pack.py
"""

import gzip
import json
from pathlib import Path

from gridsim_core.desk import fixtures

OUT = Path(__file__).resolve().parents[2] / "data/desk/fixtures-env"
DAYS = [{"seed": 3, "outage": True}, {"seed": 1}, {"date": "2025-08-14", "seed": 2}]


def main() -> None:
    (OUT / "series").mkdir(parents=True, exist_ok=True)
    rows = []
    for kw in DAYS:
        task, series = fixtures.make(**kw)
        task["pack"] = OUT.name
        rows.append(task)
        with gzip.GzipFile(OUT / task["series"], "wb", mtime=0) as f:
            f.write(json.dumps(series).encode())
    with gzip.GzipFile(OUT / "tasks.jsonl.gz", "wb", mtime=0) as f:
        f.write("".join(json.dumps(t) + "\n" for t in rows).encode())
    print("\n".join(f"{t['task_id']} {t['era']}" for t in rows))


if __name__ == "__main__":
    main()
