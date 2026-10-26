"""Pipeline-check gate (prereg v1-confirm-sft10k): both sampled means inside run 2's committed 95% CIs, valid >= 98%."""

import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
bars = {"sft": [0.802, 0.877], "trained": [0.789, 0.860]}
out = {}
for label, (lo, hi) in bars.items():
    s = next(r for r in json.loads((d / f"eval_{label}.json").read_text())["runs"] if r["decoding"] == "sampled")
    m, v = s["summary"]["reward_mean"], s["summary"]["valid_rate"]
    out[label] = {"reward_mean": m, "valid_rate": v, "run2_ci95": [lo, hi], "pass": lo <= m <= hi and v >= 0.98}
out["pass"] = all(x["pass"] for x in out.values())
(d / "gate.json").write_text(json.dumps(out, indent=1))
print(json.dumps(out), flush=True)
sys.exit(0 if out["pass"] else 1)
