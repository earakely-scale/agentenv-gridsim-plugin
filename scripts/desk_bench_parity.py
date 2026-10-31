"""Play one desk task of a desk bench bundle with a core policy ($0) through the framework's Episode API, with
scripts/desk_e2e.py's byte-for-byte checks against the in-process Session: the bench bundle's own env (built where it
deploys from the desk-v4-freeze tree) and its hook entry, the played agent in place of the harness.

    python scripts/desk_bench_parity.py --pack desk-v4-pilot --task desk-v4-2026-02-03-S01 --policy anchor
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import desk_bench  # noqa: E402
import desk_e2e  # noqa: E402

from gridsim_core.desk import load_series, load_task, policies  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.partition("\n\n")[0])
    ap.add_argument("--harness", default="codex-luna", choices=sorted(desk_bench.HARNESSES))
    ap.add_argument("--pack", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--policy", choices=list(policies.POLICIES), default="anchor")
    ap.add_argument("--reminder", default="D0 14:35", help="a reminder the first turn sets ('' for none)")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    task = load_task(a.pack, a.task)
    series = load_series(a.pack, task)
    with tempfile.TemporaryDirectory() as tmp:
        bundle = Path(tmp)
        desk_bench.write(a.harness, a.pack, bundle, [a.task])
        path = bundle / "tasks" / f"{a.task}.json"
        steps = [s for s in json.loads(path.read_text()) if s["id"] != "harness-config"]
        for step in steps:
            if step["type"] == "deploy_agent":
                step.pop("a2a_agent_id", None)
                step.pop("network_policy", None)
        path.write_text(json.dumps(steps, indent=2, ensure_ascii=False) + "\n")
        report = asyncio.run(desk_e2e.run(bundle, a.task, task, series, a.policy, None, a.reminder or None))
    if a.out:
        a.out.write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(json.dumps({k: report[k] for k in ("instance", "reward", "scores", "calls", "seconds", "problems")},
                     indent=1, default=str))
    for w in report["wakes"]:
        print(f"  turn {w['turn']:>2}  {w['now']}  {','.join(w['reasons'])}  turns_left {w['turns_left']}")
    if report["problems"]:
        sys.exit(f"{len(report['problems'])} problems")


if __name__ == "__main__":
    main()
